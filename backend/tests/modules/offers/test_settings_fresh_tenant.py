"""GET /v1/offers/settings on a tenant that never saved settings answers with the defaults."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.modules.offers import router as offers_router
from app.modules.offers.models import Offer, OfferSettings
from app.modules.offers.schemas import SettingsOut
from tests.modules._partner_db import partner_engine


@pytest.mark.asyncio
async def test_first_read_creates_and_serialises_the_default_row() -> None:
    async with (
        partner_engine([OfferSettings.__table__, Offer.__table__]) as engine,
        async_sessionmaker(engine, expire_on_commit=False)() as session,
    ):
        out = await offers_router.get_settings(session)
    assert isinstance(out, SettingsOut)
    assert out.validity_days is None
    assert out.payment_days is None
    assert out.schedule_templates == []
    assert out.next_number.startswith("OF-")


@pytest.mark.asyncio
async def test_losing_the_first_insert_race_reads_the_winners_row() -> None:
    from sqlalchemy import select

    from app.modules.offers.repository import OfferRepository

    async with (
        partner_engine([OfferSettings.__table__]) as engine,
        async_sessionmaker(engine, expire_on_commit=False)() as session,
    ):
        session.add(OfferSettings(key="default", number_pattern="X-{seq:3}"))
        await session.commit()
        real_execute = session.execute
        calls = {"n": 0}

        async def blind_first_read(stmt, *a, **kw):  # the read that raced: it saw no row yet
            calls["n"] += 1
            if calls["n"] == 1:
                return await real_execute(select(OfferSettings).where(OfferSettings.key == "none"))
            return await real_execute(stmt, *a, **kw)

        session.execute = blind_first_read  # type: ignore[method-assign]
        row = await OfferRepository(session).settings()
    assert row.number_pattern == "X-{seq:3}"
