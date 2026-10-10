# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""One payment certificate (hakediş) from stored documents: assembled, saved, frozen.

:mod:`app.modules.contracts.hakedis` computes a certificate from an input and
knows nothing about where the input comes from. This file is the other half:
it takes a :class:`CertificateSource`, which an adapter builds from a progress
claim (the contracts service) or from a subcontractor's payment application
(the subcontractors service), and does everything the two have in common.

* It reads what a person entered for the manual lines, asks the certificate
  tax registry for the taxes, and computes the document.
* It notices that stored taxes no longer belong to the document: they were
  computed on an amount, and the amount has moved since. Such taxes are not
  printed; every tax line is held with the reason.
* It stores a manual line, and it has the taxes computed on the document's own
  bases, which a person never types.
* It freezes the document when it is certified, and from then on reads it back
  from the frozen rows and computes nothing.

The previous certificate's total (line D) is the previous document's frozen
total. It is never worked out again from the claims before it: what was
signed last month is what this month starts from. While the previous document
is not certified there is no such figure, and the line is held.

``subcontractors`` imports this file; this file never imports
``subcontractors``.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.payment_taxes import Choice, PaymentTaxResult, RateRow, categories, rows_for
from app.core.validation.engine import ValidationReport, validation_engine
from app.modules.contracts import certificate_taxes
from app.modules.contracts.hakedis import (
    Certificate,
    CertificateInput,
    CertificateParty,
    CertificateWorkLine,
    ManualLine,
    SummaryLine,
    WorkLineResult,
    compute_certificate,
    expected_tax_bases,
    header_columns,
    manual_lines_for,
    printed_summary,
    printed_works,
    reason_text,
)
from app.modules.contracts.hakedis_layout import (
    HAKEDIS_LABELS,
    LOCALES,
    HakedisSettings,
    SummaryLineDef,
    has_layout,
    label,
    label_parts,
    locale_languages,
    resolve_settings,
    tax_choice,
)
from app.modules.contracts.models import CertificateLine
from app.modules.contracts.repository import CertificateLineRepository

logger = logging.getLogger(__name__)

#: Source kinds, spelled as the statutory tax lines spell them.
SOURCE_PROGRESS_CLAIM = "progress_claim"
SOURCE_SUB_PAYMENT_APPLICATION = "sub_payment_application"

#: Reserved row keys. A layout line key cannot start with ``@``.
DOCUMENT_KEY = "@document"
OPTIONS_KEY = "@options"

#: Rule set the certificate is checked against before it may be certified.
HAKEDIS_RULE_SET = "hakedis"

#: Version of the frozen snapshot, so a later shape can still read this one.
SNAPSHOT_VERSION = 1

DEC_ZERO = Decimal("0")

#: ``resolver(session, country, subdivision, on)`` answers the VAT rate in
#: percent, or ``None`` when it cannot be resolved. A module attribute so a
#: test can state a synthetic rate; nothing here ever spells a rate.
VatRateSource = Callable[[AsyncSession, str, str | None, date], Awaitable[Decimal | None]]


async def _resolve_vat_rate(session: AsyncSession, country: str, subdivision: str | None, on: date) -> Decimal | None:
    """The VAT rate in force for the project on a date, from the tax rules.

    ``None`` whenever the rules do not answer: an unknown rate holds the VAT
    line, it is never replaced by a default.
    """
    try:
        from app.modules.i18n_foundation.service import I18nFoundationService  # noqa: PLC0415

        resolution = await I18nFoundationService(session).resolve_tax_rate(country, subdivision, on_date=on.isoformat())
    except Exception:  # noqa: BLE001 - an unresolved rate is reported on the document, not raised through it
        logger.warning("hakedis: VAT rate for %s on %s could not be resolved", country, on, exc_info=True)
        return None
    if not getattr(resolution, "resolved", False) or resolution.combined_rate_pct is None:
        return None
    try:
        return Decimal(str(resolution.combined_rate_pct))
    except (InvalidOperation, ValueError):
        return None


vat_rate_source: VatRateSource = _resolve_vat_rate

#: Where the tax categories offered on the screen come from. The shipped
#: rows; a test replaces it together with the tax module's own row source.
tax_rows: Callable[[str], Sequence[RateRow]] = rows_for


# ── What an adapter hands over ────────────────────────────────────────────


@dataclass(frozen=True)
class PriorDocument:
    """One document counted before this one, in billing order.

    ``settled`` says the document can no longer change in its own workflow
    (a certified claim, a finance-approved payment application). A prior
    document that is not settled has no final total yet.
    """

    source_id: uuid.UUID
    reference: str
    settled: bool


@dataclass(frozen=True)
class CertificateSource:
    """Everything about one stored document that the certificate needs.

    Built by an adapter; nothing here is computed from other fields.

    Attributes:
        kind: ``progress_claim`` or ``sub_payment_application``.
        source_id: Id of the document.
        project_id: The project it belongs to.
        reference: The number printed on it.
        status: Its status in its own workflow.
        editable: Whether manual lines and taxes may still change.
        settled: Whether it is certified, so a frozen copy must exist.
        country_code: The project's country.
        subdivision_code: The project's subdivision, for the VAT rate.
        currency: Currency of every amount.
        flavour: ``unit_price`` or ``lump_sum``.
        position: Its place in billing order, from 1.
        period_start: First day of the period, when stated.
        period_end: Last day of the period, when stated.
        tax_date: The date its taxes are looked up for, when stated.
        project_name: Name of the project.
        contract_number: Number of the contract.
        contract_title: Title of the contract.
        employer: The party that pays.
        contractor: The party that is paid.
        lines: The works list.
        retention_percent: The contract's retention percent.
        terms: The contract terms; only ``hakedis`` is read.
        direction: ``borne_by_us`` or ``withheld_by_us``.
        prior: The documents counted before this one, oldest first.
        contract_value: The contract sum with approved changes, when known.
        contract_start: First day of the contract, when stated.
        contract_end: Last day of the contract, when stated.
        stored_gross: The period gross the source document stores.
        stored_retention: The retention the source document holds this period.
    """

    kind: str
    source_id: uuid.UUID
    project_id: uuid.UUID
    reference: str
    status: str
    editable: bool
    settled: bool
    country_code: str
    subdivision_code: str | None
    currency: str
    flavour: str
    position: int
    period_start: date | None
    period_end: date | None
    tax_date: date | None
    project_name: str
    contract_number: str
    contract_title: str
    employer: CertificateParty
    contractor: CertificateParty
    lines: tuple[CertificateWorkLine, ...]
    retention_percent: Decimal | None
    terms: Mapping[str, Any]
    direction: str
    prior: tuple[PriorDocument, ...] = ()
    contract_value: Decimal | None = None
    contract_start: date | None = None
    contract_end: date | None = None
    stored_gross: Decimal | None = None
    stored_retention: Decimal | None = None


@dataclass(frozen=True)
class TaxView:
    """What the screen is told about the taxes of one document."""

    available: bool
    stored: bool
    status: str
    stale: bool
    expected_net_amount: Decimal | None
    expected_stamp_duty_base: Decimal | None
    vat_rate_pct: Decimal | None
    document_date: date | None
    direction: str
    choices: Mapping[str, Choice]
    buyer_is_designated: bool | None
    work_value_incl_vat: Decimal | None
    work_value_note: str


