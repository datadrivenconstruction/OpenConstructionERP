# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cross-project validation status (``GET /validation/portfolio-status/``).

What has to hold for a head of estimating to trust the card:

* only projects the caller may open are listed (owner, team member, admin),
  archived projects never are;
* each estimate shows its LATEST report, and the project counts add up those
  latest reports, not the report history;
* an estimate nobody validated reads ``not_validated``, never ``passed``, and
  so does a project with one passed estimate and one unvalidated one;
* projects come back worst first;
* the statement count does not grow with the number of projects.

Run:  pytest tests/unit/test_validation_portfolio_status.py
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import event

from app.modules.validation.portfolio import (
    STATE_ERRORS,
    STATE_INFO,
    STATE_NOT_VALIDATED,
    STATE_PASSED,
    STATE_WARNINGS,
    build_portfolio_status,
    report_state,
    worst_state,
)
from tests._pg import transactional_session

T0 = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)


# ── Pure mapping ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("status", "total_rules", "expected"),
    [
        ("errors", 12, STATE_ERRORS),
        ("failed", 12, STATE_ERRORS),
        ("warnings", 12, STATE_WARNINGS),
        ("info", 12, STATE_INFO),
        ("passed", 12, STATE_PASSED),
        # Zero checks passed is not a pass.
        ("passed", 0, STATE_NOT_VALIDATED),
        ("passed", None, STATE_NOT_VALIDATED),
        ("pending", 0, STATE_NOT_VALIDATED),
        ("skipped", 0, STATE_NOT_VALIDATED),
        ("unsupported", 0, STATE_NOT_VALIDATED),
        ("something-new", 5, STATE_NOT_VALIDATED),
        (None, None, STATE_NOT_VALIDATED),
    ],
)
def test_report_state_never_invents_a_pass(status: str | None, total_rules: int | None, expected: str) -> None:
    assert report_state(status, total_rules) == expected


def test_worst_state_ranks_unvalidated_above_passed_and_below_warnings() -> None:
    assert worst_state([STATE_PASSED, STATE_NOT_VALIDATED]) == STATE_NOT_VALIDATED
    assert worst_state([STATE_NOT_VALIDATED, STATE_WARNINGS, STATE_PASSED]) == STATE_WARNINGS
    assert worst_state([STATE_INFO, STATE_PASSED]) == STATE_INFO
    assert worst_state([STATE_PASSED, STATE_ERRORS, STATE_WARNINGS]) == STATE_ERRORS
    assert worst_state([]) == STATE_NOT_VALIDATED


# ── Seeding helpers ───────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        yield s


async def _user(session, *, role: str = "editor"):
    from app.modules.users.models import User

    u = User(
        id=uuid.uuid4(),
        email=f"vps-{uuid.uuid4().hex[:10]}@test.io",
        hashed_password="x",
        full_name="Portfolio Tester",
        role=role,
    )
    session.add(u)
    await session.flush()
    return u


async def _project(session, owner, name: str, *, status: str = "active"):
    from app.modules.projects.models import Project

    p = Project(id=uuid.uuid4(), name=name, owner_id=owner.id, status=status, currency="EUR")
    session.add(p)
    await session.flush()
    return p


async def _boq(session, project, name: str, *, variation_request_id: uuid.UUID | None = None):
    from app.modules.boq.models import BOQ

    b = BOQ(
        id=uuid.uuid4(),
        project_id=project.id,
        name=name,
        status="draft",
        variation_request_id=variation_request_id,
    )
    session.add(b)
    await session.flush()
    return b


async def _report(
    session,
    boq,
    status: str,
    *,
    minutes: int = 0,
    errors: int = 0,
    warnings: int = 0,
    passed: int = 0,
    total: int | None = None,
    rule_set: str = "boq_quality",
    metadata: dict | None = None,
    project_id: uuid.UUID | None = None,
):
    from app.modules.validation.models import ValidationReport

    r = ValidationReport(
        id=uuid.uuid4(),
        project_id=project_id or boq.project_id,
        target_type="boq",
        target_id=str(boq.id),
        rule_set=rule_set,
        status=status,
        score="0.8",
        total_rules=total if total is not None else errors + warnings + passed,
        passed_count=passed,
        warning_count=warnings,
        error_count=errors,
        results=[],
        metadata_=metadata if metadata is not None else {},
        created_at=T0 + timedelta(minutes=minutes),
    )
    session.add(r)
    await session.flush()
    return r


