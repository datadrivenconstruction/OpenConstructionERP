"""Run-once ledger for event side effects against PostgreSQL, including a real race."""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.event_effects import (
    EFFECT_CONTRACT,
    EFFECT_PURCHASE_ORDER,
    EventEffect,
    bid_award_key,
    claim_effect,
    rfq_award_key,
    tender_award_key,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def factory(pg_engine):
    async with pg_engine.begin() as conn:
        await conn.run_sync(EventEffect.__table__.create, checkfirst=True)
        await conn.execute(EventEffect.__table__.delete())
    return async_sessionmaker(pg_engine, expire_on_commit=False)


async def test_second_delivery_of_one_award_does_not_claim(factory):
    key = bid_award_key("a1")
    async with factory() as first:
        assert await claim_effect(first, key, EFFECT_PURCHASE_ORDER) is not None
        await first.commit()
    async with factory() as second:
        assert await claim_effect(second, key, EFFECT_PURCHASE_ORDER) is None


async def test_two_concurrent_deliveries_of_one_award_run_the_effect_once(factory):
    """Both deliveries pass the existence check before either commits; only one may win."""
    key = tender_award_key("p", "b")
    async with factory() as first, factory() as second:
        assert await claim_effect(first, key, EFFECT_PURCHASE_ORDER) is not None
        racer = asyncio.create_task(claim_effect(second, key, EFFECT_PURCHASE_ORDER))
        await asyncio.sleep(0.3)  # the racer is now blocked on the unique index
        assert not racer.done()
        await first.commit()
        assert await asyncio.wait_for(racer, 10) is None
        await second.commit()
    async with factory() as check:
        count = (await check.execute(select(func.count()).select_from(EventEffect))).scalar_one()
    assert count == 1


async def test_rolled_back_effect_releases_the_claim_for_retry(factory):
    key = rfq_award_key("r1")
    async with factory() as failed:
        assert await claim_effect(failed, key, EFFECT_PURCHASE_ORDER) is not None
        await failed.rollback()
    async with factory() as retry:
        assert await claim_effect(retry, key, EFFECT_PURCHASE_ORDER) is not None


async def test_effects_and_re_awards_are_independent(factory):
    async with factory() as session:
        assert await claim_effect(session, bid_award_key("a1"), EFFECT_PURCHASE_ORDER) is not None
        assert await claim_effect(session, bid_award_key("a1"), EFFECT_CONTRACT) is not None
        assert await claim_effect(session, bid_award_key("a2"), EFFECT_PURCHASE_ORDER) is not None
        assert await claim_effect(session, bid_award_key("a1"), EFFECT_PURCHASE_ORDER) is None
