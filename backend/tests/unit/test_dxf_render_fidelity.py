# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""What the DXF path hands the viewer so a drawing looks like its source.

A DWG reaches the viewer through the DXF the DDC converter writes beside its
entity table, so everything here holds for DWG uploads too. Covered: line
weights (group 370, ByLayer, ByBlock), text placement (rotation, justification,
MTEXT attachment and format codes), dimensions (their rendered ``*D`` block and
the measured value), and the SOLID fills that dimension arrowheads are made of.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import ezdxf
import pytest

from app.modules.dwg_takeoff.dxf_processor import parse_dxf
from app.modules.dwg_takeoff.service import _normalize_entity


@pytest.fixture
def parsed(tmp_path: Path):
    def _parse(doc: Any) -> dict[str, Any]:
        path = tmp_path / "drawing.dxf"
        doc.saveas(str(path))
        return parse_dxf(str(path))

    return _parse


def _placed(result: dict[str, Any], entity_type: str) -> list[dict[str, Any]]:
    return [e for e in result["entities"] if e["entity_type"] == entity_type and not e.get("block")]


class TestLineWeights:
    def test_an_explicit_weight_arrives_in_millimetres(self, parsed) -> None:
        doc = ezdxf.new("R2010", setup=False)
        doc.modelspace().add_line((0, 0), (10, 0), dxfattribs={"lineweight": 50})
        (line,) = _placed(parsed(doc), "LINE")
        assert line["lineweight"] == pytest.approx(0.5)

    def test_bylayer_takes_the_layer_weight(self, parsed) -> None:
        doc = ezdxf.new("R2010", setup=False)
        doc.layers.add("A-WALL", lineweight=70)
        doc.modelspace().add_line((0, 0), (10, 0), dxfattribs={"layer": "A-WALL"})
        (line,) = _placed(parsed(doc), "LINE")
        assert line["lineweight"] == pytest.approx(0.7)

    def test_default_weight_is_left_to_the_viewer(self, parsed) -> None:
        doc = ezdxf.new("R2010", setup=False)
        doc.modelspace().add_line((0, 0), (10, 0), dxfattribs={"lineweight": -3})
        (line,) = _placed(parsed(doc), "LINE")
        assert "lineweight" not in line

    def test_byblock_and_layer_zero_members_inherit_from_the_insert(self, parsed) -> None:
        doc = ezdxf.new("R2010", setup=False)
        doc.layers.get("0").dxf.lineweight = 18
        blk = doc.blocks.new("DOOR")
        blk.add_line((0, 0), (1, 0), dxfattribs={"lineweight": -2})
        blk.add_line((0, 0), (0, 1), dxfattribs={"layer": "0"})
        blk.add_line((0, 0), (1, 1), dxfattribs={"lineweight": 35})
        doc.modelspace().add_blockref("DOOR", (5, 5), dxfattribs={"lineweight": 100})
        result = parsed(doc)
        members = [e for e in result["entities"] if e.get("block") == "DOOR"]
        assert [m.get("lineweight") for m in members] == [None, None, pytest.approx(0.35)]
        (ins,) = _placed(result, "INSERT")
        assert ins["lineweight"] == pytest.approx(1.0)

    def test_the_weight_reaches_the_viewer_shape(self) -> None:
        raw = {"entity_type": "LINE", "layer": "0", "color": "#fff", "lineweight": 0.5, "geometry_data": {}}
        assert _normalize_entity(raw, 0)["lineweight"] == 0.5
        raw.pop("lineweight")
        assert "lineweight" not in _normalize_entity(raw, 0)


