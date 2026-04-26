"""Tests for BOQ Pydantic schemas.

Validates create/update/markup schemas with boundary conditions,
defaults, and constraint enforcement. No database required.
"""

import uuid

import pytest
from pydantic import ValidationError

from app.modules.boq.schemas import (
    BOQCreate,
    BOQFromTemplateRequest,
    BOQUpdate,
    MarkupCreate,
    PositionCreate,
    SectionCreate,
)

# ── BOQCreate ────────────────────────────────────────────────────────────────


class TestBOQCreate:
    def test_valid_creation(self):
        data = BOQCreate(project_id=uuid.uuid4(), name="Test BOQ")
        assert data.name == "Test BOQ"
        assert data.description == ""

    def test_requires_project_id(self):
        with pytest.raises(ValidationError):
            BOQCreate(name="Test BOQ")  # type: ignore[call-arg]

    def test_requires_name(self):
        with pytest.raises(ValidationError):
            BOQCreate(project_id=uuid.uuid4())  # type: ignore[call-arg]

    def test_name_min_length(self):
        with pytest.raises(ValidationError):
            BOQCreate(project_id=uuid.uuid4(), name="")

    def test_name_max_length(self):
        data = BOQCreate(project_id=uuid.uuid4(), name="A" * 255)
        assert len(data.name) == 255

    def test_name_over_max_rejected(self):
        with pytest.raises(ValidationError):
            BOQCreate(project_id=uuid.uuid4(), name="A" * 256)

    def test_description_default_empty(self):
        data = BOQCreate(project_id=uuid.uuid4(), name="BOQ")
        assert data.description == ""

    def test_whitespace_stripped(self):
        data = BOQCreate(project_id=uuid.uuid4(), name="  Test  ")
        assert data.name == "Test"


# ── BOQUpdate ────────────────────────────────────────────────────────────────


class TestBOQUpdate:
    def test_all_fields_optional(self):
        data = BOQUpdate()
        assert data.name is None
        assert data.description is None
        assert data.status is None
        assert data.metadata is None

    def test_partial_update(self):
        data = BOQUpdate(name="Updated")
        assert data.name == "Updated"
        assert data.description is None

    def test_status_valid_values(self):
        for status in ("draft", "final", "archived"):
            data = BOQUpdate(status=status)
            assert data.status == status

    def test_status_invalid_rejected(self):
        with pytest.raises(ValidationError):
            BOQUpdate(status="deleted")


# ── PositionCreate ───────────────────────────────────────────────────────────


class TestPositionCreate:
    def test_valid_creation(self):
        # BUG-MATH02: quantity is now required.
        data = PositionCreate(
            boq_id=uuid.uuid4(),
            ordinal="01.01.0010",
            unit="m2",
            quantity=1.0,
        )
        assert data.ordinal == "01.01.0010"
        assert data.unit == "m2"

    def test_empty_description_allowed(self):
        data = PositionCreate(
            boq_id=uuid.uuid4(),
            ordinal="01.01.0010",
            unit="m2",
            quantity=1.0,
            description="",
        )
        assert data.description == ""

    def test_quantity_required(self):
        # BUG-MATH02: omitting quantity now fails validation.
        with pytest.raises(ValidationError) as exc:
            PositionCreate(
                boq_id=uuid.uuid4(),
                ordinal="01.01.0010",
                unit="m2",
            )  # type: ignore[call-arg]
        assert "quantity" in str(exc.value).lower()

    def test_unit_rate_defaults_to_zero(self):
        data = PositionCreate(
            boq_id=uuid.uuid4(),
            ordinal="01.01.0010",
            unit="m2",
            quantity=1.0,
        )
        assert data.unit_rate == 0.0

    def test_negative_quantity_rejected(self):
        with pytest.raises(ValidationError):
            PositionCreate(
                boq_id=uuid.uuid4(),
                ordinal="01.01.0010",
                unit="m2",
                quantity=-1.0,
            )

    def test_negative_unit_rate_rejected(self):
        with pytest.raises(ValidationError):
            PositionCreate(
                boq_id=uuid.uuid4(),
                ordinal="01.01.0010",
                unit="m2",
                quantity=1.0,
                unit_rate=-5.0,
            )

    def test_confidence_range_valid(self):
        data = PositionCreate(
            boq_id=uuid.uuid4(),
            ordinal="01.01.0010",
            unit="m2",
            quantity=1.0,
            confidence=0.85,
        )
        assert data.confidence == 0.85

    def test_confidence_over_1_rejected(self):
        with pytest.raises(ValidationError):
            PositionCreate(
                boq_id=uuid.uuid4(),
                ordinal="01.01.0010",
                unit="m2",
                quantity=1.0,
                confidence=1.5,
            )

    def test_source_defaults_to_manual(self):
        data = PositionCreate(
            boq_id=uuid.uuid4(),
            ordinal="01.01.0010",
            unit="m2",
            quantity=1.0,
        )
        assert data.source == "manual"

    def test_classification_defaults_to_empty_dict(self):
        data = PositionCreate(
            boq_id=uuid.uuid4(),
            ordinal="01.01.0010",
            unit="m2",
            quantity=1.0,
        )
        assert data.classification == {}

    def test_ordinal_required(self):
        with pytest.raises(ValidationError):
            PositionCreate(
                boq_id=uuid.uuid4(),
                unit="m2",
            )  # type: ignore[call-arg]


