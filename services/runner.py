"""
services/runner.py — Sync projection runner (lite mode).

Interface:
    run_projection_job(plan_id, scenario_id, db_session, cache) -> list[ProjectedFinancials]

The runner:
1. Loads Plan + Scenario from DB
2. Checks cache; returns cached result if hash matches
3. Calls engine.run_projection()
4. Persists results to DB
5. Stores result in cache
6. Appends AuditLog entry

Phase 2: replace with async Celery task — same signature, same return type.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

log = logging.getLogger(__name__)


def run_projection_job(
    plan_id: int,
    scenario_id: int | None,
    db: "Session",
    cache=None,
    *,
    force_recompute: bool = False,
) -> list:
    """
    Execute a projection for *plan_id* × *scenario_id*.

    Returns a list of ORM ProjectedFinancials objects (freshly computed or
    retrieved from cache).  The caller is responsible for committing the
    session if new rows were persisted.

    Args:
        plan_id:         DB id of the Plan to project.
        scenario_id:     DB id of the Scenario (None = base/management case).
        db:              SQLAlchemy Session.
        cache:           ProjectionCache instance (optional; pass None to skip cache).
        force_recompute: If True, bypass cache and always recompute.
    """
    from db.models import AuditLog, Plan, ProjectedFinancials, Scenario
    from modules.calculation.engine import run_projection
    from services.cache import plan_assumptions_hash

    # ------------------------------------------------------------------
    # 1. Load Plan
    # ------------------------------------------------------------------
    plan = db.get(Plan, plan_id)
    if plan is None:
        raise ValueError(f"Plan {plan_id} not found")

    scenario = None
    if scenario_id is not None:
        scenario = db.get(Scenario, scenario_id)
        if scenario is None:
            raise ValueError(f"Scenario {scenario_id} not found")

    # ------------------------------------------------------------------
    # 2. Cache lookup
    # ------------------------------------------------------------------
    plan_dict = {
        col.name: getattr(plan, col.name)
        for col in Plan.__table__.columns
    }
    ahash = plan_assumptions_hash(plan_dict)

    if cache is not None and not force_recompute:
        cached = cache.get(plan_id, scenario_id, ahash)
        if cached is not None:
            log.info(
                "Cache hit — plan_id=%s scenario_id=%s hash=%s",
                plan_id, scenario_id, ahash,
            )
            return cached

    # ------------------------------------------------------------------
    # 3. Compute
    # ------------------------------------------------------------------
    log.info(
        "Running projection — plan_id=%s scenario_id=%s hash=%s",
        plan_id, scenario_id, ahash,
    )
    t0 = datetime.utcnow()
    results = run_projection(plan, scenario, db)
    elapsed = (datetime.utcnow() - t0).total_seconds()
    log.info("Projection complete in %.2fs — %d periods", elapsed, len(results))

    # ------------------------------------------------------------------
    # 4. Persist (delete stale rows first, then bulk-insert)
    # ------------------------------------------------------------------
    db.query(ProjectedFinancials).filter(
        ProjectedFinancials.plan_id == plan_id,
        ProjectedFinancials.scenario_id == scenario_id,
    ).delete(synchronize_session=False)

    for pf in results:
        db.add(pf)

    # ------------------------------------------------------------------
    # 5. Audit
    # ------------------------------------------------------------------
    db.add(AuditLog(
        entity_type="Plan",
        entity_id=plan_id,
        action="RUN_PROJECTION",
        field_changed="scenario_id",
        new_value=str(scenario_id),
    ))

    db.flush()

    # ------------------------------------------------------------------
    # 6. Cache store
    # ------------------------------------------------------------------
    if cache is not None:
        cache.put(plan_id, scenario_id, ahash, results)

    return results
