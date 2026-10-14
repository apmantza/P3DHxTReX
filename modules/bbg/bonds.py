"""Bonds of the P3DH banks. Find the issuer ticker by name, list the bonds, then pull static data and the last price, yield, and spread.

The search service lists bonds as text, for example "ETEGA 5<7/8> 06/28/2035 REGS<corp>". The listing is free of data limits.
Static data costs one unique security for each bond, so the pull goes through the banks in the order of total assets and stops at the budget.
"""

from __future__ import annotations

import datetime as dt
import re
import sqlite3

from .client import BudgetExceeded, Client, LimitReached
from .schema import UNIVERSE_MIN_EUR

STATIC = ["ID_ISIN", "LEGAL_ENTITY_IDENTIFIER", "SECURITY_DES", "NAME", "CPN", "CPN_TYP", "MATURITY", "ISSUE_DT", "AMT_ISSUED", "AMT_OUTSTANDING", "CRNCY", "COLLAT_TYP",
          "PAYMENT_RANK", "SECURITY_TYP", "CALLABLE", "NXT_CALL_DT", "FIRST_CALL_DT_ISSUANCE", "MTY_TYP", "BASEL_III_DESIGNATION", "CAPITAL_CONTINGENT_SECURITY", "IS_PERPETUAL",
          "RTG_SP", "RTG_MOODY", "RTG_FITCH", "PX_LAST", "YLD_YTM_MID", "Z_SPRD_MID", "OAS_SPREAD_MID", "DUR_ADJ_MID", "ID_BB_GLOBAL", "SERIES"]
COLUMNS = ["isin", "issuer_lei", "des", "name", "coupon", "coupon_type", "maturity", "issue_date", "amt_issued", "amt_outstanding", "currency", "collateral_type",
           "payment_rank", "security_type", "callable", "next_call", "first_call", "maturity_type", "basel_iii", "contingent", "perpetual", "rating_sp", "rating_moodys",
           "rating_fitch", "px_last", "yield_mid", "z_spread", "oas", "duration", "bb_global", "series"]
BOND_TABLE_COLUMNS = ["security", "pulled_at", "lei", "isin", "issuer_lei", "designation", "name", "coupon", "coupon_type", "maturity", "issue_date", "amt_issued", "amt_outstanding",
                      "currency", "collateral_type", "payment_rank", "security_type", "callable", "next_call", "first_call", "maturity_type", "basel_iii", "contingent", "perpetual",
                      "rating_sp", "rating_moodys", "rating_fitch", "px_last", "yield_mid", "z_spread", "oas", "duration", "bb_global", "series"]
SUFFIX = re.compile(r"\b(s\.?a\.?|sa|ag|plc|spa|s\.p\.a\.?|nv|n\.v\.?|ab|a/s|as|asa|oyj|bank|banque|banco|banca|group|holdings?|holding|ltd|limited|se|dac|co|corp|the|of|de|di|and|und|et|kg|a\.s\.|s\.a|b\.v\.?|bv)\b")
# Market data: Bloomberg field -> column of bbg_bond_market. Yields in percent, spreads in basis points.
MARKET = {"PX_BID": "px_bid", "PX_ASK": "px_ask", "PX_MID": "px_mid", "PX_LAST": "px_last", "YLD_YTM_BID": "ytm_bid", "YLD_YTM_MID": "ytm_mid", "YLD_YTM_ASK": "ytm_ask",
          "YLD_YTC_MID": "ytc_mid", "YIELD_TO_WORST": "ytw", "WORKOUT_DATE_MID_TO_WORST": "worst_date", "I_SPRD_MID": "i_spread", "YAS_ISPREAD": "i_spread_yas",
          "Z_SPRD_MID": "z_spread", "G_SPREAD_MID_CALC": "g_spread", "YAS_YLD_SPREAD": "bench_spread", "YAS_BNCHMRK_BOND": "bench_bond", "GOVT_MTY_BNCHMRK_YLD_MID": "bench_yield",
          "ASSET_SWAP_SPD_MID": "asw_spread", "OAS_SPREAD_MID": "oas", "DUR_ADJ_MID": "duration", "CNVX_MID": "convexity", "AMT_OUTSTANDING": "amt_outstanding",
          "LAST_UPDATE_DT": "quote_date"}
MARKET_COLUMNS = ["quote_date", "px_bid", "px_ask", "px_mid", "px_last", "ytm_bid", "ytm_mid", "ytm_ask", "ytc_mid", "ytw", "worst_date", "i_spread", "z_spread", "g_spread",
                  "bench_spread", "bench_bond", "bench_yield", "asw_spread", "oas", "duration", "convexity", "amt_outstanding"]
