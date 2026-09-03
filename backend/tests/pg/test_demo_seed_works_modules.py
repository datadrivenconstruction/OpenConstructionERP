# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""The temporary-works, forms and portfolio demo seeds must fill, once, coherently.

All three shipped routed, permissioned and empty, and the seeders that fix that
share the same ways of being wrong - none of which shows up as a non-zero exit
code:

* they write nothing at all, because the demo marker that keeps a customer's
  live project safe also excludes the fixture the test runs against, and a
  suite asserting "at least three rows" passes on a seeder gated down to none;
* they double the register on the second boot, because idempotency in this
  codebase is per loop rather than per seeder;
* they write rows that are individually valid and collectively nonsense. On a
  safety register that is temporary works bearing load with no permit in force.
  On a form it is worse, because a submission whose answers do not match its
  template is invisible in the list and wrong the moment somebody opens it.

Every coherence assertion runs through the module's own judge -
``register.build_report``, ``validate_submission_answers``,
``build_visible_tree``, ``compute_node_cpm`` - rather than restating the rule
here. A rule restated in a test passes on data the application would reject.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select

from app.modules.contacts.models import Contact
from app.modules.forms.models import FormSubmission
from app.modules.forms.service import seed_starter_templates_if_empty
from app.modules.forms.submissions_seed import seed_forms_submissions_demo
from app.modules.forms.validation import validate_submission_answers
from app.modules.portfolio.models import PortfolioCrossLink, PortfolioMembership, PortfolioNode
from app.modules.portfolio.seed import seed_portfolio_demo
from app.modules.portfolio.service import PortfolioService
from app.modules.portfolio.tree_logic import build_visible_tree
from app.modules.projects.models import Project
from app.modules.schedule.models import Activity, Schedule
from app.modules.temporary_works import register
from app.modules.temporary_works.models import TemporaryWorksItem, TemporaryWorksPermit
from app.modules.temporary_works.seed import seed_temporary_works_demo
from app.modules.temporary_works.service import TemporaryWorksService
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio

# The gate floor is three rows. The target is a register somebody keeps, so the
# assertions are written against the target: a seeder quietly reduced to a
# handful of rows must fail here rather than squeak past a floor.
_MIN_ITEMS_PER_PROJECT = 8
_MIN_SUBMISSIONS_PER_PROJECT = 8

# The four pre-pour checks on the starter pour-acceptance template. A pour
# approved while any of these failed is the incoherent row the seeder must never
# produce.
_PRE_POUR_CHECKS = ("formwork", "reinforcement", "cast_in", "access")


async def _make_user(session, *, email: str, role: str, full_name: str) -> uuid.UUID:
    user_id = uuid.uuid4()
    session.add(
        User(
            id=user_id,
            email=email,
            hashed_password="x",
            full_name=full_name,
            role=role,
            locale="en",
            is_active=True,
            metadata_={},
        )
    )
    await session.flush()
    return user_id


async def _make_contacts(session) -> None:
    """The directory these seeders read their firms and people out of.

    Nothing in the seeded registers may name a party invented inside the seeder,
    so the fixture has to supply the parties or the coherence rules it is meant
    to enforce (an independent check is by a *different* firm) would be vacuous.
    """
    rows = [
        ("consultant", "Halveston Structures", "Ingrid", "Solvang"),
        ("consultant", "Brindlemoor Engineering", "Tomas", "Ekwall"),
        ("contractor", "Tarnholme Construction", "Nadia", "Perrault"),
        ("subcontractor", "Ravensholt Groundworks", "Owen", "Achebe"),
        ("supplier", "Cintramar Formwork", "Lise", "Bergquist"),
    ]
    for contact_type, company, first, last in rows:
        session.add(
            Contact(
                id=uuid.uuid4(),
                contact_type=contact_type,
                company_name=company,
                first_name=first,
                last_name=last,
                primary_email=f"{first.lower()}@example.test",
                is_active=True,
                metadata_={},
            )
        )
    await session.flush()


async def _make_project(
    session,
    owner_id: uuid.UUID,
    *,
    name: str,
    demo_id: str = "fixture",
    country_code: str = "DE",
    is_demo: bool = True,
) -> uuid.UUID:
    project_id = uuid.uuid4()
    session.add(
        Project(
            id=project_id,
            name=name,
            description="Works-modules seed fixture",
            currency="EUR",
            country_code=country_code,
            status="active",
            owner_id=owner_id,
            metadata_={"is_demo": True, "demo_id": demo_id} if is_demo else {},
        )
    )
    await session.flush()
    return project_id


