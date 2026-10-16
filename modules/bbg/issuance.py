"""Issuance of banks from the Bloomberg tables of the database: one row for each bond with its debt type, its class (public or private), and its maturity bucket.
The workbook writer is in issuance_xlsx.py. The functions read the database only. They need no Bloomberg terminal.

Debt type follows the Bloomberg payment rank and the Basel III designation. Public or private follows the user's rule: a note in a public MTN programme (EMTN, GMTN, DMTN) is public.
A note that is not in a programme is public only when it is a benchmark (EUR 150m or more). All other notes are private.
"""

from __future__ import annotations

import datetime as dt
import re
import sqlite3
from typing import Any

import pandas as pd

from .bonds import FRACTION, _decimal, alive
from .schema import UNIVERSE_MIN_EUR

AT1, T2, SNP, SP, COVERED, SENIOR, STRUCTURED = ("AT1", "Tier 2", "Senior non-preferred", "Senior preferred", "Covered bond", "Senior unsecured (programme notes)",
                                                 "Structured and private notes")
DEBT_TYPES = [AT1, T2, SNP, SP, COVERED, SENIOR, STRUCTURED]
PERPETUAL_KEY = 9999
ATS_PER_EUR = 13.7603  # fixed conversion rate of the Austrian schilling, as in the view v_bond_outstanding
STRUCTURED_COUPONS = {"ZERO COUPON", "STEP CPN"}
STRUCTURED_MATURITIES = {"CONVERTIBLE", "CONV/CALL"}  # the note can be repaid in shares or in another asset
SIZE_BUCKETS = [(10e6, "below 10"), (50e6, "10 to 50"), (150e6, "50 to 150")]


def programme(series: str | None) -> str:
    """The public MTN programme of a note, or an empty text. Bloomberg writes the series in mixed case (EMTN, Emtn, emTN)."""
    s = (series or "").strip().upper()
    if s.startswith("EMT"):
        return "EMTN"
    return s if s in ("GMTN", "DMTN") else ""


def debt_type(rank: str | None, basel: str | None, collateral: str | None, coupon_type: str | None, maturity_type: str | None, prog: str) -> str:
    """The order of the tests matters: capital layers first, then senior non-preferred, covered, and senior preferred. A senior unsecured note is a programme note
    only when it has a plain coupon (fixed, floating, or variable) and does not convert. Every other note is structured or private."""
    rank, basel, collateral = rank or "", basel or "", (collateral or "").upper()
    if basel == "Additional Tier 1" or rank == "Jr Subordinated":
        return AT1
    if basel == "Tier 2" or rank == "Subordinated":
        return T2
    if rank == "Sr Non Preferred":
        return SNP
    if collateral == "COVERED":
        return COVERED
    if rank == "Sr Preferred":
        return SP
    plain = bool(prog) and (coupon_type or "") not in STRUCTURED_COUPONS and (maturity_type or "") not in STRUCTURED_MATURITIES
    return SENIOR if plain else STRUCTURED


def placement(prog: str, size_eur: float | None) -> tuple[str, str]:
    """(public or private, basis of the class)."""
    if prog:
        return "Public", f"{prog} programme"
    if size_eur is not None and size_eur >= UNIVERSE_MIN_EUR:
        return "Public", "Standalone benchmark, EUR 150m or more"
    return "Private", "Not in a programme, below EUR 150m" if size_eur is not None else "Not in a programme, size unknown"


def size_bucket(size_eur: float | None) -> str:
    if size_eur is None:
        return ""
    for limit, label in SIZE_BUCKETS:
        if size_eur < limit:
            return label
    return "150 or more"


def bucket_key(year: int | None, first_year: int) -> int:
    """Calendar year of the profile. Years from first_year + 10 on are one bucket. None is a perpetual."""
    if year is None:
        return PERPETUAL_KEY
    return min(max(year, first_year), first_year + 10)


