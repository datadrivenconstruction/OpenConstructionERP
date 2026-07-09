# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Pure, deterministic quantity take-off from an ACAP FloorPlan.

NO database, NO LLM. Every function here is a pure geometry computation over
:mod:`app.modules.acap.layout.schema` pydantic models. This module is the
single source of truth for wall/opening quantities consumed by the RAB
generator (:mod:`app.modules.acap.rab.generator`).
"""

from __future__ import annotations

from app.modules.acap.layout.schema import FloorPlan, Level, Point

# Module constants — configurable, single source of truth for every geometry
# assumption consumed by rab/generator.py's ELEMENT_KODE_MAP. Every constant
# here encodes a fixed estimator decision (docs/plans/2026-07-09-rab-full-
# wiring-spec.md §2) — copied verbatim, never re-derived.
WALL_HEIGHT_M: float = 3.0
OPENING_HEIGHT_M: dict[str, float] = {"door": 2.1, "window": 1.2}

ROOF_PITCH_FACTOR: float = 1.20  # pitched roof surface area = footprint * factor
KOLOM_PRAKTIS_SPACING_M: float = 3.5  # one kolom praktis every 3.5 m of wall run
KM_TILE_HEIGHT_M: float = 2.0  # wet-area wall tiling height, floor to tile-top (m)
LAMPU_PER_ROOM: int = 1
STOPKONTAK_PER_ROOM: int = 2
SAKLAR_PER_ROOM: int = 1
DOOR_HINGES: int = 3
WINDOW_HINGES: int = 2
PIPA_BERSIH_PER_FIXTURE_M: float = 6.0  # clean-water pipe run per wet-room fixture (m)
PIPA_KOTOR_PER_KM_M: float = 8.0  # soil pipe run per kamar_mandi (m)
RISER_M: float = 10.0  # shared vertical riser allowance (m)
PONDASI_SECTION_M2: float = 0.6  # batu belah trapezoid cross-section area (m2, per running metre)

# Room types excluded from "indoor" floor/plafon/MEP scope (unheated/uncovered
# or vehicle spaces that don't get flooring/plafon/lighting the same way).
INDOOR_EXCLUDE_TYPES: frozenset[str] = frozenset({"teras", "taman", "carport", "garasi"})
WET_ROOM_TYPES: frozenset[str] = frozenset({"kamar_mandi"})


def _shoelace_area(polygon: list[Point]) -> float:
    """Shoelace-formula area of a simple polygon (works for any winding)."""
    n = len(polygon)
    if n < 3:
        return 0.0
    total = 0.0
    for i in range(n):
        p1 = polygon[i]
        p2 = polygon[(i + 1) % n]
        total += p1.x * p2.y - p2.x * p1.y
    return abs(total) / 2.0


def floor_area(level: Level) -> float:
    """Sum of the shoelace area of every room polygon on *level*."""
    return sum(_shoelace_area(room.polygon) for room in level.rooms)


def _edge_key(p1: Point, p2: Point) -> tuple[tuple[float, float], tuple[float, float]]:
    """Canonical, direction-independent key for an edge (exact-coincidence dedup).

    # ponytail: exact-coincidence dedup only — a wall shared by two rooms
    # whose edges coincide EXACTLY (same two endpoints) is deduped. Partial
    # overlaps between unequal adjacent rooms (e.g. one room's edge only
    # partially covers a neighbour's edge) are NOT merged — each such edge is
    # counted per-room as authored. Upgrade path if that proves material:
    # segment-interval merging (sort collinear segments per wall line, union
    # overlapping intervals) instead of whole-edge-endpoint matching.
    """
    a = (p1.x, p1.y)
    b = (p2.x, p2.y)
    return (a, b) if a <= b else (b, a)


def wall_length(level: Level) -> float:
    """Total deduped wall length: every room-polygon edge, shared edges counted once."""
    edges: dict[tuple[tuple[float, float], tuple[float, float]], float] = {}
    for room in level.rooms:
        n = len(room.polygon)
        for i in range(n):
            p1 = room.polygon[i]
            p2 = room.polygon[(i + 1) % n]
            key = _edge_key(p1, p2)
            if key not in edges:
                length = ((p2.x - p1.x) ** 2 + (p2.y - p1.y) ** 2) ** 0.5
                edges[key] = length
    return sum(edges.values())


def opening_area(level: Level) -> float:
    """Sum of width_m * OPENING_HEIGHT_M[type] over every opening on *level*."""
    return sum(o.width_m * OPENING_HEIGHT_M[o.type] for o in level.openings)


def net_wall_area(level: Level) -> float:
    """Gross wall area (wall_length * WALL_HEIGHT_M) minus opening_area, floored at 0."""
    gross = wall_length(level) * WALL_HEIGHT_M
    return max(0.0, gross - opening_area(level))


def _polygon_perimeter(polygon: list[Point]) -> float:
    """Perimeter of a single polygon's own edges — no cross-room dedup (unlike
    :func:`wall_length`). Used for wet-room wall tiling, where a shared wall
    with a neighbouring room still needs its own KM-side tile run."""
    n = len(polygon)
    if n < 2:
        return 0.0
    total = 0.0
    for i in range(n):
        p1 = polygon[i]
        p2 = polygon[(i + 1) % n]
        total += ((p2.x - p1.x) ** 2 + (p2.y - p1.y) ** 2) ** 0.5
    return total


def floor_area_indoor(level: Level) -> float:
    """Sum of shoelace area of every INDOOR room (excludes INDOOR_EXCLUDE_TYPES)."""
    return sum(
        _shoelace_area(room.polygon) for room in level.rooms if room.type not in INDOOR_EXCLUDE_TYPES
    )


def room_counts(level: Level) -> tuple[int, int, int]:
    """Return (room_count, indoor_room_count, wet_room_count) for *level*."""
    room_count = len(level.rooms)
    indoor_room_count = sum(1 for room in level.rooms if room.type not in INDOOR_EXCLUDE_TYPES)
    wet_room_count = sum(1 for room in level.rooms if room.type in WET_ROOM_TYPES)
    return room_count, indoor_room_count, wet_room_count


def wet_floor_area(level: Level) -> float:
    """Sum of shoelace area of every kamar_mandi room on *level*."""
    return sum(_shoelace_area(room.polygon) for room in level.rooms if room.type in WET_ROOM_TYPES)


def wet_wall_perimeter(level: Level) -> float:
    """Sum of each kamar_mandi room's own polygon perimeter (no cross-room dedup)."""
    return sum(_polygon_perimeter(room.polygon) for room in level.rooms if room.type in WET_ROOM_TYPES)


