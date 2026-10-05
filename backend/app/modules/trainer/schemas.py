# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Trainer API request and response schemas.

This file is the contract between the trainer backend and the Academy UI. The
frontend mirror is ``frontend/src/features/trainer/types.ts``: every model
here has an interface of the same name there, and every ``Literal`` below has
a ``const`` array there. A parity test on the backend side reads that file and
fails on any difference in field names, nullability or literal values.

Rules every model follows:

* ``extra="forbid"``. A response that grows a field the UI does not know, or a
  fixture that carries a stale one, fails validation instead of drifting.
* Money and other decimals are strings (``"30414.00"``), never floats. A value
  whose ``kind`` is numeric must parse as a plain decimal; a ``date`` value is
  ``YYYY-MM-DD``.
* Nothing the checker grades against is ever sent: no answer values, no
  ``correct`` flags, no diagnosis ``wrong_value``, no feedback of an option the
  learner did not choose, no hint the learner has not been shown. A diagnosis
  carries no signed ``delta`` either, because ``observed - delta`` is the
  expected value.
* Nullable fields are always present in the JSON, as ``null``. Nothing is
  optional-and-absent, so the TypeScript side never has to tell ``undefined``
  from ``null``.

Endpoints (all under ``/api/v1/trainer/``):

======================================  ==========================  ============================
Method and path                         Request                     Response
======================================  ==========================  ============================
GET  ``/public/status/``                -                           ``PublicStatus``
GET  ``/me``                            -                           ``TrainerMe`` (404: none)
GET  ``/tasks/{task_id}``               -                           ``TaskView``
PUT  ``/tasks/{task_id}/answers``       ``AnswersPut``              ``AnswersSaved`` (409: stale)
POST ``/tasks/{task_id}/check``         ``CheckRequest``            ``AttemptResult``
GET  ``/tasks/{task_id}/readback``      -                           ``ReadbackResponse``
POST ``/unlocks/{lock_id}/seen``        -                           204, idempotent
POST ``/admin/enrolments/``             ``AdminEnrolmentCreate``    ``AdminEnrolmentOut``
======================================  ==========================  ============================
"""

from __future__ import annotations

import datetime as dt
import re
import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.modules.trainer.locks import LockKind, is_known_lock_id, lock_kind

# ── Vocabularies ─────────────────────────────────────────────────────────────
# Each one is mirrored as a ``const`` array in types.ts.

#: Where a task stands for the learner. ``locked`` until the previous task
#: passes; ``needs_revision`` after a failed check or a later regression.
TaskStatus = Literal["not_started", "in_progress", "needs_revision", "passed", "locked"]
#: Whether a lock id is open for this learner yet.
LockState = Literal["open", "locked"]
#: The three progress rings a task closes.
RingId = Literal["numbers", "trace", "explain"]
#: One day of the week strip. Rest days (rest passes) are a later version.
WeekDayState = Literal["done", "off", "empty"]
#: What the menu does with modules the course does not cover.
OutsideCourse = Literal["hidden", "more"]
#: How a value is shown: money in the course currency, a percent, a plain
#: number, a calendar date, or free text.
ValueKind = Literal["money", "percent", "number", "date", "text"]
#: The kind of one check of a task.
CheckKind = Literal["numbers", "trace", "explain"]
#: How a typed answer is stored.
AnswerKind = Literal["number", "option", "text"]
#: Verdict on one graded item.
ItemVerdict = Literal["ok", "wrong", "missing", "error"]
#: Where the checker read an item from: the learner's typed answer or the ERP.
ItemSource = Literal["panel", "erp"]
#: Verdict on a whole check.
AttemptVerdict = Literal["pass", "fail"]
#: A diagnosis names an error, or a convention that differs from the ERP's.
DiagnosisKind = Literal["error", "convention"]
#: Readback of one ERP value against what the task expects, never the value.
ReadbackState = Literal["match", "mismatch", "unknown"]
#: Lifecycle of an enrolment. ``queued``: a second paid course waits while
#: another one is active (one active course per learner).
EnrolmentStatus = Literal["queued", "provisioning", "active", "completed", "revoked", "failed"]
#: Who created an enrolment.
EnrolmentSource = Literal["webhook", "admin"]

_NUMERIC_KINDS = frozenset({"money", "percent", "number"})
_DECIMAL_RE = re.compile(r"^-?\d+(\.\d+)?$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _check_value_for_kind(value: str | None, kind: str, where: str) -> None:
    """Refuse a numeric value that is not a plain decimal string, or a bad date."""
    if value is None:
        return
    if kind in _NUMERIC_KINDS and not _DECIMAL_RE.match(value):
        msg = f"{where}: a {kind} value must be a decimal string, got {value!r}"
        raise ValueError(msg)
    if kind == "date" and not _ISO_DATE_RE.match(value):
        msg = f"{where}: a date value must be YYYY-MM-DD, got {value!r}"
        raise ValueError(msg)


def _check_lock_id(value: str, where: str) -> None:
    if not is_known_lock_id(value):
        msg = f"{where}: unknown lock id {value!r}"
        raise ValueError(msg)


class _Schema(BaseModel):
    """Base for every trainer schema: unknown keys are an error."""

    model_config = ConfigDict(extra="forbid")


# ── Public status ────────────────────────────────────────────────────────────


class PublicStatus(_Schema):
    """``GET /public/status/``, readable before sign-in.

    The sign-in page of an academy box uses it to hide self-registration and
    to point a buyer at their email or the store.
    """

    academy_mode: bool
    store_url: str | None


# ── /me ──────────────────────────────────────────────────────────────────────


class CourseBadge(_Schema):
    """The badge the last task earns."""

    id: str
    title: str


class CourseInfo(_Schema):
    """The course the learner is enrolled in. Text is in the course language."""

    id: str
    version: str
    title: str
    summary: str | None
    language: str
    country: str
    #: BCP 47 tag the UI formats course content with, e.g. ``en-GB``.
    locale: str
    currency: str
    contract: str | None
    badge: CourseBadge | None


class TaskTarget(_Schema):
    """Where in the ERP a task happens. Built server side from seeded refs."""

    route: str
    anchor: str | None


class TaskVideo(_Schema):
    """The video episode that goes with a task."""

    episode: str
    title: str
    route: str


class TaskRings(_Schema):
    """Which of the three rings this task has closed."""

    numbers: bool
    trace: bool
    explain: bool


class TaskSummary(_Schema):
    """One task on the course map."""

    id: str
    n: int = Field(ge=1)
    title: str
    #: The ERP module the task happens in (``boq``, ``bid_management``, ...).
    module: str
    #: The lock id this task's pass opens, or ``badge:<course>`` for the last.
    opens: str
    opens_label: str
    estimated_minutes: int | None
    status: TaskStatus
    rings: TaskRings
    #: Required for every task that is not locked, so "Continue", "Go to task"
    #: and "Open module" always lead somewhere.
    target: TaskTarget | None
    video: TaskVideo | None
    checked_prompt: str | None
    lock_reason: str | None

    @model_validator(mode="after")
    def _open_task_has_target(self) -> TaskSummary:
        _check_lock_id(self.opens, f"task {self.id} opens")
        if self.status != "locked" and self.target is None:
            msg = f"task {self.id} is {self.status} but has no target route"
            raise ValueError(msg)
        return self


class UnlockTile(_Schema):
    """One "what you can do now" tile on the unlock dialog."""

    title: str
    text: str


class UnlockInfo(_Schema):
    """One lock id of the course and whether the learner has it yet.

    ``seen`` is false for an open lock whose unlock dialog the learner has not
    closed yet; ``POST /unlocks/{lock_id}/seen`` sets it.
    """

    lock_id: str
    kind: LockKind
    state: LockState
    #: The task number whose pass opens this lock.
    opened_by_task: int = Field(ge=1)
    opened_at: dt.datetime | None
    seen: bool
    tiles: list[UnlockTile]

    @model_validator(mode="after")
    def _known_and_consistent(self) -> UnlockInfo:
        _check_lock_id(self.lock_id, "unlock")
        if lock_kind(self.lock_id) != self.kind:
            msg = f"unlock {self.lock_id}: kind {self.kind!r} disagrees with the lock registry"
            raise ValueError(msg)
        if self.state == "locked" and (self.opened_at is not None or self.seen):
            msg = f"unlock {self.lock_id}: a locked lock has no opened_at and is never seen"
            raise ValueError(msg)
        return self


class NavInfo(_Schema):
    """How the Academy menu treats modules outside the course."""

    outside_course: OutsideCourse
    #: Module keys that are never locked (``projects``, ``boq``).
    always_open: list[str]


class RingProgress(_Schema):
    """Count of tasks whose ring of this kind is closed."""

    done: int = Field(ge=0)
    total: int = Field(ge=0)

    @model_validator(mode="after")
    def _done_within_total(self) -> RingProgress:
        if self.done > self.total:
            msg = f"ring progress {self.done}/{self.total}: done exceeds total"
            raise ValueError(msg)
        return self


class ProgressRings(_Schema):
    """Course-wide progress per ring."""

    numbers: RingProgress
    trace: RingProgress
    explain: RingProgress


class CourseProgress(_Schema):
    """Course-wide progress: passed tasks and the three rings."""

    done: int = Field(ge=0)
    total: int = Field(ge=0)
    rings: ProgressRings

    @model_validator(mode="after")
    def _done_within_total(self) -> CourseProgress:
        if self.done > self.total:
            msg = f"course progress {self.done}/{self.total}: done exceeds total"
            raise ValueError(msg)
        return self


class WeekDay(_Schema):
    """One day of the current ISO week."""

    date: dt.date
    state: WeekDayState


class WeekInfo(_Schema):
    """This ISO week: passed checks against the weekly goal."""

    goal: int = Field(ge=1)
    done: int = Field(ge=0)
    days: list[WeekDay] = Field(max_length=7)


class TrainerMe(_Schema):
    """``GET /me``: the learner's active enrolment. 404 when there is none."""

    course: CourseInfo
    tasks: list[TaskSummary] = Field(min_length=1)
    unlocks: list[UnlockInfo]
    nav: NavInfo
    progress: CourseProgress
    week: WeekInfo | None
    level: str | None

    @model_validator(mode="after")
    def _tasks_in_order(self) -> TrainerMe:
        numbers = [t.n for t in self.tasks]
        if numbers != list(range(1, len(numbers) + 1)):
            msg = f"tasks must be numbered 1..N in order, got {numbers}"
            raise ValueError(msg)
        if self.progress.total != len(self.tasks):
            msg = f"progress total {self.progress.total} != {len(self.tasks)} tasks"
            raise ValueError(msg)
        return self


