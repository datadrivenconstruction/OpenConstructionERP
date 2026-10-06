# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Module builder v2 on PostgreSQL, where a review found it broke.

Reinstalling over kept data, upgrading a module in place, one project's backlog starving another's
reminders, a workbook refusing a pasted control character, link names lost
past the first 500 rows of an export, and the edges of every link target, of
a module with no project and of comments. The fixtures are the ones
``test_module_builder_v2`` sets up.
"""

from __future__ import annotations

import csv
import importlib
import io
import json
import re
import sys
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.module_builder import service
from app.modules.module_builder.spec import ModuleSpec
from tests.pg.test_module_builder_v2 import (  # noqa: F401  (fixtures by name)
    BASE,
    COLLAB,
    KEY,
    MB,
    TABLE,
    World,
    _as,
    _body,
    _contract,
    _member,
    _project,
    _user,
    app,
    factory,
    installed,
    instance_state,
    platform,
    runtime_root,
    world,
)

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

ALL_KEY = "rv_all_links"
ALL_BASE = "/api/v1/rv-all-links"
DRIFT_KEY = "rv_drift"
DRIFT_BASE = "/api/v1/rv-drift"
FREE_KEY = "rv_free_links"
FREE_BASE = "/api/v1/rv-free-links"


def _forget_any(key: str) -> None:
    from app.database import Base

    for name in [n for n in list(sys.modules) if n.startswith(f"app.modules.{key}")]:
        del sys.modules[name]
    for table in [t for t in list(Base.metadata.tables) if t.startswith(f"oe_{key}_")]:
        Base.metadata.remove(Base.metadata.tables[table])
    for cls in ("Item", "Entry", "Thing"):
        Base.registry._class_registry.pop(cls, None)
    importlib.invalidate_caches()


@pytest.fixture(autouse=True)
def more_permissions():
    from app.modules.contacts.permissions import register_contacts_permissions
    from app.modules.deadlines.permissions import register_deadlines_permissions
    from app.modules.documents.permissions import register_document_permissions
    from app.modules.schedule.permissions import register_schedule_permissions

    for register in (
        register_contacts_permissions,
        register_deadlines_permissions,
        register_document_permissions,
        register_schedule_permissions,
    ):
        register()


@asynccontextmanager
async def _client(application: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=application, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://rv") as client:
        yield client


async def _why(application: FastAPI, method: str, url: str, **kw) -> str:
    """The exception behind a 500, re-run with app exceptions raised."""
    try:
        async with AsyncClient(transport=ASGITransport(app=application), base_url="http://rv") as client:
            r = await client.request(method, url, **kw)
        return f"no exception, {r.status_code}"
    except Exception as exc:  # noqa: BLE001
        cause = exc
        while cause.__cause__ is not None:
            cause = cause.__cause__
        return f"{type(exc).__name__}: {str(exc)[:300]} | root {type(cause).__name__}: {str(cause)[:200]}"


def _spec(key: str, entity: str, fields: list[dict], features: dict, scoped: bool = True, version: int = 2):
    return ModuleSpec.model_validate(
        {
            "key": key,
            "display_name": key.replace("_", " ").title(),
            "schema_version": version,
            "entity": {"name": entity, "display_name": entity.title(), "project_scoped": scoped, "fields": fields},
            "rules": [{"code": "REF_REQUIRED", "message": "Needs a ref.", "kind": "required", "field": "ref"}],
            "features": features,
        }
    )


# ── 1. reinstall over kept data ─────────────────────────────────────────────


STATUS = {"states": [{"code": "open", "label": "Open"}, {"code": "closed", "label": "Closed", "done": True}]}
REF = {"name": "ref", "label": "Ref", "type": "text", "required": True}
COUNT = {"name": "count", "label": "Count", "type": "integer"}


@asynccontextmanager
async def _committed(pg_engine) -> AsyncIterator[tuple[async_sessionmaker[AsyncSession], str, uuid.UUID]]:
    """An admin and a project, committed for real and deleted afterwards.

    Not the usual rolled-back outer transaction: an install over a kept table
    alters it, and ALTER TABLE waits for every open transaction that touched
    the table, so records held in one would block the install forever. The
    module's table is gone before this cleans up (each test drops it).
    """
    made = async_sessionmaker(pg_engine, class_=AsyncSession, expire_on_commit=False)
    async with made() as session:
        admin = await _user(session, "admin")
        owner = await _user(session, "manager")
        project = await _project(session, owner, "Drift site")
        await session.commit()
    try:
        yield made, admin, project
    finally:
        async with made() as session:
            await session.execute(text("DELETE FROM oe_projects_project WHERE id = :i"), {"i": str(project)})
            await session.execute(text("DELETE FROM oe_users_user WHERE id IN (:a, :b)"), {"a": admin, "b": owner})
            await session.commit()


async def _drop(app: FastAPI, key: str) -> None:
    try:
        await service.uninstall(key, app, drop_data=True)
    except service.InstallRefused:
        pass
    _forget_any(key)


async def _columns(pg_engine, table: str) -> dict[str, str]:
    async with pg_engine.connect() as connection:
        rows = await connection.execute(
            text("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = :t"), {"t": table}
        )
        return dict(rows.all())


class TestReinstallOverKeptData:
    async def test_adding_status_and_a_link_by_reinstall_keeps_the_module_working(
        self, runtime_root: Path, app: FastAPI, pg_engine
    ) -> None:
        """No edit path, so adding a function means: remove (data kept, the default), build again, install."""
        before = _spec(DRIFT_KEY, "item", [REF], {})
        after = _spec(
            DRIFT_KEY,
            "item",
            [REF, {"name": "contract", "label": "Contract", "type": "link", "target": "contract"}],
            {"status": STATUS, "export": True},
        )
        async with _committed(pg_engine) as (made, admin, project):
            await service.install(before, app)
            try:
                _as(app, made, admin, "admin")
                async with _client(app) as client:
                    first = await client.post(DRIFT_BASE, json={"project_id": str(project), "ref": "R-1"})
                assert first.status_code == 201, first.text

                removed = await service.uninstall(DRIFT_KEY, app, drop_data=False)
                assert removed
                _forget_any(DRIFT_KEY)
                installed_again = await service.install(after, app)
                assert installed_again.key == DRIFT_KEY

                async with _client(app) as client:
                    listed = await client.get(DRIFT_BASE)
                    created = await client.post(DRIFT_BASE, json={"project_id": str(project), "ref": "R-2"})
                if listed.status_code != 200:
                    pytest.fail(
                        f"list after reinstall: {listed.status_code}; create {created.status_code}; "
                        f"cause: {await _why(app, 'GET', DRIFT_BASE)}"
                    )
                assert created.status_code == 201, f"create after reinstall: {created.status_code} {created.text[:300]}"
                kept = next(i for i in listed.json()["items"] if i["ref"] == "R-1")
                assert kept["status"] == "open" and kept["contract"] is None

                # And again, as a restart or a second reinstall would: nothing left to change.
                await service.uninstall(DRIFT_KEY, app, drop_data=False)
                _forget_any(DRIFT_KEY)
                await service.install(after, app)
                async with _client(app) as client:
                    relisted = await client.get(DRIFT_BASE)
                    exported = await client.get(f"{DRIFT_BASE}/export")
                assert relisted.status_code == 200, relisted.text
                assert sorted(i["ref"] for i in relisted.json()["items"]) == ["R-1", "R-2"]
                assert exported.status_code == 200, exported.text
            finally:
                await _drop(app, DRIFT_KEY)

    async def test_a_layout_that_would_lose_records_is_refused_with_nothing_written(
        self, runtime_root: Path, app: FastAPI, pg_engine
    ) -> None:
        before = _spec(DRIFT_KEY, "item", [REF, COUNT], {})
        after = _spec(DRIFT_KEY, "item", [REF, {**COUNT, "type": "text"}], {"status": STATUS})
        async with _committed(pg_engine) as (made, admin, project):
            await service.install(before, app)
            try:
                _as(app, made, admin, "admin")
                async with _client(app) as client:
                    first = await client.post(DRIFT_BASE, json={"project_id": str(project), "ref": "R-1", "count": 7})
                assert first.status_code == 201, first.text
                await service.uninstall(DRIFT_KEY, app, drop_data=False)
                _forget_any(DRIFT_KEY)
                shape = await _columns(pg_engine, f"oe_{DRIFT_KEY}_item")

                with pytest.raises(service.InstallRefused) as refused:
                    await service.install(after, app)

                assert refused.value.code == "layout_conflict"
                assert refused.value.params == {
                    "records": 1,
                    "fields": [{"name": "count", "label": "Count", "problem": "changed"}],
                }
                assert "already holds 1 record saved with a different layout" in str(refused.value)
                assert not (runtime_root / DRIFT_KEY).exists(), "a refused install wrote files"
                # Not even the status column the new spec would have added.
                assert await _columns(pg_engine, f"oe_{DRIFT_KEY}_item") == shape

                await service.install(before, app)
                async with _client(app) as client:
                    listed = await client.get(DRIFT_BASE)
                assert [(i["ref"], i["count"]) for i in listed.json()["items"]] == [("R-1", 7)]
            finally:
                await _drop(app, DRIFT_KEY)

    async def test_an_empty_kept_table_is_made_again(self, runtime_root: Path, app: FastAPI, pg_engine) -> None:
        before = _spec(DRIFT_KEY, "item", [REF, COUNT], {})
        after = _spec(DRIFT_KEY, "item", [REF, {**COUNT, "type": "text"}], {})
        try:
            await service.install(before, app)
            await service.uninstall(DRIFT_KEY, app, drop_data=False)
            _forget_any(DRIFT_KEY)
            await service.install(after, app)
            assert (await _columns(pg_engine, f"oe_{DRIFT_KEY}_item"))["count"] == "character varying"
        finally:
            await _drop(app, DRIFT_KEY)

    async def test_the_same_spec_plans_nothing_on_postgresql(self, runtime_root: Path, app: FastAPI, pg_engine) -> None:
        """The control for every type the generator writes, a link and the status column."""
        from app.modules.module_builder import layout

        every = _spec(
            DRIFT_KEY,
            "item",
            [
                REF,
                {"name": "notes", "label": "Notes", "type": "long_text"},
                COUNT,
                {"name": "qty", "label": "Qty", "type": "number"},
                {"name": "amount", "label": "Amount", "type": "money"},
                {"name": "on_day", "label": "Day", "type": "date"},
                {"name": "at_time", "label": "Time", "type": "datetime"},
                {"name": "ok", "label": "OK", "type": "boolean"},
                {"name": "kind", "label": "Kind", "type": "select", "options": ["a", "b"]},
                {"name": "contract", "label": "Contract", "type": "link", "target": "contract"},
            ],
            {"status": STATUS},
        )
        try:
            await service.install(every, app)
            async with pg_engine.connect() as connection:
                plan = await connection.run_sync(layout.plan, every)
            assert plan.exists
            assert (plan.add, plan.relax, plan.indexes, plan.problems) == ([], [], [], [])
        finally:
            await _drop(app, DRIFT_KEY)


def _snapshot(directory: Path) -> dict[str, bytes]:
    return {
        p.relative_to(directory).as_posix(): p.read_bytes()
        for p in sorted(directory.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    }


def _wire(spec: ModuleSpec) -> dict:
    return {"spec": spec.model_dump(mode="json")}


def _broken_load(monkeypatch: pytest.MonkeyPatch, failing: ModuleSpec) -> None:
    """Loading *failing* fails, as new code with a fault in it would; every other load goes through."""
    real = service._load_into

    async def load(app: FastAPI, spec: ModuleSpec):
        if spec == failing:
            raise RuntimeError("the new code does not import")
        return await real(app, spec)

    monkeypatch.setattr(service, "_load_into", load)


class TestUpgradeInPlace:
    async def test_status_and_a_link_on_a_register_holding_records(
        self, runtime_root: Path, app: FastAPI, pg_engine
    ) -> None:
        from app.modules.module_builder import refresh

        before = _spec(DRIFT_KEY, "item", [REF, COUNT], {})
        after = _spec(
            DRIFT_KEY,
            "item",
            [REF, COUNT, {"name": "contract", "label": "Contract", "type": "link", "target": "contract"}],
            {"status": STATUS, "export": True},
        )
        async with _committed(pg_engine) as (made, admin, project):
            await service.install(before, app)
            try:
                _as(app, made, admin, "admin")
                async with _client(app) as client:
                    first = await client.post(DRIFT_BASE, json={"project_id": str(project), "ref": "R-1", "count": 7})
                    assert first.status_code == 201, first.text

                    previewed = await client.post(f"{MB}/{DRIFT_KEY}/upgrade/preview", json=_wire(after))
                    assert previewed.status_code == 200, previewed.text
                    body = previewed.json()
                    assert body["record_count"] == 1
                    assert sorted((c["kind"], c.get("field") or c.get("feature")) for c in body["changes"]) == [
                        ("feature_added", "export"),
                        ("feature_added", "status"),
                        ("link_added", "contract"),
                    ]
                    # Previewing wrote nothing and changed no column.
                    assert "status" not in await _columns(pg_engine, f"oe_{DRIFT_KEY}_item")

                    installing = (await client.post(f"{MB}/preview", json=_wire(after))).json()["review_token"]
                    wrong = await client.post(
                        f"{MB}/{DRIFT_KEY}/upgrade", json={**_wire(after), "review_token": installing}
                    )
                    assert wrong.status_code == 400, wrong.text

                    done = await client.post(
                        f"{MB}/{DRIFT_KEY}/upgrade", json={**_wire(after), "review_token": body["review_token"]}
                    )
                    assert done.status_code == 200, done.text
                    assert done.json()["record_count"] == 1
                    assert done.json()["changes"] == body["changes"]
                    assert done.json()["base_path"] == DRIFT_BASE

                    listed = await client.get(DRIFT_BASE)
                    created = await client.post(DRIFT_BASE, json={"project_id": str(project), "ref": "R-2", "count": 3})
                    exported = await client.get(f"{DRIFT_BASE}/export")
                    if listed.status_code != 200:
                        pytest.fail(f"list after upgrade: {listed.status_code}: {await _why(app, 'GET', DRIFT_BASE)}")
                    assert created.status_code == 201, created.text
                    assert exported.status_code == 200, exported.text
                    kept = next(i for i in listed.json()["items"] if i["ref"] == "R-1")
                    assert (kept["count"], kept["status"], kept["contract"]) == (7, "open", None)

                    again = await client.post(f"{MB}/{DRIFT_KEY}/upgrade/preview", json=_wire(after))
                    assert again.status_code == 200 and again.json()["changes"] == []

                on_disk = json.loads((runtime_root / DRIFT_KEY / "spec.json").read_text(encoding="utf-8"))
                assert on_disk["features"]["export"] is True
                # A restart finds the module current and loads it as upgraded.
                assert refresh.refresh_installed(runtime_root)[DRIFT_KEY] == refresh.CURRENT
            finally:
                await _drop(app, DRIFT_KEY)

    async def test_an_upgrade_that_takes_away_changes_nothing(
        self, runtime_root: Path, app: FastAPI, pg_engine
    ) -> None:
        from app.modules.module_builder import review_token

        before = _spec(DRIFT_KEY, "item", [REF, COUNT], {"status": STATUS})
        # A link that would be added, beside a retyped field and a function taken away.
        after = _spec(
            DRIFT_KEY,
            "item",
            [
                REF,
                {**COUNT, "type": "text"},
                {"name": "contract", "label": "Contract", "type": "link", "target": "contract"},
            ],
            {},
        )
        async with _committed(pg_engine) as (made, admin, project):
            await service.install(before, app)
            try:
                _as(app, made, admin, "admin")
                async with _client(app) as client:
                    first = await client.post(DRIFT_BASE, json={"project_id": str(project), "ref": "R-1", "count": 7})
                    assert first.status_code == 201, first.text
                    files = _snapshot(runtime_root / DRIFT_KEY)
                    shape = await _columns(pg_engine, f"oe_{DRIFT_KEY}_item")

                    previewed = await client.post(f"{MB}/{DRIFT_KEY}/upgrade/preview", json=_wire(after))
                    token = review_token.issue(after, admin, purpose=review_token.UPGRADE)
                    applied = await client.post(
                        f"{MB}/{DRIFT_KEY}/upgrade", json={**_wire(after), "review_token": token}
                    )

                    for refused in (previewed, applied):
                        assert refused.status_code == 409, refused.text
                        detail = refused.json()["detail"]
                        assert detail["code"] == "upgrade_not_additive"
                        assert detail["params"]["records"] == 1
                        assert sorted(detail["params"]["problems"], key=lambda p: p["code"]) == [
                            {"code": "feature_removed", "feature": "status"},
                            {"code": "field_retyped", "field": "count", "label": "Count"},
                        ]
                    assert _snapshot(runtime_root / DRIFT_KEY) == files
                    assert await _columns(pg_engine, f"oe_{DRIFT_KEY}_item") == shape

                    listed = await client.get(DRIFT_BASE)
                assert listed.status_code == 200, listed.text
                assert [(i["ref"], i["count"], i["status"]) for i in listed.json()["items"]] == [("R-1", 7, "open")]
            finally:
                await _drop(app, DRIFT_KEY)

    async def test_two_upgrades_at_once_never_half_apply(self, runtime_root: Path, app: FastAPI, pg_engine) -> None:
        """Each adds something the other lacks, so whichever runs second takes the first one's away."""
        import asyncio

        from app.modules.module_builder import upgrade

        link = {"name": "contract", "label": "Contract", "type": "link", "target": "contract"}
        before = _spec(DRIFT_KEY, "item", [REF], {})
        with_link = _spec(DRIFT_KEY, "item", [REF, link], {})
        with_status = _spec(DRIFT_KEY, "item", [REF], {"status": STATUS})
        async with _committed(pg_engine) as (made, admin, project):
            await service.install(before, app)
            try:
                _as(app, made, admin, "admin")
                async with _client(app) as client:
                    first = await client.post(DRIFT_BASE, json={"project_id": str(project), "ref": "R-1"})
                assert first.status_code == 201, first.text

                results = await asyncio.gather(
                    upgrade.upgrade(DRIFT_KEY, with_link, app),
                    upgrade.upgrade(DRIFT_KEY, with_status, app),
                    return_exceptions=True,
                )

                won = [r for r in results if isinstance(r, upgrade.Outcome)]
                lost = [r for r in results if isinstance(r, upgrade.UpgradeRefused)]
                assert (len(won), len(lost)) == (1, 1), results
                assert lost[0].code == "upgrade_not_additive"
                winner = with_link if results[0] is won[0] else with_status

                columns = await _columns(pg_engine, f"oe_{DRIFT_KEY}_item")
                assert ("contract" in columns, "status" in columns) == (winner is with_link, winner is with_status)
                assert upgrade.installed_spec(DRIFT_KEY) == winner

                # The same upgrade twice at once: the second finds nothing left to do.
                twice = await asyncio.gather(
                    upgrade.upgrade(DRIFT_KEY, winner, app), upgrade.upgrade(DRIFT_KEY, winner, app)
                )
                assert [t.changes for t in twice] == [[], []]

                async with _client(app) as client:
                    listed = await client.get(DRIFT_BASE)
                assert listed.status_code == 200, listed.text
                assert [i["ref"] for i in listed.json()["items"]] == ["R-1"]
            finally:
                await _drop(app, DRIFT_KEY)

    async def test_a_quarantined_module_is_removed_with_its_table_and_never_imported(
        self, runtime_root: Path, app: FastAPI, pg_engine
    ) -> None:
        from app.modules.module_builder import generator, refresh

        spec = _spec(DRIFT_KEY, "item", [REF], {})
        await service.install(spec, app)
        try:
            await service.uninstall(DRIFT_KEY, app, drop_data=False)
            _forget_any(DRIFT_KEY)
            # As the refresh leaves one: the files moved aside, with a note.
            place = refresh.quarantine_dir(runtime_root)
            generator.write(spec, place)
            (place / DRIFT_KEY / refresh.QUARANTINE_NOTE).write_text(
                json.dumps({"code": "unverifiable", "params": {}, "generator": 2}), encoding="utf-8"
            )
            assert any(m.key == DRIFT_KEY and m.status == "quarantined" for m in service.installed())
            assert await _columns(pg_engine, f"oe_{DRIFT_KEY}_item")

            removed = await service.uninstall(DRIFT_KEY, app, drop_data=True)

            assert removed["data_dropped"] is True
            assert await _columns(pg_engine, f"oe_{DRIFT_KEY}_item") == {}
            assert not (place / DRIFT_KEY).exists()
            assert not any(n.startswith(f"app.modules.{DRIFT_KEY}") for n in sys.modules)
        finally:
            await _drop(app, DRIFT_KEY)

    async def test_new_code_that_does_not_load_puts_the_old_back(
        self, runtime_root: Path, app: FastAPI, pg_engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.modules.module_builder import upgrade

        before = _spec(DRIFT_KEY, "item", [REF, COUNT], {})
        after = _spec(DRIFT_KEY, "item", [REF, COUNT], {"status": STATUS})
        _broken_load(monkeypatch, after)
        async with _committed(pg_engine) as (made, admin, project):
            await service.install(before, app)
            try:
                _as(app, made, admin, "admin")
                async with _client(app) as client:
                    first = await client.post(DRIFT_BASE, json={"project_id": str(project), "ref": "R-1", "count": 7})
                assert first.status_code == 201, first.text
                files = _snapshot(runtime_root / DRIFT_KEY)

                with pytest.raises(upgrade.UpgradeRefused) as refused:
                    await upgrade.upgrade(DRIFT_KEY, after, app)

                assert refused.value.code == "upgrade_failed"
                assert _snapshot(runtime_root / DRIFT_KEY) == files
                assert upgrade.installed_spec(DRIFT_KEY) == before
                # The column the upgrade added stays, empty of meaning to the old code.
                assert "status" in await _columns(pg_engine, f"oe_{DRIFT_KEY}_item")
                async with _client(app) as client:
                    listed = await client.get(DRIFT_BASE)
                    created = await client.post(DRIFT_BASE, json={"project_id": str(project), "ref": "R-2", "count": 1})
                assert listed.status_code == 200, listed.text
                assert [(i["ref"], i["count"]) for i in listed.json()["items"]] == [("R-1", 7)]
                assert "status" not in listed.json()["items"][0]
                assert created.status_code == 201, created.text
            finally:
                await _drop(app, DRIFT_KEY)

    async def test_an_empty_register_made_again_is_made_again_by_the_old_code(
        self, runtime_root: Path, app: FastAPI, pg_engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.modules.module_builder import upgrade

        before = _spec(DRIFT_KEY, "item", [REF, COUNT], {})
        after = _spec(DRIFT_KEY, "item", [REF], {})
        _broken_load(monkeypatch, after)
        await service.install(before, app)
        try:
            with pytest.raises(upgrade.UpgradeRefused) as refused:
                await upgrade.upgrade(DRIFT_KEY, after, app)

            assert refused.value.code == "upgrade_failed"
            assert "count" in await _columns(pg_engine, f"oe_{DRIFT_KEY}_item")
            assert upgrade.installed_spec(DRIFT_KEY) == before
        finally:
            await _drop(app, DRIFT_KEY)

    async def test_two_workers_upgrading_at_once_are_kept_apart_by_the_database(
        self, runtime_root: Path, app: FastAPI, pg_engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """As two server processes would: no shared in-process lock, only PostgreSQL's."""
        import asyncio

        from app.modules.module_builder import upgrade

        class Unshared(dict):
            def setdefault(self, key, default=None):
                return asyncio.Lock()

        monkeypatch.setattr(upgrade, "_locks", Unshared())
        link = {"name": "contract", "label": "Contract", "type": "link", "target": "contract"}
        before = _spec(DRIFT_KEY, "item", [REF], {})
        with_link = _spec(DRIFT_KEY, "item", [REF, link], {})
        with_status = _spec(DRIFT_KEY, "item", [REF], {"status": STATUS})
        async with _committed(pg_engine) as (made, admin, project):
            await service.install(before, app)
            try:
                _as(app, made, admin, "admin")
                async with _client(app) as client:
                    first = await client.post(DRIFT_BASE, json={"project_id": str(project), "ref": "R-1"})
                assert first.status_code == 201, first.text

                results = await asyncio.gather(
                    upgrade.upgrade(DRIFT_KEY, with_link, app),
                    upgrade.upgrade(DRIFT_KEY, with_status, app),
                    return_exceptions=True,
                )

                won = [r for r in results if isinstance(r, upgrade.Outcome)]
                lost = [r for r in results if not isinstance(r, upgrade.Outcome)]
                assert len(won) == 1, results
                # Compared against the first one's result, not a deadlock between two ALTER TABLEs.
                assert isinstance(lost[0], upgrade.UpgradeRefused), lost
                assert lost[0].code == "upgrade_not_additive"
                winner = with_link if results[0] is won[0] else with_status
                columns = await _columns(pg_engine, f"oe_{DRIFT_KEY}_item")
                assert ("contract" in columns, "status" in columns) == (winner is with_link, winner is with_status)
                assert upgrade.installed_spec(DRIFT_KEY) == winner
            finally:
                await _drop(app, DRIFT_KEY)

    async def test_building_a_quarantined_module_again_replaces_it(
        self, runtime_root: Path, app: FastAPI, pg_engine
    ) -> None:
        from app.modules.module_builder import generator, refresh

        spec = _spec(DRIFT_KEY, "item", [REF], {})
        place = refresh.quarantine_dir(runtime_root)
        generator.write(spec, place)
        (place / DRIFT_KEY / refresh.QUARANTINE_NOTE).write_text(
            json.dumps({"code": "unsafe_code", "params": {"files": ["models.py"]}, "generator": 2}), encoding="utf-8"
        )
        try:
            await service.install(spec, app)

            assert (runtime_root / DRIFT_KEY / "spec.json").is_file()
            assert not (place / DRIFT_KEY).exists()
            backups = list((runtime_root / refresh.WORK_DIR / "backups").iterdir())
            assert [b.name.startswith(f"{DRIFT_KEY}-quarantined-") for b in backups] == [True]
            listed = [m for m in service.installed() if m.key == DRIFT_KEY]
            assert [(m.status, m.problem) for m in listed] == [("installed", None)]
        finally:
            await _drop(app, DRIFT_KEY)


# ── 2. deadlines ────────────────────────────────────────────────────────────


async def _bulk_overdue(session: AsyncSession, project_id: uuid.UUID, count: int, days_ago: int) -> None:
    await session.execute(
        text(
            f"INSERT INTO {TABLE} (id, project_id, reference, due_on, status, created_at, updated_at) "
            "SELECT gen_random_uuid(), :p, 'OLD-' || g, :due, 'open', now(), now() "
            "FROM generate_series(1, :n) AS g"
        ),
        {"p": str(project_id), "due": datetime.now(UTC).date() - timedelta(days=days_ago), "n": count},
    )


class TestDeadlineSweepAcrossProjects:
    async def test_one_projects_backlog_does_not_hide_another_projects_reminder(
        self, app: FastAPI, factory, world: World
    ) -> None:
        from app.modules.deadlines.service import collect_approaching_for_sweep, collect_overdue_for_sweep

        tomorrow = (datetime.now(UTC).date() + timedelta(days=1)).isoformat()
        _as(app, factory, world.alice, "manager")
        async with _client(app) as client:
            soon = await client.post(
                BASE, json=_body(world.alice_site, "A-soon", due_on=tomorrow, responsible=world.alice)
            )
        assert soon.status_code == 201, soon.text

        async with factory() as session:
            before_overdue = await collect_overdue_for_sweep(session)
            before_soon = await collect_approaching_for_sweep(session, "built_modules", 30)
            # Bob's site has a long-forgotten backlog: 500 open records, ten days late.
            await _bulk_overdue(session, world.bob_site, 500, 10)
            await session.commit()
            overdue = await collect_overdue_for_sweep(session)
            approaching = await collect_approaching_for_sweep(session, "built_modules", 30)

        built_before = {i.entity_id for i in before_overdue if i.module == "built_modules"}
        assert world.alice_record in built_before
        assert soon.json()["id"] in {i.entity_id for i in before_soon}
        lost = []
        if world.alice_record not in {i.entity_id for i in overdue}:
            lost.append(f"overdue sweep lost Alice's record ({len(overdue)} built items collected)")
        if soon.json()["id"] not in {i.entity_id for i in approaching}:
            lost.append(f"approaching sweep lost Alice's due-tomorrow record ({len(approaching)} collected)")
        assert lost == [], "after Bob's project got 500 older open records: " + "; ".join(lost)

    async def test_repeated_sweeps_send_each_reminder_once_and_respect_window_and_done(
        self, app: FastAPI, factory, world: World
    ) -> None:
        from app.modules.deadlines.sweeper import sweep_overdue
        from app.modules.notifications.models import Notification

        today = datetime.now(UTC).date()
        _as(app, factory, world.alice, "manager")
        async with _client(app) as client:
            inside = await client.post(
                BASE,
                json=_body(
                    world.alice_site,
                    "in-window",
                    due_on=(today + timedelta(days=2)).isoformat(),
                    responsible=world.alice,
                ),
            )
            outside = await client.post(
                BASE,
                json=_body(
                    world.alice_site,
                    "out-window",
                    due_on=(today + timedelta(days=3)).isoformat(),
                    responsible=world.alice,
                ),
            )
            finished = await client.post(
                BASE,
                json=_body(
                    world.alice_site,
                    "finished",
                    due_on=(today + timedelta(days=1)).isoformat(),
                    responsible=world.alice,
                    status="done",
                ),
            )
        # fmt: skip
        for r in (inside, outside, finished):
            assert r.status_code == 201, r.text

        entity = f"built.{KEY}"

        async def count(session: AsyncSession, record: str | None = None) -> int:
            stmt = select(func.count()).select_from(Notification).where(Notification.entity_type == entity)
            if record:
                stmt = stmt.where(Notification.entity_id == record)
            return (await session.execute(stmt)).scalar_one()

        now = datetime.now(UTC)
        async with factory() as session:
            await sweep_overdue(session, now=now)
            await session.commit()
            first = await count(session)
            first_inside = await count(session, inside.json()["id"])
            first_outside = await count(session, outside.json()["id"])
            first_done = await count(session, finished.json()["id"])
            first_overdue = await count(session, world.alice_record)
            await sweep_overdue(session, now=now)
            await sweep_overdue(session, now=now + timedelta(hours=1))
            await session.commit()
            second = await count(session)
        assert first_inside >= 1
        assert first_outside == 0
        assert first_done == 0
        assert first_overdue >= 1
        assert second == first


DUE_KEY = "rv_due_at"


class TestTheWindowAndClassifyAgree:
    """The SQL now chooses the rows; it must choose exactly the ones classify would surface."""

    async def test_a_date_deadline(self, app: FastAPI, factory, world: World) -> None:
        from app.modules.deadlines.logic import ON_TIME, classify
        from app.modules.deadlines.service import _collect_built_modules

        today = datetime.now(UTC).date()
        async with factory() as session:
            for offset in (-1, 0, 2, 3):
                await session.execute(
                    text(
                        f"INSERT INTO {TABLE} (id, project_id, reference, due_on, status, created_at, updated_at) "
                        "VALUES (gen_random_uuid(), :p, :r, :due, 'open', now(), now())"
                    ),
                    {"p": str(world.alice_site), "r": f"D{offset}", "due": today + timedelta(days=offset)},
                )
            await session.commit()
            rows = (
                await session.execute(
                    text(f"SELECT id, due_on, status FROM {TABLE} WHERE project_id = :p AND due_on IS NOT NULL"),
                    {"p": str(world.alice_site)},
                )
            ).all()
            items = await _collect_built_modules(session, [world.alice_site], today, 2)

        got = {i.entity_id: i.classification for i in items}
        expected = {str(r.id): classify(r.due_on, r.status, today, {"done"}, 2)[0] for r in rows}
        assert {k: got.get(k, ON_TIME) for k in expected} == expected
        assert sorted(expected.values()).count("approaching") == 2

    async def test_a_datetime_deadline(self, runtime_root: Path, app: FastAPI, pg_engine) -> None:
        from app.modules.deadlines.logic import APPROACHING, ON_TIME, OVERDUE
        from app.modules.deadlines.service import _collect_built_modules

        spec = _spec(
            DUE_KEY,
            "item",
            [REF, {"name": "due_at", "label": "Due", "type": "datetime"}],
            {"due": {"field": "due_at", "remind_days_before": 2}},
        )
        today = datetime.now(UTC).date()
        midnight = datetime(today.year, today.month, today.day, tzinfo=UTC)
        cases = {
            "late": (midnight - timedelta(seconds=1), OVERDUE),
            "today": (midnight, APPROACHING),
            "edge": (midnight + timedelta(days=3) - timedelta(seconds=1), APPROACHING),
            "later": (midnight + timedelta(days=3), ON_TIME),
        }
        async with _committed(pg_engine) as (made, _admin, project):
            await service.install(spec, app)
            try:
                async with made() as session:
                    for ref, (moment, _) in cases.items():
                        await session.execute(
                            text(
                                f"INSERT INTO oe_{DUE_KEY}_item (id, project_id, ref, due_at, created_at, updated_at) "
                                "VALUES (gen_random_uuid(), :p, :r, :due, now(), now())"
                            ),
                            {"p": str(project), "r": ref, "due": moment},
                        )
                    await session.commit()
                    ids = dict((await session.execute(text(f"SELECT ref, id FROM oe_{DUE_KEY}_item"))).all())
                    items = await _collect_built_modules(session, [project], today, 2)
            finally:
                await _drop(app, DUE_KEY)
        got = {i.entity_id: i.classification for i in items}
        assert {ref: got.get(str(ids[ref]), ON_TIME) for ref in cases} == {ref: c for ref, (_, c) in cases.items()}


# ── 3. export ───────────────────────────────────────────────────────────────


class TestExportRobustness:
    async def test_xlsx_with_a_pasted_vertical_tab(self, app: FastAPI, factory, world: World) -> None:
        _as(app, factory, world.alice, "manager")
        async with _client(app) as client:
            created = await client.post(BASE, json=_body(world.alice_site, "Pour A\x0bLevel 2"))
            workbook = await client.get(f"{BASE}/export", params={"format": "xlsx"})
            listed = await client.get(BASE)
        assert created.status_code == 201, created.text
        assert listed.status_code == 200
        if workbook.status_code != 200:
            pytest.fail(
                f"xlsx export {workbook.status_code}; cause: "
                f"{await _why(app, 'GET', f'{BASE}/export', params={'format': 'xlsx'})}"
            )

    async def test_link_names_in_a_large_export(self, app: FastAPI, factory, world: World) -> None:
        from app.modules.contracts.models import Contract

        async with factory() as session:
            ids = [uuid.uuid4() for _ in range(520)]
            session.add_all(
                Contract(id=i, code=f"K-{n:04d}", title=f"Package {n:04d}", project_id=world.alice_site)
                for n, i in enumerate(ids)
            )
            await session.flush()
            await session.execute(
                text(
                    f"INSERT INTO {TABLE} (id, project_id, reference, contract, status, created_at, updated_at) "
                    "SELECT gen_random_uuid(), :p, 'BULK-' || c.code, c.id, 'open', now(), now() "
                    "FROM oe_contracts_contract c WHERE c.code LIKE 'K-%' AND c.project_id = :q"
                ),
                {"p": str(world.alice_site), "q": str(world.alice_site)},
            )
            await session.commit()
        _as(app, factory, world.alice, "manager")
        async with _client(app) as client:
            exported = await client.get(f"{BASE}/export", params={"format": "csv"})
        assert exported.status_code == 200, exported.text
        rows = list(csv.reader(io.StringIO(exported.content.decode("utf-8-sig"))))
        column = rows[0].index("Contract")
        raw = [r[column] for r in rows[1:] if UUID_RE.match(r[column])]
        assert len(rows) - 1 >= 520
        assert raw == [], f"{len(raw)} of {len(rows) - 1} contract cells are raw ids, e.g. {raw[:2]}"


# ── 4. every link target ────────────────────────────────────────────────────


def _all_links_spec() -> ModuleSpec:
    return _spec(
        ALL_KEY,
        "item",
        [
            {"name": "ref", "label": "Ref", "type": "text", "required": True},
            {"name": "contract", "label": "Contract", "type": "link", "target": "contract"},
            {"name": "contact", "label": "Contact", "type": "link", "target": "contact"},
            {"name": "activity", "label": "Activity", "type": "link", "target": "schedule_activity"},
            {"name": "document", "label": "Document", "type": "link", "target": "document"},
            {"name": "responsible", "label": "Responsible", "type": "link", "target": "user"},
        ],
        {"export": True},
    )


@pytest_asyncio.fixture
async def all_links(runtime_root: Path, app: FastAPI, installed):
    await service.install(_all_links_spec(), app)
    try:
        yield
    finally:
        try:
            await service.uninstall(ALL_KEY, app, drop_data=True)
        except service.InstallRefused:
            pass
        _forget_any(ALL_KEY)


@pytest_asyncio.fixture
async def all_factory(all_links, pg_engine):
    connection = await pg_engine.connect()
    outer = await connection.begin()
    try:
        yield async_sessionmaker(
            bind=connection, class_=AsyncSession, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
    finally:
        if outer.is_active:
            await outer.rollback()
        await connection.close()


class TestEveryTarget:
    async def test_each_target_stays_inside_what_the_caller_may_see(self, app: FastAPI, all_factory) -> None:
        from app.modules.contacts.models import Contact
        from app.modules.documents.folder_permissions_service import FolderPermission
        from app.modules.documents.models import Document
        from app.modules.schedule.models import Activity, Schedule

        async with all_factory() as s:
            alice = await _user(s, "manager", "Alice %_\\ Builder")
            bob = await _user(s, "manager", "Bob Builder")
            ed = await _user(s, "editor", "Ed Editor")
            a_site = await _project(s, alice, "A site")
            b_site = await _project(s, bob, "B site")
            await _member(s, a_site, ed)
            a_contract = await _contract(s, a_site, "A works 100%")
            b_contract = await _contract(s, b_site, "B works")
            await _contract(s, a_site, "A plain")
            a_contact, b_contact = uuid.uuid4(), uuid.uuid4()
            s.add(
                Contact(
                    id=a_contact,
                    contact_type="supplier",
                    company_name="A Supplies",
                    tenant_id=alice,
                    created_by=alice,
                    is_active=True,
                )
            )
            s.add(
                Contact(
                    id=b_contact,
                    contact_type="supplier",
                    company_name="B Supplies",
                    tenant_id=bob,
                    created_by=bob,
                    is_active=True,
                )
            )
            a_sched, b_sched = uuid.uuid4(), uuid.uuid4()
            s.add(Schedule(id=a_sched, project_id=a_site, name="A plan"))
            s.add(Schedule(id=b_sched, project_id=b_site, name="B plan"))
            await s.flush()
            a_act, b_act = uuid.uuid4(), uuid.uuid4()
            s.add(
                Activity(id=a_act, schedule_id=a_sched, name="A pour", start_date="2026-10-01", end_date="2026-10-02")
            )
            s.add(
                Activity(id=b_act, schedule_id=b_sched, name="B pour", start_date="2026-10-01", end_date="2026-10-02")
            )
            a_doc, b_doc, a_secret = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
            s.add(Document(id=a_doc, project_id=a_site, name="A drawing", category="drawing"))
            s.add(Document(id=b_doc, project_id=b_site, name="B drawing", category="drawing"))
            s.add(Document(id=a_secret, project_id=a_site, name="A contract scan", category="contract"))
            await s.flush()
            # The contract folder on A site is granted to Alice only, so Ed may not see the scan.
            s.add(
                FolderPermission(
                    project_id=a_site,
                    scope_kind="document",
                    scope_path="contract",
                    user_id=uuid.UUID(alice),
                    granted_by=uuid.UUID(alice),
                    role="viewer",
                )
            )
            await s.commit()
        # fmt: skip
        mine = {
            "contract": a_contract,
            "contact": str(a_contact),
            "schedule_activity": str(a_act),
            "document": str(a_doc),
            "user": ed,
        }
        theirs = {
            "contract": b_contract,
            "contact": str(b_contact),
            "schedule_activity": str(b_act),
            "document": str(b_doc),
            "user": bob,
        }
        field_of = {"contract": "contract", "contact": "contact", "schedule_activity": "activity",
                    "document": "document", "user": "responsible"}  # fmt: skip

        problems: list[str] = []
        _as(app, all_factory, alice, "manager")
        async with _client(app) as client:
            for target in mine:
                everything = await client.get(f"{MB}/lookup/{target}")
                one = await client.get(f"{MB}/lookup/{target}", params={"project_id": str(a_site)})
                labels = await client.get(
                    f"{MB}/lookup/{target}/labels", params={"ids": f"{mine[target]},{theirs[target]}"}
                )
                if everything.status_code != 200 or one.status_code != 200 or labels.status_code != 200:
                    problems.append(f"{target}: lookup {everything.status_code}/{one.status_code}/{labels.status_code}")
                    continue
                seen = {i["id"] for i in everything.json()["items"]}
                if mine[target] not in seen:
                    problems.append(f"{target}: alice's own record missing from picker")
                if theirs[target] in seen:
                    problems.append(f"{target}: bob's record LISTED to alice")
                if theirs[target] in labels.json()["labels"]:
                    problems.append(f"{target}: bob's record LABELLED for alice")
                good = await client.post(
                    ALL_BASE, json={"project_id": str(a_site), "ref": f"ok-{target}", field_of[target]: mine[target]}
                )
                bad = await client.post(ALL_BASE, json={"project_id": str(a_site), "ref": f"bad-{target}",
                                                        field_of[target]: theirs[target]})  # fmt: skip
                if good.status_code != 201:
                    problems.append(f"{target}: own link refused {good.status_code} {good.text[:200]}")
                if bad.status_code != 422:
                    problems.append(f"{target}: foreign link accepted {bad.status_code} {bad.text[:200]}")
            for q in ("%", "_", "\\", "100%", "%_\\"):
                for target in ("contract", "user"):
                    r = await client.get(f"{MB}/lookup/{target}", params={"q": q})
                    if r.status_code != 200:
                        problems.append(f"q={q!r} {target}: {r.status_code}")
                        continue
            pct = await client.get(f"{MB}/lookup/contract", params={"q": "%"})
            if [i["label"] for i in pct.json()["items"]] != ["A works 100%"]:
                problems.append(f"q='%' contract: {[i['label'] for i in pct.json()['items']]}")
            und = await client.get(f"{MB}/lookup/user", params={"q": "%_\\"})
            if [i["id"] for i in und.json()["items"]] != [alice]:
                problems.append(f"q='%_\\\\' user: {[i['label'] for i in und.json()['items']]}")

        _as(app, all_factory, ed, "editor")
        async with _client(app) as client:
            docs = await client.get(f"{MB}/lookup/document")
            doc_labels = await client.get(f"{MB}/lookup/document/labels", params={"ids": str(a_secret)})
            secret_link = await client.post(
                ALL_BASE, json={"project_id": str(a_site), "ref": "ed", "document": str(a_secret)}
            )
            exported = await client.get(f"{ALL_BASE}/export")
        # fmt: skip
        if str(a_secret) in {i["id"] for i in docs.json()["items"]}:
            problems.append("document: folder-restricted scan listed to Ed")
        if doc_labels.json()["labels"]:
            problems.append("document: folder-restricted scan labelled for Ed")
        if secret_link.status_code != 422:
            problems.append(f"document: Ed linked the restricted scan {secret_link.status_code}")
        if exported.status_code != 200:
            problems.append(f"export as Ed: {exported.status_code} {exported.text[:200]}")

        # Delete every target row Alice linked: the links must go to NULL.
        async with all_factory() as s:
            await s.execute(text("DELETE FROM oe_contracts_contract WHERE id = :i"), {"i": a_contract})
            await s.execute(text("DELETE FROM oe_contacts_contact WHERE id = :i"), {"i": str(a_contact)})
            await s.execute(text("DELETE FROM oe_schedule_activity WHERE id = :i"), {"i": str(a_act)})
            await s.execute(text("DELETE FROM oe_documents_document WHERE id = :i"), {"i": str(a_doc)})
            await s.execute(text("DELETE FROM oe_teams_membership WHERE user_id = :i"), {"i": ed})
            await s.execute(text("DELETE FROM oe_users_user WHERE id = :i"), {"i": ed})
            await s.commit()
        _as(app, all_factory, alice, "manager")
        async with _client(app) as client:
            listed = await client.get(ALL_BASE)
        assert listed.status_code == 200, listed.text
        for item in listed.json()["items"]:
            for f in ("contract", "contact", "activity", "document", "responsible"):
                if item[f] is not None:
                    problems.append(f"{f} still set after its target was deleted: {item['ref']}")
        assert problems == [], "\n".join(problems)


# ── 5. a module whose records belong to no project ──────────────────────────


class TestUnscopedLinks:
    async def test_crud_and_export_without_a_project(self, runtime_root: Path, app: FastAPI, installed, pg_engine):
        spec = _spec(
            FREE_KEY,
            "entry",
            [
                {"name": "ref", "label": "Ref", "type": "text", "required": True},
                {"name": "contract", "label": "Contract", "type": "link", "target": "contract"},
                {"name": "owner", "label": "Owner", "type": "link", "target": "user"},
                {"name": "amount", "label": "Amount", "type": "money"},
            ],
            {"export": True, "status": {"states": [{"code": "new", "label": "New"}, {"code": "ok", "label": "OK"}]}},
            scoped=False,
        )
        await service.install(spec, app)
        connection = await pg_engine.connect()
        outer = await connection.begin()
        made = async_sessionmaker(bind=connection, class_=AsyncSession, join_transaction_mode="create_savepoint",
                                  expire_on_commit=False)  # fmt: skip
        try:
            async with made() as s:
                alice = await _user(s, "manager", "Alice")
                bob = await _user(s, "manager", "Bob")
                a_site = await _project(s, alice, "A")
                b_site = await _project(s, bob, "B")
                a_contract = await _contract(s, a_site, "A works")
                b_contract = await _contract(s, b_site, "B works")
                await s.commit()
            _as(app, made, alice, "manager")
            async with _client(app) as client:
                ok = await client.post(
                    FREE_BASE, json={"ref": "1", "contract": a_contract, "owner": alice, "amount": "-12.50"}
                )
                foreign = await client.post(FREE_BASE, json={"ref": "2", "contract": b_contract})
                stranger = await client.post(FREE_BASE, json={"ref": "3", "owner": bob})
                patched = await client.patch(f"{FREE_BASE}/{ok.json().get('id')}", json={"status": "ok"})
                bad_status = await client.patch(f"{FREE_BASE}/{ok.json().get('id')}", json={"status": "nope"})
                null_status = await client.patch(f"{FREE_BASE}/{ok.json().get('id')}", json={"status": None})
                exported = await client.get(f"{FREE_BASE}/export")
                deleted = await client.delete(f"{FREE_BASE}/{ok.json().get('id')}")
            # fmt: skip
            assert ok.status_code == 201, ok.text
            assert foreign.status_code == 422, foreign.text
            assert stranger.status_code == 422, stranger.text
            assert patched.status_code == 200, patched.text
            assert bad_status.status_code == 422
            assert null_status.status_code == 422, null_status.text
            assert exported.status_code == 200, exported.text
            assert deleted.status_code in (200, 204)
        finally:
            if outer.is_active:
                await outer.rollback()
            await connection.close()
            try:
                await service.uninstall(FREE_KEY, app, drop_data=True)
            except service.InstallRefused:
                pass
            _forget_any(FREE_KEY)


# ── 6. comments edges ───────────────────────────────────────────────────────


class TestCommentEdges:
    async def test_comments_off_and_odd_keys(self, app: FastAPI, all_factory) -> None:
        async with all_factory() as s:
            alice = await _user(s, "manager", "Alice")
            site = await _project(s, alice, "site")
            await s.commit()
        _as(app, all_factory, alice, "manager")
        async with _client(app) as client:
            rec = await client.post(ALL_BASE, json={"project_id": str(site), "ref": "x"})
            off = await client.get(
                f"{COLLAB}/comments/", params={"entity_type": f"built.{ALL_KEY}", "entity_id": rec.json()["id"]}
            )
            upper = await client.get(
                f"{COLLAB}/comments/", params={"entity_type": "built.RV", "entity_id": rec.json()["id"]}
            )
            traversal = await client.get(
                f"{COLLAB}/comments/", params={"entity_type": "built.../x", "entity_id": rec.json()["id"]}
            )
        # fmt: skip
        assert rec.status_code == 201, rec.text
        assert off.status_code == 404, off.text
        assert upper.status_code in (400, 404)
        assert traversal.status_code in (400, 404)
