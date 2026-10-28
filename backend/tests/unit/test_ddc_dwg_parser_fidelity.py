# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠What the DDC DWG parser keeps, and what it throws away.

A v12.6.1 report said DWG files upload but the drawing does not look like the
source. Nothing covered ``parse_ddc_dwg_excel``, so every fidelity loss was
invisible to the suite. These tests pin the current behaviour: the parts that
are correct stay correct, and each known loss is asserted explicitly so that
whoever repairs it sees exactly one test turn red per repair.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from app.modules.dwg_takeoff.ddc_dwg_parser import parse_ddc_dwg_excel

COLUMNS = [
    "Description",
    "ID",
    "Name",
    "Layer",
    "BlockId",
    "Color",
    "Color Index",
    "On",
    "Frozen",
    "StartPoint",
    "EndPoint",
    "Position",
    "BlockTableRecord",
    "Rotation",
    "ScaleFactors",
    "Min Extents",
    "Max Extents",
    "Pattern Name",
    "Solid Fill",
    "Closed",
    # Added for the rotation tests below. Every other row simply carries two
    # more blank cells, which is what an export column nobody reads looks like.
    "Text String",
    "Height",
    # Block-table metadata: true on exactly the records a sheet was built
    # around. Blank on every row that is not an <AcDbBlockTableRecord>.
    "Layout",
]


def _row(**cells: object) -> list[object]:
    """Build one export row, leaving every unnamed column blank."""
    unknown = set(cells) - set(COLUMNS)
    assert not unknown, f"column not in the DDC export header: {sorted(unknown)}"
    return [cells.get(name) for name in COLUMNS]


@pytest.fixture
def export(tmp_path: Path):
    """Write a DDC-shaped .xlsx and return the parsed result."""

    def _build(rows: list[list[object]]) -> dict:
        openpyxl = pytest.importorskip("openpyxl")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(COLUMNS)
        for row in rows:
            ws.append(row)
        path = tmp_path / "export.xlsx"
        wb.save(str(path))
        wb.close()
        return parse_ddc_dwg_excel(path)

    return _build


LAYER = _row(Description="<AcDbLayerTableRecord>", Name="A-WALL", Color=7, On=True, Frozen=False)


