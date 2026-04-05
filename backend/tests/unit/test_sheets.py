"""Tests for Sheet Management — schemas, detection logic, and discipline mapping.

Validates SheetResponse, SheetUpdate, SheetVersionHistory schemas,
detect_sheet_info regex extraction, and discipline auto-detection.
No database required.
"""

import pytest
from pydantic import ValidationError

from app.modules.documents.schemas import SheetResponse, SheetUpdate, SheetVersionHistory
from app.modules.documents.service import (
    DISCIPLINE_PREFIX_MAP,
    detect_discipline_from_sheet_number,
    detect_sheet_info,
)


# ── detect_discipline_from_sheet_number ───────────────────────────────────


class TestDetectDiscipline:
    def test_architectural(self):
        assert detect_discipline_from_sheet_number("A-201") == "Architectural"

    def test_structural(self):
        assert detect_discipline_from_sheet_number("S-100") == "Structural"

    def test_mechanical(self):
        assert detect_discipline_from_sheet_number("M-301") == "Mechanical"

    def test_electrical(self):
        assert detect_discipline_from_sheet_number("E-101") == "Electrical"

    def test_plumbing(self):
        assert detect_discipline_from_sheet_number("P-001") == "Plumbing"

    def test_civil(self):
        assert detect_discipline_from_sheet_number("C-100") == "Civil"

    def test_landscape(self):
        assert detect_discipline_from_sheet_number("L-001") == "Landscape"

    def test_lowercase_prefix(self):
        assert detect_discipline_from_sheet_number("a-201") == "Architectural"

    def test_no_dash_format(self):
        assert detect_discipline_from_sheet_number("A201") == "Architectural"

    def test_unknown_prefix(self):
        assert detect_discipline_from_sheet_number("X-100") is None

    def test_none_input(self):
        assert detect_discipline_from_sheet_number(None) is None

    def test_empty_string(self):
        assert detect_discipline_from_sheet_number("") is None

    def test_all_prefixes_mapped(self):
        expected = {"A", "S", "M", "E", "P", "C", "L"}
        assert set(DISCIPLINE_PREFIX_MAP.keys()) == expected


# ── detect_sheet_info ────────────────────────────────────────────────────


class TestDetectSheetInfo:
    def test_empty_text(self):
        result = detect_sheet_info("")
        assert result["sheet_number"] is None
        assert result["sheet_title"] is None
        assert result["scale"] is None
        assert result["revision"] is None

    def test_none_text(self):
        result = detect_sheet_info("")
        assert all(v is None for v in result.values())

    def test_sheet_number_with_dash(self):
        result = detect_sheet_info("Some text A-201 more text")
        assert result["sheet_number"] == "A-201"

    def test_sheet_number_labeled(self):
        result = detect_sheet_info("SHEET NO: A-301\nSome text")
        assert result["sheet_number"] is not None
        assert "A-301" in result["sheet_number"]

    def test_sheet_number_dwg_no(self):
        result = detect_sheet_info("DWG NO: S-100\nOther content")
        assert result["sheet_number"] is not None

    def test_scale_1_to_100(self):
        result = detect_sheet_info("SCALE: 1:100\nSome text")
        assert result["scale"] is not None
        assert "1:100" in result["scale"]

    def test_scale_inline(self):
        result = detect_sheet_info("Drawing at 1:50 scale")
        assert result["scale"] is not None
        assert "1:50" in result["scale"]

    def test_revision_rev_a(self):
        result = detect_sheet_info("REV A\nSome content")
        assert result["revision"] == "A"

    def test_revision_revision_3(self):
        result = detect_sheet_info("REVISION: 3\nMore text")
        assert result["revision"] == "3"

    def test_revision_rev_dot(self):
        result = detect_sheet_info("Rev. B\nContent")
        assert result["revision"] == "B"

    def test_sheet_title_labeled(self):
        result = detect_sheet_info("SHEET TITLE: Floor Plan Level 2\nOther stuff")
        assert result["sheet_title"] == "Floor Plan Level 2"

    def test_title_labeled(self):
        result = detect_sheet_info("TITLE: Roof Plan\nOther content")
        assert result["sheet_title"] == "Roof Plan"

    def test_drawing_title(self):
        result = detect_sheet_info("DRAWING TITLE: Foundation Details\nMore")
        assert result["sheet_title"] == "Foundation Details"

    def test_combined_detection(self):
        text = (
            "PROJECT: Test Building\n"
            "SHEET NO: A-201\n"
            "SHEET TITLE: Floor Plan Level 2\n"
            "SCALE: 1:100\n"
            "REV A\n"
            "DATE: 2025-01-15\n"
        )
        result = detect_sheet_info(text)
        assert result["sheet_number"] is not None
        assert result["sheet_title"] == "Floor Plan Level 2"
        assert "1:100" in (result["scale"] or "")
        assert result["revision"] == "A"

    def test_title_too_short_ignored(self):
        result = detect_sheet_info("TITLE: AB\n")
        assert result["sheet_title"] is None

    def test_multidigit_sheet_number(self):
        result = detect_sheet_info("Some text S-1001 more")
        assert result["sheet_number"] == "S-1001"


