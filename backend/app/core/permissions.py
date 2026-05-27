"""‌⁠‍RBAC permission engine.

Role-Based Access Control with permission inheritance.
Roles are hierarchical: admin > manager > editor > viewer.
Modules register their own permissions at startup.

Usage:
    from app.core.permissions import permission_registry, Role

    # Register module permissions
    permission_registry.register_module_permissions("projects", [
        "projects.create",
        "projects.read",
        "projects.update",
        "projects.delete",
    ])

    # Check permission
    if permission_registry.role_has_permission(Role.EDITOR, "projects.update"):
        ...
"""

import logging
from enum import StrEnum

logger = logging.getLogger(__name__)


class Role(StrEnum):
    """‌⁠‍Built-in roles with hierarchical permissions."""

    ADMIN = "admin"  # Full access to everything
    MANAGER = "manager"  # Project management, team management
    EDITOR = "editor"  # Create and modify content
    VIEWER = "viewer"  # Read-only access
    # ── Field-worker surface (mobile/tablet, see
    # docs/architecture/FIELD_WORKER_MOBILE_DESIGN.md). DESIGN-STAGE
    # placeholders — the permission set is intentionally empty until
    # the pilot router lands so adding the enum value does not
    # accidentally widen any existing endpoint's scope.
    SITE_INSPECTOR = "site_inspector"  # QA/HSE inspector, read-broad write-narrow
    SITE_FOREMAN = "site_foreman"  # crew foreman, signs off worker entries
    FIELD_WORKER = "field_worker"  # site labourer, lowest-trust persona


# Role hierarchy: higher roles inherit all permissions of lower roles.
#
# Field-role ranks are NEGATIVE (below VIEWER=0) to ensure that a
# default-`-1` lookup (the legacy fallback shape used by
# `role_has_permission`) cannot accidentally promote a field worker
# above a viewer. Anywhere the legacy `-1` floor is read, it must be
# audited as part of the field-pilot landing PR — see the design doc
# §11 Risk #3.
ROLE_HIERARCHY: dict[Role, int] = {
    Role.FIELD_WORKER: -2,
    Role.SITE_FOREMAN: -1,
    Role.SITE_INSPECTOR: 0,
    Role.VIEWER: 0,
    Role.EDITOR: 1,
    Role.MANAGER: 2,
    Role.ADMIN: 3,
}


# Alias map — legacy / industry-specific role names that should behave like
# one of the canonical four roles. Keeps the core Role enum small while
# allowing construction-industry titles ("estimator", "surveyor", ...) to
# work without manual migration. Values are ALWAYS canonical Role members.
ROLE_ALIASES: dict[str, Role] = {
    "estimator": Role.EDITOR,
    "quantity_surveyor": Role.EDITOR,
    "qs": Role.EDITOR,
    "user": Role.EDITOR,
    "superuser": Role.ADMIN,
    "owner": Role.ADMIN,
    "readonly": Role.VIEWER,
    "guest": Role.VIEWER,
}


def _resolve_role(role: "Role | str") -> "Role | None":
    """‌⁠‍Resolve any role string (including aliases) to a canonical Role, or None."""
    if isinstance(role, Role):
        return role
    if not role:
        return None
    key = role.strip().lower()
    try:
        return Role(key)
    except ValueError:
        return ROLE_ALIASES.get(key)


