# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pydantic schemas for the professional-credentials registry."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ── Canonical vocabularies (open-ended; packs may extend via the DB) ───
#
# These are the built-in, jurisdiction-neutral credential families. The DB
# column is a plain String so a regional pack can persist a value outside this
# list without a migration; the API validates against the union so the built-in
# UI pickers stay honest.

CREDENTIAL_TYPES: tuple[str, ...] = (
    "professional_license",  # e.g. chartered / registered engineer or architect
    "certification",  # a competency certificate
    "statutory_membership",  # membership of a body required to practise
    "professional_indemnity",  # PI / liability cover tied to a person or firm
    "registration",  # a register entry (trade card, roster)
    "training",  # a completed training / course record
    "accreditation",  # firm-level accreditation
    "wsl_clearance",  # CA workers safety letter clearance
    "wsib_clearance",  # CA ON Workplace Safety and Insurance Board
    "wcb_clearance",  # CA provincial Workers Compensation Board
    "attestation_revenu_quebec",  # CA QC tax compliance attestation
    # Personnel documents tracked for people on a project (staffing module).
    # The registry holds only the validity window; the staffing file keeps at
    # most the last four characters of a document number.
    "employment_contract",  # employment or service contract of the assignment
    "work_permit",  # permission to work issued by an immigration authority
    "residence_permit",  # residence title
    "identity_document",  # passport or national identity card
    "visa",  # entry or business visa
    "occupational_health",  # occupational health certificate: date and fitness only, never findings
    "right_to_work_check",  # employer's documented right to work check
    "posting_certificate",  # social security posting certificate (e.g. EU A1)
    "other",
)

# Personnel documents: who holds a work permit, a passport or a health
# certificate, and until when, is personal data of that person. These types use
# the status and expiry engine of this module, but they are written and read
# through the staffing personnel file only, which checks the caller's
# relationship to the person and audits every read. The register (list, expiring
# soon, summary, compliance, single read, update, delete, verify) does not show
# them, a register request cannot create one or turn a credential into one, and
# a row of these types never carries an identifier, notes or metadata.
PERSONNEL_CREDENTIAL_TYPES: tuple[str, ...] = (
    "employment_contract",
    "work_permit",
    "residence_permit",
    "identity_document",
    "visa",
    "occupational_health",
    "right_to_work_check",
    "posting_certificate",
)

HOLDER_KINDS: tuple[str, ...] = ("person", "company")

STATUSES: tuple[str, ...] = (
    "active",
    "expiring_soon",
    "expired",
    "suspended",
    "revoked",
)

# Statuses a caller may set explicitly; the date-derived ones are computed.
_MANUAL_STATUSES: tuple[str, ...] = ("active", "suspended", "revoked")

_CREDENTIAL_TYPE_PATTERN = "^(" + "|".join(CREDENTIAL_TYPES) + ")$"
_HOLDER_KIND_PATTERN = "^(" + "|".join(HOLDER_KINDS) + ")$"
_MANUAL_STATUS_PATTERN = "^(" + "|".join(_MANUAL_STATUSES) + ")$"


# ── Create ─────────────────────────────────────────────────────────────


class CredentialCreate(BaseModel):
    """Body for ``POST /v1/credentials/``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    holder_name: str = Field(..., min_length=1, max_length=255)
    holder_kind: str = Field(default="person", pattern=_HOLDER_KIND_PATTERN)
    holder_user_id: UUID | None = None
    credential_type: str = Field(..., pattern=_CREDENTIAL_TYPE_PATTERN)
    discipline: str | None = Field(default=None, max_length=64)
    authority: str | None = Field(default=None, max_length=255)
    identifier: str | None = Field(default=None, max_length=120)
    jurisdiction: str | None = Field(default=None, max_length=64)
    issued_at: date | None = None
    valid_until: date | None = None
    notify_days_before: int = Field(default=30, ge=0, le=365)
    notification_obligation_days: int | None = Field(default=None, ge=0, le=365)
    notification_trigger: str | None = Field(default=None, max_length=64)
    status: str | None = Field(
        default=None,
        pattern=_MANUAL_STATUS_PATTERN,
        description=(
            "Optional manual status. Only active / suspended / revoked may be "
            "set; expiring_soon / expired are derived from the validity window."
        ),
    )
    notes: str = Field(default="", max_length=10000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _dates_consistent(self) -> CredentialCreate:
        if self.issued_at is not None and self.valid_until is not None and self.valid_until < self.issued_at:
            raise ValueError("valid_until must be on or after issued_at.")
        return self


# ── Update ─────────────────────────────────────────────────────────────


class CredentialUpdate(BaseModel):
    """Body for ``PATCH /v1/credentials/{id}``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    holder_name: str | None = Field(default=None, min_length=1, max_length=255)
    holder_kind: str | None = Field(default=None, pattern=_HOLDER_KIND_PATTERN)
    holder_user_id: UUID | None = None
    credential_type: str | None = Field(default=None, pattern=_CREDENTIAL_TYPE_PATTERN)
    discipline: str | None = Field(default=None, max_length=64)
    authority: str | None = Field(default=None, max_length=255)
    identifier: str | None = Field(default=None, max_length=120)
    jurisdiction: str | None = Field(default=None, max_length=64)
    issued_at: date | None = None
    valid_until: date | None = None
    notify_days_before: int | None = Field(default=None, ge=0, le=365)
    notification_obligation_days: int | None = Field(default=None, ge=0, le=365)
    notification_trigger: str | None = Field(default=None, max_length=64)
    status: str | None = Field(default=None, pattern=_MANUAL_STATUS_PATTERN)
    notes: str | None = Field(default=None, max_length=10000)
    metadata: dict[str, Any] | None = None


