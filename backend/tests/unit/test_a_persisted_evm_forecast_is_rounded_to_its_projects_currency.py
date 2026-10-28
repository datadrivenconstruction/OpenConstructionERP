# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠EAC / VAC / ETC are written to the row in the project currency's own units.

These three are not a view. ``FinanceService.create_evm_snapshot`` computes
them and persists them on ``oe_finance_evm_snapshot``, whose model declares
``eac``, ``vac``, ``etc`` and ``tcpi`` as stored columns. They were quantised
to ``Decimal("0.01")`` for every project on earth, so a Kuwaiti dinar's third
digit was gone before the INSERT and no reader downstream could put it back,
while a yen was stored carrying two decimals nothing in Japan can settle.

That is the difference between this file and its sibling for the schedule
rollup: a response-only rounding defect changes what one reader sees on one
request, and a persisted one has been writing wrong values into rows that are
still there.

The project's currency is the one in scope here (``Project.currency``, the
project base currency the same method already resolves for its FX blending),
and the quantum comes from ``app.core.money.money_quantum``, the platform's
single value-layer resolver. These tests assert against that resolver rather
than against a table of their own, so a currency whose count changes tomorrow
is covered without anybody editing this file.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.money import money_quantum
from app.modules.finance.schemas import EVMSnapshotCreate

from .test_finance_service import _make_service

# EV/AC/PV chosen so CPI is not 1 and EAC lands on a long non-terminating
# quotient: 480000 + 550000/0.9375 has a fractional tail in every currency,
# which is what makes the quantum observable at all.
_INPUTS = {
    "bac": "1000000",
    "pv": "500000",
    "ev": "450000",
    "ac": "480000",
}

_PERSISTED_MONEY_FIELDS = ("eac", "vac", "etc")


def _service_for_currency(code: str) -> Any:
    """A FinanceService whose project lookup answers with ``code``.

    ``create_evm_snapshot`` resolves the project through
    ``ProjectRepository(self.session).get_by_id(...)``, which is a
    ``session.get(Project, ...)``. The stub session answers ``None`` by
    default, i.e. "no project, unknown currency"; here it answers a project.
    """
    service = _make_service()

    async def _get(*_args: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(id=uuid.uuid4(), currency=code, fx_rates={})

    service.session.get = _get  # type: ignore[method-assign]
    return service


async def _snapshot_for(code: str) -> Any:
    return await _service_for_currency(code).create_evm_snapshot(
        EVMSnapshotCreate(project_id=uuid.uuid4(), snapshot_date="2026-04-01", **_INPUTS)
    )


def _places(text: str) -> int:
    return -Decimal(text).as_tuple().exponent


@pytest.mark.asyncio
async def test_a_zero_decimal_currency_is_not_stored_with_decimals() -> None:
    """A yen row must not carry a subunit the currency does not have."""
    snapshot = await _snapshot_for("JPY")

    for field in _PERSISTED_MONEY_FIELDS:
        stored = getattr(snapshot, field)
        assert _places(stored) == 0, f"{field} stored as {stored!r}, a yen has no subunit"


@pytest.mark.asyncio
async def test_a_three_decimal_currency_keeps_the_fils_it_was_losing() -> None:
    """The defect in the other direction, and the one that destroys money.

    A dinar is subdivided into 1000 fils. Rounding to two places discards a
    real fils that a real payment can carry, and it does it on the way into
    the table.
    """
    snapshot = await _snapshot_for("KWD")

    for field in _PERSISTED_MONEY_FIELDS:
        stored = getattr(snapshot, field)
        assert _places(stored) == 3, f"{field} stored as {stored!r}, a dinar carries three"


@pytest.mark.asyncio
async def test_the_stored_value_equals_the_resolver_and_not_a_literal() -> None:
    """Recompute EAC and quantise it through the resolver: the row must match.

    Comparing against ``money_quantum`` rather than a pinned string means this
    keeps testing the wiring, not a number somebody typed once.
    """
    for code in ("JPY", "KWD", "EUR", "CLP", "HUF", "IDR"):
        snapshot = await _snapshot_for(code)
        cpi = Decimal(_INPUTS["ev"]) / Decimal(_INPUTS["ac"])
        expected = (
            Decimal(_INPUTS["ac"])
            + (Decimal(_INPUTS["bac"]) - Decimal(_INPUTS["ev"])) / cpi.quantize(Decimal("0.0001"))
        ).quantize(money_quantum(code))
        assert Decimal(snapshot.eac) == expected, f"{code}: eac {snapshot.eac!r} is not the resolver's answer"


@pytest.mark.asyncio
async def test_an_unknown_currency_still_gets_two_decimals() -> None:
    """No project, no currency, no invention.

    Two places is what this method always wrote, and it stays the answer when
    there is nothing to resolve. Guessing a code would be worse than declining
    to: a mislabelled amount reads as authoritative.
    """
    service = _make_service()  # stub session answers None for the project
    snapshot = await service.create_evm_snapshot(
        EVMSnapshotCreate(project_id=uuid.uuid4(), snapshot_date="2026-04-01", **_INPUTS)
    )

    for field in _PERSISTED_MONEY_FIELDS:
        assert _places(getattr(snapshot, field)) == 2
