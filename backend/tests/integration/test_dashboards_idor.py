# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Integration tests — Dashboard rollup IDOR hardening (R7-style).

Verifies that a caller from one tenant cannot read another tenant's
dashboard widget data via the ``GET /api/v1/dashboard/rollup/`` endpoint.

IDOR posture (per router docstring):
  - Wrong-tenant project IDs are silently dropped from ``accessible_projects``.
  - The response returns 200 with an empty / zero payload, never the other
    tenant's data — never 403.

Coverage:
  1. Alice's rollup does NOT include Bob's BOQ totals.
  2. Alice's rollup scoped to Bob's project_id returns project_count=0.
  3. Malformed project_ids (garbage UUIDs) silently ignored → 200.
  4. Widget config validation via POST returns 422 on bad schema.
  5. Admin user sees all projects.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base
from app.dependencies import get_current_user_id, get_session

# ── Minimal model registration ─────────────────────────────────────────────


def _register_models() -> None:
    import app.modules.boq.models  # noqa: F401
    import app.modules.changeorders.models  # noqa: F401
    import app.modules.daily_diary.models  # noqa: F401
    import app.modules.finance.models  # noqa: F401
    import app.modules.procurement.models  # noqa: F401
    import app.modules.projects.models  # noqa: F401
    import app.modules.safety.models  # noqa: F401
    import app.modules.users.models  # noqa: F401
    import app.modules.validation.models  # noqa: F401


# ── FastAPI app factory ────────────────────────────────────────────────────


def _build_app(session_factory: async_sessionmaker, caller_id: uuid.UUID) -> FastAPI:
    """Minimal app with dashboard router and injected auth."""
    from app.modules.dashboard.router import router as dash_router

    app = FastAPI()

    async def _override_session() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as s:
            yield s

    def _override_user():
        return str(caller_id)

    app.dependency_overrides[get_session] = _override_session
    # CurrentUserId depends on get_current_user_id — override the direct
    # dependency so we bypass JWT decoding entirely in tests.
    app.dependency_overrides[get_current_user_id] = _override_user
    app.include_router(dash_router, prefix="/api/v1/dashboard")
    return app


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db_factory():
    tmp_db = Path(tempfile.mkdtemp()) / "idor_dash.db"
    url = f"sqlite+aiosqlite:///{tmp_db.as_posix()}"
    engine = create_async_engine(url, future=True)

    _register_models()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()
    try:
        tmp_db.unlink(missing_ok=True)
        tmp_db.parent.rmdir()
    except OSError:
        pass


async def _seed_user(
    session: AsyncSession,
    *,
    role: str = "member",
) -> uuid.UUID:
    from app.modules.users.models import User

    uid = uuid.uuid4()
    session.add(
        User(
            id=uid,
            email=f"u-{uid.hex[:6]}@idor.io",
            hashed_password="x",
            full_name="Test",
            role=role,
        )
    )
    await session.flush()
    return uid


async def _seed_project(
    session: AsyncSession,
    owner_id: uuid.UUID,
    *,
    name: str = "Project",
) -> uuid.UUID:
    from app.modules.projects.models import Project

    pid = uuid.uuid4()
    session.add(
        Project(
            id=pid,
            name=name,
            owner_id=owner_id,
            status="active",
            currency="EUR",
        )
    )
    await session.flush()
    return pid


async def _seed_boq_with_value(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    total: str = "99999.00",
) -> None:
    from app.modules.boq.models import BOQ, Position

    boq = BOQ(id=uuid.uuid4(), project_id=project_id, name="BOQ", status="draft")
    session.add(boq)
    await session.flush()
    session.add(
        Position(
            boq_id=boq.id,
            ordinal="01",
            description="Secret position",
            unit="m2",
            quantity="1",
            unit_rate=total,
            total=total,
        )
    )
    await session.flush()


# ── Test cases ────────────────────────────────────────────────────────────


