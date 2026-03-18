"""Tests for the RBAC permission engine."""

import pytest

from app.core.permissions import (
    ROLE_HIERARCHY,
    PermissionRegistry,
    Role,
    register_core_permissions,
)


# ── Role enum tests ──────────────────────────────────────────────────────────


class TestRole:
    def test_role_values(self):
        assert Role.ADMIN.value == "admin"
        assert Role.MANAGER.value == "manager"
        assert Role.EDITOR.value == "editor"
        assert Role.VIEWER.value == "viewer"

    def test_role_from_string(self):
        assert Role("admin") == Role.ADMIN
        assert Role("viewer") == Role.VIEWER

    def test_role_invalid_string(self):
        with pytest.raises(ValueError):
            Role("superuser")

    def test_role_is_string_subclass(self):
        """Role(str, Enum) values should be usable as plain strings."""
        assert isinstance(Role.ADMIN, str)
        assert Role.EDITOR == "editor"


# ── Role hierarchy tests ─────────────────────────────────────────────────────


class TestRoleHierarchy:
    def test_hierarchy_ordering(self):
        assert ROLE_HIERARCHY[Role.VIEWER] < ROLE_HIERARCHY[Role.EDITOR]
        assert ROLE_HIERARCHY[Role.EDITOR] < ROLE_HIERARCHY[Role.MANAGER]
        assert ROLE_HIERARCHY[Role.MANAGER] < ROLE_HIERARCHY[Role.ADMIN]

    def test_viewer_is_lowest(self):
        assert ROLE_HIERARCHY[Role.VIEWER] == 0

    def test_admin_is_highest(self):
        for role, level in ROLE_HIERARCHY.items():
            assert ROLE_HIERARCHY[Role.ADMIN] >= level

    def test_all_roles_have_hierarchy_level(self):
        for role in Role:
            assert role in ROLE_HIERARCHY


# ── PermissionRegistry tests ─────────────────────────────────────────────────