class TestBlockReferencesAreNotExpanded:
    """An INSERT keeps its insertion point; what the block draws travels apart.

    The join is left to the renderer on purpose. Expanding a block into the
    entity array here would multiply its geometry by its placement count - a
    block placed 500 times becomes 500 copies of itself - while sending the
    definition once costs one copy however often it is placed.
    """

    def test_insert_carries_no_geometry_of_its_own(self, export) -> None:
        result = export(
            [
                LAYER,
                _row(
                    Description="<AcDbBlockReference>",
                    ID="1",
                    Layer="A-WALL",
                    BlockId="*Model_Space",
                    Position="100,200,0",
                    BlockTableRecord="DOOR-900",
                    Rotation=0,
                    ScaleFactors="[1,1,1]",
                ),
            ]
        )
        inserts = [e for e in result["entities"] if e["entity_type"] == "INSERT"]
        assert len(inserts) == 1
        geometry = inserts[0]["geometry_data"]
        assert geometry["block_name"] == "DOOR-900"
        assert geometry["insert"] == {"x": 100.0, "y": 200.0}
        # A placement says where, how big and how turned - never what is drawn.
        assert "points" not in geometry
        assert "entities" not in geometry
        # The three numbers the renderer needs to place the definition are all
        # here, so the join needs nothing this parser does not already emit.
        assert geometry["x_scale"] == 1.0
        assert geometry["y_scale"] == 1.0
        assert geometry["rotation"] == 0.0

    def test_block_geometry_is_filed_under_the_block_not_offered_as_a_sheet(self, export) -> None:
        """A block definition is not a sheet, and its coordinates are not the drawing's.

        This replaces a test that pinned the opposite. ``BlockId`` carries the
        owning block-table record, which in the DWG object model is
        ``*Model_Space``, ``*Paper_Space*`` **and one entry per block
        definition**; filing all three as layouts put every door and window in
        the sheet picker as a drawable sheet, and unioned block-local
        coordinates into the drawing's extents. The DXF path never did either,
        so the same UI behaved differently depending on which format was
        uploaded - which is what showed the DWG path was wrong rather than
        merely different.
        """
        result = export(
            [
                LAYER,
                _row(
                    Description="<AcDbLine>",
                    ID="1",
                    Layer="A-WALL",
                    BlockId="*Model_Space",
                    StartPoint="0,0,0",
                    EndPoint="50,50,0",
                ),
                _row(
                    Description="<AcDbBlockReference>",
                    ID="2",
                    Layer="A-WALL",
                    BlockId="*Model_Space",
                    Position="100,200,0",
                    BlockTableRecord="DOOR-900",
                ),
                # The block's own geometry, authored around the block's origin
                # and running out to x=900 there.
                _row(
                    Description="<AcDbLine>",
                    ID="3",
                    Layer="A-WALL",
                    BlockId="DOOR-900",
                    StartPoint="0,0,0",
                    EndPoint="900,0,0",
                ),
            ]
        )

        by_block = {e.get("block"): e["entity_type"] for e in result["entities"] if e.get("block")}
        assert by_block == {"DOOR-900": "LINE"}

        # The picker offers model space and nothing else.
        assert result["layouts"] == ["*Model_Space"]

        # Every entity carries EITHER the sheet it is drawn on or the block it
        # belongs to. Never both, never neither - that invariant is what lets
        # the viewer's sheet filter drop definition members without knowing
        # what a block is.
        for entity in result["entities"]:
            assert ("layout" in entity) is not bool(entity.get("block"))

        # And the block-local 900 is gone from the drawing's extents. The
        # drawing runs to the INSERT at (100, 200), not to a coordinate that
        # only means anything inside the door.
        assert result["extents"] == {"min_x": 0.0, "min_y": 0.0, "max_x": 100.0, "max_y": 200.0}

    def test_definition_members_count_as_entities_but_not_against_a_layer(self, export) -> None:
        """Two counters, deliberately different, because they answer different questions.

        ``entity_count`` counts records on the wire, and a definition member is
        one. A layer's count describes what toggling that layer off would
        remove, and toggling removes no definition member - the INSERT that
        places it governs that.
        """
        result = export(
            [
                LAYER,
                _row(
                    Description="<AcDbBlockReference>",
                    ID="1",
                    Layer="A-WALL",
                    BlockId="*Model_Space",
                    Position="0,0,0",
                    BlockTableRecord="DOOR-900",
                ),
                _row(
                    Description="<AcDbLine>",
                    ID="2",
                    Layer="A-WALL",
                    BlockId="DOOR-900",
                    StartPoint="0,0,0",
                    EndPoint="900,0,0",
                ),
            ]
        )
        assert result["entity_count"] == 2
        assert result["layers"][0]["entity_count"] == 1


class TestModelAndPaperSpaceAreSeparated:
    """Paper space is a sheet, and its millimetres are not the model's units."""

    def test_a_sheet_border_does_not_set_the_drawing_extents(self, export) -> None:
        result = export(
            [
                LAYER,
                _row(
                    Description="<AcDbLine>",
                    ID="1",
                    Layer="A-WALL",
                    BlockId="*Model_Space",
                    StartPoint="0,0,0",
                    EndPoint="10,10,0",
                ),
                # An A3 sheet border. Real drawings nearly always carry one.
                _row(
                    Description="<AcDbLine>",
                    ID="2",
                    Layer="A-WALL",
                    BlockId="*Paper_Space",
                    StartPoint="0,0,0",
                    EndPoint="420,297,0",
                ),
            ]
        )
        # 42x narrower than the union that used to be stored. That number is
        # also what the unit inference reads, and its threshold is 1000 raw
        # units, so a large enough title block used to relabel a unitless
        # drawing as millimetres and shift every measurement by 1000.
        assert result["extents"] == {"min_x": 0.0, "min_y": 0.0, "max_x": 10.0, "max_y": 10.0}
        # Paper space is still a sheet, unlike a block definition. Model space
        # sorts first so the viewer's auto-select lands on the drawing.
        assert result["layouts"] == ["*Model_Space", "*Paper_Space"]


