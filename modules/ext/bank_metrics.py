"""Figures of one bank for the benchmark. They come from the P3DH clean layer (and from Bloomberg for the return ratios), in percent, as the ECB banking statistics give them.

  km1(conn, key)       capital, leverage, and liquidity ratios of each quarter (KM1)
  or2(conn, key)       income ratios of each year (OR2: three years in one filing)
  cr1(conn, key)       NPL ratio, gross loans, loans to non-banks, and loans by counterparty of each filing (CR1, sheet .a)
  bloomberg(conn, key) return on equity and on assets of the last fiscal year
  te(conn, key)        cost-to-income, impairment, return on assets and on equity of the fiscal years 2024 (EBA Transparency Exercise, loaded with pull_ext.py eba)
  irrbb_position(conn, key)  change of net interest income for +200 and -200 basis points, as a share of net interest income, against all banks of P3DH
A function returns {metric: {period: value}}. The period is the end of a quarter (KM1, CR1) or of a year (OR2, Bloomberg).
Assets of the income ratios are the interest-earning assets of OR2 (row 1c). The ECB divides by total assets, so the ratios of the bank are a little high.
The interest expense ratio is negative, as in the ECB data.
"""

from __future__ import annotations

import sqlite3
from statistics import median

KM1_AMOUNTS = {"cet1_ratio": "0010", "t1_ratio": "0020", "total_capital_ratio": "0030"}  # amount of capital divided by TREA (row 0040)
KM1_RATIOS = {"leverage_ratio": "0220", "lcr": "0320", "nsfr": "0350"}  # fractions in the clean layer
OR2_ROWS = {"0030": "interest_income", "0040": "interest_expense", "0050": "assets", "0060": "dividends", "0080": "fee_income", "0090": "fee_expense",
            "0100": "other_income", "0110": "other_expense", "0130": "trading", "0140": "banking_book"}
OR2_YEAR = {"0010": 0, "0020": 1, "0030": 2}  # column a is the year of the filing, b the year before, c two years before
CR1_COUNTERPARTY = {"0030": "central banks", "0040": "general government", "0050": "credit institutions", "0060": "other financial corporations", "0070": "non-financial corporations", "0090": "households"}
MIN_NII = 5e7  # a bank needs net interest income of EUR 50m for a meaningful sensitivity ratio


def km1(conn: sqlite3.Connection, key: str) -> dict[str, dict[str, float]]:
    codes = [*KM1_AMOUNTS.values(), *KM1_RATIOS.values(), "0040"]
    rows = conn.execute(f"""SELECT period_end, row_code, value FROM clean_period_fact WHERE entity_key = ? AND template_code = 'K_61.00' AND measure_col = 10
                            AND row_code IN ({','.join('?' * len(codes))}) AND value IS NOT NULL""", (key, *codes)).fetchall()
    by: dict[str, dict[str, float]] = {}
    for period, code, value in rows:
        by.setdefault(period, {})[code] = value
    out: dict[str, dict[str, float]] = {m: {} for m in (*KM1_AMOUNTS, *KM1_RATIOS)}
    for period, r in by.items():
        trea = r.get("0040")
        for m, code in KM1_AMOUNTS.items():
            if trea and trea > 0 and code in r:
                out[m][period] = r[code] / trea * 100
        for m, code in KM1_RATIOS.items():
            if code in r:
                out[m][period] = r[code] * 100
    return out


