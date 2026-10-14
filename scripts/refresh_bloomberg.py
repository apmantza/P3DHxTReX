"""Refresh the Bloomberg data of the P3DH database. Run it with the Python of the blauto project (it has blpapi). The Bloomberg terminal must run and be logged in.

  C:\\Users\\E40889\\Documents\\blauto\\.venv\\Scripts\\python scripts\\refresh_bloomberg.py daily
  ... refresh_bloomberg.py weekly       # the daily steps and the slow ones
  ... refresh_bloomberg.py monthly      # all steps, including new bonds (this one uses unique securities)
  ... refresh_bloomberg.py daily --dry-run      # show the steps only
  ... refresh_bloomberg.py daily --only rates,bond_market
  ... refresh_bloomberg.py status       # when each kind of data was pulled last

The daily and weekly runs can not request a new security: their budget is the number that this month has used already. A step that needs one stops, and the run reports it.
Only the monthly run spends unique securities (budget --budget, default 4,500). Run it on the 2nd of a month, after the count of Bloomberg has started again.
Exit code: 0 all steps ok, 1 a step failed, 2 a limit or budget stopped a step, 3 the terminal is not reachable.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.bbg import schema  # noqa: E402
from modules.bbg.client import BudgetExceeded, LimitReached  # noqa: E402

DAILY = ["rates", "equity_prices", "bond_market", "bond_history", "basis", "tickers"]
WEEKLY = ["rates", "equity_prices", "equity_slow", "ownership", "bond_market", "bond_history", "basis", "tickers"]
MONTHLY = ["rates", "entities", "equity_prices", "equity_slow", "ownership", "bonds", "bond_history", "basis", "tickers"]
PLAN = {"daily": DAILY, "weekly": WEEKLY, "monthly": MONTHLY}
OFFLINE = {"basis", "tickers"}  # these steps read the database only

# What each step does and what it costs. Used by the dry run and by the docs.
DESCRIPTION = {
    "rates": "rates, curves, FX since the last date; averages; expected deposit rate (no new security)",
    "entities": "every P3DH bank: names, parents, tickers, fundamentals, debt profile (no new security)",
    "equity_prices": "snapshot, daily prices and market cap of the listed banks (no new security)",
    "equity_slow": "fundamentals and consensus of the listed banks (no new security)",
    "ownership": "20 largest holders and holder types of the listed banks (no new security)",
    "bonds": "census of all banks again, then static and market data of new candidates of the universe (new securities)",
    "bond_market": "price, yields, and spreads of the bonds in the universe (no new security)",
    "bond_history": "daily history of the quoted bonds of the universe (no new security)",
    "basis": "market basis of each bank and fiscal year of the consensus (offline)",
    "tickers": "ticker map of each bank (offline)",
}


def budget_for(level: str, used: int, default: int) -> int:
    """The daily and weekly runs get the number used so far: they cannot request a new security."""
    return default if level == "monthly" else used


def run_plan(steps: list[str], fns: dict[str, Callable[[], str]], log: Callable[[str], None] = print, terminal_up: bool = True) -> tuple[list[dict], int]:
    """Run the steps in order. A step that fails does not stop the next ones. Returns the results and the exit code."""
    results, code = [], 0
    for name in steps:
        t0 = time.time()
        if not terminal_up and name not in OFFLINE:
            results.append({"step": name, "status": "skipped: no terminal", "seconds": 0.0, "detail": ""})
            continue
        try:
            detail = fns[name]()
            status = "ok"
        except (BudgetExceeded, LimitReached) as e:
            detail, status = str(e), "stopped: limit or budget"
            code = max(code, 2)
        except Exception as e:  # noqa: BLE001 - one step must not stop the others
            detail, status = f"{type(e).__name__}: {e}", "failed"
            code = max(code, 1)
        results.append({"step": name, "status": status, "seconds": round(time.time() - t0, 1), "detail": detail})
        log(f"[{name}] {status} in {results[-1]['seconds']}s {detail}")
    return results, code


def make_steps(client, conn: sqlite3.Connection, args) -> dict[str, Callable[[], str]]:
    def rates() -> str:
        from modules.bbg import rates as r
        n = r.pull_history(client, conn, "19990101", False)
        return f"{n} rows; averages {r.compute_averages(conn)}; expected {r.compute_expected(conn)}"

    def entities() -> str:
        from modules.bbg import entities as e
        return f"{e.pull(client, conn)} entities"

    def equity_prices() -> str:
        from modules.bbg import equity as q
        return str(q.pull(client, conn, 0, "20050101", parts=("daily",)))

    def equity_slow() -> str:
        from modules.bbg import equity as q
        return str(q.pull(client, conn, 0, "20050101", parts=("fundamentals", "consensus")))

    def ownership() -> str:
        from modules.bbg import ownership as o
        return str(o.pull(client, conn))

    def bonds() -> str:
        from modules.bbg import bonds as b
        return str(b.pull(client, conn, 0, args.max_bonds, None, True, False, True))

    def bond_market() -> str:
        from modules.bbg import bonds as b
        return f"{b.refresh_market(client, conn)} rows"

    def bond_history() -> str:
        from modules.bbg import bonds as b
        return f"{b.pull_history(client, conn, '20240101')} rows"

    def basis() -> str:
        from modules.bbg import equity as q
        q.assign_consensus_periods(conn)
        q.assign_market_basis(conn)
        return str(dict(conn.execute("SELECT COALESCE(market_basis, 'not set'), COUNT(*) FROM bbg_entity WHERE found = 1 GROUP BY 1").fetchall()))

    def tickers() -> str:
        from modules.bbg import match
        return f"{match.build_ticker_map(conn)} rows"

    return {"rates": rates, "entities": entities, "equity_prices": equity_prices, "equity_slow": equity_slow, "ownership": ownership, "bonds": bonds,
            "bond_market": bond_market, "bond_history": bond_history, "basis": basis, "tickers": tickers}


def status(conn: sqlite3.Connection) -> None:
    now = dt.datetime.now()
    print(f"{'kind':16s} {'last run':20s} {'age':>8s}  detail")
    for kind, started, detail, st in conn.execute("""SELECT kind, started_at, detail, status FROM bbg_pull_log WHERE pull_id IN (SELECT MAX(pull_id) FROM bbg_pull_log GROUP BY kind) ORDER BY kind"""):
        age = now - dt.datetime.fromisoformat(started)
        print(f"{kind:16s} {started:20s} {age.days:>5d} d  {(detail or '')[:70]} [{st}]")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("level", choices=["daily", "weekly", "monthly", "status"])
    ap.add_argument("--db", default=os.environ.get("P3DH_DB", str(ROOT / "data" / "processed" / "p3dh.sqlite")))
    ap.add_argument("--budget", type=int, default=4500, help="monthly run: unique securities that this project may request in a month")
    ap.add_argument("--max-bonds", type=int, default=100000, help="monthly run: most new bonds that get static data")
    ap.add_argument("--only", default="", help="comma list of steps")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db, timeout=600)
    conn.execute("PRAGMA journal_mode=WAL")
    schema.create(conn)
    if args.level == "status":
        status(conn)
        return 0
    steps = [s for s in PLAN[args.level] if not args.only or s in args.only.split(",")]
    print(f"{dt.datetime.now():%Y-%m-%d %H:%M} refresh {args.level}: " + ", ".join(steps))
    if args.dry_run:
        for s in steps:
            print(f"  {s:14s} {DESCRIPTION[s]}")
        return 0

    client, terminal_up = None, True
    try:
        from modules.bbg.client import Client
        client = Client(conn, budget=args.budget)
        client.budget = budget_for(args.level, client.used(), args.budget)
        print(f"unique securities used this month: {client.used()}; budget of this run: {client.budget}")
    except Exception as e:  # noqa: BLE001
        print(f"The Bloomberg terminal is not reachable: {e}")
        terminal_up = False
    results, code = run_plan(steps, make_steps(client, conn, args) if client else {s: (lambda: "") for s in steps}, terminal_up=terminal_up)
    now = dt.datetime.now().isoformat(timespec="seconds")
    ok = sum(r["status"] == "ok" for r in results)
    conn.execute("INSERT INTO bbg_pull_log (started_at, kind, detail, n_rows, status) VALUES (?, ?, ?, ?, ?)",
                 (now, f"refresh_{args.level}", "; ".join(f"{r['step']}: {r['status']}" for r in results), ok, "ok" if code == 0 else "check"))
    conn.commit()
    if not terminal_up:
        return 3
    print(f"{ok} of {len(results)} steps ok" + (f"; used {client.used()} unique securities" if client else ""))
    return code


if __name__ == "__main__":
    sys.exit(main())
