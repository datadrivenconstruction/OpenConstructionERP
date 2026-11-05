"""What the drawing can say against a plan read: scale sources, ring evidence, sheet type."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://bench:bench@127.0.0.1:1/bench")

pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

from app.modules.takeoff import plan_read as pr  # noqa: E402

CONFIDENT = 0.62
PAGE = (1190.0, 842.0)
#: One metre in page points, and a 6 m by 4 m ring at (100, 100).
M = 20.0
RING = [(100.0, 100.0), (220.0, 100.0), (220.0, 180.0), (100.0, 180.0)]


def _decide(monkeypatch, *, dim=None, note=None, model=None) -> pr.ScaleDecision:
    vector = pr.VectorLayer(page_width_pt=PAGE[0], page_height_pt=PAGE[1])
    vector.cache["scale"] = ((dim, 8) if dim else None, note)
    monkeypatch.setattr(pr, "scale_ratio_from_plan_scale", lambda *_a: model)
    return pr.decide_scale(None, SimpleNamespace(confidence=0.8) if model else None, vector, *PAGE)


def test_note_and_model_agreeing_beat_a_dimension_reading(monkeypatch) -> None:
    d = _decide(monkeypatch, dim=5.67, note=56.69, model=56.0)
    assert d.ratio == 56.69
    assert d.confidence >= CONFIDENT
    assert "scale:dimension_reading_disagrees" in d.flags


def test_dimension_and_model_agreeing_beat_a_note(monkeypatch) -> None:
    d = _decide(monkeypatch, dim=14.17, note=28.35, model=14.2)
    assert d.ratio == 14.17
    assert "scale:note_disagrees_with_sheet" in d.flags


@pytest.mark.parametrize(
    ("dim", "note", "model"),
    [
        (266.41, 28.35, None),  # a dimension alone against a note
        (None, 28.35, 56.7),  # a note alone against the model
        (2.46, 1417.0, 29.5),  # nothing agrees with anything
        (10.0, None, 20.0),  # a gap of exactly two
    ],
)
def test_a_gap_of_two_or_more_gives_no_confidence(monkeypatch, dim, note, model) -> None:
    d = _decide(monkeypatch, dim=dim, note=note, model=model)
    assert d.confidence < CONFIDENT
    assert "scale:sources_far_apart" in d.flags


def test_a_small_unconfirmed_gap_lowers_the_confidence(monkeypatch) -> None:
    d = _decide(monkeypatch, dim=28.35, note=31.0)
    assert d.ratio == 28.35
    assert d.confidence <= 0.7
    assert "scale:sources_disagree" in d.flags


def test_all_sources_agreeing_stay_confident(monkeypatch) -> None:
    assert _decide(monkeypatch, dim=28.35, note=28.35, model=28.3).confidence >= 0.95
    assert _decide(monkeypatch, dim=28.35).confidence >= 0.8


def _seen(lines: list[tuple[float, float, float, float]], ring=RING) -> str | None:
    segments = np.asarray([(*line, 0.2) for line in lines], dtype=float).reshape(-1, 5)
    return pr.interior_lines(ring, segments, margin=0.2 * M, min_side=1.0 * M, merge=0.6 * M, door=1.2 * M)


def test_thin_partition_inside_a_ring_is_seen() -> None:
    assert _seen([(160, 100, 160, 180)]) == "partition"
    # With a door in its middle and with a door at one end.
    assert _seen([(160, 100, 160, 130), (160, 150, 160, 180)]) == "partition"
    assert _seen([(160, 100, 160, 160)]) == "partition"


def test_furniture_is_not_a_partition() -> None:
    assert _seen([(160, 108, 160, 172)]) is None  # floats free of both sides
    assert _seen([(160, 100, 160, 172)]) is None  # against a wall, ends less than a door short
    assert _seen([(160, 100, 160, 112)]) is None  # short


def test_grid_axis_running_past_the_ring_is_not_a_partition() -> None:
    assert _seen([(160, 40, 160, 240)]) is None


def test_stairs_are_ruled_and_a_tiled_floor_is_not() -> None:
    treads = [(x, 100.0, x, 180.0) for x in np.arange(124.0, 200.0, 6.0)]
    assert _seen(treads) == "ruled"
    across = [(100.0, y, 220.0, y) for y in np.arange(124.0, 160.0, 6.0)]
    assert _seen(treads + across) is None


def test_an_l_shaped_rooms_own_edge_is_not_a_partition() -> None:
    ell = [(100.0, 100.0), (220.0, 100.0), (220.0, 140.0), (160.0, 140.0), (160.0, 180.0), (100.0, 180.0)]
    assert _seen([(160, 140, 160, 180), (160, 140, 220, 140)], ell) is None


def _walled_raster(sides: list[tuple[float, float, float, float]]) -> pr.WallRaster:
    vector = pr.VectorLayer(
        page_width_pt=PAGE[0],
        page_height_pt=PAGE[1],
        segments=[(*side, 2.0) for side in sides] + [(600.0, 600.0 + i, 640.0, 600.0 + i, 0.1) for i in range(40)],
    )
    return pr.WallRaster(pr._wall_index(vector), *PAGE)


def test_a_side_without_a_wall_is_open() -> None:
    raster = _walled_raster([(100, 100, 220, 100), (220, 100, 220, 180), (100, 180, 100, 100)])
    assert not raster.open_edge(RING[0], RING[1], reach=0.06 * M)
    assert raster.open_edge(RING[2], RING[3], reach=0.06 * M)


def test_a_side_broken_by_doors_is_not_open() -> None:
    raster = _walled_raster([(100, 100, 130, 100), (150, 100, 190, 100)])
    assert not raster.open_edge(RING[0], RING[1], reach=0.06 * M)


def _sheet(*words: str) -> pr.VectorLayer:
    boxes = [(0.0, 0.0, 1.0, 1.0, w) for w in words]
    return pr.VectorLayer(page_width_pt=PAGE[0], page_height_pt=PAGE[1], words=boxes)


def test_sheet_type_comes_from_its_words() -> None:
    assert pr.sheet_is_not_a_plan(_sheet("NORTH", "ELEVATION", "SOUTH", "ELEVATION", "1:100"))
    assert pr.sheet_is_not_a_plan(_sheet("Ansicht", "Nord", "Schnitt", "A-A"))
    assert not pr.sheet_is_not_a_plan(_sheet("Grundriss", "Erdgeschoss", "1:100"))
    # A floor plan that points at its sections stays a plan.
    assert not pr.sheet_is_not_a_plan(_sheet("Floor", "Plan", "Level", "1", "Floor", "see", "section", "A"))
    assert not pr.sheet_is_not_a_plan(_sheet("section", "A", "B"))


def _room(name: str = "x", **kw) -> pr.RefinedRoom:
    return pr.RefinedRoom(name, list(RING), 0.8, 0.0, "ok", wall_support=0.9, snapped=True, **kw)


def _stub_raster(nets: dict[str, int], frames: set[int]) -> SimpleNamespace:
    rooms_by_ring = iter(nets.values())
    return SimpleNamespace(network_of=lambda _pts: next(rooms_by_ring), frame_networks=lambda: frames)


def _spread(names: list[str]) -> list[pr.RefinedRoom]:
    out = []
    for i, name in enumerate(names):
        ring = [(x + 130.0 * i, y) for x, y in RING]
        out.append(pr.RefinedRoom(name, ring, 0.8, 0.0, "ok", wall_support=0.9, snapped=True))
    return out


def test_rooms_joined_to_the_frame_are_not_isolated_when_they_are_the_building() -> None:
    rooms = _spread(["a", "b", "c", "d"])
    raster = _stub_raster({"a": 1, "b": 1, "c": 1, "d": 2}, {1})
    pr._flag_overlaps_and_isolation(rooms, gap=1.0, raster=raster)
    assert not any("room:isolated" in r.flags for r in rooms)


def test_a_minority_on_the_frame_network_is_isolated() -> None:
    rooms = _spread(["a", "b", "c", "d"])
    raster = _stub_raster({"a": 2, "b": 2, "c": 2, "d": 1}, {1})
    pr._flag_overlaps_and_isolation(rooms, gap=1.0, raster=raster)
    assert ["room:isolated" in r.flags for r in rooms] == [False, False, False, True]


def _shifted(raw: list[tuple[float, float]]) -> pr.RefinedRoom:
    snapped = [(0.0, 0.0), (4.0, 0.0), (4.0, 3.0), (0.0, 3.0)]
    return pr.RefinedRoom("x", snapped, 0.8, 0.0, "ok", snapped=True, wall_support=1.0, raw_points=raw)


OUTER = [(-0.2, -0.2), (4.2, -0.2), (4.2, 3.2), (-0.2, 3.2)]
INNER = [(0.1, 0.1), (3.9, 0.1), (3.9, 2.9), (0.1, 2.9)]
FAR_INNER = [(0.3, 0.3), (3.7, 0.3), (3.7, 2.7), (0.3, 2.7)]


def test_a_ring_pulled_inward_by_a_walls_width_needs_no_label() -> None:
    room = _shifted(OUTER)
    pr._confirm_snaps([room], 1.0, [], max_wall=0.2)
    assert room.snapped
    assert "room:snap_unconfirmed" not in room.flags


def test_a_ring_grown_past_the_models_needs_a_closed_outline() -> None:
    reverted = _shifted(INNER)
    pr._confirm_snaps([reverted], 1.0, [], max_wall=0.2, evidence=lambda _ring: ["room:open_side"])
    assert not reverted.snapped
    assert "room:snap_unconfirmed" in reverted.flags

    kept = _shifted(INNER)
    pr._confirm_snaps([kept], 1.0, [], max_wall=0.2, evidence=lambda _ring: [])
    assert kept.snapped
    assert "room:snap_large_shift" in kept.flags
    scale = pr.ScaleDecision(ratio=1.0, confidence=0.97, source="page_text")
    assert pr._room_confidence(kept, scale, 1.0, scanned=False) <= 0.72


def test_a_closed_outline_does_not_excuse_a_very_large_shift() -> None:
    room = _shifted(FAR_INNER)
    pr._confirm_snaps([room], 1.0, [], max_wall=0.2, evidence=lambda _ring: [])
    assert not room.snapped
    assert "room:snap_unconfirmed" in room.flags


@pytest.mark.parametrize(
    "flag",
    ["room:open_side", "room:partition_inside", "room:lines_across", "room:sheet_not_a_plan"],
)
def test_ring_evidence_keeps_a_room_below_confident(flag: str) -> None:
    scale = pr.ScaleDecision(ratio=1.0, confidence=0.97, source="page_text")
    clean = _room()
    assert pr._room_confidence(clean, scale, 1.0, scanned=False) >= CONFIDENT
    flagged = _room()
    flagged.flags.append(flag)
    assert pr._room_confidence(flagged, scale, 1.0, scanned=False) < CONFIDENT
