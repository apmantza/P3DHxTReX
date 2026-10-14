"""Listed banks: valuation snapshot, daily prices, fundamentals history, consensus. Then the market basis of each P3DH entity."""

from __future__ import annotations

import datetime as dt
import re
import sqlite3

from .client import Client

PRIVATE_CODE = re.compile(r"^\d+[A-Z]?[ZD] ")  # placeholder tickers of private or delisted companies, for example 1030Z GR or 0794070D MV
SNAPSHOT = ["PX_LAST", "CRNCY", "ID_ISIN", "NAME", "CUR_MKT_CAP", "EQY_SH_OUT", "PX_TO_BOOK_RATIO", "PE_RATIO", "BOOK_VAL_PER_SH", "TANG_BOOK_VAL_PER_SH",
            "EQY_DVD_YLD_IND", "INDUSTRY_SECTOR", "INDUSTRY_SUBGROUP", "COUNTRY_ISO", "EQY_REC_CONS", "BEST_TARGET_PRICE", "EQY_PRIM_EXCH", "LATEST_PERIOD_END_DT_FULL_RECORD",
            "NET_INCOME", "IS_OPERATING_EXPN", "TOT_COMMON_EQY", "BS_TOT_ASSET", "RETURN_COM_EQY", "IS_STATUTORY_TAX_RATE", "EFF_TAX_RATE", "TRAIL_12M_EPS", "IS_EPS"]
FUNDAMENTALS = ["NET_INCOME", "TOT_COMMON_EQY", "BS_TOT_ASSET", "BS_TOT_LOAN", "BS_CUSTOMER_DEPOSITS", "IS_OPERATING_EXPN", "SALES_REV_TURN", "BS_RISK_WEIGHTED_ASSETS",
                "RETURN_COM_EQY", "EFF_TAX_RATE", "IS_INT_INC", "BS_TIER1_CAP_RATIO"]
CONSENSUS = ["BEST_NET_INCOME", "BEST_EPS", "BEST_DPS", "BEST_SALES", "BEST_OPP", "BEST_BPS", "BEST_ROE"]
PERIODS = ("1FY", "2FY", "3FY", "4FY")


def candidate_tickers(conn: sqlite3.Connection) -> list[str]:
    own = {r[0] for r in conn.execute("SELECT equity_ticker FROM bbg_entity WHERE equity_ticker IS NOT NULL")}
    parent = {r[0] for r in conn.execute("SELECT parent_ticker FROM bbg_entity WHERE parent_ticker IS NOT NULL")}
    return sorted(t for t in own | parent if not PRIVATE_CODE.match(t + " "))


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def pull(client: Client, conn: sqlite3.Connection, limit: int = 0, start: str = "20150101", parts: tuple[str, ...] = ("daily", "fundamentals", "consensus")) -> dict:
    """The snapshot is always pulled. parts: daily (prices and market cap), fundamentals (annual and quarterly), consensus. Prices change every day, the other two much less."""
    today = dt.date.today()
    tickers = candidate_tickers(conn)
    if limit:
        tickers = tickers[:limit]
    sec = {t: f"{t} Equity" for t in tickers}
    client.log(f"{len(tickers)} candidate tickers (placeholder codes of private companies skipped)")

    # 1. snapshot
    snap = client.ref(list(sec.values()), SNAPSHOT, overrides={"EQY_FUND_CRNCY": "EUR"})
    rows, valid = [], []
    for t, s in sec.items():
        r = snap.get(s, {})
        if "_error" in r or r.get("PX_LAST") is None:
            continue
        valid.append(t)
        rows += [(t, f, today.isoformat(), v) for f, v in r.items() if v is not None]
    conn.executemany("INSERT OR REPLACE INTO bbg_equity_snapshot VALUES (?, ?, ?, ?)", rows)
    conn.commit()
    sector = {r[0]: r[1] for r in conn.execute("SELECT ticker, value FROM bbg_equity_snapshot WHERE field = 'INDUSTRY_SECTOR' AND pull_date = ?", (today.isoformat(),))}
    fin = [t for t in valid if sector.get(t) == "Financial"]
    client.log(f"{len(valid)} tickers with a price; {len(fin)} financials get history, fundamentals, consensus")

    # 2. daily history
    last = {r[0]: r[1] for r in conn.execute("SELECT ticker, MAX(date) FROM bbg_equity_daily GROUP BY ticker")}
    groups: dict[str, list[str]] = {}
    for t in (fin if "daily" in parts else []):
        b = start if t not in last else (dt.date.fromisoformat(last[t]) - dt.timedelta(days=5)).strftime("%Y%m%d")
        groups.setdefault(b, []).append(t)
    n_daily = 0
    end = today.strftime("%Y%m%d")
    for begin, ts in groups.items():
        for i in range(0, len(ts), 5):
            part = ts[i:i + 5]
            px = client.hist([sec[t] for t in part], ["PX_LAST", "PX_TO_BOOK_RATIO", "EQY_SH_OUT"], begin, end)
            mc = client.hist([sec[t] for t in part], ["CUR_MKT_CAP"], begin, end, currency="EUR")
            for t in part:
                by_date: dict[str, list] = {}
                for d, v in px.get(sec[t], []):
                    by_date[d] = [_num(v["PX_LAST"]), None, _num(v["PX_TO_BOOK_RATIO"]), _num(v["EQY_SH_OUT"])]
                for d, v in mc.get(sec[t], []):
                    by_date.setdefault(d, [None, None, None, None])[1] = None if _num(v["CUR_MKT_CAP"]) is None else _num(v["CUR_MKT_CAP"]) * 1e6
                recs = [(t, d, *v) for d, v in by_date.items() if any(x is not None for x in v)]
                conn.executemany("INSERT OR REPLACE INTO bbg_equity_daily VALUES (?, ?, ?, ?, ?, ?)", recs)
                n_daily += len(recs)
            conn.commit()
            client.log(f"  prices {begin}: {i + len(part)}/{len(ts)}")

    # 3. fundamentals history (EUR)
    n_fund = 0
    for per, kind in ((("YEARLY", "A"), ("QUARTERLY", "Q")) if "fundamentals" in parts else ()):
        for i in range(0, len(fin), 5):
            part = fin[i:i + 5]
            data = client.hist([sec[t] for t in part], FUNDAMENTALS, "20060101", end, periodicity=per, currency="EUR", fiscal=True)
            for t in part:
                recs = [(t, d, kind, f, _num(v[f])) for d, v in data.get(sec[t], []) for f in FUNDAMENTALS if _num(v.get(f)) is not None]
                conn.executemany("INSERT OR REPLACE INTO bbg_fundamental VALUES (?, ?, ?, ?, ?)", recs)
                n_fund += len(recs)
            conn.commit()
        client.log(f"  fundamentals {per}: {n_fund} values so far")

    # 4. consensus for the next four fiscal years
    n_cons = 0
    for per in (PERIODS if "consensus" in parts else ()):
        data = client.ref([sec[t] for t in fin], CONSENSUS, overrides={"BEST_FPERIOD_OVERRIDE": per, "EQY_FUND_CRNCY": "EUR"})
        recs = []
        for t in fin:
            r = data.get(sec[t], {})
            recs += [(t, today.isoformat(), per, None, f, _num(r.get(f))) for f in CONSENSUS if _num(r.get(f)) is not None]
        conn.executemany("INSERT OR REPLACE INTO bbg_consensus VALUES (?, ?, ?, ?, ?, ?)", recs)
        n_cons += len(recs)
    conn.commit()
    assign_consensus_periods(conn)
    assign_market_basis(conn)
    conn.execute("INSERT INTO bbg_pull_log (started_at, kind, detail, n_rows, status) VALUES (?, 'equity', ?, ?, 'ok')",
                 (dt.datetime.now().isoformat(timespec="seconds"), f"{len(valid)} priced, {len(fin)} financial: {n_daily} daily, {n_fund} fundamentals, {n_cons} consensus", n_daily + n_fund + n_cons))
    conn.commit()
    return {"candidates": len(tickers), "priced": len(valid), "financial": len(fin), "daily": n_daily, "fundamentals": n_fund, "consensus": n_cons}


