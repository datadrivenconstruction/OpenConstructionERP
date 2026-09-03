# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Importing the router must register the module's permissions.

The failure this guards: ``permissions.py`` self-registers in the live
permission registry at import time, but the module loader only imports
router/models/hooks/events - so unless the ROUTER pulls permissions in,
nothing ever runs the registration. The registry denies unknown
permission names for every non-admin role, which silently turns the
whole module admin-only. Admin-role tests can never catch it.
"""

from __future__ import annotations

# The import under test: loading the router the way the module loader
# does must be enough to register the permissions.
import app.modules.work_requests.router  # noqa: F401
from app.core.permissions import permission_registry


def test_router_import_registers_every_permission() -> None:
    for perm in ("work_requests.read", "work_requests.create"):
        for role in ("viewer", "editor", "manager"):
            assert permission_registry.role_has_permission(role, perm), (
                f"{role} must pass {perm} - every authenticated user reads and raises"
            )
    for role in ("editor", "manager"):
        assert permission_registry.role_has_permission(role, "work_requests.update")
    assert permission_registry.role_has_permission("manager", "work_requests.manage")


def test_viewer_cannot_update_and_editor_cannot_manage() -> None:
    assert not permission_registry.role_has_permission("viewer", "work_requests.update")
    assert not permission_registry.role_has_permission("viewer", "work_requests.manage")
    assert not permission_registry.role_has_permission("editor", "work_requests.manage")
