"""Regression test of the clean layer: inject a unit error into new filings and measure what happens.

A new filing in a new unit is the main risk of the clean layer. This script tests it on a copy:

1. Copy the database (sqlite backup) to data/processed/injection_test.sqlite.
2. Choose banks that have the newest reference date and an older filing (so history exists).
3. Multiply every amount cell of the newest filing of those banks by a factor (default 0.001, a bank
   that files in thousand). KM1 ratio rows are not changed.
4. Run the clean steps on the copy: clean_p3dh, classify_p3dh, clean_templates, clean_engine.
5. Compare each injected cell with the value of the production clean layer:
   repaired (equals the production value), removed (fail closed), or SILENT (the injected unit stays).

The test fails (exit code 1) if more than 5% of the injected filings stay SILENT, or fewer than 80% are
repaired or removed. A bank whose older filings carry the same unit error cannot be repaired from history,
so a small silent share is normal. Run it before you trust a new version of the clean code and after each
change of the rules. It needs about 25 minutes and 4 GB of disk.

  PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/injection_test.py --factor 0.001 --banks 40
"""

from __future__ import annotations

import argparse
import sqlite3
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import clean_engine as ce  # noqa: E402

PROJECT_ROOT = SCRIPTS.parent
PROD = PROJECT_ROOT / "data" / "processed" / "p3dh.sqlite"
COPY = PROJECT_ROOT / "data" / "processed" / "injection_test.sqlite"
STEPS = ("clean_p3dh.py", "classify_p3dh.py", "clean_templates.py", "clean_engine.py")
KM1_AMOUNT_ROWS = {"0010", "0020", "0030", "0040", "0041", "0210", "0280", "0290", "0300", "0310", "0330", "0340"}
SILENT_LIMIT, HANDLED_MIN = 0.05, 0.80


def copy_database() -> None:
    for suffix in ("", "-wal", "-shm"):
        Path(str(COPY) + suffix).unlink(missing_ok=True)
    src = sqlite3.connect(f"file:{PROD.as_posix()}?mode=ro", uri=True)
    dst = sqlite3.connect(COPY)
    src.backup(dst, pages=20000)
    dst.close()
    src.close()


def inject(factor: float, n_banks: int, seed: int):
    conn = sqlite3.connect(COPY, timeout=600)
    new = conn.execute("SELECT MAX(reference_date) FROM filing").fetchone()[0]
    km = pd.read_sql_query(
        """SELECT DISTINCT e.entity_key FROM fact f JOIN entity e ON e.entity_id = f.entity_id
           WHERE f.template_code = 'K_61.00' AND f.reference_date = ? AND f.value IS NOT NULL""", conn, params=(new,))
    hist = {r[0] for r in conn.execute(
        """SELECT DISTINCT e.entity_key FROM fact f JOIN entity e ON e.entity_id = f.entity_id
           WHERE f.template_code = 'K_61.00' AND f.reference_date < ? AND f.value IS NOT NULL""", (new,))}
    km = km[km["entity_key"].isin(hist)]
    banks = sorted(km.sample(n=min(n_banks, len(km)), random_state=seed)["entity_key"])
    templates = [t for (t,) in conn.execute("SELECT DISTINCT template_code FROM fact WHERE reference_date = ? AND value IS NOT NULL", (new,))]
    n = 0
    for t in templates:
        df = pd.read_sql_query(ce.SQL, conn, params=(t,))
        df["kind"] = ce.assign_kind(df, t)
        if t == "K_61.00":
            is_amt = df["row_code"].isin(KM1_AMOUNT_ROWS)
        else:
            is_amt = df["kind"] == "amount"
        sel = df[(df["reference_date"] == new) & df["entity_key"].isin(banks) & is_amt & (df["value"] != 0)]
        if sel.empty:
            continue
        with conn:
            conn.executemany("UPDATE fact SET value = value * ? WHERE reference_date = ? AND template_code = ? AND entity_id = ? AND seq = ?",
                             [(factor, new, t, int(r.entity_id), int(r.seq)) for r in sel.itertuples()])
        n += len(sel)
    conn.close()
    return new, banks, n


