# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The running application loads the full_evm rules, not just this test package.

``conftest.py`` registers the rule set by hand for every test here, and says why
in as many words: the application does it from ``on_startup``, which no test
process runs. That fixture is correct and should stay, but it means every other
test in this package would go on passing if the ``on_startup`` wiring were
deleted tomorrow. The suite would be measuring its own fixture.

So this file empties the rule set first, boots the application the way production
boots it, with the module loader walking the manifests and calling each package's
``on_startup``, and only then asks what the registry holds. Emptying is the load
bearing step: the rules are also registered as a side effect of importing
``validators``, and this process has certainly imported it by now, so a check
that skipped it would pass either way.

The stakes are in ``test_full_evm_vocabulary.py``: when this rule set resolves to
nothing, the engine does not raise, it returns a clean report with status
``unsupported``, and ``_apply_report`` writes that onto every baseline and
measurement it touches. A lost registration is therefore silent at the point of
failure and only visible in a column nobody reads.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from app.core.validation.engine import ValidationRule, rule_registry
from app.modules.full_evm.validators import FULL_EVM_RULE_SET


@pytest_asyncio.fixture
async def booted_with_an_empty_rule_set(
    _full_evm_rules_registered: None,
) -> AsyncIterator[list[ValidationRule]]:
    """Empty the rule set, boot the real app, hand back what the registry holds.

    ``_full_evm_rules_registered`` is the package conftest's autouse fixture,
    named here to pin the order rather than to use its effect. Both are function
    scoped, and pytest happens to run autouse first, but the dependency makes
    that guarantee explicit instead of incidental. Under the opposite order the
    conftest would re-register after the boot, and the second test below would
    pass with the ``on_startup`` wiring deleted, which is the one outcome this
    file exists to make impossible.
    """
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    rule_registry.unregister_rule_set(FULL_EVM_RULE_SET)
    assert not rule_registry.get_rules_for_sets([FULL_EVM_RULE_SET]), (
        "the rule set survived unregister_rule_set, so this test cannot tell the two routes apart"
    )

    app = create_app()
    async with app.router.lifespan_context(app):
        yield rule_registry.get_rules_for_sets([FULL_EVM_RULE_SET])


@pytest.mark.asyncio
async def test_booting_the_application_registers_the_full_evm_rules(
    booted_with_an_empty_rule_set: list[ValidationRule],
) -> None:
    """The module loader's ``on_startup`` call is what has to put them back.

    The count is asserted as a floor rather than an exact roster. This file is
    about the registration route existing at all; which rules the module ships
    is ``test_full_evm_validators.py``'s subject, and pinning the exact set in
    two places would make every new rule a two file change for no extra safety.
    """
    loaded = {rule.rule_id for rule in booted_with_an_empty_rule_set}
    assert loaded, "a real application boot registered no full_evm rules at all"
    assert all(rule_id.startswith("full_evm.") for rule_id in loaded), (
        f"rules registered under the full_evm set with foreign ids: "
        f"{sorted(r for r in loaded if not r.startswith('full_evm.'))}"
    )


@pytest.mark.asyncio
async def test_the_engine_answers_to_the_rule_set_name_after_a_boot(
    booted_with_an_empty_rule_set: list[ValidationRule],
) -> None:
    """Registered is not enough; the engine has to reach them by the name callers use.

    ``service.py`` asks for the set by ``FULL_EVM_RULE_SET``. A set registered
    under one name and requested under another runs nothing and reports nothing,
    which reads exactly like a baseline with no problems.
    """
    assert booted_with_an_empty_rule_set, "nothing registered, so the name check below proves nothing"

    from app.core.validation.engine import validation_engine

    report = await validation_engine.validate(
        data={"bac": "1000", "periods": [], "currency": "EUR"},
        rule_sets=[FULL_EVM_RULE_SET],
        target_type="evm_baseline",
        target_id=None,
    )
    assert FULL_EVM_RULE_SET not in report.unsupported_rule_sets
