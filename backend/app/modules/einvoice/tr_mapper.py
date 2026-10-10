# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Map plain invoice data onto a :class:`~app.modules.einvoice.ubl_tr.TrInvoice`.

The Turkish counterpart of ``service.build_einvoice``, and ORM-free for the
same reason: it takes the dicts the finance router already builds, so it is
testable without a database and this module keeps depending on nothing.

Three things are deliberately not done here.

**No tax arithmetic.** Every VAT figure arrives as a
:class:`~app.core.payment_taxes.PaymentTaxResult`, one per group of lines that
share a VAT rate and a withholding code. This module groups the lines, tells
the caller which groups exist (:func:`group_lines`), and adds the groups of one
document together. The per-line amounts it prints are the group figures split
by :func:`~app.core.payment_taxes.allocate`, so a column of lines adds up to
the group at its foot.

**No defaults that look like data.** A unit with no e-Fatura code is passed
through as entered, so TR-UNIT-01 names the line. A missing scenario stays
empty, so TR-PROFILE-01 asks for it. The document ID is taken from the
e-invoice fields and never derived from the platform's free-text invoice
number: it stays empty for the integrator to assign.

**No reading of free text.** The address is taken field by field. A single
unstructured address line becomes the street, and the district it may contain
is not guessed out of it.

The rounding consequence of grouping, stated once: each group's VAT is rounded
on its own, so the VAT of a two-rate invoice is the sum of two rounded figures
and can differ from a single rounding of the whole by one minor unit per extra
group. That is what the format requires (one ``TaxSubtotal`` per rate), and
the totals here are sums of the group figures, never a second calculation.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from app.core.currency_registry import CURRENCIES, money_quantum
from app.core.payment_taxes import Figure, PaymentTaxResult, allocate
from app.modules.einvoice.rules import FATAL, RuleViolation
from app.modules.einvoice.tr_words import amount_in_words
from app.modules.einvoice.ubl_tr import (
    CUSTOMIZATION_ID,
    TrAddress,
    TrContact,
    TrDocumentRef,
    TrInvoice,
    TrLine,
    TrParty,
    TrPaymentMeans,
    TrTaxGroup,
    TrTotals,
    figure_amount,
    has_withholding,
)

__all__ = [
    "TR_UUID_NAMESPACE",
    "TrGroupTaxes",
    "TrLineGroup",
    "TrMapping",
    "build_tr_invoice",
    "group_key",
    "group_lines",
    "normalise_tr_tax_number",
    "tr_invoice_uuid",
]

#: The namespace every invoice UUID (ETTN) is derived in. Fixed for the life of
#: the platform: the UUID of an invoice is ``uuid5`` of this and the invoice's
#: id, so exporting the same invoice twice writes the same ETTN and a GET stays
#: a read. Changing this value renumbers every document ever exported.
TR_UUID_NAMESPACE = uuid.UUID("6f1d0c52-7a3e-5b0e-9c41-2d8e4f6a1b70")

_HOME_COUNTRY = "TR"
_HOME_COUNTRY_NAME = "Türkiye"
_INVOICE_HOME = "on this invoice"

#: UN/EDIFACT 4461 credit transfer, written when the invoice names an account
#: to pay into and no payment means code of its own.
_CREDIT_TRANSFER = "30"


def tr_invoice_uuid(invoice_id: Any) -> str:
    """The ETTN of one platform invoice: stable, and derived without a write."""
    return str(uuid.uuid5(TR_UUID_NAMESPACE, str(invoice_id)))


def normalise_tr_tax_number(value: Any) -> str:
    """A VKN or TCKN as the format wants it: digits, no spaces, no ``TR`` prefix.

    Only what is certainly decoration is removed. Anything else is kept, so a
    foreign registration is refused by TR-PARTY-01 as what it is rather than
    arriving as a shorter number that happens to be all digits.
    """
    text = "".join(str(value or "").split()).upper()
    return text[2:] if text.startswith(_HOME_COUNTRY) else text


# ── plain values in ──────────────────────────────────────────────────────────


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _decimal(value: Any) -> Decimal | None:
    """Read a number, answering ``None`` for anything that is not one."""
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if value is None or isinstance(value, bool) or _text(value) == "":
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _date(value: Any) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    text = _text(value)
    if not text:
        return None
    try:
        return dt.date.fromisoformat(text[:10])
    except ValueError:
        return None


