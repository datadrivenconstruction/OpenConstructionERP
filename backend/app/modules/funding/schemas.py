# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Public funding Pydantic schemas (request/response models)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_serializer, field_validator

# ── Money serialization helper ──────────────────────────────────────────
#
# Pydantic v2 serializes ``Decimal`` to a JSON *number*, which JavaScript
# truncates to a float. The platform convention is to emit money as a
# plain-decimal string so the wire format is exact and locale-neutral.
# This is the same helper the variations and contracts modules carry, kept
# local for the same reason they keep theirs: a module is a plugin.


def _serialize_money_string(value: Any) -> str | None:
    """Render a Decimal-ish value as a plain-decimal string, or ``None``."""
    if value is None:
        return None
    if not isinstance(value, Decimal):
        try:
            value = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return "0"
    if not value.is_finite():
        return "0"
    return format(value, "f")


# ── Controlled vocabularies ─────────────────────────────────────────────
#
# Written as patterns rather than enums to match the rest of the platform,
# and kept in one block so the frontend has a single place to read them
# from when a picker needs its options.
_AUTHORITY_LEVEL = r"^(supranational|national|regional|municipal)$"
_INSTRUMENT = r"^(grant|loan|repayment_grant|guarantee|tax_relief|equity)$"
_PROGRAMME_STATUS = r"^(draft|open|closed|suspended)$"
_APPLICATION_STATUS = r"^(draft|submitted|in_review|approved|rejected|withdrawn|closed)$"
_DISBURSEMENT_STATUS = r"^(draft|submitted|approved|paid|rejected)$"
_PROOF_KIND = r"^(interim|final)$"
_PROOF_STATUS = r"^(pending|drafting|submitted|accepted|rejected)$"
_OBLIGATION_KIND = (
    r"^(application_deadline|measure_start|disbursement|spend_window"
    r"|interim_report|final_report|retention_end|condition)$"
)
_OBLIGATION_SOURCE = r"^(programme_rule|award_notice|manual)$"
_OBLIGATION_STATUS = r"^(open|done|waived)$"
_ELIGIBILITY = r"^(eligible|partially_eligible|not_eligible|undecided)$"
_ALLOCATION_SOURCE = r"^(estimate|boq|invoice|manual)$"


# ── Programme ───────────────────────────────────────────────────────────


class ProgrammeBase(BaseModel):
    """Fields a caller may set on a funding programme."""

    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(min_length=1, max_length=80)
    name: str = Field(default="", max_length=500)
    summary: str = ""
    authority_name: str = Field(default="", max_length=255)
    authority_level: str = Field(default="national", pattern=_AUTHORITY_LEVEL)
    country: str = Field(default="", max_length=2)
    region_code: str = Field(default="", max_length=20)
    instrument: str = Field(default="grant", pattern=_INSTRUMENT)
    funding_rate_percent: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    min_amount: Decimal = Field(default=Decimal("0"), ge=0)
    max_amount: Decimal = Field(default=Decimal("0"), ge=0)
    currency: str = Field(default="EUR", max_length=3)
    own_share_percent: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    aid_intensity_cap_percent: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    de_minimis: bool = False
    cumulative: bool = True
    requires_application_before_start: bool = True
    application_window_start: str = Field(default="", max_length=40)
    application_window_end: str = Field(default="", max_length=40)
    rolling: bool = True
    proof_of_use_due_days: int = Field(default=0, ge=0, le=3650)
    disbursement_spend_days: int = Field(default=0, ge=0, le=3650)
    retention_years: int = Field(default=0, ge=0, le=50)
    eligible_applicant_types: list[str] = Field(default_factory=list)
    eligible_cost_categories: list[str] = Field(default_factory=list)
    excluded_cost_categories: list[str] = Field(default_factory=list)
    status: str = Field(default="open", pattern=_PROGRAMME_STATUS)
    source_url: str = Field(default="", max_length=1000)
    last_verified_on: str = Field(default="", max_length=40)
    notes: str = ""


class ProgrammeCreate(ProgrammeBase):
    """A new programme entry."""


