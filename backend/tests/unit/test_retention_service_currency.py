"""Service calculations use the same currency precision as payment applications."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.contracts.retention import flat_policy
from app.modules.contracts.service import ContractsService, _release_share_outside_schedule, flat_retention_within_cap


@pytest.mark.parametrize(
    ("currency", "gross", "expected"), [("JPY", "123", "6"), ("EUR", "12.345", "0.62"), ("KWD", "12.345", "0.617")]
)
@pytest.mark.asyncio
async def test_claim_currency_drives_engine_and_flat_accrual(currency, gross, expected):
    svc = ContractsService(SimpleNamespace())
    svc.retention_policy = AsyncMock(return_value=flat_policy("5"))
    svc._flat_retention_cap = AsyncMock(return_value=None)
    svc.claim_line_repo = SimpleNamespace(prior_period_value_by_line=AsyncMock(return_value={}))
    svc.claim_repo = SimpleNamespace(prior_claims=AsyncMock(return_value=[]))
    svc.release_repo = SimpleNamespace(billed_on_claims=AsyncMock(return_value=[]))
    contract = SimpleNamespace(
        id="contract", contract_type="lump_sum", currency="USD", total_value="1000", retention_percent=5
    )
    claim = SimpleNamespace(id="claim", currency=currency, gross_amount=gross)
    lines = [SimpleNamespace(contract_line_id="a", period_completed_value=gross, prior_completed_value="0")]
    figures = await svc.claim_retention_figures(claim, contract=contract, lines=lines)
    assert figures.accrual == Decimal(expected)
    assert figures.held == figures.lines["a"].retention_to_date == Decimal(expected)
    assert await svc.flat_claim_retention(contract, claim, Decimal(gross)) == Decimal(expected)


@pytest.mark.asyncio
async def test_outside_schedule_cache_cannot_reuse_another_currency_precision():
    svc = ContractsService(SimpleNamespace())
    svc.claim_line_repo = SimpleNamespace(period_value_by_claim=AsyncMock(return_value={"old": Decimal("9")}))
    prior = [SimpleNamespace(id="old", gross_amount="10", retention_amount="6.17")]
    values = []
    for currency in ("EUR", "KWD", "JPY", "EUR"):
        values.append(
            await svc.prior_retention_without_schedule_lines(
                "contract", before_claim_id="claim", prior_claims=prior, currency=currency
            )
        )
    assert values == [Decimal("0.62"), Decimal("0.617"), Decimal("1"), Decimal("0.62")]
    assert svc.claim_line_repo.period_value_by_claim.await_count == 3


@pytest.mark.parametrize(
    ("currency", "contract_sum", "before", "expected"),
    [("JPY", "123", "5", "1"), ("EUR", "12.345", "0.61", "0.01"), ("KWD", "12.345", "0.613", "0.004")],
)
def test_flat_cap_keeps_its_last_minor_units(currency, contract_sum, before, expected):
    value = flat_retention_within_cap(
        Decimal("100"),
        Decimal("20"),
        cap_percent=Decimal("5"),
        contract_sum=Decimal(contract_sum),
        accrued_before=Decimal(before),
        currency=currency,
    )
    assert value == Decimal(expected)


@pytest.mark.parametrize(("currency", "before"), [("JPY", "9.4"), ("EUR", "9.994"), ("KWD", "9.9994")])
def test_legacy_fractions_do_not_create_room_past_the_flat_cap(currency, before):
    accrued = Decimal(before)
    value = flat_retention_within_cap(
        Decimal("100"),
        Decimal("20"),
        cap_percent=Decimal("10"),
        contract_sum=Decimal("100"),
        accrued_before=accrued,
        currency=currency,
    )
    assert value == 0
    assert accrued + value <= Decimal("10")


@pytest.mark.parametrize(("currency", "expected"), [("JPY", "0"), ("EUR", "0.33"), ("KWD", "0.333")])
def test_release_split_uses_currency_units_and_full_release_clears_outside_pool(currency, expected):
    assert _release_share_outside_schedule(
        Decimal("1"), schedule_pool=Decimal("2"), outside_pool=Decimal("1"), currency=currency
    ) == Decimal(expected)
    assert _release_share_outside_schedule(
        Decimal("3"), schedule_pool=Decimal("2"), outside_pool=Decimal("1"), currency=currency
    ) == Decimal("1")
