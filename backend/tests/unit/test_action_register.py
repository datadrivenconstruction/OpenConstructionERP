# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure cross-source commitment / action register engine.

Stdlib + pytest only, so it runs on the local Python 3.11 runner exactly like
the cycle-time and coordination engine tests.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.modules.change_intelligence.action_register import (
    SOURCE_CHANGE_ORDER,
    SOURCE_MEETING_ACTION,
    SOURCE_RFI,
    SOURCE_RISK_ACTION,
    SOURCE_SUBMITTAL,
    UNASSIGNED,
    RegisterItem,
    build_register,
    is_open_commitment,
)

NOW = datetime(2026, 6, 30, tzinfo=UTC)


def _item(
    ref_id: str,
    *,
    source: str = SOURCE_RFI,
    owner: str = "alice",
    status: str | None = "open",
    due_date: str | None = None,
    opened_at: datetime | None = None,
    code: str = "",
    title: str = "",
) -> RegisterItem:
    return RegisterItem(
        source=source,
        ref_id=ref_id,
        code=code or ref_id,
        title=title or ref_id,
        owner=owner,
        status=status,
        due_date=due_date,
        opened_at=opened_at,
    )


# --------------------------------------------------------------------------
# is_open_commitment: per-source done vocabulary, default-to-open
# --------------------------------------------------------------------------


def test_none_status_is_open() -> None:
    assert is_open_commitment(SOURCE_RFI, None) is True


def test_unknown_status_defaults_open() -> None:
    assert is_open_commitment(SOURCE_RFI, "in_flight") is True


def test_unknown_source_defaults_open() -> None:
    assert is_open_commitment("mystery", "closed") is True


@pytest.mark.parametrize(
    ("source", "status"),
    [
        (SOURCE_MEETING_ACTION, "completed"),
        (SOURCE_MEETING_ACTION, "cancelled"),
        (SOURCE_RISK_ACTION, "done"),
        (SOURCE_RISK_ACTION, "resolved"),
        (SOURCE_CHANGE_ORDER, "executed"),
        (SOURCE_CHANGE_ORDER, "rejected"),
        (SOURCE_RFI, "closed"),
        (SOURCE_SUBMITTAL, "approved"),
        (SOURCE_SUBMITTAL, "rejected"),
    ],
)
def test_done_statuses_are_closed(source: str, status: str) -> None:
    assert is_open_commitment(source, status) is False


def test_status_matching_is_case_insensitive() -> None:
    assert is_open_commitment(SOURCE_RFI, "CLOSED") is False


def test_submittal_revise_and_resubmit_stays_open() -> None:
    # A resubmission bounces back to the submitter, so it is still owed.
    assert is_open_commitment(SOURCE_SUBMITTAL, "revise_and_resubmit") is True


# --------------------------------------------------------------------------
# Empty + closed filtering
# --------------------------------------------------------------------------


def test_empty_register() -> None:
    reg = build_register([], NOW)
    assert reg.total_open == 0
    assert reg.overdue_count == 0
    assert reg.by_owner == []
    assert reg.by_source == {}
    assert reg.items == []
    assert reg.generated_at == NOW.isoformat()


def test_closed_items_excluded() -> None:
    reg = build_register(
        [
            _item("A", status="open"),
            _item("B", status="closed"),
            _item("C", source=SOURCE_SUBMITTAL, status="approved"),
        ],
        NOW,
    )
    assert reg.total_open == 1
    assert [c.ref_id for c in reg.items] == ["A"]


# --------------------------------------------------------------------------
# Overdue, days_overdue, age
# --------------------------------------------------------------------------


def test_overdue_and_age_measured() -> None:
    reg = build_register(
        [_item("A", due_date="2026-06-20", opened_at=datetime(2026, 6, 1, tzinfo=UTC))],
        NOW,
    )
    row = reg.items[0]
    assert row.overdue is True
    assert row.days_overdue == 10.0
    assert row.age_days == 29.0
    assert reg.overdue_count == 1


def test_future_due_not_overdue_and_no_days() -> None:
    reg = build_register([_item("A", due_date="2026-07-15")], NOW)
    row = reg.items[0]
    assert row.overdue is False
    assert row.days_overdue == 0.0
    assert reg.overdue_count == 0


def test_no_due_date_and_no_opened_at() -> None:
    reg = build_register([_item("A", due_date=None, opened_at=None)], NOW)
    row = reg.items[0]
    assert row.overdue is False
    assert row.age_days is None


def test_unparseable_due_date_is_not_overdue() -> None:
    reg = build_register([_item("A", due_date="whenever")], NOW)
    assert reg.items[0].overdue is False


def test_naive_opened_at_is_treated_as_utc() -> None:
    reg = build_register([_item("A", opened_at=datetime(2026, 6, 20))], NOW)
    assert reg.items[0].age_days == 10.0


# --------------------------------------------------------------------------
# Ordering: overdue first (most overdue first), then soonest due, then no date
# --------------------------------------------------------------------------


def test_overdue_first_then_soonest_due_then_no_date() -> None:
    reg = build_register(
        [
            _item("NODATE", owner="z", due_date=None),
            _item("SOON", owner="y", due_date="2026-07-02"),
            _item("OVERDUE_A_BIT", owner="x", due_date="2026-06-28"),
            _item("OVERDUE_A_LOT", owner="w", due_date="2026-06-01"),
            _item("LATER", owner="v", due_date="2026-09-01"),
        ],
        NOW,
    )
    assert [c.ref_id for c in reg.items] == [
        "OVERDUE_A_LOT",
        "OVERDUE_A_BIT",
        "SOON",
        "LATER",
        "NODATE",
    ]


# --------------------------------------------------------------------------
# Owner bucketing + per-owner load ranking + per-source counts
# --------------------------------------------------------------------------


def test_blank_owner_buckets_unassigned() -> None:
    reg = build_register([_item("A", owner="")], NOW)
    assert reg.items[0].owner == UNASSIGNED
    assert reg.by_owner[0].owner == UNASSIGNED


def test_owner_load_ranking() -> None:
    reg = build_register(
        [
            _item("A1", owner="alice", due_date="2026-06-01"),  # overdue
            _item("A2", owner="alice", due_date="2026-07-10"),
            _item("A3", owner="alice", due_date=None),
            _item("B1", owner="bob", due_date="2026-06-02"),  # overdue
            _item("B2", owner="bob", due_date="2026-07-11"),
            _item("C1", owner="carol", due_date=None),
        ],
        NOW,
    )
    ranked = [(o.owner, o.open_count, o.overdue_count) for o in reg.by_owner]
    # Most open first (alice 3), then bob 2, then carol 1.
    assert ranked == [("alice", 3, 1), ("bob", 2, 1), ("carol", 1, 0)]


def test_by_source_counts() -> None:
    reg = build_register(
        [
            _item("M", source=SOURCE_MEETING_ACTION),
            _item("R1", source=SOURCE_RISK_ACTION),
            _item("R2", source=SOURCE_RISK_ACTION),
            _item("CO", source=SOURCE_CHANGE_ORDER),
        ],
        NOW,
    )
    assert reg.by_source == {
        SOURCE_CHANGE_ORDER: 1,
        SOURCE_MEETING_ACTION: 1,
        SOURCE_RISK_ACTION: 2,
    }


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
