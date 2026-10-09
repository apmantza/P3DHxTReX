"""Clean layer for templates without a period grid: IRRBB1 (K_68.00) and encumbrance AE1 to AE3.

Run after scripts/clean_p3dh.py and scripts/classify_p3dh.py. The script writes:
  clean_fact     every fact of these templates with value_raw, value, quality, unit_inferred, factor
  dq_flag        one row for each entity-filing test that changed or removed a value
  v_clean_fact   clean_fact without the removed values
  docs/p3dh_template_status.md   the working note: which template is clean and which is not

A repair needs an anchor. The anchor is a clean amount from another template of the same entity
and period. The test compares the size of the template with the anchor. A factor of 1,000 or
1,000,000 is applied only when exactly one factor gives a plausible ratio.

  K_20.01 AE1   encumbered plus unencumbered assets against total assets (entity_assets)
  K_20.02 AE2   total encumbered, row 250, against the encumbered assets of AE1
  K_20.03 AE3   encumbered assets against the encumbered assets of AE1
  K_68.00 IRRBB1  largest change of EVE against Tier 1 capital (clean KM1)

IRRBB1 values come in six conventions: EUR, thousand, million, 1,000 times too large, fraction of
Tier 1, and percent of Tier 1. The script converts a filing only when exactly one convention gives
a ratio to Tier 1 between 0.5% and 50%. Values in a ratio convention are converted to EUR with the
Tier 1 capital of the same period. The NII columns and the last-period columns of such a filing are
removed because their base is unknown.

Quality values: ok, ok_wide (ratio outside the usual range, accepted), rescaled, converted,
unverified (no anchor, size plausible), untested (statistic is 0), quarantined (value removed).

Run: PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/clean_templates.py
"""

from __future__ import annotations

import argparse
import math
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "processed" / "p3dh.sqlite"
STATUS_DOC = PROJECT_ROOT / "docs" / "p3dh_template_status.md"

TEMPLATES = ("K_68.00", "K_20.01", "K_20.02", "K_20.03")
FACTORS = (1e3, 1e6, 1e-3, 1e-6)
ABS_ASSETS = (1e7, 5e12)
IRR_PRIMARY, IRR_WIDE = (0.005, 0.5), (0.0005, 2.0)

VIEW = """
DROP VIEW IF EXISTS v_clean_fact;
CREATE VIEW v_clean_fact AS SELECT * FROM clean_fact WHERE quality <> 'quarantined';
"""


def load_facts(conn: sqlite3.Connection) -> pd.DataFrame:
    marks = ",".join("?" * len(TEMPLATES))
    return pd.read_sql_query(
        f"""SELECT e.entity_key, f.entity_id, f.reference_date, f.template_code, f.seq, f.cell_code, f.row_code,
                   f.column_code, f.row_label, f.column_label, f.sheet, f.key_descriptor, f.value
            FROM fact f JOIN entity e ON e.entity_id = f.entity_id
            WHERE f.template_code IN ({marks}) AND f.value IS NOT NULL
            ORDER BY f.template_code, e.entity_key, f.reference_date, f.seq""", conn, params=TEMPLATES)


def load_anchors(conn: sqlite3.Connection):
    t1 = {(r.entity_key, r.period_end): r.value for r in pd.read_sql_query(
        """SELECT entity_key, period_end, value FROM clean_period_fact
           WHERE template_code = 'K_61.00' AND row_code = '0020' AND measure_col = 10 AND value > 0""",
        conn).itertuples()}
    ta = {(r.entity_key, r.period_end): r.size_basis_eur for r in pd.read_sql_query(
        "SELECT entity_key, period_end, size_basis_eur FROM entity_assets WHERE size_basis_eur > 0",
        conn).itertuples()}
    raw_km1 = set(map(tuple, pd.read_sql_query(
        """SELECT DISTINCT e.entity_key, f.reference_date FROM fact f JOIN entity e ON e.entity_id = f.entity_id
           WHERE f.template_code = 'K_61.00' AND f.row_code = '0020' AND f.column_code = '0010'
             AND f.value IS NOT NULL""", conn).values))
    return t1, ta, raw_km1


