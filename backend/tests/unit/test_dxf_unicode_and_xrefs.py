# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""DXF text decoding and unresolved external references.

The DWG converter writes R2000 DXF with an ANSI code page, so every non-ASCII
character in a layer name or a text arrives as ``\\U+XXXX`` (and East Asian
multibyte text as ``\\M+NXXXX``). ezdxf keeps those escapes for this version,
and they reached the canvas, the layer list and the exports verbatim.

A host drawing whose content lives in xrefs converts to a near-empty sheet;
the parser now names the references it could not resolve.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import ezdxf
import pytest

from app.modules.dwg_takeoff.dxf_processor import decode_dxf_text, parse_dxf

GREEK_ESCAPED = "\\U+0398\\U+03B5\\U+03BC\\U+03AD\\U+03BB\\U+03B9\\U+03B1"
GREEK = "Θεμέλια"
CYRILLIC_ESCAPED = "\\U+0421\\U+0442\\U+0435\\U+043D\\U+044B"
CYRILLIC = "Стены"


def _parse(tmp_path: Path, doc: Any) -> dict[str, Any]:
    path = tmp_path / "drawing.dxf"
    doc.saveas(str(path))
    return parse_dxf(str(path))


def _doc() -> Any:
    doc = ezdxf.new("R2000", setup=False)
    doc.header["$INSUNITS"] = 4
    return doc


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (GREEK_ESCAPED, GREEK),
        (CYRILLIC_ESCAPED, CYRILLIC),
        (f"{CYRILLIC_ESCAPED} 2", f"{CYRILLIC} 2"),
        ("plain", "plain"),
        ("", ""),
    ],
)
def test_decode_dxf_text_turns_unicode_escapes_into_characters(raw: str, expected: str) -> None:
    assert decode_dxf_text(raw) == expected


def test_decode_dxf_text_passes_non_strings_through() -> None:
    assert decode_dxf_text(None) is None
    assert decode_dxf_text(3) == 3


def test_decode_dxf_text_decodes_mif_sequences() -> None:
    decoded = decode_dxf_text("\\M+5B0A1")
    assert "\\M+" not in decoded
    assert decoded


def test_layer_names_and_texts_are_decoded(tmp_path: Path) -> None:
    doc = _doc()
    doc.layers.add(GREEK_ESCAPED)
    doc.layers.add(CYRILLIC_ESCAPED)
    msp = doc.modelspace()
    msp.add_line((0, 0), (1000, 0), dxfattribs={"layer": GREEK_ESCAPED})
    msp.add_text(CYRILLIC_ESCAPED, dxfattribs={"layer": CYRILLIC_ESCAPED})
    msp.add_mtext("{\\fArial|b0|i0|c161|p34;" + GREEK_ESCAPED + "}", dxfattribs={"layer": GREEK_ESCAPED})

    result = _parse(tmp_path, doc)

    names = {layer["name"] for layer in result["layers"]}
    assert {GREEK, CYRILLIC} <= names
    assert not any("\\U+" in n for n in names)
    by_name = {layer["name"]: layer for layer in result["layers"]}
    assert by_name[GREEK]["entity_count"] == 2
    assert by_name[CYRILLIC]["entity_count"] == 1

    texts = {e["entity_type"]: e for e in result["entities"] if e["entity_type"] in ("TEXT", "MTEXT")}
    assert texts["TEXT"]["geometry_data"]["text"] == CYRILLIC
    assert texts["TEXT"]["layer"] == CYRILLIC
    assert texts["MTEXT"]["geometry_data"]["text"] == GREEK
    assert {e["layer"] for e in result["entities"] if e["entity_type"] == "LINE"} == {GREEK}


def test_block_names_are_decoded_on_insert_and_definition_alike(tmp_path: Path) -> None:
    doc = _doc()
    block = doc.blocks.new(CYRILLIC_ESCAPED)
    block.add_line((0, 0), (1, 1))
    doc.modelspace().add_blockref(CYRILLIC_ESCAPED, (5, 5))

    result = _parse(tmp_path, doc)

    inserts = [e for e in result["entities"] if e["entity_type"] == "INSERT"]
    members = [e for e in result["entities"] if e.get("block")]
    assert inserts[0]["geometry_data"]["block_name"] == CYRILLIC
    assert members and {m["block"] for m in members} == {CYRILLIC}
    assert result["xrefs"] == []


def test_attached_xrefs_are_reported(tmp_path: Path) -> None:
    doc = _doc()
    doc.add_xref_def("C:/project/site_plan.dwg", "SITE")
    msp = doc.modelspace()
    msp.add_blockref("SITE", (0, 0))
    msp.add_line((0, 0), (10, 0))

    result = _parse(tmp_path, doc)

    assert result["xrefs"] == [{"name": "SITE", "path": "C:/project/site_plan.dwg"}]


def test_insert_of_an_undefined_block_is_reported_as_unresolved(tmp_path: Path) -> None:
    doc = _doc()
    msp = doc.modelspace()
    msp.add_blockref("GONE", (0, 0))
    msp.add_line((0, 0), (10, 0))

    result = _parse(tmp_path, doc)

    assert result["xrefs"] == [{"name": "GONE", "path": None}]
