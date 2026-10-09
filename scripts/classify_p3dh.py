"""Geography and size classes for every reporting entity.

Run after scripts/clean_p3dh.py. The script writes:
  dim_country         one row for each country: ISO code, region, peer group, euro entry date.
  dim_size_class      the lower limits of the size classes (total assets in EUR).
  entity_assets       total assets (EUR) of one entity at one period end, with source and test result.
  entity_size_current the period that gives the current size of each entity.
  v_entity_assets_class  entity_assets with geography and size class for each period.
  v_entity_class         one row for each entity: geography, current total assets, size class.

The two dim tables are lookup tables. The script fills them only when they are empty. Edit
them with SQL to change a region or a limit. The views read them at query time, so no rerun
is needed after an edit. Use --reset-dims to restore the default values.

Total assets come from the published financial statements, in this order:
  K_70.00 r0010 (LR1), K_66.02 "Total assets" (CC2), K_64.01 "Total assets" (LI1); column a.
All three give the same value when more than one exists, and they share the unit errors of the
Hub. The scale is therefore tested against the clean KM1 leverage exposure of the same period.
Total assets divided by leverage exposure is normally between 0.3 and 3.0. A ratio from 0.05 to 30
is accepted and flagged (public lenders and clearing banks). A factor of 1,000 or 1,000,000 that
brings a ratio outside this range into 0.3 to 3.0 is applied once. Without a clean leverage
exposure the value is accepted only if the raw KM1 of that filing is absent and the size is
plausible. If no total assets exist, the leverage exposure gives the size (size_basis).

Run: PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/classify_p3dh.py
"""

from __future__ import annotations

import argparse
import math
import sqlite3
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "processed" / "p3dh.sqlite"

# country, ISO code, region, peer group, euro entry date, EU member (1) or EEA only (0)
COUNTRIES = [
    ("Greece", "GR", "Southern Europe", "greek", "2001-01-01", 1),
    ("Italy", "IT", "Southern Europe", "periphery", "1999-01-01", 1),
    ("Spain", "ES", "Southern Europe", "periphery", "1999-01-01", 1),
    ("Portugal", "PT", "Southern Europe", "periphery", "1999-01-01", 1),
    ("Cyprus", "CY", "Southern Europe", "periphery", "2008-01-01", 1),
    ("Malta", "MT", "Southern Europe", "other", "2008-01-01", 1),
    ("Ireland", "IE", "Western Europe", "periphery", "1999-01-01", 1),
    ("Germany", "DE", "Western Europe", "core", "1999-01-01", 1),
    ("France", "FR", "Western Europe", "core", "1999-01-01", 1),
    ("Netherlands", "NL", "Western Europe", "core", "1999-01-01", 1),
    ("Belgium", "BE", "Western Europe", "core", "1999-01-01", 1),
    ("Luxembourg", "LU", "Western Europe", "core", "1999-01-01", 1),
    ("Austria", "AT", "Western Europe", "core", "1999-01-01", 1),
    ("Liechtenstein", "LI", "Western Europe", "other", None, 0),
    ("Finland", "FI", "Nordics", "core", "1999-01-01", 1),
    ("Denmark", "DK", "Nordics", "other", None, 1),
    ("Sweden", "SE", "Nordics", "other", None, 1),
    ("Norway", "NO", "Nordics", "other", None, 0),
    ("Iceland", "IS", "Nordics", "other", None, 0),
    ("Estonia", "EE", "Baltics", "other", "2011-01-01", 1),
    ("Latvia", "LV", "Baltics", "other", "2014-01-01", 1),
    ("Lithuania", "LT", "Baltics", "other", "2015-01-01", 1),
    ("Poland", "PL", "Central and Eastern Europe", "other", None, 1),
    ("Czech", "CZ", "Central and Eastern Europe", "other", None, 1),
    ("Slovakia", "SK", "Central and Eastern Europe", "other", "2009-01-01", 1),
    ("Hungary", "HU", "Central and Eastern Europe", "other", None, 1),
    ("Slovenia", "SI", "Central and Eastern Europe", "other", "2007-01-01", 1),
    ("Croatia", "HR", "Central and Eastern Europe", "other", "2023-01-01", 1),
    ("Romania", "RO", "Central and Eastern Europe", "other", None, 1),
    ("Bulgaria", "BG", "Central and Eastern Europe", "other", "2026-01-01", 1),
]
# size class, lower limit in EUR, label of the range, sort order
SIZE_CLASSES = [
    ("Small", 0.0, "below 10bn", 1),
    ("Medium", 1e10, "10bn to 100bn", 2),
    ("Large", 1e11, "100bn to 250bn", 3),
    ("Very large", 2.5e11, "250bn and above", 4),
]