def decide(stat, anchor, raw_present, ok, wide, fit, abs_range=(0.0, 5e12), factors=FACTORS):
    """Return (factor, quality, check, detail). factor None removes the filing."""
    if stat is None or not math.isfinite(stat):
        return 1.0, "untested", "", "no statistic"
    if stat == 0:
        return 1.0, "untested", "", "statistic is 0"
    if anchor:
        r = stat / anchor
        if ok[0] <= r <= ok[1]:
            return 1.0, "ok", "", f"ratio {r:.3g}"
        if wide[0] <= r <= wide[1]:
            return 1.0, "ok_wide", "", f"ratio {r:.3g}"
        fits = [f for f in factors if fit[0] <= r * f <= fit[1]]
        if len(fits) == 1:
            return fits[0], "rescaled", "scale_vs_anchor", f"ratio {r:.3g} before the factor"
        return None, "quarantined", "scale_inconsistent", f"ratio {r:.3g} to the anchor and no single factor fits"
    if raw_present:
        return None, "quarantined", "scale_unresolved", "KM1 of this filing failed the scale test"
    if abs_range[0] <= abs(stat) <= abs_range[1]:
        return 1.0, "unverified", "", "no anchor for this period"
    return None, "quarantined", "implausible_size", f"statistic {stat:.3g}"


def irrbb_convention(stat: float, t1: float):
    """Unique convention that gives a plausible ratio to Tier 1, or None."""
    ratios = {"eur": stat / t1, "thousand": stat * 1e3 / t1, "million": stat * 1e6 / t1,
              "x1e-3": stat * 1e-3 / t1, "fraction_of_t1": stat, "percent_of_t1": stat / 100.0}
    for band in (IRR_PRIMARY, IRR_WIDE):
        hits = [k for k, r in ratios.items() if band[0] <= r <= band[1]]
        if len(hits) == 1:
            return hits[0], ratios[hits[0]], band is IRR_PRIMARY
        if len(hits) > 1:
            return None, None, "ambiguous: " + ", ".join(hits)
    return None, None, "no convention fits"


MULT = {"eur": 1.0, "thousand": 1e3, "million": 1e6, "x1e-3": 1e-3}


