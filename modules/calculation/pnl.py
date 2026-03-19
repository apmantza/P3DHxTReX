"""
modules/calculation/pnl.py — P&L projection for one quarter.

Computes quarterly P&L given:
- Balance sheet state (asset / liability volumes)
- Funding state (liability rates)
- Rate environment (for asset yields)
- Management assumptions (growth, margins, cost ratios)

All income/expense figures are quarterly (EUR mn).

Defaults loaded from config/plan_defaults.yaml at import time.
"""
from __future__ import annotations

import dataclasses
import logging
from datetime import date

from modules.calculation.state import (
    BalanceSheetState,
    FeeDetail,
    FundingState,
    NIIDetail,
    NIISensitivity,
    OpexDetail,
    PnLState,
    RateEnvironment,
    TaxDetail,
)

log = logging.getLogger(__name__)


def _load_repricing_config() -> dict:
    """Load repricing defaults from config."""
    try:
        from config.loader import load_config as _load
        return _load("repricing")
    except Exception as exc:
        log.warning("Could not load repricing config: %s", exc)
        return {}


_REPRICING_CONFIG = _load_repricing_config()
REPRICING_ASSET_PCT = _REPRICING_CONFIG.get("repricing_asset_pct", 0.70)
NII_SHOCK_PARALLEL_BPS = _REPRICING_CONFIG.get("nii_shock_parallel_bps", 100)


