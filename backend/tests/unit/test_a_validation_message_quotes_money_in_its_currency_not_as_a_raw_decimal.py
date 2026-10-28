# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Money inside a validation message is rendered, never interpolated raw.

A ``Decimal`` dropped straight into a message reaches the estimator as
``1234.5000000000`` or ``1E+3``: no thousands separator, no currency, and a
tail of zeros that reads like a precision the figure does not have. The house
renderer ``_fmt_money`` exists for exactly this, and these tests assert the
*rendered text* rather than the fact that a rule fired, so that putting the
raw value back turns them red.

The tests also pin the boundary the renderer must not cross. A quantity is a
count of units and must stay a bare number: "5" must never become "5.00 EUR".
So the negative-values rule is asserted on both slots at once - the amount
carries a currency, the quantity carries none.

No database: the property_dev rules read their session out of
``ValidationContext.metadata``, so a queued stub answers their SELECTs and the
assertion is on the string the estimator would read.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from app.core.validation.engine import ValidationContext
from app.core.validation.rules import (
    NegativeValues,
    PropDevEscrowBalanceReconciled,
    PropDevPaymentScheduleInstalmentsSumToContractValue,
    _fmt_money,
)

# A figure chosen to make every failure mode visible at once: it needs two
# grouping separators, it has a fractional part, and ``str()`` on the Decimal
# renders it without a single comma.
PROBE = Decimal("1234567.89")


# ── Stub session ───────────────────────────────────────────────────────────


