# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Stockpile arithmetic (no database, no I/O).

The pile volume is the cut of the pile surface against its base, computed by the
surfaces_volumes engine; this module only turns it into tonnes and a variance.
All results are Decimal so a course number such as 8,087.04 t is exact.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.modules.surfaces_volumes import volumes as vol
from app.modules.surfaces_volumes.tin import Tin

DENSITY_SOURCES = ("measured", "supplier", "assumed")
#: Default variance tolerance in percent when nothing sets one (UNSOURCED, advisory).
DEFAULT_TOLERANCE_PCT = Decimal(3)

_M3 = Decimal("0.001")
_T = Decimal("0.01")
_PCT = Decimal("0.01")


def dec(value: float | int | str | Decimal) -> Decimal:
    """Decimal from a float without binary noise."""
    return value if isinstance(value, Decimal) else Decimal(repr(value)) if isinstance(value, float) else Decimal(value)


def pile_volume(pile: Tin, base: Tin, cell: float | None = None) -> vol.VolumeResult:
    """Material above the base surface: the cut of ``pile`` against ``base``."""
    return vol.compute(pile, base, vol.GRID, cell)


def tonnes(volume_m3: Decimal | float, density_t_m3: Decimal | float) -> Decimal:
    """``V * rho`` in tonnes, to 0.01 t."""
    return (dec(volume_m3).quantize(_M3, ROUND_HALF_UP) * dec(density_t_m3)).quantize(_T, ROUND_HALF_UP)


@dataclass(frozen=True)
class Variance:
    """Survey against book: tonnes and percent of the book; negative means less on the ground."""

    delta_t: Decimal
    pct: Decimal | None


def variance(survey_t: Decimal | float, book_t: Decimal | float | None) -> Variance | None:
    """``survey - book`` and its percent of the book; None when there is no book stock."""
    if book_t is None:
        return None
    book = dec(book_t)
    delta = (dec(survey_t) - book).quantize(_T, ROUND_HALF_UP)
    pct = (delta / book * 100).quantize(_PCT, ROUND_HALF_UP) if book != 0 else None
    return Variance(delta, pct)
