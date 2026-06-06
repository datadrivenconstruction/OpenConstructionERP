# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Quantity-derivation formulas for the AI Estimate Builder intake (v2).

Pure, deterministic functions of a confirmed parameter sheet. They are the
single source of truth for "how a parameter becomes a measurable quantity",
keyed by a stable ``qty_formula`` id that :mod:`project_types` references on
every work package. Nothing here invents a number: every result is derived
from a value the user confirmed, mirroring the ``parse_text_scope`` rule that
only reads numbers the user actually wrote.

The formulas are callable on the no-AI (offline) path exactly as on the AI
path, so the two paths produce identical quantities for identical answers.

A formula returns a :class:`QtyResult` carrying the measurement, its unit, and
an ``estimated`` flag that is True whenever the result is derived through a
geometric proxy (perimeter inferred from area, openings from default sizes, a
debris factor). The board renders estimated values as editable so the human
can overwrite the proxy with a real measurement.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# ── Geometric default proxies (all flagged ``estimated`` when used) ──────────

# Conservative room aspect ratio used to infer a perimeter from a floor area
# when the user did not give the perimeter directly. Flagged estimated so the
# UI shows a hollow confidence and invites the real value.
_DEFAULT_ROOM_ASPECT = 1.4
# Default opening areas (m2) when only counts are known.
_DEFAULT_DOOR_AREA_M2 = 1.8
_DEFAULT_WINDOW_AREA_M2 = 1.5
# Strip-out debris proxy: 50 mm equivalent depth over the stripped floor area.
_DEFAULT_DEBRIS_DEPTH_M = 0.05
# Default ceiling height (m) when the type questionnaire omits it.
_DEFAULT_CEILING_HEIGHT_M = 2.7
# Default electrical points density (points per m2 of floor area).
_DEFAULT_POINTS_DENSITY = 0.6


@dataclass(frozen=True)
class QtyResult:
    """The output of a quantity formula.

    Attributes:
        quantity: The derived measurement (never money).
        unit: The measurement unit (m2 / m / m3 / pcs / lsum).
        estimated: True when any proxy was used (perimeter from area, openings
            from default sizes, debris factor), so the UI flags it editable.
    """

    quantity: float
    unit: str
    estimated: bool


# ── Core geometric helpers (pure) ────────────────────────────────────────────


def perimeter_m(area_m2: float, aspect: float = _DEFAULT_ROOM_ASPECT) -> float:
    """Infer a room perimeter from its floor area.

    Uses ``side = sqrt(area / aspect); P = 2 * (side + aspect * side)``. The
    aspect ratio is a conservative room proxy; the caller flags the result as
    estimated so the user can type the real perimeter.

    Args:
        area_m2: Floor area in square metres.
        aspect: Length-to-width ratio proxy (default 1.4).

    Returns:
        The inferred perimeter in metres (0.0 for a non-positive area).
    """
    if area_m2 <= 0 or aspect <= 0:
        return 0.0
    side = math.sqrt(area_m2 / aspect)
    return 2.0 * (side + aspect * side)


def gross_wall_area_m2(perimeter: float, height_m: float) -> float:
    """Gross wall area for a closed room: perimeter times height."""
    if perimeter <= 0 or height_m <= 0:
        return 0.0
    return perimeter * height_m


def net_wall_area_m2(gross: float, openings_m2: float) -> float:
    """Net wall area = gross less openings, clamped at zero."""
    return max(gross - openings_m2, 0.0)


def openings_area_m2(doors: float = 0.0, windows: float = 0.0) -> float:
    """Total opening area from door / window counts using default sizes.

    Only contributes when a count is known; never invents an opening.
    """
    return max(doors, 0.0) * _DEFAULT_DOOR_AREA_M2 + max(windows, 0.0) * _DEFAULT_WINDOW_AREA_M2


def slope_area_m2(plan_area_m2: float, pitch_deg: float) -> float:
    """Convert a plan (roof footprint) area to slope area for a given pitch.

    ``slope = plan / cos(pitch)``. A flat (0 deg) roof returns the plan area.
    """
    if plan_area_m2 <= 0:
        return 0.0
    pitch = max(min(pitch_deg, 89.0), 0.0)
    return plan_area_m2 / math.cos(math.radians(pitch))


def debris_volume_m3(demo_area_m2: float, depth_m: float = _DEFAULT_DEBRIS_DEPTH_M) -> float:
    """Strip-out debris volume proxy: stripped area times an equivalent depth."""
    if demo_area_m2 <= 0:
        return 0.0
    return demo_area_m2 * depth_m


