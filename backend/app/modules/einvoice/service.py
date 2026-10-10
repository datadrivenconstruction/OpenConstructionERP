# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Map a finance ``Invoice`` aggregate onto an EN 16931 :class:`EInvoice`
and render it as CII XML.

Kept ORM-free on purpose (takes plain dicts, exactly like
``finance.br_invoice_pdf.render_br_invoice_pdf``) so it is trivially testable
and the finance router can feed it the same ``invoice`` / ``line_items`` dicts
it already builds for the Brazilian PDF route.

German-specific fields (Leitweg-ID / buyer reference, explicit VAT rate,
seller and buyer master data) live under ``invoice['metadata']['einvoice']``,
mirroring the Brazilian ``metadata['br_fields']`` precedent. Anything the
caller passes explicitly (``seller`` / ``buyer``) wins over metadata.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.modules.einvoice.cii import (
    EInvoice,
    EInvoiceError,
    EInvoiceLine,
    Party,
    TaxSubtotal,
    build_cii_xml,
    validate_rules,
)
from app.modules.einvoice.profiles import EN16931_SYNTAXES, SYNTAX_CII, SYNTAX_UBL, SYNTAX_UBL_TR, Profile, get_profile
from app.modules.einvoice.rules import DE_INVOICE_TYPE_CODES, FATAL, RuleViolation, money_decimals
from app.modules.einvoice.tr_mapper import TrGroupTaxes, TrMapping, build_tr_invoice
from app.modules.einvoice.ubl import build_ubl_xml

_2P = Decimal("0.01")


def _dec(value: Any, default: str = "0") -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None or value == "":
        return Decimal(default)
    try:
        return Decimal(str(value))
    except (ArithmeticError, ValueError, TypeError):
        return Decimal(default)


def _money_quantum(currency: str) -> Decimal:
    """The smallest amount ``currency`` can carry on a document.

    Read from the same function that decides how many decimals get written, so
    an amount rounded to this quantum and the string later written for it are
    the same number rather than two roundings of one figure.

    Args:
        currency: the invoice currency (BT-5).

    Returns:
        The quantum, e.g. ``0.01`` for a two-decimal currency and ``1`` for a
        currency written in whole units.
    """
    return Decimal(1).scaleb(-money_decimals(currency))


def _is_true(value: Any) -> bool:
    """Read a permissive boolean flag (True / "true" / "yes" / "1")."""
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"true", "yes", "1", "y"}


# BT-3 document type codes: 380 commercial invoice, 381 credit note.
_INVOICE_TYPE_CODE = "380"
_CREDIT_NOTE_TYPE_CODE = "381"

#: The BT-3 values a user may choose, code to name. Re-exported from the rules
#: module so the catalogue a screen offers and the catalogue BR-DE-17 judges
#: against are the same object, and a construction invoice can actually be
#: called one (875, 876, 877) instead of being filed as an ordinary 380.
INVOICE_TYPE_CODES = DE_INVOICE_TYPE_CODES


def _resolve_type_code(invoice: dict[str, Any], ei: dict[str, Any]) -> str:
    """Decide the BT-3 document type code from the invoice data.

    An explicit ``metadata.einvoice.type_code`` (or top-level ``type_code``)
    wins, and is passed through even when it is not in
    :data:`INVOICE_TYPE_CODES`: BR-DE-17 is advisory in the CIUS, so an unusual
    code is reported as a warning by the rules and never silently rewritten
    here. Otherwise a credit flag (``credit_note`` / ``is_credit_note`` /
    ``invoice_direction == "credit_note"``) selects the credit note code 381,
    and everything else is a commercial invoice (380).
    """
    explicit = str(ei.get("type_code") or invoice.get("type_code") or "").strip()
    if explicit:
        return explicit
    flags = (
        ei.get("credit_note"),
        ei.get("is_credit_note"),
        invoice.get("credit_note"),
        invoice.get("is_credit_note"),
    )
    if any(_is_true(flag) for flag in flags):
        return _CREDIT_NOTE_TYPE_CODE
    if str(invoice.get("invoice_direction") or "").strip().lower() == "credit_note":
        return _CREDIT_NOTE_TYPE_CODE
    return _INVOICE_TYPE_CODE


