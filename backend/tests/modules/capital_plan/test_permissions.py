# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Role gates: viewers read, managers write, and every mutating route asks for the write permission."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core.permissions import Role, permission_registry
from app.dependencies import RequirePermission
from app.modules.capital_plan.permissions import register_capital_plan_permissions
from app.modules.capital_plan.router import router


async def test_viewer_write_is_403_and_viewer_read_passes() -> None:
    register_capital_plan_permissions()
    viewer = {"role": "viewer", "permissions": [], "sub": "u"}
    await RequirePermission("capital_plan.read")(viewer)
    with pytest.raises(HTTPException) as err:
        await RequirePermission("capital_plan.write")(viewer)
    assert err.value.status_code == 403


async def test_editor_write_is_403_and_manager_write_passes() -> None:
    register_capital_plan_permissions()
    with pytest.raises(HTTPException):
        await RequirePermission("capital_plan.write")({"role": "editor", "permissions": [], "sub": "u"})
    await RequirePermission("capital_plan.write")({"role": "manager", "permissions": [], "sub": "u"})
    assert permission_registry.role_has_permission(Role.MANAGER, "capital_plan.write")


def _gate(route) -> str:
    names = [getattr(d.dependency, "permission", "") for d in route.dependencies]
    return next((n for n in names if n.startswith("capital_plan.")), "")


def test_every_route_carries_a_gate_and_every_change_needs_write() -> None:
    seen = 0
    for route in router.routes:
        methods = route.methods - {"HEAD", "OPTIONS"}
        gate = _gate(route)
        assert gate, f"{route.path} has no capital_plan gate"
        if route.path.endswith("/autofund/"):
            # A suggestion: it reads, it never writes.
            assert methods == {"POST"} and gate == "capital_plan.read"
        elif methods == {"GET"}:
            assert gate == "capital_plan.read", route.path
        else:
            assert gate == "capital_plan.write", (route.path, methods)
        seen += 1
    assert seen >= 20
