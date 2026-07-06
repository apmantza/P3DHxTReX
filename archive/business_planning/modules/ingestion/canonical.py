from __future__ import annotations

from pathlib import Path

import pandas as pd

from modules.ingestion.common import as_path, require_paths


def _normalize_key_series(series: pd.Series, pad: int | None = None) -> pd.Series:
    text = series.astype("string").str.replace(".0", "", regex=False).str.strip()
    if pad is not None:
        numeric_mask = text.str.fullmatch(r"\d+")
        text = text.where(~numeric_mask, text.str.zfill(pad))
    return text


def load_p3dh_normalized(path: str | Path) -> pd.DataFrame:
    p = as_path(path)
    require_paths([p])
    frame = pd.read_csv(p, encoding="utf-8-sig", low_memory=False)
    frame["reference_date"] = pd.to_datetime(frame["reference_date"], errors="coerce")
    return frame


def load_trex_enriched(path: str | Path) -> pd.DataFrame:
    p = as_path(path)
    require_paths([p])
    frame = pd.read_csv(p, encoding="utf-8-sig", low_memory=False)
    if "Period" in frame.columns:
        period_str = frame["Period"].astype(str).str.replace(".0", "", regex=False)
        parsed = pd.to_datetime(period_str, format="%Y%m", errors="coerce")
        frame["reference_date"] = parsed + pd.offsets.MonthEnd(0)
    return frame


def build_canonical(
    p3dh_path: str | Path,
    trex_path: str | Path,
) -> pd.DataFrame:
    """Build canonical facts with P3DH priority and TREX fill."""
    p3dh = load_p3dh_normalized(p3dh_path)
    trex = load_trex_enriched(trex_path)

    p3dh = p3dh.rename(
        columns={
            "entity_name": "bank_name",
            "template": "template",
            "row": "row",
            "column": "column",
            "fact_value": "value",
        }
    )
    p3dh = p3dh[[
        "bank_name",
        "template",
        "row",
        "column",
        "reference_date",
        "value",
    ]].copy()
    p3dh["bank_name"] = _normalize_key_series(p3dh["bank_name"])
    p3dh["template"] = _normalize_key_series(p3dh["template"])
    p3dh["row"] = _normalize_key_series(p3dh["row"], pad=4)
    p3dh["column"] = _normalize_key_series(p3dh["column"], pad=4)
    p3dh["source"] = "P3DH"

    trex = trex.rename(
        columns={
            "Item": "row",
            "Column": "column",
            "Amount": "value",
            "Sheet": "template",
            "LEI_Code": "bank_lei",
        }
    )
    if "Template" in trex.columns:
        trex["template"] = trex["Template"]
    if "Label" in trex.columns:
        trex["row_label"] = trex["Label"]

    trex = trex[[
        "bank_lei",
        "template",
        "row",
        "column",
        "reference_date",
        "value",
    ]].copy()
    trex["bank_name"] = trex["bank_lei"]
    trex["bank_name"] = _normalize_key_series(trex["bank_name"])
    trex["template"] = _normalize_key_series(trex["template"])
    trex["row"] = _normalize_key_series(trex["row"], pad=4)
    trex["column"] = _normalize_key_series(trex["column"], pad=4)
    trex["source"] = "TREX"

    combined = pd.concat([p3dh, trex], ignore_index=True)

    # P3DH priority, then most recent reference_date
    combined["source_rank"] = combined["source"].map({"P3DH": 0, "TREX": 1}).fillna(2)
    combined = combined.sort_values(
        by=["bank_name", "template", "row", "column", "source_rank", "reference_date"],
        ascending=[True, True, True, True, True, False],
    )

    canonical = combined.drop_duplicates(
        subset=["bank_name", "template", "row", "column"],
        keep="first",
    ).drop(columns=["source_rank"])

    return canonical


def build_divergence_report(
    p3dh_path: str | Path,
    trex_path: str | Path,
    threshold: float = 0.05,
) -> pd.DataFrame:
    """Report overlaps where P3DH vs TREX diverge beyond threshold."""
    p3dh = load_p3dh_normalized(p3dh_path)
    trex = load_trex_enriched(trex_path)

    p3dh = p3dh.rename(
        columns={
            "entity_name": "bank_name",
            "template": "template",
            "row": "row",
            "column": "column",
            "fact_value": "p3dh_value",
        }
    )
    p3dh = p3dh[["bank_name", "template", "row", "column", "reference_date", "p3dh_value"]]
    p3dh["bank_name"] = _normalize_key_series(p3dh["bank_name"])
    p3dh["template"] = _normalize_key_series(p3dh["template"])
    p3dh["row"] = _normalize_key_series(p3dh["row"], pad=4)
    p3dh["column"] = _normalize_key_series(p3dh["column"], pad=4)

    trex = trex.rename(
        columns={
            "NSA": "bank_name",
            "Sheet": "sheet",
            "Item": "row",
            "Column": "column",
            "Amount": "trex_value",
        }
    )
    if "Template" in trex.columns:
        trex["template"] = trex["Template"]
    elif "sheet" in trex.columns:
        trex["template"] = trex["sheet"]

    trex = trex[["bank_name", "template", "row", "column", "reference_date", "trex_value"]]
    trex["bank_name"] = _normalize_key_series(trex["bank_name"])
    trex["template"] = _normalize_key_series(trex["template"])
    trex["row"] = _normalize_key_series(trex["row"], pad=4)
    trex["column"] = _normalize_key_series(trex["column"], pad=4)

    merged = p3dh.merge(
        trex,
        on=["bank_name", "template", "row", "column"],
        suffixes=("_p3dh", "_trex"),
    )
    merged = merged.dropna(subset=["p3dh_value", "trex_value"])
    merged["abs_diff"] = (merged["p3dh_value"] - merged["trex_value"]).abs()
    merged["rel_diff"] = merged["abs_diff"] / merged["trex_value"].abs().replace(0, pd.NA)
    report = merged[merged["rel_diff"] >= threshold].copy()
    return report
