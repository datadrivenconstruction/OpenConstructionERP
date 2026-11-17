# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""LandXML surfaces: the demo pad, namespaces, refused units and hostile XML."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.surfaces_volumes.landxml import parse_landxml
from app.modules.surfaces_volumes.tin import Tin

DEMO = Path(__file__).resolve().parents[3] / "app" / "modules" / "survey_core" / "demo" / "riverside"

NS = "http://www.landxml.org/schema/LandXML-1.2"


def _doc(body: str, units: str = '<Metric linearUnit="meter" areaUnit="squareMeter" volumeUnit="cubicMeter"/>') -> str:
    return f'<?xml version="1.0"?><LandXML xmlns="{NS}" version="1.2"><Units>{units}</Units>{body}</LandXML>'


def test_demo_design_pad_is_a_flat_6000_m2_surface_at_34_3() -> None:
    f = parse_landxml((DEMO / "design_pad.xml").read_text(encoding="utf-8"))
    assert f.epsg == 32633
    assert f.problems == []
    [s] = f.surfaces
    assert s.name == "Pad"
    assert len(s.faces) == 2
    tin = Tin.from_faces(s.e, s.n, s.z, s.faces)
    assert tin.area() == pytest.approx(6000.0)
    assert set(round(z, 3) for z in s.z) == {34.3}
    # LandXML writes northing first: E must land in the 389000 range.
    assert min(s.e) == pytest.approx(389000.0)
    assert min(s.n) == pytest.approx(5819000.0)


def test_points_without_faces_are_triangulated_later() -> None:
    body = (
        "<Surfaces><Surface name='Raw'><Definition surfType='TIN'><Pnts>"
        "<P id='1'>0 0 1</P><P id='2'>0 10 1</P><P id='3'>10 10 2</P><P id='4'>10 0 2</P>"
        "</Pnts></Definition></Surface></Surfaces>"
    )
    [s] = parse_landxml(_doc(body)).surfaces
    assert s.faces == []
    assert Tin.from_points(s.e, s.n, s.z).area() == pytest.approx(100.0)


def test_invisible_faces_and_broken_references_are_reported_not_used() -> None:
    body = (
        "<Surfaces><Surface name='S'><Definition surfType='TIN'><Pnts>"
        "<P id='1'>0 0 1</P><P id='2'>0 10 1</P><P id='3'>10 10 2</P>"
        "</Pnts><Faces><F>1 2 3</F><F i='1'>1 2 3</F><F>1 2 9</F></Faces></Definition></Surface></Surfaces>"
    )
    f = parse_landxml(_doc(body))
    assert len(f.surfaces[0].faces) == 1
    assert any("missing point" in p for p in f.problems)


def test_imperial_files_are_refused() -> None:
    with pytest.raises(ValueError, match="Imperial"):
        parse_landxml(_doc("<Surfaces/>", units='<Imperial linearUnit="USSurveyFoot"/>'))


def test_entity_expansion_is_refused() -> None:
    bomb = (
        '<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;">]>'
        f'<LandXML xmlns="{NS}">&b;</LandXML>'
    )
    with pytest.raises(ValueError):
        parse_landxml(bomb)


def test_not_landxml_is_refused() -> None:
    with pytest.raises(ValueError):
        parse_landxml("<gml/>")
    with pytest.raises(ValueError):
        parse_landxml("not xml at all")
