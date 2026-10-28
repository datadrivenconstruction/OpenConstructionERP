# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure AI feedback rollup engine.

Dependency-free: exercises :func:`summarize_feedback` directly so the overall /
per-surface counts, the alphabetical surface order, and the "no verdicts ->
None rate" rule are pinned without a database.
"""

from __future__ import annotations

from app.modules.ai_agents.feedback_summary import FeedbackItem, summarize_feedback


def test_empty_yields_zero_counts_and_none_rate() -> None:
    summary = summarize_feedback([])
    assert summary.total == 0
    assert summary.correct == 0
    assert summary.incorrect == 0
    # None, not 0.0 - "no feedback yet" must be distinguishable from "all wrong".
    assert summary.correct_rate is None
    assert summary.by_surface == []


def test_rolls_up_overall_and_per_surface() -> None:
    items = [
        FeedbackItem("ai_estimator", True),
        FeedbackItem("ai_estimator", True),
        FeedbackItem("ai_estimator", False),
        FeedbackItem("match_elements", False),
    ]
    summary = summarize_feedback(items)

    assert summary.total == 4
    assert summary.correct == 2
    assert summary.incorrect == 2
    assert summary.correct_rate == 0.5

    # Surfaces are returned alphabetically for a stable response.
    assert [b.surface for b in summary.by_surface] == ["ai_estimator", "match_elements"]

    estimator = summary.by_surface[0]
    assert (estimator.total, estimator.correct, estimator.incorrect) == (3, 2, 1)
    assert estimator.correct_rate == round(2 / 3, 4)

    match = summary.by_surface[1]
    assert (match.total, match.correct, match.incorrect) == (1, 0, 1)
    assert match.correct_rate == 0.0


def test_all_correct_rate_is_one() -> None:
    summary = summarize_feedback([FeedbackItem("advisor", True), FeedbackItem("advisor", True)])
    assert summary.correct_rate == 1.0
    assert summary.by_surface[0].correct_rate == 1.0
