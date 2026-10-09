"""Generic clean engine: unit, zero, and ratio tests for every template that has amounts.

Run after scripts/clean_p3dh.py, scripts/classify_p3dh.py, and scripts/clean_templates.py.
The engine reads no template-specific rule. It finds the rule in the data, for each run:

1. Cell type. A cell (row and column of a template) is an amount, a ratio, or other. An amount has a
   median above EUR 100,000. A ratio has 90% of its values at or below 1.5.
2. Size of a filing. For each entity and filing, the size is the 90th percentile of the non-zero
   amounts of the template.
3. Anchor. The size is compared with an anchor of the same entity and period: total assets, leverage
   exposure, TREA, Tier 1, CET1, OV1 RWEA by risk type (all clean), or the cleaned size of
   another template. The engine tests every anchor and keeps those with the tightest main mode.
4. Mode. The log10 of (size / anchor) has one main mode for filings in EUR. Filings in thousand or
   million sit 3 or 6 units away. The filings of one bank whose sizes agree form a cluster with one unit.
   All anchors of the cluster vote for a shift. No shift is the default. A shift needs enough weight
   (tight anchor 2, loose anchor 1; at least 3 and 1.5 times the weight of no shift). Conflicting votes
   remove the cluster. A filing between two modes is removed.
5. Ratio cells. A filing that reports fractions as percentages is converted when most ratio cells are
   above 1.5 and all are at most 150. Other ratio cells above 1.5 get the quality "suspect".
6. Zero placeholders. A filing with only zero amounts is removed when fewer than 10% of the filings of
   the template are all zero.

A template enters clean_fact only when its main mode is tight (at least 70% of the filings within 0.75 of
the mode and a robust spread of at most 0.35 on a window of 1.5 around it). The engine repeats the search in up to 3 rounds. A template that is
clean in one round becomes an anchor for the next round.

New data: the engine always tests again. It never assumes that a bank repeats its unit. The history
(table clean_run_log) is used only to report drift between runs.

Quality values: ok, ok_wide, ok_history, rescaled, converted, suspect, unverified, untested, quarantined.

Run: PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/clean_engine.py
"""

from __future__ import annotations

import argparse
import math
import sqlite3
import sys
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
NO_SELF_ANCHOR = {"K_70.00": {"TA"}, "K_66.02": {"TA"}, "K_64.01": {"TA"}, "K_71.00": {"LEV"}, "K_72.00": {"LEV"}}
MODE_TOL, WIDE_TOL = 0.75, 1.25
MIN_GROUPS, MIN_SHARE, MAX_SPREAD, MIN_SCORE = 10, 0.70, 0.35, 0.0
CHAIN_MIN_GROUPS = 25  # a template with fewer filings does not become an anchor
SECONDARY_SHARE, SECONDARY_SPREAD = 0.60, 0.55  # a looser anchor can still find a shift of 1,000
ZERO_SHARE_LIMIT = 0.10
AMOUNT_MEDIAN = 1e5
KEYS = ["entity_key", "reference_date"]
SQL = """SELECT e.entity_key, f.entity_id, f.reference_date, f.seq, f.cell_code, f.row_code, f.column_code,
                f.row_label, f.column_label, f.sheet, f.key_descriptor, f.value
         FROM fact f JOIN entity e ON e.entity_id = f.entity_id
         WHERE f.template_code = ? AND f.value IS NOT NULL"""


def assign_kind(df: pd.DataFrame) -> pd.Series:
    """amount, ratio, or other for each cell, from the values of all entities."""
    a = df["value"].abs()
    nz = df.loc[a > 0, ["row_code", "column_code"]].assign(a=a[a > 0])

    def table(keys):
        g = nz.groupby(keys)["a"]
        return pd.DataFrame({"n": g.size(), "p50": g.median(), "p90": g.quantile(0.9)})

    def kind(p50, p90):
        return np.where(p50 >= AMOUNT_MEDIAN, "amount", np.where(p90 <= 1.5, "ratio", "other"))

    cell, col = table(["row_code", "column_code"]), table(["column_code"])
    cell["kind"] = kind(cell["p50"], cell["p90"])
    col["kind"] = kind(col["p50"], col["p90"])
    out = df[["row_code", "column_code"]].merge(cell["kind"].reset_index(), on=["row_code", "column_code"], how="left")["kind"]
    sparse = df[["row_code", "column_code"]].merge(cell[["n"]].reset_index(), on=["row_code", "column_code"], how="left")["n"].fillna(0) < 8
    colk = df[["column_code"]].merge(col["kind"].reset_index(), on="column_code", how="left")["kind"]
    out = pd.Series(np.where(sparse.to_numpy() | out.isna().to_numpy(), colk.fillna("other").to_numpy(), out.to_numpy()), index=df.index)
    return out


