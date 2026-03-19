# Bank Business Plan & Stress Testing Tool — Design Document
**Date:** 2026-02-21
**Status:** Approved
**Revision:** 3 (data source mapping + base year construction — 2026-02-22)

---

## 1. Purpose & Mandate

A self-hosted web application for EU commercial banks that serves as both a **strategic steering tool** and a **stress testing platform**. Delivered as a white-label product — banks use it with public peer data (EBA Transparency Exercise, P3DH). Primary users are bank executives and CFOs. The tool must be thorough on all credit-related metrics used by equity and credit analysts, deeply linked to Moody's and S&P rating methodologies, and capable of benchmarking against peers.

**Dual mandate:**
- **Steering:** Define business strategy → see full financial cascade → adjust and iterate
- **Stress:** Apply macro and rate shocks to any strategy → see capital, P&L, and rating impact

---

## 2. Scope

- **Geography:** EU commercial banks (all 20 Eurozone member states + architecture supports non-Eurozone EU in Phase 2)
- **Regulatory framework:** CRR/CRD IV/V, CRR3 (Basel IV final), EBA guidelines, ECB/SSM ICAAP
- **Capital approaches:** Both Standardized (SA) and Internal Ratings-Based (IRB)
- **Rating methodologies:** Moody's BCA framework + S&P BICRA framework
- **Deployment:** Self-hosted web app (pip install + uvicorn for laptop; Docker Compose for server)
- **Data model:** White-label using public EBA/P3DH data. Own-bank data upload via Excel templates in Phase 2.

**Country coverage (PoC):**

All 20 Eurozone member states: DE, FR, IT, ES, NL, BE, AT, PT, IE, GR, FI, LU, SK, SI, LT, LV, EE, CY, MT, HR. Country list is configuration-driven (not hard-coded) to allow extension to non-Eurozone EU (PL, CZ, SE, DK, HU, RO, BG) in Phase 2.

---

## 3. Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                  Browser (Streamlit PoC)                 │
│   Dashboard · Plan Builder · Stress · Scorecard · Reports│
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│              Python Application (FastAPI / Streamlit)    │
│                                                          │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐  │
│  │  Ingestion  │  │  Calculation │  │  IRRBB / ALM  │  │
│  │   Module    │  │    Engine    │  │    Module      │  │
│  └─────────────┘  └──────────────┘  └────────────────┘  │
│                                                          │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐  │
│  │   Stress    │  │   Rating     │  │   Reporting    │  │
│  │   Engine    │  │   Engine     │  │    Engine      │  │
│  └─────────────┘  └──────────────┘  └────────────────┘  │
│                                                          │
│  ┌─────────────┐  ┌──────────────────────────────────┐  │
│  │  Optimizer  │  │  Historical Hedge Counterfactual  │  │
│  │ (Eff. Front)│  │  & Optimisation Engine            │  │
│  └─────────────┘  └──────────────────────────────────┘  │
│                                                          │
│  ┌─────────────────────────────────────────────────────┐ │
│  │   Macro Assumption Calibrator                        │ │
│  │   (ECB SDMX + Eurostat · elasticity engine)         │ │
│  └─────────────────────────────────────────────────────┘ │
└────────────┬────────────────────────────────────────────┘
             │
    ┌────────▼───────┐
    │  SQLite (PoC)  │   → PostgreSQL (production)
    └────────────────┘