def _clean(value: Any) -> str | None:
    """Strip a metadata string, returning None when it holds nothing."""
    text = str(value or "").strip()
    return text or None


def _group_vat(lines: list[EInvoiceLine], currency: str) -> list[TaxSubtotal]:
    """Build the VAT breakdown (BG-23), one group per category and rate.

    EN 16931 wants one group for each distinct combination of VAT category
    code and rate, whose taxable amount is the sum of exactly the lines that
    carry it (the BR-S-8 family) and whose VAT amount follows from that basis
    and that rate (BR-CO-17).

    Args:
        lines: the invoice lines, each already carrying its own rate/category.
        currency: the invoice currency, which decides how the VAT is rounded.

    Returns:
        The groups, ordered by category then descending rate for a stable
        document.
    """
    basis_by_key: dict[tuple[str, Decimal], Decimal] = {}
    for line in lines:
        key = (line.vat_category, line.vat_rate)
        basis_by_key[key] = basis_by_key.get(key, Decimal("0")) + line.line_net_amount

    quantum = _money_quantum(currency)
    groups = [
        TaxSubtotal(
            category=category,
            rate=rate,
            basis=basis,
            tax_amount=(basis * rate / Decimal("100")).quantize(quantum, rounding=ROUND_HALF_UP),
        )
        for (category, rate), basis in basis_by_key.items()
    ]
    groups.sort(key=lambda g: (g.category, -g.rate))
    return groups


def _coerce_party(value: Party | dict | None, *, fallback_name: str = "") -> Party:
    if isinstance(value, Party):
        return value
    d = dict(value or {})
    return Party(
        name=str(d.get("name") or fallback_name or "").strip(),
        # BT-40 / BT-55. No fallback: a country nobody typed has to stay empty
        # so BR-9 / BR-11 can say so. Shared by seller and buyer, and the buyer
        # is the more common gap, because the standing settings hold seller
        # fields only.
        country_code=str(d.get("country_code") or d.get("country") or "").strip(),
        vat_id=(d.get("vat_id") or d.get("ust_id") or None),
        tax_number=(d.get("tax_number") or d.get("steuernummer") or None),
        legal_id=(d.get("legal_id") or None),
        line1=(d.get("line1") or d.get("address") or None),
        postcode=(d.get("postcode") or d.get("zip") or None),
        city=(d.get("city") or None),
        contact_name=(d.get("contact_name") or None),
        contact_phone=(d.get("contact_phone") or None),
        # ``email`` is the older spelling, and it always meant the address a
        # person reads rather than a network endpoint. It is BT-43, so it is read
        # here rather than left pointing at a field that no longer exists.
        contact_email=(d.get("contact_email") or d.get("email") or None),
        contact_id_scheme=(d.get("electronic_address_scheme") or None),
        electronic_address=(d.get("electronic_address") or None),
    )


def _is_empty(value: Any) -> bool:
    """True for the shapes a stored-but-unset field arrives in."""
    return value is None or value == "" or value == {} or value == []


def _merge_defaults(ei: dict[str, Any], defaults: dict[str, Any] | None) -> dict[str, Any]:
    """Fill the gaps in one invoice's e-invoice metadata from standing settings.

    Field-wise, and one level into the seller and buyer parties, because an
    invoice that renames the seller still wants the configured address rather
    than no address at all. A whole-object fallback would look right on an
    invoice that says nothing and silently drop the address on one that says
    only the name.

    The invoice always wins where it speaks: a value on the document is a
    deliberate departure from the configuration, not a coincidence.
    """
    if not defaults:
        return ei
    merged = dict(ei)
    for key, value in defaults.items():
        if _is_empty(value):
            continue
        current = merged.get(key)
        if isinstance(value, dict) and isinstance(current, dict):
            nested = dict(value)
            nested.update({k: v for k, v in current.items() if not _is_empty(v)})
            merged[key] = nested
        elif _is_empty(current):
            merged[key] = value
    return merged