ASSET_SOURCES = ("K_70.00", "K_66.02", "K_64.01")
RATIO_LOW, RATIO_HIGH = 0.3, 3.0
# A unit error gives a ratio near 1,000 or 0.001. Public lenders and clearing banks reach 0.05 to 30.
WIDE_LOW, WIDE_HIGH = 0.05, 30.0
SIZE_MIN, SIZE_MAX = 1e7, 5e12
FACTORS = (1e3, 1e6, 1e-3, 1e-6)

SCHEMA = """
CREATE TABLE IF NOT EXISTS dim_country (
    country TEXT PRIMARY KEY, iso2 TEXT NOT NULL, region TEXT NOT NULL, peer_group TEXT NOT NULL,
    euro_since TEXT, eu_member INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS dim_size_class (
    size_class TEXT PRIMARY KEY, min_assets_eur REAL NOT NULL, range_label TEXT, sort_order INTEGER NOT NULL
);
"""

VIEWS = """
DROP VIEW IF EXISTS v_entity_assets_class;
CREATE VIEW v_entity_assets_class AS
WITH ent AS (
    SELECT entity_key, entity_name, country FROM (
        SELECT entity_key, entity_name, country,
               ROW_NUMBER() OVER (PARTITION BY entity_key ORDER BY last_seen DESC) AS rn FROM entity
    ) WHERE rn = 1)
SELECT a.entity_key, ent.entity_name, ent.country, c.iso2, c.region, c.peer_group, c.eu_member,
       CASE WHEN c.euro_since IS NOT NULL AND c.euro_since <= a.period_end THEN 1 ELSE 0 END AS euro_area,
       a.period_end, a.total_assets_eur, a.leverage_exposure_eur, a.size_basis, a.size_basis_eur,
       a.assets_source, a.assets_method,
       COALESCE((SELECT s.size_class FROM dim_size_class s WHERE s.min_assets_eur <= a.size_basis_eur
                 ORDER BY s.min_assets_eur DESC LIMIT 1), 'Unclassified') AS size_class
FROM entity_assets a
JOIN ent ON ent.entity_key = a.entity_key
LEFT JOIN dim_country c ON c.country = ent.country;

DROP VIEW IF EXISTS v_entity_class;
CREATE VIEW v_entity_class AS
WITH ent AS (
    SELECT entity_key, entity_name, country FROM (
        SELECT entity_key, entity_name, country,
               ROW_NUMBER() OVER (PARTITION BY entity_key ORDER BY last_seen DESC) AS rn FROM entity
    ) WHERE rn = 1)
SELECT ent.entity_key, ent.entity_name, ent.country, c.iso2, c.region, c.peer_group, c.eu_member,
       CASE WHEN c.euro_since IS NOT NULL
             AND c.euro_since <= (SELECT MAX(reference_date) FROM filing) THEN 1 ELSE 0 END AS euro_area,
       s.as_of AS assets_as_of, s.total_assets_eur, s.leverage_exposure_eur, s.size_basis, s.size_basis_eur,
       s.assets_source, s.assets_method,
       COALESCE((SELECT z.size_class FROM dim_size_class z WHERE z.min_assets_eur <= s.size_basis_eur
                 ORDER BY z.min_assets_eur DESC LIMIT 1), 'Unclassified') AS size_class
FROM ent
LEFT JOIN dim_country c ON c.country = ent.country
LEFT JOIN entity_size_current s ON s.entity_key = ent.entity_key;
"""


