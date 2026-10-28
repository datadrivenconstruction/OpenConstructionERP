# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The demo seed fills a demo project's economics from its own bill, and only that.

The figures are derived from the bill (every frame group rounded up to 100 000, the markups likewise
as the allowance), the sources add up to the frame to the cent, and a re-run adds nothing.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.economics.seed import seed_economics_demo
from tests._pg import isolated_engine
from tests.economics_stories import fake_demo_module_story, story_for
from tests.pg.economics_fixtures import build_world, call
from tests.pg.governance_fixtures import World

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _pack_story(monkeypatch: pytest.MonkeyPatch) -> None:
    """The eleven-areas pack is the active pack: its economics stories are what the seeder reads."""
    monkeypatch.setattr("app.modules.project_governance.public.demo_module_story", fake_demo_module_story)


async def _mark(w: World, demo_id: str) -> None:
    from app.modules.projects.models import Project

    async with w.factory() as s:
        await s.execute(update(Project).where(Project.id == w.project_id).values(metadata_={"demo_id": demo_id}))
        await s.commit()


async def _seed(w: World) -> dict:
    async with w.factory() as s:
        out = await seed_economics_demo(s, [w.project_id])
        await s.commit()
        return out


@pytest_asyncio.fixture
async def world():
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        yield await build_world(factory, governance=False)


async def test_a_project_without_the_demo_marker_is_left_alone(world: World) -> None:
    out = await _seed(world)
    assert out["projects"] == 0
    assert (await call(world, "cost_frame"))["lines"] == []


async def test_a_demo_project_gets_a_frame_a_case_and_covering_financing(world: World) -> None:
    await _mark(world, "residential-regensburg")
    out = await _seed(world)
    assert out["ok"] is True and out["projects"] == 1

    frame = await call(world, "cost_frame")
    # direct cost 1 760 000: two cost groups carry 1 750 000, the uncoded 10 000 sits under no line
    amounts = {row["code"]: Decimal(row["amount"]) for row in frame["lines"]}
    assert len(amounts) == 2
    assert sum(amounts.values()) >= Decimal("1750000")
    for row in frame["lines"]:
        assert Decimal(row["amount"]) % Decimal("100000") == 0
        assert Decimal(row["amount"]) >= Decimal(row["estimate"])
    assert Decimal(frame["totals"]["markup_allowance"]) % Decimal("100000") == 0
    assert Decimal(frame["totals"]["markup_allowance"]) >= Decimal(frame["totals"]["markups"])

    financing = await call(world, "financing")
    assert financing["coverage"]["covered"] is True
    assert Decimal(financing["coverage"]["shortfall"]) == 0
    assert Decimal(financing["coverage"]["surplus"]) == 0
    assert Decimal(financing["coverage"]["sources_total"]) == Decimal(frame["totals"]["frame"])
    assert len(financing["sources"]) == len(story_for("residential-regensburg")["sources"])
    for source in financing["sources"]:
        assert source["tranche_total"] == source["amount"]

    readiness = await call(world, "readiness")
    assert [f["code"] for f in readiness["errors"]] == []
    case = await call(world, "business_case")
    assert case["key_figures"]["npv"] is not None
    assert Decimal(case["key_figures"]["total_investment"]) == Decimal(frame["totals"]["frame"])


async def test_a_demo_project_the_pack_has_no_story_for_is_left_alone(world: World) -> None:
    await _mark(world, "some-other-demo")
    out = await _seed(world)
    assert out["projects"] == 0 and out["ok"] is True
    assert (await call(world, "cost_frame"))["lines"] == []


async def test_the_registers_of_the_story_are_filled_and_dated_from_the_install_day(world: World) -> None:
    await _mark(world, "residential-regensburg")
    out = await _seed(world)
    assert (out["securities"], out["insurances"], out["process"]) == (4, 4, 3)
    regs = await call(world, "registers")
    kinds = {s["kind"]: s for s in regs["securities"]}
    assert set(kinds) == {"bid", "advance_payment", "performance", "warranty"}
    assert kinds["performance"]["description"] == "Vertragserfüllungsbürgschaft des Tiefbauunternehmens (Los 1 und 2)"
    assert Decimal(kinds["performance"]["amount"]) % 1000 == 0 and Decimal(kinds["performance"]["amount"]) > 0
    assert kinds["performance"]["lapsed"] is False
    assert regs["tax"]["confirmed"] is True and regs["tax"]["confirmed_by_name"]
    assert [p["status"] for p in regs["process"]] == ["set_up", "set_up", "set_up"]
    assert regs["state"] == {
        "securities": True,
        "insurance": True,  # the fire insurance of the shell is requested but its period starts later
        "tax": True,
        "receivables_payables": True,
        "administration": True,
    }


async def test_a_second_run_adds_nothing(world: World) -> None:
    await _mark(world, "school-ludwigsburg")
    first = await _seed(world)
    again = await _seed(world)
    assert first["projects"] == 1
    assert again["projects"] == 0
    assert len((await call(world, "financing"))["sources"]) == len(story_for("school-ludwigsburg")["sources"])


async def test_a_demo_project_without_a_bill_is_skipped_with_a_reason() -> None:
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        w = await build_world(factory, governance=False, bill=False)
        await _mark(w, "residential-regensburg")
        out = await _seed(w)
    assert out["projects"] == 0
    assert out["skipped"] == [{"project_id": str(w.project_id), "reason": "no_bill"}]


