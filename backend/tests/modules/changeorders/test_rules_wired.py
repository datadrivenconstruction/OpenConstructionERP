# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The changeorders rule set runs at the real write points (PostgreSQL).

Errors refuse the write with a coded 422, warnings come back on the record and
do not block, a valid record passes untouched.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MoneyRule
from app.modules.changeorders.schemas import ChangeOrderCreate, ChangeOrderItemCreate, ChangeOrderUpdate
from app.modules.changeorders.service import ChangeOrderService
from app.modules.changeorders.validators import CHANGEORDERS_RULE_SET, register_changeorders_validation_rules
from app.modules.projects.models import Project  # noqa: F401 - register ORM
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    register_changeorders_validation_rules()
    async with transactional_session() as s:
        yield s


async def _project(session: AsyncSession, *, currency: str = "EUR") -> uuid.UUID:
    user = User(email=f"cow-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", full_name="CO", role="admin")
    session.add(user)
    await session.flush()
    proj = Project(name=f"COW {uuid.uuid4().hex[:6]}", owner_id=user.id, currency=currency)
    session.add(proj)
    await session.flush()
    return proj.id


def _rule_ids(exc: HTTPException) -> set[str]:
    return {e["rule_id"] for e in exc.detail["errors"]}


class _AdvisoryRule(MoneyRule):
    rule_id = "changeorders.test_advisory"
    name = "Advisory"
    standard = CHANGEORDERS_RULE_SET
    severity = Severity.WARNING

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        return [self.fail(context, "reference_present", ref="co", field="description")]


@pytest.fixture
def advisory_rule():
    rule_registry.register(_AdvisoryRule(), [CHANGEORDERS_RULE_SET])
    yield
    rule_registry._rules.pop(_AdvisoryRule.rule_id, None)
    rule_registry._rule_sets[CHANGEORDERS_RULE_SET].remove(_AdvisoryRule.rule_id)


@pytest.mark.asyncio
async def test_valid_order_passes_through_the_whole_flow(session):
    pid = await _project(session)
    svc = ChangeOrderService(session)
    order = await svc.create_order(ChangeOrderCreate(project_id=pid, title="Extra footing", schedule_impact_days=5))
    assert order.validation_warnings == []
    item = await svc.add_item(
        order.id, ChangeOrderItemCreate(description="Concrete", new_quantity="10", new_rate="100")
    )
    assert item.validation_warnings == []
    submitted = await svc.submit_order(order.id, str(uuid.uuid4()))
    assert submitted.status == "submitted"
    assert submitted.validation_warnings == []


@pytest.mark.asyncio
async def test_money_without_a_currency_is_refused_on_create(session):
    pid = await _project(session, currency="")
    with pytest.raises(HTTPException) as exc:
        await ChangeOrderService(session).create_order(
            ChangeOrderCreate(project_id=pid, title="No currency", cost_impact="500")
        )
    assert exc.value.status_code == 422
    assert exc.value.detail["error"] == "money_rules_failed"
    assert "changeorders.currency_consistent" in _rule_ids(exc.value)


@pytest.mark.asyncio
async def test_absurd_schedule_impact_is_refused_on_update_and_nothing_is_written(session):
    pid = await _project(session)
    svc = ChangeOrderService(session)
    order = await svc.create_order(ChangeOrderCreate(project_id=pid, title="Delay"))
    with pytest.raises(HTTPException) as exc:
        await svc.update_order(order.id, ChangeOrderUpdate(schedule_impact_days=99999))
    assert exc.value.status_code == 422
    assert "changeorders.values_in_range" in _rule_ids(exc.value)
    assert (await svc.get_order(order.id)).schedule_impact_days == 0


@pytest.mark.asyncio
async def test_unit_slip_item_is_refused_and_not_stored(session):
    pid = await _project(session)
    svc = ChangeOrderService(session)
    order = await svc.create_order(ChangeOrderCreate(project_id=pid, title="Bad line"))
    with pytest.raises(HTTPException) as exc:
        await svc.add_item(
            order.id, ChangeOrderItemCreate(description="Slip", new_quantity="2000000000000", new_rate="10")
        )
    assert "changeorders.values_in_range" in _rule_ids(exc.value)
    assert await svc.repo.list_items_for_order(order.id) == []


@pytest.mark.asyncio
async def test_warning_passes_and_is_reported_on_create_and_submit(session, advisory_rule):
    pid = await _project(session)
    svc = ChangeOrderService(session)
    order = await svc.create_order(ChangeOrderCreate(project_id=pid, title="Advisory"))
    assert [w["rule_id"] for w in order.validation_warnings] == ["changeorders.test_advisory"]
    submitted = await svc.submit_order(order.id, str(uuid.uuid4()))
    assert submitted.status == "submitted"
    assert [w["severity"] for w in submitted.validation_warnings] == ["warning"]


@pytest.mark.asyncio
async def test_reject_is_not_blocked_by_drifted_stored_money(session):
    pid = await _project(session)
    svc = ChangeOrderService(session)
    order = await svc.create_order(ChangeOrderCreate(project_id=pid, title="Legacy"))
    await svc.submit_order(order.id, str(uuid.uuid4()))
    await svc.repo.update_fields(order.id, cost_impact="500", currency="")
    rejected = await svc.reject_order(order.id, str(uuid.uuid4()))
    assert rejected.status == "rejected"
