# BBIRR Implementation Plan — Phase 1 (PoC) — Part 2

*Continuation of Steps 6–8*

---

## Step 6 — Stress + Macro + Rating

**Goal:** Apply macro scenarios, validate assumptions, and score ratings.

**Files / modules:**
- `modules/stress/scenarios.py`, `transmission.py`, `runner.py`, `reverse.py`
- `modules/macro/elasticity.py`, `auditor.py`
- `modules/rating/simplified.py`, `percentiles.py`

**Key changes vs legacy plan:**
- Peer-percentile rating grid (not absolute)
- Funding curve stress overlays
- Reverse stress included in Phase 1

**Acceptance:**
- EBA adverse worsens CET1/NII vs baseline
- Reverse stress finds breach point
- Rating improves with stronger capital and asset quality

---

## Step 7 — Historical Counterfactual + Historical Bridges

**Goal:** Counterfactual hedging and backward-looking bridges.

**Files / modules:**
- `modules/historical/counterfactual.py`
- `modules/historical/bridge_history.py`

**Acceptance:**
- Historical counterfactual uses cached ECB rates
- Historical NII/CET1/RWA bridges render without missing data where available

---

## Step 8 — UI + Reporting

**Goal:** Streamlit UX, bridges, recovery editor, ICAAP/ILAAP draft pack.

**Files / modules:**
- `ui/app.py`
- `ui/views/dashboard.py`
- `ui/views/plan_builder.py`
- `ui/views/stress_testing.py`
- `ui/views/rating_scorecard.py`
- `ui/views/reports.py`
- `ui/views/historical_analysis.py`
- `modules/reporting/pdf.py`, `modules/reporting/excel.py`
- `modules/icaap/drafting.py`

**UI requirements:**
- Dashboard with RAF limits panel + bridge drill-downs
- Plan Builder with FTP curve editor + recovery options editor
- Stress view supports recovery overlay toggle
- Reports include ICAAP/ILAAP draft pack

**Acceptance:**
- All 6 views render without errors
- Bridges drill down from KPIs
- ICAAP/ILAAP pack generates

---

## Phase 2 (Deferred)

- Full Moody’s BCA / S&P BICRA scorecards
- Hedge optimization backtest
- React frontend
- Postgres + Celery + Docker Compose
- FINREP/COREP ingestion + auto-mapping
- Multi-currency + FX stress
