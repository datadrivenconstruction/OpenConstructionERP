# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Commitment release end to end on PostgreSQL: request, tier route, verdict,
tranches, re-release on an amended document, counting rules, FX refusal,
four eyes, withdraw and the concurrent-request race.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.commitment_release.errors import CommitmentError
from app.modules.commitment_release.service import CommitmentService
from tests._pg import isolated_engine
from tests.pg.commitment_fixtures import (
    World,
    add_contract,
    add_po,
    build_world,
    decide,
    item,
    link,
    request,
    set_contract_value,
    state,
)

TODAY = date(2026, 10, 11)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def world():
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        yield await build_world(factory)


async def _view(w: World, item_id) -> dict:
    async with w.factory() as s:
        data = await CommitmentService(s).item_views(w.project_id, today=TODAY, item_ids=[item_id])
    return data["items"][0]


async def test_sponsor_tier_release_approves_and_item_is_released(world: World) -> None:
    iid = await item(world, amount="400000")
    d = await request(world, iid, "400000")
    assert d.outcome == "pending" and d.required_tier == "sponsor"
    assert await decide(world, d, world.sponsor) == "approved"
    row = await state(world, iid)
    assert row.status == "released"


async def test_rejection_keeps_item_requestable_and_counts_attempts(world: World) -> None:
    iid = await item(world, amount="40000")
    d1 = await request(world, iid, "40000")
    assert d1.required_tier == "project_manager"
    await decide(world, d1, world.pm, "rejected", comment="scope unclear")
    assert (await state(world, iid)).status == "planned"
    d2 = await request(world, iid, "40000")
    assert d2.attempt == d1.attempt + 1


async def test_second_tranche_is_evaluated_on_the_cumulative_amount(world: World) -> None:
    iid = await item(world, amount="90000")
    d1 = await request(world, iid, "40000")
    assert d1.required_tier == "project_manager"
    await decide(world, d1, world.pm)
    assert (await state(world, iid)).status == "partially_released"
    d2 = await request(world, iid, "40000")
    # 40,000 + 40,000 crosses the 50,000 project manager band.
    assert d2.required_tier == "sponsor"


async def test_amended_contract_above_tolerance_requires_re_release(world: World) -> None:
    iid = await item(world, amount="100000")
    d = await request(world, iid, "100000")
    await decide(world, d, world.sponsor)
    cid = await add_contract(world, "100000")
    await link(world, iid, "contract", cid)
    async with world.factory() as s:
        await CommitmentService(s).recompute_item(world.project_id, iid)
        await s.commit()
    assert (await state(world, iid)).status == "committed"
    # +1.5% stays inside the 2% tolerance, +5% does not.
    await set_contract_value(world, cid, "101500")
    async with world.factory() as s:
        await CommitmentService(s).recompute_item(world.project_id, iid)
        await s.commit()
    assert (await state(world, iid)).status == "committed"
    await set_contract_value(world, cid, "105000")
    async with world.factory() as s:
        await CommitmentService(s).recompute_item(world.project_id, iid)
        await s.commit()
    assert (await state(world, iid)).status == "re_release_required"


async def test_draft_po_does_not_count_but_an_issued_one_does(world: World) -> None:
    iid = await item(world, amount="30000", ctype="supplies")
    draft = await add_po(world, "10000", status="draft")
    issued = await add_po(world, "20000", status="issued")
    await link(world, iid, "purchase_order", draft)
    await link(world, iid, "purchase_order", issued)
    v = await _view(world, iid)
    assert Decimal(v["committed"]) == Decimal("20000")


async def test_document_counts_once_across_items(world: World) -> None:
    a = await item(world, code="A", amount="10000")
    b = await item(world, code="B", amount="10000")
    cid = await add_contract(world, "10000")
    await link(world, a, "contract", cid)
    with pytest.raises(CommitmentError) as exc:
        await link(world, b, "contract", cid)
    assert exc.value.code == "document_linked_elsewhere"


async def test_currency_without_a_dated_rate_refuses(world: World) -> None:
    iid = await item(world, amount="10000", currency="XTS")
    with pytest.raises(CommitmentError) as exc:
        await request(world, iid, "10000", currency="XTS")
    assert exc.value.code == "fx_rate_missing"


async def test_project_rate_converts_gbp_into_the_schedule_currency(world: World) -> None:
    # 45,000 GBP x 1.20 = 54,000 EUR: above the 50,000 project manager band.
    iid = await item(world, amount="45000", currency="GBP")
    d = await request(world, iid, "45000", currency="GBP")
    assert d.required_tier == "sponsor"


