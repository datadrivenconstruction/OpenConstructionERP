# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the BOQ Excel/CSV round-trip differ (GitHub #360).

These pin the PURE, DB-free decision layer that turns a set of
export-then-edited spreadsheet rows plus the target BOQ's current position
ids into a create / update / delete plan. The route layer only translates
this plan into service calls, so getting the diff right is what guarantees
a re-import updates in place instead of duplicating - and never mutates a
position outside the target BOQ.

Run::

    cd backend
    python -m pytest tests/unit/test_boq_excel_roundtrip.py -v
"""

from __future__ import annotations

import uuid

from app.modules.boq.roundtrip import (
    ID_COLUMN_ALIASES,
    ID_COLUMN_HEADER,
    RoundTripRow,
    diff_import_rows,
    normalise_id,
)


def _uuid() -> str:
    return str(uuid.uuid4())


def _row(idx: int, pid: str | None, **payload: object) -> RoundTripRow:
    """Build a RoundTripRow; extra kwargs land in the opaque payload."""
    return RoundTripRow(row_index=idx, position_id=pid, payload={"ordinal": str(idx), **payload})


# ── normalise_id ─────────────────────────────────────────────────────────────


def test_normalise_id_blank_and_none() -> None:
    assert normalise_id(None) is None
    assert normalise_id("") is None
    assert normalise_id("   ") is None


def test_normalise_id_strips_and_lowercases() -> None:
    raw = "  550E8400-E29B-41D4-A716-446655440000  "
    assert normalise_id(raw) == "550e8400-e29b-41d4-a716-446655440000"


def test_normalise_id_passes_non_uuid_through() -> None:
    # A non-empty but non-UUID value is returned (lowered) so the differ can
    # flag it - never silently dropped.
    assert normalise_id("Not-An-Id") == "not-an-id"


def test_id_header_constant_is_in_its_own_alias_set() -> None:
    # The exporter writes ID_COLUMN_HEADER; the importer must recognise that
    # exact spelling (case-folded) as the id column.
    assert ID_COLUMN_HEADER.lower() in ID_COLUMN_ALIASES


# ── Blank / new rows ─────────────────────────────────────────────────────────


def test_blank_id_is_a_create() -> None:
    plan = diff_import_rows([_row(2, None)], current_position_ids=[])
    assert len(plan.creates) == 1
    assert not plan.updates
    assert plan.creates[0].kind == "create"
    assert plan.creates[0].position_id is None


def test_empty_string_id_is_a_create() -> None:
    plan = diff_import_rows([_row(2, "   ")], current_position_ids=[_uuid()])
    assert len(plan.creates) == 1
    assert not plan.updates


# ── Known id -> update in place ──────────────────────────────────────────────


def test_known_id_updates_in_place() -> None:
    pid = _uuid()
    plan = diff_import_rows([_row(2, pid, description="edited")], current_position_ids=[pid])
    assert not plan.creates
    assert len(plan.updates) == 1
    action = plan.updates[0]
    assert action.kind == "update"
    assert action.position_id == pid
    # The opaque payload rides through untouched for the route to apply.
    assert action.row.payload["description"] == "edited"


def test_case_insensitive_id_match() -> None:
    # Stored id lower-case (as ``str(uuid)`` always is); sheet cell upper-cased
    # by a spreadsheet or a copy-paste. Still the same position.
    pid = _uuid()
    plan = diff_import_rows([_row(2, pid.upper())], current_position_ids=[pid])
    assert len(plan.updates) == 1
    assert plan.updates[0].position_id == pid


def test_reordered_rows_match_by_id_not_position() -> None:
    a, b, c = _uuid(), _uuid(), _uuid()
    # Sheet rows in a different order than the stored positions.
    rows = [_row(2, c), _row(3, a), _row(4, b)]
    plan = diff_import_rows(rows, current_position_ids=[a, b, c])
    assert len(plan.updates) == 3
    assert not plan.creates
    assert {u.position_id for u in plan.updates} == {a, b, c}


# ── Foreign / unknown id -> new row, never a cross-BOQ update ────────────────


def test_foreign_id_never_updates_and_is_flagged() -> None:
    ours = _uuid()
    foreign = _uuid()  # belongs to a different BOQ / project
    rows = [_row(2, ours, description="ours"), _row(3, foreign, description="theirs")]
    plan = diff_import_rows(rows, current_position_ids=[ours])

    # The foreign id is a CREATE, never an update - the safety guarantee.
    assert len(plan.updates) == 1
    assert plan.updates[0].position_id == ours
    assert foreign not in {u.position_id for u in plan.updates}
    assert len(plan.creates) == 1
    assert plan.creates[0].row.position_id == foreign
    # And it is surfaced so the user knows why it landed as a new row.
    assert len(plan.problems) == 1
    assert plan.problems[0]["issue"] == "unknown_id"
    assert plan.problems[0]["row"] == 3


def test_garbage_id_is_treated_as_new() -> None:
    plan = diff_import_rows([_row(2, "just-some-text")], current_position_ids=[_uuid()])
    assert len(plan.creates) == 1
    assert not plan.updates
    assert plan.problems[0]["issue"] == "unknown_id"


# ── Duplicate id in the sheet ────────────────────────────────────────────────


def test_duplicate_id_first_updates_rest_create() -> None:
    pid = _uuid()
    rows = [_row(2, pid, description="first"), _row(3, pid, description="second")]
    plan = diff_import_rows(rows, current_position_ids=[pid])

    assert len(plan.updates) == 1
    assert plan.updates[0].row.payload["description"] == "first"
    # The second occurrence is demoted to a create and flagged, so nothing is
    # silently overwritten twice.
    assert len(plan.creates) == 1
    assert plan.creates[0].row.payload["description"] == "second"
    assert any(p["issue"] == "duplicate_id" for p in plan.problems)


# ── Missing positions -> report always, delete opt-in ────────────────────────


def test_missing_reported_but_not_deleted_by_default() -> None:
    a, b, dropped = _uuid(), _uuid(), _uuid()
    rows = [_row(2, a), _row(3, b)]  # ``dropped`` absent from the sheet
    plan = diff_import_rows(rows, current_position_ids=[a, b, dropped])

    assert plan.would_delete == [dropped]  # always reported
    assert plan.deletes == []  # never deleted without opt-in


def test_delete_missing_opt_in_queues_deletes() -> None:
    a, dropped1, dropped2 = _uuid(), _uuid(), _uuid()
    rows = [_row(2, a)]
    plan = diff_import_rows(
        rows,
        current_position_ids=[a, dropped1, dropped2],
        delete_missing=True,
    )
    assert set(plan.deletes) == {dropped1, dropped2}
    assert set(plan.would_delete) == {dropped1, dropped2}
    assert len(plan.updates) == 1


def test_empty_sheet_with_delete_missing_removes_everything() -> None:
    ids = [_uuid(), _uuid(), _uuid()]
    plan = diff_import_rows([], current_position_ids=ids, delete_missing=True)
    assert set(plan.deletes) == set(ids)
    assert not plan.updates
    assert not plan.creates


# ── Realistic export -> edit -> re-import ─────────────────────────────────────


def test_full_roundtrip_edit_add_drop() -> None:
    """The headline scenario: export three positions, edit two, add one new
    row, drop one - then re-import."""
    p1, p2, p3 = _uuid(), _uuid(), _uuid()
    rows = [
        _row(2, p1, description="edited one"),  # update
        _row(3, p2, description="edited two"),  # update
        _row(4, None, description="brand new"),  # create
        # p3 omitted from the sheet -> would_delete
    ]

    # Default: dropped position is only reported, never removed.
    plan = diff_import_rows(rows, current_position_ids=[p1, p2, p3])
    assert plan.counts == {
        "updated": 2,
        "created": 1,
        "deleted": 0,
        "would_delete": 1,
        "problems": 0,
    }
    assert plan.would_delete == [p3]

    # Opt-in: the same upload now also deletes the dropped position.
    plan_del = diff_import_rows(rows, current_position_ids=[p1, p2, p3], delete_missing=True)
    assert plan_del.counts["deleted"] == 1
    assert plan_del.deletes == [p3]


# ── Invariants ───────────────────────────────────────────────────────────────


def test_every_row_is_covered_exactly_once() -> None:
    known = _uuid()
    rows = [
        _row(2, known),  # update
        _row(3, None),  # create (blank)
        _row(4, _uuid()),  # create (unknown)
        _row(5, known),  # create (duplicate)
    ]
    plan = diff_import_rows(rows, current_position_ids=[known])
    assert len(plan.updates) + len(plan.creates) == len(rows)


def test_counts_property_matches_lists() -> None:
    a, b = _uuid(), _uuid()
    plan = diff_import_rows(
        [_row(2, a), _row(3, None)],
        current_position_ids=[a, b],
        delete_missing=True,
    )
    c = plan.counts
    assert c["updated"] == len(plan.updates)
    assert c["created"] == len(plan.creates)
    assert c["deleted"] == len(plan.deletes)
    assert c["would_delete"] == len(plan.would_delete)
    assert c["problems"] == len(plan.problems)


def test_current_ids_are_normalised_before_matching() -> None:
    # A current id fed in with surrounding whitespace / mixed case still
    # matches a clean sheet id (defensive: callers pass ``str(uuid)`` but the
    # differ must not depend on that).
    pid = _uuid()
    plan = diff_import_rows([_row(2, pid)], current_position_ids=[f"  {pid.upper()}  "])
    assert len(plan.updates) == 1
    assert plan.updates[0].position_id == pid
