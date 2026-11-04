# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Basis-of-estimate rule set: every rule fires, a valid document passes, and the write points enforce it."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import update

from app.core.validation.engine import ValidationContext
from app.database import async_session_factory
from app.modules.estimate_basis.models import EstimateBasis
from app.modules.estimate_basis.validators import (
    BasisAccuracyBandRule,
    BasisBudgetTargetRule,
    BasisFinalNeedsClassRule,
    BasisFinalRationaleRule,
    BasisPricingDateCurrentRule,
)
from tests.modules.ncr.conftest import admin_auth, app_instance, client, project_id  # noqa: F401

TODAY = "2026-11-04"


def _b(**kw: object) -> dict:
    base = {
        "id": "b1",
        "status": "final",
        "estimate_class": 3,
        "accuracy_low_pct": "-15.0",
        "accuracy_high_pct": "20.0",
        "market_conditions": "Steel prices rising",
        "contingency_rationale": "10 % for design maturity",
        "budget_target": {"type": "client_target", "amount": "2500000"},
        "pricing_date": "2026-09-01",
    }
    base.update(kw)
    return {"basis": base}


async def _run(rule: object, data: dict, locale: str = "en"):
    return await rule.validate(ValidationContext(data=data, metadata={"locale": locale, "today": TODAY}))


CASES = [
    (BasisFinalNeedsClassRule, _b(), _b(estimate_class=None)),
    (BasisAccuracyBandRule, _b(), _b(accuracy_low_pct="10")),
    (BasisAccuracyBandRule, _b(), _b(accuracy_high_pct="-5")),
    (BasisBudgetTargetRule, _b(), _b(budget_target={"type": "budget", "amount": "0"})),
    (BasisBudgetTargetRule, _b(), _b(budget_target={"type": "budget", "amount": "abc"})),
    (BasisFinalRationaleRule, _b(), _b(contingency_rationale=" ")),
    (BasisPricingDateCurrentRule, _b(), _b(pricing_date="2025-01-15")),
    (BasisPricingDateCurrentRule, _b(), _b(pricing_date=None)),
]


@pytest.mark.parametrize(("rule_cls", "good", "bad"), CASES)
async def test_rule_passes_and_fails(rule_cls: type, good: dict, bad: dict) -> None:
    rule = rule_cls()
    assert all(r.passed for r in await _run(rule, good))
    failed = [r for r in await _run(rule, bad) if not r.passed]
    assert failed
    assert "estimating." not in failed[0].message


async def test_draft_needs_none_of_the_sign_off_fields() -> None:
    draft = _b(status="draft", estimate_class=None, market_conditions="", pricing_date=None, budget_target=None)
    for rule in (BasisFinalNeedsClassRule, BasisFinalRationaleRule, BasisPricingDateCurrentRule, BasisBudgetTargetRule):
        assert (await _run(rule(), draft))[0].passed
    noted = _b(status="draft", budget_target={"type": "budget", "amount": "", "notes": "to be agreed"})
    assert (await _run(BasisBudgetTargetRule(), noted))[0].passed


async def test_message_follows_locale() -> None:
    de = await _run(BasisAccuracyBandRule(), _b(accuracy_low_pct="10"), locale="de")
    assert "Genauigkeitsspanne" in de[0].message


async def _make_doc(project_id: str, **kw: object) -> str:
    doc = EstimateBasis(
        project_id=uuid.UUID(project_id),
        title="Basis",
        status=kw.pop("status", "draft"),
        generated_at=date.today().isoformat(),
        **kw,
    )
    async with async_session_factory() as session:
        session.add(doc)
        await session.commit()
        return str(doc.id)


async def test_blocking_rule_rejects_api_edit_with_its_code(client, admin_auth, project_id) -> None:  # noqa: F811
    _, header = admin_auth
    doc_id = await _make_doc(project_id)
    resp = await client.put(f"/api/v1/estimate-basis/documents/{doc_id}", json={"status": "final"}, headers=header)
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["error"] == "estimate_basis_rules_failed"
    assert [e["rule_id"] for e in detail["errors"]] == ["estimate_basis.final_needs_class"]
    stored = await client.get(f"/api/v1/estimate-basis/documents/{doc_id}", headers=header)
    assert stored.json()["status"] == "draft"


async def test_signed_off_document_passes_and_reports_warnings(client, admin_auth, project_id) -> None:  # noqa: F811
    _, header = admin_auth
    stale = (date.today() - timedelta(days=500)).isoformat()
    doc_id = await _make_doc(project_id, pricing_date=stale)
    resp = await client.put(
        f"/api/v1/estimate-basis/documents/{doc_id}", json={"status": "final", "estimate_class": 3}, headers=header
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "final"
    assert {w["rule_id"] for w in body["validation_warnings"]} == {
        "estimate_basis.final_rationale",
        "estimate_basis.pricing_date_current",
    }


async def test_bad_budget_target_is_rejected(client, admin_auth, project_id) -> None:  # noqa: F811
    _, header = admin_auth
    doc_id = await _make_doc(project_id)
    resp = await client.put(
        f"/api/v1/estimate-basis/documents/{doc_id}",
        json={"budget_target": {"type": "budget", "amount": "-10"}},
        headers=header,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["errors"][0]["rule_id"] == "estimate_basis.budget_target_amount"


async def test_legacy_document_with_existing_violation_stays_editable(client, admin_auth, project_id) -> None:  # noqa: F811
    _, header = admin_auth
    doc_id = await _make_doc(project_id, status="final")
    async with async_session_factory() as session:
        await session.execute(update(EstimateBasis).where(EstimateBasis.id == uuid.UUID(doc_id)).values(estimate_class=None))
        await session.commit()
    resp = await client.put(f"/api/v1/estimate-basis/documents/{doc_id}", json={"title": "Renamed"}, headers=header)
    assert resp.status_code == 200, resp.text
    assert resp.json()["title"] == "Renamed"
