# BBIRR Calculation Engine — Full Enrichment Design v2

**Date:** 2026-02-23
**Status:** Approved
**Supersedes:** `2026-02-23-engine-enrichment-design.md`
**Scope:** Engine + structured output dicts; all new items produce rich JSON blobs in `ProjectedFinancials`. New benchmarking module produces base-year peer comparison.

---

## 1. Other Comprehensive Income (OCI) + Equity Bridge

### OCI components (flow through equity, not P&L)

```
PAT
  + Bond portfolio revaluation (FVOCI mark-to-market, quarterly Δ)
  + Cash flow hedge reserve change (pay-fixed swap repricing)
  + Pension actuarial gains/losses (quarterly estimate)
  + FX translation reserve (foreign subsidiaries)
= Other Comprehensive Income (OCI)
= Total Comprehensive Income (TCI) = PAT + OCI
```

### Full equity reconciliation bridge (must close to zero residual)

```
Opening equity (prior quarter closing)
  + Total Comprehensive Income (TCI)
  − AT1 coupon payments  (charged to equity, NOT P&L)
  − Cash dividends
  − Share buybacks
  − Extraordinary payout
  +/− Capital actions (new issuance, AT1 call, T2 call)
  + DTC/DTA amortization CET1 add-on  (Greek-specific, see §3)
  +/− Other  (residual; should tend to zero)
= Closing equity
```

**Check field:** `closing_equity − (opening + TCI − AT1_coupon − payouts ± actions + dtc_addon + other)` — must be < 0.01 EUR mn.

### New dataclass: `OCIState`

```python
@dataclass
class OCIState:
    period: date
    bond_revaluation: float = 0.0         # FVOCI portfolio MTM change
    hedge_reserve_change: float = 0.0     # CFH reserve movement
    pension_actuarial: float = 0.0        # DB pension actuarial
    fx_translation: float = 0.0
    total_oci: float = 0.0
    total_comprehensive_income: float = 0.0  # PAT + OCI

@dataclass
class EquityBridge:
    period: date
    opening_equity: float = 0.0
    tci: float = 0.0                      # PAT + OCI
    at1_coupons: float = 0.0             # negative (charge to equity)
    cash_dividends: float = 0.0          # negative
    buybacks: float = 0.0               # negative
    extraordinary_payout: float = 0.0   # negative
    capital_actions: float = 0.0        # signed
    dtc_cet1_addon: float = 0.0         # positive (see §3)
    other: float = 0.0
    closing_equity: float = 0.0
    check: float = 0.0                  # must be ≈ 0
```

---

## 2. AT1 Coupon Payments

AT1 instruments pay discretionary coupons that:
- Are **charged directly to equity** (not P&L under IAS 32)
- Reduce MDA distributable items
- Must appear explicitly in the equity waterfall

```
AT1_coupon_q = AT1_capital × AT1_coupon_rate / 4
```

- `AT1_coupon_rate`: user-configurable (default 6.0% p.a. — typical EU AT1 coupon)
- Added to `CapitalState` and flows into `EquityBridge`

---

## 3. DTA / DTC — Greek Regulatory Framework

### Asset classification

| Asset type | CET1 treatment | Risk weight | Notes |
|---|---|---|---|
| DTA regular (timing diffs) | Deducted from CET1 above 10% CET1 threshold | 0% (deducted) / 250% (below threshold) | Universal |
| DTC (Deferred Tax Credit, Law 4172/2013) | **Not deducted** | **100%** | Greek-specific; government-guaranteed |

### Two amortization pathways

**A. Statutory DTA Law amortization (fixed schedule to 2052)**

Default: straight-line over remaining years to 2052.
```
years_remaining = 2052 − current_year
annual_statutory = DTC_stock_opening / years_remaining
quarterly_statutory = annual_statutory / 4
```

Override: user can supply a list of annual EUR mn amounts (`dtc_statutory_schedule: list[float]` in Plan assumptions), one per year from base year to 2052. If supplied, engine uses the schedule; otherwise uses straight-line.

**B. Distribution-linked amortization (SSM agreement)**

