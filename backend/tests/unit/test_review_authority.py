# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure decision-core tests for the review-authority module.

Pins the jurisdiction-neutral logic without a DB or a clock:

* the contestability classifier flags a missing norm reference and never
  auto-decides contestability;
* the stale-version detector fires only once the pinned and live versions
  diverge;
* the repeat radar's normalised-token overlap flags close repeats and ignores
  unrelated text;
* the SLA timeline computes days remaining and the overdue flag, and never
  flags a terminal cycle overdue;
* the FSM transition tables are well-formed;
* the completeness validation rule and the /meta label lookups behave.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.review_authority import intl
from app.modules.review_authority.service import (
    CYCLE_TERMINAL,
    CYCLE_TRANSITIONS,
    REMARK_TRANSITIONS,
    classify_remark,
    cycle_timeline,
    find_repeats,
    is_remark_stale,
    normalise_tokens,
    token_overlap_ratio,
)
from app.modules.review_authority.validators import ReviewCycleCompletenessRule

_NOW = datetime(2026, 7, 21, tzinfo=UTC)


# ── classify_remark ────────────────────────────────────────────────────


def test_classify_with_norm_reference_is_grounded() -> None:
    assert classify_remark("Wall thickness insufficient", "SP 20.13330 cl. 6.2") == "has_norm_ref"


def test_classify_without_norm_reference_is_contestable() -> None:
    assert classify_remark("Reviewer thinks it looks thin", None) == "no_norm_ref_contestable"


def test_classify_blank_norm_reference_is_contestable() -> None:
    # A whitespace-only reference is treated as absent, not as a citation.
    assert classify_remark("Any text", "   ") == "no_norm_ref_contestable"


# ── is_remark_stale ────────────────────────────────────────────────────


def test_not_stale_before_submission() -> None:
    # No pinned version yet -> nothing is stale.
    assert is_remark_stale(None, "B") is False


def test_not_stale_when_versions_match() -> None:
    assert is_remark_stale("A", "A") is False


def test_stale_when_live_version_moved_on() -> None:
    assert is_remark_stale("A", "B") is True


# ── repeat radar ───────────────────────────────────────────────────────


def test_normalise_drops_stopwords() -> None:
    assert normalise_tokens("The wall is too thin") == {"wall", "too", "thin"}


def test_overlap_identical_text_is_one() -> None:
    assert token_overlap_ratio("fire rating missing on wall", "fire rating missing on wall") == 1.0


def test_overlap_unrelated_text_is_low() -> None:
    assert token_overlap_ratio("fire rating missing", "parking ramp gradient") == 0.0


def test_overlap_empty_text_is_zero() -> None:
    assert token_overlap_ratio("", "anything") == 0.0


def test_find_repeats_flags_close_match() -> None:
    prior = [
        {"id": "r1", "text": "Fire rating not specified on stair core wall"},
        {"id": "r2", "text": "Parking ramp gradient exceeds maximum"},
    ]
    hits = find_repeats("Fire rating not specified on stair core wall again", prior, threshold=0.6)
    assert hits == ["r1"]


def test_find_repeats_orders_by_similarity() -> None:
    prior = [
        {"id": "low", "text": "fire rating wall missing something else entirely here"},
        {"id": "high", "text": "fire rating missing on wall"},
    ]
    hits = find_repeats("fire rating missing on wall", prior, threshold=0.3)
    assert hits[0] == "high"


def test_find_repeats_skips_rows_without_id() -> None:
    prior = [{"text": "fire rating missing on wall"}]
    assert find_repeats("fire rating missing on wall", prior) == []


# ── cycle_timeline ─────────────────────────────────────────────────────


def test_timeline_no_clock_before_open() -> None:
    tl = cycle_timeline(opened_at=None, sla_days=42, due_at=None, status="draft", now=_NOW)
    assert tl == {"due_on": None, "days_remaining": None, "overdue": False}


