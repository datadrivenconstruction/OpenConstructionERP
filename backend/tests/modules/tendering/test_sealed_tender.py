# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Sealed submission mode, end to end against the database.

The guarantees under test: before an authorised opening no staff read, list,
export, backup or event payload carries a sealed bid's figures; the server
refuses a submission at or after the deadline, from a revoked link and a
second time on the same link; opening needs a passed deadline and, in
two-person mode, two different users; each submission gets a receipt whose
SHA-256 the integrity check recomputes.

Every bidder price carries the distinctive figure ``4321.987`` so a leak under
any key is caught by searching the response text.

Run:
    cd backend
    python -m pytest tests/modules/tendering/test_sealed_tender.py -q
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

PRICE = "4321.987"
API = "/api/v1/tendering"


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def client():
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    from app.modules.tendering.bid_portal import reset_rate_limits

    reset_rate_limits()
    yield
    reset_rate_limits()


async def _user(client: AsyncClient, role: str) -> dict[str, str]:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    tag = uuid.uuid4().hex[:8]
    email = f"sealed-{role}-{tag}@test.io"
    password = f"Sealed{tag}9X"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"Sealed {role} {tag}"},
    )
    assert reg.status_code in (200, 201), reg.text
    async with async_session_factory() as session:
        await session.execute(update(User).where(User.email == email.lower()).values(role=role, is_active=True))
        await session.commit()
    login = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    token = login.json().get("access_token", "")
    assert token, login.text
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="module")
async def people(client: AsyncClient) -> dict[str, dict[str, str]]:
    """Editor owns the project; two admins open; an outsider owns another project."""
    return {
        "editor": await _user(client, "editor"),
        "opener_a": await _user(client, "admin"),
        "opener_b": await _user(client, "admin"),
        "outsider": await _user(client, "editor"),
    }


@pytest_asyncio.fixture(scope="module")
async def bill(client: AsyncClient, people: dict) -> dict:
    from app.database import async_session_factory
    from app.modules.boq.models import Position

    editor = people["editor"]
    project = await client.post("/api/v1/projects/", json={"name": "Sealed tests", "currency": "EUR"}, headers=editor)
    assert project.status_code in (200, 201), project.text
    project_id = project.json()["id"]
    boq = await client.post("/api/v1/boq/boqs/", json={"project_id": project_id, "name": "Bill"}, headers=editor)
    assert boq.status_code in (200, 201), boq.text
    boq_id = boq.json()["id"]
    section, item = uuid.uuid4(), uuid.uuid4()
    async with async_session_factory() as session:
        session.add(
            Position(
                id=section,
                boq_id=uuid.UUID(boq_id),
                ordinal="01",
                description="Works",
                unit="",
                quantity="0",
                unit_rate="0",
                total="0",
                sort_order=0,
            )
        )
        session.add(
            Position(
                id=item,
                boq_id=uuid.UUID(boq_id),
                parent_id=section,
                ordinal="01.001",
                description="Excavate",
                unit="m3",
                quantity="10",
                unit_rate="1",
                total="10",
                sort_order=1,
            )
        )
        await session.commit()
    return {"project_id": project_id, "boq_id": boq_id, "section": str(section), "item": str(item)}


def _future(hours: int = 48) -> str:
    return (datetime.now(UTC) + timedelta(hours=hours)).isoformat(timespec="seconds")


async def _package(client: AsyncClient, people: dict, bill: dict, *, dual: bool = False) -> str:
    resp = await client.post(
        f"{API}/packages/from-boq/",
        json={
            "project_id": bill["project_id"],
            "boq_id": bill["boq_id"],
            "section_ids": [bill["section"]],
            "package_name": f"Sealed {uuid.uuid4().hex[:6]}",
            "deadline": _future(),
        },
        headers=people["editor"],
    )
    assert resp.status_code == 201, resp.text
    package_id = resp.json()["id"]
    mode = await client.put(
        f"{API}/packages/{package_id}/submission-mode/",
        json={"mode": "sealed", "dual_opening": dual},
        headers=people["opener_a"],
    )
    assert mode.status_code == 200, mode.text
    assert mode.json()["submission_mode"] == "sealed"
    assert mode.json()["sealed"]["state"] == "sealed"
    return package_id


