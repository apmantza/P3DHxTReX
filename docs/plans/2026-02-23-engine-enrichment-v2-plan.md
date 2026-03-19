# Engine Enrichment v2 — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enrich the BBIRR calculation engine with full OCI/equity bridge, Greek DTA/DTC regulatory treatment, AT1 coupons, loan book gross bridge, RoTE/tangible book, 8 new hot-path ratios, ΔNII sensitivity, CRR3 output floor, OBS provisions, full bridge suite (PAT/NII/capital waterfall/CoR/fee/equity), and a peer benchmarking module.

**Architecture:** All additions are backward-compatible. Engine state uses Python dataclasses. No new packages needed. New `BenchmarkRun` table added to DB. New scalar columns added to `projected_financials`. All new items produce structured JSON blobs in `ProjectedFinancials` so Step 8 UI views are trivial.

**Tech Stack:** Python 3.11 stdlib dataclasses, SQLAlchemy 2.x, pandas 2.x, numpy 2.x.

**Design doc:** `docs/plans/2026-02-23-engine-enrichment-v2-design.md`

**Execution order:** Tasks must run sequentially (each imports from the prior).

---

## Task 1: DB schema — new columns + BenchmarkRun table

**Files:**
- Modify: `db/models.py`

**Step 1: Add new scalar columns to `ProjectedFinancials`**

After the existing `cir` column, add:

```python
# New hot-path scalars (Task 1)
ldr = Column(Float, nullable=True)                # loan-to-deposit ratio
nir = Column(Float, nullable=True)                # non-interest income ratio
texas_ratio = Column(Float, nullable=True)
breakeven_cor_bps = Column(Float, nullable=True)
capital_gen_rate_bps = Column(Float, nullable=True)
non_interest_income_pct = Column(Float, nullable=True)
stage2_coverage = Column(Float, nullable=True)
rote = Column(Float, nullable=True)
# New JSON blobs
peer_percentiles = Column(JSON, nullable=True)
equity_bridge = Column(JSON, nullable=True)
oci_detail = Column(JSON, nullable=True)
dta_detail = Column(JSON, nullable=True)
nii_sensitivity = Column(JSON, nullable=True)
loan_book_bridge = Column(JSON, nullable=True)
```

**Step 2: Add `BenchmarkRun` table (before the `AuditLog` class)**

```python
class BenchmarkRun(Base):
    """Peer benchmarking results for a plan."""
    __tablename__ = "benchmark_runs"

    id = Column(Integer, primary_key=True)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=False)
    peer_group_leis = Column(JSON, nullable=True)    # list[str]
    peer_count = Column(Integer, nullable=True)
    base_year_period = Column(Date, nullable=True)
    results = Column(JSON, nullable=True)            # BenchmarkReport as dict
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (Index("ix_benchmark_plan", "plan_id"),)
```

**Step 3: Also add `BenchmarkRun` to `Plan` relationship**

In `Plan` class, add:
```python
benchmark_runs = relationship("BenchmarkRun", backref="plan", cascade="all, delete-orphan")
```

**Step 4: Re-create DB (PoC uses create_all — drop and recreate)**

```bash
cd C:\Users\apman\OneDrive\Desktop\BBIRR
PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/init_db.py
```

**Verification:**
```python
PYTHONIOENCODING=utf-8 .venv/Scripts/python -c "
from db.engine import get_engine
from db.models import Base, ProjectedFinancials, BenchmarkRun
engine = get_engine('data/processed/bbirr_v2.db')
Base.metadata.create_all(engine)
cols = [c.name for c in ProjectedFinancials.__table__.columns]
assert 'ldr' in cols, 'ldr column missing'
assert 'rote' in cols, 'rote column missing'
assert 'peer_percentiles' in cols, 'peer_percentiles column missing'
from sqlalchemy import inspect
assert 'benchmark_runs' in inspect(engine).get_table_names()
print('DB schema OK — all new columns and tables present')
"
```

---

## Task 2: Enrich `state.py` — new sub-dataclasses

**Files:**
- Modify: `modules/calculation/state.py`

**Step 1: Add imports at top of file**

```python
from dataclasses import dataclass, field
from datetime import date, datetime
```
(already there — verify only)

**Step 2: Add `OCIState` after existing `FTPState`**

```python
@dataclass
class OCIState:
    """Other Comprehensive Income components (quarterly, EUR mn)."""
    period: date = field(default_factory=date.today)
    bond_revaluation: float = 0.0          # FVOCI MTM change this quarter
    hedge_reserve_change: float = 0.0      # CFH reserve movement
    pension_actuarial: float = 0.0         # DB pension actuarial (quarterly stub)
    fx_translation: float = 0.0            # foreign subsidiary FX
    total_oci: float = 0.0
    total_comprehensive_income: float = 0.0  # PAT + OCI


@dataclass
class EquityBridgeState:
    """Full equity reconciliation bridge (quarterly, EUR mn). Must close."""
    period: date = field(default_factory=date.today)
    opening_equity: float = 0.0
    tci: float = 0.0               # Total Comprehensive Income = PAT + OCI
    at1_coupons: float = 0.0       # negative: charged to equity not P&L
    cash_dividends: float = 0.0    # negative
    buybacks: float = 0.0          # negative
    extraordinary_payout: float = 0.0
    capital_actions: float = 0.0   # signed: + issuance, - buyback/call
    dtc_cet1_addon: float = 0.0    # positive: Greek DTC amortization add-on
    other: float = 0.0             # residual
    closing_equity: float = 0.0
    check: float = 0.0             # must be < 0.01 EUR mn


@dataclass
class DTAState:
    """DTA/DTC position at one quarter-end (EUR mn)."""
    period: date = field(default_factory=date.today)
    # Regular DTA
    dta_regular: float = 0.0
    dta_threshold_10pct_cet1: float = 0.0    # 10% CET1 threshold
    dta_deducted_from_cet1: float = 0.0      # portion above threshold (deducted CET1)
    dta_rw_250pct: float = 0.0               # portion below threshold (250% RW)
    # DTC — Greek Law 4172/2013 (zero for all non-Greek banks)
    dtc_stock_opening: float = 0.0
    dtc_statutory_amortization_q: float = 0.0
    dtc_distribution_linked_q: float = 0.0
    dtc_total_amortization_q: float = 0.0
    dtc_stock_closing: float = 0.0
    dtc_cet1_addon: float = 0.0             # CET1 numerator add-on this quarter
    dtc_distribution_factor: float = 0.29
    # Totals
    dta_dtc_total_bs: float = 0.0           # total DTA+DTC on B/S asset side
    dta_rwa_contribution: float = 0.0       # DTC×100% + DTA_below_thresh×250%
```

**Step 3: Update `CapitalState` — add new fields**

After existing `cet1_surplus: float = 0.0`, add:

