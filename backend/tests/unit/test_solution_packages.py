# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Solution packages: registry consistency, additive install, module switches, route guard."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core import module_guard
from app.core import solution_packages as sp
from app.core.onboarding_presets import _CORE_MODULES
from app.core.solution_packages_router import router
from app.dependencies import get_current_user_id, get_current_user_payload
from app.modules.users.router import _get_service

USER_ID = str(uuid.UUID("00000000-0000-4000-8000-0000000000b1"))


def test_registry_is_consistent() -> None:
    assert sp.validate_registry() == []


def test_registry_has_ten_to_twelve_distinct_packages() -> None:
    assert 10 <= len(sp.SOLUTION_PACKAGES) <= 12
    signatures = {frozenset(p.required) for p in sp.SOLUTION_PACKAGES.values()}
    assert len(signatures) == len(sp.SOLUTION_PACKAGES)
    for pkg in sp.SOLUTION_PACKAGES.values():
        assert 5 <= len(pkg.menu) <= 8, pkg.id
        assert pkg.widgets and pkg.demo_id


def test_validation_flags_unknown_module(monkeypatch: pytest.MonkeyPatch) -> None:
    bad = sp.SolutionPackage(id="bad", icon="X", required=("no_such_module",), depends_on=("nope",))
    monkeypatch.setitem(sp.SOLUTION_PACKAGES, "bad", bad)
    issues = sp.validate_registry()
    assert any("unknown module 'no_such_module'" in i for i in issues)
    assert any("unknown package dependency 'nope'" in i for i in issues)


def test_resolution_closes_dependencies() -> None:
    mods = sp.resolve_modules(["takeoff"])
    graph = sp.module_dependencies()
    for mod in mods:
        assert set(graph.get(mod, ())) <= mods


def test_first_install_hides_the_rest_and_later_install_only_adds() -> None:
    meta, added = sp.install({}, ["takeoff"])
    assert added == ["takeoff"]
    assert sp.is_blocked(meta, "takeoff") is False
    assert sp.is_blocked(meta, "prefab") is True
    for core in _CORE_MODULES:
        assert meta["module_preferences"][core] is True

    before = sp.enabled_set(sp.read_state(meta))
    meta2, added2 = sp.install(meta, ["supply_chain"])
    assert added2 == ["supply_chain"]
    after = sp.enabled_set(sp.read_state(meta2))
    assert before <= after
    assert sp.is_blocked(meta2, "prefab") is False

    meta3, added3 = sp.install(meta2, ["supply_chain"])
    assert added3 == []
    assert meta3[sp.STATE_KEY] == meta2[sp.STATE_KEY]


def test_package_dependencies_install_with_it() -> None:
    meta, added = sp.install({}, ["tender_procurement"])
    assert set(added) == {"estimate_quote", "tender_procurement"}


def test_unknown_package_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown package"):
        sp.install({}, ["nope"])


def test_switching_off_a_needed_module_is_blocked_unless_forced() -> None:
    meta, _ = sp.install({}, ["supply_chain"])
    dependents = sp.dependents_of("procurement", sp.enabled_set(sp.read_state(meta)))
    if not dependents:
        pytest.skip("no gateable module depends on procurement")
    same, affected = sp.set_module(meta, "procurement", False)
    assert affected and same[sp.STATE_KEY] == meta[sp.STATE_KEY]
    forced, _ = sp.set_module(meta, "procurement", False, force=True)
    assert sp.is_blocked(forced, "procurement")


def test_switching_on_pulls_dependencies() -> None:
    meta, _ = sp.install({}, ["trades"])
    meta2, _ = sp.set_module(meta, "clash", True)
    assert not sp.is_blocked(meta2, "clash")
    assert not sp.is_blocked(meta2, "bim_hub")


def test_no_packages_means_nothing_blocked() -> None:
    assert sp.is_blocked({}, "prefab") is False
    assert sp.is_blocked(None, "prefab") is False


def test_module_from_path() -> None:
    assert module_guard.module_from_path("/api/v1/site-logistics/gates/") == "site_logistics"
    assert module_guard.module_from_path("/api/v1/users/me/") is None
    assert module_guard.module_from_path("/health") is None


# ── HTTP ──────────────────────────────────────────────────────────────────────


class _Service:
    def __init__(self) -> None:
        self.metadata: dict[str, Any] = {}

    async def get_user(self, user_id: uuid.UUID) -> SimpleNamespace:
        return SimpleNamespace(metadata_=dict(self.metadata))

    async def update_profile(self, user_id: uuid.UUID, **fields: Any) -> None:
        self.metadata = dict(fields["metadata_"])


