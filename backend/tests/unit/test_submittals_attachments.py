"""R4+R5 hardening tests for the submittals module.

Scope:
    1. Direct attachment upload — magic-byte gate accepts a real PDF and
       rejects a fake-image whose body is HTML / executable bytes.
    2. File-size cap — uploads above ``_MAX_UPLOAD_BYTES`` return 413.
    3. Empty body — 400, no disk write.
    4. Closed submittal — 400 on attachment upload (terminal state).
    5. Submittal-number race — ``IntegrityError`` on the first attempt
       retries with a new number and the second create succeeds.
    6. PATCH escalation — a plain editor trying to PATCH
       ``status=approved`` gets 403, not silent FSM bypass.
    7. Project-scope IDOR — a cross-tenant GET on a submittal returns
       404 without leaking row contents.
    8. Permission registry — every router permission key is registered.
    9. Structured state-change log — ``submittal.state_change`` is emitted
       on submit / review / approve.

Pattern mirrors ``test_correspondence.py`` (magic-byte + CRLF),
``test_compliance_docs.py`` (state + role gates), and ``test_teams.py``
(IDOR) per v4.2.4 conventions.
"""

from __future__ import annotations

import logging
import uuid
from typing import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.audit_log import ActivityLog
from app.database import Base
from app.dependencies import (
    get_current_user_id,
    get_current_user_payload,
    get_session,
    verify_project_access,
)
from app.modules.projects.models import Project, ProjectMilestone, ProjectWBS
from app.modules.submittals.models import Submittal
from app.modules.submittals.router import router as submittals_router
from app.modules.submittals.schemas import SubmittalCreate, SubmittalUpdate
from app.modules.submittals.service import SubmittalService
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
                Submittal.__table__,
                ActivityLog.__table__,
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


def _build_app(
    db_session,
    *,
    caller_id: str,
    role: str = "admin",
) -> FastAPI:
    """Mount the submittals router with auth + session overrides.

    ``role`` controls the simulated caller role — set to ``"editor"`` to
    exercise the MANAGER gate on /review and /approve.
    """
    # Permission registry is process-global; ensure submittals perms are
    # registered before any test mounts the router.
    from app.modules.submittals.permissions import register_submittals_permissions

    register_submittals_permissions()

    app = FastAPI()
    app.include_router(submittals_router, prefix="/v1/submittals")

    async def _session_override():
        yield db_session

    async def _user_override() -> str:
        return caller_id

    async def _project_access_override(project_id, user_id, session) -> None:
        from fastapi import HTTPException
        from fastapi import status as st

        from app.modules.projects.models import Project as _P

        row = await session.get(_P, project_id)
        if row is None:
            raise HTTPException(status_code=st.HTTP_404_NOT_FOUND, detail="Project not found")
        if str(row.owner_id) != str(user_id) and role != "admin":
            raise HTTPException(status_code=st.HTTP_404_NOT_FOUND, detail="Project not found")

    async def _payload_override() -> dict:
        return {"sub": caller_id, "role": role, "permissions": []}

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_current_user_id] = _user_override
    app.dependency_overrides[get_current_user_payload] = _payload_override
    app.dependency_overrides[verify_project_access] = _project_access_override
    return app


# ── 1-4. Direct upload — magic-byte gate, size cap, empty body, closed ──


