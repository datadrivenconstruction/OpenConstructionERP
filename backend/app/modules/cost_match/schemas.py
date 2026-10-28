# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Cost-match Pydantic schemas - request / response models.

Money and quantities are ``Decimal`` in memory and serialise as strings, per
the platform's "Decimal as string" contract: a unit rate that crosses the wire
as a JSON number loses precision in every JavaScript client that reads it.

Confidence is also serialised as a string for the same reason. It is a
four-decimal ``Decimal`` in the database and a float in the pure matcher, and
letting it drift between the two representations is how a "0.75" boundary
becomes 0.7499999999999999 in a client-side comparison.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.modules.cost_match.models import (
    DECISION_KINDS,
    DECISION_STATES,
    RUN_STATUSES,
    TIERS,
)

# Patterns built from the model vocabulary so the API and the database can
# never drift apart on what a tier or a decision is called.
TIER_PATTERN = "|".join(TIERS)
DECISION_STATE_PATTERN = "|".join(DECISION_STATES)
DECISION_KIND_PATTERN = "|".join(DECISION_KINDS)
RUN_STATUS_PATTERN = "|".join(RUN_STATUSES)

# A pasted bill is reviewed by a person, one line at a time. Beyond this the
# submission stops being a review queue and becomes a data migration, which
# wants a different (asynchronous) shape than a request/response endpoint.
MAX_BATCH_LINES = 500


def _decimal_to_str(value: Decimal | None) -> str | None:
    """Serialise a Decimal without float coercion (``None`` stays ``None``)."""
    if value is None:
        return None
    return format(Decimal(value), "f")


# ── Submitting a batch ──────────────────────────────────────────────────────


class MatchLineInput(BaseModel):
    """One free-text line from the foreign bill.

    ``description`` is deliberately allowed to be blank. A pasted bill really
    does contain empty and header-only rows, and dropping them at the schema
    boundary would hide them from the reviewer and from the
    ``cost_match.source_description_present`` rule that exists to report them.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    description: str = Field(default="", max_length=4000)
    unit: str = Field(default="", max_length=40)
    quantity: Decimal | None = Field(default=None, ge=0)
    # The subcontractor's own item code, if their bill carried one. Used to
    # widen retrieval (a code hit is pulled into the candidate pool) but never
    # to decide a tier on its own - a code that matches with a description
    # that does not is exactly the case a reviewer must see.
    source_ref: str = Field(default="", max_length=100)


class MatchRunCreate(BaseModel):
    """Submit a batch of descriptions for matching against one cost base.

    The base is pinned by ``cost_source`` plus optionally ``region`` and
    ``catalog_id``. There is no server-side "currently active base" to inherit
    from - the platform tracks that client side - so the caller states which
    base the bill is being priced against and the run remembers it.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    name: str = Field(default="", max_length=255)
    source_label: str = Field(default="", max_length=255)
    source_locale: str = Field(default="en", max_length=12)
    cost_source: str = Field(default="cwicr", min_length=1, max_length=50)
    region: str | None = Field(default=None, max_length=50)
    catalog_id: UUID | None = None
    candidate_limit: int = Field(default=40, ge=5, le=200)
    notes: str | None = None
    tenant_id: UUID | None = None
    lines: list[MatchLineInput] = Field(..., min_length=1, max_length=MAX_BATCH_LINES)


class MatchRunUpdate(BaseModel):
    """Patch the reviewer-editable metadata of a run.

    The pinned base, the line count and every scored figure are not patchable:
    they are what the run *is*. Re-pointing a finished review at a different
    cost base would invalidate every snapshot already taken.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, max_length=255)
    source_label: str | None = Field(default=None, max_length=255)
    status: str | None = Field(default=None, pattern=rf"^({RUN_STATUS_PATTERN})$")
    notes: str | None = None


# ── Reading results ─────────────────────────────────────────────────────────


class MatchCandidate(BaseModel):
    """A runner-up cost item kept on the result so an override is a pick.

    Mirrors the snapshot shape of the winning suggestion, so the reviewer
    compares like with like and the override endpoint can be handed an id
    straight out of this list.
    """

    cost_item_id: UUID | None = None
    code: str = ""
    description: str = ""
    unit: str = ""
    rate: Decimal | None = None
    currency: str = ""
    confidence: Decimal = Decimal("0")
    band: str = ""
    reason_codes: list[str] = Field(default_factory=list)

    @field_serializer("rate", "confidence")
    def _ser_decimal(self, value: Decimal | None) -> str | None:
        return _decimal_to_str(value)


class MatchDecisionResponse(BaseModel):
    """One ruling from the append-only history of a result."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    result_id: UUID
    run_id: UUID
    seq: int
    decision: str
    tier_at_decision: str
    confidence_at_decision: Decimal
    decided_cost_item_id: UUID | None = None
    decided_code: str
    decided_description: str
    decided_unit: str
    decided_rate: Decimal | None = None
    decided_currency: str
    decided_by: UUID | None = None
    note: str | None = None
    created_at: datetime

    @field_serializer("confidence_at_decision", "decided_rate")
    def _ser_decimal(self, value: Decimal | None) -> str | None:
        return _decimal_to_str(value)


