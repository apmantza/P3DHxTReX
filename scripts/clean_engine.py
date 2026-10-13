"""Generic clean engine: unit, zero, and ratio tests for every template that has amounts.

Run after scripts/clean_p3dh.py, scripts/classify_p3dh.py, and scripts/clean_templates.py.
The engine reads no template-specific rule. It finds the rule in the data, for each run. The
audit of 2026-10-13 showed that a size anchor alone is not enough (about 14% of the first repairs were
wrong), so each decision now passes three stages.

Stage A, one template at a time (candidate):
1. Cell type. A cell is an amount, a ratio, or other. A label with a non-monetary word (tonnes, CO2,
   number of, years) is never an amount. An amount has a median of at least EUR 2,000 (and above 1.5).
2. Size of a filing. The 90th percentile of its non-zero amounts (the median for 2 or 3 cells). A filing
   with fewer than 2 amount cells has no size.
3. Anchor. The size is compared with a clean quantity of the same bank and period: total assets,
   leverage exposure, TREA, Tier 1, CET1, OV1 RWEA by risk type, or the size of an earlier template.
   Each anchor has a main mode of log10(size / anchor) for filings in EUR. Filings 3 or 6 units away are
   unit-shifted (factors 1e3 and 1e6 only).
4. Vote. The filings of one bank with sizes that agree form a cluster with one unit. Each anchor
   votes once for the cluster. A tight base anchor has weight 2, other anchors weight 1. A position
   between two modes counts as a vote for no shift. No unit error is the default. A shift needs a
   weight of at least 3, one tight base anchor, 1.5 times the weight of no shift, and a tight weight
   that is not below the tight weight of no shift. Votes that conflict remove the cluster. Chain
   anchors (the size of another template) come only from unshifted filings and are built at the end
   of a round, so the result does not depend on the order of the templates.

Stage B, one filing at a time (reconciliation across templates):
5. Identity. The same non-round raw figure in two templates of one filing has one unit. Two templates
   that share at least 2 such figures (or 1 figure above EUR 1 million with KM1 or OV1) form a group.
   KM1 and OV1 have an authoritative unit (table clean_filing_unit). A group takes the unit with at
   least twice the weight of the other. A conflict removes the group.
6. Support. A shift of a template with no identity partner stands only if the KM1 unit of the filing
   agrees (within half a decade, and then takes the exact KM1 factor, for example the BGN peg) or at
   least 3 other templates of the filing have the same shift. Otherwise the filing is removed.

Stage C, bounds:
7. A shifted filing with a maximum above 3 times total assets (or leverage exposure) is not shifted.
   A cell above 1,000 times total assets is reverted to its raw value or removed.

Other rules: a ratio filing in percentage points is found by the median of its ratio cells against the
population median of the same cells (not by a fixed limit). An all-zero filing is removed only when the
same bank has non-zero amounts for the template in another filing. A filing without an anchor is removed
only if its own KM1 was removed (scale_unresolved); otherwise it stays as unverified.

New data: the engine always tests again. It never assumes that a bank repeats its unit. The table
clean_release_diff lists every filing whose decision changed since the last run, and clean_run_log keeps
the calibration of each template.

Quality values: ok, ok_wide, ok_history, ok_tie, rescaled, rescaled_tie, rescaled_nb, cell_reverted, converted, suspect,
unverified, untested, quarantined.

Run: PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/clean_engine.py
"""

from __future__ import annotations

import argparse
import math
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import clean_templates  # noqa: E402

PROJECT_ROOT = SCRIPTS.parent
DEFAULT_DB = PROJECT_ROOT / "data" / "processed" / "p3dh.sqlite"

HANDLED_ELSEWHERE = {"K_61.00", "K_60.00", "K_68.00", "K_20.01", "K_20.02", "K_20.03"}
AUTHORITY = {"K_61.00", "K_60.00"}
NO_SELF_ANCHOR = {"K_70.00": {"TA"}, "K_66.02": {"TA"}, "K_64.01": {"TA"}, "K_71.00": {"LEV"}, "K_72.00": {"LEV"}}
MODE_TOL, WIDE_TOL = 0.75, 1.25
MAX_STEPS = 2  # factors 1e-6 to 1e6
MIN_GROUPS, MIN_SHARE, MAX_SPREAD = 10, 0.70, 0.35
CHAIN_MIN_GROUPS = 25
SECONDARY_SHARE, SECONDARY_SPREAD = 0.60, 0.55
AMOUNT_MEDIAN, SMALL_AMOUNT = 2e4, 2e3
TIE_MIN = 2000.0         # a tie figure is at least EUR 2,000 and not a round thousand
FILING_BOUND, CELL_BOUND, RAW_CELL_LIMIT = 3.0, 1000.0, 20.0
KEYS = ["entity_key", "reference_date"]
EXCLUDED_COLUMNS = {("K_41.00", "0090"), ("K_41.00", "0100")}  # financed emissions in tonnes of CO2e
NON_MONETARY = re.compile(
    r"tonne|tco2|co2|greenhouse|kwh|number of|no\. of|headcount|\bfte\b|\byears?\b|\bdays?\b|average maturity|"
    r"residual maturity|weighted maturity|\(%\)|percentage|per cent|obligors", re.I)
SQL = """SELECT e.entity_key, f.entity_id, f.reference_date, f.seq, f.cell_code, f.row_code, f.column_code,
                f.row_label, f.column_label, f.sheet, f.key_descriptor, f.value
         FROM fact f JOIN entity e ON e.entity_id = f.entity_id
         WHERE f.template_code = ? AND f.value IS NOT NULL"""
FLAG_COLUMNS = ["reference_date", "entity_key", "template_code", "period_offset", "row_code", "table_code",
                "check_name", "action", "factor", "detail"]


# ----------------------------------------------------------------------------- cell typing and sizes

