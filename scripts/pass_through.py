"""Pass-through of the market rate (3-month Euribor) to the rates of banks, by country, product, and rate cycle. The result is the table ext_passthrough.

  python scripts/pass_through.py                          compute for every country, store, and print the euro area
  python scripts/pass_through.py --country LU,GR          betas of countries (all products, all cycles)
  python scripts/pass_through.py --group Benelux          betas of a geographic group, weighted by the stocks at the start of the cycle
  python scripts/pass_through.py --product deposits       only the products whose name starts with this text
  python scripts/pass_through.py --xlsx betas.xlsx        write the table to Excel
Beta = (change of the bank rate) / (change of the 3-month Euribor) from the start to the end of a rate cycle (see modules/ext/analytics.py).
Run scripts/pull_ext.py bulk first (the history of the bank rates) and scripts/pull_ext.py all --only euribor_3m --since 1999.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.ext import analytics  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.environ.get("P3DH_DB", str(ROOT / "data" / "processed" / "p3dh.sqlite")))
    ap.add_argument("--country", default="", help="comma list of ISO codes (U2 = euro area)")
    ap.add_argument("--group", default="", help="a geographic group of ext_geo_group")
    ap.add_argument("--product", default="", help="start of the product name")
    ap.add_argument("--no-store", action="store_true", help="do not write the table ext_passthrough")
    ap.add_argument("--xlsx", default=None)
    args = ap.parse_args()
    conn = sqlite3.connect(args.db, timeout=600)
    df = analytics.pass_through(conn, store=not args.no_store)
    if args.product:
        df = df[df["product"].str.startswith(args.product)]
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    pd.set_option("display.max_rows", 500)
    print(f"{len(df)} betas: {df.country.nunique()} countries, {df['product'].nunique()} products, {df.cycle.nunique()} cycles")
    cycles = list(analytics.CYCLES)
    countries = [c for c in args.country.split(",") if c] or ([] if args.group else ["U2"])
    for c in countries:
        print(f"\n{c}: beta by product and cycle")
        print(df[df.country == c].pivot(index="product", columns="cycle", values="beta").reindex(columns=cycles).round(2).to_string())
    if args.group:
        gb = analytics.group_betas(conn, df, args.group)
        print(f"\n{args.group}: beta by product and cycle (n = countries; wmean = mean weighted by the stock at the start of the cycle)")
        print(gb.sort_values(["product", "cycle"]).round(2).to_string(index=False))
    if args.xlsx:
        df.to_excel(args.xlsx, sheet_name="betas", index=False)
        print(f"\nwritten: {args.xlsx}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
