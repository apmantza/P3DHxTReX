"""Every P3DH entity matched to Bloomberg by its LEI. The security /lei/<LEI> gives the issuer: name, parent, tax rate, ratings,
fundamentals, and the amount of debt. It works for unlisted banks too."""

from __future__ import annotations

import datetime as dt
import re
import sqlite3

from . import match
from .client import Client

# Bloomberg field -> column of bbg_entity
FIELDS = {
    "NAME": "name", "LONG_COMP_NAME": "long_name", "ID_BB_COMPANY": "bb_company", "COUNTRY_ISO": "country_iso", "INDUSTRY_SECTOR": "sector",
    "PRIVTE_STRUCTRE_INDCTR": "private_flag", "ISSUER_EQUITY_TICKER": "equity_ticker", "ID_BB_ULTIMATE_PARENT_CO_NAME": "parent_name",
    "ULT_PARENT_TICKER_EXCHANGE": "parent_ticker", "LEI_ULTIMATE_PARENT_COMPANY": "parent_lei", "LEI_DIRECT_PARENT_COMPANY": "direct_parent_lei",
    "DDIS_NUM_ISSUES_BND_LN": "n_bond_issues", "DDIS_AMT_OUTSTANDING_BND_LN": "bond_amt_outstanding", "IS_STATUTORY_TAX_RATE": "statutory_tax_rate",
    "EFF_TAX_RATE": "effective_tax_rate", "RTG_SP_LT_LC_ISSUER_CREDIT": "rating_sp", "RTG_MDY_ISSUER": "rating_moodys", "RTG_FITCH_LT_ISSUER_DEFAULT": "rating_fitch",
    "LATEST_PERIOD_END_DT_FULL_RECORD": "latest_period_end", "BS_TOT_ASSET": "total_assets", "NET_INCOME": "net_income", "IS_OPERATING_EXPN": "operating_expenses",
    "TOT_COMMON_EQY": "common_equity", "BS_CUSTOMER_DEPOSITS": "customer_deposits", "BS_TOT_LOAN": "total_loans", "BS_RISK_WEIGHTED_ASSETS": "rwa",
    "SALES_REV_TURN": "revenue", "RETURN_COM_EQY": "roe", "RETURN_ON_ASSET": "roa", "BS_TIER1_CAP_RATIO": "tier1_ratio", "IS_INT_INC": "interest_income",
    "BS_CASH_NEAR_CASH_ITEM": "cash", "TRAIL_12M_NET_INC": "net_income_ltm", "TRAIL_12M_CONT_INC": "net_income_cont_ltm", "COMPANY_TO_PARENT_RELATIONSHIP": "parent_relationship", "BUSINESS_STRUCTURE": "business_structure",
}
STRUCTURE = "CAST_CORPORATE_STRUCTURE"  # bulk field: the group of the issuer, each company with its debt, equity, and CDS ticker


def own_tickers(structure: list | None, bb_company) -> tuple[str | None, str | None]:
    """Debt ticker and CDS ticker of the issuer itself: the row of the group structure that has its Bloomberg company id."""
    for item in structure or []:
        if isinstance(item, dict) and bb_company is not None and item.get("BBID") == bb_company:
            return item.get("Company Debt Ticker") or None, item.get("CDS Ticker") or None
    return None, None
LEI_RE = match.LEI_RE


def pull_debt_profile(client: Client, conn: sqlite3.Connection, ids: list[tuple[str, str]]) -> int:
    """Amount of debt that matures in each year (EUR million), for bonds and for bonds plus loans. ids: (P3DH key, LEI in Bloomberg)."""
    data = client.ref([f"/lei/{lei}" for _, lei in ids], ["DDIS_AMT_OUTSTANDING_BY_YR", "DDIS_AMT_OUTSTANDING_BY_YR_BNDLN"], overrides={"EQY_FUND_CRNCY": "EUR"})
    now = dt.datetime.now().isoformat(timespec="seconds")
    rows = []
    key_name = "Amount Outstanding - Ultimate Parent"
    for key, lei in ids:
        r = data.get(f"/lei/{lei}", {})
        by: dict[int, list] = {}
        for k, field in enumerate(("DDIS_AMT_OUTSTANDING_BY_YR", "DDIS_AMT_OUTSTANDING_BY_YR_BNDLN")):
            for item in r.get(field) or []:
                if isinstance(item, dict) and item.get("Year") is not None:
                    by.setdefault(int(item["Year"]), [None, None])[k] = item.get(key_name)
        rows += [(key, y, v[0], v[1], now) for y, v in by.items()]
    conn.executemany("INSERT OR REPLACE INTO bbg_debt_maturity VALUES (?, ?, ?, ?, ?)", rows)
    conn.commit()
    return len(rows)


