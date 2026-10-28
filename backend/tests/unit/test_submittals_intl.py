"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure, international submittal helpers in ``intl.py``.

These tests need no database and no FastAPI app; they exercise the
dependency-free reporting helpers directly. They cover the international
behaviour (ISO dates, localisation with English fallback, SLA as a
parameter), the plain-language explainers, the guarded edge cases
(division by zero, empty sets, negative counts, a review returned before it
was submitted), and the composite summary that exposes its components.
"""

from __future__ import annotations

import pytest

from app.modules.submittals import intl

# ── Localisation ──────────────────────────────────────────────────────────


def test_localize_status_translates_known_languages() -> None:
    assert intl.localize_status("approved", "en") == "Approved"
    assert intl.localize_status("approved", "de") == "Genehmigt"
    assert intl.localize_status("approved", "ru") == "Утверждено"


def test_localize_status_region_tag_reduced_to_base_language() -> None:
    assert intl.localize_status("rejected", "de-DE") == "Abgelehnt"
    assert intl.localize_status("rejected", "ru_RU") == "Отклонено"


def test_localize_status_unknown_language_falls_back_to_english() -> None:
    # An unsupported language falls back to the English label.
    assert intl.localize_status("under_review", "xx") == "Under review"
    assert intl.localize_status("under_review", None) == "Under review"


def test_localize_status_unknown_status_is_humanised_not_raised() -> None:
    assert intl.localize_status("some_new_state", "de") == "Some new state"


def test_localize_outcome_matches_status_wording() -> None:
    for lang in ("en", "de", "ru"):
        assert intl.localize_outcome("revise_and_resubmit", lang) == intl.localize_status("revise_and_resubmit", lang)


def test_normalize_language_defaults_to_english() -> None:
    assert intl.normalize_language("") == "en"
    assert intl.normalize_language(None) == "en"
    assert intl.normalize_language("DE") == "de"


# ── ISO date parsing and cycle time ───────────────────────────────────────


def test_parse_iso_date_rejects_bad_input() -> None:
    with pytest.raises(ValueError, match="ISO 8601"):
        intl.parse_iso_date("31/12/2026")
    with pytest.raises(ValueError, match="non-empty"):
        intl.parse_iso_date("")


def test_review_cycle_time_days_counts_whole_days() -> None:
    assert intl.review_cycle_time_days("2026-01-01", "2026-01-15") == 14


def test_review_cycle_time_days_same_day_is_zero() -> None:
    assert intl.review_cycle_time_days("2026-01-01", "2026-01-01") == 0


def test_review_cycle_time_days_returned_before_submitted_raises() -> None:
    # A clean ValueError, never a misleading negative number.
    with pytest.raises(ValueError, match="precedes"):
        intl.review_cycle_time_days("2026-01-15", "2026-01-01")


def test_iso_days_between_is_signed() -> None:
    assert intl.iso_days_between("2026-01-15", "2026-01-01") == -14


# ── Due date and overdue flag (parameterised SLA) ─────────────────────────


def test_review_due_date_adds_sla_days() -> None:
    assert intl.review_due_date("2026-01-01", sla_days=14) == "2026-01-15"


def test_review_due_date_negative_sla_raises() -> None:
    with pytest.raises(ValueError, match="zero or positive"):
        intl.review_due_date("2026-01-01", sla_days=-1)


def test_is_review_overdue_respects_sla_grace() -> None:
    # Due 2026-01-10, as of 2026-01-12 that is 2 days late; a 3-day SLA
    # grace keeps it on time, a 1-day grace makes it overdue.
    assert intl.is_review_overdue("2026-01-10", "2026-01-12", sla_days=3) is False
    assert intl.is_review_overdue("2026-01-10", "2026-01-12", sla_days=1) is True


def test_is_review_overdue_default_grace_is_zero() -> None:
    assert intl.is_review_overdue("2026-01-10", "2026-01-11") is True
    assert intl.is_review_overdue("2026-01-10", "2026-01-10") is False


def test_is_review_overdue_returned_review_never_overdue() -> None:
    assert intl.is_review_overdue("2026-01-01", "2026-06-01", returned=True) is False


def test_is_review_overdue_before_due_is_not_overdue() -> None:
    assert intl.is_review_overdue("2026-01-10", "2026-01-05") is False


# ── Approval rate (guarded) ───────────────────────────────────────────────


def test_approval_rate_basic() -> None:
    assert intl.approval_rate(3, 4) == 0.75
    assert intl.approval_rate_percent(3, 4) == 75.0


def test_approval_rate_zero_reviewed_is_guarded() -> None:
    # Division-by-zero guard: no reviews yields a defined 0.0, never NaN.
    assert intl.approval_rate(0, 0) == 0.0
    assert intl.approval_rate_percent(0, 0) == 0.0


def test_approval_rate_stays_in_unit_interval() -> None:
    for approved, reviewed in ((0, 5), (5, 5), (1, 3)):
        rate = intl.approval_rate(approved, reviewed)
        assert 0.0 <= rate <= 1.0
        assert 0.0 <= intl.approval_rate_percent(approved, reviewed) <= 100.0


def test_approval_rate_negative_counts_raise() -> None:
    with pytest.raises(ValueError, match="zero or positive"):
        intl.approval_rate(-1, 5)


def test_approval_rate_more_approved_than_reviewed_raises() -> None:
    with pytest.raises(ValueError, match="cannot exceed"):
        intl.approval_rate(6, 5)


# ── Counts (empty sets and unknowns) ──────────────────────────────────────


def test_counts_by_status_zero_fills_all_statuses() -> None:
    counts = intl.counts_by_status([])
    assert set(counts) == set(intl.SUBMITTAL_STATUSES)
    assert all(value == 0 for value in counts.values())


def test_counts_by_status_tallies() -> None:
    counts = intl.counts_by_status(["draft", "draft", "approved"])
    assert counts["draft"] == 2
    assert counts["approved"] == 1
    assert counts["closed"] == 0


def test_counts_by_outcome_tallies_and_zero_fills() -> None:
    counts = intl.counts_by_outcome(["approved", "rejected", "approved"])
    assert counts["approved"] == 2
    assert counts["rejected"] == 1
    assert counts["approved_as_noted"] == 0
    assert set(counts) == set(intl.REVIEW_OUTCOMES)


def test_counts_by_outcome_unknown_raises() -> None:
    with pytest.raises(ValueError, match="Unknown outcome"):
        intl.counts_by_outcome(["approved", "not_a_real_outcome"])


# ── Explainers ────────────────────────────────────────────────────────────


def test_explainers_are_nonempty_single_line() -> None:
    for explainer in (
        intl.explain_submittal(),
        intl.explain_review_cycle_time(),
        intl.explain_approval_rate(),
        intl.explain_overdue_review(),
    ):
        assert isinstance(explainer, str)
        assert explainer.strip()
        assert "\n" not in explainer


# ── Composite summary ─────────────────────────────────────────────────────


def test_summarize_review_performance_exposes_components() -> None:
    summary = intl.summarize_review_performance(
        ["approved", "approved_as_noted", "rejected", "revise_and_resubmit"],
        cycle_times_days=[10, 20],
        language="de",
    )
    assert summary["reviewed_count"] == 4
    # approved + approved_as_noted both count as approving.
    assert summary["approved_count"] == 2
    assert summary["approval_rate"] == 0.5
    assert summary["approval_rate_percent"] == 50.0
    assert summary["average_cycle_time_days"] == 15.0
    assert summary["language"] == "de"
    # Localised tally uses the German labels.
    assert summary["counts_by_outcome_localized"]["Genehmigt"] == 1
    assert set(summary["explainers"]) == {
        "submittal",
        "review_cycle_time",
        "approval_rate",
        "overdue_review",
    }


def test_summarize_review_performance_empty_is_well_defined() -> None:
    summary = intl.summarize_review_performance([])
    assert summary["reviewed_count"] == 0
    assert summary["approval_rate"] == 0.0
    assert summary["average_cycle_time_days"] is None
    assert summary["cycle_time_sample_count"] == 0
    assert summary["language"] == "en"


def test_summarize_review_performance_negative_cycle_sample_raises() -> None:
    with pytest.raises(ValueError, match="zero or positive"):
        intl.summarize_review_performance(["approved"], cycle_times_days=[-1])


# ── Clean-character guarantee ─────────────────────────────────────────────


def _banned_characters() -> set[str]:
    """Build the banned set from code points, never as a literal string.

    Covers em dash, en dash, curly single and double quotes, and the common
    zero-width characters. Building from ``chr()`` keeps this source file
    itself free of those characters.
    """
    code_points = (
        0x2014,  # em dash
        0x2013,  # en dash
        0x2018,  # left single quote
        0x2019,  # right single quote
        0x201C,  # left double quote
        0x201D,  # right double quote
        0x200B,  # zero-width space
        0x200C,  # zero-width non-joiner
        0x200D,  # zero-width joiner
        0x2060,  # word joiner
        0xFEFF,  # zero-width no-break space
    )
    return {chr(cp) for cp in code_points}


def test_localized_and_explainer_text_has_no_banned_characters() -> None:
    banned = _banned_characters()
    samples: list[str] = [
        intl.explain_submittal(),
        intl.explain_review_cycle_time(),
        intl.explain_approval_rate(),
        intl.explain_overdue_review(),
    ]
    for lang in ("en", "de", "ru"):
        for status_value in intl.SUBMITTAL_STATUSES:
            samples.append(intl.localize_status(status_value, lang))
        for outcome in intl.REVIEW_OUTCOMES:
            samples.append(intl.localize_outcome(outcome, lang))
    for text in samples:
        assert not (banned & set(text)), f"banned character in {text!r}"