class TestOwnerClassificationDoesNotDependOnNaming:
    """The block/sheet split holds whatever ``BlockId`` turns out to contain.

    We have never confirmed against a real DwgExporter build whether that
    column holds block-table record names or numeric object ids. A classifier
    that assumed names and met ids would file every entity as a block
    definition and leave the viewer with no sheet to draw - strictly worse
    than the phantom sheets being removed here. So the test that decides is
    positive evidence: a name some reference actually places is a block.
    """

    def test_an_unrecognised_owner_is_treated_as_a_sheet(self, export) -> None:
        result = export(
            [
                LAYER,
                _row(
                    Description="<AcDbLine>",
                    ID="1",
                    Layer="A-WALL",
                    BlockId="8796093022440",
                    StartPoint="0,0,0",
                    EndPoint="10,10,0",
                ),
            ]
        )
        assert result["layouts"] == ["8796093022440"]
        assert [e.get("block") for e in result["entities"]] == [None]
        # No model space contributed, so the extents fall back to everything
        # that is not block-local rather than to the 0..1000 placeholder.
        assert result["extents"] == {"min_x": 0.0, "min_y": 0.0, "max_x": 10.0, "max_y": 10.0}

    def test_everything_classified_as_a_block_falls_back_to_model_space(self, export) -> None:
        """The last-resort guard: a drawing must never arrive with no sheet.

        Contrived - it takes two references placing each other's owner - but
        it is the shape that would leave ``layouts`` empty, and an empty
        picker renders as a blank canvas.
        """
        result = export(
            [
                LAYER,
                _row(
                    Description="<AcDbBlockReference>",
                    ID="1",
                    Layer="A-WALL",
                    BlockId="B",
                    Position="0,0,0",
                    BlockTableRecord="A",
                ),
                _row(
                    Description="<AcDbBlockReference>",
                    ID="2",
                    Layer="A-WALL",
                    BlockId="A",
                    Position="10,10,0",
                    BlockTableRecord="B",
                ),
            ]
        )
        assert result["layouts"] == ["*Model_Space"]
        assert all(e["layout"] == "*Model_Space" for e in result["entities"])
        assert all("block" not in e for e in result["entities"])
        assert result["extents"] == {"min_x": 0.0, "min_y": 0.0, "max_x": 10.0, "max_y": 10.0}


