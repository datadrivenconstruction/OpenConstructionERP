# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit-factor inference + lazy backfill tests for the dwg_takeoff module.

Covers BUG-D-TKC-002c: a DWG/DXF authored in millimetres but with no
usable ``$INSUNITS`` was stored with ``units == null`` ("unitless"), which
forced a 1.0 scale factor and made measurements read 1000x too large
(a 32 533 mm distance shown as "32 533 m").

The fix infers the unit from the drawing's extent (a >=1000-unit plan is
almost certainly in mm) at parse time, on the read path (lazy backfill for
already-seeded drawings), and as a frontend belt-and-suspenders.

Tested here (backend):

1. ``infer_units_from_extents`` — "mm" for large extents, ``None`` for
   small / empty / missing / zero / degenerate extents.
2. ``_extents_from_raw_entities`` — recovers a bounding box from stored
   entity records.
3. ``get_latest_version`` lazy backfill — a version seeded with
   ``units=null`` and ``extents={}`` but with entities on disk is
   backfilled to ``units="mm"`` and the extents persisted.
4. ``_push_quantity_to_position`` — copies the annotation's value into the
   BOQ position unchanged (the value is already real-world metres) and a
   ``None`` value never zeroes an existing quantity.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from decimal import Decimal
from pathlib import Path

# ── Per-module temp data dir (MUST run BEFORE app imports) ────────────────
_PREVIOUS_DATA_DIR = os.environ.get("DATA_DIR")
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-dwg-units-"))
os.environ["DATA_DIR"] = str(_TMP_DIR)

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

# Ensure ORM registration before the schema is materialised.
import app.modules.boq.models  # noqa: E402, F401
import app.modules.dwg_takeoff.models  # noqa: E402, F401
import app.modules.projects.models  # noqa: E402, F401
import app.modules.users.models  # noqa: E402, F401
from app.modules.dwg_takeoff.ddc_dwg_parser import infer_units_from_extents  # noqa: E402
from app.modules.dwg_takeoff.models import (  # noqa: E402
    DwgAnnotation,
    DwgDrawing,
    DwgDrawingVersion,
)
from app.modules.dwg_takeoff.service import (  # noqa: E402
    DwgTakeoffService,
    _extents_from_raw_entities,
    _get_entities_dir,
)

# Put it back. DATA_DIR is process wide and only the import above reads it, so
# left set it answers every later module that asks resolve_data_dir() where the
# platform writes, and the failure surfaces in whichever unrelated test asks.
if _PREVIOUS_DATA_DIR is None:
    os.environ.pop("DATA_DIR", None)
else:
    os.environ["DATA_DIR"] = _PREVIOUS_DATA_DIR

from tests._pg import transactional_session  # noqa: E402

pytestmark = pytest.mark.asyncio


# ── 1. infer_units_from_extents (pure, no DB) ─────────────────────────────


def test_infer_units_mm_for_large_extents() -> None:
    """A drawing whose largest extent is >= 1000 units is millimetres."""
    extents = {"min_x": 0.0, "min_y": 0.0, "max_x": 32533.0, "max_y": 18000.0}
    assert infer_units_from_extents(extents) == "mm"


def test_infer_units_mm_at_exact_threshold() -> None:
    """Exactly 1000 units crosses the millimetre threshold."""
    extents = {"min_x": 0.0, "min_y": 0.0, "max_x": 1000.0, "max_y": 500.0}
    assert infer_units_from_extents(extents) == "mm"


def test_infer_units_none_for_small_extents() -> None:
    """A small (< 1000-unit) drawing keeps the metres assumption (None)."""
    extents = {"min_x": 0.0, "min_y": 0.0, "max_x": 32.5, "max_y": 18.0}
    assert infer_units_from_extents(extents) is None


def test_infer_units_none_for_empty_or_missing() -> None:
    """Missing / empty / partial / zero extents return None (no guess)."""
    assert infer_units_from_extents(None) is None
    assert infer_units_from_extents({}) is None
    assert infer_units_from_extents({"min_x": 0.0, "max_x": 5000.0}) is None
    assert infer_units_from_extents({"min_x": 0.0, "min_y": 0.0, "max_x": 0.0, "max_y": 0.0}) is None


