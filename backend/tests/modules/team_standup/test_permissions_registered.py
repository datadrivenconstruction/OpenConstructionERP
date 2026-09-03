# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Importing the router must register the module's permissions.

The failure this guards: ``permissions.py`` self-registers in the live
permission registry at import time, but the module loader only imports
router/models/hooks/events - so unless the ROUTER pulls permissions in,
nothing ever runs the registration. The registry denies unknown
permission names for every non-admin role, which silently turns the
whole module admin-only. Admin-role tests can never catch it - admin
bypasses the registry entirely.

This module hit the bug TWICE: once at V1 (the original discovery,
fixed with the explicit router import) and again at V3, when a ruff
import-sort autofix silently dropped ``permissions as _permissions``
out of a combined import line - every editor got 403 on the whole
board while 38 admin-path tests stayed green. This file is the check
that fails when that import goes missing.
"""

from __future__ import annotations

# The import under test: loading the router the way the module loader
# does must be enough to register the permissions.
import app.modules.team_standup.router  # noqa: F401
from app.core.permissions import permission_registry

ALL_PERMISSIONS = (
    "team_standup.read",
    "team_standup.post",
    "team_standup.comment",
    "team_standup.tasks",
    "team_standup.config",
)


def test_router_import_registers_every_permission() -> None:
    for perm in ALL_PERMISSIONS:
        for role in ("viewer", "editor", "manager"):
            assert permission_registry.role_has_permission(role, perm), (
                f"{role} must pass {perm} - an unregistered permission "
                "fails closed and locks every non-admin out of the board"
            )
