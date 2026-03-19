"""
modules/calculation/bridges.py — CET1 / NII / ROE / RWA waterfall bridges.

A bridge decomposes the change in a KPI between two periods into
labelled driver components that sum to the total change.

All bridges are plain dicts of {driver_name: EUR_mn_change | ratio_change}.
Bridge components are ordered from largest positive driver to largest negative.

CET1 bridge: retained_earnings, capital_action, rwa_inflation, model_change, other
NII bridge: volume, rate_repricing, mix, fx (flat for PoC), other
ROE bridge: nii_delta, fee_delta, cost_delta, ecl_delta, tax_delta, capital_delta
RWA bridge: credit_risk_volume, credit_risk_density, market_risk, operational_risk, other
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class CET1Bridge:
    """CET1 ratio waterfall between two periods (in ratio points, e.g. 0.005 = +50bps)."""
    prior_cet1_ratio: float
    retained_earnings: float        # +net profit × (1 - payout) / RWA
    dividends: float                # -payout × net profit / RWA
    capital_actions: float          # +/- share issuance / buybacks / AT1 calls
    rwa_volume_effect: float        # - (RWA growth at constant density) / prior RWA
    rwa_density_effect: float       # - (density change) / prior RWA
    other: float                    # residual (model updates, deductions, etc.)
    current_cet1_ratio: float

    @property
    def check(self) -> float:
        """Should ≈ 0 for a clean bridge."""
        return (
            self.current_cet1_ratio
            - self.prior_cet1_ratio
            - self.retained_earnings
            - self.dividends
            - self.capital_actions
            - self.rwa_volume_effect
            - self.rwa_density_effect
            - self.other
        )

    def to_dict(self) -> dict:
        return {
            "prior": self.prior_cet1_ratio,
            "retained_earnings": self.retained_earnings,
            "dividends": self.dividends,
            "capital_actions": self.capital_actions,
            "rwa_volume": self.rwa_volume_effect,
            "rwa_density": self.rwa_density_effect,
            "other": self.other,
            "current": self.current_cet1_ratio,
            "check": self.check,
        }


@dataclass
class NIIBridge:
    """NII waterfall between two periods (EUR mn)."""
    prior_nii: float
    volume_effect: float            # avg_asset growth × prior yield
    yield_effect: float             # repricing: avg_asset × (new yield - prior yield)
    funding_cost_volume: float      # avg_liability growth × prior rate
    funding_cost_repricing: float   # avg_liability × (new rate - prior rate)
    mix_effect: float               # product mix shift
    other: float
    current_nii: float

    @property
    def check(self) -> float:
        return (
            self.current_nii
            - self.prior_nii
            - self.volume_effect
            - self.yield_effect
            - self.funding_cost_volume
            - self.funding_cost_repricing
            - self.mix_effect
            - self.other
        )

    def to_dict(self) -> dict:
        return {
            "prior": self.prior_nii,
            "volume": self.volume_effect,
            "yield_repricing": self.yield_effect,
            "funding_cost_volume": self.funding_cost_volume,
            "funding_cost_repricing": self.funding_cost_repricing,
            "mix": self.mix_effect,
            "other": self.other,
            "current": self.current_nii,
            "check": self.check,
        }


@dataclass
class ROEBridge:
    """ROE waterfall between two periods (in ratio points)."""
    prior_roe: float
    nii_effect: float
    fee_effect: float
    cost_effect: float
    ecl_effect: float
    tax_effect: float
    capital_base_effect: float      # change in equity base (dilution / accretion)
    other: float
    current_roe: float

    @property
    def check(self) -> float:
        return (
            self.current_roe
            - self.prior_roe
            - self.nii_effect
            - self.fee_effect
            - self.cost_effect
            - self.ecl_effect
            - self.tax_effect
            - self.capital_base_effect
            - self.other
        )

    def to_dict(self) -> dict:
        return {
            "prior": self.prior_roe,
            "nii": self.nii_effect,
            "fee": self.fee_effect,
            "cost": self.cost_effect,
            "ecl": self.ecl_effect,
            "tax": self.tax_effect,
            "capital_base": self.capital_base_effect,
            "other": self.other,
            "current": self.current_roe,
            "check": self.check,
        }


def calculate_nii_bridge(prior_pnl, curr_pnl, prior_bs, curr_bs,
                         prior_funding=None, curr_funding=None) -> NIIBridge:
    """
    Build NII bridge between two quarters (EUR mn).

    Decomposes NII change into:
    - Volume effect (asset side): loan/bond/cash volume growth × prior yield
    - Yield effect: repricing on existing asset volumes
    - Funding cost volume: liability volume growth × prior cost
    - Funding cost repricing: rate change on existing liabilities
    - Mix/other: residual
    """
    # --- Asset-side decomposition ---
    # Prior period implied yields (annualised)
    prior_nii_d = getattr(prior_pnl, 'nii_detail', None)
    curr_nii_d = getattr(curr_pnl, 'nii_detail', None)

    # Volume effect: ΔVolume × prior_yield / 4
    loan_delta = curr_bs.loans_net - prior_bs.loans_net
    bond_delta = curr_bs.fvoci_assets - prior_bs.fvoci_assets
    cash_delta = curr_bs.cash - prior_bs.cash

    prior_loan_yield = (
        prior_pnl.interest_income / prior_bs.loans_net * 4
        if prior_bs.loans_net > 0 else 0.055
    ) if not prior_nii_d else (
        prior_nii_d.loan_interest_income / prior_bs.loans_net * 4
        if prior_bs.loans_net > 0 else 0.055
    )
    prior_bond_yield = (
        prior_nii_d.bond_interest_income / prior_bs.fvoci_assets * 4
        if prior_nii_d and prior_bs.fvoci_assets > 0 else 0.040
    )
    prior_cash_yield = (
        prior_nii_d.cash_interest_income / prior_bs.cash * 4
        if prior_nii_d and prior_bs.cash > 0 else 0.037
    )

    asset_volume_effect = (
        loan_delta * prior_loan_yield / 4
        + bond_delta * prior_bond_yield / 4
        + cash_delta * prior_cash_yield / 4
    )

    # Yield effect: prior_volume × Δyield / 4
    if curr_nii_d and prior_nii_d:
        curr_loan_yield = (
            curr_nii_d.loan_interest_income / curr_bs.loans_net * 4
            if curr_bs.loans_net > 0 else prior_loan_yield
        )
        curr_bond_yield = (
            curr_nii_d.bond_interest_income / curr_bs.fvoci_assets * 4
            if curr_bs.fvoci_assets > 0 else prior_bond_yield
        )
        curr_cash_yield = (
            curr_nii_d.cash_interest_income / curr_bs.cash * 4
            if curr_bs.cash > 0 else prior_cash_yield
        )
        yield_effect = (
            prior_bs.loans_net * (curr_loan_yield - prior_loan_yield) / 4
            + prior_bs.fvoci_assets * (curr_bond_yield - prior_bond_yield) / 4
            + prior_bs.cash * (curr_cash_yield - prior_cash_yield) / 4
        )
    else:
        # Fallback: residual after volume
        yield_effect = (curr_pnl.interest_income - prior_pnl.interest_income) - asset_volume_effect

    # --- Funding-side decomposition ---
    if prior_funding and curr_funding:
        prior_total_fund = prior_funding.total_funding
        curr_total_fund = curr_funding.total_funding
        prior_cof = prior_funding.blended_cost_of_funds
        curr_cof = curr_funding.blended_cost_of_funds
        fund_vol_delta = curr_total_fund - prior_total_fund
        # Funding cost volume: ΔVolume × prior_cost / 4 (higher cost = negative for NII)
        funding_cost_vol = -(fund_vol_delta * prior_cof / 4)
        # Funding cost repricing: prior_volume × Δcost / 4
        funding_cost_repr = -(prior_total_fund * (curr_cof - prior_cof) / 4)
    else:
        # Fallback: split interest expense change
        ie_delta = curr_pnl.interest_expense - prior_pnl.interest_expense
        funding_cost_vol = -ie_delta * 0.5
        funding_cost_repr = -ie_delta * 0.5

    # Mix / other: residual to close the bridge
    nii_delta = curr_pnl.nii - prior_pnl.nii
    explained = asset_volume_effect + yield_effect + funding_cost_vol + funding_cost_repr
    mix_other = nii_delta - explained

    return NIIBridge(
        prior_nii=prior_pnl.nii,
        volume_effect=asset_volume_effect,
        yield_effect=yield_effect,
        funding_cost_volume=funding_cost_vol,
        funding_cost_repricing=funding_cost_repr,
        mix_effect=mix_other,
        other=0.0,
        current_nii=curr_pnl.nii,
    )


def calculate_roe_bridge(prior_pnl, curr_pnl, prior_bs, curr_bs) -> "ROEBridge":
    """Build ROE bridge between two quarters (in ratio points)."""
    avg_equity_prior = prior_bs.equity
    avg_equity_curr  = curr_bs.equity

    def _roe_effect(income_delta: float, equity: float) -> float:
        return (income_delta * 4) / equity if equity > 0 else 0.0

    nii_effect  = _roe_effect(curr_pnl.nii - prior_pnl.nii, avg_equity_curr)
    fee_effect  = _roe_effect(curr_pnl.fee_income_net - prior_pnl.fee_income_net, avg_equity_curr)
    cost_effect = _roe_effect(-(curr_pnl.total_opex - prior_pnl.total_opex), avg_equity_curr)
    ecl_effect  = _roe_effect(-(curr_pnl.ecl_charge - prior_pnl.ecl_charge), avg_equity_curr)
    tax_effect  = _roe_effect(-(curr_pnl.tax_charge - prior_pnl.tax_charge), avg_equity_curr)

    equity_delta = avg_equity_curr - avg_equity_prior
    cap_effect = (
        -(prior_pnl.net_profit * 4 * equity_delta)
        / (avg_equity_curr * avg_equity_prior)
        if avg_equity_curr > 0 and avg_equity_prior > 0 else 0.0
    )

    total_roe_delta = curr_pnl.roe - prior_pnl.roe
    other = (total_roe_delta
             - nii_effect - fee_effect - cost_effect
             - ecl_effect - tax_effect - cap_effect)

    return ROEBridge(
        prior_roe=prior_pnl.roe,
        nii_effect=nii_effect,
        fee_effect=fee_effect,
        cost_effect=cost_effect,
        ecl_effect=ecl_effect,
        tax_effect=tax_effect,
        capital_base_effect=cap_effect,
        other=other,
        current_roe=curr_pnl.roe,
    )


# ---------------------------------------------------------------------------
# PAT Bridge
# ---------------------------------------------------------------------------

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
    delta_ecl: float
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
    def _opex_attr(pnl, attr):
        od = getattr(pnl, 'opex_detail', None)
        return getattr(od, attr, 0.0) if od else 0.0

    d_pers = -(_opex_attr(curr_pnl, 'personnel_costs') - _opex_attr(prior_pnl, 'personnel_costs'))
    d_ga   = -(_opex_attr(curr_pnl, 'ga_expenses') - _opex_attr(prior_pnl, 'ga_expenses'))
    d_depn = -(_opex_attr(curr_pnl, 'depreciation') - _opex_attr(prior_pnl, 'depreciation'))
    d_nii  = curr_pnl.nii - prior_pnl.nii

    def _fee_total(pnl):
        fd = getattr(pnl, 'fee_detail', None)
        return getattr(fd, 'total', pnl.fee_income_net) if fd else pnl.fee_income_net

    d_fee = _fee_total(curr_pnl) - _fee_total(prior_pnl)
    d_trd = getattr(curr_pnl, 'trading_income', 0.0) - getattr(prior_pnl, 'trading_income', 0.0)
    d_oth = getattr(curr_pnl, 'other_income', 0.0) - getattr(prior_pnl, 'other_income', 0.0)
    d_ecl = -(curr_pnl.ecl_charge - prior_pnl.ecl_charge)
    d_tax = -(curr_pnl.tax_charge - prior_pnl.tax_charge)

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


# ---------------------------------------------------------------------------
# Capital Waterfall (EUR mn)
# ---------------------------------------------------------------------------

@dataclass
class CapitalWaterfall:
    """Capital waterfall in EUR mn (replaces ratio-point CET1 bridge)."""
    period: date
    opening_cet1_eur: float
    pat_q: float
    at1_coupons: float
    cash_dividends: float
    buybacks: float
    extraordinary_payout: float
    capital_actions: float
    rwa_growth_drag: float
    dtc_cet1_addon: float
    dta_deduction_change: float
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
                 - rwa_drag + dtc_addon)
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


# ---------------------------------------------------------------------------
# Cost of Risk Bridge
# ---------------------------------------------------------------------------

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
    vol_eff = (to_bps(prior_cor) * (curr_bs.loans_gross - prior_bs.loans_gross) / prior_bs.loans_gross
               if prior_bs.loans_gross > 0 else 0.0)
    s3_delta = curr_aq.stage3_gross - prior_aq.stage3_gross
    stage_mig = (to_bps(s3_delta / curr_bs.loans_gross * 0.40)
                 if curr_bs.loans_gross > 0 else 0.0)
    return CORBridge(prior_cor_bps=to_bps(prior_cor), volume_effect=vol_eff,
                     stage_migration=stage_mig, pd_lgd_overlay=0.0, obs_change=0.0,
                     write_off_change=0.0, other=d_bps - vol_eff - stage_mig,
                     current_cor_bps=to_bps(curr_cor))


# ---------------------------------------------------------------------------
# Fee Bridge
# ---------------------------------------------------------------------------

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
    def _seg(pnl, attr):
        fd = getattr(pnl, 'fee_detail', None)
        return getattr(fd, attr, 0.0) if fd else 0.0

    def _total(pnl):
        fd = getattr(pnl, 'fee_detail', None)
        return getattr(fd, 'total', pnl.fee_income_net) if fd else pnl.fee_income_net

    return FeeBridge(
        prior_fees_total=_total(prior_pnl),
        delta_retail=_seg(curr_pnl, 'retail') - _seg(prior_pnl, 'retail'),
        delta_corporate=_seg(curr_pnl, 'corporate') - _seg(prior_pnl, 'corporate'),
        delta_asset_mgmt=_seg(curr_pnl, 'asset_mgmt') - _seg(prior_pnl, 'asset_mgmt'),
        delta_treasury=_seg(curr_pnl, 'treasury') - _seg(prior_pnl, 'treasury'),
        other=0.0,
        current_fees_total=_total(curr_pnl),
    )
