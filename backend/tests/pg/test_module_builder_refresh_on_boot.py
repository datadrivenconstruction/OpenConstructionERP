# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A module installed by the first generator is closed on the next start.

The file-level behaviour of the refresh is in ``tests/test_module_builder_refresh.py``.
This is the claim an operator cares about, on the database it runs against:
a server that installed a project-scoped module before project access was
checked, and has records in it, restarts and from then on keeps each project's
records inside that project, with every record still there.

The restart is simulated the way the platform starts: the refresh runs on the
files first, and only then is the module discovered, imported and mounted, on
an application that has never seen the old router.
"""

from __future__ import annotations

import importlib
import shutil
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.module_builder import refresh, service
from tests.pg.test_module_builder_project_access import _as, _client, _project, _user
from tests.test_module_builder_refresh import hire_spec, install_as_v1

KEY = "refresh_hire"
BASE = "/api/v1/refresh-hire"


@pytest.fixture
def runtime_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from app.core import module_runtime_root as rr
    from app.database import Base

    root = tmp_path / "runtime-modules"
    monkeypatch.setenv(rr.ENV_VAR, str(root))
    before = list(rr._package_path())
    try:
        yield root
    finally:
        rr._package_path()[:] = before
        for name in [n for n in list(sys.modules) if n.startswith(f"app.modules.{KEY}")]:
            del sys.modules[name]
        table = Base.metadata.tables.get(f"oe_{KEY}_hire")
        if table is not None:
            Base.metadata.remove(table)
        Base.registry._class_registry.pop("Hire", None)
        importlib.invalidate_caches()


@pytest.fixture(autouse=True)
def instance_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import module_state

    monkeypatch.setattr(module_state, "_resolve_data_dir", lambda data_dir=None: tmp_path / "instance-state")


@pytest.fixture(autouse=True)
def platform_engine(pg_engine, monkeypatch: pytest.MonkeyPatch):
    import app.database

    monkeypatch.setattr(app.database, "engine", pg_engine)


async def _stop(app: FastAPI) -> None:
    """What a process exit does to a loaded module: nothing of it survives."""
    from app.core.module_loader import module_loader

    await module_loader.disable_module(f"oe_{KEY}", app)
    service._forget(KEY)
    module_loader.forget_module(f"oe_{KEY}")


def _hire(project_id, reference: str) -> dict:
    return {"project_id": str(project_id), "reference": reference, "weekly_rate": "450.00"}


async def test_an_old_install_restarts_guarded_with_its_records(runtime_root: Path, pg_engine) -> None:
    spec = hire_spec()
    before_app = FastAPI()
    connection = await pg_engine.connect()
    outer = await connection.begin()
    factory = async_sessionmaker(
        bind=connection, class_=AsyncSession, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    after_app = FastAPI()
    try:
        # The table and two projects' records, as the server had them.
        await service.install(spec, before_app)
        async with factory() as session:
            admin = await _user(session, "admin")
            alice = await _user(session, "manager")
            bob = await _user(session, "manager")
            alice_project = await _project(session, alice, "Alice's site")
            bob_project = await _project(session, bob, "Bob's site")
            await session.commit()
        async with _client(before_app) as client:
            _as(before_app, factory, alice, "manager")
            alice_record = (await client.post(BASE, json=_hire(alice_project, "A-1"))).json()["id"]
            _as(before_app, factory, bob, "manager")
            bob_record = (await client.post(BASE, json=_hire(bob_project, "B-1"))).json()["id"]
        await _stop(before_app)

        # The same module as the first generator wrote it, rows untouched.
        shutil.rmtree(runtime_root / KEY)
        install_as_v1(runtime_root, spec)
        old_app = FastAPI()
        await service._load_into(old_app, spec)
        _as(old_app, factory, bob, "manager")
        async with _client(old_app) as client:
            leaked = await client.get(BASE)
        # The control: the old code really leaks, so what follows is a change.
        assert {r["id"] for r in leaked.json()["items"]} == {alice_record, bob_record}
        await _stop(old_app)

        # Restart: refresh first, then load.
        assert refresh.refresh_installed(runtime_root) == {KEY: refresh.REFRESHED}
        await service._load_into(after_app, spec)

        _as(after_app, factory, bob, "manager")
        async with _client(after_app) as client:
            listed = await client.get(BASE)
            foreign = await client.get(f"{BASE}/{alice_record}")
            foreign_project = await client.get(BASE, params={"project_id": str(alice_project)})
        assert listed.status_code == 200, listed.text
        assert {r["id"] for r in listed.json()["items"]} == {bob_record}
        assert foreign.status_code == 404
        assert foreign_project.status_code == 404

        _as(after_app, factory, admin, "admin")
        async with _client(after_app) as client:
            everything = await client.get(BASE)
        assert {r["id"] for r in everything.json()["items"]} == {alice_record, bob_record}, "a record was lost"

        # And the next start finds nothing to do.
        assert refresh.refresh_installed(runtime_root) == {KEY: refresh.CURRENT}
    finally:
        # Release this connection's rows before the table is dropped, or the
        # DROP waits on a transaction that never ends.
        if outer.is_active:
            await outer.rollback()
        await connection.close()
        try:
            await service.uninstall(KEY, after_app, drop_data=True)
        except service.InstallRefused:
            async with pg_engine.begin() as ddl:
                await ddl.exec_driver_sql(f'DROP TABLE IF EXISTS "oe_{KEY}_hire"')