```python
    # Waterfall components (EUR mn) — for capital waterfall bridge
    opening_cet1_eur: float = 0.0
    closing_cet1_eur: float = 0.0
    at1_coupons_q: float = 0.0
    buybacks_q: float = 0.0
    extraordinary_payout_q: float = 0.0
    capital_actions_q: float = 0.0
    rwa_growth_drag: float = 0.0
    dtc_cet1_addon: float = 0.0
    cet1_other: float = 0.0
    # RoTE / tangible equity
    goodwill: float = 0.0
    other_intangibles: float = 0.0
    tangible_equity: float = 0.0
    rote: float = 0.0
    tangible_bvps: float = 0.0
    # CRR3 / output floor
    sa_rwa_estimate: float = 0.0
    output_floor_rwa: float = 0.0
    output_floor_binding: bool = False
    output_floor_cet1_ratio: float = 0.0
```

**Step 4: Update `EclState` — add OBS fields**

After existing `weight_severe: float = 0.0`, add:

```python
    # Off-balance-sheet provisions
    obs_commitments_gross: float = 0.0
    obs_ecl_provision: float = 0.0
    obs_ecl_charge_q: float = 0.0
    # Total ECL (on-BS + OBS)
    total_ecl_charge_q: float = 0.0        # ecl_charge + obs_ecl_charge_q
```

**Step 5: Add `PayoutState` and related dataclasses**

(These were in the v1 plan — confirm they exist; add if not)

```python
@dataclass
class PayoutAssumptions:
    cet1_target: float = 0.15
    regular_cash_dividend_pct: float = 0.40
    buyback_pct: float = 0.20
    extraordinary_payout_eur: float = 0.0
    extraordinary_quarter: int = 0


@dataclass
class PayoutState:
    period: date = field(default_factory=date.today)
    pat_quarterly: float = 0.0
    max_distributable_eur: float = 0.0
    regular_cash_dividend: float = 0.0
    buyback: float = 0.0
    extraordinary_payout: float = 0.0
    total_payout: float = 0.0
    payout_ratio: float = 0.0
    eps_annual: float = 0.0
    dps_annual: float = 0.0
    shares_outstanding: float = 0.0
    shares_remaining: float = 0.0
```

**Verification:**
```python
PYTHONIOENCODING=utf-8 .venv/Scripts/python -c "
from modules.calculation.state import (
    OCIState, EquityBridgeState, DTAState,
    PayoutAssumptions, PayoutState
)
d = DTAState()
assert d.dtc_distribution_factor == 0.29
p = PayoutAssumptions()
assert p.cet1_target == 0.15
e = EquityBridgeState()
print('All new state dataclasses import OK')
# Verify CapitalState has new fields
from modules.calculation.state import CapitalState
c = CapitalState()
assert hasattr(c, 'rote'), 'rote missing from CapitalState'
assert hasattr(c, 'output_floor_binding'), 'output_floor_binding missing'
# Verify EclState has OBS fields
from modules.calculation.state import EclState
ec = EclState()
assert hasattr(ec, 'obs_ecl_charge_q'), 'obs_ecl_charge_q missing'
print('State enrichment OK')
"
```

---

## Task 3: Enrich `capital.py` — DTC waterfall, RoTE, CRR3, AT1 coupons, payout, buffers, MREL

**Files:**
- Modify: `modules/calculation/capital.py`

**Step 1: Add `calculate_dta_state` function**

```python
def calculate_dta_state(
    prior: DTAState,
    period: date,
    payout: PayoutState,
    cet1_capital: float,
    *,
    dtc_statutory_schedule: list[float] | None = None,
    dtc_distribution_factor: float = 0.29,
    base_year: int = 2025,
    amortization_end_year: int = 2052,
) -> DTAState:
    """
    Project DTA/DTC state one quarter forward.

    Statutory amortization:
      - If dtc_statutory_schedule is provided: use (index = year - base_year)
      - Else: straight-line to 2052
    Distribution-linked:
      - 0.29 × total_distributions_q
    """
    from datetime import date as _date
    current_year = period.year

    # Statutory amortization (annual, divided by 4 for quarterly)
    if dtc_statutory_schedule and (current_year - base_year) < len(dtc_statutory_schedule):
        annual_statutory = dtc_statutory_schedule[current_year - base_year]
    else:
        years_remaining = max(1, amortization_end_year - current_year)
        annual_statutory = prior.dtc_stock_opening / years_remaining

    statutory_q = annual_statutory / 4

    # Distribution-linked
    total_dist_q = (payout.regular_cash_dividend + payout.buyback
                    + payout.extraordinary_payout)
    distribution_q = total_dist_q * dtc_distribution_factor

    total_amort_q = statutory_q + distribution_q
    dtc_closing = max(0.0, prior.dtc_stock_opening - total_amort_q)

    # CET1 add-on = amortized DTC (RW was 100%, releasing = CET1 benefit)
    cet1_addon = total_amort_q

    # Regular DTA: rough threshold check
    threshold = cet1_capital * 0.10
    dta_above = max(0.0, prior.dta_regular - threshold)
    dta_below  = prior.dta_regular - dta_above

    total_bs = prior.dta_regular + dtc_closing
    rwa_contribution = dtc_closing * 1.00 + dta_below * 2.50  # 100% + 250% RW

    return DTAState(
        period=period,
        dta_regular=prior.dta_regular,            # assumed flat for PoC (DTA utilised from profit)
        dta_threshold_10pct_cet1=threshold,
        dta_deducted_from_cet1=dta_above,
        dta_rw_250pct=dta_below,
        dtc_stock_opening=prior.dtc_stock_opening,
        dtc_statutory_amortization_q=statutory_q,
        dtc_distribution_linked_q=distribution_q,
        dtc_total_amortization_q=total_amort_q,
        dtc_stock_closing=dtc_closing,
        dtc_cet1_addon=cet1_addon,
        dtc_distribution_factor=dtc_distribution_factor,
        dta_dtc_total_bs=total_bs,
        dta_rwa_contribution=rwa_contribution,
    )
```

**Step 2: Add `calculate_oci` function**

```python
def calculate_oci(
    pnl_net_profit: float,
    period: date,
    *,
    bond_revaluation_sensitivity: float = 0.0,   # EUR mn per 100bps
    rate_delta_q: float = 0.0,                    # actual rate change this quarter
    hedge_reserve_annual: float = 0.0,            # EUR mn flat stub
    pension_actuarial_annual: float = 0.0,
    fx_translation_q: float = 0.0,
) -> OCIState:
    """Compute OCI for one quarter (stub implementation)."""
    from modules.calculation.state import OCIState
    bond_reval = bond_revaluation_sensitivity * (rate_delta_q / 0.01)   # scale to actual Δ
    hedge_q    = hedge_reserve_annual / 4
    pension_q  = pension_actuarial_annual / 4
    total_oci  = bond_reval + hedge_q + pension_q + fx_translation_q
    return OCIState(
        period=period,
        bond_revaluation=bond_reval,
        hedge_reserve_change=hedge_q,
        pension_actuarial=pension_q,
        fx_translation=fx_translation_q,
        total_oci=total_oci,
        total_comprehensive_income=pnl_net_profit + total_oci,
    )
```

