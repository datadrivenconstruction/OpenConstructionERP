# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pydantic schemas for the subcontractors module."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Upper bound for money fields - mirrors changeorders/full_evm/risk/punchlist.
# A finite-but-absurd magnitude (e.g. 1e400) otherwise sums into gross and
# reaches retention quantize() -> InvalidOperation -> opaque 500. ge=0 already
# rejects NaN/Infinity; this bound keeps the value inside the decimal context.
_MONEY_MAX = Decimal("1e15")

# ── R5 validators ─────────────────────────────────────────────────────────
# Currency must be a 3-letter ISO-4217 code OR empty (caller-driven default).
_ISO4217_RE = re.compile(r"^[A-Z]{3}$|^$")
# Strip CR/LF + NUL from free-form text that flows into logs / events /
# notification subjects. Mirrors the v4.2.4 correspondence subject fix.
_CRLF_RE = re.compile(r"[\r\n\x00]")


def _strip_crlf(value: str | None) -> str | None:
    if value is None:
        return None
    return _CRLF_RE.sub(" ", value).strip()


def _validate_currency(value: str | None) -> str | None:
    """Reject obviously-wrong currency codes; allow empty (means inherit)."""
    if value is None:
        return None
    upper = value.upper()
    if not _ISO4217_RE.fullmatch(upper):
        raise ValueError(
            f"currency must be a 3-letter ISO-4217 code (got {value!r})",
        )
    return upper


def _safe_document_url(value: str | None) -> str | None:
    """Reject document URLs that would let a caller pivot to SSRF / LFI.

    Permitted shapes: empty / None, a bare relative path under ``uploads/``
    or ``s3://`` / ``https://`` (TLS only). Reject ``file://``, ``http://``,
    backslash traversal, scheme-less absolute paths and anything carrying
    CR/LF / NUL.
    """
    if value is None or value == "":
        return value
    if _CRLF_RE.search(value):
        raise ValueError("document_url must not contain control characters")
    lowered = value.lower().strip()
    if lowered.startswith(("file://", "http://", "ftp://", "javascript:")):
        raise ValueError(f"document_url scheme not permitted: {value!r}")
    if ".." in lowered or lowered.startswith(("/", "\\")) or "\\" in lowered:
        raise ValueError("document_url must be a relative upload path or https/s3 URL")
    return value


# ── Subcontractor ────────────────────────────────────────────────────────


class SubcontractorBase(BaseModel):
    """Shared subcontractor fields."""

    model_config = ConfigDict(str_strip_whitespace=True)

    legal_name: str = Field(..., min_length=1, max_length=255)
    trade_name: str | None = Field(default=None, max_length=255)
    tax_id: str | None = Field(default=None, max_length=64)
    trade_categories: list[str] = Field(default_factory=list)
    country: str | None = Field(default=None, max_length=2)
    address: dict[str, Any] | None = None
    website: str | None = Field(default=None, max_length=500)
    notes: str | None = None
    contact_id: UUID | None = None


class SubcontractorCreate(SubcontractorBase):
    """Create payload for Subcontractor."""

    prequalification_status: str = Field(
        default="pending",
        pattern=r"^(pending|approved|suspended|rejected)$",
    )


class SubcontractorUpdate(BaseModel):
    """Partial update for Subcontractor.

    R5: ``rating_score`` is *deliberately* not editable here - it is the
    rolled-up output of :class:`SubcontractorRating` rows and must only
    be written through :meth:`SubcontractorService.update_rating` /
    ``bump_rating_from_event`` (both gated by ``subcontractors.rate``).
    Letting an EDITOR PATCH the score directly is rating tampering.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    legal_name: str | None = Field(default=None, min_length=1, max_length=255)
    trade_name: str | None = Field(default=None, max_length=255)
    tax_id: str | None = Field(default=None, max_length=64)
    trade_categories: list[str] | None = None
    prequalification_status: str | None = Field(
        default=None,
        pattern=r"^(pending|approved|suspended|rejected)$",
    )
    country: str | None = Field(default=None, max_length=2)
    address: dict[str, Any] | None = None
    website: str | None = Field(default=None, max_length=500)
    notes: str | None = None
    is_active: bool | None = None
    contact_id: UUID | None = None


class SubcontractorResponse(BaseModel):
    """Subcontractor returned by the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    contact_id: UUID | None = None
    legal_name: str
    trade_name: str | None = None
    tax_id: str | None = None
    trade_categories: list[str] = Field(default_factory=list)
    prequalification_status: str = "pending"
    rating_score: Decimal = Decimal("0")
    country: str | None = None
    address: dict[str, Any] | None = None
    website: str | None = None
    notes: str | None = None
    is_active: bool = True
    # ── Wave 4 / T12: construction management platform style prequal + insurance tracking ──
    prequal_score: int | None = None
    insurance_expiry_date: date | None = None
    insurance_doc_id: UUID | None = None
    prequal_questionnaire: dict[str, Any] | None = None
    prequal_completed_at: datetime | None = None
    blocked_reason: str | None = None
    is_blocked: bool = False
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class SubcontractorListResponse(BaseModel):
    """One page of subcontractors plus the size of the matching set.

    ``total`` counts the rows the query matched, not the length of ``items``.
    ``active_only`` and ``prequalification_status`` are applied before the count
    is taken, so a zero here means this question found nothing rather than the
    yard holding nothing.

    One filter is deliberately outside the count. ``trade_category`` is applied
    in Python to the page that came back, not in SQL, because the repository
    keeps that check portable across SQLite and PostgreSQL. So when a caller
    passes ``trade_category`` the count is an upper bound on the matching set
    rather than its size. No caller in the application passes it today; the day
    one does, the filter has to move into the query before the number means
    what this docstring says.
    """

    model_config = ConfigDict(from_attributes=True)

    items: list[SubcontractorResponse]
    total: int
    offset: int
    limit: int


