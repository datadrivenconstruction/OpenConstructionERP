# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Turning a module off has to stop it answering.

The loader mounts a module by handing its router to ``app.include_router`` and
takes it down again by editing ``app.routes``. That worked while including a
router copied every one of its routes into the application's route table.
Current FastAPI does not copy: it appends one marker object per include and
resolves the paths when a request arrives. A marker has no ``path``, so a sweep
that filters on ``path`` matches nothing, removes nothing, and reports success
while every endpoint of the disabled module keeps serving.

So these tests ask the question through the door rather than through the route
table: they send requests and read the schema. Both answers are the same under
either FastAPI, which is the point - the supported range spans the change.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app.core.module_loader import LoadedModule, ModuleLoader, ModuleManifest


@pytest.fixture(autouse=True)
def instance_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Enabling and disabling persists. Not into whoever ran the suite."""
    from app.core import module_state

    monkeypatch.setattr(module_state, "_resolve_data_dir", lambda data_dir=None: tmp_path / "instance-state")


def _router_for(name: str) -> APIRouter:
    """Three routes, shaped like the ones a generated module serves."""
    router = APIRouter()

    @router.get("")
    async def _list() -> dict[str, str]:
        return {"module": name}

    @router.get("/ui-spec")
    async def _ui_spec() -> dict[str, str]:
        return {"module": name}

    @router.get("/{record_id}")
    async def _one(record_id: str) -> dict[str, str]:
        return {"module": name, "id": record_id}

    return router


def _mount(loader: ModuleLoader, app: FastAPI, name: str, *, category: str = "community") -> APIRouter:
    """Mount a module exactly the way ``ModuleLoader._load_module`` mounts one.

    Including the same router object twice, canonically and under the legacy
    underscore mirror, is what production does for any key with an underscore
    in it, and it is where a removal that finds one mount and not the other
    leaves half a module behind.
    """
    dir_name = name.removeprefix("oe_")
    kebab_name = dir_name.replace("_", "-")
    router = _router_for(name)

    app.include_router(router, prefix=f"/api/v1/{kebab_name}", tags=[name])
    if kebab_name != dir_name:
        app.include_router(router, prefix=f"/api/v1/{dir_name}", tags=[name], include_in_schema=False)

    manifest = ModuleManifest(name=name, version="1.0.0", display_name=name, category=category)
    loader._manifests[name] = manifest
    loader._modules[name] = LoadedModule(manifest=manifest, package=None, router=router)
    return router


@pytest.fixture
def app() -> FastAPI:
    return FastAPI()


@pytest.fixture
def loader() -> ModuleLoader:
    """A loader of its own, so nothing here depends on what the process loaded."""
    return ModuleLoader()


class TestAMountedModule:
    def test_it_answers_on_both_the_canonical_path_and_the_mirror(self, loader, app) -> None:
        """The precondition. Without this the removal tests prove nothing."""
        _mount(loader, app, "oe_site_diary")
        client = TestClient(app)

        assert client.get("/api/v1/site-diary/ui-spec").status_code == 200
        assert client.get("/api/v1/site_diary/ui-spec").status_code == 200
        assert client.get("/api/v1/site-diary").status_code == 200
        assert client.get("/api/v1/site-diary/abc").json()["id"] == "abc"

    def test_the_loader_can_see_that_it_is_mounted(self, loader, app) -> None:
        """``_has_live_routes`` decides whether enabling reloads a module.

        Answering no about a module that is mounted makes every enable drop the
        loaded record and mount the router a second time, so the application
        accumulates a duplicate of every module anyone switches on.
        """
        _mount(loader, app, "oe_site_diary")
        assert loader._has_live_routes("oe_site_diary", app) is True

    def test_it_is_in_the_published_schema(self, loader, app) -> None:
        _mount(loader, app, "oe_site_diary")
        assert "/api/v1/site-diary/ui-spec" in app.openapi()["paths"]


class TestDisablingAModule:
    @pytest.mark.asyncio
    async def test_its_endpoints_stop_answering(self, loader, app) -> None:
        _mount(loader, app, "oe_site_diary")
        client = TestClient(app)
        assert client.get("/api/v1/site-diary/ui-spec").status_code == 200

        await loader.disable_module("oe_site_diary", app)

        assert client.get("/api/v1/site-diary/ui-spec").status_code == 404
        assert client.get("/api/v1/site-diary").status_code == 404
        assert client.get("/api/v1/site-diary/abc").status_code == 404

    @pytest.mark.asyncio
    async def test_the_legacy_mirror_goes_with_it(self, loader, app) -> None:
        """Two mounts, one module. Leaving the second one up leaves it serving."""
        _mount(loader, app, "oe_site_diary")
        client = TestClient(app)
        assert client.get("/api/v1/site_diary/ui-spec").status_code == 200

        await loader.disable_module("oe_site_diary", app)

        assert client.get("/api/v1/site_diary/ui-spec").status_code == 404

    @pytest.mark.asyncio
    async def test_the_route_table_is_the_size_it_started(self, loader, app) -> None:
        """A leftover entry that answers nothing is still a leak.

        Counted rather than searched by path: the thing left behind by a
        path-based sweep has no path, so only the count can see it.
        """
        before = len(app.routes)
        _mount(loader, app, "oe_site_diary")
        assert len(app.routes) > before

        await loader.disable_module("oe_site_diary", app)

        assert len(app.routes) == before

    @pytest.mark.asyncio
    async def test_the_schema_stops_advertising_it(self, loader, app) -> None:
        """Read once before disabling, because the schema is cached.

        The cache is keyed on a version the application bumps when its routes
        change. Editing ``app.routes`` in place does not bump it, so a document
        generated at any point before the removal keeps being handed out and
        keeps describing a module that is gone.
        """
        _mount(loader, app, "oe_site_diary")
        assert "/api/v1/site-diary/ui-spec" in app.openapi()["paths"]

        await loader.disable_module("oe_site_diary", app)

        assert "/api/v1/site-diary/ui-spec" not in app.openapi()["paths"]

    @pytest.mark.asyncio
    async def test_the_loader_reports_it_as_gone(self, loader, app) -> None:
        _mount(loader, app, "oe_site_diary")
        await loader.disable_module("oe_site_diary", app)
        assert loader._has_live_routes("oe_site_diary", app) is False

    @pytest.mark.asyncio
    async def test_a_module_whose_name_starts_the_same_keeps_serving(self, loader, app) -> None:
        """``/api/v1/schedule`` must not take ``/api/v1/schedule-advanced`` with it."""
        _mount(loader, app, "oe_schedule")
        _mount(loader, app, "oe_schedule_advanced")
        client = TestClient(app)

        await loader.disable_module("oe_schedule", app)

        assert client.get("/api/v1/schedule/ui-spec").status_code == 404
        assert client.get("/api/v1/schedule-advanced/ui-spec").status_code == 200
        assert client.get("/api/v1/schedule_advanced/ui-spec").status_code == 200
        assert loader._has_live_routes("oe_schedule", app) is False
        assert loader._has_live_routes("oe_schedule_advanced", app) is True

    @pytest.mark.asyncio
    async def test_the_module_next_to_it_is_untouched(self, loader, app) -> None:
        _mount(loader, app, "oe_site_diary")
        _mount(loader, app, "oe_day_works")
        client = TestClient(app)

        await loader.disable_module("oe_site_diary", app)

        assert client.get("/api/v1/day-works/ui-spec").json() == {"module": "oe_day_works"}
        assert "/api/v1/day-works/ui-spec" in app.openapi()["paths"]

    @pytest.mark.asyncio
    async def test_a_core_module_is_refused_and_keeps_serving(self, loader, app) -> None:
        _mount(loader, app, "oe_projects", category="core")
        client = TestClient(app)

        with pytest.raises(ValueError, match="core module"):
            await loader.disable_module("oe_projects", app)

        assert client.get("/api/v1/projects/ui-spec").status_code == 200

    @pytest.mark.asyncio
    async def test_a_module_something_else_depends_on_is_refused(self, loader, app) -> None:
        _mount(loader, app, "oe_site_diary")
        _mount(loader, app, "oe_day_works")
        loader._manifests["oe_day_works"].depends = ["oe_site_diary"]
        client = TestClient(app)

        with pytest.raises(ValueError, match="required by enabled modules"):
            await loader.disable_module("oe_site_diary", app)

        assert client.get("/api/v1/site-diary/ui-spec").status_code == 200