class ProgrammeUpdate(BaseModel):
    """A partial change to a programme. Every field is optional."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, max_length=500)
    summary: str | None = None
    authority_name: str | None = Field(default=None, max_length=255)
    authority_level: str | None = Field(default=None, pattern=_AUTHORITY_LEVEL)
    region_code: str | None = Field(default=None, max_length=20)
    instrument: str | None = Field(default=None, pattern=_INSTRUMENT)
    funding_rate_percent: Decimal | None = Field(default=None, ge=0, le=100)
    min_amount: Decimal | None = Field(default=None, ge=0)
    max_amount: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=3)
    own_share_percent: Decimal | None = Field(default=None, ge=0, le=100)
    aid_intensity_cap_percent: Decimal | None = Field(default=None, ge=0, le=100)
    de_minimis: bool | None = None
    cumulative: bool | None = None
    requires_application_before_start: bool | None = None
    application_window_start: str | None = Field(default=None, max_length=40)
    application_window_end: str | None = Field(default=None, max_length=40)
    rolling: bool | None = None
    proof_of_use_due_days: int | None = Field(default=None, ge=0, le=3650)
    disbursement_spend_days: int | None = Field(default=None, ge=0, le=3650)
    retention_years: int | None = Field(default=None, ge=0, le=50)
    eligible_applicant_types: list[str] | None = None
    eligible_cost_categories: list[str] | None = None
    excluded_cost_categories: list[str] | None = None
    status: str | None = Field(default=None, pattern=_PROGRAMME_STATUS)
    source_url: str | None = Field(default=None, max_length=1000)
    last_verified_on: str | None = Field(default=None, max_length=40)
    notes: str | None = None


class ProgrammeOut(ProgrammeBase):
    """A programme as the API returns it."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    pack_id: str = ""
    created_at: datetime
    updated_at: datetime

    @field_serializer("min_amount", "max_amount", when_used="json")
    def _money(self, value: Decimal) -> str | None:
        return _serialize_money_string(value)


# ── Application ─────────────────────────────────────────────────────────


class ApplicationBase(BaseModel):
    """Fields a caller may set on an application."""

    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(min_length=1, max_length=50)
    title: str = Field(default="", max_length=500)
    applicant_name: str = Field(default="", max_length=255)
    applicant_type: str = Field(default="", max_length=60)
    eligible_cost_base: Decimal = Field(default=Decimal("0"), ge=0)
    requested_amount: Decimal = Field(default=Decimal("0"), ge=0)
    own_share_amount: Decimal = Field(default=Decimal("0"), ge=0)
    currency: str = Field(default="EUR", max_length=3)
    submitted_on: str = Field(default="", max_length=40)
    decision_expected_on: str = Field(default="", max_length=40)
    measure_start_on: str = Field(default="", max_length=40)
    early_start_approved: bool = False
    early_start_reference: str = Field(default="", max_length=120)
    responsible_user_id: str | None = Field(default=None, max_length=36)
    linked_estimate_id: UUID | None = None
    linked_schedule_id: UUID | None = None


class ApplicationCreate(ApplicationBase):
    """A new application against one programme."""

    project_id: UUID
    programme_id: UUID


class ReceiptRecord(BaseModel):
    """Money arriving against a draw.

    A body rather than query parameters, because one of the two fields is an
    amount and a money value in a URL is a money value in an access log.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    received_on: str = Field(min_length=10, max_length=40)
    amount_received: Decimal | None = Field(default=None, ge=0)


class ApplicationUpdate(BaseModel):
    """A partial change to an application."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, max_length=500)
    applicant_name: str | None = Field(default=None, max_length=255)
    applicant_type: str | None = Field(default=None, max_length=60)
    status: str | None = Field(default=None, pattern=_APPLICATION_STATUS)
    eligible_cost_base: Decimal | None = Field(default=None, ge=0)
    requested_amount: Decimal | None = Field(default=None, ge=0)
    own_share_amount: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=3)
    submitted_on: str | None = Field(default=None, max_length=40)
    decision_expected_on: str | None = Field(default=None, max_length=40)
    measure_start_on: str | None = Field(default=None, max_length=40)
    early_start_approved: bool | None = None
    early_start_reference: str | None = Field(default=None, max_length=120)
    responsible_user_id: str | None = Field(default=None, max_length=36)
    linked_estimate_id: UUID | None = None
    linked_schedule_id: UUID | None = None


