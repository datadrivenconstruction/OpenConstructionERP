# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Assembly rules: each rule firing, a valid record passing, and the API refusing a blocking write."""

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
from app.modules.assemblies.permissions import register_assemblies_permissions
from app.modules.assemblies.router import router as assemblies_router
from app.modules.assemblies.validators import (
    ASSEMBLIES_RULE_SET,
    AssemblyApplicableRule,
    AssemblyCurrencyRule,
    BidFactorPlausibleRule,
    ComponentFactorsRule,
    DuplicateCostItemRule,
    register_assemblies_validation_rules,
)
from app.modules.users.models import User
from tests._pg import transactional_session


def _data(assembly: dict | None = None, components: list[dict] | None = None) -> dict:
    return {
        "assembly": {
            "id": "a1",
            "code": "WALL-01",
            "currency": "EUR",
            "total_rate": "120",
            "bid_factor": "1.0",
            "operation": "edit",
            **(assembly or {}),
        },
        "components": components
        if components is not None
        else [
            {
                "id": "c1",
                "cost_item_id": "i1",
                "description": "Brick",
                "factor": "1.05",
                "quantity": "50",
                "unit_cost": "0.8",
            },
            {
                "id": "c2",
                "cost_item_id": "i2",
                "description": "Mason",
                "factor": "1",
                "quantity": "1.2",
                "unit_cost": "30",
            },
        ],
    }


def _comp(**kw: object) -> dict:
    return {
        "id": "c9",
        "cost_item_id": "i9",
        "description": "Mortar",
        "factor": "1",
        "quantity": "1",
        "unit_cost": "5",
        **kw,
    }


async def _run(rule: object, data: dict, locale: str = "en"):
    return await rule.validate(ValidationContext(data=data, metadata={"locale": locale}))