# ── Parameter-sheet readers (tolerant of missing / junk values) ──────────────


def _num(params: dict[str, Any], key: str, default: float = 0.0) -> float:
    """Read a numeric parameter, returning ``default`` for missing / junk."""
    value = params.get(key)
    if value is None:
        return default
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _has(params: dict[str, Any], key: str) -> bool:
    """True when the user supplied a usable numeric value for ``key``."""
    value = params.get(key)
    if value is None:
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _ceiling_height(params: dict[str, Any]) -> float:
    """Resolve the ceiling height, defaulting to the conservative proxy."""
    height = _num(params, "ceiling_height_m", 0.0)
    return height if height > 0 else _DEFAULT_CEILING_HEIGHT_M


def _resolved_perimeter(params: dict[str, Any]) -> tuple[float, bool]:
    """Return (perimeter_m, estimated). Confirmed value wins over the proxy."""
    if _has(params, "perimeter_m") and _num(params, "perimeter_m") > 0:
        return _num(params, "perimeter_m"), False
    area = _num(params, "floor_area_m2")
    return perimeter_m(area), True


def _net_wall(params: dict[str, Any], *, share: float = 1.0) -> tuple[float, bool]:
    """Net wall area (optionally a wet-zone share), with the estimated flag.

    Estimated whenever the perimeter was inferred from the floor area (no real
    perimeter given) or openings were derived from counts via default sizes.
    """
    perim, perim_estimated = _resolved_perimeter(params)
    height = _ceiling_height(params)
    height_estimated = not _has(params, "ceiling_height_m") or _num(params, "ceiling_height_m") <= 0
    gross = gross_wall_area_m2(perim, height)
    doors = _num(params, "doors") if _has(params, "doors") else 0.0
    windows = _num(params, "windows") if _has(params, "windows") else 0.0
    openings = openings_area_m2(doors, windows)
    net = net_wall_area_m2(gross, openings) * max(min(share, 1.0), 0.0)
    estimated = perim_estimated or height_estimated or openings > 0
    return net, estimated


# ── The formula registry (qty_formula id -> pure function) ───────────────────
#
# Each function takes the parameter sheet and the work package's declared unit
# and returns a QtyResult. Keep these deterministic and side-effect-free so the
# offline path computes the exact same numbers as the AI path.


def _floor_area(params: dict[str, Any], unit: str) -> QtyResult:
    """Floor area straight from ``floor_area_m2`` (or an area-style param)."""
    area = (
        _num(params, "floor_area_m2") or _num(params, "gross_floor_area_m2") or _num(params, "extension_floor_area_m2")
    )
    return QtyResult(area, unit, estimated=False)


def _ceiling(params: dict[str, Any], unit: str) -> QtyResult:
    """Ceiling area equals the floor area (one storey footprint)."""
    return QtyResult(_num(params, "floor_area_m2"), unit, estimated=False)


def _wall_net(params: dict[str, Any], unit: str) -> QtyResult:
    """Net wall area (perimeter times height, less openings)."""
    share = 1.0
    # Wet-zone tiling covers only part of the wall unless full tiling is set.
    if params.get("wet_zone_tiling") is True and params.get("full_tiling") is not True:
        share = 0.45
    net, estimated = _net_wall(params, share=share)
    return QtyResult(net, unit, estimated=estimated)


def _wall_full(params: dict[str, Any], unit: str) -> QtyResult:
    """Full net wall area (e.g. bathroom full tiling, plaster, painting)."""
    net, estimated = _net_wall(params, share=1.0)
    return QtyResult(net, unit, estimated=estimated)


def _partition(params: dict[str, Any], unit: str) -> QtyResult:
    """New partition area = partition length times ceiling height."""
    length = _num(params, "partition_lm")
    height = _ceiling_height(params)
    estimated = not _has(params, "ceiling_height_m") or _num(params, "ceiling_height_m") <= 0
    return QtyResult(length * height, unit, estimated=estimated)


def _fixtures(params: dict[str, Any], unit: str) -> QtyResult:
    """Fixture / fitting count. Derived from rooms when no explicit count."""
    if _has(params, "fixtures_count"):
        return QtyResult(_num(params, "fixtures_count"), unit, estimated=False)
    # Derive a conservative fixture spread from wet rooms (one set per room).
    rooms = _num(params, "wet_rooms_count") or _num(params, "room_count")
    if rooms > 0:
        return QtyResult(round(rooms * 3.0), unit, estimated=True)
    return QtyResult(0.0, unit, estimated=False)


