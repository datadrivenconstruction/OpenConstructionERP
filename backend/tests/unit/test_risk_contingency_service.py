# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Risk register to finance contingency, through the services and a real database.

What a project manager relies on, each pinned with a case where the wrong
implementation gives a different number:

* closed and occurred risks drop out of EMV (and out of the summary exposure
  and the Monte Carlo draw);
* allocated contingency is the project's own Contingency budget lines, in
  either spelling, converted into the project currency;
* nothing is drawn until a person confirms; confirming the same drawdown twice
  stores one record and draws the money once; a second risk adds, the other
  line stays exactly as it was;
* a stale budget edit cannot drop or resurrect a confirmed drawdown, and a
  deleted risk does not make its drawn money disappear.

Runs on the transaction-isolated PostgreSQL session from ``tests._pg``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.modules.finance.schemas import BudgetCreate, BudgetUpdate
from app.modules.finance.service import CONTINGENCY_DRAWDOWN_PREFIX, FinanceService
from app.modules.risk.schemas import ContingencyDrawdownRequest, ContingencyPosition, RiskCreate, RiskUpdate
from app.modules.risk.service import RiskService
from tests._pg import transactional_session

D = Decimal
PROJECT_ID = uuid.uuid4()
OTHER_PROJECT_ID = uuid.uuid4()
OWNER_ID = uuid.uuid4()


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        from app.modules.projects.models import Project
        from app.modules.users.models import User

        s.add(User(id=OWNER_ID, email=f"c-{uuid.uuid4().hex[:6]}@test.io", hashed_password="x", full_name="C"))
        await s.flush()
        # 1 USD = 0.5 EUR in this project's own table, deliberately far from
        # any market rate so a naive sum and a conversion cannot coincide.
        s.add(
            Project(
                id=PROJECT_ID,
                name="Contingency",
                owner_id=OWNER_ID,
                currency="EUR",
                fx_rates=[{"code": "USD", "rate": "0.5"}],
            )
        )
        s.add(Project(id=OTHER_PROJECT_ID, name="Other", owner_id=OWNER_ID, currency="EUR"))
        await s.commit()
        yield s


async def _risk(svc: RiskService, *, project_id=PROJECT_ID, **kw) -> uuid.UUID:
    base = {"project_id": project_id, "title": "Risk", "probability": 0.5, "impact_cost": D("1000")}
    base.update(kw)
    item = await svc.create_risk(RiskCreate(**base))
    return item.id


async def _line(
    session, *, project_id=PROJECT_ID, amount="1000", category="contingency", wbs="CT-1", currency=""
) -> uuid.UUID:
    fin = FinanceService(session)
    b = await fin.create_budget(
        BudgetCreate(
            project_id=project_id,
            wbs_id=wbs,
            category=category,
            original_budget=amount,
            currency_code=currency,
        )
    )
    return b.id


def _req(amount: str, budget_id: uuid.UUID | None = None, note: str = "") -> ContingencyDrawdownRequest:
    return ContingencyDrawdownRequest(amount=D(amount), budget_id=budget_id, note=note)


async def _markers(session, budget_id: uuid.UUID) -> dict:
    fin = FinanceService(session)
    b = await fin.get_budget(budget_id)
    await session.refresh(b)
    return {k: v for k, v in (b.metadata_ or {}).items() if k.startswith(CONTINGENCY_DRAWDOWN_PREFIX)}


# ── EMV and the status rule ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_closed_and_occurred_risks_leave_emv_and_summary_exposure(session):
    svc = RiskService(session)
    await _risk(svc, probability=0.5, impact_cost=D("1000"))
    closed_id = await _risk(svc, probability=0.4, impact_cost=D("5000"))
    await svc.update_risk(closed_id, RiskUpdate(status="closed"))
    await _risk(svc, probability=0.9, impact_cost=D("3000"), status="occurred")

    pos = await svc.get_contingency_position(PROJECT_ID)
    # 0.5 x 1000 only. With the closed risk it would be 2500, with both 5200.
    assert pos["emv"] == D("500.00")
    assert pos["active_risk_count"] == 1
    assert pos["excluded_closed_count"] == 1
    assert len(pos["pending"]) == 1

    summary = await svc.get_summary(PROJECT_ID)
    assert summary["total_exposure"] == pytest.approx(500.0)
    # Every risk is still counted in the register totals.
    assert summary["total"] == 3

    ContingencyPosition(**pos)  # the dict fits the response model


