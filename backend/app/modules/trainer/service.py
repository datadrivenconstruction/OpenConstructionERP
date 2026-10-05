# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Trainer service: enrolment lifecycle, task views, answers, checks and unlocks.

The service joins the frozen pieces of Wave 1 into the learner's course:

* the pinned course spec (``oe_trainer_course.spec`` of the enrolment's row,
  located by ``course_sha256``), parsed once per process;
* the seeder (``execute_enrolment`` at enrolment start, ``execute_stage`` for
  ``on_unlock(n)`` when task ``n - 1`` passes);
* the checker (``run_task_probes`` + ``grade_task`` for a check,
  ``readback_values`` for the read-only readback).

Rules the code below keeps, by decision number:

* 4: ``/me`` is the learner's running enrolment; rings and the week are
  computed from attempts, never stored.
* 28 / 29: the answers PUT replaces the task's whole answer set and carries a
  revision; a check names the revision it grades. A stale one is 409.
* 30: a hint reveal is idempotent at the last hint.
* 36 / 40: the readback runs the probes in ``read`` mode and writes nothing;
  an ``unknown`` reading carries a ``reason_key`` when the learner can act.
* 41: a failed enrolment seed leaves the enrolment ``failed``; an admin
  reseed retries it and sends the "ready" email on success.
* 42: ``suspended`` closes the course without deleting anything.
* 43: ``TrainerTaskState`` rows are created at enrolment start (task 1
  unlocked, the rest locked), and a queued course starts when the running
  one completes.

Only a learner's own "Check my work" (or an admin) moves a task: an event
recheck records an attempt and clears ``stale_since``, nothing more, so a
background recheck can never race the learner's click into a different
unlock. Task status, rings and the week read the learner's own checks only.

Seed writes publish ERP events like any learner action. Every commit that
follows a seed runs inside :func:`seeder.seeding`, so the trainer's own event
handlers ignore what the seed published (design §5.1).
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy import select, text, update

from app.modules.trainer.checker.grading import (
    GradeOutcome,
    PanelAnswer,
    answer_kind,
    grade_task,
    ledger_labels,
    readback_values,
    run_task_probes,
)
from app.modules.trainer.checker.registry import ProbeContext, ProbeMode
from app.modules.trainer.checker.units import SCHEMA_KIND, format_decimal, probe_field_kind
from app.modules.trainer.locks import lock_kind
from app.modules.trainer.models import (
    TrainerAnswer,
    TrainerAttempt,
    TrainerCourse,
    TrainerEnrolment,
    TrainerTaskState,
)
from app.modules.trainer.repository import TrainerRepository
from app.modules.trainer.schemas import (
    AdminEnrolmentOut,
    AnswersPut,
    AnswersSaved,
    AttemptResult,
    CheckField,
    CheckRequest,
    CheckView,
    ChoiceCheckView,
    ChoiceOption,
    CourseBadge,
    CourseInfo,
    CourseProgress,
    FieldResult,
    GivenItem,
    HintRevealResult,
    NavInfo,
    NumbersCheckView,
    ProgressRings,
    ReadbackItemView,
    ReadbackResponse,
    RevealedHint,
    RingProgress,
    SavedAnswer,
    TaskRings,
    TaskStatus,
    TaskSummary,
    TaskTarget,
    TaskVideo,
    TaskView,
    TrainerMe,
    UnlockInfo,
    WeekDay,
    WeekInfo,
)
from app.modules.trainer.seeder import (
    SeedContext,
    SeedError,
    build_plan,
    execute_enrolment,
    execute_stage,
    seeding,
)
from app.modules.trainer.seeder.plan import PROJECT_REF, SeedPlan
from app.modules.trainer.spec import (
    CourseSpec,
    GivenSpec,
    Stage,
    TaskSpec,
    to_decimal,
)
from app.modules.trainer.validators import LedgerEntry, build_ledger

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.config import Settings

logger = logging.getLogger(__name__)

#: Stored on every attempt, so a later engine change can be told apart.
ENGINE_VERSION = "trainer-1"

#: Attempts the learner (or an admin) ran. Task status, rings and the week
#: read these only; an event recheck is a background note, not a verdict.
VISIBLE_TRIGGERS: tuple[str, ...] = ("manual", "admin")

#: Weekly goal when the course names none (decision 4).
DEFAULT_WEEK_GOAL = 3

#: Modules a course never locks (``nav.always_open``).
ALWAYS_OPEN_MODULES: tuple[str, ...] = ("projects", "boq")

#: Task module -> the project route segment of that module in the app.
_MODULE_ROUTES: dict[str, str] = {
    "bid_management": "bid-management",
    "contracts": "contracts",
    "variations": "variations",
}
_MARKUPS_LOCK = "boq.markups_panel"
_MARKUPS_ANCHOR = "boq-markups-panel"

#: Name of the contract-sum-analysis bill, in the course language.
_CSA_BOQ_NAMES: dict[str, str] = {
    "en": "Contract sum analysis (for valuations)",
    "de": "Aufgliederung der Vertragssumme (für Abschlagsrechnungen)",
    "fr": "Décomposition du prix (pour les situations)",
    "es": "Desglose del precio del contrato (para certificaciones)",
    "ru": "Расшифровка договорной цены (для актов выполненных работ)",
}

_SEED_ERROR_CHARS = 2000


def _now() -> datetime:
    return datetime.now(UTC)


def _http(code: int, detail: str) -> HTTPException:
    return HTTPException(status_code=code, detail=detail)


# ── The pinned course, parsed once ───────────────────────────────────────────