def fall_back_to_name(client: Client, conn: sqlite3.Connection, ids: list[tuple[str, str | None, str]], data: dict) -> list[tuple[str, str | None, str]]:
    """A rebuilt LEI that Bloomberg does not know: find the bank by its name. data gets the fields of the LEI that is found."""
    names = dict(conn.execute("SELECT lei, MAX(entity_name) FROM entity GROUP BY lei").fetchall())
    out = []
    for key, lei, method in ids:
        r = data.get(f"/lei/{lei}", {}) if lei else {}
        if method != "lei" and (not lei or "_error" in r or r.get("NAME") is None):
            found = match.lei_by_name(client, names.get(key) or key)
            client.log(f"  {key} ({names.get(key)}): rebuilt LEI not in Bloomberg; name search gives {found}")
            if found:
                data.update(client.ref([f"/lei/{found}"], list(FIELDS) + [STRUCTURE], overrides={"EQY_FUND_CRNCY": "EUR"}))
                lei, method = found, "name"
        out.append((key, lei, method))
    return out


def pull(client: Client, conn: sqlite3.Connection, limit: int = 0) -> int:
    """One row in bbg_entity for each P3DH entity. The row is keyed by the P3DH key (a LEI, or a national code for a few groups)."""
    ids = match.identify(client, conn, limit)
    client.log(f"{len(ids)} P3DH entities: " + ", ".join(f"{m} {sum(1 for i in ids if i[2] == m)}" for m in ("lei", "lei_rebuilt", "name", "none")))
    asked = [(key, lei) for key, lei, _ in ids if lei]
    data = client.ref([f"/lei/{lei}" for _, lei in asked], list(FIELDS) + [STRUCTURE], overrides={"EQY_FUND_CRNCY": "EUR"})
    ids = fall_back_to_name(client, conn, ids, data)
    now = dt.datetime.now().isoformat(timespec="seconds")
    cols = ["lei", "pulled_at", "found", "bbg_lei", "match_method"] + list(FIELDS.values()) + ["debt_ticker", "cds_ticker"]
    rows = []
    for key, lei, method in ids:
        r = data.get(f"/lei/{lei}", {}) if lei else {}
        found = int("_error" not in r and r.get("NAME") is not None)
        debt, cds = own_tickers(r.get(STRUCTURE), r.get("ID_BB_COMPANY")) if found else (None, None)
        rows.append((key, now, found, lei if found else None, method if found else "none") + tuple(r.get(f) if found else None for f in FIELDS) + (debt, cds))
    update = ", ".join(f"{c} = excluded.{c}" for c in cols[1:])  # keeps market_basis and market_ticker
    conn.executemany(f"INSERT INTO bbg_entity ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) ON CONFLICT(lei) DO UPDATE SET {update}", rows)
    conn.commit()
    n_found = sum(r[2] for r in rows)
    client.log(f"found {n_found} of {len(rows)}; with debt {conn.execute('SELECT COUNT(*) FROM bbg_entity WHERE n_bond_issues > 0').fetchone()[0]}; "
               f"with an own equity ticker {conn.execute('SELECT COUNT(*) FROM bbg_entity WHERE equity_ticker IS NOT NULL').fetchone()[0]}")
    conn.execute("INSERT INTO bbg_pull_log (started_at, kind, detail, n_rows, status) VALUES (?, 'entities', ?, ?, 'ok')", (now, f"{len(ids)} entities", len(rows)))
    conn.commit()
    n = pull_debt_profile(client, conn, [(r[0], r[3]) for r in rows if r[2]])
    client.log(f"debt maturity profile: {n} rows")
    return len(rows)
