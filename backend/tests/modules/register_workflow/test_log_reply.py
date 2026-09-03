# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""The manual reply capture — POST /items/{id}/log-reply.

On a deployment with no mailbox bridge, a supplier's answer still lands in
someone's inbox. This route files that reply against the item by hand so the
tracking board flips to "replied", the workflow keeps moving, and nothing
depends on the bridge. It reuses the Inbound Capture Gateway, so what it
writes is indistinguishable from a swept-in reply.
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

USER_ID = "00000000-0000-0000-0000-0000000000b7"

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
    """A live app, a project the overridden user owns, and one supplier."""
    async with isolated_engine() as engine:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as s:
            user = User(
                id=uuid.UUID(USER_ID),
                email=f"lr-{uuid.uuid4().hex[:8]}@example.com",
                hashed_password="x",
                full_name="Reply Test",
                role="admin",
            )
            s.add(user)
            await s.flush()
            project = Project(
                name=f"LR {uuid.uuid4().hex[:6]}",
                owner_id=user.id,
                currency="AUD",
                project_code="24188",
            )
            s.add(project)
            supplier = Contact(
                contact_type="supplier",
                company_name="Acme Cables",
                primary_email="sales@acme.example",
            )
            s.add(supplier)
            await s.commit()
            project_id = str(project.id)
            supplier_id = str(supplier.id)

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
            yield client, project_id, supplier_id


async def _raise_rfq(client, project_id: str, supplier_id: str) -> dict:
    body = {
        "project_id": project_id,
        "kind": "rfq",
        "title": "MSB-01",
        "fields": dict(RFQ_FIELDS),
        "recipient_contact_ids": [supplier_id],
    }
    r = await client.post("/api/v1/register-workflow/items", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _row_for(tracking: dict, supplier_id: str) -> dict:
    for row in tracking["rows"]:
        if row.get("contact_id") == supplier_id:
            return row
    raise AssertionError(f"supplier {supplier_id} not on the tracking board: {tracking['rows']}")


@pytest.mark.asyncio
async def test_a_hand_filed_reply_flips_the_supplier_to_replied(ctx) -> None:
    client, pid, supplier_id = ctx
    item = await _raise_rfq(client, pid, supplier_id)
    item_id = item["id"]

    # It was issued to the supplier (log the send that went out by hand).
    r = await client.post(
        f"/api/v1/register-workflow/items/{item_id}/log-sent",
        json={"contact_id": supplier_id},
    )
    assert r.status_code == 200, r.text

    # Before the reply: waiting, not replied.
    before = _row_for(
        (await client.get(f"/api/v1/register-workflow/items/{item_id}/tracking")).json(),
        supplier_id,
    )
    assert before["state"] in {"waiting", "chase", "overdue"}
    assert not before.get("replied_at")

    # File the reply by hand.
    r = await client.post(
        f"/api/v1/register-workflow/items/{item_id}/log-reply",
        json={"contact_id": supplier_id, "body": "Thanks - our price is $9,350 ex GST."},
    )
    assert r.status_code == 200, r.text

    # After: the supplier's row is answered, attributed to them.
    after = _row_for(
        (await client.get(f"/api/v1/register-workflow/items/{item_id}/tracking")).json(),
        supplier_id,
    )
    assert after["state"] in {"replied", "quoted"}, after
    assert after.get("replied_at")
    assert int(after.get("reply_count") or 0) >= 1


@pytest.mark.asyncio
async def test_log_reply_needs_a_sender(ctx) -> None:
    client, pid, supplier_id = ctx
    item = await _raise_rfq(client, pid, supplier_id)
    r = await client.post(
        f"/api/v1/register-workflow/items/{item['id']}/log-reply",
        json={"body": "no sender named"},
    )
    assert r.status_code == 400, r.text


@pytest.mark.asyncio
async def test_a_reply_from_someone_not_in_the_book_is_still_captured(ctx) -> None:
    client, pid, supplier_id = ctx
    item = await _raise_rfq(client, pid, supplier_id)
    # A free-text sender (no contact id) must not be refused - plenty of
    # answers come from a person who was never in the directory.
    r = await client.post(
        f"/api/v1/register-workflow/items/{item['id']}/log-reply",
        json={"from_name": "A passing subcontractor", "body": "we can do it next week"},
    )
    assert r.status_code == 200, r.text
