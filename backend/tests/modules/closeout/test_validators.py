"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Closeout validation rule tests."""

from __future__ import annotations

import pytest

from app.core.validation.engine import RuleCategory, Severity, ValidationContext
from app.modules.closeout.validators import (
    CloseoutCompletenessRule,
    CloseoutEvidenceRule,
    register_closeout_validation_rules,
)

pytestmark = pytest.mark.asyncio


def _ctx(slots):
    return ValidationContext(data={"slots": slots})


async def test_completeness_rule_fails_on_unbound_required_slot():
    rule = CloseoutCompletenessRule()
    results = await rule.validate(
        _ctx(
            [
                {"slot_key": "as_built", "title": "As-built", "is_required": True, "status": "empty"},
                {"slot_key": "warranty", "title": "Warranty", "is_required": True, "status": "verified"},
            ]
        )
    )
    by_slot = {r.element_ref: r for r in results}
    assert by_slot["as_built"].passed is False
    assert by_slot["as_built"].severity == Severity.ERROR
    assert by_slot["warranty"].passed is True


async def test_completeness_rule_ignores_optional_and_generated_slots():
    rule = CloseoutCompletenessRule()
    results = await rule.validate(
        _ctx(
            [
                {"slot_key": "epc", "title": "EPC", "is_required": False, "status": "empty"},
                {
                    "slot_key": "cobie",
                    "title": "COBie",
                    "is_required": True,
                    "status": "empty",
                    "source_kind": "generated",
                    "generated_artifact": "cobie_xlsx",
                },
            ]
        )
    )
    # Optional slot skipped; generated slot is not a binding gap -> no results.
    assert results == []


async def test_evidence_rule_warns_on_unverified_binding():
    rule = CloseoutEvidenceRule()
    assert rule.severity == Severity.WARNING
    assert rule.category == RuleCategory.CONSISTENCY
    results = await rule.validate(
        _ctx(
            [
                {"slot_key": "warranty", "title": "Warranty", "is_required": True, "status": "bound"},
                {"slot_key": "as_built", "title": "As-built", "is_required": True, "status": "verified"},
                {"slot_key": "om", "title": "O&M", "is_required": True, "status": "empty"},
            ]
        )
    )
    by_slot = {r.element_ref: r for r in results}
    assert by_slot["warranty"].passed is False
    assert by_slot["as_built"].passed is True
    # Empty slots are not double-flagged by the evidence rule.
    assert "om" not in by_slot


async def test_register_rules_lands_in_registry():
    from app.core.validation.engine import rule_registry

    register_closeout_validation_rules()
    assert rule_registry.get_rule("closeout.completeness") is not None
    assert rule_registry.get_rule("closeout.evidence_verified") is not None
