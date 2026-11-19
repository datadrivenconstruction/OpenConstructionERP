"""An award that fixed a payment discount and a retention cap writes them to the subcontract terms."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.modules.bid_management.events import _hand_terms_to_subcontract
from app.modules.subcontractors.terms_models import SubcontractTerms
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator:
    async with transactional_session() as s:
        yield s


async def _stored(session, contract_id: uuid.UUID) -> SubcontractTerms | None:
    result = await session.execute(select(SubcontractTerms).where(SubcontractTerms.contract_id == contract_id))
    return result.scalar_one_or_none()


async def test_award_terms_are_written_as_subcontract_terms(db_session) -> None:
    contract = SimpleNamespace(
        id=uuid.uuid4(),
        terms={
            "award_terms": {"contract_sum": "400008.60"},
            "payment_terms": {
                "retention_cap_percent": "5",
                "payment_discount_percent": "2",
                "payment_discount_days": 14,
            },
        },
    )
    await _hand_terms_to_subcontract(db_session, contract)

    row = await _stored(db_session, contract.id)
    assert row is not None
    assert row.source == "award"
    assert row.retention_cap_percent == Decimal("5")
    assert row.payment_discount_percent == Decimal("2")
    assert row.payment_discount_days == 14
    assert row.payment_discount_agreed is True


async def test_award_without_payment_terms_writes_nothing(db_session) -> None:
    contract = SimpleNamespace(id=uuid.uuid4(), terms={"award_terms": {"contract_sum": "10"}})
    await _hand_terms_to_subcontract(db_session, contract)
    assert await _stored(db_session, contract.id) is None
