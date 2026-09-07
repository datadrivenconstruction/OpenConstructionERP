# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""E-invoice clearance Pydantic schemas - request/response models.

Money crosses the wire as a decimal string, never a float, matching the finance
module it sits next to: a binary float cannot hold 0.10 and a tax authority's
arithmetic is exact. Currency is required on any request that carries an
amount - this module's whole subject is that countries differ, so an amount
with an implied currency is a bug waiting for the first cross-border invoice.

The document's country, regime and format are not accepted from the caller.
They are read from the registration the document is filed under and the country
registry behind it, because two sources for one fact is two sources that can
disagree, and the disagreement here would be an invoice cleared under the wrong
country's rules.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.modules.einvoice_clearance.models import DOCUMENT_STATUSES, EVENT_TYPES
from app.modules.einvoice_clearance.regimes import (
    LEGAL_STATUSES,
    OBLIGATIONS,
    REGIME_CLASSES,
    REGIMES,
    SUPPORTED_COUNTRIES,
)

# Kept in step with the model tuples by ``test_einvoice_clearance_module.py``.
# The tuple is what the state machine moves between and this is what the API
# will accept as a filter; a drift would let a caller filter on a status no
# document can ever hold and get a confident empty list back.
STATUSES: tuple[str, ...] = DOCUMENT_STATUSES
COUNTRIES: tuple[str, ...] = SUPPORTED_COUNTRIES
EVENTS: tuple[str, ...] = EVENT_TYPES

MAX_COUNTRY_FIELDS = 40
# An e-invoice is a few kilobytes of XML; a megabyte is already an outlier with
# an embedded attachment in it. The ceiling exists because the document is
# stored on the row, so an unbounded field would be an unbounded table.
MAX_PAYLOAD_CHARS = 1_000_000


def _serialise_money(value: Decimal | None) -> str | None:
    """Emit money as a plain decimal string. Mirrors ``finance.schemas``."""
    if value is None:
        return None
    if not isinstance(value, Decimal):
        try:
            value = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return "0"
    if not value.is_finite():
        return "0"
    return format(value, "f")


def _check_decimal(value: str, field_name: str) -> str:
    try:
        Decimal(value)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Invalid decimal value for {field_name}: {value!r}") from exc
    return value


# ── Registration ─────────────────────────────────────────────────────────────


class _ProfileBody(BaseModel):
    """The writable half of a registration, shared by create and update."""

    model_config = ConfigDict(str_strip_whitespace=True)

    company_key: str = Field(min_length=1, max_length=120)
    country: str = Field(min_length=2, max_length=2)
    tax_registration_id: str = Field(default="", max_length=64)
    network_participant_id: str = Field(default="", max_length=120)
    # A reference to the certificate, never the certificate and never a key.
    certificate_reference: str = Field(default="", max_length=255)
    adapter_key: str = Field(default="", max_length=64)
    sandbox: bool = True
    is_active: bool = True
    settings: dict[str, Any] = Field(default_factory=dict)
    notes: str = Field(default="", max_length=2000)

    @field_validator("country")
    @classmethod
    def _known_country(cls, value: str) -> str:
        code = (value or "").strip().upper()
        if code not in COUNTRIES:
            raise ValueError(
                f"No e-invoicing regime is registered for country {value!r}. Known countries: {', '.join(COUNTRIES)}."
            )
        return code


class ProfileCreateRequest(_ProfileBody):
    """Register a legal entity with one country's platform."""


class ProfileUpdateRequest(_ProfileBody):
    """Replace a registration. The editor saves the whole form, so this is a PUT."""


class ProfileResponse(BaseModel):
    """One registration as the reader receives it."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_key: str
    country: str
    regime: str
    platform: str
    tax_registration_id: str
    network_participant_id: str
    certificate_reference: str
    adapter_key: str
    sandbox: bool
    is_active: bool
    settings: dict[str, Any]
    notes: str
    created_at: datetime
    updated_at: datetime


# ── Document ─────────────────────────────────────────────────────────────────


class DocumentCreateRequest(BaseModel):
    """Put one invoice into a country's clearance flow.

    ``payload`` is the document exactly as it should reach the platform. Leave
    it out and the module builds it with the EN 16931 engine, which works for
    the countries whose format that engine covers; for a national format it
    does not cover - CFDI, NF-e, FatturaPA, KSeF, ZATCA, the Indian IRP
    schema - the payload has to come from whatever produces it.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    profile_id: UUID
    invoice_id: UUID | None = None
    invoice_number: str = Field(default="", max_length=64)
    invoice_date: str = Field(default="", max_length=40)
    currency_code: str = Field(default="", max_length=3)
    total_amount: str = Field(default="0", max_length=50)
    country_fields: dict[str, str] = Field(default_factory=dict)
    payload: str | None = Field(default=None, max_length=MAX_PAYLOAD_CHARS)
    payload_media_type: str = Field(default="application/xml", max_length=80)

    @field_validator("total_amount")
    @classmethod
    def _decimal_amount(cls, value: str) -> str:
        return _check_decimal(value, "total_amount")

    @field_validator("currency_code")
    @classmethod
    def _upper_currency(cls, value: str) -> str:
        return (value or "").strip().upper()

    @field_validator("country_fields")
    @classmethod
    def _bounded_fields(cls, value: dict[str, str]) -> dict[str, str]:
        cleaned = {str(k).strip(): str(v).strip() for k, v in (value or {}).items() if str(k).strip()}
        if len(cleaned) > MAX_COUNTRY_FIELDS:
            raise ValueError(f"At most {MAX_COUNTRY_FIELDS} country fields may be carried on one document.")
        return cleaned


