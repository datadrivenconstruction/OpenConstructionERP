# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unified parties: the matcher, the backfill, the review list and the link routes.

Run:
    cd backend
    python -m pytest -q -x --no-header tests/modules/contacts/test_unified_parties.py
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.modules.contacts.models import Contact
from app.modules.contacts.parties import (
    build_index,
    match_party,
    normalise_email,
    normalise_name,
    normalise_vat,
    recipient_party,
)


def _contact(**kw) -> Contact:
    return Contact(id=uuid.uuid4(), contact_type="subcontractor", is_active=True, **kw)


# ── Pure matcher ──────────────────────────────────────────────────────────────


def test_normalisers():
    assert normalise_email("  Ann@Alpha.IO ") == "ann@alpha.io"
    assert normalise_email("not-an-email") == ""
    assert normalise_vat("de 123.456-789") == "DE123456789"
    assert normalise_name("  ACME   Bau, GmbH. ") == "acme bau gmbh"


def test_unique_email_links_and_ignores_case():
    a = _contact(company_name="Alpha", primary_email="ann@alpha.io")
    index = build_index([a, _contact(company_name="Beta", primary_email="b@beta.io")])
    result = match_party(index, name="x", email="ANN@alpha.io")
    assert (result.decision, result.method, result.contact_ids) == ("link", "email", (a.id,))
    assert result.confidence == 0.95


def test_vat_links_when_email_is_unknown():
    a = _contact(company_name="Alpha", vat_number="DE 123 456 789")
    result = match_party(build_index([a]), name="Other name", email="who@else.io", vat="de123456789")
    assert (result.decision, result.method, result.contact_ids) == ("link", "vat", (a.id,))


def test_name_alone_is_only_a_suggestion():
    a = _contact(company_name="Alpha", primary_email="a@alpha.io")
    b = _contact(company_name="Gamma Ltd")
    index = build_index([a, b])
    weak = match_party(index, name="gamma ltd.", email="nobody@x.io")
    assert (weak.decision, weak.method, weak.reason, weak.contact_ids) == ("review", "name", "weak", (b.id,))
    assert weak.confidence < 0.95


def test_shared_email_or_name_is_ambiguous_never_linked():
    a = _contact(company_name="Twin", primary_email="t@twin.io")
    b = _contact(company_name="Twin", primary_email="t@twin.io")
    index = build_index([a, b])
    for result in (match_party(index, name="x", email="t@twin.io"), match_party(index, name="Twin", email="")):
        assert result.decision == "review"
        assert result.reason == "ambiguous"
        assert set(result.contact_ids) == {a.id, b.id}


def test_email_and_vat_pointing_at_different_contacts_go_to_review():
    a = _contact(company_name="A", primary_email="a@x.io")
    b = _contact(company_name="B", vat_number="FR99")
    result = match_party(build_index([a, b]), name="A", email="a@x.io", vat="FR99")
    assert result.decision == "review"
    assert set(result.contact_ids) == {a.id, b.id}


def test_no_signal_is_no_match():
    index = build_index([_contact(company_name="A", primary_email="a@x.io")])
    assert match_party(index, name="", email="").decision == "none"


def test_recipient_party_inherits_a_valid_contact_id_only():
    cid = uuid.uuid4()
    assert recipient_party({"contact_id": str(cid)})["contact_id"] == cid
    assert recipient_party({"contact_id": "nonsense"}) == {}
    assert recipient_party({}) == {}


# ── API ───────────────────────────────────────────────────────────────────────


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


@pytest_asyncio.fixture(scope="module")
async def staff(client: AsyncClient) -> dict[str, str]:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    tag = uuid.uuid4().hex[:8]
    email = f"parties-{tag}@test.io"
    password = f"Parties{tag}9"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"Parties {tag}", "role": "admin"},
    )
    assert reg.status_code in (200, 201), reg.text
    async with async_session_factory() as session:
        await session.execute(update(User).where(User.email == email.lower()).values(role="admin", is_active=True))
        await session.commit()
    login = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    token = login.json().get("access_token", "")
    assert token, login.text
    return {"Authorization": f"Bearer {token}"}


async def _contact_api(client: AsyncClient, staff: dict, **fields) -> str:
    resp = await client.post("/api/v1/contacts/", json={"contact_type": "subcontractor", **fields}, headers=staff)
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


async def _invite(client: AsyncClient, staff: dict, package_id: str, company: str, email: str) -> str:
    recipient = await client.post(
        f"/api/v1/tendering/packages/{package_id}/recipients/",
        json={"company_name": company, "email": email},
        headers=staff,
    )
    assert recipient.status_code == 201, recipient.text
    link = await client.post(
        f"/api/v1/tendering/packages/{package_id}/recipients/{recipient.json()['id']}/bid-link/", headers=staff
    )
    assert link.status_code == 201, link.text
    return link.json()["id"]


async def _invitations(client: AsyncClient, staff: dict, package_id: str) -> dict[str, dict]:
    resp = await client.get(f"/api/v1/tendering/packages/{package_id}/bid-invitations/", headers=staff)
    assert resp.status_code == 200, resp.text
    return {i["id"]: i for i in resp.json()["items"]}


