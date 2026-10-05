# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A built module keeps each project's records inside that project.

A project-scoped module built with the wizard used to check only the module's
own permission. Anyone holding ``<key>.read`` could list every project's rows
by leaving ``project_id`` out, read another project's rows by naming it, and
open, change or delete any record by id. The rest of the platform answers
those requests 404, because ``verify_project_access`` keeps "missing" and
"not yours" indistinguishable, and a generated module has to answer the same.

Run against PostgreSQL with a real install, real users and real projects. The
access rule reads ownership, team membership and the admin role from the
database, so nothing short of the real tables shows whether it holds.
"""

from __future__ import annotations

import importlib
import sys
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.module_builder import service
from app.modules.module_builder.spec import EntitySpec, FieldSpec, ModuleSpec, RuleSpec

KEY = "pg_crew_visit"
BASE = "/api/v1/pg-crew-visit"
CLASS_NAME = "CrewVisit"


def _spec() -> ModuleSpec:
    return ModuleSpec(
        key=KEY,
        display_name="Crew Visits",
        description="Which crew was on which project, and for how long.",
        entity=EntitySpec(
            name="crew_visit",
            display_name="Crew visit",
            plural_name="Crew visits",
            project_scoped=True,
            fields=[
                FieldSpec(name="visit_date", label="Date", type="date", required=True),
                FieldSpec(name="crew", label="Crew", type="text", required=True),
                FieldSpec(name="hours", label="Hours", type="number", unit="h", required=True),
            ],
        ),
        rules=[
            RuleSpec(
                code="HOURS_IN_RANGE",
                message="A crew cannot work more than 24 hours in a day.",
                kind="range",
                field="hours",
                min_value=0,
                max_value=24,
            ),
        ],
    )


@pytest.fixture
def runtime_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """An empty runtime module root, torn out of the process afterwards."""
    from app.core import module_runtime_root as rr
    from app.database import Base

    root = tmp_path / "runtime-modules"
    monkeypatch.setenv(rr.ENV_VAR, str(root))
    before = list(rr._package_path())
    try:
        yield root
    finally:
        # Safety net for a test that failed before uninstall ran; uninstall
        # does all of this itself.
        rr._package_path()[:] = before
        for name in [n for n in list(sys.modules) if n.startswith(f"app.modules.{KEY}")]:
            del sys.modules[name]
        table = Base.metadata.tables.get(f"oe_{KEY}_crew_visit")
        if table is not None:
            Base.metadata.remove(table)
        Base.registry._class_registry.pop(CLASS_NAME, None)
        importlib.invalidate_caches()


@pytest.fixture
def app() -> FastAPI:
    return FastAPI()


@pytest.fixture(autouse=True)
def instance_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep enable/disable bookkeeping out of the developer's own instance."""
    from app.core import module_state

    monkeypatch.setattr(module_state, "_resolve_data_dir", lambda data_dir=None: tmp_path / "instance-state")


@pytest.fixture(autouse=True)
def platform_engine(pg_engine, monkeypatch: pytest.MonkeyPatch):
    """The module's startup hook creates its table on ``app.database.engine``."""
    import app.database

    monkeypatch.setattr(app.database, "engine", pg_engine)


@pytest_asyncio.fixture
async def installed(runtime_root: Path, app: FastAPI, pg_engine):
    """The module installed for real, and removed with its table afterwards."""
    await service.install(_spec(), app)
    try:
        yield
    finally:
        try:
            await service.uninstall(KEY, app, drop_data=True)
        except service.InstallRefused:
            pass


