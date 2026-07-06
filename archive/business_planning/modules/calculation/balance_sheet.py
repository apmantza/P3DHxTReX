"""
modules/calculation/balance_sheet.py — Balance sheet projection.

Projects the balance sheet one quarter forward given:
- Prior quarter BalanceSheetState
- Management assumptions (growth rates)
- Funding state (to reconcile liability side)

All amounts in EUR mn.
"""
from __future__ import annotations

from dataclasses import asdict, replace
from datetime import date

from modules.calculation.state import BalanceSheetState, FundingState


def project_balance_sheet(
    prior: BalanceSheetState,
    period: date,
    *,
    # Asset-side growth rates (quarterly, decimal)
    loan_growth_q: float = 0.01,          # 1% quarterly = ~4% annual
    fvoci_growth_q: float = 0.005,
    cash_growth_q: float = 0.0,
    other_assets_growth_q: float = 0.005,
    # ECL allowance delta (supplied by ECL module)
    ecl_delta: float = 0.0,
    # Funding state for liability side reconciliation
    funding: FundingState | None = None,
    # Equity constraint from capital module (own_funds, one-period lag).
    # When provided, equity is pinned and the funding gap is computed.
    equity_constraint: float | None = None,
) -> BalanceSheetState:
    """
    Project balance sheet one quarter forward.

    The asset side grows by the provided growth rates.
    The liability / equity side is reconciled from funding state + equity.

    Returns a new BalanceSheetState; prior is unchanged.
    """
    loans_gross = prior.loans_gross * (1 + loan_growth_q)
    ecl_allowance = max(0.0, prior.ecl_allowance + ecl_delta)
    loans_net = max(0.0, loans_gross - ecl_allowance)

    fvoci = prior.fvoci_assets * (1 + fvoci_growth_q)
    trading = prior.trading_assets   # held flat for PoC
    cash = prior.cash * (1 + cash_growth_q)
    other = prior.other_assets * (1 + other_assets_growth_q)

    total_assets = loans_net + fvoci + trading + cash + other

    # Liability side: build from funding state if available, else grow proportionally
    funding_gap = 0.0
    if funding is not None:
        deposits = funding.retail_deposits + funding.corporate_deposits
        # Structural wholesale (excludes any prior gap fill — gap is re-solved each quarter)
        wholesale = (
            funding.interbank_funding
            + funding.covered_bonds
            + funding.senior_unsecured
            + funding.central_bank_funding
            + funding.subordinated_debt
        )
        other_liab = prior.other_liabilities * (1 + loan_growth_q / 2)

        if equity_constraint is not None:
            # Pin equity to capital module's own_funds (one-period lag).
            # Residual = funding gap, filled with short-term interbank in apply_funding_gap().
            equity = max(0.0, equity_constraint)
            total_liabilities = total_assets - equity
            base_liabilities = deposits + wholesale + other_liab
            funding_gap = max(0.0, total_liabilities - base_liabilities)
        else:
            total_liabilities = deposits + wholesale + other_liab
            equity = total_assets - total_liabilities
    else:
        # Grow liabilities proportionally to assets
        growth = total_assets / prior.total_assets if prior.total_assets > 0 else 1.0
        deposits = prior.deposits * growth
        wholesale = prior.wholesale_funding * growth
        other_liab = prior.other_liabilities * growth
        total_liabilities = deposits + wholesale + other_liab
        equity = total_assets - total_liabilities

    return BalanceSheetState(
        period=period,
        total_assets=total_assets,
        loans_gross=loans_gross,
        ecl_allowance=ecl_allowance,
        loans_net=loans_net,
        fvoci_assets=fvoci,
        trading_assets=trading,
        cash=cash,
        other_assets=other,
        deposits=deposits,
        wholesale_funding=wholesale,
        other_liabilities=other_liab,
        total_liabilities=total_liabilities,
        funding_gap=funding_gap,
        equity=equity,
    )


def balance_sheet_from_base(base_year, period: date) -> BalanceSheetState:
    """Initialise BalanceSheetState from a BaseYear snapshot.

    Note: loans_gross (EBA item 2521019) = gross carrying amount of AC loans only.
          loans_ac  (EBA item 2521006) = total financial assets at amortised cost
                                          (includes loans + AC bonds + other).
    We use loans_gross as the loan book base; remaining AC assets go into other_assets.
    """
    # Use loans_gross as the loan book base (net carrying value for PoC)
    loan_book = base_year.loans_gross if base_year.loans_gross > 0 else base_year.loans_ac
    # ECL allowance starts at 0 here — ECL module sets the stock going forward
    ecl_allowance = 0.0
    loans_net = loan_book
    # Use actual trading_assets if available
    trading = base_year.trading_assets if base_year.trading_assets > 0 else 0.0
    # Other assets absorbs non-loan AC assets, derivatives, etc.
    other = max(0.0,
        base_year.total_assets
        - loans_net
        - base_year.fvoci_assets
        - trading
        - base_year.cash
    )
    # Liability split: deposits + wholesale + other
    deposits = base_year.deposits_and_debt * 0.70
    wholesale = base_year.deposits_and_debt * 0.30
    other_liab = max(0.0, base_year.total_liabilities - base_year.deposits_and_debt)

    return BalanceSheetState(
        period=period,
        total_assets=base_year.total_assets,
        loans_gross=loan_book,
        ecl_allowance=ecl_allowance,
        loans_net=loans_net,
        fvoci_assets=base_year.fvoci_assets,
        trading_assets=trading,
        cash=base_year.cash,
        other_assets=other,
        deposits=deposits,
        wholesale_funding=wholesale,
        other_liabilities=other_liab,
        total_liabilities=base_year.total_liabilities,
        equity=base_year.equity,
    )
