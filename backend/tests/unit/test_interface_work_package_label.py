# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The work-package label recases keys and leaves written text alone.

The interface register printed "Lv 01" where the work package is "LV 01 -
Baustelleneinrichtung und Gemeinkosten". The label is built at seed time from a
subcontractor's first trade category, and that column holds two very different
kinds of string: the lowercase snake_case keys this module's own pool uses, and
whatever text a real register was set up with. ``str.title()`` is right for the
first and destroys the second, because it lowercases the tail of every word,
and an initialism does not survive that.

These cases are the two kinds side by side. The keys are asserted as well as the
free text, because a guard that only stopped the folding would also have stopped
"fire_protection" from ever becoming readable, and the register would have gone
from one wrong label to twenty.
"""

from __future__ import annotations

import pytest

from app.modules.interface_management.seed import _TRADE_DISCIPLINE, _package_label


@pytest.mark.parametrize(
    ("trade", "expected"),
    [
        # Keys from the module's own pool. These are what the caser is for.
        ("fire_protection", "Fire Protection"),
        ("steel_erection", "Steel Erection"),
        ("concrete", "Concrete"),
        # Text a person wrote. An initialism, a code prefix and a lowercase
        # German particle all survive only if nothing recases them.
        ("LV 01 - Baustelleneinrichtung und Gemeinkosten", "LV 01 - Baustelleneinrichtung und Gemeinkosten"),
        ("MEP", "MEP"),
        ("HVAC & Controls", "HVAC & Controls"),
        ("Rohbau (shell)", "Rohbau (shell)"),
        # Surrounding space is still trimmed, on both branches.
        ("  concrete  ", "Concrete"),
        ("  LV 01  ", "LV 01"),
    ],
)
def test_package_label(trade: str, expected: str) -> None:
    assert _package_label(trade) == expected


def test_every_key_in_the_pool_still_takes_the_recasing_branch() -> None:
    """The pool is what the recasing branch exists for, so none of it may fall through.

    Written as a property of the pool rather than a list of words, so a trade
    added later is covered on arrival instead of quietly taking the pass-through
    branch and reaching the register as a bare key.
    """
    unrecased = [trade for trade in _TRADE_DISCIPLINE if _package_label(trade) == trade]
    assert not unrecased, f"these trade keys would reach the register unlabelled: {unrecased}"
