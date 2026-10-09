"""Quality checks and the clean period layer for KM1 (K_61.00) and OV1 (K_60.00).

The Hub gives no unit field. The assessment of 2026-10 found these source problems:
amounts in thousands or millions, ratios in percentage points, zero placeholders, and
filings that switch scale. This script tests each column of each filing, repairs a cell only
when two independent sources agree, and removes the other bad cells.

Input:  view v_period_fact (all filings, no choice between filings yet).
Output: table dq_flag (one row for each test that fired) and table clean_period_fact
        (one row for each entity, quarter, row and measure; value is the clean value).

A repair multiplies a cell by a power of 10. Two sources must agree:
- A ratio is tested against the ratio computed from the amounts in the same column.
- An amount is tested against TREA of the same column (the ratio of the two must be plausible).
- TREA is tested against the same quarter in other filings and against the other columns.
- A cell that is off from the other columns of its filing is tested against those columns.
Cells that fail a test and cannot be repaired get the quality "quarantined". They do not
enter clean_period_fact. The next older filing that holds the quarter supplies the value.
A cell is never rescaled twice. Only the rows in AMOUNT and RATIO (and their companion rows)
are tested. All other rows of K_61.00 pass through unchanged.

Run: PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/clean_p3dh.py
"""

from __future__ import annotations

import argparse
import math
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "processed" / "p3dh.sqlite"

KM1, OV1 = "K_61.00", "K_60.00"
CORE = {"cet1": "0010", "t1": "0020", "tc": "0030", "trea": "0040", "lev_exp": "0210",
        "hqla": "0280", "netout": "0310", "asf": "0330", "rsf": "0340"}
AMOUNT = {**CORE, "trea_unfloored": "0041", "outflow": "0290", "inflow": "0300"}
RATIO = {"cet1_ratio": "0050", "t1_ratio": "0060", "tc_ratio": "0070", "lev_ratio": "0220",
         "lcr": "0320", "nsfr": "0350"}
COMPANION = {"0051": "0050", "0061": "0060", "0081": "0070"}
CAPITAL_RATIOS = (("0050", "0010"), ("0060", "0020"), ("0070", "0030"))
# Plausible range of (row value / TREA). A row outside the range is tested for a scale error.
TREA_RANGE = {
    "0010": (0.005, 3.0), "0020": (0.005, 3.0), "0030": (0.005, 3.0), "0041": (0.2, 1.3),
    "0210": (0.3, 40.0), "0280": (0.003, 8.0), "0290": (0.003, 12.0), "0300": (0.0005, 6.0),
    "0310": (0.002, 5.0), "0330": (0.03, 15.0), "0340": (0.03, 15.0),
}
KM1_LABELS = {
    "0010": r"1\. Common Equity Tier 1 \(CET1\) capital", "0020": r"2\. Tier 1 capital",
    "0030": r"3\. Total capital", "0040": r"4\. Total risk-weighted exposure amount",
    "0041": r"4a\. Total risk exposure pre-floor",
    "0050": r"5\. Common Equity Tier 1 ratio \(%\)", "0060": r"6\. Tier 1 ratio \(%\)",
    "0070": r"7\. Total capital ratio \(%\)",
    "0051": r"5b\. Common Equity Tier 1 ratio considering unfloored TREA \(%\)",
    "0061": r"6b\. Tier 1 ratio considering unfloored TREA \(%\)",
    "0081": r"7b\. Total capital ratio considering unfloored TREA \(%\)",
    "0210": r"13\. Leverage ratio total exposure measure",
    "0220": r"14\. Leverage ratio", "0280": r"15\. Total high-quality liquid assets",
    "0290": r"EU 16a\. Cash outflows - Total weighted value",
    "0300": r"EU 16b\. Cash inflows - Total weighted value",
    "0310": r"16\. Total net cash outflows", "0320": r"17\. Liquidity coverage ratio \(%\)",
    "0330": r"18\. Total available stable funding", "0340": r"19\. Total required stable funding",
    "0350": r"20\. NSFR ratio \(%\)",
}
TREA_MIN, TREA_MAX = 1e7, 5e12
CET1_MAX = 5e11
POWER_TOL = 0.06
FX_TOL = 0.08
SENTINELS = (999999.0, 999999999.0)
CAPITAL4 = ("0010", "0020", "0030", "0040")


