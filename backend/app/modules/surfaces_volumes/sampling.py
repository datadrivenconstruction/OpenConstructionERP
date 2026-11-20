# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Heights of a surface along a polyline: the rows a long or cross section is drawn from.

Chainages run from 0 at the first vertex, every ``interval`` metres, plus every
vertex and the end. Offsets are perpendicular to the leg at that chainage,
positive to the right of the direction of travel.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from app.modules.surfaces_volumes.tin import Tin

#: A section request never asks for more rows than this.
MAX_ROWS = 50_000


@dataclass(frozen=True)
class SampleRow:
    ch: float
    offset: float
    e: float
    n: float
    z: float | None


def stations(polyline: list[tuple[float, float]], interval: float) -> list[tuple[float, float, float, float, float]]:
    """``(chainage, e, n, unit_dx, unit_dy)`` at every interval, every vertex and the end."""
    pts = [(float(e), float(n)) for e, n in polyline]
    if len(pts) < 2:
        return []
    out: list[tuple[float, float, float, float, float]] = []
    ch0 = 0.0
    for i in range(len(pts) - 1):
        (e1, n1), (e2, n2) = pts[i], pts[i + 1]
        length = math.hypot(e2 - e1, n2 - n1)
        if length < 1e-9:
            continue
        ux, uy = (e2 - e1) / length, (n2 - n1) / length
        chs = [ch0]
        if interval > 0:
            k = math.floor(ch0 / interval) + 1
            while k * interval < ch0 + length - 1e-9:
                chs.append(k * interval)
                k += 1
        for ch in chs:
            if out and abs(out[-1][0] - ch) < 1e-9:
                continue
            d = ch - ch0
            out.append((round(ch, 6), e1 + ux * d, n1 + uy * d, ux, uy))
        ch0 += length
    last_e, last_n = pts[-1]
    ux, uy = (out[-1][3], out[-1][4]) if out else (1.0, 0.0)
    if not out or abs(out[-1][0] - ch0) > 1e-9:
        out.append((round(ch0, 6), last_e, last_n, ux, uy))
    return out


def sample_polyline(
    tin: Tin, polyline: list[tuple[float, float]], interval: float, offsets: list[float] | None = None
) -> list[SampleRow]:
    """One row per station and offset; ``z`` is ``None`` off the surface."""
    offs = [0.0] if not offsets else [float(o) for o in offsets]
    st = stations(polyline, interval)
    if len(st) * len(offs) > MAX_ROWS:
        raise ValueError(f"{len(st) * len(offs)} rows is more than {MAX_ROWS}: use a longer interval")
    es, ns, meta = [], [], []
    for ch, e, n, ux, uy in st:
        for o in offs:
            # Right of travel is (uy, -ux).
            es.append(e + uy * o)
            ns.append(n - ux * o)
            meta.append((ch, o))
    z = tin.sample(np.array(es), np.array(ns)) if es else np.zeros(0)
    return [
        SampleRow(
            ch=ch,
            offset=o,
            e=round(float(e), 4),
            n=round(float(n), 4),
            z=None if not math.isfinite(float(h)) else round(float(h), 4),
        )
        for (ch, o), e, n, h in zip(meta, es, ns, z, strict=True)
    ]


__all__ = ["MAX_ROWS", "SampleRow", "sample_polyline", "stations"]
