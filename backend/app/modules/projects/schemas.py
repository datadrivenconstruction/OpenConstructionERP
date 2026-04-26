"""Project Pydantic schemas for request/response validation."""

import re
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_CURRENCY_CODE_RE = re.compile(r"^[A-Z]{3}$")
_DECIMAL_RE = re.compile(r"^[0-9]+(\.[0-9]+)?$")
_UNIT_CODE_RE = re.compile(r"^[A-Za-z0-9._/²³-]{1,20}$")

# Valid date formats accepted by the platform (ISO 8601 preferred)
_DATE_FORMATS = ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d.%m.%Y", "%m/%d/%Y")


def _validate_fx_rates(value: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    """Validate the ``fx_rates`` JSON list shape (RFC 37, Issues #88/#93).

    Each entry must be a dict with:

    * ``code`` — 3-letter uppercase ISO 4217 currency code
    * ``rate`` — positive decimal-string (units of base per 1 unit of foreign)
    * ``label`` — optional human label (≤64 chars)

    Duplicate codes within a single project are rejected — the UI relies on
    unique codes for the per-resource dropdown. Stored on Project as JSON;
    we keep the dict shape rather than a structured Pydantic submodel so it
    survives round-trip through ``Project.fx_rates`` without coupling to a
    SQLAlchemy relationship.
    """
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("fx_rates must be a list of {code, rate, label} dicts")
    seen: set[str] = set()
    cleaned: list[dict[str, Any]] = []
    for entry in value:
        if not isinstance(entry, dict):
            raise ValueError("each fx_rates entry must be an object")
        code = str(entry.get("code", "")).strip().upper()
        rate = str(entry.get("rate", "")).strip()
        label = str(entry.get("label") or "").strip()[:64]
        if not _CURRENCY_CODE_RE.match(code):
            raise ValueError(f"fx_rates: '{code}' is not a 3-letter currency code")
        if code in seen:
            raise ValueError(f"fx_rates: duplicate currency '{code}'")
        if not _DECIMAL_RE.match(rate):
            raise ValueError(f"fx_rates: '{rate}' is not a decimal number for {code}")
        # Reject zero rates outright — division by zero would crash rollups
        # and a literal 0 has no plausible business meaning either.
        try:
            from decimal import Decimal

            if Decimal(rate) <= 0:
                raise ValueError(f"fx_rates: rate for {code} must be positive")
        except (ValueError, ArithmeticError) as exc:
            raise ValueError(f"fx_rates: invalid rate for {code}: {exc}") from exc
        seen.add(code)
        cleaned.append({"code": code, "rate": rate, "label": label})
    return cleaned


def _validate_vat_rate(value: str | None) -> str | None:
    """Validate ``default_vat_rate``: positive decimal string ≤100.

    Empty string is treated as None so a UI that clears the field results
    in the regional default being used again (matching the column's
    nullable contract).
    """
    if value is None:
        return None
    cleaned = str(value).strip()
    if cleaned == "":
        return None
    if not _DECIMAL_RE.match(cleaned):
        raise ValueError("default_vat_rate must be a positive decimal (e.g. '21' or '8.25')")
    from decimal import Decimal

    rate = Decimal(cleaned)
    if rate < 0 or rate > 100:
        raise ValueError("default_vat_rate must be between 0 and 100")
    return cleaned


def _validate_custom_units(value: list[str] | None) -> list[str] | None:
    """Validate ``custom_units`` list (Issue #93 item 3).

    Each unit is a short alphanumeric token. Duplicates and ones already
    matching well-known canonical units (m, m2, kg) are still allowed —
    the frontend de-duplicates against its canonical list at render time.
    """
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("custom_units must be a list of strings")
    seen: set[str] = set()
    cleaned: list[str] = []
    for entry in value:
        s = str(entry).strip()
        if not s:
            continue
        if not _UNIT_CODE_RE.match(s):
            raise ValueError(f"custom_units: '{s}' is not a valid unit token (≤20 chars, no spaces)")
        if s in seen:
            continue
        seen.add(s)
        cleaned.append(s)
    return cleaned


def _validate_date_string(value: str | None, field_name: str) -> str | None:
    """Validate that a date string can be parsed to a real date.

    Accepts ISO 8601 (2026-01-15), European (15.01.2026), US (01/15/2026).
    Returns the original string unchanged if valid.
    """
    if value is None:
        return None
    for fmt in _DATE_FORMATS:
        try:
            datetime.strptime(value.strip(), fmt)
            return value.strip()
        except ValueError:
            continue
    raise ValueError(
        f"{field_name}: '{value}' is not a valid date. Expected formats: YYYY-MM-DD, DD.MM.YYYY, or MM/DD/YYYY"
    )


# ── Create / Update ───────────────────────────────────────────────────────


class ProjectCreate(BaseModel):
    """Create a new project."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Project name (must be at least 1 character, HTML tags are rejected)",
        examples=["Residential Mitte"],
    )

    @field_validator("name", mode="after")
    @classmethod
    def reject_html_tags(cls, v: str) -> str:
        """Reject HTML tags so callers see a clear 422 instead of silent mutation.

        The previous revision silently stripped ``<...>`` sequences to prevent
        XSS. That kept the server safe but left the caller with a surprising
        delta between what they sent and what was persisted. Rejecting
        loudly preserves the XSS guarantee and stops the data from being
        quietly rewritten.
        """
        trimmed = v.strip()
        if _HTML_TAG_RE.search(trimmed):
            raise ValueError(
                "Project name contains HTML tags. Use plain text only."
            )
        return trimmed

    description: str = Field(
        default="",
        max_length=5000,
        description="Project scope description (max 5000 characters)",
        examples=["5-story residential building, 48 units, underground parking"],
    )

    @field_validator("description", mode="after")
    @classmethod
    def _strip_xss_from_description(cls, v: str) -> str:
        # BUG-326: long-form description field previously stored ``<script>``
        # and ``onerror=`` payloads verbatim. Silently stripping dangerous
        # HTML preserves legitimate text (``"beam <200mm"``) while killing
        # XSS vectors that target frontends using dangerouslySetInnerHTML.
        from app.core.sanitize import strip_dangerous_html

        return strip_dangerous_html(v)
    region: str = Field(
        default="",
        max_length=100,
        description="Region/market identifier (e.g. DACH, UK, US, Middle East). User must choose, no default bias",
        examples=["DACH"],
    )
    classification_standard: str = Field(
        default="",
        max_length=100,
        description="Classification standard identifier (e.g. din276, nrm, masterformat, uniclass)",
        examples=["din276"],
    )
    currency: str = Field(
        default="",
        max_length=10,
        description="ISO 4217 currency code (e.g. EUR, GBP, USD). User must choose, no default bias",
        examples=["EUR"],
    )
    locale: str = Field(
        default="en", max_length=10, description="UI locale code (e.g. en, de, fr)"
    )
    validation_rule_sets: list[str] = Field(
        default_factory=lambda: ["boq_quality"],
        description="List of validation rule set IDs to apply (e.g. boq_quality, din276, gaeb)",
    )

    # Phase 12 expansion fields (all optional)
    project_code: str | None = Field(default=None, max_length=50)
    project_type: str | None = Field(default=None, max_length=50)
    phase: str | None = Field(default=None, max_length=50)
    client_id: str | None = Field(default=None, max_length=36)
    parent_project_id: UUID | None = None
    address: dict[str, Any] | None = None
    contract_value: str | None = Field(default=None, max_length=50)
    planned_start_date: str | None = Field(default=None, max_length=20)
    planned_end_date: str | None = Field(default=None, max_length=20)
    actual_start_date: str | None = Field(default=None, max_length=20)
    actual_end_date: str | None = Field(default=None, max_length=20)
    budget_estimate: str | None = Field(default=None, max_length=50)
    contingency_pct: str | None = Field(default=None, max_length=10)
    custom_fields: dict[str, Any] | None = None
    work_calendar_id: str | None = Field(default=None, max_length=36)

    # ── v2.6.0 — multi-currency + per-project VAT (RFC 37) ───────────────
    fx_rates: list[dict[str, Any]] | None = Field(
        default=None,
        description=(
            "Additional currencies + decimal-string rates to base. Shape: "
            "[{code: 'USD', rate: '1200.50', label: 'US Dollar'}]. Empty/null "
            "means single-currency project."
        ),
    )
    default_vat_rate: str | None = Field(
        default=None,
        max_length=10,
        description=(
            "Per-project VAT override as decimal-string percentage (e.g. '21'). "
            "Null means use the regional template."
        ),
    )
    custom_units: list[str] | None = Field(
        default=None,
        description="Project-scoped unit codes not in the canonical frontend list.",
    )

    @field_validator("fx_rates", mode="after")
    @classmethod
    def _check_fx_rates(cls, v: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        return _validate_fx_rates(v)

    @field_validator("default_vat_rate", mode="after")
    @classmethod
    def _check_vat_rate(cls, v: str | None) -> str | None:
        return _validate_vat_rate(v)

    @field_validator("custom_units", mode="after")
    @classmethod
    def _check_custom_units(cls, v: list[str] | None) -> list[str] | None:
        return _validate_custom_units(v)

    @field_validator("planned_start_date", "planned_end_date", "actual_start_date", "actual_end_date")
    @classmethod
    def _validate_dates(cls, v: str | None, info: Any) -> str | None:
        return _validate_date_string(v, info.field_name)


class ProjectUpdate(BaseModel):
    """Update project fields. All optional — only provided fields are updated."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)

    @field_validator("name", mode="after")
    @classmethod
    def _reject_html_in_name(cls, v: str | None) -> str | None:
        if v is None:
            return v
        trimmed = v.strip()
        if _HTML_TAG_RE.search(trimmed):
            raise ValueError("Project name contains HTML tags. Use plain text only.")
        return trimmed

    @field_validator("description", mode="after")
    @classmethod
    def _strip_xss_from_description(cls, v: str | None) -> str | None:
        if v is None:
            return v
        from app.core.sanitize import strip_dangerous_html

        return strip_dangerous_html(v)
    region: str | None = Field(default=None, max_length=100)
    classification_standard: str | None = Field(default=None, max_length=100)
    currency: str | None = Field(default=None, max_length=10)
    locale: str | None = Field(default=None, max_length=10)
    validation_rule_sets: list[str] | None = None
    metadata: dict[str, Any] | None = None

    # Phase 12 expansion fields
    project_code: str | None = Field(default=None, max_length=50)
    project_type: str | None = Field(default=None, max_length=50)
    phase: str | None = Field(default=None, max_length=50)
    client_id: str | None = Field(default=None, max_length=36)
    parent_project_id: UUID | None = None
    address: dict[str, Any] | None = None
    contract_value: str | None = Field(default=None, max_length=50)
    planned_start_date: str | None = Field(default=None, max_length=20)
    planned_end_date: str | None = Field(default=None, max_length=20)
    actual_start_date: str | None = Field(default=None, max_length=20)
    actual_end_date: str | None = Field(default=None, max_length=20)
    budget_estimate: str | None = Field(default=None, max_length=50)
    contingency_pct: str | None = Field(default=None, max_length=10)
    custom_fields: dict[str, Any] | None = None
    work_calendar_id: str | None = Field(default=None, max_length=36)
    status: str | None = None

    # ── v2.6.0 — multi-currency + per-project VAT (RFC 37) ───────────────
    fx_rates: list[dict[str, Any]] | None = None
    default_vat_rate: str | None = Field(default=None, max_length=10)
    custom_units: list[str] | None = None

    @field_validator("fx_rates", mode="after")
    @classmethod
    def _check_fx_rates(cls, v: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        return _validate_fx_rates(v)

    @field_validator("default_vat_rate", mode="after")
    @classmethod
    def _check_vat_rate(cls, v: str | None) -> str | None:
        return _validate_vat_rate(v)

    @field_validator("custom_units", mode="after")
    @classmethod
    def _check_custom_units(cls, v: list[str] | None) -> list[str] | None:
        return _validate_custom_units(v)

    @field_validator("planned_start_date", "planned_end_date", "actual_start_date", "actual_end_date")
    @classmethod
    def _validate_dates(cls, v: str | None, info: Any) -> str | None:
        return _validate_date_string(v, info.field_name)

    @field_validator("name", mode="after")
    @classmethod
    def reject_html_tags(cls, v: str | None) -> str | None:
        if v is None:
            return None
        trimmed = v.strip()
        if _HTML_TAG_RE.search(trimmed):
            raise ValueError(
                "Project name contains HTML tags. Use plain text only."
            )
        return trimmed


# ── Response ──────────────────────────────────────────────────────────────


class ProjectResponse(BaseModel):
    """Project in API responses."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    name: str
    description: str
    region: str
    classification_standard: str
    currency: str
    locale: str
    validation_rule_sets: list[str]
    status: str
    owner_id: UUID
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime

    # Phase 12 expansion fields
    project_code: str | None = None
    project_type: str | None = None
    phase: str | None = None
    client_id: str | None = None
    parent_project_id: UUID | None = None
    address: dict[str, Any] | None = None
    contract_value: str | None = None
    planned_start_date: str | None = None
    planned_end_date: str | None = None
    actual_start_date: str | None = None
    actual_end_date: str | None = None
    budget_estimate: str | None = None
    contingency_pct: str | None = None
    custom_fields: dict[str, Any] | None = None
    work_calendar_id: str | None = None

    # ── v2.6.0 — multi-currency + per-project VAT (RFC 37) ───────────────
    fx_rates: list[dict[str, Any]] = Field(default_factory=list)
    default_vat_rate: str | None = None
    custom_units: list[str] = Field(default_factory=list)

    # BUG-MATH04: defence-in-depth response strip — see BOQResponse for the
    # full rationale. ``ProjectCreate`` rejects HTML in ``name`` outright
    # (loud 422) and only strips dangerous tags from ``description``;
    # benign tags stored before that fix or via non-HTTP paths are
    # neutralised here on the way out.
    @field_validator("name", "description", mode="after")
    @classmethod
    def _strip_html_on_response(cls, v: str) -> str:
        from app.core.sanitize import sanitise_text

        return sanitise_text(v) or ""


# ── WBS schemas ──────────────────────────────────────────────────────────


class WBSCreate(BaseModel):
    """Create a WBS node."""

    model_config = ConfigDict(str_strip_whitespace=True)

    parent_id: UUID | None = None
    code: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=255)
    name_translations: dict[str, str] | None = None
    level: int = Field(default=0, ge=0)
    sort_order: int = Field(default=0, ge=0)
    wbs_type: str = Field(default="cost", max_length=50)
    planned_cost: str | None = Field(default=None, max_length=50)
    planned_hours: str | None = Field(default=None, max_length=50)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WBSUpdate(BaseModel):
    """Partial update for a WBS node."""

    model_config = ConfigDict(str_strip_whitespace=True)

    parent_id: UUID | None = None
    code: str | None = Field(default=None, min_length=1, max_length=50)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    name_translations: dict[str, str] | None = None
    level: int | None = Field(default=None, ge=0)
    sort_order: int | None = Field(default=None, ge=0)
    wbs_type: str | None = Field(default=None, max_length=50)
    planned_cost: str | None = Field(default=None, max_length=50)
    planned_hours: str | None = Field(default=None, max_length=50)
    metadata: dict[str, Any] | None = None


class WBSResponse(BaseModel):
    """WBS node returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    parent_id: UUID | None
    code: str
    name: str
    name_translations: dict[str, str] | None = None
    level: int
    sort_order: int
    wbs_type: str
    planned_cost: str | None = None
    planned_hours: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Milestone schemas ────────────────────────────────────────────────────


_MILESTONE_STATUSES = ("pending", "in_progress", "completed", "cancelled")

# Allowed status transitions: from_status -> set of valid to_statuses
_MILESTONE_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"in_progress", "cancelled"},
    "in_progress": {"completed", "cancelled", "pending"},
    "completed": {"in_progress"},  # Allow reopening
    "cancelled": {"pending"},  # Allow reactivation
}


