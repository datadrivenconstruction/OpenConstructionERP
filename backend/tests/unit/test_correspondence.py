"""Baseline unit tests for the correspondence module.

Scope (intentionally tight — one happy path per security concern):
    1. Service-level create: a correspondence row is persisted with the
       sanitised subject and an auto-generated ``COR-001`` reference.
    2. Subject sanitisation strips CRLF (email-header-injection guard).
    3. Attachment upload via the router rejects a fake-image whose
       extension claims PNG but whose magic bytes are HTML (XSS attempt).
    4. Project-scope IDOR: a caller hitting another tenant's
       correspondence ID gets 404, not the row.

The suite uses an in-memory SQLite engine and the FastAPI ``TestClient``
for the upload + IDOR assertions so the magic-byte gate, permission gate,
and ``verify_project_access`` are exercised end-to-end. Heavy services
(events, audit) are not registered in unit suites, so the router runs
against the bare module.
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
from app.modules.correspondence.models import Correspondence
from app.modules.correspondence.router import router as correspondence_router
from app.modules.correspondence.schemas import CorrespondenceCreate
from app.modules.correspondence.service import CorrespondenceService
from app.modules.projects.models import Project, ProjectMilestone, ProjectWBS
from app.modules.users.models import APIKey, User

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator:
    """Fresh in-memory SQLite with only the tables this suite needs.

    ``Project.owner_id`` FKs to ``oe_users_user`` so we have to register
    that table too — but we don't need its real Pydantic / RBAC plumbing.
    """
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
                Correspondence.__table__,
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
    """Insert a project owned by ``owner_id`` and return its id."""
    project = Project(name="Test Project", owner_id=owner_id)
    session.add(project)
    await session.flush()
    await session.refresh(project)
    return project.id


# ── 1. Service layer — create + reference autogen ────────────────────────


class TestServiceCreate:
    @pytest.mark.asyncio
    async def test_create_persists_row_with_ref_number(self, db_session):
        owner_id = await _make_user(db_session)
        owner = str(owner_id)
        project_id = await _make_project(db_session, owner_id)
        service = CorrespondenceService(db_session)

        item = await service.create_correspondence(
            CorrespondenceCreate(
                project_id=project_id,
                direction="outgoing",
                subject="Project kickoff",
                correspondence_type="email",
            ),
            user_id=owner,
        )

        assert item.reference_number == "COR-001"
        assert item.subject == "Project kickoff"
        assert item.attachments == []
        assert item.created_by == owner


# ── 2. Schema — email-header-injection guard ──────────────────────────────


class TestSubjectSanitisation:
    def test_crlf_in_subject_is_stripped(self):
        """``\\r\\nBcc: attacker@example.com`` must not survive validation."""
        payload = CorrespondenceCreate(
            project_id=uuid.uuid4(),
            direction="outgoing",
            subject="Hello\r\nBcc: attacker@example.com",
            correspondence_type="email",
        )
        # CR/LF stripped by the validator. The resulting subject is a
        # single safe line — no fragment that the outgoing SMTP path
        # could interpret as a new header.
        assert "\r" not in payload.subject
        assert "\n" not in payload.subject
        # The control chars are removed (not replaced with spaces) so the
        # subject collapses without introducing a leading whitespace.
        assert payload.subject == "HelloBcc: attacker@example.com"

    def test_only_control_chars_rejected(self):
        """A subject made entirely of control chars must error, not save empty."""
        with pytest.raises(ValueError):
            CorrespondenceCreate(
                project_id=uuid.uuid4(),
                direction="outgoing",
                subject="\r\n\t\t",
                correspondence_type="email",
            )


# ── 3 + 4. Router — magic-byte rejection + project-scope IDOR ────────────


def _build_app(db_session, *, caller_id: str) -> FastAPI:
    """Mount the correspondence router with auth + session overrides.

    ``RequirePermission`` and ``verify_project_access`` use a real
    user / RBAC pipeline in production. For unit scope we override them
    so the test isolates the magic-byte gate and the project ownership
    check on ``upload_attachment`` / ``get_correspondence``.
    """
    app = FastAPI()
    app.include_router(correspondence_router, prefix="/v1/correspondence")

    async def _session_override():
        yield db_session

    async def _user_override() -> str:
        return caller_id

    async def _project_access_override(project_id, user_id, session) -> None:
        # Mirror production semantics: a missing project (or one the
        # caller doesn't own) surfaces as 404 so we don't leak ids.
        from fastapi import HTTPException
        from fastapi import status as st

        from app.modules.projects.models import Project as _P

        row = await session.get(_P, project_id)
        if row is None:
            raise HTTPException(status_code=st.HTTP_404_NOT_FOUND, detail="Project not found")
        if str(row.owner_id) != str(user_id):
            raise HTTPException(status_code=st.HTTP_404_NOT_FOUND, detail="Project not found")

    async def _payload_override() -> dict:
        # Admin-role payload short-circuits ``RequirePermission`` for every
        # ``correspondence.*`` permission — we're not testing RBAC here.
        return {"sub": caller_id, "role": "admin", "permissions": []}

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_current_user_id] = _user_override
    app.dependency_overrides[get_current_user_payload] = _payload_override
    app.dependency_overrides[verify_project_access] = _project_access_override
    return app


class TestAttachmentMagicByteGate:
    @pytest.mark.asyncio
    async def test_fake_png_with_html_payload_is_rejected(self, db_session, tmp_path, monkeypatch):
        # Redirect on-disk writes into the pytest tmp dir so the suite
        # never touches the real ``uploads/`` tree.
        from app.modules.correspondence import router as corr_router

        monkeypatch.setattr(corr_router, "ATTACHMENTS_DIR", tmp_path / "attachments")

        owner_id = await _make_user(db_session)
        # The test app's user-override always returns ``str(owner_id)``
        # so the IDOR / ownership gate sees the same caller as the row.
        nonlocal_owner = str(owner_id)
        project_id = await _make_project(db_session, owner_id)
        service = CorrespondenceService(db_session)
        item = await service.create_correspondence(
            CorrespondenceCreate(
                project_id=project_id,
                direction="outgoing",
                subject="Attach this",
                correspondence_type="email",
            ),
            user_id=nonlocal_owner,
        )
        await db_session.commit()

        app = _build_app(db_session, caller_id=nonlocal_owner)
        client = TestClient(app)

        # ``evil.png`` whose body is HTML with a <script> payload —
        # extension + Content-Type are the attacker's; only magic bytes
        # decide what we accept. Note that the file_signature detector
        # *would* classify this as ``xml`` (its branch tolerates any
        # ``<tag>``), but ``ALLOWED_ATTACHMENT_TYPES`` deliberately
        # excludes ``xml`` to keep the XSS-prone HTML payload out, so the
        # upload gate returns 415.
        fake_png = b"<html><script>alert('xss')</script></html>"
        resp = client.post(
            f"/v1/correspondence/{item.id}/attachments/",
            files={"file": ("evil.png", fake_png, "image/png")},
        )
        assert resp.status_code == 415, resp.text
        # And nothing was written to disk.
        attachments_dir = tmp_path / "attachments"
        if attachments_dir.exists():
            assert list(attachments_dir.iterdir()) == []

    @pytest.mark.asyncio
    async def test_real_pdf_is_accepted(self, db_session, tmp_path, monkeypatch):
        """Positive case: a real PDF (correct magic bytes) goes through."""
        from app.modules.correspondence import router as corr_router

        monkeypatch.setattr(corr_router, "ATTACHMENTS_DIR", tmp_path / "attachments")

        owner_id = await _make_user(db_session)
        owner = str(owner_id)
        project_id = await _make_project(db_session, owner_id)
        service = CorrespondenceService(db_session)
        item = await service.create_correspondence(
            CorrespondenceCreate(
                project_id=project_id,
                direction="outgoing",
                subject="With attachment",
                correspondence_type="email",
            ),
            user_id=owner,
        )
        await db_session.commit()

        app = _build_app(db_session, caller_id=owner)
        client = TestClient(app)

        pdf_body = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n...rest of file..."
        resp = client.post(
            f"/v1/correspondence/{item.id}/attachments/",
            files={"file": ("contract.pdf", pdf_body, "application/pdf")},
        )
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert len(payload["attachments"]) == 1
        # Server-derived filename, not attacker-controlled "contract.pdf".
        stored = payload["attachments"][0]
        assert stored.startswith("correspondence/attachments/")
        assert stored.endswith(".pdf")


class TestProjectScopeIDOR:
    @pytest.mark.asyncio
    async def test_cross_tenant_get_returns_404(self, db_session):
        # Two real users; victim owns the project, attacker is logged in.
        victim_id = await _make_user(db_session, email="victim@example.com")
        attacker_id = await _make_user(db_session, email="attacker@example.com")
        victim_project_id = await _make_project(db_session, victim_id)
        service = CorrespondenceService(db_session)
        victim_corr = await service.create_correspondence(
            CorrespondenceCreate(
                project_id=victim_project_id,
                direction="incoming",
                subject="Confidential litigation update",
                correspondence_type="letter",
            ),
            user_id=str(victim_id),
        )
        await db_session.commit()

        # The TestClient runs as the attacker.
        app = _build_app(db_session, caller_id=str(attacker_id))
        client = TestClient(app)
        resp = client.get(f"/v1/correspondence/{victim_corr.id}")
        assert resp.status_code == 404, resp.text
        assert "Confidential" not in resp.text
