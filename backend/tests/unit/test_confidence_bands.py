# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Unit tests for the v3-P9 :func:`confidence_band_for` derivation.

Per MAPPING_PROCESS.md v3 §6.4 the confidence band is no longer a pure
score threshold — it factors in:

* the count of *hard* SearchPlan filters that survived into the
  candidate's payload (more hard filters → tighter search → MEDIUM
  scores promote to HIGH), and
* the candidate row's ``classification_confidence`` field from CWICR
  (rates with low-confidence classifications need a higher score to
  promote, high-confidence ones need slightly less).

The bonuses are additive *floors*, not multiplicative — they make it
*easier* to clear a band but never raise the bar above the configured
``CONFIDENCE_*_THRESHOLD`` values (v3 BGE-M3 defaults: 0.78 / 0.62).
"""

from __future__ import annotations

import pytest

from app.core.match_service.config import (
    CONFIDENCE_HIGH_THRESHOLD,
    CONFIDENCE_MEDIUM_THRESHOLD,
)
from app.core.match_service.envelope import confidence_band_for

# ── v2 back-compat: pure threshold mode ──────────────────────────────────


def test_confidence_band_high_when_score_above_high_threshold() -> None:
    """v2 contract: ``score >= HIGH_THRESHOLD`` → HIGH, no extras needed."""
    assert confidence_band_for(0.99) == "high"
    assert confidence_band_for(CONFIDENCE_HIGH_THRESHOLD) == "high"


def test_confidence_band_medium_in_window() -> None:
    # Halfway between MEDIUM and HIGH thresholds — guaranteed MEDIUM
    # regardless of how the bands are tuned.
    midpoint = (CONFIDENCE_MEDIUM_THRESHOLD + CONFIDENCE_HIGH_THRESHOLD) / 2
    assert confidence_band_for(midpoint) == "medium"
    assert confidence_band_for(CONFIDENCE_MEDIUM_THRESHOLD) == "medium"


def test_confidence_band_low_below_medium_threshold() -> None:
    # Pick a score safely below the MEDIUM floor regardless of tuning.
    assert confidence_band_for(CONFIDENCE_MEDIUM_THRESHOLD - 0.10) == "low"
    assert confidence_band_for(0.0) == "low"


def test_confidence_band_v2_signature_still_works_with_no_kwargs() -> None:
    """Existing callsites that pass only ``score`` must keep working —
    extending the signature can never break them."""
    for s in [0.30, 0.65, 0.78, 0.92]:
        # No raise + non-empty band
        band = confidence_band_for(s)
        assert band in {"high", "medium", "low"}


# ── v3-P9 §6.4: hard-filter count promotes the band ──────────────────────


def test_three_hard_filters_promote_score_075_to_high() -> None:
    """3+ hard filters narrow the search enough that a ~0.75 vector
    score is convincing — it should land in HIGH band even when the
    score is below ``CONFIDENCE_HIGH_THRESHOLD``."""
    assert confidence_band_for(0.75, hard_filters_matched=3) == "high"
    assert confidence_band_for(0.76, hard_filters_matched=4) == "high"


def test_one_hard_filter_promotes_060_to_medium() -> None:
    """A single hard filter is enough to clear the MEDIUM floor at 0.60
    even when the score is below ``CONFIDENCE_MEDIUM_THRESHOLD``."""
    assert confidence_band_for(0.61, hard_filters_matched=1) == "medium"
    assert confidence_band_for(0.65, hard_filters_matched=2) == "medium"


def test_two_hard_filters_dont_reach_high_floor() -> None:
    """The HIGH bonus requires 3+ filters — 2 is medium territory.

    Pick a score below ``CONFIDENCE_HIGH_THRESHOLD`` so the test stays
    meaningful regardless of where the band is pinned. The score must
    still clear the MEDIUM floor under the bonus (0.60) so it doesn't
    fall through to LOW."""
    score = CONFIDENCE_HIGH_THRESHOLD - 0.05
    assert confidence_band_for(score, hard_filters_matched=2) == "medium"


def test_high_score_lands_in_high_regardless_of_hard_filter_count() -> None:
    """The bonuses *relax* floors, never raise them — a 0.95 score with
    zero hard filters is still HIGH."""
    assert confidence_band_for(0.95, hard_filters_matched=0) == "high"
    assert confidence_band_for(0.95, hard_filters_matched=10) == "high"


def test_low_score_stays_low_even_with_many_hard_filters() -> None:
    """The HIGH bonus floor is 0.75 — anything below that with hard
    filters still maxes out at MEDIUM (or LOW)."""
    assert confidence_band_for(0.40, hard_filters_matched=5) == "low"
    assert confidence_band_for(0.55, hard_filters_matched=5) == "low"


# ── v3-P9: classification_confidence shifts floors ───────────────────────


def test_high_classification_confidence_relaxes_floors_slightly() -> None:
    """A CWICR row stamped ``classification_confidence='high'`` shifts
    the floors down by 0.02 — a score 0.02 below ``CONFIDENCE_HIGH_THRESHOLD``
    that would otherwise be MEDIUM lands in HIGH."""
    score = CONFIDENCE_HIGH_THRESHOLD - 0.02
    assert confidence_band_for(score, classification_confidence="high") == "high"


def test_low_classification_confidence_tightens_floors_slightly() -> None:
    """``classification_confidence='low'`` shifts the floors UP by
    0.03 — a score that would normally clear HIGH lands in MEDIUM."""
    # Score is 0.02 above HIGH (would normally be HIGH) but
    # ``low`` cls bumps the floor by 0.03 → MEDIUM.
    score_just_high = CONFIDENCE_HIGH_THRESHOLD + 0.02
    assert confidence_band_for(score_just_high, classification_confidence="low") == "medium"
    # A clean 0.99 still clears even the tightened floor.
    assert confidence_band_for(0.99, classification_confidence="low") == "high"


def test_unknown_classification_confidence_is_a_no_op() -> None:
    """Defensive: any value other than 'high'/'low' (case-folded)
    falls back to the v2 thresholds."""
    # Score sits between MEDIUM and HIGH so the no-op verdict is MEDIUM.
    score = CONFIDENCE_HIGH_THRESHOLD - 0.05
    assert confidence_band_for(score, classification_confidence="unknown") == "medium"
    assert confidence_band_for(score, classification_confidence="") == "medium"
    assert confidence_band_for(score, classification_confidence=None) == "medium"


def test_classification_case_insensitive() -> None:
    score = CONFIDENCE_HIGH_THRESHOLD - 0.02
    assert confidence_band_for(score, classification_confidence="HIGH") == "high"
    assert confidence_band_for(score, classification_confidence="High") == "high"
    assert confidence_band_for(score, classification_confidence="  high  ") == "high"


# ── v3-P9: bonuses compound but are bounded ──────────────────────────────


def test_hard_filter_and_high_classification_compound_for_more_relaxation() -> None:
    """3 hard filters + 'high' classification → both relaxations stack.

    The HIGH floor drops to ``min(HIGH-0.02, 0.75-0.02) = 0.73`` (the
    hard-filter bonus floor of 0.75 minus the cls offset of 0.02).
    Compute it from the resolved constants so a future re-tuning of
    ``CONFIDENCE_HIGH_THRESHOLD`` doesn't silently break this case."""
    # The hard-filter HIGH bonus floor is 0.75 — the relaxed floor is
    # 0.75 - 0.02 = 0.73 regardless of where CONFIDENCE_HIGH_THRESHOLD
    # is pinned (the bonus floor is the lower of the two ⇒ wins).
    assert (
        confidence_band_for(
            0.73,
            hard_filters_matched=3,
            classification_confidence="high",
        )
        == "high"
    )