class TestAttachmentUpload:
    @pytest.mark.asyncio
    async def test_real_pdf_is_accepted(self, db_session, tmp_path, monkeypatch):
        from app.modules.submittals import router as sub_router

        monkeypatch.setattr(sub_router, "ATTACHMENTS_DIR", tmp_path / "attachments")

        owner_id = await _make_user(db_session)
        owner = str(owner_id)
        project_id = await _make_project(db_session, owner_id)
        service = SubmittalService(db_session)
        sub = await service.create_submittal(
            SubmittalCreate(
                project_id=project_id,
                title="Shop drawing — steel",
                submittal_type="shop_drawing",
            ),
            user_id=owner,
        )
        await db_session.commit()

        app = _build_app(db_session, caller_id=owner)
        client = TestClient(app)

        pdf_body = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n...rest of file..."
        resp = client.post(
            f"/v1/submittals/{sub.id}/attachments/upload/",
            files={"file": ("drawing.pdf", pdf_body, "application/pdf")},
        )
        assert resp.status_code == 201, resp.text
        payload = resp.json()
        assert payload["label"] == "drawing.pdf"

    @pytest.mark.asyncio
    async def test_fake_pdf_with_html_payload_is_rejected(self, db_session, tmp_path, monkeypatch):
        from app.modules.submittals import router as sub_router

        monkeypatch.setattr(sub_router, "ATTACHMENTS_DIR", tmp_path / "attachments")

        owner_id = await _make_user(db_session)
        owner = str(owner_id)
        project_id = await _make_project(db_session, owner_id)
        service = SubmittalService(db_session)
        sub = await service.create_submittal(
            SubmittalCreate(
                project_id=project_id,
                title="Product data",
                submittal_type="product_data",
            ),
            user_id=owner,
        )
        await db_session.commit()

        app = _build_app(db_session, caller_id=owner)
        client = TestClient(app)

        # ``.pdf`` extension + ``application/pdf`` Content-Type, but the
        # body is HTML — magic-byte gate rejects (xml not in allow-list).
        fake_pdf = b"<html><script>alert('xss')</script></html>"
        resp = client.post(
            f"/v1/submittals/{sub.id}/attachments/upload/",
            files={"file": ("evil.pdf", fake_pdf, "application/pdf")},
        )
        assert resp.status_code == 415, resp.text
        # And nothing landed on disk.
        d = tmp_path / "attachments"
        if d.exists():
            assert list(d.iterdir()) == []

    @pytest.mark.asyncio
    async def test_disguised_executable_is_rejected(self, db_session, tmp_path, monkeypatch):
        from app.modules.submittals import router as sub_router

        monkeypatch.setattr(sub_router, "ATTACHMENTS_DIR", tmp_path / "attachments")
        owner_id = await _make_user(db_session)
        owner = str(owner_id)
        project_id = await _make_project(db_session, owner_id)
        service = SubmittalService(db_session)
        sub = await service.create_submittal(
            SubmittalCreate(
                project_id=project_id,
                title="Cert",
                submittal_type="certificate",
            ),
            user_id=owner,
        )
        await db_session.commit()
        app = _build_app(db_session, caller_id=owner)
        client = TestClient(app)
        mz_body = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00"
        resp = client.post(
            f"/v1/submittals/{sub.id}/attachments/upload/",
            files={"file": ("invoice.pdf", mz_body, "application/pdf")},
        )
        assert resp.status_code == 415, resp.text

    @pytest.mark.asyncio
    async def test_empty_body_returns_400(self, db_session, tmp_path, monkeypatch):
        from app.modules.submittals import router as sub_router

        monkeypatch.setattr(sub_router, "ATTACHMENTS_DIR", tmp_path / "attachments")
        owner_id = await _make_user(db_session)
        owner = str(owner_id)
        project_id = await _make_project(db_session, owner_id)
        service = SubmittalService(db_session)
        sub = await service.create_submittal(
            SubmittalCreate(
                project_id=project_id,
                title="X",
                submittal_type="sample",
            ),
            user_id=owner,
        )
        await db_session.commit()
        app = _build_app(db_session, caller_id=owner)
        client = TestClient(app)
        resp = client.post(
            f"/v1/submittals/{sub.id}/attachments/upload/",
            files={"file": ("empty.pdf", b"", "application/pdf")},
        )
        assert resp.status_code == 400, resp.text

    @pytest.mark.asyncio
    async def test_oversize_file_returns_413(self, db_session, tmp_path, monkeypatch):
        from app.modules.submittals import router as sub_router

        monkeypatch.setattr(sub_router, "ATTACHMENTS_DIR", tmp_path / "attachments")
        # Drop the cap to 64 bytes for the test so we don't push 50 MB
        # through the TestClient just to assert one branch.
        monkeypatch.setattr(sub_router, "_MAX_UPLOAD_BYTES", 64)
        owner_id = await _make_user(db_session)
        owner = str(owner_id)
        project_id = await _make_project(db_session, owner_id)
        service = SubmittalService(db_session)
        sub = await service.create_submittal(
            SubmittalCreate(
                project_id=project_id,
                title="Big",
                submittal_type="shop_drawing",
            ),
            user_id=owner,
        )
        await db_session.commit()
        app = _build_app(db_session, caller_id=owner)
        client = TestClient(app)
        # Real PDF magic so the size check (not the magic check) trips.
        big_pdf = b"%PDF-1.7\n" + b"A" * 200
        resp = client.post(
            f"/v1/submittals/{sub.id}/attachments/upload/",
            files={"file": ("big.pdf", big_pdf, "application/pdf")},
        )
        assert resp.status_code == 413, resp.text

    @pytest.mark.asyncio
    async def test_closed_submittal_rejects_attachment(self, db_session, tmp_path, monkeypatch):
        from app.modules.submittals import router as sub_router

        monkeypatch.setattr(sub_router, "ATTACHMENTS_DIR", tmp_path / "attachments")
        owner_id = await _make_user(db_session)
        owner = str(owner_id)
        project_id = await _make_project(db_session, owner_id)
        service = SubmittalService(db_session)
        sub = await service.create_submittal(
            SubmittalCreate(
                project_id=project_id,
                title="Done",
                submittal_type="warranty",
            ),
            user_id=owner,
        )
        # Force terminal state directly on the row (bypassing FSM for
        # the fixture; the gate we're testing is on the upload path).
        sub.status = "closed"
        await db_session.commit()
        app = _build_app(db_session, caller_id=owner)
        client = TestClient(app)
        pdf_body = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
        resp = client.post(
            f"/v1/submittals/{sub.id}/attachments/upload/",
            files={"file": ("late.pdf", pdf_body, "application/pdf")},
        )
        assert resp.status_code == 400, resp.text
        assert "closed" in resp.text.lower()