**Step 3: Add `calculate_equity_bridge` function**

```python
def calculate_equity_bridge(
    prior_equity: float,
    tci: float,
    payout: PayoutState,
    at1_coupon_q: float,
    capital_actions_q: float,
    dtc_cet1_addon: float,
    closing_equity: float,
    period: date,
) -> EquityBridgeState:
    from modules.calculation.state import EquityBridgeState
    computed_closing = (
        prior_equity + tci
        - at1_coupon_q
        - payout.regular_cash_dividend
        - payout.buyback
        - payout.extraordinary_payout
        + capital_actions_q
        + dtc_cet1_addon
    )
    check = closing_equity - computed_closing
    return EquityBridgeState(
        period=period,
        opening_equity=prior_equity,
        tci=tci,
        at1_coupons=-at1_coupon_q,
        cash_dividends=-payout.regular_cash_dividend,
        buybacks=-payout.buyback,
        extraordinary_payout=-payout.extraordinary_payout,
        capital_actions=capital_actions_q,
        dtc_cet1_addon=dtc_cet1_addon,
        other=check,              # residual: ideally ≈ 0
        closing_equity=closing_equity,
        check=check,
    )
```

**Step 4: Update `calculate_capital` — add RoTE, CRR3, new waterfall fields**

Extend the existing function signature to accept:
```python
def calculate_capital(
    prior: CapitalState,
    pnl,                            # PnLState
    bs,                             # BalanceSheetState
    period: date,
    payout,                         # PayoutState
    dta_state: DTAState | None = None,
    *,
    capital_actions_other: float = 0.0,
    rwa_credit_density: float | None = None,
    at1_capital: float | None = None,
    tier2_capital: float | None = None,
    p2r: float = 0.015,
    ccyb: float = 0.0,
    osii: float = 0.0,
    snp_eligible: float = 0.0,
    mrel_req_pct: float = 0.0,
    goodwill: float = 0.0,
    other_intangibles: float = 0.0,
    sa_rwa_estimate: float = 0.0,
    shares_outstanding: float = 0.0,
    at1_coupon_rate: float = 0.06,
) -> tuple:   # (CapitalState, CapitalBuffers, MrelView)
```

In the function body, after computing `closing_cet1` and `rwa_total`:

```python
# AT1 coupon (charged to equity quarterly)
at1_coupon_q = (at1_capital or prior.at1_capital) * at1_coupon_rate / 4

# RoTE
tangible_equity = bs.equity - goodwill - other_intangibles
rote = (pnl.net_profit * 4) / tangible_equity if tangible_equity > 0 else 0.0
tangible_bvps = tangible_equity / shares_outstanding if shares_outstanding > 0 else 0.0

# CRR3 output floor
if sa_rwa_estimate > 0:
    output_floor_rwa = max(rwa_total, 0.725 * sa_rwa_estimate)
    output_floor_binding = output_floor_rwa > rwa_total
    output_floor_cet1 = closing_cet1 / output_floor_rwa if output_floor_rwa > 0 else 0.0
else:
    output_floor_rwa = rwa_total
    output_floor_binding = False
    output_floor_cet1 = closing_cet1 / rwa_total if rwa_total > 0 else 0.0

# DTC add-on
dtc_addon = dta_state.dtc_cet1_addon if dta_state else 0.0
closing_cet1 += dtc_addon   # add DTC benefit to CET1 numerator

# Waterfall tracking fields
rwa_drag = (rwa_total - prior.rwa_total) * prior.cet1_ratio
```

**Step 5: Add `calculate_payout` function**

(Same as v1 plan — verify it exists, add if not)

**Verification:**
```python
PYTHONIOENCODING=utf-8 .venv/Scripts/python -c "
from modules.calculation.capital import calculate_dta_state, calculate_oci, calculate_equity_bridge
from modules.calculation.state import DTAState, PayoutState
from datetime import date

prior_dta = DTAState(period=date(2025,6,30), dta_regular=500, dtc_stock_opening=3000)
payout = PayoutState(period=date(2025,9,30), regular_cash_dividend=290,
                     buyback=145, extraordinary_payout=0)

dta = calculate_dta_state(prior_dta, date(2025,9,30), payout, cet1_capital=6893)
print(f'DTC statutory Q: {dta.dtc_statutory_amortization_q:.1f}mn')
print(f'DTC distribution-linked: {dta.dtc_distribution_linked_q:.1f}mn')
print(f'  (should be 0.29 × {290+145} = {0.29*(290+145):.1f}mn)')
print(f'DTC CET1 addon: {dta.dtc_cet1_addon:.1f}mn')
assert abs(dta.dtc_distribution_linked_q - 0.29 * (290 + 145)) < 0.01
print('DTA/DTC calculation OK')

oci = calculate_oci(pnl_net_profit=290, period=date(2025,9,30),
    bond_revaluation_sensitivity=-50, rate_delta_q=-0.0025)
print(f'OCI bond reval: {oci.bond_revaluation:.2f}mn')
print(f'TCI: {oci.total_comprehensive_income:.2f}mn')
print('OCI OK')
"
```

---

## Task 4: Enrich `bridges.py` — full PAT + NII + capital waterfall + CoR + fee + equity bridges

**Files:**
- Modify: `modules/calculation/bridges.py`

**Step 1: Add `PATBridge` dataclass and `calculate_pat_bridge` function**

