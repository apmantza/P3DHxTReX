"""Download one P3DH template for one reference date, decode it and store it.

Flow per template:
1. Fetch the whole template with restart-token paging. Page n+1 repeats the group that
   page n cut off, so the overlap is removed. This needs no entity list.
2. If paging fails, split the entity list into batches. A batch whose response is
   truncated (restart token) or fails is split in halves. A single entity that is still
   truncated is recorded as truncated and the template is marked partial.
3. Re-fetch a few entities by name and compare their facts with the paged result.
4. Validate every response (reference date, template code), decode it with
   modules.fetch.dsr_decode and write a CSV plus the raw responses (gzip JSON lines).

A template whose first requests all fail is marked failed_server so that the run does not
spend hours on it. A server-side query timeout (rsQueryTimeoutExceeded) is final: a smaller
entity batch does not help.
"""

from __future__ import annotations

import collections
import gzip
import hashlib
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from modules.fetch.dsr_decode import ResponseError, decode_response

log = logging.getLogger(__name__)

DECODER_VERSION = 3
WINDOW = 30000  # largest primary window Power BI honours (40000 is ignored -> 500 rows)
OUT_COLUMNS = [
    "reference_date", "entity_lei", "entity_name", "country", "module_name",
    "module_code", "cell_code", "key_descriptor", "template", "row_code",
    "row_label", "column_code", "column_label", "sheet", "fact_value", "fact_text", "fact_type",
]
FIELD_MAP = {
    "entity_code": "entity_lei",
    "ent_nam": "entity_name",
    "row": "row_code",
    "column": "column_code",
    "header_label": "sheet",
}
ABORT_AFTER_FAILURES = 4
FACT_KEY = ("entity_code", "ent_nam", "cell_code", "key_descriptor", "row", "column", "header_label")


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def build_query(base_query: dict[str, Any], template: str, window: int = WINDOW) -> dict[str, Any]:
    """Copy of the captured query for one template with a large primary data window.

    The captured visual query has Primary.Window.Count=100 and Secondary.Top.Count=100.
    If the product of all counts exceeds 25M intersections Power BI ignores the counts and
    returns only 500 rows. Keeping the secondary count at 1 lets the window go up to
    about 30000 leaf rows.
    """
    query = json.loads(json.dumps(base_query))
    cmd = query["queries"][0]["Query"]["Commands"][0]["SemanticQueryDataShapeCommand"]
    for where in cmd["Query"].get("Where", []):
        cond = where.get("Condition", {}).get("In")
        if cond and cond["Expressions"][0].get("Column", {}).get("Property") == "Template":
            cond["Values"] = [[{"Literal": {"Value": f"'{template}'"}}]]
    reduction = cmd["Binding"]["DataReduction"]
    reduction["Primary"]["Window"]["Count"] = window
    reduction["Secondary"]["Top"]["Count"] = 1
    return query


def multi_entity_query(base_query: dict[str, Any], entities: list[str]) -> dict[str, Any]:
    """Copy of the query with an entity filter on one or more entity names."""
    query = json.loads(json.dumps(base_query))
    cmd = query["queries"][0]["Query"]["Commands"][0]["SemanticQueryDataShapeCommand"]
    values = [[{"Literal": {"Value": "'" + name.replace("'", "''") + "'"}}] for name in entities]
    cmd["Query"].setdefault("Where", []).append(
        {
            "Condition": {
                "In": {
                    "Expressions": [
                        {
                            "Column": {
                                "Expression": {"SourceRef": {"Source": "d1"}},
                                "Property": "ENT_NAM",
                            }
                        }
                    ],
                    "Values": values,
                }
            }
        }
    )
    return query


def set_restart_tokens(query: dict[str, Any], tokens: Any) -> dict[str, Any]:
    q = json.loads(json.dumps(query))
    cmd = q["queries"][0]["Query"]["Commands"][0]["SemanticQueryDataShapeCommand"]
    cmd["Binding"]["DataReduction"]["Primary"]["Window"]["RestartTokens"] = tokens
    return q


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------

