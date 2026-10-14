"""Ownership of the listed banks: the 20 largest holders (with their type: Government, Sovereign Wealth Fund, Bank, Investment Advisor, ...),
the share of each holder type, the institutional share, and the free float. State participation is the share of holders of type Government.

Bloomberg has no list of shareholders for a bank that is not listed (for example BIL). For such a bank the database holds the ultimate parent and the relationship to it
(bbg_entity.parent_name and parent_relationship, for example 'Govt Owned Entity' for Belfius).
"""

from __future__ import annotations

import datetime as dt
import sqlite3

from .client import Client

FIELDS = ["TOP_20_HOLDERS_PUBLIC_FILINGS", "INSTITUTION_TYPE_OWNERSHIP_PCT", "PCT_OWNERSHIP_TYP", "EQY_INST_PCT_SH_OUT", "EQY_FREE_FLOAT_PCT"]


def priced_tickers(conn: sqlite3.Connection) -> list[str]:
    return sorted(r[0] for r in conn.execute("SELECT DISTINCT ticker FROM bbg_equity_snapshot WHERE field = 'PX_LAST' AND value IS NOT NULL"))


def pull(client: Client, conn: sqlite3.Connection, limit: int = 0) -> dict:
    """Holders of every listed ticker in the database. These securities were requested for the equity data, so the pull costs no new unique security."""
    tickers = priced_tickers(conn)
    if limit:
        tickers = tickers[:limit]
    client.log(f"ownership of {len(tickers)} listed tickers")
    data = client.ref([f"{t} Equity" for t in tickers], FIELDS)
    today = dt.date.today().isoformat()
    holders, types = [], []
    for t in tickers:
        r = data.get(f"{t} Equity", {})
        if "_error" in r:
            continue
        for rank, h in enumerate(r.get("TOP_20_HOLDERS_PUBLIC_FILINGS") or [], start=1):
            holders.append((t, today, rank, h.get("Holder Name"), h.get("Institution Type"), h.get("Country"), h.get("Percent Outstanding"), h.get("Amount Held"),
                            h.get("Latest Change"), h.get("Filing Date"), h.get("Source")))
        for h in r.get("INSTITUTION_TYPE_OWNERSHIP_PCT") or []:
            types.append((t, today, "named", h.get("Ownership Type"), h.get("Ownership %")))
        for h in r.get("PCT_OWNERSHIP_TYP") or []:
            types.append((t, today, "all", h.get("Ownership Type"), h.get("Percent Ownership")))
        types += [(t, today, "scalar", f, r[f]) for f in ("EQY_INST_PCT_SH_OUT", "EQY_FREE_FLOAT_PCT") if r.get(f) is not None]
    conn.execute("DELETE FROM bbg_holder WHERE pull_date = ?", (today,))
    conn.execute("DELETE FROM bbg_ownership WHERE pull_date = ?", (today,))
    conn.executemany("INSERT OR REPLACE INTO bbg_holder VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", holders)
    conn.executemany("INSERT OR REPLACE INTO bbg_ownership VALUES (?, ?, ?, ?, ?)", types)
    conn.execute("INSERT INTO bbg_pull_log (started_at, kind, detail, n_rows, status) VALUES (?, 'ownership', ?, ?, 'ok')",
                 (dt.datetime.now().isoformat(timespec="seconds"), f"{len(tickers)} tickers", len(holders) + len(types)))
    conn.commit()
    with_gov = conn.execute("SELECT COUNT(DISTINCT ticker) FROM bbg_holder WHERE pull_date = ? AND holder_type = 'Government'", (today,)).fetchone()[0]
    return {"tickers": len(tickers), "holders": len(holders), "type rows": len(types), "tickers with a government holder in the top 20": with_gov}