def assign_kind(df: pd.DataFrame, tpl: str) -> pd.Series:
    """amount, ratio, or other for each cell, from the values of all banks."""
    a = df["value"].abs()
    nz = df.loc[a > 0, ["row_code", "column_code"]].assign(a=a[a > 0])

    def table(keys):
        g = nz.groupby(keys)["a"]
        return pd.DataFrame({"n": g.size(), "p50": g.median(), "p90": g.quantile(0.9)})

    def kind(p50, p90):
        return np.where(p50 >= AMOUNT_MEDIAN, "amount",
                        np.where((p50 >= SMALL_AMOUNT) & (p90 > 1.5), "amount", np.where(p90 <= 1.5, "ratio", "other")))

    cell, col = table(["row_code", "column_code"]), table(["column_code"])
    cell["kind"] = kind(cell["p50"], cell["p90"])
    col["kind"] = kind(col["p50"], col["p90"])
    base = df[["row_code", "column_code"]]
    own = base.merge(cell.reset_index()[["row_code", "column_code", "n", "kind"]], on=["row_code", "column_code"], how="left")
    colk = base.merge(col.reset_index()[["column_code", "kind"]], on="column_code", how="left")["kind"]
    out = np.where((own["n"].fillna(0) < 8).to_numpy() | own["kind"].isna().to_numpy(),
                   colk.fillna("other").to_numpy(), own["kind"].to_numpy())
    labs = df.drop_duplicates(["row_code", "column_code"])[["row_code", "column_code", "row_label", "column_label"]].copy()
    labs["nonmon"] = (labs["row_label"].fillna("") + " " + labs["column_label"].fillna("")).str.contains(NON_MONETARY)
    labs["excl"] = [(tpl, c) in EXCLUDED_COLUMNS for c in labs["column_code"]]
    flag = base.merge(labs[["row_code", "column_code", "nonmon", "excl"]], on=["row_code", "column_code"], how="left")
    bad = (flag["nonmon"].fillna(False) | flag["excl"].fillna(False)).to_numpy()
    return pd.Series(np.where(bad, "other", out), index=df.index)


