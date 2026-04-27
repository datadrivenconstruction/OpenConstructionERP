# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""T10 integration tests — Multi-Source Project Federation API.

Stands up a minimal FastAPI app with the dashboards router + a
``LocalStorageBackend`` rooted in a temp dir, seeds two snapshots'
worth of parquet rows, and exercises the federation endpoints.

Coverage:

* POST /federation/build — happy path, returns provenance counts +
  reconciled column list
* POST /federation/build — empty snapshot_ids → 422
* POST /federation/build — missing snapshot id → 404
* POST /federation/aggregate — count rollup includes provenance
* POST /federation/aggregate — invalid measure → 422
* Tenant isolation — caller from another tenant cannot federate the
  first tenant's snapshots (404 surfaces as snapshot.not_found)
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import AsyncGenerator

import pandas as pd
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.storage import LocalStorageBackend
from app.database import Base
from app.dependencies import get_current_user_payload, get_session
from app.modules.dashboards.models import Snapshot
from app.modules.dashboards.snapshot_storage import write_parquet

# ── Helpers ────────────────────────────────────────────────────────────────


def _register_minimal_models() -> None:
    """Pull dashboards + FK-target modules into Base.metadata."""
    import app.modules.dashboards.models  # noqa: F401
    import app.modules.projects.models  # noqa: F401
    import app.modules.users.models  # noqa: F401


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def temp_engine_and_factory():
    tmp_db = Path(tempfile.mkdtemp()) / "federation_api.db"
    url = f"sqlite+aiosqlite:///{tmp_db.as_posix()}"
    engine = create_async_engine(url, future=True)

    _register_minimal_models()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False,
    )
    yield engine, factory, tmp_db
    await engine.dispose()
    try:
        tmp_db.unlink(missing_ok=True)
        tmp_db.parent.rmdir()
    except OSError:
        pass


@pytest_asyncio.fixture
async def storage_dir() -> AsyncGenerator[Path, None]:
    """Temp directory for the federation parquet files."""
    d = Path(tempfile.mkdtemp())
    yield d
    # Best-effort cleanup — Windows sometimes holds parquet handles
    # open if a connection didn't close. The test temp_path is fine
    # to leak in that case.
    import shutil

    shutil.rmtree(d, ignore_errors=True)


@pytest_asyncio.fixture
async def local_backend(storage_dir: Path) -> LocalStorageBackend:
    return LocalStorageBackend(base_dir=storage_dir)


_current_user_payload: dict[str, str] = {}


@pytest_asyncio.fixture
async def app(temp_engine_and_factory, local_backend, monkeypatch) -> AsyncGenerator[FastAPI, None]:
    _engine, factory, _tmp = temp_engine_and_factory

    # Federation reads parquet through the global storage backend
    # accessor — point it at our temp local backend for the test.
    monkeypatch.setattr(
        "app.modules.dashboards.snapshot_storage.get_storage_backend",
        lambda: local_backend,
    )

    from app.modules.dashboards.router import router as dashboards_router

    app = FastAPI()
    app.include_router(dashboards_router, prefix="/api/v1/dashboards")

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

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user_payload] = _override_payload

    yield app


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def user_a() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def user_b() -> uuid.UUID:
    return uuid.uuid4()


def _set_acting_user(user_id: uuid.UUID, tenant_id: str | None = None) -> None:
    _current_user_payload.clear()
    _current_user_payload["sub"] = str(user_id)
    _current_user_payload["tenant_id"] = tenant_id or str(user_id)


