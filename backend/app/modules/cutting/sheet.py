# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Two-dimensional guillotine cutting optimiser for rectangular sheets.

Board, plate and glass are cut edge to edge on a panel saw or a scoring table,
so every layout produced here is guillotine by construction: each placement
splits one free rectangle into at most two, along a single straight cut.

Pure Python, integer dimensions, deterministic. Constraints:

* ``kerf`` is added to the right and top of each piece, clipped at the sheet
  edge, so two neighbouring pieces are one saw cut apart.
* ``trim`` is removed from all four sheet edges before packing.
* A piece with ``rotatable=False`` keeps its width along the sheet's x axis
  (grain direction, patterned glass, coated faces).

Strategy: pieces in decreasing area; each goes into the open sheet free
rectangle with the best area fit; when nothing fits, a new sheet is opened of
the stock type whose trial fill gives the lowest cost per placed area
(inventory offcuts first). Free rectangles at least ``min_offcut`` on both
sides are reported as reusable offcuts.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal

_ZERO = Decimal("0")


@dataclass(frozen=True)
class SheetPiece:
    """A demanded rectangle; ``width`` runs along the grain when not rotatable."""

    ref: str
    width: int
    height: int
    quantity: int = 1
    rotatable: bool = True
    label: str = ""


@dataclass(frozen=True)
class SheetStock:
    """A sheet size on offer; ``available`` of ``None`` means unlimited."""

    ref: str
    width: int
    height: int
    cost: Decimal = _ZERO
    available: int | None = None
    is_offcut: bool = False
    label: str = ""


@dataclass(frozen=True)
class SheetSettings:
    """Cutting constraints for sheet layouts."""

    kerf: int = 0
    trim: int = 0
    min_offcut: int = 0
    time_limit_s: float = 3.0


@dataclass(frozen=True)
class Rect:
    """An axis-aligned rectangle in sheet coordinates (origin bottom left)."""

    x: int
    y: int
    w: int
    h: int

    @property
    def area(self) -> int:
        """Rectangle area."""
        return self.w * self.h


@dataclass(frozen=True)
class Placement:
    """A piece placed on a sheet; ``rotated`` means width runs along y."""

    ref: str
    x: int
    y: int
    w: int
    h: int
    rotated: bool


@dataclass
class CutSheet:
    """One sheet and the pieces placed on it."""

    stock_ref: str
    width: int
    height: int
    cost: Decimal
    is_offcut: bool
    placements: list[Placement] = field(default_factory=list)
    free: list[Rect] = field(default_factory=list)
    right: int = 0
    top: int = 0

    @property
    def area(self) -> int:
        """Sheet area."""
        return self.width * self.height

    @property
    def piece_area(self) -> int:
        """Sum of the placed piece areas."""
        return sum(p.w * p.h for p in self.placements)


@dataclass
class SheetResult:
    """A complete sheet layout plan."""

    sheets: list[CutSheet]
    unplaced: list[tuple[str, int]]
    elapsed_ms: int


def _new_sheet(stock: SheetStock, settings: SheetSettings) -> CutSheet:
    t = settings.trim
    sheet = CutSheet(stock.ref, stock.width, stock.height, stock.cost, stock.is_offcut)
    sheet.right, sheet.top = stock.width - t, stock.height - t
    if stock.width - 2 * t > 0 and stock.height - 2 * t > 0:
        sheet.free = [Rect(t, t, stock.width - 2 * t, stock.height - 2 * t)]
    return sheet


def _orientations(piece: SheetPiece) -> list[tuple[int, int, bool]]:
    out = [(piece.width, piece.height, False)]
    if piece.rotatable and piece.width != piece.height:
        out.append((piece.height, piece.width, True))
    return out


def _best_fit(sheet: CutSheet, piece: SheetPiece, kerf: int) -> tuple | None:
    """Best-area-fit free rectangle for the piece: (score, index, w, h, rotated).

    A piece needs its kerf inside the free rectangle unless it ends on the
    trimmed sheet edge, where no further cut is made.
    """
    best = None
    for idx, rect in enumerate(sheet.free):
        room_w = rect.w + (kerf if rect.x + rect.w == sheet.right else 0)
        room_h = rect.h + (kerf if rect.y + rect.h == sheet.top else 0)
        for w, h, rotated in _orientations(piece):
            if w <= rect.w and h <= rect.h and w + kerf <= room_w and h + kerf <= room_h:
                key = (rect.area - w * h, min(rect.w - w, rect.h - h), idx, rotated)
                if best is None or key < best[0]:
                    best = (key, idx, w, h, rotated)
    return best


