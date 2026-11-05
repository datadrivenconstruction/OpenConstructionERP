"""The ``site_prep`` and ``site_supervision`` rule sets: each rule fires, writes are gated."""

from __future__ import annotations

import pytest

from app.core.validation.engine import Severity, ValidationContext, rule_registry
from app.modules.site_prep.models import SitePrepItem
from app.modules.site_prep.validators import (
    SITE_PREP_RULE_SET,
    ActivePlanStartRule,
    CompletedNotInFutureRule,
    GateItemOwnedRule,
    ReadyItemDatedRule,
    register_site_prep_validation_rules,
)
from app.modules.site_supervision.models import SupervisionEntry
from app.modules.site_supervision.rules import (
    SITE_SUPERVISION_RULE_SET,
    ConductedVisitDatedRule,
    EntryObservationRule,
    HiddenWorksIdentifiedRule,
    VisitNotInFutureRule,
    register_site_supervision_validation_rules,
)

from ._helpers import force_update

TODAY = "2026-11-04"


async def _run(rule, key, record, locale="en"):
    context = ValidationContext(data={key: record}, metadata={"locale": locale, "today": TODAY})
    return await rule().validate(context)


def _item(**kw):
    return {
        "id": "i1",
        "status": "in_progress",
        "is_gate": True,
        "responsible_party": "Site manager",
        "due_date": "2026-12-01",
        "completed_date": None,
    } | kw


def _plan(**kw):
    return {"id": "p1", "status": "active", "target_start_date": "2027-02-01"} | kw


def _visit(**kw):
    return {"id": "v1", "status": "conducted", "planned_date": "2026-10-30", "actual_date": "2026-10-30"} | kw


def _entry(**kw):
    return {
        "id": "e1",
        "category": "hidden_works",
        "status": "addressed",
        "observation": "Rebar inspected before pour",
        "structured_fields": {"element": "Slab S1", "location": "Level 2"},
    } | kw


PREP_CASES = [
    (
        CompletedNotInFutureRule,
        "item",
        _item(completed_date="2027-01-01"),
        "site_prep.completed_not_in_future",
        Severity.ERROR,
    ),
    (ReadyItemDatedRule, "item", _item(status="ready"), "site_prep.ready_item_dated", Severity.WARNING),
    (GateItemOwnedRule, "item", _item(responsible_party=""), "site_prep.gate_item_owned", Severity.WARNING),
    (ActivePlanStartRule, "plan", _plan(target_start_date=None), "site_prep.active_plan_start_date", Severity.ERROR),
]
PREP_VALID = {"item": _item(), "plan": _plan()}

SUP_CASES = [
    (ConductedVisitDatedRule, "visit", _visit(actual_date=None), "site_supervision.visit_dated", Severity.ERROR),
    (
        VisitNotInFutureRule,
        "visit",
        _visit(actual_date="2027-03-01"),
        "site_supervision.visit_not_in_future",
        Severity.ERROR,
    ),
    (
        EntryObservationRule,
        "entry",
        _entry(category="deviation", observation=""),
        "site_supervision.entry_observation",
        Severity.ERROR,
    ),
    (
        HiddenWorksIdentifiedRule,
        "entry",
        _entry(structured_fields={"element": "Slab S1"}),
        "site_supervision.hidden_works_identified",
        Severity.ERROR,
    ),
]
SUP_VALID = {"visit": _visit(), "entry": _entry()}


@pytest.mark.asyncio
@pytest.mark.parametrize(("rule", "key", "bad", "rule_id", "severity"), PREP_CASES)
async def test_site_prep_rule_fires_on_a_violation_and_passes_a_valid_record(rule, key, bad, rule_id, severity):
    failed = [r for r in await _run(rule, key, bad) if not r.passed]
    assert [r.rule_id for r in failed] == [rule_id]
    assert failed[0].severity == severity
    assert "{" not in failed[0].message
    assert all(r.passed for r in await _run(rule, key, PREP_VALID[key]))


@pytest.mark.asyncio
@pytest.mark.parametrize(("rule", "key", "bad", "rule_id", "severity"), SUP_CASES)
async def test_site_supervision_rule_fires_on_a_violation_and_passes_a_valid_record(rule, key, bad, rule_id, severity):
    failed = [r for r in await _run(rule, key, bad) if not r.passed]
    assert [r.rule_id for r in failed] == [rule_id]
    assert failed[0].severity == severity
    assert "{" not in failed[0].message
    assert all(r.passed for r in await _run(rule, key, SUP_VALID[key]))