def plaus_capital(r: float) -> bool:
    return 0.005 <= r <= 1.5


def plaus_leverage(r: float) -> bool:
    return 0.005 <= r <= 0.6


def exponent(ratio: float, powers=(2, 3, 4, 6), tol: float = POWER_TOL):
    """Return k when ratio is within tol (log10) of 10**k or 10**-k, else None."""
    if not (ratio and math.isfinite(ratio) and ratio > 0):
        return None
    lg = math.log10(ratio)
    for k in powers:
        for sign in (1, -1):
            if abs(lg - sign * k) <= tol:
                return sign * k
    return None


class Cleaner:
    """Holds the cells of one template as arrays and records every change."""

    def __init__(self, frame: pd.DataFrame):
        self.df = frame.reset_index(drop=True)
        self.val = self.df["value"].to_numpy(dtype=float).copy()
        self.raw = self.val.copy()
        self.qual = np.array(["ok"] * len(self.df), dtype=object)
        self.fac = np.ones(len(self.df))
        self.flags: list[dict] = []

    def log(self, i: int, check: str, action: str, factor: float | None = None, detail: str = ""):
        r = self.df.iloc[i]
        self.flags.append({
            "reference_date": r["reference_date"], "entity_key": r["entity_key"],
            "template_code": r["template_code"], "period_offset": int(r["period_offset"]),
            "row_code": r["row_code"], "table_code": r["table_code"], "check_name": check,
            "action": action, "factor": factor, "detail": detail})

    def live(self, i: int | None) -> bool:
        return i is not None and self.qual[i] != "quarantined" and math.isfinite(self.val[i])

    def get(self, rows: dict, code: str):
        i = rows.get(code)
        return float(self.val[i]) if self.live(i) else None

    def rescale(self, i: int, k: int, check: str):
        if self.qual[i] == "rescaled":
            self.quarantine(i, check, "second rescale of one cell refused")
            return
        self.val[i] *= 10.0 ** k
        self.fac[i] *= 10.0 ** k
        self.qual[i] = "rescaled"
        self.log(i, check, "rescale", 10.0 ** k)

    def quarantine(self, i: int, check: str, detail: str = ""):
        if self.qual[i] != "quarantined":
            self.qual[i] = "quarantined"
            self.log(i, check, "quarantine", None, detail)


def check_labels(df: pd.DataFrame) -> None:
    """The row codes used here must keep their meaning in every filing."""
    seen = df[df["row_code"].isin(KM1_LABELS)].drop_duplicates(["row_code", "row_label"])
    for r in seen.itertuples():
        label = re.sub(r"\s+", " ", r.row_label).strip()
        if not re.match(KM1_LABELS[r.row_code], label):
            raise ValueError(f"KM1 row {r.row_code} has label {label!r}; expected {KM1_LABELS[r.row_code]!r}")


