"""
services/cache.py — Assumptions hash + projection cache.

Caches run_projection() results keyed by (plan_id, scenario_id, assumptions_hash).
Cache entries are invalidated when assumptions change (hash mismatch).
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from typing import Any

log = logging.getLogger(__name__)


def _stable_hash(obj: Any) -> str:
    """Deterministic SHA-256 of any JSON-serialisable object."""
    raw = json.dumps(obj, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def plan_assumptions_hash(plan_dict: dict) -> str:
    """
    Hash the assumption fields of a Plan dict.
    Only the fields that affect projection output are included.
    """
    relevant = {
        k: plan_dict.get(k)
        for k in (
            "portfolio_allocations",
            "funding_strategy",
            "ftp_assumptions",
            "capital_actions",
            "dividend_policy",
            "rate_environment",
            "repricing_gap",
            "nmd_profiles",
            "hedging_instruments",
            "cet1_deductions",
            "ifrs9_transitional",
            "recovery_options",
            "horizon_years",
        )
    }
    return _stable_hash(relevant)


class ProjectionCache:
    """
    In-process LRU-style cache for projection results.

    Key: (plan_id, scenario_id, assumptions_hash)
    Value: list[dict] — serialised ProjectedFinancials

    For the PoC this is an in-memory dict. In Phase 2 this can be replaced
    with a Redis or file-backed store without changing the interface.
    """

    def __init__(self, max_entries: int = 64) -> None:
        self._store: dict[tuple, tuple[datetime, list[dict]]] = {}
        self._max = max_entries

    def _evict_oldest(self) -> None:
        if len(self._store) >= self._max:
            oldest_key = min(self._store, key=lambda k: self._store[k][0])
            del self._store[oldest_key]

    def get(
        self,
        plan_id: int,
        scenario_id: int | None,
        assumptions_hash: str,
    ) -> list[dict] | None:
        key = (plan_id, scenario_id, assumptions_hash)
        entry = self._store.get(key)
        if entry is None:
            return None
        log.debug("Cache hit for plan_id=%s scenario_id=%s", plan_id, scenario_id)
        return entry[1]

    def put(
        self,
        plan_id: int,
        scenario_id: int | None,
        assumptions_hash: str,
        result: list[dict],
    ) -> None:
        key = (plan_id, scenario_id, assumptions_hash)
        self._evict_oldest()
        self._store[key] = (datetime.utcnow(), result)
        log.debug("Cached result for plan_id=%s scenario_id=%s", plan_id, scenario_id)

    def invalidate(self, plan_id: int) -> int:
        """Remove all entries for a given plan. Returns count removed."""
        to_remove = [k for k in self._store if k[0] == plan_id]
        for k in to_remove:
            del self._store[k]
        return len(to_remove)

    def clear(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)


# Module-level singleton — shared across the process lifetime
_cache = ProjectionCache()


def get_cache() -> ProjectionCache:
    return _cache
