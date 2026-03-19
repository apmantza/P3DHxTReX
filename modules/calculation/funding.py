"""
modules/calculation/funding.py — Funding curve stack + deposit pass-through.

Models:
- Retail and corporate deposit repricing (beta model)
- Wholesale funding costs (OIS/swap spread model)
- Central bank funding (TLTRO / MRO)
- Blended cost of funds

Amounts in EUR mn; rates as decimals (annualised).

Defaults loaded from config/plan_defaults.yaml at import time.
"""
from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date

from modules.calculation.state import BalanceSheetState, FundingState, RateEnvironment

log = logging.getLogger(__name__)


def _load_funding_betas() -> dict:
    """Load funding beta defaults from config."""
    try:
        from config.loader import load_config as _load
        return _load("funding_betas")
    except Exception as exc:
        log.warning("Could not load funding_betas from YAML: %s", exc)
        return {}


_FUNDING_BETAS = _load_funding_betas()

RETAIL_BETA = _FUNDING_BETAS.get("retail_beta", 0.30)
CORPORATE_BETA = _FUNDING_BETAS.get("corporate_beta", 0.55)
INTERBANK_BETA = _FUNDING_BETAS.get("interbank_beta", 0.95)
WHOLESALE_BETA = _FUNDING_BETAS.get("wholesale_beta", 0.80)


def apply_deposit_pass_through(
    prior: FundingState,
    rate_env: RateEnvironment,
    prior_rate: float,
    period: date,
    *,
    retail_beta: float = RETAIL_BETA,
    corporate_beta: float = CORPORATE_BETA,
    interbank_beta: float = INTERBANK_BETA,
    # Volume growth
    retail_deposit_growth_q: float = 0.005,
    corporate_deposit_growth_q: float = 0.010,
    wholesale_growth_q: float = 0.0,
) -> FundingState:
    """
    Reprice deposits based on beta × rate change, grow volumes.

    deposit_rate_new = prior_rate + beta × (policy_rate - prior_policy_rate)
    """
    rate_delta = rate_env.policy_rate - prior_rate

    # Repriced deposit rates — beta pass-through on rate change.
    # Back-solve retail/corporate from blended avg to avoid compounding drift.
    # If corporate = retail × 1.2, then:
    #   avg = w_r × retail + w_c × retail × 1.2
    #   retail = avg / (w_r + w_c × 1.2)
    dep_total = prior.retail_deposits + prior.corporate_deposits
    w_r = prior.retail_deposits / dep_total if dep_total > 0 else 0.60
    w_c = prior.corporate_deposits / dep_total if dep_total > 0 else 0.40
    retail_rate_prior    = prior.avg_deposit_rate / (w_r + w_c * 1.2) if (w_r + w_c * 1.2) > 0 else prior.avg_deposit_rate
    corporate_rate_prior = retail_rate_prior * 1.2

    retail_rate    = max(0.0, retail_rate_prior    + retail_beta    * rate_delta)
    corporate_rate = max(0.0, corporate_rate_prior + corporate_beta * rate_delta)

    # Wholesale rates — incremental repricing from prior, NOT absolute swap reset.
    # Back-solve individual instrument rates from blended wholesale average
    # using fixed spread ratios, then reprice with beta × rate_delta.
    # Spread ratios: interbank ~0.95×, covered ~0.85×, senior ~1.10×, sub ~1.50×
    # (normalised so the weighted average reconstructs avg_wholesale_rate)
    wholesale_beta = WHOLESALE_BETA
    ws_base = prior.avg_wholesale_rate
    interbank_rate    = max(0.0, ws_base * 0.95 + interbank_beta * rate_delta)
    covered_bond_rate = max(0.0, ws_base * 0.85 + wholesale_beta * rate_delta)
    senior_unsec_rate = max(0.0, ws_base * 1.10 + wholesale_beta * rate_delta)
    sub_debt_rate     = max(0.0, ws_base * 1.50 + wholesale_beta * rate_delta)
    cb_funding_rate   = max(0.0, rate_env.policy_rate - 0.0025)  # MRO - 25bps

    # Volumes
    retail_dep  = prior.retail_deposits    * (1 + retail_deposit_growth_q)
    corp_dep    = prior.corporate_deposits * (1 + corporate_deposit_growth_q)
    interbank   = prior.interbank_funding  * (1 + wholesale_growth_q)
    covered     = prior.covered_bonds      * (1 + wholesale_growth_q)
    senior      = prior.senior_unsecured   * (1 + wholesale_growth_q)
    cb_fund     = prior.central_bank_funding   # held flat (policy decision)
    sub_debt    = prior.subordinated_debt      # held flat

    total = retail_dep + corp_dep + interbank + covered + senior + cb_fund + sub_debt

    # Blended cost of funds (volume-weighted)
    blended = 0.0
    if total > 0:
        blended = (
            retail_dep    * retail_rate
            + corp_dep    * corporate_rate
            + interbank   * interbank_rate
            + covered     * covered_bond_rate
            + senior      * senior_unsec_rate
            + cb_fund     * cb_funding_rate
            + sub_debt    * sub_debt_rate
        ) / total

    avg_deposit_rate = (
        (retail_dep * retail_rate + corp_dep * corporate_rate)
        / (retail_dep + corp_dep)
        if (retail_dep + corp_dep) > 0 else 0.0
    )
    avg_wholesale_rate = (
        (interbank * interbank_rate + covered * covered_bond_rate
         + senior * senior_unsec_rate + cb_fund * cb_funding_rate
         + sub_debt * sub_debt_rate)
        / (interbank + covered + senior + cb_fund + sub_debt)
        if (interbank + covered + senior + cb_fund + sub_debt) > 0 else 0.0
    )

    return FundingState(
        period=period,
        retail_deposits=retail_dep,
        corporate_deposits=corp_dep,
        interbank_funding=interbank,
        covered_bonds=covered,
        senior_unsecured=senior,
        central_bank_funding=cb_fund,
        subordinated_debt=sub_debt,
        total_funding=total,
        avg_deposit_rate=avg_deposit_rate,
        avg_wholesale_rate=avg_wholesale_rate,
        blended_cost_of_funds=blended,
        deposit_beta=retail_beta,
        # Gap reset each quarter — filled fresh by apply_funding_gap()
        interbank_gap_funding=0.0,
        interbank_gap_rate=0.0,
    )