class AwardRecord(BaseModel):
    """The decision an authority sent back, recorded in one call.

    Kept separate from ``ApplicationUpdate`` because recording an award is a
    different act from editing a draft: it sets the period every later date
    is measured against, it carries its own permission, and it is the point
    at which the module generates the deadlines it will then hold people to.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    approved: bool
    decided_on: str = Field(default="", max_length=40)
    award_reference: str = Field(default="", max_length=120)
    approved_amount: Decimal = Field(default=Decimal("0"), ge=0)
    award_period_start: str = Field(default="", max_length=40)
    award_period_end: str = Field(default="", max_length=40)
    conditions: str = ""
    rejection_reason: str = ""


class ApplicationOut(ApplicationBase):
    """An application as the API returns it."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    programme_id: UUID
    status: str
    decided_on: str = ""
    award_reference: str = ""
    approved_amount: Decimal = Decimal("0")
    award_period_start: str = ""
    award_period_end: str = ""
    conditions: str = ""
    rejection_reason: str = ""
    created_at: datetime
    updated_at: datetime

    @field_serializer(
        "eligible_cost_base",
        "requested_amount",
        "own_share_amount",
        "approved_amount",
        when_used="json",
    )
    def _money(self, value: Decimal) -> str | None:
        return _serialize_money_string(value)


# ── Disbursement ────────────────────────────────────────────────────────


class DisbursementBase(BaseModel):
    """Fields a caller may set on a disbursement request."""

    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(default="", max_length=50)
    period_from: str = Field(default="", max_length=40)
    period_to: str = Field(default="", max_length=40)
    requested_on: str = Field(default="", max_length=40)
    amount_requested: Decimal = Field(default=Decimal("0"), ge=0)
    invoice_ids: list[UUID] = Field(default_factory=list)
    notes: str = ""


class DisbursementCreate(DisbursementBase):
    """A new draw against an award."""


class DisbursementUpdate(BaseModel):
    """A partial change to a disbursement request."""

    model_config = ConfigDict(str_strip_whitespace=True)

    code: str | None = Field(default=None, max_length=50)
    period_from: str | None = Field(default=None, max_length=40)
    period_to: str | None = Field(default=None, max_length=40)
    requested_on: str | None = Field(default=None, max_length=40)
    approved_on: str | None = Field(default=None, max_length=40)
    received_on: str | None = Field(default=None, max_length=40)
    amount_requested: Decimal | None = Field(default=None, ge=0)
    amount_approved: Decimal | None = Field(default=None, ge=0)
    amount_received: Decimal | None = Field(default=None, ge=0)
    status: str | None = Field(default=None, pattern=_DISBURSEMENT_STATUS)
    invoice_ids: list[UUID] | None = None
    notes: str | None = None


