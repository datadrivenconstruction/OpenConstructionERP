# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Build an ETA v1.0 JSON document.

Two layers. :func:`build_document` turns plain inputs into the document, with
every figure computed by :mod:`app.modules.einvoice_eta.calculation`, so a
document this module builds satisfies the equations ETA checks by
construction. :func:`build_from_invoice` reads a finance invoice, the
registration's settings and the document's ``country_fields["eta"]`` and feeds
the first layer; it is the payload builder the clearance module calls for the
``eta_json_1_0`` format.

Member order follows the SDK's own sample, because the canonical serialization
walks the document in order and a reader comparing against ETA's examples
should find the same shape.

What the builder refuses to guess. It raises instead of filling in:

* the VAT subtype of a line that is not standard rated: ETA separates export,
  exempt, out of scope and the other reasons, and the platform's category does
  not say which applies;
* the exchange rate of an invoice not in EGP: ETA wants the bank rate of the
  invoice day, which only the operator knows.

Everything else that is missing (a RIN, an address, an item code) is left empty
and named by the validation rules, which is where an operator expects to be
told what to fill.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from app.modules.einvoice_eta.calculation import (
    ComputedLine,
    LineFigures,
    TaxInput,
    compute_document,
    compute_line,
    round5,
)
from app.modules.einvoice_eta.codes import (
    DOC_INVOICE,
    DOCUMENT_TYPE_VERSION,
    EGP,
    PARTY_BUSINESS,
    PARTY_FOREIGNER,
    PARTY_PERSON,
    REFERENCING_TYPES,
    TAX_VAT,
    VAT_CATEGORY_SUBTYPES,
    eta_unit_for,
)

MEDIA_TYPE = "application/json"
ZERO = Decimal("0")


class EtaBuildError(ValueError):
    """The invoice cannot become an ETA document without a decision only a person can make."""


@dataclass(frozen=True)
class EtaParty:
    type: str
    id: str
    name: str
    address: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class EtaLineInput:
    description: str
    item_type: str
    item_code: str
    unit_type: str
    quantity: Decimal
    # In the currency sold. Converted to EGP with the document's exchange rate.
    unit_price: Decimal
    internal_code: str = ""
    discount_rate: Decimal | None = None
    discount_amount: Decimal | None = None
    items_discount: Decimal = ZERO
    value_difference: Decimal = ZERO
    taxes: tuple[TaxInput, ...] = ()


@dataclass(frozen=True)
class EtaDocumentInput:
    document_type: str
    issuer: EtaParty
    receiver: EtaParty
    date_time_issued: str
    activity_code: str
    internal_id: str
    lines: tuple[EtaLineInput, ...]
    currency: str = EGP
    exchange_rate: Decimal | None = None
    references: tuple[str, ...] = ()
    extra_discount_amount: Decimal = ZERO
    purchase_order_reference: str = ""
    sales_order_reference: str = ""
    payment_terms: str = ""


def _num(value: Decimal) -> Decimal:
    """At most 5 decimals, so nothing the builder writes trips ETA's precision."""
    return round5(value)


def _address(raw: dict[str, Any], *, issuer: bool) -> dict[str, str]:
    """Address members in the SDK's order, empty optional ones left out."""
    order = (
        ("branchID", "branchId") if issuer else (),
        ("country",),
        ("governate", "governorate"),
        ("regionCity",),
        ("street",),
        ("buildingNumber",),
        ("postalCode",),
        ("floor",),
        ("room",),
        ("landmark",),
        ("additionalInformation",),
    )
    out: dict[str, str] = {}
    required = {"branchID", "country", "governate", "regionCity", "street", "buildingNumber"}
    for names in order:
        if not names:
            continue
        value = ""
        for name in names:
            if str(raw.get(name) or "").strip():
                value = str(raw[name]).strip()
                break
        if value or names[0] in required:
            out[names[0]] = value
    return out


def _party(party: EtaParty, *, issuer: bool) -> dict[str, Any]:
    out: dict[str, Any] = {"address": _address(party.address, issuer=issuer), "type": party.type}
    if party.id or issuer or party.type != PARTY_PERSON:
        out["id"] = party.id
    if party.name or issuer or party.type != PARTY_PERSON:
        out["name"] = party.name
    return out