def merge_einvoice_defaults(ei: dict[str, Any], defaults: dict[str, Any] | None) -> dict[str, Any]:
    """One invoice's e-invoice metadata with the standing settings filled in beneath it.

    The same merge ``build_einvoice`` applies, exposed for a caller that reads
    the parties without building the EN 16931 model (the UBL-TR export), so
    both formats resolve seller and buyer identically.
    """
    return _merge_defaults(ei, defaults)


def build_einvoice(
    *,
    invoice: dict[str, Any],
    line_items: list[dict[str, Any]],
    profile: str,
    seller: Party | dict | None = None,
    buyer: Party | dict | None = None,
    seller_fallback_name: str = "",
    buyer_fallback_name: str = "",
    defaults: dict[str, Any] | None = None,
) -> EInvoice:
    """Assemble an :class:`EInvoice` from finance invoice + line dicts.

    VAT is read per line (BT-152 rate, BT-151 category) when the lines carry
    it, which is what a construction invoice needs: standard-rated works and a
    reverse-charged subcontract can sit on one document. The VAT breakdown
    (BG-23) is then one group per distinct category and rate, and the VAT total
    follows from those groups so the document reconciles (BR-CO-14, BR-CO-17).

    Lines that carry no rate of their own fall back to the invoice-level rate,
    taken from ``metadata.einvoice.vat_rate`` or derived from
    ``tax_amount / amount_subtotal``, which is how every invoice written before
    per-line VAT existed still renders exactly as it did.

    Retention is represented as a prepaid/withheld amount (BT-113) so the
    amount due reconciles (BR-CO-16).
    """
    meta = dict(invoice.get("metadata") or {})
    # Merged once, here, before anything reads it. The validator and both
    # renderers reach the document through this function, so a merge anywhere
    # further out could leave one of them judging a different document from the
    # one that gets produced.
    ei = _merge_defaults(dict(meta.get("einvoice") or {}), defaults)

    subtotal = _dec(invoice.get("amount_subtotal"))
    header_tax_total = _dec(invoice.get("tax_amount"))
    retention = _dec(invoice.get("retention_amount"))
    # BT-5, mandatory and the same shape as the country: finance stores an unset
    # currency as an empty string, so substituting one here would put a figure on
    # the document in a currency nobody chose and leave BR-5 unable to fire.
    currency = str(invoice.get("currency_code") or "").strip()

    # Invoice-level fallback rate, used by any line that names none.
    if ei.get("vat_rate") not in (None, ""):
        default_rate = _dec(ei.get("vat_rate"))
    elif subtotal > 0:
        default_rate = (header_tax_total / subtotal * 100).quantize(_2P, rounding=ROUND_HALF_UP)
    else:
        default_rate = Decimal("0")
    default_category = str(ei.get("vat_category") or ("S" if default_rate > 0 else "Z"))

    # Lines. Trust line amounts as the source of the document line total so
    # BR-CO-10 holds even if the stored header subtotal drifted by a cent.
    #
    # Each amount is rounded to the currency's own quantum before it is either
    # carried on a line or added into the total, because BR-CO-10 is exact and
    # a receiver adds up the amounts we WRITE. On a currency written in whole
    # units, three lines of 100.40 are each written as 100 while an unrounded
    # total is written as 301, and the document then contradicts itself by one
    # unit per line. Rounding here, once, makes the sum we write the sum of the
    # numbers we wrote. It is the currency's decimal count that decides the
    # quantum, so this holds whatever that count is for any given currency.
    quantum = _money_quantum(currency)
    lines: list[EInvoiceLine] = []
    line_total = Decimal("0")
    any_line_rate = False
    any_line_category = False

    for idx, li in enumerate(line_items, start=1):
        amount = _dec(li.get("amount")).quantize(quantum, rounding=ROUND_HALF_UP)
        if li.get("vat_rate") not in (None, ""):
            rate = _dec(li.get("vat_rate"))
            any_line_rate = True
        else:
            rate = default_rate
        raw_category = str(li.get("vat_category") or "").strip().upper()
        if raw_category:
            any_line_category = True
        category = raw_category or default_category
        lines.append(
            EInvoiceLine(
                line_id=str(li.get("line_id") or idx),
                name=str(li.get("description") or "-"),
                quantity=_dec(li.get("quantity"), "1"),
                unit=li.get("unit"),
                net_unit_price=_dec(li.get("unit_rate")),
                line_net_amount=amount,
                vat_rate=rate,
                vat_category=category,
            )
        )
        line_total += amount

    if not lines:
        raise EInvoiceError("invoice has no line items (BR-16)")

    tax_subtotals = _group_vat(lines, currency)
    # When the lines carry their own rates the VAT total has to follow from
    # them, or the breakdown and the total contradict each other (BR-CO-14).
    # Otherwise the stored header amount stays authoritative, so a single-rate
    # invoice renders exactly the figure the user approved.
    if any_line_rate:
        tax_total = sum((g.tax_amount for g in tax_subtotals), Decimal("0"))
    else:
        tax_total = header_tax_total
        tax_subtotals = [
            TaxSubtotal(category=default_category, rate=default_rate, basis=line_total, tax_amount=tax_total)
        ]

    # BT-120 / BT-121: one declared reason for the whole invoice. It belongs to
    # the exempting groups (E, AE, K, G, O), so on a mixed document - standard
    # -rated own works beside a reverse-charged subcontract, the construction
    # case - it lands on the exempt group only and the S group stays clean, as
    # BR-S-10 demands. When no group can legitimately carry it, it is written
    # onto every group as given rather than dropped: a claimed exemption on an
    # all-standard or zero-rated document is a contradiction, and BR-S-10 /
    # BR-Z-10 report it instead of this code deciding which half to believe.
    exemption_reason = _clean(ei.get("vat_exemption_reason"))
    exemption_reason_code = _clean(ei.get("vat_exemption_reason_code"))
    if exemption_reason or exemption_reason_code:
        from app.modules.einvoice.rules import _REASON_REQUIRED_CATEGORIES

        carriers = [g for g in tax_subtotals if g.category in _REASON_REQUIRED_CATEGORIES] or tax_subtotals
        for grp in carriers:
            grp.exemption_reason = exemption_reason
            grp.exemption_reason_code = exemption_reason_code

    # Did anybody actually state the VAT treatment? An explicit invoice-level
    # rate or category, any line-level rate or category, or a non-zero tax
    # amount all count; their joint absence means the 0% / Z fallback above was
    # an inference, which OCE-VAT-01 turns into an advisory instead of silence.
    vat_declared = (
        ei.get("vat_rate") not in (None, "")
        or bool(str(ei.get("vat_category") or "").strip())
        or any_line_rate
        or any_line_category
        or header_tax_total != 0
    )

    # Totals recomputed so the document reconciles (BR-CO-10/13/15/16).
    tax_basis_total = line_total
    grand_total = tax_basis_total + tax_total
    # BT-113 is written at the document's quantum, so it has to be subtracted
    # at that quantum too, or BT-115 disagrees with the subtraction a receiver
    # performs on the two figures in front of it (BR-CO-16, exact). The case
    # that breaks is an amount withheld at exactly half a unit: rounding it and
    # rounding the difference then go opposite ways. This only becomes
    # reachable because BT-109 above is now exact - while the basis still
    # carried a fraction of its own it was cancelling the half by accident.
    prepaid = (retention if retention > 0 else Decimal("0")).quantize(quantum, rounding=ROUND_HALF_UP)
    due_payable = grand_total - prepaid

    type_code = _resolve_type_code(invoice, ei)
    payee_iban = _clean(ei.get("payee_iban") or ei.get("iban"))
    # Only claim a credit transfer once there is an account to pay into, or the
    # document fails BR-61. An explicit code in the metadata still wins.
    payment_means_code = _clean(ei.get("payment_means_code")) or ("30" if payee_iban else "1")

    return EInvoice(
        profile=profile,
        invoice_number=str(invoice.get("invoice_number") or ""),
        issue_date=str(invoice.get("invoice_date") or ""),
        currency=currency,
        seller=_coerce_party(seller or ei.get("seller"), fallback_name=seller_fallback_name),
        buyer=_coerce_party(buyer or ei.get("buyer"), fallback_name=buyer_fallback_name),
        lines=lines,
        tax_subtotals=tax_subtotals,
        line_total=line_total,
        tax_basis_total=tax_basis_total,
        tax_total=tax_total,
        grand_total=grand_total,
        due_payable=due_payable,
        type_code=type_code,
        buyer_reference=(ei.get("buyer_reference") or ei.get("leitweg_id") or None),
        order_reference=(ei.get("order_reference") or None),
        due_date=(invoice.get("due_date") or None),
        payment_terms=(ei.get("payment_terms") or None),
        prepaid_amount=prepaid,
        note=(invoice.get("notes") or None),
        payment_means_code=payment_means_code,
        payee_iban=payee_iban,
        payee_account_name=_clean(ei.get("payee_account_name") or ei.get("account_holder")),
        payee_bic=_clean(ei.get("payee_bic") or ei.get("bic")),
        tax_currency=_clean(ei.get("tax_currency")),
        tax_total_in_tax_currency=(
            _dec(ei.get("tax_total_in_tax_currency")) if ei.get("tax_total_in_tax_currency") not in (None, "") else None
        ),
        vat_declared=vat_declared,
    )


