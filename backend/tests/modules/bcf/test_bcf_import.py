# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Integration tests for :class:`BCFImportService` + ``POST /import/clashes``.

The fixtures mirror :file:`test_bcf_export.py` exactly so the test runs
against a fresh per-module SQLite DB with the BCF + Clash tables
auto-created. Each test sends a real multipart ``.bcfzip`` upload
through the FastAPI test client.

Cases:
    1. import 3 topics → 3 ClashIssue rows created
    2. re-import same archive → 0 created / 0 updated reported
    3. topic with new TopicStatus updates the existing issue's status
    4. cross-project IDOR returns 403
    5. archive > 100 MB returns 413
    6. non-zip payload returns 422
    7. missing token returns 401
    8. viewer (no ``bcf.import`` permission) returns 403
"""

from __future__ import annotations

import io
import os
import tempfile
import uuid
import zipfile
from pathlib import Path

# ── Per-module SQLite isolation MUST run BEFORE app imports ────────────────

_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-bcf-import-"))
_TMP_DB = _TMP_DIR / "bcf_import.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

# ── helpers ───────────────────────────────────────────────────────────────


def _make_bcfzip(topics: list[dict]) -> bytes:
    """Compose a real .bcfzip from a list of topic dicts.

    Each topic dict carries ``guid`` (str), ``server_assigned_id`` (str|None),
    ``status`` (str, e.g. ``"Open"``), ``priority`` (str|None),
    ``labels`` (list[str]).
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "bcf.version",
            b'<?xml version="1.0" encoding="utf-8"?><Version VersionId="3.0"/>',
        )
        for t in topics:
            sai = f' ServerAssignedId="{t["server_assigned_id"]}"' if t.get("server_assigned_id") else ""
            labels_xml = ""
            if t.get("labels"):
                labels_xml = "<Labels>" + "".join(f"<Label>{lab}</Label>" for lab in t["labels"]) + "</Labels>"
            priority_xml = f"<Priority>{t['priority']}</Priority>" if t.get("priority") else ""
            body = (
                f'<?xml version="1.0" encoding="utf-8"?><Markup>'
                f'<Topic Guid="{t["guid"]}" TopicType="Clash" '
                f'TopicStatus="{t["status"]}"{sai}>'
                f"<Title>{t.get('title', 'Test topic')}</Title>"
                f"{priority_xml}{labels_xml}"
                f"<CreationDate>2026-05-21T10:00:00Z</CreationDate>"
                f"<CreationAuthor>alice@example.com</CreationAuthor>"
                f"</Topic></Markup>"
            ).encode()
            zf.writestr(f"{t['guid']}/markup.bcf", body)
    return buf.getvalue()


# ── app / auth / project fixtures ─────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.bcf import models as _bcf_models  # noqa: F401
        from app.modules.clash import models as _clash_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield app


@pytest_asyncio.fixture(scope="module")
async def client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _register_user(client: AsyncClient, tag: str = "owner", role: str = "admin") -> tuple[dict[str, str], str]:
    """Register + (optionally) promote a user; return (auth_header, email)."""
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User
    from tests.integration._auth_helpers import promote_to_admin

    suffix = uuid.uuid4().hex[:8]
    email = f"bcf-import-{tag}-{suffix}@test.io"
    password = f"BcfImportTest{suffix}9"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": f"BCF Import Tester {tag}",
            "role": role,
        },
    )
    assert reg.status_code in (200, 201), reg.text

    if role == "admin":
        await promote_to_admin(email)
    else:
        async with async_session_factory() as session:
            await session.execute(update(User).where(User.email == email.lower()).values(is_active=True))
            await session.commit()

    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    token = login.json().get("access_token", "")
    assert token, login.text
    return {"Authorization": f"Bearer {token}"}, email


@pytest_asyncio.fixture(scope="module")
async def owner_auth(client: AsyncClient) -> dict[str, str]:
    headers, _ = await _register_user(client, "owner", role="admin")
    return headers


@pytest_asyncio.fixture(scope="module")
async def viewer_auth(client: AsyncClient) -> dict[str, str]:
    headers, _ = await _register_user(client, "viewer", role="viewer")
    return headers