class MilestoneCreate(BaseModel):
    """Create a project milestone."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=255)
    milestone_type: str = Field(default="general", max_length=50)
    planned_date: str | None = Field(default=None, max_length=20)
    actual_date: str | None = Field(default=None, max_length=20)
    status: str = Field(default="pending", max_length=50)
    linked_payment_pct: str | None = Field(default=None, max_length=10)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("status")
    @classmethod
    def _validate_status(cls, v: str) -> str:
        if v not in _MILESTONE_STATUSES:
            raise ValueError(f"Invalid status '{v}'. Must be one of: {', '.join(_MILESTONE_STATUSES)}")
        return v

    @field_validator("planned_date")
    @classmethod
    def _validate_planned_date(cls, v: str | None) -> str | None:
        return _validate_date_string(v, "planned_date")

    @field_validator("actual_date")
    @classmethod
    def _validate_actual_date(cls, v: str | None) -> str | None:
        return _validate_date_string(v, "actual_date")


class MilestoneUpdate(BaseModel):
    """Partial update for a milestone."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    milestone_type: str | None = Field(default=None, max_length=50)
    planned_date: str | None = Field(default=None, max_length=20)
    actual_date: str | None = Field(default=None, max_length=20)
    status: str | None = Field(default=None, max_length=50)
    linked_payment_pct: str | None = Field(default=None, max_length=10)
    metadata: dict[str, Any] | None = None

    @field_validator("status")
    @classmethod
    def _validate_status(cls, v: str | None) -> str | None:
        if v is not None and v not in _MILESTONE_STATUSES:
            raise ValueError(f"Invalid status '{v}'. Must be one of: {', '.join(_MILESTONE_STATUSES)}")
        return v

    @field_validator("planned_date")
    @classmethod
    def _validate_planned_date(cls, v: str | None) -> str | None:
        return _validate_date_string(v, "planned_date")

    @field_validator("actual_date")
    @classmethod
    def _validate_actual_date(cls, v: str | None) -> str | None:
        return _validate_date_string(v, "actual_date")


class MilestoneResponse(BaseModel):
    """Milestone returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    name: str
    milestone_type: str
    planned_date: str | None = None
    actual_date: str | None = None
    status: str
    linked_payment_pct: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime
