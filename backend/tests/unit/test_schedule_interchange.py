# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure unit tests for the schedule interchange model (T1.1).

Stdlib + the pure module only, so they run on the local Python 3.11 runner
without the ORM / DB. Focus: export captures every column, the parse -> emit
round-trip is lossless (including forward-compatible unknown keys), the envelope
gate rejects malformed / wrong-version documents, and canonicalisation gives a
stable order-independent normal form.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.schedule.schedule_interchange import (
    FORMAT,
    FORMAT_VERSION,
    InterchangeError,
    build_export_document,
    canonicalize,
    parse_document,
    validate_document,
)


def _activity_row(**over: object) -> SimpleNamespace:
    base = {
        "id": uuid.uuid4(),
        "activity_code": "ACT-001",
        "name": "Excavate",
        "description": "dig",
        "wbs_code": "1.1",
        "parent_id": None,
        "start_date": "2026-01-01",
        "end_date": "2026-01-05",
        "duration_days": 4,
        "progress_pct": "50",
        "status": "in_progress",
        "activity_type": "task",
        "early_start": "2026-01-01",
        "early_finish": "2026-01-05",
        "late_start": "2026-01-02",
        "late_finish": "2026-01-06",
        "total_float": 1,
        "free_float": 0,
        "is_critical": True,
        "constraint_type": "start_no_earlier",
        "constraint_date": "2026-01-01",
        "color": "#abcdef",
        "sort_order": 3,
        "resources": [{"name": "crew", "count": 2}],
        "boq_position_ids": ["b1", "b2"],
        "bim_element_ids": ["e1"],
        "cost_planned": Decimal("1234.5600"),
        "cost_actual": None,
        "percent_complete_type": "units",
        "remaining_duration": 2,
        "budgeted_units": Decimal("100.0000"),
        "installed_units": Decimal("50.0000"),
        "calendar_id": uuid.uuid4(),
        "suspended_at": None,
        "resumed_at": None,
        "suspend_reason": None,
        "metadata_": {"k": "v"},
    }
    base.update(over)
    return SimpleNamespace(**base)


def test_build_export_document_captures_columns_and_serialises_money() -> None:
    sched_id = uuid.uuid4()
    proj_id = uuid.uuid4()
    schedule = SimpleNamespace(
        id=sched_id,
        project_id=proj_id,
        name="Master",
        schedule_type="master",
        description="d",
        start_date="2026-01-01",
        end_date="2026-06-01",
        status="active",
        data_date="2026-02-01",
        metadata_={"region": "EU"},
    )
    parent = _activity_row(wbs_code="1", name="Parent")
    child = _activity_row(parent_id=parent.id, wbs_code="1.1", name="Child")
    rel = SimpleNamespace(
        predecessor_id=parent.id,
        successor_id=child.id,
        relationship_type="FS",
        lag_days=2,
        metadata_={},
    )

    doc = build_export_document(schedule, [parent, child], [rel])

    assert doc["format"] == FORMAT
    assert doc["format_version"] == FORMAT_VERSION
    assert doc["schedule"]["original_id"] == str(sched_id)
    assert doc["schedule"]["project_id"] == str(proj_id)
    assert doc["schedule"]["data_date"] == "2026-02-01"

    child_doc = doc["activities"][1]
    assert child_doc["ref"] == str(child.id)
    assert child_doc["parent_ref"] == str(parent.id)
    # Money / quantity columns are strings, never floats.
    assert child_doc["cost_planned"] == "1234.5600"
    assert child_doc["budgeted_units"] == "100.0000"
    assert child_doc["installed_units"] == "50.0000"
    assert child_doc["cost_actual"] is None
    assert child_doc["is_critical"] is True
    assert child_doc["resources"] == [{"name": "crew", "count": 2}]
    assert child_doc["calendar_id"] == str(child.calendar_id)
    # The derived dependencies JSON is intentionally absent (relationships own it).
    assert "dependencies" not in child_doc

    assert doc["relationships"][0] == {
        "predecessor_ref": str(parent.id),
        "successor_ref": str(child.id),
        "relationship_type": "FS",
        "lag_days": 2,
        "metadata": {},
    }


def _raw_doc(**over: object) -> dict[str, object]:
    raw = {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "schedule": {"name": "S", "schedule_type": "master", "metadata": {}},
        "activities": [
            {"ref": "A1", "name": "a", "duration_days": 3, "parent_ref": None, "vendor_field": 99},
            {"ref": "A2", "name": "b", "duration_days": 2, "parent_ref": "A1"},
        ],
        "relationships": [{"predecessor_ref": "A1", "successor_ref": "A2", "relationship_type": "FS", "lag_days": 0}],
    }
    raw.update(over)
    return raw


def test_round_trip_parse_emit_is_lossless() -> None:
    raw = _raw_doc(vendor_extension={"tool": "x", "build": 7})  # unknown top-level key
    parsed = parse_document(raw)
    again = parsed.to_dict()
    # Unknown top-level + per-row keys both survive.
    assert again["vendor_extension"] == {"tool": "x", "build": 7}
    assert again["activities"][0]["vendor_field"] == 99
    assert canonicalize(again) == canonicalize(raw)


def test_parse_rejects_wrong_format() -> None:
    with pytest.raises(InterchangeError):
        parse_document({"format": "something-else", "format_version": "1.0", "schedule": {}})


def test_parse_rejects_unsupported_version() -> None:
    with pytest.raises(InterchangeError):
        parse_document({"format": FORMAT, "format_version": "9.9", "schedule": {}})


def test_parse_rejects_non_object_and_bad_sections() -> None:
    with pytest.raises(InterchangeError):
        parse_document(["not", "a", "dict"])
    with pytest.raises(InterchangeError):
        parse_document({"format": FORMAT, "format_version": FORMAT_VERSION, "schedule": "nope"})
    with pytest.raises(InterchangeError):
        parse_document({"format": FORMAT, "format_version": FORMAT_VERSION, "schedule": {}, "activities": {}})


def test_validate_document_clean_is_empty() -> None:
    assert validate_document(parse_document(_raw_doc())) == []


def test_validate_document_flags_structural_problems() -> None:
    raw = _raw_doc(
        activities=[
            {"ref": "A1"},
            {"ref": "A1"},  # duplicate
            {"ref": "A3", "parent_ref": "ghost"},  # dangling parent
        ],
        relationships=[
            {"predecessor_ref": "A1", "successor_ref": "missing"},  # dangling endpoint
            {"predecessor_ref": "A3", "successor_ref": "A3"},  # self link
        ],
    )
    issues = validate_document(parse_document(raw))
    joined = " | ".join(issues)
    assert "duplicate activity ref 'A1'" in joined
    assert "parent_ref 'ghost'" in joined
    assert "successor_ref 'missing'" in joined
    assert "self-referential" in joined


def test_canonicalize_orders_rows_independent_of_input_order() -> None:
    a = _raw_doc()
    b = _raw_doc(
        activities=list(reversed(_raw_doc()["activities"])),
        relationships=_raw_doc()["relationships"],
    )
    assert canonicalize(a) == canonicalize(b)
