# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""GAEB X31 (Mengenermittlung): export, import proposal, and refusals.

Pure tests over the builder, the parser and the matcher, with hand-written
files. No app, no database.

What they pin:

* an export read back gives the same quantity for every OZ (round trip),
  through the X8x importer's own OZ assembly;
* an OZ the bill does not have is reported, never dropped and never guessed;
* two positions answering to one OZ are reported as ambiguous;
* rows without a total, an OZ named twice, and section rows are reported;
* the three decimals of ``tgDecimal_11_3`` are what is written;
* an ordinal GAEB cannot spell is left out and said so;
* entity expansion is refused like the X8x importer refuses it;
* a tender phase is not mistaken for a measurement, and the BOQ importer
  refuses an X31 rather than turning it into empty sections.

Run::

    cd backend
    python -m pytest tests/unit/test_gaeb_x31_quantity_determination.py -v
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest

from app.modules.boq.gaeb_x31 import (
    build_x31_xml,
    measured_quantity_of,
    measurement_from_x31,
    parse_x31,
    propose_x31,
)
from app.modules.boq.importers import ImporterParseError
from app.modules.boq.importers.gaeb_xml import GAEBXMLImporter

NS = "{http://www.gaeb.de/GAEB_DA_XML/DA31/3.3}"


def _pos(ordinal: str, qty: str = "0", *, unit: str = "m3", section: bool = False, **meta: object) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"id-{ordinal or 'blank'}-{len(meta)}",
        ordinal=ordinal,
        description=f"Position {ordinal}",
        unit="section" if section else unit,
        quantity=qty,
        unit_rate="0" if section else "10",
        metadata_=dict(meta),
    )


def _is_section(pos: SimpleNamespace) -> bool:
    return pos.unit == "section"


def _by_oz(proposal: dict, key: str = "matched") -> dict[str, dict]:
    return {row["oz"]: row for row in proposal[key]}


# ── Round trip ───────────────────────────────────────────────────────────


def test_export_then_import_preserves_every_quantity_per_oz() -> None:
    entries = [
        ("01.0010", Decimal("125.5")),
        ("01.0020", Decimal("42")),
        ("02.0010", Decimal("88.25")),
        ("02.0020", Decimal("-3.5")),
    ]
    exported = build_x31_xml(entries, boq_name="LV Rohbau", project_name="Neubau")
    assert exported.skipped == []
    assert exported.written == [o for o, _ in entries]

    parsed = parse_x31(exported.xml.encode("utf-8"))
    assert {i.oz: i.quantity for i in parsed.items} == {o: q.quantize(Decimal("0.001")) for o, q in entries}

    positions = [_pos(o, "1") for o, _ in entries]
    proposal = propose_x31(parsed, positions, is_section=_is_section)
    assert proposal["unmatched"] == []
    matched = _by_oz(proposal)
    assert {oz: Decimal(row["proposed_quantity"]) for oz, row in matched.items()} == {
        o: q.quantize(Decimal("0.001")) for o, q in entries
    }
    assert all(row["matched_via"] == "ordinal" for row in matched.values())


def test_round_trip_survives_the_importers_zero_padding() -> None:
    """``1.10`` is written under a mask; the reader pads it; the matcher still finds it."""
    exported = build_x31_xml(
        [("1.10", Decimal("5")), ("1.200", Decimal("6")), ("12.3", Decimal("7"))],
        boq_name="LV",
        project_name="P",
    )
    parsed = parse_x31(exported.xml.encode("utf-8"))
    # The reader pads numeric parts to the mask widths (2 and 3).
    assert sorted(i.oz for i in parsed.items) == ["01.010", "01.200", "12.003"]
    positions = [_pos("1.10"), _pos("1.200"), _pos("12.3")]
    proposal = propose_x31(parsed, positions, is_section=_is_section)
    assert proposal["unmatched"] == []
    by_ordinal = {row["ordinal"]: Decimal(row["proposed_quantity"]) for row in proposal["matched"]}
    assert by_ordinal == {"1.10": Decimal("5"), "1.200": Decimal("6"), "12.3": Decimal("7")}
    assert {row["matched_via"] for row in proposal["matched"]} == {"normalized"}


def test_quantity_is_written_with_three_decimals() -> None:
    exported = build_x31_xml([("01.0010", Decimal("1.23456"))], boq_name="LV", project_name="P")
    qty = ET.fromstring(exported.xml).find(f".//{NS}Item/{NS}QtyDeterm/{NS}Qty")
    assert qty is not None and qty.text == "1.235"


