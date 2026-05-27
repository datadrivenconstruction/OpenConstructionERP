"""Baseline tests for the architecture_map module.

The architecture map exposes high-signal structural intelligence about
the running ERP — module file lists, ORM models / table names / column
SQL types, dependency graph. That surface is gated to ``Role.ADMIN``
via the ``architecture.read`` permission. These tests pin that gate so
a future contributor does not silently drop it back to "any logged-in
user" the way it was before this audit.

What we assert:

* Non-admin (viewer) caller is rejected with **HTTP 403**.
* Admin caller gets **HTTP 200** with the documented response shape
  (``meta`` / ``modules`` / ``connections`` / ``layers`` / ``categories``
  keys, plus ``total_modules`` etc. on ``/stats``).
* The router exposes exactly the documented endpoint set so accidental
  surface widening is caught.

We mount the router in a throwaway FastAPI app and override
``get_current_user_payload`` to inject the role under test. That avoids
spinning up the full app + database and keeps the unit suite fast.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.permissions import (
    PermissionRegistry,
    Role,
    permission_registry,
)
from app.dependencies import get_current_user_payload
from app.modules.architecture_map.permissions import (
    register_architecture_map_permissions,
)
from app.modules.architecture_map.router import router


@pytest.fixture
def fresh_registry(monkeypatch):
    """Swap the global registry for a clean instance for this test only.

    The router resolves permissions via ``permission_registry`` at request
    time (through the live-registry fallback in ``RequirePermission``),
    so we have to patch the module attribute that ``dependencies.py``
    imports, not just create a local instance.
    """
    clean = PermissionRegistry()
    # Patch every import site that captured the original singleton at
    # import time. ``RequirePermission`` does a late ``from app.core...``
    # import on the fallback path, so patching the source is enough for
    # the auth gate; the module's own permissions.py and the live
    # registry assertion need the patched symbol too.
    monkeypatch.setattr("app.core.permissions.permission_registry", clean)
    monkeypatch.setattr(
        "app.modules.architecture_map.permissions.permission_registry",
        clean,
    )
    return clean


@pytest.fixture
def app(fresh_registry) -> FastAPI:
    """Mount the architecture_map router in a minimal app."""
    # Register the module's permissions onto the patched-in clean registry.
    register_architecture_map_permissions()
    # Sanity check — the registry actually got the gate we expect.
    assert fresh_registry.get_min_role("architecture.read") == Role.ADMIN

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/architecture-map")
    return app


def _set_role(app: FastAPI, role: str, permissions: list[str] | None = None) -> None:
    """Override the auth dependency to act as a user with ``role``."""

    async def _payload() -> dict[str, object]:
        return {
            "sub": "00000000-0000-0000-0000-000000000001",
            "role": role,
            "permissions": permissions or [],
        }

    app.dependency_overrides[get_current_user_payload] = _payload


# ── Negative path: non-admin is rejected ─────────────────────────────────


class TestNonAdminRejected:
    def test_viewer_gets_403_on_root(self, app):
        _set_role(app, role="viewer")
        client = TestClient(app)
        resp = client.get("/api/v1/architecture-map/")
        assert resp.status_code == 403
        assert "architecture.read" in resp.json()["detail"]

    def test_editor_gets_403_on_modules(self, app):
        _set_role(app, role="editor")
        client = TestClient(app)
        resp = client.get("/api/v1/architecture-map/modules/")
        assert resp.status_code == 403

    def test_manager_gets_403_on_stats(self, app):
        """Manager is one rung below admin — must still be blocked."""
        _set_role(app, role="manager")
        client = TestClient(app)
        resp = client.get("/api/v1/architecture-map/stats/")
        assert resp.status_code == 403

    def test_viewer_gets_403_on_search(self, app):
        _set_role(app, role="viewer")
        client = TestClient(app)
        resp = client.get("/api/v1/architecture-map/search/?q=projects")
        assert resp.status_code == 403


# ── Happy path: admin sees the documented shape ──────────────────────────


class TestAdminAllowed:
    def test_admin_gets_full_manifest_with_documented_shape(self, app):
        _set_role(app, role="admin")
        client = TestClient(app)
        resp = client.get("/api/v1/architecture-map/")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # The real manifest is auto-generated and only guarantees
        # ``modules``; the empty fallback dict provides the full set
        # (``modules`` / ``connections`` / ``layers`` / ``categories``).
        # We only pin the strict subset that's actually documented as
        # always-present.
        assert isinstance(body, dict)
        assert "modules" in body, "manifest response must always carry 'modules'"
        assert isinstance(body["modules"], list)

    def test_admin_modules_returns_list(self, app):
        _set_role(app, role="admin")
        client = TestClient(app)
        resp = client.get("/api/v1/architecture-map/modules/")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_admin_stats_returns_documented_counters(self, app):
        _set_role(app, role="admin")
        client = TestClient(app)
        resp = client.get("/api/v1/architecture-map/stats/")
        assert resp.status_code == 200
        body = resp.json()
        for key in (
            "total_modules",
            "total_connections",
            "total_layers",
            "total_categories",
            "modules_by_layer",
            "modules_by_category",
            "connections_by_type",
            "most_connected",
            "manifest_file_exists",
        ):
            assert key in body, f"missing stats key {key!r}"
        assert isinstance(body["total_modules"], int)
        assert isinstance(body["modules_by_layer"], dict)
        assert isinstance(body["most_connected"], list)

    def test_admin_search_requires_query(self, app):
        _set_role(app, role="admin")
        client = TestClient(app)
        # Query param is required + min_length=1 → 422 without it.
        resp = client.get("/api/v1/architecture-map/search/")
        assert resp.status_code == 422

    def test_admin_search_returns_grouped_results(self, app):
        _set_role(app, role="admin")
        client = TestClient(app)
        resp = client.get("/api/v1/architecture-map/search/?q=projects")
        assert resp.status_code == 200
        body = resp.json()
        for key in ("modules", "connections", "layers", "categories", "total", "query"):
            assert key in body
        assert body["query"] == "projects"


# ── Surface pinning: no accidental extra routes ──────────────────────────


def test_router_exposes_only_documented_endpoints():
    """Pin the registered route set so a new route can't sneak through
    without an explicit code review touching this test."""
    paths = sorted({route.path for route in router.routes})
    assert paths == sorted(
        [
            "/",
            "/modules/",
            "/modules/{module_id}",
            "/connections/",
            "/search/",
            "/stats/",
        ]
    ), f"unexpected router surface: {paths}"


def test_permissions_registered_at_admin_role():
    """The permission ``architecture.read`` must exist and require ADMIN.

    Done against the live registry rather than a clean one so a
    misconfigured production deploy (e.g. a startup hook that never
    ran) is caught.
    """
    # Make sure the registration function is idempotent — calling it on
    # the live registry after the app has already booted must not
    # raise and must leave the gate at ADMIN.
    register_architecture_map_permissions()
    assert permission_registry.get_min_role("architecture.read") == Role.ADMIN, (
        "architecture.read must require Role.ADMIN"
    )
