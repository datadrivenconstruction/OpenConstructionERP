# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A topic can be addressed by its BCF GUID, not only by its surrogate id.

``TopicResponse`` publishes ``guid`` and nothing else that identifies the
topic, so every client that reads a topic and then edits it can only address it
by GUID - which is also the identity the BCF standard itself uses and the one
that survives an export / import round-trip. The routes historically resolved
the path segment against the surrogate primary key only, so a client following
the response shape got a 404 on every write.

Covers, for the GUID path segment:
    * update, comment, viewpoint, snapshot and delete all resolve
    * the surrogate id keeps working (existing callers are unaffected)
    * an unknown reference is a 404, and a malformed one is not a 500
    * a GUID belonging to another project does not resolve (IDOR)

Test isolation
~~~~~~~~~~~~~~
The PostgreSQL cluster and SQLAlchemy engine are provisioned by
``tests/conftest.py`` before any test module imports, so this module runs
against that shared PostgreSQL database.
"""

from __future__ import annotations

import asyncio
import base64
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# 1x1 transparent PNG.
_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    """Boot the FastAPI app once per module against the conftest PostgreSQL."""
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.bcf import models as _bcf_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield app


@pytest_asyncio.fixture(scope="module")
async def client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture(scope="module")
async def auth(client: AsyncClient) -> dict[str, str]:
    from ._auth_helpers import promote_to_admin

    unique = uuid.uuid4().hex[:8]
    email = f"bcf-ident-{unique}@test.io"
    password = f"BcfIdentTest{unique}9"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "BCF Identity Tester",
            "role": "admin",
        },
    )
    assert reg.status_code in (200, 201), reg.text
    await promote_to_admin(email)

    token = ""
    resp = None
    for attempt in range(3):
        resp = await client.post(
            "/api/v1/users/auth/login",
            json={"email": email, "password": password},
        )
        try:
            body = resp.json()
        except Exception:  # noqa: BLE001
            body = {}
        token = body.get("access_token", "")
        if token:
            break
        if "Too many login" in body.get("detail", ""):
            await asyncio.sleep(2 * (attempt + 1))
            continue
        break
    assert token, f"could not log in: {resp.status_code if resp else '?'}"
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="module")
async def project_id(client: AsyncClient, auth: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={"name": "BCF identity project", "description": "identity test"},
        headers=auth,
    )
    assert resp.status_code in (200, 201), resp.text
    return str(resp.json()["id"])


async def _create_topic(client: AsyncClient, auth: dict[str, str], project_id: str, title: str) -> dict:
    resp = await client.post(
        f"/api/v1/bcf/projects/{project_id}/topics/",
        json={"title": title, "topic_status": "Open", "priority": "Normal"},
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _surrogate_id(topic_guid: str) -> str:
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.bcf.models import BCFTopic

    async with async_session_factory() as session:
        row = (await session.execute(select(BCFTopic).where(BCFTopic.guid == topic_guid))).scalar_one()
        return str(row.id)


# ── 1. The GUID a client is given is the GUID it can write with ────────────


@pytest.mark.asyncio
async def test_the_published_guid_is_not_the_surrogate_id(
    client: AsyncClient, auth: dict[str, str], project_id: str
) -> None:
    """Guards the premise: if these two were equal the rest proves nothing."""
    topic = await _create_topic(client, auth, project_id, "Identity premise")
    assert topic["guid"] != await _surrogate_id(topic["guid"])


@pytest.mark.asyncio
async def test_topic_reads_and_writes_resolve_by_guid(
    client: AsyncClient, auth: dict[str, str], project_id: str
) -> None:
    topic = await _create_topic(client, auth, project_id, "Duct clashes with beam")
    guid = topic["guid"]
    base = f"/api/v1/bcf/projects/{project_id}/topics/{guid}"

    read = await client.get(base, headers=auth)
    assert read.status_code == 200, read.text
    assert read.json()["guid"] == guid

    updated = await client.put(base, json={"topic_status": "Resolved"}, headers=auth)
    assert updated.status_code == 200, updated.text
    assert updated.json()["topic_status"] == "Resolved"

    commented = await client.post(
        f"{base}/comments/",
        json={"comment": "MEP to reroute above the beam"},
        headers=auth,
    )
    assert commented.status_code == 201, commented.text

    vp = await client.post(
        f"{base}/viewpoints/",
        json={
            "perspective_camera": {
                "camera_view_point": {"x": 1.0, "y": 2.0, "z": 3.0},
                "camera_direction": {"x": 0.0, "y": -1.0, "z": 0.0},
                "camera_up_vector": {"x": 0.0, "y": 0.0, "z": 1.0},
                "field_of_view": 50.0,
            },
            "element_stable_ids": ["elem_001"],
            "snapshot_png_b64": _PNG_B64,
        },
        headers=auth,
    )
    assert vp.status_code == 201, vp.text
    vp_guid = vp.json()["guid"]

    # The snapshot is reachable through the same GUID-addressed path a client
    # builds from the topic it holds.
    snap = await client.get(f"{base}/viewpoints/{vp_guid}/snapshot", headers=auth)
    assert snap.status_code == 200, snap.text
    assert snap.content == base64.b64decode(_PNG_B64)

    # And the change really landed: the list is the client's next read.
    listed = await client.get(f"/api/v1/bcf/projects/{project_id}/topics/", headers=auth)
    assert listed.status_code == 200
    row = next(r for r in listed.json() if r["guid"] == guid)
    assert row["topic_status"] == "Resolved"
    assert len(row["comments"]) == 1
    assert len(row["viewpoints"]) == 1


# ── 2. The surrogate id keeps working ──────────────────────────────────────


@pytest.mark.asyncio
async def test_surrogate_id_still_resolves(client: AsyncClient, auth: dict[str, str], project_id: str) -> None:
    topic = await _create_topic(client, auth, project_id, "Addressed by surrogate id")
    db_id = await _surrogate_id(topic["guid"])
    base = f"/api/v1/bcf/projects/{project_id}/topics/{db_id}"

    read = await client.get(base, headers=auth)
    assert read.status_code == 200, read.text
    assert read.json()["guid"] == topic["guid"]

    updated = await client.put(base, json={"priority": "Critical"}, headers=auth)
    assert updated.status_code == 200, updated.text
    assert updated.json()["priority"] == "Critical"


# ── 3. Unknown / malformed / foreign references ────────────────────────────


@pytest.mark.asyncio
async def test_unknown_reference_is_a_clean_404(client: AsyncClient, auth: dict[str, str], project_id: str) -> None:
    unknown = await client.get(
        f"/api/v1/bcf/projects/{project_id}/topics/{uuid.uuid4()}",
        headers=auth,
    )
    assert unknown.status_code == 404, unknown.text

    # A reference that is not a UUID at all must not become a 500 - BCF
    # archives from other tools carry GUIDs in shapes we do not control.
    malformed = await client.get(
        f"/api/v1/bcf/projects/{project_id}/topics/not-a-uuid-at-all",
        headers=auth,
    )
    assert malformed.status_code in (404, 422), malformed.text


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_guid_of_another_project_does_not_resolve(
    client: AsyncClient, auth: dict[str, str], project_id: str
) -> None:
    other = await client.post(
        "/api/v1/projects/",
        json={"name": "BCF identity neighbour", "description": "neighbour"},
        headers=auth,
    )
    assert other.status_code in (200, 201), other.text
    foreign = await _create_topic(client, auth, str(other.json()["id"]), "Neighbour issue")

    resp = await client.get(
        f"/api/v1/bcf/projects/{project_id}/topics/{foreign['guid']}",
        headers=auth,
    )
    assert resp.status_code == 404, resp.text


# ── 4. Delete closes the loop ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_resolves_by_guid(client: AsyncClient, auth: dict[str, str], project_id: str) -> None:
    topic = await _create_topic(client, auth, project_id, "Raised then withdrawn")
    base = f"/api/v1/bcf/projects/{project_id}/topics/{topic['guid']}"

    deleted = await client.delete(base, headers=auth)
    assert deleted.status_code == 204, deleted.text

    gone = await client.get(base, headers=auth)
    assert gone.status_code == 404, gone.text
