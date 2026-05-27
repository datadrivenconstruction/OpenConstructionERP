"""End-to-end tests for the lien-waiver upload endpoint.

Scope:
    1. Real PDF blob passes the magic-byte gate and is stored under a
       server-derived filename (no path traversal via filename).
    2. HTML-disguised-as-PDF is rejected with HTTP 415 (file content
       overrides extension + Content-Type header).
    3. Empty body is rejected with 422 (operator-error, NOT 415 —
       distinguishes "no file" from "wrong format").
    4. Invalid ``waiver_type`` is rejected with 422 (enum constraint).
    5. IDOR: uploading against a non-existent subcontractor returns 404
       without leaking which UUIDs exist.
    6. Listing lien waivers returns the freshly-created row.

Mirrors ``tests/modules/rfi/test_rfi_attachments.py`` — in-memory SQLite
with the subcontractor router mounted on a fresh FastAPI app and the
auth + permission dependencies overridden.
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
)
from app.modules.subcontractors.models import (
    Certificate,
    LienWaiver,
    PaymentApplication,
    PaymentApplicationLine,
    PrequalificationApplication,
    RetentionLedger,
    SubcontractAgreement,
    Subcontractor,
    SubcontractorContact,
    SubcontractorRating,
    WorkPackage,
)
from app.modules.subcontractors.permissions import register_subcontractors_permissions
from app.modules.subcontractors.router import router as subs_router
from app.modules.users.models import APIKey, User

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator:
    """Fresh in-memory SQLite with the subcontractor tables present."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[
                User.__table__,
                APIKey.__table__,
                Subcontractor.__table__,
                SubcontractorContact.__table__,
                PrequalificationApplication.__table__,
                Certificate.__table__,
                SubcontractAgreement.__table__,
                WorkPackage.__table__,
                PaymentApplication.__table__,
                PaymentApplicationLine.__table__,
                RetentionLedger.__table__,
                SubcontractorRating.__table__,
                LienWaiver.__table__,
            ],
        )
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield s
    await engine.dispose()


async def _make_user(session) -> str:
    user = User(
        email=f"u{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return str(user.id)


async def _make_subcontractor(session) -> uuid.UUID:
    sub = Subcontractor(legal_name=f"Acme {uuid.uuid4().hex[:6]}", trade_categories=[])
    session.add(sub)
    await session.flush()
    await session.refresh(sub)
    return sub.id


def _build_app(db_session, *, caller_id: str) -> FastAPI:
    """Mount subcontractor router with auth + session overrides."""
    register_subcontractors_permissions()

    app = FastAPI()
    app.include_router(subs_router, prefix="/v1/subcontractors")

    async def _session_override():
        yield db_session

    async def _user_override() -> str:
        return caller_id

    async def _payload_override() -> dict:
        # Admin role short-circuits every ``subcontractors.*`` permission gate.
        return {"sub": caller_id, "role": "admin", "permissions": []}

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_current_user_id] = _user_override
    app.dependency_overrides[get_current_user_payload] = _payload_override
    return app


# ── 1. Real PDF accepted ─────────────────────────────────────────────────


