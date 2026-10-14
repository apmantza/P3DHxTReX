"""Match every P3DH entity to Bloomberg, and list its tickers.

P3DH identifies a bank by its LEI. A few groups carry a national code instead:
- Country code + the first 18 characters of a LEI (Groupe BPCE: FR9695005MSX1OYEMGDF). The last 2 characters of a LEI are check digits (ISO 7064), so the full LEI can be rebuilt.
- A national bank code (Volksbank Wien: AT0000000000043000VB). Then the match goes by name: a bond of the bank gives its LEI.
Tickers: the equity ticker of the bank (a placeholder such as 3358410Z FP means private), the equity ticker of the parent, and the ticker of its bonds.
"""

from __future__ import annotations

import re
import sqlite3

from .bonds import is_bond, issuer_tickers, list_bonds, same_issuer, to_request
from .client import Client

LEI_RE = re.compile(r"^[A-Z0-9]{18}[0-9]{2}$")
CODE_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{18}$")
PRIVATE_CODE = re.compile(r"^\d+[A-Z]?[ZD] ")  # placeholder tickers of private or delisted companies, for example 3358410Z FP


def check_digits(body18: str) -> str:
    """The 2 check digits of a LEI (ISO 7064, mod 97-10)."""
    number = "".join(str(int(ch, 36)) for ch in body18 + "00")
    return f"{98 - int(number) % 97:02d}"


def valid_lei(lei: str) -> bool:
    return bool(LEI_RE.match(lei)) and lei[18:] == check_digits(lei[:18])


def lei_from_code(code: str) -> str | None:
    """Full LEI from a code of country + 18 characters of a LEI. None if the code has another form."""
    if not CODE_RE.match(code):
        return None
    lei = code[2:] + check_digits(code[2:])
    return lei if valid_lei(lei) else None


def name_variants(name: str) -> list[str]:
    """The name, then the name without its last word, then without its last 2 words (P3DH names can end in a short code, for example VB). At least 2 words stay."""
    words = name.split()
    return [" ".join(words[:n]) for n in range(len(words), 1, -1)][:3]


def lei_by_name(client: Client, name: str) -> str | None:
    """LEI of a bank found by its name. First route: a live bond of the bank has the LEI of its issuer. Second route: the (private company) equity record of the bank."""
    for variant in name_variants(name):
        for ticker in issuer_tickers(client, variant):
            bonds = list_bonds(client, ticker, 0, variant)
            if not bonds:
                continue
            req = to_request(bonds[0][0])
            data = client.ref([req], ["LEGAL_ENTITY_IDENTIFIER", "ISSUER"]).get(req, {})
            lei = data.get("LEGAL_ENTITY_IDENTIFIER")
            if lei and LEI_RE.match(lei) and same_issuer(variant, str(data.get("ISSUER") or variant)):
                return lei
        for sec, desc in client.search(variant, "YK_FILTER_EQTY", 10):
            if not sec.endswith("<equity>") or not same_issuer(variant, re.sub(r"\s+-\s+.*$", "", desc)):
                continue
            req = sec[: -len("<equity>")] + " Equity"
            data = client.ref([req], ["LEGAL_ENTITY_IDENTIFIER", "NAME"]).get(req, {})
            lei = data.get("LEGAL_ENTITY_IDENTIFIER")
            if lei and LEI_RE.match(lei):
                return lei
    return None


def identify(client: Client, conn: sqlite3.Connection, limit: int = 0) -> list[tuple[str, str | None, str]]:
    """(P3DH key, LEI to request in Bloomberg, method) for every P3DH entity with a key.
    Method: lei (the key is a LEI), lei_rebuilt (code of country + LEI start), name (found by name), none (not found).
    A national code can look like country + LEI start and give a LEI that does not exist. The caller checks the rebuilt LEI in Bloomberg and falls back to the name."""
    rows = conn.execute("SELECT lei, MAX(entity_name) FROM entity WHERE lei IS NOT NULL GROUP BY lei ORDER BY lei").fetchall()
    out = []
    for key, name in rows[:limit] if limit else rows:
        if LEI_RE.match(key):
            out.append((key, key, "lei"))
            continue
        rebuilt = lei_from_code(key)
        if rebuilt:
            out.append((key, rebuilt, "lei_rebuilt"))
            continue
        found = lei_by_name(client, name)
        out.append((key, found, "name" if found else "none"))
        client.log(f"  {key} ({name}): {'LEI ' + found + ' found by name' if found else 'no match by name'}")
    return out


def build_ticker_map(conn: sqlite3.Connection) -> int:
    """Rewrite the ticker map from the tables of the database (no Bloomberg request).

    equity: the own equity ticker of the bank. priced = 1 when the stock has a price, 0 for a placeholder of a private company.
    proxy_equity: the listed ticker of an issuer that is not the same legal entity as the P3DH group (match by rebuilt LEI).
    parent_equity: the equity ticker of the ultimate parent, with the industry subgroup in the note.
    debt: the ticker of the bonds: from the group structure of Bloomberg, and from the bond listing.
    cds: the ticker of the credit default swap of the issuer.
    """
    priced = {r[0] for r in conn.execute("SELECT DISTINCT ticker FROM bbg_equity_snapshot WHERE field = 'PX_LAST' AND value IS NOT NULL")}
    subgroup = {r[0]: r[1] for r in conn.execute("SELECT ticker, value FROM bbg_equity_snapshot WHERE field = 'INDUSTRY_SUBGROUP'")}
    rows: list[tuple] = []
    for key, name, eq, par, par_name, method, debt, cds in conn.execute(
            "SELECT lei, name, equity_ticker, parent_ticker, parent_name, COALESCE(match_method, 'lei'), debt_ticker, cds_ticker FROM bbg_entity WHERE found = 1"):
        if debt:
            rows.append((key, "debt", debt, 0, "CAST_CORPORATE_STRUCTURE", "ticker of the bonds of the issuer (Bloomberg group structure)"))
        if cds:
            rows.append((key, "cds", cds, 0, "CAST_CORPORATE_STRUCTURE", ""))
        if eq:
            is_priced = eq in priced
            kind = "equity" if method == "lei" else "proxy_equity"
            note = "" if is_priced else ("private or delisted (placeholder code)" if PRIVATE_CODE.match(eq + " ") else "no price")
            if method != "lei":
                note = ("listed issuer; the P3DH group is larger" if is_priced else note) + f" (match: {method})"
            rows.append((key, kind, eq, int(is_priced), "ISSUER_EQUITY_TICKER", note))
        if par and par != eq:
            rows.append((key, "parent_equity", par, int(par in priced), "ULT_PARENT_TICKER_EXCHANGE", f"{par_name}; {subgroup.get(par, 'not priced')}"))
    for key, tickers in conn.execute("SELECT lei, GROUP_CONCAT(DISTINCT issuer_ticker) FROM bbg_bond_listing WHERE issuer_ticker <> '' GROUP BY lei"):
        for t in (tickers or "").split(","):
            if t:
                rows.append((key, "debt", t, 0, "bond search", ""))
    conn.execute("DELETE FROM bbg_ticker_map")
    conn.executemany("INSERT OR REPLACE INTO bbg_ticker_map (entity_key, kind, ticker, priced, source, note) VALUES (?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    return len(rows)