class TestTheBlockTableDecidesWhenTheExportCarriesOne:
    """``<AcDbBlockTableRecord>`` rows answer block-or-sheet outright.

    Every heuristic beside this one is inference about a name. The export
    ships the drawing's own block table, and each record carries a ``Layout``
    flag that is true for exactly the records a sheet was built around. A real
    17 MB export carried 809 records with the flag true for two of them,
    ``*Model_Space`` and ``*Paper_Space``, and false for the other 807.

    This is what settles the definitions no reference places. An unplaced
    door block is referenced by nothing and is not anonymous, so the two
    weaker tests both had to let it through as a sheet; the block table says
    plainly that it is a block.
    """

    def test_an_unplaced_definition_is_a_block_not_a_sheet(self, export) -> None:
        result = export(
            [
                LAYER,
                _row(Description="<AcDbBlockTableRecord>", Name="*Model_Space", Layout="True"),
                _row(Description="<AcDbBlockTableRecord>", Name="MIM_NO_DOOR", Layout="False"),
                _row(
                    Description="<AcDbLine>",
                    ID="1",
                    Layer="A-WALL",
                    BlockId="*Model_Space",
                    StartPoint="0,0,0",
                    EndPoint="10,10,0",
                ),
                # Placed by nothing, so only the block table can classify it.
                _row(
                    Description="<AcDbLine>",
                    ID="2",
                    Layer="A-WALL",
                    BlockId="MIM_NO_DOOR",
                    StartPoint="0,0,0",
                    EndPoint="1,1,0",
                ),
            ]
        )
        assert result["layouts"] == ["*Model_Space"]
        by_owner = {e.get("block") or e.get("layout"): e for e in result["entities"]}
        assert by_owner["MIM_NO_DOOR"]["block"] == "MIM_NO_DOOR"
        assert "layout" not in by_owner["MIM_NO_DOOR"]

    def test_a_record_flagged_as_a_layout_stays_a_sheet(self, export) -> None:
        """Even under a name the prefix rule would otherwise call anonymous."""
        result = export(
            [
                LAYER,
                _row(Description="<AcDbBlockTableRecord>", Name="*Paper_Space0", Layout="True"),
                _row(
                    Description="<AcDbLine>",
                    ID="1",
                    Layer="A-WALL",
                    BlockId="*Paper_Space0",
                    StartPoint="0,0,0",
                    EndPoint="10,10,0",
                ),
            ]
        )
        assert result["layouts"] == ["*Paper_Space0"]

    def test_an_owner_the_table_never_mentions_falls_back_to_the_heuristics(self, export) -> None:
        """A partial table must not turn every unlisted owner into a block."""
        result = export(
            [
                LAYER,
                _row(Description="<AcDbBlockTableRecord>", Name="*Model_Space", Layout="True"),
                _row(Description="<AcDbBlockTableRecord>", Name="DOOR-900", Layout="False"),
                _row(
                    Description="<AcDbLine>",
                    ID="1",
                    Layer="A-WALL",
                    BlockId="Sheet-A-101",
                    StartPoint="0,0,0",
                    EndPoint="10,10,0",
                ),
            ]
        )
        assert result["layouts"] == ["Sheet-A-101"]

    def test_a_table_that_flags_no_layout_is_not_read_at_all(self, export) -> None:
        """The guard against a build that writes no ``Layout`` column.

        Reading such a table literally makes every owner a block definition,
        which leaves the drawing with no sheet and sends every entity through
        the last-resort fallback with its block-local coordinates intact.
        """
        result = export(
            [
                LAYER,
                _row(Description="<AcDbBlockTableRecord>", Name="*Model_Space"),
                _row(Description="<AcDbBlockTableRecord>", Name="DOOR-900"),
                _row(
                    Description="<AcDbLine>",
                    ID="1",
                    Layer="A-WALL",
                    BlockId="*Model_Space",
                    StartPoint="0,0,0",
                    EndPoint="10,10,0",
                ),
                _row(
                    Description="<AcDbBlockReference>",
                    ID="2",
                    Layer="A-WALL",
                    BlockId="*Model_Space",
                    Position="0,0,0",
                    BlockTableRecord="DOOR-900",
                ),
                _row(
                    Description="<AcDbLine>",
                    ID="3",
                    Layer="A-WALL",
                    BlockId="DOOR-900",
                    StartPoint="0,0,0",
                    EndPoint="1,1,0",
                ),
            ]
        )
        # The heuristics still get it right: model space is a sheet, and the
        # door is a block because a reference places it.
        assert result["layouts"] == ["*Model_Space"]
        assert [e.get("block") for e in result["entities"] if e.get("block")] == ["DOOR-900"]


