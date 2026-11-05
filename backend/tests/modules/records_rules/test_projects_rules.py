"""The ``projects`` rule set: each rule fires, a valid project passes, writes are gated."""

from __future__ import annotations

import uuid

import pytest

from app.core.validation.engine import Severity, ValidationContext, rule_registry
from app.modules.projects.validators import (
    PROJECTS_RULE_SET,
    ActualDatesNotFutureRule,
    ActualDatesOrderRule,
    ActualEndNeedsStartRule,
    BudgetNeedsContingencyRule,
    MoneyNeedsCurrencyRule,
    PlannedDatesOrderRule,
    register_projects_validation_rules,
)

TODAY = "2026-11-04"


def _p(**kw):
    base = {
        "id": "p1",
        "planned_start_date": "2026-03-01",
        "planned_end_date": "2027-03-01",
        "actual_start_date": "2026-03-15",
        "actual_end_date": None,
        "contract_value": "1250000",
        "budget_estimate": "1100000.50",
        "contingency_pct": "7.5",
        "gross_floor_area": "4200",
        "currency": "EUR",
    }
    base.update(kw)
    return base


async def _run(rule, project, locale="en"):
    context = ValidationContext(data={"project": project}, metadata={"locale": locale, "today": TODAY})
    return await rule().validate(context)


CASES = [
    (PlannedDatesOrderRule, _p(planned_end_date="2026-02-01"), "projects.planned_dates_order", Severity.ERROR),
    (
        ActualDatesOrderRule,
        _p(actual_end_date="2026-03-01"),
        "projects.actual_dates_order",
        Severity.ERROR,
    ),
    (
        ActualEndNeedsStartRule,
        _p(actual_start_date=None, actual_end_date="2026-06-01"),
        "projects.actual_end_needs_start",
        Severity.ERROR,
    ),
    (BudgetNeedsContingencyRule, _p(contingency_pct=""), "projects.budget_has_contingency", Severity.WARNING),
    (
        ActualDatesNotFutureRule,
        _p(actual_start_date="2999-01-01"),
        "projects.actual_not_in_future",
        Severity.WARNING,
    ),
    (MoneyNeedsCurrencyRule, _p(currency=""), "projects.money_has_currency", Severity.WARNING),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("rule", "bad", "rule_id", "severity"), CASES)
async def test_rule_fires_on_a_violation_and_passes_a_valid_project(rule, bad, rule_id, severity):
    failed = [r for r in await _run(rule, bad) if not r.passed]
    assert [r.rule_id for r in failed] == [rule_id]
    assert failed[0].severity == severity
    assert "{" not in failed[0].message
    assert all(r.passed for r in await _run(rule, _p()))


@pytest.mark.asyncio
async def test_absent_values_are_never_findings():
    empty = {"id": "p2"}
    for rule in (PlannedDatesOrderRule, ActualDatesOrderRule, ActualEndNeedsStartRule, ActualDatesNotFutureRule):
        assert all(r.passed for r in await _run(rule, empty))
    assert all(
        r.passed for r in await _run(MoneyNeedsCurrencyRule, _p(currency="", contract_value="0", budget_estimate=None))
    )


@pytest.mark.asyncio
async def test_message_is_translated():
    failed = [r for r in await _run(PlannedDatesOrderRule, _p(planned_end_date="2026-02-01"), "de") if not r.passed]
    assert "geplante" in failed[0].message


def test_rule_set_is_registered():
    register_projects_validation_rules()
    assert len({r.rule_id for r in rule_registry.get_rules_for_sets([PROJECTS_RULE_SET])}) == 6


def _body(**over):
    body = {
        "name": f"Rules {uuid.uuid4().hex[:6]}",
        "currency": "EUR",
        "planned_start_date": "2026-03-01",
        "planned_end_date": "2027-03-01",
        "contract_value": "1250000",
        "contingency_pct": "7.5",
    }
    body.update(over)
    return body


def _codes(resp):
    return {e["rule_id"] for e in resp.json()["detail"]["errors"]}


