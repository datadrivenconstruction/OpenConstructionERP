# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""E-invoice clearance service - the round trip and the state behind it.

Stateless helpers over the three models. What lives here is the part that is
genuinely this module's: preparing a payload, deciding whether it may go,
handing it to an adapter, and reading the answer as the regime defines it.

Two things it deliberately does not do:

* build an EN 16931 invoice. :mod:`app.modules.einvoice` does that, in two
  syntaxes across ten profiles, and is imported as a library.
* talk to a government platform. That is an adapter, behind an interface.

The gate
========
:func:`app.modules.einvoice_clearance.validators.evaluate` runs the rules
through the validation engine, which is guarded: a broken rule degrades to "no
findings" so a validation bug cannot stop somebody recording the state of an
invoice. That guard is exactly why it is not what stops a bad submission. The
consequential paths call
:func:`app.modules.einvoice_clearance.validators.hard_blockers` instead, which
runs the same rule objects with no guard at all, so a silenced engine can never
become a way to put an incomplete document to a tax authority. Same rules, two
callers, one definition.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.validation.engine import RuleResult, Severity
from app.modules.einvoice_clearance import repository
from app.modules.einvoice_clearance.adapters import (
    CancellationRequest,
    PollRequest,
    SubmissionOutcome,
    SubmissionRequest,
    adapter_registry,
    supports_polling,
)
from app.modules.einvoice_clearance.models import (
    SETTLED_STATUSES,
    STATUS_CANCELLED,
    STATUS_CLEARED,
    STATUS_DRAFT,
    STATUS_QUEUED,
    STATUS_REJECTED,
    STATUS_SUBMITTED,
    STATUS_VALIDATED,
    TERMINAL_SUCCESS,
    EInvoiceDocument,
    EInvoiceProfile,
    can_be_sent,
    can_transition,
)
from app.modules.einvoice_clearance.regimes import (
    REGIME_CLEARANCE,
    CountryRegime,
    get_country_regime,
    regime_as_dict,
)
from app.modules.einvoice_clearance.validators import (
    INTENT_CANCEL,
    INTENT_SAVE,
    INTENT_SUBMIT,
    evaluate,
    hard_blockers,
)

logger = logging.getLogger(__name__)


