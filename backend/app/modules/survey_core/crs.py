# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Coordinate reference systems through pyproj/PROJ.

The network is switched off: PROJ never fetches grid files at run time, so a
transform either uses what ships with pyproj or fails loudly. Country packs
list the grids they need. Packs also contribute CRS suggestions through
:func:`register_pack_crs`; core holds no national system.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache

os.environ.setdefault("PROJ_NETWORK", "OFF")

from pyproj import CRS, Transformer  # noqa: E402
from pyproj.database import query_crs_info  # noqa: E402
from pyproj.enums import PJType  # noqa: E402
from pyproj.exceptions import CRSError  # noqa: E402

Point3 = tuple[float, float, float | None]

_SEARCH_TYPES = (PJType.PROJECTED_CRS, PJType.GEOGRAPHIC_2D_CRS, PJType.VERTICAL_CRS, PJType.COMPOUND_CRS)

#: Country code -> [(epsg, note)] registered by active country packs.
_PACK_CRS: dict[str, list[tuple[int, str]]] = {}


@dataclass(frozen=True)
class CrsInfo:
    """What a person needs to know about one EPSG system."""

    epsg: int
    name: str
    kind: str  # projected | geographic | vertical | compound | other
    unit: str
    is_geographic: bool
    area: str


def _kind(crs: CRS) -> str:
    if crs.is_compound:
        return "compound"
    if crs.is_projected:
        return "projected"
    if crs.is_geographic:
        return "geographic"
    if crs.is_vertical:
        return "vertical"
    return "other"


@lru_cache(maxsize=512)
def describe(epsg: int) -> CrsInfo:
    """Name, kind and unit of an EPSG code.

    Raises:
        ValueError: when the code is not in the EPSG registry.
    """
    try:
        crs = CRS.from_epsg(int(epsg))
    except (CRSError, TypeError, ValueError) as exc:
        raise ValueError(f"EPSG {epsg} is not a known coordinate system") from exc
    axis = crs.axis_info[0] if crs.axis_info else None
    area = crs.area_of_use.name if crs.area_of_use else ""
    return CrsInfo(
        epsg=int(epsg),
        name=crs.name,
        kind=_kind(crs),
        unit=(axis.unit_name if axis else "") or "",
        is_geographic=bool(crs.is_geographic),
        area=area,
    )


@lru_cache(maxsize=1)
def _catalogue() -> tuple[tuple[int, str, str], ...]:
    rows = query_crs_info(auth_name="EPSG", pj_types=list(_SEARCH_TYPES), allow_deprecated=False)
    return tuple((int(r.code), r.name, r.type.name) for r in rows if r.code.isdigit())


def search(query: str, limit: int = 20) -> list[CrsInfo]:
    """EPSG systems matching a typed code or name; exact code first.

    Only matches what the person typed: nothing is suggested from an empty or
    one-character query.
    """
    q = (query or "").strip()
    if q.upper().startswith("EPSG"):
        q = q[4:].lstrip(": ").strip()
    if len(q) < 2:
        return []
    hits: list[int] = []
    if q.isdigit():
        exact = [c for c, _, _ in _catalogue() if str(c) == q]
        prefix = [c for c, _, _ in _catalogue() if str(c).startswith(q) and str(c) != q]
        hits = exact + sorted(prefix)
    else:
        words = q.casefold().split()
        found = [(c, name) for c, name, _ in _catalogue() if all(w in name.casefold() for w in words)]
        # Exact name, then the global WGS 84 family, then shorter names: the system most people mean comes first.
        found.sort(key=lambda r: (r[1].casefold() != q.casefold(), not r[1].startswith("WGS 84"), len(r[1]), r[0]))
        hits = [c for c, _ in found]
    out: list[CrsInfo] = []
    for code in hits[: limit * 2]:
        try:
            out.append(describe(code))
        except ValueError:
            continue
        if len(out) >= limit:
            break
    return out


def utm_epsg_for(lat: float, lon: float) -> int | None:
    """WGS 84 UTM zone code for a pin (326zz north, 327zz south); ``None`` outside UTM latitudes."""
    if not (-80.0 <= lat <= 84.0) or not (-180.0 <= lon <= 180.0):
        return None
    zone = min(int((lon + 180.0) // 6) + 1, 60)
    return (32600 if lat >= 0 else 32700) + zone


def transform_points(points: Sequence[Point3], source_epsg: int, target_epsg: int) -> list[Point3]:
    """Transform E/N/Z (or lon/lat/h) from one EPSG system to another.

    Heights are carried through unchanged unless both systems have a vertical
    component; there is no silent geoid step.

    Raises:
        ValueError: on an unknown code or a transform PROJ cannot build offline.
    """
    if int(source_epsg) == int(target_epsg):
        return list(points)
    describe(source_epsg)
    describe(target_epsg)
    try:
        tr = Transformer.from_crs(int(source_epsg), int(target_epsg), always_xy=True)
    except CRSError as exc:
        raise ValueError(f"no transform from EPSG {source_epsg} to EPSG {target_epsg}") from exc
    out: list[Point3] = []
    for x, y, z in points:
        tx, ty = tr.transform(x, y)
        if tx == float("inf") or ty == float("inf"):
            raise ValueError(f"point ({x}, {y}) is outside EPSG {target_epsg}")
        out.append((float(tx), float(ty), z))
    return out


def register_pack_crs(country: str, systems: Iterable[tuple[int, str]]) -> None:
    """Called by a country pack to offer its national systems in the CRS picker."""
    _PACK_CRS[country.strip().upper()] = [(int(e), str(note)) for e, note in systems]


def pack_crs_for(markets: Iterable[str]) -> list[tuple[int, str, str]]:
    """``(epsg, note, country)`` from the packs of the caller's markets only."""
    wanted = {m.strip().upper() for m in markets}
    if "*" in wanted:
        return []
    return [(e, note, c) for c, systems in sorted(_PACK_CRS.items()) if c in wanted for e, note in systems]


__all__ = [
    "CrsInfo",
    "describe",
    "pack_crs_for",
    "register_pack_crs",
    "search",
    "transform_points",
    "utm_epsg_for",
]
