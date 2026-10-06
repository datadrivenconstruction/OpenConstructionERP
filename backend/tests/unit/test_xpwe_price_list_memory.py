# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""An XPWE price list is read from disk in bounded memory, whatever its layout or code page.

A regional list exported as XPWE runs to tens of megabytes. Read whole into
memory, re-encoded when it is not UTF-8, and with every item held back whose
analysis names an item further on, the reader's heap grew past the file
itself. These tests write such a file to a temporary directory, read it end to
end through the same path the import uses, and hold the Python heap peak under
a fixed ceiling. What stays is the index of every item's code by its id (about
a hundred bytes an item) and the parser's buffers: about 5 MB for a 25 MB list
and 6 MB for a 64 MB one, where the reader used to peak at 120-140 MB for the
files below. The files are deleted after.
"""

from __future__ import annotations

import tempfile
import tracemalloc
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.modules.costs.pricelists.containers import open_members
from app.modules.costs.pricelists.service import plan_upload
from tests.fixtures import xpwe_builder as fx

# The heap may hold the code index and the parser's buffers, not the file.
_PEAK_LIMIT = 12 * 1024 * 1024


def _items(count: int, description: str) -> Iterator[str]:
    """Price items whose analysis lines each name the NEXT item, so every one refers forward."""
    for index in range(1, count + 1):
        yield fx._price_item(index, description, 6).replace("<IDEP>0</IDEP>", f"<IDEP>{index + 1}</IDEP>")


def _write(path: Path, *, target_bytes: int, encoding: str, description: str) -> int:
    one = len(next(_items(1, description)).encode(encoding))
    count = max(target_bytes // one, 2)
    with path.open("w", encoding=encoding, newline="") as out:
        out.write(fx._header())
        out.write("<PweElencoPrezzi>")
        for item in _items(count, description):
            out.write(item)
        out.write("</PweElencoPrezzi><PweVociComputo></PweVociComputo></PweMisurazioni></PweDocumento>")
    return count


def _read_all(path: Path) -> tuple[int, int, list]:
    """Rows read, the heap peak while reading them, and the first rows."""
    tracemalloc.start()
    try:
        with path.open("rb") as stream:
            plan = plan_upload(stream, path.name)
            assert plan.format.format_id == "xpwe"
            rows = 0
            first: list = []
            for row in plan.rows():
                rows += 1
                if len(first) < 3:
                    first.append(row)
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return rows, peak, first


@pytest.mark.slow
def test_a_large_utf8_list_with_forward_references_is_read_in_bounded_memory() -> None:
    description = ("Fornitura e posa in opera di muratura portante in blocchi di laterizio porizzato, " * 12).strip()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "elenco-grande.xpwe"
        count = _write(path, target_bytes=40 * 1024 * 1024, encoding="utf-8", description=description)
        size = path.stat().st_size
        rows, peak, first = _read_all(path)
    # Every analysis line still carries the code of the item it names (kept as
    # the record when the analysis claims more than the price).
    lines = first[0].components or first[0].extra.get("analysis")
    assert lines[0]["code"] == "EX26_01.A00.002.001"
    assert peak < _PEAK_LIMIT, f"heap peak {peak / 2**20:.1f} MB for a {size / 2**20:.1f} MB file"


@pytest.mark.slow
def test_a_list_in_a_legacy_code_page_is_transcoded_as_it_is_read() -> None:
    # No XML declaration and accented letters in cp1252: the parser cannot be
    # handed the bytes as they are, and the whole file must not be decoded at once.
    description = ("Muratura della città vecchia, compresa la malta e ogni onere di perizia. " * 12).strip()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "elenco-cp1252.xpwe"
        count = _write(path, target_bytes=24 * 1024 * 1024, encoding="cp1252", description=description)
        size = path.stat().st_size
        rows, peak, first = _read_all(path)
    assert rows == count
    assert "città" in first[0].description
    assert peak < _PEAK_LIMIT, f"heap peak {peak / 2**20:.1f} MB for a {size / 2**20:.1f} MB file"


def test_a_list_in_a_zip_reads_every_item_through_both_passes() -> None:
    # A guard, not a regression test: a ZIP member reads forward only, so it is
    # spooled to disk once and the index pass and the row pass both read that.
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("elenco.xpwe", fx.small_computo())
    members, _skipped = open_members(io.BytesIO(buf.getvalue()), "elenco.zip")
    plan = plan_upload(io.BytesIO(buf.getvalue()), "elenco.zip")
    assert [m.name for m in members] == ["elenco.xpwe"]
    codes = sorted(row.code for row in plan.rows())
    assert codes == ["EX26_01.A03.001.001", "EX26_01.B02.004.002", "EX26_17.S01.001.001"]
