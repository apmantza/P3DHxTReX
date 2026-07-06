from __future__ import annotations

from pathlib import Path

import pandas as pd

from modules.ingestion.common import as_path, require_paths


def build_peerdata(canonical_path: str | Path) -> pd.DataFrame:
    """Convert canonical facts into a PeerData-style normalized table."""
    path = as_path(canonical_path)
    require_paths([path])
    frame = pd.read_csv(path, encoding="utf-8-sig")

    frame = frame.rename(
        columns={
            "bank_name": "bank_name",
            "template": "template",
            "row": "item",
            "column": "column",
            "reference_date": "period",
            "value": "amount",
            "source": "source",
        }
    )

    frame["period"] = pd.to_datetime(frame["period"], errors="coerce")
    base_cols = ["bank_name", "period", "template", "item", "column", "amount", "source"]
    bank_cols = ["bank_lei"] if "bank_lei" in frame.columns else []
    label_cols = [col for col in frame.columns if col.endswith("_label")]
    return frame[bank_cols + base_cols + label_cols]
