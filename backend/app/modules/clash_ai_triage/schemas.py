# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍Pydantic schemas for the clash AI triage module."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer


# ── v3 §10 money serialisation helper ─────────────────────────────────────
# Mirrors backend/app/modules/boq/schemas.py — money fields are stored /
# accepted as Decimal but emitted as plain decimal strings in JSON.
def _serialise_money(v: Decimal | None) -> str | None:
    if v is None:
        return None
    if not isinstance(v, Decimal):
        try:
            v = Decimal(str(v))
        except (InvalidOperation, ValueError):
            return "0"
    if not v.is_finite():
        return "0"
    return format(v, "f")


# ── Enumerations ────────────────────────────────────────────────────────────
# Tuples are exported so service-layer validators can ``in``-check without
# importing the Literal alias type.

TRIAGE_CATEGORIES: tuple[str, ...] = (
    "real_design_flaw",
    "expected_intersection",
    "tolerance_artifact",
    "modeling_error",
    "duplicate",
    "unclear",
)
TRIAGE_SEVERITIES: tuple[str, ...] = ("critical", "high", "medium", "low")
TRIAGE_SUBJECT_TYPES: tuple[str, ...] = ("clash", "clash_issue")
TRIAGE_SUGGESTED_ACTIONS: tuple[str, ...] = (
    "reroute_pipe",
    "add_sleeve",
    "accept_intersection",
    "ignore_duplicate",
    "escalate_to_designer",
    "request_more_info",
)

# Mirror the same tuples as Literal aliases for Pydantic ``Field`` typing.
TriageCategory = Literal[
    "real_design_flaw",
    "expected_intersection",
    "tolerance_artifact",
    "modeling_error",
    "duplicate",
    "unclear",
]
TriageSeverity = Literal["critical", "high", "medium", "low"]
TriageSubjectType = Literal["clash", "clash_issue"]
TriageSuggestedAction = Literal[
    "reroute_pipe",
    "add_sleeve",
    "accept_intersection",
    "ignore_duplicate",
    "escalate_to_designer",
    "request_more_info",
]


# ── Verdict (raw LLM JSON output, post-validation) ─────────────────────────


class TriageVerdict(BaseModel):
    """The structured JSON the LLM is asked to produce.

    Used as the parse-validation target inside the service before the
    verdict is folded into a persisted ``ClashTriageResult``. Lives in
    this module rather than the ``ai`` module because the schema is
    specific to clash triage.
    """

    category: TriageCategory
    confidence: float = Field(ge=0.0, le=1.0)
    severity_suggested: TriageSeverity = "medium"
    explanation: str = ""
    suggested_action: TriageSuggestedAction | None = None
    model_evidence_used: list[str] = Field(default_factory=list)


# ── Persisted triage row response ──────────────────────────────────────────


class TriageResultResponse(BaseModel):
    """Wire shape of a persisted ``ClashTriageResult`` row."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    subject_type: TriageSubjectType
    subject_id: uuid.UUID
    clash_id: uuid.UUID | None = None
    model_name: str
    prompt_version: str
    category: TriageCategory
    confidence: float
    severity_suggested: TriageSeverity
    explanation: str
    suggested_action: TriageSuggestedAction | None = None
    model_evidence_used: list[str] = Field(default_factory=list)
    tokens_used: int = 0
    # v3 §10 — money is Decimal-as-string on the wire. The DB column is
    # Float (small USD values, no precision risk) but the contract stays
    # uniform with every other money field.
    cost_usd_estimate: Decimal = Decimal("0")
    created_by_user_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("cost_usd_estimate", when_used="json")
    def _ser_cost_usd_estimate(self, v: Decimal) -> str | None:
        return _serialise_money(v)


# ── Request shapes ─────────────────────────────────────────────────────────


class TriageBatchRequest(BaseModel):
    """Request body for ``POST /clash-ai-triage/batch``."""

    clash_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    # Bounded concurrency so an absent-minded "triage everything" call
    # cannot stampede the LLM provider with hundreds of in-flight calls.
    max_concurrent: int = Field(default=4, ge=1, le=16)
    force_refresh: bool = False


class TriageReplayRequest(BaseModel):
    """Request body for ``POST /clash-ai-triage/replay/{id}``.

    ``prompt_version`` defaults to the current ``PROMPT_VERSION`` so the
    common case ("re-run with whatever prompt is in the repo now") needs
    no payload.
    """

    prompt_version: str | None = None


# ── Prompt-templates response ──────────────────────────────────────────────


class PromptTemplatesResponse(BaseModel):
    """Read-only view of the current prompt templates.

    Returned by ``GET /clash-ai-triage/prompts/current`` so the UI can
    show the coordinator what prompt would be used for a triage call.
    No write endpoint — tuning the prompt is a deliberate code change +
    ``PROMPT_VERSION`` bump.
    """

    prompt_version: str
    system_prompt: str
    user_prompt_template: str


# ── Paginated history ──────────────────────────────────────────────────────


class TriageHistoryPage(BaseModel):
    """Paginated wrapper for a clash's triage history."""

    items: list[TriageResultResponse]
    total: int
    page: int = 1
    page_size: int = 50
