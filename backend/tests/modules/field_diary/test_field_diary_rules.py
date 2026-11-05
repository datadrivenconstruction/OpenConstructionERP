"""The ``field_diary`` rule set: each rule on its own, then enforced at the write points."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

os.environ["EXPOSE_DEV_AUTH_SECRETS"] = "true"  # request-magic-link then returns dev_token/dev_pin

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker  # noqa: E402

from app.core.validation.engine import Severity, ValidationContext, rule_registry  # noqa: E402
from app.dependencies import get_session  # noqa: E402
from app.modules.field_diary import models as fd_models  # noqa: E402,F401
from app.modules.field_diary.models import DiaryActivity  # noqa: E402
from app.modules.field_diary.router import router as fd_router  # noqa: E402
from app.modules.field_diary.validators import (  # noqa: E402
    FIELD_DIARY_RULE_SET,
    ActivityTimesConsistentRule,
    CrewHasRecordRule,
    EntryDateNotFutureRule,
    IncidentDescribedRule,
    WorkHoursMatchCrewRule,
    register_field_diary_validation_rules,
)
from tests._pg import isolated_engine  # noqa: E402
from tests.integration.test_field_diary import (  # noqa: E402
    _open_session,
    _request_link_and_grant,
    _seed_user_and_project,
)

TODAY = "2026-11-04"


async def _run(rule: object, entry: dict, locale: str = "en"):
    return await rule.validate(ValidationContext(data={"entry": entry}, metadata={"locale": locale, "today": TODAY}))


def _failed(results: list) -> list:
    return [r for r in results if not r.passed]


def _entry(**over) -> dict:
    base = {"id": "e1", "entry_date": "2026-11-03", "status": "draft", "headcount": 5, "activities": []}
    base.update(over)
    return base


def _act(kind: str = "work", **over) -> dict:
    return {"id": "a1", "activity_type": kind, "description": "Rebar fixing", "hours": "8", **over}


# -- Each rule fires, and a valid record passes --------------------------------


@pytest.mark.asyncio
async def test_entry_date_rule() -> None:
    rule = EntryDateNotFutureRule()
    assert not _failed(await _run(rule, _entry(entry_date=TODAY)))
    assert not _failed(await _run(rule, _entry(entry_date="2026-11-05")))  # one-day grace
    failed = _failed(await _run(rule, _entry(entry_date="2026-11-20")))
    assert len(failed) == 1 and failed[0].severity == Severity.ERROR


@pytest.mark.asyncio
async def test_work_hours_rule() -> None:
    rule = WorkHoursMatchCrewRule()
    assert not _failed(await _run(rule, _entry(activities=[_act(hours="40")])))
    over = _failed(await _run(rule, _entry(headcount=1, activities=[_act(hours="30")])))
    assert len(over) == 1 and over[0].severity == Severity.ERROR
    nobody = _failed(await _run(rule, _entry(headcount=0, activities=[_act(hours="8")])))
    assert len(nobody) == 1 and nobody[0].severity == Severity.WARNING


@pytest.mark.asyncio
async def test_incident_rule() -> None:
    rule = IncidentDescribedRule()
    assert not _failed(await _run(rule, _entry(activities=[_act("incident", description="Slip on ramp")])))
    bad = _failed(await _run(rule, _entry(activities=[_act("incident", description="  ")])))
    assert len(bad) == 1 and bad[0].severity == Severity.ERROR
    delay = _failed(await _run(rule, _entry(activities=[_act("delay", description=None, hours="3")])))
    assert len(delay) == 1 and delay[0].severity == Severity.WARNING


@pytest.mark.asyncio
async def test_activity_times_rule() -> None:
    rule = ActivityTimesConsistentRule()
    ok = _act(started_at="2026-11-03T07:00:00+00:00", ended_at="2026-11-03T15:00:00+00:00", hours="8")
    backwards = _act(started_at="2026-11-03T15:00:00+00:00", ended_at="2026-11-03T07:00:00+00:00")
    short = _act(started_at="2026-11-03T07:00:00+00:00", ended_at="2026-11-03T09:00:00+00:00", hours="8")
    assert not _failed(await _run(rule, _entry(activities=[ok])))
    assert _failed(await _run(rule, _entry(activities=[backwards])))[0].severity == Severity.ERROR
    assert _failed(await _run(rule, _entry(activities=[short])))[0].severity == Severity.WARNING


@pytest.mark.asyncio
async def test_crew_record_rule_only_after_draft() -> None:
    rule = CrewHasRecordRule()
    assert not _failed(await _run(rule, _entry(status="draft")))
    assert not _failed(await _run(rule, _entry(status="submitted", activities=[_act()])))
    failed = _failed(await _run(rule, _entry(status="submitted")))
    assert len(failed) == 1 and failed[0].severity == Severity.WARNING


@pytest.mark.asyncio
async def test_message_is_translated() -> None:
    bad = _entry(activities=[_act("incident", description="")])
    en = _failed(await _run(IncidentDescribedRule(), bad, "en"))[0].message
    de = _failed(await _run(IncidentDescribedRule(), bad, "de"))[0].message
    assert en != de


def test_rules_are_registered_in_the_set() -> None:
    register_field_diary_validation_rules()
    ids = {r.rule_id for r in rule_registry.get_rules_for_sets([FIELD_DIARY_RULE_SET])}
    assert ids >= {
        "field_diary.entry_date_not_future",
        "field_diary.work_hours_match_crew",
        "field_diary.incident_described",
        "field_diary.activity_times_consistent",
        "field_diary.crew_has_record",
    }


# -- Enforced at the API write points ------------------------------------------


@pytest_asyncio.fixture
async def api() -> AsyncIterator[tuple]:
    register_field_diary_validation_rules()
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        app = FastAPI()
        app.include_router(fd_router, prefix="/v1/field-diary")

        async def _session_override():
            async with factory() as s:
                try:
                    yield s
                    await s.commit()
                except Exception:
                    await s.rollback()
                    raise

        app.dependency_overrides[get_session] = _session_override
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            _owner, project_id = await _seed_user_and_project(factory)
            token, pin, _uid = await _request_link_and_grant(client, factory, project_id=project_id)
            session_token = await _open_session(client, token, pin)
            headers = {"Authorization": f"Bearer {session_token}", "X-Field-PIN": pin}
            yield client, factory, project_id, headers


def _rule_ids(resp) -> set[str]:
    return {e["rule_id"] for e in resp.json()["detail"]["errors"]}


async def _entry_api(client, project_id, headers, **over) -> dict:
    body = {"project_id": str(project_id), "entry_date": "2026-11-03", "headcount": 4, **over}
    resp = await client.post("/v1/field-diary/entries/", json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_valid_entry_and_activity_pass_and_submit(api) -> None:
    client, _f, project_id, headers = api
    entry = await _entry_api(client, project_id, headers)
    assert entry["validation_warnings"] == []
    act = await client.post(
        f"/v1/field-diary/entries/{entry['id']}/activities/",
        json={"activity_type": "work", "description": "Column pour", "hours": "20"},
        headers=headers,
    )
    assert act.status_code == 201, act.text
    assert act.json()["validation_warnings"] == []
    sub = await client.post(f"/v1/field-diary/entries/{entry['id']}/submit/", headers=headers)
    assert sub.status_code == 200, sub.text


@pytest.mark.asyncio
async def test_far_future_entry_date_is_refused_with_the_rule_code(api) -> None:
    client, _f, project_id, headers = api
    resp = await client.post(
        "/v1/field-diary/entries/",
        json={"project_id": str(project_id), "entry_date": "2031-01-02", "headcount": 3},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
    assert "field_diary.entry_date_not_future" in _rule_ids(resp)


@pytest.mark.asyncio
async def test_incident_without_description_is_refused_and_delay_only_warns(api) -> None:
    client, _f, project_id, headers = api
    entry = await _entry_api(client, project_id, headers)
    url = f"/v1/field-diary/entries/{entry['id']}/activities/"
    bad = await client.post(url, json={"activity_type": "incident"}, headers=headers)
    assert bad.status_code == 422, bad.text
    assert "field_diary.incident_described" in _rule_ids(bad)
    delay = await client.post(url, json={"activity_type": "delay", "hours": "2"}, headers=headers)
    assert delay.status_code == 201, delay.text
    assert [w["rule_id"] for w in delay.json()["validation_warnings"]] == ["field_diary.incident_described"]


@pytest.mark.asyncio
async def test_hours_beyond_a_day_per_person_are_refused(api) -> None:
    client, _f, project_id, headers = api
    entry = await _entry_api(client, project_id, headers, headcount=1)
    url = f"/v1/field-diary/entries/{entry['id']}/activities/"
    first = await client.post(
        url, json={"activity_type": "work", "description": "Night shift", "hours": "20"}, headers=headers
    )
    assert first.status_code == 201, first.text
    over = await client.post(url, json={"activity_type": "work", "description": "More", "hours": "10"}, headers=headers)
    assert over.status_code == 422, over.text
    assert "field_diary.work_hours_match_crew" in _rule_ids(over)


@pytest.mark.asyncio
async def test_activity_ending_before_it_starts_is_refused(api) -> None:
    client, _f, project_id, headers = api
    entry = await _entry_api(client, project_id, headers)
    resp = await client.post(
        f"/v1/field-diary/entries/{entry['id']}/activities/",
        json={
            "activity_type": "work",
            "description": "Backwards",
            "started_at": "2026-11-03T15:00:00+00:00",
            "ended_at": "2026-11-03T07:00:00+00:00",
        },
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
    assert "field_diary.activity_times_consistent" in _rule_ids(resp)


@pytest.mark.asyncio
async def test_a_legacy_violating_entry_stays_editable(api) -> None:
    client, factory, project_id, headers = api
    entry = await _entry_api(client, project_id, headers)
    async with factory() as s:
        s.add(DiaryActivity(entry_id=uuid.UUID(entry["id"]), activity_type="incident", description=None))
        await s.commit()
    patched = await client.patch(
        f"/v1/field-diary/entries/{entry['id']}/", json={"notes_md": "Foreman note"}, headers=headers
    )
    assert patched.status_code == 200, patched.text
    # A new bad activity is still refused.
    again = await client.post(
        f"/v1/field-diary/entries/{entry['id']}/activities/", json={"activity_type": "incident"}, headers=headers
    )
    assert again.status_code == 422, again.text
