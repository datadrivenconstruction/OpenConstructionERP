# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Demo seed data for the takeoff module.

Loaded on demand via ``await seed_takeoff_demo(session, project_ids)``.

Seeds the uploaded PDF :class:`TakeoffDocument` rows of every showcase project
- the flagship reference build plus the German demo projects, and BOTH issues
of sheet A-2.01 on the shoot project so the revision compare has two documents
to diff - together with a spread of
:class:`TakeoffMeasurement` annotations whose values are DERIVED from their
own geometry: every measurement's ``points`` + ``scale_pixels_per_unit`` are
fed through :func:`app.modules.takeoff.service.recompute_measurement_value`
(the same function the API uses), so the stored value can never contradict the
drawn shape. German projects get the vector Grundriss fixture rendered by
:mod:`app.scripts.generate_grundriss_pdf`; measurement polygons come from the
same :mod:`app.scripts.grundriss_plan` geometry, so a seeded room measurement
encloses exactly the room it names.

Where a matching BOQ position exists on the same project (matched against the
demo templates' own German descriptions, never invented), the measurement is
linked via ``linked_boq_position_id`` - the traceability chain the takeoff
workspace demonstrates. Only positions that really exist are referenced; a
missed lookup leaves the measurement unlinked rather than pointing nowhere.

The seed is idempotent PER DOCUMENT, keyed on ``metadata.seed_key``: a sheet
already present is skipped, a sheet still missing is written, and a project
holding a document this seeder did not write is left to its owner. That keeps
a re-run a no-op while an install that predates a sheet still receives it, and
it survives renaming a sheet (the old file-name-shaped identity would have
re-seeded the same drawing under its new name). Legacy demo rows minted
without a document, points or scale (the old "boq_derived" fill) are pruned -
a measurement that cannot be shown on any sheet is worse than an honest empty
state - and a document seeded before the sheet carried a revision index is
adopted into the index-A plan instead of being duplicated.

The flagship's CAD extraction session is idempotent on its own account, keyed
on the deterministic ``seed-cad-<project>`` session id its unique column
carries, because the row outlives any one sheet: it must survive a boot that
adds a sheet, and it must reach an install whose sheets are all already there.
"""

from __future__ import annotations

import logging
import math
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BOQ, Position
from app.modules.projects.models import Project
from app.modules.takeoff.models import (
    CadExtractionSession,
    TakeoffDocument,
    TakeoffMeasurement,
)
from app.modules.takeoff.service import recompute_measurement_value
from app.modules.users.models import User
from app.scripts import grundriss_plan as plan

logger = logging.getLogger(__name__)

_FLAGSHIP_ID = uuid.UUID("f1a95000-0001-4a00-8b00-000000000001")

_ASSETS_DIR = Path(__file__).resolve().parents[2] / "scripts" / "flagship_assets"

#: Calibration for the flagship's scanned book plate (``house_plans.pdf``):
#: the printed overall dimension 34'-6" (10.5156 m) measures ~230 PDF points
#: across, i.e. the ratio a user gets by calibrating on that dimension string.
_FLAGSHIP_SCALE = 230.0 / 10.5156

#: The German Grundriss is drawn at M 1:100, so its ratio is exactly the
#: frontend's 1:100 preset value (72 / 0.0254 / 100 PDF points per metre).
_GRUNDRISS_SCALE = plan.PT_PER_M


@dataclass(frozen=True)
class _Spec:
    """One measurement to seed: geometry in viewer coordinates + intent."""

    type: str
    group_name: str
    group_color: str
    annotation: str
    points: list[dict[str, float]]
    unit: str
    depth: Decimal | None = None
    count: int | None = None
    link_patterns: tuple[str, ...] = field(default=())
    #: Normalized position units this measurement's quantity can actually
    #: reach (m + depth -> m2, m2 + depth -> m3, count -> pieces). A text
    #: pattern alone can hit a lump-sum or mismatched-unit line whose
    #: quantity the takeoff figure cannot feed; empty = any unit.
    link_units: tuple[str, ...] = field(default=())


def _ring_perimeter_m(points: list[dict[str, float]], scale: float) -> Decimal | None:
    """Closed-ring perimeter of a polygon in metres (None for degenerate input)."""
    if len(points) < 3 or scale <= 0:
        return None
    total = 0.0
    for i in range(len(points)):
        a = points[i]
        b = points[(i + 1) % len(points)]
        total += math.hypot(b["x"] - a["x"], b["y"] - a["y"])
    return Decimal(str(round(total / scale, 6)))


# ── flagship: honest measurements over the scanned reference plate ──────────
# Viewer coordinates measured off the rendered page (501 x 708 pt, y down from
# the top-left). Rooms follow the plate's own printed labels; values are
# recomputed from these very points, so figure and number agree.


def _flagship_specs() -> list[_Spec]:
    return [
        _Spec(
            "area",
            "Floor areas",
            "#3B82F6",
            "Living room floor",
            [{"x": 176.0, "y": 434.0}, {"x": 305.0, "y": 434.0}, {"x": 305.0, "y": 520.0}, {"x": 176.0, "y": 520.0}],
            "m2",
        ),
        _Spec(
            "area",
            "Floor areas",
            "#3B82F6",
            "Dining room floor",
            [{"x": 309.0, "y": 434.0}, {"x": 395.0, "y": 434.0}, {"x": 395.0, "y": 520.0}, {"x": 309.0, "y": 520.0}],
            "m2",
        ),
        _Spec(
            "area",
            "Floor areas",
            "#3B82F6",
            "Kitchen floor",
            [{"x": 318.0, "y": 345.0}, {"x": 394.0, "y": 345.0}, {"x": 394.0, "y": 406.0}, {"x": 318.0, "y": 406.0}],
            "m2",
        ),
        _Spec(
            "area",
            "Floor areas",
            "#3B82F6",
            "Chamber floor (upper floor, centre)",
            [{"x": 250.0, "y": 166.0}, {"x": 314.0, "y": 166.0}, {"x": 314.0, "y": 248.5}, {"x": 250.0, "y": 248.5}],
            "m2",
        ),
        _Spec(
            "distance",
            "Skirting",
            "#F59E0B",
            "Skirting run - living room, front wall",
            [{"x": 176.0, "y": 520.0}, {"x": 305.0, "y": 520.0}],
            "m",
        ),
        _Spec(
            "distance",
            "Skirting",
            "#F59E0B",
            "Skirting run - dining room, west wall",
            [{"x": 309.0, "y": 434.0}, {"x": 309.0, "y": 520.0}],
            "m",
        ),
        _Spec(
            "count",
            "Doors",
            "#EF4444",
            "Interior doorways (ground floor)",
            [
                {"x": 235.0, "y": 430.0},
                {"x": 312.5, "y": 431.0},
                {"x": 304.0, "y": 361.0},
                {"x": 350.0, "y": 397.5},
                {"x": 344.0, "y": 430.0},
                {"x": 260.0, "y": 521.0},
            ],
            "pcs",
            count=6,
        ),
        _Spec(
            "count",
            "Windows",
            "#8B5CF6",
            "Windows (ground floor)",
            [
                {"x": 176.0, "y": 450.0},
                {"x": 176.0, "y": 495.0},
                {"x": 215.0, "y": 522.5},
                {"x": 280.0, "y": 522.5},
                {"x": 330.0, "y": 524.0},
                {"x": 350.0, "y": 524.0},
                {"x": 370.0, "y": 524.0},
                {"x": 395.0, "y": 475.0},
            ],
            "pcs",
            count=8,
        ),
    ]


# ── German projects: measurements over the vector Grundriss ─────────────────
# All geometry comes from app.scripts.grundriss_plan, the same module the PDF
# is rendered from, so the polygons sit exactly on the drawn rooms. Labels and
# groups are German; link patterns quote the demo packs' own BOQ descriptions.


def _door_markers(rev: plan.Revision, only_t30: bool = False) -> list[dict[str, float]]:
    doors = [d for d in rev.doors if d.t30] if only_t30 else list(rev.doors)
    return plan.viewer_points([(d.cx, rev.door_center_y(d)) for d in doors])


def _window_markers() -> list[dict[str, float]]:
    return plan.viewer_points([(cx, plan.window_wall_center_y(south)) for cx, south in plan.WINDOWS])


def _skirting_ring_1_06(rev: plan.Revision) -> list[dict[str, float]]:
    """Skirting run around Großraumbüro 1.06, open at the door leaf."""
    room = rev.rooms["1.06"]
    door = rev.doors_for("1.06")[0]
    x0, y0 = room.x, room.y
    x1, y1 = room.x + room.w, room.y + room.d
    east_jamb = door.cx + plan.DOOR_W_M / 2.0
    west_jamb = door.cx - plan.DOOR_W_M / 2.0
    return plan.viewer_points([(east_jamb, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0), (west_jamb, y0)])


def _corridor_line(rev: plan.Revision, y_m: float) -> list[dict[str, float]]:
    flur = rev.rooms["1.11"]
    return plan.viewer_points([(flur.x, y_m), (flur.x + flur.w, y_m)])


def _specs_frankfurt(rev: plan.Revision) -> list[_Spec]:
    flur = rev.rooms["1.11"]
    specs = [
        _Spec(
            "area",
            "Bodenplatten",
            "#3B82F6",
            "Bodenplatte EG gesamt (Achse 1-2 / A-D)",
            plan.viewer_points(plan.building_outline_m()),
            "m2",
            depth=Decimal("0.800000"),
            link_patterns=("Bodenplatte%",),
            link_units=("m3",),
        ),
        _Spec(
            "area",
            "Estriche",
            "#10B981",
            "Estrich Flur 1.11",
            plan.viewer_points(rev.room_polygon_m("1.11")),
            "m2",
            link_patterns=("%Estrich%",),
            link_units=("m2",),
        ),
        _Spec(
            "area",
            "Estriche",
            "#10B981",
            "Estrich Büro 1.01",
            plan.viewer_points(rev.room_polygon_m("1.01")),
            "m2",
            link_patterns=("%Estrich%",),
            link_units=("m2",),
        ),
        _Spec(
            "polyline",
            "Sockelleisten",
            "#F59E0B",
            "Sockelleiste Großraumbüro 1.06 (umlaufend)",
            _skirting_ring_1_06(rev),
            "m",
            link_patterns=("%Sockelleisten%",),
            link_units=("m", "lfm"),
        ),
        _Spec(
            "distance",
            "Sockelleisten",
            "#F59E0B",
            "Sockelleiste Flur 1.11, Achse B",
            _corridor_line(rev, flur.y),
            "m",
            link_patterns=("%Sockelleisten%",),
            link_units=("m", "lfm"),
        ),
        _Spec(
            "polyline",
            "Wände",
            "#06B6D4",
            "Trennwand Trockenbau Flur, Achse C (Länge)",
            _corridor_line(rev, rev.corridor_y1 + plan.INT_WALL_M / 2.0),
            "m",
            # Wall length reaches the m2 drywall position only through the
            # wall height: depth carries it (length x height = face area),
            # exactly like the slab's area x depth = volume.
            depth=Decimal("2.750000"),
            link_patterns=("Trennwand Trockenbau%", "%Trockenbau%"),
            link_units=("m2",),
        ),
        _Spec(
            "polyline",
            "Haustechnik",
            "#6366F1",
            "Rohrleitungstrasse Flur bis Technik 1.05",
            plan.viewer_points([(1.2, 6.995), (26.8, 6.995), (26.8, 3.0)]),
            "m",
            link_patterns=("Dämmung Rohrleitungen%",),
            link_units=("m", "lfm"),
        ),
        _Spec(
            "count",
            "Türen",
            "#EF4444",
            "Innentüren EG",
            _door_markers(rev),
            "pcs",
            count=len(rev.doors),
            link_patterns=("%Innentüren%",),
            link_units=_COUNT_UNITS,
        ),
        _Spec(
            "count",
            "Fenster",
            "#8B5CF6",
            "Fenster EG",
            _window_markers(),
            "pcs",
            count=len(plan.WINDOWS),
        ),
    ]
    if rev.demolished_wall_y is not None:
        # Scope this issue brought with it: the corridor wall it moved has to
        # come down first. Measured as its own item because it is new work,
        # which is also why it shows up as an ADDED row in a revision compare
        # instead of quietly changing the length of the wall that stays.
        # Demolition is priced by face area, so depth carries the wall height
        # the same way the drywall run above does.
        specs.append(
            _Spec(
                "distance",
                "Rückbau",
                "#94A3B8",
                "Rückbau Trennwand Flur, Achse C (Lage Index A)",
                _corridor_line(rev, rev.demolished_wall_y),
                "m",
                depth=Decimal("2.750000"),
                link_patterns=("%Rückbau%", "%Abbruch%"),
                link_units=("m2",),
            )
        )
    return specs


def _specs_heilbronn(rev: plan.Revision) -> list[_Spec]:
    flur = rev.rooms["1.11"]
    return [
        _Spec(
            "area",
            "Bodenplatten",
            "#3B82F6",
            "Bodenplatte EG gesamt (Achse 1-2 / A-D)",
            plan.viewer_points(plan.building_outline_m()),
            "m2",
            depth=Decimal("0.200000"),
            link_patterns=("Bodenplatte%",),
            link_units=("m3",),
        ),
        _Spec(
            "area",
            "Dämmung",
            "#14B8A6",
            "XPS-Dämmung unter Bodenplatte",
            plan.viewer_points(plan.building_outline_m(inset=0.17)),
            "m2",
            link_patterns=("XPS-Dämmung%",),
            link_units=("m2",),
        ),
        _Spec(
            "area",
            "Estriche",
            "#10B981",
            "Estrich Flur Sozialtrakt",
            plan.viewer_points(rev.room_polygon_m("1.11")),
            "m2",
            link_patterns=("%Estrich%",),
            link_units=("m2",),
        ),
        _Spec(
            "distance",
            "Sockelleisten",
            "#F59E0B",
            "Rammschutz-Sockelleiste Flur, Achse B",
            _corridor_line(rev, flur.y),
            "m",
            link_patterns=("%Sockelleisten%",),
            link_units=("m", "lfm"),
        ),
        _Spec(
            "polyline",
            "Wände",
            "#06B6D4",
            "Trockenbauwand Sozialtrakt, Achse C (Länge)",
            _corridor_line(rev, rev.corridor_y1 + plan.INT_WALL_M / 2.0),
            "m",
            depth=Decimal("2.750000"),
            link_patterns=("Trockenbauwände%", "%Trockenbau%"),
            link_units=("m2",),
        ),
        _Spec(
            "count",
            "Türen",
            "#EF4444",
            "T30-Türen Technik 1.05 und Lager 1.10",
            _door_markers(rev, only_t30=True),
            "pcs",
            count=sum(1 for d in rev.doors if d.t30),
            link_patterns=("T30%",),
            link_units=_COUNT_UNITS,
        ),
        _Spec(
            "count",
            "Türen",
            "#EF4444",
            "Innentüren Sozialtrakt EG",
            _door_markers(rev),
            "pcs",
            count=len(rev.doors),
            link_patterns=("%Innentüren%",),
            link_units=_COUNT_UNITS,
        ),
    ]


def _specs_heidelberg(rev: plan.Revision) -> list[_Spec]:
    flur = rev.rooms["1.11"]
    return [
        _Spec(
            "area",
            "Bodenplatten",
            "#3B82F6",
            "Bodenplatte EG gesamt (Achse 1-2 / A-D)",
            plan.viewer_points(plan.building_outline_m()),
            "m2",
            depth=Decimal("0.200000"),
            link_patterns=("Bodenplatte%",),
            link_units=("m3",),
        ),
        _Spec(
            "area",
            "Dämmung",
            "#14B8A6",
            "XPS-Dämmung unter Bodenplatte",
            plan.viewer_points(plan.building_outline_m(inset=0.17)),
            "m2",
            link_patterns=("XPS-Dämmung%",),
            link_units=("m2",),
        ),
        _Spec(
            "area",
            "Estriche",
            "#10B981",
            "Estrich Flur Sozialtrakt",
            plan.viewer_points(rev.room_polygon_m("1.11")),
            "m2",
            link_patterns=("%Estrich%",),
            link_units=("m2",),
        ),
        _Spec(
            "distance",
            "Sockelleisten",
            "#F59E0B",
            "Rammschutz-Sockelleiste Flur, Achse B",
            _corridor_line(rev, flur.y),
            "m",
            link_patterns=("%Sockelleisten%",),
            link_units=("m", "lfm"),
        ),
        _Spec(
            "count",
            "Türen",
            "#EF4444",
            "Innentüren Sozialtrakt EG",
            _door_markers(rev),
            "pcs",
            count=len(rev.doors),
            link_patterns=("%Innentüren%",),
            link_units=_COUNT_UNITS,
        ),
    ]


def _grundriss_extracted_text(rev: plan.Revision) -> str:
    rooms = ", ".join(f"{r.label} ({plan.format_area_de(r.area_m2)})" for r in rev.rooms.values())
    changes = "; ".join(f"Index {index}: {note} ({date})" for index, note, date in rev.history)
    return (
        f"Grundriss Erdgeschoss, Plan-Nr. A-2.01, Index {rev.index}, Stand {rev.issued}. "
        f"Maßstab M 1:100. Büro- und Sozialbereich: {rooms}. Alle Maße in m. Änderungen: {changes}."
    )


@dataclass(frozen=True)
class _DocumentPlan:
    """Everything needed to seed one project's takeoff document + rows."""

    #: Stable identity of this document inside the seeder, stamped into
    #: ``metadata.seed_key``. Idempotency is keyed on it rather than on the
    #: file name, so renaming a sheet never re-seeds it as a second document.
    seed_key: str
    source_pdf: str
    filename: str
    scale: float
    scale_source: str
    extracted_text: str
    summary: str
    specs: list[_Spec]
    #: Days between this sheet's issue and now. The document list is served
    #: newest first and the compare drawer offers the newest document as the
    #: target, so the two issues of one sheet must not share a timestamp -
    #: rows written in one transaction all carry the same ``now()``, and the
    #: pair would then order arbitrarily and diff backwards.
    age_days: int = 30
    revision_index: str | None = None


def _flagship_document_plan() -> list[_DocumentPlan]:
    return [
        _DocumentPlan(
            seed_key="flagship-ground-floor",
            source_pdf="house_plans.pdf",
            filename="ground-floor-plan.pdf",
            scale=round(_FLAGSHIP_SCALE, 6),
            scale_source="manual_calibration",
            extracted_text=(
                "Plan of Design No. 2 - reference build plate. Calibrated on the printed 34'-6\" overall "
                "dimension. Room takeoff over the scanned floor plans."
            ),
            summary="Scanned plate calibrated and measured: floors, skirting runs, doors and windows.",
            specs=_flagship_specs(),
        )
    ]


def _german_document_plan(
    rev: plan.Revision,
    specs: list[_Spec],
    *,
    source_pdf: str,
    age_days: int,
) -> _DocumentPlan:
    return _DocumentPlan(
        seed_key=f"grundriss-index-{rev.index.lower()}",
        source_pdf=source_pdf,
        filename=f"A-2.01 Grundriss Erdgeschoss (Index {rev.index}).pdf",
        scale=round(_GRUNDRISS_SCALE, 6),
        scale_source="preset",
        extracted_text=_grundriss_extracted_text(rev),
        summary=(
            f"Grundriss Index {rev.index} ausgewertet: Bodenplatte, Estriche, Trennwände, "
            "Sockelleisten, Türen und Fenster."
        ),
        specs=specs,
        age_days=age_days,
        revision_index=rev.index,
    )


def _grundriss_index_a(specs: Callable[[plan.Revision], list[_Spec]]) -> _DocumentPlan:
    return _german_document_plan(
        plan.REVISION_A,
        specs(plan.REVISION_A),
        source_pdf="grundriss_erdgeschoss.pdf",
        age_days=30,
    )


def _plans_frankfurt() -> list[_DocumentPlan]:
    """Both issues of sheet A-2.01, so the revision compare has real input.

    The shoot project carries the pair the compare screen needs: index A is
    the sheet the takeoff was built on, index B the reissue that widened the
    corridor. Same rooms, same measurement names - so a compare matches them
    up and reports the handful of quantities that really moved.
    """
    return [
        _grundriss_index_a(_specs_frankfurt),
        _german_document_plan(
            plan.REVISION_B,
            _specs_frankfurt(plan.REVISION_B),
            source_pdf="grundriss_erdgeschoss_index_b.pdf",
            age_days=3,
        ),
    ]


#: German demo projects that receive the Grundriss, keyed by project name
#: (demo installs mint random project ids, so the stable key is the name).
_GERMAN_PROJECT_PLANS: dict[str, Callable[[], list[_DocumentPlan]]] = {
    "Bürogebäude Frankfurt Europaviertel": _plans_frankfurt,
    "Lebensmittelmarkt Heilbronn": lambda: [_grundriss_index_a(_specs_heilbronn)],
    "Lebensmittelmarkt Heidelberg": lambda: [_grundriss_index_a(_specs_heidelberg)],
}


async def _resolve_owner_id(session: AsyncSession, project_id: uuid.UUID) -> uuid.UUID | None:
    """Resolve a valid owner user id for the takeoff document.

    Prefers the owner of the target project (the demo user installed alongside
    it); falls back to any existing user. Returns None when the users table is
    empty, in which case the caller skips seeding.
    """
    owner_id = (await session.execute(select(Project.owner_id).where(Project.id == project_id))).scalar_one_or_none()
    if owner_id is not None:
        return owner_id
    return (await session.execute(select(User.id).limit(1))).scalar_one_or_none()


def _position_is_priced(unit: str | None, unit_rate: str | None) -> bool:
    """True for a real, priced line item (vs. a section heading or unpriced tender row)."""
    if not (unit or "").strip():
        return False
    try:
        return Decimal(str(unit_rate)) > 0
    except (InvalidOperation, TypeError, ValueError):
        return False


def _normalize_unit(unit: str | None) -> str:
    """Canonical lowercase unit token for compatibility checks (m² -> m2)."""
    return (unit or "").strip().lower().replace("²", "2").replace("³", "3")


#: Normalized piece-count unit spellings across the demo packs (German LVs
#: write "St"/"Stk"/"Stück", international packs "pcs").
_COUNT_UNITS = ("pcs", "st", "stk", "stück")


async def _resolve_position_id(
    session: AsyncSession,
    project_id: uuid.UUID,
    patterns: tuple[str, ...],
    link_units: tuple[str, ...] = (),
) -> str | None:
    """Find a really-seeded BOQ position of this project matching a pattern.

    Patterns are tried in order (most specific first); within a pattern the
    first PRICED line item wins, deterministically via (ordinal, id). A demo
    project can carry several BOQs - the priced works LV plus unpriced tender
    LVs and cost plans whose section headings reuse the same German trade
    vocabulary - and ``Position.ordinal`` is a string, so "01.03.0020" sorts
    before "320.2" and an unpriced tender row would shadow the priced position
    the showcase hands its quantity to. A heading (empty unit) never wins; an
    unpriced-but-real position is kept only as a fallback within its pattern.

    ``link_units`` (normalized) restricts candidates to positions whose unit
    the measurement's quantity can actually reach: a doors count matched a
    priced lump-sum line ("Innenausbau ... Innentüren", unit LS) by text, and
    a piece count cannot feed a lump sum. An incompatible unit is worse than
    no link, so with no compatible candidate the measurement stays unlinked.
    """
    for pattern in patterns:
        stmt = (
            select(Position.id, Position.unit, Position.unit_rate)
            .join(BOQ, Position.boq_id == BOQ.id)
            .where(BOQ.project_id == project_id, Position.description.ilike(pattern))
            .order_by(Position.ordinal, Position.id)
        )
        rows = (await session.execute(stmt)).all()
        fallback: str | None = None
        for position_id, unit, unit_rate in rows:
            if link_units and _normalize_unit(unit) not in link_units:
                continue
            if _position_is_priced(unit, unit_rate):
                return str(position_id)
            if fallback is None and (unit or "").strip():
                fallback = str(position_id)
        if fallback is not None:
            return fallback
    return None


def _is_seeded_document(document: TakeoffDocument) -> bool:
    """True for a document this seeder wrote (never for a user's upload).

    A row opened from Project Files is excluded on its source id as well as on
    the marker: adoption re-copies the fixture over the file it names, so a row
    whose bytes came from somewhere else must never qualify, even if a future
    change lets the upload path carry a source document's metadata across.
    """
    meta = document.metadata_
    return isinstance(meta, dict) and meta.get("seed") is True and document.source_document_id is None


def _seed_key_of(document: TakeoffDocument) -> str | None:
    """The document's seed identity, or None for a row that predates it."""
    meta = document.metadata_ if isinstance(document.metadata_, dict) else {}
    return str(meta.get("seed_key") or "").strip() or None


def _adopt_legacy_document(document: TakeoffDocument, doc_plan: _DocumentPlan) -> None:
    """Bring a document seeded before the sheet carried an index up to date.

    Earlier installs seeded one unindexed sheet per project. That row IS this
    plan's document (same project, same drawing, same measurements), so it is
    renamed and re-served from the current fixture rather than left beside a
    second copy: two rows for one sheet would show up in the compare drawer as
    two revisions with an empty diff, and a row whose name promises an index
    its bytes do not carry is the defect one drawer away.
    """
    source_pdf = _ASSETS_DIR / doc_plan.source_pdf
    if document.file_path and source_pdf.exists():
        dest = Path(document.file_path)
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_pdf, dest)
            document.size_bytes = dest.stat().st_size
        except OSError:
            logger.warning("takeoff seed: could not refresh %s from %s", document.file_path, source_pdf)
    document.filename = doc_plan.filename
    document.extracted_text = doc_plan.extracted_text
    document.metadata_ = {
        **(document.metadata_ if isinstance(document.metadata_, dict) else {}),
        "seed_key": doc_plan.seed_key,
        **({"revision_index": doc_plan.revision_index} if doc_plan.revision_index else {}),
    }


