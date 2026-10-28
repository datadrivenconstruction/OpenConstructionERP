"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Router surface and permission gates (structural, no full app boot).

The full TestClient path is flaky on Windows (the documented loop artifact), so
these tests inspect the assembled APIRouter directly: that the ten documented
endpoints exist with the right methods, that each carries the expected
``RequirePermission`` dependency, and that the ``/entities`` discovery endpoint
returns the per-entity whitelist. The end-to-end run behaviour is covered by the
DB-backed service tests.
"""

from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://oe:oe@localhost:5432/openestimate")
os.environ.setdefault("DATABASE_SYNC_URL", "postgresql://oe:oe@localhost:5432/openestimate")

import pytest

from app.modules.saved_views.router import router


def _routes():
    return [r for r in router.routes if hasattr(r, "methods")]


def _route(path: str, method: str):
    for r in _routes():
        if r.path == path and method in r.methods:
            return r
    return None


@pytest.mark.parametrize(
    ("path", "method"),
    [
        ("/", "POST"),
        ("/", "GET"),
        ("/entities", "GET"),
        ("/{view_id}", "GET"),
        ("/{view_id}", "PATCH"),
        ("/{view_id}", "DELETE"),
        ("/{view_id}/run", "POST"),
        ("/run", "POST"),
        ("/{view_id}/count", "GET"),
        ("/{view_id}/export", "GET"),
    ],
)
def test_endpoint_exists(path: str, method: str):
    assert _route(path, method) is not None, f"{method} {path} is not mounted"


def _required_permissions(route) -> set[str]:
    perms: set[str] = set()
    for dep in route.dependencies:
        call = getattr(dep, "dependency", None)
        perm = getattr(call, "permission", None)
        if perm:
            perms.add(perm)
    # Also walk the dependant tree for path-operation dependencies.
    dependant = getattr(route, "dependant", None)
    if dependant is not None:
        for sub in dependant.dependencies:
            call = getattr(sub, "call", None)
            perm = getattr(call, "permission", None)
            if perm:
                perms.add(perm)
    return perms


@pytest.mark.parametrize(
    ("path", "method", "perm"),
    [
        ("/", "POST", "saved_views.create"),
        ("/", "GET", "saved_views.read"),
        ("/{view_id}", "PATCH", "saved_views.update"),
        ("/{view_id}", "DELETE", "saved_views.delete"),
        ("/{view_id}/run", "POST", "saved_views.read"),
        ("/{view_id}/export", "GET", "saved_views.export"),
    ],
)
def test_endpoint_permission_gate(path: str, method: str, perm: str):
    route = _route(path, method)
    assert route is not None
    assert perm in _required_permissions(route)


def test_permissions_registered_with_expected_roles():
    from app.core.permissions import Role, permission_registry
    from app.modules.saved_views.permissions import register_saved_views_permissions

    register_saved_views_permissions()
    assert permission_registry.get_min_role("saved_views.read") == Role.VIEWER
    assert permission_registry.get_min_role("saved_views.create") == Role.EDITOR
    assert permission_registry.get_min_role("saved_views.export") == Role.VIEWER


def test_entities_endpoint_returns_whitelist():
    """The /entities discovery payload lists each entity's whitelisted fields."""
    import asyncio

    from app.modules.saved_views.entities import register_builtin_entities
    from app.modules.saved_views.router import list_entities

    register_builtin_entities()
    payload = asyncio.run(list_entities(_={"sub": "x"}))
    entities = payload["entities"]
    assert "ledger_entry" in entities
    field_names = {f["name"] for f in entities["ledger_entry"]["fields"]}
    assert "account_code" in field_names
    # A non-whitelisted column must NOT be advertised.
    assert "created_by" not in field_names
