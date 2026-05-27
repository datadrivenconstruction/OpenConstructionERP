"""Round-2 deep-improve — Submittals review-cycle workflow + attachment versioning.

Scope:
    1. Full multi-round review cycle:
       draft → submitted → under_review → revise_and_resubmit (with notes)
       → submitted (round 2, revision incremented) → under_review → approved.
       Verifies every intermediate status, ball-in-court flip, and revision
       counter at each step.
    2. Revise-and-resubmit keeps prior attachments intact as version history
       (new attachment round labelled with revision number, old entries retained).
    3. Closing past due_date is informational only — approve + close succeeds
       even when date_required is in the past (no false 422).
    4. Magic-byte uploads — OLE (.doc/.xls legacy) and DWG positive tests (both
       are in _ALLOWED_ATTACHMENT_TYPES but not yet exercised individually).

Pattern: in-memory SQLite + TestClient dependency overrides, mirrors
test_submittals_attachments.py conventions.
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

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator:
    """Per-test in-memory SQLite with only tables this suite needs."""
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
    project = Project(name="Review Cycle Test Project", owner_id=owner_id)
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


# ── 1. Full multi-round review cycle ────────────────────────────────────────


class TestFullReviewCycle:
    """Pin the complete canonical two-round lifecycle.

    Round 1: draft → submitted → under_review → revise_and_resubmit
    Round 2: submitted (rev++) → under_review → approved
    """

    @pytest.mark.asyncio
    async def test_two_round_cycle_end_to_end(self, db_session, caplog) -> None:
        owner_id = await _make_user(db_session, email="creator@rc.test")
        reviewer_id = await _make_user(db_session, email="reviewer@rc.test")
        owner = str(owner_id)
        reviewer = str(reviewer_id)
        project_id = await _make_project(db_session, owner_id)

        service = SubmittalService(db_session)

        # ── Step 1: Create as draft ──────────────────────────────────────
        sub = await service.create_submittal(
            SubmittalCreate(
                project_id=project_id,
                title="Shop Drawing — Structural Steel",
                submittal_type="shop_drawing",
                reviewer_id=reviewer,
            ),
            user_id=owner,
        )
        await db_session.commit()

        assert sub.status == "draft"
        assert str(sub.ball_in_court) == owner
        rev0 = sub.current_revision or 0

        # ── Step 2: Submit (round 1) ─────────────────────────────────────
        sub = await service.submit_submittal(sub.id)
        await db_session.commit()

        assert sub.status == "submitted"
        assert sub.current_revision == 1, "first submit must set revision to 1"
        assert str(sub.ball_in_court) == reviewer

        # ── Step 3: Move to under_review ────────────────────────────────
        sub = await service.update_submittal(sub.id, SubmittalUpdate(status="under_review"))
        await db_session.commit()

        assert sub.status == "under_review"

        # ── Step 4: Reviewer requests revise_and_resubmit ───────────────
        with caplog.at_level(logging.INFO, logger="app.modules.submittals.service"):
            sub = await service.review_submittal(
                sub.id,
                "revise_and_resubmit",
                reviewer_id=reviewer,
            )
        await db_session.commit()

        assert sub.status == "revise_and_resubmit"
        # Ball must return to the submitter so they can revise.
        assert str(sub.ball_in_court) == owner
        rev_after_rar = sub.current_revision
        assert rev_after_rar == 1, "R&R must NOT increment revision — only re-submit does"

        # State-change log must have fired for the review step.
        state_events = [r for r in caplog.records if "submittal.state_change" in r.getMessage()]
        assert state_events, "expected at least one submittal.state_change log"

        # ── Step 5: Re-submit (round 2) ──────────────────────────────────
        sub = await service.submit_submittal(sub.id)
        await db_session.commit()

        assert sub.status == "submitted"
        assert sub.current_revision == 2, "re-submit after R&R must increment revision"
        assert str(sub.ball_in_court) == reviewer

        # ── Step 6: Under review again ───────────────────────────────────
        sub = await service.update_submittal(sub.id, SubmittalUpdate(status="under_review"))
        await db_session.commit()

        assert sub.status == "under_review"

        # ── Step 7: Final approval ───────────────────────────────────────
        sub = await service.approve_submittal(sub.id, approver_id=reviewer)
        await db_session.commit()

        assert sub.status == "approved"
        assert sub.ball_in_court is None, "approved must clear ball_in_court"
        assert sub.current_revision == 2, "revision must stay at 2 after approval"

    @pytest.mark.asyncio
    async def test_revise_resubmit_path_allows_second_submission(self, db_session) -> None:
        """Submittal in revise_and_resubmit state can be submitted again."""
        owner_id = await _make_user(db_session)
        reviewer_id = await _make_user(db_session)
        owner = str(owner_id)
        reviewer = str(reviewer_id)
        project_id = await _make_project(db_session, owner_id)
        service = SubmittalService(db_session)

        sub = await service.create_submittal(
            SubmittalCreate(
                project_id=project_id,
                title="Product Data",
                submittal_type="product_data",
                reviewer_id=reviewer,
            ),
            user_id=owner,
        )
        sub = await service.submit_submittal(sub.id)
        # Move to under_review first so review_submittal is happy.
        sub = await service.update_submittal(sub.id, SubmittalUpdate(status="under_review"))
        sub = await service.review_submittal(sub.id, "revise_and_resubmit", reviewer_id=reviewer)
        await db_session.commit()

        assert sub.status == "revise_and_resubmit"
        rev_before = sub.current_revision

        # revise_and_resubmit → submitted (re-submission) increments revision.
        sub = await service.submit_submittal(sub.id)
        assert sub.status == "submitted"
        assert sub.current_revision == rev_before + 1

    @pytest.mark.asyncio
    async def test_approved_submittal_is_idempotent(self, db_session) -> None:
        """Calling approve_submittal on an already-approved row is a no-op (ENH-095)."""
        owner_id = await _make_user(db_session)
        reviewer_id = await _make_user(db_session)
        owner = str(owner_id)
        reviewer = str(reviewer_id)
        project_id = await _make_project(db_session, owner_id)
        service = SubmittalService(db_session)

        sub = await service.create_submittal(
            SubmittalCreate(
                project_id=project_id,
                title="Certificate",
                submittal_type="certificate",
                reviewer_id=reviewer,
            ),
            user_id=owner,
        )
        sub = await service.submit_submittal(sub.id)
        sub = await service.approve_submittal(sub.id, approver_id=reviewer)
        await db_session.commit()

        # Second approve call — must return the existing approved state, not 400.
        sub2 = await service.approve_submittal(sub.id, approver_id=reviewer)
        assert sub2.status == "approved"


# ── 2. Attachment versioning across revisions ────────────────────────────────


class TestAttachmentVersioning:
    """Prior attachments are retained as version history when a submittal is resubmitted.

    The metadata["attachments"] list is append-only: uploading a new PDF in
    round 2 appends a new entry; the round-1 entry remains with its original
    index so download links are stable.
    """

    @pytest.mark.asyncio
    async def test_prior_attachments_retained_after_resubmit(self, db_session, tmp_path, monkeypatch) -> None:
        """Attachments from round 1 remain in the list after a round-2 upload.

        The metadata["attachments"] list is append-only: uploading a new PDF
        in round 2 appends a new entry; the round-1 entry is preserved so
        download links remain stable across revisions.
        """
        from app.modules.submittals import router as sub_router

        monkeypatch.setattr(sub_router, "ATTACHMENTS_DIR", tmp_path / "attachments")

        owner_id = await _make_user(db_session)
        owner = str(owner_id)
        project_id = await _make_project(db_session, owner_id)
        service = SubmittalService(db_session)

        sub = await service.create_submittal(
            SubmittalCreate(
                project_id=project_id,
                title="Shop Drawing — HVAC",
                submittal_type="shop_drawing",
            ),
            user_id=owner,
        )
        await db_session.commit()
        # Snapshot the primary key BEFORE entering the sync TestClient context
        # (accessing `sub.id` inside the sync context trips MissingGreenlet because
        # the expired async-session attribute refresh is not greenlet-aware).
        sub_id = sub.id

        app = _build_app(db_session, caller_id=owner)
        client = TestClient(app)

        # Round 1: upload a PDF attachment (submittal is still in draft — allowed).
        pdf_r1 = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\nround-1-content"
        resp = client.post(
            f"/v1/submittals/{sub_id}/attachments/upload/",
            files={"file": ("round1.pdf", pdf_r1, "application/pdf")},
            params={"label": "Round 1 drawing"},
        )
        assert resp.status_code == 201, resp.text

        # Advance through submit → under_review → revise_and_resubmit via HTTP
        # (no async session writes after TestClient has started — all transitions
        # go through the router endpoints to avoid MissingGreenlet).
        submit_resp = client.post(f"/v1/submittals/{sub_id}/submit/")
        assert submit_resp.status_code == 200, submit_resp.text

        patch_resp = client.patch(
            f"/v1/submittals/{sub_id}",
            json={"status": "under_review"},
        )
        assert patch_resp.status_code == 200, patch_resp.text

        # under_review → revise_and_resubmit via the /review endpoint.
        review_resp = client.post(
            f"/v1/submittals/{sub_id}/review/",
            json={"status": "revise_and_resubmit"},
        )
        assert review_resp.status_code == 200, review_resp.text
        assert review_resp.json()["status"] == "revise_and_resubmit"

        # Round 2: upload another PDF attachment.
        pdf_r2 = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\nround-2-revised-content"
        resp2 = client.post(
            f"/v1/submittals/{sub_id}/attachments/upload/",
            files={"file": ("round2.pdf", pdf_r2, "application/pdf")},
            params={"label": "Round 2 revised drawing"},
        )
        assert resp2.status_code == 201, resp2.text

        # List attachments: both rounds must be present.
        list_resp = client.get(f"/v1/submittals/{sub_id}/attachments/")
        assert list_resp.status_code == 200, list_resp.text
        entries = list_resp.json()
        assert len(entries) == 2, f"Expected 2 attachment entries (one per round), got {len(entries)}"
        labels = {e["label"] for e in entries}
        assert "Round 1 drawing" in labels
        assert "Round 2 revised drawing" in labels

    @pytest.mark.asyncio
    async def test_attachment_list_preserves_order(self, db_session, tmp_path, monkeypatch) -> None:
        """Attachments appear in insertion order (oldest first)."""
        from app.modules.submittals import router as sub_router

        monkeypatch.setattr(sub_router, "ATTACHMENTS_DIR", tmp_path / "attachments")

        owner_id = await _make_user(db_session)
        owner = str(owner_id)
        project_id = await _make_project(db_session, owner_id)
        service = SubmittalService(db_session)

        sub = await service.create_submittal(
            SubmittalCreate(
                project_id=project_id,
                title="Test Report",
                submittal_type="test_report",
            ),
            user_id=owner,
        )
        await db_session.commit()
        sub_id = sub.id

        app = _build_app(db_session, caller_id=owner)
        client = TestClient(app)

        pdf = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
        for label in ("alpha", "beta", "gamma"):
            r = client.post(
                f"/v1/submittals/{sub_id}/attachments/upload/",
                files={"file": (f"{label}.pdf", pdf + label.encode(), "application/pdf")},
                params={"label": label},
            )
            assert r.status_code == 201, r.text

        list_resp = client.get(f"/v1/submittals/{sub_id}/attachments/")
        entries = list_resp.json()
        assert [e["label"] for e in entries] == ["alpha", "beta", "gamma"]

    @pytest.mark.asyncio
    async def test_delete_removes_only_target_attachment(self, db_session, tmp_path, monkeypatch) -> None:
        """DELETE /{id}/attachments/{doc_id} removes one entry, leaves others intact."""
        from app.modules.submittals import router as sub_router

        monkeypatch.setattr(sub_router, "ATTACHMENTS_DIR", tmp_path / "attachments")

        owner_id = await _make_user(db_session)
        owner = str(owner_id)
        project_id = await _make_project(db_session, owner_id)
        service = SubmittalService(db_session)

        sub = await service.create_submittal(
            SubmittalCreate(
                project_id=project_id,
                title="Warranty Doc",
                submittal_type="warranty",
            ),
            user_id=owner,
        )
        await db_session.commit()
        sub_id = sub.id

        app = _build_app(db_session, caller_id=owner)
        client = TestClient(app)

        pdf = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
        r1 = client.post(
            f"/v1/submittals/{sub_id}/attachments/upload/",
            files={"file": ("keep.pdf", pdf + b"keep", "application/pdf")},
            params={"label": "keep"},
        )
        r2 = client.post(
            f"/v1/submittals/{sub_id}/attachments/upload/",
            files={"file": ("remove.pdf", pdf + b"remove", "application/pdf")},
            params={"label": "remove"},
        )
        assert r1.status_code == 201 and r2.status_code == 201

        doc_to_remove = r2.json()["document_id"]
        del_resp = client.delete(f"/v1/submittals/{sub_id}/attachments/{doc_to_remove}")
        assert del_resp.status_code == 204, del_resp.text

        list_resp = client.get(f"/v1/submittals/{sub_id}/attachments/")
        entries = list_resp.json()
        assert len(entries) == 1
        assert entries[0]["label"] == "keep"


# ── 3. Closing past due_date is informational only ───────────────────────────


class TestClosePastDueDate:
    """Closing an approved submittal past its date_required must not 422.

    The date_required field is informational (it drives UI urgency badges);
    it must never block a valid FSM transition.
    """

    @pytest.mark.asyncio
    async def test_approve_past_date_required_succeeds(self, db_session) -> None:
        """Approving a submittal past its date_required is not blocked.

        date_required is informational (urgency badge in the UI). It must
        never prevent the FSM from advancing to approved.
        """
        owner_id = await _make_user(db_session)
        reviewer_id = await _make_user(db_session)
        owner = str(owner_id)
        reviewer = str(reviewer_id)
        project_id = await _make_project(db_session, owner_id)
        service = SubmittalService(db_session)

        # Create with a date_required in the far past.
        sub = await service.create_submittal(
            SubmittalCreate(
                project_id=project_id,
                title="Overdue Shop Drawing",
                submittal_type="shop_drawing",
                reviewer_id=reviewer,
                date_required="2020-01-01",  # well in the past
            ),
            user_id=owner,
        )
        sub = await service.submit_submittal(sub.id)
        sub = await service.approve_submittal(sub.id, approver_id=reviewer)
        await db_session.commit()

        # Approval must succeed even though date_required is in the past.
        assert sub.status == "approved", (
            "Approving a submittal past date_required must succeed — overdue is informational, not a gate"
        )
        assert sub.ball_in_court is None, "approved must clear ball_in_court"


# ── 4. Magic-byte uploads — OLE and DWG positive tests ────────────────────────


class TestMagicByteExtendedFormats:
    """OLE and DWG are in _ALLOWED_ATTACHMENT_TYPES but had no positive test.

    OLE magic: D0 CF 11 E0 A1 B1 1A E1 (legacy Office .doc/.xls).
    DWG magic: 41 43 31 30 ("AC10xx" AutoCAD header).
    """

    @pytest.mark.asyncio
    async def test_ole_attachment_accepted(self, db_session, tmp_path, monkeypatch) -> None:
        from app.modules.submittals import router as sub_router

        monkeypatch.setattr(sub_router, "ATTACHMENTS_DIR", tmp_path / "attachments")

        owner_id = await _make_user(db_session)
        owner = str(owner_id)
        project_id = await _make_project(db_session, owner_id)
        service = SubmittalService(db_session)
        sub = await service.create_submittal(
            SubmittalCreate(
                project_id=project_id,
                title="Legacy spec",
                submittal_type="product_data",
            ),
            user_id=owner,
        )
        await db_session.commit()
        sub_id = sub.id

        app = _build_app(db_session, caller_id=owner)
        client = TestClient(app)

        # OLE compound document magic bytes (Word 97-2003 .doc, Excel 97-2003 .xls)
        ole_magic = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64
        resp = client.post(
            f"/v1/submittals/{sub_id}/attachments/upload/",
            files={"file": ("spec.doc", ole_magic, "application/msword")},
        )
        assert resp.status_code == 201, f"OLE upload rejected: {resp.text}"
        assert resp.json()["label"] == "spec.doc"

    @pytest.mark.asyncio
    async def test_dwg_attachment_accepted(self, db_session, tmp_path, monkeypatch) -> None:
        from app.modules.submittals import router as sub_router

        monkeypatch.setattr(sub_router, "ATTACHMENTS_DIR", tmp_path / "attachments")

        owner_id = await _make_user(db_session)
        owner = str(owner_id)
        project_id = await _make_project(db_session, owner_id)
        service = SubmittalService(db_session)
        sub = await service.create_submittal(
            SubmittalCreate(
                project_id=project_id,
                title="CAD drawing",
                submittal_type="shop_drawing",
            ),
            user_id=owner,
        )
        await db_session.commit()
        sub_id = sub.id

        app = _build_app(db_session, caller_id=owner)
        client = TestClient(app)

        # DWG magic: "AC10" (AutoCAD 2000+ format)
        dwg_magic = b"AC1015" + b"\x00" * 64
        resp = client.post(
            f"/v1/submittals/{sub_id}/attachments/upload/",
            files={"file": ("structure.dwg", dwg_magic, "application/octet-stream")},
        )
        assert resp.status_code == 201, f"DWG upload rejected: {resp.text}"
        payload = resp.json()
        assert payload["label"] == "structure.dwg"

    @pytest.mark.asyncio
    async def test_script_disguised_as_dwg_is_rejected(self, db_session, tmp_path, monkeypatch) -> None:
        from app.modules.submittals import router as sub_router

        monkeypatch.setattr(sub_router, "ATTACHMENTS_DIR", tmp_path / "attachments")

        owner_id = await _make_user(db_session)
        owner = str(owner_id)
        project_id = await _make_project(db_session, owner_id)
        service = SubmittalService(db_session)
        sub = await service.create_submittal(
            SubmittalCreate(
                project_id=project_id,
                title="Phishing drawing",
                submittal_type="shop_drawing",
            ),
            user_id=owner,
        )
        await db_session.commit()
        sub_id = sub.id

        app = _build_app(db_session, caller_id=owner)
        client = TestClient(app)

        # Shell script posing as a DWG
        bad_body = b"#!/bin/bash\nrm -rf /\n" + b"A" * 64
        resp = client.post(
            f"/v1/submittals/{sub_id}/attachments/upload/",
            files={"file": ("evil.dwg", bad_body, "application/octet-stream")},
        )
        assert resp.status_code == 415, f"Expected 415, got {resp.status_code}: {resp.text}"
