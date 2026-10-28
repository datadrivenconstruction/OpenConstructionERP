# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure change cycle-time engine (runs on py3.11)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.change_intelligence.cycle_time import (
    KIND_CHANGE_ORDER,
    KIND_MOC_ENTRY,
    KIND_VARIATION_NOTICE,
    KIND_VARIATION_ORDER,
    KIND_VARIATION_REQUEST,
    UNASSIGNED,
    ChangeItem,
    build_board,
    is_open_status,
    is_overdue,
    parse_due,
)

NOW = datetime(2026, 6, 24, 12, 0, 0, tzinfo=UTC)


def _item(
    *,
    id: str = "1",
    kind: str = "change_order",
    code: str = "CO-1",
    title: str = "Item",
    status: str = "open",
    is_open: bool = True,
    ball_in_court: str | None = "alice",
    response_due_date: str | None = None,
    opened_days_ago: float = 0.0,
    last_activity_days_ago: float | None = None,
) -> ChangeItem:
    return ChangeItem(
        id=id,
        kind=kind,
        code=code,
        title=title,
        status=status,
        is_open=is_open,
        ball_in_court=ball_in_court,
        response_due_date=response_due_date,
        opened_at=NOW - timedelta(days=opened_days_ago),
        last_activity_at=(None if last_activity_days_ago is None else NOW - timedelta(days=last_activity_days_ago)),
    )


# --- parse_due -------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-07-01", datetime(2026, 7, 1, tzinfo=UTC)),
        ("2026-07-01T09:00:00+00:00", datetime(2026, 7, 1, 9, tzinfo=UTC)),
        ("2026-07-01T09:00:00Z", datetime(2026, 7, 1, 9, tzinfo=UTC)),
        ("2026-07-01 09:00:00", datetime(2026, 7, 1, 9, tzinfo=UTC)),  # naive -> UTC
    ],
)
def test_parse_due_accepts_iso_forms(value: str, expected: datetime) -> None:
    assert parse_due(value) == expected


@pytest.mark.parametrize("value", [None, "", "   ", "not-a-date", "2026-13-99"])
def test_parse_due_rejects_unusable(value: str | None) -> None:
    assert parse_due(value) is None


def test_parse_due_datetime_with_offset_normalized_to_utc() -> None:
    assert parse_due("2026-07-01T11:00:00+02:00") == datetime(2026, 7, 1, 9, tzinfo=UTC)


# --- is_overdue ------------------------------------------------------------


def test_is_overdue_true_when_past() -> None:
    assert is_overdue("2026-06-01", NOW) is True


def test_is_overdue_false_when_future() -> None:
    assert is_overdue("2026-12-01", NOW) is False


def test_is_overdue_false_when_no_date() -> None:
    assert is_overdue(None, NOW) is False
    assert is_overdue("garbage", NOW) is False


# --- is_open_status --------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "status"),
    [
        (KIND_CHANGE_ORDER, "draft"),
        (KIND_CHANGE_ORDER, "submitted"),
        (KIND_CHANGE_ORDER, "approved"),  # approved-not-yet-executed is still open
        (KIND_VARIATION_NOTICE, "issued"),
        (KIND_VARIATION_NOTICE, "acknowledged"),
        (KIND_VARIATION_REQUEST, "draft"),
        (KIND_VARIATION_REQUEST, "submitted"),
        (KIND_VARIATION_ORDER, "issued"),
        (KIND_VARIATION_ORDER, "in_progress"),
        (KIND_MOC_ENTRY, "proposed"),
        (KIND_MOC_ENTRY, "reviewed"),
        (KIND_MOC_ENTRY, "accepted"),
    ],
)
def test_open_statuses(kind: str, status: str) -> None:
    assert is_open_status(kind, status) is True


@pytest.mark.parametrize(
    ("kind", "status"),
    [
        (KIND_CHANGE_ORDER, "executed"),
        (KIND_CHANGE_ORDER, "rejected"),
        (KIND_VARIATION_NOTICE, "responded"),
        (KIND_VARIATION_REQUEST, "approved"),
        (KIND_VARIATION_REQUEST, "converted_to_vo"),
        (KIND_VARIATION_ORDER, "completed"),
        (KIND_VARIATION_ORDER, "voided"),
        (KIND_MOC_ENTRY, "implemented"),
        (KIND_MOC_ENTRY, "declined"),
    ],
)
def test_closed_statuses(kind: str, status: str) -> None:
    assert is_open_status(kind, status) is False


def test_is_open_status_is_case_insensitive() -> None:
    assert is_open_status(KIND_CHANGE_ORDER, "EXECUTED") is False
    assert is_open_status(KIND_CHANGE_ORDER, "  Executed  ") is False


