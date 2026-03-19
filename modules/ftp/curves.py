"""
modules/ftp/curves.py — Funds Transfer Pricing curve construction.

Builds FTP rates for each business segment from the funding cost stack.
FTP rate = risk-free rate (matched tenor) + liquidity premium + credit spread.

The FTP curve is used to:
- Price internal funding costs to originating business lines
- Attribute NII between asset-generating and liability-gathering units
- Compute segment RAROC (see modules/calculation/raroc.py)

All rates are annualised decimals.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from modules.calculation.state import FundingState, FTPState, RateEnvironment


# ---------------------------------------------------------------------------
# FTP tenor bucket definitions (years)
# ---------------------------------------------------------------------------
TENOR_BUCKETS = {
    "overnight":    0.003,   # O/N: matches ON rate
    "short_term":   0.25,    # <3M: EURIBOR 3M
    "medium_term":  1.0,     # 1Y: 1Y swap
    "long_term":    5.0,     # 5Y: 5Y swap
    "very_long":   10.0,     # 10Y: 10Y swap
}

# Liquidity premium by tenor (basis points → decimal)
LIQUIDITY_PREMIUM = {
    "overnight":   0.0010,
    "short_term":  0.0025,
    "medium_term": 0.0050,
    "long_term":   0.0080,
    "very_long":   0.0120,
}


@dataclass
class FtpCurveSet:
    """Computed FTP rates for each standard tenor bucket (decimal, annualised)."""
    period: date = field(default_factory=date.today)
    overnight: float = 0.0
    short_term: float = 0.0
    medium_term: float = 0.0
    long_term: float = 0.0
    very_long: float = 0.0


def build_ftp_curves(
    rate_env: RateEnvironment,
    funding: FundingState,
    period: date,
    *,
    # Additional credit spread on top of risk-free (bank-specific funding cost)
    credit_spread: float = 0.0050,   # 50bps default
) -> FtpCurveSet:
    """
    Build FTP rates for each tenor bucket.

    FTP(tenor) = risk_free_rate(tenor) + liquidity_premium(tenor) + credit_spread

    The risk-free rate is interpolated from the RateEnvironment curve:
    - overnight / short: policy_rate / euribor_3m
    - medium: (euribor_3m + swap_2y) / 2
    - long: swap_5y
    - very_long: swap_10y
    """
    # Risk-free anchor rates by tenor
    rf = {
        "overnight":   rate_env.policy_rate,
        "short_term":  rate_env.euribor_3m,
        "medium_term": (rate_env.euribor_3m + rate_env.swap_2y) / 2 if rate_env.swap_2y else rate_env.euribor_6m,
        "long_term":   rate_env.swap_5y  if rate_env.swap_5y  else rate_env.euribor_6m,
        "very_long":   rate_env.swap_10y if rate_env.swap_10y else rate_env.swap_5y,
    }

    # Blended funding spread (excess of blended cost over risk-free)
    rf_blended = (rf["short_term"] + rf["medium_term"]) / 2
    funding_spread = max(0.0, funding.blended_cost_of_funds - rf_blended)

    def ftp(bucket: str) -> float:
        return rf[bucket] + LIQUIDITY_PREMIUM[bucket] + credit_spread + funding_spread * 0.50

    return FtpCurveSet(
        period=period,
        overnight=ftp("overnight"),
        short_term=ftp("short_term"),
        medium_term=ftp("medium_term"),
        long_term=ftp("long_term"),
        very_long=ftp("very_long"),
    )


def build_segment_ftp(
    curve: FtpCurveSet,
    *,
    # Product average duration assumptions (years)
    retail_loan_duration: float = 4.0,
    corporate_loan_duration: float = 2.0,
    mortgage_duration: float = 8.0,
    retail_deposit_duration: float = 0.5,
    wholesale_duration: float = 3.0,
) -> FTPState:
    """
    Map product durations onto the FTP curve to produce segment FTP rates.
    Uses linear interpolation between the tenor buckets.
    """
    def interpolate(duration_y: float) -> float:
        """Linearly interpolate FTP rate from tenor buckets."""
        points = [
            (0.003,   curve.overnight),
            (0.25,    curve.short_term),
            (1.0,     curve.medium_term),
            (5.0,     curve.long_term),
            (10.0,    curve.very_long),
        ]
        if duration_y <= points[0][0]:
            return points[0][1]
        if duration_y >= points[-1][0]:
            return points[-1][1]
        for i in range(len(points) - 1):
            t0, r0 = points[i]
            t1, r1 = points[i + 1]
            if t0 <= duration_y <= t1:
                w = (duration_y - t0) / (t1 - t0)
                return r0 + w * (r1 - r0)
        return curve.medium_term

    return FTPState(
        period=curve.period,
        retail_loans_ftp=interpolate(retail_loan_duration),
        corporate_loans_ftp=interpolate(corporate_loan_duration),
        mortgage_ftp=interpolate(mortgage_duration),
        retail_deposits_ftp=interpolate(retail_deposit_duration),
        wholesale_ftp=interpolate(wholesale_duration),
    )
