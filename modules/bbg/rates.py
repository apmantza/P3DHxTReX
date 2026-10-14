"""Rates, curves, FX and indices: history, period averages, and the expected ECB deposit rate."""

from __future__ import annotations

import datetime as dt
import sqlite3

import pandas as pd

from . import curve
from .client import Client

# series, ticker, name, group, unit, method. method ffill = a policy rate that holds until the next change (average over calendar days);
# obs = the mean of the observations.
CORE: list[tuple[str, str, str, str, str, str]] = [
    ("ECB_DFR_ANN", "EUORDEPO Index", "ECB deposit facility rate, dated on the day of the decision", "policy", "percent", "ffill"),
    ("ECB_MRO_ANN", "EURR002W Index", "ECB main refinancing rate, dated on the day of the decision", "policy", "percent", "ffill"),
    ("ECB_MLF_ANN", "EUORMARG Index", "ECB marginal lending facility rate, dated on the day of the decision", "policy", "percent", "ffill"),
    ("EONIA", "EONIA Index", "EONIA", "money", "percent", "obs"),
    ("ESTR", "ESTRON Index", "Euro short-term rate (ESTR)", "money", "percent", "obs"),
    ("EURIBOR_1M", "EUR001M Index", "Euribor 1 month", "money", "percent", "obs"),
    ("EURIBOR_3M", "EUR003M Index", "Euribor 3 months", "money", "percent", "obs"),
    ("EURIBOR_6M", "EUR006M Index", "Euribor 6 months", "money", "percent", "obs"),
    ("EURIBOR_12M", "EUR012M Index", "Euribor 12 months", "money", "percent", "obs"),
]
SWAPS = [(f"EUSWAP_{n}Y", f"EUSA{n} Curncy", f"EUR swap rate (6M Euribor) {n} years", "swap", "percent", "obs") for n in (1, 2, 3, 4, 5, 7, 10, 15, 20, 30)]
OIS = [(f"OIS_{label}", f"{t} Curncy", f"ESTR OIS swap rate {label}", "ois", "percent", "obs") for label, (_, t) in curve.OIS.items()]
GOVT = [
    ("BUND_2Y", "GDBR2 Index", "German government 2Y"), ("BUND_5Y", "GDBR5 Index", "German government 5Y"), ("BUND_10Y", "GDBR10 Index", "German government 10Y"),
    ("BUND_30Y", "GDBR30 Index", "German government 30Y"), ("GGB_2Y", "GGGB2YR Index", "Greek government 2Y"), ("GGB_5Y", "GGGB5YR Index", "Greek government 5Y"),
    ("GGB_7Y", "GGGB7YR Index", "Greek government 7Y"), ("GGB_10Y", "GGGB10YR Index", "Greek government 10Y"), ("BTP_10Y", "GBTPGR10 Index", "Italian government 10Y"),
    ("GOV10_IT", "GTITL10YR Govt", "Italy 10Y"), ("GOV10_ES", "GTESP10YR Govt", "Spain 10Y"), ("GOV10_FR", "GTFRF10YR Govt", "France 10Y"),
    ("GOV10_PT", "GTPTE10YR Govt", "Portugal 10Y"), ("GOV10_IE", "GTIEP10YR Govt", "Ireland 10Y"), ("GOV10_GR", "GTGRD10YR Govt", "Greece 10Y"),
    ("GOV10_AT", "GTATS10YR Govt", "Austria 10Y"), ("GOV10_BE", "GTBEF10YR Govt", "Belgium 10Y"), ("GOV10_NL", "GTNLG10YR Govt", "Netherlands 10Y"),
    ("GOV10_FI", "GTFIM10YR Govt", "Finland 10Y"), ("GOV10_CY", "GTCYP10YR Govt", "Cyprus 10Y"), ("GOV10_SE", "GTSEK10YR Govt", "Sweden 10Y"),
    ("GOV10_NO", "GTNOK10YR Govt", "Norway 10Y"), ("GOV10_DK", "GTDKK10YR Govt", "Denmark 10Y"), ("GOV10_PL", "GTPLN10YR Govt", "Poland 10Y"),
    ("GOV10_CZ", "GTCZK10YR Govt", "Czechia 10Y"), ("GOV10_HU", "GTHUF10YR Govt", "Hungary 10Y"), ("GOV10_GB", "GTGBP10YR Govt", "United Kingdom 10Y"),
    ("GOV10_US", "GT10 Govt", "United States 10Y"),
]
GOVT = [(a, b, c, "govt", "percent", "obs") for a, b, c in GOVT]
CREDIT = [
    ("IBOXX_SR_FIN", "IYG3X Index", "iBoxx EUR senior financials", "credit", "index", "obs"), ("IBOXX_SUB_FIN", "IYG5X Index", "iBoxx EUR subordinated financials", "credit", "index", "obs"),
    ("IBOXX_AT1", "IBXXC2D1 Index", "iBoxx EUR AT1 (CoCo) total return", "credit", "index", "obs"), ("IBOXX_COVERED", "IYGB Index", "iBoxx EUR covered", "credit", "index", "obs"),
    ("IBOXX_SUPRA", "QW9M Index", "iBoxx EUR supranational", "credit", "index", "obs"), ("IBOXX_AGENCIES", "QJWY Index", "iBoxx EUR agencies", "credit", "index", "obs"),
    ("IBOXX_CORP", "IBOXIG Index", "iBoxx EUR liquid non-financials", "credit", "index", "obs"),
    ("ITRAXX_MAIN_5Y", "ITRXEBE Index", "iTraxx Europe Main 5Y", "credit", "bp", "obs"), ("ITRAXX_SR_FIN_5Y", "SNRFIN CDSI GEN 5Y Corp", "iTraxx Senior Financials 5Y", "credit", "bp", "obs"),
    ("ITRAXX_SUB_FIN_5Y", "SUBFIN CDSI GEN 5Y Corp", "iTraxx Subordinated Financials 5Y", "credit", "bp", "obs"),
    ("ITRAXX_XOVER_5Y", "ITRX XOVER CDSI GEN 5Y Corp", "iTraxx Crossover 5Y", "credit", "bp", "obs"),
    ("EUROSTOXX_BANKS", "SX7E Index", "Euro Stoxx Banks", "equity_index", "index", "obs"), ("STOXX600_BANKS", "SX7P Index", "Stoxx Europe 600 Banks", "equity_index", "index", "obs"),
    ("VSTOXX", "V2X Index", "VSTOXX", "equity_index", "index", "obs"),
]
FX = [(f"FX_EUR{c}", f"EUR{c} Curncy", f"EUR/{c}: units of {c} for 1 EUR", "fx", "rate", "obs") for c in ("USD", "GBP", "CHF", "SEK", "NOK", "DKK", "PLN", "CZK", "HUF", "RON", "BGN", "ISK", "HRK", "JPY", "ZAR", "CNY", "AUD", "CAD", "TRY")]
ALL_SERIES = CORE + SWAPS + OIS + GOVT + CREDIT + FX
TENOR_DAYS = {f"OIS_{k}": v[0] for k, v in curve.OIS.items()}