class PrequalRequest(BaseModel):
    """Submit a prequalification questionnaire for a subcontractor.

    ``questionnaire`` carries the raw Yes/No / multi-choice answers as a
    plain ``dict[str, Any]`` - the questionnaire shape is intentionally
    loose so individual GCs can author their own forms without a schema
    migration. If ``score`` is None the service computes it from the
    answers (sum of truthy values / total non-null answers, x 100).
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    questionnaire: dict[str, Any] = Field(default_factory=dict)
    score: int | None = Field(default=None, ge=0, le=100)
    # When true the service rejects (400) a questionnaire that leaves any
    # required question unanswered (final submit). Default false saves a draft.
    require_complete: bool = False

    @field_validator("questionnaire")
    @classmethod
    def _bounded_questionnaire(cls, value: dict[str, Any]) -> dict[str, Any]:
        """Cap questionnaire shape to defend the scorer against a DoS
        payload: 200 top-level keys, 4 KB per scalar value. Beyond that
        the form is almost certainly garbage."""
        if len(value) > 200:
            raise ValueError("questionnaire may not exceed 200 questions")
        for key, item in value.items():
            if len(str(key)) > 200:
                raise ValueError("questionnaire keys are capped at 200 chars")
            if isinstance(item, str) and len(item) > 4096:
                raise ValueError(
                    f"questionnaire answer for {key!r} exceeds 4096 chars",
                )
        return value


class PrequalView(BaseModel):
    """Current prequalification state for a subcontractor (read model).

    Backs ``GET /subcontractors/{id}/prequal`` so the questionnaire UI can
    seed itself from the prior submission, show the stored score, and surface
    the answer-key driven evaluation (which required questions are still
    unanswered) without re-deriving it on the client.
    """

    model_config = ConfigDict(from_attributes=True)

    subcontractor_id: UUID
    prequalification_status: str = "pending"
    prequal_score: int | None = None
    prequal_questionnaire: dict[str, Any] | None = None
    prequal_completed_at: datetime | None = None
    is_blocked: bool = False
    blocked_reason: str | None = None
    # Required question keys that are still unanswered against the canonical
    # questionnaire spec. Empty when the questionnaire is complete (or none has
    # been submitted yet, in which case ``prequal_questionnaire`` is null).
    missing_required: list[str] = Field(default_factory=list)
    # The answer-key score recomputed from the stored answers, so the UI shows
    # the server-trusted value rather than trusting the persisted ``prequal_score``
    # (which may have been an explicit caller override).
    computed_score: int | None = None
    approval_threshold: int = 70


class MonthlyRatingComputeRequest(BaseModel):
    """Admin trigger to recompute a subcontractor's monthly rating rollup."""

    model_config = ConfigDict(str_strip_whitespace=True)

    period: str = Field(..., pattern=r"^\d{4}-\d{2}$")