class ClearanceError(Exception):
    """A refusal the caller can act on.

    Carries the findings that caused it where there are any, so the router can
    hand back the rule that objected rather than a sentence about it.
    """

    def __init__(self, message: str, *, findings: list[RuleResult] | None = None, conflict: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.findings = findings or []
        # ``True`` when the refusal is about the state of the record rather than
        # its contents - the router turns that into a 409 instead of a 422.
        self.conflict = conflict


def _now() -> datetime:
    return datetime.now(UTC)


def compute_payload_hash(payload: bytes) -> str:
    """SHA-256 of the exact bytes that will be submitted.

    Of the exact bytes, not of a re-serialisation of the same data: two encoders
    can agree about an invoice and disagree about whitespace, and the point of
    the hash is to answer "is this the document the authority holds" rather than
    "is this roughly the same invoice".
    """
    return hashlib.sha256(payload).hexdigest()


def _decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def regime_for(profile: EInvoiceProfile) -> CountryRegime:
    """The country registry entry behind a registration.

    Raises rather than guessing. A country with no entry has no known regime,
    and assuming network exchange for it would let a clearance country's invoice
    go out without the identifier it is not valid without.
    """
    entry = get_country_regime(profile.country)
    if entry is None:
        raise ClearanceError(
            f"No e-invoicing regime is registered for country {profile.country!r}, "
            "so there is no way to know what its authority expects."
        )
    return entry


# ── Payload ──────────────────────────────────────────────────────────────────


async def build_payload_from_invoice(
    session: AsyncSession,
    *,
    invoice_id: uuid.UUID,
    en16931_profile: str,
) -> tuple[str, str]:
    """Render the finance invoice with the EN 16931 engine.

    Only for the countries whose format that engine covers, which is the
    network-exchange set plus plain EN 16931. A national format outside it -
    CFDI, NF-e, FatturaPA, KSeF FA(3), ZATCA, the Indian IRP schema - is not
    produced here and never has been; for those the payload comes from whatever
    does produce it and is passed in.
    """
    from app.modules.einvoice import render_einvoice
    from app.modules.einvoice.cii import EInvoiceError
    from app.modules.finance.models import Invoice

    invoice = (await session.execute(select(Invoice).where(Invoice.id == invoice_id))).scalar_one_or_none()
    if invoice is None:
        raise ClearanceError(f"Invoice {invoice_id} was not found, so there is nothing to prepare.")

    invoice_dict: dict[str, Any] = {
        "invoice_number": invoice.invoice_number,
        "invoice_direction": invoice.invoice_direction,
        "invoice_date": invoice.invoice_date,
        "due_date": invoice.due_date,
        "currency_code": invoice.currency_code,
        "amount_subtotal": invoice.amount_subtotal,
        "tax_amount": invoice.tax_amount,
        "retention_amount": invoice.retention_amount,
        "amount_total": invoice.amount_total,
        "notes": invoice.notes,
        "metadata": dict(invoice.metadata_ or {}),
    }
    line_items = [
        {
            "description": item.description,
            "unit": item.unit,
            "quantity": item.quantity,
            "unit_rate": item.unit_rate,
            "amount": item.amount,
            # EN 16931 per-line VAT (BT-152 rate, BT-151 category). Without
            # these a mixed-rate invoice clears under the single rate derived
            # from the header, which reconciles and passes every rule while
            # describing money the invoice does not describe. The finance
            # export route flattens the same lines through
            # ``_line_item_dicts``, and the two documents have to match.
            "vat_rate": item.vat_rate,
            "vat_category": item.vat_category,
        }
        for item in (invoice.line_items or [])
    ]

    # The same standing configuration the finance export path resolves, buyer
    # included. Both render the same invoice row, so resolving it in only one of
    # them would mean a document cleared for export here and refused there, or
    # worse, two different documents for one invoice.
    from app.modules.finance.einvoice_parties import einvoice_defaults_for_invoice

    defaults = await einvoice_defaults_for_invoice(
        session,
        contact_id=invoice.contact_id,
        invoice_direction=invoice.invoice_direction,
    )

    try:
        _filename, media_type, body = render_einvoice(
            invoice=invoice_dict,
            line_items=line_items,
            profile=en16931_profile,
            defaults=defaults,
        )
    except EInvoiceError as exc:
        raise ClearanceError(
            f"The invoice is not complete enough to render as {en16931_profile}: {exc}. "
            "Seller identity and the bank account are set once under the e-invoice settings; "
            "the buyer address is read from the linked contact and the buyer reference "
            "belongs to this invoice."
        ) from exc
    # The engine emits UTF-8 XML. Held as text from here on so the stored
    # document and the bytes that go on the wire are one thing that cannot
    # drift through a re-encode.
    return body.decode("utf-8"), media_type


# A national format outside the EN 16931 engine can still be built from the
# finance invoice, by the package that knows the format. That package registers
# a builder here under the regime's ``document_format`` from its own startup
# hook, so this module never imports it and removing the package removes the
# format cleanly.
PayloadBuilder = Callable[..., Awaitable[tuple[str, str]]]

_payload_builders: dict[str, PayloadBuilder] = {}


def register_payload_builder(document_format: str, builder: PayloadBuilder) -> None:
    """Register the builder for one national format. Overwrites by format.

    The builder is awaited as ``builder(session, invoice_id=..., profile=...,
    country_fields=...)`` and returns ``(payload_text, media_type)``. It raises
    :class:`ClearanceError` for an invoice it cannot turn into that format.
    """
    _payload_builders[(document_format or "").strip()] = builder


def payload_builder_for(document_format: str) -> PayloadBuilder | None:
    """The registered builder for a national format, or ``None``."""
    return _payload_builders.get((document_format or "").strip())


async def resolve_payload(
    session: AsyncSession,
    *,
    regime: CountryRegime,
    supplied: str | None,
    invoice_id: uuid.UUID | None,
    media_type: str,
    profile: EInvoiceProfile | None = None,
    country_fields: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Decide what document is going to the platform.

    A supplied payload always wins: the caller knows what their national format
    generator produced, and re-deriving it here would risk sending something
    other than what they reviewed.
    """
    if supplied is not None and supplied.strip():
        return supplied, media_type
    if regime.en16931_profile and invoice_id is not None:
        return await build_payload_from_invoice(session, invoice_id=invoice_id, en16931_profile=regime.en16931_profile)
    builder = payload_builder_for(regime.document_format)
    if builder is not None and invoice_id is not None and profile is not None:
        return await builder(
            session,
            invoice_id=invoice_id,
            profile=profile,
            country_fields=dict(country_fields or {}),
        )
    raise ClearanceError(
        f"{regime.country} uses {regime.document_format}, which this platform does not generate, "
        "so the document has to be supplied with the request."
    )


# ── Validation context ───────────────────────────────────────────────────────


def profile_as_dict(profile: EInvoiceProfile) -> dict[str, Any]:
    """Flatten a registration for the rules and the adapters.

    Never carries a credential. ``certificate_reference`` names where the key
    lives; the key itself is the deployment's business and has no reason to be
    in a validation context or an adapter argument.
    """
    return {
        "id": str(profile.id),
        "company_key": profile.company_key,
        "country": profile.country,
        "regime": profile.regime,
        "platform": profile.platform,
        "tax_registration_id": profile.tax_registration_id,
        "network_participant_id": profile.network_participant_id,
        "certificate_reference": profile.certificate_reference,
        "adapter_key": profile.adapter_key,
        "sandbox": bool(profile.sandbox),
        "is_active": bool(profile.is_active),
        "settings": dict(profile.settings or {}),
    }


def document_as_dict(document: EInvoiceDocument, **overrides: Any) -> dict[str, Any]:
    """Flatten a document for the rules and the adapters."""
    payload: dict[str, Any] = {
        "id": str(document.id),
        "project_id": str(document.project_id),
        "invoice_id": str(document.invoice_id) if document.invoice_id else "",
        "country": document.country,
        "regime": document.regime,
        "document_format": document.document_format,
        "invoice_number": document.invoice_number,
        "invoice_date": document.invoice_date,
        "currency_code": document.currency_code,
        # A string, not a float. The rules only report it, but a float here
        # would be the one place in the module where money stopped being exact.
        "total_amount": format(_decimal(document.total_amount), "f"),
        "payload_hash": document.payload_hash,
        "country_fields": dict(document.country_fields or {}),
        "status": document.status,
        "authority_identifier": document.authority_identifier,
        "submitted_at": document.submitted_at,
        "cleared_at": document.cleared_at,
        "cancelled_at": document.cancelled_at,
        "cancellation_reason": document.cancellation_reason,
        "rejection_code": document.rejection_code,
        "retry_count": document.retry_count,
    }
    payload.update(overrides)
    return payload


def build_context(
    *,
    intent: str,
    profile: EInvoiceProfile,
    regime: CountryRegime,
    document: EInvoiceDocument,
    duplicate: EInvoiceDocument | None = None,
    changed_fields: list[str] | None = None,
    document_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the one dict every rule reads.

    ``invoice_is_real`` is "this document is tied to a finance invoice". That is
    the whole definition, and it is deliberately narrow: a document created
    without an invoice reference is somebody trying the module out, and warning
    them about a sandbox registration would be noise.
    """
    return {
        "intent": intent,
        "profile": profile_as_dict(profile),
        "regime": regime_as_dict(regime),
        "document": document_as_dict(document, **(document_overrides or {})),
        "duplicate": (
            {
                "id": str(duplicate.id),
                "status": duplicate.status,
                "authority_identifier": duplicate.authority_identifier,
            }
            if duplicate is not None
            else None
        ),
        "changed_fields": list(changed_fields or []),
        "invoice_is_real": document.invoice_id is not None,
        "reference_time": _now(),
        # The document itself, for the rules that read a national format. Only
        # rules registered for that format look at it.
        "payload": {
            "format": document.document_format,
            "media_type": document.payload_media_type,
            "text": document.payload or "",
        },
    }


# ── State machine ────────────────────────────────────────────────────────────


async def _move(
    session: AsyncSession,
    document: EInvoiceDocument,
    to_status: str,
    *,
    event_type: str,
    message: str = "",
    authority_code: str = "",
    raw_response: dict[str, Any] | None = None,
    actor_id: uuid.UUID | None = None,
) -> None:
    """Move a document and record the move in one step.

    One function so a status can never change without an event: the trail is
    only trustworthy if there is no other way to write the column.
    """
    from_status = document.status
    if from_status != to_status and not can_transition(from_status, to_status):
        raise ClearanceError(
            f"A document cannot go from {from_status} to {to_status}.",
            conflict=True,
        )
    document.status = to_status
    await repository.append_event(
        session,
        document_id=document.id,
        event_type=event_type,
        from_status=from_status,
        to_status=to_status,
        message=message,
        authority_code=authority_code,
        raw_response=raw_response,
        actor_id=actor_id,
    )


# ── Documents ────────────────────────────────────────────────────────────────


async def create_document(
    session: AsyncSession,
    *,
    profile: EInvoiceProfile,
    body: Any,
    actor_id: uuid.UUID | None = None,
) -> tuple[EInvoiceDocument, list[RuleResult]]:
    """Prepare one invoice for one country's platform.

    Country, regime and format come from the registration and the registry, not
    from the caller. Two sources for one fact is two sources that can disagree,
    and here the disagreement would be an invoice cleared under the wrong
    country's rules.
    """
    regime = regime_for(profile)
    if not profile.is_active:
        raise ClearanceError(
            f"The {profile.country} registration for {profile.company_key} is not active.",
            conflict=True,
        )

    payload, media_type = await resolve_payload(
        session,
        regime=regime,
        supplied=body.payload,
        invoice_id=body.invoice_id,
        media_type=body.payload_media_type,
        profile=profile,
        country_fields=dict(body.country_fields or {}),
    )

    document = EInvoiceDocument(
        project_id=body.project_id,
        invoice_id=body.invoice_id,
        profile_id=profile.id,
        country=profile.country,
        regime=regime.regime,
        document_format=regime.document_format,
        invoice_number=body.invoice_number,
        invoice_date=body.invoice_date,
        currency_code=body.currency_code,
        total_amount=_decimal(body.total_amount),
        payload=payload,
        payload_hash=compute_payload_hash(payload.encode("utf-8")),
        payload_media_type=media_type,
        payload_size=len(payload.encode("utf-8")),
        country_fields=dict(body.country_fields or {}),
        status=STATUS_DRAFT,
        adapter_key=profile.adapter_key,
    )
    await repository.add_document(session, document)
    await repository.append_event(
        session,
        document_id=document.id,
        event_type="created",
        to_status=STATUS_DRAFT,
        message=f"Prepared for {regime.label}.",
        actor_id=actor_id,
    )

    findings = await evaluate(
        build_context(intent=INTENT_SAVE, profile=profile, regime=regime, document=document),
        document_id=str(document.id),
    )
    return document, findings


async def update_document(
    session: AsyncSession,
    *,
    document: EInvoiceDocument,
    profile: EInvoiceProfile,
    body: Any,
    actor_id: uuid.UUID | None = None,
) -> tuple[EInvoiceDocument, list[RuleResult]]:
    """Correct a document that has not been sent yet.

    A settled document is refused here rather than reported as a finding,
    because a finding is advice and this is a rule about what the record *is*:
    the authority holds a copy of exactly what was sent, and a row that no
    longer matches it would be a quiet lie about a tax document.
    """
    regime = regime_for(profile)
    if document.status in SETTLED_STATUSES:
        raise ClearanceError(
            f"This document is {document.status} and cannot be changed. "
            f"Correct it the way {document.country} allows: {regime.correction_mechanism}.",
            conflict=True,
        )

    changed: list[str] = []
    for name in ("invoice_number", "invoice_date", "currency_code"):
        if getattr(document, name) != getattr(body, name):
            changed.append(name)
            setattr(document, name, getattr(body, name))
    if document.total_amount != _decimal(body.total_amount):
        changed.append("total_amount")
        document.total_amount = _decimal(body.total_amount)
    if dict(document.country_fields or {}) != dict(body.country_fields or {}):
        changed.append("country_fields")
        document.country_fields = dict(body.country_fields or {})

    if body.payload is not None and body.payload.strip():
        encoded = body.payload.encode("utf-8")
        digest = compute_payload_hash(encoded)
        if digest != document.payload_hash:
            changed.append("payload")
            document.payload = body.payload
            document.payload_hash = digest
            document.payload_size = len(encoded)
            document.payload_media_type = body.payload_media_type

    if changed:
        # Any edit puts the document back to draft: a "validated" flag that
        # survives a change to the thing it validated is worse than no flag.
        if document.status != STATUS_DRAFT:
            await _move(
                session,
                document,
                STATUS_DRAFT,
                event_type="updated",
                message=f"Changed: {', '.join(changed)}.",
                actor_id=actor_id,
            )
        else:
            await repository.append_event(
                session,
                document_id=document.id,
                event_type="updated",
                from_status=STATUS_DRAFT,
                to_status=STATUS_DRAFT,
                message=f"Changed: {', '.join(changed)}.",
                actor_id=actor_id,
            )
    await session.flush()

    findings = await evaluate(
        build_context(
            intent=INTENT_SAVE,
            profile=profile,
            regime=regime,
            document=document,
            changed_fields=changed,
        ),
        document_id=str(document.id),
    )
    return document, findings


async def validate_document(
    session: AsyncSession,
    *,
    document: EInvoiceDocument,
    profile: EInvoiceProfile,
    actor_id: uuid.UUID | None = None,
) -> list[RuleResult]:
    """Run the rules and mark the document validated when nothing blocks it.

    A dry run against the same rules the submission will use, so an operator
    finds out about a missing Uso CFDI at their desk rather than from a
    rejection three minutes before the month closes.
    """
    regime = regime_for(profile)
    duplicate = await repository.find_live_duplicate(
        session,
        profile_id=profile.id,
        payload_hash=document.payload_hash,
        exclude_id=document.id,
    )
    context = build_context(
        intent=INTENT_SUBMIT,
        profile=profile,
        regime=regime,
        document=document,
        duplicate=duplicate,
    )
    findings = await evaluate(context, document_id=str(document.id))
    blocking = await hard_blockers(context)

    if not blocking and document.status in (STATUS_DRAFT, STATUS_REJECTED):
        await _move(
            session,
            document,
            STATUS_VALIDATED,
            event_type="validated",
            message="Checked against the country rules; nothing blocking.",
            actor_id=actor_id,
        )
        await session.flush()
    return findings


async def submit_document(
    session: AsyncSession,
    *,
    document: EInvoiceDocument,
    profile: EInvoiceProfile,
    actor_id: uuid.UUID | None = None,
    accept_warnings: bool = False,
) -> tuple[EInvoiceDocument, SubmissionOutcome, list[RuleResult]]:
    """Put the document to the platform and record what came back.

    The adapter says only whether the platform accepted it. What an acceptance
    *means* is read from the regime: a clearance country's yes makes the invoice
    valid, a reporting country's yes acknowledges a filing about an invoice that
    was already valid, and a network's yes is a delivery receipt. Letting the
    adapter choose the status is how a Peppol delivery would end up recorded as
    a tax clearance.
    """
    regime = regime_for(profile)
    if not can_be_sent(document.status):
        # Asked of the state machine, not of a list kept here. The move to
        # ``queued`` below would refuse the same states anyway; refusing up
        # front says so before the duplicate lookup, the rules and the adapter
        # have all been run, and says it in the words of what is actually wrong.
        if document.status == STATUS_SUBMITTED:
            raise ClearanceError(
                f"This document has already gone to {regime.platform} and nothing is recorded about how it "
                "was answered. Sending it again risks two cleared invoices for one sale, so read the "
                "outcome off the platform and record that instead.",
                conflict=True,
            )
        raise ClearanceError(
            f"This document is already {document.status}; it cannot be sent again.",
            conflict=True,
        )

    duplicate = await repository.find_live_duplicate(
        session,
        profile_id=profile.id,
        payload_hash=document.payload_hash,
        exclude_id=document.id,
    )
    context = build_context(
        intent=INTENT_SUBMIT,
        profile=profile,
        regime=regime,
        document=document,
        duplicate=duplicate,
    )
    blocking = await hard_blockers(context)
    if blocking:
        raise ClearanceError(
            "This document cannot be submitted yet.",
            findings=blocking,
        )

    findings = await evaluate(context, document_id=str(document.id))
    warnings = [f for f in findings if f.severity == Severity.WARNING]
    if warnings and not accept_warnings:
        raise ClearanceError(
            "This document has warnings that have not been acknowledged.",
            findings=warnings,
        )

    adapter = adapter_registry.get(profile.adapter_key)
    if adapter is None:
        raise ClearanceError(
            f"No adapter named {profile.adapter_key!r} is installed, so nothing can reach "
            f"{regime.platform}. Install the {document.country} adapter or point the registration "
            "at one that is installed."
        )

    payload = (document.payload or "").encode("utf-8")
    if not payload:
        raise ClearanceError(
            "This document carries no payload, so there is nothing to send.",
            conflict=True,
        )

    request = SubmissionRequest(
        country=document.country,
        regime=document.regime,
        document_format=document.document_format,
        # The stored bytes, not a re-render. Re-deriving here could send
        # something other than the document the hash describes and the operator
        # reviewed.
        payload=payload,
        payload_hash=document.payload_hash,
        payload_media_type=document.payload_media_type,
        profile=profile_as_dict(profile),
        document=document_as_dict(document),
        regime_spec=regime_as_dict(regime),
    )

    document.adapter_key = profile.adapter_key
    await _move(session, document, STATUS_QUEUED, event_type="queued", actor_id=actor_id)
    await _move(
        session,
        document,
        STATUS_SUBMITTED,
        event_type="submitted",
        message=f"Sent to {regime.platform} via adapter {profile.adapter_key}.",
        actor_id=actor_id,
    )
    document.submitted_at = _now()

    try:
        outcome = await adapter.submit(request)
    except Exception as exc:  # noqa: BLE001 - the transport failed, the document did not
        # The document stays in ``submitted`` on purpose. A transport failure
        # does not say the platform did not receive it, and moving the row back
        # to draft would invite a second submission of a document that may
        # already be cleared.
        await repository.append_event(
            session,
            document_id=document.id,
            event_type="note",
            from_status=STATUS_SUBMITTED,
            to_status=STATUS_SUBMITTED,
            message=f"The adapter failed before answering: {exc}",
            actor_id=actor_id,
        )
        await session.flush()
        logger.warning("e-invoice clearance adapter %s failed", profile.adapter_key, exc_info=True)
        raise ClearanceError(
            f"The adapter failed before {regime.platform} answered, so this document is left as "
            "submitted with an unknown outcome. It cannot simply be sent again, because it may "
            "already be cleared. Read what the platform shows and record that against this document."
        ) from exc

    if outcome.accepted and outcome.pending:
        await _record_pending(session, document, outcome, regime=regime, actor_id=actor_id)
    elif outcome.accepted:
        target = TERMINAL_SUCCESS.get(_accepted_act(outcome, regime), STATUS_SUBMITTED)
        document.authority_identifier = outcome.authority_identifier
        document.rejection_code = ""
        document.rejection_message = ""
        # Named for the clearance case, set for all three: it is the moment the
        # platform answered, whatever the answer legally amounted to.
        document.cleared_at = _now()
        await _move(
            session,
            document,
            target,
            event_type=target,
            message=outcome.message or f"{regime.platform} accepted the document.",
            raw_response=outcome.raw_response,
            actor_id=actor_id,
        )
    else:
        document.rejection_code = outcome.rejection_code
        document.rejection_message = outcome.rejection_message
        document.retry_count += 1
        await _move(
            session,
            document,
            STATUS_REJECTED,
            event_type="rejected",
            message=outcome.rejection_message,
            authority_code=outcome.rejection_code,
            raw_response=outcome.raw_response,
            actor_id=actor_id,
        )
    await session.flush()
    return document, outcome, findings


def _accepted_act(outcome: SubmissionOutcome, regime: CountryRegime) -> str:
    """The act an accepted answer amounts to: the adapter's, if the regime declares it."""
    if outcome.act and outcome.act in regime.regimes:
        return outcome.act
    return regime.regime


async def _record_pending(
    session: AsyncSession,
    document: EInvoiceDocument,
    outcome: SubmissionOutcome,
    *,
    regime: CountryRegime,
    actor_id: uuid.UUID | None,
) -> None:
    """Keep a document the platform took in but has not decided about.

    The identifier is stored now, because it is the only handle there is on the
    document at the platform: losing it would leave nothing to poll and nothing
    to quote to the authority. The status stays ``submitted``, which already
    means "gone, verdict not recorded", so a second submission stays refused.
    """
    if outcome.authority_identifier:
        document.authority_identifier = outcome.authority_identifier
    await repository.append_event(
        session,
        document_id=document.id,
        event_type="note",
        from_status=STATUS_SUBMITTED,
        to_status=STATUS_SUBMITTED,
        message=outcome.message or f"{regime.platform} took the document in; its verdict is pending.",
        authority_code=outcome.rejection_code,
        raw_response=outcome.raw_response,
        actor_id=actor_id,
    )


async def refresh_document(
    session: AsyncSession,
    *,
    document: EInvoiceDocument,
    profile: EInvoiceProfile,
    actor_id: uuid.UUID | None = None,
) -> tuple[EInvoiceDocument, SubmissionOutcome]:
    """Ask the platform for its verdict on a document it took in.

    Only for a document in ``submitted`` that carries the platform's identifier,
    and only through an adapter that can poll. Without the identifier there is
    nothing to ask about, and the way out is the hand-recorded resolve.
    """
    regime = regime_for(profile)
    if document.status != STATUS_SUBMITTED:
        raise ClearanceError(
            f"Only a submitted document waits for a verdict; this one is {document.status}.",
            conflict=True,
        )
    if not (document.authority_identifier or "").strip():
        raise ClearanceError(
            f"Nothing came back from {regime.platform} for this document, so there is nothing to ask about. "
            "Read what the platform shows and record it by hand.",
            conflict=True,
        )
    adapter_key = document.adapter_key or profile.adapter_key
    adapter = adapter_registry.get(adapter_key)
    if adapter is None or not supports_polling(adapter):
        raise ClearanceError(
            f"The adapter {adapter_key!r} cannot read a verdict back from {regime.platform}. "
            "Read it on the platform and record it by hand.",
            conflict=True,
        )

    try:
        outcome: SubmissionOutcome = await adapter.poll(  # type: ignore[attr-defined]
            PollRequest(
                country=document.country,
                regime=document.regime,
                authority_identifier=document.authority_identifier,
                profile=profile_as_dict(profile),
                document=document_as_dict(document),
                regime_spec=regime_as_dict(regime),
            )
        )
    except Exception as exc:  # noqa: BLE001 - the transport failed, the document did not
        logger.warning("e-invoice clearance poll via %s failed", adapter_key, exc_info=True)
        raise ClearanceError(
            f"{regime.platform} could not be asked about this document: {exc}. Nothing was changed; try again."
        ) from exc

    if outcome.pending:
        await repository.append_event(
            session,
            document_id=document.id,
            event_type="note",
            from_status=STATUS_SUBMITTED,
            to_status=STATUS_SUBMITTED,
            message=outcome.message or f"{regime.platform} has not decided yet.",
            raw_response=outcome.raw_response,
            actor_id=actor_id,
        )
    elif outcome.accepted:
        target = TERMINAL_SUCCESS.get(_accepted_act(outcome, regime), STATUS_CLEARED)
        if outcome.authority_identifier:
            document.authority_identifier = outcome.authority_identifier
        document.rejection_code = ""
        document.rejection_message = ""
        document.cleared_at = _now()
        await _move(
            session,
            document,
            target,
            event_type=target,
            message=outcome.message or f"{regime.platform} accepted the document.",
            raw_response=outcome.raw_response,
            actor_id=actor_id,
        )
    else:
        document.rejection_code = outcome.rejection_code
        document.rejection_message = outcome.rejection_message
        document.retry_count += 1
        await _move(
            session,
            document,
            STATUS_REJECTED,
            event_type="rejected",
            message=outcome.rejection_message,
            authority_code=outcome.rejection_code,
            raw_response=outcome.raw_response,
            actor_id=actor_id,
        )
    await session.flush()
    return document, outcome


async def resolve_document(
    session: AsyncSession,
    *,
    document: EInvoiceDocument,
    profile: EInvoiceProfile,
    outcome: str,
    note: str,
    authority_identifier: str = "",
    rejection_code: str = "",
    rejection_message: str = "",
    actor_id: uuid.UUID | None = None,
) -> EInvoiceDocument:
    """Record by hand what the platform did with a document that is in doubt.

    Reachable only from ``submitted``, which is where a document lands when the
    adapter failed before the platform answered. The machine cannot reason its
    way out of that: it does not know whether the document arrived. The two
    tempting shortcuts are both worse than asking - sending it again risks two
    cleared invoices for one sale, and putting it back to draft loses the fact
    that something was sent - so the way out is an operator looking at the
    portal and writing down what they saw, with their name on the event.
    """
    regime = regime_for(profile)
    if document.status != STATUS_SUBMITTED:
        raise ClearanceError(
            f"Only a document left in submitted can be resolved by hand; this one is {document.status}.",
            conflict=True,
        )
    if not note.strip():
        raise ClearanceError("Say where the information came from before changing a fiscal record by hand.")

    if outcome == "cleared":
        target = TERMINAL_SUCCESS.get(regime.regime, STATUS_SUBMITTED)
        if regime.regime == REGIME_CLEARANCE and not authority_identifier.strip():
            raise ClearanceError(
                f"{regime.country} returns {regime.identifier_label or 'an identifier'}, and the invoice is "
                "not valid without it. Read it off the platform and record it here."
            )
        document.authority_identifier = authority_identifier.strip()
        document.rejection_code = ""
        document.rejection_message = ""
        document.cleared_at = _now()
        await _move(
            session,
            document,
            target,
            event_type=target,
            message=f"Resolved by hand: {note}",
            raw_response={"resolved_by_hand": True, "note": note},
            actor_id=actor_id,
        )
    elif outcome == "rejected":
        document.rejection_code = rejection_code.strip()
        document.rejection_message = rejection_message.strip() or note
        document.retry_count += 1
        await _move(
            session,
            document,
            STATUS_REJECTED,
            event_type="rejected",
            message=f"Resolved by hand: {note}",
            authority_code=rejection_code.strip(),
            raw_response={"resolved_by_hand": True, "note": note},
            actor_id=actor_id,
        )
    else:
        raise ClearanceError(f"Unknown outcome {outcome!r}; a document was either accepted or it was not.")

    await session.flush()
    return document


async def cancel_document(
    session: AsyncSession,
    *,
    document: EInvoiceDocument,
    profile: EInvoiceProfile,
    reason: str,
    actor_id: uuid.UUID | None = None,
) -> tuple[EInvoiceDocument, SubmissionOutcome, list[RuleResult]]:
    """Withdraw a document the platform has already accepted.

    The reason is carried through the check rather than written first, so a
    cancellation the country refuses does not leave a reason on a document that
    is still perfectly valid.
    """
    regime = regime_for(profile)
    if document.status not in TERMINAL_SUCCESS.values():
        raise ClearanceError(
            f"This document is {document.status}; there is nothing at {regime.platform} to withdraw.",
            conflict=True,
        )

    context = build_context(
        intent=INTENT_CANCEL,
        profile=profile,
        regime=regime,
        document=document,
        document_overrides={"cancellation_reason": reason},
    )
    blocking = await hard_blockers(context)
    if blocking:
        raise ClearanceError("This document cannot be cancelled.", findings=blocking)

    findings = await evaluate(context, document_id=str(document.id))

    adapter = adapter_registry.get(document.adapter_key or profile.adapter_key)
    if adapter is None:
        raise ClearanceError(
            f"No adapter named {document.adapter_key or profile.adapter_key!r} is installed, "
            f"so the cancellation cannot reach {regime.platform}."
        )

    outcome = await adapter.cancel(
        CancellationRequest(
            country=document.country,
            regime=document.regime,
            authority_identifier=document.authority_identifier,
            reason=reason,
            profile=profile_as_dict(profile),
            document=document_as_dict(document),
            regime_spec=regime_as_dict(regime),
        )
    )

    if not outcome.accepted:
        # The platform refused. The document is still cleared and still valid,
        # so nothing about its status changes - only the trail records that a
        # withdrawal was attempted and turned down. Writing the refusal into
        # ``rejection_code`` would say the *invoice* was rejected, which it
        # was not.
        await repository.append_event(
            session,
            document_id=document.id,
            event_type="note",
            from_status=document.status,
            to_status=document.status,
            message=outcome.rejection_message or "The platform refused the cancellation.",
            authority_code=outcome.rejection_code,
            raw_response=outcome.raw_response,
            actor_id=actor_id,
        )
        await session.flush()
        return document, outcome, findings

    document.cancellation_reason = reason
    document.cancelled_at = _now()
    await _move(
        session,
        document,
        STATUS_CANCELLED,
        event_type="cancelled",
        message=outcome.message or f"Withdrawn from {regime.platform}.",
        raw_response=outcome.raw_response,
        actor_id=actor_id,
    )
    await session.flush()
    return document, outcome, findings


__all__ = [
    "ClearanceError",
    "build_context",
    "build_payload_from_invoice",
    "cancel_document",
    "compute_payload_hash",
    "create_document",
    "document_as_dict",
    "payload_builder_for",
    "profile_as_dict",
    "refresh_document",
    "regime_for",
    "register_payload_builder",
    "resolve_document",
    "resolve_payload",
    "submit_document",
    "update_document",
    "validate_document",
]
