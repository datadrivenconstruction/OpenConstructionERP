# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""COGO, field traverse and level book on the worked examples of the survey v2 domain spec."""

from __future__ import annotations

import math

import pytest

from app.modules.survey_core import cogo
from app.modules.survey_core.field_traverse import Station, adjust, angular_verdict
from app.modules.survey_core.level_book import HEIGHT_OF_INSTRUMENT, BookRow, reduce

# ── P0-5 COGO ──────────────────────────────────────────────────────────────


def test_inverse_worked_example() -> None:
    inv = cogo.inverse((1000.000, 1000.000), (1100.000, 1086.603))
    assert round(inv.distance, 3) == 132.288
    assert inv.bearing_deg == pytest.approx(49.1065, abs=1e-4)
    assert cogo.to_unit(inv.bearing_deg, "gon") == pytest.approx(54.5627, abs=1e-4)


@pytest.mark.parametrize(
    ("value", "unit", "deg"),
    [
        ("49 06 23.4", "dms", 49.10650),
        ("49°06'23.4\"", "dms", 49.10650),
        (49.06234, "dms", 49.10650),
        ("-12-30-00", "dms", -12.5),
        ("100", "gon", 90.0),
        (400, "gon", 360.0),
        ("12,5", "deg", 12.5),
    ],
)
def test_parse_angle_units(value, unit: str, deg: float) -> None:
    assert cogo.parse_angle(value, unit) == pytest.approx(deg, abs=1e-6)


def test_parse_angle_refuses_bad_minutes() -> None:
    with pytest.raises(ValueError, match="below 60"):
        cogo.parse_angle("10 75 00", "dms")


def test_format_angle_round_trip() -> None:
    assert cogo.format_angle(49.1065, "dms", 4) == "49°06'23.4\""
    assert cogo.format_angle(90.0, "gon") == "100.0000"


def test_polar_is_the_inverse_of_inverse() -> None:
    inv = cogo.inverse((1000.0, 1000.0), (1100.0, 1086.603))
    e, n = cogo.polar((1000.0, 1000.0), inv.bearing_deg, inv.distance)
    assert (round(e, 3), round(n, 3)) == (1100.0, 1086.603)


def test_bearing_bearing_intersection() -> None:
    e, n = cogo.bearing_bearing((0.0, 0.0), 45.0, (100.0, 0.0), 315.0)
    assert (round(e, 6), round(n, 6)) == (50.0, 50.0)


def test_parallel_lines_raise_srv040_code() -> None:
    with pytest.raises(cogo.CogoError) as err:
        cogo.bearing_bearing((0.0, 0.0), 30.0, (10.0, 0.0), 210.0)
    assert err.value.code == "parallel"


def test_distance_distance_gives_two_solutions_right_first() -> None:
    sols = cogo.distance_distance((0.0, 0.0), 50.0, (60.0, 0.0), 50.0)
    assert len(sols) == 2
    assert sols[0] == pytest.approx((30.0, -40.0))
    assert sols[1] == pytest.approx((30.0, 40.0))


def test_distance_distance_without_solution() -> None:
    with pytest.raises(cogo.CogoError):
        cogo.distance_distance((0.0, 0.0), 10.0, (100.0, 0.0), 10.0)


def test_offset_right_positive() -> None:
    off = cogo.offset_to_line((0.0, 0.0), (0.0, 100.0), (5.0, 40.0))
    assert (off.chainage, off.offset, off.foot) == (40.0, 5.0, (0.0, 40.0))


def test_area_and_perimeter() -> None:
    a, p = cogo.area([(0, 0), (50, 0), (50, 32), (0, 28)])
    assert a == pytest.approx(1500.0)
    assert p == pytest.approx(50 + 32 + math.hypot(50, 4) + 28)


# ── P0-6 Traverse from field observations ─────────────────────────────────


def _pentagon(total_error_sec: float) -> list[Station]:
    angles = [108.0 + total_error_sec / 5 / 3600.0] * 5
    return [Station(f"S{i + 1}", a, 100.0) for i, a in enumerate(angles)]


def test_angular_misclosure_25_seconds_against_fgcc_classes() -> None:
    result = adjust("loop", (1000.0, 1000.0), 90.0, _pentagon(25.0))
    assert result.expected_sum_deg == 540.0
    assert result.angular_misclosure_sec == pytest.approx(25.0, abs=1e-6)
    allowed_i, verdict_i = angular_verdict(result.angular_misclosure_sec, 5, 10.0)
    allowed_ii, verdict_ii = angular_verdict(result.angular_misclosure_sec, 5, 12.0)
    assert round(allowed_i, 1) == 22.4
    assert verdict_i == "fail"
    assert round(allowed_ii, 1) == 26.8
    assert verdict_ii == "pass"


def test_even_correction_then_bowditch_closes_the_loop() -> None:
    result = adjust("loop", (1000.0, 1000.0), 90.0, _pentagon(25.0))
    assert result.angular_correction_sec == pytest.approx(-5.0)
    assert [s.station_id for s in result.stations] == ["S1", "S2", "S3", "S4", "S5"]
    # With the angles corrected the pentagon is regular, so the leg closure is ~0.
    assert result.misclosure_m < 1e-6
    s2 = result.stations[1]
    assert (round(s2.e, 3), round(s2.n, 3)) == (1100.0, 1000.0)


