from __future__ import annotations

from pathlib import Path

import pandas as pd

from modules.ingestion.common import as_path, require_paths


def _normalize_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


def find_bank_names(peerdata: pd.DataFrame, query: str) -> list[str]:
    needle = _normalize_name(query)
    names = peerdata["bank_name"].dropna().unique().tolist()
    exact = [name for name in names if _normalize_name(name) == needle]
    if exact:
        return exact
    contains = [name for name in names if needle in _normalize_name(name)]
    return contains


def resolve_bank_name(
    peerdata: pd.DataFrame,
    institutions: pd.DataFrame | None,
    query: str,
) -> str:
    """Resolve a user-provided bank name using TR_Metadata first, then peerdata."""
    if institutions is not None and not institutions.empty:
        name_col = "Name" if "Name" in institutions.columns else None
        if name_col:
            inst_names = institutions[name_col].dropna().unique().tolist()
            inst_matches = [n for n in inst_names if _normalize_name(n) == _normalize_name(query)]
            if not inst_matches:
                inst_matches = [n for n in inst_names if _normalize_name(query) in _normalize_name(n)]
            if inst_matches:
                return inst_matches[0]

    matches = find_bank_names(peerdata, query)
    if not matches:
        raise ValueError(f"Bank not found in peer data: {query}")
    return matches[0]


def resolve_bank_lei(
    institutions: pd.DataFrame | None,
    query: str,
) -> str | None:
    if institutions is None or institutions.empty:
        return None
    if "Name" not in institutions.columns or "LEI_Code" not in institutions.columns:
        return None
    inst = institutions.copy()
    inst["_name_norm"] = inst["Name"].astype(str).map(_normalize_name)
    needle = _normalize_name(query)
    exact = inst[inst["_name_norm"] == needle]
    if exact.empty:
        exact = inst[inst["_name_norm"].str.contains(needle, na=False)]
    if exact.empty:
        return None
    lei = exact.iloc[0]["LEI_Code"]
    return str(lei) if pd.notna(lei) else None


def build_base_year(
    peerdata_path: str | Path,
    bank_name: str,
    institutions_path: str | Path | None = None,
) -> pd.DataFrame:
    path = as_path(peerdata_path)
    require_paths([path])
    peerdata = pd.read_csv(path, encoding="utf-8-sig")
    peerdata["period"] = pd.to_datetime(peerdata["period"], errors="coerce")

    institutions = None
    if institutions_path is not None:
        inst_path = as_path(institutions_path)
        if inst_path.exists():
            institutions = pd.read_csv(inst_path, encoding="utf-8-sig")

    selected_lei = resolve_bank_lei(institutions, bank_name)
    if selected_lei and "bank_lei" in peerdata.columns:
        bank_rows = peerdata[peerdata["bank_lei"] == selected_lei].copy()
    else:
        selected = resolve_bank_name(peerdata, institutions, bank_name)
        bank_rows = peerdata[peerdata["bank_name"] == selected].copy()

    bank_rows = bank_rows.sort_values(
        by=["template", "item", "column", "period"],
        ascending=[True, True, True, False],
    )
    base_year = bank_rows.drop_duplicates(
        subset=["template", "item", "column"],
        keep="first",
    )
    return base_year


def export_base_year(
    peerdata_path: str | Path,
    bank_name: str,
    output_path: str | Path,
    institutions_path: str | Path | None = None,
) -> pd.DataFrame:
    base_year = build_base_year(peerdata_path, bank_name, institutions_path)
    out = as_path(output_path)
    base_year.to_csv(out, index=False, encoding="utf-8-sig")
    return base_year
