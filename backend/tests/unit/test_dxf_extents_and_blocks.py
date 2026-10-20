# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""What box the DXF path stores, and what a block reference brings with it.

Three defects met here, all of them invisible to the suite because nothing
compared the parser's answer to the service's answer for the same drawing:

* ``parse_dxf`` unioned every layout into one extents, so an A3 title block in
  Layout1 made a 10-unit drawing report 420x297 - a box nobody is ever shown,
  and the box the unit inference reads.
* Its extents loop looked for ``insertion_point``, which no writer in this
  codebase emits - every writer emits ``insert`` - so a block placement was
  invisible to the parser while the service's copy of the same rule saw it.
  The two functions reported different boxes for the same file.
* Rotation was passed through in ezdxf's degrees while the viewer feeds it
  straight to ``ctx.rotate``, which is radians. Text authored at 90 degrees
  rendered at 90 radians.

The last class of test here is the one that would have caught the second
defect on the day it landed: it asserts the two functions agree.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import ezdxf
import pytest

from app.modules.dwg_takeoff.dxf_processor import parse_dxf
from app.modules.dwg_takeoff.service import _extents_from_raw_entities, _normalize_entity, visible_entities

A3_SHEET = (420.0, 297.0)


def _new_doc() -> Any:
    """An empty R2000 document with units pinned to unitless.

    R2000 rather than R12: R12 silently drops ``$INSUNITS`` on export, and
    leaving the unit unresolved would let the extents-based unit guess fire on
    the very numbers these tests are about.
    """
    doc = ezdxf.new("R2000", setup=False)
    doc.header["$INSUNITS"] = 0
    return doc


@pytest.fixture
def parsed(tmp_path: Path):
    """Save a document and push it through the real parser."""

    def _parse(doc: Any, name: str = "drawing.dxf") -> dict[str, Any]:
        path = tmp_path / name
        doc.saveas(str(path))
        return parse_dxf(str(path))

    return _parse


class TestPaperSpaceDoesNotSetTheModelExtents:
    def test_a_sheet_border_is_excluded_from_the_stored_box(self, parsed) -> None:
        doc = _new_doc()
        doc.modelspace().add_line((0, 0), (10, 10))
        doc.layout("Layout1").add_line((0, 0), A3_SHEET)

        result = parsed(doc)

        assert result["extents"] == {"min_x": 0.0, "min_y": 0.0, "max_x": 10.0, "max_y": 10.0}
        # The sheet is still a sheet - it is only excluded from the box, not
        # dropped. Both layouts remain selectable.
        assert result["layouts"] == ["Model", "Layout1"]

    def test_a_drawing_with_no_model_content_keeps_its_real_box(self, parsed) -> None:
        """The consequence of the filter, stated as a test.

        A sheet set where everything was drawn in paper space would otherwise
        report no extents at all and land on the parser's 0..1000 placeholder.
        It gets its real paper-space box instead: wrong about coordinate
        system, right about magnitude, and magnitude is all the unit inference
        reads.
        """
        doc = _new_doc()
        doc.layout("Layout1").add_line((0, 0), A3_SHEET)

        result = parsed(doc)

        assert result["extents"] == {"min_x": 0.0, "min_y": 0.0, "max_x": 420.0, "max_y": 297.0}


class TestBlockPlacementsReachTheExtents:
    def test_an_insert_moves_the_stored_box(self, parsed) -> None:
        """The ``insertion_point``/``insert`` mismatch, pinned.

        Before the fix this file reported 10x10 from the parser and 30x10 from
        the service, for the same entities, and no test compared them.
        """
        doc = _new_doc()
        doc.modelspace().add_line((0, 0), (10, 10))
        doc.blocks.new(name="DETAIL").add_line((0, 0), (2, 2))
        doc.modelspace().add_blockref("DETAIL", (30, 0))

        result = parsed(doc)

        assert result["extents"] == {"min_x": 0.0, "min_y": 0.0, "max_x": 30.0, "max_y": 10.0}