class DisbursementOut(DisbursementBase):
    """A disbursement as the API returns it."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    application_id: UUID
    sequence: int
    approved_on: str = ""
    received_on: str = ""
    spend_deadline_on: str = ""
    amount_approved: Decimal = Decimal("0")
    amount_received: Decimal = Decimal("0")
    status: str
    created_at: datetime
    updated_at: datetime

    @field_serializer("amount_requested", "amount_approved", "amount_received", when_used="json")
    def _money(self, value: Decimal) -> str | None:
        return _serialize_money_string(value)


# ── Proof of use ────────────────────────────────────────────────────────


class ProofOfUseBase(BaseModel):
    """Fields a caller may set on a proof of use."""

    model_config = ConfigDict(str_strip_whitespace=True)

    kind: str = Field(default="final", pattern=_PROOF_KIND)
    due_on: str = Field(default="", max_length=40)
    narrative_report: str = ""
    total_eligible_spent: Decimal = Field(default=Decimal("0"), ge=0)
    total_funding_used: Decimal = Field(default=Decimal("0"), ge=0)
    total_own_share: Decimal = Field(default=Decimal("0"), ge=0)
    voucher_count: int = Field(default=0, ge=0)


class ProofOfUseCreate(ProofOfUseBase):
    """A new proof of use, interim or final."""


class ProofOfUseUpdate(BaseModel):
    """A partial change to a proof of use."""

    model_config = ConfigDict(str_strip_whitespace=True)

    kind: str | None = Field(default=None, pattern=_PROOF_KIND)
    due_on: str | None = Field(default=None, max_length=40)
    submitted_on: str | None = Field(default=None, max_length=40)
    accepted_on: str | None = Field(default=None, max_length=40)
    status: str | None = Field(default=None, pattern=_PROOF_STATUS)
    narrative_report: str | None = None
    total_eligible_spent: Decimal | None = Field(default=None, ge=0)
    total_funding_used: Decimal | None = Field(default=None, ge=0)
    total_own_share: Decimal | None = Field(default=None, ge=0)
    voucher_count: int | None = Field(default=None, ge=0)
    findings: str | None = None


class ProofOfUseOut(ProofOfUseBase):
    """A proof of use as the API returns it."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    application_id: UUID
    submitted_on: str = ""
    accepted_on: str = ""
    status: str
    findings: str = ""
    retention_until: str = ""
    created_at: datetime
    updated_at: datetime

    @field_serializer("total_eligible_spent", "total_funding_used", "total_own_share", when_used="json")
    def _money(self, value: Decimal) -> str | None:
        return _serialize_money_string(value)


# ── Obligation ──────────────────────────────────────────────────────────


class ObligationBase(BaseModel):
    """Fields a caller may set on an obligation."""

    model_config = ConfigDict(str_strip_whitespace=True)

    kind: str = Field(default="condition", pattern=_OBLIGATION_KIND)
    title: str = Field(default="", max_length=500)
    detail: str = ""
    due_on: str = Field(default="", max_length=40)
    source: str = Field(default="manual", pattern=_OBLIGATION_SOURCE)
    source_reference: str = Field(default="", max_length=255)
    responsible_user_id: str | None = Field(default=None, max_length=36)


class ObligationCreate(ObligationBase):
    """A new obligation, usually typed in rather than derived."""


