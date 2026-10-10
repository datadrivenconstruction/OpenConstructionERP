# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Assemble what the UBL-TR mapper needs from one stored invoice.

The mapper in ``einvoice.tr_mapper`` is pure and takes plain data. This module
is the part that reads: the invoice, its parties, its Turkish e-invoice fields
and, above all, its taxes.

**Where the taxes come from.** Never from here. An invoice raised from a
certified progress claim reads the statutory taxes stored for that claim
(source kind ``progress_claim``), so the VAT on the e-Fatura is the VAT the
payment certificate shows. Any other invoice reads the ones stored for the
invoice itself (source kind ``invoice``). Both are written and confirmed
through the payment taxes screen (``/tax-withholding/statutory``); nothing in
this module stores or confirms anything, so the export stays a read.

When nothing is stored the figures are previewed from the shared calculation
with no choice made, which holds the withholding, and the report says what to
do. When the stored figures are a draft the report says that instead. Either
way no file is written: an invoice goes to the revenue administration on
confirmed taxes or not at all.

**More than one VAT rate.** The store keeps one net amount and one rate per
document. An invoice whose lines fall into several groups (rate, withholding
code) therefore cannot print the stored figures as they are. Each group is
computed by the same shared calculation with the stored choices, and the
report carries a warning that says so. Two consequences are refused rather
than printed: an amount a person entered by hand has no group to belong to,
and a threshold the calculation judged on one group's amount was judged on
less than the document.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.payment_taxes import Choice, PaymentTaxResult
from app.modules.einvoice.rules import FATAL, WARNING, RuleViolation
from app.modules.einvoice.service import merge_einvoice_defaults
from app.modules.einvoice.tr_mapper import TrGroupTaxes, TrLineGroup, group_lines
from app.modules.finance.einvoice_tr_schemas import TR_BLOCK_KEY, TrEInvoiceFields
from app.modules.finance.models import Invoice

logger = logging.getLogger(__name__)

__all__ = [
    "SOURCE_KIND_CLAIM",
    "SOURCE_KIND_INVOICE",
    "TrExportInputs",
    "agreement_problems",
    "assemble_tr_export",
    "invoice_source",
    "read_tr_fields",
]

SOURCE_KIND_CLAIM = "progress_claim"
SOURCE_KIND_INVOICE = "invoice"

_TAXES_HOME = "Open the payment taxes of this document (Finance, Payment taxes)"
_NOT_APPLICABLE_ON_INVOICE = "not part of an invoice tax block"


@dataclass(frozen=True)
class TrExportInputs:
    """Everything ``einvoice.map_tr_einvoice`` is called with, plus what the screen is told.

    Attributes:
        mapper_kwargs: the keyword arguments of ``map_tr_einvoice``.
        tax_source: where the taxes were read from and in what state, as plain
            values for the dry-run response.
        fields: the Turkish e-invoice fields as stored, defaults filled in.
    """

    mapper_kwargs: dict[str, Any]
    tax_source: dict[str, Any] = field(default_factory=dict)
    fields: dict[str, Any] = field(default_factory=dict)


def _finding(rule_id: str, severity: str, message: str, term: str = "TaxTotal", **params: object) -> RuleViolation:
    return RuleViolation(rule_id, severity, message, term, {key: str(value) for key, value in params.items()})


def invoice_source(invoice: Invoice) -> tuple[str, uuid.UUID]:
    """The statutory tax source of one invoice: its claim when it has one, else itself."""
    if invoice.source_claim_id is not None:
        return SOURCE_KIND_CLAIM, invoice.source_claim_id
    return SOURCE_KIND_INVOICE, invoice.id


def read_tr_fields(metadata: Any) -> tuple[dict[str, Any], str]:
    """The stored Turkish fields of an invoice, and why they could not be read.

    Returns:
        The fields with their defaults, and an empty string. When the stored
        block does not validate, the defaults alone and the reason: a block
        written before a field was renamed must be reported, never crash the
        export.
    """
    einvoice = (metadata or {}).get("einvoice") if isinstance(metadata, Mapping) else None
    block = einvoice.get(TR_BLOCK_KEY) if isinstance(einvoice, Mapping) else None
    if block is None:
        return TrEInvoiceFields().model_dump(), ""
    try:
        return TrEInvoiceFields.model_validate(block).model_dump(), ""
    except Exception as exc:  # noqa: BLE001 - pydantic's error, or a block that is not an object
        return TrEInvoiceFields().model_dump(), str(exc)


