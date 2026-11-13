# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""DWG Takeoff demo seed - measurements taken off the drawing that exists.

The drawing itself is already seeded (``app.scripts.seed_dwg_drawing`` authors a
small floor plan with ezdxf and parses it through the same path an upload uses),
so what was missing was everything an estimator does *to* a drawing: nothing had
ever been measured on it, and ``/dwg-takeoff`` opened on bare geometry.

Every annotation written here is read back off the parsed drawing through
:meth:`DwgTakeoffService.get_entities` - the same reader the viewer uses - and
its coordinates are that entity's own coordinates. A closed polyline becomes an
area measurement whose value is the shoelace area of its vertices; a line becomes
a distance measurement whose value is the length between its endpoints; a text
label becomes a pin at its own insertion point carrying its own string. Raw
drawing units are converted to metres with the factor the parse recorded on the
version, and when the units are unknown the measurement is left empty rather than
stated wrongly. Nothing is placed at coordinates the drawing does not have.

What this seeder deliberately does not do
-----------------------------------------
* **It does not add a second drawing version.** A version row asserts that the
  drawing was re-issued and re-parsed. Pointing a second version at the first
  one's entities file would claim a revision whose geometry is byte-identical to
  the one it supersedes, and the revision-compare view would report a re-issue
  with no changes.
* **It does not add a second drawing.** There is no committed DXF asset in the
  tree to widen the register with; the one demo plan is authored at seed time.
  A second row therefore means authoring a second plan, which is new geometry.
* **It does not save entity groups.** Entity ids are positional (``e_{index}``,
  minted per read over the *layer-filtered* list), so a stored group selects
  different entities as soon as a layer is toggled off.

Idempotent per drawing: a drawing that already carries an annotation is left
alone, so a re-run never doubles the markup.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.dwg_takeoff.models import DwgAnnotation, DwgDrawing, DwgDrawingVersion

logger = logging.getLogger(__name__)

# Raw drawing units to metres. The parse records the unit on the version, taken
# from the DXF header's $INSUNITS. An unrecognised unit yields no factor, and a
# measurement is then left unset rather than stated in the wrong scale.
_UNIT_TO_METRES: dict[str, float] = {
    "mm": 0.001,
    "millimeters": 0.001,
    "cm": 0.01,
    "centimeters": 0.01,
    "m": 1.0,
    "meters": 1.0,
    "in": 0.0254,
    "inches": 0.0254,
    "ft": 0.3048,
    "feet": 0.3048,
}

# How many of each kind of measurement one drawing gets. An estimator measures
# the rooms and the runs that matter, not every entity on the sheet.
_MAX_AREAS = 2
_MAX_DISTANCES = 3
_MAX_PINS = 2

# Marker colours, one per kind, so the three measurement types read apart on the
# canvas. Mirrors the palette the tool palette offers.
_COLOR_AREA = "#22c55e"
_COLOR_DISTANCE = "#3b82f6"
_COLOR_PIN = "#f59e0b"

_SEED_SOURCE = "dwg_takeoff_demo_seed"

# Envelope outlines (gross floor area, plot boundary, building footprint) and the
# sheet frame enclose the rooms, so largest-first would always pick them over what
# an estimator measures. Matched against AIA layer name parts, e.g. A-AREA-GROS,
# C-PROP, C-BLDG, A-ANNO-TTLB.
_ENVELOPE_LAYER_PARTS = frozenset({"GROS", "PROP", "BLDG", "TTLB"})


def _is_envelope_layer(layer: str) -> bool:
    return any(part in _ENVELOPE_LAYER_PARTS for part in layer.upper().split("-"))


def _unit_factor(units: str | None) -> float | None:
    """Metres per raw drawing unit, or None when the unit is not recognised."""
    return _UNIT_TO_METRES.get((units or "").strip().lower())


def _point(raw: Any) -> dict[str, float] | None:
    """Coerce a parsed point to ``{"x": float, "y": float}``, or None."""
    if not isinstance(raw, dict):
        return None
    try:
        return {"x": float(raw["x"]), "y": float(raw["y"])}
    except (KeyError, TypeError, ValueError):
        return None


def _points(raw: Any) -> list[dict[str, float]]:
    """Coerce a parsed vertex list, dropping anything unusable."""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, float]] = []
    for item in raw:
        point = _point(item)
        if point is not None:
            out.append(point)
    return out


def _polygon_area(points: Sequence[dict[str, float]]) -> float:
    """Shoelace area of a closed ring, in raw units squared. Zero when degenerate."""
    if len(points) < 3:
        return 0.0
    total = 0.0
    for index, current in enumerate(points):
        nxt = points[(index + 1) % len(points)]
        total += current["x"] * nxt["y"] - nxt["x"] * current["y"]
    return abs(total) / 2.0


