"""Pull the external statistics into the database. One request for each indicator gives all countries.

  pull(conn)                          every indicator of specs.SPECS
  pull(conn, only=["bsi_loans_nfc"])  chosen indicators
An indicator that fails does not stop the others. A blank value (the source holds it back for confidentiality) is not stored.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import sqlite3
from typing import Callable

from . import schema
from .http import NoData, fetch
from .keys import concept_of
from .specs import COUNTRIES, ECB_AREAS, EURO_AREA, EUROSTAT_CODE, GEO_GROUPS, SPECS, Spec

ECB_URL = "https://data-api.ecb.europa.eu/service/data"
EUROSTAT_URL = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
ISO = {c[0] for c in COUNTRIES} | {EURO_AREA}
UNIT_MULT = {"eur_th": 3, "eur_m": 6}
QUARTER_END = {"1": "03-31", "2": "06-30", "3": "09-30", "4": "12-31"}


def period_end(period: str) -> str:
    """Last day of a period written as 2025, 2026-Q2, 2025-S1, 2026-08, or 2026-10-13."""
    p = period.strip()
    if len(p) == 4:
        return f"{p}-12-31"
    if "-Q" in p:
        y, q = p.split("-Q")
        return f"{y}-{QUARTER_END[q]}"
    if "-S" in p:
        y, s = p.split("-S")
        return f"{y}-06-30" if s == "1" else f"{y}-12-31"
    if len(p) == 7:
        y, m = int(p[:4]), int(p[5:7])
        nxt = dt.date(y + (m == 12), m % 12 + 1, 1)
        return (nxt - dt.timedelta(days=1)).isoformat()
    return p[:10]


def since_for(freq: str, year: int) -> str:
    return {"A": f"{year}", "Q": f"{year}-Q1", "M": f"{year}-01", "D": f"{year}-01-01"}[freq]


def seed_countries(conn: sqlite3.Connection) -> None:
    rows = [(iso, name, ea, iso, EUROSTAT_CODE.get(iso, iso)) for iso, name, ea in COUNTRIES] + [(EURO_AREA, "Euro area", 1, EURO_AREA, "EA")]
    conn.executemany("INSERT OR REPLACE INTO ext_country VALUES (?, ?, ?, ?, ?)", rows)
    if not conn.execute("SELECT 1 FROM ext_geo_group LIMIT 1").fetchone():  # the groups are seeded once; the user can edit the table
        conn.executemany("INSERT OR IGNORE INTO ext_geo_group VALUES (?, ?)", [(g, c) for g, cs in GEO_GROUPS.items() for c in cs])


# ------------------------------------------------------------------------------------------------ ECB
def ecb_url(spec: Spec, since: int) -> str:
    key = spec.key.replace("{A}", "+".join(ECB_AREAS))
    return f"{ECB_URL}/{spec.dataset}/{key}?startPeriod={since_for(spec.freq, since)}&format=csvdata"


def parse_ecb(text: str, spec: Spec) -> list[dict]:
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        value = (r.get("OBS_VALUE") or "").strip()
        area = r.get("REF_AREA") or (EURO_AREA if spec.euro_area_only else "")
        if not value or area not in ISO:
            continue
        indicator = f"{spec.indicator}_{r[spec.indicator_col]}" if spec.indicator_col else spec.indicator
        rows.append({"key": r["KEY"], "indicator": indicator, "area": area, "title": r.get("TITLE") or r.get("TITLE_COMPL") or "", "period": r["TIME_PERIOD"], "value": float(value), "status": r.get("OBS_STATUS") or ""})
    return rows


# ------------------------------------------------------------------------------------------------ Eurostat
def eurostat_url(spec: Spec, since: int) -> str:
    return f"{EUROSTAT_URL}/{spec.dataset}?format=JSON&lang=en&{spec.key}&sinceTimePeriod={since_for(spec.freq, since)}"


def _categories(dim: dict) -> dict[int, str]:
    index = dim["category"]["index"]
    return {pos: code for code, pos in index.items()} if isinstance(index, dict) else dict(enumerate(index))


def parse_eurostat(text: str, spec: Spec) -> list[dict]:
    """JSON-stat: the values are in one list that runs over the dimensions, the last dimension (time) fastest."""
    j = json.loads(text)
    if "error" in j:
        raise RuntimeError(f"Eurostat: {str(j['error'])[:200]}")
    ids, sizes, dims = j["id"], j["size"], j["dimension"]
    cats = {d: _categories(dims[d]) for d in ids}
    geos = set(cats["geo"].values())
    euro = sorted((g for g in geos if g.startswith("EA") and g[2:].isdigit()), key=lambda g: -int(g[2:]))
    to_iso = {EUROSTAT_CODE.get(i, i): i for i, _, _ in COUNTRIES}
    if euro:
        to_iso[euro[0]] = EURO_AREA  # the newest euro area aggregate, for example EA21
    values = j.get("value", {})
    values = values.items() if isinstance(values, dict) else enumerate(values)
    status = j.get("status", {})
    rows = []
    for k, v in values:
        if v is None:
            continue
        i, coords = int(k), []
        for size in reversed(sizes):
            coords.append(i % size)
            i //= size
        coords.reverse()
        pos = dict(zip(ids, coords))
        area = to_iso.get(cats["geo"][pos["geo"]])
        if area is None:
            continue
        other = [cats[d][pos[d]] for d in ids if d not in ("geo", "time")]
        flag = status.get(str(k), "") if isinstance(status, dict) else (status[int(k)] if int(k) < len(status) else "")
        rows.append({"key": f"ESTAT.{spec.dataset}." + ".".join(other + [area]), "indicator": spec.indicator, "area": area, "title": j.get("label", spec.desc),
                     "period": cats["time"][pos["time"]], "value": float(v), "status": flag or ""})
    return rows


# ------------------------------------------------------------------------------------------------ storage
def store(conn: sqlite3.Connection, spec: Spec, rows: list[dict], now: str) -> tuple[int, int]:
    series: dict[str, dict] = {}
    for r in rows:
        series.setdefault(r["key"], r)
    def concept(k: str, r: dict) -> tuple[str, str]:
        if spec.source == "ecb":
            return concept_of(k, r["area"])
        return r["indicator"], spec.dataset

    conn.executemany("""INSERT INTO ext_series (source, series_key, indicator, ref_area, freq, unit, title, pulled_at, concept, flow, unit_mult) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(source, series_key) DO UPDATE SET indicator = excluded.indicator, ref_area = excluded.ref_area, freq = excluded.freq, unit = excluded.unit,
                        title = excluded.title, pulled_at = excluded.pulled_at, concept = excluded.concept, flow = excluded.flow, unit_mult = excluded.unit_mult""",
                     [(spec.source, k, r["indicator"], r["area"], spec.freq, spec.unit, r["title"], now, *concept(k, r), UNIT_MULT.get(spec.unit)) for k, r in series.items()])
    conn.executemany("INSERT OR REPLACE INTO ext_obs VALUES (?, ?, ?, ?, ?, ?)", [(spec.source, r["key"], r["period"], period_end(r["period"]), r["value"], r["status"]) for r in rows])
    conn.execute(f"""UPDATE ext_series SET first_period = (SELECT MIN(period_end) FROM ext_obs o WHERE o.source = ext_series.source AND o.series_key = ext_series.series_key),
                     last_period = (SELECT MAX(period_end) FROM ext_obs o WHERE o.source = ext_series.source AND o.series_key = ext_series.series_key),
                     n_obs = (SELECT COUNT(*) FROM ext_obs o WHERE o.source = ext_series.source AND o.series_key = ext_series.series_key)
                     WHERE source = ? AND series_key IN ({','.join('?' * len(series))})""", [spec.source, *series]) if series else None
    return len(series), len(rows)


def backfill_concepts(conn: sqlite3.Connection) -> int:
    """Concept, flow, and unit multiplier of the series that were stored before these columns existed."""
    todo = conn.execute("SELECT source, series_key, ref_area, indicator, unit FROM ext_series WHERE concept IS NULL").fetchall()
    rows = []
    for source, key, area, indicator, unit in todo:
        concept, flow = concept_of(key, area) if source == "ecb" else (indicator, key.split(".")[1] if key.startswith("ESTAT.") else "")
        rows.append((concept, flow, UNIT_MULT.get(unit), source, key))
    conn.executemany("UPDATE ext_series SET concept = ?, flow = ?, unit_mult = ? WHERE source = ? AND series_key = ?", rows)
    conn.commit()
    return len(rows)


def pull(conn: sqlite3.Connection, fetcher: Callable[[str], str] = fetch, only: list[str] | None = None, since: int = 2010, log: Callable[[str], None] = print) -> dict:
    schema.create(conn)
    seed_countries(conn)
    backfill_concepts(conn)
    summary: dict = {"ok": {}, "failed": {}}
    for spec in SPECS:
        if only and not any(spec.indicator == o or spec.indicator.startswith(o) or spec.group == o or spec.source == o for o in only):
            continue
        now = dt.datetime.now().isoformat(timespec="seconds")
        try:
            url = ecb_url(spec, since) if spec.source == "ecb" else eurostat_url(spec, since)
            rows = (parse_ecb if spec.source == "ecb" else parse_eurostat)(fetcher(url), spec)
            n_series, n_obs = store(conn, spec, rows, now)
            status, detail = "ok", ""
            summary["ok"][spec.indicator] = (n_series, n_obs)
        except NoData:
            n_series = n_obs = 0
            status, detail = "no data", "the source has no series for this request"
            summary["failed"][spec.indicator] = detail
        except Exception as e:  # noqa: BLE001 - one indicator must not stop the others
            n_series = n_obs = 0
            status, detail = "failed", f"{type(e).__name__}: {e}"[:300]
            summary["failed"][spec.indicator] = detail
        conn.execute("INSERT INTO ext_pull_log (started_at, indicator, source, n_series, n_obs, status, detail) VALUES (?, ?, ?, ?, ?, ?, ?)", (now, spec.indicator, spec.source, n_series, n_obs, status, detail))
        conn.commit()
        log(f"  {spec.indicator:18s} {status:8s} {n_series:4d} series {n_obs:7d} observations {detail}")
    return summary
