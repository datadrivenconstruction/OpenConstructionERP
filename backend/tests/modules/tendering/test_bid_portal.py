# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bidder price-entry links, end to end against the database.

A subcontractor without an account opens ``/tendering/bid/{token}``, prices the bill and
submits. These tests drive the real routes: staff make the link, an anonymous
client reads and writes through ``/api/v1/tendering/bid-portal/{token}/``, and
the consumer is checked, not just the definition: the submitted prices must
show up in ``GET /packages/{id}/comparison/`` and in the leveling matrix the
buyer reads.

The bill used here has two sections. The package is raised over section A
only, so section B's line is in the same BOQ and still out of scope. Every
buyer rate carries the distinctive figure ``987.654`` so a leak under an
innocent key name is caught by searching the response text, not only the key
names.

Run:
    cd backend
    python -m pytest tests/modules/tendering/test_bid_portal.py -v
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

BUYER_RATE = "987.654"
FORBIDDEN_KEY_PARTS = ("rate", "total", "markup", "resource", "budget", "cost", "metadata", "margin")


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


@pytest_asyncio.fixture(scope="module")
async def staff(client: AsyncClient) -> dict[str, str]:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    tag = uuid.uuid4().hex[:8]
    email = f"bidportal-{tag}@test.io"
    password = f"BidPortal{tag}9"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"Bid Portal {tag}", "role": "admin"},
    )
    assert reg.status_code in (200, 201), reg.text
    async with async_session_factory() as session:
        await session.execute(update(User).where(User.email == email.lower()).values(role="admin", is_active=True))
        await session.commit()
    login = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    token = login.json().get("access_token", "")
    assert token, login.text
    return {"Authorization": f"Bearer {token}"}


async def _add_positions(boq_id: str, rows: list[dict]) -> dict[str, str]:
    """Insert positions straight into the bill; returns ordinal -> id."""
    from app.database import async_session_factory
    from app.modules.boq.models import Position

    ids: dict[str, str] = {}
    async with async_session_factory() as session:
        by_ordinal: dict[str, uuid.UUID] = {}
        for index, row in enumerate(rows):
            pid = uuid.uuid4()
            parent = by_ordinal.get(row.get("parent", ""))
            session.add(
                Position(
                    id=pid,
                    boq_id=uuid.UUID(boq_id),
                    parent_id=parent,
                    ordinal=row["ordinal"],
                    description=row["description"],
                    unit=row.get("unit", ""),
                    quantity=row.get("quantity", "0"),
                    unit_rate=row.get("unit_rate", "0"),
                    total=row.get("total", "0"),
                    sort_order=index,
                    metadata_=row.get("metadata", {}),
                )
            )
            by_ordinal[row["ordinal"]] = pid
            ids[row["ordinal"]] = str(pid)
        await session.commit()
    return ids


@pytest_asyncio.fixture(scope="module")
async def bill(client: AsyncClient, staff: dict[str, str]) -> dict:
    """A project in EUR, a bill with two sections, and a package over section A."""
    project = await client.post(
        "/api/v1/projects/",
        json={"name": "Bid portal tests", "description": "bidder link", "currency": "EUR", "locale": "de"},
        headers=staff,
    )
    assert project.status_code in (200, 201), project.text
    project_id = project.json()["id"]

    boq = await client.post("/api/v1/boq/boqs/", json={"project_id": project_id, "name": "Main bill"}, headers=staff)
    assert boq.status_code in (200, 201), boq.text
    boq_id = boq.json()["id"]

    ids = await _add_positions(
        boq_id,
        [
            {"ordinal": "01", "description": "Earthworks"},
            {
                "ordinal": "01.001",
                "parent": "01",
                "description": "Excavate trench",
                "unit": "m3",
                "quantity": "120.5",
                "unit_rate": BUYER_RATE,
                "total": "119012.31",
                "metadata": {
                    "gaeb_long_text": "Excavate trench in soil class 3-5, depth up to 1.75 m, load and remove spoil.",
                    "resources": [{"name": "Excavator", "cost": BUYER_RATE}],
                },
            },
            {
                "ordinal": "01.002",
                "parent": "01",
                "description": "Backfill and compact",
                "unit": "m3",
                "quantity": "80",
                "unit_rate": BUYER_RATE,
                "total": "79012.32",
            },
            {
                "ordinal": "01.003",
                "parent": "01",
                "description": "Dispose of surplus soil",
                "unit": "t",
                "quantity": "15",
                "unit_rate": BUYER_RATE,
                "total": "14814.81",
            },
            {"ordinal": "02", "description": "Concrete"},
            {
                "ordinal": "02.001",
                "parent": "02",
                "description": "Foundation slab C30/37",
                "unit": "m3",
                "quantity": "40",
                "unit_rate": BUYER_RATE,
                "total": "39506.16",
            },
        ],
    )

    package = await client.post(
        "/api/v1/tendering/packages/from-boq/",
        json={
            "project_id": project_id,
            "boq_id": boq_id,
            "section_ids": [ids["01"]],
            "package_name": "Earthworks package",
            "package_description": "Earthworks for the main building",
            "deadline": (datetime.now(UTC) + timedelta(days=14)).strftime("%Y-%m-%d"),
        },
        headers=staff,
    )
    assert package.status_code == 201, package.text
    package_id = package.json()["id"]

    # A second package over a second bill: its lines must never be accepted by
    # the first package's link.
    other_boq = await client.post(
        "/api/v1/boq/boqs/", json={"project_id": project_id, "name": "Second bill"}, headers=staff
    )
    other_ids = await _add_positions(
        other_boq.json()["id"],
        [
            {"ordinal": "09", "description": "Roofing"},
            {"ordinal": "09.001", "parent": "09", "description": "Roof membrane", "unit": "m2", "quantity": "300"},
        ],
    )
    other_package = await client.post(
        "/api/v1/tendering/packages/from-boq/",
        json={"project_id": project_id, "boq_id": other_boq.json()["id"], "package_name": "Roofing package"},
        headers=staff,
    )
    assert other_package.status_code == 201, other_package.text

    return {
        "project_id": project_id,
        "boq_id": boq_id,
        "package_id": package_id,
        "other_package_id": other_package.json()["id"],
        "ids": ids,
        "other_ids": other_ids,
    }


