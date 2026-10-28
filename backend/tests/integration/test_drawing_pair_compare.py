# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for the drawing-vs-drawing compare (discussion #289).

The revision compare shipped as version-vs-version of ONE drawing. This
covers the new drawing-PAIR path that diffs the latest version of two
INDEPENDENTLY uploaded drawings (the user picks or uploads a second drawing
as the comparison target), mirroring the PDF module's two-document compare:

* ``DwgTakeoffService.compare_drawing_pair`` runs the shared diff core over
  the latest version of each drawing WITHOUT the same-drawing guard and
  returns a payload that additionally carries ``from_drawing_id`` /
  ``to_drawing_id``.
* When two independently uploaded drawings share a stable annotation
  ``compare_key`` linked to a priced BOQ position, the value change is
  priced through the same path (proving ``_compute_annotation_delta`` is
  wired identically).
* Cross-project safety: a drawing in ANOTHER project is never diffed
  against (404), so a compare never crosses tenants or blends currencies.
* ``create_variation_from_drawing_pair`` mints a DRAFT variation with
  ``source=dwg_drawing_pair_compare`` provenance.

Test isolation (``feedback_test_isolation.md``): the per-session PostgreSQL
database + eager model registration + synchronous event-bus shim come from
``backend/tests/conftest.py``; the production database is never touched.

Run:
    cd backend
    python -m pytest tests/integration/test_drawing_pair_compare.py -v --tb=short
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio

from app.database import async_session_factory


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _schema():
    """Create every table this suite touches on the shared test engine."""
    import app.modules.boq.models  # noqa: F401
    import app.modules.dwg_takeoff.models  # noqa: F401
    import app.modules.projects.models  # noqa: F401
    import app.modules.takeoff.models  # noqa: F401
    import app.modules.users.models  # noqa: F401
    import app.modules.variations.models  # noqa: F401
    from app.database import Base, engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


# ── Direct row seeding (no upload endpoint -> deterministic, no parsing) ──


async def _seed_user() -> uuid.UUID:
    from app.modules.users.models import User

    async with async_session_factory() as session:
        user = User(
            email=f"pair-{uuid.uuid4().hex[:10]}@test.io",
            hashed_password="x",
            full_name="Pair Compare Tester",
            role="manager",
            is_active=True,
        )
        session.add(user)
        await session.flush()
        uid = user.id
        await session.commit()
        return uid


async def _seed_project(owner_id: uuid.UUID, *, currency: str = "EUR") -> uuid.UUID:
    from app.modules.projects.models import Project

    async with async_session_factory() as session:
        project = Project(
            name="Pair compare project",
            region="DACH",
            classification_standard="din276",
            currency=currency,
            owner_id=owner_id,
        )
        session.add(project)
        await session.flush()
        pid = project.id
        await session.commit()
        return pid


async def _seed_boq_position(
    project_id: uuid.UUID,
    *,
    unit_rate: str,
    quantity: str = "0",
) -> uuid.UUID:
    """Insert a BOQ + one priced Position, return the position id."""
    from app.modules.boq.models import BOQ, Position

    async with async_session_factory() as session:
        boq = BOQ(project_id=project_id, name="Pair BOQ", status="draft")
        session.add(boq)
        await session.flush()
        pos = Position(
            boq_id=boq.id,
            ordinal="01.001",
            description="Concrete wall",
            unit="m2",
            quantity=quantity,
            unit_rate=unit_rate,
            total="0",
        )
        session.add(pos)
        await session.flush()
        pid = pos.id
        await session.commit()
        return pid