CAP = 990
PERPETUAL_COUPONS = range(0, 15)
# Banks that get bond-level data by default: NBG, BIL, Bank of Cyprus, HCOB, and the other Greek banks. Other banks: use --leis.
FOCUS = {"5UMCZOEYKCVFAW8ZLO05": "NBG", "9CZ7TVMR36CYD5TZBS50": "BIL", "635400L14KNHZXPUZM19": "Bank of Cyprus", "TUKDD90GPC79G1KOE162": "HCOB",
         "213800KGF4EFNUQKAT69": "Eurobank", "213800DBQIB6VBNU5C64": "Alpha Bank", "213800OYHR1MPQ5VJL60": "Piraeus"}
DATE = re.compile(r"(\d{2})/(\d{2})/(\d{4})")


def alive(security: str, today: dt.date | None = None) -> bool:
    """A bond without a date in the name (a perpetual) is alive. A bond with a maturity date in the past is not."""
    today = today or dt.date.today()
    m = DATE.search(security)
    if not m:
        return True
    return dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2))) >= today


def norm(name: str) -> set[str]:
    s = re.sub(r"[^a-z0-9 ]", " ", name.lower().replace("&", " and "))
    s = SUFFIX.sub(" ", s)
    return {w for w in s.split() if len(w) > 1}


def _same_word(a: str, b: str) -> bool:
    """Equal words, or one is the start of the other (Bloomberg cuts some names, for example Luxemb for Luxembourg)."""
    return a == b or (min(len(a), len(b)) >= 5 and (a.startswith(b) or b.startswith(a)))


def same_issuer(a: str, b: str) -> bool:
    """Two names of the same issuer. The share of common words, counted against all words of both names, must be 75% or more.
    Deutsche Bank Luxembourg and Deutsche Bank AG are two issuers: they share 1 of 2 words."""
    x, y = norm(a), norm(b)
    if not x or not y:
        return False
    common = sum(1 for w in x if any(_same_word(w, v) for v in y))
    return common / (len(x) + len(y) - common) >= 0.75


FRACTION = re.compile(r"(\d*)<(\d+)/(\d+)>")


def _decimal(m: re.Match) -> str:
    value = int(m.group(1) or 0) + int(m.group(2)) / int(m.group(3))
    return f"{value:.6f}".rstrip("0").rstrip(".")


def to_request(security: str) -> str:
    """'ETEGA 5<7/8> 06/28/2035 REGS<corp>' becomes 'ETEGA 5.875 06/28/2035 REGS Corp'. Bloomberg accepts the decimal coupon, not the fraction."""
    s = FRACTION.sub(_decimal, security).replace("<corp>", " Corp")
    return re.sub(r"\s+", " ", s).strip()


def is_bond(security: str, ticker: str) -> bool:
    s = security
    if not s.endswith("<corp>") or not s.startswith(ticker + " "):
        return False
    return " CDS " not in s and not re.match(r"^BL\d", s)


LOAN_CODE = re.compile(r"^B[LF]\d+$")  # Bloomberg codes of loan facilities, for example BL196138


def issuer_tickers(client: Client, name: str) -> list[str]:
    found: list[str] = []
    for sec, desc in client.search(name, "YK_FILTER_CORP", 40):
        base = re.sub(r"\s*\(multiple matches\)\s*$", "", desc, flags=re.I)
        if not sec.endswith("<corp>") or not same_issuer(name, base):
            continue
        token = sec[:-6].split(" ")[0]
        if token and token not in found and not LOAN_CODE.match(token):
            found.append(token)
    return found