def test_document_follows_the_x31_element_order() -> None:
    exported = build_x31_xml([("01.0010", Decimal("1"))], boq_name="LV", project_name="P")
    root = ET.fromstring(exported.xml)
    assert root.tag == f"{NS}GAEB"
    assert [child.tag for child in root] == [f"{NS}GAEBInfo", f"{NS}QtyDeterm"]
    qd = root.find(f"{NS}QtyDeterm")
    assert qd is not None
    assert [child.tag for child in qd] == [f"{NS}PrjInfo", f"{NS}QtyDetermInfo", f"{NS}DP", f"{NS}BoQ"]
    assert qd.findtext(f"{NS}DP") == "31"
    assert qd.findtext(f"{NS}QtyDetermInfo/{NS}MethodDescription") == "REB23003-2009"
    # No price and no text: X31 carries quantities only.
    assert root.find(f".//{NS}UP") is None
    assert root.find(f".//{NS}Description") is None


def test_unwritable_ordinals_are_left_out_and_reported() -> None:
    exported = build_x31_xml(
        [
            ("01.0010", Decimal("1")),
            ("01.0050", Decimal("1")),
            ("01.0060", Decimal("1")),
            ("A/3", Decimal("2")),  # a slash has no GAEB spelling
            ("0030", Decimal("3")),  # another depth than the rest
            ("01.0010", Decimal("4")),  # named twice
            ("", Decimal("5")),
            ("01.0040", Decimal("123456789")),  # beyond tgDecimal_11_3
        ],
        boq_name="LV",
        project_name="P",
    )
    reasons = {(s["ordinal"], s["reason"]) for s in exported.skipped}
    assert ("A/3", "ordinal_not_representable") in reasons
    assert ("0030", "ordinal_depth_mismatch") in reasons
    assert ("01.0010", "duplicate_ordinal") in reasons
    assert ("", "empty_ordinal") in reasons
    assert ("01.0040", "quantity_out_of_range") in reasons
    # Both occurrences of a doubled OZ are left out: either could be the right one.
    assert exported.written == ["01.0050", "01.0060"]


# ── Proposal ─────────────────────────────────────────────────────────────

_X31_BY_HAND = b"""<?xml version="1.0" encoding="UTF-8"?>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA31/3.3">
  <GAEBInfo><Version>3.3</Version><VersDate>2021-05</VersDate><Date>2026-09-30</Date></GAEBInfo>
  <QtyDeterm>
    <PrjInfo><RefPrjName>Neubau Kita</RefPrjName></PrjInfo>
    <QtyDetermInfo>
      <MethodDescription>REB23003-2009</MethodDescription>
      <ServiceProvisionStartDate>2026-09-01</ServiceProvisionStartDate>
      <ServiceProvisionEndDate>2026-09-30</ServiceProvisionEndDate>
    </QtyDetermInfo>
    <DP>31</DP>
    <BoQ ID="B1">
      <RefBoQName>LV Rohbau</RefBoQName>
      <BoQBkdn><Type>BoQLevel</Type><Length>2</Length><Num>Yes</Num></BoQBkdn>
      <BoQBkdn><Type>Item</Type><Length>4</Length><Num>Yes</Num></BoQBkdn>
      <BoQBody>
        <BoQCtgy ID="C01" RNoPart="01">
          <BoQBody>
            <Itemlist>
              <Item ID="I1" RNoPart="0010">
                <QtyDeterm>
                  <Qty>125.500</Qty>
                  <QDetermItem><QTakeoff Row="           Fund A   10 5,00*3,20*0,75=                              0001A0      "/></QDetermItem>
                  <QDetermItem><QTakeoff Row="           Fund B   10 4,00*3,20*0,75=                              0001A1      "/></QDetermItem>
                </QtyDeterm>
              </Item>
              <Item ID="I2" RNoPart="0020"><QtyDeterm><Qty>42.000</Qty></QtyDeterm></Item>
              <Item ID="I3" RNoPart="0030">
                <QtyDeterm>
                  <QDetermItem><QTakeoff Row="           Wand N   10 12,50*3,00=                                  0002A0      "/></QDetermItem>
                </QtyDeterm>
              </Item>
            </Itemlist>
          </BoQBody>
        </BoQCtgy>
        <BoQCtgy ID="C09" RNoPart="09">
          <BoQBody>
            <Itemlist><Item ID="I9" RNoPart="0010"><QtyDeterm><Qty>7.000</Qty></QtyDeterm></Item></Itemlist>
          </BoQBody>
        </BoQCtgy>
      </BoQBody>
    </BoQ>
  </QtyDeterm>
</GAEB>
"""


