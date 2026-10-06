# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A price list saved as Excel "Unicode text" is read, and a damaged archive is refused by name.

Excel saves "Unicode text" as UTF-16 with a byte-order mark, and the reader
used to take it for Windows-1252: every second byte a NUL, no header found,
and the preview said the list held nothing to import. A ZIP member whose
contents do not match its checksum used to surface on the import as an
internal error instead of a refusal the screen can name.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from app.modules.costs.pricelists.containers import ContainerRefused
from app.modules.costs.pricelists.service import plan_upload

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "pricelists"


def _codes(content: bytes, name: str) -> list[str]:
    plan = plan_upload(io.BytesIO(content), name)
    return [row.code for row in plan.rows()]


@pytest.fixture(scope="module")
def puglia() -> tuple[str, list[str]]:
    text = (FIXTURES / "puglia_2026.csv").read_bytes().decode("utf-8")
    codes = _codes(text.encode("utf-8"), "puglia.csv")
    assert codes, "the fixture itself must yield rows"
    return text, codes


@pytest.mark.parametrize(
    ("label", "encode"),
    [
        ("utf-16 with mark (Excel Unicode text)", lambda t: t.encode("utf-16")),
        ("utf-16 big-endian with mark", lambda t: b"\xfe\xff" + t.encode("utf-16-be")),
        ("utf-16 little-endian without mark", lambda t: t.encode("utf-16-le")),
        ("utf-8 with mark", lambda t: b"\xef\xbb\xbf" + t.encode("utf-8")),
    ],
)
def test_a_list_in_a_unicode_encoding_reads_the_same_rows(puglia, label, encode) -> None:
    text, codes = puglia
    assert _codes(encode(text), "puglia.csv") == codes, label


def test_a_utf16_file_that_does_not_decode_is_refused_naming_the_encoding() -> None:
    # A UTF-16 mark, then an unpaired high surrogate: not readable as UTF-16.
    broken = b"\xff\xfe" + "codice;voce\n".encode("utf-16-le") + b"\x00\xd8\x41\x00"
    with pytest.raises(ContainerRefused) as caught:
        _codes(broken, "lista.csv")
    assert caught.value.code == "text_encoding_unreadable"
    assert caught.value.params == {"encoding": "UTF-16", "member": "lista.csv"}


def test_a_binary_file_named_csv_is_refused_without_an_encoding() -> None:
    blob = bytes(range(256)) * 64
    with pytest.raises(ContainerRefused) as caught:
        _codes(blob, "lista.csv")
    assert caught.value.code == "text_encoding_unreadable"
    assert caught.value.params == {"encoding": None, "member": "lista.csv"}


def _damaged_zip() -> bytes:
    """A ZIP whose member's bytes no longer match the checksum it declares."""
    content = (FIXTURES / "puglia_2026.csv").read_bytes()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("Prezzario_PUG_2026.csv", content)
    data = bytearray(buf.getvalue())
    # Flip one digit in the stored data: sizes stay true, the CRC no longer does.
    at = data.index(b"TOTALE") + 40
    while not chr(data[at]).isdigit():
        at += 1
    data[at] = ord("7") if data[at] != ord("7") else ord("3")
    return bytes(data)


def test_a_member_that_fails_its_checksum_is_refused_by_name() -> None:
    with pytest.raises(ContainerRefused) as caught:
        _codes(_damaged_zip(), "puglia.zip")
    assert caught.value.code == "zip_member_corrupt"
    assert caught.value.params == {"member": "Prezzario_PUG_2026.csv"}


def test_the_preview_reports_a_damaged_member_as_a_refusal() -> None:
    """Planning reads the member's head, so a small member fails there; a large one fails while read."""
    from app.modules.costs.pricelist_import import PriceListRefused, preview

    with pytest.raises((ContainerRefused, PriceListRefused)) as caught:
        preview(plan_upload(io.BytesIO(_damaged_zip()), "puglia.zip"), None, None)
    assert caught.value.code == "zip_member_corrupt"
