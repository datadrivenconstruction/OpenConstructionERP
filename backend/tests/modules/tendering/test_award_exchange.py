# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The paper trail of a subcontract tender: X83 in, X84 back, X86 out, bill unchanged.

DOMAIN worked example: the issuer's X83 is imported, a firm prices it through
its link by uploading an X84, the buyer awards it, and the X86 is the same bill
(item numbers, units, quantities, texts) with the firm's unit prices. Once a
quantity on the bill is changed the X86 is refused.

Run:
    cd backend
    python -m pytest tests/modules/tendering/test_award_exchange.py -q
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

ITEMS = [
    ("0010", "120.5", "m3", "Excavate trench"),
    ("0020", "80", "m3", "Backfill and compact"),
]
PRICES = {"0010": "21.40", "0020": "9.95"}


def _gaeb(dp: str, items: list[tuple[str, str, str, str]], prices: dict[str, str] | None = None) -> bytes:
    rows = "".join(
        f'<Item RNoPart="{rno}"><Qty>{qty}</Qty><QU>{unit}</QU>'
        + (f"<UP>{prices[rno]}</UP>" if prices and rno in prices else "")
        + f"<Description><CompleteText><OutlineText><OutlTxt><TextOutlTxt><p><span>{text}</span></p>"
        "</TextOutlTxt></OutlTxt></OutlineText></CompleteText></Description></Item>"
        for rno, qty, unit, text in items
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA{dp}/3.3"><GAEBInfo><Version>3.3</Version></GAEBInfo>'
        f"<Award><DP>{dp}</DP><AwardInfo><Cur>EUR</Cur></AwardInfo><BoQ><BoQInfo>"
        "<BoQBkdn><Type>BoQLevel</Type><Length>2</Length><Num>Yes</Num></BoQBkdn>"
        "<BoQBkdn><Type>Item</Type><Length>4</Length><Num>Yes</Num></BoQBkdn></BoQInfo>"
        '<BoQBody><BoQCtgy RNoPart="01"><LblTx><p><span>Earthworks</span></p></LblTx>'
        f"<BoQBody><Itemlist>{rows}</Itemlist></BoQBody></BoQCtgy></BoQBody></BoQ></Award></GAEB>"
    )
    return xml.encode()


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
    email, password = f"awx-{tag}@test.io", f"AwardExch{tag}9"
    await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"Award {tag}", "role": "admin"},
    )
    async with async_session_factory() as session:
        await session.execute(update(User).where(User.email == email.lower()).values(role="admin", is_active=True))
        await session.commit()
    login = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _imported_package(client: AsyncClient, staff: dict[str, str], name: str) -> dict:
    """A project, a bill imported from an X83 and a package over the whole bill."""
    project = await client.post(
        "/api/v1/projects/", json={"name": name, "currency": "EUR", "locale": "de"}, headers=staff
    )
    assert project.status_code in (200, 201), project.text
    project_id = project.json()["id"]
    boq = await client.post("/api/v1/boq/boqs/", json={"project_id": project_id, "name": name}, headers=staff)
    boq_id = boq.json()["id"]
    imported = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/import/gaeb/",
        files={"file": ("tender.X83", _gaeb("83", ITEMS), "application/xml")},
        headers=staff,
    )
    assert imported.status_code in (200, 201), imported.text
    package = await client.post(
        "/api/v1/tendering/packages/from-boq/",
        json={
            "project_id": project_id,
            "boq_id": boq_id,
            "package_name": f"{name} package",
            "deadline": (datetime.now(UTC) + timedelta(days=14)).strftime("%Y-%m-%d"),
        },
        headers=staff,
    )
    assert package.status_code == 201, package.text
    return {"project_id": project_id, "boq_id": boq_id, "package_id": package.json()["id"]}


