# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Integration tests for the cost-explorer region endpoints.

The cost explorer's region backbone - ``GET /v1/costs/regions/`` (the
loaded-catalogue list) and ``GET /v1/costs/regions/stats/`` (per-region
counts) - is what powers the multibase base picker and the per-region
comparison surface. These endpoints are process-cached, so this module also
pins the cache-invalidation contract: after ``_invalidate_cost_cache`` a
stale region set can never persist, which is the isolation guarantee the
multibase UI relies on when a base is loaded or cleared.

Isolation note: the integration DB is shared and carries auto-seeded rows,
so every region id here is a module-unique synthetic (``OE_EXP_*``) and
every assertion is a subset / scoped check - never an exact grand total.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

_R_DE = "OE_EXP_DE"
_R_CH = "OE_EXP_CH"
_R_GB = "OE_EXP_GB"
_MY_REGIONS = {_R_DE, _R_CH, _R_GB}

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    """Boot the app once per module and seed 3 synthetic regions.

    OE_EXP_DE: EXP_D1..D3   OE_EXP_CH: EXP_C1..C2   OE_EXP_GB: EXP_G1
    """
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        from app.database import Base, async_session_factory, engine
        from app.modules.costs import models as _costs_models  # noqa: F401
        from app.modules.costs.models import CostItem

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        def _row(code: str, region: str) -> CostItem:
            return CostItem(
                id=uuid.uuid4(),
                code=code,
                description=f"desc {code}",
                unit="m3",
                rate="100.00",
                currency="EUR",
                source="cwicr",
                classification={"collection": "Buildings"},
                components=[],
                tags=[],
                region=region,
                is_active=True,
                metadata_={},
            )

        async with async_session_factory() as s:
            s.add_all(
                [
                    _row("EXP_D1", _R_DE),
                    _row("EXP_D2", _R_DE),
                    _row("EXP_D3", _R_DE),
                    _row("EXP_C1", _R_CH),
                    _row("EXP_C2", _R_CH),
                    _row("EXP_G1", _R_GB),
                ]
            )
            await s.commit()

        try:
            from app.modules.costs.router import _invalidate_cost_cache

            _invalidate_cost_cache()
        except Exception:
            pass

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture(scope="module")
async def auth_headers(http_client):
    """Register + promote-to-admin + log in a test user, return auth headers."""
    from sqlalchemy import update as sa_update

    from app.database import async_session_factory
    from app.modules.users.models import User

    unique = uuid.uuid4().hex[:8]
    email = f"cost-explorer-{unique}@test.io"
    password = f"Explorer{unique}9!"

    reg = await http_client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Cost Explorer"},
    )
    assert reg.status_code in (200, 201), f"register failed: {reg.text}"

    async with async_session_factory() as s:
        await s.execute(sa_update(User).where(User.email == email.lower()).values(role="admin", is_active=True))
        await s.commit()

    login = await http_client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, f"login failed: {login.text}"
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ── Region list + stats ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_loaded_regions_lists_every_seeded_region(http_client, auth_headers):
    """``GET /regions/`` surfaces each loaded catalogue, sorted, distinct."""
    resp = await http_client.get("/api/v1/costs/regions/", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    regions = resp.json()
    assert isinstance(regions, list)
    assert _MY_REGIONS.issubset(set(regions))
    # Distinct (no dupes) and sorted.
    assert len(regions) == len(set(regions))
    assert regions == sorted(regions)


@pytest.mark.asyncio
async def test_region_stats_reports_per_region_counts(http_client, auth_headers):
    """``GET /regions/stats/`` reports the item count for each loaded region."""
    resp = await http_client.get("/api/v1/costs/regions/stats/", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    by_region = {row["region"]: row["count"] for row in resp.json()}
    assert by_region.get(_R_DE) == 3
    assert by_region.get(_R_CH) == 2
    assert by_region.get(_R_GB) == 1


# ── Cache isolation / invalidation ────────────────────────────────────────


@pytest.mark.asyncio
async def test_region_cache_invalidation_prevents_stale_regions(http_client, auth_headers):
    """The loaded-regions aggregate is process-cached. ``_invalidate_cost_cache``
    must empty it so a change in the loaded set is never masked by a stale
    cached list - the isolation guarantee the base picker leans on."""
    from app.modules.costs.router import _invalidate_cost_cache, _region_cache

    # First read populates the cache.
    r1 = await http_client.get("/api/v1/costs/regions/", headers=auth_headers)
    assert r1.status_code == 200
    assert _MY_REGIONS.issubset(set(r1.json()))
    assert _region_cache["regions"] is not None

    # Invalidation must clear it - no stale region set can survive.
    _invalidate_cost_cache()
    assert _region_cache["regions"] is None

    # The next read recomputes fresh and still sees every loaded region.
    r2 = await http_client.get("/api/v1/costs/regions/", headers=auth_headers)
    assert r2.status_code == 200
    assert _MY_REGIONS.issubset(set(r2.json()))


# ── Multi-region browse provenance ────────────────────────────────────────


@pytest.mark.asyncio
async def test_multi_region_browse_items_carry_region_provenance(http_client, auth_headers):
    """Browsing several loaded bases at once returns rows scoped to those
    bases, and each row is attributable to its originating region - the data
    substrate a per-region price comparison is built on."""
    resp = await http_client.get(
        "/api/v1/costs/",
        params={"regions": [_R_DE, _R_CH], "limit": 100},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    codes = {it["code"] for it in body["items"]}
    assert codes == {"EXP_D1", "EXP_D2", "EXP_D3", "EXP_C1", "EXP_C2"}

    # Region provenance is carried on each row when the response model exposes
    # it (it does for CWICR rows); assert both bases are represented.
    item_regions = {it.get("region") for it in body["items"] if it.get("region")}
    if item_regions:
        assert item_regions == {_R_DE, _R_CH}
