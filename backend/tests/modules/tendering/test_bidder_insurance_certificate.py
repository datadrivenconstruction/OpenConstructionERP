"""An insurance certificate sent through a bidder link lands in the subcontractor's certificate register."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from sqlalchemy import select

from app.dependencies import get_current_user_id, get_current_user_payload, get_session
from app.modules.projects.models import Project
from app.modules.subcontractors.models import Certificate, Subcontractor
from app.modules.subcontractors.permissions import register_subcontractors_permissions
from app.modules.subcontractors.router import router as subs_router
from app.modules.subcontractors.service import next_payment_blocked
from app.modules.tendering.bid_portal import hash_token
from app.modules.tendering.bidder_exchange import BidderExchangeService
from app.modules.tendering.models import TenderBidFile, TenderBidInvitation, TenderPackage
from app.modules.users.models import User
from tests._pg import transactional_session

PDF = b"%PDF-1.7\n%coi"
PDF_RENEWED = b"%PDF-1.7\n%coi renewed"


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator:
    async with transactional_session() as s:
        yield s


async def _seed(session, *, directory_firm: bool, other_recipient_is_directory: bool = False, status: str = "draft"):
    user = User(email=f"u{uuid.uuid4().hex[:8]}@example.com", hashed_password="x")
    session.add(user)
    await session.flush()
    project = Project(id=uuid.uuid4(), name="Coi link", owner_id=user.id, currency="EUR")
    session.add(project)
    sub = Subcontractor(legal_name=f"Cover {uuid.uuid4().hex[:6]}", trade_categories=[])
    session.add(sub)
    await session.flush()
    recipient = {"id": "r1", "company_name": "Cover Bau", "email": "a@sub.test"}
    if directory_firm:
        recipient["subcontractor_id"] = str(sub.id)
    recipients = [recipient]
    if other_recipient_is_directory:
        recipients.append({"id": "r2", "company_name": "Other", "email": "b@sub.test", "subcontractor_id": str(sub.id)})
    package = TenderPackage(
        project_id=project.id,
        name="Coi package",
        status=status,
        deadline=(datetime.now(UTC) + timedelta(days=14)).strftime("%Y-%m-%d"),
        metadata_={"recipients": recipients},
    )
    session.add(package)
    await session.flush()
    token = uuid.uuid4().hex
    session.add(
        TenderBidInvitation(
            package_id=package.id,
            recipient_id="r1",
            company_name="Cover Bau",
            email="a@sub.test",
            token_hash=hash_token(token),
            expires_at=datetime.now(UTC) + timedelta(days=10),
        )
    )
    await session.commit()
    return str(user.id), sub.id, token


def _client(session, caller: str):
    register_subcontractors_permissions()
    app = FastAPI()
    app.include_router(subs_router, prefix="/v1/subcontractors")

    async def _session():
        yield session

    async def _user() -> str:
        return caller

    async def _payload() -> dict:
        return {"sub": caller, "role": "admin", "permissions": []}

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user_id] = _user
    app.dependency_overrides[get_current_user_payload] = _payload
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_insurance_from_a_bidder_link_waits_for_review(db_session) -> None:
    caller, sub_id, token = await _seed(db_session, directory_firm=True)
    until = date.today() + timedelta(days=300)
    await BidderExchangeService(db_session).upload(token, "insurance", "coi.pdf", PDF, until)
    await db_session.commit()
    async with _client(db_session, caller) as c:
        rows = (await c.get(f"/v1/subcontractors/certificates/?subcontractor_id={sub_id}")).json()
        assert len(rows) == 1
        assert rows[0]["cert_type"] == "insurance"
        assert rows[0]["valid_until"] == until.isoformat()
        assert rows[0]["review_status"] == "awaiting_review"
        dl = await c.get(f"/v1/subcontractors/certificates/{rows[0]['id']}/download")
        assert dl.status_code == 200 and dl.content == PDF
        ok = await c.post(f"/v1/subcontractors/certificates/{rows[0]['id']}/verify")
        assert ok.json()["review_status"] == "verified"


@pytest.mark.asyncio
async def test_insurance_from_a_firm_outside_the_directory_is_only_filed(db_session) -> None:
    caller, sub_id, token = await _seed(db_session, directory_firm=False)
    view = await BidderExchangeService(db_session).upload(token, "insurance", "coi.pdf", PDF, None)
    await db_session.commit()
    assert [f.kind for f in view.files] == ["insurance"]
    async with _client(db_session, caller) as c:
        assert (await c.get(f"/v1/subcontractors/certificates/?subcontractor_id={sub_id}")).json() == []


@pytest.mark.asyncio
async def test_insurance_must_be_a_pdf_or_image(db_session) -> None:
    _caller, _sub, token = await _seed(db_session, directory_firm=True)
    with pytest.raises(HTTPException) as err:
        await BidderExchangeService(db_session).upload(token, "insurance", "coi.docx", b"PK\x03\x04" + b"\x00" * 40)
    assert err.value.status_code == 422


async def _certs(session, sub_id) -> list[Certificate]:
    return list((await session.execute(select(Certificate).where(Certificate.subcontractor_id == sub_id))).scalars())


@pytest.mark.asyncio
async def test_another_recipients_directory_link_never_applies(db_session) -> None:
    _caller, sub_id, token = await _seed(db_session, directory_firm=False, other_recipient_is_directory=True)
    await BidderExchangeService(db_session).upload(token, "insurance", "coi.pdf", PDF, "2027-06-30")
    assert await _certs(db_session, sub_id) == []


@pytest.mark.asyncio
async def test_insurance_rejects_an_office_file_and_stores_nothing(db_session) -> None:
    _caller, sub_id, token = await _seed(db_session, directory_firm=True)
    with pytest.raises(HTTPException) as err:
        await BidderExchangeService(db_session).upload(token, "insurance", "coi.xlsx", b"PK\x03\x04" + b"\x00" * 40)
    assert err.value.detail == "file_type_not_allowed"
    assert (await db_session.execute(select(TenderBidFile))).scalars().all() == []
    assert await _certs(db_session, sub_id) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["30.06.2027", "2027-13-01", "1899-01-01", "tomorrow"])
async def test_an_unreadable_expiry_is_refused_before_anything_is_stored(db_session, raw: str) -> None:
    _caller, sub_id, token = await _seed(db_session, directory_firm=True)
    with pytest.raises(HTTPException) as err:
        await BidderExchangeService(db_session).upload(token, "insurance", "coi.pdf", PDF, raw)
    assert err.value.status_code == 422
    assert err.value.detail == "invalid_valid_until"
    assert (await db_session.execute(select(TenderBidFile))).scalars().all() == []
    assert await _certs(db_session, sub_id) == []


@pytest.mark.asyncio
async def test_a_re_upload_keeps_one_row_and_a_new_file_needs_a_new_review(db_session) -> None:
    caller, sub_id, token = await _seed(db_session, directory_firm=True)
    svc = BidderExchangeService(db_session)
    url = f"/v1/subcontractors/certificates/?subcontractor_id={sub_id}"
    await svc.upload(token, "insurance", "coi.pdf", PDF, "2027-06-30")
    await db_session.commit()
    async with _client(db_session, caller) as c:
        cert_id = (await c.get(url)).json()[0]["id"]
        assert (await c.post(f"/v1/subcontractors/certificates/{cert_id}/verify")).status_code == 200

    # The same file and the same date again: still one row, still verified.
    await svc.upload(token, "insurance", "coi.pdf", PDF, "2027-06-30")
    await db_session.commit()
    async with _client(db_session, caller) as c:
        assert [r["review_status"] for r in (await c.get(url)).json()] == ["verified"]

    # A renewed policy: the row is reused, its expiry moves and the verification is dropped.
    await svc.upload(token, "insurance", "coi-2028.pdf", PDF_RENEWED, "2028-06-30")
    await db_session.commit()
    async with _client(db_session, caller) as c:
        rows = (await c.get(url)).json()
        assert [r["id"] for r in rows] == [cert_id]
        assert rows[0]["valid_until"] == "2028-06-30"
        assert rows[0]["review_status"] == "awaiting_review"
        dl = await c.get(f"/v1/subcontractors/certificates/{cert_id}/download")
        assert dl.content == PDF_RENEWED


@pytest.mark.asyncio
async def test_a_closed_tender_takes_no_certificate(db_session) -> None:
    _caller, sub_id, token = await _seed(db_session, directory_firm=True, status="closed")
    with pytest.raises(HTTPException) as err:
        await BidderExchangeService(db_session).upload(token, "insurance", "coi.pdf", PDF, "2027-06-30")
    assert err.value.status_code == 409
    assert await _certs(db_session, sub_id) == []


@pytest.mark.asyncio
async def test_an_expired_link_takes_no_certificate(db_session) -> None:
    _caller, sub_id, token = await _seed(db_session, directory_firm=True)
    invitation = (
        await db_session.execute(select(TenderBidInvitation).where(TenderBidInvitation.token_hash == hash_token(token)))
    ).scalar_one()
    package = await db_session.get(TenderPackage, invitation.package_id)
    package.deadline = (datetime.now(UTC) - timedelta(days=2)).strftime("%Y-%m-%d")
    invitation.expires_at = datetime.now(UTC) - timedelta(days=1)
    await db_session.commit()
    with pytest.raises(HTTPException) as err:
        await BidderExchangeService(db_session).upload(token, "insurance", "coi.pdf", PDF, "2027-06-30")
    assert err.value.status_code == 410
    assert await _certs(db_session, sub_id) == []


def test_an_unreviewed_bidder_certificate_does_not_clear_the_payment_gate() -> None:
    today = date(2027, 1, 15)
    sent = Certificate(
        cert_type="insurance",
        valid_until=date(2027, 12, 31),
        revoked=False,
        metadata_={"source": "bid_portal", "bid_file_id": str(uuid.uuid4())},
    )
    assert next_payment_blocked([sent], today=today, required_types=("insurance",)).blocked
    sent.metadata_ = {**sent.metadata_, "review": {"verified_at": "2027-01-10T09:00:00+00:00", "verified_by": "u"}}
    assert not next_payment_blocked([sent], today=today, required_types=("insurance",)).blocked
