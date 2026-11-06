"""The ``reporting`` rule set: each rule fires, valid records pass, writes are gated."""

from __future__ import annotations

import uuid

import pytest

from app.core.validation.engine import Severity, ValidationContext, rule_registry
from app.modules.reporting.models import KPISnapshot
from app.modules.reporting.validators import (
    REPORTING_RULE_SET,
    IndexValuesRule,
    OpenCountsRule,
    PercentValuesRule,
    ScheduleRecipientsRule,
    SnapshotDateRule,
    register_reporting_validation_rules,
)

TODAY = "2026-11-04"


def _kpi(**kw):
    base = {
        "id": "k1",
        "snapshot_date": "2026-11-03",
        "cpi": "0.97",
        "spi": "1.02",
        "risk_score_avg": "2.5",
        "budget_consumed_pct": "62",
        "schedule_progress_pct": "58",
        "open_defects": 4,
        "open_observations": 2,
        "open_rfis": 7,
        "open_submittals": 3,
    }
    return base | kw


def _schedule(**kw):
    return {
        "id": "s1",
        "is_scheduled": True,
        "schedule_cron": "0 9 * * 1",
        "recipients": ["pm@example.com"],
    } | kw


async def _run(rule, key, record, locale="en"):
    context = ValidationContext(data={key: record}, metadata={"locale": locale, "today": TODAY})
    return await rule().validate(context)


CASES = [
    (SnapshotDateRule, "kpi", _kpi(snapshot_date="2026-02-30"), "reporting.snapshot_date", Severity.ERROR),
    (SnapshotDateRule, "kpi", _kpi(snapshot_date="2999-01-01"), "reporting.snapshot_date", Severity.ERROR),
    (IndexValuesRule, "kpi", _kpi(cpi="abc"), "reporting.index_values", Severity.ERROR),
    (IndexValuesRule, "kpi", _kpi(spi="-1"), "reporting.index_values", Severity.ERROR),
    (PercentValuesRule, "kpi", _kpi(schedule_progress_pct="140"), "reporting.percent_values", Severity.ERROR),
    (PercentValuesRule, "kpi", _kpi(budget_consumed_pct="-5"), "reporting.percent_values", Severity.ERROR),
    (PercentValuesRule, "kpi", _kpi(budget_consumed_pct="118"), "reporting.percent_values", Severity.WARNING),
    (OpenCountsRule, "kpi", _kpi(open_rfis=-2), "reporting.open_counts", Severity.ERROR),
    (
        ScheduleRecipientsRule,
        "schedule",
        _schedule(recipients=["not-an-address@"]),
        "reporting.schedule_recipients",
        Severity.ERROR,
    ),
    (ScheduleRecipientsRule, "schedule", _schedule(recipients=[]), "reporting.schedule_recipients", Severity.ERROR),
]
VALID = {"kpi": _kpi(), "schedule": _schedule()}


@pytest.mark.asyncio
@pytest.mark.parametrize(("rule", "key", "bad", "rule_id", "severity"), CASES)
async def test_rule_fires_on_a_violation_and_passes_a_valid_record(rule, key, bad, rule_id, severity):
    failed = [r for r in await _run(rule, key, bad) if not r.passed]
    assert [r.rule_id for r in failed] == [rule_id]
    assert failed[0].severity == severity
    assert "{" not in failed[0].message
    assert all(r.passed for r in await _run(rule, key, VALID[key]))


@pytest.mark.asyncio
async def test_absent_figures_a_paused_schedule_and_user_id_recipients_pass():
    blanks = _kpi(cpi=None, spi="", budget_consumed_pct=None, schedule_progress_pct=None, risk_score_avg=None)
    for rule in (IndexValuesRule, PercentValuesRule):
        assert all(r.passed for r in await _run(rule, "kpi", blanks))
    assert all(
        r.passed for r in await _run(ScheduleRecipientsRule, "schedule", _schedule(is_scheduled=False, recipients=[]))
    )
    assert all(r.passed for r in await _run(ScheduleRecipientsRule, "schedule", _schedule(recipients=["8a1c-user-id"])))


@pytest.mark.asyncio
async def test_message_is_translated():
    failed = [r for r in await _run(SnapshotDateRule, "kpi", CASES[1][2], "de") if not r.passed]
    assert "Zukunft" in failed[0].message