```
quarterly_distribution_linked = 0.29 × (cash_div_q + buyback_q + extraordinary_q)
```

The 29% factor (or `dtc_distribution_factor`, default 0.29) is user-configurable to allow for future SSM renegotiation.

**Total quarterly DTC amortization:**
```
dtc_amortization_q = quarterly_statutory + quarterly_distribution_linked
```

**CET1 impact (per SSM-agreed regulatory treatment):**
```
dtc_cet1_addon_q = dtc_amortization_q
  (added to CET1 numerator; RWA in regulatory return stays unchanged
   — benefit recognised as CET1 add-on, not RWA reduction in B/S)
```

**Balance sheet:**
```
DTC_stock_closing = DTC_stock_opening − dtc_amortization_q
DTA_total_BS_closing = DTA_regular + DTC_stock_closing
```

### New dataclass: `DTAState`

```python
@dataclass
class DTAState:
    period: date
    # Regular DTA
    dta_regular: float = 0.0
    dta_threshold_10pct_cet1: float = 0.0    # 10% of CET1 (threshold)
    dta_deducted_from_cet1: float = 0.0      # portion above threshold (deducted)
    dta_rw_250pct: float = 0.0               # portion below threshold (250% RW)
    # DTC (Law 4172 — Greek banks only; zero for all others)
    dtc_stock_opening: float = 0.0
    dtc_statutory_amortization_q: float = 0.0
    dtc_distribution_linked_q: float = 0.0
    dtc_total_amortization_q: float = 0.0
    dtc_stock_closing: float = 0.0
    dtc_cet1_addon: float = 0.0             # CET1 numerator add-on
    dtc_distribution_factor: float = 0.29  # SSM-agreed factor
    # Totals
    dta_dtc_total_bs: float = 0.0           # total DTA+DTC on asset side
    dta_rwa_contribution: float = 0.0       # DTC×100% + DTA_below_thresh×250%
```

### Plan assumption fields for DTA/DTC

```python
# In Plan.portfolio_allocations:
{
    "dta_regular_opening":     float,     # EUR mn (from base year)
    "dtc_stock_opening":       float,     # EUR mn (from base year)
    "dtc_statutory_schedule":  list[float] | None,  # annual EUR mn, None = straight-line
    "dtc_distribution_factor": float,     # default 0.29
    "at1_coupon_rate":         float,     # default 0.060
}
```

---

## 4. Loan Book Gross Bridge

Included in `balance_sheet_detail` blob each quarter:

```python
"loan_book_bridge": {
    "opening_gross":    float,   # prior quarter gross loans
    "originations":     float,   # = loan_growth_q × opening (or user override)
    "repayments":       float,   # = repayment_rate × opening (default 15% p.a.)
    "write_offs":       float,   # from AssetQualityState.written_off
    "fx_other":         float,   # placeholder
    "closing_gross":    float,   # current quarter gross loans
    "check":            float,   # closing − (opening + originations − repayments − write_offs + fx)
}
```

New plan assumption: `loan_repayment_rate_annual: float = 0.15` (15% annual scheduled repayment rate on gross book).

---

## 5. RoTE + Tangible Book Value

```
Tangible equity = Total equity − Goodwill − Other intangibles
RoTE = (Net profit × 4) / Average tangible equity
Tangible BVPS = Tangible equity / Shares outstanding
```

Additional fields in `CapitalState`:
```python
goodwill: float = 0.0
other_intangibles: float = 0.0
tangible_equity: float = 0.0
rote: float = 0.0
tangible_bvps: float = 0.0
```

Plan assumptions: `goodwill: float = 0.0`, `intangibles_annual_amortization: float = 0.0`.

---

## 6. Additional Key Ratios (all hot-path scalars on ProjectedFinancials)

These are computed in the engine and stored as **scalar columns** (not just in JSON blobs) so they can be queried directly.