@pytest.mark.asyncio
async def test_planned_visits_and_ready_gate_items_are_left_alone():
    assert all(
        r.passed for r in await _run(ConductedVisitDatedRule, "visit", _visit(status="planned", actual_date=None))
    )
    assert all(
        r.passed for r in await _run(VisitNotInFutureRule, "visit", _visit(status="planned", actual_date="2027-03-01"))
    )
    assert all(r.passed for r in await _run(GateItemOwnedRule, "item", _item(status="ready", responsible_party="")))
    assert all(
        r.passed for r in await _run(EntryObservationRule, "entry", _entry(category="conformance", observation=""))
    )


@pytest.mark.asyncio
async def test_messages_are_translated():
    failed = [
        r
        for r in await _run(CompletedNotInFutureRule, "item", _item(completed_date="2027-01-01"), "de")
        if not r.passed
    ]
    assert "Zukunft" in failed[0].message
    failed = [r for r in await _run(ConductedVisitDatedRule, "visit", _visit(actual_date=None), "ru") if not r.passed]
    assert "дат" in failed[0].message


def test_rule_sets_are_registered():
    register_site_prep_validation_rules()
    register_site_supervision_validation_rules()
    assert len({r.rule_id for r in rule_registry.get_rules_for_sets([SITE_PREP_RULE_SET])}) == 4
    assert len({r.rule_id for r in rule_registry.get_rules_for_sets([SITE_SUPERVISION_RULE_SET])}) == 4


# -- write points: site_prep ---------------------------------------------------------------------------


def _prep(project_id, tail=""):
    return f"/api/v1/site-prep/projects/{project_id}/{tail}"


@pytest.mark.asyncio
async def test_an_active_plan_without_a_start_date_is_refused_with_its_code(client, admin_auth, new_project):
    _, h = admin_auth
    pid = await new_project()
    resp = await client.post(_prep(pid, "plan"), json={"status": "active"}, headers=h)
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == "site_prep_rules_failed"
    assert [e["rule_id"] for e in detail["errors"]] == ["site_prep.active_plan_start_date"]
    ok = await client.post(_prep(pid, "plan"), json={"status": "active", "target_start_date": "2027-02-01"}, headers=h)
    assert ok.status_code == 201, ok.text
    assert ok.json()["validation_warnings"] == []


@pytest.mark.asyncio
async def test_a_plan_update_that_clears_the_start_date_of_an_active_plan_is_refused(client, admin_auth, new_project):
    _, h = admin_auth
    pid = await new_project()
    ok = await client.post(_prep(pid, "plan"), json={"status": "draft"}, headers=h)
    assert ok.status_code == 201, ok.text
    bad = await client.patch(_prep(pid, "plan"), json={"status": "active"}, headers=h)
    assert bad.status_code == 422, bad.text
    assert bad.json()["detail"]["error"] == "site_prep_rules_failed"


@pytest.mark.asyncio
async def test_an_item_completed_in_the_future_is_refused_and_a_legacy_one_stays_editable(
    client, admin_auth, new_project
):
    _, h = admin_auth
    pid = await new_project()
    bad = await client.post(
        _prep(pid, "items"),
        json={"category": "access", "title": "Haul road", "status": "ready", "completed_date": "2999-01-01"},
        headers=h,
    )
    assert bad.status_code == 422, bad.text
    assert [e["rule_id"] for e in bad.json()["detail"]["errors"]] == ["site_prep.completed_not_in_future"]

    ok = await client.post(
        _prep(pid, "items"),
        json={"category": "access", "title": "Haul road", "status": "ready", "completed_date": "2026-10-01"},
        headers=h,
    )
    assert ok.status_code == 201, ok.text
    item_id = ok.json()["id"]
    await force_update(SitePrepItem, item_id, completed_date="2999-01-01")
    edited = await client.patch(_prep(pid, f"items/{item_id}"), json={"notes": "Gate keys with the foreman"}, headers=h)
    assert edited.status_code == 200, edited.text


