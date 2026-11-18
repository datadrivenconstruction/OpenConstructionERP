"""Section Langtext on GAEB import, and the GAEB Kurztext length rule.

A ``BoQCtgy`` whose ``LblTx`` runs over several paragraphs keeps the first one
as its title and the rest as its Langtext. A ``Remark`` (Hinweistext) inside the
section, either in its ``BoQBody`` or in its ``Itemlist``, joins that Langtext.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from app.core.validation.rules import GAEBShortTextLength
from app.modules.boq.importers.gaeb_xml import GAEBXMLImporter

_X83 = """<?xml version="1.0" encoding="UTF-8"?>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA83/3.3">
 <Award>
  <DP>83</DP>
  <BoQ ID="B1">
   <BoQInfo><Name>LV</Name></BoQInfo>
   <BoQBody>
    <BoQCtgy ID="CT39" RNoPart="39">
     <LblTx><p><span>TROCKENBAU</span></p></LblTx>
     <BoQBody>
      <BoQCtgy ID="CT391" RNoPart="1">
       <LblTx>
        <p><span>METALLSTAENDERWAENDE</span></p>
        <p><span>Systemwaende nach DIN 18183,</span><br/><span>Ausfuehrung bis Rohdecke.</span></p>
       </LblTx>
       <BoQBody>
        <Itemlist>
         <Remark ID="RM1">
          <Description><CompleteText><DetailTxt><Text>
           <p><span>Hinweis: Anschluesse elastisch.</span></p>
          </Text></DetailTxt></CompleteText></Description>
         </Remark>
         <Item ID="IT1" RNoPart="10">
          <Qty>12.000</Qty>
          <QU>m2</QU>
          <Description><CompleteText>
           <DetailTxt><Text><p><span>Trennwand 125 mm</span></p><p><span>Beplankung 2x12,5</span></p></Text></DetailTxt>
           <OutlineText><OutlTxt><TextOutlTxt><p><span>Trennwand 125 mm</span></p></TextOutlTxt></OutlTxt></OutlineText>
          </CompleteText></Description>
         </Item>
        </Itemlist>
       </BoQBody>
      </BoQCtgy>
     </BoQBody>
    </BoQCtgy>
   </BoQBody>
  </BoQ>
 </Award>
</GAEB>
"""


def _parse() -> Any:
    return asyncio.run(GAEBXMLImporter.parse(_X83.encode("utf-8")))


def _rows(imported: Any) -> dict[str, Any]:
    return {p.ordinal: p for p in imported.positions}


def test_multi_paragraph_label_splits_into_title_and_long_text() -> None:
    section = _rows(_parse())["39.1"]
    assert section.is_section
    assert section.description == "METALLSTAENDERWAENDE"
    long_text = section.metadata["gaeb_long_text"]
    assert long_text.startswith("Systemwaende nach DIN 18183,\nAusfuehrung bis Rohdecke.")


def test_remark_in_itemlist_joins_the_section_long_text() -> None:
    imported = _parse()
    section = _rows(imported)["39.1"]
    assert section.metadata["gaeb_long_text"].endswith("\n\nHinweis: Anschluesse elastisch.")
    assert imported.metadata["gaeb_header"]["remarks"][0]["text"] == "Hinweis: Anschluesse elastisch."
    unread = {f["field"] for f in imported.fidelity if f["kind"] == "unsupported_element"}
    assert "Remark" not in unread


def test_single_line_section_has_no_long_text() -> None:
    section = _rows(_parse())["39"]
    assert section.description == "TROCKENBAU"
    assert "gaeb_long_text" not in section.metadata


def test_position_long_text_still_imported() -> None:
    pos = _rows(_parse())["39.1.10"]
    assert pos.description == "Trennwand 125 mm"
    assert pos.metadata["gaeb_long_text"] == "Trennwand 125 mm\nBeplankung 2x12,5"


def _validate(positions: list[dict[str, Any]]) -> list[Any]:
    context = SimpleNamespace(data={"positions": positions}, metadata={}, locale="en")
    return asyncio.run(GAEBShortTextLength().validate(context))


def test_short_text_rule_warns_only_when_export_would_cut() -> None:
    long_short = "x" * 71
    results = _validate(
        [
            {"id": "a", "ordinal": "1", "description": long_short, "metadata": {"gaeb_long_text": "Details"}},
            {"id": "b", "ordinal": "2", "description": "x" * 70, "metadata": {"gaeb_long_text": "Details"}},
            {"id": "c", "ordinal": "3", "description": long_short, "metadata": {}},
            {
                "id": "d",
                "ordinal": "4",
                "description": long_short,
                "metadata": {"gaeb_is_section": True, "gaeb_long_text": "x"},
            },
        ]
    )
    by_ref = {r.element_ref: r for r in results}
    assert set(by_ref) == {"a", "b"}
    assert not by_ref["a"].passed
    assert "71" in by_ref["a"].message
    assert by_ref["b"].passed
