# BBIRR Implementation Plan — Phase 1 (PoC)

**Date:** 2026-02-21
**Last updated:** 2026-02-25
**Scope:** Phase 1 PoC — full engine + Streamlit UI + reporting

---

## Principles (Phase 1)

- **Small, composable modules:** avoid monoliths; each calculation block is its own file
- **Cache everything deterministic:** projections, peer percentiles, macro elasticities
- **Dual runtime:** sync runner in lite mode; async runner in full mode (same interface)
- **Engine-first:** pure Python core with clean inputs/outputs and explicit state

---

## Module Map (Non-monolithic)

```
modules/
  ingestion/         eba_transparency.py, p3dh.py, bank_factory.py
  calculation/       engine.py, state.py, pnl.py, balance_sheet.py, capital.py,
                     asset_quality.py, ecl.py, liquidity.py, funding.py,
                     bridges.py, raroc.py
  irrbb/             rates.py, repricing_gap.py, nmd.py, metrics.py, prepayment.py
  stress/            scenarios.py, transmission.py, runner.py, reverse.py
  macro/             elasticity.py, auditor.py
  rating/            simplified.py, percentiles.py
  historical/        ecb_client.py, eurostat_client.py, cache.py, api.py,
                     counterfactual.py
  market/            yfinance_client.py, ticker_map.py
  ftp/               curves.py
  vbm/               economic_profit.py
  icaap/             drafting.py
  reporting/         pdf.py, excel.py

services/
  runner.py          sync/async job runner
  cache.py           assumptions hash + projection cache
```

---

## Step 1 — Scaffold + DB + Runner + Cache

**Goal:** Project skeleton, config, DB schema, job runner, and caching.

**Files / modules:**
- `config.py`, `.env.example`
- `db/models.py`, `db/engine.py`, Alembic migrations
- `services/runner.py` (sync lite, async full)
- `services/cache.py` (assumptions hash + projection cache)

**DB entities:**
- Add all design entities incl. bridges, market metrics, FTP, recovery options, ICAAP/ILAAP draft

**Acceptance:**
- `alembic upgrade head` creates full schema
- Cache hit returns without recompute
- Runner executes sync in lite mode

**Progress:**
- [x] Ingestion module scaffolding (`modules/ingestion/*`)
- [x] Full DB schema — all 21 tables incl. `Bank`, `Plan`, `Scenario`, `ProjectedFinancials`, `StressRun`, `RatingScore`, `MarketData`, `HistoricalRateCurve`, `HistoricalMacroSeries`, `MacroElasticity`, `HedgeCounterfactualRun`, `HedgeOptimisationRun`, `OptimizationRun`, `ReportRun`, `IcaapIlaapDraft`, `AuditLog` (`db/models.py`)
- [x] `P3DHDataDictionary` reference table — 9,937 records, 100% match on keyed P3DH rows (`data/processed/p3dh_data_dictionary.csv`, `scripts/build_p3dh_data_dictionary.py`, `scripts/load_p3dh_dict_db.py`)
- [x] `banks` table populated — 138 institutions (120 TrEx with LEI, 18 P3DH-only); NBG confirmed as subject bank (id=65); `peer_data.bank_name` patched to human-readable names (`scripts/load_banks_db.py`)
- [ ] Alembic migrations (deferred — SQLite `create_all` used for PoC)
- [ ] Runner + cache abstraction (`services/runner.py`, `services/cache.py`)

---

## Step 2 — Historical + Market Data Layer

**Goal:** ECB/Eurostat ingestion + equity market data cache.

**Files / modules:**
- `modules/historical/ecb_client.py`, `eurostat_client.py`, `cache.py`, `api.py`
- `modules/market/yfinance_client.py`, `ticker_map.py`

**Acceptance:**
- Historical rates and macro series cached locally
- Market data stored in `MarketData` with refresh on demand

**Progress:**
- [x] P3DH normalization and incremental ingestion
- [x] TREX SDD enrichment + unmatched export
- [x] Canonical facts + divergence report
- [x] Canonical enrichment with TR_Metadata dimensions
- [x] EBA DPM 4.1 annotated table layouts downloaded and parsed — unit (EUR/PCT/TEXT), section, main DPM property per cell (`data/raw/EBA_DPM/`, `scripts/build_p3dh_data_dictionary.py`)
- [x] ECB historical rates (EURIBOR 1M/3M/6M/1Y, ESTER, MRO, DFR) — quarterly 2024-2025 (`modules/historical/ecb_rates.py`, `data/processed/ecb_rates_quarterly.csv`)
- [x] ECB rates loaded to DB — 50 records in `historical_rate_curves` (`scripts/load_ecb_rates_db.py`)
- [ ] ECB/Eurostat historical layer
- [ ] yfinance market data layer