async def _link(client: AsyncClient, staff: dict[str, str], package_id: str, company: str) -> str:
    recipient = await client.post(
        f"/api/v1/tendering/packages/{package_id}/recipients/",
        json={"company_name": company, "email": f"{uuid.uuid4().hex[:6]}@sub.test"},
        headers=staff,
    )
    assert recipient.status_code == 201, recipient.text
    resp = await client.post(
        f"/api/v1/tendering/packages/{package_id}/recipients/{recipient.json()['id']}/bid-link/", headers=staff
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["url"].rsplit("/bid/", 1)[1]


async def _positions(boq_id: str) -> list:
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.boq.models import Position

    async with async_session_factory() as session:
        return list(
            (await session.execute(select(Position).where(Position.boq_id == uuid.UUID(boq_id)))).scalars().all()
        )


@pytest.fixture(scope="module")
def anyio_backend() -> str:
    return "asyncio"


# ── Tests ─────────────────────────────────────────────────────────────────────


async def test_the_imported_file_is_kept_with_its_hash(client, staff):
    import hashlib

    pkg = await _imported_package(client, staff, "Keep source")
    resp = await client.get(f"/api/v1/tendering/packages/{pkg['package_id']}/bill-source/", headers=staff)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"]["file_sha256"] == hashlib.sha256(_gaeb("83", ITEMS)).hexdigest()
    assert body["source"]["format_id"].startswith("gaeb")
    assert body["changed"] is False
    assert body["differences"] == []
    rule = next(r for r in body["rule_results"] if r["rule_id"] == "tender.bill_changed_since_import")
    assert rule["passed"] is True


async def test_x83_to_x84_to_x86_round_trip(client, staff):
    from app.modules.boq.importers.gaeb_xml import GAEBXMLImporter

    pkg = await _imported_package(client, staff, "Round trip")
    token = await _link(client, staff, pkg["package_id"], "Tiefbau Nord")

    x84 = _gaeb("84", ITEMS, PRICES)
    check = await client.post(
        f"/api/v1/tendering/bid-portal/{token}/x84/check/", files={"file": ("offer.X84", x84, "application/xml")}
    )
    assert check.status_code == 200, check.text
    assert check.json()["blocking"] is False
    assert check.json()["rule_results"]

    sent = await client.post(
        f"/api/v1/tendering/bid-portal/{token}/x84/", files={"file": ("offer.X84", x84, "application/xml")}
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["state"] == "submitted"
    assert [f["kind"] for f in sent.json()["files"]] == ["x84"]

    bids = await client.get(f"/api/v1/tendering/packages/{pkg['package_id']}/bids/", headers=staff)
    bid = next(b for b in bids.json() if b["company_name"] == "Tiefbau Nord")

    award = await client.get(
        f"/api/v1/tendering/packages/{pkg['package_id']}/export/gaeb-x86/",
        params={"bid_id": bid["id"]},
        headers=staff,
    )
    assert award.status_code == 200, award.text
    assert ".X86" in award.headers["content-disposition"]
    assert "<DP>86</DP>" in award.text

    parsed = await GAEBXMLImporter.parse(award.content)
    lines = [p for p in parsed.positions if not p.is_section]
    source = {rno: (qty, unit, text) for rno, qty, unit, text in ITEMS}
    assert len(lines) == len(ITEMS)
    for line in lines:
        rno = line.ordinal.split(".")[-1]
        qty, unit, text = source[rno]
        assert float(line.quantity) == float(qty)
        assert line.unit.lower().replace("³", "3") == unit
        assert text in line.description
        assert f"{float(line.unit_rate):.2f}" == PRICES[rno]

    files = await client.get(f"/api/v1/tendering/packages/{pkg['package_id']}/bid-files/", headers=staff)
    assert files.status_code == 200
    assert files.json()[0]["company_name"] == "Tiefbau Nord"
    assert files.json()[0]["document_id"]


async def test_the_x86_is_refused_once_a_quantity_changed(client, staff):
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.boq.models import Position

    pkg = await _imported_package(client, staff, "Changed bill")
    token = await _link(client, staff, pkg["package_id"], "Erdbau Sued")
    sent = await client.post(
        f"/api/v1/tendering/bid-portal/{token}/x84/",
        files={"file": ("offer.X84", _gaeb("84", ITEMS, PRICES), "application/xml")},
    )
    assert sent.status_code == 200, sent.text
    line = next(p for p in await _positions(pkg["boq_id"]) if p.unit)
    async with async_session_factory() as session:
        await session.execute(update(Position).where(Position.id == line.id).values(quantity="999"))
        await session.commit()

    state = await client.get(f"/api/v1/tendering/packages/{pkg['package_id']}/bill-source/", headers=staff)
    assert state.json()["changed"] is True
    assert state.json()["differences"][0]["field"] == "quantity"
    rule = next(r for r in state.json()["rule_results"] if r["rule_id"] == "tender.bill_changed_since_import")
    assert rule["passed"] is False

    bids = await client.get(f"/api/v1/tendering/packages/{pkg['package_id']}/bids/", headers=staff)
    bid = next(b for b in bids.json() if b["company_name"] == "Erdbau Sued")
    award = await client.get(
        f"/api/v1/tendering/packages/{pkg['package_id']}/export/gaeb-x86/",
        params={"bid_id": bid["id"]},
        headers=staff,
    )
    assert award.status_code == 409, award.text
    assert award.json()["detail"]["code"] == "bill_changed_since_import"


async def test_an_x84_that_changed_a_quantity_shows_the_mismatch_and_is_not_submitted(client, staff):
    pkg = await _imported_package(client, staff, "Mismatch")
    token = await _link(client, staff, pkg["package_id"], "Kanalbau West")
    altered = [("0010", "130", "m3", "Excavate trench"), ITEMS[1]]
    resp = await client.post(
        f"/api/v1/tendering/bid-portal/{token}/x84/",
        files={"file": ("offer.X84", _gaeb("84", altered, PRICES), "application/xml")},
    )
    assert resp.status_code == 422, resp.text
    preview = resp.json()["detail"]["preview"]
    assert any("quantity_changed" in line["issues"] for line in preview["lines"])
    view = await client.get(f"/api/v1/tendering/bid-portal/{token}/")
    assert view.json()["state"] == "open"
    assert view.json()["files"] == []


async def test_a_firm_declines_with_a_reason_and_the_buyer_sees_it(client, staff):
    pkg = await _imported_package(client, staff, "Decline")
    token = await _link(client, staff, pkg["package_id"], "Busy Bau")
    resp = await client.post(f"/api/v1/tendering/bid-portal/{token}/decline/", json={"reason": "No capacity in May"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "declined"
    draft = await client.put(f"/api/v1/tendering/bid-portal/{token}/draft/", json={"unit_prices": {}})
    assert draft.status_code == 409
    assert draft.json()["detail"] == "bid_declined"
    listing = await client.get(f"/api/v1/tendering/packages/{pkg['package_id']}/bid-invitations/", headers=staff)
    row = next(i for i in listing.json()["items"] if i["company_name"] == "Busy Bau")
    assert row["status"] == "declined"
    assert row["decline_reason"] == "No capacity in May"


async def test_offer_files_are_kept_per_firm_and_filed_in_documents(client, staff):
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.documents.models import Document

    pkg = await _imported_package(client, staff, "Offer files")
    token = await _link(client, staff, pkg["package_id"], "Offer Bau")
    resp = await client.post(
        f"/api/v1/tendering/bid-portal/{token}/files/",
        files={"file": ("Angebot.pdf", b"%PDF-1.7\n%offer", "application/pdf")},
        data={"kind": "offer_pdf"},
    )
    assert resp.status_code == 200, resp.text
    assert [f["kind"] for f in resp.json()["files"]] == ["offer_pdf"]
    bad = await client.post(
        f"/api/v1/tendering/bid-portal/{token}/files/",
        files={"file": ("setup.exe", b"MZ\x90\x00" + b"\x00" * 40, "application/octet-stream")},
    )
    assert bad.status_code == 422
    listing = await client.get(f"/api/v1/tendering/packages/{pkg['package_id']}/bid-invitations/", headers=staff)
    row = next(i for i in listing.json()["items"] if i["company_name"] == "Offer Bau")
    assert row["file_count"] == 1
    async with async_session_factory() as session:
        docs = (
            (await session.execute(select(Document).where(Document.project_id == uuid.UUID(pkg["project_id"]))))
            .scalars()
            .all()
        )
    assert any(d.name == "Angebot.pdf" for d in docs)


async def test_request_documents_are_served_only_to_links_of_their_package(client, staff):
    from app.database import async_session_factory
    from app.modules.documents.service import UPLOAD_BASE

    pkg = await _imported_package(client, staff, "Request docs")
    other = await _imported_package(client, staff, "Other docs")
    token = await _link(client, staff, pkg["package_id"], "Doc Bau")
    other_token = await _link(client, staff, other["package_id"], "Other Bau")

    from pathlib import Path

    from app.modules.documents.models import Document

    folder = Path(UPLOAD_BASE) / "awx-tests"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{uuid.uuid4().hex}.pdf"
    path.write_bytes(b"%PDF-1.7\n%conditions")
    async with async_session_factory() as session:
        doc = Document(
            project_id=uuid.UUID(pkg["project_id"]),
            name="Conditions.pdf",
            category="contract",
            file_size=path.stat().st_size,
            mime_type="application/pdf",
            file_path=str(path),
            version=1,
            uploaded_by="",
            tags=[],
            metadata_={},
        )
        session.add(doc)
        await session.commit()
        doc_id = str(doc.id)

    foreign = await client.post(
        f"/api/v1/tendering/packages/{other['package_id']}/documents/", json={"document_ids": [doc_id]}, headers=staff
    )
    assert foreign.status_code == 404

    attached = await client.post(
        f"/api/v1/tendering/packages/{pkg['package_id']}/documents/", json={"document_ids": [doc_id]}, headers=staff
    )
    assert attached.status_code == 200, attached.text
    link_id = attached.json()[0]["id"]

    view = await client.get(f"/api/v1/tendering/bid-portal/{token}/")
    assert [d["name"] for d in view.json()["documents"]] == ["Conditions.pdf"]
    got = await client.get(f"/api/v1/tendering/bid-portal/{token}/documents/{link_id}/")
    assert got.status_code == 200
    assert got.content.startswith(b"%PDF")
    assert got.headers["x-content-type-options"] == "nosniff"
    assert "attachment" in got.headers["content-disposition"]

    assert (await client.get(f"/api/v1/tendering/bid-portal/{other_token}/documents/{link_id}/")).status_code == 404
    assert (await client.get(f"/api/v1/tendering/bid-portal/{token}/documents/{uuid.uuid4()}/")).status_code == 404

    detached = await client.delete(
        f"/api/v1/tendering/packages/{pkg['package_id']}/documents/{link_id}/", headers=staff
    )
    assert detached.status_code == 204
    assert (await client.get(f"/api/v1/tendering/bid-portal/{token}/documents/{link_id}/")).status_code == 404
