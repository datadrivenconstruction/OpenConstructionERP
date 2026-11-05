"""Plan-read belt on shipped sample sheets the benchmark generator did not draw.

Fixed hand-traced model answers (``tests/bench/takeoff_vision/real_cases.py``);
ground truth is the sheet's own area labels. No constant is tuned on these.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://bench:bench@127.0.0.1:1/bench")

pytest.importorskip("fitz")
pytest.importorskip("cv2")

from app.modules.takeoff import plan_read as pr  # noqa: E402
from tests.bench.takeoff_vision import real_cases as rc  # noqa: E402

LABELS = {
    "Buero 1.01 (inner, jitter)": 29.73,
    "Buero 1.02 (centreline)": 29.67,
    "Besprechung (outer face)": 36.34,
    "Grossraumbuero (inner)": 64.09,
    "Lager 1.10": 33.60,
    "Flur 1.11 (inner)": 55.02,
}


@pytest.fixture(scope="module")
def grundriss():
    _res, ref, _lines = rc.read_case(rc.GRUNDRISS)
    return ref, {r.name: r for r in ref.rooms}


@pytest.fixture(scope="module")
def house():
    _res, ref, _lines = rc.read_case(rc.HOUSE)
    return {r.name: r for r in ref.rooms}


def _m2(ref, room) -> float:
    return pr.shoelace_area(room.points) / ref.scale.ratio**2


def test_white_mask_over_dark_wall_fill_is_the_inner_face(grundriss) -> None:
    ref, rooms = grundriss
    for name, label in LABELS.items():
        assert abs(_m2(ref, rooms[name]) - label) / label < 0.01, name


def test_mask_edges_enter_the_wall_index() -> None:
    data, *_ = rc._sheet(rc.GRUNDRISS["file"])
    vec = pr.extract_vector_layer(data, 1)
    assert any(seg[4] >= 2.0 for seg in vec.segments)
    assert any(dark is False for dark, _ring in vec.fill_ops)


def test_invented_rooms_never_reach_the_medium_band(grundriss) -> None:
    _ref, rooms = grundriss
    for name in ("corridor slice", "outside building", "WC H+D merged", "Teekueche+Technik merged"):
        assert rooms[name].confidence < 0.62, name


def test_corridor_slice_takes_the_overlap_not_the_corridor(grundriss) -> None:
    _ref, rooms = grundriss
    assert "room:overlaps" in rooms["corridor slice"].flags
    assert "room:overlaps" not in rooms["Flur 1.11 (inner)"].flags


def test_confidence_never_exceeds_the_model_without_a_label(grundriss, house) -> None:
    _ref, rooms = grundriss
    for r in [*rooms.values(), *house.values()]:
        if not r.corroborated:
            assert r.confidence <= r.model_confidence + 1e-9, r.name


def test_label_mismatch_lowers_confidence_continuously() -> None:
    def conf(rel: float) -> float:
        r = pr.RefinedRoom("x", [(0, 0), (10, 0), (10, 10), (0, 10)], model_confidence=0.9, confidence=0, verdict="ok")
        r.snapped, r.wall_support, r.area_label_m2 = True, 1.0, 100.0 * (1 + rel)
        r.corroborated = pr._label_agrees(r.points, r.area_label_m2, 1.0)
        scale = pr.ScaleDecision(ratio=1.0, confidence=0.97, source="page_text", flags=[])
        return pr._room_confidence(r, scale, 1.0, scanned=False)

    values = [conf(rel) for rel in (0.0, 0.02, 0.04, 0.06, 0.08)]
    assert values[0] >= 0.9
    assert all(a > b for a, b in zip(values, values[1:], strict=False))
    assert values[1] < 0.62


def test_two_floors_on_one_sheet_are_not_isolated(house) -> None:
    for name in ("Living room", "Dining room", "Chamber mid", "Chamber left"):
        assert "room:isolated" not in house[name].flags, name


def test_real_split_metrics() -> None:
    m = rc.evaluate()
    assert m["vector_rooms_kept"] == m["vector_rooms_labelled"] == 6
    assert m["area_err_max_pct"] < 1.0
    assert m["invented_confident"] == 0
    assert m["real_rooms_flagged_isolated"] == 0
    assert m["conf_above_model_uncorroborated"] == 0
