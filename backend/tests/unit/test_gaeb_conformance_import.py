# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠GAEB importer regression against the in-house X83 conformance fixture.

``oce_conformance_x83.x83`` is written by us (see
scripts/generate_gaeb_conformance_fixtures.py) and deliberately stresses the
corners a real-world LV can hit. Each maps to a bug class the audit found in
a client-side import path:

* **Indexpositionen** - four items carry ``RNoIndex`` (``"1"``, ``"A"``,
  ``"y"``, ``"z"``). The index is PART of the OZ (Ordnungszahl): dropping it
  collapses distinct positions onto one ordinal and the persistence layer
  correctly answers 409. The importer must deliver ALL 27 positions with
  distinct ordinals.
* **Embedded graphics** - one Langtext carries an inline base64 JPEG
  (~56k chars). The graphic must be stripped (the text kept) and the
  description capped so the 5000-char position schema never rejects the row.
* **Phase detection** - the file is an X83 (Angebotsaufforderung / call for
  bids, ``Award/DP == 83``). Detection must read the DP / namespace, never
  infer the phase from the presence of prices (the file is unpriced, so a
  price heuristic would misreport it as X81).
* **Bedarfspositionen** - three items carry ``Provis`` and no price at all,
  which the validators used to report as pricing errors.

The tests drive the pure importer directly (no app / DB), so they run
anywhere.

Run::

    cd backend
    python -m pytest tests/unit/test_gaeb_conformance_import.py -v --tb=short
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.modules.boq.importers.gaeb_xml import GAEBXMLImporter

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "gaeb" / "oce_conformance_x83.x83"

# First bytes of the base64-encoded JPEG embedded in the fixture's Langtext.
_JPEG_B64_MARKER = "/9j/4AAQ"

# The four Indexpositionen of the fixture: same RNoPart as their base
# position, distinguished ONLY by RNoIndex.
_INDEXED_OZS = (
    "001.001.0010.1",
    "001.001.0010.A",
    "999.999.9999.y",
    "999.999.9999.z",
)


@pytest.fixture(scope="module")
def conformance_result():
    import asyncio

    content = _FIXTURE.read_bytes()
    return asyncio.run(GAEBXMLImporter.parse(content))


def _items(result) -> list:
    return [p for p in result.positions if not p.is_section]


class TestConformanceAllPositions:
    def test_all_27_positions_imported(self, conformance_result) -> None:
        """The conformance fixture yields ALL 27 items, no errors."""
        items = _items(conformance_result)
        assert len(items) == 27, f"expected 27 items, got {len(items)}"
        assert conformance_result.errors == []
        assert conformance_result.skipped == 0

    def test_rno_index_is_part_of_the_oz(self, conformance_result) -> None:
        """Indexpositionen keep their RNoIndex suffix: 27 DISTINCT ordinals."""
        ordinals = [p.ordinal for p in _items(conformance_result)]
        assert len(set(ordinals)) == len(ordinals), (
            "duplicate ordinals - RNoIndex was dropped from the OZ: "
            + ", ".join(sorted({o for o in ordinals if ordinals.count(o) > 1}))
        )
        for oz in _INDEXED_OZS:
            assert oz in ordinals, f"Indexposition {oz} missing from import"

    def test_rno_index_recorded_in_metadata(self, conformance_result) -> None:
        """Each Indexposition carries its raw index for round-trip export."""
        by_ordinal = {p.ordinal: p for p in _items(conformance_result)}
        for oz in _INDEXED_OZS:
            index = oz.rsplit(".", 1)[-1]
            assert by_ordinal[oz].metadata.get("gaeb_rno_index") == index


class TestConformancePhaseDetection:
    def test_x83_detected_as_x83(self, conformance_result) -> None:
        """Phase comes from Award/DP (83), never from the absence of prices.

        The fixture is unpriced, so a "has prices => X83, else X81"
        heuristic would misreport it. The importer must say x83.
        """
        assert conformance_result.metadata["da_kind"] == "x83"
        assert _items(conformance_result)[0].metadata["gaeb_da_kind"] == "x83"


class TestConformanceEmbeddedGraphics:
    def test_base64_blob_never_reaches_description(self, conformance_result) -> None:
        """The inline JPEG is stripped from every description."""
        for pos in conformance_result.positions:
            assert _JPEG_B64_MARKER not in (pos.description or ""), (
                f"base64 graphic leaked into description of {pos.ordinal}"
            )

    def test_base64_blob_never_reaches_metadata(self, conformance_result) -> None:
        """The inline JPEG does not hide in long-text / rich-text metadata."""
        for pos in conformance_result.positions:
            meta_json = json.dumps(pos.metadata, default=str)
            assert _JPEG_B64_MARKER not in meta_json, f"base64 graphic leaked into metadata of {pos.ordinal}"

    def test_graphic_item_keeps_its_text(self, conformance_result) -> None:
        """Stripping the graphic must not throw away the human text with it."""
        by_ordinal = {p.ordinal: p for p in _items(conformance_result)}
        # 001.002.0010 is the item whose Langtext embeds the graphic.
        item = by_ordinal["001.002.0010"]
        assert item.description.startswith("Sohlplatte in Ortbeton")
        assert len(item.description) > 40

    def test_descriptions_fit_the_position_schema(self, conformance_result) -> None:
        """No description exceeds the 5000-char PositionCreate cap (422 class)."""
        for pos in conformance_result.positions:
            assert len(pos.description or "") <= 5000, f"description of {pos.ordinal} is {len(pos.description)} chars"