# The ECB applies a new rate on the first Wednesday after the meeting (the Bloomberg series is dated on the day of the decision).
EFFECTIVE = {"ECB_DFR": ("ECB_DFR_ANN", "ECB deposit facility rate"), "ECB_MRO": ("ECB_MRO_ANN", "ECB main refinancing rate"),
             "ECB_MLF": ("ECB_MLF_ANN", "ECB marginal lending facility rate")}


def next_wednesday(d: dt.date) -> dt.date:
    return d + dt.timedelta(days=(2 - d.weekday()) % 7 or 7)


def derive_effective(conn: sqlite3.Connection) -> int:
    """Daily series of the policy rates with the dates on which the rates apply (the first Wednesday after the decision)."""
    total = 0
    for series, (ann, name) in EFFECTIVE.items():
        rows = conn.execute("SELECT date, value FROM bbg_rate_daily WHERE series = ? ORDER BY date", (ann,)).fetchall()
        if not rows:
            continue
        first = dt.date.fromisoformat(rows[0][0])
        last = dt.date.fromisoformat(rows[-1][0])
        changes = [(first, rows[0][1])]
        for (d0, v0), (d1, v1) in zip(rows, rows[1:]):
            if v1 != v0:
                changes.append((next_wednesday(dt.date.fromisoformat(d1)), v1))
        out, k, cur, day = [], 0, None, first
        while day <= last:
            while k < len(changes) and changes[k][0] <= day:
                cur = changes[k][1]
                k += 1
            out.append((series, day.isoformat(), cur))
            day += dt.timedelta(days=1)
        conn.execute("DELETE FROM bbg_rate_daily WHERE series = ?", (series,))
        conn.executemany("INSERT INTO bbg_rate_daily VALUES (?, ?, ?)", out)
        conn.execute("INSERT OR REPLACE INTO bbg_rate_series (series, ticker, name, group_name, unit, tenor_days, method) VALUES (?, ?, ?, 'policy', 'percent', NULL, 'ffill')",
                     (series, "derived from " + ann, name + ", dated on the day the rate applies"))
        total += len(out)
    conn.commit()
    return total