def bucket_labels(first_year: int) -> list[tuple[int, str]]:
    return [(y, str(y)) for y in range(first_year, first_year + 10)] + [(first_year + 10, f"{first_year + 10}+"), (PERPETUAL_KEY, "Perpetual")]


def _date(v: Any) -> dt.date | None:
    if v is None or (isinstance(v, float) and v != v) or v == "":
        return None
    return dt.date.fromisoformat(str(v)[:10])


def fx_rates(conn: sqlite3.Connection) -> tuple[dict[str, float], str | None]:
    """Units of a currency for one EUR, from the latest value of each series FX_EUR<currency>, and the latest date."""
    rows = conn.execute("""SELECT series, value, date FROM bbg_rate_daily x WHERE series LIKE 'FX_EUR___' AND date = (SELECT MAX(date) FROM bbg_rate_daily y WHERE y.series = x.series)""").fetchall()
    return {s[-3:]: v for s, v, _ in rows if v}, max((d for _, _, d in rows), default=None)


def to_eur(amount: float | None, currency: str | None, fx: dict[str, float]) -> float | None:
    if amount is None or amount != amount:
        return None
    if currency == "EUR":
        return amount
    if currency == "ATS":
        return amount / ATS_PER_EUR
    rate = fx.get(currency or "")
    return amount / rate if rate else None


def parse_name(security: str) -> tuple[float | None, dt.date | None, bool]:
    """Coupon, maturity date, and perpetual flag from a Bloomberg name such as 'TICKER 5<7/8> 06/28/2035 REGS<corp>' or 'TICKER 0 PERP<corp>'."""
    text = FRACTION.sub(_decimal, security.replace("<corp>", ""))
    tokens = text.split()
    coupon = None
    if len(tokens) > 1:
        try:
            coupon = float(tokens[1])
        except ValueError:
            coupon = None
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", text)
    date = dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2))) if m else None
    return coupon, date, " PERP" in f" {text}"