def list_bonds(client: Client, ticker: str, expected: int = 0, issuer: str = "", years: list[int] | None = None) -> list[tuple[str, str]]:
    """Live bonds of an issuer ticker. One search gives a part. A sweep over the maturity years adds the rest.
    years: the years in which the issuer has debt that matures (from the debt maturity profile). Without it the sweep covers 35 years, or it is skipped when the first search is complete.
    A ticker can belong to several issuers. With the issuer name, a bond stays only if its issuer name matches."""
    def keep(s: str, d: str) -> bool:
        if not (is_bond(s, ticker) and alive(s)):
            return False
        return not issuer or same_issuer(issuer, re.sub(r"\s*\(multiple matches\)\s*$", "", d, flags=re.I))

    res = {s: d for s, d in client.search(ticker, "YK_FILTER_CORP", 1000) if keep(s, d)}
    if years is not None or len(res) < 0.9 * expected or len(res) >= CAP:
        sweep = years if years is not None else list(range(dt.date.today().year, dt.date.today().year + 35))
        for year in sweep:
            for s, d in client.search(f"{ticker} {year}", "YK_FILTER_CORP", 1000):
                if keep(s, d):
                    res[s] = d
        for q in (f"{ticker} FRN", f"{ticker} 0"):
            for s, d in client.search(q, "YK_FILTER_CORP", 1000):
                if keep(s, d):
                    res[s] = d
    # Bloomberg finds a perpetual only when the query holds a coupon. The query "<ticker> 7 PERP" returns the perpetuals with a coupon from 7 to 7.99.
    for n in PERPETUAL_COUPONS:
        for s, d in client.search(f"{ticker} {n} PERP", "YK_FILTER_CORP", 1000):
            if " PERP" in s and keep(s, d):
                res[s] = d
    return list(res.items())


def maturity_years(conn: sqlite3.Connection, lei: str) -> list[int] | None:
    """Years from now on with debt that matures (bonds or bonds and loans). None when the bank has no profile."""
    rows = conn.execute("SELECT year FROM bbg_debt_maturity WHERE lei = ? AND year >= ? AND (COALESCE(bonds_m, 0) > 0 OR COALESCE(bonds_loans_m, 0) > 0) ORDER BY year",
                        (lei, dt.date.today().year)).fetchall()
    return [r[0] for r in rows] or None


def census(client: Client, conn: sqlite3.Connection, leis: list[str] | None = None, limit: int = 0, relist: bool = False) -> dict:
    """List the live bonds of banks. The search service costs no unique security. A bank that is listed already is skipped, unless relist is true (new issues of a bank that was listed before).
    A bond that is listed again keeps its status.
    leis=None: every bank with debt. The listing gets one row for each bond (status NULL) and the issuer ticker, also when the bank has no bond."""
    where, params = "", ()
    if leis:
        where, params = f" AND e.lei IN ({','.join('?' * len(leis))})", tuple(leis)
    rows = conn.execute(f"""SELECT e.lei, e.long_name, e.name, (SELECT MAX(entity_name) FROM entity WHERE lei = e.lei), COALESCE(e.n_bond_issues, 0)
                            FROM bbg_entity e WHERE e.found = 1 AND e.n_bond_issues > 0{where}
                            ORDER BY CASE WHEN e.match_method = 'lei' OR e.match_method IS NULL THEN 0 ELSE 1 END, COALESCE(e.total_assets, 0) DESC""", params).fetchall()
    # two P3DH entities can have one Bloomberg issuer (Groupe Credit Agricole and Credit Agricole SA): list the bonds once, under the entity with a real LEI
    seen, unique = set(), []
    issuer = dict(conn.execute("SELECT lei, COALESCE(bbg_lei, lei) FROM bbg_entity").fetchall())
    for r in rows:
        if issuer.get(r[0], r[0]) not in seen:
            seen.add(issuer.get(r[0], r[0]))
            unique.append(r)
    rows = sorted(unique, key=lambda r: -(conn.execute("SELECT COALESCE(total_assets, 0) FROM bbg_entity WHERE lei = ?", (r[0],)).fetchone()[0]))
    done = set() if relist else {r[0] for r in conn.execute("SELECT DISTINCT lei FROM bbg_bond_listing")}
    todo = [r for r in rows if r[0] not in done]
    if limit:
        todo = todo[:limit]
    client.log(f"census: {len(rows)} banks with debt, {len(rows) - len(todo)} listed already, {len(todo)} to list")
    n_bonds = n_none = 0
    for k, (lei, long_name, name, p3dh_name, expected) in enumerate(todo):
        tickers, used = [], ""
        for cand in dict.fromkeys(x for x in (long_name, name, p3dh_name) if x):
            tickers = issuer_tickers(client, cand)
            if tickers:
                used = cand
                break
        listed: dict[str, tuple[str, str]] = {}
        years = maturity_years(conn, lei)
        for t in tickers:
            for s, d in list_bonds(client, t, expected if t == tickers[0] else 0, used, years):
                listed[s] = (t, d)
        upsert = "INSERT INTO bbg_bond_listing (lei, issuer_ticker, security, description) VALUES (?, ?, ?, ?) ON CONFLICT(lei, security) DO UPDATE SET issuer_ticker = excluded.issuer_ticker, description = excluded.description"
        conn.executemany(upsert, [(lei, t, s, d) for s, (t, d) in listed.items()])
        if not listed:
            conn.execute(upsert, (lei, ",".join(tickers), "", "no bonds found" if tickers else "no issuer ticker found"))
            n_none += 1
        conn.commit()
        n_bonds += len(listed)
        if (k + 1) % 10 == 0:
            client.log(f"  census {k + 1}/{len(todo)} banks, {n_bonds} live bonds listed")
    conn.execute("UPDATE bbg_bond_listing SET status = 'ambiguous' WHERE status IS NULL AND description LIKE '%Multiple Matches%'")
    classify_known(conn)
    return {"banks listed": len(todo), "bonds listed": n_bonds, "banks without bonds": n_none}


