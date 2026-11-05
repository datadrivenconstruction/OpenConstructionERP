# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Capital plan service against a real database.

What the pure tests cannot show: a clone is a separate set of rows, a plan has one
baseline, a plan under a node sees only that node's projects, and a suggestion writes
nothing until the user applies it.
"""

from __future__ import annotations

import io
import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select

from app.modules.capital_plan.models import CapitalPlanItem
from app.modules.capital_plan.schemas import (
    ApplyStatuses,
    EnvelopesReplace,
    ItemCreate,
    ItemPatch,
    PlanCreate,
    PlanPatch,
    ScenarioCreate,
    ScenarioPatch,
)
from app.modules.capital_plan.seed import seed_capital_plan_demo
from app.modules.capital_plan.service import CapitalPlanService
from app.modules.portfolio.models import PortfolioMembership, PortfolioNode
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        yield s


async def _user(session) -> str:
    user = User(email=f"capplan-{uuid.uuid4().hex[:8]}@example.test", hashed_password="x")
    session.add(user)
    await session.flush()
    return str(user.id)


async def _plan(session, user: str, **kw):
    service = CapitalPlanService(session)
    plan = await service.create_plan(
        PlanCreate(name="Plan", currency="eur", start_year=2030, horizon_years=3, **kw), user
    )
    (baseline,), _ = await service.list_scenarios(plan.id)
    return service, plan, baseline


async def _item(service, scenario, title="Road", **kw):
    data = {"title": title, "start_year": 2030, "total_cost": Decimal("100"), **kw}
    return await service.create_item(scenario.id, ItemCreate(**data))


async def test_a_new_plan_has_one_baseline_and_an_upper_case_currency(session) -> None:
    _, plan, baseline = await _plan(session, await _user(session))
    assert plan.currency == "EUR"
    assert baseline.is_baseline and baseline.name == "Baseline"


async def test_only_one_scenario_can_be_the_baseline(session) -> None:
    service, plan, baseline = await _plan(session, await _user(session))
    with pytest.raises(HTTPException) as err:
        await service.create_scenario(plan.id, ScenarioCreate(name="Second", is_baseline=True))
    assert err.value.status_code == 409
    other = await service.create_scenario(plan.id, ScenarioCreate(name="What if"))
    with pytest.raises(HTTPException):
        await service.patch_scenario(plan.id, other.id, ScenarioPatch(is_baseline=True))
    with pytest.raises(HTTPException):
        await service.delete_scenario(plan.id, baseline.id)


async def test_editing_a_clone_leaves_the_baseline_alone(session) -> None:
    service, plan, baseline = await _plan(session, await _user(session))
    road = await _item(service, baseline)
    clone = await service.clone_scenario(plan.id, baseline.id, "Delay roads 1y")
    assert not clone.is_baseline
    (copy,), _ = await service.list_items(clone.id)
    assert copy.id != road.id and copy.title == "Road"

    await service.patch_item(copy.id, ItemPatch(start_year=2031, status="deferred"))
    await service.delete_item(copy.id)
    (still,), _ = await service.list_items(baseline.id)
    assert still.start_year == 2030 and still.status == "proposed"


async def test_envelopes_are_replaced_as_a_set(session) -> None:
    service, plan, _ = await _plan(session, await _user(session))
    body = EnvelopesReplace.model_validate(
        {
            "envelopes": [
                {"year": 2030, "amount": "50", "label": "Bond"},
                {"year": 2030, "amount": "20", "label": "Grant"},
            ]
        }
    )
    assert len(await service.replace_envelopes(plan.id, body)) == 2
    again = EnvelopesReplace.model_validate({"envelopes": [{"year": 2031, "amount": "10"}]})
    assert [e.year for e in await service.replace_envelopes(plan.id, again)] == [2031]
    dup = EnvelopesReplace.model_validate({"envelopes": [{"year": 2030, "amount": "1"}] * 2})
    with pytest.raises(HTTPException):
        await service.replace_envelopes(plan.id, dup)


async def test_summary_reports_the_red_year_and_the_findings(session) -> None:
    service, plan, baseline = await _plan(session, await _user(session))
    await service.replace_envelopes(
        plan.id, EnvelopesReplace.model_validate({"envelopes": [{"year": 2030, "amount": "60"}]})
    )
    await _item(service, baseline)
    out = await service.summary(baseline.id)
    assert out["rows"][0]["gap"] == "-40.00"
    assert out["unfunded"]
    assert "cp.year_over_envelope" in {f["rule_id"] for f in out["findings"]}


async def test_a_suggestion_changes_nothing_until_it_is_applied(session) -> None:
    service, plan, baseline = await _plan(session, await _user(session))
    await service.replace_envelopes(
        plan.id, EnvelopesReplace.model_validate({"envelopes": [{"year": 2030, "amount": "150"}]})
    )
    first = await _item(service, baseline, "First", priority=1)
    second = await _item(service, baseline, "Second", priority=2)
    out = await service.autofund(baseline.id)
    by_id = {s["id"]: s for s in out["items"]}
    assert by_id[str(first.id)]["status"] == "funded"
    assert by_id[str(second.id)]["reason"] == "exceeds envelope in 2030"
    rows = (await session.execute(select(CapitalPlanItem.status))).scalars().all()
    assert set(rows) == {"proposed"}

    applied = await service.apply_statuses(
        baseline.id, ApplyStatuses.model_validate({"items": [{"id": str(first.id), "status": "funded"}]})
    )
    assert {i.title: i.status for i in applied} == {"First": "funded", "Second": "proposed"}


async def test_compare_two_scenarios_of_one_plan(session) -> None:
    service, plan, baseline = await _plan(session, await _user(session))
    await _item(service, baseline)
    clone = await service.clone_scenario(plan.id, baseline.id, None)
    (copy,), _ = await service.list_items(clone.id)
    await service.patch_item(copy.id, ItemPatch(start_year=2031))
    out = await service.compare(plan.id, baseline.id, clone.id)
    assert out["changed_items"][0]["start_year_b"] == 2031
    assert out["years"][0]["delta_demand"] == "-100.00"
    with pytest.raises(HTTPException):
        await service.compare(plan.id, baseline.id, uuid.uuid4())


async def test_changing_the_duration_resets_stale_phasing(session) -> None:
    service, _, baseline = await _plan(session, await _user(session))
    item = await _item(service, baseline, duration_years=2, phasing=[Decimal("0.4"), Decimal("0.6")])
    assert item.phasing_json == ["0.4", "0.6"]
    patched = await service.patch_item(item.id, ItemPatch(duration_years=3))
    assert patched.phasing_json == []


async def test_import_takes_only_the_projects_under_the_plans_node(session) -> None:
    user = await _user(session)
    inside = Project(
        name="Inside",
        owner_id=uuid.UUID(user),
        currency="EUR",
        budget_estimate="1200000",
        planned_start_date="2031-03-01",
        planned_end_date="2032-09-30",
    )
    outside = Project(name="Outside", owner_id=uuid.UUID(user), currency="EUR", budget_estimate="5")
    node = PortfolioNode(name="Roads", node_type="programme")
    other = PortfolioNode(name="Schools", node_type="programme")
    session.add_all([inside, outside, node, other])
    await session.flush()
    session.add_all(
        [
            PortfolioMembership(node_id=node.id, project_id=inside.id),
            PortfolioMembership(node_id=other.id, project_id=outside.id),
        ]
    )
    await session.flush()

    service, plan, baseline = await _plan(session, user, node_id=node.id)
    created, skipped = await service.import_projects(plan.id, baseline.id, user)
    assert [i.title for i in created] == ["Inside"] and skipped == 0
    item = created[0]
    assert (item.start_year, item.duration_years, item.total_cost) == (2031, 2, Decimal("1200000.00"))

    again, skipped = await service.import_projects(plan.id, baseline.id, user)
    assert again == [] and skipped == 1


async def test_plans_are_listed_per_node_including_descendants(session) -> None:
    user = await _user(session)
    parent = PortfolioNode(name="Parent", node_type="portfolio")
    session.add(parent)
    await session.flush()
    child = PortfolioNode(name="Child", node_type="programme", parent_id=parent.id)
    sibling = PortfolioNode(name="Sibling", node_type="portfolio")
    session.add_all([child, sibling])
    await session.flush()
    service = CapitalPlanService(session)
    for name, node in (("on child", child), ("on sibling", sibling), ("tenant wide", None)):
        await service.create_plan(
            PlanCreate(name=name, currency="EUR", start_year=2030, node_id=node.id if node else None), user
        )
    assert {p.name for p in (await service.list_plans(parent.id))[0]} == {"on child"}
    assert {p.name for p in (await service.list_plans(None))[0]} >= {"on child", "on sibling", "tenant wide"}
    with pytest.raises(HTTPException):
        await service.create_plan(PlanCreate(name="x", currency="EUR", start_year=2030, node_id=uuid.uuid4()), user)


async def test_patching_a_plan_updates_its_horizon(session) -> None:
    service, plan, _ = await _plan(session, await _user(session))
    patched = await service.patch_plan(plan.id, PlanPatch(horizon_years=7))
    assert patched.horizon_years == 7


async def test_the_workbook_has_the_years_as_columns(session) -> None:
    from openpyxl import load_workbook

    service, plan, baseline = await _plan(session, await _user(session))
    await service.replace_envelopes(
        plan.id, EnvelopesReplace.model_validate({"envelopes": [{"year": 2030, "amount": "60"}]})
    )
    await _item(service, baseline)
    ws = load_workbook(io.BytesIO(await service.export_xlsx(baseline.id, "en"))).active
    header = [c.value for c in ws[3]]
    assert header[4:] == [2030, 2031, 2032]
    labels = [row[0].value for row in ws.iter_rows(min_row=5)]
    assert "Envelope" in labels and "Gap" in labels


async def test_the_demo_has_one_plan_two_scenarios_and_exactly_one_red_year(session) -> None:
    totals = await seed_capital_plan_demo(session)
    assert totals == {"plans": 1, "scenarios": 2, "items": 16}
    assert await seed_capital_plan_demo(session) == {"plans": 0, "scenarios": 0, "items": 0}
    service = CapitalPlanService(session)
    (plan,), _ = await service.list_plans()
    (baseline, delayed), _ = await service.list_scenarios(plan.id)
    assert baseline.is_baseline and not delayed.is_baseline
    items, total = await service.list_items(baseline.id, limit=3)
    assert len(items) == 3
    assert total == 8
    red = [r for r in (await service.summary(baseline.id))["rows"] if Decimal(r["gap"]) < 0]
    assert len(red) == 1
    assert not [r for r in (await service.summary(delayed.id))["rows"] if Decimal(r["gap"]) < 0]