def agreement_problems(
    *,
    invoice_net: Decimal,
    invoice_vat: Decimal,
    invoice_currency: str,
    taxes_net: Decimal | None,
    taxes_vat: Decimal | None,
    taxes_currency: str,
) -> list[str]:
    """How an invoice differs from the statutory taxes it is issued on.

    Pure, so the export and the validation rule
    ``finance.invoice_agrees_with_certificate`` give one answer.

    Args:
        invoice_net: the invoice amount before VAT.
        invoice_vat: the VAT the invoice carries.
        invoice_currency: the invoice currency.
        taxes_net: the amount the stored taxes were computed on.
        taxes_vat: the stored computed VAT, ``None`` while it is held.
        taxes_currency: the currency of the stored taxes.

    Returns:
        One sentence per difference; empty when they agree.
    """
    problems: list[str] = []
    mine, theirs = (invoice_currency or "").strip().upper(), (taxes_currency or "").strip().upper()
    if mine != theirs:
        problems.append(f"the invoice is in {mine or 'no currency'} and the taxes are in {theirs or 'no currency'}")
        return problems
    if taxes_net is not None and invoice_net != taxes_net:
        problems.append(f"the invoice amount before VAT is {invoice_net} and the taxes were computed on {taxes_net}")
    if taxes_vat is not None and invoice_vat != taxes_vat:
        problems.append(f"the invoice carries {invoice_vat} VAT and the taxes show {taxes_vat}")
    return problems


def _dec(value: Any) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except Exception:  # noqa: BLE001 - anything unreadable is simply not a number
        return None
    return parsed if parsed.is_finite() else None


def _line_dicts(
    invoice: Invoice, default_rate: Decimal | None, default_code: str, per_line: Mapping[str, str]
) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    for item in invoice.line_items or []:
        rate = _dec(item.vat_rate) if item.vat_rate is not None else default_rate
        key = str(item.id).lower()
        lines.append(
            {
                "description": item.description,
                "unit": item.unit,
                "quantity": item.quantity,
                "unit_rate": item.unit_rate,
                "amount": item.amount,
                "vat_rate": rate,
                "withholding_code": per_line.get(key, default_code),
            }
        )
    return lines


async def _project_country(session: AsyncSession, project_id: uuid.UUID) -> str:
    from app.modules.projects.models import Project

    country = (await session.execute(select(Project.country_code).where(Project.id == project_id))).scalar_one_or_none()
    return (country or "").strip().upper()


async def _standard_rate(session: AsyncSession, country: str, on_date: str) -> Decimal | None:
    """The country's standard VAT rate on a date, from the registry; ``None`` when it cannot say."""
    if not country:
        return None
    try:
        from app.modules.i18n_foundation.service import I18nFoundationService

        resolution = await I18nFoundationService(session).resolve_tax_rate(country, on_date=on_date[:10] or None)
    except Exception:  # noqa: BLE001 - a registry that cannot answer leaves the rate unknown
        logger.warning("standard VAT rate for %s could not be resolved", country, exc_info=True)
        return None
    if not resolution.resolved or resolution.combined_rate_pct is None:
        return None
    return _dec(resolution.combined_rate_pct)


async def _original_invoice(session: AsyncSession, invoice: Invoice, fields: dict[str, Any]) -> list[RuleViolation]:
    """Fill ``original_invoice`` from a platform invoice named by id. Mutates ``fields``."""
    wanted = str(fields.get("original_invoice_id") or "").strip()
    if not wanted or fields.get("original_invoice"):
        return []
    try:
        original = await session.get(Invoice, uuid.UUID(wanted))
    except ValueError:
        original = None
    if original is None or original.project_id != invoice.project_id:
        return [
            _finding(
                "OCE-TR-12",
                FATAL,
                "The invoice this one returns is not an invoice of this project. Choose the original invoice "
                "again, or enter its number and date on this invoice.",
                "BillingReference",
                original_invoice_id=wanted,
            )
        ]
    theirs, _reason = read_tr_fields(original.metadata_)
    fields["original_invoice"] = {
        "document_id": theirs.get("document_id") or "",
        "issue_date": (original.invoice_date or "")[:10],
    }
    if not theirs.get("document_id"):
        return [
            _finding(
                "OCE-TR-12",
                FATAL,
                f"The invoice this one returns ({original.invoice_number}) has no e-Fatura document number yet. "
                "Enter the number its integrator gave it on that invoice first.",
                "BillingReference/InvoiceDocumentReference/ID",
                original_invoice=str(original.invoice_number or ""),
            )
        ]
    return []


