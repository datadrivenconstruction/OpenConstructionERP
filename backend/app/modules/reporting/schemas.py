# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Reporting & Dashboards Pydantic schemas - request/response models."""

import html
import re
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ── R7 HTML-injection guard ──────────────────────────────────────────────
#
# Generated reports are rendered to PDF / HTML downstream (WeasyPrint or
# similar). User-supplied ``title`` / ``description`` strings flow into
# the renderer; if a future template embeds them inside HTML without
# auto-escaping, ``<script>`` / ``<iframe>`` / ``<img onerror=...>`` tags
# would execute in the email recipient's browser when they preview the
# rendered HTML, or - in WeasyPrint's CSS-only context - fetch arbitrary
# attacker-controlled assets at render time (SSRF + tracking pixels).
#
# We strip raw HTML tags at the schema layer so the row never lands in
# the DB with executable markup. This is belt-and-braces on top of any
# future ``{{ value | e }}`` auto-escaping in the template - a renderer
# regression at the template layer (e.g. ``{{ value | safe }}``) would
# otherwise re-introduce the vulnerability.

# Match any HTML tag (greedy enough to swallow ``<script src="...">..</script>``
# style payloads but not arithmetic ``a < b`` text). We also escape any
# stray ``<`` / ``>`` left over so downstream renderers see a literal
# entity, never an opening bracket.
_HTML_TAG_RE = re.compile(r"<[^>]*>")

# ── ISO 4217 currency shape guard ─────────────────────────────────────────
#
# Reports stamp a resolved ISO 4217 currency onto the generated row and into
# the ``data_snapshot`` so every money figure reads in a single, explicit
# currency (the platform never blends currencies). The caller-supplied
# ``override_currency`` is the highest-priority source in that resolution
# chain, so it must be a well-formed 3-letter code before it can win.
#
# Soft shape check (3 uppercase letters), not a closed ISO-4217 enum - this
# mirrors ``app.modules.projects.schemas._normalise_currency``: OpenEstimate
# is a global product and we do not want to reject a valid but obscure code
# just because it is not on a hand-maintained list. A 4-letter code such as
# ``"EURO"`` or a 2-letter code is still rejected with HTTP 422.
_CURRENCY_CODE_RE = re.compile(r"^[A-Z]{3}$")


def _normalise_override_currency(value: str | None) -> str | None:
    """Normalise / validate a caller-supplied ISO 4217 override.

    ``None`` / empty → ``None`` (inherit from project, then EUR fallback).
    A non-empty value is stripped, upper-cased, and shape-checked against
    ``^[A-Z]{3}$``. Anything that is not a 3-letter code raises
    ``ValueError`` so FastAPI surfaces it as HTTP 422 before the handler
    touches the database.
    """
    if value is None:
        return None
    code = value.strip().upper()
    if not code:
        return None
    if not _CURRENCY_CODE_RE.match(code):
        raise ValueError(
            f"override_currency: '{value}' is not a 3-letter ISO 4217 currency code "
            "(e.g. EUR, USD, GBP, JPY). Leave empty to inherit the project currency."
        )
    return code


def _strip_html(value: str) -> str:
    """Return *value* with HTML tags removed and ``<>&`` HTML-escaped.

    Two-pass: first ``<tag>`` removal, then ``html.escape`` of the
    leftover so a raw ``<`` (e.g. inside a math expression) still lands
    as ``&lt;`` rather than reaching the renderer raw.
    """
    if not value:
        return value
    stripped = _HTML_TAG_RE.sub("", value)
    return html.escape(stripped, quote=True)


# ── KPI Snapshot schemas ─────────────────────────────────────────────────


class KPISnapshotCreate(BaseModel):
    """Create a new KPI snapshot for a project."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    snapshot_date: str = Field(..., max_length=20, description="ISO date string (YYYY-MM-DD)")
    cpi: str | None = Field(default=None, max_length=20)
    spi: str | None = Field(default=None, max_length=20)
    budget_consumed_pct: str | None = Field(default=None, max_length=20)
    open_defects: int = 0
    open_observations: int = 0
    schedule_progress_pct: str | None = Field(default=None, max_length=20)
    open_rfis: int = 0
    open_submittals: int = 0
    risk_score_avg: str | None = Field(default=None, max_length=20)
    metadata: dict[str, Any] = Field(default_factory=dict)


class KPISnapshotResponse(BaseModel):
    """KPI snapshot returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    snapshot_date: str
    cpi: str | None = None
    spi: str | None = None
    budget_consumed_pct: str | None = None
    open_defects: int = 0
    open_observations: int = 0
    schedule_progress_pct: str | None = None
    open_rfis: int = 0
    open_submittals: int = 0
    risk_score_avg: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Report Template schemas ──────────────────────────────────────────────


