# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Customer-facing documents printed by the generic generator: invoice and change order.

Each kind reads one record into a :class:`RecordDocument` (values, meta rows,
item table, totals) already formatted in the document language; the firm's
blocks and the locked legal zone come from the template layer. Amounts and
lines always come from the record, never from template text.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from app.core.doc_templates.pdf import TableSpec
from app.core.doc_templates.registry import DocumentKind, MergeField, RecordDocument
from app.core.doc_templates.standards import EN16931_INVOICE_MINIMUM

__all__ = [
    "CHANGE_ORDER_KEY",
    "INVOICE_KEY",
    "OFFER_BLOCK_TO_TEXT",
    "OFFER_KEY",
    "change_order_kind",
    "invoice_kind",
    "offer_kind",
    "offer_text_from_block",
]

INVOICE_KEY = "finance.invoice"
CHANGE_ORDER_KEY = "changeorders.change_order"
OFFER_KEY = "offers.offer"

#: Template block -> offer text kind. The offer keeps its own generator (envelope
#: window, schedule, acceptance block); the firm's wording reaches it as its
#: company text, below a project's own text.
OFFER_BLOCK_TO_TEXT = {"intro": "intro", "body": "conditions", "terms": "payment_terms", "closing": "closing"}

_COMMON_FIELDS = (
    MergeField("project.name", "text", "Haus B", "project"),
    MergeField("entity.legal_name", "text", "Muster Hochbau GmbH", "company"),
    MergeField("entity.address", "text", "Hauptstr. 1, 10115 Berlin", "company"),
    MergeField("entity.vat_id", "text", "DE123456789", "company"),
    MergeField("entity.tax_number", "text", "", "company"),
    MergeField("entity.tax_id", "text", "DE123456789", "company"),
    MergeField("entity.email", "text", "office@muster-hochbau.example", "company"),
    MergeField("entity.phone", "text", "+49 30 1234567", "company"),
    MergeField("recipient.name", "text", "Bau AG", "recipient"),
    MergeField("recipient.address", "text", "Ring 5, 80331 München", "recipient"),
    MergeField("recipient.vat_id", "text", "DE987654321", "recipient"),
)

_INVOICE_DEFAULTS = {
    "en": {
        "title": "Invoice {{doc.number}}",
        "intro": "Dear Sir or Madam,\n\nfor the work on {{project.name}} we invoice you as follows.",
        "terms": "Please pay {{doc.total_gross}} by {{doc.due_date}} quoting invoice number {{doc.number}}.",
        "closing": "Thank you for your order.\n\nKind regards\n{{entity.legal_name}}",
    },
    "de": {
        "title": "Rechnung {{doc.number}}",
        "intro": "Sehr geehrte Damen und Herren,\n\nfür die Leistungen am Bauvorhaben {{project.name}} "
        "berechnen wir Ihnen wie folgt.",
        "terms": "Bitte überweisen Sie {{doc.total_gross}} bis zum {{doc.due_date}} unter Angabe der "
        "Rechnungsnummer {{doc.number}}.",
        "closing": "Vielen Dank für Ihren Auftrag.\n\nMit freundlichen Grüßen\n{{entity.legal_name}}",
    },
}

_CO_DEFAULTS = {
    "en": {
        "title": "Change order {{doc.number}}: {{doc.title}}",
        "intro": "Dear Sir or Madam,\n\nfor {{project.name}} we submit the following change.",
        "terms": "The change takes effect when both parties have signed it. Time impact: {{doc.time_impact}}.",
        "closing": "Kind regards\n{{entity.legal_name}}",
        "signature": "Accepted (client): ______________________    Date: ____________",
    },
    "de": {
        "title": "Nachtrag {{doc.number}}: {{doc.title}}",
        "intro": "Sehr geehrte Damen und Herren,\n\nfür das Bauvorhaben {{project.name}} reichen wir "
        "folgenden Nachtrag ein.",
        "terms": "Der Nachtrag wird mit Unterschrift beider Parteien wirksam. Bauzeitauswirkung: {{doc.time_impact}}.",
        "closing": "Mit freundlichen Grüßen\n{{entity.legal_name}}",
        "signature": "Beauftragt (Auftraggeber): ______________________    Datum: ____________",
    },
}


