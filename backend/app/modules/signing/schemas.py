# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pydantic schemas for the e-signature registry.

None of these carry cryptographic material. There is deliberately no field for a
private key, a certificate file, a password or any credential - the API records
attestations and certificate *metadata* only, and rejects anything else by
simply not modelling it.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ── Vocabularies (open-ended in the DB; validated at the edge) ─────────
#
# A signature is described by its legal *capability*, never by a vendor. These
# are the jurisdiction-neutral families every regional scheme maps onto:
#   - qualified_electronic : highest tier (e.g. EU eIDAS QES, RU УКЭП/GOST)
#   - advanced_electronic  : identity-bound, tamper-evident advanced signature
#   - simple_electronic    : a basic electronic signature / click-to-sign
#   - digital_certificate  : a certificate-backed signature (e.g. India DSC)
CAPABILITIES: tuple[str, ...] = (
    "qualified_electronic",
    "advanced_electronic",
    "simple_electronic",
    "digital_certificate",
)

# Full session lifecycle. Only draft / awaiting_signatures may be set by a
# caller; the rest are derived from the recorded attestations and the expiry.
SESSION_STATUSES: tuple[str, ...] = (
    "draft",
    "awaiting_signatures",
    "partially_signed",
    "fully_signed",
    "declined",
    "expired",
)
_SETTABLE_SESSION_STATUSES: tuple[str, ...] = ("draft", "awaiting_signatures")

SIGNATURE_STATUSES: tuple[str, ...] = ("signed", "declined")

_CAPABILITY_PATTERN = "^(" + "|".join(CAPABILITIES) + ")$"
_SETTABLE_STATUS_PATTERN = "^(" + "|".join(_SETTABLE_SESSION_STATUSES) + ")$"


# ── Signatory map entry ────────────────────────────────────────────────


class SignatoryEntry(BaseModel):
    """One expected signatory in a session's ``signatory_map``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=255)
    role: str = Field(..., min_length=1, max_length=64)
    required: bool = Field(
        default=True,
        description="Whether the session needs this signatory to reach fully_signed.",
    )


# ── Session create / update ────────────────────────────────────────────


class SigningSessionCreate(BaseModel):
    """Body for ``POST /v1/signing/sessions/``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    document_ref: str = Field(..., min_length=1, max_length=512)
    document_content_hash: str = Field(..., min_length=1, max_length=128)
    provider_capability: str = Field(default="simple_electronic", pattern=_CAPABILITY_PATTERN)
    signatory_map: list[SignatoryEntry] = Field(default_factory=list)
    expires_at: datetime | None = None
    status: str | None = Field(
        default=None,
        pattern=_SETTABLE_STATUS_PATTERN,
        description="Optional initial status: draft or awaiting_signatures. Others are derived.",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _roles_unique(self) -> SigningSessionCreate:
        roles = [s.role for s in self.signatory_map]
        if len(roles) != len(set(roles)):
            raise ValueError("signatory_map roles must be unique within a session.")
        return self


class SigningSessionUpdate(BaseModel):
    """Body for ``PATCH /v1/signing/sessions/{id}``.

    Changing ``document_content_hash`` is the supported way to re-issue the
    signed content; earlier signatures then show up as stale via delta-by-hash.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    document_ref: str | None = Field(default=None, min_length=1, max_length=512)
    document_content_hash: str | None = Field(default=None, min_length=1, max_length=128)
    provider_capability: str | None = Field(default=None, pattern=_CAPABILITY_PATTERN)
    signatory_map: list[SignatoryEntry] | None = None
    expires_at: datetime | None = None
    status: str | None = Field(default=None, pattern=_SETTABLE_STATUS_PATTERN)
    metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _roles_unique(self) -> SigningSessionUpdate:
        if self.signatory_map is not None:
            roles = [s.role for s in self.signatory_map]
            if len(roles) != len(set(roles)):
                raise ValueError("signatory_map roles must be unique within a session.")
        return self


# ── Attestation / decline ──────────────────────────────────────────────


class AttestationCreate(BaseModel):
    """Body for ``POST /v1/signing/sessions/{id}/attest``.

    Records that a signatory has signed. It carries the content hash actually
    signed and, optionally, descriptive certificate metadata. It deliberately
    has no field for a key, a certificate file or a password.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    signatory_name: str = Field(..., min_length=1, max_length=255)
    signatory_role: str = Field(..., min_length=1, max_length=64)
    content_hash: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="sha256 hex the signatory actually signed. Compared to the session hash.",
    )
    cert_subject: str | None = Field(default=None, max_length=512)
    cert_valid_until: date | None = None
    signed_at: datetime | None = Field(
        default=None,
        description="When the signature was made. Defaults to now.",
    )
    notes: str = Field(default="", max_length=2000)


class DeclineCreate(BaseModel):
    """Body for ``POST /v1/signing/sessions/{id}/decline``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    signatory_name: str = Field(..., min_length=1, max_length=255)
    signatory_role: str = Field(..., min_length=1, max_length=64)
    reason: str = Field(default="", max_length=2000)


# ── Responses ──────────────────────────────────────────────────────────


class SignatureResponse(BaseModel):
    """A recorded attestation returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    project_id: UUID
    signatory_name: str
    signatory_role: str
    signed_at: datetime
    cert_subject: str | None = None
    cert_valid_until: date | None = None
    content_hash: str
    status: str = "signed"
    notes: str = ""
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime

    # Whether this signature's content_hash still matches its session's current
    # document_content_hash. False = stale, the content moved on since signing.
    stale: bool | None = Field(
        default=None,
        description="True when the signed content hash no longer matches the session hash.",
    )


class SigningSessionResponse(BaseModel):
    """A signing session returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    document_ref: str
    document_content_hash: str
    provider_capability: str = "simple_electronic"
    # What the resolved provider actually delivers. Never defaulted to the
    # required value: None means "not recorded", and a reader that renders it
    # as the requirement is back to claiming a tier nothing delivered.
    delivered_capability: str | None = None
    signatory_map: list[dict[str, Any]] = Field(default_factory=list)
    status: str = "draft"
    expires_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime

    # Convenience roll-ups computed by the service from the attestations.
    required_count: int = 0
    signed_count: int = 0
    declined_count: int = 0
    signatures: list[SignatureResponse] = Field(default_factory=list)


class CertExpiryFlag(BaseModel):
    """A signature whose certificate metadata is expired or expiring soon."""

    session_id: UUID
    signature_id: UUID
    signatory_name: str
    signatory_role: str
    cert_subject: str | None = None
    cert_valid_until: date
    days_until_expiry: int
    expired: bool


__all__ = [
    "CAPABILITIES",
    "SESSION_STATUSES",
    "SIGNATURE_STATUSES",
    "AttestationCreate",
    "CertExpiryFlag",
    "DeclineCreate",
    "SignatoryEntry",
    "SignatureResponse",
    "SigningSessionCreate",
    "SigningSessionResponse",
    "SigningSessionUpdate",
]