| Scalar column | Formula | Purpose |
|---|---|---|
| `ldr` | Net loans / Total deposits | Funding risk |
| `nir` | (Fee + Trading) / TOI | Revenue diversification |
| `texas_ratio` | NPL gross / (Tangible equity + ECL reserves) | Systemic stress signal |
| `breakeven_cor_bps` | PPP / Avg loans × 10,000 | Risk absorption capacity |
| `capital_gen_rate_bps` | (PAT − dividends − buybacks) / RWA × 10,000 × 4 | Organic CET1 build p.a. |
| `non_interest_income_pct` | (Fee + Trading + Other) / NII | Revenue mix |
| `stage2_coverage` | ECL_S2 / Stage2_gross | S2 adequacy |
| `rote` | (Net profit × 4) / Avg tangible equity | Capital efficiency |

These **require DB schema changes** — new nullable Float columns added to `projected_financials` table.

---

## 7. ΔNII Rate Sensitivity (±100bps parallel shock)

Computed per quarter using a first-order repricing gap approximation:

```
repricing_assets  = floating_rate_loans + cash    (approximated as 70% of loans + 100% of cash)
repricing_liabs   = total_deposits × blended_deposit_beta

ΔNII_+100bps (annualised, EUR mn) = (repricing_assets − repricing_liabs) × 0.01
ΔNII_−100bps = −ΔNII_+100bps  (symmetric, first-order)
```

Note: floors `ΔNII_−100bps` at 0 if policy rate would go negative (lower bound assumed 0%).

Stored in `pnl_detail` blob:
```python
"nii_sensitivity": {
    "repricing_assets_eur": float,
    "repricing_liabilities_eur": float,
    "blended_deposit_beta": float,
    "delta_nii_up100bps_eur_ann": float,
    "delta_nii_dn100bps_eur_ann": float,
    "nii_at_risk_pct": float,      # |ΔNII_dn100| / base NII ann
}
```

---

## 8. CRR3 / Basel IV Output Floor

```
output_floor_rwa = max(reported_rwa, 0.725 × sa_rwa_estimate)
output_floor_binding = output_floor_rwa > reported_rwa
output_floor_cet1_ratio = cet1_capital / output_floor_rwa
```

Plan assumptions: `sa_rwa_estimate: float = 0.0` (user inputs; for SA banks = actual RWA so floor never binds; for IRB banks user supplies SA equivalent).

Fields in `CapitalState`:
```python
sa_rwa_estimate: float = 0.0
output_floor_rwa: float = 0.0
output_floor_binding: bool = False
output_floor_cet1_ratio: float = 0.0
```

---

## 9. Off-Balance-Sheet Provisions

```
obs_commitments_gross = loans_gross × obs_commitments_pct  (default 15%)
obs_ecl_provision = obs_commitments_gross × pd_s1 × lgd_s1  (S1 ECL on OBS)
obs_ecl_charge_q = change in obs_ecl_provision
```

Flows into total ECL charge alongside on-balance-sheet ECL.

Fields in `EclState`:
```python
obs_commitments_gross: float = 0.0
obs_ecl_provision: float = 0.0
obs_ecl_charge_q: float = 0.0
```

Plan assumption: `obs_commitments_pct: float = 0.15`.

---

## 10. Enhanced Bridges

### 10a. PAT Bridge (period-on-period, EUR mn)

```
ΔPAT = ΔNII + ΔFees + ΔTrading + ΔOtherIncome
       − ΔPersonnel − ΔG&A − ΔDepreciation
       − ΔECL (inc. OBS provisions change)
       − ΔTaxes
       + residual (other)
```

### 10b. NII Bridge (EUR mn)

```
ΔNII = Asset volume effect  (+loan growth × prior yield)
     + Asset yield repricing  (same volume × yield Δ)
     + Liability volume effect  (−deposit growth × prior rate)
     + Deposit beta repricing  (−deposit volume × rate Δ × beta)
     + Mix effect  (product shift)
     + OCI / hedge carry  (CFH reserve amortization into NII)
     + other
```

### 10c. Capital Waterfall (EUR mn — replaces ratio-point CET1 bridge)

