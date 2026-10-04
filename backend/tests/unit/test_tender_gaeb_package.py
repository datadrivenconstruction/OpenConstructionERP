# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The GAEB call for bids of one tender package holds exactly the package's lines.

The tender page sent the whole source bill as X83, so a bidder asked to price
the drywall also received the earthworks and the concrete. The package export
narrows the bill to the package's scope and hands it to the same GAEB writer,
so it must still validate as DP 83 and still carry no price.

The scope comes from package metadata in the shape ``create_from_boq`` writes:
a ``line_item_template`` holding the chosen section header and every row under
it.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

etree = pytest.importorskip("lxml.etree")

from app.modules.boq.router import build_gaeb_xml
from app.modules.tendering.gaeb_package import package_bill, package_line_ids
from tests.unit.test_gaeb_export_xsd import _assert_validates, _load_official_schema, _pos


def _with_id(pos: SimpleNamespace, parent_id: uuid.UUID | None) -> SimpleNamespace:
    pos.id = uuid.uuid4()
    pos.parent_id = parent_id
    return pos


def _bill() -> tuple[SimpleNamespace, list[SimpleNamespace], dict]:
    """A two-section bill, a package over the second section, and that package's metadata."""
    earth = SimpleNamespace(id=uuid.uuid4(), parent_id=None, ordinal="01", description="Erdarbeiten", unit="")
    concrete = SimpleNamespace(id=uuid.uuid4(), parent_id=None, ordinal="02", description="Betonarbeiten", unit="")
    earth_lines = [
        _with_id(_pos("01.001", "Mutterboden abtragen", "m3", "250", "12.50"), earth.id),
        _with_id(_pos("01.002", "Baugrube ausheben", "m3", "480", "18.75"), earth.id),
    ]
    concrete_lines = [
        _with_id(_pos("02.001", "Stahlbeton C30/37 Bodenplatte", "m3", "12.5", "168.40"), concrete.id),
        _with_id(_pos("02.002", "Baustelleneinrichtung", "lsum", "1", "9500.00"), concrete.id),
    ]
    structured = SimpleNamespace(
        name="Demo LV",
        sections=[
            SimpleNamespace(id=earth.id, ordinal="01", description="Erdarbeiten", positions=earth_lines),
            SimpleNamespace(id=concrete.id, ordinal="02", description="Betonarbeiten", positions=concrete_lines),
        ],
        positions=[],
        markups=[SimpleNamespace(name="BGK", percentage=10.0, amount=100, is_active=True)],
        direct_cost=0,
        net_total=0,
    )
    flat = [earth, *earth_lines, concrete, *concrete_lines]
    metadata = {"line_item_template": [{"position_id": str(p.id)} for p in (concrete, *concrete_lines)]}
    return structured, flat, metadata


def _local_names(xml: str) -> list[str]:
    return [etree.QName(el).localname for el in etree.fromstring(xml.encode("utf-8")).iter() if isinstance(el.tag, str)]


def test_the_package_x83_holds_only_the_package_lines() -> None:
    structured, flat, metadata = _bill()
    bill = package_bill(structured, package_line_ids(flat, metadata))

    xml = build_gaeb_xml(bill, project_name="XSD Demo", project_currency="EUR", gaeb_format="x83")

    names = _local_names(xml)
    assert names.count("Item") == 2, "the two concrete lines, nothing of the earthworks"
    assert names.count("BoQCtgy") == 1, "the earthworks section has no line of the package and is left out"
    assert "Stahlbeton C30/37 Bodenplatte" in xml
    assert "Baustelleneinrichtung" in xml
    assert "Mutterboden" not in xml
    assert "Erdarbeiten" not in xml


def test_the_package_x83_carries_no_price() -> None:
    structured, flat, metadata = _bill()
    bill = package_bill(structured, package_line_ids(flat, metadata))

    names = _local_names(build_gaeb_xml(bill, project_name="XSD Demo", project_currency="EUR", gaeb_format="x83"))

    for priced in ("UP", "IT", "MarkupItem", "Totals"):
        assert priced not in names, priced


def test_the_package_x83_validates_against_our_profile_schema() -> None:
    structured, flat, metadata = _bill()
    _assert_validates(package_bill(structured, package_line_ids(flat, metadata)), "x83")


def test_the_package_x83_validates_against_the_published_schema() -> None:
    structured, flat, metadata = _bill()
    bill = package_bill(structured, package_line_ids(flat, metadata))
    schema = _load_official_schema("83")
    doc = etree.fromstring(
        build_gaeb_xml(bill, project_name="XSD Demo", project_currency="EUR", gaeb_format="x83").encode("utf-8")
    )
    assert schema.validate(doc), "; ".join(f"{e.line}:{e.message}" for e in schema.error_log[:8])


def test_a_package_without_a_scope_sends_the_whole_bill() -> None:
    structured, flat, _ = _bill()
    bill = package_bill(structured, package_line_ids(flat, {}))

    names = _local_names(build_gaeb_xml(bill, project_name="XSD Demo", project_currency="EUR", gaeb_format="x83"))

    assert names.count("Item") == 4
    assert names.count("BoQCtgy") == 2


def test_ungrouped_lines_are_narrowed_too() -> None:
    structured, flat, metadata = _bill()
    loose_in = _with_id(_pos("90", "Bauschild", "pcs", "1", "300"), None)
    loose_out = _with_id(_pos("91", "Bauzaun", "m", "120", "8"), None)
    structured.positions = [loose_in, loose_out]
    flat += [loose_in, loose_out]
    metadata["line_item_template"].append({"position_id": str(loose_in.id)})

    bill = package_bill(structured, package_line_ids(flat, metadata))

    assert [p.description for p in bill.positions] == ["Bauschild"]
    _assert_validates(bill, "x83")
