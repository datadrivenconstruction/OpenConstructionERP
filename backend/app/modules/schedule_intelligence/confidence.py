# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""E5.3 — Confidence framework (uniform schema + config-as-data gating).

Every insight this module emits — a readiness classification, a forward-risk
score, a priced decision — carries the *same* confidence shape: a 0..1
``score``, a ``band`` (high/medium/low), and a ``rationale`` that lists, in
order, every adjustment that produced the score. There is one place that
computes it (:func:`compute_confidence`) so the semantics can never drift
between engines.

The gating policy is **config-as-data**, not code: caps and bonuses live in a
``confidence_config`` row (versioned + audit-logged, E2.1-AC7) and are loaded
into a :class:`ConfidencePolicy`. This is what lets a degraded feed surface a
*reduced, explained* confidence rather than a silently optimistic one
(spec P5 — "degraded feeds show reduced confidence with stated reason, never
silent"): a schedule-quality or feed-coverage tier imposes a hard ceiling the
base score cannot exceed, and the reason is always recorded in the rationale.

Ordering guarantee: corroboration **bonuses** are applied first, then **caps**
last, so a cap is a true ceiling that corroboration can never lift past. The
whole computation is pure and deterministic — identical inputs always yield an
identical result (mirrors the determinism the classifier promises, E1.1-AC6).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from app.modules.schedule_intelligence.enums import ConfidenceBand

# Deployment-wide fallback used when no ``confidence_config`` row exists yet.
# Deliberately conservative: unknown-quality inputs are not assumed pristine.
_DEFAULT_BAND_THRESHOLDS: dict[str, float] = {"high": 0.75, "medium": 0.5}
_DEFAULT_SCHEDULE_QUALITY_CAPS: dict[str, float] = {
    "poor": 0.4,
    "fair": 0.7,
    "good": 1.0,
}
_DEFAULT_FEED_COVERAGE_CAPS: dict[str, float] = {
    "sparse": 0.5,
    "partial": 0.8,
    "full": 1.0,
}
_DEFAULT_CORROBORATION_BONUSES: dict[str, float] = {
    "document_backed": 0.1,
    "cross_feed_agreement": 0.1,
    "human_confirmed": 0.15,
}


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


@dataclass(frozen=True)
class ConfidencePolicy:
    """Immutable, resolved confidence gating policy (the data behind E5.3)."""

    band_thresholds: Mapping[str, float]
    schedule_quality_caps: Mapping[str, float]
    feed_coverage_caps: Mapping[str, float]
    corroboration_bonuses: Mapping[str, float]
    version: int | None = None

    @classmethod
    def default(cls) -> ConfidencePolicy:
        """The built-in fallback policy (no DB row required)."""
        return cls(
            band_thresholds=dict(_DEFAULT_BAND_THRESHOLDS),
            schedule_quality_caps=dict(_DEFAULT_SCHEDULE_QUALITY_CAPS),
            feed_coverage_caps=dict(_DEFAULT_FEED_COVERAGE_CAPS),
            corroboration_bonuses=dict(_DEFAULT_CORROBORATION_BONUSES),
            version=None,
        )

    @classmethod
    def from_config(cls, row: Any) -> ConfidencePolicy:
        """Build a policy from a ``ConfidenceConfig`` ORM row (duck-typed).

        Missing / empty maps fall back to the corresponding default so a
        partially-configured row still behaves sensibly (an operator can set
        only the caps they care about). Keeps this module import-free of the
        models layer.
        """
        default = cls.default()
        return cls(
            band_thresholds=dict(getattr(row, "band_thresholds", None) or default.band_thresholds),
            schedule_quality_caps=dict(getattr(row, "schedule_quality_caps", None) or default.schedule_quality_caps),
            feed_coverage_caps=dict(getattr(row, "feed_coverage_caps", None) or default.feed_coverage_caps),
            corroboration_bonuses=dict(getattr(row, "corroboration_bonuses", None) or default.corroboration_bonuses),
            version=getattr(row, "version", None),
        )


@dataclass(frozen=True)
class ConfidenceResult:
    """Uniform confidence attached to every insight.

    ``rationale`` is an ordered list of ``{"step", "effect", "detail"}`` dicts —
    the audit-and-UI record of *why* the score is what it is. It is never
    empty: the base contribution is always the first entry.
    """

    score: float
    band: ConfidenceBand
    rationale: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "band": self.band.value,
            "rationale": self.rationale,
        }


