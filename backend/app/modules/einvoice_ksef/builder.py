# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Finance invoice -> FA(3) document.

The finance invoice is the source of the amounts, the lines and the buyer. What
the finance model has no field for (the invoice kind, a correction's original,
the advances a settlement accounts for, the Annex 15 flags, the contract number)
comes from the clearance document's ``country_fields["ksef"]``. The seller is the
registration: its tax registration id is the NIP, its ``settings["ksef"]["issuer"]``
the name and address.

The VAT is recomputed from the lines the way FA(3) defines it, once per rate
group. If that disagrees with the VAT the invoice already states, the builder
refuses rather than send a document whose VAT differs from the books.
"""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from app.modules.einvoice_ksef import fa3, split_payment

# EN 16931 VAT category codes as the finance lines carry them, to FA(3) rate codes
# for the lines whose code is not simply a percentage.
_CATEGORY_CODES: dict[str, str] = {
    "E": "zw",
    "AE": "oo",
    "O": "np I",
    "K": "0 WDT",
    "G": "0 EX",
    "Z": "0 KR",
}

# Greece is GR as a country and EL as a VAT prefix; both are listed so either spelling is EU.
_EU = frozenset(
    {
        "AT",
        "BE",
        "BG",
        "CY",
        "CZ",
        "DE",
        "DK",
        "EE",
        "EL",
        "ES",
        "FI",
        "FR",
        "GR",
        "HR",
        "HU",
        "IE",
        "IT",
        "LT",
        "LU",
        "LV",
        "MT",
        "NL",
        "PT",
        "RO",
        "SE",
        "SI",
        "SK",
        "XI",
    }
)


def _dec(value: Any, *, what: str) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise fa3.Fa3BuildError(f"{what} {value!r} is not a number") from exc
    if not parsed.is_finite():
        raise fa3.Fa3BuildError(f"{what} is not a finite number")
    return parsed


def _flag(value: Any) -> bool:
    return value is True or str(value).strip().lower() in ("1", "true", "yes")


# The split payment marker the finance invoice may carry in its metadata. Kept
# as a cross-check: P_18A is still decided from the lines, and a disagreement
# stops the build instead of choosing one side.
STORED_SPLIT_PAYMENT_KEY = "split_payment"


def vat_code_for(rate: Decimal | None, category: str | None) -> str:
    """The FA(3) rate code for a finance line's rate and EN 16931 category."""
    code = (category or "").strip().upper()
    if code in _CATEGORY_CODES:
        return _CATEGORY_CODES[code]
    if rate is None:
        raise fa3.Fa3BuildError("a line has neither a VAT rate nor a VAT category")
    normalized = rate.normalize()
    if normalized == 0:
        return "0 KR"
    text = format(normalized, "f")
    if text not in fa3.RATE_FIELDS:
        raise fa3.Fa3BuildError(f"{text}% is not a Polish VAT rate (23, 8, 5 and the historical 22, 7, 4, 3)")
    return text


def party_from_buyer(buyer: dict[str, Any]) -> fa3.Party:
    """A finance buyer dict (name, country_code, vat_id, line1, postcode, city) as an FA(3) party."""
    country = str(buyer.get("country_code") or "PL").strip().upper() or "PL"
    vat_id = str(buyer.get("vat_id") or "").replace(" ", "").replace("-", "").upper()
    line2 = " ".join(p for p in (str(buyer.get("postcode") or "").strip(), str(buyer.get("city") or "").strip()) if p)
    common = {
        "name": str(buyer.get("name") or "").strip(),
        "country": country,
        "address_line1": str(buyer.get("line1") or "").strip(),
        "address_line2": line2,
    }
    if country == "PL":
        nip = vat_id[2:] if vat_id.startswith("PL") else vat_id
        return fa3.Party(nip=nip, no_id=not nip, **common)
    if country in _EU and vat_id:
        prefix = "EL" if country == "GR" else country
        number = vat_id[len(prefix) :] if vat_id.startswith(prefix) else vat_id
        return fa3.Party(eu_country=prefix, eu_vat=number, **common)
    if vat_id:
        return fa3.Party(other_country=country, other_id=vat_id, **common)
    return fa3.Party(no_id=True, **common)


def _seller(nip: str, settings: dict[str, Any], seller_defaults: dict[str, Any]) -> fa3.Party:
    issuer = settings.get("issuer") if isinstance(settings.get("issuer"), dict) else {}
    defaults = seller_defaults or {}
    line2 = " ".join(
        p for p in (str(defaults.get("postcode") or "").strip(), str(defaults.get("city") or "").strip()) if p
    )
    return fa3.Party(
        name=str(issuer.get("name") or defaults.get("name") or "").strip(),
        nip=(nip or "").strip().upper().removeprefix("PL"),
        country=str(issuer.get("country") or "PL").strip().upper(),
        address_line1=str(issuer.get("address_line1") or defaults.get("line1") or "").strip(),
        address_line2=str(issuer.get("address_line2") or line2).strip(),
        email=str(issuer.get("email") or "").strip(),
    )