@dataclass(frozen=True)
class HakedisDocument:
    """A certificate ready to be shown or printed.

    ``frozen`` documents were read back from their frozen rows. ``carried_total``
    is the amount the next certificate takes as its line D.
    """

    source: CertificateSource
    cert: Certificate
    settings: HakedisSettings
    frozen: bool
    taxes: TaxView
    issue_date: date | None
    carried_total: Decimal | None
    previous_frozen: Mapping[str, Any] = field(default_factory=dict)
    manual: Mapping[str, ManualLine] = field(default_factory=dict)
    conditions: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    frozen_at: str = ""


# ── Small helpers ─────────────────────────────────────────────────────────


def _plain(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _dec(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _day(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def as_day(value: Any) -> date | None:
    """A stored date, in whichever of its two spellings, as a ``date``; ``None`` when unreadable."""
    return _day(value)


def first_language(locale: str) -> str:
    """The first language of a document locale: ``tr`` for ``tr`` and ``tr-en``, else ``en``.

    Raises:
        ValueError: ``locale`` is not one of the three.
    """
    return locale_languages(locale)[0]


def _address(value: Any) -> str:
    """An address stored as text or as an object, on one line."""
    if isinstance(value, str):
        return " ".join(value.split())
    if not isinstance(value, Mapping):
        return ""
    known = ("line1", "street", "address", "line2", "district", "postal_code", "zip", "city", "state", "country")
    parts = [str(value[name]).strip() for name in known if value.get(name) not in (None, "")]
    if not parts:
        parts = [str(item).strip() for item in value.values() if isinstance(item, str) and item.strip()]
    return ", ".join(part for part in parts if part)


def party_from_record(record: Any, *, fallback_name: str | None = None) -> CertificateParty:
    """A contact or a subcontractor row as the certificate header names a party.

    Read with ``getattr`` throughout: the two directories carry different
    columns, and the tax office is a column a directory may not have yet.
    """
    if record is None:
        return CertificateParty(name=fallback_name or "")
    name = (
        getattr(record, "legal_name", None)
        or getattr(record, "company_name", None)
        or getattr(record, "trade_name", None)
        or fallback_name
        or ""
    )
    return CertificateParty(
        name=str(name),
        tax_number=str(getattr(record, "vat_number", None) or getattr(record, "tax_id", None) or ""),
        tax_office=str(getattr(record, "tax_office", None) or ""),
        address=_address(getattr(record, "address", None)),
    )


def own_company_party() -> CertificateParty:
    """The company that runs this install, from its stored company profile.

    The profile carries one free line for its registration, which is where a
    tax number and office are written; it is printed as it stands.
    """
    try:
        from app.core.company_profile import read_company_profile  # noqa: PLC0415

        profile = read_company_profile()
    except Exception:  # noqa: BLE001 - an unreadable profile leaves the party unnamed, visibly
        logger.warning("hakedis: the company profile could not be read", exc_info=True)
        profile = {}
    return CertificateParty(
        name=str(profile.get("legal_name") or ""),
        tax_number=str(profile.get("registration_line") or ""),
        address=_address(profile.get("address")),
    )


def _refuse(code: int, error: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=code, detail={"error": error, "message": message, **extra})


def not_available() -> HTTPException:
    """The answer for a contract that has no certificate layout: an ordinary 404."""
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "error": "hakedis_not_available",
            "message": "The payment certificate is not available for this contract.",
        },
    )


def hakedis_available(country_code: str | None, terms: Mapping[str, Any] | None) -> bool:
    """Whether the certificate exists for a project country and a contract's terms."""
    return has_layout(country_code, terms)


def check_terms(country_code: str | None, terms: Mapping[str, Any] | None) -> None:
    """Refuse contract terms whose ``hakedis`` entry cannot be used.

    Only an entry that is present is checked: a contract that says nothing
    about the certificate takes its country's standard, and a contract in a
    country with no standard simply has no certificate.

    Raises:
        HTTPException: 400 ``invalid_contract_terms`` naming the key at fault.
    """
    if not isinstance(terms, Mapping) or "hakedis" not in terms:
        return
    try:
        resolve_settings(country_code, terms)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_contract_terms", "message": str(exc), "field": "terms.hakedis"},
        ) from exc


def settings_for(source: CertificateSource) -> HakedisSettings:
    """The contract's certificate configuration.

    Raises:
        HTTPException: 404 when there is no layout; 409 when the stored
            configuration cannot be used (it was valid when saved, or was
            written before it was checked).
    """
    if not has_layout(source.country_code, source.terms):
        raise not_available()
    try:
        return resolve_settings(source.country_code, source.terms)
    except ValueError as exc:
        raise _refuse(
            status.HTTP_409_CONFLICT,
            "hakedis_configuration_invalid",
            f"The contract's certificate configuration cannot be used: {exc}",
        ) from exc


def _previous_line(layout: Sequence[SummaryLineDef]) -> SummaryLineDef | None:
    """The layout line that prints the previous certificate's total."""
    for defn in layout:
        if defn.op == "input" and defn.operands and defn.operands[0] == "previous_certified_total":
            return defn
    return None


def _carried_total(cert: Certificate) -> Decimal | None:
    """The amount the next certificate starts from: line C.

    Line C is the line the previous-certificate line is subtracted from; a
    layout that names it ``total`` is the standard, and any other is found by
    looking for the difference that takes the previous total off.
    """
    previous = _previous_line(cert.inp.layout)
    if previous is None:
        return None
    for defn in cert.inp.layout:
        if defn.op == "difference" and len(defn.operands) >= 2 and previous.key in defn.operands[1:]:
            line = cert.line(defn.operands[0])
            return line.amount if line.status == "value" else None
    return None


def _manual_from_row(row: CertificateLine) -> ManualLine:
    return ManualLine(
        key=row.line_key,
        status=row.calc_status if row.calc_status in ("value", "not_applicable", "held") else "held",  # type: ignore[arg-type]
        amount=Decimal(str(row.amount)) if row.amount is not None else None,
        note=row.note or "",
        pct=Decimal(str(row.pct)) if row.pct is not None else None,
    )


def _conditions(
    country: str, taxes: PaymentTaxResult | None, layout: Sequence[SummaryLineDef], on: date | None
) -> dict:
    """The condition each computed tax line is subject to, per language."""
    found: dict[str, dict[str, str]] = {"tr": {}, "en": {}}
    if taxes is None:
        return found
    try:
        rows = tuple(tax_rows(country))
    except Exception:  # noqa: BLE001 - a condition is a remark; its absence must not stop the document
        return found
    for defn in layout:
        if defn.op != "tax":
            continue
        figure = getattr(taxes, defn.tax_kind, None)
        code = getattr(figure, "code", "")
        if not code or getattr(figure, "status", "") != "value":
            continue
        for row in rows:
            if row.code != code:
                continue
            if on is not None and (row.effective_from > on or (row.effective_to is not None and row.effective_to < on)):
                continue
            for language in found:
                if row.conditions.get(language):
                    found[language][defn.key] = str(row.conditions[language])
            break
    return found


# ── Building the live document ────────────────────────────────────────────


async def _options(repo: CertificateLineRepository, source: CertificateSource) -> dict[str, Any]:
    row = await repo.get_line(source.kind, source.source_id, OPTIONS_KEY, frozen=False)
    return dict(row.basis or {}) if row is not None else {}


async def _entered(repo: CertificateLineRepository, source: CertificateSource) -> dict[str, ManualLine]:
    rows = await repo.list_for_source(source.kind, source.source_id, frozen=False)
    return {row.line_key: _manual_from_row(row) for row in rows if not row.line_key.startswith("@")}