@pytest_asyncio.fixture
async def factory(installed, pg_engine) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Sessions that share one outer transaction, rolled back afterwards.

    Depends on ``installed`` so it is torn down first: the rollback has to
    release this connection's row locks before uninstall drops the table, or
    the DROP waits for a transaction that never ends.
    """
    connection = await pg_engine.connect()
    outer = await connection.begin()
    try:
        yield async_sessionmaker(
            bind=connection,
            class_=AsyncSession,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        )
    finally:
        if outer.is_active:
            await outer.rollback()
        await connection.close()


@dataclass
class World:
    admin: str
    alice: str
    bob: str
    alice_project: uuid.UUID
    bob_project: uuid.UUID
    alice_record: str
    bob_record: str


async def _user(session: AsyncSession, role: str) -> str:
    from app.modules.users.models import User

    user_id = uuid.uuid4()
    session.add(
        User(
            id=user_id,
            email=f"{role}-{user_id.hex[:8]}@example.test",
            hashed_password="x",
            full_name=f"Test {role}",
            role=role,
            locale="en",
            is_active=True,
            metadata_={},
        )
    )
    await session.flush()
    return str(user_id)


async def _project(session: AsyncSession, owner: str, name: str) -> uuid.UUID:
    from app.modules.projects.models import Project

    project_id = uuid.uuid4()
    session.add(
        Project(
            id=project_id,
            name=name,
            description="Built module access fixture",
            currency="EUR",
            status="active",
            owner_id=uuid.UUID(owner),
            metadata_={},
        )
    )
    await session.flush()
    return project_id


def _as(app: FastAPI, factory: async_sessionmaker[AsyncSession], user_id: str, role: str) -> None:
    """Make the next requests arrive as this user.

    The payload stands in for the decoded token. Its role decides the module
    permission; the project access rule reads the role from the user row, so
    the row has to agree, and it does because the fixture wrote it.
    """
    from app.dependencies import get_current_user_id, get_current_user_payload, get_session

    async def _session():
        async with factory() as session:
            yield session
            await session.commit()

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user_id] = lambda: user_id
    app.dependency_overrides[get_current_user_payload] = lambda: {"sub": user_id, "role": role, "permissions": []}


@asynccontextmanager
async def _client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://access-test") as client:
        yield client


def _body(project_id: uuid.UUID, crew: str, hours: str = "8") -> dict:
    return {
        "project_id": str(project_id),
        "visit_date": (date.today() - timedelta(days=1)).isoformat(),
        "crew": crew,
        "hours": hours,
    }


@pytest_asyncio.fixture
async def world(app: FastAPI, factory) -> World:
    """Two managers with a project each, one record in each, and an admin."""
    async with factory() as session:
        admin = await _user(session, "admin")
        alice = await _user(session, "manager")
        bob = await _user(session, "manager")
        alice_project = await _project(session, alice, "Alice's site")
        bob_project = await _project(session, bob, "Bob's site")
        await session.commit()

    async with _client(app) as client:
        _as(app, factory, alice, "manager")
        created_a = await client.post(BASE, json=_body(alice_project, "Alice crew"))
        _as(app, factory, bob, "manager")
        created_b = await client.post(BASE, json=_body(bob_project, "Bob crew"))
    assert created_a.status_code == 201, created_a.text
    assert created_b.status_code == 201, created_b.text
    return World(
        admin=admin,
        alice=alice,
        bob=bob,
        alice_project=alice_project,
        bob_project=bob_project,
        alice_record=created_a.json()["id"],
        bob_record=created_b.json()["id"],
    )


class TestListing:
    async def test_naming_someone_elses_project_is_404(self, app: FastAPI, factory, world: World) -> None:
        _as(app, factory, world.bob, "manager")
        async with _client(app) as client:
            foreign = await client.get(BASE, params={"project_id": str(world.alice_project)})
            own = await client.get(BASE, params={"project_id": str(world.bob_project)})

        assert foreign.status_code == 404, foreign.text
        # The control: the same request for Bob's own project answers, so the
        # 404 above is about whose project it is and not about the route.
        assert own.status_code == 200, own.text
        assert [r["id"] for r in own.json()["items"]] == [world.bob_record]

    async def test_leaving_the_project_out_lists_only_reachable_projects(
        self, app: FastAPI, factory, world: World
    ) -> None:
        """The generic screen at /modules/<key> lists without a project."""
        _as(app, factory, world.bob, "manager")
        async with _client(app) as client:
            listed = await client.get(BASE)

        assert listed.status_code == 200, listed.text
        body = listed.json()
        assert {r["id"] for r in body["items"]} == {world.bob_record}
        # Counted inside the same scope: a total of 2 here would tell Bob that
        # a record he cannot see exists.
        assert body["total"] == 1

    async def test_a_user_with_no_projects_lists_nothing(self, app: FastAPI, factory, world: World) -> None:
        """An empty scope is no rows, never every row."""
        async with factory() as session:
            loner = await _user(session, "manager")
            await session.commit()
        _as(app, factory, loner, "manager")
        async with _client(app) as client:
            listed = await client.get(BASE)

        assert listed.status_code == 200, listed.text
        assert listed.json() == {"items": [], "total": 0}

    async def test_an_admin_lists_every_project(self, app: FastAPI, factory, world: World) -> None:
        _as(app, factory, world.admin, "admin")
        async with _client(app) as client:
            listed = await client.get(BASE)
            scoped = await client.get(BASE, params={"project_id": str(world.alice_project)})

        assert listed.status_code == 200, listed.text
        assert {r["id"] for r in listed.json()["items"]} == {world.alice_record, world.bob_record}
        assert scoped.status_code == 200, scoped.text
        assert [r["id"] for r in scoped.json()["items"]] == [world.alice_record]


class TestOneRecord:
    async def test_reading_another_projects_record_looks_like_a_missing_one(
        self, app: FastAPI, factory, world: World
    ) -> None:
        """Same status, same body. A different detail would be an existence oracle."""
        _as(app, factory, world.bob, "manager")
        async with _client(app) as client:
            foreign = await client.get(f"{BASE}/{world.alice_record}")
            missing = await client.get(f"{BASE}/{uuid.uuid4()}")
            own = await client.get(f"{BASE}/{world.bob_record}")

        assert foreign.status_code == 404, foreign.text
        assert foreign.json() == missing.json()
        assert own.status_code == 200, own.text

    async def test_changing_another_projects_record_is_404_and_changes_nothing(
        self, app: FastAPI, factory, world: World
    ) -> None:
        _as(app, factory, world.bob, "manager")
        async with _client(app) as client:
            sound = await client.patch(f"{BASE}/{world.alice_record}", json={"crew": "Bob was here"})
            # Refused by the module's own rule if it ever reached it. Answering
            # 422 would tell Bob the record exists, so the access check has to
            # come before validation.
            invalid = await client.patch(f"{BASE}/{world.alice_record}", json={"hours": "99"})
            missing = await client.patch(f"{BASE}/{uuid.uuid4()}", json={"crew": "Bob was here"})

        assert sound.status_code == 404, sound.text
        assert invalid.status_code == 404, invalid.text
        assert sound.json() == missing.json()

        _as(app, factory, world.alice, "manager")
        async with _client(app) as client:
            after = await client.get(f"{BASE}/{world.alice_record}")
        assert after.json()["crew"] == "Alice crew"

    async def test_deleting_another_projects_record_is_404_and_keeps_it(
        self, app: FastAPI, factory, world: World
    ) -> None:
        _as(app, factory, world.bob, "manager")
        async with _client(app) as client:
            deleted = await client.delete(f"{BASE}/{world.alice_record}")
            missing = await client.delete(f"{BASE}/{uuid.uuid4()}")

        assert deleted.status_code == 404, deleted.text
        assert deleted.json() == missing.json()

        _as(app, factory, world.alice, "manager")
        async with _client(app) as client:
            after = await client.get(f"{BASE}/{world.alice_record}")
        assert after.status_code == 200, after.text

    async def test_a_record_cannot_be_moved_to_another_project(self, app: FastAPI, factory, world: World) -> None:
        """The update schema has no project, so the move is refused outright."""
        _as(app, factory, world.alice, "manager")
        async with _client(app) as client:
            moved = await client.patch(f"{BASE}/{world.alice_record}", json={"project_id": str(world.bob_project)})
            after = await client.get(f"{BASE}/{world.alice_record}")

        assert moved.status_code == 422, moved.text
        assert after.json()["project_id"] == str(world.alice_project)

    async def test_an_admin_reaches_any_record(self, app: FastAPI, factory, world: World) -> None:
        _as(app, factory, world.admin, "admin")
        async with _client(app) as client:
            read = await client.get(f"{BASE}/{world.alice_record}")
            changed = await client.patch(f"{BASE}/{world.bob_record}", json={"crew": "Checked by admin"})

        assert read.status_code == 200, read.text
        assert changed.status_code == 200, changed.text
        assert changed.json()["crew"] == "Checked by admin"


class TestCreating:
    async def test_creating_in_another_project_is_404_and_writes_nothing(
        self, app: FastAPI, factory, world: World
    ) -> None:
        _as(app, factory, world.bob, "manager")
        async with _client(app) as client:
            created = await client.post(BASE, json=_body(world.alice_project, "Bob crew"))

        assert created.status_code == 404, created.text

        _as(app, factory, world.alice, "manager")
        async with _client(app) as client:
            listed = await client.get(BASE, params={"project_id": str(world.alice_project)})
        assert [r["id"] for r in listed.json()["items"]] == [world.alice_record]

    async def test_creating_in_a_project_that_does_not_exist_is_404(self, app: FastAPI, factory, world: World) -> None:
        _as(app, factory, world.bob, "manager")
        async with _client(app) as client:
            created = await client.post(BASE, json=_body(uuid.uuid4(), "Bob crew"))

        assert created.status_code == 404, created.text