def _line(line: EtaLineInput, computed: ComputedLine, *, currency: str, rate: Decimal | None) -> dict[str, Any]:
    if currency == EGP:
        unit_value: dict[str, Any] = {"currencySold": EGP, "amountEGP": _num(line.unit_price)}
    else:
        unit_value = {
            "currencySold": currency,
            "amountEGP": _num(line.unit_price * (rate or ZERO)),
            "amountSold": _num(line.unit_price),
            "currencyExchangeRate": _num(rate or ZERO),
        }
    out: dict[str, Any] = {
        "description": line.description,
        "itemType": line.item_type,
        "itemCode": line.item_code,
        "unitType": line.unit_type,
        "quantity": _num(line.quantity),
        "internalCode": line.internal_code,
        "salesTotal": computed.sales_total,
        "total": computed.total,
        "valueDifference": _num(computed.value_difference),
        "totalTaxableFees": computed.total_taxable_fees,
        "netTotal": computed.net_total,
        "itemsDiscount": _num(computed.items_discount),
        "unitValue": unit_value,
    }
    if computed.discount_amount or computed.discount_rate:
        out["discount"] = {"rate": _num(computed.discount_rate or ZERO), "amount": computed.discount_amount}
    out["taxableItems"] = [
        {"taxType": tax.tax_type, "amount": tax.amount, "subType": tax.sub_type, "rate": _num(tax.rate)}
        for tax in computed.taxes
    ]
    return out


def build_document(data: EtaDocumentInput) -> dict[str, Any]:
    """The ETA document for these inputs, unsigned, as an ordered dict."""
    currency = (data.currency or EGP).strip().upper()
    if currency != EGP and (data.exchange_rate is None or data.exchange_rate <= 0):
        raise EtaBuildError(
            f"The invoice is in {currency}. ETA needs the bank exchange rate to EGP of the invoice day; "
            "set it in the document's ETA fields (exchange_rate)."
        )
    rate = data.exchange_rate if currency != EGP else None
    computed: list[ComputedLine] = []
    for line in data.lines:
        price_egp = line.unit_price if currency == EGP else round5(line.unit_price * (rate or ZERO))
        computed.append(
            compute_line(
                LineFigures(
                    quantity=_num(line.quantity),
                    unit_amount_egp=_num(price_egp),
                    discount_rate=line.discount_rate,
                    discount_amount=line.discount_amount,
                    items_discount=_num(line.items_discount),
                    value_difference=_num(line.value_difference),
                    taxes=line.taxes,
                )
            )
        )
    totals = compute_document(computed, extra_discount_amount=_num(data.extra_discount_amount))

    doc: dict[str, Any] = {
        "issuer": _party(data.issuer, issuer=True),
        "receiver": _party(data.receiver, issuer=False),
        "documentType": data.document_type,
        "documentTypeVersion": DOCUMENT_TYPE_VERSION,
        "dateTimeIssued": data.date_time_issued,
        "taxpayerActivityCode": data.activity_code,
        "internalID": data.internal_id,
    }
    if data.purchase_order_reference:
        doc["purchaseOrderReference"] = data.purchase_order_reference
    if data.sales_order_reference:
        doc["salesOrderReference"] = data.sales_order_reference
    if data.payment_terms:
        doc["payment"] = {"terms": data.payment_terms}
    if data.document_type in REFERENCING_TYPES or data.references:
        doc["references"] = list(data.references)
    doc["invoiceLines"] = [
        _line(line, comp, currency=currency, rate=rate) for line, comp in zip(data.lines, computed, strict=True)
    ]
    doc["totalDiscountAmount"] = totals.total_discount_amount
    doc["totalSalesAmount"] = totals.total_sales_amount
    doc["netAmount"] = totals.net_amount
    doc["taxTotals"] = [{"taxType": tax_type, "amount": amount} for tax_type, amount in totals.tax_totals]
    doc["totalAmount"] = totals.total_amount
    doc["extraDiscountAmount"] = totals.extra_discount_amount
    doc["totalItemsDiscountAmount"] = totals.total_items_discount_amount
    return doc