# ── Response ───────────────────────────────────────────────────────────


class CredentialResponse(BaseModel):
    """Credential returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    holder_name: str
    holder_kind: str = "person"
    holder_user_id: UUID | None = None
    credential_type: str
    discipline: str | None = None
    authority: str | None = None
    identifier: str | None = None
    jurisdiction: str | None = None
    issued_at: date | None = None
    valid_until: date | None = None
    notify_days_before: int = 30
    notification_obligation_days: int | None = None
    notification_trigger: str | None = None
    status: str = "active"
    notes: str = ""
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias="metadata_",
    )
    verified_by: str | None = None
    verified_at: date | None = None
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime

    # Computed convenience field. None when the credential is perpetual
    # (no valid_until); otherwise signed - negative once expired.
    days_until_expiry: int | None = Field(
        default=None,
        description="Days to expiry: negative when expired, 0 on expiry day, None when perpetual.",
    )
    # True when the stored status column has drifted behind the validity window
    # - i.e. the row aged into a new bucket and nothing has written to it since.
    # ``status`` above is always the freshly derived value, so the register never
    # reports a status its own expiry date contradicts; this flag exists so an
    # operator can tell the stored column needs the refresh endpoint run.
    status_is_stale: bool = Field(
        default=False,
        description="True when the persisted status column disagrees with the derived one.",
    )


# ── Verification ───────────────────────────────────────────────────────


class CredentialVerifyRequest(BaseModel):
    """Body for ``POST /v1/credentials/{id}/verify/``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    verified: bool = Field(
        default=True,
        description="True records a verification; False clears one (a retraction).",
    )
    verified_at: date | None = Field(
        default=None,
        description="Date the check was performed. Defaults to today when omitted.",
    )
    note: str | None = Field(default=None, max_length=2000)


# ── Requirements ───────────────────────────────────────────────────────

# The audience token meaning "everyone on this project's register".
APPLIES_TO_ALL = "all"


class RequirementCreate(BaseModel):
    """Body for ``POST /v1/credentials/requirements/``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    credential_type: str = Field(..., pattern=_CREDENTIAL_TYPE_PATTERN)
    applies_to: str = Field(
        default=APPLIES_TO_ALL,
        min_length=1,
        max_length=64,
        description=(
            "'all' binds every holder on the register; any other value is matched against the holder's discipline."
        ),
    )
    holder_kind: str = Field(default="person", pattern=_HOLDER_KIND_PATTERN)
    is_blocking: bool = Field(
        default=True,
        description="True means a gap stops the holder working; False means it is a note.",
    )
    grace_days: int = Field(default=0, ge=0, le=365)
    description: str = Field(default="", max_length=10000)
    is_active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class RequirementUpdate(BaseModel):
    """Body for ``PATCH /v1/credentials/requirements/{id}``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    credential_type: str | None = Field(default=None, pattern=_CREDENTIAL_TYPE_PATTERN)
    applies_to: str | None = Field(default=None, min_length=1, max_length=64)
    holder_kind: str | None = Field(default=None, pattern=_HOLDER_KIND_PATTERN)
    is_blocking: bool | None = None
    grace_days: int | None = Field(default=None, ge=0, le=365)
    description: str | None = Field(default=None, max_length=10000)
    is_active: bool | None = None
    metadata: dict[str, Any] | None = None


