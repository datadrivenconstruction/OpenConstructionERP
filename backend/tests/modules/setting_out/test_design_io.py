# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Design CSV, measured CSV and LandXML reading, including refused XML."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.setting_out.design_io import (
    alignment_from_json,
    alignment_to_json,
    parse_design_csv,
    parse_landxml,
    parse_measured_csv,
    place_on_alignment,
)

DEMO = Path(__file__).resolve().parents[3] / "app" / "modules" / "setting_out" / "demo" / "riverside"


def test_demo_design_csv_has_two_columns_with_header() -> None:
    f = parse_design_csv((DEMO / "stakeout_design.csv").read_text(encoding="utf-8"))
    assert f.problems == []
    assert [(p.point_id, p.e, p.n, p.z) for p in f.points] == [
        ("C-03", 389060.0, 5819030.0, 34.3),
        ("C-04", 389080.0, 5819030.0, 34.3),
    ]


def test_headerless_csv_reads_penz_order_and_decimal_comma() -> None:
    f = parse_design_csv("A1;100,5;200,25;10\nA2;101;201\n")
    assert [(p.point_id, p.e, p.n, p.z) for p in f.points] == [("A1", 100.5, 200.25, 10.0), ("A2", 101.0, 201.0, None)]


def test_duplicate_and_empty_rows_are_reported() -> None:
    f = parse_design_csv("point,e,n\nP1,1,2\nP1,1,3\n,4,5\nP3,x,y\n")
    assert [p.point_id for p in f.points] == ["P1"]
    assert [pr.line for pr in f.problems] == [3, 4, 5]


def test_chainage_rows_are_placed_on_the_alignment() -> None:
    al = parse_landxml((DEMO / "axis_c.xml").read_text(encoding="utf-8")).alignment
    f = parse_design_csv("point,chainage,offset\nX1,60,0\nX2,80,-1.5\n")
    place_on_alignment(f.points, al, f.problems)
    assert f.problems == []
    assert (f.points[0].e, f.points[0].n) == pytest.approx((389060.0, 5819030.0))
    # Heading east, left (negative offset) is north.
    assert (f.points[1].e, f.points[1].n) == pytest.approx((389080.0, 5819031.5))


def test_chainage_without_alignment_is_a_problem() -> None:
    f = parse_design_csv("point,chainage,offset\nX1,60,0\n")
    place_on_alignment(f.points, None, f.problems)
    assert f.points == []
    assert "alignment" in f.problems[0].message


def test_landxml_alignment_reads_northing_first() -> None:
    f = parse_landxml((DEMO / "axis_c.xml").read_text(encoding="utf-8"))
    assert f.alignment is not None
    assert f.alignment.name == "Axis C"
    assert f.alignment.length == pytest.approx(100.0)
    assert f.alignment.elements[0].start == (389000.0, 5819030.0)
    assert alignment_from_json(alignment_to_json(f.alignment)) == f.alignment


def test_landxml_cgpoints_and_curve() -> None:
    xml = """<?xml version="1.0"?>
<LandXML xmlns="http://www.landxml.org/schema/LandXML-1.2" version="1.2">
  <CgPoints><CgPoint name="S1" code="COL">200.0 100.0 5.5</CgPoint><CgPoint name="S2">201 101</CgPoint></CgPoints>
  <Alignments><Alignment name="R" staStart="10"><CoordGeom>
    <Curve rot="ccw"><Start>0 100</Start><Center>0 0</Center><End>100 0</End></Curve>
    <Spiral><Start>100 0</Start><End>110 0</End></Spiral>
  </CoordGeom></Alignment></Alignments>
</LandXML>"""
    f = parse_landxml(xml)
    assert [(p.point_id, p.e, p.n, p.z, p.code) for p in f.points] == [
        ("S1", 100.0, 200.0, 5.5, "COL"),
        ("S2", 101.0, 201.0, None, ""),
    ]
    assert f.alignment is not None
    assert f.alignment.start_chainage == 10.0
    assert any("Spiral" in p.message for p in f.problems)


def test_landxml_entity_expansion_is_refused() -> None:
    bomb = """<?xml version="1.0"?>
<!DOCTYPE LandXML [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">]>
<LandXML><CgPoints><CgPoint name="&b;">1 2</CgPoint></CgPoints></LandXML>"""
    f = parse_landxml(bomb)
    assert f.points == []
    assert "not a readable LandXML" in f.problems[0].message


def test_landxml_external_entity_is_refused() -> None:
    xxe = """<?xml version="1.0"?>
<!DOCTYPE LandXML [<!ENTITY x SYSTEM "file:///etc/passwd">]>
<LandXML><CgPoints><CgPoint name="&x;">1 2</CgPoint></CgPoints></LandXML>"""
    f = parse_landxml(xxe)
    assert f.points == []
    assert f.problems


def test_demo_measured_csv() -> None:
    rows, problems = parse_measured_csv((DEMO / "stakeout_measured.csv").read_text(encoding="utf-8"))
    assert problems == []
    c03 = next(r for r in rows if r.point_id == "C-03")
    assert (c03.e, c03.n, c03.z) == (389060.012, 5819029.991, 34.302)
    assert (c03.instrument, c03.control_ref, c03.measured_by) == ("Demo total station", "CP1, CP2", "Demo surveyor")