```python
@dataclass
class PATBridge:
    prior_pat: float
    delta_nii: float
    delta_fees: float
    delta_trading: float
    delta_other_income: float
    delta_personnel: float
    delta_ga: float
    delta_depreciation: float
    delta_ecl: float                # includes OBS provisions
    delta_taxes: float
    other: float
    current_pat: float

    @property
    def check(self) -> float:
        return (self.current_pat - self.prior_pat
                - self.delta_nii - self.delta_fees - self.delta_trading
                - self.delta_other_income - self.delta_personnel
                - self.delta_ga - self.delta_depreciation
                - self.delta_ecl - self.delta_taxes - self.other)

    def to_dict(self) -> dict:
        return {
            "prior": self.prior_pat,
            "delta_nii": self.delta_nii, "delta_fees": self.delta_fees,
            "delta_trading": self.delta_trading, "delta_other": self.delta_other_income,
            "delta_personnel": self.delta_personnel, "delta_ga": self.delta_ga,
            "delta_depreciation": self.delta_depreciation,
            "delta_ecl": self.delta_ecl, "delta_taxes": self.delta_taxes,
            "other": self.other, "current": self.current_pat, "check": self.check,
        }


def calculate_pat_bridge(prior_pnl, curr_pnl) -> PATBridge:
    d = lambda attr: getattr(curr_pnl, attr, 0.0) - getattr(prior_pnl, attr, 0.0)
    d_pers = -(getattr(curr_pnl.opex_detail,'personnel_costs',0) - getattr(prior_pnl.opex_detail,'personnel_costs',0))
    d_ga   = -(getattr(curr_pnl.opex_detail,'ga_expenses',0)     - getattr(prior_pnl.opex_detail,'ga_expenses',0))
    d_depn = -(getattr(curr_pnl.opex_detail,'depreciation',0)    - getattr(prior_pnl.opex_detail,'depreciation',0))
    d_nii  = d('nii')
    d_fee  = getattr(curr_pnl.fee_detail,'total',curr_pnl.fee_income_net) - getattr(prior_pnl.fee_detail,'total',prior_pnl.fee_income_net)
    d_trd  = getattr(curr_pnl,'trading_income',0) - getattr(prior_pnl,'trading_income',0)
    d_oth  = getattr(curr_pnl,'other_income',0) - getattr(prior_pnl,'other_income',0)
    d_ecl  = -(d('ecl_charge'))
    d_tax  = -(d('tax_charge'))
    actual = curr_pnl.net_profit - prior_pnl.net_profit
    explained = d_nii + d_fee + d_trd + d_oth + d_pers + d_ga + d_depn + d_ecl + d_tax
    return PATBridge(
        prior_pat=prior_pnl.net_profit,
        delta_nii=d_nii, delta_fees=d_fee, delta_trading=d_trd,
        delta_other_income=d_oth, delta_personnel=d_pers,
        delta_ga=d_ga, delta_depreciation=d_depn,
        delta_ecl=d_ecl, delta_taxes=d_tax,
        other=actual - explained,
        current_pat=curr_pnl.net_profit,
    )
```

**Step 2: Add `CapitalWaterfall` dataclass**

```python
@dataclass
class CapitalWaterfall:
    """Capital waterfall in EUR mn (replaces ratio-point CET1 bridge)."""
    period: date
    opening_cet1_eur: float
    pat_q: float
    at1_coupons: float           # negative
    cash_dividends: float        # negative
    buybacks: float              # negative
    extraordinary_payout: float  # negative
    capital_actions: float       # signed
    rwa_growth_drag: float       # negative (ΔRWA × opening CET1%)
    dtc_cet1_addon: float        # positive (Greek DTC)
    dta_deduction_change: float  # signed (threshold breach/release)
    other: float
    closing_cet1_eur: float
    opening_rwa: float
    closing_rwa: float
    opening_cet1_ratio: float
    closing_cet1_ratio: float

    def to_dict(self) -> dict:
        return {
            "opening_cet1_eur": self.opening_cet1_eur,
            "pat": self.pat_q, "at1_coupons": self.at1_coupons,
            "cash_dividends": self.cash_dividends, "buybacks": self.buybacks,
            "extraordinary": self.extraordinary_payout,
            "capital_actions": self.capital_actions,
            "rwa_drag": self.rwa_growth_drag,
            "dtc_addon": self.dtc_cet1_addon,
            "dta_deduction_change": self.dta_deduction_change,
            "other": self.other,
            "closing_cet1_eur": self.closing_cet1_eur,
            "opening_rwa": self.opening_rwa, "closing_rwa": self.closing_rwa,
            "opening_ratio": self.opening_cet1_ratio,
            "closing_ratio": self.closing_cet1_ratio,
        }


def calculate_capital_waterfall(prior_cap, curr_cap, pnl, payout, dta_state, period) -> CapitalWaterfall:
    at1_q = curr_cap.at1_coupons_q
    rwa_drag = (curr_cap.rwa_total - prior_cap.rwa_total) * prior_cap.cet1_ratio
    dtc_addon = dta_state.dtc_cet1_addon if dta_state else 0.0
    actual_delta = curr_cap.cet1_capital - prior_cap.cet1_capital
    explained = (pnl.net_profit - at1_q
                 - payout.regular_cash_dividend - payout.buyback - payout.extraordinary_payout
                 + 0.0 - rwa_drag + dtc_addon)
    return CapitalWaterfall(
        period=period,
        opening_cet1_eur=prior_cap.cet1_capital,
        pat_q=pnl.net_profit, at1_coupons=-at1_q,
        cash_dividends=-payout.regular_cash_dividend,
        buybacks=-payout.buyback,
        extraordinary_payout=-payout.extraordinary_payout,
        capital_actions=0.0, rwa_growth_drag=-rwa_drag,
        dtc_cet1_addon=dtc_addon, dta_deduction_change=0.0,
        other=actual_delta - explained,
        closing_cet1_eur=curr_cap.cet1_capital,
        opening_rwa=prior_cap.rwa_total, closing_rwa=curr_cap.rwa_total,
        opening_cet1_ratio=prior_cap.cet1_ratio,
        closing_cet1_ratio=curr_cap.cet1_ratio,
    )
```

**Step 3: Add `CorBridge`, `FeeBridge`, `EquityBridgeOut` and calculation functions**

