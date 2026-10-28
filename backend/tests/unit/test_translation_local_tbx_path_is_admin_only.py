# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Only an administrator may point the IATE import at a file on the server.

``POST /translation/lookup-tables/download`` with ``local_tbx_path`` parses
whatever path it is given on the server's own disk and writes the result into
the installation-wide dictionaries every user's translations read from. It
used to ask for nothing but a login, so any viewer could probe which server
paths exist (the task's error string says so) and overwrite the shared
dictionaries from any TBX-shaped file they could get onto the disk. A path on
the server is the operator's business, so the route now asks for the admin
role when the body carries one. The mirror download and MUSE pairs are
unchanged.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.translation import router as translation_router
from app.dependencies import get_current_user_id, get_current_user_payload

URL = "/api/v1/translation/lookup-tables/download"


def _app(role: str) -> FastAPI:
    app = FastAPI()
    app.include_router(translation_router.router, prefix="/api/v1")

    async def _user() -> str:
        return "00000000-0000-0000-0000-000000000001"

    async def _payload() -> dict[str, Any]:
        return {"sub": "00000000-0000-0000-0000-000000000001", "role": role, "permissions": []}

    app.dependency_overrides[get_current_user_id] = _user
    app.dependency_overrides[get_current_user_payload] = _payload
    return app


@pytest.fixture
def scheduled(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, ...]]:
    calls: list[tuple[Any, ...]] = []

    async def _fake_run_iate(*args: Any) -> None:
        calls.append(args)

    monkeypatch.setattr(translation_router, "_run_iate", _fake_run_iate)
    return calls


async def _post(role: str, body: dict[str, Any]) -> int:
    async with AsyncClient(transport=ASGITransport(app=_app(role)), base_url="http://test") as client:
        return (await client.post(URL, json=body)).status_code


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["viewer", "editor", "manager"])
async def test_a_non_admin_cannot_parse_a_server_path(role: str, scheduled: list) -> None:
    status = await _post(role, {"kind": "iate", "local_tbx_path": "/etc/passwd"})
    assert status == 403
    assert scheduled == []


@pytest.mark.asyncio
async def test_an_admin_can_import_a_local_dump(scheduled: list) -> None:
    status = await _post("admin", {"kind": "iate", "local_tbx_path": "/srv/iate/IATE_export.tbx"})
    assert status == 202
    assert len(scheduled) == 1


@pytest.mark.asyncio
async def test_the_mirror_download_still_needs_only_a_login(scheduled: list) -> None:
    status = await _post("viewer", {"kind": "iate", "url": "https://iate.europa.eu/em-api/entries/download"})
    assert status == 202
    assert len(scheduled) == 1
