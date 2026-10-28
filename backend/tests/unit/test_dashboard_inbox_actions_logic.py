# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure tests for the inbox item-state logic (no database).

Covers the two things the action endpoints stand on: that an item id can be
parsed back into the source and row it names, and that a recorded state changes
what the inbox returns. The second matters most - if ``build_inbox`` ignored the
states, dismissing would write a row, return 200 and change nothing the user
can see, which is the worst possible outcome for a button labelled "dismiss".
"""

from __future__ import annotations

import uuid

from app.modules.dashboard.inbox_logic import (
    KIND_ALERT,
    KIND_APPROVAL,
    STATE_ACKNOWLEDGED,
    STATE_DISMISSED,
    apply_item_states,
    build_inbox,
    parse_item_id,
    source_is_approval,
)


def _item(item_id: str, kind: str = KIND_ALERT, created: str = "2026-07-01T00:00:00+00:00") -> dict:
    return {
        "id": item_id,
        "kind": kind,
        "source": item_id.split(":")[0],
        "title": item_id,
        "severity": "info",
        "created_at": created,
        "project_id": None,
    }


# ── parse_item_id ────────────────────────────────────────────────────────────


def test_parse_accepts_every_source_the_aggregator_stamps() -> None:
    row = str(uuid.uuid4())
    for source in ("file_approval", "change_order_approval", "notification"):
        assert parse_item_id(f"{source}:{row}") == (source, row)


def test_parse_rejects_an_unknown_source() -> None:
    assert parse_item_id(f"rfi:{uuid.uuid4()}") is None


def test_parse_rejects_a_suffix_that_is_not_a_uuid() -> None:
    assert parse_item_id("notification:not-a-uuid") is None
    assert parse_item_id("notification:") is None


def test_parse_rejects_an_id_with_no_separator() -> None:
    assert parse_item_id(str(uuid.uuid4())) is None
    assert parse_item_id("") is None


def test_only_the_two_approval_sources_count_as_approvals() -> None:
    assert source_is_approval("file_approval")
    assert source_is_approval("change_order_approval")
    assert not source_is_approval("notification")


# ── apply_item_states ────────────────────────────────────────────────────────


def test_without_states_every_item_survives_and_is_unacknowledged() -> None:
    items = [_item("notification:a"), _item("notification:b")]
    out = apply_item_states(items, None)
    assert [it["id"] for it in out] == ["notification:a", "notification:b"]
    assert all(it["acknowledged"] is False for it in out)


def test_a_dismissed_item_is_removed_and_an_acknowledged_one_is_flagged() -> None:
    items = [_item("notification:a"), _item("notification:b"), _item("notification:c")]
    out = apply_item_states(
        items,
        {"notification:a": STATE_DISMISSED, "notification:b": STATE_ACKNOWLEDGED},
    )
    assert [it["id"] for it in out] == ["notification:b", "notification:c"]
    assert out[0]["acknowledged"] is True
    assert out[1]["acknowledged"] is False


def test_an_unknown_state_value_leaves_the_item_alone() -> None:
    out = apply_item_states([_item("notification:a")], {"notification:a": "snoozed"})
    assert [it["id"] for it in out] == ["notification:a"]
    assert out[0]["acknowledged"] is False


def test_apply_does_not_mutate_the_items_it_was_given() -> None:
    items = [_item("notification:a")]
    apply_item_states(items, {"notification:a": STATE_ACKNOWLEDGED})
    assert "acknowledged" not in items[0]


# ── build_inbox with states ──────────────────────────────────────────────────


def test_dismissing_removes_the_row_from_the_counts_as_well_as_the_list() -> None:
    approvals = [_item("file_approval:x", kind=KIND_APPROVAL)]
    alerts = [_item("notification:a"), _item("notification:b")]

    before = build_inbox(approvals, alerts, accessible_project_ids=None, limit=50)
    assert (before["total"], before["approvals_count"], before["alerts_count"]) == (3, 1, 2)

    after = build_inbox(
        approvals,
        alerts,
        accessible_project_ids=None,
        limit=50,
        item_states={"notification:a": STATE_DISMISSED},
    )
    assert (after["total"], after["approvals_count"], after["alerts_count"]) == (2, 1, 1)
    assert [it["id"] for it in after["items"]] == ["notification:b", "file_approval:x"]


def test_acknowledging_keeps_the_row_and_its_count() -> None:
    alerts = [_item("notification:a")]
    payload = build_inbox(
        [],
        alerts,
        accessible_project_ids=None,
        limit=50,
        item_states={"notification:a": STATE_ACKNOWLEDGED},
    )
    assert payload["total"] == 1
    assert payload["alerts_count"] == 1
    assert payload["items"][0]["acknowledged"] is True


def test_a_state_for_an_item_the_caller_cannot_see_changes_nothing() -> None:
    """A stale state row must not silently drop somebody else's item."""
    alerts = [_item("notification:a")]
    payload = build_inbox(
        [],
        alerts,
        accessible_project_ids=None,
        limit=50,
        item_states={"notification:zzz": STATE_DISMISSED},
    )
    assert [it["id"] for it in payload["items"]] == ["notification:a"]