def _place(sheet: CutSheet, piece: SheetPiece, fit: tuple, kerf: int) -> None:
    """Place the piece in the chosen free rectangle and split the rest with one guillotine cut."""
    _, idx, w, h, rotated = fit
    rect = sheet.free.pop(idx)
    sheet.placements.append(Placement(piece.ref, rect.x, rect.y, w, h, rotated))
    cw = min(w + kerf, rect.w)
    ch = min(h + kerf, rect.h)
    right_w = rect.w - cw
    top_h = rect.h - ch
    # Shorter-leftover-axis rule keeps the larger remainder whole.
    if right_w < top_h:
        right = Rect(rect.x + cw, rect.y, right_w, ch)
        top = Rect(rect.x, rect.y + ch, rect.w, top_h)
    else:
        right = Rect(rect.x + cw, rect.y, right_w, rect.h)
        top = Rect(rect.x, rect.y + ch, cw, top_h)
    for part in (right, top):
        if part.w > 0 and part.h > 0:
            sheet.free.append(part)


def _priced(stocks: list[SheetStock]) -> bool:
    purchasable = [s for s in stocks if not s.is_offcut]
    return bool(purchasable) and all(s.cost > 0 for s in purchasable)


def _trial(stock: SheetStock, queue: list[SheetPiece], settings: SheetSettings, cap: int) -> int:
    """Area a fresh sheet of this stock would take from the head of the queue."""
    sheet = _new_sheet(stock, settings)
    for piece in queue[:cap]:
        fit = _best_fit(sheet, piece, settings.kerf)
        if fit is not None:
            _place(sheet, piece, fit, settings.kerf)
    return sheet.piece_area


def optimise_sheets(
    pieces: list[SheetPiece],
    stocks: list[SheetStock],
    settings: SheetSettings | None = None,
) -> SheetResult:
    """Produce guillotine sheet layouts for the demanded rectangles."""
    settings = settings or SheetSettings()
    started = time.monotonic()
    deadline = started + max(0.05, settings.time_limit_s)
    queue: list[SheetPiece] = []
    for piece in pieces:
        if piece.quantity <= 0 or piece.width <= 0 or piece.height <= 0:
            continue
        queue.extend([piece] * piece.quantity)
    queue.sort(key=lambda p: (-(p.width * p.height), -max(p.width, p.height), p.ref))
    stocks = sorted(
        (s for s in stocks if s.width > 0 and s.height > 0),
        key=lambda s: (not s.is_offcut, s.width * s.height, s.ref),
    )
    remaining = {s.ref: s.available for s in stocks}
    priced = _priced(stocks)
    sheets: list[CutSheet] = []
    unplaced: dict[str, int] = {}
    trial_cap = 400

    for i, piece in enumerate(queue):
        best = None
        for s_idx, sheet in enumerate(sheets):
            fit = _best_fit(sheet, piece, settings.kerf)
            if fit is not None and (best is None or fit[0] < best[0][0]):
                best = (fit, s_idx)
        if best is not None:
            _place(sheets[best[1]], piece, best[0], settings.kerf)
            continue
        rest = queue[i:]
        cap = trial_cap if time.monotonic() < deadline else 20
        choice = None
        for stock in stocks:
            if remaining[stock.ref] is not None and remaining[stock.ref] <= 0:
                continue
            fresh = _new_sheet(stock, settings)
            if _best_fit(fresh, piece, settings.kerf) is None:
                continue
            placed = _trial(stock, rest, settings, cap)
            if stock.is_offcut:
                key = (0, Decimal(-placed), stock.width * stock.height, stock.ref)
            elif priced:
                key = (1, stock.cost / placed, stock.width * stock.height, stock.ref)
            else:
                key = (1, Decimal(stock.width * stock.height - placed) / placed, stock.width * stock.height, stock.ref)
            if choice is None or key < choice[0]:
                choice = (key, stock)
        if choice is None:
            unplaced[piece.ref] = unplaced.get(piece.ref, 0) + 1
            continue
        stock = choice[1]
        if remaining[stock.ref] is not None:
            remaining[stock.ref] -= 1
        sheet = _new_sheet(stock, settings)
        fit = _best_fit(sheet, piece, settings.kerf)
        assert fit is not None  # checked when the stock was chosen
        _place(sheet, piece, fit, settings.kerf)
        sheets.append(sheet)

    sheets.sort(key=lambda s: (not s.is_offcut, s.stock_ref, -s.piece_area))
    elapsed = int((time.monotonic() - started) * 1000)
    return SheetResult(sheets=sheets, unplaced=sorted(unplaced.items()), elapsed_ms=elapsed)


def reusable_offcuts(sheet: CutSheet, settings: SheetSettings) -> list[Rect]:
    """Free rectangles at least ``min_offcut`` on both sides (none when the threshold is 0)."""
    m = settings.min_offcut
    if m <= 0:
        return []
    return sorted((r for r in sheet.free if r.w >= m and r.h >= m), key=lambda r: (-r.area, r.x, r.y))


def sheet_scrap(sheet: CutSheet, settings: SheetSettings) -> int:
    """Waste area: the sheet minus pieces and reusable offcuts."""
    return sheet.area - sheet.piece_area - sum(r.area for r in reusable_offcuts(sheet, settings))


__all__ = [
    "CutSheet",
    "Placement",
    "Rect",
    "SheetPiece",
    "SheetResult",
    "SheetSettings",
    "SheetStock",
    "optimise_sheets",
    "reusable_offcuts",
    "sheet_scrap",
]