def _client(service: _Service, payload: dict[str, Any] | None = None) -> httpx.AsyncClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user_id] = lambda: USER_ID
    app.dependency_overrides[get_current_user_payload] = lambda: payload or {"sub": USER_ID, "role": "admin"}
    app.dependency_overrides[_get_service] = lambda: service
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_http_list_install_toggle() -> None:
    service = _Service()
    async with _client(service) as client:
        listing = (await client.get("/api/v1/solution-packages/")).json()
        assert {p["id"] for p in listing["packages"]} == set(sp.SOLUTION_PACKAGES)
        assert listing["state"]["packaged"] is False

        res = await client.post("/api/v1/solution-packages/install/", json={"package_ids": ["site_field"]})
        assert res.status_code == 200
        body = res.json()
        assert body["added"] == ["site_field"] and body["demos"] == ["hospital-lyon"]
        assert "daily_diary" in body["enabled_modules"]

        bad = await client.post("/api/v1/solution-packages/install/", json={"package_ids": ["x"]})
        assert bad.status_code == 422

        res = await client.put("/api/v1/solution-packages/modules/prefab/", json={"enabled": True})
        assert res.status_code == 200 and res.json()["modules"]["prefab"] is True

        missing = await client.put("/api/v1/solution-packages/modules/users/", json={"enabled": False})
        assert missing.status_code == 404


@pytest.mark.asyncio
async def test_guard_answers_403_for_hidden_module(monkeypatch: pytest.MonkeyPatch) -> None:
    meta, _ = sp.install({}, ["takeoff"])

    async def _meta(_uid: str) -> dict[str, Any]:
        return meta

    monkeypatch.setattr(module_guard, "_load_metadata", _meta)
    monkeypatch.setattr(module_guard, "_user_id_from_scope", lambda scope: USER_ID)

    app = FastAPI()

    @app.get("/api/v1/prefab/units/")
    async def _units() -> list[str]:
        return []

    @app.get("/api/v1/takeoff/x/")
    async def _takeoff() -> list[str]:
        return []

    app.add_middleware(module_guard.ModuleGuardMiddleware)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        blocked = await client.get("/api/v1/prefab/units/")
        assert blocked.status_code == 403 and blocked.json()["detail"] == "module_disabled"
        assert (await client.get("/api/v1/takeoff/x/")).status_code == 200


def test_remove_hides_only_modules_no_other_package_needs() -> None:
    meta, _ = sp.install({}, ["takeoff", "bim_model"])
    after, hidden = sp.remove(meta, "takeoff")
    assert "dwg_takeoff" in hidden and "takeoff" in hidden
    assert "boq" not in hidden and "cad" not in hidden  # bim_model still needs them
    assert sp.read_state(after)["installed"] == ["bim_model"]
    assert not sp.is_blocked(after, "bim_hub") and sp.is_blocked(after, "dwg_takeoff")
    with pytest.raises(ValueError):
        sp.remove(after, "takeoff")


def test_remove_takes_dependent_packages_with_it() -> None:
    meta, _ = sp.install({}, ["tender_procurement"])
    after, _hidden = sp.remove(meta, "estimate_quote")
    assert sp.read_state(after)["installed"] == []


@pytest.mark.parametrize(
    ("payload", "allowed"),
    [
        ({"sub": USER_ID, "role": "admin"}, True),
        ({"sub": USER_ID, "role": "editor", "tenant_id": USER_ID}, True),
        ({"sub": USER_ID, "role": "manager"}, False),
        ({"sub": USER_ID, "role": "editor", "tenant_id": "someone-else"}, False),
        ({"sub": USER_ID, "role": "viewer"}, False),
    ],
)
@pytest.mark.asyncio
async def test_only_admin_or_owner_may_change_packages(payload: dict[str, Any], allowed: bool) -> None:
    service = _Service()
    async with _client(service, payload) as client:
        calls = [
            client.post("/api/v1/solution-packages/install/", json={"package_ids": ["takeoff"]}),
            client.put("/api/v1/solution-packages/modules/prefab/", json={"enabled": True}),
            client.post("/api/v1/solution-packages/takeoff/remove/", json={"confirm": False}),
        ]
        codes = [(await c).status_code for c in calls]
        assert (codes[0] == 200) is allowed and (codes[1] == 200) is allowed
        if not allowed:
            assert codes == [403, 403, 403] and service.metadata == {}
        assert (await client.get("/api/v1/solution-packages/")).status_code == 200


@pytest.mark.asyncio
async def test_http_remove_previews_then_confirms() -> None:
    service = _Service()
    async with _client(service) as client:
        await client.post("/api/v1/solution-packages/install/", json={"package_ids": ["takeoff", "supply_chain"]})
        preview = (await client.post("/api/v1/solution-packages/supply_chain/remove/", json={})).json()
        assert "prefab" in preview["hidden"] and preview["removed"] is False
        assert "supply_chain" in sp.read_state(service.metadata)["installed"]
        done = (await client.post("/api/v1/solution-packages/supply_chain/remove/", json={"confirm": True})).json()
        assert done["removed"] is True and done["modules"]["prefab"] is False
        missing = await client.post("/api/v1/solution-packages/supply_chain/remove/", json={"confirm": True})
        assert missing.status_code == 404
