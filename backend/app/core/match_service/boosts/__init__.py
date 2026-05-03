# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Boost registry — the ranker iterates ``BOOSTS`` in order.

Each boost is a sync function ``(envelope, candidate, settings) ->
dict[str, float]``. The ranker sums every reported delta into the
candidate's ``boosts_applied`` dict and adjusts the final score by the
sum (clamped to [0, 1]).

Adding a new boost:
    1. Drop a module under ``boosts/`` exposing ``def boost(env, cand, settings)``.
    2. Append it to ``BOOSTS`` below.
    3. Add the new weight to ``BoostWeights`` in ``config.py``.
    4. Add a unit test verifying the delta and (if relevant) a no-op path.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.core.match_service.boosts import classifier, lex, region, unit
from app.core.match_service.envelope import ElementEnvelope, MatchCandidate

# Boost callable signature.
BoostFn = Callable[[ElementEnvelope, MatchCandidate, Any], dict[str, float]]

# Order doesn't affect math (sum is commutative) but it does affect the
# ``boosts_applied`` insertion order shown in the API response — so we
# keep them in "most explainable first" order: classifier → unit →
# region → lex.
BOOSTS: list[BoostFn] = [
    classifier.boost,
    unit.boost,
    region.boost,
    lex.boost,
]


def apply_boosts(
    envelope: ElementEnvelope,
    candidate: MatchCandidate,
    settings: Any,
) -> dict[str, float]:
    """Run every registered boost and merge their reported deltas.

    Returns a flat dict ``{boost_name: delta}`` covering all non-zero
    contributions. Empty dict means no boost fired.
    """
    out: dict[str, float] = {}
    for fn in BOOSTS:
        try:
            delta = fn(envelope, candidate, settings)
        except Exception:  # pragma: no cover — boosts must never crash ranking
            continue
        if delta:
            out.update(delta)
    return out


__all__ = ["BOOSTS", "BoostFn", "apply_boosts"]
