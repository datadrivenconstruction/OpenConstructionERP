"""The floor-plan reader's parts: hatching, clipping, openings, sheet topology, time and memory."""

from __future__ import annotations

import math
import random
import time

import numpy as np
import pytest

from app.modules.takeoff import floorplan as fp
from app.modules.takeoff import recognize, vector_plan
from app.modules.takeoff.vector_plan import Budget, Seg, TimeBudgetExceeded, drop_hatching

PT_PER_M = 72 / 0.0254 / 50


def _seg(x1: float, y1: float, x2: float, y2: float, lw: float = 0.5) -> Seg:
    return Seg((x1, y1), (x2, y2), lw, 0)


def _hatch(x0: float, y0: float, n: int, pitch: float = 2.3, length: float = 120.0, deg: float = 135.0) -> list[Seg]:
    ca, sa = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    out = []
    for i in range(n):
        ox, oy = x0 - sa * pitch * i, y0 + ca * pitch * i
        out.append(_seg(ox, oy, ox + ca * length, oy + sa * length))
    return out


def _rect_walls(x0: float, y0: float, x1: float, y1: float, t: float) -> list[Seg]:
    """A room outlined by double-line walls, faces ``t`` apart."""
    return [
        _seg(x0, y0, x1, y0),
        _seg(x0 - t, y0 - t, x1 + t, y0 - t),
        _seg(x0, y1, x1, y1),
        _seg(x0 - t, y1 + t, x1 + t, y1 + t),
        _seg(x0, y0, x0, y1),
        _seg(x0 - t, y0 - t, x0 - t, y1 + t),
        _seg(x1, y0, x1, y1),
        _seg(x1 + t, y0 - t, x1 + t, y1 + t),
    ]


class TestHatching:
    def test_a_family_of_even_parallels_goes_at_any_angle(self) -> None:
        for deg in (135.0, 45.0, 0.0, 90.0, 17.0):
            lines = _hatch(500, 500, 40, deg=deg)
            assert drop_hatching(lines) == []

    def test_wall_faces_stay(self) -> None:
        walls = _rect_walls(100, 100, 400, 300, 8.0)
        assert len(drop_hatching(walls)) == len(walls)

    def test_a_row_of_party_walls_stays(self) -> None:
        # Bays 3.6 m apart are evenly spaced parallels too; nothing about them is a pattern.
        bays = [_seg(100 + i * 3.6 * PT_PER_M, 100, 100 + i * 3.6 * PT_PER_M, 400) for i in range(16)]
        assert len(drop_hatching(bays, PT_PER_M)) == 16

    def test_a_wall_of_five_layers_stays(self) -> None:
        layers = [_seg(100, 100 + c, 800, 100 + c) for c in (0.0, 0.9, 6.5, 8.5, 17.0)]
        assert len(drop_hatching(layers, PT_PER_M)) == 5

    def test_hatching_inside_a_wall_leaves_the_wall_and_the_frame_upright(self) -> None:
        walls = _rect_walls(100, 100, 400, 300, 8.0)
        # Long diagonal lines outweigh the walls by squared length unless they are classified first.
        hatch = _hatch(600, 150, 200, length=400.0)
        kept = drop_hatching(walls + hatch)
        assert len(kept) == len(walls)
        assert vector_plan.candidate_angles(kept, [])[0] == 0.0


class TestClipping:
    def test_a_stroke_is_cut_to_its_clip(self) -> None:
        box = [(10.0, 10.0), (20.0, 10.0), (20.0, 20.0), (10.0, 20.0)]
        drawing = {
            "items": [("l", (0.0, 15.0), (30.0, 15.0))],
            "type": "s",
            "width": 1.0,
            "color": (0, 0, 0),
            "clip": [box],
        }
        segs, _fills, _curves = vector_plan.parse([drawing])
        assert len(segs) == 1
        assert sorted(p[0] for p in (segs[0].a, segs[0].b)) == pytest.approx([10.0, 20.0])

    def test_a_stroke_outside_its_clip_is_gone(self) -> None:
        box = [(10.0, 10.0), (20.0, 10.0), (20.0, 20.0), (10.0, 20.0)]
        drawing = {
            "items": [("l", (0.0, 50.0), (30.0, 50.0))],
            "type": "s",
            "width": 1.0,
            "color": (0, 0, 0),
            "clip": [box],
        }
        assert vector_plan.parse([drawing])[0] == []

    def test_what_lies_off_the_page_is_not_on_the_drawing(self) -> None:
        drawing = {"items": [("l", (900.0, 15.0), (3000.0, 15.0))], "type": "s", "width": 1.0, "color": (0, 0, 0)}
        segs = vector_plan.parse([drawing], (1000.0, 800.0))[0]
        assert max(segs[0].a[0], segs[0].b[0]) == pytest.approx(1000.0)


