# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The figures the submittal register derives, and what a review writes.

No database: ``tracking`` is standard library only and the clock is an
argument, so every date here is pinned and none of this rots.

What is held:

* the reviewer's decision and the mark stamped for it, including a row written
  before either was stored;
* days in review, and "overdue for review" being unknown, not false and not a
  default, when no review period is recorded;
* the date an approval is needed by, required on site less lead time, and the
  days past it while the item is still not approved;
* what a review appends to the history, and that a returned revision is
  replaced by the next one whether it came back for revision or was rejected;
* the register header counts, where "unknown" has its own figure.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from app.modules.submittals import tracking
from app.modules.submittals.intl import REVIEW_OUTCOMES as INTL_REVIEW_OUTCOMES
from app.modules.submittals.pdf_translations import CATALOGUE
from app.modules.submittals.schemas import (
    SubmittalCreate,
    SubmittalReviewRequest,
    SubmittalUpdate,
)

TODAY = "2026-10-10"
PROJECT = "22222222-2222-2222-2222-222222222222"


def _row(**overrides: object) -> SimpleNamespace:
    """A submittal under review, with nothing of the register recorded yet."""
    base: dict[str, object] = {
        "status": "under_review",
        "submittal_type": "product_data",
        "current_revision": 1,
        "date_submitted": "2026-09-20",
        "date_returned": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# ── Vocabulary ────────────────────────────────────────────────────────────


def test_the_outcomes_are_the_modules_own_four_decisions() -> None:
    """The stamp does not bring a second outcome vocabulary beside the review's."""
    assert tracking.REVIEW_OUTCOMES == INTL_REVIEW_OUTCOMES
    assert set(tracking.DEFAULT_REVIEW_CODES) == set(tracking.REVIEW_OUTCOMES)
    assert [tracking.DEFAULT_REVIEW_CODES[o] for o in tracking.REVIEW_OUTCOMES] == ["A", "B", "C", "D"]


def test_every_default_discipline_has_a_code_a_mark_and_both_labels() -> None:
    codes = [item.code for item in tracking.DISCIPLINES]
    marks = [item.short for item in tracking.DISCIPLINES]
    assert len(set(codes)) == len(codes)
    assert len(set(marks)) == len(marks)
    for item in tracking.DISCIPLINES:
        assert item.code == item.code.lower()
        assert len(item.short) == 2
        assert item.short.isupper()
        assert item.labels["en"].strip()
        assert item.labels["tr"].strip()
        # The printed catalogue is built from this list, not kept beside it.
        assert CATALOGUE.label("discipline", item.code, "tr") == item.labels["tr"]
    # The trades a building services contractor splits its log by are offered.
    assert {"hvac", "plumbing", "fire_protection", "electrical", "lighting", "elv", "bms"} <= set(codes)


def test_a_discipline_outside_the_list_is_accepted_and_printed_as_stored() -> None:
    created = SubmittalCreate(project_id=PROJECT, title="T", submittal_type="sample", discipline="vertical_transport")
    assert created.discipline == "vertical_transport"
    assert CATALOGUE.label("discipline", "vertical_transport", "tr") == "vertical_transport"


def test_hand_typed_codes_are_brought_to_their_stored_spelling() -> None:
    created = SubmittalCreate(
        project_id=PROJECT, title="T", submittal_type="sample", discipline="Fire Protection", country_of_origin="tr"
    )
    assert created.discipline == "fire_protection"
    assert created.country_of_origin == "TR"
    assert SubmittalUpdate(manufacturer="   ").manufacturer is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("discipline", "çelik"),
        ("country_of_origin", "TUR"),
        ("lead_time_weeks", -1),
        ("review_period_days", -3),
        ("required_on_site_date", "10.10.2026"),
    ],
)
def test_a_malformed_register_value_is_refused(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        SubmittalUpdate(**{field: value})


def test_a_plain_edit_cannot_write_the_reviewers_stamp() -> None:
    """The stamp is written by the role-gated review, never by PATCH."""
    assert "review_outcome" not in SubmittalUpdate.model_fields
    assert "review_code" not in SubmittalUpdate.model_fields
    assert "review_history" not in SubmittalUpdate.model_fields
    assert SubmittalReviewRequest(status="approved_as_noted", code="2").code == "2"


# ── The decision and its mark ─────────────────────────────────────────────


def test_a_stored_outcome_wins_and_survives_the_status_moving_on() -> None:
    closed = _row(status="closed", review_outcome="approved_as_noted", review_code="B")
    figures = tracking.track(closed, TODAY)
    assert figures.outcome == "approved_as_noted"
    assert figures.code == "B"
    assert figures.may_proceed is True


def test_a_row_from_before_the_stamp_reads_its_decision_from_the_status() -> None:
    """An existing installation's approved rows are still approved."""
    legacy = SimpleNamespace(status="approved", current_revision=1, date_submitted="2026-09-01", date_returned=None)
    figures = tracking.track(legacy, TODAY)
    assert figures.outcome == "approved"
    assert figures.code == "A"
    assert figures.may_proceed is True


def test_no_decision_means_no_code() -> None:
    figures = tracking.track(_row(), TODAY)
    assert figures.outcome is None
    assert figures.code is None
    assert figures.may_proceed is False


def test_the_mark_is_printed_as_the_reviewer_wrote_it() -> None:
    """A project whose reviewer stamps numbers is not rewritten into letters."""
    figures = tracking.track(
        _row(status="approved_as_noted", review_outcome="approved_as_noted", review_code="2"), TODAY
    )
    assert figures.code == "2"


@pytest.mark.parametrize(
    "outcome,proceeds",
    [
        ("approved", True),
        ("approved_as_noted", True),
        ("revise_and_resubmit", False),
        ("rejected", False),
        (None, False),
    ],
)
def test_only_an_approval_releases_the_work(outcome: str | None, proceeds: bool) -> None:
    assert tracking.may_proceed(outcome) is proceeds


# ── Days in review, overdue for review ────────────────────────────────────


def test_days_in_review_run_to_today_while_the_reviewer_has_it() -> None:
    assert tracking.track(_row(), TODAY).days_in_review == 20


def test_days_in_review_stop_at_the_return() -> None:
    returned = _row(status="revise_and_resubmit", date_returned="2026-09-27")
    assert tracking.track(returned, TODAY).days_in_review == 7


def test_days_in_review_are_unknown_for_a_draft_and_for_dates_that_run_backwards() -> None:
    assert tracking.track(_row(status="draft", date_submitted=None), TODAY).days_in_review is None
    assert tracking.track(_row(date_returned="2026-09-01"), TODAY).days_in_review is None


def test_overdue_for_review_is_unknown_without_a_review_period() -> None:
    """Twenty days with the reviewer is not late until a contract says what late is."""
    figures = tracking.track(_row(), TODAY)
    assert figures.review_due_date is None
    assert figures.review_overdue_days is None
    assert figures.review_overdue is False


def test_overdue_for_review_counts_from_the_contractual_period() -> None:
    figures = tracking.track(_row(review_period_days=14), TODAY)
    assert figures.review_due_date == date(2026, 10, 4)
    assert figures.review_overdue_days == 6
    assert figures.review_overdue is True


def test_a_review_inside_its_period_is_not_overdue() -> None:
    figures = tracking.track(_row(review_period_days=21), TODAY)
    assert figures.review_overdue_days == 0
    assert figures.review_overdue is False


def test_a_returned_submittal_is_not_overdue_for_review() -> None:
    returned = _row(status="approved", date_returned="2026-10-09", review_period_days=14)
    assert tracking.track(returned, TODAY).review_overdue_days is None


# ── Required on site, lead time, approval needed by ───────────────────────


def test_approval_is_needed_by_required_on_site_less_lead_time() -> None:
    figures = tracking.track(_row(required_on_site_date="2027-01-18", lead_time_weeks=12), TODAY)
    assert figures.approval_needed_by == date(2026, 10, 26)
    assert figures.approval_late_days == 0
    assert figures.approval_late is False


def test_past_the_needed_by_date_an_unapproved_item_is_late_by_that_many_days() -> None:
    figures = tracking.track(_row(required_on_site_date="2026-12-14", lead_time_weeks=12), TODAY)
    assert figures.approval_needed_by == date(2026, 9, 21)
    assert figures.approval_late_days == 19
    assert figures.approval_late is True


def test_an_approved_item_is_no_longer_late() -> None:
    approved = _row(status="approved_as_noted", required_on_site_date="2026-12-14", lead_time_weeks=12)
    assert tracking.track(approved, TODAY).approval_late_days is None


def test_no_lead_time_means_no_needed_by_date_rather_than_a_guess() -> None:
    figures = tracking.track(_row(required_on_site_date="2026-12-14", long_lead=True), TODAY)
    assert figures.approval_needed_by is None
    assert figures.approval_late_days is None


def test_a_zero_lead_time_is_a_lead_time() -> None:
    figures = tracking.track(_row(required_on_site_date="2026-10-20", lead_time_weeks=0), TODAY)
    assert figures.approval_needed_by == date(2026, 10, 20)


def test_the_last_day_to_submit_leaves_one_full_review() -> None:
    figures = tracking.track(_row(required_on_site_date="2027-01-18", lead_time_weeks=12, review_period_days=14), TODAY)
    assert figures.submit_by_date == date(2026, 10, 12)
    assert tracking.track(_row(required_on_site_date="2027-01-18", lead_time_weeks=12), TODAY).submit_by_date is None


# ── What a review writes ──────────────────────────────────────────────────


def test_a_review_stamps_the_row_and_appends_to_the_history() -> None:
    row = _row(review_history=[])
    fields = tracking.review_stamp(
        row,
        "revise_and_resubmit",
        code=None,
        reviewer_id="r-1",
        date_returned="2026-10-01",
        notes=" Fan curves missing ",
    )
    assert fields["review_outcome"] == "revise_and_resubmit"
    assert fields["review_code"] == "C"
    assert fields["review_history"] == [
        {
            "revision": 1,
            "outcome": "revise_and_resubmit",
            "code": "C",
            "date_submitted": "2026-09-20",
            "date_returned": "2026-10-01",
            "reviewer_id": "r-1",
            "notes": "Fan curves missing",
            "resubmit_for_record": False,
        }
    ]
    # The list the row holds is not the one that was written: the ORM does not
    # notice an append to a JSON list it already has.
    assert row.review_history == []


def test_the_history_keeps_every_cycle_in_order() -> None:
    first = tracking.review_stamp(_row(), "revise_and_resubmit", code="C", reviewer_id="r", date_returned="2026-10-01")
    second_row = _row(current_revision=2, date_submitted="2026-10-03", review_history=first["review_history"])
    second = tracking.review_stamp(second_row, "approved", code="A", reviewer_id="r", date_returned="2026-10-09")
    assert [(e["revision"], e["code"]) for e in second["review_history"]] == [(1, "C"), (2, "A")]
    assert tracking.latest_history_entry(second["review_history"], 1)["outcome"] == "revise_and_resubmit"
    assert tracking.latest_history_entry(second["review_history"], 3) is None


def test_approved_as_noted_can_owe_a_copy_for_the_record_and_still_proceeds() -> None:
    fields = tracking.review_stamp(
        _row(), "approved_as_noted", code="B", reviewer_id="r", date_returned="2026-10-01", resubmit_for_record=True
    )
    row = _row(status="approved_as_noted", **fields)
    figures = tracking.track(row, TODAY)
    assert figures.may_proceed is True
    assert figures.resubmit_for_record is True


def test_only_approved_as_noted_can_owe_a_copy_for_the_record() -> None:
    fields = tracking.review_stamp(
        _row(), "rejected", code=None, reviewer_id="r", date_returned="2026-10-01", resubmit_for_record=True
    )
    assert fields["review_history"][-1]["resubmit_for_record"] is False


@pytest.mark.parametrize(
    "status,outcome,replaced",
    [
        ("revise_and_resubmit", "revise_and_resubmit", True),
        # Taken back to draft after either answer: the answered revision is replaced.
        ("draft", "revise_and_resubmit", True),
        ("draft", "rejected", True),
        # A row from before the stamp was stored, sent back for revision.
        ("revise_and_resubmit", None, True),
        # A first submission replaces nothing.
        ("draft", None, False),
    ],
)
def test_submitting_after_an_answer_sends_in_the_next_revision(
    status: str, outcome: str | None, replaced: bool
) -> None:
    assert tracking.replaces_returned_revision(_row(status=status, review_outcome=outcome)) is replaced


# ── The register header ───────────────────────────────────────────────────


def test_the_header_counts_what_the_weekly_meeting_asks() -> None:
    rows = [
        # With the reviewer, past a 14 day period.
        _row(discipline="hvac", review_period_days=14),
        # With the reviewer, no period recorded: unknown, not "on time".
        _row(discipline="hvac", status="submitted"),
        # Long lead, not approved, already past its needed-by date.
        _row(discipline="electrical", long_lead=True, required_on_site_date="2026-12-14", lead_time_weeks=12),
        # Long lead with no lead time: cannot be dated.
        _row(discipline="electrical", status="draft", date_submitted=None, long_lead=True),
        # Approved long lead: no longer awaiting anything.
        _row(status="approved", review_outcome="approved", long_lead=True, date_returned="2026-10-01"),
        # Closed after approval as noted: still counted under its outcome.
        _row(status="closed", review_outcome="approved_as_noted", date_returned="2026-10-01"),
    ]
    summary = tracking.summarise(rows, TODAY)
    assert summary["total"] == 6
    assert summary["awaiting_review"] == 3
    assert summary["review_overdue"] == 1
    assert summary["review_period_unknown"] == 2
    assert summary["long_lead"] == 3
    assert summary["long_lead_awaiting_approval"] == 2
    assert summary["long_lead_without_lead_time"] == 1
    assert summary["approval_late"] == 1
    assert summary["by_outcome"] == {"approved": 1, "approved_as_noted": 1, "revise_and_resubmit": 0, "rejected": 0}
    assert summary["by_discipline"] == {"hvac": 2, "electrical": 2, "": 2}
    assert summary["by_status"] == {"under_review": 2, "submitted": 1, "draft": 1, "approved": 1, "closed": 1}


def test_an_empty_register_counts_to_zero() -> None:
    summary = tracking.summarise([], TODAY)
    assert summary["total"] == 0
    assert summary["by_discipline"] == {}
    assert set(summary["by_outcome"].values()) == {0}


def test_rows_from_before_the_register_columns_are_counted_without_error() -> None:
    """All the new columns absent: the counts still add up and nothing is late."""
    legacy = [
        SimpleNamespace(status="approved", submittal_type="shop_drawing", current_revision=1),
        SimpleNamespace(status="under_review", submittal_type="sample", current_revision=1),
    ]
    summary = tracking.summarise(legacy, TODAY)
    assert summary["total"] == 2
    assert summary["by_outcome"]["approved"] == 1
    assert summary["review_period_unknown"] == 1
    assert summary["approval_late"] == 0
    assert summary["long_lead"] == 0