# ── SheetUpdate schema ───────────────────────────────────────────────────


class TestSheetUpdate:
    def test_all_fields_optional(self):
        data = SheetUpdate()
        assert data.sheet_number is None
        assert data.sheet_title is None
        assert data.discipline is None
        assert data.revision is None
        assert data.scale is None
        assert data.is_current is None
        assert data.metadata is None

    def test_partial_update(self):
        data = SheetUpdate(discipline="Structural", revision="B")
        assert data.discipline == "Structural"
        assert data.revision == "B"
        assert data.sheet_number is None

    def test_sheet_number_max_length(self):
        data = SheetUpdate(sheet_number="A" * 100)
        assert len(data.sheet_number) == 100

    def test_sheet_number_over_max_rejected(self):
        with pytest.raises(ValidationError):
            SheetUpdate(sheet_number="A" * 101)

    def test_sheet_title_max_length(self):
        data = SheetUpdate(sheet_title="X" * 500)
        assert len(data.sheet_title) == 500

    def test_sheet_title_over_max_rejected(self):
        with pytest.raises(ValidationError):
            SheetUpdate(sheet_title="X" * 501)

    def test_is_current_bool(self):
        data = SheetUpdate(is_current=False)
        assert data.is_current is False

    def test_metadata_accepts_dict(self):
        data = SheetUpdate(metadata={"key": "value"})
        assert data.metadata == {"key": "value"}

    def test_strip_whitespace(self):
        data = SheetUpdate(discipline="  Architectural  ")
        assert data.discipline == "Architectural"


# ── SheetVersionHistory schema ───────────────────────────────────────────


class TestSheetVersionHistory:
    def test_empty_history(self):
        from datetime import datetime, timezone
        from uuid import uuid4

        current = SheetResponse(
            id=uuid4(),
            project_id=uuid4(),
            page_number=1,
            created_at=datetime.now(tz=timezone.utc),
            updated_at=datetime.now(tz=timezone.utc),
        )
        history = SheetVersionHistory(current=current, history=[])
        assert history.current.page_number == 1
        assert history.history == []

    def test_with_history(self):
        from datetime import datetime, timezone
        from uuid import uuid4

        now = datetime.now(tz=timezone.utc)
        pid = uuid4()

        current = SheetResponse(
            id=uuid4(), project_id=pid, page_number=1,
            revision="B", created_at=now, updated_at=now,
        )
        prev = SheetResponse(
            id=uuid4(), project_id=pid, page_number=1,
            revision="A", created_at=now, updated_at=now,
        )
        history = SheetVersionHistory(current=current, history=[prev])
        assert len(history.history) == 1
        assert history.history[0].revision == "A"
