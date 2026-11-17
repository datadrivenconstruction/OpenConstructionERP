# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Sealed estimate request and response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

BasisKind = Literal["tender", "award", "negotiated"]
DepositMode = Literal["platform", "external"]
OpeningReason = Literal["variation", "claim", "dispute", "final_account", "audit", "other"]
BasisMethod = Literal["original_basis", "cost_plus_markup", "agreed", "daywork"]


class Finding(BaseModel):
    """One validation result."""

    rule_id: str
    code: str = ""
    severity: str
    message: str


class Policy(BaseModel):
    """The market profile a project's seals follow."""

    profile: str
    enabled: bool
    term: str
    methods: list[str]
    require_breakdown: bool
    require_receipt: bool
    require_both_parties: bool
    internal_read: bool
    retention_years: int
    on_account_percent: int | None = None
    attachment_presets: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    tsa_configured: bool = False
    has_contract: bool = False


class SealCheck(BaseModel):
    """One pre-seal check line."""

    code: str
    status: Literal["ok", "warning", "error", "info"]
    message: str
    blocking: bool = False


class SealPreview(BaseModel):
    """What sealing this bill would produce, with the checks; nothing is written."""

    project_id: uuid.UUID
    source_boq_id: uuid.UUID
    contract_id: uuid.UUID | None
    label: str
    currency: str
    seal_total: str
    award_value: str | None
    positions: int
    with_breakdown: int
    markup_names: list[str]
    checks: list[SealCheck]
    can_seal: bool
    policy: Policy


class SealCreate(BaseModel):
    """Seal a bill."""

    source_boq_id: uuid.UUID
    contract_id: uuid.UUID | None = None
    basis_kind: BasisKind = "award"
    label: str = Field(default="", max_length=255)
    deposit_mode: DepositMode = "platform"
    request_receipt: bool = False
    attachment_document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)


class SupersedeCreate(SealCreate):
    """Seal again, naming the seal this one corrects."""

    reason: str = Field(min_length=3, max_length=2000)


class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID | None
    name: str
    kind: str
    file_hash: str


class ReceiptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    signing_session_id: uuid.UUID | None
    external_reference: str
    receipt_document_id: uuid.UUID | None
    acknowledged_hash: str
    status: str
    signed_at: datetime | None
    created_at: datetime


class ExternalReceiptCreate(BaseModel):
    """Record a receipt handed over on paper or media."""

    external_reference: str = Field(min_length=1, max_length=255)
    receipt_document_id: uuid.UUID | None = None


class SealSummary(BaseModel):
    """A seal as listed in the register."""

    id: uuid.UUID
    project_id: uuid.UUID
    contract_id: uuid.UUID | None
    contract_label: str = ""
    source_boq_id: uuid.UUID | None
    label: str
    basis_kind: str
    status: str
    deposit_mode: str
    profile: str
    sealed_at: datetime
    sealed_by_name: str = ""
    award_total: str
    currency: str
    content_hash: str
    tsa_authority: str | None = None
    receipt_status: str = "none"
    openings: int = 0
    positions: int = 0
    with_breakdown: int = 0
    supersedes_id: uuid.UUID | None = None
    superseded_by: dict[str, Any] | None = None
    last_verified_at: datetime | None = None
    last_verified_ok: bool | None = None


class SealDetail(SealSummary):
    """A seal with its receipts, files, findings and whether the caller may read it."""

    attachments: list[AttachmentOut] = Field(default_factory=list)
    receipts: list[ReceiptOut] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    can_read_contents: bool = False
    open_opening_id: uuid.UUID | None = None
    retention_until: str | None = None
    supersede_reason: str = ""
    policy: Policy


class SealList(BaseModel):
    items: list[SealSummary]
    total: int


class SealKpis(BaseModel):
    seals: int
    awaiting_receipt: int
    openings_in_progress: int
    openings_this_year: int
    positions_without_breakdown: int


class VerifyResult(BaseModel):
    seal_id: uuid.UUID
    ok: bool
    sealed_hash: str
    actual_hash: str
    verified_at: datetime


class Attendee(BaseModel):
    user_id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=255)
    organisation: str = Field(default="", max_length=255)
    role: str = Field(default="", max_length=120)
    side: Literal["internal", "counterparty"] = "internal"
    present: bool = False


class OpeningCreate(BaseModel):
    """Request an opening."""

    reason: OpeningReason
    reference_type: str = Field(default="", max_length=40)
    reference_id: uuid.UUID | None = None
    reference_label: str = Field(default="", max_length=255)
    scope: Literal["full", "positions"] = "full"
    scope_ordinals: list[str] = Field(default_factory=list, max_length=500)
    attendees: list[Attendee] = Field(default_factory=list, max_length=50)
    one_party_reason: str = Field(default="", max_length=2000)