# ── Task view ────────────────────────────────────────────────────────────────


class GivenItem(_Schema):
    """One given value a task states up front."""

    name: str
    value: str
    kind: ValueKind

    @model_validator(mode="after")
    def _value_matches_kind(self) -> GivenItem:
        _check_value_for_kind(self.value, self.kind, f"given {self.name}")
        return self


class CheckField(_Schema):
    """One input of a numbers check. ``key`` is the answer name to PUT."""

    key: str
    label: str
    kind: ValueKind
    #: ISO currency of a money field; null for every other kind.
    currency: str | None


class ChoiceOption(_Schema):
    """One option of a trace or explain question. Never carries ``correct``."""

    index: int = Field(ge=0)
    text: str


class NumbersCheckView(_Schema):
    """A check where the learner types figures."""

    id: str
    kind: Literal["numbers"]
    prompt: str
    fields: list[CheckField] = Field(min_length=1)


class ChoiceCheckView(_Schema):
    """A trace or explain question. The answer name to PUT is the check ``id``."""

    id: str
    kind: Literal["trace", "explain"]
    prompt: str
    options: list[ChoiceOption] = Field(min_length=2)

    @model_validator(mode="after")
    def _indexes_in_order(self) -> ChoiceCheckView:
        if [o.index for o in self.options] != list(range(len(self.options))):
            msg = f"check {self.id}: option indexes must be 0..N-1 in order"
            raise ValueError(msg)
        return self


