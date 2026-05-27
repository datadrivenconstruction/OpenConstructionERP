# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Integration tests for the OpenCDE BCF-API 3.0 surface.

Covers the 14 endpoints of the minimum compliance profile mounted at
``/api/v1/bcf/3.0/``:

    GET    /projects
    GET    /projects/{project_id}
    GET    /projects/{project_id}/extensions
    GET    /projects/{project_id}/topics
    POST   /projects/{project_id}/topics
    GET    /projects/{project_id}/topics/{topic_guid}
    PUT    /projects/{project_id}/topics/{topic_guid}
    DELETE /projects/{project_id}/topics/{topic_guid}
    GET    .../topics/{topic_guid}/comments
    POST   .../topics/{topic_guid}/comments
    GET    .../topics/{topic_guid}/viewpoints
    POST   .../topics/{topic_guid}/viewpoints
    GET    .../viewpoints/{vp}/snapshot
    GET    /current-user

Per ``feedback_test_isolation.md`` we point ``DATABASE_URL`` at a fresh
temp SQLite *before* importing any ``app`` module.
"""

from __future__ import annotations

import base64
import os
import tempfile
import uuid
from pathlib import Path

# ── Per-module SQLite isolation (MUST run BEFORE app imports) ─────────────

_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-bcf-opencde-routes-"))
_TMP_DB = _TMP_DIR / "bcf_opencde_routes.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

# 1x1 transparent PNG.
_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff"
    b"\xff?\x00\x05\xfe\x02\xfe\xa3yX\xd4\x00\x00\x00\x00IEND\xaeB`\x82"
)
_PNG_B64 = base64.b64encode(_PNG_BYTES).decode("ascii")

_API = "/api/v1/bcf/3.0"


# ── App / fixtures ────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
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


async def _register_admin(client: AsyncClient, tag: str) -> tuple[dict[str, str], str]:
    from tests.integration._auth_helpers import promote_to_admin

    suffix = uuid.uuid4().hex[:8]
    email = f"bcf-opencde-{tag}-{suffix}@test.io"
    password = f"BcfOpenCDE{suffix}9"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": f"BCF OpenCDE Tester {tag}",
            "role": "admin",
        },
    )
    assert reg.status_code in (200, 201), reg.text
    await promote_to_admin(email)
    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    token = login.json().get("access_token", "")
    assert token, login.text
    return {"Authorization": f"Bearer {token}"}, email


@pytest_asyncio.fixture(scope="module")
async def auth(client: AsyncClient) -> dict[str, str]:
    headers, _ = await _register_admin(client, "owner")
    return headers


@pytest_asyncio.fixture(scope="module")
async def project_id(client: AsyncClient, auth: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={"name": "BCF OpenCDE probe", "description": "BCF OpenCDE"},
        headers=auth,
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


async def _create_topic(client: AsyncClient, auth: dict[str, str], project_id: str, **overrides) -> dict:
    payload = {
        "topic_type": "Issue",
        "topic_status": "Open",
        "priority": "Normal",
        "title": "Sample issue",
        "description": "Some description",
        "labels": ["MEP"],
    }
    payload.update(overrides)
    resp = await client.post(
        f"{_API}/projects/{project_id}/topics",
        json=payload,
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── 1. Happy-path: list projects ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_projects_happy(client: AsyncClient, auth: dict[str, str], project_id: str) -> None:
    resp = await client.get(f"{_API}/projects", headers=auth)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list)
    assert any(p["project_id"] == project_id for p in body)


# ── 2. Single project ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_single_project(client: AsyncClient, auth: dict[str, str], project_id: str) -> None:
    resp = await client.get(f"{_API}/projects/{project_id}", headers=auth)
    assert resp.status_code == 200
    body = resp.json()
    assert body["project_id"] == project_id
    assert "authorization" in body


# ── 3. Extensions ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_extensions(client: AsyncClient, auth: dict[str, str], project_id: str) -> None:
    resp = await client.get(f"{_API}/projects/{project_id}/extensions", headers=auth)
    assert resp.status_code == 200
    body = resp.json()
    assert "topic_type" in body
    assert "topic_status" in body
    assert "priority" in body
    assert "Open" in body["topic_status"]


# ── 4. Create topic — caller is creation_author ──────────────────────────


@pytest.mark.asyncio
async def test_create_topic_uses_caller_as_author(client: AsyncClient, auth: dict[str, str], project_id: str) -> None:
    topic = await _create_topic(client, auth, project_id, title="Created by me")
    # creation_author must be present and non-empty.
    assert topic["creation_author"]
    assert topic["title"] == "Created by me"
    assert topic["topic_status"] == "Open"


# ── 5. List topics ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_topics_returns_envelope(client: AsyncClient, auth: dict[str, str], project_id: str) -> None:
    await _create_topic(client, auth, project_id, title="A list test topic")
    resp = await client.get(f"{_API}/projects/{project_id}/topics", headers=auth)
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert isinstance(body["items"], list)
    assert "X-Total-Count" in resp.headers


# ── 6. Single topic — ETag returned ──────────────────────────────────────


@pytest.mark.asyncio
async def test_get_topic_returns_etag(client: AsyncClient, auth: dict[str, str], project_id: str) -> None:
    topic = await _create_topic(client, auth, project_id)
    resp = await client.get(f"{_API}/projects/{project_id}/topics/{topic['guid']}", headers=auth)
    assert resp.status_code == 200
    assert "etag" in {k.lower() for k in resp.headers.keys()}
    assert resp.json()["guid"] == topic["guid"]


# ── 7. PUT — bumps modified_author / modified_date ───────────────────────


@pytest.mark.asyncio
async def test_put_topic_bumps_modified(client: AsyncClient, auth: dict[str, str], project_id: str) -> None:
    topic = await _create_topic(client, auth, project_id)
    original_modified = topic["modified_date"]
    import asyncio

    await asyncio.sleep(0.01)
    resp = await client.put(
        f"{_API}/projects/{project_id}/topics/{topic['guid']}",
        json={"title": "Edited", "topic_status": "In Progress"},
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["title"] == "Edited"
    assert body["topic_status"] == "In Progress"
    assert body["modified_date"] != original_modified


# ── 8. ETag round-trip — stale If-Match → 412 ────────────────────────────


@pytest.mark.asyncio
async def test_etag_stale_if_match_returns_412(client: AsyncClient, auth: dict[str, str], project_id: str) -> None:
    topic = await _create_topic(client, auth, project_id)
    stale_etag = '"deadbeef0000000000000000000000000000aaaa"'
    resp = await client.put(
        f"{_API}/projects/{project_id}/topics/{topic['guid']}",
        json={"title": "Should fail"},
        headers={**auth, "If-Match": stale_etag},
    )
    assert resp.status_code == 412, resp.text


# ── 9. ETag round-trip — current If-Match → 200 ──────────────────────────


@pytest.mark.asyncio
async def test_etag_fresh_if_match_succeeds(client: AsyncClient, auth: dict[str, str], project_id: str) -> None:
    topic = await _create_topic(client, auth, project_id)
    get_resp = await client.get(f"{_API}/projects/{project_id}/topics/{topic['guid']}", headers=auth)
    etag = get_resp.headers["etag"]
    resp = await client.put(
        f"{_API}/projects/{project_id}/topics/{topic['guid']}",
        json={"description": "Updated body"},
        headers={**auth, "If-Match": etag},
    )
    assert resp.status_code == 200, resp.text


# ── 10. DELETE → 204; subsequent GET → 404 ───────────────────────────────


@pytest.mark.asyncio
async def test_delete_topic_204_then_404(client: AsyncClient, auth: dict[str, str], project_id: str) -> None:
    topic = await _create_topic(client, auth, project_id, title="Delete me")
    del_resp = await client.delete(f"{_API}/projects/{project_id}/topics/{topic['guid']}", headers=auth)
    assert del_resp.status_code == 204
    get_resp = await client.get(f"{_API}/projects/{project_id}/topics/{topic['guid']}", headers=auth)
    assert get_resp.status_code == 404


# ── 11. POST comment ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_comment(client: AsyncClient, auth: dict[str, str], project_id: str) -> None:
    topic = await _create_topic(client, auth, project_id)
    resp = await client.post(
        f"{_API}/projects/{project_id}/topics/{topic['guid']}/comments",
        json={"comment": "First reply"},
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["comment"] == "First reply"
    assert body["topic_guid"] == topic["guid"]


# ── 12. POST comment with reply_to_comment_guid ──────────────────────────


@pytest.mark.asyncio
async def test_post_comment_reply_chain(client: AsyncClient, auth: dict[str, str], project_id: str) -> None:
    topic = await _create_topic(client, auth, project_id)
    first = await client.post(
        f"{_API}/projects/{project_id}/topics/{topic['guid']}/comments",
        json={"comment": "Parent"},
        headers=auth,
    )
    parent_guid = first.json()["guid"]
    second = await client.post(
        f"{_API}/projects/{project_id}/topics/{topic['guid']}/comments",
        json={"comment": "Child", "reply_to_comment_guid": parent_guid},
        headers=auth,
    )
    assert second.status_code == 201, second.text
    body = second.json()
    assert body["reply_to_comment_guid"] == parent_guid


# ── 13. GET comments list ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_comments(client: AsyncClient, auth: dict[str, str], project_id: str) -> None:
    topic = await _create_topic(client, auth, project_id)
    await client.post(
        f"{_API}/projects/{project_id}/topics/{topic['guid']}/comments",
        json={"comment": "One"},
        headers=auth,
    )
    await client.post(
        f"{_API}/projects/{project_id}/topics/{topic['guid']}/comments",
        json={"comment": "Two"},
        headers=auth,
    )
    resp = await client.get(
        f"{_API}/projects/{project_id}/topics/{topic['guid']}/comments",
        headers=auth,
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) >= 2


# ── 14. POST viewpoint (JSON body, no XML) ───────────────────────────────


@pytest.mark.asyncio
async def test_post_viewpoint(client: AsyncClient, auth: dict[str, str], project_id: str) -> None:
    topic = await _create_topic(client, auth, project_id)
    body = {
        "perspective_camera": {
            "camera_view_point": {"x": 1.0, "y": 2.0, "z": 3.0},
            "camera_direction": {"x": 0.0, "y": 0.0, "z": -1.0},
            "camera_up_vector": {"x": 0.0, "y": 1.0, "z": 0.0},
            "field_of_view": 60.0,
            "aspect_ratio": 1.0,
        },
        "components": {
            "selection": [{"ifc_guid": "0aBcDe"}],
            "visibility": {"default_visibility": True},
            "coloring": [],
        },
        "snapshot": {"snapshot_type": "png", "snapshot_data": _PNG_B64},
    }
    resp = await client.post(
        f"{_API}/projects/{project_id}/topics/{topic['guid']}/viewpoints",
        json=body,
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["guid"]
    assert body["perspective_camera"]["camera_view_point"]["x"] == 1.0


# ── 15. GET viewpoints list ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_viewpoints(client: AsyncClient, auth: dict[str, str], project_id: str) -> None:
    topic = await _create_topic(client, auth, project_id)
    await client.post(
        f"{_API}/projects/{project_id}/topics/{topic['guid']}/viewpoints",
        json={"perspective_camera": {"field_of_view": 90.0}},
        headers=auth,
    )
    resp = await client.get(
        f"{_API}/projects/{project_id}/topics/{topic['guid']}/viewpoints",
        headers=auth,
    )
    assert resp.status_code == 200
    assert "items" in resp.json()
    assert len(resp.json()["items"]) >= 1


# ── 16. Snapshot endpoint ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_snapshot_returns_png(client: AsyncClient, auth: dict[str, str], project_id: str) -> None:
    topic = await _create_topic(client, auth, project_id)
    vp_resp = await client.post(
        f"{_API}/projects/{project_id}/topics/{topic['guid']}/viewpoints",
        json={
            "perspective_camera": {"field_of_view": 60.0},
            "snapshot": {"snapshot_type": "png", "snapshot_data": _PNG_B64},
        },
        headers=auth,
    )
    vp_guid = vp_resp.json()["guid"]
    snap_resp = await client.get(
        f"{_API}/projects/{project_id}/topics/{topic['guid']}/viewpoints/{vp_guid}/snapshot",
        headers=auth,
    )
    assert snap_resp.status_code == 200
    assert snap_resp.headers["content-type"] == "image/png"
    assert snap_resp.content.startswith(b"\x89PNG\r\n\x1a\n")


# ── 17. /current-user ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_current_user(client: AsyncClient, auth: dict[str, str]) -> None:
    resp = await client.get(f"{_API}/current-user", headers=auth)
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"]
    assert body["name"]


# ── 18. Auth: missing token → 401 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_token_401(client: AsyncClient, project_id: str) -> None:
    resp = await client.get(f"{_API}/projects/{project_id}/topics")
    assert resp.status_code in (401, 403)


# ── 19. Auth: wrong project (IDOR) → 403/404 ─────────────────────────────


@pytest.mark.asyncio
async def test_wrong_project_blocked(client: AsyncClient, project_id: str) -> None:
    other_headers, _ = await _register_admin(client, "second-owner-idor")
    # other_headers is also admin → can read. Make a viewer instead.
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    suffix = uuid.uuid4().hex[:8]
    email = f"bcf-opencde-viewer-{suffix}@test.io"
    password = f"BcfOpenCDEVwr{suffix}9"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "Viewer",
            "role": "viewer",
        },
    )
    assert reg.status_code in (200, 201)
    async with async_session_factory() as session:
        await session.execute(update(User).where(User.email == email.lower()).values(is_active=True))
        await session.commit()
    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    token = login.json().get("access_token", "")
    assert token
    headers = {"Authorization": f"Bearer {token}"}
    resp = await client.get(f"{_API}/projects/{project_id}/topics", headers=headers)
    assert resp.status_code in (403, 404)


# ── 20. Validation: invalid UUID → 422 ───────────────────────────────────


@pytest.mark.asyncio
async def test_invalid_uuid_422(client: AsyncClient, auth: dict[str, str], project_id: str) -> None:
    resp = await client.get(
        f"{_API}/projects/{project_id}/topics/not-a-real-uuid",
        headers=auth,
    )
    assert resp.status_code == 422


# ── 21. Validation: malformed JSON → 422 ─────────────────────────────────


@pytest.mark.asyncio
async def test_malformed_json_422(client: AsyncClient, auth: dict[str, str], project_id: str) -> None:
    resp = await client.post(
        f"{_API}/projects/{project_id}/topics",
        content=b"{ not valid json",
        headers={**auth, "Content-Type": "application/json"},
    )
    assert resp.status_code in (400, 422)


# ── 22. OData $filter forwards to DB ─────────────────────────────────────


@pytest.mark.asyncio
async def test_odata_filter_topic_status(client: AsyncClient, auth: dict[str, str]) -> None:
    # Fresh isolated project so the count is predictable.
    proj_resp = await client.post(
        "/api/v1/projects/",
        json={"name": "filter probe", "description": "filter"},
        headers=auth,
    )
    pid = proj_resp.json()["id"]
    await _create_topic(client, auth, pid, title="A1", topic_status="Open")
    await _create_topic(client, auth, pid, title="A2", topic_status="Open")
    await _create_topic(client, auth, pid, title="B1", topic_status="In Progress")

    resp = await client.get(
        f"{_API}/projects/{pid}/topics",
        params={"$filter": "topic_status eq 'Open'"},
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == 2
    assert all(it["topic_status"] == "Open" for it in items)


# ── 23. 503 when ClashIssue table missing (via patched OpenCDEService) ───


@pytest.mark.asyncio
async def test_503_when_clash_issue_unavailable(
    client: AsyncClient,
    auth: dict[str, str],
    project_id: str,
    monkeypatch,
) -> None:
    """The OpenCDE surface mirrors the import path's degradation contract:
    when a dependent feature is unavailable, surface 503 with structured detail
    rather than 500.

    Here we patch ``list_projects`` to raise the service-layer 503 marker.
    """
    from app.modules.bcf import opencde_service

    async def boom(*args, **kwargs):
        raise opencde_service.FeatureUnavailableError("Clash storage table missing")

    monkeypatch.setattr(opencde_service.OpenCDEService, "list_projects", boom)
    resp = await client.get(f"{_API}/projects", headers=auth)
    assert resp.status_code == 503, resp.text
    assert "Clash storage table missing" in resp.text