MIN_AVERAGE_BOND = 50_000_000  # an issuer whose bonds average less than this (EUR) has almost no bond above the universe limit: 1% of such bonds do


def rank_candidates(rows: list[tuple], focus: set[str] | None = None) -> list[tuple[str, str]]:
    """Order the bonds that are not in the database yet, so that the likely members of the universe (outstanding above UNIVERSE_MIN_EUR) are requested first.
    The size of a bond is known only after it is requested, so the order uses signals that cost nothing:
    - the average bond of the issuer (amount of debt / number of issues). An issuer below MIN_AVERAGE_BOND is skipped: 1% of its bonds are in the universe, against 37% to 61% for the others.
    - the name: a Reg S bond with a coupon is in the universe in 74% of the cases. A zero-coupon note or a bond without Reg S in 11% to 14%.
    - an issuer whose total debt is below the universe limit cannot have a bond in it.
    rows: (security, lei, issuer debt in EUR, number of issues, total assets). Banks in focus are never skipped."""
    focus = focus or set()
    ranked = []
    for security, lei, debt, n_issues, assets in rows:
        avg = debt / n_issues if debt and n_issues else None
        if lei not in focus and debt is not None and (debt <= UNIVERSE_MIN_EUR or (avg is not None and avg < MIN_AVERAGE_BOND)):
            continue
        good_name = " REGS<" in security and not re.match(r"^\S+ 0 ", security)
        big_issuer = avg is not None and avg >= 100_000_000
        tier = 0 if lei in focus else (1 if good_name and big_issuer else 2 if good_name else 3 if big_issuer else 4)
        ranked.append((tier, -(assets or 0), security, lei))
    ranked.sort()
    return [(r[2], r[3]) for r in ranked]


def pending_candidates(conn: sqlite3.Connection, scope: list[str] | None) -> list[tuple[str, str]]:
    where, params = "", ()
    if scope:
        where, params = f" AND l.lei IN ({','.join('?' * len(scope))})", tuple(scope)
    rows = conn.execute(f"""SELECT l.security, l.lei, e.bond_amt_outstanding, e.n_bond_issues, e.total_assets FROM bbg_bond_listing l JOIN bbg_entity e ON e.lei = l.lei
                            WHERE l.security <> '' AND l.status IS NULL AND l.security NOT IN (SELECT security FROM bbg_bond){where}""", params).fetchall()
    return rank_candidates(rows, set(FOCUS))


def classify_known(conn: sqlite3.Connection) -> None:
    """Status of the bonds that are in the database: redeemed (amount 0 or matured), ok (in the universe), or small (outstanding, but not above the universe limit)."""
    conn.execute(f"""UPDATE bbg_bond_listing SET status = (
                         SELECT CASE WHEN NOT (b.amt_outstanding > 0 AND (b.perpetual = 'Y' OR b.maturity IS NULL OR b.maturity >= date('now'))) THEN 'redeemed'
                                     WHEN v.amt_outstanding_eur > {UNIVERSE_MIN_EUR} THEN 'ok' ELSE 'small' END
                         FROM bbg_bond b LEFT JOIN v_bond_outstanding v ON v.security = b.security WHERE b.security = bbg_bond_listing.security)
                     WHERE security IN (SELECT security FROM bbg_bond) AND (status IS NULL OR status IN ('ok', 'small', 'redeemed'))""")
    conn.commit()


def _market_row(m: dict, pull_date: str, security: str) -> tuple:
    v = {MARKET[f]: m.get(f) for f in MARKET}
    i_spread = v["i_spread"] if v["i_spread"] is not None else v["i_spread_yas"]
    ytw = v["ytw"]
    if ytw is None:
        ytw = min((y for y in (v["ytm_mid"], v["ytc_mid"]) if y is not None), default=None)
    v["i_spread"], v["ytw"] = i_spread, ytw
    return (security, pull_date) + tuple(v[c] for c in MARKET_COLUMNS)


