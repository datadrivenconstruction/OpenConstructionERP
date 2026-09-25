"""A refresh that lands on a locked ECB set answers 409, not 500.

The repository already refuses to rewrite a locked set (``RateSetLockedError``),
and the create and delete routes translate that into a conflict. The refresh
route did not, so the same refusal reached the client as an unhandled
``RuntimeError``: a 500 that reads as a crash instead of "this set is pinned".
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.modules.fx.router import fx_refresh
from app.modules.fx.service import FxService
from tests._pg import transactional_session

_DAY = date(2026, 7, 1)


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        yield s


@pytest.mark.asyncio
async def test_a_refresh_onto_a_locked_set_is_a_conflict(session, monkeypatch) -> None:
    svc = FxService(session)

    async def _fetch():
        return {"USD": Decimal("1.10")}, _DAY

    monkeypatch.setattr(svc, "fetch_ecb_rates", _fetch)
    first = await svc.refresh()
    await svc.set_rate_set_lock(uuid.UUID(first["rate_set_id"]), locked=True)

    async def _refetch():
        return {"USD": Decimal("1.25")}, _DAY

    monkeypatch.setattr(svc, "fetch_ecb_rates", _refetch)
    with pytest.raises(HTTPException) as caught:
        await fx_refresh(_user_id="u", service=svc)
    assert caught.value.status_code == 409
    assert "2026-07-01" in str(caught.value.detail)
    assert "locked" in str(caught.value.detail)


@pytest.mark.asyncio
async def test_a_refresh_onto_an_unlocked_set_still_rewrites_it(session, monkeypatch) -> None:
    svc = FxService(session)

    async def _fetch():
        return {"USD": Decimal("1.10")}, _DAY

    monkeypatch.setattr(svc, "fetch_ecb_rates", _fetch)
    await svc.refresh()
    result = await fx_refresh(_user_id="u", service=svc)
    assert result.network_ok is True