class TestPermissionRegistry:
    @pytest.fixture
    def registry(self):
        reg = PermissionRegistry()
        yield reg
        reg.clear()

    # ── Registration ──────────────────────────────────────────────────

    def test_register_single_permission(self, registry):
        registry.register("projects.create", Role.EDITOR)
        assert "projects.create" in registry.list_all()

    def test_register_default_min_role_is_editor(self, registry):
        registry.register("projects.read")
        all_perms = registry.list_all()
        assert all_perms["projects.read"] == "editor"

    def test_register_module_permissions(self, registry):
        registry.register_module_permissions(
            "projects",
            {
                "projects.create": Role.EDITOR,
                "projects.read": Role.VIEWER,
                "projects.update": Role.EDITOR,
                "projects.delete": Role.MANAGER,
            },
        )
        all_perms = registry.list_all()
        assert len(all_perms) == 4
        assert all_perms["projects.read"] == "viewer"
        assert all_perms["projects.delete"] == "manager"

    def test_register_module_permissions_tracked_by_module(self, registry):
        perms = {
            "boq.create": Role.EDITOR,
            "boq.read": Role.VIEWER,
            "boq.export": Role.EDITOR,
        }
        registry.register_module_permissions("boq", perms)
        modules = registry.list_modules()
        assert "boq" in modules
        assert set(modules["boq"]) == {"boq.create", "boq.read", "boq.export"}

    def test_register_multiple_modules(self, registry):
        registry.register_module_permissions("mod_a", {"mod_a.x": Role.VIEWER})
        registry.register_module_permissions("mod_b", {"mod_b.y": Role.EDITOR})
        modules = registry.list_modules()
        assert "mod_a" in modules
        assert "mod_b" in modules

    # ── Admin bypass ──────────────────────────────────────────────────

    def test_admin_has_all_registered_permissions(self, registry):
        registry.register_module_permissions(
            "projects",
            {
                "projects.create": Role.EDITOR,
                "projects.read": Role.VIEWER,
                "projects.delete": Role.ADMIN,
            },
        )
        assert registry.role_has_permission(Role.ADMIN, "projects.create")
        assert registry.role_has_permission(Role.ADMIN, "projects.read")
        assert registry.role_has_permission(Role.ADMIN, "projects.delete")

    def test_admin_has_even_unknown_permissions(self, registry):
        """Admin bypasses all checks, including for unregistered permissions."""
        assert registry.role_has_permission(Role.ADMIN, "totally.unknown.permission")

    def test_admin_string_role(self, registry):
        registry.register("projects.read", Role.VIEWER)
        assert registry.role_has_permission("admin", "projects.read")

    # ── Role-based checks ─────────────────────────────────────────────

    def test_viewer_has_viewer_permission(self, registry):
        registry.register("projects.read", Role.VIEWER)
        assert registry.role_has_permission(Role.VIEWER, "projects.read")

    def test_viewer_lacks_editor_permission(self, registry):
        registry.register("projects.create", Role.EDITOR)
        assert not registry.role_has_permission(Role.VIEWER, "projects.create")

    def test_editor_inherits_viewer_permissions(self, registry):
        registry.register("projects.read", Role.VIEWER)
        assert registry.role_has_permission(Role.EDITOR, "projects.read")

    def test_editor_has_editor_permission(self, registry):
        registry.register("projects.update", Role.EDITOR)
        assert registry.role_has_permission(Role.EDITOR, "projects.update")

    def test_editor_lacks_manager_permission(self, registry):
        registry.register("projects.manage_team", Role.MANAGER)
        assert not registry.role_has_permission(Role.EDITOR, "projects.manage_team")

    def test_manager_inherits_editor_and_viewer(self, registry):
        registry.register("projects.read", Role.VIEWER)
        registry.register("projects.create", Role.EDITOR)
        registry.register("projects.manage_team", Role.MANAGER)
        assert registry.role_has_permission(Role.MANAGER, "projects.read")
        assert registry.role_has_permission(Role.MANAGER, "projects.create")
        assert registry.role_has_permission(Role.MANAGER, "projects.manage_team")

    def test_manager_lacks_admin_permission(self, registry):
        registry.register("system.modules.install", Role.ADMIN)
        assert not registry.role_has_permission(Role.MANAGER, "system.modules.install")

    # ── Unknown permissions ───────────────────────────────────────────

    def test_unknown_permission_denied_for_viewer(self, registry):
        assert not registry.role_has_permission(Role.VIEWER, "nonexistent.perm")

    def test_unknown_permission_denied_for_editor(self, registry):
        assert not registry.role_has_permission(Role.EDITOR, "nonexistent.perm")

    def test_unknown_permission_denied_for_manager(self, registry):
        assert not registry.role_has_permission(Role.MANAGER, "nonexistent.perm")

    def test_unknown_permission_allowed_for_admin(self, registry):
        assert registry.role_has_permission(Role.ADMIN, "nonexistent.perm")

    # ── String role handling ──────────────────────────────────────────

    def test_string_role_valid(self, registry):
        registry.register("projects.read", Role.VIEWER)
        assert registry.role_has_permission("viewer", "projects.read")
        assert registry.role_has_permission("editor", "projects.read")

    def test_string_role_invalid_returns_false(self, registry):
        registry.register("projects.read", Role.VIEWER)
        assert not registry.role_has_permission("invalid_role", "projects.read")

    # ── get_role_permissions ──────────────────────────────────────────

    def test_get_role_permissions_viewer(self, registry):
        registry.register_module_permissions(
            "test",
            {
                "test.read": Role.VIEWER,
                "test.write": Role.EDITOR,
                "test.manage": Role.MANAGER,
                "test.admin": Role.ADMIN,
            },
        )
        viewer_perms = registry.get_role_permissions(Role.VIEWER)
        assert "test.read" in viewer_perms
        assert "test.write" not in viewer_perms
        assert "test.manage" not in viewer_perms
        assert "test.admin" not in viewer_perms

    def test_get_role_permissions_editor(self, registry):
        registry.register_module_permissions(
            "test",
            {
                "test.read": Role.VIEWER,
                "test.write": Role.EDITOR,
                "test.manage": Role.MANAGER,
                "test.admin": Role.ADMIN,
            },
        )
        editor_perms = registry.get_role_permissions(Role.EDITOR)
        assert "test.read" in editor_perms
        assert "test.write" in editor_perms
        assert "test.manage" not in editor_perms
        assert "test.admin" not in editor_perms

    def test_get_role_permissions_manager(self, registry):
        registry.register_module_permissions(
            "test",
            {
                "test.read": Role.VIEWER,
                "test.write": Role.EDITOR,
                "test.manage": Role.MANAGER,
                "test.admin": Role.ADMIN,
            },
        )
        manager_perms = registry.get_role_permissions(Role.MANAGER)
        assert "test.read" in manager_perms
        assert "test.write" in manager_perms
        assert "test.manage" in manager_perms
        assert "test.admin" not in manager_perms

    def test_get_role_permissions_admin_gets_all(self, registry):
        registry.register_module_permissions(
            "test",
            {
                "test.read": Role.VIEWER,
                "test.write": Role.EDITOR,
                "test.manage": Role.MANAGER,
                "test.admin": Role.ADMIN,
            },
        )
        admin_perms = registry.get_role_permissions(Role.ADMIN)
        assert set(admin_perms) == {"test.read", "test.write", "test.manage", "test.admin"}

    def test_get_role_permissions_string_role(self, registry):
        registry.register("data.read", Role.VIEWER)
        perms = registry.get_role_permissions("viewer")
        assert "data.read" in perms

    def test_get_role_permissions_invalid_role_returns_empty(self, registry):
        registry.register("data.read", Role.VIEWER)
        perms = registry.get_role_permissions("nonexistent")
        assert perms == []

    def test_get_role_permissions_empty_registry(self, registry):
        perms = registry.get_role_permissions(Role.ADMIN)
        assert perms == []

    # ── list_all and list_modules ─────────────────────────────────────

    def test_list_all_sorted(self, registry):
        registry.register("z_perm", Role.VIEWER)
        registry.register("a_perm", Role.EDITOR)
        all_perms = registry.list_all()
        keys = list(all_perms.keys())
        assert keys == sorted(keys)

    def test_list_all_contains_min_role_values(self, registry):
        registry.register("projects.read", Role.VIEWER)
        registry.register("projects.delete", Role.ADMIN)
        all_perms = registry.list_all()
        assert all_perms["projects.read"] == "viewer"
        assert all_perms["projects.delete"] == "admin"

    def test_list_modules_empty(self, registry):
        assert registry.list_modules() == {}

    # ── clear ─────────────────────────────────────────────────────────

    def test_clear_removes_permissions(self, registry):
        registry.register("perm.a", Role.VIEWER)
        registry.register_module_permissions("mod", {"mod.x": Role.EDITOR})
        registry.clear()
        assert registry.list_all() == {}
        assert registry.list_modules() == {}

    def test_clear_resets_role_permissions(self, registry):
        registry.register("perm.a", Role.VIEWER)
        registry.clear()
        assert registry.get_role_permissions(Role.VIEWER) == []
        # Admin still returns empty after clear (no permissions registered)
        assert registry.get_role_permissions(Role.ADMIN) == []