async def _make_schedule(session, project_id: uuid.UUID, *, name: str, activities: int = 6) -> uuid.UUID:
    """A schedule with real, non-zero-duration leaf activities to link across."""
    schedule_id = uuid.uuid4()
    start = date.today()
    session.add(
        Schedule(
            id=schedule_id,
            project_id=project_id,
            name=name,
            schedule_type="baseline",
            description="",
            start_date=start.isoformat(),
            end_date=(start + timedelta(days=activities * 10)).isoformat(),
            status="active",
            metadata_={},
        )
    )
    await session.flush()
    for index in range(activities):
        act_start = start + timedelta(days=index * 10)
        session.add(
            Activity(
                id=uuid.uuid4(),
                schedule_id=schedule_id,
                name=f"{name} activity {index + 1}",
                description="",
                wbs_code=f"{index + 1:02d}",
                start_date=act_start.isoformat(),
                end_date=(act_start + timedelta(days=8)).isoformat(),
                duration_days=8,
                progress_pct="0",
                status="planned",
                dependencies=[],
                resources=[],
                boq_position_ids=[],
                metadata_={},
            )
        )
    await session.flush()
    return schedule_id


async def _count(session, model, project_id: uuid.UUID) -> int:
    return (
        await session.execute(select(func.count()).select_from(model).where(model.project_id == project_id))
    ).scalar_one()


# ── Temporary works ───────────────────────────────────────────────────────────


async def _tw_fixture(session, count: int = 4) -> list[uuid.UUID]:
    owner_id = await _make_user(session, email="tw-owner@example.test", role="manager", full_name="Site Manager")
    await _make_user(session, email="tw-admin@example.test", role="admin", full_name="Delivery Director")
    await _make_contacts(session)
    return [
        await _make_project(session, owner_id, name=f"TW project {index}", demo_id="residential-fixture")
        for index in range(count)
    ]


async def _register_items(session, project_id: uuid.UUID) -> list[TemporaryWorksItem]:
    return list(
        (
            await session.execute(
                select(TemporaryWorksItem)
                .where(TemporaryWorksItem.project_id == project_id)
                .order_by(TemporaryWorksItem.sort_order)
            )
        )
        .scalars()
        .all()
    )


async def test_the_temporary_works_register_is_populated_and_spans_the_lifecycle(pg_session) -> None:
    """Each demo project shows a register, not a handful of rows in one state."""
    projects = await _tw_fixture(pg_session)

    counts = await seed_temporary_works_demo(pg_session, projects)
    await pg_session.flush()

    assert counts["projects"] == len(projects)
    assert counts["permits"] > 0, "a register with no permits authorises nothing"

    for project_id in projects:
        items = await _register_items(pg_session, project_id)
        assert len(items) >= _MIN_ITEMS_PER_PROJECT, f"only {len(items)} item(s) on {project_id}"
        statuses = {item.status for item in items}
        assert len(statuses) >= 6, f"register sits in only {sorted(statuses)}"
        # Every row has to be readable as engineering, not as filler: a type, a
        # check category, a design case and a place on site.
        for item in items:
            assert item.tw_type in register.ALL_TW_TYPES
            assert item.status in register.ALL_ITEM_STATUSES
            assert item.design_check_category in register.ALL_DESIGN_CHECK_CATEGORIES
            assert item.description and "Design case:" in item.description
            assert item.location


async def test_the_register_puts_two_items_under_time_pressure(pg_session) -> None:
    """The overdue lists are what a coordinator opens the screen for.

    A register where nothing is ever late renders both overdue panels empty, so
    the seed deliberately runs one item past its load date and one past its
    strike date - and the assertion goes through the register core rather than
    re-deriving "overdue" here.
    """
    projects = await _tw_fixture(pg_session, count=2)
    await seed_temporary_works_demo(pg_session, projects)
    await pg_session.flush()

    service = TemporaryWorksService(pg_session)
    for project_id in projects:
        report = await service.build_register(project_id)
        assert report["overdue_to_load"], f"nothing overdue to load on {project_id}"
        assert report["overdue_to_strike"], f"nothing overdue to strike on {project_id}"
        # Design clearance has to be a real fraction, not 0 or 100 percent.
        pct = report["design_clearance_pct"]
        assert pct is not None and 0 < float(pct) < 100, f"design clearance reads {pct}"


