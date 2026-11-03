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


# ── Review step: field changes, stale rows, formula ids ──────────────────────

from decimal import Decimal  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from app.modules.boq.roundtrip import (  # noqa: E402
    ROW_VERSION_COLUMN_ALIASES,
    ApplyChoices,
    conflict,
    field_changes,
    is_formula_id,
    parse_row_version,
)


def _stored(**kw: object) -> SimpleNamespace:
    base = {
        "description": "Concrete C30/37",
        "unit": "m3",
        "ordinal": "01.01",
        "quantity": Decimal("12.5000"),
        "unit_rate": Decimal("85.2500"),
        "classification": {"din276": "331"},
        "version": 2,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _payload(**kw: object) -> dict[str, object]:
    base = {
        "description": "Concrete C30/37",
        "unit": "m3",
        "ordinal": "01.01",
        "quantity": 12.5,
        "unit_rate": 85.25,
        "classification": {"code": "331"},
    }
    base.update(kw)
    return base


def _code(cls: dict) -> str:
    return str(cls.get("din276", ""))


def test_unedited_row_has_no_changes() -> None:
    assert field_changes(_stored(), _payload(), code_of=_code) == []


def test_changes_are_reported_per_field_with_old_and_new() -> None:
    changes = field_changes(_stored(), _payload(quantity=20.0, unit_rate=90), code_of=_code)
    assert [(c.field, c.old, c.new) for c in changes] == [
        ("quantity", "12.5", "20"),
        ("unit_rate", "85.25", "90"),
    ]


def test_trim_nfc_and_case_do_not_count_as_edits() -> None:
    stored = _stored(description="Café floor", unit="M3")
    payload = _payload(description="  Café floor  ", unit="m3")
    assert field_changes(stored, payload, code_of=_code) == []


def test_decimal_precision_beyond_storage_is_not_an_edit() -> None:
    assert field_changes(_stored(), _payload(quantity=12.50004), code_of=_code) == []
    assert [c.field for c in field_changes(_stored(), _payload(quantity=12.5001), code_of=_code)] == ["quantity"]


def test_blank_cells_never_clear_stored_values() -> None:
    changes = field_changes(_stored(), _payload(unit="", ordinal="", classification={}), code_of=_code)
    assert changes == []


def test_classification_change_uses_the_displayed_code() -> None:
    changes = field_changes(_stored(), _payload(classification={"code": "334"}), code_of=_code)
    assert [(c.field, c.old, c.new) for c in changes] == [("classification", "331", "334")]


def test_conflict_needs_a_stamp_and_a_difference() -> None:
    assert conflict(3, 2) is True
    assert conflict(3, 3) is False
    assert conflict(3, None) is False
    assert conflict(None, 3) is False


def test_parse_row_version() -> None:
    assert parse_row_version("4") == 4
    assert parse_row_version(4.0) == 4
    assert parse_row_version("") is None
    assert parse_row_version("abc") is None
    assert parse_row_version(-1) is None
    assert parse_row_version(True) is None
    assert "row version" in ROW_VERSION_COLUMN_ALIASES


def test_stale_update_is_flagged_and_listed() -> None:
    pid = _uuid()
    row = RoundTripRow(row_index=2, position_id=pid, payload=_payload(quantity=99.0), row_version=1)
    plan = diff_import_rows(
        [row],
        [pid],
        stored_versions={pid: 3},
        stored={pid: _stored()},
        code_of=_code,
    )
    assert plan.stale_ids == {pid}
    assert [p["issue"] for p in plan.problems] == ["stale_row"]
    assert plan.problems[0]["severity"] == "error"
    assert len(plan.updates) == 1


def test_stale_row_with_nothing_to_lose_is_not_a_conflict() -> None:
    pid = _uuid()
    row = RoundTripRow(row_index=2, position_id=pid, payload=_payload(), row_version=1)
    plan = diff_import_rows([row], [pid], stored_versions={pid: 3}, stored={pid: _stored()}, code_of=_code)
    assert plan.stale_ids == set()
    assert plan.problems == []


def test_sheet_without_row_version_has_no_conflict_check() -> None:
    pid = _uuid()
    row = RoundTripRow(row_index=2, position_id=pid, payload=_payload(quantity=99.0))
    plan = diff_import_rows([row], [pid], stored_versions={pid: 7}, stored={pid: _stored()}, code_of=_code)
    assert plan.stale_ids == set()
    assert plan.problems == []


def test_unchanged_agrees_with_apply_update_builder() -> None:
    from app.modules.boq.router import _prepared_row_to_update

    stored = _stored()
    for payload in (_payload(), _payload(description=" Concrete C30/37 "), _payload(quantity=12.50001)):
        no_changes = field_changes(stored, payload, code_of=_code) == []
        assert no_changes == (_prepared_row_to_update(payload, stored) is None)
    edited = _payload(quantity=20.0, classification={"code": "334"})
    update = _prepared_row_to_update(edited, stored, version=2)
    assert update is not None
    assert update.quantity == 20.0
    assert update.version == 2
    assert update.classification == {"din276": "334"}


def test_foreign_id_with_a_version_never_updates() -> None:
    mine, foreign = _uuid(), _uuid()
    row = RoundTripRow(row_index=2, position_id=foreign, payload=_payload(), row_version=1)
    plan = diff_import_rows([row], [mine], stored_versions={mine: 1}, stored={mine: _stored()})
    assert plan.updates == []
    assert len(plan.creates) == 1
    assert [p["issue"] for p in plan.problems] == ["unknown_id"]


def test_duplicate_id_second_row_is_a_create() -> None:
    pid = _uuid()
    rows = [
        RoundTripRow(row_index=2, position_id=pid, payload=_payload(), row_version=3),
        RoundTripRow(row_index=3, position_id=pid, payload=_payload(), row_version=3),
    ]
    plan = diff_import_rows(rows, [pid], stored_versions={pid: 3})
    assert len(plan.updates) == 1
    assert len(plan.creates) == 1
    assert [p["issue"] for p in plan.problems] == ["duplicate_id"]


def test_formula_ids_are_detected() -> None:
    for bad in ("=1+1", "+cmd", "-2", "@SUM(A1)", "\t=x", " =x"):
        assert is_formula_id(bad), bad
    for ok in (None, "", "550e8400-e29b-41d4-a716-446655440000", 5):
        assert not is_formula_id(ok), ok


def test_apply_choices_json_round_trip() -> None:
    choices = ApplyChoices(accept=frozenset({"a"}), skip=frozenset({"b"}), delete=frozenset({"c"}))
    assert ApplyChoices.from_json(choices.to_json()) == choices
    assert ApplyChoices.from_json(None) is None


def test_decimal_comma_sheet_agrees_with_stored_values() -> None:
    from app.modules.boq import router as boq_router

    pid = "550e8400-e29b-41d4-a716-446655440000"
    csv_bytes = (
        "Pos.;Description;Unit;Quantity;Unit Rate;Position ID;Row Version\n"
        f"01.01;Beton C30;m3;1.234,50;85,25;{pid};3\n"
        "01.02;Stahl;kg;10,5;2,10;=cmd|x;1\n"
    ).encode()
    rows = boq_router._parse_rows_from_csv(csv_bytes)
    prepared, errors, _warnings, _skipped = boq_router._prepare_rows(rows, {}, "x.csv")
    assert prepared[0]["quantity"] == 1234.5
    assert prepared[0]["unit_rate"] == 85.25
    assert prepared[0]["row_version"] == 3
    assert len(prepared) == 1
    assert "formula_in_id" in errors[0]["error"]
    stored = _stored(description="Beton C30", quantity=Decimal("1234.5"), unit_rate=Decimal("85.25"))
    assert field_changes(stored, prepared[0], code_of=_code) == []


def test_roundtrip_rules_word_each_finding() -> None:
    import asyncio

    from app.modules.boq.validators import evaluate_roundtrip

    issues = [
        {"kind": "formula_in_id", "row": 3},
        {"kind": "unknown_id", "row": 4, "position_id": "x"},
        {"kind": "duplicate_id", "row": 5, "position_id": "y"},
        {"kind": "stale_row", "row": 6, "position_id": "z", "ordinal": "01.02"},
        {"kind": "locked_boq"},
    ]
    results = asyncio.run(evaluate_roundtrip(issues, "en"))
    assert {r.rule_id for r in results} == {
        "boq.roundtrip.formula_in_id",
        "boq.roundtrip.unknown_id",
        "boq.roundtrip.duplicate_id",
        "boq.roundtrip.stale_row",
        "boq.roundtrip.locked_boq",
    }
    stale = next(r for r in results if r.rule_id == "boq.roundtrip.stale_row")
    assert "01.02" in stale.message
    assert all("boq_roundtrip" not in r.message for r in results)