async def _recipient(client: AsyncClient, staff: dict[str, str], package_id: str, company: str) -> str:
    email = f"{company.lower().replace(' ', '-')}-{uuid.uuid4().hex[:6]}@sub.test"
    resp = await client.post(
        f"/api/v1/tendering/packages/{package_id}/recipients/",
        json={"company_name": company, "email": email},
        headers=staff,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _link(client: AsyncClient, staff: dict[str, str], package_id: str, company: str) -> tuple[str, dict]:
    recipient_id = await _recipient(client, staff, package_id, company)
    resp = await client.post(
        f"/api/v1/tendering/packages/{package_id}/recipients/{recipient_id}/bid-link/", headers=staff
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "/tendering/bid/" in body["url"]
    return body["url"].rsplit("/bid/", 1)[1], body


async def _fresh_package(client: AsyncClient, staff: dict[str, str], bill: dict, name: str, days: int | None) -> str:
    """A package of its own over section A, so a test can move its deadline freely."""
    body: dict = {
        "project_id": bill["project_id"],
        "boq_id": bill["boq_id"],
        "section_ids": [bill["ids"]["01"]],
        "package_name": name,
    }
    if days is not None:
        body["deadline"] = (datetime.now(UTC) + timedelta(days=days)).strftime("%Y-%m-%d")
    resp = await client.post("/api/v1/tendering/packages/from-boq/", json=body, headers=staff)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _set_deadline(package_id: str, deadline: str | None) -> None:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.tendering.models import TenderPackage

    async with async_session_factory() as session:
        await session.execute(
            update(TenderPackage).where(TenderPackage.id == uuid.UUID(package_id)).values(deadline=deadline)
        )
        await session.commit()


async def _backdate_links(package_id: str, days: int) -> None:
    """Pretend every link of a package was made ``days`` ago."""
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.tendering.models import TenderBidInvitation

    async with async_session_factory() as session:
        await session.execute(
            update(TenderBidInvitation)
            .where(TenderBidInvitation.package_id == uuid.UUID(package_id))
            .values(created_at=datetime.now(UTC) - timedelta(days=days))
        )
        await session.commit()


def _yesterday() -> str:
    return (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")


async def _bids_of(client: AsyncClient, staff: dict[str, str], package_id: str, company: str) -> list[dict]:
    resp = await client.get(f"/api/v1/tendering/packages/{package_id}/bids/", headers=staff)
    assert resp.status_code == 200, resp.text
    return [b for b in resp.json() if b["company_name"] == company]


def _keys(value: object) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, inner in value.items():
            found.append(str(key))
            found.extend(_keys(inner))
    elif isinstance(value, list):
        for inner in value:
            found.extend(_keys(inner))
    return found


# ── Tests ─────────────────────────────────────────────────────────────────────


async def test_the_token_is_stored_only_as_its_hash(client, staff, bill):
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.tendering.models import TenderBidInvitation

    token, created = await _link(client, staff, bill["package_id"], "Hash Erdbau")
    assert len(token) >= 40
    async with async_session_factory() as session:
        row = (
            await session.execute(select(TenderBidInvitation).where(TenderBidInvitation.id == uuid.UUID(created["id"])))
        ).scalar_one()
    assert row.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert token not in repr(row.__dict__)

    # The listing never hands the token back.
    listing = await client.get(f"/api/v1/tendering/packages/{bill['package_id']}/bid-invitations/", headers=staff)
    assert listing.status_code == 200, listing.text
    assert token not in listing.text
    mine = [item for item in listing.json()["items"] if item["id"] == created["id"]]
    assert mine and mine[0]["status"] == "not_opened"


async def test_the_public_view_carries_no_buyer_pricing(client, staff, bill):
    token, _ = await _link(client, staff, bill["package_id"], "Leak Probe Bau")

    resp = await client.get(f"/api/v1/tendering/bid-portal/{token}/")  # no auth header
    assert resp.status_code == 200, resp.text
    body = resp.json()

    leaked = sorted({k for k in _keys(body) if any(part in k.lower() for part in FORBIDDEN_KEY_PARTS)})
    assert leaked == [], f"public payload exposes buyer-side keys: {leaked}"
    assert BUYER_RATE not in resp.text
    for gc_total in ("119012.31", "79012.32", "14814.81", "39506.16"):
        assert gc_total not in resp.text
    assert "Excavator" not in resp.text
    assert resp.headers.get("cache-control") == "no-store"

    # The bill as the bidder needs it: the heading, the three in-scope lines in
    # order, quantities and long text. Section B is out of scope.
    lines = body["lines"]
    assert [(line["kind"], line["ordinal"]) for line in lines] == [
        ("section", "01"),
        ("item", "01.001"),
        ("item", "01.002"),
        ("item", "01.003"),
    ]
    first = lines[1]
    assert (first["unit"], first["quantity"]) == ("m3", "120.5")
    assert first["long_text"].startswith("Excavate trench in soil class")
    assert body["currency"] == "EUR"
    assert body["package_name"] == "Earthworks package"
    assert body["bidder_company"] == "Leak Probe Bau"
    assert body["state"] == "open"
    assert (body["item_count"], body["unpriced_count"]) == (3, 3)

    # Opening is recorded for the buyer.
    listing = await client.get(f"/api/v1/tendering/packages/{bill['package_id']}/bid-invitations/", headers=staff)
    statuses = {item["company_name"]: item["status"] for item in listing.json()["items"]}
    assert statuses["Leak Probe Bau"] == "opened"


async def test_a_submitted_bid_reaches_the_comparison_and_the_leveling(client, staff, bill):
    token, created = await _link(client, staff, bill["package_id"], "Submit Tiefbau")
    ids = bill["ids"]

    draft = await client.put(
        f"/api/v1/tendering/bid-portal/{token}/draft/",
        json={"unit_prices": {ids["01.001"]: "45.10"}, "notes": "Valid 60 days", "currency": "EUR"},
    )
    assert draft.status_code == 200, draft.text
    assert draft.json()["draft"]["unit_prices"] == {ids["01.001"]: "45.10"}

    # The draft survives a reload.
    reread = await client.get(f"/api/v1/tendering/bid-portal/{token}/")
    assert reread.json()["draft"]["unit_prices"] == {ids["01.001"]: "45.10"}
    assert reread.json()["draft"]["notes"] == "Valid 60 days"

    submit = await client.post(
        f"/api/v1/tendering/bid-portal/{token}/submit/",
        json={"unit_prices": {ids["01.001"]: "45.10", ids["01.002"]: 12.5, ids["01.003"]: ""}, "currency": "EUR"},
    )
    assert submit.status_code == 200, submit.text
    receipt = submit.json()
    assert receipt["state"] == "submitted"
    assert receipt["unpriced_count"] == 1
    # 120.5 x 45.10 + 80 x 12.5 = 5434.55 + 1000.00
    assert receipt["bid_amount"] == "6434.55"

    comparison = await client.get(f"/api/v1/tendering/packages/{bill['package_id']}/comparison/", headers=staff)
    assert comparison.status_code == 200, comparison.text
    data = comparison.json()
    totals = [bt for bt in data["bid_totals"] if bt["company_name"] == "Submit Tiefbau"]
    assert len(totals) == 1
    assert totals[0]["total"] == 6434.55
    assert totals[0]["currency"] == "EUR"
    assert totals[0]["status"] == "submitted"
    bid_id = totals[0]["bid_id"]
    rows = {row["position_id"]: row for row in data["rows"]}
    cell = next(b for b in rows[ids["01.001"]]["bids"] if b["bid_id"] == bid_id)
    assert cell["unit_rate"] == 45.1
    assert cell["total"] == 5434.55
    cell = next(b for b in rows[ids["01.002"]]["bids"] if b["bid_id"] == bid_id)
    assert cell["unit_rate"] == 12.5

    matrix = await client.get(f"/api/v1/tendering/packages/{bill['package_id']}/leveling-matrix/", headers=staff)
    assert matrix.status_code == 200, matrix.text
    mrows = {row["position_id"]: row for row in matrix.json()["rows"]}
    status_of = {
        pid: next(c["status"] for c in mrows[pid]["cells"] if c["bid_id"] == bid_id)
        for pid in (ids["01.001"], ids["01.002"], ids["01.003"])
    }
    assert status_of == {ids["01.001"]: "matched", ids["01.002"]: "matched", ids["01.003"]: "imputed"}

    # The link is read-only now: a second submit and a draft save are refused,
    # and no second bid appears.
    again = await client.post(
        f"/api/v1/tendering/bid-portal/{token}/submit/", json={"unit_prices": {ids["01.001"]: "1"}}
    )
    assert again.status_code == 409, again.text
    assert again.json()["detail"] == "bid_already_submitted"
    late_draft = await client.put(
        f"/api/v1/tendering/bid-portal/{token}/draft/", json={"unit_prices": {ids["01.001"]: "1"}}
    )
    assert late_draft.status_code == 409
    view = await client.get(f"/api/v1/tendering/bid-portal/{token}/")
    assert view.json()["state"] == "submitted"
    assert view.json()["bid_amount"] == "6434.55"
    bids = await client.get(f"/api/v1/tendering/packages/{bill['package_id']}/bids/", headers=staff)
    assert [b["company_name"] for b in bids.json()].count("Submit Tiefbau") == 1

    listing = await client.get(f"/api/v1/tendering/packages/{bill['package_id']}/bid-invitations/", headers=staff)
    mine = next(item for item in listing.json()["items"] if item["id"] == created["id"])
    assert mine["status"] == "submitted"
    assert mine["bid_id"] == bid_id


async def test_a_left_out_line_and_a_zero_price_read_differently_in_the_comparison(client, staff, bill):
    """Blank means not offered, 0 means offered for nothing: compare must keep them apart."""
    token, _ = await _link(client, staff, bill["package_id"], "Zero Price Bau")
    ids = bill["ids"]

    submit = await client.post(
        f"/api/v1/tendering/bid-portal/{token}/submit/",
        json={"unit_prices": {ids["01.001"]: "20", ids["01.002"]: "0", ids["01.003"]: ""}, "currency": "EUR"},
    )
    assert submit.status_code == 200, submit.text
    receipt = submit.json()
    assert receipt["unpriced_count"] == 1
    # 120.5 x 20 + 80 x 0
    assert receipt["bid_amount"] == "2410.00"

    comparison = await client.get(f"/api/v1/tendering/packages/{bill['package_id']}/comparison/", headers=staff)
    assert comparison.status_code == 200, comparison.text
    data = comparison.json()
    totals = next(bt for bt in data["bid_totals"] if bt["company_name"] == "Zero Price Bau")
    bid_id = totals["bid_id"]
    rows = {row["position_id"]: row for row in data["rows"]}

    def cell(ordinal: str) -> dict:
        return next(b for b in rows[ids[ordinal]]["bids"] if b["bid_id"] == bid_id)

    assert cell("01.001")["priced"] is True
    assert cell("01.001")["unit_rate"] == 20
    zero = cell("01.002")
    assert zero["priced"] is True
    assert zero["unit_rate"] == 0
    assert zero["total"] == 0
    left_out = cell("01.003")
    assert left_out["priced"] is False
    assert left_out["unit_rate"] is None
    assert left_out["total"] is None

    # Two of the package's three priceable lines carry a price, the zero included.
    assert (totals["matched_lines"], totals["total_lines"]) == (2, 3)
    assert totals["total"] == 2410.0


async def test_only_an_explicit_reopen_lets_a_submitted_firm_change_its_bid(client, staff, bill):
    """A new link alone is a receipt; ``reopen=true`` is the buyer's deliberate reopen."""
    ids = bill["ids"]
    base = f"/api/v1/tendering/packages/{bill['package_id']}/recipients"
    recipient_id = await _recipient(client, staff, bill["package_id"], "Reopen Bau")
    first = await client.post(f"{base}/{recipient_id}/bid-link/", headers=staff)
    token = first.json()["url"].rsplit("/bid/", 1)[1]
    sub = await client.post(
        f"/api/v1/tendering/bid-portal/{token}/submit/", json={"unit_prices": {ids["01.001"]: "10"}}
    )
    assert sub.status_code == 200, sub.text

    # Copying the link again without reopening hands out a read-only receipt.
    second = await client.post(f"{base}/{recipient_id}/bid-link/", headers=staff)
    assert second.status_code == 201
    assert (second.json()["replaced_count"], second.json()["status"]) == (1, "submitted")
    receipt_token = second.json()["url"].rsplit("/bid/", 1)[1]
    receipt = await client.get(f"/api/v1/tendering/bid-portal/{receipt_token}/")
    assert (receipt.json()["state"], receipt.json()["bid_amount"]) == ("submitted", "1205.00")
    refused = await client.post(
        f"/api/v1/tendering/bid-portal/{receipt_token}/submit/", json={"unit_prices": {ids["01.001"]: "1"}}
    )
    assert (refused.status_code, refused.json()["detail"]) == (409, "bid_already_submitted")

    third = await client.post(f"{base}/{recipient_id}/bid-link/?reopen=true", headers=staff)
    assert third.status_code == 201
    assert third.json()["status"] == "not_opened"
    new_token = third.json()["url"].rsplit("/bid/", 1)[1]

    old = await client.get(f"/api/v1/tendering/bid-portal/{token}/")
    assert (old.status_code, old.json()["detail"]) == (410, "bid_link_revoked")
    reopened = await client.get(f"/api/v1/tendering/bid-portal/{new_token}/")
    assert reopened.json()["state"] == "open"
    assert reopened.json()["draft"]["unit_prices"] == {ids["01.001"]: "10"}

    resub = await client.post(
        f"/api/v1/tendering/bid-portal/{new_token}/submit/", json={"unit_prices": {ids["01.001"]: "11"}}
    )
    assert resub.status_code == 200, resub.text
    mine = await _bids_of(client, staff, bill["package_id"], "Reopen Bau")
    assert len(mine) == 1
    assert mine[0]["total_amount"] == "1325.50"
    # What the reopen replaced is kept on the bid.
    revisions = mine[0]["metadata"]["revisions"]
    assert [r["total_amount"] for r in revisions] == ["1205.00"]
    assert revisions[0]["line_items"][0]["position_id"] == ids["01.001"]
    assert revisions[0]["submitted_at"]


async def test_distributing_again_after_a_submit_keeps_the_bid_closed(client, staff, bill, monkeypatch):
    """Another distribution run must not hand a submitted firm a writable link."""
    import app.core.email as email_pkg

    sent: list = []

    class _Result:
        ok = True
        reason = "captured"

    class _Capture:
        backend_name = "capture"

        async def send(self, message):
            sent.append(message)
            return _Result()

    monkeypatch.setattr(email_pkg, "get_email_service", lambda: _Capture())
    package_id = await _fresh_package(client, staff, bill, "Redistributed package", days=14)
    ids = bill["ids"]
    token, _ = await _link(client, staff, package_id, "Closed Bau")
    sub = await client.post(
        f"/api/v1/tendering/bid-portal/{token}/submit/", json={"unit_prices": {ids["01.001"]: "10"}}
    )
    assert sub.status_code == 200, sub.text

    resp = await client.post(
        f"/api/v1/tendering/packages/{package_id}/distribute/", json={"resend": True}, headers=staff
    )
    assert resp.status_code == 200, resp.text
    mail = next(m for m in sent if "closed-bau" in m.to)
    new_token = mail.html_body.split("/bid/", 1)[1].split('"', 1)[0]
    assert new_token != token

    view = await client.get(f"/api/v1/tendering/bid-portal/{new_token}/")
    assert view.status_code == 200, view.text
    assert (view.json()["state"], view.json()["bid_amount"]) == ("submitted", "1205.00")
    for method, path in (("put", "draft/"), ("post", "submit/")):
        resp = await getattr(client, method)(
            f"/api/v1/tendering/bid-portal/{new_token}/{path}", json={"unit_prices": {ids["01.001"]: "1"}}
        )
        assert (resp.status_code, resp.json()["detail"]) == (409, "bid_already_submitted")

    mine = await _bids_of(client, staff, package_id, "Closed Bau")
    assert [b["total_amount"] for b in mine] == ["1205.00"]
    listing = await client.get(f"/api/v1/tendering/packages/{package_id}/bid-invitations/", headers=staff)
    assert listing.json()["items"][0]["status"] == "submitted"


async def test_a_deadline_cuts_links_made_while_the_tender_ran(client, staff, bill):
    ids = bill["ids"]

    # Moved earlier: the link made three days ago stops at the new deadline.
    earlier = await _fresh_package(client, staff, bill, "Deadline moved earlier", days=14)
    token, _ = await _link(client, staff, earlier, "Early Cut Bau")
    await _backdate_links(earlier, days=3)
    assert (await client.get(f"/api/v1/tendering/bid-portal/{token}/")).status_code == 200
    await _set_deadline(earlier, _yesterday())
    for method, path in (("get", ""), ("put", "draft/"), ("post", "submit/")):
        kwargs = {} if method == "get" else {"json": {"unit_prices": {ids["01.001"]: "5"}}}
        resp = await getattr(client, method)(f"/api/v1/tendering/bid-portal/{token}/{path}", **kwargs)
        assert (resp.status_code, resp.json()["detail"]) == (410, "bid_link_expired")
        assert "Earthworks" not in resp.text

    # No deadline when the link was made; one set later cuts it just the same.
    open_ended = await _fresh_package(client, staff, bill, "Deadline set later", days=None)
    token, _ = await _link(client, staff, open_ended, "No Deadline Bau")
    await _backdate_links(open_ended, days=3)
    assert (await client.get(f"/api/v1/tendering/bid-portal/{token}/")).status_code == 200
    await _set_deadline(open_ended, _yesterday())
    resp = await client.post(
        f"/api/v1/tendering/bid-portal/{token}/submit/", json={"unit_prices": {ids["01.001"]: "5"}}
    )
    assert (resp.status_code, resp.json()["detail"]) == (410, "bid_link_expired")
    assert await _bids_of(client, staff, open_ended, "No Deadline Bau") == []

    # A link the buyer makes after the deadline is a deliberate late invitation:
    # it works, and the bid it brings in is marked late.
    late_token, _ = await _link(client, staff, open_ended, "Late Invite Bau")
    resp = await client.post(
        f"/api/v1/tendering/bid-portal/{late_token}/submit/", json={"unit_prices": {ids["01.001"]: "5"}}
    )
    assert resp.status_code == 200, resp.text
    (late_bid,) = await _bids_of(client, staff, open_ended, "Late Invite Bau")
    assert late_bid["metadata"]["late"] is True

    on_time_token, _ = await _link(client, staff, bill["package_id"], "On Time Bau")
    await client.post(
        f"/api/v1/tendering/bid-portal/{on_time_token}/submit/", json={"unit_prices": {ids["01.001"]: "5"}}
    )
    (on_time,) = await _bids_of(client, staff, bill["package_id"], "On Time Bau")
    assert on_time["metadata"]["late"] is False


async def test_an_older_link_submitting_mid_send_does_not_add_a_second_bid(client, staff, bill):
    """The new link has no bid yet when the old one submits; its submit must find that bid."""
    from app.database import async_session_factory
    from app.modules.tendering.bid_portal import BidPortalService
    from app.modules.tendering.models import TenderPackage

    ids = bill["ids"]
    recipient_id = await _recipient(client, staff, bill["package_id"], "Race Bau")
    first = await client.post(
        f"/api/v1/tendering/packages/{bill['package_id']}/recipients/{recipient_id}/bid-link/", headers=staff
    )
    old_token = first.json()["url"].rsplit("/bid/", 1)[1]

    # Distribution mints the new link and only retires the old one after the
    # email went out; both are live in between.
    async with async_session_factory() as session:
        package = await session.get(TenderPackage, uuid.UUID(bill["package_id"]))
        recipient = {"id": recipient_id, "company_name": "Race Bau", "email": "race@sub.test"}
        _, new_token = await BidPortalService(session).mint(package, recipient, actor_id=None)
        await session.commit()

    old = await client.post(
        f"/api/v1/tendering/bid-portal/{old_token}/submit/", json={"unit_prices": {ids["01.001"]: "10"}}
    )
    assert old.status_code == 200, old.text
    new = await client.post(
        f"/api/v1/tendering/bid-portal/{new_token}/submit/", json={"unit_prices": {ids["01.001"]: "12"}}
    )
    assert new.status_code == 200, new.text

    mine = await _bids_of(client, staff, bill["package_id"], "Race Bau")
    assert len(mine) == 1
    assert mine[0]["total_amount"] == "1446.00"
    assert [r["total_amount"] for r in mine[0]["metadata"]["revisions"]] == ["1205.00"]


async def test_the_receipt_shows_what_the_firm_submitted_not_later_buyer_edits(client, staff, bill):
    token, _ = await _link(client, staff, bill["package_id"], "Receipt Bau")
    sub = await client.post(
        f"/api/v1/tendering/bid-portal/{token}/submit/", json={"unit_prices": {bill["ids"]["01.001"]: "10"}}
    )
    assert sub.status_code == 200, sub.text
    (bid,) = await _bids_of(client, staff, bill["package_id"], "Receipt Bau")
    edit = await client.patch(f"/api/v1/tendering/bids/{bid['id']}", json={"total_amount": "4242424.00"}, headers=staff)
    assert edit.status_code == 200, edit.text

    view = await client.get(f"/api/v1/tendering/bid-portal/{token}/")
    assert view.json()["bid_amount"] == "1205.00"
    assert "4242424" not in view.text


async def test_the_bid_currency_is_the_tenders_never_the_bidders(client, staff, bill):
    """With no currency on the buyer's side the bid stays unknown, whatever the bidder sends."""
    from sqlalchemy import select, update

    from app.database import async_session_factory
    from app.modules.projects.models import Project

    project_uuid = uuid.UUID(bill["project_id"])
    async with async_session_factory() as session:
        original = (await session.execute(select(Project.currency).where(Project.id == project_uuid))).scalar_one()
        await session.execute(update(Project).where(Project.id == project_uuid).values(currency=""))
        await session.commit()
    try:
        # Raised while the project names no currency, so the package records none either.
        package_id = await _fresh_package(client, staff, bill, "No currency package", days=14)
        token, _ = await _link(client, staff, package_id, "Currency Pick Bau")
        resp = await client.post(
            f"/api/v1/tendering/bid-portal/{token}/submit/",
            json={"unit_prices": {bill["ids"]["01.001"]: "10"}, "currency": "JPY"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["currency"] == ""
    finally:
        async with async_session_factory() as session:
            await session.execute(update(Project).where(Project.id == project_uuid).values(currency=original))
            await session.commit()
    (bid,) = await _bids_of(client, staff, package_id, "Currency Pick Bau")
    assert bid["currency"] == ""


async def test_minus_zero_is_stored_as_zero(client, staff, bill):
    from app.modules.tendering.bid_portal import parse_unit_price

    assert format(parse_unit_price("-0"), "f") == "0"
    assert format(parse_unit_price("-0.00"), "f") == "0.00"

    token, _ = await _link(client, staff, bill["package_id"], "Minus Zero Bau")
    draft = await client.put(
        f"/api/v1/tendering/bid-portal/{token}/draft/", json={"unit_prices": {bill["ids"]["01.001"]: "-0"}}
    )
    assert draft.status_code == 200, draft.text
    assert draft.json()["draft"]["unit_prices"] == {bill["ids"]["01.001"]: "0"}


async def test_a_recipient_without_an_id_gets_no_link(client, staff, bill):
    from app.database import async_session_factory
    from app.modules.tendering.bid_portal import BidPortalService, usable_recipient_id
    from app.modules.tendering.models import TenderPackage

    for missing in (None, "", " ", "None", "null", 0, "0", False):
        assert usable_recipient_id(missing) is None
    assert usable_recipient_id("r-1") == "r-1"

    for rid in ("0", "None"):
        resp = await client.post(
            f"/api/v1/tendering/packages/{bill['package_id']}/recipients/{rid}/bid-link/", headers=staff
        )
        assert (resp.status_code, resp.json()["detail"]) == (422, "recipient_without_id")

    async with async_session_factory() as session:
        package = await session.get(TenderPackage, uuid.UUID(bill["package_id"]))
        with pytest.raises(ValueError, match="recipient_without_id"):
            await BidPortalService(session).mint(package, {"id": None, "company_name": "X"}, actor_id=None)


async def test_revoked_expired_and_unknown_links_are_refused(client, staff, bill):
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.tendering.models import TenderBidInvitation, TenderPackage

    unknown = await client.get("/api/v1/tendering/bid-portal/not-a-real-token-at-all/")
    assert (unknown.status_code, unknown.json()["detail"]) == (404, "bid_link_not_found")

    token, created = await _link(client, staff, bill["package_id"], "Revoked Bau")
    revoke = await client.post(
        f"/api/v1/tendering/packages/{bill['package_id']}/bid-invitations/{created['id']}/revoke/", headers=staff
    )
    assert revoke.status_code == 200, revoke.text
    assert revoke.json()["status"] == "revoked"
    for method, path in (("get", ""), ("put", "draft/"), ("post", "submit/")):
        kwargs = {} if method == "get" else {"json": {"unit_prices": {}}}
        resp = await getattr(client, method)(f"/api/v1/tendering/bid-portal/{token}/{path}", **kwargs)
        assert (resp.status_code, resp.json()["detail"]) == (410, "bid_link_revoked")
        assert "Earthworks" not in resp.text

    # Expired: the stored expiry has passed and the deadline gives no reprieve.
    token, created = await _link(client, staff, bill["package_id"], "Expired Bau")
    past = datetime.now(UTC) - timedelta(days=1)
    async with async_session_factory() as session:
        await session.execute(
            update(TenderBidInvitation)
            .where(TenderBidInvitation.id == uuid.UUID(created["id"]))
            .values(expires_at=past)
        )
        await session.commit()
    # The package deadline is still ahead, so moving it later keeps links alive.
    alive = await client.get(f"/api/v1/tendering/bid-portal/{token}/")
    assert alive.status_code == 200, alive.text

    original_deadline = None
    async with async_session_factory() as session:
        package = await session.get(TenderPackage, uuid.UUID(bill["package_id"]))
        original_deadline = package.deadline
        await session.execute(
            update(TenderPackage)
            .where(TenderPackage.id == uuid.UUID(bill["package_id"]))
            .values(deadline=(past - timedelta(days=1)).strftime("%Y-%m-%d"))
        )
        await session.commit()
    try:
        expired = await client.post(
            f"/api/v1/tendering/bid-portal/{token}/submit/", json={"unit_prices": {bill["ids"]["01.001"]: "5"}}
        )
        assert (expired.status_code, expired.json()["detail"]) == (410, "bid_link_expired")
        listing = await client.get(f"/api/v1/tendering/packages/{bill['package_id']}/bid-invitations/", headers=staff)
        assert next(i for i in listing.json()["items"] if i["id"] == created["id"])["status"] == "expired"
    finally:
        async with async_session_factory() as session:
            await session.execute(
                update(TenderPackage)
                .where(TenderPackage.id == uuid.UUID(bill["package_id"]))
                .values(deadline=original_deadline)
            )
            await session.commit()


@pytest.mark.parametrize(
    ("label", "value", "reason"),
    [
        ("negative", "-1", "negative"),
        ("not a number", "NaN", "not_a_number"),
        ("infinity", "Infinity", "not_a_number"),
        ("signalling nan", "sNaN", "not_a_number"),
        ("text", "twelve", "not_a_number"),
        ("too many decimals", "1.123456", "too_many_decimals"),
        ("absurd", "1e15", "too_large"),
        ("boolean", True, "not_a_number"),
    ],
)
async def test_unusable_prices_are_refused(client, staff, bill, label, value, reason):
    token, _ = await _link(client, staff, bill["package_id"], f"Bad Price {label}")
    resp = await client.post(
        f"/api/v1/tendering/bid-portal/{token}/submit/", json={"unit_prices": {bill["ids"]["01.001"]: value}}
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "invalid_unit_prices"
    assert detail["errors"] == [{"line_id": bill["ids"]["01.001"], "reason": reason}]
    # Nothing was written.
    view = await client.get(f"/api/v1/tendering/bid-portal/{token}/")
    assert view.json()["state"] == "open"


async def test_lines_outside_the_package_are_refused(client, staff, bill):
    token, _ = await _link(client, staff, bill["package_id"], "Scope Bau")
    for foreign in (bill["ids"]["02.001"], bill["other_ids"]["09.001"], bill["ids"]["01"], str(uuid.uuid4())):
        resp = await client.put(
            f"/api/v1/tendering/bid-portal/{token}/draft/",
            json={"unit_prices": {bill["ids"]["01.001"]: "10", foreign: "10"}},
        )
        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"]["errors"] == [{"line_id": foreign, "reason": "not_in_package"}]
    view = await client.get(f"/api/v1/tendering/bid-portal/{token}/")
    assert view.json()["draft"]["unit_prices"] == {}


async def test_a_foreign_currency_and_an_empty_bid_are_refused(client, staff, bill):
    token, _ = await _link(client, staff, bill["package_id"], "Currency Bau")
    wrong = await client.post(
        f"/api/v1/tendering/bid-portal/{token}/submit/",
        json={"unit_prices": {bill["ids"]["01.001"]: "10"}, "currency": "USD"},
    )
    assert wrong.status_code == 422, wrong.text
    assert wrong.json()["detail"] == {"code": "currency_mismatch", "expected": "EUR"}

    empty = await client.post(
        f"/api/v1/tendering/bid-portal/{token}/submit/",
        json={"unit_prices": {bill["ids"]["01.001"]: "", bill["ids"]["01.002"]: None}},
    )
    assert (empty.status_code, empty.json()["detail"]) == (422, "nothing_priced")


async def test_staff_cannot_revoke_another_packages_link_through_their_own(client, staff, bill):
    _, other = await _link(client, staff, bill["other_package_id"], "Other Package Bau")
    resp = await client.post(
        f"/api/v1/tendering/packages/{bill['package_id']}/bid-invitations/{other['id']}/revoke/", headers=staff
    )
    assert resp.status_code == 404


async def test_removing_a_recipient_kills_its_link(client, staff, bill):
    recipient_id = await _recipient(client, staff, bill["package_id"], "Removed Bau")
    made = await client.post(
        f"/api/v1/tendering/packages/{bill['package_id']}/recipients/{recipient_id}/bid-link/", headers=staff
    )
    token = made.json()["url"].rsplit("/bid/", 1)[1]
    removed = await client.delete(
        f"/api/v1/tendering/packages/{bill['package_id']}/recipients/{recipient_id}", headers=staff
    )
    assert removed.status_code == 204, removed.text
    resp = await client.get(f"/api/v1/tendering/bid-portal/{token}/")
    assert (resp.status_code, resp.json()["detail"]) == (410, "bid_link_revoked")


async def test_the_staff_routes_need_a_login(client, bill):
    resp = await client.get(f"/api/v1/tendering/packages/{bill['package_id']}/bid-invitations/")
    assert resp.status_code in (401, 403)


async def test_distribution_emails_the_public_link_in_the_project_language(client, staff, bill, monkeypatch):
    """The email carries a working bidder link, not the internal /tendering route."""
    import app.core.email as email_pkg

    sent: list = []

    class _Result:
        ok = True
        reason = "captured"

    class _Capture:
        backend_name = "capture"

        async def send(self, message):
            sent.append(message)
            return _Result()

    monkeypatch.setattr(email_pkg, "get_email_service", lambda: _Capture())

    await _recipient(client, staff, bill["package_id"], "Mail Bau")
    resp = await client.post(f"/api/v1/tendering/packages/{bill['package_id']}/distribute/", json={}, headers=staff)
    assert resp.status_code == 200, resp.text
    mail = next(m for m in sent if "mail-bau" in m.to)
    assert "/tendering?package=" not in mail.html_body
    assert "/tendering/bid/" in mail.html_body
    # The project is German, so the email is.
    assert mail.subject == "Aufforderung zur Angebotsabgabe: Earthworks package"
    token = mail.html_body.split("/bid/", 1)[1].split('"', 1)[0]
    view = await client.get(f"/api/v1/tendering/bid-portal/{token}/")
    assert view.status_code == 200, view.text
    assert view.json()["bidder_company"] == "Mail Bau"