class ObligationUpdate(BaseModel):
    """A partial change to an obligation."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, max_length=500)
    detail: str | None = None
    due_on: str | None = Field(default=None, max_length=40)
    responsible_user_id: str | None = Field(default=None, max_length=36)
    status: str | None = Field(default=None, pattern=_OBLIGATION_STATUS)
    completed_on: str | None = Field(default=None, max_length=40)


class ObligationOut(ObligationBase):
    """An obligation as the API returns it.

    ``title`` and ``detail`` are English. They are written by the server when
    it derives a deadline from a programme's terms, which makes them data by
    the time anyone could translate them, and this platform ships in 42
    languages. So the payload also carries the same two sentences in the form
    that can be translated, and those are the contract:

    * ``title_key`` and ``detail_key`` are message keys.
    * ``detail_params`` holds the values ``detail_key`` interpolates.

    Render the keys and ignore the prose. The prose is kept for a caller with
    no message bundle, and for the one case where it is not translatable at
    all: an obligation somebody typed carries their own words, both keys come
    back empty, and ``title`` is then the only right answer.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    application_id: UUID
    status: str
    completed_on: str = ""
    # Not a column. "Open and the due date has passed", worked out at read
    # time so a server that was switched off over a weekend does not report
    # a deadline as still comfortable on Monday.
    overdue: bool = False
    # Not a column either: ``kind`` is an enum and the key is built from it.
    # Empty when the title is somebody's own words rather than a derived
    # sentence, which is how a caller tells the two apart without having to
    # know what ``source`` implies.
    title_key: str = ""
    # Stored, because one kind produces two different sentences: a retention
    # deadline counted from the end of the award period reads differently
    # from the same deadline recounted from the day the proof of use was
    # accepted. A caller must not have to guess which one it is holding.
    detail_key: str = ""
    # The values ``detail_key`` interpolates, plus the references that say
    # which row the sentence is about - the sequence number of the draw a
    # spend window belongs to, which the prose spells out and the key does
    # not. Not typed more tightly than this on purpose: a day count is an
    # integer, a programme code is a string, and a caller hands the whole
    # object to its own interpolator.
    detail_params: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    @field_validator("detail_key", "detail_params", mode="before")
    @classmethod
    def _absent_reads_as_empty(cls, value: Any, info: ValidationInfo) -> Any:
        """Treat a missing key or parameter set as an empty one, not an error.

        Both columns are newer than the rows that have to be read through
        them, and on a database that reached them through the boot heal rather
        than the migration the two did not arrive alike. Measured on such a
        database: ``detail_key`` is NOT NULL with ``DEFAULT ''``, while
        ``detail_params`` is nullable with no default at all. The model is
        what splits them. ``default=""`` is a scalar the heal can render into
        DDL, so every existing row was given an empty string; ``default=dict``
        is a callable it cannot render, so that column arrived without a
        default, and a column added without one is nullable whatever the model
        declares. Every row predating the change therefore reads back with a
        real ``detail_key`` and a ``None`` ``detail_params``.

        ``detail_key`` is coerced as well. On the shape measured here it is
        never ``None``, but that is a property of how this database was built
        rather than of the model, and an install that took the migration, or
        any later change to that default, moves the line.

        Without this, ``model_validate`` raises on the first such row and the
        whole deadline list answers 500 - which is what it did: the summary
        endpoint counted two open deadlines while the list beside it said
        there were none, because only one of the two reads obligation rows
        through this model.

        An empty key means the same thing as an empty key on a hand written
        obligation: there is nothing to translate, render the prose in
        ``detail``. That is already the contract, so an old row lands in the
        branch built for it rather than in an error.
        """
        if value is not None:
            return value
        return {} if info.field_name == "detail_params" else ""


# ── Cost allocation ─────────────────────────────────────────────────────


class CostAllocationBase(BaseModel):
    """Fields a caller may set on a cost allocation line."""

    model_config = ConfigDict(str_strip_whitespace=True)

    cost_group: str = Field(default="", max_length=40)
    description: str = Field(default="", max_length=500)
    amount: Decimal = Field(default=Decimal("0"), ge=0)
    eligible_amount: Decimal = Field(default=Decimal("0"), ge=0)
    eligibility: str = Field(default="undecided", pattern=_ELIGIBILITY)
    reason: str = ""
    source_kind: str = Field(default="manual", pattern=_ALLOCATION_SOURCE)
    source_ref_id: UUID | None = None


class CostAllocationCreate(CostAllocationBase):
    """A new cost allocation line."""


class CostAllocationUpdate(BaseModel):
    """A partial change to a cost allocation line."""

    model_config = ConfigDict(str_strip_whitespace=True)

    cost_group: str | None = Field(default=None, max_length=40)
    description: str | None = Field(default=None, max_length=500)
    amount: Decimal | None = Field(default=None, ge=0)
    eligible_amount: Decimal | None = Field(default=None, ge=0)
    eligibility: str | None = Field(default=None, pattern=_ELIGIBILITY)
    reason: str | None = None
    source_kind: str | None = Field(default=None, pattern=_ALLOCATION_SOURCE)
    source_ref_id: UUID | None = None