def _distance(start: dict[str, float], end: dict[str, float]) -> float:
    """Length between two points, in raw units."""
    return ((end["x"] - start["x"]) ** 2 + (end["y"] - start["y"]) ** 2) ** 0.5


def _plan_annotations(entities: Sequence[dict[str, Any]], factor: float | None) -> list[dict[str, Any]]:
    """Derive the markup for one drawing from its own parsed entities.

    Returns annotation field dicts, ordered areas then distances then pins.
    Every geometry is the source entity's own coordinates, and every
    measurement is computed from them - so a drawing with no closed polyline
    simply gets no area measurement rather than an invented one.
    """
    areas: list[tuple[float, dict[str, Any]]] = []
    distances: list[tuple[float, str, dict[str, Any]]] = []
    pins: list[dict[str, Any]] = []

    for entity in entities:
        etype = str(entity.get("type") or "")
        layer = str(entity.get("layer") or "")

        if etype in ("LWPOLYLINE", "POLYLINE") and entity.get("closed"):
            ring = _points(entity.get("vertices"))
            raw_area = _polygon_area(ring)
            if raw_area <= 0 or _is_envelope_layer(layer):
                continue
            areas.append(
                (
                    raw_area,
                    {
                        "annotation_type": "area",
                        "geometry": {"points": ring},
                        "text": f"Enclosed area on {layer}" if layer else "Enclosed area",
                        "color": _COLOR_AREA,
                        "measurement_value": (
                            Decimal(str(round(raw_area * factor * factor, 6))) if factor is not None else None
                        ),
                        "measurement_unit": "m2" if factor is not None else None,
                        "metadata_": {
                            "source": _SEED_SOURCE,
                            "derived_from": {"entity_type": etype, "layer": layer},
                            "raw_value": round(raw_area, 6),
                        },
                    },
                )
            )
            continue

        if etype == "LINE":
            start = _point(entity.get("start"))
            end = _point(entity.get("end"))
            if start is None or end is None or _is_envelope_layer(layer):
                continue
            raw_length = _distance(start, end)
            if raw_length <= 0:
                continue
            distances.append(
                (
                    raw_length,
                    layer,
                    {
                        "annotation_type": "distance",
                        "geometry": {"points": [start, end]},
                        "text": f"Run measured on {layer}" if layer else "Measured run",
                        "color": _COLOR_DISTANCE,
                        "measurement_value": (
                            Decimal(str(round(raw_length * factor, 6))) if factor is not None else None
                        ),
                        "measurement_unit": "m" if factor is not None else None,
                        "metadata_": {
                            "source": _SEED_SOURCE,
                            "derived_from": {"entity_type": etype, "layer": layer},
                            "raw_value": round(raw_length, 6),
                        },
                    },
                )
            )
            continue

        if etype == "TEXT":
            insert = _point(entity.get("start"))
            label = str(entity.get("text") or "").strip()
            if insert is None or not label:
                continue
            pins.append(
                {
                    "annotation_type": "text_pin",
                    "geometry": {"points": [insert]},
                    "text": label,
                    "color": _COLOR_PIN,
                    "measurement_value": None,
                    "measurement_unit": None,
                    "metadata_": {
                        "source": _SEED_SOURCE,
                        "derived_from": {"entity_type": etype, "layer": layer},
                    },
                }
            )

    # Largest first: the room before the cupboard, the long run before the
    # short one, which is the order an estimator works in.
    # Room polygons live on an AIA area layer (A-AREA); when the drawing has them,
    # roof, slab and wall outlines are not what a takeoff measures.
    room_areas = [item for item in areas if "AREA" in item[1]["metadata_"]["derived_from"]["layer"].upper().split("-")]
    areas = room_areas or areas
    areas.sort(key=lambda item: item[0], reverse=True)

    planned = [fields for _size, fields in areas[:_MAX_AREAS]]
    planned += _pick_distances(distances)
    planned += pins[:_MAX_PINS]
    return planned


