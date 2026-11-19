"""Local grid Helmert (P0-2) and combined scale factor (P0-3), from the worked examples."""

from __future__ import annotations

import math

import pytest

from app.modules.survey_core.geodesy import (
    CommonPoint,
    Helmert2D,
    combined_scale_factor,
    elevation_factor,
    ground_grid_difference_mm,
    point_scale,
    solve_helmert,
    tm_scale_approx,
    unit_mixup,
)

A = CommonPoint("A", 1000.0, 1000.0, 389012.345, 5819020.111)
B = CommonPoint("B", 1100.0, 1000.0, 389111.966, 5819028.827)


def test_two_points_fix_the_transform_exactly() -> None:
    fit = solve_helmert([A, B])
    t = fit.transform
    assert t.rotation_deg == pytest.approx(5.0, abs=0.001)
    # The example rounds to 20 ppm; the exact solution of its coordinates is 15.6 ppm.
    assert t.scale_ppm == pytest.approx(15.6, abs=0.2)
    assert fit.rms_mm == 0.0
    for p in (A, B):
        e, n = t.forward(p.x, p.y)
        assert (e, n) == pytest.approx((p.e, p.n), abs=1e-6)


def test_the_worked_example_maps_c_and_gives_its_residual() -> None:
    t = solve_helmert([A, B]).transform
    e, n = t.forward(1050.0, 1080.0)
    assert e == pytest.approx(389055.183, abs=0.001)
    assert n == pytest.approx(5819104.166, abs=0.001)
    # Measured C (389055.187, 5819104.163); the example quotes 4.9 mm from its rounded C.
    r = math.hypot(389055.187 - e, 5819104.163 - n) * 1000
    assert r == pytest.approx(5.1, abs=0.2)


def test_three_points_by_least_squares_spread_the_residuals() -> None:
    c = CommonPoint("C", 1050.0, 1080.0, 389055.187, 5819104.163)
    fit = solve_helmert([A, B, c])
    assert fit.used == 3
    assert fit.rms_mm > 0
    assert {r.point_id for r in fit.residuals} == {"A", "B", "C"}
    assert max(r.r_mm for r in fit.residuals) < 5.0
    # Residuals of a similarity fit sum to zero per axis.
    assert sum(r.de_mm for r in fit.residuals) == pytest.approx(0, abs=1e-3)


def test_a_check_point_is_reported_but_not_fitted() -> None:
    c = CommonPoint("C", 1050.0, 1080.0, 389055.187, 5819104.163, use=False)
    fit = solve_helmert([A, B, c])
    assert fit.used == 2
    [rc] = [r for r in fit.residuals if r.point_id == "C"]
    assert not rc.used
    assert rc.r_mm == pytest.approx(5.1, abs=0.2)


@pytest.mark.parametrize("points", [[], [A], [A, CommonPoint("A2", 1000.0, 1000.0, 389012.345, 5819020.111)]])
def test_fewer_than_two_distinct_points_is_refused(points: list[CommonPoint]) -> None:
    with pytest.raises(ValueError):
        solve_helmert(points)


def test_inverse_round_trips() -> None:
    t = Helmert2D.from_params(1.00002, 5.0, 388000.0, 5818000.0)
    x, y = t.inverse(*t.forward(1234.5, 678.9))
    assert (x, y) == pytest.approx((1234.5, 678.9), abs=1e-7)


@pytest.mark.parametrize(
    ("scale", "mixed"),
    [(1.00002, False), (0.3048, True), (1 / 0.3048, True), (1200 / 3937, True), (0.31, False), (1.01, False)],
)
def test_a_metre_foot_ratio_is_a_unit_mixup(scale: float, mixed: bool) -> None:
    assert unit_mixup(scale) is mixed


# -- combined scale factor ---------------------------------------------------------------------------------------


def test_the_csf_worked_example_by_the_formula() -> None:
    k = tm_scale_approx(389000 - 500000)
    ef = elevation_factor(120.0)
    assert k == pytest.approx(0.99975171, abs=5e-9)
    assert ef == pytest.approx(0.99998117, abs=5e-9)
    assert k * ef == pytest.approx(0.99973288, abs=5e-9)


def test_pyproj_point_scale_agrees_with_the_formula() -> None:
    assert point_scale(32633, 389000.0, 5819000.0) == pytest.approx(tm_scale_approx(-111000), abs=2e-6)


def test_250_m_on_the_ground_is_249_933_m_on_the_grid() -> None:
    sf = combined_scale_factor(32633, 389000.0, 5819000.0, 120.0)
    assert sf.grid_from_ground(250.0) == pytest.approx(249.933, abs=0.001)
    assert sf.ground_from_grid(sf.grid_from_ground(250.0)) == pytest.approx(250.0, abs=1e-9)
    assert ground_grid_difference_mm(sf.csf, 250.0) == pytest.approx(67, abs=1)


def test_on_the_central_meridian_at_sea_level_the_csf_is_k0() -> None:
    sf = combined_scale_factor(32633, 500000.0, 5819000.0, 0.0)
    assert sf.csf == pytest.approx(0.9996, abs=1e-6)
    assert sf.elevation_factor == 1.0