def clean_km1_column(c: Cleaner, rows: dict, siblings: list) -> None:
    """Tests inside one column (one filing, one period). `siblings` are the other columns of the filing."""
    g = lambda code: c.get(rows, code)  # noqa: E731
    verified: set[str] = set()

    def sibling_ratio(code):
        vals = [float(c.val[s[code]]) for s in siblings if code in s and c.live(s[code]) and c.val[s[code]] > 0]
        me = g(code)
        if me is None or me <= 0 or len(vals) < 2:
            return None
        return me / float(np.median(vals))

    def fix_ratio(code: str, exp: int, check: str):
        c.rescale(rows[code], exp, check)
        for comp, main in COMPANION.items():
            if main == code and c.live(rows.get(comp)):
                c.rescale(rows[comp], exp, check)

    cap_cells = [c.val[rows[x]] for x in CAPITAL4 if x in rows]
    if len(cap_cells) == 4 and all(v == 0 for v in cap_cells):
        for code, i in rows.items():
            if c.live(i) and (code in CAPITAL4 or c.val[i] == 0):
                c.quarantine(i, "zero_placeholder", "CET1, Tier 1, total capital and TREA are 0")

    for code in list(CORE.values()) + list(RATIO.values()):
        i = rows.get(code)
        if i is None or not c.live(i):
            continue
        v = c.val[i]
        if abs(v) in SENTINELS:
            c.quarantine(i, "sentinel", f"value {v}")
        elif v == 0:
            c.quarantine(i, "zero_value", "0 reported for a value that cannot be 0")
        elif code in CORE.values() and v < 0:
            c.quarantine(i, "negative_amount", f"value {v}")

    trea = g("0040")
    if trea:
        votes = {}
        for rcode, acode in CAPITAL_RATIOS:
            r, a = g(rcode), g(acode)
            if r is None or a is None:
                continue
            d = a / trea
            if abs(r - d) <= max(0.0005, 0.03 * abs(d)):
                votes[rcode] = 0
                verified.add(rcode)
            else:
                votes[rcode] = exponent(r / d) if d > 0 and r > 0 else None
        breaks = Counter(k for k in votes.values() if k is not None and abs(k) in (3, 6))
        top = breaks.most_common(1)
        if top and top[0][1] >= 2:
            k = top[0][0]
            voters = [rc for rc, kk in votes.items() if kk == k]
            cet1 = g("0010")
            r_ok = all(plaus_capital(g(rc)) for rc in voters)
            s_trea, s_cet1 = sibling_ratio("0040"), sibling_ratio("0010")
            near = lambda s: s is not None and 1 / 1.6 <= s <= 1.6  # noqa: E731
            amounts_ok = TREA_MIN <= trea <= TREA_MAX and cet1 is not None and 1e5 <= cet1 <= CET1_MAX
            options = {
                "trea": r_ok and TREA_MIN <= trea * 10.0 ** -k <= TREA_MAX,
                "capital": r_ok and cet1 is not None and 1e5 <= cet1 * 10.0 ** k <= CET1_MAX
                           and TREA_MIN <= trea <= TREA_MAX,
                "ratio": (not r_ok) and amounts_ok and all(plaus_capital(g(rc) * 10.0 ** -k) for rc in voters),
            }
            if s_trea is not None and s_cet1 is not None:
                options["trea"] = options["trea"] and near(s_trea * 10.0 ** -k) and near(s_cet1)
                options["capital"] = options["capital"] and near(s_cet1 * 10.0 ** k) and near(s_trea)
                options["ratio"] = options["ratio"] and near(s_trea) and near(s_cet1)
            chosen = [name for name, ok in options.items() if ok]
            if chosen == ["trea"]:
                c.rescale(rows["0040"], -k, "capital_identity")
            elif chosen == ["capital"]:
                for a in ("0010", "0020", "0030"):
                    if g(a):
                        c.rescale(rows[a], k, "capital_identity")
            elif chosen == ["ratio"]:
                for rc in voters:
                    fix_ratio(rc, -k, "ratio_unit")
            else:
                for code in CAPITAL4:
                    if g(code) is not None:
                        c.quarantine(rows[code], "capital_identity", f"scale break 10^{k}, source unclear")
        else:
            for rcode, acode in CAPITAL_RATIOS:
                k = votes.get(rcode)
                r = g(rcode)
                if k is None or k == 0 or r is None:
                    continue
                if abs(k) in (3, 6) and plaus_capital(r):
                    a = g(acode)
                    if a is not None and 1e5 <= a * 10.0 ** k <= CET1_MAX:
                        c.rescale(rows[acode], k, "capital_identity")
                    else:
                        c.quarantine(rows[rcode], "capital_identity", "amount and ratio disagree")
                elif abs(k) in (2, 3, 4) and plaus_capital(r * 10.0 ** -k):
                    fix_ratio(rcode, -k, "ratio_unit")
                elif not plaus_capital(r):
                    c.quarantine(rows[rcode], "ratio_unit", f"value {r} does not fit capital / TREA")
    for rcode, _ in CAPITAL_RATIOS:
        i = rows.get(rcode)
        if c.live(i) and c.qual[i] == "ok" and rcode not in verified and c.val[i] > 1.5:
            c.quarantine(i, "ratio_unverified", f"value {c.val[i]} above 1.5 and no amount confirms it")

    lev, t1, r_l = g("0210"), g("0020"), g("0220")
    if lev and t1 and r_l and r_l > 0:
        d = t1 / lev
        if abs(r_l - d) <= max(0.0005, 0.03 * d):
            verified.add("0220")
        else:
            k = exponent(r_l / d)
            if k is not None and plaus_leverage(r_l) and abs(k) in (3, 6):
                c.rescale(rows["0210"], -k, "leverage_identity")
            elif k is not None and not plaus_leverage(r_l) and abs(k) in (2, 3, 4) \
                    and plaus_leverage(r_l * 10.0 ** -k):
                fix_ratio("0220", -k, "ratio_unit")
    r_l = g("0220")
    if r_l is not None and r_l > 0.6 and c.qual[rows["0220"]] == "ok" and "0220" not in verified:
        c.quarantine(rows["0220"], "ratio_unverified", f"leverage ratio {r_l} above 0.6")

    asf, rsf, nsfr = g("0330"), g("0340"), g("0350")
    if asf and rsf and nsfr and nsfr > 0:
        d = asf / rsf
        if abs(nsfr - d) <= max(0.01, 0.03 * d):
            verified.add("0350")
        else:
            k = exponent(nsfr / d)
            if k == 2 or k == -2:
                fix_ratio("0350", -k, "ratio_unit")
            elif k is not None and abs(k) in (3, 6):
                for code in ("0330", "0340", "0350"):
                    c.quarantine(rows[code], "nsfr_identity", f"ASF / RSF differs from NSFR by 10^{k}")

    hqla, net, lcr = g("0280"), g("0310"), g("0320")
    if hqla and net and lcr and lcr > 0:
        d = hqla / net
        if 0.6 <= lcr / d <= 1.7:
            verified.add("0320")
        else:
            k = exponent(lcr / d, tol=0.15)
            if k == 2 or k == -2:
                fix_ratio("0320", -k, "ratio_unit")
            elif k is not None and abs(k) in (3, 6):
                for code in ("0280", "0310", "0320"):
                    c.quarantine(rows[code], "lcr_identity", f"HQLA / outflows differs from LCR by 10^{k}")
    for code in ("0320", "0350"):
        i = rows.get(code)
        if c.live(i) and c.qual[i] == "ok" and code not in verified and c.val[i] > 1000:
            c.quarantine(i, "ratio_unverified", f"value {c.val[i]} is above 1000 and no amount confirms it")


