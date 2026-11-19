# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Staged volumes: a chain of surfaces over time, cut and fill per stage.

A stage is a surveyed surface, or a strip of the stage before it by a depth
(topsoil strip of d metres). Each step compares one stage with the next by the
same method as a single volume, so the steps add up to first-to-last.

Bank, loose and compacted volumes use factors from a per-material table the
user enters. Core ships no factor: a material without one shows bank volume
only and SRV-082 says so.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.surfaces_volumes import volumes as vol
from app.modules.surfaces_volumes.tin import Tin


@dataclass
class Factors:
    """Bank to loose (swell, > 1) and bank to compacted (< 1, or > 1 for rock), per material."""

    loose: float | None = None
    compacted: float | None = None


@dataclass
class StepResult:
    """Cut and fill from one stage to the next."""

    index: int
    from_label: str
    to_label: str
    material: str
    cut: float
    fill: float
    coverage_pct: float
    cut_loose: float | None
    fill_bank_needed: float | None

    @property
    def net(self) -> float:
        return self.cut - self.fill


def strip(tin: Tin, depth: float) -> Tin:
    """The same surface lowered by ``depth`` metres (topsoil strip)."""
    return Tin(tin.e, tin.n, tin.z - depth, tin.tri, tin.origin)


def staged_volumes(
    stages: list[tuple[str, Tin]],
    materials: list[str],
    factors: dict[str, Factors],
    method: str = vol.GRID,
    cell: float | None = None,
    boundary: vol.Ring | None = None,
) -> list[StepResult]:
    """Cut and fill for each consecutive pair of ``stages``.

    ``materials[i]`` is what moves in step i (stage i to i+1). Cut becomes loose
    volume with the material's loose factor; fill is converted back to the bank
    volume it needs with the compacted factor.
    """
    if len(stages) < 2:
        raise ValueError("A staged volume needs at least two stages")
    out: list[StepResult] = []
    for i in range(len(stages) - 1):
        (a_label, a), (b_label, b) = stages[i], stages[i + 1]
        r = vol.compute(a, b, method, cell, boundary)
        material = materials[i] if i < len(materials) else ""
        f = factors.get(material) if material else None
        out.append(
            StepResult(
                index=i + 1,
                from_label=a_label,
                to_label=b_label,
                material=material,
                cut=r.cut,
                fill=r.fill,
                coverage_pct=r.coverage_pct,
                cut_loose=r.cut * f.loose if f and f.loose else None,
                fill_bank_needed=r.fill / f.compacted if f and f.compacted else None,
            )
        )
    return out


__all__ = ["Factors", "StepResult", "staged_volumes", "strip"]