def _save_market(conn: sqlite3.Connection, data: dict, req: dict, pull_date: str) -> int:
    rows = [_market_row(data[r], pull_date, s) for r, s in req.items() if r in data and "_error" not in data[r]]
    conn.executemany("INSERT OR REPLACE INTO bbg_bond_market (security, pull_date, " + ", ".join(MARKET_COLUMNS) + ") VALUES (" + ",".join("?" * (2 + len(MARKET_COLUMNS))) + ")", rows)
    return len(rows)


def refresh_market(client: Client, conn: sqlite3.Connection, leis: list[str] | None = None) -> int:
    """Price, yields, and spreads of the bonds in the universe that are in the database. These securities were requested before, so this costs no new unique security."""
    where, params = "", ()
    if leis:
        where, params = f" WHERE lei IN ({','.join('?' * len(leis))})", tuple(leis)
    secs = [r[0] for r in conn.execute(f"SELECT security FROM v_bond_universe{where}", params)]
    req = {to_request(s): s for s in secs}
    client.log(f"market data of {len(req)} bonds in the universe (outstanding above EUR {UNIVERSE_MIN_EUR / 1e6:,.0f}m)")
    today = dt.date.today().isoformat()
    n = 0
    for i in range(0, len(req), 300):
        part = dict(list(req.items())[i:i + 300])
        data = client.ref(list(part), list(MARKET))
        n += _save_market(conn, data, part, today)
        conn.commit()
        client.log(f"  market {min(i + 300, len(req))}/{len(req)}")
    conn.execute("INSERT INTO bbg_pull_log (started_at, kind, detail, n_rows, status) VALUES (?, 'bond_market', ?, ?, 'ok')", (dt.datetime.now().isoformat(timespec="seconds"), f"{len(req)} bonds", n))
    conn.commit()
    return n


def pull(client: Client, conn: sqlite3.Connection, limit: int = 0, max_bonds: int = 100000, leis: list[str] | None = None, everything: bool = False, census_only: bool = False,
         relist: bool = False) -> dict:
    """Census, then static and market data of the bonds that are not in the database, then the market data of the bonds in the universe.
    The universe is the bonds with an outstanding amount above UNIVERSE_MIN_EUR. The size of a bond is known only after it is requested, so rank_candidates puts the likely members first."""
    scope = None if everything else (leis or list(FOCUS))
    result: dict = {"census": census(client, conn, scope, limit, relist)}
    if census_only:
        return result
    todo = pending_candidates(conn, scope)[:max_bonds]
    client.log(f"static and market data of {len(todo)} bonds (candidates of the universe, most likely first)")
    now = dt.datetime.now().isoformat(timespec="seconds")
    today = dt.date.today().isoformat()
    fields = STATIC + [f for f in MARKET if f not in STATIC]
    n_static, n_redeemed, stopped = 0, 0, ""
    for i in range(0, len(todo), 100):
        part = todo[i:i + 100]
        req = {to_request(s): (s, lei) for s, lei in part}
        try:
            data = client.ref(list(req), fields)
        except (BudgetExceeded, LimitReached) as e:
            stopped = str(e)
            break
        recs = []
        for r, (s, lei) in req.items():
            v = data.get(r, {})
            if "_error" in v:
                conn.execute("UPDATE bbg_bond_listing SET status = 'unresolved' WHERE lei = ? AND security = ?", (lei, s))
                continue
            m = {f: v.get(f) for f in fields}
            # column order of bbg_bond: security, pulled_at, lei, isin, issuer_lei, designation, name, coupon, ...
            recs.append((s, now, lei, m["ID_ISIN"], m["LEGAL_ENTITY_IDENTIFIER"], m["SECURITY_DES"], m["NAME"], m["CPN"], m["CPN_TYP"], m["MATURITY"], m["ISSUE_DT"], m["AMT_ISSUED"],
                         m["AMT_OUTSTANDING"], m["CRNCY"], m["COLLAT_TYP"], m["PAYMENT_RANK"], m["SECURITY_TYP"], m["CALLABLE"], m["NXT_CALL_DT"], m["FIRST_CALL_DT_ISSUANCE"],
                         m["MTY_TYP"], m["BASEL_III_DESIGNATION"], m["CAPITAL_CONTINGENT_SECURITY"], m["IS_PERPETUAL"], m["RTG_SP"], m["RTG_MOODY"], m["RTG_FITCH"], m["PX_LAST"],
                         m["YLD_YTM_MID"], m["Z_SPRD_MID"], m["OAS_SPREAD_MID"], m["DUR_ADJ_MID"], m["ID_BB_GLOBAL"], m["SERIES"]))
        conn.executemany("INSERT OR REPLACE INTO bbg_bond (" + ", ".join(BOND_TABLE_COLUMNS) + ") VALUES (" + ",".join("?" * len(BOND_TABLE_COLUMNS)) + ")", recs)
        n_redeemed += sum(1 for rec in recs if not ((rec[12] or 0) > 0 and (rec[23] == "Y" or not rec[9] or rec[9] >= today)))
        _save_market(conn, data, {r: x[0] for r, x in req.items()}, today)
        conn.commit()
        classify_known(conn)
        n_static += len(recs)
        client.log(f"  static and market data {min(i + 100, len(todo))}/{len(todo)}")
    conn.execute("INSERT INTO bbg_pull_log (started_at, kind, detail, n_rows, status) VALUES (?, 'bonds', ?, ?, ?)",
                 (now, f"{n_static} bonds with static data ({n_redeemed} no longer outstanding)", n_static, "stopped: " + stopped if stopped else "ok"))
    conn.commit()
    if stopped:
        client.log(f"stopped: {stopped}")
    result["static"], result["redeemed"], result["stopped"] = n_static, n_redeemed, stopped
    result["market"] = refresh_market(client, conn, scope)
    where2, params2 = "", ()
    if scope:
        where2, params2 = f" AND lei IN ({','.join('?' * len(scope))})", tuple(scope)
    result["listing status"] = dict(conn.execute(f"SELECT COALESCE(status, 'pending'), COUNT(*) FROM bbg_bond_listing WHERE security <> ''{where2} GROUP BY 1", params2).fetchall())
    return result


