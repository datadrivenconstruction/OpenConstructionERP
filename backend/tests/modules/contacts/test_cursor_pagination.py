"""Keyset (cursor) pagination of the contacts list.

Run:
    cd backend
    python -m pytest -q -x --no-header tests/modules/contacts/test_cursor_pagination.py
"""

import asyncio
import base64
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.database import async_session_factory
from app.main import create_app
from app.modules.contacts.models import Contact

pytestmark = pytest.mark.asyncio

URL = "/api/v1/contacts/"


@pytest_asyncio.fixture(scope="module")
async def client():
    app = create_app()
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac


async def _login(client: AsyncClient, *, admin: bool = False) -> tuple[dict[str, str], str]:
    unique = uuid.uuid4().hex[:8]
    email, password = f"cur-{unique}@test.io", f"Cursor{unique}9"
    reg = await client.post(
        "/api/v1/users/auth/register", json={"email": email, "password": password, "full_name": "C"}
    )
    assert reg.status_code == 201, reg.text
    from tests.integration._auth_helpers import promote_to_admin

    await promote_to_admin(email)
    if not admin:
        from sqlalchemy import update

        from app.modules.users.models import User

        async with async_session_factory() as s:
            await s.execute(update(User).where(User.email == email).values(role="editor"))
            await s.commit()
    data: dict = {}
    for attempt in range(3):
        data = (await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})).json()
        if data.get("access_token"):
            headers = {"Authorization": f"Bearer {data['access_token']}"}
            me = await client.get("/api/v1/users/me", headers=headers)
            return headers, me.json()["id"]
        await asyncio.sleep(5 * (attempt + 1))
    raise AssertionError(f"login failed: {data}")


async def _insert(tenant: str, names: list[str]) -> list[str]:
    ids = []
    async with async_session_factory() as session:
        for n in names:
            c = Contact(contact_type="client", company_name=n, tenant_id=tenant, created_by=tenant)
            session.add(c)
            await session.flush()
            ids.append(str(c.id))
        await session.commit()
    return ids


async def _walk(client, headers, limit: int, hook=None) -> list[str]:
    seen: list[str] = []
    cursor = ""
    page = 0
    while True:
        r = await client.get(URL, params={"cursor": cursor, "limit": limit}, headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        seen += [i["id"] for i in body["items"]]
        cursor = body["next_cursor"]
        page += 1
        if hook:
            await hook(page)
        if cursor is None:
            return seen


async def test_cursor_visits_each_row_once_with_inserts_between_pages(client):
    headers, uid = await _login(client)
    # Mixed case and repeated names exercise the id tiebreak.
    names = [f"{'Aa'[i % 2]}contact {i % 400:04d}" for i in range(1000)]
    original = set(await _insert(uid, names))
    late: set[str] = set()

    async def hook(page: int) -> None:
        if page in (2, 5):
            late.update(await _insert(uid, [f"zz late {page}-{k}" for k in range(3)]))

    seen = await _walk(client, headers, 100, hook)
    assert len(seen) == len(set(seen)), "a row was returned twice"
    assert original <= set(seen), "an existing row was skipped"
    assert set(seen) <= original | late


async def test_offset_callers_unchanged(client):
    headers, uid = await _login(client)
    await _insert(uid, ["one", "two", "three"])
    body = (await client.get(URL, params={"limit": 2}, headers=headers)).json()
    assert body["total"] == 3 and len(body["items"]) == 2 and body["next_cursor"] is None


@pytest.mark.parametrize("bad", ["not-base64!!", base64.urlsafe_b64encode(b"[1,2]").decode(), "e30", "W10"])
async def test_invalid_cursor_is_422(client, bad):
    headers, _ = await _login(client)
    r = await client.get(URL, params={"cursor": bad}, headers=headers)
    assert r.status_code == 422, r.text


async def test_cursor_does_not_cross_tenants(client):
    a_headers, a_id = await _login(client)
    b_headers, b_id = await _login(client)
    await _insert(a_id, [f"a-{i:03d}" for i in range(30)])
    b_rows = set(await _insert(b_id, [f"b-{i:03d}" for i in range(30)]))

    first = await client.get(URL, params={"cursor": "", "limit": 10}, headers=a_headers)
    assert first.status_code == 200, first.text
    cursor = first.json()["next_cursor"]
    assert cursor
    as_b = await client.get(URL, params={"cursor": cursor, "limit": 100}, headers=b_headers)
    assert {i["id"] for i in as_b.json()["items"]} <= b_rows
    assert not (set(await _walk(client, a_headers, 10)) & b_rows)