def group_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Size of each filing. 90th percentile of the non-zero amounts; median for 2 or 3 cells; none for 1 cell."""
    am = df[(df["kind"] == "amount") & (df["value"] != 0)]
    g = am.assign(a=am["value"].abs()).groupby(KEYS)["a"]
    stat = pd.DataFrame({"n": g.size(), "mx": g.max(), "p90": g.quantile(0.9), "med": g.median()})
    stat["s"] = np.where(stat["n"] >= 4, stat["p90"], np.where(stat["n"] >= 2, stat["med"], np.nan))
    allcells = df[df["kind"] == "amount"].groupby(KEYS)["value"].agg(n_all="size", n_zero=lambda s: int((s == 0).sum()))
    return stat.join(allcells, how="outer")


def tie_key(v: pd.Series):
    """Integer key of a figure, and a flag for non-round figures. Figures of EUR 1 million or more match to the EUR."""
    big = (v >= 1e6).to_numpy()
    key = np.where(big, v.round(), (v * 100).round()).astype("int64")
    nonround = np.where(big, key % 1000 != 0, key % 100000 != 0)
    return key * 2 + big.astype("int64"), nonround


def tie_values(df: pd.DataFrame, tpl: str) -> pd.DataFrame:
    """Non-round amounts of a template, for the identity test."""
    am = df[df["kind"] == "amount"]
    v = am["value"].abs()
    keep = (v >= TIE_MIN).to_numpy()
    am, v = am[keep], v[keep]
    k, nonround = tie_key(v)
    out = pd.DataFrame({"entity_key": am["entity_key"].to_numpy(), "reference_date": am["reference_date"].to_numpy(),
                        "tpl": tpl, "k": k, "veur": v.to_numpy()})
    return out[nonround].drop_duplicates(["entity_key", "reference_date", "tpl", "k"])


def tie_pairs(parts: list[pd.DataFrame]) -> pd.DataFrame:
    """Pairs of templates that share figures in one filing."""
    tv = pd.concat(parts, ignore_index=True)
    k = ["entity_key", "reference_date", "k"]
    tv = tv[tv.groupby(k)["tpl"].transform("nunique") >= 2]
    m = tv.merge(tv, on=k, suffixes=("_a", "_b"))
    m = m[m["tpl_a"] < m["tpl_b"]]
    return m.groupby(["entity_key", "reference_date", "tpl_a", "tpl_b"]).agg(n=("k", "nunique"), vmax=("veur_a", "max")).reset_index()


def authority_evidence(parts: list[pd.DataFrame], cells: pd.DataFrame) -> pd.DataFrame:
    """Figures of a template that are identical to a KM1 or OV1 cell of the same filing, with the unit of that cell."""
    cu = cells[cells["veur"] >= TIE_MIN].copy()
    k, nonround = tie_key(cu["veur"])
    cu = cu.assign(k=k)[nonround].drop_duplicates(["entity_key", "reference_date", "k", "lf"])
    tv = pd.concat(parts, ignore_index=True)
    m = tv.merge(cu[["entity_key", "reference_date", "k", "lf"]], on=["entity_key", "reference_date", "k"])
    return m.groupby(["entity_key", "reference_date", "tpl", "lf"]).agg(n=("k", "nunique"), vmax=("veur", "max")).reset_index()


# ----------------------------------------------------------------------------- stage A

def calibrate(x: np.ndarray):
    """Main mode of log10(size / anchor). Returns a dict or None."""
    n = len(x)
    if n < MIN_GROUPS:
        return None
    best_c, best_cnt = 0.0, -1
    for c in np.arange(-1.5, 1.5, 0.05):
        cnt = int((np.abs(((x - c + 1.5) % 3) - 1.5) <= 0.3).sum())
        if cnt > best_cnt:
            best_c, best_cnt = c, cnt
    ks = np.round((x - best_c) / 3).astype(int)
    inside = np.abs(x - (best_c + 3 * ks)) <= MODE_TOL
    if not inside.any():
        return None
    vals, counts = np.unique(ks[inside], return_counts=True)
    main = x[inside & (ks == vals[counts.argmax()])]
    m = float(np.median(main))
    window = x[np.abs(x - m) <= 1.5]
    spread = float(1.4826 * np.median(np.abs(window - np.median(window))))
    share = len(main) / n
    score = share * (1 - min(1.0, spread / 0.5))
    return {"m": m, "spread": spread, "share": share, "score": score, "n": n,
            "ok": share >= MIN_SHARE and spread <= MAX_SPREAD,
            "secondary": share >= SECONDARY_SHARE and spread <= SECONDARY_SPREAD}


def load_base_anchors(conn: sqlite3.Connection):
    km = pd.read_sql_query(
        """SELECT entity_key, period_end AS reference_date, row_code, value FROM clean_period_fact
           WHERE template_code = 'K_61.00' AND measure_col = 10 AND row_code IN ('0010', '0020', '0040', '0210') AND value > 0""", conn)
    a = km.pivot_table(index=KEYS, columns="row_code", values="value", aggfunc="first").rename(
        columns={"0010": "CET1", "0020": "T1", "0040": "TREA", "0210": "LEV"})
    ov = pd.read_sql_query(
        """SELECT entity_key, period_end AS reference_date, row_code, value FROM clean_period_fact
           WHERE template_code = 'K_60.00' AND measure_col = 10
             AND row_code IN ('0010', '0070', '0120', '0210', '0260', '0320') AND value > 0""", conn)
    a = a.join(ov.pivot_table(index=KEYS, columns="row_code", values="value", aggfunc="first").rename(
        columns={"0010": "OV1_CREDIT", "0070": "OV1_CCR", "0120": "OV1_CVA", "0210": "OV1_SEC", "0260": "OV1_MKT",
                 "0320": "OV1_OPRISK"}), how="outer")
    ta = pd.read_sql_query("SELECT entity_key, period_end AS reference_date, total_assets_eur AS TA FROM entity_assets "
                           "WHERE total_assets_eur > 0", conn)
    return a.join(ta.set_index(KEYS), how="outer")


def load_units(conn: sqlite3.Connection):
    u = pd.read_sql_query("SELECT * FROM clean_filing_unit", conn)
    auth = {(r.entity_key, r.reference_date, r.template_code): float(r.factor) for r in u.itertuples() if pd.notna(r.factor)}
    km_failed = {(r.entity_key, r.reference_date) for r in u.itertuples() if r.template_code == "K_61.00" and pd.isna(r.factor)}
    return auth, km_failed


def decide_quality(x, m):
    n = round((x - m) / 3)
    r = x - m - 3 * n
    return n, r


def evaluate(tpl: str, stat: pd.DataFrame, anchors: dict, km_failed: set):
    """Calibrate a template against every anchor and return (summary, candidates)."""
    s = stat["s"].dropna()
    s = s[s > 0]
    if len(s) == 0:
        return {"status": "no_amounts", "note": "the template has no amount cells (ratios, counts, or text only)"}, None
    if len(s) < MIN_GROUPS:
        return {"status": "too_few", "n_groups": len(s), "note": f"only {len(s)} filings with amounts (needs {MIN_GROUPS})"}, None
    cands = []
    for name, ser in anchors.items():
        if name in NO_SELF_ANCHOR.get(tpl, ()) or name == f"S:{tpl}":
            continue
        a = ser.reindex(s.index)
        ok = a.notna() & (a > 0)
        if ok.sum() < MIN_GROUPS:
            continue
        cal = calibrate((np.log10(s[ok]) - np.log10(a[ok])).to_numpy())
        if cal:
            cands.append((name, cal))
    if not cands:
        return {"status": "no_anchor", "note": "no anchor with enough filings"}, None
    cands.sort(key=lambda t: (-t[1]["score"], t[0]))
    best_name, best = cands[0]
    summary = {"anchor": best_name, "score": best["score"], "share_main": best["share"], "spread": best["spread"],
               "mode_center": best["m"], "n_groups": len(s), "status": "ok" if best["ok"] else "weak"}
    if not best["ok"]:
        summary["note"] = (f"best anchor {best_name}: {best['share']:.0%} of filings in the main mode, spread {best['spread']:.2f}; "
                           f"needs at least {MIN_SHARE:.0%} and at most {MAX_SPREAD}")
        return summary, None
    tight_tier = [(n, c) for n, c in cands if c["ok"] and c["score"] >= 0.5 * best["score"]]
    usable = tight_tier + [(n, c) for n, c in cands if (n, c) not in tight_tier and c["secondary"]]
    summary["n_anchors"] = len(usable)
    names = [n for n, _ in usable]
    chain = [n.startswith("S:") for n in names]
    tight_base = [(n, c) in tight_tier and not ch for (n, c), ch in zip(usable, chain)]
    weight = [1 if ch else (2 if tb else 1) for ch, tb in zip(chain, tight_base)]

    idx = stat.index
    n_all = len(idx)
    sv = stat["s"].astype(float).to_numpy()
    ok_pos = np.isfinite(sv) & (sv > 0)
    votes: list[dict] = [dict() for _ in range(n_all)]  # position -> {anchor j: (n, exact?)}
    has_anchor = np.zeros(n_all, bool)
    x_first = np.full(n_all, np.nan)
    for j, (name, cal) in enumerate(usable):
        a = anchors[name].reindex(idx).astype(float).to_numpy()
        use = np.isfinite(a) & (a > 0) & ok_pos
        x = np.full(n_all, np.nan)
        x[use] = np.log10(sv[use]) - np.log10(a[use])
        for i in np.where(use)[0]:
            has_anchor[i] = True
            if np.isnan(x_first[i]):
                x_first[i] = x[i]
            n_j, r = decide_quality(x[i], cal["m"])
            if abs(n_j) <= MAX_STEPS and abs(r) <= MODE_TOL:
                votes[i][j] = (int(n_j), True)
            elif n_j == 0 and abs(r) <= WIDE_TOL:
                votes[i][j] = (0, False)

    parent = list(range(n_all))

    def find(p):
        while parent[p] != p:
            parent[p] = parent[parent[p]]
            p = parent[p]
        return p

    by_entity: dict = defaultdict(list)
    for pos, key in enumerate(idx):
        if ok_pos[pos]:
            by_entity[key[0]].append(pos)
    for members in by_entity.values():
        for p in members:
            for q in members:
                if p < q and abs(math.log10(sv[p]) - math.log10(sv[q])) <= MODE_TOL:
                    parent[find(p)] = find(q)
    clusters: dict = defaultdict(list)
    for pos in range(n_all):
        if ok_pos[pos]:
            clusters[find(pos)].append(pos)

    verdict: dict = {}
    for root, members in clusters.items():
        tally: dict = defaultdict(float)
        tight: dict = defaultdict(float)
        voters = []
        for j in range(len(usable)):
            vs = [votes[p][j] for p in members if j in votes[p]]
            if not vs:
                continue
            cnt = Counter(v[0] for v in vs)
            top = max(cnt.values())
            choices = [n for n, c in cnt.items() if c == top]
            n_choice = 0 if 0 in choices else min(choices, key=abs)
            exact = any(v[1] for v in vs if v[0] == n_choice)
            w = weight[j] if exact else 1
            tally[n_choice] += w
            if tight_base[j] and exact:
                tight[n_choice] += w
            voters.append((names[j], n_choice, w))
        detail = "voters " + " ".join(f"{nm}({n:+d})" for nm, n, _ in voters)
        w0, t0 = tally.get(0, 0.0), tight.get(0, 0.0)
        shifts = {n: w for n, w in tally.items() if n != 0}
        if not tally:
            verdict[root] = ("none" if any(has_anchor[p] for p in members) else "pending", 0, detail)
        elif not shifts:
            verdict[root] = ("accept", 0, detail)
        else:
            n_best, w_best = max(shifts.items(), key=lambda kv: (kv[1], -abs(kv[0])))
            rivals = [w for n, w in shifts.items() if n != n_best]
            if rivals and max(rivals) * 1.5 > w_best:
                verdict[root] = ("conflict", 0, detail)
            elif w_best >= 3 and w_best >= 1.5 * w0 and tight.get(n_best, 0) >= 2 and tight.get(n_best, 0) >= t0:
                verdict[root] = ("shift", n_best, detail)
            elif w0 >= w_best:
                verdict[root] = ("accept", 0, detail)
            else:
                verdict[root] = ("unconfirmed", n_best, detail)

    cols = ["factor", "quality", "check", "anchor", "detail", "tight"]
    rows = {}
    good_abs = []
    for i, key in enumerate(idx):
        if not ok_pos[i]:
            continue
        kind, n_best, detail = verdict[find(i)]
        own = votes[i]
        if kind == "pending":
            rows[key] = [np.nan, "pending", "", "", "", False]
        elif kind == "none":
            rows[key] = [np.nan, "quarantined", "scale_ambiguous", best_name, detail, False]
        elif kind == "accept":
            if any(v == (0, True) for v in own.values()):
                q = "ok"
            elif own:
                q = "ok_wide"
            else:
                q = "ok_history"
            rows[key] = [1.0, q, "", "", detail, False]
            good_abs.append(math.log10(sv[i]))
        elif kind == "shift":
            f = 10.0 ** (-3 * n_best)
            rows[key] = [f, "rescaled", "scale_vs_anchor", best_name, detail, True]
            good_abs.append(math.log10(sv[i] * f))
        else:
            rows[key] = [np.nan, "quarantined", "scale_conflict" if kind == "conflict" else "scale_unconfirmed", best_name, detail, False]
    dec = pd.DataFrame.from_dict(rows, orient="index", columns=cols)
    dec.index = pd.MultiIndex.from_tuples(dec.index, names=KEYS)
    lo, hi = (np.quantile(good_abs, 0.01) - 0.5, np.quantile(good_abs, 0.99) + 0.5) if len(good_abs) > 10 else (-np.inf, np.inf)
    for key in dec.index[dec["quality"] == "pending"]:
        val = math.log10(float(stat.at[key, "s"]))
        if key in km_failed:
            dec.loc[key, ["factor", "quality", "check"]] = [np.nan, "quarantined", "scale_unresolved"]
        elif lo <= val <= hi:
            dec.loc[key, ["factor", "quality", "check"]] = [1.0, "unverified", ""]
        else:
            dec.loc[key, ["factor", "quality", "check"]] = [np.nan, "quarantined", "implausible_size"]
    return summary, dec


# ----------------------------------------------------------------------------- stages B and C

def weight_of(q: str, tight: bool) -> float:
    if q == "rescaled":
        return 2.0 if tight else 1.0
    return {"ok": 2.0, "ok_wide": 1.0, "ok_history": 1.0, "unverified": 0.5}.get(q, 0.0)


def reconcile(decisions: dict, stats: dict, pairs: pd.DataFrame, ev: pd.DataFrame, auth: dict, ta_map: dict):
    """Stage B and C. Changes the decision tables in place. Returns counts for the log."""
    state: dict = defaultdict(dict)  # (ent, ref) -> {tpl: [factor, quality, check, detail, tight]}
    for tpl, dec in decisions.items():
        for key, r in zip(dec.index, dec[["factor", "quality", "check", "detail", "tight"]].itertuples(index=False)):
            state[key][tpl] = [r.factor, r.quality, r.check, r.detail, bool(r.tight)]
    ev_map: dict = defaultdict(lambda: defaultdict(dict))
    for r in ev.itertuples():
        if r.n >= 2 or r.vmax >= 1e4:
            ev_map[(r.entity_key, r.reference_date)][r.tpl][float(r.lf)] = int(r.n)
    edges: dict = defaultdict(list)
    for r in pairs.itertuples():
        if r.n >= 3 or (r.n >= 2 and r.vmax >= 1e5) or (r.n >= 1 and r.vmax >= 1e6):
            edges[(r.entity_key, r.reference_date)].append((r.tpl_a, r.tpl_b))
    changed = Counter()
    touched: set = set()  # (template, filing) changed by an identity decision

    for key in sorted(set(state) | set(edges) | set(ev_map)):
        ent, ref = key
        nodes = state.get(key, {})
        forced: dict = {}
        for t, evs in ev_map.get(key, {}).items():
            if t not in nodes:
                continue
            if len(evs) == 1:
                forced[t] = 10.0 ** next(iter(evs))
            else:
                nodes[t][:4] = [np.nan, "quarantined", "identity_conflict",
                                f"identical figures match KM1 or OV1 cells of different units {sorted(evs)}"]
                touched.add((t, key))
                changed["identity_conflict"] += 1
        for t, fa in forced.items():
            f = nodes[t][0]
            if pd.isna(f) or abs(math.log10(f) - math.log10(fa)) > 0.0015:
                nodes[t][:4] = [fa, "ok_tie" if abs(math.log10(fa)) < 0.0015 else "rescaled_tie", "identity_authority",
                                "identical figures in KM1 or OV1 of the same filing"]
                touched.add((t, key))
                changed["identity_authority"] += 1

        parent: dict = {}

        def find(t):
            parent.setdefault(t, t)
            while parent[t] != t:
                parent[t] = parent[parent[t]]
                t = parent[t]
            return t

        for ta_, tb_ in edges.get(key, []):
            if ta_ in nodes and tb_ in nodes:
                parent[find(ta_)] = find(tb_)
        groups: dict = defaultdict(list)
        for t in list(parent):
            groups[find(t)].append(t)
        in_group = set()
        for members in groups.values():
            if len(members) < 2:
                continue
            in_group.update(members)
            tally: dict = defaultdict(float)
            for t in members:
                if t in forced:
                    tally[round(math.log10(forced[t]), 3)] += 100.0
                elif not pd.isna(nodes[t][0]):
                    tally[round(math.log10(nodes[t][0]), 3)] += weight_of(nodes[t][1], nodes[t][4])
            if not tally:
                continue
            ranked = sorted(tally.items(), key=lambda kv: -kv[1])
            win_log, w1 = ranked[0]
            w2 = ranked[1][1] if len(ranked) > 1 else 0.0
            win = 10.0 ** win_log
            ties = ", ".join(sorted(members))
            for t in members:
                if t in forced:
                    continue
                f = nodes[t][0]
                if w1 >= 2 * w2:
                    if pd.isna(f) or abs(math.log10(f) - win_log) > 0.0015:
                        nodes[t][:4] = [win, "ok_tie" if win == 1.0 else "rescaled_tie", "identity_tie", f"identical figures in {ties}"]
                        touched.add((t, key))
                        changed["identity_tie"] += 1
                elif not pd.isna(f):
                    nodes[t][:4] = [np.nan, "quarantined", "identity_conflict", f"identical figures disagree in {ties}"]
                    touched.add((t, key))
                    changed["identity_conflict"] += 1

        f_km = auth.get((ent, ref, "K_61.00"))
        snap = {t: v[0] for t, v in nodes.items()}
        for t, v in nodes.items():
            if t in in_group or t in forced:
                continue
            f = v[0]
            if pd.isna(f) or f == 1.0:
                continue
            if f_km is not None and abs(math.log10(f / f_km)) <= 0.5:
                if abs(math.log10(f_km) - round(math.log10(f_km))) > 0.01:
                    v[:4] = [f_km, "rescaled", "bgn_peg", "unit of the KM1 filing"]
                else:
                    v[:4] = [f_km, "rescaled", v[2] or "scale_vs_anchor", v[3]]
                v[4] = True
                continue
            same = sum(1 for u, fu in snap.items() if u != t and not pd.isna(fu) and fu != 1.0
                       and abs(math.log10(fu / f)) <= 0.01)
            if same >= 3:
                continue
            v[:4] = [np.nan, "quarantined", "rescale_unconfirmed", f"no identity, KM1 unit {f_km}, {same} sister templates"]
            changed["rescale_unconfirmed"] += 1

    # single-cell filings take the unit of the KM1 filing only when sister templates agree
    for tpl, dec in decisions.items():
        st = stats[tpl]
        missing = st.index[st["s"].isna() & (st["n"] >= 1)]
        add = {}
        for key in missing:
            if key in dec.index:
                continue
            nodes = state.get(key, {})
            f_km = auth.get((key[0], key[1], "K_61.00"))
            same = sum(1 for t, v in nodes.items() if t != tpl and not pd.isna(v[0]) and f_km is not None and v[0] != 1.0
                       and abs(math.log10(v[0] / f_km)) <= 0.01)
            if f_km is not None and f_km != 1.0 and same >= 3:
                add[key] = [f_km, "rescaled_tie", "single_cell", "one amount cell; unit of the KM1 filing and 3 sister templates", False]
            else:
                add[key] = [1.0, "unverified", "", "one amount cell", False]
        if add:
            extra = pd.DataFrame.from_dict(add, orient="index", columns=["factor", "quality", "check", "detail", "tight"])
            extra.index = pd.MultiIndex.from_tuples(extra.index, names=KEYS)
            extra["anchor"] = ""
            decisions[tpl] = pd.concat([dec, extra[dec.columns]])

    for tpl, dec in decisions.items():
        for key in dec.index:
            v = state.get(key, {}).get(tpl)
            if v is not None:
                dec.loc[key, ["factor", "quality", "check", "detail", "tight"]] = v

    # stage C: a shifted filing, and a filing rescued by identity, may not exceed 3 times the size of the bank
    for tpl, dec in decisions.items():
        st = stats[tpl]
        shifted = set(dec.index[dec["factor"].notna() & (dec["factor"] != 1.0)])
        rescued = {key for (t, key) in touched if t == tpl and key in dec.index and pd.notna(dec.at[key, "factor"])}
        for key in sorted(shifted | rescued):
            ta = ta_map.get(key)
            if ta is None or key not in st.index:
                continue
            mx, f = float(st.at[key, "mx"]), float(dec.at[key, "factor"])
            if mx * f > FILING_BOUND * ta:
                if f != 1.0 and mx <= FILING_BOUND * ta:
                    dec.loc[key, ["factor", "quality", "check", "detail"]] = [1.0, "ok_wide", "size_bound", "a shift would exceed 3 times total assets"]
                else:
                    dec.loc[key, ["factor", "quality", "check", "detail"]] = [np.nan, "quarantined", "size_bound",
                                                                              "the largest figure exceeds 3 times total assets"]
                changed["size_bound"] += 1
    return changed


# ----------------------------------------------------------------------------- cells

def percent_filings(df: pd.DataFrame, is_ratio: np.ndarray) -> set:
    """Filings whose ratio cells are in percentage points: median of value / population median is about 100."""
    rc = df[is_ratio & (df["value"] != 0)].assign(v=lambda t: t["value"].abs())
    if rc.empty:
        return set()
    pm = rc.groupby(["row_code", "column_code"])["v"].transform("median")
    rc = rc[pm > 0.001].assign(lr=lambda t: np.log10(t["v"] / pm[pm > 0.001]))
    g = rc.groupby(KEYS)["lr"]
    agg = pd.DataFrame({"n": g.size(), "med": g.median(), "share": g.apply(lambda s: float((s >= 1.3).mean()))})
    return set(agg[(agg["n"] >= 3) & (agg["share"] >= 0.6) & agg["med"].between(1.5, 2.5)].index)


def cell_output(tpl: str, df: pd.DataFrame, dec: pd.DataFrame, ta_map: dict):
    """Cleaned cells and flags for one template."""
    df = df.copy()
    df["kind"] = assign_kind(df, tpl)
    gk = pd.MultiIndex.from_frame(df[KEYS])
    d = dec.reindex(gk)
    factor, gq = d["factor"].to_numpy(float), d["quality"].to_numpy(object)
    raw = df["value"].to_numpy(float)
    n = len(df)
    val, qual = raw.copy(), np.array(["untested"] * n, dtype=object)
    unit, fac = np.array([""] * n, dtype=object), np.ones(n)
    is_amt, is_ratio = (df["kind"] == "amount").to_numpy(), (df["kind"] == "ratio").to_numpy()
    flags = []

    st = group_stats(df)
    zero_f = st[(st["n_all"] >= 5) & (st["n_zero"] == st["n_all"])].index
    nonzero_entities = set(st[st["n"] >= 1].index.get_level_values(0))
    placeholder = [k for k in zero_f if k[0] in nonzero_entities]
    zero_group = pd.MultiIndex.from_frame(df[KEYS]).isin(placeholder)

    resolved = ~pd.isna(gq)
    amt_ok = is_amt & resolved & ~np.isnan(factor)
    val[amt_ok] = raw[amt_ok] * factor[amt_ok]
    fac[amt_ok] = factor[amt_ok]
    qual[amt_ok] = gq[amt_ok]
    unit[amt_ok] = np.where(factor[amt_ok] != 1.0, [f"x{f:g}" for f in factor[amt_ok]], "eur")
    amt_q = is_amt & resolved & np.isnan(factor)
    val[amt_q], qual[amt_q] = np.nan, "quarantined"
    zq = is_amt & zero_group & ~amt_q
    val[zq], qual[zq] = np.nan, "quarantined"

    # cell bound: no cell exceeds 1,000 times the size of the bank
    ta = np.array([ta_map.get(k, np.nan) for k in zip(df["entity_key"], df["reference_date"])])
    over = amt_ok & np.isfinite(ta) & (np.abs(val) > CELL_BOUND * ta)
    revert = over & (np.abs(raw) <= RAW_CELL_LIMIT * ta) & (fac != 1.0)
    val[revert], fac[revert], qual[revert], unit[revert] = raw[revert], 1.0, "cell_reverted", "eur"
    drop = over & ~revert
    val[drop], qual[drop] = np.nan, "quarantined"
    for key in sorted({k for k in zip(df.loc[revert, "entity_key"], df.loc[revert, "reference_date"])}):
        flags.append((key[1], key[0], tpl, "cell_bound", "revert", None, "cells above 1,000 times total assets keep their raw value"))
    for key in sorted({k for k in zip(df.loc[drop, "entity_key"], df.loc[drop, "reference_date"])}):
        flags.append((key[1], key[0], tpl, "cell_bound", "quarantine", None, "cells above 1,000 times total assets removed"))

    pct = percent_filings(df, is_ratio)
    in_pct = pd.MultiIndex.from_frame(df[KEYS]).isin(pct)
    conv = is_ratio & in_pct & (raw != 0)
    val[conv], qual[conv], unit[conv], fac[conv] = raw[conv] / 100.0, "converted", "percent", 0.01
    qual[is_ratio & ~in_pct & (np.abs(raw) > 1.5)] = "suspect"
    qual[is_ratio & (qual == "untested")] = "ok"
    for key in sorted(pct):
        flags.append((key[1], key[0], tpl, "ratio_percent", "convert", 0.01, "ratio cells in percentage points"))

    for (key, ref), r in dec[dec["quality"].isin(["rescaled", "rescaled_tie", "ok_tie", "quarantined"])].iterrows():
        act = "quarantine" if r["quality"] == "quarantined" else ("rescale" if r["quality"].startswith("rescaled") else "revert")
        flags.append((ref, key, tpl, r["check"] or "scale_vs_anchor", act,
                      None if pd.isna(r["factor"]) else float(r["factor"]), str(r["detail"])[:300]))
    for key in placeholder:
        flags.append((key[1], key[0], tpl, "zero_placeholder", "quarantine", None, "all amounts are 0; the bank has amounts in another filing"))

    period = np.where(df["column_label"].str.contains("T-", regex=False), None, df["reference_date"])
    out = pd.DataFrame({
        "entity_key": df["entity_key"], "entity_id": df["entity_id"], "reference_date": df["reference_date"], "template_code": tpl,
        "seq": df["seq"], "cell_code": df["cell_code"], "row_code": df["row_code"], "column_code": df["column_code"],
        "row_label": df["row_label"], "column_label": df["column_label"], "sheet": df["sheet"], "key_descriptor": df["key_descriptor"],
        "period_end": period, "value_raw": raw, "value": val, "quality": qual, "unit_inferred": unit, "factor": fac})
    fl = pd.DataFrame(flags, columns=["reference_date", "entity_key", "template_code", "check_name", "action", "factor", "detail"])
    fl["period_offset"], fl["row_code"], fl["table_code"] = 0, "", tpl
    return out, fl[FLAG_COLUMNS]


def filing_state(out: pd.DataFrame) -> pd.Series:
    """One state for each (template, entity, filing): the factor of its amounts, or 'removed'."""
    am = out[out["unit_inferred"].isin(["eur"]) | out["unit_inferred"].str.startswith("x") | (out["quality"] == "quarantined")]
    am = am[am["quality"] != "converted"]
    k = ["template_code", "entity_key", "reference_date"]
    live = am[am["quality"] != "quarantined"].groupby(k)["factor"].first()
    allq = am.groupby(k)["quality"].apply(lambda s: bool((s == "quarantined").all()))
    state = live.map(lambda f: f"x{f:g}")
    removed = pd.Series("removed", index=allq.index[allq], dtype=object)
    return pd.concat([state[~state.index.isin(removed.index)], removed])


# ----------------------------------------------------------------------------- stage D

AMOUNT_QUALITIES = {"ok", "ok_wide", "ok_history", "ok_tie", "rescaled", "rescaled_tie", "cell_reverted", "unverified"}
NEIGHBOUR_JUMP, NEIGHBOUR_AGREE, NEIGHBOUR_FIT, NEIGHBOUR_MIN_CELLS = 2.5, 1.0, 0.75, 3


def neighbour_stage(tpl: str, out: pd.DataFrame, ta_map: dict):
    """Neighbouring filings of one bank are anchors. A filing that jumps by 1,000 or more against agreeing
    neighbours is rescaled to match them (when that fits within 0.75 decades) or removed. The test uses the same
    cells (row, column, key, sheet) in both filings, so it does not depend on which cells a bank filled.
    """
    is_amt = (out["unit_inferred"] == "eur") | out["unit_inferred"].str.startswith("x")
    live = out[is_amt & out["quality"].isin(AMOUNT_QUALITIES) & out["value"].notna() & (out["value"].abs() >= 1e4)].copy()
    flags = []
    if live.empty:
        return out, flags
    live["cell"] = live["cell_code"] + "|" + live["key_descriptor"] + "|" + live["sheet"]
    live["lv"] = np.log10(live["value"].abs())
    for ent, g in live.groupby("entity_key"):
        refs = sorted(g["reference_date"].unique())
        if len(refs) < 2:
            continue
        pv = g.groupby(["cell", "reference_date"])["lv"].first().unstack("reference_date").reindex(columns=refs)
        arr = pv.to_numpy()
        f = len(refs)
        d = np.full((f, f), np.nan)
        fr = np.zeros((f, f))
        cnt = np.zeros((f, f), int)
        for i in range(f):
            for j in range(f):
                if i == j:
                    continue
                diff = arr[:, i] - arr[:, j]
                ok = ~np.isnan(diff)
                cnt[i, j] = int(ok.sum())
                if cnt[i, j] >= NEIGHBOUR_MIN_CELLS:
                    d[i, j] = float(np.median(diff[ok]))
                    fr[i, j] = float(np.mean(np.abs(diff[ok]) >= NEIGHBOUR_JUMP))
        # a pair jumps if the median jumps or a fifth of the cells jump (a mixed filing); it agrees if almost no cell jumps
        jump = (cnt >= NEIGHBOUR_MIN_CELLS) & ((np.abs(np.nan_to_num(d)) >= NEIGHBOUR_JUMP) | (fr >= 0.2))
        agree = (cnt >= NEIGHBOUR_MIN_CELLS) & (fr < 0.1) & (np.abs(np.nan_to_num(d, nan=99.0)) < NEIGHBOUR_AGREE)
        if not jump.any():
            continue
        odd = set()
        for i in range(f):
            j_i, a_i = int(jump[i].sum()), int(agree[i].sum())
            if j_i > 0 and j_i > a_i:
                odd.add(i)
        if not odd:
            # two filings against each other: the one farther from the size of the bank is odd
            for i, j in zip(*np.where(np.triu(jump))):
                dist = []
                for k in (i, j):
                    ta = ta_map.get((ent, refs[k]))
                    mx = float(g.loc[g["reference_date"] == refs[k], "value"].abs().max())
                    dist.append(abs(math.log10(mx / ta)) if ta else np.nan)
                if np.isnan(dist).any() or abs(dist[0] - dist[1]) < 0.5:
                    odd.update((i, j))
                else:
                    odd.add(i if dist[0] > dist[1] else j)
        good = [k for k in range(f) if k not in odd]
        for i in sorted(odd):
            ref = refs[i]
            rows = (out["entity_key"] == ent) & (out["reference_date"] == ref) & is_amt & out["quality"].isin(AMOUNT_QUALITIES) & out["value"].notna()
            partners = [k for k in good if jump[i, k]]
            note = ""
            if partners:
                cell_diff = np.nanmedian(np.where(np.isnan(arr[:, [k for k in good]]), np.nan,
                                                  arr[:, [i]] - arr[:, [k for k in good]]), axis=1) \
                    if good else np.array([])
                comparable = cell_diff[~np.isnan(cell_diff)]
                delta = -3 * round(float(np.median(comparable)) / 3) if len(comparable) else 0
                if abs(delta) in (3, 6):
                    fits = float(np.mean(np.abs(comparable + delta) < NEIGHBOUR_FIT))
                    zero = float(np.mean(np.abs(comparable) < NEIGHBOUR_FIT))
                    if fits >= 0.9 and zero <= 0.1:
                        factor = 10.0 ** delta
                        out.loc[rows, "value"] = out.loc[rows, "value"] * factor
                        out.loc[rows, "factor"] = out.loc[rows, "factor"] * factor
                        out.loc[rows, "quality"] = "rescaled_nb"
                        out.loc[rows, "unit_inferred"] = f"x{out.loc[rows, 'factor'].iloc[0]:g}"
                        flags.append((ref, ent, tpl, "neighbour", "rescale", factor,
                                      f"{fits:.0%} of {len(comparable)} cells jump {-delta} decades against {len(good)} agreeing filings"))
                        continue
                    note = f" (mixed units: {fits:.0%} of cells fit the shift, {zero:.0%} fit no shift)"
                else:
                    note = " (no shift of 1,000 or 1,000,000 fits)"
            out.loc[rows, "value"] = np.nan
            out.loc[rows, "quality"] = "quarantined"
            flags.append((ref, ent, tpl, "neighbour_conflict", "quarantine", None, "unit jump against neighbouring filings" + note))
    return out, flags


def identity_final(outs: dict, pairs: pd.DataFrame):
    """Templates that share identical figures must end with one unit. Of two that do not, the shifted one is removed."""
    fac: dict = {}
    for tpl, out in outs.items():
        live = out[((out["unit_inferred"] == "eur") | out["unit_inferred"].str.startswith("x")) & out["value"].notna()]
        g = live.groupby(KEYS)["factor"].first()
        fac[tpl] = g.to_dict()
    victims: set = set()
    p = pairs[pairs["n"] >= 2]
    for r in p.itertuples():
        fa = fac.get(r.tpl_a, {}).get((r.entity_key, r.reference_date))
        fb = fac.get(r.tpl_b, {}).get((r.entity_key, r.reference_date))
        if fa is None or fb is None or abs(math.log10(fa / fb)) <= 0.01:
            continue
        if abs(math.log10(fa)) < 0.01:
            victims.add((r.tpl_b, r.entity_key, r.reference_date, r.tpl_a))
        elif abs(math.log10(fb)) < 0.01:
            victims.add((r.tpl_a, r.entity_key, r.reference_date, r.tpl_b))
        else:
            victims.add((r.tpl_a, r.entity_key, r.reference_date, r.tpl_b))
            victims.add((r.tpl_b, r.entity_key, r.reference_date, r.tpl_a))
    flags = []
    for tpl, ent, ref, partner in sorted(victims):
        out = outs[tpl]
        rows = (out["entity_key"] == ent) & (out["reference_date"] == ref) & ((out["unit_inferred"] == "eur") | out["unit_inferred"].str.startswith("x")) \
            & out["value"].notna()
        out.loc[rows, "value"] = np.nan
        out.loc[rows, "quality"] = "quarantined"
        flags.append((ref, ent, tpl, "identity_conflict", "quarantine", None, f"identical figures with {partner} but a different unit"))
    return flags


# ----------------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--templates", nargs="*", help="Only these templates (default: all with amounts)")
    ap.add_argument("--dry-run", action="store_true", help="Calibrate and print, write nothing")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    for name in ("clean_period_fact", "entity_assets", "clean_fact", "clean_filing_unit", "clean_cell_unit"):
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (name,)).fetchone():
            print(f"{name} is missing. Run clean_p3dh.py, classify_p3dh.py, and clean_templates.py first.", file=sys.stderr)
            return 1
    base = load_base_anchors(conn)
    anchors = {c: base[c].dropna() for c in base.columns}
    auth, km_failed = load_units(conn)
    ta_series = anchors["TA"].combine_first(anchors["LEV"]) if "LEV" in anchors else anchors["TA"]
    ta_map = ta_series.to_dict()

    all_templates = [t for (t,) in conn.execute("SELECT DISTINCT template_code FROM fact WHERE value IS NOT NULL ORDER BY template_code")]
    templates = [t for t in all_templates if t not in HANDLED_ELSEWHERE and (not args.templates or t in args.templates)]
    stats, tie_parts = {}, []
    for t in templates:
        df = pd.read_sql_query(SQL, conn, params=(t,))
        df["kind"] = assign_kind(df, t)
        stats[t] = group_stats(df)
        tie_parts.append(tie_values(df, t))
    pairs = tie_pairs(tie_parts)
    ev = authority_evidence(tie_parts, pd.read_sql_query("SELECT * FROM clean_cell_unit", conn))
    print(f"{len(templates)} templates prepared, {len(pairs)} template pairs and {len(ev)} KM1/OV1 matches share figures", flush=True)

    summaries, decisions, pending = {}, {}, list(templates)
    for rnd in range(1, 4):
        snapshot = dict(anchors)
        new_anchors, progress = {}, []
        for t in pending:
            summ, dec = evaluate(t, stats[t], snapshot, km_failed)
            summ["round"] = rnd
            summaries[t] = summ
            if summ["status"] == "ok":
                decisions[t] = dec
                good = dec[dec["quality"].isin(["ok", "ok_wide"]) & (dec["factor"] == 1.0)]
                chain = stats[t].loc[good.index, "s"].astype(float).dropna()
                if len(chain) >= CHAIN_MIN_GROUPS:
                    new_anchors[f"S:{t}"] = chain[chain > 0]
                progress.append(t)
        anchors.update(new_anchors)
        pending = [t for t in pending if t not in decisions]
        print(f"round {rnd}: {len(progress)} templates calibrated, {len(pending)} left", flush=True)
        if not progress or not pending:
            break

    changed = reconcile(decisions, stats, pairs, ev, auth, ta_map)
    print("reconciliation:", dict(changed), flush=True)

    cal = pd.DataFrame([{"template_code": t, **summaries.get(t, {"status": "no_amounts", "note": "no amount cells"})} for t in templates])
    print(cal[["template_code", "status", "round", "anchor", "share_main", "spread", "n_groups"]].round(2).to_string(index=False))
    if args.dry_run:
        return 0

    outs, flags = {}, []
    for t in sorted(decisions):
        df = pd.read_sql_query(SQL, conn, params=(t,))
        out, fl = cell_output(t, df, decisions[t], ta_map)
        out, nb_flags = neighbour_stage(t, out, ta_map)
        if nb_flags:
            nbf = pd.DataFrame(nb_flags, columns=["reference_date", "entity_key", "template_code", "check_name", "action", "factor", "detail"])
            nbf["period_offset"], nbf["row_code"], nbf["table_code"] = 0, "", t
            fl = pd.concat([fl, nbf[FLAG_COLUMNS]], ignore_index=True)
        outs[t] = out
        flags.append(fl)
        print(f"  {t}: {len(out)} cells", flush=True)
    id_flags = identity_final(outs, pairs)
    if id_flags:
        idf = pd.DataFrame(id_flags, columns=["reference_date", "entity_key", "template_code", "check_name", "action", "factor", "detail"])
        idf["period_offset"], idf["row_code"], idf["table_code"] = 0, "", idf["template_code"]
        flags.append(idf[FLAG_COLUMNS])
    print(f"final identity pass: {len(id_flags)} template filings removed", flush=True)
    result = pd.concat(list(outs.values()), ignore_index=True) if outs else pd.DataFrame()
    flag_df = pd.concat(flags, ignore_index=True) if flags else pd.DataFrame(columns=FLAG_COLUMNS)

    ts = datetime.now().isoformat(timespec="seconds")
    cal["run_ts"] = ts
    done = list(decisions) + [t for t in templates if t not in decisions]
    marks = ",".join("?" * len(done))
    old_state = None
    if conn.execute("SELECT COUNT(*) FROM clean_fact WHERE template_code IN (%s)" % marks, done).fetchone()[0]:
        old = pd.read_sql_query(
            "SELECT template_code, entity_key, reference_date, factor, quality, unit_inferred FROM clean_fact "
            "WHERE template_code IN (%s)" % marks, conn, params=done)
        old_state = filing_state(old)
    new_state = filing_state(result) if len(result) else pd.Series(dtype=object)

    with conn:
        conn.execute("DELETE FROM clean_fact WHERE template_code IN (%s)" % marks, done)
        if len(result):
            result.to_sql("clean_fact", conn, if_exists="append", index=False, chunksize=100000)
        conn.execute("DELETE FROM dq_flag WHERE template_code IN (%s)" % marks, done)
        if len(flag_df):
            flag_df.to_sql("dq_flag", conn, if_exists="append", index=False)
        if args.templates:
            conn.execute("DELETE FROM clean_calibration WHERE template_code IN (%s)" % marks, done)
            cal.to_sql("clean_calibration", conn, if_exists="append", index=False)
        else:
            cal.to_sql("clean_calibration", conn, if_exists="replace", index=False)
        log = cal[["run_ts", "template_code", "status", "anchor", "mode_center", "share_main", "spread", "n_groups"]].copy()
        q = flag_df[flag_df["action"] == "quarantine"].groupby("template_code").size() if len(flag_df) else pd.Series(dtype=int)
        r = flag_df[flag_df["action"] == "rescale"].groupby("template_code").size() if len(flag_df) else pd.Series(dtype=int)
        log["n_quarantined"] = log["template_code"].map(q).fillna(0).astype(int)
        log["n_rescaled"] = log["template_code"].map(r).fillna(0).astype(int)
        log.to_sql("clean_run_log", conn, if_exists="append", index=False)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_clean_fact ON clean_fact(template_code, entity_key, reference_date)")
    release_diff(conn, old_state, new_state, ts)
    drift_report(conn)
    clean_templates.write_status(conn, doc=clean_templates.STATUS_DOC if args.db.resolve() == DEFAULT_DB.resolve() else None)
    conn.close()
    return 0


def release_diff(conn, old: pd.Series | None, new: pd.Series, ts: str) -> None:
    """Every filing whose decision changed since the last run. A person should review them."""
    if old is None or new.empty:
        print("Release diff: first run, nothing to compare.")
        return
    j = pd.DataFrame({"old_state": old, "new_state": new}).dropna()
    diff = j[j["old_state"] != j["new_state"]].reset_index()
    diff["run_ts"] = ts
    with conn:
        diff.to_sql("clean_release_diff", conn, if_exists="append", index=False)
    print(f"Release diff: {len(diff)} of {len(j)} filings changed state since the last run "
          f"({len(diff) / max(1, len(j)):.1%}). See table clean_release_diff.")


def drift_report(conn: sqlite3.Connection) -> None:
    """Compare the last two runs. A change in mode, share, or removals means the data changed."""
    runs = [r[0] for r in conn.execute("SELECT DISTINCT run_ts FROM clean_run_log ORDER BY run_ts DESC LIMIT 2")]
    if len(runs) < 2:
        print("Drift report: first run, nothing to compare.")
        return
    d = pd.read_sql_query("SELECT * FROM clean_run_log WHERE run_ts IN (?, ?)", conn, params=tuple(runs))
    new, old = d[d.run_ts == runs[0]].set_index("template_code"), d[d.run_ts == runs[1]].set_index("template_code")
    j = new.join(old, lsuffix="_new", rsuffix="_old", how="outer")
    active = (j["status_new"] == "ok") | (j["status_old"] == "ok")
    rows = j[active & ((j["status_new"] != j["status_old"]) | ((j["share_main_new"] - j["share_main_old"]).abs() > 0.05)
                       | ((j["mode_center_new"] - j["mode_center_old"]).abs() > 0.3) | (j["anchor_new"] != j["anchor_old"]))]
    print(f"Drift report ({runs[1]} -> {runs[0]}): {len(rows)} templates changed")
    if len(rows):
        print(rows[["status_old", "status_new", "anchor_old", "anchor_new", "share_main_old", "share_main_new",
                    "mode_center_old", "mode_center_new"]].round(2).to_string())


if __name__ == "__main__":
    sys.exit(main())