def test_rule_set_is_registered():
    register_reporting_validation_rules()
    assert len({r.rule_id for r in rule_registry.get_rules_for_sets([REPORTING_RULE_SET])}) == 5


# -- write points --------------------------------------------------------------------------------------

BASE = "/api/v1/reporting"


def _snapshot(project_id, **over):
    return {
        "project_id": project_id,
        "snapshot_date": "2026-11-03",
        "cpi": "0.97",
        "spi": "1.02",
        "budget_consumed_pct": "62",
        "schedule_progress_pct": "58",
        "open_defects": 4,
    } | over


@pytest.mark.asyncio
async def test_a_snapshot_with_a_bad_date_or_figure_is_refused_with_its_code(client, admin_auth, project_id):
    _, h = admin_auth
    for over, code in (
        ({"snapshot_date": "2999-01-01"}, "reporting.snapshot_date"),
        ({"snapshot_date": "yesterday"}, "reporting.snapshot_date"),
        ({"cpi": "n/a"}, "reporting.index_values"),
        ({"schedule_progress_pct": "180"}, "reporting.percent_values"),
        ({"open_defects": -1}, "reporting.open_counts"),
    ):
        resp = await client.post(f"{BASE}/kpi/snapshot/", json=_snapshot(project_id, **over), headers=h)
        assert resp.status_code == 422, resp.text
        detail = resp.json()["detail"]
        assert detail["error"] == "reporting_rules_failed"
        assert detail["code"] == code
    ok = await client.post(f"{BASE}/kpi/snapshot/", json=_snapshot(project_id), headers=h)
    assert ok.status_code == 201, ok.text
    assert ok.json()["validation_warnings"] == []


@pytest.mark.asyncio
async def test_an_over_budget_snapshot_is_saved_with_a_warning(client, admin_auth, project_id):
    _, h = admin_auth
    resp = await client.post(
        f"{BASE}/kpi/snapshot/",
        json=_snapshot(project_id, snapshot_date="2026-10-01", budget_consumed_pct="112"),
        headers=h,
    )
    assert resp.status_code == 201, resp.text
    assert [w["rule_id"] for w in resp.json()["validation_warnings"]] == ["reporting.percent_values"]


@pytest.mark.asyncio
async def test_re_posting_a_day_whose_stored_figure_was_already_bad_is_not_blocked_by_it(
    client, admin_auth, project_id
):
    from sqlalchemy import update

    from app.database import async_session_factory

    _, h = admin_auth
    ok = await client.post(f"{BASE}/kpi/snapshot/", json=_snapshot(project_id, snapshot_date="2026-09-01"), headers=h)
    assert ok.status_code == 201, ok.text
    async with async_session_factory() as session:
        await session.execute(update(KPISnapshot).where(KPISnapshot.id == uuid.UUID(ok.json()["id"])).values(cpi="n/a"))
        await session.commit()
    again = await client.post(
        f"{BASE}/kpi/snapshot/", json=_snapshot(project_id, snapshot_date="2026-09-01", cpi="n/a"), headers=h
    )
    assert again.status_code == 201, again.text
    worse = await client.post(
        f"{BASE}/kpi/snapshot/", json=_snapshot(project_id, snapshot_date="2026-09-01", spi="n/a"), headers=h
    )
    assert worse.status_code == 422, worse.text


@pytest.mark.asyncio
async def test_a_schedule_needs_real_recipients(client, admin_auth, project_id):
    _, h = admin_auth
    made = await client.post(
        f"{BASE}/templates/",
        json={"name": "Weekly status", "report_type": "project_status"},
        headers=h,
    )
    assert made.status_code == 201, made.text
    url = f"{BASE}/templates/{made.json()['id']}/schedule/"
    bare = await client.post(url, json={"schedule_cron": "0 9 * * 1", "recipients": []}, headers=h)
    assert bare.status_code == 422, bare.text
    assert bare.json()["detail"]["code"] == "reporting.schedule_recipients"
    bad = await client.post(url, json={"schedule_cron": "0 9 * * 1", "recipients": ["pm@"]}, headers=h)
    assert bad.status_code == 422, bad.text
    ok = await client.post(url, json={"schedule_cron": "0 9 * * 1", "recipients": ["pm@example.com"]}, headers=h)
    assert ok.status_code == 200, ok.text
    assert ok.json()["validation_warnings"] == []
    paused = await client.post(url, json={"schedule_cron": None, "recipients": []}, headers=h)
    assert paused.status_code == 200, paused.text
