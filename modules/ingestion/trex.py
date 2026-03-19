from __future__ import annotations

from pathlib import Path
from typing import Dict

import pandas as pd

from modules.ingestion.common import IngestionResult, as_path, require_paths
from modules.ingestion.sdd import attach_sdd_metadata, summarize_sdd_coverage


TREX_FILES = {
    "tr_oth": "tr_oth.csv",
    "tr_cre": "tr_cre.csv",
    "tr_sov": "tr_sov.csv",
    "tr_mrk": "tr_mrk.csv",
}


def load_trex(root_dir: str | Path) -> Dict[str, pd.DataFrame]:
    """Load EBA Transparency Exercise CSVs into DataFrames."""
    root = as_path(root_dir)
    file_paths = {key: root / filename for key, filename in TREX_FILES.items()}
    require_paths(file_paths.values())

    data = {}
    for key, file_path in file_paths.items():
        data[key] = pd.read_csv(file_path, encoding="utf-8")
    return data


def summarize_trex(root_dir: str | Path) -> list[IngestionResult]:
    """Return row/column counts for core TREX files."""
    frames = load_trex(root_dir)
    results: list[IngestionResult] = []
    for key, frame in frames.items():
        results.append(
            IngestionResult(
                name=key,
                path=as_path(root_dir) / TREX_FILES[key],
                rows=len(frame.index),
                columns=len(frame.columns),
            )
        )
    return results


def enrich_trex_with_sdd(
    root_dir: str | Path,
    sdd_path: str | Path,
) -> Dict[str, pd.DataFrame]:
    """Load TREX data and attach SDD metadata columns."""
    data = load_trex(root_dir)
    from modules.ingestion.sdd import load_sdd

    sdd = load_sdd(sdd_path)
    enriched: Dict[str, pd.DataFrame] = {}
    for key, frame in data.items():
        csv_name = TREX_FILES[key]
        enriched_frame = attach_sdd_metadata(frame, csv_name, sdd)
        enriched[key] = enriched_frame
    return enriched


def summarize_trex_sdd_coverage(
    root_dir: str | Path,
    sdd_path: str | Path,
) -> Dict[str, dict]:
    """Return SDD match rates by TREX file."""
    enriched = enrich_trex_with_sdd(root_dir, sdd_path)
    return {name: summarize_sdd_coverage(frame) for name, frame in enriched.items()}


def extract_trex_unmatched(
    root_dir: str | Path,
    sdd_path: str | Path,
) -> pd.DataFrame:
    """Return unmatched TREX rows (no SDD category)."""
    enriched = enrich_trex_with_sdd(root_dir, sdd_path)
    unmatched_frames = []
    for name, frame in enriched.items():
        unmatched = frame[frame["Category"].isna()].copy()
        if not unmatched.empty:
            unmatched.insert(0, "source_file", TREX_FILES[name])
            unmatched_frames.append(unmatched)
    if unmatched_frames:
        return pd.concat(unmatched_frames, ignore_index=True)
    return pd.DataFrame()
