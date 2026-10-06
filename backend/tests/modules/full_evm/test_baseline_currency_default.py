"""Creation defaults follow the currency; explicit and persisted precision wins."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.modules.full_evm.models import EVMBaseline
from app.modules.full_evm.schemas import BaselineCreate, BaselineUpdate, MeasureCreate
from app.modules.full_evm.service import EVMBaselineService
from tests._pg import transactional_session


def payload(**values):
    return BaselineCreate(project_id=uuid4(), name="Currency default", bac="1000", **values)


@pytest.mark.parametrize("currency,expected", [("JPY", 0), ("KWD", 3), ("EUR", 2), (" jpy ", 0), ("XXX", 2), (None, 2)])
def test_omitted_precision_uses_registry_or_existing_unknown_policy(currency, expected):
    data = payload(currency=currency)
    assert data.minor_units == expected
    assert "minor_units" not in data.model_fields_set


def test_omitted_currency_keeps_the_existing_two_digit_policy():
    assert payload().minor_units == 2
    assert payload().currency is None


@pytest.mark.parametrize("currency,override", [("JPY", 2), ("KWD", 0), ("EUR", 4), ("XXX", 3), (None, 1)])
def test_explicit_precision_is_not_replaced(currency, override):
    data = payload(currency=currency, minor_units=override)
    assert data.minor_units == override
    assert "minor_units" in data.model_fields_set


@pytest.mark.parametrize("invalid", [None, -1, 5])
def test_explicit_invalid_precision_is_still_rejected(invalid):
    with pytest.raises(ValidationError):
        payload(currency="JPY", minor_units=invalid)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "currency,digits,expected_cv", [("JPY", 0, "1"), ("KWD", 3, "0.555"), ("EUR", 2, "0.56"), ("XXX", 2, "0.56")]
)
async def test_new_baseline_persists_currency_default_and_uses_it_for_measurements(currency, digits, expected_cv):
    async with transactional_session() as session:
        service = EVMBaselineService(session)
        baseline = await service.create_baseline(payload(currency=currency))
        measure = await service.record_measure(
            baseline,
            MeasureCreate(data_date=date(2026, 10, 6), ev="100.555", ac="100", pv="100"),
        )
        await session.flush()
        stored = await session.scalar(select(EVMBaseline.minor_units).where(EVMBaseline.id == baseline.id))
        assert stored == digits
        assert measure.cv == Decimal(expected_cv)


@pytest.mark.asyncio
async def test_explicit_legacy_precision_survives_create_read_update_and_remeasurement():
    async with transactional_session() as session:
        service = EVMBaselineService(session)
        baseline = await service.create_baseline(payload(currency="JPY", minor_units=2))
        first = await service.record_measure(
            baseline,
            MeasureCreate(data_date=date(2026, 10, 5), ev="100.555", ac="100", pv="100"),
        )
        first_cv = first.cv
        reread = await service.get_baseline(baseline.id)
        assert reread.minor_units == 2
        await service.update_baseline(reread, BaselineUpdate(name="Renamed legacy baseline", currency="KWD"))
        second = await service.record_measure(
            reread,
            MeasureCreate(data_date=date(2026, 10, 6), ev="100.555", ac="100", pv="100"),
        )
        assert reread.minor_units == 2
        assert first.cv == first_cv == Decimal("0.56")
        assert second.cv == Decimal("0.56")
