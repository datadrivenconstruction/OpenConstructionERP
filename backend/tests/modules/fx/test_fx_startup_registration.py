# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The running application loads the fx rules, not just this test package.

``conftest.py`` registers the rule set by hand for every test here and states the
reason plainly: the application registers them from ``on_startup``, which no test
process runs, so without the fixture the ``fx`` set would resolve to zero rules
and the engine would report it unsupported, which is indistinguishable from the
rules running and finding nothing. The fixture is right to exist. The cost is
that every other test in this package would keep passing if the ``on_startup``
wiring were removed, because the fixture would go on doing the application's job.

This file closes that gap. It empties the rule set, boots the application the way
production boots it, with the module loader walking manifests and calling each
package's ``on_startup``, and then asks the registry what came back. Emptying
first is what makes the answer mean anything: the rules are also registered as a
side effect of importing ``validators``, which this process has certainly done.

For fx the damage from a lost registration is quieter than a crash. The report is
what tells an estimator that the project's reporting currency is not quoted by
the set it prices against, or that a pinned set was left unlocked. With no rules
registered that report comes back clean, and the figures it was supposed to
question ship looking checked.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from app.core.validation.engine import ValidationRule, rule_registry
from app.modules.fx.validators import FX_RULE_SET


@pytest_asyncio.fixture
async def booted_with_an_empty_rule_set() -> AsyncIterator[list[ValidationRule]]:
    """Empty the rule set, boot the real app, hand back what the registry holds.

    No ordering dependency on the package conftest is declared here, unlike the
    ``full_evm`` counterpart: ``_fx_module_registered`` is session scoped, so it
    has already run before any function-scoped fixture and cannot land after the
    boot.
    """
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    rule_registry.unregister_rule_set(FX_RULE_SET)
    assert not rule_registry.get_rules_for_sets([FX_RULE_SET]), (
        "the rule set survived unregister_rule_set, so this test cannot tell the two routes apart"
    )

    app = create_app()
    async with app.router.lifespan_context(app):
        yield rule_registry.get_rules_for_sets([FX_RULE_SET])


@pytest.mark.asyncio
async def test_booting_the_application_registers_the_fx_rules(
    booted_with_an_empty_rule_set: list[ValidationRule],
) -> None:
    """The module loader's ``on_startup`` call is what has to put them back."""
    loaded = {rule.rule_id for rule in booted_with_an_empty_rule_set}
    assert loaded, "a real application boot registered no fx rules at all"
    assert all(rule_id.startswith("fx.") for rule_id in loaded), (
        f"rules registered under the fx set with foreign ids: {sorted(r for r in loaded if not r.startswith('fx.'))}"
    )


@pytest.mark.asyncio
async def test_the_engine_answers_to_the_rule_set_name_after_a_boot(
    booted_with_an_empty_rule_set: list[ValidationRule],
) -> None:
    """Registered is not enough; the engine has to reach them by the name callers use.

    ``FxService.validate_project`` asks for the set by ``FX_RULE_SET``. A set
    registered under one name and requested under another runs nothing and
    reports nothing, which reads exactly like a project with sound rates.
    """
    assert booted_with_an_empty_rule_set, "nothing registered, so the name check below proves nothing"

    from app.core.validation.engine import validation_engine

    report = await validation_engine.validate(
        data={"policy": None, "rates": {}, "quotes": []},
        rule_sets=[FX_RULE_SET],
        target_type="fx_policy",
        target_id=None,
    )
    assert FX_RULE_SET not in report.unsupported_rule_sets