class PermissionRegistry:
    """Central registry of all permissions in the system.

    Permissions follow the pattern: '{module}.{action}'
    Examples: 'projects.create', 'boq.export', 'users.manage'

    Each permission has a minimum required role level.
    """

    def __init__(self) -> None:
        # permission_name → minimum Role required
        self._permissions: dict[str, Role] = {}
        # module_name → list of permission names
        self._module_permissions: dict[str, list[str]] = {}

    def register(self, permission: str, min_role: Role = Role.EDITOR) -> None:
        """Register a single permission with its minimum required role."""
        self._permissions[permission] = min_role
        logger.debug("Registered permission: %s (min_role=%s)", permission, min_role.value)

    def register_module_permissions(
        self,
        module_name: str,
        permissions: dict[str, Role],
    ) -> None:
        """Register all permissions for a module.

        Args:
            module_name: Module identifier (e.g., 'projects').
            permissions: Dict of permission_name → minimum Role.
        """
        self._module_permissions[module_name] = list(permissions.keys())
        for perm, min_role in permissions.items():
            self._permissions[perm] = min_role
        logger.info(
            "Registered %d permissions for module '%s'",
            len(permissions),
            module_name,
        )

    def role_has_permission(self, role: Role | str, permission: str) -> bool:
        """Check if a role has a specific permission.

        Admin always has all permissions.
        Other roles are checked against the hierarchy.
        Accepts canonical roles and legacy aliases (e.g. "estimator").
        """
        resolved = _resolve_role(role)
        if resolved is None:
            return False

        # Admin bypasses all checks
        if resolved == Role.ADMIN:
            return True

        min_role = self._permissions.get(permission)
        if min_role is None:
            # Unknown permission — deny by default
            logger.warning("Unknown permission checked: %s", permission)
            return False

        return ROLE_HIERARCHY.get(resolved, -1) >= ROLE_HIERARCHY.get(min_role, 999)

    def get_role_permissions(self, role: Role | str) -> list[str]:
        """Get all permissions available to a role."""
        resolved = _resolve_role(role)
        if resolved is None:
            return []

        if resolved == Role.ADMIN:
            return list(self._permissions.keys())

        return [
            perm
            for perm, min_role in self._permissions.items()
            if ROLE_HIERARCHY.get(resolved, -1) >= ROLE_HIERARCHY.get(min_role, 999)
        ]

    def list_all(self) -> dict[str, str]:
        """List all registered permissions with their minimum role."""
        return {perm: role.value for perm, role in sorted(self._permissions.items())}

    def list_modules(self) -> dict[str, list[str]]:
        """List permissions grouped by module."""
        return dict(self._module_permissions)

    def clear(self) -> None:
        """Remove all permissions. Used in testing."""
        self._permissions.clear()
        self._module_permissions.clear()

    # ── Edit operations (used by the admin permissions matrix UI) ─────────

    def has(self, permission: str) -> bool:
        """True iff the permission key exists in the registry."""
        return permission in self._permissions

    def get_min_role(self, permission: str) -> Role | None:
        """Return the minimum role required for ``permission`` or ``None``."""
        return self._permissions.get(permission)

    def set_min_role(self, permission: str, min_role: Role) -> Role:
        """Update the minimum role for an existing permission.

        Returns the previous ``min_role`` so callers can audit the delta.
        Raises ``KeyError`` if the permission is not registered — we never
        silently create permissions through the admin UI.
        """
        previous = self._permissions.get(permission)
        if previous is None:
            raise KeyError(permission)
        self._permissions[permission] = min_role
        logger.info(
            "Permission min_role updated: %s %s → %s",
            permission,
            previous.value,
            min_role.value,
        )
        return previous

    def snapshot(self) -> dict[str, Role]:
        """Return a copy of the current permission → min_role map.

        Used by the admin UI to diff against a preset / baseline without
        mutating the live registry.
        """
        return dict(self._permissions)


# Global singleton
permission_registry = PermissionRegistry()


# ── Role presets for the admin UI ─────────────────────────────────────────
#
# A preset answers "what should role X be able to do by default?" without
# resetting every permission row by hand. Applied by walking every
# registered permission and computing the implied min_role from a rule.
#
# Each preset is a callable (permission_key) -> Role:
#
#   • viewer-default   — viewer can read, everything else stays Editor+.
#   • editor-default   — editor can read/create/update, manager+ for
#                        delete / destructive actions, admin for "system."
#   • manager-default  — manager can do almost anything; admin still owns
#                        system-level toggles.
#
# Presets are intentionally derived from the permission key shape rather
# than from a hard-coded list — this keeps them working even as new
# modules register new permissions.