def log(conn: sqlite3.Connection, kind: str, detail: str, n: int, status: str = "ok") -> None:
    conn.execute("INSERT INTO bbg_pull_log (started_at, kind, detail, n_rows, status) VALUES (?, ?, ?, ?, ?)", (dt.datetime.now().isoformat(timespec="seconds"), kind, detail, n, status))
    conn.commit()


def pull_history(client: Client, conn: sqlite3.Connection, start: str = "19990101", full: bool = False) -> int:
    """Daily history of all series. A series that has data is updated from 10 days before its last date."""
    today = dt.date.today().strftime("%Y%m%d")
    tickers = {s[1]: s for s in ALL_SERIES}
    valid_resp = client.ref(list(tickers), ["PX_LAST"])
    valid = [t for t, r in valid_resp.items() if r.get("PX_LAST") is not None]
    bad = sorted(set(tickers) - set(valid))
    if bad:
        client.log(f"series that Bloomberg does not resolve (skipped): {bad}")
    total = 0
    last = {r[0]: r[1] for r in conn.execute("SELECT series, last_date FROM bbg_rate_series")}
    groups: dict[str, list[str]] = {}
    for t in valid:
        series = tickers[t][0]
        begin = start if (full or series not in last or not last[series]) else (dt.date.fromisoformat(last[series]) - dt.timedelta(days=10)).strftime("%Y%m%d")
        groups.setdefault(begin, []).append(t)
    for begin, ts in groups.items():
        for i in range(0, len(ts), 6):
            part = ts[i:i + 6]
            data = client.hist(part, ["PX_LAST"], begin, today)
            for t, rows in data.items():
                series = tickers[t][0]
                recs = [(series, d, v["PX_LAST"]) for d, v in rows if v["PX_LAST"] is not None]
                conn.executemany("INSERT OR REPLACE INTO bbg_rate_daily VALUES (?, ?, ?)", recs)
                total += len(recs)
            conn.commit()
            client.log(f"  rates {begin}: {', '.join(tickers[t][0] for t in part)}")
    for t in valid:
        series, ticker, name, group, unit, method = tickers[t]
        conn.execute("INSERT OR REPLACE INTO bbg_rate_series (series, ticker, name, group_name, unit, tenor_days, method) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (series, ticker, name, group, unit, TENOR_DAYS.get(series), method))
    total += derive_effective(conn)
    conn.execute("""UPDATE bbg_rate_series SET first_date = (SELECT MIN(date) FROM bbg_rate_daily d WHERE d.series = bbg_rate_series.series),
                    last_date = (SELECT MAX(date) FROM bbg_rate_daily d WHERE d.series = bbg_rate_series.series),
                    n_obs = (SELECT COUNT(*) FROM bbg_rate_daily d WHERE d.series = bbg_rate_series.series)""")
    log(conn, "rates", f"{len(valid)} series from {start}", total)
    return total


def _daily(conn: sqlite3.Connection, series: str, method: str) -> pd.Series:
    df = pd.read_sql_query("SELECT date, value FROM bbg_rate_daily WHERE series = ? ORDER BY date", conn, params=(series,))
    if df.empty:
        return pd.Series(dtype=float)
    s = pd.Series(df["value"].to_numpy(), index=pd.to_datetime(df["date"]))
    if method == "ffill":
        s = s.reindex(pd.date_range(s.index[0], s.index[-1], freq="D")).ffill()
    return s


def _row(series: str, kind: str, start: pd.Timestamp, end: pd.Timestamp, s: pd.Series, last_date: pd.Timestamp):
    part = s[(s.index >= start) & (s.index <= end)]
    if part.empty:
        return None
    return (series, kind, start.date().isoformat(), end.date().isoformat(), float(part.mean()), float(part.iloc[0]), float(part.iloc[-1]), int(len(part)), int(end <= last_date))


def compute_averages(conn: sqlite3.Connection) -> int:
    """Averages per month (M), quarter (Q), half year (H), calendar year (Y), year to date (YTD), and the last 12 months (LTM)."""
    conn.execute("DELETE FROM bbg_rate_average")
    n = 0
    for series, method in conn.execute("SELECT series, method FROM bbg_rate_series").fetchall():
        s = _daily(conn, series, method)
        if s.empty:
            continue
        last_date = s.index[-1]
        rows = []
        first_year, last_year = s.index[0].year, last_date.year
        for y in range(first_year, last_year + 1):
            rows.append(_row(series, "Y", pd.Timestamp(y, 1, 1), pd.Timestamp(y, 12, 31), s, last_date))
            for h, (m0, m1) in enumerate(((1, 6), (7, 12))):
                rows.append(_row(series, "H", pd.Timestamp(y, m0, 1), pd.Timestamp(y, m1, 1) + pd.offsets.MonthEnd(0), s, last_date))
            for q in range(4):
                a = pd.Timestamp(y, 3 * q + 1, 1)
                b = a + pd.offsets.MonthEnd(3)
                rows.append(_row(series, "Q", a, b, s, last_date))
                rows.append(_row(series, "YTD", pd.Timestamp(y, 1, 1), b, s, last_date))
                rows.append(_row(series, "LTM", b - pd.Timedelta(days=364), b, s, last_date))
            for m in range(1, 13):
                a = pd.Timestamp(y, m, 1)
                rows.append(_row(series, "M", a, a + pd.offsets.MonthEnd(0), s, last_date))
        rows = [r for r in rows if r and pd.Timestamp(r[2]) <= last_date]
        conn.executemany("INSERT OR REPLACE INTO bbg_rate_average VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        n += len(rows)
    conn.commit()
    log(conn, "averages", "month, quarter, half, year, ytd, ltm", n)
    return n


def _value_before(s: pd.Series, day: pd.Timestamp, max_gap: int = 7):
    part = s[s.index <= day]
    if part.empty or (day - part.index[-1]).days > max_gap:
        return None
    return float(part.iloc[-1])


def compute_expected(conn: sqlite3.Connection, first: str = "2020-01-31") -> int:
    """Expected ECB deposit rate for calendar years, seen from each month end since 2020. For the last date also for halves and quarters."""
    dfr = _daily(conn, "ECB_DFR", "obs")
    estr = _daily(conn, "ESTR", "obs")
    ois = {label: _daily(conn, f"OIS_{label}", "obs") for label in curve.OIS}
    if dfr.empty or estr.empty:
        return 0
    changes = [(d.date(), float(v)) for k, (d, v) in enumerate(dfr.items()) if k == 0 or v != dfr.iloc[k - 1]]
    as_ofs = [d for d in pd.date_range(first, dfr.index[-1], freq="ME")] + [dfr.index[-1]]
    conn.execute("DELETE FROM bbg_expected_dfr")
    rows = []
    for a in as_ofs:
        quotes = {label: _value_before(s, a) for label, s in ois.items() if not s.empty}
        e, d = _value_before(estr, a), _value_before(dfr, a, 40)
        if e is None or d is None or sum(v is not None for v in quotes.values()) < 4:
            continue
        nodes = curve.discount_factors(quotes)
        spread = d - e
        day = a.date()
        for y in range(day.year, day.year + 5):
            v = curve.expected_year_average(day, y, changes, nodes, spread)
            if v is not None:
                rows.append((day.isoformat(), "Y", f"{y}-01-01", f"{y}-12-31", v, spread))
        if a == as_ofs[-1]:
            for y in range(day.year, day.year + 5):
                for h, (m0, m1) in enumerate(((1, 6), (7, 12))):
                    a0, a1 = dt.date(y, m0, 1), (pd.Timestamp(y, m1, 1) + pd.offsets.MonthEnd(0)).date()
                    rows.append((day.isoformat(), "H", a0.isoformat(), a1.isoformat(), curve.expected_average(day, a0, a1, changes, nodes, spread), spread))
                for q in range(4):
                    a0 = dt.date(y, 3 * q + 1, 1)
                    a1 = (pd.Timestamp(a0) + pd.offsets.MonthEnd(3)).date()
                    rows.append((day.isoformat(), "Q", a0.isoformat(), a1.isoformat(), curve.expected_average(day, a0, a1, changes, nodes, spread), spread))
    conn.executemany("INSERT OR REPLACE INTO bbg_expected_dfr VALUES (?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    log(conn, "expected_dfr", f"{len(as_ofs)} as-of dates", len(rows))
    return len(rows)