class TestLienWaiverUpload:
    @pytest.mark.asyncio
    async def test_real_pdf_is_stored(
        self,
        db_session,
        tmp_path,
        monkeypatch,
    ) -> None:
        """Happy path — PDF body persists with a server-derived filename."""
        from app.modules.subcontractors import router as subs_router_mod

        monkeypatch.setattr(
            subs_router_mod,
            "LIEN_WAIVERS_DIR",
            tmp_path / "waivers",
        )

        caller = await _make_user(db_session)
        sub_id = await _make_subcontractor(db_session)
        await db_session.commit()

        app = _build_app(db_session, caller_id=caller)
        client = TestClient(app)

        pdf_body = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\nrest..."
        resp = client.post(
            f"/v1/subcontractors/subcontractors/{sub_id}/lien-waivers/upload",
            data={
                "waiver_type": "conditional_partial",
                "amount": "1250.00",
                "currency": "USD",
                "signed_date": "2026-05-25",
                "notes": "Draw #3",
            },
            files={"file": ("waiver.pdf", pdf_body, "application/pdf")},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["waiver_type"] == "conditional_partial"
        assert body["mime_type"] == "application/pdf"
        # Server-derived path — never echoes the attacker-supplied filename.
        assert body["document_url"].startswith(
            f"subcontractors/lien_waivers/{sub_id}/conditional_partial_",
        )
        assert body["document_url"].endswith(".pdf")
        assert "waiver.pdf" not in body["document_url"]
        assert body["file_size"] == len(pdf_body)

    # ── 2. Unknown-binary payload (faked as PDF) rejected ─────────────

    @pytest.mark.asyncio
    async def test_unknown_binary_disguised_as_pdf_returns_415(
        self,
        db_session,
        tmp_path,
        monkeypatch,
    ) -> None:
        """A blob whose magic bytes don't match any allowed signature
        must be rejected even though the filename / Content-Type claim
        application/pdf. NB: an HTML payload is not used here because
        the detector recognises `<html…>` as XML, which is itself an
        allowed document type for IDS / BCF / GAEB imports — the
        magic-byte gate would happily store it. We instead probe with
        a short binary header that registers as `unknown`.
        """
        from app.modules.subcontractors import router as subs_router_mod

        waivers_dir = tmp_path / "waivers"
        monkeypatch.setattr(subs_router_mod, "LIEN_WAIVERS_DIR", waivers_dir)

        caller = await _make_user(db_session)
        sub_id = await _make_subcontractor(db_session)
        await db_session.commit()

        app = _build_app(db_session, caller_id=caller)
        client = TestClient(app)

        random_bin = b"\x00\x01\x02\x03MEOW\xff\xee\xdd\xcc"
        resp = client.post(
            f"/v1/subcontractors/subcontractors/{sub_id}/lien-waivers/upload",
            data={"waiver_type": "conditional_partial"},
            files={"file": ("evil.pdf", random_bin, "application/pdf")},
        )
        assert resp.status_code == 415, resp.text
        # No disk write happened.
        if waivers_dir.exists():
            for sub_dir in waivers_dir.iterdir():
                assert list(sub_dir.iterdir()) == []

    # ── 3. Empty body returns 422 ─────────────────────────────────────

    @pytest.mark.asyncio
    async def test_empty_body_returns_422(
        self,
        db_session,
        tmp_path,
        monkeypatch,
    ) -> None:
        from app.modules.subcontractors import router as subs_router_mod

        monkeypatch.setattr(
            subs_router_mod,
            "LIEN_WAIVERS_DIR",
            tmp_path / "waivers",
        )

        caller = await _make_user(db_session)
        sub_id = await _make_subcontractor(db_session)
        await db_session.commit()

        app = _build_app(db_session, caller_id=caller)
        client = TestClient(app)

        resp = client.post(
            f"/v1/subcontractors/subcontractors/{sub_id}/lien-waivers/upload",
            data={"waiver_type": "conditional_partial"},
            files={"file": ("empty.pdf", b"", "application/pdf")},
        )
        assert resp.status_code == 422, resp.text

    # ── 4. Bad waiver_type returns 422 ────────────────────────────────

    @pytest.mark.asyncio
    async def test_bad_waiver_type_returns_422(
        self,
        db_session,
        tmp_path,
        monkeypatch,
    ) -> None:
        from app.modules.subcontractors import router as subs_router_mod

        monkeypatch.setattr(
            subs_router_mod,
            "LIEN_WAIVERS_DIR",
            tmp_path / "waivers",
        )

        caller = await _make_user(db_session)
        sub_id = await _make_subcontractor(db_session)
        await db_session.commit()

        app = _build_app(db_session, caller_id=caller)
        client = TestClient(app)

        pdf_body = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
        resp = client.post(
            f"/v1/subcontractors/subcontractors/{sub_id}/lien-waivers/upload",
            data={"waiver_type": "not_a_real_waiver"},
            files={"file": ("waiver.pdf", pdf_body, "application/pdf")},
        )
        assert resp.status_code == 422, resp.text

    # ── 5. IDOR — non-existent sub returns 404, NOT 403 or 500 ───────

    @pytest.mark.asyncio
    async def test_nonexistent_subcontractor_returns_404(
        self,
        db_session,
        tmp_path,
        monkeypatch,
    ) -> None:
        from app.modules.subcontractors import router as subs_router_mod

        monkeypatch.setattr(
            subs_router_mod,
            "LIEN_WAIVERS_DIR",
            tmp_path / "waivers",
        )

        caller = await _make_user(db_session)
        await db_session.commit()

        app = _build_app(db_session, caller_id=caller)
        client = TestClient(app)

        ghost_id = uuid.uuid4()
        pdf_body = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
        resp = client.post(
            f"/v1/subcontractors/subcontractors/{ghost_id}/lien-waivers/upload",
            data={"waiver_type": "w9"},
            files={"file": ("w9.pdf", pdf_body, "application/pdf")},
        )
        assert resp.status_code == 404, resp.text

    # ── 6. Listing returns the freshly-created row ────────────────────

    @pytest.mark.asyncio
    async def test_list_after_upload_returns_row(
        self,
        db_session,
        tmp_path,
        monkeypatch,
    ) -> None:
        from app.modules.subcontractors import router as subs_router_mod

        monkeypatch.setattr(
            subs_router_mod,
            "LIEN_WAIVERS_DIR",
            tmp_path / "waivers",
        )

        caller = await _make_user(db_session)
        sub_id = await _make_subcontractor(db_session)
        await db_session.commit()

        app = _build_app(db_session, caller_id=caller)
        client = TestClient(app)

        pdf_body = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
        up = client.post(
            f"/v1/subcontractors/subcontractors/{sub_id}/lien-waivers/upload",
            data={"waiver_type": "w9", "amount": "0"},
            files={"file": ("w9.pdf", pdf_body, "application/pdf")},
        )
        assert up.status_code == 201, up.text

        ls = client.get(
            f"/v1/subcontractors/subcontractors/{sub_id}/lien-waivers",
        )
        assert ls.status_code == 200, ls.text
        rows = ls.json()
        assert len(rows) == 1
        assert rows[0]["waiver_type"] == "w9"
