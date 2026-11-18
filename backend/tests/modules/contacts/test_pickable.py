"""The assignee picker lists the company's contacts; writes stay with the author.

Run:
    cd backend
    python -m pytest -q -x --no-header tests/modules/contacts/test_pickable.py
"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.database import async_session_factory
from app.main import create_app
from app.modules.contacts.models import Contact
from app.modules.teams.models import RosterMember
from tests.modules.contacts.test_cursor_pagination import _login

pytestmark = pytest.mark.asyncio

URL = "/api/v1/contacts/"


@pytest_asyncio.fixture(scope="module")
async def client():
    app = create_app()
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac


async def _contact(owner: str, name: str) -> uuid.UUID:
    async with async_session_factory() as session:
        c = Contact(contact_type="subcontractor", company_name=name, tenant_id=owner, created_by=owner)
        session.add(c)
        await session.commit()
        return c.id


async def _project(client: AsyncClient, headers: dict[str, str], tag: str) -> uuid.UUID:
    r = await client.post("/api/v1/projects/", json={"name": f"P {tag}", "currency": "EUR"}, headers=headers)
    assert r.status_code in (200, 201), r.text
    return uuid.UUID(r.json()["id"])


async def test_private_contact_of_another_user_is_not_offered(client: AsyncClient) -> None:
    _, author = await _login(client)
    tag = uuid.uuid4().hex[:8]
    await _contact(author, f"Private {tag}")
    viewer_headers, _ = await _login(client)

    r = await client.get(f"{URL}pickable/", params={"q": tag}, headers=viewer_headers)
    assert r.status_code == 200, r.text
    assert r.json() == {"team": [], "company": []}

    admin_headers, _ = await _login(client, admin=True)
    seen = await client.get(f"{URL}pickable/", params={"q": tag}, headers=admin_headers)
    assert [c["company_name"] for c in seen.json()["company"]] == [f"Private {tag}"]


async def test_colleague_on_my_project_roster_is_pickable_but_not_editable(client: AsyncClient) -> None:
    _, author = await _login(client)
    tag = uuid.uuid4().hex[:8]
    theirs = await _contact(author, f"Theirs {tag}")
    headers, _ = await _login(client)
    pid = await _project(client, headers, tag)
    async with async_session_factory() as session:
        session.add(RosterMember(project_id=pid, contact_id=theirs, display_name=f"Theirs {tag}"))
        await session.commit()

    # No project given: still offered, through the roster of a project the caller reaches.
    r = await client.get(f"{URL}pickable/", params={"q": tag}, headers=headers)
    assert r.status_code == 200, r.text
    assert [c["company_name"] for c in r.json()["company"]] == [f"Theirs {tag}"]
    assert "primary_phone" not in r.json()["company"][0]

    assert (await client.patch(f"{URL}{theirs}", json={"company_name": "Hijacked"}, headers=headers)).status_code == 403
    assert (await client.delete(f"{URL}{theirs}", headers=headers)).status_code == 403


async def test_project_team_comes_first_and_search_spans_both(client: AsyncClient) -> None:
    headers, me = await _login(client)
    _, other = await _login(client)
    tag = uuid.uuid4().hex[:8]
    member = await _contact(other, f"Zed team {tag}")
    outsider = await _contact(me, f"Abe outsider {tag}")
    pid = await _project(client, headers, tag)
    async with async_session_factory() as session:
        session.add(RosterMember(project_id=pid, contact_id=member, display_name=f"Zed team {tag}"))
        await session.commit()

    r = await client.get(f"{URL}pickable/", params={"project_id": str(pid), "q": tag}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert [c["id"] for c in body["team"]] == [str(member)]
    assert [c["id"] for c in body["company"]] == [str(outsider)]

    foreign = await client.get(f"{URL}pickable/", params={"project_id": str(uuid.uuid4())}, headers=headers)
    assert foreign.status_code in (403, 404)