async def _link(client: AsyncClient, people: dict, package_id: str, company: str) -> tuple[str, str]:
    email = f"{uuid.uuid4().hex[:6]}@sub.test"
    rec = await client.post(
        f"{API}/packages/{package_id}/recipients/",
        json={"company_name": company, "email": email},
        headers=people["editor"],
    )
    assert rec.status_code == 201, rec.text
    rid = rec.json()["id"]
    link = await client.post(f"{API}/packages/{package_id}/recipients/{rid}/bid-link/", headers=people["editor"])
    assert link.status_code == 201, link.text
    return link.json()["url"].rsplit("/bid/", 1)[1], rid


async def _submit(client: AsyncClient, token: str, item: str) -> object:
    return await client.post(f"{API}/bid-portal/{token}/submit/", json={"unit_prices": {item: PRICE}})


async def _pass_deadline(package_id: str) -> None:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.tendering.models import TenderPackage

    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat(timespec="seconds")
    async with async_session_factory() as session:
        await session.execute(
            update(TenderPackage).where(TenderPackage.id == uuid.UUID(package_id)).values(deadline=past)
        )
        await session.commit()


# ── Tests ─────────────────────────────────────────────────────────────────────


async def test_staff_reads_lists_and_exports_hide_sealed_amounts(client, people, bill):
    package_id = await _package(client, people, bill)
    token, _ = await _link(client, people, package_id, "Sealed Erdbau")
    sub = await _submit(client, token, bill["item"])
    assert sub.status_code == 200, sub.text
    # The bidder sees its own sum and the receipt.
    assert sub.json()["bid_amount"] is not None
    assert len(sub.json()["receipt_sha256"]) == 64
    assert sub.json()["received_at"]

    for who in ("editor", "opener_a"):
        headers = people[who]
        for path in (f"/packages/{package_id}", f"/packages/{package_id}/bids/"):
            resp = await client.get(f"{API}{path}", headers=headers)
            assert resp.status_code == 200, resp.text
            assert PRICE not in resp.text and "43219" not in resp.text, (who, path)
        bids = (await client.get(f"{API}/packages/{package_id}/bids/", headers=headers)).json()
        assert bids and all(b["sealed"] and b["total_amount"] == "" and b["line_items"] == [] for b in bids)
        for path in (
            "comparison/",
            "comparison/export/",
            "leveling-matrix/",
            "award-record/",
            "award-record/pdf/",
            "export/pdf/",
        ):
            resp = await client.get(f"{API}/packages/{package_id}/{path}", headers=headers)
            assert resp.status_code in (404, 409), (path, resp.status_code)
            assert PRICE not in resp.text
        analysis = await client.get(f"{API}/bid-analysis/?project_id={bill['project_id']}", headers=headers)
        assert PRICE not in analysis.text

    # Staff cannot enter or edit figures on a sealed package.
    bid_id = bids[0]["id"]
    patch = await client.patch(f"{API}/bids/{bid_id}", json={"total_amount": "1"}, headers=people["opener_a"])
    assert patch.status_code == 409
    manual = await client.post(
        f"{API}/packages/{package_id}/bids/",
        json={"company_name": "Manual", "total_amount": "5"},
        headers=people["opener_a"],
    )
    assert manual.status_code == 409


async def test_other_tenant_cannot_reach_a_sealed_package(client, people, bill):
    package_id = await _package(client, people, bill)
    for path in ("", "/bids/", "/sealed/"):
        resp = await client.get(f"{API}/packages/{package_id}{path}", headers=people["outsider"])
        assert resp.status_code in (403, 404), (path, resp.status_code)
    opened = await client.post(f"{API}/packages/{package_id}/sealed/open/", headers=people["outsider"])
    assert opened.status_code in (403, 404)


