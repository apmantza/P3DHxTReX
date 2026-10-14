"""Benchmark of one bank against the banks of its country, the euro area, the EU, and geographic groups. The comparison data are the ECB statistics in the database.

  report(conn, key)                 every table below for the bank with the entity key (the LEI)
  compare(conn, metric, bank, country, groups)
  loan_mix(conn, bank_mix, country, groups, period)
  loan_growth(conn, gross_loans, country, groups)
The ratios use the consolidated banking data of the ECB (CBD2, domestic banks of each country, all sizes) and the supervisory banking statistics (SUP, leverage ratio).
The country figure and the euro area figure are the ECB aggregates. The EU figures are the median of the country figures (each country counts once). A group figure is the median of its countries.
The loan mix and the loan growth use the balance sheet statistics (BSI: loans of the monetary financial institutions of the country to residents of the euro area).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import bank_metrics

GENERIC_GROUPS = {"EU27", "Euro area (members)", "Non-euro EU"}  # shown in their own columns or not a peer set


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    concept: str
    freq: str  # A: annual series, Q: quarterly series


def _cbd(item: str, framework: str = "A") -> str:
    return f"CBD2/W0.11._Z._Z.A.{framework}.{item}._Z._Z._Z._Z._Z._Z.PC"


METRICS = [
    Metric("cet1_ratio", "CET1 ratio", _cbd("I4008"), "Q"),
    Metric("t1_ratio", "Tier 1 ratio", _cbd("I4002"), "Q"),
    Metric("total_capital_ratio", "Total capital ratio", _cbd("I4001"), "Q"),
    Metric("leverage_ratio", "Leverage ratio (transitional)", "SUP/W0._Z.KSV13._T.ALL._Z._Z._Z.PCT.C", "Q"),
    Metric("lcr", "Liquidity coverage ratio", _cbd("I3017"), "Q"),
    Metric("nsfr", "Net stable funding ratio", _cbd("I3214"), "Q"),
    Metric("npl_ratio", "NPL ratio (gross loans)", _cbd("I3632", "F"), "Q"),
    Metric("nii_to_assets", "Net interest income / assets", _cbd("I2410"), "A"),
    Metric("interest_income_to_assets", "Interest income / assets", _cbd("I2411"), "A"),
    Metric("interest_expense_to_assets", "Interest expense / assets", _cbd("I2412"), "A"),
    Metric("fee_to_assets", "Net fees / assets", _cbd("I2430"), "A"),
    Metric("income_to_assets", "Operating income / assets", _cbd("I2400"), "A"),
    Metric("nii_to_income", "Net interest income / operating income", _cbd("I2510"), "A"),
    Metric("fee_to_income", "Net fees / operating income", _cbd("I2530"), "A"),
    Metric("roe", "Return on equity", _cbd("I2003"), "A"),
    Metric("roa", "Return on assets", _cbd("I2004"), "A"),
]
BY_KEY = {m.key: m for m in METRICS}

# loans of the banks (BSI A20 stocks, euro area residents) by counterparty, as the groups of the CR1 counterparties
LOAN_SECTORS = {  # each group has options: the first option of which every sector exists is used. A code with a minus sign is subtracted: 0000 is all loans, 2000 loans to non-MFIs, 2200 loans to non-MFIs without general government.
    "credit institutions": [["1000"], ["0000", "-2000"], ["1200"]],  # CR1 central banks and credit institutions form one group (the ECB sector MFIs includes the Eurosystem)
    "general government": [["2100"], ["2000", "-2200"]],
    "other financial corporations": [["2210", "2220"], ["2200", "-2240", "-2250"]],  # other financial institutions and funds, insurance, and pension funds
    "non-financial corporations": [["2240"]],
    "households": [["2250"]],
}
LOAN_STOCK = "BSI/N.A.A20.A.1.U2.{sector}.Z01.E"
LOAN_TOTAL = LOAN_STOCK.format(sector="0000")


def members(conn: sqlite3.Connection, group: str) -> list[str]:
    return [r[0] for r in conn.execute("SELECT iso2 FROM ext_geo_group WHERE group_name = ? ORDER BY iso2", (group,))]


def groups_of(conn: sqlite3.Connection, country: str) -> dict[str, list[str]]:
    """The geographic groups that contain the country (the generic ones are left out), with their members."""
    names = [g for (g,) in conn.execute("SELECT group_name FROM ext_geo_group WHERE iso2 = ? ORDER BY group_name", (country,)) if g not in GENERIC_GROUPS]
    return {g: members(conn, g) for g in names}


def cross_section(conn: sqlite3.Connection, concept: str, freq: str) -> pd.DataFrame:
    """The values of a concept: one row for each period end, one column for each country (the euro area is U2)."""
    d = pd.read_sql_query("""SELECT s.ref_area AS country, o.period_end, o.value FROM ext_series s JOIN ext_obs o ON o.source = s.source AND o.series_key = s.series_key
                             WHERE s.concept = ? AND s.freq = ? AND o.value IS NOT NULL""", conn, params=(concept, freq))
    if d.empty:
        return pd.DataFrame()
    return d.pivot_table(index="period_end", columns="country", values="value", aggfunc="last").sort_index()


def _row_for(x: pd.DataFrame, period: str, freq: str) -> pd.Series | None:
    """The row of the cross-section for a bank period: the same quarter end, or for an annual series the same calendar year."""
    if x.empty:
        return None
    if freq == "A":
        hit = x.index[x.index.str[:4] == period[:4]]
        return x.loc[hit[-1]] if len(hit) else None
    return x.loc[period] if period in x.index else None


def compare(conn: sqlite3.Connection, metric: Metric, bank: dict[str, float], country: str, groups: dict[str, list[str]] | None = None) -> pd.DataFrame:
    """One row for each period of the bank. 'eu_rank' is the share of the EU countries (with data) that have a lower figure than the bank."""
    x = cross_section(conn, metric.concept, metric.freq)
    eu = members(conn, "EU27")
    rows = []
    for period, value in sorted(bank.items()):
        r = _row_for(x, period, metric.freq)
        row = {"metric": metric.key, "label": metric.label, "period": period, "bank": value}
        if r is None:
            row.update({"country": np.nan, "euro_area": np.nan, "eu_median": np.nan, "eu_rank": np.nan, "n_eu": 0})
        else:
            peers = r[[c for c in eu if c in r.index]].dropna()
            row.update({"country": r.get(country, np.nan), "euro_area": r.get("U2", np.nan), "eu_median": peers.median() if len(peers) else np.nan,
                        "eu_rank": float((peers < value).mean() * 100) if len(peers) else np.nan, "n_eu": len(peers)})
            for g, cs in (groups or {}).items():
                vals = r[[c for c in cs if c in r.index]].dropna()
                row[g] = vals.median() if len(vals) else np.nan
        row["bank_less_country"] = value - row["country"] if row["country"] == row["country"] else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def _month(period: str) -> str:
    return period[:7]


def _stock_cross(conn: sqlite3.Connection, concept: str) -> pd.DataFrame:
    x = cross_section(conn, concept, "M")
    if not x.empty:
        x.index = x.index.str[:7]
    return x


def loan_mix(conn: sqlite3.Connection, bank_mix: dict[str, float], country: str, groups: dict[str, list[str]] | None, period: str, exclude: tuple[str, ...] = ()) -> pd.DataFrame:
    """Share of each counterparty in the loans, bank against the banks of the country, the euro area, and the groups. A country needs a figure for every counterparty (else it is left out of
    the group). The group shares are the shares of the sum of the stocks of its countries. A counterparty in 'exclude' is left out of the bank and of the ECB figures, and the shares add up to 100 again.
    The last row gives the number of countries behind each ECB column. The balance sheet statistics cover the euro area countries only."""
    month = _month(period)
    codes = {c.lstrip("-") for options in LOAN_SECTORS.values() for option in options for c in option}
    sectors = {c: _stock_cross(conn, LOAN_STOCK.format(sector=c)) for c in codes}
    mix = {**{k: v for k, v in bank_mix.items() if k not in ("central banks", "credit institutions")}, "credit institutions": bank_mix.get("central banks", 0.0) + bank_mix.get("credit institutions", 0.0)}

    def value(code: str, area: str) -> float:
        c = code.lstrip("-")
        v = sectors[c][area].get(month, np.nan) if area in sectors[c].columns else np.nan
        return -v if code.startswith("-") else v

    def stocks(area: str) -> dict[str, float] | None:
        out = {}
        for name, options in LOAN_SECTORS.items():
            for option in options:
                vals = [value(c, area) for c in option]
                if not any(np.isnan(v) for v in vals):
                    out[name] = float(sum(vals))
                    break
            else:
                return None
        return out

    def share(areas: list[str]) -> tuple[dict[str, float] | None, int]:
        got = [s for s in (stocks(a) for a in areas) if s]
        if not got:
            return None, 0
        total = {k: sum(g[k] for g in got) for k in LOAN_SECTORS if k not in exclude}
        grand = sum(total.values())
        return {k: v / grand * 100 for k, v in total.items()}, len(got)

    euro, n_euro = share(["U2"])
    if euro is None:
        euro, n_euro = share(members(conn, "Euro area (members)"))
    cols = {"country": share([country]), "euro area": (euro, n_euro)}
    for g, cs in (groups or {}).items():
        cols[g] = share(cs)
    kept = sum(v for k, v in mix.items() if k not in exclude)
    rows = []
    for name in (n for n in LOAN_SECTORS if n not in exclude):
        row = {"counterparty": name, "bank": mix[name] / kept * 100 if name in mix and kept > 0 else np.nan}
        for c, (s, _) in cols.items():
            row[c] = s[name] if s else np.nan
        row["bank_less_country"] = row["bank"] - row["country"] if row["country"] == row["country"] else np.nan
        rows.append(row)
    rows.append({"counterparty": "countries behind the figure", "bank": np.nan, **{c: float(n) for c, (_, n) in cols.items()}, "bank_less_country": np.nan})
    return pd.DataFrame(rows)


def loan_growth(conn: sqlite3.Connection, gross_loans: dict[str, float], country: str, groups: dict[str, list[str]] | None, concept: str = LOAN_TOTAL) -> pd.DataFrame:
    """Annual growth of the loans of the bank (CR1) against the growth of the loan stock of the banks of the country (BSI, loans to residents of the euro area, the concept says which sectors),
    at the same month. The stocks are not adjusted for reclassifications and exchange rates."""
    x = _stock_cross(conn, concept)
    eu = members(conn, "EU27")
    rows = []
    for period, value in sorted(gross_loans.items()):
        before = f"{int(period[:4]) - 1}{period[4:]}"
        if before not in gross_loans or gross_loans[before] <= 0:
            continue
        m, m0 = _month(period), _month(before)
        row = {"period": period, "bank": (value / gross_loans[before] - 1) * 100}
        if x.empty or m not in x.index or m0 not in x.index:
            rows.append({**row, "country": np.nan, "euro_area": np.nan, "eu_median": np.nan, "bank_less_country": np.nan})
            continue
        g = (x.loc[m] / x.loc[m0] - 1) * 100
        row.update({"country": g.get(country, np.nan), "euro_area": g.get("U2", np.nan), "eu_median": g[[c for c in eu if c in g.index]].median()})
        for name, cs in (groups or {}).items():
            row[name] = g[[c for c in cs if c in g.index]].median()
        row["bank_less_country"] = row["bank"] - row["country"] if row["country"] == row["country"] else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


CONTEXT = {"domestic banks, share of the banking assets of the country (%)": ("CBD2/W0.11._Z._Z.A.A.I0002._Z._Z._Z._Z._Z._Z.PC", "A"),
           "5 largest credit institutions, share of the assets (%)": ("SSI/122C.S10.X.A1.Z0Z.Z", "A"),
           "Herfindahl index of the total assets of the credit institutions": ("SSI/122C.H10.X.A1.Z0Z.Z", "A")}


def context(conn: sqlite3.Connection, country: str) -> dict[str, tuple[str, float]]:
    """How far the country figure stands for the bank: the domestic banks may be a small part of the sector, and the bank is part of the country figure. {name: (year, value)}."""
    out = {}
    for name, (concept, freq) in CONTEXT.items():
        x = cross_section(conn, concept, freq)
        if not x.empty and country in x.columns and x[country].notna().any():
            last = x[country].dropna()
            out[name] = (last.index[-1][:4], float(last.iloc[-1]))
    return out


def report(conn: sqlite3.Connection, key: str, country: str | None = None, groups: list[str] | None = None) -> dict:
    """Every table for a bank. Returns {'bank', 'country', 'groups', 'context', 'ratios', 'loan_mix', 'loan_mix_non_bank', 'loan_growth', 'irrbb'}."""
    country = country or bank_metrics.country_of(conn, key)
    if not country:
        raise ValueError("the country of the bank is not known: give it as an ISO code")
    grp = {g: members(conn, g) for g in groups} if groups is not None else groups_of(conn, country)
    figures = bank_metrics.all_metrics(conn, key)
    name = conn.execute("SELECT entity_name FROM v_entity_class WHERE entity_key = ?", (key,)).fetchone()
    ratios = [compare(conn, m, figures["ratios"][m.key], country, grp) for m in METRICS if m.key in figures["ratios"]]
    mix = figures["loan_mix"]
    last = max(mix) if mix else None
    growth = [loan_growth(conn, figures["gross_loans"], country, grp, LOAN_TOTAL).assign(measure="all loans"),
              loan_growth(conn, figures["nonbank_loans"], country, grp, LOAN_STOCK.format(sector="2000")).assign(measure="loans to non-banks")]
    return {"bank": name[0] if name else key, "country": country, "groups": grp, "context": context(conn, country),
            "ratios": pd.concat(ratios, ignore_index=True) if ratios else pd.DataFrame(),
            "loan_mix": loan_mix(conn, mix[last], country, grp, last).assign(period=last) if last else pd.DataFrame(),
            "loan_mix_non_bank": loan_mix(conn, mix[last], country, grp, last, exclude=("credit institutions",)).assign(period=last) if last else pd.DataFrame(),
            "loan_growth": pd.concat([g for g in growth if not g.empty], ignore_index=True) if any(not g.empty for g in growth) else pd.DataFrame(),
            "irrbb": bank_metrics.irrbb_position(conn, key, grp)}