@pytest.mark.asyncio
async def test_a_ready_item_without_a_date_is_saved_with_a_warning(client, admin_auth, new_project):
    _, h = admin_auth
    pid = await new_project()
    resp = await client.post(
        _prep(pid, "items"), json={"category": "access", "title": "Site office", "status": "ready"}, headers=h
    )
    assert resp.status_code == 201, resp.text
    assert [w["rule_id"] for w in resp.json()["validation_warnings"]] == ["site_prep.ready_item_dated"]


# -- write points: site_supervision --------------------------------------------------------------------

SUP = "/api/v1/site-supervision"


@pytest.mark.asyncio
async def test_a_conducted_visit_needs_its_date_and_cannot_lie_in_the_future(client, admin_auth, project_id):
    _, h = admin_auth
    undated = await client.post(
        f"{SUP}/visits/", json={"project_id": project_id, "status": "conducted", "visitor": "Architect"}, headers=h
    )
    assert undated.status_code == 422, undated.text
    detail = undated.json()["detail"]
    assert detail["error"] == "site_supervision_rules_failed"
    assert [e["rule_id"] for e in detail["errors"]] == ["site_supervision.visit_dated"]
    future = await client.post(
        f"{SUP}/visits/",
        json={"project_id": project_id, "status": "reported", "actual_date": "2999-01-01"},
        headers=h,
    )
    assert future.status_code == 422, future.text
    assert [e["rule_id"] for e in future.json()["detail"]["errors"]] == ["site_supervision.visit_not_in_future"]
    ok = await client.post(f"{SUP}/visits/", json={"project_id": project_id, "planned_date": "2999-01-01"}, headers=h)
    assert ok.status_code == 201, ok.text
    assert ok.json()["validation_warnings"] == []
    # the status change dates the visit itself, so it passes
    conducted = await client.post(f"{SUP}/visits/{ok.json()['id']}/conduct", headers=h)
    assert conducted.status_code == 200, conducted.text


@pytest.mark.asyncio
async def test_a_deviation_without_an_observation_is_refused_and_a_legacy_one_stays_editable(
    client, admin_auth, project_id
):
    _, h = admin_auth
    visit = await client.post(
        f"{SUP}/visits/", json={"project_id": project_id, "planned_date": "2999-01-01"}, headers=h
    )
    visit_id = visit.json()["id"]
    bad = await client.post(
        f"{SUP}/entries/", json={"visit_id": visit_id, "category": "deviation", "observation": ""}, headers=h
    )
    assert bad.status_code == 422, bad.text
    assert [e["rule_id"] for e in bad.json()["detail"]["errors"]] == ["site_supervision.entry_observation"]
    ok = await client.post(
        f"{SUP}/entries/",
        json={"visit_id": visit_id, "category": "deviation", "observation": "Cover to rebar 25 mm, 40 mm specified"},
        headers=h,
    )
    assert ok.status_code == 201, ok.text
    entry_id = ok.json()["id"]
    await force_update(SupervisionEntry, entry_id, observation="")
    edited = await client.patch(f"{SUP}/entries/{entry_id}/", json={"links_to_change_ref": "CO-14"}, headers=h)
    assert edited.status_code == 200, edited.text


@pytest.mark.asyncio
async def test_hidden_works_cannot_be_closed_without_naming_element_and_location(client, admin_auth, project_id):
    _, h = admin_auth
    visit = await client.post(
        f"{SUP}/visits/", json={"project_id": project_id, "planned_date": "2999-01-01"}, headers=h
    )
    entry = await client.post(
        f"{SUP}/entries/",
        json={"visit_id": visit.json()["id"], "category": "hidden_works", "observation": "Drainage before backfill"},
        headers=h,
    )
    assert entry.status_code == 201, entry.text
    entry_id = entry.json()["id"]
    bad = await client.patch(f"{SUP}/entries/{entry_id}/", json={"status": "closed"}, headers=h)
    assert bad.status_code == 422, bad.text
    assert [e["rule_id"] for e in bad.json()["detail"]["errors"]] == ["site_supervision.hidden_works_identified"]
    ok = await client.patch(
        f"{SUP}/entries/{entry_id}/",
        json={"status": "closed", "structured_fields": {"element": "Drain D3", "location": "Grid B/4"}},
        headers=h,
    )
    assert ok.status_code == 200, ok.text