def load(conn: sqlite3.Connection, banks: list[tuple[str, str]], today: dt.date | None = None) -> dict[str, Any]:
    """banks: [(short name, LEI)]. Returns {'issues': frame, 'unresolved': frame, 'meta': {...}, 'first_year': year}.
    issues: one row for each bond in bbg_bond (active or not). unresolved: live names of the census without a record in bbg_bond (several notes behind one name, not found, or not loaded yet)."""
    today = today or dt.date.today()
    short = {lei: s for s, lei in banks}
    marks = ",".join("?" * len(banks))
    leis = [lei for _, lei in banks]
    fx, fx_date = fx_rates(conn)
    raw = conn.execute(f"""SELECT b.lei, b.security, b.isin, b.name, b.payment_rank, b.basel_iii, b.collateral_type, b.coupon, b.coupon_type, b.issue_date, b.maturity, b.next_call, b.perpetual,
                                  b.currency, b.amt_issued, b.amt_outstanding, b.maturity_type, b.series, b.pulled_at, m.quote_date, m.px_mid, m.ytm_mid, m.i_spread, m.z_spread
                           FROM bbg_bond b LEFT JOIN bbg_bond_market m ON m.security = b.security AND m.pull_date = (SELECT MAX(pull_date) FROM bbg_bond_market x WHERE x.security = b.security)
                           WHERE b.lei IN ({marks}) ORDER BY b.lei, b.maturity""", leis).fetchall()
    cols = ["lei", "security", "isin", "name", "rank", "basel", "collateral", "coupon", "coupon_type", "issue_date", "maturity", "next_call", "perpetual", "currency", "issued", "outstanding",
            "maturity_type", "series", "pulled_at", "quote_date", "px", "ytm", "i_spread", "z_spread"]
    rows = []
    for r in raw:
        d = dict(zip(cols, r))
        perpetual = d["perpetual"] == "Y"
        mat, call = _date(d["maturity"]), _date(d["next_call"])
        eur = to_eur(d["outstanding"], d["currency"], fx)
        active = bool(d["outstanding"] and d["outstanding"] > 0 and (perpetual or mat is None or mat >= today))
        size = eur if eur else to_eur(d["issued"], d["currency"], fx)
        prog = programme(d["series"])
        kind = debt_type(d["rank"], d["basel"], d["collateral"], d["coupon_type"], d["maturity_type"], prog)
        pub, basis = placement(prog, size)
        year_m = None if perpetual else (mat.year if mat else None)
        year_c = call.year if call and call >= today and (perpetual or mat is None or call <= mat) else year_m
        rows.append({
            "issuer": short[d["lei"]], "active": "Y" if active else "N", "debt_type": kind, "public_private": pub, "programme": prog, "basis": basis, "isin": d["isin"], "security": d["security"],
            "rank": d["rank"], "basel": d["basel"], "collateral": d["collateral"], "coupon_type": d["coupon_type"], "coupon": d["coupon"], "currency": d["currency"],
            "issue_date": _date(d["issue_date"]), "maturity": mat, "next_call": call, "perpetual": "Y" if perpetual else "N",
            "issued": None if d["issued"] is None else d["issued"] / 1e6, "outstanding": None if d["outstanding"] is None else d["outstanding"] / 1e6,
            "eur": None if eur is None else eur / 1e6, "size_bucket": size_bucket(size), "years": None if (perpetual or mat is None) else round((mat - today).days / 365.25, 2),
            "bucket_m": bucket_key(year_m, today.year) if active else None, "bucket_c": bucket_key(year_c, today.year) if active else None,
            "px": d["px"], "ytm": d["ytm"], "i_spread": d["i_spread"], "z_spread": d["z_spread"], "quote_date": _date(d["quote_date"]), "series": d["series"], "name": d["name"],
            "pulled_at": d["pulled_at"]})
    issues = pd.DataFrame(rows)
    texts = {"ambiguous": ("Ambiguous", "Several notes share this name. Bloomberg gives no single record. The name stands for at least 1 note."),
             "unresolved": ("Not found", "Bloomberg returned no record for this name."),
             None: ("Not loaded", "The census listed this name after the last pull of static data. The database has no static data for it yet.")}
    lst = conn.execute(f"""SELECT lei, security, description, status FROM bbg_bond_listing WHERE lei IN ({marks}) AND security <> ''
                           AND (status IN ('ambiguous', 'unresolved') OR (status IS NULL AND security NOT IN (SELECT security FROM bbg_bond)))
                           AND security NOT IN (SELECT security FROM bbg_bond WHERE lei = bbg_bond_listing.lei) ORDER BY lei, security""", leis).fetchall()
    un = []
    for lei, sec, desc, status in lst:
        if not alive(sec, today):
            continue
        coupon, mat, perp = parse_name(sec)
        label, meaning = texts.get(status, texts[None])
        un.append({"issuer": short[lei], "security": sec, "status": label, "meaning": meaning, "coupon": coupon, "maturity": mat, "perpetual": "Y" if perp else "N",
                   "bucket": bucket_key(None if perp else (mat.year if mat else None), today.year), "description": desc})
    unresolved = pd.DataFrame(un, columns=["issuer", "security", "status", "meaning", "coupon", "maturity", "perpetual", "bucket", "description"])
    meta = {"today": today, "fx_date": fx_date, "static_from": min(issues["pulled_at"].dropna(), default=None) if not issues.empty else None,
            "static_to": max(issues["pulled_at"].dropna(), default=None) if not issues.empty else None,
            "market_to": max((q for q in issues["quote_date"].dropna()), default=None) if not issues.empty else None, "banks": banks}
    return {"issues": issues.drop(columns=["pulled_at"]) if not issues.empty else issues, "unresolved": unresolved, "meta": meta, "first_year": today.year}
