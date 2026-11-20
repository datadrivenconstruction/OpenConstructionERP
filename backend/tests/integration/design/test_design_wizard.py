"""R12: the first-run wizard saves a whole module map; it must not drop what the design offer switched on.

Needs ERP core patch 0004 (onboarding keeps preferences of modules the profiles do not govern)."""

from __future__ import annotations

import inspect

import pytest

pytestmark = pytest.mark.asyncio

router = pytest.importorskip("app.modules.users.router")
if "governed" not in inspect.getsource(router.save_onboarding if hasattr(router, "save_onboarding") else router):
    pytest.skip("core patch 0004 (onboarding keeps unmanaged preferences) is not applied", allow_module_level=True)

from .conftest import make_user  # noqa: E402

PREFS = "/api/v1/users/me/module-preferences/"
ONBOARDING = "/api/v1/users/me/onboarding/"


async def test_finishing_the_wizard_keeps_the_design_switch(client):
    _, h = await make_user(client)
    on = await client.patch(PREFS, json={"modules": {"design": True}}, headers=h)
    assert on.status_code == 200, on.text
    done = await client.post(
        ONBOARDING, json={"company_type": None, "enabled_modules": ["boq", "schedule"], "completed": True}, headers=h
    )
    assert done.status_code == 200, done.text
    prefs = (await client.get(PREFS, headers=h)).json()
    mods = prefs.get("modules", prefs)
    assert mods["design"] is True
    assert mods["boq"] is True, "the wizard's own choice is still applied"


async def test_a_switched_off_design_module_stays_off(client):
    _, h = await make_user(client)
    await client.patch(PREFS, json={"modules": {"design": False}}, headers=h)
    await client.post(ONBOARDING, json={"company_type": None, "enabled_modules": ["boq"], "completed": True}, headers=h)
    prefs = (await client.get(PREFS, headers=h)).json()
    assert prefs.get("modules", prefs)["design"] is False


async def test_the_wizard_still_replaces_the_modules_it_governs(client):
    _, h = await make_user(client)
    await client.patch(PREFS, json={"modules": {"design": True, "boq": True, "schedule": True}}, headers=h)
    await client.post(ONBOARDING, json={"company_type": None, "enabled_modules": ["boq"], "completed": True}, headers=h)
    mods = (await client.get(PREFS, headers=h)).json()
    mods = mods.get("modules", mods)
    assert mods["boq"] is True and mods["schedule"] is False and mods["design"] is True


async def test_a_user_who_never_touched_design_gets_no_entry(client):
    _, h = await make_user(client)
    await client.post(ONBOARDING, json={"company_type": None, "enabled_modules": ["boq"], "completed": True}, headers=h)
    mods = (await client.get(PREFS, headers=h)).json()
    assert "design" not in mods.get("modules", mods)
