# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The bidder gate and the award rules, without a database.

The directory's award block verdict maps onto three rules: a blocked firm and
a lapsed certificate refuse the award, a certificate not on file only warns
(payment is held later). The pack names which certificates count.
"""

from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace

import pytest

from app.core.validation.engine import ValidationContext, rule_registry
from app.modules.subcontractors.service import subcontractor_award_block
from app.modules.tendering.award_terms import gate_from_verdict
from app.modules.tendering.validators import AWARD_RULE_SET, register_award_rules

pytestmark = pytest.mark.asyncio

PACK_TYPES = ("construction_tax_exemption", "social_security_clearance")


def _sub(**kw):
    base = {
        "id": uuid.uuid4(),
        "legal_name": "Drywall GmbH",
        "trade_name": None,
        "is_blocked": False,
        "prequalification_status": "approved",
    }
    return SimpleNamespace(**(base | kw))


def _cert(cert_type: str, valid_until: date | None, *, revoked: bool = False):
    return SimpleNamespace(
        cert_type=cert_type,
        valid_until=valid_until,
        revoked=revoked,
        status="revoked" if revoked else "valid",
        is_mandatory=True,
        issue_date=None,
        metadata_={},
    )


def _gate(sub, certs, required=PACK_TYPES):
    verdict = subcontractor_award_block(sub, certificates=certs, as_at=date(2026, 11, 19), required_types=required)
    return gate_from_verdict(sub, verdict, SimpleNamespace(source="pack", reference="DE"), required)


async def _run(gate) -> dict[str, list]:
    register_award_rules()
    rules = rule_registry.get_rules_for_sets([AWARD_RULE_SET])
    ctx = ValidationContext(data={"gate": gate.model_dump(mode="json"), "rounds_count": 0, "revisions_count": 0})
    out: dict[str, list] = {}
    for rule in rules:
        if rule.rule_id.startswith(("award.bidder", "award.evidence")):
            out[rule.rule_id] = [r for r in await rule.validate(ctx) if not r.passed]
    return out


async def test_a_blocked_firm_fails_the_blocked_rule_only() -> None:
    gate = _gate(_sub(is_blocked=True), [_cert(t, date(2027, 6, 30)) for t in PACK_TYPES])
    assert gate.blocked
    assert [f.rule_id for f in gate.findings] == ["award.bidder_blocked"]
    failed = await _run(gate)
    assert len(failed["award.bidder_blocked"]) == 1
    assert failed["award.evidence_expired"] == [] and failed["award.evidence_missing"] == []


async def test_a_lapsed_pack_certificate_blocks_and_a_missing_one_warns() -> None:
    gate = _gate(_sub(), [_cert("construction_tax_exemption", date(2026, 10, 31))])
    by_rule = {f.rule_id: f for f in gate.findings}
    assert by_rule["award.evidence_expired"].document_type == "construction_tax_exemption"
    assert by_rule["award.evidence_expired"].severity == "error"
    assert by_rule["award.evidence_missing"].document_type == "social_security_clearance"
    assert by_rule["award.evidence_missing"].severity == "warning"
    assert gate.blocked
    failed = await _run(gate)
    assert failed["award.evidence_missing"][0].severity == "warning"


async def test_a_firm_with_every_pack_certificate_passes() -> None:
    gate = _gate(_sub(), [_cert(t, date(2027, 6, 30)) for t in PACK_TYPES])
    assert gate.findings == []
    assert not gate.blocked
    assert gate.requirements_source == "pack"


async def test_insurance_is_not_demanded_when_the_pack_does_not_name_it() -> None:
    gate = _gate(_sub(), [_cert(t, date(2027, 6, 30)) for t in PACK_TYPES])
    assert all(f.document_type != "insurance" for f in gate.findings)
