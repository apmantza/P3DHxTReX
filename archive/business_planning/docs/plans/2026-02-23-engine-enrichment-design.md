# BBIRR Calculation Engine Enrichment — Design

**Date:** 2026-02-23
**Status:** Approved
**Scope:** Engine + structured output dicts (ProjectedFinancials JSON blobs enriched for Step 8 UI)

---

## 1. Enriched P&L Structure

The P&L is split into **banking book** and **trading book** NII, then a full income waterfall:

```
Banking Book NII
  ├── Loan interest income
  ├── Bond portfolio income (FVOCI / amortised cost)
  ├── Cash / central bank income
  └── Customer deposit expense (by bucket: current / savings / time / corporate)

Trading Book Income
  ├── Trading bond carry
  ├── FX gains/losses (net)
  └── Derivatives / structured products

= Total NII  (banking + trading interest)
+ Fee income (net):
    ├── Retail Banking
    ├── Corporate Banking
    ├── Asset Management
    └── Treasury
+ Total trading income (net, from trading book above)
+ Other operating income
= Total Operating Income (TOI)

Personnel costs
G&A expenses
Depreciation & amortisation
= Total Opex
= CIR = Opex / TOI

Pre-Provision Profit (PPP) = TOI − Opex

ECL / Impairment charge:
  ├── Stage 1 change
  ├── Stage 2 change
  └── Stage 3 / write-offs net

Profit Before Tax (PBT) = PPP − ECL

Current tax + Deferred tax = Tax charge
Profit After Tax (PAT) = PBT − Tax
```

### New state fields added to PnLState

```python
@dataclass
class OpexDetail:
    personnel_costs: float
    ga_expenses: float
    depreciation: float
    total_opex: float

@dataclass
class FeeDetail:
    retail: float
    corporate: float
    asset_mgmt: float
    treasury: float
    total: float

@dataclass
class NIIDetail:
    banking_book_interest_income: float
    loan_interest_income: float
    bond_interest_income: float
    cash_interest_income: float
    banking_book_interest_expense: float   # by deposit bucket
    banking_book_nii: float
    trading_book_nii: float                # carry on trading positions
    total_nii: float

@dataclass
class TaxDetail:
    current_tax: float
    deferred_tax: float
    total_tax: float
    effective_tax_rate: float
```

---

## 2. Deposit Mix Model

### Buckets (retail × 3 + corporate × 1)

| Bucket | Default Beta | Default Rate | Notes |
|---|---|---|---|
| Retail current (O/N) | 0.10 | 0.10% | Sticky; low pass-through |
| Retail savings | 0.30 | 1.00% | Moderate |
| Retail time deposits | 0.70 | 2.50% | High; full repricing at maturity |
| Corporate deposits | 0.55 | blended | Moderate-high |

### User-configurable fields (in Plan assumptions)

```python
@dataclass
class DepositMixAssumptions:
    # Volume split (must sum to 1.0 for retail; corporate is separate volume)
    retail_current_pct: float = 0.30
    retail_savings_pct: float = 0.40
    retail_time_pct: float = 0.30
    # Betas (user can override defaults)
    beta_retail_current: float = 0.10
    beta_retail_savings: float = 0.30
    beta_retail_time: float = 0.70
    beta_corporate: float = 0.55
    # Base rates (starting deposit rates, decimal)
    rate_retail_current: float = 0.001
    rate_retail_savings: float = 0.010
    rate_retail_time: float = 0.025
    rate_corporate: float = 0.020
```

Deposit repricing:
```
rate_bucket_new = rate_bucket_prior + beta_bucket × ΔPolicyRate
```

---

## 3. Bridges

### 3a. PAT Bridge (period-on-period, EUR mn)

```
ΔPAT = ΔNII + ΔFees + ΔTrading + ΔOtherIncome
       − ΔPersonnel − ΔG&A − ΔDepreciation
       − ΔImpairments − ΔTaxes
```

Check: sum of all components = ΔPAT (residual capped at < 0.01 EUR mn for bridge integrity).

### 3b. NII Bridge (EUR mn)

```
ΔNII = Volume effect (asset growth × prior yield)
     + Yield repricing (same volume × yield Δ)
     + Funding cost volume (liability growth × prior rate)
     + Deposit beta repricing (liability volume × rate Δ × beta)
     + Mix effect (product shift)
     + Other / residual
```

### 3c. Capital Waterfall — EUR mn (replaces ratio-point CET1 bridge)

