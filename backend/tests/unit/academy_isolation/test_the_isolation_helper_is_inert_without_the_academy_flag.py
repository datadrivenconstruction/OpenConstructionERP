# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The academy isolation helper does nothing at all unless the flag is on.

A normal install must not change, so with the flag off every gate returns its
input untouched and never reaches the database: the tests pass ``None`` as the
session, which would raise on the first query. With the flag on, the parts that
need no database (a malformed id, the self-or-admin rule) refuse as specified.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator

import pytest
from fastapi import HTTPException

from app.config import get_settings
from app.core.academy_isolation import (
    USER_NOT_IN_PROJECT,
    academy_mode_enabled,
    assert_self_or_admin,
    assert_users_can_access_project,
    filter_users_to_project,
    limits_users_to_self,
)

pytestmark = pytest.mark.asyncio

ME = str(uuid.uuid4())
OTHER = str(uuid.uuid4())


@pytest.fixture
def academy(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[bool], None]]:
    def _set(on: bool) -> None:
        monkeypatch.delenv("ACADEMY_MODE", raising=False)
        monkeypatch.setenv("OE_ACADEMY_MODE", "true" if on else "false")
        get_settings.cache_clear()

    try:
        yield _set
    finally:
        monkeypatch.delenv("OE_ACADEMY_MODE", raising=False)
        get_settings.cache_clear()


async def test_the_flag_is_read_from_the_settings_on_each_call(academy) -> None:
    academy(True)
    assert academy_mode_enabled() is True
    academy(False)
    assert academy_mode_enabled() is False


async def test_academy_off_the_project_gates_never_touch_the_database(academy) -> None:
    academy(False)
    given = [OTHER, "not-a-uuid", None, uuid.UUID(ME)]

    await assert_users_can_access_project(None, uuid.uuid4(), given)  # type: ignore[arg-type]
    assert await filter_users_to_project(None, uuid.uuid4(), given) == given


@pytest.mark.tenant_isolation
async def test_academy_off_another_users_record_stays_readable(academy) -> None:
    academy(False)
    manager = {"sub": ME, "role": "manager"}

    assert limits_users_to_self(manager) is False
    await assert_self_or_admin(OTHER, manager)


@pytest.mark.tenant_isolation
async def test_academy_on_another_users_record_is_404_for_a_manager(academy) -> None:
    academy(True)
    manager = {"sub": ME, "role": "manager"}

    assert limits_users_to_self(manager) is True
    with pytest.raises(HTTPException) as caught:
        await assert_self_or_admin(OTHER, manager)
    assert caught.value.status_code == 404
    assert caught.value.detail == "User not found"


@pytest.mark.tenant_isolation
async def test_academy_on_self_and_admin_still_pass(academy) -> None:
    academy(True)

    await assert_self_or_admin(ME, {"sub": ME, "role": "manager"})
    await assert_self_or_admin(uuid.UUID(ME), {"sub": ME, "role": "viewer"})
    admin = {"sub": ME, "role": "admin"}
    assert limits_users_to_self(admin) is False
    await assert_self_or_admin(OTHER, admin)


@pytest.mark.tenant_isolation
async def test_academy_on_a_malformed_id_is_refused_like_an_outsider(academy) -> None:
    academy(True)

    with pytest.raises(HTTPException) as caught:
        await assert_users_can_access_project(None, uuid.uuid4(), ["not-a-uuid"])  # type: ignore[arg-type]
    assert caught.value.status_code == 422
    assert caught.value.detail["error"] == USER_NOT_IN_PROJECT
    # Naming nobody needs no lookup and passes.
    await assert_users_can_access_project(None, uuid.uuid4(), [None, "", "  "])  # type: ignore[arg-type]
    # Without a session there is nobody to keep.
    assert await filter_users_to_project(None, uuid.uuid4(), [OTHER]) == []