def band_for(score: float, thresholds: Mapping[str, float]) -> ConfidenceBand:
    """Map a 0..1 score to a band using the policy thresholds."""
    high = float(thresholds.get("high", _DEFAULT_BAND_THRESHOLDS["high"]))
    medium = float(thresholds.get("medium", _DEFAULT_BAND_THRESHOLDS["medium"]))
    if score >= high:
        return ConfidenceBand.HIGH
    if score >= medium:
        return ConfidenceBand.MEDIUM
    return ConfidenceBand.LOW


def compute_confidence(
    base_score: float,
    *,
    schedule_quality: str | None = None,
    feed_coverage: str | None = None,
    corroboration: Iterable[str] = (),
    policy: ConfidencePolicy | None = None,
) -> ConfidenceResult:
    """Compute a uniform :class:`ConfidenceResult` from a base score + signals.

    Args:
        base_score: The engine's raw 0..1 confidence before gating.
        schedule_quality: Schedule-quality tier of the underlying data (keys of
            ``policy.schedule_quality_caps``, e.g. ``"poor"``). Caps the score.
        feed_coverage: Feed-coverage tier (keys of
            ``policy.feed_coverage_caps``, e.g. ``"sparse"``). Caps the score.
        corroboration: Corroboration signals present for this insight (keys of
            ``policy.corroboration_bonuses``, e.g. ``"document_backed"``). Each
            adds its bonus before caps apply.
        policy: The gating policy; defaults to :meth:`ConfidencePolicy.default`.

    Returns:
        A deterministic result whose ``rationale`` records the base score, each
        corroboration bonus applied, and each cap in effect (whether or not it
        bound), so nothing about the number is silent.
    """
    policy = policy or ConfidencePolicy.default()
    rationale: list[dict[str, Any]] = []

    score = _clamp01(float(base_score))
    rationale.append({"step": "base", "effect": round(score, 4), "detail": "engine base score"})

    # 1) Corroboration bonuses (applied first, additive, clamped to 1.0).
    for signal in corroboration:
        bonus = policy.corroboration_bonuses.get(signal)
        if not bonus:
            continue
        before = score
        score = _clamp01(score + float(bonus))
        rationale.append(
            {
                "step": f"corroboration:{signal}",
                "effect": round(score - before, 4),
                "detail": f"+{float(bonus):g} for {signal}",
            }
        )

    # 2) Caps (applied last — a hard ceiling corroboration cannot lift past).
    score = _apply_cap(
        score,
        tier=schedule_quality,
        caps=policy.schedule_quality_caps,
        kind="schedule_quality",
        rationale=rationale,
    )
    score = _apply_cap(
        score,
        tier=feed_coverage,
        caps=policy.feed_coverage_caps,
        kind="feed_coverage",
        rationale=rationale,
    )

    score = round(_clamp01(score), 4)
    return ConfidenceResult(
        score=score,
        band=band_for(score, policy.band_thresholds),
        rationale=rationale,
    )


def _apply_cap(
    score: float,
    *,
    tier: str | None,
    caps: Mapping[str, float],
    kind: str,
    rationale: list[dict[str, Any]],
) -> float:
    """Apply a tier cap, always recording it when the tier is known.

    Recording the cap even when it does not bind is intentional (P5): the UI
    can state "capped at 0.7 by fair schedule quality" so a degraded feed's
    reduced ceiling is never invisible.
    """
    if tier is None:
        return score
    if tier not in caps:
        # Unknown tier is itself a degraded-input signal — surface it.
        rationale.append(
            {
                "step": f"cap:{kind}",
                "effect": 0.0,
                "detail": f"unknown {kind} tier {tier!r}; no cap applied",
            }
        )
        return score
    cap = float(caps[tier])
    before = score
    score = min(score, cap)
    rationale.append(
        {
            "step": f"cap:{kind}",
            "effect": round(score - before, 4),
            "detail": f"{kind}={tier!r} caps confidence at {cap:g}",
        }
    )
    return score
