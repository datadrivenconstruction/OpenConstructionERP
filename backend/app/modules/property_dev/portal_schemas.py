"""Pydantic schemas for the buyer self-service portal.

Kept in a separate module from the main ``property_dev/schemas.py`` so
the buyer-portal surface area (which is PUBLIC; no internal JWT auth)
is easy to audit in isolation.

Convention reminders (mirrors the rest of property_dev):
* ``Decimal`` money fields serialize as plain-decimal strings (R7 fix,
  see ``_serialize_money_string`` in ``schemas.py``).
* ``metadata_`` columns surface as ``metadata`` on the wire via
  ``validation_alias='metadata_'``.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.modules.property_dev.schemas import _serialize_money_string

# ── Issuance (internal, JWT-authed) ─────────────────────────────────────


class PortalTokenIssueRequest(BaseModel):
    """Sales-manager request body to mint a fresh buyer-portal link.

    Exactly ONE of ``reservation_id`` / ``sales_contract_id`` is
    required; both can be set when the buyer has progressed from
    reservation to SPA on the same plot.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    buyer_id: UUID
    reservation_id: UUID | None = None
    sales_contract_id: UUID | None = None


class PortalTokenResponse(BaseModel):
    """The persisted PortalToken row (audit + revocation view)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    buyer_id: UUID
    reservation_id: UUID | None = None
    sales_contract_id: UUID | None = None
    jwt_id: str
    issued_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None
    last_used_ip: str | None = None
    issued_by_user_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class PortalTokenIssueResponse(BaseModel):
    """Response from ``POST /issue/`` — includes the one-time token URL.

    The full URL is rendered once and never again — the JWT is not
    persisted in plaintext (only its ``jti`` lands on the audit row).
    """

    token: str
    expires_at: datetime
    portal_url: str
    row: PortalTokenResponse


# ── Verification (public) ──────────────────────────────────────────────


class PortalVerifyRequest(BaseModel):
    """``POST /verify/`` body — the magic-link token from the URL."""

    model_config = ConfigDict(str_strip_whitespace=True)

    token: str = Field(..., min_length=20, max_length=4096)


class PortalVerifyResponse(BaseModel):
    """Minimal buyer summary — what the portal landing page renders."""

    buyer_id: UUID
    buyer_full_name: str
    reservation_id: UUID | None = None
    sales_contract_id: UUID | None = None
    scope_summary: str  # human-readable label (e.g. "reservation + SPA")


# ── Overview (public via token) ────────────────────────────────────────


class PortalReservationCard(BaseModel):
    """Compact reservation card for the portal landing page."""

    id: UUID
    reservation_number: str
    plot_id: UUID
    plot_number: str
    plot_area_m2: Decimal = Decimal("0")
    plot_address: str = ""
    deposit_amount: Decimal = Decimal("0")
    currency: str = ""
    status: str = ""
    cooling_off_until: str | None = None
    expires_at: str | None = None
    signed_on: datetime | None = None  # alias of deposit_paid_at

    @field_serializer("deposit_amount", "plot_area_m2", when_used="json")
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


class PortalSalesContractCard(BaseModel):
    """Compact SPA card for the portal landing page."""

    id: UUID
    contract_number: str
    plot_id: UUID
    signing_date: str | None = None
    total_value: Decimal = Decimal("0")
    currency: str = ""
    status: str = ""

    @field_serializer("total_value", when_used="json")
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


class PortalInstalmentRow(BaseModel):
    """One row of the payment-schedule table."""

    id: UUID
    sequence: int
    milestone_label: str = ""
    due_date: str | None = None
    amount: Decimal = Decimal("0")
    amount_paid: Decimal = Decimal("0")
    amount_outstanding: Decimal = Decimal("0")
    status: Literal["pending", "due", "overdue", "paid", "waived", "cancelled"] = "pending"
    paid_at: datetime | None = None
    currency: str = ""

    @field_serializer(
        "amount",
        "amount_paid",
        "amount_outstanding",
        when_used="json",
    )
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


class PortalDocumentRow(BaseModel):
    """A signed/delivered document the buyer can download.

    ``download_url`` is scoped to the magic-link's TTL — when the
    token expires, the URL stops working.
    """

    id: UUID
    title: str
    doc_type: str  # "spa" | "handover_doc:<type>" | ...
    delivered_at: str | None = None
    download_url: str  # already includes the token


class PortalKycRequest(BaseModel):
    """Outstanding KYC document the buyer is asked to upload."""

    code: str  # e.g. "passport" | "address_proof" | "income_statement"
    label: str
    description: str = ""
    is_uploaded: bool = False


class PortalOverviewResponse(BaseModel):
    """Everything the buyer-portal landing page needs in one round-trip."""

    buyer_id: UUID
    buyer_full_name: str
    buyer_email: str
    buyer_language: str = "en"
    development_name: str = ""
    reservation: PortalReservationCard | None = None
    sales_contract: PortalSalesContractCard | None = None
    payment_schedule_total: Decimal = Decimal("0")
    payment_schedule_paid: Decimal = Decimal("0")
    payment_schedule_outstanding: Decimal = Decimal("0")
    payment_schedule_currency: str = ""
    instalments: list[PortalInstalmentRow] = Field(default_factory=list)
    documents: list[PortalDocumentRow] = Field(default_factory=list)
    kyc_requests: list[PortalKycRequest] = Field(default_factory=list)

    @field_serializer(
        "payment_schedule_total",
        "payment_schedule_paid",
        "payment_schedule_outstanding",
        when_used="json",
    )
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


# ── KYC upload (public via token) ──────────────────────────────────────

# These are KYC document-type codes the buyer is allowed to upload via
# the portal. Free-string at the storage layer (metadata.kyc_code on the
# stored document) so we don't need a migration each time a jurisdiction
# adds a doc type — the validation is in the schema.
_KYC_DOC_TYPE_PATTERN = (
    r"^(passport|national_id|address_proof|income_statement|"
    r"bank_statement|tax_return|source_of_funds|aml_questionnaire|"
    r"power_of_attorney|other)$"
)


class PortalKycUploadResponse(BaseModel):
    """Returned after a successful KYC document upload."""

    document_id: UUID
    document_type: str
    accepted_at: datetime
    storage_path: str  # diagnostic — buyer doesn't act on this


# ── Contact agent (public via token) ───────────────────────────────────


class PortalContactAgentRequest(BaseModel):
    """Buyer sends a free-form message to the assigned sales agent."""

    model_config = ConfigDict(str_strip_whitespace=True)

    message: str = Field(..., min_length=1, max_length=2000)
    callback_phone: str | None = Field(default=None, max_length=40)


class PortalContactAgentResponse(BaseModel):
    """Confirmation that the message was filed."""

    activity_id: UUID
    accepted_at: datetime


__all__ = [
    "PortalContactAgentRequest",
    "PortalContactAgentResponse",
    "PortalDocumentRow",
    "PortalInstalmentRow",
    "PortalKycRequest",
    "PortalKycUploadResponse",
    "PortalOverviewResponse",
    "PortalReservationCard",
    "PortalSalesContractCard",
    "PortalTokenIssueRequest",
    "PortalTokenIssueResponse",
    "PortalTokenResponse",
    "PortalVerifyRequest",
    "PortalVerifyResponse",
    "_KYC_DOC_TYPE_PATTERN",
]
