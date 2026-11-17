# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Issuing generic documents: invoice and change order PDFs, mandatory data, the issue log."""

from __future__ import annotations

import io
import json
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from app.modules.changeorders.models import ChangeOrder, ChangeOrderItem
from app.modules.contacts.models import Contact
from app.modules.doc_templates.models import DocTemplateIssue
from app.modules.finance.models import Invoice, InvoiceLineItem
from app.modules.projects.models import Project
from tests.modules.doc_templates.test_doc_templates_api import _app, _http, _publish, _user, db_session  # noqa: F401

INVOICE = "finance.invoice"
CHANGE_ORDER = "changeorders.change_order"

_PROFILE = {
    "legal_name": "Muster Hochbau GmbH",
    "address": "Hauptstr. 1\n10115 Berlin",
    "vat_id": "DE123456789",
    "tax_number": "",
    "registration_line": "",
    "email": "",
    "phone": "",
    "website": "",
    "document_logo_data_url": "",
    "document_logo_png_data_url": "",
}
_DE_FILE = (
    Path(__file__).resolve().parents[4]
    / "packs"
    / "germany-de"
    / "src"
    / "openconstructionerp_germany_de"
    / "document_requirements.json"
)


def _text(pdf: bytes) -> str:
    from pypdf import PdfReader

    return "".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf)).pages)


@pytest.fixture
def german_market(monkeypatch):
    from app.core.company_profile import DEFAULT_COMPANY_PROFILE
    from app.core.doc_templates import legal
    from app.modules.doc_templates import service as dt_service

    profile = dict(DEFAULT_COMPANY_PROFILE) | _PROFILE

    async def _countries(*_a, **_k):
        return ["DE"]

    monkeypatch.setattr("app.core.company_profile.read_company_profile", lambda *_a, **_k: dict(profile))
    monkeypatch.setattr(dt_service, "workspace_countries", _countries)
    monkeypatch.setattr(dt_service, "PREVIEW_TIMEOUT", 120.0)
    reqs = tuple(legal._parse(json.loads(_DE_FILE.read_text(encoding="utf-8")), "DE"))
    monkeypatch.setattr(legal, "_all_requirements", lambda: reqs)
    return profile


async def _invoice(session, owner_id, *, with_buyer: bool = True) -> Invoice:
    project = Project(name="Haus B", owner_id=owner_id, locale="de")
    session.add(project)
    await session.flush()
    contact_id = None
    if with_buyer:
        contact = Contact(
            contact_type="client",
            company_name="Bau AG",
            vat_number="DE987654321",
            country_code="DE",
            address={"street": "Ring 5", "postal_code": "80331", "city": "München"},
        )
        session.add(contact)
        await session.flush()
        contact_id = str(contact.id)
    inv = Invoice(
        project_id=project.id,
        contact_id=contact_id,
        invoice_direction="receivable",
        invoice_number="RE-2026-0042",
        invoice_date="2026-11-16",
        due_date="2026-12-16",
        currency_code="EUR",
        amount_subtotal=Decimal("10000.00"),
        tax_amount=Decimal("1900.00"),
        amount_total=Decimal("11900.00"),
        metadata_={"supply_date": "2026-10-30"},
    )
    session.add(inv)
    await session.flush()
    session.add(
        InvoiceLineItem(
            invoice_id=inv.id,
            description="Rohbau Erdgeschoss",
            quantity=Decimal("1"),
            unit="psch",
            unit_rate=Decimal("10000.00"),
            amount=Decimal("10000.00"),
            vat_rate=Decimal("19"),
        )
    )
    await session.commit()
    return inv


@pytest.mark.asyncio
async def test_invoice_pdf_prints_record_text_and_german_notes(db_session, german_market) -> None:
    user = await _user(db_session)
    inv = await _invoice(db_session, user.id)
    async with _http(_app(db_session, str(user.id))) as c:
        state = await _publish(c, INVOICE, "de", {"intro": "Wir berechnen Ihnen für {{project.name}}:"})
        version_id = state["versions"][0]["id"]
        r = await c.get(f"/dt/{INVOICE}/records/{inv.id}/pdf", params={"locale": "de"})
    assert r.status_code == 200, r.text
    text = _text(r.content)
    for expected in (
        "RE-2026-0042",
        "Rohbau Erdgeschoss",
        "11.900,00",
        "Wir berechnen Ihnen für Haus B",
        "DE123456789",
    ):
        assert expected in text, expected
    assert "Leistungsdatum" in text
    log = (await db_session.execute(select(DocTemplateIssue))).scalars().all()
    assert [(i.kind, i.record_id, str(i.template_version_id), i.locale) for i in log] == [
        (INVOICE, str(inv.id), version_id, "de")
    ]