```

### Deployment Profiles

| Profile | Target | Stack |
|---|---|---|
| **Lite** | Windows laptop / personal | `pip install` + `uvicorn` + SQLite, sync execution |
| **Full** | Bank server | Docker Compose: app + nginx + postgres + redis + celery |

Single `DEPLOY_MODE=lite` env var switches behaviour. Same codebase, same calculation engine.

### PoC → Production Migration Path

The calculation engine is built as a **pure Python library** with no UI dependencies. Streamlit is a thin shell on top. When the model is validated, React + FastAPI replaces Streamlit without touching the engine.

---

## 4. Core Modules

### 4.1 Ingestion Module

Two public data sources provide comprehensive bank-level data. Together they cover >95% of the data points the calculation engine requires — the remaining gaps are estimated and calibrated (see Section 4.2).

#### 4.1.1 Data Sources & Refresh Cadence

| Source | Content | Frequency | Update trigger |
|---|---|---|---|
| **EBA Transparency Exercise** | Bank-by-bank structured data for ~120 EU banks (CSV/Excel). Covers capital, P&L, assets, liabilities, credit risk by segment/country/approach, NPE, sovereign, market risk, leverage. | **Annual** (published ~December, reference date typically June). Ad-hoc vintages possible. | Manual: user triggers re-import when new vintage is published. |
| **P3DH (EBA Pillar 3 Data Hub)** | Standardised CRR Pillar 3 disclosure templates for ~120 EU banks. More granular and more frequent than Transparency Exercise. Covers key metrics, own funds composition, credit risk by PD band, LCR/NSFR with full components, IRRBB metrics, MREL, operational risk SMA, asset encumbrance, ESG/climate. | **Quarterly** (Q1/Q2/Q3/Q4, published with ~3-month lag). | Automated: scheduler checks P3DH for new quarter availability and imports on detection. Manual override available. |

**Bundled default dataset:** The application ships with a pre-cached snapshot of the latest Transparency Exercise vintage and the latest P3DH quarter for all banks. This ensures the tool is usable immediately on first run without any API calls or downloads.

#### 4.1.2 EBA Transparency Exercise — Data Map

Source files: `tr_oth.csv` (capital, RWA, P&L, assets, liabilities, leverage), `tr_cre.csv` (credit risk, NPE, forborne, NACE, collateral), `tr_sov.csv` (sovereign exposures), `tr_mrk.csv` (market risk).

**Capital (tr_oth.csv — Capital template):**

| Data point | Item |
|---|---|
| Own Funds (total) | OWN FUNDS |
| CET1 capital (net of deductions, after transitional) | COMMON EQUITY TIER 1 CAPITAL |
| CET1 instruments + share premium | Capital instruments eligible as CET1 |
| Retained earnings | Retained earnings |
| AOCI | Accumulated other comprehensive income |
| Other reserves | Other Reserves |
| Funds for general banking risk | Funds for general banking risk |
| Minority interests in CET1 | Minority interest given recognition in CET1 |
| Prudential filters | Adjustments to CET1 due to prudential filters |
| (-) Intangible assets (incl. goodwill) | (-) Intangible assets (including Goodwill) |
| (-) DTAs on future profitability | (-) DTAs that rely on future profitability |
| (-) IRB shortfall | (-) IRB shortfall of credit risk adjustments to expected losses |
| (-) Pension fund assets | (-) Defined benefit pension fund assets |
| (-) Reciprocal cross holdings | (-) Reciprocal cross holdings in CET1 |
| (-) AT1 excess deduction | (-) Excess deduction from AT1 items |
| (-) 1250% deductions (incl. securitisation) | (-) Deductions related to assets at 1250% RW |
| (-) Holdings in fin. sector (non-significant) | (-) Holdings of CET1 of fin. sector entities (non-significant) |
| (-) DTAs from temporary differences | (-) Deductible DTAs from temporary differences |
| (-) Holdings in fin. sector (significant) | (-) Holdings of CET1 of fin. sector entities (significant) |
| (-) 17.65% threshold excess | (-) Amount exceeding the 17.65% threshold |
| (-) Additional CRR Art. 3 deductions | (-) Additional deductions due to Article 3 CRR |
| Other CET1 elements | CET1 capital elements or deductions - other |
| Transitional adjustments (grandfathered, minority, other) | 3 separate transitional adjustment items |
| IFRS 9 transitional adjustments (CET1, AT1, T2, RWA) | 4 separate IFRS 9 adjustment items |
| (-) Insufficient NPE coverage | (-) Insufficient coverage for non-performing exposures |
| (-) Minimum value commitment shortfalls | (-) Minimum value commitment shortfalls |
| (-) Other foreseeable tax charges | (-) Other foreseeable tax charges |
| AT1 capital (net), AT1 instruments, AT1 transitional | 4 items |
| T1 capital | TIER 1 CAPITAL |
| T2 capital (net), T2 instruments, T2 transitional | 4 items |
| Total RWA (post-floor) | TOTAL RISK EXPOSURE AMOUNT |
| Total RWA (pre-floor) | TOTAL RISK EXPOSURE AMOUNT - PRE FLOOR |
| CET1 / T1 / TC ratios (transitional + fully loaded, pre-floor + post-floor) | 8 ratio items |

**RWA OV1 (tr_oth.csv):**

| Data point | Breakdown |
|---|---|
| Credit risk RWA (excl. CCR) | Total + SA / F-IRB / A-IRB / equity IRB |
| CCR RWA | Counterparty credit risk (excl. CVA) |
| CVA risk | Credit valuation adjustment |
| Settlement risk | Settlement risk |
| Securitisation RWA | Securitisation (after cap) |
| Market risk RWA | Total + SA / IMA + securitisation in trading book |
| Large exposures in trading book | Large exposures |
| Operational risk RWA | Total + BIA / SA / AMA |
| Other risk amounts | Other risk exposure amounts |
| Total RWA | Pre-floor + floor adjustment + post-floor |

**P&L (tr_oth.csv):**

| Data point | Detail |
|---|---|
| Interest income | Total + from debt securities + from loans & advances |
| Interest expenses | Total + from deposits + from debt securities issued |
| Dividend income | — |
| Net fee & commission income | — |
| Trading P&L | HFT gains/losses + FVPL gains/losses + hedge accounting + FX |
| Derecognition gains/losses | Non-FVPL financial assets and non-financial assets |
| Net other operating income | — |
| **Total operating income** | — |
| Admin expenses | — |
| Depreciation | — |
| Provisions | Total + commitments/guarantees + other (incl. legal, restructuring) |
| Impairment | Total + FVOCI + amortised cost (separately) |
| Goodwill impairment | — |
| Share of associates P&L | — |
| **Pre-tax profit** | — |
| **Post-tax profit** | — |
| **Net income** | Total + attributable to parent |
| Modification gains/losses | — |
| Resolution fund contributions | Cash + provisions for commitments |

**Assets (tr_oth.csv) — by IFRS 9 stage (1/2/3):**

| Data point | Stage breakdown |
|---|---|
| Cash at central banks | — |
| HFT financial assets | — |
| Mandatory FVPL | — |
| Designated FVPL | — |
| FVOCI | Total + debt securities (gross + impairment) + loans (gross + impairment), **by Stage 1/2/3** |
| Amortised cost | Total + debt securities (gross + impairment) + loans (gross + impairment), **by Stage 1/2/3** |
| Hedge accounting derivatives | — |
| Other assets | — |
| **Total assets** | — |

**Liabilities (tr_oth.csv) — by financial instrument:**

| Data point | Instrument breakdown |
|---|---|
| Financial liabilities at amortised cost | Total |
| **Deposits** | Total + current accounts/overnight deposits |
| **Debt securities issued** | Total + subordinated |
| Derivatives (liability side) | — |
| Other financial liabilities | — |
| HFT liabilities | — |
| Designated FVPL liabilities | — |
| Provisions, tax liabilities | — |
| **Total liabilities** | — |
| **Total equity** | — |

**Credit Risk (tr_cre.csv) — the granular core:**

Dimensions on every data point: **approach** (SA/F-IRB/A-IRB) × **exposure class** (~30 classes) × **country** (~35) × **default status** (defaulted/non-defaulted) × **performance status** (performing/Stage 2/non-performing/Stage 3) × **NACE sector** (19 industries).

| Metric | Exposure class granularity |
|---|---|
| Original exposure | Central banks, governments, institutions, corporates (total + SME + specialised lending), retail (total + secured by RE + qualifying revolving + other + SME/non-SME), mortgages/ADC, in default, high risk, covered bonds, equity, other |
| Exposure value (post-CRM) | Same granularity |
| RWA | Same granularity |
| Value adjustments & provisions | Same granularity |

**NPE (tr_cre.csv):** Gross carrying amount, accumulated impairment, and collateral on NPEs — all by exposure class × country × performance status × stage. Includes off-balance sheet NPEs.

**Forborne (tr_cre.csv):** Forborne gross carrying, impairment, collateral — by instrument type × exposure class × performance. Quality metrics (forborne >2 times, failed exit criteria).

**NACE (tr_cre.csv):** Gross carrying amount and accumulated impairment by 19 NACE industry sectors.

**Collateral (tr_cre.csv):** Gross carrying on secured loans, impairment on secured, collateral values (capped at exposure + above cap), immovable property specifically, LTV bands (60-80%, 80-100%, >100%), financial guarantees, accumulated write-offs.

**Sovereign (tr_sov.csv):** By country × accounting portfolio (HFT/FVPL/FVOCI/amortised cost) × **maturity bucket** (0-3M, 3M-1Y, 1-2Y, 2-3Y, 3-5Y, 5-10Y, 10Y+). On-balance, derivatives (positive/negative FV + notional), off-balance, RWA.

**Market Risk (tr_mrk.csv):** Total RWA by product (debt/equity/FX/commodity) and model (SA/IMA). VaR and SVaR (60-day average × multiplier + previous day). IRC and CTP charges.

**Leverage (tr_oth.csv):** T1 capital (transitional + fully loaded), total leverage exposure, leverage ratios.

#### 4.1.3 P3DH (Pillar 3 Data Hub) — Data Map

89 templates across 5 modules. Updated **quarterly**. Key templates mapped to engine inputs:

**Common Disclosures Module:**

| Template | Content | Engine use |
|---|---|---|
| **K_61.00 — EU KM1** (Key Metrics) | CET1/T1/TC capital and ratios, RWA, leverage, LCR, NSFR, MREL — current + 4 prior periods | Dashboard KPIs, time-series trending |
| **K_66.01 — EU CC1** (Own Funds Composition) | Every CET1/AT1/T2 line item: instruments, retained earnings, AOCI, **every deduction individually** (AVA, intangibles, DTAs, IRB shortfall, pension, own holdings, cross-holdings, significant/non-significant investments, 17.65% threshold, losses, foreseeable tax), transitional. Buffer stack: P1R, CCoB, CCyB, SyRB, O-SII/G-SII, P2R. | **Complete CET1 bridge** — auto-populate all deductions. Buffer requirement calibration. |
| **K_60.00 — EU OV1** (RWA Overview) | RWA by risk type: credit (SA/F-IRB/A-IRB), CCR, CVA, settlement, securitisation, market (SA/A-IMA), operational. Output floor %, floor adjustment (pre + post transitional cap). Current + prior period. | RWA decomposition, output floor calibration |
| **K_26.00 — EU CR6** (IRB by PD Range) | For each PD band (0-0.15%, ..., 100% default): on-balance exposure, off-balance (pre-CCF), **weighted avg CCF**, exposure post-CRM, **weighted avg PD**, obligor count, **weighted avg LGD**, **weighted avg maturity**, RWA, RWA density, expected loss, provisions. | **Actual PD/LGD by portfolio** — direct input to ECL model and IRB RWA engine. |
| **K_24.00 — EU CR4** (SA CRM Effects) | SA exposures pre/post CRM, RWA, by exposure class. | SA RWA for output floor calculation |
| **K_25.00 — EU CR5** (SA Risk Weights) | SA exposures by risk weight bucket (0%, 20%, ..., 1250%), by exposure class. | SA RWA density by segment |
| **K_23.00 — EU CR3** (CRM Overview) | Secured/unsecured exposures, collateral types, guarantees. | Collateral coverage for LGD |
| **K_19.02 — EU OR2** (Business Indicator) | ILDC (interest/lease income+expense, assets, dividends), SC (fee income/expense, other operating), FC (trading P&L, banking book P&L). BI, BIC. **3 years + average.** | **Direct SMA operational risk RWA input** — no estimation needed. |
| **K_19.03 — EU OR3** (Op Risk RWA) | BIC, own funds requirement, risk exposure amount. | Operational risk RWA validation |
| **K_02.00–K_08.00** (CCR templates) | CCR by approach, collateral, credit derivatives, CCP exposures. | Counterparty credit risk RWA |
| **K_63.01–K_63.02 — EU CMS1/CMS2** | SA vs internal model RWA comparison at risk and asset class level. | Output floor impact analysis |
| **K_67.01–K_67.02 — EU CCyB1/CCyB2** | Geographic distribution for CCyB + institution-specific CCyB rate. | Buffer stack calibration |
| **K_70.00–K_72.00 — EU LR1/LR2/LR3** | Leverage ratio: accounting-to-exposure reconciliation, full common disclosure, on-balance split. | Leverage ratio decomposition |
| **K_68.00 — EU IRRBB1** | **ΔNII and ΔEVE under all 6 EBA standardized shocks** (parallel up/down, steepener, flattener, short up/down). Current + last period. | **Calibration target for IRRBB engine** — see Section 4.2. |
| **K_73.00 — EU LIQ1** (LCR) | Full LCR: HQLA, retail deposits (stable/less stable), wholesale (operational/non-operational), unsecured debt, secured, derivative outflows, credit/liquidity facilities, all inflow categories, inflow caps. **Unweighted + weighted values. 4 quarters.** | **Complete LCR with actual components** — no simplified model needed. |
| **K_74.00 — EU LIQ2** (NSFR) | Full NSFR: ASF by category (capital, retail stable/less stable, wholesale operational/other, other liabilities) and RSF (HQLA, performing loans/securities, mortgages, off-balance). **By maturity: no maturity / <6M / 6M-1Y / ≥1Y.** | **Complete NSFR with actual ASF/RSF** — no simplified model needed. |
| **K_90.01 — EU KM2** (MREL Key Metrics) | Own funds + eligible liabilities as % of TREA and TEM. Subordination. **5 years of history.** | MREL adequacy tracking |
| **K_91.00 — EU TLAC1** (MREL Composition) | CET1, AT1, T2, subordinated eligible liabilities, non-subordinated (pre/post cap). Buffer stack: CCoB, CCyB, SyRB, G-SII/O-SII. CET1 available after all requirements. | MREL composition, available headroom |

**Financial Disclosures Module:**

| Template | Content | Engine use |
|---|---|---|
| **K_21.01 — EU CR1** | Performing and non-performing exposures + provisions, **by segment × stage** (performing Stage 1 / performing Stage 2 / non-performing Stage 2 / non-performing Stage 3). By exposure class (loans: central banks, governments, institutions, other financial, **corporates**, of which SME, **households**; debt securities by same). Off-balance sheet. Write-offs. | **NPL/NPE by segment and stage.** Provisions by segment and stage. Stage 1/2/3 balances. |
| **K_21.02 — EU CR1-A** (Maturity) | Loans and advances + debt securities by maturity: **on demand / ≤1Y / 1-5Y / >5Y / no stated maturity.** | **Basic repricing/maturity profile** — 4 buckets for gap estimation. |
| **K_22.01 — EU CR2** (NPL Flows) | Opening NPL stock + inflows - outflows (write-offs + other) = closing NPL stock. | **Default/cure rate calibration** from actual flow data. |
| **K_22.02 — EU CR2a** (NPL Recoveries) | Changes in NPL stock with net accumulated recoveries. | Recovery rate estimation |
| **K_80.00–K_87.00 — EU CQ1-CQ8** | Forborne quality, past-due buckets, NPE by geography, credit quality by industry, collateral valuation, collateral obtained (including vintage). | Granular asset quality by geography and industry, collateral LTV |
| **K_20.01–K_20.03 — EU AE1-AE3** | Asset encumbrance: encumbered vs unencumbered (with EHQLA/HQLA flag), by asset type. Sources of encumbrance. | HQLA eligibility, LCR buffer validation, covered bond capacity |

**IRRBB Disclosures Module:**

| Template | Content | Engine use |
|---|---|---|
| **K_68.00 — EU IRRBB1** | ΔNII (columns a/b: current + last period) and ΔEVE (columns c/d: current + last period) for each of 6 shocks. | See Section 4.2 — calibration target |

**MREL/TLAC Disclosures Module:**

| Template | Content | Engine use |
|---|---|---|
| K_90.01, K_91.00, K_93.00, K_95.00, K_97.00, K_98.00 | Full MREL/TLAC framework. | MREL adequacy, creditor hierarchy |

**ESG Disclosures Module:**

| Template | Content | Engine use |
|---|---|---|
| **K_41.00** (Template 1) | Climate transition risk: credit quality by NACE sector × emissions × residual maturity. | ESG stress scenarios (Phase 2) |
| **K_42.00** (Template 2) | Loans collateralised by immovable property — energy efficiency of collateral. | Green mortgage LGD adjustments |
| **K_43.00** (Template 3) | Alignment metrics by NACE sector. | Transition risk exposure |
| **K_44.00** (Template 4) | Exposures to top 20 carbon-intensive firms. | Concentration risk |
| **K_45.00** (Template 5) | Physical risk exposures. | Climate physical risk |
| **K_46.00–K_50.00** (Templates 6-10) | GAR/BTAR KPIs, mitigating actions, taxonomy alignment. | Taxonomy reporting |

#### 4.1.4 Data Refresh Pipeline

```
Quarterly (automated):
  1. Check P3DH for new quarter availability
  2. Download new P3DH data for all banks
  3. Parse and validate
  4. Upsert into database (preserve historical quarters)
  5. Re-compute peer distributions (for rating percentile grid)
  6. Log refresh result + timestamp

Ad-hoc (user-triggered):
  1. User uploads new EBA Transparency Exercise vintage (Excel/CSV)
  2. Parse and validate against SDD schema
  3. Upsert into database
  4. Merge with P3DH data (P3DH takes precedence for overlapping fields
     since it is more frequent)
  5. Re-compute peer distributions

Data precedence:
  P3DH quarterly data is the primary source (more granular, more frequent).
  Transparency Exercise fills gaps where P3DH templates are not available
  (e.g., sovereign maturity profile, NACE breakdown, collateral LTV bands).
  When both sources report the same metric, P3DH is preferred unless
  the Transparency Exercise vintage is more recent.
```

#### 4.1.5 Validation Layer

- Balance sheet identity: Assets = Liabilities + Equity (within 0.1% tolerance)
- Capital ratio consistency: CET1_capital / RWA = CET1_ratio (within rounding)
- Cross-source consistency: key metrics from Transparency vs P3DH flagged if divergence > 5%
- Outlier flagging: any metric >3 SD from peer group mean is flagged (logged, not rejected)
- Missing field handling: NaN with visible warning (never silently default to zero)
- Schema validation: all fields checked against SDD data dictionary

#### 4.1.6 Phase 2 Additions

- Own-bank Excel template upload (key balance sheet, P&L, repricing gap data)
- FINREP / COREP template ingestion (own bank regulatory data)
- Internal management accounts Excel ingestion with column mapping wizard
- Mapping templates saved and reusable per bank

---

### 4.2 Base Year Construction

The base year (Year 0) is the starting point for all forward projections. It is constructed automatically from ingested public data, with a small number of calibrated estimates for data points not available from public sources.

#### 4.2.1 Executive Workflow

```
1. SELECT BANK
   User picks from ~120 EU banks (identified by LEI code).
   System loads latest P3DH quarter + latest Transparency Exercise vintage.
       ↓