class TestOpenings:
    @staticmethod
    def _mask() -> np.ndarray:
        return np.zeros((400, 400), np.uint8)

    def test_two_jambs_are_an_opening(self) -> None:
        mask = self._mask()
        mask[200:208, 20:150] = 255
        mask[200:208, 200:380] = 255
        bands = fp.axis_bands(mask, min_len_px=6)
        assert fp.bridge_gaps(mask, bands, lambda _t: 100.0) == 1
        assert mask[204, 175] == 255

    def test_walls_lined_up_across_a_corridor_are_not(self) -> None:
        mask = self._mask()
        mask[100:106, 20:380] = 255  # the corridor's walls
        mask[160:166, 20:380] = 255
        mask[20:100, 200:206] = 255  # party walls either side, in line
        mask[166:380, 200:206] = 255
        bands = fp.axis_bands(mask, min_len_px=6)
        fp.bridge_gaps(mask, bands, lambda _t: 100.0)
        assert mask[130, 203] == 0

    def test_a_door_taking_the_corner_does_not_free_a_party_wall(self) -> None:
        mask = self._mask()
        mask[100:106, 20:190] = 255  # corridor wall, with a door right where the party wall meets it
        mask[100:106, 230:380] = 255
        mask[160:166, 20:380] = 255
        mask[20:100, 200:206] = 255
        mask[166:380, 200:206] = 255
        bands = fp.axis_bands(mask, min_len_px=6)
        fp.bridge_gaps(mask, bands, lambda _t: 100.0)
        assert mask[130, 203] == 0

    def test_a_seam_is_closed_whatever_runs_past_it(self) -> None:
        mask = self._mask()
        mask[200:208, 20:150] = 255
        mask[200:208, 152:380] = 255
        bands = fp.axis_bands(mask, min_len_px=6)
        assert fp.bridge_gaps(mask, bands, lambda _t: 100.0) == 1


class TestPairs:
    def test_the_index_finds_what_comparing_everything_finds(self) -> None:
        rng = random.Random(7)
        lines = sorted(
            (
                vector_plan._Line1D(rng.uniform(0, 400), lo, lo + rng.uniform(1, 200), i)
                for i, lo in enumerate(rng.uniform(0, 1000) for _ in range(300))
            ),
            key=lambda ln: ln.c,
        )
        got = {(i, j) for i, j, _d, _ov in vector_plan._candidate_pairs(lines, 20.0)}
        want = set()
        for i, a in enumerate(lines):
            for j in range(i + 1, len(lines)):
                b = lines[j]
                if b.c - a.c > 20.0:
                    break
                if b.c - a.c >= 0.35 and min(a.hi, b.hi) - max(a.lo, b.lo) > 0.5:
                    want.add((i, j))
        assert got == want

    def test_a_stroke_keeps_its_nearest_partners(self) -> None:
        lines = [vector_plan._Line1D(i * 0.5, 0.0, 100.0, i) for i in range(2000)]
        pairs = vector_plan._candidate_pairs(lines, 40.0)
        per_stroke: dict[int, int] = {}
        for i, _j, _d, _ov in pairs:
            per_stroke[i] = per_stroke.get(i, 0) + 1
        assert max(per_stroke.values()) <= vector_plan._MAX_PARTNERS


class TestTopology:
    @staticmethod
    def _room(x0: int, y0: int, x1: int, y1: int, neighbours: int = 1) -> dict:
        return {"box_px": (x0, y0, x1, y1), "neighbours": neighbours, "tol_px": 6.0}

    def test_rooms_sharing_walls_read_as_a_plan(self) -> None:
        rooms = [
            self._room(0, 0, 100, 120),
            self._room(106, 0, 200, 60),
            self._room(106, 66, 260, 120),
            self._room(0, 126, 260, 170),
        ]
        assert vector_plan.looks_like_rooms(vector_plan.PlanResult(rooms=rooms))

    def test_windows_on_a_facade_do_not(self) -> None:
        rooms = [self._room(100 + 300 * i, 100, 160 + 300 * i, 180, neighbours=0) for i in range(8)]
        assert not vector_plan.looks_like_rooms(vector_plan.PlanResult(rooms=rooms))

    def test_table_cells_do_not(self) -> None:
        rooms = [self._room(c * 106, r * 26, c * 106 + 100, r * 26 + 20) for c in range(5) for r in range(12)]
        assert not vector_plan.looks_like_rooms(vector_plan.PlanResult(rooms=rooms))


