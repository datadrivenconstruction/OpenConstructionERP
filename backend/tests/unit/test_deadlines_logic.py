# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure-function unit tests for the cross-module deadline logic (item #18).

These pin the DB-free helpers in ``app.modules.deadlines.logic``:

* ``parse_due``       - normalise heterogeneous due values to a date.
* ``classify``        - date-only overdue/approaching verdict + severity.
* ``build_register``  - filter + sort + count + cap, with pre-cap counts.

The module under test imports NOTHING from SQLAlchemy or ``app.database`` (only
the pydantic transport schemas), so this file runs on any Python without a
database - it does not use the ``session`` fixture or the embedded PostgreSQL
cluster.

Run:
    cd backend
    python -m pytest tests/unit/test_deadlines_logic.py -v
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.modules.deadlines.logic import (
    APPROACHING,
    ON_TIME,
    OVERDUE,
    SEVERITY_CRITICAL,
    SEVERITY_WARNING,
    build_register,
    classify,
    parse_due,
)
from app.modules.deadlines.schemas import DeadlineItem

# Terminal sets mirror the pinned per-source vocabularies.
CORR_TERMINAL = {"responded", "closed"}
NCR_TERMINAL = {"done", "cancelled"}


def _item(**over: Any) -> DeadlineItem:
    """A minimal DeadlineItem with sensible defaults, overridable."""
    base: dict[str, Any] = {
        "id": "punchlist:1",
        "module": "punchlist",
        "entity_type": "punch_item",
        "entity_id": "1",
        "project_id": "p1",
        "title": "t",
        "due_date": "2026-07-10",
        "status": "open",
        "classification": OVERDUE,
        "days_overdue": 1,
        "severity": SEVERITY_CRITICAL,
        "action_url": "/punchlist",
    }
    base.update(over)
    return DeadlineItem(**base)


# ── parse_due ───────────────────────────────────────────────────────────────


def test_parse_due_iso_date() -> None:
    assert parse_due("2026-07-10") == date(2026, 7, 10)


def test_parse_due_iso_datetime() -> None:
    assert parse_due("2026-07-10T09:00:00+00:00") == date(2026, 7, 10)


def test_parse_due_iso_datetime_trailing_z() -> None:
    assert parse_due("2026-07-10T09:00:00Z") == date(2026, 7, 10)


def test_parse_due_real_datetime() -> None:
    assert parse_due(datetime(2026, 7, 10, 9, 0, 0)) == date(2026, 7, 10)


def test_parse_due_real_date() -> None:
    assert parse_due(date(2026, 7, 10)) == date(2026, 7, 10)


def test_parse_due_garbage_returns_none() -> None:
    assert parse_due("") is None
    assert parse_due(None) is None
    assert parse_due("not-a-date") is None
    assert parse_due("   ") is None


# ── classify ────────────────────────────────────────────────────────────────


def test_classify_overdue() -> None:
    # due yesterday, still open
    cls, days, sev = classify(date(2026, 7, 9), "open", date(2026, 7, 10), set(), 3)
    assert cls == OVERDUE
    assert days == 1
    assert sev == SEVERITY_CRITICAL


def test_classify_due_today_not_overdue() -> None:
    cls, days, _sev = classify(date(2026, 7, 10), "open", date(2026, 7, 10), set(), 3)
    assert cls != OVERDUE
    assert cls == APPROACHING
    assert days == 0


def test_classify_approaching_window() -> None:
    cls, days, sev = classify(date(2026, 7, 12), "open", date(2026, 7, 10), set(), 3)
    assert cls == APPROACHING
    assert days == -2
    assert sev == SEVERITY_WARNING


def test_classify_beyond_window_on_time() -> None:
    cls, _days, _sev = classify(date(2026, 7, 20), "open", date(2026, 7, 10), set(), 3)
    assert cls == ON_TIME


def test_classify_terminal_status_on_time() -> None:
    # An overdue date but a terminal status must not surface.
    cls, days, _sev = classify(date(2026, 7, 1), "responded", date(2026, 7, 10), CORR_TERMINAL, 3)
    assert cls == ON_TIME
    assert days == 0


def test_classify_ncr_done_is_terminal() -> None:
    cls, _days, _sev = classify(date(2026, 7, 1), "done", date(2026, 7, 10), NCR_TERMINAL, 3)
    assert cls == ON_TIME


def test_classify_ncr_unknown_intermediate_still_overdue() -> None:
    # An unknown non-terminal state (e.g. 'in_progress') past due must surface
    # - the whole point of terminal-exclusion over open-state inclusion.
    cls, _days, _sev = classify(date(2026, 7, 1), "in_progress", date(2026, 7, 10), NCR_TERMINAL, 3)
    assert cls == OVERDUE


def test_classify_no_due_is_on_time() -> None:
    cls, days, _sev = classify(None, "open", date(2026, 7, 10), set(), 3)
    assert cls == ON_TIME
    assert days == 0


# ── build_register ──────────────────────────────────────────────────────────


def test_build_register_counts_are_pre_cap() -> None:
    items = [
        _item(id=f"punchlist:{i}", entity_id=str(i), classification=OVERDUE, days_overdue=i + 1) for i in range(5)
    ] + [_item(id=f"c:{i}", entity_id=str(i), classification=APPROACHING, days_overdue=-1) for i in range(3)]
    reg = build_register(items, status="all", limit=2)
    # Counts reflect the full set, not the 2-row cap.
    assert reg.overdue_count == 5
    assert reg.approaching_count == 3
    assert len(reg.items) == 2


def test_build_register_status_filter_overdue_only() -> None:
    items = [
        _item(id="o:1", classification=OVERDUE, days_overdue=2),
        _item(id="a:1", classification=APPROACHING, days_overdue=-1),
    ]
    reg = build_register(items, status=OVERDUE, limit=50)
    assert [it.id for it in reg.items] == ["o:1"]
    # Counts still reflect both classes.
    assert reg.overdue_count == 1
    assert reg.approaching_count == 1


def test_build_register_sort_overdue_first_then_most_overdue() -> None:
    items = [
        _item(id="a:1", classification=APPROACHING, days_overdue=-1),
        _item(id="o:small", classification=OVERDUE, days_overdue=1),
        _item(id="o:big", classification=OVERDUE, days_overdue=9),
    ]
    reg = build_register(items, status="all", limit=50)
    assert [it.id for it in reg.items] == ["o:big", "o:small", "a:1"]


def test_build_register_excludes_on_time() -> None:
    items = [
        _item(id="ok:1", classification=ON_TIME, days_overdue=-30),
        _item(id="o:1", classification=OVERDUE, days_overdue=1),
    ]
    reg = build_register(items, status="all", limit=50)
    assert [it.id for it in reg.items] == ["o:1"]