async def test_only_the_third_project_carries_a_lapsed_permit(pg_session) -> None:
    """Nothing bears load without a permit in force, bar the one deliberate case.

    A compliance breach is the register's red flag, so the estate has exactly
    one: on a project that is not the one a user lands on, an item still in use
    whose permit to load has run out. Everything else has to come back clean,
    and the check runs through ``compliance_breaches`` rather than restating what
    a valid permit is.
    """
    projects = await _tw_fixture(pg_session)
    await seed_temporary_works_demo(pg_session, projects)
    await pg_session.flush()

    service = TemporaryWorksService(pg_session)
    breaches = {}
    for index, project_id in enumerate(projects):
        status = await service.get_load_status(project_id)
        breaches[index] = status["compliance_breaches"]

    assert breaches[2], "the deliberate lapsed permit produced no breach at all"
    assert len(breaches[2]) == 1, f"expected one breach, got {len(breaches[2])}"
    for index in (0, 1, 3):
        assert not breaches[index], f"project {index} reports {breaches[index]}"

    # And the lapsed one has to read as a renewal that is late, not as works
    # somebody walked away from: the strike date is still ahead.
    items = await _register_items(pg_session, projects[2])
    flagged = {b["reference"] for b in breaches[2]}
    breached = [i for i in items if i.reference in flagged]
    assert breached, "the breach names a reference that is not in the register"
    for item in breached:
        assert item.required_strike_date is not None
        assert item.required_strike_date > datetime.now(UTC).date()


async def test_a_category_two_or_three_check_is_by_a_different_firm(pg_session) -> None:
    """Independence is the definition of those categories, so the data has to show it."""
    projects = await _tw_fixture(pg_session, count=2)
    await seed_temporary_works_demo(pg_session, projects)
    await pg_session.flush()

    checked = 0
    for project_id in projects:
        for item in await _register_items(pg_session, project_id):
            assert item.designer_name, f"{item.reference} names no designer"
            assert item.twc_name, f"{item.reference} names no coordinator"
            if item.design_check_category in ("2", "3"):
                checked += 1
                assert item.checker_name, f"{item.reference} is category {item.design_check_category} with no checker"
                assert item.checker_name != item.designer_name, (
                    f"{item.reference} is category {item.design_check_category} but the designer checked their own work"
                )
    assert checked, "no category 2 or 3 item was seeded, so independence was never exercised"


async def test_a_second_temporary_works_pass_adds_nothing(pg_session) -> None:
    """Running the seed twice must not double the register."""
    projects = await _tw_fixture(pg_session, count=2)

    await seed_temporary_works_demo(pg_session, projects)
    await pg_session.flush()
    first = {pid: await _count(pg_session, TemporaryWorksItem, pid) for pid in projects}
    permits = {pid: await _count(pg_session, TemporaryWorksPermit, pid) for pid in projects}
    assert all(first.values())

    second = await seed_temporary_works_demo(pg_session, projects)
    await pg_session.flush()
    assert second["items"] == 0, f"the second pass wrote {second['items']} item(s) again"
    assert second["permits"] == 0
    for project_id in projects:
        assert await _count(pg_session, TemporaryWorksItem, project_id) == first[project_id]
        assert await _count(pg_session, TemporaryWorksPermit, project_id) == permits[project_id]


async def test_a_project_without_the_demo_marker_gets_no_safety_records(pg_session) -> None:
    """A customer's live project must never be handed invented permits."""
    owner_id = await _make_user(session=pg_session, email="live@example.test", role="manager", full_name="Owner")
    await _make_contacts(pg_session)
    live = await _make_project(pg_session, owner_id, name="Customer project", is_demo=False)

    counts = await seed_temporary_works_demo(pg_session, [live])
    await pg_session.flush()

    assert counts == {"projects": 0, "items": 0, "permits": 0}
    assert await _count(pg_session, TemporaryWorksItem, live) == 0


# ── Forms ─────────────────────────────────────────────────────────────────────


async def _forms_fixture(session, count: int = 3) -> list[uuid.UUID]:
    owner_id = await _make_user(session, email="forms-owner@example.test", role="manager", full_name="Site Manager")
    await _make_contacts(session)
    await seed_starter_templates_if_empty(session)
    return [
        await _make_project(session, owner_id, name=f"Forms project {index}", demo_id="residential-fixture")
        for index in range(count)
    ]