def opening_counts(level: Level) -> dict[str, float]:
    """Door/window counts, kusen lengths, leaf areas, and glass area for *level*.

    door_kusen_len_m  = Σ 2*(w + door_height)   window_kusen_len_m  = Σ 2*(w + window_height)
    door_leaf_area_m2 = Σ w*door_height         window_leaf_area_m2 = Σ w*window_height
    glass_area_m2 mirrors window_leaf_area_m2 (glazed-sash assumption).
    """
    door_h = OPENING_HEIGHT_M["door"]
    window_h = OPENING_HEIGHT_M["window"]
    door_count = 0
    window_count = 0
    door_kusen_len_m = 0.0
    window_kusen_len_m = 0.0
    door_leaf_area_m2 = 0.0
    window_leaf_area_m2 = 0.0
    for o in level.openings:
        if o.type == "door":
            door_count += 1
            door_kusen_len_m += 2 * (o.width_m + door_h)
            door_leaf_area_m2 += o.width_m * door_h
        else:
            window_count += 1
            window_kusen_len_m += 2 * (o.width_m + window_h)
            window_leaf_area_m2 += o.width_m * window_h
    return {
        "door_count": door_count,
        "window_count": window_count,
        "door_kusen_len_m": door_kusen_len_m,
        "window_kusen_len_m": window_kusen_len_m,
        "door_leaf_area_m2": door_leaf_area_m2,
        "window_leaf_area_m2": window_leaf_area_m2,
        "glass_area_m2": window_leaf_area_m2,
    }


