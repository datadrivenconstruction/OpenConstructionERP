"""Audit /timeline/ is scoped to the caller's tenant."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from app.core import tenant_scope
from app.core.audit_log import log_activity
from app.core.audit_router import get_timeline
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        yield s


async def _timeline(session, tenant_id):
    return await get_timeline(
        session=session,
        _user_id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        _perm=None,
        entity_type=None,
        entity_id=None,
        actor_id=None,
        module=None,
        limit=100,
        offset=0,
    )


@pytest.mark.asyncio
async def test_timeline_hides_other_tenants(session, monkeypatch) -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    for tid, eid in ((a, "a-row"), (b, "b-row"), (None, "system-row")):
        await log_activity(
            session, module="t", entity_type="x", entity_id=eid, action="create", actor_id=None, tenant_id=tid
        )
    await session.flush()

    async def not_admin(_s, _u):
        return False

    monkeypatch.setattr(tenant_scope, "_is_admin", not_admin)
    seen = {r["entity_id"] for r in await _timeline(session, str(a))}
    assert seen == {"a-row", "system-row"}


@pytest.mark.asyncio
async def test_timeline_admin_sees_all_tenants(session, monkeypatch) -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    for tid, eid in ((a, "a-row"), (b, "b-row")):
        await log_activity(
            session, module="t", entity_type="x", entity_id=eid, action="create", actor_id=None, tenant_id=tid
        )
    await session.flush()

    async def admin(_s, _u):
        return True

    monkeypatch.setattr(tenant_scope, "_is_admin", admin)
    seen = {r["entity_id"] for r in await _timeline(session, str(a))}
    assert {"a-row", "b-row"} <= seen
