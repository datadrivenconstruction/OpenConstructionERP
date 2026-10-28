# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Shared fixtures for the Full EVM module tests."""

from __future__ import annotations

import pytest

from app.modules.full_evm.validators import register_full_evm_rules


@pytest.fixture(autouse=True)
def _full_evm_rules_registered() -> None:
    """Register the ``full_evm`` rule set for every test in this package.

    The application registers these from the module ``on_startup`` hook, which
    no test process runs. Without this the core engine would report the rule
    set as *unsupported* and hand back a clean report - indistinguishable from
    the rules having run and found nothing, which is exactly the false pass
    these tests exist to rule out.

    No teardown: registration is idempotent (the registry keys rules by id) and
    leaving the set in place cannot make another suite fail, whereas tearing it
    down mid-session could.
    """
    register_full_evm_rules()
