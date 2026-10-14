"""Market data for the M&A workbook. It reads the Bloomberg tables of the P3DH database (bbg_*). No Streamlit code.

Units: amounts in EUR million, shares in million, rates as fractions. Price and per-share values are in the currency of the stock.
A bank with market basis 'self' has its own listed shares. All other banks have no market cap: the workbook values them with their nearest listed peers.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Callable

import pandas as pd

Query = Callable[..., pd.DataFrame]
YEARS = (2026, 2027, 2028, 2029)
CONS_METRICS = {"NI": "BEST_NET_INCOME", "EPS": "BEST_EPS", "DPS": "BEST_DPS", "SALES": "BEST_SALES", "OPP": "BEST_OPP"}
OIS_LABELS = ["1W", "2W", "3W", "1M", "2M", "3M", "6M", "9M", "10M", "1Y", "2Y", "3Y", "4Y", "5Y", "6Y", "7Y", "10Y"]
EUROPE = {"AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE",
          "IS", "LI", "NO", "GB", "CH"}
PTBV_RANGE = (0.15, 6.0)
ROTE_RANGE = (-0.10, 0.60)


def _f(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _m(v: Any, divisor: float = 1e6) -> float | None:
    x = _f(v)
    return None if x is None else x / divisor


def lei_of(query: Query, entity_key: str) -> str:
    """LEI of a P3DH entity. Bloomberg data is linked by the LEI."""
    d = query("SELECT lei FROM entity WHERE entity_key = ? AND lei IS NOT NULL LIMIT 1", (entity_key,))
    return entity_key if d.empty else str(d.iloc[0]["lei"])


def tables_exist(query: Query) -> bool:
    d = query("SELECT name FROM sqlite_master WHERE name IN ('bbg_entity', 'bbg_rate_daily', 'bbg_equity_snapshot', 'bbg_expected_dfr')")
    return len(d) == 4


def slot(query: Query, lei: str) -> dict[str, Any]:
    """Bloomberg data of one bank, found by its LEI."""
    e = query("SELECT * FROM bbg_entity WHERE lei = ?", (lei,))
    out: dict[str, Any] = {"lei": lei, "found": False, "basis": "none", "ticker": None, "cons": {}}
    if e.empty or not int(e.iloc[0]["found"] or 0):
        return out
    r = e.iloc[0]
    out.update(found=True, name=r["name"], basis=r["market_basis"] or "none", ticker=r["market_ticker"], sector=r["sector"], private=r["private_flag"],
               country=r["country_iso"], parent_name=r["parent_name"], parent_ticker=r["parent_ticker"],
               ni_fy=_f(r["net_income"]), ni_ltm=_f(r.get("net_income_cont_ltm")) if _f(r.get("net_income_cont_ltm")) is not None else _f(r["net_income_ltm"]),
               ni_ltm_reported=_f(r["net_income_ltm"]), revenue=_f(r["revenue"]), opex=_f(r["operating_expenses"]), equity=_f(r["common_equity"]),
               assets=_f(r["total_assets"]), rwa=_f(r["rwa"]), tax_stat=_f(r["statutory_tax_rate"]), tax_eff=None if _f(r["effective_tax_rate"]) is None else _f(r["effective_tax_rate"]) / 100.0,
               record_end=r["latest_period_end"], rating_sp=r["rating_sp"], rating_moodys=r["rating_moodys"], bonds_n=_f(r["n_bond_issues"]), debt_out=_m(r["bond_amt_outstanding"]),
               pulled_at=r["pulled_at"])
    if out["basis"] != "self" or not out["ticker"]:
        return out
    t = out["ticker"]
    s = query("""SELECT field, value FROM bbg_equity_snapshot s WHERE ticker = ? AND pull_date = (SELECT MAX(pull_date) FROM bbg_equity_snapshot x WHERE x.ticker = s.ticker AND x.field = s.field)""", (t,))
    sn = dict(zip(s["field"], s["value"]))
    out.update(price=_f(sn.get("PX_LAST")), ccy=sn.get("CRNCY"), shares=_f(sn.get("EQY_SH_OUT")), bvps=_f(sn.get("BOOK_VAL_PER_SH")), tbvps=_f(sn.get("TANG_BOOK_VAL_PER_SH")),
               eps_ttm=_f(sn.get("TRAIL_12M_EPS")), eps_fy=_f(sn.get("IS_EPS")))
    d = query("SELECT date, mkt_cap_eur FROM bbg_equity_daily WHERE ticker = ? AND mkt_cap_eur IS NOT NULL ORDER BY date DESC LIMIT 1", (t,))
    out["mcap"] = None if d.empty else float(d.iloc[0]["mkt_cap_eur"]) / 1e6
    out["price_date"] = None if d.empty else d.iloc[0]["date"]
    c = query("""SELECT period_end, field, value FROM bbg_consensus WHERE ticker = ? AND pull_date = (SELECT MAX(pull_date) FROM bbg_consensus WHERE ticker = ?)""", (t, t))
    inv = {v: k for k, v in CONS_METRICS.items()}
    for row in c.itertuples():
        if row.period_end and row.field in inv:
            out["cons"].setdefault(int(str(row.period_end)[:4]), {})[inv[row.field]] = _f(row.value)
    return out


DEPENDENT = {"Subsidiary", "Synthetic Parent", "Related Entities"}  # values of the Bloomberg field COMPANY_TO_PARENT_RELATIONSHIP for a bank that belongs to a group
SOVEREIGN_OR_DEPOSITARY = re.compile(r"^(republic|principality|kingdom) of |^stichting ", re.I)  # not a corporate parent: a state, or a foundation that holds depositary receipts
COOPERATIVE_NAME = re.compile(r"\b(coop|cooperative|cooperativa|cooperatif|popolare|populaire|genossenschaft|scpa|caisse regionale|credit agricole|volksbank|raiffeisenverband)\b", re.I)


SPECIALIST_SUBGROUPS = {"Finance-Leasing Compan", "Finance-Commercial", "Finance-Invest Bnkr/Brkr", "Invest Mgmnt/Advis Serv", "Special Purpose Banks", "Commercial Serv-Finance", "Mortgage Banks"}  # Bloomberg subgroups
SPECIALIST_NAMES = re.compile(r"\bbanca sistema\b", re.I)  # banks that Bloomberg classes as commercial banks but that are specialists (Banca Sistema: factoring)


def peer_exclusion(name: str, relationship: str | None, parent_name: str | None, subgroup: str | None) -> str | None:
    """Why a listed bank is not a peer, or None. Subsidiaries, cooperatives, and specialists are left out: the price of a bank that a parent controls, that has certificates and members,
    or that lends in one niche, is not the price of an independent universal bank.
    Subsidiary: Bloomberg gives the bank a parent in a group, unless that parent is a state or a depositary foundation (a state-owned bank trades freely; so does ABN AMRO).
    Cooperative: the Bloomberg subgroup Cooperative Banks, or a cooperative legal form or name.
    Specialist: a Bloomberg subgroup of leasing, commercial finance, brokerage, investment management, mortgage, or special purpose banks; or a named exception."""
    if relationship in DEPENDENT and not SOVEREIGN_OR_DEPOSITARY.match(parent_name or ""):
        return "subsidiary"
    if subgroup == "Cooperative Banks" or COOPERATIVE_NAME.search(name or ""):
        return "cooperative"
    if subgroup in SPECIALIST_SUBGROUPS or SPECIALIST_NAMES.search(name or ""):
        return "specialist"
    return None


def peers(query: Query, countries: set[str] | None = None) -> dict[str, Any]:
    """Listed banks of P3DH with four numbers each:
    P/TBV and RoTE from per-share values (price / tangible book, trailing EPS / tangible book),
    P/CET1 and RoCET1 from the market cap in EUR, the trailing profit (EPS x shares), and CET1 of the newest KM1 filing in P3DH.
    Only European banks by default. A bank with a number outside the ranges, or without CET1, is left out.
    Subsidiaries, cooperatives, and specialists are left out too (peer_exclusion). They are listed in "removed" with the reason."""
    countries = EUROPE if countries is None else countries
    d = query("""SELECT e.lei, e.name, e.country_iso AS country, e.market_ticker AS ticker, e.parent_relationship, e.parent_name,
                        (SELECT value FROM bbg_equity_snapshot s WHERE s.ticker = e.market_ticker AND s.field = 'INDUSTRY_SUBGROUP' ORDER BY pull_date DESC LIMIT 1) AS subgroup,
                        (SELECT value FROM bbg_equity_snapshot s WHERE s.ticker = e.market_ticker AND s.field = 'PX_LAST' ORDER BY pull_date DESC LIMIT 1) AS px,
                        (SELECT value FROM bbg_equity_snapshot s WHERE s.ticker = e.market_ticker AND s.field = 'TANG_BOOK_VAL_PER_SH' ORDER BY pull_date DESC LIMIT 1) AS tbvps,
                        (SELECT value FROM bbg_equity_snapshot s WHERE s.ticker = e.market_ticker AND s.field = 'TRAIL_12M_EPS' ORDER BY pull_date DESC LIMIT 1) AS eps,
                        (SELECT value FROM bbg_equity_snapshot s WHERE s.ticker = e.market_ticker AND s.field = 'CRNCY' ORDER BY pull_date DESC LIMIT 1) AS ccy,
                        (SELECT mkt_cap_eur FROM bbg_equity_daily x WHERE x.ticker = e.market_ticker AND x.mkt_cap_eur IS NOT NULL ORDER BY date DESC LIMIT 1) AS mcap,
                        (SELECT MAX(pull_date) FROM bbg_equity_snapshot s WHERE s.ticker = e.market_ticker) AS pull_date
                 FROM bbg_entity e WHERE e.found = 1 AND e.market_basis = 'self'""")
    km1 = query("""SELECT entity_key, period_end, value FROM clean_period_fact WHERE template_code = 'K_61.00' AND measure_col = 10 AND row_code = '0010' AND value IS NOT NULL""")
    cet1: dict[str, float] = {}
    if not km1.empty:
        newest = pd.Timestamp(km1["period_end"].max()) - pd.Timedelta(days=400)
        km1 = km1[pd.to_datetime(km1["period_end"]) >= newest].sort_values("period_end").groupby("entity_key").tail(1)
        cet1 = dict(zip(km1["entity_key"], km1["value"]))
    rows, removed = [], []
    for r in d.itertuples():
        px, tb, eps, mcap, c1 = _f(r.px), _f(r.tbvps), _f(r.eps), _f(r.mcap), _f(cet1.get(r.lei))
        if r.country not in countries or r.ccy == "GBp" or None in (px, tb, eps, mcap, c1) or tb <= 0 or px <= 0 or c1 <= 0:
            continue
        ptbv, rote = px / tb, eps / tb
        pcet1, rocet1 = mcap / c1, mcap * eps / px / c1
        if PTBV_RANGE[0] < ptbv < PTBV_RANGE[1] and PTBV_RANGE[0] < pcet1 < PTBV_RANGE[1] and ROTE_RANGE[0] < rote < ROTE_RANGE[1] and ROTE_RANGE[0] < rocet1 < ROTE_RANGE[1]:
            why = peer_exclusion(r.name, r.parent_relationship, r.parent_name, r.subgroup)
            rec = {"lei": r.lei, "name": r.name, "country": r.country, "ticker": r.ticker, "ptbv": ptbv, "rote": rote, "pcet1": pcet1, "rocet1": rocet1}
            if why:
                removed.append({**rec, "reason": why, "parent": r.parent_name})
            else:
                rows.append(rec)
    rows.sort(key=lambda x: (x["country"], x["name"]))
    removed.sort(key=lambda x: (x["reason"], x["country"], x["name"]))
    return {"rows": rows, "removed": removed, "pull_date": None if d.empty else d["pull_date"].max()}


def _label(kind: str, end: str) -> str:
    y, m = end[:4], int(end[5:7])
    return {"Y": y, "H": f"{y} H{1 if m <= 6 else 2}", "Q": f"{y} Q{(m - 1) // 3 + 1}"}[kind]


def rates(query: Query) -> dict[str, Any]:
    """Today's rates, the OIS curve, the deposit-rate path, and the average deposit rate per year, half, and quarter.
    A period that is over has its realised average. A period that has not ended has the realised path to the pull date, then the OIS forward rate plus the spread."""
    out: dict[str, Any] = {"today": {}, "ois": {}, "history": [], "periods": [], "by_year": {}, "as_of": None, "spread": None}
    last = query("""SELECT series, MAX(date) AS date FROM bbg_rate_daily WHERE series IN ('ECB_DFR', 'ESTR') OR series LIKE 'OIS_%' GROUP BY series""")
    for r in last.itertuples():
        v = query("SELECT value FROM bbg_rate_daily WHERE series = ? AND date = ?", (r.series, r.date))
        val = None if v.empty else float(v.iloc[0]["value"]) / 100.0
        if r.series.startswith("OIS_"):
            out["ois"][r.series[4:]] = val
        else:
            out["today"][r.series] = val
    d = query("SELECT date, value FROM bbg_rate_daily WHERE series = 'ECB_DFR' AND date >= '2024-01-01' ORDER BY date")
    prev = None
    for r in d.itertuples():
        if r.value != prev:
            out["history"].append((r.date, float(r.value) / 100.0))
            prev = r.value
    asof = query("SELECT MAX(as_of) AS a FROM bbg_expected_dfr")
    out["as_of"] = None if asof.empty else asof.iloc[0]["a"]
    if not out["as_of"]:
        return out
    exp = query("SELECT period_type, period_start, period_end, expected_avg, spread FROM bbg_expected_dfr WHERE as_of = ? ORDER BY period_end", (out["as_of"],))
    out["spread"] = None if exp.empty else float(exp.iloc[0]["spread"]) / 100.0
    expected = {(r.period_type, r.period_end): (r.period_start, float(r.expected_avg) / 100.0) for r in exp.itertuples()}
    real = query("SELECT period_type, period_start, period_end, avg, complete FROM bbg_rate_average WHERE series = 'ECB_DFR' AND period_type IN ('Y', 'H', 'Q') AND period_end >= '2024-01-01'")
    realised = {(r.period_type, r.period_end): (r.period_start, float(r.avg) / 100.0, int(r.complete)) for r in real.itertuples()}
    keys = sorted(set(expected) | {k for k, v in realised.items() if v[2]}, key=lambda k: ({"Y": 0, "H": 1, "Q": 2}[k[0]], k[1]))
    for kind, end in keys:
        if kind == "Y" and not "2024" <= end[:4] <= "2029":
            continue
        if kind in ("H", "Q") and not "2025" <= end[:4] <= "2028":
            continue
        have_real = (kind, end) in realised and realised[(kind, end)][2]
        start = realised[(kind, end)][0] if have_real else expected[(kind, end)][0]
        if end <= out["as_of"]:
            status = "realised"
        elif start <= out["as_of"]:
            status = "realised to the pull date, then forward"
        else:
            status = "OIS forward plus spread"
        avg = realised[(kind, end)][1] if status == "realised" and have_real else expected[(kind, end)][1]
        out["periods"].append({"type": kind, "label": _label(kind, end), "start": start, "end": end, "avg": avg, "status": status})
        if kind == "Y" and end[:4].isdigit() and int(end[:4]) in YEARS:
            out["by_year"][int(end[:4])] = avg
    return out


def load(query: Query, leis: list[str]) -> dict[str, Any]:
    """Everything the workbook needs. leis[0] is NBG. leis[1:] are the targets."""
    if not tables_exist(query):
        raise RuntimeError("The database has no Bloomberg tables. Run scripts/pull_bloomberg.py (see README).")
    log = query("SELECT started_at, kind FROM bbg_pull_log ORDER BY pull_id DESC")
    pulled: dict[str, str] = {}
    for r in log.itertuples():
        pulled.setdefault(r.kind, r.started_at)
    out = {"slots": [slot(query, x) for x in leis], "peers": peers(query), "rates": rates(query), "pulled": pulled}
    out["stamp"] = "|".join(f"{k}={v}" for k, v in sorted(pulled.items()))
    return out


def age_days(pulled: dict[str, str]) -> int | None:
    """Days since the oldest of the main pulls."""
    stamps = [pulled[k] for k in ("rates", "equity", "entities") if k in pulled]
    if not stamps:
        return None
    return (dt.date.today() - dt.date.fromisoformat(min(stamps)[:10])).days
