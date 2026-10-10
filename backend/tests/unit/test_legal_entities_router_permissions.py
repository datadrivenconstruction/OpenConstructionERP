"""Every write on legal entities is admin-only; reads need only a signed-in user.

The service tests run below the router, so a write route that lost its
permission dependency would still pass all of them. These tests read the gate
off each route and then ask the gate itself who gets through.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from app.dependencies import RequirePermission
from app.modules.legal_entities.permissions import register_legal_entities_permissions
from app.modules.legal_entities.router import router


def _permissions(route: APIRoute) -> set[str]:
    found: set[str] = set()
    stack = list(route.dependant.dependencies)
    while stack:
        dep = stack.pop()
        if isinstance(dep.call, RequirePermission):
            found.add(dep.call.permission)
        stack.extend(dep.dependencies)
    return found


def _routes() -> list[APIRoute]:
    return [r for r in router.routes if isinstance(r, APIRoute)]


def test_every_write_route_requires_manage() -> None:
    writes = [r for r in _routes() if r.methods & {"POST", "PATCH", "PUT", "DELETE"}]
    # Entities and branches, each created, updated and deleted.
    assert len(writes) == 6
    missing = [f"{sorted(r.methods)} {r.path}" for r in writes if "legal_entities.manage" not in _permissions(r)]
    assert missing == []


def test_read_routes_do_not_demand_manage() -> None:
    reads = [r for r in _routes() if r.methods <= {"GET", "HEAD"}]
    assert reads
    assert all("legal_entities.manage" not in _permissions(r) for r in reads)


@pytest.mark.parametrize("role", ["viewer", "editor", "manager"])
def test_manage_refuses_below_admin(role: str) -> None:
    register_legal_entities_permissions()
    gate = RequirePermission("legal_entities.manage")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(gate({"sub": "u1", "role": role, "permissions": []}))
    assert exc.value.status_code == 403


def test_manage_lets_an_admin_through() -> None:
    register_legal_entities_permissions()
    gate = RequirePermission("legal_entities.manage")
    asyncio.run(gate({"sub": "u1", "role": "admin", "permissions": []}))
