# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Horizontal alignment designed by intersection points (IPs), no database.

An alignment is drawn as a polyline of IPs. At every inner IP with a radius the
two tangents are joined by a circular arc:

    deflection D (signed, left positive), tangent T = R tan(|D| / 2),
    arc length L = R |D|, external E = R (sec(|D| / 2) - 1),
    TC = IP - u_in * T, CT = IP + u_out * T, centre = TC + R * normal (to the turn side).

Curves on one leg must fit: T of the curve behind plus T of the curve ahead may not exceed
the leg length (SRV-073). The minimum radius per design speed comes from the active
country pack; core ships one demo table, labelled "Demo values, not a standard" (SRV-072).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from app.modules.setting_out.design_io import alignment_to_json
from app.modules.setting_out.stakeout_math import Alignment, ArcElement, LineElement

DEMO_ROAD = Path(__file__).resolve().parent / "demo" / "riverside" / "access_road.json"

#: Design speed km/h -> minimum radius m. Course data for Riverside Yard only.
DEMO_MIN_RADIUS: Mapping[float, float] = {
    30.0: 25.0,
    40.0: 40.0,
    50.0: 60.0,
    60.0: 100.0,
    70.0: 150.0,
    80.0: 220.0,
    90.0: 300.0,
    100.0: 400.0,
    120.0: 650.0,
}
DEMO_REFERENCE = "Demo values, not a standard"

_PACK_TABLES: dict[str, tuple[dict[float, float], str]] = {}


@dataclass(frozen=True)
class Ip:
    """One intersection point; ``radius`` 0 is an angle point without a curve."""

    e: float
    n: float
    radius: float = 0.0
    name: str = ""


@dataclass(frozen=True)
class Curve:
    ref: str
    ip_index: int
    radius: float
    deflection_deg: float
    left: bool
    tangent: float
    arc_length: float
    external: float
    tc: tuple[float, float]
    ct: tuple[float, float]
    centre: tuple[float, float]
    tc_chainage: float = 0.0
    ct_chainage: float = 0.0


@dataclass(frozen=True)
class Overlap:
    """Curves ``a`` and ``b`` need ``need`` metres of a leg that is ``have`` metres long."""

    a: str
    b: str
    need: float
    have: float


@dataclass
class IpDesign:
    ips: list[Ip]
    start_chainage: float
    curves: list[Curve] = field(default_factory=list)
    overlaps: list[Overlap] = field(default_factory=list)
    alignment: Alignment | None = None

    @property
    def fits(self) -> bool:
        return not self.overlaps

    @property
    def length(self) -> float:
        return self.alignment.length if self.alignment else 0.0


@dataclass(frozen=True)
class MinRadius:
    radius_m: float
    speed_kmh: float
    #: ``demo`` | ``pack``
    source: str
    reference: str
    country: str = ""


def _ref(ips: Sequence[Ip], i: int) -> str:
    return ips[i].name or f"IP{i}"


def _unit(a: tuple[float, float], b: tuple[float, float]) -> tuple[tuple[float, float], float]:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    if length < 1e-9:
        raise ValueError("Two intersection points coincide")
    return (dx / length, dy / length), length


def design_from_ips(ips: Sequence[Ip], start_chainage: float = 0.0) -> IpDesign:
    """Tangent points, arcs and the stakeable alignment of an IP polyline.

    Curves that overlap are still reported with their geometry; the alignment is only built
    when every curve fits, so nothing is staked on a broken design.

    Raises:
        ValueError: fewer than two IPs, coincident IPs or a negative radius.
    """
    pts = list(ips)
    if len(pts) < 2:
        raise ValueError("An alignment needs at least two intersection points")
    if any(p.radius < 0 for p in pts):
        raise ValueError("A radius cannot be negative")
    xy = [(p.e, p.n) for p in pts]
    legs = [_unit(xy[i], xy[i + 1]) for i in range(len(xy) - 1)]
    out = IpDesign(pts, start_chainage)
    tangents = [0.0] * len(pts)
    raw: list[tuple[int, float, bool, float]] = []
    corners: list[int] = []
    for i in range(1, len(pts) - 1):
        (u1, _), (u2, _) = legs[i - 1], legs[i]
        cross = u1[0] * u2[1] - u1[1] * u2[0]
        dot = max(-1.0, min(1.0, u1[0] * u2[0] + u1[1] * u2[1]))
        defl = math.atan2(cross, dot)
        r = pts[i].radius
        if r <= 0 or abs(defl) < 1e-9:
            if abs(defl) >= 1e-9:
                corners.append(i)
            continue
        if abs(abs(defl) - math.pi) < 1e-6:
            raise ValueError("The alignment doubles back on itself")
        tangents[i] = r * math.tan(abs(defl) / 2.0)
        raw.append((i, defl, defl > 0, r))
    for k, (_, length) in enumerate(legs):
        need = tangents[k] + tangents[k + 1]
        if need > length + 1e-6:
            a = _ref(pts, k) if tangents[k] else _ref(pts, k + 1)
            b = _ref(pts, k + 1) if tangents[k] else a
            out.overlaps.append(Overlap(a, b, round(need, 4), round(length, 4)))

    elements: list[LineElement | ArcElement] = []
    cursor = xy[0]
    run = start_chainage
    vertices = sorted([(i, None) for i in corners] + [(c[0], c) for c in raw], key=lambda x: x[0])
    for i, spec in vertices:
        if spec is None:
            run += math.hypot(xy[i][0] - cursor[0], xy[i][1] - cursor[1])
            elements.append(LineElement(cursor, xy[i]))
            cursor = xy[i]
            continue
        _, defl, left, r = spec
        (u1, _), (u2, _) = legs[i - 1], legs[i]
        t = tangents[i]
        tc = (xy[i][0] - u1[0] * t, xy[i][1] - u1[1] * t)
        ct = (xy[i][0] + u2[0] * t, xy[i][1] + u2[1] * t)
        nx, ny = (-u1[1], u1[0]) if left else (u1[1], -u1[0])
        centre = (tc[0] + nx * r, tc[1] + ny * r)
        straight = math.hypot(tc[0] - cursor[0], tc[1] - cursor[1])
        if straight > 1e-9:
            elements.append(LineElement(cursor, tc))
        run += straight
        arc = r * abs(defl)
        out.curves.append(
            Curve(
                ref=_ref(pts, i),
                ip_index=i,
                radius=r,
                deflection_deg=math.degrees(abs(defl)),
                left=left,
                tangent=t,
                arc_length=arc,
                external=r * (1.0 / math.cos(abs(defl) / 2.0) - 1.0),
                tc=tc,
                ct=ct,
                centre=centre,
                tc_chainage=run,
                ct_chainage=run + arc,
            )
        )
        elements.append(ArcElement(tc, centre, ct, left))
        run += arc
        cursor = ct
    if math.hypot(xy[-1][0] - cursor[0], xy[-1][1] - cursor[1]) > 1e-9:
        elements.append(LineElement(cursor, xy[-1]))
    if out.fits:
        out.alignment = Alignment(tuple(elements), start_chainage)
    return out


