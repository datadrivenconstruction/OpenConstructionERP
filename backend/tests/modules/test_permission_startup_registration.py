# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A real application boot is what has to register these permission keys.

Both modules covered here gate a route on a permission key that only exists
because the package's ``on_startup`` hook put it there. The module loader
auto-imports ``router``, ``models``, ``hooks``, ``events``, ``validators`` and
``pipeline_nodes``; it never imports ``permissions.py``. The single path from a
``permissions.py`` to a running registry is ``__init__.on_startup``, which
``module_loader.py:352-355`` reaches with ``getattr(package, "on_startup")``.

The failure this closes is silent, and it is the one the whole fix exists to
prevent. ``RequirePermission`` denies a key nobody registered, and the admin
role short-circuits above that check, so an unregistered key produces a route
that behaves exactly like a correct admin-only route. Every test that
authenticates as an admin stays green. The route is simply undelegatable
forever, because ``set_min_role`` raises ``KeyError`` on a key the registry
does not know, so the admin permission matrix cannot hand it to anyone.

Unregistering first is what makes the answer mean anything. Both registration
functions are importable, and any test process that touched the module has
almost certainly run them as a side effect. Asserting the keys are present
after an import proves the function works; it says nothing about whether the
application calls it. So this empties both modules out of the registry, asserts
the emptying actually took, boots the app the way production boots it, and only
then asks what came back.

One file and one boot for two modules on purpose: the fixture is the expensive
part, and the assertion is the same mechanism in both cases.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from app.core.permissions import Role, permission_registry

# The eight keys that exist only if on_startup ran. Seven writes on global
# reference tables plus the Qdrant install, which writes a service binary to
# the host.
I18N_KEYS: tuple[str, ...] = (
    "i18n_foundation.exchange_rates.fetch",
    "i18n_foundation.exchange_rates.create",
    "i18n_foundation.exchange_rates.update",
    "i18n_foundation.exchange_rates.delete",
    "i18n_foundation.work_calendars.create",
    "i18n_foundation.work_calendars.update",
    "i18n_foundation.tax_configs.create",
    "i18n_foundation.tax_configs.update",
)

MATCH_KEYS: tuple[str, ...] = ("match_elements.qdrant.install",)

ALL_KEYS: tuple[str, ...] = I18N_KEYS + MATCH_KEYS


@pytest_asyncio.fixture(scope="module")
async def booted_with_the_keys_removed() -> AsyncIterator[None]:
    """Drop both modules from the registry, boot the real app, hand back.

    ``unregister_module_permissions`` removes a key only when no other module
    still claims it, which is the behaviour wanted here: if some other module
    were also registering these keys, the emptying assertion below would fail
    and say so rather than letting the boot take credit for someone else's
    registration.
    """
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    permission_registry.unregister_module_permissions("i18n_foundation")
    permission_registry.unregister_module_permissions("match_elements")

    still_present = [key for key in ALL_KEYS if permission_registry.get_min_role(key) is not None]
    assert not still_present, (
        f"these keys survived unregister_module_permissions, so a boot that finds them proves nothing: {still_present}"
    )

    app = create_app()
    async with app.router.lifespan_context(app):
        yield


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ALL_KEYS)
async def test_a_real_boot_registers_the_key(booted_with_the_keys_removed: None, key: str) -> None:
    """``get_min_role`` returns None for an unknown key, so this discriminates.

    ``role_has_permission(Role.ADMIN, ...)`` never could: admin is allowed by
    bypass, so it answers True for a key that was never registered.
    """
    assert permission_registry.get_min_role(key) == Role.ADMIN, (
        f"a real application boot left {key} unregistered; the route gated on it is admin-only by accident"
    )


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
@pytest.mark.parametrize("key", ALL_KEYS)
async def test_a_registered_key_can_be_delegated(booted_with_the_keys_removed: None, key: str) -> None:
    """The quiet half of the defect: an unknown key cannot be granted to anyone.

    ``set_min_role`` raises ``KeyError`` on a key the registry does not hold, so
    a route gated on a typo can never be delegated through the admin matrix no
    matter what that matrix says. Restores ADMIN afterwards.
    """
    previous = permission_registry.set_min_role(key, Role.MANAGER)
    try:
        assert previous == Role.ADMIN
    finally:
        permission_registry.set_min_role(key, Role.ADMIN)


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_a_non_admin_is_refused_after_a_real_boot(booted_with_the_keys_removed: None) -> None:
    """Authentication was never the missing piece on any of these routes.

    MANAGER is the highest role below admin, so a refusal here is a refusal for
    every non-admin role.
    """
    for key in ALL_KEYS:
        assert permission_registry.role_has_permission(Role.MANAGER, key) is False, (
            f"{key} is reachable by a non-admin after a real boot"
        )