def apply_funding_gap(
    funding: FundingState,
    gap_eur: float,
    policy_rate: float,
    *,
    gap_spread: float = 0.0010,  # 10bps: DFR + short-term interbank premium
) -> FundingState:
    """
    Fill the balance sheet funding gap with short-term interbank borrowing.

    Gap arises when asset growth outpaces deposit + wholesale growth.
    Rate = DFR + gap_spread (default 10bps ~ ECB corridor overnight).

    Returns updated FundingState with gap reflected in total_funding and
    blended_cost_of_funds.  interbank_gap_funding tracks the gap amount.
    """
    if gap_eur <= 0:
        return replace(funding, interbank_gap_funding=0.0, interbank_gap_rate=0.0)

    gap_rate = max(0.0, policy_rate + gap_spread)
    new_total = funding.total_funding + gap_eur

    # Recompute blended cost (marginal cost of gap at gap_rate)
    new_blended = (
        (funding.blended_cost_of_funds * funding.total_funding + gap_eur * gap_rate)
        / new_total
        if new_total > 0
        else 0.0
    )

    # Recompute avg wholesale rate (gap is interbank-type)
    prior_whl_vol = (
        funding.interbank_funding
        + funding.covered_bonds
        + funding.senior_unsecured
        + funding.central_bank_funding
        + funding.subordinated_debt
    )
    new_whl_vol = prior_whl_vol + gap_eur
    new_wholesale_rate = (
        (funding.avg_wholesale_rate * prior_whl_vol + gap_eur * gap_rate) / new_whl_vol
        if new_whl_vol > 0
        else gap_rate
    )

    return replace(
        funding,
        total_funding=new_total,
        blended_cost_of_funds=new_blended,
        avg_wholesale_rate=new_wholesale_rate,
        interbank_gap_funding=gap_eur,
        interbank_gap_rate=gap_rate,
    )


def funding_from_base(base_year, bs: BalanceSheetState, rate_env: RateEnvironment, period: date) -> FundingState:
    """Initialise FundingState from BaseYear + BalanceSheetState."""
    deposits_total = base_year.deposits_and_debt * 0.70 if base_year.deposits_and_debt else bs.deposits
    retail_dep  = deposits_total * 0.60
    corp_dep    = deposits_total * 0.40
    wholesale   = max(0.0, base_year.deposits_and_debt * 0.30) if base_year.deposits_and_debt else bs.wholesale_funding
    covered     = wholesale * 0.50
    senior      = wholesale * 0.30
    interbank   = wholesale * 0.15
    sub_debt    = wholesale * 0.05
    cb_fund     = 0.0
    total       = retail_dep + corp_dep + covered + senior + interbank + sub_debt

    # Back-solve blended cost from base year interest expense
    blended = (
        base_year.interest_expense / total
        if total > 0 and base_year.interest_expense > 0
        else rate_env.policy_rate * 0.50   # fallback: 50% of policy rate
    )

    # Use actual deposit expense for more accurate deposit rate calibration
    deposits_total_for_rate = retail_dep + corp_dep
    if base_year.deposit_expense > 0 and deposits_total_for_rate > 0:
        implied_deposit_rate = base_year.deposit_expense / deposits_total_for_rate
    else:
        implied_deposit_rate = blended * 0.80

    # Wholesale rate: back-solve residual expense on non-deposit funding
    wholesale_total = covered + senior + interbank + sub_debt
    if base_year.deposit_expense > 0 and wholesale_total > 0:
        residual_expense = max(0.0, base_year.interest_expense - base_year.deposit_expense)
        implied_wholesale_rate = residual_expense / wholesale_total
    else:
        implied_wholesale_rate = blended * 1.30

    return FundingState(
        period=period,
        retail_deposits=retail_dep,
        corporate_deposits=corp_dep,
        interbank_funding=interbank,
        covered_bonds=covered,
        senior_unsecured=senior,
        central_bank_funding=cb_fund,
        subordinated_debt=sub_debt,
        total_funding=total,
        avg_deposit_rate=implied_deposit_rate,
        avg_wholesale_rate=implied_wholesale_rate,
        blended_cost_of_funds=blended,
        deposit_beta=RETAIL_BETA,
    )