def _date(value: Any, lang: str) -> str:
    from app.core.regional_format import date_format_for_language
    from app.core.register_export import EMPTY, format_stored_date

    out = format_stored_date(value, date_format_for_language(lang))
    return "" if out == EMPTY else out


def _money(value: Any, currency: str, lang: str) -> str:
    from app.core.money import format_money

    if value is None or str(value).strip() == "":
        return ""
    return format_money(str(Decimal(str(value)).quantize(Decimal("0.01"))), currency or "EUR", lang)


def _qty(value: Any, lang: str) -> str:
    from app.core.regional_format import format_number, number_style_for_language

    if value is None:
        return ""
    d = Decimal(str(value)).normalize()
    exponent = d.as_tuple().exponent
    places = max(0, -exponent) if isinstance(exponent, int) else 0
    return format_number(d, min(places, 4), number_style_for_language(lang))


async def _project(session: Any, project_id: Any) -> Any:
    from app.modules.projects.models import Project

    return await session.get(Project, project_id)


def _seller_values() -> dict[str, str]:
    from app.core.doc_templates.seller import resolve_seller

    return resolve_seller().as_fields()


# ── Invoice ─────────────────────────────────────────────────────────────────


async def _invoice_records(session: Any, project_ids: set[Any] | None) -> list[tuple[str, str]]:
    from sqlalchemy import select

    from app.modules.finance.models import Invoice

    stmt = (
        select(Invoice.id, Invoice.invoice_number, Invoice.invoice_date)
        .where(Invoice.invoice_direction != "payable")
        .order_by(Invoice.invoice_date.desc())
        .limit(50)
    )
    if project_ids is not None:
        stmt = stmt.where(Invoice.project_id.in_(project_ids))
    return [(str(i), f"{n} ({d})") for i, n, d in (await session.execute(stmt)).all()]


async def _invoice_document(session: Any, record_id: str, lang: str) -> RecordDocument:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.core.party_names import resolve_party_details, resolve_party_names
    from app.modules.finance.models import Invoice
    from app.modules.finance.pdf_translations import tr

    inv = (
        await session.execute(
            select(Invoice).options(selectinload(Invoice.line_items)).where(Invoice.id == uuid.UUID(record_id))
        )
    ).scalar_one_or_none()
    if inv is None:
        raise LookupError(record_id)
    project = await _project(session, inv.project_id)
    cur = inv.currency_code or getattr(project, "currency", "") or "EUR"
    meta = dict(inv.metadata_ or {})
    names = await resolve_party_names(session, [inv.contact_id])
    details = await resolve_party_details(session, [inv.contact_id])
    party = details.get(str(inv.contact_id)) if inv.contact_id else None
    lines = sorted(inv.line_items or [], key=lambda li: li.sort_order or 0)
    values: dict[str, str] = {
        **_seller_values(),
        "project.name": getattr(project, "name", "") or "",
        "doc.number": inv.invoice_number or "",
        "doc.date": _date(inv.invoice_date, lang),
        "doc.due_date": _date(inv.due_date, lang),
        "doc.supply_date": _date(meta.get("supply_date") or meta.get("service_period") or inv.invoice_date, lang),
        "doc.currency": cur,
        "doc.total_net": _money(inv.amount_subtotal, cur, lang),
        "doc.total_vat": _money(inv.tax_amount, cur, lang),
        "doc.total_gross": _money(inv.amount_total, cur, lang),
        "doc.reverse_charge": "1" if any((li.vat_category or "").upper() == "AE" for li in lines) else "",
        "doc.small_business": "1" if meta.get("small_business") else "",
        "doc.private_customer": "1" if meta.get("private_customer") else "",
        "recipient.name": names.get(str(inv.contact_id), "") if inv.contact_id else "",
        "recipient.address": party.address if party else "",
        "recipient.vat_id": party.tax_id if party else "",
    }
    if values["recipient.name"] == str(inv.contact_id):
        values["recipient.name"] = ""
    meta_rows = [
        (tr(lang, "invoice_number"), values["doc.number"]),
        (tr(lang, "invoice_date"), values["doc.date"]),
        (tr(lang, "due_date"), values["doc.due_date"]),
        (tr(lang, "client"), ", ".join(p for p in (values["recipient.name"], values["recipient.address"]) if p)),
    ]
    if values["recipient.vat_id"]:
        meta_rows.append((tr(lang, "counterparty_tax_id"), values["recipient.vat_id"]))
    table = TableSpec(
        header=[
            tr(lang, "col_no"),
            tr(lang, "col_description"),
            tr(lang, "col_quantity"),
            tr(lang, "col_unit"),
            tr(lang, "col_unit_rate"),
            tr(lang, "col_vat"),
            tr(lang, "col_amount"),
        ],
        rows=[
            [
                str(n),
                li.description or "",
                _qty(li.quantity, lang),
                li.unit or "",
                _money(li.unit_rate, cur, lang),
                f"{_qty(li.vat_rate, lang)} %" if li.vat_rate is not None else "",
                _money(li.amount, cur, lang),
            ]
            for n, li in enumerate(lines, 1)
        ],
        col_widths_mm=(10, 62, 16, 12, 25, 14, 31),
        numeric_cols=(2, 4, 5, 6),
    )
    totals = [
        (tr(lang, "subtotal"), values["doc.total_net"]),
        (tr(lang, "tax"), values["doc.total_vat"]),
        (tr(lang, "total_gross"), values["doc.total_gross"]),
    ]
    return RecordDocument(
        values=values,
        meta=[r for r in meta_rows if r[1]],
        table=table,
        totals=totals,
        project_id=inv.project_id,
        filename=f"invoice-{inv.invoice_number or inv.id}",
        locale=getattr(project, "locale", None),
    )