# ── Synthetic corner cases (no fixture dependency) ───────────────────────────

_XML_HEAD = b"""<?xml version="1.0" encoding="UTF-8"?>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA83/3.3">
  <GAEBInfo><Version>3.3</Version></GAEBInfo>
  <Award>
    <DP>83</DP>
    <AwardInfo><Cur>EUR</Cur></AwardInfo>
    <BoQ ID="idBoQ">
      <BoQInfo><Name>LV</Name></BoQInfo>
      <BoQBody>
        <Itemlist>
"""

_XML_TAIL = b"""
        </Itemlist>
      </BoQBody>
    </BoQ>
  </Award>
</GAEB>
"""


@pytest.mark.asyncio
async def test_oversized_langtext_is_capped_not_rejected() -> None:
    """A pathological Langtext longer than the schema cap is truncated.

    The text survives (truncated to the 5000-char position schema limit),
    the row imports without error, and nothing downstream can 422 on it.
    """
    giant = ("Sehr langer Beschreibungstext. " * 400).strip()  # ~12k chars
    body = (
        b'<Item ID="idI1" RNoPart="0010">'
        b"<Qty>10.000</Qty><QU>m2</QU>"
        b"<Description><CompleteText><DetailTxt><Text><p><span>"
        + giant.encode("utf-8")
        + b"</span></p></Text></DetailTxt></CompleteText></Description>"
        b"</Item>"
    )
    result = await GAEBXMLImporter.parse(_XML_HEAD + body + _XML_TAIL)
    items = [p for p in result.positions if not p.is_section]
    assert len(items) == 1
    assert result.errors == []
    assert 0 < len(items[0].description) <= 5000
    assert items[0].description.startswith("Sehr langer Beschreibungstext.")


@pytest.mark.asyncio
async def test_inline_image_payload_stripped_text_kept() -> None:
    """A base64 <image> inside the Langtext never lands in the description."""
    blob = ("/9j/4AAQ" + "A" * 6000).encode("ascii")
    body = (
        b'<Item ID="idI1" RNoPart="0010">'
        b"<Qty>1.000</Qty><QU>St</QU>"
        b"<Description><CompleteText><DetailTxt><Text>"
        b"<p><span>Bagger liefern und betreiben.</span></p>"
        b'<p><image align="left" Type="image/jpeg" Name="bagger.jpg">' + blob + b"</image></p>"
        b"</Text></DetailTxt></CompleteText></Description>"
        b"</Item>"
    )
    result = await GAEBXMLImporter.parse(_XML_HEAD + body + _XML_TAIL)
    items = [p for p in result.positions if not p.is_section]
    assert len(items) == 1
    assert items[0].description == "Bagger liefern und betreiben."
    assert "/9j/4AAQ" not in json.dumps(items[0].metadata, default=str)


@pytest.mark.asyncio
async def test_priced_x83_still_detected_as_x83() -> None:
    """A priced X83 stays x83: the DP is authoritative, not the prices."""
    body = (
        b'<Item ID="idI1" RNoPart="0010">'
        b"<Qty>10.000</Qty><QU>m2</QU><UP>12.500</UP>"
        b"<Description><CompleteText><DetailTxt><Text><p><span>Putz</span></p>"
        b"</Text></DetailTxt></CompleteText></Description>"
        b"</Item>"
    )
    result = await GAEBXMLImporter.parse(_XML_HEAD + body + _XML_TAIL)
    assert result.metadata["da_kind"] == "x83"


@pytest.mark.asyncio
async def test_unpriced_x84_still_detected_as_x84() -> None:
    """An X84 without prices stays x84: the DP is authoritative."""
    xml = (
        _XML_HEAD.replace(b"/DA83/", b"/DA84/").replace(b"<DP>83</DP>", b"<DP>84</DP>")
        + b'<Item ID="idI1" RNoPart="0010">'
        b"<Qty>10.000</Qty>"
        b"<Description><CompleteText><DetailTxt/></CompleteText></Description>"
        b"</Item>" + _XML_TAIL
    )
    result = await GAEBXMLImporter.parse(xml)
    assert result.metadata["da_kind"] == "x84"
