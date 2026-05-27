# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Regression: GET /v1/projects/{id}/profile must auto-retrofit a
default profile for projects that never ran through the setup wizard,
instead of returning 404.

Source defect (user error log openconstructionerp-log-2026-05-22.json,
v4.3.2, locale fr-FR): 50 of 64 captured errors in a 2-minute session
were the same ``GET /v1/projects/{uuid}/profile -> 404`` firing on
every page navigation (/, /files, /bim, /correspondence, /modules,
…). The 404 response body even said "Run the wizard or GET /modules
to retrofit a default" — but the bare GET /profile didn't itself do
that retrofit. The sibling endpoint ``PATCH /profile/focus-mode``
already calls ``ensure_default_profile``; ``GET /modules`` does too.
Aligning ``GET /profile`` with that behaviour collapses the spam.

Tests in this file:
    1. GET on a project with no profile returns 200 with a usable
       default (was 404).
    2. Repeated GETs do not duplicate rows — ``ensure_default_profile``
       must be idempotent.
    3. POST /profile (apply_project_profile) is unaffected — it still
       upserts an explicit profile.
    4. The retrofitted shape matches what /profile/focus-mode produced
       previously (focus_mode_enabled=False, preset="custom").
"""

from __future__ import annotations

import tempfile
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
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
    tmp_db = Path(tempfile.mkdtemp()) / "profile_autoretrofit.db"
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


async def _seed_owner_and_bare_project(
    factory: async_sessionmaker[AsyncSession],
) -> tuple[uuid.UUID, uuid.UUID]:
    """Owner + project with NO ProjectProfile row — the exact state
    that used to produce a 404 on every page navigation."""
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    async with factory() as s:
        owner = User(
            id=uuid.uuid4(),
            email=f"owner-{uuid.uuid4().hex[:6]}@retrofit.io",
            hashed_password="x" * 60,
            full_name="Retrofit Owner",
            role="estimator",
            is_active=True,
            metadata_={},
        )
        s.add(owner)
        await s.flush()

        project = Project(
            id=uuid.uuid4(),
            owner_id=owner.id,
            name="Pre-wizard legacy project",
            status="active",
        )
        s.add(project)
        await s.commit()
        return owner.id, project.id


async def test_get_profile_on_bare_project_auto_retrofits_default(
    client: AsyncClient,
    temp_engine_and_factory,
) -> None:
    """A project with no ProjectProfile row used to 404. It must now
    silently retrofit a default and return 200 with a usable profile."""
    _engine, factory, _tmp = temp_engine_and_factory
    owner_id, project_id = await _seed_owner_and_bare_project(factory)
    _set_acting_user(owner_id)

    resp = await client.get(f"/api/v1/projects/{project_id}/profile")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    prof = body["profile"]
    # Matches what /profile/focus-mode already produced: ensure_default_profile
    # sets preset="custom" and focus_mode_enabled=False (legacy view).
    assert prof["preset"] == "custom"
    assert prof["focus_mode_enabled"] is False
    # Module list must be non-empty (every discoverable module assigned).
    assert isinstance(body["modules"], list)
    assert body["enabled_count"] >= 1, body


async def test_get_profile_is_idempotent_no_duplicate_rows(
    client: AsyncClient,
    temp_engine_and_factory,
) -> None:
    """Calling GET /profile twice on the same bare project must not
    create a second ProjectProfile row (idempotency contract — older
    builds would happily insert duplicates on each retrofit call)."""
    from app.modules.projects.models import ProjectModule, ProjectProfile

    _engine, factory, _tmp = temp_engine_and_factory
    owner_id, project_id = await _seed_owner_and_bare_project(factory)
    _set_acting_user(owner_id)

    r1 = await client.get(f"/api/v1/projects/{project_id}/profile")
    assert r1.status_code == 200, r1.text

    async with factory() as s:
        rows_after_first = (
            await s.execute(
                select(func.count(ProjectProfile.id)).where(
                    ProjectProfile.project_id == project_id,
                ),
            )
        ).scalar_one()
        modules_after_first = (
            await s.execute(
                select(func.count(ProjectModule.id)).where(
                    ProjectModule.project_id == project_id,
                ),
            )
        ).scalar_one()
    assert rows_after_first == 1

    r2 = await client.get(f"/api/v1/projects/{project_id}/profile")
    assert r2.status_code == 200, r2.text

    async with factory() as s:
        rows_after_second = (
            await s.execute(
                select(func.count(ProjectProfile.id)).where(
                    ProjectProfile.project_id == project_id,
                ),
            )
        ).scalar_one()
        modules_after_second = (
            await s.execute(
                select(func.count(ProjectModule.id)).where(
                    ProjectModule.project_id == project_id,
                ),
            )
        ).scalar_one()
    # Exactly one profile row before and after — no duplication.
    assert rows_after_second == 1, (rows_after_first, rows_after_second)
    # Module assignment rows must also not duplicate.
    assert modules_after_second == modules_after_first, (
        modules_after_first,
        modules_after_second,
    )

    # Response bodies must agree.
    assert r1.json()["profile"]["preset"] == r2.json()["profile"]["preset"]
    assert r1.json()["enabled_count"] == r2.json()["enabled_count"]


async def test_post_profile_still_creates_explicit_profile(
    client: AsyncClient,
    temp_engine_and_factory,
) -> None:
    """POST /profile (apply_project_profile) is independent of the GET
    retrofit and must keep working: it upserts the wizard answers and
    overwrites any retrofitted default."""
    from app.modules.projects.models import ProjectProfile

    _engine, factory, _tmp = temp_engine_and_factory
    owner_id, project_id = await _seed_owner_and_bare_project(factory)
    _set_acting_user(owner_id)

    body = {
        "preset": "bim_qc",
        "activity": ["construction"],
        "phases": ["design", "tender"],
        "role": "estimator",
        "size": "medium",
        "region": "DE",
        "language": "de",
        "extensions_enabled": [],
        "focus_mode_enabled": True,
        "setup_completion": {},
    }

    resp = await client.post(
        f"/api/v1/projects/{project_id}/profile",
        json=body,
    )
    assert resp.status_code == 200, resp.text
    out = resp.json()["profile"]
    assert out["preset"] == "bim_qc"
    assert out["focus_mode_enabled"] is True
    assert out["region"] == "DE"

    # Still exactly one ProjectProfile row.
    async with factory() as s:
        rows = (
            await s.execute(
                select(func.count(ProjectProfile.id)).where(
                    ProjectProfile.project_id == project_id,
                ),
            )
        ).scalar_one()
    assert rows == 1


async def test_retrofit_matches_focus_mode_default_shape(
    client: AsyncClient,
    temp_engine_and_factory,
) -> None:
    """The shape /profile auto-retrofits must equal the shape
    /profile/focus-mode would have produced — both paths share
    ``ensure_default_profile``. This locks the contract so future
    refactors can't drift one without the other.
    """
    _engine, factory, _tmp = temp_engine_and_factory

    # Project A — retrofit via GET /profile.
    owner_a, proj_a = await _seed_owner_and_bare_project(factory)
    _set_acting_user(owner_a)
    r_get = await client.get(f"/api/v1/projects/{proj_a}/profile")
    assert r_get.status_code == 200, r_get.text

    # Project B — retrofit via PATCH /profile/focus-mode (the prior
    # canonical retrofit entry point).
    owner_b, proj_b = await _seed_owner_and_bare_project(factory)
    _set_acting_user(owner_b)
    r_focus = await client.patch(
        f"/api/v1/projects/{proj_b}/profile/focus-mode",
        json={"focus_mode_enabled": False},
    )
    assert r_focus.status_code == 200, r_focus.text

    prof_get = r_get.json()["profile"]
    prof_focus = r_focus.json()["profile"]

    # Same defaults — preset, focus mode, and module-count semantics.
    assert prof_get["preset"] == prof_focus["preset"] == "custom"
    assert prof_get["focus_mode_enabled"] is False
    assert prof_focus["focus_mode_enabled"] is False
    assert r_get.json()["enabled_count"] == r_focus.json()["enabled_count"]
    # Both retrofitted projects expose the same set of modules.
    names_get = {m["module_name"] for m in r_get.json()["modules"]}
    names_focus = {m["module_name"] for m in r_focus.json()["modules"]}
    assert names_get == names_focus