async def _prune_documentless_demo_rows(session: AsyncSession) -> int:
    """Delete legacy demo measurements that have no document behind them.

    Older demo installs minted 4 rows per project straight from BOQ items
    (``metadata.source == "boq_derived"``) with no document, no points and no
    scale - list entries that break the moment they are opened on a sheet.
    Only rows carrying that exact demo marker are touched; user rows never
    match it.
    """
    rows = (
        await session.execute(
            select(TakeoffMeasurement.id, TakeoffMeasurement.metadata_).where(TakeoffMeasurement.document_id.is_(None))
        )
    ).all()
    stale = [row_id for row_id, meta in rows if isinstance(meta, dict) and meta.get("source") == "boq_derived"]
    if stale:
        await session.execute(delete(TakeoffMeasurement).where(TakeoffMeasurement.id.in_(stale)))
    return len(stale)


async def _seed_project_document(
    session: AsyncSession,
    project_id: uuid.UUID,
    owner_id: uuid.UUID,
    doc_plan: _DocumentPlan,
) -> dict[str, int]:
    """Seed one project's document + measurements. Returns per-entity counts."""
    from app.modules.takeoff.service import _takeoff_documents_dir

    counts = {"documents": 0, "measurements": 0, "linked": 0}

    # --- the takeoff document, backed by a REAL PDF on disk ---
    # The viewer streams the file from GET /takeoff/documents/{id}/download/,
    # which 404s unless an actual PDF exists under the takeoff documents
    # directory. The id is generated up front so the on-disk file name matches
    # the row, exactly like a real upload.
    doc_uuid = uuid.uuid4()
    source_pdf = _ASSETS_DIR / doc_plan.source_pdf
    pages = 1
    size_bytes = 0
    file_path = ""
    if source_pdf.exists():
        documents_dir = _takeoff_documents_dir()
        documents_dir.mkdir(parents=True, exist_ok=True)
        dest_pdf = documents_dir / f"{doc_uuid}.pdf"
        shutil.copyfile(source_pdf, dest_pdf)
        size_bytes = dest_pdf.stat().st_size
        file_path = str(dest_pdf)
        try:
            import fitz  # PyMuPDF - already a takeoff dependency

            with fitz.open(dest_pdf) as opened:
                pages = max(1, opened.page_count)
        except Exception:  # noqa: BLE001 - page count is cosmetic, never fatal
            pages = 1
    else:
        logger.warning("takeoff seed: reference PDF missing at %s", source_pdf)

    document = TakeoffDocument(
        id=doc_uuid,
        filename=doc_plan.filename,
        pages=pages,
        size_bytes=size_bytes,
        content_type="application/pdf",
        status="analyzed",
        project_id=project_id,
        owner_id=owner_id,
        file_path=file_path,
        created_at=datetime.now(UTC) - timedelta(days=doc_plan.age_days),
        extracted_text=doc_plan.extracted_text,
        page_data=[{"page": n, "text": doc_plan.filename, "tables": []} for n in range(1, pages + 1)],
        analysis={"summary": doc_plan.summary, "trades": ["concrete", "drywall", "flooring", "doors", "windows"]},
        # The frontend counts only pages present in ``byPage`` as calibrated
        # (``pageIsCalibrated`` in pdf-takeoff/data/page-scales.ts); a seeded
        # document presented as analyzed and measured must not greet the user
        # with a "Not calibrated" badge, so page 1 carries its own entry.
        page_scales={
            "defaultScale": {"pixelsPerUnit": doc_plan.scale, "unitLabel": "m"},
            "byPage": {"1": {"pixelsPerUnit": doc_plan.scale, "unitLabel": "m"}},
        },
        metadata_={
            "seed": True,
            "demo": True,
            "scale": "1:100",
            "seed_key": doc_plan.seed_key,
            **({"revision_index": doc_plan.revision_index} if doc_plan.revision_index else {}),
        },
    )
    session.add(document)
    await session.flush()
    # Capture the generated id locally (never read document.measurements - a
    # lazy relationship would raise MissingGreenlet under async).
    document_id = str(document.id)
    counts["documents"] = 1

    owner_ref = str(owner_id)
    for spec in doc_plan.specs:
        # The value is DERIVED from the seeded geometry through the same
        # function the API uses - figure and number cannot disagree.
        raw_value = recompute_measurement_value(
            measurement_type=spec.type,
            points=spec.points,
            scale_pixels_per_unit=doc_plan.scale,
            count_value=spec.count,
            client_value=None,
        )
        value = Decimal(str(round(raw_value, 6))) if raw_value is not None else None
        volume = None
        if spec.depth is not None and value is not None:
            volume = (value * spec.depth).quantize(Decimal("0.000001"))
        perimeter = _ring_perimeter_m(spec.points, doc_plan.scale) if spec.type == "area" else None

        linked_position_id = None
        if spec.link_patterns:
            linked_position_id = await _resolve_position_id(session, project_id, spec.link_patterns, spec.link_units)
            if linked_position_id is not None:
                counts["linked"] += 1

        measurement = TakeoffMeasurement(
            project_id=project_id,
            document_id=document_id,
            page=1,
            type=spec.type,
            group_name=spec.group_name,
            group_color=spec.group_color,
            annotation=spec.annotation,
            points=spec.points,
            measurement_value=value,
            measurement_unit=spec.unit,
            depth=spec.depth,
            volume=volume,
            perimeter=perimeter,
            count_value=spec.count,
            scale_pixels_per_unit=doc_plan.scale,
            scale_source=doc_plan.scale_source,
            linked_boq_position_id=linked_position_id,
            metadata_={"seed": True, "demo": True},
            created_by=owner_ref,
        )
        session.add(measurement)
        counts["measurements"] += 1

    return counts


