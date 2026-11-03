"""GAEB DA XML fidelity on a tender LV: Bedarfspositionen, full texts, OZ, X84 return file.

Synthetic fixture ``synthetic_drywall_provis_x83.x83`` carries the structures a
real tender uses: an unpadded OZ under a padded OZ-Maske, ``Provis`` items,
Langtext built of ``Text`` and ``TextComplement`` blocks, a Kurztext under
``CompleteText``, ``CtlgAssign`` to a DIN 276 catalogue and a project header.

Run::

    cd backend
    python -m pytest tests/unit/test_gaeb_fidelity_provis_text_oz.py -q
"""

from __future__ import annotations

import asyncio
import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.boq.gaeb_common import is_excluded_from_total
from app.modules.boq.importers.gaeb_xml import GAEBXMLImporter
from app.modules.boq.router import build_gaeb_xml
from app.modules.boq.service import _leaf_total_base_with_resources

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "gaeb"
_X83 = _FIXTURES / "synthetic_drywall_provis_x83.x83"
_PROFILE = Path(__file__).resolve().parents[2] / "app" / "modules" / "boq" / "gaeb_profile"

# Test prices per OZ; 39.1.1.2 is the Bedarfsposition ohne Gesamtbetrag.
_RATES = {"39.1.1.1": "50", "39.1.1.2": "20", "39.1.1.3": "60", "39.2.1.1": "30"}


def _parse(content: bytes) -> Any:
    return asyncio.run(GAEBXMLImporter.parse(content))


@pytest.fixture(scope="module")
def imported() -> Any:
    return _parse(_X83.read_bytes())


def _items(result: Any) -> list[Any]:
    return [p for p in result.positions if not p.is_section]


def _by_oz(result: Any) -> dict[str, Any]:
    return {p.ordinal: p for p in _items(result)}


# ── Import ─────────────────────────────────────────────────────────────────


def test_oz_is_kept_exactly_as_in_the_file(imported: Any) -> None:
    assert sorted(_by_oz(imported)) == ["39.1.1.1", "39.1.1.2", "39.1.1.3", "39.2.1.1"]
    sections = [p.ordinal for p in imported.positions if p.is_section]
    assert sections == ["39", "39.1", "39.1.1", "39.2", "39.2.1"]


def test_kurztext_under_complete_text_is_the_description(imported: Any) -> None:
    pos = _by_oz(imported)
    assert pos["39.1.1.1"].description == "Staenderwand 125 mm"
    assert pos["39.2.1.1"].description == "Mineralfaserdecke"


def test_langtext_keeps_every_text_block_and_complement(imported: Any) -> None:
    long_text = _by_oz(imported)["39.1.1.1"].metadata["gaeb_long_text"]
    assert long_text == "Leichte Trennwand Bereich 'A'\nDicke '125' mm\nFabrikat '.....' Zeile eins\nZeile zwei"


def test_text_complements_are_kept_with_kind(imported: Any) -> None:
    complements = _by_oz(imported)["39.1.1.1"].metadata["gaeb_text_complements"]
    assert [c["kind"] for c in complements] == ["Owner", "Owner", "Bidder"]
    assert complements[1] == {"mark": "2", "kind": "Owner", "caption": "Dicke", "body": "'125'", "tail": "mm"}


def test_provis_flag_and_source_ids(imported: Any) -> None:
    pos = _by_oz(imported)
    assert pos["39.1.1.2"].metadata["gaeb_provis"] == "WithoutTotal"
    assert pos["39.1.1.3"].metadata["gaeb_provis"] == "WithTotal"
    assert "gaeb_provis" not in pos["39.1.1.1"].metadata
    assert pos["39.1.1.1"].metadata["gaeb_id"] == "IT0001"
    assert pos["39.1.1.1"].metadata["gaeb_rno_parts"] == ["39", "1", "1", "1"]


def test_ctlg_assign_maps_din276_cost_group(imported: Any) -> None:
    pos = _by_oz(imported)["39.1.1.1"]
    assert pos.classification["din276"] == "342"
    codes = {(a["name"], a["code"]) for a in pos.metadata["gaeb_ctlg_assign"]}
    assert ("DIN276-1_08", "342") in codes
    assert ("Leistungsbereichkatalog", "039") in codes


def test_header_is_kept(imported: Any) -> None:
    header = imported.metadata["gaeb_header"]
    assert header["project_number"] == "4711"
    assert header["project_label"] == "Musterstadt, Neubau Lagerhalle"
    assert header["submission_date"] == "2026-12-01"
    assert header["construction_start"] == "2027-03-01"
    assert header["construction_end"] == "2027-08-31"
    assert "Bindefrist" in header["add_texts"][0]["detail"]
    assert header["owner"]["Name1"] == "Muster Immobilien GmbH"
    assert header["remarks"] == [{"section": "39", "id": "RM391", "text": "1. Allgemeines\nAlle Waende bis Rohdecke."}]


def test_units_keep_the_original_string(imported: Any) -> None:
    pos = _by_oz(imported)
    assert pos["39.1.1.2"].metadata["gaeb_unit_original"] == "St"
    assert pos["39.1.1.3"].metadata["gaeb_unit_original"] == "h"