CheckView = Annotated[NumbersCheckView | ChoiceCheckView, Field(discriminator="kind")]


class ReadbackItemView(_Schema):
    """One value the panel reads back from the ERP while the learner works."""

    id: str
    what: str
    kind: ValueKind


class SavedAnswer(_Schema):
    """One stored answer. Exactly one of ``value_text`` / ``option_index``."""

    name: str
    kind: AnswerKind
    value_text: str | None
    option_index: int | None

    @model_validator(mode="after")
    def _one_value(self) -> SavedAnswer:
        if self.kind == "option":
            ok = self.option_index is not None and self.value_text is None
        else:
            ok = self.value_text is not None and self.option_index is None
        if not ok:
            msg = f"answer {self.name}: a {self.kind} answer carries exactly its own value"
            raise ValueError(msg)
        return self


class RelatedValue(_Schema):
    """One derivation a diagnosis shows."""

    name: str
    value: str
    kind: ValueKind

    @model_validator(mode="after")
    def _value_matches_kind(self) -> RelatedValue:
        _check_value_for_kind(self.value, self.kind, f"related {self.name}")
        return self


class Diagnosis(_Schema):
    """Why a value is wrong, matched within that field only.

    ``related`` lists the derivations the course author chose to show. There is
    no signed delta: with the observed value it would give away the answer.
    """

    id: str
    kind: DiagnosisKind
    message: str
    related: list[RelatedValue]