@dataclass(slots=True)
class LoadedCourse:
    """One course row, parsed: the spec, its ledger and (lazily) its seed plan."""

    row_id: uuid.UUID
    sha256: str
    course_key: str
    version: str
    spec: CourseSpec
    ledger: dict[str, LedgerEntry]
    _plan: SeedPlan | None = field(default=None, repr=False)
    _labels: dict[str, str] | None = field(default=None, repr=False)

    @property
    def plan(self) -> SeedPlan:
        """The seed plan (decision 39 guarantees it builds for a stored valid course)."""
        if self._plan is None:
            self._plan = build_plan(self.spec)
        return self._plan

    @property
    def labels(self) -> dict[str, str]:
        """Human names of ledger keys in the course language (``RelatedValue.label``)."""
        if self._labels is None:
            self._labels = ledger_labels(self.spec.tasks)
        return self._labels

    @property
    def tasks(self) -> list[TaskSpec]:
        """The tasks in number order."""
        return sorted(self.spec.tasks, key=lambda t: t.n)

    def task(self, task_id: str) -> TaskSpec | None:
        """A task by id."""
        return next((t for t in self.spec.tasks if t.id == task_id), None)

    def task_by_n(self, n: int) -> TaskSpec | None:
        """A task by number."""
        return next((t for t in self.spec.tasks if t.n == n), None)

    @property
    def currency(self) -> str:
        """The course currency."""
        return self.spec.currency

    @property
    def language(self) -> str:
        """The course language, for engine messages."""
        return self.spec.language


_COURSE_CACHE: dict[tuple[uuid.UUID, str], LoadedCourse] = {}


def parse_course_row(row: TrainerCourse) -> LoadedCourse:
    """Parse a stored course row once per process; the cache key is (id, sha256)."""
    key = (row.id, row.sha256)
    cached = _COURSE_CACHE.get(key)
    if cached is not None:
        return cached
    spec = CourseSpec.model_validate(row.spec)
    # The ledger reads Decimals, as the loader produced them; the stored JSON
    # carries strings, so it is rebuilt from the validated model.
    ledger = build_ledger(spec.model_dump(mode="python", by_alias=True, exclude_unset=True))
    loaded = LoadedCourse(row.id, row.sha256, row.course_key, row.version, spec, ledger)
    _COURSE_CACHE[key] = loaded
    return loaded


# ── Pure helpers: views, rings, status ───────────────────────────────────────


def _choice_ids(task: TaskSpec) -> dict[str, str]:
    """Check id -> ``trace`` | ``explain`` for the task's choice checks."""
    return {c.id: c.kind for c in task.checks if c.kind in ("trace", "explain")}


def rings_of(task: TaskSpec, fields: Iterable[FieldResult]) -> TaskRings:
    """The rings one attempt closed: the same split ``grade_task`` makes."""
    choices = _choice_ids(task)
    groups: dict[str, list[FieldResult]] = {"numbers": [], "trace": [], "explain": []}
    for item in fields:
        groups[choices.get(item.key, "numbers")].append(item)

    def closed(items: list[FieldResult]) -> bool:
        return bool(items) and all(i.verdict == "ok" for i in items)

    return TaskRings(
        numbers=closed(groups["numbers"]), trace=closed(groups["trace"]), explain=closed(groups["explain"])
    )


def _stored_fields(attempt: TrainerAttempt) -> list[FieldResult]:
    return [FieldResult.model_validate(item) for item in (attempt.result or [])]


def _union(a: TaskRings, b: TaskRings) -> TaskRings:
    return TaskRings(numbers=a.numbers or b.numbers, trace=a.trace or b.trace, explain=a.explain or b.explain)


_NO_RINGS = TaskRings(numbers=False, trace=False, explain=False)


def task_status(state: TrainerTaskState, last_passed: bool | None, has_answers: bool) -> TaskStatus:
    """Where a task stands for the learner.

    ``last_passed`` is the verdict of the learner's latest own check of the
    task (None when there is none).
    """
    if state.state == "locked":
        return "locked"
    if state.state == "passed":
        return "passed"
    if last_passed is False:
        return "needs_revision"
    if has_answers or last_passed is not None:
        return "in_progress"
    return "not_started"


def _humanise(name: str) -> str:
    text = name.replace("_", " ").replace("-", " ").strip()
    return text[:1].upper() + text[1:] if text else name


def _panel_texts(value: Any) -> list[str]:
    """``tasks[].panel_notes`` is opaque: strings, or objects with ``text``."""
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item)
        elif isinstance(item, dict) and isinstance(item.get("text"), str) and item["text"].strip():
            out.append(item["text"])
    return out


def _given_view(given: GivenSpec, ledger: Mapping[str, LedgerEntry], currency: str) -> GivenItem | None:
    """A given value as the panel shows it; a rate in percent, never as a fraction."""
    number = to_decimal(given.value)
    if number is None:
        text = given.value if isinstance(given.value, str) and given.value else given.text
        return GivenItem(name=given.name, value=text, kind="text") if text else None
    entry = ledger.get(given.ledger_key) if given.ledger_key else None
    unit = given.unit or (entry.unit if entry is not None else None)
    if unit in ("percent", "fraction"):
        return GivenItem(
            name=given.name, value=format_decimal(number * 100 if unit == "fraction" else number), kind="percent"
        )
    if isinstance(unit, str) and unit.strip().upper() == currency.upper():
        return GivenItem(name=given.name, value=format_decimal(number), kind="money")
    return GivenItem(name=given.name, value=format_decimal(number), kind="number")


def _numbers_fields(task: TaskSpec, check_expects: list[str], taken: set[str], currency: str) -> list[CheckField]:
    """The panel fields of one numbers check: the panel answers it names.

    A check that names nothing takes every panel answer no earlier check took.
    """
    panel = [a for a in task.answer_key if a.grading.has_panel_field]
    free = [a for a in panel if a.name not in taken]
    chosen = [a for a in free if a.name in check_expects] if check_expects else free
    fields: list[CheckField] = []
    for answer in chosen:
        kind = SCHEMA_KIND[answer_kind(answer, task=task)]
        fields.append(
            CheckField(
                key=answer.name,
                label=_humanise(answer.name),
                kind=kind,
                currency=currency if kind == "money" else None,
            )
        )
    return fields