async def _previous_total(
    repo: CertificateLineRepository,
    source: CertificateSource,
    settings: HakedisSettings,
    entered: Mapping[str, ManualLine],
) -> tuple[Decimal | None, str, dict[str, str], dict[str, Any]]:
    """Line D: ``(amount, reason when held, its parameters, the previous frozen facts)``.

    * No document before this one: what a person stated as the opening total,
      or nothing.
    * The previous document is frozen: its frozen total, whatever anyone typed.
    * The previous document is settled but was certified before certificates
      were frozen: what a person states, held until they do.
    * The previous document is not settled yet: held, and nobody can type the
      figure in its place.
    """
    line = _previous_line(settings.layout)
    stated = entered.get(line.key) if line is not None else None
    stated_amount = stated.amount if stated is not None and stated.status == "value" else None
    if not source.prior:
        return (stated_amount if stated_amount is not None else DEC_ZERO), "", {}, {}
    last = source.prior[-1]
    frozen = await repo.get_line(source.kind, last.source_id, DOCUMENT_KEY, frozen=True)
    if frozen is not None:
        snapshot = dict(frozen.basis or {})
        facts = {
            "reference": last.reference,
            "total": _plain(Decimal(str(frozen.amount))) if frozen.amount is not None else None,
            "work_cumulative": snapshot.get("work_cumulative"),
        }
        if frozen.amount is None:
            return None, "previous_unknown", {}, facts
        return Decimal(str(frozen.amount)), "", {}, facts
    if last.settled:
        if stated_amount is not None:
            return stated_amount, "", {}, {}
        return None, "previous_unknown", {}, {}
    return None, "previous_not_certified", {"number": last.reference}, {}


def _stale_reason(
    state: certificate_taxes.CertificateTaxes,
    *,
    net: Decimal | None,
    stamp_base: Decimal | None,
    tax_date: date | None,
    vat_rate: Decimal | None,
) -> tuple[str, dict[str, str]] | None:
    """Why stored taxes no longer belong to the document, or ``None`` when they do."""
    if net is not None and state.net_amount is not None and state.net_amount != net:
        return "taxes_stale", {"stored": format(state.net_amount, "f"), "expected": format(net, "f")}
    stamp = state.choices.get("stamp_duty")
    if stamp is not None and stamp.state == "selected" and stamp_base is not None:
        stored = state.stamp_duty_base
        if stored is None and state.stamp_duty_base_same_as_net:
            stored = state.net_amount
        if stored is None:
            # Stored while the base was not known yet (the advance line was
            # still open). It is known now, so the set has to be worked out again.
            return "taxes_outdated", {}
        if stored != stamp_base:
            return "taxes_stale", {"stored": format(stored, "f"), "expected": format(stamp_base, "f")}
    if state.status == "draft":
        # A confirmed set is a person's signature under a date and a rate; it
        # is not reopened because a rate table moved. A draft is nobody's yet.
        if tax_date is not None and state.document_date is not None and state.document_date != tax_date:
            return "taxes_outdated", {}
        if state.vat_rate_pct != vat_rate:
            return "taxes_outdated", {}
    return None


def _certificate_number(source: CertificateSource) -> int:
    digits = "".join(ch for ch in source.reference if ch.isdigit())
    if digits and source.reference.strip().isdigit():
        return int(digits)
    return source.position


def _input(
    source: CertificateSource,
    settings: HakedisSettings,
    *,
    manual: Mapping[str, ManualLine],
    previous_total: Decimal | None,
    previous_reason: str,
    previous_params: Mapping[str, str],
    is_final: bool,
    taxes: PaymentTaxResult | None,
    tax_status: str,
    conditions: Mapping[str, str],
) -> CertificateInput:
    if source.period_end is None:
        raise _refuse(
            status.HTTP_409_CONFLICT,
            "hakedis_period_missing",
            "The document does not say when its period ends. State the period before opening the certificate.",
        )
    if settings.retention_source == "fixed":
        retention = settings.retention_pct
    elif settings.retention_source == "none":
        retention = None
    else:
        retention = source.retention_percent
    return CertificateInput(
        flavour=source.flavour,  # type: ignore[arg-type]
        certificate_number=_certificate_number(source),
        is_final=is_final,
        period_start=source.period_start or source.period_end,
        period_end=source.period_end,
        currency=source.currency,
        country_code=source.country_code,
        project_name=source.project_name,
        contract_number=source.contract_number,
        contract_title=source.contract_title,
        employer=source.employer,
        contractor=source.contractor,
        lines=source.lines,
        previous_certified_total=previous_total,
        manual_lines=manual,
        retention_pct=retention,
        taxes=taxes,
        layout=settings.layout,
        signature_roles=settings.signature_roles,
        tax_conditions=conditions,
        tax_status=tax_status,
        previous_held_reason=previous_reason or "previous_unknown",
        previous_held_params=previous_params,
    )


async def build_document(session: AsyncSession, source: CertificateSource, *, language: str = "tr") -> HakedisDocument:
    """The certificate of one stored document.

    A frozen document is read back as it was certified. Any other is computed
    now, from the document, what was entered for it, and its stored taxes.

    Args:
        session: The request's session.
        source: The document, from its adapter.
        language: ``tr`` or ``en``: the language a tax row's condition is
            printed in (it is printed once, in the document's first language).

    Raises:
        HTTPException: 404 when the contract has no certificate layout; 409
            when its configuration cannot be used, the document states no
            period end, or it is settled and no frozen copy exists.
    """
    repo = CertificateLineRepository(session)
    frozen = await repo.get_line(source.kind, source.source_id, DOCUMENT_KEY, frozen=True)
    if frozen is not None:
        return _from_snapshot(source, dict(frozen.basis or {}), frozen.amount, language)
    settings = settings_for(source)

    entered = await _entered(repo, source)
    manual = manual_lines_for(settings, {key: line for key, line in entered.items() if key in _manual_keys(settings)})
    options = await _options(repo, source)
    previous_total, previous_reason, previous_params, previous_frozen = await _previous_total(
        repo, source, settings, entered
    )

    def make(taxes: PaymentTaxResult | None, tax_status: str, conditions: Mapping[str, str]) -> CertificateInput:
        return _input(
            source,
            settings,
            manual=manual,
            previous_total=previous_total,
            previous_reason=previous_reason,
            previous_params=previous_params,
            is_final=bool(options.get("is_final")),
            taxes=taxes,
            tax_status=tax_status,
            conditions=conditions,
        )

    bases = expected_tax_bases(make(None, "", {}))
    net = bases.get("vat_computed", bases.get("income_withheld"))
    stamp_base = bases.get("stamp_duty")

    available = certificate_taxes.provider_registered()
    state = await certificate_taxes.collect_certificate_tax_state(session, source.kind, source.source_id)
    vat_rate: Decimal | None = None
    if available and source.tax_date is not None:
        vat_rate = await vat_rate_source(session, source.country_code, source.subdivision_code, source.tax_date)

    taxes: PaymentTaxResult | None
    tax_status = ""
    stale = False
    if not available:
        taxes = None
    elif state is None:
        taxes = certificate_taxes.held_result("taxes_not_stored")
    else:
        tax_status = state.status if state.status in ("draft", "confirmed") else ""
        outdated = _stale_reason(state, net=net, stamp_base=stamp_base, tax_date=source.tax_date, vat_rate=vat_rate)
        if outdated is not None:
            stale = True
            taxes = certificate_taxes.held_result(outdated[0], **outdated[1])
        else:
            taxes = state.result

    conditions = _conditions(source.country_code, None if stale else taxes, settings.layout, source.tax_date)
    cert = compute_certificate(make(taxes, tax_status, conditions.get(language) or {}))

    choices: dict[str, Choice] = {}
    for kind in certificate_taxes.TAX_CHOICE_KINDS:
        stored = state.choices.get(kind) if state is not None else None
        choices[kind] = stored if stored is not None else tax_choice(settings, kind)
    view = TaxView(
        available=available,
        stored=state is not None,
        status=tax_status,
        stale=stale,
        expected_net_amount=net,
        expected_stamp_duty_base=stamp_base,
        vat_rate_pct=vat_rate,
        document_date=source.tax_date,
        direction=source.direction,
        choices=MappingProxyType(choices),
        buyer_is_designated=state.buyer_is_designated if state is not None else None,
        work_value_incl_vat=state.work_value_incl_vat if state is not None else None,
        work_value_note=state.work_value_note if state is not None else "",
    )
    return HakedisDocument(
        source=source,
        cert=cert,
        settings=settings,
        frozen=False,
        taxes=view,
        issue_date=source.tax_date,
        carried_total=_carried_total(cert),
        previous_frozen=previous_frozen,
        manual=MappingProxyType(dict(entered)),
        conditions=conditions,
    )