async def test_subscribers_and_backup_do_not_receive_sealed_amounts(client, people, bill):
    from app.core.events import event_bus

    seen: list[dict] = []

    async def _capture(event) -> None:  # noqa: ANN001 - bus passes its own event type
        seen.append(dict(getattr(event, "data", None) or {}))

    event_bus.subscribe("tendering.bid.created", _capture)
    try:
        package_id = await _package(client, people, bill)
        token, _ = await _link(client, people, package_id, "Event Bau")
        assert (await _submit(client, token, bill["item"])).status_code == 200
        await asyncio.sleep(0.2)
    finally:
        event_bus.unsubscribe("tendering.bid.created", _capture)
    mine = [e for e in seen if e.get("package_id") == package_id]
    assert mine, seen
    assert all("total_amount" not in e and PRICE not in repr(e) for e in mine)

    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.backup.service import _without_sealed_content
    from app.modules.tendering.models import TenderBid

    async with async_session_factory() as session:
        rows = list(
            (await session.execute(select(TenderBid).where(TenderBid.package_id == uuid.UUID(package_id)))).scalars()
        )
        assert rows
        assert await _without_sealed_content(session, rows) == []


async def test_late_submission_is_refused_not_flagged(client, people, bill):
    package_id = await _package(client, people, bill)
    token, rid = await _link(client, people, package_id, "Late Bau")
    await _pass_deadline(package_id)
    resp = await _submit(client, token, bill["item"])
    assert resp.status_code == 410
    # A link made after the deadline is no way around it in sealed mode.
    fresh = await client.post(f"{API}/packages/{package_id}/recipients/{rid}/bid-link/", headers=people["editor"])
    if fresh.status_code == 201:
        late_token = fresh.json()["url"].rsplit("/bid/", 1)[1]
        assert (await _submit(client, late_token, bill["item"])).status_code == 410
    bids = (await client.get(f"{API}/packages/{package_id}/bids/", headers=people["editor"])).json()
    assert bids == []


async def test_replay_and_revoked_link_are_refused(client, people, bill):
    package_id = await _package(client, people, bill)
    token, _ = await _link(client, people, package_id, "Replay Bau")
    assert (await _submit(client, token, bill["item"])).status_code == 200
    assert (await _submit(client, token, bill["item"])).status_code == 409

    other, _ = await _link(client, people, package_id, "Revoked Bau")
    invitations = (await client.get(f"{API}/packages/{package_id}/bid-invitations/", headers=people["editor"])).json()
    target = next(i for i in invitations["items"] if i["company_name"] == "Revoked Bau")
    revoked = await client.post(
        f"{API}/packages/{package_id}/bid-invitations/{target['id']}/revoke/", headers=people["editor"]
    )
    assert revoked.status_code == 200, revoked.text
    assert (await _submit(client, other, bill["item"])).status_code == 410


async def test_opening_needs_deadline_permission_and_two_people(client, people, bill):
    package_id = await _package(client, people, bill, dual=True)
    token, _ = await _link(client, people, package_id, "Dual Bau")
    assert (await _submit(client, token, bill["item"])).status_code == 200

    early = await client.post(f"{API}/packages/{package_id}/sealed/open/", headers=people["opener_a"])
    assert early.status_code == 409 and early.json()["detail"] == "sealed_deadline_not_passed"

    await _pass_deadline(package_id)
    editor_try = await client.post(f"{API}/packages/{package_id}/sealed/open/", headers=people["editor"])
    assert editor_try.status_code == 403

    first = await client.post(f"{API}/packages/{package_id}/sealed/open/", headers=people["opener_a"])
    assert first.status_code == 200 and first.json()["state"] == "awaiting_second"
    still = await client.get(f"{API}/packages/{package_id}/bids/", headers=people["opener_a"])
    assert PRICE not in still.text

    same = await client.post(f"{API}/packages/{package_id}/sealed/open/", headers=people["opener_a"])
    assert same.status_code == 409 and same.json()["detail"] == "sealed_second_opener_must_differ"

    second = await client.post(f"{API}/packages/{package_id}/sealed/open/", headers=people["opener_b"])
    assert second.status_code == 200 and second.json()["state"] == "opened"

    bids = (await client.get(f"{API}/packages/{package_id}/bids/", headers=people["editor"])).json()
    assert bids and not bids[0]["sealed"] and bids[0]["total_amount"] not in ("", "0")
    comparison = await client.get(f"{API}/packages/{package_id}/comparison/", headers=people["editor"])
    assert comparison.status_code == 200

    from sqlalchemy import select

    from app.core.audit import AuditEntry
    from app.database import async_session_factory

    async with async_session_factory() as session:
        actions = set(
            (
                await session.execute(
                    select(AuditEntry.action).where(
                        AuditEntry.entity_type == "tender_sealed", AuditEntry.entity_id == package_id
                    )
                )
            ).scalars()
        )
    assert {"open_first_approval", "open", "read"} <= actions

    validation = await client.get(f"{API}/packages/{package_id}/sealed/validation/", headers=people["editor"])
    assert validation.status_code == 200, validation.text
    # The test moved the deadline before the receipt, so only the on-time rule may fail.
    failed = {r["rule_id"] for r in validation.json()["results"] if not r["passed"]}
    assert failed == {"tendering_sealed.bid_on_time"}, validation.text