```python
@dataclass
class CORBridge:
    prior_cor_bps: float
    volume_effect: float
    stage_migration: float
    pd_lgd_overlay: float
    obs_change: float
    write_off_change: float
    other: float
    current_cor_bps: float

    def to_dict(self) -> dict:
        return {"prior_bps": self.prior_cor_bps, "volume": self.volume_effect,
                "stage_migration": self.stage_migration, "pd_lgd_overlay": self.pd_lgd_overlay,
                "obs": self.obs_change, "write_offs": self.write_off_change,
                "other": self.other, "current_bps": self.current_cor_bps}


def calculate_cor_bridge(prior_cor, curr_cor, prior_aq, curr_aq, prior_bs, curr_bs) -> CORBridge:
    to_bps = lambda x: x * 10000
    d_bps = to_bps(curr_cor) - to_bps(prior_cor)
    vol_eff = to_bps(prior_cor) * (
        (curr_bs.loans_gross - prior_bs.loans_gross) / prior_bs.loans_gross
        if prior_bs.loans_gross > 0 else 0.0)
    stage_mig = to_bps((curr_aq.stage3_gross - prior_aq.stage3_gross)
                        / curr_bs.loans_gross * 0.40) if curr_bs.loans_gross > 0 else 0.0
    return CORBridge(prior_cor_bps=to_bps(prior_cor), volume_effect=vol_eff,
                     stage_migration=stage_mig, pd_lgd_overlay=0.0, obs_change=0.0,
                     write_off_change=0.0, other=d_bps - vol_eff - stage_mig,
                     current_cor_bps=to_bps(curr_cor))


@dataclass
class FeeBridge:
    prior_fees_total: float
    delta_retail: float
    delta_corporate: float
    delta_asset_mgmt: float
    delta_treasury: float
    other: float
    current_fees_total: float

    def to_dict(self) -> dict:
        return {"prior": self.prior_fees_total, "delta_retail": self.delta_retail,
                "delta_corporate": self.delta_corporate, "delta_asset_mgmt": self.delta_asset_mgmt,
                "delta_treasury": self.delta_treasury, "other": self.other,
                "current": self.current_fees_total}


def calculate_fee_bridge(prior_pnl, curr_pnl) -> FeeBridge:
    pfd = lambda pnl: getattr(pnl, 'fee_detail', None)
    def seg(pnl, attr):
        fd = pfd(pnl)
        return getattr(fd, attr, 0.0) if fd else 0.0
    return FeeBridge(
        prior_fees_total=seg(prior_pnl,'total') or prior_pnl.fee_income_net,
        delta_retail=seg(curr_pnl,'retail') - seg(prior_pnl,'retail'),
        delta_corporate=seg(curr_pnl,'corporate') - seg(prior_pnl,'corporate'),
        delta_asset_mgmt=seg(curr_pnl,'asset_mgmt') - seg(prior_pnl,'asset_mgmt'),
        delta_treasury=seg(curr_pnl,'treasury') - seg(prior_pnl,'treasury'),
        other=0.0,
        current_fees_total=seg(curr_pnl,'total') or curr_pnl.fee_income_net,
    )
```

**Verification:**
```python
PYTHONIOENCODING=utf-8 .venv/Scripts/python -c "
from modules.calculation.bridges import (
    calculate_pat_bridge, calculate_capital_waterfall,
    calculate_cor_bridge, calculate_fee_bridge,
    PATBridge, CapitalWaterfall, CORBridge, FeeBridge
)
print('All bridge classes and functions import OK')
"
```

---

## Task 5: Enrich `pnl.py` — ΔNII sensitivity + full opex/fee/tax/trading

**Files:**
- Modify: `modules/calculation/pnl.py`

**Step 1: Add ΔNII sensitivity computation at end of `calculate_pnl`**

After computing `net_profit`, add:

```python
# ΔNII sensitivity: first-order repricing gap
repricing_asset_pct = 0.70   # assumed 70% of loans are floating/short
repricing_assets  = bs.loans_net * repricing_asset_pct + bs.cash
blended_beta = funding.deposit_beta if hasattr(funding,'deposit_beta') else 0.30
repricing_liabs   = (funding.retail_deposits + funding.corporate_deposits) * blended_beta
delta_nii_up100   = (repricing_assets - repricing_liabs) * 0.01    # annualised EUR mn
delta_nii_dn100   = max(-(repricing_assets - repricing_liabs) * 0.01,
                        -pnl.nii * 4 * 0.50)  # floor: max -50% NII
nii_at_risk_pct   = abs(delta_nii_dn100) / max(pnl.nii * 4, 1.0)

# Store in pnl as attribute (consumed by engine for JSON blob)
pnl._nii_sensitivity = {
    "repricing_assets_eur": repricing_assets,
    "repricing_liabilities_eur": repricing_liabs,
    "blended_deposit_beta": blended_beta,
    "delta_nii_up100bps_eur_ann": delta_nii_up100,
    "delta_nii_dn100bps_eur_ann": delta_nii_dn100,
    "nii_at_risk_pct": nii_at_risk_pct,
}
```

Note: `_nii_sensitivity` is a runtime attribute (not in the dataclass definition) — the engine reads it via `getattr(pnl, '_nii_sensitivity', {})`.

**Step 2: Add `trading_income` field to `PnLState`**

Add to `PnLState`:
```python
trading_income: float = 0.0     # net trading income (separate from NII)
```

**Verification:**
```python
PYTHONIOENCODING=utf-8 .venv/Scripts/python -c "
from modules.calculation.pnl import pnl_from_base
from modules.calculation.state import BaseYear
from datetime import date
base = BaseYear(nii=2325, interest_income=3400, interest_expense=1075,
    fee_income_net=750, total_operating_income=3400, admin_expenses=800,
    depreciation=200, ecl_charge=400, net_profit=1161,
    total_assets=73932, loans_ac=45000, loans_gross=47000,
    deposits_and_debt=50000, equity=18000, nim=0.0314, roe=0.14, cir=0.369)
pnl = pnl_from_base(base, date(2025,9,30))
assert hasattr(pnl, 'trading_income'), 'trading_income missing'
print(f'NII quarterly: {pnl.nii:.1f}mn (annual equiv: {pnl.nii*4:.0f}mn)')
print('pnl_from_base OK')
"
```

---

## Task 6: Enrich `engine.py` — wire all enriched modules + compute new hot-path scalars

**Files:**
- Modify: `modules/calculation/engine.py`

**Step 1: Add new default plan assumptions**

```python
_DEFAULT_PORTFOLIO.update({
    # DTA/DTC
    "dta_regular_opening":        0.0,
    "dtc_stock_opening":          0.0,
    "dtc_statutory_schedule":     None,
    "dtc_distribution_factor":    0.29,
    # Capital
    "at1_coupon_rate":            0.06,
    "goodwill":                   0.0,
    "other_intangibles":          0.0,
    "intangibles_annual_amort":   0.0,
    "sa_rwa_estimate":            0.0,
    "mrel_req_pct":               0.0,
    "snp_eligible":               0.0,
    "p2r":                        0.015,
    "ccyb":                       0.0,
    "osii":                       0.0,
    "cet1_target":                0.15,
    # Payout
    "regular_cash_dividend_pct":  0.40,
    "buyback_pct":                0.20,
    "extraordinary_payout_eur":   0.0,
    "extraordinary_quarter":      0,
    "shares_outstanding":         0.0,
    "share_price":                0.0,
    # OCI stubs
    "bond_revaluation_sensitivity": 0.0,
    "hedge_reserve_annual":         0.0,
    "pension_actuarial_annual":     0.0,
    # Credit
    "obs_commitments_pct":        0.15,
    "loan_repayment_rate_annual":  0.15,
    # Fee weights
    "fee_weights": {"retail":0.50,"corporate":0.30,"asset_mgmt":0.10,"treasury":0.10},
    # P&L opex split
    "personnel_pct":              0.60,
    "ga_pct":                     0.25,
    "depn_pct":                   0.15,
    "current_tax_rate":           0.20,
    "deferred_tax_rate":          0.02,
    "trading_income_annual":      0.0,
    "other_income_annual":        0.0,
    # Benchmarking
    "peer_lei_list":              None,
})
```