```
Opening CET1 (EUR mn)
  + Quarterly PAT
  − Cash dividends
  − Share buybacks
  +/− Capital actions (new issuance, AT1 call, T2 redemption, etc.)
  − RWA growth drag (ΔRWA × opening CET1%)
  +/− Other (DTA change, intangibles movement, IFRS9 transitional)
= Closing CET1 (EUR mn)
→ CET1 ratio = Closing CET1 / Closing RWA
```

### 3d. Cost of Risk Bridge (bps p.a.)

```
ΔCoR = Volume effect (loan growth × prior CoR rate)
     + Stage migration (S2→S3 increase × LGD Δ)
     + PD/LGD overlay (macro scenario)
     + Write-off changes
     + Other
```

### 3e. Fee Bridge (EUR mn, by segment)

```
ΔFees = ΔRetail + ΔCorporate + ΔAssetMgmt + ΔTreasury + Other
```

---

## 4. Payout Model

### Rules

1. **Max distributable** = `max(0, CET1_ratio - cet1_target) × RWA`
   + `quarterly_PAT × max_regular_payout_ratio`

2. **User inputs (per year, in Plan assumptions)**:
   - `cet1_target`: target operating CET1 ratio (e.g. 0.15)
   - `regular_cash_dividend_pct`: % of PAT as cash dividend (e.g. 0.40)
   - `buyback_pct`: % of PAT as share buyback (e.g. 0.20)
   - `extraordinary_payout_eur` and `extraordinary_period`: optional one-off; validated against CET1 surplus vs target

3. **Share count update**: buybacks reduce shares outstanding, increasing EPS

### EPS / DPS / Buyback yield

```python
EPS = PAT_annual / shares_outstanding
DPS = cash_dividend_annual / shares_outstanding
Buyback_yield = buyback_annual_eur / (shares × price)
Payout_ratio = (cash_dividend + buyback) / PAT
```

---

## 5. Capital Buffers View

Output dict in every ProjectedFinancials `capital_detail` blob:

```python
{
  "buffers": {
    "p1_minimum":        0.045,
    "ccb":               0.025,
    "p2r":               user_input,        # e.g. 0.015
    "ccyb":              user_input,        # e.g. 0.000
    "osii":              user_input,        # e.g. 0.005
    "mda_trigger":       computed,          # sum of above
    "current_cet1":      projected_ratio,
    "headroom_pct":      current_cet1 - mda_trigger,
    "headroom_eur":      headroom_pct × RWA,
    "max_distributable": headroom_eur,
  }
}
```

---

## 6. MREL-MDA (Basic)

Output dict in `capital_detail`:

```python
{
  "mrel": {
    "requirement_pct_trea":  user_input,     # e.g. 0.214 for NBG
    "own_funds":             computed,
    "at1":                   computed,
    "tier2":                 computed,
    "snp_eligible":          user_input,     # Senior Non-Preferred notional
    "total_mrel_stack_eur":  computed,
    "total_mrel_stack_pct":  stack / RWA,
    "mrel_headroom_eur":     computed,
    "mrel_headroom_pct":     computed,
    "mda_distributable_eur": headroom_eur,
    "mrel_mda_eur":          min(mda_distributable, mrel_headroom),
  }
}
```

---

## 7. Balance Sheet Before → After View

Included in each `balance_sheet_detail` blob as a `before_after` sub-dict comparing prior and current quarter on all key line items. The UI renders this as a two-column table.

---

## 8. Implementation Changes

### Files to modify
- `modules/calculation/state.py` — add `OpexDetail`, `FeeDetail`, `NIIDetail`, `TaxDetail`, `DepositMixAssumptions`, `PayoutAssumptions`, `CapitalBuffers`, `MrelView`
- `modules/calculation/pnl.py` — split opex into 3 lines, add banking/trading NII, fee segmentation, tax detail
- `modules/calculation/funding.py` — replace flat deposit with 4-bucket deposit mix model
- `modules/calculation/capital.py` — add capital waterfall (EUR mn), buffers view, MREL view, payout logic
- `modules/calculation/bridges.py` — enrich all bridge dataclasses as per Section 3
- `modules/calculation/engine.py` — wire up all enriched modules

### Files to create
- None (all enrichments go into existing files)

### Plan assumption fields to add
In the `Plan.portfolio_allocations` JSON, add:
- `deposit_mix: DepositMixAssumptions`
- `payout: PayoutAssumptions`
- `capital_reqs: {p2r, ccyb, osii, cet1_target}`
- `mrel: {requirement_pct_trea, snp_eligible}`
- `shares_outstanding`
- `fee_segment_weights: {retail, corporate, asset_mgmt, treasury}`