#: How long the seeded CAD extraction session stays readable. The showcase row
#: is a fixture rather than somebody's working upload, so it is minted with the
#: same far-future expiry the two "keep this session" endpoints write
#: (``cad_data_save`` and ``takeoff_save_session_to_project``, both
#: ``now + 365 * 10 days``). The seed used to pair ``is_permanent=True`` with a
#: seven-day ``expires_at``, and the two readers disagree about which column
#: decides: the list query exempts a permanent row from the expiry test, the
#: single-session read does not. A week after the row was written the workspace
#: therefore still listed the extraction and returned nothing when it was
#: opened.
_CAD_SESSION_LIFETIME = timedelta(days=365 * 10)


async def _existing_cad_session(session: AsyncSession, session_id: str) -> CadExtractionSession | None:
    """The seeded CAD session row of this id, or None.

    The idempotency guard of the seeder below, and the one question that
    decides whether it writes. Kept separate because it is also the seam the
    race is reached through: a check that answers "not there" against a
    database that holds the row puts the caller in exactly the position the
    loser of two simultaneous boots is in.
    """
    return (
        await session.execute(select(CadExtractionSession).where(CadExtractionSession.session_id == session_id))
    ).scalar_one_or_none()


async def _seed_flagship_cad_session(session: AsyncSession, project_id: uuid.UUID) -> int:
    """Seed the flagship's CAD extraction session, once.

    Guarded on the session id itself rather than on the documents seeded beside
    it. ``session_id`` is deterministic (``seed-cad-<project>``) and its column
    is unique, so the unguarded insert this replaces raised a unique violation
    on every boot that found the row already there. Because the whole seeder
    shares one transaction and the caller swallows the exception, that took the
    documents, the measurements and the prune of the same run down with it, and
    left the state that produced the failure in place for the next boot.

    Existence check plus a SAVEPOINT rather than an upsert: the check is the
    shape the sibling seeders in this tree already use and it reads as the
    intent ("a row that is there is not written again"), while the SAVEPOINT
    covers the one case the check cannot, two workers booting at the same
    moment and both missing. A dialect-specific ``ON CONFLICT DO NOTHING``
    would have to be a Core insert, which means spelling out by hand every
    default ``session.add`` supplies here (the primary key, both timestamps and
    the two JSON columns).

    Args:
        session: Open async DB session.
        project_id: The flagship project, whose id the session id is built from.

    Returns:
        1 when a row was written, 0 when one was already there or no owner user
        could be resolved.
    """
    session_id = f"seed-cad-{project_id}"
    existing = await _existing_cad_session(session, session_id)
    now = datetime.now(UTC)
    if existing is not None:
        # Heal a row minted with the old seven-day expiry, which the workspace
        # lists and then cannot open. Only this seeder's own row is touched,
        # and only when its expiry has already passed, so an ordinary re-boot
        # writes nothing at all.
        stored = existing.expires_at
        if stored is not None and stored.tzinfo is None:
            stored = stored.replace(tzinfo=UTC)
        if stored is None or stored <= now:
            existing.expires_at = now + _CAD_SESSION_LIFETIME
            existing.is_permanent = True
            logger.info("takeoff seed: refreshed the expiry of CAD session %s", session_id)
        return 0

    owner_id = await _resolve_owner_id(session, project_id)
    if owner_id is None:
        logger.info("takeoff CAD session seed skipped for %s: no owner user available", project_id)
        return 0

    owner_ref = str(owner_id)
    # Flush the documents and measurements added earlier in this run before the
    # SAVEPOINT opens, so they sit outside it and a lost race here costs this
    # row alone.
    await session.flush()
    try:
        async with session.begin_nested():
            session.add(
                CadExtractionSession(
                    session_id=session_id,
                    user_id=owner_ref,
                    filename="structure.ifc",
                    file_format="ifc",
                    element_count=6,
                    extraction_time=2.4,
                    elements_data=[
                        {"id": "elem_001", "category": "wall", "area_m2": 84.3},
                        {"id": "elem_002", "category": "slab", "area_m2": 92.6},
                    ],
                    columns_metadata={"category": "string", "area_m2": "number"},
                    project_id=str(project_id),
                    display_name="Structure (IFC) extraction",
                    is_permanent=True,
                    expires_at=now + _CAD_SESSION_LIFETIME,
                    created_by=owner_ref,
                    session_ttl_days=None,
                    is_persistent=True,
                    bim_model_id=None,
                )
            )
            await session.flush()
    except IntegrityError:
        # A worker booting alongside this one won the unique index. The row it
        # wrote is the row this one wanted, so there is nothing left to do.
        # Catching it is not enough on its own: a failed statement aborts the
        # whole transaction, which is why the insert sits in a SAVEPOINT.
        logger.info("takeoff seed: CAD session %s was written by a concurrent boot", session_id)
        return 0
    return 1