**Step 2: Initialise new states before loop**

```python
from modules.calculation.state import DTAState, OCIState, EquityBridgeState
from modules.calculation.capital import (
    calculate_dta_state, calculate_oci, calculate_equity_bridge, calculate_payout
)
from modules.calculation.bridges import (
    calculate_pat_bridge, calculate_capital_waterfall,
    calculate_cor_bridge, calculate_fee_bridge
)

# Initialise DTA/DTC
prior_dta = DTAState(
    period=base_period,
    dta_regular=float(port_cfg.get("dta_regular_opening", 0.0)),
    dtc_stock_opening=float(port_cfg.get("dtc_stock_opening", 0.0)),
)
prior_equity = base.equity
shares_outstanding = float(port_cfg.get("shares_outstanding", 0.0))
```

**Step 3: Per-quarter loop additions**

Within the loop, after computing `pnl`, `capital`, `payout` etc.:

```python
# OCI
rate_delta_q = rate_env.policy_rate - prior_rate
oci = calculate_oci(
    pnl_net_profit=pnl.net_profit,
    period=period,
    bond_revaluation_sensitivity=float(port_cfg.get("bond_revaluation_sensitivity", 0.0)),
    rate_delta_q=rate_delta_q,
    hedge_reserve_annual=float(port_cfg.get("hedge_reserve_annual", 0.0)),
    pension_actuarial_annual=float(port_cfg.get("pension_actuarial_annual", 0.0)),
)

# Payout (computed before capital to inform DTC amortization)
payout_assumptions = PayoutAssumptions(
    cet1_target=float(port_cfg.get("cet1_target", 0.15)),
    regular_cash_dividend_pct=float(port_cfg.get("regular_cash_dividend_pct", 0.40)),
    buyback_pct=float(port_cfg.get("buyback_pct", 0.20)),
    extraordinary_payout_eur=float(port_cfg.get("extraordinary_payout_eur", 0.0)),
    extraordinary_quarter=int(port_cfg.get("extraordinary_quarter", 0)),
)
payout = calculate_payout(pnl, prior_cap, period, i+1,
    rwa=prior_cap.rwa_total, assumptions=payout_assumptions,
    prior_shares=shares_outstanding)

# DTA/DTC
dta_state = calculate_dta_state(
    prior_dta, period, payout,
    cet1_capital=prior_cap.cet1_capital,
    dtc_statutory_schedule=port_cfg.get("dtc_statutory_schedule"),
    dtc_distribution_factor=float(port_cfg.get("dtc_distribution_factor", 0.29)),
)

# Capital (now receives payout + dta_state)
capital, cap_buffers, mrel_view = calculate_capital(
    prior_cap, pnl, bs, period, payout, dta_state,
    goodwill=float(port_cfg.get("goodwill", 0.0)),
    other_intangibles=float(port_cfg.get("other_intangibles", 0.0)),
    sa_rwa_estimate=float(port_cfg.get("sa_rwa_estimate", 0.0)),
    at1_coupon_rate=float(port_cfg.get("at1_coupon_rate", 0.06)),
    shares_outstanding=shares_outstanding,
    p2r=float(port_cfg.get("p2r", 0.015)),
    snp_eligible=float(port_cfg.get("snp_eligible", 0.0)),
    mrel_req_pct=float(port_cfg.get("mrel_req_pct", 0.0)),
)

# Equity bridge
eq_bridge = calculate_equity_bridge(
    prior_equity=prior_equity,
    tci=oci.total_comprehensive_income,
    payout=payout,
    at1_coupon_q=capital.at1_coupons_q,
    capital_actions_q=0.0,
    dtc_cet1_addon=dta_state.dtc_cet1_addon,
    closing_equity=bs.equity,
    period=period,
)

# All bridges
capital_wf = calculate_capital_waterfall(prior_cap, capital, pnl, payout, dta_state, period)
pat_bridge  = calculate_pat_bridge(prior_pnl, pnl)
fee_bridge  = calculate_fee_bridge(prior_pnl, pnl)
cor_bridge  = calculate_cor_bridge(
    prior_cor=getattr(prior_pf, 'cost_of_risk', 0.0) if i > 0 else 0.0,
    curr_cor=pnl.ecl_charge * 4 / bs.loans_gross if bs.loans_gross > 0 else 0.0,
    prior_aq=prior_aq_state, curr_aq=aq, prior_bs=prior_bs, curr_bs=bs
)

# Loan book gross bridge
repayment_rate = float(port_cfg.get("loan_repayment_rate_annual", 0.15))
originations = prior_bs.loans_gross * float(port_cfg.get("loan_growth_q", 0.01)) + prior_bs.loans_gross * repayment_rate / 4
repayments   = prior_bs.loans_gross * repayment_rate / 4
loan_book_bridge = {
    "opening_gross": prior_bs.loans_gross,
    "originations": originations,
    "repayments": -repayments,
    "write_offs": -aq.written_off,
    "fx_other": 0.0,
    "closing_gross": bs.loans_gross,
    "check": bs.loans_gross - (prior_bs.loans_gross + originations - repayments - aq.written_off),
}

# New hot-path scalars
total_deposits = funding.retail_deposits + funding.corporate_deposits
ldr = bs.loans_net / total_deposits if total_deposits > 0 else 0.0
nii_ann = pnl.nii * 4
fee_tot = getattr(pnl.fee_detail, 'total', pnl.fee_income_net) if hasattr(pnl, 'fee_detail') else pnl.fee_income_net
trd_inc = getattr(pnl, 'trading_income', 0.0)
toi_ann = pnl.total_operating_income * 4
nir = (fee_tot * 4 + trd_inc * 4) / toi_ann if toi_ann > 0 else 0.0
ecl_total_q = ecl.ecl_total + getattr(ecl, 'obs_ecl_provision', 0.0)
npl_g = aq.npl_gross
tangible_eq = capital.tangible_equity if hasattr(capital, 'tangible_equity') else bs.equity
texas = npl_g / (tangible_eq + ecl_total_q) if (tangible_eq + ecl_total_q) > 0 else 0.0
ppp_ann = pnl.pre_provision_profit * 4
breakeven_cor = ppp_ann / bs.loans_gross * 10000 if bs.loans_gross > 0 else 0.0
total_payout_q = payout.total_payout
retained_q = pnl.net_profit - total_payout_q
cap_gen_bps = (retained_q * 4) / capital.rwa_total * 10000 if capital.rwa_total > 0 else 0.0
ni_income_pct = (fee_tot + trd_inc) / (nii_ann / 4) if nii_ann > 0 else 0.0
s2_cov = ecl.ecl_stage2 / aq.stage2_gross if aq.stage2_gross > 0 else 0.0

# NII sensitivity (set by calculate_pnl)
nii_sens = getattr(pnl, '_nii_sensitivity', {})

# Update prior_equity
prior_equity = bs.equity

# Assemble ProjectedFinancials
pf = ProjectedFinancials(
    ...
    # New hot-path scalars
    ldr=ldr, nir=nir, texas_ratio=texas,
    breakeven_cor_bps=breakeven_cor, capital_gen_rate_bps=cap_gen_bps,
    non_interest_income_pct=ni_income_pct, stage2_coverage=s2_cov,
    rote=capital.rote,
    # Updated/new blobs
    capital_detail={
        **_to_dict(capital),
        "buffers": _to_dict(cap_buffers),
        "mrel": _to_dict(mrel_view),
        "payout": _to_dict(payout),
        "waterfall": capital_wf.to_dict(),
        "dta": _to_dict(dta_state),
    },
    pnl_detail={
        **_to_dict(pnl),
        "nii_sensitivity": nii_sens,
    },
    balance_sheet_detail={
        "before": _to_dict(prior_bs),
        "after":  _to_dict(bs),
        "deposit_mix": _to_dict(deposit_mix),
        "loan_book_bridge": loan_book_bridge,
    },
    oci_detail=_to_dict(oci),
    equity_bridge=_to_dict(eq_bridge),
    dta_detail=_to_dict(dta_state),
    nii_sensitivity=nii_sens,
    bridges={
        "pat":           pat_bridge.to_dict(),
        "nii":           nii_bridge.to_dict(),
        "cet1_waterfall": capital_wf.to_dict(),
        "cor":           cor_bridge.to_dict(),
        "fees":          fee_bridge.to_dict(),
        "roe":           roe_bridge.to_dict(),
        "equity":        _to_dict(eq_bridge),
    },
)
```