---

## Step 3 — Ingestion (EBA Transparency + P3DH)

**Goal:** Parse public disclosures into normalized peer data.

**Files / modules:**
- `modules/ingestion/eba_transparency.py`
- `modules/ingestion/p3dh.py`
- `modules/ingestion/bank_factory.py`

**Acceptance:**
- `PeerData` populated with validated records
- `create_plan_from_peer_data()` builds base year

**P3DH Data Timing Notes:**
- P3DH publishes **full data only twice per year**: 31/12 and 30/06
- Q1 (31/03) and Q3 (30/09) releases contain only a subset of templates (lighter files)
- **Expected availability:**
  - 31/12 data: Complete by end of March each year
  - 30/06 data: Complete by end of November each year
- Current 31/12 data is incomplete — files will be re-downloaded in March and re-ingested
- Incremental ingestion handles re-downloads: same keys are skipped, new keys added

**Progress:**
- [x] TREX raw load + SDD mapping
- [x] P3DH normalization + upsert + delta reports
- [x] Map canonical facts into `PeerData` (261k rows in DB)
- [x] Export TR_Metadata dictionaries
- [x] Base-year factory (CSV) — NBG base year (`data/processed/base_year_nbg.csv`)
- [x] Base-year loader into DB (1,742 rows in `base_year_snapshots`)
- [x] `banks` table seeded from TrEx institutions list; interactive LEI-prompt for unresolved P3DH banks

---

## Step 4 — Calculation Engine (Core)

**Goal:** 5-year quarterly projection with ECL, funding curves, bridges, RAROC, VBM Lite.

**Files / modules:**
- `modules/calculation/engine.py` (orchestrator)
- `modules/calculation/state.py` (typed intermediate states)
- `modules/calculation/pnl.py`, `balance_sheet.py`, `capital.py`, `asset_quality.py`
- `modules/calculation/ecl.py` (IFRS 9)
- `modules/calculation/liquidity.py` (LCR/NSFR + survival horizon)
- `modules/calculation/funding.py` (funding curve stack + deposit pass-through)
- `modules/calculation/bridges.py` (CET1/NII/ROE/RWA)
- `modules/calculation/raroc.py`
- `modules/vbm/economic_profit.py`
- `modules/ftp/curves.py`

**Acceptance:**
- Projection runs in <2s (lite mode)
- ECL is scenario-weighted and stage-driven
- Bridges reconcile to totals
- RAROC/VBM computed without NaNs

---

## Step 5 — IRRBB / ALM + Funding Curves

**Goal:** Repricing gap, NMD model, IRRBB metrics, basis risk.

**Files / modules:**
- `modules/irrbb/rates.py`, `repricing_gap.py`, `nmd.py`, `metrics.py`, `prepayment.py`

**Acceptance:**
- ΔNII and ΔEVE computed across 6 EBA shocks
- Pre-hedge vs post-hedge outputs

---

## Appendix A — Cross-Module Interfaces (Phase 1)

**Conventions:**
- All modules accept/return typed dataclasses (or Pydantic models)
- No module reads the DB directly except ingestion and persistence layers

**Calculation core:**
- `run_projection(plan: Plan, scenario: Scenario | None) -> list[ProjectedFinancials]`
- `calculate_pnl(state: BalanceSheetState, funding: FundingState, rate_env: RateEnvironment) -> PnLState`
- `calculate_ecl(state: AssetQualityState, scenario: Scenario | None) -> EclState`
- `calculate_liquidity(state: BalanceSheetState, funding: FundingState) -> LiquidityState`
- `calculate_bridges(prev: ProjectedFinancials, curr: ProjectedFinancials) -> Bridges`

**Funding & FTP:**
- `build_funding_curves(plan: Plan, scenario: Scenario | None) -> FundingCurveStack`
- `apply_deposit_pass_through(plan: Plan, rate_env: RateEnvironment) -> DepositPricingState`
- `build_ftp_curves(plan: Plan) -> FtpCurveSet`

**IRRBB:**
- `build_repricing_gap(plan: Plan) -> RepricingGapTable`
- `calculate_irrbb_metrics(plan: Plan, rate_env: RateEnvironment) -> IrrbbMetrics`

**Stress:**
- `run_stress_test(plan: Plan, scenario: Scenario) -> StressRun`
- `run_reverse_stress(plan: Plan, target_metric: str, floor: float) -> StressRun`

**Rating:**
- `calculate_simplified_rating(financials: ProjectedFinancials, peer_data: list[PeerData]) -> SimplifiedRating`

**Macro:**
- `fit_all_elasticities(country: str) -> list[MacroElasticity]`
- `audit_assumptions(plan: Plan, scenario: Scenario | None) -> list[AssumptionAudit]`

---

*Continued in Part 2...*
