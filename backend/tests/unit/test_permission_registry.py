# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Taking a module's permissions back out of the registry.

Registering is what every module does at startup and it has always worked. The
reverse direction only became reachable when modules started being installed
and removed while the server runs: a module that is gone must not leave
permissions behind that the admin matrix still offers and no endpoint any
longer enforces.

The registry is a process-global singleton, so each test builds its own.
"""

from __future__ import annotations

import pytest

from app.core.permissions import PermissionRegistry, Role


@pytest.fixture
def registry() -> PermissionRegistry:
    """A registry of this test's own, with nothing else's permissions in it."""
    return PermissionRegistry()


class TestUnregisteringAModule:
    def test_the_permissions_stop_being_granted(self, registry: PermissionRegistry) -> None:
        registry.register_module_permissions("site_diary", {"site_diary.read": Role.VIEWER})
        assert registry.role_has_permission(Role.VIEWER, "site_diary.read")

        registry.unregister_module_permissions("site_diary")

        assert not registry.role_has_permission(Role.VIEWER, "site_diary.read")
        assert not registry.has("site_diary.read")

    def test_it_reports_what_it_removed(self, registry: PermissionRegistry) -> None:
        registry.register_module_permissions(
            "site_diary",
            {"site_diary.read": Role.VIEWER, "site_diary.write": Role.EDITOR},
        )
        assert sorted(registry.unregister_module_permissions("site_diary")) == [
            "site_diary.read",
            "site_diary.write",
        ]

    def test_the_module_stops_being_listed(self, registry: PermissionRegistry) -> None:
        """The admin matrix is built from this list, so a removed module has to leave it."""
        registry.register_module_permissions("site_diary", {"site_diary.read": Role.VIEWER})
        registry.unregister_module_permissions("site_diary")
        assert "site_diary" not in registry.list_modules()

    def test_another_module_keeps_everything(self, registry: PermissionRegistry) -> None:
        registry.register_module_permissions("site_diary", {"site_diary.read": Role.VIEWER})
        registry.register_module_permissions("boq", {"boq.read": Role.VIEWER, "boq.export": Role.EDITOR})

        registry.unregister_module_permissions("site_diary")

        assert registry.has("boq.read")
        assert registry.has("boq.export")
        assert registry.list_modules()["boq"] == ["boq.read", "boq.export"]

    def test_a_module_that_was_never_registered(self, registry: PermissionRegistry) -> None:
        """Uninstalling a module that never got as far as registering is not an error."""
        assert registry.unregister_module_permissions("never_there") == []

    def test_a_permission_two_modules_share_survives(self, registry: PermissionRegistry) -> None:
        """One key, two owners: removing one owner must not disarm the other.

        Nothing ships like this today, but the registry is a flat dictionary and
        a generated module can pick any key it likes, including one already in
        use. Removing the entry outright would leave the surviving module's
        endpoint checking a permission the registry no longer knows, and an
        unknown permission is denied to everyone below admin.
        """
        registry.register_module_permissions("site_diary", {"reports.read": Role.VIEWER})
        registry.register_module_permissions("reports", {"reports.read": Role.VIEWER})

        removed = registry.unregister_module_permissions("site_diary")

        assert removed == ["reports.read"], "it should still say what it was asked to remove"
        assert registry.role_has_permission(Role.VIEWER, "reports.read"), "the other module lost its permission"

    def test_registering_again_afterwards_is_a_clean_slate(self, registry: PermissionRegistry) -> None:
        """A module reinstalled with fewer permissions must not keep the old ones.

        This is the case that makes removal necessary rather than tidy: the
        builder can reinstall the same key from a different spec.
        """
        registry.register_module_permissions(
            "site_diary",
            {"site_diary.read": Role.VIEWER, "site_diary.approve": Role.MANAGER},
        )
        registry.unregister_module_permissions("site_diary")
        registry.register_module_permissions("site_diary", {"site_diary.read": Role.VIEWER})

        assert registry.has("site_diary.read")
        assert not registry.has("site_diary.approve")
