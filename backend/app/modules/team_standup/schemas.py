# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Team Standup Pydantic schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.team_standup.models import MAX_COMMENT_CHARS, MAX_FIELD_CHARS

#: The record kinds a task may link to - mirrors ``models.LINK_KINDS``
#: (kept in step by a test). ``request`` is a department work request.
LinkKind = Literal["", "rfi", "rfq", "order", "vo", "del", "tbx", "request", "mail"]
#: Public = the whole team; private = creator, assignee and admins only.
TaskVisibility = Literal["public", "private"]


class EntryUpsert(BaseModel):
    """Save my update for one day. The author is always the caller -
    there is deliberately no user_id field to accept."""

    day: str = Field(min_length=10, max_length=10)
    status: str = Field(default="office", max_length=16)
    yesterday: str = Field(default="", max_length=MAX_FIELD_CHARS)
    today: str = Field(default="", max_length=MAX_FIELD_CHARS)
    blockers: str = Field(default="", max_length=MAX_FIELD_CHARS)
    job_ids: list[str] = Field(default_factory=list, max_length=50)
    activities: list[str] = Field(default_factory=list, max_length=20)
    blocker_by: str = Field(default="", max_length=10)


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=MAX_COMMENT_CHARS)


class CommentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    entry_id: uuid.UUID
    user_id: str
    author_name: str
    body: str
    created_at: datetime


class FileRead(BaseModel):
    """One attachment row (entry or task - same shape)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    mime_type: str
    size_bytes: int
    uploaded_by: str
    created_at: datetime


class EntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: str
    author_name: str
    day: str
    status: str
    yesterday: str
    today: str
    blockers: str
    blocker_by: str = ""
    job_ids: list[str] = Field(default_factory=list)
    activities: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    comments: list[CommentRead] = Field(default_factory=list)
    files: list[FileRead] = Field(default_factory=list)


class JobRead(BaseModel):
    """One non-archived project, for the job picker and chip labels."""

    id: str
    name: str
    code: str


class TaskLite(BaseModel):
    """One open native task (oe_tasks) on a member's card."""

    id: str
    project_id: str
    title: str
    status: str
    priority: str
    due_date: str | None = None
    overdue: bool = False


class LastEntryRead(BaseModel):
    """The most recent update of a member who has not posted today."""

    day: str
    status: str
    today: str
    blockers: str


class TeamMember(BaseModel):
    user_id: str
    name: str
    has_posted: bool
    open_tasks: list[TaskLite] = Field(default_factory=list)
    open_tasks_total: int = 0
    last_entry: LastEntryRead | None = None


class BoardMe(BaseModel):
    user_id: str
    name: str


class BoardRead(BaseModel):
    day: str
    me: BoardMe
    entries: list[EntryRead]
    roster: list[TeamMember]
    jobs: list[JobRead] = Field(default_factory=list)