HISTORY = {"PX_LAST": "px_last", "PX_BID": "px_bid", "PX_ASK": "px_ask", "YLD_YTM_MID": "ytm_mid", "YLD_YTC_MID": "ytc_mid", "I_SPRD_MID": "i_spread", "Z_SPRD_MID": "z_spread",
           "ASSET_SWAP_SPD_MID": "asw_spread"}


def pull_history(client: Client, conn: sqlite3.Connection, start: str = "20240101", leis: list[str] | None = None) -> int:
    """Daily price, yields, and spreads of the outstanding bonds that have a quote. A bond that has history is updated from 5 days before its last date."""
    where, params = "", ()
    if leis:
        where, params = f" AND lei IN ({','.join('?' * len(leis))})", tuple(leis)
    secs = [r[0] for r in conn.execute(f"SELECT security FROM v_bond_universe WHERE px_mid IS NOT NULL{where}", params)]
    last = {r[0]: r[1] for r in conn.execute("SELECT security, MAX(date) FROM bbg_bond_history GROUP BY security")}
    groups: dict[str, dict[str, str]] = {}
    for s in secs:
        begin = start if s not in last else (dt.date.fromisoformat(last[s]) - dt.timedelta(days=5)).strftime("%Y%m%d")
        groups.setdefault(begin, {})[to_request(s)] = s
    end = dt.date.today().strftime("%Y%m%d")
    n = 0
    for begin, req in groups.items():
        items = list(req.items())
        for i in range(0, len(items), 5):
            part = dict(items[i:i + 5])
            data = client.hist(list(part), list(HISTORY), begin, end)
            recs = []
            for r, s in part.items():
                for d, v in data.get(r, []):
                    vals = [v.get(f) for f in HISTORY]
                    if any(x is not None for x in vals):
                        recs.append((s, d, *vals))
            conn.executemany("INSERT OR REPLACE INTO bbg_bond_history VALUES (" + ",".join("?" * (2 + len(HISTORY))) + ")", recs)
            conn.commit()
            n += len(recs)
            if (i // 5) % 20 == 0:
                client.log(f"  history from {begin}: {i + len(part)}/{len(items)} bonds, {n} rows")
    conn.execute("INSERT INTO bbg_pull_log (started_at, kind, detail, n_rows, status) VALUES (?, 'bond_history', ?, ?, 'ok')", (dt.datetime.now().isoformat(timespec="seconds"), f"{len(secs)} bonds from {start}", n))
    conn.commit()
    return n