def _manual_keys(settings: HakedisSettings) -> set[str]:
    return {defn.key for defn in settings.layout if defn.op == "manual"}


# ── Freezing and reading back ─────────────────────────────────────────────


def _party(party: CertificateParty) -> dict[str, str]:
    return {
        "name": party.name,
        "tax_number": party.tax_number,
        "tax_office": party.tax_office,
        "address": party.address,
    }


_WORK_INPUT_FIELDS = (
    "contract_quantity",
    "previous_quantity",
    "period_quantity",
    "unit_price",
    "contract_amount",
    "weight_pct",
    "previous_pct",
    "period_pct",
    "stated_previous_amount",
    "stated_period_amount",
)
_WORK_RESULT_FIELDS = (
    "previous_quantity",
    "period_quantity",
    "cumulative_quantity",
    "previous_pct",
    "period_pct",
    "cumulative_pct",
    "contract_amount",
    "previous_amount",
    "period_amount",
    "cumulative_amount",
    "over_by",
    "computed_cumulative_amount",
)


def snapshot_of(document: HakedisDocument, *, frozen_at: str) -> dict[str, Any]:
    """Everything a certified document is printed from, as plain JSON.

    The labels are stored too, the built-in table with the contract's own over
    it: a word changed in a later release must not change a signed document.
    """
    cert = document.cert
    inp = cert.inp
    settings = document.settings
    labels = {
        language: {**HAKEDIS_LABELS[language], **dict(settings.labels.get(language) or {})}
        for language in HAKEDIS_LABELS
    }
    view = document.taxes
    return {
        "version": SNAPSHOT_VERSION,
        "frozen_at": frozen_at,
        "issue_date": document.issue_date.isoformat() if document.issue_date else None,
        "work_cumulative": _plain(cert.totals.cumulative_amount),
        "input": {
            "flavour": inp.flavour,
            "certificate_number": inp.certificate_number,
            "is_final": inp.is_final,
            "period_start": inp.period_start.isoformat(),
            "period_end": inp.period_end.isoformat(),
            "currency": inp.currency,
            "country_code": inp.country_code,
            "project_name": inp.project_name,
            "contract_number": inp.contract_number,
            "contract_title": inp.contract_title,
            "employer": _party(inp.employer),
            "contractor": _party(inp.contractor),
            "previous_certified_total": _plain(inp.previous_certified_total),
            "retention_pct": _plain(inp.retention_pct),
            "tax_status": inp.tax_status,
            "signature_roles": list(inp.signature_roles),
            "manual_lines": {
                key: {"status": line.status, "amount": _plain(line.amount), "note": line.note, "pct": _plain(line.pct)}
                for key, line in inp.manual_lines.items()
            },
            "layout": [
                {
                    "key": defn.key,
                    "letter": defn.letter,
                    "op": defn.op,
                    "operands": list(defn.operands),
                    "sign": defn.sign,
                    "tax_kind": defn.tax_kind,
                    "section": defn.section,
                }
                for defn in inp.layout
            ],
        },
        "work_lines": [
            {
                "code": row.line.code,
                "description": row.line.description,
                "unit": row.line.unit,
                "section": row.line.section,
                "input": {name: _plain(getattr(row.line, name)) for name in _WORK_INPUT_FIELDS},
                "index": row.index,
                "status": row.status,
                "reason": row.reason,
                "over_measured": row.over_measured,
                "result": {name: _plain(getattr(row, name)) for name in _WORK_RESULT_FIELDS},
            }
            for row in cert.work_lines
        ],
        "summary": [
            {
                "key": line.key,
                "letter": line.letter,
                "status": line.status,
                "amount": _plain(line.amount),
                "basis": dict(line.basis),
                "section": line.section,
            }
            for line in cert.summary
        ],
        "settings": {
            "retention_source": settings.retention_source,
            "retention_pct": _plain(settings.retention_pct),
            "advance_recovery_pct": _plain(settings.advance_recovery_pct),
            "advance_amount": _plain(settings.advance_amount),
            "columns": {flavour: list(keys) for flavour, keys in settings.columns.items()},
            "labels": labels,
        },
        "conditions": {language: dict(by_key) for language, by_key in document.conditions.items()},
        "taxes": {
            "status": view.status,
            "expected_net_amount": _plain(view.expected_net_amount),
            "expected_stamp_duty_base": _plain(view.expected_stamp_duty_base),
            "vat_rate_pct": _plain(view.vat_rate_pct),
            "document_date": view.document_date.isoformat() if view.document_date else None,
            "direction": view.direction,
            "choices": {
                kind: {"state": choice.state, "code": choice.code, "reason": choice.reason}
                for kind, choice in view.choices.items()
            },
            "buyer_is_designated": view.buyer_is_designated,
            "work_value_incl_vat": _plain(view.work_value_incl_vat),
            "work_value_note": view.work_value_note,
        },
    }