# ── Totals ─────────────────────────────────────────────────────────────────


def test_bedarfsposition_without_total_is_not_summed() -> None:
    without = SimpleNamespace(total="200", quantity="10", metadata={"gaeb_provis": "WithoutTotal"})
    with_total = SimpleNamespace(total="480", quantity="8", metadata={"gaeb_provis": "WithTotal"})
    normal = SimpleNamespace(total="6000", quantity="120", metadata={})
    assert is_excluded_from_total(without)
    assert not is_excluded_from_total(with_total)
    assert _leaf_total_base_with_resources(without, None, "EUR") == Decimal("0")
    assert _leaf_total_base_with_resources(with_total, None, "EUR") == Decimal("480")
    assert _leaf_total_base_with_resources(normal, None, "EUR") == Decimal("6000")


# ── Export ─────────────────────────────────────────────────────────────────


def _bill_from(result: Any) -> SimpleNamespace:
    """A structured bill as the service hands it to the exporter, priced."""
    sections: dict[str, SimpleNamespace] = {}
    for row in result.positions:
        if row.is_section:
            sections[row.ordinal] = SimpleNamespace(
                ordinal=row.ordinal, description=row.description, positions=[], metadata=row.metadata
            )
    direct = Decimal("0")
    for row in _items(result):
        rate = Decimal(_RATES[row.ordinal])
        qty = Decimal(str(row.quantity))
        total = (qty * rate).quantize(Decimal("0.01"))
        pos = SimpleNamespace(
            ordinal=row.ordinal,
            description=row.description,
            unit=row.unit,
            quantity=qty,
            unit_rate=rate,
            total=total,
            metadata=row.metadata,
        )
        sections[row.metadata["gaeb_section"]].positions.append(pos)
        if not is_excluded_from_total(pos):
            direct += total
    return SimpleNamespace(
        name="LV 39",
        sections=list(sections.values()),
        positions=[],
        markups=[],
        direct_cost=direct,
        net_total=direct,
        grand_total=direct,
        metadata={"gaeb_header": result.metadata["gaeb_header"]},
    )


def _local(tag: str) -> str:
    return tag.split("}", 1)[-1]


def _find_all(root: ET.Element, name: str) -> list[ET.Element]:
    return [el for el in root.iter() if _local(el.tag) == name]


def _child(el: ET.Element, name: str) -> ET.Element | None:
    return next((c for c in el if _local(c.tag) == name), None)


@pytest.fixture(scope="module")
def x84(imported: Any) -> str:
    return build_gaeb_xml(_bill_from(imported), project_name="Demo", project_currency="EUR", gaeb_format="x84")


def test_x84_nests_categories_like_the_source(x84: str) -> None:
    root = ET.fromstring(x84)
    for el in _find_all(root, "BoQCtgy") + _find_all(root, "Item"):
        assert "_" not in el.get("RNoPart", ""), el.get("RNoPart")
    item = next(i for i in _find_all(root, "Item") if i.get("ID") == "IT0001")
    assert item.get("RNoPart") == "1"
    parents = {c: p for p in root.iter() for c in p}
    chain: list[str] = []
    node = item
    while node in parents:
        node = parents[node]
        if _local(node.tag) == "BoQCtgy":
            chain.insert(0, node.get("RNoPart"))
    assert chain == ["39", "1", "1"]
    assert {c.get("ID") for c in _find_all(root, "BoQCtgy")} >= {"CT39", "CT391", "CT3911"}


def test_x84_writes_units_provis_and_kurztext(x84: str) -> None:
    root = ET.fromstring(x84)
    items = {i.get("ID"): i for i in _find_all(root, "Item")}
    assert _child(items["IT0001"], "QU").text == "m2"
    assert _child(items["IT0002"], "QU").text == "St"
    assert _child(items["IT0003"], "QU").text == "h"
    assert _child(items["IT0002"], "Provis").text == "WithoutTotal"
    assert _child(items["IT0003"], "Provis").text == "WithTotal"
    assert _child(items["IT0001"], "Provis") is None
    outline = "".join(_find_all(items["IT0004"], "OutlineText")[0].itertext()).strip()
    assert outline == "Mineralfaserdecke"


def test_x84_totals_leave_out_bedarfspositionen(x84: str) -> None:
    root = ET.fromstring(x84)
    info_total = _find_all(_find_all(root, "BoQInfo")[0], "Total")[0].text
    # 120*50 + 8*60 + 45.5*30; the WithoutTotal line (10*20) is not summed.
    assert info_total == "7845.00"
    ctgy = next(c for c in _find_all(root, "BoQCtgy") if c.get("ID") == "CT3911")
    assert _child(_child(ctgy, "Totals"), "Total").text == "6480.00"
    # The item itself still carries its price.
    item = next(i for i in _find_all(root, "Item") if i.get("ID") == "IT0002")
    assert _child(item, "IT").text == "200.00"


