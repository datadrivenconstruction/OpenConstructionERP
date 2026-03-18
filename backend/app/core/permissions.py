"""RBAC permission engine.

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
    """Built-in roles with hierarchical permissions."""

    ADMIN = "admin"  # Full access to everything
    MANAGER = "manager"  # Project management, team management
    EDITOR = "editor"  # Create and modify content
    VIEWER = "viewer"  # Read-only access


# Role hierarchy: higher roles inherit all permissions of lower roles
ROLE_HIERARCHY: dict[Role, int] = {
    Role.VIEWER: 0,
    Role.EDITOR: 1,
    Role.MANAGER: 2,
    Role.ADMIN: 3,
}


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
        """
        if isinstance(role, str):
            try:
                role = Role(role)
            except ValueError:
                return False

        # Admin bypasses all checks
        if role == Role.ADMIN:
            return True

        min_role = self._permissions.get(permission)
        if min_role is None:
            # Unknown permission — deny by default
            logger.warning("Unknown permission checked: %s", permission)
            return False

        return ROLE_HIERARCHY.get(role, -1) >= ROLE_HIERARCHY.get(min_role, 999)

    def get_role_permissions(self, role: Role | str) -> list[str]:
        """Get all permissions available to a role."""
        if isinstance(role, str):
            try:
                role = Role(role)
            except ValueError:
                return []

        if role == Role.ADMIN:
            return list(self._permissions.keys())

        return [
            perm
            for perm, min_role in self._permissions.items()
            if ROLE_HIERARCHY.get(role, -1) >= ROLE_HIERARCHY.get(min_role, 999)
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


# Global singleton
permission_registry = PermissionRegistry()


def register_core_permissions() -> None:
    """Register permissions for core system features."""
    permission_registry.register_module_permissions(
        "system",
        {
            "system.modules.list": Role.VIEWER,
            "system.modules.install": Role.ADMIN,
            "system.modules.uninstall": Role.ADMIN,
            "system.validation_rules.list": Role.VIEWER,
            "system.hooks.list": Role.ADMIN,
            "system.settings.read": Role.MANAGER,
            "system.settings.write": Role.ADMIN,
        },
    )
