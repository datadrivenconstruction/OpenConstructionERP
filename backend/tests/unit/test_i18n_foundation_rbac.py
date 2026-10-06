# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Seven writes on global reference tables used to authenticate and stop there.

``POST``/``PATCH``/``DELETE`` on exchange rates, work calendars and tax
configurations each declared a ``CurrentUserId`` it underscore-prefixed and
never read, and carried no permission. Being logged in was the whole gate, so
any account of any role could rewrite the VAT rate and the currency conversion
that every tenant's estimates and invoices are computed from. The three tables
have no tenant, owner or project column, so there was no ownership check
underneath to fall back on either.

Two things have to be true for the fix to hold, and each is tested separately
because they fail independently:

1. The keys are REGISTERED. ``RequirePermission`` returns False for a key
   nobody registered, and admin short-circuits above that check, so a
   misspelled key produces a route that behaves as admin-only and that no
   admin-authenticated test can tell from a correct one. That is the
   post-mortem in ``app/core/module_router.py:44-49``, and it is why the
   assertions below use a NON-admin role: ``role_has_permission(Role.ADMIN,
   anything)`` is True by bypass and can never discriminate.
2. The routes ASK for them. Registration alone would pass every check in
   part 1 while the routes stayed open.
"""

from __future__ import annotations

import pytest
from fastapi.routing import APIRoute

from app.core.permissions import Role, permission_registry
from app.modules.i18n_foundation.permissions import register_i18n_foundation_permissions

# (method, path, expected permission key) for every write in the module.
WRITE_ROUTES: tuple[tuple[str, str, str], ...] = (
    ("POST", "/exchange-rates/", "i18n_foundation.exchange_rates.create"),
    ("PATCH", "/exchange-rates/{rate_id}", "i18n_foundation.exchange_rates.update"),
    ("DELETE", "/exchange-rates/{rate_id}", "i18n_foundation.exchange_rates.delete"),
    ("POST", "/work-calendars/", "i18n_foundation.work_calendars.create"),
    ("PATCH", "/work-calendars/{calendar_id}", "i18n_foundation.work_calendars.update"),
    ("POST", "/tax-configs/", "i18n_foundation.tax_configs.create"),
    ("PATCH", "/tax-configs/{config_id}", "i18n_foundation.tax_configs.update"),
    # The reference data update. The preview is a read, gated anyway because it
    # is the first half of an install-wide write; see the router.
    ("GET", "/reference-data/updates/", "i18n_foundation.reference_data.preview"),
    ("POST", "/reference-data/updates/apply/", "i18n_foundation.reference_data.apply"),
)

WRITE_KEYS: tuple[str, ...] = tuple(key for _, _, key in WRITE_ROUTES)


@pytest.fixture(autouse=True)
def _registered() -> None:
    """The loader runs this through ``on_startup``; a unit test has to ask."""
    register_i18n_foundation_permissions()


class TestPermissionsAreRegistered:
    """Part 1 - the keys exist in the registry, at ADMIN."""

    @pytest.mark.parametrize("key", WRITE_KEYS)
    def test_key_is_registered_at_admin(self, key: str) -> None:
        # get_min_role returns None for a key nothing registered, so this
        # assertion fails on an unknown key rather than quietly passing.
        assert permission_registry.get_min_role(key) == Role.ADMIN

    @pytest.mark.parametrize("key", WRITE_KEYS)
    def test_key_can_be_delegated(self, key: str) -> None:
        """``set_min_role`` raises KeyError on an unregistered permission.

        This is the cost the post-mortem calls the quiet one: a route gated on
        an unknown key can never be delegated through the admin permission
        matrix, no matter what the matrix says. Restores ADMIN afterwards.
        """
        previous = permission_registry.set_min_role(key, Role.MANAGER)
        assert previous == Role.ADMIN
        permission_registry.set_min_role(key, Role.ADMIN)

    @pytest.mark.parametrize("key", WRITE_KEYS)
    def test_a_non_admin_is_refused(self, key: str) -> None:
        """The point of the fix: authentication was never the missing piece.

        MANAGER is authenticated, and is the highest role below admin, so a
        refusal here is a refusal for every non-admin role.
        """
        assert permission_registry.role_has_permission(Role.MANAGER, key) is False
        assert permission_registry.role_has_permission(Role.EDITOR, key) is False
        assert permission_registry.role_has_permission(Role.VIEWER, key) is False

    @pytest.mark.parametrize("key", WRITE_KEYS)
    def test_an_admin_is_allowed(self, key: str) -> None:
        assert permission_registry.role_has_permission(Role.ADMIN, key) is True

    def test_the_harmless_fetch_is_not_stricter_than_the_writes(self) -> None:
        """``fetch-ecb`` only pulls published ECB data and was the ONLY route
        here that asked for a permission. It stays ADMIN; the point is that the
        destructive routes are no longer looser than it."""
        assert permission_registry.get_min_role("i18n_foundation.exchange_rates.fetch") == Role.ADMIN


class TestRoutesAskForThem:
    """Part 2 - each write route actually carries its key."""

    @staticmethod
    def _permissions_on(method: str, path: str) -> set[str | None]:
        from app.modules.i18n_foundation import router as i18n_router

        route = next(
            r for r in i18n_router.router.routes if isinstance(r, APIRoute) and r.path == path and method in r.methods
        )
        return {getattr(dep.call, "permission", None) for dep in route.dependant.dependencies}

    @pytest.mark.parametrize(("method", "path", "key"), WRITE_ROUTES)
    def test_route_carries_its_permission(self, method: str, path: str, key: str) -> None:
        perms = self._permissions_on(method, path)
        assert key in perms, f"{method} {path} is gated by authentication only; saw {perms}"

    def test_the_reads_stay_open(self) -> None:
        """These three tables hold global reference data - currencies, public
        holidays, VAT rates - with no tenant column, so nothing tenant-scoped
        can leak through a read. Gating them would break the login page, which
        needs locale data before anyone has authenticated."""
        for path in ("/exchange-rates/", "/tax-configs/", "/work-calendars/"):
            named = {p for p in self._permissions_on("GET", path) if p}
            assert not named, f"GET {path} picked up a permission gate: {named}"
