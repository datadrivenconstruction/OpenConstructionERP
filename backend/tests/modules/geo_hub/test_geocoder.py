"""Unit tests for the Nominatim geocoder + cache layer.

These tests poke ``app.modules.geo_hub.geocoder`` directly without
the FastAPI app — they only need the per-module SQLite from
``conftest.py`` (loaded via ``app_instance``) to materialise the
``oe_geo_hub_geocode_cache`` table.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest

from app.database import async_session_factory
from app.modules.geo_hub import geocoder as gc
from app.modules.geo_hub.geocoder import (
    CACHE_TTL,
    ProjectAddress,
    geocode_address,
    project_address_from_jsonb,
)

# ── Helpers ─────────────────────────────────────────────────────────────


def _berlin_payload() -> list[dict[str, Any]]:
    return [
        {
            "place_id": 12345,
            "lat": "52.5200066",
            "lon": "13.4049540",
            "display_name": "Hauptstraße 12, 10115 Berlin, Germany",
            "addresstype": "house",
            "class": "building",
            "boundingbox": ["52.519", "52.521", "13.404", "13.406"],
        },
    ]


def _make_transport(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def _isolate_rate_state(monkeypatch):
    """Reset the geocoder's process-global rate-limit clock between tests."""
    monkeypatch.setattr(gc, "_last_request_monotonic", 0.0)
    # Drop the inter-call min interval to 0 so the suite finishes fast.
    monkeypatch.setattr(gc, "_MIN_INTERVAL_SECONDS", 0.0)
    monkeypatch.delenv("OE_GEOCODER_DISABLED", raising=False)
    monkeypatch.delenv("OE_GEOCODER_BASE_URL", raising=False)


@pytest.fixture(autouse=True)
async def _clear_cache(app_instance):  # noqa: ARG001 — bootstraps schema
    from sqlalchemy import delete

    from app.modules.geo_hub.models import GeocodeCache

    async with async_session_factory() as session:
        await session.execute(delete(GeocodeCache))
        await session.commit()


# ── 15+ tests ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_address_with_all_fields_builds_correct_query():
    addr = ProjectAddress(
        street="Hauptstraße",
        house_number="12",
        postal_code="10115",
        city="Berlin",
        country="Germany",
    )
    q = gc._normalised_query(addr)
    assert q == "hauptstraße 12, 10115, berlin, germany"


@pytest.mark.asyncio
async def test_address_country_only_returns_country_precision():
    captured: list[httpx.Request] = []

    async def handler(req: httpx.Request) -> httpx.Response:
        captured.append(req)
        return httpx.Response(
            200,
            json=[
                {
                    "lat": "51.0",
                    "lon": "9.0",
                    "display_name": "Germany",
                    "addresstype": "country",
                    "class": "boundary",
                    "boundingbox": ["47.0", "55.0", "5.0", "15.0"],
                },
            ],
        )

    async with _make_transport(handler) as client:
        result = await geocode_address(
            ProjectAddress(country="Germany"),
            http_client=client,
        )
    assert result is not None
    assert result.precision == "country"
    assert result.source == "nominatim"


@pytest.mark.asyncio
async def test_empty_country_returns_none_without_network():
    calls = 0

    async def handler(_req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=[])

    async with _make_transport(handler) as client:
        result = await geocode_address(
            ProjectAddress(country=""),
            http_client=client,
        )
    assert result is None
    assert calls == 0  # short-circuits before hitting the network


@pytest.mark.asyncio
async def test_user_agent_header_set_correctly():
    captured: list[httpx.Request] = []

    async def handler(req: httpx.Request) -> httpx.Response:
        captured.append(req)
        return httpx.Response(200, json=_berlin_payload())

    async with _make_transport(handler) as client:
        await geocode_address(
            ProjectAddress(country="Germany", city="Berlin"),
            http_client=client,
        )
    assert captured, "Nominatim was never called"
    ua = captured[0].headers.get("User-Agent") or ""
    assert "OpenConstructionERP" in ua
    assert "info@datadrivenconstruction.io" in ua