async def test_the_demo_that_reached_its_decision_is_approved_and_the_other_waits_in_review(world: World) -> None:
    await _mark(world, "residential-regensburg")
    out = await _seed(world)
    assert (out["proposed"], out["approved"]) == (1, 1)
    view = await call(world, "plan_view", actor_id=world.manager, can_edit=True, can_manage=True)
    approval = view["approvals"][0]
    assert view["status"] == "approved"
    assert approval["approval_source"] == "hand"
    assert approval["approved_by"] != approval["proposed_by"]


async def test_a_demo_plan_that_has_not_reached_its_decision_stays_proposed() -> None:
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        w = await build_world(factory, governance=False)
        await _mark(w, "school-ludwigsburg")
        out = await _seed(w)
        view = await call(w, "plan_view", actor_id=w.manager, can_edit=True, can_manage=True)
    assert (out["proposed"], out["approved"]) == (1, 0)
    assert view["status"] == "proposed"
    assert view["editable"] is False


async def test_grant_sources_are_linked_to_real_funding_applications(world: World) -> None:
    await _mark(world, "school-ludwigsburg")
    await _seed(world)
    financing = await call(world, "financing")
    grants = [s for s in financing["sources"] if s["kind"] == "grant"]
    assert len(grants) == 2
    by_status = {g["award"]["status"]: g for g in grants}
    assert by_status["approved"]["award"]["basis"] == "approved"
    assert by_status["approved"]["award"]["amount"] == by_status["approved"]["amount"]
    assert by_status["submitted"]["award"]["basis"] == "requested"
    assert by_status["submitted"]["award"]["amount"] == by_status["submitted"]["amount"]


async def test_with_gates_the_decided_gate_approves_the_demo_plan_by_someone_else() -> None:
    from app.modules.economics.events import handle_frame_document
    from app.modules.project_governance.evaluator import ProposedCondition
    from tests.pg.economics_fixtures import COMMERCIAL_DOC, GATE
    from tests.pg.governance_fixtures import decide, documents, prepare_gate

    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        w = await build_world(factory)
        await _mark(w, "residential-regensburg")
        gate = await prepare_gate(w, GATE)
        # The demo is installed with the plan, so no plan exists yet when the decision is taken: the decider
        # goes at risk on the commercial area, with the plan as the condition, and the seed then finds a decided
        # gate. The quality concept of the gate is not part of this story and is taken at risk as well.
        conditions = tuple(
            ProposedCondition(area_code=area, document_type=None, text=text, owner_user_id=str(w.owner))
            for area, text in (
                ("m09_commercial", "Cost plan proposed and financed"),
                ("m10_quality", "Quality concept approved"),
            )
        )
        await decide(
            w,
            gate.id,
            "go_with_conditions",
            conditions=conditions,
            proceed_at_risk_areas=("m09_commercial", "m10_quality"),
            rationale="The commercial frame follows with the demo plan.",
        )
        doc = (await documents(w))[COMMERCIAL_DOC]
        await handle_frame_document(
            {"project_id": str(w.project_id), "document_id": str(doc.id), "status": "binding"},
            session_factory=w.factory,
        )
        out = await _seed(w)
        view = await call(w, "plan_view", actor_id=w.manager, can_edit=True, can_manage=True)
    assert out["ok"] is True
    approval = view["approvals"][0]
    assert (view["status"], approval["approval_source"]) == ("approved", "gate")
    assert approval["approved_by"] == str(w.decider)
    assert approval["proposed_by"] != approval["approved_by"]


@pytest.mark.parametrize(
    ("demo_id", "direct_low", "direct_high"),
    # The installed bill carries the direct cost only; the markups (and with them the gross of about 59.2 and
    # 40.8 million) are added to the bill by the demo enrichment, which this test does not run.
    [("residential-regensburg", 40_000_000, 41_500_000), ("school-ludwigsburg", 27_500_000, 28_600_000)],
)
async def test_the_real_demo_bills_give_the_expected_plan(pg_session, demo_id, direct_low, direct_high) -> None:
    """Install the shipped demo, seed its economics and read the totals back against the bill."""
    from app.core.demo_projects import install_demo_project
    from app.modules.economics.service import EconomicsService

    result = await install_demo_project(pg_session, demo_id)
    await pg_session.flush()
    pid = result["project_id"]
    pid = uuid.UUID(str(pid))
    out = await seed_economics_demo(pg_session, [pid])
    await pg_session.flush()
    assert out["ok"] is True and out["projects"] == 1, out
    service = EconomicsService(pg_session)
    frame = await service.cost_frame(pid)
    financing = await service.financing(pid)
    readiness = await service.readiness(pid)
    estimate = Decimal(frame["totals"]["estimate"])
    total = Decimal(frame["totals"]["frame"])
    print(
        f"\nDEMO {demo_id}: direct {frame['totals']['estimate_direct']} markups {frame['totals']['markups']} "
        f"estimate {estimate} frame {total} sources {financing['coverage']['sources_total']}"
    )
    assert direct_low <= Decimal(frame["totals"]["estimate_direct"]) <= direct_high
    assert estimate <= total <= estimate * Decimal("1.04")
    assert Decimal(financing["coverage"]["sources_total"]) == total
    assert readiness["errors"] == []
