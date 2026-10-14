"""Analytics on the external statistics: group aggregates and pass-through of market rates to the rates of banks.

  monthly(conn, concept)                         monthly series of one concept, one column for each country
  aggregate(conn, concept, group, weight)        a geographic group: weighted mean, simple mean, median, minimum, maximum, number of countries
  pass_through(conn)                             for each country, product, and rate cycle: the share of the change of the market rate that the retail rate follows (beta)
  group_betas(df, group)                         betas of a group
The pass-through measure is the cumulative beta of a cycle: (change of the retail rate) / (change of the 3-month Euribor), each between the start and the end of the cycle.
A rate is the average of 3 months, which removes the noise of a single month. A cycle in which the market rate moves less than half a point has no beta
(a cycle that is not finished needs a move of a quarter point).
"""

from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

# cycles of the 3-month Euribor (month before the first move, month of the end of the effect)
CYCLES = {
    "hike 2005-08": ("2005-11", "2008-09"),
    "cut 2008-10": ("2008-09", "2010-06"),
    "hike 2022-23": ("2022-06", "2023-12"),
    "cut 2024-25": ("2024-06", "2025-12"),
    "hike 2026 (to date)": ("2026-02", "2026-08"),  # the cycle is not finished: the end is the last month of the bank rates
}
MIN_MOVE = 0.5  # percentage points of the market rate
MIN_MOVE_BY_CYCLE = {"hike 2026 (to date)": 0.25}  # a cycle that is not finished has moved less; its betas are early and can change
# product -> (concept of the rate, concept of the weight: the stock that the rate applies to)
DEP_HH, DEP_NFC = "BSI/N.A.L20.A.1.U2.2250.Z01.E", "BSI/N.A.L20.A.1.U2.2240.Z01.E"
LOAN_HH, LOAN_NFC = "BSI/N.A.A20.A.1.U2.2250.Z01.E", "BSI/N.A.A20.A.1.U2.2240.Z01.E"
PRODUCTS = {
    "deposits households, overnight": ("MIR/B.L21.A.R.A.2250.EUR.N", DEP_HH),
    "deposits corporations, overnight": ("MIR/B.L21.A.R.A.2240.EUR.N", DEP_NFC),
    "deposits households, agreed maturity, new": ("MIR/B.L22.A.R.A.2250.EUR.N", DEP_HH),
    "deposits corporations, agreed maturity, new": ("MIR/B.L22.A.R.A.2240.EUR.N", DEP_NFC),
    "deposits households, agreed maturity, book": ("MIR/B.L22.A.R.A.2250.EUR.O", DEP_HH),
    "deposits corporations, agreed maturity, book": ("MIR/B.L22.A.R.A.2240.EUR.O", DEP_NFC),
    "deposits households, redeemable at notice": ("MIR/B.L23.A.R.A.2250.EUR.N", DEP_HH),
    "loans corporations, new (cost of borrowing)": ("MIR/B.A2I.AM.R.A.2240.EUR.N", LOAN_NFC),
    "loans households, house purchase, new (cost of borrowing)": ("MIR/B.A2C.AM.R.A.2250.EUR.N", LOAN_HH),
    "loans corporations, book": ("MIR/B.A20.A.R.A.2240.EUR.O", LOAN_NFC),
    "loans households, book": ("MIR/B.A20.A.R.A.2250.EUR.O", LOAN_HH),
    "loans households, consumption, new": ("MIR/B.A2B.A.R.A.2250.EUR.N", LOAN_HH),
}


def monthly(conn: sqlite3.Connection, concept: str, indicator: str | None = None) -> pd.DataFrame:
    """Monthly values of a concept (or of an indicator name), index = month (YYYY-MM), one column for each country."""
    col, val = ("indicator", indicator) if indicator else ("concept", concept)
    d = pd.read_sql_query(f"SELECT country, period, value FROM v_ext_obs WHERE {col} = ? AND freq = 'M'", conn, params=(val,))
    if d.empty:
        return pd.DataFrame()
    return d.pivot_table(index="period", columns="country", values="value", aggfunc="last").sort_index()


def members(conn: sqlite3.Connection, group: str) -> list[str]:
    rows = conn.execute("SELECT iso2 FROM ext_geo_group WHERE group_name = ? ORDER BY iso2", (group,)).fetchall()
    if not rows:
        raise ValueError(f"unknown group {group}: {[r[0] for r in conn.execute('SELECT DISTINCT group_name FROM ext_geo_group')]}")
    return [r[0] for r in rows]