class BlockRequest(BaseModel):
    """Hard-block a subcontractor from bidding / payment with a reason."""

    model_config = ConfigDict(str_strip_whitespace=True)

    reason: str = Field(..., min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def _no_crlf(cls, value: str) -> str:
        out = _strip_crlf(value)
        if not out:
            raise ValueError("reason must not be empty after CR/LF stripping")
        return out


class InsuranceExpiryEntry(BaseModel):
    """One subcontractor flagged by ``check_insurance_expiry``."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    legal_name: str
    insurance_expiry_date: date | None = None
    days_until_expiry: int  # negative if already past
    is_blocked: bool = False


# ── SubcontractorContact ─────────────────────────────────────────────────


class SubcontractorContactCreate(BaseModel):
    """Create payload for SubcontractorContact."""

    model_config = ConfigDict(str_strip_whitespace=True)

    subcontractor_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    role: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=64)
    primary: bool = False


class SubcontractorContactUpdate(BaseModel):
    """Partial update for SubcontractorContact."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    role: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=64)
    primary: bool | None = None


class SubcontractorContactResponse(BaseModel):
    """SubcontractorContact returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    subcontractor_id: UUID
    name: str
    role: str | None = None
    email: str | None = None
    phone: str | None = None
    primary: bool = False
    created_at: datetime
    updated_at: datetime


# ── PrequalificationApplication ─────────────────────────────────────────


class PrequalificationCreate(BaseModel):
    """Create payload for PrequalificationApplication."""

    model_config = ConfigDict(str_strip_whitespace=True)

    subcontractor_id: UUID
    answers: dict[str, Any] = Field(default_factory=dict)
    status: str = Field(
        default="draft",
        pattern=r"^(draft|submitted|under_review|approved|rejected)$",
    )


class PrequalificationUpdate(BaseModel):
    """Partial update for PrequalificationApplication."""

    model_config = ConfigDict(str_strip_whitespace=True)

    answers: dict[str, Any] | None = None
    status: str | None = Field(
        default=None,
        pattern=r"^(draft|submitted|under_review|approved|rejected)$",
    )
    decision_notes: str | None = None


class PrequalificationResponse(BaseModel):
    """PrequalificationApplication returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    subcontractor_id: UUID
    submitted_at: datetime | None = None
    status: str = "draft"
    answers: dict[str, Any] = Field(default_factory=dict)
    reviewer_id: str | None = None
    decision_at: datetime | None = None
    decision_notes: str | None = None
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


# ── Certificate ──────────────────────────────────────────────────────────

# The certificate types a subcontractor can file. The last three are the
# generic names for clearances a national pack may require before a sub is paid
# (a construction tax exemption, a social-security clearance, an employers'
# liability clearance). They are named by what they prove, never by one
# country's form, so the country's own label comes from the pack and the
# locales while the stored value stays the same everywhere.
_CERT_TYPE_PATTERN = (
    r"^(insurance|license|iso|safety|bond|wsl_clearance|wsib_clearance|wcb_clearance|attestation_revenu_quebec"
    r"|construction_tax_exemption|social_security_clearance|employers_liability_clearance)$"
)


class CertificateCreate(BaseModel):
    """Create payload for Certificate."""

    model_config = ConfigDict(str_strip_whitespace=True)

    subcontractor_id: UUID
    cert_type: str = Field(
        ...,
        pattern=_CERT_TYPE_PATTERN,
    )
    issued_by: str | None = Field(default=None, max_length=255)
    issue_date: date | None = None
    valid_until: date | None = None
    document_url: str | None = Field(default=None, max_length=1000)
    notes: str | None = None

    @field_validator("document_url")
    @classmethod
    def _safe_url(cls, value: str | None) -> str | None:
        return _safe_document_url(value)

    @field_validator("valid_until")
    @classmethod
    def _expiry_sane(cls, value: date | None, info: Any) -> date | None:
        """Reject backdated expiry (``valid_until < issue_date``) and
        absurd 100-year-out values that hint at a typo or bypass attempt."""
        if value is None:
            return value
        issue = info.data.get("issue_date") if hasattr(info, "data") else None
        if issue is not None and value < issue:
            raise ValueError(
                "valid_until must be on or after issue_date",
            )
        if value.year > 2100:
            raise ValueError("valid_until year is out of range")
        return value


class CertificateUpdate(BaseModel):
    """Partial update for Certificate."""

    model_config = ConfigDict(str_strip_whitespace=True)

    cert_type: str | None = Field(
        default=None,
        pattern=_CERT_TYPE_PATTERN,
    )
    issued_by: str | None = Field(default=None, max_length=255)
    issue_date: date | None = None
    valid_until: date | None = None
    document_url: str | None = Field(default=None, max_length=1000)
    revoked: bool | None = None
    notes: str | None = None

    @field_validator("document_url")
    @classmethod
    def _safe_url(cls, value: str | None) -> str | None:
        return _safe_document_url(value)

    @field_validator("valid_until")
    @classmethod
    def _expiry_sane(cls, value: date | None) -> date | None:
        if value is not None and value.year > 2100:
            raise ValueError("valid_until year is out of range")
        return value


class CertificateResponse(BaseModel):
    """Certificate returned by the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    subcontractor_id: UUID
    cert_type: str
    issued_by: str | None = None
    issue_date: date | None = None
    valid_until: date | None = None
    document_url: str | None = None
    status: str = "valid"
    revoked: bool = False
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── SubcontractAgreement ─────────────────────────────────────────────────


class AgreementCreate(BaseModel):
    """Create payload for SubcontractAgreement."""

    model_config = ConfigDict(str_strip_whitespace=True)

    subcontractor_id: UUID
    project_id: UUID
    title: str = Field(..., min_length=1, max_length=500)
    total_value: Decimal = Field(default=Decimal("0"), ge=0)
    currency: str = Field(default="", max_length=3)
    start_date: date | None = None
    end_date: date | None = None
    retention_percent: Decimal = Field(default=Decimal("5.0"), ge=0, le=100)
    retention_release_event: str | None = Field(default=None, max_length=120)
    requires_lien_waiver: bool = False
    prime_contract_id: UUID | None = None
    contract_id: UUID | None = None
    notes: str | None = None

    @field_validator("currency")
    @classmethod
    def _currency_iso(cls, value: str) -> str:
        return _validate_currency(value) or ""


class UnlinkedTwinResponse(BaseModel):
    """An agreement and a contract on one project that look like one subcontract."""

    agreement_id: UUID
    agreement_title: str
    contract_id: UUID
    contract_code: str
    contract_title: str
    currency: str
    agreement_value: Decimal
    contract_value: Decimal
    #: ``counterparty`` when the same subcontractor or contact is named,
    #: ``name`` when only the normalised company names agree.
    matched_on: str
    #: Values within 1% of each other; a supporting signal, not the reason.
    value_close: bool


class DismissTwinRequest(BaseModel):
    """Say an agreement and a contract are different subcontracts."""

    contract_id: UUID


class AgreementUpdate(BaseModel):
    """Partial update for SubcontractAgreement."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=500)
    total_value: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=3)
    start_date: date | None = None
    end_date: date | None = None
    retention_percent: Decimal | None = Field(default=None, ge=0, le=100)
    retention_release_event: str | None = Field(default=None, max_length=120)
    requires_lien_waiver: bool | None = None
    prime_contract_id: UUID | None = None
    contract_id: UUID | None = None
    status: str | None = Field(
        default=None,
        pattern=r"^(draft|active|completed|terminated)$",
    )
    notes: str | None = None

    @field_validator("currency")
    @classmethod
    def _currency_iso(cls, value: str | None) -> str | None:
        return _validate_currency(value)


