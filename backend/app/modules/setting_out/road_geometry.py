# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Vertical profile and the road/rail stake list (no database).

A profile is a list of PVIs (chainage, level, vertical curve length). Between
PVIs the level runs on straight grades; around a PVI with a curve length ``L``
it follows the symmetric parabola

    y(x) = y_BVC + g1 * x + (g2 - g1) / (2 L) * x^2,    x = ch - (ch_PVI - L/2)

The stake list walks the horizontal alignment every ``N`` metres, gives E/N
of the centreline and each offset, the design level (crossfall applied to
offsets) and, where a measured level is given, ``dz = measured - design``.

``dz > 0`` means the ground stands above the design. In ``stake`` mode that is
cut (dig down to grade); in ``as_built`` mode it is fill placed above grade
(the as-built check of a finished layer).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from app.modules.setting_out.stakeout_math import Alignment, AlignmentError

STAKE = "stake"
AS_BUILT = "as_built"


class ProfileError(ValueError):
    """The profile cannot give a level at this chainage (SRV-070)."""


@dataclass(frozen=True)
class Pvi:
    chainage: float
    level: float
    curve_length: float = 0.0


@dataclass(frozen=True)
class VerticalCurve:
    pvi: Pvi
    g1: float
    g2: float

    @property
    def bvc(self) -> float:
        return self.pvi.chainage - self.pvi.curve_length / 2.0

    @property
    def evc(self) -> float:
        return self.pvi.chainage + self.pvi.curve_length / 2.0

    @property
    def bvc_level(self) -> float:
        return self.pvi.level - self.g1 * self.pvi.curve_length / 2.0

    def level_at(self, ch: float) -> float:
        x = ch - self.bvc
        length = self.pvi.curve_length
        return self.bvc_level + self.g1 * x + (self.g2 - self.g1) / (2.0 * length) * x * x

    def turning_point(self) -> tuple[float, float] | None:
        """High or low point inside the curve: ``x = -g1 * L / (g2 - g1)``."""
        if self.g1 == self.g2:
            return None
        x = -self.g1 * self.pvi.curve_length / (self.g2 - self.g1)
        if not 0.0 <= x <= self.pvi.curve_length:
            return None
        return self.bvc + x, self.level_at(self.bvc + x)


@dataclass(frozen=True)
class VerticalProfile:
    pvis: tuple[Pvi, ...]
    name: str = ""

    def __post_init__(self) -> None:
        if len(self.pvis) < 2:
            raise ProfileError("A profile needs at least two PVIs")
        chs = [p.chainage for p in self.pvis]
        if any(b <= a for a, b in zip(chs, chs[1:], strict=False)):
            raise ProfileError("PVI chainages must increase")

    @property
    def start(self) -> float:
        return self.pvis[0].chainage

    @property
    def end(self) -> float:
        return self.pvis[-1].chainage

    def grade(self, i: int) -> float:
        """Grade (rise/run) from PVI ``i`` to PVI ``i + 1``."""
        a, b = self.pvis[i], self.pvis[i + 1]
        return (b.level - a.level) / (b.chainage - a.chainage)

    def curves(self) -> list[VerticalCurve]:
        return [
            VerticalCurve(self.pvis[i], self.grade(i - 1), self.grade(i))
            for i in range(1, len(self.pvis) - 1)
            if self.pvis[i].curve_length > 0
        ]

    def level_at(self, ch: float) -> float:
        """Design level at chainage ``ch``.

        Raises:
            ProfileError: when ``ch`` lies outside the profile.
        """
        tol = 1e-6
        if ch < self.start - tol or ch > self.end + tol:
            raise ProfileError(f"Profile does not cover chainage {ch:.3f}")
        for curve in self.curves():
            if curve.bvc - tol <= ch <= curve.evc + tol:
                return curve.level_at(ch)
        for i in range(len(self.pvis) - 1):
            a, b = self.pvis[i], self.pvis[i + 1]
            if ch <= b.chainage + tol:
                return a.level + self.grade(i) * (ch - a.chainage)
        return self.pvis[-1].level  # pragma: no cover


@dataclass
class StakeRow:
    chainage: float
    offset: float
    e: float
    n: float
    design_z: float | None
    measured_z: float | None = None
    dz_mm: float | None = None
    #: ``cut`` | ``fill`` | ``on_grade`` | "" (no measurement)
    cut_fill: str = ""


@dataclass
class StakeList:
    rows: list[StakeRow] = field(default_factory=list)
    #: Chainages the profile does not cover (SRV-070).
    uncovered: list[float] = field(default_factory=list)


def chainages(start: float, end: float, interval: float, extra: Iterable[float] = ()) -> list[float]:
    """Every ``interval`` metres on round multiples, plus both ends and ``extra`` (element joints)."""
    if interval <= 0:
        raise ValueError("The stake interval must be positive")
    if end < start:
        raise ValueError("The end chainage is before the start")
    out = {round(start, 6), round(end, 6)}
    ch = math.ceil(start / interval - 1e-9) * interval
    while ch < end - 1e-9:
        out.add(round(ch, 6))
        ch += interval
    out.update(round(x, 6) for x in extra if start - 1e-9 <= x <= end + 1e-9)
    return sorted(out)


def cut_fill(dz_mm: float, mode: str = STAKE, on_grade_mm: float = 0.5) -> str:
    """The word for a level difference ``measured - design`` (see the module docstring)."""
    if abs(dz_mm) < on_grade_mm:
        return "on_grade"
    above = dz_mm > 0
    if mode == AS_BUILT:
        return "fill" if above else "cut"
    return "cut" if above else "fill"


def stake_list(
    alignment: Alignment,
    profile: VerticalProfile | None,
    interval: float,
    offsets: Sequence[float] = (0.0,),
    start: float | None = None,
    end: float | None = None,
    crossfall_pct: float = 0.0,
    measured: dict[tuple[float, float], float] | None = None,
    mode: str = STAKE,
) -> StakeList:
    """Stake rows every ``interval`` m along ``alignment`` with design level and cut/fill.

    ``measured`` maps (chainage, offset), both rounded to 3 decimals, to a measured level.
    ``crossfall_pct`` falls away from the centreline on both sides (2.5 = 2.5 % down).
    """
    first = alignment.start_chainage if start is None else start
    last = alignment.start_chainage + alignment.length if end is None else end
    joints, run = [], alignment.start_chainage
    for el in alignment.elements:
        run += el.length
        joints.append(run)
    out = StakeList()
    measured = measured or {}
    for ch in chainages(first, last, interval, joints[:-1]):
        try:
            centre = profile.level_at(ch) if profile is not None else None
        except ProfileError:
            centre = None
            out.uncovered.append(ch)
        for off in offsets:
            try:
                e, n = alignment.point_at(ch, off)
            except AlignmentError:
                continue
            design = None if centre is None else centre - abs(off) * crossfall_pct / 100.0
            row = StakeRow(round(ch, 3), off, e, n, design)
            m = measured.get((round(ch, 3), round(off, 3)))
            if m is not None:
                row.measured_z = m
                if design is not None:
                    row.dz_mm = round((m - design) * 1000.0, 1)
                    row.cut_fill = cut_fill(row.dz_mm, mode)
            out.rows.append(row)
    return out


__all__ = [
    "AS_BUILT",
    "STAKE",
    "ProfileError",
    "Pvi",
    "StakeList",
    "StakeRow",
    "VerticalCurve",
    "VerticalProfile",
    "chainages",
    "cut_fill",
    "stake_list",
]