@pytest_asyncio.fixture(scope="module")
async def project_id(client: AsyncClient, owner_auth: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={"name": "BCF import probe", "description": "BCF clash import"},
        headers=owner_auth,
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


# ── 1. happy path: 3 topics import → 3 issues created ────────────────────


@pytest.mark.asyncio
async def test_import_3_topics_creates_3_clash_issues(
    client: AsyncClient,
    owner_auth: dict[str, str],
    project_id: str,
) -> None:
    """A 3-topic archive lands as 3 ClashIssue rows on the target project."""
    topics = [
        {
            "guid": uuid.uuid4().hex,
            "server_assigned_id": "BCF-001",
            "status": "Open",
            "priority": "Critical",
            "labels": ["hard", "MEP-vs-STR"],
        },
        {
            "guid": uuid.uuid4().hex,
            "server_assigned_id": "BCF-002",
            "status": "Closed",
            "priority": "Minor",
            "labels": ["clearance"],
        },
        {
            "guid": uuid.uuid4().hex,
            "server_assigned_id": "BCF-003",
            "status": "In Progress",
            "priority": "Normal",
            "labels": [],
        },
    ]
    payload = _make_bcfzip(topics)
    resp = await client.post(
        "/api/v1/bcf/import/clashes",
        params={"project_id": project_id},
        headers=owner_auth,
        files={"file": ("topics.bcfzip", payload, "application/zip")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["created"] == 3
    assert body["updated"] == 0
    assert body["skipped"] == 0
    assert body["errors"] == []

    # Verify rows actually exist in the DB.
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.clash.models import ClashIssue

    async with async_session_factory() as session:
        rows = (
            (await session.execute(select(ClashIssue).where(ClashIssue.project_id == uuid.UUID(project_id))))
            .scalars()
            .all()
        )
        # Could be 3 (or 3 + other tests' rows — assert at least 3 in this proj).
        assert len(rows) >= 3
        sids = {(r.server_assigned_id or "") for r in rows}
        assert {"BCF-001", "BCF-002", "BCF-003"}.issubset(sids)


# ── 2. re-import is idempotent ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reimport_same_archive_is_idempotent(
    client: AsyncClient,
    owner_auth: dict[str, str],
    project_id: str,
) -> None:
    """Re-uploading the same archive must report 0 created / 0 updated."""
    topics = [
        {
            "guid": uuid.uuid4().hex,
            "server_assigned_id": "BCF-IDEM-1",
            "status": "Open",
            "priority": "Normal",
            "labels": ["idempotent"],
        },
    ]
    payload = _make_bcfzip(topics)
    files = {"file": ("idem.bcfzip", payload, "application/zip")}
    r1 = await client.post(
        "/api/v1/bcf/import/clashes",
        params={"project_id": project_id},
        headers=owner_auth,
        files=files,
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["created"] == 1

    # Second upload — same bytes.
    r2 = await client.post(
        "/api/v1/bcf/import/clashes",
        params={"project_id": project_id},
        headers=owner_auth,
        files={"file": ("idem.bcfzip", payload, "application/zip")},
    )
    assert r2.status_code == 200, r2.text
    b2 = r2.json()
    assert b2["created"] == 0
    # No fields changed → all skipped (not "updated").
    assert b2["updated"] == 0
    assert b2["skipped"] == 1


# ── 3. status update is detected ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_status_change_triggers_update(
    client: AsyncClient,
    owner_auth: dict[str, str],
    project_id: str,
) -> None:
    """Re-import with TopicStatus=Closed flips the issue's smart status."""
    sai = "BCF-CHANGED"
    guid = uuid.uuid4().hex
    first = _make_bcfzip(
        [
            {
                "guid": guid,
                "server_assigned_id": sai,
                "status": "Open",
                "priority": "Normal",
                "labels": [],
            }
        ]
    )
    r1 = await client.post(
        "/api/v1/bcf/import/clashes",
        params={"project_id": project_id},
        headers=owner_auth,
        files={"file": ("a.bcfzip", first, "application/zip")},
    )
    assert r1.status_code == 200
    assert r1.json()["created"] == 1

    second = _make_bcfzip(
        [
            {
                "guid": guid,
                "server_assigned_id": sai,
                "status": "Closed",  # ← changed
                "priority": "Normal",
                "labels": [],
            }
        ]
    )
    r2 = await client.post(
        "/api/v1/bcf/import/clashes",
        params={"project_id": project_id},
        headers=owner_auth,
        files={"file": ("b.bcfzip", second, "application/zip")},
    )
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["updated"] == 1
    assert body["created"] == 0
    # DB-side: status should be ``resolved`` (mapped from BCF "Closed").
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.clash.models import ClashIssue

    async with async_session_factory() as session:
        row = (
            (
                await session.execute(
                    select(ClashIssue)
                    .where(ClashIssue.project_id == uuid.UUID(project_id))
                    .where(ClashIssue.server_assigned_id == sai)
                )
            )
            .scalars()
            .first()
        )
        assert row is not None
        assert row.status == "resolved"


# ── 4. cross-project IDOR ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cross_project_idor_blocked(
    client: AsyncClient,
    viewer_auth: dict[str, str],
    project_id: str,
) -> None:
    """A viewer who does NOT own the project gets a 403 (or 404)."""
    payload = _make_bcfzip(
        [
            {
                "guid": uuid.uuid4().hex,
                "server_assigned_id": "BCF-IDOR",
                "status": "Open",
                "priority": "Normal",
                "labels": [],
            }
        ]
    )
    resp = await client.post(
        "/api/v1/bcf/import/clashes",
        params={"project_id": project_id},
        headers=viewer_auth,
        files={"file": ("idor.bcfzip", payload, "application/zip")},
    )
    assert resp.status_code in (403, 404), resp.text


# ── 5. > 100 MB upload (we simulate the cap with a small reader cap) ─────
#
# We can't actually upload 100 MB through the test client without slowing
# the suite to a crawl, so we verify the router enforces the cap by
# uploading >cap with a temporarily monkey-patched cap.


@pytest.mark.asyncio
async def test_oversize_upload_returns_413(
    client: AsyncClient,
    owner_auth: dict[str, str],
    project_id: str,
    monkeypatch,
) -> None:
    from app.modules.bcf import router as bcf_router

    monkeypatch.setattr(bcf_router, "_BCF_IMPORT_MAX_BYTES", 256)  # 256 B cap

    # Build a legitimate but >cap archive.
    big = _make_bcfzip(
        [
            {
                "guid": uuid.uuid4().hex,
                "server_assigned_id": f"BCF-BIG-{i}",
                "status": "Open",
                "priority": "Normal",
                "labels": [],
            }
            for i in range(4)
        ]
    )
    assert len(big) > 256
    resp = await client.post(
        "/api/v1/bcf/import/clashes",
        params={"project_id": project_id},
        headers=owner_auth,
        files={"file": ("big.bcfzip", big, "application/zip")},
    )
    assert resp.status_code == 413, resp.text


# ── 6. non-zip payload returns 422 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_non_zip_payload_returns_422(
    client: AsyncClient,
    owner_auth: dict[str, str],
    project_id: str,
) -> None:
    resp = await client.post(
        "/api/v1/bcf/import/clashes",
        params={"project_id": project_id},
        headers=owner_auth,
        files={"file": ("bogus.bcfzip", b"NOT-A-ZIP", "application/zip")},
    )
    assert resp.status_code == 422, resp.text