async def test_requester_who_holds_the_tier_cannot_approve_their_own_release(world: World) -> None:
    iid = await item(world, amount="10000")
    with pytest.raises(CommitmentError) as exc:
        await request(world, iid, "10000", actor=world.pm, manage=True)
    assert exc.value.code == "four_eyes_requester_is_approver"


async def test_withdraw_returns_the_item_and_cancels_the_instance(world: World) -> None:
    from app.modules.approval_routes.service import ApprovalRouteService

    iid = await item(world, amount="10000")
    d = await request(world, iid, "10000")
    async with world.factory() as s:
        out = await CommitmentService(s).withdraw_release(
            world.project_id, iid, actor_id=world.requester, reason="wrong item"
        )
        await s.commit()
    assert out.outcome == "withdrawn"
    assert (await state(world, iid)).status == "planned"
    async with world.factory() as s:
        inst = await ApprovalRouteService(s).get_instance(d.approval_instance_id)
    assert inst.status == "cancelled"


async def test_concurrent_requests_on_one_item_admit_exactly_one(world: World) -> None:
    iid = await item(world, amount="10000")
    results = await asyncio.gather(request(world, iid, "10000"), request(world, iid, "10000"), return_exceptions=True)
    ok = [r for r in results if not isinstance(r, BaseException)]
    errors = [r for r in results if isinstance(r, BaseException)]
    assert len(ok) == 1, results
    assert len(errors) == 1
    assert getattr(errors[0], "status_code", None) == 409, repr(errors[0])


async def test_changing_a_tier_holder_regenerates_the_route_and_routes_to_the_new_holder(world: World) -> None:
    from app.modules.approval_routes.models import Route
    from app.modules.commitment_release.models import CommitmentMatrix
    from tests.pg.governance_fixtures import add_user

    async with world.factory() as s:
        new_pm = await add_user(s, "manager")
        from sqlalchemy import select

        from app.modules.teams.models import Team, TeamMembership

        team = (await s.execute(select(Team).where(Team.project_id == world.project_id))).scalars().first()
        s.add(TeamMembership(team_id=team.id, user_id=new_pm))
        old_route = (
            (await s.execute(select(CommitmentMatrix).where(CommitmentMatrix.project_id == world.project_id)))
            .scalar_one()
            .tier_routes["project_manager"]
        )
        await CommitmentService(s).put_assignments(
            world.project_id,
            [
                {"project_role": "owner_pm", "user_id": new_pm},
                {"project_role": "owner_sponsor", "user_id": world.sponsor},
                {"project_role": "owner_board_member", "user_id": world.board},
            ],
            actor_id=world.manager,
            today=TODAY,
        )
        await s.commit()
    async with world.factory() as s:
        assert (await s.get(Route, uuid.UUID(old_route))).is_active is False
    iid = await item(world, amount="10000")
    d = await request(world, iid, "10000")
    assert await decide(world, d, new_pm) == "approved"
    assert (await state(world, iid)).status == "released"


async def test_a_deleted_tier_route_refuses_the_request_with_a_code(world: World) -> None:
    from sqlalchemy import select

    from app.modules.approval_routes.models import Route
    from app.modules.commitment_release.models import CommitmentMatrix

    async with world.factory() as s:
        matrix = (
            await s.execute(select(CommitmentMatrix).where(CommitmentMatrix.project_id == world.project_id))
        ).scalar_one()
        route = await s.get(Route, uuid.UUID(matrix.tier_routes["project_manager"]))
        route.is_active = False
        await s.commit()
    iid = await item(world, amount="10000")
    with pytest.raises(CommitmentError) as exc:
        await request(world, iid, "10000")
    assert exc.value.code == "no_route_for_tier"


async def _contingency_line(w: World, amount: str) -> uuid.UUID:
    from app.modules.finance.models import ProjectBudget

    async with w.factory() as s:
        line = ProjectBudget(
            project_id=w.project_id,
            category="contingency",
            currency_code="EUR",
            original_budget=Decimal(amount),
            revised_budget=Decimal(amount),
            metadata_={},
        )
        s.add(line)
        await s.commit()
        return line.id


