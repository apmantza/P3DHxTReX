"""Tables of the external statistics. One long table for all sources and countries: a new country or a new indicator needs no new column."""

from __future__ import annotations

import sqlite3

TABLES = """
CREATE TABLE IF NOT EXISTS ext_country (iso2 TEXT PRIMARY KEY, name TEXT, euro_area INTEGER, ecb_code TEXT, eurostat_code TEXT) WITHOUT ROWID;  -- U2 = the euro area
CREATE TABLE IF NOT EXISTS ext_series (
    source TEXT, series_key TEXT, indicator TEXT, ref_area TEXT, freq TEXT, unit TEXT, title TEXT, first_period TEXT, last_period TEXT, n_obs INTEGER, pulled_at TEXT,
    flow TEXT, concept TEXT, dims TEXT, unit_mult INTEGER,
    PRIMARY KEY (source, series_key)) WITHOUT ROWID;  -- concept: the key without frequency and country, so the same concept can be compared across countries; dims: the dimensions of the key (JSON); unit_mult: power of 10 of the unit (3 = thousand)
CREATE INDEX IF NOT EXISTS ix_ext_series_indicator ON ext_series (indicator, ref_area);
CREATE TABLE IF NOT EXISTS ext_obs (
    source TEXT, series_key TEXT, period TEXT, period_end TEXT, value REAL, status TEXT,
    PRIMARY KEY (source, series_key, period)) WITHOUT ROWID;  -- period as the source writes it (2026-08, 2026-Q2, 2025); period_end is the last day
CREATE TABLE IF NOT EXISTS ext_geo_group (group_name TEXT, iso2 TEXT, PRIMARY KEY (group_name, iso2)) WITHOUT ROWID;  -- geographic groups of countries for peer aggregates
CREATE TABLE IF NOT EXISTS ext_pull_log (pull_id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT, indicator TEXT, source TEXT, n_series INTEGER, n_obs INTEGER, status TEXT, detail TEXT);

"""

VIEWS = """
DROP VIEW IF EXISTS v_ext_obs;
CREATE VIEW v_ext_obs AS
    SELECT s.indicator, s.concept, s.flow, s.ref_area AS country, s.freq, o.period, o.period_end, o.value, o.status, s.unit, s.unit_mult, s.source, s.series_key
    FROM ext_obs o JOIN ext_series s ON s.source = o.source AND s.series_key = o.series_key WHERE o.value IS NOT NULL;

DROP VIEW IF EXISTS v_ext_latest;
CREATE VIEW v_ext_latest AS
    SELECT s.indicator, s.ref_area AS country, s.freq, o.period, o.period_end, o.value, s.unit, s.title
    FROM ext_series s JOIN ext_obs o ON o.source = s.source AND o.series_key = s.series_key
    WHERE o.value IS NOT NULL AND o.period_end = (SELECT MAX(x.period_end) FROM ext_obs x WHERE x.source = s.source AND x.series_key = s.series_key AND x.value IS NOT NULL);

-- annual growth of a monthly stock (loans, deposits): value / value of the same month one year before - 1
DROP VIEW IF EXISTS v_country_growth;
CREATE VIEW v_country_growth AS
    SELECT a.indicator, a.country, a.period, a.period_end, a.value, b.value AS value_year_before, a.value / b.value - 1 AS growth_yoy
    FROM v_ext_obs a JOIN v_ext_obs b ON b.indicator = a.indicator AND b.country = a.country AND b.freq = a.freq
         AND b.period = (CAST(substr(a.period, 1, 4) AS INTEGER) - 1) || substr(a.period, 5)
    WHERE a.freq = 'M' AND a.indicator LIKE 'bsi\\_%' ESCAPE '\\' AND b.value > 0;

-- rate of new business or of the outstanding book, less the 3-month Euribor of the month (loans: positive spread; deposits: the margin is Euribor less the rate)
DROP VIEW IF EXISTS v_country_spreads;
CREATE VIEW v_country_spreads AS
    SELECT r.indicator, r.country, r.period, r.period_end, r.value AS rate, e.value AS euribor_3m,
           r.value - e.value AS spread_to_euribor, e.value - r.value AS deposit_margin
    FROM v_ext_obs r JOIN v_ext_obs e ON e.indicator = 'euribor_3m' AND e.country = 'U2' AND e.period = r.period
    WHERE r.indicator LIKE 'mir\\_%' ESCAPE '\\' AND r.freq = 'M';
"""

ADDED_COLUMNS = {"ext_series": [("flow", "TEXT"), ("concept", "TEXT"), ("dims", "TEXT"), ("unit_mult", "INTEGER")]}


def create(conn: sqlite3.Connection) -> None:
    conn.executescript(TABLES)
    for table, cols in ADDED_COLUMNS.items():  # a database made before these columns existed
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, kind in cols:
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_ext_series_concept ON ext_series (concept, ref_area)")
    conn.executescript(VIEWS)
    conn.commit()