class CostAllocationOut(CostAllocationBase):
    """A cost allocation line as the API returns it."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    application_id: UUID
    created_at: datetime
    updated_at: datetime

    @field_serializer("amount", "eligible_amount", when_used="json")
    def _money(self, value: Decimal) -> str | None:
        return _serialize_money_string(value)


# ── Rollups ─────────────────────────────────────────────────────────────


class ApplicationSummary(BaseModel):
    """What one application stands at, in the numbers people ask for.

    Every figure here is derived. None of it is stored, because each part is
    stored somewhere already and a second copy would be the one that is
    stale in the screenshot somebody forwards to an auditor.
    """

    application_id: UUID
    currency: str = "EUR"
    approved_amount: Decimal = Decimal("0")
    requested_amount: Decimal = Decimal("0")
    drawn_amount: Decimal = Decimal("0")
    received_amount: Decimal = Decimal("0")
    outstanding_amount: Decimal = Decimal("0")
    eligible_cost_base: Decimal = Decimal("0")
    allocated_amount: Decimal = Decimal("0")
    allocated_eligible_amount: Decimal = Decimal("0")
    own_share_required: Decimal = Decimal("0")
    own_share_recorded: Decimal = Decimal("0")
    effective_funding_rate_percent: Decimal = Decimal("0")
    obligations_open: int = 0
    obligations_overdue: int = 0
    next_due_on: str = ""
    # ``next_due_title`` is the obligation's own title and carries the same
    # English the obligation does. ``next_due_kind`` is the enum behind it,
    # so a caller can name the next deadline in its reader's language the
    # same way it names the deadline list. Empty when nothing is due.
    next_due_title: str = ""
    next_due_kind: str = ""
    # The message key for ``next_due_title``, decided exactly as the deadline
    # list decides it: by who wrote the title. Empty when the words are
    # somebody's own, and then ``next_due_title`` is the right thing to show.
    #
    # ``next_due_kind`` does not answer that question, which is why this field
    # exists beside it. A condition copied out of an award notice is typed by a
    # person and a final report deadline is written by the server, and both can
    # carry any kind, so a caller reading the kind alone either translates away
    # a note somebody wrote or leaves the server's English on the page.
    next_due_title_key: str = ""
    # What the title names that the key does not interpolate: the sequence
    # number of the draw a spend window belongs to. Kept out of the key on
    # purpose - the same key labels the group a deadline belongs to - so a
    # caller renders the key and attaches these the way its own screen
    # attaches a reference. Empty for every other kind.
    next_due_title_params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("next_due_title_params", mode="before")
    @classmethod
    def _absent_params_read_as_empty(cls, value: Any) -> Any:
        """Treat a missing parameter set as an empty one, not an error.

        The values come from an obligation's ``detail_params``, which is newer
        than the table it sits on and arrives nullable on an installation that
        reached it through the boot heal rather than the migration. The service
        already turns that ``None`` into an empty dict, so this is the second
        of two guards rather than the only one; it is here because the first
        one is a different file, and a summary that raises takes down the one
        endpoint that stayed up the last time these columns caught us out.
        """
        return {} if value is None else value

    @field_serializer(
        "approved_amount",
        "requested_amount",
        "drawn_amount",
        "received_amount",
        "outstanding_amount",
        "eligible_cost_base",
        "allocated_amount",
        "allocated_eligible_amount",
        "own_share_required",
        "own_share_recorded",
        "effective_funding_rate_percent",
        when_used="json",
    )
    def _money(self, value: Decimal) -> str | None:
        return _serialize_money_string(value)


class ProjectFundingSummary(BaseModel):
    """Every application on one project, added up.

    ``aid_intensity_percent`` is the number a state-aid auditor computes
    first: everything public, over the eligible base. It is reported even
    when no programme declares a cap, because the cap can arrive later and
    the applicant is expected to have known the figure all along.
    """

    project_id: UUID
    currency: str = "EUR"
    application_count: int = 0
    approved_count: int = 0
    approved_amount: Decimal = Decimal("0")
    received_amount: Decimal = Decimal("0")
    outstanding_amount: Decimal = Decimal("0")
    eligible_cost_base: Decimal = Decimal("0")
    aid_intensity_percent: Decimal = Decimal("0")
    aid_intensity_cap_percent: Decimal = Decimal("0")
    obligations_open: int = 0
    obligations_overdue: int = 0

    @field_serializer(
        "approved_amount",
        "received_amount",
        "outstanding_amount",
        "eligible_cost_base",
        "aid_intensity_percent",
        "aid_intensity_cap_percent",
        when_used="json",
    )
    def _money(self, value: Decimal) -> str | None:
        return _serialize_money_string(value)
