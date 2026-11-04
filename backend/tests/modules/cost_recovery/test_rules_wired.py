# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The cost_recovery rule set runs at the real write points (PostgreSQL).

Errors refuse the write with a coded 422, warnings come back on the record and
do not block, a valid record passes untouched.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MoneyRule
from app.modules.cost_recovery.schemas import ApportionmentShareIn, BackChargeCreate, BackChargeUpdate
from app.modules.cost_recovery.service import apportion_back_charge, create_back_charge, update_back_charge
from app.modules.cost_recovery.validators import COST_RECOVERY_RULE_SET, register_cost_recovery_validation_rules
from app.modules.projects.models import Project  # noqa: F401 - register ORM
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    register_cost_recovery_validation_rules()
    async with transactional_session() as s:
        yield s


async def _project(session: AsyncSession) -> uuid.UUID:
    user = User(email=f"crw-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", full_name="CR", role="admin")
    session.add(user)
    await session.flush()
    proj = Project(name=f"CRW {uuid.uuid4().hex[:6]}", owner_id=user.id, currency="USD")
    session.add(proj)
    await session.flush()
    return proj.id


def _rule_ids(exc: HTTPException) -> set[str]:
    return {e["rule_id"] for e in exc.detail["errors"]}


class _AdvisoryRule(MoneyRule):
    rule_id = "cost_recovery.test_advisory"
    name = "Advisory"
    standard = COST_RECOVERY_RULE_SET
    severity = Severity.WARNING

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        return [self.fail(context, "reference_present", ref="bc", field="basis")]


@pytest.fixture
def advisory_rule():
    rule_registry.register(_AdvisoryRule(), [COST_RECOVERY_RULE_SET])
    yield
    rule_registry._rules.pop(_AdvisoryRule.rule_id, None)
    rule_registry._rule_sets[COST_RECOVERY_RULE_SET].remove(_AdvisoryRule.rule_id)


@pytest.mark.asyncio
async def test_valid_back_charge_passes_without_warnings(session):
    pid = await _project(session)
    bc = await create_back_charge(
        session, pid, BackChargeCreate(responsible_party="Sub A", gross_amount=Decimal("1000"))
    )
    assert bc.status == "proposed"
    assert bc.validation_warnings == []


@pytest.mark.asyncio
async def test_create_without_responsible_party_is_refused_with_its_code(session):
    pid = await _project(session)
    with pytest.raises(HTTPException) as exc:
        await create_back_charge(session, pid, BackChargeCreate(gross_amount=Decimal("500")))
    assert exc.value.status_code == 422
    assert exc.value.detail["error"] == "money_rules_failed"
    assert "cost_recovery.references_present" in _rule_ids(exc.value)


@pytest.mark.asyncio
async def test_update_to_an_edge_the_workflow_lacks_is_refused(session):
    pid = await _project(session)
    bc = await create_back_charge(
        session, pid, BackChargeCreate(responsible_party="Sub A", gross_amount=Decimal("100"))
    )
    with pytest.raises(HTTPException) as exc:
        await update_back_charge(session, pid, bc.id, BackChargeUpdate(status="recovered"))
    assert exc.value.status_code == 422
    assert "cost_recovery.status_transition" in _rule_ids(exc.value)
    assert bc.status == "proposed"


@pytest.mark.asyncio
async def test_recovery_above_the_chargeable_amount_is_refused(session):
    pid = await _project(session)
    bc = await create_back_charge(
        session, pid, BackChargeCreate(responsible_party="Sub A", gross_amount=Decimal("100"), status="agreed")
    )
    with pytest.raises(HTTPException) as exc:
        await update_back_charge(
            session, pid, bc.id, BackChargeUpdate(status="recovered", recovered_amount=Decimal("250"))
        )
    assert "cost_recovery.values_in_range" in _rule_ids(exc.value)


@pytest.mark.asyncio
async def test_valid_update_and_apportionment_pass(session):
    pid = await _project(session)
    bc = await create_back_charge(
        session, pid, BackChargeCreate(responsible_party="Sub A", gross_amount=Decimal("100"))
    )
    updated = await update_back_charge(session, pid, bc.id, BackChargeUpdate(status="agreed"))
    assert updated.status == "agreed"
    assert updated.validation_warnings == []
    rows = await apportion_back_charge(
        session,
        pid,
        bc.id,
        [
            ApportionmentShareIn(party="Sub A", share_pct=Decimal("0.6")),
            ApportionmentShareIn(party="Sub B", share_pct=Decimal("0.4")),
        ],
    )
    assert sum(r.share_amount for r in rows) == Decimal("100")


@pytest.mark.asyncio
async def test_warning_passes_and_is_reported(session, advisory_rule):
    pid = await _project(session)
    bc = await create_back_charge(
        session, pid, BackChargeCreate(responsible_party="Sub A", gross_amount=Decimal("100"))
    )
    assert bc.id is not None
    assert [w["rule_id"] for w in bc.validation_warnings] == ["cost_recovery.test_advisory"]
    assert bc.validation_warnings[0]["severity"] == "warning"
