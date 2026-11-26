"""A preview or a list is a read: a viewer gets it, only the write it leads to is refused.

Each case names a GET route that used to demand a write permission, reads the
gate off the route, and asks the gate itself whether a viewer passes. The
write route each preview leads to keeps its write gate and still refuses a
viewer.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from app.dependencies import RequirePermission
from app.modules.contracts.permissions import register_contracts_permissions
from app.modules.contracts.router import router as contracts_router
from app.modules.equipment.permissions import register_equipment_permissions
from app.modules.equipment.router import router as equipment_router
from app.modules.supplier_catalogs.permissions import register_supplier_catalogs_permissions
from app.modules.supplier_catalogs.router import router as supplier_router


def _permissions(route: APIRoute) -> set[str]:
    found: set[str] = set()
    stack = list(route.dependant.dependencies)
    while stack:
        dep = stack.pop()
        if isinstance(dep.call, RequirePermission):
            found.add(dep.call.permission)
        stack.extend(dep.dependencies)
    return found


def _route(router, method: str, path: str) -> APIRoute:
    for r in router.routes:
        if isinstance(r, APIRoute) and method in r.methods and r.path.endswith(path):
            return r
    raise AssertionError(f"no {method} route ending in {path}")


def _passes(permission: str, role: str) -> bool:
    gate = RequirePermission(permission)
    try:
        asyncio.run(gate({"sub": "u1", "role": role, "permissions": []}))
    except HTTPException as exc:
        assert exc.status_code == 403
        return False
    return True


@pytest.fixture(autouse=True)
def _registry() -> None:
    register_contracts_permissions()
    register_equipment_permissions()
    register_supplier_catalogs_permissions()


READS = [
    (contracts_router, "GET", "/progress-claims/{claim_id}/populate-from-progress"),
    (equipment_router, "GET", "/maintenance-schedules/due-within"),
    (supplier_router, "GET", "/migration/preview"),
]

WRITES = [
    (contracts_router, "PUT", "/progress-claims/{claim_id}/commit-populated-lines", "editor"),
    (equipment_router, "POST", "/maintenance-schedules/due-within/work-orders", "manager"),
]


@pytest.mark.parametrize(("router", "method", "path"), READS)
def test_a_viewer_passes_every_gate_on_the_read(router, method: str, path: str) -> None:
    perms = _permissions(_route(router, method, path))
    assert perms
    assert all(_passes(p, "viewer") for p in perms), perms


@pytest.mark.parametrize(("router", "method", "path", "writer"), WRITES)
def test_the_write_behind_the_preview_still_refuses_a_viewer(router, method: str, path: str, writer: str) -> None:
    perms = _permissions(_route(router, method, path))
    assert perms
    assert not all(_passes(p, "viewer") for p in perms), perms
    assert all(_passes(p, writer) for p in perms), perms


def test_listing_due_maintenance_creates_nothing() -> None:
    """The GET answers with due schedules, not work orders: creating them is the POST."""
    from app.modules.equipment.schemas import MaintenanceDueItem

    route = _route(equipment_router, "GET", "/maintenance-schedules/due-within")
    assert route.response_model == list[MaintenanceDueItem]
