# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The Frankfurt Rohbau X83 fixture: schema-valid, realistic, fully imported.

``frankfurt_rohbau_x83.x83`` is the everyday-shaped companion to the
conformance fixture: a clean German Angebotsaufforderung (X83, DA83/3.3)
for "Bürogebäude Frankfurt Europaviertel" - one Gewerk (Rohbau), 21 positions
with real German construction texts, m2/m3/psch/St/kg units, non-round
quantities and NO prices. These tests pin that the fixture

* validates against the GAEB 3.3 profile schema we ship,
* imports completely (21/21 items) with the phase read from ``Award/DP``,
* keeps its German texts, units and quantities intact, and
* carries no prices and no company names (it is a tender request).

Run::

    cd backend
    python -m pytest tests/unit/test_gaeb_frankfurt_fixture.py -v --tb=short
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from app.modules.boq.importers.gaeb_xml import GAEBXMLImporter

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "gaeb" / "frankfurt_rohbau_x83.x83"

_EXPECTED_ITEMS = 21


@pytest.fixture(scope="module")
def frankfurt_result():
    import asyncio

    return asyncio.run(GAEBXMLImporter.parse(_FIXTURE.read_bytes()))


def _items(result) -> list:
    return [p for p in result.positions if not p.is_section]


def test_fixture_validates_against_gaeb_33_xsd() -> None:
    """The authored file passes the X83 3.3 profile schema we ship."""
    etree = pytest.importorskip("lxml.etree")

    from tests.unit.test_gaeb_export_xsd import _load_schema

    schema = _load_schema("83")
    doc = etree.parse(str(_FIXTURE))
    assert schema.validate(doc), "Frankfurt X83 fixture failed XSD validation: " + "; ".join(
        f"{e.line}:{e.message}" for e in schema.error_log[:10]
    )


def test_all_positions_import(frankfurt_result) -> None:
    """All 21 positions import; nothing skipped, nothing errored."""
    items = _items(frankfurt_result)
    assert len(items) == _EXPECTED_ITEMS
    assert frankfurt_result.errors == []
    assert frankfurt_result.skipped == 0
    ordinals = [p.ordinal for p in items]
    assert len(set(ordinals)) == _EXPECTED_ITEMS, "ordinals must be distinct"


def test_phase_and_currency_from_the_file(frankfurt_result) -> None:
    """X83 detected from Award/DP (unpriced file, so no price heuristic works)."""
    assert frankfurt_result.metadata["da_kind"] == "x83"
    assert frankfurt_result.currency == "EUR"


def test_single_gewerk_rohbau(frankfurt_result) -> None:
    """One Gewerk: every item OZ sits under the top-level '01' (Rohbau)."""
    sections = {s.ordinal: s for s in frankfurt_result.positions if s.is_section}
    assert sections["01"].description == "Rohbau"
    for pos in _items(frankfurt_result):
        assert pos.ordinal.startswith("01."), f"{pos.ordinal} escaped the Rohbau Gewerk"


def test_units_and_nonround_quantities(frankfurt_result) -> None:
    """m2/m3/psch/St/kg survive (psch -> lsum, St -> pcs internal tokens)."""
    items = _items(frankfurt_result)
    assert {p.unit for p in items} == {"m2", "m3", "lsum", "pcs", "kg"}
    quantities = {Decimal(str(p.quantity)) for p in items}
    # The camera-friendly non-round Mengen of the brief.
    assert Decimal("386.5") in quantities
    assert Decimal("57522.5") in quantities
    assert Decimal("1212.75") in quantities


def test_german_texts_survive(frankfurt_result) -> None:
    """Real German construction wording, umlauts intact."""
    blob = "\n".join(p.description for p in _items(frankfurt_result))
    for term in ("Bewehrung", "Schalung", "Ortbeton C25/30", "Kalksandstein", "Abdichtung"):
        assert term in blob, f"expected German term {term!r} in imported descriptions"
    assert "Wände" in blob, "umlauts must survive the import"


def test_unpriced_and_anonymous(frankfurt_result) -> None:
    """An Angebotsaufforderung: no prices; and the file names no company."""
    for pos in _items(frankfurt_result):
        assert pos.unit_rate == 0.0, f"{pos.ordinal} carries a price in an unpriced X83"
    raw = _FIXTURE.read_text(encoding="utf-8")
    for tag in ("<CTR", "<OWN", "<Bidder"):
        assert tag not in raw, f"fixture must not name a company ({tag})"