@pytest.mark.asyncio
async def test_simulation_leaves_out_closed_risks(session):
    svc = RiskService(session)
    rid = await _risk(svc, probability=0.9, impact_cost=D("10000"))
    await svc.update_risk(rid, RiskUpdate(status="closed"))
    result = await svc.simulate(PROJECT_ID, iterations=1000, mode="cost")
    assert result["p80_cost"] == 0.0
    assert result["tornado"] == []


@pytest.mark.asyncio
async def test_usd_risk_is_converted_with_the_project_rate(session):
    svc = RiskService(session)
    await _risk(svc, probability=0.5, impact_cost=D("1000"))
    await _risk(svc, probability=0.5, impact_cost=D("1000"), currency="USD")
    await _risk(svc, probability=0.5, impact_cost=D("600"), currency="GBP")
    pos = await svc.get_contingency_position(PROJECT_ID)
    # EUR 500 + USD 500 x 0.5 = 750. Summing in own units would say 1000.
    assert pos["emv"] == D("750.00")
    assert pos["unconverted_emv"] == {"GBP": D("300.00")}
    assert pos["missing_fx_rates"] == ["GBP"]


# ── Allocated contingency from finance ────────────────────────────────────


@pytest.mark.asyncio
async def test_allocated_reads_only_this_projects_contingency_lines(session):
    svc = RiskService(session)
    await _line(session, amount="1000", category="contingency", wbs="A")
    await _line(session, amount="400", category="Contingency", wbs="B")  # manual form spelling
    await _line(session, amount="9000", category="material", wbs="C")
    await _line(session, amount="2000", category="contingency", wbs="D", currency="USD")
    await _line(session, project_id=OTHER_PROJECT_ID, amount="7777", category="contingency", wbs="A")
    pos = await svc.get_contingency_position(PROJECT_ID)
    # 1000 + 400 + 2000 x 0.5 = 2400 EUR.
    assert pos["allocated"] == D("2400.00")
    assert len(pos["lines"]) == 3
    assert pos["state"] == "covered"


@pytest.mark.asyncio
async def test_no_line_means_no_allocation(session):
    svc = RiskService(session)
    await _risk(svc)
    pos = await svc.get_contingency_position(PROJECT_ID)
    assert pos["state"] == "no_allocation"
    assert pos["allocated"] == D("0.00")


# ── Drawdown confirmation ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_nothing_is_drawn_until_a_person_confirms(session):
    svc = RiskService(session)
    line = await _line(session, amount="10000")
    await _risk(svc, impact_cost=D("2500"), status="occurred")
    pos = await svc.get_contingency_position(PROJECT_ID)
    assert pos["drawn"] == D("0.00")
    assert pos["pending"][0]["proposed_amount"] == D("2500.00")
    assert pos["pending"][0]["proposed_budget_id"] == str(line)
    assert await _markers(session, line) == {}


@pytest.mark.asyncio
async def test_confirm_twice_draws_once_and_keeps_the_original_record(session):
    svc = RiskService(session)
    line = await _line(session, amount="10000")
    rid = await _risk(svc, impact_cost=D("2500"), status="occurred", title="Crane collapse")

    first = await svc.confirm_contingency_drawdown(PROJECT_ID, rid, _req("2400"), user_id="u-1")
    stored_first = await _markers(session, line)
    second = await svc.confirm_contingency_drawdown(PROJECT_ID, rid, _req("2400"), user_id="u-2")
    stored_second = await _markers(session, line)

    assert first["drawn"] == second["drawn"] == D("2400.00")
    assert second["remaining"] == D("7600.00")
    assert len(stored_second) == 1
    # The replay did not re-stamp who confirmed it or when.
    assert stored_second == stored_first
    record = next(iter(stored_second.values()))
    assert record["confirmed_by"] == "u-1"
    assert record["risk_title"] == "Crane collapse"
    assert record["currency"] == "EUR"
    # Drawn risks leave pending and EMV.
    assert second["pending"] == []
    assert second["excluded_drawn_count"] == 1


