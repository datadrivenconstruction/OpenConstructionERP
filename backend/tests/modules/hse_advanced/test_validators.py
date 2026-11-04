# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""HSE rule set: each rule fires, a valid record passes, a blocking rule rejects the API write."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from app.core.validation.engine import Severity, ValidationContext, rule_registry
from app.modules.hse_advanced.permissions import register_hse_advanced_permissions
from app.modules.hse_advanced.router import router as hse_router
from app.modules.hse_advanced.validators import (
    HSE_RULE_SET,
    CapaTargetDateRule,
    CertificationDatesRule,
    PermitWindowRule,
    PPEDatesRule,
    ToolboxNotFutureRule,
    register_hse_validation_rules,
)
from tests._pg import transactional_session
from tests.modules._site_api import build_app, http, make_project

pytestmark = pytest.mark.asyncio

NOW = datetime.now(UTC)
TODAY = NOW.date()


async def _run(rule: object, data: dict, locale: str = "en"):
    return await rule.validate(ValidationContext(data=data, metadata={"locale": locale}))


def _permit(kind: str, hours: int) -> dict:
    return {"permit": {"id": "p", "permit_type": kind, "work_start": NOW, "work_end": NOW + timedelta(hours=hours)}}


CASES = [
    (
        CertificationDatesRule,
        {"certification": {"id": "c", "issue_date": "2026-01-10", "valid_until": "2028-01-10"}},
        {"certification": {"id": "c", "issue_date": "2026-01-10", "valid_until": "2025-12-31"}},
    ),
    (
        PPEDatesRule,
        {
            "ppe": {
                "id": "x",
                "issued_at": NOW,
                "returned_at": NOW + timedelta(days=30),
                "valid_until": TODAY + timedelta(days=90),
            }
        },
        {"ppe": {"id": "x", "issued_at": NOW, "returned_at": NOW - timedelta(days=1)}},
    ),
    (PermitWindowRule, _permit("hot_work", 10), _permit("hot_work", 48)),
    (
        ToolboxNotFutureRule,
        {"talk": {"id": "t", "conducted_at": NOW}},
        {"talk": {"id": "t", "conducted_at": NOW + timedelta(days=7)}},
    ),
    (
        CapaTargetDateRule,
        {"capa": {"id": "k", "target_date": TODAY + timedelta(days=14)}},
        {"capa": {"id": "k", "target_date": TODAY - timedelta(days=14)}},
    ),
]


@pytest.mark.parametrize(("rule_cls", "good", "bad"), CASES, ids=lambda v: getattr(v, "__name__", ""))
async def test_rule_passes_and_fails(rule_cls: type, good: dict, bad: dict) -> None:
    rule = rule_cls()
    assert all(r.passed for r in await _run(rule, good))
    failed = [r for r in await _run(rule, bad) if not r.passed]
    assert failed
    assert "site." not in failed[0].message and "money." not in failed[0].message


async def test_partial_records_and_long_general_permit() -> None:
    for cls, _, _ in CASES:
        assert all(r.passed for r in await _run(cls(), {}))
    # A multi-day excavation permit is normal; only a shift-bound hazard is held to 24 hours.
    assert all(r.passed for r in await _run(PermitWindowRule(), _permit("excavation", 72)))
    assert not all(r.passed for r in await _run(PermitWindowRule(), _permit("excavation", 24 * 40)))


async def test_registration_and_severities() -> None:
    assert PermitWindowRule.severity == Severity.WARNING
    assert CapaTargetDateRule.severity == Severity.WARNING
    register_hse_validation_rules()
    ids = {r.rule_id for r in rule_registry.get_rules_for_sets([HSE_RULE_SET])}
    assert len(ids) == 5


async def test_message_follows_locale() -> None:
    fr = await _run(ToolboxNotFutureRule(), CASES[3][2], locale="fr")
    assert "futur" in fr[0].message


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator:
    register_hse_advanced_permissions()
    async with transactional_session() as s:
        yield s


async def test_api_blocks_with_coded_422_and_accepts_valid(db_session) -> None:
    uid, _ = await make_project(db_session)
    body = {
        "cert_type": "Working at height",
        "owner_name": "A. Mason",
        "issue_date": "2026-03-01",
        "valid_until": "2028-03-01",
    }
    async with http(build_app(db_session, uid, hse_router, "/v1/hse")) as c:
        r = await c.post("/v1/hse/certifications/", json={**body, "valid_until": "2026-02-01"})
        assert r.status_code == 422, r.text
        assert r.json()["detail"]["code"] == "hse_advanced.certification_dates"

        r = await c.post("/v1/hse/certifications/", json=body)
        assert r.status_code == 201, r.text
        cert_id = r.json()["id"]

        r = await c.patch(f"/v1/hse/certifications/{cert_id}", json={"valid_until": "2025-01-01"})
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "hse_advanced.certification_dates"

        r = await c.patch(f"/v1/hse/certifications/{cert_id}", json={"valid_until": "2029-03-01"})
        assert r.status_code == 200, r.text