class RequirementResponse(BaseModel):
    """A requirement returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    credential_type: str
    applies_to: str = APPLIES_TO_ALL
    holder_kind: str = "person"
    is_blocking: bool = True
    grace_days: int = 0
    description: str = ""
    is_active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


# ── Compliance ─────────────────────────────────────────────────────────

# Why a holder fails a requirement. ``missing`` and ``expired`` are the two
# that stop work; ``expiring_soon`` is the warning ahead of it.
GAP_REASONS: tuple[str, ...] = ("missing", "expired", "suspended", "revoked", "expiring_soon")


class ComplianceGap(BaseModel):
    """One unmet requirement for one holder."""

    requirement_id: UUID
    credential_type: str
    applies_to: str
    reason: str = Field(..., description=" | ".join(GAP_REASONS))
    is_blocking: bool
    grace_days: int = 0
    # Present for every reason except ``missing`` - there is no credential to
    # point at when the holder never had one.
    credential_id: UUID | None = None
    valid_until: date | None = None
    days_until_expiry: int | None = None
    # True when the gap is a lapse still inside the requirement's grace window,
    # so it is reportable but does not stop work yet.
    within_grace: bool = False


class ComplianceHolderRow(BaseModel):
    """Every requirement outcome for one holder on the project."""

    holder_name: str
    holder_kind: str
    holder_user_id: UUID | None = None
    discipline: str | None = None
    # The headline: can this person or firm work today.
    is_blocked: bool = False
    gaps: list[ComplianceGap] = Field(default_factory=list)
    satisfied_count: int = 0
    unverified_count: int = Field(
        default=0,
        description="Satisfied requirements met by a credential nobody has checked.",
    )


class ComplianceReport(BaseModel):
    """Answers 'who may not work today, and what is about to stop them'."""

    project_id: UUID
    as_of: date
    requirement_count: int
    holder_count: int
    blocked_holder_count: int
    holders: list[ComplianceHolderRow] = Field(default_factory=list)
    # Requirements that bind nobody because the register holds no matching
    # holder. A rule nobody is measured against is usually a mistake, so it is
    # surfaced rather than silently counted as met.
    unmatched_requirement_ids: list[UUID] = Field(default_factory=list)


# ── Summary ────────────────────────────────────────────────────────────


class CredentialSummary(BaseModel):
    """Counts for the register's dashboard tile."""

    project_id: UUID
    as_of: date
    total: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    expiring_within_30_days: int = 0
    expired: int = 0
    unverified: int = 0
    perpetual: int = 0
    stale_status_count: int = Field(
        default=0,
        description="Rows whose stored status has drifted; run the refresh endpoint.",
    )


class RefreshResult(BaseModel):
    """Outcome of recomputing the stored status column."""

    project_id: UUID
    as_of: date
    examined: int = 0
    updated: int = 0


# ── Validation ─────────────────────────────────────────────────────────


class CredentialsValidationFinding(BaseModel):
    """One finding from the ``credentials`` rule set."""

    rule_id: str
    severity: str
    message: str
    key: str = Field(..., description="i18n key for the message, namespaced per rule.")
    context: dict[str, Any] = Field(default_factory=dict)


class CredentialsValidationReport(BaseModel):
    """Report returned by ``GET /v1/credentials/validate/``."""

    project_id: UUID
    status: str
    # None when nothing was checked - an empty register scores nothing rather
    # than scoring perfectly.
    score: float | None = None
    error_count: int = 0
    warning_count: int = 0
    findings: list[CredentialsValidationFinding] = Field(default_factory=list)


__all__ = [
    "APPLIES_TO_ALL",
    "CREDENTIAL_TYPES",
    "PERSONNEL_CREDENTIAL_TYPES",
    "GAP_REASONS",
    "HOLDER_KINDS",
    "STATUSES",
    "ComplianceGap",
    "ComplianceHolderRow",
    "ComplianceReport",
    "CredentialCreate",
    "CredentialResponse",
    "CredentialSummary",
    "CredentialUpdate",
    "CredentialVerifyRequest",
    "CredentialsValidationFinding",
    "CredentialsValidationReport",
    "RefreshResult",
    "RequirementCreate",
    "RequirementResponse",
    "RequirementUpdate",
]