def _rate_rows(tax_service: Any, country: str) -> Sequence[Any]:
    """The statutory rate rows of a country: the ones that ship. A seam for tests."""
    return tax_service.shipped_rows(country) if country else ()


def _withholding_name(tax_service: Any, taxes: PaymentTaxResult, inputs: Any, rows: Sequence[Any]) -> str:
    """The Turkish category text of the row behind a withholding, empty when it cannot be found."""
    try:
        row = tax_service.row_behind(taxes.vat_withheld, inputs, rows)
    except Exception:  # noqa: BLE001 - the name is a label; the figures do not depend on it
        return ""
    labels = getattr(row, "labels", None) or {}
    return str(labels.get("tr") or labels.get("en") or "")


def _group_inputs(inputs: Any, group: TrLineGroup, stored_choice: Choice) -> Any:
    """The stored inputs narrowed to one group of lines.

    Income tax withholding and stamp duty are not part of an invoice's tax
    block, so they are switched off rather than computed once per group.
    """
    if group.withholding_code:
        withholding = Choice("selected", code=group.withholding_code)
    elif stored_choice.state == "selected":
        withholding = Choice("not_applicable", reason="no withholding on these lines")
    else:
        withholding = stored_choice
    return replace(
        inputs,
        net_amount=group.taxable_amount,
        vat_rate_pct=group.vat_rate_pct,
        vat_withholding=withholding,
        income_withholding=Choice("not_applicable", reason=_NOT_APPLICABLE_ON_INVOICE),
        stamp_duty=Choice("not_applicable", reason=_NOT_APPLICABLE_ON_INVOICE),
        stamp_duty_base=None,
        stamp_duty_base_same_as_net=False,
    )


def _compute_groups(
    tax_service: Any, inputs: Any, groups: Sequence[TrLineGroup], rows: Sequence[Any], stored_choice: Choice
) -> tuple[list[TrGroupTaxes], list[RuleViolation]]:
    """Run the shared calculation once per group. A refused group is left out, so it prints as held."""
    out: list[TrGroupTaxes] = []
    findings: list[RuleViolation] = []
    for group in groups:
        if group.vat_rate_pct is None:
            continue
        narrowed = _group_inputs(inputs, group, stored_choice)
        try:
            taxes = tax_service.compute_statutory(narrowed, rows)
        except tax_service.StatutoryRefusal as exc:
            findings.append(
                _finding(
                    "OCE-TR-28",
                    FATAL,
                    f"The taxes of the {group.key} lines could not be computed: {exc}",
                    f"TaxSubtotal[{group.key}]",
                    group=group.key,
                )
            )
            continue
        reasons = {figure.reason_key for figure in taxes.figures()}
        if "below_threshold" in reasons:
            findings.append(
                _finding(
                    "OCE-TR-26",
                    FATAL,
                    f"The withholding on the {group.key} lines was judged against a threshold on the amount of "
                    "those lines alone, and the threshold is set for the whole document. Issue the lines that "
                    "are subject to withholding as an invoice of their own.",
                    f"WithholdingTaxTotal[{group.key}]",
                    group=group.key,
                )
            )
        out.append(
            TrGroupTaxes(
                vat_rate_pct=group.vat_rate_pct,
                withholding_code=group.withholding_code,
                taxes=taxes,
                withholding_name=_withholding_name(tax_service, taxes, narrowed, rows),
            )
        )
    return out, findings