def build_input_from_invoice(
    *,
    invoice: dict[str, Any],
    lines: list[dict[str, Any]],
    nip: str,
    settings: dict[str, Any],
    ksef_fields: dict[str, Any],
    buyer: dict[str, Any] | None,
    seller_defaults: dict[str, Any] | None = None,
) -> fa3.Fa3Input:
    """FA(3) inputs from plain dicts, so it is testable without a database.

    ``invoice`` and ``lines`` use the finance model's field names.
    """
    overrides = ksef_fields.get("lines") if isinstance(ksef_fields.get("lines"), list) else []
    subtotal = _dec(invoice.get("amount_subtotal"), what="the invoice subtotal") or Decimal("0")
    tax = _dec(invoice.get("tax_amount"), what="the invoice VAT") or Decimal("0")
    header_rate = (tax / subtotal * 100).quantize(Decimal("1")) if subtotal else None

    built: list[fa3.Line] = []
    for index, row in enumerate(lines):
        where = f"line {index + 1}"
        override = overrides[index] if index < len(overrides) and isinstance(overrides[index], dict) else {}
        quantity = _dec(row.get("quantity"), what=f"{where} quantity") or Decimal("0")
        price = _dec(row.get("unit_rate"), what=f"{where} unit rate") or Decimal("0")
        amount = _dec(row.get("amount"), what=f"{where} amount")
        net = amount if amount is not None else (quantity * price).quantize(fa3.CENT)
        code = str(override.get("vat_code") or "").strip()
        if not code:
            rate = _dec(row.get("vat_rate"), what=f"{where} VAT rate")
            code = vat_code_for(rate if rate is not None else header_rate, row.get("vat_category"))
        built.append(
            fa3.Line(
                description=str(row.get("description") or "").strip(),
                quantity=quantity,
                unit=str(override.get("unit") or row.get("unit") or "").strip(),
                unit_net_price=price,
                net_amount=net,
                vat_code=code,
                annex_15=_flag(override.get("annex_15")),
                pkwiu=str(override.get("pkwiu") or "").strip(),
                gtu=str(override.get("gtu") or "").strip(),
                delivery_date=str(override.get("delivery_date") or "").strip(),
                state_before=_flag(override.get("state_before")),
            )
        )

    kind = str(ksef_fields.get("kind") or fa3.KIND_VAT).strip().upper()
    currency = str(invoice.get("currency_code") or "PLN").strip().upper() or "PLN"
    rate = _dec(ksef_fields.get("exchange_rate"), what="the exchange rate")

    totals = fa3.compute_totals(built)
    if kind not in fa3.ADVANCE_KINDS and abs(totals.vat_total - tax) > fa3.CENT * max(len(totals.vat), 1):
        raise fa3.Fa3BuildError(
            f"the invoice states VAT {tax} but its lines give {totals.vat_total} when rounded per rate as FA(3) "
            "requires; correct the invoice before sending it"
        )
    decision = split_payment.decide(
        gross=totals.gross,
        currency=currency,
        annex_15_lines=sum(1 for line in built if line.annex_15),
        exchange_rate=rate,
    )
    if decision.verdict == split_payment.UNDECIDABLE:
        raise fa3.Fa3BuildError(f"split payment cannot be decided: {decision.reason}")
    metadata = invoice.get("metadata") if isinstance(invoice.get("metadata"), dict) else {}
    stored = metadata.get(STORED_SPLIT_PAYMENT_KEY)
    if decision.verdict == split_payment.NOT_CHECKED:
        # No threshold to compare with. The invoice's own marker is the only
        # answer left; without it the build stops rather than guess a number.
        if stored is None:
            raise fa3.Fa3BuildError(
                f"split payment was not checked: {decision.reason}; record the split payment marker on the "
                "invoice or restore the Polish VAT data"
            )
        split_required = _flag(stored)
    else:
        if stored is not None and _flag(stored) != decision.required:
            raise fa3.Fa3BuildError(
                f"the invoice is recorded as split payment {'required' if _flag(stored) else 'not required'} but "
                f"its lines say otherwise ({decision.reason}); mark the Annex 15 lines or correct the invoice"
            )
        split_required = decision.required

    correction = None
    raw_correction = ksef_fields.get("correction") if isinstance(ksef_fields.get("correction"), dict) else None
    if raw_correction is not None:
        try:
            correction_type = int(raw_correction.get("type") or 2)
        except (TypeError, ValueError) as exc:
            raise fa3.Fa3BuildError("the correction type is 1, 2 or 3") from exc
        correction = fa3.Correction(
            reason=str(raw_correction.get("reason") or "").strip(),
            type=correction_type,
            corrected=tuple(
                fa3.CorrectedInvoice(
                    number=str(item.get("number") or "").strip(),
                    issue_date=str(item.get("date") or "").strip()[:10],
                    ksef_number=str(item.get("ksef_number") or "").strip(),
                )
                for item in raw_correction.get("corrected") or []
                if isinstance(item, dict)
            ),
        )

    advance = ksef_fields.get("advance") if isinstance(ksef_fields.get("advance"), dict) else {}
    order_lines = tuple(
        fa3.OrderLine(
            description=str(item.get("description") or "").strip(),
            quantity=_dec(item.get("quantity"), what="order line quantity") or Decimal("1"),
            unit=str(item.get("unit") or "").strip(),
            unit_net_price=_dec(item.get("unit_net_price"), what="order line price") or Decimal("0"),
            net_amount=_dec(item.get("net_amount"), what="order line net") or Decimal("0"),
            vat_amount=_dec(item.get("vat_amount"), what="order line VAT") or Decimal("0"),
            vat_code=str(item.get("vat_code") or "23").strip(),
            annex_15=_flag(item.get("annex_15")),
        )
        for item in advance.get("order_lines") or []
        if isinstance(item, dict)
    )
    contracts = tuple(
        fa3.Contract(number=str(item.get("number") or "").strip(), date=str(item.get("date") or "").strip()[:10])
        for item in ksef_fields.get("contracts") or []
        if isinstance(item, dict)
    )
    return fa3.Fa3Input(
        seller=_seller(nip, settings, seller_defaults or {}),
        buyer=party_from_buyer(buyer or {}),
        number=str(invoice.get("invoice_number") or "").strip(),
        issue_date=str(invoice.get("invoice_date") or "").strip()[:10],
        currency=currency,
        lines=tuple(built),
        kind=kind,
        place_of_issue=str(ksef_fields.get("place_of_issue") or "").strip(),
        delivery_date=str(ksef_fields.get("delivery_date") or "").strip()[:10],
        period_from=str(ksef_fields.get("period_from") or "").strip()[:10],
        period_to=str(ksef_fields.get("period_to") or "").strip()[:10],
        exchange_rate=rate,
        cash_accounting=_flag(ksef_fields.get("cash_accounting")),
        self_billing=_flag(ksef_fields.get("self_billing")),
        reverse_charge=_flag(ksef_fields.get("reverse_charge")) or any(line.vat_code == "oo" for line in built),
        split_payment=split_required,
        exemption_basis=str(ksef_fields.get("exemption_basis") or "").strip(),
        correction=correction,
        advance_invoices=tuple(
            fa3.AdvanceInvoiceRef(
                number=str(item.get("number") or "").strip(), ksef_number=str(item.get("ksef_number") or "").strip()
            )
            for item in advance.get("advance_invoices") or []
            if isinstance(item, dict)
        ),
        order_value_gross=_dec(advance.get("order_value_gross"), what="the order value"),
        order_lines=order_lines,
        contracts=contracts,
        due_date=str(invoice.get("due_date") or "").strip()[:10],
        bank_account=str(ksef_fields.get("bank_account") or settings.get("bank_account") or "").strip(),
    )


