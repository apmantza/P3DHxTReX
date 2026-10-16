"""Data of the deal pack (NBG + BIL): the numbers that the sheets Valuation, Balance sheet, P&L, MREL scenario, and Sources need and that the model does not hold.

Every function takes query(sql, params) that returns a DataFrame, as ma_data does. No Streamlit code. A function that cannot read its tables returns an empty result:
the sheets then say that the data is missing. Amounts in EUR million unless the name says bn.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

Query = Callable[..., pd.DataFrame]

OR2_LINES = {"0030": "interest_income", "0040": "interest_expense", "0050": "asset_component", "0060": "dividends", "0080": "fee_income", "0090": "fee_expense",
             "0100": "other_income", "0110": "other_expense", "0130": "trading", "0140": "banking_book"}
OR2_YEAR = {"0010": 0, "0020": 1, "0030": 2}  # column a = year of the filing, b = year before, c = two years before
TE_PNL = {
    "Interest income": "interest_income", "Interest expenses": "interest_expense", "Net Fee and commission income": "fees", "TOTAL OPERATING INCOME_ NET": "income",
    "(Administrative expenses)": "admin", "(Cash contributions to resolution funds and deposit guarantee schemes)": "resolution", "(Depreciation)": "depreciation",
    "(Impairment or (-) reversal of impairment on financial assets not measured at fair value through profit or loss)": "impairment",
    "PROFIT OR (-) LOSS BEFORE TAX FROM CONTINUING OPERATIONS": "pbt", "PROFIT OR (-) LOSS FOR THE YEAR": "profit",
}
K_GRID = (10, 15, 20, 25, 30, 40)


class _Cursor:
    def __init__(self, rows: list[tuple]):
        self.rows = rows

    def fetchall(self) -> list[tuple]:
        return self.rows

    def fetchone(self) -> tuple | None:
        return self.rows[0] if self.rows else None


class QueryConn:
    """Gives a function query(sql, params) the small interface of an SQLite connection (execute, fetchall, fetchone), so the readers of modules/ext/bank_metrics.py can be used."""

    def __init__(self, query: Query):
        self.query = query

    def execute(self, sql: str, params: tuple = ()) -> _Cursor:
        return _Cursor(list(self.query(sql, tuple(params)).itertuples(index=False, name=None)))


def _f(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


# ------------------------------------------------------------------------------------------------ P&L history
def or2_lines(query: Query, key: str) -> dict[int, dict[str, float]]:
    """Business indicator lines of OR2 (EUR m) by calendar year. An expense is positive. A later filing replaces an earlier one for the same year."""
    d = query(f"""SELECT reference_date, row_code, column_code, value FROM clean_fact WHERE entity_key = ? AND template_code = 'K_19.02' AND quality <> 'quarantined' AND sheet = '' AND key_descriptor = ''
                  AND column_code IN ('0010', '0020', '0030') AND row_code IN ({','.join('?' * len(OR2_LINES))}) AND value IS NOT NULL ORDER BY reference_date""", (key, *OR2_LINES))
    years: dict[int, dict[str, float]] = {}
    for r in d.itertuples():
        v = float(r.value) / 1e6
        name = OR2_LINES[r.row_code]
        years.setdefault(int(r.reference_date[:4]) - OR2_YEAR[r.column_code], {})[name] = abs(v) if name in ("interest_expense", "fee_expense", "other_expense") else v
    return years


def te_lines(query: Query, key: str) -> dict[str, dict[str, Any]]:
    """EBA Transparency Exercise: P&L lines (year to date), total assets, and equity (EUR m) by reference date. {period_end: {'n_quarters': n, 'lines': {...}}}. Empty when the table is not loaded."""
    if query("SELECT name FROM sqlite_master WHERE name = 'te_oth'").empty:
        return {}
    marks = ",".join("?" * len(TE_PNL))
    d = query(f"""SELECT period_end, sheet, label, n_quarters, assets_fv, assets_stages, amount FROM te_oth WHERE lei = ? AND amount IS NOT NULL AND (
                  (sheet = 'P&L' AND label IN ({marks})) OR (sheet = 'Assets' AND label = 'Total Assets') OR (sheet = 'Liabilities' AND label = 'TOTAL EQUITY')) ORDER BY vintage""", (key, *TE_PNL))
    out: dict[str, dict[str, Any]] = {}
    for r in d.itertuples():
        rec = out.setdefault(r.period_end, {"n_quarters": None, "lines": {}})
        if r.sheet == "P&L":
            rec["n_quarters"] = int(r.n_quarters)
            rec["lines"][TE_PNL[r.label]] = float(r.amount)
        elif r.sheet == "Assets" and (r.assets_fv or 0) == 0 and (r.assets_stages or 0) == 0:
            rec["lines"]["assets"] = float(r.amount)
        elif r.sheet == "Liabilities":
            rec["lines"]["equity"] = float(r.amount)
    return out


# ------------------------------------------------------------------------------------------------ balance sheet
ASSET_RULES = [("cash", ("cash",)), ("interbank", ("loans and advances to credit", "due from banks")), ("loans", ("loans and advances to customers",)),
               ("securities", ("financial investments", "investment securities", "financial assets at fair value", "financial assets held for trading", "non-trading")),
               ("derivatives", ("derivative", "")), ("intangibles", ("intangible", "software", "goodwill"))]
LIAB_RULES = [("interbank", ("amounts due to credit", "due to banks")), ("deposits", ("amounts due to customers", "due to customers")), ("debt", ("debt securities",)),
              ("sub", ("subordinated", "other borrowed funds")), ("derivatives", ("derivative", "financial liabilities held", "financial liabilities measured at", "other financial liabilities"))]
EQUITY_WORDS = ("subscribed capital", "reserves", "net income for the year", "other equity", "gains and losses not recognised", "treasury", "retained earnings", "share capital", "share premium",
                "additional paid-in", "non-controlling")


def _bucket(text: str, rules: list[tuple[str, tuple[str, ...]]], other: str = "other") -> str:
    t = text.lower().replace("type of assets =", "").replace("type of liabilities =", "").strip()
    for name, words in rules:
        for w in words:
            if (w == "" and t == "") or (w != "" and t.startswith(w)) or (w != "" and w in t and name in ("derivatives", "sub")):
                return name
    return other


def cc2_summary(query: Query, key: str) -> dict[str, Any]:
    """Balance sheet of the newest CC2 filing whose lines add up to the total assets (within 2%). Amounts in EUR m.
    {'date', 'assets': {cash, interbank, loans, securities, derivatives, intangibles, other}, 'liabilities': {interbank, deposits, debt, sub, derivatives, other}, 'equity', 'total'} or {}."""
    d = query("""SELECT reference_date, cell_code, key_descriptor, row_label, value FROM clean_fact WHERE entity_key = ? AND template_code = 'K_66.02' AND column_code = '0010'
                 AND value IS NOT NULL AND quality <> 'quarantined'""", (key,))
    if d.empty:
        return {}
    for date in sorted(d["reference_date"].unique(), reverse=True):
        x = d[d["reference_date"] == date]
        sheet = x["cell_code"].str.extract(r"K_66\.02\.(\w)")[0]
        total = x[sheet == "b"]["value"]
        eq = x[sheet == "f"]["value"]
        a = x[(sheet == "a")]
        c = x[(sheet == "c")]
        if total.empty or eq.empty or a.empty or c.empty:
            continue
        assets = {k: 0.0 for k, _ in ASSET_RULES} | {"other": 0.0}
        for r in a.itertuples():
            kd = (r.key_descriptor or "").replace("Type of assets = ", "")
            if kd.lower().startswith("of which"):
                continue
            assets[_bucket(kd, ASSET_RULES)] += float(r.value) / 1e6
        liab = {k: 0.0 for k, _ in LIAB_RULES} | {"other": 0.0}
        for r in c.itertuples():
            kd = (r.key_descriptor or "").replace("Type of liabilities = ", "")
            if not kd or any(w in kd.lower() for w in EQUITY_WORDS):  # some banks list equity lines among the liabilities; equity comes from the total of sheet f
                continue
            liab[_bucket(kd, LIAB_RULES)] += float(r.value) / 1e6
        t = float(total.iloc[0]) / 1e6
        e = float(eq.iloc[0]) / 1e6
        if t > 0 and abs(sum(assets.values()) - t) <= 0.02 * t and abs(sum(liab.values()) + e - t) <= 0.02 * t:
            return {"date": date, "assets": assets, "liabilities": liab, "equity": e, "total": t}
    return {}


def cr1_detail(query: Query, key: str) -> dict[str, Any]:
    """Loans of the newest CR1 filing (sheet a): gross loans, non-performing loans, loans by counterparty, and the accumulated impairment of sheet d (coverage). EUR m."""
    from modules.ext import bank_metrics

    c = bank_metrics.cr1(QueryConn(query), key)
    if not c["gross_loans"]:
        return {}
    date = max(c["gross_loans"])
    perf = query("SELECT value FROM clean_fact WHERE entity_key = ? AND template_code = 'K_21.01' AND reference_date = ? AND cell_code = '{K_21.01.a, r0020, c0010}' AND sheet = '' AND key_descriptor = ''", (key, date))
    imp = query("""SELECT cell_code, value FROM clean_fact WHERE entity_key = ? AND template_code = 'K_21.01' AND reference_date = ? AND cell_code IN ('{K_21.01.d, r0020, c0010}', '{K_21.01.d, r0020, c0040}')
                   AND sheet = '' AND key_descriptor = ''""", (key, date))
    imp_d = {r.cell_code[-6:-1]: float(r.value) / 1e6 for r in imp.itertuples()}
    gross = c["gross_loans"][date] / 1e6
    npl_ratio = c["npl_ratio"][date]
    npe = gross * npl_ratio / 100
    return {"date": date, "gross": gross, "npe": npe, "npl_ratio": npl_ratio, "performing": None if perf.empty else float(perf.iloc[0]["value"]) / 1e6,
            "impairment_performing": abs(imp_d.get("c0010", 0.0)), "impairment_npe": abs(imp_d.get("c0040", 0.0)), "mix": c["loan_mix"].get(date, {}),
            "history": {k: v / 1e6 for k, v in c["gross_loans"].items()}}


# ------------------------------------------------------------------------------------------------ Bloomberg bonds of the target
def bonds_by_rank(query: Query, lei: str) -> dict[str, Any]:
    """Bonds of an issuer in EUR bn by rank (Bloomberg): senior preferred, senior non-preferred, other senior, Tier 2, AT1. Only EUR bonds are summed; the others are counted."""
    d = query("""SELECT payment_rank, basel_iii, perpetual, currency, COUNT(*) AS n, SUM(amt_outstanding) AS amt FROM bbg_bond WHERE lei = ? AND amt_outstanding > 0 GROUP BY 1, 2, 3, 4""", (lei,))
    out = {"senior_preferred": 0.0, "senior_non_preferred": 0.0, "other_senior": 0.0, "tier2": 0.0, "at1": 0.0, "non_eur_count": 0}
    for r in d.itertuples():
        if r.currency != "EUR":
            out["non_eur_count"] += int(r.n)
            continue
        amt = float(r.amt or 0) / 1e9
        rank = r.payment_rank or ""
        if r.basel_iii == "Additional Tier 1" or rank == "Jr Subordinated":
            out["at1"] += amt
        elif r.basel_iii == "Tier 2" or rank == "Subordinated":
            out["tier2"] += amt
        elif rank == "Sr Preferred":
            out["senior_preferred"] += amt
        elif rank == "Sr Non Preferred":
            out["senior_non_preferred"] += amt
        else:
            out["other_senior"] += amt
    return out


# ------------------------------------------------------------------------------------------------ ECB and Eurostat drivers of the target's country
def ecb_drivers(query: Query, country: str = "LU") -> dict[str, Any]:
    """Luxembourg (or another country) against the euro area: loan growth of the ECB, spread of new loans to the 3-month Euribor now and 12 months before, deposit betas,
    lending survey (net percentage), and the local 3-month rate. Each item is {'value': latest, 'period': month, 'before': 12 months before, 'euro_area': ...}. Empty when the tables are missing."""
    if query("SELECT name FROM sqlite_master WHERE name = 'v_ext_obs'").empty:
        return {}

    def last(ind: str, area: str, table: str = "v_ext_obs") -> tuple[str, float, float | None] | None:
        d = query(f"SELECT period, value FROM {table} WHERE indicator = ? AND country = ? ORDER BY period DESC LIMIT 13", (ind, area))
        if d.empty:
            return None
        y0 = int(d.iloc[0]["period"][:4]) - 1
        prev = d[d["period"] == f"{y0}{d.iloc[0]['period'][4:]}"]
        return d.iloc[0]["period"], float(d.iloc[0]["value"]), None if prev.empty else float(prev.iloc[0]["value"])

    out: dict[str, Any] = {}
    items = [("loan growth, corporations (%)", "growth_loans_nfc", "v_ext_obs", 1.0), ("loan growth, house purchase (%)", "growth_loans_hp", "v_ext_obs", 1.0),
             ("loan growth, households (%)", "growth_loans_hh", "v_ext_obs", 1.0), ("deposit growth, households (%)", "growth_dep_hh", "v_ext_obs", 1.0),
             ("deposit growth, corporations (%)", "growth_dep_nfc", "v_ext_obs", 1.0),
             ("new corporate loans: rate less 3-month Euribor (points)", "mir_cob_nfc", "v_country_spreads", 1.0), ("new house purchase loans: rate less 3-month Euribor (points)", "mir_cob_hp", "v_country_spreads", 1.0),
             ("lending survey: corporate loan demand (net %)", "bls_dem_nfc", "v_ext_obs", 1.0), ("lending survey: corporate credit standards (net %)", "bls_std_nfc", "v_ext_obs", 1.0),
             ("lending survey: house purchase demand (net %)", "bls_dem_hp", "v_ext_obs", 1.0)]
    for label, ind, table, _ in items:
        col = "spread_to_euribor" if table == "v_country_spreads" else "value"
        try:
            if table == "v_country_spreads":
                d = {a: query("SELECT period, spread_to_euribor AS value FROM v_country_spreads WHERE indicator = ? AND country = ? ORDER BY period DESC LIMIT 13", (ind, a)) for a in (country, "U2")}
                got = {}
                for a, x in d.items():
                    if x.empty:
                        continue
                    y0 = int(x.iloc[0]["period"][:4]) - 1
                    p = x[x["period"] == f"{y0}{x.iloc[0]['period'][4:]}"]
                    got[a] = (x.iloc[0]["period"], float(x.iloc[0]["value"]), None if p.empty else float(p.iloc[0]["value"]))
            else:
                got = {a: last(ind, a) for a in (country, "U2")}
        except Exception:  # noqa: BLE001
            continue
        if got.get(country):
            out[label] = {"period": got[country][0], "value": got[country][1], "before": got[country][2],
                          "euro_area": got["U2"][1] if got.get("U2") else None, "euro_area_before": got["U2"][2] if got.get("U2") else None}
    if not query("SELECT name FROM sqlite_master WHERE name = 'ext_passthrough'").empty:
        pt = query("SELECT product, cycle, beta, months_to_half FROM ext_passthrough WHERE country IN (?, 'U2') AND product LIKE 'deposits%'", (country,))
        pt_c = query("SELECT country, product, cycle, beta FROM ext_passthrough WHERE country IN (?, 'U2') AND product LIKE 'deposits%'", (country,))
        out["betas"] = {(r.country, r.product, r.cycle): None if r.beta != r.beta else float(r.beta) for r in pt_c.itertuples()}
    m = query("SELECT period, value FROM v_ext_obs WHERE indicator = 'euribor_3m' AND country = 'U2' ORDER BY period DESC LIMIT 1")
    if not m.empty:
        out["euribor_3m"] = (m.iloc[0]["period"], float(m.iloc[0]["value"]))
    return out


# ------------------------------------------------------------------------------------------------ valuation helpers (static tables)
def _near(rows: list[dict], key: str, value: float, k: int) -> list[dict]:
    dist = sorted(abs(r[key] - value) for r in rows)
    if not dist:
        return []
    cut = dist[min(k, len(dist)) - 1]
    return [r for r in rows if abs(r[key] - value) <= cut]


def k_grid(rows: list[dict], rote: float, rocet1: float, tbv_bn: float, cet1_bn: float, ks: tuple[int, ...] = K_GRID) -> list[dict]:
    """For several k: median P/TBV and P/CET1 of the k nearest peers (ties included, as in the sheet Peers) and the raw values in EUR bn, before the cost of equity factor."""
    out = []
    for k in ks:
        a, b = _near(rows, "rote", rote, k), _near(rows, "rocet1", rocet1, k)
        if not a or not b:
            continue
        pa, pb = sorted(r["ptbv"] for r in a), sorted(r["pcet1"] for r in b)
        med = lambda v: v[len(v) // 2] if len(v) % 2 else (v[len(v) // 2 - 1] + v[len(v) // 2]) / 2  # noqa: E731
        out.append({"k": k, "n_tbv": len(a), "n_cet1": len(b), "ptbv": med(pa), "pcet1": med(pb), "value_tbv": med(pa) * tbv_bn, "value_cet1": med(pb) * cet1_bn})
    return out


G_GRID = (0.0, 0.01, 0.02, 0.03)
GRID_K, GRID_COE = 20, 0.10  # the defaults of Calc N17 and N24: the static grids use them


def g_grid(rows: list[dict], rote: float, rocet1: float, tbv_bn: float, cet1_bn: float, k: int = GRID_K, coe: float = GRID_COE, gs: tuple[float, ...] = G_GRID) -> list[dict]:
    """For several g: the cost of equity that the k nearest peers imply (g + (return - g) / multiple, median), the factor (peer cost of equity - g) / (coe - g),
    and the value of the target on tangible equity and on CET1 after the factor (EUR bn), as the sheets Peers and Calc compute them."""
    a, b = _near(rows, "rote", rote, k), _near(rows, "rocet1", rocet1, k)
    if not a or not b:
        return []
    med = lambda v: float(pd.Series(v).median())  # noqa: E731
    out = []
    for g in gs:
        ca, cb = med([g + (r["rote"] - g) / r["ptbv"] for r in a]), med([g + (r["rocet1"] - g) / r["pcet1"] for r in b])
        fa, fb = ((ca - g) / (coe - g) if ca > g and coe > g else 1.0), ((cb - g) / (coe - g) if cb > g and coe > g else 1.0)
        out.append({"g": g, "coe_tbv": ca, "coe_cet1": cb, "factor_tbv": fa, "factor_cet1": fb,
                    "value_tbv": med([r["ptbv"] for r in a]) * tbv_bn * fa, "value_cet1": med([r["pcet1"] for r in b]) * cet1_bn * fb})
    return out


def gordon_check(query: Query, rows: list[dict], g: float = 0.02) -> dict[str, Any]:
    """Implied cost of equity of the peers by three routes, with the Gordon model P/TBV = (RoTE - g) / (cost of equity - g):
    (1) trailing RoTE at the market multiple; (2) consensus RoTE of the first fiscal year at the market multiple; (3) consensus RoTE at the multiple of the analyst target price.
    Per-share values of Bloomberg are in EUR and the price and the consensus EPS are in the currency of the stock: the consensus RoTE uses the exchange rate that follows from
    price / (price to book ratio x book value) so that the units agree. Returns the number of peers, median and quartiles of each route."""
    tickers = [r["ticker"] for r in rows if r.get("ticker")]
    if not tickers:
        return {}
    marks = ",".join("?" * len(tickers))
    s = query(f"""SELECT ticker, field, value FROM bbg_equity_snapshot x WHERE ticker IN ({marks}) AND field IN ('PX_LAST', 'BOOK_VAL_PER_SH', 'PX_TO_BOOK_RATIO', 'TANG_BOOK_VAL_PER_SH', 'BEST_TARGET_PRICE')
                 AND pull_date = (SELECT MAX(pull_date) FROM bbg_equity_snapshot y WHERE y.ticker = x.ticker AND y.field = x.field)""", tuple(tickers))
    c = query(f"""SELECT ticker, value FROM bbg_consensus x WHERE ticker IN ({marks}) AND field = 'BEST_EPS' AND fperiod = '1FY' AND pull_date = (SELECT MAX(pull_date) FROM bbg_consensus y WHERE y.ticker = x.ticker)""", tuple(tickers))
    if s.empty:
        return {}
    snap = {t: dict(zip(g_["field"], g_["value"])) for t, g_ in s.groupby("ticker")}
    eps1 = dict(zip(c["ticker"], c["value"]))
    r1, r2, r3 = [], [], []
    for p in rows:
        sn = snap.get(p["ticker"], {})
        px, p2b, bv, tb, tp, e1 = _f(sn.get("PX_LAST")), _f(sn.get("PX_TO_BOOK_RATIO")), _f(sn.get("BOOK_VAL_PER_SH")), _f(sn.get("TANG_BOOK_VAL_PER_SH")), _f(sn.get("BEST_TARGET_PRICE")), _f(eps1.get(p["ticker"]))
        if p["ptbv"] > 0 and p["rote"] > g:
            r1.append(g + (p["rote"] - g) / p["ptbv"])
        if None in (px, p2b, bv, tb, e1) or p2b <= 0 or bv <= 0 or tb <= 0:
            continue
        fx = px / (p2b * bv)  # local currency per EUR
        rote_f = e1 / (tb * fx)
        if not -0.10 < rote_f < 0.40 or rote_f <= g:
            continue
        r2.append(g + (rote_f - g) / p["ptbv"])
        if tp and tp > 0:
            r3.append(g + (rote_f - g) / (p["ptbv"] * tp / px))
    q = lambda v: {"n": len(v), "median": float(pd.Series(v).median()) if v else None, "q1": float(pd.Series(v).quantile(0.25)) if v else None, "q3": float(pd.Series(v).quantile(0.75)) if v else None}  # noqa: E731
    return {"g": g, "trailing": q(r1), "consensus": q(r2), "target": q(r3)}


# ------------------------------------------------------------------------------------------------ everything
def load(query: Query, banks: list, market: dict) -> dict[str, Any]:
    """The data of the pack for NBG (banks[0]) and the first target (banks[1]). A part that fails is left empty and named in 'missing'."""
    pack: dict[str, Any] = {"missing": []}

    def part(name: str, fn: Callable[[], Any], default: Any) -> Any:
        try:
            v = fn()
        except Exception as e:  # noqa: BLE001 - one missing table must not stop the workbook
            pack["missing"].append(f"{name}: {type(e).__name__}: {str(e)[:100]}")
            return default
        if not v:
            pack["missing"].append(f"{name}: no data")
        return v if v else default

    names = ("nbg", "tgt")
    leis = [s["lei"] for s in market["slots"][:2]]
    pack["funnel"] = market["peers"].get("funnel", [])
    pack["removed_by_reason"] = market["peers"].get("removed_by_reason", {})
    for i, nm in enumerate(names):
        k = banks[i].key
        pack[f"or2_{nm}"] = part(f"OR2 {nm}", lambda k=k: or2_lines(query, k), {})
        pack[f"te_{nm}"] = part(f"EBA exercise {nm}", lambda k=k: te_lines(query, k), {})
        pack[f"cc2_{nm}"] = part(f"CC2 {nm}", lambda k=k: cc2_summary(query, k), {})
        pack[f"cr1_{nm}"] = part(f"CR1 {nm}", lambda k=k: cr1_detail(query, k), {})
        pack[f"bonds_{nm}"] = part(f"bonds {nm}", lambda l=leis[i]: bonds_by_rank(query, l), {})
        pack[f"irrbb_nii_{nm}"] = {c: (it.value, it.period) for c, it in banks[i].irrbb_nii.items() if it.value is not None}
    pack["ecb"] = part("ECB drivers", lambda: ecb_drivers(query, "LU"), {})
    pack["dfr_2025"] = next((p["avg"] for p in market["rates"]["periods"] if p["label"] == "2025" and p["type"] == "Y"), None)
    rows = market["peers"]["rows"]
    tb = None
    t = banks[1]
    if t.get("cc1_cet1_before_adj") and t.get("cc1_intangibles") is not None and t.get("cet1"):
        tb = (t.get("cc1_cet1_before_adj") - abs(t.get("cc1_intangibles"))) / 1e9
        ni = market["slots"][1].get("ni_ltm") or market["slots"][1].get("ni_fy")
        if tb > 0 and ni:
            pack["k_grid"] = part("k grid", lambda: k_grid(rows, ni / 1000 / tb, ni / 1000 / (t.get("cet1") / 1e9), tb, t.get("cet1") / 1e9), [])
            pack["g_grid"] = part("g grid", lambda: g_grid(rows, ni / 1000 / tb, ni / 1000 / (t.get("cet1") / 1e9), tb, t.get("cet1") / 1e9), [])
    pack["gordon"] = part("Gordon check", lambda: gordon_check(query, rows), {})
    return pack
