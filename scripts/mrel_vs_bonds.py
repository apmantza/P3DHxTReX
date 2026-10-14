"""Compare the MREL templates of P3DH (KM2 and TLAC1) with the bonds of a bank in the Bloomberg tables.

  dashboard/.venv/Scripts/python scripts/mrel_vs_bonds.py                      # BIL
  dashboard/.venv/Scripts/python scripts/mrel_vs_bonds.py --lei 5UMCZOEYKCVFAW8ZLO05   # NBG

TLAC1 (K_91.00) is filed once a year. KM2 (K_90.01) is filed each quarter. The bonds are those of the database that were outstanding on the reference date
(issued on or before it, not matured) and that have a residual maturity of at least 1 year, which is the condition for MREL. Amounts are in EUR million.
The amount of a bond is its amount outstanding today, not on the reference date.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BIL = "9CZ7TVMR36CYD5TZBS50"


def fx_table(conn: sqlite3.Connection) -> dict[str, float]:
    out = {"EUR": 1.0, "ATS": 13.7603}
    for series, value in conn.execute("SELECT series, (SELECT value FROM bbg_rate_daily x WHERE x.series = s.series ORDER BY date DESC LIMIT 1) FROM bbg_rate_series s WHERE series LIKE 'FX_EUR%'"):
        out[series[6:]] = value
    return out


def template(conn: sqlite3.Connection, lei: str, code: str) -> tuple[str | None, dict[str, float]]:
    ref = conn.execute("SELECT MAX(reference_date) FROM clean_fact WHERE entity_key = ? AND template_code = ? AND value IS NOT NULL", (lei, code)).fetchone()[0]
    if not ref:
        return None, {}
    rows = conn.execute("SELECT row_code, value FROM clean_fact WHERE entity_key = ? AND template_code = ? AND reference_date = ? AND value IS NOT NULL", (lei, code, ref)).fetchall()
    return ref, {r[0]: r[1] / 1e6 for r in rows}


def bonds_on(conn: sqlite3.Connection, lei: str, ref: str, fx: dict[str, float]) -> pd.DataFrame:
    b = pd.read_sql_query("SELECT security, payment_rank, basel_iii, maturity, issue_date, currency, amt_outstanding, perpetual, security_type, coupon_type, series FROM bbg_bond WHERE lei = ?", conn, params=(lei,))
    b["emtn"] = b.series.fillna("").str.upper().eq("EMTN")  # the spelling of the series differs: EMTN, Emtn, emtn
    b["eur_m"] = [(a or 0) / fx.get(c, float("nan")) / 1e6 for a, c in zip(b.amt_outstanding, b.currency)]
    b["perp"] = (b.perpetual == "Y") | b.maturity.isna()
    live = b[(b.eur_m > 0) & (b.issue_date <= ref) & (b.perp | (b.maturity > ref))].copy()
    live["resid_y"] = [99.0 if p else (pd.Timestamp(m) - pd.Timestamp(ref)).days / 365.25 for p, m in zip(live.perp, live.maturity)]
    return live


def report(conn: sqlite3.Connection, lei: str) -> None:
    name = conn.execute("SELECT MAX(entity_name) FROM entity WHERE lei = ?", (lei,)).fetchone()[0]
    fx = fx_table(conn)
    ref1, t1 = template(conn, lei, "K_91.00")
    ref2, k2 = template(conn, lei, "K_90.01")
    print(f"\n=== {name} ({lei})")
    if not t1:
        print("  no TLAC1 in P3DH: only KM2 can be compared at the level of the total")
    if k2:
        print(f"  KM2 {ref2}: own funds and eligible liabilities {k2.get('0010', 0):,.0f}m, of which own funds and subordinated liabilities {k2.get('0020', 0):,.0f}m, TREA {k2.get('0030', 0):,.0f}m")
    if not t1:
        return
    live = bonds_on(conn, lei, ref1, fx)
    ge1 = live[live.resid_y >= 1]
    s = lambda df: float(df.eur_m.sum())  # noqa: E731
    at1_b = s(ge1[ge1.basel_iii == "Additional Tier 1"])
    t2_b = s(live[live.basel_iii == "Tier 2"])
    snp_b = s(ge1[ge1.payment_rank == "Sr Non Preferred"])
    sp_b = s(ge1[ge1.payment_rank == "Sr Preferred"])
    su_b = s(ge1[ge1.payment_rank.isin(["Sr Unsecured", "Unsecured"])])
    sp_emtn = s(ge1[(ge1.payment_rank == "Sr Preferred") & ge1.emtn])
    g = lambda code: t1.get(code, 0.0)  # noqa: E731
    nonsub = g("0160") or g("0140") + g("0150")  # row 14, or rows 13 and EU-13a when a bank leaves row 14 empty
    rows = [
        ("AT1", g("0020"), at1_b, "TLAC1 row 2 / Basel III designation 'Additional Tier 1'"),
        ("Tier 2 incl. the amortised part counted as liability", g("0060") + g("0130"), t2_b, "TLAC1 rows 6 + EU-12c / designation 'Tier 2' (all residual maturities)"),
        ("Subordinated eligible liabilities (senior non-preferred)", g("0100") + g("0120"), snp_b, "TLAC1 rows 12 + EU-12b / rank 'Sr Non Preferred', at least 1 year"),
        ("Non-subordinated eligible liabilities, lower bound", nonsub, sp_b, "TLAC1 row 14 / rank 'Sr Preferred', at least 1 year"),
        ("Non-subordinated eligible liabilities, EMTN series", nonsub, sp_emtn, "TLAC1 row 14 / rank 'Sr Preferred' and series EMTN, at least 1 year"),
        ("Non-subordinated eligible liabilities, upper bound", nonsub, sp_b + su_b, "TLAC1 row 14 / 'Sr Preferred' + 'Sr Unsecured' + 'Unsecured', at least 1 year"),
    ]
    print(f"  TLAC1 {ref1} against the bonds outstanding on that date ({len(live)} bonds, {len(ge1)} with at least 1 year left)")
    print(f"  {'item':58s} {'P3DH':>9s} {'Bloomberg':>10s} {'difference':>11s} {'%':>7s}  basis")
    for item, p, bb, basis in rows:
        diff = bb - p
        print(f"  {item:58s} {p:9,.1f} {bb:10,.1f} {diff:11,.1f} {(diff / p * 100 if p else float('nan')):6.1f}%  {basis}")
    print(f"  check inside TLAC1: row 17a (subordinated items) {g('0200'):,.1f} = rows 12 + EU-12b + EU-12c {g('0100') + g('0120') + g('0130'):,.1f}; row 14 {g('0160'):,.1f} (rows 13 + EU-13a {g('0140') + g('0150'):,.1f})")
    other = ge1[ge1.payment_rank.isin(["Sr Unsecured", "Unsecured"])]
    if len(other):
        by = other.groupby("coupon_type", dropna=False).eur_m.agg(["count", "sum"]).round(0)
        print("  'Sr Unsecured' with at least 1 year left, by coupon type (count, EUR m):", {k: (int(v["count"]), float(v["sum"])) for k, v in by.to_dict("index").items()})
    ambiguous = conn.execute("SELECT COUNT(*) FROM bbg_bond_listing WHERE lei = ? AND status IN ('ambiguous', 'unresolved')", (lei,)).fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM bbg_bond_listing WHERE lei = ? AND security <> '' AND status IS NULL", (lei,)).fetchone()[0]
    print(f"  Bloomberg bonds not seen: {ambiguous} names that Bloomberg cannot resolve, {pending} not pulled yet")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--lei", nargs="*", default=[BIL])
    ap.add_argument("--db", default=os.environ.get("P3DH_DB", str(ROOT / "data" / "processed" / "p3dh.sqlite")))
    args = ap.parse_args()
    conn = sqlite3.connect(f"file:{Path(args.db).as_posix()}?mode=ro", uri=True)
    for lei in args.lei:
        report(conn, lei)
    return 0


if __name__ == "__main__":
    sys.exit(main())