async def build_from_invoice(
    session: Any,
    *,
    invoice_id: uuid.UUID,
    profile: Any,
    country_fields: dict[str, Any],
) -> tuple[str, str]:
    """The payload builder registered for ``ksef_fa_3``."""
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
        session, contact_id=invoice.contact_id, invoice_direction=invoice.invoice_direction
    )
    settings = dict((profile.settings or {}).get("ksef") or {})
    ksef_fields = country_fields.get("ksef") if isinstance(country_fields.get("ksef"), dict) else {}
    seller_defaults = (
        defaults.get("seller") if isinstance(defaults, dict) and isinstance(defaults.get("seller"), dict) else {}
    )
    try:
        data = build_input_from_invoice(
            invoice={
                "invoice_number": invoice.invoice_number,
                "invoice_date": invoice.invoice_date,
                "due_date": invoice.due_date,
                "currency_code": invoice.currency_code,
                "amount_subtotal": invoice.amount_subtotal,
                "tax_amount": invoice.tax_amount,
                "metadata": dict(invoice.metadata_ or {}),
            },
            lines=[
                {
                    "description": row.description,
                    "quantity": row.quantity,
                    "unit": row.unit,
                    "unit_rate": row.unit_rate,
                    "amount": row.amount,
                    "vat_rate": row.vat_rate,
                    "vat_category": row.vat_category,
                }
                for row in rows
            ],
            nip=profile.tax_registration_id,
            settings=settings,
            ksef_fields=ksef_fields,
            buyer=defaults.get("buyer") if isinstance(defaults, dict) else None,
            seller_defaults=seller_defaults,
        )
        return fa3.build_xml(data), fa3.MEDIA_TYPE
    except fa3.Fa3BuildError as exc:
        raise ClearanceError(f"The FA(3) document cannot be built: {exc}") from exc


__all__ = [
    "STORED_SPLIT_PAYMENT_KEY",
    "build_from_invoice",
    "build_input_from_invoice",
    "party_from_buyer",
    "vat_code_for",
]