```
Opening CET1 (EUR mn)
  + Quarterly PAT
  − AT1 coupon (charged to equity)
  − Cash dividends
  − Share buybacks
  − Extraordinary payout
  +/− Capital actions
  − RWA growth drag  (ΔRWA × opening CET1%)
  + DTC/DTA amortization add-on
  +/− DTA deduction change  (threshold breaches / releases)
  +/− Other  (intangibles movement, IFRS9 transitional)
= Closing CET1 (EUR mn)
→ CET1 ratio = Closing CET1 / Closing RWA
```

### 10d. Cost of Risk Bridge (bps p.a.)

```
ΔCoR = Volume effect  (loan growth × prior CoR)
     + Stage migration  (S2→S3 increase × LGD)
     + PD/LGD overlay  (macro scenario)
     + OBS provisions change
     + Write-off rate change
     + other
```

### 10e. Fee Bridge (EUR mn, by segment)

```
ΔFees = ΔRetail + ΔCorporate + ΔAsset Mgmt + ΔTreasury + other
```

### 10f. NEW: Equity Bridge (EUR mn — full reconciliation)

As specified in §1.

---

## 11. Benchmarking Module — `modules/rating/benchmarking.py`

### Peer group selection

1. User provides `peer_lei_list: list[str]` in Plan assumptions → use exactly this list
2. If not provided: use `banks` table filtered by `country = subject_bank.country`
3. Fallback: all 138 banks

### Metric computation from base year

For each metric, extract from `base_year_snapshots` using the same `BaseYearExtractor` logic, applied to each peer bank. Compute distribution statistics.

### Metrics benchmarked

| Area | Metrics |
|---|---|
| Capital | CET1 ratio, Total capital ratio, Leverage ratio, CET1 surplus vs MDA (bps) |
| P&L efficiency | NIM, ROE, RoTE (where data available), CIR, Non-interest income % |
| Asset quality | NPL ratio, CoR (bps), Coverage ratio, Texas ratio, Stage2 ratio |
| Liquidity | LCR, NSFR, LDR |
| Revenue mix | Fee ratio (fee/NII), NIR |
| Capital generation | Organic CET1 build (bps p.a.) |

### Output dataclass

```python
@dataclass
class BenchmarkMetric:
    metric_name: str
    subject_value: float
    peer_count: int
    peer_p10: float
    peer_p25: float
    peer_median: float
    peer_p75: float
    peer_p90: float
    subject_percentile: float      # 0–100
    signal: str                    # "TOP_QUARTILE" | "ABOVE_MEDIAN" | "BELOW_MEDIAN" | "BOTTOM_QUARTILE" | "BOTTOM_DECILE"

@dataclass
class BenchmarkReport:
    subject_bank_lei: str
    subject_bank_name: str
    peer_group_leis: list[str]
    peer_count: int
    base_year_period: date
    metrics: dict[str, BenchmarkMetric]   # keyed by metric_name
    generated_at: datetime
```

### DB: New `BenchmarkRun` table

```python
class BenchmarkRun(Base):
    __tablename__ = "benchmark_runs"
    id = Column(Integer, primary_key=True)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=False)
    peer_group_leis = Column(JSON)           # list of LEIs used
    peer_count = Column(Integer)
    base_year_period = Column(Date)
    results = Column(JSON)                   # BenchmarkReport as dict
    created_at = Column(DateTime, server_default=func.now())
```

---

## 12. Peer Percentile Placeholders on Projected Financials

Each `ProjectedFinancials` row gains a `peer_percentiles` JSON blob (null until benchmarking is run):

```python
peer_percentiles = Column(JSON, nullable=True)
# Structure:
{
    "cet1_ratio": {"value": 0.187, "percentile": 82.5, "peer_median": 0.155},
    "nim": {"value": 0.0314, "percentile": 71.0, "peer_median": 0.025},
    # ... one entry per benchmarked metric
}
```

---

## 13. Updated Module Map — Files to Create / Modify

### New files

```
modules/rating/benchmarking.py          — BenchmarkMetric, BenchmarkReport, run_benchmarking()
```

### Modified files

