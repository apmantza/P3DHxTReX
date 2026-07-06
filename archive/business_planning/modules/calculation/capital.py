"""
modules/calculation/capital.py — Capital accumulation, DTA/DTC, payout, buffers, MREL.

Returns a tuple (CapitalState, CapitalBuffers, MrelView) from calculate_capital().
Amounts in EUR mn; ratios as decimals.

Defaults loaded from config/plan_defaults.yaml at import time.
"""
from __future__ import annotations

import logging
from datetime import date

from modules.calculation.state import (
    BalanceSheetState, CapitalBuffers, CapitalState,
    DTAState, EquityBridgeState, MrelView, OCIState,
    PayoutAssumptions, PayoutState, PnLState,
)

log = logging.getLogger(__name__)


def _load_capital_reg() -> dict:
    """Load capital regulatory defaults from config."""
    try:
        from config.loader import load_config as _load
        return _load("capital_regulatory")
    except Exception as exc:
        log.warning("Could not load capital_regulatory from YAML: %s", exc)
        return {}


_CAP_REG = _load_capital_reg()

MIN_CET1_RATIO = _CAP_REG.get("min_cet1_ratio", 0.045)
MDA_BUFFER = _CAP_REG.get("mda_buffer", 0.025)
MIN_T1_RATIO = _CAP_REG.get("min_t1_ratio", 0.060)
MIN_TOTAL_CAP = _CAP_REG.get("min_total_cap_ratio", 0.080)


