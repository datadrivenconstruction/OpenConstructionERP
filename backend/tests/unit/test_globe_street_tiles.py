# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""The 3D globe shows relief unless an operator configures raster street tiles.

The globe can only draw raster XYZ imagery and no keyless public raster
street service permits app use, so relief is the default. These tests pin the
opt-in: a complete configuration (template plus attribution) switches the
globe to streets through a same-origin proxy, and anything less leaves it on
relief instead of drawing an uncredited map or requesting a broken URL.

Run: pytest backend/tests/unit/test_globe_street_tiles.py
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest

from app.modules.geo_hub import router

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


class _Settings:
    globe_street_tiles_url = ""
    globe_street_tiles_attribution = ""
    globe_street_tiles_max_zoom = 19


class _Request:
    headers: dict[str, str] = {}


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[type[_Settings]]:
    class _Fresh(_Settings):
        pass

    monkeypatch.setattr(router, "get_settings", lambda: _Fresh)
    router.reset_basemap_state()
    router._GLOBE_WARNED.clear()
    yield _Fresh
    router.reset_basemap_state()


class _Upstream:
    """Records every URL the proxy fetches and answers with ``body``."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.body: bytes | None = _PNG

    async def fetch(self, url: str) -> bytes | None:
        self.calls.append(url)
        return self.body


@pytest.fixture
def upstream(monkeypatch: pytest.MonkeyPatch) -> _Upstream:
    fake = _Upstream()
    monkeypatch.setattr(router, "_fetch_upstream", fake.fetch)
    return fake


def _configure(settings: type[_Settings]) -> None:
    settings.globe_street_tiles_url = "https://tiles.example.internal/osm/{z}/{x}/{y}.png"
    settings.globe_street_tiles_attribution = "© OpenStreetMap contributors"


def test_relief_is_the_default(settings: type[_Settings], upstream: _Upstream) -> None:
    assert asyncio.run(router.globe_imagery()).streets is None
    res = asyncio.run(router.proxy_globe_street_tile(3, 1, 1, _Request()))
    assert res.body == router._BLANK_TILE
    assert upstream.calls == []


def test_a_configured_source_is_served_same_origin_with_its_credit(
    settings: type[_Settings], upstream: _Upstream
) -> None:
    _configure(settings)
    settings.globe_street_tiles_max_zoom = 17

    streets = asyncio.run(router.globe_imagery()).streets
    assert streets is not None
    # The browser gets our path, never the operator's server.
    assert streets.tile_url == "/api/v1/geo-hub/globe-streets/{z}/{x}/{y}.png"
    assert "example.internal" not in streets.model_dump_json()
    assert streets.attribution == "© OpenStreetMap contributors"
    assert streets.max_zoom == 17

    res = asyncio.run(router.proxy_globe_street_tile(5, 17, 10, _Request()))
    assert res.body == _PNG
    assert res.media_type == "image/png"
    assert upstream.calls == ["https://tiles.example.internal/osm/5/17/10.png"]
    assert "immutable" not in res.headers["cache-control"]

    # Second request comes from the cache.
    asyncio.run(router.proxy_globe_street_tile(5, 17, 10, _Request()))
    assert len(upstream.calls) == 1


@pytest.mark.parametrize(
    ("url", "attribution"),
    [
        ("https://tiles.example.internal/{z}/{x}/{y}.png", ""),
        ("https://tiles.example.internal/{z}/{x}.png", "© provider"),
        ("file:///srv/tiles/{z}/{x}/{y}.png", "© provider"),
    ],
    ids=["no-attribution", "no-y", "not-http"],
)
def test_a_half_configured_source_falls_back_to_relief(
    settings: type[_Settings], upstream: _Upstream, url: str, attribution: str
) -> None:
    settings.globe_street_tiles_url = url
    settings.globe_street_tiles_attribution = attribution
    assert asyncio.run(router.globe_imagery()).streets is None
    assert asyncio.run(router.proxy_globe_street_tile(1, 0, 0, _Request())).body == router._BLANK_TILE
    assert upstream.calls == []


def test_an_upstream_answer_that_is_not_an_image_is_not_a_tile(settings: type[_Settings], upstream: _Upstream) -> None:
    _configure(settings)
    upstream.body = b"<html>quota exceeded</html>"
    assert asyncio.run(router.proxy_globe_street_tile(2, 1, 1, _Request())).body == router._BLANK_TILE

    upstream.body = _JPEG
    res = asyncio.run(router.proxy_globe_street_tile(2, 1, 1, _Request()))
    assert res.body == _JPEG
    assert res.media_type == "image/jpeg"


def test_off_grid_and_too_deep_tiles_are_not_requested(settings: type[_Settings], upstream: _Upstream) -> None:
    _configure(settings)
    settings.globe_street_tiles_max_zoom = 10
    assert asyncio.run(router.proxy_globe_street_tile(11, 0, 0, _Request())).body == router._BLANK_TILE
    assert asyncio.run(router.proxy_globe_street_tile(2, 4, 0, _Request())).body == router._BLANK_TILE
    assert upstream.calls == []


def test_both_routes_answer_without_auth_through_routing(settings: type[_Settings], upstream: _Upstream) -> None:
    """The globe's tile loader cannot attach a header, so both paths must be public."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    _configure(settings)
    app = FastAPI()
    app.include_router(router.router, prefix="/api/v1/geo-hub")
    client = TestClient(app)

    answer = client.get("/api/v1/geo-hub/globe-imagery/")
    assert answer.status_code == 200
    tile_url = answer.json()["streets"]["tile_url"]
    assert tile_url == "/api/v1/geo-hub/globe-streets/{z}/{x}/{y}.png"

    tile = client.get(tile_url.format(z=4, x=8, y=5))
    assert tile.status_code == 200
    assert tile.content == _PNG
    assert upstream.calls == ["https://tiles.example.internal/osm/4/8/5.png"]