class MatchResultResponse(BaseModel):
    """One source line with its suggestion, its evidence and its rulings."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_id: UUID
    project_id: UUID
    line_no: int
    source_ref: str
    source_description: str
    source_unit: str
    source_quantity: Decimal | None = None
    tier: str
    confidence: Decimal
    tie: bool
    hint_code: str
    reason_codes: list[str] = Field(default_factory=list)
    factors: dict[str, Any] = Field(default_factory=dict)
    alternatives: list[MatchCandidate] = Field(default_factory=list)
    suggested_cost_item_id: UUID | None = None
    suggested_code: str
    suggested_description: str
    suggested_unit: str
    suggested_rate: Decimal | None = None
    suggested_currency: str
    decision_state: str
    decisions: list[MatchDecisionResponse] = Field(default_factory=list)
    # Rendered from ``reason_codes`` in the caller's locale. Not stored:
    # persisting the sentence would freeze one language into the database.
    explanation: str = ""
    hint: str | None = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("confidence", "source_quantity", "suggested_rate")
    def _ser_decimal(self, value: Decimal | None) -> str | None:
        return _decimal_to_str(value)


class MatchRunCounts(BaseModel):
    """Aggregated state of one run, computed from its results in SQL.

    Never stored. A persisted counter and the rows it summarises drift the
    first time anything writes outside the service, and a review screen that
    says "3 pending" over an empty queue destroys trust in the whole feature.
    """

    total: int = 0
    exact: int = 0
    high_confidence: int = 0
    needs_review: int = 0
    unmatched: int = 0
    pending: int = 0
    confirmed: int = 0
    overridden: int = 0
    rejected: int = 0
    # Pending results in the tiers that require a person before anything can
    # be priced. This is the length of the review queue.
    queue_length: int = 0


class MatchRunResponse(BaseModel):
    """A run header with its aggregated counts."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    source_label: str
    source_locale: str
    cost_source: str
    region: str | None = None
    catalog_id: UUID | None = None
    status: str
    item_count: int
    candidate_limit: int
    created_by: UUID | None = None
    tenant_id: UUID | None = None
    notes: str | None = None
    counts: MatchRunCounts = Field(default_factory=MatchRunCounts)
    created_at: datetime
    updated_at: datetime


class MatchResultPage(BaseModel):
    """One page of results plus the totals the pager needs."""

    run_id: UUID
    total: int
    offset: int
    limit: int
    items: list[MatchResultResponse] = Field(default_factory=list)


# ── Deciding ────────────────────────────────────────────────────────────────


class MatchDecisionCreate(BaseModel):
    """A person's ruling on one result.

    ``confirmed`` accepts the suggestion as it stands and needs no item id.
    ``overridden`` requires ``cost_item_id`` - that is what makes it an
    override rather than a confirmation. ``rejected`` records that nothing in
    this base fits, which is a real and useful answer: it takes the line out
    of the queue without inventing a rate for it.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    decision: str = Field(..., pattern=rf"^({DECISION_KIND_PATTERN})$")
    cost_item_id: UUID | None = None
    note: str | None = Field(default=None, max_length=2000)


# ── Validation report ───────────────────────────────────────────────────────


class CostMatchFinding(BaseModel):
    """One failing rule, ready for the traffic-light review panel."""

    rule_id: str
    severity: str
    category: str
    message: str
    key: str
    element_ref: str | None = None
    suggestion: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class CostMatchValidationReport(BaseModel):
    """The ``cost_match`` rule set collapsed into the module's response shape."""

    target_type: str
    target_id: Any = None
    status: str
    error_count: int = 0
    warning_count: int = 0
    info_count: int = 0
    passed_count: int = 0
    findings: list[CostMatchFinding] = Field(default_factory=list)
    unsupported_rule_sets: list[str] = Field(default_factory=list)