def _points(params: dict[str, Any], unit: str) -> QtyResult:
    """Electrical points = round(floor area times a density proxy)."""
    area = _num(params, "floor_area_m2")
    density = _num(params, "points_density") if _has(params, "points_density") else _DEFAULT_POINTS_DENSITY
    return QtyResult(float(round(area * density)), unit, estimated=True)


def _slope(params: dict[str, Any], unit: str) -> QtyResult:
    """Roof slope area from plan area and pitch."""
    plan = _num(params, "roof_area_m2")
    pitch = _num(params, "pitch_deg")
    estimated = not _has(params, "pitch_deg")
    return QtyResult(slope_area_m2(plan, pitch), unit, estimated=estimated)


def _facade_net(params: dict[str, Any], unit: str) -> QtyResult:
    """Facade system area = gross facade less openings area."""
    gross = _num(params, "facade_area_m2")
    openings = _num(params, "openings_area_m2")
    return QtyResult(net_wall_area_m2(gross, openings), unit, estimated=False)


def _facade_gross(params: dict[str, Any], unit: str) -> QtyResult:
    """Scaffolding area = gross facade area (or a lump when absent)."""
    return QtyResult(_num(params, "facade_area_m2"), unit, estimated=False)


def _paving(params: dict[str, Any], unit: str) -> QtyResult:
    return QtyResult(_num(params, "paving_area_m2"), unit, estimated=False)


def _planting(params: dict[str, Any], unit: str) -> QtyResult:
    return QtyResult(_num(params, "planting_area_m2") or _num(params, "turf_area_m2"), unit, estimated=False)


def _fencing(params: dict[str, Any], unit: str) -> QtyResult:
    return QtyResult(_num(params, "fencing_lm"), unit, estimated=False)


def _debris(params: dict[str, Any], unit: str) -> QtyResult:
    """Strip-out debris volume from the demolished floor area."""
    area = _num(params, "floor_area_m2")
    return QtyResult(debris_volume_m3(area), unit, estimated=True)


def _site_area(params: dict[str, Any], unit: str) -> QtyResult:
    return QtyResult(_num(params, "site_area_m2"), unit, estimated=False)


def _earthworks(params: dict[str, Any], unit: str) -> QtyResult:
    """Earthworks volume (explicit, or footprint times excavation depth)."""
    if _has(params, "earthworks_volume_m3"):
        return QtyResult(_num(params, "earthworks_volume_m3"), unit, estimated=False)
    footprint = _num(params, "footprint_m2") or _num(params, "extension_floor_area_m2")
    depth = _num(params, "excavation_depth_m") if _has(params, "excavation_depth_m") else 0.5
    return QtyResult(footprint * depth, unit, estimated=True)


def _lump(params: dict[str, Any], unit: str) -> QtyResult:
    """A single lump-sum line (commissioning, connection, making-good)."""
    return QtyResult(1.0, unit, estimated=False)


# qty_formula id -> pure function. The integrity test asserts every
# WorkPackage.qty_formula resolves to a key here, so adding a package without a
# formula fails fast.
FORMULAS: dict[str, Callable[[dict[str, Any], str], QtyResult]] = {
    "floor_area": _floor_area,
    "ceiling": _ceiling,
    "wall_net": _wall_net,
    "wall_full": _wall_full,
    "partition": _partition,
    "fixtures": _fixtures,
    "points": _points,
    "slope": _slope,
    "facade_net": _facade_net,
    "facade_gross": _facade_gross,
    "paving": _paving,
    "planting": _planting,
    "fencing": _fencing,
    "debris": _debris,
    "site_area": _site_area,
    "earthworks": _earthworks,
    "lump": _lump,
}

# The set of quantity-feeding formula ids a ProjectParam may reference in its
# ``unlocks`` tuple. Kept identical to FORMULAS keys so the integrity test can
# assert every unlock points at a real formula.
FORMULA_IDS: frozenset[str] = frozenset(FORMULAS)


def compute_quantity(qty_formula: str, params: dict[str, Any], unit: str) -> QtyResult:
    """Evaluate one work package's quantity from the confirmed parameter sheet.

    Args:
        qty_formula: The stable formula id declared on the work package.
        params: The confirmed (or partial) parameter sheet.
        unit: The work package's measurement unit (echoed onto the result).

    Returns:
        A :class:`QtyResult`. An unknown ``qty_formula`` yields a zero,
        non-estimated result rather than raising, so a data typo degrades to an
        honest empty quantity the user can fill in.
    """
    fn = FORMULAS.get(qty_formula)
    if fn is None:
        return QtyResult(0.0, unit, estimated=False)
    return fn(params, unit)


