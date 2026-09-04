# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Installing a module end to end, on the database it will run against.

Everything up to here checks a part: the spec refuses what cannot work, the
generator renders files that import, the table gets created. This checks the
one claim a user actually makes, which is that pressing install leaves them
with a module that is there.

It runs in the PostgreSQL lane because installing calls the module's own
startup hook, and that hook creates its table against the real engine.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import inspect

from app.modules.module_builder import service
from app.modules.module_builder.spec import EntitySpec, FieldSpec, ModuleSpec, RuleSpec

KEY = "pg_site_diary"


def _spec(**overrides) -> ModuleSpec:
    payload = {
        "key": KEY,
        "display_name": "Site Diary",
        "description": "One entry per day per crew, with weather and hours worked.",
        "entity": EntitySpec(
            name="entry",
            display_name="Entry",
            fields=[
                FieldSpec(name="entry_date", label="Date", type="date", required=True),
                FieldSpec(name="crew", label="Crew", type="text", required=True),
                FieldSpec(name="hours_worked", label="Hours worked", type="number", unit="h", required=True),
                FieldSpec(name="weather", label="Weather", type="select", options=["dry", "rain", "frost"]),
                FieldSpec(name="notes", label="Notes", type="long_text"),
            ],
        ),
        "rules": [
            RuleSpec(code="CREW_REQUIRED", message="An entry needs a crew.", kind="required", field="crew"),
            RuleSpec(
                code="HOURS_IN_RANGE",
                message="A crew cannot work more than 24 hours in a day.",
                kind="range",
                field="hours_worked",
                min_value=0,
                max_value=24,
            ),
            RuleSpec(
                code="ENTRY_NOT_FUTURE",
                message="A diary entry cannot be dated in the future.",
                kind="not_future",
                field="entry_date",
            ),
        ],
    }
    payload.update(overrides)
    return ModuleSpec(**payload)


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
        # A safety net for a test that failed before it could uninstall, not the
        # mechanism under test: uninstalling does all of this itself, and
        # test_the_key_is_free_again reinstalls inside one test to prove it.
        rr._package_path()[:] = before
        for name in [n for n in list(sys.modules) if n.startswith(f"app.modules.{KEY}")]:
            del sys.modules[name]
        table = Base.metadata.tables.get(f"oe_{KEY}_entry")
        if table is not None:
            Base.metadata.remove(table)
        Base.registry._class_registry.pop("Entry", None)
        importlib.invalidate_caches()


@pytest.fixture
def app() -> FastAPI:
    """A bare application, so mounting is observable rather than assumed."""
    return FastAPI()