def test_timeline_days_remaining_from_sla() -> None:
    opened = _NOW - timedelta(days=10)
    tl = cycle_timeline(opened_at=opened, sla_days=42, due_at=None, status="under_review", now=_NOW)
    assert tl["days_remaining"] == 32
    assert tl["overdue"] is False


def test_timeline_overdue_flag() -> None:
    opened = _NOW - timedelta(days=50)
    tl = cycle_timeline(opened_at=opened, sla_days=42, due_at=None, status="under_review", now=_NOW)
    assert tl["days_remaining"] == -8
    assert tl["overdue"] is True


def test_timeline_terminal_cycle_never_overdue() -> None:
    opened = _NOW - timedelta(days=50)
    tl = cycle_timeline(opened_at=opened, sla_days=42, due_at=None, status="approved", now=_NOW)
    assert tl["overdue"] is False


def test_timeline_explicit_due_at_wins() -> None:
    due = _NOW + timedelta(days=5)
    tl = cycle_timeline(
        opened_at=_NOW - timedelta(days=100),
        sla_days=42,
        due_at=due,
        status="under_review",
        now=_NOW,
    )
    assert tl["days_remaining"] == 5


# ── FSM tables ─────────────────────────────────────────────────────────


def test_cycle_fsm_terminal_states_have_no_exits() -> None:
    for terminal in CYCLE_TERMINAL:
        assert CYCLE_TRANSITIONS[terminal] == frozenset()


def test_cycle_fsm_submit_path() -> None:
    assert "submitted" in CYCLE_TRANSITIONS["draft"]
    assert "under_review" in CYCLE_TRANSITIONS["submitted"]


def test_remark_fsm_respond_then_decide() -> None:
    assert "responded" in REMARK_TRANSITIONS["open"]
    assert "accepted" in REMARK_TRANSITIONS["responded"]
    assert "contested" in REMARK_TRANSITIONS["responded"]
    # A responded remark cannot jump straight back to open.
    assert "open" not in REMARK_TRANSITIONS["responded"]


# ── validation rule ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_completeness_rule_flags_missing_pinned_version() -> None:
    from app.core.validation.engine import ValidationContext

    rule = ReviewCycleCompletenessRule()
    ctx = ValidationContext(
        data={"cycle": {"id": "c1", "status": "under_review", "pinned_document_version": None}, "remarks": []}
    )
    results = await rule.validate(ctx)
    assert any(not r.passed for r in results)


@pytest.mark.asyncio
async def test_completeness_rule_flags_approved_with_open_remarks() -> None:
    from app.core.validation.engine import ValidationContext

    rule = ReviewCycleCompletenessRule()
    ctx = ValidationContext(
        data={
            "cycle": {"id": "c1", "status": "approved", "pinned_document_version": "A"},
            "remarks": [{"ordinal": 1, "status": "open"}],
        }
    )
    results = await rule.validate(ctx)
    assert any(not r.passed for r in results)


@pytest.mark.asyncio
async def test_completeness_rule_passes_clean_approved_cycle() -> None:
    from app.core.validation.engine import ValidationContext

    rule = ReviewCycleCompletenessRule()
    ctx = ValidationContext(
        data={
            "cycle": {"id": "c1", "status": "approved", "pinned_document_version": "A"},
            "remarks": [{"ordinal": 1, "status": "accepted"}],
        }
    )
    results = await rule.validate(ctx)
    assert all(r.passed for r in results)


# ── intl labels ────────────────────────────────────────────────────────


def test_authority_kind_labels_localise() -> None:
    assert intl.describe_authority_kind("state_expertise", "ru") == "Государственная экспертиза"
    assert intl.describe_authority_kind("building_control", "en") == "Building control"


def test_classification_labels_localise() -> None:
    assert intl.describe_classification("no_norm_ref_contestable", "de") == "Kein Normbezug (anfechtbar)"


def test_unknown_locale_falls_back_to_english() -> None:
    assert intl.describe_cycle_status("approved", "zz") == "Approved"


def test_unknown_code_is_humanised_not_raw() -> None:
    assert intl.describe_authority_kind("planning_inspectorate", "en") == "Planning Inspectorate"