def _time(value: Any) -> dt.time | None:
    if isinstance(value, dt.time):
        return value
    text = _text(value)
    if not text:
        return None
    try:
        return dt.time.fromisoformat(text)
    except ValueError:
        return None


def _quantum(currency: str) -> Decimal:
    # An unknown currency is refused by TR-CUR-02. Two decimals here only
    # keeps the preview of such a document readable until it is.
    return money_quantum(currency) if currency in CURRENCIES else Decimal("0.01")


def _rate_label(rate: Decimal | None) -> str:
    if rate is None:
        return "?"
    text = f"{rate.normalize():f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def group_key(vat_rate_pct: Decimal | None, withholding_code: str) -> str:
    """The key of the group one line belongs to: its VAT rate and withholding code."""
    code = _text(withholding_code)
    return f"{_rate_label(vat_rate_pct)}|{code}" if code else _rate_label(vat_rate_pct)


# ── grouping ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TrLineGroup:
    """The lines of one invoice that share a VAT rate and a withholding code.

    Attributes:
        key: what :func:`group_key` answers for the pair.
        vat_rate_pct: the rate, ``None`` when a line states none and no
            default was supplied.
        withholding_code: the withholding code, empty when nothing is withheld.
        taxable_amount: the sum of the lines, each on the currency's quantum.
        line_indexes: positions of the lines in the list that was grouped.
    """

    key: str
    vat_rate_pct: Decimal | None
    withholding_code: str
    taxable_amount: Decimal
    line_indexes: tuple[int, ...]


@dataclass(frozen=True)
class TrGroupTaxes:
    """The computed taxes of one group, as the shared calculation returned them.

    Attributes:
        vat_rate_pct: the rate the calculation was given.
        withholding_code: the withholding code it was given, empty for none.
        taxes: its result, untouched.
        withholding_name: the category text of the rate row behind the
            withholding, printed as the scheme name of the withholding block.
    """

    vat_rate_pct: Decimal | None
    withholding_code: str
    taxes: PaymentTaxResult
    withholding_name: str = ""


def _line_amount(line: Mapping[str, Any], quantum: Decimal) -> Decimal:
    return (_decimal(line.get("amount")) or Decimal("0")).quantize(quantum, rounding=ROUND_HALF_UP)


def group_lines(line_items: Sequence[Mapping[str, Any]], currency: str) -> list[TrLineGroup]:
    """Group invoice lines by VAT rate and withholding code, in order of first appearance.

    This is the one place the grouping is decided. The caller computes the
    taxes of each group it is told about and hands them back to
    :func:`build_tr_invoice`, which groups the same lines the same way.

    Args:
        line_items: line dicts carrying ``amount``, ``vat_rate`` and
            ``withholding_code``.
        currency: the document currency, which decides the rounding quantum.

    Returns:
        One group per distinct pair. Each line amount is rounded half up to
        the quantum before it is added, so a group's taxable amount is the sum
        of the amounts the document prints.
    """
    quantum = _quantum(_text(currency).upper())
    order: list[str] = []
    found: dict[str, dict[str, Any]] = {}
    for index, line in enumerate(line_items):
        rate = _decimal(line.get("vat_rate"))
        code = _text(line.get("withholding_code"))
        key = group_key(rate, code)
        if key not in found:
            order.append(key)
            found[key] = {"rate": rate, "code": code, "amount": Decimal("0"), "lines": []}
        found[key]["amount"] += _line_amount(line, quantum)
        found[key]["lines"].append(index)
    return [
        TrLineGroup(
            key=key,
            vat_rate_pct=found[key]["rate"],
            withholding_code=found[key]["code"],
            taxable_amount=found[key]["amount"],
            line_indexes=tuple(found[key]["lines"]),
        )
        for key in order
    ]