**Step 4: Track `prior_aq_state` in loop**

Add `prior_aq_state = aq` at end of loop alongside other `prior_*` assignments.

---

## Task 7: Create `modules/rating/benchmarking.py`

**Files:**
- Create: `modules/rating/__init__.py`
- Create: `modules/rating/benchmarking.py`

**Full implementation:**

```python
"""
modules/rating/benchmarking.py — Peer benchmarking module.

Compares subject bank's base year metrics against a user-selectable peer group.
Default peer group: same country as subject bank (from banks table).

Output: BenchmarkReport with per-metric BenchmarkMetric (percentile + distribution).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

log = logging.getLogger(__name__)


@dataclass
class BenchmarkMetric:
    metric_name: str
    subject_value: float
    peer_count: int
    peer_p10: float = 0.0
    peer_p25: float = 0.0
    peer_median: float = 0.0
    peer_p75: float = 0.0
    peer_p90: float = 0.0
    subject_percentile: float = 0.0
    signal: str = "UNKNOWN"   # TOP_QUARTILE|ABOVE_MEDIAN|BELOW_MEDIAN|BOTTOM_QUARTILE|BOTTOM_DECILE


@dataclass
class BenchmarkReport:
    subject_bank_lei: str
    subject_bank_name: str
    peer_group_leis: list
    peer_count: int
    base_year_period: date
    metrics: dict = field(default_factory=dict)
    generated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["generated_at"] = self.generated_at.isoformat()
        d["base_year_period"] = self.base_year_period.isoformat()
        return d


def _signal(percentile: float) -> str:
    if percentile >= 75: return "TOP_QUARTILE"
    if percentile >= 50: return "ABOVE_MEDIAN"
    if percentile >= 25: return "BELOW_MEDIAN"
    if percentile >= 10: return "BOTTOM_QUARTILE"
    return "BOTTOM_DECILE"


def _make_metric(name: str, subject: float, peer_values: list[float]) -> BenchmarkMetric:
    vals = [v for v in peer_values if v is not None and not np.isnan(v) and v > -9999]
    if not vals:
        return BenchmarkMetric(metric_name=name, subject_value=subject, peer_count=0, signal="NO_PEERS")
    arr = np.array(vals, dtype=float)
    pct = float(np.mean(arr <= subject) * 100)
    return BenchmarkMetric(
        metric_name=name, subject_value=subject, peer_count=len(arr),
        peer_p10=float(np.percentile(arr, 10)),
        peer_p25=float(np.percentile(arr, 25)),
        peer_median=float(np.percentile(arr, 50)),
        peer_p75=float(np.percentile(arr, 75)),
        peer_p90=float(np.percentile(arr, 90)),
        subject_percentile=pct,
        signal=_signal(pct),
    )


def _extract_peer_metrics(db: "Session", bank_lei: str) -> dict[str, float]:
    """Extract key base-year metrics for one bank from DB."""
    from modules.calculation.state import BaseYearExtractor
    try:
        byx = BaseYearExtractor(db, bank_lei=bank_lei)
        base = byx.extract()
        if base.total_assets < 100:   # filter out near-empty rows
            return {}
        metrics = {
            "cet1_ratio":          base.cet1_ratio,
            "total_capital_ratio": base.total_capital_ratio,
            "leverage_ratio":      base.leverage_ratio,
            "nim":                 base.nim,
            "roe":                 base.roe,
            "cir":                 base.cir,
            "npl_ratio":           base.npl_ratio,
            "ldr":                 base.loans_ac / base.deposits_and_debt if base.deposits_and_debt > 0 else 0.0,
            "fee_ratio":           base.fee_income_net / base.nii if base.nii > 0 else 0.0,
            "ecl_charge_ratio":    base.ecl_charge / base.loans_ac if base.loans_ac > 0 else 0.0,
        }
        return metrics
    except Exception as e:
        log.debug("Failed to extract metrics for %s: %s", bank_lei, e)
        return {}


def run_benchmarking(
    plan,
    db: "Session",
    peer_lei_list: list[str] | None = None,
) -> BenchmarkReport:
    """
    Compute benchmark report for plan's subject bank vs peer group.

    peer_lei_list: if None, uses country-filtered peer group from banks table.
    """
    from db.models import Bank

    subject_bank = plan.bank
    subject_lei = subject_bank.lei or ""
    subject_country = subject_bank.country

    # Resolve peer group
    if peer_lei_list is not None:
        peers = peer_lei_list
    else:
        peer_banks = (db.query(Bank)
                      .filter(Bank.country == subject_country,
                              Bank.lei != subject_lei)
                      .all())
        peers = [b.lei for b in peer_banks if b.lei]

    log.info("Benchmarking %s vs %d peers (country=%s)", subject_bank.name, len(peers), subject_country)

    # Extract subject metrics
    subject_metrics = _extract_peer_metrics(db, subject_lei)
    if not subject_metrics:
        log.warning("Could not extract base year metrics for subject bank %s", subject_lei)

    # Extract peer metrics
    peer_data: dict[str, dict] = {}
    for lei in peers:
        m = _extract_peer_metrics(db, lei)
        if m:
            peer_data[lei] = m

    # Build benchmark metrics
    metric_names = [
        "cet1_ratio", "total_capital_ratio", "leverage_ratio",
        "nim", "roe", "cir",
        "npl_ratio", "ldr", "fee_ratio", "ecl_charge_ratio",
    ]
    metrics = {}
    for name in metric_names:
        subject_val = subject_metrics.get(name, 0.0)
        peer_vals = [pd[name] for pd in peer_data.values() if name in pd]
        metrics[name] = _make_metric(name, subject_val, peer_vals)

    # Determine base year period (most recent period in subject bank's snapshot)
    from db.models import BaseYearSnapshot
    latest = (db.query(BaseYearSnapshot.period)
               .filter(BaseYearSnapshot.bank_lei == subject_lei)
               .order_by(BaseYearSnapshot.period.desc())
               .first())
    base_period = latest[0] if latest else date.today()

    return BenchmarkReport(
        subject_bank_lei=subject_lei,
        subject_bank_name=subject_bank.name,
        peer_group_leis=peers,
        peer_count=len(peer_data),
        base_year_period=base_period,
        metrics=metrics,
    )


def save_benchmark_run(plan, report: BenchmarkReport, db: "Session") -> None:
    """Persist BenchmarkReport to benchmark_runs table."""
    from db.models import BenchmarkRun
    run = BenchmarkRun(
        plan_id=plan.id,
        peer_group_leis=report.peer_group_leis,
        peer_count=report.peer_count,
        base_year_period=report.base_year_period,
        results=report.to_dict(),
    )
    db.add(run)
    db.flush()
    log.info("Saved BenchmarkRun id=%s for plan_id=%s", run.id, plan.id)
```

