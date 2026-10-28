# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Correctness properties and runtime bounds of the 1D cutting optimiser.

Every plan must place each demanded piece exactly once, keep every bar within
its stock length once kerf and trim are counted, respect stock availability,
and be the same plan on every run.
"""

from __future__ import annotations

import random
import time
from collections import Counter
from decimal import Decimal

import pytest

from app.modules.cutting.linear import (
    LinearPiece,
    LinearSettings,
    LinearStock,
    consumed_length,
    optimise_linear,
    remnant,
    reusable_offcut,
    scrap,
)


def _assert_valid(result, pieces, stocks, settings) -> None:
    demanded = Counter()
    for p in pieces:
        demanded[(p.ref, p.length)] += p.quantity
    placed = Counter((ref, length) for bar in result.bars for ref, length in bar.cuts)
    unplaced = Counter()
    by_ref = {p.ref: p.length for p in pieces}
    for ref, qty in result.unplaced:
        unplaced[(ref, by_ref[ref])] += qty
    assert placed + unplaced == demanded, "every piece is placed exactly once or reported unplaced"
    lengths = {s.ref: s.length for s in stocks}
    used = Counter(bar.stock_ref for bar in result.bars)
    for stock in stocks:
        if stock.available is not None:
            assert used[stock.ref] <= stock.available, f"stock {stock.ref} used beyond availability"
    for bar in result.bars:
        assert bar.stock_length == lengths[bar.stock_ref]
        assert consumed_length([c[1] for c in bar.cuts], settings.kerf, settings.trim) <= bar.stock_length
        assert bar.cuts, "no empty bars"
        assert scrap(bar, settings) >= 0
        assert bar.piece_length + reusable_offcut(bar, settings) + scrap(bar, settings) == bar.stock_length


def test_a_simple_job_places_every_piece_within_bounds() -> None:
    pieces = [LinearPiece("A", 40000, 5), LinearPiece("B", 30000, 7), LinearPiece("C", 25000, 3)]
    stocks = [LinearStock("12m", 120000, Decimal("60")), LinearStock("6m", 60000, Decimal("32"))]
    settings = LinearSettings(kerf=30, min_offcut=5000)
    result = optimise_linear(pieces, stocks, settings)
    _assert_valid(result, pieces, stocks, settings)
    assert result.unplaced == []


def test_kerf_is_charged_between_pieces_but_not_after_a_piece_ending_at_the_bar_end() -> None:
    settings = LinearSettings(kerf=5)
    # two 50 pieces need 50 + 5 + 50 = 105 on a 105 bar, with no trailing kerf
    result = optimise_linear([LinearPiece("A", 50, 2)], [LinearStock("S", 105)], settings)
    assert len(result.bars) == 1
    assert remnant(result.bars[0], settings) == 0
    # on a 104 bar they no longer fit together
    result = optimise_linear([LinearPiece("A", 50, 2)], [LinearStock("S", 104)], settings)
    assert len(result.bars) == 2


def test_trim_is_taken_off_every_bar() -> None:
    settings = LinearSettings(trim=10)
    result = optimise_linear([LinearPiece("A", 95, 1)], [LinearStock("S", 100)], settings)
    assert result.unplaced == [("A", 1)]
    result = optimise_linear([LinearPiece("A", 90, 1)], [LinearStock("S", 100)], settings)
    assert result.unplaced == []


def test_a_piece_longer_than_every_stock_is_reported_not_dropped() -> None:
    pieces = [LinearPiece("LONG", 130000, 2), LinearPiece("OK", 1000, 1)]
    result = optimise_linear(pieces, [LinearStock("12m", 120000)], LinearSettings())
    assert result.unplaced == [("LONG", 2)]
    assert sum(len(b.cuts) for b in result.bars) == 1


def test_limited_availability_is_respected_and_the_shortfall_reported() -> None:
    pieces = [LinearPiece("A", 6000, 6)]
    stocks = [LinearStock("S", 12000, available=2)]
    settings = LinearSettings()
    result = optimise_linear(pieces, stocks, settings)
    _assert_valid(result, pieces, stocks, settings)
    assert len(result.bars) == 2
    assert result.unplaced == [("A", 2)]


def test_inventory_offcuts_are_used_before_purchased_stock() -> None:
    pieces = [LinearPiece("A", 2500, 2), LinearPiece("B", 9000, 1)]
    stocks = [LinearStock("12m", 12000, Decimal("60")), LinearStock("OFF", 3000, available=2, is_offcut=True)]
    settings = LinearSettings()
    result = optimise_linear(pieces, stocks, settings)
    _assert_valid(result, pieces, stocks, settings)
    offcut_bars = [b for b in result.bars if b.is_offcut]
    assert len(offcut_bars) == 2
    assert all(c[0] == "A" for b in offcut_bars for c in b.cuts)


def test_cheaper_stock_per_metre_wins_when_prices_are_known() -> None:
    # 12 m costs 50 (4.17/m), 6 m costs 40 (6.67/m): two 5.9 m pieces belong on one 12 m bar
    pieces = [LinearPiece("A", 59000, 2)]
    stocks = [LinearStock("12m", 120000, Decimal("50")), LinearStock("6m", 60000, Decimal("40"))]
    result = optimise_linear(pieces, stocks, LinearSettings(kerf=30))
    assert [b.stock_ref for b in result.bars] == ["12m"]


def test_a_lone_short_piece_is_moved_to_the_shorter_stock() -> None:
    pieces = [LinearPiece("A", 70000, 1), LinearPiece("B", 50000, 1), LinearPiece("C", 20000, 1)]
    stocks = [LinearStock("12m", 120000, Decimal("60")), LinearStock("3m", 30000, Decimal("16"))]
    result = optimise_linear(pieces, stocks, LinearSettings())
    assert sorted(b.stock_ref for b in result.bars) == ["12m", "3m"]


def test_the_exact_search_proves_a_small_instance_optimal() -> None:
    pieces = [LinearPiece("A", 4000, 2), LinearPiece("B", 3000, 3), LinearPiece("C", 2000, 4)]
    result = optimise_linear(pieces, [LinearStock("6m", 6000)], LinearSettings())
    assert result.exact is True
    assert result.proven_optimal is True
    assert len(result.bars) == 5  # 25 m of pieces needs at least 5 six-metre bars


def test_the_exact_search_beats_a_greedy_trap() -> None:
    # Greedy FFD packs 5+... badly; an optimum of 3 bars of 10 exists: (5,5) (4,3,3) (4,3,3)
    pieces = [LinearPiece("F", 5, 2), LinearPiece("D", 4, 2), LinearPiece("T", 3, 4)]
    result = optimise_linear(pieces, [LinearStock("10", 10)], LinearSettings())
    assert len(result.bars) == 3
    assert result.proven_optimal is True


def test_the_plan_is_deterministic() -> None:
    rnd = random.Random(7)
    pieces = [LinearPiece(f"P{i}", rnd.randint(300, 5900), rnd.randint(1, 4)) for i in range(120)]
    stocks = [LinearStock("12m", 12000, Decimal("60")), LinearStock("6m", 6000, Decimal("32"))]
    settings = LinearSettings(kerf=4, min_offcut=500)
    first = optimise_linear(pieces, stocks, settings)
    second = optimise_linear(pieces, stocks, settings)
    assert [(b.stock_ref, b.cuts) for b in first.bars] == [(b.stock_ref, b.cuts) for b in second.bars]


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_random_instances_keep_every_property(seed: int) -> None:
    rnd = random.Random(seed)
    pieces = [LinearPiece(f"P{i}", rnd.randint(100, 7000), rnd.randint(1, 6)) for i in range(60)]
    stocks = [
        LinearStock("12m", 12000, Decimal("60")),
        LinearStock("6m", 6000, Decimal("32"), available=10),
        LinearStock("OFF", 2500, available=5, is_offcut=True),
    ]
    settings = LinearSettings(kerf=rnd.randint(0, 6), trim=rnd.randint(0, 20), min_offcut=400)
    result = optimise_linear(pieces, stocks, settings)
    _assert_valid(result, pieces, stocks, settings)
    assert result.unplaced == []


def test_two_thousand_pieces_finish_within_the_time_bound() -> None:
    rnd = random.Random(1)
    pieces = [LinearPiece(f"P{i}", rnd.randint(300, 5900), rnd.randint(1, 5)) for i in range(800)]
    stocks = [LinearStock("12m", 12000, Decimal("60")), LinearStock("6m", 6000, Decimal("32"))]
    settings = LinearSettings(kerf=4, min_offcut=500, time_limit_s=2.0)
    started = time.monotonic()
    result = optimise_linear(pieces, stocks, settings)
    elapsed = time.monotonic() - started
    _assert_valid(result, pieces, stocks, settings)
    assert elapsed < 10.0, f"took {elapsed:.1f}s"
    yield_ratio = sum(b.piece_length for b in result.bars) / sum(b.stock_length for b in result.bars)
    assert yield_ratio > 0.95
