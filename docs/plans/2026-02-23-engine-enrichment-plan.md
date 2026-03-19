# Engine Enrichment Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enrich the calculation engine with granular P&L (banking/trading NII split, opex breakdown, fee segmentation), 4-bucket deposit mix, full bridge suite (PAT / NII / capital waterfall / CoR / fees), capital buffers, MREL-MDA view, payout model (cash div + buyback + extraordinary), and EPS — all flowing into structured JSON blobs on `ProjectedFinancials`.

**Architecture:** All enrichments are backward-compatible additions to existing dataclasses in `state.py`; `pnl.py`, `funding.py`, `capital.py` and `bridges.py` each get focused enrichments; `engine.py` is re-wired to use the enriched modules. No new files are created. The `Plan.portfolio_allocations` JSON carries all new user-configurable inputs with safe defaults so existing plans still run.

**Tech Stack:** Python 3.11+ stdlib dataclasses, SQLAlchemy 2.x, pandas 2.x, numpy 2.x. No new packages needed.

---

## Reference: Key design decisions

- **P&L**: Banking-book NII + trading-book income shown separately; opex = personnel + G&A + D&A (3 lines); tax = current + deferred
- **Fees**: 4 segments — Retail / Corporate / Asset Management / Treasury; per-segment bridge
- **Deposit mix**: 4 buckets — Retail current / Retail savings / Retail time / Corporate; each has user-configurable beta
- **Capital waterfall**: EUR mn (not ratio points) — Opening CET1 + PAT − Cash div − Buyback ± Capital actions − RWA drag ± Other = Closing CET1
- **Payout**: max distributable = f(CET1 surplus vs target); user sets regular cash div %, buyback %, optional extraordinary payout (EUR mn + period)
- **MREL**: basic — requirement % TREA, SNP eligible (user input), stack vs requirement, MREL-MDA = min(MDA distributable, MREL headroom)
- **Bridges**: PAT / NII / CET1 waterfall / Cost of Risk / Fees — all as structured dicts on the `bridges` JSON blob

---

## Task 1: Enrich `state.py` — new sub-dataclasses

**Files:**
- Modify: `modules/calculation/state.py`

**What to add:**

Add these dataclasses **before** the existing `BalanceSheetState`. Each is imported and used by later modules.

```python
@dataclass
class NIIDetail:
    """Banking-book and trading-book NII decomposition (quarterly, EUR mn)."""
    # Banking book asset income
    loan_interest_income: float = 0.0
    bond_interest_income: float = 0.0        # FVOCI + AC bonds
    cash_interest_income: float = 0.0
    # Banking book liability cost (by deposit bucket)
    cost_retail_current: float = 0.0
    cost_retail_savings: float = 0.0
    cost_retail_time: float = 0.0
    cost_corporate: float = 0.0
    cost_wholesale: float = 0.0
    total_banking_book_income: float = 0.0
    total_banking_book_expense: float = 0.0
    banking_book_nii: float = 0.0
    # Trading book
    trading_book_carry: float = 0.0
    fx_gains: float = 0.0
    derivatives_income: float = 0.0
    trading_book_nii: float = 0.0
    # Total
    total_nii: float = 0.0


@dataclass
class FeeDetail:
    """Fee income by business segment (quarterly, EUR mn)."""
    retail: float = 0.0
    corporate: float = 0.0
    asset_mgmt: float = 0.0
    treasury: float = 0.0
    total: float = 0.0


@dataclass
class OpexDetail:
    """Operating expenses breakdown (quarterly, EUR mn)."""
    personnel_costs: float = 0.0
    ga_expenses: float = 0.0           # General & Administrative
    depreciation: float = 0.0
    total_opex: float = 0.0


@dataclass
class TaxDetail:
    """Tax charge decomposition (quarterly, EUR mn)."""
    current_tax: float = 0.0
    deferred_tax: float = 0.0
    total_tax: float = 0.0
    effective_tax_rate: float = 0.0    # decimal


@dataclass
class DepositMixAssumptions:
    """User-configurable deposit mix and betas. Stored in Plan.portfolio_allocations."""
    # Volume split of retail deposits (fractions, must sum to 1.0)
    retail_current_pct: float = 0.30
    retail_savings_pct: float = 0.40
    retail_time_pct: float = 0.30
    # Betas (fraction of policy rate change that passes through to deposit cost)
    beta_retail_current: float = 0.10
    beta_retail_savings: float = 0.30
    beta_retail_time: float = 0.70
    beta_corporate: float = 0.55
    # Base deposit rates (annualised, decimal)
    rate_retail_current: float = 0.001
    rate_retail_savings: float = 0.010
    rate_retail_time: float = 0.025
    rate_corporate: float = 0.020


@dataclass
class DepositMixState:
    """Deposit volumes and rates by bucket at one quarter-end (EUR mn, rates decimal)."""
    period: date = field(default_factory=date.today)
    retail_current: float = 0.0
    retail_savings: float = 0.0
    retail_time: float = 0.0
    corporate: float = 0.0
    total_retail: float = 0.0
    total_deposits: float = 0.0
    rate_retail_current: float = 0.0
    rate_retail_savings: float = 0.0
    rate_retail_time: float = 0.0
    rate_corporate: float = 0.0
    blended_deposit_rate: float = 0.0


@dataclass
class PayoutAssumptions:
    """User-configurable payout policy. Stored in Plan.portfolio_allocations."""
    # Operating CET1 target ratio (max distributable = surplus above this)
    cet1_target: float = 0.15
    # Regular payouts as % of quarterly PAT
    regular_cash_dividend_pct: float = 0.40
    buyback_pct: float = 0.20
    # Extraordinary payout (one-off, EUR mn) — validated vs CET1 surplus
    extraordinary_payout_eur: float = 0.0
    extraordinary_quarter: int = 0          # 1-20 (which projection quarter); 0 = none


@dataclass
class PayoutState:
    """Payout computation for one quarter (EUR mn)."""
    period: date = field(default_factory=date.today)
    pat_quarterly: float = 0.0
    max_distributable_eur: float = 0.0      # CET1 surplus vs target × RWA
    regular_cash_dividend: float = 0.0
    buyback: float = 0.0
    extraordinary_payout: float = 0.0
    total_payout: float = 0.0
    payout_ratio: float = 0.0              # total_payout / (pat × 4)
    # Per-share (populated if shares_outstanding > 0)
    eps_annual: float = 0.0
    dps_annual: float = 0.0
    shares_outstanding: float = 0.0
    shares_remaining: float = 0.0          # after buyback


@dataclass
class CapitalBuffers:
    """Regulatory capital buffer stack at one quarter-end (all as decimal ratios and EUR mn)."""
    period: date = field(default_factory=date.today)
    p1_minimum: float = 0.045
    ccb: float = 0.025
    p2r: float = 0.015
    ccyb: float = 0.000
    osii: float = 0.000
    mda_trigger: float = 0.0         # computed: sum of above
    current_cet1_ratio: float = 0.0
    headroom_pct: float = 0.0        # current_cet1 - mda_trigger
    headroom_eur: float = 0.0        # headroom_pct × RWA
    max_distributable_eur: float = 0.0


@dataclass
class MrelView:
    """Basic MREL-MDA view at one quarter-end (EUR mn and % TREA)."""
    period: date = field(default_factory=date.today)
    requirement_pct_trea: float = 0.0
    own_funds: float = 0.0
    at1: float = 0.0
    tier2: float = 0.0
    snp_eligible: float = 0.0          # Senior Non-Preferred (user input)
    total_mrel_stack_eur: float = 0.0
    total_mrel_stack_pct: float = 0.0  # as % TREA (= RWA for simplicity)
    mrel_headroom_eur: float = 0.0
    mrel_headroom_pct: float = 0.0
    mda_distributable_eur: float = 0.0
    mrel_mda_eur: float = 0.0          # min(mda_distributable, mrel_headroom)
```

