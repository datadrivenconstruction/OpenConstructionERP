# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for the revision-compare -> variation handoff (Item 17).

Covers the genuinely-untested pieces the handoff lane added on top of the
already-shipped deterministic compare:

* ``DwgTakeoffService.create_variation_from_versions`` creates a DRAFT
  ``VariationRequest`` whose estimated cost impact equals the compare's
  net impact (in the project base currency), with provenance metadata
  (``source=dwg_revision_compare``, the version pair, changed annotation
  ids).
* ``TakeoffService.create_variation_from_documents`` does the same for the
  PDF path (``source=pdf_revision_compare``).
* Cross-tenant safety: an annotation linked to a BOQ position in ANOTHER
  project is NOT priced, so the compare (and thus the handoff) never leaks
  or blends a foreign tenant's rate.

Test isolation (``feedback_test_isolation.md``): the per-session
PostgreSQL database + eager model registration + synchronous event-bus
shim come from ``backend/tests/conftest.py``; the production database is
never touched. SQLite is removed, so these run on real PostgreSQL.

Run:
    cd backend
    python -m pytest tests/integration/test_revision_compare_variation_handoff.py -v --tb=short
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio

from app.database import async_session_factory


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _schema():
    """Create every table this suite touches on the shared test engine.

    We drive the services directly (no HTTP client / no app lifespan), so
    we register the relevant module ORM models and run ``create_all``
    against the per-session embedded PostgreSQL engine. ``create_all`` is
    idempotent, so re-running it across modules is harmless. The conftest
    already registers users/projects/boq/takeoff; we add dwg_takeoff and
    variations here so their FKs resolve.
    """
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
            email=f"rev-{uuid.uuid4().hex[:10]}@test.io",
            hashed_password="x",
            full_name="Revision Tester",
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
            name="Revision compare project",
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
        boq = BOQ(project_id=project_id, name="Rev BOQ", status="draft")
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