def _emit(value: Any, indent: int, out: list[str]) -> None:
    pad = "  " * indent
    inner = "  " * (indent + 1)
    if isinstance(value, dict):
        if not value:
            out.append("{}")
            return
        out.append("{\n")
        items = list(value.items())
        for position, (key, child) in enumerate(items):
            out.append(f"{inner}{json.dumps(str(key))}: ")
            _emit(child, indent + 1, out)
            out.append(",\n" if position < len(items) - 1 else "\n")
        out.append(f"{pad}}}")
    elif isinstance(value, (list, tuple)):
        if not value:
            out.append("[]")
            return
        out.append("[\n")
        for position, child in enumerate(value):
            out.append(inner)
            _emit(child, indent + 1, out)
            out.append(",\n" if position < len(value) - 1 else "\n")
        out.append(f"{pad}]")
    elif isinstance(value, bool):
        out.append("true" if value else "false")
    elif isinstance(value, Decimal):
        # Plain notation, never an exponent: the literal is what gets signed.
        out.append(format(value, "f"))
    elif isinstance(value, int):
        out.append(str(value))
    elif value is None:
        out.append("null")
    else:
        out.append(json.dumps(str(value), ensure_ascii=False))


def to_json_text(doc: dict[str, Any]) -> str:
    """The document as JSON text, numbers written exactly as computed."""
    out: list[str] = []
    _emit(doc, 0, out)
    return "".join(out) + "\n"


# ── From a finance invoice ───────────────────────────────────────────────────


def _dec(value: Any, *, what: str) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise EtaBuildError(f"{what} is not a number: {value!r}.") from exc


def _taxes_from(raw: Any, *, where: str) -> tuple[TaxInput, ...]:
    if not isinstance(raw, list):
        return ()
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        out.append(
            TaxInput(
                tax_type=str(item.get("taxType") or "").strip().upper(),
                sub_type=str(item.get("subType") or "").strip(),
                rate=_dec(item.get("rate"), what=f"{where} rate"),
                amount=_dec(item.get("amount"), what=f"{where} amount"),
            )
        )
    return tuple(out)


def receiver_from_buyer(buyer: dict[str, Any]) -> EtaParty:
    """An ETA receiver from the buyer the finance module resolves for an invoice.

    A natural person in Egypt is type P, any party outside Egypt is type F, and
    everyone else is a business in Egypt, type B. The buyer record has no
    governorate, so the city stands in for it and the operator corrects it in
    the document's ETA fields when ETA's validator says otherwise.
    """
    country = str(buyer.get("country_code") or "EG").strip().upper() or "EG"
    person = bool(buyer.get("first_name") or buyer.get("family_name"))
    if country != "EG":
        kind = PARTY_FOREIGNER
    elif person:
        kind = PARTY_PERSON
    else:
        kind = PARTY_BUSINESS
    city = str(buyer.get("city") or "").strip()
    return EtaParty(
        type=kind,
        id=str(buyer.get("vat_id") or "").strip(),
        name=str(buyer.get("name") or "").strip(),
        address={
            "country": country,
            "governate": city,
            "regionCity": str(buyer.get("district") or city).strip(),
            "street": str(buyer.get("line1") or "").strip(),
            "buildingNumber": str(buyer.get("building_number") or "").strip(),
            "postalCode": str(buyer.get("postcode") or "").strip(),
        },
    )


def _party_from_dict(raw: dict[str, Any]) -> EtaParty:
    return EtaParty(
        type=str(raw.get("type") or "").strip().upper(),
        id=str(raw.get("id") or "").strip(),
        name=str(raw.get("name") or "").strip(),
        address=dict(raw.get("address") or {}),
    )