class BlockerRead(BaseModel):
    """One open blocker line for the digest strip."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: str
    author_name: str
    day: str
    blockers: str


# ------------------------------------------------- delivery board (V3)


class StageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    color: str
    position: int
    wip_limit: int | None = None
    is_done: bool = False
    spawn: list[str] = Field(default_factory=list)


class StageWrite(BaseModel):
    """One stage row in a whole-list replace. ``id`` present = update
    that stage (its tasks stay put); absent = create."""

    id: str | None = None
    name: str = Field(min_length=1, max_length=120)
    color: str = Field(default="slate", max_length=20)
    wip_limit: int | None = Field(default=None, ge=0, le=99)
    is_done: bool = False
    spawn: list[str] = Field(default_factory=list, max_length=10)


class StagesReplace(BaseModel):
    stages: list[StageWrite] = Field(min_length=2, max_length=20)


class ActivityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    color: str
    position: int
    exclusive: bool = False


class ActivityWrite(BaseModel):
    id: str | None = None
    name: str = Field(min_length=1, max_length=120)
    color: str = Field(default="slate", max_length=20)
    exclusive: bool = False


class ActivitiesReplace(BaseModel):
    activities: list[ActivityWrite] = Field(min_length=2, max_length=20)


class WaitsReplace(BaseModel):
    reasons: list[str] = Field(default_factory=list, max_length=40)


class TaskCommentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    user_id: str
    author_name: str
    body: str
    created_at: datetime


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    project_id: str
    # The GUID column type hands back uuid.UUID on a fresh read but the
    # plain string a service just assigned inside the same session -
    # normalise both to the string the client keys on.
    stage_id: str

    @field_validator("stage_id", mode="before")
    @classmethod
    def _stage_as_str(cls, v: object) -> str:
        return str(v)

    assignee_id: str
    assignee_name: str
    due: str = ""
    priority: str = "medium"
    waiting_on: str = ""
    notes: str = ""
    repeat_rule: str = ""
    link_kind: str = ""
    link_ref: str = ""
    link_target_id: str = ""
    is_sub: bool = False
    visibility: str = "public"
    created_by: str = ""
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    comments: list[TaskCommentRead] = Field(default_factory=list)
    files: list[FileRead] = Field(default_factory=list)


class TaskWrite(BaseModel):
    """One line of the composer (bulk create)."""

    title: str = Field(min_length=1, max_length=500)
    project_id: str = Field(min_length=1, max_length=36)
    stage_id: str = Field(default="", max_length=36)
    assignee_id: str = Field(default="", max_length=36)
    due: str = Field(default="", max_length=10)
    priority: str = Field(default="medium", max_length=10)
    waiting_on: str = Field(default="", max_length=200)
    notes: str = Field(default="", max_length=4000)
    repeat_rule: str = Field(default="", max_length=20)
    link_kind: LinkKind = ""
    link_ref: str = Field(default="", max_length=80)
    link_target_id: str = Field(default="", max_length=36)
    visibility: TaskVisibility = "public"


class TasksCreate(BaseModel):
    tasks: list[TaskWrite] = Field(min_length=1, max_length=20)


class TaskPatch(BaseModel):
    """Partial edit. Stage is deliberately absent - stage changes go
    through /move so the templates always fire."""

    title: str | None = Field(default=None, max_length=500)
    project_id: str | None = Field(default=None, max_length=36)
    assignee_id: str | None = Field(default=None, max_length=36)
    due: str | None = Field(default=None, max_length=10)
    priority: str | None = Field(default=None, max_length=10)
    waiting_on: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=4000)
    repeat_rule: str | None = Field(default=None, max_length=20)
    link_kind: LinkKind | None = None
    link_ref: str | None = Field(default=None, max_length=80)
    link_target_id: str | None = Field(default=None, max_length=36)
    #: Creator, assignee or admin only - the service refuses anyone else.
    visibility: TaskVisibility | None = None


class TaskMove(BaseModel):
    stage_id: str = Field(min_length=1, max_length=36)


class TaskMoveResult(BaseModel):
    task: TaskRead
    spawned: list[TaskRead] = Field(default_factory=list)
    repeated: TaskRead | None = None


class TaskMoveUndo(BaseModel):
    to_stage_id: str = Field(min_length=1, max_length=36)
    spawned_ids: list[str] = Field(default_factory=list, max_length=10)
    repeated_id: str | None = None


class PersonRead(BaseModel):
    id: str
    name: str
    initials: str
    color: str


class LogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    author_name: str
    what: str
    where_label: str
    kind: str
    color: str
    created_at: datetime


class BoardJobRead(BaseModel):
    """One job as the delivery board wants it - short code, client
    family, and the work description."""

    id: str
    code: str
    client: str
    #: The client contact's brand colour as a hex string, '' when unset.
    client_color: str = ""
    label: str
    name: str


class WeekRead(BaseModel):
    start: str
    entries: list[EntryRead] = Field(default_factory=list)


class FullBoardRead(BaseModel):
    """Everything the board page needs in one round trip."""

    day: str
    today: str
    me: BoardMe
    people: list[PersonRead] = Field(default_factory=list)
    entries: list[EntryRead] = Field(default_factory=list)
    week: WeekRead
    stages: list[StageRead] = Field(default_factory=list)
    #: Per-job stage runs keyed by project id. A job listed here shows
    #: ONLY these columns; every other job shows ``stages``.
    stage_overrides: dict[str, list[StageRead]] = Field(default_factory=dict)
    activities: list[ActivityRead] = Field(default_factory=list)
    waits: list[str] = Field(default_factory=list)
    tasks: list[TaskRead] = Field(default_factory=list)
    jobs: list[BoardJobRead] = Field(default_factory=list)
    log: list[LogRead] = Field(default_factory=list)


class EntryListResponse(BaseModel):
    """A page of history rows and how many the date range holds."""

    items: list[EntryRead] = Field(default_factory=list)
    total: int = 0
    limit: int
    offset: int


class BlockerListResponse(BaseModel):
    items: list[BlockerRead] = Field(default_factory=list)
    total: int = 0
    limit: int
    offset: int


class LogListResponse(BaseModel):
    """``total`` counts the log, not one viewer's view of it: a line about
    a private task is redacted from the page after the window is read, so
    a reader without the rights may be served fewer rows than the count
    promises. What the envelope answers is how far back the feed goes."""

    items: list[LogRead] = Field(default_factory=list)
    total: int = 0
    limit: int
    offset: int
