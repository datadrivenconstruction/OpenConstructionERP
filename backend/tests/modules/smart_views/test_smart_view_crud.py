# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Smart Views CRUD tests — service-layer, against an isolated PostgreSQL.

Every test uses a transaction-isolated session from ``tests._pg`` (the shared
schema-loaded ``oe_test_unit`` database, rolled back on teardown) — never the
production / shared test DB.

We exercise the service layer directly (mirroring
``tests/modules/bim_hub/test_federations.py``) so the test stays
hermetic — no FastAPI dependency graph, no JWT plumbing. RBAC (the
401/403 surface) is exercised by exercising the auth dependency in
isolation through the FastAPI TestClient with an unauthenticated
request.
"""

from __future__ import annotations

import uuid

import pytest

# itsdangerous (share-link token signing) is not in the base or [dev]
# dependency closure, only arriving via fastapi[all]/starlette[full]. The
# smart_views service imports it at module top, so guard the whole module so a
# [dev]-only install (the CI test job) skips it cleanly instead of erroring
# during collection.
pytest.importorskip("itsdangerous", reason="itsdangerous is not in the [dev] install")

import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bim_hub.models import BIMElement, BIMModel
from app.modules.smart_views.models import SmartView
from app.modules.smart_views.schemas import (
    SmartViewActionArgs,
    SmartViewCreate,
    SmartViewRule,
    SmartViewSelector,
    SmartViewUpdate,
)
from app.modules.smart_views.service import SmartViewService
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Transaction-isolated PostgreSQL session, seeded with two users + one project each."""
    async with transactional_session() as s:
        from app.modules.projects.models import Project
        from app.modules.users.models import User

        owner_a = User(
            id=uuid.uuid4(),
            email=f"a-{uuid.uuid4().hex[:6]}@test.io",
            hashed_password="x",
            full_name="A",
        )
        owner_b = User(
            id=uuid.uuid4(),
            email=f"b-{uuid.uuid4().hex[:6]}@test.io",
            hashed_password="x",
            full_name="B",
        )
        s.add_all([owner_a, owner_b])
        await s.flush()
        project_a = Project(
            id=uuid.uuid4(),
            name="Project A",
            owner_id=owner_a.id,
            currency="EUR",
        )
        project_b = Project(
            id=uuid.uuid4(),
            name="Project B",
            owner_id=owner_b.id,
            currency="EUR",
        )
        s.add_all([project_a, project_b])
        await s.commit()
        s.info["owner_a_id"] = owner_a.id
        s.info["owner_b_id"] = owner_b.id
        s.info["project_a_id"] = project_a.id
        s.info["project_b_id"] = project_b.id
        yield s


def _rule_payload(rule_id: str = "r1", action: str = "hide") -> SmartViewRule:
    return SmartViewRule(
        id=rule_id,
        selector=SmartViewSelector(ifc_class="IfcWall"),
        action=action,  # type: ignore[arg-type]
        action_args=SmartViewActionArgs(),
        order=0,
    )


# ── 1. Create user-scoped view ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_user_scoped_view(session: AsyncSession) -> None:
    owner_a: uuid.UUID = session.info["owner_a_id"]
    service = SmartViewService(session)
    payload = SmartViewCreate(
        scope_type="user",
        scope_id=owner_a,
        name="My walls only",
        description="private view",
        rules=[_rule_payload()],
        default_action="show_all",
    )
    response = await service.create_view(payload, user_id=owner_a)
    await session.commit()

    assert response.name == "My walls only"
    assert response.scope_type == "user"
    assert response.scope_id == owner_a
    assert response.created_by == owner_a
    assert len(response.rules) == 1

    # Round-trip through the DB.
    row = (await session.execute(select(SmartView).where(SmartView.id == response.id))).scalar_one()
    assert row.name == "My walls only"
    assert isinstance(row.rules, list) and len(row.rules) == 1


# ── 2. Cannot create user-scoped view for another user ───────────────────


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_cannot_create_user_view_for_another_user(
    session: AsyncSession,
) -> None:
    owner_a: uuid.UUID = session.info["owner_a_id"]
    owner_b: uuid.UUID = session.info["owner_b_id"]
    service = SmartViewService(session)

    with pytest.raises(HTTPException) as exc:
        await service.create_view(
            SmartViewCreate(
                scope_type="user",
                scope_id=owner_b,  # not me!
                name="evil",
                rules=[_rule_payload()],
            ),
            user_id=owner_a,
        )
    assert exc.value.status_code == 403


# ── 3. Create project-scoped view requires project ownership ─────────────


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_create_project_scoped_view_requires_owner(
    session: AsyncSession,
) -> None:
    owner_a: uuid.UUID = session.info["owner_a_id"]
    project_b: uuid.UUID = session.info["project_b_id"]
    service = SmartViewService(session)

    # owner_a cannot create a view on project_b (owned by owner_b).
    with pytest.raises(HTTPException) as exc:
        await service.create_view(
            SmartViewCreate(
                scope_type="project",
                scope_id=project_b,
                name="cross-tenant",
                rules=[_rule_payload()],
            ),
            user_id=owner_a,
        )
    assert exc.value.status_code == 403


