# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""The register's own generated mail, read as plain text.

The renderer and the .eml assembly are proved in
``tests/modules/outlook_bridge/test_plain_text_part.py``. What this file
proves is that the register's THREE generated messages actually reach it:
the item email, the award confirmation and a reply drafted off a captured
message. A text part that exists in the builder and never reaches the
download is the same defect it replaced.
"""

from __future__ import annotations

import re
import uuid
from email import message_from_bytes, policy

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

USER_ID = "00000000-0000-0000-0000-0000000000e7"
API = "/api/v1/register-workflow"

TAG = re.compile(r"<\s*/?[a-zA-Z][a-zA-Z0-9]*(\s[^>]*)?/?\s*>")

RFQ_FIELDS = {
    "Package": "Cable ladder",
    "Delivery to": "12 Site Rd",
    "Site contact": "Alex Example 0400 000 000",
    "Delivery window / site hours": "Site hours 06:30-14:30",
    "Estimated value $": "9900",
    "Quotes due": "2026-09-30",
}


def _parts(raw: bytes) -> tuple[str, str]:
    msg = message_from_bytes(raw, policy=policy.default)
    plain = msg.get_body(preferencelist=("plain",))
    html = msg.get_body(preferencelist=("html",))
    return (
        plain.get_content() if plain is not None else "",
        html.get_content() if html is not None else "",
    )


@pytest_asyncio.fixture
async def ctx():
    async with isolated_engine() as engine:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as s:
            user = User(
                id=uuid.UUID(USER_ID),
                email=f"pt-{uuid.uuid4().hex[:8]}@example.com",
                hashed_password="x",
                full_name="Plain Text",
                role="admin",
            )
            s.add(user)
            await s.flush()
            project = Project(
                name=f"PT {uuid.uuid4().hex[:6]}",
                owner_id=user.id,
                currency="AUD",
                project_code="25406",
            )
            s.add(project)
            supplier = Contact(
                contact_type="supplier",
                company_name="Acme Electrical",
                first_name="Alex",
                last_name="Example",
                primary_email="alex@acme.example",
            )
            s.add(supplier)
            await s.commit()
            project_id, supplier_id = str(project.id), str(supplier.id)

        app = FastAPI()
        app.include_router(rw_router, prefix=API)
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
            yield client, project_id, supplier_id, maker


async def _raise_rfq(client, project_id: str, supplier_id: str) -> dict:
    r = await client.post(
        f"{API}/items",
        json={
            "project_id": project_id,
            "kind": "rfq",
            "title": "MSB-01",
            "fields": dict(RFQ_FIELDS),
            "recipient_contact_ids": [supplier_id],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.asyncio
async def test_the_item_eml_carries_the_request_in_plain_text(ctx) -> None:
    client, pid, supplier_id, maker = ctx
    item = await _raise_rfq(client, pid, supplier_id)
    note = "The crane window is 06:30-09:00 only - please price accordingly."
    r = await client.post(
        f"{API}/items/{item['id']}/email/eml",
        json={"contact_id": supplier_id, "extra_note": note},
    )
    assert r.status_code == 200, r.text
    plain, html = _parts(r.content)

    # The reference a reply is filed against, then the request itself.
    assert item["reference"] in plain
    assert "Reference: " in plain
    # At least three of the form's own labels, spelled as the register
    # spells them - this is the document, not a summary of it.
    labels = [line for line in ("Package:", "Delivery to:", "Site contact:", "Quotes due:") if line in plain]
    assert len(labels) >= 3, plain
    assert "Cable ladder" in plain
    # THE FREE TEXT. This is what the supplier is actually being told, and
    # for a while the .eml path dropped it entirely - the preview showed
    # the note and the downloaded draft did not carry it.
    assert "crane window is 06:30-09:00" in plain

    # No markup, no entities, nothing a person has to decode.
    assert TAG.search(plain) is None
    assert "&nbsp;" not in plain and "&#x27;" not in plain
    # The money rail holds on the second door too.
    assert "9900" not in plain and "9,900" not in plain

    # The HTML part is unchanged - still the livery, still the same facts.
    assert html.startswith("<table") and item["reference"] in html
    assert "Cable ladder" in html


@pytest.mark.asyncio
async def test_the_award_confirmation_eml_carries_a_plain_text_order(ctx) -> None:
    client, pid, supplier_id, maker = ctx
    item = await _raise_rfq(client, pid, supplier_id)
    r = await client.post(
        f"{API}/items/{item['id']}/award-confirmation/eml",
        json={
            "contact_id": supplier_id,
            "po_number": "PO-5599",
            "amount": "9350",
            "note": "Deliver to gate 3 on Friday.",
        },
    )
    assert r.status_code == 200, r.text
    plain, html = _parts(r.content)
    assert "Purchase order: PO-5599" in plain
    assert "Reference: " in plain and item["reference"] in plain
    assert "Deliver to gate 3 on Friday." in plain
    assert "awarded to you" in plain
    assert TAG.search(plain) is None and "&nbsp;" not in plain
    assert "PO-5599" in html


@pytest.mark.asyncio
async def test_a_reply_draft_carries_the_quoted_original_as_text(ctx) -> None:
    """A reply is a generated message too - it needs a readable plain part."""
    from app.modules.correspondence.models import Correspondence
    from app.modules.register_workflow import replying

    client, pid, supplier_id, maker = ctx
    item = await _raise_rfq(client, pid, supplier_id)

    # The builder is exercised directly (as tests/…/test_replying.py does)
    # so the assertion is about the DRAFT, not about the capture path.
    from app.modules.register_workflow.models import RegisterItem

    async with maker() as session:
        row = Correspondence(
            project_id=uuid.UUID(pid),
            reference_number="COR-001",
            direction="inbound",
            subject="Our quote 100042",
            to_contact_ids=[],
            from_contact_id=supplier_id,
            correspondence_type="email",
            notes="Total $9,350.00 ex GST",
            status="received",
            metadata_={"register_item_id": item["id"]},
        )
        session.add(row)
        await session.flush()
        stored = await session.get(RegisterItem, uuid.UUID(item["id"]))
        built = await replying.build_reply(
            session,
            stored,
            correspondence_id=str(row.id),
            mode="reply",
            to=[],
            body="<p>Thanks Alex - noted.</p>",
        )

    text = built["text"]
    assert "Thanks Alex - noted." in text
    assert "-----Original message-----" in text
    assert "Subject: Our quote 100042" in text
    assert "9,350.00" in text
    assert TAG.search(text) is None
    # What was typed leads; the original is quoted underneath it.
    assert text.index("Thanks Alex") < text.index("9,350.00")


def test_the_quoted_original_reads_as_a_mail_client_writes_one() -> None:
    from app.modules.register_workflow import replying

    quoted = replying.quoted_original_text(
        {
            "from_people": [{"name": "Alex Example", "email": "alex@acme.example"}],
            "to_people": [{"name": "Example Projects", "email": "projects@example.com"}],
            "date": "2026-09-01",
            "subject": "Our quote 100042",
            "html": "<p>Total <b>$9,350.00</b> ex GST</p>",
        }
    )
    assert "-----Original message-----" in quoted
    assert "From: Alex Example <alex@acme.example>" in quoted
    assert "Sent: 2026-09-01" in quoted
    assert "Total $9,350.00 ex GST" in quoted
    assert TAG.search(quoted) is None
