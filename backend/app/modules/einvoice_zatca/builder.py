# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The UBL 2.1 KSA profile document, from neutral inputs.

Two layers, so the format is testable without a database:

* :class:`ZatcaInvoiceInput` and :func:`build_unsigned` turn plain values into
  the document tree, computing every figure the way ZATCA checks it (XML
  Implementation Standard v1.2 §9 and the EN 16931 rules ZATCA runs): line net
  = quantity x price, line VAT (KSA-11) and line total (KSA-12) per line, VAT
  per category on the category's taxable amount (BR-CO-17), two decimals,
  half up.
* :func:`input_from_invoice` reads a finance invoice (as plain dicts), the
  registration's ZATCA settings and the document's ZATCA fields.

Signing is :mod:`stamp`'s job and the chain is the service's. This module never
touches either: it is handed the ICV and the previous hash.

Construction rules applied here (VAT Guideline for the Contracting Sector, May
2026, §5): the document bills the gross value and never subtracts retention,
because VAT is due on the full invoiced amount (§5.2); a reduction is never a
negative line but a 381 credit note (§5.4); advances deducted on a final
invoice are prepayment lines with ``PrepaidAmount`` (P1 §9.5), and the VAT of
the document stays the VAT of the whole supply, as in the SDK's "Advance
Payment adjustments" sample.
"""

from __future__ import annotations

import datetime as dt
import uuid as uuid_module
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from app.modules.einvoice_zatca import c14n
from app.modules.einvoice_zatca.codes import (
    CATEGORY_OUT_OF_SCOPE,
    CATEGORY_STANDARD,
    EXEMPTION_REASONS,
    GOVERNMENT_LEGAL_FORM,
    NOTE_TYPES,
    NS_CAC,
    NS_CBC,
    NS_EXT,
    NS_INVOICE,
    PAYMENT_MEANS,
    PROFILE_ID,
    SAUDI_ARABIA,
    TAX_CURRENCY,
    TYPE_CREDIT_NOTE,
    TYPE_DEBIT_NOTE,
    TYPE_INVOICE,
    TYPE_PREPAYMENT,
    VAT_CATEGORIES,
    VAT_SCHEME,
    Subtype,
)
from app.modules.einvoice_zatca.qr import QrFields

MEDIA_TYPE = "application/xml"
CENT = Decimal("0.01")
ZERO = Decimal("0")
HUNDRED = Decimal("100")


class ZatcaBuildError(ValueError):
    """The invoice cannot be expressed as a ZATCA document; the message says what to change."""


def money(value: Decimal) -> Decimal:
    """Two decimals, half up: the rounding ZATCA applies to every amount."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def amount_text(value: Decimal) -> str:
    return format(money(value), "f")


def rate_text(value: Decimal) -> str:
    return format(value.quantize(CENT, rounding=ROUND_HALF_UP), "f")


