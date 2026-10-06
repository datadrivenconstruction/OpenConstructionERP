# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Deleting a section is a ``boq.delete`` call: a viewer is refused, an editor is not.

The BOQ grid now hides its delete controls (the section trash icon, the
"Delete section" menu item, the position Delete, the batch Delete) from any
role below ``boq.delete``, through ``PERMISSION_MIN_ROLE`` in the frontend's
``permissionGates.ts``. That is only honest while the server draws the line in
the same place: if the route moved to ``boq.update`` (VIEWER), the UI would be
hiding a control that works, which is the direction nobody notices.

This pins the server side of that agreement without a database or an app boot:
the section delete (``DELETE /positions/{id}?cascade=true``) is the position
delete route, that route depends on ``RequirePermission("boq.delete")``, and the
gate itself answers 403 to a viewer and lets an editor through.

Run:
    cd backend
    python -m pytest tests/modules/boq/test_section_delete_needs_boq_delete.py -v
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core.permissions import Role, permission_registry
from app.dependencies import RequirePermission
from app.modules.boq.permissions import register_boq_permissions
from app.modules.boq.router import router


def _delete_position_route():
    for route in router.routes:
        if getattr(route, "path", None) == "/positions/{position_id}" and "DELETE" in getattr(route, "methods", set()):
            return route
    return None


def _required_permissions(route) -> set[str]:
    perms: set[str] = set()
    for dep in getattr(route, "dependencies", []):
        perm = getattr(getattr(dep, "dependency", None), "permission", None)
        if perm:
            perms.add(perm)
    dependant = getattr(route, "dependant", None)
    if dependant is not None:
        for sub in dependant.dependencies:
            perm = getattr(getattr(sub, "call", None), "permission", None)
            if perm:
                perms.add(perm)
    return perms


def test_the_section_delete_route_is_gated_on_boq_delete() -> None:
    route = _delete_position_route()
    assert route is not None, "DELETE /positions/{position_id} is not mounted on the BOQ router"
    assert _required_permissions(route) == {"boq.delete"}


def test_boq_delete_starts_at_editor() -> None:
    register_boq_permissions()
    assert permission_registry.get_min_role("boq.delete") == Role.EDITOR
    assert not permission_registry.role_has_permission(Role.VIEWER, "boq.delete")
    assert permission_registry.role_has_permission(Role.EDITOR, "boq.delete")


@pytest.mark.asyncio
async def test_the_gate_refuses_a_viewer_and_admits_an_editor() -> None:
    register_boq_permissions()
    gate = RequirePermission("boq.delete")

    # A viewer's token carries what a viewer is granted, which excludes boq.delete.
    with pytest.raises(HTTPException) as refused:
        await gate({"sub": "viewer-1", "role": "viewer", "permissions": ["boq.read", "boq.update"]})
    assert refused.value.status_code == 403

    # An editor passes, also on a stale token without the permission listed
    # (the gate falls back to the live registry).
    await gate({"sub": "editor-1", "role": "editor", "permissions": ["boq.delete"]})
    await gate({"sub": "editor-2", "role": "editor", "permissions": []})