class TestTextPlacement:
    def test_mtext_keeps_rotation_attachment_and_drops_format_codes(self, parsed) -> None:
        doc = ezdxf.new("R2010", setup=False)
        doc.modelspace().add_mtext(
            "{\\fArial|b1;ROOM}\\P101",
            dxfattribs={"insert": (10, 20), "char_height": 250, "rotation": 90, "attachment_point": 5},
        )
        (mt,) = _placed(parsed(doc), "MTEXT")
        gd = mt["geometry_data"]
        assert gd["text"] == "ROOM\n101"
        assert gd["rotation"] == pytest.approx(math.pi / 2)
        assert gd["attachment_point"] == 5
        front = _normalize_entity(mt, 0)
        assert front["type"] == "TEXT"
        assert front["attachment_point"] == 5
        assert front["rotation"] == pytest.approx(math.pi / 2)

    def test_justified_text_anchors_on_its_alignment_point(self, parsed) -> None:
        doc = ezdxf.new("R2010", setup=False)
        t = doc.modelspace().add_text("AXIS A", dxfattribs={"height": 300})
        t.set_placement((1000, 2000), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)
        (txt,) = _placed(parsed(doc), "TEXT")
        front = _normalize_entity(txt, 0)
        assert front["halign"] == 1
        assert front["valign"] == 2
        assert front["align_point"] == {"x": 1000, "y": 2000}

    def test_left_baseline_text_carries_no_alignment(self, parsed) -> None:
        doc = ezdxf.new("R2010", setup=False)
        doc.modelspace().add_text("NOTE", dxfattribs={"insert": (1, 2), "height": 2.5})
        (txt,) = _placed(parsed(doc), "TEXT")
        front = _normalize_entity(txt, 0)
        assert "halign" not in front
        assert "align_point" not in front


class TestDimensions:
    def _linear(self) -> Any:
        doc = ezdxf.new("R2010", setup=True)
        dim = doc.modelspace().add_linear_dim(base=(0, 500), p1=(0, 0), p2=(3000, 0), dimstyle="EZDXF")
        dim.render()
        return doc

    def test_a_linear_dimension_brings_its_block_and_value(self, parsed) -> None:
        result = parsed(self._linear())
        (dim,) = _placed(result, "DIMENSION")
        gd = dim["geometry_data"]
        assert gd["block_name"].startswith("*D")
        assert gd["measurement"] == pytest.approx(3000.0)
        assert gd["dimension_type"] == 0
        assert gd["defpoint2"] == {"x": 0.0, "y": 0.0}
        assert gd["defpoint3"] == {"x": 3000.0, "y": 0.0}
        assert gd["text_midpoint"]["x"] == pytest.approx(1500.0)
        members = [e for e in result["entities"] if e.get("block") == gd["block_name"]]
        kinds = {m["entity_type"] for m in members}
        assert {"LINE", "MTEXT"} <= kinds

    def test_the_viewer_gets_a_dimension_it_can_place_or_draw(self, parsed) -> None:
        (dim,) = _placed(parsed(self._linear()), "DIMENSION")
        front = _normalize_entity(dim, 3)
        assert front["type"] == "DIMENSION"
        assert front["block_name"].startswith("*D")
        assert front["measurement"] == pytest.approx(3000.0)
        assert front["start"] == {"x": 0.0, "y": 0.0}
        assert front["end"] == {"x": 3000.0, "y": 0.0}
        assert front["dim_line_point"] == {"x": 0.0, "y": 500.0}
        assert front["text_position"]["x"] == pytest.approx(1500.0)
        # "<>" means "the measured value", which the viewer substitutes.
        assert front["text_override"] in ("", "<>")


class TestSolidFill:
    def test_a_solid_becomes_a_closed_outline_in_drawing_order(self, parsed) -> None:
        doc = ezdxf.new("R2010", setup=False)
        # SOLID stores its corners in Z order: 0, 1, 3, 2 is the outline.
        doc.modelspace().add_solid([(0, 0), (10, 0), (0, 10), (10, 10)])
        (solid,) = _placed(parsed(doc), "SOLID")
        front = _normalize_entity(solid, 0)
        assert front["type"] == "LWPOLYLINE"
        assert front["closed"] is True
        assert front["filled"] is True
        assert [(v["x"], v["y"]) for v in front["vertices"]] == [(0, 0), (10, 0), (10, 10), (0, 10)]

    def test_a_triangle_solid_drops_its_repeated_corner(self, parsed) -> None:
        doc = ezdxf.new("R2010", setup=False)
        doc.modelspace().add_solid([(0, 0), (10, 0), (5, 5)])
        (solid,) = _placed(parsed(doc), "SOLID")
        assert len(_normalize_entity(solid, 0)["vertices"]) == 3
