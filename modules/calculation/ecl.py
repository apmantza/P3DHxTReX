"""
modules/calculation/ecl.py — IFRS 9 ECL calculation.

Implements a simplified 3-scenario probability-weighted ECL model:
- Stage 1: 12-month ECL = PD12m × LGD × EAD
- Stage 2: Lifetime ECL = PDlt × LGD × EAD
- Stage 3: Incurred ECL = LGD × EAD (100% PD)

Scenarios are probability-weighted as per IAS 39 / IFRS 9 guidance.
Macro stress overlays shift PD assumptions.

Amounts in EUR mn.

Defaults loaded from config/plan_defaults.yaml at import time.
"""
from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date

from modules.calculation.state import AssetQualityState, EclState

log = logging.getLogger(__name__)


def _load_ecl_defaults() -> dict:
    """Load ECL defaults from config/plan_defaults.yaml."""
    try:
        from config.loader import load_ecl_defaults as _load
        return _load()
    except Exception as exc:
        log.warning("Could not load ECL defaults from YAML: %s", exc)
        return {}


_ECL_CONFIG = _load_ecl_defaults()

DEFAULT_PD_S1 = _ECL_CONFIG.get("pd_s1", 0.005)
DEFAULT_PD_S2 = _ECL_CONFIG.get("pd_s2", 0.08)
DEFAULT_PD_S3 = _ECL_CONFIG.get("pd_s3", 1.0)
DEFAULT_LGD_S1 = _ECL_CONFIG.get("lgd_s1", 0.40)
DEFAULT_LGD_S2 = _ECL_CONFIG.get("lgd_s2", 0.40)
DEFAULT_LGD_S3 = _ECL_CONFIG.get("lgd_s3", 0.50)
DEFAULT_WEIGHT_BASE = _ECL_CONFIG.get("weight_base", 0.50)
DEFAULT_WEIGHT_ADVERSE = _ECL_CONFIG.get("weight_adverse", 0.35)
DEFAULT_WEIGHT_SEVERE = _ECL_CONFIG.get("weight_severe", 0.15)
ADVERSE_PD_MULTIPLIER = _ECL_CONFIG.get("pd_mult_adverse", 1.50)
SEVERE_PD_MULTIPLIER = _ECL_CONFIG.get("pd_mult_severe", 2.50)


