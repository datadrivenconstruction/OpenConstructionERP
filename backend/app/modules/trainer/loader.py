# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Course loader: read course files, validate them, upsert ``oe_trainer_course``.

The pipeline per file is Import -> Parse -> VALIDATE -> Store:

1. :func:`parse_course_bytes` (pure): sha256 of the raw bytes,
   ``json.loads(parse_float=Decimal)``, :func:`spec.normalise_course_dict`
   and the :class:`spec.CourseSpec` shape gate.
2. :func:`validate_course` runs the ``trainer_spec`` rule set on the same
   normalised dict, so a file that fails the shape still gets a verdict from
   every rule. It fails closed: a rule that raised (an engine-error row, which
   the engine itself never counts as a failure) or a rule set the engine did
   not know makes the course invalid. It then builds the seed plan
   (decision 39): a ``PlanError`` is an error of the course, not of a later
   enrolment.
3. :func:`load_courses_dir` stores every course through a
   :class:`CourseStore` (decision 26, design section 3.1): a valid one as
   ``active``, an invalid one as ``invalid`` with its error list in
   ``validation_report["error_list"]`` and an empty spec, so it is never
   offered or seeded and an admin sees why. A file is never a reason for the
   boot to stop.

A stored valid ``(course_key, version)`` is never overwritten: the same bytes
again are a no-op, different bytes fail ``trainer.version_not_bumped`` and
the stored row stays, because enrolments grade against the content they
started on. An ``invalid`` row was never offered, so nobody pinned it, and new
bytes replace it in place without a version bump.

:func:`load_courses_at_startup` is the boot entry point. The DB part sits
behind :class:`CourseStore`, so the unit tests run with a fake store and no
database.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol

from pydantic import ValidationError

from app.core.validation.engine import Severity, validation_engine
from app.modules.trainer.spec import COLUMN_LIMITS, CourseSpec, normalise_course_dict
from app.modules.trainer.validators import TRAINER_SPEC_RULE_SET, register_trainer_rules

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

#: File names the loader picks up inside the courses directory.
COURSE_FILE_GLOB = "course_*_v*.json"

LoadStatus = Literal["loaded", "unchanged", "invalid", "refused", "failed"]


# ── Pure part ────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class ParsedCourse:
    """One course file after parsing and the shape gate.

    Attributes:
        source_file: Basename of the file (never a full path).
        sha256: Hex digest of the raw bytes.
        data: The normalised dict the rules run on, or ``None`` when the bytes
            are not a JSON object.
        spec: :meth:`CourseSpec.dump_for_storage` when the shape gate passed.
        errors: Shape and parse errors, ``"<json path>: <message>"``.
    """

    source_file: str
    sha256: str
    data: dict[str, Any] | None
    spec: dict[str, Any] | None
    errors: list[str] = field(default_factory=list)

    @property
    def course_key(self) -> str | None:
        """The course ``id`` from the file, when it has one."""
        value = (self.data or {}).get("id")
        return value if isinstance(value, str) else None

    @property
    def version(self) -> str | None:
        """The course ``version`` from the file, when it has one."""
        value = (self.data or {}).get("version")
        return value if isinstance(value, str) else None


def _error_lines(exc: ValidationError) -> list[str]:
    lines = []
    for err in exc.errors():
        path = ".".join(str(part) for part in err["loc"]) or "<root>"
        lines.append(f"{path}: {err['msg']}")
    return lines


def parse_course_bytes(raw: bytes, source_file: str) -> ParsedCourse:
    """Hash, parse, normalise and shape-check one course file.

    Pure: no I/O, no database, no rule engine.

    Args:
        raw: The file's bytes.
        source_file: Name to record; reduced to its basename.

    Returns:
        A :class:`ParsedCourse`; ``spec`` is ``None`` when any step failed.
    """
    name = Path(source_file).name
    digest = hashlib.sha256(raw).hexdigest()
    try:
        loaded = json.loads(raw.decode("utf-8-sig"), parse_float=Decimal)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return ParsedCourse(name, digest, None, None, [f"<file>: not valid UTF-8 JSON ({exc})"])
    data, problems = normalise_course_dict(loaded)
    if problems:
        return ParsedCourse(name, digest, None, None, list(problems))
    try:
        spec = CourseSpec.model_validate(data).dump_for_storage()
    except ValidationError as exc:
        return ParsedCourse(name, digest, data, None, _error_lines(exc))
    return ParsedCourse(name, digest, data, spec)


