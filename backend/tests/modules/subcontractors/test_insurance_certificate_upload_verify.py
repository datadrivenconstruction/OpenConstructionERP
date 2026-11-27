"""Insurance upload on an agreement records a certificate awaiting review; permitted members verify it."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from app.dependencies import get_current_user_id, get_current_user_payload, get_session
from app.modules.projects.models import Project
from app.modules.subcontractors.models import SubcontractAgreement, Subcontractor
from app.modules.subcontractors.permissions import register_subcontractors_permissions
from app.modules.subcontractors.router import router as subs_router
from app.modules.users.models import User
from tests._pg import transactional_session

PDF = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\nbody"


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator:
    async with transactional_session() as s:
        yield s


async def _seed(session):
    user = User(email=f"u{uuid.uuid4().hex[:8]}@example.com", hashed_password="x")
    session.add(user)
    await session.flush()
    sub = Subcontractor(legal_name=f"Acme {uuid.uuid4().hex[:6]}", trade_categories=[])
    session.add(sub)
    project = Project(id=uuid.uuid4(), name="Cert probe", owner_id=user.id, currency="USD")
    session.add(project)
    await session.flush()
    agreement = SubcontractAgreement(
        id=uuid.uuid4(),
        subcontractor_id=sub.id,
        project_id=project.id,
        title="Concrete subcontract",
        currency="USD",
        total_value=Decimal("8000"),
        status="active",
    )
    session.add(agreement)
    await session.flush()
    await session.commit()
    return str(user.id), sub.id, agreement.id


def _app(session, caller: str, *, role: str, permissions: list[str] | None = None) -> FastAPI:
    register_subcontractors_permissions()
    app = FastAPI()
    app.include_router(subs_router, prefix="/v1/subcontractors")

    async def _session():
        yield session

    async def _user() -> str:
        return caller

    async def _payload() -> dict:
        return {"sub": caller, "role": role, "permissions": permissions or []}

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user_id] = _user
    app.dependency_overrides[get_current_user_payload] = _payload
    return app


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _upload(client, agreement_id, valid_until: date):
    return await client.post(
        f"/v1/subcontractors/agreements/{agreement_id}/documents/upload",
        data={"doc_role": "insurance", "valid_until": valid_until.isoformat()},
        files={"file": ("coi.pdf", PDF, "application/pdf")},
    )


@pytest.mark.asyncio
async def test_insurance_upload_registers_certificate_awaiting_review(db_session, tmp_path, monkeypatch) -> None:
    from app.modules.subcontractors import router as mod

    monkeypatch.setattr(mod, "AGREEMENT_DOCUMENTS_DIR", tmp_path / "docs")
    caller, sub_id, agreement_id = await _seed(db_session)
    async with _client(_app(db_session, caller, role="admin")) as c:
        resp = await _upload(c, agreement_id, date.today() + timedelta(days=200))
        assert resp.status_code == 201, resp.text
        certs = (await c.get(f"/v1/subcontractors/certificates/?subcontractor_id={sub_id}")).json()
        assert len(certs) == 1
        cert = certs[0]
        assert cert["cert_type"] == "insurance"
        assert cert["status"] == "valid"
        assert cert["review_status"] == "awaiting_review"
        assert cert["verified_at"] is None
        # The reviewer can open the stored file.
        dl = await c.get(f"/v1/subcontractors/certificates/{cert['id']}/download")
        assert dl.status_code == 200 and dl.content == PDF


@pytest.mark.asyncio
async def test_non_insurance_upload_makes_no_certificate(db_session, tmp_path, monkeypatch) -> None:
    from app.modules.subcontractors import router as mod

    monkeypatch.setattr(mod, "AGREEMENT_DOCUMENTS_DIR", tmp_path / "docs")
    caller, sub_id, agreement_id = await _seed(db_session)
    async with _client(_app(db_session, caller, role="admin")) as c:
        resp = await c.post(
            f"/v1/subcontractors/agreements/{agreement_id}/documents/upload",
            data={"doc_role": "safety_plan"},
            files={"file": ("p.pdf", PDF, "application/pdf")},
        )
        assert resp.status_code == 201, resp.text
        assert (await c.get(f"/v1/subcontractors/certificates/?subcontractor_id={sub_id}")).json() == []


@pytest.mark.asyncio
async def test_verify_flow_and_permissions(db_session, tmp_path, monkeypatch) -> None:
    from app.modules.subcontractors import router as mod

    monkeypatch.setattr(mod, "AGREEMENT_DOCUMENTS_DIR", tmp_path / "docs")
    caller, sub_id, agreement_id = await _seed(db_session)
    async with _client(_app(db_session, caller, role="admin")) as admin:
        await _upload(admin, agreement_id, date.today() + timedelta(days=200))
        cert_id = (await admin.get(f"/v1/subcontractors/certificates/?subcontractor_id={sub_id}")).json()[0]["id"]

    # An editor can upload but not verify.
    async with _client(_app(db_session, caller, role="editor")) as editor:
        assert (await editor.post(f"/v1/subcontractors/certificates/{cert_id}/verify")).status_code == 403

    # A manager (approve_prequalification) verifies; the state shows who and when.
    async with _client(_app(db_session, caller, role="manager")) as mgr:
        ok = await mgr.post(f"/v1/subcontractors/certificates/{cert_id}/verify")
        assert ok.status_code == 200, ok.text
        body = ok.json()
        assert body["review_status"] == "verified"
        assert body["verified_by"] == caller and body["verified_at"]
        # Replacing the expiry invalidates the earlier check.
        patched = await mgr.patch(
            f"/v1/subcontractors/certificates/{cert_id}",
            json={"valid_until": (date.today() + timedelta(days=400)).isoformat()},
        )
        assert patched.json()["review_status"] == "awaiting_review"
        await mgr.post(f"/v1/subcontractors/certificates/{cert_id}/verify")
        undone = await mgr.delete(f"/v1/subcontractors/certificates/{cert_id}/verify")
        assert undone.json()["review_status"] == "awaiting_review"


@pytest.mark.asyncio
async def test_expired_certificate_cannot_be_verified(db_session, tmp_path, monkeypatch) -> None:
    from app.modules.subcontractors import router as mod

    monkeypatch.setattr(mod, "AGREEMENT_DOCUMENTS_DIR", tmp_path / "docs")
    caller, sub_id, agreement_id = await _seed(db_session)
    async with _client(_app(db_session, caller, role="admin")) as c:
        await _upload(c, agreement_id, date.today() - timedelta(days=3))
        cert = (await c.get(f"/v1/subcontractors/certificates/?subcontractor_id={sub_id}")).json()[0]
        assert cert["review_status"] == "expired"
        assert (await c.post(f"/v1/subcontractors/certificates/{cert['id']}/verify")).status_code == 409