def _clean(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("\xa0", " ").strip()
    return value


def to_records(rows: list[dict[str, Any]], date_iso: str) -> list[dict[str, Any]]:
    """Rename decoder fields to the output schema. Responses were validated for date_iso."""
    records = []
    for row in rows:
        rec = {FIELD_MAP.get(k, k): _clean(v) for k, v in row.items()}
        rec["reference_date"] = date_iso
        value = rec.pop("fact_value", None)
        if isinstance(value, float):
            rec["fact_value"], rec["fact_text"], rec["fact_type"] = repr(value), "", "number"
        else:
            rec["fact_value"], rec["fact_text"], rec["fact_type"] = "", "" if value is None else str(value), "text"
        records.append({col: rec.get(col) for col in OUT_COLUMNS})
    return records


def validate(rows: list[dict[str, Any]], info: dict[str, Any], date_iso: str, code: str) -> None:
    """Raise ValueError if the response is not for the requested date and template."""
    ref = info["header"].get("reference_date")
    if ref and ref != date_iso:
        raise ValueError(f"response reference date {ref} != requested {date_iso}")
    bad = {r.get("template") for r in rows if not str(r.get("template") or "").startswith(code)}
    if bad:
        raise ValueError(f"response contains other templates: {sorted(map(str, bad))[:3]}")


def _row_tuple(row: dict[str, Any]) -> tuple:
    return tuple(sorted((k, str(v)) for k, v in row.items()))


def drop_page_overlap(prev: list[dict[str, Any]], new: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Remove the head of `new` that repeats the tail of `prev` (the group a page cut off).

    Only an exact sequence match of whole rows is removed, so repeated facts that really
    occur twice (for example identical texts in an open table) are kept.
    """
    limit = min(len(prev), len(new))
    if not limit:
        return new, 0
    prev_t = [_row_tuple(r) for r in prev[-limit:]]
    new_t = [_row_tuple(r) for r in new[:limit]]
    first = new_t[0]
    for k in range(limit, 0, -1):
        if prev_t[-k] == first and prev_t[-k:] == new_t[:k]:
            return new[k:], k
    return new, 0


def fact_key(row: dict[str, Any]) -> tuple:
    return tuple(row.get(k) for k in FACT_KEY)


def keyed_duplicates(rows: list[dict[str, Any]]) -> tuple[int, int]:
    """Count repeated natural keys among facts with a concrete cell code, and how many differ.

    Facts without a cell code (open-table labels) and open-table cells with a wildcard row
    (r*) are not unique by design, so they are skipped.
    """
    seen: dict[tuple, Any] = {}
    dups = conflicts = 0
    for row in rows:
        cell = row.get("cell_code")
        if not cell or ", r*," in cell:
            continue
        key = fact_key(row)
        if key in seen:
            dups += 1
            conflicts += seen[key] != row.get("fact_value")
        else:
            seen[key] = row.get("fact_value")
    return dups, conflicts


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

class Fetcher:
    """Rate-limited query execution with the shared token manager."""

    def __init__(self, token, limiter, execute_query, polite_delay, delay_ms, timeout, retries):
        self.token = token
        self.limiter = limiter
        self._execute = execute_query
        self._delay = polite_delay
        self.delay_ms = delay_ms
        self.timeout = timeout
        self.retries = retries
        self._lock = threading.Lock()
        self.requests = 0

    def query(self, query: dict[str, Any], retries: int | None = None) -> dict[str, Any]:
        self._delay(self.delay_ms, self.limiter)
        with self._lock:
            self.requests += 1
        return self._execute(
            self.token.url, dict(self.token.headers), query,
            retries=retries or self.retries, timeout=self.timeout,
        )


def fetch_paged(fetcher: Fetcher, base: dict[str, Any], date_iso: str, code: str,
                max_pages: int = 500) -> tuple[list[dict[str, Any]], list[tuple[str, dict]], dict[str, int]]:
    """Fetch a whole template with restart-token paging (no entity list needed)."""
    rows: list[dict[str, Any]] = []
    responses: list[tuple[str, dict[str, Any]]] = []
    tokens = None
    overlap_total = 0
    boundaries: list[str] = []
    for page in range(1, max_pages + 1):
        query = base if tokens is None else set_restart_tokens(base, tokens)
        resp = fetcher.query(query, retries=2)
        decoded, info = decode_response(resp)
        validate(decoded, info, date_iso, code)
        if page > 1:
            if rows and rows[-1].get("ent_nam"):
                boundaries.append(rows[-1]["ent_nam"])
            decoded, dropped = drop_page_overlap(rows, decoded)
            overlap_total += dropped
        rows.extend(decoded)
        responses.append((f"page:{page}", resp))
        if info["complete"]:
            return rows, responses, {"pages": page, "overlap_rows_dropped": overlap_total,
                                     "boundary_entities": boundaries[:5]}
        if not info["restart_tokens"] or info["restart_tokens"] == tokens:
            raise RuntimeError("paging did not advance (no new restart token)")
        tokens = info["restart_tokens"]
    raise RuntimeError(f"more than {max_pages} pages")


def cross_check(fetcher: Fetcher, base: dict[str, Any], rows: list[dict[str, Any]],
                date_iso: str, code: str, sample: int, boundary: list[str] | None = None) -> dict[str, Any]:
    """Re-fetch a few entities by name and compare their facts with the paged result.

    The sample holds the entities where a page was cut (they test the overlap removal),
    NBG, and entities spread over the name list.
    """
    names = sorted({r["ent_nam"] for r in rows if r.get("ent_nam")})
    if not names or sample <= 0:
        return {"checked": 0}
    picks = set(boundary or [])
    picks |= {n for n in names if n.startswith("National Bank of Greece")}
    step = max(1, len(names) // max(1, sample))
    picks |= set(names[::step][:sample])
    picks = sorted(picks)
    resp = fetcher.query(multi_entity_query(base, picks), retries=2)
    other, info = decode_response(resp)
    validate(other, info, date_iso, code)
    if not info["complete"]:
        return {"checked": len(picks), "result": "inconclusive (batch truncated)"}
    mine = collections.Counter((fact_key(r), str(r.get("fact_value"))) for r in rows if r.get("ent_nam") in picks)
    theirs = collections.Counter((fact_key(r), str(r.get("fact_value"))) for r in other)
    return {"checked": len(picks), "facts": sum(mine.values()),
            "result": "ok" if mine == theirs else "MISMATCH",
            "only_paged": sum((mine - theirs).values()), "only_batch": sum((theirs - mine).values())}


def download_template(
    fetcher: Fetcher,
    template: str,
    code: str,
    get_entities: Callable[[], list[str]],
    date_iso: str,
    batch_size: int,
    workers: int,
    chunk_tasks: int = 8,
    cross_check_sample: int = 3,
) -> dict[str, Any]:
    """Return {'status', 'rows', 'responses', 'stats', ...} for one template.

    `get_entities` is called only if paging fails and the entity list is needed.
    """
    token = fetcher.token
    started = time.time()
    requests_before = fetcher.requests
    token.ensure_fresh()
    base = build_query(token.base_query, template)
    rows: list[dict[str, Any]] = []
    responses: list[tuple[str, dict[str, Any]]] = []
    stats: dict[str, Any] = {"mode": "paged", "template_level": None}
    failed: list[str] = []
    truncated: list[str] = []
    empty: list[str] = []
    processed: set[str] = set()
    lock = threading.Lock()
    counters = {"ok": 0, "err": 0, "split": 0, "batches": 0}
    abort = threading.Event()
    shared = {"size": max(1, batch_size)}

    # 1. paged fetch
    final_error = None
    try:
        paged, resps, page_stats = fetch_paged(fetcher, base, date_iso, code)
        rows.extend(paged)
        responses.extend(resps)
        stats.update(page_stats, template_level="complete")
    except ResponseError as exc:
        stats["template_level"] = f"error: {str(exc)[:120]}"
        if exc.code == "rsQueryTimeoutExceeded":
            final_error = str(exc)[:200]
    except Exception as exc:  # noqa: BLE001
        stats["template_level"] = f"error: {str(exc)[:120]}"

    # 2. fall back to entity batches
    def accept(label: str, resp: dict[str, Any], decoded: list[dict[str, Any]]) -> None:
        with lock:
            rows.extend(decoded)
            responses.append((label, resp))

    def run_single(entity: str) -> None:
        try:
            resp = fetcher.query(multi_entity_query(base, [entity]), retries=2)
            decoded, info = decode_response(resp)
            validate(decoded, info, date_iso, code)
        except Exception as exc:  # noqa: BLE001
            with lock:
                counters["err"] += 1
                failed.append(f"{entity} | {exc}")
            return
        with lock:
            counters["ok"] += 1
            processed.add(entity)
        if not decoded:
            with lock:
                empty.append(entity)
            return
        accept(entity, resp, decoded)
        if not info["complete"]:
            with lock:
                truncated.append(entity)

    def run_batch(batch: list[str]) -> None:
        if abort.is_set():
            return
        with lock:
            counters["batches"] += 1
        if len(batch) == 1:
            run_single(batch[0])
            return
        info = None
        try:
            resp = fetcher.query(multi_entity_query(base, batch))
            decoded, info = decode_response(resp)
            validate(decoded, info, date_iso, code)
        except Exception:  # noqa: BLE001
            info = None
            with lock:
                counters["err"] += 1
                give_up = counters["ok"] == 0 and counters["err"] >= ABORT_AFTER_FAILURES
            if give_up:
                abort.set()
                return
        if info is None or not info["complete"]:
            with lock:
                counters["split"] += 1
                if info is not None:
                    shared["size"] = max(1, min(shared["size"], len(batch) // 2))
            mid = len(batch) // 2
            run_batch(batch[:mid])
            run_batch(batch[mid:])
            return
        with lock:
            counters["ok"] += 1
            processed.update(batch)
        accept(f"batch:{len(batch)}", resp, decoded)
        seen = {r.get("ent_nam") for r in decoded}
        with lock:
            empty.extend(e for e in batch if e not in seen)

    if stats["template_level"] != "complete" and final_error is None:
        stats["mode"] = "partition"
        pending = list(get_entities())
        while pending and not abort.is_set():
            token.ensure_fresh()
            tasks = []
            for _ in range(chunk_tasks):
                if not pending:
                    break
                tasks.append(pending[: shared["size"]])
                pending = pending[shared["size"]:]
            with ThreadPoolExecutor(max_workers=workers) as ex:
                list(ex.map(run_batch, tasks))
            if counters["ok"] == 0 and counters["err"] + counters["split"] >= ABORT_AFTER_FAILURES:
                abort.set()
        stats["batch_size"] = batch_size
        stats["final_batch_size"] = shared["size"]
        listed = list(get_entities())
        for entity in listed:
            if entity not in processed and not any(f.startswith(entity + " |") for f in failed):
                failed.append(f"{entity} | not requested or failed")
        stats["entities_listed"] = len(listed)
        stats["detail"] = "entity-list fallback: the slicer list can miss entities, completeness not proven"

    # 3. checks
    if rows:
        dups, conflicts = keyed_duplicates(rows)
        stats["keyed_duplicates"], stats["keyed_conflicts"] = dups, conflicts
    if rows and stats["mode"] == "paged" and cross_check_sample:
        try:
            stats["cross_check"] = cross_check(fetcher, base, rows, date_iso, code, cross_check_sample,
                                               stats.get("boundary_entities"))
        except Exception as exc:  # noqa: BLE001
            stats["cross_check"] = {"result": f"error: {str(exc)[:80]}"}

    if final_error is not None and not rows:
        status = "failed_server"
        stats["detail"] = final_error
    elif abort.is_set() and not rows:
        status = "failed_server"
    elif not rows:
        # zero rows is "empty" only if the portal answered completely; an error is not empty
        status = "empty" if stats["template_level"] == "complete" else "failed_server"
    elif stats["mode"] == "partition" or failed or truncated or stats.get("keyed_conflicts") or \
            stats.get("cross_check", {}).get("result") == "MISMATCH":
        status = "partial"
    else:
        status = "complete"
    stats.update(
        requests=fetcher.requests - requests_before,
        seconds=round(time.time() - started, 1),
        entities_empty=len(empty),
        entities_failed=len(failed),
        entities_truncated=len(truncated),
    )
    return {"status": status, "rows": rows, "responses": responses, "stats": stats,
            "failed": failed, "truncated": truncated, "empty": empty}


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_outputs(
    result: dict[str, Any], code: str, date_folder: str, date_iso: str, raw_dir: Path, json_dir: Path
) -> dict[str, Any]:
    """Write the CSV and the raw JSON archive. Return facts about what was written."""
    frame = pd.DataFrame(to_records(result["rows"], date_iso), columns=OUT_COLUMNS)
    out_dir = raw_dir / date_folder
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{code}_data_points.csv"
    tmp = out.with_suffix(".csv.tmp")
    frame.to_csv(tmp, index=False, encoding="utf-8")
    tmp.replace(out)
    jdir = json_dir / date_folder
    jdir.mkdir(parents=True, exist_ok=True)
    jout = jdir / f"{code}.jsonl.gz"
    jtmp = jout.with_suffix(".gz.tmp")
    with gzip.open(jtmp, "wt", encoding="utf-8") as fh:
        for label, resp in result["responses"]:
            fh.write(json.dumps({"scope": label, "response": resp}, ensure_ascii=False) + "\n")
    jtmp.replace(jout)
    return {
        "csv": str(out), "json": str(jout), "rows": len(frame),
        "entities_with_rows": int(frame["entity_lei"].nunique()),
        "sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
    }


def rebuild_from_archive(json_path: Path, code: str, date_iso: str) -> list[dict[str, Any]]:
    """Decode every response of a template archive again. Use after a decoder change.

    Responses are read in the order they were saved. Paged archives drop the overlap
    between pages exactly as the download did.
    """
    rows: list[dict[str, Any]] = []
    with gzip.open(json_path, "rt", encoding="utf-8") as fh:
        for line in fh:
            item = json.loads(line)
            decoded, info = decode_response(item["response"])
            validate(decoded, info, date_iso, code)
            if item["scope"].startswith("page:") and item["scope"] != "page:1":
                decoded, _ = drop_page_overlap(rows, decoded)
            rows.extend(decoded)
    return rows


class Manifest:
    """Thread-safe JSON manifest, one file per reference date."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self.data: dict[str, Any] = {"decoder_version": DECODER_VERSION, "templates": {}}
        if path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))

    def get(self, code: str) -> dict[str, Any]:
        return self.data["templates"].get(code, {})

    def update(self, code: str, entry: dict[str, Any]) -> None:
        with self._lock:
            entry["updated_at"] = datetime.now().isoformat(timespec="seconds")
            entry.setdefault("decoder_version", DECODER_VERSION)
            self.data["templates"][code] = entry
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self.data, indent=1, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