def _en16931_profile(profile: str) -> Profile:
    """Look a profile up and refuse one the EN 16931 engine does not write.

    Every function below builds the EN 16931 model first. A profile outside
    that model handed to them would be validated against the wrong rules and
    written by the wrong writer, so it is refused here, by name, before any of
    that happens.

    Raises:
        EInvoiceError: the profile is unknown, or it is not EN 16931.
    """
    prof = get_profile(profile)
    if prof is None:
        raise EInvoiceError(f"unknown e-invoice profile {profile!r}")
    if prof.syntax == SYNTAX_UBL_TR:
        raise EInvoiceError(
            f"profile {profile!r} is UBL-TR, which is not an EN 16931 document; "
            "use render_tr_einvoice / tr_violations_for with the invoice's payment taxes"
        )
    if prof.syntax not in EN16931_SYNTAXES:
        raise EInvoiceError(f"profile {profile!r} has the syntax {prof.syntax!r}, which no writer here produces")
    return prof


def render_einvoice(
    *,
    invoice: dict[str, Any],
    line_items: list[dict[str, Any]],
    profile: str,
    seller: Party | dict | None = None,
    buyer: Party | dict | None = None,
    seller_fallback_name: str = "",
    buyer_fallback_name: str = "",
    defaults: dict[str, Any] | None = None,
    strict: bool = True,
) -> tuple[str, str, bytes]:
    """Return ``(filename, media_type, xml_bytes)`` for the invoice.

    ``direction`` unused for now; both payable and receivable render the same
    CII (party roles are already set by seller/buyer).
    """
    prof = _en16931_profile(profile)
    ei = build_einvoice(
        invoice=invoice,
        line_items=line_items,
        profile=profile,
        seller=seller,
        buyer=buyer,
        seller_fallback_name=seller_fallback_name,
        buyer_fallback_name=buyer_fallback_name,
        defaults=defaults,
    )
    xml = _write_en16931(ei, prof, strict=strict)
    safe_num = _safe_token(ei.invoice_number)
    filename = f"einvoice_{safe_num}_{profile}.xml"
    return filename, "application/xml", xml


