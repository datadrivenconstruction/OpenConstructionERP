# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""One-dimensional cutting stock optimiser (bars, profiles, pipes, timber).

Pure Python, no database, no randomness. Lengths are integers in one unit the
caller chooses (the service uses tenths of a millimetre), so every comparison is
exact and the same input always yields the same plan.

Model of a cut bar:

* ``trim`` is cut off the bar end first (damaged or unsquare end).
* Every piece after the first is separated from its neighbour by one ``kerf``.
  The last piece may end exactly at the bar end without a cut.
* Whatever is left after the last piece costs one more kerf to separate. If the
  remnant is at least ``min_offcut`` it is a reusable offcut, otherwise scrap.

Strategy, in order:

1. Pattern-greedy: open one bar at a time, choosing the stock type whose
   first-fit-decreasing fill gives the lowest cost per placed length (inventory
   offcuts are free, so they are used first). The fill is improved by swaps.
2. Local improvement: try to empty the least-filled bar into the others and
   downsize each bar to the cheapest stock type its cuts still fit.
3. Exact branch and bound for small single-stock instances, bounded by a node
   budget (deterministic) and a wall-clock cap (safety).
"""

from __future__ import annotations

import time
from bisect import bisect_left, bisect_right, insort
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal

_ZERO = Decimal("0")


@dataclass(frozen=True)
class LinearPiece:
    """A demanded piece: ``quantity`` cuts of ``length``."""

    ref: str
    length: int
    quantity: int = 1
    label: str = ""


@dataclass(frozen=True)
class LinearStock:
    """A stock length on offer.

    ``available`` of ``None`` means unlimited (purchasable). ``is_offcut`` marks
    an inventory remnant; offcuts are used before purchased stock.
    """

    ref: str
    length: int
    cost: Decimal = _ZERO
    available: int | None = None
    is_offcut: bool = False
    label: str = ""


@dataclass(frozen=True)
class LinearSettings:
    """Cutting constraints and search limits."""

    kerf: int = 0
    trim: int = 0
    min_offcut: int = 0
    exact_max_pieces: int = 14
    node_budget: int = 200_000
    time_limit_s: float = 2.0


@dataclass
class CutBar:
    """One stock piece and the cuts taken from it."""

    stock_ref: str
    stock_length: int
    cost: Decimal
    is_offcut: bool
    cuts: list[tuple[str, int]] = field(default_factory=list)

    @property
    def piece_length(self) -> int:
        """Sum of the piece lengths cut from this bar."""
        return sum(c[1] for c in self.cuts)


@dataclass
class LinearResult:
    """A complete cutting plan with its key figures."""

    bars: list[CutBar]
    unplaced: list[tuple[str, int]]
    exact: bool
    proven_optimal: bool
    elapsed_ms: int


def consumed_length(lengths: list[int], kerf: int, trim: int) -> int:
    """Length a set of pieces needs on one bar, kerfs between pieces and trim included."""
    if not lengths:
        return trim
    return trim + sum(lengths) + kerf * (len(lengths) - 1)


def fits(lengths: list[int], capacity: int, kerf: int, trim: int) -> bool:
    """Whether the pieces fit on a bar of ``capacity``."""
    return consumed_length(lengths, kerf, trim) <= capacity


def remnant(bar: CutBar, settings: LinearSettings) -> int:
    """Length left after the last piece and the kerf that frees it (never negative)."""
    lengths = [c[1] for c in bar.cuts]
    left = bar.stock_length - consumed_length(lengths, settings.kerf, settings.trim)
    if left <= 0:
        return 0
    return max(0, left - settings.kerf)


def scrap(bar: CutBar, settings: LinearSettings) -> int:
    """Waste on a bar: everything that is neither a piece nor a reusable offcut."""
    rest = remnant(bar, settings)
    offcut = rest if rest >= settings.min_offcut and settings.min_offcut > 0 else 0
    return bar.stock_length - bar.piece_length - offcut


def reusable_offcut(bar: CutBar, settings: LinearSettings) -> int:
    """The reusable remnant of a bar, or 0 when it is shorter than ``min_offcut``."""
    rest = remnant(bar, settings)
    return rest if settings.min_offcut > 0 and rest >= settings.min_offcut else 0


# -- Pattern-greedy ---------------------------------------------------------


def _fill(
    capacity: int, demand: dict[int, int], keys: list[int], settings: LinearSettings, *, improve: bool = True
) -> list[int]:
    """First-fit-decreasing fill of one bar from the remaining demand (``keys`` sorted descending), then swaps."""
    kerf, trim = settings.kerf, settings.trim
    chosen: list[int] = []
    used = trim
    smallest = keys[-1] if keys else 0
    for length in keys:
        if chosen and used + kerf + smallest > capacity:
            break
        if used + length + (kerf if chosen else 0) > capacity:
            continue
        count = demand[length]
        while count > 0:
            extra = length + (kerf if chosen else 0)
            if used + extra > capacity:
                break
            chosen.append(length)
            used += extra
            count -= 1
    if not improve or not chosen:
        return chosen
    return _improve_fill(chosen, capacity, demand, keys, settings)


def _take(spare: list[int], left: Counter[int], length: int) -> None:
    left[length] -= 1
    if left[length] == 0:
        del spare[bisect_left(spare, length)]


def _give(spare: list[int], left: Counter[int], length: int) -> None:
    if left[length] <= 0:
        insort(spare, length)
        left[length] = 0
    left[length] += 1


def _improve_fill(
    chosen: list[int], capacity: int, demand: dict[int, int], keys: list[int], settings: LinearSettings
) -> list[int]:
    """Swap one chosen piece for one or two remaining pieces of greater total length while the fill grows."""
    kerf, trim = settings.kerf, settings.trim
    left: Counter[int] = Counter(demand)
    for ln in chosen:
        left[ln] -= 1
    spare = [ln for ln in reversed(keys) if left[ln] > 0]
    load = consumed_length(chosen, kerf, trim)
    for _round in range(60):
        slack = capacity - load
        if slack <= 0 or not spare:
            break
        swapped = False
        for out in sorted(set(chosen))[:40]:
            # one-for-one: the longest remaining piece that still fits in out's place
            pos = bisect_right(spare, out + slack) - 1
            if pos >= 0 and spare[pos] > out:
                cand = spare[pos]
                chosen[chosen.index(out)] = cand
                load += cand - out
                _take(spare, left, cand)
                _give(spare, left, out)
                swapped = True
                break
            # one-for-two: two pieces in out's place, costing one more kerf
            budget = out + slack - kerf
            hi = bisect_right(spare, budget)
            pool = spare[max(0, hi - 40) : hi]
            pair = None
            for a in reversed(pool):
                rest = budget - a
                j = bisect_right(spare, min(rest, a)) - 1
                while j >= 0 and spare[j] == a and left[a] < 2:
                    j -= 1
                if j >= 0 and a + spare[j] > out:
                    pair = (a, spare[j])
                    break
            if pair is not None:
                chosen.remove(out)
                chosen.extend(pair)
                load += pair[0] + pair[1] + kerf - out
                _take(spare, left, pair[0])
                _take(spare, left, pair[1])
                _give(spare, left, out)
                swapped = True
                break
        if not swapped:
            break
    return sorted(chosen, reverse=True)


def _priced(stocks: list[LinearStock]) -> bool:
    purchasable = [s for s in stocks if not s.is_offcut]
    return bool(purchasable) and all(s.cost > 0 for s in purchasable)


def _score(stock: LinearStock, filled: list[int], priced: bool) -> tuple:
    placed = sum(filled)
    if stock.is_offcut:
        return (0, Decimal(-placed), stock.length, stock.ref)
    if priced:
        return (1, stock.cost / placed, stock.length, stock.ref)
    return (1, Decimal(stock.length - placed) / placed, stock.length, stock.ref)


def _greedy(pieces: list[LinearPiece], stocks: list[LinearStock], settings: LinearSettings, deadline: float) -> tuple:
    """Open bars one by one with the best-scoring stock pattern until demand is met."""
    demand: Counter[int] = Counter()
    refs: dict[int, list[str]] = {}
    for piece in pieces:
        demand[piece.length] += piece.quantity
        refs.setdefault(piece.length, []).extend([piece.ref] * piece.quantity)
    for length in refs:
        refs[length].sort()
    remaining = {s.ref: s.available for s in stocks}
    priced = _priced(stocks)
    bars: list[CutBar] = []
    while True:
        live = {ln: c for ln, c in demand.items() if c > 0}
        if not live:
            break
        keys = sorted(live, reverse=True)
        improve = time.monotonic() < deadline
        best: tuple | None = None
        for stock in stocks:
            if remaining[stock.ref] is not None and remaining[stock.ref] <= 0:
                continue
            filled = _fill(stock.length, live, keys, settings, improve=improve)
            if not filled:
                continue
            key = _score(stock, filled, priced)
            if best is None or key < best[0]:
                best = (key, stock, filled)
        if best is None:
            break
        _, stock, filled = best
        if remaining[stock.ref] is not None:
            remaining[stock.ref] -= 1
        bar = CutBar(stock.ref, stock.length, stock.cost, stock.is_offcut)
        for length in filled:
            demand[length] -= 1
            bar.cuts.append((refs[length].pop(0), length))
        bars.append(bar)
    unplaced_counter: Counter[str] = Counter()
    for length, count in (+demand).items():
        for ref in refs[length][:count]:
            unplaced_counter[ref] += 1
    return bars, sorted(unplaced_counter.items()), remaining


# -- Local improvement ------------------------------------------------------


def _eliminate_bars(bars: list[CutBar], remaining: dict, settings: LinearSettings, deadline: float) -> None:
    """Empty the least-filled purchased bars into the others' slack where every cut fits."""
    kerf, trim = settings.kerf, settings.trim
    loads = [consumed_length([c[1] for c in b.cuts], kerf, trim) for b in bars]
    changed = True
    while changed and len(bars) > 1 and time.monotonic() < deadline:
        changed = False
        total_slack = sum(b.stock_length - ld for b, ld in zip(bars, loads, strict=True))
        order = sorted(range(len(bars)), key=lambda i: (bars[i].piece_length / bars[i].stock_length, i))
        for victim_idx in order[:60]:
            if time.monotonic() >= deadline:
                break
            victim = bars[victim_idx]
            if victim.is_offcut:
                continue  # emptying a free inventory offcut saves nothing
            own_slack = victim.stock_length - loads[victim_idx]
            if victim.piece_length + kerf * len(victim.cuts) > total_slack - own_slack:
                continue
            trial = list(loads)
            moves: list[tuple[int, tuple[str, int]]] = []
            for cut in sorted(victim.cuts, key=lambda c: -c[1]):
                target = None
                best_slack = None
                for i, bar in enumerate(bars):
                    if i == victim_idx:
                        continue
                    slack = bar.stock_length - (trial[i] + kerf + cut[1] if bar.cuts else trim + cut[1])
                    if slack >= 0 and (best_slack is None or slack < best_slack):
                        target, best_slack = i, slack
                if target is None:
                    break
                trial[target] = bars[target].stock_length - best_slack
                moves.append((target, cut))
            if len(moves) == len(victim.cuts):
                for target, cut in moves:
                    bars[target].cuts.append(cut)
                if remaining.get(victim.stock_ref) is not None:
                    remaining[victim.stock_ref] += 1
                del bars[victim_idx]
                del trial[victim_idx]
                loads = trial
                changed = True
                break
    for bar in bars:
        bar.cuts.sort(key=lambda c: (-c[1], c[0]))


