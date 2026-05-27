"""Integration tests for the BCF module HTTP surface.

Covers:
    * topic / comment / viewpoint CRUD with auth
    * full ``.bcfzip`` roundtrip (create → export → import-into-clean →
      assert equality) for BOTH BCF 2.1 and 3.0
    * malformed-zip import → structured 200 report (never 500)
    * auth: unauthenticated request is rejected
    * IDOR: a non-owner cannot read another project's topics

Test isolation
~~~~~~~~~~~~~~
Per ``feedback_test_isolation.md`` we point ``DATABASE_URL`` at a fresh
temp SQLite file BEFORE ``app.database`` is first imported.
"""

from __future__ import annotations

import base64
import io
import os
import tempfile
import uuid
import zipfile
from pathlib import Path

# ── Per-module SQLite isolation (MUST run BEFORE app imports) ─────────────

_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-bcf-api-"))
_TMP_DB = _TMP_DIR / "bcf_api.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import asyncio  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

# 1x1 transparent PNG.
_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="


# ── App + auth fixtures ────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    """Boot the FastAPI app once per module against the temp SQLite."""
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
    email = f"bcf-{tag}-{unique}@test.io"
    password = f"BcfApiTest{unique}9"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": f"BCF Tester {tag}",
            "role": role,
        },
    )
    assert reg.status_code in (200, 201), f"register failed: {reg.text}"

    if role == "admin":
        await promote_to_admin(email)
    else:
        # /auth/register demotes everyone to viewer and (in admin-approve
        # mode) leaves them inactive. For a genuine "authenticated but not
        # the project owner" IDOR probe we only need an active account —
        # NOT admin — so flip is_active without touching the role.
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


async def _make_project(client: AsyncClient, auth: dict[str, str], name: str) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={"name": name, "description": "bcf test"},
        headers=auth,
    )
    assert resp.status_code in (200, 201), f"project create: {resp.text[:200]}"
    return resp.json()["id"]


@pytest_asyncio.fixture(scope="module")
async def project_id(client: AsyncClient, auth: dict[str, str]) -> str:
    return await _make_project(client, auth, "BCF roundtrip project")


# ── 1. Topic + comment + viewpoint CRUD ───────────────────────────────────


@pytest.mark.asyncio
async def test_topic_comment_viewpoint_crud(client: AsyncClient, auth: dict[str, str], project_id: str) -> None:
    """Create topic → add viewpoint (with PNG) → add comment → fetch."""
    create = await client.post(
        f"/api/v1/bcf/projects/{project_id}/topics/",
        json={
            "title": "Door swing clashes with wall",
            "description": "D-103 swings into the partition.",
            "topic_type": "Clash",
            "topic_status": "Open",
            "priority": "Normal",
            "labels": ["Architecture"],
        },
        headers=auth,
    )
    assert create.status_code == 201, create.text
    topic = create.json()
    topic_db_id = None  # the URL uses surrogate id; fetch list to resolve

    # The response carries the BCF guid; list to get the surrogate path id.
    lst = await client.get(f"/api/v1/bcf/projects/{project_id}/topics/", headers=auth)
    assert lst.status_code == 200
    assert any(t["guid"] == topic["guid"] for t in lst.json())

    # Resolve the path id via the get-by-guid-less route: the create
    # response's guid is stable, but routes are keyed by surrogate id.
    # We re-create through the service-agnostic list and match guid.
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.bcf.models import BCFTopic

    async with async_session_factory() as session:
        row = (await session.execute(select(BCFTopic).where(BCFTopic.guid == topic["guid"]))).scalar_one()
        topic_db_id = str(row.id)

    # Add a viewpoint with a perspective camera + snapshot.
    vp_resp = await client.post(
        f"/api/v1/bcf/projects/{project_id}/topics/{topic_db_id}/viewpoints/",
        json={
            "perspective_camera": {
                "camera_view_point": {"x": 1.0, "y": 2.0, "z": 3.0},
                "camera_direction": {"x": 0.0, "y": -1.0, "z": 0.0},
                "camera_up_vector": {"x": 0.0, "y": 0.0, "z": 1.0},
                "field_of_view": 50.0,
            },
            "components": {
                "selection": ["2O2Fr$t4X7Zf8NOew3FNr"],
                "visible": [],
                "hidden": [],
                "default_visibility": True,
            },
            "element_stable_ids": ["elem_001"],
            "snapshot_png_b64": _PNG_B64,
        },
        headers=auth,
    )
    assert vp_resp.status_code == 201, vp_resp.text
    vp = vp_resp.json()
    assert vp["has_snapshot"] is True
    assert vp["snapshot_url"]

    # Snapshot is retrievable as a PNG.
    snap = await client.get(vp["snapshot_url"], headers=auth)
    assert snap.status_code == 200
    assert snap.headers["content-type"] == "image/png"
    assert snap.content == base64.b64decode(_PNG_B64)

    # Add a comment bound to the viewpoint.
    c_resp = await client.post(
        f"/api/v1/bcf/projects/{project_id}/topics/{topic_db_id}/comments/",
        json={"comment": "Confirmed clash, please revise.", "viewpoint_guid": vp["guid"]},
        headers=auth,
    )
    assert c_resp.status_code == 201, c_resp.text
    assert c_resp.json()["viewpoint_guid"] == vp["guid"]

    # Fetch full topic — comment + viewpoint nested.
    got = await client.get(
        f"/api/v1/bcf/projects/{project_id}/topics/{topic_db_id}",
        headers=auth,
    )
    assert got.status_code == 200
    full = got.json()
    assert len(full["comments"]) == 1
    assert len(full["viewpoints"]) == 1