def test_proposal_reports_unknown_oz_and_rows_without_total() -> None:
    parsed = parse_x31(_X31_BY_HAND)
    assert parsed.method == "REB23003-2009"
    assert parsed.project_name == "Neubau Kita"
    positions = [
        _pos("01", section=True),
        _pos("01.0010", "120"),
        _pos("01.0020", "40", measurement={"unit": "m3", "lines": [{"formula": "40"}]}),
        _pos("01.0030", "37.5"),
        _pos("01.0040", "10"),
    ]
    proposal = propose_x31(parsed, positions, is_section=_is_section)

    matched = _by_oz(proposal)
    assert set(matched) == {"01.0010", "01.0020"}
    first = matched["01.0010"]
    assert first["proposed_quantity"] == "125.500"
    assert first["current_quantity"] == "120.000"
    assert first["difference_to_quantity"] == "5.500"
    assert first["current_measured_quantity"] is None
    assert first["row_count"] == 2 and len(first["rows"]) == 2
    second = matched["01.0020"]
    assert second["current_measured_quantity"] == "40.000"
    assert second["unchanged"] is False

    unmatched = _by_oz(proposal, "unmatched")
    assert unmatched["09.0010"]["reason"] == "unknown_oz"
    assert unmatched["09.0010"]["quantity"] == "7.000"
    assert unmatched["01.0030"]["reason"] == "rows_without_total"
    assert unmatched["01.0030"]["row_count"] == 1
    # Four measurable positions, two proposed: the other two stay as they are.
    assert proposal["positions_not_in_file"] == 2


def test_ambiguous_oz_is_reported_and_no_position_is_picked() -> None:
    parsed = parse_x31(_X31_BY_HAND)
    positions = [_pos("1.10", "1"), _pos("01.010", "2"), _pos("01.0020", "3")]
    proposal = propose_x31(parsed, positions, is_section=_is_section)
    unmatched = _by_oz(proposal, "unmatched")
    assert unmatched["01.0010"]["reason"] == "ambiguous_oz"
    assert sorted(unmatched["01.0010"]["candidates"]) == ["01.010", "1.10"]
    assert "01.0010" not in _by_oz(proposal)


def test_the_oz_a_gaeb_import_recorded_is_matched() -> None:
    parsed = parse_x31(_X31_BY_HAND)
    positions = [_pos("10", "1", gaeb_ordinal="01.0020")]
    proposal = propose_x31(parsed, positions, is_section=_is_section)
    matched = _by_oz(proposal)
    assert matched["01.0020"]["ordinal"] == "10"
    assert matched["01.0020"]["matched_via"] == "gaeb_ordinal"


def test_an_oz_named_twice_in_the_file_is_not_proposed() -> None:
    doubled = _X31_BY_HAND.replace(b'RNoPart="0020"', b'RNoPart="0010"')
    parsed = parse_x31(doubled)
    proposal = propose_x31(parsed, [_pos("01.0010", "1")], is_section=_is_section)
    assert proposal["matched"] == []
    reasons = [row["reason"] for row in proposal["unmatched"] if row["oz"] == "01.0010"]
    assert reasons == ["duplicate_oz_in_file", "duplicate_oz_in_file"]


def test_section_rows_never_take_a_quantity() -> None:
    parsed = parse_x31(_X31_BY_HAND)
    proposal = propose_x31(parsed, [_pos("01.0010", section=True)], is_section=_is_section)
    assert _by_oz(proposal, "unmatched")["01.0010"]["reason"] == "unknown_oz"


def test_itemlist_directly_under_a_category_is_read() -> None:
    """Some writers drop the inner BoQBody; the OZ must come out the same."""
    loose = _X31_BY_HAND.replace(
        b'<BoQCtgy ID="C09" RNoPart="09">\n          <BoQBody>', b'<BoQCtgy ID="C09" RNoPart="09">'
    )
    loose = loose.replace(
        b"</Itemlist>\n          </BoQBody>\n        </BoQCtgy>\n      </BoQBody>",
        b"</Itemlist>\n        </BoQCtgy>\n      </BoQBody>",
    )
    parsed = parse_x31(loose)
    assert {i.oz for i in parsed.items} >= {"09.0010"}


# ── What a confirmed proposal becomes ───────────────────────────────────


def test_confirmed_quantity_becomes_a_one_line_measurement_sheet() -> None:
    sheet = measurement_from_x31(
        Decimal("125.5"), unit="m3", file_name="aufmass.x31", oz="01.0010", rows=["row a", "row b"]
    )
    position = _pos("01.0010", "120", measurement=sheet)
    assert measured_quantity_of(position) == Decimal("125.500")
    assert sheet["gaeb_x31"]["row_count"] == 2
    # Same input, same sheet: confirming a file twice changes nothing.
    again = measurement_from_x31(
        Decimal("125.5"), unit="m3", file_name="aufmass.x31", oz="01.0010", rows=["row a", "row b"]
    )
    assert again == sheet