# ── the mapping ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TrMapping:
    """What mapping one invoice produced.

    Attributes:
        invoice: the document, or ``None`` when it could not be assembled at
            all (the findings then say why).
        findings: what the mapping itself has to report, before
            :func:`~app.modules.einvoice.rules_tr.check_tr` is asked.
        inferred: fields nobody stated that followed from the data, by name.
            Shown to the user so a derived invoice type is never a surprise.
    """

    invoice: TrInvoice | None
    findings: list[RuleViolation] = field(default_factory=list)
    inferred: dict[str, str] = field(default_factory=dict)


def _finding(rule_id: str, message: str, term: str, **params: object) -> RuleViolation:
    return RuleViolation(rule_id, FATAL, message, term, {key: str(value) for key, value in params.items()})


def _held_taxes(reason_key: str) -> PaymentTaxResult:
    """Figures for a group nobody supplied taxes for: all held, so nothing is printed as zero."""

    def held(kind: str) -> Figure:
        return Figure(
            kind=kind,
            status="held",
            amount=None,
            base=None,
            rate_pct=None,
            numerator=None,
            denominator=None,
            code="",
            legal_reference="",
            effective_from=None,
            review_status="",
            overridden=False,
            reason_key=reason_key,
            reason_params={},
        )

    return PaymentTaxResult(
        vat_computed=held("vat_computed"),
        vat_withheld=held("vat_withheld"),
        vat_payable=held("vat_payable"),
        income_withheld=held("income_withheld"),
        stamp_duty=held("stamp_duty"),
    )


def _party(data: Mapping[str, Any]) -> TrParty:
    """One party from a plain dict. Nothing is filled in that the dict does not say."""
    tax_number = normalise_tr_tax_number(data.get("tax_number") or data.get("vat_id"))
    country_code = _text(data.get("country_code")).upper()
    country_name = _text(data.get("country_name")) or (_HOME_COUNTRY_NAME if country_code == _HOME_COUNTRY else "")
    address = TrAddress(
        district=_text(data.get("district")),
        city=_text(data.get("city")),
        country_name=country_name,
        street=_text(data.get("street") or data.get("line1")),
        building_number=_text(data.get("building_number")),
        postal_zone=_text(data.get("postcode")),
        country_code=country_code,
    )
    contact = TrContact(
        name=_text(data.get("contact_name")),
        telephone=_text(data.get("contact_phone")),
        email=_text(data.get("contact_email")),
    )
    return TrParty(
        tax_number=tax_number,
        address=address,
        name=_text(data.get("name")),
        first_name=_text(data.get("first_name")),
        family_name=_text(data.get("family_name")),
        tax_office=_text(data.get("tax_office")),
        contact=contact,
        website=_text(data.get("website")),
    )


def _shares(total: Decimal | None, weights: Sequence[Decimal], currency: str) -> list[Decimal] | None:
    """Split a group figure over its lines, or ``None`` when there is nothing to split."""
    if total is None:
        return None
    try:
        return allocate(total, list(weights), currency)
    except (TypeError, ValueError):
        # An unknown currency, or a figure with no line to carry it. The
        # document is then written without line level tax blocks, which the
        # schema allows, and the rules report the cause.
        return None