def seed_dims(conn: sqlite3.Connection, reset: bool) -> None:
    conn.executescript(SCHEMA)
    if reset:
        conn.execute("DELETE FROM dim_country")
        conn.execute("DELETE FROM dim_size_class")
    if not conn.execute("SELECT COUNT(*) FROM dim_country").fetchone()[0]:
        conn.executemany("INSERT INTO dim_country VALUES (?,?,?,?,?,?)", COUNTRIES)
    if not conn.execute("SELECT COUNT(*) FROM dim_size_class").fetchone()[0]:
        conn.executemany("INSERT INTO dim_size_class VALUES (?,?,?,?)", SIZE_CLASSES)
    conn.commit()


def load_inputs(conn: sqlite3.Connection):
    cand = pd.read_sql_query(
        """SELECT e.entity_key, f.reference_date, f.template_code, f.value
           FROM fact f JOIN entity e ON e.entity_id = f.entity_id
           WHERE f.value IS NOT NULL AND f.row_code = '0010' AND f.column_code = '0010'
             AND (f.template_code = 'K_70.00'
                  OR (f.template_code IN ('K_66.02', 'K_64.01') AND f.row_label = 'Total assets'))""", conn)
    lev = pd.read_sql_query(
        """SELECT entity_key, period_end, value AS lev FROM clean_period_fact
           WHERE template_code = 'K_61.00' AND row_code = '0210' AND measure_col = 10 AND value > 0""", conn)
    raw_km1 = pd.read_sql_query(
        """SELECT DISTINCT e.entity_key, f.reference_date AS period_end
           FROM fact f JOIN entity e ON e.entity_id = f.entity_id
           WHERE f.template_code = 'K_61.00' AND f.row_code = '0210' AND f.column_code = '0010'
             AND f.value IS NOT NULL""", conn)
    return cand, lev, raw_km1


def test_assets(value: float, anchor: float | None, raw_km1_present: bool):
    """Return (value, method) for one total-assets candidate."""
    if anchor is not None:
        r = value / anchor
        if RATIO_LOW <= r <= RATIO_HIGH:
            return value, "verified_vs_leverage_exposure"
        if WIDE_LOW <= r <= WIDE_HIGH:
            return value, "accepted: ratio to leverage exposure outside 0.3 to 3.0 (exempt or off-balance items)"
        fits = [k for k in FACTORS if RATIO_LOW <= r * k <= RATIO_HIGH]
        if len(fits) == 1:
            return value * fits[0], "rescaled_vs_leverage_exposure"
        return None, "rejected: inconsistent with leverage exposure"
    if raw_km1_present:
        return None, "rejected: scale unresolved (KM1 of the filing failed the scale test)"
    if SIZE_MIN <= value <= SIZE_MAX:
        return value, "unverified: no KM1 for this period"
    return None, "rejected: implausible size"


def build_assets(cand: pd.DataFrame, lev: pd.DataFrame, raw_km1: pd.DataFrame) -> pd.DataFrame:
    lev_map = {(r.entity_key, r.period_end): r.lev for r in lev.itertuples()}
    raw_set = set(zip(raw_km1.entity_key, raw_km1.period_end))
    rows: dict[tuple, dict] = {}
    for (key, ref), grp in cand.groupby(["entity_key", "reference_date"]):
        grp = grp.assign(rank=grp["template_code"].map({t: i for i, t in enumerate(ASSET_SOURCES)}))
        chosen = None
        for r in grp.sort_values("rank").itertuples():
            if not (r.value > 0 and math.isfinite(r.value)):
                continue
            val, method = test_assets(r.value, lev_map.get((key, ref)), (key, ref) in raw_set)
            if chosen is None or (chosen["total_assets_eur"] is None and val is not None):
                chosen = {"total_assets_eur": val, "assets_source": r.template_code, "assets_method": method}
        if chosen is None:
            chosen = {"total_assets_eur": None, "assets_source": None, "assets_method": "rejected: no positive value"}
        rows[(key, ref)] = chosen
    for (key, per), v in lev_map.items():
        rows.setdefault((key, per), {"total_assets_eur": None, "assets_source": None, "assets_method": None})
    df = pd.DataFrame([{"entity_key": k, "period_end": p, **v, "leverage_exposure_eur": lev_map.get((k, p))}
                       for (k, p), v in rows.items()])
    df["size_basis"] = None
    df.loc[df["leverage_exposure_eur"].notna(), "size_basis"] = "leverage_exposure"
    df.loc[df["total_assets_eur"].notna(), "size_basis"] = "total_assets"
    df["size_basis_eur"] = df["total_assets_eur"].fillna(df["leverage_exposure_eur"])
    return df.sort_values(["entity_key", "period_end"]).reset_index(drop=True)