def calculate_ecl(
    aq: AssetQualityState,
    period: date,
    prior_ecl: EclState | None = None,
    *,
    # PD parameters (annualised)
    pd_s1: float = DEFAULT_PD_S1,
    pd_s2: float = DEFAULT_PD_S2,
    lgd_s1: float = DEFAULT_LGD_S1,
    lgd_s2: float = DEFAULT_LGD_S2,
    lgd_s3: float = DEFAULT_LGD_S3,
    # Scenario weights
    weight_base: float = DEFAULT_WEIGHT_BASE,
    weight_adverse: float = DEFAULT_WEIGHT_ADVERSE,
    weight_severe: float = DEFAULT_WEIGHT_SEVERE,
    # Macro overlays (scenario-specific PD multipliers)
    pd_mult_adverse: float = ADVERSE_PD_MULTIPLIER,
    pd_mult_severe: float = SEVERE_PD_MULTIPLIER,
    # Off-balance-sheet ECL
    obs_commitments_pct: float = 0.0,
    obs_ccf: float = 0.75,   # credit conversion factor for OBS commitments
) -> EclState:
    """
    Compute IFRS 9 ECL for one quarter.

    For simplicity, EAD = gross carrying amount (no CCF modelling).
    PDs are annualised; for quarterly ECL we scale by 1/4 for S1 and
    use full lifetime PD for S2/S3 (appropriate for a stock measure).

    The ECL charge = change in stock ECL allowance vs prior quarter.
    """
    # Stage EADs
    ead_s1 = aq.stage1_gross
    ead_s2 = aq.stage2_gross
    ead_s3 = aq.stage3_gross

    # --- Base scenario ECL ---
    ecl_s1_base = ead_s1 * pd_s1 * lgd_s1          # 12m PD (stock)
    ecl_s2_base = ead_s2 * pd_s2 * lgd_s2          # lifetime
    ecl_s3_base = ead_s3 * DEFAULT_PD_S3 * lgd_s3

    # --- Adverse scenario ECL ---
    ecl_s1_adv = ead_s1 * (pd_s1 * pd_mult_adverse) * lgd_s1
    ecl_s2_adv = ead_s2 * (pd_s2 * pd_mult_adverse) * lgd_s2
    ecl_s3_adv = ead_s3 * DEFAULT_PD_S3 * lgd_s3   # S3: LGD still 1×

    # --- Severe scenario ECL ---
    ecl_s1_sev = ead_s1 * (pd_s1 * pd_mult_severe) * lgd_s1
    ecl_s2_sev = ead_s2 * (pd_s2 * pd_mult_severe) * lgd_s2
    ecl_s3_sev = ead_s3 * DEFAULT_PD_S3 * (lgd_s3 * 1.20)   # higher LGD in severe

    # Probability-weighted ECL
    ecl_s1 = (
        weight_base    * ecl_s1_base
        + weight_adverse * ecl_s1_adv
        + weight_severe  * ecl_s1_sev
    )
    ecl_s2 = (
        weight_base    * ecl_s2_base
        + weight_adverse * ecl_s2_adv
        + weight_severe  * ecl_s2_sev
    )
    ecl_s3 = (
        weight_base    * ecl_s3_base
        + weight_adverse * ecl_s3_adv
        + weight_severe  * ecl_s3_sev
    )

    ecl_total = ecl_s1 + ecl_s2 + ecl_s3

    # ECL charge = increase in allowance stock (write-offs netted by AQ module)
    prior_total = prior_ecl.ecl_total if prior_ecl else ecl_total
    ecl_charge = ecl_total - prior_total  # positive = charge, negative = release

    # --- Off-balance-sheet ECL ---
    obs_gross = aq.loans_gross * obs_commitments_pct if obs_commitments_pct > 0 else 0.0
    if obs_gross > 0:
        obs_ead = obs_gross * obs_ccf  # credit-equivalent exposure
        # Weighted average PD across stages (simplified: use S1 PD for OBS)
        obs_pd_base = pd_s1
        obs_ecl_prov = (
            weight_base    * obs_ead * obs_pd_base * lgd_s1
            + weight_adverse * obs_ead * (obs_pd_base * pd_mult_adverse) * lgd_s1
            + weight_severe  * obs_ead * (obs_pd_base * pd_mult_severe) * lgd_s1
        )
        prior_obs = prior_ecl.obs_ecl_provision if prior_ecl else obs_ecl_prov
        obs_charge = obs_ecl_prov - prior_obs
    else:
        obs_ecl_prov = 0.0
        obs_charge = 0.0

    total_ecl_charge = ecl_charge + obs_charge

    return EclState(
        period=period,
        ecl_stage1=ecl_s1,
        ecl_stage2=ecl_s2,
        ecl_stage3=ecl_s3,
        ecl_total=ecl_total,
        ecl_charge=ecl_charge,
        weight_base=weight_base,
        weight_adverse=weight_adverse,
        weight_severe=weight_severe,
        obs_commitments_gross=obs_gross,
        obs_ecl_provision=obs_ecl_prov,
        obs_ecl_charge_q=obs_charge,
        total_ecl_charge_q=total_ecl_charge,
    )


def ecl_from_base(base_year, aq: AssetQualityState, period: date) -> EclState:
    """Initialise EclState from BaseYear (uses historical ECL allowance)."""
    # Use actual ECL allowance splits if available from NPE template
    if base_year.ecl_allowance_total > 0:
        ecl_s1 = base_year.ecl_allow_performing - base_year.ecl_allow_stage2
        ecl_s2 = base_year.ecl_allow_stage2
        ecl_s3 = base_year.ecl_allow_npe
        total_allowance = base_year.ecl_allowance_total
    else:
        # Fallback: back-solve from gross vs AC, rough 10/25/65 split
        total_allowance = base_year.loans_gross - base_year.loans_ac
        total_allowance = max(0.0, total_allowance)
        ecl_s1 = total_allowance * 0.10
        ecl_s2 = total_allowance * 0.25
        ecl_s3 = total_allowance * 0.65

    return EclState(
        period=period,
        ecl_stage1=ecl_s1,
        ecl_stage2=ecl_s2,
        ecl_stage3=ecl_s3,
        ecl_total=total_allowance,
        ecl_charge=base_year.ecl_charge / 4,  # quarterly
        weight_base=DEFAULT_WEIGHT_BASE,
        weight_adverse=DEFAULT_WEIGHT_ADVERSE,
        weight_severe=DEFAULT_WEIGHT_SEVERE,
    )