# ── 4. Create project-scoped view succeeds for owner ─────────────────────


@pytest.mark.asyncio
async def test_create_project_scoped_view_as_owner(
    session: AsyncSession,
) -> None:
    owner_a: uuid.UUID = session.info["owner_a_id"]
    project_a: uuid.UUID = session.info["project_a_id"]
    service = SmartViewService(session)

    response = await service.create_view(
        SmartViewCreate(
            scope_type="project",
            scope_id=project_a,
            name="Project walls",
            rules=[_rule_payload()],
        ),
        user_id=owner_a,
    )
    await session.commit()
    assert response.scope_type == "project"
    assert response.scope_id == project_a


# ── 5. Fetch one view by id ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_view_by_id(session: AsyncSession) -> None:
    owner_a: uuid.UUID = session.info["owner_a_id"]
    service = SmartViewService(session)
    created = await service.create_view(
        SmartViewCreate(
            scope_type="user",
            scope_id=owner_a,
            name="V1",
            rules=[_rule_payload()],
        ),
        user_id=owner_a,
    )
    await session.commit()

    fetched = await service.get_view(created.id, user_id=owner_a)
    assert fetched.id == created.id
    assert fetched.name == "V1"


# ── 6. 404 on missing view id ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_view_missing_404(session: AsyncSession) -> None:
    owner_a: uuid.UUID = session.info["owner_a_id"]
    service = SmartViewService(session)
    with pytest.raises(HTTPException) as exc:
        await service.get_view(uuid.uuid4(), user_id=owner_a)
    assert exc.value.status_code == 404


# ── 7. Update view (rules + name) ────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_view(session: AsyncSession) -> None:
    owner_a: uuid.UUID = session.info["owner_a_id"]
    service = SmartViewService(session)
    created = await service.create_view(
        SmartViewCreate(
            scope_type="user",
            scope_id=owner_a,
            name="V1",
            rules=[_rule_payload("r1", action="hide")],
        ),
        user_id=owner_a,
    )
    await session.commit()

    updated = await service.update_view(
        created.id,
        SmartViewUpdate(
            name="V1-renamed",
            rules=[_rule_payload("r1", action="show"), _rule_payload("r2", action="hide")],
        ),
        user_id=owner_a,
    )
    await session.commit()

    assert updated.name == "V1-renamed"
    assert len(updated.rules) == 2
    assert updated.rules[0].action == "show"


# ── 8. Non-author cannot update someone else's user-scoped view ──────────


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_non_author_cannot_update(session: AsyncSession) -> None:
    owner_a: uuid.UUID = session.info["owner_a_id"]
    owner_b: uuid.UUID = session.info["owner_b_id"]
    service = SmartViewService(session)
    # owner_a creates a private view.
    created = await service.create_view(
        SmartViewCreate(
            scope_type="user",
            scope_id=owner_a,
            name="V1",
            rules=[_rule_payload()],
        ),
        user_id=owner_a,
    )
    await session.commit()

    # owner_b cannot see it at all — 404.
    with pytest.raises(HTTPException) as exc:
        await service.update_view(
            created.id,
            SmartViewUpdate(name="hijack"),
            user_id=owner_b,
        )
    assert exc.value.status_code == 404


# ── 9. Delete view ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_view(session: AsyncSession) -> None:
    owner_a: uuid.UUID = session.info["owner_a_id"]
    service = SmartViewService(session)
    created = await service.create_view(
        SmartViewCreate(
            scope_type="user",
            scope_id=owner_a,
            name="V1",
            rules=[_rule_payload()],
        ),
        user_id=owner_a,
    )
    await session.commit()

    await service.delete_view(created.id, user_id=owner_a)
    await session.commit()

    with pytest.raises(HTTPException) as exc:
        await service.get_view(created.id, user_id=owner_a)
    assert exc.value.status_code == 404


# ── 10. Non-author cannot delete ─────────────────────────────────────────


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_non_author_cannot_delete(session: AsyncSession) -> None:
    owner_a: uuid.UUID = session.info["owner_a_id"]
    owner_b: uuid.UUID = session.info["owner_b_id"]
    service = SmartViewService(session)
    created = await service.create_view(
        SmartViewCreate(
            scope_type="user",
            scope_id=owner_a,
            name="V1",
            rules=[_rule_payload()],
        ),
        user_id=owner_a,
    )
    await session.commit()

    with pytest.raises(HTTPException) as exc:
        await service.delete_view(created.id, user_id=owner_b)
    assert exc.value.status_code == 404


# ── 11. Evaluate against a BIM model ─────────────────────────────────────


