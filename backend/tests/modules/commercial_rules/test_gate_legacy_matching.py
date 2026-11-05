"""gate_rule_set spares a legacy error only when the same record part still carries it."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.quality_rules import QualityRule, gate_rule_set

SET = "gate_probe"


class _PerItem(QualityRule):
    rule_id = "gate_probe.item_ok"
    name = "probe"
    standard = SET
    severity = Severity.ERROR
    message_section = "contacts"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = []
        for item in context.data["rec"]["items"]:
            if item["bad"]:
                out.append(self.fail(context, "identity_missing", ref=item["ref"]))
        return out


@pytest.mark.asyncio
async def test_a_new_bad_item_is_not_masked_by_an_old_one_with_the_same_text():
    rule_registry.register(_PerItem(), [SET])
    kw = {
        "rule_set": SET,
        "key": "rec",
        "target_type": "t",
        "target_id": "1",
        "operation": "update",
        "subject": "probe",
        "error_code": "probe_invalid",
    }
    before = {"items": [{"ref": "a", "bad": True}, {"ref": "b", "bad": False}]}
    same = {"items": [{"ref": "a", "bad": True}, {"ref": "b", "bad": False}]}
    await gate_rule_set(same, before=before, **kw)  # legacy error on a stays editable
    worse = {"items": [{"ref": "a", "bad": True}, {"ref": "b", "bad": True}]}
    with pytest.raises(HTTPException) as exc:
        await gate_rule_set(worse, before=before, **kw)
    assert exc.value.status_code == 422
