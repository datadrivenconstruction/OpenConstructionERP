# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Correctness properties and runtime bounds of the 2D guillotine optimiser.

Every layout must place each piece exactly once, keep pieces inside the
trimmed sheet, keep a saw kerf between neighbours, never turn a grain-locked
piece, and be cuttable edge to edge (guillotine).
"""

from __future__ import annotations

import random
import time
from collections import Counter
from decimal import Decimal

import pytest

from app.modules.cutting.sheet import (
    SheetPiece,
    SheetSettings,
    SheetStock,
    optimise_sheets,
    reusable_offcuts,
    sheet_scrap,
)


def _guillotine(rects: list[tuple[int, int, int, int]], x0: int, y0: int, x1: int, y1: int) -> bool:
    """Whether the rectangles in a region can be separated by edge-to-edge cuts."""
    if len(rects) <= 1:
        return True
    for axis in (0, 1):
        lo, hi = (x0, x1) if axis == 0 else (y0, y1)
        cuts = sorted({r[axis] + r[axis + 2] for r in rects} | {r[axis] for r in rects})
        for c in cuts:
            if not lo < c < hi:
                continue
            first = [r for r in rects if r[axis] + r[axis + 2] <= c]
            second = [r for r in rects if r[axis] >= c]
            if len(first) + len(second) == len(rects) and first and second:
                if axis == 0:
                    return _guillotine(first, x0, y0, c, y1) and _guillotine(second, c, y0, x1, y1)
                return _guillotine(first, x0, y0, x1, c) and _guillotine(second, x0, c, x1, y1)
    return False


def _assert_valid(result, pieces, stocks, settings) -> None:
    demanded = Counter()
    for p in pieces:
        demanded[p.ref] += p.quantity
    placed = Counter(pl.ref for sh in result.sheets for pl in sh.placements)
    assert placed + Counter(dict(result.unplaced)) == demanded
    by_ref = {p.ref: p for p in pieces}
    used = Counter(sh.stock_ref for sh in result.sheets)
    for stock in stocks:
        if stock.available is not None:
            assert used[stock.ref] <= stock.available
    k, t = settings.kerf, settings.trim
    for sh in result.sheets:
        rects = []
        for pl in sh.placements:
            piece = by_ref[pl.ref]
            dims = (pl.h, pl.w) if pl.rotated else (pl.w, pl.h)
            assert dims == (piece.width, piece.height)
            if not piece.rotatable:
                assert not pl.rotated, "a grain-locked piece was turned"
            assert pl.x >= t and pl.y >= t
            assert pl.x + pl.w <= sh.width - t and pl.y + pl.h <= sh.height - t
            # the kerf-grown footprint, clipped to the usable area
            rects.append((pl.x, pl.y, min(pl.w + k, sh.width - t - pl.x), min(pl.h + k, sh.height - t - pl.y)))
        for i, a in enumerate(rects):
            for b in rects[i + 1 :]:
                overlap = a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]
                assert not overlap, f"pieces overlap (kerf included) on {sh.stock_ref}: {a} {b}"
        assert _guillotine(rects, t, t, sh.width - t, sh.height - t), "layout is not guillotine-cuttable"
        assert sheet_scrap(sh, settings) >= 0


def test_a_simple_job_is_valid() -> None:
    pieces = [SheetPiece("A", 1200, 600, 4), SheetPiece("B", 800, 400, 6), SheetPiece("C", 300, 300, 10)]
    stocks = [SheetStock("2500x1250", 2500, 1250, Decimal("40"))]
    settings = SheetSettings(kerf=4, trim=10, min_offcut=200)
    result = optimise_sheets(pieces, stocks, settings)
    _assert_valid(result, pieces, stocks, settings)
    assert result.unplaced == []


def test_a_grain_locked_piece_that_only_fits_turned_is_unplaced() -> None:
    pieces = [SheetPiece("G", 1000, 2000, 1, rotatable=False)]
    result = optimise_sheets(pieces, [SheetStock("S", 2500, 1250)], SheetSettings())
    assert result.unplaced == [("G", 1)]
    pieces = [SheetPiece("R", 1000, 2000, 1, rotatable=True)]
    result = optimise_sheets(pieces, [SheetStock("S", 2500, 1250)], SheetSettings())
    assert result.unplaced == []
    assert result.sheets[0].placements[0].rotated is True


def test_kerf_separates_neighbours() -> None:
    # two 1250 wide pieces fit a 2500 sheet only without kerf
    pieces = [SheetPiece("A", 1250, 1250, 2)]
    no_kerf = optimise_sheets(pieces, [SheetStock("S", 2500, 1250)], SheetSettings(kerf=0))
    with_kerf = optimise_sheets(pieces, [SheetStock("S", 2500, 1250)], SheetSettings(kerf=4))
    assert len(no_kerf.sheets) == 1
    assert len(with_kerf.sheets) == 2


def test_reusable_offcuts_respect_the_minimum() -> None:
    settings = SheetSettings(min_offcut=500)
    result = optimise_sheets([SheetPiece("A", 1000, 1250, 1)], [SheetStock("S", 2500, 1250)], settings)
    offcuts = reusable_offcuts(result.sheets[0], settings)
    assert [(r.w, r.h) for r in offcuts] == [(1500, 1250)]
    assert reusable_offcuts(result.sheets[0], SheetSettings(min_offcut=0)) == []


def test_inventory_offcut_sheets_are_used_first() -> None:
    pieces = [SheetPiece("A", 500, 500, 2)]
    stocks = [SheetStock("FULL", 2500, 1250, Decimal("40")), SheetStock("OFF", 1100, 600, available=1, is_offcut=True)]
    result = optimise_sheets(pieces, stocks, SheetSettings())
    assert [s.stock_ref for s in result.sheets] == ["OFF"]


def test_the_layout_is_deterministic() -> None:
    rnd = random.Random(3)
    pieces = [SheetPiece(f"S{i}", rnd.randint(100, 1200), rnd.randint(100, 1200), rnd.randint(1, 3)) for i in range(60)]
    stocks = [SheetStock("A", 2500, 1250, Decimal("40")), SheetStock("B", 2800, 2070, Decimal("70"))]
    first = optimise_sheets(pieces, stocks, SheetSettings(kerf=4))
    second = optimise_sheets(pieces, stocks, SheetSettings(kerf=4))
    assert [(s.stock_ref, s.placements) for s in first.sheets] == [(s.stock_ref, s.placements) for s in second.sheets]


@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_random_instances_keep_every_property(seed: int) -> None:
    rnd = random.Random(seed)
    pieces = [
        SheetPiece(f"S{i}", rnd.randint(50, 1300), rnd.randint(50, 1200), rnd.randint(1, 3), rotatable=i % 3 != 0)
        for i in range(50)
    ]
    stocks = [
        SheetStock("A", 2500, 1250, Decimal("40")),
        SheetStock("B", 2800, 2070, Decimal("70"), available=4),
        SheetStock("OFF", 900, 700, available=3, is_offcut=True),
    ]
    settings = SheetSettings(kerf=rnd.randint(0, 5), trim=rnd.randint(0, 15), min_offcut=200)
    result = optimise_sheets(pieces, stocks, settings)
    _assert_valid(result, pieces, stocks, settings)


def test_five_hundred_pieces_finish_within_the_time_bound() -> None:
    rnd = random.Random(1)
    pieces = [
        SheetPiece(f"S{i}", rnd.randint(100, 1200), rnd.randint(100, 1200), rnd.randint(1, 3)) for i in range(250)
    ]
    stocks = [SheetStock("A", 2500, 1250, Decimal("40")), SheetStock("B", 2800, 2070, Decimal("70"))]
    settings = SheetSettings(kerf=4, trim=10, min_offcut=300)
    started = time.monotonic()
    result = optimise_sheets(pieces, stocks, settings)
    elapsed = time.monotonic() - started
    _assert_valid(result, pieces, stocks, settings)
    assert elapsed < 10.0, f"took {elapsed:.1f}s"
    ratio = sum(s.piece_area for s in result.sheets) / sum(s.area for s in result.sheets)
    assert ratio > 0.8
