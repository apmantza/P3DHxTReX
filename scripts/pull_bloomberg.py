"""Pull Bloomberg data into the P3DH database (tables bbg_*). Run with the Python of the blauto project (it has blpapi).

  C:\\Users\\E40889\\Documents\\blauto\\.venv\\Scripts\\python scripts\\pull_bloomberg.py rates        # history of rates, curves, FX, indices
  ...  scripts\\pull_bloomberg.py averages     # averages per month, quarter, half, year, YTD, LTM (needs no Bloomberg)
  ...  scripts\\pull_bloomberg.py expected     # expected deposit rate from the OIS curve (needs no Bloomberg)
  ...  scripts\\pull_bloomberg.py basis        # market basis of each entity and fiscal year of the consensus (needs no Bloomberg)
  ...  scripts\\pull_bloomberg.py tickers      # ticker map of every bank: equity, parent, bonds (needs no Bloomberg)
  ...  scripts\\pull_bloomberg.py entities     # every P3DH entity by LEI: name, parent, tax, ratings, fundamentals, debt
  ...  scripts\\pull_bloomberg.py equity       # prices, valuation, fundamentals, consensus of the listed banks
  ...  scripts\\pull_bloomberg.py ownership    # 20 largest holders and holder types of the listed banks (state participation)
  ...  scripts\\pull_bloomberg.py bonds        # outstanding bonds: list them, then static and market data (--all: every bank; --census-only: list only)
  ...  scripts\\pull_bloomberg.py bondhist     # daily price, yields, spreads of the quoted outstanding bonds (--start, default 20240101)
  ...  scripts\\pull_bloomberg.py bondmarket   # price, yields, and spreads of the outstanding bonds that are in the database
  ...  scripts\\pull_bloomberg.py status       # what is in the tables

The client counts the unique securities of each month (--budget). The data stays in data/processed (not in git).
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.bbg import schema  # noqa: E402


def status(conn: sqlite3.Connection) -> None:
    q = lambda sql: conn.execute(sql).fetchall()  # noqa: E731
    print("rate series:", q("SELECT COUNT(*) FROM bbg_rate_series")[0][0], "| daily rows:", q("SELECT COUNT(*) FROM bbg_rate_daily")[0][0],
          "| average rows:", q("SELECT COUNT(*) FROM bbg_rate_average")[0][0], "| expected rows:", q("SELECT COUNT(*) FROM bbg_expected_dfr")[0][0])
    print("entities:", q("SELECT COUNT(*), SUM(found) FROM bbg_entity")[0], "| equity tickers with snapshot:", q("SELECT COUNT(DISTINCT ticker) FROM bbg_equity_snapshot")[0][0],
          "| equity daily rows:", q("SELECT COUNT(*) FROM bbg_equity_daily")[0][0], "| fundamentals:", q("SELECT COUNT(*) FROM bbg_fundamental")[0][0],
          "| consensus:", q("SELECT COUNT(*) FROM bbg_consensus")[0][0])
    print("bond listings:", q("SELECT COUNT(*) FROM bbg_bond_listing")[0][0], "| bonds with static data:", q("SELECT COUNT(*) FROM bbg_bond")[0][0],
          "| listing status:", dict(q("SELECT COALESCE(status, 'not requested'), COUNT(*) FROM bbg_bond_listing WHERE security <> '' GROUP BY 1")))
    print("market basis of the entities:", dict(q("SELECT COALESCE(market_basis, 'not set'), COUNT(*) FROM bbg_entity WHERE found = 1 GROUP BY 1")))
    print("unique securities used this month:", q("SELECT COUNT(*) FROM bbg_security_use WHERE month = strftime('%Y-%m', 'now')")[0][0])
    for r in q("SELECT started_at, kind, detail, n_rows, status FROM bbg_pull_log ORDER BY pull_id DESC LIMIT 8"):
        print("  log:", r)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["rates", "averages", "expected", "basis", "tickers", "entities", "equity", "ownership", "bonds", "bondmarket", "bondhist", "status"])
    ap.add_argument("--db", default=os.environ.get("P3DH_DB", str(ROOT / "data" / "processed" / "p3dh.sqlite")))
    ap.add_argument("--budget", type=int, default=4500, help="unique securities per month that this project may request")
    ap.add_argument("--start", default=None, help="first date of the history (YYYYMMDD). Default: 1999 for rates, 2005 for equity")
    ap.add_argument("--full", action="store_true", help="pull the whole history again")
    ap.add_argument("--limit", type=int, default=0, help="only the first N entities, tickers, or issuers (test runs)")
    ap.add_argument("--max-bonds", type=int, default=100000, help="most bonds that get static data in one run")
    ap.add_argument("--leis", nargs="*", default=None, help="banks for the bond pull (LEI). Default: NBG, BIL, Bank of Cyprus, HCOB, and the other Greek banks")
    ap.add_argument("--all", action="store_true", help="bonds: every bank with debt, not only the default banks")
    ap.add_argument("--census-only", action="store_true", help="bonds: only list the live bonds (needs no unique security)")
    ap.add_argument("--relist", action="store_true", help="bonds: list the banks again to find new issues (a bond keeps its status)")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db, timeout=600)
    conn.execute("PRAGMA journal_mode=WAL")
    schema.create(conn)
    if args.what == "status":
        status(conn)
        return 0
    if args.what == "averages":
        from modules.bbg import rates
        print("average rows:", rates.compute_averages(conn))
        return 0
    if args.what == "expected":
        from modules.bbg import rates
        print("expected rows:", rates.compute_expected(conn))
        return 0
    if args.what == "tickers":
        from modules.bbg import match
        print("ticker map rows:", match.build_ticker_map(conn))
        return 0
    if args.what == "basis":
        from modules.bbg import equity
        equity.assign_consensus_periods(conn)
        equity.assign_market_basis(conn)
        print("market basis:", conn.execute("SELECT market_basis, COUNT(*) FROM bbg_entity WHERE found = 1 GROUP BY 1").fetchall())
        return 0

    from modules.bbg.client import BudgetExceeded, Client, LimitReached
    client = Client(conn, budget=args.budget)
    print(f"unique securities used this month: {client.used()} of {args.budget}")
    try:
        if args.what == "rates":
            from modules.bbg import rates
            print("rate rows:", rates.pull_history(client, conn, args.start or "19990101", args.full))
            print("average rows:", rates.compute_averages(conn))
            print("expected rows:", rates.compute_expected(conn))
        elif args.what == "entities":
            from modules.bbg import entities
            print("entities:", entities.pull(client, conn, args.limit))
        elif args.what == "equity":
            from modules.bbg import equity
            print("equity:", equity.pull(client, conn, args.limit, args.start or "20050101"))
        elif args.what == "bonds":
            from modules.bbg import bonds
            print("bonds:", bonds.pull(client, conn, args.limit, args.max_bonds, args.leis, args.all, args.census_only, args.relist))
        elif args.what == "ownership":
            from modules.bbg import ownership
            print("ownership:", ownership.pull(client, conn, args.limit))
        elif args.what == "bondhist":
            from modules.bbg import bonds
            print("bond history rows:", bonds.pull_history(client, conn, args.start or "20240101", args.leis))
        elif args.what == "bondmarket":
            from modules.bbg import bonds
            print("bond market rows:", bonds.refresh_market(client, conn, args.leis))
    except (BudgetExceeded, LimitReached) as e:
        print("STOPPED:", e)
        return 2
    finally:
        print(f"unique securities used this month: {client.used()} of {args.budget}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
