# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Subcontractor insurance: alert buckets, the mandatory-lapse gate and its rules​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.core.validation.engine import validation_engine
from app.modules.subcontractors import insurance_rules
from app.modules.subcontractors.insurance import (
    alert_bucket,
    certificate_payload,
    lapsed_mandatory_reasons,
    overall_status,
    override_covers,
)

TODAY = date(2026, 10, 26)


def _cert(cert_type: str, days: int | None, *, mandatory: bool = True, revoked: bool = False, **kw):
    return SimpleNamespace(
        id=uuid.uuid4(),
        subcontractor_id=uuid.uuid4(),
        cert_type=cert_type,
        is_mandatory=mandatory,
        revoked=revoked,
        valid_until=TODAY + timedelta(days=days) if days is not None else None,
        issue_date=kw.get("issue_date"),
        policy_number=kw.get("policy_number", "P-1"),
        coverage_amount=kw.get("coverage_amount", 1000),
        coverage_currency="EUR",
        issued_by="Insurer",
    )


@pytest.mark.parametrize(
    ("days", "bucket"),
    [(45, "valid"), (30, "due_30"), (15, "due_30"), (14, "due_14"), (1, "due_14"), (0, "due_0"), (-1, "expired")],
)
def test_alert_buckets_at_30_14_0(days: int, bucket: str) -> None:
    assert alert_bucket(TODAY + timedelta(days=days), TODAY) == bucket


def test_no_expiry_is_valid_and_revoked_wins() -> None:
    assert alert_bucket(None, TODAY) == "valid"
    assert alert_bucket(TODAY + timedelta(days=100), TODAY, revoked=True) == "revoked"


def test_expired_mandatory_blocks_but_renewal_clears() -> None:
    old = _cert("employers_liability", -5)
    assert lapsed_mandatory_reasons([old], TODAY) == [
        f"expired_mandatory_certificate:employers_liability:{(TODAY - timedelta(days=5)).isoformat()}"
    ]
    renewed = _cert("employers_liability", 360)
    assert lapsed_mandatory_reasons([old, renewed], TODAY) == []


def test_non_mandatory_lapse_does_not_block() -> None:
    assert lapsed_mandatory_reasons([_cert("professional_indemnity", -30, mandatory=False)], TODAY) == []


def test_override_covers_only_named_lapses() -> None:
    assert override_covers(["a", "b"], ["a"])
    assert not override_covers(["a"], ["a", "b"])
    assert not override_covers(["a"], [])


def test_overall_status() -> None:
    certs = [certificate_payload(_cert("public_liability", 10), TODAY)]
    assert overall_status(certs, blocked=False) == "expiring"
    assert overall_status(certs, blocked=True) == "non_compliant"
    assert overall_status([certificate_payload(_cert("public_liability", 300), TODAY)], blocked=False) == "compliant"


@pytest.mark.asyncio
async def test_insurance_rules_error_on_lapse_and_warn_on_expiry() -> None:
    insurance_rules.register_insurance_rules()
    certs = [
        certificate_payload(_cert("employers_liability", -3), TODAY),
        certificate_payload(_cert("contractors_all_risk", 11), TODAY),
        certificate_payload(_cert("public_liability", 200, policy_number=None), TODAY),
    ]
    report = await validation_engine.validate(
        {"as_of": TODAY.isoformat(), "certificates": certs},
        rule_sets=[insurance_rules.RULE_SET],
        metadata={"locale": "ru"},
    )
    failed = [(r.rule_id, r.severity.value) for r in report.results if not r.passed]
    assert ("subcontractor_insurance.mandatory_certificate_valid", "error") in failed
    assert ("subcontractor_insurance.certificate_expiring", "warning") in failed
    assert ("subcontractor_insurance.policy_details_recorded", "warning") in failed
    lapse = next(r for r in report.results if r.rule_id.endswith("mandatory_certificate_valid") and not r.passed)
    assert "Ответственность работодателя" in lapse.message
