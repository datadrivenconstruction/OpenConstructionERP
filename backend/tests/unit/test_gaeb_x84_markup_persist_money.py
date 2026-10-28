"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠FA-GAEB-002 - GAEB X84 markup must persist its exact <IT>, not re-derive it.

Sister test to ``test_gaeb_x84_import_money.py``. That one proves the parser
surfaces the Zuschlagsposition (ITMarkup 850,000.00 at 10% = IT 85,000.00)
into ``metadata['markup_items']``. This one proves the *persistence* step
(``_persist_imported_markups``) then writes it correctly and that the totals
engine reconciles the BOQ to its declared grand total.

The money bug: a GAEB ``<MarkupItem>`` carries three figures -

* ``ITMarkup`` - the base, which is the sum of ONLY the surcharged positions
  (a SUBSET of the BOQ): here 850,000.00;
* ``Markup``   - the percentage: here 10%;
* ``IT``       - the exact resulting amount: here 85,000.00 (= 850,000 * 10%).

The percentage was computed against the *partial* base (850,000.00), NOT the
full BOQ direct cost (1,915,000.00). Persisting it as a percentage markup made
the totals engine recompute 1,915,000.00 * 10% = 191,500.00, inflating the
grand total to 2,106,500.00 (off by 106,500.00). The fix persists the exact
``<IT>`` as a FIXED markup, which the engine adds verbatim:
1,915,000.00 + 85,000.00 = 2,000,000.00.

Reference figures (computed by hand from the fixture - identical to the
sister test):

* sum of the 27 ``<Item><IT>``           = 1,915,000.00  (direct cost)
* the single ``<MarkupItem><IT>``         =    85,000.00  (the exact surcharge)
* the ``<MarkupItem><ITMarkup>``          =   850,000.00  (the partial base)
* declared ``<BoQInfo><Totals><Total>``   = 2,000,000.00  (== 1,915,000 + 85,000)
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.modules.boq.importers.gaeb_xml import GAEBXMLImporter
from app.modules.boq.router import _persist_imported_markups
from app.modules.boq.schemas import MarkupCreate
from app.modules.boq.service import _calculate_markup_amounts

# In-house X84 conformance fixture.
_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "gaeb"
_X84 = _FIXTURES / "oce_conformance_x84.x84"

_REF_DIRECT_COST = Decimal("1915000.00")
_REF_MARKUP_IT = Decimal("85000.00")
_REF_MARKUP_BASE = Decimal("850000.00")
_REF_GRAND_TOTAL = Decimal("2000000.00")
# The amount the OLD (buggy) percentage-persist path would have produced.
_WRONG_RECOMPUTED = (_REF_DIRECT_COST * Decimal("10") / Decimal("100")).quantize(Decimal("0.01"))  # 191,500.00


class _RecordingService:
    """Minimal stand-in for ``BOQService`` that records every markup payload.

    ``_persist_imported_markups`` only ever calls ``await service.add_markup``;
    we capture each :class:`MarkupCreate` so the test can assert on exactly what
    would be written, without a database.
    """

    def __init__(self) -> None:
        self.created: list[MarkupCreate] = []

    async def add_markup(self, boq_id: Any, data: MarkupCreate) -> MarkupCreate:  # noqa: ARG002
        self.created.append(data)
        return data


class _FakeMarkupORM:
    """Attribute-only stand-in for ``BOQMarkup`` as read by the totals engine.

    ``_calculate_markup_amounts`` reads only ``is_active``, ``apply_to``,
    ``markup_type``, ``percentage`` and ``fixed_amount``; the real ORM stores
    money as strings, so a fixed markup's ``fixed_amount`` is the stringified
    Decimal exactly as ``add_markup`` would persist it.
    """

    def __init__(self, data: MarkupCreate) -> None:
        self.is_active = data.is_active
        self.apply_to = data.apply_to
        self.markup_type = data.markup_type
        self.percentage = str(data.percentage)
        self.fixed_amount = str(data.fixed_amount)