async def test_receipt_hash_verifies_and_detects_tampering(client, people, bill):
    from sqlalchemy import select, update

    from app.database import async_session_factory
    from app.modules.tendering.models import TenderBid
    from app.modules.tendering.sealed import canonical_content

    package_id = await _package(client, people, bill)
    token, _ = await _link(client, people, package_id, "Hash Bau")
    sub = await _submit(client, token, bill["item"])
    receipt = sub.json()["receipt_sha256"]

    async with async_session_factory() as session:
        bid = (
            await session.execute(select(TenderBid).where(TenderBid.package_id == uuid.UUID(package_id)))
        ).scalar_one()
        assert hashlib.sha256(canonical_content(bid)).hexdigest() == receipt
        bid_id = str(bid.id)

    ok = await client.get(f"{API}/bids/{bid_id}/integrity/", headers=people["editor"])
    assert ok.status_code == 200 and ok.json()["intact"] and ok.json()["receipt_sha256"] == receipt
    assert PRICE not in ok.text

    async with async_session_factory() as session:
        await session.execute(update(TenderBid).where(TenderBid.id == uuid.UUID(bid_id)).values(total_amount="1.00"))
        await session.commit()
    bad = await client.get(f"{API}/bids/{bid_id}/integrity/", headers=people["editor"])
    assert bad.status_code == 200 and not bad.json()["intact"]

    view = await client.get(f"{API}/bid-portal/{token}/")
    assert view.json()["receipt_sha256"] == receipt


async def test_mode_rules_deadline_and_existing_bids(client, people, bill):
    resp = await client.post(
        f"{API}/packages/from-boq/",
        json={
            "project_id": bill["project_id"],
            "boq_id": bill["boq_id"],
            "section_ids": [bill["section"]],
            "package_name": "Date only",
            "deadline": (datetime.now(UTC) + timedelta(days=3)).strftime("%Y-%m-%d"),
        },
        headers=people["editor"],
    )
    package_id = resp.json()["id"]
    bad = await client.put(
        f"{API}/packages/{package_id}/submission-mode/", json={"mode": "sealed"}, headers=people["opener_a"]
    )
    assert bad.status_code == 422 and bad.json()["detail"] == "sealed_deadline_needs_time_and_zone"
    editor = await client.put(
        f"{API}/packages/{package_id}/submission-mode/", json={"mode": "sealed"}, headers=people["editor"]
    )
    assert editor.status_code == 403

    sealed_id = await _package(client, people, bill)
    token, _ = await _link(client, people, sealed_id, "Mode Bau")
    assert (await _submit(client, token, bill["item"])).status_code == 200
    back = await client.put(
        f"{API}/packages/{sealed_id}/submission-mode/", json={"mode": "informal"}, headers=people["opener_a"]
    )
    assert back.status_code == 409 and back.json()["detail"] == "sealed_bids_exist"


def test_sealed_rules_flag_a_bid_without_receipt_and_same_user_opening():
    from app.core.validation.engine import ValidationContext
    from app.modules.tendering.validators import SealedBidHasReceipt, SealedDualOpeningDistinct

    data = {
        "mode": "sealed",
        "deadline_ok": True,
        "dual_opening": True,
        "opened": True,
        "first_approver_id": "u1",
        "opened_by": "u1",
        "bids": [{"bid_id": "b1", "has_receipt": False}],
    }
    ctx = ValidationContext(data=data)
    receipt = asyncio.run(SealedBidHasReceipt().validate(ctx))
    dual = asyncio.run(SealedDualOpeningDistinct().validate(ctx))
    assert not receipt[0].passed and not dual[0].passed
