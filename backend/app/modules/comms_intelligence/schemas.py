# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Pydantic schemas for the Comms Intelligence module.

The verdict coercer is the trust boundary between the LLM and the
database: whatever the model answered is clamped onto this schema or the
row is stored as a zero-confidence ``general`` verdict with the raw text
kept as the receipt.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.comms_intelligence.models import (
    ANALYSIS_CATEGORIES,
    DRAFT_KINDS,
)

_ISO_DATE_RX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_AMOUNT_RX = re.compile(r"^\d+(\.\d{1,4})?$")

#: Statuses the confirm endpoint may write onto a correspondence row -
#: the vocabulary the correspondence module itself uses.
CORRESPONDENCE_STATUSES = ("open", "awaiting_response", "responded", "closed")
CORRESPONDENCE_TYPES = ("letter", "email", "notice", "memo")


def _clean_iso_date(value: Any) -> str | None:
    if not isinstance(value, str) or not _ISO_DATE_RX.fullmatch(value.strip()):
        return None
    return value.strip()


class ExtractedPrice(BaseModel):
    amount: str = Field(min_length=1, max_length=20)
    currency: str = Field(default="", max_length=8)
    context: str = Field(default="", max_length=300)

    @field_validator("amount")
    @classmethod
    def _amount_is_canonical_money(cls, v: str) -> str:
        v = v.strip().replace(",", "")
        if not _AMOUNT_RX.fullmatch(v):
            raise ValueError("amount must be a plain decimal string")
        return v


class ExtractedDates(BaseModel):
    response_requested_by: str | None = None
    event_date: str | None = None

    @field_validator("response_requested_by", "event_date", mode="before")
    @classmethod
    def _iso_or_none(cls, v: Any) -> str | None:
        return _clean_iso_date(v)


class ExtractedCommitment(BaseModel):
    who: str = Field(default="", max_length=200)
    what: str = Field(default="", max_length=500)
    when: str | None = None

    @field_validator("when", mode="before")
    @classmethod
    def _iso_or_none(cls, v: Any) -> str | None:
        return _clean_iso_date(v)


class PackagePrice(BaseModel):
    """The single authoritative price of a quote, with its receipt."""

    amount: str = Field(min_length=1, max_length=20)
    #: "ex gst" | "inc gst" | "plus gst" | "" (no basis stated near the figure)
    basis: str = Field(default="", max_length=20)
    #: Verbatim ±90 chars around the figure - the words that justify it.
    evidence: str = Field(default="", max_length=400)

    @field_validator("amount")
    @classmethod
    def _amount_is_canonical_money(cls, v: str) -> str:
        v = v.strip().replace(",", "")
        if not _AMOUNT_RX.fullmatch(v):
            raise ValueError("amount must be a plain decimal string")
        return v


class ExtractedFacts(BaseModel):
    prices: list[ExtractedPrice] = Field(default_factory=list, max_length=20)
    package_price: PackagePrice | None = None
    lead_time: str = Field(default="", max_length=60)
    #: quote | query | other - the deterministic counting rule behind
    #: "2 of 3 quoted"; a supplier's question is never a quote.
    reply_kind: str = "other"
    quote_number: str | None = Field(default=None, max_length=40)
    reference_numbers: list[str] = Field(default_factory=list, max_length=30)
    dates: ExtractedDates = Field(default_factory=ExtractedDates)
    commitments: list[ExtractedCommitment] = Field(default_factory=list, max_length=20)

    @field_validator("reference_numbers")
    @classmethod
    def _bound_refs(cls, v: list[str]) -> list[str]:
        return [str(r)[:40] for r in v if str(r).strip()]

    @field_validator("reply_kind", mode="before")
    @classmethod
    def _known_kind(cls, v: Any) -> str:
        return v if v in ("quote", "query", "other") else "other"