class FieldResult(_Schema):
    """The verdict on one graded item.

    ``key`` is the answer name for a panel item, the readback id for an ERP
    item. ``observed`` is what the checker read (the learner's own figure or
    the ERP value), as a string. ``feedback`` is the feedback of the option the
    learner chose, for a trace or explain item; null otherwise.
    """

    key: str
    source: ItemSource
    verdict: ItemVerdict
    observed: str | None
    diagnosis: Diagnosis | None
    feedback: str | None

    @model_validator(mode="after")
    def _diagnosis_only_when_wrong(self) -> FieldResult:
        if self.verdict == "ok" and self.diagnosis is not None:
            msg = f"item {self.key}: an ok item carries no diagnosis"
            raise ValueError(msg)
        return self


class AttemptResult(_Schema):
    """``POST /tasks/{task_id}/check``: one run of the checker.

    A pass needs at least one graded item and every graded item ``ok``; a check
    over zero items never passes. A pass stays recorded: a later failing check
    returns ``regressed: true`` and does not lock the task again.
    """

    attempt_id: uuid.UUID
    client_attempt_id: uuid.UUID | None
    task_id: str
    verdict: AttemptVerdict
    graded_items: int = Field(ge=0)
    passed_items: int = Field(ge=0)
    fields: list[FieldResult]
    task_status: TaskStatus
    rings: TaskRings
    progress: CourseProgress
    #: Lock ids this attempt opened. Empty unless it was the passing attempt.
    unlocked: list[str]
    regressed: bool
    #: The hint a failed check revealed, if one was left to reveal.
    revealed_hint: str | None
    checked_at: dt.datetime

    @model_validator(mode="after")
    def _verdict_follows_items(self) -> AttemptResult:
        if self.passed_items > self.graded_items:
            msg = f"passed_items {self.passed_items} > graded_items {self.graded_items}"
            raise ValueError(msg)
        if len(self.fields) != self.graded_items:
            msg = f"{len(self.fields)} field results for {self.graded_items} graded items"
            raise ValueError(msg)
        passing = self.graded_items > 0 and self.passed_items == self.graded_items
        if (self.verdict == "pass") != passing:
            msg = (
                f"verdict {self.verdict!r} contradicts {self.passed_items}/{self.graded_items} "
                "(a pass needs at least one graded item, all ok)"
            )
            raise ValueError(msg)
        if sum(1 for f in self.fields if f.verdict == "ok") != self.passed_items:
            msg = "passed_items disagrees with the ok verdicts"
            raise ValueError(msg)
        if self.verdict == "fail" and self.unlocked:
            msg = "a failed attempt opens nothing"
            raise ValueError(msg)
        if self.verdict == "pass" and self.revealed_hint is not None:
            msg = "a passing attempt reveals no hint"
            raise ValueError(msg)
        for lock_id in self.unlocked:
            _check_lock_id(lock_id, "unlocked")
        return self


class TaskView(_Schema):
    """``GET /tasks/{task_id}``: a task with every secret removed.

    ``hints`` holds only the hints already revealed to this learner;
    ``hints_total`` says how many exist. ``answers_revision`` is the token the
    next ``PUT /answers`` must send back.
    """

    id: str
    n: int = Field(ge=1)
    title: str
    module: str
    status: TaskStatus
    brief: str
    given: list[GivenItem]
    steps: list[str]
    hints: list[str]
    hints_total: int = Field(ge=0)
    panel_notes: list[str]
    #: True when a step asks for a date, so the panel shows the date-input note.
    has_date_steps: bool
    checks: list[CheckView] = Field(min_length=1)
    readback: list[ReadbackItemView]
    answers: list[SavedAnswer]
    answers_revision: int = Field(ge=0)
    last_attempt: AttemptResult | None

    @model_validator(mode="after")
    def _consistent(self) -> TaskView:
        if len(self.hints) > self.hints_total:
            msg = f"task {self.id}: {len(self.hints)} hints shown of {self.hints_total}"
            raise ValueError(msg)
        keys = [f.key for c in self.checks if isinstance(c, NumbersCheckView) for f in c.fields]
        keys += [c.id for c in self.checks if isinstance(c, ChoiceCheckView)]
        if len(keys) != len(set(keys)):
            msg = f"task {self.id}: answer names repeat across checks"
            raise ValueError(msg)
        unknown = sorted({a.name for a in self.answers} - set(keys))
        if unknown:
            msg = f"task {self.id}: saved answers for unknown names {unknown}"
            raise ValueError(msg)
        if self.last_attempt is not None and self.last_attempt.task_id != self.id:
            msg = f"task {self.id}: last attempt belongs to {self.last_attempt.task_id}"
            raise ValueError(msg)
        return self