@pytest.mark.asyncio
async def test_backfill_review_confirm_unlink_and_validation(client: AsyncClient, staff: dict):
    tag = uuid.uuid4().hex[:6]
    project = await client.post(
        "/api/v1/projects/", json={"name": f"Parties {tag}", "currency": "EUR", "locale": "en"}, headers=staff
    )
    assert project.status_code in (200, 201), project.text
    package = await client.post(
        "/api/v1/tendering/packages/",
        json={"project_id": project.json()["id"], "name": f"Parties package {tag}"},
        headers=staff,
    )
    assert package.status_code in (200, 201), package.text
    package_id = package.json()["id"]

    # Invitations are made first, the directory contacts arrive later: nothing links at mint time.
    late = await _invite(client, staff, package_id, f"Late Co {tag}", f"late-{tag}@firm.test")
    twin = await _invite(client, staff, package_id, f"Twin Co {tag}", f"twin-{tag}@firm.test")
    solo = await _invite(client, staff, package_id, f"Solo Co {tag}", f"solo-{tag}@firm.test")
    nobody = await _invite(client, staff, package_id, f"Nobody Co {tag}", f"nobody-{tag}@firm.test")

    late_contact = await _contact_api(
        client, staff, company_name="Different Legal Name", primary_email=f"LATE-{tag}@firm.test"
    )
    twin_a = await _contact_api(client, staff, company_name=f"Twin Co {tag}", primary_email=f"ta-{tag}@x.test")
    twin_b = await _contact_api(client, staff, company_name=f"Twin Co {tag}", primary_email=f"tb-{tag}@x.test")
    solo_contact = await _contact_api(client, staff, company_name=f"Solo Co {tag}", primary_email=f"s-{tag}@x.test")

    before = await _invitations(client, staff, package_id)
    assert all(i["contact_id"] is None for i in before.values())

    # A dry run changes nothing.
    dry = await client.post("/api/v1/contacts/parties/backfill/", json={"dry_run": True}, headers=staff)
    assert dry.status_code == 200, dry.text
    assert all(i["contact_id"] is None for i in (await _invitations(client, staff, package_id)).values())

    run = await client.post(
        "/api/v1/contacts/parties/backfill/", json={"entity_types": ["tender_invitation"]}, headers=staff
    )
    assert run.status_code == 200, run.text
    after = await _invitations(client, staff, package_id)
    assert after[late]["contact_id"] == late_contact
    assert (after[late]["contact_match_method"], after[late]["contact_match_confidence"]) == ("email", 0.95)
    assert after[late]["contact_name"] == "Different Legal Name"
    # Name-only and ambiguous matches are never linked on their own.
    for key in (twin, solo, nobody):
        assert after[key]["contact_id"] is None
    assert after[solo]["suggestion"]["contact_id"] == solo_contact
    assert after[solo]["suggestion"]["method"] == "name"
    assert after[nobody]["suggestion"] is None

    # Idempotent: a second run adds no review rows and links nothing more.
    reviews = (await client.get("/api/v1/contacts/parties/review/", headers=staff)).json()["items"]
    by_entity: dict[str, list[dict]] = {}
    for r in reviews:
        by_entity.setdefault(r["entity_id"], []).append(r)
    again = await client.post("/api/v1/contacts/parties/backfill/", json={}, headers=staff)
    assert again.status_code == 200
    reviews_again = (await client.get("/api/v1/contacts/parties/review/", headers=staff)).json()["items"]
    assert sorted(r["id"] for r in reviews_again) == sorted(r["id"] for r in reviews)
    assert {r["contact_id"] for r in by_entity[twin]} == {twin_a, twin_b}
    assert all(r["reason"] == "ambiguous" for r in by_entity[twin])

    # A person confirms the solo suggestion; the twin stays unlinked until someone picks.
    review_id = by_entity[solo][0]["id"]
    confirm = await client.post(f"/api/v1/contacts/parties/review/{review_id}/confirm/", headers=staff)
    assert confirm.status_code == 200, confirm.text
    linked = (await _invitations(client, staff, package_id))[solo]
    assert (linked["contact_id"], linked["contact_match_method"], linked["contact_match_confidence"]) == (
        solo_contact,
        "manual",
        1.0,
    )
    repeat = await client.post(f"/api/v1/contacts/parties/review/{review_id}/confirm/", headers=staff)
    assert repeat.status_code == 409

    # Manual link of the twin to one contact.
    put = await client.put(
        f"/api/v1/tendering/packages/{package_id}/bid-invitations/{twin}/party/",
        json={"contact_id": twin_b},
        headers=staff,
    )
    assert put.status_code == 200, put.text
    assert put.json()["contact_id"] == twin_b

    # Validation: only the one still unlinked bidder is warned about.
    validation = (
        await client.get(f"/api/v1/tendering/packages/{package_id}/parties/validation/", headers=staff)
    ).json()
    failed = [r for r in validation["results"] if not r["passed"]]
    assert len(failed) == 1
    assert failed[0]["rule_id"] == "tendering_parties.bidder_has_party"
    assert failed[0]["severity"].lower().endswith("warning")
    assert validation["passed"] is False

    # Unlink: the contact is untouched and the same pair is not re-linked by the next backfill.
    gone = await client.delete(f"/api/v1/tendering/packages/{package_id}/bid-invitations/{late}/party/", headers=staff)
    assert gone.status_code == 200
    assert gone.json()["contact_id"] is None
    await client.post("/api/v1/contacts/parties/backfill/", json={}, headers=staff)
    assert (await _invitations(client, staff, package_id))[late]["contact_id"] is None
    assert (await client.get(f"/api/v1/contacts/{late_contact}", headers=staff)).status_code == 200

    # A contact that does not exist cannot be linked.
    missing = await client.put(
        f"/api/v1/tendering/packages/{package_id}/bid-invitations/{nobody}/party/",
        json={"contact_id": str(uuid.uuid4())},
        headers=staff,
    )
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_backfill_needs_a_login(client: AsyncClient):
    resp = await client.post("/api/v1/contacts/parties/backfill/", json={})
    assert resp.status_code in (401, 403)