**Also update `CapitalState`** to add these fields:
```python
# Add to CapitalState:
retained_earnings_delta: float = 0.0   # (already exists)
dividends_paid: float = 0.0            # (already exists — rename to cash_dividends)
buybacks: float = 0.0                  # NEW
capital_actions_other: float = 0.0    # NEW (issuance, calls, etc.)
rwa_growth_drag: float = 0.0          # NEW (ΔRWA × opening CET1%, EUR mn)
cet1_other: float = 0.0               # NEW (DTA, intangibles, IFRS9 transitional)
# Capital waterfall
opening_cet1_eur: float = 0.0         # NEW
closing_cet1_eur: float = 0.0         # NEW (= cet1_capital)
```

**Verification:**
```python
# Run from project root:
cd C:\Users\apman\OneDrive\Desktop\BBIRR
PYTHONIOENCODING=utf-8 .venv/Scripts/python -c "
from modules.calculation.state import (
    NIIDetail, FeeDetail, OpexDetail, TaxDetail,
    DepositMixAssumptions, DepositMixState,
    PayoutAssumptions, PayoutState,
    CapitalBuffers, MrelView
)
print('All new state classes import OK')
d = DepositMixAssumptions()
assert d.retail_current_pct + d.retail_savings_pct + d.retail_time_pct == 1.0
print('DepositMixAssumptions sums to 1.0 OK')
"
```
Expected: `All new state classes import OK` / `DepositMixAssumptions sums to 1.0 OK`

---

## Task 2: Enrich `funding.py` — 4-bucket deposit mix

**Files:**
- Modify: `modules/calculation/funding.py`

**What to change:**

Replace the single `avg_deposit_rate` + `deposit_beta` approach with a 4-bucket model. The `FundingState` dataclass stays as-is (it already has `retail_deposits`, `corporate_deposits`); we add a `DepositMixState` computation alongside it.

**Add this function:**

```python
def build_deposit_mix(
    prior: DepositMixState,
    rate_env: RateEnvironment,
    prior_policy_rate: float,
    period: date,
    total_retail_deposits: float,
    total_corporate_deposits: float,
    assumptions: DepositMixAssumptions,
    *,
    # Volume growth (quarterly)
    retail_deposit_growth_q: float = 0.005,
    corporate_deposit_growth_q: float = 0.010,
) -> DepositMixState:
    """
    Project deposit mix one quarter forward.

    Each bucket reprices: rate_new = rate_prior + beta × Δpolicy_rate
    Volumes grow by bucket-level growth rates applied to prior mix.
    """
    from modules.calculation.state import DepositMixState
    rate_delta = rate_env.policy_rate - prior_policy_rate

    # Reprice each bucket
    r_cur = max(0.0, prior.rate_retail_current + assumptions.beta_retail_current * rate_delta)
    r_sav = max(0.0, prior.rate_retail_savings + assumptions.beta_retail_savings * rate_delta)
    r_tim = max(0.0, prior.rate_retail_time    + assumptions.beta_retail_time    * rate_delta)
    r_cor = max(0.0, prior.rate_corporate      + assumptions.beta_corporate      * rate_delta)

    # Volumes: grow total then re-split by prior mix pct
    total_retail = total_retail_deposits * (1 + retail_deposit_growth_q)
    total_corp   = total_corporate_deposits * (1 + corporate_deposit_growth_q)

    v_cur = total_retail * assumptions.retail_current_pct
    v_sav = total_retail * assumptions.retail_savings_pct
    v_tim = total_retail * assumptions.retail_time_pct

    total_deposits = total_retail + total_corp

    # Blended deposit rate
    blended = 0.0
    if total_deposits > 0:
        blended = (
            v_cur * r_cur + v_sav * r_sav + v_tim * r_tim + total_corp * r_cor
        ) / total_deposits

    return DepositMixState(
        period=period,
        retail_current=v_cur,
        retail_savings=v_sav,
        retail_time=v_tim,
        corporate=total_corp,
        total_retail=total_retail,
        total_deposits=total_deposits,
        rate_retail_current=r_cur,
        rate_retail_savings=r_sav,
        rate_retail_time=r_tim,
        rate_corporate=r_cor,
        blended_deposit_rate=blended,
    )
```

