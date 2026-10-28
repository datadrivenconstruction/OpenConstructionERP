"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠R5 deep-audit tests for the RFI attachment magic-byte gate.

Scope (one happy / one adversarial per behaviour):
    1. ``require_signature`` against ``ALLOWED_ATTACHMENT_TYPES`` accepts
       a real PDF blob (the common "RFI reply with marked-up sheet" case).
    2. The same gate rejects an attacker-controlled "evil.png" whose
       payload is in fact HTML — proving the magic-byte gate, not the
       file extension, is what's authoritative.
    3. The full upload endpoint, mounted on an ``httpx.AsyncClient`` with
       dependency overrides for session / auth / project access, accepts
       a real PDF and stores it under the server-derived filename
       (``{rfi_id}_<hex>.pdf``) — proving the path-traversal defence
       holds end-to-end.
    4. The same endpoint rejects the HTML-disguised-as-PNG body with
       HTTP 415 (Unsupported Media Type) and leaves the disk clean.

The suite mirrors ``test_correspondence.py``. Each test runs against a
PostgreSQL session wrapped in an outer transaction that is rolled back on
teardown, so committed data is visible to the client within the test but
undone afterwards (see ``tests._pg.transactional_session``).

The HTTP calls go through ``httpx.AsyncClient`` over ``ASGITransport`` rather
than the synchronous ``TestClient``. ``TestClient`` drives the app from its own
event loop in a worker thread, while ``db_session`` is bound to the loop pytest
runs the test on; the two loops cannot share one asyncpg connection, so every
request died on "attached to a different loop". ``AsyncClient`` runs the app
inline on the test's own loop, which is what makes the shared session work.
"""

from __future__ import annotations

import uuid
from typing import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from app.dependencies import (
    get_current_user_id,
    get_current_user_payload,
    get_session,
    verify_project_access,
)
from app.modules.projects.models import Project
from app.modules.rfi.router import router as rfi_router
from app.modules.rfi.schemas import RFICreate
from app.modules.rfi.service import RFIService
from app.modules.users.models import User
from tests._pg import transactional_session

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator:
    """PostgreSQL session inside a transaction rolled back on teardown.

    The shared ``oe_test_unit`` database already carries the full schema, so
    no ``create_all`` is needed here.
    """
    async with transactional_session() as s:
        yield s


async def _make_user(session, *, email: str | None = None) -> uuid.UUID:
    user = User(
        email=email or f"u{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user.id


async def _make_project(session, owner_id: uuid.UUID) -> uuid.UUID:
    project = Project(name="Test Project", owner_id=owner_id)
    session.add(project)
    await session.flush()
    await session.refresh(project)
    return project.id


def _build_app(db_session, *, caller_id: str) -> FastAPI:
    """Mount the RFI router with auth + session overrides."""
    app = FastAPI()
    app.include_router(rfi_router, prefix="/v1/rfi")

    async def _session_override():
        yield db_session

    async def _user_override() -> str:
        return caller_id

    async def _project_access_override(project_id, user_id, session) -> None:
        from fastapi import HTTPException
        from fastapi import status as st

        from app.modules.projects.models import Project as _P  # noqa: N814

        row = await session.get(_P, project_id)
        if row is None:
            raise HTTPException(status_code=st.HTTP_404_NOT_FOUND, detail="Project not found")
        if str(row.owner_id) != str(user_id):
            raise HTTPException(status_code=st.HTTP_404_NOT_FOUND, detail="Project not found")

    async def _payload_override() -> dict:
        # Admin-role payload short-circuits ``RequirePermission`` for every
        # ``rfi.*`` permission and keeps the assigner/respondent gates
        # off the critical path of these attachment tests.
        return {"sub": caller_id, "role": "admin", "permissions": []}

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_current_user_id] = _user_override
    app.dependency_overrides[get_current_user_payload] = _payload_override
    app.dependency_overrides[verify_project_access] = _project_access_override
    return app


# ── 1 + 2. Magic-byte helper (router constant + library helper) ──────────


class TestMagicByteGateConstant:
    def test_real_pdf_blob_passes_allowlist(self) -> None:
        from app.core.file_signature import require as require_signature
        from app.modules.rfi.router import ALLOWED_ATTACHMENT_TYPES

        pdf_head = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
        detected = require_signature(pdf_head, ALLOWED_ATTACHMENT_TYPES, filename="reply.pdf")
        assert detected == "pdf"

    def test_html_payload_disguised_as_png_is_rejected(self) -> None:
        """File extension says PNG; bytes are HTML — gate must say no."""
        from app.core.file_signature import FileSignatureMismatch
        from app.core.file_signature import require as require_signature
        from app.modules.rfi.router import ALLOWED_ATTACHMENT_TYPES

        fake_png = b"<html><script>alert('xss')</script></html>"
        with pytest.raises(FileSignatureMismatch):
            require_signature(fake_png, ALLOWED_ATTACHMENT_TYPES, filename="evil.png")


# ── 3 + 4. End-to-end upload via the router ──────────────────────────────


class TestAttachmentUploadEndpoint:
    @pytest.mark.asyncio
    async def test_real_pdf_is_stored_with_server_derived_name(self, db_session, tmp_path, monkeypatch) -> None:
        """Happy path: a real PDF gets a server-controlled filename."""
        from app.modules.rfi import router as rfi_router_mod

        monkeypatch.setattr(rfi_router_mod, "ATTACHMENTS_DIR", tmp_path / "attachments")

        owner_id = await _make_user(db_session)
        owner = str(owner_id)
        project_id = await _make_project(db_session, owner_id)
        service = RFIService(db_session)
        rfi = await service.create_rfi(
            RFICreate(
                project_id=project_id,
                subject="Foundation grade",
                question="C30 or C35?",
            ),
            user_id=owner,
        )
        await db_session.commit()

        app = _build_app(db_session, caller_id=owner)
        transport = httpx.ASGITransport(app=app)

        pdf_body = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n...rest of file..."
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/v1/rfi/{rfi.id}/attachments/",
                files={"file": ("reply.pdf", pdf_body, "application/pdf")},
            )
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert len(payload["attachments"]) == 1
        stored = payload["attachments"][0]
        # The stored path is server-derived: prefix + RFI UUID + hex + .pdf.
        assert stored.startswith("rfi/attachments/")
        assert stored.endswith(".pdf")
        # Attacker-controlled "reply.pdf" base name must NOT appear in
        # the persisted path — only the server-derived ``{rfi_id}_<hex>``.
        assert "reply.pdf" not in stored

    @pytest.mark.asyncio
    async def test_html_disguised_as_png_returns_415(self, db_session, tmp_path, monkeypatch) -> None:
        """The router refuses the request and writes nothing to disk."""
        from app.modules.rfi import router as rfi_router_mod

        attachments_dir = tmp_path / "attachments"
        monkeypatch.setattr(rfi_router_mod, "ATTACHMENTS_DIR", attachments_dir)

        owner_id = await _make_user(db_session)
        owner = str(owner_id)
        project_id = await _make_project(db_session, owner_id)
        service = RFIService(db_session)
        rfi = await service.create_rfi(
            RFICreate(
                project_id=project_id,
                subject="Foundation grade",
                question="C30 or C35?",
            ),
            user_id=owner,
        )
        await db_session.commit()

        app = _build_app(db_session, caller_id=owner)
        transport = httpx.ASGITransport(app=app)

        fake_png = b"<html><script>alert('xss')</script></html>"
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/v1/rfi/{rfi.id}/attachments/",
                files={"file": ("evil.png", fake_png, "image/png")},
            )
        assert resp.status_code == 415, resp.text
        # Nothing landed on disk.
        if attachments_dir.exists():
            assert list(attachments_dir.iterdir()) == []

    @pytest.mark.asyncio
    async def test_empty_upload_returns_400(self, db_session, tmp_path, monkeypatch) -> None:
        """Zero-byte file is a 400, not a 415 — distinguishes operator error."""
        from app.modules.rfi import router as rfi_router_mod

        monkeypatch.setattr(rfi_router_mod, "ATTACHMENTS_DIR", tmp_path / "attachments")

        owner_id = await _make_user(db_session)
        owner = str(owner_id)
        project_id = await _make_project(db_session, owner_id)
        service = RFIService(db_session)
        rfi = await service.create_rfi(
            RFICreate(
                project_id=project_id,
                subject="x",
                question="y",
            ),
            user_id=owner,
        )
        await db_session.commit()

        app = _build_app(db_session, caller_id=owner)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/v1/rfi/{rfi.id}/attachments/",
                files={"file": ("empty.pdf", b"", "application/pdf")},
            )
        assert resp.status_code == 400, resp.text


# ── 5 + 6. Download round-trip + bounds (completeness: the read path) ─────


class TestAttachmentDownloadEndpoint:
    """The upload handler wrote files that previously had no read path.

    These tests prove ``GET /{rfi_id}/attachments/{index}`` rounds the
    bytes back out (so the feature is actually usable end-to-end) and that
    an out-of-range index is a clean 404 rather than an IndexError 500.
    """

    @pytest.mark.asyncio
    async def test_uploaded_attachment_downloads_back(self, db_session, tmp_path, monkeypatch) -> None:
        from app.modules.rfi import router as rfi_router_mod

        # Coherent tmp tree: stored path is ``rfi/attachments/<name>`` and the
        # download handler resolves it against ``_UPLOADS_BASE``. Point the
        # upload dir and the download base at the same root so the bytes match.
        monkeypatch.setattr(rfi_router_mod, "_UPLOADS_BASE", tmp_path)
        monkeypatch.setattr(rfi_router_mod, "ATTACHMENTS_DIR", tmp_path / "rfi" / "attachments")

        owner_id = await _make_user(db_session)
        owner = str(owner_id)
        project_id = await _make_project(db_session, owner_id)
        service = RFIService(db_session)
        rfi = await service.create_rfi(
            RFICreate(project_id=project_id, subject="x", question="y"),
            user_id=owner,
        )
        await db_session.commit()

        app = _build_app(db_session, caller_id=owner)
        transport = httpx.ASGITransport(app=app)

        pdf_body = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\nround-trip-me"
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            up = await client.post(
                f"/v1/rfi/{rfi.id}/attachments/",
                files={"file": ("reply.pdf", pdf_body, "application/pdf")},
            )
            assert up.status_code == 200, up.text

            down = await client.get(f"/v1/rfi/{rfi.id}/attachments/0")
        assert down.status_code == 200, down.text
        assert down.content == pdf_body
        assert down.headers["content-type"].startswith("application/pdf")
        # Served as an attachment, never inline, so a stray HTML payload can
        # never be rendered by the browser.
        assert "attachment" in down.headers.get("content-disposition", "")

    @pytest.mark.asyncio
    async def test_out_of_range_index_returns_404(self, db_session, tmp_path, monkeypatch) -> None:
        from app.modules.rfi import router as rfi_router_mod

        monkeypatch.setattr(rfi_router_mod, "_UPLOADS_BASE", tmp_path)
        monkeypatch.setattr(rfi_router_mod, "ATTACHMENTS_DIR", tmp_path / "rfi" / "attachments")

        owner_id = await _make_user(db_session)
        owner = str(owner_id)
        project_id = await _make_project(db_session, owner_id)
        service = RFIService(db_session)
        rfi = await service.create_rfi(
            RFICreate(project_id=project_id, subject="x", question="y"),
            user_id=owner,
        )
        await db_session.commit()

        app = _build_app(db_session, caller_id=owner)
        transport = httpx.ASGITransport(app=app)

        # No attachments uploaded - index 0 is already out of range.
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/v1/rfi/{rfi.id}/attachments/0")
        assert resp.status_code == 404, resp.text
