# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""What the router registers and who is turned away before any query runs. No database."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.dependencies import get_optional_user_payload, get_session
from app.modules.bi_feed.router import router


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/v1/bi-feed")

    async def _session() -> AsyncIterator[None]:
        yield None  # type: ignore[misc] - the requests below are refused before the session is used

    async def _anonymous() -> dict[str, Any] | None:
        return None

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_optional_user_payload] = _anonymous
    return app


def test_only_read_verbs_are_registered() -> None:
    methods = {m for route in router.routes for m in getattr(route, "methods", set())}
    assert methods == {"GET"}


def test_feed_file_routes_exist_for_every_format() -> None:
    paths = {route.path for route in router.routes}
    assert {"/feeds", "/feeds/{feed_id}.csv", "/feeds/{feed_id}.parquet", "/feeds/{feed_id}.json"} <= paths


async def test_no_credentials_is_a_401() -> None:
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        for path in ("/v1/bi-feed/feeds", "/v1/bi-feed/feeds/invoices.csv", "/v1/bi-feed/sql-status"):
            response = await client.get(path)
            assert response.status_code == 401, path


async def test_write_verbs_are_not_allowed() -> None:
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        for verb in ("post", "put", "patch", "delete"):
            response = await getattr(client, verb)("/v1/bi-feed/feeds/invoices.csv")
            assert response.status_code == 405, verb
