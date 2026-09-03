# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""The order confirmation to the winning supplier - the step after award.

Awarding an RFQ is not the end of the workflow: the winner still has to be
told they were successful and issued a purchase order. These endpoints render
that confirmation to the winner (with the PO and any notes) and hand it over
as an editable .eml - server-side, so it needs no mailbox bridge.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.dependencies import (  # noqa: E402
    get_current_user_id,
    get_current_user_payload,
    get_session,
)
from app.modules.contacts.models import Contact  # noqa: E402
from app.modules.projects.models import Project  # noqa: E402
from app.modules.register_workflow.router import router as rw_router  # noqa: E402
from app.modules.users.models import User  # noqa: E402
from tests._pg import isolated_engine

USER_ID = "00000000-0000-0000-0000-0000000000c3"

RFQ_FIELDS = {
    "Package": "Cable ladder",
    "Delivery to": "12 Site Rd",
    "Site contact": "Alex Example 0400 000 000",
    "Delivery window / site hours": "Site hours 06:30-14:30",
    "Estimated value $": "9900",
    "Quotes due": "2026-09-30",
}


@pytest_asyncio.fixture
async def ctx():
    async with isolated_engine() as engine:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as s:
            user = User(
                id=uuid.UUID(USER_ID),
                email=f"ac-{uuid.uuid4().hex[:8]}@example.com",
                hashed_password="x",
                full_name="Award Test",
                role="admin",
            )
            s.add(user)
            await s.flush()
            project = Project(
                name=f"AC {uuid.uuid4().hex[:6]}",
                owner_id=user.id,
                currency="AUD",
                project_code="24188",
            )
            s.add(project)
            winner = Contact(
                contact_type="supplier",
                company_name="Northbank Electrical",
                first_name="Sam",
                primary_email="sam@northbank.example",
            )
            s.add(winner)
            await s.commit()
            project_id = str(project.id)
            winner_id = str(winner.id)

        app = FastAPI()
        app.include_router(rw_router, prefix="/api/v1/register-workflow")
        app.dependency_overrides[get_current_user_id] = lambda: USER_ID
        app.dependency_overrides[get_current_user_payload] = lambda: {
            "sub": USER_ID,
            "role": "admin",
            "permissions": ["*"],
        }

        async def _session_override():
            async with maker() as s:
                yield s

        app.dependency_overrides[get_session] = _session_override

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            yield client, project_id, winner_id


async def _raise_rfq(client, project_id: str, winner_id: str) -> dict:
    body = {
        "project_id": project_id,
        "kind": "rfq",
        "title": "MSB-01",
        "fields": dict(RFQ_FIELDS),
        "recipient_contact_ids": [winner_id],
    }
    r = await client.post("/api/v1/register-workflow/items", json=body)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.asyncio
async def test_confirmation_preview_names_the_winner_the_po_and_the_note(ctx) -> None:
    client, pid, winner_id = ctx
    item = await _raise_rfq(client, pid, winner_id)
    r = await client.post(
        f"/api/v1/register-workflow/items/{item['id']}/award-confirmation/preview",
        json={"contact_id": winner_id, "po_number": "PO-5599", "amount": "9350", "note": "Deliver Friday."},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    html = body["html"]
    # Reads as an order confirmation, not a repeat of the RFQ request.
    assert "confirmation" in html.lower() or "awarded" in html.lower()
    # The PO, the note and the package all reach the winner.
    assert "PO-5599" in body["subject"] or "PO-5599" in html
    assert "Deliver Friday." in html
    assert "MSB-01" in html
    # Addressed to the winner, and no side effect (preview only).
    assert body["to"] == ["sam@northbank.example"]


@pytest.mark.asyncio
async def test_confirmation_eml_downloads_as_rfc822(ctx) -> None:
    client, pid, winner_id = ctx
    item = await _raise_rfq(client, pid, winner_id)
    r = await client.post(
        f"/api/v1/register-workflow/items/{item['id']}/award-confirmation/eml",
        json={"contact_id": winner_id, "po_number": "PO-5599", "note": "thanks"},
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("message/rfc822")
    assert b"Subject:" in r.content
    # Downloading it counts as a send on the item, so the trail is not blank.
    tracking = (await client.get(f"/api/v1/register-workflow/items/{item['id']}/tracking")).json()
    row = next((x for x in tracking["rows"] if x.get("contact_id") == winner_id), None)
    assert row is not None and row["sent_count"] >= 1


@pytest.mark.asyncio
async def test_confirmation_refuses_an_unknown_winner(ctx) -> None:
    client, pid, _winner_id = ctx
    item = await _raise_rfq(client, pid, _winner_id)
    r = await client.post(
        f"/api/v1/register-workflow/items/{item['id']}/award-confirmation/preview",
        json={"contact_id": str(uuid.uuid4()), "po_number": "PO-1"},
    )
    assert r.status_code == 400, r.text