# ── SectionCreate ────────────────────────────────────────────────────────────


class TestSectionCreate:
    def test_valid_section(self):
        data = SectionCreate(ordinal="01", description="Earthworks")
        assert data.ordinal == "01"
        assert data.description == "Earthworks"

    def test_ordinal_required(self):
        with pytest.raises(ValidationError):
            SectionCreate(description="Test")  # type: ignore[call-arg]

    def test_empty_ordinal_rejected(self):
        with pytest.raises(ValidationError):
            SectionCreate(ordinal="", description="Test")

    def test_description_defaults_empty(self):
        data = SectionCreate(ordinal="01")
        assert data.description == ""

    def test_metadata_defaults_empty_dict(self):
        data = SectionCreate(ordinal="01")
        assert data.metadata == {}


# ── MarkupCreate ─────────────────────────────────────────────────────────────


class TestMarkupCreate:
    def test_valid_markup(self):
        data = MarkupCreate(name="Overhead", percentage=10.0)
        assert data.name == "Overhead"
        assert data.percentage == 10.0

    def test_percentage_min_zero(self):
        data = MarkupCreate(name="Zero", percentage=0.0)
        assert data.percentage == 0.0

    def test_percentage_max_100(self):
        data = MarkupCreate(name="Full", percentage=100.0)
        assert data.percentage == 100.0

    def test_percentage_over_100_rejected(self):
        with pytest.raises(ValidationError):
            MarkupCreate(name="Over", percentage=101.0)

    def test_percentage_negative_rejected(self):
        with pytest.raises(ValidationError):
            MarkupCreate(name="Neg", percentage=-5.0)

    def test_valid_categories(self):
        valid = ["overhead", "profit", "tax", "contingency", "insurance", "bond", "other"]
        for cat in valid:
            data = MarkupCreate(name="Test", category=cat)
            assert data.category == cat

    def test_invalid_category_rejected(self):
        with pytest.raises(ValidationError):
            MarkupCreate(name="Test", category="custom_invalid")

    def test_valid_markup_types(self):
        for mt in ("percentage", "fixed", "per_unit"):
            data = MarkupCreate(name="Test", markup_type=mt)
            assert data.markup_type == mt

    def test_invalid_markup_type_rejected(self):
        with pytest.raises(ValidationError):
            MarkupCreate(name="Test", markup_type="absolute")

    def test_valid_apply_to(self):
        for apply in ("direct_cost", "subtotal", "cumulative"):
            data = MarkupCreate(name="Test", apply_to=apply)
            assert data.apply_to == apply

    def test_invalid_apply_to_rejected(self):
        with pytest.raises(ValidationError):
            MarkupCreate(name="Test", apply_to="everything")

    def test_defaults(self):
        data = MarkupCreate(name="Test")
        assert data.markup_type == "percentage"
        assert data.category == "overhead"
        assert data.percentage == 0.0
        assert data.fixed_amount == 0.0
        assert data.apply_to == "direct_cost"
        assert data.sort_order == 0
        assert data.is_active is True


# ── BOQFromTemplateRequest ───────────────────────────────────────────────────


class TestBOQFromTemplateRequest:
    def test_valid_request(self):
        data = BOQFromTemplateRequest(
            project_id=uuid.uuid4(),
            template_id="residential",
            area_m2=500.0,
        )
        assert data.area_m2 == 500.0

    def test_area_must_be_positive(self):
        with pytest.raises(ValidationError):
            BOQFromTemplateRequest(
                project_id=uuid.uuid4(),
                template_id="residential",
                area_m2=0.0,
            )

    def test_area_negative_rejected(self):
        with pytest.raises(ValidationError):
            BOQFromTemplateRequest(
                project_id=uuid.uuid4(),
                template_id="residential",
                area_m2=-100.0,
            )