class DocumentUpdateRequest(BaseModel):
    """Correct a document that has not been sent yet.

    There is no status here. A status is the outcome of an act - validating,
    submitting, cancelling - and letting a caller set one directly would make
    every guarantee in the state machine optional.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    invoice_number: str = Field(default="", max_length=64)
    invoice_date: str = Field(default="", max_length=40)
    currency_code: str = Field(default="", max_length=3)
    total_amount: str = Field(default="0", max_length=50)
    country_fields: dict[str, str] = Field(default_factory=dict)
    payload: str | None = Field(default=None, max_length=MAX_PAYLOAD_CHARS)
    payload_media_type: str = Field(default="application/xml", max_length=80)

    @field_validator("total_amount")
    @classmethod
    def _decimal_amount(cls, value: str) -> str:
        return _check_decimal(value, "total_amount")

    @field_validator("currency_code")
    @classmethod
    def _upper_currency(cls, value: str) -> str:
        return (value or "").strip().upper()

    @field_validator("country_fields")
    @classmethod
    def _bounded_fields(cls, value: dict[str, str]) -> dict[str, str]:
        cleaned = {str(k).strip(): str(v).strip() for k, v in (value or {}).items() if str(k).strip()}
        if len(cleaned) > MAX_COUNTRY_FIELDS:
            raise ValueError(f"At most {MAX_COUNTRY_FIELDS} country fields may be carried on one document.")
        return cleaned


class DocumentResponse(BaseModel):
    """One document as the reader receives it."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    invoice_id: UUID | None
    profile_id: UUID
    country: str
    regime: str
    document_format: str
    invoice_number: str
    invoice_date: str
    currency_code: str
    total_amount: Decimal
    payload_hash: str
    payload_media_type: str
    payload_size: int
    country_fields: dict[str, Any]
    status: str
    authority_identifier: str
    submitted_at: datetime | None
    cleared_at: datetime | None
    cancelled_at: datetime | None
    rejection_code: str
    rejection_message: str
    cancellation_reason: str
    retry_count: int
    adapter_key: str
    created_at: datetime
    updated_at: datetime

    @field_serializer("total_amount")
    def _money(self, value: Decimal) -> str | None:
        return _serialise_money(value)


class SubmitRequest(BaseModel):
    """Put a prepared document to the platform."""

    model_config = ConfigDict(str_strip_whitespace=True)

    # Acknowledge the warnings and go anyway. Errors are never waivable; a
    # warning is the module saying "this looks wrong" about something a human
    # may know more about than the rule does.
    accept_warnings: bool = False


