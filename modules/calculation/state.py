"""
modules/calculation/state.py — Typed intermediate states for the calculation engine.

All states are plain Python dataclasses — no external dependencies.
Amounts are in EUR millions unless documented otherwise.
Ratios are as decimals (e.g. 0.145 = 14.5%).

Also provides BaseYearExtractor which reads the base_year_snapshots table and
maps EBA TrEx SDD item codes to named scalar fields.

SDD codes are loaded from config/data_mappings.yaml at import time.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

log = logging.getLogger(__name__)


def _load_sdd_codes() -> dict:
    """Load SDD item codes from config/data_mappings.yaml."""
    try:
        from config.loader import load_sdd_codes as _load
        return _load()
    except Exception as exc:
        log.warning("Could not load SDD codes from YAML: %s", exc)
        return {}


_SDD_CONFIG = _load_sdd_codes()

_PNL_ITEMS: dict[str, int] = (
    _SDD_CONFIG.get("pnl", {}).get("items", {}) or {
        "interest_income": 2520301,
        "interest_income_bonds": 2520302,
        "interest_income_loans": 2520303,
        "interest_expense": 2520304,
        "deposit_expense": 2520305,
        "fee_income_net": 2520309,
        "trading_gains": 2520311,
        "fx_gains": 2520314,
        "other_operating_income": 2520315,
        "total_operating_income": 2520316,
        "admin_expenses": 2520317,
        "depreciation": 2520318,
        "provisions": 2520319,
        "ecl_charge": 2520324,
        "profit_before_tax": 2520332,
        "profit_after_tax": 2520333,
        "net_profit": 2520335,
    }
)

_CAPITAL_ITEMS: dict[str, int] = (
    _SDD_CONFIG.get("capital", {}).get("items", {}) or {
        "own_funds": 2520101,
        "cet1_capital": 2520102,
        "at1_capital": 2520118,
        "tier2": 2520122,
        "intangibles": 2520110,
        "dta": 2520111,
        "dta_temp_diff": 2520106,
    }
)

_RWA_ITEMS: dict[str, int] = (
    _SDD_CONFIG.get("rwa", {}).get("items", {}) or {
        "rwa_credit": 2520201,
        "rwa_market": 2520210,
        "rwa_operational": 2520215,
        "rwa_ccr": 2520206,
    }
)

_ASSET_ITEMS: dict[str, int] = (
    _SDD_CONFIG.get("assets", {}).get("items", {}) or {
        "cash": 2521001,
        "trading_assets": 2521002,
        "fvoci_assets": 2521005,
        "amortised_cost": 2521006,
        "total_assets": 2521010,
        "loans_gross": 2521019,
        "bonds_gross": 2521018,
    }
)

_LIABILITY_ITEMS: dict[str, int] = (
    _SDD_CONFIG.get("liabilities", {}).get("items", {}) or {
        "trading_liabilities": 2521201,
        "amortised_cost_liab": 2521204,
        "total_liabilities": 2521214,
    }
)

_NPE_ITEMS: dict[str, int] = (
    _SDD_CONFIG.get("npe", {}).get("items", {}) or {
        "npe_total": 2520603,
        "npe_performing": 2520603,
        "npe_stage2": 2520603,
        "npe_gross": 2520603,
        "npe_stage3": 2520603,
    }
)

_NPE_COLUMNS: dict[str, int] = (
    _SDD_CONFIG.get("npe", {}).get("columns", {}) or {
        "total": 3,
        "performing": 4,
        "stage2": 5,
        "gross": 7,
        "stage3": 10,
    }
)

_ECL_ALLOWANCE_ITEMS: dict[str, int] = (
    _SDD_CONFIG.get("ecl_allowance", {}).get("items", {}) or {
        "performing": 2520613,
        "stage2": 2520613,
        "npe": 2520613,
    }
)

_ECL_ALLOWANCE_COLUMNS: dict[str, int] = (
    _SDD_CONFIG.get("ecl_allowance", {}).get("columns", {}) or {
        "performing": 11,
        "stage2": 12,
        "npe": 13,
    }
)


# ---------------------------------------------------------------------------
# Base year extractor
# ---------------------------------------------------------------------------

class BaseYearExtractor:
    """
    Reads the base_year_snapshots table for a given bank/snapshot and
    resolves named scalar fields from the SDD item code mappings above.

    Usage:
        extractor = BaseYearExtractor(db, bank_lei="5UMCZOEYKCVFAW8ZLO05")
        base = extractor.extract()
    """

    # Column priority for annual figures (full-year preferred)
    _PNL_COL_PRIORITY = [4, 6, 3, 5]   # column 4 = Dec FY; 6 = Jun H1 × 2 annualised
    _BS_COL_PRIORITY  = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17]

    def __init__(
        self,
        db: "Session",
        *,
        bank_lei: str | None = None,
        bank_name: str | None = None,
        snapshot_name: str | None = None,
    ) -> None:
        if not bank_lei and not bank_name:
            raise ValueError("Provide bank_lei or bank_name")
        self._db = db
        self._bank_lei = bank_lei
        self._bank_name = bank_name
        self._snapshot_name = snapshot_name
        self._rows: list | None = None

    def _load(self) -> list:
        if self._rows is not None:
            return self._rows
        from db.models import BaseYearSnapshot
        q = self._db.query(BaseYearSnapshot)
        if self._bank_lei:
            q = q.filter(BaseYearSnapshot.bank_lei == self._bank_lei)
        elif self._bank_name:
            q = q.filter(BaseYearSnapshot.bank_name == self._bank_name)
        if self._snapshot_name:
            q = q.filter(BaseYearSnapshot.snapshot_name == self._snapshot_name)
        self._rows = q.all()
        return self._rows

    def _lookup(
        self,
        template: str,
        item: int,
        col_priority: list[int],
        *,
        annualise_factor: float = 1.0,
    ) -> float:
        """Return first non-null amount matching template/item across col_priority."""
        rows = self._load()
        item_str = str(float(item))
        for col in col_priority:
            col_str = str(float(col))
            for r in rows:
                if (
                    r.template == template
                    and str(r.item) == item_str
                    and str(r.column) == col_str
                    and r.amount is not None
                ):
                    return r.amount * annualise_factor
        return 0.0

    def _lookup_sum(self, template: str, items: list[int], col_priority: list[int]) -> float:
        return sum(self._lookup(template, i, col_priority) for i in items)

    def extract(self) -> "BaseYear":
        """Extract all key base-year scalars and return a BaseYear dataclass."""
        p = self._PNL_COL_PRIORITY
        b = self._BS_COL_PRIORITY

        # Annualise H1 figures (col 6) if col 4 is zero
        interest_income = self._lookup("P&L", _PNL_ITEMS["interest_income"], [4]) or \
                          self._lookup("P&L", _PNL_ITEMS["interest_income"], [6]) * 2

        interest_expense = self._lookup("P&L", _PNL_ITEMS["interest_expense"], [4]) or \
                           self._lookup("P&L", _PNL_ITEMS["interest_expense"], [6]) * 2

        nii = interest_income - interest_expense

        fee_income = self._lookup("P&L", _PNL_ITEMS["fee_income_net"], [4]) or \
                     self._lookup("P&L", _PNL_ITEMS["fee_income_net"], [6]) * 2

        total_oi = self._lookup("P&L", _PNL_ITEMS["total_operating_income"], [4]) or \
                   self._lookup("P&L", _PNL_ITEMS["total_operating_income"], [6]) * 2

        admin_exp = abs(self._lookup("P&L", _PNL_ITEMS["admin_expenses"], [4]) or
                        self._lookup("P&L", _PNL_ITEMS["admin_expenses"], [6]) * 2)

        depn = abs(self._lookup("P&L", _PNL_ITEMS["depreciation"], [4]) or
                   self._lookup("P&L", _PNL_ITEMS["depreciation"], [6]) * 2)

        ecl_charge = abs(self._lookup("P&L", _PNL_ITEMS["ecl_charge"], [4]) or
                         self._lookup("P&L", _PNL_ITEMS["ecl_charge"], [6]) * 2)

        net_profit = self._lookup("P&L", _PNL_ITEMS["net_profit"], [4]) or \
                     self._lookup("P&L", _PNL_ITEMS["net_profit"], [6]) * 2

        profit_before_tax = self._lookup("P&L", _PNL_ITEMS["profit_before_tax"], [4]) or \
                            self._lookup("P&L", _PNL_ITEMS["profit_before_tax"], [6]) * 2

        # P&L detail — already mapped, just not previously extracted
        trading_gains = self._lookup("P&L", _PNL_ITEMS["trading_gains"], [4]) or \
                        self._lookup("P&L", _PNL_ITEMS["trading_gains"], [6]) * 2
        deposit_expense = abs(self._lookup("P&L", _PNL_ITEMS["deposit_expense"], [4]) or
                              self._lookup("P&L", _PNL_ITEMS["deposit_expense"], [6]) * 2)
        int_income_loans = self._lookup("P&L", _PNL_ITEMS["interest_income_loans"], [4]) or \
                           self._lookup("P&L", _PNL_ITEMS["interest_income_loans"], [6]) * 2
        int_income_bonds = self._lookup("P&L", _PNL_ITEMS["interest_income_bonds"], [4]) or \
                           self._lookup("P&L", _PNL_ITEMS["interest_income_bonds"], [6]) * 2
        fx_gains = self._lookup("P&L", _PNL_ITEMS["fx_gains"], [4]) or \
                   self._lookup("P&L", _PNL_ITEMS["fx_gains"], [6]) * 2
        other_oi = self._lookup("P&L", _PNL_ITEMS["other_operating_income"], [4]) or \
                   self._lookup("P&L", _PNL_ITEMS["other_operating_income"], [6]) * 2
        provisions = abs(self._lookup("P&L", _PNL_ITEMS["provisions"], [4]) or
                         self._lookup("P&L", _PNL_ITEMS["provisions"], [6]) * 2)

        cet1 = self._lookup("Capital", _CAPITAL_ITEMS["cet1_capital"], b)
        own_funds = self._lookup("Capital", _CAPITAL_ITEMS["own_funds"], b)

        # Capital detail — already mapped
        at1 = self._lookup("Capital", _CAPITAL_ITEMS["at1_capital"], b)
        tier2 = self._lookup("Capital", _CAPITAL_ITEMS["tier2"], b)
        intangibles = abs(self._lookup("Capital", _CAPITAL_ITEMS["intangibles"], b))
        dta = abs(self._lookup("Capital", _CAPITAL_ITEMS["dta"], b))
        dta_temp_diff = abs(self._lookup("Capital", _CAPITAL_ITEMS["dta_temp_diff"], b))

        rwa_credit = self._lookup("RWA OV1", _RWA_ITEMS["rwa_credit"], b)
        rwa_market = self._lookup("RWA OV1", _RWA_ITEMS["rwa_market"], b)
        rwa_opex   = self._lookup("RWA OV1", _RWA_ITEMS["rwa_operational"], b)
        rwa_total  = rwa_credit + rwa_market + rwa_opex

        total_assets = self._lookup("Assets", _ASSET_ITEMS["total_assets"], b)
        loans_ac = self._lookup("Assets", _ASSET_ITEMS["amortised_cost"], b)
        loans_gross = self._lookup("Assets", _ASSET_ITEMS["loans_gross"], b) or loans_ac
        cash = self._lookup("Assets", _ASSET_ITEMS["cash"], b)
        fvoci = self._lookup("Assets", _ASSET_ITEMS["fvoci_assets"], b)

        # Assets detail — already mapped
        bonds_gross = self._lookup("Assets", _ASSET_ITEMS["bonds_gross"], b)
        trading_assets = self._lookup("Assets", _ASSET_ITEMS["trading_assets"], b)

        total_liabilities = self._lookup("Liabilities", _LIABILITY_ITEMS["total_liabilities"], b)
        deposits_and_debt  = self._lookup("Liabilities", _LIABILITY_ITEMS["amortised_cost_liab"], b)

        equity = total_assets - total_liabilities if total_liabilities else (own_funds or cet1)

        # NPE: template "NPE", item from config, specific columns
        npe_item = _NPE_ITEMS.get("npe_gross", 2520603)
        npe_gross = self._lookup("NPE", npe_item, [_NPE_COLUMNS.get("gross", 7)])
        npe_performing = self._lookup("NPE", npe_item, [_NPE_COLUMNS.get("performing", 4)])
        npe_stage2 = self._lookup("NPE", npe_item, [_NPE_COLUMNS.get("stage2", 5)])
        npe_stage3 = self._lookup("NPE", npe_item, [_NPE_COLUMNS.get("stage3", 10)])
        npl_ratio = npe_gross / loans_gross if loans_gross > 0 else 0.0

        # ECL allowances: item from config, specific columns
        ecl_item = _ECL_ALLOWANCE_ITEMS.get("performing", 2520613)
        ecl_allow_performing = self._lookup("NPE", ecl_item, [_ECL_ALLOWANCE_COLUMNS.get("performing", 11)])
        ecl_allow_stage2 = self._lookup("NPE", ecl_item, [_ECL_ALLOWANCE_COLUMNS.get("stage2", 12)])
        ecl_allow_npe = self._lookup("NPE", ecl_item, [_ECL_ALLOWANCE_COLUMNS.get("npe", 13)])
        ecl_allowance_total = ecl_allow_performing + ecl_allow_npe

        cet1_ratio = cet1 / rwa_total if rwa_total > 0 else 0.0
        total_cap_ratio = own_funds / rwa_total if rwa_total > 0 else 0.0
        nim = nii / total_assets if total_assets > 0 else 0.0
        roe = net_profit / equity if equity > 0 else 0.0
        cir = (admin_exp + depn) / total_oi if total_oi > 0 else 0.0
        leverage_ratio = cet1 / total_assets if total_assets > 0 else 0.0

        return BaseYear(
            # P&L (EUR mn, annualised)
            interest_income=interest_income,
            interest_expense=interest_expense,
            nii=nii,
            fee_income_net=fee_income,
            total_operating_income=total_oi,
            admin_expenses=admin_exp,
            depreciation=depn,
            ecl_charge=ecl_charge,
            profit_before_tax=profit_before_tax,
            net_profit=net_profit,
            # P&L detail
            trading_gains=trading_gains,
            deposit_expense=deposit_expense,
            interest_income_loans=int_income_loans,
            interest_income_bonds=int_income_bonds,
            fx_gains=fx_gains,
            other_operating_income=other_oi,
            provisions=provisions,
            # Balance sheet (EUR mn)
            total_assets=total_assets,
            loans_ac=loans_ac,
            loans_gross=loans_gross,
            fvoci_assets=fvoci,
            cash=cash,
            bonds_gross=bonds_gross,
            trading_assets=trading_assets,
            total_liabilities=total_liabilities,
            deposits_and_debt=deposits_and_debt,
            equity=equity,
            # Capital
            cet1_capital=cet1,
            own_funds=own_funds,
            at1_capital=at1,
            tier2_capital=tier2,
            intangibles=intangibles,
            dta=dta,
            dta_temp_diff=dta_temp_diff,
            rwa_credit=rwa_credit,
            rwa_market=rwa_market,
            rwa_operational=rwa_opex,
            rwa_total=rwa_total,
            # Credit quality
            npe_gross=npe_gross,
            npl_ratio=npl_ratio,
            npe_performing=npe_performing,
            npe_stage2=npe_stage2,
            npe_stage3=npe_stage3,
            ecl_allow_performing=ecl_allow_performing,
            ecl_allow_stage2=ecl_allow_stage2,
            ecl_allow_npe=ecl_allow_npe,
            ecl_allowance_total=ecl_allowance_total,
            # Key ratios
            cet1_ratio=cet1_ratio,
            total_capital_ratio=total_cap_ratio,
            nim=nim,
            roe=roe,
            cir=cir,
            leverage_ratio=leverage_ratio,
        )


# ---------------------------------------------------------------------------
# Typed state dataclasses
# ---------------------------------------------------------------------------

@dataclass
class BaseYear:
    """Key scalar metrics extracted from the base year snapshot."""
    # P&L — EUR mn, annualised
    interest_income: float = 0.0
    interest_expense: float = 0.0
    nii: float = 0.0
    fee_income_net: float = 0.0
    total_operating_income: float = 0.0
    admin_expenses: float = 0.0
    depreciation: float = 0.0
    ecl_charge: float = 0.0
    profit_before_tax: float = 0.0
    net_profit: float = 0.0
    # P&L detail (EUR mn, annualised)
    trading_gains: float = 0.0
    deposit_expense: float = 0.0
    interest_income_loans: float = 0.0
    interest_income_bonds: float = 0.0
    fx_gains: float = 0.0
    other_operating_income: float = 0.0
    provisions: float = 0.0
    # Balance sheet — EUR mn
    total_assets: float = 0.0
    loans_ac: float = 0.0
    loans_gross: float = 0.0
    fvoci_assets: float = 0.0
    cash: float = 0.0
    total_liabilities: float = 0.0
    deposits_and_debt: float = 0.0
    equity: float = 0.0
    # Assets detail (EUR mn)
    bonds_gross: float = 0.0
    trading_assets: float = 0.0
    # Capital — EUR mn
    cet1_capital: float = 0.0
    own_funds: float = 0.0
    at1_capital: float = 0.0
    tier2_capital: float = 0.0
    intangibles: float = 0.0
    dta: float = 0.0
    dta_temp_diff: float = 0.0  # DTA from temp diffs (DTC proxy for Greek banks)
    rwa_credit: float = 0.0
    rwa_market: float = 0.0
    rwa_operational: float = 0.0
    rwa_total: float = 0.0
    # Credit quality
    npe_gross: float = 0.0
    npl_ratio: float = 0.0
    # Credit quality — granular (EUR mn)
    npe_performing: float = 0.0
    npe_stage2: float = 0.0
    npe_stage3: float = 0.0
    ecl_allow_performing: float = 0.0
    ecl_allow_stage2: float = 0.0
    ecl_allow_npe: float = 0.0
    ecl_allowance_total: float = 0.0
    # Ratios
    cet1_ratio: float = 0.0
    total_capital_ratio: float = 0.0
    nim: float = 0.0
    roe: float = 0.0
    cir: float = 0.0
    leverage_ratio: float = 0.0


@dataclass
class RateEnvironment:
    """Current and projected policy / market rates (decimal, e.g. 0.035 = 3.5%)."""
    policy_rate: float = 0.035          # ECB deposit facility rate
    euribor_3m: float = 0.030
    euribor_6m: float = 0.032
    swap_2y: float = 0.028
    swap_5y: float = 0.025
    swap_10y: float = 0.027
    # Per-quarter rate path (list of 20 values for 5-year plan)
    # If empty, policy_rate is held constant.
    rate_path: list[float] = field(default_factory=list)


@dataclass
class BalanceSheetState:
    """Balance sheet at one quarter-end (EUR mn)."""
    period: date = field(default_factory=date.today)
    total_assets: float = 0.0
    loans_net: float = 0.0          # Net loans (after ECL allowance)
    loans_gross: float = 0.0
    ecl_allowance: float = 0.0
    fvoci_assets: float = 0.0
    trading_assets: float = 0.0
    cash: float = 0.0
    other_assets: float = 0.0
    # Liabilities
    deposits: float = 0.0
    wholesale_funding: float = 0.0
    other_liabilities: float = 0.0
    total_liabilities: float = 0.0
    # Funding gap: assets growing faster than deposits/wholesale → filled with interbank
    funding_gap: float = 0.0
    # Equity
    equity: float = 0.0


@dataclass
class PnLState:
    """P&L for one quarter (EUR mn, quarterly figures)."""
    period: date = field(default_factory=date.today)
    interest_income: float = 0.0
    interest_expense: float = 0.0
    nii: float = 0.0
    fee_income_net: float = 0.0
    trading_gains: float = 0.0
    trading_income: float = 0.0     # net trading income (separate from NII)
    other_income: float = 0.0
    total_operating_income: float = 0.0
    admin_expenses: float = 0.0
    depreciation: float = 0.0
    total_opex: float = 0.0
    pre_provision_profit: float = 0.0
    ecl_charge: float = 0.0
    provisions: float = 0.0
    profit_before_tax: float = 0.0
    tax_charge: float = 0.0
    net_profit: float = 0.0
    # Derived
    nim: float = 0.0    # annualised NII / avg assets
    roe: float = 0.0    # annualised net profit / avg equity
    cir: float = 0.0    # (opex) / total_operating_income
    # Sub-detail objects (populated by calculate_pnl; None until enriched)
    opex_detail: "OpexDetail | None" = field(default=None, repr=False)
    fee_detail: "FeeDetail | None" = field(default=None, repr=False)
    nii_detail: "NIIDetail | None" = field(default=None, repr=False)
    tax_detail: "TaxDetail | None" = field(default=None, repr=False)
    nii_sensitivity: "NIISensitivity | None" = field(default=None, repr=False)


@dataclass
class CapitalState:
    """Capital position at one quarter-end (EUR mn and ratios)."""
    period: date = field(default_factory=date.today)
    cet1_capital: float = 0.0
    at1_capital: float = 0.0
    tier2_capital: float = 0.0
    own_funds: float = 0.0
    rwa_credit: float = 0.0
    rwa_market: float = 0.0
    rwa_operational: float = 0.0
    rwa_total: float = 0.0
    cet1_ratio: float = 0.0
    t1_ratio: float = 0.0
    total_capital_ratio: float = 0.0
    leverage_ratio: float = 0.0
    # Surplus / headroom vs MDA trigger
    cet1_surplus: float = 0.0
    # Retained earnings added this quarter
    retained_earnings_delta: float = 0.0
    # Dividends paid this quarter
    dividends_paid: float = 0.0
    # Waterfall components (EUR mn) — for capital waterfall bridge
    opening_cet1_eur: float = 0.0
    closing_cet1_eur: float = 0.0
    at1_coupons_q: float = 0.0
    buybacks_q: float = 0.0
    extraordinary_payout_q: float = 0.0
    capital_actions_q: float = 0.0
    rwa_growth_drag: float = 0.0
    dtc_cet1_addon: float = 0.0
    cet1_other: float = 0.0
    # RoTE / tangible equity
    goodwill: float = 0.0
    other_intangibles: float = 0.0
    tangible_equity: float = 0.0
    rote: float = 0.0
    tangible_bvps: float = 0.0
    # CRR3 / output floor
    sa_rwa_estimate: float = 0.0
    output_floor_rwa: float = 0.0
    output_floor_binding: bool = False
    output_floor_cet1_ratio: float = 0.0


@dataclass
class AssetQualityState:
    """Credit quality at one quarter-end."""
    period: date = field(default_factory=date.today)
    loans_gross: float = 0.0
    npl_gross: float = 0.0      # Non-performing (stage 3)
    stage1_gross: float = 0.0
    stage2_gross: float = 0.0
    stage3_gross: float = 0.0
    npl_ratio: float = 0.0
    stage2_ratio: float = 0.0
    # Migration flows this quarter
    new_npls: float = 0.0
    cured_npls: float = 0.0
    written_off: float = 0.0
    disposed_npls: float = 0.0
    # Coverage
    coverage_ratio: float = 0.0   # ECL allowance / NPL gross


@dataclass
class EclState:
    """IFRS 9 ECL detail at one quarter-end (EUR mn)."""
    period: date = field(default_factory=date.today)
    # Allowances by stage
    ecl_stage1: float = 0.0
    ecl_stage2: float = 0.0
    ecl_stage3: float = 0.0
    ecl_total: float = 0.0
    # P&L charge for the quarter
    ecl_charge: float = 0.0
    # Scenario weights applied (base/adverse/severe)
    weight_base: float = 1.0
    weight_adverse: float = 0.0
    weight_severe: float = 0.0
    # Off-balance-sheet provisions
    obs_commitments_gross: float = 0.0
    obs_ecl_provision: float = 0.0
    obs_ecl_charge_q: float = 0.0
    # Total ECL (on-BS + OBS)
    total_ecl_charge_q: float = 0.0


@dataclass
class FundingState:
    """Funding structure at one quarter-end (EUR mn and rates)."""
    period: date = field(default_factory=date.today)
    # Volume
    retail_deposits: float = 0.0
    corporate_deposits: float = 0.0
    interbank_funding: float = 0.0
    covered_bonds: float = 0.0
    senior_unsecured: float = 0.0
    central_bank_funding: float = 0.0
    subordinated_debt: float = 0.0
    total_funding: float = 0.0
    # Blended rates (decimal)
    avg_deposit_rate: float = 0.0
    avg_wholesale_rate: float = 0.0
    blended_cost_of_funds: float = 0.0
    # Deposit beta (pass-through of policy rate changes)
    deposit_beta: float = 0.40
    # Interbank gap funding: short-term borrowing to fill balance sheet gap
    interbank_gap_funding: float = 0.0
    interbank_gap_rate: float = 0.0


@dataclass
class LiquidityState:
    """Liquidity metrics at one quarter-end."""
    period: date = field(default_factory=date.today)
    # LCR components (EUR mn)
    hqla: float = 0.0               # High-quality liquid assets
    net_cash_outflows_30d: float = 0.0
    lcr: float = 0.0                # HQLA / net outflows
    # NSFR components (EUR mn)
    available_stable_funding: float = 0.0
    required_stable_funding: float = 0.0
    nsfr: float = 0.0
    # Survival horizon (days) — stressed scenario
    survival_horizon_days: float = 0.0


@dataclass
class FTPState:
    """Funds Transfer Pricing rates at one quarter-end (decimal)."""
    period: date = field(default_factory=date.today)
    # Blended FTP rates by business
    retail_loans_ftp: float = 0.0
    corporate_loans_ftp: float = 0.0
    mortgage_ftp: float = 0.0
    retail_deposits_ftp: float = 0.0
    wholesale_ftp: float = 0.0


# ---------------------------------------------------------------------------
# Enriched P&L sub-dataclasses
# ---------------------------------------------------------------------------

@dataclass
class OpexDetail:
    """Opex breakdown (quarterly EUR mn)."""
    personnel_costs: float = 0.0
    ga_expenses: float = 0.0
    depreciation: float = 0.0
    total_opex: float = 0.0


@dataclass
class FeeDetail:
    """Fee income by business segment (quarterly EUR mn)."""
    retail: float = 0.0
    corporate: float = 0.0
    asset_mgmt: float = 0.0
    treasury: float = 0.0
    total: float = 0.0


@dataclass
class NIIDetail:
    """Banking/trading NII split (quarterly EUR mn)."""
    banking_book_interest_income: float = 0.0
    loan_interest_income: float = 0.0
    bond_interest_income: float = 0.0
    cash_interest_income: float = 0.0
    banking_book_interest_expense: float = 0.0
    banking_book_nii: float = 0.0
    trading_book_nii: float = 0.0
    total_nii: float = 0.0


@dataclass
class TaxDetail:
    """Tax breakdown (quarterly EUR mn)."""
    current_tax: float = 0.0
    deferred_tax: float = 0.0
    total_tax: float = 0.0
    effective_tax_rate: float = 0.0


@dataclass
class NIISensitivity:
    """NII repricing gap sensitivity (EUR mn, annualised)."""
    repricing_assets_eur: float = 0.0
    repricing_liabilities_eur: float = 0.0
    blended_deposit_beta: float = 0.0
    delta_nii_up100bps_eur_ann: float = 0.0
    delta_nii_dn100bps_eur_ann: float = 0.0
    nii_at_risk_pct: float = 0.0


@dataclass
class DepositMixAssumptions:
    """4-bucket deposit mix with user-configurable betas."""
    retail_current_pct: float = 0.30
    retail_savings_pct: float = 0.40
    retail_time_pct: float = 0.30
    beta_retail_current: float = 0.10
    beta_retail_savings: float = 0.30
    beta_retail_time: float = 0.70
    beta_corporate: float = 0.55
    rate_retail_current: float = 0.001
    rate_retail_savings: float = 0.010
    rate_retail_time: float = 0.025
    rate_corporate: float = 0.020


# ---------------------------------------------------------------------------
# DTA / DTC state
# ---------------------------------------------------------------------------

@dataclass
class DTAState:
    """DTA/DTC position at one quarter-end (EUR mn)."""
    period: date = field(default_factory=date.today)
    # Regular DTA
    dta_regular: float = 0.0
    dta_threshold_10pct_cet1: float = 0.0
    dta_deducted_from_cet1: float = 0.0
    dta_rw_250pct: float = 0.0
    # DTC — Greek Law 4172/2013 (zero for all non-Greek banks)
    dtc_stock_opening: float = 0.0
    dtc_statutory_amortization_q: float = 0.0
    dtc_distribution_linked_q: float = 0.0
    dtc_total_amortization_q: float = 0.0
    dtc_stock_closing: float = 0.0
    dtc_cet1_addon: float = 0.0
    dtc_distribution_factor: float = 0.29
    # Totals
    dta_dtc_total_bs: float = 0.0
    dta_rwa_contribution: float = 0.0


# ---------------------------------------------------------------------------
# OCI and Equity Bridge states
# ---------------------------------------------------------------------------

@dataclass
class OCIState:
    """Other Comprehensive Income components (quarterly, EUR mn)."""
    period: date = field(default_factory=date.today)
    bond_revaluation: float = 0.0
    hedge_reserve_change: float = 0.0
    pension_actuarial: float = 0.0
    fx_translation: float = 0.0
    total_oci: float = 0.0
    total_comprehensive_income: float = 0.0


@dataclass
class EquityBridgeState:
    """Full equity reconciliation bridge (quarterly, EUR mn). Must close."""
    period: date = field(default_factory=date.today)
    opening_equity: float = 0.0
    tci: float = 0.0
    at1_coupons: float = 0.0
    cash_dividends: float = 0.0
    buybacks: float = 0.0
    extraordinary_payout: float = 0.0
    capital_actions: float = 0.0
    dtc_cet1_addon: float = 0.0
    other: float = 0.0
    closing_equity: float = 0.0
    check: float = 0.0


# ---------------------------------------------------------------------------
# Capital buffers and MREL views (output-only, produced by capital.py)
# ---------------------------------------------------------------------------

@dataclass
class CapitalBuffers:
    """CET1 buffer stack and MDA distributable (ratios as decimals)."""
    p1_minimum: float = 0.045
    ccb: float = 0.025
    p2r: float = 0.015
    ccyb: float = 0.0
    osii: float = 0.0
    mda_trigger: float = 0.0
    current_cet1: float = 0.0
    headroom_pct: float = 0.0
    headroom_eur: float = 0.0
    max_distributable: float = 0.0


@dataclass
class MrelView:
    """Basic MREL stack and headroom (EUR mn and ratios)."""
    requirement_pct_trea: float = 0.0
    own_funds: float = 0.0
    at1: float = 0.0
    tier2: float = 0.0
    snp_eligible: float = 0.0
    total_mrel_stack_eur: float = 0.0
    total_mrel_stack_pct: float = 0.0
    mrel_headroom_eur: float = 0.0
    mrel_headroom_pct: float = 0.0
    mda_distributable_eur: float = 0.0
    mrel_mda_eur: float = 0.0


# ---------------------------------------------------------------------------
# Payout
# ---------------------------------------------------------------------------

@dataclass
class PayoutAssumptions:
    cet1_target: float = 0.15
    regular_cash_dividend_pct: float = 0.40
    buyback_pct: float = 0.20
    extraordinary_payout_eur: float = 0.0
    extraordinary_quarter: int = 0


@dataclass
class PayoutState:
    period: date = field(default_factory=date.today)
    pat_quarterly: float = 0.0
    max_distributable_eur: float = 0.0
    regular_cash_dividend: float = 0.0
    buyback: float = 0.0
    extraordinary_payout: float = 0.0
    total_payout: float = 0.0
    payout_ratio: float = 0.0
    eps_annual: float = 0.0
    dps_annual: float = 0.0
    shares_outstanding: float = 0.0
    shares_remaining: float = 0.0
