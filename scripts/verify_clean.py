"""Verify the clean layer after each refresh. Exit code 1 if a check fails.

The checks do not use the rules of the engine, so they are an independent test of its result.

1. Neighbouring filings. For each bank and template, the size in one filing must be close to the size
   in the next filing. A jump of 1,000 or more is a unit error. After cleaning no jump may remain, and
   cleaning must not create a jump that the raw data did not have.
2. Arithmetic. For amounts, value = value_raw x factor. Removed cells have no value. The quality
   values are known.
3. Known cases. Banks with a known unit error must keep the repair (see CASES). A new data load can
   add cases to this list. A case that fails shows a change in the rules or in the Hub data.

New data makes check 1 stronger: each new filing adds pairs. A new unit pattern that the engine does
not handle shows as a remaining jump or as a removed filing in the drift report.

Run: PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/verify_clean.py
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "processed" / "p3dh.sqlite"
QUALITIES = {"ok", "ok_wide", "ok_history", "rescaled", "converted", "suspect", "unverified", "untested", "quarantined"}
JUMP = 2.5

# (label, query, check). The query returns one number. check gets that number.
SG, CITI, BNP, EUROB, PIR, NBG = ("O2RNE8IBXP4R0TD8PU41", "N1FBEDJ5J41VKZLO2475", "R0MUWSFPU8MPRO8K5P83",
                                  "213800KGF4EFNUQKAT69", "213800OYHR1MPQ5VJL60", "5UMCZOEYKCVFAW8ZLO05")
CASES = [
    ("SocGen IRRBB 2025-06-30 is in thousand, repaired to EUR (-2.8bn)",
     f"SELECT value FROM clean_fact WHERE template_code='K_68.00' AND entity_key='{SG}' AND reference_date='2025-06-30' AND row_code='0010' AND column_code='0010'",
     lambda v: abs(v - (-2.817e9)) / 2.817e9 < 0.01),
    ("Citibank Europe IRRBB 2025-06-30 is 1,000 times too large, repaired (-122m)",
     f"SELECT value FROM clean_fact WHERE template_code='K_68.00' AND entity_key='{CITI}' AND reference_date='2025-06-30' AND row_code='0010' AND column_code='0010'",
     lambda v: abs(v - (-1.2199e8)) / 1.2199e8 < 0.01),
    ("BNP IRRBB 2025-12-31 is a fraction of Tier 1, converted to EUR (about -8.0bn)",
     f"SELECT value FROM clean_fact WHERE template_code='K_68.00' AND entity_key='{BNP}' AND reference_date='2025-12-31' AND row_code='0010' AND column_code='0010'",
     lambda v: -9e9 < v < -7e9),
    ("Eurobank KM1 leverage exposure 2025-09-30 is in EUR (108.3bn)",
     f"SELECT value FROM clean_period_fact WHERE template_code='K_61.00' AND entity_key='{EUROB}' AND period_end='2025-09-30' AND row_code='0210' AND measure_col=10",
     lambda v: abs(v - 1.082953e11) / 1.082953e11 < 0.001),
    ("Piraeus total assets 2025-12-31 equal Bloomberg (90,893m)",
     f"SELECT total_assets_eur FROM entity_assets WHERE entity_key='{PIR}' AND period_end='2025-12-31'",
     lambda v: abs(v - 90893e6) / 90893e6 < 0.001),
    ("NBG total assets 2025-12-31 equal Bloomberg (78,886m)",
     f"SELECT total_assets_eur FROM entity_assets WHERE entity_key='{NBG}' AND period_end='2025-12-31'",
     lambda v: abs(v - 78886e6) / 78886e6 < 0.001),
    ("NBG CET1 ratio 2026-06-30 is 16.97% (a fraction)",
     f"SELECT value FROM clean_period_fact WHERE template_code='K_61.00' AND entity_key='{NBG}' AND period_end='2026-06-30' AND row_code='0050' AND measure_col=10",
     lambda v: abs(v - 0.1697) < 0.0005),
]


def check_neighbours(conn) -> tuple[bool, list[str]]:
    df = pd.read_sql_query(
        """SELECT template_code, entity_key, reference_date, value_raw, value, quality FROM clean_fact
           WHERE unit_inferred <> '' AND unit_inferred <> 'percent' AND value_raw <> 0""", conn)
    keys = ["template_code", "entity_key", "reference_date"]
    raw = df.assign(a=df["value_raw"].abs()).groupby(keys)["a"].quantile(0.9)
    clean = df[df["quality"] != "quarantined"].assign(a=lambda t: t["value"].abs()).groupby(keys)["a"].quantile(0.9)
    t = pd.DataFrame({"raw": raw, "clean": clean}).reset_index().sort_values(["template_code", "entity_key", "reference_date"])
    g = t.groupby(["template_code", "entity_key"])
    t["d_raw"] = np.abs(np.log10(t["raw"] / g["raw"].shift(1)))
    t["d_clean"] = np.abs(np.log10(t["clean"] / g["clean"].shift(1)))
    p = t.dropna(subset=["d_raw"])
    both = p.dropna(subset=["d_clean"])
    remaining = both[both["d_clean"] >= JUMP]
    created = both[(both["d_raw"] < 1) & (both["d_clean"] >= JUMP)]
    msgs = [f"neighbouring filings: {len(p)} pairs, {int((p.d_raw >= JUMP).sum())} unit-sized jumps in the raw data, "
            f"{len(remaining)} after cleaning, {len(created)} created by cleaning"]
    for r in remaining.head(15).itertuples():
        msgs.append(f"  remaining jump: {r.template_code} {r.entity_key} {r.reference_date}")
    return remaining.empty and created.empty, msgs


def check_arithmetic(conn) -> tuple[bool, list[str]]:
    bad_q = pd.read_sql_query("SELECT DISTINCT quality FROM clean_fact", conn)["quality"].tolist()
    unknown = sorted(set(bad_q) - QUALITIES)
    r = pd.read_sql_query(
        """SELECT
             SUM(quality = 'quarantined' AND value IS NOT NULL) AS removed_with_value,
             SUM(quality <> 'quarantined' AND value IS NULL) AS kept_without_value,
             SUM(quality IN ('ok','ok_wide','ok_history','rescaled','unverified') AND unit_inferred NOT IN ('', 'percent', 'fraction_of_t1', 'percent_of_t1')
                 AND ABS(value - value_raw * factor) > 1e-9 * ABS(value_raw * factor) + 1e-6) AS arithmetic_errors,
             COUNT(*) AS cells FROM clean_fact""", conn).iloc[0]
    ok = not unknown and r.removed_with_value == 0 and r.kept_without_value == 0 and r.arithmetic_errors == 0
    return ok, [f"arithmetic: {int(r.cells):,} cells, unknown quality {unknown or 'none'}, removed cells with a value {int(r.removed_with_value)}, "
                f"kept cells without a value {int(r.kept_without_value)}, value differs from raw x factor {int(r.arithmetic_errors)}"]


def check_cases(conn) -> tuple[bool, list[str]]:
    ok, msgs = True, []
    for label, sql, test in CASES:
        row = conn.execute(sql).fetchone()
        passed = row is not None and row[0] is not None and bool(test(row[0]))
        ok &= passed
        msgs.append(f"  {'ok  ' if passed else 'FAIL'} {label}" + ("" if passed else f" (got {row[0] if row else 'no row'})"))
    return ok, ["known cases:"] + msgs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = ap.parse_args()
    conn = sqlite3.connect(f"file:{args.db.as_posix()}?mode=ro", uri=True)
    failed = False
    for name, fn in (("neighbours", check_neighbours), ("arithmetic", check_arithmetic), ("cases", check_cases)):
        ok, msgs = fn(conn)
        failed |= not ok
        print(f"[{'pass' if ok else 'FAIL'}] {name}")
        for m in msgs:
            print("   ", m)
    print("\nRESULT:", "FAILED" if failed else "all clean-layer checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
