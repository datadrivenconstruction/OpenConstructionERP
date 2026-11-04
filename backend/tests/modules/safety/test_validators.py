# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Safety incident rule set: each rule fires, a valid record passes, a blocking rule rejects the API write."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from app.core.validation.engine import Severity, ValidationContext, rule_registry
from app.modules.safety.permissions import register_safety_permissions
from app.modules.safety.router import router as safety_router
from app.modules.safety.validators import (
    SAFETY_RULE_SET,
    ClosedNeedsRootCauseRule,
    FatalitySeverityRule,
    IncidentDateNotFutureRule,
    LostDaysNeedInjuryRule,
    RegulatorReportRule,
    register_safety_validation_rules,
)
from tests._pg import transactional_session
from tests.modules._site_api import build_app, http, make_project

pytestmark = pytest.mark.asyncio

TODAY = datetime.now(UTC).date()


def _inc(**kw: object) -> dict:
    base = {
        "id": "i1",
        "incident_date": TODAY.isoformat(),
        "incident_type": "injury",
        "severity": "moderate",
        "treatment_type": "medical",
        "days_lost": 2,
        "root_cause": "wet floor",
        "reported_to_regulator": False,
        "status": "reported",
    }
    base.update(kw)
    return {"incident": base}


async def _run(rule: object, data: dict, locale: str = "en"):
    return await rule.validate(ValidationContext(data=data, metadata={"locale": locale}))


CASES = [
    (IncidentDateNotFutureRule, _inc(), _inc(incident_date=(TODAY + timedelta(days=9)).isoformat())),
    (
        FatalitySeverityRule,
        _inc(treatment_type="fatality", severity="critical"),
        _inc(treatment_type="fatality", severity="minor"),
    ),
    (LostDaysNeedInjuryRule, _inc(), _inc(incident_type="near_miss", days_lost=3)),
    (RegulatorReportRule, _inc(), _inc(treatment_type="hospital")),
    (ClosedNeedsRootCauseRule, _inc(status="closed"), _inc(status="closed", severity="severe", root_cause="")),
]


@pytest.mark.parametrize(("rule_cls", "good", "bad"), CASES, ids=lambda v: getattr(v, "__name__", ""))
async def test_rule_passes_and_fails(rule_cls: type, good: dict, bad: dict) -> None:
    rule = rule_cls()
    assert all(r.passed for r in await _run(rule, good))
    failed = [r for r in await _run(rule, bad) if not r.passed]
    assert failed
    assert "site." not in failed[0].message


async def test_partial_record_does_not_false_positive() -> None:
    for cls, _, _ in CASES:
        assert all(r.passed for r in await _run(cls(), {"incident": {"id": "draft"}}))


async def test_severities_and_registration() -> None:
    assert RegulatorReportRule.severity == Severity.WARNING
    assert ClosedNeedsRootCauseRule.severity == Severity.WARNING
    register_safety_validation_rules()
    ids = {r.rule_id for r in rule_registry.get_rules_for_sets([SAFETY_RULE_SET])}
    assert len(ids) == 5


async def test_message_follows_locale() -> None:
    de = await _run(FatalitySeverityRule(), _inc(treatment_type="fatality", severity="minor"), locale="de")
    assert "widerspricht" in de[0].message


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator:
    register_safety_permissions()
    async with transactional_session() as s:
        yield s


async def test_api_blocks_with_coded_422_and_accepts_valid(db_session) -> None:
    uid, pid = await make_project(db_session)
    body = {
        "project_id": str(pid),
        "incident_date": TODAY.isoformat(),
        "incident_type": "injury",
        "severity": "minor",
        "treatment_type": "fatality",
        "description": "fall from scaffold",
    }
    async with http(build_app(db_session, uid, safety_router, "/v1/safety")) as c:
        r = await c.post("/v1/safety/incidents/", json=body)
        assert r.status_code == 422, r.text
        assert r.json()["detail"]["code"] == "safety.fatality_severity"

        r = await c.post("/v1/safety/incidents/", json={**body, "severity": "critical"})
        assert r.status_code == 201, r.text  # regulator warning does not block
        incident_id = r.json()["id"]

        r = await c.patch(f"/v1/safety/incidents/{incident_id}", json={"description": "fall from scaffold, level 3"})
        assert r.status_code == 200, r.text

        r = await c.patch(f"/v1/safety/incidents/{incident_id}", json={"incident_type": "near_miss", "days_lost": 4})
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "safety.lost_days_need_injury"
