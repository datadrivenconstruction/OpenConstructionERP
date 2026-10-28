"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Positive control: the design_options rule set is really registered.

Every other validation test in this suite is only meaningful when the six rules
are in the process-global registry. When they are not, the engine resolves
``design_options`` as an unsupported rule set, runs nothing, and returns a clean
report - which reads exactly like "the rules ran and found no problem". These
tests fail loudly in that situation so the rest of the suite cannot quietly
degrade into proving nothing.
"""

from __future__ import annotations

import pytest

from app.core.validation.engine import RuleCategory, Severity, rule_registry, validation_engine
from app.modules.design_options.validators import DESIGN_OPTIONS_RULE_SET

EXPECTED_RULES = {
    "design_options.gfa_present": (Severity.ERROR, RuleCategory.COMPLETENESS),
    "design_options.priced_complete": (Severity.WARNING, RuleCategory.COMPLETENESS),
    "design_options.gfa_consistent": (Severity.WARNING, RuleCategory.CONSISTENCY),
    "design_options.scope_coverage": (Severity.WARNING, RuleCategory.COMPLETENESS),
    "design_options.unit_consistency": (Severity.ERROR, RuleCategory.CONSISTENCY),
    "design_options.currency_consistent": (Severity.ERROR, RuleCategory.CONSISTENCY),
}


def test_rule_set_holds_exactly_the_six_module_rules() -> None:
    """The rule set exists and carries all six rules, no more and no fewer."""
    rule_sets = rule_registry.list_rule_sets()
    assert DESIGN_OPTIONS_RULE_SET in rule_sets, (
        "the design_options rule set is missing from the registry; every rule test in "
        "this suite would pass without running a single rule"
    )
    assert rule_sets[DESIGN_OPTIONS_RULE_SET] == len(EXPECTED_RULES)

    registered = {r["rule_id"] for r in rule_registry.list_rules(DESIGN_OPTIONS_RULE_SET)}
    assert registered == set(EXPECTED_RULES)


@pytest.mark.parametrize(("rule_id", "expected"), sorted(EXPECTED_RULES.items()))
def test_each_rule_resolves_with_its_declared_severity(
    rule_id: str,
    expected: tuple[Severity, RuleCategory],
) -> None:
    """Each rule body is retrievable and keeps its declared severity/category."""
    rule = rule_registry.get_rule(rule_id)
    assert rule is not None
    severity, category = expected
    assert rule.severity == severity
    assert rule.category == category
    assert rule.standard == DESIGN_OPTIONS_RULE_SET
    assert rule.enabled is True


def test_engine_treats_the_rule_set_as_supported() -> None:
    """``resolve_rule_sets`` must not bucket design_options as unsupported."""
    supported, unsupported = validation_engine.registry.resolve_rule_sets([DESIGN_OPTIONS_RULE_SET])
    assert supported == [DESIGN_OPTIONS_RULE_SET]
    assert unsupported == []