class TestAnonymousBlocksAreNotSheets:
    """A ``*`` owner that is not model or paper space is a block, not a sheet.

    AutoCAD reserves the ``*`` prefix for block-table records it writes
    itself: ``*D`` per dimension, ``*X`` per hatch, ``*U`` for an unnamed
    group. The reference test alone could not see them, because a dimension
    block is owned implicitly by its DIMENSION and never placed by an
    ``<AcDbBlockReference>`` row, so every one of them failed it and was
    offered as a sheet. A real 36 MB export offered 1108 sheets, of which
    1107 were anonymous records and one was the drawing.

    The prefix rule cannot hide a genuine sheet, which is the direction that
    would cost geometry: a real sheet is always model or paper space, and
    :func:`_is_layout_block_id` answers those first.
    """

    def test_a_dimension_block_is_not_offered_as_a_sheet(self, export) -> None:
        result = export(
            [
                LAYER,
                _row(
                    Description="<AcDbLine>",
                    ID="1",
                    Layer="A-WALL",
                    BlockId="*Model_Space",
                    StartPoint="0,0,0",
                    EndPoint="10,10,0",
                ),
                _row(
                    Description="<AcDbLine>",
                    ID="2",
                    Layer="A-WALL",
                    BlockId="*D1000",
                    StartPoint="0,0,0",
                    EndPoint="1,1,0",
                ),
            ]
        )
        assert result["layouts"] == ["*Model_Space"]
        by_owner = {e.get("block") or e.get("layout"): e for e in result["entities"]}
        assert set(by_owner) == {"*Model_Space", "*D1000"}
        # The dimension's geometry is block content: tagged, and carrying no
        # sheet, so the existing sheet filter drops it without an edit.
        assert by_owner["*D1000"]["block"] == "*D1000"
        assert "layout" not in by_owner["*D1000"]

    def test_an_anonymous_owner_does_not_reach_the_extents(self, export) -> None:
        """Block-local coordinates never describe where the drawing is."""
        result = export(
            [
                LAYER,
                _row(
                    Description="<AcDbLine>",
                    ID="1",
                    Layer="A-WALL",
                    BlockId="*Model_Space",
                    StartPoint="0,0,0",
                    EndPoint="10,10,0",
                ),
                _row(
                    Description="<AcDbLine>",
                    ID="2",
                    Layer="A-WALL",
                    BlockId="*U358",
                    StartPoint="-5000,-5000,0",
                    EndPoint="5000,5000,0",
                ),
            ]
        )
        assert result["extents"] == {"min_x": 0.0, "min_y": 0.0, "max_x": 10.0, "max_y": 10.0}

    def test_paper_space_survives_the_prefix_rule(self, export) -> None:
        """The one ``*`` family that really is a sheet stays one."""
        result = export(
            [
                LAYER,
                _row(
                    Description="<AcDbLine>",
                    ID="1",
                    Layer="A-WALL",
                    BlockId="*Paper_Space0",
                    StartPoint="0,0,0",
                    EndPoint="10,10,0",
                ),
                _row(
                    Description="<AcDbLine>",
                    ID="2",
                    Layer="A-WALL",
                    BlockId="*X7",
                    StartPoint="0,0,0",
                    EndPoint="1,1,0",
                ),
            ]
        )
        assert result["layouts"] == ["*Paper_Space0"]

    def test_a_drawing_of_nothing_but_anonymous_blocks_still_has_a_sheet(self, export) -> None:
        """The last-resort guard still holds: an empty picker is a blank canvas."""
        result = export(
            [
                LAYER,
                _row(
                    Description="<AcDbLine>",
                    ID="1",
                    Layer="A-WALL",
                    BlockId="*D1000",
                    StartPoint="0,0,0",
                    EndPoint="10,10,0",
                ),
            ]
        )
        assert result["layouts"] == ["*Model_Space"]
        assert all(e["layout"] == "*Model_Space" for e in result["entities"])
        assert all("block" not in e for e in result["entities"])