async def _drawdowns(w: World, line_id: uuid.UUID) -> dict:
    from app.modules.finance.models import ProjectBudget

    async with w.factory() as s:
        meta = (await s.get(ProjectBudget, line_id)).metadata_ or {}
    return {k: v for k, v in meta.items() if k.startswith("contingency_drawdown:")}


async def test_an_approved_drawdown_is_written_to_the_contingency_line_once(world: World) -> None:
    line = await _contingency_line(world, "100000")
    iid = await item(world, code="CD-1", amount="60000", ctype="contingency_drawdown")
    d1 = await request(world, iid, "30000")
    await decide(world, d1, world.pm)
    assert {k: v["amount"] for k, v in (await _drawdowns(world, line)).items()} == {
        f"contingency_drawdown:commitment:{iid}": "30000.00"
    }
    # The second tranche replaces the record with the cumulative amount, never adds a second one.
    d2 = await request(world, iid, "20000")
    await decide(world, d2, world.pm)  # cumulative 50,000 is still the project manager tier
    assert {k: v["amount"] for k, v in (await _drawdowns(world, line)).items()} == {
        f"contingency_drawdown:commitment:{iid}": "50000.00"
    }


async def test_a_drawdown_above_the_lines_balance_is_refused(world: World) -> None:
    await _contingency_line(world, "100000")
    first = await item(world, code="CD-1", amount="70000", ctype="contingency_drawdown")
    d = await request(world, first, "70000")
    await decide(world, d, world.sponsor)
    second = await item(world, code="CD-2", amount="40000", ctype="contingency_drawdown")
    with pytest.raises(CommitmentError) as exc:
        await request(world, second, "40000")
    assert exc.value.code == "contingency_insufficient"


async def test_a_drawdown_taken_while_the_request_waited_turns_the_approval_into_a_rejection(world: World) -> None:
    line = await _contingency_line(world, "100000")
    a = await item(world, code="CD-A", amount="60000", ctype="contingency_drawdown")
    b = await item(world, code="CD-B", amount="60000", ctype="contingency_drawdown")
    da = await request(world, a, "60000")
    db = await request(world, b, "60000")
    await decide(world, da, world.sponsor)
    await decide(world, db, world.sponsor)
    async with world.factory() as s:
        from app.modules.commitment_release.models import ReleaseDecision

        late = await s.get(ReleaseDecision, db.id)
    assert (late.outcome, late.rationale) == ("rejected", "contingency_insufficient")
    assert list(await _drawdowns(world, line)) == [f"contingency_drawdown:commitment:{a}"]


async def test_an_item_on_a_gate_names_its_management_area(world: World) -> None:
    with pytest.raises(CommitmentError) as exc:
        await item(world, code="G-1", amount="1000", gate_code="strategy_to_brief")
    assert exc.value.code == "governance_area_required"


async def test_a_drawdown_line_in_a_currency_without_a_rate_is_refused_with_a_code(world: World) -> None:
    """Review finding 11: the missing rate is a coded refusal at request time, never an unhandled error."""
    from app.modules.finance.models import ProjectBudget

    async with world.factory() as s:
        s.add(
            ProjectBudget(
                project_id=world.project_id,
                category="contingency",
                currency_code="XTS",
                original_budget=Decimal("100000"),
                revised_budget=Decimal("100000"),
                metadata_={},
            )
        )
        await s.commit()
    iid = await item(world, code="CD-X", amount="10000", ctype="contingency_drawdown")
    with pytest.raises(CommitmentError) as exc:
        await request(world, iid, "10000")
    assert (exc.value.code, exc.value.status_code) == ("fx_rate_missing", 422)
    assert (await state(world, iid)).status == "planned"


async def test_a_drawdown_whose_line_vanished_while_waiting_is_rejected_not_stranded(world: World) -> None:
    """Review finding 11: an approval that cannot write its drawdown closes the request with the code."""
    from app.modules.commitment_release.models import ReleaseDecision
    from app.modules.finance.models import ProjectBudget

    line = await _contingency_line(world, "100000")
    iid = await item(world, code="CD-V", amount="10000", ctype="contingency_drawdown")
    d = await request(world, iid, "10000")
    async with world.factory() as s:
        row = await s.get(ProjectBudget, line)
        row.category = "works"
        await s.commit()
    await decide(world, d, world.pm)
    async with world.factory() as s:
        late = await s.get(ReleaseDecision, d.id)
    assert (late.outcome, late.rationale) == ("rejected", "contingency_line_required")
    assert (await state(world, iid)).status == "planned"
