# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Importing the router must register the module's permissions.

The failure this guards: ``permissions.py`` self-registers in the live
permission registry at import time, but the module loader only imports
router/models/hooks/events - so unless the ROUTER pulls permissions in,
nothing ever runs the registration. The registry denies unknown
permission names for every non-admin role, which silently turns the
whole module admin-only. Admin-role tests can never catch it - admin
bypasses the registry entirely.
"""

from __future__ import annotations

# The import under test: loading the router the way the module loader
# does must be enough to register the permissions.
import app.modules.comms_intelligence.router  # noqa: F401
from app.core.permissions import permission_registry


def test_router_import_registers_permissions_for_non_admin_roles() -> None:
    # Viewer-level read - what every list/get route gates on.
    assert permission_registry.role_has_permission("viewer", "comms_intelligence.read")
    # Editor-level verbs (spend AI tokens / mutate on confirm).
    for perm in (
        "comms_intelligence.analyze",
        "comms_intelligence.review",
        "comms_intelligence.draft",
    ):
        assert permission_registry.role_has_permission("editor", perm)
        # Floor, not blanket: viewers read but never run the editor verbs.
        assert not permission_registry.role_has_permission("viewer", perm)
