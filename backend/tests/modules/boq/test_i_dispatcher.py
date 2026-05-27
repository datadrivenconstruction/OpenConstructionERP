"""Epic I4 — dispatcher detect() chain tests.

Validates that the importer registry's ``detect()`` chain claims the
right format for each canonical fixture (synthetic minimal files):

* GAEB X83 → ``gaeb_xml``
* FIEBDC-3 / BC3 → ``bc3``
* Excel (.xlsx) and CSV → ``excel``
* Unknown payload → no native importer claims it (the dispatcher would
  fall back to ``smart_import`` at runtime).
"""

from __future__ import annotations

import csv
import io

import pytest

from app.modules.boq.importers import REGISTERED_IMPORTERS


def _detect(head_bytes: bytes, filename: str) -> str | None:
    """Walk the registry exactly the way the dispatcher does."""
    for imp in REGISTERED_IMPORTERS:
        if imp.detect(head_bytes, filename):
            return imp.format_id
    return None


# ── Synthetic minimal fixtures ─────────────────────────────────────────────


_GAEB_X83_MINIMAL = b"""<?xml version="1.0" encoding="UTF-8"?>
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
            </Itemlist>
          </BoQBody>
        </BoQCtgy>
      </BoQBody>
    </BoQ>
  </Award>
</GAEB>
"""


_BC3_MINIMAL_UTF8 = (
    "~V|FIEBDC-3|3.0|MyExporter 1.0|2026-01-01|Sample|0|UTF-8|EUR|\n"
    "~C|01#|m2|Demolición de pavimento existente|12.50||1|\n"
    "~C|01.01|m3|Hormigón en masa HM-20|65.00||0|\n"
    "~T|01.01|Hormigón en masa HM-20/P/40/I, de central, vertido directo desde camión.|\n"
    "~M|01\\01.01|1|24.5|\n"
).encode()


def _minimal_xlsx_bytes() -> bytes:
    """Build a tiny valid .xlsx in memory."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Pos", "Description", "Unit", "Quantity", "Unit Rate"])
    ws.append(["1", "Concrete C30/37", "m3", 10.0, 150.0])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _minimal_csv_bytes() -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Pos", "Description", "Unit", "Quantity", "Unit Rate"])
    writer.writerow(["1", "Concrete C30/37", "m3", "10.0", "150.0"])
    return buf.getvalue().encode("utf-8")


# ── Detection chain tests ──────────────────────────────────────────────────


class TestDispatcherDetection:
    def test_gaeb_x83_xml(self) -> None:
        assert _detect(_GAEB_X83_MINIMAL[:4096], "Project.x83") == "gaeb_xml"

    def test_gaeb_x83_with_generic_xml_extension(self) -> None:
        # Should still be picked up by content sniff.
        assert _detect(_GAEB_X83_MINIMAL[:4096], "tender.xml") == "gaeb_xml"

    def test_bc3_explicit_extension(self) -> None:
        assert _detect(_BC3_MINIMAL_UTF8[:4096], "obra.bc3") == "bc3"

    def test_bc3_content_sniff_without_extension(self) -> None:
        # Without .bc3 extension we must still sniff the ~V header.
        assert _detect(_BC3_MINIMAL_UTF8[:4096], "obra.txt") == "bc3"

    def test_xlsx(self) -> None:
        xlsx = _minimal_xlsx_bytes()
        assert _detect(xlsx[:4096], "boq.xlsx") == "excel"

    def test_csv(self) -> None:
        csv_bytes = _minimal_csv_bytes()
        assert _detect(csv_bytes[:4096], "boq.csv") == "excel"

    def test_unknown_payload_falls_through(self) -> None:
        # Binary garbage with no recognisable magic should NOT claim any importer.
        assert _detect(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100, "image.png") is None

    def test_empty_payload_falls_through(self) -> None:
        assert _detect(b"", "") is None

    def test_priority_gaeb_beats_excel_on_xml_named_file(self) -> None:
        """GAEB XML detection precedes Excel — a ``.xml`` upload with
        GAEB content must never be misclaimed (ExcelImporter rejects
        non-xlsx/csv extensions anyway, but this pins the ordering)."""
        chosen = _detect(_GAEB_X83_MINIMAL[:4096], "weird.xml")
        assert chosen == "gaeb_xml"


# ── Round-trip parse smoke ─────────────────────────────────────────────────


class TestDispatcherParse:
    @pytest.mark.asyncio
    async def test_gaeb_parse_yields_positions(self) -> None:
        from app.modules.boq.importers.gaeb_xml import GAEBXMLImporter

        result = await GAEBXMLImporter.parse(_GAEB_X83_MINIMAL)
        assert result.source_format == "gaeb"
        # 1 partida (item) — section labels are captured as metadata,
        # not as positions in the dispatcher flow.
        assert len(result.positions) == 1
        assert result.positions[0].description == "Aushub Mutterboden"
        assert result.positions[0].unit == "m3"
        assert result.positions[0].quantity == 120.5
        assert result.positions[0].unit_rate == 3.5
        assert result.currency == "EUR"

    @pytest.mark.asyncio
    async def test_excel_parse_yields_positions(self) -> None:
        from app.modules.boq.importers.excel import ExcelImporter

        result = await ExcelImporter.parse(_minimal_xlsx_bytes())
        assert result.source_format == "xlsx"
        assert len(result.positions) == 1
        assert result.positions[0].description == "Concrete C30/37"
        assert result.positions[0].unit == "m3"

    @pytest.mark.asyncio
    async def test_csv_parse_yields_positions(self) -> None:
        from app.modules.boq.importers.excel import ExcelImporter

        result = await ExcelImporter.parse(_minimal_csv_bytes())
        assert result.source_format == "csv"
        assert len(result.positions) == 1