async def _member(session, project, user) -> None:
    from app.modules.teams.models import Team, TeamMembership

    team = Team(id=uuid.uuid4(), project_id=project.id, name="Site team", metadata_={})
    session.add(team)
    await session.flush()
    session.add(TeamMembership(id=uuid.uuid4(), team_id=team.id, user_id=user.id, role="member"))
    await session.flush()


def _by_id(resp) -> dict[uuid.UUID, object]:
    return {p.project_id: p for p in resp.projects}


# ── Tenancy ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_lists_only_projects_the_caller_can_open(session) -> None:
    owner = await _user(session)
    member = await _user(session)
    stranger = await _user(session)

    own = await _project(session, owner, "Owned tower")
    shared = await _project(session, owner, "Shared depot")
    theirs = await _project(session, stranger, "Someone else's school")
    archived = await _project(session, owner, "Old archive", status="archived")
    await _member(session, shared, member)
    for p in (own, shared, theirs, archived):
        await _report(session, await _boq(session, p, f"{p.name} BOQ"), "errors", errors=3)

    seen_by_owner = set(_by_id(await build_portfolio_status(session, str(owner.id))))
    assert seen_by_owner == {own.id, shared.id}

    seen_by_member = set(_by_id(await build_portfolio_status(session, str(member.id))))
    assert seen_by_member == {shared.id}

    seen_by_stranger = set(_by_id(await build_portfolio_status(session, str(stranger.id))))
    assert seen_by_stranger == {theirs.id}


@pytest.mark.asyncio
async def test_admin_sees_every_live_project_but_no_archived_one(session) -> None:
    admin = await _user(session, role="admin")
    a = await _user(session)
    b = await _user(session)
    pa = await _project(session, a, "A")
    pb = await _project(session, b, "B")
    gone = await _project(session, a, "Gone", status="archived")

    seen = set(_by_id(await build_portfolio_status(session, str(admin.id))))
    assert {pa.id, pb.id} <= seen
    assert gone.id not in seen


@pytest.mark.asyncio
async def test_unknown_or_malformed_caller_gets_nothing(session) -> None:
    owner = await _user(session)
    await _project(session, owner, "Private")

    assert (await build_portfolio_status(session, str(uuid.uuid4()))).projects == []
    assert (await build_portfolio_status(session, "not-a-uuid")).projects == []


@pytest.mark.asyncio
async def test_a_report_filed_under_another_project_does_not_colour_this_estimate(session) -> None:
    owner = await _user(session)
    stranger = await _user(session)
    mine = await _project(session, owner, "Mine")
    other = await _project(session, stranger, "Other")
    boq = await _boq(session, mine, "Main bill")
    # A row that names my BOQ but belongs to another project must not count.
    await _report(session, boq, "errors", errors=9, project_id=other.id)

    resp = await build_portfolio_status(session, str(owner.id))
    (project,) = resp.projects
    assert project.state == STATE_NOT_VALIDATED
    assert project.estimates[0].report_id is None


# ── Latest report, never the history ──────────────────────────────────────


@pytest.mark.asyncio
async def test_the_newest_report_decides_in_both_directions(session) -> None:
    owner = await _user(session)
    p = await _project(session, owner, "Hospital")
    fixed = await _boq(session, p, "Fixed since")
    broke = await _boq(session, p, "Broke since")
    await _report(session, fixed, "errors", minutes=0, errors=10)
    newest_fixed = await _report(session, fixed, "passed", minutes=5, passed=20)
    await _report(session, broke, "passed", minutes=0, passed=20)
    newest_broke = await _report(session, broke, "errors", minutes=5, errors=1, passed=19)

    (project,) = (await build_portfolio_status(session, str(owner.id))).projects
    est = {e.boq_id: e for e in project.estimates}
    assert est[fixed.id].state == STATE_PASSED
    assert est[fixed.id].report_id == newest_fixed.id
    assert est[broke.id].state == STATE_ERRORS
    assert est[broke.id].report_id == newest_broke.id
    # Counts are the latest reports only: 1 error, not 1 + 10 from history.
    assert project.error_count == 1
    assert project.passed_count == 20 + 19
    assert project.state == STATE_ERRORS
    assert project.last_validated_at == T0 + timedelta(minutes=5)