def check_views(task: TaskSpec, currency: str) -> list[CheckView]:
    """The task's checks without a single expected value or ``correct`` flag."""
    views: list[CheckView] = []
    taken: set[str] = set()
    for check in task.checks:
        if check.kind == "numbers":
            fields = _numbers_fields(task, check.expects, taken, currency)
            if not fields:
                continue  # everything this check names is read from the ERP
            taken.update(f.key for f in fields)
            views.append(NumbersCheckView(id=check.id, kind="numbers", prompt=check.prompt, fields=fields))
        else:
            question = task.trace_question if check.kind == "trace" else task.explain_question
            views.append(
                ChoiceCheckView(
                    id=check.id,
                    kind=check.kind,
                    prompt=check.prompt,
                    options=[ChoiceOption(index=i, text=o.text) for i, o in enumerate(question.options)],
                )
            )
    # The grader reads every panel answer; one no check named still needs a
    # field, or the task could never pass. It joins the first numbers check.
    leftover = _numbers_fields(task, [], taken, currency)
    if leftover:
        first = next((i for i, v in enumerate(views) if isinstance(v, NumbersCheckView)), None)
        if first is not None:
            view = views[first]
            views[first] = view.model_copy(update={"fields": [*view.fields, *leftover]})  # type: ignore[union-attr]
        else:
            numbers = next((c for c in task.checks if c.kind == "numbers"), None)
            views.insert(
                0,
                NumbersCheckView(
                    id=numbers.id if numbers is not None else f"{task.id}-numbers",
                    kind="numbers",
                    prompt=numbers.prompt if numbers is not None else task.brief,
                    fields=leftover,
                ),
            )
    return views


def answer_names(views: Iterable[CheckView]) -> dict[str, Literal["number", "option"]]:
    """Every answer name the panel may PUT, with the kind it is stored as."""
    names: dict[str, Literal["number", "option"]] = {}
    for view in views:
        if isinstance(view, NumbersCheckView):
            names.update(dict.fromkeys((f.key for f in view.fields), "number"))
        else:
            names[view.id] = "option"
    return names


def readback_views(task: TaskSpec) -> list[ReadbackItemView]:
    """What each readback reads, never what it expects."""
    items: list[ReadbackItemView] = []
    for index, readback in enumerate(task.readback):
        kind = "text"
        if readback.probe is not None:
            kind = SCHEMA_KIND[probe_field_kind(readback.probe.type, getattr(readback.probe.args, "field", None))]
        items.append(ReadbackItemView(id=f"rb{index}", what=readback.what, kind=kind))
    return items


def _video(task: TaskSpec) -> TaskVideo | None:
    video = task.video
    if not isinstance(video, dict) or not isinstance(video.get("episode"), str) or not video["episode"]:
        return None
    episode = video["episode"]
    title = video.get("title") if isinstance(video.get("title"), str) and video.get("title") else episode
    return TaskVideo(episode=episode, title=title, route=f"/videos?episode={episode}")


def _checked_prompt(task: TaskSpec) -> str | None:
    numbers = next((c for c in task.checks if c.kind == "numbers"), None)
    return (numbers or task.checks[0]).prompt if task.checks else None


def _week_days(today: date) -> list[date]:
    monday = today - timedelta(days=today.weekday())
    return [monday + timedelta(days=i) for i in range(7)]


# ── Snapshot of one enrolment ────────────────────────────────────────────────


@dataclass(slots=True)
class _TaskProgress:
    status: TaskStatus
    rings: TaskRings
    last_attempt: TrainerAttempt | None


@dataclass(slots=True)
class _Snapshot:
    tasks: dict[str, _TaskProgress]
    progress: CourseProgress
    attempts: list[TrainerAttempt]


# ── Service ──────────────────────────────────────────────────────────────────


