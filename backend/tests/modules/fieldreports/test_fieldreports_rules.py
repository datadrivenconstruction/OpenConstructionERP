"""The ``fieldreports`` rule set: each rule on its own, then enforced at the write points."""

from __future__ import annotations

import io

import pytest
from httpx import AsyncClient

from app.core.validation.engine import Severity, ValidationContext, rule_registry
from app.modules.fieldreports.validators import (
    FIELDREPORTS_RULE_SET,
    DelayExplainedRule,
    EquipmentHoursPlausibleRule,
    ReportDateNotFutureRule,
    ReportHasContentRule,
    WorkforceHoursPlausibleRule,
    register_fieldreports_validation_rules,
)

TODAY = "2026-11-04"


async def _run(rule: object, data: dict, locale: str = "en"):
    return await rule.validate(ValidationContext(data=data, metadata={"locale": locale, "today": TODAY}))


def _failed(results: list) -> list:
    return [r for r in results if not r.passed]


def _report(**over) -> dict:
    base = {
        "id": "r1",
        "status": "submitted",
        "report_date": "2026-11-03",
        "work_performed": "Poured slab, zone B",
        "notes": None,
        "delays": None,
        "delay_hours": 0,
        "workforce": [],
    }
    base.update(over)
    return {"report": base}


# ── Each rule fires, and a valid record passes ──────────────────────────────


@pytest.mark.asyncio
async def test_content_rule_blocks_an_empty_submitted_report_only() -> None:
    rule = ReportHasContentRule()
    empty = _report(work_performed="  ")
    assert not _failed(await _run(rule, _report()))
    assert not _failed(
        await _run(rule, _report(work_performed="", workforce=[{"trade": "Mason", "count": 3, "hours": 8}]))
    )
    assert not _failed(await _run(rule, _report(status="draft", work_performed="")))
    failed = _failed(await _run(rule, empty))
    assert len(failed) == 1 and failed[0].severity == Severity.ERROR


@pytest.mark.asyncio
async def test_delay_rule_is_an_error_after_draft_and_a_warning_in_draft() -> None:
    rule = DelayExplainedRule()
    assert not _failed(await _run(rule, _report(delay_hours=3, delays="Rain stopped the pour")))
    assert not _failed(await _run(rule, _report(delay_hours=0)))
    assert _failed(await _run(rule, _report(delay_hours=3)))[0].severity == Severity.ERROR
    assert _failed(await _run(rule, _report(status="draft", delay_hours=3)))[0].severity == Severity.WARNING


@pytest.mark.asyncio
async def test_future_date_rule() -> None:
    rule = ReportDateNotFutureRule()
    assert not _failed(await _run(rule, _report(report_date=TODAY)))
    assert _failed(await _run(rule, _report(report_date="2026-11-20")))[0].severity == Severity.ERROR
    assert _failed(await _run(rule, _report(status="draft", report_date="2026-11-20")))[0].severity == Severity.WARNING


@pytest.mark.asyncio
async def test_workforce_hours_rule_reads_per_person_and_crew_totals() -> None:
    rule = WorkforceHoursPlausibleRule()
    assert not _failed(await _run(rule, _report(workforce=[{"trade": "Mason", "count": 4, "hours": 10}])))
    assert len(_failed(await _run(rule, _report(workforce=[{"trade": "Mason", "count": 4, "hours": 40}])))) == 1
    ok_log = {"workforce_log": [{"id": "w", "item": "Rebar", "count": 5, "hours": 60}], **_report()}
    bad_log = {"workforce_log": [{"id": "w", "item": "Rebar", "count": 2, "hours": 60}], **_report()}
    assert not _failed(await _run(rule, ok_log))
    assert len(_failed(await _run(rule, bad_log))) == 1


@pytest.mark.asyncio
async def test_equipment_hours_rule() -> None:
    rule = EquipmentHoursPlausibleRule()
    ok = {
        "equipment_log": [
            {"id": "e", "item": "Crane", "hours_operational": "8", "hours_standby": "2", "hours_breakdown": "0"}
        ]
    }
    bad = {
        "equipment_log": [
            {"id": "e", "item": "Crane", "hours_operational": "20", "hours_standby": "4", "hours_breakdown": "2"}
        ]
    }
    assert not _failed(await _run(rule, ok))
    assert len(_failed(await _run(rule, bad))) == 1


@pytest.mark.asyncio
async def test_message_is_translated() -> None:
    bad = _report(delay_hours=3)
    en = _failed(await _run(DelayExplainedRule(), bad, "en"))[0].message
    ru = _failed(await _run(DelayExplainedRule(), bad, "ru"))[0].message
    assert en != ru and "3" in ru


def test_rules_are_registered_in_the_set() -> None:
    register_fieldreports_validation_rules()
    ids = {r.rule_id for r in rule_registry.get_rules_for_sets([FIELDREPORTS_RULE_SET])}
    assert ids >= {
        "fieldreports.content_recorded",
        "fieldreports.delay_explained",
        "fieldreports.date_not_future",
        "fieldreports.workforce_hours_plausible",
        "fieldreports.equipment_hours_plausible",
    }


# ── Enforced at the API write points ────────────────────────────────────────

BASE = "/api/v1/fieldreports"


def _body(project_id: str, **over) -> dict:
    body = {"project_id": project_id, "report_date": "2026-11-03", "work_performed": "Formwork level 2"}
    body.update(over)
    return body


def _rule_ids(resp) -> set[str]:
    return {e["rule_id"] for e in resp.json()["detail"]["errors"]}