def invoice_kind() -> DocumentKind:
    """The customer invoice, with the EN 16931 minimum as mandatory data."""
    return DocumentKind(
        key=INVOICE_KEY,
        channel="pdf",
        module="finance",
        label="Invoice",
        blocks=("title", "intro", "terms", "closing", "signature", "footer"),
        fields=(
            *_COMMON_FIELDS,
            MergeField("doc.number", "text", "RE-2026-0042", "document"),
            MergeField("doc.date", "date", "16.11.2026", "document"),
            MergeField("doc.due_date", "date", "16.12.2026", "document"),
            MergeField("doc.supply_date", "date", "30.10.2026", "document"),
            MergeField("doc.currency", "text", "EUR", "document"),
            MergeField("doc.total_net", "money", "10.000,00 €", "document"),
            MergeField("doc.total_vat", "money", "1.900,00 €", "document"),
            MergeField("doc.total_gross", "money", "11.900,00 €", "document"),
        ),
        defaults=lambda lang: _INVOICE_DEFAULTS.get(lang, {}),
        languages=("en", "de"),
        required_blocks=("title",),
        appearance_type="invoice",
        records=_invoice_records,
        mandatory=EN16931_INVOICE_MINIMUM,
        record_document=_invoice_document,
    )


# ── Change order ────────────────────────────────────────────────────────────


async def _change_order_records(session: Any, project_ids: set[Any] | None) -> list[tuple[str, str]]:
    from sqlalchemy import select

    from app.modules.changeorders.models import ChangeOrder

    stmt = select(ChangeOrder.id, ChangeOrder.code, ChangeOrder.title).order_by(ChangeOrder.code).limit(50)
    if project_ids is not None:
        stmt = stmt.where(ChangeOrder.project_id.in_(project_ids))
    return [(str(i), f"{c} {t}") for i, c, t in (await session.execute(stmt)).all()]