2. AUTO-POPULATE BASE YEAR (>95% of data points)
   All items below are populated directly from public data — zero estimation:

   Capital:
   ✓ Complete CET1 bridge with every deduction (CC1)
   ✓ AT1, T2 composition
   ✓ Buffer stack: P1R + CCoB + CCyB + SyRB + O-SII/G-SII + P2R (CC1)
   ✓ MDA trigger level
   ✓ IFRS 9 transitional adjustments
   ✓ MREL composition, requirement, headroom (KM2 + TLAC1)
   ✓ Leverage ratio components (LR1/LR2/LR3)

   RWA:
   ✓ Full OV1: credit (SA/F-IRB/A-IRB), CCR, CVA, market (SA/IMA),
     operational, securitisation (OV1)
   ✓ Output floor percentage + floor adjustment (OV1)
   ✓ SA RWA by exposure class and risk weight (CR4, CR5)

   P&L:
   ✓ NII decomposed: interest income (from securities + from loans)
     vs interest expense (from deposits + from debt issued)
   ✓ Fee income, trading P&L (by type), other operating
   ✓ Admin expenses, depreciation
   ✓ Provisions (by type), impairment (FVOCI + amortised cost)
   ✓ Pre-tax, post-tax, net income

   Credit risk:
   ✓ Loan book by 30+ exposure classes × SA/IRB × country × NACE (Credit Risk templates)
   ✓ PD / LGD / EAD / maturity by PD band — for IRB portfolios (CR6)
   ✓ SA exposures by risk weight bucket (CR5)
   ✓ NPL/NPE by segment × stage (CR1)
   ✓ Provisions by segment × stage (CR1)
   ✓ NPL flows: inflows, outflows, write-offs (CR2)
   ✓ Forborne exposures + quality metrics (CQ1, CQ2)
   ✓ Collateral coverage, LTV bands (Collateral template)
   ✓ Geographic concentration (by country)
   ✓ Industry concentration (by NACE sector)

   Funding & Liquidity:
   ✓ Deposits (total + current accounts/overnight) (Liabilities template)
   ✓ Debt securities issued (total + subordinated) (Liabilities template)
   ✓ LCR with ALL components: HQLA, retail/wholesale outflows,
     inflows, caps (LIQ1) — 4 quarters of history
   ✓ NSFR with full ASF/RSF by maturity bucket (LIQ2)
   ✓ Asset encumbrance (AE1-AE3)

   IRRBB:
   ✓ ΔNII under 6 EBA shocks (current + prior period) (IRRBB1)
   ✓ ΔEVE under 6 EBA shocks (current + prior period) (IRRBB1)

   Operational risk:
   ✓ Full Business Indicator decomposition: ILDC, SC, FC, BI, BIC (OR2)
   ✓ Op risk own funds requirement and REA (OR3)
   ✓ 10-year operational loss history (OR1)

   Sovereign:
   ✓ Sovereign portfolio by country × accounting portfolio × 7 maturity buckets

   ESG:
   ✓ Climate transition risk by sector (Template 1)
   ✓ Energy efficiency of collateral (Template 2)
   ✓ Physical risk exposures (Template 5)
       ↓
