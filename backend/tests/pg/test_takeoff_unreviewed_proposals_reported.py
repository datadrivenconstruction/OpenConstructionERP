"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠PG: the estimate says how much takeoff work it left out.

Excluding unreviewed proposals from priced quantities is correct and already
pinned by ``test_takeoff_proposals_excluded_from_quantities``. What that
exclusion creates is a silence: a user who ran plan reading, never worked the
review queue and then priced the project sees a total that is short of what the
drawing shows, with nothing to explain the difference.

``ai_takeoff.unreviewed_proposals`` fills that silence. These tests pin the two
halves that have to line up for it to mean anything: the repository counting the
right rows, and the rule reading a count it is actually given. The rule is a
WARNING and not an ERROR on purpose - the estimator refuses to apply a run whose
report carries errors, and pricing the confirmed subset is a legitimate thing to
want.

Real PostgreSQL because the count is aggregation SQL over an enum-ish column.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid

import pytest

from app.core.validation.engine import RuleCategory, Severity, ValidationContext
from app.core.validation.rules import UNREVIEWED_PROPOSALS_META_KEY, TakeoffUnreviewedProposalsRule
from app.modules.projects.models import Project
from app.modules.takeoff.models import TakeoffMeasurement
from app.modules.takeoff.repository import MeasurementRepository
from app.modules.users.models import User

SQUARE = [{"x": 0.0, "y": 0.0}, {"x": 10.0, "y": 0.0}, {"x": 10.0, "y": 10.0}, {"x": 0.0, "y": 10.0}]


async def _seed_project(session) -> Project:
    """Insert an owner and one project."""
    owner = User(email=f"unreviewed-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x")
    session.add(owner)
    await session.flush()
    project = Project(name="Unreviewed reporting", owner_id=owner.id, currency="EUR")
    session.add(project)
    await session.flush()
    return project


def _measurement(project_id, *, review_status: str, annotation: str) -> TakeoffMeasurement:
    """One 100 m2 area row in the given review state."""
    return TakeoffMeasurement(
        project_id=project_id,
        document_id=f"doc-{uuid.uuid4().hex[:8]}",
        page=1,
        type="area",
        group_name="Slabs",
        annotation=annotation,
        points=SQUARE,
        measurement_value=100.0,
        measurement_unit="m2",
        review_status=review_status,
        created_by="tester",
    )


async def _run_rule(pending: int | None) -> list:
    """Evaluate the rule as the estimator calls it, or without a count at all."""
    metadata: dict = {"base_currency": "EUR"}
    if pending is not None:
        metadata[UNREVIEWED_PROPOSALS_META_KEY] = pending
    return await TakeoffUnreviewedProposalsRule().validate(ValidationContext(data={"positions": []}, metadata=metadata))


@pytest.mark.asyncio
async def test_only_undecided_rows_are_counted(pg_session) -> None:
    """Confirmed work is in the estimate and a rejection is a decision already made."""
    project = await _seed_project(pg_session)
    pg_session.add_all(
        [
            _measurement(project.id, review_status="confirmed", annotation="Agreed slab"),
            _measurement(project.id, review_status="proposed", annotation="First guess"),
            _measurement(project.id, review_status="proposed", annotation="Second guess"),
            _measurement(project.id, review_status="rejected", annotation="Turned down"),
        ]
    )
    await pg_session.flush()

    count = await MeasurementRepository(pg_session).count_unreviewed_for_project(project.id)

    assert count == 2, "only the two undecided rows are work the estimate is missing"


@pytest.mark.asyncio
async def test_a_project_with_nothing_pending_counts_zero(pg_session) -> None:
    """No queue means no warning, which is what makes the warning worth reading."""
    project = await _seed_project(pg_session)
    pg_session.add(_measurement(project.id, review_status="confirmed", annotation="Agreed slab"))
    await pg_session.flush()

    assert await MeasurementRepository(pg_session).count_unreviewed_for_project(project.id) == 0


@pytest.mark.asyncio
async def test_the_count_does_not_leak_across_projects(pg_session) -> None:
    """A neighbour's unworked queue must not accuse this estimate of a gap."""
    mine = await _seed_project(pg_session)
    theirs = await _seed_project(pg_session)
    pg_session.add_all(
        [
            _measurement(mine.id, review_status="confirmed", annotation="Agreed slab"),
            _measurement(theirs.id, review_status="proposed", annotation="Their guess"),
        ]
    )
    await pg_session.flush()

    assert await MeasurementRepository(pg_session).count_unreviewed_for_project(mine.id) == 0


@pytest.mark.asyncio
async def test_pending_proposals_warn_without_blocking_the_estimate() -> None:
    """The report names the gap; applying the run stays the user's decision."""
    results = await _run_rule(3)

    assert len(results) == 1
    result = results[0]
    assert result.passed is False
    assert result.severity is Severity.WARNING, "ERROR would stop the run being applied at all"
    assert result.category is RuleCategory.COMPLETENESS
    assert "3" in result.message
    assert result.suggestion, "a warning with no way to clear it is just noise"