def clean(df: pd.DataFrame, t1: dict, ta: dict, raw_km1: set):
    n = len(df)
    raw = df["value"].to_numpy(float)
    val, fac = raw.copy(), np.ones(n)
    qual = np.array(["ok"] * n, dtype=object)
    unit = np.array(["eur"] * n, dtype=object)
    period = np.array([None] * n, dtype=object)
    flags: list[dict] = []

    def flag(tpl, key, ref, check, action, factor, detail):
        flags.append({"reference_date": ref, "entity_key": key, "template_code": tpl, "period_offset": 0,
                      "row_code": "", "table_code": tpl, "check_name": check, "action": action,
                      "factor": factor, "detail": detail})

    def apply(idx, tpl, key, ref, factor, quality, check, detail):
        if factor is None:
            val[idx] = np.nan
            qual[idx] = "quarantined"
            flag(tpl, key, ref, check, "quarantine", None, detail)
            return
        val[idx] = raw[idx] * factor
        fac[idx] = factor
        qual[idx] = quality
        if factor != 1.0:
            unit[idx] = f"x{factor:g}"
            flag(tpl, key, ref, check, "rescale", factor, detail)

    ae1_enc: dict = {}
    for (tpl, key, ref), g in df[df.template_code == "K_20.01"].groupby(
            ["template_code", "entity_key", "reference_date"], sort=False):
        idx = g.index.to_numpy()
        period[idx] = ref
        tot = g[(g.row_code == "0010") & g.column_code.isin(["0010", "0060"])]["value"].sum()
        f, q, chk, det = decide(tot, ta.get((key, ref)), (key, ref) in raw_km1, (0.5, 2.0), (0.1, 10.0), (0.5, 2.0),
                                ABS_ASSETS)
        apply(idx, tpl, key, ref, f, q, chk, det)
        enc = g[(g.row_code == "0010") & (g.column_code == "0010")]["value"]
        if f is not None and len(enc) and enc.iloc[0] * f > 0:
            ae1_enc[(key, ref)] = float(enc.iloc[0] * f)

    for (tpl, key, ref), g in df[df.template_code.isin(["K_20.02", "K_20.03"])].groupby(
            ["template_code", "entity_key", "reference_date"], sort=False):
        idx = g.index.to_numpy()
        period[idx] = ref
        raw_present = (key, ref) in raw_km1
        anchor_enc = ae1_enc.get((key, ref))
        if tpl == "K_20.02":
            s = g[(g.row_code == "0250") & (g.column_code == "0010")]["value"]
            stat = float(s.iloc[0]) if len(s) else None
            bands = ((0.95, 3.0), (0.05, 30.0), (0.5, 3.0)) if anchor_enc else ((0.005, 1.0), (0.0005, 2.0), (0.005, 1.0))
        else:
            s = g[(g.row_code == "0010") & (g.column_code == "0030")]["value"]
            stat = float(s.iloc[0]) if len(s) else None
            if not stat:
                s = g[(g.row_code == "0010") & (g.column_code == "0010")]["value"]
                stat = float(s.iloc[0]) if len(s) else None
            bands = ((0.3, 2.5), (0.005, 30.0), (0.3, 2.5)) if anchor_enc else ((0.001, 1.0), (0.0001, 2.0), (0.001, 1.0))
        anchor = anchor_enc or ta.get((key, ref))
        f, q, chk, det = decide(stat, anchor, raw_present, *bands)
        apply(idx, tpl, key, ref, f, q, chk, det)

    for (key, ref), g in df[df.template_code == "K_68.00"].groupby(["entity_key", "reference_date"], sort=False):
        idx = g.index.to_numpy()
        tpl = "K_68.00"
        current = g["column_code"].isin(["0010", "0030"]).to_numpy()
        period[idx[current]] = ref
        if (g["value"] == 0).all():
            apply(idx, tpl, key, ref, None, "quarantined", "zero_placeholder", "all values are 0")
            continue
        anchor = t1.get((key, ref))
        if not anchor:
            if (key, ref) in raw_km1:
                apply(idx, tpl, key, ref, None, "quarantined", "scale_unresolved", "KM1 of this filing failed the scale test")
            else:
                qual[idx] = "unverified"
            continue
        eve = g[g.column_code.isin(["0010", "0020"])]["value"].abs()
        stat = float(eve.max()) if len(eve) else float(g["value"].abs().max())
        if stat == 0:
            qual[idx] = "untested"
            continue
        conv, ratio, info = irrbb_convention(stat, anchor)
        if conv is None:
            apply(idx, tpl, key, ref, None, "quarantined", "irrbb_convention", info)
            continue
        if conv in MULT:
            quality = ("ok" if info else "ok_wide") if conv == "eur" else "rescaled"
            apply(idx, tpl, key, ref, MULT[conv], quality, "irrbb_unit", f"{conv}; ratio to Tier 1 {ratio:.3g}")
            if conv != "eur":
                unit[idx] = conv
            continue
        base = anchor if conv == "fraction_of_t1" else anchor / 100.0
        for i, col in zip(idx, g["column_code"]):
            if col == "0010":
                val[i], fac[i], qual[i], unit[i] = raw[i] * base, base, "converted", conv
            else:
                val[i], qual[i] = np.nan, "quarantined"
        flag(tpl, key, ref, "irrbb_unit", "convert", None, f"{conv}; EVE current period times Tier 1; other columns removed")

    out = df.drop(columns="value").copy()
    out["period_end"] = period
    out["value_raw"], out["value"] = raw, val
    out["quality"], out["unit_inferred"], out["factor"] = qual, unit, fac
    cols = ["entity_key", "entity_id", "reference_date", "template_code", "seq", "cell_code", "row_code", "column_code",
            "row_label", "column_label", "sheet", "key_descriptor", "period_end", "value_raw", "value", "quality",
            "unit_inferred", "factor"]
    flag_cols = ["reference_date", "entity_key", "template_code", "period_offset", "row_code", "table_code",
                 "check_name", "action", "factor", "detail"]
    return out[cols], pd.DataFrame(flags, columns=flag_cols)