# ── register_core_permissions tests ──────────────────────────────────────────


class TestRegisterCorePermissions:
    def test_core_permissions_registered(self):
        """register_core_permissions populates the global singleton."""
        from app.core.permissions import permission_registry

        # Save state and clear
        original_perms = dict(permission_registry._permissions)
        original_modules = dict(permission_registry._module_permissions)
        permission_registry.clear()

        try:
            register_core_permissions()

            all_perms = permission_registry.list_all()
            assert "system.modules.list" in all_perms
            assert "system.modules.install" in all_perms
            assert "system.modules.uninstall" in all_perms
            assert "system.settings.read" in all_perms
            assert "system.settings.write" in all_perms
            assert "system.validation_rules.list" in all_perms
            assert "system.hooks.list" in all_perms

            # Check that module listing works
            modules = permission_registry.list_modules()
            assert "system" in modules

        finally:
            # Restore original state
            permission_registry.clear()
            permission_registry._permissions.update(original_perms)
            permission_registry._module_permissions.update(original_modules)

    def test_core_permission_levels(self):
        """Core permissions have correct minimum role levels."""
        from app.core.permissions import permission_registry

        original_perms = dict(permission_registry._permissions)
        original_modules = dict(permission_registry._module_permissions)
        permission_registry.clear()

        try:
            register_core_permissions()

            # Viewer-level permissions
            assert permission_registry.role_has_permission(Role.VIEWER, "system.modules.list")
            assert permission_registry.role_has_permission(
                Role.VIEWER, "system.validation_rules.list"
            )

            # Manager-level permissions
            assert not permission_registry.role_has_permission(Role.VIEWER, "system.settings.read")
            assert permission_registry.role_has_permission(Role.MANAGER, "system.settings.read")

            # Admin-only permissions
            assert not permission_registry.role_has_permission(
                Role.MANAGER, "system.modules.install"
            )
            assert not permission_registry.role_has_permission(
                Role.MANAGER, "system.settings.write"
            )
            assert permission_registry.role_has_permission(Role.ADMIN, "system.modules.install")
            assert permission_registry.role_has_permission(Role.ADMIN, "system.settings.write")

        finally:
            permission_registry.clear()
            permission_registry._permissions.update(original_perms)
            permission_registry._module_permissions.update(original_modules)