class TrainerService:
    """Business logic of the trainer. Stateless; one instance per request."""

    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        if settings is None:
            from app.config import get_settings

            settings = get_settings()
        self.session = session
        self.settings = settings
        self.repo = TrainerRepository(session)

    # ── Loading ──────────────────────────────────────────────────────────────

    async def course_of(self, enrolment: TrainerEnrolment) -> LoadedCourse:
        """The enrolment's pinned course.

        Raises:
            HTTPException: 409 when the pinned row is gone or no longer matches.
        """
        row = await self.repo.course(enrolment.course_id)
        if row is None or row.sha256 != enrolment.course_sha256 or not row.spec:
            raise _http(status.HTTP_409_CONFLICT, "course_unavailable")
        try:
            return parse_course_row(row)
        except ValidationError as exc:
            logger.error("Trainer course %s v%s no longer parses: %s", row.course_key, row.version, exc)
            raise _http(status.HTTP_409_CONFLICT, "course_unavailable") from None

    async def learner_enrolment(self, user_id: str | uuid.UUID, *, for_update: bool = False) -> TrainerEnrolment:
        """The learner's current enrolment.

        Raises:
            HTTPException: 404 when the learner has none (decision 4).
        """
        enrolment = await self.repo.learner_enrolment(uuid.UUID(str(user_id)), for_update=for_update)
        if enrolment is None:
            raise _http(status.HTTP_404_NOT_FOUND, "no_enrolment")
        return enrolment

    def _states(self, enrolment: TrainerEnrolment) -> dict[str, TrainerTaskState]:
        return {s.task_id: s for s in enrolment.task_states}

    def _task_and_state(
        self, course: LoadedCourse, enrolment: TrainerEnrolment, task_id: str, *, allow_locked: bool = False
    ) -> tuple[TaskSpec, TrainerTaskState]:
        task = course.task(task_id)
        state = self._states(enrolment).get(task_id) if task is not None else None
        if task is None or state is None:
            raise _http(status.HTTP_404_NOT_FOUND, "task_not_found")
        if state.state == "locked" and not allow_locked:
            raise _http(status.HTTP_409_CONFLICT, "task_locked")
        return task, state

    # ── Snapshot ─────────────────────────────────────────────────────────────

    async def _snapshot(self, enrolment: TrainerEnrolment, course: LoadedCourse) -> _Snapshot:
        attempts = await self.repo.attempts(enrolment.id, triggers=VISIBLE_TRIGGERS)
        answered = await self.repo.answered_task_ids(enrolment.id)
        states = self._states(enrolment)
        by_task: dict[str, list[TrainerAttempt]] = {}
        for attempt in attempts:
            by_task.setdefault(attempt.task_id, []).append(attempt)
        tasks: dict[str, _TaskProgress] = {}
        for task in course.tasks:
            state = states.get(task.id)
            mine = by_task.get(task.id, [])
            last = mine[-1] if mine else None
            rings = _NO_RINGS
            for attempt in mine:
                rings = _union(rings, rings_of(task, _stored_fields(attempt)))
            if state is None:
                tasks[task.id] = _TaskProgress("locked", rings, last)
                continue
            status_ = task_status(state, last.passed if last is not None else None, task.id in answered)
            tasks[task.id] = _TaskProgress(status_, rings, last)
        total = len(course.tasks)
        done = sum(1 for t in tasks.values() if t.status == "passed")
        progress = CourseProgress(
            done=done,
            total=total,
            rings=ProgressRings(
                numbers=RingProgress(done=sum(1 for t in tasks.values() if t.rings.numbers), total=total),
                trace=RingProgress(done=sum(1 for t in tasks.values() if t.rings.trace), total=total),
                explain=RingProgress(done=sum(1 for t in tasks.values() if t.rings.explain), total=total),
            ),
        )
        return _Snapshot(tasks, progress, attempts)

    def _week(self, attempts: list[TrainerAttempt], today: date | None = None) -> WeekInfo:
        """This ISO week: the days with a passed check, and the tasks passed in it."""
        today = today or _now().date()
        days = _week_days(today)
        passed_days: set[date] = set()
        passed_tasks: set[str] = set()
        for attempt in attempts:
            day = attempt.created_at.astimezone(UTC).date()
            if attempt.passed and days[0] <= day <= days[-1]:
                passed_days.add(day)
                passed_tasks.add(attempt.task_id)
        return WeekInfo(
            goal=DEFAULT_WEEK_GOAL,
            done=len(passed_tasks),
            days=[WeekDay(date=d, state="done" if d in passed_days else "empty") for d in days],
        )

    def _target(self, enrolment: TrainerEnrolment, course: LoadedCourse, task: TaskSpec) -> TaskTarget:
        """Where a task happens, built from the seeded refs. Never empty."""
        refs = enrolment.seeded_refs or {}
        project = enrolment.project_id
        boq_id = refs.get("boq.main")
        if task.module == "boq" and isinstance(boq_id, str):
            states = self._states(enrolment)
            opener = next((t for t in course.tasks if t.opens == _MARKUPS_LOCK), None)
            markups_open = (
                opener is not None
                and opener.n < task.n
                and states.get(opener.id) is not None
                and states[opener.id].state == "passed"
            )
            return TaskTarget(route=f"/boq/{boq_id}", anchor=_MARKUPS_ANCHOR if markups_open else None)
        if project is not None and task.module in _MODULE_ROUTES:
            return TaskTarget(route=f"/projects/{project}/{_MODULE_ROUTES[task.module]}", anchor=None)
        if project is not None:
            return TaskTarget(route=f"/projects/{project}", anchor=None)
        return TaskTarget(route="/academy", anchor=None)

    def _summaries(self, enrolment: TrainerEnrolment, course: LoadedCourse, snap: _Snapshot) -> list[TaskSummary]:
        out: list[TaskSummary] = []
        for task in course.tasks:
            prog = snap.tasks[task.id]
            out.append(
                TaskSummary(
                    id=task.id,
                    n=task.n,
                    title=task.title,
                    module=task.module,
                    opens=task.opens,
                    opens_label=task.opens_label or task.opens,
                    estimated_minutes=task.estimated_minutes,
                    status=prog.status,
                    rings=prog.rings,
                    target=None if prog.status == "locked" else self._target(enrolment, course, task),
                    video=_video(task),
                    checked_prompt=_checked_prompt(task),
                    lock_reason=None,
                )
            )
        return out

    def _unlocks(self, enrolment: TrainerEnrolment, course: LoadedCourse) -> list[UnlockInfo]:
        states = self._states(enrolment)
        out: list[UnlockInfo] = []
        seen_ids: set[str] = set()
        for task in course.tasks:
            kind = lock_kind(task.opens)
            if kind is None or task.opens in seen_ids:
                continue
            seen_ids.add(task.opens)
            state = states.get(task.id)
            is_open = state is not None and state.state == "passed"
            out.append(
                UnlockInfo(
                    lock_id=task.opens,
                    kind=kind,
                    state="open" if is_open else "locked",
                    opened_by_task=task.n,
                    opened_at=state.passed_at if is_open and state is not None else None,
                    seen=bool(is_open and state is not None and state.unlock_seen_at is not None),
                    tiles=[],
                )
            )
        return out

    # ── /me ──────────────────────────────────────────────────────────────────

    async def get_me(self, user_id: str | uuid.UUID) -> TrainerMe:
        """``GET /me``: the learner's running enrolment in the decision 4 shape."""
        enrolment = await self.learner_enrolment(user_id)
        course = await self.course_of(enrolment)
        snap = await self._snapshot(enrolment, course)
        spec = course.spec
        return TrainerMe(
            course=CourseInfo(
                id=spec.id,
                version=spec.version,
                title=spec.title,
                summary=spec.summary,
                language=spec.language,
                country=spec.country,
                locale=spec.locale or f"{spec.language}-{spec.country}",
                currency=spec.currency,
                contract=spec.contract,
                badge=CourseBadge(id=spec.badge.id, title=spec.badge.title),
            ),
            tasks=self._summaries(enrolment, course, snap),
            unlocks=self._unlocks(enrolment, course),
            nav=NavInfo(outside_course="hidden", always_open=list(ALWAYS_OPEN_MODULES)),
            progress=snap.progress,
            week=self._week(snap.attempts),
            level=None,
        )

    # ── Task view ────────────────────────────────────────────────────────────

    async def get_task_view(self, user_id: str | uuid.UUID, task_id: str) -> TaskView:
        """``GET /tasks/{id}``: the task with every secret removed."""
        enrolment = await self.learner_enrolment(user_id)
        course = await self.course_of(enrolment)
        task, state = self._task_and_state(course, enrolment, task_id)
        snap = await self._snapshot(enrolment, course)
        views = check_views(task, course.currency)
        names = answer_names(views)
        answers = [a for a in await self.repo.answers(enrolment.id, task.id) if a.answer_name in names]
        last = snap.tasks[task.id].last_attempt
        given = [g for g in (_given_view(x, course.ledger, course.currency) for x in task.given) if g is not None]
        return TaskView(
            id=task.id,
            n=task.n,
            title=task.title,
            module=task.module,
            status=snap.tasks[task.id].status,
            brief=task.brief,
            given=given,
            steps=list(task.steps),
            hints=list(task.hints[: state.hints_revealed]),
            hints_total=len(task.hints),
            panel_notes=_panel_texts(task.panel_notes),
            has_date_steps=any(
                isinstance(v, NumbersCheckView) and any(f.kind == "date" for f in v.fields) for v in views
            ),
            checks=views,
            readback=readback_views(task),
            answers=[self._saved(a) for a in answers],
            answers_revision=state.answers_revision,
            last_attempt=(
                self._attempt_result(task, state, last, snap.progress, snap.tasks[task.id].status)
                if last is not None
                else None
            ),
        )

    @staticmethod
    def _saved(answer: TrainerAnswer) -> SavedAnswer:
        kind = "option" if answer.kind == "option" else ("text" if answer.kind == "text" else "number")
        return SavedAnswer(
            name=answer.answer_name, kind=kind, value_text=answer.value_text, option_index=answer.option_index
        )

    # ── Answers ──────────────────────────────────────────────────────────────

    async def put_answers(self, user_id: str | uuid.UUID, task_id: str, body: AnswersPut) -> AnswersSaved:
        """Replace the task's whole answer set (decision 28).

        Raises:
            HTTPException: 409 on a stale revision or a locked task, 422 on an
                unknown name or a value of the wrong kind.
        """
        enrolment = await self.learner_enrolment(user_id, for_update=True)
        course = await self.course_of(enrolment)
        task, state = self._task_and_state(course, enrolment, task_id)
        if body.revision != state.answers_revision:
            raise _http(status.HTTP_409_CONFLICT, "stale_revision")
        views = check_views(task, course.currency)
        names = answer_names(views)
        options = {v.id: len(v.options) for v in views if isinstance(v, ChoiceCheckView)}
        unknown = sorted(a.name for a in body.answers if a.name not in names)
        if unknown:
            raise _http(status.HTTP_422_UNPROCESSABLE_CONTENT, f"unknown_answer_names: {', '.join(unknown)}")
        revision = state.answers_revision + 1
        rows: list[TrainerAnswer] = []
        for answer in body.answers:
            kind = names[answer.name]
            if kind == "option":
                if answer.value_text is not None:
                    raise _http(status.HTTP_422_UNPROCESSABLE_CONTENT, f"answer {answer.name}: an option, not text")
                if answer.option_index is None:
                    continue  # cleared
                if answer.option_index >= options[answer.name]:
                    raise _http(status.HTTP_422_UNPROCESSABLE_CONTENT, f"answer {answer.name}: no such option")
                rows.append(
                    TrainerAnswer(
                        enrolment_id=enrolment.id,
                        task_id=task.id,
                        answer_name=answer.name,
                        kind="option",
                        value_text=None,
                        option_index=answer.option_index,
                        revision=revision,
                    )
                )
            else:
                if answer.option_index is not None:
                    raise _http(status.HTTP_422_UNPROCESSABLE_CONTENT, f"answer {answer.name}: a number, not an option")
                text = (answer.value_text or "").strip()
                if not text:
                    continue  # cleared
                rows.append(
                    TrainerAnswer(
                        enrolment_id=enrolment.id,
                        task_id=task.id,
                        answer_name=answer.name,
                        kind="number",
                        value_text=text[:64],
                        option_index=None,
                        revision=revision,
                    )
                )
        await self.repo.replace_answers(enrolment.id, task.id, rows)
        state.answers_revision = revision
        await self.session.flush()
        return AnswersSaved(task_id=task.id, revision=revision, answers=[self._saved(r) for r in rows])

    # ── Check ────────────────────────────────────────────────────────────────

    def _ctx(self, enrolment: TrainerEnrolment, task: TaskSpec) -> ProbeContext:
        if enrolment.project_id is None:
            raise _http(status.HTTP_409_CONFLICT, "course_not_seeded")
        return ProbeContext(
            project_id=enrolment.project_id,
            seeded_refs=dict(enrolment.seeded_refs or {}),
            enrolment_id=enrolment.id,
            task_id=task.id,
        )

    async def _grade(
        self, enrolment: TrainerEnrolment, course: LoadedCourse, task: TaskSpec, mode: ProbeMode
    ) -> GradeOutcome:
        answers = {
            a.answer_name: PanelAnswer(value_text=a.value_text, option_index=a.option_index)
            for a in await self.repo.answers(enrolment.id, task.id)
        }
        results = await run_task_probes(
            self.session, task, self._ctx(enrolment, task), currency=course.currency, ledger=course.ledger, mode=mode
        )
        return grade_task(
            task,
            answers,
            results,
            currency=course.currency,
            ledger=course.ledger,
            locale=course.language,
            labels=course.labels,
        )

    async def _record(
        self,
        enrolment: TrainerEnrolment,
        course: LoadedCourse,
        task: TaskSpec,
        state: TrainerTaskState,
        *,
        trigger: str,
        client_attempt_id: uuid.UUID | None,
        mode: ProbeMode = "check",
    ) -> tuple[TrainerAttempt, GradeOutcome]:
        started = time.perf_counter()
        outcome = await self._grade(enrolment, course, task, mode)
        now = _now()
        attempt = await self.repo.add_attempt(
            TrainerAttempt(
                enrolment_id=enrolment.id,
                task_id=task.id,
                client_attempt_id=client_attempt_id,
                trigger=trigger,
                passed=outcome.passed,
                graded_items=outcome.graded_items,
                passed_items=outcome.passed_items,
                result=[f.model_dump(mode="json") for f in outcome.fields],
                spec_sha256=enrolment.course_sha256,
                engine_version=ENGINE_VERSION,
                duration_ms=int((time.perf_counter() - started) * 1000),
                created_at=now,
            )
        )
        state.attempts_count += 1
        state.best_passed_items = max(state.best_passed_items, outcome.passed_items)
        state.total_items = outcome.graded_items
        state.last_attempt_id = attempt.id
        enrolment.last_checked_at = now
        enrolment.stale_since = None
        return attempt, outcome

    def _attempt_result(
        self,
        task: TaskSpec,
        state: TrainerTaskState,
        attempt: TrainerAttempt,
        progress: CourseProgress,
        status_: TaskStatus,
        *,
        revealed_hint: str | None = None,
    ) -> AttemptResult:
        """An ``AttemptResult`` rebuilt from a stored attempt.

        ``unlocked`` is the task's lock only on the attempt whose pass moved
        the task (its ``passed_at``). A replayed failed attempt carries no
        ``revealed_hint``: the hint is in the task view by then.
        """
        fields = _stored_fields(attempt)
        unlocked = [task.opens] if attempt.passed and state.passed_at == attempt.created_at else []
        regressed = (
            not attempt.passed
            and state.state == "passed"
            and state.passed_at is not None
            and attempt.created_at > state.passed_at
        )
        return AttemptResult(
            attempt_id=attempt.id,
            client_attempt_id=attempt.client_attempt_id,
            task_id=task.id,
            verdict="pass" if attempt.passed else "fail",
            graded_items=attempt.graded_items,
            passed_items=attempt.passed_items,
            fields=fields,
            task_status=status_,
            rings=rings_of(task, fields),
            progress=progress,
            unlocked=unlocked,
            regressed=regressed,
            revealed_hint=None if attempt.passed else revealed_hint,
            checked_at=attempt.created_at,
        )

    async def check(self, user_id: str | uuid.UUID, task_id: str, body: CheckRequest) -> AttemptResult:
        """``POST /tasks/{id}/check``: grade, record and, on a pass, unlock the next task.

        Idempotent on ``client_attempt_id``: a retry returns the stored attempt.

        Raises:
            HTTPException: 409 on a stale revision, a locked task, an unseeded
                course or a ``client_attempt_id`` used for another task.
        """
        enrolment = await self.learner_enrolment(user_id, for_update=True)
        course = await self.course_of(enrolment)
        task, state = self._task_and_state(course, enrolment, task_id)
        existing = await self.repo.attempt_by_client_id(enrolment.id, body.client_attempt_id)
        if existing is not None:
            if existing.task_id != task.id:
                raise _http(status.HTTP_409_CONFLICT, "client_attempt_id_reused")
            snap = await self._snapshot(enrolment, course)
            return self._attempt_result(task, state, existing, snap.progress, snap.tasks[task.id].status)
        if body.revision is not None and body.revision != state.answers_revision:
            raise _http(status.HTTP_409_CONFLICT, "stale_revision")

        attempt, outcome = await self._record(
            enrolment, course, task, state, trigger="manual", client_attempt_id=body.client_attempt_id
        )
        revealed: str | None = None
        if outcome.passed and state.state == "unlocked":
            state.state = "passed"
            state.passed_at = attempt.created_at
            await self._after_pass(enrolment, course, task)
        elif not outcome.passed:
            revealed = self._reveal_next(task, state)
        await self.session.flush()
        snap = await self._snapshot(enrolment, course)
        result = self._attempt_result(
            task, state, attempt, snap.progress, snap.tasks[task.id].status, revealed_hint=revealed
        )
        # The unlock seed published ERP events; they reach the trainer's own
        # handlers at this commit and must read as the seed's, not the learner's.
        with seeding(enrolment.id):
            await self.session.commit()
        return result

    @staticmethod
    def _reveal_next(task: TaskSpec, state: TrainerTaskState) -> str | None:
        if state.hints_revealed >= len(task.hints):
            return None
        hint = task.hints[state.hints_revealed]
        state.hints_revealed += 1
        return hint

    async def _after_pass(self, enrolment: TrainerEnrolment, course: LoadedCourse, task: TaskSpec) -> None:
        """Unlock the next task (and run its seed), or complete the course."""
        nxt = course.task_by_n(task.n + 1)
        if nxt is None:
            enrolment.status = "completed"
            enrolment.completed_at = _now()
            await self._activate_queued(enrolment.user_id)
            return
        state = self._states(enrolment).get(nxt.id)
        if state is not None and state.state == "locked":
            await self._seed_and_unlock(enrolment, course, nxt, state)

    def _seed_context(self, enrolment: TrainerEnrolment, course: LoadedCourse) -> SeedContext:
        language = (course.language or "en").split("-")[0].lower()
        return SeedContext(
            enrolment_id=enrolment.id,
            learner_id=enrolment.user_id,
            csa_boq_name=_CSA_BOQ_NAMES.get(language, _CSA_BOQ_NAMES["en"]),
        )

    async def _seed_and_unlock(
        self, enrolment: TrainerEnrolment, course: LoadedCourse, task: TaskSpec, state: TrainerTaskState
    ) -> bool:
        """Run ``on_unlock(n)`` and open task ``n``. A failed seed leaves it locked for an admin reseed."""
        try:
            refs = await execute_stage(
                self.session,
                course.plan,
                Stage("on_unlock", task.n),
                self._seed_context(enrolment, course),
                enrolment.seeded_refs,
            )
        except SeedError as exc:
            logger.error("Trainer unlock seed failed for enrolment %s task %s: %s", enrolment.id, task.id, exc)
            state.seed_status = "failed"
            state.seed_error = str(exc)[:_SEED_ERROR_CHARS]
            return False
        enrolment.seeded_refs = dict(refs)
        state.state = "unlocked"
        state.unlocked_at = _now()
        state.seed_status = "done"
        state.seed_error = None
        enrolment.current_task_n = max(enrolment.current_task_n or 1, task.n)
        return True

    # ── Readback ─────────────────────────────────────────────────────────────

    async def readback(self, user_id: str | uuid.UUID, task_id: str) -> ReadbackResponse:
        """``GET /tasks/{id}/readback``: live values, read-only (decision 36)."""
        enrolment = await self.learner_enrolment(user_id)
        course = await self.course_of(enrolment)
        task, _state = self._task_and_state(course, enrolment, task_id)
        results = await run_task_probes(
            self.session,
            task,
            self._ctx(enrolment, task),
            currency=course.currency,
            ledger=course.ledger,
            mode="read",
        )
        items = readback_values(task, results, currency=course.currency, ledger=course.ledger)
        return ReadbackResponse(task_id=task.id, items=items, read_at=_now())

    # ── Hints and unlocks ────────────────────────────────────────────────────

    async def reveal_hint(self, user_id: str | uuid.UUID, task_id: str) -> HintRevealResult:
        """``POST /tasks/{id}/hints/reveal`` (decision 30): the next hint, idempotent at the last."""
        enrolment = await self.learner_enrolment(user_id, for_update=True)
        course = await self.course_of(enrolment)
        task, state = self._task_and_state(course, enrolment, task_id)
        total = len(task.hints)
        if total == 0:
            raise _http(status.HTTP_409_CONFLICT, "no_hints")
        if state.hints_revealed < total:
            state.hints_revealed += 1
            await self.session.flush()
        index = state.hints_revealed - 1
        return HintRevealResult(
            hint=RevealedHint(index=index, text=task.hints[index]),
            hints_revealed=state.hints_revealed,
            hints_total=total,
        )

    async def mark_unlock_seen(self, user_id: str | uuid.UUID, lock_id: str) -> None:
        """``POST /unlocks/{lock_id}/seen``: idempotent.

        Raises:
            HTTPException: 404 for a lock this course does not have, 409 for
                one that is not open yet.
        """
        enrolment = await self.learner_enrolment(user_id, for_update=True)
        course = await self.course_of(enrolment)
        task = next((t for t in course.tasks if t.opens == lock_id), None)
        if task is None:
            raise _http(status.HTTP_404_NOT_FOUND, "unknown_lock")
        state = self._states(enrolment).get(task.id)
        if state is None or state.state != "passed":
            raise _http(status.HTTP_409_CONFLICT, "lock_not_open")
        if state.unlock_seen_at is None:
            state.unlock_seen_at = _now()
            await self.session.flush()

    # ── Enrolment lifecycle ──────────────────────────────────────────────────

    def _ensure_task_states(self, enrolment: TrainerEnrolment, course: LoadedCourse) -> None:
        """Create the missing ``TrainerTaskState`` rows (decision 43): task 1 open, the rest locked.

        Idempotent: a row that exists is never touched, so a retried start, a
        reactivation or a reseed never collides with the unique constraint.
        """
        have = {s.task_id for s in enrolment.task_states}
        now = _now()
        for task in course.tasks:
            if task.id in have:
                continue
            first = task.n == 1
            enrolment.task_states.append(
                TrainerTaskState(
                    enrolment_id=enrolment.id,
                    task_id=task.id,
                    task_n=task.n,
                    state="unlocked" if first else "locked",
                    unlocked_at=now if first else None,
                    seed_status="pending" if first else "none",
                )
            )

    async def start_enrolment(self, enrolment_id: uuid.UUID) -> TrainerEnrolment:
        """Create the task states and run the enrolment seed (``on_enrol`` + ``on_unlock(1)``).

        Writes, never commits. The caller holds :func:`seeding` across its
        commit.

        Raises:
            SeedError: a seed step failed; nothing of that stage was kept.
            LookupError: no such enrolment.
        """
        enrolment = await self.repo.enrolment(enrolment_id, for_update=True)
        if enrolment is None:
            msg = f"no trainer enrolment {enrolment_id}"
            raise LookupError(msg)
        course = await self.course_of(enrolment)
        self._ensure_task_states(enrolment, course)
        await self.session.flush()
        refs = await execute_enrolment(
            self.session, course.plan, self._seed_context(enrolment, course), enrolment.seeded_refs
        )
        enrolment.seeded_refs = dict(refs)
        project = refs.get(PROJECT_REF)
        if isinstance(project, str):
            enrolment.project_id = uuid.UUID(project)
        for state in enrolment.task_states:
            if state.task_n == 1:
                state.seed_status = "done"
                state.seed_error = None
        enrolment.status = "active"
        enrolment.started_at = enrolment.started_at or _now()
        enrolment.current_task_n = max(enrolment.current_task_n or 1, 1)
        await self.session.flush()
        return enrolment

    async def _activate_queued(self, user_id: uuid.UUID) -> None:
        """Start the learner's next queued course (decision 43). A failed seed marks it failed."""
        nxt = await self.repo.next_queued_enrolment(user_id)
        if nxt is None:
            return
        # Read before the savepoint: a rolled-back savepoint expires what it
        # touched, and an expired attribute cannot be loaded lazily here.
        nxt_id = nxt.id
        metadata = dict(nxt.metadata_ or {})
        try:
            async with self.session.begin_nested():
                nxt.status = "provisioning"
                with seeding(nxt_id):
                    await self.start_enrolment(nxt_id)
        except Exception as exc:
            logger.error("Trainer could not start queued enrolment %s: %s", nxt_id, type(exc).__name__, exc_info=True)
            await self.session.execute(
                update(TrainerEnrolment)
                .where(TrainerEnrolment.id == nxt_id)
                .values(status="failed", metadata_={**metadata, "seed_error": type(exc).__name__})
                .execution_options(synchronize_session=False)
            )
            # The row now says "failed"; make the identity map agree.
            await self.session.get(TrainerEnrolment, nxt_id, populate_existing=True)
            return
        await self.session.flush()

    # ── Event rechecks ───────────────────────────────────────────────────────

    async def recheck_open_task(self, enrolment_id: uuid.UUID) -> TrainerAttempt | None:
        """Re-grade the learner's open task after an ERP event. Commits.

        Best effort (risk R9). Only a task the learner has checked at least
        once is regraded, and the attempt is a note (``trigger="event"``):
        it never passes a task, unlocks or reveals a hint. "Check my work"
        stays the only way forward. The probes run in ``read`` mode, so a
        note never computes a levelling table the learner did not open
        (decision 36).
        """
        enrolment = await self.repo.enrolment(enrolment_id, for_update=True)
        if enrolment is None or enrolment.status != "active" or enrolment.stale_since is None:
            return None
        course = await self.course_of(enrolment)
        state = next((s for s in enrolment.task_states if s.state == "unlocked"), None)
        task = course.task(state.task_id) if state is not None else None
        if state is None or task is None or state.attempts_count == 0:
            enrolment.stale_since = None
            await self.session.commit()
            return None
        # Read mode: only the learner's own "Check my work" may compute a
        # levelling table (decision 36); a background note writes nothing.
        attempt, _outcome = await self._record(
            enrolment, course, task, state, trigger="event", client_attempt_id=None, mode="read"
        )
        await self.session.commit()
        return attempt

    # ── Admin ────────────────────────────────────────────────────────────────

    async def admin_enrolment_out(self, enrolment_id: uuid.UUID) -> AdminEnrolmentOut:
        """One enrolment as the admin screens show it.

        Raises:
            HTTPException: 404 when there is no such enrolment.
        """
        row = await self.repo.admin_enrolment(enrolment_id)
        if row is None:
            raise _http(status.HTTP_404_NOT_FOUND, "enrolment_not_found")
        return _admin_out(*row)

    async def admin_list(
        self, *, status_filter: str | None, email: str | None, limit: int, offset: int
    ) -> list[AdminEnrolmentOut]:
        """Enrolments, newest first."""
        rows = await self.repo.admin_enrolments(status=status_filter, email=email, limit=limit, offset=offset)
        return [_admin_out(*row) for row in rows]

    async def retry_failed_unlocks(self, enrolment: TrainerEnrolment) -> int:
        """Rerun the unlock seeds that failed on a running enrolment. Returns how many opened."""
        course = await self.course_of(enrolment)
        opened = 0
        for state in sorted(enrolment.task_states, key=lambda s: s.task_n):
            if state.state != "locked" or state.seed_status != "failed":
                continue
            task = course.task(state.task_id)
            previous = course.task_by_n(state.task_n - 1)
            prev_state = self._states(enrolment).get(previous.id) if previous is not None else None
            if task is None or prev_state is None or prev_state.state != "passed":
                continue
            if await self._seed_and_unlock(enrolment, course, task, state):
                opened += 1
        return opened


