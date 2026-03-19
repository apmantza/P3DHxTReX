"""
modules/calculation/liquidity.py — LCR, NSFR and survival horizon.

Implements simplified EBA-aligned LCR and NSFR proxy calculations.
Full regulatory LCR/NSFR requires granular cashflow data not available
from public disclosures — these proxies use balance sheet approximations
suitable for the business planning horizon.

Survival horizon: days until HQLA buffer is exhausted under a stress outflow scenario.

Amounts in EUR mn; ratios as decimals (e.g. 1.50 = 150%).

Defaults loaded from config/plan_defaults.yaml at import time.
"""
from __future__ import annotations

import logging
from datetime import date

from modules.calculation.state import BalanceSheetState, FundingState, LiquidityState

log = logging.getLogger(__name__)


def _load_liquidity_rates() -> dict:
    """Load liquidity rates from config."""
    try:
        from config.loader import load_config as _load
        return _load("liquidity_rates")
    except Exception as exc:
        log.warning("Could not load liquidity_rates from YAML: %s", exc)
        return {}


_LIQ = _load_liquidity_rates()

OUTFLOW_RETAIL_STABLE = _LIQ.get("outflow_retail_stable", 0.05)
OUTFLOW_RETAIL_LESS_STAB = _LIQ.get("outflow_retail_less_stab", 0.10)
OUTFLOW_CORPORATE = _LIQ.get("outflow_corporate", 0.25)
OUTFLOW_WHOLESALE = 1.00
OUTFLOW_COVERED_BONDS = _LIQ.get("outflow_covered_bonds", 0.15)
OUTFLOW_CB_FUNDING = _LIQ.get("outflow_cb_funding", 0.25)

INFLOW_LOANS_PERFORMING = _LIQ.get("inflow_loans_performing", 0.50)

RSF_LOANS_LONG = _LIQ.get("rsf_loans_long", 0.85)
RSF_LOANS_SHORT = _LIQ.get("rsf_loans_short", 0.50)
RSF_NPL = 1.00
RSF_BONDS_HQLA = _LIQ.get("rsf_bonds_hqla", 0.05)
RSF_OTHER_ASSETS = 1.00

ASF_RETAIL_STABLE = _LIQ.get("asf_retail_stable", 0.95)
ASF_RETAIL_LESS_STAB = _LIQ.get("asf_retail_less_stab", 0.90)
ASF_CORPORATE = _LIQ.get("asf_corporate", 0.50)
ASF_WHOLESALE_LT = 1.00
ASF_WHOLESALE_ST = _LIQ.get("asf_wholesale_short", 0.00)
ASF_EQUITY = 1.00


def calculate_liquidity(
    bs: BalanceSheetState,
    funding: FundingState,
    period: date,
    *,
    # HQLA as % of total assets (proxy for LCR numerator)
    hqla_ratio: float = 0.20,
    # Retail deposit split (stable vs less stable)
    retail_stable_pct: float = 0.60,
    # Wholesale assumed <30d maturity bucket (stressed)
    wholesale_stressed_pct: float = 0.30,
    # Loan inflow rate (performing book, 30d contractual receipts)
    loan_inflow_rate_30d: float = 0.015,  # 1.5% of performing book in 30d
    # Stress scenario: daily liquidity buffer burn rate (EUR mn/day)
    stress_daily_outflow: float | None = None,
    # Long-term loan %
    loans_lt_pct: float = 0.70,
) -> LiquidityState:
    """
    Compute LCR, NSFR and survival horizon for one quarter-end.

    LCR = HQLA / Net cash outflows over 30 calendar days
    NSFR = Available stable funding / Required stable funding
    Survival horizon = HQLA / stress daily outflow
    """
    # ------------------------------------------------------------------
    # LCR
    # ------------------------------------------------------------------
    hqla = bs.total_assets * hqla_ratio

    retail_stable    = funding.retail_deposits * retail_stable_pct
    retail_less_stab = funding.retail_deposits * (1 - retail_stable_pct)
    corporate_dep    = funding.corporate_deposits
    wholesale_st     = (funding.interbank_funding + funding.senior_unsecured) * wholesale_stressed_pct
    cb_fund          = funding.central_bank_funding

    gross_outflows = (
        retail_stable    * OUTFLOW_RETAIL_STABLE
        + retail_less_stab * OUTFLOW_RETAIL_LESS_STAB
        + corporate_dep    * OUTFLOW_CORPORATE
        + wholesale_st     * OUTFLOW_WHOLESALE
        + funding.covered_bonds * OUTFLOW_COVERED_BONDS
        + cb_fund          * OUTFLOW_CB_FUNDING
    )

    # Contractual inflows from performing loans (capped at 75% of outflows)
    performing_loans = max(0.0, bs.loans_gross - (bs.ecl_allowance * 3))  # rough NPL proxy
    loan_inflows = performing_loans * loan_inflow_rate_30d
    net_inflows  = min(loan_inflows, 0.75 * gross_outflows)

    net_outflows = max(gross_outflows - net_inflows, gross_outflows * 0.25)  # floor at 25%
    lcr = hqla / net_outflows if net_outflows > 0 else 9.99

    # ------------------------------------------------------------------
    # NSFR
    # ------------------------------------------------------------------
    loans_lt = bs.loans_gross * loans_lt_pct
    loans_st = bs.loans_gross * (1 - loans_lt_pct)
    npl_est  = bs.ecl_allowance * 2   # rough NPL proxy

    rsf = (
        loans_lt                   * RSF_LOANS_LONG
        + loans_st                 * RSF_LOANS_SHORT
        + npl_est                  * RSF_NPL
        + bs.fvoci_assets          * RSF_BONDS_HQLA
        + bs.other_assets          * RSF_OTHER_ASSETS
    )

    asf = (
        retail_stable              * ASF_RETAIL_STABLE
        + retail_less_stab         * ASF_RETAIL_LESS_STAB
        + corporate_dep            * ASF_CORPORATE
        + funding.covered_bonds    * ASF_WHOLESALE_LT
        + funding.subordinated_debt * ASF_WHOLESALE_LT
        + funding.senior_unsecured * ASF_WHOLESALE_ST
        + funding.interbank_funding * ASF_WHOLESALE_ST
        + bs.equity                * ASF_EQUITY
    )

    nsfr = asf / rsf if rsf > 0 else 9.99

    # ------------------------------------------------------------------
    # Survival horizon (days)
    # ------------------------------------------------------------------
    if stress_daily_outflow is None:
        # Default: 3% of total funding per day under stress
        stress_daily_outflow = funding.total_funding * 0.03
    survival_days = hqla / stress_daily_outflow if stress_daily_outflow > 0 else 999.0

    return LiquidityState(
        period=period,
        hqla=hqla,
        net_cash_outflows_30d=net_outflows,
        lcr=lcr,
        available_stable_funding=asf,
        required_stable_funding=rsf,
        nsfr=nsfr,
        survival_horizon_days=survival_days,
    )
