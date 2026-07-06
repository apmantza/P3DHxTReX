from __future__ import annotations

from pathlib import Path

import pandas as pd

from modules.ingestion.common import as_path, require_paths


SDD_SHEET = "SDD"
SDD_COLUMNS = ["CSV", "Template", "Collection", "Item", "Category", "Label"]


def load_sdd(sdd_path: str | Path) -> pd.DataFrame:
    path = as_path(sdd_path)
    require_paths([path])
    sdd = pd.read_excel(path, sheet_name=SDD_SHEET, header=1)
    missing = [col for col in SDD_COLUMNS if col not in sdd.columns]
    if missing:
        raise ValueError(f"SDD missing required columns: {', '.join(missing)}")
    return sdd[SDD_COLUMNS].copy()


def attach_sdd_metadata(
    frame: pd.DataFrame,
    csv_name: str,
    sdd: pd.DataFrame,
    template_column: str = "Sheet",
) -> pd.DataFrame:
    """Attach SDD category and template metadata to a TREX frame."""
    if template_column not in frame.columns:
        raise ValueError(f"Expected template column '{template_column}' in frame")
    if "Item" not in frame.columns or "Label" not in frame.columns:
        raise ValueError("Frame must include Item and Label columns")

    sdd_filtered = sdd[sdd["CSV"] == csv_name].copy()
    if sdd_filtered.empty:
        raise ValueError(f"No SDD rows for CSV '{csv_name}'")

    enriched = frame.copy()
    enriched = enriched.rename(columns={template_column: "Template"})

    merged = enriched.merge(
        sdd_filtered,
        how="left",
        on=["Template", "Item", "Label"],
        suffixes=("", "_sdd"),
    )
    return merged


def summarize_sdd_coverage(frame: pd.DataFrame) -> dict:
    """Return basic coverage stats for SDD merge."""
    total = len(frame.index)
    matched = int(frame["Category"].notna().sum()) if "Category" in frame.columns else 0
    return {
        "total_rows": total,
        "matched_rows": matched,
        "match_rate": (matched / total) if total else 0.0,
    }
