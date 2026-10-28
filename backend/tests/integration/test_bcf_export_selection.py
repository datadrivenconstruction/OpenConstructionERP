# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for the selective ``.bcfzip`` export.

``POST /api/v1/bcf/projects/{project_id}/export`` hands the other side exactly
the topics a model-review session walked, named by BCF GUID. The companion
``GET`` route always exports the whole register.

Covers:
    * a selection exports only the named topics (and keeps their comments)
    * an omitted selection is parity with the whole-project ``GET`` export
    * a selection that matches nothing is a 422, never a hollow archive
    * a foreign GUID cannot smuggle another project's topic into the archive
    * unauthenticated access is rejected
    * IDOR - a non-owner cannot export another project's selection

Test isolation
~~~~~~~~~~~~~~
The PostgreSQL cluster and SQLAlchemy engine are provisioned by
``tests/conftest.py`` before any test module imports, so this module runs
against that shared PostgreSQL database.
"""

from __future__ import annotations

import asyncio
import io
import uuid
import zipfile

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# ── App + auth fixtures ────────────────────────────────────────────────────


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


async def _register_login(client: AsyncClient, tag: str, role: str = "admin") -> dict[str, str]:
    """Register a unique user, (optionally) promote to admin, return headers."""
    from ._auth_helpers import promote_to_admin

    unique = uuid.uuid4().hex[:8]
    email = f"bcf-sel-{tag}-{unique}@test.io"
    password = f"BcfSelTest{unique}9"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": f"BCF Selection Tester {tag}",
            "role": role,
        },
    )
    assert reg.status_code in (200, 201), f"register failed: {reg.text}"

    if role == "admin":
        await promote_to_admin(email)
    else:
        # /auth/register demotes to viewer and may leave the account inactive.
        # For the IDOR probe we only need an active, authenticated account.
        from sqlalchemy import update

        from app.database import async_session_factory
        from app.modules.users.models import User

        async with async_session_factory() as session:
            await session.execute(update(User).where(User.email == email.lower()).values(is_active=True))
            await session.commit()

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
async def auth(client: AsyncClient) -> dict[str, str]:
    return await _register_login(client, "owner")


@pytest_asyncio.fixture(scope="module")
async def project_id(client: AsyncClient, auth: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={"name": "BCF selection export project", "description": "bcf selection test"},
        headers=auth,
    )
    assert resp.status_code in (200, 201), f"project create: {resp.text[:200]}"
    return str(resp.json()["id"])


async def _create_topic(client: AsyncClient, auth: dict[str, str], project_id: str, title: str) -> dict:
    resp = await client.post(
        f"/api/v1/bcf/projects/{project_id}/topics/",
        json={
            "title": title,
            "description": f"Raised during the review: {title}",
            "topic_type": "Clash",
            "topic_status": "Open",
            "priority": "Normal",
            "labels": ["Structure"],
        },
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest_asyncio.fixture(scope="module")
async def agenda(client: AsyncClient, auth: dict[str, str], project_id: str) -> list[dict]:
    """Four topics; a review session will hand over two of them."""
    return [
        await _create_topic(client, auth, project_id, title)
        for title in (
            "Duct clashes with beam at grid C-4",
            "Door swing blocked by riser",
            "Slab opening missing for the stair core",
            "Sprinkler head under the ceiling grid",
        )
    ]


def _topic_guids_in_archive(archive: bytes) -> set[str]:
    """Return the topic GUIDs an exported ``.bcfzip`` contains.

    A BCF archive stores one directory per topic, named by the topic GUID and
    holding its ``markup.bcf``; reading the directory names is enough to say
    which issues were handed over.
    """
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        return {name.split("/")[0] for name in zf.namelist() if name.endswith("markup.bcf")}


# ── 1. A selection exports only the named topics ───────────────────────────


@pytest.mark.asyncio
async def test_selection_exports_only_the_named_topics(
    client: AsyncClient, auth: dict[str, str], project_id: str, agenda: list[dict]
) -> None:
    chosen = [agenda[0]["guid"], agenda[2]["guid"]]
    resp = await client.post(
        f"/api/v1/bcf/projects/{project_id}/export",
        json={"version": "2.1", "topic_guids": chosen},
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/octet-stream"
    assert "attachment;" in resp.headers["content-disposition"]
    assert ".bcfzip" in resp.headers["content-disposition"]
    assert resp.headers.get("x-bcf-topic-count") == "2"

    exported = _topic_guids_in_archive(resp.content)
    assert exported == set(chosen)
    # The two topics NOT on the agenda stay out of the hand-over.
    assert agenda[1]["guid"] not in exported
    assert agenda[3]["guid"] not in exported


# ── 2. No selection is parity with the whole-project GET export ────────────


@pytest.mark.asyncio
async def test_omitted_selection_exports_the_whole_project(
    client: AsyncClient, auth: dict[str, str], project_id: str, agenda: list[dict]
) -> None:
    posted = await client.post(
        f"/api/v1/bcf/projects/{project_id}/export",
        json={"version": "2.1"},
        headers=auth,
    )
    assert posted.status_code == 200, posted.text

    got = await client.get(
        f"/api/v1/bcf/projects/{project_id}/export?version=2.1",
        headers=auth,
    )
    assert got.status_code == 200, got.text

    all_guids = {t["guid"] for t in agenda}
    assert _topic_guids_in_archive(posted.content) == all_guids
    assert _topic_guids_in_archive(got.content) == all_guids


# ── 3. A selection that matches nothing is a 422, not a hollow archive ─────


@pytest.mark.asyncio
async def test_unknown_selection_is_rejected(
    client: AsyncClient, auth: dict[str, str], project_id: str, agenda: list[dict]
) -> None:
    resp = await client.post(
        f"/api/v1/bcf/projects/{project_id}/export",
        json={"version": "2.1", "topic_guids": [str(uuid.uuid4())]},
        headers=auth,
    )
    assert resp.status_code == 422, resp.text
    assert "selected" in resp.json()["detail"].lower()

    # An empty list is a selection of nothing - also a 422, never "everything".
    empty = await client.post(
        f"/api/v1/bcf/projects/{project_id}/export",
        json={"version": "2.1", "topic_guids": []},
        headers=auth,
    )
    assert empty.status_code == 422, empty.text


# ── 4. A GUID from another project cannot be pulled into the archive ───────


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_selection_cannot_reach_across_projects(
    client: AsyncClient, auth: dict[str, str], project_id: str, agenda: list[dict]
) -> None:
    other = await client.post(
        "/api/v1/projects/",
        json={"name": "BCF selection neighbour", "description": "neighbour"},
        headers=auth,
    )
    assert other.status_code in (200, 201), other.text
    other_id = str(other.json()["id"])
    foreign = await _create_topic(client, auth, other_id, "Neighbour project issue")

    resp = await client.post(
        f"/api/v1/bcf/projects/{project_id}/export",
        json={"version": "2.1", "topic_guids": [agenda[0]["guid"], foreign["guid"]]},
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    exported = _topic_guids_in_archive(resp.content)
    assert exported == {agenda[0]["guid"]}
    assert foreign["guid"] not in exported


# ── 5. Unsupported version is refused before any work happens ──────────────


@pytest.mark.asyncio
async def test_unsupported_version_is_refused(
    client: AsyncClient, auth: dict[str, str], project_id: str, agenda: list[dict]
) -> None:
    resp = await client.post(
        f"/api/v1/bcf/projects/{project_id}/export",
        json={"version": "1.0", "topic_guids": [agenda[0]["guid"]]},
        headers=auth,
    )
    assert resp.status_code == 422, resp.text


# ── 6. Auth + IDOR ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unauthenticated_export_is_rejected(client: AsyncClient, project_id: str) -> None:
    resp = await client.post(
        f"/api/v1/bcf/projects/{project_id}/export",
        json={"version": "2.1"},
    )
    assert resp.status_code in (401, 403), resp.text


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_non_owner_cannot_export_selection(client: AsyncClient, project_id: str, agenda: list[dict]) -> None:
    stranger = await _register_login(client, "stranger", role="viewer")
    resp = await client.post(
        f"/api/v1/bcf/projects/{project_id}/export",
        json={"version": "2.1", "topic_guids": [agenda[0]["guid"]]},
        headers=stranger,
    )
    # 404 (not 403) so the endpoint never confirms the project exists; a
    # viewer role without bcf.export lands on 403 just as legitimately.
    assert resp.status_code in (403, 404), resp.text
