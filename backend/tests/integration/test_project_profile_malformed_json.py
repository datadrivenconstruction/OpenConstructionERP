# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Regression: GET /v1/projects/{id}/profile must survive a
``ProjectProfile`` whose JSON columns hold scalars instead of the
declared list / dict shape.

Real shipped defect (observed live, demo session, 3× HTTP 500): the
showcase "gap-fill" seed persisted profiles with ``activity =
"construction"`` (a bare string) and ``setup_completion = 1`` (an int).
``profile_service._to_profile_read`` did ``dict(row.setup_completion or
{})`` → ``dict(1)`` → ``TypeError: 'int' object is not iterable`` →
unhandled 500. ``list(row.activity or [])`` separately exploded the
string into single characters.

This drives the real ``projects`` router over HTTP against a temp
SQLite DB, plants the exact malformed state, and asserts the endpoint
returns 200 with a contract-correct payload (activity is a clean
``["construction"]``, setup_completion is a dict).
"""

from __future__ import annotations

import tempfile
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def _register_minimal_models() -> None:
    import app.core.audit  # noqa: F401
    import app.modules.projects.models  # noqa: F401
    import app.modules.users.models  # noqa: F401


@pytest_asyncio.fixture
async def temp_engine_and_factory():
    tmp_db = Path(tempfile.mkdtemp()) / "profile_malformed_json.db"
    url = f"sqlite+aiosqlite:///{tmp_db.as_posix()}"
    engine = create_async_engine(url, future=True)

    _register_minimal_models()

    from app.database import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    yield engine, factory, tmp_db

    await engine.dispose()
    try:
        tmp_db.unlink(missing_ok=True)
        tmp_db.parent.rmdir()
    except OSError:
        pass


_current_user_payload: dict[str, str] = {}


@pytest_asyncio.fixture
async def app(temp_engine_and_factory) -> AsyncGenerator[FastAPI, None]:
    _engine, factory, _tmp = temp_engine_and_factory

    from app.dependencies import (
        get_current_user_id,
        get_current_user_payload,
        get_session,
    )
    from app.modules.projects.router import router as projects_router

    fastapi_app = FastAPI()
    fastapi_app.include_router(projects_router, prefix="/api/v1/projects")

    async def _override_session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def _override_payload() -> dict[str, str]:
        return dict(_current_user_payload)

    async def _override_user_id() -> str:
        return _current_user_payload.get("sub", "")

    fastapi_app.dependency_overrides[get_session] = _override_session
    fastapi_app.dependency_overrides[get_current_user_payload] = _override_payload
    fastapi_app.dependency_overrides[get_current_user_id] = _override_user_id

    yield fastapi_app


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _set_acting_user(user_id: uuid.UUID) -> None:
    _current_user_payload.clear()
    _current_user_payload["sub"] = str(user_id)
    _current_user_payload["role"] = "estimator"


async def _seed_malformed_profile(
    factory: async_sessionmaker[AsyncSession],
) -> tuple[uuid.UUID, uuid.UUID]:
    """Owner + project + a ProjectProfile carrying the exact bad shipped
    JSON-column state, plus a couple of ProjectModule rows."""
    from app.modules.projects.models import (
        Project,
        ProjectModule,
        ProjectProfile,
    )
    from app.modules.users.models import User

    async with factory() as s:
        owner = User(
            id=uuid.uuid4(),
            email=f"owner-{uuid.uuid4().hex[:6]}@profmal.io",
            hashed_password="x" * 60,
            full_name="Profile Malformed Owner",
            role="estimator",
            is_active=True,
            metadata_={},
        )
        s.add(owner)
        await s.flush()

        project = Project(
            id=uuid.uuid4(),
            owner_id=owner.id,
            name="Edifício Comercial — gap-fill seed",
            status="active",
        )
        s.add(project)
        await s.flush()

        prof = ProjectProfile(
            project_id=project.id,
            preset="commercial",
            role="estimator",
            size="large",
            region="PT_SAOPAULO",
            language="pt",
            focus_mode_enabled=False,
        )
        # The defect-triggering state (mirrors prod openestimate.db
        # seed metadata "gapfill-20260516"):
        prof.activity = "construction"  # bare str, not ["construction"]
        prof.phases = ["design", "tender"]  # this one was well-formed
        prof.extensions_enabled = ["bim"]
        prof.setup_completion = 1  # int, not a dict  → dict(1) 500
        s.add(prof)

        s.add(
            ProjectModule(
                project_id=project.id,
                module_name="projects",
                enabled=True,
                tier="core",
                score=1,
                phase="design",
                source="profile",
                ordinal=0,
                why="seed",
            )
        )
        s.add(
            ProjectModule(
                project_id=project.id,
                module_name="boq",
                enabled=True,
                tier="core",
                score=1,
                phase="tender",
                source="profile",
                ordinal=1,
                why="seed",
            )
        )
        await s.commit()
        return owner.id, project.id


async def test_get_profile_with_scalar_json_columns_returns_200(
    client: AsyncClient,
    temp_engine_and_factory,
) -> None:
    _engine, factory, _tmp = temp_engine_and_factory
    owner_id, project_id = await _seed_malformed_profile(factory)
    _set_acting_user(owner_id)

    resp = await client.get(f"/api/v1/projects/{project_id}/profile")

    assert resp.status_code == 200, resp.text
    body = resp.json()

    prof = body["profile"]
    # setup_completion (was int 1 → dict(1) TypeError → 500) is now a dict.
    assert isinstance(prof["setup_completion"], dict)
    assert prof["setup_completion"] == {}
    # activity ("construction" str) is coerced to a clean one-element
    # list — NOT exploded into ['c','o','n','s',...].
    assert prof["activity"] == ["construction"]
    assert prof["phases"] == ["design", "tender"]
    assert prof["extensions_enabled"] == ["bim"]
    assert prof["preset"] == "commercial"
    assert prof["focus_mode_enabled"] is False

    # Module list / counts contract preserved.
    assert body["enabled_count"] == 2
    assert {m["module_name"] for m in body["modules"]} == {"projects", "boq"}


async def test_get_profile_with_none_json_columns_returns_200(
    client: AsyncClient,
    temp_engine_and_factory,
) -> None:
    """A profile with NULL JSON columns must also be safe (defensive —
    server_default backfills are not guaranteed on legacy rows)."""
    from app.modules.projects.models import Project, ProjectProfile
    from app.modules.users.models import User

    _engine, factory, _tmp = temp_engine_and_factory
    async with factory() as s:
        owner = User(
            id=uuid.uuid4(),
            email=f"owner-{uuid.uuid4().hex[:6]}@profnull.io",
            hashed_password="x" * 60,
            full_name="Null Owner",
            role="estimator",
            is_active=True,
            metadata_={},
        )
        s.add(owner)
        await s.flush()
        project = Project(
            id=uuid.uuid4(),
            owner_id=owner.id,
            name="Null JSON project",
            status="active",
        )
        s.add(project)
        await s.flush()
        prof = ProjectProfile(project_id=project.id, preset="custom")
        prof.activity = None
        prof.phases = None
        prof.extensions_enabled = None
        prof.setup_completion = None
        s.add(prof)
        await s.commit()
        owner_id, project_id = owner.id, project.id

    _set_acting_user(owner_id)
    resp = await client.get(f"/api/v1/projects/{project_id}/profile")

    assert resp.status_code == 200, resp.text
    prof_body = resp.json()["profile"]
    assert prof_body["activity"] == []
    assert prof_body["phases"] == []
    assert prof_body["extensions_enabled"] == []
    assert prof_body["setup_completion"] == {}
