"""
modules/calculation/asset_quality.py — Credit quality projection.

Models NPL migration, cure rates, write-offs and coverage ratio evolution.
Applies macro-driven stress overlays when a Scenario is provided.

Amounts in EUR mn; ratios as decimals.
"""
from __future__ import annotations

from datetime import date

from modules.calculation.state import AssetQualityState, BalanceSheetState


def calculate_asset_quality(
    prior: AssetQualityState,
    bs: BalanceSheetState,
    period: date,
    *,
    # NPL migration assumptions (quarterly, decimal of performing book)
    default_rate_q: float = 0.004,      # 0.4% quarterly new defaults (≈1.6% p.a.)
    cure_rate_q: float = 0.05,          # 5% of NPLs cure per quarter
    write_off_rate_q: float = 0.03,     # 3% of NPLs written off per quarter
    disposal_rate_q: float = 0.0,       # NPE sales/securitisation (quarterly % of NPL stock)
    # Stage 2 ratio (proportion of performing book that is elevated risk)
    stage2_proportion: float = 0.08,
    # Macro stress overlay — additive to default_rate_q
    stress_default_overlay: float = 0.0,
) -> AssetQualityState:
    """
    Project asset quality one quarter forward.

    NPL migration:
        new_npls  = prior_performing × (default_rate_q + stress_overlay)
        cured     = prior_npl × cure_rate_q
        written_off = prior_npl × write_off_rate_q
        npl_gross_new = prior_npl + new_npls - cured - written_off

    Returns a new AssetQualityState.
    """
    loans_gross = bs.loans_gross if bs.loans_gross > 0 else prior.loans_gross
    prior_performing = max(0.0, prior.loans_gross - prior.npl_gross)

    new_npls = prior_performing * (default_rate_q + stress_default_overlay)
    cured = prior.npl_gross * cure_rate_q
    written_off = prior.npl_gross * write_off_rate_q
    disposed = prior.npl_gross * disposal_rate_q

    npl_gross = max(0.0, prior.npl_gross + new_npls - cured - written_off - disposed)
    performing = max(0.0, loans_gross - npl_gross)

    stage2 = performing * stage2_proportion
    stage1 = performing - stage2
    stage3 = npl_gross

    npl_ratio = npl_gross / loans_gross if loans_gross > 0 else 0.0
    stage2_ratio = stage2 / loans_gross if loans_gross > 0 else 0.0

    coverage = bs.ecl_allowance / npl_gross if npl_gross > 0 else 0.0

    return AssetQualityState(
        period=period,
        loans_gross=loans_gross,
        npl_gross=npl_gross,
        stage1_gross=stage1,
        stage2_gross=stage2,
        stage3_gross=stage3,
        npl_ratio=npl_ratio,
        stage2_ratio=stage2_ratio,
        new_npls=new_npls,
        cured_npls=cured,
        written_off=written_off,
        disposed_npls=disposed,
        coverage_ratio=coverage,
    )


def asset_quality_from_base(base_year, bs: BalanceSheetState, period: date) -> AssetQualityState:
    """Initialise AssetQualityState from BaseYear + BalanceSheetState."""
    loans_gross = base_year.loans_gross if base_year.loans_gross > 0 else base_year.loans_ac
    npl_gross = base_year.npe_gross
    npl_ratio = base_year.npl_ratio

    performing = max(0.0, loans_gross - npl_gross)
    # Use actual Stage 2 if available, else default 8% of performing
    if base_year.npe_stage2 > 0:
        stage2 = base_year.npe_stage2
    else:
        stage2 = performing * 0.08
    stage1 = performing - stage2

    coverage = bs.ecl_allowance / npl_gross if npl_gross > 0 else 0.0

    return AssetQualityState(
        period=period,
        loans_gross=loans_gross,
        npl_gross=npl_gross,
        stage1_gross=stage1,
        stage2_gross=stage2,
        stage3_gross=npl_gross,
        npl_ratio=npl_ratio,
        stage2_ratio=stage2 / loans_gross if loans_gross > 0 else 0.0,
        new_npls=0.0,
        cured_npls=0.0,
        written_off=0.0,
        coverage_ratio=coverage,
    )