def render_einvoice_pdf(
    *,
    invoice: dict[str, Any],
    line_items: list[dict[str, Any]],
    profile: str,
    seller: Party | dict | None = None,
    buyer: Party | dict | None = None,
    seller_fallback_name: str = "",
    buyer_fallback_name: str = "",
    defaults: dict[str, Any] | None = None,
    strict: bool = True,
    locale: str = "en",
) -> tuple[str, str, bytes]:
    """Return ``(filename, "application/pdf", pdf)`` for a Factur-X/ZUGFeRD hybrid.

    Only CII profiles (zugferd/facturx/xrechnung/en16931) can be embedded in a
    PDF; UBL/Peppol is XML-only, so callers should use :func:`render_einvoice`
    for those. ``locale`` selects the language of the readable page only; the
    embedded XML never varies with it.
    """
    from app.modules.einvoice.pdf_embed import build_facturx_pdf

    prof = _en16931_profile(profile)
    if prof.syntax != SYNTAX_CII:
        raise EInvoiceError(
            f"profile {profile!r} is UBL/XML-only; a hybrid PDF needs a CII profile "
            "(zugferd, facturx, xrechnung or en16931)"
        )
    ei = build_einvoice(
        invoice=invoice,
        line_items=line_items,
        profile=profile,
        seller=seller,
        buyer=buyer,
        seller_fallback_name=seller_fallback_name,
        buyer_fallback_name=buyer_fallback_name,
        defaults=defaults,
    )
    pdf = build_facturx_pdf(ei, strict=strict, locale=locale)
    safe_num = _safe_token(ei.invoice_number)
    filename = f"einvoice_{safe_num}_{profile}.pdf"
    return filename, "application/pdf", pdf