```
db/models.py                            — Add BenchmarkRun table; add new scalar columns to projected_financials
modules/calculation/state.py            — Add OCIState, EquityBridge, DTAState, extended CapitalState/EclState
modules/calculation/pnl.py              — OCI stub, ΔNII sensitivity output
modules/calculation/capital.py          — RoTE, tangible equity, DTC waterfall, CRR3 floor, AT1 coupon, payout
modules/calculation/bridges.py          — EquityBridge, enhanced PAT/NII/CoR/Fee bridges + CET1 waterfall
modules/calculation/engine.py           — Wire everything; compute all new hot-path scalars; include loan book bridge
```

---

## 14. Plan Assumption Schema (complete, all new fields)

```python
# Plan.portfolio_allocations additions:
{
    # === DTA/DTC ===
    "dta_regular_opening":          float,   # EUR mn (from base year)
    "dtc_stock_opening":            float,   # EUR mn (Greek banks only)
    "dtc_statutory_schedule":       list[float] | None,  # annual EUR mn list or None = straight-line
    "dtc_distribution_factor":      float,   # default 0.29
    # === Capital ===
    "at1_coupon_rate":              float,   # default 0.060
    "goodwill":                     float,   # EUR mn (from base year)
    "other_intangibles":            float,   # EUR mn
    "intangibles_annual_amort":     float,   # EUR mn p.a.
    "sa_rwa_estimate":              float,   # EUR mn (for CRR3 floor; 0 for SA banks)
    "cet1_target":                  float,   # operating target CET1 ratio, default 0.15
    "p2r":                          float,   # SREP add-on, default 0.015
    "ccyb":                         float,   # CCyB, default 0.0
    "osii":                         float,   # O-SII buffer, default 0.0
    "mrel_req_pct":                 float,   # MREL req as % TREA
    "snp_eligible":                 float,   # EUR mn SNP instruments
    # === OCI (first-order stubs) ===
    "bond_revaluation_sensitivity": float,   # EUR mn per 100bps (used to compute OCI from rate Δ)
    "hedge_reserve_annual":         float,   # EUR mn OCI from hedges (flat annual stub)
    # === Payout ===
    "regular_cash_dividend_pct":    float,   # % of quarterly PAT, default 0.40
    "buyback_pct":                  float,   # % of quarterly PAT, default 0.20
    "extraordinary_payout_eur":     float,   # one-off EUR mn
    "extraordinary_quarter":        int,     # 1-20 (which projection quarter)
    "shares_outstanding":           float,   # number of shares (mn)
    "share_price":                  float,   # EUR (for buyback yield; 0 if unknown)
    # === Funding / deposits ===
    "deposit_mix": {
        "retail_current_pct":       float,   # default 0.30
        "retail_savings_pct":       float,   # default 0.40
        "retail_time_pct":          float,   # default 0.30
        "beta_retail_current":      float,   # default 0.10
        "beta_retail_savings":      float,   # default 0.30
        "beta_retail_time":         float,   # default 0.70
        "beta_corporate":           float,   # default 0.55
        "rate_retail_current":      float,
        "rate_retail_savings":      float,
        "rate_retail_time":         float,
        "rate_corporate":           float,
    },
    # === Credit / ECL ===
    "obs_commitments_pct":          float,   # % of loans gross, default 0.15
    "loan_repayment_rate_annual":   float,   # default 0.15
    # === OCI stub ===
    "pension_actuarial_annual":     float,   # EUR mn stub (flat), default 0.0
    # === Benchmarking ===
    "peer_lei_list":                list[str] | None,  # None = country default
    # === Fee weights ===
    "fee_weights": {
        "retail":       float,   # default 0.50
        "corporate":    float,   # default 0.30
        "asset_mgmt":   float,   # default 0.10
        "treasury":     float,   # default 0.10
    },
    # === P&L ===
    "personnel_pct":                float,   # share of opex, default 0.60
    "ga_pct":                       float,   # default 0.25
    "depn_pct":                     float,   # default 0.15
    "current_tax_rate":             float,   # default 0.20
    "deferred_tax_rate":            float,   # default 0.02
    "trading_income_annual":        float,   # EUR mn flat stub, default 0.0
    "other_income_annual":          float,   # EUR mn flat stub
}
```

---

*End of design document.*
