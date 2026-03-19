"""
modules/rating/benchmarking.py — Peer benchmarking module.

Compares subject bank's base year metrics against a user-selectable peer group.
Default peer group: same country as subject bank (from banks table).

Output: BenchmarkReport with per-metric BenchmarkMetric (percentile + distribution).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

log = logging.getLogger(__name__)


@dataclass
class BenchmarkMetric:
    metric_name: str
    subject_value: float
    peer_count: int
    peer_p10: float = 0.0
    peer_p25: float = 0.0
    peer_median: float = 0.0
    peer_p75: float = 0.0
    peer_p90: float = 0.0
    subject_percentile: float = 0.0
    signal: str = "UNKNOWN"   # TOP_QUARTILE|ABOVE_MEDIAN|BELOW_MEDIAN|BOTTOM_QUARTILE|BOTTOM_DECILE


@dataclass
class BenchmarkReport:
    subject_bank_lei: str
    subject_bank_name: str
    peer_group_leis: list
    peer_count: int
    base_year_period: date
    metrics: dict = field(default_factory=dict)
    generated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        d = {
            "subject_bank_lei": self.subject_bank_lei,
            "subject_bank_name": self.subject_bank_name,
            "peer_group_leis": self.peer_group_leis,
            "peer_count": self.peer_count,
            "base_year_period": self.base_year_period.isoformat(),
            "generated_at": self.generated_at.isoformat(),
            "metrics": {k: asdict(v) for k, v in self.metrics.items()},
        }
        return d


def _signal(percentile: float) -> str:
    if percentile >= 75:
        return "TOP_QUARTILE"
    if percentile >= 50:
        return "ABOVE_MEDIAN"
    if percentile >= 25:
        return "BELOW_MEDIAN"
    if percentile >= 10:
        return "BOTTOM_QUARTILE"
    return "BOTTOM_DECILE"


def _make_metric(name: str, subject: float, peer_values: list[float]) -> BenchmarkMetric:
    vals = [v for v in peer_values if v is not None and not np.isnan(v) and v > -9999]
    if not vals:
        return BenchmarkMetric(metric_name=name, subject_value=subject, peer_count=0, signal="NO_PEERS")
    arr = np.array(vals, dtype=float)
    pct = float(np.mean(arr <= subject) * 100)
    return BenchmarkMetric(
        metric_name=name,
        subject_value=subject,
        peer_count=len(arr),
        peer_p10=float(np.percentile(arr, 10)),
        peer_p25=float(np.percentile(arr, 25)),
        peer_median=float(np.percentile(arr, 50)),
        peer_p75=float(np.percentile(arr, 75)),
        peer_p90=float(np.percentile(arr, 90)),
        subject_percentile=pct,
        signal=_signal(pct),
    )


def _extract_peer_metrics(db: "Session", bank_lei: str) -> dict[str, float]:
    """Extract key base-year metrics for one bank from DB."""
    from modules.calculation.state import BaseYearExtractor
    try:
        byx = BaseYearExtractor(db, bank_lei=bank_lei)
        base = byx.extract()
        if base.total_assets < 100:
            return {}
        metrics = {
            "cet1_ratio":          base.cet1_ratio,
            "total_capital_ratio": base.total_capital_ratio,
            "leverage_ratio":      base.leverage_ratio,
            "nim":                 base.nim,
            "roe":                 base.roe,
            "cir":                 base.cir,
            "npl_ratio":           base.npl_ratio,
            "ldr":                 base.loans_ac / base.deposits_and_debt if base.deposits_and_debt > 0 else 0.0,
            "fee_ratio":           base.fee_income_net / base.nii if base.nii > 0 else 0.0,
            "ecl_charge_ratio":    base.ecl_charge / base.loans_ac if base.loans_ac > 0 else 0.0,
        }
        return metrics
    except Exception as e:
        log.debug("Failed to extract metrics for %s: %s", bank_lei, e)
        return {}


def run_benchmarking(
    plan,
    db: "Session",
    peer_lei_list: list[str] | None = None,
) -> BenchmarkReport:
    """
    Compute benchmark report for plan's subject bank vs peer group.

    peer_lei_list: if None, uses country-filtered peer group from banks table.
    """
    from db.models import Bank, BaseYearSnapshot

    subject_bank = plan.bank
    subject_lei = subject_bank.lei or ""
    subject_country = subject_bank.country

    # Resolve peer group
    if peer_lei_list is not None:
        peers = peer_lei_list
    else:
        peer_banks = (db.query(Bank)
                      .filter(Bank.country == subject_country,
                              Bank.lei != subject_lei)
                      .all())
        peers = [b.lei for b in peer_banks if b.lei]

    log.info("Benchmarking %s vs %d peers (country=%s)", subject_bank.name, len(peers), subject_country)

    # Extract subject metrics
    subject_metrics = _extract_peer_metrics(db, subject_lei)
    if not subject_metrics:
        log.warning("Could not extract base year metrics for subject bank %s", subject_lei)

    # Extract peer metrics
    peer_data: dict[str, dict] = {}
    for lei in peers:
        m = _extract_peer_metrics(db, lei)
        if m:
            peer_data[lei] = m

    # Build benchmark metrics
    metric_names = [
        "cet1_ratio", "total_capital_ratio", "leverage_ratio",
        "nim", "roe", "cir",
        "npl_ratio", "ldr", "fee_ratio", "ecl_charge_ratio",
    ]
    metrics = {}
    for name in metric_names:
        subject_val = subject_metrics.get(name, 0.0)
        peer_vals = [pd[name] for pd in peer_data.values() if name in pd]
        metrics[name] = _make_metric(name, subject_val, peer_vals)

    # Determine base year period
    latest = (db.query(BaseYearSnapshot.period)
               .filter(BaseYearSnapshot.bank_lei == subject_lei)
               .order_by(BaseYearSnapshot.period.desc())
               .first())
    base_period = latest[0] if latest else date.today()

    return BenchmarkReport(
        subject_bank_lei=subject_lei,
        subject_bank_name=subject_bank.name,
        peer_group_leis=peers,
        peer_count=len(peer_data),
        base_year_period=base_period,
        metrics=metrics,
    )


def save_benchmark_run(plan, report: BenchmarkReport, db: "Session") -> None:
    """Persist BenchmarkReport to benchmark_runs table."""
    from db.models import BenchmarkRun
    run = BenchmarkRun(
        plan_id=plan.id,
        peer_group_leis=report.peer_group_leis,
        peer_count=report.peer_count,
        base_year_period=report.base_year_period,
        results=report.to_dict(),
    )
    db.add(run)
    db.flush()
    log.info("Saved BenchmarkRun id=%s for plan_id=%s", run.id, plan.id)
