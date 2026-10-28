# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The running application loads the saved-views rules, not just the tests.

A rule registered at import time is registered the moment anything in the test
process imports the module that defines it - including a fixture, a conftest, or
an unrelated test that pulled in the service. A suite can therefore be entirely
green over a module whose rules the real application never loads at all, because
the tests did the registration the application was supposed to do.

So this file does not ask "are the rules registered". It empties the rule set
first, boots the application the way it boots in production - the module loader
walking the manifests and calling each package's ``on_startup`` - and then asks
whether they came back. If the only registration route were the import that has
already happened, they would not.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from app.core.validation.engine import rule_registry
from app.modules.saved_views.validators import SAVED_VIEWS_RULE_SET

#: Every rule id the module is expected to put into the registry.
EXPECTED_RULE_IDS = {
    "saved_views.entity_registered",
    "saved_views.spec_parses",
    "saved_views.fields_whitelisted",
    "saved_views.field_capability",
    "saved_views.enum_values_current",
    "saved_views.share_scope_known",
    "saved_views.team_share_has_team",
    "saved_views.shared_view_pinned",
    "saved_views.within_complexity_budget",
    "saved_views.page_size_within_cap",
    "saved_views.spec_is_not_empty",
    "saved_views.shared_view_described",
}


@pytest_asyncio.fixture
async def booted_with_an_empty_rule_set():
    """Empty the rule set, boot the real app, hand back what the registry holds.

    Emptying first is the whole point. The rules are also registered at import,
    and this process has certainly imported the module by now, so a check that
    skipped this step would pass whether or not ``on_startup`` did anything.
    """
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    rule_registry.unregister_rule_set(SAVED_VIEWS_RULE_SET)
    assert not rule_registry.get_rules_for_sets([SAVED_VIEWS_RULE_SET]), (
        "the rule set survived unregister_rule_set, so this test cannot tell the two routes apart"
    )

    app = create_app()
    async with app.router.lifespan_context(app):
        yield rule_registry.get_rules_for_sets([SAVED_VIEWS_RULE_SET])


@pytest.mark.asyncio
async def test_booting_the_application_registers_every_saved_views_rule(
    booted_with_an_empty_rule_set,
) -> None:
    """The module loader's ``on_startup`` call is what has to put them back."""
    loaded = {rule.rule_id for rule in booted_with_an_empty_rule_set}
    assert loaded == EXPECTED_RULE_IDS, (
        f"missing after a real boot: {sorted(EXPECTED_RULE_IDS - loaded)}; "
        f"unexpected: {sorted(loaded - EXPECTED_RULE_IDS)}"
    )


@pytest.mark.asyncio
async def test_the_engine_answers_to_the_rule_set_name_after_a_boot(
    booted_with_an_empty_rule_set,
) -> None:
    """Registered is not enough; the engine has to reach them by the name callers use.

    A rule set registered under one name and requested under another runs
    nothing and reports nothing, which reads exactly like a view with no
    problems.
    """
    assert booted_with_an_empty_rule_set, "nothing registered, so the name check below proves nothing"

    from app.core.validation.engine import validation_engine

    report = await validation_engine.validate(
        data={"scope": "view", "entity_type": "project", "spec": {}, "share_scope": "private"},
        rule_sets=[SAVED_VIEWS_RULE_SET],
        target_type="saved_view",
        target_id=None,
    )
    assert SAVED_VIEWS_RULE_SET not in report.unsupported_rule_sets
