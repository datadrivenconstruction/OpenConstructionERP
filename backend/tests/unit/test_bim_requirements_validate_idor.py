# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""IDOR audit test for ``BIMRequirementService.validate_against_model``.

Finding #11 (Max-Audit v8.8.3): the ``POST /bim-requirements/validate/{set_id}/
?model_id=...`` path verified project access only for the requirement SET, then
loaded the caller-supplied ``model_id`` with no check that the model's project
was reachable by the caller. A user owning a set in project A could therefore
validate against a model from another tenant's project B, and because the set's
``element_filter`` / ``constraint_def`` are attacker-controllable the matched /
compliant / non-compliant counts in the response become a cross-tenant
property-value oracle (plus a model-existence + element-class oracle).

The fix threads ``user_id`` into ``validate_against_model`` and calls
``verify_project_access(model.project_id, user_id, session)`` (mirroring the
sibling ``preview-yaml`` endpoint) before reading any elements, collapsing a
foreign / unreachable model to 404 so existence is not leaked. A model that
belongs to a different project than the set is also rejected with 404 as
defence in depth.

These service-level tests exercise that gate directly: a model in another
owner's project must 404, while the set's own-project model validates fine.

Isolation runs on PostgreSQL via ``transactional_session``: each test gets a
session inside an outer transaction that is rolled back on teardown, so the
test never leaves rows behind in the shared schema database (mirrors
``test_carbon_idor.py``).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bim_requirements.models import BIMRequirement, BIMRequirementSet
from app.modules.bim_requirements.service import BIMRequirementService
from tests._pg import transactional_session

# ── Fixtures ──────────────────────────────────────────────────────────────


async def _make_owner(session: AsyncSession) -> uuid.UUID:
    from app.modules.users.models import User

    user = User(
        id=uuid.uuid4(),
        email=f"u-{uuid.uuid4().hex[:8]}@test.local",
        hashed_password="x",
        full_name="Test",
        role="editor",
    )
    session.add(user)
    await session.flush()
    return user.id


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    """Yield a session inside a PostgreSQL transaction rolled back on teardown."""
    async with transactional_session() as session:
        yield session


async def _setup_two_projects(session: AsyncSession) -> dict[str, Any]:
    """Two unrelated projects owned by two different users.

    Returns dict with: project_a, project_b, owner_a, owner_b, service.
    """
    from app.modules.projects.models import Project

    owner_a = await _make_owner(session)
    owner_b = await _make_owner(session)
    proj_a = Project(id=uuid.uuid4(), name="A", owner_id=owner_a)
    proj_b = Project(id=uuid.uuid4(), name="B", owner_id=owner_b)
    session.add_all([proj_a, proj_b])
    await session.flush()
    return {
        "project_a": proj_a,
        "project_b": proj_b,
        "owner_a": owner_a,
        "owner_b": owner_b,
        "service": BIMRequirementService(session),
    }


async def _make_set(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    with_requirement: bool = True,
) -> BIMRequirementSet:
    """Create a requirement set (and one active requirement) for a project."""
    req_set = BIMRequirementSet(
        project_id=project_id,
        name="set",
        source_format="IDS",
    )
    session.add(req_set)
    await session.flush()
    if with_requirement:
        session.add(
            BIMRequirement(
                requirement_set_id=req_set.id,
                element_filter={"ifc_class": "IfcWall"},
                property_name="FireRating",
                constraint_def={"type": "exists"},
                source_format="IDS",
                is_active=True,
            )
        )
        await session.flush()
    return req_set


async def _make_model(session: AsyncSession, project_id: uuid.UUID):
    """Create a BIM model row belonging to ``project_id``."""
    from app.modules.bim_hub.models import BIMModel

    model = BIMModel(
        id=uuid.uuid4(),
        project_id=project_id,
        name="model",
        status="ready",
    )
    session.add(model)
    await session.flush()
    return model


# ── IDOR: foreign model must 404 ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_validate_foreign_model_returns_404(db_session: AsyncSession) -> None:
    """Set in project A + model in another owner's project B → 404.

    This is the core finding: before the fix the validation ran against
    project B's elements and returned compliance counts. The model's project
    is now re-authorised, so a caller who cannot reach project B gets a 404
    that is indistinguishable from a missing model.
    """
    ctx = await _setup_two_projects(db_session)
    req_set = await _make_set(db_session, ctx["project_a"].id)
    foreign_model = await _make_model(db_session, ctx["project_b"].id)

    with pytest.raises(HTTPException) as exc:
        await ctx["service"].validate_against_model(
            req_set.id,
            foreign_model.id,
            user_id=str(ctx["owner_a"]),
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_validate_unknown_model_returns_404(db_session: AsyncSession) -> None:
    """A non-existent model_id still 404s (no existence leak, unchanged)."""
    ctx = await _setup_two_projects(db_session)
    req_set = await _make_set(db_session, ctx["project_a"].id)

    with pytest.raises(HTTPException) as exc:
        await ctx["service"].validate_against_model(
            req_set.id,
            uuid.uuid4(),
            user_id=str(ctx["owner_a"]),
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_validate_model_in_other_accessible_project_returns_404(
    db_session: AsyncSession,
) -> None:
    """Even if the caller could reach the model's project, a set/model project
    mismatch is rejected (defence in depth).

    Here the SAME owner owns both projects, so ``verify_project_access`` would
    pass for the model's project, but the model belongs to a different project
    than the requirement set, so the cross-project pairing must still 404.
    """
    from app.modules.projects.models import Project

    owner = await _make_owner(db_session)
    proj_a = Project(id=uuid.uuid4(), name="A", owner_id=owner)
    proj_b = Project(id=uuid.uuid4(), name="B", owner_id=owner)
    db_session.add_all([proj_a, proj_b])
    await db_session.flush()
    service = BIMRequirementService(db_session)

    req_set = await _make_set(db_session, proj_a.id)
    model_b = await _make_model(db_session, proj_b.id)

    with pytest.raises(HTTPException) as exc:
        await service.validate_against_model(
            req_set.id,
            model_b.id,
            user_id=str(owner),
        )
    assert exc.value.status_code == 404


# ── Happy path: own-project model validates ────────────────────────────────


@pytest.mark.asyncio
async def test_validate_same_project_model_succeeds(db_session: AsyncSession) -> None:
    """Set + model in the caller's own project → a normal compliance report.

    Pins that the IDOR guard does not break the legitimate path: the model is
    in the set's project and owned by the caller, so validation runs and
    returns the report dict (the model has no elements, so the single active
    requirement is ``not_applicable``).
    """
    ctx = await _setup_two_projects(db_session)
    req_set = await _make_set(db_session, ctx["project_a"].id)
    own_model = await _make_model(db_session, ctx["project_a"].id)

    report = await ctx["service"].validate_against_model(
        req_set.id,
        own_model.id,
        user_id=str(ctx["owner_a"]),
    )
    assert report["requirement_set_id"] == str(req_set.id)
    assert report["model_id"] == str(own_model.id)
    # One active requirement, no elements in the model → not_applicable.
    assert report["total_requirements"] == 1
    assert report["not_applicable"] == 1