@pytest.mark.skipif(not _X84.exists(), reason="official BVBS X84 fixture not present")
class TestGAEBX84MarkupPersistMoney:
    @pytest.mark.asyncio
    async def test_markup_persisted_as_fixed_exact_it(self) -> None:
        """The Zuschlag is written as a FIXED markup carrying the exact <IT>."""
        imported = await GAEBXMLImporter.parse(_X84.read_bytes())

        # Sanity: the parser surfaced exactly the markup we expect to persist.
        markup_items = imported.metadata["markup_items"]
        assert len(markup_items) == 1
        assert Decimal(markup_items[0]["it"]) == _REF_MARKUP_IT
        assert Decimal(markup_items[0]["it_markup_base"]) == _REF_MARKUP_BASE

        service = _RecordingService()
        errors: list[dict[str, Any]] = []
        await _persist_imported_markups(
            "00000000-0000-0000-0000-000000000001",
            imported,
            service=service,  # type: ignore[arg-type]
            errors=errors,
        )

        assert errors == []
        assert len(service.created) == 1
        created = service.created[0]

        # (a) persisted as a fixed markup carrying the exact GAEB <IT>.
        assert created.markup_type == "fixed"
        assert created.fixed_amount == _REF_MARKUP_IT
        assert created.apply_to == "subtotal"
        # The percentage field stays at its default - the amount is authoritative.
        assert created.percentage == 0.0
        # Provenance preserved so nothing about the source figure is lost.
        assert created.metadata["source"] == "gaeb_import"
        assert created.metadata["gaeb_ordinal"] == "001.002.0040"
        assert Decimal(created.metadata["gaeb_it"]) == _REF_MARKUP_IT
        assert Decimal(created.metadata["gaeb_it_markup_base"]) == _REF_MARKUP_BASE
        # The source percent is preserved verbatim from the file (<Markup>10.00</Markup>).
        assert Decimal(created.metadata["gaeb_markup_percentage"]) == Decimal("10")

    @pytest.mark.asyncio
    async def test_engine_reconciles_to_declared_grand_total(self) -> None:
        """direct_cost + the persisted fixed markup == declared 2,000,000.00."""
        imported = await GAEBXMLImporter.parse(_X84.read_bytes())

        service = _RecordingService()
        errors: list[dict[str, Any]] = []
        await _persist_imported_markups(
            "00000000-0000-0000-0000-000000000001",
            imported,
            service=service,  # type: ignore[arg-type]
            errors=errors,
        )
        assert len(service.created) == 1

        # Feed the persisted markup through the REAL totals engine with the
        # fixture's true direct cost (sum of the 27 item ITs).
        orm_markups = [_FakeMarkupORM(m) for m in service.created]
        computed = _calculate_markup_amounts(_REF_DIRECT_COST, orm_markups)

        assert len(computed) == 1
        _markup, amount = computed[0]
        # The engine adds the fixed amount verbatim - exactly the GAEB <IT>.
        assert amount == _REF_MARKUP_IT

        grand_total = _REF_DIRECT_COST + sum((a for _m, a in computed), Decimal("0"))
        assert grand_total == _REF_GRAND_TOTAL

        # And it is NOT the inflated figure the old percentage path produced.
        assert amount != _WRONG_RECOMPUTED
        assert grand_total != _REF_DIRECT_COST + _WRONG_RECOMPUTED

    @pytest.mark.asyncio
    async def test_unpriced_percentage_fallback_still_supported(self) -> None:
        """A markup item with a percentage but no <IT> keeps the percentage path.

        This is the X83 (Angebotsanforderung) shape - the file declares the
        Zuschlag percent but no resulting amount, so the engine must derive it.
        """

        # A hand-built imported result carrying only a percentage (no it).
        class _Imported:
            metadata = {
                "markup_items": [
                    {
                        "ordinal": "001.002.0040",
                        "it": "",
                        "it_markup_base": "",
                        "percentage": "10",
                    }
                ]
            }

        service = _RecordingService()
        errors: list[dict[str, Any]] = []
        await _persist_imported_markups(
            "00000000-0000-0000-0000-000000000001",
            _Imported(),  # type: ignore[arg-type]
            service=service,  # type: ignore[arg-type]
            errors=errors,
        )

        assert errors == []
        assert len(service.created) == 1
        created = service.created[0]
        assert created.markup_type == "percentage"
        assert created.percentage == pytest.approx(10.0)
        assert created.apply_to == "subtotal"
        assert created.fixed_amount == Decimal("0")
