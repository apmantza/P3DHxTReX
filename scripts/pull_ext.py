"""Pull external statistics by country (ECB Data Portal, Eurostat) into the P3DH database.

  python scripts/pull_ext.py all                   every indicator
  python scripts/pull_ext.py ecb                   the indicators of the ECB
  python scripts/pull_ext.py eurostat
  python scripts/pull_ext.py all --only mir,bsi    chosen indicators: a name, the start of a name, a group (rates, volumes, survey, profitability, ...), or a source
  python scripts/pull_ext.py all --since 2015      first year (default 2010)
  python scripts/pull_ext.py bulk                  every series of the ECB datasets MIR, BSI, BLS, CBD2, SUP, SSI, RAI, IRS, RESR, RESH, CLIFS, CISS with the full history (from 1999)
  python scripts/pull_ext.py bulk --flows MIR,BSI --areas LU,DE --since 2010
  python scripts/pull_ext.py eba                   EBA Transparency Exercise (bank by bank, with a P&L; last data 30 Jun 2025): downloads 4 files (about 230 MB) and loads them
  python scripts/pull_ext.py eba --flows oth,sov   chosen files of the exercise (oth, sov, mrk, cre)
  python scripts/pull_ext.py status                what the database holds, for each dataflow
  python scripts/pull_ext.py status --only x       the same, with a line for each curated indicator
The data is public. It needs no terminal and no key. The run takes a few minutes.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.ext import bulk, eba_te, pull, schema  # noqa: E402
from modules.ext.specs import BY_INDICATOR, SPECS  # noqa: E402


def status(conn: sqlite3.Connection, detail: bool = False) -> None:
    print(f"{'dataflow':10s} {'source':9s} {'countries':>9s} {'series':>8s} {'obs':>10s}  {'first':10s}  {'last':10s}")
    for flow, src, n_c, n_s, n_o, first, last in conn.execute("""SELECT COALESCE(flow, ''), source, COUNT(DISTINCT ref_area), COUNT(*), COALESCE(SUM(n_obs), 0), MIN(first_period), MAX(last_period)
                                                                 FROM ext_series GROUP BY flow, source ORDER BY source, flow"""):
        print(f"{flow:10s} {src:9s} {n_c:>9d} {n_s:>8,d} {n_o:>10,d}  {first or '':10s}  {last or '':10s}")
    if detail:
        print(f"\n{'indicator':20s} {'freq':4s} {'countries':>9s} {'series':>7s} {'obs':>9s}  {'first':10s}  {'last':10s}")
        for ind, freq, n_c, n_s, n_o, first, last in conn.execute("""SELECT indicator, freq, COUNT(DISTINCT ref_area), COUNT(*), COALESCE(SUM(n_obs), 0), MIN(first_period), MAX(last_period)
                                                                     FROM ext_series WHERE indicator IN (%s) GROUP BY indicator, freq ORDER BY indicator""" % ",".join("?" * len(BY_INDICATOR)), list(BY_INDICATOR)):
            print(f"{ind:20s} {freq:4s} {n_c:>9d} {n_s:>7d} {n_o:>9,d}  {first or '':10s}  {last or '':10s}")
    for f in eba_te.FILES:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (f"te_{f}",)).fetchone():
            n, banks, last = conn.execute(f"SELECT COUNT(*), COUNT(DISTINCT lei), MAX(period_end) FROM te_{f}").fetchone()
            print(f"{'te_' + f:10s} {'eba':9s} {banks:>6d} banks {n:>10,d} rows  last {last}")
    n_geo = conn.execute("SELECT COUNT(DISTINCT group_name) FROM ext_geo_group").fetchone()[0]
    print(f"\n{len(SPECS)} curated indicators are defined. {n_geo} geographic groups are stored.")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["all", "ecb", "eurostat", "bulk", "eba", "status"])
    ap.add_argument("--db", default=os.environ.get("P3DH_DB", str(ROOT / "data" / "processed" / "p3dh.sqlite")))
    ap.add_argument("--only", default="", help="comma list")
    ap.add_argument("--since", type=int, default=None, help="first year (curated: 2010; bulk: 1999)")
    ap.add_argument("--flows", default="", help="bulk: comma list of dataflows (default all)")
    ap.add_argument("--areas", default="", help="bulk: comma list of countries (default all)")
    args = ap.parse_args()
    conn = sqlite3.connect(args.db, timeout=600)
    conn.execute("PRAGMA journal_mode=WAL")
    schema.create(conn)
    pull.seed_countries(conn)
    conn.commit()
    if args.what == "status":
        status(conn, detail=bool(args.only))
        return 0
    if args.what == "eba":
        eba_te.load(conn, files=tuple(f for f in args.flows.split(",") if f) or tuple(eba_te.FILES))
        return 0
    if args.what == "bulk":
        flows = [f for f in args.flows.split(",") if f] or list(bulk.BULK)
        areas = [a for a in args.areas.split(",") if a] or None
        failed = {}
        for flow in flows:
            try:
                r = bulk.pull_flow(conn, flow, since=args.since or 1999, areas=areas)
            except Exception as e:  # noqa: BLE001 - one flow must not stop the others
                failed[flow] = f"{type(e).__name__}: {e}"[:200]
                continue
            print(f"{flow}: {r['series']:,d} series stored (catalogue {r['catalogue']:,d}), {r['observations']:,d} observations")
            failed.update({f"{flow} {a}": m for a, m in r["failed"].items()})
        for k, v in failed.items():
            print(f"  failed: {k}: {v}")
        return 1 if failed else 0
    only = [o for o in args.only.split(",") if o] or ([args.what] if args.what != "all" else None)
    result = pull.pull(conn, only=only, since=args.since or 2010)
    print(f"{len(result['ok'])} indicators ok, {len(result['failed'])} failed")
    for k, v in result["failed"].items():
        print(f"  failed: {k}: {v}")
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
