# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""ERP Chat Pydantic schemas - request/response models."""

import re
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: A BCP-47-like language tag as the UI sends it: "de", "pt-BR", "fil", "zh-Hant-TW".
_LOCALE_TAG = re.compile(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*")
MAX_LOCALE_LENGTH = 16
MAX_ROUTE_LENGTH = 200


class ChatClientContext(BaseModel):
    """Where the person is in the app when they send a message.

    A hint for the prompt and never a reason to refuse the message, so a value
    that does not fit is dropped or cut rather than rejected with a 422. The
    server checks ``project_id`` against the person's access before the model
    sees anything about that project.
    """

    route: str | None = Field(default=None, description="Current path in the app; cut to 200 characters.")
    project_id: UUID | None = Field(default=None, description="Project open in the app, if any.")

    @field_validator("route", mode="before")
    @classmethod
    def _cut_route(cls, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        return value.strip()[:MAX_ROUTE_LENGTH] or None

    @field_validator("project_id", mode="before")
    @classmethod
    def _drop_malformed_project_id(cls, value: Any) -> UUID | None:
        if isinstance(value, UUID):
            return value
        try:
            return UUID(str(value)) if value else None
        except ValueError:
            return None


class StreamChatRequest(BaseModel):
    """Request body for the streaming chat endpoint.

    ``locale`` and ``client_context`` describe the person's screen (UI language,
    current route, open project). Like the context itself they are hints: a
    malformed locale is ignored instead of failing the request.
    """

    model_config = ConfigDict(from_attributes=True)

    session_id: UUID | None = None
    message: str = Field(..., min_length=1, max_length=5000)
    project_id: UUID | None = None
    conversation_history: list[dict] | None = None
    locale: str | None = Field(default=None, description="UI language as a BCP-47 tag, e.g. 'de' or 'pt-BR'.")
    client_context: ChatClientContext | None = None

    @field_validator("locale", mode="before")
    @classmethod
    def _normalise_locale(cls, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        tag = value.strip().replace("_", "-")
        if len(tag) > MAX_LOCALE_LENGTH or not _LOCALE_TAG.fullmatch(tag):
            return None
        return tag

    @field_validator("client_context", mode="before")
    @classmethod
    def _drop_malformed_context(cls, value: Any) -> Any:
        return value if isinstance(value, dict | ChatClientContext) else None


class ChatSessionResponse(BaseModel):
    """Chat session returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    project_id: UUID | None = None
    title: str
    created_at: datetime
    updated_at: datetime


class ChatSessionCreate(BaseModel):
    """Create a new chat session."""

    model_config = ConfigDict(from_attributes=True)

    project_id: UUID | None = None
    title: str = "New Chat"


class ChatMessageResponse(BaseModel):
    """Chat message returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    role: str
    content: str | None = None
    # The stream stores one entry per tool call, so these are lists; a dict is
    # still accepted for a row written in the single-object shape.
    tool_calls: list[dict[str, Any]] | dict[str, Any] | None = None
    tool_results: list[dict[str, Any]] | dict[str, Any] | None = None
    renderer: str | None = None
    # The primary tool result's ``data``: a list for table-like tools.
    renderer_data: dict[str, Any] | list[Any] | None = None
    tokens_used: int = 0
    created_at: datetime


class SessionListResponse(BaseModel):
    """Paginated list of chat sessions."""

    model_config = ConfigDict(from_attributes=True)

    items: list[ChatSessionResponse]
    total: int


# ── T8: feedback + admin observability ─────────────────────────────────────


class FeedbackRequest(BaseModel):
    """Body for ``POST /v1/erp_chat/messages/{id}/feedback``."""

    model_config = ConfigDict(from_attributes=True)

    # +1 = thumbs up, -1 = thumbs down. We deliberately do *not* accept 0 -
    # to clear feedback the frontend should DELETE (future) or just leave
    # the row in place; "no rating" is the absence of a row.
    rating: Literal[-1, 1]
    comment: str | None = Field(default=None, max_length=2000)


class FeedbackResponse(BaseModel):
    """Echo of the persisted feedback row."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    message_id: UUID
    user_id: UUID | None = None
    rating: int
    comment: str | None = None
    created_at: datetime
    updated_at: datetime


class DailyChatStat(BaseModel):
    """One row of the admin-stats daily breakdown."""

    model_config = ConfigDict(from_attributes=True)

    date: str  # ISO date "YYYY-MM-DD"
    messages: int
    thumbs_up: int
    thumbs_down: int
    tokens: int


class NegativePromptSnippet(BaseModel):
    """One of the top user-prompts that received a thumbs-down."""

    model_config = ConfigDict(from_attributes=True)

    snippet: str  # First 120 chars of the user-prompt
    thumbs_down: int  # How many distinct downvotes the linked turn drew
    message_id: UUID | None = None


class AdminStatsResponse(BaseModel):
    """Admin observability rollup over a ``window_days`` window."""

    model_config = ConfigDict(from_attributes=True)

    window_days: int
    total_messages: int
    total_thumbs_up: int
    total_thumbs_down: int
    feedback_rate_pct: float  # % of assistant messages with any rating
    total_tokens_input: int
    total_tokens_output: int
    cache_hit_rate_pct: float  # % of turns where provider reported cache_hit=True
    top_negative_prompts: list[NegativePromptSnippet]
    daily_breakdown: list[DailyChatStat]


# ── AI actions: proposals a person applies, rejects or undoes ─────────────
#
# The contract the dock renders. Values in ``ActionField.value`` / ``before``
# are raw data, never pre-formatted: numbers and money are JSON numbers, dates
# are ISO ``YYYY-MM-DD`` strings, enums carry their stored value and the option
# list carries the labels. The frontend formats them in the reader's locale.

ActionStatus = Literal["proposed", "applied", "rejected", "failed", "reverted"]
ActionFieldKind = Literal["text", "longtext", "number", "money", "date", "enum", "percent", "ref"]


class ActionFieldOption(BaseModel):
    """One choice of an ``enum`` field.

    A fixed choice (a priority, a task type) has an i18n ``label_key``. A data
    choice (a project member) has none, and its ``label`` is shown as it is.
    """

    value: str
    label_key: str | None = None
    label: str


class ActionField(BaseModel):
    """One row of a proposal's field table.

    ``key`` is the payload key a PATCH writes to. ``before`` is set only for an
    edit of an existing record and holds the value the proposal was based on.
    """

    key: str
    label_key: str
    label: str
    kind: ActionFieldKind
    value: Any = None
    before: Any = None
    currency: str | None = None
    unit: str | None = None
    options: list[ActionFieldOption] | None = None
    editable: bool = False
    required: bool = False


class ActionNote(BaseModel):
    """Something the person should know before applying, shown under the fields.

    ``key`` is an i18n key; ``text`` is its English rendering with ``params``
    already filled in, and ``params`` are passed to the translation as-is.
    ``field`` names the field the note is about, when there is one.
    """

    key: str
    text: str
    params: dict[str, Any] = Field(default_factory=dict)
    field: str | None = None
    tone: Literal["info", "warning"] = "info"


class ActionEntityRef(BaseModel):
    """A record an action points at (its target) or produced (its result)."""

    entity_type: str
    entity_id: str
    label: str | None = None
    url: str | None = None


class ActionUserRef(BaseModel):
    """A person in an action's story, with the name to show."""

    id: UUID
    name: str


class ChatActionCounts(BaseModel):
    """How many visible actions sit in each status (under the same filters)."""

    proposed: int = 0
    applied: int = 0
    rejected: int = 0
    failed: int = 0
    reverted: int = 0


class ChatActionResponse(BaseModel):
    """A proposal and its lifecycle, as the dock renders it.

    ``can_*`` are computed for the caller: they are what the caller may do
    now, under the same gates the record's REST route would run for them.
    ``blocked_reason_key`` explains a pending action the caller cannot apply.
    """

    id: UUID
    session_id: UUID | None = None
    message_id: UUID | None = None
    project_id: UUID | None = None
    project_name: str | None = None
    action_type: str
    status: ActionStatus
    title: str
    title_key: str
    summary: str | None = None
    subtitle: str | None = None
    fields: list[ActionField] = Field(default_factory=list)
    notes: list[ActionNote] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    original_payload: dict[str, Any] = Field(default_factory=dict)
    edited: bool = False
    confidence: float | None = None
    rationale: str | None = None
    target: ActionEntityRef | None = None
    result: ActionEntityRef | None = None
    requested_by: ActionUserRef | None = None
    decided_by: ActionUserRef | None = None
    decided_at: datetime | None = None
    reverted_by: ActionUserRef | None = None
    reverted_at: datetime | None = None
    decision_note: str | None = None
    revert_note: str | None = None
    error: str | None = None
    error_code: str | None = None
    can_apply: bool = False
    can_edit: bool = False
    can_reject: bool = False
    can_revert: bool = False
    blocked_reason_key: str | None = None
    blocked_reason: str | None = None
    revert_hint_key: str | None = None
    revert_hint: str | None = None
    batch_id: str | None = None
    created_at: datetime
    updated_at: datetime


class ChatActionListResponse(BaseModel):
    """A page of visible actions plus per-status counts for the filter pills."""

    items: list[ChatActionResponse]
    total: int
    counts: ChatActionCounts


class ChatActionPatchRequest(BaseModel):
    """Human edits to a pending proposal: a partial payload, merged and re-validated."""

    payload: dict[str, Any] = Field(..., description="Partial payload; keys must be editable fields.")


class ChatActionDecisionRequest(BaseModel):
    """Optional note for a reject or an undo."""

    note: str | None = Field(default=None, max_length=2000)


class ChatActionBatchRequest(BaseModel):
    """Apply several proposals; each one succeeds or fails on its own."""

    ids: list[UUID] = Field(..., min_length=1, max_length=50)


class ChatActionBatchError(BaseModel):
    """Why one id of a batch was not applied (the others are unaffected)."""

    id: UUID
    status_code: int
    code: str
    message: str
    message_key: str


class ChatActionBatchResponse(BaseModel):
    """Result of an apply-all: every visible action in its new state, plus refusals."""

    items: list[ChatActionResponse]
    errors: list[ChatActionBatchError] = Field(default_factory=list)