def clean_km1_across_filings(c: Cleaner, cols_by_filing: dict) -> None:
    """TREA of one quarter across filings, then the absolute size test."""
    by_period = defaultdict(list)
    trea_of = {}
    for (ent, ref), cols in cols_by_filing.items():
        for po, rows in cols.items():
            t = c.get(rows, "0040")
            if t:
                trea_of[(ent, ref, po)] = t
                by_period[(ent, c.df.at[rows["0040"], "period_end"])].append((ref, po, t))
    votes = defaultdict(list)
    for (ent, _), items in by_period.items():
        for a in items:
            for b in items:
                if a[0] == b[0] or a[2] <= b[2]:
                    continue
                k = exponent(a[2] / b[2], powers=(3, 6), tol=FX_TOL)
                if k is None:
                    continue
                if b[2] * 10.0 ** k <= TREA_MAX:
                    votes[(ent, b[0], b[1])].append(k)
                elif a[2] >= TREA_MAX:
                    votes[(ent, a[0], a[1])].append(-k)
    exps = {key: Counter(ks).most_common(1)[0][0] for key, ks in votes.items()}
    applied = dict(exps)
    # a vote on one column applies to the other columns of that filing on the same scale
    for (ent, ref), cols in cols_by_filing.items():
        voted = {po: exps[(ent, ref, po)] for po in cols if (ent, ref, po) in exps}
        if not voted:
            continue
        e = Counter(voted.values()).most_common(1)[0][0]
        base = [trea_of[(ent, ref, po)] for po in voted if (ent, ref, po) in trea_of]
        if not base:
            continue
        ref_val = float(np.median(base))
        for po in cols:
            t = trea_of.get((ent, ref, po))
            if (ent, ref, po) not in applied and t and 1 / 3 <= t / ref_val <= 3:
                applied[(ent, ref, po)] = e
    for (ent, ref, po), e in applied.items():
        i = cols_by_filing[(ent, ref)][po]["0040"]
        if c.live(i):
            c.rescale(i, e, "cross_filing")
    for cols in cols_by_filing.values():
        for rows in cols.values():
            t = c.get(rows, "0040")
            if t is not None and 0 < t < TREA_MIN:
                for code in AMOUNT.values():
                    i = rows.get(code)
                    if c.live(i):
                        c.quarantine(i, "suspect_scale", f"TREA {t:.4g} is below {TREA_MIN:.0e}")


