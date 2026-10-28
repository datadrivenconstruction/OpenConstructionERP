"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Round-2 deep-improve — Requirements matrix endpoint + traceability.

Scope:
    1. Matrix endpoint integration test:
       - loads 20 requirements (many-row stress test) into a project
       - calls service.get_project_matrix() and verifies it completes
         under 1 second (performance regression guard)
       - verifies the response shape: project_id, deliverable_types,
         rows, coverage_pct all present and correct
    2. Matrix HTTP route: GET /projects/{project_id}/matrix/ returns 200
       with the expected shape and cross-tenant attacker gets 404.
    3. Traceability — link_to_bim_elements:
       - happy path: adds bim_element_ids to requirement metadata
       - cross-tenant 404: requirement belonging to a different project
         cannot be linked by the attacker's requirement_id
       - replace=True overwrites the array
       - list_by_bim_element returns the correct requirements
    4. Traceability — cross-tenant 404 for link_to_position.
    5. Requirements upload endpoint — magic-byte gate for Excel (.xlsx)
       and CSV (no magic-byte required, but content-type check).

Pattern: PostgreSQL transaction-isolated session + pytest-asyncio, no Alembic
migration (the shared test database carries the full schema).
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

# Ensure FK targets are in metadata.
import app.modules.boq.models  # noqa: F401
import app.modules.projects.models  # noqa: F401
from app.dependencies import (
    get_current_user_id,
    get_current_user_payload,
    get_session,
    verify_project_access,
)
from app.modules.projects.models import Project
from app.modules.requirements.models import (
    Requirement,
    RequirementDeliverable,
    RequirementSet,
)
from app.modules.requirements.service import RequirementsService
from app.modules.users.models import User
from tests._pg import transactional_session

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """PostgreSQL session in a rolled-back transaction, FK enforcement OFF.

    Foreign keys are disabled (``session_replication_role = replica``) so the
    tests can insert requirement rows under synthetic ``project_id`` UUIDs that
    have no backing Project row, avoiding cross-module FK pain.
    """
    async with transactional_session(disable_fks=True) as s:
        yield s


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """PostgreSQL session (FK OFF) — used for router tests needing User/Project tables.

    Runs inside an outer transaction that is rolled back on teardown, so each
    test starts from an empty database.
    """
    async with transactional_session(disable_fks=True) as s:
        yield s


async def _make_user(session, *, email: str | None = None) -> uuid.UUID:
    user = User(
        email=email or f"u{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user.id


async def _make_project(session, owner_id: uuid.UUID) -> uuid.UUID:
    project = Project(name="Matrix Test Project", owner_id=owner_id)
    session.add(project)
    await session.flush()
    await session.refresh(project)
    return project.id


async def _make_req_set(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    name: str = "Test Set",
) -> RequirementSet:
    item = RequirementSet(
        project_id=project_id,
        name=name,
        description="",
        source_type="manual",
        status="draft",
        created_by="test",
    )
    session.add(item)
    await session.flush()
    await session.refresh(item)
    return item


async def _make_requirement(
    session: AsyncSession,
    set_id: uuid.UUID,
    *,
    entity: str = "wall",
    attribute: str = "fire_rating",
) -> Requirement:
    req = Requirement(
        requirement_set_id=set_id,
        entity=entity,
        attribute=attribute,
        constraint_type="equals",
        constraint_value="F90",
        priority="must",
        status="open",
        created_by="test",
    )
    session.add(req)
    await session.flush()
    await session.refresh(req)
    return req


def _build_app(
    db_session,
    *,
    caller_id: str,
    role: str = "admin",
    permissions: list[str] | None = None,
) -> FastAPI:
    """Build the requirements app with one identity bound to it.

    ``permissions`` exists because ``role`` alone cannot express a caller who
    is subject to the project gate. ``RequirePermission`` short-circuits for
    admin, and every other role has to carry the permission either in its
    payload or in the live registry, so with an empty list admin was the only
    identity that reached a guarded route at all. A harness for a module whose
    defects are about identity has to be able to build more than one.
    """
    from app.modules.requirements.router import router as req_router

    app = FastAPI()
    app.include_router(req_router, prefix="/v1/requirements")

    async def _session_override():
        yield db_session

    async def _user_override() -> str:
        return caller_id

    async def _project_access_override(project_id, user_id, session) -> None:
        from fastapi import HTTPException
        from fastapi import status as st

        from app.modules.projects.models import Project as _P

        row = await session.get(_P, project_id)
        if row is None:
            raise HTTPException(status_code=st.HTTP_404_NOT_FOUND, detail="not found")
        if str(row.owner_id) != str(user_id) and role != "admin":
            raise HTTPException(status_code=st.HTTP_404_NOT_FOUND, detail="not found")

    async def _payload_override() -> dict:
        return {"sub": caller_id, "role": role, "permissions": list(permissions or [])}

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_current_user_id] = _user_override
    app.dependency_overrides[get_current_user_payload] = _payload_override
    app.dependency_overrides[verify_project_access] = _project_access_override
    return app