class AgreementResponse(BaseModel):
    """SubcontractAgreement returned by the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    subcontractor_id: UUID
    project_id: UUID
    title: str
    total_value: Decimal = Decimal("0")
    currency: str = ""
    start_date: date | None = None
    end_date: date | None = None
    retention_percent: Decimal = Decimal("5.0")
    retention_release_event: str | None = None
    requires_lien_waiver: bool = False
    prime_contract_id: UUID | None = None
    contract_id: UUID | None = None
    status: str = "draft"
    notes: str | None = None
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── WorkPackage ──────────────────────────────────────────────────────────


class WorkPackageCreate(BaseModel):
    """Create payload for WorkPackage."""

    model_config = ConfigDict(str_strip_whitespace=True)

    agreement_id: UUID
    name: str = Field(..., min_length=1, max_length=500)
    scope: str | None = None
    planned_value: Decimal = Field(default=Decimal("0"), ge=0)
    completion_percent: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    status: str = Field(
        default="planned",
        pattern=r"^(planned|in_progress|completed)$",
    )
    contract_line_id: UUID | None = None


class WorkPackageUpdate(BaseModel):
    """Partial update for WorkPackage."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=500)
    scope: str | None = None
    planned_value: Decimal | None = Field(default=None, ge=0)
    completion_percent: Decimal | None = Field(default=None, ge=0, le=100)
    status: str | None = Field(
        default=None,
        pattern=r"^(planned|in_progress|completed)$",
    )
    # Sending ``null`` explicitly clears the mapping; leaving the key out
    # keeps it. The service reads ``exclude_unset``, so the two differ.
    contract_line_id: UUID | None = None


class WorkPackageResponse(BaseModel):
    """WorkPackage returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agreement_id: UUID
    name: str
    scope: str | None = None
    planned_value: Decimal = Decimal("0")
    completion_percent: Decimal = Decimal("0")
    status: str = "planned"
    contract_line_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


# ── PaymentApplication & Lines ───────────────────────────────────────────


class PaymentApplicationLineCreate(BaseModel):
    """Line item attached to a payment application."""

    model_config = ConfigDict(str_strip_whitespace=True)

    work_package_id: UUID
    claimed_amount: Decimal = Field(default=Decimal("0"), ge=0, le=_MONEY_MAX)
    certified_amount: Decimal = Field(default=Decimal("0"), ge=0, le=_MONEY_MAX)
    approved_amount: Decimal = Field(default=Decimal("0"), ge=0, le=_MONEY_MAX)
    claimed_qty: Decimal = Field(default=Decimal("0"))
    assessed_qty: Decimal = Field(default=Decimal("0"))
    certified_qty: Decimal = Field(default=Decimal("0"))
    # Optional override of the work package's GC schedule-of-values line.
    contract_line_id: UUID | None = None


class PaymentApplicationLineUpdate(BaseModel):
    """Re-map one pay-application line to a GC schedule-of-values line.

    Only the mapping is editable here. The amounts belong to the pay
    application's approval chain and are not reopened by a mapping change.
    ``null`` clears the override, so the line falls back to its work package.
    """

    contract_line_id: UUID | None = None


class ApprovedLineAmount(BaseModel):
    """What finance approves on one line of the pay application it approves."""

    line_id: UUID
    approved_amount: Decimal = Field(ge=0, le=_MONEY_MAX)


class PaymentApplicationFinanceApproval(BaseModel):
    """Optional body of the finance approval: the approved amount per line.

    A line named here gets exactly that amount, at most what was claimed on
    it. A line left out keeps an approved amount it already has, and one still
    at zero is approved at its claimed amount, because approving the pay
    application approves its gross, which the claims make up. So an approval
    without a body, or with no lines, approves every line as claimed.
    """

    lines: list[ApprovedLineAmount] = Field(default_factory=list)


class PaymentApplicationLineResponse(BaseModel):
    """Line item returned with a payment application."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    payment_application_id: UUID
    work_package_id: UUID
    claimed_amount: Decimal = Decimal("0")
    certified_amount: Decimal = Decimal("0")
    approved_amount: Decimal = Decimal("0")
    claimed_qty: Decimal = Decimal("0")
    assessed_qty: Decimal = Decimal("0")
    certified_qty: Decimal = Decimal("0")
    contract_line_id: UUID | None = None


class PaymentApplicationLineListResponse(BaseModel):
    """One page of a pay application's lines plus how many it has.

    ``total`` counts the pay application's lines, not the rows on the page, so
    a reader holding fewer than ``total`` knows there are more. Declared after
    :class:`PaymentApplicationLineResponse` on purpose: ``from __future__
    import annotations`` turns the field into a string, so naming the row
    class before it exists parses here and fails when Pydantic builds
    the model.
    """

    model_config = ConfigDict(from_attributes=True)

    items: list[PaymentApplicationLineResponse]
    total: int
    offset: int = 0
    limit: int = 50


class PaymentApplicationCreate(BaseModel):
    """Create payload for PaymentApplication."""

    model_config = ConfigDict(str_strip_whitespace=True)

    agreement_id: UUID
    application_number: str | None = Field(default=None, max_length=40)
    period_start: date | None = None
    period_end: date | None = None
    gross_amount: Decimal = Field(default=Decimal("0"), ge=0, le=_MONEY_MAX)
    currency: str = Field(default="", max_length=3)
    lines: list[PaymentApplicationLineCreate] = Field(default_factory=list)

    @field_validator("currency")
    @classmethod
    def _currency_iso(cls, value: str) -> str:
        return _validate_currency(value) or ""


class PaymentApplicationUpdate(BaseModel):
    """Partial update for PaymentApplication."""

    model_config = ConfigDict(str_strip_whitespace=True)

    period_start: date | None = None
    period_end: date | None = None
    gross_amount: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=3)
    rejection_reason: str | None = None

    @field_validator("currency")
    @classmethod
    def _currency_iso(cls, value: str | None) -> str | None:
        return _validate_currency(value)

    @field_validator("rejection_reason")
    @classmethod
    def _no_crlf_reason(cls, value: str | None) -> str | None:
        return _strip_crlf(value)


