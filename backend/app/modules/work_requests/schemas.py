# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Work Requests request bodies.

Shapes only: the real validation (dates, users, stages, request types,
disciplines) lives in the service so that every entry point - API, a
future importer, a test - is refused the same way. Responses are plain
dicts built by ``service.payloads`` / ``service.department_payload``.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.work_requests.models import (
    MAX_BOQ_POSITIONS,
    MAX_BULK_IDS,
    MAX_CHECKLIST_ITEMS,
    MAX_COMMENT_CHARS,
    MAX_REQUEST_TYPES,
    MAX_TEXT_CHARS,
    MAX_TITLE_CHARS,
)

FieldType = Literal["text", "area", "date", "number", "bool", "select", "url"]
Priority = Literal["low", "normal", "high", "urgent"]


class StageSpec(BaseModel):
    key: str = Field(max_length=40)
    name: str = Field(max_length=120)
    colour: str = Field(default="slate", max_length=30)
    order: int | None = None
    closes: bool = False


class FieldSpec(BaseModel):
    key: str = Field(max_length=60)
    label: str = Field(default="", max_length=200)
    type: FieldType = "text"
    options: list[str] = Field(default_factory=list, max_length=100)
    required: bool = False


class ChecklistSpec(BaseModel):
    """One tick-box a request type declares. ``key`` is slugged from the
    label when it is left out, exactly like a request type's own key."""

    key: str | None = Field(default=None, max_length=60)
    label: str = Field(max_length=200)
    required: bool = False


class RequestTypeSpec(BaseModel):
    key: str = Field(max_length=60)
    label: str = Field(default="", max_length=200)
    disciplines: list[str] = Field(default_factory=list, max_length=20)
    fields: list[FieldSpec] = Field(default_factory=list, max_length=60)
    #: The tick-boxes a request of this type must work through. Required
    #: ones gate the closing stage.
    checklist: list[ChecklistSpec] = Field(default_factory=list, max_length=MAX_CHECKLIST_ITEMS)
    #: Retiring a type is ``active: false`` - never a delete, so the
    #: requests already raised against it keep their label and fields.
    active: bool = True
    position: int = Field(default=0, ge=0, le=1000)


class RequestTypeCreate(BaseModel):
    """``POST /departments/{key}/request-types``. The key is slugged from
    the label when it is left out."""

    key: str | None = Field(default=None, max_length=60)
    label: str = Field(max_length=200)
    disciplines: list[str] = Field(default_factory=list, max_length=20)
    fields: list[FieldSpec] = Field(default_factory=list, max_length=60)
    checklist: list[ChecklistSpec] = Field(default_factory=list, max_length=MAX_CHECKLIST_ITEMS)
    active: bool = True
    position: int | None = Field(default=None, ge=0, le=1000)


class RequestTypePatch(BaseModel):
    """Only the keys sent are changed. The type's key is fixed for life."""

    label: str | None = Field(default=None, max_length=200)
    disciplines: list[str] | None = Field(default=None, max_length=20)
    fields: list[FieldSpec] | None = Field(default=None, max_length=60)
    checklist: list[ChecklistSpec] | None = Field(default=None, max_length=MAX_CHECKLIST_ITEMS)
    active: bool | None = None
    position: int | None = Field(default=None, ge=0, le=1000)


class RequestTypeOrder(BaseModel):
    keys: list[str] = Field(default_factory=list, max_length=200)


class DepartmentCreate(BaseModel):
    key: str = Field(max_length=40)
    name: str = Field(max_length=120)
    #: Optional 2-5 letter reference token; derived from the key when absent.
    prefix: str | None = Field(default=None, max_length=5)
    colour: str = Field(default="slate", max_length=30)
    description: str = Field(default="", max_length=MAX_TEXT_CHARS)
    active: bool = True
    lead_user_id: str | None = Field(default=None, max_length=36)
    member_ids: list[str] = Field(default_factory=list, max_length=200)
    hourly_rate: str | None = Field(default=None, max_length=20)
    #: Turnaround target in WORKING days from acceptance; null = none.
    target_days: int | None = Field(default=None, ge=0, le=365)
    stages: list[StageSpec] = Field(default_factory=list, max_length=40)
    request_types: list[RequestTypeSpec] = Field(default_factory=list, max_length=60)