class ResolveRequest(BaseModel):
    """Record by hand what a platform did with a document.

    For the case a state machine cannot reason its way out of: the adapter
    failed before the platform answered, so the document sits in ``submitted``
    with an outcome nobody knows. Without this the row is stuck forever, and
    the two wrong ways out are both worse - sending it again risks a second
    cleared invoice for one sale, and quietly putting it back to draft loses
    the fact that something was sent.

    What an accountant actually does is log into the portal and look. This
    records what they saw, as an event with their name on it.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    outcome: Literal["cleared", "rejected"]
    authority_identifier: str = Field(default="", max_length=255)
    rejection_code: str = Field(default="", max_length=64)
    rejection_message: str = Field(default="", max_length=2000)
    # Mandatory: a hand-written status change on a fiscal record has to say
    # where the information came from.
    note: str = Field(min_length=1, max_length=1000)


class CancelRequest(BaseModel):
    """Withdraw a document the platform has already accepted."""

    model_config = ConfigDict(str_strip_whitespace=True)

    # Mandatory, and not for tidiness: every platform that accepts a
    # cancellation records why, and six months later the reason is the only
    # part anybody needs.
    reason: str = Field(min_length=1, max_length=1000)


class ClearanceFinding(BaseModel):
    """One validation finding shown beside the document.

    ``key`` is what the reader translates; ``message`` is the English the rule
    wrote and is shown only where a locale has no string for the key yet. The
    same split the cases findings use.
    """

    key: str
    rule_id: str
    severity: str
    message: str
    suggestion: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class DocumentSaveResponse(BaseModel):
    """A saved document plus what validation made of it."""

    document: DocumentResponse
    findings: list[ClearanceFinding] = Field(default_factory=list)


class SubmissionResponse(BaseModel):
    """The result of one round trip to a platform."""

    document: DocumentResponse
    accepted: bool
    # Repeated out of the document so a caller that only reads this envelope
    # still gets the code by name; a rejection code the accountant will be
    # asked about must not be one nesting level away.
    authority_identifier: str = ""
    rejection_code: str = ""
    rejection_message: str = ""
    message: str = ""
    findings: list[ClearanceFinding] = Field(default_factory=list)


class EventResponse(BaseModel):
    """One entry in a document's trail."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    sequence: int
    event_type: str
    from_status: str
    to_status: str
    message: str
    authority_code: str
    raw_response: dict[str, Any]
    actor_id: UUID | None
    created_at: datetime


class CommencementPhaseResponse(BaseModel):
    """One wave of one obligation, with the source the date was read from.

    The provenance travels to the client. A commencement date is something a
    business plans around, and one arriving without a citation cannot be checked
    against the authority that set it.
    """

    obligation: str
    effective_date: str = ""
    scope: str = ""
    threshold: str = ""
    legal_status: str = ""
    source_url: str = ""
    read_date: str = ""
    notes: str = ""


class CountryRegimeResponse(BaseModel):
    """One country's regime as the meta endpoint reports it.

    Everything below ``notes`` was added after the first clients shipped, so all
    of it is defaulted: a reader written against the older shape sees the same
    keys with the same meanings, and a country that states no commencement
    serialises exactly as it did before the field existed.
    """

    country: str
    regime: str
    platform: str
    label: str
    identifier_label: str
    document_format: str
    en16931_profile: str
    profile_fields: list[str]
    document_fields: list[str]
    cancellation_window_days: int | None
    is_cancellable: bool
    correction_mechanism: str
    notes: str
    # ``regime`` names the act that decides the terminal state; this names the
    # class the country belongs to, which is ``hybrid`` when it performs more
    # than one act. Both are reported because they answer different questions.
    regime_class: str = ""
    is_hybrid: bool = False
    additional_regimes: list[str] = Field(default_factory=list)
    cancellation_basis: str = ""
    scope: str = ""
    commencement: list[CommencementPhaseResponse] = Field(default_factory=list)


class AdapterResponse(BaseModel):
    """One installed platform adapter."""

    key: str
    label: str
    countries: list[str]


class MetaResponse(BaseModel):
    """The vocabularies the UI needs to render this module."""

    regimes: list[str] = Field(default_factory=lambda: list(REGIMES))
    # The three acts plus ``hybrid``. Separate from ``regimes`` because a filter
    # offering "hybrid" as a fourth act would ask the API for a terminal state
    # that does not exist.
    regime_classes: list[str] = Field(default_factory=lambda: list(REGIME_CLASSES))
    obligations: list[str] = Field(default_factory=lambda: list(OBLIGATIONS))
    legal_statuses: list[str] = Field(default_factory=lambda: list(LEGAL_STATUSES))
    statuses: list[str] = Field(default_factory=lambda: list(STATUSES))
    event_types: list[str] = Field(default_factory=lambda: list(EVENTS))
    countries: list[CountryRegimeResponse] = Field(default_factory=list)
    adapters: list[AdapterResponse] = Field(default_factory=list)


__all__ = [
    "COUNTRIES",
    "EVENTS",
    "MAX_COUNTRY_FIELDS",
    "STATUSES",
    "AdapterResponse",
    "CancelRequest",
    "ClearanceFinding",
    "CommencementPhaseResponse",
    "CountryRegimeResponse",
    "DocumentCreateRequest",
    "DocumentResponse",
    "DocumentSaveResponse",
    "DocumentUpdateRequest",
    "EventResponse",
    "MetaResponse",
    "ProfileCreateRequest",
    "ProfileResponse",
    "ProfileUpdateRequest",
    "ResolveRequest",
    "SubmissionResponse",
    "SubmitRequest",
]