def family_note(code: str) -> tuple[str, str]:
    """Status and note of a template that has no clean layer yet."""
    num = float(code[2:])
    if num < 1:
        return "text only", "Narrative text. HTML escapes occur in some facts."
    if code == "K_01.00":
        return "not clean", "Not tested."
    if num < 9:
        return "not clean", ("Sums pass in 98.6% of tests. Non-monetary cells (alpha in K_02.00, PD and LGD in K_04.00) "
                             "carry FX or unit factors. Whole-filing unit errors are not tested.")
    if num < 20 and code not in ("K_19.01", "K_19.02", "K_19.03"):
        return "not clean", ("Securitisation, market risk, and CVA templates. Sums pass in 98.6% of tests. "
                             "Whole-filing unit errors are not tested.")
    if code.startswith("K_19."):
        return "not clean", "Operational risk. Event counts are scaled by FX or unit factors in 516 of 4,929 cells. Sums pass in 98.6%."
    if code == "K_30.01" or code.startswith("K_30."):
        return "not clean", "Remuneration. Pay per head is below EUR 10,000 in 14% of entity-dates (unit errors)."
    if num < 30:
        note = "Credit risk. Sums pass in 97% to 99.8% of tests. Whole-filing unit errors are not tested."
        if code == "K_26.00":
            note += " One exposure class has a blank key."
        if code == "K_29.02":
            note += " The layout changes between dates."
        return "not clean", note
    if 41 <= num <= 50:
        return "not clean", "Climate and GAR. About 4.5% of entity-dates have a wrong scale. K_43.00 keys contain the metric value."
    if code in ("K_70.00", "K_66.02", "K_64.01"):
        return "partly clean", 'Row "Total assets" is tested for scale (table entity_assets). The other rows have no test.'
    if code == "K_66.01":
        return "not clean", "Own funds (CC1). Sums fail in 2.7% to 4.7% of cells. CC1 shares the unit error of KM1 in one filing."
    if code == "K_67.01":
        return "not clean", "CCyB1. Open table with a blank key. About 5% of entity-filings have ratios in percentage points."
    if code == "K_67.02":
        return "not clean", "CCyB2. Ratios in percentage points in about 5% of entity-filings."
    if code == "K_71.00":
        return "not clean", "LR2. Leverage ratio in percentage points for 11 banks (for example Piraeus). T-1 is the previous disclosure date."
    if code in ("K_73.00", "K_74.00"):
        return "not clean", "LIQ1 and LIQ2. LCR and NSFR in percentage points for about 2%. Outflows fail the sum test in 8.4%."
    if code == "K_83.01":
        return "not downloaded", "The server times out. The downloader skips this template."
    if 80 <= num < 90:
        return "not clean", "Credit quality (CQ). CQ3 equals CR1 in all tested cases. Unit errors are not tested."
    if 90 <= num <= 93:
        return "not clean", "MREL and TLAC. Ratios in percentage points (NBG, 3 of 3 filings). Not tested."
    if 95 <= num <= 98:
        return "not clean", "Creditor ranking. Open tables with blank keys. Rank labels change between dates."
    if num >= 100:
        return "not clean", "G-SIB indicators. Three of 13 banks file in million or thousand."
    return "not clean", "Not assessed in detail. Unit errors are not tested."


CLEAN_NOTES = {
    "K_61.00": ("clean", "KM1. Tests: units, zeros, ratio units, period dates. Table clean_period_fact."),
    "K_60.00": ("clean", "OV1, column T only. Tests: scale against KM1, zero total. Table clean_period_fact."),
    "K_68.00": ("clean", "IRRBB1. Test: size against Tier 1. Six unit conventions are found and converted. "
                         "Table clean_fact. The last-period columns have no date."),
    "K_20.01": ("clean", "AE1. Test: encumbered plus unencumbered assets against total assets. "
                         "Values are medians of 4 quarters. Table clean_fact."),
    "K_20.02": ("clean", "AE2. Test: row 250 against the encumbered assets of AE1. Table clean_fact."),
    "K_20.03": ("clean", "AE3. Test: encumbered assets against the encumbered assets of AE1. Table clean_fact."),
}