def _from_snapshot(
    source: CertificateSource, snapshot: Mapping[str, Any], carried: Any, language: str
) -> HakedisDocument:
    """A certified document, rebuilt from its frozen row without computing anything."""
    raw = dict(snapshot.get("input") or {})
    layout = tuple(
        SummaryLineDef(
            key=str(item["key"]),
            letter=str(item.get("letter") or ""),
            op=item["op"],
            operands=tuple(str(key) for key in item.get("operands") or ()),
            sign=int(item.get("sign") or 1),
            tax_kind=str(item.get("tax_kind") or ""),
            section=str(item.get("section") or ""),
        )
        for item in raw.get("layout") or ()
    )
    conditions = {
        str(lang): {str(key): str(text) for key, text in dict(by_key or {}).items()}
        for lang, by_key in dict(snapshot.get("conditions") or {}).items()
    }
    chosen = conditions.get(language) or {}

    def party(value: Any) -> CertificateParty:
        data = dict(value or {})
        return CertificateParty(
            name=str(data.get("name") or ""),
            tax_number=str(data.get("tax_number") or ""),
            tax_office=str(data.get("tax_office") or ""),
            address=str(data.get("address") or ""),
        )

    work_inputs: list[CertificateWorkLine] = []
    work_results: list[WorkLineResult] = []
    for item in snapshot.get("work_lines") or ():
        given = dict(item.get("input") or {})
        line = CertificateWorkLine(
            code=str(item.get("code") or ""),
            description=str(item.get("description") or ""),
            unit=str(item.get("unit") or ""),
            section=str(item.get("section") or ""),
            **{name: _dec(given.get(name)) for name in _WORK_INPUT_FIELDS},
        )
        work_inputs.append(line)
        result = dict(item.get("result") or {})
        work_results.append(
            WorkLineResult(
                line=line,
                index=int(item.get("index") or len(work_results) + 1),
                status=item.get("status") or "value",
                reason=str(item.get("reason") or ""),
                over_measured=bool(item.get("over_measured")),
                **{name: _dec(result.get(name)) for name in _WORK_RESULT_FIELDS},
            )
        )

    summary: list[SummaryLine] = []
    for item in snapshot.get("summary") or ():
        basis = {str(name): str(value) for name, value in dict(item.get("basis") or {}).items()}
        key = str(item["key"])
        if "conditions" in basis or key in chosen:
            # The condition was frozen in both languages; the one printed
            # follows the language of this print.
            if key in chosen:
                basis["conditions"] = chosen[key]
        summary.append(
            SummaryLine(
                key=key,
                letter=str(item.get("letter") or ""),
                status=item.get("status") or "held",
                amount=_dec(item.get("amount")),
                basis=MappingProxyType(basis),
                section=str(item.get("section") or ""),
            )
        )

    manual = {
        str(key): ManualLine(
            key=str(key),
            status=dict(value).get("status") or "held",
            amount=_dec(dict(value).get("amount")),
            note=str(dict(value).get("note") or ""),
            pct=_dec(dict(value).get("pct")),
        )
        for key, value in dict(raw.get("manual_lines") or {}).items()
    }
    period_end = _day(raw.get("period_end")) or source.period_end or date.min
    inp = CertificateInput(
        flavour=raw.get("flavour") or source.flavour,
        certificate_number=int(raw.get("certificate_number") or source.position),
        is_final=bool(raw.get("is_final")),
        period_start=_day(raw.get("period_start")) or period_end,
        period_end=period_end,
        currency=str(raw.get("currency") or source.currency),
        country_code=str(raw.get("country_code") or source.country_code),
        project_name=str(raw.get("project_name") or ""),
        contract_number=str(raw.get("contract_number") or ""),
        contract_title=str(raw.get("contract_title") or ""),
        employer=party(raw.get("employer")),
        contractor=party(raw.get("contractor")),
        lines=tuple(work_inputs),
        previous_certified_total=_dec(raw.get("previous_certified_total")),
        manual_lines=MappingProxyType(manual),
        retention_pct=_dec(raw.get("retention_pct")),
        taxes=None,
        layout=layout,
        signature_roles=tuple(str(role) for role in raw.get("signature_roles") or ()),
        tax_conditions=chosen,
        tax_status=str(raw.get("tax_status") or ""),
    )
    by_key = {line.key: line for line in summary}
    cert = Certificate(inp=inp, work_lines=tuple(work_results), summary=tuple(summary), payable=by_key["payable"])

    stored = dict(snapshot.get("settings") or {})
    settings = HakedisSettings(
        layout=layout,
        retention_source=stored.get("retention_source") or "contract",
        retention_pct=_dec(stored.get("retention_pct")),
        advance_recovery_pct=_dec(stored.get("advance_recovery_pct")),
        advance_amount=_dec(stored.get("advance_amount")),
        signature_roles=inp.signature_roles,
        columns=MappingProxyType(
            {
                str(flavour): tuple(str(key) for key in keys)
                for flavour, keys in dict(stored.get("columns") or {}).items()
            }
        ),
        labels=MappingProxyType(
            {str(lang): dict(table or {}) for lang, table in dict(stored.get("labels") or {}).items()}
        ),
    )
    taxes = dict(snapshot.get("taxes") or {})
    view = TaxView(
        available=True,
        stored=True,
        status=str(taxes.get("status") or ""),
        stale=False,
        expected_net_amount=_dec(taxes.get("expected_net_amount")),
        expected_stamp_duty_base=_dec(taxes.get("expected_stamp_duty_base")),
        vat_rate_pct=_dec(taxes.get("vat_rate_pct")),
        document_date=_day(taxes.get("document_date")),
        direction=str(taxes.get("direction") or source.direction),
        choices=MappingProxyType(
            {
                str(kind): Choice(
                    dict(value).get("state") or "unset",
                    str(dict(value).get("code") or ""),
                    str(dict(value).get("reason") or ""),
                )
                for kind, value in dict(taxes.get("choices") or {}).items()
            }
        ),
        buyer_is_designated=taxes.get("buyer_is_designated"),
        work_value_incl_vat=_dec(taxes.get("work_value_incl_vat")),
        work_value_note=str(taxes.get("work_value_note") or ""),
    )
    return HakedisDocument(
        source=source,
        cert=cert,
        settings=settings,
        frozen=True,
        taxes=view,
        issue_date=_day(snapshot.get("issue_date")),
        carried_total=Decimal(str(carried)) if carried is not None else None,
        manual=MappingProxyType(manual),
        conditions=conditions,
        frozen_at=str(snapshot.get("frozen_at") or ""),
    )


async def freeze_document(
    session: AsyncSession,
    source: CertificateSource,
    *,
    user_id: str | None,
    document: HakedisDocument | None = None,
) -> bool:
    """Store the certified document so it is never computed again.

    Idempotent: a document that already has its frozen rows is left exactly as
    it is, and ``False`` is returned.

    The caller has already run :func:`enforce_ready` and may hand over the
    document it returned; nothing is checked here.
    """
    repo = CertificateLineRepository(session)
    if await repo.get_line(source.kind, source.source_id, DOCUMENT_KEY, frozen=True) is not None:
        return False
    if document is None or document.frozen:
        document = await build_document(session, source)
    by = _user(user_id)
    snapshot = snapshot_of(document, frozen_at=datetime.now(UTC).isoformat())
    session.add(
        CertificateLine(
            source_kind=source.kind,
            source_id=source.source_id,
            line_key=DOCUMENT_KEY,
            calc_status="value" if document.carried_total is not None else "held",
            amount=document.carried_total,
            basis=snapshot,
            frozen=True,
            entered_by=by,
        )
    )
    for line in document.cert.summary:
        session.add(
            CertificateLine(
                source_kind=source.kind,
                source_id=source.source_id,
                line_key=line.key,
                calc_status=line.status,
                amount=line.amount,
                basis=dict(line.basis),
                note=str(line.basis.get("note") or ""),
                frozen=True,
                entered_by=by,
            )
        )
    await session.flush()
    return True


def _user(user_id: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(user_id)) if user_id else None
    except ValueError:
        return None


# ── What a person changes ─────────────────────────────────────────────────


def _require_editable(source: CertificateSource) -> None:
    if not source.editable:
        raise _refuse(
            status.HTTP_409_CONFLICT,
            "hakedis_not_editable",
            f"The document is {source.status!r}; its certificate can no longer change.",
            document_status=source.status,
        )


