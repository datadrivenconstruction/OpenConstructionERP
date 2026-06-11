"""FA-GAEB-001 - GAEB X84 import must preserve every cent.

The worst money bug in the full audit: importing the official BVBS
Pruefdatei DA XML 3.3 X84 (Angebotsabgabe / priced bid) used to wipe all
2,000,000.00 EUR to 0.00 while reporting ``imported: 27, errors: []``. An
X84 carries the binding unit price in ``<UP>`` and the binding position
total in ``<IT>`` but no ``<Qty>``; the old importer dropped IT, defaulted
Qty to 0 and so produced a 0.00 grand total, and silently dropped the
``<MarkupItem>`` (Zuschlagsposition, ITMarkup 850,000.00 at 10% = IT
85,000.00).

The reference totals below are computed once, by hand, from the fixture
(summing the ``<IT>`` children) and hardcoded:

* sum of the 27 ``<Item><IT>`` values  = 1,915,000.00
* the single ``<MarkupItem><IT>``       =    85,000.00
* declared ``<BoQInfo><Totals><Total>`` = 2,000,000.00  (== 1,915,000 + 85,000)

This test imports the real fixture (pure parser, no DB) and asserts:

1. ``quantity * unit_rate`` of every item sums to 1,915,000.00 to the cent;
2. the authoritative ``IT`` is preserved verbatim under
   ``metadata["gaeb_it"]`` and sums to the same figure;
3. the markup position is surfaced (in ``metadata["markup_items"]`` and as a
   warning) - never dropped silently;
4. the importer reports honest counts (no lost element goes unreported).
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from app.modules.boq.importers.gaeb_xml import GAEBXMLImporter

# Committed copy of the official BVBS Pruefdatei 3.3 X84 (see
# tests/fixtures/gaeb/README.md for provenance).
_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "gaeb"
_X84 = _FIXTURES / "bvbs_pruefdatei_3.3_x84.x84"

# Reference figures computed by hand from the fixture (sum of <IT>).
_REF_ITEM_IT_TOTAL = Decimal("1915000.00")
_REF_MARKUP_IT = Decimal("85000.00")
_REF_MARKUP_BASE = Decimal("850000.00")
_REF_GRAND_TOTAL = Decimal("2000000.00")
_REF_ITEM_COUNT = 27


def _line_total(quantity: float, unit_rate: float) -> Decimal:
    """Reproduce the service's quantity * unit_rate rounding (4dp -> 2dp)."""
    return (Decimal(repr(quantity)) * Decimal(repr(unit_rate))).quantize(Decimal("0.01"))


@pytest.mark.skipif(not _X84.exists(), reason="official BVBS X84 fixture not present")
class TestGAEBX84ImportMoney:
    @pytest.mark.asyncio
    async def test_grand_total_to_the_cent(self) -> None:
        result = await GAEBXMLImporter.parse(_X84.read_bytes())
        items = [p for p in result.positions if not p.is_section]
        assert len(items) == _REF_ITEM_COUNT

        # 1. quantity * unit_rate reconstructs IT to the cent for every line.
        computed = sum((_line_total(p.quantity, p.unit_rate) for p in items), Decimal("0"))
        assert computed == _REF_ITEM_IT_TOTAL

        # 2. The binding IT is preserved verbatim and sums identically.
        it_sum = sum(
            (Decimal(p.metadata["gaeb_it"]) for p in items if "gaeb_it" in p.metadata),
            Decimal("0"),
        )
        assert it_sum == _REF_ITEM_IT_TOTAL

        # Item totals plus the markup IT equal the declared LV grand total.
        markups = result.metadata["markup_items"]
        markup_it = sum((Decimal(m["it"]) for m in markups if m["it"]), Decimal("0"))
        assert it_sum + markup_it == _REF_GRAND_TOTAL

    @pytest.mark.asyncio
    async def test_phase_detected_as_x84(self) -> None:
        result = await GAEBXMLImporter.parse(_X84.read_bytes())
        assert result.metadata["da_kind"] == "x84"
        items = [p for p in result.positions if not p.is_section]
        assert all(p.metadata["gaeb_da_kind"] == "x84" for p in items)

    @pytest.mark.asyncio
    async def test_markup_position_not_dropped_silently(self) -> None:
        result = await GAEBXMLImporter.parse(_X84.read_bytes())
        markups = result.metadata["markup_items"]
        assert len(markups) == 1
        mk = markups[0]
        assert Decimal(mk["it"]) == _REF_MARKUP_IT
        assert Decimal(mk["it_markup_base"]) == _REF_MARKUP_BASE
        assert mk["ordinal"] == "002.001.0030"
        # And it surfaces as a warning so the UI cannot miss it.
        assert any("Markup position" in w["warning"] for w in result.warnings)

    @pytest.mark.asyncio
    async def test_import_reports_honest_counts(self) -> None:
        result = await GAEBXMLImporter.parse(_X84.read_bytes())
        # No money was lost: every priced line was valued, none unmapped.
        assert result.metadata["unmapped_money_count"] == 0
        assert result.metadata["derived_quantity_count"] == _REF_ITEM_COUNT
        # The response carries warnings (markup) and zero hard errors - the
        # old importer reported errors:[] while losing 2,000,000.00.
        assert result.errors == []
        assert len(result.warnings) >= 1

    @pytest.mark.asyncio
    async def test_full_oz_preserved_not_opaque_id(self) -> None:
        result = await GAEBXMLImporter.parse(_X84.read_bytes())
        ordinals = [p.ordinal for p in result.positions if not p.is_section]
        # Real OZ from the RNoPart chain, including the RNoIndex variants.
        assert "001.001.0010" in ordinals
        assert "001.001.0010.1" in ordinals
        assert "001.001.0010.A" in ordinals
        # None of the opaque xs:ID values leaked through as the ordinal.
        assert not any(o.startswith("ID0") or o.startswith("ID02") for o in ordinals)

    @pytest.mark.asyncio
    async def test_hierarchy_not_flattened(self) -> None:
        result = await GAEBXMLImporter.parse(_X84.read_bytes())
        sections = [p for p in result.positions if p.is_section]
        # The two-level BoQCtgy tree is mirrored as section header rows.
        assert len(sections) >= 6
        section_ordinals = {s.ordinal for s in sections}
        assert "001" in section_ordinals
        assert "001.001" in section_ordinals
