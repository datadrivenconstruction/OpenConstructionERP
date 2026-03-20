"""Tests for Project Pydantic schemas.

Validates ProjectCreate and ProjectUpdate with boundary conditions
and verifies no hardcoded restrictions on region/currency/standard.
No database required.
"""

import pytest
from pydantic import ValidationError

from app.modules.projects.schemas import ProjectCreate, ProjectUpdate


# ── ProjectCreate ────────────────────────────────────────────────────────────


class TestProjectCreate:
    def test_valid_creation(self):
        data = ProjectCreate(name="New Office")
        assert data.name == "New Office"

    def test_name_required(self):
        with pytest.raises(ValidationError):
            ProjectCreate()  # type: ignore[call-arg]

    def test_name_min_length_1(self):
        data = ProjectCreate(name="A")
        assert data.name == "A"

    def test_name_empty_rejected(self):
        with pytest.raises(ValidationError):
            ProjectCreate(name="")

    def test_name_max_length_255(self):
        data = ProjectCreate(name="A" * 255)
        assert len(data.name) == 255

    def test_name_over_255_rejected(self):
        with pytest.raises(ValidationError):
            ProjectCreate(name="A" * 256)

    def test_description_default_empty(self):
        data = ProjectCreate(name="Test")
        assert data.description == ""

    def test_description_max_length(self):
        data = ProjectCreate(name="Test", description="X" * 5000)
        assert len(data.description) == 5000

    def test_description_over_max_rejected(self):
        with pytest.raises(ValidationError):
            ProjectCreate(name="Test", description="X" * 5001)

    def test_region_default_empty(self):
        data = ProjectCreate(name="Test")
        assert data.region == ""

    def test_currency_default_empty(self):
        data = ProjectCreate(name="Test")
        assert data.currency == ""

    def test_classification_standard_default_empty(self):
        data = ProjectCreate(name="Test")
        assert data.classification_standard == ""

    def test_locale_default_en(self):
        data = ProjectCreate(name="Test")
        assert data.locale == "en"

    def test_default_validation_rule_sets(self):
        data = ProjectCreate(name="Test")
        assert data.validation_rule_sets == ["boq_quality"]

    # No hardcoded restrictions — any values accepted

    def test_any_region_accepted(self):
        for region in ("DACH", "UK", "US-Northeast", "Asia-Pacific", "Custom Region"):
            data = ProjectCreate(name="Test", region=region)
            assert data.region == region

    def test_any_currency_accepted(self):
        for currency in ("EUR", "USD", "GBP", "JPY", "CHF"):
            data = ProjectCreate(name="Test", currency=currency)
            assert data.currency == currency

    def test_any_classification_standard_accepted(self):
        for std in ("din276", "nrm", "masterformat", "uniclass", "custom_v1"):
            data = ProjectCreate(name="Test", classification_standard=std)
            assert data.classification_standard == std

    def test_custom_validation_rule_sets(self):
        data = ProjectCreate(
            name="Test",
            validation_rule_sets=["din276", "gaeb", "boq_quality"],
        )
        assert data.validation_rule_sets == ["din276", "gaeb", "boq_quality"]


# ── ProjectUpdate ────────────────────────────────────────────────────────────


class TestProjectUpdate:
    def test_all_fields_optional(self):
        data = ProjectUpdate()
        assert data.name is None
        assert data.description is None
        assert data.region is None
        assert data.classification_standard is None
        assert data.currency is None
        assert data.locale is None
        assert data.validation_rule_sets is None
        assert data.metadata is None

    def test_partial_update_name_only(self):
        data = ProjectUpdate(name="Renamed")
        assert data.name == "Renamed"
        assert data.description is None

    def test_name_empty_rejected(self):
        with pytest.raises(ValidationError):
            ProjectUpdate(name="")

    def test_name_min_length_1(self):
        data = ProjectUpdate(name="X")
        assert data.name == "X"

    def test_metadata_accepts_dict(self):
        data = ProjectUpdate(metadata={"key": "value", "count": 42})
        assert data.metadata == {"key": "value", "count": 42}

    def test_update_region(self):
        data = ProjectUpdate(region="Berlin")
        assert data.region == "Berlin"

    def test_update_currency(self):
        data = ProjectUpdate(currency="USD")
        assert data.currency == "USD"