def or2(conn: sqlite3.Connection, key: str) -> dict[str, dict[str, float]]:
    """Income ratios of each calendar year. An expense is an expense whatever its sign in the filing."""
    rows = conn.execute(f"""SELECT reference_date, row_code, column_code, value FROM clean_fact WHERE entity_key = ? AND template_code = 'K_19.02' AND quality <> 'quarantined'
                            AND sheet = '' AND key_descriptor = '' AND column_code IN ('0010', '0020', '0030') AND row_code IN ({','.join('?' * len(OR2_ROWS))})
                            AND value IS NOT NULL ORDER BY reference_date""", (key, *OR2_ROWS)).fetchall()
    years: dict[int, dict[str, float]] = {}
    for ref, row, col, value in rows:  # a later filing replaces an earlier one for the same year
        years.setdefault(int(ref[:4]) - OR2_YEAR[col], {})[OR2_ROWS[row]] = value
    out: dict[str, dict[str, float]] = {m: {} for m in ("nii_to_assets", "interest_income_to_assets", "interest_expense_to_assets", "fee_to_assets", "income_to_assets", "nii_to_income", "fee_to_income")}
    for year, r in sorted(years.items()):
        need = ("interest_income", "interest_expense", "assets", "fee_income", "fee_expense")
        if any(n not in r for n in need) or r["assets"] <= 0:
            continue
        nii = r["interest_income"] - abs(r["interest_expense"])
        fees = r["fee_income"] - abs(r["fee_expense"])
        income = nii + r.get("dividends", 0.0) + fees + r.get("other_income", 0.0) - abs(r.get("other_expense", 0.0)) + r.get("trading", 0.0) + r.get("banking_book", 0.0)
        period, a = f"{year}-12-31", r["assets"]
        for m, v in (("nii_to_assets", nii / a), ("interest_income_to_assets", r["interest_income"] / a), ("interest_expense_to_assets", -abs(r["interest_expense"]) / a),  # negative, as the ECB gives it
                     ("fee_to_assets", fees / a), ("income_to_assets", income / a)):
            out[m][period] = v * 100
        if income > 0:
            out["nii_to_income"][period] = nii / income * 100
            out["fee_to_income"][period] = fees / income * 100
    return out


def cr1(conn: sqlite3.Connection, key: str) -> dict:
    """From sheet .a of CR1 (amounts): gross loans = performing + non-performing loans and advances. The mix is the share of each counterparty in the sum of the counterparties."""
    rows = conn.execute("""SELECT reference_date, row_code, column_code, value FROM clean_fact WHERE entity_key = ? AND template_code = 'K_21.01' AND cell_code LIKE '{K_21.01.a, r%'
                           AND row_code IN ('0020', '0030', '0040', '0050', '0060', '0070', '0090') AND column_code IN ('0010', '0040') AND quality <> 'quarantined'
                           AND sheet = '' AND key_descriptor = '' AND value IS NOT NULL""", (key,)).fetchall()
    cells: dict[str, dict[tuple[str, str], float]] = {}
    for ref, row, col, value in rows:
        cells.setdefault(ref, {})[(row, col)] = value
    out: dict = {"npl_ratio": {}, "gross_loans": {}, "nonbank_loans": {}, "loan_mix": {}}
    for ref, c in sorted(cells.items()):
        perf, npl = c.get(("0020", "0010")), c.get(("0020", "0040"))
        if perf is None or npl is None or perf + npl <= 0:
            continue
        gross = perf + npl
        out["npl_ratio"][ref], out["gross_loans"][ref] = npl / gross * 100, gross
        parts = {name: c.get((row, "0010"), 0.0) + c.get((row, "0040"), 0.0) for row, name in CR1_COUNTERPARTY.items() if (row, "0010") in c}
        total = sum(parts.values())
        if len(parts) == len(CR1_COUNTERPARTY) and total > 0 and abs(total - gross) <= 0.05 * gross:
            out["loan_mix"][ref] = {name: v / total * 100 for name, v in parts.items()}
            out["nonbank_loans"][ref] = total - parts["central banks"] - parts["credit institutions"]
    return out


def bloomberg(conn: sqlite3.Connection, key: str) -> dict[str, dict[str, float]]:
    r = conn.execute("SELECT latest_period_end, roe, roa FROM bbg_entity WHERE lei = ? AND found = 1", (key,)).fetchone()
    out: dict[str, dict[str, float]] = {"roe": {}, "roa": {}}
    if r and r[0]:
        for m, v in (("roe", r[1]), ("roa", r[2])):
            if v is not None:
                out[m][r[0]] = float(v)
    return out


