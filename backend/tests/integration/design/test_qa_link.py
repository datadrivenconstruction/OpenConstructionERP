"""QA (adversarial): code/token/lock security of the design module. Written against contract s7/s8."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from .conftest import LINK, make_project, make_user

pytestmark = pytest.mark.asyncio
BASE = "/api/v1/design"


async def _code(client, headers, pid, **extra):
    r = await client.post(
        f"{BASE}/link/code", json={"project_id": str(pid), "action": "new"}, headers={**headers, **LINK, **extra}
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _token(client, headers, pid) -> str:
    x = await client.post(
        f"{BASE}/link/exchange", json={"code": (await _code(client, headers, pid))["code"]}, headers=LINK
    )
    assert x.status_code == 200, x.text
    return x.json()["token"]


async def _db(stmt):
    from app.database import async_session_factory

    async with async_session_factory() as s:
        await s.execute(stmt)
        await s.commit()


def _bearer(tok):
    return {"Authorization": f"Bearer {tok}", **LINK}


def _aware(iso: str) -> datetime:
    d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=UTC)


async def test_code_lifetime_at_most_five_minutes(client):
    uid, h = await make_user(client)
    link = await _code(client, h, await make_project(uid))
    assert 240 < (_aware(link["expires_at"]) - datetime.now(UTC)).total_seconds() <= 300
    assert len(link["code"]) >= 32


async def test_expired_code_is_gone(client):
    from sqlalchemy import update

    from app.modules.design.auth import digest
    from app.modules.design.models import DesignLinkCode

    uid, h = await make_user(client)
    code = (await _code(client, h, await make_project(uid)))["code"]
    await _db(
        update(DesignLinkCode)
        .where(DesignLinkCode.code_hash == digest(code))
        .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    assert (await client.post(f"{BASE}/link/exchange", json={"code": code}, headers=LINK)).status_code == 410


async def test_parallel_exchange_yields_one_token(client):
    uid, h = await make_user(client)
    code = (await _code(client, h, await make_project(uid)))["code"]
    rs = await asyncio.gather(
        *[client.post(f"{BASE}/link/exchange", json={"code": code}, headers=LINK) for _ in range(8)]
    )
    assert [r.status_code for r in rs].count(200) == 1


async def test_token_and_code_stored_only_as_hash(client):
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.design.models import DesignLinkCode, DesignLinkToken

    uid, h = await make_user(client)
    link = await _code(client, h, await make_project(uid))
    tok = (await client.post(f"{BASE}/link/exchange", json={"code": link["code"]}, headers=LINK)).json()["token"]
    async with async_session_factory() as s:
        for col in (DesignLinkCode.code_hash, DesignLinkToken.token_hash):
            vals = (await s.execute(select(col))).scalars().all()
            assert link["code"] not in vals and tok not in vals


async def test_short_or_foreign_codes_rejected(client):
    for code in ("x" * 31, "x" * 129):
        assert (await client.post(f"{BASE}/link/exchange", json={"code": code}, headers=LINK)).status_code == 422
    assert (await client.post(f"{BASE}/link/exchange", json={"code": "A" * 43}, headers=LINK)).status_code == 410


async def test_exchange_is_rate_limited(client):
    # 256-bit codes make guessing infeasible, but an unauthenticated endpoint should still throttle.
    rs = [
        await client.post(f"{BASE}/link/exchange", json={"code": uuid.uuid4().hex + uuid.uuid4().hex}, headers=LINK)
        for _ in range(40)
    ]
    assert any(r.status_code == 429 for r in rs)


async def test_expired_token_rejected(client):
    from sqlalchemy import update

    from app.modules.design.auth import digest
    from app.modules.design.models import DesignLinkToken

    uid, h = await make_user(client)
    pid = await make_project(uid)
    tok = await _token(client, h, pid)
    await _db(
        update(DesignLinkToken)
        .where(DesignLinkToken.token_hash == digest(tok))
        .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    assert (await client.get(f"{BASE}/projects/{pid}/context", headers=_bearer(tok))).status_code == 401


async def test_revoked_token_rejected(client):
    from sqlalchemy import update

    from app.modules.design.auth import digest
    from app.modules.design.models import DesignLinkToken

    uid, h = await make_user(client)
    pid = await make_project(uid)
    tok = await _token(client, h, pid)
    await _db(
        update(DesignLinkToken).where(DesignLinkToken.token_hash == digest(tok)).values(revoked_at=datetime.now(UTC))
    )
    assert (await client.get(f"{BASE}/projects/{pid}/context", headers=_bearer(tok))).status_code == 401


async def test_link_token_cannot_mint_codes_or_touch_other_projects(client):
    uid, h = await make_user(client)
    p1, p2 = await make_project(uid), await make_project(uid, name="Other")
    tok = await _token(client, h, p1)
    for pid in (p1, p2):  # a stolen editor token must not mint further codes
        r = await client.post(f"{BASE}/link/code", json={"project_id": str(pid), "action": "new"}, headers=_bearer(tok))
        assert r.status_code in (401, 403), (pid, r.status_code)
    for method in ("post", "delete"):
        r = await getattr(client, method)(f"{BASE}/projects/{p2}/lock", headers=_bearer(tok))
        assert r.status_code == 404


async def test_token_dies_when_user_loses_project(client):
    from sqlalchemy import update

    from app.modules.projects.models import Project

    owner, h = await make_user(client)
    other, _ = await make_user(client)
    pid = await make_project(owner)
    tok = await _token(client, h, pid)
    await _db(update(Project).where(Project.id == pid).values(owner_id=other))
    assert (await client.get(f"{BASE}/projects/{pid}/context", headers=_bearer(tok))).status_code == 404


async def test_token_dies_when_user_deactivated(client):
    from sqlalchemy import update

    from app.modules.users.models import User

    owner, h = await make_user(client)
    pid = await make_project(owner)
    tok = await _token(client, h, pid)
    await _db(update(User).where(User.id == owner).values(is_active=False))
    assert (await client.get(f"{BASE}/projects/{pid}/context", headers=_bearer(tok))).status_code in (401, 403)


async def test_every_response_carries_version_header(client):
    # contract s8: "Every request and response carries X-DDC-Link: 1" (only GET / does today).
    uid, h = await make_user(client)
    pid = await make_project(uid)
    tok = await _token(client, h, pid)
    r = await client.get(f"{BASE}/projects/{pid}/context", headers=_bearer(tok))
    assert r.headers.get("x-ddc-link") == "1"
    assert (await client.post(f"{BASE}/projects/{pid}/lock", headers=_bearer(tok))).headers.get("x-ddc-link") == "1"
    assert (await client.get(f"{BASE}/", headers={"X-DDC-Link": "9"})).headers.get("x-ddc-link") == "1"


@pytest.mark.parametrize("value", ["+1", "01", "1.0", "0"])
async def test_version_header_must_be_canonical(client, value):
    assert (await client.get(f"{BASE}/", headers={"X-DDC-Link": value})).status_code == 426


async def test_erp_url_not_taken_from_host_header(client):
    # A forged Host would point the .ddclink (and the one-time code) at another server.
    uid, h = await make_user(client)
    link = await _code(client, h, await make_project(uid), Host="evil.example")
    assert "evil.example" not in link["erp_url"]


async def test_heartbeat_without_lock_does_not_acquire(client):
    # contract s8: lost heartbeat => "lock lost" in the editor; silently re-acquiring hides it.
    uid, h = await make_user(client)
    pid = await make_project(uid)
    tok = await _token(client, h, pid)
    hb = await client.post(f"{BASE}/projects/{pid}/lock/heartbeat", headers=_bearer(tok))
    assert hb.status_code in (404, 409, 410), hb.text
    ctx = (await client.get(f"{BASE}/projects/{pid}/context", headers=_bearer(tok))).json()
    assert ctx["lock"] is None


async def test_heartbeat_after_expiry_reports_lock_lost(client):
    from sqlalchemy import update

    from app.modules.collaboration_locks.models import CollabLock

    uid, h = await make_user(client)
    pid = await make_project(uid)
    tok = await _token(client, h, pid)
    assert (await client.post(f"{BASE}/projects/{pid}/lock", headers=_bearer(tok))).status_code == 200
    await _db(
        update(CollabLock)
        .where(CollabLock.entity_id == pid)
        .values(expires_at=datetime.now(UTC) - timedelta(seconds=5))
    )
    hb = await client.post(f"{BASE}/projects/{pid}/lock/heartbeat", headers=_bearer(tok))
    assert hb.status_code in (404, 409, 410), hb.text


async def test_expired_lock_is_takeable_and_ttl_is_capped(client):
    from sqlalchemy import update

    from app.modules.collaboration_locks.models import CollabLock

    a, ha = await make_user(client)
    _, hb_ = await make_user(client, role="admin")
    pid = await make_project(a)
    tok = await _token(client, ha, pid)
    r = await client.post(f"{BASE}/projects/{pid}/lock", headers=_bearer(tok))
    assert (_aware(r.json()["expires_at"]) - datetime.now(UTC)).total_seconds() <= 600
    await _db(
        update(CollabLock)
        .where(CollabLock.entity_id == pid)
        .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    assert (await client.post(f"{BASE}/projects/{pid}/lock", headers=hb_)).status_code == 200


async def test_read_only_role_cannot_publish(client):
    uid, h = await make_user(client, role="viewer")
    pid = await make_project(uid)
    tok = await _token(client, h, pid)
    ctx = (await client.get(f"{BASE}/projects/{pid}/context", headers=_bearer(tok))).json()
    assert ctx["permissions"]["can_publish"] is False
    assert (await client.post(f"{BASE}/projects/{pid}/lock", headers=_bearer(tok))).status_code == 403