def aggregate(conn: sqlite3.Connection, concept: str, group: str, weight: str | None = None, indicator: str | None = None) -> pd.DataFrame:
    """Aggregate of a monthly concept over the countries of a group. The weighted mean uses the weight concept of the same month (the last known value when a month is missing);
    a country without a weight in the month is left out of the weighted mean. Without a weight concept the weighted mean is the simple mean."""
    x = monthly(conn, concept, indicator)
    cols = [c for c in members(conn, group) if c in x.columns]
    x = x[cols]
    out = pd.DataFrame(index=x.index)
    out["mean"], out["median"], out["min"], out["max"], out["n"] = x.mean(axis=1), x.median(axis=1), x.min(axis=1), x.max(axis=1), x.notna().sum(axis=1)
    if weight:
        w = monthly(conn, weight).reindex(index=x.index.union(monthly(conn, weight).index)).sort_index().ffill().reindex(x.index)
        w = w.reindex(columns=cols)
        ok = x.notna() & w.notna() & (w > 0)
        out["wmean"] = (x.where(ok) * w.where(ok)).sum(axis=1) / w.where(ok).sum(axis=1).replace(0, np.nan)
    else:
        out["wmean"] = out["mean"]
    return out[["wmean", "mean", "median", "min", "max", "n"]]


def _avg3(s: pd.Series, month: str) -> float:
    i = s.index.get_indexer([month])[0]
    if i < 2:
        return float("nan")
    return float(s.iloc[i - 2:i + 1].mean())


def pass_through(conn: sqlite3.Connection, reference: str = "euribor_3m", cycles: dict | None = None, products: dict | None = None, store: bool = True) -> pd.DataFrame:
    """Cumulative betas by country, product, and cycle. Writes the table ext_passthrough when store is true."""
    cycles, products = cycles or CYCLES, products or PRODUCTS
    mkt = monthly(conn, "", reference)
    if mkt.empty:
        raise ValueError(f"no market rate: pull the indicator {reference}")
    m = mkt["U2"].dropna()
    rows = []
    for product, (concept, _) in products.items():
        x = monthly(conn, concept)
        for country in x.columns:
            rs = x[country].reindex(m.index).interpolate(limit_area="inside")  # the retail rate on the months of the market rate; a gap inside the history is filled
            for cycle, (start, end) in cycles.items():
                if start not in rs.index or end not in rs.index or rs.reindex([start, end]).isna().any():
                    continue
                r0, r1, m0, m1 = _avg3(rs, start), _avg3(rs, end), _avg3(m, start), _avg3(m, end)
                if np.isnan([r0, r1, m0, m1]).any():
                    continue
                dm = m1 - m0
                beta = (r1 - r0) / dm if abs(dm) >= MIN_MOVE_BY_CYCLE.get(cycle, MIN_MOVE) else float("nan")
                half = float("nan")
                if abs(r1 - r0) > 1e-9 and not np.isnan(beta):
                    path = rs.loc[start:end].rolling(3).mean().dropna()
                    hit = ((path - r0) / (r1 - r0))
                    hit = hit[hit >= 0.5]
                    half = float(rs.index.get_loc(hit.index[0]) - rs.index.get_loc(start)) if len(hit) else float("nan")
                rows.append((country, product, concept, cycle, start, end, r0, r1, m0, m1, beta, half))
    df = pd.DataFrame(rows, columns=["country", "product", "concept", "cycle", "start", "end", "rate_start", "rate_end", "market_start", "market_end", "beta", "months_to_half"])
    if store:
        df.to_sql("ext_passthrough", conn, if_exists="replace", index=False)
        conn.commit()
    return df


def group_betas(conn: sqlite3.Connection, df: pd.DataFrame, group: str, weighted: bool = True) -> pd.DataFrame:
    """Beta of a group, by product and cycle: median, mean, and (when the stocks are available) the mean weighted by the deposit or loan stock at the start of the cycle."""
    cs = members(conn, group)
    d = df[df.country.isin(cs)].dropna(subset=["beta"])
    res = []
    for (product, cycle), g in d.groupby(["product", "cycle"]):
        row = {"product": product, "cycle": cycle, "n": len(g), "median": g.beta.median(), "mean": g.beta.mean(), "min": g.beta.min(), "max": g.beta.max()}
        if weighted:
            w = monthly(conn, PRODUCTS[product][1])
            ww = []
            for r in g.itertuples():
                if r.country in w.columns and r.start in w.index and not np.isnan(w.loc[r.start, r.country]):
                    ww.append((r.beta, w.loc[r.start, r.country]))
            if ww:
                b, wt = np.array(ww).T
                row["wmean"] = float((b * wt).sum() / wt.sum())
        res.append(row)
    return pd.DataFrame(res)
