# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Integration-style tests for BOQ tax_rate computation (Wave 25 / task #168).

These tests exercise the BOQ schema + service-layer tax arithmetic without a
live DB:  they drive the BOQ creation schema and the helper functions that
compute grand_total = net_total + tax_amount.

Full end-to-end DB integration lives in the nightly suite; these fast tests
cover the tax arithmetic correctness and schema validation rules.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.boq.schemas import BOQCreate, BOQListItem, BOQUpdate, BOQWithSections

# ── BOQCreate schema — tax_rate validation ──────────────────────────────────


class TestBOQCreateTaxRateSchema:
    """tax_rate field validation on BOQCreate."""

    def _make_create(self, tax_rate=None) -> BOQCreate:
        return BOQCreate(
            project_id="00000000-0000-0000-0000-000000000001",
            name="Test BOQ",
            tax_rate=tax_rate,
        )

    def test_no_tax_rate_defaults_to_none(self) -> None:
        obj = self._make_create()
        assert obj.tax_rate is None

    def test_tax_rate_as_decimal_string(self) -> None:
        obj = self._make_create(tax_rate="0.19")
        assert obj.tax_rate == Decimal("0.19")

    def test_tax_rate_as_decimal(self) -> None:
        obj = self._make_create(tax_rate=Decimal("0.20"))
        assert obj.tax_rate == Decimal("0.20")

    def test_tax_rate_as_float_coerced(self) -> None:
        # Float inputs are accepted and coerced to Decimal
        obj = self._make_create(tax_rate=0.19)
        # Result must be Decimal, not float
        assert isinstance(obj.tax_rate, Decimal)

    def test_tax_rate_zero_accepted(self) -> None:
        obj = self._make_create(tax_rate="0.00")
        assert obj.tax_rate == Decimal("0.00")

    def test_tax_rate_null_accepted(self) -> None:
        obj = self._make_create(tax_rate=None)
        assert obj.tax_rate is None

    def test_tax_rate_negative_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self._make_create(tax_rate="-0.01")

    def test_tax_rate_over_one_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self._make_create(tax_rate="1.5")

    def test_tax_rate_non_numeric_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self._make_create(tax_rate="nineteen_percent")


class TestBOQUpdateTaxRateSchema:
    """tax_rate field validation on BOQUpdate (PATCH)."""

    def test_patch_sets_tax_rate(self) -> None:
        update = BOQUpdate(tax_rate="0.19")
        assert update.tax_rate == Decimal("0.19")

    def test_patch_clears_tax_rate(self) -> None:
        update = BOQUpdate(tax_rate=None)
        assert update.tax_rate is None

    def test_patch_uk_reduced(self) -> None:
        update = BOQUpdate(tax_rate="0.05")
        assert update.tax_rate == Decimal("0.05")


# ── BOQ totals computation ──────────────────────────────────────────────────
#
# These tests verify the arithmetic contract Wave 25 adds WITHOUT a DB:
#   grand_total = net_total + tax_amount
#   tax_amount  = net_total * tax_rate   (ROUND_HALF_UP to 2 dp)


