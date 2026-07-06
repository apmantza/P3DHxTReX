"""
modules/calculation/engine.py — Calculation engine orchestrator.

Entry point:
    run_projection(plan: Plan, scenario: Scenario | None, db: Session)
        -> list[ProjectedFinancials]

Produces 20 quarterly ProjectedFinancials rows (5-year plan horizon).

Execution order per quarter:
    1. Funding state (deposit repricing, volume growth)
    2. FTP curves
    3. Balance sheet (asset-side growth + equity constraint)
    4. Funding gap fill (interbank at DFR + spread)
    5. Asset quality (NPL migration — current quarter stages)
    6. ECL (IFRS 9 probability-weighted — uses current AQ)
    7. P&L (NII, fees, opex, ECL charge from step 6)
    8. Payout (dividends + buybacks)
    9. DTA/DTC
   10. Capital (CET1 accumulation, buffers, MREL)
   11. OCI
   12. Equity bridge
   13. Liquidity (LCR / NSFR / survival horizon)
   14. RAROC (segment)
   15. VBM (economic profit)
   16. Bridges (PAT / NII / capital waterfall / CoR / fee / ROE)
   17. Hot-path scalars
   18. Assemble ProjectedFinancials ORM row
"""
from __future__ import annotations

import dataclasses
import logging
from datetime import date, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default plan assumptions
# Loaded from config/plan_defaults.yaml at import time.
# The inline dicts below are a last-resort fallback only — edit the YAML.
# ---------------------------------------------------------------------------
_FALLBACK_RATE_ENV = {
    "policy_rate": 0.035, "euribor_3m": 0.030, "euribor_6m": 0.032,
    "swap_2y": 0.028, "swap_5y": 0.025, "swap_10y": 0.027, "rate_path": [],
}
_FALLBACK_PORTFOLIO = {
    "loan_growth_q": 0.010, "fvoci_growth_q": 0.005, "fee_growth_q": 0.010,
    "loan_yield": 0.055, "bond_yield": 0.040, "opex_growth_q": 0.005,
    "tax_rate": 0.22, "deposit_beta": 0.30, "hqla_ratio": 0.20,
    "cet1_target": 0.15, "p2r": 0.015, "at1_coupon_rate": 0.06,
    "regular_cash_dividend_pct": 0.40, "buyback_pct": 0.20,
    "default_rate_q": 0.004, "cure_rate_q": 0.05, "write_off_rate_q": 0.03,
    "stage2_proportion": 0.08, "obs_commitments_pct": 0.15,
    "interbank_gap_spread": 0.0010, "peer_lei_list": None,
}

try:
    from config.loader import load_defaults as _load_defaults
    _yaml_rate, _yaml_port = _load_defaults()
except Exception as _exc:
    log.warning("Could not load config/plan_defaults.yaml: %s", _exc)
    _yaml_rate, _yaml_port = {}, {}

_DEFAULT_RATE_ENV  = {**_FALLBACK_RATE_ENV,  **_yaml_rate}
_DEFAULT_PORTFOLIO = {**_FALLBACK_PORTFOLIO, **_yaml_port}