def write_status(conn: sqlite3.Connection, clean_df: pd.DataFrame) -> None:
    tpl = pd.read_sql_query(
        """SELECT template_code, title FROM (SELECT template_code, title, ROW_NUMBER() OVER (
               PARTITION BY template_code ORDER BY reference_date DESC) rn FROM dim_template) WHERE rn = 1
           ORDER BY template_code""", conn)
    tpl["num"] = tpl["template_code"].str[2:].astype(float)
    tpl = tpl.sort_values("num")
    rows = []
    for r in tpl.itertuples():
        status, note = CLEAN_NOTES.get(r.template_code) or family_note(r.template_code)
        rows.append((r.template_code, (r.title or "").replace("|", "/")[:90], status, note))
    counts = pd.Series([s for _, _, s, _ in rows]).value_counts()
    lines = [
        "# P3DH template status",
        "",
        "This is the working note on the clean layer. The goal is a clean layer for every template. "
        "`scripts/clean_templates.py` writes this file at each run. Edit the lists `CLEAN_NOTES` and "
        "`family_note` in that script, not this file.",
        "",
        "Status values:",
        "",
        "- clean: unit, zero, and scale tests run. Use `clean_period_fact` or `clean_fact`.",
        "- partly clean: some cells are tested.",
        "- not clean: no test. Use the raw `fact` table for one bank in one filing only.",
        "- text only: no amounts.",
        "- not downloaded: no data in the database.",
        "",
        "Count by status: " + ", ".join(f"{k} {v}" for k, v in counts.items()) + ".",
        "",
        "## Result of the last run",
        "",
        "| Template | Entity-filings | ok | rescaled or converted | removed |",
        "|----------|----------------|----|-----------------------|---------|",
    ]
    per = clean_df.groupby(["template_code", "entity_key", "reference_date"])["quality"].agg(
        lambda s: "quarantined" if (s == "quarantined").all() else
        ("converted" if (s == "converted").any() else "rescaled" if (s == "rescaled").any() else "ok")).reset_index()
    for code in TEMPLATES:
        p = per[per.template_code == code]["quality"].value_counts()
        lines.append(f"| {code} | {int(p.sum())} | {int(p.get('ok', 0))} | "
                     f"{int(p.get('rescaled', 0) + p.get('converted', 0))} | {int(p.get('quarantined', 0))} |")
    lines += ["", "## All templates", "", "| Template | Title | Status | Note |", "|----------|-------|--------|------|"]
    lines += [f"| {c} | {t} | {s} | {n} |" for c, t, s, n in rows]
    lines += ["", "## Next in line", "",
              "1. Credit risk and credit quality (K_21.01 to K_29.02, K_80.00 to K_87.00): anchor on total assets and CR1.",
              "2. Liquidity and leverage (K_71.00 to K_74.00): anchor on KM1.",
              "3. MREL, TLAC, and creditor ranking (K_90.01 to K_98.00): ratio units.",
              "4. Climate, remuneration, and G-SIB (K_30.01, K_41.00 to K_50.00, K_100.00 to K_113.00).", ""]
    STATUS_DOC.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--dry-run", action="store_true", help="Print the summary and write nothing")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    for name in ("clean_period_fact", "entity_assets"):
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (name,)).fetchone():
            print(f"{name} is missing. Run clean_p3dh.py and classify_p3dh.py first.", file=sys.stderr)
            return 1
    df = load_facts(conn)
    t1, ta, raw_km1 = load_anchors(conn)
    out, flags = clean(df, t1, ta, raw_km1)
    if out.duplicated(["template_code", "entity_id", "reference_date", "seq"]).any():
        raise RuntimeError("duplicate keys in clean_fact")

    summary = out.groupby(["template_code", "quality"]).size().unstack(fill_value=0)
    print(summary.to_string())
    print("\nFilings changed or removed (by check):")
    print(flags.groupby(["template_code", "check_name", "action"]).size().rename("n").reset_index().to_string(index=False))
    if args.dry_run:
        return 0
    with conn:
        out.to_sql("clean_fact", conn, if_exists="replace", index=False)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_clean_fact ON clean_fact(template_code, entity_key, reference_date)")
        conn.executemany("DELETE FROM dq_flag WHERE template_code = ?", [(t,) for t in TEMPLATES])
        flags.to_sql("dq_flag", conn, if_exists="append", index=False)
        conn.executescript(VIEW)
    write_status(conn, out)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
