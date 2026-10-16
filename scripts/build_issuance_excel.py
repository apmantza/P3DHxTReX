"""Build the issuance workbook of NBG and BIL (docs/Issuance NBG and BIL.xlsx) from the Bloomberg tables of the P3DH database.

  dashboard/.venv/Scripts/python scripts/build_issuance_excel.py
  dashboard/.venv/Scripts/python scripts/build_issuance_excel.py --banks NBG=5UMCZOEYKCVFAW8ZLO05 BIL=9CZ7TVMR36CYD5TZBS50 BoC=635400L14KNHZXPUZM19

The file has the liability profile by debt type for each issuer and combined, one row for each bond, and the live names that have no data yet.
It holds Bloomberg data. Do not publish it. To refresh the bond data first: scripts/pull_bloomberg.py bonds (see docs/bloomberg_db.md).
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from modules.bbg import issuance, issuance_xlsx  # noqa: E402

DEFAULT_BANKS = ["NBG=5UMCZOEYKCVFAW8ZLO05", "BIL=9CZ7TVMR36CYD5TZBS50"]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--banks", nargs="+", default=DEFAULT_BANKS, help="SHORT=LEI for each issuer")
    ap.add_argument("--db", default=os.environ.get("P3DH_DB", str(ROOT / "data" / "processed" / "p3dh.sqlite")))
    ap.add_argument("--out", default=str(ROOT / "docs" / "Issuance NBG and BIL.xlsx"))
    args = ap.parse_args()
    banks = [tuple(b.split("=", 1)) for b in args.banks]
    conn = sqlite3.connect(f"file:{Path(args.db).as_posix()}?mode=ro", uri=True)
    data = issuance.load(conn, banks)
    bridge = issuance.load_bridge(conn, banks)
    issuance_xlsx.write_workbook(args.out, data, bridge)
    iss, un = data["issues"], data["unresolved"]
    print(f"Saved {args.out}")
    for s, _ in banks:
        a = iss[(iss["issuer"] == s) & (iss["active"] == "Y")]
        print(f"  {s}: {len(a)} active bonds, EUR {a['eur'].sum():,.0f}m; {int((iss['issuer'] == s).sum()) - len(a)} not active; {int((un['issuer'] == s).sum())} listed names without data")
    for s, b in bridge.items():
        print(f"  Bridge {s}: " + (f"P3DH CC2 and TLAC1 of {b['date']}" if b else "no CC2 liability lines with TLAC1 in P3DH"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