# ── Human-readable derivation + assumptions (for the WorkGroup metadata) ──────
#
# A short, layperson-readable formula sentence ("perimeter x height") per
# qty_formula id, surfaced read-only on the group so the user can see HOW a
# quantity was derived. Independent of the parameter sheet (it is the shape of
# the formula, not the numbers).
_DERIVATION_TEXT: dict[str, str] = {
    "floor_area": "floor area",
    "ceiling": "ceiling area equals the floor area",
    "wall_net": "perimeter x height less openings",
    "wall_full": "perimeter x height less openings",
    "partition": "partition length x ceiling height",
    "fixtures": "fixture count",
    "points": "floor area x points density",
    "slope": "plan roof area / cos(pitch)",
    "facade_net": "facade area less openings",
    "facade_gross": "gross facade area",
    "paving": "paving area",
    "planting": "planting / turf area",
    "fencing": "fencing length",
    "debris": "stripped floor area x equivalent depth",
    "site_area": "site area",
    "earthworks": "footprint x excavation depth",
    "lump": "single lump-sum line",
}


def describe_derivation(qty_formula: str, params: dict[str, Any], result: QtyResult) -> tuple[str, list[str]]:
    """Describe how a quantity was derived, plus the proxy assumptions used.

    Produces the two human-facing provenance fields the WorkGroup metadata
    standardises (design section 3.1): a short formula sentence (for example
    ``"perimeter x height less openings"``) and a list of plain-language
    assumptions naming each proxy that was actually applied for these params
    (for example ``"perimeter inferred from floor area (aspect 1.4)"``). The
    assumptions list is non-empty only when a proxy was used; a quantity taken
    straight from a confirmed value carries no assumptions.

    Nothing here invents a number; it only explains the derivation the pure
    formula already performed. An unknown ``qty_formula`` yields an empty
    description, mirroring :func:`compute_quantity`.

    Args:
        qty_formula: The stable formula id declared on the work package.
        params: The confirmed (or partial) parameter sheet.
        result: The :class:`QtyResult` already computed for this package.

    Returns:
        A ``(derivation_text, assumptions)`` pair. ``derivation_text`` is empty
        for an unknown formula; ``assumptions`` is empty when no proxy was used.
    """
    derivation = _DERIVATION_TEXT.get(qty_formula, "")
    if not derivation or not result.estimated:
        return derivation, []

    assumptions: list[str] = []
    if qty_formula in ("wall_net", "wall_full", "partition", "points", "debris"):
        if qty_formula in ("wall_net", "wall_full"):
            if not (_has(params, "perimeter_m") and _num(params, "perimeter_m") > 0):
                assumptions.append(f"perimeter inferred from floor area (aspect {_DEFAULT_ROOM_ASPECT})")
            if not _has(params, "ceiling_height_m") or _num(params, "ceiling_height_m") <= 0:
                assumptions.append(f"ceiling height defaulted to {_DEFAULT_CEILING_HEIGHT_M} m")
            doors = _num(params, "doors") if _has(params, "doors") else 0.0
            windows = _num(params, "windows") if _has(params, "windows") else 0.0
            if doors > 0 or windows > 0:
                assumptions.append(
                    f"openings sized from defaults (door {_DEFAULT_DOOR_AREA_M2} m2, "
                    f"window {_DEFAULT_WINDOW_AREA_M2} m2)"
                )
        elif qty_formula == "partition":
            assumptions.append(f"ceiling height defaulted to {_DEFAULT_CEILING_HEIGHT_M} m")
        elif qty_formula == "points":
            assumptions.append(f"points density proxy {_DEFAULT_POINTS_DENSITY} per m2 of floor area")
        elif qty_formula == "debris":
            assumptions.append(f"debris depth proxy {_DEFAULT_DEBRIS_DEPTH_M} m over stripped area")
    elif qty_formula == "fixtures":
        assumptions.append("fixtures inferred from room count (3 per wet room)")
    elif qty_formula == "slope":
        assumptions.append("flat roof assumed (pitch not given)")
    elif qty_formula == "earthworks":
        depth = _num(params, "excavation_depth_m") if _has(params, "excavation_depth_m") else 0.5
        assumptions.append(f"excavation depth proxy {depth} m over the footprint")

    return derivation, assumptions