def to_json(design: IpDesign, name: str, design_speed_kmh: float | None) -> dict:
    """The stored alignment: the stakeable elements plus the IPs they were designed from."""
    if design.alignment is None:
        raise ValueError("Curves overlap; the alignment cannot be stored")
    al = Alignment(design.alignment.elements, design.start_chainage, name)
    data = alignment_to_json(al)
    data["ips"] = [{"e": p.e, "n": p.n, "radius": p.radius, "name": p.name} for p in design.ips]
    data["design_speed_kmh"] = design_speed_kmh
    return data


def ticks(start: float, end: float, interval: float, label_every: float) -> list[tuple[float, bool]]:
    """Chainage ticks on round multiples of ``interval``; True where a label goes."""
    if interval <= 0 or label_every <= 0:
        raise ValueError("Tick intervals must be positive")
    out: list[tuple[float, bool]] = []
    ch = math.ceil(start / interval - 1e-9) * interval
    while ch <= end + 1e-9:
        q = ch / label_every
        out.append((round(ch, 6), abs(q - round(q)) < 1e-9))
        ch += interval
    return out


# ── Minimum radius per design speed ───────────────────────────────────────


def register_pack_min_radius(country: str, table: Mapping[float, float], reference: str) -> None:
    """Called by a country pack: design speed km/h -> minimum radius m, with its source."""
    if not table:
        raise ValueError("A minimum radius table cannot be empty")
    _PACK_TABLES[country.strip().upper()] = ({float(k): float(v) for k, v in table.items()}, reference)


def unregister_pack_min_radius(country: str) -> None:
    _PACK_TABLES.pop(country.strip().upper(), None)


def _lookup(table: Mapping[float, float], speed: float) -> tuple[float, float]:
    speeds = sorted(table)
    pick = next((s for s in speeds if s >= speed - 1e-9), speeds[-1])
    return table[pick], pick


def min_radius(speed_kmh: float | None, markets: Iterable[str]) -> MinRadius | None:
    """Minimum radius for ``speed_kmh``: the first active pack table, else the demo table."""
    if not speed_kmh or speed_kmh <= 0:
        return None
    from app.core.active_markets import pack_active  # noqa: PLC0415

    markets = list(markets)
    for country in sorted(_PACK_TABLES):
        if markets and pack_active(markets, [country]):
            table, reference = _PACK_TABLES[country]
            r, s = _lookup(table, speed_kmh)
            return MinRadius(r, s, "pack", reference, country)
    r, s = _lookup(DEMO_MIN_RADIUS, speed_kmh)
    return MinRadius(r, s, "demo", DEMO_REFERENCE)


def check_payload(design: IpDesign, rmin: MinRadius | None) -> dict:
    """Validation payload of the ``setting_out_road`` rule set (SRV-072, SRV-073)."""
    return {
        "curves": [
            {
                "ref": c.ref,
                "radius": c.radius,
                "min_radius": rmin.radius_m if rmin else None,
                "speed": rmin.speed_kmh if rmin else None,
            }
            for c in design.curves
        ],
        "overlaps": [
            {"ref": f"{o.a}/{o.b}", "a": o.a, "b": o.b, "need": o.need, "have": o.have} for o in design.overlaps
        ],
    }


__all__ = [
    "DEMO_MIN_RADIUS",
    "DEMO_ROAD",
    "Curve",
    "Ip",
    "IpDesign",
    "MinRadius",
    "Overlap",
    "check_payload",
    "design_from_ips",
    "min_radius",
    "register_pack_min_radius",
    "ticks",
    "to_json",
    "unregister_pack_min_radius",
]