def _vat_item(
    *,
    rate: Decimal | None,
    category: str | None,
    override_subtype: str,
    line_number: int,
) -> TaxInput | None:
    if rate is None and not override_subtype:
        return None
    rate = rate or ZERO
    subtype = override_subtype
    if not subtype:
        if rate > 0 and (category or "S").upper() == "S":
            subtype = VAT_CATEGORY_SUBTYPES.values["S"]
        else:
            raise EtaBuildError(
                f"Line {line_number} carries VAT at {rate}% (category {category or 'none'}). ETA needs to know why a "
                "line is not standard rated: set vat_subtype on that line in the document's ETA fields "
                "(V001 export, V002 free zones, V003 exempt, V004 not taxable, V005-V008 special exemptions, "
                "V010 other rates)."
            )
    return TaxInput(tax_type=TAX_VAT, sub_type=subtype, rate=rate)


def build_input_from_invoice(
    *,
    invoice: dict[str, Any],
    lines: list[dict[str, Any]],
    rin: str,
    settings: dict[str, Any],
    eta_fields: dict[str, Any],
    buyer: dict[str, Any] | None,
) -> EtaDocumentInput:
    """Neutral inputs from a finance invoice, the registration and the document's ETA fields.

    Plain dicts in, so it is testable without a database. ``invoice`` and
    ``lines`` use the finance model's field names.
    """
    issuer_settings = settings.get("issuer") if isinstance(settings.get("issuer"), dict) else {}
    issuer = EtaParty(
        type=PARTY_BUSINESS,
        id=(rin or "").strip(),
        name=str(issuer_settings.get("name") or "").strip(),
        address=dict(issuer_settings.get("address") or {}),
    )
    if isinstance(eta_fields.get("receiver"), dict):
        receiver = _party_from_dict(eta_fields["receiver"])
    elif buyer:
        receiver = receiver_from_buyer(buyer)
    else:
        receiver = EtaParty(type=PARTY_BUSINESS, id="", name="", address={"country": "EG"})

    default_item = settings.get("default_item") if isinstance(settings.get("default_item"), dict) else {}
    overrides = eta_fields.get("lines") if isinstance(eta_fields.get("lines"), list) else []
    default_taxes = _taxes_from(eta_fields.get("default_taxes"), where="default tax")

    subtotal = _dec(invoice.get("amount_subtotal"), what="invoice subtotal") or ZERO
    tax_amount = _dec(invoice.get("tax_amount"), what="invoice tax") or ZERO
    header_rate = (tax_amount / subtotal * 100).quantize(Decimal("0.01")) if subtotal else None

    built: list[EtaLineInput] = []
    for index, row in enumerate(lines):
        number = index + 1
        override = overrides[index] if index < len(overrides) and isinstance(overrides[index], dict) else {}
        where = f"line {number}"
        if isinstance(override.get("taxableItems"), list):
            taxes = _taxes_from(override["taxableItems"], where=where)
        else:
            line_rate = _dec(row.get("vat_rate"), what=f"{where} VAT rate")
            vat = _vat_item(
                rate=line_rate if line_rate is not None else header_rate,
                category=row.get("vat_category"),
                override_subtype=str(override.get("vat_subtype") or "").strip(),
                line_number=number,
            )
            taxes = (vat,) if vat is not None else ()
        present = {t.tax_type for t in taxes}
        taxes = taxes + tuple(t for t in default_taxes if t.tax_type not in present)

        unit = str(override.get("unitType") or "").strip() or eta_unit_for(row.get("unit"))
        unit = unit or str(default_item.get("unitType") or "").strip()
        discount = override.get("discount") if isinstance(override.get("discount"), dict) else {}
        built.append(
            EtaLineInput(
                description=str(row.get("description") or "").strip(),
                item_type=str(override.get("itemType") or default_item.get("itemType") or "").strip().upper(),
                item_code=str(override.get("itemCode") or default_item.get("itemCode") or "").strip(),
                unit_type=unit,
                quantity=_dec(row.get("quantity"), what=f"{where} quantity") or ZERO,
                unit_price=_dec(row.get("unit_rate"), what=f"{where} unit rate") or ZERO,
                internal_code=str(override.get("internalCode") or row.get("cost_category") or "").strip(),
                discount_rate=_dec(discount.get("rate"), what=f"{where} discount rate"),
                discount_amount=_dec(discount.get("amount"), what=f"{where} discount"),
                items_discount=_dec(override.get("itemsDiscount"), what=f"{where} items discount") or ZERO,
                value_difference=_dec(override.get("valueDifference"), what=f"{where} value difference") or ZERO,
                taxes=taxes,
            )
        )

    invoice_date = str(invoice.get("invoice_date") or "").strip()[:10]
    issued = str(eta_fields.get("date_time_issued") or "").strip() or (
        f"{invoice_date}T00:00:00Z" if invoice_date else ""
    )
    references = eta_fields.get("references") if isinstance(eta_fields.get("references"), list) else []
    return EtaDocumentInput(
        document_type=str(eta_fields.get("document_type") or DOC_INVOICE).strip().lower(),
        issuer=issuer,
        receiver=receiver,
        date_time_issued=issued,
        activity_code=str(eta_fields.get("activity_code") or settings.get("activity_code") or "").strip(),
        internal_id=str(invoice.get("invoice_number") or "").strip(),
        lines=tuple(built),
        currency=str(invoice.get("currency_code") or EGP).strip().upper() or EGP,
        exchange_rate=_dec(eta_fields.get("exchange_rate"), what="exchange rate"),
        references=tuple(str(r).strip() for r in references if str(r).strip()),
        extra_discount_amount=_dec(eta_fields.get("extra_discount_amount"), what="extra discount") or ZERO,
        purchase_order_reference=str(eta_fields.get("purchase_order_reference") or "").strip(),
        payment_terms=str(eta_fields.get("payment_terms") or "").strip(),
    )