@pytest.fixture(autouse=True)
def instance_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the enable/disable bookkeeping out of whoever ran the suite.

    Loading a module persists its state beside the database, which on this lane
    resolves to the home directory. A test run has no business switching
    modules on and off in the instance a developer actually uses.
    """
    from app.core import module_state

    monkeypatch.setattr(module_state, "_resolve_data_dir", lambda data_dir=None: tmp_path / "instance-state")


@pytest.fixture(autouse=True)
def platform_engine(pg_engine, monkeypatch: pytest.MonkeyPatch):
    """Point the platform engine at the cluster this lane runs against.

    Installing calls the generated module's own startup hook, and that hook
    creates its table on ``app.database.engine`` - which is the right thing in
    production and unbound here, because this lane hands out its own engine and
    never rebinds the global one. Without this the CREATE TABLE goes to
    whatever ``DATABASE_URL`` points at, which has no platform schema, and the
    foreign key to the projects table fails.

    Patched on the module rather than on an import: every caller resolves
    ``engine`` at call time, inside the function that uses it.
    """
    import app.database

    monkeypatch.setattr(app.database, "engine", pg_engine)


@pytest_asyncio.fixture
async def installed(runtime_root: Path, app: FastAPI, pg_engine):
    """A module installed for real, removed with its data afterwards."""
    spec = _spec()
    result = await service.install(spec, app)
    try:
        yield spec, result
    finally:
        try:
            await service.uninstall(KEY, app, drop_data=True)
        except service.InstallRefused:
            pass


async def _tables(engine) -> set[str]:
    async with engine.connect() as connection:
        return set(await connection.run_sync(lambda sync: inspect(sync).get_table_names()))


async def _columns(engine, table: str) -> set[str]:
    async with engine.connect() as connection:
        columns = await connection.run_sync(lambda sync: inspect(sync).get_columns(table))
    return {c["name"] for c in columns}


class TestInstall:
    @pytest.mark.asyncio
    async def test_the_files_land_in_the_runtime_root(self, runtime_root: Path, installed) -> None:
        spec, _ = installed
        directory = runtime_root / KEY
        assert directory.is_dir()
        assert (directory / "manifest.py").is_file()
        assert (directory / "spec.json").is_file()
        assert (directory / "models.py").is_file()
        # Not in the source tree: a platform upgrade must not be able to
        # overwrite what a user built, and a user without a checkout must still
        # be able to install one.
        from app.core.module_loader import MODULES_DIR

        assert not (Path(MODULES_DIR) / spec.key).exists()

    @pytest.mark.asyncio
    async def test_it_reports_what_it_installed(self, installed) -> None:
        spec, result = installed
        assert result.key == spec.key
        assert result.module_name == "oe_pg_site_diary"
        assert result.field_count == len(spec.entity.fields)
        assert result.rule_count == len(spec.rules)

    @pytest.mark.asyncio
    async def test_the_module_is_importable_afterwards(self, installed) -> None:
        """No restart. The point of installing at runtime is that it is live."""
        module = importlib.import_module(f"app.modules.{KEY}.manifest")
        assert module.manifest.name == "oe_pg_site_diary"

    @pytest.mark.asyncio
    async def test_its_table_exists(self, installed, pg_engine) -> None:
        """Created by the module's own startup hook during install."""
        assert f"oe_{KEY}_entry" in await _tables(pg_engine)

    @pytest.mark.asyncio
    async def test_its_routes_are_mounted_where_the_spec_says(self, app: FastAPI, installed) -> None:
        """A module that loaded but serves nothing is not installed as far as anyone can tell.

        The path is asserted exactly, not by substring. The loader mounts on the
        hyphenated form of the directory name, so a key with an underscore is
        served from a URL without one, and a substring check would pass on
        either. The frontend fetches ``base_path`` and has to be right.

        Read through :func:`served_paths` rather than off ``app.routes``, whose
        entries are one opaque marker per included router on current FastAPI.
        """
        from app.core.module_loader import served_paths

        spec, result = installed
        paths = set(served_paths(app))

        assert spec.url_prefix == "/api/v1/pg-site-diary"
        assert result.base_path == spec.url_prefix
        assert f"{spec.url_prefix}/ui-spec" in paths, f"nothing serves the screen description under {spec.url_prefix}"
        assert spec.url_prefix in paths, "the list endpoint is not where the wizard says it is"
        assert f"{spec.url_prefix}/{{record_id}}" in paths

    @pytest.mark.asyncio
    async def test_the_screen_description_is_served(self, app: FastAPI, installed) -> None:
        """Ask the application, not its bookkeeping.

        A route table is a claim about what would happen; this is what happens.
        The frontend has no compiled screen for a module built at runtime, so it
        renders from exactly this response, and a 404 here is a module the user
        installed and cannot open.
        """
        spec, _ = installed

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://install-test") as client:
            response = await client.get(f"{spec.url_prefix}/ui-spec")
            missing = await client.get("/api/v1/pg-site-diary-not-a-module/ui-spec")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["key"] == KEY
        assert [f["name"] for f in body["entity"]["fields"]] == [f.name for f in spec.entity.fields]
        # The control: this app really does answer 404 for something unmounted,
        # so the assertion above is about the module and not about the client.
        assert missing.status_code == 404

    @pytest.mark.asyncio
    async def test_its_permissions_are_registered(self, installed) -> None:
        from app.core.permissions import Role, permission_registry

        assert permission_registry.role_has_permission(Role.VIEWER, f"{KEY}.read")
        assert permission_registry.role_has_permission(Role.MANAGER, f"{KEY}.delete")
        assert not permission_registry.role_has_permission(Role.VIEWER, f"{KEY}.write")

    @pytest.mark.asyncio
    async def test_it_is_listed(self, installed) -> None:
        assert KEY in {m.key for m in service.installed()}

    @pytest.mark.asyncio
    async def test_installing_the_same_key_twice_is_refused(self, app: FastAPI, installed) -> None:
        spec, _ = installed
        with pytest.raises(service.InstallRefused, match="already installed"):
            await service.install(spec, app)