# ── 2. Full .bcfzip roundtrip for BOTH 2.1 and 3.0 ────────────────────────


@pytest.mark.parametrize("version", ["2.1", "3.0"])
@pytest.mark.asyncio
async def test_bcfzip_roundtrip(client: AsyncClient, auth: dict[str, str], version: str) -> None:
    """Build topics in project A → export → import into clean project B →
    assert the topic/comment/viewpoint set is equal.
    """
    src_proj = await _make_project(client, auth, f"BCF src {version}")
    dst_proj = await _make_project(client, auth, f"BCF dst {version}")

    # Seed two topics with comments + viewpoints in the source project.
    seeded_guids: list[str] = []
    for i in range(2):
        cr = await client.post(
            f"/api/v1/bcf/projects/{src_proj}/topics/",
            json={
                "title": f"Issue {i} ({version})",
                "description": f"Body {i}",
                "topic_type": "Issue",
                "topic_status": "Open",
                "priority": "High" if i == 0 else "Low",
                "labels": [f"L{i}"],
            },
            headers=auth,
        )
        assert cr.status_code == 201
        guid = cr.json()["guid"]
        seeded_guids.append(guid)

        from sqlalchemy import select

        from app.database import async_session_factory
        from app.modules.bcf.models import BCFTopic

        async with async_session_factory() as session:
            row = (await session.execute(select(BCFTopic).where(BCFTopic.guid == guid))).scalar_one()
            tid = str(row.id)

        await client.post(
            f"/api/v1/bcf/projects/{src_proj}/topics/{tid}/viewpoints/",
            json={
                "orthogonal_camera": {
                    "camera_view_point": {"x": 0.0, "y": 0.0, "z": 5.0},
                    "camera_direction": {"x": 0.0, "y": 0.0, "z": -1.0},
                    "camera_up_vector": {"x": 0.0, "y": 1.0, "z": 0.0},
                    "view_to_world_scale": 1.5,
                },
                "components": {
                    "selection": [f"sel-{i}"],
                    "visible": [],
                    "hidden": [],
                    "default_visibility": True,
                },
                "snapshot_png_b64": _PNG_B64,
            },
            headers=auth,
        )
        await client.post(
            f"/api/v1/bcf/projects/{src_proj}/topics/{tid}/comments/",
            json={"comment": f"Comment on issue {i}"},
            headers=auth,
        )

    # Export the source project as a .bcfzip.
    export = await client.get(
        f"/api/v1/bcf/projects/{src_proj}/export?version={version}",
        headers=auth,
    )
    assert export.status_code == 200, export.text
    archive = export.content
    # The archive is a real zip with the expected spec members.
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        names = zf.namelist()
        assert "bcf.version" in names
        assert sum(1 for n in names if n.endswith("markup.bcf")) == 2

    # Import into the *clean* destination project.
    files = {"file": (f"export-{version}.bcfzip", archive, "application/octet-stream")}
    imp = await client.post(
        f"/api/v1/bcf/projects/{dst_proj}/import",
        files=files,
        headers=auth,
    )
    assert imp.status_code == 200, imp.text
    report = imp.json()
    assert report["detected_version"] == version
    assert report["topics_imported"] == 2
    assert report["comments_imported"] == 2
    assert report["viewpoints_imported"] == 2
    assert report["status"] in ("passed", "warnings")

    # Destination now mirrors the source: same guids, comments, viewpoints.
    dst_list = await client.get(f"/api/v1/bcf/projects/{dst_proj}/topics/", headers=auth)
    assert dst_list.status_code == 200
    dst_topics = {t["guid"]: t for t in dst_list.json()}
    assert set(dst_topics) == set(seeded_guids)
    for guid in seeded_guids:
        dt = dst_topics[guid]
        assert dt["topic_type"] == "Issue"
        assert len(dt["comments"]) == 1
        assert len(dt["viewpoints"]) == 1

    # Re-import the same archive → idempotent (updates, no duplicates).
    imp2 = await client.post(
        f"/api/v1/bcf/projects/{dst_proj}/import",
        files={"file": (f"again-{version}.bcfzip", archive, "application/octet-stream")},
        headers=auth,
    )
    assert imp2.status_code == 200, imp2.text
    report2 = imp2.json()
    assert report2["topics_imported"] == 0
    assert report2["topics_updated"] == 2
    dst_list2 = await client.get(f"/api/v1/bcf/projects/{dst_proj}/topics/", headers=auth)
    assert len(dst_list2.json()) == 2  # no duplicates


