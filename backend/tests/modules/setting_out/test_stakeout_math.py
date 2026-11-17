# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Stake deltas, verdicts and chainage/offset against hand-computed values (DOMAIN.md example 2)."""

from __future__ import annotations

import math

import pytest

from app.modules.setting_out.stakeout_math import Alignment, AlignmentError, ArcElement, LineElement, stake_delta


def test_domain_example_2_fails_at_15_mm_against_10() -> None:
    # design (100.000, 200.000), staked (100.012, 199.991): d = sqrt(12^2 + 9^2) = 15 mm.
    delta = stake_delta((100.0, 200.0, None), (100.012, 199.991, None), 10.0)
    assert (delta.de_mm, delta.dn_mm, delta.d_mm) == (12.0, -9.0, 15.0)
    assert delta.dz_mm is None
    assert delta.verdict == "fail"


def test_riverside_c04_passes_at_5_mm() -> None:
    # +0.004 / -0.003 is a 3-4-5 triangle: 5 mm.
    delta = stake_delta((389080.0, 5819030.0, 34.3), (389080.004, 5819029.997, 34.298), 10.0, 10.0)
    assert delta.d_mm == 5.0
    assert delta.dz_mm == -2.0
    assert delta.verdict == "pass"


def test_exactly_at_tolerance_passes() -> None:
    assert stake_delta((0.0, 0.0, None), (0.006, 0.008, None), 10.0).verdict == "pass"
    assert stake_delta((0.0, 0.0, None), (0.006, 0.0082, None), 10.0).verdict == "fail"


def test_height_outside_vertical_tolerance_fails_even_when_plan_passes() -> None:
    delta = stake_delta((0.0, 0.0, 10.0), (0.001, 0.0, 10.012), 10.0, 10.0)
    assert delta.d_mm == 1.0
    assert delta.dz_mm == 12.0
    assert delta.verdict == "fail"


def test_no_vertical_tolerance_skips_the_height_check() -> None:
    assert stake_delta((0.0, 0.0, 10.0), (0.0, 0.0, 10.5), 10.0, None).verdict == "pass"


def test_no_profile_gives_no_verdict() -> None:
    assert stake_delta((0.0, 0.0, None), (0.1, 0.0, None), None).verdict == "no_tolerance"


EAST = Alignment((LineElement((0.0, 0.0), (100.0, 0.0)),))
NORTH = Alignment((LineElement((0.0, 0.0), (0.0, 100.0)),), start_chainage=1000.0)


def test_line_heading_east_right_is_south() -> None:
    assert EAST.point_at(30.0, 5.0) == pytest.approx((30.0, -5.0))
    assert EAST.point_at(30.0, -5.0) == pytest.approx((30.0, 5.0))
    assert EAST.station_offset(60.0, -2.0) == pytest.approx((60.0, 2.0))


def test_line_heading_north_right_is_east_with_start_chainage() -> None:
    assert NORTH.point_at(1010.0, 3.0) == pytest.approx((3.0, 10.0))
    assert NORTH.station_offset(3.0, 10.0) == pytest.approx((1010.0, 3.0))


def test_riverside_axis_c_chainages() -> None:
    axis_c = Alignment((LineElement((389000.0, 5819030.0), (389100.0, 5819030.0)),), name="Axis C")
    assert axis_c.station_offset(389060.0, 5819030.0) == pytest.approx((60.0, 0.0))
    assert axis_c.station_offset(389080.0, 5819030.0) == pytest.approx((80.0, 0.0))


def test_quarter_arc_ccw() -> None:
    # Centre (0,0), R 100, from (100,0) to (0,100) turning left: length = pi/2 * 100 = 157.0796 m.
    arc = Alignment((ArcElement((100.0, 0.0), (0.0, 0.0), (0.0, 100.0), ccw=True),))
    assert arc.length == pytest.approx(157.0796, abs=1e-4)
    half = arc.length / 2
    assert arc.point_at(half) == pytest.approx((70.7107, 70.7107), abs=1e-4)
    # Turning left, the right side is outside the curve: offset +5 means radius 105.
    assert arc.point_at(half, 5.0) == pytest.approx((74.2462, 74.2462), abs=1e-4)
    assert arc.station_offset(74.2462, 74.2462) == pytest.approx((half, 5.0), abs=1e-3)


def test_quarter_arc_cw_right_is_inside() -> None:
    arc = Alignment((ArcElement((0.0, 100.0), (0.0, 0.0), (100.0, 0.0), ccw=False),))
    pt = arc.point_at(arc.length / 2, 5.0)
    assert math.hypot(*pt) == pytest.approx(95.0, abs=1e-6)


def test_line_then_arc_chainage_runs_on() -> None:
    al = Alignment(
        (
            LineElement((0.0, -50.0), (100.0, -50.0)),
            ArcElement((100.0, -50.0), (100.0, 0.0), (150.0, 0.0), ccw=True),
        )
    )
    # Quarter arc R 50 after 100 m of straight.
    assert al.length == pytest.approx(100.0 + math.pi * 25.0)
    assert al.point_at(100.0 + math.pi * 25.0) == pytest.approx((150.0, 0.0), abs=1e-6)
    ch, off = al.station_offset(150.0, 0.0)
    assert ch == pytest.approx(100.0 + math.pi * 25.0, abs=1e-6)
    assert off == pytest.approx(0.0, abs=1e-6)


def test_off_the_ends_raises() -> None:
    with pytest.raises(AlignmentError):
        EAST.point_at(100.5)
    with pytest.raises(AlignmentError):
        EAST.station_offset(-5.0, 0.0)