def test_hard_filter_relaxation_never_inverts_low_into_medium_band() -> None:
    """A score below the MEDIUM_BONUS_FLOOR (0.60) never becomes MEDIUM
    no matter how many hard filters matched."""
    assert confidence_band_for(0.55, hard_filters_matched=10) == "low"
    assert confidence_band_for(0.55, hard_filters_matched=10, classification_confidence="high") == "low"


@pytest.mark.parametrize(
    ("score", "hard", "cls", "expected"),
    [
        # Cases insensitive to where the bands are pinned (use the
        # well-defined hard-filter bonus floors of 0.75 / 0.60 instead).
        (0.99, 0, None, "high"),  # clean HIGH regardless of tuning
        (0.78, 3, None, "high"),  # 3 hard filters promote → HIGH (≥ 0.75 floor)
        (0.61, 1, None, "medium"),  # 1 hard filter promotes → MEDIUM (≥ 0.60 floor)
        (0.55, 10, "high", "low"),  # below MEDIUM floor 0.60 — no promotion
    ],
)
def test_band_derivation_matrix_threshold_insensitive(score: float, hard: int, cls: str | None, expected: str) -> None:
    """Cases pinned on the HARD-FILTER floors (0.75 / 0.60), not on
    ``CONFIDENCE_*_THRESHOLD`` — survive future re-pinning."""
    assert confidence_band_for(score, hard_filters_matched=hard, classification_confidence=cls) == expected


def test_band_derivation_matrix_threshold_relative() -> None:
    """Cases that depend on the actual band pinning — derive scores from
    the constants rather than hardcoding so a future calibration is a
    one-line edit instead of a matrix rebuild."""
    # No-bonus path: score halfway between MEDIUM and HIGH → MEDIUM.
    mid = (CONFIDENCE_MEDIUM_THRESHOLD + CONFIDENCE_HIGH_THRESHOLD) / 2
    assert confidence_band_for(mid, hard_filters_matched=0) == "medium"

    # Score one step below MEDIUM with no bonus → LOW.
    below_med = CONFIDENCE_MEDIUM_THRESHOLD - 0.05
    assert confidence_band_for(below_med, hard_filters_matched=0) == "low"

    # cls=high relaxes by 0.02 — a score 0.02 below HIGH lands in HIGH.
    just_below_high = CONFIDENCE_HIGH_THRESHOLD - 0.02
    assert confidence_band_for(just_below_high, classification_confidence="high") == "high"

    # cls=low tightens by 0.03 — a score 0.02 above HIGH lands in MEDIUM.
    just_above_high = CONFIDENCE_HIGH_THRESHOLD + 0.02
    assert confidence_band_for(just_above_high, classification_confidence="low") == "medium"