def build_current(assets: pd.DataFrame) -> pd.DataFrame:
    """Latest period with a size. Total assets win when they are at most 12 months older."""
    out = []
    usable = assets[assets["size_basis_eur"].notna()]
    for key, grp in usable.groupby("entity_key"):
        latest = grp.iloc[-1]
        ta = grp[grp["total_assets_eur"].notna()]
        pick = latest
        if len(ta):
            last_ta = ta.iloc[-1]
            gap = (pd.Timestamp(latest["period_end"]) - pd.Timestamp(last_ta["period_end"])).days
            if gap <= 366:
                pick = last_ta
        out.append({"entity_key": key, "as_of": pick["period_end"],
                    "total_assets_eur": pick["total_assets_eur"], "leverage_exposure_eur": pick["leverage_exposure_eur"],
                    "size_basis": pick["size_basis"], "size_basis_eur": pick["size_basis_eur"],
                    "assets_source": pick["assets_source"], "assets_method": pick["assets_method"]})
    return pd.DataFrame(out, columns=["entity_key", "as_of", "total_assets_eur", "leverage_exposure_eur", "size_basis",
                                      "size_basis_eur", "assets_source", "assets_method"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--reset-dims", action="store_true", help="Restore the default lookup tables")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'clean_period_fact'").fetchone():
        print("clean_period_fact is missing. Run scripts/clean_p3dh.py first.", file=sys.stderr)
        return 1
    seed_dims(conn, args.reset_dims)
    cand, lev, raw_km1 = load_inputs(conn)
    assets = build_assets(cand, lev, raw_km1)
    current = build_current(assets)
    if assets.duplicated(["entity_key", "period_end"]).any() or current["entity_key"].duplicated().any():
        raise RuntimeError("duplicate keys in the classification tables")
    with conn:
        assets.to_sql("entity_assets", conn, if_exists="replace", index=False)
        current.to_sql("entity_size_current", conn, if_exists="replace", index=False)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_entity_assets ON entity_assets(entity_key, period_end)")
        conn.executescript(VIEWS)

    classes = pd.read_sql_query("SELECT * FROM v_entity_class", conn)
    print(f"entities: {len(classes)} | with a size: {int(classes['size_basis_eur'].notna().sum())}")
    print("\nMethod of total assets (entity-periods):")
    print(assets["assets_method"].fillna("none (leverage exposure only)").value_counts().to_string())
    print("\nSize class (current):")
    order = pd.read_sql_query("SELECT size_class FROM dim_size_class ORDER BY sort_order", conn)["size_class"].tolist()
    print(classes["size_class"].value_counts().reindex(order + ["Unclassified"]).fillna(0).astype(int).to_string())
    print("\nSize basis (current):", classes["size_basis"].fillna("none").value_counts().to_dict())
    print("Peer group:", classes["peer_group"].fillna("UNMAPPED").value_counts().to_dict())
    unmapped = classes.loc[classes["region"].isna(), "country"].unique().tolist()
    if unmapped:
        print(f"UNMAPPED COUNTRIES (add them to dim_country): {unmapped}", file=sys.stderr)
    conn.close()
    return 1 if unmapped else 0


if __name__ == "__main__":
    sys.exit(main())