# ── Not validated is never passed ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_project_with_no_report_reads_not_validated(session) -> None:
    owner = await _user(session)
    empty = await _project(session, owner, "No estimates yet")
    unrun = await _project(session, owner, "Estimate never validated")
    await _boq(session, unrun, "Draft bill")

    by_id = _by_id(await build_portfolio_status(session, str(owner.id)))
    assert by_id[empty.id].state == STATE_NOT_VALIDATED
    assert by_id[empty.id].estimate_count == 0
    assert by_id[unrun.id].state == STATE_NOT_VALIDATED
    assert by_id[unrun.id].estimate_count == 1
    assert by_id[unrun.id].not_validated_count == 1
    assert by_id[unrun.id].last_validated_at is None


@pytest.mark.asyncio
async def test_one_passed_estimate_does_not_make_a_half_validated_project_pass(session) -> None:
    owner = await _user(session)
    p = await _project(session, owner, "Half checked")
    good = await _boq(session, p, "Checked bill")
    await _boq(session, p, "Unchecked bill")
    await _report(session, good, "passed", passed=15)

    resp = await build_portfolio_status(session, str(owner.id))
    (project,) = resp.projects
    assert project.state == STATE_NOT_VALIDATED
    assert project.validated_count == 1
    assert project.not_validated_count == 1
    assert resp.summary.not_validated == 1
    assert resp.summary.passed == 0


@pytest.mark.asyncio
async def test_a_report_that_checked_nothing_is_not_a_pass(session) -> None:
    owner = await _user(session)
    p = await _project(session, owner, "Nothing ran")
    pending = await _boq(session, p, "Pending")
    empty_pass = await _boq(session, p, "Empty pass")
    unsupported = await _boq(session, p, "Unsupported")
    await _report(session, pending, "pending")
    await _report(session, empty_pass, "passed", total=0)
    await _report(
        session,
        unsupported,
        "unsupported",
        metadata={"rule_sets": ["xyz"], "unsupported_rule_sets": ["xyz"]},
    )

    (project,) = (await build_portfolio_status(session, str(owner.id))).projects
    assert project.state == STATE_NOT_VALIDATED
    assert {e.state for e in project.estimates} == {STATE_NOT_VALIDATED}
    est = {e.boq_name: e for e in project.estimates}
    # The raw status and report link survive, so the reader can see why.
    assert est["Unsupported"].report_status == "unsupported"
    assert est["Unsupported"].unsupported_rule_sets == ["xyz"]
    assert est["Empty pass"].report_id is not None


@pytest.mark.asyncio
async def test_a_variation_bill_is_not_part_of_the_project_register(session) -> None:
    owner = await _user(session)
    p = await _project(session, owner, "With a variation")
    main = await _boq(session, p, "Main bill")
    variation = await _boq(session, p, "VR-7 bill", variation_request_id=uuid.uuid4())
    await _report(session, main, "passed", passed=10)
    await _report(session, variation, "errors", errors=4)

    (project,) = (await build_portfolio_status(session, str(owner.id))).projects
    assert [e.boq_id for e in project.estimates] == [main.id]
    assert project.state == STATE_PASSED
    assert project.error_count == 0


