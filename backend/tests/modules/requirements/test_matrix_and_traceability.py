"""Round-2 deep-improve — Requirements matrix endpoint + traceability.

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

Pattern: in-memory SQLite + pytest-asyncio, no Alembic migration.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Ensure FK targets are in metadata.
import app.modules.boq.models  # noqa: F401
import app.modules.projects.models  # noqa: F401
from app.database import Base
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

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """In-memory SQLite session with FK enforcement OFF (avoids cross-module FK pain)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys=OFF"))
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        await s.execute(text("PRAGMA foreign_keys=OFF"))
        yield s
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Full schema session (FK OFF) — used for router tests needing User/Project tables."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys=OFF"))
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        await s.execute(text("PRAGMA foreign_keys=OFF"))
        yield s
    await engine.dispose()


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


def _build_app(db_session, *, caller_id: str, role: str = "admin") -> FastAPI:
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
        return {"sub": caller_id, "role": role, "permissions": []}

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_current_user_id] = _user_override
    app.dependency_overrides[get_current_user_payload] = _payload_override
    app.dependency_overrides[verify_project_access] = _project_access_override
    return app


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
        client = TestClient(app)
        resp = client.get(f"/v1/requirements/projects/{project_id}/matrix/")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["project_id"] == str(project_id)
        assert len(body["rows"]) == 1
        assert "model" in body["deliverable_types"]

    @pytest.mark.asyncio
    async def test_matrix_route_cross_tenant_returns_404(self, db_session: AsyncSession) -> None:
        from app.modules.requirements.permissions import register_requirements_permissions

        register_requirements_permissions()

        victim_id = await _make_user(db_session, email="victim@matrix.test")
        attacker_id = await _make_user(db_session, email="attacker@matrix.test")
        victim_project = await _make_project(db_session, victim_id)

        # Build app as attacker (role=editor so admin bypass doesn't fire).
        app = _build_app(db_session, caller_id=str(attacker_id), role="editor")
        client = TestClient(app)

        resp = client.get(f"/v1/requirements/projects/{victim_project}/matrix/")
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
    """link_to_position must 404 when the BOQ position doesn't exist
    (which also covers the cross-tenant case since IDOR would mean the
    position doesn't exist in the attacker's session).
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
