"""Verify the clean layer after each refresh. Exit code 1 if a check fails.

The checks do not use the rules of the engine, so they are an independent test of its result.

1. Neighbouring filings. For each bank and template, the size in one filing must be close to the size
   in the next filing. A jump of 1,000 or more is a unit error. After cleaning no jump may remain, and
   cleaning must not create a jump that the raw data did not have.
2. Arithmetic. For amounts, value = value_raw x factor. Removed cells have no value. The quality
   values are known.
3. Known cases. Banks with a known unit error must keep the repair (see CASES). A new data load can
   add cases to this list. A case that fails shows a change in the rules or in the Hub data.
4. Identity. The same non-round raw figure in two templates of one filing has one unit. After cleaning
   no two such templates may have different factors. This test finds a wrong repair that moves all
   filings of a bank together, which test 1 cannot see.
5. Bound. A repaired filing may not hold a value above 3 times the total assets (or leverage exposure)
   of the bank.
6. Fixtures. The wrong decisions that the audit of 2026-10-13 found stay right (see FIXTURES).

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
QUALITIES = {"ok", "ok_wide", "ok_history", "ok_tie", "rescaled", "rescaled_tie", "rescaled_nb", "cell_reverted", "converted", "suspect",
             "unverified", "untested", "quarantined"}
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
    """Same cells in consecutive filings of one bank: no unit step in the median or in a fifth of the cells."""
    df = pd.read_sql_query(
        """SELECT template_code AS tpl, entity_key AS ent, reference_date AS ref, cell_code, key_descriptor, sheet,
                  value_raw AS raw, value AS clean FROM clean_fact
           WHERE (unit_inferred = 'eur' OR unit_inferred LIKE 'x%' OR quality = 'quarantined') AND ABS(value_raw) >= 10000""", conn)
    cell = ["cell_code", "key_descriptor", "sheet"]
    df["rank"] = df.groupby(["tpl", "ent"])["ref"].rank(method="dense").astype(int)
    prev = df.assign(rank=df["rank"] + 1)
    m = df.merge(prev, on=["tpl", "ent", "rank"] + cell, suffixes=("", "_p"))
    m["d_raw"] = np.abs(np.log10(m["raw"].abs() / m["raw_p"].abs()))
    both = m["clean"].notna() & m["clean_p"].notna() & (m["clean"] != 0) & (m["clean_p"] != 0)
    m["d_clean"] = np.where(both, np.abs(np.log10(np.abs(m["clean"]) / np.abs(m["clean_p"]).where(both, 1))), np.nan)
    m["j_raw"] = (m["d_raw"] >= JUMP).astype(float)
    m["j_clean"] = np.where(both, (m["d_clean"] >= JUMP).astype(float), np.nan)
    g = m.groupby(["tpl", "ent", "ref"])
    pairs = pd.DataFrame({"n": g["d_raw"].size(), "raw": g["d_raw"].median(), "raw_frac": g["j_raw"].mean(),
                          "clean": g["d_clean"].median(), "clean_frac": g["j_clean"].mean(), "n_clean": g["d_clean"].count()}).reset_index()
    pairs = pairs[pairs["n"] >= 3]
    jump_raw = (pairs["raw"] >= JUMP) | (pairs["raw_frac"] >= 0.2)
    remaining = pairs[(pairs["n_clean"] >= 3) & ((pairs["clean"] >= JUMP) | (pairs["clean_frac"] >= 0.2))]
    created = remaining[(remaining["raw"] < 1) & (remaining["raw_frac"] < 0.1)]
    msgs = [f"neighbouring filings: {len(pairs)} filing pairs with at least 3 shared cells, {int(jump_raw.sum())} unit-sized jumps "
            f"in the raw data, {len(remaining)} after cleaning, {len(created)} created by cleaning"]
    names = pd.read_sql_query("SELECT entity_key, MIN(entity_name) AS name FROM entity GROUP BY entity_key", conn).set_index("entity_key")["name"]
    for r in remaining.head(15).itertuples():
        msgs.append(f"  remaining jump: {r.tpl} {names.get(r.ent, r.ent)[:40]} {r.ref} (median {r.clean:.1f} decades, "
                    f"{r.clean_frac:.0%} of cells jump, raw {r.raw:.1f})")
    return remaining.empty, msgs


def check_arithmetic(conn) -> tuple[bool, list[str]]:
    bad_q = pd.read_sql_query("SELECT DISTINCT quality FROM clean_fact", conn)["quality"].tolist()
    unknown = sorted(set(bad_q) - QUALITIES)
    r = pd.read_sql_query(
        """SELECT
             SUM(quality = 'quarantined' AND value IS NOT NULL) AS removed_with_value,
             SUM(quality <> 'quarantined' AND value IS NULL) AS kept_without_value,
             SUM(quality IN ('ok','ok_wide','ok_history','ok_tie','rescaled','rescaled_tie','rescaled_nb','unverified') AND unit_inferred NOT IN ('', 'percent', 'fraction_of_t1', 'percent_of_t1')
                 AND ABS(value - value_raw * factor) > 1e-9 * ABS(value_raw * factor) + 1e-6) AS arithmetic_errors,
             COUNT(*) AS cells FROM clean_fact""", conn).iloc[0]
    ok = not unknown and r.removed_with_value == 0 and r.kept_without_value == 0 and r.arithmetic_errors == 0
    return ok, [f"arithmetic: {int(r.cells):,} cells, unknown quality {unknown or 'none'}, removed cells with a value {int(r.removed_with_value)}, "
                f"kept cells without a value {int(r.kept_without_value)}, value differs from raw x factor {int(r.arithmetic_errors)}"]


def live_factor(conn, tpl: str, name: str, ref: str):
    """Share of amount cells that are live, and their factor, for one filing of one template."""
    r = conn.execute(
        """SELECT SUM(c.quality <> 'quarantined'), COUNT(*), AVG(CASE WHEN c.quality <> 'quarantined' THEN c.factor END)
           FROM clean_fact c JOIN entity e ON e.entity_key = c.entity_key
           WHERE c.template_code = ? AND e.entity_name LIKE ? AND c.reference_date = ?
             AND (c.unit_inferred = 'eur' OR c.unit_inferred LIKE 'x%' OR c.quality = 'quarantined')""", (tpl, name, ref)).fetchone()
    if not r or not r[1]:
        return None
    return {"live": (r[0] or 0) / r[1], "factor": r[2]}


def is_one(d):
    return d is not None and d["factor"] is not None and abs(d["factor"] - 1.0) < 1e-9


def is_one_or_removed(d):
    return d is not None and (d["live"] == 0 or is_one(d))


FIXTURES = [
    ("APS Bank K_10.00 2026-06-30 is EUR (raw equals OV1 market risk)", "K_10.00", "APS BANK%", "2026-06-30", is_one),
    ("ING Belgium K_11.00 2025-12-31 is EUR (raw equals OV1 market risk)", "K_11.00", "ING Belg%", "2025-12-31", is_one),
    ("SFIL K_08.00 2025-12-31 is EUR", "K_08.00", "SFIL%", "2025-12-31", is_one),
    ("NLB K_03.00 2025-12-31 is EUR or removed (limit: one weak vote, no tie partner)", "K_03.00", "Nova Ljubljanska%", "2025-12-31", is_one_or_removed),
    ("Goldman Sachs Bank Europe K_22.01 is not scaled up", "K_22.01", "Goldman Sachs Bank Europe%", "2025-12-31", is_one_or_removed),
    ("Permanent TSB K_26.00 2025-12-31 is not scaled down", "K_26.00", "permanent tsb%", "2025-12-31", is_one_or_removed),
    ("de Volksbank K_84.01 2025-06-30 is not scaled up", "K_84.01", "de Volksbank%", "2025-06-30", is_one_or_removed),
    ("Piraeus K_67.02 2025-06-30 is not multiplied by 1,000", "K_67.02", "Piraeus%", "2025-06-30", is_one_or_removed),
    ("NBG K_09.03 2025-12-31 is kept (round millions, EUR)", "K_09.03", "National Bank of Greece%", "2025-12-31", is_one),
    ("NBG K_09.03 2026-06-30 is kept", "K_09.03", "National Bank of Greece%", "2026-06-30", is_one),
    ("Swedbank Hypotek K_21.01 2025-12-31 is kept in EUR", "K_21.01", "Swedbank Hypotek%", "2025-12-31", is_one),
    ("Nordea Eiendomskreditt K_21.01 2026-06-30 is kept in EUR", "K_21.01", "Nordea Eiendomskreditt%", "2026-06-30", is_one),
    ("Bank of Montreal Europe 2025-10-31 keeps its amounts (off-quarter date)", "K_21.01", "Bank of Montreal Europe%", "2025-10-31",
     lambda d: d is None or d["live"] > 0.5),
    ("Scotiabank (Ireland) 2025-10-31 keeps its amounts", "K_21.01", "Scotiabank (Ireland)%", "2025-10-31", lambda d: d is None or d["live"] > 0.5),
    ("UBB 2025-12-31 K_66.01 is converted from BGN thousand with the peg 511.29", "K_66.01", "United Bulgarian Bank%", "2025-12-31",
     lambda d: d is not None and d["factor"] is not None and abs(d["factor"] - 511.29) < 1.0),
]


def check_fixtures(conn) -> tuple[bool, list[str]]:
    ok, msgs = True, []
    for label, tpl, name, ref, test in FIXTURES:
        d = live_factor(conn, tpl, name, ref)
        passed = bool(test(d))
        ok &= passed
        msgs.append(f"  {'ok  ' if passed else 'FAIL'} {label}" + ("" if passed else f" (got {d})"))
    return ok, ["fixtures from the audit:"] + msgs


def check_identity(conn) -> tuple[bool, list[str]]:
    """The same non-round figure in two templates of one filing has one unit factor."""
    cf = pd.read_sql_query(
        """SELECT template_code AS tpl, entity_key, reference_date, value_raw, factor FROM clean_fact
           WHERE (unit_inferred = 'eur' OR unit_inferred LIKE 'x%') AND quality <> 'quarantined' AND ABS(value_raw) >= 100000""", conn)
    cp = pd.read_sql_query(
        """SELECT template_code AS tpl, entity_key, reference_date, value_raw, value / value_raw AS factor FROM clean_period_fact
           WHERE period_offset = 0 AND measure_col IN (10, 30) AND ABS(value_raw) >= 100000 AND value_raw <> 0""", conn)
    cp = cp[cp["tpl"].isin(["K_61.00", "K_60.00"])]
    allc = pd.concat([cf, cp], ignore_index=True)
    cents = (allc["value_raw"].abs() * 100).round()
    allc = allc[(cents % 100000) != 0].assign(v=cents.astype("int64"))
    allc["lf"] = np.log10(allc["factor"].astype(float)).round(3)
    k = ["entity_key", "reference_date", "v"]
    allc = allc.drop_duplicates(k + ["tpl", "lf"])
    allc = allc[allc.groupby(k)["tpl"].transform("nunique") >= 2]
    m = allc.merge(allc, on=k, suffixes=("_a", "_b"))
    m = m[(m["tpl_a"] < m["tpl_b"]) & ((m["lf_a"] - m["lf_b"]).abs() > 0.01)]
    pairs = m.groupby(["entity_key", "reference_date", "tpl_a", "tpl_b"]).size().rename("n").reset_index()
    pairs = pairs[pairs["n"] >= 2]
    msgs = [f"identity: {len(pairs)} template pairs share at least 2 figures and have different factors"]
    names = pd.read_sql_query("SELECT entity_key, MIN(entity_name) AS name FROM entity GROUP BY entity_key", conn).set_index("entity_key")["name"]
    for r in pairs.head(12).itertuples():
        msgs.append(f"  {names.get(r.entity_key, r.entity_key)[:40]} {r.reference_date} {r.tpl_a} vs {r.tpl_b}: {r.n} figures")
    return pairs.empty, msgs


def check_bounds(conn) -> tuple[bool, list[str]]:
    r = pd.read_sql_query(
        """SELECT c.template_code, c.entity_key, c.reference_date, MAX(ABS(c.value)) AS mx, a.size_basis_eur AS ta
           FROM clean_fact c JOIN entity_assets a ON a.entity_key = c.entity_key AND a.period_end = c.reference_date
           WHERE c.quality IN ('rescaled', 'rescaled_tie', 'rescaled_nb') AND a.size_basis_eur > 0
             AND c.template_code NOT IN ('K_41.00') GROUP BY 1, 2, 3""", conn)
    bad = r[r["mx"] > 3 * r["ta"]]
    msgs = [f"bounds: {len(r)} repaired filings with a known size, {len(bad)} above 3 times total assets"]
    for x in bad.head(10).itertuples():
        msgs.append(f"  {x.template_code} {x.entity_key} {x.reference_date}: {x.mx:.3g} against {x.ta:.3g}")
    return bad.empty, msgs


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
    for name, fn in (("neighbours", check_neighbours), ("arithmetic", check_arithmetic), ("cases", check_cases),
                     ("identity", check_identity), ("bounds", check_bounds), ("fixtures", check_fixtures)):
        ok, msgs = fn(conn)
        failed |= not ok
        print(f"[{'pass' if ok else 'FAIL'}] {name}")
        for m in msgs:
            print("   ", m)
    print("\nRESULT:", "FAILED" if failed else "all clean-layer checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
