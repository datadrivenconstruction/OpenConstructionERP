"""Condition service: scales, ratings, derived plan, inflation, validation (real PostgreSQL)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.core.validation.engine import ValidationEngine, rule_registry
from app.modules.condition.schemas import (
    ActionCreate,
    ActionUpdate,
    AssessmentCreate,
    AssessmentUpdate,
    ScaleCreate,
    ScaleLevel,
)
from app.modules.condition.service import ConditionService
from app.modules.condition.validators import CONDITION_RULE_SET, register_condition_validation_rules

pytestmark = pytest.mark.asyncio


def _assessment(project_id, **kw) -> AssessmentCreate:
    base = {
        "project_id": project_id,
        "element_name": "Flat roof membrane",
        "asset_ref": "roof-1",
        "rating": 5,
        "severity": 3,
        "extent_pct": 40,
        "intensity": 3,
        "quantity": Decimal("500"),
        "unit": "m2",
        "unit_cost": Decimal("60"),
        "currency": "EUR",
    }
    base.update(kw)
    return AssessmentCreate(**base)


async def test_rating_keeps_the_suggestion_beside_the_decision(session, project_id):
    service = ConditionService(session)
    row = await service.create_assessment(_assessment(project_id, rating=6), "u1")
    assert row.rating == 6
    assert row.suggested_rating == 4
    assert 0 < row.suggestion_confidence < 1
    assert row.assessed_at is not None


async def test_rating_off_the_scale_is_refused(session, project_id):
    with pytest.raises(HTTPException) as exc:
        await ConditionService(session).create_assessment(_assessment(project_id, rating=7), "u1")
    assert exc.value.status_code == 422


async def test_project_scale_lifecycle(session, project_id):
    service = ConditionService(session)
    levels = [ScaleLevel(level=i, label=f"L{i}") for i in (1, 2, 3)]
    created = await service.create_scale(project_id, ScaleCreate(key="three", name="Three", levels=levels), "u1")
    assert created["source"] == "custom" and created["action_threshold"] == 3
    keys = [s["key"] for s in await service.list_scales(project_id)]
    assert keys[0] == "default_6" and "three" in keys
    with pytest.raises(HTTPException) as dup:
        await service.create_scale(project_id, ScaleCreate(key="default_6", name="x", levels=levels), None)
    assert dup.value.status_code == 409
    await service.create_assessment(_assessment(project_id, scale_key="three", rating=3), "u1")
    with pytest.raises(HTTPException) as used:
        await service.delete_scale(project_id, "three")
    assert used.value.status_code == 409
    with pytest.raises(HTTPException):
        await service.delete_scale(project_id, "default_6")


async def test_derive_proposes_once_from_the_latest_rating(session, project_id):
    service = ConditionService(session)
    await service.create_assessment(_assessment(project_id, rating=2, assessed_at=date(2025, 1, 1)), "u1")
    latest = await service.create_assessment(_assessment(project_id, rating=5), "u1")
    result = await service.derive(project_id, 2027, "u1")
    assert result["created"] == 1
    action = result["actions"][0]
    assert action.assessment_id == latest.id
    assert action.status == "proposed" and action.source == "derived"
    assert action.action_type == "repair" and action.first_year == 2028
    assert action.quantity == Decimal("200")
    again = await service.derive(project_id, 2027, "u1")
    assert again["created"] == 0


async def test_plan_counts_approved_only_unless_asked(session, project_id):
    service = ConditionService(session)
    await service.create_assessment(_assessment(project_id), "u1")
    derived = (await service.derive(project_id, 2027, "u1"))["actions"][0]
    plan = await service.plan(project_id, start_year=2027, horizon_years=5)
    assert plan["totals"]["cost"] == "0.00"
    with_proposed = await service.plan(project_id, start_year=2027, horizon_years=5, include_proposed=True)
    assert with_proposed["totals"]["cost"] == "12000.00"
    await service.update_action(derived, ActionUpdate(status="approved"), "manager")
    assert derived.decided_by == "manager"
    plan = await service.plan(project_id, start_year=2027, horizon_years=5, inflation_rate=Decimal("0.05"))
    year = next(y for y in plan["years"] if y["year"] == 2028)
    assert year["cost_inflated"] == "12600.00"
    assert plan["inflation_source"] == "explicit"
    assert plan["currencies"] == ["EUR"]


async def test_manual_action_is_approved_and_recurring(session, project_id):
    service = ConditionService(session)
    row = await service.create_action(
        ActionCreate(
            project_id=project_id,
            element_name="Lift",
            action_type="maintain",
            first_year=2027,
            interval_years=1,
            unit_cost=Decimal("1200"),
        ),
        "u1",
    )
    assert row.status == "approved" and row.source == "manual"
    plan = await service.plan(project_id, start_year=2027, horizon_years=3)
    assert [y["cost"] for y in plan["years"]] == ["1200.00", "1200.00", "1200.00"]
    assert plan["totals"]["annual_equivalent"] == "1200.00"


async def test_update_recomputes_the_suggestion(session, project_id):
    service = ConditionService(session)
    row = await service.create_assessment(
        _assessment(project_id, severity=1, extent_pct=5, intensity=1, rating=1), "u1"
    )
    assert row.suggested_rating == 1
    await service.update_assessment(row, AssessmentUpdate(severity=4, extent_pct=90, intensity=4))
    assert row.suggested_rating == 6


async def test_inflation_from_an_unknown_index_series_is_refused(session, project_id):
    import uuid

    with pytest.raises(HTTPException) as exc:
        await ConditionService(session).resolve_inflation(None, uuid.uuid4())
    assert exc.value.status_code == 422


async def test_rules_flag_poor_rating_without_action_and_unpriced_action(session, project_id):
    register_condition_validation_rules()
    service = ConditionService(session)
    poor = await service.create_assessment(_assessment(project_id, severity=None, extent_pct=None), "u1")
    data = {
        "scales": {s["key"]: s for s in await service.list_scales(project_id)},
        "assessments": [
            {
                "id": str(poor.id),
                "asset_ref": poor.asset_ref,
                "element_name": poor.element_name,
                "scale_key": poor.scale_key,
                "rating": poor.rating,
                "severity": None,
                "extent_pct": None,
            }
        ],
        "actions": [{"id": "x", "element_name": "Lift", "status": "approved", "unit_cost": None, "first_year": 2027}],
    }
    report = await ValidationEngine(rule_registry).validate(data=data, rule_sets=[CONDITION_RULE_SET])
    failed = {r.rule_id for r in report.results if not r.passed}
    assert failed == {
        "condition.poor_rating_has_action",
        "condition.action_priced",
        "condition.defect_record_complete",
    }