async def _submissions(session, project_id: uuid.UUID) -> list[FormSubmission]:
    return list(
        (
            await session.execute(
                select(FormSubmission)
                .where(FormSubmission.project_id == project_id)
                .order_by(FormSubmission.submission_number)
            )
        )
        .scalars()
        .all()
    )


async def test_the_submissions_list_is_populated_and_mixed(pg_session) -> None:
    """Each demo project's forms list reads as a site record, not an empty state."""
    projects = await _forms_fixture(pg_session)

    counts = await seed_forms_submissions_demo(pg_session, projects)
    await pg_session.flush()

    assert counts["projects"] == len(projects)
    assert counts["drafts"] > 0, "every submission completed reads as a list nobody is working on"

    for project_id in projects:
        rows = await _submissions(pg_session, project_id)
        assert len(rows) >= _MIN_SUBMISSIONS_PER_PROJECT, f"only {len(rows)} submission(s) on {project_id}"
        assert {r.status for r in rows} == {"draft", "completed"}
        assert len({r.template_category for r in rows}) >= 3, "the list draws on only one starter template"
        assert len({r.submission_number for r in rows}) == len(rows), "submission numbers collided"
        # A completed checklist has to carry the result it rolled up to, and the
        # estate has to show more than one outcome.
        completed = [r for r in rows if r.status == "completed"]
        results = {r.result for r in completed if r.result}
        assert "pass" in results and "fail" in results, f"only saw results {sorted(results)}"
        assert all(r.completed_at for r in completed), "a completed sheet with no completion date"


async def test_every_seeded_submission_matches_the_template_it_points_at(pg_session) -> None:
    """The failure that never shows up in a list: answers that do not fit the form.

    A completed submission has to satisfy the module's own validator outright. A
    draft cannot - it is unfinished by construction - so what is asserted there
    is that every problem it has is a *missing* answer and never a wrong one. A
    draft carrying an out-of-vocabulary choice or an unparseable number is
    invisible until somebody opens it and then cannot be completed at all.
    """
    projects = await _forms_fixture(pg_session, count=2)
    await seed_forms_submissions_demo(pg_session, projects)
    await pg_session.flush()

    seen_draft = seen_completed = 0
    for project_id in projects:
        for row in await _submissions(pg_session, project_id):
            snapshot = list(row.template_snapshot or [])
            answers: dict[str, Any] = dict(row.answers_data or {})
            assert snapshot, f"{row.submission_number} froze no template snapshot"
            check = validate_submission_answers(snapshot, answers)
            if row.status == "completed":
                seen_completed += 1
                assert check.is_complete, (
                    f"{row.submission_number} ({row.template_name}) is completed but fails its own "
                    f"template: {[i.as_dict() for i in check.issues]}"
                )
            else:
                seen_draft += 1
                codes = {issue.code for issue in check.issues}
                assert codes <= {"required_missing"}, (
                    f"{row.submission_number} is a draft with a wrong answer, not a missing one: {sorted(codes)}"
                )
    assert seen_completed and seen_draft, f"completed={seen_completed} draft={seen_draft}"


async def test_no_pour_is_approved_over_a_failed_pre_pour_check(pg_session) -> None:
    """A held pour has to be readable as held, on both lines and in the result."""
    projects = await _forms_fixture(pg_session, count=2)
    await seed_forms_submissions_demo(pg_session, projects)
    await pg_session.flush()

    held = released = 0
    for project_id in projects:
        for row in await _submissions(pg_session, project_id):
            if row.template_category != "quality" or row.status != "completed":
                continue
            answers = dict(row.answers_data or {})
            failed = [key for key in _PRE_POUR_CHECKS if str(answers.get(key, "")).lower() == "fail"]
            approved = str(answers.get("approved", "")).lower()
            if failed:
                held += 1
                assert approved == "fail", f"{row.submission_number} was approved over a failed {failed[0]} check"
                assert row.result == "fail", f"{row.submission_number} failed a check but rolled up to {row.result!r}"
            else:
                released += 1
                assert approved == "pass", f"{row.submission_number} was held with every pre-pour check passed"
    assert held, "no held pour was seeded, so the failing path was never exercised"
    assert released, "every pour was held, which is not a job anybody is running"


