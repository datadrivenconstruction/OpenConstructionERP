# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tests for the BIM Federation feature (v4.0 / Slice 1).

Per ``feedback_test_isolation.md`` every test uses a per-test temp
SQLite — never the production / shared test DB.

Coverage
--------
* test_create_federation
* test_add_model_to_federation
* test_list_federations_filtered_by_project
* test_federation_detail_returns_models_ordered_by_z
* test_cannot_access_other_project_federation
* test_delete_cascades_member_links
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base
from app.modules.bim_hub.models import (
    BIMFederation,
    BIMFederationModel,
    BIMModel,
)
from app.modules.bim_hub.schemas import (
    FederationCreate,
    FederationModelAdd,
    FederationOriginOffset,
)
from app.modules.bim_hub.service import BIMHubService


def _register_models() -> None:
    """Eagerly register every ORM module referenced by the test DB."""
    import app.modules.bim_hub.models  # noqa: F401
    import app.modules.boq.models  # noqa: F401
    import app.modules.projects.models  # noqa: F401
    import app.modules.users.models  # noqa: F401


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Spin up an isolated SQLite, register the schema, yield a session.

    Two projects are pre-seeded under two distinct owners so the
    cross-tenant test can probe the project-access guard without
    additional setup.
    """
    tmp_db = Path(tempfile.mkdtemp(prefix="oe-bim-fed-")) / "fed.db"
    url = f"sqlite+aiosqlite:///{tmp_db.as_posix()}"
    engine = create_async_engine(url, future=True)

    # Enforce ON DELETE CASCADE on SQLite — without this the FK is
    # advisory only and the cascade test would silently no-op.
    from sqlalchemy import event as sa_event
    from sqlalchemy.engine import Engine

    @sa_event.listens_for(Engine, "connect")
    def _fk_on(dbapi_conn: object, _: object) -> None:
        cursor = dbapi_conn.cursor()  # type: ignore[union-attr]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    _register_models()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
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
        # Attach handy refs onto the session so tests can grab them
        # without re-querying.
        s.info["project_a_id"] = project_a.id
        s.info["project_b_id"] = project_b.id
        s.info["owner_a_id"] = str(owner_a.id)
        s.info["owner_b_id"] = str(owner_b.id)
        yield s
    await engine.dispose()
    try:
        tmp_db.unlink(missing_ok=True)
        tmp_db.parent.rmdir()
    except OSError:
        pass


async def _seed_bim_model(
    session: AsyncSession,
    project_id: uuid.UUID,
    name: str = "Test model",
    discipline: str | None = None,
) -> BIMModel:
    """Insert a minimal BIMModel row so federation members have something to link."""
    model = BIMModel(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        discipline=discipline,
        version="1",
        status="ready",
    )
    session.add(model)
    await session.commit()
    return model


# ── 1. Create federation ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_federation(session: AsyncSession) -> None:
    """``create_federation`` persists a header with shared origin + units."""
    project_id: uuid.UUID = session.info["project_a_id"]
    service = BIMHubService(session)
    payload = FederationCreate(
        project_id=project_id,
        name="Coordination Federation",
        description="Arch + Struct + MEP",
        origin_offset=FederationOriginOffset(x=0.0, y=0.0, z=0.0),
        shared_units="m",
    )
    response = await service.create_federation(payload)
    await session.commit()

    assert response.id is not None
    assert response.project_id == project_id
    assert response.name == "Coordination Federation"
    assert response.shared_units == "m"
    assert response.member_count == 0
    assert response.origin_offset == {"x": 0.0, "y": 0.0, "z": 0.0}

    # Round-trip — the row really lives in the DB.
    stmt = select(BIMFederation).where(BIMFederation.id == response.id)
    row = (await session.execute(stmt)).scalar_one()
    assert row.name == "Coordination Federation"


# ── 2. Add model to federation ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_model_to_federation(session: AsyncSession) -> None:
    """``add_federation_member`` binds an existing BIMModel via the link table."""
    project_id: uuid.UUID = session.info["project_a_id"]
    service = BIMHubService(session)
    federation = await service.create_federation(FederationCreate(project_id=project_id, name="Coord-1"))
    model = await _seed_bim_model(session, project_id, name="ARCH-01")

    member = await service.add_federation_member(
        federation.id,
        FederationModelAdd(
            bim_model_id=model.id,
            discipline="arch",
            color_hint="#8b5cf6",
            visible=True,
            z_order=0,
        ),
    )
    await session.commit()

    assert member.federation_id == federation.id
    assert member.bim_model_id == model.id
    assert member.discipline == "arch"
    assert member.color_hint == "#8b5cf6"
    assert member.visible is True
    assert member.z_order == 0

    # Duplicate add must 409 (UniqueConstraint).
    with pytest.raises(HTTPException) as exc:
        await service.add_federation_member(
            federation.id,
            FederationModelAdd(bim_model_id=model.id, discipline="arch"),
        )
    assert exc.value.status_code == 409


# ── 3. List filters by project ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_federations_filtered_by_project(session: AsyncSession) -> None:
    """``list_federations`` only returns federations of the requested project."""
    project_a: uuid.UUID = session.info["project_a_id"]
    project_b: uuid.UUID = session.info["project_b_id"]
    service = BIMHubService(session)

    await service.create_federation(FederationCreate(project_id=project_a, name="A1"))
    await service.create_federation(FederationCreate(project_id=project_a, name="A2"))
    await service.create_federation(FederationCreate(project_id=project_b, name="B1"))
    await session.commit()

    items_a, total_a = await service.list_federations(project_a)
    items_b, total_b = await service.list_federations(project_b)

    assert total_a == 2
    assert total_b == 1
    assert {f.name for f in items_a} == {"A1", "A2"}
    assert {f.name for f in items_b} == {"B1"}
    # Cross-project leak guard — none of B's rows show up in A's list.
    assert all(f.project_id == project_a for f in items_a)
    assert all(f.project_id == project_b for f in items_b)


# ── 4. Detail returns members ordered by z_order ──────────────────────────


@pytest.mark.asyncio
async def test_federation_detail_returns_models_ordered_by_z(
    session: AsyncSession,
) -> None:
    """The detail response orders ``members`` by ``z_order`` ascending."""
    project_id: uuid.UUID = session.info["project_a_id"]
    service = BIMHubService(session)
    federation = await service.create_federation(FederationCreate(project_id=project_id, name="ZSort"))
    m_top = await _seed_bim_model(session, project_id, name="MEP")
    m_mid = await _seed_bim_model(session, project_id, name="STRUCT")
    m_bot = await _seed_bim_model(session, project_id, name="ARCH")

    # Insert intentionally out of order so the sort is doing work.
    await service.add_federation_member(
        federation.id,
        FederationModelAdd(bim_model_id=m_top.id, discipline="mep", z_order=5),
    )
    await service.add_federation_member(
        federation.id,
        FederationModelAdd(bim_model_id=m_bot.id, discipline="arch", z_order=0),
    )
    await service.add_federation_member(
        federation.id,
        FederationModelAdd(bim_model_id=m_mid.id, discipline="struct", z_order=2),
    )
    await session.commit()

    full = await service.get_federation_full(federation.id)
    assert full.member_count == 3
    z_orders = [m.z_order for m in full.members]
    assert z_orders == sorted(z_orders) == [0, 2, 5]
    # And the bim_model ids line up with the expected order.
    assert [m.bim_model_id for m in full.members] == [
        m_bot.id,
        m_mid.id,
        m_top.id,
    ]


# ── 5. Cross-project access is denied ──────────────────────────────────────


@pytest.mark.asyncio
async def test_cannot_access_other_project_federation(
    session: AsyncSession,
) -> None:
    """Project A's owner cannot fetch federations belonging to Project B.

    The router-level guard is ``_verify_project_access`` which 404s on
    cross-project IDs. We exercise it directly here because the test runs
    without the FastAPI dependency graph.
    """
    project_a: uuid.UUID = session.info["project_a_id"]
    project_b: uuid.UUID = session.info["project_b_id"]
    owner_a: str = session.info["owner_a_id"]

    service = BIMHubService(session)
    fed_b = await service.create_federation(FederationCreate(project_id=project_b, name="B-private"))
    await session.commit()

    # The federation exists and we can load it directly — the *guard*
    # is what blocks access.
    federation = await service.get_federation(fed_b.id)
    assert federation.project_id == project_b

    from app.modules.bim_hub.router import _verify_project_access

    with pytest.raises(HTTPException) as exc:
        await _verify_project_access(session, federation.project_id, owner_a)
    assert exc.value.status_code == 404

    # Same guard against a totally synthetic UUID for completeness —
    # missing and forbidden both surface as 404 to avoid enumeration.
    with pytest.raises(HTTPException) as exc:
        await _verify_project_access(session, uuid.uuid4(), owner_a)
    assert exc.value.status_code == 404

    # Sanity: A's list of A's federations is still empty (no leak).
    items_a, total_a = await service.list_federations(project_a)
    assert total_a == 0
    assert items_a == []


# ── 6. Delete cascades to member link rows ─────────────────────────────────


@pytest.mark.asyncio
async def test_delete_cascades_member_links(session: AsyncSession) -> None:
    """Deleting a federation removes its member link rows (FK CASCADE).

    The underlying BIMModel rows are NOT deleted — the federation is
    purely an overlay.
    """
    project_id: uuid.UUID = session.info["project_a_id"]
    service = BIMHubService(session)
    federation = await service.create_federation(FederationCreate(project_id=project_id, name="ToDelete"))
    m_one = await _seed_bim_model(session, project_id, name="M1")
    m_two = await _seed_bim_model(session, project_id, name="M2")
    await service.add_federation_member(
        federation.id,
        FederationModelAdd(bim_model_id=m_one.id, z_order=0),
    )
    await service.add_federation_member(
        federation.id,
        FederationModelAdd(bim_model_id=m_two.id, z_order=1),
    )
    await session.commit()

    # Pre-state: 2 link rows for this federation.
    link_stmt = select(BIMFederationModel).where(BIMFederationModel.federation_id == federation.id)
    pre_links = (await session.execute(link_stmt)).scalars().all()
    assert len(pre_links) == 2

    await service.delete_federation(federation.id)
    await session.commit()

    # Federation gone.
    fed_row = await session.get(BIMFederation, federation.id)
    assert fed_row is None

    # Link rows gone too (SQLite ON DELETE CASCADE is enforced because the
    # session sets PRAGMA foreign_keys=ON at connect time).
    post_links = (await session.execute(link_stmt)).scalars().all()
    assert post_links == []

    # Underlying BIM models are still around — federation is only an overlay.
    m1_row = await session.get(BIMModel, m_one.id)
    m2_row = await session.get(BIMModel, m_two.id)
    assert m1_row is not None
    assert m2_row is not None