class TestUninstall:
    @pytest.mark.asyncio
    async def test_the_files_go_and_the_data_stays(self, runtime_root: Path, app: FastAPI, pg_engine) -> None:
        """The default. Someone removing a module should not lose what they recorded.

        The table is left behind on purpose: reinstalling the same module finds
        its rows where it left them, and dropping it later is a separate ask.
        """
        await service.install(_spec(), app)
        result = await service.uninstall(KEY, app)

        assert result["removed"] is True
        assert result["data_dropped"] is False
        assert not (runtime_root / KEY).exists()
        # The claim being made: the rows are still there to come back to.
        assert f"oe_{KEY}_entry" in await _tables(pg_engine)

        # Put the cluster back as it was found. Uninstalling again cannot do
        # it: the module is gone, so there is nothing left to ask.
        async with pg_engine.begin() as connection:
            await connection.exec_driver_sql(f'DROP TABLE IF EXISTS "oe_{KEY}_entry"')

    @pytest.mark.asyncio
    async def test_asking_for_the_data_to_go_drops_the_table(self, runtime_root, app: FastAPI, pg_engine) -> None:
        await service.install(_spec(), app)
        assert f"oe_{KEY}_entry" in await _tables(pg_engine)

        result = await service.uninstall(KEY, app, drop_data=True)

        assert result["data_dropped"] is True
        assert f"oe_{KEY}_entry" not in await _tables(pg_engine)

    @pytest.mark.asyncio
    async def test_it_stops_answering(self, runtime_root: Path, app: FastAPI, pg_engine) -> None:
        """Removed means removed. A module still serving after it was taken away
        is worse than one that never went: the files are gone, so nobody can
        read what is answering, and the endpoints keep running until a restart.

        Counted as well as requested. The route table holds one entry per mount
        and a module with an underscore in its key is mounted twice, so an
        entry left behind by a removal that found only one of them is invisible
        to any check that asks about paths.
        """
        base = "/api/v1/pg-site-diary"
        empty = len(app.routes)

        await service.install(_spec(), app)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://uninstall-test") as client:
            while_installed = await client.get(f"{base}/ui-spec")
        assert while_installed.status_code == 200

        await service.uninstall(KEY, app, drop_data=True)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://uninstall-test") as client:
            afterwards = await client.get(f"{base}/ui-spec")
            legacy = await client.get("/api/v1/pg_site_diary/ui-spec")
        assert afterwards.status_code == 404
        assert legacy.status_code == 404, "the underscore mirror outlived the module"
        assert len(app.routes) == empty, "the removal left an entry behind"
        assert base not in app.openapi()["paths"], "the published schema still describes it"

    @pytest.mark.asyncio
    async def test_it_stops_being_listed_and_counted(self, runtime_root: Path, app: FastAPI, pg_engine) -> None:
        """The module registry has to let go of it too, not just the route table.

        Disabling a module deliberately keeps its manifest, because that is what
        a later enable reads back. Removing one has no such reader: the files
        are gone. A manifest kept anyway is a module ``GET /api/v1/modules``
        still lists, the health endpoint's ``modules_discovered`` still counts,
        and the enable route still accepts, since its 404 guard is a lookup in
        that registry. ``modules_loaded`` used to be the length of that same
        list rather than of the loaded ones, so it counted the ghost too; it now
        counts what its name says, which narrows this defect without closing it,
        because the registry entry is still there for the enable route to find.
        Accepting is the one that hurts: the enable then walks into importlib
        and raises ``ModuleNotFoundError``, which is not the ``ValueError`` the
        route catches, so the caller gets a 500 where a 404 was the answer.
        """
        from app.core.module_loader import module_loader

        module_name = f"oe_{KEY}"
        await service.install(_spec(), app)
        listed = {row["name"] for row in module_loader.list_modules()}
        assert module_name in listed, "the freshly installed module was not listed"
        counted_while_installed = len(module_loader.list_modules())

        await service.uninstall(KEY, app, drop_data=True)

        assert module_name not in {row["name"] for row in module_loader.list_modules()}
        assert len(module_loader.list_modules()) == counted_while_installed - 1
        # Population beside the verdict: what the registry holds is now what the
        # loader has actually loaded plus whatever is switched off, and this key
        # is in neither.
        assert module_name not in module_loader.loaded_modules
        # The guard both /modules/<name>/enable and /disable ask before doing
        # anything. It has to say no now, so the caller gets a 404.
        assert module_name not in module_loader._manifests

    @pytest.mark.asyncio
    async def test_the_permissions_go_with_it(self, runtime_root: Path, app: FastAPI, pg_engine) -> None:
        """A module that is gone must stop granting anything.

        Left registered, its permissions keep appearing in the admin matrix and
        keep being granted to roles with nothing behind them. The check is made
        against a registry the module has demonstrably just entered, so it
        cannot pass on residue from an earlier test.
        """
        from app.core.permissions import Role, permission_registry

        await service.install(_spec(), app)
        assert permission_registry.role_has_permission(Role.VIEWER, f"{KEY}.read")
        assert KEY in permission_registry.list_modules()

        await service.uninstall(KEY, app, drop_data=True)

        assert not permission_registry.role_has_permission(Role.VIEWER, f"{KEY}.read")
        assert KEY not in permission_registry.list_modules()

    @pytest.mark.asyncio
    async def test_the_key_is_free_again(self, runtime_root: Path, app: FastAPI, pg_engine) -> None:
        """Install, remove, install again with a different record shape.

        This is what a user does after getting a field wrong, and it is where a
        cached import of the old module would quietly serve the old shape. The
        second spec adds a column rather than only renaming the module: the
        class is re-declared under the same name, so a stale entry in the
        mapper registry or in ``sys.modules`` shows up as a table without the
        new column rather than as an error.
        """
        await service.install(_spec(), app)
        await service.uninstall(KEY, app, drop_data=True)

        entity = _spec().entity
        reshaped = _spec(
            display_name="Daily Diary",
            entity=entity.model_copy(
                update={
                    "fields": [
                        *entity.fields,
                        FieldSpec(name="shift", label="Shift", type="select", options=["day", "night"]),
                    ]
                }
            ),
        )
        result = await service.install(reshaped, app)
        try:
            assert result.display_name == "Daily Diary"
            assert result.field_count == len(entity.fields) + 1
            module = importlib.import_module(f"app.modules.{KEY}.manifest")
            assert module.manifest.display_name == "Daily Diary"

            columns = await _columns(pg_engine, f"oe_{KEY}_entry")
            assert "shift" in columns, "the table was built from the module it replaced"
        finally:
            await service.uninstall(KEY, app, drop_data=True)

    @pytest.mark.asyncio
    async def test_it_leaves_the_rest_of_the_schema_alone(self, runtime_root, app: FastAPI, pg_engine) -> None:
        """Removing one module must not take another module's schema with it."""
        before = await _tables(pg_engine)
        assert len(before) > 50, "the cluster has no platform schema, so this proves nothing"

        await service.install(_spec(), app)
        await service.uninstall(KEY, app, drop_data=True)

        assert await _tables(pg_engine) == before