def quantity_text(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    if "." not in text:
        return text + ".00"
    whole, frac = text.split(".")
    return f"{whole}.{frac.ljust(2, '0')}"


# ── Inputs ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Address:
    """A postal address in the KSA profile's terms (BR-KSA-09, BR-KSA-10)."""

    street: str = ""
    additional_street: str = ""
    building_number: str = ""
    # The "additional number" of the Saudi national address (cbc:PlotIdentification).
    additional_number: str = ""
    district: str = ""
    city: str = ""
    postal_zone: str = ""
    country_subentity: str = ""
    country: str = SAUDI_ARABIA


@dataclass(frozen=True)
class Party:
    name: str
    vat_number: str = ""
    id_scheme: str = ""
    id_value: str = ""
    address: Address = field(default_factory=Address)
    # KSA-40: "GOV" for a government buyer under VAT IR Art 20(5) (BR-KSA-91).
    legal_form: str = ""


@dataclass(frozen=True)
class Line:
    description: str
    quantity: Decimal
    unit_code: str
    price: Decimal
    vat_category: str = CATEGORY_STANDARD
    vat_rate: Decimal = Decimal("15")
    exemption_code: str = ""
    exemption_text: str = ""


@dataclass(frozen=True)
class Prepayment:
    """An advance (a 386 document) deducted on this invoice."""

    number: str
    issue_date: str
    issue_time: str
    taxable_amount: Decimal
    uuid: str = ""
    vat_category: str = CATEGORY_STANDARD
    vat_rate: Decimal = Decimal("15")
    exemption_code: str = ""
    exemption_text: str = ""

    @property
    def vat_amount(self) -> Decimal:
        return money(self.taxable_amount * self.vat_rate / HUNDRED)


@dataclass(frozen=True)
class ZatcaInvoiceInput:
    number: str
    uuid: str
    issue_date: str
    issue_time: str
    type_code: str
    subtype: Subtype
    currency: str
    seller: Party
    buyer: Party | None
    lines: tuple[Line, ...]
    icv: int
    previous_hash: str
    billing_reference: str = ""
    reason: str = ""
    payment_means_code: str = "42"
    supply_date: str = ""
    supply_end_date: str = ""
    # BT-7: for a government claim under VAT IR Art 20(5), the payment order date (BR-KSA-92).
    tax_point_date: str = ""
    prepayments: tuple[Prepayment, ...] = ()
    # SAR per unit of ``currency``; required when the document is not in SAR.
    exchange_rate: Decimal | None = None
    notes: tuple[str, ...] = ()


# ── Figures ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LineFigures:
    net: Decimal
    vat: Decimal

    @property
    def total(self) -> Decimal:
        return self.net + self.vat


@dataclass(frozen=True)
class CategoryFigures:
    category: str
    rate: Decimal
    taxable: Decimal
    vat: Decimal
    exemption_code: str
    exemption_text: str


@dataclass(frozen=True)
class Totals:
    lines: tuple[LineFigures, ...]
    categories: tuple[CategoryFigures, ...]
    line_extension: Decimal
    tax_exclusive: Decimal
    vat: Decimal
    vat_in_sar: Decimal
    tax_inclusive: Decimal
    prepaid: Decimal
    payable: Decimal


def compute(data: ZatcaInvoiceInput) -> Totals:
    """Every figure of the document, the way ZATCA recomputes it."""
    lines = tuple(
        LineFigures(
            net=money(line.quantity * line.price),
            vat=money(money(line.quantity * line.price) * line.vat_rate / HUNDRED),
        )
        for line in data.lines
    )
    groups: dict[tuple[str, Decimal], list[int]] = {}
    for index, line in enumerate(data.lines):
        groups.setdefault((line.vat_category, line.vat_rate), []).append(index)
    categories: list[CategoryFigures] = []
    for (category, rate), indexes in groups.items():
        taxable = sum((lines[i].net for i in indexes), ZERO)
        first = data.lines[indexes[0]]
        categories.append(
            CategoryFigures(
                category=category,
                rate=rate,
                taxable=money(taxable),
                vat=money(taxable * rate / HUNDRED),
                exemption_code=first.exemption_code,
                exemption_text=first.exemption_text,
            )
        )
    line_extension = money(sum((f.net for f in lines), ZERO))
    vat = money(sum((c.vat for c in categories), ZERO))
    rate = data.exchange_rate if data.currency != TAX_CURRENCY else Decimal("1")
    vat_in_sar = money(vat * (rate or Decimal("1")))
    tax_inclusive = line_extension + vat
    prepaid = money(sum((p.taxable_amount + p.vat_amount for p in data.prepayments), ZERO))
    return Totals(
        lines=lines,
        categories=tuple(categories),
        line_extension=line_extension,
        tax_exclusive=line_extension,
        vat=vat,
        vat_in_sar=vat_in_sar,
        tax_inclusive=tax_inclusive,
        prepaid=prepaid,
        payable=tax_inclusive - prepaid,
    )


# ── Checks the builder refuses on ────────────────────────────────────────────


def _input_problems(data: ZatcaInvoiceInput) -> list[str]:
    problems: list[str] = list(data.subtype.problems())
    if data.type_code not in (TYPE_INVOICE, TYPE_CREDIT_NOTE, TYPE_DEBIT_NOTE, TYPE_PREPAYMENT):
        problems.append(f"document type {data.type_code!r} is not one of 388, 381, 383, 386")
    if data.type_code in NOTE_TYPES:
        if not data.billing_reference.strip():
            problems.append("a credit or debit note needs the number of the invoice it corrects (BR-KSA-56)")
        if not data.reason.strip():
            problems.append("a credit or debit note needs the reason it is issued (BR-KSA-17)")
    if not data.lines:
        problems.append("the document has no lines")
    for number, line in enumerate(data.lines, start=1):
        if line.quantity < ZERO or line.price < ZERO:
            problems.append(
                f"line {number} is negative; ZATCA accepts positive amounts only (BR-KSA-F-04). "
                "Bill this period's value, and issue a 381 credit note for a reduction"
            )
        if line.vat_category not in VAT_CATEGORIES:
            problems.append(f"line {number} has VAT category {line.vat_category!r}; use S, Z, E or O")
        elif line.vat_category != CATEGORY_STANDARD:
            if line.vat_rate != ZERO:
                problems.append(f"line {number} is category {line.vat_category} and must carry a 0% rate")
            reason = EXEMPTION_REASONS.get(line.exemption_code)
            if reason is None or reason.category != line.vat_category:
                problems.append(
                    f"line {number} is category {line.vat_category} and needs a VATEX-SA reason code of that "
                    "category (BR-KSA-CL-04)"
                )
            elif not (line.exemption_text or reason.text):
                problems.append(f"line {number} needs the reason text for {line.exemption_code}")
    if data.currency != TAX_CURRENCY and not data.exchange_rate:
        problems.append(
            f"the document is in {data.currency}; give the SAR exchange rate so the VAT total in SAR can be stated"
        )
    if data.icv < 1:
        problems.append("the invoice counter (ICV) starts at 1")
    if not data.previous_hash:
        problems.append("the previous invoice hash (PIH) is missing")
    if data.payment_means_code not in PAYMENT_MEANS:
        problems.append(f"payment means {data.payment_means_code!r} is not in the ZATCA list")
    return problems


# ── Tree ─────────────────────────────────────────────────────────────────────


def _address(parent: c14n.Element, address: Address) -> None:
    node = parent.add("cac:PostalAddress")
    for tag, value in (
        ("cbc:StreetName", address.street),
        ("cbc:AdditionalStreetName", address.additional_street),
        ("cbc:BuildingNumber", address.building_number),
        ("cbc:PlotIdentification", address.additional_number),
        ("cbc:CitySubdivisionName", address.district),
        ("cbc:CityName", address.city),
        ("cbc:PostalZone", address.postal_zone),
        ("cbc:CountrySubentity", address.country_subentity),
    ):
        if value:
            node.add(tag, value)
    node.add("cac:Country").add("cbc:IdentificationCode", address.country or SAUDI_ARABIA)


def _party(parent: c14n.Element, tag: str, party: Party) -> None:
    node = parent.add(tag).add("cac:Party")
    if party.id_scheme and party.id_value:
        node.add("cac:PartyIdentification").add("cbc:ID", party.id_value, schemeID=party.id_scheme)
    _address(node, party.address)
    scheme = node.add("cac:PartyTaxScheme")
    if party.vat_number:
        scheme.add("cbc:CompanyID", party.vat_number)
    scheme.add("cac:TaxScheme").add("cbc:ID", VAT_SCHEME)
    legal = node.add("cac:PartyLegalEntity")
    legal.add("cbc:RegistrationName", party.name)
    if party.legal_form:
        legal.add("cbc:CompanyLegalForm", party.legal_form)


def _tax_category(parent: c14n.Element, tag: str, category: str, rate: Decimal, code: str = "", text: str = "") -> None:
    node = parent.add(tag)
    node.add("cbc:ID", category)
    node.add("cbc:Percent", rate_text(rate))
    if category != CATEGORY_STANDARD:
        reason = EXEMPTION_REASONS.get(code)
        if code:
            node.add("cbc:TaxExemptionReasonCode", code)
        reason_text = text or (reason.text if reason else "")
        if reason_text:
            node.add("cbc:TaxExemptionReason", reason_text)
    node.add("cac:TaxScheme").add("cbc:ID", VAT_SCHEME)


def build_unsigned(data: ZatcaInvoiceInput) -> c14n.Element:
    """The document tree without the stamp and the QR.

    Raises :class:`ZatcaBuildError` listing everything that has to change.
    """
    problems = _input_problems(data)
    if problems:
        raise ZatcaBuildError("This invoice cannot be issued to ZATCA yet: " + "; ".join(problems) + ".")
    totals = compute(data)
    currency = data.currency

    root = c14n.Element("Invoice", ns={"": NS_INVOICE, "cac": NS_CAC, "cbc": NS_CBC, "ext": NS_EXT})
    root.add("cbc:ProfileID", PROFILE_ID)
    root.add("cbc:ID", data.number)
    root.add("cbc:UUID", data.uuid)
    root.add("cbc:IssueDate", data.issue_date)
    root.add("cbc:IssueTime", data.issue_time)
    root.add("cbc:InvoiceTypeCode", data.type_code, name=data.subtype.code)
    for note in data.notes:
        root.add("cbc:Note", note)
    if data.tax_point_date:
        root.add("cbc:TaxPointDate", data.tax_point_date)
    root.add("cbc:DocumentCurrencyCode", currency)
    root.add("cbc:TaxCurrencyCode", TAX_CURRENCY)
    if data.billing_reference:
        root.add("cac:BillingReference").add("cac:InvoiceDocumentReference").add("cbc:ID", data.billing_reference)
    icv = root.add("cac:AdditionalDocumentReference")
    icv.add("cbc:ID", "ICV")
    icv.add("cbc:UUID", str(data.icv))
    pih = root.add("cac:AdditionalDocumentReference")
    pih.add("cbc:ID", "PIH")
    pih.add("cac:Attachment").add("cbc:EmbeddedDocumentBinaryObject", data.previous_hash, mimeCode="text/plain")

    _party(root, "cac:AccountingSupplierParty", data.seller)
    if data.buyer is not None:
        _party(root, "cac:AccountingCustomerParty", data.buyer)
    else:
        # The UBL schema requires the element; a simplified invoice to an
        # unnamed consumer leaves it empty, as the SDK's samples do.
        root.add("cac:AccountingCustomerParty")
    if data.supply_date or data.supply_end_date:
        delivery = root.add("cac:Delivery")
        if data.supply_date:
            delivery.add("cbc:ActualDeliveryDate", data.supply_date)
        if data.supply_end_date:
            delivery.add("cbc:LatestDeliveryDate", data.supply_end_date)
    means = root.add("cac:PaymentMeans")
    means.add("cbc:PaymentMeansCode", data.payment_means_code)
    if data.type_code in NOTE_TYPES:
        means.add("cbc:InstructionNote", data.reason)

    # BT-111 in SAR without a breakdown, then BT-110 with it (P1 §9.1; SDK samples).
    root.add("cac:TaxTotal").add("cbc:TaxAmount", amount_text(totals.vat_in_sar), currencyID=TAX_CURRENCY)
    tax_total = root.add("cac:TaxTotal")
    tax_total.add("cbc:TaxAmount", amount_text(totals.vat), currencyID=currency)
    for group in totals.categories:
        subtotal = tax_total.add("cac:TaxSubtotal")
        subtotal.add("cbc:TaxableAmount", amount_text(group.taxable), currencyID=currency)
        subtotal.add("cbc:TaxAmount", amount_text(group.vat), currencyID=currency)
        _tax_category(
            subtotal, "cac:TaxCategory", group.category, group.rate, group.exemption_code, group.exemption_text
        )

    monetary = root.add("cac:LegalMonetaryTotal")
    monetary.add("cbc:LineExtensionAmount", amount_text(totals.line_extension), currencyID=currency)
    monetary.add("cbc:TaxExclusiveAmount", amount_text(totals.tax_exclusive), currencyID=currency)
    monetary.add("cbc:TaxInclusiveAmount", amount_text(totals.tax_inclusive), currencyID=currency)
    if data.prepayments:
        monetary.add("cbc:PrepaidAmount", amount_text(totals.prepaid), currencyID=currency)
    monetary.add("cbc:PayableAmount", amount_text(totals.payable), currencyID=currency)

    number = 0
    for line, figures in zip(data.lines, totals.lines, strict=True):
        number += 1
        node = root.add("cac:InvoiceLine")
        node.add("cbc:ID", str(number))
        node.add("cbc:InvoicedQuantity", quantity_text(line.quantity), unitCode=line.unit_code)
        node.add("cbc:LineExtensionAmount", amount_text(figures.net), currencyID=currency)
        line_tax = node.add("cac:TaxTotal")
        line_tax.add("cbc:TaxAmount", amount_text(figures.vat), currencyID=currency)
        line_tax.add("cbc:RoundingAmount", amount_text(figures.total), currencyID=currency)
        item = node.add("cac:Item")
        item.add("cbc:Name", line.description)
        _tax_category(item, "cac:ClassifiedTaxCategory", line.vat_category, line.vat_rate)
        node.add("cac:Price").add("cbc:PriceAmount", format(line.price, "f"), currencyID=currency)

    for prepayment in data.prepayments:
        number += 1
        node = root.add("cac:InvoiceLine")
        node.add("cbc:ID", str(number))
        node.add("cbc:InvoicedQuantity", "0.00", unitCode="PCE")
        node.add("cbc:LineExtensionAmount", "0.00", currencyID=currency)
        reference = node.add("cac:DocumentReference")
        reference.add("cbc:ID", prepayment.number)
        if prepayment.uuid:
            reference.add("cbc:UUID", prepayment.uuid)
        reference.add("cbc:IssueDate", prepayment.issue_date)
        reference.add("cbc:IssueTime", prepayment.issue_time)
        reference.add("cbc:DocumentTypeCode", TYPE_PREPAYMENT)
        line_tax = node.add("cac:TaxTotal")
        line_tax.add("cbc:TaxAmount", "0.00", currencyID=currency)
        line_tax.add("cbc:RoundingAmount", "0.00", currencyID=currency)
        subtotal = line_tax.add("cac:TaxSubtotal")
        subtotal.add("cbc:TaxableAmount", amount_text(prepayment.taxable_amount), currencyID=currency)
        subtotal.add("cbc:TaxAmount", amount_text(prepayment.vat_amount), currencyID=currency)
        _tax_category(
            subtotal,
            "cac:TaxCategory",
            prepayment.vat_category,
            prepayment.vat_rate,
            prepayment.exemption_code,
            prepayment.exemption_text,
        )
        item = node.add("cac:Item")
        item.add("cbc:Name", f"Prepayment adjustment {prepayment.number}")
        _tax_category(item, "cac:ClassifiedTaxCategory", prepayment.vat_category, prepayment.vat_rate)
        node.add("cac:Price").add("cbc:PriceAmount", "0.00", currencyID=currency)
    return root


def qr_fields(data: ZatcaInvoiceInput) -> QrFields:
    """Tags 1 to 5, read the way the SDK reads them off the document.

    Tag 4 is the amount due (``PayableAmount``), not ``TaxInclusiveAmount``:
    the SDK's QR generator reads that element and the official prepayment and
    rounding samples carry it. Tag 5 is the first VAT total, the one in SAR.
    """
    totals = compute(data)
    return QrFields(
        seller_name=data.seller.name,
        vat_number=data.seller.vat_number,
        timestamp=f"{data.issue_date}T{data.issue_time}",
        total_with_vat=amount_text(totals.payable),
        vat_total=amount_text(totals.vat_in_sar),
    )


# ── From a finance invoice ───────────────────────────────────────────────────


def _dec(value: Any, *, what: str) -> Decimal | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ZatcaBuildError(f"The {what} {value!r} is not a number.") from exc


def _text(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    return str(value).strip() if value is not None else ""


def address_from(raw: dict[str, Any]) -> Address:
    """An address from settings keys, or from the finance buyer party's keys."""
    return Address(
        street=_text(raw, "street") or _text(raw, "line1"),
        additional_street=_text(raw, "additional_street"),
        building_number=_text(raw, "building_number"),
        additional_number=_text(raw, "additional_number"),
        district=_text(raw, "district"),
        city=_text(raw, "city"),
        postal_zone=_text(raw, "postal_zone") or _text(raw, "postcode"),
        country_subentity=_text(raw, "country_subentity"),
        country=(_text(raw, "country") or _text(raw, "country_code") or SAUDI_ARABIA).upper(),
    )


def seller_from(settings: dict[str, Any], vat_number: str) -> Party:
    seller = settings.get("seller") if isinstance(settings.get("seller"), dict) else {}
    address = seller.get("address") if isinstance(seller.get("address"), dict) else {}
    return Party(
        name=_text(seller, "name"),
        vat_number=(vat_number or "").strip(),
        id_scheme=_text(seller, "id_scheme").upper() or "CRN",
        id_value=_text(seller, "id_value"),
        address=address_from(address),
    )


def buyer_from(defaults: dict[str, Any] | None, override: dict[str, Any], *, government: bool) -> Party | None:
    base = dict(defaults or {})
    base.update({k: v for k, v in override.items() if k != "address"})
    if isinstance(override.get("address"), dict):
        base.update(override["address"])
    if not _text(base, "name"):
        return None
    return Party(
        name=_text(base, "name"),
        vat_number=_text(base, "vat_number") or _text(base, "vat_id"),
        id_scheme=_text(base, "id_scheme").upper(),
        id_value=_text(base, "id_value"),
        address=address_from(base),
        legal_form=GOVERNMENT_LEGAL_FORM if government else _text(base, "legal_form"),
    )


def _vat(
    row: dict[str, Any], override: dict[str, Any], default_exemption: str, number: int
) -> tuple[str, Decimal, str, str]:
    rate = _dec(override.get("vat_rate"), what=f"line {number} VAT rate")
    if rate is None:
        rate = _dec(row.get("vat_rate"), what=f"line {number} VAT rate")
    category = (_text(override, "vat_category") or _text(row, "vat_category")).upper()
    if category not in VAT_CATEGORIES:
        category = CATEGORY_STANDARD if (rate or ZERO) > ZERO else ""
    if rate is None:
        rate = ZERO if category and category != CATEGORY_STANDARD else None
    if rate is None or not category:
        raise ZatcaBuildError(
            f"Line {number} has no VAT rate, or a 0% rate without saying whether it is zero rated (Z), exempt (E) "
            "or out of scope (O). Set the line's VAT category, or the document's ZATCA line fields."
        )
    code = _text(override, "exemption_code") or (default_exemption if category != CATEGORY_STANDARD else "")
    text = _text(override, "exemption_text")
    if category == CATEGORY_OUT_OF_SCOPE and not code:
        code = "VATEX-SA-OOS"
    return category, rate, code, text


def input_from_invoice(
    *,
    invoice: dict[str, Any],
    lines: list[dict[str, Any]],
    vat_number: str,
    settings: dict[str, Any],
    zatca_fields: dict[str, Any],
    buyer: dict[str, Any] | None,
    icv: int,
    previous_hash: str,
    unit_code_for: Any,
    now: dt.datetime,
) -> ZatcaInvoiceInput:
    """Neutral inputs from a finance invoice, the registration's settings and the document's ZATCA fields.

    ``invoice`` and ``lines`` use the finance model's field names. Retention is
    read and deliberately not used: VAT is due on the gross (P4 §5.2).
    """
    type_code = _text(zatca_fields, "document_type") or TYPE_INVOICE
    simplified = bool(zatca_fields.get("simplified", settings.get("simplified_by_default", False)))
    subtype = Subtype(
        simplified=simplified,
        third_party=bool(zatca_fields.get("third_party")),
        nominal=bool(zatca_fields.get("nominal")),
        export=bool(zatca_fields.get("export")),
        summary=bool(zatca_fields.get("summary")),
        self_billed=bool(zatca_fields.get("self_billed")),
    )
    government = zatca_fields.get("government") if isinstance(zatca_fields.get("government"), dict) else {}
    is_government_claim = bool(government.get("contract")) and _text(government, "role").lower() != "subcontractor"

    overrides = zatca_fields.get("lines") if isinstance(zatca_fields.get("lines"), list) else []
    default_exemption = _text(zatca_fields, "exemption_code")
    built: list[Line] = []
    for index, row in enumerate(lines):
        number = index + 1
        override = overrides[index] if index < len(overrides) and isinstance(overrides[index], dict) else {}
        quantity = _dec(row.get("quantity"), what=f"line {number} quantity")
        price = _dec(row.get("unit_rate"), what=f"line {number} unit rate")
        amount = _dec(row.get("amount"), what=f"line {number} amount")
        if quantity is None or price is None:
            if amount is None:
                raise ZatcaBuildError(f"Line {number} has neither a quantity and rate nor an amount.")
            quantity, price = Decimal("1"), amount
        if amount is not None and abs(money(quantity * price) - money(amount)) > CENT:
            raise ZatcaBuildError(
                f"Line {number} says {quantity} x {price} but its amount is {amount}. ZATCA checks that the line "
                "amount is quantity times price, so correct the line before issuing."
            )
        category, rate, code, text = _vat(row, override, default_exemption, number)
        built.append(
            Line(
                description=_text(override, "description") or _text(row, "description") or f"Line {number}",
                quantity=quantity,
                unit_code=_text(override, "unit_code") or unit_code_for(row.get("unit")),
                price=price,
                vat_category=category,
                vat_rate=rate,
                exemption_code=code,
                exemption_text=text,
            )
        )

    prepayments: list[Prepayment] = []
    for index, raw in enumerate(zatca_fields.get("prepayments") or []):
        if not isinstance(raw, dict):
            continue
        taxable = _dec(raw.get("taxable_amount"), what=f"prepayment {index + 1} taxable amount")
        if taxable is None:
            raise ZatcaBuildError(f"Prepayment {index + 1} needs the taxable amount of the advance invoice.")
        prepayments.append(
            Prepayment(
                number=_text(raw, "number"),
                uuid=_text(raw, "uuid"),
                issue_date=_text(raw, "issue_date")[:10],
                issue_time=_text(raw, "issue_time") or "00:00:00",
                taxable_amount=taxable,
                vat_category=(_text(raw, "vat_category") or CATEGORY_STANDARD).upper(),
                vat_rate=_dec(raw.get("vat_rate"), what=f"prepayment {index + 1} VAT rate") or Decimal("15"),
                exemption_code=_text(raw, "exemption_code"),
                exemption_text=_text(raw, "exemption_text"),
            )
        )

    issue_date = str(invoice.get("invoice_date") or "").strip()[:10] or now.date().isoformat()
    supply_date = _text(zatca_fields, "supply_date")[:10]
    if not supply_date and type_code == TYPE_INVOICE and not subtype.simplified:
        # BR-KSA-15: a standard tax invoice states its supply date. The
        # contracting guideline ties the date of supply of a continuous supply
        # to the invoice (P4 §5.2), so the invoice date is the honest default.
        supply_date = issue_date
    buyer_override = zatca_fields.get("buyer") if isinstance(zatca_fields.get("buyer"), dict) else {}
    exchange_rate = _dec(zatca_fields.get("exchange_rate"), what="exchange rate")
    notes = tuple(str(n).strip() for n in (zatca_fields.get("notes") or []) if str(n).strip())
    return ZatcaInvoiceInput(
        number=str(invoice.get("invoice_number") or "").strip(),
        uuid=_text(zatca_fields, "uuid") or str(uuid_module.uuid4()),
        issue_date=issue_date,
        issue_time=_text(zatca_fields, "issue_time") or now.strftime("%H:%M:%S"),
        type_code=type_code,
        subtype=subtype,
        currency=(str(invoice.get("currency_code") or TAX_CURRENCY).strip().upper() or TAX_CURRENCY),
        seller=seller_from(settings, vat_number),
        buyer=buyer_from(buyer, buyer_override, government=is_government_claim),
        lines=tuple(built),
        icv=icv,
        previous_hash=previous_hash,
        billing_reference=_text(zatca_fields, "billing_reference"),
        reason=_text(zatca_fields, "reason"),
        payment_means_code=_text(zatca_fields, "payment_means_code") or _text(settings, "payment_means_code") or "42",
        supply_date=supply_date,
        supply_end_date=_text(zatca_fields, "supply_end_date")[:10],
        tax_point_date=_text(government, "payment_order_date")[:10] if is_government_claim else "",
        prepayments=tuple(prepayments),
        exchange_rate=exchange_rate,
        notes=notes,
    )


__all__ = [
    "MEDIA_TYPE",
    "Address",
    "CategoryFigures",
    "Line",
    "LineFigures",
    "Party",
    "Prepayment",
    "Totals",
    "ZatcaBuildError",
    "ZatcaInvoiceInput",
    "address_from",
    "amount_text",
    "build_unsigned",
    "buyer_from",
    "compute",
    "input_from_invoice",
    "money",
    "qr_fields",
    "seller_from",
]
