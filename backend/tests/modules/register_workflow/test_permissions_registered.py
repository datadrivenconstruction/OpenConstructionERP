# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Importing the router must register the module's permissions.

The failure this guards: ``permissions.py`` self-registers in the live
permission registry at import time, but the module loader only imports
router/models/hooks/events - so unless the ROUTER pulls permissions in,
nothing ever runs the registration. The registry denies unknown
permission names for every non-admin role, which silently turns the
whole module admin-only (the stress-pass "estimator 403 on /portfolio"
fail-closed skip was this bug). Admin-role tests can never catch it -
admin bypasses the registry entirely.
"""

from __future__ import annotations

# The import under test: loading the router the way the module loader
# does must be enough to register the permissions.
import app.modules.register_workflow.router  # noqa: F401
from app.core.permissions import permission_registry


def test_router_import_registers_permissions_for_non_admin_roles() -> None:
    # Viewer-level read - the permission every list/get route gates on.
    assert permission_registry.role_has_permission("viewer", "register_workflow.read")
    # Editor-level mutations.
    assert permission_registry.role_has_permission("editor", "register_workflow.create")
    assert permission_registry.role_has_permission("editor", "register_workflow.update")
    # The mapping is a floor, not a blanket: viewer must NOT get editor verbs,
    # and delete stays manager+.
    assert not permission_registry.role_has_permission("viewer", "register_workflow.create")
    assert not permission_registry.role_has_permission("editor", "register_workflow.delete")
    assert permission_registry.role_has_permission("manager", "register_workflow.delete")