**Update `funding_from_base`** to also return a `DepositMixState` (initialized from base assumptions):
```python
def deposit_mix_from_base(
    base_year,
    assumptions: DepositMixAssumptions,
    period: date,
) -> DepositMixState:
    """Initialise DepositMixState from base year + assumptions."""
    from modules.calculation.state import DepositMixState
    deposits_total = base_year.deposits_and_debt * 0.70 if base_year.deposits_and_debt else 0.0
    total_retail = deposits_total * 0.60
    total_corp   = deposits_total * 0.40
    v_cur = total_retail * assumptions.retail_current_pct
    v_sav = total_retail * assumptions.retail_savings_pct
    v_tim = total_retail * assumptions.retail_time_pct
    blended = (
        v_cur * assumptions.rate_retail_current
        + v_sav * assumptions.rate_retail_savings
        + v_tim * assumptions.rate_retail_time
        + total_corp * assumptions.rate_corporate
    ) / (deposits_total if deposits_total > 0 else 1.0)
    return DepositMixState(
        period=period,
        retail_current=v_cur, retail_savings=v_sav, retail_time=v_tim,
        corporate=total_corp,
        total_retail=total_retail, total_deposits=deposits_total,
        rate_retail_current=assumptions.rate_retail_current,
        rate_retail_savings=assumptions.rate_retail_savings,
        rate_retail_time=assumptions.rate_retail_time,
        rate_corporate=assumptions.rate_corporate,
        blended_deposit_rate=blended,
    )
```

**Verification:**
```python
PYTHONIOENCODING=utf-8 .venv/Scripts/python -c "
from modules.calculation.state import DepositMixAssumptions, DepositMixState, RateEnvironment
from modules.calculation.funding import build_deposit_mix
from datetime import date

assumptions = DepositMixAssumptions()
prior = DepositMixState(
    period=date(2025, 6, 30),
    retail_current=3000, retail_savings=4000, retail_time=3000,
    corporate=8000, total_retail=10000, total_deposits=18000,
    rate_retail_current=0.001, rate_retail_savings=0.010,
    rate_retail_time=0.025, rate_corporate=0.020, blended_deposit_rate=0.015
)
rate_env = RateEnvironment(policy_rate=0.040)  # rate cut by -50bps from 0.040? let's test increase
result = build_deposit_mix(prior, rate_env, prior_policy_rate=0.035, period=date(2025, 9, 30),
    total_retail_deposits=10000, total_corporate_deposits=8000, assumptions=assumptions)
print(f'Blended rate: {result.blended_deposit_rate:.4f}')
print(f'Retail time rate: {result.rate_retail_time:.4f}  (should increase by 0.70*0.005={0.70*0.005:.4f})')
assert abs(result.rate_retail_time - (0.025 + 0.70 * 0.005)) < 0.0001, 'beta repricing failed'
print('Deposit mix build OK')
"
```
Expected: `Deposit mix build OK`

---

## Task 3: Enrich `pnl.py` — banking/trading NII split, fee segments, opex 3-way, tax detail

**Files:**
- Modify: `modules/calculation/pnl.py`

**Replace `calculate_pnl` signature** to accept:
- `deposit_mix: DepositMixState` (for granular interest expense)
- `fee_weights: dict` (segment allocation)
- `personnel_pct: float = 0.60` (share of opex that is personnel)
- `ga_pct: float = 0.25` (G&A)
- `depn_pct: float = 0.15` (D&A)
- `current_tax_rate: float = 0.20`, `deferred_tax_rate: float = 0.02`

**Return type becomes a richer structure.** Update `PnLState` to carry the sub-detail objects:

Add to `PnLState`:
```python
nii_detail: NIIDetail = field(default_factory=NIIDetail)
fee_detail: FeeDetail = field(default_factory=FeeDetail)
opex_detail: OpexDetail = field(default_factory=OpexDetail)
tax_detail: TaxDetail = field(default_factory=TaxDetail)
# Rename existing flat fields to remain for backward compat:
personnel_costs: float = 0.0
ga_expenses: float = 0.0
# (depreciation already exists)
pre_provision_profit: float = 0.0  # (already exists)
trading_income: float = 0.0        # NEW: net trading income (separate from NII)
```

**Updated `calculate_pnl` logic:**

```python
def calculate_pnl(
    bs: BalanceSheetState,
    funding: FundingState,
    deposit_mix: DepositMixState,
    rate_env: RateEnvironment,
    period: date,
    prior_bs: BalanceSheetState | None = None,
    *,
    loan_yield: float = 0.055,
    bond_yield: float = 0.040,
    cash_yield_spread: float = 0.002,
    fee_growth_q: float = 0.01,
    base_fee_income: float = 0.0,
    fee_weights: dict | None = None,       # {'retail':0.50,'corporate':0.30,'asset_mgmt':0.10,'treasury':0.10}
    trading_income: float = 0.0,           # net trading income (flat for PoC, from assumptions)
    other_income: float = 0.0,
    total_opex_q: float = 0.0,             # total opex for the quarter
    personnel_pct: float = 0.60,
    ga_pct: float = 0.25,
    depn_pct: float = 0.15,
    current_tax_rate: float = 0.20,
    deferred_tax_rate: float = 0.02,
    ecl_charge_q: float = 0.0,
) -> PnLState:
```