async def assemble_tr_export(
    session: AsyncSession,
    invoice: Invoice,
    *,
    defaults: Mapping[str, Any] | None,
) -> TrExportInputs:
    """Read everything a UBL-TR export of one invoice needs. Writes nothing.

    Args:
        session: an open database session.
        invoice: the invoice, with its line items loaded.
        defaults: the standing e-invoice configuration for this invoice, as
            ``einvoice_defaults_for_invoice`` returns it (seller from the
            settings, buyer from the linked contact).

    Returns:
        The mapper's arguments, with every finding this module established in
        ``extra_findings``, and the state of the tax source.
    """
    metadata = dict(invoice.metadata_ or {})
    merged = merge_einvoice_defaults(dict(metadata.get("einvoice") or {}), dict(defaults or {}))
    seller = dict(merged.get("seller") or {})
    buyer = dict(merged.get("buyer") or {})
    fields, unreadable = read_tr_fields(metadata)
    findings: list[RuleViolation] = []
    if unreadable:
        findings.append(
            _finding(
                "OCE-TR-20",
                FATAL,
                f"The Turkish e-invoice fields stored on this invoice cannot be read: {unreadable}. "
                "Open the e-Fatura fields of the invoice and save them again.",
                "metadata.einvoice.tr",
            )
        )
    if (invoice.invoice_direction or "") != "receivable":
        findings.append(
            _finding(
                "OCE-TR-29",
                FATAL,
                "This is a supplier invoice. An e-Fatura is issued by the seller, so only an invoice this "
                "company raises can be exported as one.",
                "AccountingSupplierParty",
            )
        )
    findings += await _original_invoice(session, invoice, fields)

    currency = (invoice.currency_code or "").strip().upper()
    invoice_date = (invoice.invoice_date or "")[:10]
    source_kind, source_id = invoice_source(invoice)
    country = await _project_country(session, invoice.project_id) or str(seller.get("country_code") or "").upper()
    tax_source: dict[str, Any] = {
        "source_kind": source_kind,
        "source_id": str(source_id),
        "project_id": str(invoice.project_id),
        "country_code": country,
        "currency_code": currency,
        "status": "module_absent",
    }
    per_line = dict(fields.get("line_withholding") or {})
    group_taxes: list[TrGroupTaxes] = []

    try:
        from app.modules.tax_withholding import service as tax_service
    except ImportError:
        tax_service = None  # type: ignore[assignment]

    if tax_service is None:
        findings.append(
            _finding(
                "OCE-TR-30",
                FATAL,
                "The payment taxes module is not installed, so the VAT of this invoice cannot be computed. "
                "Enable the tax withholding module.",
            )
        )
        lines = _line_dicts(invoice, None, "", per_line)
    else:
        stored = await tax_service.get_statutory(session, source_kind=source_kind, source_id=source_id)
        rows = _rate_rows(tax_service, country)
        if stored is None:
            tax_source["status"] = "not_stored"
            rate = await _standard_rate(session, country, invoice_date)
            lines = _line_dicts(invoice, rate, "", per_line)
            groups = group_lines(lines, currency)
            where = (
                "Confirm the taxes on the payment certificate this invoice was raised from."
                if source_kind == SOURCE_KIND_CLAIM
                else f"{_TAXES_HOME}, choose the withholding and confirm them."
            )
            findings.append(
                _finding(
                    "OCE-TR-21",
                    FATAL,
                    f"No taxes are stored for this invoice, so the figures shown are a preview. {where}",
                    source_kind=source_kind,
                )
            )
            tax_source["suggested_vat_rate_pct"] = None if rate is None else str(rate)
            date_value = _iso_date(invoice_date)
            if date_value is not None and currency:
                base = tax_service.StatutoryInputs(
                    country_code=country,
                    currency_code=currency,
                    document_date=date_value,
                    net_amount=Decimal("0"),
                    vat_rate_pct=rate,
                )
                group_taxes, more = _compute_groups(tax_service, base, groups, rows, Choice("unset"))
                findings += more
        else:
            calc, stored_lines = stored
            tax_source["status"] = calc.status
            try:
                inputs = tax_service.inputs_from_stored(calc, stored_lines)
                result = tax_service.result_from_lines(stored_lines)
                overrides = tax_service.overrides_from_stored(stored_lines)
            except tax_service.StatutoryDataError as exc:
                findings.append(
                    _finding(
                        "OCE-TR-31",
                        FATAL,
                        f"The taxes stored for this invoice cannot be read: {exc}. {_TAXES_HOME} and save them again.",
                    )
                )
                inputs = None
            if inputs is None:
                lines = _line_dicts(invoice, None, "", per_line)
            else:
                tax_source["net_amount"] = str(inputs.net_amount)
                tax_source["vat_rate_pct"] = None if inputs.vat_rate_pct is None else str(inputs.vat_rate_pct)
                stored_choice = inputs.vat_withholding
                default_code = stored_choice.code if stored_choice.state == "selected" else ""
                lines = _line_dicts(invoice, inputs.vat_rate_pct, default_code, per_line)
                groups = group_lines(lines, currency)
                if calc.status != "confirmed":
                    findings.append(
                        _finding(
                            "OCE-TR-22",
                            FATAL,
                            f"The taxes of this invoice are {calc.status}, not confirmed. {_TAXES_HOME} and "
                            "confirm them; an e-Fatura is only written on confirmed taxes.",
                            status=calc.status,
                        )
                    )
                net = sum((group.taxable_amount for group in groups), Decimal("0"))
                differences = agreement_problems(
                    invoice_net=net,
                    invoice_vat=_dec(invoice.tax_amount) or Decimal("0"),
                    invoice_currency=currency,
                    taxes_net=inputs.net_amount,
                    # A claim invoice carries the certificate's VAT whatever its lines say.
                    # Otherwise the stored figure is only comparable when it is the one printed.
                    taxes_vat=(
                        result.vat_computed.amount if source_kind == SOURCE_KIND_CLAIM or len(groups) == 1 else None
                    ),
                    taxes_currency=inputs.currency_code,
                )
                if differences:
                    claim = source_kind == SOURCE_KIND_CLAIM
                    findings.append(
                        _finding(
                            "OCE-TR-23" if claim else "OCE-TR-27",
                            FATAL,
                            (
                                "This invoice does not agree with the payment certificate it was raised from: "
                                if claim
                                else "This invoice and the taxes stored for it show different figures: "
                            )
                            + "; ".join(differences)
                            + (
                                ". Correct the invoice, or reopen the certificate's taxes and confirm them again."
                                if claim
                                # Either side can be the stale one. An invoice whose VAT was never
                                # entered is the usual case, and recomputing the taxes would not fix it.
                                else ". Set the invoice amounts to the figures of its taxes, or, if the invoice "
                                f"is right, {_TAXES_HOME[0].lower()}{_TAXES_HOME[1:]} and compute them again."
                            ),
                            differences=" | ".join(differences),
                        )
                    )
                single = (
                    len(groups) == 1
                    and groups[0].vat_rate_pct == inputs.vat_rate_pct
                    and groups[0].withholding_code == default_code
                )
                if single:
                    group_taxes = [
                        TrGroupTaxes(
                            vat_rate_pct=groups[0].vat_rate_pct,
                            withholding_code=default_code,
                            taxes=result,
                            withholding_name=_withholding_name(tax_service, result, inputs, rows),
                        )
                    ]
                elif groups:
                    if overrides:
                        findings.append(
                            _finding(
                                "OCE-TR-25",
                                FATAL,
                                "A tax amount of this invoice was entered by hand, and the invoice has lines "
                                "with different VAT rates or withholding. An amount entered for the whole "
                                "document cannot be divided between them. Clear the entered amount, or issue "
                                "the lines as separate invoices.",
                                kinds=", ".join(sorted(overrides)),
                            )
                        )
                    group_taxes, more = _compute_groups(tax_service, inputs, groups, rows, stored_choice)
                    findings += more
                    findings.append(
                        _finding(
                            "OCE-TR-24",
                            WARNING,
                            f"This invoice has {len(groups)} groups of lines with their own VAT rate or "
                            "withholding. Each group's VAT is computed and rounded on its own with the choices "
                            "confirmed for the document, so the total can differ from the confirmed single "
                            "figure by a rounding unit per group.",
                            groups=", ".join(group.key for group in groups),
                        )
                    )

    payment = {
        "payee_iban": merged.get("payee_iban"),
        "payment_means_code": merged.get("payment_means_code"),
        "payment_terms": merged.get("payment_terms"),
    }
    kwargs: dict[str, Any] = {
        "invoice_id": invoice.id,
        "invoice": {
            "invoice_number": invoice.invoice_number,
            "invoice_date": invoice.invoice_date,
            "due_date": invoice.due_date,
            "currency_code": currency,
        },
        "line_items": lines,
        "seller": seller,
        "buyer": buyer,
        "tr": fields,
        "group_taxes": group_taxes,
        "payment": payment,
        "extra_findings": findings,
    }
    return TrExportInputs(mapper_kwargs=kwargs, tax_source=tax_source, fields=fields)


def _iso_date(value: str) -> Any:
    import datetime as dt

    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None