def test_x84_header_answers_under_the_issuer_project(x84: str) -> None:
    root = ET.fromstring(x84)
    assert _find_all(root, "NamePrj")[0].text == "4711"
    assert _find_all(root, "OpenDate")[0].text == "2026-12-01"


def test_x84_reimport_is_identical(imported: Any, x84: str) -> None:
    again = _parse(x84.encode("utf-8"))
    first, second = _by_oz(imported), _by_oz(again)
    assert sorted(second) == sorted(first)
    for oz, pos in first.items():
        assert second[oz].unit == pos.unit, oz
        assert second[oz].description == pos.description, oz
        assert second[oz].metadata.get("gaeb_provis") == pos.metadata.get("gaeb_provis"), oz
    assert [p.ordinal for p in again.positions if p.is_section] == ["39", "39.1", "39.1.1", "39.2", "39.2.1"]


def test_x83_reexport_keeps_provis_units_and_long_text(imported: Any) -> None:
    xml = build_gaeb_xml(_bill_from(imported), project_name="Demo", project_currency="EUR", gaeb_format="x83")
    again = _parse(xml.encode("utf-8"))
    first, second = _by_oz(imported), _by_oz(again)
    for oz, pos in first.items():
        assert second[oz].metadata.get("gaeb_unit_original") == pos.metadata["gaeb_unit_original"], oz
        assert second[oz].metadata.get("gaeb_provis") == pos.metadata.get("gaeb_provis"), oz
        assert second[oz].description == pos.description, oz
    assert "Dicke '125' mm" in second["39.1.1.1"].metadata["gaeb_long_text"]


@pytest.mark.parametrize("gaeb_format", ["x83", "x84"])
def test_export_validates_against_profile(imported: Any, gaeb_format: str) -> None:
    etree = pytest.importorskip("lxml.etree")
    dp = "84" if gaeb_format == "x84" else "83"
    schema = etree.XMLSchema(etree.parse(str(_PROFILE / f"oce-gaeb-3.3-x{dp}.xsd")))
    xml = build_gaeb_xml(_bill_from(imported), project_name="Demo", project_currency="EUR", gaeb_format=gaeb_format)
    doc = etree.fromstring(xml.encode("utf-8"))
    assert schema.validate(doc), "; ".join(f"{e.line}:{e.message}" for e in schema.error_log[:8])


# ── Validation rules ───────────────────────────────────────────────────────


def _ctx(positions: list[dict[str, Any]], locale: str = "en") -> Any:
    from app.core.validation.engine import ValidationContext

    return ValidationContext(data={"positions": positions}, metadata={"locale": locale})


def test_rule_lists_priced_bedarfsposition_outside_total() -> None:
    from app.core.validation.rules import GAEBProvisWithoutTotal

    positions = [
        {"id": "a", "ordinal": "39.1.1.2", "total": "200", "metadata": {"gaeb_provis": "WithoutTotal"}},
        {"id": "b", "ordinal": "39.1.1.3", "total": "480", "metadata": {"gaeb_provis": "WithTotal"}},
        {"id": "c", "ordinal": "39.1.1.4", "total": "0", "metadata": {"gaeb_provis": "WithoutTotal"}},
    ]
    results = asyncio.run(GAEBProvisWithoutTotal().validate(_ctx(positions, "de")))
    assert [r.element_ref for r in results] == ["a"]
    assert "39.1.1.2" in results[0].message and "200" in results[0].message
    assert "Bedarfsposition" in results[0].message


def test_rule_flags_oz_changed_against_source() -> None:
    from app.core.validation.rules import GAEBOrdinalChanged

    positions = [
        {"id": "a", "ordinal": "39.01.01.01", "metadata": {"gaeb_ordinal": "39.1.1.1"}},
        {"id": "b", "ordinal": "39.1.1.2", "metadata": {"gaeb_ordinal": "39.1.1.2"}},
        {"id": "c", "ordinal": "7"},
    ]
    results = asyncio.run(GAEBOrdinalChanged().validate(_ctx(positions)))
    assert [(r.element_ref, r.passed) for r in results] == [("a", False), ("b", True)]
    assert "39.1.1.1" in results[0].message


def test_rule_flags_unit_not_gaeb_exportable() -> None:
    from app.core.validation.rules import GAEBUnitExportable

    positions = [
        {"id": "a", "ordinal": "1", "unit": "m2"},
        {"id": "b", "ordinal": "2", "unit": "pcs", "metadata": {"gaeb_unit_original": "St"}},
        {"id": "c", "ordinal": "3", "unit": "Laufmeter"},
    ]
    results = asyncio.run(GAEBUnitExportable().validate(_ctx(positions)))
    assert [(r.element_ref, r.passed) for r in results] == [("a", True), ("b", True), ("c", False)]
    assert "Laufmeter" in results[2].message


def test_unpadded_oz_passes_the_ordinal_mask_rule() -> None:
    from app.core.validation.rules import GAEBOrdinalFormat

    pos = {"id": "1", "ordinal": "39.1.1.1", "metadata": {"gaeb_oz_mask": [2, 2, 2, 2]}}
    assert asyncio.run(GAEBOrdinalFormat().validate(_ctx([pos])))[0].passed