def _pick_distances(
    candidates: list[tuple[float, str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Choose the runs to measure: the longest on each layer, then the rest.

    Taking the longest lines outright would measure one layer twice and say the
    same thing twice - a window drawn as a pair of parallel lines yields two
    identical readings. Taking the longest run per layer first covers the
    distinct elements on the sheet before it doubles up on any of them.
    """
    candidates = sorted(candidates, key=lambda item: item[0], reverse=True)
    chosen: list[dict[str, Any]] = []
    seen_layers: set[str] = set()
    remainder: list[dict[str, Any]] = []

    for _length, layer, fields in candidates:
        if layer in seen_layers:
            remainder.append(fields)
            continue
        seen_layers.add(layer)
        if len(chosen) < _MAX_DISTANCES:
            chosen.append(fields)
        else:
            remainder.append(fields)

    for fields in remainder:
        if len(chosen) >= _MAX_DISTANCES:
            break
        chosen.append(fields)
    return chosen


async def _has_annotations(session: AsyncSession, drawing_id: uuid.UUID) -> bool:
    """True when the drawing already carries markup."""
    stmt = select(DwgAnnotation.id).where(DwgAnnotation.drawing_id == drawing_id).limit(1)
    return (await session.execute(stmt)).scalars().first() is not None


async def _latest_version(session: AsyncSession, drawing_id: uuid.UUID) -> DwgDrawingVersion | None:
    """The drawing's newest parsed version, or None when it has none."""
    stmt = (
        select(DwgDrawingVersion)
        .where(DwgDrawingVersion.drawing_id == drawing_id)
        .order_by(DwgDrawingVersion.version_number.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()


async def _seed_project(
    session: AsyncSession,
    project_id: uuid.UUID,
    owner_id: uuid.UUID | None,
) -> dict[str, int]:
    """Mark up every unannotated drawing on one project."""
    from app.modules.dwg_takeoff.service import DwgTakeoffService

    empty = {"projects": 0, "drawings": 0, "annotations": 0, "measured": 0}

    # Found by query, never by recomputing the seeder's deterministic id: the
    # flagship path and the demo-asset path mint their drawings separately.
    drawings = list(
        (await session.execute(select(DwgDrawing).where(DwgDrawing.project_id == project_id))).scalars().all()
    )
    if not drawings:
        logger.debug("DWG takeoff demo skipped for project=%s (no drawing)", project_id)
        return empty

    service = DwgTakeoffService(session)
    author = str(owner_id) if owner_id is not None else ""
    counts = {"projects": 0, "drawings": 0, "annotations": 0, "measured": 0}

    for drawing in drawings:
        if await _has_annotations(session, drawing.id):
            continue

        version = await _latest_version(session, drawing.id)
        if version is None or version.status != "ready":
            # An unparsed drawing has no geometry to measure. The convert CTA is
            # the honest state for it, not markup over nothing.
            continue

        entities = await service.get_entities(drawing.id)
        if not entities:
            continue

        factor = _unit_factor(version.units)
        if factor is None:
            logger.info(
                "DWG takeoff demo: drawing=%s has unrecognised units %r - annotations carry no measurement",
                drawing.id,
                version.units,
            )

        planned = _plan_annotations(entities, factor)
        if not planned:
            continue

        for fields in planned:
            session.add(
                DwgAnnotation(
                    project_id=project_id,
                    drawing_id=drawing.id,
                    drawing_version_id=version.id,
                    created_by=author,
                    **fields,
                )
            )
            counts["annotations"] += 1
            if fields.get("measurement_value") is not None:
                counts["measured"] += 1
        await session.flush()
        counts["drawings"] += 1

    if counts["drawings"]:
        counts["projects"] = 1
    return counts


async def seed_dwg_takeoff_demo(
    session: AsyncSession,
    project_ids: Iterable[uuid.UUID],
) -> dict[str, int]:
    """Mark up the demo projects' drawings with measurements taken off them.

    Only demo projects are touched: ``enrich_all`` hands this seeder every
    project in the database, including a customer's own. A project without
    ``metadata["demo_id"]`` is skipped outright - "this drawing has no
    annotations" is not a gate, because a real drawing nobody has measured yet
    is empty by that test too.

    Args:
        session: Async DB session. The caller commits.
        project_ids: Candidate projects. Skipped when not a demo project, when
            it carries no drawing, or when every drawing is already annotated.

    Returns:
        Dict with the number of projects and drawings touched, annotations
        written, and how many of those carry a real measurement.
    """
    totals = {"projects": 0, "drawings": 0, "annotations": 0, "measured": 0}
    ids = list(project_ids)
    if not ids:
        return totals

    from app.modules.projects.models import Project

    rows = (
        await session.execute(select(Project.id, Project.owner_id, Project.metadata_).where(Project.id.in_(ids)))
    ).all()

    for project_id, owner_id, metadata in rows:
        if not (metadata or {}).get("demo_id"):
            continue
        try:
            # A SAVEPOINT per project: on PostgreSQL a failed statement aborts
            # the whole transaction, so one project that cannot be seeded would
            # otherwise take every later project down with it.
            async with session.begin_nested():
                counts = await _seed_project(session, project_id, owner_id)
        except Exception:
            logger.warning("DWG takeoff demo seed skipped for project=%s (non-fatal)", project_id, exc_info=True)
            continue
        for key, value in counts.items():
            totals[key] += value
    return totals