@pytest.mark.asyncio
async def test_blocking_rules_reject_api_create_with_code(client, admin_auth):
    _, h = admin_auth
    r = await client.post("/api/v1/projects/", json=_body(planned_end_date="2026-01-01"), headers=h)
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "project_rules_failed"
    assert r.json()["detail"]["code"] == "projects.planned_dates_order"
    r = await client.post(
        "/api/v1/projects/", json=_body(actual_start_date=None, actual_end_date="2026-06-01"), headers=h
    )
    assert r.status_code == 422 and _codes(r) == {"projects.actual_end_needs_start"}


@pytest.mark.asyncio
async def test_valid_project_is_clean_and_future_actuals_are_warned(client, admin_auth):
    _, h = admin_auth
    ok = await client.post("/api/v1/projects/", json=_body(), headers=h)
    assert ok.status_code == 201, ok.text
    assert ok.json()["validation_warnings"] == []
    warned = await client.post(
        "/api/v1/projects/", json=_body(actual_start_date="2999-01-01", currency="", region="DACH"), headers=h
    )
    assert warned.status_code == 201, warned.text
    assert {w["rule_id"] for w in warned.json()["validation_warnings"]} == {
        "projects.actual_not_in_future",
        "projects.money_has_currency",
    }
    nobuffer = await client.post(
        "/api/v1/projects/", json=_body(budget_estimate="900000", contingency_pct=None), headers=h
    )
    assert [w["rule_id"] for w in nobuffer.json()["validation_warnings"]] == ["projects.budget_has_contingency"]


@pytest.mark.asyncio
async def test_project_with_only_a_name_is_still_created(client, admin_auth):
    _, h = admin_auth
    r = await client.post("/api/v1/projects/", json={"name": f"Bare {uuid.uuid4().hex[:6]}"}, headers=h)
    assert r.status_code == 201, r.text
    assert r.json()["validation_warnings"] == []


@pytest.mark.asyncio
async def test_update_blocks_an_introduced_error_and_keeps_the_stored_project(client, admin_auth):
    _, h = admin_auth
    proj = (await client.post("/api/v1/projects/", json=_body(), headers=h)).json()
    bad = await client.patch(f"/api/v1/projects/{proj['id']}", json={"planned_end_date": "2025-01-01"}, headers=h)
    assert bad.status_code == 422 and _codes(bad) == {"projects.planned_dates_order"}
    assert (await client.get(f"/api/v1/projects/{proj['id']}", headers=h)).json()["planned_end_date"] == "2027-03-01"
    fine = await client.patch(f"/api/v1/projects/{proj['id']}", json={"planned_end_date": "2028-01-01"}, headers=h)
    assert fine.status_code == 200, fine.text


@pytest.mark.asyncio
async def test_legacy_project_with_reversed_dates_stays_editable(client, admin_auth):
    uid, h = admin_auth
    from app.database import async_session_factory
    from app.modules.projects.models import Project

    async with async_session_factory() as s:
        legacy = Project(
            name=f"Legacy {uuid.uuid4().hex[:6]}",
            owner_id=uuid.UUID(uid),
            currency="EUR",
            planned_start_date="2026-05-01",
            planned_end_date="2026-03-01",
        )
        s.add(legacy)
        await s.commit()
        pid = str(legacy.id)
    edit = await client.patch(f"/api/v1/projects/{pid}", json={"description": "site office moved"}, headers=h)
    assert edit.status_code == 200, edit.text
    worse = await client.patch(f"/api/v1/projects/{pid}", json={"planned_end_date": "2026-02-01"}, headers=h)
    assert worse.status_code == 422 and _codes(worse) == {"projects.planned_dates_order"}


@pytest.mark.asyncio
async def test_duplicate_of_a_legacy_project_is_not_refused(client, admin_auth):
    uid, h = admin_auth
    from app.database import async_session_factory
    from app.modules.projects.models import Project

    async with async_session_factory() as s:
        legacy = Project(
            name=f"Legacy copy {uuid.uuid4().hex[:6]}",
            owner_id=uuid.UUID(uid),
            currency="EUR",
            planned_start_date="2026-05-01",
            planned_end_date="2026-03-01",
        )
        s.add(legacy)
        await s.commit()
        pid = str(legacy.id)
    dup = await client.post(f"/api/v1/projects/{pid}/duplicate/", json={}, headers=h)
    assert dup.status_code in (200, 201), dup.text
