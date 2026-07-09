# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Pure, deterministic quantity take-off from an ACAP FloorPlan.

NO database, NO LLM. Every function here is a pure geometry computation over
:mod:`app.modules.acap.layout.schema` pydantic models. This module is the
single source of truth for wall/opening quantities consumed by the RAB
generator (:mod:`app.modules.acap.rab.generator`).
"""

from __future__ import annotations

from app.modules.acap.layout.schema import FloorPlan, Level, Point

# Module constants — configurable, single source of truth for this phase's
# scope (wall/finish take-off only; see rab/generator.py for the MVP scope
# note).
WALL_HEIGHT_M: float = 3.0
OPENING_HEIGHT_M: dict[str, float] = {"door": 2.1, "window": 1.2}


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


def takeoff(plan: FloorPlan) -> list[dict]:
    """Run the full take-off over every level of *plan*.

    Returns one dict per level: {level, floor_area_m2, wall_length_m,
    gross_wall_area_m2, opening_area_m2, net_wall_area_m2}.
    """
    results: list[dict] = []
    for level in plan.levels:
        wl = wall_length(level)
        gross = wl * WALL_HEIGHT_M
        oa = opening_area(level)
        results.append(
            {
                "level": level.level,
                "floor_area_m2": floor_area(level),
                "wall_length_m": wl,
                "gross_wall_area_m2": gross,
                "opening_area_m2": oa,
                "net_wall_area_m2": max(0.0, gross - oa),
            }
        )
    return results
