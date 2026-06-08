"""‌⁠‍Change Order Pydantic schemas - request/response models.

Defines create, update, and response schemas for change orders and their items.
Monetary values (cost_impact, cost_delta, quantities, rates) are exposed as
canonical decimal *strings* on the wire (matching the ``finance`` module
contract) and stored as ``String(50)`` in the SQLite-compatible models.
Floats are deliberately avoided to prevent silent binary-rounding loss on
money values.
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Bound ints at PostgreSQL INT4 max - anything above is clearly bad input and
# would overflow the underlying column.
_INT32_MAX = 2_147_483_647


def _validate_decimal(v: str, field_name: str = "value") -> str:
    """‌⁠‍Validate that a string is a valid decimal number (allows negative - CO
    cost impacts can be credits)."""
    try:
        Decimal(v)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Invalid decimal value for {field_name}: {v!r}") from exc
    return v


def _validate_non_negative_decimal(v: str, field_name: str = "value") -> str:
    """‌⁠‍Validate that a string is a valid non-negative decimal number."""
    try:
        d = Decimal(v)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Invalid decimal value for {field_name}: {v!r}") from exc
    if d < 0:
        raise ValueError(f"{field_name} must be non-negative, got {v!r}")
    return v


def _decimal_to_str(v: object) -> object:
    """Response-side coercion: turn ORM ``Decimal`` / numeric values into
    canonical strings. Non-Decimal, non-numeric inputs pass through untouched."""
    if isinstance(v, Decimal):
        return format(v, "f")
    if isinstance(v, (int, float)):
        return format(Decimal(str(v)), "f")
    return v


# ── Change Order schemas ─────────────────────────────────────────────────────


class ChangeOrderCreate(BaseModel):
    """‌⁠‍Create a new change order."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    project_id: UUID
    title: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="", max_length=5000)
    reason_category: str = Field(
        default="client_request",
        pattern=r"^(client_request|design_change|unforeseen|regulatory|error)$",
    )
    schedule_impact_days: int = Field(default=0, ge=0, le=_INT32_MAX)
    # Empty when the caller does not specify one - the service resolves it
    # from the project's currency. NEVER default to a literal "EUR" here
    # (task #217): that silently mis-stamps non-Eurozone projects.
    currency: str = Field(default="", max_length=10)
    # BUG-385: cost_impact was silently dropped at create time because
    # it wasn't on the schema. Accept it here for the common manual-entry
    # case; when line items are added ``add_item`` will still recompute.
    cost_impact: str | None = Field(
        default=None,
        max_length=50,
        description="Optional initial cost impact (signed decimal string, e.g. '1250.50'). Recomputed from items when items are added.",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChangeOrderUpdate(BaseModel):
    """‌⁠‍Partial update for a change order.

    Status transitions must go through the dedicated action endpoints
    (``/submit``, ``/approve``, ``/reject``). Sending ``status`` here
    returns 422 instead of silently ignoring it - the silent-ignore
    behaviour was :bug:`385` and made the whole CO workflow look
    non-functional.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    reason_category: str | None = Field(
        default=None,
        pattern=r"^(client_request|design_change|unforeseen|regulatory|error)$",
    )
    schedule_impact_days: int | None = Field(default=None, ge=0, le=_INT32_MAX)
    currency: str | None = Field(default=None, max_length=10)
    cost_impact: str | None = Field(default=None, max_length=50)
    metadata: dict[str, Any] | None = None
    # T3: commitment / RFI links are mutable while the CO is in draft.
    linked_po_ids: list[UUID] | None = Field(default=None, max_length=50)
    linked_rfi_ids: list[UUID] | None = Field(default=None, max_length=50)
    status: str | None = Field(
        default=None,
        description="Reserved - use /submit, /approve, /reject to change status.",
    )

    @field_validator("status")
    @classmethod
    def _reject_status_in_patch(cls, v: str | None) -> str | None:
        if v is not None:
            raise ValueError(
                "Status cannot be changed via PATCH. Use POST /changeorders/{id}/submit, /approve, or /reject."
            )
        return v


class ChangeOrderItemResponse(BaseModel):
    """Change order item returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    change_order_id: UUID
    description: str
    change_type: str
    original_quantity: str = "0"
    new_quantity: str = "0"
    original_rate: str = "0"
    new_rate: str = "0"
    cost_delta: str = "0"
    unit: str
    sort_order: int
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime

    _coerce_decimal = field_validator(
        "original_quantity",
        "new_quantity",
        "original_rate",
        "new_rate",
        "cost_delta",
        mode="before",
    )(lambda cls, v: _decimal_to_str(v))


class ChangeOrderResponse(BaseModel):
    """Change order returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    code: str
    title: str
    description: str
    reason_category: str
    status: str
    submitted_by: str | None = None
    approved_by: str | None = None
    # BUG-351: rejection writes its own dedicated columns (never reuses
    # ``approved_*``). Exposing them on the wire lets the UI render an honest
    # "Rejected by X on DATE" card. A CO rejected straight from 'submitted'
    # sets only ``rejected_*`` - without these fields the rejection was
    # invisible to users.
    rejected_by: str | None = None
    submitted_at: str | None = None
    approved_at: str | None = None
    rejected_at: str | None = None
    cost_impact: str = "0"
    schedule_impact_days: int = 0
    currency: str
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime
    item_count: int = 0

    _coerce_decimal = field_validator("cost_impact", mode="before")(lambda cls, v: _decimal_to_str(v))
    # T3: construction management platform style commitment / RFI links + approval-chain cursor.
    # Normalised to ``[]`` on read so legacy COs that pre-date v3082
    # (where the columns are physically NULL) still serialize cleanly.
    linked_po_ids: list[str] = Field(default_factory=list)
    linked_rfi_ids: list[str] = Field(default_factory=list)
    current_approval_step: int | None = None


class ChangeOrderWithItems(ChangeOrderResponse):
    """Change order response including all line items."""

    items: list[ChangeOrderItemResponse] = []


# ── Item schemas ─────────────────────────────────────────────────────────────


class ChangeOrderItemCreate(BaseModel):
    """Create a new change order item."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    description: str = Field(..., min_length=1, max_length=5000)
    change_type: str = Field(
        default="modified",
        pattern=r"^(added|removed|modified)$",
    )
    original_quantity: str = Field(default="0", max_length=50)
    new_quantity: str = Field(default="0", max_length=50)
    original_rate: str = Field(default="0", max_length=50)
    new_rate: str = Field(default="0", max_length=50)
    unit: str = Field(default="", max_length=20)
    sort_order: int = Field(default=0, ge=0, le=_INT32_MAX)
    metadata: dict[str, Any] = Field(default_factory=dict)

    _coerce_in = field_validator(
        "original_quantity",
        "new_quantity",
        "original_rate",
        "new_rate",
        mode="before",
    )(lambda cls, v: _decimal_to_str(v))

    @field_validator("original_quantity", "new_quantity", "original_rate", "new_rate")
    @classmethod
    def _check_non_negative_decimal(cls, v: str) -> str:
        return _validate_non_negative_decimal(v)


class ChangeOrderItemUpdate(BaseModel):
    """Partial update for a change order item."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    description: str | None = Field(default=None, min_length=1, max_length=5000)
    change_type: str | None = Field(
        default=None,
        pattern=r"^(added|removed|modified)$",
    )
    original_quantity: str | None = Field(default=None, max_length=50)
    new_quantity: str | None = Field(default=None, max_length=50)
    original_rate: str | None = Field(default=None, max_length=50)
    new_rate: str | None = Field(default=None, max_length=50)
    unit: str | None = Field(default=None, max_length=20)
    sort_order: int | None = Field(default=None, ge=0, le=_INT32_MAX)
    metadata: dict[str, Any] | None = None

    _coerce_in = field_validator(
        "original_quantity",
        "new_quantity",
        "original_rate",
        "new_rate",
        mode="before",
    )(lambda cls, v: _decimal_to_str(v))

    @field_validator("original_quantity", "new_quantity", "original_rate", "new_rate")
    @classmethod
    def _check_non_negative_decimal(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _validate_non_negative_decimal(v)


# ── Approval-chain schemas (T3 - construction management platform style multi-step approval) ──


class ApprovalStartRequest(BaseModel):
    """Start a multi-step approval chain on a change order.

    ``approver_user_ids`` is the ordered list of approvers (step 1 acts
    first, then step 2, etc.). Duplicates are allowed in case the same
    user must sign off twice at different stages; the service enforces
    a minimum of one approver.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    approver_user_ids: list[UUID] = Field(..., min_length=1, max_length=20)


class ApprovalAdvanceRequest(BaseModel):
    """Record the current approver's decision on a chain step."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    decision: str = Field(..., pattern=r"^(approved|rejected)$")
    comments: str | None = Field(default=None, max_length=2000)


class ApprovalRow(BaseModel):
    """One row in a change order's approval chain."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    change_order_id: UUID
    step_order: int
    approver_user_id: UUID | None = None
    decision: str
    decided_at: datetime | None = None
    comments: str | None = None
    created_at: datetime


# ── Summary schema ───────────────────────────────────────────────────────────


class ChangeOrderSummary(BaseModel):
    """Aggregated change order stats for a project."""

    total: int = 0
    total_orders: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    by_type: dict[str, int] = Field(default_factory=dict)
    draft_count: int = 0
    submitted_count: int = 0
    approved_count: int = 0
    rejected_count: int = 0
    total_approved_amount: str = "0"
    total_cost_impact: str = "0"
    total_time_impact_days: int = 0
    total_schedule_impact_days: int = 0
    # The project's BASE currency - the only currency ``total_cost_impact`` /
    # ``total_approved_amount`` are expressed in. Empty only when the project
    # carries no currency - never a literal "EUR" (task #217).
    currency: str = ""
    # Approved change orders priced in a FOREIGN currency that has no FX rate
    # in ``Project.fx_rates`` are excluded from the base-currency total (money
    # rule: never blend currencies without conversion) and surfaced here,
    # grouped by their own ISO code as decimal strings, e.g. {"USD": "5000.00"}.
    unconverted_by_currency: dict[str, str] = Field(default_factory=dict)

    _coerce_decimal = field_validator("total_approved_amount", "total_cost_impact", mode="before")(
        lambda cls, v: _decimal_to_str(v)
    )


# ── What-If impact simulator (TOP-30 #11) ────────────────────────────────────


class SimulateImpactRequest(BaseModel):
    """Run a what-if impact projection for a change order.

    Both fields are optional overrides: when omitted the simulator uses the
    change order's own stored ``cost_impact`` / ``schedule_impact_days`` so a
    plain ``POST`` with an empty body forecasts the order exactly as it stands.
    Supplying a value lets the user explore "what if this CO were worth X / ran
    Y days longer" before committing to it. Nothing is persisted by a simulate
    call - it is a read-only projection.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    cost_impact: str | None = Field(
        default=None,
        max_length=50,
        description="Optional signed decimal override for the CO cost impact, in the CO's own currency.",
    )
    schedule_impact_days: int | None = Field(
        default=None,
        ge=0,
        le=_INT32_MAX,
        description="Optional override for the number of calendar days this CO adds to the programme.",
    )

    @field_validator("cost_impact")
    @classmethod
    def _check_decimal(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _validate_decimal(v, "cost_impact")


class ImpactCost(BaseModel):
    """Cost side of an impact projection, all in the project base currency."""

    budget_before: str = "0"
    budget_after: str = "0"
    delta: str = "0"
    pct_of_budget: float = 0.0


class ImpactSchedule(BaseModel):
    """Schedule side of an impact projection."""

    current_end_date: str | None = None
    projected_end_date: str | None = None
    days_added: int = 0
    finish_moves: bool = False


class ImpactEVM(BaseModel):
    """Earned-value projection before and after the change order is applied."""

    bac_before: str = "0"
    bac_after: str = "0"
    eac_before: str = "0"
    eac_after: str = "0"
    vac_before: str = "0"
    vac_after: str = "0"
    spi: str = "0"
    cpi: str = "0"


class ImpactBOQ(BaseModel):
    """Preview of what approving the CO would write into the project BOQ."""

    item_count: int = 0
    sections_added: int = 0
    positions_added: int = 0
    target_boq_name: str | None = None


class SimulateImpactResponse(BaseModel):
    """Full what-if impact projection for a change order."""

    order_id: UUID
    code: str
    base_currency: str = ""
    as_of: str
    co_cost_native: str = "0"
    co_currency: str = ""
    co_cost_base: str = "0"
    fx_converted: bool = True
    cost: ImpactCost
    schedule: ImpactSchedule
    evm: ImpactEVM
    boq: ImpactBOQ
    notes: list[str] = Field(default_factory=list)


# ── AI / heuristic draft from free text, RFI or daily log (TOP-30 #11) ───────


class AIDraftRequest(BaseModel):
    """Draft a change order from a piece of source text.

    The text can come from an RFI thread, a daily-diary entry, or be pasted
    free-hand. When an AI provider key is configured the text is sent to the
    model for structured extraction; otherwise a deterministic heuristic reads
    the obvious cost/schedule signals so the feature still produces a usable
    draft offline. Nothing is saved - the response is a review-ready proposal
    the user confirms (or edits) before a change order is actually created.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    project_id: UUID
    source_kind: str = Field(
        default="free_text",
        pattern=r"^(free_text|rfi|daily_log)$",
    )
    source_id: UUID | None = None
    source_text: str = Field(..., min_length=1, max_length=20000)
    currency: str = Field(default="", max_length=10)


class AIDraftLine(BaseModel):
    """One suggested change-order line item in a draft proposal."""

    description: str = ""
    unit: str = ""
    quantity: str = "0"
    rate: str = "0"
    cost_delta: str = "0"
    confidence: int = Field(default=0, ge=0, le=100)


class AIDraftResponse(BaseModel):
    """A review-ready change-order draft (never auto-saved)."""

    title: str = ""
    description: str = ""
    reason_category: str = "client_request"
    cost_impact: str = "0"
    schedule_impact_days: int = 0
    currency: str = ""
    lines: list[AIDraftLine] = Field(default_factory=list)
    confidence: int = Field(default=0, ge=0, le=100)
    ai_used: bool = False
    provider: str = ""
    source_kind: str = "free_text"
    source_id: UUID | None = None
    note: str = ""