def calculate_pnl(
    bs: BalanceSheetState,
    funding: FundingState,
    rate_env: RateEnvironment,
    period: date,
    prior_bs: BalanceSheetState | None = None,
    *,
    loan_yield: float = 0.055,
    bond_yield: float = 0.040,
    fee_growth_q: float = 0.01,
    base_fee_income: float = 0.0,
    trading_income_annual: float = 0.0,
    other_income_annual: float = 0.0,
    admin_expenses_q: float = 0.0,
    depreciation_q: float = 0.0,
    ecl_charge_q: float = 0.0,
    tax_rate: float = 0.22,
    cash_yield_spread: float = 0.002,
    # Opex split (fractions of total opex) — used when prior_opex_detail is None
    personnel_pct: float = 0.60,
    ga_pct: float = 0.25,
    depn_pct: float = 0.15,
    # Current/deferred tax split
    current_tax_rate: float = 0.20,
    deferred_tax_rate: float = 0.02,
    # Fee segment weights (must sum to 1.0) — used when prior_fee_detail is None
    fee_weights: dict | None = None,
    # ---- Volume-driven fee model (per-segment) ----
    # When prior_fee_detail is provided, each segment grows independently.
    prior_fee_detail: FeeDetail | None = None,
    retail_fee_growth_q: float = 0.008,       # ~3.2% annual
    corporate_fee_growth_q: float = 0.008,
    aum: float = 0.0,                          # current AUM (EUR mn); 0 = use growth proxy
    aum_growth_q: float = 0.010,
    mgmt_fee_rate: float = 0.005,             # annual bps on AUM
    treasury_fee_yield: float = 0.0008,       # annual yield on total assets
    # ---- Per-line opex model ----
    # When prior_opex_detail is provided, each line grows independently.
    prior_opex_detail: OpexDetail | None = None,
    personnel_growth_q: float = 0.005,        # ~2% annual
    ga_growth_q: float = 0.003,               # ~1.2% annual
    capex_q: float = 0.0,                     # quarterly capex (EUR mn)
    da_life_years: float = 5.0,               # avg asset life for incremental D&A
) -> PnLState:
    """
    Compute quarterly P&L with enriched opex/fee/tax/NII sub-detail.
    """
    if fee_weights is None:
        fee_weights = {"retail": 0.50, "corporate": 0.30, "asset_mgmt": 0.10, "treasury": 0.10}

    avg_loans = (bs.loans_net + (prior_bs.loans_net if prior_bs else bs.loans_net)) / 2
    avg_bonds = (bs.fvoci_assets + (prior_bs.fvoci_assets if prior_bs else bs.fvoci_assets)) / 2
    avg_cash  = (bs.cash + (prior_bs.cash if prior_bs else bs.cash)) / 2

    eff_cash_yield = (rate_env.policy_rate or rate_env.euribor_3m) + cash_yield_spread

    # Interest income breakdown
    loan_int_q  = avg_loans * loan_yield / 4
    bond_int_q  = avg_bonds * bond_yield / 4
    cash_int_q  = avg_cash  * eff_cash_yield / 4
    interest_income = loan_int_q + bond_int_q + cash_int_q

    # Interest expense
    interest_expense = funding.blended_cost_of_funds * funding.total_funding / 4

    nii = interest_income - interest_expense
    banking_nii = nii  # all banking book in this model

    # NII detail
    nii_detail = NIIDetail(
        banking_book_interest_income=interest_income,
        loan_interest_income=loan_int_q,
        bond_interest_income=bond_int_q,
        cash_interest_income=cash_int_q,
        banking_book_interest_expense=interest_expense,
        banking_book_nii=banking_nii,
        trading_book_nii=0.0,
        total_nii=nii,
    )

    # Fee income — volume-driven per segment when prior_fee_detail is available
    if prior_fee_detail is not None:
        retail_fee = prior_fee_detail.retail * (1 + retail_fee_growth_q)
        corp_fee = prior_fee_detail.corporate * (1 + corporate_fee_growth_q)
        # Asset management: AUM-driven when AUM is known, else growth proxy
        if aum > 0:
            asset_mgmt_fee = aum * mgmt_fee_rate / 4
        else:
            asset_mgmt_fee = prior_fee_detail.asset_mgmt * (1 + aum_growth_q)
        # Treasury: yield on total assets (transactional + markets business)
        treasury_fee = bs.total_assets * treasury_fee_yield / 4
        fee_income = retail_fee + corp_fee + asset_mgmt_fee + treasury_fee
        fee_detail = FeeDetail(
            retail=retail_fee,
            corporate=corp_fee,
            asset_mgmt=asset_mgmt_fee,
            treasury=treasury_fee,
            total=fee_income,
        )
    else:
        # Legacy: flat growth on total fee income, split by weights
        fee_income = base_fee_income * (1 + fee_growth_q) if base_fee_income > 0 else 0.0
        fee_detail = FeeDetail(
            retail=fee_income * fee_weights.get("retail", 0.50),
            corporate=fee_income * fee_weights.get("corporate", 0.30),
            asset_mgmt=fee_income * fee_weights.get("asset_mgmt", 0.10),
            treasury=fee_income * fee_weights.get("treasury", 0.10),
            total=fee_income,
        )

    # Trading and other income (quarterly)
    trading_inc_q = trading_income_annual / 4
    other_inc_q = other_income_annual / 4

    # Total operating income
    total_oi = nii + fee_income + trading_inc_q + other_inc_q

    # Opex — per-line growth when prior_opex_detail is available
    if prior_opex_detail is not None:
        personnel_q = prior_opex_detail.personnel_costs * (1 + personnel_growth_q)
        ga_q = prior_opex_detail.ga_expenses * (1 + ga_growth_q)
        # D&A: prior stock + incremental from capex (straight-line over da_life_years)
        depn_detail_q = prior_opex_detail.depreciation + capex_q / (da_life_years * 4)
        total_opex = personnel_q + ga_q + depn_detail_q
        # Override caller values so PnLState fields are consistent
        admin_expenses_q = personnel_q + ga_q
        depreciation_q = depn_detail_q
    else:
        # Legacy: split from total passed by caller
        total_opex = admin_expenses_q + depreciation_q
        personnel_q = total_opex * personnel_pct
        ga_q = total_opex * ga_pct
        depn_detail_q = total_opex * depn_pct
    opex_detail = OpexDetail(
        personnel_costs=personnel_q,
        ga_expenses=ga_q,
        depreciation=depn_detail_q,
        total_opex=total_opex,
    )

    ppp = total_oi - total_opex
    pbt = ppp - ecl_charge_q

    # Tax with current/deferred split
    total_tax = max(0.0, pbt * tax_rate)
    current_tax = max(0.0, pbt * current_tax_rate)
    deferred_tax = total_tax - current_tax
    net_profit = pbt - total_tax
    tax_detail = TaxDetail(
        current_tax=current_tax,
        deferred_tax=deferred_tax,
        total_tax=total_tax,
        effective_tax_rate=total_tax / pbt if pbt > 0 else 0.0,
    )

    # Derived ratios (annualised)
    avg_assets = bs.total_assets
    avg_equity = bs.equity
    nim = (nii * 4) / avg_assets if avg_assets > 0 else 0.0
    roe = (net_profit * 4) / avg_equity if avg_equity > 0 else 0.0
    cir = total_opex / total_oi if total_oi > 0 else 0.0

    pnl = PnLState(
        period=period,
        interest_income=interest_income,
        interest_expense=interest_expense,
        nii=nii,
        fee_income_net=fee_income,
        trading_gains=trading_inc_q,
        trading_income=trading_inc_q,
        other_income=other_inc_q,
        total_operating_income=total_oi,
        admin_expenses=admin_expenses_q,
        depreciation=depreciation_q,
        total_opex=total_opex,
        pre_provision_profit=ppp,
        ecl_charge=ecl_charge_q,
        provisions=0.0,
        profit_before_tax=pbt,
        tax_charge=total_tax,
        net_profit=net_profit,
        nim=nim,
        roe=roe,
        cir=cir,
        opex_detail=opex_detail,
        fee_detail=fee_detail,
        nii_detail=nii_detail,
        tax_detail=tax_detail,
    )

    # ΔNII sensitivity: first-order repricing gap (configurable parallel shock)
    shock_bps = NII_SHOCK_PARALLEL_BPS / 100.0
    repricing_assets = bs.loans_net * REPRICING_ASSET_PCT + bs.cash
    blended_beta = funding.deposit_beta if hasattr(funding, 'deposit_beta') else 0.30
    total_deposits = funding.retail_deposits + funding.corporate_deposits
    repricing_liabs = total_deposits * blended_beta
    delta_nii_up100 = (repricing_assets - repricing_liabs) * shock_bps
    nii_ann = nii * 4
    delta_nii_dn100 = max(-(repricing_assets - repricing_liabs) * shock_bps, -nii_ann * 0.50)
    nii_at_risk_pct = abs(delta_nii_dn100) / max(nii_ann, 1.0)
    pnl = dataclasses.replace(pnl, nii_sensitivity=NIISensitivity(
        repricing_assets_eur=repricing_assets,
        repricing_liabilities_eur=repricing_liabs,
        blended_deposit_beta=blended_beta,
        delta_nii_up100bps_eur_ann=delta_nii_up100,
        delta_nii_dn100bps_eur_ann=delta_nii_dn100,
        nii_at_risk_pct=nii_at_risk_pct,
    ))

    return pnl