@pytest.mark.asyncio
async def test_invoice_without_mandatory_data_is_refused(db_session, german_market) -> None:
    german_market["vat_id"] = ""
    user = await _user(db_session)
    inv = await _invoice(db_session, user.id, with_buyer=False)
    async with _http(_app(db_session, str(user.id))) as c:
        r = await c.get(f"/dt/{INVOICE}/records/{inv.id}/pdf", params={"locale": "de"})
    assert r.status_code == 422, r.text
    issues = r.json()["detail"]["issues"]
    assert {i["rule_id"] for i in issues} == {"doctpl.legal_data_missing"}
    fields = {i["params"]["field"] for i in issues}
    assert "Seller VAT id or tax number" in fields and "Buyer name" in fields
    assert (await db_session.execute(select(DocTemplateIssue))).scalars().all() == []


@pytest.mark.asyncio
async def test_preview_with_a_real_invoice_shows_missing_data_but_renders(db_session, german_market) -> None:
    german_market["vat_id"] = ""
    user = await _user(db_session)
    inv = await _invoice(db_session, user.id)
    async with _http(_app(db_session, str(user.id))) as c:
        r = await c.post(
            f"/dt/{INVOICE}/preview", params={"locale": "de"}, json={"blocks": {}, "record_id": str(inv.id)}
        )
    assert r.status_code == 200, r.text
    assert "RE-2026-0042" in _text(r.content)


@pytest.mark.asyncio
async def test_change_order_pdf_uses_the_default_wording_and_logs_it(db_session, german_market) -> None:
    user = await _user(db_session)
    project = Project(name="Haus B", owner_id=user.id, locale="en")
    db_session.add(project)
    await db_session.flush()
    co = ChangeOrder(project_id=project.id, code="CO-007", title="Extra footing", currency="EUR")
    db_session.add(co)
    await db_session.flush()
    db_session.add(
        ChangeOrderItem(
            change_order_id=co.id,
            description="Footing F7 deepened",
            original_quantity=Decimal("10"),
            new_quantity=Decimal("14"),
            original_rate=Decimal("250"),
            new_rate=Decimal("250"),
            cost_delta=Decimal("1000"),
            unit="m3",
        )
    )
    co.cost_impact = Decimal("1000")
    await db_session.commit()
    async with _http(_app(db_session, str(user.id))) as c:
        r = await c.get(f"/dt/{CHANGE_ORDER}/records/{co.id}/pdf", params={"locale": "en"})
    assert r.status_code == 200, r.text
    text = _text(r.content)
    assert "CO-007" in text and "Footing F7 deepened" in text and "Extra footing" in text
    log = (await db_session.execute(select(DocTemplateIssue))).scalars().one()
    assert log.template_version_id is None and log.source == "default"


@pytest.mark.asyncio
async def test_records_outside_the_callers_projects_are_not_found(db_session, german_market) -> None:
    owner = await _user(db_session)
    stranger = await _user(db_session, role="editor")
    inv = await _invoice(db_session, owner.id)
    async with _http(_app(db_session, str(stranger.id), role="editor")) as c:
        r = await c.get(f"/dt/{INVOICE}/records/{inv.id}/pdf", params={"locale": "de"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_tender_letter_logs_the_template_version_it_printed(db_session) -> None:
    from app.modules.doc_templates.service import log_letter_issue
    from app.modules.tendering.letter_texts import AWARD_KEY

    user = await _user(db_session)
    async with _http(_app(db_session, str(user.id))) as c:
        state = await _publish(c, AWARD_KEY, "en", {"subject": "Award for {{package}}", "body": "Congratulations."})
    version_id = state["versions"][0]["id"]
    await log_letter_issue(db_session, AWARD_KEY, "bid-1", None, "en", str(user.id))
    await log_letter_issue(db_session, AWARD_KEY, "bid-2", None, "en", str(user.id), wording="override")
    await db_session.flush()
    log = (await db_session.execute(select(DocTemplateIssue).order_by(DocTemplateIssue.record_id))).scalars().all()
    assert [(i.record_id, i.source, str(i.template_version_id) if i.template_version_id else None) for i in log] == [
        ("bid-1", "published", version_id),
        ("bid-2", "override", None),
    ]