async def _change_order_document(session: Any, record_id: str, lang: str) -> RecordDocument:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.modules.changeorders.models import ChangeOrder
    from app.modules.changeorders.pdf_translations import tr

    co = (
        await session.execute(
            select(ChangeOrder).options(selectinload(ChangeOrder.items)).where(ChangeOrder.id == uuid.UUID(record_id))
        )
    ).scalar_one_or_none()
    if co is None:
        raise LookupError(record_id)
    project = await _project(session, co.project_id)
    cur = co.currency or getattr(project, "currency", "") or "EUR"
    days = co.approved_time_days if co.approved_time_days is not None else co.schedule_impact_days
    values: dict[str, str] = {
        **_seller_values(),
        "project.name": getattr(project, "name", "") or "",
        "doc.number": co.code or "",
        "doc.title": co.title or "",
        "doc.date": _date(co.submitted_at or co.created_at, lang),
        "doc.total": _money(co.approved_amount if co.approved_amount is not None else co.cost_impact, cur, lang),
        "doc.time_impact": str(days or 0),
        "doc.description": co.description or "",
        "recipient.name": "",
        "recipient.address": "",
        "recipient.vat_id": "",
    }
    items = sorted(co.items or [], key=lambda i: i.sort_order or 0)
    table = TableSpec(
        header=[
            tr(lang, "item_description"),
            tr(lang, "item_original_quantity"),
            tr(lang, "item_new_quantity"),
            tr(lang, "item_unit"),
            tr(lang, "item_new_rate"),
            tr(lang, "item_cost_delta"),
        ],
        rows=[
            [
                it.description or "",
                _qty(it.original_quantity, lang),
                _qty(it.new_quantity, lang),
                it.unit or "",
                _money(it.new_rate, cur, lang),
                _money(it.cost_delta, cur, lang),
            ]
            for it in items
        ],
        col_widths_mm=(66, 20, 20, 14, 25, 25),
        numeric_cols=(1, 2, 4, 5),
    )
    meta_rows = [(tr(lang, "col_code"), values["doc.number"]), (tr(lang, "col_title"), values["doc.title"])]
    if co.description:
        meta_rows.append((tr(lang, "description"), co.description))
    return RecordDocument(
        values=values,
        meta=[r for r in meta_rows if r[1]],
        table=table,
        totals=[
            (tr(lang, "col_cost_impact"), values["doc.total"]),
            (tr(lang, "time_impact"), values["doc.time_impact"]),
        ],
        project_id=co.project_id,
        filename=f"change-order-{co.code or co.id}",
        locale=getattr(project, "locale", None),
    )


def change_order_kind() -> DocumentKind:
    """The change order sent to the client for signature."""
    return DocumentKind(
        key=CHANGE_ORDER_KEY,
        channel="pdf",
        module="changeorders",
        label="Change order",
        blocks=("title", "intro", "terms", "closing", "signature", "footer"),
        fields=(
            *_COMMON_FIELDS,
            MergeField("doc.number", "text", "CO-007", "document"),
            MergeField("doc.title", "text", "Extra footing F7", "document"),
            MergeField("doc.date", "date", "16.11.2026", "document"),
            MergeField("doc.total", "money", "1.000,00 €", "document"),
            MergeField("doc.time_impact", "quantity", "3", "document"),
        ),
        defaults=lambda lang: _CO_DEFAULTS.get(lang, {}),
        languages=("en", "de"),
        required_blocks=("title",),
        appearance_type="change_order",
        records=_change_order_records,
        record_document=_change_order_document,
    )


# ── Offer (own generator, wording only) ─────────────────────────────────────


def offer_text_from_block(text: str) -> str:
    """``{{offer.net_total}}`` -> ``{net_total}``, the offer generator's placeholder form."""
    import re

    return re.sub(r"\{\{\s*offer\.([a-z_]+)\s*\}\}", lambda m: "{" + m.group(1) + "}", text or "")


def _block_from_offer_text(text: str) -> str:
    import re

    return re.sub(r"(?<!\{)\{([a-z_]+)\}(?!\})", lambda m: "{{offer." + m.group(1) + "}}", text or "")


def _offer_defaults(lang: str) -> dict[str, str]:
    from app.modules.offers import pack as pack_mod

    neutral = pack_mod.pack_for(None)
    out: dict[str, str] = {}
    for block, text_kind in OFFER_BLOCK_TO_TEXT.items():
        texts = (neutral.get("texts") or {}).get(text_kind) or {}
        if lang in texts:
            out[block] = _block_from_offer_text(texts[lang])
    return out


def offer_kind() -> DocumentKind:
    """The customer offer: its own PDF generator, the firm's wording from templates."""
    from app.modules.offers import pack as pack_mod
    from app.modules.offers.pricing import PLACEHOLDERS

    samples = {"offer_number": "A-2026-014", "customer_name": "Bau AG", "project_name": "Haus B"}
    langs = sorted({lang for t in (pack_mod.pack_for(None).get("texts") or {}).values() for lang in (t or {})} | {"en"})
    return DocumentKind(
        key=OFFER_KEY,
        channel="pdf",
        module="offers",
        label="Offer",
        blocks=tuple(OFFER_BLOCK_TO_TEXT),
        fields=tuple(MergeField(f"offer.{p}", "text", samples.get(p, ""), "document") for p in PLACEHOLDERS),
        defaults=_offer_defaults,
        languages=tuple(langs),
        appearance_type="customer_offer",
    )
