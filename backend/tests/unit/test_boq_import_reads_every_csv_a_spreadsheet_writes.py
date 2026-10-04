# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Every CSV a spreadsheet program writes imports as the same bill.

Excel alone writes a CSV a dozen ways: with or without a UTF-8 byte-order
mark, in the ANSI code page of the machine, as "Unicode text" in UTF-16 with
a byte-order mark, separated by the list separator of the locale (a
semicolon wherever the decimal point is a comma), with a "sep=" line that
names the separator, and on a Mac with bare carriage returns between lines.
Other programs add tabs and pipes.

One small German bill is written each of those ways here and has to import
as the same two lines every time: "12,5" is twelve and a half, "1.250" is
twelve hundred and fifty, and the umlaut survives.

Two of these did not import at all before: a UTF-16 file was taken for a
binary and handed to the AI fallback, and a file with bare carriage returns
failed with a csv module error.

Run::

    cd backend
    python -m pytest tests/unit/test_boq_import_reads_every_csv_a_spreadsheet_writes.py -v
"""

from __future__ import annotations

import asyncio

import pytest

from app.modules.boq.importers import REGISTERED_IMPORTERS
from app.modules.boq.importers._base import ImportedBOQ
from app.modules.boq.importers._encoding import decode_text_bytes
from app.modules.boq.importers.excel import ExcelImporter, _detect_file_format, _parse_csv

_ROWS = [
    ["Pos", "Beschreibung", "Einheit", "Menge", "Einheitspreis"],
    ["1", "Stahlbetonwände C25/30", "m3", "12,5", "185,50"],
    ["2", "Betonstahl BSt 500", "t", "1.250", "1.450,00"],
]
_EXPECTED = [
    ("Stahlbetonwände C25/30", "m3", 12.5, 185.5),
    ("Betonstahl BSt 500", "t", 1250.0, 1450.0),
]


def _text(delimiter: str, newline: str = "\r\n", *, quote: bool = False) -> str:
    def cell(value: str) -> str:
        return f'"{value}"' if quote else value

    return "".join(delimiter.join(cell(value) for value in row) + newline for row in _ROWS)


_VARIANTS: dict[str, tuple[bytes, str, str]] = {
    # name: (bytes, expected encoding, expected delimiter)
    "utf8 bom, semicolon": (b"\xef\xbb\xbf" + _text(";").encode("utf-8"), "utf-8-sig", ";"),
    "utf8 no bom, semicolon": (_text(";").encode("utf-8"), "utf-8-sig", ";"),
    "ansi cp1252, semicolon": (_text(";").encode("cp1252"), "cp1252", ";"),
    "ansi cp1252, tab": (_text("\t").encode("cp1252"), "cp1252", "\t"),
    "utf16 le bom, tab (Unicode text)": (_text("\t").encode("utf-16"), "utf-16", "\t"),
    "utf16 be bom, tab": (b"\xfe\xff" + _text("\t").encode("utf-16-be"), "utf-16", "\t"),
    "utf8, pipe": (_text("|").encode("utf-8"), "utf-8-sig", "|"),
    "utf8, comma, quoted decimal commas": (_text(",", quote=True).encode("utf-8"), "utf-8-sig", ","),
    "mac, bare carriage returns": (_text(";", "\r").encode("cp1252"), "cp1252", ";"),
    "unix, line feeds": (_text(";", "\n").encode("utf-8"), "utf-8-sig", ";"),
    "sep line, semicolon": (("sep=;\r\n" + _text(";")).encode("utf-8"), "utf-8-sig", ";"),
}


def _import(content: bytes) -> ImportedBOQ:
    return asyncio.run(ExcelImporter.parse(content))


@pytest.mark.parametrize("name", sorted(_VARIANTS))
def test_the_upload_is_claimed_by_the_spreadsheet_importer(name: str) -> None:
    content, _, _ = _VARIANTS[name]
    assert _detect_file_format(content[:4096]) == "csv"
    claimed = [importer for importer in REGISTERED_IMPORTERS if importer.detect(content[:4096], "bill.csv")]
    assert claimed[:1] == [ExcelImporter]


@pytest.mark.parametrize("name", sorted(_VARIANTS))
def test_every_variant_imports_the_same_two_lines(name: str) -> None:
    content, _, _ = _VARIANTS[name]
    result = _import(content)

    assert result.errors == []
    assert [(p.description, p.unit, p.quantity, p.unit_rate) for p in result.positions] == [
        (description, unit, pytest.approx(quantity), pytest.approx(rate))
        for description, unit, quantity, rate in _EXPECTED
    ]


@pytest.mark.parametrize("name", sorted(_VARIANTS))
def test_the_import_reports_the_encoding_and_separator_it_read(name: str) -> None:
    content, encoding, delimiter = _VARIANTS[name]
    _, meta = _parse_csv(content)

    assert (meta["encoding"], meta["delimiter"]) == (encoding, delimiter)
    assert meta["header_language"] == "de"


def test_a_sep_line_wins_over_what_the_lines_below_look_like() -> None:
    # Three note lines split into three fields by semicolons outnumber the
    # comma-separated table under them, so a count alone picks the semicolon.
    # The "sep=" line Excel writes names the separator outright.
    notes = "Projekt; Haus A; Rev. 2\nStand; 01.10.2026; geprüft\nWährung; EUR; netto\n"
    table = "Pos,Beschreibung,Einheit,Menge,Einheitspreis\n1,Stahlbetonwände,m3,12.5,185.50\n"
    content = ("sep=,\n" + notes + table).encode("utf-8")

    _, meta = _parse_csv(content)
    result = _import(content)

    assert meta["delimiter"] == ","
    assert [(p.description, p.quantity, p.unit_rate) for p in result.positions] == [
        ("Stahlbetonwände", pytest.approx(12.5), pytest.approx(185.5))
    ]


def test_a_sep_line_does_not_shift_the_row_numbers_the_messages_name() -> None:
    content = ("sep=;\n" + "Pos;Beschreibung;Einheit;Menge;Einheitspreis\n1;Wand;m2;zwölf;55\n").encode("utf-8")
    result = _import(content)

    assert [error["row"] for error in result.errors] == [3]


@pytest.mark.parametrize("bom", [b"\xff\xfe", b"\xfe\xff", b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff"])
def test_a_byte_order_mark_names_the_unicode_form(bom: bytes) -> None:
    codec = {
        b"\xff\xfe": "utf-16-le",
        b"\xfe\xff": "utf-16-be",
        b"\xff\xfe\x00\x00": "utf-32-le",
        b"\x00\x00\xfe\xff": "utf-32-be",
    }[bom]
    text, encoding = decode_text_bytes(bom + "Menge;Wände".encode(codec))

    assert text == "Menge;Wände"
    assert encoding in ("utf-16", "utf-32")


def test_a_binary_upload_with_nul_bytes_is_still_refused() -> None:
    assert _detect_file_format(b"PK\x03\x04garbage") == "xlsx"
    assert _detect_file_format(b"\x00\x01\x02binary\x00") == "unknown"
