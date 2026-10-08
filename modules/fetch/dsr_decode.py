"""Decode Power BI DSR (data shape result) responses from the EDAP P3DH report.

The P3DH query returns a tree of nested groups (one level per dimension, DM0..DMn).
Each group node carries a schema ("S"), the value of its dimension ("G<n>") and two
bit masks: "R" (value repeated from the previous node at the same level) and "O"
(null). Leaf nodes carry measure items ("X") with the same masks.
Values of dictionary-encoded dimensions are indexes into "ValueDicts".

The decoder walks the tree in document order and keeps the last value of every
column, so repeated and null values are decoded exactly. Field names come from the
query descriptor, so the decoder does not depend on a fixed column order.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

NULL_MASK_KEYS = ("Ø", "O")  # "Ø" in the Power BI protocol


class ResponseError(RuntimeError):
    """The portal answered HTTP 200 but the body is an error (for example a DAX timeout)."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _mask(node: dict[str, Any], keys: tuple[str, ...]) -> int:
    for key in keys:
        if key in node:
            return int(node[key])
    return 0


def _field_name(select_name: str) -> str:
    """'dm_Cell.CellCode' -> 'cell_code'; 'Measure P3.FactValue' -> 'fact_value'."""
    prop = select_name.split(".", 1)[-1]
    prop = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", prop)
    return re.sub(r"[^0-9a-zA-Z]+", "_", prop).strip("_").lower()


_NUMBER = re.compile(r"^-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?[DLM]?$")


def _parse_measure(raw: Any) -> Any:
    """Numbers are floats; quoted strings ('text') are text facts; booleans are kept."""
    if isinstance(raw, str):
        if len(raw) >= 2 and raw[0] == "'" and raw[-1] == "'":
            return raw[1:-1].replace("''", "'")
        if _NUMBER.match(raw):
            return float(raw.rstrip("DLM"))
        return raw
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return float(raw)
    return raw


def descriptor_fields(response: dict[str, Any]) -> dict[str, str]:
    """Map column id ('G5', 'M0') to a field name using the query descriptor."""
    data = response["results"][0]["result"]["data"]
    fields: dict[str, str] = {}
    for sel in data.get("descriptor", {}).get("Select", []):
        value = sel.get("Value")
        name = sel.get("Name", "")
        if value:
            fields[value] = _field_name(name)
    return fields


def decode_response(response: dict[str, Any], strict: bool = True) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return (rows, info). Each row maps field name -> value, plus 'fact_value'.

    Raises ResponseError for an error body, a malformed body, and (if strict) for decoding
    anomalies: a repeat bit with no earlier value, or a dictionary reference that cannot be
    resolved. Without strict, the anomalies are only counted in info['anomalies'].

    info has: 'complete' (False if the response carries a restart token),
    'n_leaves', 'fields', 'header' (values from the SH header such as reference date).
    """
    try:
        data = response["results"][0]["result"]["data"]
        dsr = data["dsr"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ResponseError("malformed_response", f"missing {exc!r} in the response body") from exc
    if "DS" not in dsr:
        shapes = dsr.get("DataShapes") or [{}]
        err = shapes[0].get("odata.error", {})
        details = " | ".join(str(d.get("details", "")) for d in err.get("azure:values", []) if "details" in d)
        raise ResponseError(err.get("code", "unknown_response_shape"),
                            f"{err.get('message', {}).get('value', '')} {details}".strip())
    if not dsr["DS"]:
        raise ResponseError("malformed_response", "empty DS list")
    ds = dsr["DS"][0]
    fields = descriptor_fields(response)
    value_dicts = ds.get("ValueDicts", {})
    schemas: dict[str, list[dict[str, Any]]] = {}
    state: dict[str, Any] = {}
    header: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []
    measure_ids = [k for k in fields if k.startswith("M")] or ["M0"]
    null_measures = 0
    anomalies = {"repeat_without_value": 0, "bad_dictionary_reference": 0}

    def resolve(col: dict[str, Any], raw: Any) -> Any:
        dn = col.get("DN")
        if dn is not None and isinstance(raw, int) and not isinstance(raw, bool):
            values = value_dicts.get(dn)
            if values is not None and 0 <= raw < len(values):
                return values[raw]
            anomalies["bad_dictionary_reference"] += 1
        if col.get("T") == 7 and isinstance(raw, (int, float)):
            return datetime.fromtimestamp(raw / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        return raw

    def apply_columns(level: str, node: dict[str, Any], measure: bool = False) -> None:
        if "S" in node and isinstance(node["S"], list):
            schemas[level] = node["S"]
        cols = schemas.get(level, [])
        repeat = _mask(node, ("R",))
        null = _mask(node, NULL_MASK_KEYS)
        for i, col in enumerate(cols):
            name = col["N"]
            if repeat >> i & 1:
                if name not in state:
                    anomalies["repeat_without_value"] += 1
                continue  # value repeated from the previous node at this level
            if null >> i & 1 or name not in node:
                state[name] = None
                continue
            raw = node[name]
            state[name] = _parse_measure(resolve(col, raw)) if measure else resolve(col, raw)

    def emit() -> None:
        row = {fields.get(k, k): v for k, v in state.items() if k not in header_ids}
        rows.append(row)

    for sh in ds.get("SH", []):
        for key, nodes in sh.items():
            if key.startswith("DM"):
                for node in nodes:
                    apply_columns(key, node)
        header.update({fields.get(k, k): v for k, v in state.items()})
    header_ids = set(state)

    def walk(node: dict[str, Any], level: str) -> None:
        apply_columns(level, node)
        nonlocal null_measures
        for item in node.get("X", []):
            apply_columns(level + ".X", item, measure=True)
            if all(state.get(m) is None for m in measure_ids):
                null_measures += 1  # a cell without a value is not a fact
                continue
            emit()
        for member in node.get("M", []):
            for key, children in member.items():
                if key.startswith("DM"):
                    for child in children:
                        walk(child, key)

    for ph in ds.get("PH", []):
        for key, nodes in ph.items():
            if key.startswith("DM"):
                for node in nodes:
                    walk(node, key)

    if strict and any(anomalies.values()):
        raise ResponseError("decoding_anomaly", f"{anomalies}")
    info = {
        "anomalies": anomalies,
        "complete": "RT" not in ds,
        "restart_tokens": ds.get("RT"),
        "n_leaves": len(rows),
        "null_measures": null_measures,
        "fields": fields,
        "header": header,
    }
    return rows, info