async def save_line(
    session: AsyncSession,
    source: CertificateSource,
    line_key: str,
    *,
    state: str,
    amount: Decimal | None,
    pct: Decimal | None,
    note: str,
    user_id: str | None,
) -> None:
    """Store, or clear, what a person entered for one line.

    ``state`` is ``value`` (with an amount, or a percent of the line's base),
    ``not_applicable`` (with the reason as its note) or ``unset`` (the entry
    is removed and the line is held again).

    Raises:
        HTTPException: 404 for a line the layout does not have; 409 when the
            document can no longer change, or the line is not one a person
            enters; 422 when the entry is incomplete.
    """
    _require_editable(source)
    settings = settings_for(source)
    repo = CertificateLineRepository(session)
    if await repo.get_line(source.kind, source.source_id, DOCUMENT_KEY, frozen=True) is not None:
        raise _refuse(status.HTTP_409_CONFLICT, "hakedis_not_editable", "The certificate is certified and frozen.")
    by_key = {defn.key: defn for defn in settings.layout}
    defn = by_key.get(line_key)
    if defn is None:
        raise _refuse(status.HTTP_404_NOT_FOUND, "hakedis_line_unknown", f"The certificate has no line {line_key!r}.")
    previous = _previous_line(settings.layout)
    if previous is not None and defn.key == previous.key:
        await _require_opening_total_allowed(repo, source)
        if state == "not_applicable" or pct is not None:
            raise _refuse(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "hakedis_line_entry_invalid",
                "The previous certificates' total is an amount.",
            )
    elif defn.op != "manual":
        raise _refuse(
            status.HTTP_409_CONFLICT,
            "hakedis_line_not_manual",
            f"Line {line_key!r} is computed and cannot be entered.",
        )
    existing = await repo.get_line(source.kind, source.source_id, line_key, frozen=False)
    if state == "unset":
        if existing is not None:
            await session.delete(existing)
            await session.flush()
        return
    if state == "value":
        if amount is None and pct is None:
            raise _refuse(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "hakedis_line_entry_invalid",
                "Enter an amount, or a percent of the line's base.",
            )
        if amount is not None and pct is not None:
            raise _refuse(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "hakedis_line_entry_invalid",
                "Enter an amount or a percent, not both.",
            )
        if pct is not None and not defn.operands:
            raise _refuse(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "hakedis_line_entry_invalid",
                f"Line {line_key!r} has no base a percent could be taken of.",
            )
        if amount is not None and amount < 0 and defn.sign < 0:
            raise _refuse(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "hakedis_line_entry_invalid",
                "A deduction is entered as a positive amount.",
            )
    elif state == "not_applicable":
        if not note.strip():
            raise _refuse(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "hakedis_line_entry_invalid",
                "Say why the line does not apply.",
            )
        amount, pct = None, None
    else:
        raise _refuse(status.HTTP_422_UNPROCESSABLE_CONTENT, "hakedis_line_entry_invalid", f"Unknown state {state!r}.")
    if existing is None:
        session.add(
            CertificateLine(
                source_kind=source.kind,
                source_id=source.source_id,
                line_key=line_key,
                calc_status=state,
                amount=amount,
                pct=pct,
                note=note,
                basis={},
                frozen=False,
                entered_by=_user(user_id),
            )
        )
    else:
        existing.calc_status = state
        existing.amount = amount
        existing.pct = pct
        existing.note = note
        existing.entered_by = _user(user_id)
    await session.flush()


async def _require_opening_total_allowed(repo: CertificateLineRepository, source: CertificateSource) -> None:
    """A person may state line D only where no frozen figure exists or is coming."""
    if not source.prior:
        return
    last = source.prior[-1]
    if await repo.get_line(source.kind, last.source_id, DOCUMENT_KEY, frozen=True) is not None:
        raise _refuse(
            status.HTTP_409_CONFLICT,
            "hakedis_previous_is_certified",
            f"The previous certificate ({last.reference}) is certified; its total is taken from it.",
        )
    if not last.settled:
        raise _refuse(
            status.HTTP_409_CONFLICT,
            "hakedis_previous_not_certified",
            f"The previous certificate ({last.reference}) is not certified yet; certify it first.",
        )


async def save_options(
    session: AsyncSession, source: CertificateSource, *, is_final: bool, user_id: str | None
) -> None:
    """Store whether this is the final certificate. Never inferred from anything."""
    _require_editable(source)
    settings_for(source)
    repo = CertificateLineRepository(session)
    row = await repo.get_line(source.kind, source.source_id, OPTIONS_KEY, frozen=False)
    if row is None:
        session.add(
            CertificateLine(
                source_kind=source.kind,
                source_id=source.source_id,
                line_key=OPTIONS_KEY,
                calc_status="value",
                basis={"is_final": bool(is_final)},
                frozen=False,
                entered_by=_user(user_id),
            )
        )
    else:
        row.basis = {**dict(row.basis or {}), "is_final": bool(is_final)}
        row.entered_by = _user(user_id)
    await session.flush()


async def save_taxes(
    session: AsyncSession,
    source: CertificateSource,
    *,
    choices: Mapping[str, Choice | None],
    buyer_facts: Mapping[str, Any],
    user_id: str,
) -> None:
    """Have the document's taxes computed on its own bases and stored as a draft.

    The amount before VAT and the stamp duty base are the certificate's; the
    VAT rate comes from the tax rules for the document's date. A person sends
    only the choices and the facts about the buyer, and whatever they leave
    out keeps its stored value: sending nothing recalculates on the current
    amounts.

    Raises:
        HTTPException: 409 when the document can no longer change, states no
            date, or its amount before VAT is not known yet; 503 when no tax
            module is installed; and whatever the tax module refuses, with its
            own status and code.
    """
    _require_editable(source)
    document = await build_document(session, source)
    if document.frozen:
        raise _refuse(status.HTTP_409_CONFLICT, "hakedis_not_editable", "The certificate is certified and frozen.")
    view = document.taxes
    if source.tax_date is None:
        raise _refuse(
            status.HTTP_409_CONFLICT,
            "hakedis_date_missing",
            "The document has no date its taxes could be looked up for. State its date first.",
        )
    if view.expected_net_amount is None:
        raise _refuse(
            status.HTTP_409_CONFLICT,
            "hakedis_base_held",
            "The amount of this certificate is not known yet, so its taxes cannot be computed. "
            "Complete the lines above the taxes first.",
        )
    merged = {
        kind: (choices.get(kind) or view.choices.get(kind) or Choice("unset"))
        for kind in certificate_taxes.TAX_CHOICE_KINDS
    }
    request = certificate_taxes.CertificateTaxRequest(
        project_id=source.project_id,
        source_kind=source.kind,
        source_id=source.source_id,
        source_reference=source.reference,
        direction=source.direction,
        country_code=source.country_code,
        currency=source.currency,
        document_date=source.tax_date,
        net_amount=view.expected_net_amount,
        stamp_duty_base=view.expected_stamp_duty_base,
        vat_rate_pct=view.vat_rate_pct,
        user_id=user_id,
        choices=merged,
        buyer_is_designated=buyer_facts.get("buyer_is_designated", view.buyer_is_designated),
        work_value_incl_vat=buyer_facts.get("work_value_incl_vat", view.work_value_incl_vat),
        work_value_note=buyer_facts.get("work_value_note", view.work_value_note) or "",
    )
    try:
        await certificate_taxes.save_certificate_taxes(session, request)
    except certificate_taxes.CertificateTaxesUnavailableError as exc:
        raise _refuse(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "hakedis_taxes_unavailable",
            "The tax calculation module is not installed.",
        ) from exc
    except certificate_taxes.CertificateTaxRefusalError as refusal:
        raise HTTPException(
            status_code=refusal.http_status,
            detail={"error": refusal.code, "message": refusal.message, "details": refusal.details},
        ) from refusal


# ── Rules and the certification gate ──────────────────────────────────────