def _quarter_ends(base_date: date, n_quarters: int) -> list[date]:
    """Generate n quarter-end dates starting the quarter after base_date."""
    import calendar
    quarters = []
    y, m = base_date.year, base_date.month
    q_month = ((m - 1) // 3 + 1) * 3
    if q_month > 12:
        q_month, y = q_month - 12, y + 1
    current = date(y, q_month, calendar.monthrange(y, q_month)[1])
    for _ in range(n_quarters):
        m2 = current.month + 3
        y2 = current.year
        if m2 > 12:
            m2, y2 = m2 - 12, y2 + 1
        current = date(y2, m2, calendar.monthrange(y2, m2)[1])
        quarters.append(current)
    return quarters


def _merge(defaults: dict, overrides: dict | None) -> dict:
    if not overrides:
        return dict(defaults)
    merged = dict(defaults)
    merged.update({k: v for k, v in overrides.items() if v is not None})
    return merged


def _to_dict(obj) -> dict:
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    return {}


def run_projection(plan, scenario, db: "Session") -> list:
    """
    Run a 5-year quarterly projection for *plan* × *scenario*.
    Returns a list of ProjectedFinancials ORM objects (not yet committed).
    """
    from db.models import ProjectedFinancials
    from modules.calculation.asset_quality import asset_quality_from_base, calculate_asset_quality
    from modules.calculation.balance_sheet import balance_sheet_from_base, project_balance_sheet
    from modules.calculation.bridges import (
        calculate_capital_waterfall, calculate_cor_bridge, calculate_fee_bridge,
        calculate_nii_bridge, calculate_pat_bridge, calculate_roe_bridge,
    )
    from modules.calculation.capital import (
        calculate_capital, calculate_dta_state, calculate_equity_bridge,
        calculate_oci, calculate_payout, capital_from_base,
    )
    from modules.calculation.ecl import calculate_ecl, ecl_from_base
    from modules.calculation.funding import apply_deposit_pass_through, apply_funding_gap, funding_from_base
    from modules.calculation.liquidity import calculate_liquidity
    from modules.calculation.pnl import calculate_pnl, pnl_from_base
    from modules.calculation.raroc import calculate_segment_raroc
    from modules.calculation.state import (
        BaseYearExtractor, DTAState, PayoutAssumptions, RateEnvironment,
    )
    from modules.ftp.curves import build_ftp_curves
    from modules.vbm.economic_profit import calculate_vbm

    # ------------------------------------------------------------------
    # 1. Load base year
    # ------------------------------------------------------------------
    byx = BaseYearExtractor(db, bank_lei=plan.bank.lei if plan.bank.lei else None,
                            bank_name=plan.bank.name)
    base = byx.extract()
    log.info(
        "Base year: CET1=%.0fmn CET1r=%.1f%% NII=%.0fmn RWA=%.0fmn",
        base.cet1_capital, base.cet1_ratio * 100, base.nii, base.rwa_total,
    )

    # ------------------------------------------------------------------
    # 2. Resolve assumptions
    # ------------------------------------------------------------------
    rate_cfg = _merge(_DEFAULT_RATE_ENV, plan.rate_environment)
    port_cfg = _merge(_DEFAULT_PORTFOLIO, plan.portfolio_allocations)

    # Macro overlay from scenario
    stress_default_overlay = 0.0
    pd_mult_adv = 1.50
    pd_mult_sev = 2.50
    w_base = 1.0
    w_adv  = 0.0
    w_sev  = 0.0
    if scenario is not None:
        macro = scenario.macro_assumptions or {}
        stress_default_overlay = float(macro.get("stress_default_overlay", 0.0))
        pd_mult_adv = float(macro.get("pd_mult_adverse", 1.50))
        pd_mult_sev = float(macro.get("pd_mult_severe", 2.50))
        w_base = float(macro.get("weight_base",    0.50))
        w_adv  = float(macro.get("weight_adverse", 0.35))
        w_sev  = float(macro.get("weight_severe",  0.15))

    rate_env = RateEnvironment(
        policy_rate=float(rate_cfg["policy_rate"]),
        euribor_3m =float(rate_cfg["euribor_3m"]),
        euribor_6m =float(rate_cfg["euribor_6m"]),
        swap_2y    =float(rate_cfg.get("swap_2y", 0.028)),
        swap_5y    =float(rate_cfg.get("swap_5y", 0.025)),
        swap_10y   =float(rate_cfg.get("swap_10y", 0.027)),
        rate_path  =rate_cfg.get("rate_path", []),
    )

    # Fee weights dict (legacy flat model fallback)
    fee_weights = port_cfg.get("fee_weights") or {"retail": 0.50, "corporate": 0.30, "asset_mgmt": 0.10, "treasury": 0.10}
    # AUM: initialise to 0; grows at aum_growth_q each quarter if non-zero
    aum_q = float(port_cfg.get("aum_opening", 0.0))

    # ------------------------------------------------------------------
    # 3. Initialise states from base year
    # ------------------------------------------------------------------
    base_period = date(2025, 6, 30)
    quarters = _quarter_ends(base_period, plan.horizon_years * 4)

    bs      = balance_sheet_from_base(base, base_period)
    pnl     = pnl_from_base(base, base_period)
    capital = capital_from_base(base, base_period)
    aq      = asset_quality_from_base(base, bs, base_period)
    ecl     = ecl_from_base(base, aq, base_period)
    funding = funding_from_base(base, bs, rate_env, base_period)

    # Patch base-year BS with the ECL module's initial allowance stock
    # so that ecl_allowance, loans_net and coverage_ratio are consistent from Q0.
    if ecl.ecl_total > 0:
        bs = dataclasses.replace(
            bs,
            ecl_allowance=ecl.ecl_total,
            loans_net=max(0.0, bs.loans_gross - ecl.ecl_total),
        )

    # DTC stock: use config if set, else seed from base-year DTA temp diff extraction
    # (for Greek banks, item 2520106 is largely DTC under Law 4172/2013)
    dtc_opening = float(port_cfg.get("dtc_stock_opening", 0.0))
    if dtc_opening == 0.0 and base.dta_temp_diff > 0:
        dtc_opening = base.dta_temp_diff
    prior_dta = DTAState(
        period=base_period,
        dta_regular=float(port_cfg.get("dta_regular_opening", 0.0)) or base.dta,
        dtc_stock_opening=dtc_opening,
    )
    prior_equity = base.equity
    shares_outstanding = float(port_cfg.get("shares_outstanding", 0.0))

    # Seed trading/other income from base year when config defaults are zero
    if float(port_cfg.get("trading_income_annual", 0.0)) == 0.0 and base.trading_gains > 0:
        port_cfg["trading_income_annual"] = base.trading_gains
    if float(port_cfg.get("other_income_annual", 0.0)) == 0.0:
        other_ann = base.fx_gains + base.other_operating_income
        if other_ann != 0.0:
            port_cfg["other_income_annual"] = other_ann
    # Seed intangibles from base year when config defaults are zero
    if float(port_cfg.get("goodwill", 0.0)) == 0.0 and float(port_cfg.get("other_intangibles", 0.0)) == 0.0 and base.intangibles > 0:
        port_cfg["other_intangibles"] = base.intangibles

    # ------------------------------------------------------------------
    # 4. Quarterly loop
    # ------------------------------------------------------------------
    results: list[ProjectedFinancials] = []
    prior_pnl = pnl
    prior_bs  = bs
    prior_cap = capital
    prior_ecl = ecl
    prior_vbm = None
    prior_rate = rate_env.policy_rate
    prior_aq   = aq
    prior_pf_cor = 0.0
    prior_funding = funding

    opex_q = (base.admin_expenses + base.depreciation) / 4

    for i, period in enumerate(quarters):
        # Rate path override
        if rate_env.rate_path and i < len(rate_env.rate_path):
            rate_env = RateEnvironment(
                policy_rate=rate_env.rate_path[i],
                euribor_3m=rate_env.rate_path[i] - 0.005,
                euribor_6m=rate_env.rate_path[i] - 0.003,
                swap_2y=rate_env.rate_path[i] - 0.008,
                swap_5y=rate_env.rate_path[i] - 0.010,
                swap_10y=rate_env.rate_path[i] - 0.008,
                rate_path=rate_env.rate_path,
            )

        rate_delta_q = rate_env.policy_rate - prior_rate

        # --- Funding ---
        funding = apply_deposit_pass_through(
            funding, rate_env, prior_rate=prior_rate, period=period,
            retail_beta=float(port_cfg.get("deposit_beta", 0.30)),
        )
        prior_rate = rate_env.policy_rate

        # --- FTP ---
        ftp_curve = build_ftp_curves(rate_env, funding, period)

        # --- Balance sheet ---
        # Equity pinned to prior quarter's own_funds (one-period lag avoids
        # circular dependency between capital and balance sheet modules).
        bs = project_balance_sheet(
            prior_bs, period,
            loan_growth_q=float(port_cfg["loan_growth_q"]),
            fvoci_growth_q=float(port_cfg["fvoci_growth_q"]),
            ecl_delta=0.0,  # ECL allowance patched after ECL step (below)
            funding=funding,
            equity_constraint=prior_cap.own_funds if i > 0 else None,
        )

        # --- Funding gap fill ---
        # If assets grew faster than deposits/wholesale, bs.funding_gap > 0.
        # Fill with short-term interbank at DFR + gap_spread.
        if bs.funding_gap > 0:
            funding = apply_funding_gap(
                funding, bs.funding_gap, rate_env.policy_rate,
                gap_spread=float(port_cfg.get("interbank_gap_spread", 0.0010)),
            )

        # --- Asset quality (BEFORE ECL and P&L) ---
        # AQ must run first so ECL sees current-quarter stage splits.
        aq = calculate_asset_quality(
            aq, bs, period,
            default_rate_q=float(port_cfg["default_rate_q"]),
            cure_rate_q=float(port_cfg["cure_rate_q"]),
            write_off_rate_q=float(port_cfg["write_off_rate_q"]),
            disposal_rate_q=float(port_cfg.get("npe_disposal_rate_q", 0.0)),
            stage2_proportion=float(port_cfg["stage2_proportion"]),
            stress_default_overlay=stress_default_overlay,
        )

        # --- ECL (BEFORE P&L) ---
        # Uses current-quarter AQ stages; charge flows into P&L below.
        ecl = calculate_ecl(
            aq, period, prior_ecl,
            weight_base=w_base, weight_adverse=w_adv, weight_severe=w_sev,
            pd_mult_adverse=pd_mult_adv, pd_mult_severe=pd_mult_sev,
            obs_commitments_pct=float(port_cfg.get("obs_commitments_pct", 0.15)),
            obs_ccf=float(port_cfg.get("obs_ccf", 0.75)),
        )

        # --- Patch BS with current-quarter ECL allowance ---
        # The BS was built before ECL ran; now update ecl_allowance and loans_net
        # so that P&L interest income is computed on the correct net loan base.
        ecl_stock_delta = ecl.ecl_total - prior_ecl.ecl_total
        if ecl_stock_delta != 0:
            new_allowance = max(0.0, bs.ecl_allowance + ecl_stock_delta)
            bs = dataclasses.replace(
                bs,
                ecl_allowance=new_allowance,
                loans_net=max(0.0, bs.loans_gross - new_allowance),
            )

        # --- P&L ---
        # Now receives current-quarter ecl.ecl_charge (not prior's).
        # AUM growth (if AUM-driven asset_mgmt fees are in use)
        if aum_q > 0:
            aum_q = aum_q * (1 + float(port_cfg.get("aum_growth_q", 0.010)))

        # Legacy flat opex fallback (only used when prior_pnl.opex_detail is None)
        opex_q = opex_q * (1 + float(port_cfg["opex_growth_q"]))

        pnl = calculate_pnl(
            bs, funding, rate_env, period, prior_bs=prior_bs,
            loan_yield=float(port_cfg["loan_yield"]),
            bond_yield=float(port_cfg["bond_yield"]),
            fee_growth_q=float(port_cfg["fee_growth_q"]),
            base_fee_income=prior_pnl.fee_income_net,
            trading_income_annual=float(port_cfg.get("trading_income_annual", 0.0)),
            other_income_annual=float(port_cfg.get("other_income_annual", 0.0)),
            admin_expenses_q=opex_q * (1 - float(port_cfg.get("depn_pct", 0.15))),
            depreciation_q=opex_q * float(port_cfg.get("depn_pct", 0.15)),
            ecl_charge_q=ecl.total_ecl_charge_q,
            tax_rate=float(port_cfg["tax_rate"]),
            personnel_pct=float(port_cfg.get("personnel_pct", 0.60)),
            ga_pct=float(port_cfg.get("ga_pct", 0.25)),
            depn_pct=float(port_cfg.get("depn_pct", 0.15)),
            current_tax_rate=float(port_cfg.get("current_tax_rate", 0.20)),
            deferred_tax_rate=float(port_cfg.get("deferred_tax_rate", 0.02)),
            fee_weights=fee_weights,
            # Volume-driven fee model (active when prior_pnl has fee_detail set)
            prior_fee_detail=prior_pnl.fee_detail,
            retail_fee_growth_q=float(port_cfg.get("retail_fee_growth_q", 0.008)),
            corporate_fee_growth_q=float(port_cfg.get("corporate_fee_growth_q", 0.008)),
            aum=aum_q,
            aum_growth_q=float(port_cfg.get("aum_growth_q", 0.010)),
            mgmt_fee_rate=float(port_cfg.get("mgmt_fee_rate", 0.005)),
            treasury_fee_yield=float(port_cfg.get("treasury_fee_yield", 0.0008)),
            # Per-line opex model (active when prior_pnl has opex_detail set)
            prior_opex_detail=prior_pnl.opex_detail,
            personnel_growth_q=float(port_cfg.get("personnel_growth_q", 0.005)),
            ga_growth_q=float(port_cfg.get("ga_growth_q", 0.003)),
            capex_q=float(port_cfg.get("capex_q", 0.0)),
            da_life_years=float(port_cfg.get("da_life_years", 5.0)),
        )

        # --- Payout ---
        payout_assumptions = PayoutAssumptions(
            cet1_target=float(port_cfg.get("cet1_target", 0.15)),
            regular_cash_dividend_pct=float(port_cfg.get("regular_cash_dividend_pct", 0.40)),
            buyback_pct=float(port_cfg.get("buyback_pct", 0.20)),
            extraordinary_payout_eur=float(port_cfg.get("extraordinary_payout_eur", 0.0)),
            extraordinary_quarter=int(port_cfg.get("extraordinary_quarter", 0)),
        )
        payout = calculate_payout(
            pnl, prior_cap, period, i + 1,
            rwa=prior_cap.rwa_total,
            assumptions=payout_assumptions,
            prior_shares=shares_outstanding,
        )

        # --- DTA/DTC ---
        dta_state = calculate_dta_state(
            prior_dta, period, payout,
            cet1_capital=prior_cap.cet1_capital,
            dtc_statutory_schedule=port_cfg.get("dtc_statutory_schedule"),
            dtc_distribution_factor=float(port_cfg.get("dtc_distribution_factor", 0.29)),
        )

        # --- Capital ---
        capital, cap_buffers, mrel_view = calculate_capital(
            prior_cap, pnl, bs, period, payout, dta_state,
            prior_loans_gross=prior_bs.loans_gross,
            goodwill=float(port_cfg.get("goodwill", 0.0)),
            other_intangibles=float(port_cfg.get("other_intangibles", 0.0)),
            sa_rwa_estimate=float(port_cfg.get("sa_rwa_estimate", 0.0)),
            at1_coupon_rate=float(port_cfg.get("at1_coupon_rate", 0.06)),
            shares_outstanding=shares_outstanding,
            p2r=float(port_cfg.get("p2r", 0.015)),
            ccyb=float(port_cfg.get("ccyb", 0.0)),
            osii=float(port_cfg.get("osii", 0.0)),
            snp_eligible=float(port_cfg.get("snp_eligible", 0.0)),
            mrel_req_pct=float(port_cfg.get("mrel_req_pct", 0.0)),
        )

        # --- OCI ---
        oci = calculate_oci(
            pnl_net_profit=pnl.net_profit,
            period=period,
            bond_revaluation_sensitivity=float(port_cfg.get("bond_revaluation_sensitivity", 0.0)),
            rate_delta_q=rate_delta_q,
            hedge_reserve_annual=float(port_cfg.get("hedge_reserve_annual", 0.0)),
            pension_actuarial_annual=float(port_cfg.get("pension_actuarial_annual", 0.0)),
        )

        # --- Equity bridge ---
        eq_bridge = calculate_equity_bridge(
            prior_equity=prior_equity,
            tci=oci.total_comprehensive_income,
            payout=payout,
            at1_coupon_q=capital.at1_coupons_q,
            capital_actions_q=0.0,
            dtc_cet1_addon=dta_state.dtc_cet1_addon,
            period=period,
            bs_equity=bs.equity,
        )

        # --- Liquidity ---
        liquidity = calculate_liquidity(bs, funding, period,
                                        hqla_ratio=float(port_cfg.get("hqla_ratio", 0.20)))

        # --- RAROC ---
        segment_raroc = calculate_segment_raroc(pnl, capital, period)

        # --- Share count: decrement for buybacks ---
        share_price = float(port_cfg.get("share_price", 0.0))
        if payout.buyback > 0 and share_price > 0 and shares_outstanding > 0:
            shares_bought_back = payout.buyback / share_price  # EUR mn / EUR per share = mn shares
            shares_outstanding = max(0.0, shares_outstanding - shares_bought_back)

        # --- VBM ---
        vbm = calculate_vbm(
            pnl, bs, capital, period, prior_vbm=prior_vbm,
            shares_outstanding=shares_outstanding,
            market_price_per_share=share_price,
            dividend_payout=float(port_cfg.get("regular_cash_dividend_pct", 0.40)),
        )

        # --- Bridges ---
        capital_wf = calculate_capital_waterfall(prior_cap, capital, pnl, payout, dta_state, period)
        pat_bridge = calculate_pat_bridge(prior_pnl, pnl)
        nii_bridge = calculate_nii_bridge(prior_pnl, pnl, prior_bs, bs,
                                         prior_funding=prior_funding, curr_funding=funding)
        roe_bridge = calculate_roe_bridge(prior_pnl, pnl, prior_bs, bs)
        fee_bridge = calculate_fee_bridge(prior_pnl, pnl)

        curr_cor = pnl.ecl_charge * 4 / bs.loans_gross if bs.loans_gross > 0 else 0.0
        cor_bridge = calculate_cor_bridge(
            prior_cor=prior_pf_cor,
            curr_cor=curr_cor,
            prior_aq=prior_aq,
            curr_aq=aq,
            prior_bs=prior_bs,
            curr_bs=bs,
        )
        prior_pf_cor = curr_cor

        # --- Loan book gross bridge ---
        repayment_rate = float(port_cfg.get("loan_repayment_rate_annual", 0.15))
        originations = (prior_bs.loans_gross * float(port_cfg.get("loan_growth_q", 0.01))
                        + prior_bs.loans_gross * repayment_rate / 4)
        repayments = prior_bs.loans_gross * repayment_rate / 4
        loan_book_bridge = {
            "opening_gross": prior_bs.loans_gross,
            "originations": originations,
            "repayments": -repayments,
            "write_offs": -aq.written_off,
            "fx_other": 0.0,
            "closing_gross": bs.loans_gross,
            "check": bs.loans_gross - (prior_bs.loans_gross + originations - repayments - aq.written_off),
        }

        # --- New hot-path scalars ---
        total_deposits = funding.retail_deposits + funding.corporate_deposits
        ldr = bs.loans_net / total_deposits if total_deposits > 0 else 0.0

        fee_tot = pnl.fee_detail.total if pnl.fee_detail else pnl.fee_income_net
        trd_inc = pnl.trading_income
        toi_ann = pnl.total_operating_income * 4
        nir = (fee_tot * 4 + trd_inc * 4) / toi_ann if toi_ann > 0 else 0.0

        ecl_total_q = ecl.ecl_total + ecl.obs_ecl_provision
        npl_g = aq.npl_gross
        tangible_eq = capital.tangible_equity if capital.tangible_equity > 0 else bs.equity
        texas = npl_g / (tangible_eq + ecl_total_q) if (tangible_eq + ecl_total_q) > 0 else 0.0

        ppp_ann = pnl.pre_provision_profit * 4
        breakeven_cor = ppp_ann / bs.loans_gross * 10000 if bs.loans_gross > 0 else 0.0

        retained_q = pnl.net_profit - payout.total_payout
        cap_gen_bps = (retained_q * 4) / capital.rwa_total * 10000 if capital.rwa_total > 0 else 0.0

        ni_income_pct = (fee_tot + trd_inc) / (pnl.nii * 4) if pnl.nii * 4 > 0 else 0.0
        s2_cov = ecl.ecl_stage2 / aq.stage2_gross if aq.stage2_gross > 0 else 0.0

        nii_sens = _to_dict(pnl.nii_sensitivity) if pnl.nii_sensitivity else {}

        # --- Assemble ProjectedFinancials ---
        pf = ProjectedFinancials(
            plan_id=plan.id,
            scenario_id=scenario.id if scenario else None,
            period=period,
            is_stressed=(scenario is not None),
            # Existing hot-path scalars
            cet1_ratio=capital.cet1_ratio,
            t1_ratio=capital.t1_ratio,
            total_capital_ratio=capital.total_capital_ratio,
            rwa=capital.rwa_total,
            nii=pnl.nii * 4,
            nim=pnl.nim,
            roe=pnl.roe,
            rote=capital.rote,
            npl_ratio=aq.npl_ratio,
            cost_of_risk=curr_cor,
            lcr=liquidity.lcr,
            nsfr=liquidity.nsfr,
            leverage_ratio=capital.leverage_ratio,
            cir=pnl.cir,
            # New hot-path scalars
            ldr=ldr,
            nir=nir,
            texas_ratio=texas,
            breakeven_cor_bps=breakeven_cor,
            capital_gen_rate_bps=cap_gen_bps,
            non_interest_income_pct=ni_income_pct,
            stage2_coverage=s2_cov,
            # Detail blobs
            pnl_detail={
                **_to_dict(pnl),
                "nii_sensitivity": nii_sens,
            },
            balance_sheet_detail={
                "before": _to_dict(prior_bs),
                "after":  _to_dict(bs),
                "loan_book_bridge": loan_book_bridge,
            },
            capital_detail={
                **_to_dict(capital),
                "buffers": _to_dict(cap_buffers),
                "mrel": _to_dict(mrel_view),
                "payout": _to_dict(payout),
                "waterfall": capital_wf.to_dict(),
                "dta": _to_dict(dta_state),
            },
            asset_quality_detail=_to_dict(aq),
            ecl_detail=_to_dict(ecl),
            liquidity_detail=_to_dict(liquidity),
            bridges={
                "pat":            pat_bridge.to_dict(),
                "nii":            nii_bridge.to_dict(),
                "cet1_waterfall": capital_wf.to_dict(),
                "cor":            cor_bridge.to_dict(),
                "fees":           fee_bridge.to_dict(),
                "roe":            roe_bridge.to_dict(),
                "equity":         _to_dict(eq_bridge),
            },
            segment_raroc=[_to_dict(s) for s in segment_raroc],
            vbm_metrics=_to_dict(vbm),
            liquidity_survival={"survival_horizon_days": liquidity.survival_horizon_days},
            oci_detail=_to_dict(oci),
            equity_bridge=_to_dict(eq_bridge),
            dta_detail=_to_dict(dta_state),
            nii_sensitivity=nii_sens,
            loan_book_bridge=loan_book_bridge,
            warnings=[],
        )
        results.append(pf)

        # Roll forward
        prior_pnl   = pnl
        prior_bs    = bs
        prior_cap   = capital
        prior_ecl   = ecl
        prior_vbm   = vbm
        prior_aq    = aq
        prior_funding = funding
        prior_dta   = DTAState(
            period=period,
            dta_regular=dta_state.dta_regular,
            dtc_stock_opening=dta_state.dtc_stock_closing,
        )
        # IFRS book equity tracks the equity bridge waterfall (not own_funds).
        # own_funds (CET1+AT1+T2) is used for the BS equity constraint separately.
        prior_equity = eq_bridge.closing_equity

    log.info("Projection complete — %d quarters generated", len(results))
    return results