def assign_consensus_periods(conn: sqlite3.Connection) -> None:
    """The fiscal year of each consensus period is the last annual report plus 1 to 4 years. Uses data in the database only."""
    for (t,) in conn.execute("SELECT DISTINCT ticker FROM bbg_consensus").fetchall():
        row = conn.execute("SELECT MAX(period_end) FROM bbg_fundamental WHERE ticker = ? AND period_type = 'A'", (t,)).fetchone()
        if row and row[0]:
            y, md = int(row[0][:4]), row[0][4:]
            for k, per in enumerate(PERIODS, start=1):
                conn.execute("UPDATE bbg_consensus SET period_end = ? WHERE ticker = ? AND fperiod = ?", (f"{y + k}{md}", t, per))
    conn.commit()


def assign_market_basis(conn: sqlite3.Connection) -> None:
    """Market basis of each P3DH entity: its own listed equity (self), else the equity of its ultimate parent when that parent is a bank (parent), else none (none).
    proxy: a group that was matched to a listed issuer that is not the same legal entity.
    The share price of a conglomerate or a car maker says nothing about the bank inside it. Uses data in the database only."""
    snap = {}
    for t, f, v in conn.execute("""SELECT ticker, field, value FROM bbg_equity_snapshot s WHERE field IN ('PX_LAST', 'INDUSTRY_SUBGROUP')
                                   AND pull_date = (SELECT MAX(pull_date) FROM bbg_equity_snapshot x WHERE x.ticker = s.ticker AND x.field = s.field)"""):
        snap.setdefault(t, {})[f] = v
    priced = [t for t, d in snap.items() if d.get("PX_LAST") is not None]
    bank_parent = [t for t in priced if "Bank" in str(snap[t].get("INDUSTRY_SUBGROUP") or "")]
    conn.execute("UPDATE bbg_entity SET market_basis = NULL, market_ticker = NULL")
    conn.execute("UPDATE bbg_entity SET market_basis = 'self', market_ticker = equity_ticker WHERE equity_ticker IN (%s)" % ",".join("?" * len(priced)), priced)
    conn.execute("UPDATE bbg_entity SET market_basis = 'parent', market_ticker = parent_ticker WHERE market_basis IS NULL AND parent_ticker IN (%s) AND parent_lei <> lei" % ",".join("?" * len(bank_parent)),
                 bank_parent)
    conn.execute("UPDATE bbg_entity SET market_basis = 'none' WHERE market_basis IS NULL")
    # a group that was matched by a rebuilt LEI or by name is not the listed entity: it keeps the ticker as a proxy, with no market cap of its own
    conn.execute("UPDATE bbg_entity SET market_basis = 'proxy' WHERE market_basis = 'self' AND COALESCE(match_method, 'lei') <> 'lei'")
    conn.commit()
