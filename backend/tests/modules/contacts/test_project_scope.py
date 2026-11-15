"""The contacts list and its stats narrowed to one project.

A hosted demo shows one project at a time; its contacts carry
``metadata.project_id``, and the directory must be able to show those alone.

Run:
    cd backend
    python -m pytest -q -x --no-header tests/modules/contacts/test_project_scope.py
"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.database import async_session_factory
from app.main import create_app
from app.modules.contacts.models import Contact
from tests.modules.contacts.test_cursor_pagination import _login

pytestmark = pytest.mark.asyncio

URL = "/api/v1/contacts/"


@pytest_asyncio.fixture(scope="module")
async def client():
    app = create_app()
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac


async def _seed(tenant: str, project_a: str, project_b: str) -> None:
    async with async_session_factory() as session:
        rows = [
            ("A client", "client", {"project_id": project_a, "demo_id": "office-london"}),
            ("A sub", "subcontractor", {"project_id": project_a}),
            ("B client", "client", {"project_id": project_b}),
            ("Loose", "supplier", {}),
        ]
        for name, kind, meta in rows:
            session.add(
                Contact(contact_type=kind, company_name=name, tenant_id=tenant, created_by=tenant, metadata_=meta)
            )
        await session.commit()


async def test_list_and_stats_follow_the_project(client: AsyncClient) -> None:
    headers, me = await _login(client)
    project_a, project_b = str(uuid.uuid4()), str(uuid.uuid4())
    await _seed(me, project_a, project_b)

    everything = await client.get(URL, params={"limit": 500}, headers=headers)
    assert everything.status_code == 200, everything.text
    assert {c["company_name"] for c in everything.json()["items"]} >= {"A client", "A sub", "B client", "Loose"}

    scoped = await client.get(URL, params={"project_id": project_a, "limit": 500}, headers=headers)
    assert scoped.status_code == 200, scoped.text
    assert sorted(c["company_name"] for c in scoped.json()["items"]) == ["A client", "A sub"]
    assert scoped.json()["total"] == 2

    keyset = await client.get(URL, params={"project_id": project_b, "cursor": ""}, headers=headers)
    assert keyset.status_code == 200, keyset.text
    assert [c["company_name"] for c in keyset.json()["items"]] == ["B client"]

    stats = await client.get(f"{URL}stats/", params={"project_id": project_a}, headers=headers)
    assert stats.status_code == 200, stats.text
    assert stats.json()["total"] == 2
    assert stats.json()["by_type"] == {"client": 1, "subcontractor": 1}


async def test_project_id_must_be_a_uuid(client: AsyncClient) -> None:
    headers, _ = await _login(client)
    r = await client.get(URL, params={"project_id": "not-a-uuid"}, headers=headers)
    assert r.status_code == 422