def _downsize(bars: list[CutBar], stocks: list[LinearStock], remaining: dict, settings: LinearSettings) -> None:
    """Move each purchased bar to the cheapest (then shortest) available stock its cuts still fit."""
    priced = _priced(stocks)
    by_ref = {s.ref: s for s in stocks}
    for bar in bars:
        if bar.is_offcut:
            continue
        lengths = [c[1] for c in bar.cuts]
        current = by_ref[bar.stock_ref]
        best = current
        for stock in stocks:
            if stock.is_offcut or stock.ref == current.ref:
                continue
            if remaining.get(stock.ref) is not None and remaining[stock.ref] <= 0:
                continue
            if not fits(lengths, stock.length, settings.kerf, settings.trim):
                continue
            better = (stock.cost, stock.length) < (best.cost, best.length) if priced else stock.length < best.length
            if better:
                best = stock
        if best is not current:
            if remaining.get(best.ref) is not None:
                remaining[best.ref] -= 1
            if remaining.get(current.ref) is not None:
                remaining[current.ref] += 1
            bar.stock_ref, bar.stock_length, bar.cost = best.ref, best.length, best.cost


# -- Exact search -----------------------------------------------------------


def _exact(
    lengths: list[int],
    capacity: int,
    upper: int,
    settings: LinearSettings,
    deadline: float,
) -> tuple[list[list[int]] | None, bool]:
    """Branch and bound on bar count for one stock length. Returns (bins or None, proven)."""
    kerf, trim = settings.kerf, settings.trim
    lengths = sorted(lengths, reverse=True)
    total = sum(ln + kerf for ln in lengths)
    lower = max(1, -(-total // (capacity - trim + kerf)))
    best: list[list[int]] | None = None
    best_count = upper
    nodes = 0
    aborted = False
    bins: list[list[int]] = []
    loads: list[int] = []

    def search(i: int) -> None:
        nonlocal best, best_count, nodes, aborted
        if aborted:
            return
        nodes += 1
        if nodes > settings.node_budget or (nodes & 1023 == 0 and time.monotonic() > deadline):
            aborted = True
            return
        if len(bins) >= best_count:
            return
        if i == len(lengths):
            best = [list(b) for b in bins]
            best_count = len(bins)
            return
        length = lengths[i]
        tried: set[int] = set()
        for b in range(len(bins)):
            load = loads[b]
            if load in tried:
                continue
            tried.add(load)
            if load + kerf + length <= capacity:
                bins[b].append(length)
                loads[b] = load + kerf + length
                search(i + 1)
                bins[b].pop()
                loads[b] = load
                if best_count <= lower:
                    return
        if len(bins) + 1 < best_count:
            bins.append([length])
            loads.append(trim + length)
            search(i + 1)
            bins.pop()
            loads.pop()

    search(0)
    return best, (not aborted) or best_count <= lower


# -- Entry point ------------------------------------------------------------


def optimise_linear(
    pieces: list[LinearPiece],
    stocks: list[LinearStock],
    settings: LinearSettings | None = None,
) -> LinearResult:
    """Produce a cutting plan for linear stock.

    Pieces longer than every stock are reported in ``unplaced`` rather than
    raising, so the caller can show them next to the validation finding.
    """
    settings = settings or LinearSettings()
    started = time.monotonic()
    deadline = started + max(0.05, settings.time_limit_s)
    pieces = [p for p in pieces if p.quantity > 0 and p.length > 0]
    stocks = sorted((s for s in stocks if s.length > 0), key=lambda s: (not s.is_offcut, s.length, s.ref))
    bars, unplaced, remaining = _greedy(pieces, stocks, settings, deadline)
    _eliminate_bars(bars, remaining, settings, deadline)
    _downsize(bars, stocks, remaining, settings)

    exact = proven = False
    purchasable = [s for s in stocks if not s.is_offcut]
    total_pieces = sum(len(b.cuts) for b in bars)
    if (
        not unplaced
        and len(purchasable) == 1
        and len(purchasable) == len(stocks)
        and purchasable[0].available is None
        and 0 < total_pieces <= settings.exact_max_pieces
    ):
        stock = purchasable[0]
        cuts = sorted((c for b in bars for c in b.cuts), key=lambda c: (-c[1], c[0]))
        found, proven = _exact([c[1] for c in cuts], stock.length, len(bars), settings, deadline)
        exact = True
        if found is not None and len(found) < len(bars):
            pool: dict[int, list[str]] = {}
            for ref, length in cuts:
                pool.setdefault(length, []).append(ref)
            bars = []
            for lengths in found:
                bar = CutBar(stock.ref, stock.length, stock.cost, False)
                bar.cuts = [(pool[ln].pop(0), ln) for ln in sorted(lengths, reverse=True)]
                bars.append(bar)
    bars.sort(key=lambda b: (not b.is_offcut, b.stock_ref, -b.piece_length))
    elapsed = int((time.monotonic() - started) * 1000)
    return LinearResult(bars=bars, unplaced=unplaced, exact=exact, proven_optimal=proven, elapsed_ms=elapsed)


__all__ = [
    "CutBar",
    "LinearPiece",
    "LinearResult",
    "LinearSettings",
    "LinearStock",
    "consumed_length",
    "fits",
    "optimise_linear",
    "remnant",
    "reusable_offcut",
    "scrap",
]