class TestDashboardIDOR:
    @pytest.mark.asyncio
    async def test_alice_rollup_excludes_bobs_boq_value(
        self,
        db_factory: async_sessionmaker,
    ) -> None:
        """Alice's rollup total must not include Bob's BOQ value."""
        async with db_factory() as session:
            alice_id = await _seed_user(session)
            bob_id = await _seed_user(session)
            alice_project = await _seed_project(session, alice_id, name="Alice-P")
            bob_project = await _seed_project(session, bob_id, name="Bob-P")
            await _seed_boq_with_value(session, alice_project, total="1000.00")
            await _seed_boq_with_value(session, bob_project, total="99999.00")
            await session.commit()

        # Authenticate as Alice.
        app = _build_app(db_factory, alice_id)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/dashboard/rollup/",
                params={"widgets": "boq_summary"},
            )
        assert resp.status_code == 200
        data = resp.json()
        boq = data.get("boq_summary", {})
        # Alice has 1 project → 1 BOQ → total 1 000; Bob's 99 999 must not leak.
        total_val = boq.get("total_value_eur", "0")
        from decimal import Decimal

        assert Decimal(total_val) < Decimal("10000"), f"Bob's BOQ value leaked into Alice's rollup: {total_val}"

    @pytest.mark.asyncio
    async def test_scoping_to_bobs_project_returns_zero(
        self,
        db_factory: async_sessionmaker,
    ) -> None:
        """Alice scopes rollup to Bob's project_id → project_count=0, empty data."""
        async with db_factory() as session:
            alice_id = await _seed_user(session)
            bob_id = await _seed_user(session)
            _alice_proj = await _seed_project(session, alice_id, name="Alice-P")
            bob_proj = await _seed_project(session, bob_id, name="Bob-P")
            await session.commit()

        app = _build_app(db_factory, alice_id)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/dashboard/rollup/",
                params={
                    "widgets": "boq_summary",
                    "project_ids": str(bob_proj),
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("project_count", -1) == 0, "Scoping to another tenant's project_id must yield project_count=0"

    @pytest.mark.asyncio
    async def test_garbage_project_ids_ignored(
        self,
        db_factory: async_sessionmaker,
    ) -> None:
        """Malformed UUIDs in project_ids → 200 with zero results, not 422/500."""
        async with db_factory() as session:
            alice_id = await _seed_user(session)
            await _seed_project(session, alice_id)
            await session.commit()

        app = _build_app(db_factory, alice_id)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/dashboard/rollup/",
                params={
                    "widgets": "boq_summary",
                    "project_ids": "not-a-uuid,also-bad,12345",
                },
            )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_sees_both_tenants(
        self,
        db_factory: async_sessionmaker,
    ) -> None:
        """Admin rollup aggregates across all tenants."""
        async with db_factory() as session:
            admin_id = await _seed_user(session, role="admin")
            alice_id = await _seed_user(session)
            bob_id = await _seed_user(session)
            _pa = await _seed_project(session, alice_id, name="Alice-P")
            _pb = await _seed_project(session, bob_id, name="Bob-P")
            await session.commit()

        app = _build_app(db_factory, admin_id)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/dashboard/rollup/",
                params={"widgets": "boq_summary"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("project_count", 0) >= 2, "Admin must see at least the two seeded projects"

    @pytest.mark.asyncio
    async def test_post_rollup_bad_widget_config_returns_422(
        self,
        db_factory: async_sessionmaker,
    ) -> None:
        """POST /rollup/ with unknown config key returns 422 before any DB query."""
        async with db_factory() as session:
            alice_id = await _seed_user(session)
            await session.commit()

        app = _build_app(db_factory, alice_id)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/dashboard/rollup/",
                json={
                    "widgets": ["boq_summary"],
                    "widget_configs": [
                        {
                            "widget_id": "boq_summary",
                            "config": {"evil_injection_key": True},
                        }
                    ],
                },
            )
        assert resp.status_code == 422, f"Expected 422 for unknown config key, got {resp.status_code}"

    @pytest.mark.asyncio
    async def test_post_rollup_unknown_widget_id_returns_422(
        self,
        db_factory: async_sessionmaker,
    ) -> None:
        """POST /rollup/ with unknown widget_id returns 422."""
        async with db_factory() as session:
            alice_id = await _seed_user(session)
            await session.commit()

        app = _build_app(db_factory, alice_id)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/dashboard/rollup/",
                json={
                    "widget_configs": [
                        {"widget_id": "fake_widget", "config": {}},
                    ],
                },
            )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_post_rollup_valid_config_returns_200(
        self,
        db_factory: async_sessionmaker,
    ) -> None:
        """POST /rollup/ with valid config returns 200."""
        async with db_factory() as session:
            alice_id = await _seed_user(session)
            await _seed_project(session, alice_id)
            await session.commit()

        app = _build_app(db_factory, alice_id)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/dashboard/rollup/",
                json={
                    "widgets": ["boq_summary"],
                    "widget_configs": [
                        {
                            "widget_id": "boq_summary",
                            "config": {"show_last_boq": True, "max_by_project": 10},
                        },
                    ],
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "boq_summary" in data