# ── Worst first ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_projects_and_estimates_come_back_worst_first(session) -> None:
    owner = await _user(session)

    async def _one(name: str, status: str | None, **counts):
        p = await _project(session, owner, name)
        b = await _boq(session, p, f"{name} bill")
        if status is not None:
            await _report(session, b, status, **counts)
        return p

    # Names are chosen so alphabetical order would be wrong everywhere.
    passed = await _one("Alpha", "passed", passed=30)
    info = await _one("Bravo", "info", passed=29, total=30)
    unvalidated = await _one("Charlie", None)
    warnings = await _one("Delta", "warnings", warnings=2, passed=28)
    few_errors = await _one("Echo", "errors", errors=2, passed=28)
    many_errors = await _one("Foxtrot", "errors", errors=5, passed=25)
    # Same error count as Echo; more warnings breaks the tie.
    errors_and_warnings = await _one("Golf", "errors", errors=2, warnings=3, passed=25)

    resp = await build_portfolio_status(session, str(owner.id))
    assert [p.project_id for p in resp.projects] == [
        many_errors.id,
        errors_and_warnings.id,
        few_errors.id,
        warnings.id,
        unvalidated.id,
        info.id,
        passed.id,
    ]
    assert resp.summary.errors == 3
    assert resp.summary.warnings == 1
    assert resp.summary.not_validated == 1
    assert resp.summary.info == 1
    assert resp.summary.passed == 1
    assert resp.project_count == 7

    # Inside one project the estimates are ordered the same way.
    p = await _project(session, owner, "Mixed")
    b_pass = await _boq(session, p, "A passed")
    b_none = await _boq(session, p, "B unvalidated")
    b_err = await _boq(session, p, "C errors")
    await _report(session, b_pass, "passed", passed=4)
    await _report(session, b_err, "errors", errors=1)
    mixed = _by_id(await build_portfolio_status(session, str(owner.id)))[p.id]
    assert [e.boq_id for e in mixed.estimates] == [b_err.id, b_none.id, b_pass.id]
    assert mixed.state == STATE_ERRORS


# ── Rule sets ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rule_sets_come_from_metadata_or_the_label(session) -> None:
    owner = await _user(session)
    p = await _project(session, owner, "Rules")
    from_meta = await _boq(session, p, "Meta")
    from_label = await _boq(session, p, "Label")
    await _report(
        session,
        from_meta,
        "passed",
        passed=3,
        rule_set="ignored",
        metadata={"rule_sets": ["din276", "boq_quality"]},
    )
    await _report(session, from_label, "warnings", warnings=1, rule_set="gaeb+boq_quality")

    (project,) = (await build_portfolio_status(session, str(owner.id))).projects
    est = {e.boq_name: e for e in project.estimates}
    assert est["Meta"].rule_sets == ["din276", "boq_quality"]
    assert est["Label"].rule_sets == ["gaeb", "boq_quality"]
    assert sorted(project.rule_sets) == ["boq_quality", "din276", "gaeb"]


# ── No N+1 ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_statement_count_does_not_grow_with_projects(session) -> None:
    small = await _user(session)
    large = await _user(session)
    p = await _project(session, small, "Only one")
    await _report(session, await _boq(session, p, "Bill"), "passed", passed=2)
    for i in range(6):
        lp = await _project(session, large, f"Large {i}")
        for j in range(3):
            b = await _boq(session, lp, f"Bill {i}.{j}")
            await _report(session, b, "errors", errors=1, minutes=0)
            await _report(session, b, "warnings", warnings=1, minutes=1)

    counter = {"n": 0}

    def _count(*_args, **_kwargs) -> None:
        counter["n"] += 1

    bind = session.get_bind()
    event.listen(bind, "before_cursor_execute", _count)
    try:
        counter["n"] = 0
        await build_portfolio_status(session, str(small.id))
        one = counter["n"]
        counter["n"] = 0
        resp = await build_portfolio_status(session, str(large.id))
        many = counter["n"]
    finally:
        event.remove(bind, "before_cursor_execute", _count)

    # The listener must actually see the reads (project names, estimates,
    # latest reports at the least), or 0 == 0 would pass for anything.
    assert one >= 3, one
    assert len(resp.projects) == 6
    assert all(pr.estimate_count == 3 for pr in resp.projects)
    assert all(pr.state == STATE_WARNINGS for pr in resp.projects)
    assert many == one, f"{one} statements for 1 project but {many} for 6"