async def _ensure_user_and_project(
    factory,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
) -> None:
    """Idempotently insert the User + Project rows the FKs need.

    The dashboards Snapshot model references both
    ``oe_users_user.id`` and ``oe_projects_project.id`` via ON-DELETE
    CASCADE foreign keys, so SQLite (with FK enforcement on by default
    in our test bootstrap) refuses inserts that lack a parent row.
    """
    from sqlalchemy import select

    from app.modules.projects.models import Project
    from app.modules.users.models import User

    async with factory() as s:
        existing_user = (
            await s.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if existing_user is None:
            s.add(
                User(
                    id=user_id,
                    email=f"user-{user_id}@test.local",
                    hashed_password="x",
                    full_name="Test",
                    role="editor",
                )
            )
            await s.commit()

    async with factory() as s:
        existing_project = (
            await s.execute(
                select(Project).where(Project.id == project_id)
            )
        ).scalar_one_or_none()
        if existing_project is None:
            s.add(
                Project(
                    id=project_id,
                    name=f"Project-{project_id}",
                    description="",
                    region="DACH",
                    classification_standard="din276",
                    currency="EUR",
                    locale="de",
                    validation_rule_sets=["boq_quality"],
                    status="active",
                    owner_id=user_id,
                )
            )
            await s.commit()


async def _seed_snapshot(
    factory,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    label: str,
    rows: list[dict],
    tenant_id: str,
    backend: LocalStorageBackend,
) -> uuid.UUID:
    """Insert a Snapshot row + write its entities parquet file."""
    await _ensure_user_and_project(
        factory, user_id=user_id, project_id=project_id,
    )

    snapshot_id = uuid.uuid4()
    async with factory() as s:
        snap = Snapshot(
            id=snapshot_id,
            project_id=project_id,
            tenant_id=tenant_id,
            label=label,
            parquet_dir=f"dashboards/{project_id}/{snapshot_id}",
            total_entities=len(rows),
            total_categories=len({r.get("category") for r in rows if r.get("category")}),
            summary_stats={},
            source_files_json=[],
            created_by_user_id=user_id,
        )
        s.add(snap)
        await s.commit()

    df = pd.DataFrame(rows)
    await write_parquet(project_id, snapshot_id, "entities", df, backend=backend)
    return snapshot_id


# ── Tests ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_build_happy_path_intersect(
    client: AsyncClient,
    temp_engine_and_factory,
    local_backend: LocalStorageBackend,
    user_a: uuid.UUID,
) -> None:
    _engine, factory, _tmp = temp_engine_and_factory
    _set_acting_user(user_a)
    project_id = uuid.uuid4()

    s1 = await _seed_snapshot(
        factory,
        user_id=user_a,
        project_id=project_id,
        label="Baseline",
        rows=[
            {"entity_guid": "g1", "category": "wall", "area_m2": 10.0},
            {"entity_guid": "g2", "category": "door", "area_m2": 2.0},
        ],
        tenant_id=str(user_a),
        backend=local_backend,
    )
    s2 = await _seed_snapshot(
        factory,
        user_id=user_a,
        project_id=project_id,
        label="Updated",
        rows=[
            {"entity_guid": "g3", "category": "wall", "area_m2": 25.0},
        ],
        tenant_id=str(user_a),
        backend=local_backend,
    )

    resp = await client.post(
        "/api/v1/dashboards/federation/build",
        json={
            "snapshot_ids": [str(s1), str(s2)],
            "schema_align": "intersect",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["snapshot_count"] == 2
    assert body["project_count"] == 1
    assert body["row_count"] == 3
    assert "__project_id" in body["columns"]
    assert "__snapshot_id" in body["columns"]
    assert "category" in body["columns"]


@pytest.mark.asyncio
async def test_build_empty_snapshot_ids_rejected(
    client: AsyncClient,
    user_a: uuid.UUID,
) -> None:
    _set_acting_user(user_a)
    resp = await client.post(
        "/api/v1/dashboards/federation/build",
        json={"snapshot_ids": [], "schema_align": "intersect"},
    )
    # Pydantic min_length=1 rejects → 422.
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_build_missing_snapshot_returns_404(
    client: AsyncClient,
    user_a: uuid.UUID,
) -> None:
    _set_acting_user(user_a)
    ghost = uuid.uuid4()
    resp = await client.post(
        "/api/v1/dashboards/federation/build",
        json={
            "snapshot_ids": [str(ghost)],
            "schema_align": "intersect",
        },
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_aggregate_count_with_provenance(
    client: AsyncClient,
    temp_engine_and_factory,
    local_backend: LocalStorageBackend,
    user_a: uuid.UUID,
) -> None:
    _engine, factory, _tmp = temp_engine_and_factory
    _set_acting_user(user_a)
    project_id = uuid.uuid4()

    s1 = await _seed_snapshot(
        factory,
        user_id=user_a,
        project_id=project_id,
        label="Q1",
        rows=[
            {"entity_guid": "g1", "category": "wall", "area_m2": 10.0},
            {"entity_guid": "g2", "category": "wall", "area_m2": 12.0},
            {"entity_guid": "g3", "category": "door", "area_m2": 2.0},
        ],
        tenant_id=str(user_a),
        backend=local_backend,
    )
    s2 = await _seed_snapshot(
        factory,
        user_id=user_a,
        project_id=project_id,
        label="Q2",
        rows=[
            {"entity_guid": "g4", "category": "wall", "area_m2": 20.0},
        ],
        tenant_id=str(user_a),
        backend=local_backend,
    )

    resp = await client.post(
        "/api/v1/dashboards/federation/aggregate",
        json={
            "snapshot_ids": [str(s1), str(s2)],
            "schema_align": "intersect",
            "group_by": ["category"],
            "measure": "*",
            "agg": "count",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["snapshot_count"] == 2
    assert body["agg"] == "count"
    # Every row has provenance.
    for row in body["rows"]:
        assert "__project_id" in row
        assert "__snapshot_id" in row
        assert "category" in row
        assert "measure_value" in row
    total = sum(int(r["measure_value"]) for r in body["rows"])
    assert total == 4


@pytest.mark.asyncio
async def test_aggregate_invalid_measure_returns_422(
    client: AsyncClient,
    temp_engine_and_factory,
    local_backend: LocalStorageBackend,
    user_a: uuid.UUID,
) -> None:
    _engine, factory, _tmp = temp_engine_and_factory
    _set_acting_user(user_a)
    project_id = uuid.uuid4()

    s1 = await _seed_snapshot(
        factory,
        user_id=user_a,
        project_id=project_id,
        label="Only",
        rows=[{"entity_guid": "g1", "category": "wall", "area_m2": 10.0}],
        tenant_id=str(user_a),
        backend=local_backend,
    )

    resp = await client.post(
        "/api/v1/dashboards/federation/aggregate",
        json={
            "snapshot_ids": [str(s1)],
            "schema_align": "intersect",
            "group_by": [],
            "measure": "no_such_column",
            "agg": "sum",
        },
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_tenant_b_cannot_federate_tenant_a_snapshots(
    client: AsyncClient,
    temp_engine_and_factory,
    local_backend: LocalStorageBackend,
    user_a: uuid.UUID,
    user_b: uuid.UUID,
) -> None:
    """Federation must surface 404 (snapshot.not_found) when a caller
    references a snapshot owned by another tenant — same defence as
    every other dashboards endpoint."""
    _engine, factory, _tmp = temp_engine_and_factory
    project_id = uuid.uuid4()

    # Tenant A seeds.
    _set_acting_user(user_a, tenant_id=str(user_a))
    s1 = await _seed_snapshot(
        factory,
        user_id=user_a,
        project_id=project_id,
        label="Tenant-A-only",
        rows=[{"entity_guid": "g1", "category": "wall", "area_m2": 10.0}],
        tenant_id=str(user_a),
        backend=local_backend,
    )

    # Tenant B (different tenant) tries to read.
    _set_acting_user(user_b, tenant_id=str(user_b))
    resp = await client.post(
        "/api/v1/dashboards/federation/build",
        json={
            "snapshot_ids": [str(s1)],
            "schema_align": "intersect",
        },
    )
    assert resp.status_code == 404, resp.text