async def rule_context(session: AsyncSession, document: HakedisDocument) -> dict[str, Any]:
    """The plain dict the ``hakedis`` rules read. Amounts are strings."""
    source = document.source
    cert = document.cert
    settings = document.settings
    repo = CertificateLineRepository(session)
    recovered_before = DEC_ZERO
    if source.prior:
        frozen = await repo.frozen_lines_for_sources(
            source.kind, [prior.source_id for prior in source.prior], "advance_recovery"
        )
        for row in frozen.values():
            if row.calc_status == "value" and row.amount is not None:
                recovered_before += Decimal(str(row.amount))
    previous = _previous_line(settings.layout)
    return {
        "currency": source.currency,
        "country_code": source.country_code,
        "document": {
            "kind": source.kind,
            "id": str(source.source_id),
            "reference": source.reference,
            "flavour": cert.inp.flavour,
            "is_final": cert.inp.is_final,
            "stored_gross": _plain(source.stored_gross),
            "stored_retention": _plain(source.stored_retention),
        },
        "contract": {
            "value": _plain(source.contract_value),
            "start": source.contract_start.isoformat() if source.contract_start else None,
            "end": source.contract_end.isoformat() if source.contract_end else None,
            "advance_amount": _plain(settings.advance_amount),
        },
        "previous": {
            "line_key": previous.key if previous is not None else "",
            "exists": bool(source.prior),
            "reference": source.prior[-1].reference if source.prior else "",
            "frozen_total": document.previous_frozen.get("total"),
            "frozen_work_cumulative": document.previous_frozen.get("work_cumulative"),
            "advance_recovered": _plain(recovered_before),
        },
        "work": {
            "previous_total": _plain(cert.totals.previous_amount),
            "period_total": _plain(cert.totals.period_amount),
            "cumulative_total": _plain(cert.totals.cumulative_amount),
            "lines": [
                {
                    "index": row.index,
                    "code": row.code,
                    "description": row.description,
                    "status": row.status,
                    "weight_pct": _plain(row.weight_pct),
                    "period_quantity": _plain(row.period_quantity),
                    "period_pct": _plain(row.period_pct),
                    "period_amount": _plain(row.period_amount),
                    "cumulative_amount": _plain(row.cumulative_amount),
                    "computed_cumulative_amount": _plain(row.computed_cumulative_amount),
                    "over_measured": row.over_measured,
                }
                for row in cert.work_lines
            ],
        },
        "summary": [
            {
                "key": line.key,
                "letter": line.letter,
                "status": line.status,
                "amount": _plain(line.amount),
                "reason": line.basis.get("reason", "") if line.status == "held" else "",
                "base": line.basis.get("base"),
                "rate_pct": line.basis.get("rate_pct"),
                "labels": {
                    language: label(f"line.{line.key}", language, settings.labels) for language in HAKEDIS_LABELS
                },
                "reason_texts": _reason_texts(line, cert, settings),
            }
            for line in cert.summary
        ],
        "tax_lines": [defn.key for defn in settings.layout if defn.op == "tax"],
        "taxes": {
            "available": document.taxes.available,
            "stored": document.taxes.stored,
            "status": document.taxes.status,
            "stale": document.taxes.stale,
            "income_withholding": document.taxes.choices.get("income_withholding", Choice("unset")).state,
        },
    }


def _reason_texts(line: SummaryLine, cert: Certificate, settings: HakedisSettings) -> dict[str, str]:
    """Why a held line is held, as a sentence per language; empty for any other line."""
    if line.status != "held":
        return {}
    prefix = "reason."
    params = {name[len(prefix) :]: value for name, value in line.basis.items() if name.startswith(prefix)}
    reason = line.basis.get("reason", "")
    return {language: reason_text(reason, params, cert, language, settings) for language in HAKEDIS_LABELS}


async def run_rules(session: AsyncSession, document: HakedisDocument, *, locale: str) -> ValidationReport:
    """Run the ``hakedis`` rule set against one document."""
    return await validation_engine.validate(
        data=await rule_context(session, document),
        rule_sets=[HAKEDIS_RULE_SET],
        target_type=document.source.kind,
        target_id=str(document.source.source_id),
        project_id=str(document.source.project_id),
        metadata={"locale": locale, "workflow": "hakedis_certification"},
    )


def findings_payload(report: ValidationReport) -> list[dict[str, Any]]:
    """The findings of a report that did not pass, as the screen lists them."""
    return [
        {
            "rule_id": result.rule_id,
            "rule_name": result.rule_name,
            "severity": result.severity.value,
            "message": result.message,
            "element_ref": result.element_ref,
            "suggestion": result.suggestion,
            "details": result.details,
            "engine_error": bool(result.is_engine_error),
        }
        for result in report.results
        if not result.passed
    ]


async def enforce_ready(session: AsyncSession, source: CertificateSource, *, locale: str) -> HakedisDocument:
    """Refuse to certify a document whose certificate is not complete.

    A document with no certificate layout is none of this gate's business and
    is not passed to it. A frozen document passes: it was checked when it was
    frozen.

    Raises:
        HTTPException: 422 ``hakedis_not_ready`` listing the findings; 503
            when the rule set is not registered, because a set that checks
            nothing must not read as a pass on a document that moves money.
    """
    document = await build_document(session, source)
    if document.frozen:
        return document
    report = await run_rules(session, document, locale=locale)
    if HAKEDIS_RULE_SET in report.unsupported_rule_sets:
        logger.error("contracts: rule set %s is not registered; the certificate gate cannot run", HAKEDIS_RULE_SET)
        raise _refuse(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "hakedis_rules_unavailable",
            "The certificate checks are not available, so the document cannot be certified.",
        )
    blocking = [*report.errors, *report.engine_errors]
    if not blocking:
        return document
    heads = "; ".join(result.message for result in blocking[:3])
    if len(blocking) > 3:
        heads = f"{heads} (+{len(blocking) - 3})"
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={
            "error": "hakedis_not_ready",
            "message": f"The payment certificate is not complete: {heads}",
            "findings": findings_payload(report),
        },
    )


# ── The screen's view ─────────────────────────────────────────────────────


def _category(row: RateRow, language: str) -> dict[str, Any]:
    return {
        "code": row.code,
        "label": row.labels.get(language) or row.labels.get("en") or row.code,
        "rate_pct": _plain(row.rate_pct),
        "numerator": row.numerator,
        "denominator": row.denominator,
        "legal_reference": row.legal_reference,
        "review_status": row.review_status,
        "conditions": row.conditions.get(language) or row.conditions.get("en") or "",
        "buyer_scope": row.buyer_scope,
    }


def tax_categories(country: str, on: date | None, language: str) -> dict[str, list[dict[str, Any]]]:
    """The categories a person may choose per tax, in force on the document's date."""
    offered: dict[str, list[dict[str, Any]]] = {kind: [] for kind in certificate_taxes.TAX_CHOICE_KINDS}
    if on is None:
        return offered
    try:
        rows = tuple(tax_rows(country))
    except Exception:  # noqa: BLE001 - an empty picker is shown; the screen still opens
        logger.exception("hakedis: tax categories for %s could not be read", country)
        return offered
    for kind in offered:
        offered[kind] = [_category(row, language) for row in categories(rows, country=country, kind=kind, on=on)]
    return offered