async def _create(client: AsyncClient, header: dict, project_id: str, **over) -> dict:
    resp = await client.post(f"{BASE}/reports/", json=_body(project_id, **over), headers=header)
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_valid_report_passes_and_submits(client, admin_auth, project_id) -> None:
    _, header = admin_auth
    report = await _create(client, header, project_id, workforce=[{"trade": "Carpenter", "count": 3, "hours": 8}])
    assert report["validation_warnings"] == []
    resp = await client.post(f"{BASE}/reports/{report['id']}/submit/", headers=header)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "submitted"


@pytest.mark.asyncio
async def test_empty_report_cannot_be_submitted(client, admin_auth, project_id) -> None:
    _, header = admin_auth
    report = await _create(client, header, project_id, work_performed="")
    resp = await client.post(f"{BASE}/reports/{report['id']}/submit/", headers=header)
    assert resp.status_code == 422, resp.text
    assert "fieldreports.content_recorded" in _rule_ids(resp)
    still = await client.get(f"{BASE}/reports/{report['id']}", headers=header)
    assert still.json()["status"] == "draft"


@pytest.mark.asyncio
async def test_unexplained_delay_warns_in_draft_and_blocks_submit(client, admin_auth, project_id) -> None:
    _, header = admin_auth
    report = await _create(client, header, project_id, delay_hours=4)
    assert [w["rule_id"] for w in report["validation_warnings"]] == ["fieldreports.delay_explained"]
    resp = await client.post(f"{BASE}/reports/{report['id']}/submit/", headers=header)
    assert resp.status_code == 422 and "fieldreports.delay_explained" in _rule_ids(resp)
    fixed = await client.patch(
        f"{BASE}/reports/{report['id']}", json={"delays": "Crane out of service"}, headers=header
    )
    assert fixed.status_code == 200, fixed.text
    assert fixed.json()["validation_warnings"] == []
    ok = await client.post(f"{BASE}/reports/{report['id']}/submit/", headers=header)
    assert ok.status_code == 200, ok.text


@pytest.mark.asyncio
async def test_future_date_is_a_draft_warning(client, admin_auth, project_id) -> None:
    _, header = admin_auth
    report = await _create(client, header, project_id, report_date="2031-01-02")
    assert [w["rule_id"] for w in report["validation_warnings"]] == ["fieldreports.date_not_future"]


@pytest.mark.asyncio
async def test_workforce_log_over_a_day_is_refused_with_the_rule_code(client, admin_auth, project_id) -> None:
    _, header = admin_auth
    report = await _create(client, header, project_id)
    ok = await client.post(
        f"{BASE}/reports/{report['id']}/workforce/",
        json={"field_report_id": report["id"], "worker_type": "Mason", "headcount": 4, "hours_worked": "32"},
        headers=header,
    )
    assert ok.status_code == 201, ok.text
    bad = await client.post(
        f"{BASE}/reports/{report['id']}/workforce/",
        json={
            "field_report_id": report["id"],
            "worker_type": "Mason",
            "headcount": 2,
            "hours_worked": "60",
            "overtime_hours": "4",
        },
        headers=header,
    )
    assert bad.status_code == 422, bad.text
    assert "fieldreports.workforce_hours_plausible" in _rule_ids(bad)
    patch = await client.patch(f"{BASE}/workforce/{ok.json()['id']}", json={"hours_worked": "200"}, headers=header)
    assert patch.status_code == 422 and "fieldreports.workforce_hours_plausible" in _rule_ids(patch)


@pytest.mark.asyncio
async def test_equipment_log_over_a_day_is_refused(client, admin_auth, project_id) -> None:
    _, header = admin_auth
    report = await _create(client, header, project_id)
    bad = await client.post(
        f"{BASE}/reports/{report['id']}/equipment/",
        json={
            "field_report_id": report["id"],
            "equipment_description": "Tower crane",
            "hours_operational": "20",
            "hours_standby": "6",
        },
        headers=header,
    )
    assert bad.status_code == 422, bad.text
    assert "fieldreports.equipment_hours_plausible" in _rule_ids(bad)
    ok = await client.post(
        f"{BASE}/reports/{report['id']}/equipment/",
        json={
            "field_report_id": report["id"],
            "equipment_description": "Tower crane",
            "hours_operational": "8",
            "hours_standby": "2",
        },
        headers=header,
    )
    assert ok.status_code == 201, ok.text


@pytest.mark.asyncio
async def test_a_legacy_violating_report_stays_editable(client, admin_auth, project_id) -> None:
    from sqlalchemy import text

    from app.database import async_session_factory

    _, header = admin_auth
    report = await _create(client, header, project_id, workforce=[{"trade": "Mason", "count": 2, "hours": 8}])
    async with async_session_factory() as session:
        await session.execute(
            text("UPDATE oe_fieldreports_report SET workforce = CAST(:w AS json) WHERE id = :i"),
            {"w": '[{"trade": "Mason", "count": 2, "hours": 90}]', "i": report["id"]},
        )
        await session.commit()
    resp = await client.patch(f"{BASE}/reports/{report['id']}", json={"notes": "Site meeting held"}, headers=header)
    assert resp.status_code == 200, resp.text
    # A new violation introduced by the edit is still refused.
    worse = await client.patch(
        f"{BASE}/reports/{report['id']}",
        json={"workforce": [{"trade": "Mason", "count": 2, "hours": 30}]},
        headers=header,
    )
    assert worse.status_code == 422, worse.text


@pytest.mark.asyncio
async def test_import_runs_the_rules_and_reports_the_row(client, admin_auth, project_id) -> None:
    _, header = admin_auth
    csv_text = "report_date,work_performed\n2026-11-02,Backfill trench\n2026-11-01,Screed level 1\n"
    resp = await client.post(
        f"{BASE}/reports/import/file/?project_id={project_id}",
        files={"file": ("reports.csv", io.BytesIO(csv_text.encode()), "text/csv")},
        headers=header,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["imported"] == 2