class DepartmentPatch(BaseModel):
    """Only the keys sent are changed. ``key`` and ``prefix`` are fixed."""

    name: str | None = Field(default=None, max_length=120)
    colour: str | None = Field(default=None, max_length=30)
    description: str | None = Field(default=None, max_length=MAX_TEXT_CHARS)
    active: bool | None = None
    position: int | None = Field(default=None, ge=0, le=1000)
    lead_user_id: str | None = Field(default=None, max_length=36)
    member_ids: list[str] | None = Field(default=None, max_length=200)
    hourly_rate: str | None = Field(default=None, max_length=20)
    target_days: int | None = Field(default=None, ge=0, le=365)
    stages: list[StageSpec] | None = Field(default=None, max_length=40)
    request_types: list[RequestTypeSpec] | None = Field(default=None, max_length=60)


class LinkSpec(BaseModel):
    label: str = Field(default="", max_length=200)
    url: str = Field(max_length=2000)


class RequestCreate(BaseModel):
    project_id: uuid.UUID
    department: str = Field(max_length=40)
    #: One request may need several types at once (FDS + PLC + SCADA).
    #: Send ``request_types``; ``request_type`` remains for the callers
    #: that only ever send one, and becomes the first of the list.
    request_type: str = Field(default="", max_length=60)
    request_types: list[str] | None = Field(default=None, max_length=MAX_REQUEST_TYPES)
    title: str = Field(max_length=MAX_TITLE_CHARS)
    description: str = Field(default="", max_length=MAX_TEXT_CHARS)
    cost_centres: dict[str, str] = Field(default_factory=dict)
    estimated_hours: dict[str, float] = Field(default_factory=dict)
    quoted_hours: float | None = None
    info_required_by: date | None = None
    due_date: date | None = None
    priority: Priority = "normal"
    links: list[LinkSpec] = Field(default_factory=list, max_length=50)
    fields: dict[str, Any] = Field(default_factory=dict)
    assignee_ids: list[str] = Field(default_factory=list, max_length=50)
    responsible_user_id: str | None = Field(default=None, max_length=36)
    depends_on_ids: list[str] = Field(default_factory=list, max_length=100)
    parent_id: str | None = Field(default=None, max_length=36)
    #: Save without submitting - required fields are not enforced yet.
    draft: bool = False


class RequestPatch(BaseModel):
    """Only the keys sent are changed (``exclude_unset``)."""

    title: str | None = Field(default=None, max_length=MAX_TITLE_CHARS)
    description: str | None = Field(default=None, max_length=MAX_TEXT_CHARS)
    request_type: str | None = Field(default=None, max_length=60)
    request_types: list[str] | None = Field(default=None, max_length=MAX_REQUEST_TYPES)
    cost_centres: dict[str, str] | None = None
    estimated_hours: dict[str, float] | None = None
    quoted_hours: float | None = None
    hours_to_complete: float | None = None
    info_required_by: date | None = None
    due_date: date | None = None
    scheduled_start: date | None = None
    scheduled_end: date | None = None
    delivered_at: date | None = None
    tested_at: date | None = None
    priority: Priority | None = None
    links: list[LinkSpec] | None = Field(default=None, max_length=50)
    fields: dict[str, Any] | None = None
    planner_uploaded: bool | None = None
    assignee_ids: list[str] | None = Field(default=None, max_length=50)
    responsible_user_id: str | None = Field(default=None, max_length=36)
    depends_on_ids: list[str] | None = Field(default=None, max_length=100)
    parent_id: str | None = Field(default=None, max_length=36)
    status: str | None = Field(default=None, max_length=20)
    status_note: str | None = Field(default=None, max_length=2000)
    stage: str | None = Field(default=None, max_length=60)
    stage_note: str | None = Field(default=None, max_length=2000)
    #: The programme activity this work feeds and the estimate lines it
    #: draws on - both must be on this request's own job.
    schedule_activity_id: str | None = Field(default=None, max_length=36)
    boq_position_ids: list[str] | None = Field(default=None, max_length=MAX_BOQ_POSITIONS)
    #: A template is kept to copy from and is left out of every list.
    is_template: bool | None = None


class ChecklistTick(BaseModel):
    """``POST /requests/{id}/checklist`` - tick or untick one item."""

    key: str = Field(min_length=1, max_length=60)
    done: bool = True