@pytest.mark.asyncio
async def test_self_hosted_base_url_honoured(monkeypatch):
    captured: list[httpx.Request] = []
    monkeypatch.setenv(
        "OE_GEOCODER_BASE_URL",
        "https://nominatim.example.com",
    )

    async def handler(req: httpx.Request) -> httpx.Response:
        captured.append(req)
        return httpx.Response(200, json=_berlin_payload())

    async with _make_transport(handler) as client:
        await geocode_address(
            ProjectAddress(country="Germany", city="Berlin"),
            http_client=client,
        )
    assert captured
    assert str(captured[0].url).startswith(
        "https://nominatim.example.com/search",
    )


@pytest.mark.asyncio
async def test_disabled_env_var_short_circuits(monkeypatch):
    calls = 0
    monkeypatch.setenv("OE_GEOCODER_DISABLED", "true")

    async def handler(_req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_berlin_payload())

    async with _make_transport(handler) as client:
        result = await geocode_address(
            ProjectAddress(country="Germany", city="Berlin"),
            http_client=client,
        )
    assert result is None
    assert calls == 0


@pytest.mark.asyncio
async def test_timeout_returns_none():
    async def handler(_req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("nominatim took too long")

    async with _make_transport(handler) as client:
        result = await geocode_address(
            ProjectAddress(country="Germany", city="Berlin"),
            http_client=client,
        )
    assert result is None


@pytest.mark.asyncio
async def test_502_from_nominatim_returns_none():
    async def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="Bad Gateway")

    async with _make_transport(handler) as client:
        result = await geocode_address(
            ProjectAddress(country="Germany", city="Berlin"),
            http_client=client,
        )
    assert result is None


@pytest.mark.asyncio
async def test_empty_response_list_returns_none():
    async def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    async with _make_transport(handler) as client:
        result = await geocode_address(
            ProjectAddress(country="Atlantis"),
            http_client=client,
        )
    assert result is None


@pytest.mark.asyncio
async def test_cache_hit_returns_without_http_call():
    calls = 0

    async def handler(_req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_berlin_payload())

    addr = ProjectAddress(
        country="Germany",
        city="Berlin",
        street="Hauptstraße",
        house_number="12",
        postal_code="10115",
    )
    async with _make_transport(handler) as client:
        first = await geocode_address(addr, http_client=client)
        second = await geocode_address(addr, http_client=client)

    assert first is not None and second is not None
    assert calls == 1, "Second call should have hit the cache"
    assert second.source == "cache"
    assert second.lat == first.lat
    assert second.lon == first.lon


@pytest.mark.asyncio
async def test_cache_ttl_expired_refetches():
    calls = 0

    async def handler(_req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_berlin_payload())

    addr = ProjectAddress(country="Germany", city="Berlin")
    async with _make_transport(handler) as client:
        await geocode_address(addr, http_client=client)
        # Backdate the cached_at past the TTL.
        from sqlalchemy import update

        from app.modules.geo_hub.models import GeocodeCache

        async with async_session_factory() as session:
            stale = datetime.now(UTC) - CACHE_TTL - timedelta(days=1)
            await session.execute(
                update(GeocodeCache).values(cached_at=stale),
            )
            await session.commit()
        second = await geocode_address(addr, http_client=client)
    assert calls == 2
    assert second is not None
    assert second.source == "nominatim"  # not cache after TTL


@pytest.mark.asyncio
async def test_force_refresh_skips_cache():
    calls = 0

    async def handler(_req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_berlin_payload())

    addr = ProjectAddress(country="Germany", city="Berlin")
    async with _make_transport(handler) as client:
        await geocode_address(addr, http_client=client)
        await geocode_address(addr, http_client=client, force_refresh=True)
    assert calls == 2