class PaymentApplicationResponse(BaseModel):
    """PaymentApplication returned by the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    agreement_id: UUID
    application_number: str
    period_start: date | None = None
    period_end: date | None = None
    gross_amount: Decimal = Decimal("0")
    retention_amount: Decimal = Decimal("0")
    net_amount: Decimal = Decimal("0")
    currency: str = ""
    status: str = "submitted"
    submitted_at: datetime | None = None
    foreman_approved_at: datetime | None = None
    foreman_approved_by: str | None = None
    finance_approved_at: datetime | None = None
    finance_approved_by: str | None = None
    # The payable side, set at finance approval and read-only here. Empty
    # before it, and on a pay application approved before these existed,
    # which was paid as claimed.
    approved_gross_amount: Decimal | None = None
    approved_retention_amount: Decimal | None = None
    approved_net_amount: Decimal | None = None
    paid_at: datetime | None = None
    rejection_reason: str | None = None
    # Read-only here: only the claim rollup's include / exclude routes write it.
    progress_claim_id: UUID | None = None
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Retention ────────────────────────────────────────────────────────────


class RetentionLedgerEntryResponse(BaseModel):
    """RetentionLedger entry returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agreement_id: UUID
    payment_application_id: UUID | None = None
    accrued_amount: Decimal = Decimal("0")
    released_amount: Decimal = Decimal("0")
    released_at: datetime | None = None
    release_reason: str | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime
    # Set only on the response to a release: codes for what the release went
    # ahead without, e.g. ``no_final_lien_waiver``. A warning, not a refusal.
    warnings: list[str] = Field(default_factory=list)


class RetentionReleasePayload(BaseModel):
    """Release retention for an agreement."""

    model_config = ConfigDict(str_strip_whitespace=True)

    agreement_id: UUID
    amount: Decimal = Field(..., gt=0)
    reason: str = Field(..., min_length=1, max_length=255)

    @field_validator("reason")
    @classmethod
    def _no_crlf(cls, value: str) -> str:
        out = _strip_crlf(value)
        if not out:
            raise ValueError("reason must not be empty after CR/LF stripping")
        return out


# ── Rating ──────────────────────────────────────────────────────────────


class RatingCreate(BaseModel):
    """Create payload for a SubcontractorRating period rollup."""

    model_config = ConfigDict(str_strip_whitespace=True)

    subcontractor_id: UUID
    period: str = Field(..., pattern=r"^\d{4}-\d{2}$")
    quality_score: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    hse_score: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    schedule_score: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    cost_score: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    basis: dict[str, Any] = Field(default_factory=dict)


# Keys inside ``basis`` that record where a number came from rather than what
# it is. ``sources`` holds a per-metric {"event": n, "direct": n} pair, and the
# ``direct`` half is a raw COUNT(*) over the NCR, safety-incident and schedule
# tables filtered only by subcontractor and month. Those tables are gated by
# verify_project_access when read through their own modules; this count is not
# gated at all, so publishing the pair hands any reader an exact tally of
# another installation tenant's non-conformances and safety incidents through
# an endpoint that asks only for subcontractors.read.
_RATING_BASIS_INTERNAL_KEYS = frozenset({"sources"})


