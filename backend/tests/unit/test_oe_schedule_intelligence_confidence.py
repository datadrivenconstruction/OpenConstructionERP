# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""E5.3 confidence framework — uniform schema, config-as-data gating.

Pure unit tests for ``confidence.compute_confidence``. Focus areas:
    * caps are a true ceiling (degraded feed / poor schedule → reduced score),
    * the reduction is never silent — the rationale states it (spec P5),
    * corroboration bonuses apply before caps and cannot exceed them,
    * the computation is deterministic (identical inputs → identical output).
"""

from __future__ import annotations

import pytest

from app.modules.schedule_intelligence.confidence import (
    ConfidencePolicy,
    compute_confidence,
)
from app.modules.schedule_intelligence.enums import ConfidenceBand


def test_clean_high_base_is_high_band() -> None:
    result = compute_confidence(0.9)
    assert result.score == 0.9
    assert result.band == ConfidenceBand.HIGH
    # rationale is never empty; the base is always first.
    assert result.rationale[0]["step"] == "base"


def test_poor_schedule_quality_caps_confidence() -> None:
    result = compute_confidence(0.9, schedule_quality="poor")
    assert result.score == 0.4  # default poor cap
    assert result.band == ConfidenceBand.LOW
    cap_steps = [r for r in result.rationale if r["step"] == "cap:schedule_quality"]
    assert cap_steps and cap_steps[0]["effect"] < 0  # reduction recorded, not silent


def test_sparse_feed_coverage_caps_confidence() -> None:
    result = compute_confidence(0.95, feed_coverage="sparse")
    assert result.score == 0.5  # default sparse cap
    assert result.band == ConfidenceBand.MEDIUM
    assert any(r["step"] == "cap:feed_coverage" for r in result.rationale)


def test_corroboration_bonuses_are_additive_and_recorded() -> None:
    result = compute_confidence(0.3, corroboration=["document_backed", "human_confirmed"])
    # 0.3 + 0.10 + 0.15 = 0.55
    assert result.score == 0.55
    assert result.band == ConfidenceBand.MEDIUM
    bonus_steps = [r for r in result.rationale if r["step"].startswith("corroboration:")]
    assert len(bonus_steps) == 2


def test_cap_beats_corroboration_bonus() -> None:
    """A cap is a hard ceiling — corroboration cannot lift the score past it."""
    result = compute_confidence(0.6, schedule_quality="poor", corroboration=["human_confirmed"])
    assert result.score == 0.4  # bonus pushed to 0.75, then poor cap clamps to 0.4
    assert result.band == ConfidenceBand.LOW


def test_unknown_tier_is_surfaced_not_silently_ignored() -> None:
    result = compute_confidence(0.8, schedule_quality="does-not-exist")
    assert result.score == 0.8  # no cap applied
    notes = [r for r in result.rationale if r["step"] == "cap:schedule_quality" and "unknown" in r["detail"]]
    assert notes  # the unknown tier is recorded


def test_base_score_is_clamped_to_unit_interval() -> None:
    assert compute_confidence(1.5).score == 1.0
    assert compute_confidence(-0.2).score == 0.0


def test_computation_is_deterministic() -> None:
    kwargs = dict(
        schedule_quality="fair",
        feed_coverage="partial",
        corroboration=["document_backed"],
    )
    a = compute_confidence(0.7, **kwargs)
    b = compute_confidence(0.7, **kwargs)
    assert a.as_dict() == b.as_dict()


class _ConfigRow:
    """Duck-typed stand-in for a ConfidenceConfig ORM row."""

    def __init__(self, **kwargs) -> None:
        self.band_thresholds = kwargs.get("band_thresholds")
        self.schedule_quality_caps = kwargs.get("schedule_quality_caps")
        self.feed_coverage_caps = kwargs.get("feed_coverage_caps")
        self.corroboration_bonuses = kwargs.get("corroboration_bonuses")
        self.version = kwargs.get("version", 3)


def test_from_config_falls_back_for_missing_facets() -> None:
    # Only override the schedule-quality caps; everything else defaults.
    policy = ConfidencePolicy.from_config(_ConfigRow(schedule_quality_caps={"poor": 0.2}))
    assert policy.version == 3
    assert policy.schedule_quality_caps["poor"] == 0.2
    # Falls back to built-in defaults for the untouched facets.
    assert policy.band_thresholds == ConfidencePolicy.default().band_thresholds
    assert policy.corroboration_bonuses == ConfidencePolicy.default().corroboration_bonuses

    result = compute_confidence(0.9, schedule_quality="poor", policy=policy)
    assert result.score == 0.2  # the overridden cap is honoured


@pytest.mark.parametrize(
    "score,expected",
    [
        (0.75, ConfidenceBand.HIGH),
        (0.74, ConfidenceBand.MEDIUM),
        (0.5, ConfidenceBand.MEDIUM),
        (0.49, ConfidenceBand.LOW),
    ],
)
def test_band_thresholds_at_boundaries(score: float, expected: ConfidenceBand) -> None:
    assert compute_confidence(score).band == expected