def _admin_out(enrolment: TrainerEnrolment, email: str, course_key: str, version: str) -> AdminEnrolmentOut:
    return AdminEnrolmentOut(
        id=enrolment.id,
        user_id=enrolment.user_id,
        email=email,
        course_key=course_key,
        course_version=version,
        status=enrolment.status,  # type: ignore[arg-type]
        source=enrolment.source,  # type: ignore[arg-type]
        project_id=enrolment.project_id,
        current_task_n=max(enrolment.current_task_n or 1, 1),
        created_at=enrolment.created_at,
    )


# ── Entry points that open their own session ─────────────────────────────────


def _session_factory() -> Any:
    from app.database import async_session_factory

    return async_session_factory


def seed_lock_key(enrolment_id: uuid.UUID) -> int:
    """The PostgreSQL advisory lock key a running enrolment seed holds."""
    digest = hashlib.blake2b(b"oe_trainer.seed:" + enrolment_id.bytes, digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=True)


async def seed_on_enrol(enrolment_id: uuid.UUID) -> None:
    """Start one enrolment in a session of its own and commit (provisioning's ``seed_on_enrol``).

    The seed and the commit both run inside :func:`seeding`, so the events
    the seed publishes never read as learner activity. The transaction holds
    the advisory lock :func:`seed_lock_key` from start to commit (the seed
    itself only flushes and uses savepoints, so the lock spans all of it),
    and an admin reseed can tell a seed that is running from one that died
    with its process. A second seed of the same enrolment waits for the
    first and then does nothing unless the enrolment still needs seeding.

    Raises:
        Exception: the seed failed; provisioning marks the enrolment failed.
    """
    with seeding(enrolment_id):
        async with _session_factory()() as session:
            try:
                await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": seed_lock_key(enrolment_id)})
                current = await session.scalar(
                    select(TrainerEnrolment.status).where(TrainerEnrolment.id == enrolment_id)
                )
                if current != "provisioning":
                    # Another seed finished (or failed) while this one waited.
                    logger.info("Trainer seed of enrolment %s skipped: status is %s", enrolment_id, current)
                    await session.rollback()
                    return
                await TrainerService(session).start_enrolment(enrolment_id)
                await session.commit()
            except Exception:
                await session.rollback()
                raise


