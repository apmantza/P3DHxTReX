"""Tables and views for the Bloomberg data. They live in the P3DH database and use the prefix bbg_."""

from __future__ import annotations

import sqlite3

UNIVERSE_MIN_EUR = 150_000_000  # bond universe: outstanding amount above this value, in EUR or the equivalent in another currency

SCHEMA = """
CREATE TABLE IF NOT EXISTS bbg_pull_log (
    pull_id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT, kind TEXT, detail TEXT, n_rows INTEGER, status TEXT);
CREATE TABLE IF NOT EXISTS bbg_security_use (month TEXT, security TEXT, PRIMARY KEY (month, security)) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS bbg_rate_series (
    series TEXT PRIMARY KEY, ticker TEXT, name TEXT, group_name TEXT, unit TEXT, tenor_days INTEGER, method TEXT,
    first_date TEXT, last_date TEXT, n_obs INTEGER);
CREATE TABLE IF NOT EXISTS bbg_rate_daily (series TEXT, date TEXT, value REAL, PRIMARY KEY (series, date)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS bbg_rate_average (
    series TEXT, period_type TEXT, period_start TEXT, period_end TEXT, avg REAL, first REAL, last REAL, n_days INTEGER, complete INTEGER,
    PRIMARY KEY (series, period_type, period_end)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS bbg_expected_dfr (
    as_of TEXT, period_type TEXT, period_start TEXT, period_end TEXT, expected_avg REAL, spread REAL,
    PRIMARY KEY (as_of, period_type, period_end)) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS bbg_entity (
    lei TEXT PRIMARY KEY, pulled_at TEXT, found INTEGER, name TEXT, long_name TEXT, bb_company INTEGER, country_iso TEXT, sector TEXT, private_flag TEXT,
    equity_ticker TEXT, parent_name TEXT, parent_ticker TEXT, parent_lei TEXT, direct_parent_lei TEXT, n_bond_issues INTEGER, bond_amt_outstanding REAL,
    statutory_tax_rate REAL, effective_tax_rate REAL, rating_sp TEXT, rating_moodys TEXT, rating_fitch TEXT, latest_period_end TEXT,
    total_assets REAL, net_income REAL, operating_expenses REAL, common_equity REAL, customer_deposits REAL, total_loans REAL, rwa REAL, revenue REAL,
    roe REAL, roa REAL, tier1_ratio REAL, interest_income REAL, cash REAL,
    market_basis TEXT, market_ticker TEXT, net_income_ltm REAL);  -- net_income, revenue, operating_expenses, common_equity: last fiscal year, EUR million. net_income_ltm: last 12 months.

CREATE TABLE IF NOT EXISTS bbg_holder (
    ticker TEXT, pull_date TEXT, rank INTEGER, holder TEXT, holder_type TEXT, country TEXT, pct_out REAL, shares REAL, change REAL, filing_date TEXT, source TEXT,
    PRIMARY KEY (ticker, pull_date, rank)) WITHOUT ROWID;  -- the 20 largest holders of a listed ticker. holder_type: Government, Sovereign Wealth Fund, Bank, Investment Advisor, ...
CREATE TABLE IF NOT EXISTS bbg_ownership (
    ticker TEXT, pull_date TEXT, kind TEXT, owner_type TEXT, pct REAL, PRIMARY KEY (ticker, pull_date, kind, owner_type)) WITHOUT ROWID;  -- kind: named (holders with a filing), all (all holders, by type), or scalar (EQY_INST_PCT_SH_OUT, EQY_FREE_FLOAT_PCT)

CREATE TABLE IF NOT EXISTS bbg_ticker_map (
    entity_key TEXT, kind TEXT, ticker TEXT, priced INTEGER, source TEXT, note TEXT, PRIMARY KEY (entity_key, kind, ticker)) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS bbg_debt_maturity (lei TEXT, year INTEGER, bonds_m REAL, bonds_loans_m REAL, pulled_at TEXT, PRIMARY KEY (lei, year)) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS bbg_equity_snapshot (ticker TEXT, field TEXT, pull_date TEXT, value, PRIMARY KEY (ticker, field, pull_date)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS bbg_equity_daily (
    ticker TEXT, date TEXT, px_last REAL, mkt_cap_eur REAL, px_to_book REAL, shares REAL, PRIMARY KEY (ticker, date)) WITHOUT ROWID;  -- px_last in the currency of the stock, mkt_cap_eur in EUR, shares in millions
CREATE TABLE IF NOT EXISTS bbg_fundamental (
    ticker TEXT, period_end TEXT, period_type TEXT, field TEXT, value REAL, PRIMARY KEY (ticker, period_end, period_type, field)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS bbg_consensus (
    ticker TEXT, pull_date TEXT, fperiod TEXT, period_end TEXT, field TEXT, value REAL, PRIMARY KEY (ticker, pull_date, fperiod, field)) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS bbg_bond_listing (lei TEXT, issuer_ticker TEXT, security TEXT, description TEXT, PRIMARY KEY (lei, security)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS bbg_bond (
    security TEXT PRIMARY KEY, pulled_at TEXT, lei TEXT, isin TEXT, issuer_lei TEXT, designation TEXT, name TEXT, coupon REAL, coupon_type TEXT, maturity TEXT, issue_date TEXT,
    amt_issued REAL, amt_outstanding REAL, currency TEXT, collateral_type TEXT, payment_rank TEXT, security_type TEXT, callable TEXT, next_call TEXT,
    first_call TEXT, maturity_type TEXT, basel_iii TEXT, contingent TEXT, perpetual TEXT, rating_sp TEXT, rating_moodys TEXT, rating_fitch TEXT,
    px_last REAL, yield_mid REAL, z_spread REAL, oas REAL, duration REAL, bb_global TEXT);

CREATE TABLE IF NOT EXISTS bbg_bond_market (
    security TEXT, pull_date TEXT, quote_date TEXT, px_bid REAL, px_ask REAL, px_mid REAL, px_last REAL, ytm_bid REAL, ytm_mid REAL, ytm_ask REAL, ytc_mid REAL, ytw REAL,
    worst_date TEXT, i_spread REAL, z_spread REAL, g_spread REAL, bench_spread REAL, bench_bond TEXT, bench_yield REAL, asw_spread REAL, oas REAL, duration REAL, convexity REAL,
    amt_outstanding REAL, PRIMARY KEY (security, pull_date)) WITHOUT ROWID;  -- yields in percent, spreads in basis points, prices in percent of par

CREATE TABLE IF NOT EXISTS bbg_bond_history (
    security TEXT, date TEXT, px_last REAL, px_bid REAL, px_ask REAL, ytm_mid REAL, ytc_mid REAL, i_spread REAL, z_spread REAL, asw_spread REAL,
    PRIMARY KEY (security, date)) WITHOUT ROWID;  -- daily history of the quoted outstanding bonds. Bloomberg keeps the Z-spread and the asset-swap spread for about 60 days only

DROP VIEW IF EXISTS v_bond_outstanding;
CREATE VIEW v_bond_outstanding AS
    SELECT (SELECT MAX(entity_name) FROM entity WHERE lei = b.lei) AS bank, b.lei, b.security, b.isin, b.designation, b.payment_rank, b.basel_iii, b.coupon, b.coupon_type, b.maturity,
           b.next_call, b.currency, b.amt_issued, b.amt_outstanding,
           CASE WHEN b.currency = 'EUR' THEN b.amt_outstanding
                WHEN b.currency = 'ATS' THEN b.amt_outstanding / 13.7603  -- fixed conversion rate of the Austrian schilling
                ELSE b.amt_outstanding / (SELECT value FROM bbg_rate_daily WHERE series = 'FX_EUR' || b.currency ORDER BY date DESC LIMIT 1) END AS amt_outstanding_eur, m.pull_date, m.quote_date, m.px_bid, m.px_ask, m.px_mid, m.ytm_mid, m.ytc_mid, m.ytw, m.i_spread, m.z_spread,
           m.g_spread, m.bench_spread, m.asw_spread, m.oas, m.duration
    FROM bbg_bond b LEFT JOIN bbg_bond_market m ON m.security = b.security AND m.pull_date = (SELECT MAX(pull_date) FROM bbg_bond_market x WHERE x.security = b.security)
    WHERE b.amt_outstanding > 0 AND (b.perpetual = 'Y' OR b.maturity IS NULL OR b.maturity >= date('now'));

DROP VIEW IF EXISTS v_bond_universe;
CREATE VIEW v_bond_universe AS SELECT * FROM v_bond_outstanding WHERE amt_outstanding_eur > @MIN_EUR@;

DROP VIEW IF EXISTS v_dfr_average;
CREATE VIEW v_dfr_average AS
    SELECT period_type, period_start, period_end, avg AS dfr_avg, first AS dfr_first, last AS dfr_last, n_days, complete
    FROM bbg_rate_average WHERE series = 'ECB_DFR';
DROP VIEW IF EXISTS v_dfr_p3dh;
CREATE VIEW v_dfr_p3dh AS
    SELECT f.reference_date,
           (SELECT value FROM bbg_rate_daily d WHERE d.series = 'ECB_DFR' AND d.date <= f.reference_date ORDER BY d.date DESC LIMIT 1) AS dfr_spot,
           (SELECT avg FROM bbg_rate_average a WHERE a.series = 'ECB_DFR' AND a.period_type = 'Q' AND a.period_end = f.reference_date) AS dfr_avg_quarter,
           (SELECT avg FROM bbg_rate_average a WHERE a.series = 'ECB_DFR' AND a.period_type = 'H' AND a.period_end = f.reference_date) AS dfr_avg_half,
           (SELECT avg FROM bbg_rate_average a WHERE a.series = 'ECB_DFR' AND a.period_type = 'YTD' AND a.period_end = f.reference_date) AS dfr_avg_ytd,
           (SELECT avg FROM bbg_rate_average a WHERE a.series = 'ECB_DFR' AND a.period_type = 'LTM' AND a.period_end = f.reference_date) AS dfr_avg_ltm
    FROM (SELECT DISTINCT reference_date FROM filing) f;
DROP VIEW IF EXISTS v_bank_ownership;
CREATE VIEW v_bank_ownership AS
    WITH h AS (SELECT * FROM bbg_holder WHERE pull_date = (SELECT MAX(pull_date) FROM bbg_holder)),
         o AS (SELECT * FROM bbg_ownership WHERE pull_date = (SELECT MAX(pull_date) FROM bbg_ownership))
    SELECT e.lei AS entity_key, (SELECT MAX(entity_name) FROM entity WHERE lei = e.lei) AS bank, e.country_iso AS country, e.market_basis, e.market_ticker AS ticker,
           CASE WHEN e.market_basis = 'self' THEN 0 ELSE 1 END AS via_parent, e.parent_name, e.parent_relationship,
           (SELECT SUM(pct_out) FROM h WHERE h.ticker = e.market_ticker AND h.holder_type = 'Government') AS state_pct_named,
           (SELECT pct FROM o WHERE o.ticker = e.market_ticker AND o.kind = 'all' AND o.owner_type = 'Government') AS state_pct_all,
           (SELECT SUM(pct_out) FROM h WHERE h.ticker = e.market_ticker AND h.holder_type = 'Sovereign Wealth Fund') AS swf_pct_named,
           (SELECT holder FROM h WHERE h.ticker = e.market_ticker AND h.rank = 1) AS largest_holder,
           (SELECT holder_type FROM h WHERE h.ticker = e.market_ticker AND h.rank = 1) AS largest_type,
           (SELECT pct_out FROM h WHERE h.ticker = e.market_ticker AND h.rank = 1) AS largest_pct,
           (SELECT pct FROM o WHERE o.ticker = e.market_ticker AND o.kind = 'scalar' AND o.owner_type = 'EQY_FREE_FLOAT_PCT') AS free_float_pct,
           (SELECT pct FROM o WHERE o.ticker = e.market_ticker AND o.kind = 'scalar' AND o.owner_type = 'EQY_INST_PCT_SH_OUT') AS institutional_pct,
           CASE WHEN e.parent_relationship = 'Govt Owned Entity' OR e.parent_name LIKE 'Kingdom of%' OR e.parent_name LIKE '%Republic of%' OR e.parent_name LIKE 'State of%'
                     OR e.parent_name LIKE 'Government of%' OR e.parent_name LIKE 'Freistaat%' OR e.parent_name LIKE 'Free State%' OR e.parent_name LIKE '%Republic' OR e.parent_name LIKE '%Republic/%'
                     OR e.parent_name LIKE 'Principality of%' OR e.parent_name LIKE 'State of%' THEN 'owned by a government'
                WHEN (SELECT SUM(pct_out) FROM h WHERE h.ticker = e.market_ticker AND h.holder_type = 'Government') >= 50 THEN 'state majority'
                WHEN (SELECT SUM(pct_out) FROM h WHERE h.ticker = e.market_ticker AND h.holder_type = 'Government') > 0 THEN 'state participation'
                ELSE 'none reported' END AS state_status
    FROM bbg_entity e WHERE e.found = 1;
DROP VIEW IF EXISTS v_bank_tickers;
CREATE VIEW v_bank_tickers AS
    SELECT e.entity_key, e.entity_name, e.country, t.kind, t.ticker, t.priced, t.note
    FROM entity e JOIN bbg_ticker_map t ON t.entity_key = e.lei;
DROP VIEW IF EXISTS v_bank_market;
CREATE VIEW v_bank_market AS
    SELECT e.entity_key, e.entity_name, e.country, b.lei, b.found, b.private_flag, b.market_basis, b.market_ticker, b.equity_ticker, b.parent_ticker, b.parent_name,
           b.n_bond_issues, b.bond_amt_outstanding, b.statutory_tax_rate, b.effective_tax_rate, b.rating_sp, b.rating_moodys,
           b.bbg_lei, b.match_method, b.total_assets, b.net_income, b.net_income_ltm, b.operating_expenses, b.common_equity, b.rwa, b.revenue, b.roe, b.latest_period_end
    FROM entity e LEFT JOIN bbg_entity b ON b.lei = e.lei;
"""


ADDED_COLUMNS = {"bbg_entity": [("net_income_ltm", "REAL"), ("bbg_lei", "TEXT"), ("match_method", "TEXT"), ("parent_relationship", "TEXT"), ("business_structure", "TEXT"), ("debt_ticker", "TEXT"), ("cds_ticker", "TEXT")], "bbg_bond_listing": [("status", "TEXT")]}  # status: NULL = not requested, ambiguous, unresolved


def create(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA.replace("@MIN_EUR@", str(UNIVERSE_MIN_EUR)))
    for table, cols in ADDED_COLUMNS.items():
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, kind in cols:
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")
    conn.commit()