@pytest.mark.asyncio
async def test_reconfirm_replaces_second_risk_adds_and_other_line_is_untouched(session):
    svc = RiskService(session)
    fin = FinanceService(session)
    line_a = await _line(session, amount="10000", wbs="A")
    line_b = await _line(session, amount="3000", wbs="B")
    before_b = await fin.get_budget(line_b)
    snapshot_b = (
        before_b.original_budget,
        before_b.revised_budget,
        before_b.committed,
        before_b.actual,
        dict(before_b.metadata_ or {}),
    )
    r1 = await _risk(svc, status="occurred", title="One")
    r2 = await _risk(svc, status="occurred", title="Two")

    await svc.confirm_contingency_drawdown(PROJECT_ID, r1, _req("1000", line_a))
    await svc.confirm_contingency_drawdown(PROJECT_ID, r1, _req("1500", line_a))  # replaces, not adds
    pos = await svc.confirm_contingency_drawdown(PROJECT_ID, r2, _req("700", line_a))

    # 1500 + 700. Adding the first confirmation as well would give 3200.
    assert pos["drawn"] == D("2200.00")
    by_id = {ln["budget_id"]: ln for ln in pos["lines"]}
    assert by_id[str(line_a)]["drawn"] == D("2200.00")
    assert by_id[str(line_b)]["drawn"] == D("0.00")
    assert sum(ln["drawn"] for ln in pos["lines"]) == pos["drawn"]
    after_b = await fin.get_budget(line_b)
    await session.refresh(after_b)
    assert (
        after_b.original_budget,
        after_b.revised_budget,
        after_b.committed,
        after_b.actual,
        dict(after_b.metadata_ or {}),
    ) == snapshot_b
    # The drawdown never moves the budget columns of the line it draws from.
    a = await fin.get_budget(line_a)
    await session.refresh(a)
    assert a.revised_budget == D("10000")


@pytest.mark.asyncio
async def test_confirm_onto_another_line_moves_it(session):
    svc = RiskService(session)
    line_a = await _line(session, amount="10000", wbs="A")
    line_b = await _line(session, amount="3000", wbs="B")
    rid = await _risk(svc, status="occurred")
    await svc.confirm_contingency_drawdown(PROJECT_ID, rid, _req("500", line_a))
    pos = await svc.confirm_contingency_drawdown(PROJECT_ID, rid, _req("500", line_b))
    assert pos["drawn"] == D("500.00")
    assert await _markers(session, line_a) == {}
    assert len(await _markers(session, line_b)) == 1


@pytest.mark.asyncio
async def test_drawdown_on_usd_line_is_in_usd_and_converts_into_totals(session):
    svc = RiskService(session)
    await _line(session, amount="10000", currency="USD", wbs="U")
    rid = await _risk(svc, status="occurred", impact_cost=D("1000"))
    pos = await svc.confirm_contingency_drawdown(PROJECT_ID, rid, _req("800.005"))
    record = pos["drawdowns"][0]
    assert record["currency"] == "USD"
    assert record["amount"] == D("800.01")  # half up to the cent
    # Totals in EUR at 0.5: allocated 5000, drawn 400.005 -> 400.01.
    assert pos["allocated"] == D("5000.00")
    assert pos["drawn"] == D("400.01")


@pytest.mark.asyncio
async def test_confirm_refuses_a_risk_that_has_not_occurred(session):
    svc = RiskService(session)
    await _line(session)
    rid = await _risk(svc, status="open")
    with pytest.raises(HTTPException) as exc:
        await svc.confirm_contingency_drawdown(PROJECT_ID, rid, _req("100"))
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_confirm_without_a_contingency_line_is_a_conflict(session):
    svc = RiskService(session)
    await _line(session, category="material")
    rid = await _risk(svc, status="occurred")
    with pytest.raises(HTTPException) as exc:
        await svc.confirm_contingency_drawdown(PROJECT_ID, rid, _req("100"))
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_confirm_with_several_lines_needs_a_choice(session):
    svc = RiskService(session)
    await _line(session, wbs="A")
    await _line(session, wbs="B")
    rid = await _risk(svc, status="occurred")
    with pytest.raises(HTTPException) as exc:
        await svc.confirm_contingency_drawdown(PROJECT_ID, rid, _req("100"))
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_confirm_refuses_another_projects_line_and_risk(session):
    svc = RiskService(session)
    await _line(session, wbs="A")
    foreign_line = await _line(session, project_id=OTHER_PROJECT_ID, wbs="A")
    rid = await _risk(svc, status="occurred")
    foreign_risk = await _risk(svc, project_id=OTHER_PROJECT_ID, status="occurred")
    with pytest.raises(HTTPException) as exc:
        await svc.confirm_contingency_drawdown(PROJECT_ID, rid, _req("100", foreign_line))
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        await svc.confirm_contingency_drawdown(PROJECT_ID, foreign_risk, _req("100"))
    assert exc.value.status_code == 404
    assert await _markers(session, foreign_line) == {}


