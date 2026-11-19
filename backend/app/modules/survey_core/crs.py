# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Coordinate reference systems through pyproj/PROJ.

The network is switched off: PROJ never fetches grid files at run time, so a
transform either uses what ships with pyproj or fails loudly. Country packs
list the grids they need. National grids, heights and geoid names come from
``core/country_data/survey_reference.json`` (registered at startup, so they
work without a pack); packs may add systems through :func:`register_pack_crs`.
"""

from __future__ import annotations

import json
import os
import warnings
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

os.environ.setdefault("PROJ_NETWORK", "OFF")

from pyproj import CRS, Transformer  # noqa: E402
from pyproj.database import query_crs_info  # noqa: E402
from pyproj.enums import PJType  # noqa: E402
from pyproj.exceptions import CRSError  # noqa: E402
from pyproj.transformer import TransformerGroup  # noqa: E402

Point3 = tuple[float, float, float | None]

_SEARCH_TYPES = (PJType.PROJECTED_CRS, PJType.GEOGRAPHIC_2D_CRS, PJType.VERTICAL_CRS, PJType.COMPOUND_CRS)


@dataclass(frozen=True)
class NationalCrs:
    """One national grid as a country offers it: role, its height system and geoid model."""

    epsg: int
    note: str = ""
    role: str = "primary"  # primary | zone | legacy
    vertical_epsg: int | None = None
    geoid_grid: str | None = None
    proj_grid: str | None = None


#: Country code -> national systems: core reference data first, then whatever packs add.
_PACK_CRS: dict[str, list[NationalCrs]] = {}


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


SystemSpec = NationalCrs | tuple | dict


def _as_national(spec: SystemSpec) -> NationalCrs:
    if isinstance(spec, NationalCrs):
        return spec
    if isinstance(spec, dict):
        v = spec.get("vertical_epsg")
        return NationalCrs(
            epsg=int(spec["epsg"]),
            note=str(spec.get("note") or ""),
            role=str(spec.get("role") or "primary"),
            vertical_epsg=int(v) if v else None,
            geoid_grid=spec.get("geoid_grid") or None,
            proj_grid=spec.get("proj_grid") or None,
        )
    epsg, note, *rest = spec
    role = str(rest[0]) if rest else "primary"
    vertical = int(rest[1]) if len(rest) > 1 and rest[1] else None
    geoid = str(rest[2]) if len(rest) > 2 and rest[2] else None
    return NationalCrs(int(epsg), str(note), role, vertical, geoid)


def register_pack_crs(country: str, systems: Iterable[SystemSpec]) -> None:
    """Offer national systems in the CRS picker; a second call only adds codes not yet listed."""
    listed = _PACK_CRS.setdefault(country.strip().upper(), [])
    known = {s.epsg for s in listed}
    for spec in systems:
        item = _as_national(spec)
        if item.epsg not in known:
            listed.append(item)
            known.add(item.epsg)


def national_crs_for(markets: Iterable[str]) -> list[tuple[NationalCrs, str]]:
    """``(system, country)`` for the caller's markets only; no market chosen lists nothing."""
    wanted = {m.strip().upper() for m in markets}
    if "*" in wanted:
        return []
    return [(s, c) for c, systems in sorted(_PACK_CRS.items()) if c in wanted for s in systems]


def pack_crs_for(markets: Iterable[str]) -> list[tuple[int, str, str]]:
    """``(epsg, note, country)`` from the packs of the caller's markets only."""
    return [(s.epsg, s.note, c) for s, c in national_crs_for(markets)]


# ── National reference data (core, works without a pack) ──────────────────────────────────────────────────────────

REFERENCE_PATH = Path(__file__).resolve().parents[2] / "core" / "country_data" / "survey_reference.json"


@lru_cache(maxsize=1)
def survey_reference() -> dict[str, dict[str, Any]]:
    """``country -> entry`` from ``country_data/survey_reference.json``."""
    data = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    return {str(k).upper(): v for k, v in (data.get("countries") or {}).items()}


def load_survey_reference() -> int:
    """Register every country's national systems from the core reference; returns how many systems."""
    count = 0
    for country, entry in survey_reference().items():
        vertical = [int(v["epsg"]) for v in entry.get("vertical") or []]
        geoid = entry.get("geoid") or {}
        systems = [
            NationalCrs(
                epsg=int(h["epsg"]),
                note=str(h.get("note") or ""),
                role=str(h.get("role") or "primary"),
                vertical_epsg=vertical[0] if vertical else None,
                geoid_grid=geoid.get("name") or None,
                proj_grid=geoid.get("proj_grid") or None,
            )
            for h in entry.get("horizontal") or []
        ]
        register_pack_crs(country, systems)
        count += len(systems)
    return count


def legacy_note(epsg: int | None, markets: Iterable[str] | None = None) -> tuple[str, int] | None:
    """``(country, primary epsg)`` when ``epsg`` is a legacy grid there (SRV-021); markets narrow the search."""
    if epsg is None:
        return None
    wanted = None if markets is None else {m.strip().upper() for m in markets} - {"*"}
    for country, systems in sorted(_PACK_CRS.items()):
        if wanted and country not in wanted:
            continue
        if not any(s.epsg == int(epsg) and s.role == "legacy" for s in systems):
            continue
        primary = next((s.epsg for s in systems if s.role == "primary"), None)
        if primary is not None:
            return country, primary
    return None