class TestConfidence:
    @staticmethod
    def _plan() -> vector_plan.PlanResult:
        square = [(100.0, 100.0), (300.0, 100.0), (300.0, 300.0), (100.0, 300.0)]
        sliver = [(400.0, 100.0), (640.0, 100.0), (640.0, 112.0), (400.0, 112.0)]
        common = {"snapped": 1.0, "vertices": 4, "neighbours": 1, "box_px": (0, 0, 1, 1), "tol_px": 4.0}
        return vector_plan.PlanResult(
            rooms=[
                {**common, "points": square, "closure": 0.9, "rectangularity": 1.0, "aspect": 1.0},
                {**common, "points": sliver, "closure": 0.5, "rectangularity": 1.0, "aspect": 20.0},
            ]
        )

    def test_snapping_alone_earns_nothing(self) -> None:
        cands = recognize.plan_candidates(self._plan(), PT_PER_M)
        assert cands[0]["confidence"] > cands[1]["confidence"] + 0.1

    def test_a_name_and_a_matching_printed_area_raise_it(self) -> None:
        area = (200 / PT_PER_M) ** 2
        words = [
            (180.0, 180.0, 220.0, 190.0, "OFFICE"),
            (180.0, 195.0, 200.0, 205.0, f"{area:.2f}"),
            (201.0, 195.0, 215.0, 205.0, "m²"),
        ]
        named = recognize.plan_candidates(self._plan(), PT_PER_M, words)
        bare = recognize.plan_candidates(self._plan(), PT_PER_M, [(1.0, 1.0, 9.0, 9.0, "NOTES")])
        assert named[0]["confidence"] > bare[0]["confidence"] + 0.2

    def test_a_printed_area_that_disagrees_lowers_it(self) -> None:
        words = [
            (180.0, 180.0, 220.0, 190.0, "OFFICE"),
            (180.0, 195.0, 200.0, 205.0, "3.00"),
            (201.0, 195.0, 215.0, 205.0, "m²"),
        ]
        wrong = recognize.plan_candidates(self._plan(), PT_PER_M, words)
        area = (200 / PT_PER_M) ** 2
        right_words = [*words[:1], (180.0, 195.0, 200.0, 205.0, f"{area:.2f}"), words[2]]
        right = recognize.plan_candidates(self._plan(), PT_PER_M, right_words)
        assert wrong[0]["confidence"] < right[0]["confidence"] - 0.2

    def test_square_feet_are_read(self) -> None:
        words = [(10.0, 10.0, 30.0, 20.0, "120"), (32.0, 10.0, 44.0, 20.0, "SF")]
        assert recognize._printed_area_m2(words, 0) == pytest.approx(120 * 0.09290304)


class TestCeiling:
    def test_rooms_go_before_walls_and_the_rest_is_reported(self) -> None:
        rooms = [{"dimension": "area", "confidence": 0.5} for _ in range(70)]
        walls = [{"dimension": "length", "confidence": 0.9} for _ in range(50)]
        kept, held = recognize._rank_and_cap(rooms + walls, 100)
        assert held == 20
        assert sum(c["dimension"] == "area" for c in kept) == 70

    def test_what_is_hardly_a_guess_is_not_proposed(self) -> None:
        kept, held = recognize._rank_and_cap([{"dimension": "area", "confidence": 0.2}], 100)
        assert kept == []
        assert held == 0


class TestTime:
    def test_twenty_thousand_hatch_lines_are_quick(self) -> None:
        segs = _rect_walls(100, 100, 800, 500, 8.0) + _hatch(900, 150, 20_000, pitch=0.2, length=300.0)
        t0 = time.perf_counter()
        vector_plan.read_parts(segs, [], [], PT_PER_M)
        assert time.perf_counter() - t0 < 15.0

    def test_a_dense_field_of_short_strokes_stops_at_the_budget(self) -> None:
        rng = random.Random(3)
        segs = []
        for _ in range(60_000):
            x, y = rng.uniform(0, 2000), rng.uniform(0, 1400)
            segs.append(_seg(x, y, x + rng.uniform(5, 60), y))
        t0 = time.perf_counter()
        with pytest.raises(TimeBudgetExceeded):
            vector_plan.read_parts(segs, [], [], PT_PER_M, budget=Budget(0.2))
        assert time.perf_counter() - t0 < 10.0

    def test_a_budget_without_seconds_never_runs_out(self) -> None:
        Budget(None).check()