# ── Answers ──────────────────────────────────────────────────────────────────


class AnswerIn(_Schema):
    """One answer to store. Both values null clears the stored answer.

    ``value_text`` is what the learner typed, already normalised to a plain
    decimal string by the UI for a number field.
    """

    name: str = Field(min_length=1, max_length=255)
    value_text: str | None = Field(default=None, max_length=64)
    option_index: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _at_most_one_value(self) -> AnswerIn:
        if self.value_text is not None and self.option_index is not None:
            msg = f"answer {self.name}: send value_text or option_index, not both"
            raise ValueError(msg)
        return self


class AnswersPut(_Schema):
    """``PUT /tasks/{task_id}/answers``.

    ``revision`` is the ``answers_revision`` the client last read. Any other
    value is answered 409, so two tabs cannot overwrite each other silently.
    An unknown answer name is answered 422.
    """

    answers: list[AnswerIn] = Field(min_length=1)
    revision: int = Field(ge=0)

    @model_validator(mode="after")
    def _names_unique(self) -> AnswersPut:
        names = [a.name for a in self.answers]
        if len(names) != len(set(names)):
            msg = "each answer name may appear once per request"
            raise ValueError(msg)
        return self


class AnswersSaved(_Schema):
    """Response to the answers PUT: the new revision and every stored answer."""

    task_id: str
    revision: int = Field(ge=1)
    answers: list[SavedAnswer]


# ── Check ────────────────────────────────────────────────────────────────────


class CheckRequest(_Schema):
    """``POST /tasks/{task_id}/check``.

    ``client_attempt_id`` is generated once per click; a retry with the same id
    returns the stored attempt. ``revision`` names the answers the learner sees;
    when it is stale the check is refused with 409 rather than graded against
    answers the learner never saw.
    """

    client_attempt_id: uuid.UUID
    revision: int | None = Field(default=None, ge=0)


# ── Readback ─────────────────────────────────────────────────────────────────


class ReadbackValue(_Schema):
    """What the ERP holds now for one readback item, never the expected value."""

    id: str
    state: ReadbackState
    #: The value read from the learner's project; null when it cannot be read.
    app_value: str | None
    kind: ValueKind

    @model_validator(mode="after")
    def _value_matches_kind(self) -> ReadbackValue:
        _check_value_for_kind(self.app_value, self.kind, f"readback {self.id}")
        if self.state == "unknown" and self.app_value is not None:
            msg = f"readback {self.id}: an unknown reading has no value"
            raise ValueError(msg)
        return self


class ReadbackResponse(_Schema):
    """``GET /tasks/{task_id}/readback``."""

    task_id: str
    items: list[ReadbackValue]
    read_at: dt.datetime


# ── Admin ────────────────────────────────────────────────────────────────────


class AdminEnrolmentCreate(_Schema):
    """``POST /admin/enrolments/``: provision a learner by hand.

    Runs the same provisioning as a paid webhook, with ``source="admin"``.
    """

    email: EmailStr
    full_name: str = Field(min_length=1, max_length=255)
    course_key: str = Field(min_length=1, max_length=80)
    #: UI locale for a newly created account; ignored for an existing one.
    locale: str | None = Field(default=None, max_length=16)


class AdminEnrolmentOut(_Schema):
    """One enrolment as the admin screens show it."""

    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    course_key: str
    course_version: str
    status: EnrolmentStatus
    source: EnrolmentSource
    project_id: uuid.UUID | None
    current_task_n: int = Field(ge=1)
    created_at: dt.datetime