async def test_a_second_forms_pass_adds_no_submissions(pg_session) -> None:
    """Running the seed twice must not double the list."""
    projects = await _forms_fixture(pg_session, count=2)

    await seed_forms_submissions_demo(pg_session, projects)
    await pg_session.flush()
    first = {pid: await _count(pg_session, FormSubmission, pid) for pid in projects}
    assert all(first.values())

    second = await seed_forms_submissions_demo(pg_session, projects)
    await pg_session.flush()
    assert second["submissions"] == 0, f"the second pass wrote {second['submissions']} submission(s) again"
    for project_id in projects:
        assert await _count(pg_session, FormSubmission, project_id) == first[project_id]


async def test_a_project_without_the_demo_marker_gets_no_forms(pg_session) -> None:
    """A project somebody is really using is not filled with invented paperwork."""
    owner_id = await _make_user(session=pg_session, email="forms-live@example.test", role="manager", full_name="Owner")
    await _make_contacts(pg_session)
    await seed_starter_templates_if_empty(pg_session)
    live = await _make_project(pg_session, owner_id, name="Customer project", is_demo=False)

    counts = await seed_forms_submissions_demo(pg_session, [live])
    await pg_session.flush()

    assert counts["submissions"] == 0
    assert await _count(pg_session, FormSubmission, live) == 0


# ── Portfolio ─────────────────────────────────────────────────────────────────

# Shaped to reach every branch of the builder, because a fixture that misses one
# lets a whole sector be filed nowhere and still passes:
#
# * three residential projects in three regions, so that sector crosses the
#   split threshold and grows region subprogrammes under it - the deeper branch,
#   whose nodes only get their ids on a later flush;
# * two industrial projects, so a sector below the threshold is filed straight
#   onto its programme;
# * one social project, so a sector of one is too.
#
# The pairs inside a sector are also what make a cross-link land wholly under a
# single programme node, which is the only way running the CPM on anything but
# the root has an edge to apply.
_PORTFOLIO_FIXTURE = (
    ("Alpha Homes", "residential-alpha", "DE"),
    ("Bravo Homes", "residential-bravo", "BR"),
    ("Charlie Homes", "residential-charlie", "IN"),
    ("Delta Depot", "warehouse-delta", "AE"),
    ("Echo School", "school-echo", "FR"),
    ("Foxtrot Depot", "warehouse-foxtrot", "US"),
)


async def _portfolio_fixture(session) -> tuple[list[uuid.UUID], uuid.UUID]:
    owner_id = await _make_user(session, email="pf-owner@example.test", role="manager", full_name="Programme Manager")
    admin_id = await _make_user(session, email="pf-admin@example.test", role="admin", full_name="Delivery Director")
    projects: list[uuid.UUID] = []
    for name, demo_id, country in _PORTFOLIO_FIXTURE:
        project_id = await _make_project(session, owner_id, name=name, demo_id=demo_id, country_code=country)
        await _make_schedule(session, project_id, name=name)
        projects.append(project_id)
    return projects, admin_id


async def _nodes(session) -> list[PortfolioNode]:
    return list((await session.execute(select(PortfolioNode))).scalars().all())


async def test_every_demo_project_is_filed_under_exactly_one_node(pg_session) -> None:
    """The tree is the screen, so it has to build and reach every project."""
    projects, admin_id = await _portfolio_fixture(pg_session)

    counts = await seed_portfolio_demo(pg_session, projects)
    await pg_session.flush()

    assert counts["memberships"] == len(projects)
    nodes = await _nodes(pg_session)
    assert len(nodes) == counts["nodes"]
    types = {node.node_type for node in nodes}
    # All three node types, so the deeper branch of the builder is exercised: a
    # subprogramme's id only exists after a later flush than its programme's.
    assert types == {"portfolio", "programme", "subprogramme"}, f"tree has only {sorted(types)}"
    assert sum(1 for node in nodes if node.parent_id is None) == 1, "more than one root"
    assert all(node.owner_id is not None for node in nodes), "a node with no owner cannot be managed from the UI"

    memberships = list((await pg_session.execute(select(PortfolioMembership))).scalars().all())
    filed = [m.project_id for m in memberships]
    assert sorted(map(str, filed)) == sorted(map(str, projects))
    assert len(set(filed)) == len(filed), "a project was filed under more than one node"

    # Built through the module's own pruner, admin view, so a node that cannot
    # be rendered fails here rather than on screen.
    tree = build_visible_tree(
        [
            {
                "id": str(n.id),
                "parent_id": str(n.parent_id) if n.parent_id else None,
                "node_type": n.node_type,
                "name": n.name,
                "code": n.code,
                "sort_order": n.sort_order,
            }
            for n in nodes
        ],
        [{"node_id": str(m.node_id), "project_id": str(m.project_id)} for m in memberships],
        None,
    )
    assert len(tree) == 1, "the tree does not render as a single portfolio"

    def _project_ids(node: dict) -> list[str]:
        out = list(node["project_ids"])
        for child in node["children"]:
            out.extend(_project_ids(child))
        return out

    assert sorted(_project_ids(tree[0])) == sorted(map(str, projects))
    assert tree[0]["children"], "the root has no programmes under it"