def pnl_from_base(base_year, period: date) -> PnLState:
    """Initialise PnLState from a BaseYear snapshot (quarterly = annual / 4)."""
    q = 4.0
    total_oi = base_year.total_operating_income / q
    admin_q = base_year.admin_expenses / q
    depn_q = base_year.depreciation / q
    total_opex = admin_q + depn_q
    ecl_q = base_year.ecl_charge / q
    pbt = base_year.profit_before_tax / q
    net_profit = base_year.net_profit / q
    tax = max(0.0, pbt - net_profit)
    nii_q = base_year.nii / q
    fee_q = base_year.fee_income_net / q
    interest_income_q = base_year.interest_income / q
    interest_expense_q = base_year.interest_expense / q

    # Use actual P&L detail if extracted, else estimate
    trading_q = base_year.trading_gains / q if base_year.trading_gains else 0.0
    fx_q = base_year.fx_gains / q if base_year.fx_gains else 0.0
    other_oi_q = base_year.other_operating_income / q if base_year.other_operating_income else 0.0
    provisions_q = base_year.provisions / q if base_year.provisions else 0.0
    # "other_income" = fx + other_oi + anything not NII/fees/trading
    other_income_q = fx_q + other_oi_q
    if trading_q == 0.0 and other_income_q == 0.0:
        # Fallback: residual from total OI
        other_income_q = max(0.0, total_oi - nii_q - fee_q)

    ppp = total_oi - total_opex

    # Sub-details from base year
    opex_detail = OpexDetail(
        personnel_costs=total_opex * 0.60,
        ga_expenses=total_opex * 0.25,
        depreciation=total_opex * 0.15,
        total_opex=total_opex,
    )
    fee_detail = FeeDetail(
        retail=fee_q * 0.50, corporate=fee_q * 0.30,
        asset_mgmt=fee_q * 0.10, treasury=fee_q * 0.10,
        total=fee_q,
    )
    # NII detail: use actual loan/bond interest splits if available
    if base_year.interest_income_loans > 0:
        loan_int_q = base_year.interest_income_loans / q
        bond_int_q = base_year.interest_income_bonds / q
        cash_int_q = max(0.0, interest_income_q - loan_int_q - bond_int_q)
    else:
        loan_int_q = interest_income_q * 0.85
        bond_int_q = interest_income_q * 0.12
        cash_int_q = interest_income_q * 0.03
    nii_detail = NIIDetail(
        banking_book_interest_income=interest_income_q,
        loan_interest_income=loan_int_q,
        bond_interest_income=bond_int_q,
        cash_interest_income=cash_int_q,
        banking_book_interest_expense=interest_expense_q,
        banking_book_nii=nii_q,
        trading_book_nii=0.0,
        total_nii=nii_q,
    )
    tax_detail = TaxDetail(
        current_tax=(tax / q) * (0.20 / 0.22),
        deferred_tax=(tax / q) * (0.02 / 0.22),
        total_tax=tax,
        effective_tax_rate=tax / pbt if pbt > 0 else 0.0,
    )

    return PnLState(
        period=period,
        interest_income=interest_income_q,
        interest_expense=interest_expense_q,
        nii=nii_q,
        fee_income_net=fee_q,
        trading_gains=trading_q,
        trading_income=trading_q,
        other_income=other_income_q,
        total_operating_income=total_oi,
        admin_expenses=admin_q,
        depreciation=depn_q,
        total_opex=total_opex,
        pre_provision_profit=ppp,
        ecl_charge=ecl_q,
        provisions=provisions_q,
        profit_before_tax=pbt,
        tax_charge=tax,
        net_profit=net_profit,
        nim=base_year.nim,
        roe=base_year.roe,
        cir=base_year.cir,
        opex_detail=opex_detail,
        fee_detail=fee_detail,
        nii_detail=nii_detail,
        tax_detail=tax_detail,
    )
