"""Tests of the external statistics (ECB, Eurostat). They use canned answers, so they need no network. The last test reads the real database when it holds the data.

  python scripts/test_ext.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.ext import pull, schema, specs  # noqa: E402
from modules.ext.http import NoData  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {name}{(' - ' + detail) if detail and not ok else ''}")
    if not ok:
        FAILED.append(name)


def near(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


HEAD = "KEY,FREQ,REF_AREA,TIME_PERIOD,OBS_VALUE,OBS_STATUS,TITLE\n"
MIR = HEAD + "\n".join([
    "MIR.M.LU.B.A2I.AM.R.A.2240.EUR.N,M,LU,2026-07,3.20,A,Cost of borrowing for corporations",
    "MIR.M.LU.B.A2I.AM.R.A.2240.EUR.N,M,LU,2026-08,3.17,A,Cost of borrowing for corporations",
    "MIR.M.GR.B.A2I.AM.R.A.2240.EUR.N,M,GR,2026-08,4.10,A,Cost of borrowing for corporations",
    "MIR.M.GR.B.A2I.AM.R.A.2240.EUR.N,M,GR,2026-07,,A,Cost of borrowing for corporations",   # held back: not stored
    "MIR.M.US.B.A2I.AM.R.A.2240.EUR.N,M,US,2026-08,9.99,A,not an EU country",                  # not an EU country: not stored
])
FM = HEAD + "\n".join(["FM.M.U2.EUR.RT.MM.EURIBOR3MD_.HSTA,M,,2026-07,2.60,A,Euribor 3-month", "FM.M.U2.EUR.RT.MM.EURIBOR3MD_.HSTA,M,,2026-08,2.63,A,Euribor 3-month"])
BSI = HEAD + "\n".join(["BSI.M.LU.N.A.A20.A.1.U2.2240.Z01.E,M,LU,2025-08,100000,A,Loans to NFCs", "BSI.M.LU.N.A.A20.A.1.U2.2240.Z01.E,M,LU,2026-08,110000,A,Loans to NFCs",
                        "BSI.M.GR.N.A.A20.A.1.U2.2240.Z01.E,M,GR,2026-08,50000,A,Loans to NFCs"])
BLS = HEAD + "BLS.Q.LU.ALL.O.E.Z.B3.ST.S.FNET,Q,LU,2026-Q3,20,A,Credit standards-Overall-Enterprise\n"
GEOS = ["EL", "LU", "EA20", "EA21", "NO"]
HPI = json.dumps({"label": "House price index - quarterly data", "id": ["freq", "unit", "geo", "time"], "size": [1, 1, 5, 2],
                  "dimension": {"freq": {"category": {"index": {"Q": 0}}}, "unit": {"category": {"index": {"RCH_A": 0}}},
                                "geo": {"category": {"index": {g: i for i, g in enumerate(GEOS)}}}, "time": {"category": {"index": {"2026-Q1": 0, "2026-Q2": 1}}}},
                  "value": {str(i): float(i) for i in range(10) if i != 5}, "status": {"3": "p"}})  # position = geo * 2 + time; the value of LU 2026-Q2 (3) is provisional; EA20 Q2 is missing


def fake_fetch(url: str) -> str:
    if "/MIR/" in url:
        return MIR
    if "/FM/" in url:
        return FM
    if "/BSI/" in url:
        return BSI
    if "/BLS/" in url:
        return BLS
    if "prc_hpi_q" in url:
        return HPI
    raise NoData(url)


def new_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    schema.create(conn)
    return conn


def test_helpers() -> None:
    print("1. periods and urls")
    cases = {"2025": "2025-12-31", "2026-Q2": "2026-06-30", "2026-Q4": "2026-12-31", "2025-S1": "2025-06-30", "2025-S2": "2025-12-31", "2026-08": "2026-08-31", "2026-02": "2026-02-28", "2024-02": "2024-02-29",
             "2026-12": "2026-12-31", "2026-10-13": "2026-10-13"}
    bad = {p: pull.period_end(p) for p, want in cases.items() if pull.period_end(p) != want}
    check("last day of a period (year, quarter, half year, month, day; leap year; December)", not bad, str(bad))
    sp = specs.BY_INDICATOR["cbd_roe"]
    url = pull.ecb_url(sp, 2015)
    check("ECB url: all countries joined by +, the euro area too, and the first period of the frequency", "A.AT+BE+BG+HR+CY+CZ+DK+EE+FI+FR+DE+GR+HU+IE+IT+LV+LT+LU+MT+NL+PL+PT+RO+SK+SI+ES+SE+U2.W0.11._Z._Z.A.A.I2003._Z._Z._Z._Z._Z._Z.PC" in url
          and url.endswith("startPeriod=2015&format=csvdata"), url)
    check("ECB url of a monthly and a quarterly indicator", pull.ecb_url(specs.BY_INDICATOR["mir_cob_nfc"], 2012).endswith("startPeriod=2012-01&format=csvdata")
          and pull.ecb_url(specs.BY_INDICATOR["bls_std_nfc"], 2012).endswith("startPeriod=2012-Q1&format=csvdata"))
    eu = pull.eurostat_url(specs.BY_INDICATOR["es_hpi_yoy"], 2010)
    check("Eurostat url: filters and the first quarter", "prc_hpi_q?format=JSON&lang=en&unit=RCH_A&purchase=TOTAL&sinceTimePeriod=2010-Q1" in eu, eu)
    keys = [s.indicator for s in specs.SPECS]
    check("every indicator is defined once, with a known frequency, and an ECB key has {A} unless it is euro area only",
          len(keys) == len(set(keys)) and all(s.freq in "AQMD" for s in specs.SPECS) and all("{A}" in s.key or s.euro_area_only for s in specs.SPECS if s.source == "ecb"))
    check("27 EU countries, the euro area as U2, Greece is EL at Eurostat", len(specs.COUNTRIES) == 27 and specs.EURO_AREA == "U2" and specs.EUROSTAT_CODE["GR"] == "EL")


def test_pull() -> None:
    print("2. pull, storage, views")
    conn = new_db()
    log: list[str] = []
    res = pull.pull(conn, fetcher=fake_fetch, only=["mir_cob_nfc", "euribor_3m", "bsi_loans_nfc", "es_hpi_yoy"], log=log.append)
    check("four indicators ok, none failed", sorted(res["ok"]) == ["bsi_loans_nfc", "es_hpi_yoy", "euribor_3m", "mir_cob_nfc"] and not res["failed"], str(res))
    n = lambda sql, *p: conn.execute(sql, p).fetchone()[0]  # noqa: E731
    check("ECB: a blank value and a non-EU country are not stored; Greece stays GR", n("SELECT COUNT(*) FROM v_ext_obs WHERE indicator = 'mir_cob_nfc'") == 3
          and n("SELECT COUNT(*) FROM v_ext_obs WHERE indicator = 'mir_cob_nfc' AND country = 'GR'") == 1 and n("SELECT COUNT(*) FROM v_ext_obs WHERE country = 'US'") == 0)
    check("ECB: a series without a REF_AREA column value of the euro area is stored under U2", n("SELECT COUNT(*) FROM v_ext_obs WHERE indicator = 'euribor_3m' AND country = 'U2'") == 2)
    rows = {(r[0], r[1]): r[2:] for r in conn.execute("SELECT country, period, value, status, period_end FROM v_ext_obs WHERE indicator = 'es_hpi_yoy'")}
    check("Eurostat: EL is stored as GR and the newest euro area aggregate (EA21) as U2; EA20 and a country outside the list are left out",
          {c for c, _ in rows} == {"GR", "LU", "U2"} and rows[("GR", "2026-Q1")][0] == 0.0 and rows[("U2", "2026-Q1")][0] == 6.0, str(rows))
    check("Eurostat: the flag (p = provisional) and the last day of the quarter are stored", rows[("LU", "2026-Q2")][1] == "p" and rows[("LU", "2026-Q2")][2] == "2026-06-30", str(rows[("LU", "2026-Q2")]))
    check("Eurostat: 6 observations are stored (EL, LU, EA21 for 2 quarters); EA20, the missing value, and the country outside the list give none", n("SELECT COUNT(*) FROM v_ext_obs WHERE indicator = 'es_hpi_yoy'") == 6)
    keyrow = conn.execute("SELECT series_key FROM ext_series WHERE indicator = 'es_hpi_yoy' AND ref_area = 'LU'").fetchone()[0]
    check("Eurostat series key = dataset, the other dimensions, the country", keyrow == "ESTAT.prc_hpi_q.Q.RCH_A.LU", keyrow)
    st = conn.execute("SELECT first_period, last_period, n_obs FROM ext_series WHERE indicator = 'mir_cob_nfc' AND ref_area = 'LU'").fetchone()
    check("series statistics: first and last period end, number of observations", st == ("2026-07-31", "2026-08-31", 2), str(st))
    before = (n("SELECT COUNT(*) FROM ext_obs"), n("SELECT COUNT(*) FROM ext_series"))
    pull.pull(conn, fetcher=fake_fetch, only=["mir_cob_nfc", "bsi_loans_nfc", "euribor_3m", "es_hpi_yoy"], log=lambda *_: None)
    check("a second pull does not duplicate anything (observations and series)", (n("SELECT COUNT(*) FROM ext_obs"), n("SELECT COUNT(*) FROM ext_series")) == before, str(before))
    g = conn.execute("SELECT growth_yoy FROM v_country_growth WHERE indicator = 'bsi_loans_nfc' AND country = 'LU' AND period = '2026-08'").fetchone()
    check("view growth: loans of 110,000 against 100,000 one year before give 10%", g is not None and near(g[0], 0.10), str(g))
    check("view growth: a country without the month of the year before has no growth", conn.execute("SELECT COUNT(*) FROM v_country_growth WHERE country = 'GR'").fetchone()[0] == 0)
    sp = conn.execute("SELECT rate, euribor_3m, spread_to_euribor, deposit_margin FROM v_country_spreads WHERE indicator = 'mir_cob_nfc' AND country = 'LU' AND period = '2026-08'").fetchone()
    check("view spreads: 3.17 less the Euribor of 2.63 = 0.54; the deposit margin is the opposite", sp is not None and near(sp[2], 0.54, 1e-6) and near(sp[3], -0.54, 1e-6), str(sp))
    latest = conn.execute("SELECT period, value FROM v_ext_latest WHERE indicator = 'mir_cob_nfc' AND country = 'LU'").fetchone()
    check("view latest: the last observation of each series", latest == ("2026-08", 3.17), str(latest))
    check("countries are seeded: 27 and the euro area", n("SELECT COUNT(*) FROM ext_country") == 28 and n("SELECT eurostat_code FROM ext_country WHERE iso2 = 'GR'") == "EL")
    log2: list[str] = []
    pull.pull(new_db(), fetcher=fake_fetch, only=["survey"], log=log2.append)
    check("a group name selects its indicators (survey: the six of the lending survey)", len(log2) == 6 and all(line.strip().startswith("bls_") for line in log2), str(log2[:2]))


def test_failures() -> None:
    print("3. a failing indicator does not stop the others")
    conn = new_db()

    def flaky(url: str) -> str:
        if "/MIR/" in url:
            raise RuntimeError("HTTP 500")
        return fake_fetch(url)

    res = pull.pull(conn, fetcher=flaky, only=["mir_cob_nfc", "bsi_loans_nfc", "sup_roe"], log=lambda *_: None)
    check("the failed one is reported, the good one is stored, a 404 is 'no data'", "mir_cob_nfc" in res["failed"] and "bsi_loans_nfc" in res["ok"] and "sup_roe" in res["failed"]
          and conn.execute("SELECT status FROM ext_pull_log WHERE indicator = 'sup_roe'").fetchone()[0] == "no data"
          and conn.execute("SELECT status FROM ext_pull_log WHERE indicator = 'mir_cob_nfc'").fetchone()[0] == "failed", str(res))
    bad = '{"error": [{"status": 400, "label": "INVALID_QUERY"}]}'
    try:
        pull.parse_eurostat(bad, specs.BY_INDICATOR["es_hpi_yoy"])
        raised = False
    except RuntimeError:
        raised = True
    check("an error answer of Eurostat raises", raised)


CAT_HEAD = "KEY,FREQ,REF_AREA,BS_ITEM,TIME_PERIOD,OBS_VALUE,TITLE,UNIT,UNIT_MULT\n"
CAT_MIR = CAT_HEAD + "\n".join([
    "MIR.M.LU.A2I,M,LU,A2I,2026-08,3.17,Cost of borrowing LU,PC,0",
    "MIR.M.DE.A2I,M,DE,A2I,2026-08,3.50,Cost of borrowing DE,PC,0",
    "MIR.M.LU.L21,M,LU,L21,2026-08,0.50,Overnight deposits LU,PC,0",
    "MIR.M.US.A2I,M,US,A2I,2026-08,9.99,not an EU country,PC,0",
])
DATA_HEAD = "KEY,FREQ,REF_AREA,BS_ITEM,TIME_PERIOD,OBS_VALUE\n"
DATA_LU = DATA_HEAD + "\n".join(["MIR.M.LU.A2I,M,LU,A2I,2026-07,3.20", "MIR.M.LU.A2I,M,LU,A2I,2026-08,3.17", "MIR.M.LU.A2I,M,LU,A2I,2026-06,",
                                 "MIR.M.LU.L21,M,LU,L21,2026-08,0.50", "MIR.M.LU.ZZZ,M,LU,ZZZ,2026-08,1.00"])  # a blank value and a series that the catalogue does not list: not stored
DATA_DE = DATA_HEAD + "MIR.M.DE.A2I,M,DE,A2I,2026-08,3.50\n"
CAT_BSI = ("KEY,FREQ,REF_AREA,ADJUSTMENT,BS_REP_SECTOR,BS_ITEM,MATURITY_ORIG,DATA_TYPE,COUNT_AREA,BS_COUNT_SECTOR,CURRENCY_TRANS,BS_SUFFIX,TIME_PERIOD,OBS_VALUE,TITLE,UNIT,UNIT_MULT\n"
           "BSI.M.LU.N.A.A20.A.1.U2.2240.Z01.E,M,LU,N,A,A20,A,1,U2,2240,Z01,E,2026-08,1,Loans stock,EUR,6\n"
           "BSI.M.LU.N.A.A20.A.4.U2.2240.Z01.E,M,LU,N,A,A20,A,4,U2,2240,Z01,E,2026-08,1,Loans flow,EUR,6\n")


def fake_bulk(url: str) -> str:
    if "lastNObservations=1" in url:
        return CAT_BSI if "/BSI?" in url else CAT_MIR
    if "/MIR/.LU." in url:
        return DATA_LU
    if "/MIR/.DE." in url:
        return DATA_DE
    raise NoData(url)


def test_bulk() -> None:
    from modules.ext import bulk, keys
    print("4. concepts of series and the bulk pull of a dataflow")
    cases = [(("MIR.M.LU.B.A2I.AM.R.A.2240.EUR.N", "LU"), ("MIR/B.A2I.AM.R.A.2240.EUR.N", "MIR")),
             (("BSI.M.U2.N.A.A20.A.1.U2.2240.Z01.E", "U2"), ("BSI/N.A.A20.A.1.U2.2240.Z01.E", "BSI")),  # the first U2 is the area; the second is the counterpart area and stays
             (("FM.M.U2.EUR.RT.MM.EURIBOR3MD_.HSTA", "U2"), ("FM/EUR.RT.MM.EURIBOR3MD_.HSTA", "FM")),
             (("EST.B.EU000A2X2A25.WT", "U2"), ("EST/EU000A2X2A25.WT", "EST"))]
    bad = {k: keys.concept_of(*k) for k, want in cases if keys.concept_of(*k) != want}
    check("concept = the key without the frequency and the country (the counterpart area of a BSI key stays; a key without a country keeps its dimensions)", not bad, str(bad))
    check("the same measure in two countries has the same concept", keys.concept_of("MIR.M.LU.B.A2I", "LU")[0] == keys.concept_of("MIR.M.DE.B.A2I", "DE")[0])

    dims, cat = bulk.read_catalogue("MIR", fake_bulk)
    check("catalogue: dimensions are the columns between KEY and TIME_PERIOD; a non-EU country is left out", dims == ["FREQ", "REF_AREA", "BS_ITEM"] and len(cat) == 3 and not any(".US." in k for k in cat), f"{dims} {list(cat)}")
    dims_b, cat_b = bulk.read_catalogue("BSI", fake_bulk)
    check("catalogue of BSI: a flow series (data type 4) is left out", len(cat_b) == 1 and ".1.U2." in next(iter(cat_b)), str(list(cat_b)))
    check("request for a country: the country at its place, the fixed dimensions of the flow, the first year", bulk.area_url("MIR", dims, "LU", 1999).endswith("/MIR/.LU.?startPeriod=1999&detail=dataonly&format=csvdata"), bulk.area_url("MIR", dims, "LU", 1999))
    check("request for BSI: the fixed dimensions (monthly, sector A, counterpart area U2, all currencies) at their places", "/BSI/M.LU..A....U2..Z01.?" in bulk.area_url("BSI", dims_b, "LU", 2000), bulk.area_url("BSI", dims_b, "LU", 2000))

    conn = new_db()
    conn.execute("INSERT INTO ext_series (source, series_key, indicator, ref_area, freq) VALUES ('ecb', 'MIR.M.LU.A2I', 'mir_cob_nfc', 'LU', 'M')")  # a curated series
    log: list[str] = []
    res = bulk.pull_flow(conn, "MIR", since=2026, fetcher=fake_bulk, log=log.append)
    n = lambda sql, *p: conn.execute(sql, p).fetchone()[0]  # noqa: E731
    check("pull: 3 series in the catalogue, 4 observations stored (LU 3 and DE 1; the blank value and the unlisted series are left out)", res["series"] == 3 and res["observations"] == 4 and n("SELECT COUNT(*) FROM ext_obs") == 4, str(res))
    check("a curated series keeps its indicator name; a new series gets its concept as the name", n("SELECT indicator FROM ext_series WHERE series_key = 'MIR.M.LU.A2I'") == "mir_cob_nfc"
          and n("SELECT indicator FROM ext_series WHERE series_key = 'MIR.M.LU.L21'") == "MIR/L21")
    row = conn.execute("SELECT concept, flow, ref_area, freq, unit, title, dims, unit_mult FROM ext_series WHERE series_key = 'MIR.M.DE.A2I'").fetchone()
    check("series row: concept, flow, country, frequency, unit, title, dimensions, multiplier", row[:6] == ("MIR/A2I", "MIR", "DE", "M", "PC", "Cost of borrowing DE") and json.loads(row[6]) == {"FREQ": "M", "REF_AREA": "DE", "BS_ITEM": "A2I"} and row[7] == 0, str(row))
    st = conn.execute("SELECT first_period, last_period, n_obs FROM ext_series WHERE series_key = 'MIR.M.LU.A2I'").fetchone()
    check("statistics of the series after the pull", st == ("2026-07-31", "2026-08-31", 2), str(st))
    check("the pull is logged", n("SELECT COUNT(*) FROM ext_pull_log WHERE indicator = 'bulk:MIR' AND status = 'ok'") == 1)
    before = (n("SELECT COUNT(*) FROM ext_obs"), n("SELECT COUNT(*) FROM ext_series"))
    bulk.pull_flow(conn, "MIR", since=2026, fetcher=fake_bulk, log=lambda *_: None)
    check("a second pull does not duplicate anything", (n("SELECT COUNT(*) FROM ext_obs"), n("SELECT COUNT(*) FROM ext_series")) == before)
    check("a chosen country only", bulk.pull_flow(new_db(), "MIR", since=2026, areas=["DE"], fetcher=fake_bulk, log=lambda *_: None)["observations"] == 1)

    def flaky(url: str) -> str:
        if "/MIR/.DE." in url:
            raise RuntimeError("HTTP 500")
        return fake_bulk(url)

    c2 = new_db()
    res = bulk.pull_flow(c2, "MIR", since=2026, fetcher=flaky, log=lambda *_: None)
    check("a failing country is reported; the other country is stored; the log says failed", list(res["failed"]) == ["DE"] and res["observations"] == 3
          and c2.execute("SELECT status FROM ext_pull_log WHERE indicator = 'bulk:MIR'").fetchone()[0] == "failed", str(res))


def _put(conn: sqlite3.Connection, indicator: str, concept: str, area: str, data: dict[str, float], freq: str = "M") -> None:
    key = f"{concept}|{area}|{freq}"
    conn.execute("INSERT OR REPLACE INTO ext_series (source, series_key, indicator, concept, ref_area, freq) VALUES ('ecb', ?, ?, ?, ?, ?)", (key, indicator, concept, area, freq))
    conn.executemany("INSERT OR REPLACE INTO ext_obs VALUES ('ecb', ?, ?, ?, ?, '')", [(key, p, pull.period_end(p), v) for p, v in data.items()])


def _months(first: str, n: int) -> list[str]:
    y, m = int(first[:4]), int(first[5:])
    return [f"{y + (m - 1 + i) // 12}-{(m - 1 + i) % 12 + 1:02d}" for i in range(n)]


def test_analytics() -> None:
    import numpy as np
    from modules.ext import analytics as an
    print("5. group aggregates and pass-through (synthetic data with known answers)")
    conn = new_db()
    pull.seed_countries(conn)
    check("months helper", _months("2025-11", 4) == ["2025-11", "2025-12", "2026-01", "2026-02"])
    # market: 0 until 2022-06, then +0.25 a month for 16 months to 4.0 in 2023-10, then flat to 2023-12
    months = _months("2022-01", 24)
    market = {p: min(max(0.0, 0.25 * (i - 5)), 4.0) for i, p in enumerate(months)}  # 2022-06 is index 5
    check("the synthetic market rate: 0 at the start month, 4 at the end month", market["2022-06"] == 0.0 and market["2023-12"] == 4.0)
    _put(conn, "euribor_3m", "FM/EUR.RT.MM.EURIBOR3MD_.HSTA", "U2", market)
    product = "deposits households, overnight"
    rate_concept, weight_concept = an.PRODUCTS[product]
    _put(conn, "x", rate_concept, "AA", {p: 0.5 * v for p, v in market.items()})                      # beta 0.5, no lag
    _put(conn, "x", rate_concept, "BB", {p: 0.0 for p in months})                                     # a rate that does not move
    gap = {p: v for p, v in {p: 1.0 * market[p] for p in months}.items() if p != "2022-12"}
    _put(conn, "x", rate_concept, "CC", gap)                                                           # beta 1, one month missing in the history
    short = {p: v for p, v in market.items() if p >= "2022-09"}
    _put(conn, "x", rate_concept, "DD", short)                                                         # starts after the start of the cycle: no beta
    cycles = {"hike": ("2022-06", "2023-12"), "small": ("2023-10", "2023-12")}
    df = an.pass_through(conn, cycles=cycles, products={product: an.PRODUCTS[product]}, store=True)
    b = {(r.country, r.cycle): r for r in df.itertuples()}
    check("beta of a rate that follows half of the market move is 0.5; the rates at the start and the end are the averages of 3 months", near(b[("AA", "hike")].beta, 0.5) and near(b[("AA", "hike")].rate_end, 2.0)
          and near(b[("AA", "hike")].market_start, 0.0) and near(b[("AA", "hike")].market_end, 4.0), str(b[("AA", "hike")]))
    check("a rate that does not move has beta 0 and no half-time", near(b[("BB", "hike")].beta, 0.0) and np.isnan(b[("BB", "hike")].months_to_half))
    check("a gap inside the history is filled: beta 1", near(b[("CC", "hike")].beta, 1.0), str(b[("CC", "hike")].beta))
    check("the months until half of the move: 9 (the retail rate lags the market by one month through the average of 3 months)", b[("AA", "hike")].months_to_half == 9.0, str(b[("AA", "hike")].months_to_half))
    check("a series that starts after the start of the cycle has no row for it", ("DD", "hike") not in b)
    check("a cycle in which the market moves less than half a point has no beta", np.isnan(b[("AA", "small")].beta), str(b[("AA", "small")].beta))
    early = {"finished": ("2022-06", "2022-08"), "to date": ("2022-06", "2022-08")}  # the market moves 0.25 in both
    saved = dict(an.MIN_MOVE_BY_CYCLE)
    an.MIN_MOVE_BY_CYCLE["to date"] = 0.2
    try:
        e = {r.cycle: r.beta for r in an.pass_through(conn, cycles=early, products={product: an.PRODUCTS[product]}, store=False).itertuples() if r.country == "AA"}
    finally:
        an.MIN_MOVE_BY_CYCLE.clear()
        an.MIN_MOVE_BY_CYCLE.update(saved)
    check("a cycle that is not finished needs a smaller market move: a move of 0.25 gives a beta only to it", np.isnan(e["finished"]) and near(e["to date"], 0.5), str(e))
    check("the table ext_passthrough is written", conn.execute("SELECT COUNT(*) FROM ext_passthrough").fetchone()[0] == len(df))
    try:
        an.pass_through(new_db(), cycles=cycles)
        raised = False
    except ValueError:
        raised = True
    check("no market rate: an error that names the indicator to pull", raised)

    # aggregates
    conn.execute("INSERT INTO ext_geo_group VALUES ('Test', 'AA'), ('Test', 'BB'), ('Test', 'CC')")
    jan = ["2026-01", "2026-02", "2026-03"]
    _put(conn, "y", "MIR/X", "AA", dict(zip(jan, [2.0, 3.0, 4.0])))
    _put(conn, "y", "MIR/X", "BB", dict(zip(jan, [1.0, 1.0, 1.0])))
    _put(conn, "y", "MIR/X", "CC", dict(zip(jan, [10.0, 10.0, 10.0])))
    _put(conn, "y", "BSI/W", "AA", dict(zip(jan, [100.0, 100.0, 100.0])))
    _put(conn, "y", "BSI/W", "BB", {"2026-01": 300.0, "2026-03": 300.0})       # February is missing: the last known weight is used
    agg = an.aggregate(conn, "MIR/X", "Test", weight="BSI/W")
    check("weighted mean: (2 x 100 + 1 x 300) / 400 = 1.25; a country without weights (CC) is left out of it", near(agg.loc["2026-01", "wmean"], 1.25), str(agg.loc["2026-01"].to_dict()))
    check("a missing weight month uses the last known weight: (3 x 100 + 1 x 300) / 400 = 1.5", near(agg.loc["2026-02", "wmean"], 1.5), str(agg.loc["2026-02"].to_dict()))
    check("mean, median, minimum, maximum, and number include all 3 countries", near(agg.loc["2026-01", "mean"], 13 / 3) and agg.loc["2026-01", "median"] == 2.0 and agg.loc["2026-01", "min"] == 1.0
          and agg.loc["2026-01", "max"] == 10.0 and agg.loc["2026-01", "n"] == 3)
    check("without a weight concept the weighted mean is the simple mean", near(an.aggregate(conn, "MIR/X", "Test").loc["2026-01", "wmean"], 13 / 3))
    try:
        an.members(conn, "Nowhere")
        raised = False
    except ValueError as e:
        raised = "Benelux" in str(e) or "Test" in str(e)
    check("an unknown group raises an error that lists the groups", raised)
    benelux = an.members(conn, "Benelux")
    check("the geographic groups are seeded: Benelux = BE, LU, NL; the euro area group has 21 members; EU27 has 27", benelux == ["BE", "LU", "NL"] and len(an.members(conn, "Euro area (members)")) == 21 and len(an.members(conn, "EU27")) == 27, str(benelux))
    # group betas with stocks at the start of the cycle
    _put(conn, "z", weight_concept, "AA", {p: 100.0 for p in months})
    _put(conn, "z", weight_concept, "CC", {p: 300.0 for p in months})
    df2 = an.pass_through(conn, cycles={"hike": ("2022-06", "2023-12")}, products={product: an.PRODUCTS[product]}, store=False)
    gb = an.group_betas(conn, df2, "Test")
    r = gb.iloc[0]
    check("group beta: median of AA 0.5, BB 0, CC 1.0 is 0.5; mean 0.5; the weighted mean uses the stocks (AA 100, CC 300; BB has none): (0.5 x 100 + 1 x 300) / 400 = 0.875",
          r["n"] == 3 and near(r["median"], 0.5) and near(r["mean"], 0.5) and near(r["wmean"], 0.875), str(r.to_dict()))


P3DH_TABLES = """
CREATE TABLE clean_period_fact (entity_key TEXT, period_end TEXT, template_code TEXT, measure_col INTEGER, row_code TEXT, value REAL, quality TEXT);
CREATE TABLE clean_fact (entity_key TEXT, reference_date TEXT, template_code TEXT, cell_code TEXT, row_code TEXT, column_code TEXT, sheet TEXT, key_descriptor TEXT, value REAL, quality TEXT);
CREATE TABLE bbg_entity (lei TEXT, found INTEGER, country_iso TEXT, latest_period_end TEXT, roe REAL, roa REAL);
CREATE TABLE v_entity_class (entity_key TEXT, entity_name TEXT, country TEXT);
"""


def _fact(conn: sqlite3.Connection, key: str, ref: str, tpl: str, row: str, col: str, value: float, sheet: str = "", quality: str = "ok") -> None:
    cell = "{%s%s, r%s, c%s}" % (tpl, "." + sheet if sheet else "", row, col)
    conn.execute("INSERT INTO clean_fact VALUES (?, ?, ?, ?, ?, ?, '', '', ?, ?)", (key, ref, tpl, cell, row, col, value, quality))


def test_benchmark() -> None:
    from modules.ext import bank_metrics as bm, benchmark as bk
    print("6. bank figures and the benchmark (synthetic data with known answers)")
    conn = new_db()
    pull.seed_countries(conn)
    conn.executescript(P3DH_TABLES)
    conn.executemany("INSERT INTO v_entity_class VALUES (?, ?, ?)", [("B1", "Bank one", "Luxembourg"), ("B2", "Bank two", "Luxembourg"), ("B3", "Bank three", "Germany"), ("B4", "Bank four", "Germany"),
                                                                      ("B5", "Bank five", "France"), ("B6", "Bank six", "France"), ("B7", "Bank seven", "Czech")])
    conn.execute("INSERT INTO bbg_entity VALUES ('B1', 1, 'LU', '2025-12-31', 8.0, 0.7)")
    # KM1 of B1: 10% CET1, 12% Tier 1, 15% total capital, leverage 6%, LCR 175%, NSFR 130%; a quarter without TREA has the liquidity ratios only
    for row, v in {"0010": 1000, "0020": 1200, "0030": 1500, "0040": 10000, "0220": 0.06, "0320": 1.75, "0350": 1.3}.items():
        conn.execute("INSERT INTO clean_period_fact VALUES ('B1', '2025-12-31', 'K_61.00', 10, ?, ?, 'ok')", (row, v))
    conn.execute("INSERT INTO clean_period_fact VALUES ('B1', '2025-09-30', 'K_61.00', 10, '0320', 1.6, 'ok')")
    k = bm.km1(conn, "B1")
    check("KM1: capital ratios = capital / TREA in percent; leverage, LCR, and NSFR fractions become percent",
          near(k["cet1_ratio"]["2025-12-31"], 10) and near(k["t1_ratio"]["2025-12-31"], 12) and near(k["total_capital_ratio"]["2025-12-31"], 15) and near(k["leverage_ratio"]["2025-12-31"], 6)
          and near(k["lcr"]["2025-12-31"], 175) and near(k["nsfr"]["2025-12-31"], 130), str(k))
    check("KM1: a quarter without TREA has no capital ratio, but it has its LCR", "2025-09-30" not in k["cet1_ratio"] and near(k["lcr"]["2025-09-30"], 160))
    # OR2: three years in one filing; 2025 = column a, 2024 = b, 2023 = c; the expense is negative in 2025 and 2023, positive in 2024
    for row, vals in {"0030": (1000, 900, 800), "0040": (-500, 400, -300), "0050": (20000, 19000, 18000), "0060": (5, 5, 5), "0080": (250, 200, 150), "0090": (50, 40, 30),
                      "0100": (20, 20, 20), "0110": (10, 10, 10), "0130": (10, 10, 10), "0140": (5, 5, 5)}.items():
        for col, v in zip(("0010", "0020", "0030"), vals):
            _fact(conn, "B1", "2025-12-31", "K_19.02", row, col, v * 2e5)  # amounts in EUR: NII of 2025 = 100m; the ratios do not depend on the scale
    _fact(conn, "B1", "2025-12-31", "K_19.02", "0030", "0010", 999999, quality="quarantined")
    o = bm.or2(conn, "B1")
    p = "2025-12-31"
    check("OR2 2025: NII 500, fees 200, income 730 give 2.5% NII, 1.0% fees, 3.65% income on assets 20,000, and shares of income 68.49% and 27.40%",
          near(o["nii_to_assets"][p], 2.5) and near(o["fee_to_assets"][p], 1.0) and near(o["income_to_assets"][p], 3.65) and near(o["nii_to_income"][p], 500 / 730 * 100) and near(o["fee_to_income"][p], 200 / 730 * 100), str({m: v.get(p) for m, v in o.items()}))
    check("OR2: interest income 5.0% and interest expense -2.5% of assets (the expense is negative as in the ECB data)", near(o["interest_income_to_assets"][p], 5.0) and near(o["interest_expense_to_assets"][p], -2.5))
    check("OR2: the older years of the filing are 2024 and 2023; an expense with a positive sign (2024: +400) is still an expense (-400 / 19,000)", set(o["nii_to_assets"]) == {"2023-12-31", "2024-12-31", "2025-12-31"}
          and near(o["interest_expense_to_assets"]["2024-12-31"], -400 / 19000 * 100) and near(o["nii_to_assets"]["2024-12-31"], 500 / 19000 * 100), str(o["nii_to_assets"]))
    check("OR2: a quarantined cell is not used", near(o["interest_income_to_assets"][p], 5.0))
    # CR1: sheet .a is the amounts; a cell of sheet .b with the same row and column must not count
    def cr1(ref: str, f: float) -> None:
        for row, (perf, npl) in {"0020": (7600, 400), "0030": (1000, 0), "0040": (500, 0), "0050": (500, 0), "0060": (1000, 0), "0070": (2800, 250), "0090": (1800, 150)}.items():
            _fact(conn, "B1", ref, "K_21.01", row, "0010", perf * f, "a")
            _fact(conn, "B1", ref, "K_21.01", row, "0040", npl * f, "a")
    cr1("2025-12-31", 1.0)
    cr1("2024-12-31", 0.8)
    _fact(conn, "B1", "2025-12-31", "K_21.01", "0020", "0010", 999999, "b")
    c = bm.cr1(conn, "B1")
    check("CR1: NPL ratio = 400 / 8,000 = 5%; gross loans 8,000; the cell of sheet .b is not used", near(c["npl_ratio"]["2025-12-31"], 5) and near(c["gross_loans"]["2025-12-31"], 8000), str(c["gross_loans"]))
    mix = c["loan_mix"]["2025-12-31"]
    check("CR1 mix: central banks 12.5%, credit institutions 6.25%, general government 6.25%, other financial 12.5%, non-financial 38.125%, households 24.375%",
          near(mix["central banks"], 12.5) and near(mix["credit institutions"], 6.25) and near(mix["general government"], 6.25) and near(mix["other financial corporations"], 12.5)
          and near(mix["non-financial corporations"], 38.125) and near(mix["households"], 24.375) and near(sum(mix.values()), 100), str(mix))
    check("CR1: loans to non-banks = general government + other financial + non-financial + households = 6,500", near(c["nonbank_loans"]["2025-12-31"], 6500), str(c["nonbank_loans"]))
    b = bm.bloomberg(conn, "B1")
    check("Bloomberg: return on equity and on assets of the last fiscal year", b["roe"] == {"2025-12-31": 8.0} and b["roa"] == {"2025-12-31": 0.7})
    check("country of a bank: Bloomberg first, then the P3DH classification by name (Germany = DE, Czech = CZ); unknown = none",
          bm.country_of(conn, "B1") == "LU" and bm.country_of(conn, "B3") == "DE" and bm.country_of(conn, "B7") == "CZ" and bm.country_of(conn, "nobody") is None)

    # ECB side
    cet1 = bk.BY_KEY["cet1_ratio"]
    _put(conn, "x", cet1.concept, "LU", {"2025-12-31": 12.0}, "Q")
    for area, v in {"U2": 16.0, "DE": 18.0, "FR": 14.0, "BE": 20.0}.items():
        _put(conn, "x", cet1.concept, area, {"2025-12-31": v}, "Q")
    r = bk.compare(conn, cet1, {"2025-12-31": 10.0, "2026-06-30": 11.0}, "LU", {"Benelux": bk.members(conn, "Benelux")}).set_index("period")
    a = r.loc["2025-12-31"]
    check("compare: country 12, euro area 16, EU median of LU, DE, FR, BE = 16, bank below all 4 (rank 0%), Benelux median of BE and LU = 16, bank less country = -2",
          near(a["country"], 12) and near(a["euro_area"], 16) and near(a["eu_median"], 16) and a["eu_rank"] == 0 and a["n_eu"] == 4 and near(a["Benelux"], 16) and near(a["bank_less_country"], -2), str(a.to_dict()))
    check("compare: a bank figure of 15 is above 2 of 4 countries (rank 50%)", bk.compare(conn, cet1, {"2025-12-31": 15.0}, "LU").iloc[0]["eu_rank"] == 50.0)
    check("compare: a period without ECB data gives empty figures, not an error", np_isnan(r.loc["2026-06-30", "country"]) and r.loc["2026-06-30", "n_eu"] == 0)
    nii = bk.BY_KEY["nii_to_assets"]
    _put(conn, "x", nii.concept, "LU", {"2025": 1.5}, "A")
    check("compare: an annual ECB series is matched to the bank by calendar year", near(bk.compare(conn, nii, {"2025-12-31": 2.5}, "LU").iloc[0]["country"], 1.5))

    # loan mix: LU lacks the sectors 1000, 2100, and 2210 (derived from 0000, 2000, 2200); DE has all
    def stock(area: str, code: str, v: float) -> None:
        _put(conn, "x", bk.LOAN_STOCK.format(sector=code), area, {"2025-12": v, "2024-12": v / 1.1}, "M")
    for code, v in {"0000": 1000, "2000": 400, "2200": 380, "2240": 100, "2250": 150, "2220": 10}.items():
        stock("LU", code, v)
    for code, v in {"1000": 300, "2100": 50, "2210": 100, "2220": 10, "2240": 200, "2250": 340}.items():
        stock("DE", code, v)
    conn.execute("INSERT OR IGNORE INTO ext_geo_group VALUES ('Test', 'LU'), ('Test', 'DE')")
    bank_mix = {k: v for k, v in c["loan_mix"]["2025-12-31"].items()}
    m = bk.loan_mix(conn, bank_mix, "LU", {"Test": ["LU", "DE"]}, "2025-12-31").set_index("counterparty")
    check("loan mix, LU: credit institutions 60 (0000 - 2000), general government 2 (2000 - 2200), other financial 13 (2200 - 2240 - 2250), non-financial 10, households 15 (shares of 1,000)",
          all(near(m.loc[k, "country"], v) for k, v in {"credit institutions": 60, "general government": 2, "other financial corporations": 13, "non-financial corporations": 10, "households": 15}.items()), str(m["country"].to_dict()))
    check("loan mix, group of LU and DE: the shares of the sums (credit 45, government 3.5, other financial 12, non-financial 15, households 24.5); 2 countries",
          all(near(m.loc[k, "Test"], v) for k, v in {"credit institutions": 45, "general government": 3.5, "other financial corporations": 12, "non-financial corporations": 15, "households": 24.5}.items()) and m.loc["countries behind the figure", "Test"] == 2, str(m["Test"].to_dict()))
    check("loan mix, bank: central banks and credit institutions form one group (18.75%)", near(m.loc["credit institutions", "bank"], 18.75) and near(m.loc["households", "bank"], 24.375))
    m2 = bk.loan_mix(conn, bank_mix, "LU", None, "2025-12-31", exclude=("credit institutions",)).set_index("counterparty")
    check("loan mix without credit institutions: the shares add up to 100 again (LU: government 5, other financial 32.5, non-financial 25, households 37.5; bank households 24.375 / 81.25 = 30%)",
          "credit institutions" not in m2.index and near(m2.loc["general government", "country"], 5) and near(m2.loc["other financial corporations", "country"], 32.5) and near(m2.loc["households", "country"], 37.5)
          and near(m2.loc["households", "bank"], 30.0) and near(m2[["bank"]].iloc[:-1].sum().iloc[0], 100), str(m2[["bank", "country"]].to_dict()))
    g = bk.loan_growth(conn, c["gross_loans"], "LU", None).iloc[0]
    check("loan growth: bank 8,000 against 6,400 = +25%; the ECB stock of LU 1,000 against 909 = +10%; bank less country = 15", near(g["bank"], 25) and near(g["country"], 10) and near(g["bank_less_country"], 15), str(g.to_dict()))
    g2 = bk.loan_growth(conn, c["nonbank_loans"], "LU", None, bk.LOAN_STOCK.format(sector="2000")).iloc[0]
    check("loan growth of non-bank loans: bank 6,500 against 5,200 = +25%", near(g2["bank"], 25), str(g2.to_dict()))

    # rate sensitivity: NII of 100m for five banks, and one bank with 10m that is left out
    def irr(key: str, nii_m: float, up: float, down: float, date: str = "2026-06-30") -> None:
        if key != "B1":  # B1 has its OR2 above (NII 100m)
            _fact(conn, key, "2025-12-31", "K_19.02", "0030", "0010", nii_m * 1.5e6)
            _fact(conn, key, "2025-12-31", "K_19.02", "0040", "0010", -nii_m * 0.5e6)
        _fact(conn, key, date, "K_68.00", "0010", "0030", up * 1e6)
        _fact(conn, key, date, "K_68.00", "0020", "0030", down * 1e6)
    conn.execute("INSERT INTO v_entity_class VALUES ('B9', 'Bank nine', 'France')")
    for key, nii_m, up, down, date in (("B1", 100, 2, -8, "2026-06-30"), ("B2", 100, 1, -4, "2026-06-30"), ("B3", 100, 4, -2, "2026-06-30"), ("B4", 100, 6, -1, "2026-06-30"),
                                       ("B5", 100, 3, -3, "2025-12-31"), ("B6", 10, 9, -9, "2026-06-30"), ("B9", 100, 50, -50, "2024-12-31")):
        irr(key, nii_m, up, down, date)
    ir = bm.irrbb_position(conn, "B1")
    check("IRRBB: 5 banks with NII of 100m (B6 with 10m is left out; B5 counts with its filing of 6 months before; B9 with a filing of 24 months before is left out); B1 gains 2% for +200 and loses 8% for -200",
          ir["n_banks"] == 5 and ir["first_date"] == "2025-12-31" and near(ir["bank"]["up"], 2.0) and near(ir["bank"]["down"], -8.0), str(ir))
    check("IRRBB: median of the country (B1, B2): +1.5 / -6; of the euro area (all 5): +3 / -3; of all: +3 / -3", near(ir["country"]["up"], 1.5) and near(ir["country"]["down"], -6) and ir["country"]["n"] == 2
          and near(ir["euro area"]["up"], 3) and near(ir["euro area"]["down"], -3) and near(ir["all"]["up"], 3), str(ir))
    check("IRRBB: B1 is above 1 of 5 banks for +200 (20%) and above none for -200 (0%)", near(ir["above"]["up"], 20) and near(ir["above"]["down"], 0), str(ir["above"]))
    check("IRRBB: a bank without IRRBB data gives an empty answer", bm.irrbb_position(conn, "B7") == {})

    # context and the whole report
    _put(conn, "x", bk.CONTEXT["domestic banks, share of the banking assets of the country (%)"][0], "LU", {"2024": 13.4, "2025": 13.9}, "A")
    ctx = bk.context(conn, "LU")
    check("context: the last year of the share of the domestic banks", ctx["domestic banks, share of the banking assets of the country (%)"] == ("2025", 13.9), str(ctx))
    rep = bk.report(conn, "B1")
    check("report: country from Bloomberg, groups of the country without the generic ones (Benelux, Core euro area, and the group Test of this test), and every table", rep["country"] == "LU" and set(rep["groups"]) == {"Benelux", "Core euro area", "Test"}
          and not rep["ratios"].empty and not rep["loan_mix"].empty and not rep["loan_growth"].empty and rep["irrbb"]["n_banks"] == 5 and rep["bank"] == "Bank one", f"{rep['country']} {list(rep['groups'])}")
    check("report: loan growth has the two measures", set(rep["loan_growth"]["measure"]) == {"all loans", "loans to non-banks"} if not rep["loan_growth"].empty else False)
    empty = bk.report(conn, "B7")
    check("report: a bank without figures gives empty tables, not an error", empty["country"] == "CZ" and empty["ratios"].empty and empty["loan_mix"].empty and empty["loan_growth"].empty and empty["irrbb"] == {})
    try:
        bk.report(conn, "nobody")
        raised = False
    except ValueError:
        raised = True
    check("report: an unknown bank without a country raises an error that asks for the country", raised)


def np_isnan(x) -> bool:
    return x != x


def test_real_database() -> None:
    print("7. coverage of the real database (skipped when the data is not pulled)")
    db = ROOT / "data" / "processed" / "p3dh.sqlite"
    if not db.exists():
        print("  skipped (no database)")
        return
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    if not conn.execute("SELECT name FROM sqlite_master WHERE name = 'ext_obs'").fetchone() or not conn.execute("SELECT COUNT(*) FROM ext_obs").fetchone()[0]:
        print("  skipped (no external statistics: run scripts/pull_ext.py all)")
        return
    q = lambda sql, *p: conn.execute(sql, p).fetchall()  # noqa: E731
    cov = dict(q("SELECT indicator, COUNT(DISTINCT ref_area) FROM ext_series WHERE ref_area <> 'U2' GROUP BY indicator"))
    for ind in ("bsi_loans_nfc", "bsi_loans_hh", "cbd_roe", "es_gdp_yoy", "es_unemployment"):
        check(f"{ind}: at least 24 of the 27 EU countries", cov.get(ind, 0) >= 24, str(cov.get(ind)))
    for ind in ("mir_cob_nfc", "bls_std_nfc", "sup_roe"):  # these ECB sources cover the members of the euro area only
        check(f"{ind}: at least 17 euro area countries (the source has no data for the other EU countries)", cov.get(ind, 0) >= 17, str(cov.get(ind)))
    check("Luxembourg has the main indicators for the example (rates, loan stocks, survey, profitability)", all(q("SELECT 1 FROM ext_series WHERE ref_area = 'LU' AND indicator = ? LIMIT 1", i) for i in ("mir_cob_nfc", "bsi_loans_nfc", "bls_dem_nfc", "cbd_nii", "sup_nim")))
    check("the euro area aggregate and the market rates are there", q("SELECT 1 FROM ext_series WHERE indicator = 'euribor_3m' AND ref_area = 'U2'") and q("SELECT 1 FROM ext_series WHERE indicator = 'estr_daily' AND ref_area = 'U2'"))
    bad = q("SELECT indicator, country, period, value FROM v_ext_obs WHERE indicator LIKE 'mir\\_%' ESCAPE '\\' AND (value < -1 OR value > 40) LIMIT 5")
    check("interest rates are between -1% and 40% (consumer credit in some countries is dear)", not bad, str(bad))
    gr = q("SELECT MIN(growth_yoy), MAX(growth_yoy) FROM v_country_growth WHERE indicator = 'bsi_loans_nfc' AND period >= '2024-01' AND country IN (SELECT iso2 FROM ext_country WHERE euro_area = 1)")[0]
    check("annual growth of loans to corporations from the stocks, euro area countries, is between -60% and +100% (no unit error). Stocks of non-euro countries are not comparable (Romania)",
          gr[0] is not None and -0.6 < gr[0] and gr[1] < 1.0, str(gr))
    diff = q("""SELECT c.country, c.growth_yoy * 100, g.value FROM v_country_growth c JOIN v_ext_obs g ON g.indicator = 'growth_loans_nfc' AND g.country = c.country AND g.period = c.period
                WHERE c.indicator = 'bsi_loans_nfc' AND c.country IN ('LU', 'DE', 'FR', 'IT', 'ES') AND c.period = (SELECT MAX(period) FROM v_ext_obs WHERE indicator = 'growth_loans_nfc')""")
    check("the ECB growth rate and the growth computed from the stocks are within 5 points for LU, DE, FR, IT, ES (the ECB rate is adjusted for reclassifications)", len(diff) == 5 and all(abs(a - b) < 5 for _, a, b in diff), str(diff))
    flows = {r[0]: r[1:] for r in q("SELECT flow, COUNT(*), COUNT(DISTINCT ref_area), MIN(first_period) FROM ext_series WHERE flow IN ('MIR', 'BSI', 'BLS', 'CBD2', 'SUP', 'SSI') GROUP BY flow")}
    if not flows.get("CBD2") or flows["CBD2"][0] < 10000:
        print("  skipped (the bulk pull is not done: run scripts/pull_ext.py bulk)")
        return
    check("bulk pull: all 6 dataflows are stored with the full set of series (MIR 7,000+, BSI 6,000+, BLS 20,000+, CBD2 50,000+, SUP 10,000+, SSI 600+)",
          all(flows.get(f, (0,))[0] >= n for f, n in {"MIR": 7000, "BSI": 6000, "BLS": 20000, "CBD2": 50000, "SUP": 10000, "SSI": 600}.items()), str(flows))
    check("bulk pull: the history of the bank rates and balance sheet starts in 1999 or 2000", flows["MIR"][2] <= "2000-12-31" and flows["BSI"][2] <= "2000-12-31", f"{flows['MIR'][2]} {flows['BSI'][2]}")
    n_rate = q("SELECT COUNT(DISTINCT ref_area) FROM ext_series WHERE concept = 'MIR/B.L21.A.R.A.2250.EUR.N'")[0][0]
    n_stock = q("SELECT COUNT(DISTINCT ref_area) FROM ext_series WHERE concept = 'BSI/N.A.L20.A.1.U2.2250.Z01.E'")[0][0]
    check("the same concept in many countries: household overnight deposit rate (19 or more) and the deposit stock (24 or more)", n_rate >= 19 and n_stock >= 24, f"{n_rate} {n_stock}")
    check("geographic groups are stored (11) and every member is a known country", q("SELECT COUNT(DISTINCT group_name) FROM ext_geo_group")[0][0] == 11 and not q("SELECT 1 FROM ext_geo_group WHERE iso2 NOT IN (SELECT iso2 FROM ext_country)"))
    old = q("SELECT 1 FROM v_ext_obs WHERE indicator = 'euribor_3m' AND period = '2006-06'")
    check("the Euribor history starts before the first rate cycle (2005)", bool(old))
    if q("SELECT 1 FROM sqlite_master WHERE name = 'ext_passthrough'"):
        pt = {(r[0], r[1]): r[2] for r in q("SELECT product, cycle, beta FROM ext_passthrough WHERE country = 'U2'")}
        hh = pt.get(("deposits households, overnight", "hike 2022-23"))
        nfc = pt.get(("deposits corporations, agreed maturity, new", "hike 2022-23"))
        check("euro area betas of the 2022-23 cycle are in the known ranges: household overnight deposits below 0.25, new term deposits of corporations 0.7 to 1.05", hh is not None and 0 <= hh < 0.25 and nfc is not None and 0.7 <= nfc <= 1.05, f"{hh} {nfc}")
        check("every beta of the euro area is between -0.2 and 1.5", all(-0.2 <= b <= 1.5 for b in pt.values() if b == b), str({k: v for k, v in pt.items() if v == v and not -0.2 <= v <= 1.5}))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    test_helpers()
    test_pull()
    test_failures()
    test_bulk()
    test_analytics()
    test_benchmark()
    test_real_database()
    if FAILED:
        print(f"\n{len(FAILED)} check(s) failed: " + "; ".join(FAILED))
        return 1
    print("\nall external statistics checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