class ReportTemplateCreate(BaseModel):
    """Create a custom report template.

    HTML-injection guard: ``name`` and ``description`` are sanitized at
    the schema layer (strip raw HTML tags + ``html.escape`` leftovers)
    because they end up in the PDF/HTML renderer downstream. See the
    module-level ``_strip_html`` doc for the threat model.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=255)
    name_translations: dict[str, str] | None = None
    report_type: str = Field(
        ...,
        pattern=r"^(project_status|cost_report|schedule_status|safety_report|inspection_report|portfolio_summary|progress_report)$",
    )
    description: str | None = None
    template_data: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name", "description")
    @classmethod
    def _sanitize_renderable(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _strip_html(v)


class ReportTemplateResponse(BaseModel):
    """Report template returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    name: str
    name_translations: dict[str, str] | None = None
    report_type: str
    description: str | None = None
    template_data: dict[str, Any] = Field(default_factory=dict)
    is_system: bool = False
    created_by: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    # Schedule fields (v2.3.0)
    schedule_cron: str | None = None
    recipients: list[str] = Field(default_factory=list)
    is_scheduled: bool = False
    last_run_at: str | None = None
    next_run_at: str | None = None
    project_id_scope: UUID | None = None
    created_at: datetime
    updated_at: datetime


# ── Schedule Request / Response (v2.3.0) ────────────────────────────────


class ReportScheduleRequest(BaseModel):
    """Turn a template into a scheduled report.

    Passing ``schedule_cron=None`` turns scheduling off without clearing
    the recipient list - the worker then skips the template on its
    next-due scan.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    schedule_cron: str | None = Field(
        default=None,
        max_length=100,
        description="5-field POSIX cron expression (e.g. '0 9 * * 1' for 09:00 every Mon)",
    )
    recipients: list[str] = Field(
        default_factory=list,
        description="Email addresses or user IDs that receive the rendered report",
    )
    project_id_scope: UUID | None = Field(
        default=None,
        description="Scope the report to one project; None = portfolio-wide",
    )
    is_scheduled: bool = Field(
        default=True,
        description="Pass False to pause without clearing the cron expression",
    )


# ── Generated Report schemas ─────────────────────────────────────────────


class GenerateReportRequest(BaseModel):
    """Request to generate a report.

    The ``title`` field is sanitized via ``_strip_html`` at the schema
    layer - it is the highest-risk user-controlled string in this
    module because it appears in every PDF / HTML rendering of the
    report. A future template that does ``{{ title | safe }}`` would
    otherwise execute attacker-supplied ``<script>`` in the recipient's
    email preview.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    template_id: UUID | None = None
    report_type: str = Field(
        ...,
        pattern=r"^(project_status|cost_report|schedule_status|safety_report|inspection_report|portfolio_summary|progress_report)$",
    )
    title: str = Field(..., min_length=1, max_length=500)
    format: str = Field(
        default="pdf",
        pattern=r"^(pdf|excel|html)$",
    )
    data_snapshot: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    override_currency: str | None = Field(
        default=None,
        max_length=10,
        description=(
            "ISO 4217 currency code (e.g. EUR, USD, GBP). When set it wins over "
            "the project's currency for this report. Leave empty to inherit the "
            "project currency (then the EUR fallback)."
        ),
        examples=["USD"],
    )

    @field_validator("title")
    @classmethod
    def _sanitize_title(cls, v: str) -> str:
        return _strip_html(v)

    @field_validator("override_currency", mode="after")
    @classmethod
    def _normalise_override_currency(cls, v: str | None) -> str | None:
        return _normalise_override_currency(v)


class GeneratedReportResponse(BaseModel):
    """Generated report returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    template_id: UUID | None = None
    report_type: str
    title: str
    generated_at: str
    generated_by: UUID | None = None
    format: str = "pdf"
    storage_key: str | None = None
    currency: str | None = None
    data_snapshot: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    published_at: datetime | None = None
    published_by: UUID | None = None
    created_at: datetime
    updated_at: datetime
