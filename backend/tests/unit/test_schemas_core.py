"""Tests for core Pydantic schemas in app/schemas.py.

Validates enums, Classification model, PaginatedResponse, and
the canonical data structures. No database required.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas import (
    CADElement,
    Classification,
    CostSearchQuery,
    MeasurementUnit,
    ModuleInfoSchema,
    OEBase,
    OEResponse,
    PaginatedResponse,
    PositionCreate,
    ProjectCreate,
    SourceType,
    ValidationResultSchema,
    ValidationStatusEnum,
)


# ── MeasurementUnit enum ────────────────────────────────────────────────────


class TestMeasurementUnit:
    def test_all_expected_values_exist(self):
        expected = {"m", "m2", "m3", "kg", "t", "pcs", "lsum", "h", "set", "lm", "l", "pa"}
        actual = {e.value for e in MeasurementUnit}
        assert expected == actual

    def test_total_count(self):
        assert len(MeasurementUnit) == 12

    def test_string_subclass(self):
        assert isinstance(MeasurementUnit.M2, str)
        assert MeasurementUnit.M2 == "m2"

    def test_from_value(self):
        assert MeasurementUnit("kg") == MeasurementUnit.KG

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError):
            MeasurementUnit("invalid_unit")


# ── SourceType enum ──────────────────────────────────────────────────────────


class TestSourceType:
    def test_all_expected_values(self):
        expected = {"manual", "cad_import", "ai_takeoff", "gaeb_import", "excel_import", "api"}
        actual = {e.value for e in SourceType}
        assert expected == actual

    def test_total_count(self):
        assert len(SourceType) == 6

    def test_manual_is_default_string(self):
        assert SourceType.MANUAL == "manual"

    def test_from_value(self):
        assert SourceType("cad_import") == SourceType.CAD_IMPORT


# ── ValidationStatusEnum ────────────────────────────────────────────────────


class TestValidationStatusEnum:
    def test_all_expected_values(self):
        expected = {"pending", "passed", "warnings", "errors"}
        actual = {e.value for e in ValidationStatusEnum}
        assert expected == actual

    def test_total_count(self):
        assert len(ValidationStatusEnum) == 4

    def test_from_value(self):
        assert ValidationStatusEnum("passed") == ValidationStatusEnum.PASSED


# ── Classification ───────────────────────────────────────────────────────────


class TestClassification:
    def test_all_defaults_none(self):
        c = Classification()
        assert c.din276 is None
        assert c.nrm is None
        assert c.masterformat is None
        assert c.uniclass is None
        assert c.omniclass is None
        assert c.custom == {}

    def test_set_din276(self):
        c = Classification(din276="330")
        assert c.din276 == "330"

    def test_set_multiple(self):
        c = Classification(din276="330", nrm="2.6.1", masterformat="03 30 00")
        assert c.din276 == "330"
        assert c.nrm == "2.6.1"
        assert c.masterformat == "03 30 00"

    def test_custom_dict(self):
        c = Classification(custom={"my_standard": "A.1.2"})
        assert c.custom["my_standard"] == "A.1.2"


# ── PaginatedResponse ───────────────────────────────────────────────────────


class TestPaginatedResponse:
    def test_default_values(self):
        p = PaginatedResponse(items=[], total=0, limit=20, offset=0, has_more=False)
        assert p.items == []
        assert p.total == 0
        assert p.has_more is False

    def test_with_items(self):
        p = PaginatedResponse(
            items=[{"id": 1}, {"id": 2}],
            total=100,
            limit=2,
            offset=0,
            has_more=True,
        )
        assert len(p.items) == 2
        assert p.total == 100
        assert p.has_more is True


# ── OEBase ───────────────────────────────────────────────────────────────────


class TestOEBase:
    def test_strip_whitespace(self):
        """OEBase has str_strip_whitespace enabled."""
        # Use a concrete subclass with a string field
        p = ProjectCreate(name="  Test Project  ")
        assert p.name == "Test Project"


# ── ValidationResultSchema ──────────────────────────────────────────────────


class TestValidationResultSchema:
    def test_valid_creation(self):
        r = ValidationResultSchema(
            rule_id="boq_quality.zero_quantity",
            rule_name="Zero Quantity Check",
            severity="error",
            category="quality",
            passed=False,
            message="Position has zero quantity",
        )
        assert r.rule_id == "boq_quality.zero_quantity"
        assert r.passed is False

    def test_optional_fields_default_none(self):
        r = ValidationResultSchema(
            rule_id="test",
            rule_name="Test",
            severity="info",
            category="completeness",
            passed=True,
            message="OK",
        )
        assert r.element_ref is None
        assert r.suggestion is None
        assert r.details == {}


# ── ModuleInfoSchema ─────────────────────────────────────────────────────────


class TestModuleInfoSchema:
    def test_minimal_creation(self):
        m = ModuleInfoSchema(name="oe_boq", display_name="BOQ", version="1.0.0")
        assert m.name == "oe_boq"
        assert m.category == "community"
        assert m.installed is False
        assert m.depends == []

    def test_full_creation(self):
        m = ModuleInfoSchema(
            name="oe_gaeb",
            display_name="GAEB Import/Export",
            version="2.1.0",
            description="GAEB XML support",
            author="OE Team",
            category="core",
            depends=["oe_boq"],
            installed=True,
        )
        assert m.depends == ["oe_boq"]
        assert m.installed is True


# ── CADElement ───────────────────────────────────────────────────────────────


class TestCADElement:
    def test_minimal(self):
        e = CADElement(id="elem_001", category="wall")
        assert e.id == "elem_001"
        assert e.category == "wall"
        assert e.geometry == {}
        assert e.properties == {}
        assert e.quantities == {}

    def test_with_geometry(self):
        e = CADElement(
            id="elem_002",
            category="floor",
            geometry={"type": "slab", "area_m2": 85.0},
            quantities={"area": 85.0, "volume": 17.0},
        )
        assert e.geometry["area_m2"] == 85.0
        assert e.quantities["volume"] == 17.0


# ── Core CostSearchQuery ────────────────────────────────────────────────────


class TestCoreCostSearchQuery:
    def test_defaults(self):
        q = CostSearchQuery()
        assert q.limit == 20
        assert q.offset == 0
        assert q.semantic is False

    def test_limit_max_100(self):
        q = CostSearchQuery(limit=100)
        assert q.limit == 100

    def test_limit_over_100_rejected(self):
        with pytest.raises(ValidationError):
            CostSearchQuery(limit=101)