class TestHatchIsReducedToItsBoundingBox:
    def test_non_rectangular_fill_becomes_a_rectangle(self, export) -> None:
        result = export(
            [
                LAYER,
                _row(
                    Description="<AcDbHatch>",
                    ID="1",
                    Layer="A-WALL",
                    BlockId="*Model_Space",
                    **{"Min Extents": "0,0,0", "Max Extents": "100,50,0"},
                    **{"Pattern Name": "ANSI31", "Solid Fill": "false"},
                ),
            ]
        )
        hatches = [e for e in result["entities"] if e["entity_type"] == "HATCH"]
        assert len(hatches) == 1
        # Four axis-aligned corners, whatever the real boundary was. An L-shaped
        # room fills its whole bounding rectangle on screen.
        assert hatches[0]["geometry_data"]["points"] == [
            {"x": 0.0, "y": 0.0},
            {"x": 100.0, "y": 0.0},
            {"x": 100.0, "y": 50.0},
            {"x": 0.0, "y": 50.0},
        ]


class TestSplinesAreApproximated:
    def test_closed_spline_becomes_an_ellipse_on_its_bounding_box(self, export) -> None:
        result = export(
            [
                LAYER,
                _row(
                    Description="<AcDbSpline>",
                    ID="1",
                    Layer="A-WALL",
                    BlockId="*Model_Space",
                    Closed="true",
                    **{"Min Extents": "0,0,0", "Max Extents": "40,20,0"},
                ),
            ]
        )
        assert [e["entity_type"] for e in result["entities"]] == ["ELLIPSE"]
        geometry = result["entities"][0]["geometry_data"]
        assert geometry["center"] == {"x": 20.0, "y": 10.0}
        assert geometry["major_radius"] == pytest.approx(20.0)
        assert geometry["minor_radius"] == pytest.approx(10.0)
        assert geometry["end_angle"] == pytest.approx(math.pi * 2)

    def test_open_spline_becomes_a_straight_chord(self, export) -> None:
        result = export(
            [
                LAYER,
                _row(
                    Description="<AcDbSpline>",
                    ID="1",
                    Layer="A-WALL",
                    BlockId="*Model_Space",
                    Closed="false",
                    StartPoint="0,0,0",
                    EndPoint="100,100,0",
                ),
            ]
        )
        # Every control point between the ends is gone; a curve is drawn as the
        # straight line joining its endpoints.
        assert [e["entity_type"] for e in result["entities"]] == ["LINE"]
        geometry = result["entities"][0]["geometry_data"]
        assert geometry["start"] == {"x": 0.0, "y": 0.0}
        assert geometry["end"] == {"x": 100.0, "y": 100.0}


class TestWhatTheParserGetsRight:
    """Guard the correct behaviour so a fidelity repair cannot regress it."""

    def test_line_layer_and_extents_survive(self, export) -> None:
        result = export(
            [
                LAYER,
                _row(
                    Description="<AcDbLine>",
                    ID="1",
                    Layer="A-WALL",
                    BlockId="*Model_Space",
                    StartPoint="10,20,0",
                    EndPoint="110,220,0",
                ),
            ]
        )
        assert result["entity_count"] == 1
        entity = result["entities"][0]
        assert entity["entity_type"] == "LINE"
        assert entity["layer"] == "A-WALL"
        assert entity["geometry_data"]["start"] == {"x": 10.0, "y": 20.0}
        assert result["extents"] == {
            "min_x": 10.0,
            "min_y": 20.0,
            "max_x": 110.0,
            "max_y": 220.0,
        }
        assert [layer["name"] for layer in result["layers"]] == ["A-WALL"]
        assert result["layers"][0]["entity_count"] == 1

    def test_frozen_layer_is_reported_invisible(self, export) -> None:
        result = export(
            [
                _row(
                    Description="<AcDbLayerTableRecord>",
                    Name="A-HIDDEN",
                    Color=7,
                    On=True,
                    Frozen=True,
                ),
            ]
        )
        assert result["layers"][0]["visible"] is False


