# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Least-squares traverse adjustment and the riverside course numbers.

Worked examples first:

* the plane-triangle angle condition (three angles must sum to 180 deg), the
  opening example of least squares by condition equations in Mikhail & Gracie,
  "Analysis and Adjustment of Survey Measurements" (1981) and Ghilani,
  "Adjustment Computations" (Wiley): with exact sides and equally weighted
  angles each angle takes -w/3;
* the same loop adjusted by the three closure conditions of a traverse
  (angle sum, sum dE, sum dN; Ghilani, traverse adjustment chapter), solved
  here independently, must give the parametric result;
* chi-square table values (any statistics table): chi2(3; 0.025) = 0.216,
  chi2(3; 0.975) = 9.348, chi2(2; 0.95) = 5.991.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from app.modules.survey_core.field_traverse import Station, adjust
from app.modules.survey_core.level_book import BookRow, reduce
from app.modules.survey_core.lsq_traverse import (
    CONFIDENCE_95,
    INSTRUMENT_CLASSES,
    Weights,
    adjust_lsq,
    chi2_quantile,
    ellipse,
)
from app.modules.survey_core.traverse import level_verdict

DEMO = Path(__file__).resolve().parents[3] / "app" / "modules" / "survey_core" / "demo" / "riverside"
EXPECTED = json.loads((DEMO / "expected.json").read_text(encoding="utf-8"))["survey_calc"]
CALC_DEMO = json.loads((DEMO / "calc_demo.json").read_text(encoding="utf-8"))


def _dms(text: str) -> float:
    d, m, s = (float(x) for x in text.split("-"))
    return d + m / 60 + s / 3600


def _demo_stations() -> list[Station]:
    return [Station(s["station_id"], _dms(s["angle"]), s["distance_m"]) for s in CALC_DEMO["traverse"]["stations"]]


def _demo_start() -> tuple[float, float]:
    s = CALC_DEMO["traverse"]["start"]
    return s["e"], s["n"]


def _demo_weights() -> Weights:
    t = CALC_DEMO["traverse"]
    return Weights(t["angle_sd_sec"], t["dist_sd_mm"], t["dist_ppm"], t["centering_sd_mm"])


# ── Worked examples ────────────────────────────────────────────────────────


def test_chi_square_table_values() -> None:
    assert chi2_quantile(0.025, 3) == pytest.approx(0.2158, abs=1e-4)
    assert chi2_quantile(0.975, 3) == pytest.approx(9.3484, abs=1e-4)
    assert chi2_quantile(0.95, 2) == pytest.approx(5.9915, abs=1e-4)
    assert math.sqrt(5.9915) == pytest.approx(CONFIDENCE_95, abs=1e-4)


def test_triangle_angle_condition_spreads_the_misclosure_evenly() -> None:
    w = 30.0  # arc seconds over three angles
    tri = [Station(f"S{i}", 60.0 + w / 3 / 3600, 100.0) for i in range(3)]
    r = adjust_lsq("loop", (0.0, 0.0), 90.0, tri, Weights(5.0, 2.0))
    angles = [x for x in r.residuals if x.kind == "angle"]
    sides = [x for x in r.residuals if x.kind == "distance"]
    assert [round(x.residual, 6) for x in angles] == [-10.0, -10.0, -10.0]
    assert all(abs(x.residual) < 1e-6 for x in sides)
    assert r.redundancy == 3
    # vTPv = 3 * (10 / 5)^2 = 12 over r = 3, so sigma0 = 2.
    assert r.vtpv == pytest.approx(12.0, abs=1e-6)
    assert r.sigma0 == pytest.approx(2.0, abs=1e-6)
    s2 = r.stations[2]
    assert (round(s2.e, 6), round(s2.n, 6)) == (50.0, round(100 * math.sqrt(3) / 2, 6))