# ── 7. unauthenticated → 401 ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_auth_returns_401(client: AsyncClient, project_id: str) -> None:
    resp = await client.post(
        "/api/v1/bcf/import/clashes",
        params={"project_id": project_id},
        files={"file": ("x.bcfzip", b"PK\x05\x06" + b"\x00" * 18, "application/zip")},
    )
    assert resp.status_code in (401, 403), resp.text


# ── 8. viewer lacking bcf.import → 403 ────────────────────────────────────


@pytest.mark.asyncio
async def test_viewer_lacks_import_permission(
    client: AsyncClient,
    viewer_auth: dict[str, str],
    project_id: str,
) -> None:
    """A viewer-role user lacks ``bcf.import`` (EDITOR-or-higher)."""
    # We don't even need to reach the IDOR check — the RequirePermission
    # gate should fire first. But the viewer ALSO isn't the project owner,
    # so 403 is the correct answer either way.
    payload = _make_bcfzip(
        [
            {
                "guid": uuid.uuid4().hex,
                "server_assigned_id": "BCF-VIEWER",
                "status": "Open",
                "priority": "Normal",
                "labels": [],
            }
        ]
    )
    resp = await client.post(
        "/api/v1/bcf/import/clashes",
        params={"project_id": project_id},
        headers=viewer_auth,
        files={"file": ("v.bcfzip", payload, "application/zip")},
    )
    assert resp.status_code == 403, resp.text