def test_negative_measured_quantity_survives_the_sheet() -> None:
    sheet = measurement_from_x31(Decimal("-2.25"), unit="m2", file_name="f.x31", oz="1", rows=[])
    assert measured_quantity_of(_pos("1", measurement=sheet)) == Decimal("-2.250")


# ── Refusals ─────────────────────────────────────────────────────────────

_BILLION_LAUGHS = b"""<?xml version="1.0"?>
<!DOCTYPE lolz [
  <!ENTITY lol "lol">
  <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
  <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
]>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA31/3.3"><QtyDeterm><DP>&lol3;</DP></QtyDeterm></GAEB>
"""

_EXTERNAL_ENTITY = b"""<?xml version="1.0"?>
<!DOCTYPE GAEB [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA31/3.3"><QtyDeterm><DP>&xxe;</DP></QtyDeterm></GAEB>
"""


@pytest.mark.parametrize("payload", [_BILLION_LAUGHS, _EXTERNAL_ENTITY], ids=["entity-expansion", "external-entity"])
def test_entity_tricks_are_refused_like_the_x8x_importer_refuses_them(payload: bytes) -> None:
    with pytest.raises(ImporterParseError, match="security parser"):
        parse_x31(payload)


@pytest.mark.parametrize("payload", [_BILLION_LAUGHS, _EXTERNAL_ENTITY], ids=["entity-expansion", "external-entity"])
async def test_the_x8x_importer_refuses_the_same_payloads(payload: bytes) -> None:
    """The baseline the X31 reader is held to: the existing importer's refusal."""
    with pytest.raises(ImporterParseError, match="security parser"):
        await GAEBXMLImporter.parse(payload)


def test_a_tender_phase_is_not_read_as_a_measurement() -> None:
    x83 = b"""<?xml version="1.0"?><GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA83/3.3">
    <GAEBInfo><Version>3.3</Version></GAEBInfo><Award><DP>83</DP><BoQ ID="b"><BoQBody/></BoQ></Award></GAEB>"""
    with pytest.raises(ImporterParseError, match="X83"):
        parse_x31(x83)


def test_empty_and_malformed_uploads_are_refused() -> None:
    with pytest.raises(ImporterParseError, match="empty"):
        parse_x31(b"")
    with pytest.raises(ImporterParseError, match="Failed to parse"):
        parse_x31(b"<GAEB><QtyDeterm>")


async def test_the_bill_importer_refuses_an_x31_instead_of_making_empty_sections() -> None:
    assert GAEBXMLImporter.detect(_X31_BY_HAND[:4096], "aufmass.x31") is True
    with pytest.raises(ImporterParseError, match="X31"):
        await GAEBXMLImporter.parse(_X31_BY_HAND)


async def test_the_bill_importer_still_reads_a_tender_file() -> None:
    """The guard must not catch the phases it exists to let through."""
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "gaeb" / "oce_conformance_x83.x83"
    result = await GAEBXMLImporter.parse(fixture.read_bytes())
    assert any(not p.is_section for p in result.positions)


# ── The schema GAEB publishes (opt-in) ──────────────────────────────────


def test_published_x31_schema_accepts_the_export() -> None:
    """Validated against GAEB's own X31 schema when a local copy is provided.

    Set ``GAEB_XSD_DIR`` to a directory holding
    ``GAEB_DA_XML_31_3.3_2021-05.xsd`` and its ``GAEB_DA_XML_Lib_3.3_2021-05.xsd``.
    The schema is not redistributed with this repository.
    """
    etree = pytest.importorskip("lxml.etree")
    directory = os.environ.get("GAEB_XSD_DIR", "")
    xsd = Path(directory) / "GAEB_DA_XML_31_3.3_2021-05.xsd"
    if not directory or not xsd.exists():
        pytest.skip("GAEB_XSD_DIR does not hold the published X31 schema")
    parser = etree.XMLParser(load_dtd=False, no_network=True)
    schema = etree.XMLSchema(etree.parse(str(xsd), parser))
    exported = build_x31_xml(
        [("01.0010", Decimal("125.5")), ("01.0020", Decimal("42")), ("02.0010", Decimal("-1"))],
        boq_name="LV Rohbau mit langem Namen",
        project_name="P",
    )
    assert schema.validate(etree.fromstring(exported.xml.encode("utf-8"))), [str(e) for e in schema.error_log][:5]
    assert schema.validate(etree.fromstring(_X31_BY_HAND)), [str(e) for e in schema.error_log][:5]