def build_tr_invoice(
    *,
    invoice_id: Any,
    invoice: Mapping[str, Any],
    line_items: Sequence[Mapping[str, Any]],
    seller: Mapping[str, Any],
    buyer: Mapping[str, Any],
    tr: Mapping[str, Any] | None,
    group_taxes: Sequence[TrGroupTaxes],
    payment: Mapping[str, Any] | None = None,
) -> TrMapping:
    """Assemble a :class:`TrInvoice` from finance invoice data and computed taxes.

    Args:
        invoice_id: the platform id of the invoice, which the ETTN derives from.
        invoice: ``invoice_number``, ``invoice_date``, ``due_date`` and
            ``currency_code``.
        line_items: per line ``description``, ``quantity``, ``unit``,
            ``unit_rate``, ``amount``, ``vat_rate`` (percent) and
            ``withholding_code``.
        seller: the supplier as a party dict (``name``, ``tax_number``,
            ``tax_office``, ``line1``, ``building_number``, ``district``,
            ``city``, ``postcode``, ``country_code``, contact fields; for a
            natural person ``first_name`` and ``family_name``).
        buyer: the customer, same shape.
        tr: the Turkish e-invoice fields of this invoice
            (``metadata.einvoice.tr``), already validated by the caller.
        group_taxes: the shared calculation's result for every group
            :func:`group_lines` reports.
        payment: optional ``payee_iban``, ``payment_means_code`` and
            ``payment_terms``.

    Returns:
        The document with the mapping's own findings. Run
        :func:`~app.modules.einvoice.rules_tr.check_tr` over the document for
        the rest.
    """
    fields = dict(tr or {})
    settle = dict(payment or {})
    findings: list[RuleViolation] = []
    inferred: dict[str, str] = {}
    currency = _text(invoice.get("currency_code")).upper()
    quantum = _quantum(currency)

    issue_date = _date(invoice.get("invoice_date"))
    if issue_date is None:
        findings.append(
            _finding(
                "OCE-TR-10",
                f"The invoice date {invoice.get('invoice_date')!r} cannot be read as a date, so no e-Fatura "
                f"can be built. Enter the date {_INVOICE_HOME}.",
                "IssueDate",
                invoice_date=_text(invoice.get("invoice_date")),
            )
        )
        return TrMapping(None, findings, inferred)

    # ── groups and their figures ─────────────────────────────────────────────
    supplied = {group_key(item.vat_rate_pct, item.withholding_code): item for item in group_taxes}
    line_groups = group_lines(line_items, currency)
    tax_groups: list[TrTaxGroup] = []
    by_key: dict[str, TrTaxGroup] = {}
    exemption_code = _text(fields.get("exemption_reason_code"))
    exemption_text = _text(fields.get("exemption_reason"))
    for found in line_groups:
        item = supplied.get(found.key)
        if found.vat_rate_pct is None:
            lines = ", ".join(str(index + 1) for index in found.line_indexes)
            findings.append(
                _finding(
                    "OCE-TR-11",
                    f"No VAT rate is known for line {lines}. Enter the rate on the line, or resolve why the "
                    "country's standard rate is not on file for the invoice date.",
                    f"TaxSubtotal[{found.key}]",
                    lines=lines,
                )
            )
        taxes = item.taxes if item is not None else _held_taxes("taxes_not_supplied")
        computed = figure_amount(taxes.vat_computed)
        # An exemption reason belongs to a group that charges no VAT. Writing
        # it onto a taxed group would claim an exemption the group does not use.
        exempt = computed is not None and computed == 0
        group = TrTaxGroup(
            key=found.key,
            vat_rate_pct=found.vat_rate_pct if found.vat_rate_pct is not None else Decimal("0"),
            taxable_amount=found.taxable_amount,
            taxes=taxes,
            withholding_code=found.withholding_code,
            withholding_name=item.withholding_name if item is not None else "",
            exemption_reason_code=exemption_code if exempt else "",
            exemption_reason=exemption_text if exempt else "",
        )
        tax_groups.append(group)
        by_key[found.key] = group

    # ── lines, each with its share of its group's figures ────────────────────
    amounts = [_line_amount(line, quantum) for line in line_items]
    line_computed: dict[int, Decimal] = {}
    line_withheld: dict[int, Decimal] = {}
    for found in line_groups:
        group = by_key[found.key]
        weights = [amounts[index] for index in found.line_indexes]
        computed_shares = _shares(figure_amount(group.taxes.vat_computed), weights, currency)
        payable_known = group.taxes.vat_payable.status == "value"
        if computed_shares is None or not payable_known:
            continue
        withheld_shares = None
        if has_withholding(group):
            withheld_shares = _shares(figure_amount(group.taxes.vat_withheld), weights, currency)
            if withheld_shares is None:
                continue
        for position, index in enumerate(found.line_indexes):
            line_computed[index] = computed_shares[position]
            if withheld_shares is not None:
                line_withheld[index] = withheld_shares[position]

    lines: list[TrLine] = []
    for index, line in enumerate(line_items):
        rate = _decimal(line.get("vat_rate"))
        key = group_key(rate, _text(line.get("withholding_code")))
        vat = line_computed.get(index)
        withheld = line_withheld.get(index)
        lines.append(
            TrLine(
                line_id=str(index + 1),
                name=_text(line.get("description")),
                quantity=_decimal(line.get("quantity")) or Decimal("0"),
                unit=_text(line.get("unit")),
                unit_price=_decimal(line.get("unit_rate")) or Decimal("0"),
                line_amount=amounts[index],
                tax_group=key,
                vat_amount=vat,
                vat_withheld=withheld,
                # The line's payable VAT is a subtraction of its two shares,
                # so the three close on every line as they do on the group.
                vat_payable=None if vat is None else vat - (withheld or Decimal("0")),
            )
        )

    # ── totals: sums of what is printed above, never a second calculation ────
    zero = Decimal("0").quantize(quantum)
    net = sum(amounts, zero)
    vat_total = zero
    withheld_total = zero
    for group in tax_groups:
        vat_total += figure_amount(group.taxes.vat_computed) or zero
        if has_withholding(group):
            withheld_total += figure_amount(group.taxes.vat_withheld) or zero
    totals = TrTotals(
        line_extension=net,
        tax_exclusive=net,
        tax_inclusive=net + vat_total,
        payable=net + vat_total - withheld_total,
    )

    # ── header ───────────────────────────────────────────────────────────────
    invoice_type = _text(fields.get("invoice_type")).upper()
    if not invoice_type:
        # Derived, not guessed: a document that withholds VAT is a TEVKIFAT
        # and one that does not is a sale. A return or an exemption invoice is
        # a decision and has to be stated.
        invoice_type = "TEVKIFAT" if any(has_withholding(group) for group in tax_groups) else "SATIS"
        inferred["invoice_type"] = invoice_type

    billing: tuple[TrDocumentRef, ...] = ()
    original = fields.get("original_invoice")
    if isinstance(original, Mapping) and _text(original.get("document_id")):
        original_date = _date(original.get("issue_date"))
        if original_date is None:
            findings.append(
                _finding(
                    "OCE-TR-12",
                    "The invoice this one returns is named without its date. Enter the issue date of the "
                    f"original invoice {_INVOICE_HOME}.",
                    "BillingReference/InvoiceDocumentReference/IssueDate",
                    reference=_text(original.get("document_id")),
                )
            )
        else:
            billing = (
                TrDocumentRef(
                    id=_text(original.get("document_id")),
                    issue_date=original_date,
                    document_type_code="IADE",
                ),
            )

    exchange_rate = _decimal(fields.get("exchange_rate"))
    exchange_rate_date = _date(fields.get("exchange_rate_date")) or (issue_date if exchange_rate is not None else None)

    notes: list[str] = []
    if fields.get("amount_in_words", True) and all(group.taxes.vat_payable.status == "value" for group in tax_groups):
        try:
            notes.append(amount_in_words(totals.payable, currency))
        except ValueError:
            # No Turkish name for this currency. The note is a courtesy line,
            # so the document goes out without it rather than with a guess.
            pass
    notes.extend(_text(note) for note in fields.get("notes") or () if _text(note))

    payee_iban = "".join(_text(settle.get("payee_iban")).split())
    means: tuple[TrPaymentMeans, ...] = ()
    due_date = _date(invoice.get("due_date"))
    if payee_iban:
        means = (
            TrPaymentMeans(
                code=_text(settle.get("payment_means_code")) or _CREDIT_TRANSFER,
                due_date=due_date,
                payee_iban=payee_iban,
                payee_currency=currency,
            ),
        )

    document = TrInvoice(
        profile_id=_text(fields.get("profile_id")).upper(),
        invoice_type=invoice_type,
        document_id=_text(fields.get("document_id")).upper(),
        uuid=tr_invoice_uuid(invoice_id),
        issue_date=issue_date,
        currency=currency,
        supplier=_party(seller),
        customer=_party(buyer),
        lines=lines,
        tax_groups=tax_groups,
        totals=totals,
        issue_time=_time(fields.get("issue_time")),
        exchange_rate=exchange_rate,
        exchange_rate_date=exchange_rate_date,
        notes=tuple(notes),
        billing_references=billing,
        payment_means=means,
        payment_terms_note=_text(settle.get("payment_terms")),
        payment_due_date=due_date,
        customization_id=_text(fields.get("customization_id")) or CUSTOMIZATION_ID,
        tax_total_convention=fields.get("tax_total_convention") or "net_of_withholding",
    )
    return TrMapping(document, findings, inferred)
