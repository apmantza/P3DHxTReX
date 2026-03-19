"""
modules/vbm/economic_profit.py — Value-Based Management: Economic Profit / EVA Lite.

Economic Profit (EP) = Net Operating Profit After Tax - Cost of Equity × Book Equity
                     = Net Profit - (CoE × BV_Equity)

Where CoE (Cost of Equity) is estimated using a simplified CAPM or provided explicitly.

Also computes:
- Implied P/BV (price-to-book value) = 1 + EP / (CoE × BV) if sustainable
- TSR proxy (Total Shareholder Return) based on EPS growth + dividend yield
- ROE vs CoE spread (value creation / destruction signal)

Amounts EUR mn; rates as decimals; per-share in EUR if shares provided.

Defaults loaded from config/plan_defaults.yaml at import time.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from modules.calculation.state import BalanceSheetState, CapitalState, PnLState

log = logging.getLogger(__name__)


def _load_vbm_config() -> dict:
    """Load VBM defaults from config."""
    try:
        from config.loader import load_config as _load
        return _load("vbm")
    except Exception as exc:
        log.warning("Could not load vbm config: %s", exc)
        return {}


_VBM_CONFIG = _load_vbm_config()

RISK_FREE_RATE = _VBM_CONFIG.get("risk_free_rate", 0.030)
EQUITY_RISK_PREM = _VBM_CONFIG.get("equity_risk_premium", 0.055)
BETA_BANK = _VBM_CONFIG.get("beta_bank", 1.10)


def implied_coe(
    beta: float = BETA_BANK,
    risk_free: float = RISK_FREE_RATE,
    erp: float = EQUITY_RISK_PREM,
) -> float:
    """Simplified CAPM: CoE = Rf + β × ERP."""
    return risk_free + beta * erp


@dataclass
class VbmMetrics:
    """Value-Based Management metrics for one quarter."""
    period: date
    # Inputs (annualised, EUR mn unless noted)
    net_profit_ann: float = 0.0        # annualised net profit
    book_equity: float = 0.0
    cost_of_equity: float = 0.0        # decimal (e.g. 0.12)
    # Economic profit (annualised, EUR mn)
    equity_charge: float = 0.0        # CoE × book equity
    economic_profit: float = 0.0      # net profit - equity charge
    # ROE vs CoE spread
    roe: float = 0.0
    roe_coe_spread: float = 0.0       # ROE - CoE
    # Implied P/BV
    implied_ptbv: float = 0.0
    # Per-share (EUR) — only populated if shares_outstanding provided
    shares_outstanding: float = 0.0
    eps: float = 0.0                   # annualised EPS
    dps: float = 0.0                   # annualised DPS
    implied_pe: float = 0.0
    # TSR proxy = EPS growth + dividend yield
    eps_growth: float = 0.0           # vs prior year (decimal)
    dividend_yield_proxy: float = 0.0


def calculate_vbm(
    pnl: PnLState,
    bs: BalanceSheetState,
    capital: CapitalState,
    period: date,
    prior_vbm: "VbmMetrics | None" = None,
    *,
    cost_of_equity: float | None = None,
    beta: float = BETA_BANK,
    risk_free: float = RISK_FREE_RATE,
    erp: float = EQUITY_RISK_PREM,
    dividend_payout: float = 0.40,
    shares_outstanding: float = 0.0,
    market_price_per_share: float = 0.0,
) -> VbmMetrics:
    """
    Compute VBM metrics for one quarter.

    Economic Profit = annualised net profit - CoE × average book equity
    """
    coe = cost_of_equity if cost_of_equity is not None else implied_coe(beta, risk_free, erp)

    net_profit_ann = pnl.net_profit * 4  # quarterly → annual
    book_eq = bs.equity

    equity_charge = coe * book_eq
    economic_profit = net_profit_ann - equity_charge

    roe = pnl.roe   # already annualised in PnLState
    roe_coe_spread = roe - coe

    # Gordon Growth implied P/BV:  P/BV = (ROE - g) / (CoE - g)  approx.
    # For PoC: use simpler formula P/BV = 1 + EP / (CoE × BV)
    implied_ptbv = (
        1.0 + economic_profit / (coe * book_eq)
        if coe * book_eq > 0 else 1.0
    )
    implied_ptbv = max(0.0, implied_ptbv)

    # Per-share metrics
    eps = dps = implied_pe = eps_growth = div_yield = 0.0
    if shares_outstanding > 0:
        eps = net_profit_ann / shares_outstanding
        dps = eps * dividend_payout
        if market_price_per_share > 0:
            implied_pe = market_price_per_share / eps if eps > 0 else 0.0
            div_yield = dps / market_price_per_share
        # EPS growth vs prior
        if prior_vbm and prior_vbm.eps > 0:
            eps_growth = (eps - prior_vbm.eps) / prior_vbm.eps

    return VbmMetrics(
        period=period,
        net_profit_ann=net_profit_ann,
        book_equity=book_eq,
        cost_of_equity=coe,
        equity_charge=equity_charge,
        economic_profit=economic_profit,
        roe=roe,
        roe_coe_spread=roe_coe_spread,
        implied_ptbv=implied_ptbv,
        shares_outstanding=shares_outstanding,
        eps=eps,
        dps=dps,
        implied_pe=implied_pe,
        eps_growth=eps_growth,
        dividend_yield_proxy=div_yield,
    )