class AnalysisSuggestions(BaseModel):
    set_status: str | None = None
    response_required_by: str | None = None
    link_rfi_id: str | None = None
    correspondence_type: str | None = None

    @field_validator("set_status", mode="before")
    @classmethod
    def _known_status_or_none(cls, v: Any) -> str | None:
        return v if v in CORRESPONDENCE_STATUSES else None

    @field_validator("correspondence_type", mode="before")
    @classmethod
    def _known_type_or_none(cls, v: Any) -> str | None:
        return v if v in CORRESPONDENCE_TYPES else None

    @field_validator("response_required_by", mode="before")
    @classmethod
    def _iso_or_none(cls, v: Any) -> str | None:
        return _clean_iso_date(v)

    @field_validator("link_rfi_id", mode="before")
    @classmethod
    def _uuid_or_none(cls, v: Any) -> str | None:
        try:
            return str(uuid.UUID(str(v)))
        except (ValueError, AttributeError, TypeError):
            return None


class AnalysisVerdict(BaseModel):
    """The coerced shape of one analysis pass (heuristic or AI)."""

    category: str = "general"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    summary: str = Field(default="", max_length=1000)
    extracted: ExtractedFacts = Field(default_factory=ExtractedFacts)
    reply_needed: bool = False
    suggestions: AnalysisSuggestions = Field(default_factory=AnalysisSuggestions)

    @field_validator("category", mode="before")
    @classmethod
    def _known_category(cls, v: Any) -> str:
        return v if v in ANALYSIS_CATEGORIES else "general"


# ── API payloads ─────────────────────────────────────────────────────────


class AnalyzeRequest(BaseModel):
    """Manual (re-)analysis trigger. ``use_ai=False`` re-runs heuristics only."""

    use_ai: bool = True


class ConfirmRequest(BaseModel):
    """Which suggestion keys to apply to the correspondence row.

    Partial confirmation is first-class: the reviewer unticks what the
    model got wrong and confirms the rest.
    """

    apply_status: bool = True
    apply_response_required_by: bool = True
    apply_link_rfi: bool = True
    apply_type: bool = False


class AnalysisRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    correspondence_id: str
    reference_number: str
    category: str
    confidence: float
    summary: str
    extracted: dict
    suggestions: dict
    reply_needed: bool
    status: str
    reviewed_by: str | None
    reviewed_at: str | None
    applied: dict
    source: str
    model_name: str
    prompt_version: str
    tokens_used: int
    created_at: Any = None
    updated_at: Any = None


class DraftRequest(BaseModel):
    kind: str = "reply"
    #: Free-text steer for the AI draft ("decline politely, we already
    #: awarded this package"). Ignored by template fallbacks.
    instructions: str = Field(default="", max_length=2000)
    use_ai: bool = True

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, v: str) -> str:
        if v not in DRAFT_KINDS:
            raise ValueError(f"kind must be one of {DRAFT_KINDS}")
        return v


class DraftRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    correspondence_id: str
    kind: str
    subject: str
    body: str
    confidence: float
    status: str
    source: str
    model_name: str
    created_at: Any = None


class DraftStatusUpdate(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def _accepted_or_dismissed(cls, v: str) -> str:
        if v not in ("accepted", "dismissed"):
            raise ValueError("status must be 'accepted' or 'dismissed'")
        return v


# ── Dashboard ────────────────────────────────────────────────────────────


class DashboardEntry(BaseModel):
    correspondence_id: str
    reference_number: str
    subject: str
    direction: str
    status: str
    response_required_by: str | None
    days_until_due: int | None
    from_contact_id: str | None
    category: str | None = None
    confidence: float | None = None


class DashboardRead(BaseModel):
    project_id: uuid.UUID
    pending_review: int
    reply_needed: int
    overdue: list[DashboardEntry]
    due_soon: list[DashboardEntry]
    awaiting_response: list[DashboardEntry]
    categories: dict[str, int]


class AnalysisListResponse(BaseModel):
    """A page of analyses and how many the project holds under the filter."""

    items: list[AnalysisRead] = Field(default_factory=list)
    total: int = 0
    limit: int
    offset: int


class DraftListResponse(BaseModel):
    """Every draft written against one message. The set is small and is
    never cut, so ``total`` and the page agree unless a window is asked
    for explicitly."""

    items: list[DraftRead] = Field(default_factory=list)
    total: int = 0
    limit: int
    offset: int