# ---------------------------------------------------------------------------
# DTA / DTC
# ---------------------------------------------------------------------------

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
      - dtc_distribution_factor × total_distributions_q
    """
    current_year = period.year

    # Guard: no DTC amortization if there is no DTC stock
    if prior.dtc_stock_opening <= 0:
        statutory_q = 0.0
        distribution_q = 0.0
        total_amort_q = 0.0
        dtc_closing = 0.0
        cet1_addon = 0.0
    else:
        # Statutory amortization (annual ÷ 4 for quarterly)
        if dtc_statutory_schedule and (current_year - base_year) < len(dtc_statutory_schedule):
            annual_statutory = dtc_statutory_schedule[current_year - base_year]
        else:
            years_remaining = max(1, amortization_end_year - current_year)
            annual_statutory = prior.dtc_stock_opening / years_remaining

        statutory_q = annual_statutory / 4

        # Distribution-linked amortization (Law 4172/2013: 29% of distributions)
        total_dist_q = (payout.regular_cash_dividend + payout.buyback + payout.extraordinary_payout)
        distribution_q = total_dist_q * dtc_distribution_factor

        total_amort_q = statutory_q + distribution_q
        # Cap amortization at remaining stock
        total_amort_q = min(total_amort_q, prior.dtc_stock_opening)
        dtc_closing = max(0.0, prior.dtc_stock_opening - total_amort_q)

        # DTC amortization REDUCES the DTC asset (which was CET1-qualifying).
        # The amortized portion becomes a liability to the Greek state.
        # Net CET1 impact = negative (loss of CET1-supporting asset).
        cet1_addon = -total_amort_q

    # Regular DTA threshold
    threshold = cet1_capital * 0.10
    dta_above = max(0.0, prior.dta_regular - threshold)
    dta_below = prior.dta_regular - dta_above

    total_bs = prior.dta_regular + dtc_closing
    rwa_contribution = dtc_closing * 1.00 + dta_below * 2.50

    return DTAState(
        period=period,
        dta_regular=prior.dta_regular,
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


# ---------------------------------------------------------------------------
# OCI (stub)
# ---------------------------------------------------------------------------

def calculate_oci(
    pnl_net_profit: float,
    period: date,
    *,
    bond_revaluation_sensitivity: float = 0.0,
    rate_delta_q: float = 0.0,
    hedge_reserve_annual: float = 0.0,
    pension_actuarial_annual: float = 0.0,
    fx_translation_q: float = 0.0,
) -> OCIState:
    """Compute OCI for one quarter (stub implementation)."""
    bond_reval = bond_revaluation_sensitivity * (rate_delta_q / 0.01) if rate_delta_q != 0.0 else 0.0
    hedge_q = hedge_reserve_annual / 4
    pension_q = pension_actuarial_annual / 4
    total_oci = bond_reval + hedge_q + pension_q + fx_translation_q
    return OCIState(
        period=period,
        bond_revaluation=bond_reval,
        hedge_reserve_change=hedge_q,
        pension_actuarial=pension_q,
        fx_translation=fx_translation_q,
        total_oci=total_oci,
        total_comprehensive_income=pnl_net_profit + total_oci,
    )


# ---------------------------------------------------------------------------
# Equity bridge
# ---------------------------------------------------------------------------

def calculate_equity_bridge(
    prior_equity: float,
    tci: float,
    payout: PayoutState,
    at1_coupon_q: float,
    capital_actions_q: float,
    dtc_cet1_addon: float,
    period: date,
    bs_equity: float = 0.0,
) -> EquityBridgeState:
    """Reconcile IFRS book equity quarter-over-quarter.

    closing_equity is DERIVED from the waterfall (not imposed from the BS).
    The `check` field shows the gap vs the balance-sheet equity constraint.
    """
    closing_equity = (
        prior_equity + tci
        - at1_coupon_q
        - payout.regular_cash_dividend
        - payout.buyback
        - payout.extraordinary_payout
        + capital_actions_q
        + dtc_cet1_addon
    )
    # check = discrepancy vs BS equity (the regulatory constraint);
    # non-zero expected due to one-period lag + regulatory ≠ IFRS definition.
    check = bs_equity - closing_equity if bs_equity > 0 else 0.0
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
        other=0.0,
        closing_equity=closing_equity,
        check=check,
    )


# ---------------------------------------------------------------------------
# Payout
# ---------------------------------------------------------------------------

def calculate_payout(
    pnl: PnLState,
    prior_cap: CapitalState,
    period: date,
    quarter_index: int,
    *,
    rwa: float,
    assumptions: PayoutAssumptions,
    prior_shares: float,
) -> PayoutState:
    """
    Compute quarterly payout (cash dividends + buybacks + extraordinary).

    Max distributable = max(0, CET1_ratio - cet1_target) × RWA + PAT × max_payout_pct
    Actual payout = min(max_distributable, PAT × (div_pct + bb_pct))
    """
    pat_q = pnl.net_profit
    surplus_cet1 = max(0.0, prior_cap.cet1_ratio - assumptions.cet1_target) * rwa
    max_from_surplus = surplus_cet1
    max_from_pat = pat_q * (assumptions.regular_cash_dividend_pct + assumptions.buyback_pct)
    max_distributable = max_from_surplus + max_from_pat

    # Regular distributions
    regular_div = pat_q * assumptions.regular_cash_dividend_pct
    buyback = pat_q * assumptions.buyback_pct
    regular_total = regular_div + buyback

    # Cap to max distributable
    if regular_total > max_distributable and max_distributable > 0:
        scale = max_distributable / regular_total
        regular_div *= scale
        buyback *= scale

    # Extraordinary payout (only in specified quarter)
    extraordinary = 0.0
    if assumptions.extraordinary_quarter > 0 and quarter_index == assumptions.extraordinary_quarter:
        avail = max(0.0, max_distributable - regular_div - buyback)
        extraordinary = min(assumptions.extraordinary_payout_eur, avail)

    total_payout = regular_div + buyback + extraordinary
    payout_ratio = total_payout / pat_q if pat_q > 0 else 0.0

    shares = prior_shares
    eps = (pat_q * 4) / shares if shares > 0 else 0.0
    dps = (regular_div * 4) / shares if shares > 0 else 0.0

    return PayoutState(
        period=period,
        pat_quarterly=pat_q,
        max_distributable_eur=max_distributable,
        regular_cash_dividend=regular_div,
        buyback=buyback,
        extraordinary_payout=extraordinary,
        total_payout=total_payout,
        payout_ratio=payout_ratio,
        eps_annual=eps,
        dps_annual=dps,
        shares_outstanding=shares,
        shares_remaining=shares,
    )


# ---------------------------------------------------------------------------
# Main capital calculation
# ---------------------------------------------------------------------------

def calculate_capital(
    prior: CapitalState,
    pnl: PnLState,
    bs: BalanceSheetState,
    period: date,
    payout: PayoutState,
    dta_state: DTAState | None = None,
    *,
    capital_actions_other: float = 0.0,
    rwa_credit_density: float | None = None,
    prior_loans_gross: float | None = None,
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
) -> tuple:
    """
    Project capital one quarter forward.

    Returns (CapitalState, CapitalBuffers, MrelView).
    """
    at1 = at1_capital if at1_capital is not None else prior.at1_capital
    tier2 = tier2_capital if tier2_capital is not None else prior.tier2_capital

    # AT1 coupon (charged to equity, not P&L)
    at1_coupon_q = at1 * at1_coupon_rate / 4

    # DTC CET1 add-on
    dtc_addon = dta_state.dtc_cet1_addon if dta_state else 0.0

    # CET1 = prior + retained (net profit minus total payout) + capital actions + DTC add-on
    # Note: AT1 coupons reduce equity but in our simplified model CET1 is the focus;
    # AT1 coupons are tracked in the waterfall separately.
    retained = pnl.net_profit - payout.total_payout - at1_coupon_q
    closing_cet1 = prior.cet1_capital + retained + capital_actions_other + dtc_addon

    own_funds = closing_cet1 + at1 + tier2

    # RWA — credit risk scales with loan book at constant density.
    # Pass prior_bs.loans_gross via the new parameter to compute density correctly.
    if rwa_credit_density is None:
        if prior_loans_gross and prior_loans_gross > 0 and prior.rwa_credit > 0:
            rwa_credit_density = prior.rwa_credit / prior_loans_gross
        else:
            rwa_credit_density = 0.70
    rwa_credit = bs.loans_gross * rwa_credit_density

    # Note: DTA/DTC RWA is already embedded in the base-year credit RWA figure
    # (TrEx item 2520201 is the reported total credit RWA including DTA at 250%/100%).
    # We do NOT add dta_rwa_contribution on top — that would double-count.
    # As DTC amortizes, the density computed from prior.rwa_credit / prior_loans
    # will naturally drift down (since credit RWA shrinks relative to loans).
    # TODO: for more precision, subtract the DTC amortization × RW from rwa_credit.
    rwa_market = prior.rwa_market
    rwa_op = prior.rwa_operational
    rwa_total = rwa_credit + rwa_market + rwa_op

    # Ratios
    cet1_ratio = closing_cet1 / rwa_total if rwa_total > 0 else 0.0
    t1_ratio = (closing_cet1 + at1) / rwa_total if rwa_total > 0 else 0.0
    total_ratio = own_funds / rwa_total if rwa_total > 0 else 0.0
    leverage = closing_cet1 / bs.total_assets if bs.total_assets > 0 else 0.0

    # MDA headroom
    mda_trigger = MIN_CET1_RATIO + MDA_BUFFER + p2r + ccyb + osii
    cet1_surplus = (cet1_ratio - mda_trigger) * rwa_total

    # RoTE
    tangible_equity = bs.equity - goodwill - other_intangibles
    rote = (pnl.net_profit * 4) / tangible_equity if tangible_equity > 0 else 0.0
    tangible_bvps = tangible_equity / shares_outstanding if shares_outstanding > 0 else 0.0

    # CRR3 output floor (72.5% of SA RWA)
    if sa_rwa_estimate > 0:
        output_floor_rwa = max(rwa_total, 0.725 * sa_rwa_estimate)
        output_floor_binding = output_floor_rwa > rwa_total
        output_floor_cet1 = closing_cet1 / output_floor_rwa if output_floor_rwa > 0 else 0.0
    else:
        output_floor_rwa = rwa_total
        output_floor_binding = False
        output_floor_cet1 = cet1_ratio

    # RWA growth drag (for waterfall)
    rwa_drag = (rwa_total - prior.rwa_total) * prior.cet1_ratio

    cap_state = CapitalState(
        period=period,
        cet1_capital=closing_cet1,
        at1_capital=at1,
        tier2_capital=tier2,
        own_funds=own_funds,
        rwa_credit=rwa_credit,
        rwa_market=rwa_market,
        rwa_operational=rwa_op,
        rwa_total=rwa_total,
        cet1_ratio=cet1_ratio,
        t1_ratio=t1_ratio,
        total_capital_ratio=total_ratio,
        leverage_ratio=leverage,
        cet1_surplus=cet1_surplus,
        retained_earnings_delta=retained,
        dividends_paid=payout.total_payout,
        opening_cet1_eur=prior.cet1_capital,
        closing_cet1_eur=closing_cet1,
        at1_coupons_q=at1_coupon_q,
        buybacks_q=payout.buyback,
        extraordinary_payout_q=payout.extraordinary_payout,
        capital_actions_q=capital_actions_other,
        rwa_growth_drag=rwa_drag,
        dtc_cet1_addon=dtc_addon,
        goodwill=goodwill,
        other_intangibles=other_intangibles,
        tangible_equity=tangible_equity,
        rote=rote,
        tangible_bvps=tangible_bvps,
        sa_rwa_estimate=sa_rwa_estimate,
        output_floor_rwa=output_floor_rwa,
        output_floor_binding=output_floor_binding,
        output_floor_cet1_ratio=output_floor_cet1,
    )

    # Capital buffers
    headroom_pct = cet1_ratio - mda_trigger
    headroom_eur = headroom_pct * rwa_total
    cap_buffers = CapitalBuffers(
        p1_minimum=MIN_CET1_RATIO,
        ccb=MDA_BUFFER,
        p2r=p2r,
        ccyb=ccyb,
        osii=osii,
        mda_trigger=mda_trigger,
        current_cet1=cet1_ratio,
        headroom_pct=headroom_pct,
        headroom_eur=headroom_eur,
        max_distributable=max(0.0, headroom_eur),
    )

    # MREL view
    total_mrel_stack = own_funds + snp_eligible
    total_mrel_pct = total_mrel_stack / rwa_total if rwa_total > 0 else 0.0
    mrel_req_eur = mrel_req_pct * rwa_total
    mrel_headroom_eur = total_mrel_stack - mrel_req_eur
    mrel_headroom_pct = mrel_headroom_eur / rwa_total if rwa_total > 0 else 0.0
    mrel_mda = min(headroom_eur, mrel_headroom_eur)
    mrel_view = MrelView(
        requirement_pct_trea=mrel_req_pct,
        own_funds=own_funds,
        at1=at1,
        tier2=tier2,
        snp_eligible=snp_eligible,
        total_mrel_stack_eur=total_mrel_stack,
        total_mrel_stack_pct=total_mrel_pct,
        mrel_headroom_eur=mrel_headroom_eur,
        mrel_headroom_pct=mrel_headroom_pct,
        mda_distributable_eur=headroom_eur,
        mrel_mda_eur=mrel_mda,
    )

    return cap_state, cap_buffers, mrel_view


def capital_from_base(base_year, period: date) -> CapitalState:
    """Initialise CapitalState from a BaseYear snapshot."""
    cet1 = base_year.cet1_capital
    own_funds = base_year.own_funds
    # Use actual AT1/T2 if extracted, else estimate from own_funds − CET1
    if base_year.at1_capital > 0 or base_year.tier2_capital > 0:
        at1 = max(0.0, base_year.at1_capital)
        tier2 = max(0.0, base_year.tier2_capital)
    else:
        at1 = max(0.0, own_funds - cet1) * 0.4
        tier2 = max(0.0, own_funds - cet1) * 0.6

    mda_trigger = MIN_CET1_RATIO + MDA_BUFFER + 0.015
    rwa_total = base_year.rwa_total if base_year.rwa_total > 0 else 1.0
    cet1_surplus = (base_year.cet1_ratio - mda_trigger) * rwa_total

    return CapitalState(
        period=period,
        cet1_capital=cet1,
        at1_capital=at1,
        tier2_capital=tier2,
        own_funds=own_funds,
        rwa_credit=base_year.rwa_credit,
        rwa_market=base_year.rwa_market,
        rwa_operational=base_year.rwa_operational,
        rwa_total=rwa_total,
        cet1_ratio=base_year.cet1_ratio,
        t1_ratio=(cet1 + at1) / rwa_total if rwa_total > 0 else 0.0,
        total_capital_ratio=base_year.total_capital_ratio,
        leverage_ratio=base_year.leverage_ratio,
        cet1_surplus=cet1_surplus,
        retained_earnings_delta=0.0,
        dividends_paid=0.0,
        opening_cet1_eur=cet1,
        closing_cet1_eur=cet1,
        # Seed intangibles from base year extraction
        other_intangibles=base_year.intangibles,
    )
