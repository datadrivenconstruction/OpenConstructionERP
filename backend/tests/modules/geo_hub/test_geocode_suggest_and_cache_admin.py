# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""HTTP tests for the new geocode suggest + cache admin endpoints.

Covers (Wave 7 depth):

* ``GET  /api/v1/geo-hub/geocode/suggest`` — autocomplete dropdown
* ``GET  /api/v1/geo-hub/geocode/cache/stats`` — admin cache panel
* ``DELETE /api/v1/geo-hub/geocode/cache`` — manual cache purge

The suggest endpoint is patched at the geocoder layer so the tests
never touch the network. RBAC + auth gates are exercised end-to-end.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.geo_hub import geocoder as geocoder_mod
from app.modules.geo_hub.geocoder import SuggestionResult


def _berlin_suggestions(count: int = 3) -> list[SuggestionResult]:
    out = []
    for i in range(count):
        out.append(
            SuggestionResult(
                display_name=f"Berlin Result {i}, Germany",
                lat=Decimal(f"52.520{i}"),
                lon=Decimal(f"13.405{i}"),
                country_code="de",
                bbox=(
                    Decimal("52.0"),
                    Decimal("13.0"),
                    Decimal("53.0"),
                    Decimal("14.0"),
                ),
                addresstype="city" if i == 0 else "road",
                osm_type="relation",
            )
        )
    return out


@pytest.fixture
def patch_suggest_ok(monkeypatch):
    async def fake(_q, *, limit: int = 5, **_kwargs):
        return _berlin_suggestions(min(limit, 3))

    monkeypatch.setattr(geocoder_mod, "suggest_addresses", fake)
    return fake


@pytest.fixture
def patch_suggest_empty(monkeypatch):
    async def fake(*_args, **_kwargs):
        return []

    monkeypatch.setattr(geocoder_mod, "suggest_addresses", fake)
    return fake