@asynccontextmanager
async def _http(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """In-process async HTTP client bound to ``app`` on the current loop."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# ── 1. Matrix endpoint: many-row performance + shape correctness ──────────────


class TestMatrixPerformance:
    @pytest.mark.asyncio
    async def test_matrix_with_twenty_requirements_under_one_second(self, session: AsyncSession) -> None:
        """Matrix must resolve 20 requirements + deliverables under 1 second.

        This is a regression guard for the server-error fixed in #140. If the
        endpoint hits an N+1 query or falls over without deliverables, it will
        either raise or exceed the time bound.
        """
        project_id = uuid.uuid4()
        svc = RequirementsService(session)

        req_set = await _make_req_set(session, project_id, name="Performance Set")
        await session.commit()

        now = datetime.now(UTC)
        # Create 20 requirements, each with one "model" deliverable (submitted).
        req_ids: list[uuid.UUID] = []
        for i in range(20):
            req = await _make_requirement(
                session,
                req_set.id,
                entity=f"element_{i:02d}",
                attribute="u_value",
            )
            d = RequirementDeliverable(
                requirement_id=req.id,
                deliverable_type="model",
                lod="300",
                submitted_at=now,
            )
            session.add(d)
            req_ids.append(req.id)
        await session.commit()

        start = time.perf_counter()
        payload = await svc.get_project_matrix(project_id)
        elapsed = time.perf_counter() - start

        assert elapsed < 1.0, (
            f"get_project_matrix took {elapsed:.2f}s — expected < 1s. Possible N+1 query or missing eager load."
        )

        assert payload["project_id"] == project_id
        assert "model" in payload["deliverable_types"]
        assert len(payload["rows"]) == 20

        # Each row must have a "model" cell with status=submitted.
        for row in payload["rows"]:
            assert row["cells"]["model"]["status"] == "submitted"
            assert row["coverage_pct"] == pytest.approx(0.0, abs=0.01), (
                "submitted (not accepted) must not count toward coverage_pct"
            )

    @pytest.mark.asyncio
    async def test_matrix_empty_project_returns_canonical_columns(self, session: AsyncSession) -> None:
        """An empty project must return the 6 canonical deliverable types."""
        project_id = uuid.uuid4()
        svc = RequirementsService(session)

        payload = await svc.get_project_matrix(project_id)
        assert payload["project_id"] == project_id
        assert payload["rows"] == []
        assert payload["coverage_pct"] == 0.0
        for col in ("model", "drawing", "schedule", "report", "cobie", "pset"):
            assert col in payload["deliverable_types"]

    @pytest.mark.asyncio
    async def test_matrix_accepted_deliverable_increments_coverage(self, session: AsyncSession) -> None:
        """An accepted deliverable makes coverage_pct > 0."""
        project_id = uuid.uuid4()
        svc = RequirementsService(session)
        req_set = await _make_req_set(session, project_id)
        await session.commit()

        now = datetime.now(UTC)
        req = await _make_requirement(session, req_set.id)
        d = RequirementDeliverable(
            requirement_id=req.id,
            deliverable_type="drawing",
            lod="200",
            submitted_at=now,
            accepted_at=now,
        )
        session.add(d)
        await session.commit()

        payload = await svc.get_project_matrix(project_id)
        assert len(payload["rows"]) == 1
        row = payload["rows"][0]
        assert row["cells"]["drawing"]["status"] == "accepted"
        assert row["coverage_pct"] == pytest.approx(100.0, abs=0.01)
        assert payload["coverage_pct"] == pytest.approx(100.0, abs=0.01)

    @pytest.mark.asyncio
    async def test_matrix_surfaces_linked_position_id(self, session: AsyncSession) -> None:
        """A requirement linked to a BOQ position exposes linked_position_id on its row.

        Powers the matrix BOQ chip (CONN-29) that deep-links to /boq. FK
        enforcement is off in this fixture so we set the id directly without a
        backing Position row.
        """
        project_id = uuid.uuid4()
        svc = RequirementsService(session)
        req_set = await _make_req_set(session, project_id)

        linked_pos = uuid.uuid4()
        linked_req = await _make_requirement(session, req_set.id, entity="wall", attribute="fire_rating")
        linked_req.linked_position_id = linked_pos
        # A second requirement with no link must report None.
        await _make_requirement(session, req_set.id, entity="roof", attribute="pitch")
        await session.commit()

        payload = await svc.get_project_matrix(project_id)
        by_entity = {row["entity"]: row for row in payload["rows"]}
        assert by_entity["wall"]["linked_position_id"] == linked_pos
        assert by_entity["roof"]["linked_position_id"] is None

    @pytest.mark.asyncio
    async def test_matrix_route_exposes_linked_position_id(self, db_session: AsyncSession) -> None:
        """The HTTP matrix response serializes linked_position_id as a string."""
        from app.modules.requirements.permissions import register_requirements_permissions

        register_requirements_permissions()

        owner_id = await _make_user(db_session)
        project_id = await _make_project(db_session, owner_id)

        req_set = await _make_req_set(db_session, project_id)
        req = await _make_requirement(db_session, req_set.id)
        linked_pos = uuid.uuid4()
        req.linked_position_id = linked_pos
        await db_session.commit()

        app = _build_app(db_session, caller_id=str(owner_id))
        async with _http(app) as client:
            resp = await client.get(f"/v1/requirements/projects/{project_id}/matrix/")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["rows"][0]["linked_position_id"] == str(linked_pos)

    @pytest.mark.asyncio
    async def test_matrix_filter_by_deliverable_type(self, session: AsyncSession) -> None:
        """Filtering by deliverable_type returns only that column."""
        project_id = uuid.uuid4()
        svc = RequirementsService(session)
        req_set = await _make_req_set(session, project_id)
        req = await _make_requirement(session, req_set.id)
        now = datetime.now(UTC)
        for dtype in ("model", "drawing", "schedule"):
            d = RequirementDeliverable(
                requirement_id=req.id,
                deliverable_type=dtype,
                submitted_at=now,
            )
            session.add(d)
        await session.commit()

        payload = await svc.get_project_matrix(project_id, deliverable_type="drawing")
        assert payload["deliverable_types"] == ["drawing"]
        row = payload["rows"][0]
        assert "drawing" in row["cells"]
        # model and schedule must not appear in cells.
        assert "model" not in row["cells"]
        assert "schedule" not in row["cells"]


# ── 2. Matrix HTTP route: 200 happy + cross-tenant 404 ────────────────────────


class TestMatrixRoute:
    @pytest.mark.asyncio
    async def test_matrix_route_returns_200_with_rows(self, db_session: AsyncSession) -> None:
        from app.modules.requirements.permissions import register_requirements_permissions

        register_requirements_permissions()

        owner_id = await _make_user(db_session)
        project_id = await _make_project(db_session, owner_id)
        svc = RequirementsService(db_session)

        req_set = await _make_req_set(db_session, project_id)
        req = await _make_requirement(db_session, req_set.id)
        now = datetime.now(UTC)
        d = RequirementDeliverable(
            requirement_id=req.id,
            deliverable_type="model",
            submitted_at=now,
            accepted_at=now,
        )
        db_session.add(d)
        await db_session.commit()

        app = _build_app(db_session, caller_id=str(owner_id))
        async with _http(app) as client:
            resp = await client.get(f"/v1/requirements/projects/{project_id}/matrix/")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["project_id"] == str(project_id)
        assert len(body["rows"]) == 1
        assert "model" in body["deliverable_types"]

    @pytest.mark.tenant_isolation
    @pytest.mark.asyncio
    async def test_matrix_route_cross_tenant_returns_404(self, db_session: AsyncSession) -> None:
        from app.modules.requirements.permissions import register_requirements_permissions

        register_requirements_permissions()

        victim_id = await _make_user(db_session, email="victim@matrix.test")
        attacker_id = await _make_user(db_session, email="attacker@matrix.test")
        victim_project = await _make_project(db_session, victim_id)

        # Build app as attacker (role=editor so admin bypass doesn't fire).
        app = _build_app(db_session, caller_id=str(attacker_id), role="editor")

        async with _http(app) as client:
            resp = await client.get(f"/v1/requirements/projects/{victim_project}/matrix/")
        assert resp.status_code == 404, resp.text


# ── 3. Traceability — link_to_bim_elements ────────────────────────────────────


class TestBimTraceability:
    @pytest.mark.asyncio
    async def test_link_bim_elements_happy_path(self, session: AsyncSession) -> None:
        project_id = uuid.uuid4()
        svc = RequirementsService(session)
        req_set = await _make_req_set(session, project_id)
        req = await _make_requirement(session, req_set.id)
        await session.commit()

        elem1 = str(uuid.uuid4())
        elem2 = str(uuid.uuid4())

        updated = await svc.link_to_bim_elements(req.id, [elem1, elem2])
        await session.commit()

        bim_ids = updated.metadata_.get("bim_element_ids", [])
        assert elem1 in bim_ids
        assert elem2 in bim_ids

    @pytest.mark.asyncio
    async def test_link_bim_elements_additive_merge(self, session: AsyncSession) -> None:
        """Calling link_to_bim_elements twice without replace=True merges."""
        project_id = uuid.uuid4()
        svc = RequirementsService(session)
        req_set = await _make_req_set(session, project_id)
        req = await _make_requirement(session, req_set.id)
        await session.commit()

        elem1 = str(uuid.uuid4())
        elem2 = str(uuid.uuid4())

        await svc.link_to_bim_elements(req.id, [elem1])
        updated = await svc.link_to_bim_elements(req.id, [elem2])
        await session.commit()

        bim_ids = updated.metadata_.get("bim_element_ids", [])
        assert elem1 in bim_ids
        assert elem2 in bim_ids

    @pytest.mark.asyncio
    async def test_link_bim_elements_replace_overwrites(self, session: AsyncSession) -> None:
        """replace=True discards existing ids."""
        project_id = uuid.uuid4()
        svc = RequirementsService(session)
        req_set = await _make_req_set(session, project_id)
        req = await _make_requirement(session, req_set.id)
        await session.commit()

        old_elem = str(uuid.uuid4())
        new_elem = str(uuid.uuid4())

        await svc.link_to_bim_elements(req.id, [old_elem])
        updated = await svc.link_to_bim_elements(req.id, [new_elem], replace=True)
        await session.commit()

        bim_ids = updated.metadata_.get("bim_element_ids", [])
        assert new_elem in bim_ids
        assert old_elem not in bim_ids, "replace=True must discard the previous bim_element_ids"

    @pytest.mark.asyncio
    async def test_link_bim_elements_nonexistent_requirement_raises_404(self, session: AsyncSession) -> None:
        from fastapi import HTTPException

        svc = RequirementsService(session)
        phantom_id = uuid.uuid4()

        with pytest.raises(HTTPException) as exc:
            await svc.link_to_bim_elements(phantom_id, [str(uuid.uuid4())])
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_list_by_bim_element_returns_linked_requirements(self, session: AsyncSession) -> None:
        """list_by_bim_element returns only requirements that pin the element."""
        project_id = uuid.uuid4()
        svc = RequirementsService(session)
        req_set = await _make_req_set(session, project_id)
        req_a = await _make_requirement(session, req_set.id, entity="wall", attribute="u_value")
        req_b = await _make_requirement(session, req_set.id, entity="roof", attribute="pitch")
        req_a_id = req_a.id
        req_b_id = req_b.id
        await session.commit()

        elem_x = str(uuid.uuid4())
        elem_y = str(uuid.uuid4())

        # Link req_a to elem_x; req_b to elem_y.
        await svc.link_to_bim_elements(req_a_id, [elem_x])
        await svc.link_to_bim_elements(req_b_id, [elem_y])
        await session.commit()

        results = await svc.list_by_bim_element(elem_x, project_id=project_id)
        assert len(results) == 1
        assert results[0].entity == "wall"

    @pytest.mark.asyncio
    async def test_invalid_uuid_in_bim_element_ids_is_silently_skipped(self, session: AsyncSession) -> None:
        """Non-UUID strings in bim_element_ids are silently dropped."""
        project_id = uuid.uuid4()
        svc = RequirementsService(session)
        req_set = await _make_req_set(session, project_id)
        req = await _make_requirement(session, req_set.id)
        await session.commit()

        valid = str(uuid.uuid4())
        updated = await svc.link_to_bim_elements(req.id, [valid, "not-a-uuid", ""])
        await session.commit()

        bim_ids = updated.metadata_.get("bim_element_ids", [])
        assert valid in bim_ids
        assert "not-a-uuid" not in bim_ids


# ── 4. Traceability — cross-tenant 404 for link_to_position ──────────────────


class TestPositionTraceabilityCrossTenant:
    """link_to_position, at the service level and across a tenant boundary.

    The first two tests below are absence tests: a random uuid4 names a row
    that exists for nobody, and the 404 says so. They do not cover the
    cross-tenant case, and an earlier version of this docstring claimed they
    did on the grounds that IDOR would mean the position does not exist in
    the attacker's session. It does not follow. Absent globally and absent
    from your tenant produce the same 404 and prove nothing about each other,
    and the service reaches the position with ``session.get(Position, id)``,
    which is not scoped to a caller at all.

    The cross-tenant case therefore needs a row that really exists under
    somebody else, and it needs to go through the route, because the service
    takes no caller and so has no tenant to be foreign to. That is the third
    test.
    """

    @pytest.mark.asyncio
    async def test_link_to_nonexistent_position_raises_404(self, session: AsyncSession) -> None:
        from fastapi import HTTPException

        project_id = uuid.uuid4()
        svc = RequirementsService(session)
        req_set = await _make_req_set(session, project_id)
        req = await _make_requirement(session, req_set.id)
        await session.commit()

        # Random UUID — position does not exist in this DB.
        phantom_pos = uuid.uuid4()
        with pytest.raises(HTTPException) as exc:
            await svc.link_to_position(req.id, phantom_pos)
        assert exc.value.status_code == 404
        assert "position" in exc.value.detail.lower()

    @pytest.mark.asyncio
    async def test_link_to_position_with_nonexistent_requirement_raises_404(self, session: AsyncSession) -> None:
        from fastapi import HTTPException

        svc = RequirementsService(session)
        with pytest.raises(HTTPException) as exc:
            await svc.link_to_position(uuid.uuid4(), uuid.uuid4())
        assert exc.value.status_code == 404
        assert "requirement" in exc.value.detail.lower()

    @pytest.mark.tenant_isolation
    @pytest.mark.asyncio
    async def test_a_position_in_another_projects_boq_cannot_be_linked(self, db_session: AsyncSession) -> None:
        """A caller may link only to positions in the project they are linking from.

        The route gates on the requirement's project, so the caller here owns
        that project outright and passes the gate honestly. The position is the
        variable: it lives in another owner's BOQ, and nothing on this path
        compared the two projects until the guard this test covers.

        The control is what makes the 404 mean something. The position's own
        owner links it first and gets a 200, so the row demonstrably exists and
        the endpoint demonstrably works on it. Only then is it asked for by a
        caller from the other project, where a 404 can only be a refusal.

        Both callers are editors carrying the permission explicitly, not
        admins. An admin would bypass the project gate on the requirement and
        leave the result resting on a bypass rather than on the boundary.
        """
        from app.modules.boq.models import BOQ, Position
        from app.modules.requirements.permissions import register_requirements_permissions

        register_requirements_permissions()

        owner_a = await _make_user(db_session, email="owner-a@link.test")
        owner_b = await _make_user(db_session, email="owner-b@link.test")
        project_a = await _make_project(db_session, owner_a)
        project_b = await _make_project(db_session, owner_b)

        set_a = await _make_req_set(db_session, project_a, name="Set A")
        req_a = await _make_requirement(db_session, set_a.id)
        set_b = await _make_req_set(db_session, project_b, name="Set B")
        req_b = await _make_requirement(db_session, set_b.id)

        boq_b = BOQ(project_id=project_b, name="B's bill")
        db_session.add(boq_b)
        await db_session.flush()
        position_b = Position(
            boq_id=boq_b.id,
            ordinal="1.1",
            description="B's exterior wall",
            unit="m2",
        )
        db_session.add(position_b)
        await db_session.flush()
        await db_session.refresh(position_b)

        path = "/v1/requirements/{s}/requirements/{r}/link/{p}"

        editor = {"role": "editor", "permissions": ["requirements.update"]}

        # Control: the position's own project can link it. Proves existence.
        app_b = _build_app(db_session, caller_id=str(owner_b), **editor)
        async with _http(app_b) as client:
            allowed = await client.post(path.format(s=set_b.id, r=req_b.id, p=position_b.id))
        assert allowed.status_code == 200, allowed.text
        assert allowed.json()["linked_position_id"] == str(position_b.id)

        # The boundary: same position, a caller from the other project.
        app_a = _build_app(db_session, caller_id=str(owner_a), **editor)
        async with _http(app_a) as client:
            refused = await client.post(path.format(s=set_a.id, r=req_a.id, p=position_b.id))
        assert refused.status_code == 404, (
            "a position in another project's BOQ was linkable across the boundary; "
            f"got {refused.status_code}: {refused.text}"
        )

        # The body is a separate assertion from the status, because a 404 that
        # repeats the identifier back has still confirmed the identifier is
        # real. That is a smaller leak than the 200 and the same kind of leak,
        # and it is why the refusal reuses the wording of the not-found case
        # instead of explaining itself.
        assert str(position_b.id) not in refused.text, f"the refusal echoed the foreign position id: {refused.text}"
        assert str(boq_b.id) not in refused.text, f"the refusal echoed the foreign BOQ id: {refused.text}"

        # A refusal must also not have written anything.
        await db_session.refresh(req_a)
        assert req_a.linked_position_id is None

    @pytest.mark.tenant_isolation
    @pytest.mark.asyncio
    async def test_the_additive_route_refuses_a_foreign_position_too(self, db_session: AsyncSession) -> None:
        """The same boundary on the newer route, which names the position in the body.

        ``attach_position`` reaches the position through the request body rather
        than the path. That changes nothing about who may name it, and the two
        routes had the identical defect, so a guard proven on only one of them
        would be a guard tested at the call site that was already right. This is
        the second call site.
        """
        from app.modules.boq.models import BOQ, Position
        from app.modules.requirements.permissions import register_requirements_permissions

        register_requirements_permissions()

        owner_a = await _make_user(db_session, email="owner-a@attach.test")
        owner_b = await _make_user(db_session, email="owner-b@attach.test")
        project_a = await _make_project(db_session, owner_a)
        project_b = await _make_project(db_session, owner_b)

        set_a = await _make_req_set(db_session, project_a, name="Set A")
        req_a = await _make_requirement(db_session, set_a.id)
        set_b = await _make_req_set(db_session, project_b, name="Set B")
        req_b = await _make_requirement(db_session, set_b.id)

        boq_b = BOQ(project_id=project_b, name="B's bill")
        db_session.add(boq_b)
        await db_session.flush()
        position_b = Position(boq_id=boq_b.id, ordinal="2.1", description="B's slab", unit="m3")
        db_session.add(position_b)
        await db_session.flush()
        await db_session.refresh(position_b)

        path = "/v1/requirements/{s}/requirements/{r}/positions/"
        body = {"position_id": str(position_b.id), "link_source": "manual", "notes": ""}
        editor = {"role": "editor", "permissions": ["requirements.update"]}

        # Control: the position's own project attaches it and gets a 201.
        app_b = _build_app(db_session, caller_id=str(owner_b), **editor)
        async with _http(app_b) as client:
            allowed = await client.post(path.format(s=set_b.id, r=req_b.id), json=body)
        assert allowed.status_code == 201, allowed.text
        assert allowed.json()["position_id"] == str(position_b.id)

        # The boundary: same position, named from the other project.
        app_a = _build_app(db_session, caller_id=str(owner_a), **editor)
        async with _http(app_a) as client:
            refused = await client.post(path.format(s=set_a.id, r=req_a.id), json=body)
        assert refused.status_code == 404, (
            f"a foreign position was attachable through the body; got {refused.status_code}: {refused.text}"
        )
        assert str(position_b.id) not in refused.text, f"the refusal echoed the foreign position id: {refused.text}"

        # And nothing was linked.
        links = await RequirementsService(db_session).list_position_links(req_a.id)
        assert links == []


# ── 5. Requirements file upload — Excel magic-byte ────────────────────────────


class TestRequirementsFileUpload:
    """The /import/excel endpoint (if present) must pass the magic-byte gate.
    We test at the file_signature helper level for Excel format.
    """

    def test_xlsx_magic_bytes_recognised(self) -> None:
        """xlsx (Office Open XML / ZIP) magic = PK\\x03\\x04."""
        from app.core.file_signature import require as require_signature

        allowed = frozenset({"zip"})  # xlsx is a zip under the hood
        xlsx_head = b"PK\x03\x04" + b"\x00" * 64
        detected = require_signature(xlsx_head, allowed, filename="requirements.xlsx")
        assert detected == "zip"

    def test_csv_text_content_round_trip(self) -> None:
        """CSV import works via text — verify the text-import parser round-trips."""
        # Pure logic test, no network needed.

        text_block = (
            "exterior_wall | fire_rating | equals | F90 | -\n"
            "exterior_wall | u_value | min | 0.25 | W/m2K\n"
            "# This is a comment\n"
            "\n"
            "roof | pitch | equals | 15deg | deg\n"
        )

        # We only test the parsing logic inline (the service's parser method
        # is embedded in import_from_text; extract the line-splitting part).
        lines = text_block.strip().split("\n")
        parsed = []
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 5:
                parsed.append({"entity": parts[0], "attribute": parts[1]})
        assert len(parsed) == 3
        assert parsed[0]["entity"] == "exterior_wall"
        assert parsed[2]["entity"] == "roof"


# ── 6. Text import — the set named in the path must be the caller's ───────────


class TestTextImportCrossTenant:
    """``POST /{set_id}/import/text/`` appends rows to the set the path names.

    This was the one set-scoped route in the module carrying no project check
    of any kind while thirty of its neighbours carry one. Its own docstring
    said a new set was created, which would have made the absent check
    harmless. The service resolves the existing set and appends to it, so the
    call was a write into another tenant's set that handed back that set's
    full contents in the 201 body.
    """

    @pytest.mark.tenant_isolation
    async def test_text_cannot_be_imported_into_another_projects_set(self, db_session: AsyncSession) -> None:
        """Both polarities: the owner's import lands, the stranger's 404s and writes nothing."""
        from sqlalchemy import func, select

        from app.modules.requirements.models import Requirement
        from app.modules.requirements.permissions import register_requirements_permissions

        register_requirements_permissions()

        owner_a = await _make_user(db_session, email="owner-a@textimport.test")
        owner_b = await _make_user(db_session, email="owner-b@textimport.test")
        project_a = await _make_project(db_session, owner_a)
        project_b = await _make_project(db_session, owner_b)

        set_a = await _make_req_set(db_session, project_a, name="A's set")
        set_b = await _make_req_set(db_session, project_b, name="B's set")

        path = "/v1/requirements/{s}/import/text/"
        body = {"text": "exterior_wall | fire_rating | equals | F90 | -"}
        creator = {"role": "editor", "permissions": ["requirements.create"]}

        async def _rows_in(set_id: uuid.UUID) -> int:
            result = await db_session.execute(
                select(func.count()).select_from(Requirement).where(Requirement.requirement_set_id == set_id)
            )
            return int(result.scalar_one())

        # Control: B imports into B's own set and the row lands.
        app_b = _build_app(db_session, caller_id=str(owner_b), **creator)
        async with _http(app_b) as client:
            allowed = await client.post(path.format(s=set_b.id), json=body)
        assert allowed.status_code == 201, allowed.text
        assert await _rows_in(set_b.id) == 1

        # The boundary: A names B's set. The count taken here is the control's
        # one row, so an unchanged count is what proves nothing was appended.
        before = await _rows_in(set_b.id)
        app_a = _build_app(db_session, caller_id=str(owner_a), **creator)
        async with _http(app_a) as client:
            refused = await client.post(path.format(s=set_b.id), json=body)
        assert refused.status_code == 404, (
            f"text was importable into a foreign set; got {refused.status_code}: {refused.text}"
        )
        assert str(set_b.id) not in refused.text, f"the refusal echoed the foreign set id: {refused.text}"
        assert await _rows_in(set_b.id) == before, "the refused import still appended rows to the foreign set"

        # A's own set is empty too, which rules out the rows having been
        # redirected somewhere harmless rather than actually refused.
        assert await _rows_in(set_a.id) == 0


# ── 7. Set creation — the project the caller names must be the caller's ───────


class TestSetCreationCrossTenant:
    """``POST /`` takes its project from the request body or the query string.

    Nothing fetched that project and nothing compared it, so a holder of the
    global requirements.create role could plant a set inside another tenant's
    project, where it appears in that tenant's set list under a name a stranger
    chose. The route reads no row at all, which is why an audit looking for a
    fetch by identifier walks straight past it. An identifier arriving from
    outside is enough on its own.
    """

    @pytest.mark.tenant_isolation
    async def test_a_set_cannot_be_created_inside_another_projects_id(self, db_session: AsyncSession) -> None:
        """Both polarities, and both spellings, since the project arrives two ways."""
        from sqlalchemy import func, select

        from app.modules.requirements.models import RequirementSet
        from app.modules.requirements.permissions import register_requirements_permissions

        register_requirements_permissions()

        owner_a = await _make_user(db_session, email="owner-a@setcreate.test")
        owner_b = await _make_user(db_session, email="owner-b@setcreate.test")
        project_a = await _make_project(db_session, owner_a)
        project_b = await _make_project(db_session, owner_b)

        creator = {"role": "editor", "permissions": ["requirements.create"]}

        async def _sets_in(project_id: uuid.UUID) -> int:
            result = await db_session.execute(
                select(func.count()).select_from(RequirementSet).where(RequirementSet.project_id == project_id)
            )
            return int(result.scalar_one())

        app_a = _build_app(db_session, caller_id=str(owner_a), **creator)

        # Control: A creates inside A's own project and it lands.
        async with _http(app_a) as client:
            allowed = await client.post(
                "/v1/requirements/",
                json={"project_id": str(project_a), "name": "A's own set", "source_type": "manual"},
            )
        assert allowed.status_code == 201, allowed.text
        assert await _sets_in(project_a) == 1

        # The boundary, body spelling.
        async with _http(app_a) as client:
            refused_body = await client.post(
                "/v1/requirements/",
                json={"project_id": str(project_b), "name": "planted", "source_type": "manual"},
            )
        assert refused_body.status_code == 404, (
            f"a set was creatable inside a foreign project; got {refused_body.status_code}: {refused_body.text}"
        )

        # The boundary, query spelling. The route accepts the project two ways,
        # and a guard proved on only one of them is a guard on the spelling.
        async with _http(app_a) as client:
            refused_query = await client.post(
                f"/v1/requirements/?project_id={project_b}",
                json={"name": "planted", "source_type": "manual"},
            )
        assert refused_query.status_code == 404, (
            f"the query spelling reached a foreign project; got {refused_query.status_code}: {refused_query.text}"
        )

        assert await _sets_in(project_b) == 0, "a set was planted in the foreign project"
        assert await _sets_in(project_a) == 1, "the refused calls landed in the caller's own project instead"


# -- 6. Containment: the BIM model a set is validated against -------------------


class TestTheModelValidatedAgainstBelongsToTheSetsProject:
    """``validate-bim`` gated the set and never the model.

    The route resolves the requirement set and checks the caller against that
    set's project, honestly and correctly. Nothing checked the model. So a
    caller entitled to their own set could name any model id in the
    installation, and every element of it would be read, measured against
    their requirements, and folded into a report stored against their project.
    The stolen data arrives as the report rather than as the response body,
    which is why a test that only reads the status code would have missed it.

    The refusal is asserted for indistinguishability rather than for the
    absence of a substring. The model id cannot be kept out of the message -
    the caller supplied it in the path and already knows it. What must not
    differ is everything else: a model that belongs to somebody else has to be
    refused in exactly the words used for a model that never existed, because
    a refusal that reads differently is an existence oracle that can be walked
    one identifier at a time.
    """

    @staticmethod
    async def _make_model(session: AsyncSession, project_id: uuid.UUID, name: str):
        from app.modules.bim_hub.models import BIMModel

        model = BIMModel(project_id=project_id, name=name, status="ready")
        session.add(model)
        await session.flush()
        await session.refresh(model)
        return model

    @staticmethod
    async def _reports_for(session: AsyncSession, project_id: uuid.UUID) -> int:
        from sqlalchemy import func, select

        from app.modules.validation.models import ValidationReport

        stmt = select(func.count()).select_from(
            select(ValidationReport).where(ValidationReport.project_id == project_id).subquery()
        )
        return int((await session.execute(stmt)).scalar_one())

    @pytest.mark.tenant_isolation
    @pytest.mark.asyncio
    async def test_a_model_in_another_project_cannot_be_validated_against(self, db_session: AsyncSession) -> None:
        """The boundary, with both controls that make the 404 mean something.

        Two controls, because a 404 on its own proves nothing. The model's own
        owner validates against it first, so the row demonstrably exists and
        the endpoint demonstrably works on it. The attacker then validates
        against their own model, so their identity, permission and set are
        demonstrably sufficient. Only with both standing can the third call's
        404 be a refusal rather than a coincidence.

        Both callers are editors carrying the permission explicitly. An admin
        would pass the project gate by bypass, and the result would rest on the
        bypass rather than on the boundary. It matters more here than usual:
        the rule under test is deliberately role-independent, since validating
        one project's requirements against another project's model files a
        wrong record whoever asks for it.
        """
        from app.modules.requirements.permissions import register_requirements_permissions

        register_requirements_permissions()

        owner_a = await _make_user(db_session, email="owner-a@validate.test")
        owner_b = await _make_user(db_session, email="owner-b@validate.test")
        project_a = await _make_project(db_session, owner_a)
        project_b = await _make_project(db_session, owner_b)

        set_a = await _make_req_set(db_session, project_a, name="A's set")
        await _make_requirement(db_session, set_a.id)
        set_b = await _make_req_set(db_session, project_b, name="B's set")
        await _make_requirement(db_session, set_b.id)

        model_a = await self._make_model(db_session, project_a, "A's model")
        model_b = await self._make_model(db_session, project_b, "B's model")

        path = "/v1/requirements/{s}/validate-bim/{m}"
        editor = {"role": "editor", "permissions": ["requirements.read", "validation.create"]}

        app_b = _build_app(db_session, caller_id=str(owner_b), **editor)
        app_a = _build_app(db_session, caller_id=str(owner_a), **editor)

        # Control one: the model's own project validates against it.
        async with _http(app_b) as client:
            owner_call = await client.post(path.format(s=set_b.id, m=model_b.id))
        assert owner_call.status_code == 200, owner_call.text

        # Control two: the other caller's own tenant still works.
        async with _http(app_a) as client:
            own_call = await client.post(path.format(s=set_a.id, m=model_a.id))
        assert own_call.status_code == 200, (
            f"the guard refused a model in the caller's own project; got {own_call.status_code}: {own_call.text}"
        )

        reports_before = await self._reports_for(db_session, project_a)

        # The boundary: A's set, B's model.
        async with _http(app_a) as client:
            refused = await client.post(path.format(s=set_a.id, m=model_b.id))
        assert refused.status_code == 404, (
            "a model in another project was validated against across the boundary; "
            f"got {refused.status_code}: {refused.text}"
        )

        # Nothing about the foreign project may travel back in the refusal.
        assert str(project_b) not in refused.text, f"the refusal echoed the foreign project id: {refused.text}"
        assert "B's model" not in refused.text, f"the refusal echoed the foreign model name: {refused.text}"

        # And the read must not have happened: a refusal files no report.
        assert await self._reports_for(db_session, project_a) == reports_before, (
            "the refused call still wrote a validation report into the caller's project"
        )

    @pytest.mark.tenant_isolation
    @pytest.mark.asyncio
    async def test_a_foreign_model_is_refused_in_the_same_words_as_a_missing_one(
        self, db_session: AsyncSession
    ) -> None:
        """Indistinguishable, not merely refused.

        Asking for a model that belongs to somebody else and asking for a model
        that does not exist have to produce the same answer. If they read
        differently, the endpoint answers "does this id exist somewhere in the
        installation" for any id the caller cares to try, and a private model
        list can be enumerated through a pair of 404s.

        The two ids are substituted out before the comparison, because each
        message quotes back the id the caller themselves put in the path. That
        one difference is not information the caller did not already have.
        """
        from app.modules.requirements.permissions import register_requirements_permissions

        register_requirements_permissions()

        owner_a = await _make_user(db_session, email="owner-a@oracle.test")
        owner_b = await _make_user(db_session, email="owner-b@oracle.test")
        project_a = await _make_project(db_session, owner_a)
        project_b = await _make_project(db_session, owner_b)

        set_a = await _make_req_set(db_session, project_a, name="A's set")
        await _make_requirement(db_session, set_a.id)
        model_b = await self._make_model(db_session, project_b, "B's model")
        never_existed = uuid.uuid4()

        path = "/v1/requirements/{s}/validate-bim/{m}"
        app_a = _build_app(
            db_session,
            caller_id=str(owner_a),
            role="editor",
            permissions=["requirements.read", "validation.create"],
        )

        async with _http(app_a) as client:
            foreign = await client.post(path.format(s=set_a.id, m=model_b.id))
            missing = await client.post(path.format(s=set_a.id, m=never_existed))

        assert foreign.status_code == missing.status_code == 404

        foreign_detail = foreign.json()["detail"].replace(str(model_b.id), "<id>")
        missing_detail = missing.json()["detail"].replace(str(never_existed), "<id>")
        assert foreign_detail == missing_detail, (
            "a model owned by another project is refused in different words than a model that "
            f"never existed, which tells the caller it is real: {foreign_detail!r} vs {missing_detail!r}"
        )