def _condition_adjustment(start, az_deg, stations, weights):
    """Independent solution by the three closure conditions of a loop (Gauss-Helmert, iterated)."""
    rho = 180 / math.pi * 3600
    n = len(stations)
    obs = np.array([math.radians(s.angle_deg) for s in stations] + [s.distance_m for s in stations])
    sd = np.array([weights.angle_sd_sec / rho] * n + [weights.dist_sd_mm / 1000] * n)
    q = np.diag(sd**2)
    az0 = math.radians(az_deg)

    def conditions(x):
        beta, dist = x[:n], x[n:]
        az = [az0]
        for i in range(1, n):
            az.append(az[-1] + math.pi + beta[i])
        return np.array(
            [
                beta.sum() - (n - 2) * math.pi,
                sum(d * math.sin(a) for d, a in zip(dist, az, strict=True)),
                sum(d * math.cos(a) for d, a in zip(dist, az, strict=True)),
            ]
        )

    x = obs.copy()
    for _ in range(20):
        jac = np.zeros((3, 2 * n))
        for j in range(2 * n):
            h = 1e-9 if j < n else 1e-6
            dx = np.zeros(2 * n)
            dx[j] = h
            jac[:, j] = (conditions(x + dx) - conditions(x - dx)) / (2 * h)
        v = x - obs
        w = conditions(x) - jac @ v
        v_new = -q @ jac.T @ np.linalg.solve(jac @ q @ jac.T, w)
        step = np.max(np.abs(v_new - v))
        x = obs + v_new
        if step < 1e-12:
            break
    v = x - obs
    vtpv = float(v @ np.linalg.solve(q, v))
    az = [az0]
    for i in range(1, n):
        az.append(az[-1] + math.pi + x[i])
    e, nn = [start[0]], [start[1]]
    for i in range(n - 1):
        e.append(e[-1] + x[n + i] * math.sin(az[i]))
        nn.append(nn[-1] + x[n + i] * math.cos(az[i]))
    return vtpv, list(zip(e, nn, strict=True))


def test_parametric_matches_the_condition_method_on_the_demo_loop() -> None:
    weights = Weights(10.0, 15.0)  # no ppm, no centering: weights fixed, as the condition method assumes
    r = adjust_lsq("loop", _demo_start(), 90.0, _demo_stations(), weights)
    vtpv, coords = _condition_adjustment(_demo_start(), 90.0, _demo_stations(), weights)
    assert r.vtpv == pytest.approx(vtpv, rel=1e-6)
    for s, (e, n) in zip(r.stations, coords, strict=True):
        assert s.e == pytest.approx(e, abs=1e-5)
        assert s.n == pytest.approx(n, abs=1e-5)


# ── Riverside course numbers ───────────────────────────────────────────────


def test_demo_bowditch_matches_the_register() -> None:
    exp = EXPECTED["traverse"]
    b = adjust("loop", _demo_start(), 90.0, _demo_stations())
    assert b.angular_misclosure_sec == pytest.approx(exp["angular_misclosure_sec"], abs=1e-6)
    assert b.angular_correction_sec == pytest.approx(exp["angular_correction_sec"], abs=1e-6)
    assert round(b.length_m, 1) == exp["length_m"]
    assert (round(b.f_e, 3), round(b.f_n, 3)) == (exp["f_e_m"], exp["f_n_m"])
    assert round(b.misclosure_m, 3) == exp["misclosure_m"]
    assert b.ratio == exp["ratio"] == 11731
    first = b.stations[1]
    assert (round(first.c_e, 3), round(first.c_n, 3)) == (exp["c_e_m"], exp["c_n_m"])


def test_demo_register_and_calc_agree() -> None:
    register = json.loads((DEMO / "expected.json").read_text(encoding="utf-8"))["survey_register"]["lesson_4"]
    exp = EXPECTED["traverse"]
    for key in ("length_m", "f_e_m", "f_n_m", "misclosure_m", "ratio", "c_e_m", "c_n_m", "bowditch_leg_m"):
        assert register[key] == exp[key], key


def test_demo_least_squares() -> None:
    exp = EXPECTED["traverse"]["lsq"]
    r = adjust_lsq("loop", _demo_start(), 90.0, _demo_stations(), _demo_weights())
    assert r.redundancy == exp["redundancy"]
    assert round(r.sigma0, 3) == exp["sigma0"]
    assert round(r.vtpv, 3) == exp["vtpv"]
    assert (round(r.chi2_lower, 3), round(r.chi2_upper, 3)) == (exp["chi2_lower"], exp["chi2_upper"])
    assert r.chi2_pass is exp["chi2_pass"]
    worst = next(x for x in r.residuals if x.flagged)
    assert worst.ref == exp["largest_residual"]
    assert round(worst.standardized or 0.0, 2) == exp["largest_standardized"]
    assert not any(x.suspect for x in r.residuals)
    assert {e.ref: round(e.a_m * 1000, 1) for e in r.ellipses} == exp["ellipse_a_mm"]
    # The loop closes on itself: start fixed, every station adjusted.
    assert [s.fixed for s in r.stations] == [True, False, False, False]
    assert len(r.relative_ellipses) == 4