async def seed_takeoff_demo(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
) -> dict[str, int]:
    """Seed demo takeoff documents, measurements and a CAD session.

    Args:
        session: Open async DB session.
        project_ids: Candidate projects. The flagship project and the German
            showcase projects (matched by name) each receive their own
            documents - two on the shoot project, one everywhere else - and a
            document already seeded is skipped. The flagship also receives one
            CAD extraction session, guarded separately on its own session id.

    Returns:
        A dict of row counts per entity inserted (plus ``linked``, ``pruned``
        and ``adopted``), or an empty dict when nothing was done.
    """
    if not project_ids:
        return {}

    counts: dict[str, int] = {
        "documents": 0,
        "measurements": 0,
        "linked": 0,
        "cad_sessions": 0,
        "pruned": 0,
        "adopted": 0,
    }

    # Heal older installs: demo rows without a document cannot be shown on any
    # sheet, so they go before new documents arrive.
    counts["pruned"] = await _prune_documentless_demo_rows(session)

    # Resolve seed targets: the flagship by id, German projects by name.
    targets: list[tuple[uuid.UUID, list[_DocumentPlan]]] = []
    if _FLAGSHIP_ID in project_ids:
        targets.append((_FLAGSHIP_ID, _flagship_document_plan()))
    name_rows = (
        await session.execute(
            select(Project.id, Project.name).where(
                Project.id.in_(project_ids), Project.name.in_(list(_GERMAN_PROJECT_PLANS))
            )
        )
    ).all()
    for pid, name in name_rows:
        targets.append((pid, _GERMAN_PROJECT_PLANS[name]()))

    for project_id, doc_plans in targets:
        existing = list(
            (await session.execute(select(TakeoffDocument).where(TakeoffDocument.project_id == project_id)))
            .scalars()
            .all()
        )
        # Idempotency is per DOCUMENT, keyed on ``metadata.seed_key``: a
        # project that already carries every sheet of its plan is done, and a
        # project that carries only the first one (an install that predates
        # the second issue) gets the missing sheet without duplicating what is
        # already there. A document this seeder did not write means a user has
        # taken the project over - it is left alone entirely.
        if any(not _is_seeded_document(doc) for doc in existing):
            continue
        seeded_keys = {key for doc in existing if (key := _seed_key_of(doc)) is not None}
        legacy = [doc for doc in existing if _seed_key_of(doc) is None]
        if legacy and doc_plans[0].seed_key not in seeded_keys:
            _adopt_legacy_document(legacy[0], doc_plans[0])
            seeded_keys.add(doc_plans[0].seed_key)
            counts["adopted"] += 1
        pending = [doc_plan for doc_plan in doc_plans if doc_plan.seed_key not in seeded_keys]
        if pending:
            owner_id = await _resolve_owner_id(session, project_id)
            if owner_id is None:
                logger.info("takeoff seed skipped for %s: no owner user available", project_id)
            else:
                for doc_plan in pending:
                    project_counts = await _seed_project_document(session, project_id, owner_id, doc_plan)
                    for key, num in project_counts.items():
                        counts[key] += num

        # --- 1 CAD extraction session (flagship only) ---
        # Reached whether or not a sheet was pending. The row carries its own
        # guard, so an install holding every sheet still receives the session it
        # never got, and one holding the session is not asked to insert it a
        # second time when a new sheet arrives. The user-takeover bail-out above
        # still covers it: a project somebody has taken over is skipped before
        # this line.
        if project_id == _FLAGSHIP_ID:
            counts["cad_sessions"] += await _seed_flagship_cad_session(session, project_id)

    await session.flush()
    if any(counts.values()):
        logger.info("takeoff demo seed inserted: %s", counts)
        return counts
    return {}
