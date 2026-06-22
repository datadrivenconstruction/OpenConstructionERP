# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍RBAC tests for the EAC v2 engine (Max-Audit finding #6).

Before this fix the entire EAC router gated every endpoint with only
``CurrentUserId`` + a tenant check - there was no ``permissions.py`` and
no ``on_startup`` hook, so a read-only VIEWER (the default registration
role) could create / edit / delete cost-calculation rules and trigger
runs. This module asserts the new role gate:

* ``eac.read``   -> VIEWER
* ``eac.write``  -> EDITOR  (create/update rule + ruleset, import aliases)
* ``eac.delete`` -> MANAGER (delete rule/ruleset/alias)
* ``eac.run``    -> EDITOR  (run/rerun/cancel/dry-run/validate/compile)

and that EVERY mutating/executing route in the EAC routers (and the
aliases sub-router) actually carries a ``RequirePermission`` dependency,
so a viewer is rejected (403) before any DB work - including the
formula-executing dry-run / validate / compile / resolve paths.

These run at the registry / route-introspection level rather than over
HTTP, mirroring ``tests/unit/test_hse_advanced_security.py`` -
booting the full FastAPI app would load ~110 modules per test.
"""

from __future__ import annotations

from app.core.permissions import Role, permission_registry
from app.modules.eac.permissions import register_eac_permissions

# ── 1. Permission -> minimum role mapping ───────────────────────────────


def test_eac_permission_min_roles() -> None:
    """The four EAC permissions map to the documented minimum roles."""
    register_eac_permissions()

    assert permission_registry.get_min_role("eac.read") == Role.VIEWER
    assert permission_registry.get_min_role("eac.write") == Role.EDITOR
    assert permission_registry.get_min_role("eac.delete") == Role.MANAGER
    assert permission_registry.get_min_role("eac.run") == Role.EDITOR


# ── 2. A VIEWER may read but must NOT write / run / delete ───────────────


def test_viewer_cannot_write_run_or_delete_eac() -> None:
    """Finding #6: a read-only VIEWER must be rejected from the write /

    execute / delete surface (create_rule, run, etc.) while still being
    able to read.
    """
    register_eac_permissions()

    # A viewer keeps read access.
    assert permission_registry.role_has_permission(Role.VIEWER, "eac.read") is True

    # ...but cannot author rules/rulesets, run the engine, or delete.
    assert permission_registry.role_has_permission(Role.VIEWER, "eac.write") is False
    assert permission_registry.role_has_permission(Role.VIEWER, "eac.run") is False
    assert permission_registry.role_has_permission(Role.VIEWER, "eac.delete") is False


def test_editor_can_write_and_run_but_not_delete_eac() -> None:
    """An EDITOR authors + runs rules; deletes stay MANAGER-only."""
    register_eac_permissions()

    assert permission_registry.role_has_permission(Role.EDITOR, "eac.read") is True
    assert permission_registry.role_has_permission(Role.EDITOR, "eac.write") is True
    assert permission_registry.role_has_permission(Role.EDITOR, "eac.run") is True
    assert permission_registry.role_has_permission(Role.EDITOR, "eac.delete") is False

    # MANAGER inherits write/run and gains delete.
    assert permission_registry.role_has_permission(Role.MANAGER, "eac.delete") is True


# ── 3. on_startup wires the permission registration ─────────────────────


async def test_on_startup_registers_eac_permissions() -> None:
    """The module ``on_startup`` hook must populate the registry.

    Without this the ``RequirePermission`` gates would deny everyone
    (unknown permission -> deny) and the module would be dead, so the
    loader-invoked hook is part of the contract.
    """
    from app.modules.eac import on_startup

    await on_startup()
    assert permission_registry.get_min_role("eac.write") == Role.EDITOR
    assert permission_registry.get_min_role("eac.run") == Role.EDITOR


# ── 4. Every mutating/executing route carries a RequirePermission gate ───


# Routes that change state or execute user-supplied rule/formula bodies.
# Path is the suffix as declared on the EAC router (mounted at
# ``/api/v1/eac``). A bare RequirePermission MUST be present on each, or
# a viewer could reach it - the exact bypass class finding #6 describes.
_MUTATING_OR_EXECUTING = {
    ("POST", "/rules"),
    ("PUT", "/rules/{rule_id}"),
    ("DELETE", "/rules/{rule_id}"),
    ("POST", "/rules:validate"),
    ("POST", "/rules:dry-run"),
    ("POST", "/rules:compile"),
    ("POST", "/rulesets"),
    ("PUT", "/rulesets/{ruleset_id}"),
    ("DELETE", "/rulesets/{ruleset_id}"),
    ("POST", "/rulesets/{ruleset_id}:run"),
    ("POST", "/runs/{run_id}:cancel"),
    ("POST", "/runs/{run_id}:rerun"),
    # Aliases sub-router (mounted under the same parent router).
    ("POST", "/aliases"),
    ("PUT", "/aliases/{alias_id}"),
    ("DELETE", "/aliases/{alias_id}"),
    ("POST", "/aliases/{alias_id}/test"),
    ("POST", "/aliases:resolve-bulk"),
    ("POST", "/aliases:resolve"),
    ("POST", "/aliases:import"),
}


def _route_has_require_permission(route) -> bool:
    """True when a FastAPI route carries a ``RequirePermission`` dependency."""
    from app.dependencies import RequirePermission

    for dep in getattr(getattr(route, "dependant", None), "dependencies", []):
        call = getattr(dep, "call", None)
        if isinstance(call, RequirePermission):
            return True
    # ``dependencies=[Depends(RequirePermission(...))]`` also surfaces on the
    # APIRoute's own ``dependencies`` list as Depends objects.
    for dep in getattr(route, "dependencies", []) or []:
        if isinstance(getattr(dep, "dependency", None), RequirePermission):
            return True
    return False


def test_all_mutating_eac_routes_require_permission() -> None:
    """No mutating/executing EAC endpoint may be reachable without a gate.

    Guards against a future endpoint being added (or one of the existing
    ones losing its gate) and silently re-opening the finding-#6 hole.
    """
    from app.modules.eac.aliases.router import router as eac_aliases_router
    from app.modules.eac.router import router as eac_router

    seen: dict[tuple[str, str], bool] = {}
    # The aliases sub-router is included into eac_router at import time, but we
    # also iterate it directly so its routes are always discoverable regardless
    # of include ordering (and so each alias route's permission gate is checked).
    for route in list(eac_router.routes) + list(eac_aliases_router.routes):
        methods = getattr(route, "methods", None) or set()
        path = getattr(route, "path", "")
        for method in methods:
            key = (method, path)
            if key in _MUTATING_OR_EXECUTING:
                seen[key] = _route_has_require_permission(route)

    missing_routes = sorted(k for k in _MUTATING_OR_EXECUTING if k not in seen)
    assert not missing_routes, f"Expected EAC routes not found (path drift?): {missing_routes}"

    ungated = sorted(k for k, ok in seen.items() if not ok)
    assert not ungated, f"Mutating/executing EAC routes missing a RequirePermission gate: {ungated}"