class RatingResponse(BaseModel):
    """SubcontractorRating returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    subcontractor_id: UUID
    period: str
    quality_score: Decimal = Decimal("0")
    hse_score: Decimal = Decimal("0")
    schedule_score: Decimal = Decimal("0")
    cost_score: Decimal = Decimal("0")
    overall_score: Decimal = Decimal("0")
    basis: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    @field_validator("basis", mode="after")
    @classmethod
    def _drop_internal_basis_keys(cls, value: dict[str, Any]) -> dict[str, Any]:
        """Keep the provenance record on the row and off the wire.

        The stored column is left alone, because the audit trail is the reason
        it is written. This only decides what leaves the process, and it sits
        on the response schema rather than in a router so that all three
        routes returning a rating are covered by one rule.

        This narrows the exposure, it does not close it. The headline counters
        beside it are ``max(accumulated, direct)``, so a subcontractor busier
        outside the reader's projects than inside them still shows a number the
        reader could not otherwise obtain, and the score is computed from those
        same counters. Closing that needs a decision on whether a rating is per
        project, per tenant or deliberately shared, which changes both what the
        query may count and what a stored rating row means. Recorded rather
        than guessed at.
        """
        return {k: v for k, v in value.items() if k not in _RATING_BASIS_INTERNAL_KEYS}


# ── Helpers / dashboards ────────────────────────────────────────────────


class ExpiryAlert(BaseModel):
    """A pending expiry alert for a single certificate."""

    certificate_id: UUID
    subcontractor_id: UUID
    cert_type: str
    valid_until: date
    days_until_expiry: int
    window: int = Field(description="Alert window: 60 / 30 / 7")


class ComplianceDetail(BaseModel):
    """One document behind a compliance refusal, with the date it lapsed.

    The `reasons` list is a flat list of codes and stays that way for callers
    that already read it. This is the same verdict in a form a caller can act
    on without parsing a string: which document, what is wrong with it, where
    the fact was read, and when it stopped being valid.
    """

    document_type: str = Field(description="Certificate type, e.g. 'insurance' or 'license'")
    state: str = Field(description="missing | expired | revoked")
    source: str = Field(description="certificate | subcontractor_record")
    lapsed_on: date | None = Field(
        default=None,
        description="Day the document stopped being valid; null when none was ever on file",
    )


class PaymentBlockResult(BaseModel):
    """Result of a `next_payment_blocked` or `subcontractor_award_block` check."""

    blocked: bool
    reasons: list[str] = Field(default_factory=list)
    details: list[ComplianceDetail] = Field(default_factory=list)


class PaymentReleaseCheck(BaseModel):
    """Lien-waiver release gate for a single payment application.

    Drives the waiver badge and the disabled state of the approve/pay buttons
    in the payment-approval UI.
    """

    payment_application_id: UUID
    waiver_required: bool
    blocked: bool
    reasons: list[str] = Field(default_factory=list)


class AwardEligibility(BaseModel):
    """Whether a subcontractor may be awarded live work (TOP-30 #20).

    Drives the prequalification banner in the subcontractor drawer and the
    409 raised when an agreement is activated or a payment is claimed for a
    blocked or rejected/suspended vendor.
    """

    subcontractor_id: UUID
    awardable: bool
    reasons: list[str] = Field(default_factory=list)
    details: list[ComplianceDetail] = Field(default_factory=list)


class VendorEligibility(BaseModel):
    """Award-eligibility verdict resolved from a CRM contact id (TOP-30 #20).

    Procurement POs reference a vendor by ``vendor_contact_id`` (a CRM
    ``Contact``), not a subcontractor id. This shape lets the PO-row badge
    and the create/issue/update gate resolve the prequalification / block
    status from that contact. ``known`` is false when the contact is not a
    registered subcontractor - the gate then treats it as an ad-hoc vendor
    (no block, no warning) rather than an error.
    """

    contact_id: UUID
    known: bool = False
    subcontractor_id: UUID | None = None
    legal_name: str | None = None
    awardable: bool = True
    prequalification_status: str | None = None
    is_blocked: bool = False
    rating_score: str | None = None
    reasons: list[str] = Field(default_factory=list)
    details: list[ComplianceDetail] = Field(default_factory=list)


class CurrencyAmount(BaseModel):
    """One ISO-currency bucket of a money rollup.

    Used to expose per-currency breakdowns of amounts that would otherwise
    be blended into a single, meaningless cross-currency scalar.
    """

    currency: str = ""
    amount: Decimal = Decimal("0")


class SubcontractorDashboard(BaseModel):
    """Summary statistics for a subcontractor."""

    subcontractor_id: UUID
    legal_name: str
    prequalification_status: str
    rating_score: Decimal = Decimal("0")
    active_agreements: int = 0
    open_payment_applications: int = 0
    # ── Money-correctness (additive, non-breaking) ──────────────────────
    # ``pending_retention`` is retained for back-compat but is only a
    # meaningful total when every agreement shares one currency. A
    # subcontractor may hold agreements in different currencies (each
    # SubcontractAgreement carries its own ``currency``), so summing their
    # retention balances into one scalar blends ISO currencies. Consumers
    # should read ``pending_retention_by_currency`` (one bucket per
    # currency) and treat ``pending_retention`` as a blended figure only
    # when ``mixed_currency`` is False.
    pending_retention: Decimal = Decimal("0")
    pending_retention_by_currency: list[CurrencyAmount] = Field(default_factory=list)
    mixed_currency: bool = False
    expired_certificates: int = 0
    expiring_soon_certificates: int = 0
    blocked: bool = False
    block_reasons: list[str] = Field(default_factory=list)


# ── Schedule of Values (SOV) summary ──────────────────────────────────────


class SOVRow(BaseModel):
    """One row in a Schedule-of-Values rollup - per work-package totals."""

    work_package_id: UUID
    name: str
    planned_value: Decimal = Decimal("0")
    completion_percent: Decimal = Decimal("0")
    # All claim/cert/approved totals are rolled up across every payment app
    # tied to this work package - current period + all prior periods.
    claimed_to_date: Decimal = Decimal("0")
    certified_to_date: Decimal = Decimal("0")
    approved_to_date: Decimal = Decimal("0")
    remaining: Decimal = Decimal("0")
    status: str = "planned"


class SOVSummaryResponse(BaseModel):
    """Schedule-of-Values rollup for a subcontract agreement."""

    agreement_id: UUID
    subcontractor_id: UUID
    project_id: UUID | None = None
    total_value: Decimal = Decimal("0")
    currency: str = ""
    rows: list[SOVRow] = Field(default_factory=list)
    totals: dict[str, Decimal] = Field(default_factory=dict)


# ── Tax-ID / VAT validator ────────────────────────────────────────────────


class TaxIdValidationRequest(BaseModel):
    """Request payload for tax-id / VAT format validation."""

    model_config = ConfigDict(str_strip_whitespace=True)

    country: str = Field(..., min_length=2, max_length=2)
    tax_id: str = Field(..., min_length=1, max_length=64)


class TaxIdValidationResponse(BaseModel):
    """Result of tax-id format validation.

    NB: this is a *format* check (regex-based), not a live lookup against a
    government registry. The `country` is upper-cased; the `tax_id` is
    returned in the canonical form (uppercase, no spaces / dots / dashes).
    """

    country: str
    tax_id_normalised: str
    format_valid: bool
    standard: str | None = Field(
        default=None,
        description=(
            "Name of the standard the value was checked against - e.g. "
            "'EU VAT', 'US EIN', 'GB VRN'. None if no rule is known for the country."
        ),
    )
    reason: str | None = Field(
        default=None,
        description="Failure reason when format_valid is false; None on success.",
    )


# ── Lien waivers / tax forms ─────────────────────────────────────────────


# Valid waiver types - restrict at schema level so the magic-byte
# endpoint cannot store arbitrary strings (avoids enum-poisoning that
# could break downstream reporting).
_VALID_WAIVER_TYPES: frozenset[str] = frozenset(
    {
        "conditional_partial",
        "conditional_final",
        "unconditional_partial",
        "unconditional_final",
        "w9",  # US - vendor tax form, annual
        "w8",  # International - vendor tax form, valid 3 years
    },
)


class LienWaiverResponse(BaseModel):
    """Lien waiver / W-9 / W-8 record."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    subcontractor_id: UUID
    payment_application_id: UUID | None = None
    waiver_type: str
    document_url: str
    mime_type: str | None = None
    file_size: int | None = None
    signed_date: date | None = None
    through_date: date | None = None
    amount: Decimal = Decimal("0")
    currency: str = ""
    notes: str | None = None
    uploaded_by: str | None = None
    # ``metadata`` is exposed on the wire, but read from the ``metadata_``
    # ORM attribute (the model maps SQLAlchemy's reserved ``metadata``
    # column to ``metadata_`` in Python). Mirrors CertificateResponse.
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias="metadata_",
    )
    created_at: datetime
    updated_at: datetime


class LienWaiverFormFields(BaseModel):
    """Multipart form fields accepted by the lien-waiver upload endpoint."""

    waiver_type: str
    payment_application_id: UUID | None = None
    signed_date: date | None = None
    through_date: date | None = None
    amount: Decimal = Decimal("0")
    currency: str = ""
    notes: str | None = None

    @field_validator("waiver_type")
    @classmethod
    def _check_waiver_type(cls, v: str) -> str:
        if v not in _VALID_WAIVER_TYPES:
            raise ValueError(
                f"waiver_type must be one of {sorted(_VALID_WAIVER_TYPES)}",
            )
        return v

    @field_validator("currency")
    @classmethod
    def _check_currency(cls, v: str) -> str:
        return _validate_currency(v) or ""

    @field_validator("notes")
    @classmethod
    def _strip_notes(cls, v: str | None) -> str | None:
        return _strip_crlf(v)


# ── GC claim rollup (subcontractor pay applications -> prime progress claim) ──
#
# Read-only shapes for ``GET /progress-claims/{claim_id}/rollup`` and its
# siblings. Money is Decimal and serialises as a string; every figure is in the
# claim's currency, and a pay application in another currency is counted as
# skipped rather than converted or blended.


class IncludePaymentApplicationsRequest(BaseModel):
    """Pay applications a person has chosen to roll into one GC progress claim."""

    payment_application_ids: list[UUID] = Field(..., min_length=1, max_length=200)


class SubWaiverState(BaseModel):
    """What the lien waivers on file for one pay application amount to.

    ``state`` is the strongest payment waiver present: ``unconditional`` beats
    ``conditional`` beats ``none``. Tax forms (W-9 / W-8) never count.
    ``covers_net`` mirrors the payment gate: the largest waiver amount is at
    least the pay application's net. ``through_date`` is the latest day any
    waiver of that state releases, read from the waiver's own through-date and
    falling back to its signing date for waivers filed before the through-date
    existed (``through_date_basis`` says which).
    """

    state: str = "none"
    amount_covered: Decimal = Decimal("0")
    covers_net: bool = False
    through_date: date | None = None
    through_date_basis: str | None = None


class SubWithholdingTerms(BaseModel):
    """What a withholding scheme takes from a payment no certificate covers."""

    scheme: str
    rate_pct: str
    vat_included: bool = True
    # Small-amount limit per payee and calendar year, when the scheme has one.
    annual_limit: Decimal | None = None
    currency: str = ""
    reference: str | None = None


class SubPaymentDateFinding(BaseModel):
    """A certificate the law reads on the payment day, judged for one pay application.

    ``state`` is ``missing``, ``expired`` or ``revoked`` for a paid pay
    application the certificate did not cover on ``judged_on``; ``undated``
    for one marked paid without a payment date; and, while it is unpaid,
    ``pending`` (the certificate on file runs until ``valid_until``),
    ``pending_open`` (it has no end date) or ``pending_invalid`` (nothing on
    file could cover a payment made after the period end). Nothing is
    deducted: ``withholding`` states what the law takes, a person acts on it.
    """

    document_type: str
    state: str
    judged_on: date | None = None
    lapsed_on: date | None = None
    valid_until: date | None = None
    withholding: SubWithholdingTerms | None = None


class SubRollupPayApp(BaseModel):
    """One subcontractor pay application as the GC's claim sees it."""

    payment_application_id: UUID
    application_number: str
    agreement_id: UUID
    agreement_title: str = ""
    subcontractor_id: UUID
    subcontractor_name: str = ""
    status: str
    period_start: date | None = None
    period_end: date | None = None
    currency: str = ""
    gross_amount: Decimal = Decimal("0")
    net_amount: Decimal = Decimal("0")
    claimed_amount: Decimal = Decimal("0")
    certified_amount: Decimal = Decimal("0")
    approved_amount: Decimal = Decimal("0")
    # Lines the pay application carries. With none it bills nothing on the
    # claim, even though approving it approves its gross for payment.
    line_count: int = 0
    progress_claim_id: UUID | None = None
    # ``True`` / ``False`` when the claim has a period to compare against;
    # ``None`` when it has none yet, so nothing is asserted either way.
    in_period: bool | None = None
    requires_lien_waiver: bool = False
    waiver: SubWaiverState = Field(default_factory=SubWaiverState)
    # ``None`` when the claim has no period end to judge the certificates on.
    certificates_ok: bool | None = None
    certificate_findings: list[ComplianceDetail] = Field(default_factory=list)
    foreign_currency: bool = False
    # Set only when the national pack reads a certificate on the payment day.
    # ``paid_on`` is the UTC day the pay application was marked paid.
    paid_on: date | None = None
    payment_date_findings: list[SubPaymentDateFinding] | None = None
    certificates_pending_payment: bool | None = None


class SubRollupRow(BaseModel):
    """One pay application's contribution to one GC schedule-of-values line."""

    payment_application_id: UUID
    application_number: str
    agreement_id: UUID
    subcontractor_id: UUID
    subcontractor_name: str = ""
    status: str
    claimed_amount: Decimal = Decimal("0")
    certified_amount: Decimal = Decimal("0")
    approved_amount: Decimal = Decimal("0")
    waiver_state: str = "none"
    waiver_covers_net: bool = False
    certificates_ok: bool | None = None
    # ``True`` while a certificate read on the payment day waits for that day.
    certificates_pending_payment: bool | None = None


class SubRollupLine(BaseModel):
    """One GC schedule-of-values line with the subcontract billing under it."""

    contract_line_id: UUID
    code: str = ""
    description: str = ""
    scheduled_value: Decimal = Decimal("0")
    gc_period_value: Decimal = Decimal("0")
    sub_period_approved: Decimal = Decimal("0")
    sub_approved_to_date: Decimal = Decimal("0")
    # GC figure minus the subs' approved figure for this period. Positive means
    # the GC bills more on the line than its subs were approved for.
    variance: Decimal = Decimal("0")
    exceeds_scheduled_value: bool = False
    subs: list[SubRollupRow] = Field(default_factory=list)


class SubRollupUnmappedLine(BaseModel):
    """A pay-application line that resolves to no billable GC line."""

    payment_application_id: UUID
    application_number: str
    line_id: UUID
    work_package_id: UUID
    work_package_name: str = ""
    approved_amount: Decimal = Decimal("0")
    claimed_amount: Decimal = Decimal("0")
    # ``none`` (nothing mapped), ``foreign_line`` (mapped to a line that is not
    # on this contract's schedule of values) or ``parent_line`` (mapped to a
    # roll-up line, which is never billed directly).
    reason: str = "none"
    contract_line_id: UUID | None = None


class SubRollupAgreement(BaseModel):
    """How one subcontract agreement on the project resolves to a prime contract."""

    agreement_id: UUID
    title: str = ""
    subcontractor_id: UUID
    subcontractor_name: str = ""
    prime_contract_id: UUID | None = None
    # ``explicit`` (the agreement names it), ``single_active_client`` (the one
    # active client contract on the project), ``ambiguous`` (several, and the
    # agreement names none) or ``none`` (no active client contract at all).
    resolution: str = "none"


class SubPaymentRequirementsResponse(BaseModel):
    """What a subcontractor must hold before being paid, and where that came from."""

    certificate_types: list[str] = Field(default_factory=list)
    lien_waiver_required: bool = False
    # ``pack`` when a national regional pack answered, ``fallback`` when the
    # module's built-in list applied because no pack did.
    source: str = "fallback"
    reference: str | None = None
    # The certificate types read on the payment day rather than the period end.
    payment_date_types: list[str] = Field(default_factory=list)


class ClaimSubRollupResponse(BaseModel):
    """Everything the subcontractors billed under one GC progress claim."""

    claim_id: UUID
    contract_id: UUID
    project_id: UUID
    claim_status: str
    currency: str = ""
    period_from: date | None = None
    period_to: date | None = None
    # ``dates`` when the claim carries typed period dates, ``parsed`` when they
    # were read from its period strings, ``explicit_only`` when neither exists
    # and only pay applications a person included are considered.
    period_matching: str = "explicit_only"
    as_of: date | None = None
    lines: list[SubRollupLine] = Field(default_factory=list)
    included: list[SubRollupPayApp] = Field(default_factory=list)
    candidates: list[SubRollupPayApp] = Field(default_factory=list)
    unmapped_lines: list[SubRollupUnmappedLine] = Field(default_factory=list)
    agreements: list[SubRollupAgreement] = Field(default_factory=list)
    requirements: SubPaymentRequirementsResponse = Field(default_factory=SubPaymentRequirementsResponse)
    skipped_foreign_currency: int = 0
    sub_period_approved_total: Decimal = Decimal("0")
    gc_period_total: Decimal = Decimal("0")


class SuggestedClaimLineItem(BaseModel):
    """One claim line suggested from the subcontractors' approved amounts.

    Same fields as the contracts module's progress preview item, so the claim
    page can show both through one preview and commit both through the one
    existing commit route. ``observed_pct`` is the cumulative percent complete
    that the subs' approved-to-date amount represents on the line, clamped to
    0-100 because the commit route refuses anything above 100.

    ``origin`` says where the row came from: ``subcontract`` for a suggestion,
    ``existing`` for a line already on the claim that no subcontractor covers.
    The commit route replaces every line on the claim, so an existing line left
    out of the preview would be deleted by committing it; carrying it unchanged
    is what keeps the GC's own work on the bill.
    """

    contract_line_id: UUID
    contract_line_code: str = ""
    contract_line_description: str = ""
    boq_position_id: UUID | None = None
    unit: str | None = None
    contract_quantity: Decimal = Decimal("0")
    contract_line_value: Decimal = Decimal("0")
    observed_pct: Decimal = Decimal("0")
    period_label: str | None = None
    recorded_at: datetime | None = None
    period_completed_qty: Decimal = Decimal("0")
    period_completed_value: Decimal = Decimal("0")
    cumulative_completed_value: Decimal = Decimal("0")
    origin: str = "subcontract"
    # What the claim carries on this line today, so a reviewer can see what a
    # suggestion would replace. ``None`` when the claim has no line there yet.
    current_period_value: Decimal | None = None


class SuggestedClaimLinesResponse(BaseModel):
    """Preview payload for ``GET /progress-claims/{claim_id}/rollup/suggested-lines``.

    ``skipped_unlinked`` counts subcontract lines that map to no billable GC
    line, ``skipped_foreign_currency`` those in a currency other than the
    claim's. ``skipped_no_progress`` is always zero here and exists only so the
    shape matches the progress preview.
    """

    claim_id: UUID
    contract_id: UUID
    currency: str = ""
    items: list[SuggestedClaimLineItem] = Field(default_factory=list)
    skipped_unlinked: int = 0
    skipped_no_progress: int = 0
    skipped_foreign_currency: int = 0
    gross: Decimal = Decimal("0")
    retention: Decimal = Decimal("0")
    prior_claims_total: Decimal = Decimal("0")
    net_due: Decimal = Decimal("0")