def test_infer_units_handles_negative_origin() -> None:
    """Width is computed as a span, so a negative origin still measures big."""
    extents = {"min_x": -5000.0, "min_y": -2000.0, "max_x": 5000.0, "max_y": 2000.0}
    assert infer_units_from_extents(extents) == "mm"


# ── 2. _extents_from_raw_entities (pure, no DB) ───────────────────────────


def test_extents_from_raw_entities_line_and_polyline() -> None:
    """Bounding box spans line endpoints and polyline vertices."""
    raw = [
        {
            "entity_type": "LINE",
            "geometry_data": {"start": {"x": 0, "y": 0}, "end": {"x": 5000, "y": 4000}},
        },
        {
            "entity_type": "LWPOLYLINE",
            "geometry_data": {"points": [{"x": 100, "y": 200}, {"x": 5500, "y": 100}]},
        },
    ]
    box = _extents_from_raw_entities(raw)
    assert box == {"min_x": 0.0, "min_y": 0.0, "max_x": 5500.0, "max_y": 4000.0}


def test_extents_from_raw_entities_empty() -> None:
    """No coordinates → None."""
    assert _extents_from_raw_entities([]) is None
    assert _extents_from_raw_entities([{"entity_type": "TEXT", "geometry_data": {}}]) is None


# ── DB fixtures / seed helpers ────────────────────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Isolated PostgreSQL session per test (rolled back on teardown)."""
    async with transactional_session() as sess:
        yield sess


async def _seed_project(session: AsyncSession) -> uuid.UUID:
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(
        email=f"dwg-units-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="DWG Units Tester",
    )
    session.add(user)
    await session.flush()
    project = Project(name="DWG Units Test Project", owner_id=user.id)
    session.add(project)
    await session.flush()
    return project.id