class TestBlockDefinitionsTravelWithTheDrawing:
    """The block's geometry ships once, tagged, and out of the extents."""

    def _door_drawing(self) -> Any:
        doc = _new_doc()
        doc.modelspace().add_line((0, 0), (10, 10))
        block = doc.blocks.new(name="DOOR-900")
        # Authored around the block's own origin, running out to x=900 there.
        block.add_line((0, 0), (900, 0))
        doc.modelspace().add_blockref("DOOR-900", (5, 5))
        return doc

    def test_the_definition_is_serialized_and_tagged(self, parsed) -> None:
        result = parsed(self._door_drawing())

        members = [e for e in result["entities"] if e.get("block")]
        assert [(e["block"], e["entity_type"]) for e in members] == [("DOOR-900", "LINE")]
        # A definition member is drawn only where an INSERT places it, so it
        # has no sheet of its own and never appears in the picker.
        assert result["layouts"] == ["Model", "Layout1"]

    def test_every_entity_carries_a_sheet_or_a_block_never_both(self, parsed) -> None:
        result = parsed(self._door_drawing())

        for entity in result["entities"]:
            assert ("layout" in entity) is not bool(entity.get("block"))

    def test_block_local_coordinates_stay_out_of_the_extents(self, parsed) -> None:
        result = parsed(self._door_drawing())

        # The 900 means something only inside the door. The drawing runs to
        # the model line and the placement, not to a block's internal reach.
        assert result["extents"] == {"min_x": 0.0, "min_y": 0.0, "max_x": 10.0, "max_y": 10.0}

    def test_definition_members_count_as_entities_but_not_against_a_layer(self, parsed) -> None:
        """Two counters, deliberately different, because they answer different questions.

        ``entity_count`` counts records on the wire, and a definition member is
        one. The layer panel counts what a toggle would remove, and a toggle
        removes nothing here: a block's members are governed by the INSERT that
        places them, not by their own authoring layer.
        """
        result = parsed(self._door_drawing())

        assert result["entity_count"] == 3  # model line + insert + definition member
        by_layer = {layer["name"]: layer["entity_count"] for layer in result["layers"]}
        assert by_layer["0"] == 2

    def test_nested_definitions_are_followed(self, parsed) -> None:
        doc = _new_doc()
        inner = doc.blocks.new(name="INNER")
        inner.add_line((0, 0), (1, 1))
        outer = doc.blocks.new(name="OUTER")
        outer.add_blockref("INNER", (0, 0))
        doc.modelspace().add_blockref("OUTER", (0, 0))

        result = parsed(doc)

        assert {e["block"] for e in result["entities"] if e.get("block")} == {"OUTER", "INNER"}

    def test_an_unplaced_definition_costs_nothing(self, parsed) -> None:
        """Only what an INSERT references is emitted.

        ``doc.blocks`` also holds the layout blocks and every anonymous
        ``*D``/``*U`` block a dimension or hatch left behind. Walking the block
        table instead of the placements would ship all of them, and duplicate
        model space into the bargain.
        """
        doc = _new_doc()
        doc.modelspace().add_line((0, 0), (10, 10))
        doc.blocks.new(name="UNPLACED").add_line((0, 0), (900, 0))

        result = parsed(doc)

        assert [e for e in result["entities"] if e.get("block")] == []
        assert result["entity_count"] == 1


class TestRotationIsRadiansOnTheWire:
    """One unit for rotation, chosen by what the renderer already does.

    ``dxf-renderer.ts`` calls ``ctx.rotate(-entity.rotation)``, and canvas
    takes radians. The DDC/DWG parser already emitted radians and this path
    emitted ezdxf's degrees, so the same authored angle rendered differently
    depending on which format the user uploaded.
    """

    def test_text_rotation_is_converted(self, parsed) -> None:
        doc = _new_doc()
        doc.modelspace().add_text("HI", dxfattribs={"height": 2.5, "insert": (1, 1), "rotation": 90.0})

        result = parsed(doc)

        text = next(e for e in result["entities"] if e["entity_type"] == "TEXT")
        assert text["geometry_data"]["rotation"] == pytest.approx(math.pi / 2)

    def test_insert_rotation_is_converted(self, parsed) -> None:
        doc = _new_doc()
        doc.blocks.new(name="DETAIL").add_line((0, 0), (2, 2))
        doc.modelspace().add_blockref(
            "DETAIL",
            (0, 0),
            dxfattribs={"rotation": 180.0, "xscale": 2.0, "yscale": 3.0},
        )

        result = parsed(doc)

        insert = next(e for e in result["entities"] if e["entity_type"] == "INSERT")
        geometry = insert["geometry_data"]
        assert geometry["rotation"] == pytest.approx(math.pi)
        # The scale factors are untouched - they are ratios, not angles.
        assert geometry["x_scale"] == 2.0
        assert geometry["y_scale"] == 3.0


