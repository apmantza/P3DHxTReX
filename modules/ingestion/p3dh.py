from __future__ import annotations

from pathlib import Path
from typing import Dict

import pandas as pd

from modules.ingestion.common import IngestionResult, as_path, require_paths


def load_p3dh(excel_path: str | Path) -> Dict[str, pd.DataFrame]:
    """Load P3DH workbook into a dict of sheet DataFrames."""
    path = as_path(excel_path)
    require_paths([path])

    workbook = pd.read_excel(path, sheet_name=None, engine="openpyxl")
    return workbook


def summarize_p3dh(excel_path: str | Path) -> list[IngestionResult]:
    """Return row/column counts for all P3DH sheets."""
    sheets = load_p3dh(excel_path)
    results: list[IngestionResult] = []
    for name, frame in sheets.items():
        results.append(
            IngestionResult(
                name=name,
                path=as_path(excel_path),
                rows=len(frame.index),
                columns=len(frame.columns),
            )
        )
    return results


def summarize_p3dh_directory(p3dh_dir: str | Path) -> list[IngestionResult]:
    """Return row/column counts for legacy Excel and API CSV P3DH files."""
    dir_path = as_path(p3dh_dir)
    results: list[IngestionResult] = []
    for xlsx_file in sorted(dir_path.rglob("*.xlsx")):
        try:
            sheets = load_p3dh(xlsx_file)
            for name, frame in sheets.items():
                results.append(
                    IngestionResult(
                        name=name,
                        path=xlsx_file,
                        rows=len(frame.index),
                        columns=len(frame.columns),
                    )
                )
        except Exception as e:
            print(f"Skipping {xlsx_file.name}: {e}")

    for csv_file in sorted(dir_path.rglob("*.csv")):
        try:
            frame = pd.read_csv(csv_file, encoding="utf-8-sig", low_memory=False)
            results.append(
                IngestionResult(
                    name="csv",
                    path=csv_file,
                    rows=len(frame.index),
                    columns=len(frame.columns),
                )
            )
        except Exception as e:
            print(f"Skipping {csv_file.name}: {e}")
    return results