def group_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Size of each filing: 90th percentile of the non-zero amounts (maximum if fewer than 3)."""
    am = df[(df["kind"] == "amount") & (df["value"] != 0)]
    g = am.assign(a=am["value"].abs()).groupby(KEYS)["a"]
    stat = pd.DataFrame({"s": g.quantile(0.9), "n": g.size(), "mx": g.max()})
    stat.loc[stat["n"] < 3, "s"] = stat["mx"]
    allcells = df[df["kind"] == "amount"].groupby(KEYS)["value"].agg(n_all="size", n_zero=lambda s: int((s == 0).sum()))
    return stat.join(allcells, how="outer")


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
    k_main = vals[counts.argmax()]
    main = x[inside & (ks == k_main)]
    m = float(np.median(main))
    window = x[np.abs(x - m) <= 1.5]
    spread = float(1.4826 * np.median(np.abs(window - np.median(window))))
    share = len(main) / n
    score = share * (1 - min(1.0, spread / 0.5))
    return {"m": m, "spread": spread, "share": share, "score": score, "n": n,
            "ok": share >= MIN_SHARE and spread <= MAX_SPREAD and score >= MIN_SCORE,
            "secondary": share >= SECONDARY_SHARE and spread <= SECONDARY_SPREAD}


def decide(x: np.ndarray, m: float):
    """Factor, quality, and check for each filing. NaN factor removes the filing."""
    n = np.round((x - m) / 3)
    r = x - m - 3 * n
    factor = np.full(len(x), np.nan)
    qual = np.full(len(x), "quarantined", dtype=object)
    check = np.full(len(x), "scale_ambiguous", dtype=object)
    exact = np.abs(r) <= MODE_TOL
    factor[exact & (n == 0)], qual[exact & (n == 0)], check[exact & (n == 0)] = 1.0, "ok", ""
    shifted = exact & (n != 0) & (np.abs(n) <= 3)
    factor[shifted] = 10.0 ** (-3 * n[shifted])
    qual[shifted], check[shifted] = "rescaled", "scale_vs_anchor"
    wide = (n == 0) & ~exact & (np.abs(r) <= WIDE_TOL)
    factor[wide], qual[wide], check[wide] = 1.0, "ok_wide", ""
    return factor, qual, check


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
    ta = pd.read_sql_query("SELECT entity_key, period_end AS reference_date, size_basis_eur AS TA FROM entity_assets WHERE size_basis_eur > 0", conn)
    a = a.join(ta.set_index(KEYS), how="outer")
    # the chain anchors in clean_templates (AE1 total assets) are handled by the TA anchor
    raw = set(map(tuple, pd.read_sql_query(
        """SELECT DISTINCT e.entity_key, f.reference_date FROM fact f JOIN entity e ON e.entity_id = f.entity_id
           WHERE f.template_code = 'K_61.00' AND f.row_code = '0020' AND f.column_code = '0010' AND f.value IS NOT NULL""", conn).values))
    return a, raw


def evaluate(tpl: str, stat: pd.DataFrame, anchors: dict, raw_km1: set):
    """Calibrate a template against every anchor and decide each filing. Returns (summary, decisions).

    Every usable anchor tests each filing. Two anchors that give different factors remove the filing.
    A filing with no usable anchor is removed only if its own KM1 failed the scale test. Otherwise it
    is kept as "unverified".
    """
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
        x = (np.log10(s[ok]) - np.log10(a[ok])).to_numpy()
        cal = calibrate(x)
        if cal:
            cands.append((name, cal))
    if not cands:
        return {"status": "no_anchor", "note": "no anchor with enough filings"}, None
    cands.sort(key=lambda t: -t[1]["score"])
    best_name, best = cands[0]
    summary = {"anchor": best_name, "score": best["score"], "share_main": best["share"], "spread": best["spread"],
               "mode_center": best["m"], "n_groups": len(s), "status": "ok" if best["ok"] else "weak"}
    if not best["ok"]:
        summary["note"] = (f"best anchor {best_name}: {best['share']:.0%} of filings in the main mode, spread {best['spread']:.2f}; "
                           f"needs at least {MIN_SHARE:.0%} and at most {MAX_SPREAD}")
        return summary, None
    usable = [(n, c) for n, c in cands if c["ok"] and c["score"] >= 0.5 * best["score"]]
    usable += [(n, c) for n, c in cands if not (c["ok"] and c["score"] >= 0.5 * best["score"]) and c["secondary"]]
    summary["n_anchors"] = len(usable)
    tier_ok = [bool(c["ok"] and c["score"] >= 0.5 * best["score"]) for _, c in usable]
    idx = stat.index
    fac = np.full((len(idx), len(usable)), np.nan)
    has = np.zeros((len(idx), len(usable)), dtype=bool)
    xs = np.full((len(idx), len(usable)), np.nan)
    qual = np.full((len(idx), len(usable)), "", dtype=object)
    chk = np.full((len(idx), len(usable)), "", dtype=object)
    sv = stat["s"].astype(float).to_numpy()
    for j, (name, cal) in enumerate(usable):
        a = anchors[name].reindex(idx).astype(float).to_numpy()
        use = np.isfinite(a) & (a > 0) & np.isfinite(sv) & (sv > 0)
        x = np.log10(sv[use]) - np.log10(a[use])
        f, q, c = decide(x, cal["m"])
        fac[use, j], qual[use, j], chk[use, j], xs[use, j], has[use, j] = f, q, c, x, True
    km_failed = raw_km1 - set(anchors["T1"].index)
    n_all = len(idx)
    ok_pos = np.isfinite(sv) & (sv > 0)

    # 1. Each anchor votes for a shift (n = number of 3-decade steps). A tight anchor has weight 2, a loose one 1.
    votes: list[dict] = [dict() for _ in range(n_all)]
    for i in range(n_all):
        for j in range(len(usable)):
            if has[i, j]:
                n_j = round((xs[i, j] - usable[j][1]["m"]) / 3)
                if abs(xs[i, j] - usable[j][1]["m"] - 3 * n_j) <= MODE_TOL and abs(n_j) <= 3:
                    votes[i][int(n_j)] = votes[i].get(int(n_j), 0) + (2 if tier_ok[j] else 1)

    # 2. Filings of one bank whose raw sizes agree (within 0.75 decades) share one unit. They form a cluster.
    parent = list(range(n_all))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    by_entity: dict = {}
    for pos, key in enumerate(idx):
        if ok_pos[pos]:
            by_entity.setdefault(key[0], []).append(pos)
    for members in by_entity.values():
        for a in members:
            for b in members:
                if a < b and abs(np.log10(sv[a]) - np.log10(sv[b])) <= MODE_TOL:
                    parent[find(a)] = find(b)
    clusters: dict = {}
    for pos in range(n_all):
        if ok_pos[pos]:
            clusters.setdefault(find(pos), []).append(pos)

    # 3. The cluster decides one scale. No unit error is the default. A shift needs weight 3 and 1.5 times the
    #    weight of "no shift". Two different shifts of similar weight remove the cluster.
    verdict: dict = {}
    for root, members in clusters.items():
        tally: dict = {}
        for pos in members:
            for n_j, w in votes[pos].items():
                tally[n_j] = tally.get(n_j, 0) + w
        w0 = tally.get(0, 0)
        shifts = {n_j: w for n_j, w in tally.items() if n_j != 0}
        if not tally:
            verdict[root] = ("none", 0)
        elif not shifts:
            verdict[root] = ("accept", 0)
        else:
            n_best, w_best = max(shifts.items(), key=lambda kv: kv[1])
            rivals = [w for n_j, w in shifts.items() if n_j != n_best]
            if rivals and max(rivals) * 1.5 > w_best:
                verdict[root] = ("conflict", 0)
            elif w_best >= 3 and w_best >= 1.5 * w0:
                verdict[root] = ("shift", n_best)
            elif w0 >= w_best:
                verdict[root] = ("accept", 0)
            else:
                verdict[root] = ("unconfirmed", n_best)

    # 4. Each filing gets the verdict of its cluster.
    dec = pd.DataFrame(index=idx, columns=["factor", "quality", "check", "anchor", "x"], dtype=object)
    cols = ["factor", "quality", "check", "anchor", "x"]
    good_abs = []
    for i, key in enumerate(idx):
        if not ok_pos[i]:
            continue
        kind, n_best = verdict[find(i)]
        own = [j for j in range(len(usable)) if has[i, j]]
        j0 = own[0] if own else None
        if kind == "none":
            if j0 is not None:
                dec.loc[[key], cols] = [np.nan, "quarantined", "scale_ambiguous", usable[j0][0], xs[i, j0]]
            else:
                dec.loc[[key], ["factor", "quality", "check"]] = [np.nan, "pending", ""]
        elif kind == "accept":
            exact = [j for j in own if not np.isnan(fac[i, j]) and fac[i, j] == 1.0]
            if exact:
                j = exact[0]
                dec.loc[[key], cols] = [1.0, qual[i, j], chk[i, j], usable[j][0], xs[i, j]]
            else:
                dec.loc[[key], cols] = [1.0, "ok_history", "", "history", np.nan]
            good_abs.append(np.log10(sv[i]))
        elif kind == "shift":
            f = 10.0 ** (-3 * n_best)
            dec.loc[[key], cols] = [f, "rescaled", "scale_vs_anchor", usable[j0][0] if j0 is not None else "history", xs[i, j0] if j0 is not None else np.nan]
            good_abs.append(np.log10(sv[i] * f))
        else:
            why = "scale_conflict" if kind == "conflict" else "scale_unconfirmed"
            dec.loc[[key], cols] = [np.nan, "quarantined", why, usable[j0][0] if j0 is not None else "history", xs[i, j0] if j0 is not None else np.nan]
    lo, hi = (np.quantile(good_abs, 0.01) - 0.5, np.quantile(good_abs, 0.99) + 0.5) if len(good_abs) > 10 else (-np.inf, np.inf)
    for key in dec.index[dec["quality"] == "pending"]:
        val = math.log10(float(stat.at[key, "s"]))
        if key in km_failed:
            dec.loc[[key], ["factor", "quality", "check"]] = [np.nan, "quarantined", "scale_unresolved"]
        elif lo <= val <= hi:
            dec.loc[[key], ["factor", "quality", "check"]] = [1.0, "unverified", ""]
        else:
            dec.loc[[key], ["factor", "quality", "check"]] = [np.nan, "quarantined", "implausible_size"]
    return summary, dec


def cell_output(tpl: str, df: pd.DataFrame, dec: pd.DataFrame, zero_limit: float):
    """Cleaned cells and flags for one template."""
    df = df.copy()
    df["kind"] = assign_kind(df)
    gk = pd.MultiIndex.from_frame(df[KEYS])
    d = dec.reindex(gk)
    factor, gq, gc = d["factor"].to_numpy(float), d["quality"].to_numpy(object), d["check"].to_numpy(object)
    raw = df["value"].to_numpy(float)
    val, qual, unit, fac = raw.copy(), np.array(["untested"] * len(df), dtype=object), np.array([""] * len(df), dtype=object), np.ones(len(df))
    is_amt, is_ratio = (df["kind"] == "amount").to_numpy(), (df["kind"] == "ratio").to_numpy()
    flags = []

    st = group_stats(df)
    all_zero = st[(st["n_all"] >= 5) & (st["n_zero"] == st["n_all"])].index
    zero_pop = len(all_zero) / max(1, int((st["n_all"] >= 5).sum()))
    zero_group = pd.MultiIndex.from_frame(df[KEYS]).isin(all_zero)

    resolved = ~pd.isna(gq)
    amt_ok = is_amt & resolved & ~np.isnan(factor)
    val[amt_ok] = raw[amt_ok] * factor[amt_ok]
    fac[amt_ok] = factor[amt_ok]
    qual[amt_ok] = gq[amt_ok]
    unit[amt_ok] = np.where(factor[amt_ok] != 1.0, [f"x{f:g}" for f in factor[amt_ok]], "eur")
    amt_q = is_amt & resolved & np.isnan(factor)
    val[amt_q], qual[amt_q] = np.nan, "quarantined"
    zq = is_amt & zero_group & (zero_pop < zero_limit)
    val[zq], qual[zq] = np.nan, "quarantined"
    qual[is_amt & zero_group & ~zq & ~amt_q & (qual == "untested")] = "untested"
    qual[is_amt & ~resolved & ~zero_group] = "untested"

    rc = df[is_ratio & (raw != 0)].assign(v=lambda t: t["value"].abs())
    if len(rc):
        g = rc.groupby(KEYS)["v"]
        agg = pd.DataFrame({"n": g.size(), "share": g.apply(lambda s: float((s > 1.5).mean())), "ok150": g.max() <= 150})
        pct = agg[(agg["n"] >= 3) & (agg["share"] >= 0.6) & agg["ok150"]].index
        in_pct = pd.MultiIndex.from_frame(df[KEYS]).isin(pct)
        conv = is_ratio & in_pct & (raw != 0)
        val[conv], qual[conv], unit[conv], fac[conv] = raw[conv] / 100.0, "converted", "percent", 0.01
        sus = is_ratio & ~in_pct & (np.abs(raw) > 1.5)
        qual[sus] = "suspect"
        qual[is_ratio & (qual == "untested")] = "ok"
        for (key, ref) in pct:
            flags.append((ref, key, tpl, "ratio_percent", "convert", 0.01, "ratio cells in percentage points"))

    qual[~is_amt & ~is_ratio] = "untested"
    for (key, ref), r in dec[dec["quality"].isin(["rescaled", "quarantined"])].iterrows():
        flags.append((ref, key, tpl, r["check"], "rescale" if r["quality"] == "rescaled" else "quarantine",
                      None if pd.isna(r["factor"]) else float(r["factor"]), f"anchor {r['anchor']}, x={r['x'] if pd.notna(r['x']) else float('nan'):.2f}"))
    if zero_pop < zero_limit:
        for key, ref in all_zero:
            flags.append((ref, key, tpl, "zero_placeholder", "quarantine", None, "all amounts are 0"))

    period = np.where(df["column_label"].str.contains("T-", regex=False), None, df["reference_date"])
    out = pd.DataFrame({
        "entity_key": df["entity_key"], "entity_id": df["entity_id"], "reference_date": df["reference_date"], "template_code": tpl,
        "seq": df["seq"], "cell_code": df["cell_code"], "row_code": df["row_code"], "column_code": df["column_code"],
        "row_label": df["row_label"], "column_label": df["column_label"], "sheet": df["sheet"], "key_descriptor": df["key_descriptor"],
        "period_end": period, "value_raw": raw, "value": val, "quality": qual, "unit_inferred": unit, "factor": fac})
    fl = pd.DataFrame(flags, columns=["reference_date", "entity_key", "template_code", "check_name", "action", "factor", "detail"])
    fl["period_offset"], fl["row_code"], fl["table_code"] = 0, "", tpl
    return out, fl[["reference_date", "entity_key", "template_code", "period_offset", "row_code", "table_code", "check_name", "action", "factor", "detail"]]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--templates", nargs="*", help="Only these templates (default: all with amounts)")
    ap.add_argument("--dry-run", action="store_true", help="Calibrate and print, write nothing")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    for name in ("clean_period_fact", "entity_assets", "clean_fact"):
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (name,)).fetchone():
            print(f"{name} is missing. Run clean_p3dh.py, classify_p3dh.py, and clean_templates.py first.", file=sys.stderr)
            return 1
    base, raw_km1 = load_base_anchors(conn)
    anchors = {c: base[c].dropna() for c in base.columns}
    templates = [t for (t,) in conn.execute("SELECT DISTINCT template_code FROM fact WHERE value IS NOT NULL ORDER BY template_code")
                 if t not in HANDLED_ELSEWHERE and (not args.templates or t in args.templates)]
    stats, summaries, decisions = {}, {}, {}
    for t in templates:
        df = pd.read_sql_query(SQL, conn, params=(t,))
        df["kind"] = assign_kind(df)
        stats[t] = group_stats(df)
    print(f"{len(templates)} templates prepared", flush=True)

    pending = list(templates)
    for rnd in range(1, 4):
        progress = []
        for t in pending:
            summ, dec = evaluate(t, stats[t], anchors, raw_km1)
            summ["round"] = rnd
            summaries[t] = summ
            if summ["status"] == "ok":
                decisions[t] = dec
                good = dec[dec["quality"].isin(["ok", "rescaled", "ok_wide", "ok_history"])]
                chain = (stats[t].loc[good.index, "s"].astype(float) * good["factor"].astype(float)).dropna()
                if len(chain) >= CHAIN_MIN_GROUPS:
                    anchors[f"S:{t}"] = chain[chain > 0]
                progress.append(t)
        pending = [t for t in pending if t not in decisions]
        print(f"round {rnd}: {len(progress)} templates calibrated, {len(pending)} left", flush=True)
        if not progress or not pending:
            break

    cal = pd.DataFrame([{"template_code": t, **summaries.get(t, {"status": "no_amounts", "note": "no amount cells"})} for t in templates])
    cal["note"] = cal.get("note")
    print(cal[["template_code", "status", "round", "anchor", "share_main", "spread", "score", "n_groups"]].round(2).to_string(index=False))
    if args.dry_run:
        return 0

    zero_limit = ZERO_SHARE_LIMIT
    outs, flags = [], []
    for t in decisions:
        df = pd.read_sql_query(SQL, conn, params=(t,))
        out, fl = cell_output(t, df, decisions[t], zero_limit)
        outs.append(out)
        flags.append(fl)
        print(f"  {t}: {len(out)} cells, {int((out['quality'] == 'quarantined').sum())} removed", flush=True)
    result = pd.concat(outs, ignore_index=True) if outs else pd.DataFrame()
    flag_df = pd.concat(flags, ignore_index=True) if flags else pd.DataFrame()

    ts = datetime.now().isoformat(timespec="seconds")
    cal["run_ts"] = ts
    with conn:
        conn.execute("DELETE FROM clean_fact WHERE template_code NOT IN ({})".format(",".join("?" * len(HANDLED_ELSEWHERE))), tuple(HANDLED_ELSEWHERE))
        if len(result):
            result.to_sql("clean_fact", conn, if_exists="append", index=False, chunksize=100000)
        conn.execute("DELETE FROM dq_flag WHERE template_code NOT IN ({})".format(",".join("?" * len(HANDLED_ELSEWHERE))), tuple(HANDLED_ELSEWHERE))
        if len(flag_df):
            flag_df.to_sql("dq_flag", conn, if_exists="append", index=False)
        cal.to_sql("clean_calibration", conn, if_exists="replace", index=False)
        log = cal[["run_ts", "template_code", "status", "anchor", "mode_center", "share_main", "spread", "n_groups"]].copy()
        quarantined = flag_df[flag_df["action"] == "quarantine"].groupby("template_code").size() if len(flag_df) else pd.Series(dtype=int)
        rescaled = flag_df[flag_df["action"] == "rescale"].groupby("template_code").size() if len(flag_df) else pd.Series(dtype=int)
        log["n_quarantined"] = log["template_code"].map(quarantined).fillna(0).astype(int)
        log["n_rescaled"] = log["template_code"].map(rescaled).fillna(0).astype(int)
        log.to_sql("clean_run_log", conn, if_exists="append", index=False)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_clean_fact ON clean_fact(template_code, entity_key, reference_date)")
    drift_report(conn)
    clean_templates.write_status(conn)
    conn.close()
    return 0


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
        print(rows[["status_old", "status_new", "anchor_old", "anchor_new", "share_main_old", "share_main_new", "mode_center_old", "mode_center_new"]].round(2).to_string())


if __name__ == "__main__":
    sys.exit(main())