def _write_entities(version_id: uuid.UUID, raw_entities: list[dict]) -> str:
    """Persist raw entity records to the on-disk store and return the key."""
    key = f"{version_id}/entities.json"
    path = os.path.join(_get_entities_dir(), key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(raw_entities, f)
    return key


# ── 3. Lazy backfill on the read path ─────────────────────────────────────


async def test_get_latest_version_backfills_units_from_entities(session: AsyncSession) -> None:
    """A seeded mm drawing (units=null, extents={}) is backfilled to mm.

    Mirrors the flagship demo: the version row carries no unit and no
    extents, but its entities exist on disk. Reading the drawing must
    recover extents, infer mm and persist both onto the row.
    """
    project_id = await _seed_project(session)
    drawing = DwgDrawing(
        project_id=project_id,
        name="Flagship plan",
        filename="plan.dwg",
        file_format="dwg",
        file_path="x/plan.dwg",
        status="ready",
    )
    session.add(drawing)
    await session.flush()
    drawing_id = drawing.id  # capture before the backfill expires the session

    version = DwgDrawingVersion(
        drawing_id=drawing.id,
        version_number=1,
        layers=[],
        entity_count=2,
        extents={},  # seeded with NO extents
        units=None,  # seeded with NO unit
        status="ready",
    )
    session.add(version)
    await session.flush()

    # A clearly-millimetre drawing: ~32.5 m span stored as 32 533 units.
    raw_entities = [
        {
            "entity_type": "LINE",
            "geometry_data": {
                "start": {"x": 0, "y": 0},
                "end": {"x": 32533, "y": 0},
            },
        },
        {
            "entity_type": "LWPOLYLINE",
            "geometry_data": {
                "points": [{"x": 0, "y": 0}, {"x": 0, "y": 18000}],
            },
        },
    ]
    version.entities_key = _write_entities(version.id, raw_entities)
    await session.flush()

    service = DwgTakeoffService(session)
    result = await service.get_latest_version(drawing_id)

    assert result is not None
    assert result.units == "mm"
    assert result.extents.get("max_x") == 32533.0
    assert result.extents.get("max_y") == 18000.0

    # And it is persisted: a fresh read sees the backfilled values.
    refetched = await service.version_repo.get_latest_for_drawing(drawing_id)
    assert refetched is not None
    assert refetched.units == "mm"


async def test_get_latest_version_leaves_known_units_alone(session: AsyncSession) -> None:
    """A version whose unit is already resolved is never touched."""
    project_id = await _seed_project(session)
    drawing = DwgDrawing(
        project_id=project_id,
        name="Metric plan",
        filename="plan.dxf",
        file_format="dxf",
        file_path="x/plan.dxf",
        status="ready",
    )
    session.add(drawing)
    await session.flush()
    version = DwgDrawingVersion(
        drawing_id=drawing.id,
        version_number=1,
        layers=[],
        entity_count=0,
        extents={"min_x": 0.0, "min_y": 0.0, "max_x": 50000.0, "max_y": 50000.0},
        units="m",  # explicitly metres — do NOT override with the mm guess
        status="ready",
    )
    session.add(version)
    await session.flush()

    service = DwgTakeoffService(session)
    result = await service.get_latest_version(drawing.id)
    assert result is not None
    assert result.units == "m"


# ── 4. BOQ push preserves the (already-scaled) value ──────────────────────


async def _seed_boq_position(
    session: AsyncSession, project_id: uuid.UUID, *, unit: str, qty: str = "0", rate: str = "10"
):
    from app.modules.boq.models import BOQ, Position

    boq = BOQ(project_id=project_id, name="Test BOQ")
    session.add(boq)
    await session.flush()
    position = Position(
        boq_id=boq.id,
        ordinal="01.001",
        description="Test position",
        unit=unit,
        quantity=qty,
        unit_rate=rate,
        total="0",
    )
    session.add(position)
    await session.flush()
    return position


async def _make_annotation(
    session: AsyncSession,
    project_id: uuid.UUID,
    drawing_id: uuid.UUID,
    *,
    annotation_type: str,
    value,
) -> DwgAnnotation:
    ann = DwgAnnotation(
        project_id=project_id,
        drawing_id=drawing_id,
        annotation_type=annotation_type,
        geometry={"points": []},
        measurement_value=value,
    )
    session.add(ann)
    await session.flush()
    return ann


async def test_push_quantity_copies_distance_value(session: AsyncSession) -> None:
    """A distance annotation's metres value lands on the BOQ quantity as-is.

    The frontend stores ``measurement_value`` already in real-world metres
    (extractEntityMeasurement multiplies by the unit factor before sending),
    so the push must NOT re-scale: 32.533 m in → 32.533 quantity out.
    """
    project_id = await _seed_project(session)
    drawing = DwgDrawing(
        project_id=project_id,
        name="d",
        filename="d.dwg",
        file_format="dwg",
        file_path="x",
        status="ready",
    )
    session.add(drawing)
    await session.flush()

    position = await _seed_boq_position(session, project_id, unit="m", rate="10")
    position_id = position.id  # capture before the push expires the session
    ann = await _make_annotation(
        session,
        project_id,
        drawing.id,
        annotation_type="distance",
        value=Decimal("32.533"),
    )

    service = DwgTakeoffService(session)
    await service._push_quantity_to_position(str(position_id), ann)  # noqa: SLF001

    from app.modules.boq.service import BOQService

    refetched = await BOQService(session).position_repo.get_by_id(position_id)
    assert refetched is not None
    assert Decimal(refetched.quantity) == Decimal("32.533")
    # total = qty × rate is recomputed via the canonical BOQ path.
    assert Decimal(refetched.total) == Decimal("325.33")


async def test_push_quantity_none_value_is_noop(session: AsyncSession) -> None:
    """A value-less annotation never zeroes the existing BOQ quantity."""
    project_id = await _seed_project(session)
    drawing = DwgDrawing(
        project_id=project_id,
        name="d",
        filename="d.dwg",
        file_format="dwg",
        file_path="x",
        status="ready",
    )
    session.add(drawing)
    await session.flush()

    position = await _seed_boq_position(session, project_id, unit="m", qty="7", rate="10")
    position_id = position.id  # capture before the push expires the session
    ann = await _make_annotation(session, project_id, drawing.id, annotation_type="distance", value=None)

    service = DwgTakeoffService(session)
    await service._push_quantity_to_position(str(position_id), ann)  # noqa: SLF001

    from app.modules.boq.service import BOQService

    refetched = await BOQService(session).position_repo.get_by_id(position_id)
    assert refetched is not None
    assert Decimal(refetched.quantity) == Decimal("7")  # untouched
