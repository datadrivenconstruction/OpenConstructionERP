# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠An assignment can name the schedule activity it staffs.

Covers the whole of the link: the column is persisted on create and on
propose, a PATCH can both set and clear it, the list query filters on it, the
by-activity read stays inside the project whose access was verified, and the
``resources`` rule set both fires and stays quiet on the right inputs.

The rule tests do not stop at calling ``Rule().validate(...)``. A rule that no
engine ever reaches passes that kind of test exactly as a working one does, so
the reachability of the set is asserted separately and one finding is followed
all the way out of ``validation_engine.validate``.
"""

from __future__ import annotations

import sys
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.validation.engine import ValidationContext, rule_registry, validation_engine
from app.modules.resources.models import Assignment
from app.modules.resources.repository import AssignmentRepository
from app.modules.resources.schemas import (
    AssignmentCreate,
    AssignmentProposeRequest,
    AssignmentResponse,
    AssignmentUpdate,
)
from app.modules.resources.service import ResourcesService
from app.modules.resources.validators import (
    RESOURCES_RULE_SET,
    RESOURCES_RULES,
    AssignmentActivityMissing,
    AssignmentOutsideActivityWindow,
    AssignmentTargetAmbiguous,
    register_resources_rules,
)

START = datetime(2026, 8, 10, 8, 0, tzinfo=UTC)
END = datetime(2026, 8, 14, 17, 0, tzinfo=UTC)


# ── Doubles ───────────────────────────────────────────────────────────────


class _StubSession:
    """Enough AsyncSession surface for the assignment paths under test."""

    def __init__(self) -> None:
        self.executed: list[Any] = []
        self.rows: list[Any] = []

    async def refresh(self, obj: Any) -> None:
        return None

    async def flush(self) -> None:
        return None

    def add(self, obj: Any) -> None:
        return None

    async def execute(self, stmt: Any) -> Any:
        self.executed.append(stmt)
        rows = self.rows
        return SimpleNamespace(
            scalar_one=lambda: len(rows),
            scalar_one_or_none=lambda: rows[0] if rows else None,
            scalars=lambda: SimpleNamespace(all=lambda: rows),
            all=lambda: rows,
        )


class _RecordingAssignmentRepo:
    """Assignment repository double that records what it was handed."""

    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}
        self.created: list[Any] = []
        self.updated: list[dict[str, Any]] = []
        self.list_calls: list[dict[str, Any]] = []
        self.activity_rows: list[Any] = []

    async def get_by_id(self, assignment_id: uuid.UUID) -> Any:
        return self.rows.get(assignment_id)

    async def create(self, assignment: Any) -> Any:
        assignment.id = assignment.id or uuid.uuid4()
        self.rows[assignment.id] = assignment
        self.created.append(assignment)
        return assignment

    async def update_fields(self, assignment_id: uuid.UUID, **fields: Any) -> None:
        self.updated.append(fields)
        row = self.rows.get(assignment_id)
        for key, value in fields.items():
            setattr(row, key, value)

    async def list_for_resource(
        self,
        resource_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 200,
        status: str | None = None,
        activity_id: uuid.UUID | None = None,
    ) -> tuple[list[Any], int]:
        self.list_calls.append(
            {
                "resource_id": resource_id,
                "offset": offset,
                "limit": limit,
                "status": status,
                "activity_id": activity_id,
            }
        )
        return [], 0

    async def list_for_activity(
        self,
        activity_id: uuid.UUID,
        *,
        project_id: uuid.UUID,
        offset: int = 0,
        limit: int = 500,
        status: str | None = None,
    ) -> tuple[list[Any], int]:
        self.list_calls.append(
            {
                "activity_id": activity_id,
                "project_id": project_id,
                "offset": offset,
                "limit": limit,
                "status": status,
            }
        )
        return list(self.activity_rows), len(self.activity_rows)

    async def assignments_for_resource_in_window(self, *args: Any, **kwargs: Any) -> list[Any]:
        del args, kwargs
        return []


def _make_service(resource: Any | None = None) -> ResourcesService:
    """A service wired to doubles, with the assignment paths exercisable."""
    svc = ResourcesService.__new__(ResourcesService)
    svc.session = _StubSession()
    svc.assignment_repo = _RecordingAssignmentRepo()
    svc.resource_repo = SimpleNamespace(get_by_id=_returning(resource or _make_resource()))
    svc.resource_skill_repo = SimpleNamespace(list_for_resource=_returning([]))
    return svc


def _returning(value: Any) -> Any:
    """An async callable that answers ``value`` whatever it is asked."""

    async def _call(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        return value

    return _call


def _make_resource() -> Any:
    return SimpleNamespace(
        id=uuid.uuid4(),
        code="P-001",
        name="Test Person",
        resource_type="person",
        default_cost_rate=Decimal("50"),
        currency="EUR",
        status="active",
    )


def _make_assignment(
    *,
    activity_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
    start_at: datetime = START,
    end_at: datetime = END,
) -> Assignment:
    return Assignment(
        id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        task_id=task_id,
        activity_id=activity_id,
        start_at=start_at,
        end_at=end_at,
        allocation_percent=100,
        status="proposed",
    )


def _make_activity(*, start_date: Any = "2026-08-01", end_date: Any = "2026-08-31") -> Any:
    return SimpleNamespace(
        id=uuid.uuid4(),
        name="Second floor slab",
        wbs_code="1.2.3",
        activity_code="ACT-007",
        start_date=start_date,
        end_date=end_date,
    )


# ── Persistence ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_assignment_stores_the_activity_link() -> None:
    activity_id = uuid.uuid4()
    svc = _make_service()
    data = AssignmentCreate(
        resource_id=uuid.uuid4(),
        activity_id=activity_id,
        start_at=START,
        end_at=END,
    )

    assignment = await svc.create_assignment(data, user_id="u1")

    assert assignment.activity_id == activity_id
    assert svc.assignment_repo.created[0].activity_id == activity_id


@pytest.mark.asyncio
async def test_create_assignment_without_an_activity_stores_none() -> None:
    svc = _make_service()
    data = AssignmentCreate(resource_id=uuid.uuid4(), start_at=START, end_at=END)

    assignment = await svc.create_assignment(data, user_id="u1")

    assert assignment.activity_id is None


@pytest.mark.asyncio
async def test_propose_assignment_stores_the_activity_link() -> None:
    activity_id = uuid.uuid4()
    svc = _make_service()
    data = AssignmentProposeRequest(
        resource_id=uuid.uuid4(),
        activity_id=activity_id,
        start_at=START,
        end_at=END,
    )

    assignment = await svc.propose_assignment(data, user_id="u1")

    assert assignment.activity_id == activity_id


@pytest.mark.asyncio
async def test_patch_sets_the_activity_link() -> None:
    activity_id = uuid.uuid4()
    svc = _make_service()
    stored = _make_assignment()
    svc.assignment_repo.rows[stored.id] = stored

    await svc.update_assignment(stored.id, AssignmentUpdate(activity_id=activity_id))

    assert svc.assignment_repo.updated == [{"activity_id": activity_id}]
    assert stored.activity_id == activity_id


@pytest.mark.asyncio
async def test_patch_clears_the_activity_link() -> None:
    svc = _make_service()
    stored = _make_assignment(activity_id=uuid.uuid4())
    svc.assignment_repo.rows[stored.id] = stored

    await svc.update_assignment(stored.id, AssignmentUpdate(activity_id=None))

    # An explicit null must reach the column. Were exclude_unset to swallow it,
    # "detach this booking from its bar" would silently do nothing.
    assert svc.assignment_repo.updated == [{"activity_id": None}]
    assert stored.activity_id is None


@pytest.mark.asyncio
async def test_patch_that_does_not_mention_the_activity_leaves_it_alone() -> None:
    activity_id = uuid.uuid4()
    svc = _make_service()
    stored = _make_assignment(activity_id=activity_id)
    svc.assignment_repo.rows[stored.id] = stored

    await svc.update_assignment(stored.id, AssignmentUpdate(notes="reworded"))

    assert "activity_id" not in svc.assignment_repo.updated[0]
    assert stored.activity_id == activity_id


def test_the_read_schema_returns_the_activity_link() -> None:
    activity_id = uuid.uuid4()
    row = _make_assignment(activity_id=activity_id)
    row.created_at = START
    row.updated_at = START
    row.metadata_ = {}
    row.cost_rate = Decimal("0")
    row.currency = "EUR"
    row.notes = ""

    assert AssignmentResponse.model_validate(row).activity_id == activity_id


# ── List filter ───────────────────────────────────────────────────────────


def _where_text(stmt: Any) -> str:
    """The WHERE clause of a SELECT as text, or empty when it has none.

    Compiling the whole statement would not do: ``activity_id`` is in the
    select list of every one of these queries, so a match on the full SQL
    proves only that the column exists.
    """
    clause = getattr(stmt, "whereclause", None)
    return str(clause) if clause is not None else ""


@pytest.mark.asyncio
async def test_repository_list_constrains_the_activity_when_asked() -> None:
    session = _StubSession()
    repo = AssignmentRepository(session)

    await repo.list_for_resource(uuid.uuid4(), activity_id=uuid.uuid4())

    assert any("activity_id" in _where_text(s) for s in session.executed)


@pytest.mark.asyncio
async def test_repository_list_does_not_constrain_the_activity_by_default() -> None:
    session = _StubSession()
    repo = AssignmentRepository(session)

    await repo.list_for_resource(uuid.uuid4())

    # Guards the test above: without this, a query that always mentions the
    # column would satisfy it while filtering nothing.
    assert not any("activity_id" in _where_text(s) for s in session.executed)


@pytest.mark.asyncio
async def test_repository_list_for_activity_constrains_the_activity() -> None:
    session = _StubSession()
    repo = AssignmentRepository(session)

    await repo.list_for_activity(uuid.uuid4(), project_id=uuid.uuid4())

    assert any("activity_id" in _where_text(s) for s in session.executed)


@pytest.mark.asyncio
async def test_repository_list_for_activity_scopes_the_project_in_sql() -> None:
    """The tenant scope has to be in the WHERE clause, not applied to a page.

    Filtering the returned page in Python would leave the caller with short
    pages, rows skipped between pages, and a total counting records the
    filter had already removed. The count query has to carry the scope too,
    or the total describes a wider set than the rows do.
    """
    session = _StubSession()
    repo = AssignmentRepository(session)

    await repo.list_for_activity(uuid.uuid4(), project_id=uuid.uuid4())

    # Two statements: the count, whose predicate lives inside a subquery and
    # so is not reachable through ``whereclause``, and the page. The count's
    # select list is only ``count(*)``, so reading its whole SQL cannot match
    # a column name by accident the way the page's select list would.
    count_stmt, page_stmt = session.executed[0], session.executed[-1]
    count_sql = str(count_stmt)
    assert "activity_id" in count_sql
    assert "project_id" in count_sql

    page_where = _where_text(page_stmt)
    assert "activity_id" in page_where
    assert "project_id" in page_where


@pytest.mark.asyncio
async def test_service_hands_the_activity_filter_to_the_repository() -> None:
    activity_id = uuid.uuid4()
    svc = _make_service()

    await svc.list_assignments_for_resource(uuid.uuid4(), activity_id=activity_id)

    assert svc.assignment_repo.list_calls[0]["activity_id"] == activity_id


@pytest.mark.asyncio
async def test_service_hands_the_project_scope_down_to_the_query() -> None:
    """The service must not re-filter a page the query already scoped.

    Its whole job here is to pass the verified project through, so the tests
    that matter are this one and the repository's WHERE clause above.
    """
    project_id = uuid.uuid4()
    activity_id = uuid.uuid4()
    mine = _make_assignment()
    mine.project_id = project_id
    svc = _make_service()
    svc.assignment_repo.activity_rows = [mine]

    items, total = await svc.list_assignments_for_activity(activity_id, project_id=project_id)

    call = svc.assignment_repo.list_calls[0]
    assert call["activity_id"] == activity_id
    assert call["project_id"] == project_id
    assert items == [mine]
    assert total == 1


# ── Rules: outside the activity window ────────────────────────────────────


async def _run(rule: Any, payload: dict[str, Any]) -> list[Any]:
    return await rule.validate(ValidationContext(data=payload))


@pytest.mark.asyncio
async def test_window_rule_fires_when_the_booking_starts_before_the_activity() -> None:
    assignment = _make_assignment(
        activity_id=uuid.uuid4(),
        start_at=datetime(2026, 7, 20, 8, 0, tzinfo=UTC),
        end_at=datetime(2026, 8, 5, 17, 0, tzinfo=UTC),
    )
    results = await _run(
        AssignmentOutsideActivityWindow(),
        {"assignment": assignment, "activity": _make_activity()},
    )

    assert [r.passed for r in results] == [False]
    assert results[0].details["days_early"] == 12
    assert results[0].details["days_late"] == 0


@pytest.mark.asyncio
async def test_window_rule_fires_when_the_booking_runs_past_the_activity() -> None:
    assignment = _make_assignment(
        activity_id=uuid.uuid4(),
        start_at=datetime(2026, 8, 20, 8, 0, tzinfo=UTC),
        end_at=datetime(2026, 9, 4, 17, 0, tzinfo=UTC),
    )
    results = await _run(
        AssignmentOutsideActivityWindow(),
        {"assignment": assignment, "activity": _make_activity()},
    )

    assert [r.passed for r in results] == [False]
    assert results[0].details["days_late"] == 4


@pytest.mark.asyncio
async def test_window_rule_is_quiet_when_the_booking_sits_inside() -> None:
    assignment = _make_assignment(activity_id=uuid.uuid4())
    results = await _run(
        AssignmentOutsideActivityWindow(),
        {"assignment": assignment, "activity": _make_activity()},
    )

    assert [r.passed for r in results] == [True]


@pytest.mark.asyncio
async def test_window_rule_is_quiet_on_the_boundary_days() -> None:
    assignment = _make_assignment(
        activity_id=uuid.uuid4(),
        start_at=datetime(2026, 8, 1, 8, 0, tzinfo=UTC),
        end_at=datetime(2026, 8, 31, 17, 0, tzinfo=UTC),
    )
    results = await _run(
        AssignmentOutsideActivityWindow(),
        {"assignment": assignment, "activity": _make_activity()},
    )

    assert [r.passed for r in results] == [True]


@pytest.mark.asyncio
async def test_window_rule_is_quiet_when_no_activity_is_named() -> None:
    results = await _run(
        AssignmentOutsideActivityWindow(),
        {"assignment": _make_assignment(), "activity": None},
    )

    assert [r.passed for r in results] == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["", "   ", "not a date", None])
async def test_window_rule_blames_nobody_for_unreadable_activity_dates(bad: Any) -> None:
    assignment = _make_assignment(
        activity_id=uuid.uuid4(),
        start_at=datetime(2030, 1, 1, tzinfo=UTC),
        end_at=datetime(2030, 1, 2, tzinfo=UTC),
    )
    results = await _run(
        AssignmentOutsideActivityWindow(),
        {"assignment": assignment, "activity": _make_activity(start_date=bad)},
    )

    # The dates are wildly outside the activity, so a rule that guessed a
    # window from the unreadable value would fire here.
    assert [r.passed for r in results] == [True]


@pytest.mark.asyncio
async def test_window_rule_reads_a_datetime_stamped_activity_date() -> None:
    assignment = _make_assignment(
        activity_id=uuid.uuid4(),
        start_at=datetime(2026, 9, 10, 8, 0, tzinfo=UTC),
        end_at=datetime(2026, 9, 12, 17, 0, tzinfo=UTC),
    )
    results = await _run(
        AssignmentOutsideActivityWindow(),
        {
            "assignment": assignment,
            "activity": _make_activity(start_date="2026-08-01T00:00:00Z", end_date="2026-08-31T23:59:59Z"),
        },
    )

    assert [r.passed for r in results] == [False]


# ── Rules: two targets at once ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ambiguity_rule_fires_when_both_targets_are_named() -> None:
    assignment = _make_assignment(activity_id=uuid.uuid4(), task_id=uuid.uuid4())

    results = await _run(AssignmentTargetAmbiguous(), {"assignment": assignment})

    assert [r.passed for r in results] == [False]
    assert set(results[0].details) == {"activity_id", "task_id"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("activity", "task"),
    [(True, False), (False, True), (False, False)],
)
async def test_ambiguity_rule_is_quiet_on_at_most_one_target(activity: bool, task: bool) -> None:
    assignment = _make_assignment(
        activity_id=uuid.uuid4() if activity else None,
        task_id=uuid.uuid4() if task else None,
    )

    results = await _run(AssignmentTargetAmbiguous(), {"assignment": assignment})

    assert [r.passed for r in results] == [True]


# ── Rules: the activity does not resolve ──────────────────────────────────


@pytest.mark.asyncio
async def test_missing_rule_fires_when_the_named_activity_is_gone() -> None:
    assignment = _make_assignment(activity_id=uuid.uuid4())

    results = await _run(AssignmentActivityMissing(), {"assignment": assignment, "activity": None})

    assert [r.passed for r in results] == [False]


@pytest.mark.asyncio
async def test_missing_rule_is_quiet_when_no_activity_is_named() -> None:
    results = await _run(AssignmentActivityMissing(), {"assignment": _make_assignment(), "activity": None})

    assert [r.passed for r in results] == [True]


@pytest.mark.asyncio
async def test_missing_rule_is_quiet_when_the_activity_resolves() -> None:
    assignment = _make_assignment(activity_id=uuid.uuid4())

    results = await _run(
        AssignmentActivityMissing(),
        {"assignment": assignment, "activity": _make_activity()},
    )

    assert [r.passed for r in results] == [True]


@pytest.mark.asyncio
async def test_missing_rule_is_quiet_when_the_schedule_register_is_absent() -> None:
    """An activity that cannot be sought is not an activity that is gone.

    On an install without the schedule module the lookup returns None for
    every id there is. Reading that as "deleted" would accuse every linked
    assignment on the install of staffing nothing.
    """
    assignment = _make_assignment(activity_id=uuid.uuid4())

    results = await _run(
        AssignmentActivityMissing(),
        {"assignment": assignment, "activity": None, "activity_lookup_available": False},
    )

    assert [r.passed for r in results] == [True]


@pytest.mark.asyncio
async def test_missing_rule_fires_when_the_lookup_ran_and_found_nothing() -> None:
    """The other side of the flag: a lookup that ran is worth believing."""
    assignment = _make_assignment(activity_id=uuid.uuid4())

    results = await _run(
        AssignmentActivityMissing(),
        {"assignment": assignment, "activity": None, "activity_lookup_available": True},
    )

    assert [r.passed for r in results] == [False]


@pytest.mark.asyncio
async def test_every_rule_survives_an_empty_payload() -> None:
    for rule_cls in RESOURCES_RULES:
        results = await _run(rule_cls(), {})
        assert [r.passed for r in results] == [True], rule_cls.__name__


# ── Reachability ──────────────────────────────────────────────────────────


def test_the_rule_set_resolves_to_exactly_these_rules() -> None:
    """A rule nothing registers is indistinguishable from a rule that passed."""
    register_resources_rules()

    ids = [r.rule_id for r in rule_registry.get_rules_for_sets([RESOURCES_RULE_SET]) if r.enabled]

    for rule_cls in RESOURCES_RULES:
        assert ids.count(rule_cls.rule_id) == 1, f"{rule_cls.rule_id} is not reachable exactly once"


def test_registration_is_idempotent() -> None:
    register_resources_rules()
    register_resources_rules()

    ids = [r.rule_id for r in rule_registry.get_rules_for_sets([RESOURCES_RULE_SET])]

    assert len(ids) == len(set(ids))


@pytest.mark.asyncio
async def test_the_engine_reaches_the_window_rule() -> None:
    """Follow one finding all the way out of the engine, not just the rule.

    ``validate`` on an unregistered set returns a clean report, which reads
    exactly like a pass. This is the assertion that tells the two apart.
    """
    register_resources_rules()
    assignment = _make_assignment(
        activity_id=uuid.uuid4(),
        start_at=datetime(2026, 7, 1, 8, 0, tzinfo=UTC),
        end_at=datetime(2026, 7, 3, 17, 0, tzinfo=UTC),
    )

    report = await validation_engine.validate(
        data={"assignment": assignment, "activity": _make_activity()},
        rule_sets=[RESOURCES_RULE_SET],
        target_type="resource_assignment",
        target_id=str(assignment.id),
    )

    assert report.unsupported_rule_sets == []
    assert [r.rule_id for r in report.warnings] == ["resources.assignment_outside_activity_window"]


@pytest.mark.asyncio
async def test_service_validate_assignment_reports_the_finding() -> None:
    register_resources_rules()
    activity = _make_activity()
    assignment = _make_assignment(
        activity_id=activity.id,
        start_at=datetime(2026, 7, 1, 8, 0, tzinfo=UTC),
        end_at=datetime(2026, 7, 3, 17, 0, tzinfo=UTC),
    )
    svc = _make_service()
    svc.assignment_repo.rows[assignment.id] = assignment
    svc.session.rows = [activity]

    report = await svc.validate_assignment(assignment.id)

    assert report.assignment_id == assignment.id
    assert report.warning_count == 1
    assert report.error_count == 0
    finding = report.findings[0]
    assert finding.rule_id == "resources.assignment_outside_activity_window"
    # The i18n key must not repeat the module segment the rule id already has.
    assert finding.key == "resources.validation.assignment_outside_activity_window"


@pytest.mark.asyncio
async def test_service_validate_assignment_is_clean_on_a_well_placed_booking() -> None:
    register_resources_rules()
    activity = _make_activity()
    assignment = _make_assignment(activity_id=activity.id, start_at=START, end_at=END)
    svc = _make_service()
    svc.assignment_repo.rows[assignment.id] = assignment
    svc.session.rows = [activity]

    report = await svc.validate_assignment(assignment.id)

    assert report.findings == []
    assert report.warning_count == 0


@pytest.mark.asyncio
async def test_service_validate_assignment_flags_an_activity_that_is_gone() -> None:
    register_resources_rules()
    assignment = _make_assignment(activity_id=uuid.uuid4())
    svc = _make_service()
    svc.assignment_repo.rows[assignment.id] = assignment
    svc.session.rows = []  # the activity does not resolve

    report = await svc.validate_assignment(assignment.id)

    assert [f.rule_id for f in report.findings] == ["resources.assignment_activity_missing"]


@pytest.mark.asyncio
async def test_service_says_nothing_when_there_is_no_schedule_register_to_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without the schedule module the report has to stay empty, not accuse.

    ``None`` in ``sys.modules`` is what an absent module looks like to an
    import statement: the import raises ``ImportError``. The same code path a
    partial install takes, without a partial install.
    """
    register_resources_rules()
    monkeypatch.setitem(sys.modules, "app.modules.schedule.models", None)
    assignment = _make_assignment(activity_id=uuid.uuid4())
    svc = _make_service()
    svc.assignment_repo.rows[assignment.id] = assignment
    svc.session.rows = []

    activity, lookup_available = await svc._resolve_activity(assignment.activity_id)  # noqa: SLF001
    report = await svc.validate_assignment(assignment.id)

    assert activity is None
    assert lookup_available is False
    assert report.findings == []


def test_the_window_never_widens_by_a_day_somewhere_in_the_maths() -> None:
    """Pin the arithmetic the day counts rest on, in plain terms."""
    start = datetime(2026, 8, 1, tzinfo=UTC)
    assert (start + timedelta(days=12)).date() == datetime(2026, 8, 13, tzinfo=UTC).date()