def test_instrument_class_weights_reject_the_demo_closure() -> None:
    # A 52 mm misclosure is far beyond a 1" instrument: the global test must say so.
    one = INSTRUMENT_CLASSES[0]
    w = Weights(one.angle_sd_sec, one.dist_sd_mm, one.dist_ppm, one.centering_sd_mm)
    r = adjust_lsq("loop", _demo_start(), 90.0, _demo_stations(), w)
    assert not r.chi2_pass
    assert any(x.suspect for x in r.residuals)


def test_demo_level_run() -> None:
    exp = EXPECTED["level_book"]
    book = CALC_DEMO["level_book"]
    rows = [BookRow(r["station"], r.get("bs"), r.get("is"), r.get("fs"), r.get("distance_m")) for r in book["rows"]]
    for method in ("rise_fall", "hi"):
        out = reduce(rows, book["start_rl"], book["close_rl"], method)
        assert round(out.misclosure_mm, 1) == exp["misclosure_mm"]
        assert out.distance_km == pytest.approx(exp["distance_km"])
        assert out.arithmetic_ok is exp["arithmetic_ok"]
        allowed, verdict = level_verdict(out.misclosure_mm, out.distance_km, book["k_mm"])
        assert (round(allowed, 2), verdict) == (exp["allowed_mm"], exp["verdict"])
        assert [r.step_mm for r in out.rows if r.fs is not None] == exp["steps_mm"]
        peg = next(r for r in out.rows if r.station == exp["intermediate"])
        assert round(peg.rl_adjusted, 4) == exp["intermediate_rl_adjusted"]
        assert round(out.rows[-1].rl_adjusted, 3) == exp["close_rl_adjusted"]


# ── Degenerate geometry ────────────────────────────────────────────────────


def test_coincident_stations_are_refused() -> None:
    # Out 100 m east and straight back: the third station sits on the first.
    stations = [Station("A", 0.0, 100.0), Station("B", 0.0, 100.0), Station("C", 180.0, 0.001)]
    with pytest.raises(ValueError, match="coincide|singular"):
        adjust_lsq("loop", (0.0, 0.0), 90.0, stations, Weights(5.0, 3.0))


def test_straight_link_has_ellipses_along_and_across_the_line() -> None:
    # A straight link north: the along-line and across-line errors separate, the axes lie on 0 / 90 deg.
    stations = [Station("A", 90.0, 100.0), Station("B", 180.0, 100.0), Station("C", 180.0, 100.0), Station("D", 270.0)]
    r = adjust_lsq(
        "link", (0.0, 0.0), 270.0, stations, Weights(2.0, 2.0, 2.0, 1.0), end=(0.0, 300.0), closing_azimuth_deg=90.0
    )
    assert r.redundancy == 3
    for e in r.ellipses:
        assert math.isfinite(e.a_m) and e.a_m > 0
        assert min(e.azimuth_deg % 90, 90 - e.azimuth_deg % 90) < 1e-3
    # Weaker angles widen the across-line axis only.
    loose = adjust_lsq(
        "link", (0.0, 0.0), 270.0, stations, Weights(20.0, 2.0, 2.0, 1.0), end=(0.0, 300.0), closing_azimuth_deg=90.0
    )
    assert loose.ellipses[0].sd_e_m > r.ellipses[0].sd_e_m * 5
    assert loose.ellipses[0].sd_n_m == pytest.approx(r.ellipses[0].sd_n_m, rel=0.05)


def test_zero_weight_is_refused() -> None:
    with pytest.raises(ValueError, match="standard deviation"):
        adjust_lsq("loop", (0.0, 0.0), 90.0, _demo_stations(), Weights(0.0, 3.0))


def test_ellipse_orientation() -> None:
    e = ellipse(1e-6, 4e-6, 0.0)
    assert (round(e.a_m * 1000, 6), round(e.b_m * 1000, 6), e.azimuth_deg) == (2.0, 1.0, 0.0)
    assert ellipse(4e-6, 1e-6, 0.0).azimuth_deg == pytest.approx(90.0)
