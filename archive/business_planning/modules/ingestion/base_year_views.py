from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from modules.ingestion.common import as_path, require_paths


def _sanitize_metric_id(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", text)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned


def build_base_year_wide(base_year_path: str | Path) -> pd.DataFrame:
    path = as_path(base_year_path)
    require_paths([path])
    df = pd.read_csv(path, encoding="utf-8-sig")

    df["template"] = df["template"].astype(str)
    df["item"] = df["item"].astype(str)
    df["column"] = df["column"].astype(str)

    df["metric_id"] = df["template"] + "__" + df["item"] + "__" + df["column"]
    df["metric_id"] = df["metric_id"].map(_sanitize_metric_id)

    wide = df.pivot_table(
        index=["bank_name"],
        columns="metric_id",
        values="amount",
        aggfunc="first",
    ).reset_index()
    return wide


def build_base_year_longitudinal(base_year_path: str | Path) -> pd.DataFrame:
    """Build base year with period dimension for YoY/QoQ."""
    path = as_path(base_year_path)
    require_paths([path])
    df = pd.read_csv(path, encoding="utf-8-sig")

    df["template"] = df["template"].astype(str)
    df["item"] = df["item"].astype(str)
    df["column"] = df["column"].astype(str)

    df["metric_id"] = df["template"] + "__" + df["item"] + "__" + df["column"]
    df["metric_id"] = df["metric_id"].map(_sanitize_metric_id)

    df = df.sort_values(["metric_id", "period"])
    return df


def add_yoy_qoq(df: pd.DataFrame) -> pd.DataFrame:
    """Add YoY% and QoQ% changes for each metric."""
    result = []
    for metric_id, grp in df.groupby("metric_id"):
        grp = grp.sort_values("period")
        grp = grp.copy()
        grp["amount_yoy"] = grp["amount"].pct_change(periods=4)
        grp["amount_qoq"] = grp["amount"].pct_change(periods=1)
        grp["amount_yoy"] = grp["amount_yoy"].replace([float("inf"), float("-inf")], float("nan"))
        grp["amount_qoq"] = grp["amount_qoq"].replace([float("inf"), float("-inf")], float("nan"))
        result.append(grp)
    return pd.concat(result, ignore_index=True)


def add_normalizations(df: pd.DataFrame) -> pd.DataFrame:
    """Add % of deposits and % of assets normalizations."""
    deposits_metric = [c for c in df["metric_id"].unique() if "deposit" in c.lower() and "customer" in c.lower()]
    assets_metric = [c for c in df["metric_id"].unique() if "total" in c.lower() and "asset" in c.lower()]

    if deposits_metric:
        deposits_col = deposits_metric[0]
        deposits_vals = df[df["metric_id"] == deposits_col].set_index("period")["amount"]
        df["deposits_base"] = df["period"].map(deposits_vals)
        df["pct_of_deposits"] = df["amount"] / df["deposits_base"]

    if assets_metric:
        assets_col = assets_metric[0]
        assets_vals = df[df["metric_id"] == assets_col].set_index("period")["amount"]
        df["assets_base"] = df["period"].map(assets_vals)
        df["pct_of_assets"] = df["amount"] / df["assets_base"]

    return df


def export_base_year_wide(base_year_path: str | Path, output_path: str | Path) -> pd.DataFrame:
    wide = build_base_year_wide(base_year_path)
    out = as_path(output_path)
    wide.to_csv(out, index=False, encoding="utf-8-sig")
    return wide


def export_base_year_enriched(base_year_path: str | Path, output_path: str | Path) -> pd.DataFrame:
    """Export base year with YoY%, QoQ%, and normalizations."""
    df = build_base_year_longitudinal(base_year_path)
    df = add_yoy_qoq(df)
    df = add_normalizations(df)
    out = as_path(output_path)
    df.to_csv(out, index=False, encoding="utf-8-sig")
    return df