# ── Validation ───────────────────────────────────────────────────────────────


@dataclass(slots=True)
class CourseVerdict:
    """Shape gate plus rule set verdict for one parsed course."""

    valid: bool
    errors: list[str]
    report: dict[str, Any]


def _row(result: Any) -> dict[str, Any]:
    return {
        "rule_id": result.rule_id,
        "severity": str(getattr(result.severity, "value", result.severity)),
        "element_ref": result.element_ref,
        "reason": (result.details or {}).get("reason"),
        "message": result.message,
        "engine_error": bool(result.is_engine_error),
    }


async def validate_course(parsed: ParsedCourse, *, previous_sha256: str | None = None) -> CourseVerdict:
    """Run the ``trainer_spec`` rule set and combine it with the shape gate.

    Args:
        parsed: Output of :func:`parse_course_bytes`.
        previous_sha256: The sha256 already stored for this course and
            version, if any; different content under it is refused.

    Returns:
        The verdict. ``valid`` is true only when the shape gate passed, no
        ERROR finding was raised, no rule crashed and the rule set ran.
    """
    errors = list(parsed.errors)
    if parsed.data is None:
        return CourseVerdict(False, errors, {"status": "unparsed", "errors": 0, "warnings": 0, "results": []})
    register_trainer_rules()
    report = await validation_engine.validate(
        data=parsed.data,
        rule_sets=[TRAINER_SPEC_RULE_SET],
        target_type="trainer_course",
        target_id=parsed.course_key or parsed.source_file,
        region=parsed.data.get("country") if isinstance(parsed.data.get("country"), str) else None,
        metadata={"sha256": parsed.sha256, "previous_sha256": previous_sha256},
    )
    failed = [r for r in report.results if not r.passed or r.is_engine_error]
    if TRAINER_SPEC_RULE_SET not in report.supported_rule_sets:
        errors.append(f"rule set {TRAINER_SPEC_RULE_SET} is not registered")
    for result in failed:
        if result.is_engine_error:
            errors.append(f"{result.rule_id}: rule crashed, course treated as invalid")
        elif result.severity == Severity.ERROR:
            errors.append(f"{result.rule_id} at {result.element_ref}: {result.message}")
    errors.extend(seed_plan_errors(parsed))
    summary = {
        "status": str(getattr(report.status, "value", report.status)),
        "errors": len(report.errors),
        "warnings": len(report.warnings),
        "engine_errors": len(report.engine_errors),
        "results": [_row(r) for r in failed],
    }
    return CourseVerdict(not errors, errors, summary)


def seed_plan_errors(parsed: ParsedCourse) -> list[str]:
    """The seeder's plan problems for a course that passed the shape gate (decision 39).

    The plan is built at load, so a seed whose blocks contradict each other
    stores the course as invalid instead of failing a learner's enrolment.
    A course that failed the shape gate has no spec to plan; its shape errors
    already make it invalid.
    """
    if parsed.spec is None:
        return []
    from app.modules.trainer.seeder.plan import PlanError, build_plan

    try:
        build_plan(parsed.spec)
    except PlanError as exc:
        return [f"seed plan: {problem}" for problem in exc.problems]
    except ValidationError as exc:
        return [f"seed plan: {line}" for line in _error_lines(exc)]
    return []


# ── Storage ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class StoredCourse:
    """What the loader needs to know about a row already stored."""

    sha256: str
    status: str


@dataclass(slots=True)
class CourseRecord:
    """Everything one ``oe_trainer_course`` row holds."""

    course_key: str
    version: str
    country: str
    language: str
    currency: str
    title: str
    source_file: str
    sha256: str
    spec: dict[str, Any]
    validation_report: dict[str, Any]
    status: str = "active"
    loaded_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class CourseStore(Protocol):
    """Where loaded courses go; the loader never talks to the ORM directly."""

    async def get(self, course_key: str, version: str) -> StoredCourse | None:
        """Return the stored row of ``(course_key, version)``, or ``None``."""
        ...

    async def insert(self, record: CourseRecord) -> None:
        """Insert a new row; called only for a ``(course_key, version)`` with no row."""
        ...

    async def replace(self, record: CourseRecord) -> None:
        """Overwrite the row of an invalid course; called for no other status."""
        ...


