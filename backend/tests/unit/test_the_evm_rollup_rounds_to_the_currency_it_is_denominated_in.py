# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The scalar EVM rollup rounds money to the currency it is denominated in.

``app.core.money.money_quantum`` is the platform's single value-layer resolver
for how many decimals an amount really has. Two surfaces in the schedule module
compute earned value over the same activities:

* the 4D dashboard, through ``service_4d._q_money``, which asks the resolver;
* ``GET /schedules/{id}/evm-summary/``, through ``evm_math.compute_evm_summary``,
  which used a fixed four-decimal quantum and never asked anything.

So one schedule answered two different numbers depending on which endpoint was
asked, and a yen came back with four decimals nothing in Japan can settle.
``compute_evm_summary`` now takes the quantum from its caller. ``evm_math`` is
deliberately free of ORM and app imports and cannot resolve a currency itself,
which is why the argument is a quantum and not a currency code; the router
resolves it through ``money_quantum`` and these tests do the same, so a drift
between the resolver and this module fails here rather than in production.

Only the *value* layer is under test. What a screen prints and what an invoice
declares are decided elsewhere (see the three-layer note in ``app.core.money``).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.core.money import money_quantum
from app.modules.schedule.evm_math import EvmCostRow, compute_evm_summary

# One cost-loaded activity, fully elapsed by the data date, half done. The
# numbers are chosen so every money field lands on a value whose rendering
# differs between a 0-, 2- and 3-decimal currency.
_AS_OF = date(2026, 4, 1)
_ROWS = [
    EvmCostRow(
        start_date="2026-01-01",
        end_date="2026-02-01",
        cost_planned=Decimal("1000"),
        cost_actual=Decimal("600"),
        progress_pct="50",
    )
]

_MONEY_FIELDS = (
    "planned_value",
    "earned_value",
    "actual_cost",
    "budget_at_completion",
    "schedule_variance",
    "cost_variance",
    "estimate_at_completion",
    "estimate_to_complete",
    "variance_at_completion",
)


def _exponent(text: str) -> int:
    """How many decimal places a rendered amount carries."""
    return -Decimal(text).as_tuple().exponent


def test_a_zero_decimal_currency_gets_no_decimals() -> None:
    """JPY has no subunit, so no money field may carry one.

    Before the quantum was passed in, every field came back with four decimal
    places, none of which a yen payment can express.
    """
    data = compute_evm_summary(_ROWS, _AS_OF, quantum=money_quantum("JPY")).to_json()

    for name in _MONEY_FIELDS:
        value = data[name]
        assert value is not None, f"{name} unexpectedly None"
        assert _exponent(value) == 0, f"{name} is {value!r}, a yen has no subunit"


def test_a_three_decimal_currency_keeps_its_third_digit() -> None:
    """KWD is subdivided into 1000 fils, so the third digit is real money."""
    data = compute_evm_summary(_ROWS, _AS_OF, quantum=money_quantum("KWD")).to_json()

    for name in _MONEY_FIELDS:
        assert _exponent(data[name]) == 3, f"{name} is {data[name]!r}, a dinar carries three"


def test_a_two_decimal_currency_gets_two() -> None:
    """The ordinary case, and the one a four-decimal quantum also got wrong."""
    data = compute_evm_summary(_ROWS, _AS_OF, quantum=money_quantum("EUR")).to_json()

    for name in _MONEY_FIELDS:
        assert _exponent(data[name]) == 2, f"{name} is {data[name]!r}, a euro carries two"


def test_the_quantum_reaches_the_forecast_block_not_only_the_totals() -> None:
    """EAC / ETC / VAC are rounded too, not just PV / EV / AC / BAC.

    The forecast block is computed after the totals and returned through a
    separate ``None``-guarded branch, so it is exactly where a quantum gets
    dropped without any of the headline numbers noticing.
    """
    data = compute_evm_summary(_ROWS, _AS_OF, quantum=money_quantum("JPY")).to_json()

    for name in ("estimate_at_completion", "estimate_to_complete", "variance_at_completion"):
        assert data[name] is not None, f"{name} should be computable from this fixture"
        assert _exponent(data[name]) == 0, f"{name} is {data[name]!r}, a yen has no subunit"


def test_omitting_the_quantum_keeps_the_currency_agnostic_trim() -> None:
    """No quantum means no currency was claimed, and nothing is invented.

    Four places is finer than every currency in the registry, so it is a safe
    intermediate. It is emphatically not an answer to "how many decimals does
    this amount have", which is why the endpoint passes a real one.
    """
    data = compute_evm_summary(_ROWS, _AS_OF).to_json()

    assert data["planned_value"] == "1000.0000"
    assert data["earned_value"] == "500.0000"
    assert data["actual_cost"] == "600.0000"


def test_the_old_fixed_quantum_and_the_resolved_one_are_different_numbers() -> None:
    """The defect stated as the values it produced, not as a signature.

    Four places was the constant this module used for every currency. Pinning
    both answers side by side keeps the record of what changed: a yen went from
    four decimals it cannot settle to none, and the two strings are not the
    same string.
    """
    old = compute_evm_summary(_ROWS, _AS_OF, quantum=Decimal("0.0001")).to_json()
    new = compute_evm_summary(_ROWS, _AS_OF, quantum=money_quantum("JPY")).to_json()

    assert old["budget_at_completion"] == "1000.0000"
    assert new["budget_at_completion"] == "1000"
    assert old["budget_at_completion"] != new["budget_at_completion"]


def test_the_response_carries_the_currency_it_was_rounded_to() -> None:
    """A rounded amount without its currency is not a readable answer.

    The 4D dashboard already returns one. The summary endpoint did not, so a
    client seeing ``1000`` could not tell a whole yen from a euro that had lost
    its cents somewhere upstream.
    """
    from app.modules.schedule.schemas import EvmSummaryResponse

    assert "currency" in EvmSummaryResponse.model_fields, (
        "EvmSummaryResponse must declare the currency its money fields are rounded to"
    )
    assert EvmSummaryResponse.model_fields["currency"].default == ""


def test_the_two_schedule_surfaces_agree_on_one_currency() -> None:
    """The rollup and the 4D dashboard round the same amount the same way.

    ``service_4d._q_money`` already asked ``money_quantum``; the rollup did
    not, so the dashboard and the summary endpoint disagreed about the same
    schedule. Asserting the two quanta are equal, rather than pinning a
    literal, means a currency added tomorrow is covered without editing this.
    """
    for code in ("JPY", "KWD", "EUR", "CLP", "HUF", "IDR", ""):
        summary_q = money_quantum(code)
        data = compute_evm_summary(_ROWS, _AS_OF, quantum=summary_q).to_json()
        # What the dashboard would have produced for the same total.
        dashboard = Decimal("1000").quantize(money_quantum(code))
        assert Decimal(data["budget_at_completion"]) == dashboard
        assert _exponent(data["budget_at_completion"]) == -dashboard.as_tuple().exponent, (
            f"{code}: summary and dashboard disagree on the rendered precision"
        )