def geoid_name_for(vertical_epsg: int | None) -> str | None:
    """The geoid model a country pairs with this height system, from the reference."""
    if not vertical_epsg:
        return None
    for entry in survey_reference().values():
        if any(int(v["epsg"]) == int(vertical_epsg) for v in entry.get("vertical") or []):
            geoid = entry.get("geoid") or {}
            if geoid.get("name"):
                return str(geoid["name"])
    return None


# ── Heights ───────────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class VerticalStatus:
    """Whether heights between two systems can be converted with what is installed."""

    needed: bool
    available: bool
    missing_grids: tuple[str, ...] = ()


def _compound(h: int, v: int | None) -> CRS:
    base = CRS.from_epsg(int(h))
    if v is None:
        return base.to_3d() if base.is_geographic else base
    return CRS.from_user_input(f"EPSG:{int(h)}+{int(v)}")


@lru_cache(maxsize=256)
def vertical_status(source_h: int, source_v: int | None, target_h: int, target_v: int | None) -> VerticalStatus:
    """Can heights go from ``source_h+source_v`` to ``target_h+target_v`` offline?

    ``None`` as a vertical code means ellipsoidal heights when the horizontal
    system is geographic, and "carry as measured" for a projected one.
    """
    if source_v == target_v:
        return VerticalStatus(needed=False, available=True)
    try:
        src, dst = _compound(source_h, source_v), _compound(target_h, target_v)
        if len(src.axis_info) < 3 or len(dst.axis_info) < 3:
            return VerticalStatus(needed=False, available=True)
        with warnings.catch_warnings():
            # The missing grid is reported to the person as SRV-020, not to the log.
            warnings.simplefilter("ignore", UserWarning)
            group = TransformerGroup(src, dst, always_xy=True)
    except (CRSError, ValueError) as exc:
        raise ValueError(f"no height transform from {source_h}+{source_v} to {target_h}+{target_v}") from exc
    missing = sorted(
        {
            grid.short_name or grid.full_name or grid.name
            for op in group.unavailable_operations
            for grid in getattr(op, "grids", [])
            if not grid.available
        }
    )
    usable = bool(group.transformers) and (group.best_available or not missing)
    return VerticalStatus(needed=True, available=usable, missing_grids=tuple(missing))


@dataclass
class Transform3dResult:
    """Moved points, whether heights were converted, and which grids were missing."""

    points: list[Point3]
    heights_converted: bool
    missing_grids: tuple[str, ...] = ()


def transform_points_3d(
    points: Sequence[Point3],
    source_epsg: int,
    target_epsg: int,
    source_vertical: int | None = None,
    target_vertical: int | None = None,
) -> Transform3dResult:
    """E/N/H through a compound CRS when both heights are named and the geoid grid is installed.

    Without the grid the plan position is still transformed and heights are
    kept as measured; the caller reports SRV-020.
    """
    status = vertical_status(int(source_epsg), source_vertical, int(target_epsg), target_vertical)
    if not status.needed or not status.available:
        moved = transform_points(points, source_epsg, target_epsg)
        return Transform3dResult(moved, False, status.missing_grids)
    tr = Transformer.from_crs(
        _compound(source_epsg, source_vertical), _compound(target_epsg, target_vertical), always_xy=True
    )
    out: list[Point3] = []
    for x, y, z in points:
        if z is None:
            tx, ty = transform_points([(x, y, None)], source_epsg, target_epsg)[0][:2]
            out.append((tx, ty, None))
            continue
        tx, ty, tz = tr.transform(x, y, z)
        if float("inf") in (tx, ty, tz):
            raise ValueError(f"point ({x}, {y}) is outside EPSG {target_epsg}")
        out.append((float(tx), float(ty), float(tz)))
    return Transform3dResult(out, True, ())


__all__ = [
    "CrsInfo",
    "NationalCrs",
    "Transform3dResult",
    "VerticalStatus",
    "describe",
    "geoid_name_for",
    "legacy_note",
    "load_survey_reference",
    "national_crs_for",
    "pack_crs_for",
    "register_pack_crs",
    "survey_reference",
    "transform_points_3d",
    "vertical_status",
    "search",
    "transform_points",
    "utm_epsg_for",
]


def wgs84_projector(epsg: int | None) -> Callable[[Sequence[float], Sequence[float]], list[tuple[float, float]]]:
    """``f(e_values, n_values) -> [(lon, lat), ...]`` for map display.

    A local grid (``None``) and WGS 84 pass through unchanged: a local plan is
    drawn in its own metres, never pinned to a place it is not.
    """
    if epsg is None or int(epsg) == 4326:
        return lambda e, n: [(round(float(a), 8), round(float(b), 8)) for a, b in zip(e, n, strict=True)]
    tr = Transformer.from_crs(int(epsg), 4326, always_xy=True)

    def run(e: Sequence[float], n: Sequence[float]) -> list[tuple[float, float]]:
        lon, lat = tr.transform(list(map(float, e)), list(map(float, n)))
        return [(round(float(a), 8), round(float(b), 8)) for a, b in zip(lon, lat, strict=True)]

    return run