def _row_values(record: CourseRecord) -> dict[str, Any]:
    return {
        "course_key": record.course_key,
        "version": record.version,
        "country": record.country,
        "language": record.language,
        "currency": record.currency,
        "title": record.title,
        "source_file": record.source_file,
        "sha256": record.sha256,
        "spec": record.spec,
        "validation_report": record.validation_report,
        "status": record.status,
        "loaded_at": record.loaded_at,
    }


class SqlCourseStore:
    """:class:`CourseStore` over an ``AsyncSession``; the caller commits.

    Every write runs inside a SAVEPOINT. One failed write (a unique-constraint
    race with a second worker booting at the same time) then rolls back alone
    instead of leaving the boot session in pending-rollback, which would fail
    every later file and the caller's final commit.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, course_key: str, version: str) -> StoredCourse | None:
        """Return the stored row of ``(course_key, version)``, or ``None``."""
        from sqlalchemy import select

        from app.modules.trainer.models import TrainerCourse

        stmt = select(TrainerCourse.sha256, TrainerCourse.status).where(
            TrainerCourse.course_key == course_key, TrainerCourse.version == version
        )
        row = (await self._session.execute(stmt)).one_or_none()
        return StoredCourse(row.sha256, row.status) if row is not None else None

    async def insert(self, record: CourseRecord) -> None:
        """Add the row inside a SAVEPOINT and flush it."""
        from app.modules.trainer.models import TrainerCourse

        async with self._session.begin_nested():
            self._session.add(TrainerCourse(**_row_values(record)))
            await self._session.flush()

    async def replace(self, record: CourseRecord) -> None:
        """Overwrite an invalid row inside a SAVEPOINT; a row of any other status is left alone."""
        from sqlalchemy import update

        from app.modules.trainer.models import TrainerCourse

        stmt = (
            update(TrainerCourse)
            .where(
                TrainerCourse.course_key == record.course_key,
                TrainerCourse.version == record.version,
                TrainerCourse.status == "invalid",
            )
            .values(**_row_values(record))
            .execution_options(synchronize_session=False)
        )
        async with self._session.begin_nested():
            result = await self._session.execute(stmt)
        if result.rowcount != 1:
            msg = f"no invalid row of {record.course_key} {record.version} to replace"
            raise RuntimeError(msg)


# ── Directory walk ───────────────────────────────────────────────────────────


@dataclass(slots=True)
class LoadOutcome:
    """What happened to one file.

    ``status``: ``loaded`` (stored active), ``invalid`` (stored as invalid
    with its errors, or only logged when the file names no course id and
    version), ``unchanged`` (same bytes as the stored row), ``refused`` (new
    bytes under a version stored valid; nothing written) or ``failed`` (an
    unexpected error; nothing written for this file).
    """

    source_file: str
    status: LoadStatus
    course_key: str | None = None
    version: str | None = None
    errors: list[str] = field(default_factory=list)


def _fit(value: Any, column: str, width: int | None = None) -> str:
    text = value if isinstance(value, str) else ""
    return text[: width if width is not None else COLUMN_LIMITS[column]]


def _record(parsed: ParsedCourse, verdict: CourseVerdict) -> CourseRecord:
    """The row for a parsed course; an invalid one keeps no spec and fits every column."""
    valid = verdict.valid and parsed.spec is not None
    data = parsed.data or {}
    report = dict(verdict.report, error_list=list(verdict.errors))
    return CourseRecord(
        course_key=_fit(parsed.course_key, "course_key"),
        version=_fit(parsed.version, "version"),
        country=_fit(data.get("country"), "country", 2),
        language=_fit(data.get("language"), "language"),
        currency=_fit(data.get("currency"), "currency", 3),
        title=_fit(data.get("title"), "title"),
        source_file=_fit(parsed.source_file, "source_file", 255),
        sha256=parsed.sha256,
        spec=parsed.spec if valid and parsed.spec is not None else {},
        validation_report=report,
        status="active" if valid else "invalid",
    )


def _storable_key(parsed: ParsedCourse) -> bool:
    key, version = parsed.course_key, parsed.version
    return bool(
        key and version and len(key) <= COLUMN_LIMITS["course_key"] and len(version) <= COLUMN_LIMITS["version"]
    )


async def load_course_file(path: Path, store: CourseStore) -> LoadOutcome:
    """Load one file into ``store`` (decision 26).

    A valid course is stored ``active``. An invalid one is stored ``invalid``
    with its error list and no spec, so it is never offered and an admin sees
    why; it may replace an earlier invalid row of the same version, because
    nobody can have pinned that. New bytes under a version stored valid are
    refused (``trainer.version_not_bumped``) and nothing is written.

    Raises:
        Exception: only from the store; :func:`load_courses_dir` turns it into
            a ``failed`` outcome.
    """
    try:
        raw = path.read_bytes()
    except OSError as exc:
        logger.warning("trainer course %s unreadable: %s", path.name, exc)
        return LoadOutcome(path.name, "failed", errors=[str(exc)])
    parsed = parse_course_bytes(raw, path.name)
    key, version = parsed.course_key, parsed.version
    stored = await store.get(key, version) if _storable_key(parsed) and key and version else None
    if stored is not None and stored.sha256 == parsed.sha256:
        return LoadOutcome(path.name, "unchanged", key, version)
    pinned = stored is not None and stored.status != "invalid"
    verdict = await validate_course(parsed, previous_sha256=stored.sha256 if pinned and stored else None)
    if pinned:
        errors = verdict.errors or [f"{key} v{version} is stored valid; bump the version to change it"]
        logger.error(
            "trainer course %s refused; %s v%s stays as stored:\n  %s",
            path.name,
            key,
            version,
            "\n  ".join(errors),
        )
        return LoadOutcome(path.name, "refused", key, version, errors)
    if not verdict.valid:
        logger.error(
            "trainer course %s is invalid, %d error(s):\n  %s",
            path.name,
            len(verdict.errors),
            "\n  ".join(verdict.errors),
        )
    if not _storable_key(parsed):
        return LoadOutcome(path.name, "invalid", key, version, verdict.errors)
    record = _record(parsed, verdict)
    if stored is None:
        await store.insert(record)
    else:
        await store.replace(record)
    if record.status == "active":
        logger.info("trainer course %s v%s loaded from %s", key, version, path.name)
        return LoadOutcome(path.name, "loaded", key, version)
    return LoadOutcome(path.name, "invalid", key, version, verdict.errors)


def resolve_courses_dir(directory: str | Path | None = None) -> Path | None:
    """Return the courses directory, from the argument or ``Settings.trainer_courses_dir``.

    An empty setting means no courses; that is the normal state of an install
    without the academy.
    """
    if directory is None:
        from app.config import get_settings

        directory = get_settings().trainer_courses_dir
    text = str(directory).strip()
    return Path(text) if text else None


async def load_courses_dir(store: CourseStore, directory: str | Path | None = None) -> list[LoadOutcome]:
    """Load every ``course_*_v*.json`` of the courses directory into ``store``.

    Args:
        store: Destination of the courses.
        directory: Override for ``Settings.trainer_courses_dir``.

    Returns:
        One outcome per file, in file-name order. Empty when no directory is
        configured or it does not exist. One file's failure, even an
        unexpected exception from the store, never stops the others.
    """
    root = resolve_courses_dir(directory)
    if root is None:
        return []
    if not root.is_dir():
        logger.warning("trainer courses directory %s does not exist; no courses loaded", root)
        return []
    outcomes: list[LoadOutcome] = []
    for path in sorted(root.glob(COURSE_FILE_GLOB)):
        try:
            outcomes.append(await load_course_file(path, store))
        except Exception as exc:  # one bad file must never stop the boot
            logger.exception("trainer course %s failed to load", path.name)
            outcomes.append(LoadOutcome(path.name, "failed", errors=[f"loader error: {exc}"]))
    return outcomes


def _session_factory() -> Any:
    from app.database import async_session_factory

    return async_session_factory


async def load_courses_at_startup() -> list[LoadOutcome]:
    """Load the configured courses in one session and commit; never raises.

    Called by ``trainer.on_startup`` when the academy flag is on. Any failure,
    from opening the session to the final commit, is logged and the boot goes
    on with whatever courses were stored before.
    """
    try:
        async with _session_factory()() as session:
            outcomes = await load_courses_dir(SqlCourseStore(session))
            await session.commit()
    except Exception:  # the boot must never crash on course loading
        logger.exception("trainer course load at startup failed; the stored courses are unchanged")
        return []
    counts: dict[str, int] = {}
    for outcome in outcomes:
        counts[outcome.status] = counts.get(outcome.status, 0) + 1
    logger.info("trainer courses at startup: %s", counts or "no course files")
    return outcomes
