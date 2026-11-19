# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Road/rail setting out with a profile: the P0-8 worked example, spirals and the stake list."""

from __future__ import annotations

import math

import pytest

from app.modules.setting_out.design_io import alignment_from_json, alignment_to_json, parse_landxml
from app.modules.setting_out.road_geometry import (
    AS_BUILT,
    STAKE,
    ProfileError,
    Pvi,
    VerticalProfile,
    chainages,
    cut_fill,
    stake_list,
)
from app.modules.setting_out.stakeout_math import Alignment, LineElement, SpiralElement

# PVI 1+200 at 52.400, g1 = +2.0 %, g2 = -1.5 %, L = 160 m.
PROFILE = VerticalProfile((Pvi(1000.0, 48.400), Pvi(1200.0, 52.400, 160.0), Pvi(1400.0, 49.400)))


def test_vertical_curve_worked_example() -> None:
    [curve] = PROFILE.curves()
    assert curve.g1 == pytest.approx(0.02)
    assert curve.g2 == pytest.approx(-0.015)
    assert curve.bvc == 1120.0
    assert round(curve.bvc_level, 3) == 50.800
    assert round(PROFILE.level_at(1180.0), 3) == 51.606
    ch, level = curve.turning_point()
    assert round(ch, 2) == 1211.43
    assert round(level, 3) == 51.714


def test_measured_level_gives_34_mm() -> None:
    dz = round((51.640 - PROFILE.level_at(1180.0)) * 1000)
    assert dz == 34
    assert cut_fill(dz, AS_BUILT) == "fill"
    assert cut_fill(dz, STAKE) == "cut"
    assert cut_fill(0.2) == "on_grade"


def test_profile_outside_raises_srv070() -> None:
    with pytest.raises(ProfileError, match="does not cover chainage 1500.000"):
        PROFILE.level_at(1500.0)


def test_straight_grades_outside_the_curve() -> None:
    assert PROFILE.level_at(1100.0) == pytest.approx(50.400)
    assert PROFILE.level_at(1300.0) == pytest.approx(50.900)


def test_chainages_on_round_multiples_with_joints() -> None:
    assert chainages(1005.0, 1050.0, 20.0, [1033.3]) == [1005.0, 1020.0, 1033.3, 1040.0, 1050.0]


def test_stake_list_marks_uncovered_and_cut_fill() -> None:
    al = Alignment((LineElement((0.0, 0.0), (0.0, 300.0)),), 1150.0)
    rows = stake_list(al, PROFILE, 10.0, offsets=(0.0, 3.5), crossfall_pct=2.5, measured={(1180.0, 0.0): 51.640})
    hit = next(r for r in rows.rows if r.chainage == 1180.0 and r.offset == 0.0)
    assert round(hit.design_z, 3) == 51.606
    assert hit.cut_fill == "cut"
    assert hit.dz_mm == pytest.approx(33.75, abs=0.06)
    right = next(r for r in rows.rows if r.chainage == 1180.0 and r.offset == 3.5)
    assert right.e == pytest.approx(3.5)
    assert right.design_z == pytest.approx(PROFILE.level_at(1180.0) - 3.5 * 0.025)
    assert rows.uncovered == [1410.0, 1420.0, 1430.0, 1440.0, 1450.0]


def test_clothoid_from_tangent_to_radius() -> None:
    sp = SpiralElement((0.0, 0.0), 0.0, 100.0, None, 500.0, ccw=False)
    # Deflection at the end is L / (2R) = 0.1 rad; clothoid series x = L - L^3/(40 R^2), y = L^2/(6R) - L^4/(336 R^3).
    assert math.degrees(sp.azimuth_at(100.0)) == pytest.approx(math.degrees(0.1))
    e, n = sp.end
    assert n == pytest.approx(100.0 - 100.0**3 / (40 * 500.0**2), abs=1e-3)
    assert e == pytest.approx(100.0**2 / (6 * 500.0) - 100.0**4 / (336 * 500.0**3), abs=1e-4)
    s, off = sp.project(*sp.point(60.0, 2.0))
    assert (s, off) == (pytest.approx(60.0, abs=1e-3), pytest.approx(2.0, abs=1e-3))


LANDXML = """<?xml version="1.0"?>
<LandXML xmlns="http://www.landxml.org/schema/LandXML-1.2" version="1.2">
 <Alignments>
  <Alignment name="Main" staStart="1000" length="300">
   <CoordGeom>
    <Line><Start>0 0</Start><End>100 0</End></Line>
    <Spiral length="100" radiusStart="INF" radiusEnd="500" rot="cw" spiType="clothoid">
     <Start>100 0</Start><PI>166.67 0</PI><End>199.75 3.33</End>
    </Spiral>
    <Spiral rot="cw"><Start>199.75 3.33</Start></Spiral>
   </CoordGeom>
   <Profile><ProfAlign name="FG">
    <PVI>1000 48.4</PVI><ParaCurve length="160">1200 52.4</ParaCurve><PVI>1400 49.4</PVI>
   </ProfAlign></Profile>
  </Alignment>
 </Alignments>
</LandXML>"""


def test_landxml_reads_spiral_and_profile_and_reports_srv071() -> None:
    out = parse_landxml(LANDXML)
    assert out.alignment is not None
    assert [type(e).__name__ for e in out.alignment.elements] == ["LineElement", "SpiralElement"]
    assert out.spirals_skipped == [3]
    assert any("SRV-071" in p.message for p in out.problems)
    assert out.profile is not None
    assert round(out.profile.level_at(1180.0), 3) == 51.606
    # Start->PI runs along N (LandXML writes N first), so the tangent azimuth is 0.
    spiral = out.alignment.elements[1]
    assert spiral.azimuth_deg == pytest.approx(0.0)
    again = alignment_from_json(alignment_to_json(out.alignment))
    assert again.point_at(1150.0) == pytest.approx(out.alignment.point_at(1150.0))