class OpeningStart(BaseModel):
    """Tick attendance at the meeting; the server then re-hashes."""

    present: list[str] = Field(default_factory=list, description="Attendee names present")


class OpeningClose(BaseModel):
    minutes_document_id: uuid.UUID | None = None


class OpeningOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    seal_id: uuid.UUID
    seal_label: str = ""
    requested_by: uuid.UUID | None
    requested_by_name: str = ""
    reason: str
    reference_type: str
    reference_id: uuid.UUID | None
    reference_label: str
    scope: str
    scope_ordinals: list[str]
    attendees: list[dict[str, Any]]
    one_party_reason: str
    status: str
    requested_at: datetime
    opened_at: datetime | None
    closed_at: datetime | None
    hash_check: str | None
    hash_seen: str | None
    minutes_document_id: uuid.UUID | None
    positions_viewed: list[str]
    findings: list[Finding] = Field(default_factory=list)


class OpeningList(BaseModel):
    items: list[OpeningOut]
    total: int


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    seal_id: uuid.UUID
    opening_id: uuid.UUID | None
    event_type: str
    actor_id: uuid.UUID | None
    actor_name: str
    actor_organisation: str
    detail: dict[str, Any]
    created_at: datetime


class EventList(BaseModel):
    items: list[EventOut]
    total: int


class ContentsOut(BaseModel):
    """The sealed payload, returned only to a caller allowed to read it."""

    seal_id: uuid.UUID
    content_hash: str
    payload: dict[str, Any]
    scope_ordinals: list[str] | None = None


class ResourceChange(BaseModel):
    code: str = Field(max_length=120)
    consumption: Decimal | None = None
    unit_cost: Decimal | None = None
    note: str = Field(default="", max_length=2000)


class ResourceAddition(BaseModel):
    kind: str = Field(default="other", max_length=40)
    code: str = Field(default="", max_length=120)
    description: str = Field(min_length=1, max_length=500)
    unit: str = Field(default="", max_length=20)
    consumption: Decimal = Decimal("1")
    unit_cost: Decimal = Decimal("0")
    price_date: str = Field(default="", max_length=40)
    quote_ref: str = Field(default="", max_length=255)
    note: str = Field(default="", max_length=2000)


class DeriveRequest(BaseModel):
    """Price one sealed position for a change; nothing is written."""

    position_ordinal: str = Field(min_length=1, max_length=50)
    quantity: Decimal | None = None
    changes: list[ResourceChange] = Field(default_factory=list, max_length=200)
    additions: list[ResourceAddition] = Field(default_factory=list, max_length=200)
    removals: list[str] = Field(default_factory=list, max_length=200)
    current_unit_costs: dict[str, Decimal] = Field(default_factory=dict)
    agreed_rate: Decimal | None = None


class DeriveResult(BaseModel):
    seal_id: uuid.UUID
    result: dict[str, Any]
    findings: list[Finding]
    methods_order: list[str]
    citations: list[str]


class DerivationCreate(DeriveRequest):
    """Record a priced change position, optionally writing it into the variation's bill."""

    variation_request_id: uuid.UUID | None = None
    change_order_item_id: uuid.UUID | None = None
    reference_label: str = Field(default="", max_length=255)
    description: str = Field(default="", max_length=2000)
    basis_method: BasisMethod | None = None
    write_to_variation_bill: bool = False


class DerivationChoose(BaseModel):
    basis_method: BasisMethod


class DerivationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    seal_id: uuid.UUID
    position_ordinal: str
    variation_request_id: uuid.UUID | None
    change_order_item_id: uuid.UUID | None
    reference_label: str
    description: str
    quantity: Decimal
    inputs: dict[str, Any]
    result: dict[str, Any]
    basis_method: str | None
    chosen_rate: Decimal | None
    variation_position_id: uuid.UUID | None
    created_at: datetime
    findings: list[Finding] = Field(default_factory=list)


class DerivationList(BaseModel):
    items: list[DerivationOut]
    total: int


class ChangeOrderRateFill(BaseModel):
    """Fill a change order line's original rate from the seal."""

    position_ordinal: str = Field(min_length=1, max_length=50)


class ChangeOrderRateFilled(BaseModel):
    change_order_item_id: uuid.UUID
    original_rate: Decimal
    seal_id: uuid.UUID
    position_ordinal: str
