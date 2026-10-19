"""French late-payment notice regimes: four clocks. Interest figures live in app/core/late_payment.

France had no regime of its own, so a French clock could only be opened on the
EU Directive row, which states ECB + 8 points. That is the public-buyer rate and
two points short of the private B2B default (Code de commerce L441-10 II). Each
case below is chosen so the wrong model gives a different answer.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.payment_clock.data import PAYMENT_REGIMES, regime_by_code
from app.modules.payment_clock.schemas import RegimeSeedRow

B2B = "fr_com_l441_10"
PUBLIC = "fr_ccp_r2192_10"
HEALTH = "fr_ccp_r2192_11_health"
UNDERTAKING = "fr_ccp_r2192_11_undertaking"


class TestTheFrenchRows:
    def test_france_has_four_clocks_of_its_own(self) -> None:
        codes = {r["code"] for r in PAYMENT_REGIMES if r["country_code"] == "FR"}
        assert codes == {B2B, PUBLIC, HEALTH, UNDERTAKING}

    @pytest.mark.parametrize(
        ("code", "days", "margin"),
        [(B2B, 30, "10"), (PUBLIC, 30, "8"), (HEALTH, 50, "8"), (UNDERTAKING, 60, "8")],
    )
    def test_each_clock_carries_its_own_period_and_margin(self, code: str, days: int, margin: str) -> None:
        regime = regime_by_code(code)
        assert regime is not None
        RegimeSeedRow(**regime)
        assert regime["final_date_days"] == days
        assert regime["interest_margin_percent"] == Decimal(margin)
        assert regime["no_notice_effect"] == "none"

    def test_the_private_default_is_not_the_directive_margin(self) -> None:
        eu = regime_by_code("eu_late_payment")
        fr = regime_by_code(B2B)
        assert eu is not None and fr is not None
        assert fr["interest_margin_percent"] - eu["interest_margin_percent"] == Decimal("2")
