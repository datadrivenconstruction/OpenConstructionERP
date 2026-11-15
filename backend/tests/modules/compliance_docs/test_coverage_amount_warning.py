"""An insurance or bond document without a coverage amount saves; the rule warns."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.core.validation.engine import Severity, ValidationContext, rule_registry
from app.modules.compliance_docs.schemas import ComplianceDocCreate
from app.modules.compliance_docs.validators import (
    COMPLIANCE_RULE_SET,
    CoverageAmountRecorded,
    coverage_findings,
    register_compliance_docs_rules,
)


class _Doc:
    def __init__(self, doc_type: str, coverage_amount: Decimal | None) -> None:
        self.doc_type = doc_type
        self.coverage_amount = coverage_amount


async def _run(doc_type: str, amount: object):
    ctx = ValidationContext(
        data={"compliance_doc": {"id": "d1", "doc_type": doc_type, "coverage_amount": amount}},
        metadata={"locale": "en"},
    )
    return await CoverageAmountRecorded().validate(ctx)


@pytest.mark.parametrize("doc_type", ["insurance_general_liability", "insurance_auto", "bond_payment", "bond_bid"])
def test_create_without_coverage_amount_is_accepted(doc_type):
    body = ComplianceDocCreate(
        project_id="00000000-0000-0000-0000-000000000001",
        doc_type=doc_type,
        name="Policy",
        effective_date=date(2026, 1, 1),
        expires_at=date(2027, 1, 1),
    )
    assert body.coverage_amount is None


@pytest.mark.parametrize("doc_type", ["insurance_auto", "bond_performance"])
async def test_rule_warns_when_coverage_amount_missing(doc_type):
    failed = [r for r in await _run(doc_type, None) if not r.passed]
    assert [r.severity for r in failed] == [Severity.WARNING]
    assert failed[0].rule_id == "compliance_docs.coverage_amount_recorded"
    assert "compliance_docs." not in failed[0].message


async def test_rule_passes_with_amount_and_for_other_types():
    assert all(r.passed for r in await _run("insurance_auto", "250000"))
    assert all(r.passed for r in await _run("permit_building", None))


def test_response_findings_follow_the_same_predicate():
    assert [f["severity"] for f in coverage_findings(_Doc("bond_bid", None))] == ["warning"]
    assert coverage_findings(_Doc("bond_bid", Decimal("1000"))) == []
    assert coverage_findings(_Doc("certification_safety", None)) == []


def test_rule_is_registered():
    register_compliance_docs_rules()
    ids = {r.rule_id for r in rule_registry.get_rules_for_sets([COMPLIANCE_RULE_SET])}
    assert "compliance_docs.coverage_amount_recorded" in ids
