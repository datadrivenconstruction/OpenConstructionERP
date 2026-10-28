# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠What the funding messages write as money, and what they must never.

Two of this module's amounts already go through ``_fmt_money``. The three
figures beside them are **rates**, and their templates glue the word
``percent`` straight onto the slot: "an own contribution of {rate} percent".
A currency code there would read "25 EUR percent", which is why the sweep that
converted the amounts had to stop at them.

That makes these the pins rather than the fixes. They are written with
four-digit values on purpose: a pin on ``5`` cannot tell a later conversion
from a no-op, while a pin on ``1234`` catches both the thousands separator and
the added decimals the conversion would bring.
"""

from __future__ import annotations

from typing import Any

from app.core.validation.engine import ValidationContext
from app.modules.funding.validators import (
    FundingCumulationWithinAidIntensity,
    FundingOwnShareIsCovered,
)


async def _only(rule: Any, data: dict[str, Any]) -> str:
    context = ValidationContext(data=data, metadata={"locale": "en"})
    results = await rule.validate(context)
    assert len(results) == 1, f"expected exactly one result, got {results}"
    return results[0].message


class TestOwnShareIsCovered:
    async def test_the_amounts_are_money_and_the_rate_is_not(self) -> None:
        """One sentence carrying both kinds, so a sweep cannot convert half of it."""
        data = {
            "application": {
                "code": "APP-1",
                "currency": "EUR",
                "eligible_cost_base": "1000000",
                "own_share_amount": "1000",
            },
            "programme": {"own_share_percent": "1234"},
        }
        message = await _only(FundingOwnShareIsCovered(), data)
        assert message == (
            "The programme requires an own contribution of 1234 percent, "
            "which is 12,340,000.00 EUR, but the application records 1,000.00 EUR"
        )
        assert "1234 EUR percent" not in message
        assert "1,234" not in message, "the rate is a percentage and must not be grouped"

    async def test_an_application_without_a_currency_writes_none(self) -> None:
        data = {
            "application": {
                "code": "APP-1",
                "currency": "",
                "eligible_cost_base": "1000000",
                "own_share_amount": "1000",
            },
            "programme": {"own_share_percent": "1234"},
        }
        assert await _only(FundingOwnShareIsCovered(), data) == (
            "The programme requires an own contribution of 1234 percent, "
            "which is 12,340,000.00, but the application records 1,000.00"
        )


class TestCumulationWithinAidIntensity:
    async def test_every_figure_in_this_sentence_is_a_rate_or_a_count(self) -> None:
        """No money at all here: an intensity, a ceiling and how many applications."""
        data = {
            "application": {"project_id": "p1", "currency": "EUR", "eligible_cost_base": "1000"},
            "project_applications": [
                {"status": "approved", "approved_amount": "12345", "aid_intensity_cap_percent": "1234"},
            ],
        }
        message = await _only(FundingCumulationWithinAidIntensity(), data)
        assert message == (
            "The 1 applications on this project come to 1234.50 percent of the eligible costs, "
            "over the 1234 percent ceiling the strictest of their programmes declares"
        )
        assert "EUR" not in message
        assert "1,234" not in message, "an intensity and a ceiling are rates, never grouped money"