3. CALIBRATE ESTIMATES (only 4 items require estimation)

   a. REPRICING GAP (10-bucket IRRBB granularity):
      Not directly available from public data. Estimated via:
      Step 1: Start with CR1-A maturity profile (on-demand / ≤1Y / 1-5Y / >5Y)
      Step 2: Add sovereign maturity profile (7 buckets from Transparency)
      Step 3: Interpolate to 10 IRRBB buckets (ON/1M/3M/6M/1Y/2Y/3Y/5Y/7Y/10Y+)
              using proportional allocation within each CR1-A band
      Step 4: CALIBRATE against disclosed IRRBB1 metrics:
              - Run the IRRBB engine on the estimated gap
              - Compare computed ΔNII and ΔEVE against disclosed values
              - If mismatch > 10%, adjust gap distribution via least-squares
                fitting to minimize the distance to all 12 disclosed values
                (6 shocks × ΔNII + ΔEVE)
              - Display: "Estimated repricing gap produces ΔNII within X% of
                disclosed figure"
      Confidence: MEDIUM (calibrated against actual disclosed metrics)
      User can override any bucket manually.

   b. FIXED vs FLOATING SPLIT:
      Not directly available. Estimated from:
      - Country heuristic: southern EU ~55-65% floating, northern EU ~35-45%
      - Cross-checked against the disclosed ΔNII for parallel +200bp shock:
        higher ΔNII → more floating-rate exposure → higher floating share
      Confidence: MEDIUM
      User override expected for accuracy.

   c. NMD BEHAVIOURAL PARAMETERS (beta, core/non-core, decay):
      Not available from public data. Default values applied:
      | Product | Default beta | Default core % | Default avg life |
      |---|---|---|---|
      | Current accounts (retail) | 0.20 | 80% | 4Y |
      | Savings accounts | 0.40 | 60% | 3Y |
      | Corporate deposits | 0.60 | 40% | 2Y |
      NMD volume is derived from LIQ1 (retail deposits: stable + less stable)
      and Liabilities template (current accounts/overnight).
      Parameters are calibrated against disclosed IRRBB1 metrics (same
      fitting as repricing gap — NMD parameters affect ΔNII sensitivity).
      Confidence: LOW-MEDIUM
      User calibration strongly recommended.

   d. HEDGE PORTFOLIO:
      Not available from public data (hedges are not disclosed at instrument level).
      Default: no hedges.
      User inputs their hedge instruments (IRS type, notional, tenor, fixed rate).
      The IRRBB pre-hedge vs post-hedge comparison uses disclosed IRRBB1
      as the "current state" (which includes the bank's actual hedges).
       ↓
4. REVIEW BASE YEAR VALIDATION SCREEN

   The UI displays a "Base Year Review" panel before allowing forward projection:

   ┌─────────────────────────────────────────────────────────────┐
   │  BASE YEAR VALIDATION — [Bank Name] — [Reference Date]     │
   ├─────────────────────────────────────────────────────────────┤
   │  Source: P3DH Q2 2025 + Transparency Exercise 2024         │
   │                                                             │
   │  ✅ Capital:     CET1 14.2%  [CC1 — complete]              │
   │  ✅ RWA:         €72.3bn     [OV1 — complete]              │
   │  ✅ P&L:         NII €2.1bn  [Transparency — complete]     │
   │  ✅ Credit risk:  NPL 2.1%   [CR1 — by segment × stage]   │
   │  ✅ PD/LGD:      IRB         [CR6 — by PD band]           │
   │  ✅ LCR:         142%        [LIQ1 — full components]      │
   │  ✅ NSFR:        118%        [LIQ2 — full ASF/RSF]        │
   │  ✅ MREL:        27.3% TREA  [TLAC1 — complete]            │
   │  ✅ IRRBB:       ΔNII +200bp = +€180m [IRRBB1 — disclosed]│
   │  ✅ Op risk:     BI = €3.2bn [OR2 — complete]              │
   │                                                             │
   │  ⚠️  Repricing gap:  ESTIMATED (calibrated to IRRBB1)     │
   │      → ΔNII within 4% of disclosed [Edit gap]             │
   │  ⚠️  Fixed/float:   ESTIMATED (58% floating)              │
   │      → Based on country heuristic + ΔNII cross-check [Edit]│
   │  ⚠️  NMD params:    DEFAULT VALUES                         │
   │      → Using standard EU profiles [Calibrate]              │
   │  ⚠️  Hedges:        NONE (user input required)             │
   │      → [Add hedge instruments]                              │
   │                                                             │
   │  [Accept & Proceed to Plan Builder]  [Export Base Year]     │
   └─────────────────────────────────────────────────────────────┘

   The executive reviews, optionally adjusts the 4 estimated items,
   and proceeds to the Business Plan Builder with a fully populated
   base year.
       ↓
5. SET FORWARD ASSUMPTIONS → RUN PROJECTION → ITERATE
```

#### 4.2.2 Segment Mapping

EBA exposure classes are mapped to the engine's 5 loan segments:

| Engine segment | EBA exposure classes (aggregated) |
|---|---|
| **Corporate** | Corporates (excl. SME) + Specialised Lending + Non-financial corporations (excl. SME) |
| **Mortgage** | Retail secured by RE (non-SME) + Households collateralised by residential immovable property + Secured by mortgages on immovable property (non-SME) |
| **Consumer** | Retail qualifying revolving + Retail other (non-SME) + Households credit for consumption |
| **SME** | Corporate SME + Retail SME + Non-financial corporations SME |
| **Public sector** | Central governments/banks + Regional governments + Public sector entities + Multilateral development banks |

This mapping is applied to: original exposure, exposure value, RWA, provisions, NPL/NPE, PD/LGD (IRB), and is configurable if a bank's portfolio doesn't fit the standard mapping.

#### 4.2.3 Segment Margin Derivation

Total NII is known from P&L. Segment-level margins are derived:

1. Blended asset yield = Interest income from loans / Average gross loans
2. Blended funding cost = Interest expense / Average interest-bearing liabilities
3. Blended NIM = asset yield - funding cost
4. Segment margin allocation: apply typical EU spread differentials to the blended NIM:

| Segment | Spread adjustment vs blended |
|---|---|
| Corporate | −20 to −40 bps (tighter spreads, larger tickets) |
| Mortgage | −10 to −20 bps (secured, lower risk weight) |
| Consumer | +80 to +150 bps (unsecured, higher risk) |
| SME | +20 to +50 bps (higher risk, smaller tickets) |
| Public sector | −40 to −60 bps (sovereign-linked, low risk) |

The spread differentials are calibrated so that the weighted sum across segments equals the known total NII. User can override individual segment margins.

---

### 4.3 Calculation Engine

Full 5-year projection at quarterly granularity. Driven by user assumptions, cascades automatically when strategy changes.

#### 4.3.1 Iterative Convergence Loop

The quarterly projection has circular dependencies (NII → net income → retained earnings → equity → funding requirement → funding cost → NII; and for IRB banks: asset quality → PD/LGD → RWA → capital ratios). The engine resolves these through an **iterative convergence loop**:

1. **Initial pass:** Run all sub-modules sequentially using previous-quarter state as starting estimates
2. **Convergence iterations:** Re-run the cascade using updated values from the previous iteration
3. **Termination:** Stop when all key variables (equity, RWA, NII, CET1 ratio) change by less than **0.01%** between iterations, or after a maximum of **5 iterations** (with a convergence warning if the cap is hit)

This ensures internal consistency between interdependent quantities in every quarter.

#### 4.3.2 P&L

- Net Interest Income (NII) and NIM decomposition by asset segment
- **NII Bridge (quarterly + cumulative):** volume, mix, base rate, deposit pass-through, funding spread, hedge impact, credit migration (Stage 2/3) effects on interest income
- Fee & commission income
- Trading income
- Operating expenses / Cost-to-Income Ratio (CIR)
- Loan loss provisions — **driven by the IFRS 9 ECL model** (see Section 4.3.5), not exogenous CoR
- Tax, net income

#### 4.3.3 Balance Sheet

- Loan book by segment (corporate, mortgage, consumer, SME, public sector)
- Securities portfolio (FVOCI and amortised cost)
- RWA: credit risk (SA and IRB paths), market risk, operational risk (see Section 4.3.7)
- Basel IV output floor (see Section 4.3.6)
- Funding: retail deposits, wholesale (by tenor), covered bonds, MREL/TLAC instruments
- **Funding curve stack (by instrument class):** retail deposits, wholesale senior, covered bonds, MREL/T2; separate base rate + spread components

#### 4.3.4 Capital — Regulatory CET1 Bridge

Capital ratios are **regulatory ratios**, not accounting equity ratios. The engine computes a full CET1 bridge:

```
Accounting shareholders' equity
  + Net income (retained)
  − Dividends declared (see Section 4.3.8)
  + CET1 issuances − buybacks
  = Accounting equity (end of period)

  Prudential adjustments:
  − Goodwill and other intangible assets
  − Deferred tax assets relying on future profitability (above threshold)
  − Significant investments in financial sector entities (above threshold)
  − IRB shortfall (expected loss > provisions)
  − Prudent valuation adjustment (AVA)
  + / − IFRS 9 transitional relief (phase-out schedule: 25% add-back 2025, 0% from 2028)
  − AOCI prudential filter (unrealised gains/losses on FVOCI securities, per CRR treatment election)
  = CET1 capital

CET1 ratio = CET1 capital / max(RWA_internal, RWA_floor)  [see Section 4.3.6]
Tier 1 = CET1 + AT1 instruments (with regulatory amortisation and call features)
Total Capital = Tier 1 + Tier 2 instruments
Leverage ratio = Tier 1 / total exposure measure
```

**Buffer stack and MDA:**
- CET1 requirement = Pillar 1 (4.5%) + P2R + CCoB (2.5%) + CCyB (country-specific) + SyRB + O-SII/G-SII buffer
- MDA trigger = sum of all requirements. Breach triggers automatic distribution restrictions (dividends, AT1 coupons, variable remuneration)
- P2G headroom (Pillar 2 guidance — non-binding but monitored by ECB/SSM)

**MREL adequacy:**
- MREL available = own funds + eligible liabilities (subordinated, >1Y residual maturity)
- MREL requirement = bank-specific SRB target (typically 8% TLOF + recapitalisation amount)
- MREL surplus / deficit tracked and reported alongside capital ratios

**CFO Bridges (core outputs):**
- **CET1 Bridge** (quarterly + cumulative): net income, dividends/buybacks, CET1 issuances, prudential deductions, IFRS 9 transitional effects, RWA floor add-on
- **ROE Bridge**: NII, fees, trading, opex, provisions, tax, capital actions
- **RWA Bridge**: credit SA/IRB, CCR/CVA, market, operational, securitisation, output floor add-on (split into volume vs risk-weight vs PD/LGD shifts)

#### 4.3.5 IFRS 9 Expected Credit Loss Model

Provisions are **output** of the ECL model, not an exogenous CoR assumption. The user provides credit quality assumptions (PD curves, LGD); the engine computes provisions:

**Stage classification:**
- **Stage 1** (performing, no SICR): 12-month ECL
- **Stage 2** (SICR triggered): Lifetime ECL
- **Stage 3** (credit-impaired, 90 DPD or UTP): Lifetime ECL with defaulted exposure treatment

**SICR trigger** (Stage 1 → Stage 2):
- Relative criterion: lifetime PD has increased by more than **2.0×** vs origination PD
- Absolute criterion: lifetime PD exceeds **1.0%** (configurable per segment)
- Either criterion triggers Stage 2; both can be overridden by the user

**ECL calculation:**

```
Stage 1 ECL = PD_12m × LGD × EAD, discounted at Effective Interest Rate (EIR)
Stage 2 ECL = Σ(t=1..T) [marginal_PD(t) × LGD(t) × EAD(t) × discount_factor(t)]
              where T = remaining contractual maturity
Stage 3 ECL = LGD × EAD (100% PD, discounted at EIR)
```

**Forward-looking overlay (IFRS 9.5.17):**

ECL is computed under **three probability-weighted macro scenarios**:
1. Base case (plan assumptions) — weight: 50% (configurable)
2. Upside — weight: 20%
3. Downside (from stress engine) — weight: 30%

Weighted ECL = Σ(scenario_weight × scenario_ECL)

This produces provisions that flow into P&L. The user-visible CoR (bps) is a derived output: CoR = total provisions / average gross loans.

**Stage migration flows:**

```
Stage 1 → Stage 2: SICR trigger (PD deterioration)
Stage 2 → Stage 3: Default (90 DPD or UTP event)
Stage 3 → Stage 2: Cure (with 6-month probation period, configurable)
Stage 2 → Stage 1: PD recovers below SICR threshold (with 3-month probation)
```

#### 4.3.6 Basel IV Output Floor (CRR3)

The output floor compares aggregate internal-model RWA against the standardised approach. The SA used for the floor is **CRR3 final standardised approach** — not legacy CRR SA. Key differences from legacy SA:

- **Real estate exposures:** Split by LTV bands (≤55%, 55–80%, >80%) with different risk weights
- **Unrated corporates:** New SME supporting factor treatment, revised risk weights
- **Equity exposures:** Higher risk weights (250%+ for speculative holdings)
- **Operational risk:** Standardised Measurement Approach replaces all previous approaches (see Section 4.3.7)

**Floor calculation (aggregate level):**

```
SA_RWA_total = SA_credit_RWA + SA_market_RWA + SA_operational_RWA
Floor_RWA = SA_RWA_total × phase_in_percentage
RWA_total = max(internal_RWA_total, Floor_RWA)
RWA_add_on = max(0, Floor_RWA − internal_RWA_total)

Phase-in: 50% (2025) → 55% (2026) → 60% (2027) → 65% (2028) → 70% (2029) → 72.5% (2030+)
```

The floor is applied at aggregate level (not per-segment). Both SA and internal RWA include credit, market, and operational risk.

#### 4.3.7 Operational Risk RWA — Standardised Measurement Approach (SMA)

**Business Indicator (BI) calculation:**

```
BI = ILDC + SC + FC
  where:
  ILDC = Interest, Lease and Dividend Component
       = max(interest_income − interest_expense, 0) + dividend_income + lease_income
  SC   = Services Component
       = max(fee_income, fee_expense) + max(other_operating_income, other_operating_expense)
  FC   = Financial Component
       = abs(trading_P&L) + abs(banking_book_P&L)
```

**BI Component (BIC):**

| BI bucket | BI range | Marginal coefficient |
|---|---|---|
| 1 | ≤ €1bn | 12% |
| 2 | €1bn – €30bn | 15% |
| 3 | > €30bn | 18% |

BIC = 12% × min(BI, €1bn) + 15% × min(max(BI − €1bn, 0), €29bn) + 18% × max(BI − €30bn, 0)

**Internal Loss Multiplier (ILM):** Set to **1.0** in PoC (no internal operational loss history available from public data; EU CRR3 allows national discretion to set ILM = 1).

**Op risk RWA = BIC × ILM = BIC × 1.0**

#### 4.3.8 Dividend Policy & Distribution Restrictions

- **Payout ratio target:** User sets target dividend payout ratio (% of net income)
- **MDA restriction engine:** When CET1 ratio falls below MDA trigger:
  - Compute Maximum Distributable Amount per CRD V Article 141:
    - CET1 shortfall below combined buffer → restricts distributions to 0%, 20%, 40%, or 60% of distributable profits depending on which quartile of the buffer the shortfall falls in
  - Auto-restrict: dividends, AT1 coupon payments, variable remuneration
- **AT1 coupon:** Paid from distributable items; cancelled if MDA is breached (no deferral — AT1 coupons are non-cumulative)
- **DPS vs buyback:** User specifies split between cash dividends and share buybacks (buybacks reduce share count → affect TBVPS)

#### 4.3.9 Asset Quality

- NPL ratio, NPE coverage ratio — driven by IFRS 9 stage migration (Section 4.3.5)
- Stage 1 / Stage 2 / Stage 3 balances and migration flows
- PD/LGD by segment (IRB banks): user-input PD term structures, scenario-dependent LGD
- CoR trajectory — **derived output** of the ECL model, not input

#### 4.3.10 Liquidity — LCR and NSFR

**Base year:** Full LCR and NSFR with all components are sourced directly from P3DH (EU LIQ1 / EU LIQ2) — no simplification needed. Four quarters of history are available. See Section 4.2 for the complete list of LCR/NSFR components available from P3DH.

**Forward projection:** For projected periods (Year 1–5), LCR and NSFR are re-computed using a simplified model that applies regulatory run-off/haircut factors to the projected balance sheet. **Forward-projected liquidity ratios are labelled as "indicative — simplified model" in all outputs.**

**Liquidity survival horizon:**
- Computes survival days under idiosyncratic and market-wide stress (cash flow-based)
- Links to ILAAP internal liquidity buffer and contingency funding plan

**LCR projection model:**

```
HQLA:
  Level 1 (0% haircut): cash + central bank reserves + sovereign bonds (0% RW)
  Level 2A (15% haircut): covered bonds (CQS1), corporate bonds (CQS1), sovereign bonds (20% RW)
  Level 2B (50% haircut): corporate bonds (CQS2-3), equity (major index)
  Cap: Level 2 ≤ 2/3 of Level 1; Level 2B ≤ 15/85 of total HQLA

Net cash outflows (30-day):
  Retail deposits: insured 5%, other 10%
  Operational deposits: 25%
  Wholesale (unsecured, financial): 100%
  Wholesale (unsecured, non-financial): 40%
  Committed facilities (to financials): 40%; (to non-financials): 10%
  Inflows: capped at 75% of outflows

LCR = HQLA / net_outflows × 100%
```

**NSFR projection model:**

ASF/RSF factors applied per CRR Article 428 categories:
- Stable retail deposits: 95% ASF
- Less stable retail: 90% ASF
- Wholesale funding <6M: 0% ASF; 6M–1Y: 50% ASF; >1Y: 100% ASF
- Performing loans <6M: 50% RSF; 6M–1Y: 65% RSF; >1Y: 85% RSF
- Sovereign bonds: 5% RSF; other HQLA L2: 15% RSF

**Simplification disclaimer (forward projection only):** Projected liquidity ratios use regulatory run-off/haircut factors applied to aggregate balance sheet categories. Full regulatory LCR/NSFR computation requires counterparty-level cash flow data not available for forward periods. Base year values are actual disclosed figures.

#### 4.3.11 Sensitivity Analysis Tables

In addition to full scenario projections, the engine produces **standardised sensitivity tables** for key metrics:

| Sensitivity | Metric impacted | Method |
|---|---|---|
| NII per +/- 100bp parallel rate shift | NII | IRRBB repricing gap |
| CET1 per +10bp CoR | CET1 ratio | Re-run ECL with PD + 10bp |
| CET1 per €1bn RWA increase | CET1 ratio | Arithmetic |
| ROE per 1pp CIR change | ROE | P&L re-run |
| NPL ratio per 50bp PD shock | NPL | Stage migration re-run |
| EVE per +/- 100bp parallel shift | EVE | IRRBB EVE model |
| CET1 per 10% property price decline | CET1 ratio | LGD uplift on mortgage/CRE |

Sensitivities are computed once per projection and displayed in the Dashboard and Reports.

#### 4.3.12 Funding Curve Engine & Deposit Pass-Through

**Funding curve stack:**
- Each liability class has its own curve: retail deposits, wholesale senior unsecured, covered bonds, MREL/T2
- Each curve = base rate (risk-free) + instrument spread
- Spreads are driven by rating level, liquidity ratios (LCR/NSFR), market stress (credit spread), and tenor
- Calibration sources: proxy spreads and peer-average spreads (primary), with user overrides

**Deposit pass-through (beta) model:**
- Beta per product (current, savings, term) and per segment (retail/SME/corporate)
- **Asymmetric betas:** separate up-rate vs down-rate betas
- **Lag structure:** configurable repricing lags and ramp profiles (e.g., 1–4 quarters)
- **Rate floors/caps:** deposit rate floors at 0% and optional product caps
- **Volume elasticity:** migration to term deposits or outflows when beta exceeds a threshold; modeled as a volume retention function
- **Stress overlay:** higher betas and shorter lags under liquidity stress; documented in scenario assumptions

**NII bridge integration:**
- NII impact decomposed into base rate change, pass-through change, funding spread change, volume/mix shift, hedges

#### 4.3.13 Market & Shareholder Metrics

**Market data inputs (Phase 1, external):**
- Equity price series, dividends, shares outstanding (via yfinance where available)
- Bank-specific ticker mapping (configurable, manual overrides for EU listings)

**Computed outputs:**
- EPS, DPS, payout ratio, dividend yield, buyback yield
- ROTE and TBVPS (tangible equity and tangible book value per share)
- Valuation multiples: P/E, P/TBV, implied cost of equity
- Total shareholder return (TSR) over plan horizon and historical window

**Segment profitability:**
- **RAROC per segment** = (segment net income after expected credit loss) / (segment economic capital)
- Economic capital proxy: segment RWA × target CET1 ratio (configurable) or IRB capital requirement

#### 4.3.14 Funds Transfer Pricing (FTP)

- Internal pricing curves for assets and liabilities by segment and tenor
- FTP curves derived from funding curve stack with liquidity premium and term adjustments
- Feeds NII bridge, segment profitability, and steering decisions

#### 4.3.15 VBM Lite

- Economic profit = (ROTE − cost of equity) × tangible equity
- Value contribution by segment using RAROC vs hurdle rate
- Value bridge aligned to NII/CET1/ROE bridges

#### 4.3.16 Error Handling

All financial calculations follow these rules:
- **Division by zero:** Returns NaN with a warning flag (e.g., ROE when equity ≤ 0)
- **Negative equity:** Triggers a "bank failure" warning in the UI; projection continues (showing the trajectory) but marks all periods post-failure
- **NaN propagation:** Any NaN in a critical input (e.g., missing PD curve) blocks the projection with a clear error message listing missing inputs, rather than propagating silently
- **Infeasible states:** If CET1 < 0 under stress, the stress run completes but flags the scenario as "institution non-viable" in results
- **Convergence failure:** If the iterative loop (Section 4.3.1) does not converge within 5 iterations, the projection completes with a warning badge showing which variables did not converge and by how much

---

### 4.4 IRRBB / ALM Module

Interest rate risk is a first-class module — not an afterthought.

**Rate Input Layer:**
- Yield curve: EURIBOR term structure (ON, 1M, 3M, 6M, 12M) + EUR swap curve (2Y–30Y)
- User inputs current curve + forward path (base / up / down)
- 6 EBA standardized IRRBB shocks pre-loaded: parallel ±200bp, steepener, flattener, short rate ±
- Rate floor: −100bp for EUR per current EBA guidance (configurable)

**Repricing Gap Model:**
- Asset buckets: ON, 1M, 3M, 6M, 1Y, 2Y, 3Y, 5Y, 7Y, 10Y+
- Liability buckets: same granularity
- Floating rate assets: by EURIBOR index and reset frequency
- Fixed rate assets: slotted by contractual maturity

**NMD Behavioural Model:**
- Core vs non-core deposit split per product (current accounts, savings, term)
- Deposit beta per product (rate pass-through)
- **Weighted average repricing maturity (WAM) cap: 5 years** per EBA NMD guidelines. Individual deposit tranches may have modelled lives beyond 5Y provided the portfolio WAM stays at or below 5Y.
- **Regulatory floor on non-core volume:** A minimum percentage of NMD volume must be classified as non-core (rate-sensitive). Default: 10% of total NMD volume (configurable per product). This prevents over-optimistic stability assumptions.
- **Volume elasticity to rates:** In rising rate environments, NMD volumes can shrink as depositors migrate to term deposits. Modelled as: `volume_retention = base_volume × (1 − migration_rate × max(0, rate_change))` where migration_rate is calibrated per product type (default: 5% per 100bp rate increase for savings, 2% for current accounts).
- Decay rate + average behavioural life

**Deposit pricing layer (ties to Funding Curve Engine):**
- Deposit pricing uses product-level betas, lags, and floors as defined in Section 4.3.13
- NII and IRRBB outputs surface the contribution of deposit repricing separately

**Hedging Overlay:**

| Instrument | Effect | Valuation |
|---|---|---|
| Receive-fixed IRS | Extends asset duration | **OIS-discounted** NPV; cash flows = fixed leg − floating leg per quarter |
| Pay-fixed IRS | Shortens liability duration | OIS-discounted NPV |
| Caps / Floors | Optionality on floating rate exposure | **Phase 1: vanilla IRS only.** Caps/floors require implied vol surface — deferred to Phase 2 (see Section 4.8) |
| Cross-currency swaps | FX + rate combined exposure | **Deferred to Phase 2** (no FX exposure in Phase 1 balance sheet) |

Pre-hedge vs post-hedge view across all IRRBB metrics.

**Day count convention:** ACT/360 for EURIBOR-linked cash flows, 30/360 for fixed-rate bond-equivalent flows. Configurable per instrument.

**EVE Calculation Methodology:**

EVE (Economic Value of Equity) is computed per EBA/GL/2022/14 standardised framework:

```
EVE = PV(asset cash flows) − PV(liability cash flows)

Cash flow generation:
  For each repricing gap bucket:
    1. Convert gap volume to a cash flow stream (principal repayment at repricing date
       + coupon payments at the bucket's assumed rate × volume × time fraction)
    2. For NMDs: use the behavioural model's bucket distribution to generate modelled cash flows
    3. For hedges: add IRS fixed/floating leg cash flows

Discounting:
  All cash flows discounted at the **EUR risk-free swap curve** (OIS curve),
  per EBA standardised framework. NOT the bank's own funding curve.

ΔEVE = EVE(shocked curve) − EVE(base curve)
```

**IRRBB Metrics Computed:**
- ΔNIIi across all 6 EBA standardized shocks (1Y and 3Y horizon)
- ΔEVE across same 6 scenarios
- NII at Risk (worst-case NII, 1Y and 3Y)
- Duration gap (Macaulay duration of assets − Macaulay duration of liabilities)
- **Basis risk:** NII impact of EURIBOR tenor spread changes. Computed as: for each mismatched notional (e.g., assets at EURIBOR 3M, liabilities at EURIBOR 6M), apply a ±10bp spread shock between tenor pairs and compute the NII delta. Reported as total basis risk NII impact.
- Prepayment sensitivity on mortgage/consumer books (rate-dependent CPR model)
- EVE outlier test: flags ΔEVE > 15% of Tier 1 (EBA Pillar 2 trigger)

---

### 4.5 Stress Testing Engine

Four modes, all saveable and comparable:

| Mode | Description |
|---|---|
| **EBA Baseline** | Pre-loaded EBA macro scenarios (latest vintage + historical) |
| **EBA Adverse / Severely Adverse** | EBA shock magnitudes, ready to run out of the box |
| **Custom** | User defines: GDP Δ, unemployment Δ, HPI Δ, credit spread Δ, rate curve shift |
| **Reverse** | Set a floor (e.g., CET1 ≥ 10.5%) — scipy solver finds minimum shock that breaches it |

#### 4.5.1 Macro-to-Financial Transmission Models

Transmission models convert macro shocks into financial impacts. All use **nonlinear** functions and the user can override every elasticity parameter.

**Credit risk transmission (Vasicek single-factor model):**

PD migration uses the asymptotic single-risk-factor (ASRF) model — the same framework underpinning the Basel IRB formula and used by EBA as its benchmark:

```
PD_stressed = Φ( (Φ⁻¹(PD_base) + √ρ × Φ⁻¹(macro_shock_percentile)) / √(1 − ρ) )

where:
  Φ     = standard normal CDF
  Φ⁻¹   = standard normal inverse CDF
  ρ     = asset correlation (per Basel: 12%–24% depending on PD, with SME adjustment)
  macro_shock_percentile = severity of the macro shock mapped to a quantile
                           (e.g., EBA adverse ≈ 1st percentile)
```

This produces the characteristic **nonlinear amplification** at tail severities: a 5% GDP shock produces more than 2× the credit losses of a 2.5% shock.

**Segment-specific mappings:**

| Macro variable | Financial impact | Transmission |
|---|---|---|
| GDP / unemployment | PD migration | Vasicek ASRF model; ρ per segment (corporate: 20%, mortgage: 15%, consumer: 10%, SME: 18%) |
| GDP / unemployment | LGD uplift | LGD_stressed = LGD_base × (1 + downturn_factor × severity). Downturn factor calibrated per segment. |
| Property prices | LGD on mortgage/CRE | LGD_stressed = min(LGD_base × (1 − HPI_shock / (1 − LTV)), 1.0) |
| Rate curve shift | NII/NIM | Via IRRBB repricing gap model (direct delegation to Section 4.4) |
| Credit spread | Fair value marks | Modified duration × spread change × FVOCI portfolio value |
| Credit spread | Wholesale funding cost | Spread change × outstanding wholesale funding |

**Elasticity calibration and transparency:**

All transmission model parameters (asset correlations, downturn factors, LGD multipliers) are:
1. Published in the tool's documentation with their source (Basel framework, EBA methodology papers, or academic reference)
2. Pre-loaded with default values but **user-overridable** in the scenario builder
3. Accompanied by **uncertainty bands**: the tool shows a central estimate and a ±1 SD range for stressed CET1 and NII, derived by varying each elasticity parameter within its historical confidence interval

#### 4.5.2 Scenario Consistency Check

When running combined credit + rate scenarios, the engine validates **macro-financial consistency**:

- If GDP shock is severe (e.g., −3%) but the rate curve is unchanged → warning: "Central bank typically cuts rates in recession; consider a rate-down path"
- If rates rise sharply but credit spreads are unchanged → warning: "Rate hikes typically widen credit spreads"
- If HPI is stable but unemployment rises sharply → warning: "Property prices and unemployment are historically correlated"

These are **warnings**, not blocks. The user can proceed with any combination, but inconsistencies are flagged. Consistency checks are based on the macro correlation matrix (see Section 4.5.3).

#### 4.5.3 Macro Correlation Matrix

A pre-loaded correlation matrix captures historical co-movement between macro variables (GDP, unemployment, rates, HPI, credit spreads). Estimated from Eurozone data 2000–present.

**Uses:**
- **Scenario consistency check** (Section 4.5.2): flag implausible combinations
- **Coherent custom scenario generation:** user specifies one anchor shock (e.g., GDP −3%), tool auto-suggests correlated shocks for other variables based on the correlation matrix. User can accept, modify, or override each suggestion.
- **Monte Carlo uncertainty bands:** joint sampling from the correlation structure to produce confidence intervals on stress results

The correlation matrix is a simple 6×6 matrix (GDP, unemployment, HICP, HPI, 3M rate, 10Y rate, credit spread) estimated via rolling 10-year window. Not a full VAR model — that is Phase 2 complexity.

#### 4.5.4 Reverse Stress Testing

**Specification (Phase 1):**

The reverse stress test finds the minimum macro shock that breaches a user-defined floor:

- **Search space:** Single-variable (e.g., find minimum GDP shock that pushes CET1 below 10.5%) or two-variable (GDP + rate simultaneously)
- **Objective function:** Minimise |shock_magnitude| subject to: metric(shock) ≤ floor
- **Solver:** `scipy.optimize.minimize_scalar` for single-variable; `scipy.optimize.minimize` (L-BFGS-B) for two-variable with bounds
- **Non-differentiability:** The transmission model is treated as a black box. The solver uses finite-difference gradient approximation (suitable because a single stress run takes <2 seconds)
- **Multiple local minima:** Run the solver from 3 starting points (mild, moderate, severe) and report the minimum across all runs
- **Output:** The exact shock magnitude at the breach point, plus a "headroom chart" showing the metric trajectory as the shock increases from 0 to breach level

---

### 4.6 Rating Engine

**Important disclaimer (shown in UI and all reports):**

> "Indicative credit scoring model based on quantitative financial metrics. This is NOT a simulation of actual Moody's or S&P rating actions. Actual ratings incorporate qualitative factors, management assessment, peer group context, and sovereign support considerations not captured here. Use for directional analysis only."

#### 4.6.1 Simplified Indicator (always visible on dashboard)

8 key ratios mapped to a **percentile-calibrated** notch grid. The grid thresholds are derived from the **EBA Transparency Exercise peer distribution** — not from US-centric absolute values:

| Factor | Mapping approach | Moody's anchor | S&P anchor |
|---|---|---|---|
| CET1 (fully loaded) | Peer percentile → notch | Capital adequacy | Capital & earnings |
| NPL ratio | Peer percentile → notch (inverse) | Asset quality | Risk position |
| CoR / credit loss rate | Peer percentile → notch (inverse) | Asset quality | Risk position |
| ROA / ROTE | Peer percentile → notch | Profitability | Capital & earnings |
| NIM | Peer percentile → notch | Profitability | Business position |
| CIR | Peer percentile → notch (inverse) | Efficiency | Business position |
| LCR | Peer percentile → notch | Liquidity | Funding & liquidity |
| Wholesale funding % | Peer percentile → notch (inverse) | Funding | Funding & liquidity |

**Percentile-based notch grid:**

Instead of hard-coded absolute thresholds, each factor's notch is determined by where the bank sits in the **EU peer distribution**:

```
Percentile ≥ 90th  → notch score 2 (Aa2/AA)
Percentile 75–90th → notch score 4 (Aa3/AA−)
Percentile 60–75th → notch score 6 (A2/A)
Percentile 40–60th → notch score 8 (Baa1/BBB+)
Percentile 25–40th → notch score 10 (Baa3/BBB−)
Percentile 10–25th → notch score 12 (Ba2/BB)
Percentile < 10th  → notch score 15 (B2/B)
```

The peer distribution is refreshed each time EBA data is ingested. This ensures EU-appropriate calibration — a NIM of 1.5% scores well in an EU context (where it is above median) rather than poorly (as it would on a US-centric grid).

**Factor weights:**

Default weights (user-overridable):

```
CET1: 0.20, NPL: 0.15, CoR: 0.15, ROA: 0.10, NIM: 0.10, CIR: 0.10, LCR: 0.10, Wholesale%: 0.10
```

These are heuristic weights informed by the relative emphasis in Moody's and S&P published methodologies. The tool clearly labels them as "default heuristic weights — not Moody's/S&P proprietary weights."

**Sovereign / systemic support adjustment:**

An additive notch adjustment for government support uplift:

| Bank category | Support uplift |
|---|---|
| G-SIB | +2 notches |
| D-SIB (O-SII with resolution expectation of bail-in) | +1 notch |
| Other | 0 notches |

The user selects the bank's systemic importance category. This is a simplified proxy for Moody's "Loss Given Failure" and S&P "External Support" assessment.

#### 4.6.2 Direction Calculation

```
Compare weighted score current period vs previous period:
  Improvement > 0.5 notch → "positive pressure" (↗)
  Deterioration > 0.5 notch → "negative pressure" (↘)
  Otherwise → "stable" (→)
```

#### 4.6.3 S&P BICRA Anchor

S&P's BICRA (Banking Industry Country Risk Assessment) is a **country-level input**, not computed from bank data. The tool pre-loads published BICRA scores per country:

| Country | Economic Risk | Industry Risk | BICRA group |
|---|---|---|---|
| DE | 1 | 2 | 2 |
| FR | 2 | 3 | 3 |
| IT | 4 | 4 | 4 |
| ES | 3 | 4 | 4 |
| NL | 1 | 2 | 2 |
| ... | ... | ... | ... |

(Full table for all 20 Eurozone countries, sourced from S&P's publicly available BICRA reports.)

BICRA group → Anchor rating (e.g., BICRA 2 → anchor "a", BICRA 4 → anchor "bbb+"). Individual factor adjustments then move the rating up or down from the anchor.

#### 4.6.4 Full Scorecard (on-demand, Phase 2)

*Moody's BCA framework:*
Macro Profile score → Financial Profile (Capital & Profitability · Asset Risk · Funding & Liquidity) → Qualitative adjustments → BCA → Adjusted BCA (affiliate support) → Final rating (sovereign / systemic support uplift)

*S&P BICRA framework:*
BICRA Anchor → Individual factor adjustments (Business position · Capital & earnings · Risk position · Funding & liquidity) → SACP → External support → ICR

Both scorecards show: current score · stressed score · peer percentile per factor.

---

### 4.7 Steering & Optimizer

**Portfolio Steering Scenarios (primary mode):**

User defines a named strategy:

| Input | Example |
|---|---|
| Segment reallocation | +€2bn mortgages, -€2bn corporate |
| Segment growth rates | Mortgages +8% YoY, consumer flat |
| Fixed/floating mix | Increase fixed-rate asset share 20% → 30% |
| NMD hedging overlay | Add €1bn 3Y receive-fixed IRS |
| Capital actions | €500m CET1 issuance Y2, DPS reduction |
| Dividend policy | Target payout ratio 40%, subject to MDA restrictions |
| Funding strategy | Reduce wholesale reliance 5pp, grow retail deposits |
| Recovery options | Dividend suspension, capital raise, asset sale, collateral optimisation |

Each change cascades automatically through NII, provisions (ECL), RWA, CET1, IRRBB profile, and rating scorecard.

**Recovery options library:**
- Capital and liquidity recovery actions with timing, constraints, and feasibility scoring
- Apply as overlays in stress runs and ICAAP/ILAAP drafts

**Risk Appetite Framework (RAF) Limits:**
- User-configurable limits (CET1 floor, NPL/NPE ceiling, CoR ceiling, NII-at-Risk limit, LCR/NSFR floors, leverage ratio floor)
- Traffic-light status (green/amber/red) on Dashboard and scenario comparison
- Breach alerts with driver decomposition and suggested levers

**Optimizer — Efficient Frontier Mode (optional):**
- Objective: Maximise ROE *or* CET1 *or* rating notch
- Constraints: CET1 floor, NPL ceiling, NII-at-Risk limit, minimum rating
- Levers: segment allocations, fixed/float mix, funding mix
- Engine: `scipy.optimize` sweeping feasible space
- Output: Pareto-optimal frontier chart + table of strategies. Bank picks their preferred point — tool does not prescribe.

**NII Target Optimizer ("nuclear option")**:
- Goal-seeking mode: user sets required NII growth (e.g., +10% YoY) or absolute NII target
- Solver finds minimum-disruption set of levers (pricing, mix, funding, hedging) to achieve target
- Constraints: CET1 floor, LCR/NSFR floors, RAF limits, maximum change per lever
- Output: recommended lever changes + feasibility flag + trade-off summary

---

### 4.8 Historical Hedge Counterfactual & Optimisation

Answers the question: *"What would have happened in 2024 if we had put on more hedge in 2023?"*

**Data source:** ECB SDMX historical rate curves (DFR, MRO, €STR, EURIBOR 1M/3M/6M/12M, EUR swap 2Y/5Y/10Y/20Y), fetched once and cached locally. FRED as fallback. User triggers refresh on demand. **A pre-cached CSV snapshot of key rate series is bundled with the application** for immediate usability.

**Counterfactual Engine (primary mode):**

User defines a hypothetical hedge programme — instruments they could have entered in 2023:

| Input | Example |
|---|---|
| Instrument type | Receive-fixed IRS, pay-fixed IRS |
| Notional | €1bn |
| Tenor | 3Y |
| Fixed rate | 3.50% |
| Entry date | Q1 2023 |

**Phase 1 instrument scope:** Vanilla IRS only (receive-fixed and pay-fixed). Caps, floors, and cross-currency swaps are deferred to Phase 2 — they require an implied volatility surface that is not available from public data sources.

Multiple instruments can be stacked to model a full hedge programme. The engine feeds the actual historical ECB rate path through the existing repricing gap and NMD models — same engine as forward-looking IRRBB, run backwards on real data.

**IRS valuation:**
- Day count: ACT/360 for floating leg (EURIBOR), 30/360 for fixed leg
- Discounting: **OIS curve** (€STR-based) for NPV, consistent with post-financial-crisis market convention
- Fixed leg cash flow: notional × fixed_rate × day_count_fraction
- Floating leg cash flow: notional × EURIBOR_fixing × day_count_fraction (using actual historical fixings)

For each quarter end in the historical window, the engine computes NII and EVE with and without the hypothetical hedge, outputting: ΔNIIi per quarter, ΔEVE per quarter, cumulative NII benefit, cumulative EVE benefit.

**Known limitation:** The counterfactual uses the plan's **current** repricing gap profile, not the bank's actual historical repricing gap (which is not available from public data). This means the counterfactual answers "what would happen to TODAY's balance sheet if these historical rates occurred" — not a true historical replay. This limitation is documented in the UI.

**Historical Attribution (backward-looking):**
- NII and CET1 historical bridges using disclosed P&L and balance sheet data (where available)
- Replay any historical rate path against current or disclosed balance sheet to isolate rate vs pass-through effects
- Management action replay: dividend cuts, capital raises, funding mix shifts, and hedge overlays to quantify counterfactual headroom

**Hedge Optimisation Backtest (efficient frontier mode):**

Instead of the user specifying the hedge, the optimiser finds the Pareto-optimal set of hedge portfolios across three objectives:

- Maximise cumulative 2024 NII
- Minimise NII-at-Risk (worst quarterly NII outcome in 2024)
- Maximise EVE stability (minimise quarter-on-quarter EVE variance)

Levers: notional of receive-fixed IRS by tenor (1Y, 2Y, 3Y, 5Y), entry timing (Q1/Q2/Q3 2023). Constraints: maximum total notional, no naked shorts, maximum hedge cost. Engine: `scipy.optimize` sweeping feasible space. Output: Pareto-optimal frontier scatter plot — user picks a point and sees the exact hedge portfolio and full quarterly NII/EVE outcome it would have produced.

---

### 4.9 Macro Assumption Calibrator

Challenges forward-looking planning assumptions against historical macro-financial relationships, at both EU and country level.

**Data sources:**

*ECB SDMX — Policy & Money Market Rates (EU-wide):*

| Series | Use |
|---|---|
| DFR (Deposit Facility Rate) | NMD deposit beta calibration, NII floor |
| MRO (Main Refinancing Operations) | Lending rate benchmark, historical pass-through |
| €STR | Overnight benchmark, OIS discounting |
| EURIBOR 1M / 3M / 6M / 12M | Floating rate asset repricing, basis risk |
| EUR swap curve 2Y / 5Y / 10Y / 20Y | Hedge pricing, EVE discounting |

*ECB SDMX — Country Risk-Free Rates:*

10Y government bond yields for all 20 Eurozone member states. Used for sovereign spread over swap, securities portfolio mark-to-market under rate shocks, and country-specific wholesale funding cost benchmarking.

*Eurostat — Country-Specific (Micro):*

| Series | Granularity |
|---|---|
| GDP growth | Quarterly, per country |
| Unemployment rate | Monthly, per country |
| HICP inflation | Monthly, per country |
| Household saving rate | Quarterly, per country |
| House Price Index | Quarterly, per country |
| Private sector credit growth | Quarterly, per country |

*Eurostat — EU Aggregate (Macro):*

Same series at Eurozone aggregate level. Used as the EU baseline for elasticity regressions; country-specific deviation from EU trend is computed as a second factor.

**Data fetching resilience:**

- ECB SDMX API has aggressive rate limiting (sometimes 1 req/s) and response times of 10+ seconds per series
- **Retry logic:** Exponential backoff with 3 retries per request, circuit breaker after 5 consecutive failures
- **Bulk download preference:** Where available, use ECB bulk download files instead of per-series SDMX queries
- **Bundled default dataset:** Application ships with a pre-cached snapshot of all series (updated with each release). First-run experience does not require any API calls.
- **Progress indicator:** Initial data refresh shows progress bar with series count and estimated time remaining

**Historical relationship engine:**

For each key planning assumption, a two-layer regression is fitted over the available historical window (2015–present, COVID outlier years optionally excluded):

1. EU-level relationship: EU GDP → EU metric (e.g., deposit growth, loan growth by segment, CoR)
2. Country adjustment: historical deviation of the bank's home country from EU trend

**Statistical methodology:**
- All series transformed to **growth rates or first differences** (stationary) before regression
- **Newey-West standard errors** (HAC-consistent) to handle serial correlation in macro time series, with automatic lag selection
- R² is reported alongside **adjusted R²** and the Newey-West confidence interval for the elasticity coefficient
- User can adjust the estimation window (e.g., 2018–present to exclude NIRP era)
- Optional **post-2022 regime dummy** variable to account for the structural break in the rate environment
- Minimum observation count: regression requires ≥ 20 observations or a warning is displayed

Implied elasticities computed:
- GDP (country + EU) → retail deposit growth
- GDP → loan growth by segment (corporate, mortgage, consumer, SME)
- Unemployment → CoR / credit losses
- GDP + unemployment → NPL migration
- HICP + DFR → NIM (deposit repricing pass-through)

**Assumption audit panel (Business Plan Builder — collapsible):**

Every user-entered growth/volume assumption is checked against its macro-implied value given the active scenario's macro path. Each row shows:

```
Assumption               Your input    EU-implied    Country-adj.    ±1 SD range    Status
─────────────────────────────────────────────────────────────────────────────────────────
Retail deposit growth    +4.0%         +0.8%         +1.1%           −0.2 to +2.4   🔴 High
Corporate loan growth    +3.0%         +2.5%         +2.7%           +1.8 to +3.6   🟢 OK
Mortgage growth          +6.0%         +4.2%         +4.5%           +3.0 to +6.0   🟡 Elevated
Cost of Risk             45 bps        52 bps        49 bps          38 to 60 bps   🟡 Optimistic
```

Thresholds: within 1 SD of historical = green, 1–2 SD = amber, >2 SD = red. Clicking any row shows the underlying scatter plot with regression line, confidence band, and current assumption marked.

When the active scenario changes (e.g., switching to EBA adverse), the panel re-runs automatically against the stressed macro path — the challenge is always relative to the scenario in view.

---

### 4.10 Reporting Engine

| Output | Technology | Contents |
|---|---|---|
| **Interactive dashboard** | Streamlit (PoC) → React | Live KPIs, charts, scenario comparison |
| **PDF report** | reportlab (PoC, Windows-compatible) / WeasyPrint (Full) | Executive summary, plan, stress results, rating scorecard, peers |
| **Excel workbook** | openpyxl | Full model output, assumptions, scenario comparison tabs |
| **ICAAP/ILAAP draft pack** | reportlab / WeasyPrint | Quantitative annexes + auto-drafted narrative from 3-year business plan |

**PDF technology note:** WeasyPrint requires GTK/Cairo native libraries that are difficult to install on Windows. For the Lite (Windows laptop) deployment, PDF generation uses `reportlab` as the default engine. The Full (Docker) deployment uses WeasyPrint for higher-fidelity HTML-to-PDF rendering. The report content and structure are identical regardless of engine.

---

### 4.11 ICAAP / ILAAP & Supervisory Pack

**Purpose:** Produce ICAAP/ILAAP-ready quantitative annexes and an auto-drafted narrative from the 3-year business plan, base and adverse scenarios, and reverse stress outputs.

**ICAAP scope:**
- Internal capital adequacy vs regulatory minima (P1, P2R, buffers, P2G headroom)
- Management buffers (target CET1 and internal limits) with rationale and governance sign-off
- Capital plan under base/adverse, including bridge and RWA drivers
- Reverse stress test for capital breach (CET1 floor) with feasibility of management actions
- Recovery options for capital (dividend suspension, capital raises, AT1/T2 issuance, RWA mitigation)

**ILAAP scope:**
- Liquidity adequacy beyond LCR/NSFR: survival horizon, name-specific outflows, funding concentration
- Internal liquidity buffer definition and usage rules
- Stress liquidity scenarios linked to macro + market spread shocks
- Reverse stress test for liquidity survival horizon breach
- Recovery options for liquidity (asset sales, collateral optimisation, central bank facilities)

**Drafting capability:**
- Auto-populates quantitative annexes from model outputs (bridges, RAF limits, stress results)
- Generates narrative sections (assumptions, governance, limitations, management actions) with editable templates
- Supports versioning, approval workflow, and audit trail

**ICAAP/ILAAP template (ECB/SSM-aligned outline):**
- Executive summary and management statement
- Governance, risk appetite, and decision-use in planning
- Scope, perimeter, and key methodologies (incl. model limitations)
- Capital adequacy assessment (base and adverse)
- RWA and capital bridge analysis
- Stress testing framework and reverse stress tests
- Management actions and feasibility assessment
- Liquidity adequacy assessment (base and adverse)
- Survival horizon, funding concentration, and contingency funding plan
- Internal buffers and limit monitoring (RAF)
- Recovery plan alignment and early warning indicators
- Quantitative annexes (tables, charts, sensitivities, scenario results)

## 5. Data Model

### 5.1 Core Entities

```
Bank
├── id, name, country, approach (SA|IRB), tier, peer_group
├── systemic_importance (GSIB|DSIB|OTHER)  — for rating support uplift
├── bicra_group  — S&P BICRA country group (pre-loaded lookup)

Plan  (one per bank per planning cycle)
├── id, bank_id, name, horizon_years
├── created_at, updated_at, version, created_by
├── PortfolioAllocation[]     (segment × period × volume, mix, margin assumptions)
├── FundingStrategy[]         (liability mix × period)
├── FTPAssumptions[]           (internal pricing curves by segment × tenor)
├── CapitalAction[]           (issuances, buybacks, DPS, payout_ratio per period)
├── DividendPolicy            (target_payout_ratio, mda_restriction_enabled)
├── RateEnvironment           (yield curve + forward path, base/up/down)
├── RepricingGap[]            (asset and liability buckets)
├── NMDProfile[]              (per product: beta, decay rate, core/non-core split, volume_migration_rate)
├── HedgingInstrument[]       (type, notional, tenor, fixed rate, day_count_convention)
├── CET1Deductions            (goodwill, intangibles, dta_threshold, significant_investments, ava)
├── IFRS9TransitionalRelief   (elected: bool, phase_out_schedule)
├── RecoveryOption[]          (capital or liquidity recovery actions with timing and impact)

ProjectedFinancials           (output of calculation engine, per plan × period)
├── id, plan_id, scenario_id (nullable), period, is_stressed
├── Key metrics as columns (for efficient querying):
│   cet1_ratio, npl_ratio, nii, roe, nim, lcr, nsfr
├── P&L detail (JSON with Pydantic validation)
├── Balance sheet detail (JSON with Pydantic validation)
├── Capital bridge detail (JSON with Pydantic validation)
├── Asset quality detail (JSON with Pydantic validation)
├── IRRBB metrics (JSON with Pydantic validation)
├── Profitability metrics (JSON with Pydantic validation)
├── Liquidity detail (JSON with Pydantic validation)
├── ECL detail (JSON: stage balances, provisions by stage, migration flows)
├── convergence_iterations: int  — how many iterations the convergence loop took
├── warnings: list[str]  — any warnings from the projection
├── bridges (JSON): cet1_bridge, nii_bridge, roe_bridge, rwa_bridge
├── market_metrics (JSON): eps, dps, payout_ratio, dividend_yield, buyback_yield, rote, tbvps, pe, ptbv, tsr
├── segment_raroc (JSON): by segment, per period
├── liquidity_survival (JSON): survival_horizon_days, stress_type, buffer_usage
├── vbm_metrics (JSON): economic_profit, implied_coe, value_contribution_by_segment

Scenario
├── id, name, type (EBA_BASELINE|EBA_ADVERSE|EBA_SEVERELY_ADVERSE|CUSTOM|REVERSE)
├── MacroAssumptions          (GDP Δ, unemployment Δ, HPI Δ, spread Δ, rate path)
├── TransmissionOverrides     (user-overridden elasticities, if any)
├── FundingCurveAssumptions   (base curves, spreads, stress beta/lag shifts)

StressRun
├── plan_id × scenario_id → ProjectedFinancials (stressed)
├── uncertainty_bands (JSON: p10/p50/p90 for key metrics)

RatingScore
├── plan_id, scenario_id (null = base), methodology (MOODYS|SP)
├── Simplified: 8 factor scores + composite notch + direction + support_uplift
├── Full scorecard: all sub-factors, anchor, adjustments, final rating (Phase 2)
├── disclaimer_acknowledged: bool

MarketData
├── bank_id, ticker, source (YFINANCE), currency, exchange
├── date, close_price, shares_outstanding, dividend_per_share

EquityMetrics
├── plan_id, period, scenario_id (nullable)
├── eps, dps, payout_ratio, dividend_yield, buyback_yield
├── rote, tbvps, pe, ptbv, implied_coe, tsr

SegmentRAROC
├── plan_id, period, scenario_id (nullable)
├── segment, net_income_after_ecl, economic_capital, raroc

FTPAssumptions
├── plan_id, segment, tenor_bucket
├── ftp_rate, liquidity_premium, term_adjustment

RecoveryOption
├── plan_id, type (CAPITAL|LIQUIDITY), name, timing
├── impact (JSON): cet1_delta, rwt_delta, liquidity_buffer_delta, survival_days_delta
├── feasibility_score, constraints, notes

PeerData
├── bank_id, source (EBA_TRANSPARENCY|P3DH), period
├── Key metrics as columns (for efficient peer queries):
│   cet1_ratio, npl_ratio, cor, roa, nim, cir, lcr, wholesale_pct
├── Full financials (JSON with Pydantic validation)

OptimizationRun
├── plan_id, objective, constraints[], levers[]
├── EfficientFrontier[]       (set of Pareto-optimal strategies)

HistoricalRateCurve
├── date, series, tenor, rate, country (null for EU-wide), source

HistoricalMacroSeries
├── date, country (null = Eurozone aggregate), series, value, source

MacroElasticity
├── series_pair, country (null = EU baseline)
├── coefficient, std_error, r_squared, adj_r_squared, n_obs
├── confidence_interval_lower, confidence_interval_upper
├── window_start, window_end, covid_excluded: bool, regime_dummy: bool

HedgeCounterfactualRun
├── plan_id, instruments (JSON), window_start, window_end
├── quarterly_results (JSON): per quarter NII/EVE actual vs counterfactual
├── known_limitation_note: "Uses current repricing gap, not historical"

HedgeOptimisationRun
├── plan_id, constraints{max_notional, max_cost}, historical_window
├── EfficientFrontier[]: {notionals_by_tenor{}, entry_timing, nii_cumulative, nii_at_risk, eve_variance}
```

### 5.2 Audit Trail

```
AuditLog
├── id, timestamp, entity_type, entity_id
├── action (CREATE|UPDATE|DELETE)
├── field_changed, old_value, new_value
├── session_id
```

Every Plan modification is logged with before/after state. This supports regulatory traceability (ECB/SSM ICAAP reviews expect assumption change history).

### 5.3 Report Tracking

```
ReportRun
├── id, plan_id, scenarios[] (list of scenario IDs included)
├── format (PDF|EXCEL), sections_included[]
├── generated_at, file_path
├── session_id

IcaapIlaapDraft
├── id, plan_id, horizon_years (3), base_scenario_id, adverse_scenario_id
├── internal_capital_buffer, internal_liquidity_buffer
├── survival_horizon_days, liquidity_reverse_stress_result
├── capital_reverse_stress_result, management_actions_summary
├── narrative_sections (JSON), quantitative_annexes (JSON)
├── version, status (DRAFT|APPROVED), generated_at, file_path
```

### 5.4 Data Validation

All JSON fields are validated by **Pydantic models** before database persistence:
- Each JSON blob has a corresponding Pydantic schema defining required fields, types, and value ranges
- Invalid data raises a validation error with a clear message — never silently stored
- Schema versioning: each JSON blob includes a `_schema_version` field to support migration when new metrics are added

### 5.5 Enums

```
Segment: CORPORATE, MORTGAGE, CONSUMER, SME, PUBLIC_SECTOR
Approach: SA, IRB
ScenarioType: EBA_BASELINE, EBA_ADVERSE, EBA_SEVERELY_ADVERSE, CUSTOM, REVERSE
Methodology: MOODYS, SP
InstrumentType: RECEIVE_FIXED_IRS, PAY_FIXED_IRS  (Phase 1)
               + CAP, FLOOR, CROSS_CURRENCY_SWAP   (Phase 2)
RateSeries: DFR, MRO, ESTER, EURIBOR_1M, EURIBOR_3M, EURIBOR_6M, EURIBOR_12M,
            SWAP_2Y, SWAP_5Y, SWAP_10Y, SWAP_20Y, GOV_10Y
MacroSeries: GDP, UNEMPLOYMENT, HICP, SAVING_RATE, HPI, CREDIT_GROWTH
PeerSource: EBA_TRANSPARENCY, P3DH
SystemicImportance: GSIB, DSIB, OTHER
```

### 5.6 Database Resilience

- **SQLite WAL mode** enabled for concurrent reads during Streamlit re-runs
- **Automatic backup:** On application startup and before each data refresh, the SQLite file is copied to `data/backups/bbirr_YYYYMMDD_HHMMSS.db`. Backups older than 30 days are auto-pruned.
- **Migration:** Alembic manages schema evolution. All JSON blobs include `_schema_version` for forward-compatible changes.

---

## 6. UI Layout (6 Views)

### 6.1 Dashboard
KPI strip: CET1 · NPL · NIM · ROE · LCR · indicative rating notch + direction arrow
Charts: P&L trajectory, capital trajectory, NII-at-Risk across 6 IRRBB shocks, peer percentile positioning
Sensitivity tables (Section 4.3.11): key metric sensitivities displayed in a collapsible panel
RAF limits panel: traffic-light status for key limits with breach drivers

### 6.2 Business Plan Builder
Left: assumption inputs (portfolio mix sliders, growth rates, margin targets, capital actions, dividend policy, funding strategy, rate environment, hedging instruments)
Right: live preview of P&L, balance sheet, capital reacting to inputs
Bottom (collapsible): **Assumption Audit Panel** — all forward assumptions vs macro-implied values (EU and country-adjusted), with ±1 SD confidence bands, colour-coded green/amber/red, updates automatically when active scenario changes

**Recalculation strategy:** To avoid sluggish UI on rapid slider changes, recalculation is **debounced** — the engine waits 500ms after the last input change before triggering a re-run. IRRBB metrics (6 shocks × 2 horizons × pre/post hedge) and rating score are computed on a separate "Refresh IRRBB & Rating" button rather than on every slider change, to keep the main cascade responsive. A "Recalculating..." spinner is shown during computation.

**Undo/redo:** Plan state is auto-saved to session history on every recalculation. The user can undo the last N changes (default N=20) via an Undo button. Plan version history is also persisted to the database (Section 5.2) for cross-session audit trail.

**Bridges panel:** CET1 bridge, NII bridge, ROE bridge, RWA bridge (quarterly + cumulative), with drill-down to driver components

**FTP curve panel:** editable internal pricing curves by segment and tenor, with base rate + liquidity premium components

**Recovery options editor:** create/edit capital and liquidity actions (timing, impact, constraints) for stress overlays and ICAAP/ILAAP drafts

### 6.3 Stress Testing
Scenario selector (EBA presets or custom builder) · macro shock inputs · transmission parameter overrides (expandable) · side-by-side scenario comparison · reverse stress test mode · recovery options overlay · combined credit + rate shocks with consistency check warnings · **uncertainty bands** (±1 SD) on key stressed metrics
Funding curve stress view: curve shifts by liability class with pass-through changes highlighted

### 6.4 Rating Scorecard
Toggle Moody's / S&P / Both · **indicative disclaimer always visible** · simplified indicator always visible · full scorecard expandable by section (Phase 2) · base vs stressed comparison · peer factor positioning · sovereign support adjustment visible · **user-overridable factor weights**

### 6.5 Reports & Export
Generate PDF · download Excel · configure report sections
All reports include the rating disclaimer and any model warnings/limitations

### 6.6 Historical Analysis
Two tabs:
- **Counterfactual:** hedge input form (instrument type: IRS only in Phase 1, notional, tenor, fixed rate, entry date, stackable) + quarterly NII/EVE charts actual vs hypothetical + cumulative benefit summary + **known limitation banner** ("Uses current repricing gap, not historical balance sheet")
- **Optimal Hedge:** efficient frontier scatter across three objectives (max NII / min NII-at-Risk / max EVE stability) + selected portfolio detail + full quarterly NII/EVE outcome
- **Historical Bridges:** NII bridge, CET1 bridge, and RWA bridge over historical periods (where data available), with replay overlays

### 6.7 Authentication (Basic)

Even in PoC, the tool may process bank-sensitive analysis. Basic authentication is required:
- **Lite deployment:** Simple username/password stored in hashed form in a local config file. Single-user by default; multi-user optional.
- **Full deployment:** Integration with bank's SSO/LDAP (Phase 2). Basic auth as interim.
- Session tracking for audit trail (which session made which changes).

---

## 7. Tech Stack

| Layer | PoC | Production |
|---|---|---|
| Frontend | Streamlit | React + TypeScript + Recharts/D3 |
| API | Streamlit native / FastAPI | FastAPI |
| Calculation engine | Python (pandas, numpy, scipy) | Same |
| Database | SQLite (WAL mode) | PostgreSQL |
| Async tasks | Sync (inline) | Celery + Redis |
| PDF | reportlab (Windows-compatible) | WeasyPrint (Docker) |
| Excel | openpyxl | openpyxl |
| Charts (static export) | plotly + kaleido | Same |
| Deployment | pip + uvicorn | Docker Compose |
| Historical rates | ECB SDMX API (pandasdmx) + FRED fallback + bundled CSV | Same |
| Macro data | Eurostat API + bundled CSV | Same |
| Validation | Pydantic v2 | Same |
| Auth | streamlit-authenticator | FastAPI OAuth2 / SSO |

---

## 8. Key Design Principles

- **Engine-first:** The calculation engine is a pure Python library. UI is a shell. Swap Streamlit for React without touching the model.
- **Cascade by default:** Any change to strategy assumptions propagates through all downstream metrics and the rating scorecard, resolved via iterative convergence loop.
- **Auditability:** Every metric is traceable to its input assumptions. No black boxes. Full audit trail on all plan changes. All model limitations and simplifications documented in output.
- **Regulatory accuracy:** EBA IRRBB standardized shocks (EBA/GL/2022/14), CRR3 Basel IV output floor with correct SA methodology, IFRS 9 ECL model with three-scenario probability weighting, EBA stress test transmission via Vasicek ASRF — all implemented to spec with documented simplifications where applicable.
- **Bank-grade data sovereignty:** Self-hosted, no external data calls at runtime. Public data (EBA, P3DH) ingested once and stored locally. Automatic database backups.
- **Honest about limitations:** Every simplification is documented. Rating model carries a disclaimer. Liquidity ratios labelled as indicative. Confidence intervals shown alongside point estimates.
- **Resilient data pipeline:** Bundled default datasets, exponential backoff on API calls, circuit breakers, progress indicators. The tool works offline after initial data load.

---

## 9. Build Phases

**Phase 1 — PoC (current)**
- Data ingestion: EBA Transparency Exercise + P3DH parsers + bundled default dataset
- Calculation engine: full financial model with iterative convergence, IFRS 9 ECL, CET1 bridge with prudential deductions, Basel IV output floor (CRR3 SA), SMA operational risk, MDA/dividend restrictions, sensitivity tables
- IRRBB module: repricing gap, NMD model (with volume elasticity, WAM cap, non-core floor), IRS hedging overlay (OIS-discounted), EVE via risk-free curve, basis risk quantification, 6 EBA scenarios
- Stress engine: Vasicek ASRF transmission model, EBA scenarios + custom + reverse stress, scenario consistency checks, macro correlation matrix, uncertainty bands
- Rating engine: percentile-calibrated simplified indicator with EU-appropriate thresholds, sovereign support adjustment, user-overridable weights, rating disclaimer
- Historical data fetch & cache: ECB SDMX + Eurostat with retry/circuit breaker + bundled CSV fallback, all 20 Eurozone countries
- Historical hedge counterfactual engine (IRS only) + View 6 Counterfactual tab + documented limitation on static balance sheet
- Macro assumption calibrator: elasticity engine with Newey-West standard errors, configurable window, regime dummy, confidence intervals + Assumption Audit Panel
- UI: Streamlit — all 6 views + basic auth + debounced recalculation + undo/redo
- Output: PDF (reportlab) + Excel export
- Data model: normalised key metrics, Pydantic validation on all JSON, audit trail, automatic backups
- Error handling: documented strategy for negative equity, NaN propagation, convergence failures, division-by-zero

**Phase 2 — Production**
- Own-bank Excel template upload (key BS, P&L, repricing gap)
- Full Moody's BCA + S&P BICRA scorecard implementation
- Optimizer (efficient frontier — forward-looking)
- Hedge optimisation backtest (efficient frontier — historical)
- Caps, floors, cross-currency swaps (requires implied vol surface)
- Multi-currency balance sheet and FX stress
- Full CRR-compliant LCR/NSFR (with own-bank counterparty-level data)
- VAR model for joint macro scenario generation (replacing correlation matrix)
- Climate / ESG stress scenarios
- React frontend migration
- PostgreSQL + Celery + Docker Compose
- SSO/LDAP authentication
- Excel ingestion modules (FINREP/COREP + management accounts)
- FINREP/COREP auto-mapping

---

## 10. Testing Strategy

**Known-answer tests:** Every calculation module has tests with exact expected outputs, not just directional checks. Example: "Given CET1 capital = €10bn, RWA = €70bn, the CET1 ratio must be exactly 14.29%."

**Regression tests:** A reference bank (based on EBA data) with known inputs produces a full 20-quarter projection. Any code change that alters outputs triggers a diff review.

**Edge case tests:**
- Negative equity (bank failure scenario)
- CET1 < 0 under stress
- Zero loan book (all metrics degenerate gracefully)
- Missing EBA data fields (NaN handling)
- NMD volume = 0 (no division-by-zero)
- Convergence loop hitting max iterations
- ECB API timeout / unavailable (fallback to cache)

**Integration tests:** End-to-end: ingest EBA data → create plan → run projection → run stress → compute rating → generate report. Verify the chain produces consistent, non-NaN output.

**Performance tests:** Full 20-quarter projection must complete in < 2 seconds on a modern laptop. IRRBB full suite (6 shocks × 2 horizons × pre/post hedge) must complete in < 5 seconds.
