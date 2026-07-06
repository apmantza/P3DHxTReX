from __future__ import annotations

from pathlib import Path

import pandas as pd

from modules.ingestion.canonical import load_trex_enriched
from modules.ingestion.common import as_path, require_paths


DIMENSION_MAP = {
    "Exposure": "trex_metadata_Exposure.csv",
    "Financial_instruments": "trex_metadata_Financial_instruments.csv",
    "ASSETS_Stages": "trex_metadata_ASSETS_Stages.csv",
    "ASSETS_FV": "trex_metadata_ASSETS_FV.csv",
    "Portfolio": "trex_metadata_Portfolio.csv",
    "Country": "trex_metadata_Country.csv",
    "Status": "trex_metadata_Status.csv",
    "Perf_Status": "trex_metadata_Perf_status.csv",
    "NACE_codes": "trex_metadata_NACE_codes.csv",
    "Accounting_portfolio": "trex_metadata_Accounting_portfolio.csv",
    "Maturity": "trex_metadata_Maturity.csv",
    "MKT_Modprod": "trex_metadata_MKT_Modprod.csv",
    "Mkt_risk": "trex_metadata_MKT_Risk.csv",
    "Fin_end_year": "trex_metadata_Fin_end_year.csv",
}


def _normalize_code(value: object) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def load_dimension_map(metadata_dir: str | Path) -> dict[str, dict[str, str]]:
    base = as_path(metadata_dir)
    require_paths([base])
    mappings: dict[str, dict[str, str]] = {}
    for dim, filename in DIMENSION_MAP.items():
        path = base / filename
        if not path.exists():
            continue
        df = pd.read_csv(path, header=None, encoding="utf-8-sig")
        if df.empty:
            continue
        df = df.iloc[:, :2]
        df.columns = ["code", "label"]
        df["code"] = df["code"].map(_normalize_code)
        df["label"] = df["label"].astype(str).str.strip()
        mappings[dim] = dict(zip(df["code"], df["label"]))
    return mappings


def enrich_trex_dimensions(trex: pd.DataFrame, metadata_dir: str | Path) -> pd.DataFrame:
    mappings = load_dimension_map(metadata_dir)
    enriched = trex.copy()
    for dim, mapping in mappings.items():
        if dim not in enriched.columns:
            continue
        label_col = f"{dim}_label"
        enriched[label_col] = enriched[dim].map(_normalize_code).map(mapping)
    return enriched


def build_canonical_enriched(
    canonical_path: str | Path,
    trex_enriched_path: str | Path,
    metadata_dir: str | Path,
) -> pd.DataFrame:
    canonical = pd.read_csv(as_path(canonical_path), encoding="utf-8-sig")
    trex = load_trex_enriched(trex_enriched_path)
    trex = enrich_trex_dimensions(trex, metadata_dir)

    if "Template" in trex.columns and "template" not in trex.columns:
        trex["template"] = trex["Template"]
    if "Sheet" in trex.columns and "template" not in trex.columns:
        trex["template"] = trex["Sheet"]
    if "row" not in trex.columns and "Item" in trex.columns:
        trex["row"] = trex["Item"]
    if "column" not in trex.columns and "Column" in trex.columns:
        trex["column"] = trex["Column"]

    trex_join_cols = [
        "NSA",
        "template",
        "row",
        "column",
        "reference_date",
    ]
    trex_join_cols = [col for col in trex_join_cols if col in trex.columns]
    trex_labels = [col for col in trex.columns if col.endswith("_label")]
    trex_dim_cols = [
        "Exposure",
        "Financial_instruments",
        "ASSETS_Stages",
        "ASSETS_FV",
        "Portfolio",
        "Country",
        "Status",
        "Perf_Status",
        "NACE_codes",
        "Accounting_portfolio",
        "Maturity",
        "MKT_Modprod",
        "Mkt_risk",
        "Fin_end_year",
    ]
    trex_dim_cols = [col for col in trex_dim_cols if col in trex.columns]

    trex_subset = trex[trex_join_cols + trex_dim_cols + trex_labels].copy()
    trex_subset = trex_subset.rename(columns={"NSA": "bank_name"})

    for col in ("row", "column"):
        if col in canonical.columns:
            canonical[col] = canonical[col].astype(str)
        if col in trex_subset.columns:
            trex_subset[col] = trex_subset[col].astype(str)

    canonical["reference_date"] = pd.to_datetime(canonical["reference_date"], errors="coerce")
    trex_subset["reference_date"] = pd.to_datetime(trex_subset["reference_date"], errors="coerce")

    enriched = canonical.merge(
        trex_subset,
        on=["bank_name", "template", "row", "column", "reference_date"],
        how="left",
    )
    return enriched