async def build_from_invoice(
    session: Any,
    *,
    invoice_id: uuid.UUID,
    profile: Any,
    country_fields: dict[str, Any],
) -> tuple[str, str]:
    """The payload builder registered for ``eta_json_1_0``.

    Reads the finance invoice and its lines, resolves the buyer the same way the
    finance export path does, and builds the document.
    """
    from sqlalchemy import select

    from app.modules.einvoice_clearance.service import ClearanceError
    from app.modules.finance.einvoice_parties import einvoice_defaults_for_invoice
    from app.modules.finance.models import Invoice, InvoiceLineItem

    invoice = (await session.execute(select(Invoice).where(Invoice.id == invoice_id))).scalar_one_or_none()
    if invoice is None:
        raise ClearanceError(f"Invoice {invoice_id} was not found, so there is nothing to prepare.")
    rows = (
        (
            await session.execute(
                select(InvoiceLineItem)
                .where(InvoiceLineItem.invoice_id == invoice_id)
                .order_by(InvoiceLineItem.sort_order, InvoiceLineItem.created_at)
            )
        )
        .scalars()
        .all()
    )
    defaults = await einvoice_defaults_for_invoice(
        session,
        contact_id=invoice.contact_id,
        invoice_direction=invoice.invoice_direction,
    )
    settings = dict((profile.settings or {}).get("eta") or {})
    eta_fields = country_fields.get("eta") if isinstance(country_fields.get("eta"), dict) else {}
    try:
        data = build_input_from_invoice(
            invoice={
                "invoice_number": invoice.invoice_number,
                "invoice_date": invoice.invoice_date,
                "currency_code": invoice.currency_code,
                "amount_subtotal": invoice.amount_subtotal,
                "tax_amount": invoice.tax_amount,
            },
            lines=[
                {
                    "description": row.description,
                    "quantity": row.quantity,
                    "unit": row.unit,
                    "unit_rate": row.unit_rate,
                    "vat_rate": row.vat_rate,
                    "vat_category": row.vat_category,
                    "cost_category": row.cost_category,
                }
                for row in rows
            ],
            rin=profile.tax_registration_id,
            settings=settings,
            eta_fields=eta_fields,
            buyer=defaults.get("buyer") if isinstance(defaults, dict) else None,
        )
        return to_json_text(build_document(data)), MEDIA_TYPE
    except EtaBuildError as exc:
        raise ClearanceError(str(exc)) from exc


__all__ = [
    "MEDIA_TYPE",
    "EtaBuildError",
    "EtaDocumentInput",
    "EtaLineInput",
    "EtaParty",
    "build_document",
    "build_from_invoice",
    "build_input_from_invoice",
    "receiver_from_buyer",
    "to_json_text",
]