class TestRotationIsRadiansOnTheWire:
    """The wire format is radians, and this path was not converting to it.

    ``dxf-renderer.ts`` hands ``entity.rotation`` straight to ``ctx.rotate``,
    which takes radians, so the unit is not a preference here. The DXF path was
    fixed to convert; a comment in ``dxf_processor.py`` states that this parser
    already emitted radians, and it did not.

    The export writes an angle either as a bare number already in radians or
    with a ``d`` suffix meaning degrees, which is why the ARC branch reads its
    start and end angles through ``_parse_angle``. Rotation was read through
    ``_safe_float`` instead. ``float("90.0d")`` raises, ``_safe_float`` answers
    None, and ``or 0.0`` turned that into an unrotated entity, so a drawing
    whose export used the suffix form came back with every label upright and
    every block facing the same way, with nothing logged.

    Nothing caught it because the only rotation assertion in this file used a
    fixture that left the cell blank and asserted 0.0, and zero is zero in both
    units. An assertion that cannot tell the two apart is not a units test.
    """

    def test_a_degree_suffixed_text_rotation_becomes_radians(self, export) -> None:
        result = export(
            [
                LAYER,
                _row(
                    Description="<AcDbText>",
                    ID="1",
                    Layer="A-WALL",
                    Position="10,20,0",
                    **{"Text String": "ROOM 101", "Height": 2.5, "Rotation": "90.0d"},
                ),
            ]
        )
        texts = [e for e in result["entities"] if e["entity_type"] == "TEXT"]
        assert len(texts) == 1
        # Not 90.0, and not 0.0 either, which is what the old read produced.
        assert texts[0]["geometry_data"]["rotation"] == pytest.approx(math.pi / 2)

    def test_a_bare_text_rotation_is_already_radians_and_is_left_alone(self, export) -> None:
        result = export(
            [
                LAYER,
                _row(
                    Description="<AcDbText>",
                    ID="1",
                    Layer="A-WALL",
                    Position="10,20,0",
                    **{"Text String": "ROOM 101", "Height": 2.5, "Rotation": "1.5707963"},
                ),
            ]
        )
        texts = [e for e in result["entities"] if e["entity_type"] == "TEXT"]
        # Converting this one would be the mirror of the bug: the same number
        # would be multiplied by pi over 180 and the label would lie flat.
        assert texts[0]["geometry_data"]["rotation"] == pytest.approx(math.pi / 2)

    def test_a_degree_suffixed_block_rotation_becomes_radians(self, export) -> None:
        result = export(
            [
                LAYER,
                _row(
                    Description="<AcDbBlockReference>",
                    ID="1",
                    Layer="A-WALL",
                    BlockId="*Model_Space",
                    Position="100,200,0",
                    BlockTableRecord="DOOR-900",
                    Rotation="180.0d",
                    ScaleFactors="[1,1,1]",
                ),
            ]
        )
        inserts = [e for e in result["entities"] if e["entity_type"] == "INSERT"]
        assert len(inserts) == 1
        # A placement carries the rotation for the whole definition, so losing
        # it hangs every door in the drawing on the same side of its frame.
        assert inserts[0]["geometry_data"]["rotation"] == pytest.approx(math.pi)

    def test_a_missing_rotation_is_still_zero(self, export) -> None:
        """The absent case is the one the old read got right, and it stays right."""
        result = export(
            [
                LAYER,
                _row(
                    Description="<AcDbBlockReference>",
                    ID="1",
                    Layer="A-WALL",
                    BlockId="*Model_Space",
                    Position="100,200,0",
                    BlockTableRecord="DOOR-900",
                    ScaleFactors="[1,1,1]",
                ),
            ]
        )
        inserts = [e for e in result["entities"] if e["entity_type"] == "INSERT"]
        assert inserts[0]["geometry_data"]["rotation"] == 0.0
