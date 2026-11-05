"""The rule engine answers in the request language when the caller passes no locale."""

import pytest

from app.core.i18n import set_locale
from app.core.validation.engine import (
    RuleCategory,
    RuleRegistry,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationEngine,
    ValidationRule,
)


class _Echo(ValidationRule):
    rule_id = "t.echo"
    name = "echo"
    standard = "t"
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=False,
                message=str(context.metadata.get("locale")),
            )
        ]


async def _run(metadata=None):
    reg = RuleRegistry()
    reg.register(_Echo(), ["t"])
    report = await ValidationEngine(reg).validate({}, ["t"], metadata=metadata)
    return report.errors[0].message


@pytest.mark.asyncio
async def test_defaults_to_request_locale():
    set_locale("de")
    try:
        assert await _run() == "de"
    finally:
        set_locale("en")


@pytest.mark.asyncio
async def test_explicit_locale_wins():
    set_locale("de")
    try:
        assert await _run({"locale": "fr"}) == "fr"
    finally:
        set_locale("en")
