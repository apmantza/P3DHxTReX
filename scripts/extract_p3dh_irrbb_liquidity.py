"""
scripts/extract_p3dh_irrbb_liquidity.py — Extract IRRBB, Liquidity, Funding & MREL templates for 31/12/2025.

Outputs:
    data/extracted/p3dh_irrbb_liquidity_funding_mrel_2025H2.csv

Templates extracted:
    IRRBB:     K_68.00, K_00.04
    Liquidity: K_72.00, K_73.00, K_74.00
    Funding:   K_70.00, K_71.00, K_20.01, K_20.02, K_20.03, K_64.01, K_64.03
    MREL/TLAC: K_90.01, K_91.00, K_93.00, K_95.00, K_96.00, K_97.00, K_98.00
    Key metrics: K_61.00, K_60.00, K_66.01, K_66.02
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
P3DH_DB = PROJECT_ROOT / "data" / "processed" / "p3dh.sqlite"
BBIRR_DB = PROJECT_ROOT / "data" / "processed" / "bbirr.db"
OUTPUT_DIR = PROJECT_ROOT / "data" / "extracted"
OUTPUT_FILE = OUTPUT_DIR / "p3dh_irrbb_liquidity_funding_mrel_2025H2.csv"

# Template codes to extract (plain codes, will match both plain and descriptive names)
TEMPLATE_CODES = sorted(
    set(
        [
            # IRRBB
            "K_68.00",
            "K_00.04",
            # Liquidity
            "K_72.00",
            "K_73.00",
            "K_74.00",
            # Funding structure / Leverage
            "K_70.00",
            "K_71.00",
            "K_20.01",
            "K_20.02",
            "K_20.03",
            "K_64.01",
            "K_64.03",
            # MREL / TLAC / Creditor ranking
            "K_90.01",
            "K_91.00",
            "K_93.00",
            "K_95.00",
            "K_96.00",
            "K_97.00",
            "K_98.00",
            # Key metrics & Own funds (for enrichment context)
            "K_61.00",
            "K_60.00",
            "K_66.01",
            "K_66.02",
        ]
    )
)

CATEGORY_MAP = {
    "K_68.00": "IRRBB",
    "K_00.04": "IRRBB",
    "K_72.00": "Liquidity",
    "K_73.00": "Liquidity",
    "K_74.00": "Liquidity",
    "K_70.00": "Funding",
    "K_71.00": "Funding",
    "K_20.01": "Funding",
    "K_20.02": "Funding",
    "K_20.03": "Funding",
    "K_64.01": "Funding",
    "K_64.03": "Funding",
    "K_90.01": "MREL/TLAC",
    "K_91.00": "MREL/TLAC",
    "K_93.00": "MREL/TLAC",
    "K_95.00": "MREL/TLAC",
    "K_96.00": "MREL/TLAC",
    "K_97.00": "MREL/TLAC",
    "K_98.00": "MREL/TLAC",
    "K_61.00": "Key metrics",
    "K_60.00": "Key metrics",
    "K_66.01": "Own funds",
    "K_66.02": "Own funds",
}

TEMPLATE_LABELS = {
    "K_68.00": "IRRBB1 - Interest rate risks of non-trading book",
    "K_00.04": "IRRBB narrative disclosure",
    "K_72.00": "LR3 - Leverage ratio split-up of exposures",
    "K_73.00": "LIQ1 - Liquidity Coverage Ratio (LCR)",
    "K_74.00": "LIQ2 - Net Stable Funding Ratio (NSFR)",
    "K_70.00": "LR1 - Leverage ratio summary reconciliation",
    "K_71.00": "LR2 - Leverage ratio common disclosure",
    "K_20.01": "AE1 - Encumbered and unencumbered assets",
    "K_20.02": "AE2 - Collateral received and own debt securities issued",
    "K_20.03": "AE3 - Sources of encumbrance",
    "K_64.01": "LI1 - Differences between accounting and prudential scope",
    "K_64.03": "LI2 - Main sources of differences between regulatory exposures",
    "K_90.01": "KM2 - Key metrics MREL and G-SII requirement",
    "K_91.00": "TLAC1 - Composition MREL and G-SII requirement",
    "K_93.00": "ILAC - Internal loss absorbing capacity",
    "K_95.00": "Creditor ranking - Entity that is not a resolution entity",
    "K_96.00": "TLAC2b - Creditor ranking - Entity not resolution entity (TLAC)",
    "K_97.00": "TLAC3 - Creditor ranking - resolution entity",
    "K_98.00": "TLAC3b - Creditor ranking - resolution entity (TLAC)",
    "K_61.00": "KM1 - Key metrics template",
    "K_60.00": "OV1 - Overview of total risk exposure amounts",
    "K_66.01": "CC1 - Composition of regulatory own funds",
    "K_66.02": "CC2 - Reconciliation of regulatory own funds to balance sheet",
}


def extract_template_code(template_name: str | None) -> str | None:
    """Extract K_XX.YY code from a template name like 'K_68.00 - EU IRRBB1...' or plain 'K_68.00'."""
    if not template_name:
        return None
    m = re.match(r"^(K_\d+\.\d+)", template_name.strip())
    return m.group(1) if m else None


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # ── 1. Read P3DH facts ──────────────────────────────────────────────
    p3dh = sqlite3.connect(str(P3DH_DB))
    df = pd.read_sql(
        "SELECT * FROM p3dh_facts WHERE reference_date = '2025-12-31'",
        p3dh,
    )
    p3dh.close()
    print(
        f"Loaded {len(df):,} rows for 2025-12-31 ({df['entity_name'].nunique()} banks)"
    )

    # ── 2. Filter to relevant templates ────────────────────────────────
    df["template_code"] = df["template"].apply(extract_template_code)
    mask = df["template_code"].isin(TEMPLATE_CODES)
    extracted = df[mask].copy()
    print(
        f"Filtered to {len(extracted):,} rows across {extracted['template_code'].nunique()} template codes"
    )

    # Combine plain and descriptive template variants (e.g. 'K_68.00' and 'K_68.00 - EU IRRBB1...')
    # For row dedup: keep the descriptive name where available, else plain code
    # But first, let's just add category and label columns
    extracted["category"] = extracted["template_code"].map(CATEGORY_MAP)
    extracted["template_label"] = extracted["template_code"].map(TEMPLATE_LABELS)

    # ── 3. Load data dictionary for row/column labels ───────────────────
    bbirr = sqlite3.connect(str(BBIRR_DB))
    dd = pd.read_sql("SELECT * FROM p3dh_data_dictionary", bbirr)
    bbirr.close()
    print(
        f"Data dictionary: {len(dd):,} entries across {dd['template_code'].nunique()} template codes"
    )

    # Merge data dictionary labels (row_name_dd, col_name_dd, unit, section)
    dd_lookup = dd.rename(
        columns={
            "row_name": "dd_row_name",
            "col_name": "dd_col_name",
        }
    )
    dd_lookup["row_code"] = dd_lookup["row_code"].astype(str).str.strip()
    dd_lookup["col_code"] = dd_lookup["col_code"].astype(str).str.strip()

    # Join on (template_code, row_code, col_code)
    extracted["row"] = extracted["row"].astype(str).str.strip()
    extracted["column"] = extracted["column"].astype(str).str.strip()

    # Merge row labels
    dd_rows = dd_lookup[
        ["template_code", "row_code", "dd_row_name", "unit", "section", "module_name"]
    ].drop_duplicates(subset=["template_code", "row_code"])
    extracted = extracted.merge(
        dd_rows,
        left_on=["template_code", "row"],
        right_on=["template_code", "row_code"],
        how="left",
        suffixes=("", "_dd"),
    )

    # Merge column labels
    dd_cols = dd_lookup[["template_code", "col_code", "dd_col_name"]].drop_duplicates(
        subset=["template_code", "col_code"]
    )
    extracted = extracted.merge(
        dd_cols,
        left_on=["template_code", "column"],
        right_on=["template_code", "col_code"],
        how="left",
    )

    # ── 4. Deduplicate: prefer descriptive template name over plain code ──
    # When both 'K_68.00' and 'K_68.00 - EU IRRBB1...' exist for the same bank,
    # keep the one with the descriptive name (longer name = richer info)
    # Build dedup key: (entity_name, template_code, row, column, cell, open_key)
    extracted["dedup_key"] = (
        extracted["entity_name"]
        + "|"
        + extracted["template_code"]
        + "|"
        + extracted["row"].fillna("")
        + "|"
        + extracted["column"].fillna("")
        + "|"
        + extracted["cell"].fillna("")
        + "|"
        + extracted["open_key"].fillna("")
    )

    # Sort so descriptive template names come after plain ones
    extracted["_name_len"] = extracted["template"].str.len()
    before = len(extracted)

    # For duplicate keys, keep the row with the longer template name (descriptive)
    extracted = extracted.sort_values("_name_len", ascending=False)
    # Also prefer rows that have row_name / column_name filled
    extracted = extracted.drop_duplicates(subset=["dedup_key"], keep="first")
    after = len(extracted)
    print(f"Dedup: {before:,} → {after:,} rows (removed {before - after:,} duplicates)")

    # ── 5. Select and order output columns ─────────────────────────────
    # Use richer names where available
    extracted["row_label"] = (
        extracted["dd_row_name"].fillna(extracted["row_name"]).fillna(extracted["row"])
    )
    extracted["col_label"] = (
        extracted["dd_col_name"]
        .fillna(extracted["column_name"])
        .fillna(extracted["column"])
    )

    output_cols = [
        "category",
        "template_code",
        "template_label",
        "template",
        "module_name_dd" if "module_name_dd" in extracted.columns else "module_name",
        "section" if "section" in extracted.columns else "section",
        "entity_name",
        "country",
        "cell",
        "open_key",
        "row",
        "row_label",
        "column",
        "col_label",
        "sheet",
        "fact_value",
        "unit" if "unit" in extracted.columns else "unit",
    ]

    # Resolve column names that might have suffixes from merges
    col_map = {}
    for c in output_cols:
        if c in extracted.columns:
            col_map[c] = c
        elif c + "_dd" in extracted.columns:
            col_map[c + "_dd"] = c
        elif c.replace("_dd", "") in extracted.columns:
            col_map[c.replace("_dd", "")] = c

    actual_cols = []
    for src, dst in col_map.items():
        actual_cols.append(src)

    result = extracted[list(actual_cols)].copy()
    result.columns = [col_map[c] for c in actual_cols]

    # Clean up
    result = result.drop(columns=["dedup_key", "_name_len"], errors="ignore")
    result = result.sort_values(
        ["category", "template_code", "entity_name", "row", "column"]
    ).reset_index(drop=True)

    # ── 6. Write output ────────────────────────────────────────────────
    result.to_csv(str(OUTPUT_FILE), index=False, encoding="utf-8-sig")
    print(f"\nExported {len(result):,} rows to {OUTPUT_FILE}")
    print(f"\nBreakdown by category:")
    for cat in [
        "IRRBB",
        "Liquidity",
        "Funding",
        "MREL/TLAC",
        "Key metrics",
        "Own funds",
    ]:
        sub = result[result["category"] == cat]
        if len(sub) > 0:
            templates = sub.groupby("template_code")["entity_name"].nunique().to_dict()
            print(
                f"  {cat:12} {len(sub):>5} rows, {sub['entity_name'].nunique():>3} banks | {templates}"
            )

    print(f"\nBreakdown by template code:")
    for tc in sorted(result["template_code"].unique()):
        sub = result[result["template_code"] == tc]
        label = sub["template_label"].iloc[0] if len(sub) > 0 else ""
        print(
            f"  {tc:10} {len(sub):>5} rows, {sub['entity_name'].nunique():>3} banks | {label}"
        )


if __name__ == "__main__":
    main()
