"""Benchmark of a bank against its country, the euro area, the EU, and geographic groups (ECB statistics in the database).

  python scripts/benchmark_bank.py --lei 9CZ7TVMR36CYD5TZBS50
  python scripts/benchmark_bank.py --lei <LEI> --country LU --groups Benelux,DACH --since 2024
  python scripts/benchmark_bank.py --lei <LEI> --xlsx "benchmark.xlsx"
The bank figures come from P3DH (and Bloomberg for the return ratios). Run scripts/pull_ext.py bulk first. An Excel file can hold Bloomberg data: keep it out of the repository.
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

from modules.ext import benchmark  # noqa: E402

ORDER = ["bank", "country", "euro_area", "eu_median"]


def show(df: pd.DataFrame, title: str, first: list[str], digits: int = 2) -> None:
    print(f"\n{title}")
    if df.empty:
        print("  no data")
        return
    cols = [c for c in df.columns if c not in first]
    print(df[first + cols].round(digits).to_string(index=False))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--lei", required=True, help="entity key of the bank (the LEI)")
    ap.add_argument("--db", default=os.environ.get("P3DH_DB", str(ROOT / "data" / "processed" / "p3dh.sqlite")))
    ap.add_argument("--country", default=None, help="ISO code; default: from Bloomberg or the P3DH classification")
    ap.add_argument("--groups", default=None, help="comma list of geographic groups; default: the groups of the country")
    ap.add_argument("--since", type=int, default=None, help="first year of the bank figures to show")
    ap.add_argument("--xlsx", default=None, help="write the tables to this Excel file")
    args = ap.parse_args()
    conn = sqlite3.connect(f"file:{Path(args.db).as_posix()}?mode=ro", uri=True, timeout=300)
    groups = [g for g in args.groups.split(",") if g] if args.groups else None
    r = benchmark.report(conn, args.lei, args.country, groups)
    ratios = r["ratios"]
    if args.since and not ratios.empty:
        ratios = ratios[ratios["period"].str[:4].astype(int) >= args.since]
    print(f"{r['bank']} ({args.lei}), country {r['country']}; groups: {', '.join(r['groups']) or 'none'}")
    print("Figures in percent. 'eu_rank' = share of the EU countries with a lower figure than the bank. Groups and EU: median of the countries.")
    for name, (year, value) in r["context"].items():
        print(f"  context {r['country']} {year}: {name}: {value:.1f}")
    print("  The country figure is for the domestic banks of the country. The bank is part of it. When the domestic banks are few or small in the sector, the figure says little.")
    if not ratios.empty:
        for label, g in ratios.groupby("label", sort=False):
            show(g.drop(columns=["metric", "label"]), label, ["period", *ORDER])
    mix_cols = ["period", "counterparty", "bank", "country", "euro area"]
    note = "(share of the loans; the ECB figures are the loans of all monetary financial institutions of the country to residents of the euro area)"
    show(r["loan_mix"], f"Loans by counterparty {note}", mix_cols)
    show(r["loan_mix_non_bank"], f"Loans by counterparty, without loans to credit institutions and central banks {note}", mix_cols)
    if not r["loan_growth"].empty:
        for measure, g in r["loan_growth"].groupby("measure", sort=False):
            show(g.drop(columns=["measure"]), f"Growth of the {measure}, year on year (the ECB figures are loan stocks of the banks of the country: not adjusted for reclassifications)", ["period", *ORDER])
    ir = r["irrbb"]
    if ir:
        print(f"\nChange of net interest income, as a percent of net interest income (P3DH: bank at {ir['date']}, peers from {ir['first_date']}; {ir['n_banks']} banks with net interest income of EUR 50m or more)")
        rows = [{"": "bank", "+200bp": ir["bank"]["up"], "-200bp": ir["bank"]["down"]}] + [{"": f"{k} (median, {v['n']} bank{'s' if v['n'] != 1 else ''})", "+200bp": v["up"], "-200bp": v["down"]} for k, v in ir.items() if isinstance(v, dict) and "n" in v]
        print(pd.DataFrame(rows).round(1).to_string(index=False))
        print(f"the figure of the bank is higher than that of {ir['above']['up']:.0f}% of the banks for +200bp and {ir['above']['down']:.0f}% for -200bp")
    if args.xlsx:
        with pd.ExcelWriter(args.xlsx) as xl:
            ratios.to_excel(xl, "ratios", index=False)
            r["loan_mix"].to_excel(xl, "loan mix", index=False)
            r["loan_mix_non_bank"].to_excel(xl, "loan mix non-bank", index=False)
            r["loan_growth"].to_excel(xl, "loan growth", index=False)
            if ir:
                pd.DataFrame(rows).to_excel(xl, "irrbb", index=False)
        print(f"\nwritten: {args.xlsx}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