TE_PNL = {  # label in the P&L sheet of the EBA Transparency Exercise -> name
    "Interest income": "interest_income", "Interest expenses": "interest_expense", "Net Fee and commission income": "fees", "TOTAL OPERATING INCOME_ NET": "income",
    "(Administrative expenses)": "admin", "(Cash contributions to resolution funds and deposit guarantee schemes)": "resolution", "(Depreciation)": "depreciation",
    "(Impairment or (-) reversal of impairment on financial assets not measured at fair value through profit or loss)": "impairment",
    "PROFIT OR (-) LOSS FOR THE YEAR": "profit",
}


def te(conn: sqlite3.Connection, key: str) -> dict[str, dict[str, float]]:
    """Ratios of the last full fiscal years from the EBA Transparency Exercise (table te_oth; empty when the bank or the table is missing). Only a December date with 4 quarters counts:
    the P&L amounts are year to date. Assets and equity are at the end of the year. Costs carry the minus sign of the ECB data: cost-to-income and the impairment ratio are negative."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'te_oth'").fetchone():
        return {}
    marks = ",".join("?" * len(TE_PNL))
    pnl = conn.execute(f"""SELECT period_end, label, amount FROM te_oth WHERE lei = ? AND sheet = 'P&L' AND n_quarters = 4 AND substr(period_end, 6, 5) = '12-31' AND label IN ({marks})
                           AND amount IS NOT NULL ORDER BY vintage""", (key, *TE_PNL)).fetchall()
    bal = conn.execute("""SELECT period_end, label, amount FROM te_oth WHERE lei = ? AND substr(period_end, 6, 5) = '12-31' AND amount IS NOT NULL AND
                          ((sheet = 'Assets' AND label = 'Total Assets' AND assets_fv = 0 AND assets_stages = 0) OR (sheet = 'Liabilities' AND label = 'TOTAL EQUITY'))
                          ORDER BY vintage""", (key,)).fetchall()
    years: dict[str, dict[str, float]] = {}
    for period, label, amount in pnl:
        years.setdefault(period, {})[TE_PNL[label]] = amount
    for period, label, amount in bal:
        years.setdefault(period, {})["assets" if label == "Total Assets" else "equity"] = amount
    out: dict[str, dict[str, float]] = {m: {} for m in ("cost_to_income", "impairment_to_assets", "roa_te", "roe_te")}
    for period, r in sorted(years.items()):
        if r.get("income", 0) > 0 and all(k in r for k in ("admin", "depreciation")):
            out["cost_to_income"][period] = -(abs(r["admin"]) + abs(r["depreciation"]) + abs(r.get("resolution", 0.0))) / r["income"] * 100
        if r.get("assets", 0) > 0:
            if "impairment" in r:
                out["impairment_to_assets"][period] = -r["impairment"] / r["assets"] * 100
            if "profit" in r:
                out["roa_te"][period] = r["profit"] / r["assets"] * 100
        if r.get("equity", 0) > 0 and "profit" in r:
            out["roe_te"][period] = r["profit"] / r["equity"] * 100
    return out


def all_metrics(conn: sqlite3.Connection, key: str) -> dict:
    """Every ratio of the bank by metric name and period, and the CR1 items (gross loans, loan mix)."""
    c = cr1(conn, key)
    ratios = {**km1(conn, key), **or2(conn, key), "npl_ratio": c["npl_ratio"], **bloomberg(conn, key), **te(conn, key)}
    return {"ratios": {m: v for m, v in ratios.items() if v}, "gross_loans": c["gross_loans"], "nonbank_loans": c["nonbank_loans"], "loan_mix": c["loan_mix"]}


def _iso_of_names(conn: sqlite3.Connection) -> dict[str, str]:
    names = {n.lower(): iso for iso, n in conn.execute("SELECT iso2, name FROM ext_country WHERE iso2 <> 'U2'")}
    names.update({"czech": "CZ", "czech republic": "CZ", "czechia": "CZ", "slovak republic": "SK"})
    return names


def country_of(conn: sqlite3.Connection, key: str) -> str | None:
    """Country (ISO code) of a bank: Bloomberg when it knows the bank, else the country of the P3DH classification."""
    r = conn.execute("SELECT country_iso FROM bbg_entity WHERE lei = ? AND found = 1", (key,)).fetchone()
    if r and r[0]:
        return r[0]
    r = conn.execute("SELECT country FROM v_entity_class WHERE entity_key = ?", (key,)).fetchone()
    return _iso_of_names(conn).get((r[0] or "").lower()) if r else None


def irrbb_position(conn: sqlite3.Connection, key: str, groups: dict[str, list[str]] | None = None) -> dict:
    """Change of net interest income for a parallel shift of +200 and -200 basis points (IRRBB1, K_68.00, column b), as a percent of the net interest income of the last OR2 year before
    the filing. All banks of P3DH with net interest income of EUR 50m or more form the comparison, each with its latest filing of the 12 months up to the date of the bank. Returns the bank, the median of its country, of the euro area, of all, and the rank:
    'above' = the share of the banks with a smaller figure (for +200: more benefit; for -200: a smaller loss means a higher figure)."""
    ent = {k: (n, c) for k, n, c in conn.execute("SELECT entity_key, entity_name, country FROM v_entity_class")}
    iso = _iso_of_names(conn)
    euro = {i for (i,) in conn.execute("SELECT iso2 FROM ext_country WHERE euro_area = 1")}
    irr = conn.execute("""SELECT entity_key, reference_date, row_code, value FROM clean_fact WHERE template_code = 'K_68.00' AND column_code = '0030' AND row_code IN ('0010', '0020')
                          AND quality <> 'quarantined' AND value IS NOT NULL""").fetchall()
    nii_rows = conn.execute("""SELECT entity_key, reference_date, SUM(CASE WHEN row_code = '0030' THEN value ELSE -ABS(value) END) FROM clean_fact  -- an expense is an expense whatever its sign in the filing: 164 of 204 banks file it positive
                               WHERE template_code = 'K_19.02' AND column_code = '0010' AND row_code IN ('0030', '0040')
                               AND quality <> 'quarantined' AND sheet = '' AND key_descriptor = '' AND value IS NOT NULL GROUP BY entity_key, reference_date HAVING COUNT(*) = 2""").fetchall()
    nii: dict[str, list[tuple[str, float]]] = {}
    for k, ref, v in nii_rows:
        nii.setdefault(k, []).append((ref, v))
    by_bank: dict[str, dict[str, dict[str, float]]] = {}
    for k, ref, row, v in irr:
        by_bank.setdefault(k, {}).setdefault(ref, {})["up" if row == "0010" else "down"] = v
    dates = sorted(by_bank.get(key, {}))
    if not dates:
        return {}
    date = dates[-1]
    cutoff = f"{int(date[:4]) - 1}{date[4:]}"  # a peer counts with its latest filing of the 12 months up to the date of the bank (not all banks file at the same date)
    rows: dict[str, dict[str, float]] = {}
    for k, by_date in by_bank.items():
        ok = [d for d, r in by_date.items() if cutoff < d <= date and "up" in r and "down" in r]
        if not ok:
            continue
        d = max(ok)
        base = [x for r, x in sorted(nii.get(k, [])) if r <= d]
        if base and base[-1] >= MIN_NII:
            rows[k] = {"up": by_date[d]["up"] / base[-1] * 100, "down": by_date[d]["down"] / base[-1] * 100, "date": d}
    if key not in rows:
        return {}
    country = iso.get((ent.get(key, ("", ""))[1] or "").lower())
    out: dict = {"date": date, "first_date": min(r["date"] for r in rows.values()), "n_banks": len(rows), "bank": {"up": rows[key]["up"], "down": rows[key]["down"]}}
    pools = {"country": [r for k, r in rows.items() if country and iso.get((ent.get(k, ("", ""))[1] or "").lower()) == country],
             "euro area": [r for k, r in rows.items() if iso.get((ent.get(k, ("", ""))[1] or "").lower()) in euro], "all": list(rows.values())}
    for g, members in (groups or {}).items():
        pools[g] = [r for k, r in rows.items() if iso.get((ent.get(k, ("", ""))[1] or "").lower()) in members]
    for name, pool in pools.items():
        if pool:
            out[name] = {"n": len(pool), "up": median(r["up"] for r in pool), "down": median(r["down"] for r in pool)}
    out["above"] = {s: sum(r[s] < rows[key][s] for r in rows.values()) / len(rows) * 100 for s in ("up", "down")}
    return out