**Banking-book NII computation:**
```python
avg_loans = (bs.loans_net + (prior_bs.loans_net if prior_bs else bs.loans_net)) / 2
avg_bonds = (bs.fvoci_assets + (prior_bs.fvoci_assets if prior_bs else bs.fvoci_assets)) / 2
avg_cash  = (bs.cash + (prior_bs.cash if prior_bs else bs.cash)) / 2

eff_cash_yield = rate_env.policy_rate + cash_yield_spread
loan_income  = avg_loans * loan_yield / 4
bond_income  = avg_bonds * bond_yield / 4
cash_income  = avg_cash  * eff_cash_yield / 4
total_bb_income = loan_income + bond_income + cash_income

# Deposit expense from mix (annualised rate / 4)
cost_cur = deposit_mix.retail_current * deposit_mix.rate_retail_current / 4
cost_sav = deposit_mix.retail_savings * deposit_mix.rate_retail_savings / 4
cost_tim = deposit_mix.retail_time    * deposit_mix.rate_retail_time    / 4
cost_cor = deposit_mix.corporate      * deposit_mix.rate_corporate      / 4
cost_whl = (funding.covered_bonds + funding.senior_unsecured
            + funding.interbank_funding + funding.subordinated_debt
            + funding.central_bank_funding) * funding.avg_wholesale_rate / 4
total_bb_expense = cost_cur + cost_sav + cost_tim + cost_cor + cost_whl

bb_nii = total_bb_income - total_bb_expense
tb_nii = trading_income   # trading book carry included in trading_income
total_nii = bb_nii + tb_nii
```

**Fee segmentation:**
```python
_default_fee_weights = {'retail': 0.50, 'corporate': 0.30, 'asset_mgmt': 0.10, 'treasury': 0.10}
fw = fee_weights or _default_fee_weights
total_fee = base_fee_income * (1 + fee_growth_q)
fee_detail = FeeDetail(
    retail=total_fee * fw.get('retail', 0.50),
    corporate=total_fee * fw.get('corporate', 0.30),
    asset_mgmt=total_fee * fw.get('asset_mgmt', 0.10),
    treasury=total_fee * fw.get('treasury', 0.10),
    total=total_fee,
)
```

**Opex split:**
```python
personnel = total_opex_q * personnel_pct
ga        = total_opex_q * ga_pct
depn      = total_opex_q * depn_pct
opex_detail = OpexDetail(personnel_costs=personnel, ga_expenses=ga, depreciation=depn, total_opex=total_opex_q)
```

**Tax:**
```python
pbt = pre_provision_profit - ecl_charge_q
current_tax  = max(0.0, pbt * current_tax_rate)
deferred_tax = max(0.0, pbt * deferred_tax_rate)
total_tax    = current_tax + deferred_tax
eff_rate     = total_tax / pbt if pbt > 0 else 0.0
net_profit   = pbt - total_tax
tax_detail = TaxDetail(current_tax=current_tax, deferred_tax=deferred_tax,
                        total_tax=total_tax, effective_tax_rate=eff_rate)
```

**Verification:**
```python
PYTHONIOENCODING=utf-8 .venv/Scripts/python -c "
from modules.calculation.pnl import calculate_pnl
from modules.calculation.state import *
from datetime import date

bs = BalanceSheetState(period=date(2025,9,30), total_assets=74000, loans_net=45000,
    loans_gross=47000, ecl_allowance=2000, fvoci_assets=12000, cash=10000,
    other_assets=7000, deposits=30000, wholesale_funding=20000,
    other_liabilities=4000, total_liabilities=54000, equity=20000)
dm = DepositMixState(period=date(2025,9,30), retail_current=6000, retail_savings=8000,
    retail_time=6000, corporate=10000, total_retail=20000, total_deposits=30000,
    rate_retail_current=0.001, rate_retail_savings=0.010,
    rate_retail_time=0.025, rate_corporate=0.020, blended_deposit_rate=0.015)
funding = FundingState(period=date(2025,9,30), retail_deposits=20000,
    corporate_deposits=10000, interbank_funding=5000, covered_bonds=8000,
    senior_unsecured=4000, central_bank_funding=0, subordinated_debt=1000,
    total_funding=48000, avg_deposit_rate=0.015, avg_wholesale_rate=0.030,
    blended_cost_of_funds=0.021, deposit_beta=0.30)
rate_env = RateEnvironment(policy_rate=0.035, euribor_3m=0.030)

pnl = calculate_pnl(bs, funding, dm, rate_env, date(2025,9,30),
    loan_yield=0.055, bond_yield=0.040, base_fee_income=100,
    total_opex_q=300, ecl_charge_q=50)
print(f'Banking NII: {pnl.nii_detail.banking_book_nii:.1f}')
print(f'Total NII: {pnl.nii:.1f}')
print(f'Fee Retail: {pnl.fee_detail.retail:.1f}')
print(f'Personnel: {pnl.opex_detail.personnel_costs:.1f}')
print(f'Tax: {pnl.tax_detail.total_tax:.1f}')
print(f'Net profit: {pnl.net_profit:.1f}')
assert pnl.opex_detail.total_opex == 300
print('pnl enrichment OK')
"
```

---

## Task 4: Enrich `capital.py` — waterfall EUR mn, buffers, MREL, payout

**Files:**
- Modify: `modules/calculation/capital.py`