async def reseed_enrolment(
    session: AsyncSession, settings: Settings, enrolment_id: uuid.UUID, *, email_service: Any = None
) -> AdminEnrolmentOut:
    """Admin reseed (decision 41). Commits.

    A ``failed`` enrolment is started again from scratch (its seed is
    idempotent per ref); on success it is active and the "ready" email goes
    out. So is one left in ``provisioning`` by a seed that died with its
    process; while a seed really runs (it holds :func:`seed_lock_key`) the
    answer is 409 ``seed_running``. A running enrolment gets its failed
    unlock seeds rerun.
    """
    from app.modules.trainer.provisioning import send_course_ready_email

    # Before the row lock: a running seed holds the enrolment row FOR UPDATE,
    # and waiting on it would turn "a seed is running" into a long request.
    free = await session.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": seed_lock_key(enrolment_id)})
    if not free:
        raise _http(status.HTTP_409_CONFLICT, "seed_running")
    service = TrainerService(session, settings)
    enrolment = await service.repo.enrolment(enrolment_id, for_update=True)
    if enrolment is None:
        raise _http(status.HTTP_404_NOT_FOUND, "enrolment_not_found")
    if enrolment.status in ("failed", "provisioning"):
        enrolment.status = "provisioning"
        await session.commit()
        try:
            await seed_on_enrol(enrolment_id)
        except Exception as exc:
            logger.error("Trainer admin reseed failed for enrolment %s: %s", enrolment_id, type(exc).__name__)
            failed = await session.get(TrainerEnrolment, enrolment_id, populate_existing=True)
            if failed is not None:
                failed.status = "failed"
                failed.metadata_ = {**(failed.metadata_ or {}), "seed_error": type(exc).__name__}
            await session.commit()
        else:
            await session.get(TrainerEnrolment, enrolment_id, populate_existing=True)
            await send_course_ready_email(session, settings, enrolment_id, email_service=email_service)
    elif enrolment.status == "active":
        opened = await service.retry_failed_unlocks(enrolment)
        with seeding(enrolment.id):
            await session.commit()
        logger.info("Trainer admin reseed opened %d task(s) of enrolment %s", opened, enrolment_id)
    else:
        raise _http(status.HTTP_409_CONFLICT, f"cannot_reseed_{enrolment.status}")
    return await service.admin_enrolment_out(enrolment_id)


__all__ = [
    "ENGINE_VERSION",
    "LoadedCourse",
    "TrainerService",
    "answer_names",
    "check_views",
    "parse_course_row",
    "readback_views",
    "reseed_enrolment",
    "rings_of",
    "seed_lock_key",
    "seed_on_enrol",
    "task_status",
]