class TestTheWireForm:
    """What ``get_entities`` actually hands the viewer.

    Every other test here reads the parser's stored form. The contract the
    frontend codes against is the form after the layer filter and
    ``_normalize_entity``, and those two steps are where a definition member
    can still be lost: it carries its authoring layer, usually "0", which is
    rarely the layer its INSERT sits on, so any layer toggle that hides "0"
    used to delete the geometry while keeping the placement that needs it. The
    block then renders empty, and nothing on the frontend side can diagnose
    why.
    """

    def _doc(self) -> Any:
        doc = _new_doc()
        block = doc.blocks.new(name="DOOR-900")
        # Authored on "0", the CAD default for block internals.
        block.add_line((0, 0), (900, 0))
        doc.modelspace().add_blockref("DOOR-900", (5, 5), dxfattribs={"layer": "DOORS"})
        doc.modelspace().add_line((0, 0), (10, 10), dxfattribs={"layer": "NOTES"})
        return doc

    def test_hiding_the_authoring_layer_keeps_the_definition(self, parsed) -> None:
        entities = parsed(self._doc())["entities"]

        # The viewer asks for the placement's layer only. "0" is off.
        kept = visible_entities(entities, ["DOORS"])

        assert [e.get("block") for e in kept if e.get("block")] == ["DOOR-900"]
        assert [e["entity_type"] for e in kept] == ["INSERT", "LINE"]

    def test_an_ordinary_entity_on_a_hidden_layer_is_dropped(self, parsed) -> None:
        entities = parsed(self._doc())["entities"]

        kept = visible_entities(entities, ["DOORS"])

        # The exemption is for definition members, not a blanket amnesty: the
        # note line is on "NOTES", carries no block, and goes.
        assert not [e for e in kept if e.get("layer") == "NOTES"]

    def test_no_filter_keeps_everything(self, parsed) -> None:
        entities = parsed(self._doc())["entities"]

        assert visible_entities(entities, None) == entities

    def test_the_either_or_invariant_survives_normalization(self, parsed) -> None:
        entities = parsed(self._doc())["entities"]

        wire = [_normalize_entity(e, i) for i, e in enumerate(visible_entities(entities, ["DOORS"]))]

        for entity in wire:
            assert ("layout" in entity) is not bool(entity.get("block"))
        member = next(e for e in wire if e.get("block") == "DOOR-900")
        assert member["type"] == "LINE"
        assert "layout" not in member

    def test_a_dwg_shaped_record_reaches_the_wire_the_same_way(self) -> None:
        """The DDC path writes the same two tags, so it gets the same contract.

        Built by hand rather than parsed: the DWG path needs an Excel export to
        run, and what is under test here is the shape those two writers share,
        not either parser.
        """
        stored = [
            {
                "entity_type": "LINE",
                "layer": "0",
                "color": "#ffffff",
                "block": "DOOR-900",
                "geometry_data": {"start": {"x": 0, "y": 0}, "end": {"x": 900, "y": 0}},
            },
            {
                "entity_type": "INSERT",
                "layer": "DOORS",
                "color": "#ffffff",
                "layout": "*Model_Space",
                "geometry_data": {"insert": {"x": 5, "y": 5}},
            },
        ]

        wire = [_normalize_entity(e, i) for i, e in enumerate(visible_entities(stored, ["DOORS"]))]

        assert [e.get("block") for e in wire] == ["DOOR-900", None]
        for entity in wire:
            assert ("layout" in entity) is not bool(entity.get("block"))


class TestTheTwoExtentsFunctionsAgree:
    """The comparison no test made.

    ``parse_dxf`` stores an extents on the version row; ``_extents_from_raw_
    entities`` recomputes one from the same stored entities for the lazy units
    backfill. A rule written once per caller is only ever tested at the caller
    that happened to be right, and here the parser was the wrong one - so the
    backfill could overwrite a correct stored box with a different number.
    """

    def _cases(self) -> dict[str, Any]:
        plain = _new_doc()
        plain.modelspace().add_line((0, 0), (10, 10))

        with_sheet = _new_doc()
        with_sheet.modelspace().add_line((0, 0), (10, 10))
        with_sheet.layout("Layout1").add_line((0, 0), A3_SHEET)

        with_block = _new_doc()
        with_block.modelspace().add_line((0, 0), (10, 10))
        with_block.blocks.new(name="DOOR-900").add_line((0, 0), (900, 0))
        with_block.modelspace().add_blockref("DOOR-900", (30, 0))

        sheet_only = _new_doc()
        sheet_only.layout("Layout1").add_line((0, 0), A3_SHEET)

        return {
            "plain": plain,
            "with_sheet": with_sheet,
            "with_block": with_block,
            "sheet_only": sheet_only,
        }

    def test_the_service_recomputes_what_the_parser_stored(self, parsed) -> None:
        for name, doc in self._cases().items():
            result = parsed(doc, f"{name}.dxf")
            recomputed = _extents_from_raw_entities(result["entities"])
            assert recomputed == result["extents"], name


class TestEllipticalArcsKeepTheirRange:
    """An ELLIPSE with a parameter range is an arc (a door swing), not a whole oval."""

    def test_the_wire_entity_carries_radii_rotation_and_range(self, parsed) -> None:
        doc = _new_doc()
        doc.modelspace().add_ellipse((10, 20), major_axis=(0, 600), ratio=0.5, start_param=0.0, end_param=math.pi / 2)
        entities = parsed(doc)["entities"]
        (wire,) = [_normalize_entity(e, i) for i, e in enumerate(entities) if e["entity_type"] == "ELLIPSE"]
        assert wire["major_radius"] == pytest.approx(600)
        assert wire["minor_radius"] == pytest.approx(300)
        assert wire["rotation"] == pytest.approx(math.pi / 2)
        assert (wire["start_angle"], wire["end_angle"]) == (pytest.approx(0.0), pytest.approx(math.pi / 2))