**4a. Capital waterfall (`calculate_capital`):**

Replace the existing CET1 accumulation logic with the EUR mn waterfall:

```python
def calculate_capital(
    prior: CapitalState,
    pnl: PnLState,
    bs: BalanceSheetState,
    period: date,
    payout: PayoutState,          # NEW: pass computed payout state
    *,
    capital_actions_other: float = 0.0,   # EUR mn (+ = issuance, - = buyback/call)
    rwa_credit_density: float | None = None,
    at1_capital: float | None = None,
    tier2_capital: float | None = None,
    p2r: float = 0.015,
    ccyb: float = 0.0,
    osii: float = 0.0,
    snp_eligible: float = 0.0,
    mrel_req_pct: float = 0.0,
) -> tuple[CapitalState, CapitalBuffers, MrelView]:
    """Returns (CapitalState, CapitalBuffers, MrelView) — all three."""
```

**Waterfall computation:**
```python
opening_cet1 = prior.cet1_capital
pat_q = pnl.net_profit
cash_div = payout.regular_cash_dividend
buyback  = payout.buyback
extra    = payout.extraordinary_payout
rwa_growth_drag = (bs.loans_gross - prior.rwa_credit / (prior_density or 0.70)) * (prior_density or 0.70) * prior.cet1_ratio
# simplified: drag = ΔRWA_credit × prior_cet1_ratio
rwa_credit_new = bs.loans_gross * (rwa_credit_density or prior_density)
delta_rwa_credit = rwa_credit_new - prior.rwa_credit
rwa_drag_eur = delta_rwa_credit * prior.cet1_ratio   # EUR mn reduction
cet1_other = 0.0  # DTA / intangibles / IFRS9 (zero for PoC)

closing_cet1 = (
    opening_cet1
    + pat_q
    - cash_div
    - buyback
    - extra
    + capital_actions_other
    - rwa_drag_eur
    + cet1_other
)
```

**CapitalBuffers computation:**
```python
mda_trigger = 0.045 + 0.025 + p2r + ccyb + osii
headroom_pct = closing_cet1 / rwa_total - mda_trigger
headroom_eur = headroom_pct * rwa_total
buffers = CapitalBuffers(
    period=period, p1_minimum=0.045, ccb=0.025, p2r=p2r,
    ccyb=ccyb, osii=osii, mda_trigger=mda_trigger,
    current_cet1_ratio=closing_cet1/rwa_total,
    headroom_pct=headroom_pct, headroom_eur=headroom_eur,
    max_distributable_eur=max(0.0, headroom_eur),
)
```

**MrelView computation:**
```python
total_mrel_stack = closing_cet1 + at1 + tier2 + snp_eligible
req_eur = mrel_req_pct * rwa_total
mrel_headroom = total_mrel_stack - req_eur
mrel_view = MrelView(
    period=period, requirement_pct_trea=mrel_req_pct,
    own_funds=closing_cet1 + at1 + tier2,
    at1=at1, tier2=tier2, snp_eligible=snp_eligible,
    total_mrel_stack_eur=total_mrel_stack,
    total_mrel_stack_pct=total_mrel_stack / rwa_total if rwa_total > 0 else 0.0,
    mrel_headroom_eur=mrel_headroom,
    mrel_headroom_pct=mrel_headroom / rwa_total if rwa_total > 0 else 0.0,
    mda_distributable_eur=max(0.0, headroom_eur),
    mrel_mda_eur=min(max(0.0, headroom_eur), max(0.0, mrel_headroom)),
)
```

**4b. Add `calculate_payout` function:**
```python
def calculate_payout(
    pnl: PnLState,
    prior_capital: CapitalState,
    period: date,
    quarter_index: int,          # 1-based index in projection (1-20)
    rwa: float,
    assumptions: PayoutAssumptions,
    prior_shares: float = 0.0,
    share_price: float = 0.0,
) -> PayoutState:
    """Compute payout for one quarter given PAT and CET1 surplus."""
    pat_q = pnl.net_profit
    # Max distributable: CET1 surplus above target × RWA + regular payout of PAT
    cet1_surplus_eur = max(0.0, (prior_capital.cet1_ratio - assumptions.cet1_target) * rwa)
    max_dist = cet1_surplus_eur + pat_q * max(assumptions.regular_cash_dividend_pct,
                                               assumptions.buyback_pct)

    # Regular payout
    cash_div = pat_q * assumptions.regular_cash_dividend_pct
    buyback  = pat_q * assumptions.buyback_pct

    # Extraordinary payout (only in specified quarter, validated vs surplus)
    extra = 0.0
    if quarter_index == assumptions.extraordinary_quarter and assumptions.extraordinary_payout_eur > 0:
        extra = min(assumptions.extraordinary_payout_eur, max(0.0, cet1_surplus_eur))

    total_payout = cash_div + buyback + extra
    payout_ratio = (total_payout * 4) / (pat_q * 4) if pat_q > 0 else 0.0

    # Per-share
    shares = prior_shares if prior_shares > 0 else 1.0  # avoid div/0
    buyback_shares = buyback / share_price if share_price > 0 else 0.0
    shares_remaining = max(0.0, shares - buyback_shares)
    eps = (pat_q * 4) / shares_remaining if shares_remaining > 0 else 0.0
    dps = (cash_div * 4) / shares_remaining if shares_remaining > 0 else 0.0

    return PayoutState(
        period=period, pat_quarterly=pat_q,
        max_distributable_eur=max_dist,
        regular_cash_dividend=cash_div,
        buyback=buyback, extraordinary_payout=extra,
        total_payout=total_payout, payout_ratio=payout_ratio,
        eps_annual=eps, dps_annual=dps,
        shares_outstanding=shares, shares_remaining=shares_remaining,
    )
```

