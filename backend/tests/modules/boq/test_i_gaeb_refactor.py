"""Epic I2 + I11 + I12 — GAEB XML importer regression tests.

Pins that the refactored ``GAEBXMLImporter`` still parses representative
GAEB DA XML fixtures correctly. Specifically:

* X81 / X83 / X84 / X86 detection
* Namespace-agnostic tag matching
* Currency capture from ``<Award><Cur>``
* Section ordinal threading via ``<BoQCtgy>`` ancestors
* I11 — X86 award metadata captured under ``metadata['award']``
* I12 — ``<DescrTxc>`` rich-text preserved under
  ``metadata['descr_txc']``.
"""

from __future__ import annotations

import pytest

from app.modules.boq.importers.gaeb_xml import GAEBXMLImporter

_GAEB_X83 = b"""<?xml version="1.0" encoding="UTF-8"?>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/200407">
  <GAEBInfo><DPType>83</DPType></GAEBInfo>
  <Award>
    <Cur>EUR</Cur>
    <BoQ>
      <BoQInfo><Name>Test LV</Name></BoQInfo>
      <BoQBody>
        <BoQCtgy ID="01">
          <LblTx>Erdarbeiten</LblTx>
          <BoQBody>
            <Itemlist>
              <Item ID="01.01.0010">
                <Description><CompleteText><DetailTxt><Text>Aushub Mutterboden</Text></DetailTxt></CompleteText></Description>
                <QU>m3</QU>
                <Qty>120.5</Qty>
                <UP>3.50</UP>
              </Item>
              <Item ID="01.01.0020">
                <Description><CompleteText><DetailTxt><Text>Bodenaustausch</Text></DetailTxt></CompleteText></Description>
                <QU>m3</QU>
                <Qty>80.0</Qty>
                <UP>4.20</UP>
              </Item>
            </Itemlist>
          </BoQBody>
        </BoQCtgy>
      </BoQBody>
    </BoQ>
  </Award>
</GAEB>
"""


_GAEB_X86 = b"""<?xml version="1.0" encoding="UTF-8"?>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/200407">
  <GAEBInfo><DPType>86</DPType></GAEBInfo>
  <Award>
    <Cur>EUR</Cur>
    <OrderNo>O-2026-0042</OrderNo>
    <DateOfContract>2026-05-26</DateOfContract>
    <BoQ>
      <BoQBody>
        <Itemlist>
          <Item ID="01.0010">
            <Description><CompleteText><DetailTxt><Text>Awarded item</Text></DetailTxt></CompleteText></Description>
            <QU>m3</QU>
            <Qty>50.0</Qty>
            <UP>120.0</UP>
          </Item>
        </Itemlist>
      </BoQBody>
    </BoQ>
  </Award>
</GAEB>
"""


_GAEB_X83_WITH_DESCRTXC = b"""<?xml version="1.0" encoding="UTF-8"?>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/200407">
  <Award>
    <Cur>EUR</Cur>
    <BoQ>
      <BoQBody>
        <Itemlist>
          <Item ID="01.0010">
            <Description>
              <CompleteText><DetailTxt><Text>Plain summary</Text></DetailTxt></CompleteText>
              <DescrTxc>
                <p><b>Bold heading</b></p>
                <p>Indented detail line.</p>
              </DescrTxc>
            </Description>
            <QU>m</QU>
            <Qty>10.0</Qty>
            <UP>15.0</UP>
          </Item>
        </Itemlist>
      </BoQBody>
    </BoQ>
  </Award>
</GAEB>
"""