class ChecklistItemAdd(BaseModel):
    """``POST /requests/{id}/checklist/items`` - one item on THIS request.

    The key is slugged from the label server-side; ``after_key`` puts it
    straight after an item already on the list instead of at the end.
    """

    label: str = Field(min_length=1, max_length=200)
    required: bool = False
    after_key: str | None = Field(default=None, max_length=60)


class ChecklistItemPatch(BaseModel):
    """``PATCH /requests/{id}/checklist/items/{key}``. Only the keys sent
    are changed; the item's key is fixed (the ticks are keyed by it)."""

    label: str | None = Field(default=None, max_length=200)
    required: bool | None = None


class ChecklistOrder(BaseModel):
    """``PUT /requests/{id}/checklist/order`` - the order this request
    reads its list in. Keys left out keep their relative order, at the
    end."""

    keys: list[str] = Field(default_factory=list, max_length=MAX_CHECKLIST_ITEMS)


class DuplicateBody(BaseModel):
    """``POST /requests/{id}/duplicate``. Both keys optional: the copy
    keeps the title and the job unless told otherwise."""

    title: str | None = Field(default=None, max_length=MAX_TITLE_CHARS)
    project_id: uuid.UUID | None = None


class BulkPatch(BaseModel):
    """The only keys a bulk edit may set. ``extra=forbid`` on purpose: a
    key this does not know would otherwise be dropped in silence."""

    model_config = ConfigDict(extra="forbid")

    assignee_ids: list[str] | None = Field(default=None, max_length=50)
    responsible_user_id: str | None = Field(default=None, max_length=36)
    stage: str | None = Field(default=None, max_length=60)
    status: str | None = Field(default=None, max_length=20)
    due_date: date | None = None
    priority: Priority | None = None


class BulkBody(BaseModel):
    """``POST /requests/bulk``. At most ``MAX_BULK_IDS`` ids; the service
    refuses a longer list with a sentence rather than a schema error."""

    ids: list[str] = Field(default_factory=list, max_length=MAX_BULK_IDS * 5)
    patch: BulkPatch = Field(default_factory=BulkPatch)


class StageMove(BaseModel):
    stage: str = Field(max_length=60)
    note: str = Field(default="", max_length=2000)


class AssignBody(BaseModel):
    assignee_ids: list[str] = Field(default_factory=list, max_length=50)
    responsible_user_id: str | None = Field(default=None, max_length=36)


class NeedsInfoBody(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_COMMENT_CHARS)


class AnswerBody(BaseModel):
    answer: str = Field(min_length=1, max_length=MAX_COMMENT_CHARS)


class HandoffBody(BaseModel):
    department: str = Field(max_length=40)
    request_type: str = Field(default="", max_length=60)
    request_types: list[str] | None = Field(default=None, max_length=MAX_REQUEST_TYPES)
    title: str | None = Field(default=None, max_length=MAX_TITLE_CHARS)
    description: str | None = Field(default=None, max_length=MAX_TEXT_CHARS)
    due_date: date | None = None
    info_required_by: date | None = None
    copy_links: bool = True


class HoursBody(BaseModel):
    date: date
    hours: float = Field(gt=0, le=24)
    note: str = Field(default="", max_length=2000)
    #: Log on somebody else's behalf (department or manager only).
    user_id: str | None = Field(default=None, max_length=36)


class CommentBody(BaseModel):
    body: str = Field(min_length=1, max_length=MAX_COMMENT_CHARS)
    mention_ids: list[str] = Field(default_factory=list, max_length=50)


class PlannerAllocBody(BaseModel):
    #: ``{"2026-09-07": 2, "2026-09-08": 0}`` - zero clears the day.
    alloc: dict[str, float | None] = Field(default_factory=dict)


class WorkRequestListResponse(BaseModel):
    """A page of rows, and how many rows the filters actually matched.

    The rows themselves stay plain dicts, because that is what the whole
    module answers with and a row model here would be a second description
    of a payload the service already owns. What the envelope adds is the
    one thing an array cannot say: whether the caller is holding all of it.
    """

    items: list[dict[str, Any]] = Field(default_factory=list)
    total: int = 0
    limit: int
    offset: int