**Verification:**
```python
PYTHONIOENCODING=utf-8 .venv/Scripts/python -c "
from modules.calculation.capital import calculate_payout
from modules.calculation.state import PayoutAssumptions, CapitalState, PnLState
from datetime import date

assumptions = PayoutAssumptions(cet1_target=0.15, regular_cash_dividend_pct=0.40, buyback_pct=0.20)
cap = CapitalState(period=date(2025,6,30), cet1_capital=6893, cet1_ratio=0.187, rwa_total=36825)
pnl = PnLState(period=date(2025,9,30), net_profit=290)

payout = calculate_payout(pnl, cap, date(2025,9,30), quarter_index=1, rwa=36825, assumptions=assumptions)
print(f'Cash dividend: {payout.regular_cash_dividend:.1f}mn')
print(f'Buyback: {payout.buyback:.1f}mn')
print(f'Payout ratio: {payout.payout_ratio:.1%}')
assert abs(payout.regular_cash_dividend - 290 * 0.40) < 0.01
print('Payout calc OK')
"
```

---

## Task 5: Enrich `bridges.py` — full PAT bridge + CoR bridge + fee bridge

**Files:**
- Modify: `modules/calculation/bridges.py`

**5a. PAT Bridge (new dataclass):**

```python
@dataclass
class PATBridge:
    """Profit After Tax waterfall between two periods (EUR mn quarterly)."""
    prior_pat: float
    delta_nii: float
    delta_fees: float
    delta_trading: float
    delta_other_income: float
    delta_personnel: float       # negative = cost increase
    delta_ga: float              # negative = cost increase
    delta_depreciation: float    # negative = cost increase
    delta_impairments: float     # negative = ECL/provisions increase
    delta_taxes: float           # negative = tax increase
    other: float                 # residual
    current_pat: float

    @property
    def check(self) -> float:
        return (self.current_pat - self.prior_pat
                - self.delta_nii - self.delta_fees - self.delta_trading
                - self.delta_other_income
                - self.delta_personnel - self.delta_ga - self.delta_depreciation
                - self.delta_impairments - self.delta_taxes - self.other)

    def to_dict(self) -> dict:
        return {
            "prior": self.prior_pat,
            "delta_nii": self.delta_nii,
            "delta_fees": self.delta_fees,
            "delta_trading": self.delta_trading,
            "delta_other_income": self.delta_other_income,
            "delta_personnel": self.delta_personnel,
            "delta_ga": self.delta_ga,
            "delta_depreciation": self.delta_depreciation,
            "delta_impairments": self.delta_impairments,
            "delta_taxes": self.delta_taxes,
            "other": self.other,
            "current": self.current_pat,
            "check": self.check,
        }


def calculate_pat_bridge(prior_pnl: PnLState, curr_pnl: PnLState) -> PATBridge:
    delta_nii      = curr_pnl.nii - prior_pnl.nii
    delta_fees     = curr_pnl.fee_income_net - prior_pnl.fee_income_net
    delta_trading  = curr_pnl.trading_income - prior_pnl.trading_income
    delta_other    = curr_pnl.other_income - prior_pnl.other_income
    delta_pers     = -(curr_pnl.opex_detail.personnel_costs - prior_pnl.opex_detail.personnel_costs)
    delta_ga       = -(curr_pnl.opex_detail.ga_expenses     - prior_pnl.opex_detail.ga_expenses)
    delta_depn     = -(curr_pnl.opex_detail.depreciation    - prior_pnl.opex_detail.depreciation)
    delta_imp      = -(curr_pnl.ecl_charge - prior_pnl.ecl_charge)
    delta_tax      = -(curr_pnl.tax_charge - prior_pnl.tax_charge)
    total_explained = (delta_nii + delta_fees + delta_trading + delta_other
                       + delta_pers + delta_ga + delta_depn + delta_imp + delta_tax)
    actual_delta = curr_pnl.net_profit - prior_pnl.net_profit
    return PATBridge(
        prior_pat=prior_pnl.net_profit,
        delta_nii=delta_nii, delta_fees=delta_fees, delta_trading=delta_trading,
        delta_other_income=delta_other, delta_personnel=delta_pers,
        delta_ga=delta_ga, delta_depreciation=delta_depn,
        delta_impairments=delta_imp, delta_taxes=delta_tax,
        other=actual_delta - total_explained,
        current_pat=curr_pnl.net_profit,
    )
```

**5b. Cost of Risk Bridge (new dataclass):**
```python
@dataclass
class CORBridge:
    """Cost of Risk bridge between two periods (bps p.a.)."""
    prior_cor_bps: float
    volume_effect: float       # loan growth × prior CoR rate
    stage_migration: float     # S2→S3 increase
    pd_lgd_overlay: float      # macro scenario overlay
    write_off_change: float    # change in net write-offs
    other: float
    current_cor_bps: float

    def to_dict(self) -> dict:
        return {
            "prior_bps": self.prior_cor_bps,
            "volume": self.volume_effect,
            "stage_migration": self.stage_migration,
            "pd_lgd_overlay": self.pd_lgd_overlay,
            "write_offs": self.write_off_change,
            "other": self.other,
            "current_bps": self.current_cor_bps,
        }


def calculate_cor_bridge(prior_pf_cor, curr_pf_cor, prior_aq, curr_aq, prior_bs, curr_bs) -> CORBridge:
    """
    prior_pf_cor, curr_pf_cor: annualised CoR (decimal) from ProjectedFinancials
    prior_aq, curr_aq: AssetQualityState
    """
    to_bps = lambda x: x * 10000
    prior_bps = to_bps(prior_pf_cor)
    curr_bps  = to_bps(curr_pf_cor)
    delta_bps = curr_bps - prior_bps

    volume_effect = to_bps(prior_pf_cor) * (
        (curr_bs.loans_gross - prior_bs.loans_gross) / prior_bs.loans_gross
        if prior_bs.loans_gross > 0 else 0.0
    )
    stage_mig = to_bps((curr_aq.stage3_gross - prior_aq.stage3_gross) /
                        curr_bs.loans_gross * 0.40) if curr_bs.loans_gross > 0 else 0.0  # rough LGD
    other = delta_bps - volume_effect - stage_mig
    return CORBridge(prior_cor_bps=prior_bps, volume_effect=volume_effect,
                     stage_migration=stage_mig, pd_lgd_overlay=0.0,
                     write_off_change=0.0, other=other, current_cor_bps=curr_bps)
```

