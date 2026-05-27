"""‌⁠‍Unit tests for Wave 4 / T13 — ISO 19650 EIR deliverable matrix.

Covers:
    * compute_deliverable_coverage(): 3 rows, 2 accepted → 66.67%.
    * compute_deliverable_coverage(): empty list → 0% with empty by_type.
    * service.add_deliverable / list_deliverables: round-trip.
    * service.get_project_matrix(): rows + cells + per-row coverage.
    * service.list_deliverables(deliverable_type=...): filter works.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import AsyncIterator
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Importing dependent models so Base.metadata.create_all() in the
# fixture has every FK target available (Requirement → BOQ Position,
# RequirementSet → Project, etc.). Conftest also imports these but
# this file may be run in isolation.
import app.modules.boq.models  # noqa: F401
import app.modules.projects.models  # noqa: F401
from app.database import Base
from app.modules.requirements.evaluator import compute_deliverable_coverage
from app.modules.requirements.models import (
    Requirement,
    RequirementDeliverable,
    RequirementSet,
)
from app.modules.requirements.schemas import DeliverableCreate
from app.modules.requirements.service import RequirementsService

# ── Async DB fixture ─────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """Per-test in-memory SQLite session with the full schema bootstrapped.

    FK enforcement is turned OFF for this fixture so EIR rows can hang
    off a synthesised requirement/set without first inserting a full
    Project row tree — the matrix/coverage logic under test is
    self-contained around ``oe_requirement_deliverable`` and doesn't
    care about cross-module integrity.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        future=True,
    )
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys=OFF"))
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        await s.execute(text("PRAGMA foreign_keys=OFF"))
        yield s
    await engine.dispose()


@pytest_asyncio.fixture
async def requirement(session: AsyncSession) -> Requirement:
    """A bare-bones requirement that can hang deliverables off.

    Carries ``_project_id`` as a plain attribute so tests can read the
    parent set's project without triggering a lazy load (the fixture's
    session is short-lived and SQLAlchemy's async lazy-load needs a
    greenlet on every relationship access).
    """
    project_id = uuid.uuid4()
    req_set = RequirementSet(
        project_id=project_id,
        name="T13 EIR fixture",
        description="",
        source_type="manual",
        status="draft",
    )
    session.add(req_set)
    await session.flush()
    req = Requirement(
        requirement_set_id=req_set.id,
        entity="exterior_wall",
        attribute="fire_rating",
        constraint_type="equals",
        constraint_value="F90",
        priority="must",
        status="open",
    )
    session.add(req)
    await session.commit()
    await session.refresh(req)
    # Snapshot project_id for callers that would otherwise dereference
    # ``requirement.requirement_set.project_id`` outside a greenlet.
    req._project_id = project_id  # type: ignore[attr-defined]
    return req


# ── compute_deliverable_coverage (pure function) ─────────────────────────


def test_coverage_two_of_three_accepted() -> None:
    """3 rows total, 2 accepted, 1 submitted → coverage_pct ≈ 66.67."""
    now = datetime.now(UTC)
    rows = [
        {
            "deliverable_type": "model",
            "accepted_at": now,
            "submitted_at": now,
        },
        {
            "deliverable_type": "drawing",
            "accepted_at": now,
            "submitted_at": now,
        },
        {
            "deliverable_type": "schedule",
            "accepted_at": None,
            "submitted_at": now,
        },
    ]
    out = compute_deliverable_coverage(rows)
    assert out["total"] == 3
    assert out["accepted"] == 2
    assert out["submitted"] == 1
    assert out["missing"] == 0
    assert out["coverage_pct"] == pytest.approx(66.67, abs=0.01)
    # by_type carries the same totals broken down per column.
    assert out["by_type"]["model"]["accepted"] == 1
    assert out["by_type"]["schedule"]["submitted"] == 1


def test_coverage_empty_returns_zero() -> None:
    """No deliverables → coverage_pct == 0 and empty by_type."""
    out = compute_deliverable_coverage([])
    assert out["total"] == 0
    assert out["coverage_pct"] == 0.0
    assert out["by_type"] == {}


# ── service.add_deliverable / list_deliverables ─────────────────────────


@pytest.mark.asyncio
async def test_service_add_and_list_deliverables(
    session: AsyncSession,
    requirement: Requirement,
) -> None:
    """Round-trip: add 3 deliverables, list them back."""
    svc = RequirementsService(session)
    with patch("app.modules.requirements.service.event_bus.publish_detached"):
        for dtype, lod, loi in [
            ("model", "300", "3"),
            ("drawing", "200", "2"),
            ("schedule", None, None),
        ]:
            await svc.add_deliverable(
                requirement.id,
                DeliverableCreate(
                    deliverable_type=dtype,
                    lod=lod,
                    loi=loi,
                ),
            )

    rows = await svc.list_deliverables(requirement.id)
    assert len(rows) == 3
    types = {r.deliverable_type for r in rows}
    assert types == {"model", "drawing", "schedule"}


@pytest.mark.asyncio
async def test_service_list_deliverables_filtered_by_type(
    session: AsyncSession,
    requirement: Requirement,
) -> None:
    """Passing deliverable_type filters the returned rows."""
    svc = RequirementsService(session)
    with patch("app.modules.requirements.service.event_bus.publish_detached"):
        await svc.add_deliverable(
            requirement.id,
            DeliverableCreate(deliverable_type="model", lod="300"),
        )
        await svc.add_deliverable(
            requirement.id,
            DeliverableCreate(deliverable_type="drawing", lod="200"),
        )

    only_models = await svc.list_deliverables(requirement.id, deliverable_type="model")
    assert len(only_models) == 1
    assert only_models[0].deliverable_type == "model"


# ── service.get_project_matrix ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_project_matrix_returns_cell_structure(
    session: AsyncSession,
    requirement: Requirement,
) -> None:
    """Matrix endpoint returns rows with the expected cell shape."""
    svc = RequirementsService(session)
    project_id = requirement._project_id  # type: ignore[attr-defined]

    now = datetime.now(UTC)
    # One accepted model + one submitted drawing.
    accepted = RequirementDeliverable(
        requirement_id=requirement.id,
        deliverable_type="model",
        lod="300",
        loi="3",
        submitted_at=now,
        accepted_at=now,
    )
    submitted_only = RequirementDeliverable(
        requirement_id=requirement.id,
        deliverable_type="drawing",
        lod="200",
        submitted_at=now,
    )
    session.add_all([accepted, submitted_only])
    await session.commit()

    payload = await svc.get_project_matrix(project_id)

    assert payload["project_id"] == project_id
    # Canonical columns plus any custom ones (none here).
    assert "model" in payload["deliverable_types"]
    assert "drawing" in payload["deliverable_types"]
    assert "schedule" in payload["deliverable_types"]

    assert len(payload["rows"]) == 1
    row = payload["rows"][0]
    assert row["requirement_id"] == requirement.id
    assert row["entity"] == "exterior_wall"

    # Cells: model accepted, drawing submitted, schedule missing.
    cells = row["cells"]
    assert cells["model"]["status"] == "accepted"
    assert cells["model"]["lod"] == "300"
    assert cells["drawing"]["status"] == "submitted"
    assert cells["schedule"]["status"] == "missing"
    assert cells["schedule"]["deliverable_id"] is None

    # 1 of 2 deliverables accepted → 50%.
    assert row["coverage_pct"] == pytest.approx(50.0, abs=0.01)
    assert payload["coverage_pct"] == pytest.approx(50.0, abs=0.01)