def run_steps() -> None:
    for step in STEPS:
        print(f"== {step} on the copy", flush=True)
        code = subprocess.call([sys.executable, str(SCRIPTS / step), "--db", str(COPY)])
        if code:
            raise SystemExit(f"{step} failed with exit code {code}")


def classify(prod: pd.DataFrame, copy: pd.DataFrame, factor: float, keys: list) -> pd.DataFrame:
    c = prod.merge(copy, on=keys, how="left", suffixes=("_prod", "_inj"))
    vp, vi = c["value_prod"].to_numpy(float), c["value_inj"].to_numpy(float)
    c["outcome"] = np.select(
        [np.isnan(vi), np.abs(vi - vp) <= 1e-6 * np.abs(vp) + 1e-9, np.abs(vi - vp * factor) <= 1e-6 * np.abs(vp * factor) + 1e-9],
        ["removed", "repaired", "SILENT"], "other")
    return c


def evaluate(new: str, banks: list, factor: float) -> bool:
    prod = sqlite3.connect(f"file:{PROD.as_posix()}?mode=ro", uri=True)
    copy = sqlite3.connect(f"file:{COPY.as_posix()}?mode=ro", uri=True)
    ph = ",".join("?" * len(banks))
    q1 = (f"SELECT template_code, entity_key, seq, value FROM clean_fact WHERE reference_date = ? AND entity_key IN ({ph}) "
          "AND (unit_inferred = 'eur' OR unit_inferred LIKE 'x%' OR quality = 'quarantined')")
    a = pd.read_sql_query(q1, prod, params=[new] + banks)
    a = a[a["value"].notna()]
    b = pd.read_sql_query(q1, copy, params=[new] + banks)
    c1 = classify(a.rename(columns={"value": "value"}), b, factor, ["template_code", "entity_key", "seq"])
    q2 = (f"SELECT template_code, entity_key, row_code, measure_col, table_code, value FROM clean_period_fact WHERE period_end = ? "
          f"AND entity_key IN ({ph}) AND row_code IN ({','.join('?' * len(KM1_AMOUNT_ROWS))}) AND template_code = 'K_61.00' AND value IS NOT NULL")
    args = [new] + banks + sorted(KM1_AMOUNT_ROWS)
    pa = pd.read_sql_query(q2, prod, params=args)
    pb = pd.read_sql_query(q2, copy, params=args)
    c2 = classify(pa, pb, factor, ["template_code", "entity_key", "row_code", "measure_col", "table_code"])
    ok = True
    for label, c in (("generic engine, IRRBB, encumbrance", c1), ("KM1 amounts, column T", c2)):
        f = c.groupby(["template_code", "entity_key"])["outcome"].agg(lambda s: s.value_counts().index[0]).reset_index()
        share = f["outcome"].value_counts(normalize=True)
        silent, handled = share.get("SILENT", 0.0), share.get("repaired", 0.0) + share.get("removed", 0.0)
        print(f"\n{label}: {len(f)} injected filings")
        print(f["outcome"].value_counts().to_string())
        print(f"silent {silent:.1%} (limit {SILENT_LIMIT:.0%}), repaired or removed {handled:.1%} (minimum {HANDLED_MIN:.0%})")
        names = pd.read_sql_query("SELECT entity_key, MIN(entity_name) AS name FROM entity GROUP BY entity_key", prod).set_index("entity_key")["name"]
        for r in f[f["outcome"] == "SILENT"].head(10).itertuples():
            print(f"   silent: {r.template_code} {names.get(r.entity_key, r.entity_key)[:40]}")
        ok &= silent <= SILENT_LIMIT and handled >= HANDLED_MIN
    prod.close()
    copy.close()
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--factor", type=float, default=0.001)
    ap.add_argument("--banks", type=int, default=40)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--keep", action="store_true", help="Keep the copy after the test")
    args = ap.parse_args()
    print("copying the database ...", flush=True)
    copy_database()
    new, banks, n = inject(args.factor, args.banks, args.seed)
    print(f"injected factor {args.factor} into {n} cells of {len(banks)} banks at {new}", flush=True)
    run_steps()
    ok = evaluate(new, banks, args.factor)
    if not args.keep:
        for suffix in ("", "-wal", "-shm"):
            Path(str(COPY) + suffix).unlink(missing_ok=True)
    print("\nRESULT:", "passed" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