def violations_for(
    *,
    invoice: dict[str, Any],
    line_items: list[dict[str, Any]],
    profile: str,
    seller: Party | dict | None = None,
    buyer: Party | dict | None = None,
    seller_fallback_name: str = "",
    buyer_fallback_name: str = "",
    defaults: dict[str, Any] | None = None,
) -> list[RuleViolation]:
    """Validate without rendering, keeping each rule's id and severity.

    This is what a screen should call. ``problems_for`` flattens the same
    result to the fatal messages only, which cannot tell a reader that an
    invoice exports fine but ought to name a bank account.

    Raises:
        EInvoiceError: the profile is registered and is not an EN 16931
            profile. A UBL-TR invoice is checked by :func:`tr_violations_for`.
            A profile nobody registered is still reported as a finding by the
            rules, as it always was.
    """
    if get_profile(profile) is not None:
        _en16931_profile(profile)
    ei = build_einvoice(
        invoice=invoice,
        line_items=line_items,
        profile=profile,
        seller=seller,
        buyer=buyer,
        seller_fallback_name=seller_fallback_name,
        buyer_fallback_name=buyer_fallback_name,
        defaults=defaults,
    )
    return validate_rules(ei)


def problems_for(
    *,
    invoice: dict[str, Any],
    line_items: list[dict[str, Any]],
    profile: str,
    seller: Party | dict | None = None,
    buyer: Party | dict | None = None,
    seller_fallback_name: str = "",
    buyer_fallback_name: str = "",
    defaults: dict[str, Any] | None = None,
) -> list[str]:
    """Validate without rendering - the fatal messages that block a render."""
    found = violations_for(
        invoice=invoice,
        line_items=line_items,
        profile=profile,
        seller=seller,
        buyer=buyer,
        seller_fallback_name=seller_fallback_name,
        buyer_fallback_name=buyer_fallback_name,
        defaults=defaults,
    )
    return [v.message for v in found if v.severity == FATAL]


def _write_en16931(ei: EInvoice, prof: Profile, *, strict: bool) -> bytes:
    """Write the EN 16931 model in the syntax its profile names.

    Each syntax is named. A final ``else`` that fell through to one of the
    writers would hand it every syntax added later, and the file would come
    out well formed in the wrong format.

    Raises:
        EInvoiceError: the profile's syntax has no EN 16931 writer.
    """
    if prof.syntax == SYNTAX_UBL:
        return build_ubl_xml(ei, strict=strict)
    if prof.syntax == SYNTAX_CII:
        return build_cii_xml(ei, strict=strict)
    raise EInvoiceError(f"profile {prof.name!r} has the syntax {prof.syntax!r}, which no writer here produces")


# ── UBL-TR (e-Fatura / e-Arşiv Fatura) ───────────────────────────────────────
#
# A separate path on purpose. The Turkish document has its own model and its
# own rules, and it never passes through ``build_einvoice`` or the EN 16931
# rules above: BR-CO-14, BR-CO-15 and BR-CO-16 would refuse a correct
# withholding invoice. The caller supplies the taxes, one result of the shared
# payment tax calculation per group of lines; nothing here computes any.


