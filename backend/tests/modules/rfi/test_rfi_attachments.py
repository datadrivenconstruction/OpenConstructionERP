"""‌⁠‍R5 deep-audit tests for the RFI attachment magic-byte gate.

Scope (one happy / one adversarial per behaviour):
    1. ``require_signature`` against ``ALLOWED_ATTACHMENT_TYPES`` accepts
       a real PDF blob (the common "RFI reply with marked-up sheet" case).
    2. The same gate rejects an attacker-controlled "evil.png" whose
       payload is in fact HTML — proving the magic-byte gate, not the
       file extension, is what's authoritative.
    3. The full upload endpoint, mounted on a FastAPI ``TestClient`` with
       dependency overrides for session / auth / project access, accepts
       a real PDF and stores it under the server-derived filename
       (``{rfi_id}_<hex>.pdf``) — proving the path-traversal defence
       holds end-to-end.
    4. The same endpoint rejects the HTML-disguised-as-PNG body with
       HTTP 415 (Unsupported Media Type) and leaves the disk clean.

The suite mirrors ``test_correspondence.py`` so the in-memory SQLite
engine + TestClient combo doesn't need a live database.
"""

from __future__ import annotations

import uuid
from typing import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.dependencies import (
    get_current_user_id,
    get_current_user_payload,
    get_session,
    verify_project_access,
)
from app.modules.projects.models import Project, ProjectMilestone, ProjectWBS
from app.modules.rfi.models import RFI
from app.modules.rfi.router import router as rfi_router
from app.modules.rfi.schemas import RFICreate
from app.modules.rfi.service import RFIService
from app.modules.users.models import APIKey, User

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator:
    """Fresh in-memory SQLite with only the tables this suite needs."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[
                User.__table__,
                APIKey.__table__,
                Project.__table__,
                ProjectWBS.__table__,
                ProjectMilestone.__table__,
                RFI.__table__,
            ],
        )
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield s
    await engine.dispose()


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
        client = TestClient(app)

        pdf_body = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n...rest of file..."
        resp = client.post(
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
        client = TestClient(app)

        fake_png = b"<html><script>alert('xss')</script></html>"
        resp = client.post(
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
        client = TestClient(app)

        resp = client.post(
            f"/v1/rfi/{rfi.id}/attachments/",
            files={"file": ("empty.pdf", b"", "application/pdf")},
        )
        assert resp.status_code == 400, resp.text