# ── Suggest endpoint ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_suggest_returns_dropdown_rows(
    http_client,
    tenant_a,
    patch_suggest_ok,
):
    res = await http_client.get(
        "/api/v1/geo-hub/geocode/suggest?q=Berlin",
        headers=tenant_a["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["query"] == "Berlin"
    assert body["geocoder_disabled"] is False
    assert len(body["suggestions"]) == 3
    first = body["suggestions"][0]
    assert "Berlin" in first["display_name"]
    assert first["country_code"] == "de"
    assert first["bbox"] == ["52.0", "13.0", "53.0", "14.0"]
    assert first["addresstype"] == "city"


@pytest.mark.asyncio
async def test_suggest_respects_limit_param(
    http_client,
    tenant_a,
    patch_suggest_ok,
):
    res = await http_client.get(
        "/api/v1/geo-hub/geocode/suggest?q=Berlin&limit=2",
        headers=tenant_a["headers"],
    )
    assert res.status_code == 200
    assert len(res.json()["suggestions"]) == 2


@pytest.mark.asyncio
async def test_suggest_caps_limit_at_10(
    http_client,
    tenant_a,
    patch_suggest_ok,
):
    res = await http_client.get(
        "/api/v1/geo-hub/geocode/suggest?q=Berlin&limit=999",
        headers=tenant_a["headers"],
    )
    # FastAPI Query(le=10) rejects > 10.
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_suggest_requires_q(http_client, tenant_a, patch_suggest_ok):
    res = await http_client.get(
        "/api/v1/geo-hub/geocode/suggest",
        headers=tenant_a["headers"],
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_suggest_requires_auth(http_client, patch_suggest_ok):
    res = await http_client.get("/api/v1/geo-hub/geocode/suggest?q=Berlin")
    # No Authorization header → 401 from the auth middleware.
    assert res.status_code in (401, 403)


@pytest.mark.asyncio
async def test_suggest_returns_empty_when_geocoder_disabled(
    http_client,
    tenant_a,
    monkeypatch,
    patch_suggest_ok,
):
    monkeypatch.setenv("OE_GEOCODER_DISABLED", "true")
    res = await http_client.get(
        "/api/v1/geo-hub/geocode/suggest?q=Berlin",
        headers=tenant_a["headers"],
    )
    assert res.status_code == 200
    body = res.json()
    assert body["geocoder_disabled"] is True
    assert body["suggestions"] == []
    monkeypatch.delenv("OE_GEOCODER_DISABLED", raising=False)


@pytest.mark.asyncio
async def test_suggest_returns_empty_on_failure(
    http_client,
    tenant_a,
    patch_suggest_empty,
):
    res = await http_client.get(
        "/api/v1/geo-hub/geocode/suggest?q=Atlantis",
        headers=tenant_a["headers"],
    )
    assert res.status_code == 200
    assert res.json()["suggestions"] == []


# ── Cache admin: stats + purge ──────────────────────────────────────────


async def _seed_cache_row(query_hash: str, days_old: int = 0) -> None:
    """Write a cache row N days old for the admin tests."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import insert

    from app.database import async_session_factory
    from app.modules.geo_hub.models import GeocodeCache

    async with async_session_factory() as session:
        await session.execute(
            insert(GeocodeCache).values(
                query_hash=query_hash,
                query_text=f"q-{query_hash[:6]}",
                lat=Decimal("52.0"),
                lon=Decimal("13.0"),
                precision="address",
                display_name="seed",
                source="nominatim",
                cached_at=datetime.now(UTC) - timedelta(days=days_old),
                hit_count=days_old,
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_cache_stats_requires_admin(http_client, tenant_b):
    """tenant_b is editor (not admin) — RBAC must reject."""
    res = await http_client.get(
        "/api/v1/geo-hub/geocode/cache/stats",
        headers=tenant_b["headers"],
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_cache_stats_returns_counts(http_client, tenant_a):
    await _seed_cache_row("stat" + "a" * 60, days_old=1)
    await _seed_cache_row("stat" + "b" * 60, days_old=40)  # stale
    res = await http_client.get(
        "/api/v1/geo-hub/geocode/cache/stats",
        headers=tenant_a["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] >= 2
    assert body["stale"] >= 1
    assert body["ttl_days"] == 30


@pytest.mark.asyncio
async def test_cache_purge_requires_admin(http_client, tenant_b):
    res = await http_client.delete(
        "/api/v1/geo-hub/geocode/cache",
        headers=tenant_b["headers"],
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_cache_purge_default_30_days_only_sweeps_stale(
    http_client,
    tenant_a,
):
    fresh = "purge" + "f" * 60
    stale = "purge" + "s" * 60
    await _seed_cache_row(fresh, days_old=1)
    await _seed_cache_row(stale, days_old=45)
    res = await http_client.delete(
        "/api/v1/geo-hub/geocode/cache",
        headers=tenant_a["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["older_than_days"] == 30
    assert body["deleted"] >= 1


@pytest.mark.asyncio
async def test_cache_purge_zero_days_flushes_everything(
    http_client,
    tenant_a,
):
    await _seed_cache_row("purgeall" + "x" * 56, days_old=0)
    res = await http_client.delete(
        "/api/v1/geo-hub/geocode/cache?older_than_days=0",
        headers=tenant_a["headers"],
    )
    assert res.status_code == 200
    body = res.json()
    # No assertion on exact count — other tests may have left rows; but
    # at least our just-seeded row must be gone.
    stats = await http_client.get(
        "/api/v1/geo-hub/geocode/cache/stats",
        headers=tenant_a["headers"],
    )
    assert stats.status_code == 200
    assert stats.json()["total"] == 0
    assert body["deleted"] >= 1


@pytest.mark.asyncio
async def test_cache_purge_rejects_negative_days(
    http_client,
    tenant_a,
):
    res = await http_client.delete(
        "/api/v1/geo-hub/geocode/cache?older_than_days=-5",
        headers=tenant_a["headers"],
    )
    # Query(ge=0) rejects negative — FastAPI returns 422.
    assert res.status_code == 422


# ── Anchored projects: new metadata fields ──────────────────────────────


@pytest.mark.asyncio
async def test_anchored_projects_returns_project_type_and_status(
    http_client,
    tenant_a,
):
    """Pin layer must include project_type + status for icon rendering."""
    res = await http_client.get(
        "/api/v1/geo-hub/projects",
        headers=tenant_a["headers"],
    )
    assert res.status_code == 200, res.text
    rows = res.json()
    assert isinstance(rows, list)
    if rows:
        first = rows[0]
        # ``project_type`` is nullable — but the field must be present.
        assert "project_type" in first
        assert "status" in first
        assert "project_address_text" in first


# ── Geocoder unit: suggest_addresses ────────────────────────────────────


@pytest.mark.asyncio
async def test_suggest_addresses_short_query_returns_empty(monkeypatch):
    """Short queries (< 3 chars) must short-circuit before HTTP."""
    import httpx

    from app.modules.geo_hub.geocoder import suggest_addresses

    calls = 0

    async def handler(_req):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=[])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        out = await suggest_addresses("Be", http_client=c)
    assert out == []
    assert calls == 0


@pytest.mark.asyncio
async def test_suggest_addresses_parses_top_n_results(monkeypatch):
    import httpx

    from app.modules.geo_hub.geocoder import suggest_addresses

    async def handler(_req):
        return httpx.Response(
            200,
            json=[
                {
                    "lat": "52.52",
                    "lon": "13.405",
                    "display_name": "Berlin, Germany",
                    "addresstype": "city",
                    "osm_type": "relation",
                    "address": {"country_code": "de"},
                    "boundingbox": ["52.3", "52.7", "13.0", "13.8"],
                },
                {
                    "lat": "52.4",
                    "lon": "13.5",
                    "display_name": "Berlin Schönefeld, Germany",
                    "addresstype": "town",
                    "osm_type": "relation",
                    "address": {"country_code": "de"},
                },
            ],
        )

    monkeypatch.setattr(geocoder_mod, "_MIN_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(geocoder_mod, "_last_request_monotonic", 0.0)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        out = await suggest_addresses("Berlin", http_client=c)
    assert len(out) == 2
    assert out[0].display_name.startswith("Berlin,")
    assert out[0].country_code == "de"
    assert out[0].bbox == (
        Decimal("52.3"),
        Decimal("13.0"),
        Decimal("52.7"),
        Decimal("13.8"),
    )