@pytest.mark.asyncio
async def test_precision_address_for_house_payload():
    async def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_berlin_payload())

    async with _make_transport(handler) as client:
        result = await geocode_address(
            ProjectAddress(
                country="Germany",
                city="Berlin",
                street="Hauptstraße",
                house_number="12",
            ),
            http_client=client,
        )
    assert result is not None
    assert result.precision == "address"


@pytest.mark.asyncio
async def test_bbox_parsed_from_nominatim():
    async def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_berlin_payload())

    async with _make_transport(handler) as client:
        result = await geocode_address(
            ProjectAddress(country="Germany", city="Berlin"),
            http_client=client,
        )
    assert result is not None
    assert result.bbox is not None
    min_lat, min_lon, max_lat, max_lon = result.bbox
    assert min_lat == Decimal("52.519")
    assert max_lon == Decimal("13.406")


@pytest.mark.asyncio
async def test_lat_lon_are_decimal_not_float():
    async def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_berlin_payload())

    async with _make_transport(handler) as client:
        result = await geocode_address(
            ProjectAddress(country="Germany", city="Berlin"),
            http_client=client,
        )
    assert result is not None
    assert isinstance(result.lat, Decimal)
    assert isinstance(result.lon, Decimal)
    # Sanity: the Berlin Mitte mock latitude is around 52.52.
    assert Decimal("52") < result.lat < Decimal("53")


@pytest.mark.asyncio
async def test_invalid_lat_lon_in_payload_returns_none():
    async def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"lat": "nope", "lon": "12"}])

    async with _make_transport(handler) as client:
        result = await geocode_address(
            ProjectAddress(country="Germany"),
            http_client=client,
        )
    assert result is None


@pytest.mark.asyncio
async def test_out_of_range_lat_returns_none():
    async def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"lat": "190", "lon": "12"}])

    async with _make_transport(handler) as client:
        result = await geocode_address(
            ProjectAddress(country="Germany"),
            http_client=client,
        )
    assert result is None


@pytest.mark.asyncio
async def test_project_address_from_jsonb_skips_missing_country():
    assert project_address_from_jsonb(None) is None
    assert project_address_from_jsonb({}) is None
    assert project_address_from_jsonb({"city": "Berlin"}) is None
    typed = project_address_from_jsonb(
        {
            "country": "Germany",
            "street": "Hauptstraße",
            "postal_code": "10115",
            "city": "Berlin",
        },
    )
    assert typed is not None
    assert typed.country == "Germany"
    assert typed.postal_code == "10115"


@pytest.mark.asyncio
async def test_concurrent_calls_serialise_through_rate_lock():
    """The asyncio semaphore must prevent parallel outbound calls."""
    import asyncio

    in_flight = 0
    max_in_flight = 0

    async def handler(_req: httpx.Request) -> httpx.Response:
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return httpx.Response(200, json=_berlin_payload())

    async with _make_transport(handler) as client:
        tasks = [
            geocode_address(
                ProjectAddress(country=f"Country{i}"),
                http_client=client,
            )
            for i in range(5)
        ]
        await asyncio.gather(*tasks)
    assert max_in_flight == 1


@pytest.mark.asyncio
async def test_hit_count_incremented_on_cache_hit():
    """Each cache hit should bump the row's hit_count column."""
    from sqlalchemy import select

    from app.modules.geo_hub.models import GeocodeCache

    async def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_berlin_payload())

    addr = ProjectAddress(country="Germany", city="Berlin")
    async with _make_transport(handler) as client:
        await geocode_address(addr, http_client=client)
        await geocode_address(addr, http_client=client)
        await geocode_address(addr, http_client=client)

    async with async_session_factory() as session:
        row = (await session.execute(select(GeocodeCache))).scalars().first()
    assert row is not None
    # Initial write (0) + two hits = 2.
    assert row.hit_count >= 2
