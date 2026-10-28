# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The X83 export must not state a unit the source file never stated.

An X84 item carries no ``QU``, so the importer guesses a unit to be able to
store the row at all and records the source's silence in
``metadata["gaeb_unit_original"]``. Exporting that guess as a ``QU`` code turns
our guess into somebody else's fact: a reader of the exported file cannot tell
``psch`` we invented from ``psch`` a bidder wrote.

The exporter therefore consults the recorded original. The distinction is
membership rather than truthiness, and one of the tests below exists only to
hold that line: a row with no ``gaeb_unit_original`` key at all has no recorded
silence to honour, and must keep its unit.

Absence is not a statement about origin. It covers a row that never came from a
GAEB import, and also a row that did and whose unit a person has since changed,
because ``update_position`` retires the claim once the value it described is
gone. Both must export their unit. The second shape is exercised end to end in
``test_boq_unit_provenance_lifecycle.py``.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest

from app.modules.boq.importers.gaeb_xml import GAEBXMLImporter
from app.modules.boq.router import build_gaeb_xml

_X84 = Path(__file__).resolve().parents[1] / "fixtures" / "gaeb" / "oce_conformance_x84.x84"


def _pos(ordinal: str, unit: str, metadata: dict | None) -> SimpleNamespace:
    q = Decimal("10")
    r = Decimal("25.00")
    return SimpleNamespace(
        ordinal=ordinal,
        description=f"Position {ordinal}",
        unit=unit,
        quantity=q,
        unit_rate=r,
        total=(q * r).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        metadata=metadata if metadata is not None else {},
    )


def _boq(positions: list[SimpleNamespace]) -> SimpleNamespace:
    direct = sum((p.total for p in positions), Decimal("0.00"))
    return SimpleNamespace(
        name="Unit provenance LV",
        sections=[SimpleNamespace(ordinal="01", description="Abschnitt", positions=positions)],
        positions=[],
        markups=[],
        direct_cost=direct,
        net_total=direct,
        grand_total=direct,
    )


def _qu_by_ordinal(xml: str) -> dict[str, str | None]:
    """Map each Item's RNoPart to its QU text, or None when no QU element."""
    root = ET.fromstring(xml.split("-->", 1)[-1].strip() if xml.lstrip().startswith("<!--") else xml)
    out: dict[str, str | None] = {}
    for el in root.iter():
        if el.tag.split("}", 1)[-1] != "Item":
            continue
        qu = next((c for c in el if c.tag.split("}", 1)[-1] == "QU"), None)
        out[el.get("RNoPart") or ""] = None if qu is None else (qu.text or "")
    return out


def test_a_guessed_unit_is_not_written_into_the_export() -> None:
    """An empty recorded original means the file said nothing. Say nothing."""
    xml = build_gaeb_xml(
        _boq([_pos("001", "lsum", {"gaeb_unit_original": ""})]),
        project_name="P",
        project_currency="EUR",
        gaeb_format="x83",
    )
    assert _qu_by_ordinal(xml)["001"] is None
    assert "psch" not in xml


def test_a_stated_unit_is_still_written() -> None:
    """A recorded original that is non-empty is a fact and must survive."""
    xml = build_gaeb_xml(
        _boq([_pos("001", "m2", {"gaeb_unit_original": "m2"})]),
        project_name="P",
        project_currency="EUR",
        gaeb_format="x83",
    )
    assert _qu_by_ordinal(xml)["001"] == "m2"


def test_a_row_that_never_came_from_gaeb_keeps_its_unit() -> None:
    """No key means no recorded silence to honour, so the unit is exported.

    Both rows here are the never-imported shape, a manual entry and a
    spreadsheet import. Absence also covers a GAEB row whose unit a person
    later changed, which ``test_boq_unit_provenance_lifecycle.py`` exercises.
    This test is the regression guard for reading the metadata with ``.get()``,
    which cannot separate an absent key from an empty one and would strip the
    unit out of every hand-built BOQ the platform exports.
    """
    xml = build_gaeb_xml(
        _boq([_pos("001", "lsum", None), _pos("002", "m3", {"import_source": "sheet.xlsx"})]),
        project_name="P",
        project_currency="EUR",
        gaeb_format="x83",
    )
    got = _qu_by_ordinal(xml)
    assert got["001"] == "psch"
    assert got["002"] == "m3"


def test_the_two_shapes_are_told_apart_in_one_document() -> None:
    """A mixed BOQ keeps the stated units and drops only the guessed ones."""
    xml = build_gaeb_xml(
        _boq(
            [
                _pos("001", "lsum", {"gaeb_unit_original": ""}),
                _pos("002", "m2", {"gaeb_unit_original": "m2"}),
                _pos("003", "pcs", {"gaeb_unit_original": ""}),
            ]
        ),
        project_name="P",
        project_currency="EUR",
        gaeb_format="x83",
    )
    got = _qu_by_ordinal(xml)
    assert got["001"] is None
    assert got["002"] == "m2"
    assert got["003"] is None


@pytest.mark.asyncio
@pytest.mark.skipif(not _X84.exists(), reason="X84 conformance fixture not present")
async def test_a_real_x84_round_trips_without_gaining_a_unit() -> None:
    """The case the whole change is for.

    Import the X84, which states no unit on any of its 27 items, export X83,
    and confirm the export invented nothing. Before this change every one of
    the 27 came out as a stated Pauschalposition.
    """
    imported = await GAEBXMLImporter.parse(_X84.read_bytes())
    items = [p for p in imported.positions if not p.is_section]
    assert len(items) == 27

    positions = [
        SimpleNamespace(
            ordinal=p.ordinal,
            description=p.description,
            unit=p.unit,
            quantity=Decimal(str(p.quantity)),
            unit_rate=Decimal(str(p.unit_rate)),
            total=(Decimal(str(p.quantity)) * Decimal(str(p.unit_rate))).quantize(Decimal("0.01")),
            metadata=p.metadata,
        )
        for p in items
    ]
    xml = build_gaeb_xml(_boq(positions), project_name="P", project_currency="EUR", gaeb_format="x83")

    assert all(qu is None for qu in _qu_by_ordinal(xml).values())
    assert "psch" not in xml


@pytest.mark.asyncio
@pytest.mark.skipif(not _X84.exists(), reason="X84 conformance fixture not present")
async def test_the_x84_export_still_omits_qu_for_its_own_reason() -> None:
    """X84 omits QU on every item regardless, and that is unchanged.

    The two paths now agree for a position imported from an X84, but they
    agree for different reasons: X84 omits QU because the phase has no slot
    for it, X83 omits it because this particular source stated none. An X83
    export of a hand-built BOQ still carries units.
    """
    xml = build_gaeb_xml(
        _boq([_pos("001", "m2", {"gaeb_unit_original": "m2"})]),
        project_name="P",
        project_currency="EUR",
        gaeb_format="x84",
    )
    assert _qu_by_ordinal(xml)["001"] is None
