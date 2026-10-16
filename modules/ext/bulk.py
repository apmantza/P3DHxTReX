"""Bulk pull of complete ECB datasets with their full history.

The catalogue of a dataflow lists every series with its title and unit. A request for one country gives the observations of all its series (no titles: detail=dataonly keeps the answer small).
So a dataflow takes one request for the catalogue and one request for each country. A series of the catalogue without an observation in the request (other frequency, other fixed dimension, or all values held back) is not stored.

  pull_flow(conn, "MIR")                       every series of the euro area countries and the other EU countries, from 1999
  pull_flow(conn, "BSI", areas=["LU", "DE"])   chosen countries
A series that the curated pull (modules/ext/pull.py) has stored keeps its curated indicator name. A new series gets its concept as the indicator name.
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
from .pull import ECB_URL, ISO, period_end, seed_countries
from .specs import ECB_AREAS

# the dimensions to fix in the request (smaller answers) and a test that a series must pass
def national(r: dict) -> bool:
    """A property series of the whole country (REGION _T): the regional and capital city series are not comparable between countries."""
    return r.get("REGION") == "_T"


BULK: dict[str, dict] = {
    "MIR": {}, "BLS": {}, "SSI": {}, "SUP": {}, "CBD2": {},
    # balance sheet of the banks: sector MFIs excluding the central bank, monthly, all currencies together; stocks, growth rates, and transactions (flows).
    # Counterpart area: the euro area (U2) and its two parts, the country itself (U6) and the other euro area countries (U5). Lending outside the euro area is not in this data set.
    "BSI": {"fixed": {"FREQ": "M", "BS_REP_SECTOR": "A", "COUNT_AREA": "U2+U5+U6", "CURRENCY_TRANS": "Z01"}},
    "RAI": {},  # risk assessment indicators of the banking sector: lending margins, interbank share, leverage, loan-to-deposit, funding structure
    "IRS": {},  # long-term government bond yields (convergence criterion) and money market rates in local currency
    "RESR": {"keep": national},  # residential property prices (index and growth), whole country
    "RESH": {"keep": national},  # structural housing indicators, whole country
    "CLIFS": {},  # country-level index of financial stress
    "CISS": {},  # composite indicator of systemic stress (euro area) and of sovereign stress (large countries)
}
UNIT_MULT = {"EUR": 0}


def dimensions(columns: list[str]) -> list[str]:
    """The key dimensions: the columns between KEY and TIME_PERIOD."""
    return columns[1:columns.index("TIME_PERIOD")]


def read_catalogue(flow: str, fetcher: Callable[[str], str] = fetch) -> tuple[list[str], dict[str, dict]]:
    """Series of the flow for the EU countries and the euro area, with title and unit. Returns the dimensions and {key: row}."""
    text = fetcher(f"{ECB_URL}/{flow}?lastNObservations=1&format=csvdata")
    reader = csv.DictReader(io.StringIO(text))
    dims = dimensions(reader.fieldnames or [])
    keep = BULK[flow].get("keep")
    series = {r["KEY"]: r for r in reader if r.get("REF_AREA") in ISO and (keep is None or keep(r))}
    return dims, series


def area_url(flow: str, dims: list[str], area: str, since: int) -> str:
    fixed = BULK[flow].get("fixed", {})
    key = ".".join(area if d == "REF_AREA" else fixed.get(d, "") for d in dims)
    return f"{ECB_URL}/{flow}/{key}?startPeriod={since}&detail=dataonly&format=csvdata"


def pull_flow(conn: sqlite3.Connection, flow: str, since: int = 1999, areas: list[str] | None = None, fetcher: Callable[[str], str] = fetch, log: Callable[[str], None] = print) -> dict:
    if flow not in BULK:
        raise ValueError(f"unknown dataflow {flow}: {sorted(BULK)}")
    schema.create(conn)
    seed_countries(conn)
    now = dt.datetime.now().isoformat(timespec="seconds")
    dims, catalogue = read_catalogue(flow, fetcher)
    by_area: dict[str, int] = {}
    for r in catalogue.values():
        by_area[r["REF_AREA"]] = by_area.get(r["REF_AREA"], 0) + 1
    log(f"{flow}: {len(catalogue):,} series in the catalogue for {len(by_area)} countries; dimensions {dims}")
    total_obs = total_series = 0
    failed: dict[str, str] = {}
    for area in [a for a in ECB_AREAS if a in by_area and (not areas or a in areas)]:
        try:
            rows = list(csv.DictReader(io.StringIO(fetcher(area_url(flow, dims, area, since)))))
        except NoData:
            continue
        except Exception as e:  # noqa: BLE001 - one country must not stop the others
            failed[area] = f"{type(e).__name__}: {e}"[:200]
            log(f"  {area}: failed {failed[area]}")
            continue
        series_rows, obs_rows = {}, []
        for r in rows:
            key, value = r["KEY"], (r.get("OBS_VALUE") or "").strip()
            meta = catalogue.get(key)
            if meta is None or not value:
                continue
            if key not in series_rows:
                concept, _ = concept_of(key, area)
                unit = meta.get("UNIT") or meta.get("UNIT_MEASURE") or ""
                mult = meta.get("UNIT_MULT") or ""
                series_rows[key] = (key, concept, area, meta.get("FREQ", ""), unit, meta.get("TITLE") or meta.get("TITLE_COMPL") or "", flow, json.dumps({d: meta.get(d, "") for d in dims}),
                                    int(mult) if mult.lstrip("-").isdigit() else None)
            obs_rows.append(("ecb", key, r["TIME_PERIOD"], period_end(r["TIME_PERIOD"]), float(value), ""))
        conn.executemany("""INSERT INTO ext_series (source, series_key, indicator, concept, ref_area, freq, unit, title, flow, dims, unit_mult, pulled_at) VALUES ('ecb', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(source, series_key) DO UPDATE SET concept = excluded.concept, ref_area = excluded.ref_area, freq = excluded.freq, unit = excluded.unit, title = excluded.title,
                            flow = excluded.flow, dims = excluded.dims, unit_mult = excluded.unit_mult, pulled_at = excluded.pulled_at""",
                         [(k, v[1], v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[8], now) for k, v in series_rows.items()])
        conn.executemany("INSERT OR REPLACE INTO ext_obs VALUES (?, ?, ?, ?, ?, ?)", obs_rows)
        conn.commit()
        total_obs += len(obs_rows)
        total_series += len(series_rows)
        log(f"  {area}: {len(series_rows):6,d} series {len(obs_rows):9,d} observations")
    conn.execute("""UPDATE ext_series SET first_period = (SELECT MIN(period_end) FROM ext_obs o WHERE o.source = ext_series.source AND o.series_key = ext_series.series_key),
                    last_period = (SELECT MAX(period_end) FROM ext_obs o WHERE o.source = ext_series.source AND o.series_key = ext_series.series_key),
                    n_obs = (SELECT COUNT(*) FROM ext_obs o WHERE o.source = ext_series.source AND o.series_key = ext_series.series_key)
                    WHERE source = 'ecb' AND flow = ?""", (flow,))
    conn.execute("INSERT INTO ext_pull_log (started_at, indicator, source, n_series, n_obs, status, detail) VALUES (?, ?, 'ecb', ?, ?, ?, ?)",
                 (now, f"bulk:{flow}", total_series, total_obs, "ok" if not failed else "failed", json.dumps(failed)[:300]))
    conn.commit()
    return {"flow": flow, "catalogue": len(catalogue), "series": total_series, "observations": total_obs, "failed": failed}