class _ScalarRows:
    """Answers the ORM-entity shape: ``.scalars().all()`` / ``.scalar_one_or_none()``."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = list(rows)

    def scalars(self) -> _ScalarRows:
        return self

    def all(self) -> list[Any]:
        return list(self._rows)

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None


class _TupleRows:
    """Answers the grouped-aggregate shape: ``.all()`` over row tuples."""

    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = list(rows)

    def all(self) -> list[tuple[Any, ...]]:
        return list(self._rows)


class _QueuedSession:
    """Hands back pre-built results in the order the rule asks for them."""

    def __init__(self, results: list[Any]) -> None:
        self._queue = list(results)

    async def execute(self, statement: Any) -> Any:  # noqa: ARG002 - the stub never runs SQL
        if not self._queue:
            raise AssertionError("the rule issued more queries than this fixture queued")
        return self._queue.pop(0)


def _propdev_context(session: _QueuedSession) -> ValidationContext:
    return ValidationContext(
        data={},
        project_id=str(uuid.uuid4()),
        metadata={"locale": "en", "session": session, "development_id": str(uuid.uuid4())},
    )


# ── The renderer itself ────────────────────────────────────────────────────


class TestFmtMoney:
    """The two raw shapes named in the defect, plus the no-currency path."""

    def test_an_exponent_decimal_renders_as_a_readable_amount(self) -> None:
        assert str(Decimal("1E+3")) == "1E+3"
        assert _fmt_money(Decimal("1E+3"), "EUR") == "1,000.00 EUR"

    def test_a_trailing_zero_decimal_loses_its_false_precision(self) -> None:
        assert str(Decimal("1234.5000000000")) == "1234.5000000000"
        assert _fmt_money(Decimal("1234.5000000000"), "EUR") == "1,234.50 EUR"

    def test_a_blank_currency_groups_the_digits_and_omits_the_code(self) -> None:
        rendered = _fmt_money(PROBE, "")
        assert rendered == "1,234,567.89"
        assert rendered == rendered.strip(), "a blank currency must not leave a trailing space"

    def test_a_currency_without_a_subunit_keeps_no_decimals(self) -> None:
        assert _fmt_money(Decimal("1500"), "JPY") == "1,500 JPY"


# ── boq_quality.negative_values ────────────────────────────────────────────


async def _negative_values_message(positions: list[dict[str, Any]], **data: Any) -> str:
    context = ValidationContext(
        data={"positions": positions, **data},
        metadata={"locale": "en"},
    )
    results = await NegativeValues().validate(context)
    failed = [r for r in results if not r.passed]
    assert failed, "expected the rule to flag the negative row"
    return failed[0].message


class TestNegativeValuesMessage:
    async def test_a_negative_unit_rate_is_quoted_with_its_currency(self) -> None:
        """The regression guard: reverting to the raw float drops the commas and the code."""
        message = await _negative_values_message(
            [{"id": "p1", "ordinal": "1.1", "quantity": 10, "unit_rate": -1234567.89, "currency": "EUR"}]
        )
        assert message == "Position 1.1 has negative unit_rate=-1,234,567.89 EUR"
        assert "-1234567.89" not in message

    async def test_the_bill_header_currency_is_used_when_the_row_states_none(self) -> None:
        message = await _negative_values_message(
            [{"id": "p1", "ordinal": "2.1", "quantity": 1, "unit_rate": -1500}],
            boq={"currency": "JPY"},
        )
        assert message == "Position 2.1 has negative unit_rate=-1,500 JPY"

    async def test_no_currency_anywhere_still_groups_the_amount_and_invents_nothing(self) -> None:
        message = await _negative_values_message(
            [{"id": "p1", "ordinal": "3.1", "quantity": 1, "unit_rate": -1234567.89}]
        )
        assert message == "Position 3.1 has negative unit_rate=-1,234,567.89"

    async def test_a_negative_quantity_stays_a_bare_count(self) -> None:
        """A quantity is not money: five items must never read as "5.00 EUR"."""
        message = await _negative_values_message(
            [{"id": "p1", "ordinal": "4.1", "quantity": -5, "unit_rate": 10, "currency": "EUR"}]
        )
        assert message == "Position 4.1 has negative quantity=-5.0"
        assert "EUR" not in message

    async def test_both_slots_in_one_row_keep_their_own_shapes(self) -> None:
        message = await _negative_values_message(
            [{"id": "p1", "ordinal": "5.1", "quantity": -5, "unit_rate": -1234567.89, "currency": "EUR"}]
        )
        assert message == "Position 5.1 has negative quantity=-5.0, unit_rate=-1,234,567.89 EUR"


# ── property_dev.escrow_balance_reconciled ─────────────────────────────────


async def test_an_escrow_drift_is_reported_in_the_accounts_currency() -> None:
    """Reverting to ``str(Decimal.quantize(...))`` renders ``1234567.89`` and fails here."""
    account = SimpleNamespace(
        id=uuid.uuid4(),
        currency="AED",
        metadata_={"ledger_balance": str(PROBE)},
    )
    session = _QueuedSession(
        [
            _ScalarRows([account]),
            _TupleRows([("credit", Decimal("2000000.00"), 3)]),
        ]
    )
    results = await PropDevEscrowBalanceReconciled().validate(_propdev_context(session))

    failed = [r for r in results if not r.passed]
    assert len(failed) == 1
    assert failed[0].message == (
        f"Escrow account {account.id}: ledger balance 1,234,567.89 AED drifts 765,432.11 AED from 3 transactions sum"
    )
    # The structured payload keeps the unrendered figure - only prose is formatted.
    assert failed[0].details["declared_ledger"] == "1234567.89"


async def test_an_escrow_account_without_a_currency_states_no_code() -> None:
    """A blank currency column degrades to a grouped number rather than a guess."""
    account = SimpleNamespace(id=uuid.uuid4(), currency="", metadata_={"ledger_balance": "0"})
    session = _QueuedSession(
        [
            _ScalarRows([account]),
            _TupleRows([("credit", PROBE, 1)]),
        ]
    )
    results = await PropDevEscrowBalanceReconciled().validate(_propdev_context(session))

    failed = [r for r in results if not r.passed]
    assert len(failed) == 1
    assert failed[0].message == (
        f"Escrow account {account.id}: ledger balance 0.00 drifts 1,234,567.89 from 1 transactions sum"
    )


# ── property_dev.payment_schedule_instalments_sum_to_contract_value ────────


async def test_an_instalment_shortfall_is_reported_in_the_contracts_currency() -> None:
    """Every one of the three amount slots is rendered, including the drift."""
    contract = SimpleNamespace(id=uuid.uuid4(), currency="EUR", total_value=Decimal("1000000.00"))
    schedule = SimpleNamespace(id=uuid.uuid4())
    instalments = [
        SimpleNamespace(amount=Decimal("1000000.00")),
        SimpleNamespace(amount=Decimal("234567.89")),
    ]
    session = _QueuedSession(
        [
            _ScalarRows([contract]),
            _ScalarRows([schedule]),
            _ScalarRows(instalments),
        ]
    )
    rule = PropDevPaymentScheduleInstalmentsSumToContractValue()
    results = await rule.validate(_propdev_context(session))

    failed = [r for r in results if not r.passed]
    assert len(failed) == 1
    assert failed[0].message == (
        f"Contract {contract.id}: instalments total 1,234,567.89 EUR "
        "differs from contract value 1,000,000.00 EUR (drift 234,567.89 EUR)"
    )
    assert "1234567.89" not in failed[0].message
