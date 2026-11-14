# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""No demo programme activity starts before the project's own start.

Hand-written programmes carry literal calendar dates while the rest of a demo
hangs off the rolling anchor, so a programme written for an earlier month used
to open with phases finished before the project began. The installer now moves
such a programme forward as a block.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.core.demo_projects import DEMO_TEMPLATES, _anchored_schedule_spans, _demo_anchor, _phase_progress

_ANCHOR = datetime(2026, 8, 1)


def test_programme_before_the_anchor_moves_as_a_block() -> None:
    spans = _anchored_schedule_spans(
        [
            ("Design", "2026-04-01", "2026-06-30"),
            ("Piling", "2026-06-01", "2026-08-31"),
        ],
        _ANCHOR,
    )
    assert spans[0][1] == _ANCHOR
    # Gaps and durations survive the move.
    assert (spans[1][1] - spans[0][1]).days == 61
    assert (spans[0][2] - spans[0][1]).days == 90
    assert (spans[1][2] - spans[1][1]).days == 91


def test_programme_after_the_anchor_is_left_as_written() -> None:
    spans = _anchored_schedule_spans([("Design", "2026-09-01", "2026-10-01")], _ANCHOR)
    assert spans == [("Design", datetime(2026, 9, 1), datetime(2026, 10, 1))]


def test_design_phase_never_starts_before_the_project_and_progress_follows_the_calendar() -> None:
    (_n, start, end), *_ = _anchored_schedule_spans([("Design", "2026-04-01", "2026-06-30")], _ANCHOR)
    assert start >= _ANCHOR
    prog, status = _phase_progress(start, end, datetime(2026, 9, 1))
    assert (prog, status) == (34, "in_progress")


@pytest.mark.parametrize(
    "demo_id", sorted(k for k, t in DEMO_TEMPLATES.items() if getattr(t, "schedule_activities", None))
)
def test_no_hand_written_activity_starts_before_the_anchor(demo_id: str) -> None:
    anchor = _demo_anchor()
    spans = _anchored_schedule_spans(DEMO_TEMPLATES[demo_id].schedule_activities, anchor)
    assert spans
    for name, start, end in spans:
        assert start >= anchor, f"{demo_id}: {name} starts before the project start"
        assert end >= start, f"{demo_id}: {name} ends before it starts"


def test_riyadh_declares_an_einvoice_showcase_for_a_saudi_seller() -> None:
    showcase = DEMO_TEMPLATES["full-showcase-riyadh"].einvoice_showcase
    seller = showcase["einvoice"]["seller"]
    assert seller["country_code"] == "SA"
    assert seller["name"]
    assert len(seller["vat_id"]) == 15
    assert showcase["invoice"]["invoice_number"]