def document_payload(
    document: HakedisDocument, *, locale: str, report: ValidationReport | None = None
) -> dict[str, Any]:
    """The certificate as the screen reads it. Every amount is a string.

    Raises:
        ValueError: ``locale`` is not ``tr``, ``en`` or ``tr-en``.
    """
    languages = locale_languages(locale)
    cert = document.cert
    inp = cert.inp
    settings = document.settings
    source = document.source
    overrides = settings.labels
    layout = {defn.key: defn for defn in inp.layout}
    previous = _previous_line(inp.layout)
    general, parties = header_columns(cert, locale, settings, document.issue_date)
    columns, rows = printed_works(cert, locale, settings)
    editable = source.editable and not document.frozen
    # Line D may be typed only where no certified figure exists or is coming:
    # on a first certificate, or after one that was settled before sheets were
    # stored. The same rule the save applies, so the screen offers the field
    # exactly when the save would take it.
    opening_total_allowed = not source.prior or (source.prior[-1].settled and not document.previous_frozen)

    summary: list[dict[str, Any]] = []
    for printed, line in zip(printed_summary(cert, locale, settings), cert.summary, strict=True):
        defn = layout[line.key]
        reason_key = line.basis.get("reason", "") if line.status == "held" else ""
        prefix = "reason."
        params = {name[len(prefix) :]: value for name, value in line.basis.items() if name.startswith(prefix)}
        entered = document.manual.get(line.key)
        summary.append(
            {
                "key": line.key,
                "letter": line.letter,
                "section": line.section,
                "op": defn.op,
                "sign": defn.sign,
                "tax_kind": defn.tax_kind,
                "status": line.status,
                "amount": _plain(line.amount) if line.status == "value" else None,
                "text": printed.text,
                "labels": list(printed.labels),
                "formulas": list(printed.formulas),
                "details": list(printed.details),
                "basis": dict(line.basis),
                "reason_key": reason_key,
                "reason_params": params if reason_key else {},
                "reason_text": (
                    [reason_text(reason_key, params, cert, language, settings) for language in languages]
                    if reason_key
                    else []
                ),
                "notes": list(printed.notes),
                "emphasis": printed.emphasis,
                "enterable": editable
                and (
                    defn.op == "manual" or (previous is not None and defn.key == previous.key and opening_total_allowed)
                ),
                "accepts_percent": defn.op == "manual" and bool(defn.operands),
                "entered": (
                    {
                        "state": entered.status,
                        "amount": _plain(entered.amount),
                        "pct": _plain(entered.pct),
                        "note": entered.note,
                    }
                    if entered is not None
                    else None
                ),
            }
        )

    view = document.taxes
    language = languages[0]
    findings = findings_payload(report) if report is not None else []
    blocking = [item for item in findings if item["severity"] == "error" or item["engine_error"]]
    return {
        "source_kind": source.kind,
        "source_id": str(source.source_id),
        "project_id": str(source.project_id),
        "reference": source.reference,
        "status": source.status,
        "locale": locale,
        "locales": list(LOCALES),
        "layout_available": True,
        "editable": editable,
        "frozen": document.frozen,
        "frozen_at": document.frozen_at or None,
        "is_draft": cert.is_draft,
        "currency": inp.currency,
        "country_code": inp.country_code,
        "flavour": inp.flavour,
        "header": {
            "certificate_number": inp.certificate_number,
            "is_final": inp.is_final,
            "period_start": inp.period_start.isoformat(),
            "period_end": inp.period_end.isoformat(),
            "issue_date": document.issue_date.isoformat() if document.issue_date else None,
            "project_name": inp.project_name,
            "contract_number": inp.contract_number,
            "contract_title": inp.contract_title,
            "employer": _party(inp.employer),
            "contractor": _party(inp.contractor),
            "rows": [{"labels": list(names), "value": value} for names, value in general],
            "party_rows": [{"labels": list(names), "value": value} for names, value in parties],
        },
        "works": {
            "columns": [
                {
                    "key": column.key,
                    "letter": column.letter,
                    "kind": column.kind,
                    "labels": list(label_parts(f"col.{inp.flavour}.{column.key}", locale, overrides)),
                }
                for column in columns
            ],
            "rows": [
                {
                    "kind": row.kind,
                    "title": row.title,
                    "cells": list(row.cells),
                    # Plain notation, so a zero reads "0" live and from the
                    # snapshot alike, never as an exponent.
                    "values": [
                        _plain(value) if isinstance(value, Decimal) else (None if value is None else str(value))
                        for value in row.values
                    ],
                    "flagged": row.flagged,
                    "held": row.held,
                }
                for row in rows
            ],
            "totals": {
                "previous_amount": _plain(cert.totals.previous_amount),
                "period_amount": _plain(cert.totals.period_amount),
                "cumulative_amount": _plain(cert.totals.cumulative_amount),
                "contract_amount": _plain(cert.totals.contract_amount),
            },
        },
        "summary": summary,
        "notes": [
            {
                "number": note.number,
                "line_key": note.line_key,
                "letter": note.letter,
                "reason_key": note.reason_key,
                "reason_params": dict(note.params),
                "text": [reason_text(note.reason_key, note.params, cert, lang, settings) for lang in languages],
            }
            for note in cert.notes
        ],
        "taxes": {
            "available": view.available,
            "stored": view.stored,
            "status": view.status,
            "stale": view.stale,
            "expected_net_amount": _plain(view.expected_net_amount),
            "expected_stamp_duty_base": _plain(view.expected_stamp_duty_base),
            "vat_rate_pct": _plain(view.vat_rate_pct),
            "document_date": view.document_date.isoformat() if view.document_date else None,
            "direction": view.direction,
            "choices": {
                kind: {"state": choice.state, "code": choice.code, "reason": choice.reason}
                for kind, choice in view.choices.items()
            },
            "buyer_is_designated": view.buyer_is_designated,
            "work_value_incl_vat": _plain(view.work_value_incl_vat),
            "work_value_note": view.work_value_note,
            "categories": (
                {kind: [] for kind in certificate_taxes.TAX_CHOICE_KINDS}
                if document.frozen
                else tax_categories(inp.country_code, view.document_date, language)
            ),
        },
        "options": {"is_final": inp.is_final},
        "signature_roles": [
            {"key": role, "labels": list(label_parts(f"role.{role}", locale, overrides))}
            for role in inp.signature_roles
        ],
        "carried_total": _plain(document.carried_total),
        "findings": findings,
        "can_certify": not document.frozen and report is not None and not blocking,
    }


def file_name(document: HakedisDocument, extension: str, locale: str) -> str:
    """A name for the printed file: the contract, the certificate number, the language."""
    inp = document.cert.inp
    stem = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in (inp.contract_number or "hakedis")).strip("-")
    draft = "-draft" if document.cert.is_draft else ""
    return f"hakedis-{stem or 'contract'}-{inp.certificate_number:02d}-{locale}{draft}.{extension}"


__all__ = [
    "DOCUMENT_KEY",
    "HAKEDIS_RULE_SET",
    "OPTIONS_KEY",
    "SOURCE_PROGRESS_CLAIM",
    "SOURCE_SUB_PAYMENT_APPLICATION",
    "CertificateSource",
    "HakedisDocument",
    "PriorDocument",
    "TaxView",
    "as_day",
    "build_document",
    "check_terms",
    "document_payload",
    "enforce_ready",
    "file_name",
    "findings_payload",
    "first_language",
    "freeze_document",
    "hakedis_available",
    "not_available",
    "own_company_party",
    "party_from_record",
    "rule_context",
    "run_rules",
    "save_line",
    "save_options",
    "save_taxes",
    "settings_for",
    "snapshot_of",
    "tax_categories",
]
