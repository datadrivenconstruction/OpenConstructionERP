# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Router-level tests for the register workflow endpoints.

The service layer underneath these is covered elsewhere; what this file
proves is the WIRING - that each route reaches the right function, passes
its arguments through, and answers with the shape the workspace renders.
A wiring mistake here (a payload field never read, a response missing its
native facts, an upload landing nowhere) is invisible to service tests
and immediately visible to the user.

Mounted as a bare app with the auth dependencies overridden, so no JWT is
minted and no module loader runs.
"""

from __future__ import annotations

import io
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
from app.modules.projects.models import Project  # noqa: E402
from app.modules.register_workflow.router import router as rw_router  # noqa: E402
from app.modules.users.models import User  # noqa: E402
from tests._pg import isolated_engine

USER_ID = "00000000-0000-0000-0000-0000000000a1"

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
    """A live app + a project the overridden user may access."""
    async with isolated_engine() as engine:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as s:
            user = User(
                id=uuid.UUID(USER_ID),
                email=f"rt-{uuid.uuid4().hex[:8]}@example.com",
                hashed_password="x",
                full_name="Router Test",
                role="admin",
            )
            s.add(user)
            await s.flush()
            project = Project(name=f"RT {uuid.uuid4().hex[:6]}", owner_id=user.id, currency="AUD", project_code="24188")
            s.add(project)
            await s.commit()
            project_id = str(project.id)

        app = FastAPI()
        app.include_router(rw_router, prefix="/api/v1/register-workflow")
        app.dependency_overrides[get_current_user_id] = lambda: USER_ID
        app.dependency_overrides[get_current_user_payload] = lambda: {
            "sub": USER_ID,
            "role": "admin",
            "permissions": ["*"],
        }

        # The routes take their session from ``get_session``. Overriding
        # the DEPENDENCY is the only reliable seam: app.dependencies binds
        # ``async_session_factory`` by name at import time, so patching the
        # database module afterwards leaves the routes on the real engine.
        async def _session_override():
            async with maker() as s:
                yield s

        app.dependency_overrides[get_session] = _session_override

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            yield client, project_id, maker


async def _raise_rfq(client, project_id: str, **over) -> dict:
    body = {
        "project_id": project_id,
        "kind": "rfq",
        "title": over.pop("title", "MSB-01"),
        "fields": dict(RFQ_FIELDS, **over.pop("fields", {})),
        "recipient_contact_ids": over.pop("recipients", []),
    }
    r = await client.post("/api/v1/register-workflow/items", json=body)
    assert r.status_code == 201, r.text
    return r.json()


# ── The spec every form is drawn from ────────────────────────────────────


@pytest.mark.asyncio
async def test_spec_route_serves_every_kind(ctx) -> None:
    client, _pid, _m = ctx
    r = await client.get("/api/v1/register-workflow/spec")
    assert r.status_code == 200
    body = r.json()
    assert set(body["kinds"]) == {"rfi", "rfq", "order", "variation", "delay", "toolbox"}
    rfq = body["specs"]["rfq"]
    assert rfq["recipient"] == "multi"
    assert any(f["required"] for f in rfq["fields"])
    assert any(f["internal"] for f in rfq["fields"])


# ── Raise, list, enrich ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_raise_answers_with_the_native_record_and_gate(ctx) -> None:
    client, pid, _m = ctx
    item = await _raise_rfq(client, pid)
    # The answer carries the platform's own RFQ and its live gate, so the
    # UI never has to re-fetch to learn what it just made.
    assert item["native"]["rfq_number"].startswith("RFQ-")
    assert item["native"]["quote_gate"]["required"] == 3
    assert item["steps_total"] > 0

    listed = await client.get(f"/api/v1/register-workflow/items?project_id={pid}&kind=rfq")
    assert listed.status_code == 200
    assert [i["id"] for i in listed.json()["items"]] == [item["id"]]
    assert listed.json()["total"] == 1


@pytest.mark.asyncio
async def test_raise_refuses_the_incomplete_delivery_block(ctx) -> None:
    client, pid, _m = ctx
    r = await client.post(
        "/api/v1/register-workflow/items",
        json={"project_id": pid, "kind": "rfq", "title": "No block", "fields": {"Package": "x"}},
    )
    assert r.status_code == 400
    assert "Delivery to" in r.json()["detail"]


# ── The email routes ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_compose_preview_needs_no_item_and_peeks_the_reference(ctx) -> None:
    client, pid, _m = ctx
    r = await client.post(
        "/api/v1/register-workflow/preview-email",
        json={
            "project_id": pid,
            "kind": "rfq",
            "title": "Switchboard supply",
            "fields": RFQ_FIELDS,
            "recipient_contact_ids": [],
            "contact_id": None,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["peeked_reference"] == "REG-RFQ-24188-0001"
    assert "Switchboard supply" in body["html"]
    # Peeked, NOT minted: nothing exists yet.
    listed = await client.get(f"/api/v1/register-workflow/items?project_id={pid}")
    assert listed.json()["items"] == [] and listed.json()["total"] == 0


@pytest.mark.asyncio
async def test_item_email_preview_has_no_side_effects(ctx) -> None:
    client, pid, _m = ctx
    item = await _raise_rfq(client, pid)
    r = await client.post(
        f"/api/v1/register-workflow/items/{item['id']}/email/preview",
        json={"contact_id": None, "extra_to": ["someone@example.com"]},
    )
    assert r.status_code == 200
    assert r.json()["to"] == ["someone@example.com"]
    # Previewing is not sending: the log stays empty.
    again = await client.get(f"/api/v1/register-workflow/items/{item['id']}")
    assert again.json()["fields"].get("_send_log") in (None, [])


@pytest.mark.asyncio
async def test_eml_download_is_an_unsent_draft_and_logs_the_send(ctx) -> None:
    client, pid, _m = ctx
    item = await _raise_rfq(client, pid)
    r = await client.post(
        f"/api/v1/register-workflow/items/{item['id']}/email/eml",
        json={"contact_id": None, "extra_to": []},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("message/rfc822")
    assert item["reference"] in r.headers["content-disposition"]
    body = r.content.decode("utf-8", errors="replace")
    assert "X-Unsent: 1" in body
    # The draft is in the user's hands, so it counts as a send.
    after = await client.get(f"/api/v1/register-workflow/items/{item['id']}")
    assert len(after.json()["fields"]["_send_log"]) == 1


@pytest.mark.asyncio
async def test_outlook_draft_degrades_to_503_off_windows(ctx, monkeypatch) -> None:
    """No desktop Outlook is not an error in the record - it is a 503 the
    UI turns into "use the .eml"."""
    import app.modules.outlook_bridge.ps as ps

    client, pid, _m = ctx
    item = await _raise_rfq(client, pid)
    monkeypatch.setattr(ps.sys, "platform", "linux")
    r = await client.post(
        f"/api/v1/register-workflow/items/{item['id']}/email/draft",
        json={"contact_id": None, "extra_to": []},
    )
    assert r.status_code == 503
    assert "Windows" in r.json()["detail"]


# ── Attachments ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_upload_lands_rides_the_email_and_can_be_held_back(ctx, monkeypatch, tmp_path) -> None:
    from pathlib import Path

    import app.modules.register_workflow.emailing as emailing

    client, pid, _m = ctx
    item = await _raise_rfq(client, pid)

    r = await client.post(
        f"/api/v1/register-workflow/items/{item['id']}/attachments",
        files={"file": ("ladder drawing.pdf", io.BytesIO(b"%PDF-1.4 x"), "application/pdf")},
    )
    assert r.status_code == 200, r.text
    atts = r.json()["fields"]["_attachments"]
    assert len(atts) == 1
    # Sanitised name, and it rides by default.
    assert atts[0]["filename"] == "ladder drawing.pdf"
    assert atts[0]["email"] is True

    # The file really is on disk where the email builder looks for it.
    monkeypatch.setattr(emailing, "ATTACH_ROOT", Path("uploads/register_workflow"))
    prev = await client.post(
        f"/api/v1/register-workflow/items/{item['id']}/email/preview",
        json={"contact_id": None, "extra_to": []},
    )
    assert prev.json()["attachment_names"] == ["ladder drawing.pdf"]

    # Held back: on the record, out of the supplier's inbox.
    off = await client.patch(
        f"/api/v1/register-workflow/items/{item['id']}/attachments",
        json={"filename": "ladder drawing.pdf", "email": False},
    )
    assert off.status_code == 200
    prev2 = await client.post(
        f"/api/v1/register-workflow/items/{item['id']}/email/preview",
        json={"contact_id": None, "extra_to": []},
    )
    assert prev2.json()["attachment_names"] == []


@pytest.mark.asyncio
async def test_flagging_an_unknown_attachment_is_a_404(ctx) -> None:
    client, pid, _m = ctx
    item = await _raise_rfq(client, pid)
    r = await client.patch(
        f"/api/v1/register-workflow/items/{item['id']}/attachments",
        json={"filename": "never-uploaded.pdf", "email": True},
    )
    assert r.status_code == 404


# ── Steps, quotes, award, thread, suggestions ────────────────────────────


@pytest.mark.asyncio
async def test_step_routes_enforce_the_rails(ctx) -> None:
    client, pid, _m = ctx
    item = await _raise_rfq(client, pid)
    steps = item["steps"]

    # Out of order.
    bad = await client.post(f"/api/v1/register-workflow/steps/{steps[2]['id']}/complete", json={})
    assert bad.status_code == 409
    assert "earlier steps first" in bad.json()["detail"]

    # In order, and the answer carries the whole updated item.
    ok = await client.post(f"/api/v1/register-workflow/steps/{steps[0]['id']}/complete", json={})
    assert ok.status_code == 200
    assert ok.json()["steps_done"] == 1

    # A gate cannot be waved away.
    gate = next(s for s in steps if s["type"] == "gate")
    waive = await client.post(f"/api/v1/register-workflow/steps/{gate['id']}/not-required", json={})
    assert waive.status_code == 409
    assert "hold point" in waive.json()["detail"]


@pytest.mark.asyncio
async def test_quote_then_award_runs_the_gate(ctx) -> None:
    client, pid, _m = ctx
    item = await _raise_rfq(client, pid)

    q = await client.post(
        f"/api/v1/register-workflow/items/{item['id']}/quotes",
        json={"bidder_contact_id": "alpha", "amount": "9350.00", "lead_time": "6 weeks"},
    )
    assert q.status_code == 200
    gate = q.json()["native"]["quote_gate"]
    assert (gate["counted"], gate["required"], gate["passes"]) == (1, 3, False)
    bid_id = q.json()["native"]["bids"][0]["id"]

    # One of three: refused, with the machine-readable force flag.
    refused = await client.post(
        f"/api/v1/register-workflow/items/{item['id']}/award",
        json={"bid_id": bid_id, "reason": "Best price", "po_number": "", "gate_override_reason": ""},
    )
    assert refused.status_code == 409
    detail = refused.json()["detail"]
    assert detail["gate"] == "quotes" and detail["can_force"] is True

    # With a written reason it goes through, and the reason is kept.
    forced = await client.post(
        f"/api/v1/register-workflow/items/{item['id']}/award",
        json={
            "bid_id": bid_id,
            "reason": "Only supplier who quoted",
            "po_number": "PO-1234",
            "gate_override_reason": "Two declined in writing",
        },
    )
    assert forced.status_code == 200
    award = forced.json()["native"]["award"]
    assert award["po_number"] == "PO-1234"
    assert award["quote_gate"]["override_reason"] == "Two declined in writing"


@pytest.mark.asyncio
async def test_thread_and_suggestions_answer_for_a_fresh_item(ctx) -> None:
    client, pid, _m = ctx
    item = await _raise_rfq(client, pid)

    thread = await client.get(f"/api/v1/register-workflow/items/{item['id']}/thread")
    assert thread.status_code == 200 and thread.json()["items"] == []

    sugg = await client.get(f"/api/v1/register-workflow/items/{item['id']}/suggestions")
    assert sugg.status_code == 200
    assert sugg.json() == {"by_supplier": {}, "unmatched": []}


@pytest.mark.asyncio
async def test_prefill_route_carries_the_reference_across(ctx) -> None:
    client, pid, _m = ctx
    rfi = await client.post(
        "/api/v1/register-workflow/items",
        json={
            "project_id": pid,
            "kind": "rfi",
            "title": "Grid clash",
            "fields": {"Question": "Which revision applies?"},
            "recipient_contact_ids": [],
        },
    )
    assert rfi.status_code == 201
    item = rfi.json()
    pre = await client.get(f"/api/v1/register-workflow/items/{item['id']}/prefill/variation")
    assert pre.status_code == 200
    body = pre.json()
    assert body["raised_from_reference"] == item["reference"]
    assert body["fields"]["Client instruction ref"] == item["reference"]


@pytest.mark.asyncio
async def test_summary_route_counts_every_kind(ctx) -> None:
    client, pid, _m = ctx
    await _raise_rfq(client, pid)
    r = await client.get(f"/api/v1/register-workflow/summary?project_id={pid}")
    assert r.status_code == 200
    body = r.json()
    assert body["rfq"]["total"] == 1 and body["rfq"]["open"] == 1
    assert body["delay"]["total"] == 0
