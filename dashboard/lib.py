"""Shared data access for the P3DH dashboard. The database is opened read-only."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
DB = Path(os.environ.get("P3DH_DB", ROOT / "data" / "processed" / "p3dh.sqlite"))
STATUS_DOC = ROOT / "docs" / "p3dh_template_status.md"

GREEK = {
    "5UMCZOEYKCVFAW8ZLO05": "NBG", "213800KGF4EFNUQKAT69": "Eurobank",
    "213800DBQIB6VBNU5C64": "Alpha", "213800OYHR1MPQ5VJL60": "Piraeus",
}
KM1_ROWS = {
    "cet1_capital": "0010", "t1_capital": "0020", "total_capital": "0030", "trea": "0040",
    "cet1_ratio": "0050", "t1_ratio": "0060", "total_capital_ratio": "0070",
    "leverage_exposure": "0210", "leverage_ratio": "0220", "lcr": "0320", "nsfr": "0350",
}
RATIO_LABELS = {
    "cet1_ratio": "CET1 ratio", "t1_ratio": "Tier 1 ratio", "total_capital_ratio": "Total capital ratio",
    "leverage_ratio": "Leverage ratio", "lcr": "LCR", "nsfr": "NSFR",
}
SIZE_ORDER = ["Small", "Medium", "Large", "Very large", "Unclassified"]


def db_stamp() -> float:
    return DB.stat().st_mtime if DB.exists() else 0.0


@st.cache_resource
def _conn() -> sqlite3.Connection:
    return sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True, check_same_thread=False)


@st.cache_data(show_spinner=False)
def _run(sql: str, params: tuple, stamp: float) -> pd.DataFrame:
    return pd.read_sql_query(sql, _conn(), params=params)


def q(sql: str, params: tuple = ()) -> pd.DataFrame:
    """Run a query. The database file time is part of the cache key, so a refresh shows at once."""
    return _run(sql, params, db_stamp())


def table_exists(name: str) -> bool:
    return not q("SELECT 1 FROM sqlite_master WHERE name = ?", (name,)).empty


def classes() -> pd.DataFrame:
    df = q("SELECT * FROM v_entity_class")
    df["size_class"] = pd.Categorical(df["size_class"], SIZE_ORDER, ordered=True)
    return df


def km1_wide() -> pd.DataFrame:
    """Clean KM1 metrics, one row for each entity and quarter."""
    codes = tuple(KM1_ROWS.values())
    df = q(f"""SELECT entity_key, period_end, row_code, value FROM clean_period_fact
               WHERE template_code = 'K_61.00' AND measure_col = 10 AND row_code IN ({','.join('?' * len(codes))})""", codes)
    inv = {v: k for k, v in KM1_ROWS.items()}
    df["metric"] = df["row_code"].map(inv)
    wide = df.pivot_table(index=["entity_key", "period_end"], columns="metric", values="value", aggfunc="first").reset_index()
    return wide


def cohort_filters(df: pd.DataFrame, key: str = "") -> pd.DataFrame:
    """Sidebar filters for size class, peer group, region, and country. Returns the filtered frame."""
    st.sidebar.header("Cohort")
    size = st.sidebar.multiselect("Size class", [s for s in SIZE_ORDER if s in set(df["size_class"].astype(str))], key=f"{key}size")
    peer = st.sidebar.multiselect("Peer group", sorted(df["peer_group"].dropna().unique()), key=f"{key}peer")
    region = st.sidebar.multiselect("Region", sorted(df["region"].dropna().unique()), key=f"{key}region")
    country = st.sidebar.multiselect("Country", sorted(df["country"].dropna().unique()), key=f"{key}country")
    out = df
    if size:
        out = out[out["size_class"].astype(str).isin(size)]
    if peer:
        out = out[out["peer_group"].isin(peer)]
    if region:
        out = out[out["region"].isin(region)]
    if country:
        out = out[out["country"].isin(country)]
    return out