async def _seed_drawing_one_version(
    project_id: uuid.UUID,
    *,
    name: str,
    layers: list[dict],
    entity_count: int,
    annotation_value: str | None = None,
    compare_key: str | None = None,
    linked_position_id: uuid.UUID | None = None,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Insert a drawing with ONE parsed version (+ an optional annotation).

    Returns ``(drawing_id, version_id)``. When ``annotation_value`` is set
    a single area annotation is stamped on the version, optionally carrying
    a ``compare_key`` (so two drawings can match a logical item) and a BOQ
    link (so the change is priced).
    """
    from app.modules.dwg_takeoff.models import (
        DwgAnnotation,
        DwgDrawing,
        DwgDrawingVersion,
    )

    async with async_session_factory() as session:
        drawing = DwgDrawing(
            project_id=project_id,
            name=name,
            filename=f"{name}.dxf",
            file_format="dxf",
            file_path="/tmp/nonexistent.dxf",
            size_bytes=0,
            status="ready",
            metadata_={},
        )
        session.add(drawing)
        await session.flush()

        version = DwgDrawingVersion(
            drawing_id=drawing.id,
            version_number=1,
            layers=layers,
            entity_count=entity_count,
            status="ready",
            metadata_={},
        )
        session.add(version)
        await session.flush()

        if annotation_value is not None:
            ann = DwgAnnotation(
                project_id=project_id,
                drawing_id=drawing.id,
                drawing_version_id=version.id,
                annotation_type="area",
                geometry={},
                measurement_value=Decimal(annotation_value),
                measurement_unit="m2",
                linked_boq_position_id=(str(linked_position_id) if linked_position_id else None),
                metadata_=({"compare_key": compare_key} if compare_key else {}),
                created_by="",
            )
            session.add(ann)
            await session.flush()

        ids = (drawing.id, version.id)
        await session.commit()
        return ids


# ── Entity diff across two independent drawings ─────────────────────────


@pytest.mark.asyncio
async def test_pair_compare_produces_entity_diff() -> None:
    from app.modules.dwg_takeoff.service import DwgTakeoffService

    owner = await _seed_user()
    project_id = await _seed_project(owner)
    d1, v1 = await _seed_drawing_one_version(
        project_id,
        name="Plan A",
        layers=[{"name": "WALLS", "entity_count": 10}],
        entity_count=10,
    )
    d2, v2 = await _seed_drawing_one_version(
        project_id,
        name="Plan B",
        layers=[{"name": "WALLS", "entity_count": 12}, {"name": "DOORS", "entity_count": 3}],
        entity_count=15,
    )

    async with async_session_factory() as session:
        service = DwgTakeoffService(session)
        diff = await service.compare_drawing_pair(project_id, d1, d2)

    # Both sides are labelled so the UI can name each drawing.
    assert diff["from_drawing_id"] == d1
    assert diff["to_drawing_id"] == d2
    assert diff["from_version_id"] == v1
    assert diff["to_version_id"] == v2
    # drawing_id stays populated (baseline) for back-compat.
    assert diff["drawing_id"] == d1

    summary = diff["summary"]
    ents = summary["entities"]
    # WALLS present in both with a different count -> modified; DOORS only
    # in the target -> added.
    assert ents["modified"] == 1
    assert ents["added"] == 1
    assert summary["from_entity_count"] == 10
    assert summary["to_entity_count"] == 15
    # No linked annotation changed value -> no cost impact.
    assert summary["net_cost_impact"] is None

    layers = {r["layer"]: r for r in diff["entity_rows"]}
    assert layers["WALLS"]["change_type"] == "modified"
    assert layers["WALLS"]["delta"] == 2
    assert layers["DOORS"]["change_type"] == "added"


# ── Priced annotation change through the pair path ──────────────────────


@pytest.mark.asyncio
async def test_pair_compare_prices_matched_annotation_and_handoff() -> None:
    from app.modules.dwg_takeoff.service import DwgTakeoffService
    from app.modules.variations.service import VariationsService

    owner = await _seed_user()
    project_id = await _seed_project(owner, currency="EUR")
    position_id = await _seed_boq_position(project_id, unit_rate="100")
    d1, _ = await _seed_drawing_one_version(
        project_id,
        name="Plan A",
        layers=[{"name": "WALLS", "entity_count": 10}],
        entity_count=10,
        annotation_value="50",
        compare_key="WALL-01",
        linked_position_id=position_id,
    )
    d2, _ = await _seed_drawing_one_version(
        project_id,
        name="Plan B",
        layers=[{"name": "WALLS", "entity_count": 10}],
        entity_count=10,
        annotation_value="55",
        compare_key="WALL-01",
        linked_position_id=position_id,
    )

    async with async_session_factory() as session:
        service = DwgTakeoffService(session)
        diff = await service.compare_drawing_pair(project_id, d1, d2)
        # (55 - 50) * 100 = 500.00 EUR (single base currency).
        assert diff["summary"]["net_cost_impact"] == "500.00"
        assert diff["summary"]["cost_currency"] == "EUR"

        result = await service.create_variation_from_drawing_pair(project_id, d1, d2, user_id=str(owner))
        assert result["estimated_cost_impact"] == "500.00"
        assert result["currency"] == "EUR"
        vr = await VariationsService(session).get_request(result["variation_request_id"])

    assert vr.status == "draft"  # human-confirm: never auto-submitted
    assert vr.classification == "scope_change"
    meta = vr.metadata_ or {}
    assert meta.get("source") == "dwg_drawing_pair_compare"
    assert meta.get("from_drawing_id") == str(d1)
    assert meta.get("to_drawing_id") == str(d2)
    assert len(meta.get("changed_annotation_ids") or []) == 1


# ── Cross-project safety ────────────────────────────────────────────────


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_pair_compare_rejects_cross_project_drawing() -> None:
    """A drawing in ANOTHER project 404s - a compare never crosses tenants."""
    from fastapi import HTTPException

    from app.modules.dwg_takeoff.service import DwgTakeoffService

    owner = await _seed_user()
    project_a = await _seed_project(owner, currency="EUR")
    project_b = await _seed_project(owner, currency="USD")
    d_a, _ = await _seed_drawing_one_version(
        project_a,
        name="A",
        layers=[{"name": "L", "entity_count": 1}],
        entity_count=1,
    )
    d_b, _ = await _seed_drawing_one_version(
        project_b,
        name="B",
        layers=[{"name": "L", "entity_count": 2}],
        entity_count=2,
    )

    async with async_session_factory() as session:
        service = DwgTakeoffService(session)
        with pytest.raises(HTTPException) as exc:
            await service.compare_drawing_pair(project_a, d_a, d_b)
    assert exc.value.status_code == 404