class TestGAEBImporterRegression:
    @staticmethod
    def _items(result: object) -> list:
        """Return only the item rows (drop emitted section headers)."""
        return [p for p in result.positions if not p.is_section]  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_x83_round_trip(self) -> None:
        result = await GAEBXMLImporter.parse(_GAEB_X83)
        assert result.source_format == "gaeb"
        assert result.currency == "EUR"
        items = self._items(result)
        assert len(items) == 2
        assert items[0].description == "Aushub Mutterboden"
        assert items[0].unit == "m3"
        assert items[0].quantity == 120.5
        assert items[0].unit_rate == 3.5
        assert items[0].classification["gaeb_section"] == "01"
        # Hierarchy preserved: a section header row mirrors the BoQCtgy.
        sections = [p for p in result.positions if p.is_section]
        assert any(s.ordinal == "01" for s in sections)

    @pytest.mark.asyncio
    async def test_namespace_agnostic(self) -> None:
        """A file without the standard GAEB namespace must still parse —
        the importer matches by tag local-name."""
        no_ns = _GAEB_X83.replace(
            b'<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/200407">',
            b"<GAEB>",
        )
        result = await GAEBXMLImporter.parse(no_ns)
        assert len(self._items(result)) == 2

    @pytest.mark.asyncio
    async def test_currency_captured(self) -> None:
        result = await GAEBXMLImporter.parse(_GAEB_X83)
        assert result.currency == "EUR"
        # Per-position metadata too.
        assert self._items(result)[0].metadata["gaeb_currency"] == "EUR"

    @pytest.mark.asyncio
    async def test_section_label_collected(self) -> None:
        result = await GAEBXMLImporter.parse(_GAEB_X83)
        sections = result.metadata["sections"]
        assert any(s["ordinal"] == "01" and s["label"] == "Erdarbeiten" for s in sections)

    @pytest.mark.asyncio
    async def test_da_kind_x83(self) -> None:
        result = await GAEBXMLImporter.parse(_GAEB_X83)
        assert result.metadata["da_kind"] == "x83"
        assert self._items(result)[0].metadata["gaeb_da_kind"] == "x83"

    @pytest.mark.asyncio
    async def test_da_kind_x86_with_award_metadata(self) -> None:
        """Epic I11 — X86 (Auftragserteilung / order award) detection."""
        result = await GAEBXMLImporter.parse(_GAEB_X86)
        assert result.metadata["da_kind"] == "x86"
        award = result.metadata["award"]
        assert award["OrderNo"] == "O-2026-0042"
        assert award["DateOfContract"] == "2026-05-26"

    @pytest.mark.asyncio
    async def test_descr_txc_rich_text_preserved(self) -> None:
        """Epic I12 — ``<DescrTxc>`` blocks preserved verbatim."""
        result = await GAEBXMLImporter.parse(_GAEB_X83_WITH_DESCRTXC)
        assert len(result.positions) == 1
        pos = result.positions[0]
        # Plain description is unchanged.
        assert pos.description == "Plain summary"
        # Rich-text view captured under metadata.
        assert "descr_txc" in pos.metadata
        descr = pos.metadata["descr_txc"]
        assert "DescrTxc" in descr["raw_xml"] or "DescrTxc" in descr["raw_xml"].replace("{", "")
        assert "Bold heading" in descr["plain_text"]
        assert "Indented detail line" in descr["plain_text"]

    @pytest.mark.asyncio
    async def test_empty_buffer_raises(self) -> None:
        from app.modules.boq.importers import ImporterParseError

        with pytest.raises(ImporterParseError):
            await GAEBXMLImporter.parse(b"")

    @pytest.mark.asyncio
    async def test_no_boq_body_raises(self) -> None:
        from app.modules.boq.importers import ImporterParseError

        with pytest.raises(ImporterParseError):
            await GAEBXMLImporter.parse(b"<?xml version='1.0'?><GAEB/>")

    def test_detect_extensions(self) -> None:
        for ext in (".x81", ".x83", ".x84", ".x86"):
            assert GAEBXMLImporter.detect(b"<?xml", f"f{ext}") is True

    def test_detect_generic_xml_with_gaeb_content(self) -> None:
        assert GAEBXMLImporter.detect(_GAEB_X83[:512], "tender.xml") is True

    def test_detect_rejects_plain_xml(self) -> None:
        assert GAEBXMLImporter.detect(b"<?xml version='1.0'?><foo/>", "boq.xml") is False