def clean_km1_trea_ratio(c: Cleaner, rows: dict) -> None:
    """Each amount must be plausible against TREA of its own column."""
    trea = c.get(rows, "0040")
    if not trea or not (TREA_MIN <= trea <= TREA_MAX):
        return
    deviating, tested = {}, 0
    for code, (lo, hi) in TREA_RANGE.items():
        v = c.get(rows, code)
        if v is None or v <= 0:
            continue
        tested += 1
        x = v / trea
        if lo <= x <= hi:
            continue
        deviating[code] = [e for e in (3, 6, -3, -6) if lo <= x * 10.0 ** e <= hi]
    if not deviating:
        return
    if tested >= 3 and len(deviating) == tested:
        common = set.intersection(*[set(f) for f in deviating.values()])
        if len(common) == 1:
            e = -next(iter(common))
            if TREA_MIN <= trea * 10.0 ** e <= TREA_MAX:
                c.rescale(rows["0040"], e, "trea_ratio")
                return
    for code, fits in deviating.items():
        i = rows[code]
        if len(fits) == 1:
            c.rescale(i, fits[0], "trea_ratio")
        else:
            c.quarantine(i, "trea_ratio", f"value / TREA = {c.val[i] / trea:.3g}, no single scale fits")


def clean_km1_filing(c: Cleaner, cols: dict) -> None:
    """One column of a row that is 10^3 or 10^6 off while at least 3 other columns agree."""
    for code in AMOUNT.values():
        items = [(po, rows[code]) for po, rows in cols.items() if code in rows and c.live(rows[code])
                 and c.val[rows[code]] > 0]
        if len(items) < 4:
            continue
        for po, i in items:
            if not c.live(i):
                continue
            others = [c.val[j] for _, j in items if j != i and c.live(j)]
            if len(others) < 3:
                continue
            med = float(np.median(others))
            if not all(1 / 1.6 <= o / med <= 1.6 for o in others):
                continue
            lg = math.log10(c.val[i] / med)
            if abs(lg) < 2.5:
                continue
            e = 3 * round(lg / 3)
            if abs(e) in (3, 6) and abs(lg - e) <= 0.12 and 1 / 1.6 <= c.val[i] * 10.0 ** -e / med <= 1.6:
                c.rescale(i, -e, "filing_spread")
            else:
                c.quarantine(i, "filing_spread", f"value is 10^{lg:.1f} of the median of the other columns")


def clean_ov1(c: Cleaner, cols: dict, km1_trea: dict) -> None:
    """OV1: zero total, and a column that disagrees with KM1 TREA by 10^3 or 10^6."""
    for (ent, ref, per), rows in cols.items():
        total_cells = [i for (rc, _, mc), i in rows.items() if rc == "0380" and c.live(i)]
        total = [c.val[i] for (rc, _, mc), i in rows.items() if rc == "0380" and mc == 10 and c.live(i)]
        credit = [c.val[i] for (rc, _, mc), i in rows.items() if rc == "0010" and mc == 10 and c.live(i)]
        if total and max(total) == 0 and credit and max(credit) > 0:
            for i in total_cells:
                c.quarantine(i, "zero_total", "OV1 total is 0 while credit risk is above 0")
            total = []
        t = max(total) if total else None
        trea = km1_trea.get((ent, ref, per))
        amount_cells = [i for (_, tb, _), i in rows.items() if tb in ("K_60.00.a", "K_60.00.c")]
        if t and trea:
            k = exponent(t / trea, powers=(3, 6))
            if k is not None:
                for i in amount_cells:
                    if c.live(i):
                        c.rescale(i, -k, "ov1_vs_km1")
        elif t and t < TREA_MIN:
            for i in amount_cells:
                if c.live(i):
                    c.quarantine(i, "suspect_scale", f"OV1 total {t:.4g} is below {TREA_MIN:.0e}")


def load(conn: sqlite3.Connection, template: str) -> pd.DataFrame:
    return pd.read_sql_query(
        """SELECT entity_key, entity_name, country, reference_date, template_code, table_code,
                  period_offset, period_end, row_code, row_label, column_label, measure_col,
                  key_descriptor, sheet, value
           FROM v_period_fact WHERE template_code = ? AND value IS NOT NULL
           ORDER BY entity_key, reference_date, period_offset, row_code, table_code""",
        conn, params=(template,))