async def _seed_drawing_with_two_versions(
    project_id: uuid.UUID,
    *,
    linked_position_id: uuid.UUID | None,
    old_value: str,
    new_value: str,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Insert a drawing with two versions + a linked annotation per version.

    The annotation carries a stable ``metadata.compare_key`` so the
    deterministic compare matches the old/new annotation as the SAME
    logical item (a measured value change), which is what produces the
    cost impact. Returns ``(drawing_id, from_version_id, to_version_id)``.
    """
    from app.modules.dwg_takeoff.models import (
        DwgAnnotation,
        DwgDrawing,
        DwgDrawingVersion,
    )

    compare_key = "WALL-01"
    async with async_session_factory() as session:
        drawing = DwgDrawing(
            project_id=project_id,
            name="Plan A",
            filename="a.dxf",
            file_format="dxf",
            file_path="/tmp/nonexistent.dxf",
            size_bytes=0,
            status="ready",
            metadata_={},
        )
        session.add(drawing)
        await session.flush()

        v1 = DwgDrawingVersion(
            drawing_id=drawing.id,
            version_number=1,
            layers=[{"name": "WALLS", "entity_count": 10}],
            entity_count=10,
            status="ready",
            metadata_={},
        )
        v2 = DwgDrawingVersion(
            drawing_id=drawing.id,
            version_number=2,
            layers=[{"name": "WALLS", "entity_count": 12}, {"name": "DOORS", "entity_count": 3}],
            entity_count=15,
            status="ready",
            metadata_={},
        )
        session.add_all([v1, v2])
        await session.flush()

        for version, value in ((v1, old_value), (v2, new_value)):
            ann = DwgAnnotation(
                project_id=project_id,
                drawing_id=drawing.id,
                drawing_version_id=version.id,
                annotation_type="area",
                geometry={},
                measurement_value=Decimal(value),
                measurement_unit="m2",
                linked_boq_position_id=(str(linked_position_id) if linked_position_id else None),
                metadata_={"compare_key": compare_key},
                created_by="",
            )
            session.add(ann)

        await session.flush()
        ids = (drawing.id, v1.id, v2.id)
        await session.commit()
        return ids


# ── DWG handoff ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dwg_handoff_creates_draft_variation_with_net_impact() -> None:
    from app.modules.dwg_takeoff.service import DwgTakeoffService
    from app.modules.variations.service import VariationsService

    owner = await _seed_user()
    project_id = await _seed_project(owner, currency="EUR")
    position_id = await _seed_boq_position(project_id, unit_rate="100")
    drawing_id, v1, v2 = await _seed_drawing_with_two_versions(
        project_id,
        linked_position_id=position_id,
        old_value="50",
        new_value="55",
    )

    async with async_session_factory() as session:
        service = DwgTakeoffService(session)
        result = await service.create_variation_from_versions(drawing_id, v1, v2, user_id=str(owner))

        # (55 - 50) * 100 = 500.00 in EUR (project base currency).
        assert result["estimated_cost_impact"] == "500.00"
        assert result["currency"] == "EUR"
        vr_id = result["variation_request_id"]
        code = result["code"]

        vr = await VariationsService(session).get_request(vr_id)

    assert vr.status == "draft"  # human-confirm: never auto-submitted
    assert vr.classification == "scope_change"
    assert vr.code == code
    assert Decimal(str(vr.estimated_cost_impact)) == Decimal("500.00")
    assert vr.currency == "EUR"

    meta = vr.metadata_ or {}
    assert meta.get("source") == "dwg_revision_compare"
    assert meta.get("drawing_id") == str(drawing_id)
    assert meta.get("from_version_id") == str(v1)
    assert meta.get("to_version_id") == str(v2)
    # The modified linked annotation id is captured for traceability.
    assert isinstance(meta.get("changed_annotation_ids"), list)
    assert len(meta["changed_annotation_ids"]) == 1
    # Default title names the drawing + version pair.
    assert "v1->v2" in vr.title


@pytest.mark.asyncio
async def test_dwg_handoff_zero_impact_when_no_linked_position() -> None:
    """An unlinked annotation change has no price -> the draft VR is 0."""
    from app.modules.dwg_takeoff.service import DwgTakeoffService

    owner = await _seed_user()
    project_id = await _seed_project(owner)
    drawing_id, v1, v2 = await _seed_drawing_with_two_versions(
        project_id,
        linked_position_id=None,
        old_value="50",
        new_value="55",
    )

    async with async_session_factory() as session:
        service = DwgTakeoffService(session)
        result = await service.create_variation_from_versions(drawing_id, v1, v2)

    assert result["estimated_cost_impact"] == "0"


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_dwg_handoff_cross_tenant_position_not_priced() -> None:
    """A linked position in ANOTHER project is never priced (no leak/blend)."""
    from app.modules.dwg_takeoff.service import DwgTakeoffService

    owner = await _seed_user()
    project_a = await _seed_project(owner, currency="EUR")
    project_b = await _seed_project(owner, currency="USD")
    # The priced position lives in project B, but the drawing is in A.
    foreign_position = await _seed_boq_position(project_b, unit_rate="100")
    drawing_id, v1, v2 = await _seed_drawing_with_two_versions(
        project_a,
        linked_position_id=foreign_position,
        old_value="50",
        new_value="55",
    )

    async with async_session_factory() as session:
        service = DwgTakeoffService(session)
        # The compare itself must not price against the foreign position.
        diff = await service.compare_drawing_versions(drawing_id, v1, v2)
        assert diff["summary"]["net_cost_impact"] is None
        for row in diff["annotation_rows"]:
            assert row["cost_impact"] is None

        result = await service.create_variation_from_versions(drawing_id, v1, v2)

    assert result["estimated_cost_impact"] == "0"


# ── PDF handoff ───────────────────────────────────────────────────────


async def _seed_two_measured_documents(
    project_id: uuid.UUID,
    owner_id: uuid.UUID,
    *,
    linked_position_id: uuid.UUID,
    old_value: str,
    new_value: str,
) -> tuple[str, str]:
    """Two TakeoffDocuments with one linked measurement each (same compare key).

    ``document_id`` on a measurement is a ``String(255)`` carrying the
    string form of the document's UUID PK, so we let the PK default and
    pass ``str(doc.id)`` through.
    """
    from app.modules.takeoff.models import TakeoffDocument, TakeoffMeasurement

    doc_ids: list[str] = []
    async with async_session_factory() as session:
        for value in (old_value, new_value):
            doc = TakeoffDocument(
                project_id=project_id,
                owner_id=owner_id,
                filename="rev.pdf",
                status="analyzed",
            )
            session.add(doc)
            await session.flush()
            doc_id = str(doc.id)
            doc_ids.append(doc_id)
            session.add(
                TakeoffMeasurement(
                    project_id=project_id,
                    document_id=doc_id,
                    page=1,
                    type="area",
                    group_name="Slab",
                    annotation="S1",
                    measurement_value=Decimal(value),
                    measurement_unit="m2",
                    linked_boq_position_id=str(linked_position_id),
                    metadata_={"compare_key": "SLAB-01"},
                )
            )
        await session.flush()
        await session.commit()
    return doc_ids[0], doc_ids[1]


@pytest.mark.asyncio
async def test_pdf_handoff_creates_draft_variation() -> None:
    from app.modules.takeoff.service import TakeoffService
    from app.modules.variations.service import VariationsService

    owner = await _seed_user()
    project_id = await _seed_project(owner, currency="EUR")
    position_id = await _seed_boq_position(project_id, unit_rate="100")
    doc_from, doc_to = await _seed_two_measured_documents(
        project_id,
        owner,
        linked_position_id=position_id,
        old_value="50",
        new_value="55",
    )

    async with async_session_factory() as session:
        service = TakeoffService(session)
        result = await service.create_variation_from_documents(project_id, doc_from, doc_to, user_id=str(owner))
        assert result["estimated_cost_impact"] == "500.00"
        assert result["currency"] == "EUR"
        vr = await VariationsService(session).get_request(result["variation_request_id"])

    assert vr.status == "draft"
    assert vr.classification == "scope_change"
    meta = vr.metadata_ or {}
    assert meta.get("source") == "pdf_revision_compare"
    assert meta.get("from_document_id") == doc_from
    assert meta.get("to_document_id") == doc_to
    assert len(meta.get("changed_measurement_ids") or []) == 1