# ── 5. Submittal-number race → 409 / retry ───────────────────────────────


class TestNumberCollision:
    @pytest.mark.asyncio
    async def test_integrity_error_triggers_retry(self, db_session, monkeypatch):
        """Simulate a collision on the first attempt; the service must
        retry and the second attempt must succeed with the next number.
        """
        from sqlalchemy.exc import IntegrityError

        from app.modules.submittals.repository import SubmittalRepository

        owner_id = await _make_user(db_session)
        owner = str(owner_id)
        project_id = await _make_project(db_session, owner_id)

        service = SubmittalService(db_session)
        # First call returns "SUB-001"; the .create() patched below
        # raises IntegrityError on the first invocation only.
        original_create = SubmittalRepository.create
        calls = {"n": 0}

        async def flaky_create(self, submittal):  # type: ignore[no-untyped-def]
            calls["n"] += 1
            if calls["n"] == 1:
                raise IntegrityError("simulated", {}, Exception("uq"))
            return await original_create(self, submittal)

        monkeypatch.setattr(SubmittalRepository, "create", flaky_create)

        sub = await service.create_submittal(
            SubmittalCreate(
                project_id=project_id,
                title="Race",
                submittal_type="sample",
            ),
            user_id=owner,
        )
        # Retry succeeded — the second number assignment used.
        assert sub.submittal_number.startswith("SUB-")
        assert calls["n"] >= 2

    @pytest.mark.asyncio
    async def test_unresolvable_collision_returns_409(self, db_session, monkeypatch):
        from fastapi import HTTPException
        from sqlalchemy.exc import IntegrityError

        from app.modules.submittals.repository import SubmittalRepository

        owner_id = await _make_user(db_session)
        owner = str(owner_id)
        project_id = await _make_project(db_session, owner_id)
        service = SubmittalService(db_session)

        async def always_collide(self, submittal):  # type: ignore[no-untyped-def]
            raise IntegrityError("simulated", {}, Exception("uq"))

        monkeypatch.setattr(SubmittalRepository, "create", always_collide)

        with pytest.raises(HTTPException) as exc_info:
            await service.create_submittal(
                SubmittalCreate(
                    project_id=project_id,
                    title="Forever",
                    submittal_type="sample",
                ),
                user_id=owner,
            )
        assert exc_info.value.status_code == 409


# ── 6. PATCH FSM escalation guard ────────────────────────────────────────