**Verification:**
```python
PYTHONIOENCODING=utf-8 .venv/Scripts/python -c "
from db.engine import get_session
from db.models import Bank, Plan
DB_PATH = 'data/processed/bbirr.db'
Session = get_session(DB_PATH)
db = Session()

from modules.rating.benchmarking import run_benchmarking, BenchmarkReport
nbg = db.query(Bank).filter(Bank.lei == '5UMCZOEYKCVFAW8ZLO05').first()
plan = Plan(bank_id=nbg.id, name='Benchmark Test', horizon_years=5, version=1)
plan.bank = nbg
report = run_benchmarking(plan, db, peer_lei_list=None)
print(f'Peers found: {report.peer_count}')
print(f'Metrics computed: {list(report.metrics.keys())}')
for name, m in report.metrics.items():
    print(f'  {name:30s}: {m.subject_value:.3f}  pct={m.subject_percentile:.0f}th  [{m.signal}]')
db.rollback()
print('Benchmarking OK')
"
```

---

## Task 8: Full engine integration test

**Files:** (no changes — verification only)

**Full verification:**
```python
PYTHONIOENCODING=utf-8 .venv/Scripts/python -c "
import logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
from db.engine import get_session
from db.models import Bank, Plan
DB_PATH = 'data/processed/bbirr.db'
Session = get_session(DB_PATH)
db = Session()

nbg = db.query(Bank).filter(Bank.lei == '5UMCZOEYKCVFAW8ZLO05').first()
plan = Plan(
    bank_id=nbg.id, name='Full Enriched Test', horizon_years=5, version=1,
    portfolio_allocations={
        'loan_growth_q': 0.01,
        'dtc_stock_opening': 3000.0,
        'dtc_distribution_factor': 0.29,
        'dta_regular_opening': 500.0,
        'regular_cash_dividend_pct': 0.40,
        'buyback_pct': 0.20,
        'at1_coupon_rate': 0.06,
        'cet1_target': 0.15,
        'p2r': 0.015,
        'mrel_req_pct': 0.214,
        'shares_outstanding': 1300.0,
        'fee_weights': {'retail':0.50,'corporate':0.30,'asset_mgmt':0.10,'treasury':0.10},
    }
)
db.add(plan); db.flush()

from modules.calculation.engine import run_projection
results = run_projection(plan, None, db)
print(f'Generated {len(results)} quarters')

pf = results[0]
print()
print('=== Key scalars (Q1) ===')
print(f'CET1 ratio:   {pf.cet1_ratio:.2%}')
print(f'RoTE:         {pf.rote:.2%}')
print(f'LDR:          {pf.ldr:.2f}')
print(f'Texas ratio:  {pf.texas_ratio:.2f}')
print(f'Cap gen (bps):{pf.capital_gen_rate_bps:.0f}')
print(f'Break-even CoR:{pf.breakeven_cor_bps:.0f}bps')

print()
print('=== Blob keys ===')
print(f'capital_detail:   {sorted(pf.capital_detail.keys())}')
print(f'bridges:          {sorted(pf.bridges.keys())}')
print(f'balance_sheet_detail: {sorted(pf.balance_sheet_detail.keys())}')

assert 'waterfall' in pf.capital_detail
assert 'dta' in pf.capital_detail
assert 'mrel' in pf.capital_detail
assert 'buffers' in pf.capital_detail
assert 'payout' in pf.capital_detail
assert 'pat' in pf.bridges
assert 'cet1_waterfall' in pf.bridges
assert 'cor' in pf.bridges
assert 'fees' in pf.bridges
assert 'equity' in pf.bridges
assert 'before' in pf.balance_sheet_detail
assert 'loan_book_bridge' in pf.balance_sheet_detail
assert pf.equity_bridge is not None
assert pf.oci_detail is not None

print()
print('=== 5-year summary ===')
print(f'{\"Period\":<14} {\"CET1%\":>7} {\"RoTE\":>7} {\"LDR\":>6} {\"DTC stk\":>10} {\"EPS\":>8} {\"DPS\":>8}')
print('-' * 62)
for r in results[::4]:  # annual
    dtc = r.capital_detail.get('dta', {}).get('dtc_stock_closing', 0.0)
    eps = r.capital_detail.get('payout', {}).get('eps_annual', 0.0)
    dps = r.capital_detail.get('payout', {}).get('dps_annual', 0.0)
    print(f'{str(r.period):<14} {r.cet1_ratio:.1%} {r.rote:.1%} {r.ldr:.2f} {dtc:>10,.0f} {eps:>8.4f} {dps:>8.4f}')

db.rollback()
print()
print('FULL INTEGRATION TEST PASSED')
"
```

Expected: 20 quarters, all assertions pass, DTC stock declining quarter-on-quarter, CET1 add-on visible in capital waterfall.

---

## Execution order

```
Task 1 → Task 2 → Task 3 → Task 4 → Task 5 → Task 6 → Task 7 → Task 8
  DB        State    Capital  Bridges   PnL      Engine   Bench   Verify
```

Each task must complete and its verification must pass before starting the next.