def _viewer_default(key: str) -> Role:
    # Everything readable to viewers, structural changes manager+, system
    # toggles admin-only.
    if key.startswith("system.") or key.endswith(".delete"):
        return Role.ADMIN if key.startswith("system.") else Role.MANAGER
    if any(key.endswith(s) for s in (".read", ".list", ".view", ".export")):
        return Role.VIEWER
    return Role.EDITOR


def _editor_default(key: str) -> Role:
    if key.startswith("system."):
        return Role.ADMIN
    if key.endswith(".delete") or key.endswith(".approve") or key.endswith(".reject"):
        return Role.MANAGER
    if any(key.endswith(s) for s in (".read", ".list", ".view", ".export")):
        return Role.VIEWER
    return Role.EDITOR


def _manager_default(key: str) -> Role:
    if key.startswith("system."):
        return Role.ADMIN
    if any(key.endswith(s) for s in (".read", ".list", ".view", ".export")):
        return Role.VIEWER
    if any(key.endswith(s) for s in (".create", ".update", ".import")):
        return Role.EDITOR
    return Role.MANAGER


PRESETS: dict[str, "callable"] = {
    "viewer-default": _viewer_default,
    "editor-default": _editor_default,
    "manager-default": _manager_default,
}


def register_field_role_permissions() -> None:
    """Register the field-worker surface permission set.

    DESIGN-STAGE STUB — intentionally empty until the pilot
    ``/api/v1/field/*`` router lands. See
    ``docs/architecture/FIELD_WORKER_MOBILE_DESIGN.md`` §4 for the
    full permission matrix the pilot will fill in.

    TODO (pilot, Daily Diary surface):
      * ``daily_diary.read``           → FIELD_WORKER (own day only,
        scope enforced at service layer via
        ``oe_field_module_grant``)
      * ``daily_diary.create``         → FIELD_WORKER
      * ``daily_diary.update``         → FIELD_WORKER (own entries
        <24 h; foreman-and-above for others)
      * ``daily_diary.upload_photo``   → FIELD_WORKER
      * ``daily_diary.fetch_weather``  → FIELD_WORKER
      * ``daily_diary.close``          → SITE_FOREMAN (sign-off)
      * ``daily_diary.sign``           → MANAGER (unchanged)

    TODO (phase 2 — design-doc §4.2):
      * ``hse_advanced.report_incident`` → FIELD_WORKER
      * ``ncr.flag``                     → FIELD_WORKER
      * ``inspections.create``           → SITE_INSPECTOR
      * ``punchlist.update_own``         → FIELD_WORKER
      * ``equipment.log_usage``          → FIELD_WORKER

    Until those permissions are registered here, the three field
    roles can sign in (the ``Role`` enum members exist) but every
    permission check returns False — by design.
    """
    # Intentionally empty. See module docstring above.
    return


def register_core_permissions() -> None:
    """Register permissions for core system features."""
    permission_registry.register_module_permissions(
        "system",
        {
            "system.settings.read": Role.MANAGER,
            "system.settings.write": Role.ADMIN,
            "system.modules.list": Role.VIEWER,
            "system.modules.install": Role.ADMIN,
            "system.modules.uninstall": Role.ADMIN,
            "system.modules.enable": Role.ADMIN,
            "system.modules.disable": Role.ADMIN,
            "system.hooks.list": Role.ADMIN,
            "system.validation_rules.list": Role.VIEWER,
            # Audit log + viewer (audit_router.py + future admin UI).
            # Without these, `RequirePermission("audit.view")` resolved to an
            # unknown permission and fell through to the ADMIN-role bypass —
            # technically safe but the gate was effectively ADMIN-only by
            # accident, and "audit.delete" was completely unreachable.
            "audit.view": Role.MANAGER,
            "audit.delete": Role.ADMIN,
            # Epic H §H9 — GDPR right-to-erasure on activity-log rows.
            # ADMIN-only by design: a redact mutates compliance records.
            "audit.redact": Role.ADMIN,
        },
    )