# ── Indexpositionen ──────────────────────────────────────────────────────


def test_an_index_position_is_written_with_rnoindex_and_reads_back_to_its_oz() -> None:
    """A bill imported from an X83 with Indexpositionen exports their measured quantities too."""
    exported = build_x31_xml(
        [("01.0010", Decimal("5")), ("01.0020", Decimal("6")), ("01.0020.A", Decimal("7"))],
        boq_name="LV",
        project_name="P",
    )
    assert exported.skipped == []
    assert exported.written == ["01.0010", "01.0020", "01.0020.A"]
    items = ET.fromstring(exported.xml).findall(f".//{NS}Item")
    assert [(i.get("RNoPart"), i.get("RNoIndex")) for i in items] == [("0010", None), ("0020", None), ("0020", "A")]
    bkdn_types = [b.findtext(f"{NS}Type") for b in ET.fromstring(exported.xml).iter(f"{NS}BoQBkdn")]
    assert bkdn_types == ["BoQLevel", "Item", "Index"]
    parsed = parse_x31(exported.xml.encode("utf-8"))
    assert [(i.oz, i.quantity) for i in parsed.items] == [
        ("01.0010", Decimal("5.000")),
        ("01.0020", Decimal("6.000")),
        ("01.0020.A", Decimal("7.000")),
    ]


def test_a_bill_of_mostly_index_positions_keeps_the_depth_of_its_base_positions() -> None:
    """Three indexed OZ outnumber the one plain OZ, yet the plain one is not rejected as too shallow."""
    entries = [
        ("01.0010", Decimal("1")),
        ("01.0020.A", Decimal("2")),
        ("01.0020.B", Decimal("3")),
        ("01.0030.A", Decimal("4")),
    ]
    exported = build_x31_xml(entries, boq_name="LV", project_name="P")
    assert exported.skipped == []
    parsed = parse_x31(exported.xml.encode("utf-8"))
    assert [i.oz for i in parsed.items] == [o for o, _ in entries]


def test_an_index_the_import_recorded_is_used_even_when_it_does_not_look_like_one() -> None:
    entries = [("01.0010", Decimal("1")), ("01.0010.X1", Decimal("2"))]
    # Unrecorded, X1 reads as a third level, and one of the two OZ cannot share the other's depth.
    guessed = build_x31_xml(entries, boq_name="LV", project_name="P")
    assert len(guessed.skipped) == 1
    recorded = build_x31_xml(entries, boq_name="LV", project_name="P", index_of={"01.0010.X1": "X1"})
    assert recorded.skipped == []
    assert [i.oz for i in parse_x31(recorded.xml.encode("utf-8")).items] == ["01.0010", "01.0010.X1"]


# ── What an apply would replace ──────────────────────────────────────────


def test_a_proposal_says_how_many_take_off_lines_applying_would_replace() -> None:
    take_off = {
        "unit": "m3",
        "lines": [
            {"description": "Fund A", "formula": "5*3.2*0.75"},
            {"description": "Fund B", "formula": "4*3.2*0.75"},
            {"description": "Fund C", "formula": "2*3.2*0.75"},
        ],
    }
    hand_measured = _pos("01.0010", "100", measurement=take_off)
    hand_measured.version = 4
    from_x31 = _pos(
        "01.0020",
        "40",
        measurement=measurement_from_x31(Decimal("40"), unit="t", file_name="a.x31", oz="01.0020", rows=[]),
    )
    proposal = propose_x31(parse_x31(_X31_BY_HAND), [hand_measured, from_x31], is_section=_is_section)
    rows = _by_oz(proposal)
    assert rows["01.0010"]["current_sheet_lines"] == 3
    assert rows["01.0010"]["current_sheet_source"] == "manual"
    assert rows["01.0010"]["position_version"] == 4
    assert rows["01.0020"]["current_sheet_lines"] == 1
    assert rows["01.0020"]["current_sheet_source"] == "gaeb_x31"
    # A SimpleNamespace without a version column carries none.
    assert rows["01.0020"]["position_version"] is None


def test_a_control_character_in_a_name_does_not_break_the_file() -> None:
    exported = build_x31_xml([("01.0010", Decimal("1"))], boq_name="LV\x0bRohbau", project_name="Kita\x01 Nord")
    root = ET.fromstring(exported.xml)
    assert root.findtext(f"{NS}QtyDeterm/{NS}PrjInfo/{NS}RefPrjName") == "Kita Nord"
    assert parse_x31(exported.xml.encode("utf-8")).boq_name == "LVRohbau"