def test_link_traverse_closes_on_the_known_end() -> None:
    stations = [Station("A", 90.0, 100.0), Station("B", 180.0, 100.0), Station("C", 270.0 + 10 / 3600)]
    result = adjust("link", (0.0, 0.0), 270.0, stations, end=(0.0, 200.05), closing_azimuth_deg=90.0)
    assert result.angular_misclosure_sec == pytest.approx(10.0, abs=1e-6)
    end = result.stations[-1]
    assert (round(end.e, 6), round(end.n, 6)) == (0.0, 200.05)
    assert result.misclosure_m == pytest.approx(0.05, abs=1e-3)


def test_angle_left_is_turned_into_angle_right() -> None:
    right = adjust("loop", (0.0, 0.0), 90.0, _pentagon(0.0))
    left = adjust(
        "loop", (0.0, 0.0), 90.0, [Station(s.station_id, 360.0 - s.angle_deg, 100.0) for s in _pentagon(0)], "left"
    )
    assert left.stations[2].e == pytest.approx(right.stations[2].e)


# ── P0-7 Level book ───────────────────────────────────────────────────────

BOOK = [
    BookRow("BM1", bs=1.523),
    BookRow("TP1", fs=0.874, bs=2.011, distance_m=300),
    BookRow("TP2", fs=1.208, bs=0.987, distance_m=250),
    BookRow("BM2", fs=1.644, distance_m=250),
]


@pytest.mark.parametrize("method", ["rise_fall", HEIGHT_OF_INSTRUMENT])
def test_level_book_worked_example(method: str) -> None:
    out = reduce(BOOK, 45.200, 45.990, method)
    rises = [r.rise if r.rise is not None else -(r.fall or 0) for r in out.rows[1:]]
    assert [round(x, 3) for x in rises] == [0.649, 0.803, -0.657]
    assert round(out.last_rl, 3) == 45.995
    assert round(out.misclosure_mm, 1) == 5.0
    assert out.distance_km == pytest.approx(0.8)
    assert out.arithmetic_ok
    assert [r.step_mm for r in out.rows[1:]] == [-1.9, -1.6, -1.5]
    assert [round(r.rl_adjusted, 3) for r in out.rows] == [45.200, 45.847, 46.649, 45.990]


def test_level_book_limits_fgcc() -> None:
    from app.modules.survey_core.traverse import level_verdict

    assert level_verdict(5.0, 0.8, 12.0) == (pytest.approx(10.73, abs=0.01), "pass")
    allowed, verdict = level_verdict(5.0, 0.8, 6.0)
    assert round(allowed, 1) == 5.4
    assert verdict == "pass"


def test_intermediate_sight_does_not_advance_the_run() -> None:
    rows = [BookRow("BM1", bs=1.5), BookRow("P1", is_=1.0, distance_m=20), BookRow("BM2", fs=0.5, distance_m=40)]
    out = reduce(rows, 10.0, 11.0)
    assert out.rows[1].rl == pytest.approx(10.5)
    assert out.rows[1].run_m == 20
    assert out.rows[2].run_m == 40
    assert out.misclosure_mm == pytest.approx(0.0)


def test_hand_reduced_book_with_a_slip_fails_the_arithmetic_check() -> None:
    rows = [*BOOK[:-1], BookRow("BM2", fs=1.644, distance_m=250, rl_entered=45.985)]
    assert not reduce(rows, 45.200, 45.990).arithmetic_ok


def test_level_book_needs_an_opening_backsight() -> None:
    with pytest.raises(ValueError, match="backsight"):
        reduce([BookRow("BM1", fs=1.0), BookRow("BM2", fs=1.0)], 10.0)


async def _calc_failed(rule, data: dict) -> list:
    from app.core.validation.engine import ValidationContext

    return [r for r in await rule.validate(ValidationContext(data=data, metadata={"locale": "en"})) if not r.passed]


async def test_srv040_041_on_cogo_rows() -> None:
    from app.modules.survey_core.calc_validators import ParallelLinesRule, TwoSolutionsRule

    data = {"cogo": [{"ref": "x", "method": "line_line", "status": "parallel"},
                     {"ref": "y", "method": "distance_distance", "status": "two_solutions"}]}  # fmt: skip
    assert [r.rule_id for r in await _calc_failed(ParallelLinesRule(), data)] == ["SRV-040"]
    assert [r.rule_id for r in await _calc_failed(TwoSolutionsRule(), data)] == ["SRV-041"]


async def test_srv050_pentagon_25_seconds_against_k10_and_k12() -> None:
    from app.modules.survey_core.calc_validators import AngularMisclosureRule

    row = {"id": "t", "kind": "traverse", "ang_misclosure_sec": 25.0, "angle_count": 5}
    [hit] = await _calc_failed(AngularMisclosureRule(), {"traverses": [{**row, "ang_k_sec": 10}]})
    assert hit.rule_id == "SRV-050" and "25.0" in hit.message
    assert await _calc_failed(AngularMisclosureRule(), {"traverses": [{**row, "ang_k_sec": 12}]}) == []
    assert await _calc_failed(AngularMisclosureRule(), {"traverses": [row]}) == []


async def test_srv060_level_arithmetic() -> None:
    from app.modules.survey_core.calc_validators import LevelArithmeticRule

    row = {"id": "l", "kind": "level", "name": "Run 1", "arithmetic_ok": False,
           "sum_bs": 5.0, "sum_fs": 4.2, "first_rl": 45.2, "last_rl": 46.0}  # fmt: skip
    [hit] = await _calc_failed(LevelArithmeticRule(), {"traverses": [row]})
    assert hit.rule_id == "SRV-060" and "Run 1" in hit.message
    assert await _calc_failed(LevelArithmeticRule(), {"traverses": [{**row, "arithmetic_ok": True}]}) == []