def takeoff(plan: FloorPlan) -> list[dict]:
    """Run the full take-off over every level of *plan*.

    Returns one dict per level: {level, floor_area_m2, floor_area_indoor_m2,
    roof_footprint_m2, wall_length_m, exterior_perimeter_m, gross_wall_area_m2,
    opening_area_m2, net_wall_area_m2, room_count, indoor_room_count,
    wet_room_count, wet_floor_area_m2, wet_wall_perimeter_m, door_count,
    window_count, door_kusen_len_m, window_kusen_len_m, door_leaf_area_m2,
    window_leaf_area_m2, glass_area_m2}.
    """
    results: list[dict] = []
    for level in plan.levels:
        wl = wall_length(level)
        gross = wl * WALL_HEIGHT_M
        oa = opening_area(level)
        room_count, indoor_room_count, wet_room_count = room_counts(level)
        results.append(
            {
                "level": level.level,
                "floor_area_m2": floor_area(level),
                "floor_area_indoor_m2": floor_area_indoor(level),
                # Roof geometry uses the FOOTPRINT (every room, indoor or not)
                # — the generator picks the top level's value only.
                "roof_footprint_m2": floor_area(level),
                "wall_length_m": wl,
                "exterior_perimeter_m": wl,
                "gross_wall_area_m2": gross,
                "opening_area_m2": oa,
                "net_wall_area_m2": max(0.0, gross - oa),
                "room_count": room_count,
                "indoor_room_count": indoor_room_count,
                "wet_room_count": wet_room_count,
                "wet_floor_area_m2": wet_floor_area(level),
                "wet_wall_perimeter_m": wet_wall_perimeter(level),
                **opening_counts(level),
            }
        )
    return results


# Per-level fields summed across every level to build the plan-wide
# aggregate (everything EXCEPT the top-level-only / ground-level-only fields
# handled explicitly in :func:`aggregate`).
_SUMMED_FIELDS: tuple[str, ...] = (
    "net_wall_area_m2",
    "floor_area_indoor_m2",
    "wall_length_m",
    "room_count",
    "indoor_room_count",
    "wet_room_count",
    "wet_floor_area_m2",
    "wet_wall_perimeter_m",
    "door_count",
    "window_count",
    "door_kusen_len_m",
    "window_kusen_len_m",
    "door_leaf_area_m2",
    "window_leaf_area_m2",
    "glass_area_m2",
)


def aggregate(plan: FloorPlan) -> dict:
    """Plan-wide quantities consumed by the RAB generator's ELEMENT_KODE_MAP.

    Every field in :data:`_SUMMED_FIELDS` is SUMMED across every level, except:
      * ``roof_footprint_m2`` / ``top_exterior_perimeter_m`` — the TOP level
        only (roof/listplank geometry is a function of the topmost footprint,
        not the sum of every floor's footprint).
      * ``ground_wall_length_m`` — level 1 only (pondasi runs under the
        ground floor's walls, not upper-floor walls).
    """
    results = takeoff(plan)
    if not results:
        agg: dict = dict.fromkeys(_SUMMED_FIELDS, 0.0)
        agg["roof_footprint_m2"] = 0.0
        agg["top_exterior_perimeter_m"] = 0.0
        agg["ground_wall_length_m"] = 0.0
        return agg

    agg = {field: sum(r[field] for r in results) for field in _SUMMED_FIELDS}
    top = max(results, key=lambda r: r["level"])
    ground = min(results, key=lambda r: r["level"])
    agg["roof_footprint_m2"] = top["roof_footprint_m2"]
    agg["top_exterior_perimeter_m"] = top["exterior_perimeter_m"]
    agg["ground_wall_length_m"] = ground["wall_length_m"]
    return agg
