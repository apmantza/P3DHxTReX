from __future__ import annotations

from pathlib import Path

import pandas as pd

from modules.ingestion.common import as_path, require_paths


INSTITUTIONS_SHEET = "List of Institutions"


def load_institutions(metadata_path: str | Path) -> pd.DataFrame:
    path = as_path(metadata_path)
    require_paths([path])
    df = pd.read_excel(path, sheet_name=INSTITUTIONS_SHEET, header=1)
    return df


def export_institutions(metadata_path: str | Path, output_path: str | Path) -> pd.DataFrame:
    df = load_institutions(metadata_path)
    out = as_path(output_path)
    df.to_csv(out, index=False, encoding="utf-8-sig")
    return df


def export_all_sheets(metadata_path: str | Path, output_dir: str | Path) -> dict[str, Path]:
    """Export all TR_Metadata sheets as CSVs."""
    path = as_path(metadata_path)
    require_paths([path])
    out_dir = as_path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    workbook = pd.ExcelFile(path)
    exported: dict[str, Path] = {}
    for sheet in workbook.sheet_names:
        df = pd.read_excel(path, sheet_name=sheet, header=1)
        safe_name = sheet.replace(" ", "_").replace("/", "-")
        out_path = out_dir / f"trex_metadata_{safe_name}.csv"
        df.to_csv(out_path, index=False, encoding="utf-8-sig")
        exported[sheet] = out_path
    return exported