class TestPatchEscalationGuard:
    @pytest.mark.asyncio
    async def test_patch_to_approved_is_forbidden(self, db_session):
        """An editor with ``submittals.update`` cannot bypass MANAGER
        gate by PATCHing ``status=approved`` directly."""
        from fastapi import HTTPException

        owner_id = await _make_user(db_session)
        owner = str(owner_id)
        project_id = await _make_project(db_session, owner_id)
        service = SubmittalService(db_session)
        sub = await service.create_submittal(
            SubmittalCreate(
                project_id=project_id,
                title="Sneaky",
                submittal_type="sample",
            ),
            user_id=owner,
        )
        # Force a state from which "approved" is a *valid* FSM transition,
        # so we hit the role-gate branch (not the transition-allowed
        # branch). ``submitted -> approved`` is in the FSM map.
        sub.status = "submitted"
        await db_session.commit()

        with pytest.raises(HTTPException) as exc_info:
            await service.update_submittal(
                sub.id,
                SubmittalUpdate(status="approved"),
            )
        assert exc_info.value.status_code == 403
        assert "approve" in str(exc_info.value.detail).lower()

    @pytest.mark.asyncio
    async def test_patch_to_under_review_is_allowed(self, db_session):
        """Benign in-flight transitions still work via PATCH."""
        owner_id = await _make_user(db_session)
        owner = str(owner_id)
        project_id = await _make_project(db_session, owner_id)
        service = SubmittalService(db_session)
        sub = await service.create_submittal(
            SubmittalCreate(
                project_id=project_id,
                title="Live",
                submittal_type="sample",
            ),
            user_id=owner,
        )
        sub.status = "submitted"
        await db_session.commit()

        updated = await service.update_submittal(
            sub.id,
            SubmittalUpdate(status="under_review"),
        )
        assert updated.status == "under_review"


# ── 7. Project-scope IDOR ────────────────────────────────────────────────


class TestProjectScopeIDOR:
    @pytest.mark.asyncio
    async def test_cross_tenant_get_returns_404(self, db_session):
        victim_id = await _make_user(db_session, email="victim@x.com")
        attacker_id = await _make_user(db_session, email="attacker@x.com")
        victim_project = await _make_project(db_session, victim_id)
        service = SubmittalService(db_session)
        victim_sub = await service.create_submittal(
            SubmittalCreate(
                project_id=victim_project,
                title="Confidential change-order rider",
                submittal_type="shop_drawing",
            ),
            user_id=str(victim_id),
        )
        await db_session.commit()

        # Caller is the attacker, role=editor so admin-bypass doesn't kick.
        app = _build_app(db_session, caller_id=str(attacker_id), role="editor")
        client = TestClient(app)
        resp = client.get(f"/v1/submittals/{victim_sub.id}")
        assert resp.status_code == 404, resp.text
        assert "Confidential" not in resp.text


# ── 8. Permission registry contract ──────────────────────────────────────


def test_permission_registry_has_all_four_submittals_permissions() -> None:
    from app.core.permissions import permission_registry
    from app.modules.submittals.permissions import register_submittals_permissions

    register_submittals_permissions()
    keys = set(permission_registry.list_all().keys())
    for verb in ("create", "read", "update", "delete"):
        assert f"submittals.{verb}" in keys, f"submittals.{verb} not registered — router calls would 403 at runtime"


# ── 9. Structured state-change log ───────────────────────────────────────


@pytest.mark.asyncio
async def test_submit_emits_structured_state_change_log(db_session, caplog) -> None:
    """The submit handler must emit a ``submittal.state_change`` payload
    so the log shipper can index from/to/actor for the cycle dashboard.
    """
    owner_id = await _make_user(db_session)
    owner = str(owner_id)
    project_id = await _make_project(db_session, owner_id)
    service = SubmittalService(db_session)
    sub = await service.create_submittal(
        SubmittalCreate(
            project_id=project_id,
            title="Log me",
            submittal_type="sample",
            reviewer_id="rev-1",
        ),
        user_id=owner,
    )
    await db_session.commit()

    with caplog.at_level(logging.INFO, logger="app.modules.submittals.service"):
        await service.submit_submittal(sub.id)

    state_events = [r for r in caplog.records if "submittal.state_change" in r.getMessage()]
    assert state_events, "no structured state-change log emitted on submit"
    msg = state_events[-1].getMessage()
    assert "'from_status': 'draft'" in msg
    assert "'to_status': 'submitted'" in msg