# ── 3. Malformed zip → structured report, never 500 ───────────────────────


@pytest.mark.asyncio
async def test_import_malformed_zip_returns_report(client: AsyncClient, auth: dict[str, str], project_id: str) -> None:
    """A non-BCF / corrupt payload returns a 200 report with errors."""
    files = {"file": ("garbage.bcfzip", b"\x50\x4b not really a zip", "application/octet-stream")}
    resp = await client.post(
        f"/api/v1/bcf/projects/{project_id}/import",
        files=files,
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "errors"
    assert body["topics_imported"] == 0
    assert any(i["severity"] == "error" for i in body["issues"])


@pytest.mark.asyncio
async def test_import_empty_file_rejected(client: AsyncClient, auth: dict[str, str], project_id: str) -> None:
    """An empty upload is a 400 (client error), not a 500."""
    files = {"file": ("empty.bcfzip", b"", "application/octet-stream")}
    resp = await client.post(
        f"/api/v1/bcf/projects/{project_id}/import",
        files=files,
        headers=auth,
    )
    assert resp.status_code == 400


# ── 4. Auth ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unauthenticated_is_rejected(client: AsyncClient, project_id: str) -> None:
    """No bearer token → 401/403, never 200."""
    resp = await client.get(f"/api/v1/bcf/projects/{project_id}/topics/")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_idor_non_owner_cannot_read_other_project(
    client: AsyncClient, auth: dict[str, str], project_id: str
) -> None:
    """A different (non-admin) user cannot read the owner's topics."""
    intruder = await _register_login(client, "intruder", role="viewer")
    resp = await client.get(f"/api/v1/bcf/projects/{project_id}/topics/", headers=intruder)
    # 403 (access denied) or 404 (existence hidden) — both block the read.
    assert resp.status_code in (403, 404)
