# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠What the running app loads at startup, not what the fixtures load.

The credentials module shipped with validation rules that ``on_startup`` never
registered. Its conftest registered them by hand, so seventy-two tests ran
against a rule set that did not exist in the running application and every one
of them passed. That is the most expensive shape of bug available here, because
the test suite actively conceals it.

So these assertions are made against ``on_startup`` itself with both registrars
monkeypatched. The suite's own fixture registering the rules cannot make them
pass, and removing either call from the hook fails them.
"""

from __future__ import annotations

import pytest

from app.modules import timeline
from app.modules.timeline.validators import TIMELINE_RULE_SET, register_timeline_rules


@pytest.mark.asyncio
async def test_on_startup_registers_the_subscriber_and_the_rules(monkeypatch) -> None:
    """Both registrars must be called, and the assertion names which is missing."""
    called: list[str] = []

    import app.modules.timeline.events as events_module
    import app.modules.timeline.validators as validators_module

    monkeypatch.setattr(
        events_module,
        "register_timeline_subscribers",
        lambda: called.append("subscriber"),
    )
    monkeypatch.setattr(
        validators_module,
        "register_timeline_rules",
        lambda: called.append("rules"),
    )

    await timeline.on_startup()

    assert called == ["subscriber", "rules"]


def test_the_rule_set_is_not_empty_once_registered() -> None:
    """A rule set nobody registered reports as *unsupported*, not as clean.

    The engine cannot tell the caller apart from "ran and found nothing", so an
    empty set is the failure that looks most like success. Assert the rules are
    actually reachable through the registry by name.
    """
    from app.core.validation.engine import rule_registry

    register_timeline_rules()
    rules = rule_registry.get_rules_for_sets([TIMELINE_RULE_SET])

    assert rules, f"the {TIMELINE_RULE_SET!r} rule set resolves to no rules at all"
    found = {r.rule_id for r in rules}
    assert {
        "timeline.unroutable_entry",
        "timeline.entry_without_entity",
        "timeline.unattributed_entry",
    } <= found, f"missing rules; registry has {sorted(found)}"


def test_registering_twice_leaves_one_copy_of_each_rule() -> None:
    """Startup plus the test fixture must not double-register."""
    from app.core.validation.engine import rule_registry

    register_timeline_rules()
    register_timeline_rules()
    rules = rule_registry.get_rules_for_sets([TIMELINE_RULE_SET])

    ids = [r.rule_id for r in rules if r.rule_id.startswith("timeline.")]
    assert len(ids) == len(set(ids)), f"duplicate rule registrations: {sorted(ids)}"