**5c. Fee Bridge (new dataclass):**
```python
@dataclass
class FeeBridge:
    """Fee income bridge between two periods (EUR mn quarterly)."""
    prior_fees_total: float
    delta_retail: float
    delta_corporate: float
    delta_asset_mgmt: float
    delta_treasury: float
    other: float
    current_fees_total: float

    def to_dict(self) -> dict:
        return {
            "prior": self.prior_fees_total,
            "delta_retail": self.delta_retail,
            "delta_corporate": self.delta_corporate,
            "delta_asset_mgmt": self.delta_asset_mgmt,
            "delta_treasury": self.delta_treasury,
            "other": self.other,
            "current": self.current_fees_total,
        }


def calculate_fee_bridge(prior_pnl: PnLState, curr_pnl: PnLState) -> FeeBridge:
    d_ret  = curr_pnl.fee_detail.retail     - prior_pnl.fee_detail.retail
    d_cor  = curr_pnl.fee_detail.corporate  - prior_pnl.fee_detail.corporate
    d_am   = curr_pnl.fee_detail.asset_mgmt - prior_pnl.fee_detail.asset_mgmt
    d_tre  = curr_pnl.fee_detail.treasury   - prior_pnl.fee_detail.treasury
    d_tot  = curr_pnl.fee_detail.total - prior_pnl.fee_detail.total
    return FeeBridge(
        prior_fees_total=prior_pnl.fee_detail.total,
        delta_retail=d_ret, delta_corporate=d_cor,
        delta_asset_mgmt=d_am, delta_treasury=d_tre,
        other=d_tot - d_ret - d_cor - d_am - d_tre,
        current_fees_total=curr_pnl.fee_detail.total,
    )
```

**Also update `CET1Bridge`** to use the EUR mn waterfall (remove ratio-point fields, add EUR mn fields matching the capital waterfall in Task 4).

**Verification:**
```python
PYTHONIOENCODING=utf-8 .venv/Scripts/python -c "
from modules.calculation.bridges import calculate_pat_bridge, PATBridge
from modules.calculation.state import PnLState, OpexDetail, FeeDetail, TaxDetail
from datetime import date

p = PnLState(period=date(2025,6,30), nii=580, fee_income_net=100, trading_income=20,
    other_income=10, net_profit=290, ecl_charge=50, tax_charge=80,
    opex_detail=OpexDetail(personnel_costs=180, ga_expenses=75, depreciation=45, total_opex=300),
    fee_detail=FeeDetail(retail=50, corporate=30, asset_mgmt=10, treasury=10, total=100),
    tax_detail=TaxDetail(current_tax=64, deferred_tax=16, total_tax=80, effective_tax_rate=0.216))
c = PnLState(period=date(2025,9,30), nii=595, fee_income_net=103, trading_income=22,
    other_income=10, net_profit=300, ecl_charge=48, tax_charge=82,
    opex_detail=OpexDetail(personnel_costs=182, ga_expenses=76, depreciation=46, total_opex=304),
    fee_detail=FeeDetail(retail=52, corporate=31, asset_mgmt=10, treasury=10, total=103),
    tax_detail=TaxDetail(current_tax=65, deferred_tax=17, total_tax=82, effective_tax_rate=0.215))
bridge = calculate_pat_bridge(p, c)
print(f'PAT bridge check: {bridge.check:.4f}  (should be ~0)')
assert abs(bridge.check) < 0.001, f'Bridge does not reconcile: {bridge.check}'
print('PAT bridge OK')
"
```

---

## Task 6: Update `engine.py` — wire enriched modules

**Files:**
- Modify: `modules/calculation/engine.py`

**Changes:**

1. **Add new plan assumption keys** to `_DEFAULT_PORTFOLIO`:
```python
_DEFAULT_PORTFOLIO.update({
    "personnel_pct":            0.60,
    "ga_pct":                   0.25,
    "depn_pct":                 0.15,
    "current_tax_rate":         0.20,
    "deferred_tax_rate":        0.02,
    "trading_income_q":         0.0,
    "other_income_q":           0.0,
    "p2r":                      0.015,
    "ccyb":                     0.000,
    "osii":                     0.000,
    "mrel_req_pct":             0.0,
    "snp_eligible":             0.0,
    "cet1_target":              0.15,
    "regular_cash_dividend_pct": 0.40,
    "buyback_pct":              0.20,
    "extraordinary_payout_eur": 0.0,
    "extraordinary_quarter":    0,
    "shares_outstanding":       0.0,
    "fee_weights": {
        "retail": 0.50, "corporate": 0.30, "asset_mgmt": 0.10, "treasury": 0.10
    },
    "deposit_mix": None,       # will use DepositMixAssumptions defaults
})
```

