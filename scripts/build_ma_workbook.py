"""Build the M&A workbook (docs/M&A calc v2.xlsx) from the P3DH clean layer and the Bloomberg tables of the P3DH database.

  .venv/Scripts/python scripts/build_ma_workbook.py
  .venv/Scripts/python scripts/build_ma_workbook.py --targets "Banque Internationale" "Bank of Cyprus" "Hamburg Commercial"

The file keeps your sheet unchanged (sheet Original (user)) and adds Calc, Merger, P3DH, Market, Peers, Review, and Guide.
Every number in Calc is a formula. The workbook has Bloomberg values on the sheets Market and Peers. Do not publish it.
Refresh the Bloomberg tables first: scripts/pull_bloomberg.py.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dashboard"))
import ma_data  # noqa: E402
import ma_workbook as W  # noqa: E402

DEFAULT_TARGETS = ["9CZ7TVMR36CYD5TZBS50", "635400L14KNHZXPUZM19", "TUKDD90GPC79G1KOE162"]  # BIL, Bank of Cyprus, HCOB


def resolve(conn: sqlite3.Connection, text: str) -> str:
    if len(text) == 20 and text.isalnum() and text.upper() == text:
        return text
    rows = conn.execute("SELECT DISTINCT entity_key, entity_name FROM entity WHERE entity_name LIKE ?", (f"%{text}%",)).fetchall()
    if len(rows) != 1:
        raise SystemExit(f"'{text}' matches {len(rows)} banks: {[r[1] for r in rows][:6]}. Use a longer name or the LEI.")
    return rows[0][0]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", nargs=3, default=DEFAULT_TARGETS, help="Three target banks (name part or LEI)")
    ap.add_argument("--as-of", default="2026-06-30", help="Quarter of NBG; a target uses its newest quarter up to this date")
    ap.add_argument("--db", default=os.environ.get("P3DH_DB", str(ROOT / "data" / "processed" / "p3dh.sqlite")))
    ap.add_argument("--out", default=str(ROOT / "docs" / "M&A calc v2.xlsx"))
    args = ap.parse_args()

    conn = sqlite3.connect(f"file:{Path(args.db).as_posix()}?mode=ro", uri=True)

    def q(sql: str, params: tuple = ()) -> pd.DataFrame:
        return pd.read_sql_query(sql, conn, params=params)

    keys = [W.NBG_KEY] + [resolve(conn, t) for t in args.targets]
    banks = []
    for k in keys:
        periods = [p for p in ma_data.km1_periods(q, k) if p <= args.as_of]
        if not periods:
            raise SystemExit(f"No KM1 filing up to {args.as_of} for {k}")
        banks.append(ma_data.load_bank(q, k, periods[0]))
    market = W.load_market(q, banks)
    deals = [W.default_deal(b, sl["lei"]) for b, sl in zip(banks[1:], market["slots"][1:])]
    wb = W.build_workbook(banks, deals, W.default_globals(), market)
    out = Path(args.out)
    wb.save(out)
    print(f"Saved {out}")
    for b, sl in zip(banks, market["slots"]):
        print(f"  {b.name} ({b.country}), P3DH data of {b.as_of}; Bloomberg: {'found' if sl['found'] else 'NOT FOUND'}, market basis {sl['basis']}")
    print(f"  Bloomberg pulls: {market['stamp']}; peers in the fit: {len(market['peers']['rows'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