# ── Reversal, deletion and stale edits ────────────────────────────────────


@pytest.mark.asyncio
async def test_reverse_returns_the_money_and_twice_is_not_found(session):
    svc = RiskService(session)
    line = await _line(session, amount="5000")
    rid = await _risk(svc, status="occurred")
    await svc.confirm_contingency_drawdown(PROJECT_ID, rid, _req("1200"))
    pos = await svc.reverse_contingency_drawdown(PROJECT_ID, rid)
    assert pos["drawn"] == D("0.00")
    assert pos["remaining"] == D("5000.00")
    assert len(pos["pending"]) == 1  # occurred again waits for a confirmation
    assert await _markers(session, line) == {}
    with pytest.raises(HTTPException) as exc:
        await svc.reverse_contingency_drawdown(PROJECT_ID, rid)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_deleting_a_drawn_risk_keeps_the_drawn_money(session):
    svc = RiskService(session)
    await _line(session, amount="5000")
    rid = await _risk(svc, status="occurred", title="Flooded basement")
    await svc.confirm_contingency_drawdown(PROJECT_ID, rid, _req("900"))
    await svc.delete_risk(rid)
    pos = await svc.get_contingency_position(PROJECT_ID)
    assert pos["drawn"] == D("900.00")
    assert pos["remaining"] == D("4100.00")
    assert pos["drawdowns"][0]["risk_title"] == "Flooded basement"
    # And it can still be reversed through its project.
    pos = await svc.reverse_contingency_drawdown(PROJECT_ID, rid)
    assert pos["drawn"] == D("0.00")


@pytest.mark.asyncio
async def test_stale_budget_edit_cannot_drop_or_resurrect_a_drawdown(session):
    svc = RiskService(session)
    fin = FinanceService(session)
    line = await _line(session, amount="5000")
    rid = await _risk(svc, status="occurred")
    loaded = await fin.get_budget(line)
    stale_metadata = dict(loaded.metadata_ or {})  # what the Budgets tab holds

    await svc.confirm_contingency_drawdown(PROJECT_ID, rid, _req("900"))
    # Saving the edit form with the metadata it loaded before the drawdown.
    await fin.update_budget(line, BudgetUpdate(metadata={**stale_metadata, "notes": "weather"}))
    pos = await svc.get_contingency_position(PROJECT_ID)
    assert pos["drawn"] == D("900.00")
    b = await fin.get_budget(line)
    await session.refresh(b)
    assert b.metadata_["notes"] == "weather"

    # The other way round: a form loaded while the drawdown existed must not
    # bring it back after it was reversed.
    with_drawdown = dict(b.metadata_ or {})
    await svc.reverse_contingency_drawdown(PROJECT_ID, rid)
    await fin.update_budget(line, BudgetUpdate(metadata=with_drawdown))
    pos = await svc.get_contingency_position(PROJECT_ID)
    assert pos["drawn"] == D("0.00")


@pytest.mark.asyncio
async def test_a_line_with_drawdowns_keeps_its_category(session):
    svc = RiskService(session)
    fin = FinanceService(session)
    line = await _line(session, amount="5000")
    rid = await _risk(svc, status="occurred")
    await svc.confirm_contingency_drawdown(PROJECT_ID, rid, _req("900"))
    with pytest.raises(HTTPException) as exc:
        await fin.update_budget(line, BudgetUpdate(category="material"))
    assert exc.value.status_code == 409
    # Respelling the same category is fine.
    await fin.update_budget(line, BudgetUpdate(category="Contingency"))
    pos = await svc.get_contingency_position(PROJECT_ID)
    assert pos["drawn"] == D("900.00")
