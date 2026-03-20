"""Tests for Cost item Pydantic schemas.

Validates CostItemCreate, CostItemUpdate, and CostSearchQuery
with boundary conditions and constraint enforcement. No database required.
"""

import pytest
from pydantic import ValidationError

from app.modules.costs.schemas import CostItemCreate, CostItemUpdate, CostSearchQuery


# ── CostItemCreate ───────────────────────────────────────────────────────────


class TestCostItemCreate:
    def test_valid_creation(self):
        data = CostItemCreate(code="CONC-001", unit="m3", rate=185.0)
        assert data.code == "CONC-001"
        assert data.unit == "m3"
        assert data.rate == 185.0

    def test_code_required(self):
        with pytest.raises(ValidationError):
            CostItemCreate(unit="m3", rate=10.0)  # type: ignore[call-arg]

    def test_code_min_length(self):
        with pytest.raises(ValidationError):
            CostItemCreate(code="", unit="m3", rate=10.0)

    def test_code_max_length(self):
        data = CostItemCreate(code="A" * 100, unit="m3", rate=10.0)
        assert len(data.code) == 100

    def test_code_over_max_rejected(self):
        with pytest.raises(ValidationError):
            CostItemCreate(code="A" * 101, unit="m3", rate=10.0)

    def test_unit_required(self):
        with pytest.raises(ValidationError):
            CostItemCreate(code="CONC-001", rate=10.0)  # type: ignore[call-arg]

    def test_rate_required(self):
        with pytest.raises(ValidationError):
            CostItemCreate(code="CONC-001", unit="m3")  # type: ignore[call-arg]

    def test_rate_as_float(self):
        data = CostItemCreate(code="X", unit="m2", rate=42.5)
        assert isinstance(data.rate, float)
        assert data.rate == 42.5

    def test_rate_zero_allowed(self):
        data = CostItemCreate(code="X", unit="m2", rate=0.0)
        assert data.rate == 0.0

    def test_rate_negative_rejected(self):
        with pytest.raises(ValidationError):
            CostItemCreate(code="X", unit="m2", rate=-1.0)

    def test_default_currency_eur(self):
        data = CostItemCreate(code="X", unit="m2", rate=10.0)
        assert data.currency == "EUR"

    def test_default_source_cwicr(self):
        data = CostItemCreate(code="X", unit="m2", rate=10.0)
        assert data.source == "cwicr"

    def test_classification_defaults_empty(self):
        data = CostItemCreate(code="X", unit="m2", rate=10.0)
        assert data.classification == {}

    def test_tags_defaults_empty(self):
        data = CostItemCreate(code="X", unit="m2", rate=10.0)
        assert data.tags == []

    def test_descriptions_dict_accepted(self):
        data = CostItemCreate(
            code="X",
            unit="m2",
            rate=10.0,
            descriptions={"en": "Concrete", "de": "Beton"},
        )
        assert data.descriptions["en"] == "Concrete"


# ── CostItemUpdate ───────────────────────────────────────────────────────────


class TestCostItemUpdate:
    def test_all_fields_optional(self):
        data = CostItemUpdate()
        assert data.code is None
        assert data.description is None
        assert data.unit is None
        assert data.rate is None
        assert data.currency is None
        assert data.source is None
        assert data.classification is None
        assert data.components is None
        assert data.tags is None
        assert data.region is None
        assert data.is_active is None
        assert data.metadata is None

    def test_partial_update(self):
        data = CostItemUpdate(rate=200.0)
        assert data.rate == 200.0
        assert data.code is None

    def test_rate_negative_rejected(self):
        with pytest.raises(ValidationError):
            CostItemUpdate(rate=-10.0)

    def test_code_empty_rejected(self):
        with pytest.raises(ValidationError):
            CostItemUpdate(code="")


# ── CostSearchQuery ──────────────────────────────────────────────────────────


class TestCostSearchQuery:
    def test_default_values(self):
        data = CostSearchQuery()
        assert data.limit == 50
        assert data.offset == 0
        assert data.q is None

    def test_limit_max_500(self):
        data = CostSearchQuery(limit=500)
        assert data.limit == 500

    def test_limit_over_500_rejected(self):
        with pytest.raises(ValidationError):
            CostSearchQuery(limit=501)

    def test_limit_min_1(self):
        data = CostSearchQuery(limit=1)
        assert data.limit == 1

    def test_limit_zero_rejected(self):
        with pytest.raises(ValidationError):
            CostSearchQuery(limit=0)

    def test_offset_zero(self):
        data = CostSearchQuery(offset=0)
        assert data.offset == 0

    def test_offset_negative_rejected(self):
        with pytest.raises(ValidationError):
            CostSearchQuery(offset=-1)

    def test_min_rate_negative_rejected(self):
        with pytest.raises(ValidationError):
            CostSearchQuery(min_rate=-1.0)

    def test_max_rate_zero_allowed(self):
        data = CostSearchQuery(max_rate=0.0)
        assert data.max_rate == 0.0

    def test_text_search(self):
        data = CostSearchQuery(q="concrete")
        assert data.q == "concrete"