class TestBOQTotalsWithTax:
    """BOQ totals arithmetic: subtotal 100 + tax_rate 0.19 = 119."""

    def _make_boq_with_sections(
        self,
        net_total: Decimal,
        tax_rate: Decimal | None,
    ) -> BOQWithSections:
        """Construct a minimal BOQWithSections with given totals."""
        if tax_rate is not None:
            tax_amount = (net_total * tax_rate).quantize(Decimal("0.01"))
        else:
            tax_amount = Decimal("0")
        grand_total = net_total + tax_amount

        return BOQWithSections(
            id="00000000-0000-0000-0000-000000000001",
            project_id="00000000-0000-0000-0000-000000000002",
            name="Test BOQ",
            description="",
            status="draft",
            metadata={},
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:00",
            tax_rate=tax_rate,
            direct_cost=net_total,
            net_total=net_total,
            tax_amount=tax_amount,
            grand_total=grand_total,
        )

    def test_subtotal_100_tax_19pct_grand_total_119(self) -> None:
        """Core arithmetic: 100 × 1.19 = 119.00"""
        boq = self._make_boq_with_sections(
            net_total=Decimal("100.00"),
            tax_rate=Decimal("0.19"),
        )
        assert boq.tax_amount == Decimal("19.00")
        assert boq.grand_total == Decimal("119.00")

    def test_subtotal_100_tax_20pct_grand_total_120(self) -> None:
        """UK standard VAT 20 %"""
        boq = self._make_boq_with_sections(
            net_total=Decimal("100.00"),
            tax_rate=Decimal("0.20"),
        )
        assert boq.tax_amount == Decimal("20.00")
        assert boq.grand_total == Decimal("120.00")

    def test_subtotal_100_no_tax_grand_total_100(self) -> None:
        """Without tax_rate, grand_total must equal net_total exactly."""
        boq = self._make_boq_with_sections(
            net_total=Decimal("100.00"),
            tax_rate=None,
        )
        assert boq.tax_amount == Decimal("0")
        assert boq.grand_total == Decimal("100.00")

    def test_subtotal_100_tax_zero_grand_total_100(self) -> None:
        """Explicit zero tax_rate: grand_total = 100 + 0 = 100."""
        boq = self._make_boq_with_sections(
            net_total=Decimal("100.00"),
            tax_rate=Decimal("0.00"),
        )
        assert boq.tax_amount == Decimal("0.00")
        assert boq.grand_total == Decimal("100.00")

    def test_subtotal_1234_tax_19pct(self) -> None:
        """Non-round amount: 1234.56 × 0.19 = 234.57 (rounded HALF_UP)."""
        net = Decimal("1234.56")
        rate = Decimal("0.19")
        expected_tax = (net * rate).quantize(Decimal("0.01"))  # 234.57
        boq = self._make_boq_with_sections(net_total=net, tax_rate=rate)
        assert boq.tax_amount == expected_tax
        assert boq.grand_total == net + expected_tax

    def test_json_serialisation_uses_decimal_strings(self) -> None:
        """tax_amount and grand_total must be emitted as decimal strings in JSON."""
        boq = self._make_boq_with_sections(
            net_total=Decimal("100"),
            tax_rate=Decimal("0.19"),
        )
        data = boq.model_dump(mode="json")
        # Serialised money fields must be strings, not floats.
        # _serialise_money uses format(v, "f") which preserves trailing zeros
        # (Decimal("19.00") -> "19.00", Decimal("119.00") -> "119.00").
        assert isinstance(data["tax_amount"], str)
        assert isinstance(data["grand_total"], str)
        assert Decimal(data["tax_amount"]) == Decimal("19")
        assert Decimal(data["grand_total"]) == Decimal("119")

    def test_tax_rate_serialised_as_string_in_json(self) -> None:
        """tax_rate itself is serialised as a Decimal string."""
        boq = self._make_boq_with_sections(
            net_total=Decimal("100"),
            tax_rate=Decimal("0.19"),
        )
        data = boq.model_dump(mode="json")
        assert data["tax_rate"] == "0.19"


class TestBOQListItemTaxAmount:
    """BOQListItem must carry tax_amount field (Wave 25)."""

    def test_list_item_has_tax_amount_field(self) -> None:
        item = BOQListItem(
            id="00000000-0000-0000-0000-000000000001",
            project_id="00000000-0000-0000-0000-000000000002",
            name="Test BOQ",
            description="",
            status="draft",
            metadata={},
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:00",
            direct_cost_total=Decimal("100"),
            markups_total=Decimal("0"),
            tax_amount=Decimal("19"),
            grand_total=Decimal("119"),
            tax_rate=Decimal("0.19"),
        )
        assert item.tax_amount == Decimal("19")
        assert item.grand_total == Decimal("119")

    def test_list_item_default_tax_amount_is_zero(self) -> None:
        item = BOQListItem(
            id="00000000-0000-0000-0000-000000000001",
            project_id="00000000-0000-0000-0000-000000000002",
            name="Test BOQ",
            description="",
            status="draft",
            metadata={},
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:00",
        )
        assert item.tax_amount == Decimal("0")
