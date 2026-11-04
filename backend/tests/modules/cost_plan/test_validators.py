# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Cost plan rules: each rule firing, a valid plan passing, and the export refusing a blocking one."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.core.audit_log  # noqa: F401 - registers ActivityLog with Base
from app.core.validation.engine import ValidationContext, rule_registry
from app.dependencies import get_current_user_id, get_current_user_payload, get_session
from app.modules.boq.models import BOQ, Position
from app.modules.cost_plan.permissions import register_cost_plan_permissions
from app.modules.cost_plan.router import router as cost_plan_router
from app.modules.cost_plan.validators import (
    COST_PLAN_RULE_SET,
    GifaMissingRule,
    MarkupLoadRule,
    PlanCurrencyRule,
    PlanTiesToBillRule,
    UnallocatedShareRule,
    register_cost_plan_validation_rules,
)
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session


def _plan(**kw: object) -> dict:
    return {
        "plan": {
            "id": "b1",
            "currency": "EUR",
            "gifa": "1200",
            "direct_cost": "1000",
            "grand_total": "1150",
            "markups_total": "150",
            "allocated_total": "980",
            "unallocated_total": "20",
            "unallocated_count": 1,
            "building_works_total": "900",
            **kw,
        }
    }


async def _run(rule: object, data: dict, locale: str = "en"):
    return await rule.validate(ValidationContext(data=data, metadata={"locale": locale}))


CASES = [
    (PlanTiesToBillRule, _plan(), _plan(allocated_total="900")),
    (PlanTiesToBillRule, _plan(), _plan(grand_total="1000")),
    (PlanCurrencyRule, _plan(), _plan(currency="")),
    (UnallocatedShareRule, _plan(), _plan(allocated_total="800", unallocated_total="200", unallocated_count=7)),
    (GifaMissingRule, _plan(), _plan(gifa=None)),
    (MarkupLoadRule, _plan(), _plan(markups_total="1400", grand_total="2400")),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("rule_cls", "good", "bad"), CASES)
async def test_rule_passes_and_fails(rule_cls: type, good: dict, bad: dict) -> None:
    rule = rule_cls()
    assert all(r.passed for r in await _run(rule, good))
    failed = [r for r in await _run(rule, bad) if not r.passed]
    assert failed
    assert "cost_rules." not in failed[0].message
    assert "money." not in failed[0].message


@pytest.mark.asyncio
async def test_empty_bill_plan_passes_every_rule() -> None:
    zero = _plan(
        currency="",
        gifa=None,
        direct_cost="0",
        grand_total="0",
        markups_total="0",
        allocated_total="0",
        unallocated_total="0",
        unallocated_count=0,
        building_works_total="0",
    )
    for rule_cls, _, _ in CASES:
        assert all(r.passed for r in await _run(rule_cls(), zero)), rule_cls.__name__
        assert all(r.passed for r in await _run(rule_cls(), {})), rule_cls.__name__


@pytest.mark.asyncio
async def test_unallocated_message_follows_locale() -> None:
    bad = _plan(allocated_total="800", unallocated_total="200", unallocated_count=7)
    de = (await _run(UnallocatedShareRule(), bad, locale="de"))[0]
    assert "20.0" in de.message
    assert "NRM-1" in de.message


def test_registered_under_rule_set() -> None:
    register_cost_plan_validation_rules()
    ids = {r.rule_id for r in rule_registry.get_rules_for_sets([COST_PLAN_RULE_SET])}
    assert "cost_plan.ties_to_bill" in ids
    assert len(ids) == 5


# ── API on real PostgreSQL ───────────────────────────────────────────────────


@pytest_asyncio.fixture
async def ctx() -> AsyncIterator[tuple[AsyncClient, object, User]]:
    register_cost_plan_permissions()
    register_cost_plan_validation_rules()
    async with transactional_session() as session:
        user = User(email=f"cp-{uuid.uuid4().hex[:6]}@example.com", hashed_password="x", role="admin")
        session.add(user)
        await session.flush()
        await session.commit()
        app = FastAPI()
        app.include_router(cost_plan_router, prefix="/v1/cost-plan")

        async def _session():
            yield session

        app.dependency_overrides[get_session] = _session
        app.dependency_overrides[get_current_user_id] = lambda: str(user.id)
        app.dependency_overrides[get_current_user_payload] = lambda: {
            "sub": str(user.id),
            "role": "admin",
            "permissions": [],
        }
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c, session, user


async def _bill(
    session, user: User, *, currency: str, gifa: str | None, code: str | None, rate: str = "100"
) -> uuid.UUID:
    project = Project(name="CP test", owner_id=user.id, currency=currency, gross_floor_area=gifa)
    session.add(project)
    await session.flush()
    boq = BOQ(project_id=project.id, name="Bill 1")
    session.add(boq)
    await session.flush()
    session.add(
        Position(
            boq_id=boq.id,
            ordinal="01",
            description="Strip foundation",
            unit="m3",
            quantity="10",
            unit_rate=rate,
            total=str(10 * int(rate)),
            classification={"nrm": code} if code else {},
        )
    )
    await session.flush()
    await session.commit()
    return boq.id


@pytest.mark.asyncio
async def test_api_reports_findings_without_blocking_the_reading(ctx) -> None:
    c, session, user = ctx
    boq = await _bill(session, user, currency="EUR", gifa=None, code=None)
    r = await c.get(f"/v1/cost-plan/boqs/{boq}/nrm1")
    assert r.status_code == 200, r.text
    ids = {f["rule_id"] for f in r.json()["findings"]}
    assert {"cost_plan.unallocated_share"} <= ids
    assert all(f["severity"] == "warning" for f in r.json()["findings"])


@pytest.mark.asyncio
async def test_api_clean_plan_has_no_findings(ctx) -> None:
    c, session, user = ctx
    boq = await _bill(session, user, currency="EUR", gifa="500", code="1.1")
    r = await c.get(f"/v1/cost-plan/boqs/{boq}/nrm1")
    assert r.status_code == 200, r.text
    assert r.json()["findings"] == []
    x = await c.get(f"/v1/cost-plan/boqs/{boq}/nrm1/export.xlsx")
    assert x.status_code == 200, x.text[:200]


@pytest.mark.asyncio
async def test_api_export_refuses_a_plan_with_money_and_no_currency(ctx) -> None:
    c, session, user = ctx
    boq = await _bill(session, user, currency="", gifa="500", code="1.1")
    read = await c.get(f"/v1/cost-plan/boqs/{boq}/nrm1")
    assert read.status_code == 200
    assert "cost_plan.currency_stated" in {f["rule_id"] for f in read.json()["findings"]}
    r = await c.get(f"/v1/cost-plan/boqs/{boq}/nrm1/export.xlsx")
    assert r.status_code == 422, r.text[:300]
    assert r.json()["detail"]["code"] == "cost_plan.currency_stated"