def run(conn: sqlite3.Connection):
    km = load(conn, KM1)
    check_labels(km)
    ck = Cleaner(km)
    cols_by_filing: dict = defaultdict(lambda: defaultdict(dict))
    for i, r in enumerate(ck.df[["entity_key", "reference_date", "period_offset", "row_code"]]
                          .itertuples(index=False)):
        rows = cols_by_filing[(r.entity_key, r.reference_date)][r.period_offset]
        if r.row_code in rows:
            raise ValueError(f"duplicate KM1 cell {r}")
        rows[r.row_code] = i
    for filing in cols_by_filing.values():
        for rows in filing.values():
            clean_km1_column(ck, rows, [r for r in filing.values() if r is not rows])
    clean_km1_across_filings(ck, cols_by_filing)
    for filing in cols_by_filing.values():
        for rows in filing.values():
            clean_km1_trea_ratio(ck, rows)
    for filing in cols_by_filing.values():
        clean_km1_filing(ck, filing)

    km1_trea = {}
    for (ent, ref), cols in cols_by_filing.items():
        rows = cols.get(0)
        if rows is not None:
            t = ck.get(rows, "0040")
            if t:
                km1_trea[(ent, ref, ck.df.at[rows["0040"], "period_end"])] = t

    ov = load(conn, OV1)
    co = Cleaner(ov)
    ov_cols: dict = defaultdict(dict)
    for i, r in enumerate(co.df[["entity_key", "reference_date", "period_end", "row_code", "table_code",
                                 "measure_col"]].itertuples(index=False)):
        ov_cols[(r.entity_key, r.reference_date, r.period_end)][(r.row_code, r.table_code, r.measure_col)] = i
    clean_ov1(co, ov_cols, km1_trea)
    return ck, co


def assemble(ck: Cleaner, co: Cleaner) -> tuple[pd.DataFrame, pd.DataFrame]:
    parts = []
    for cl in (ck, co):
        df = cl.df.copy()
        df["value_raw"] = cl.raw
        df["value"] = cl.val
        df["quality"] = cl.qual
        df["factor"] = cl.fac
        parts.append(df)
    full = pd.concat(parts, ignore_index=True)
    keep = full[full["quality"] != "quarantined"].copy()
    keep = keep.sort_values(["reference_date", "table_code"], ascending=[False, True])
    key = ["entity_key", "template_code", "period_end", "row_code", "key_descriptor", "sheet", "measure_col"]
    clean = keep.drop_duplicates(key, keep="first").sort_values(key).reset_index(drop=True)
    flags = pd.DataFrame(ck.flags + co.flags, columns=[
        "reference_date", "entity_key", "template_code", "period_offset", "row_code", "table_code",
        "check_name", "action", "factor", "detail"])
    return clean, flags


def population_report(km: pd.DataFrame) -> None:
    """Entities with KM1 column T in each filing, and how many of the previous filing are absent.

    An entity that is absent has no data. It does not have the value 0. A large drop between two
    quarters means that the later filing is partial or that many banks report less often.
    """
    t = km[km["period_offset"] == 0].groupby("reference_date")["entity_key"].agg(set)
    prev = None
    print("\nKM1 entities by filing:")
    for ref, keys in t.items():
        gone = f"{len(prev - keys)} of the previous filing absent" if prev is not None else ""
        print(f"  {ref}: {len(keys):4d} entities  {gone}")
        prev = keys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--dry-run", action="store_true", help="Print the summary and write nothing")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    ck, co = run(conn)
    clean, flags = assemble(ck, co)
    if len(clean) and clean.duplicated(["entity_key", "template_code", "period_end", "row_code",
                                        "key_descriptor", "sheet", "measure_col"]).any():
        raise RuntimeError("clean_period_fact has duplicate keys")

    print(f"cells: {len(ck.df) + len(co.df):,} | clean rows: {len(clean):,} | flags: {len(flags):,}")
    if len(flags):
        summary = (flags.groupby(["template_code", "check_name", "action"]).size()
                   .rename("n").reset_index())
        print(summary.to_string(index=False))
    population_report(ck.df)
    if args.dry_run:
        return 0
    with conn:
        clean.to_sql("clean_period_fact", conn, if_exists="replace", index=False)
        flags.to_sql("dq_flag", conn, if_exists="replace", index=False)
        conn.execute("CREATE INDEX idx_clean_lookup ON clean_period_fact(template_code, entity_key, period_end)")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