def map_tr_einvoice(
    *,
    invoice_id: Any,
    invoice: Mapping[str, Any],
    line_items: Sequence[Mapping[str, Any]],
    seller: Mapping[str, Any],
    buyer: Mapping[str, Any],
    tr: Mapping[str, Any] | None,
    group_taxes: Sequence[TrGroupTaxes],
    payment: Mapping[str, Any] | None = None,
    extra_findings: Sequence[RuleViolation] = (),
    today: dt.date | None = None,
) -> tuple[TrMapping, list[RuleViolation]]:
    """Map an invoice onto UBL-TR and collect every finding about it.

    Args:
        invoice_id: the platform id of the invoice.
        invoice: the invoice header dict.
        line_items: the invoice lines, each with its VAT rate and withholding code.
        seller: the supplier party dict.
        buyer: the customer party dict.
        tr: the Turkish e-invoice fields of the invoice.
        group_taxes: the computed taxes of every line group.
        payment: optional settlement fields.
        extra_findings: findings the caller established before mapping, for
            example that the taxes are not confirmed. They are reported first.
        today: the day the issue date is judged against; defaults to the
            calendar day in Türkiye.

    Returns:
        The mapping and the full list of findings: the caller's, the
        mapper's, then those of :func:`~app.modules.einvoice.rules_tr.check_tr`.
    """
    from app.modules.einvoice.rules_tr import check_tr

    mapping = build_tr_invoice(
        invoice_id=invoice_id,
        invoice=invoice,
        line_items=line_items,
        seller=seller,
        buyer=buyer,
        tr=tr,
        group_taxes=group_taxes,
        payment=payment,
    )
    found = [*extra_findings, *mapping.findings]
    if mapping.invoice is not None:
        found += check_tr(mapping.invoice, today=today)
    return mapping, found


def tr_violations_for(**kwargs: Any) -> list[RuleViolation]:
    """Validate a UBL-TR invoice without rendering it. See :func:`map_tr_einvoice`."""
    return map_tr_einvoice(**kwargs)[1]


def render_tr_einvoice(**kwargs: Any) -> tuple[str, str, bytes, list[RuleViolation]]:
    """Return ``(filename, media_type, xml, findings)`` for an unsigned UBL-TR invoice.

    The file is what the customer's licensed integrator signs and submits.
    ``findings`` are the warnings and information findings that did not block
    it, for the caller to hand over with the file.

    Args:
        **kwargs: the arguments of :func:`map_tr_einvoice`.

    Raises:
        EInvoiceError: a fatal finding blocks the document. The message lists
            every one of them.
    """
    from app.modules.einvoice.ubl_tr import build_ubl_tr_xml

    mapping, found = map_tr_einvoice(**kwargs)
    fatal = [violation for violation in found if violation.severity == FATAL]
    if fatal or mapping.invoice is None:
        raise EInvoiceError("; ".join(str(violation) for violation in fatal) or "the invoice could not be mapped")
    # Checked above against the same day, so the writer is not asked to check
    # again against a day of its own.
    xml = build_ubl_tr_xml(mapping.invoice, strict=False)
    number = mapping.invoice.document_id or str(kwargs["invoice"].get("invoice_number") or "")
    filename = f"einvoice_{_safe_token(number)}_ubl_tr.xml"
    return filename, "application/xml", xml, found


def _safe_token(raw: str) -> str:
    """Single-line token for a Content-Disposition filename.

    Keeps the invoice number's real characters (umlauts included); the header
    site wraps the finished filename in
    :func:`app.core.content_disposition.attachment_disposition`, which derives
    the RFC 6266 ASCII fallback and UTF-8 ``filename*`` pair. Only the
    characters that would break the header or the filename are normalised
    here, exactly as before.
    """
    cleaned = (
        (raw or "invoice")
        .replace("\r", "")
        .replace("\n", "")
        .replace('"', "'")
        .replace("/", "-")
        .replace(" ", "_")
        .strip()
    )
    return cleaned[:80] or "invoice"
