"""The validation registry must be populated before a test runs, not after it.

``register_builtin_rules()`` is called by the application lifespan, which no test
process starts. The autouse guard in ``conftest`` used to repopulate the registry
only in its teardown, so the *first* test in a process to ask for a rule set found
an empty registry. The engine answers that by marking the set unsupported and
returning a clean report, which reads exactly like "my rule passed" and is really
"nothing ran at all".

This file is the reachability gate for that. Run it on its own and it is the first
test in the process, which is the condition the bug needed:

    pytest tests/unit/test_validation_registry_populated.py
"""

from __future__ import annotations

import pytest

from app.core.validation.engine import validation_engine

#: Sets that ship built in and that other suites rely on being reachable.
EXPECTED_RULE_SETS = [
    # ``boq_quality`` is a shared set name: modules register into it too, so it
    # is the one entry here that can be present while the built-in pack is not.
    # It stays because suites request it, but it can never stand in for the
    # pack, which is why the rest of this list has to be checked alongside it.
    "boq_quality",
    "ai_estimator",
    "din276",
    # Inline BOQ-import validation asks for ``gaeb`` on any DACH project, and
    # it went missing on a shard while ``boq_quality`` was present.
    "gaeb",
    "pipeline",
    "procurement",
    "subcontract",
    "submittal",
    # The request-for-quotation rules split across two sets on purpose: one runs
    # when the package goes out, the other when an award is made against the bids
    # that came back. There is no single "rfq_bidding" set.
    "rfq_issue",
    "rfq_award",
    # Registered by a module's on_startup, which no test process runs. The
    # conftest guard calls every module registrar for that reason; before it
    # did, these existed only in files that registered them by hand and every
    # other file got a clean report from rules that never ran.
    "pay_application",
]


@pytest.mark.parametrize("rule_set", EXPECTED_RULE_SETS)
def test_the_registry_is_populated_before_the_first_test_body(rule_set: str) -> None:
    """A rule set is reachable without any other test having run first."""
    available = validation_engine.registry.list_rule_sets()
    assert rule_set in available, (
        f"{rule_set!r} is not in the registry at test start. The registry holds "
        f"{sorted(available)!r}. A rule in a missing set never executes and the engine "
        f"reports a clean result, so this failure is silent everywhere else."
    )


def test_every_registered_rule_carries_a_rule_id() -> None:
    """Guard against a rule landing in the registry without an id to look up.

    A blank id resolves no message key, and the translate helper answers a missing
    key by humanising it, so the finding would render as plausible English rather
    than raising.
    """
    rules = validation_engine.registry.get_rules_for_sets(EXPECTED_RULE_SETS)
    assert rules, "no rules registered for the built-in sets"
    missing = [type(rule).__name__ for rule in rules if not getattr(rule, "rule_id", "")]
    assert not missing, f"rules registered without a rule_id: {missing}"