def test_is_open_status_defaults_open_for_unknowns() -> None:
    assert is_open_status(KIND_CHANGE_ORDER, None) is True
    assert is_open_status(KIND_CHANGE_ORDER, "some_new_state") is True
    assert is_open_status("unknown_kind", "whatever") is True


# --- build_board -----------------------------------------------------------


def test_empty_board() -> None:
    board = build_board([], NOW)
    assert board.total_open == 0
    assert board.total_overdue == 0
    assert board.unassigned_open == 0
    assert board.parties == []
    assert board.items == []
    assert board.as_of == NOW


def test_closed_items_excluded() -> None:
    board = build_board([_item(is_open=False)], NOW)
    assert board.total_open == 0
    assert board.items == []


def test_single_open_item_makes_one_party() -> None:
    board = build_board([_item(ball_in_court="alice", opened_days_ago=3)], NOW)
    assert board.total_open == 1
    assert len(board.parties) == 1
    party = board.parties[0]
    assert party.party == "alice"
    assert party.open_count == 1
    assert party.oldest_age_days == pytest.approx(3.0)
    assert party.total_age_days == pytest.approx(3.0)
    assert party.avg_age_days == pytest.approx(3.0)


def test_unassigned_bucket() -> None:
    board = build_board([_item(ball_in_court=None)], NOW)
    assert board.unassigned_open == 1
    assert board.parties[0].party == UNASSIGNED


def test_overdue_flagged_and_counted() -> None:
    board = build_board(
        [_item(id="late", response_due_date="2026-06-01"), _item(id="ok", response_due_date="2026-12-01")],
        NOW,
    )
    assert board.total_overdue == 1
    overdue_item = next(r for r in board.items if r.id == "late")
    assert overdue_item.overdue is True
    assert overdue_item.days_to_due is not None and overdue_item.days_to_due < 0
    ok_item = next(r for r in board.items if r.id == "ok")
    assert ok_item.overdue is False
    assert ok_item.days_to_due is not None and ok_item.days_to_due > 0


def test_parties_sorted_by_open_count_desc() -> None:
    items = [
        _item(id="a1", ball_in_court="alice"),
        _item(id="b1", ball_in_court="bob"),
        _item(id="b2", ball_in_court="bob"),
    ]
    board = build_board(items, NOW)
    assert [p.party for p in board.parties] == ["bob", "alice"]
    assert board.parties[0].open_count == 2


def test_party_tiebreak_overdue_then_name() -> None:
    # Two parties, one open each; the one with an overdue item ranks first.
    items = [
        _item(id="a1", ball_in_court="alice", response_due_date="2026-12-01"),
        _item(id="b1", ball_in_court="bob", response_due_date="2026-06-01"),
    ]
    board = build_board(items, NOW)
    assert [p.party for p in board.parties] == ["bob", "alice"]


def test_items_sorted_overdue_first_then_oldest() -> None:
    items = [
        _item(id="young_ok", opened_days_ago=1, response_due_date="2026-12-01"),
        _item(id="old_ok", opened_days_ago=10, response_due_date="2026-12-01"),
        _item(id="overdue_young", opened_days_ago=2, response_due_date="2026-06-01"),
    ]
    board = build_board(items, NOW)
    assert [r.id for r in board.items] == ["overdue_young", "old_ok", "young_ok"]


def test_oldest_and_total_age_per_party() -> None:
    items = [
        _item(id="a1", ball_in_court="alice", opened_days_ago=2),
        _item(id="a2", ball_in_court="alice", opened_days_ago=5),
    ]
    board = build_board(items, NOW)
    party = board.parties[0]
    assert party.oldest_age_days == pytest.approx(5.0)
    assert party.total_age_days == pytest.approx(7.0)
    assert party.avg_age_days == pytest.approx(3.5)


def test_stale_days_none_when_never_updated() -> None:
    board = build_board([_item(last_activity_days_ago=None)], NOW)
    assert board.items[0].stale_days is None


def test_stale_days_computed_when_updated() -> None:
    board = build_board([_item(opened_days_ago=10, last_activity_days_ago=2)], NOW)
    assert board.items[0].stale_days == pytest.approx(2.0)
    assert board.items[0].age_days == pytest.approx(10.0)


def test_naive_opened_at_treated_as_utc() -> None:
    naive = ChangeItem(
        id="n",
        kind="change_order",
        code="CO-N",
        title="Naive",
        status="open",
        is_open=True,
        ball_in_court="alice",
        response_due_date=None,
        opened_at=datetime(2026, 6, 22, 12, 0, 0),  # no tzinfo
        last_activity_at=None,
    )
    board = build_board([naive], NOW)
    assert board.items[0].age_days == pytest.approx(2.0)
