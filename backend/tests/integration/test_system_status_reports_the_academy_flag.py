# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""``/api/system/status`` reports the academy flag, read per request.

The Academy UI decides from this one field whether to draw the course map,
the task dock and the module locks. Two properties matter:

* on an install that never set ``OE_ACADEMY_MODE`` the field is ``false``, so
  nothing of the trainer appears;
* the value is read from ``get_settings()`` when the request arrives, not from
  the ``settings`` captured when the app was built. Both polarities are asked
  of ONE app instance, so a handler that baked the value in at construction
  would answer the same twice and fail here.

The vector probe is pre-cached on ``app.state`` so the request never waits on
an external vector store; it is not what is under test.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.dependencies import get_current_user_id
from app.main import create_app

_FLAG_NAMES = ("OE_ACADEMY_MODE", "ACADEMY_MODE")


def _clear_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _FLAG_NAMES:
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    _clear_flag(monkeypatch)
    app = create_app()
    app.dependency_overrides[get_current_user_id] = lambda: "00000000-0000-0000-0000-000000000001"
    app.state._vector_status_cache = {
        "data": {"status": "offline", "engine": "qdrant"},
        "checked_at": time.time(),
    }
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac
    finally:
        _clear_flag(monkeypatch)
        assert get_settings().academy_mode is False


@pytest.mark.asyncio
async def test_the_flag_is_false_unless_the_install_sets_it(client: AsyncClient) -> None:
    resp = await client.get("/api/system/status")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["academy_mode"] is False


@pytest.mark.asyncio
async def test_the_flag_follows_the_setting_on_one_running_app(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OE_ACADEMY_MODE", "true")
    get_settings.cache_clear()
    on = await client.get("/api/system/status")
    assert on.status_code == 200, on.text
    assert on.json()["academy_mode"] is True

    monkeypatch.setenv("OE_ACADEMY_MODE", "false")
    get_settings.cache_clear()
    off = await client.get("/api/system/status")
    assert off.json()["academy_mode"] is False
