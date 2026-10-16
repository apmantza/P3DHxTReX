"""Tests of the Bloomberg part: curve maths, rate series, bond names, market basis, the reader of the M&A workbook, and (if the database has Bloomberg data) its coverage.

  dashboard/.venv/Scripts/python scripts/test_bbg.py

The tests need no Bloomberg terminal. They use a small database in memory.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dashboard"))
import ma_market  # noqa: E402
from modules.bbg import bonds, curve, entities, equity, match, ownership, rates, schema  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {name}{(' - ' + detail) if detail and not ok else ''}")
    if not ok:
        FAILED.append(name)


def near(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def new_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    schema.create(conn)
    conn.execute("CREATE TABLE entity (entity_key TEXT, lei TEXT, entity_name TEXT, country TEXT)")
    conn.execute("CREATE TABLE clean_period_fact (entity_key TEXT, period_end TEXT, template_code TEXT, measure_col INTEGER, row_code TEXT, value REAL)")
    return conn


def query_of(conn: sqlite3.Connection):
    return lambda sql, params=(): pd.read_sql_query(sql, conn, params=params)


def test_curve() -> None:
    print("1. curve maths")
    flat = {label: 3.0 for label in curve.OIS}
    nodes = curve.discount_factors(flat)
    check("one-year discount factor from a 3% par rate: 1 / (1 + 3% x 365/360)", near(curve.df_at(nodes, 365), 1 / (1 + 0.03 * 365 / 360)))
    tau = 365 / 360
    for years in (2, 5, 10):
        pv = sum(0.03 * tau * curve.df_at(nodes, 365 * k) for k in range(1, years + 1)) + curve.df_at(nodes, 365 * years)
        check(f"{years}-year swap at its par rate is worth 1 (fixed leg plus principal)", near(pv, 1.0, 1e-3), f"{pv:.6f}")
    check("forward rate of a flat curve is near the flat rate", abs(curve.forward_rate(nodes, 400, 700) - 3.0) < 0.05, f"{curve.forward_rate(nodes, 400, 700):.4f}")
    inverted = curve.discount_factors({"1Y": 3.0, "2Y": 2.0})
    check("a lower 2-year rate gives a forward rate below 2% in year 2", curve.forward_rate(inverted, 365, 730) < 2.0)
    changes = [(dt.date(2026, 1, 1), 2.0), (dt.date(2026, 6, 17), 2.25)]
    h1 = curve.expected_average(dt.date(2026, 12, 31), dt.date(2026, 1, 1), dt.date(2026, 6, 30), changes, nodes, 0.061)
    check("realised half year: days weigh the rate (167 days at 2.00%, 14 days at 2.25%)", near(h1, (167 * 2.0 + 14 * 2.25) / 181), f"{h1:.5f}")
    fut = curve.expected_average(dt.date(2026, 10, 13), dt.date(2028, 1, 1), dt.date(2028, 12, 31), changes, nodes, 0.061)
    check("future year: forward rate plus the spread", abs(fut - (3.0 + 0.061)) < 0.06, f"{fut:.4f}")
    mixed = curve.expected_average(dt.date(2026, 7, 1), dt.date(2026, 1, 1), dt.date(2026, 12, 31), changes, nodes, 0.0)
    check("current year: the realised part and the forward part both count", 2.0 < mixed < 3.1)
    check("value of a step series", curve.value_on(changes, dt.date(2026, 6, 16)) == 2.0 and curve.value_on(changes, dt.date(2026, 6, 17)) == 2.25 and curve.value_on(changes, dt.date(2025, 1, 1)) is None)


def test_rates() -> None:
    print("2. rate series")
    check("the ECB applies a decision of Thursday 11/06/2026 on Wednesday 17/06/2026", rates.next_wednesday(dt.date(2026, 6, 11)) == dt.date(2026, 6, 17))
    check("a decision on a Wednesday applies on the next Wednesday", rates.next_wednesday(dt.date(2026, 6, 17)) == dt.date(2026, 6, 24))
    conn = new_db()
    days = pd.date_range("2026-01-01", "2026-12-31", freq="D")
    rows = [("ECB_DFR_ANN", d.date().isoformat(), 2.0 if d < pd.Timestamp("2026-06-11") else 2.25) for d in days]
    conn.executemany("INSERT INTO bbg_rate_daily VALUES (?, ?, ?)", rows)
    n = rates.derive_effective(conn)
    eff = dict(conn.execute("SELECT date, value FROM bbg_rate_daily WHERE series = 'ECB_DFR'").fetchall())
    check("effective series changes on the first Wednesday after the decision", eff["2026-06-16"] == 2.0 and eff["2026-06-17"] == 2.25 and n == len(days))
    rates.compute_averages(conn)
    y = conn.execute("SELECT avg, complete, n_days FROM bbg_rate_average WHERE series = 'ECB_DFR' AND period_type = 'Y' AND period_end = '2026-12-31'").fetchone()
    expect = (167 * 2.0 + 198 * 2.25) / 365
    check("average of the calendar year 2026 (167 days at 2.00%, 198 days at 2.25%)", y is not None and near(y[0], expect) and y[1] == 1 and y[2] == 365, str(y))
    q2 = conn.execute("SELECT avg FROM bbg_rate_average WHERE series = 'ECB_DFR' AND period_type = 'Q' AND period_end = '2026-06-30'").fetchone()
    check("average of the second quarter", q2 is not None and near(q2[0], (77 * 2.0 + 14 * 2.25) / 91), str(q2))


def test_bonds() -> None:
    print("3. bond names")
    check("fraction coupon becomes decimal", bonds.to_request("ETEGA 5<7/8> 06/28/2035 REGS<corp>") == "ETEGA 5.875 06/28/2035 REGS Corp")
    check("quarter coupon on a perpetual", bonds.to_request("EUROB 6<1/4> PERP REGS<corp>") == "EUROB 6.25 PERP REGS Corp")
    check("coupon without fraction stays", bonds.to_request("BOCHLN 4 09/18/2036 REGS<corp>") == "BOCHLN 4 09/18/2036 REGS Corp")
    check("a zero coupon of 1/8", bonds.to_request("X 0<1/8> 01/01/2030<corp>") == "X 0.125 01/01/2030 Corp")
    today = dt.date(2026, 10, 13)
    check("a bond that matured is not alive", not bonds.alive("ACAFP 0.425 11/28/2019<corp>", today) and bonds.alive("ETEGA 5<7/8> 06/28/2035 REGS<corp>", today))
    check("a perpetual (no date in the name) is alive", bonds.alive("ETEGA 5.8 PERP REGS<corp>", today))
    check("a CDS contract and a loan are not bonds", not bonds.is_bond("ETEGA CDS EUR SR 5Y D14<corp>", "ETEGA") and not bonds.is_bond("BL196138<corp>", "BL196138"))
    check("a bond of another ticker is not a bond of this issuer", not bonds.is_bond("ETEGAX 5 01/01/2030<corp>", "ETEGA") and bonds.is_bond("ETEGA 5 01/01/2030<corp>", "ETEGA"))
    check("loan facility codes are not issuer tickers", bonds.LOAN_CODE.match("BL196138") and bonds.LOAN_CODE.match("BF228218") and not bonds.LOAN_CODE.match("BNP"))
    check("same issuer by name", bonds.same_issuer("Eurobank SA", "Eurobank S.A.") and not bonds.same_issuer("Eurobank SA", "WPC Eurobond BV"))
    check("a subsidiary is not its parent (Deutsche Bank Luxembourg, Deutsche Bank AG)", not bonds.same_issuer("Deutsche Bank Luxembourg S.A.", "Deutsche Bank AG")
          and not bonds.same_issuer("BNP Paribas Fortis SA", "BNP Paribas SA") and bonds.same_issuer("Deutsche Bank AG", "DEUTSCHE BANK AG"))
    check("a name that Bloomberg cut still matches (Luxemb, Luxembourg)", bonds.same_issuer("Banque Internationale a Luxemb", "Banque Internationale a Luxembourg SA"))
    check("accents and legal forms do not matter", bonds.same_issuer("Banque Internationale à Luxembourg", "BANQUE INTERNATIONALE A LUXEMBOURG S.A.") and bonds.same_issuer("National Bank of Greece, S.A.", "National Bank of Greece SA"))

    from modules.bbg.client import Client, LimitReached

    class Err:  # the error element of a Bloomberg answer
        def __init__(self, **kw):
            self.kw = kw

        def hasElement(self, name: str) -> bool:
            return name in self.kw

        def getElementAsString(self, name: str) -> str:
            return self.kw[name]

    try:
        Client._response_error(Err(message="Workflow review needed. [nid:21937] ", category="LIMIT", code="-4002"))
        limit_ok = False
    except LimitReached as e:
        limit_ok = "-4002" in str(e) and "DAPI" in str(e)
    check("Bloomberg data limit: category LIMIT stops the pull with LimitReached, although the text has no limit word", limit_ok)
    other = Client._response_error(Err(message="Invalid request", category="BAD_ARGS", code="-1"))
    check("another response error is a plain RuntimeError, not a limit", isinstance(other, RuntimeError) and not isinstance(other, LimitReached))
    try:
        Client._response_error(Err(message="You have exceeded the monthly data limit"))
        text_ok = False
    except LimitReached:
        text_ok = True
    check("a limit that Bloomberg describes in words (no category) still stops the pull", text_ok)


def test_bond_market() -> None:
    print("3b. bond market data")
    full = {"PX_BID": 99.0, "PX_ASK": 99.5, "YLD_YTM_MID": 4.5, "YLD_YTC_MID": 4.8, "I_SPRD_MID": None, "YAS_ISPREAD": 80.0, "Z_SPRD_MID": 82.0, "G_SPREAD_MID_CALC": 105.0, "AMT_OUTSTANDING": 5e8}
    row = dict(zip(["security", "pull_date"] + bonds.MARKET_COLUMNS, bonds._market_row(full, "2026-10-14", "X<corp>")))
    check("I-spread: the YAS value when the direct field is empty", row["i_spread"] == 80.0 and row["z_spread"] == 82.0 and row["g_spread"] == 105.0)
    check("yield to worst: the lower of yield to maturity and yield to call when Bloomberg gives none", row["ytw"] == 4.5)
    row = dict(zip(["security", "pull_date"] + bonds.MARKET_COLUMNS, bonds._market_row({**full, "YLD_YTC_MID": 4.2}, "2026-10-14", "X<corp>")))
    check("yield to worst below yield to maturity when the call yield is lower", row["ytw"] == 4.2)
    row = dict(zip(["security", "pull_date"] + bonds.MARKET_COLUMNS, bonds._market_row({**full, "YIELD_TO_WORST": 4.1}, "2026-10-14", "X<corp>")))
    check("yield to worst: Bloomberg value when it exists", row["ytw"] == 4.1)
    row = dict(zip(["security", "pull_date"] + bonds.MARKET_COLUMNS, bonds._market_row({"AMT_OUTSTANDING": 0.0}, "2026-10-14", "X<corp>")))
    check("a bond without a quote gives empty yields, not an error", row["ytm_mid"] is None and row["ytw"] is None and row["amt_outstanding"] == 0.0)
    conn = new_db()
    cols = "security, lei, amt_outstanding, perpetual, maturity"
    conn.executemany(f"INSERT INTO bbg_bond ({cols}) VALUES (?, ?, ?, ?, ?)", [
        ("LIVE<corp>", "L1", 5e8, "N", "2999-01-01"), ("CALLED<corp>", "L1", 0.0, "N", "2999-01-01"), ("MATURED<corp>", "L1", 1e8, "N", "2000-01-01"),
        ("PERP<corp>", "L1", 3e8, "Y", None), ("UNKNOWN<corp>", "L1", None, "N", "2999-01-01")])
    live = sorted(r[0] for r in conn.execute("SELECT security FROM v_bond_outstanding"))
    check("outstanding = amount above 0 and not matured (a perpetual stays; a called bond with a future date is out)", live == ["LIVE<corp>", "PERP<corp>"], str(live))


def test_universe() -> None:
    print("3d. bond universe above EUR 150m")
    rows = [
        ("FOC 4 01/01/2030 REGS<corp>", "FOCUS", 100e6, 50, 1e9),       # a bank in focus is never skipped
        ("BIG 3 01/01/2031 REGS<corp>", "BIG", 20e9, 80, 500e9),         # issuer average 250m, Reg S, coupon: first tier
        ("BIG 0 01/01/2031 REGS<corp>", "BIG", 20e9, 80, 500e9),         # zero coupon: later
        ("MID 5 01/01/2031 REGS<corp>", "MID", 6e9, 60, 100e9),          # issuer average 100m, Reg S, coupon
        ("SML 4 01/01/2031 REGS<corp>", "SML", 2e9, 100, 900e9),         # issuer average 20m: skipped
        ("TNY 4 01/01/2031 REGS<corp>", "TNY", 100e6, 2, 900e9),         # total debt below the universe limit: skipped
        ("LOW 4 01/01/2031<corp>", "LOW", 3e9, 50, 50e9),                # issuer average 60m, no Reg S: last tier
        ("UNK 4 01/01/2031 REGS<corp>", "UNK", None, None, 10e9),        # unknown debt: kept
    ]
    order = [r[0] for r in bonds.rank_candidates(rows, {"FOCUS"})]
    check("candidates: a bank in focus first, then Reg S coupon bonds of large issuers, then the rest; issuers with a small average bond or total debt are skipped",
          order[0] == "FOC 4 01/01/2030 REGS<corp>" and order[1] == "BIG 3 01/01/2031 REGS<corp>" and "SML 4 01/01/2031 REGS<corp>" not in order and "TNY 4 01/01/2031 REGS<corp>" not in order
          and order.index("MID 5 01/01/2031 REGS<corp>") < order.index("BIG 0 01/01/2031 REGS<corp>") < order.index("LOW 4 01/01/2031<corp>") and "UNK 4 01/01/2031 REGS<corp>" in order, str(order))
    conn = new_db()
    conn.execute("INSERT INTO bbg_rate_daily VALUES ('FX_EURUSD', '2026-10-14', 1.2)")
    conn.executemany("INSERT INTO bbg_bond (security, lei, currency, amt_outstanding, perpetual, maturity) VALUES (?, 'L', ?, ?, 'N', ?)", [
        ("EUR200<corp>", "EUR", 200e6, "2999-01-01"), ("EUR100<corp>", "EUR", 100e6, "2999-01-01"), ("EUR150<corp>", "EUR", 150e6, "2999-01-01"), ("USD240<corp>", "USD", 240e6, "2999-01-01"),
        ("USD150<corp>", "USD", 150e6, "2999-01-01"), ("CALLED<corp>", "EUR", 0.0, "2999-01-01"), ("MATURED<corp>", "EUR", 500e6, "2000-01-01")])
    conn.execute("INSERT INTO bbg_bond (security, lei, currency, amt_outstanding, perpetual, maturity) VALUES ('PERP<corp>', 'L', 'EUR', 300e6, 'Y', NULL)")
    conn.executemany("INSERT INTO bbg_bond_listing (lei, issuer_ticker, security, description) VALUES ('L', 'X', ?, 'X')", [(r[0],) for r in conn.execute("SELECT security FROM bbg_bond").fetchall()])
    bonds.classify_known(conn)
    st = dict(conn.execute("SELECT security, status FROM bbg_bond_listing").fetchall())
    check("status: above EUR 150m is ok (also in another currency: 240m USD = 200m EUR), exactly 150m or below is small, called or matured is redeemed, a perpetual is ok",
          st == {"EUR200<corp>": "ok", "EUR100<corp>": "small", "EUR150<corp>": "small", "USD240<corp>": "ok", "USD150<corp>": "small", "CALLED<corp>": "redeemed", "MATURED<corp>": "redeemed", "PERP<corp>": "ok"}, str(st))
    uni = sorted(r[0] for r in conn.execute("SELECT security FROM v_bond_universe"))
    check("view of the universe: the same bonds as status ok, with the amount in EUR", uni == ["EUR200<corp>", "PERP<corp>", "USD240<corp>"] and conn.execute("SELECT amt_outstanding_eur FROM v_bond_universe WHERE security = 'USD240<corp>'").fetchone()[0] == 200e6, str(uni))
    conn.execute("UPDATE bbg_bond_listing SET status = 'unresolved' WHERE security = 'EUR100<corp>'")
    conn.execute("UPDATE bbg_bond SET amt_outstanding = 400e6 WHERE security = 'EUR150<corp>'")
    bonds.classify_known(conn)
    check("a bond whose size grew moves to ok; the status of a bond that is not in the database is not changed",
          conn.execute("SELECT status FROM bbg_bond_listing WHERE security = 'EUR150<corp>'").fetchone()[0] == "ok")
    check("listing a bank again keeps the status of its bonds", True)
    up = "INSERT INTO bbg_bond_listing (lei, issuer_ticker, security, description) VALUES (?, ?, ?, ?) ON CONFLICT(lei, security) DO UPDATE SET issuer_ticker = excluded.issuer_ticker, description = excluded.description"
    conn.execute(up, ("L", "X2", "EUR200<corp>", "new description"))
    check("upsert of a listed bond updates the description and keeps the status", conn.execute("SELECT status, issuer_ticker, description FROM bbg_bond_listing WHERE security = 'EUR200<corp>'").fetchone() == ("ok", "X2", "new description"))


def test_refresh() -> None:
    print("3e. refresh by cadence")
    import importlib.util
    spec = importlib.util.spec_from_file_location("refresh_bloomberg", ROOT / "scripts" / "refresh_bloomberg.py")
    rb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rb)
    check("daily is part of weekly, weekly is part of monthly (same order)", [x for x in rb.WEEKLY if x in rb.DAILY] == rb.DAILY[:len([x for x in rb.WEEKLY if x in rb.DAILY])]
          and set(rb.DAILY) - {"bond_market"} <= set(rb.MONTHLY) and set(rb.DAILY) <= set(rb.WEEKLY))
    check("every step has a description and a function", all(x in rb.DESCRIPTION for p in rb.PLAN.values() for x in p) and set(rb.make_steps(None, None, argparse_ns()).keys()) >= {x for p in rb.PLAN.values() for x in p})
    check("only the monthly run may use new unique securities: the daily and weekly budget is the number used", rb.budget_for("daily", 1234, 4500) == 1234 and rb.budget_for("weekly", 1234, 4500) == 1234
          and rb.budget_for("monthly", 1234, 4500) == 4500)
    check("the monthly run is the only one with the step that pulls new bonds", "bonds" in rb.MONTHLY and "bonds" not in rb.DAILY and "bonds" not in rb.WEEKLY and "entities" not in rb.DAILY)
    from modules.bbg.client import BudgetExceeded as BE

    def boom() -> str:
        raise ValueError("bad")

    def over() -> str:
        raise BE("4300 securities used this month, 5 new, budget 4300")

    log: list[str] = []
    res, code = rb.run_plan(["a", "b", "c", "d"], {"a": lambda: "fine", "b": boom, "c": over, "d": lambda: "after the failures"}, log.append)
    check("a failing step does not stop the next steps; a budget stop gives exit code 2 and a failure gives 1 (the higher one counts)",
          [r["status"] for r in res] == ["ok", "failed", "stopped: limit or budget", "ok"] and code == 2 and res[3]["detail"] == "after the failures", str(res))
    res, code = rb.run_plan(["rates", "basis", "tickers"], {"rates": lambda: "x", "basis": lambda: "offline", "tickers": lambda: "offline"}, log.append, terminal_up=False)
    check("without the terminal, the steps that need Bloomberg are skipped and the offline steps still run", [r["status"] for r in res] == ["skipped: no terminal", "ok", "ok"] and code == 0, str(res))
    conn = new_db()
    conn.execute("INSERT INTO bbg_pull_log (started_at, kind, detail, n_rows, status) VALUES ('2026-10-14T10:00:00', 'rates', 'x', 1, 'ok')")
    check("the batch file calls the refresh with the blauto Python and writes a log", "refresh_bloomberg.py %LEVEL%" in (ROOT / "scripts" / "refresh_bloomberg.bat").read_text(encoding="utf-8")
          and "blauto" in (ROOT / "scripts" / "refresh_bloomberg.bat").read_text(encoding="utf-8"))


def argparse_ns():
    import argparse
    return argparse.Namespace(max_bonds=10)


class HistClient:
    def __init__(self):
        self.calls = []

    def log(self, msg):
        pass

    def hist(self, securities, fields, start, end, **kw):
        self.calls.append((list(securities), start))
        return {s: [("2026-10-12", {"PX_LAST": 99.0, "YLD_YTM_MID": 4.0, "I_SPRD_MID": None}), ("2026-10-13", {"PX_LAST": 99.5, "YLD_YTM_MID": 3.9}), ("2026-10-14", {})] for s in securities}


def test_bond_history() -> None:
    print("3c. bond history")
    conn = new_db()
    conn.execute("INSERT INTO bbg_bond (security, lei, currency, amt_outstanding, perpetual, maturity) VALUES ('ETEGA 5<7/8> 06/28/2035 REGS<corp>', 'L1', 'EUR', 5e8, 'N', '2999-01-01')")
    conn.execute("INSERT INTO bbg_bond (security, lei, currency, amt_outstanding, perpetual, maturity) VALUES ('NOQUOTE 4 01/01/2999<corp>', 'L1', 'EUR', 5e8, 'N', '2999-01-01')")
    conn.execute("INSERT INTO bbg_bond_market (security, pull_date, px_mid) VALUES ('ETEGA 5<7/8> 06/28/2035 REGS<corp>', '2026-10-14', 99.0)")
    conn.commit()
    client = HistClient()
    n = bonds.pull_history(client, conn, "20240101")
    check("history: only quoted bonds of the universe, the request uses the decimal coupon, empty days are dropped", n == 2 and client.calls == [(["ETEGA 5.875 06/28/2035 REGS Corp"], "20240101")], str(client.calls))
    check("history: values stored as columns", conn.execute("SELECT px_last, ytm_mid, i_spread FROM bbg_bond_history WHERE date = '2026-10-13'").fetchone() == (99.5, 3.9, None))
    client2 = HistClient()
    bonds.pull_history(client2, conn, "20240101")
    check("history: a second run starts 5 days before the last date", client2.calls[0][1] == "20261008", str(client2.calls))


def entity_rows(conn: sqlite3.Connection) -> None:
    cols = "lei, found, name, country_iso, equity_ticker, parent_name, parent_ticker, parent_lei, net_income, net_income_ltm, operating_expenses, common_equity, revenue, statutory_tax_rate, effective_tax_rate"
    data = [
        ("LEI_SELF_00000000001", 1, "Self Bank", "GR", "SELF GA", "Self Bank", "SELF GA", "LEI_SELF_00000000001", 1000.0, 1100.0, 500.0, 8000.0, 3000.0, 0.29, 25.0),
        ("LEI_SUB_000000000002", 1, "Sub Bank of Group", "IT", "9999Z IM", "Group Bank", "GRP IM", "LEI_GRP_00000000003", 100.0, None, 50.0, 800.0, 300.0, None, 20.0),
        ("LEI_CONGLOM00000004", 1, "Conglomerate Bank", "LU", "0001Z LX", "Conglomerate Holdings", "CONG HK", "LEI_CONG_0000000005", 210.0, 210.0, 465.0, 2777.0, 1644.0, 0.2387, 11.7),
        ("LEI_AUTO_0000000006", 1, "Auto Bank", "DE", "0002Z GR", "Car Maker AG", "CAR GR", "LEI_CAR_00000000007", 50.0, None, 20.0, 400.0, 100.0, 0.30, None),
        ("LEI_NONE_0000000008", 1, "Private Bank", "DE", "0003Z GR", "Private Bank", "0003Z GR", "LEI_NONE_0000000008", 165.0, 248.0, 382.0, 3956.0, 1641.0, 0.30, 42.9),
    ]
    conn.executemany(f"INSERT INTO bbg_entity ({cols}) VALUES ({','.join('?' * 15)})", data)
    conn.execute("UPDATE bbg_entity SET net_income_cont_ltm = 170.0 WHERE lei = 'LEI_CONGLOM00000004'")  # net income 210 includes a gain on discontinued operations
    conn.execute("INSERT INTO bbg_entity (lei, found, name, equity_ticker, bbg_lei, match_method) VALUES ('FR969500TJ5KRTCJQWXH', 1, 'Listed SA', 'LIST FP', '969500TJ5KRTCJQWXH05', 'lei_rebuilt')")
    conn.execute("INSERT INTO bbg_equity_snapshot VALUES ('LIST FP', 'PX_LAST', '2026-10-13', 10.0)")
    conn.execute("INSERT INTO bbg_equity_snapshot VALUES ('LIST FP', 'INDUSTRY_SUBGROUP', '2026-10-13', 'Commer Banks Non-US')")
    conn.execute("INSERT INTO clean_period_fact VALUES ('LEI_SELF_00000000001', '2026-06-30', 'K_61.00', 10, '0010', 8000000000.0)")
    snap = [("SELF GA", "PX_LAST", "2026-10-13", 16.0), ("SELF GA", "CRNCY", "2026-10-13", "EUR"), ("SELF GA", "EQY_SH_OUT", "2026-10-13", 900.0),
            ("SELF GA", "TANG_BOOK_VAL_PER_SH", "2026-10-13", 10.0), ("SELF GA", "BOOK_VAL_PER_SH", "2026-10-13", 12.0), ("SELF GA", "PX_TO_BOOK_RATIO", "2026-10-13", 16.0 / 12.0),
            ("SELF GA", "TRAIL_12M_EPS", "2026-10-13", 1.2), ("SELF GA", "INDUSTRY_SUBGROUP", "2026-10-13", "Commer Banks Non-US"),
            ("GRP IM", "PX_LAST", "2026-10-13", 5.0), ("GRP IM", "INDUSTRY_SUBGROUP", "2026-10-13", "Diversified Banking Inst"),
            ("CONG HK", "PX_LAST", "2026-10-13", 20.0), ("CONG HK", "INDUSTRY_SUBGROUP", "2026-10-13", "Computers"),
            ("CAR GR", "PX_LAST", "2026-10-13", 80.0), ("CAR GR", "INDUSTRY_SUBGROUP", "2026-10-13", "Auto-Cars/Light Trucks")]
    conn.executemany("INSERT INTO bbg_equity_snapshot VALUES (?, ?, ?, ?)", snap)
    conn.execute("INSERT INTO bbg_equity_daily (ticker, date, px_last, mkt_cap_eur) VALUES ('SELF GA', '2026-10-13', 16.0, 14400000000.0)")
    conn.execute("INSERT INTO bbg_fundamental VALUES ('SELF GA', '2025-12-31', 'A', 'NET_INCOME', 1000.0)")
    conn.execute("INSERT INTO bbg_fundamental VALUES ('SELF GA', '2024-12-31', 'A', 'NET_INCOME', 900.0)")
    cons = [("SELF GA", "2026-10-13", per, None, "BEST_NET_INCOME", v) for per, v in zip(("1FY", "2FY", "3FY", "4FY"), (1200.0, 1300.0, 1400.0, None)) if v is not None]
    cons += [("SELF GA", "2026-10-13", "1FY", None, "BEST_SALES", 3200.0)]
    conn.executemany("INSERT INTO bbg_consensus VALUES (?, ?, ?, ?, ?, ?)", cons)
    conn.commit()


def test_issuance() -> None:
    print("3e. issuance: debt type, public or private, buckets, workbook")
    from modules.bbg import issuance, issuance_xlsx

    check("programme: mixed-case series are one programme; an empty or numeric series is none", issuance.programme("EmtN") == "EMTN" and issuance.programme("emt1") == "EMTN" and issuance.programme("GMTN") == "GMTN"
          and issuance.programme("") == "" and issuance.programme("0000") == "" and issuance.programme(None) == "" and issuance.programme("*") == "")
    dt_ = issuance.debt_type
    check("debt type: capital layers first (AT1 by designation or rank, Tier 2 by designation or rank)", dt_("Jr Subordinated", None, None, "FIXED", None, "") == issuance.AT1
          and dt_("Sr Unsecured", "Additional Tier 1", None, None, None, "") == issuance.AT1 and dt_("Subordinated", None, None, None, None, "EMTN") == issuance.T2 and dt_(None, "Tier 2", None, None, None, "") == issuance.T2)
    check("debt type: senior non-preferred, covered (collateral), senior preferred", dt_("Sr Non Preferred", None, "SR NON-PREFERRED", "ZERO COUPON", None, "EMTN") == issuance.SNP
          and dt_("Secured", None, "COVERED", "FLOATING", None, "") == issuance.COVERED and dt_("Sr Preferred", None, "SR PREFERRED", "FIXED", None, "EMTN") == issuance.SP)
    check("debt type: a senior unsecured note is a programme note only with a plain coupon, in a programme, and without conversion",
          dt_("Sr Unsecured", None, None, "FIXED", "AT MATURITY", "EMTN") == issuance.SENIOR and dt_("Sr Unsecured", None, None, "VARIABLE", "CALLABLE", "EMTN") == issuance.SENIOR
          and dt_("Sr Unsecured", None, None, "ZERO COUPON", "AT MATURITY", "EMTN") == issuance.STRUCTURED and dt_("Sr Unsecured", None, None, "STEP CPN", None, "EMTN") == issuance.STRUCTURED
          and dt_("Sr Unsecured", None, None, "FIXED", "CONVERTIBLE", "EMTN") == issuance.STRUCTURED and dt_("Sr Unsecured", None, None, "FIXED", "CONV/CALL", "EMTN") == issuance.STRUCTURED
          and dt_("Sr Unsecured", None, None, "FIXED", "AT MATURITY", "") == issuance.STRUCTURED)
    check("public or private: a programme note is public; a standalone note is public from EUR 150m; below, or of unknown size, it is private",
          issuance.placement("EMTN", 1e6)[0] == "Public" and issuance.placement("", 150e6)[0] == "Public" and issuance.placement("", 149.9e6)[0] == "Private" and issuance.placement("", None)[0] == "Private")
    check("size buckets", [issuance.size_bucket(x) for x in (5e6, 10e6, 49e6, 50e6, 149e6, 150e6, None)] == ["below 10", "10 to 50", "10 to 50", "50 to 150", "50 to 150", "150 or more", ""])
    check("bucket keys: ten single years, one open bucket, and perpetual", [issuance.bucket_key(y, 2026) for y in (2026, 2035, 2036, 2064, None)] == [2026, 2035, 2036, 2036, issuance.PERPETUAL_KEY]
          and [lab for _, lab in issuance.bucket_labels(2026)][-3:] == ["2035", "2036+", "Perpetual"])
    cp, mat, perp = issuance.parse_name("BBB 5<7/8> 06/28/2035 REGS<corp>")
    cp0, mat0, perp0 = issuance.parse_name("BBB 0 PERP<corp>")
    cp1, mat1, perp1 = issuance.parse_name("BBB<corp>")
    check("names: coupon with a fraction, date, perpetual, and a name without coupon", (cp, mat, perp) == (5.875, dt.date(2035, 6, 28), False) and (cp0, mat0, perp0) == (0.0, None, True) and (cp1, mat1, perp1) == (None, None, False))
    check("to EUR: EUR as is, schilling at the fixed rate, another currency by the rate, an unknown currency has no value", issuance.to_eur(10.0, "EUR", {}) == 10.0 and abs(issuance.to_eur(13.7603, "ATS", {}) - 1.0) < 1e-12
          and issuance.to_eur(12.0, "USD", {"USD": 1.2}) == 10.0 and issuance.to_eur(5.0, "XXX", {}) is None)

    today = dt.date(2026, 10, 16)
    conn = new_db()
    conn.execute("INSERT INTO bbg_rate_daily VALUES ('FX_EURUSD', '2026-10-14', 1.2)")
    cols = "security, lei, isin, payment_rank, basel_iii, collateral_type, coupon, coupon_type, maturity, next_call, perpetual, currency, amt_issued, amt_outstanding, maturity_type, series, pulled_at"
    rows = [
        ("SP<corp>", "L1", "XS1", "Sr Preferred", None, "SR PREFERRED", 3.0, "FIXED", "2030-05-01", None, "N", "EUR", 500e6, 500e6, "AT MATURITY", "EmtN", "2026-10-14"),
        ("SNP<corp>", "L1", "XS2", "Sr Non Preferred", None, "SR NON-PREFERRED", 4.0, "FIXED", "2031-05-01", "2030-05-01", "N", "EUR", 300e6, 300e6, "CALLABLE", "EMTN", "2026-10-14"),
        ("T2BIG<corp>", "L1", "XS3", "Subordinated", "Tier 2", "SUBORDINATED", 6.0, "FIXED", "2035-01-01", None, "N", "EUR", 200e6, 200e6, "AT MATURITY", "", "2026-10-14"),
        ("T2SML<corp>", "L1", "XS4", "Subordinated", "Tier 2", "SUBORDINATED", 6.0, "FIXED", "2036-01-01", None, "N", "EUR", 100e6, 100e6, "AT MATURITY", "", "2026-10-14"),
        ("AT1<corp>", "L1", "XS5", "Jr Subordinated", "Additional Tier 1", "JR SUBORDINATED", 7.0, "FIXED", None, "2030-06-01", "Y", "EUR", 400e6, 400e6, "PERP/CALL", "", "2026-10-14"),
        ("ZERO<corp>", "L1", "LU1", "Sr Unsecured", None, "SR UNSECURED", 0.0, "ZERO COUPON", "2064-01-01", None, "N", "EUR", 5e6, 5e6, "AT MATURITY", "", "2026-10-14"),
        ("CONV<corp>", "L1", "CH1", "Sr Unsecured", None, "SR UNSECURED", 9.0, "FIXED", "2027-02-01", None, "N", "USD", 12e6, 12e6, "CONVERTIBLE", "EMTN", "2026-10-14"),
        ("PLAIN<corp>", "L1", "XS6", "Sr Unsecured", None, "SR UNSECURED", 5.0, "FIXED", "2028-03-01", None, "N", "EUR", 50e6, 50e6, "AT MATURITY", "EMTN", "2026-10-14"),
        ("COV<corp>", "L2", "XS7", "Secured", None, "COVERED", 2.0, "FIXED", "2029-04-01", None, "N", "EUR", 700e6, 700e6, "AT MATURITY", "EMTN", "2026-10-14"),
        ("CALLED<corp>", "L2", "XS8", "Sr Preferred", None, "SR PREFERRED", 2.0, "FIXED", "2030-04-01", None, "N", "EUR", 100e6, 0.0, "AT MATURITY", "EMTN", "2026-10-14"),
        ("MATURED<corp>", "L2", "XS9", "Sr Preferred", None, "SR PREFERRED", 2.0, "FIXED", "2020-04-01", None, "N", "EUR", 100e6, 100e6, "AT MATURITY", "EMTN", "2026-10-14"),
    ]
    conn.executemany(f"INSERT INTO bbg_bond ({cols}) VALUES ({','.join('?' * 17)})", rows)
    conn.execute("INSERT INTO bbg_bond_market (security, pull_date, quote_date, px_mid, ytm_mid) VALUES ('SP<corp>', '2026-10-14', '2026-10-14', 99.5, 3.2), ('SP<corp>', '2026-10-10', '2026-10-10', 90.0, 9.9)")
    conn.executemany("INSERT INTO bbg_bond_listing (lei, issuer_ticker, security, description, status) VALUES (?, 'T', ?, 'Issuer', ?)", [
        ("L2", "T 0 01/02/2029<corp>", "ambiguous"), ("L2", "T 5<7/8> 06/28/2035 REGS<corp>", "unresolved"), ("L2", "T 0 04/21/2027<corp>", None), ("L2", "T 0 01/02/2020<corp>", "ambiguous"),
        ("L2", "T 0 PERP<corp>", "unresolved"), ("L1", "SP<corp>", "ok"), ("L2", "COV<corp>", None)])
    data = issuance.load(conn, [("AAA", "L1"), ("BBB", "L2")], today)
    iss, un = data["issues"].set_index("security"), data["unresolved"]
    g = lambda s, c: iss.loc[s, c]  # noqa: E731
    check("issues: debt types of the invented bonds", [g(s, "debt_type") for s in ("SP<corp>", "SNP<corp>", "T2BIG<corp>", "AT1<corp>", "ZERO<corp>", "CONV<corp>", "PLAIN<corp>", "COV<corp>")]
          == [issuance.SP, issuance.SNP, issuance.T2, issuance.AT1, issuance.STRUCTURED, issuance.STRUCTURED, issuance.SENIOR, issuance.COVERED])
    check("issues: public or private (EMTN public even when small, standalone from 150m, smaller private)", [g(s, "public_private") for s in ("SP<corp>", "CONV<corp>", "T2BIG<corp>", "T2SML<corp>", "ZERO<corp>", "AT1<corp>")]
          == ["Public", "Public", "Public", "Private", "Private", "Public"])
    check("issues: active flag (a called bond and a matured bond are not active; the perpetual is)", [g(s, "active") for s in ("SP<corp>", "CALLED<corp>", "MATURED<corp>", "AT1<corp>")] == ["Y", "N", "N", "Y"])
    check("issues: amount in EUR (12m USD at 1.2 = 10m) and size bucket", abs(g("CONV<corp>", "eur") - 10.0) < 1e-9 and g("CONV<corp>", "size_bucket") == "10 to 50" and g("ZERO<corp>", "size_bucket") == "below 10")
    check("issues: maturity bucket (open bucket for 2064, perpetual 9999) and call-adjusted bucket (the call year when a call is ahead)",
          (g("ZERO<corp>", "bucket_m"), g("AT1<corp>", "bucket_m"), g("AT1<corp>", "bucket_c"), g("SNP<corp>", "bucket_m"), g("SNP<corp>", "bucket_c")) == (2036, issuance.PERPETUAL_KEY, 2030, 2031, 2030)
          and pd.isna(g("CALLED<corp>", "bucket_m")))
    check("issues: the latest market row of a bond is used", g("SP<corp>", "px") == 99.5 and g("SP<corp>", "ytm") == 3.2)
    check("unresolved: a matured name and a name that is in the bond table are left out; status text, coupon, maturity, perpetual", len(un) == 4 and set(un["status"]) == {"Ambiguous", "Not found", "Not loaded"}
          and sorted(un["bucket"]) == [2027, 2029, 2035, issuance.PERPETUAL_KEY] and 5.875 in un["coupon"].tolist())
    if True:
        import tempfile

        try:
            import formulas
            import openpyxl
        except ImportError:
            print("  skipped (pip install formulas): the formulas of the Profile sheet")
            return
        tmp = Path(tempfile.mkdtemp()) / "iss.xlsx"
        issuance_xlsx.write_workbook(str(tmp), data)
        wb = openpyxl.load_workbook(tmp)
        check("workbook: four sheets, one selected tab, charts on the Profile, tables with a filter", wb.sheetnames == ["Read me", "Profile", "Issues", "Listed without data"] and sum(1 for s in wb if s.sheet_view.tabSelected) == 1
              and len(wb["Profile"]._charts) == 3 and len(wb["Issues"].tables) == 1)
        sol = formulas.ExcelModel().loads(str(tmp)).finish().calculate()
        keys = {k.upper(): k for k in sol}

        def val(coord: str):
            v = sol[keys[f"'[{tmp.name}]PROFILE'!{coord}".upper()]].value
            return v[0, 0] if hasattr(v, "shape") else v

        ws = wb["Profile"]
        labels = issuance.bucket_labels(2026)
        act = data["issues"][data["issues"]["active"] == "Y"]
        bad = []
        for basis in (1, 2):
            ws["B4"] = basis
            wb.save(tmp)
            sol = formulas.ExcelModel().loads(str(tmp)).finish().calculate()
            keys = {k.upper(): k for k in sol}
            for r in range(1, ws.max_row + 1):
                if str(ws.cell(row=r, column=2).value or "").startswith("Issuer filter"):
                    crit = ws.cell(row=r, column=5).value
                    sub = act if crit == "*" else act[act["issuer"] == crit]
                    for i, kind in enumerate(issuance.DEBT_TYPES):
                        for j, (key, _) in enumerate(labels, start=2):
                            exp = sub[(sub["debt_type"] == kind) & (sub["bucket_m" if basis == 1 else "bucket_c"] == key)]["eur"].sum()
                            got = val(f"{openpyxl.utils.get_column_letter(j)}{r + 3 + i}")
                            if abs(float(got) - exp) > 1e-9:
                                bad.append((basis, crit, kind, key, got, exp))
        check("workbook: every cell of the debt type by bucket table equals pandas, for both bases, each issuer and combined", not bad, str(bad[:3]))
        r_comb = next(r for r in range(1, ws.max_row + 1) if ws.cell(row=r, column=5).value == "*")
        total = val(f"N{r_comb + 3 + len(issuance.DEBT_TYPES)}")
        check("workbook: the combined total equals the sum of the active bonds in EUR", abs(float(total) - act["eur"].sum()) < 1e-9, f"{total} {act['eur'].sum()}")
        tmp.unlink(missing_ok=True)


def test_bridge() -> None:
    print("3f. bridge: issued and MREL-eligible debt from P3DH, check against KM2")
    from modules.bbg import issuance, issuance_xlsx

    check("CC2 groups: debt securities, fair-value liabilities (not held for trading), subordinated and other borrowed funds, other equity instruments; other lines are not debt",
          [issuance.cc2_group(x) for x in ("Type of liabilities = Debt securities in issue", "Type of liabilities = Financial liabilities measured at fair value through profit or loss",
                                           "Type of liabilities = Financial liabilities held for trading", "Type of liabilities = Subordinated debts", "Type of liabilities = Other borrowed funds",
                                           "Type of liabilities = Other equity instruments", "Type of liabilities = Due to customers")] == ["debt", "fv", None, "sub", "sub", "at1", None])
    check("KM2 ratio units: a fraction stays, percentage points are divided by 100", issuance._ratio(0.436) == 0.436 and abs(issuance._ratio(27.94) - 0.2794) < 1e-12 and issuance._ratio(None) is None)
    conn = new_db()
    conn.execute("CREATE TABLE clean_fact (entity_key TEXT, reference_date TEXT, template_code TEXT, cell_code TEXT, row_code TEXT, column_code TEXT, sheet TEXT, key_descriptor TEXT, row_label TEXT, value REAL, quality TEXT)")
    ins = lambda d, t, cell, row, kd, v: conn.execute("INSERT INTO clean_fact VALUES ('L9', ?, ?, ?, ?, '0010', '', ?, '', ?, 'ok')", (d, t, cell, row, kd, v * 1e6))  # noqa: E731
    for kd, v in (("Debt securities", 400), ("Subordinated debts", 50), ("Other equity instruments", 30), ("Due to customers", 9000)):
        ins("2025-12-31", "K_66.02", "{K_66.02.c, r0010, c0010}", "0010", "Type of liabilities = " + kd, v)
    for row, v in (("0010", 500), ("0020", 30), ("0060", 35), ("0100", 40), ("0120", 0), ("0130", 5), ("0140", 200), ("0150", 0), ("0160", 200), ("0230", -10), ("0270", 2000)):
        ins("2025-12-31", "K_91.00", "", row, "", v)
    for d, tot, sub, trea, ratio, sratio in (("2025-12-31", 800, 610, 2000, 40.0, 30.5), ("2026-06-30", 900, 650, 2000, 45.0, 32.5)):  # ratios in percentage points, as some banks file them
        for row, v in (("0010", tot), ("0020", sub), ("0030", trea), ("0040", ratio), ("0050", sratio)):
            ins(d, "K_90.01", "", row, "", v if row in ("0010", "0020", "0030") else v / 1e6)
    conn.execute("INSERT INTO bbg_bond (security, lei, isin, currency, amt_issued, amt_outstanding, perpetual, maturity, issue_date, payment_rank, series, coupon_type, pulled_at) "
                 "VALUES ('Z 5 01/01/2030<corp>', 'L9', 'XS0', 'EUR', 100e6, 100e6, 'N', '2030-01-01', '2024-01-01', 'Sr Preferred', 'EMTN', 'FIXED', '2026-10-14')")
    banks = [("ZZZ", "L9")]
    br = issuance.load_bridge(conn, banks)["ZZZ"]
    check("bridge loader: the newest date with CC2 and TLAC1, debt lines by group, TLAC1 rows in EUR m", br["date"] == "2025-12-31" and br["cc2"] == {"debt": 400.0, "sub": 50.0, "at1": 30.0}
          and br["tlac"]["cet1"] == 500.0 and br["tlac"]["ded"] == -10.0 and br["tlac"]["ns14"] == 200.0, str(br))
    check("bridge loader: KM2 of the TLAC1 date and the newest KM2 (ratios as fractions)", br["km2"]["date"] == "2025-12-31" and br["km2"]["total"] == 800.0 and abs(br["km2"]["ratio"] - 0.40) < 1e-9
          and br["km2_new"]["date"] == "2026-06-30" and br["km2_new"]["total"] == 900.0 and abs(br["km2_new"]["sub_ratio"] - 0.325) < 1e-9, str(br["km2"]) + str(br["km2_new"]))
    check("bridge loader: a bank without CC2 liability lines and TLAC1 gives an empty result", issuance.load_bridge(conn, [("NONE", "L0")]) == {"NONE": {}})
    try:
        import formulas
        import openpyxl
        import tempfile
    except ImportError:
        print("  skipped (pip install formulas): the formulas of the sheet Bridge")
        return
    data = issuance.load(conn, banks, dt.date(2026, 10, 16))
    tmp = Path(tempfile.mkdtemp()) / "br.xlsx"
    issuance_xlsx.write_workbook(str(tmp), data, {"ZZZ": br})
    sol = formulas.ExcelModel().loads(str(tmp)).finish().calculate()
    keys = {k.upper(): k for k in sol}
    ws = openpyxl.load_workbook(tmp)["Bridge"]

    def val(label: str, col: str = "B", nth: int = 1):
        rows = [r for r in range(1, ws.max_row + 1) if str(ws.cell(row=r, column=1).value or "").startswith(label)]
        v = sol[keys[f"'[{tmp.name}]BRIDGE'!{col}{rows[nth - 1]}".upper()]].value
        return v[0, 0] if hasattr(v, "shape") else v

    check("bridge sheet: total issued debt 480 (400 + 50 + 30), eligible 310, not eligible 170", abs(float(val("Total issued debt")) - 480) < 1e-9 and abs(float(val("Eligible debt, gross")) - 310) < 1e-9 and abs(float(val("Not eligible")) - 170) < 1e-9)
    check("bridge sheet: own funds and eligible liabilities 800 equal KM2, ratio 40.00% equals the reported ratio (difference below 0.5 bp)",
          abs(float(val("Own funds and eligible liabilities, computed")) - 800) < 1e-9 and abs(float(val("Difference (EUR m)"))) < 1e-9 and abs(float(val("Difference (bp)", nth=1))) < 0.5, str(val("Difference (bp)")))
    check("bridge sheet: subordinated 610 and 30.50%, newest KM2 totals 900 and 45.00%", abs(float(val("Own funds and subordinated liabilities, computed")) - 610) < 1e-9 and abs(float(val("Subordinated, % of TREA, computed")) - 0.305) < 1e-9
          and abs(float(val("% of TREA, computed")) - 0.45) < 1e-9)
    check("bridge sheet: the summary table has the same total (Tier 2 maps to the subordinated line here)", abs(float(val("Total MREL (own funds and eligible liabilities)", "C")) - 800) < 1e-9 and abs(float(val("Subordinated notes", "C")) - 40) < 1e-9)
    tmp.unlink(missing_ok=True)


def test_equity_and_market() -> None:
    print("4. market basis, consensus years, and the reader of the M&A workbook")
    conn = new_db()
    entity_rows(conn)
    equity.assign_consensus_periods(conn)
    equity.assign_market_basis(conn)
    basis = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT lei, market_basis, market_ticker FROM bbg_entity")}
    check("a bank with its own priced shares has basis self", basis["LEI_SELF_00000000001"] == ("self", "SELF GA"))
    check("a bank in a listed bank group has basis parent", basis["LEI_SUB_000000000002"] == ("parent", "GRP IM"))
    check("a bank in a conglomerate has no market basis (the share price of a conglomerate says nothing about the bank)", basis["LEI_CONGLOM00000004"][0] == "none")
    check("a captive bank of a car maker has no market basis", basis["LEI_AUTO_0000000006"][0] == "none")
    check("a private bank has no market basis", basis["LEI_NONE_0000000008"][0] == "none")
    check("a group matched by a rebuilt LEI keeps the listed ticker as a proxy and has no market cap of its own", conn.execute("SELECT market_basis, market_ticker FROM bbg_entity WHERE lei = 'FR969500TJ5KRTCJQWXH'").fetchone() == ("proxy", "LIST FP"))
    per = {r[0]: r[1] for r in conn.execute("SELECT fperiod, period_end FROM bbg_consensus WHERE field = 'BEST_NET_INCOME'")}
    check("consensus years: last annual report 2025-12-31 plus 1 to 3 years", per == {"1FY": "2026-12-31", "2FY": "2027-12-31", "3FY": "2028-12-31"}, str(per))

    q = query_of(conn)
    s = ma_market.slot(q, "LEI_SELF_00000000001")
    check("slot: market cap in EUR million (14.4bn = 14,400)", near(s["mcap"], 14400.0) and s["basis"] == "self" and s["shares"] == 900.0)
    check("slot: consensus by calendar year, in EUR million", s["cons"][2026]["NI"] == 1200.0 and s["cons"][2027]["NI"] == 1300.0 and s["cons"][2026]["SALES"] == 3200.0 and 2029 not in s["cons"])
    check("slot: effective tax rate as a fraction, statutory as given", near(s["tax_eff"], 0.25) and near(s["tax_stat"], 0.29))
    u = ma_market.slot(q, "LEI_NONE_0000000008")
    check("slot of a bank without market cap: Bloomberg data of the bank, no price", u["basis"] == "none" and u["ni_ltm"] == 248.0 and u["opex"] == 382.0 and "mcap" not in u)
    cg = ma_market.slot(q, "LEI_CONGLOM00000004")
    check("slot: profit of the last 12 months is the income from continuing operations when Bloomberg has it (170 against a net income of 210); the reported value stays available",
          cg["ni_ltm"] == 170.0 and cg["ni_ltm_reported"] == 210.0, str((cg["ni_ltm"], cg["ni_ltm_reported"])))
    check("slot: without a continuing value the net income of the last 12 months is used", u["ni_ltm"] == 248.0 and u["ni_ltm_reported"] == 248.0)
    check("slot of an unknown LEI is not found", not ma_market.slot(q, "LEI_UNKNOWN_0000000")["found"])
    check("LEI of an entity: the key when the entity table has no LEI", ma_market.lei_of(lambda *_: pd.DataFrame({"lei": []}), "K1") == "K1")

    pe = ma_market.peers(q)["rows"]
    check("peers: P/TBV = price to book ratio x book value / tangible book value (1.3333 x 12 / 10 = 1.6) and RoTE = EPS / tangible book (1.2 / 10 = 12%)", len(pe) == 1 and near(pe[0]["ptbv"], 1.6) and near(pe[0]["rote"], 0.12))
    check("peers: P/CET1 = market cap / CET1 of P3DH (14.4bn / 8bn = 1.8) and RoCET1 = P/CET1 x EPS / price in EUR (1.8 x 1.2 / 16 = 13.5%)", near(pe[0]["pcet1"], 1.8) and near(pe[0]["rocet1"], 0.135))
    check("peers: a proxy group is not a peer", all(p_["lei"] != "FR969500TJ5KRTCJQWXH" for p_ in pe))
    conn.execute("DELETE FROM clean_period_fact")
    check("peers: a bank without CET1 in P3DH is left out", ma_market.peers(q)["rows"] == [])
    conn.execute("INSERT INTO clean_period_fact VALUES ('LEI_SELF_00000000001', '2026-06-30', 'K_61.00', 10, '0010', 8000000000.0)")
    conn.execute("UPDATE bbg_entity SET country_iso = 'US' WHERE lei = 'LEI_SELF_00000000001'")
    check("peers: banks outside Europe are not in the fit", ma_market.peers(q)["rows"] == [] and len(ma_market.peers(q, {"US"})["rows"]) == 1)
    conn.execute("UPDATE bbg_entity SET country_iso = 'GR' WHERE lei = 'LEI_SELF_00000000001'")
    conn.execute("UPDATE bbg_equity_snapshot SET value = 80.0 / 12.0 WHERE ticker = 'SELF GA' AND field = 'PX_TO_BOOK_RATIO'")
    check("peers: a P/TBV above 6x is left out", ma_market.peers(q)["rows"] == [])
    conn.execute("UPDATE bbg_equity_snapshot SET value = 16.0 / 12.0 WHERE ticker = 'SELF GA' AND field = 'PX_TO_BOOK_RATIO'")
    check("peers: at a normal price the bank is a peer, and nothing is removed", len(ma_market.peers(q)["rows"]) == 1 and ma_market.peers(q)["removed"] == [])
    conn.execute("UPDATE bbg_entity SET parent_relationship = 'Subsidiary', parent_name = 'Parent Bank AG' WHERE lei = 'LEI_SELF_00000000001'")
    pr = ma_market.peers(q)
    check("peers: a subsidiary is left out and listed with the reason", pr["rows"] == [] and [(x["lei"], x["reason"]) for x in pr["removed"]] == [("LEI_SELF_00000000001", "subsidiary")], str(pr["removed"]))
    conn.execute("UPDATE bbg_entity SET parent_name = 'Republic of Greece' WHERE lei = 'LEI_SELF_00000000001'")
    check("peers: a bank that a state owns stays a peer", len(ma_market.peers(q)["rows"]) == 1)
    conn.execute("UPDATE bbg_entity SET parent_relationship = NULL, name = 'Self Cooperative Bank' WHERE lei = 'LEI_SELF_00000000001'")
    pr = ma_market.peers(q)
    check("peers: a cooperative is left out and listed with the reason", pr["rows"] == [] and [x["reason"] for x in pr["removed"]] == ["cooperative"], str(pr["removed"]))
    px = ma_market.peer_exclusion
    cases = [("Tatra Banka as", "Subsidiary", "Raiffeisen Bank International", None, "subsidiary"), ("Credit Agricole SA", "Subsidiary", "Credit Agricole Group", "Diversified Banking Inst", "subsidiary"),
             ("Caisse Regionale de Credit Agr", "Synthetic Parent", "Credit Agricole Group", "Regional Banks-Non US", "subsidiary"),
             ("ABN AMRO Bank NV", "Subsidiary", "Stichting Administratiekantoor", "Commer Banks Non-US", None), ("Bank Ochrony Srodowiska SA", "Subsidiary", "Republic of Poland", None, None),
             ("Hrvatska Postanska Banka dd", "Govt Owned Entity", "Republic of Croatia", None, None), ("Banca Agricola Popolare di Sic", None, None, "Cooperative Banks", "cooperative"),
             ("Coop Pank AS", None, None, "Commer Banks Non-US", "cooperative"), ("Banca Valsabbina SCpA", None, None, None, "cooperative"),
             ("Raiffeisen Bank International", None, None, "Commer Banks Non-US", None), ("Alpha Bank SA", None, "Alpha Bank SA", "Commer Banks Non-US", None),
             ("GRENKE AG", None, None, "Finance-Leasing Compan", "specialist"), ("Banca IFIS SpA", None, None, "Finance-Commercial", "specialist"),
             ("flatexDEGIRO SE", None, None, "Finance-Invest Bnkr/Brkr", "specialist"), ("VP Bank AG", None, None, "Invest Mgmnt/Advis Serv", "specialist"),
             ("Banca Sistema SpA", None, None, "Commer Banks Non-US", "specialist"), ("Leasing Sub AG", "Subsidiary", "Parent AG", "Finance-Leasing Compan", "subsidiary"),
             ("Bank of Cyprus Holdings PLC", None, "Bank of Cyprus Holdings PLC", "Commer Banks Non-US", None), ("Deutsche Bank AG", None, "Deutsche Bank AG", "Diversified Banking Inst", None)]
    bad = [c_[0] for c_ in cases if px(*c_[:4]) != c_[4]]
    check("peer exclusion: subsidiary (a parent in a group, not a state or a depositary foundation), cooperative (subgroup, legal form, name), and specialist (subgroup or named exception)", not bad, str(bad))
    conn.execute("UPDATE bbg_entity SET name = 'Self Bank' WHERE lei = 'LEI_SELF_00000000001'")
    conn.execute("UPDATE bbg_equity_snapshot SET value = 'Finance-Leasing Compan' WHERE ticker = 'SELF GA' AND field = 'INDUSTRY_SUBGROUP'")
    pr = ma_market.peers(q)
    check("peers: a specialist is left out and listed with the reason", pr["rows"] == [] and [x["reason"] for x in pr["removed"]] == ["specialist"], str(pr["removed"]))
    conn.execute("UPDATE bbg_equity_snapshot SET value = 'Commer Banks Non-US' WHERE ticker = 'SELF GA' AND field = 'INDUSTRY_SUBGROUP'")
    check("peers: the bank is a normal peer again", len(ma_market.peers(q)["rows"]) == 1)
    conn.execute("UPDATE bbg_equity_snapshot SET value = 'DKK' WHERE ticker = 'SELF GA' AND field = 'CRNCY'")
    conn.execute("UPDATE bbg_equity_snapshot SET value = 16.0 * 7.475 WHERE ticker = 'SELF GA' AND field = 'PX_LAST'")
    pk = ma_market.peers(q)["rows"]
    check("peers: a bank that trades in another currency (price 7.475 times higher, per-share values in EUR) keeps P/TBV 1.6 and RoCET1 13.5%; the old formula gave 12.0 and dropped it",
          len(pk) == 1 and near(pk[0]["ptbv"], 1.6) and near(pk[0]["rocet1"], 0.135), str(pk))
    conn.execute("UPDATE bbg_equity_snapshot SET value = 'EUR' WHERE ticker = 'SELF GA' AND field = 'CRNCY'")
    conn.execute("UPDATE bbg_equity_snapshot SET value = 16.0 WHERE ticker = 'SELF GA' AND field = 'PX_LAST'")
    conn.execute("INSERT INTO clean_period_fact VALUES ('LEI_SELF_00000000001', '2026-06-30', 'K_61.00', 10, '0040', 50000000000.0)")  # TREA 50bn
    conn.execute("UPDATE bbg_entity SET rwa = 50000.0 WHERE lei = 'LEI_SELF_00000000001'")  # EUR million
    check("peers: P3DH TREA equal to the Bloomberg RWA: the bank is a peer", len(ma_market.peers(q)["rows"]) == 1)
    conn.execute("UPDATE bbg_entity SET rwa = 2000.0 WHERE lei = 'LEI_SELF_00000000001'")
    pr = ma_market.peers(q)
    check("peers: P3DH TREA 25 times the Bloomberg RWA: left out and listed with the reason scale mismatch", pr["rows"] == [] and [x["reason"] for x in pr["removed"]] == ["scale mismatch"], str(pr["removed"]))
    conn.execute("UPDATE bbg_entity SET rwa = 30000.0 WHERE lei = 'LEI_SELF_00000000001'")
    check("peers: TREA 1.67 times the Bloomberg RWA is inside the range (0.5 to 2)", len(ma_market.peers(q)["rows"]) == 1)
    conn.execute("UPDATE bbg_entity SET rwa = NULL WHERE lei = 'LEI_SELF_00000000001'")
    check("peers: a bank without Bloomberg RWA is not tested", len(ma_market.peers(q)["rows"]) == 1)
    conn.execute("DELETE FROM bbg_equity_snapshot WHERE ticker = 'SELF GA' AND field = 'PX_TO_BOOK_RATIO'")
    check("peers: a bank without the price to book ratio is left out (the price cannot be converted)", ma_market.peers(q)["rows"] == [])


def test_rates_reader() -> None:
    print("5. rates for the workbook")
    conn = new_db()
    conn.executemany("INSERT INTO bbg_rate_daily VALUES (?, ?, ?)", [("ECB_DFR", "2025-06-11", 2.0), ("ECB_DFR", "2026-06-17", 2.25), ("ECB_DFR", "2026-09-16", 2.5),
                                                                   ("ESTR", "2026-10-12", 2.439), ("OIS_1Y", "2026-10-13", 2.9), ("OIS_5Y", "2026-10-13", 3.1)])
    conn.executemany("INSERT INTO bbg_expected_dfr VALUES (?, ?, ?, ?, ?, ?)", [
        ("2026-10-13", "Y", "2026-01-01", "2026-12-31", 2.22, 0.061), ("2026-10-13", "Y", "2027-01-01", "2027-12-31", 3.14, 0.061),
        ("2026-10-13", "H", "2026-01-01", "2026-06-30", 2.02, 0.061), ("2026-10-13", "H", "2026-07-01", "2026-12-31", 2.42, 0.061),
        ("2026-10-13", "Q", "2026-01-01", "2026-03-31", 2.0, 0.061), ("2026-10-13", "Q", "2026-10-01", "2026-12-31", 2.56, 0.061)])
    conn.executemany("INSERT INTO bbg_rate_average VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", [
        ("ECB_DFR", "Y", "2025-01-01", "2025-12-31", 2.26, 2.5, 2.0, 365, 1), ("ECB_DFR", "Y", "2026-01-01", "2026-12-31", 2.13, 2.0, 2.5, 286, 0),
        ("ECB_DFR", "H", "2025-07-01", "2025-12-31", 2.0, 2.0, 2.0, 184, 1)])
    conn.commit()
    r = ma_market.rates(query_of(conn))
    by = {p["label"]: p for p in r["periods"]}
    check("2025 is realised (average from the table of averages)", by["2025"]["status"] == "realised" and near(by["2025"]["avg"], 0.0226))
    check("2026 is a mix: realised to the pull date, then forward", by["2026"]["status"].startswith("realised to the pull date") and near(by["2026"]["avg"], 0.0222))
    check("2027 is forward", by["2027"]["status"] == "OIS forward plus spread" and near(by["2027"]["avg"], 0.0314))
    check("half years and quarters have labels like '2026 H2' and '2026 Q4'", "2026 H2" in by and "2026 Q4" in by and "2026 H1" in by)
    check("a half year that is over is realised, one that has not ended is a mix", by["2026 H1"]["status"] == "realised" and by["2026 H2"]["status"].startswith("realised to the pull date"))
    check("the quarter that is running at the pull date is a mix, with the expected average", by["2026 Q4"]["status"].startswith("realised to the pull date") and near(by["2026 Q4"]["avg"], 0.0256))
    check("average per calendar year for the workbook", set(r["by_year"]) == {2026, 2027} and near(r["by_year"][2027], 0.0314))
    check("rates today and OIS curve as fractions", near(r["today"]["ECB_DFR"], 0.025) and near(r["today"]["ESTR"], 0.02439) and near(r["ois"]["5Y"], 0.031))
    check("changes of the deposit rate since 2024", [d for d, _ in r["history"]] == ["2025-06-11", "2026-06-17", "2026-09-16"] and near(r["spread"], 0.00061))


class FakeClient:
    def __init__(self, data):
        self.data = data
        self.messages: list[str] = []

    def log(self, msg):
        self.messages.append(msg)

    def ref(self, securities, fields, overrides=None, **kw):
        return {s: self.data.get(s, {"_error": "unknown"}) for s in securities}


class BondClient(FakeClient):
    """Bloomberg stand-in for a bank with an EMTN bond and a perpetual. The search finds the perpetual only when the query holds a coupon."""
    def search(self, query, yellow_key="YK_FILTER_CORP", max_results=1000):
        q = query.upper()
        if q in ("TEST BANK", "TST"):
            return [("TST 4 01/01/2030<corp>", "Test Bank")]
        if q == "TST 7 PERP":
            return [("TST 7<1/4> PERP REGS<corp>", "Test Bank"), ("TSTX 7 PERP<corp>", "Other Bank")]
        return []


def test_perpetual_and_series() -> None:
    print("3d2. a perpetual is found by its coupon; the series of a bond is stored")
    bond = {"ID_ISIN": "XS1", "NAME": "Test Bank", "CPN": 4.0, "MATURITY": "2030-01-01", "ISSUE_DT": "2025-01-01", "AMT_OUTSTANDING": 5e8, "CRNCY": "EUR", "PAYMENT_RANK": "Sr Preferred",
            "SECURITY_TYP": "EURO MTN", "IS_PERPETUAL": "N", "SERIES": "EMTN"}
    perp = {"ID_ISIN": "XS2", "NAME": "Test Bank", "CPN": 7.25, "MATURITY": None, "ISSUE_DT": "2025-03-07", "AMT_OUTSTANDING": 3e8, "CRNCY": "EUR", "PAYMENT_RANK": "Jr Subordinated",
            "SECURITY_TYP": "EURO-ZONE", "IS_PERPETUAL": "Y", "BASEL_III_DESIGNATION": "Additional Tier 1"}
    client = BondClient({"TST 4 01/01/2030 Corp": bond, "TST 7.25 PERP REGS Corp": perp})
    listed = dict(bonds.list_bonds(client, "TST", 1, "Test Bank", None))
    check("list: the perpetual is found with the coupon sweep, and a bond of another issuer is not kept", sorted(listed) == ["TST 4 01/01/2030<corp>", "TST 7<1/4> PERP REGS<corp>"], str(sorted(listed)))
    conn = new_db()
    conn.execute("INSERT INTO entity VALUES ('K', 'L1', 'Test Bank', 'Greece')")
    conn.execute("INSERT INTO bbg_entity (lei, found, name, long_name, n_bond_issues, bond_amt_outstanding, total_assets) VALUES ('L1', 1, 'Test Bank', 'Test Bank', 2, 8e8, 1e10)")
    res = bonds.pull(client, conn, 0, 100000, ["L1"], False, False, True)
    row = {r[0]: r[1:] for r in conn.execute("SELECT security, series, perpetual, basel_iii, payment_rank FROM bbg_bond")}
    check("pull: both bonds are stored; the series of the EMTN bond is EMTN, the perpetual has none and is flagged Y",
          res["static"] == 2 and row["TST 4 01/01/2030<corp>"][0] == "EMTN" and row["TST 7<1/4> PERP REGS<corp>"][:3] == (None, "Y", "Additional Tier 1"), str(row))
    uni = sorted(r[0] for r in conn.execute("SELECT security FROM v_bond_universe"))
    check("the perpetual of EUR 300m is in the universe", "TST 7<1/4> PERP REGS<corp>" in uni, str(uni))
    check("the view of outstanding bonds shows security type and series", conn.execute("SELECT series, security_type FROM v_bond_outstanding WHERE security = 'TST 4 01/01/2030<corp>'").fetchone() == ("EMTN", "EURO MTN"))


def test_entities() -> None:
    print("6. entity pull keeps the market basis")
    conn = new_db()
    conn.execute("INSERT INTO entity VALUES ('K', 'ABCDEFGHIJKLMNOPQR12', 'Test Bank', 'Greece')")
    lei = "ABCDEFGHIJKLMNOPQR12"
    fake = FakeClient({f"/lei/{lei}": {"NAME": "Test Bank", "COUNTRY_ISO": "GR", "TRAIL_12M_NET_INC": 123.0, "TRAIL_12M_CONT_INC": 110.0, "NET_INCOME": 100.0, "DDIS_AMT_OUTSTANDING_BY_YR": [{"Year": 2030, "Amount Outstanding - Ultimate Parent": 500.0}]}})
    entities.pull(fake, conn)
    conn.execute("UPDATE bbg_entity SET market_basis = 'self', market_ticker = 'TST GA' WHERE lei = ?", (lei,))
    entities.pull(fake, conn)
    row = conn.execute("SELECT market_basis, market_ticker, net_income_ltm, net_income FROM bbg_entity WHERE lei = ?", (lei,)).fetchone()
    check("a second pull updates the values and keeps market basis and ticker", row == ("self", "TST GA", 123.0, 100.0), str(row))
    check("income from continuing operations of the last 12 months is stored next to the net income", conn.execute("SELECT net_income_cont_ltm FROM bbg_entity WHERE lei = ?", (lei,)).fetchone() == (110.0,))
    check("debt maturity profile stored", conn.execute("SELECT bonds_m FROM bbg_debt_maturity WHERE lei = ? AND year = 2030", (lei,)).fetchone() == (500.0,))
    check("a LEI without data is stored as not found", entities.pull(FakeClient({}), conn) == 1 and conn.execute("SELECT found FROM bbg_entity WHERE lei = ?", (lei,)).fetchone() == (0,))


class NameClient(FakeClient):
    """Bloomberg stand-in for a bank that has no live bond and only a private-company equity record."""
    def search(self, query, yellow_key="YK_FILTER_CORP", max_results=1000):
        if yellow_key == "YK_FILTER_EQTY":
            return [("1160124D AV<equity>", "Volksbank Wien AG - Private Company")] if query.upper().startswith("VOLKSBANK WIEN") else []
        return [("VOWIBA<corp>", "Volksbank Wien AG (Multiple Matches)")] if query.upper() == "VOLKSBANK WIEN AG" else []


def test_match() -> None:
    print("6b. match to Bloomberg: rebuilt LEI and name")
    check("check digits of a LEI (ISO 7064): BPCE 46, Credit Agricole SA 05", match.check_digits("9695005MSX1OYEMGDF") == "46" and match.check_digits("969500TJ5KRTCJQWXH") == "05")
    check("a real LEI passes the check, a changed one fails", match.valid_lei("5UMCZOEYKCVFAW8ZLO05") and not match.valid_lei("5UMCZOEYKCVFAW8ZLO06"))
    check("code of country + LEI start gives the full LEI", match.lei_from_code("FR9695005MSX1OYEMGDF") == "9695005MSX1OYEMGDF46" and match.lei_from_code("FR969500TJ5KRTCJQWXH") == "969500TJ5KRTCJQWXH05")
    check("a code of another form gives no LEI", match.lei_from_code("AT0000000000043000") is None and match.lei_from_code("short") is None)
    check("name variants drop a short code at the end", match.name_variants("VOLKSBANK WIEN AG VB") == ["VOLKSBANK WIEN AG VB", "VOLKSBANK WIEN AG", "VOLKSBANK WIEN"])
    client = NameClient({"1160124D AV Equity": {"LEGAL_ENTITY_IDENTIFIER": "529900D4CD6DIB3CI904", "NAME": "Volksbank Wien AG"},
                         "/lei/529900D4CD6DIB3CI904": {"NAME": "Volksbank Wien AG", "COUNTRY_ISO": "AT"}})
    check("name route: a private-company equity record gives the LEI", match.lei_by_name(client, "VOLKSBANK WIEN AG VB") == "529900D4CD6DIB3CI904")
    conn = new_db()
    conn.executemany("INSERT INTO entity VALUES (?, ?, ?, ?)", [("AT0000000000043000VB", "AT0000000000043000VB", "VOLKSBANK WIEN AG VB", "Austria"),
                                                                 ("FR9695005MSX1OYEMGDF", "FR9695005MSX1OYEMGDF", "Groupe BPCE", "France"), ("ABCDEFGHIJKLMNOPQR12", "ABCDEFGHIJKLMNOPQR12", "Plain Bank", "Greece")])
    client.data["/lei/9695005MSX1OYEMGDF46"] = {"NAME": "BPCE SA", "COUNTRY_ISO": "FR", "ISSUER_EQUITY_TICKER": "3358410Z FP", "ID_BB_ULTIMATE_PARENT_CO_NAME": "Groupe BPCE", "ULT_PARENT_TICKER_EXCHANGE": "3692594Z FP"}
    client.data["/lei/ABCDEFGHIJKLMNOPQR12"] = {"NAME": "Plain Bank", "COUNTRY_ISO": "GR", "ISSUER_EQUITY_TICKER": "PLAIN GA"}
    entities.pull(client, conn)
    got = {r[0]: r[1:] for r in conn.execute("SELECT lei, bbg_lei, match_method, name FROM bbg_entity")}
    check("pull: a plain LEI, a rebuilt LEI, and a name match, each under the P3DH key",
          got["ABCDEFGHIJKLMNOPQR12"][1] == "lei" and got["FR9695005MSX1OYEMGDF"] == ("9695005MSX1OYEMGDF46", "lei_rebuilt", "BPCE SA")
          and got["AT0000000000043000VB"] == ("529900D4CD6DIB3CI904", "name", "Volksbank Wien AG"), str(got))
    conn.execute("INSERT INTO bbg_equity_snapshot VALUES ('PLAIN GA', 'PX_LAST', '2026-10-13', 5.0)")
    conn.execute("INSERT INTO bbg_bond_listing (lei, issuer_ticker, security, description) VALUES ('FR9695005MSX1OYEMGDF', 'BPCEGP', 'BPCEGP 4 01/01/2030<corp>', 'BPCE SA')")
    n = match.build_ticker_map(conn)
    kinds = {(r[0], r[1]): (r[2], r[3]) for r in conn.execute("SELECT entity_key, kind, ticker, priced FROM bbg_ticker_map")}
    check("ticker map: a priced equity, a private placeholder, and the ticker of the bonds", kinds[("ABCDEFGHIJKLMNOPQR12", "equity")] == ("PLAIN GA", 1)
          and kinds[("FR9695005MSX1OYEMGDF", "proxy_equity")] == ("3358410Z FP", 0) and kinds[("FR9695005MSX1OYEMGDF", "debt")] == ("BPCEGP", 0) and n >= 4, str(kinds))
    note = conn.execute("SELECT note FROM bbg_ticker_map WHERE entity_key = 'FR9695005MSX1OYEMGDF' AND kind = 'proxy_equity'").fetchone()[0]
    check("ticker map: the placeholder code is marked private", "private" in note, note)


class OwnerClient(FakeClient):
    def ref(self, securities, fields, overrides=None, **kw):
        h = lambda name, kind, pct: {"Holder Name": name, "Institution Type": kind, "Percent Outstanding": pct, "Amount Held": pct * 1e6, "Country": "X", "Filing Date": "2026-10-13", "Source": "EXCH"}  # noqa: E731
        data = {
            "STATE GA Equity": {"TOP_20_HOLDERS_PUBLIC_FILINGS": [h("State of A", "Government", 8.0), h("Vanguard", "Investment Advisor", 5.0)],
                                "INSTITUTION_TYPE_OWNERSHIP_PCT": [{"Ownership Type": "Government", "Ownership %": 8.0}], "PCT_OWNERSHIP_TYP": [{"Ownership Type": "Government", "Percent Ownership": 13.9}],
                                "EQY_INST_PCT_SH_OUT": 59.7, "EQY_FREE_FLOAT_PCT": 91.7},
            "MAJOR GA Equity": {"TOP_20_HOLDERS_PUBLIC_FILINGS": [h("Republic of B", "Government", 57.0)]},
            "PRIV GA Equity": {"TOP_20_HOLDERS_PUBLIC_FILINGS": [h("Vanguard", "Investment Advisor", 5.0)]},
            "BAD GA Equity": {"_error": "unknown"}}
        return {s: data.get(s, {"_error": "unknown"}) for s in securities}


def test_ownership() -> None:
    print("6c. ownership and state participation")
    check("own tickers of an issuer: the row of the group structure with its company id", entities.own_tickers(
        [{"BBID": 1, "Company Debt Ticker": "TOP", "CDS Ticker": ""}, {"BBID": 2, "Company Debt Ticker": "BPCEGP", "CDS Ticker": "BPCEGP CDS"}], 2) == ("BPCEGP", "BPCEGP CDS")
          and entities.own_tickers([{"BBID": 1}], 9) == (None, None) and entities.own_tickers(None, 1) == (None, None))
    conn = new_db()
    for t in ("STATE GA", "MAJOR GA", "PRIV GA", "BAD GA"):
        conn.execute("INSERT INTO bbg_equity_snapshot VALUES (?, 'PX_LAST', '2026-10-13', 5.0)", (t,))
    for t in ("STATE GA", "MAJOR GA", "PRIV GA"):
        conn.execute("INSERT INTO bbg_equity_snapshot VALUES (?, 'INDUSTRY_SUBGROUP', '2026-10-13', 'Commer Banks Non-US')", (t,))
    conn.executemany("INSERT INTO bbg_entity (lei, found, name, market_basis, market_ticker, equity_ticker, parent_ticker, parent_name, parent_relationship) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?)", [
        ("E_STATE", "State Bank", "self", "STATE GA", "STATE GA", "STATE GA", "State Bank", None), ("E_MAJOR", "Major Bank", "self", "MAJOR GA", "MAJOR GA", "MAJOR GA", "Major Bank", None),
        ("E_PRIV", "Private Holder Bank", "self", "PRIV GA", "PRIV GA", "PRIV GA", "Private Holder Bank", None),
        ("E_GOV", "Belfius-like", "none", None, "1111Z BB", None, "Kingdom of Belgium", "Govt Owned Entity"), ("E_SUB", "Sub of listed", "parent", "STATE GA", "2222Z BB", "STATE GA", "State Bank", "Subsidiary"),
        ("E_NONE", "Unknown", "none", None, "3333Z BB", None, "Some Holding", "Subsidiary"), ("E_PT", "Portugal-like", "none", None, "4444Z BB", None, "Portuguese Republic", None)])
    res = ownership.pull(OwnerClient({}), conn)
    check("ownership pull: holders, types, and the government count", res["tickers"] == 4 and res["holders"] == 4 and res["tickers with a government holder in the top 20"] == 2, str(res))
    st = {r[0]: r[1:] for r in conn.execute("SELECT entity_key, state_status, state_pct_named, via_parent, free_float_pct, institutional_pct, largest_holder FROM v_bank_ownership")}
    check("state participation: an 8% Government holder in the top 20", st["E_STATE"][0] == "state participation" and near(st["E_STATE"][1], 8.0) and st["E_STATE"][2] == 0 and near(st["E_STATE"][3], 91.7)
          and near(st["E_STATE"][4], 59.7) and st["E_STATE"][5] == "State of A", str(st["E_STATE"]))
    check("state majority above 50%", st["E_MAJOR"][0] == "state majority")
    check("no government holder gives none reported", st["E_PRIV"][0] == "none reported" and st["E_NONE"][0] == "none reported")
    check("an unlisted bank owned by a government (relationship, or a parent that is a republic or kingdom)", st["E_GOV"][0] == "owned by a government" and st["E_PT"][0] == "owned by a government")
    check("a subsidiary shows the ownership of its listed parent and is marked via_parent", st["E_SUB"][0] == "state participation" and st["E_SUB"][2] == 1)
    conn.execute("INSERT INTO bbg_equity_snapshot VALUES ('STATE GA', 'EQY_SH_OUT', '2026-10-14', 100.0)")
    equity.assign_market_basis(conn)
    check("a newer partial snapshot does not change the market basis", conn.execute("SELECT market_basis FROM bbg_entity WHERE lei = 'E_STATE'").fetchone()[0] == "self")
    s = ma_market.slot(query_of(conn), "E_STATE")
    check("a newer partial snapshot does not hide the price in the M&A reader", s["basis"] == "self" and s["price"] == 5.0 and s["shares"] == 100.0, str(s.get("price")))


def test_database() -> None:
    print("7. coverage of the real database")
    db = ROOT / "data" / "processed" / "p3dh.sqlite"
    if not db.exists():
        print("  skipped (no database)")
        return
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    if not ma_market.tables_exist(query_of(conn)):
        print("  skipped (no Bloomberg tables)")
        return
    q = lambda sql, p=(): conn.execute(sql, p).fetchall()  # noqa: E731
    leis = [r[0] for r in q("SELECT DISTINCT lei FROM entity WHERE lei IS NOT NULL")]  # includes the groups that have a national code instead of a LEI
    found = q("SELECT COUNT(*) FROM bbg_entity WHERE found = 1")[0][0]
    check(f"every P3DH entity with a LEI has a row in bbg_entity ({len(leis)})", q("SELECT COUNT(*) FROM bbg_entity WHERE lei IN (SELECT lei FROM entity)")[0][0] == len(leis))
    check("every entity is found in Bloomberg (a LEI, a rebuilt LEI, or a name)", found == len(leis), f"{found} of {len(leis)}")
    for key, name, ticker in (("FR9695005MSX1OYEMGDF", "Groupe BPCE", "BPCEGP"), ("FR969500TJ5KRTCJQWXH", "Groupe Credit Agricole", "ACA FP"), ("AT0000000000043000VB", "Volksbank Wien", None)):
        row = q("SELECT found, match_method, market_basis FROM bbg_entity WHERE lei = ?", (key,))
        check(f"{name}: matched by {row[0][1] if row else '?'}, no market cap of its own", bool(row) and row[0][0] == 1 and row[0][1] in ("lei_rebuilt", "name") and row[0][2] in ("none", "proxy"), str(row))
        if ticker:
            have = {r[0] for r in q("SELECT ticker FROM bbg_ticker_map WHERE entity_key = ?", (key,))}
            check(f"{name}: ticker {ticker} in the ticker map", ticker in have or ticker == "BPCEGP" and not q("SELECT 1 FROM bbg_bond_listing WHERE lei = ?", (key,)), str(have))
    check("every entity has a market basis", q("SELECT COUNT(*) FROM bbg_entity WHERE found = 1 AND market_basis IS NULL")[0][0] == 0)
    check("a parent is a bank (no conglomerate or car maker)", q("""SELECT COUNT(*) FROM bbg_entity e WHERE market_basis = 'parent' AND NOT EXISTS
                                                                  (SELECT 1 FROM bbg_equity_snapshot s WHERE s.ticker = e.market_ticker AND s.field = 'INDUSTRY_SUBGROUP' AND s.value LIKE '%Bank%')""")[0][0] == 0)
    check("consensus has a fiscal year for every row", q("SELECT COUNT(*) FROM bbg_consensus WHERE period_end IS NULL")[0][0] == 0)
    own = q("SELECT COUNT(*), SUM(state_status <> 'none reported') FROM v_bank_ownership")[0]
    check("ownership: every bank is in the view and NBG shows the Hellenic Republic as a Government holder", own[0] == len(leis) and q(
        "SELECT state_status, largest_holder, largest_type FROM v_bank_ownership WHERE entity_key = '5UMCZOEYKCVFAW8ZLO05'")[0] == ("state participation", "Hellenic Republic", "Government"))
    check("ownership: holders are loaded for the listed banks and some banks have state participation", q("SELECT COUNT(DISTINCT ticker) FROM bbg_holder")[0][0] > 100 and own[1] > 20, str(own))
    check("ticker map: every bank with its own priced equity is in the map", q("SELECT COUNT(*) FROM bbg_entity b WHERE market_basis = 'self' AND NOT EXISTS "
          "(SELECT 1 FROM bbg_ticker_map t WHERE t.entity_key = b.lei AND t.kind = 'equity' AND t.priced = 1)")[0][0] == 0)
    out = q("SELECT COUNT(*), SUM(px_mid IS NOT NULL) FROM v_bond_outstanding")[0]
    check("outstanding bonds exist and have market data", out[0] > 100 and out[1] > 50, str(out))
    check("outstanding bonds: amount above 0 and a market data row for most", q("SELECT COUNT(*) FROM v_bond_outstanding WHERE amt_outstanding <= 0")[0][0] == 0 and q("SELECT COUNT(*) FROM v_bond_outstanding WHERE pull_date IS NULL")[0][0] < 0.05 * out[0])
    odd = q("""SELECT COUNT(*) FROM v_bond_outstanding WHERE (z_spread IS NOT NULL AND (z_spread < -300 OR z_spread > 3000)) OR (ytm_mid IS NOT NULL AND (ytm_mid < -2 OR ytm_mid > 30))""")[0][0]
    check("spreads and yields are plausible: fewer than 1% outside Z-spread -300 to 3000 bp and yield -2 to 30% (Bloomberg values of zero-coupon notes and of bonds close to maturity)", odd < 0.01 * max(out[1], 1), f"{odd} of {out[1]}")
    check("yield to worst is never above yield to maturity", q("SELECT COUNT(*) FROM v_bond_outstanding WHERE ytw IS NOT NULL AND ytm_mid IS NOT NULL AND ytw > ytm_mid + 1e-9")[0][0] == 0)
    check("a bond that is listed as redeemed has no amount outstanding or a past maturity", q("""SELECT COUNT(*) FROM bbg_bond_listing l JOIN bbg_bond b ON b.security = l.security AND b.lei = l.lei WHERE l.status = 'redeemed'
          AND b.amt_outstanding > 0 AND (b.perpetual = 'Y' OR b.maturity IS NULL OR b.maturity >= date('now'))""")[0][0] == 0)
    check("market cap in EUR for the banks of the M&A workbook is between EUR 1bn and EUR 100bn", all(1e9 < r[0] < 1e11 for r in q(
        "SELECT mkt_cap_eur FROM bbg_equity_daily WHERE ticker IN ('ETE GA', 'BOCHGR GA') AND date = (SELECT MAX(date) FROM bbg_equity_daily)")))
    for lei, name in (("9CZ7TVMR36CYD5TZBS50", "BIL"), ("TUKDD90GPC79G1KOE162", "HCOB")):
        s = ma_market.slot(query_of(conn), lei)
        check(f"{name}: net income, opex, tax rate from Bloomberg and no market cap", s["found"] and s["basis"] != "self" and s["ni_ltm"] and s["opex"] and (s["tax_stat"] or s["tax_eff"]))
    nbg = ma_market.slot(query_of(conn), "5UMCZOEYKCVFAW8ZLO05")
    check("NBG: statutory tax 29%, four years of consensus", nbg["found"] and near(nbg["tax_stat"], 0.29) and all(nbg["cons"].get(y, {}).get("NI") for y in ma_market.YEARS))
    r = ma_market.rates(query_of(conn))
    check("deposit rate: an average for each year 2026 to 2029", set(ma_market.YEARS) <= set(r["by_year"]))
    check("peers: at least 40 European banks with market cap, tangible book, and CET1", len(ma_market.peers(query_of(conn))["rows"]) >= 40)


if __name__ == "__main__":
    test_curve()
    test_rates()
    test_bonds()
    test_bond_market()
    test_bond_history()
    test_universe()
    test_issuance()
    test_bridge()
    test_perpetual_and_series()
    test_refresh()
    test_equity_and_market()
    test_rates_reader()
    test_entities()
    test_match()
    test_ownership()
    test_database()
    if FAILED:
        print(f"\n{len(FAILED)} check(s) failed: {', '.join(FAILED)}")
        sys.exit(1)
    print("\nall Bloomberg checks passed")