async def test_the_portfolio_cpm_applies_cross_links_below_the_root(pg_session) -> None:
    """A programme node has to compute, not only the root.

    The CPM only honours a link when both of its ends are in the analysed
    subtree, so an estate whose every link spans two programmes shows a zero and
    an empty critical path on every node but the root - which photographs as
    broken. The check runs the module's own CPM rather than counting rows.
    """
    projects, admin_id = await _portfolio_fixture(pg_session)
    counts = await seed_portfolio_demo(pg_session, projects)
    await pg_session.flush()

    assert counts["cross_links"] >= 2, f"only {counts['cross_links']} cross-link(s) seeded"
    service = PortfolioService(pg_session)
    nodes = await _nodes(pg_session)
    root = next(node for node in nodes if node.parent_id is None)

    top = await service.compute_node_cpm(root.id, str(admin_id))
    assert top["schedule_count"] == len(projects)
    assert top["activity_count"] > 0
    assert top["cross_links_applied"] == counts["cross_links"]
    assert top["critical_path"], "the portfolio CPM returns no critical path"

    programmes = [node for node in nodes if node.node_type == "programme"]
    applied = [await service.compute_node_cpm(node.id, str(admin_id)) for node in programmes]
    assert any(result["cross_links_applied"] > 0 for result in applied), (
        "no programme node has a cross-link wholly inside it, so every node but the root computes an empty CPM"
    )


async def test_the_seeded_cross_links_are_directed_and_never_double_back(pg_session) -> None:
    """A cycle across schedules is a 409 on the screen, so the seed cannot make one."""
    projects, _admin_id = await _portfolio_fixture(pg_session)
    await seed_portfolio_demo(pg_session, projects)
    await pg_session.flush()

    links = list((await pg_session.execute(select(PortfolioCrossLink))).scalars().all())
    assert links, "no cross-links seeded"
    edges = {(str(link.predecessor_schedule_id), str(link.successor_schedule_id)) for link in links}
    assert all(left != right for left, right in edges), "a link points a schedule at itself"
    assert not any((right, left) in edges for left, right in edges), "two schedules point at each other"
    assert all(link.metadata_.get("reason") for link in links), "a cross-link with no reason is an unexplained arrow"


async def test_a_second_portfolio_pass_adds_no_nodes(pg_session) -> None:
    """The tree is one global structure, so a re-run must be a complete no-op."""
    projects, _admin_id = await _portfolio_fixture(pg_session)

    first = await seed_portfolio_demo(pg_session, projects)
    await pg_session.flush()
    before = len(await _nodes(pg_session))
    assert before == first["nodes"] > 0

    second = await seed_portfolio_demo(pg_session, projects)
    await pg_session.flush()
    assert second == {"nodes": 0, "memberships": 0, "cross_links": 0}
    assert len(await _nodes(pg_session)) == before
    assert (await pg_session.execute(select(func.count()).select_from(PortfolioMembership))).scalar_one() == first[
        "memberships"
    ]


async def test_a_project_without_the_demo_marker_is_not_filed(pg_session) -> None:
    """A customer's project is never swept into a portfolio it did not ask for."""
    owner_id = await _make_user(session=pg_session, email="pf-live@example.test", role="manager", full_name="Owner")
    live = await _make_project(pg_session, owner_id, name="Customer project", is_demo=False)

    counts = await seed_portfolio_demo(pg_session, [live])
    await pg_session.flush()

    assert counts == {"nodes": 0, "memberships": 0, "cross_links": 0}
    assert not await _nodes(pg_session)
