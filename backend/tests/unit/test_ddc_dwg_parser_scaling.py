# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The vertex rows of a DDC export are read once, not once per polyline.

A 22 MB drawing sat in "converting" for over an hour and was then declared
dead. The DDC subprocess had long finished; the phase that had not was the
xlsx parse, which recovered each polyline's terminal End Point by re-reading
every row of the export once per polyline. That is O(polylines x rows), in
the one phase of the DWG pipeline with no timeout on it.

Wall-clock cannot express that on a shared runner, so these tests count work.
``_parse_coord`` is called three times per vertex row by the collection pass.
A second pass over the vertex rows shows up as a fourth call per row, whatever
the fixture size, so the count is an exact assertion rather than a threshold.

Exact, not ``<=``, deliberately. An upper bound of ``3n`` would be satisfied by
a parser that made the three lookups lazy and then added a second pass back,
which is ``2n``, and that is precisely the regression this file exists to stop.
The cost of exactness is that a genuine optimisation also turns it red: if you
short-circuit ``sp or pt or ep`` and the count drops, lower the constant and
keep the test. A drop is fine. A rise is the bug coming back.

The remaining tests pin the behaviour the collection pass has to preserve,
because a faster parser that loses the tail vertex is not a fix.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.dwg_takeoff import ddc_dwg_parser
from app.modules.dwg_takeoff.ddc_dwg_parser import parse_ddc_dwg_excel

COLUMNS = [
    "Description",
    "ID",
    "Name",
    "Layer",
    "ParentID",
    "Color",
    "Color Index",
    "On",
    "Frozen",
    "Closed",
    "Start Point",
    "End Point",
    "Point",
]


def _row(**cells: object) -> list[object]:
    """Build one export row, leaving every unnamed column blank."""
    unknown = set(cells) - set(COLUMNS)
    assert not unknown, f"column not in the DDC export header: {sorted(unknown)}"
    return [cells.get(name) for name in COLUMNS]


LAYER = _row(Description="<AcDbLayerTableRecord>", Name="A-WALL", Color=7, On=True, Frozen=False)


def _vertex(parent: str, start: str, end: str | None = None) -> list[object]:
    cells: dict[str, object] = {"Description": "<AcDbVertex>", "ParentID": parent}
    cells["Start Point"] = start
    if end is not None:
        cells["End Point"] = end
    return _row(**cells)


def _polyline(eid: str, closed: str = "false") -> list[object]:
    return _row(Description="<AcDbPolyline>", ID=eid, Layer="A-WALL", Closed=closed)


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


def _points(result: dict) -> list[list[tuple[float, float]]]:
    return [
        [(p["x"], p["y"]) for p in e["geometry_data"]["points"]]
        for e in result["entities"]
        if e["entity_type"] == "LWPOLYLINE"
    ]


class TestVertexRowsAreReadOnce:
    """The cost of the parse must track the size of the export, not its square."""

    @pytest.mark.parametrize(("polylines", "verts"), [(1, 3), (4, 5), (10, 4)])
    def test_parse_coord_is_called_three_times_per_vertex_row(
        self, export, monkeypatch, polylines: int, verts: int
    ) -> None:
        calls = 0
        real = ddc_dwg_parser._parse_coord

        def counting(value: object):
            nonlocal calls
            calls += 1
            return real(value)

        monkeypatch.setattr(ddc_dwg_parser, "_parse_coord", counting)

        rows = [LAYER]
        for p in range(polylines):
            rows.append(_polyline(f"PL{p}"))
        for p in range(polylines):
            for v in range(verts):
                rows.append(_vertex(f"PL{p}", f"[{v}.0 {p}.0]", f"[{v + 1}.0 {p}.0]"))

        export(rows)

        # Start Point, Point, End Point. Nothing else may look at these rows:
        # a second visit is a second pass, and a second pass over the vertex
        # rows is quadratic the moment it sits inside a per-polyline loop.
        assert calls == 3 * polylines * verts


class TestTheTailVertexSurvives:
    """Whatever the collection pass does, the open-polyline tail is kept."""

    def test_end_point_on_the_last_vertex_only(self, export) -> None:
        result = export(
            [
                LAYER,
                _polyline("PL1"),
                _vertex("PL1", "[0.0 0.0]"),
                _vertex("PL1", "[1.0 0.0]"),
                _vertex("PL1", "[2.0 0.0]", "[3.0 0.0]"),
            ]
        )
        assert _points(result) == [[(0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (3.0, 0.0)]]

    def test_end_point_on_every_vertex_keeps_only_the_last(self, export) -> None:
        result = export(
            [
                LAYER,
                _polyline("PL1"),
                _vertex("PL1", "[0.0 0.0]", "[1.0 0.0]"),
                _vertex("PL1", "[1.0 0.0]", "[2.0 0.0]"),
                _vertex("PL1", "[2.0 0.0]", "[3.0 0.0]"),
            ]
        )
        assert _points(result) == [[(0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (3.0, 0.0)]]

    def test_tail_equal_to_the_last_start_is_not_repeated(self, export) -> None:
        result = export(
            [
                LAYER,
                _polyline("PL1"),
                _vertex("PL1", "[0.0 0.0]"),
                _vertex("PL1", "[2.0 0.0]", "[2.0 0.0]"),
            ]
        )
        assert _points(result) == [[(0.0, 0.0), (2.0, 0.0)]]

    def test_interleaved_polylines_do_not_borrow_each_others_tails(self, export) -> None:
        result = export(
            [
                LAYER,
                _polyline("PL1"),
                _polyline("PL2", closed="true"),
                _vertex("PL1", "[0.0 0.0]"),
                _vertex("PL2", "[10.0 0.0]"),
                _vertex("PL1", "[1.0 0.0]", "[9.0 9.0]"),
                _vertex("PL2", "[11.0 0.0]", "[12.0 0.0]"),
            ]
        )
        assert _points(result) == [
            [(0.0, 0.0), (1.0, 0.0), (9.0, 9.0)],
            [(10.0, 0.0), (11.0, 0.0), (12.0, 0.0)],
        ]