2. **Import and use new modules** in the quarterly loop:
   - `from modules.calculation.state import DepositMixAssumptions, PayoutAssumptions`
   - `from modules.calculation.funding import build_deposit_mix, deposit_mix_from_base`
   - `from modules.calculation.capital import calculate_payout`
   - `from modules.calculation.bridges import calculate_pat_bridge, calculate_fee_bridge, calculate_cor_bridge`

3. **Loop changes** (per quarter):
   - Initialise `deposit_mix` from base; call `build_deposit_mix()` each quarter
   - Call `calculate_payout()` before `calculate_capital()` (payout feeds capital waterfall)
   - Call enriched `calculate_pnl()` with `deposit_mix`, `fee_weights`, opex split params, tax params
   - Call `calculate_pat_bridge()`, `calculate_fee_bridge()`, `calculate_cor_bridge()` and include in `bridges` dict
   - Include `deposit_mix`, `payout`, `capital_buffers`, `mrel_view` in the `ProjectedFinancials` JSON blobs

4. **Balance sheet before→after**: In the `balance_sheet_detail` blob:
```python
balance_sheet_detail = {
    **_to_dict(bs),
    "before": _to_dict(prior_bs),
    "after":  _to_dict(bs),
}
```

5. **Updated ProjectedFinancials blobs:**
```python
pf = ProjectedFinancials(
    ...
    # New/updated blobs
    capital_detail={
        **_to_dict(capital),
        "buffers": _to_dict(capital_buffers),
        "mrel": _to_dict(mrel_view),
        "payout": _to_dict(payout),
        "waterfall": {
            "opening_cet1": prior_cap.cet1_capital,
            "pat": pnl.net_profit,
            "cash_dividends": -payout.regular_cash_dividend,
            "buybacks": -payout.buyback,
            "extraordinary": -payout.extraordinary_payout,
            "capital_actions": 0.0,
            "rwa_drag": -capital.rwa_growth_drag,
            "other": capital.cet1_other,
            "closing_cet1": capital.cet1_capital,
        }
    },
    pnl_detail={
        **_to_dict(pnl),
        "nii_detail": _to_dict(pnl.nii_detail),
        "fee_detail": _to_dict(pnl.fee_detail),
        "opex_detail": _to_dict(pnl.opex_detail),
        "tax_detail": _to_dict(pnl.tax_detail),
    },
    balance_sheet_detail={
        "before": _to_dict(prior_bs),
        "after":  _to_dict(bs),
        "deposit_mix": _to_dict(deposit_mix),
    },
    bridges={
        "pat":  pat_bridge.to_dict(),
        "nii":  nii_bridge.to_dict(),
        "cet1_waterfall": capital_waterfall_dict,
        "cor":  cor_bridge.to_dict(),
        "fees": fee_bridge.to_dict(),
        "roe":  roe_bridge.to_dict(),
    },
)
```

**Full engine verification** (run after all tasks complete):
```python
PYTHONIOENCODING=utf-8 .venv/Scripts/python -c "
import logging; logging.basicConfig(level=logging.INFO)
from db.engine import get_session
from db.models import Bank, Plan
DB_PATH = 'data/processed/bbirr.db'
Session = get_session(DB_PATH)
db = Session()

nbg = db.query(Bank).filter(Bank.lei == '5UMCZOEYKCVFAW8ZLO05').first()
plan = Plan(bank_id=nbg.id, name='Enriched Test Plan', horizon_years=5, version=1,
    portfolio_allocations={
        'loan_growth_q': 0.01, 'dividend_payout': 0.40,
        'fee_weights': {'retail':0.50,'corporate':0.30,'asset_mgmt':0.10,'treasury':0.10},
        'p2r': 0.015, 'cet1_target': 0.15, 'mrel_req_pct': 0.214,
    })
db.add(plan); db.flush()
from modules.calculation.engine import run_projection
results = run_projection(plan, None, db)
print(f'Generated {len(results)} quarters')
pf = results[0]
print(f'CET1 ratio: {pf.cet1_ratio:.2%}')
print(f'NII (ann): EUR {pf.nii:,.0f}mn')
print(f'Bridges keys: {list(pf.bridges.keys())}')
print(f'Capital detail keys: {list(pf.capital_detail.keys())}')
print(f'Balance sheet detail keys: {list(pf.balance_sheet_detail.keys())}')
assert \"pat\" in pf.bridges, \"missing pat bridge\"
assert \"buffers\" in pf.capital_detail, \"missing capital buffers\"
assert \"before\" in pf.balance_sheet_detail, \"missing before/after BS\"
print()
print(f'{'Period':<14} {'CET1%':>7} {'NII ann':>10} {'ROE':>7} {'EPS':>8} {'DPS':>8}')
print('-' * 55)
for r in results:
    pay = r.capital_detail.get('payout', {})
    eps = pay.get('eps_annual', 0) if pay else 0
    dps = pay.get('dps_annual', 0) if pay else 0
    print(f'{str(r.period):<14} {r.cet1_ratio:.1%} {r.nii:>10,.0f} {r.roe:.1%} {eps:>8.4f} {dps:>8.4f}')
db.rollback()
print()
print('Full engine verification PASSED')
"
```
Expected: 20 quarters, all bridges present, capital buffers and BS before/after included.

---

## Execution order

Tasks must be executed in sequence (each builds on the prior):
1. → Task 1 (state.py additions — all downstream imports this)
2. → Task 2 (funding.py deposit mix — used by pnl.py and engine)
3. → Task 3 (pnl.py enrichment — requires deposit_mix from Task 2)
4. → Task 4 (capital.py waterfall + payout — requires enriched pnl from Task 3)
5. → Task 5 (bridges.py full suite — requires enriched pnl + capital from Tasks 3-4)
6. → Task 6 (engine.py re-wire — requires all of the above)
