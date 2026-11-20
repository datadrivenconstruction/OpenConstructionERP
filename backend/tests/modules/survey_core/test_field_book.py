# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Field book reduction: two faces, slope distances, angle conventions and the Riverside loop."""

from __future__ import annotations

import math

import pytest

from app.modules.survey_core import field_book as fb
from app.modules.survey_core.cogo import parse_angle
from app.modules.survey_core.field_traverse import adjust


def _dms(text: str | None) -> float | None:
    return parse_angle(text, "dms") if text else None


def test_two_faces_are_meaned_and_their_difference_kept() -> None:
    mean, diff = fb.mean_faces(_dms("148 42 46"), _dms("148 42 42"))
    assert mean == pytest.approx(_dms("148 42 44"))
    assert diff == pytest.approx(4.0)
    # Across zero the circle mean is still right: 359 59 58 and 0 00 04 give 0 00 01.
    mean, diff = fb.mean_faces(_dms("359 59 58"), _dms("0 00 04"))
    assert mean * 3600 == pytest.approx(1.0)
    assert diff == pytest.approx(-6.0)
    assert fb.mean_faces(None, 10.0) == (10.0, None)


def test_slope_distance_with_zenith_and_heights() -> None:
    # SD 100 at Z 80 deg: HD = 100 sin 80 = 98.481, dH = 100 cos 80 + 1.5 - 1.6 = 17.265.
    row = fb.BookRow("A", 0.0, None, 100.0, "slope", 80.0, 1.5, 1.6)
    hd, dh = fb.horizontal(row)
    assert hd == pytest.approx(98.4808, abs=1e-4)
    assert dh == pytest.approx(100 * math.cos(math.radians(80)) - 0.1, abs=1e-6)
    with pytest.raises(ValueError, match="zenith"):
        fb.horizontal(fb.BookRow("A", 0.0, None, 100.0, "slope"))


def _square(values: list[float]) -> list[fb.BookRow]:
    return [fb.BookRow(f"S{i + 1}", v, None, 100.0) for i, v in enumerate(values)]


def test_left_deflection_and_azimuth_give_the_same_angles_right() -> None:
    # A 100 m square run anticlockwise: interior angles right 90, first leg east.
    right = fb.reduce_book("loop", "right", _square([90.0] * 4), backsight_azimuth_deg=0.0)
    left = fb.reduce_book("loop", "left", _square([270.0] * 4), backsight_azimuth_deg=0.0)
    defl = fb.reduce_book("loop", "deflection", _square([-90.0] * 4), backsight_azimuth_deg=0.0)
    azim = fb.reduce_book("loop", "azimuth", _square([90.0, 0.0, 270.0, 180.0]), backsight_azimuth_deg=None)
    for book in (right, left, defl, azim):
        assert [round(s.angle_deg, 9) for s in book.stations] == [90.0] * 4
        assert book.azimuth_deg == pytest.approx(90.0)
        result = adjust("loop", (0.0, 0.0), book.azimuth_deg, book.stations)
        assert result.misclosure_m == pytest.approx(0.0, abs=1e-9)
        assert result.stations[2].e == pytest.approx(100.0)
        assert result.stations[2].n == pytest.approx(100.0)


def test_closing_angle_on_a_control_backsight() -> None:
    # Backsight to a mark due north (0 deg); angle to the first foresight 90 (east);
    # closing angle from the last station (south, 180) to the mark is 180, interior = 270.
    rows = [fb.BookRow("A", 90.0, None, 10.0), fb.BookRow("B", 90.0, None, 10.0)]
    book = fb.reduce_book("loop", "right", rows, backsight_azimuth_deg=0.0, closing_angle_deg=180.0)
    assert book.azimuth_deg == pytest.approx(90.0)
    assert book.stations[0].angle_deg == pytest.approx(270.0)


def test_unknown_mode_and_missing_orientation() -> None:
    with pytest.raises(ValueError, match="mode"):
        fb.reduce_book("loop", "bearing", _square([90.0] * 4), 0.0)
    with pytest.raises(ValueError, match="backsight"):
        fb.reduce_book("loop", "right", _square([90.0] * 4), None)


def test_riverside_field_book_closes_within_class() -> None:
    book = fb.parse_book_csv(fb.DEMO_BOOK.read_text(encoding="utf-8"))
    assert book["start"]["station_id"] == "T1"
    assert [r["station"] for r in book["rows"]] == ["T1", "T2", "T3", "T4", "T5", "T6"]
    rows = [
        fb.BookRow(
            r["station"],
            _dms(r["face_l"]),
            _dms(r["face_r"]),
            float(r["distance"]),
            r["dist_mode"],
            _dms(r["zenith"]),
            float(r["hi"]),
            float(r["ht"]),
        )
        for r in book["rows"]
    ]
    reduced = fb.reduce_book("loop", "right", rows, _dms(book["backsight_azimuth"]), _dms(book["closing_angle"]))
    assert reduced.rows[1].hd == pytest.approx(103.410, abs=5e-4)
    assert reduced.rows[1].face_diff_sec == pytest.approx(-6.0)
    result = adjust("loop", (book["start"]["e"], book["start"]["n"]), reduced.azimuth_deg, reduced.stations)
    # 6 angles, 13" misclosure: inside 10" * sqrt(6) = 24.5"; linear 1:109 000 beats 1:10 000.
    assert round(result.angular_misclosure_sec) == 13
    assert round(result.misclosure_m, 4) == 0.0058
    assert result.ratio is not None
    assert result.ratio > 100_000
    t4 = next(s for s in result.stations if s.station_id == "T4")
    assert (round(t4.e, 3), round(t4.n, 3)) == (389098.771, 5819151.881)


async def test_book_to_traverse_closes_through_the_calc_service() -> None:
    from app.modules.survey_core.calc_service import CalcService
    from app.modules.survey_core.field_book_router import FieldBookIn, _out, to_traverse

    raw = fb.parse_book_csv(fb.DEMO_BOOK.read_text(encoding="utf-8"))
    body = FieldBookIn(
        name=raw["name"],
        start=raw["start"],
        backsight_azimuth=raw["backsight_azimuth"],
        closing_angle=raw["closing_angle"],
        rows=[{k: v for k, v in r.items() if v != ""} for r in raw["rows"]],
        angular_k_sec=10,
        min_ratio=10_000,
    )
    reduced, traverse = to_traverse(body)
    result = await CalcService.compute_traverse(traverse, [], None, None, "en")
    out = _out(reduced, body, result)
    assert result.angular_verdict == "pass"
    assert result.linear_verdict == "pass"
    assert result.angular_allowed_sec == pytest.approx(24.49, abs=0.01)
    assert out.fixed_end.station_id == "T1"
    assert out.computed_end.e - out.fixed_end.e == pytest.approx(result.f_e)
    assert out.unadjusted[0].e == pytest.approx(389004.12)
