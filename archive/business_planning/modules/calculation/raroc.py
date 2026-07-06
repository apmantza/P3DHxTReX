"""
modules/calculation/raroc.py — Risk-Adjusted Return on Capital (RAROC).

RAROC = (Net Revenue - ECL - Operating Costs) / Economic Capital
     = Risk-Adjusted Income / EC

Where Economic Capital is derived from CET1 allocated to each segment
proportionally to RWA contribution.

Also computes:
- RAROC spread = RAROC - hurdle rate (cost of equity)
- Value added = (RAROC - hurdle) × EC

All amounts EUR mn; ratios as decimals.

Defaults loaded from config/plan_defaults.yaml at import time.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from modules.calculation.state import CapitalState, PnLState

log = logging.getLogger(__name__)


def _load_raroc_defaults() -> dict:
    """Load RAROC defaults from config/plan_defaults.yaml."""
    try:
        from config.loader import load_raroc_defaults as _load
        return _load()
    except Exception as exc:
        log.warning("Could not load RAROC defaults from YAML: %s", exc)
        return {}


_RAROC_CONFIG = _load_raroc_defaults()

DEFAULT_HURDLE_RATE = _RAROC_CONFIG.get("hurdle_rate", 0.12)

_DEFAULT_SEGMENT_WEIGHTS = _RAROC_CONFIG.get("segment_weights", {
    "Retail Banking": 0.50,
    "Corporate Banking": 0.35,
    "Treasury": 0.15,
})

_DEFAULT_COST_WEIGHTS = _RAROC_CONFIG.get("cost_weights", {
    "Retail Banking": 0.55,
    "Corporate Banking": 0.30,
    "Treasury": 0.15,
})

_DEFAULT_ECL_WEIGHTS = _RAROC_CONFIG.get("ecl_weights", {
    "Retail Banking": 0.60,
    "Corporate Banking": 0.35,
    "Treasury": 0.05,
})

_DEFAULT_RWA_WEIGHTS = _RAROC_CONFIG.get("rwa_weights", {
    "Retail Banking": 0.50,
    "Corporate Banking": 0.40,
    "Treasury": 0.10,
})


@dataclass
class SegmentRARoC:
    """RAROC metrics for one business segment."""
    segment: str
    period: date
    # Income drivers (quarterly, EUR mn)
    nii: float = 0.0
    fee_income: float = 0.0
    net_revenue: float = 0.0
    ecl_charge: float = 0.0
    allocated_costs: float = 0.0
    risk_adjusted_income: float = 0.0
    # Capital
    allocated_rwa: float = 0.0
    economic_capital: float = 0.0
    # RAROC (annualised)
    raroc: float = 0.0
    hurdle_rate: float = DEFAULT_HURDLE_RATE
    raroc_spread: float = 0.0
    # Value creation (annualised, EUR mn)
    value_added: float = 0.0


def calculate_segment_raroc(
    pnl: PnLState,
    capital: CapitalState,
    period: date,
    *,
    # Segment income allocation weights (must sum to 1)
    segment_weights: dict[str, float] | None = None,
    # Cost allocation (proportion of total opex per segment)
    cost_weights: dict[str, float] | None = None,
    # ECL allocation (proportion of ECL charge per segment)
    ecl_weights: dict[str, float] | None = None,
    # RWA allocation (proportion of credit RWA per segment)
    rwa_weights: dict[str, float] | None = None,
    # CET1 ratio used for economic capital (Pillar 2 target)
    ec_ratio: float = 0.12,
    hurdle_rate: float = DEFAULT_HURDLE_RATE,
) -> list[SegmentRARoC]:
    """
    Compute RAROC for each segment.

    Default segments: Retail Banking, Corporate Banking, Treasury.
    Income, cost and ECL are allocated proportionally by weight.
    Economic capital = allocated RWA × EC ratio.
    """
    # Default weights from config (balanced retail-skewed bank)
    if segment_weights is None:
        segment_weights = dict(_DEFAULT_SEGMENT_WEIGHTS)
    if cost_weights is None:
        cost_weights = dict(_DEFAULT_COST_WEIGHTS)
    if ecl_weights is None:
        ecl_weights = dict(_DEFAULT_ECL_WEIGHTS)
    if rwa_weights is None:
        rwa_weights = dict(_DEFAULT_RWA_WEIGHTS)

    results = []
    for segment, w_income in segment_weights.items():
        w_cost = cost_weights.get(segment, w_income)
        w_ecl  = ecl_weights.get(segment, w_income)
        w_rwa  = rwa_weights.get(segment, w_income)

        seg_nii     = pnl.nii           * w_income
        seg_fee     = pnl.fee_income_net * w_income
        seg_rev     = seg_nii + seg_fee
        seg_ecl     = pnl.ecl_charge    * w_ecl
        seg_cost    = pnl.total_opex    * w_cost
        seg_rai     = seg_rev - seg_ecl - seg_cost

        seg_rwa     = capital.rwa_credit * w_rwa
        seg_ec      = seg_rwa * ec_ratio

        raroc = (seg_rai * 4) / seg_ec if seg_ec > 0 else 0.0
        spread = raroc - hurdle_rate
        value_added = spread * seg_ec

        results.append(SegmentRARoC(
            segment=segment,
            period=period,
            nii=seg_nii,
            fee_income=seg_fee,
            net_revenue=seg_rev,
            ecl_charge=seg_ecl,
            allocated_costs=seg_cost,
            risk_adjusted_income=seg_rai,
            allocated_rwa=seg_rwa,
            economic_capital=seg_ec,
            raroc=raroc,
            hurdle_rate=hurdle_rate,
            raroc_spread=spread,
            value_added=value_added,
        ))

    return results