CASES = [
    (ComponentFactorsRule, _data(), _data(components=[_comp(factor="115")])),
    (ComponentFactorsRule, _data(), _data({"bid_factor": "15"})),
    (BidFactorPlausibleRule, _data(), _data({"bid_factor": "3"})),
    (DuplicateCostItemRule, _data(), _data(components=[_comp(), _comp(id="c10")])),
    (AssemblyCurrencyRule, _data(), _data({"currency": ""})),
    (AssemblyApplicableRule, _data({"operation": "apply"}), _data({"operation": "apply", "total_rate": "0"})),
    (AssemblyApplicableRule, _data({"operation": "apply"}), _data({"operation": "apply"}, components=[])),
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
async def test_drafts_and_partial_records_pass() -> None:
    empty_draft = _data({"total_rate": "0", "currency": ""}, components=[])
    for rule_cls, _, _ in CASES:
        assert all(r.passed for r in await _run(rule_cls(), {}))
        assert all(r.passed for r in await _run(rule_cls(), empty_draft))  # edit of an empty draft
    # a component with no cost item (free text line) is never a duplicate of another
    free = _data(components=[_comp(cost_item_id=""), _comp(id="c10", cost_item_id="")])
    assert all(r.passed for r in await _run(DuplicateCostItemRule(), free))
    # bid factor beyond the hard limits belongs to the error rule only
    assert all(r.passed for r in await _run(BidFactorPlausibleRule(), _data({"bid_factor": "15"})))


@pytest.mark.asyncio
async def test_apply_message_follows_locale() -> None:
    bad = _data({"operation": "apply", "total_rate": "0"})
    ru = (await _run(AssemblyApplicableRule(), bad, locale="ru"))[0]
    assert "WALL-01" in ru.message
    assert "сборк" in ru.message


def test_registered_under_rule_set() -> None:
    register_assemblies_validation_rules()
    ids = {r.rule_id for r in rule_registry.get_rules_for_sets([ASSEMBLIES_RULE_SET])}
    assert "assemblies.applicable" in ids
    assert len(ids) == 5


# ── API on real PostgreSQL ───────────────────────────────────────────────────


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    register_assemblies_permissions()
    register_assemblies_validation_rules()
    async with transactional_session() as session:
        user = User(email=f"asm-{uuid.uuid4().hex[:6]}@example.com", hashed_password="x", role="admin")
        session.add(user)
        await session.flush()
        await session.commit()
        app = FastAPI()
        app.include_router(assemblies_router, prefix="/v1/assemblies")

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
            yield c


async def _make_assembly(c: AsyncClient) -> str:
    r = await c.post(
        "/v1/assemblies/",
        json={"code": f"A-{uuid.uuid4().hex[:6]}", "name": "Brick wall", "unit": "m2", "currency": "EUR"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.mark.asyncio
async def test_api_blocks_slipped_factor_with_code(client: AsyncClient) -> None:
    aid = await _make_assembly(client)
    ok = await client.post(
        f"/v1/assemblies/{aid}/components/",
        json={"description": "Brick", "unit": "pcs", "quantity": 50, "unit_cost": "0.8", "factor": 1.05},
    )
    assert ok.status_code == 201, ok.text

    r = await client.post(
        f"/v1/assemblies/{aid}/components/",
        json={"description": "Mortar", "unit": "kg", "quantity": 5, "unit_cost": "0.3", "factor": 115},
    )
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "assemblies.factors_in_range"
    assert detail["error"] == "assemblies_rules_failed"


@pytest.mark.asyncio
async def test_api_blocks_update_to_slipped_bid_factor_and_reports_findings(client: AsyncClient) -> None:
    aid = await _make_assembly(client)
    r = await client.patch(f"/v1/assemblies/{aid}", json={"bid_factor": 15})
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "assemblies.factors_in_range"

    # warnings do not block: a plausible-but-high bid factor saves, and shows on the report
    r = await client.patch(f"/v1/assemblies/{aid}", json={"bid_factor": 3})
    assert r.status_code == 200, r.text
    report = (await client.get(f"/v1/assemblies/{aid}/validation/")).json()
    assert report["errors"] == []
    assert "assemblies.bid_factor_plausible" in {w["rule_id"] for w in report["warnings"]}


@pytest.mark.asyncio
async def test_api_refuses_to_apply_an_empty_assembly(client: AsyncClient) -> None:
    aid = await _make_assembly(client)
    r = await client.post(
        f"/v1/assemblies/{aid}/apply-to-boq/",
        json={"boq_id": str(uuid.uuid4()), "quantity": 10},
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "assemblies.applicable"


@pytest_asyncio.fixture
async def stored_session(client: AsyncClient):
    """The session behind ``client`` is the transactional one; reach it through the dependency override."""
    session = None
    async for s in client._transport.app.dependency_overrides[get_session]():  # type: ignore[union-attr]
        session = s
    return session


@pytest.mark.asyncio
async def test_edit_is_blocked_only_by_errors_it_introduces(client: AsyncClient, stored_session) -> None:
    from sqlalchemy import update

    from app.modules.assemblies.models import Component

    aid = await _make_assembly(client)
    r = await client.post(
        f"/v1/assemblies/{aid}/components/",
        json={"description": "Brick", "unit": "pcs", "quantity": 50, "unit_cost": "0.8", "factor": 1.05},
    )
    assert r.status_code == 201, r.text
    # A component saved before the rules existed carries a slipped factor.
    await stored_session.execute(update(Component).where(Component.assembly_id == uuid.UUID(aid)).values(factor="115"))
    await stored_session.flush()

    r = await client.patch(f"/v1/assemblies/{aid}", json={"bid_factor": 1.1})
    assert r.status_code == 200, r.text
    r = await client.post(
        f"/v1/assemblies/{aid}/components/",
        json={"description": "Sand", "unit": "kg", "quantity": 5, "unit_cost": "0.3", "factor": 1.02},
    )
    assert r.status_code == 201, r.text
    r = await client.post(
        f"/v1/assemblies/{aid}/components/",
        json={"description": "Mortar", "unit": "kg", "quantity": 5, "unit_cost": "0.3", "factor": 99},
    )
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "assemblies.factors_in_range"
    assert {"results", "rule_sets", "status"} <= set(detail)