@pytest.mark.asyncio
async def test_an_empty_queue_passes() -> None:
    """Zero pending is a positive statement, not silence."""
    results = await _run_rule(0)

    assert len(results) == 1
    assert results[0].passed is True


def test_the_estimator_actually_reaches_this_rule() -> None:
    """The rule is registered where the estimator will hand it a context.

    This is the failure this whole change exists because of. A rule filed into
    a set no caller ever validates against never runs, and every test that
    calls a rule object directly stays green while that is true. Asking the
    registry the same question the engine asks is the only check that tells a
    working rule apart from one nothing will ever reach.

    Exactly once, not twice: the rule belongs to two sets and the estimator
    could grow to pass both, which would otherwise put the same warning in one
    report twice.
    """
    from app.core.validation.engine import rule_registry
    from app.core.validation.rules import register_builtin_rules

    register_builtin_rules()
    # The sets ai_estimator._validate_positions passes, minus the optional
    # regional one it appends per catalogue.
    reachable = [r.rule_id for r in rule_registry.get_rules_for_sets(["boq_quality", "ai_estimator"]) if r.enabled]

    assert reachable.count("ai_takeoff.unreviewed_proposals") == 1


def test_the_boq_report_reaches_this_rule_too() -> None:
    """A BOQ validation resolves to boq_quality when a project configures nothing.

    Gathering the count on the BOQ path is wasted work unless the rule sits in
    the set that path validates against, and boq_quality alone is what an
    untagged project resolves to.
    """
    from app.core.validation.engine import rule_registry
    from app.core.validation.rules import register_builtin_rules

    register_builtin_rules()
    reachable = [r.rule_id for r in rule_registry.get_rules_for_sets(["boq_quality"]) if r.enabled]

    assert reachable.count("ai_takeoff.unreviewed_proposals") == 1


@pytest.mark.asyncio
async def test_the_boq_helper_hands_the_rule_a_real_count(pg_session) -> None:
    """The BOQ path gathers the same number the estimator does."""
    from app.core.validation.rules import register_builtin_rules
    from app.modules.boq.router import _unreviewed_proposal_meta

    register_builtin_rules()

    project = await _seed_project(pg_session)
    pg_session.add_all(
        [
            _measurement(project.id, review_status="confirmed", annotation="Agreed slab"),
            _measurement(project.id, review_status="proposed", annotation="First guess"),
            _measurement(project.id, review_status="proposed", annotation="Second guess"),
        ]
    )
    await pg_session.flush()

    assert await _unreviewed_proposal_meta(pg_session, project.id, ["boq_quality"]) == {
        UNREVIEWED_PROPOSALS_META_KEY: 2
    }


@pytest.mark.asyncio
async def test_a_count_that_could_not_be_taken_stays_silent() -> None:
    """A broken query must not turn into a clean review queue on the report.

    Validation runs on the BOQ path as a secondary diagnostic that must never
    fail the request, so the count is caught. Catching it and passing zero
    would certify something nobody checked, so the key is omitted instead and
    the rule makes no claim at all.
    """
    from app.modules.boq.router import _unreviewed_proposal_meta

    class _BrokenSession:
        async def execute(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201, ARG002
            raise RuntimeError("database is unavailable")

    result = await _unreviewed_proposal_meta(_BrokenSession(), uuid.uuid4(), ["boq_quality"])  # type: ignore[arg-type]

    assert result == {}


@pytest.mark.asyncio
async def test_rule_sets_that_cannot_reach_the_rule_are_not_counted_for() -> None:
    """A project that configured the rule away is not charged for the query.

    ``validation_rule_sets`` is per project, so a project can legitimately
    replace the universal set with its own. Counting rows for a report that
    will not carry the warning is work done for nobody, once per validation
    and once per import.
    """
    from app.core.validation.rules import register_builtin_rules
    from app.modules.boq.router import _unreviewed_proposal_meta

    # Registered, so the skip is the sets not reaching the rule and not an
    # empty registry agreeing with the assertion for the wrong reason.
    register_builtin_rules()

    class _CountingSession:
        def __init__(self) -> None:
            self.queries = 0

        async def execute(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201, ARG002
            self.queries += 1
            raise RuntimeError("this session must never be asked")

    session = _CountingSession()

    result = await _unreviewed_proposal_meta(session, uuid.uuid4(), ["din276", "gaeb"])  # type: ignore[arg-type]

    assert result == {}
    assert session.queries == 0, "skipped is not the same as failed - a failed count also returns {}"


@pytest.mark.asyncio
async def test_no_count_means_no_claim() -> None:
    """A caller that never asked about the queue gets no verdict about it.

    The estimator is the only path that supplies the count today. Reporting a
    clean review queue to any other caller would certify something nobody
    checked, so an absent key has to mean silence rather than zero.
    """
    assert await _run_rule(None) == []