@pytest.mark.asyncio
async def test_evaluate_against_bim_model(session: AsyncSession) -> None:
    """End-to-end happy path: create view + create model + elements → evaluate.

    Verifies the full pipeline runs: scoping check → element load →
    evaluator → response shape.
    """
    owner_a: uuid.UUID = session.info["owner_a_id"]
    project_a: uuid.UUID = session.info["project_a_id"]
    service = SmartViewService(session)

    # Seed a BIM model + a handful of elements.
    model = BIMModel(
        id=uuid.uuid4(),
        project_id=project_a,
        name="ARCH",
        version="1",
        status="ready",
    )
    session.add(model)
    await session.flush()
    walls = [
        BIMElement(
            id=uuid.uuid4(),
            model_id=model.id,
            stable_id=f"W{i}",
            element_type="IfcWall",
            properties={"FireRating": f"F{30 + 30 * i}"},
        )
        for i in range(3)
    ]
    door = BIMElement(
        id=uuid.uuid4(),
        model_id=model.id,
        stable_id="D1",
        element_type="IfcDoor",
        properties={},
    )
    session.add_all(walls + [door])
    await session.commit()

    created = await service.create_view(
        SmartViewCreate(
            scope_type="project",
            scope_id=project_a,
            name="Color walls by FireRating",
            rules=[
                SmartViewRule(
                    id="r1",
                    selector=SmartViewSelector(
                        ifc_class="IfcWall",
                        property="FireRating",
                        operator="exists",
                    ),
                    action="color",
                    action_args=SmartViewActionArgs(color_by_property="FireRating"),
                    order=0,
                )
            ],
        ),
        user_id=owner_a,
    )
    await session.commit()

    response = await service.evaluate(created.id, model.id, user_id=owner_a)
    assert response.element_count == 4
    assert response.rule_count == 1
    # Three walls should each have a colour.
    assert response.states["W0"].color is not None
    assert response.states["W1"].color is not None
    assert response.states["W2"].color is not None
    # Door has no FireRating — no colour
    assert response.states["D1"].color is None
    assert response.legend is not None
    assert set(response.legend.keys()) == {"F30", "F60", "F90"}


# ── 12. Evaluate against unrelated project's model → 404 ─────────────────


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_evaluate_cross_project_404(session: AsyncSession) -> None:
    owner_a: uuid.UUID = session.info["owner_a_id"]
    owner_b: uuid.UUID = session.info["owner_b_id"]
    project_a: uuid.UUID = session.info["project_a_id"]
    project_b: uuid.UUID = session.info["project_b_id"]
    service_a = SmartViewService(session)

    # Owner B creates a model in their own project.
    model_b = BIMModel(
        id=uuid.uuid4(),
        project_id=project_b,
        name="B-model",
        version="1",
        status="ready",
    )
    session.add(model_b)
    await session.commit()

    # Owner A creates a view scoped to their own project.
    created = await service_a.create_view(
        SmartViewCreate(
            scope_type="project",
            scope_id=project_a,
            name="A",
            rules=[_rule_payload()],
        ),
        user_id=owner_a,
    )
    await session.commit()

    # Owner A asks to evaluate their own view against owner B's model:
    # the model exists but is not in any project A can read → 404.
    with pytest.raises(HTTPException) as exc:
        await service_a.evaluate(created.id, model_b.id, user_id=owner_a)
    assert exc.value.status_code == 404


# ── 13. Rule schema validation rejects empty selector ────────────────────


@pytest.mark.asyncio
async def test_empty_selector_rejected_at_schema() -> None:
    with pytest.raises(ValueError):
        SmartViewSelector()  # neither ifc_class nor property


# ── 14. Update rejects mismatching scope mutation ────────────────────────


@pytest.mark.asyncio
async def test_update_cannot_change_scope(session: AsyncSession) -> None:
    """``SmartViewUpdate`` schema has no scope_type/scope_id field.

    Asserted by introspection rather than by trying to push an extra
    field (which Pydantic with strict mode would reject before we
    could test the desired property).
    """
    fields = set(SmartViewUpdate.model_fields.keys())
    assert "scope_type" not in fields
    assert "scope_id" not in fields


# ── 15. Unauthenticated request → 401 via FastAPI ────────────────────────


@pytest.mark.asyncio
async def test_unauthenticated_request_returns_401(monkeypatch) -> None:
    """A request without a bearer token must 401 — RBAC on the route.

    Stand up just the smart_views router behind the JWT dependency and
    fire an authless POST. The auth dependency throws ``HTTPException(401)``
    which FastAPI translates to the response code.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.modules.smart_views.router import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/smart-views")

    client = TestClient(app)
    res = client.post(
        "/api/v1/smart-views/",
        json={
            "scope_type": "user",
            "scope_id": str(uuid.uuid4()),
            "name": "x",
            "rules": [],
        },
    )
    # Auth dependency rejects before the body is validated.
    assert res.status_code in (401, 403)
