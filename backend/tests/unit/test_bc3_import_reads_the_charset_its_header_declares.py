# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A BC3 file is decoded in the character set its ``~V`` record declares.

FIEBDC-3 names the character set in the fifth field of ``~V``
(JUEGO_CARACTERES): ``850`` and ``437`` for the MS-DOS code pages, ``ANSI``
for Windows-1252, and ``UTF-8`` in the newer revisions; an empty field means
850. The importer used to ignore the field and try UTF-8, then Windows-1252,
and Windows-1252 decodes any byte. A file the DOS-era programs still write in
code page 850 therefore imported "Excavación" as "Excavaci¢n" and "Peña" as
"Pe¤a", without an error, into every description of the budget.

Run::

    cd backend
    python -m pytest tests/unit/test_bc3_import_reads_the_charset_its_header_declares.py -v
"""

from __future__ import annotations

import asyncio

import pytest

from app.modules.boq.importers._base import ImportedBOQ
from app.modules.boq.importers.bc3 import BC3Importer, declared_bc3_charset

_TEXT = "Excavación en zanja, Peña y Cía., señalización ÁÉÍÓÚÜ ¿¡ 12º"


def _bc3(charset_field: str, *, layout: str = "spec") -> str:
    if layout == "spec":
        # PROPIEDAD | VERSION\DATE | PROGRAMA | CABECERA\ROTULO | JUEGO_CARACTERES | COMENTARIO
        version = f"~V|SOFT S.A.|FIEBDC-3/2020\\01102026|PROGRAMA 4.1|Obra Peña|{charset_field}|Comentario|2|\n"
    else:
        # The layout our exporter writes, one field later.
        version = f"~V|obra.bc3|FIEBDC-3/2020|OpenConstructionERP|2026-10-01|Obra Peña|{charset_field}|2||EUR|\n"
    return (
        version + "~C|01#||Movimiento de tierras|0|||1|\n"
        f"~C|01.01|m3|{_TEXT}|18.50|||0|\n"
        "~D|01#|01.01\\1\\125|\n"
        "~M|01#\\01.01|1|125.0||\n"
    )


def _import(content: bytes) -> ImportedBOQ:
    return asyncio.run(BC3Importer.parse(content))


def _description(result: ImportedBOQ) -> str:
    return next(p.description for p in result.positions if not p.is_section)


@pytest.mark.parametrize(
    ("field", "codec"),
    [
        ("850", "cp850"),
        ("437", "cp437"),
        ("ANSI", "cp1252"),
        ("UTF-8", "utf-8"),
    ],
)
@pytest.mark.parametrize("layout", ["spec", "exporter"])
def test_the_declared_charset_decodes_the_file(field: str, codec: str, layout: str) -> None:
    if codec == "cp437":
        # Code page 437 has no capital accented vowels but É, nor º.
        text = _bc3(field, layout=layout).replace("ÁÉÍÓÚÜ", "ÉÜ").replace("12º", "12")
        expected = _TEXT.replace("ÁÉÍÓÚÜ", "ÉÜ").replace("12º", "12")
    else:
        text, expected = _bc3(field, layout=layout), _TEXT
    result = _import(text.encode(codec))

    assert _description(result) == expected
    assert result.metadata["bc3_encoding"] == codec
    assert result.metadata["bc3_declared_charset"] == field


def test_a_code_page_850_file_no_longer_reads_as_windows_1252() -> None:
    # The bytes of "ó" and "ñ" in code page 850 are 0xA2 and 0xA4, which
    # Windows-1252 reads as "¢" and "¤", and Latin-1, the probe's last
    # resort, reads the same. Without capitals both decodes succeed and only
    # the declaration tells them apart.
    text = _bc3("850").replace("ÁÉÍÓÚÜ ", "")
    content = text.encode("cp850")
    assert "Excavaci¢n" in content.decode("cp1252")

    description = _description(_import(content))
    assert "Excavación" in description
    assert "Peña" in description


def test_an_empty_charset_field_reads_as_850_when_the_bytes_say_so() -> None:
    # The standard makes 850 the default. Older programs leave the field
    # empty and write 850; many Windows programs leave it empty and write
    # ANSI. The letters a Spanish budget is made of decide between the two.
    result = _import(_bc3("").encode("cp850"))

    assert _description(result) == _TEXT
    assert result.metadata["bc3_encoding"] == "cp850"
    assert result.metadata["bc3_declared_charset"] == ""


def test_an_empty_charset_field_reads_as_ansi_when_the_bytes_say_so() -> None:
    result = _import(_bc3("").encode("cp1252"))

    assert _description(result) == _TEXT
    assert result.metadata["bc3_encoding"] == "cp1252"


def test_a_file_that_is_utf8_wins_over_a_stale_declaration() -> None:
    # A program that converted the file to UTF-8 and kept the old header.
    # Text in a single-byte code page with accents is almost never valid
    # UTF-8, so bytes that decode as UTF-8 are UTF-8.
    result = _import(_bc3("ANSI").encode("utf-8"))

    assert _description(result) == _TEXT
    assert result.metadata["bc3_encoding"] == "utf-8"
    assert result.metadata["bc3_declared_charset"] == "ANSI"


def test_a_utf8_byte_order_mark_wins_over_the_declaration() -> None:
    result = _import(b"\xef\xbb\xbf" + _bc3("850").encode("utf-8"))

    assert _description(result) == _TEXT
    assert result.metadata["bc3_encoding"] == "utf-8-sig"


def test_an_unknown_charset_falls_back_to_the_probe() -> None:
    result = _import(_bc3("EBCDIC").encode("cp1252"))

    assert _description(result) == _TEXT
    assert result.metadata["bc3_encoding"] == "cp1252"


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        ("~V|A|FIEBDC-3/2020|P|R|850|C|", "850"),
        ("~V|A|FIEBDC-3/2020|P|R|ansi|C|", "ANSI"),
        ("~V|A|FIEBDC-3/2020|P|R|utf8|", "UTF-8"),
        ("~V|A|FIEBDC-3/2020|P|R||C|", ""),
        ("~V|A|FIEBDC-3/2020|P|", ""),
        ("~V|f.bc3|FIEBDC-3/2020|Prog|2026-10-01|Obra|ANSI|2||EUR|", "ANSI"),
        # The layout of the older fixtures, the charset two fields along.
        ("~V|FIEBDC-3|3.0|Exp|2026-01-01|sample|0|CP1252|EUR|", "ANSI"),
        ("no version record here", None),
    ],
)
def test_the_charset_field_is_read_where_the_programs_put_it(record: str, expected: str | None) -> None:
    assert declared_bc3_charset((record + "\r\n~C|X|m|x|1|||0|\r\n").encode("latin-1")) == expected
