"""The ``phonelog`` rule set: each rule fires, a valid call passes, writes are gated."""

from __future__ import annotations

import uuid

import pytest

from app.core.validation.engine import Severity, ValidationContext, rule_registry
from app.modules.phonelog.models import PhoneLog
from app.modules.phonelog.validators import (
    PHONELOG_RULE_SET,
    CallNotInFutureRule,
    CallTimesOrderedRule,
    InstructionNamesPartyRule,
    LoggedCallHasContentRule,
    register_phonelog_validation_rules,
)

TODAY = "2026-11-04"
KEY = "call"


def _call(**kw):
    base = {
        "id": "c1",
        "status": "logged",
        "occurred_at": "2026-11-03T09:00:00+00:00",
        "ended_at": "2026-11-03T09:10:00+00:00",
        "parties": ["Site manager", "Foreman"],
        "transcript": "Pour the slab on Monday.",
        "summary": "Slab pour confirmed",
        "instructions": ["Pour the slab on Monday."],
    }
    return base | kw


async def _run(rule, record, locale="en"):
    context = ValidationContext(data={KEY: record}, metadata={"locale": locale, "today": TODAY})
    return await rule().validate(context)


CASES = [
    (
        CallNotInFutureRule,
        _call(occurred_at="2026-12-31T09:00:00+00:00"),
        "phonelog.call_not_in_future",
        Severity.ERROR,
    ),
    (
        CallTimesOrderedRule,
        _call(ended_at="2026-11-03T08:00:00+00:00"),
        "phonelog.call_times_ordered",
        Severity.ERROR,
    ),
    (
        LoggedCallHasContentRule,
        _call(transcript="  ", summary=""),
        "phonelog.logged_has_content",
        Severity.ERROR,
    ),
    (InstructionNamesPartyRule, _call(parties=[]), "phonelog.instruction_names_party", Severity.WARNING),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("rule", "bad", "rule_id", "severity"), CASES)
async def test_rule_fires_on_a_violation_and_passes_a_valid_record(rule, bad, rule_id, severity):
    failed = [r for r in await _run(rule, bad) if not r.passed]
    assert [r.rule_id for r in failed] == [rule_id]
    assert failed[0].severity == severity
    assert "{" not in failed[0].message
    assert all(r.passed for r in await _run(rule, _call()))


@pytest.mark.asyncio
async def test_a_draft_without_content_and_a_call_without_instructions_pass():
    assert all(r.passed for r in await _run(LoggedCallHasContentRule, _call(status="draft", transcript="", summary="")))
    assert all(r.passed for r in await _run(InstructionNamesPartyRule, _call(parties=[], instructions=[])))


@pytest.mark.asyncio
async def test_message_is_translated():
    failed = [r for r in await _run(CallNotInFutureRule, CASES[0][1], "de") if not r.passed]
    assert "Zukunft" in failed[0].message


def test_rule_set_is_registered():
    register_phonelog_validation_rules()
    assert len({r.rule_id for r in rule_registry.get_rules_for_sets([PHONELOG_RULE_SET])}) == 4


# -- write points --------------------------------------------------------------------------------------

BASE = "/api/v1/phonelog"


def _body(project_id, **over):
    return {
        "project_id": project_id,
        "raw_parties": "Site manager; Foreman",
        "direction": "inbound",
        "started_at": "2026-11-03T09:00:00+00:00",
        "ended_at": "2026-11-03T09:10:00+00:00",
        "transcript": "Pour the slab on Monday.",
        "summary": "Slab pour confirmed",
    } | over


async def _insert(project_id, **values) -> str:
    from app.database import async_session_factory

    async with async_session_factory() as session:
        row = PhoneLog(project_id=uuid.UUID(project_id), **values)
        session.add(row)
        await session.commit()
        return str(row.id)


@pytest.mark.asyncio
async def test_a_call_from_the_future_is_refused_with_its_code(client, admin_auth, project_id):
    _, h = admin_auth
    resp = await client.post(
        f"{BASE}/",
        json=_body(project_id, started_at="2999-01-01T09:00:00+00:00", ended_at="2999-01-01T09:10:00+00:00"),
        headers=h,
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == "phonelog_rules_failed"
    assert detail["code"] == "phonelog.call_not_in_future"
    ok = await client.post(f"{BASE}/", json=_body(project_id), headers=h)
    assert ok.status_code == 201, ok.text
    assert ok.json()["validation_warnings"] == []


@pytest.mark.asyncio
async def test_a_call_that_ends_before_it_starts_or_says_nothing_is_refused(client, admin_auth, project_id):
    _, h = admin_auth
    inverted = await client.post(f"{BASE}/", json=_body(project_id, ended_at="2026-11-03T08:00:00+00:00"), headers=h)
    assert inverted.status_code == 422, inverted.text
    assert inverted.json()["detail"]["code"] == "phonelog.call_times_ordered"
    empty = await client.post(f"{BASE}/", json=_body(project_id, transcript="", summary=""), headers=h)
    assert empty.status_code == 422, empty.text
    assert empty.json()["detail"]["code"] == "phonelog.logged_has_content"


@pytest.mark.asyncio
async def test_instructions_without_parties_are_saved_with_a_warning(client, admin_auth, project_id):
    _, h = admin_auth
    draft = await _insert(project_id, status="draft", transcript="", summary="")
    resp = await client.patch(
        f"{BASE}/{draft}",
        json={"transcript": "Move the crane.", "raw_parties": "", "instructions": ["Move the crane."]},
        headers=h,
    )
    assert resp.status_code == 200, resp.text
    assert [w["rule_id"] for w in resp.json()["validation_warnings"]] == ["phonelog.instruction_names_party"]


@pytest.mark.asyncio
async def test_confirming_an_empty_draft_is_refused_and_a_filled_one_is_logged(client, admin_auth, project_id):
    _, h = admin_auth
    draft = await _insert(project_id, status="draft", transcript="", summary="")
    refused = await client.patch(f"{BASE}/{draft}", json={"transcript": "", "summary": ""}, headers=h)
    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"]["code"] == "phonelog.logged_has_content"
    ok = await client.patch(f"{BASE}/{draft}", json={"transcript": "Agreed to move the crane."}, headers=h)
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "logged"


@pytest.mark.asyncio
async def test_a_legacy_record_without_content_stays_editable(client, admin_auth, project_id):
    _, h = admin_auth
    legacy = await _insert(project_id, status="logged", transcript="", summary="")
    edited = await client.patch(f"{BASE}/{legacy}", json={"raw_parties": "Foreman", "channel": "phone"}, headers=h)
    assert edited.status_code == 200, edited.text
