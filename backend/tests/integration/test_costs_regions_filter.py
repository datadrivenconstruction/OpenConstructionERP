# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Integration tests for the multibase ``regions`` filter on GET /v1/costs/.

The v3-P8 multibase wave lets ``GET /api/v1/costs/`` accept a *repeated*
``regions`` query param so a project scoped to several loaded catalogues
browses the union in one request. Precedence: ``regions`` (plural union)
beats ``region`` (singular), which beats "no filter" (every region).

This exercises the wire contract end-to-end through the FastAPI router:
repeated-param parsing, the union SQL, the precedence rule, and per-request
isolation (a scope change is never masked by the response of the prior
request). The pure repository SQL is covered by
``tests/unit/test_costs_repository_regions.py``.

Isolation note: the integration DB is shared across modules and carries
auto-seeded rows, so - like ``test_costs_intelligence.py`` - every region id
here is a module-unique synthetic (``OE_RGF_*``) and every assertion is
scoped to those regions. Scoped counts are therefore exact regardless of
what else lives in the catalogue; the one un-scoped check asserts only a
lower bound.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Module-unique synthetic regions - collision-proof against auto-seed and
# any other test module sharing the process DB.
_R_DE = "OE_RGF_DE"
_R_CH = "OE_RGF_CH"
_R_GB = "OE_RGF_GB"

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    """Boot the app once per module and seed cost items across 3 synthetic
    regions.

    OE_RGF_DE: RGF_D1..D3   OE_RGF_CH: RGF_C1..C2   OE_RGF_GB: RGF_G1
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
                    _row("RGF_D1", _R_DE),
                    _row("RGF_D2", _R_DE),
                    _row("RGF_D3", _R_DE),
                    _row("RGF_C1", _R_CH),
                    _row("RGF_C2", _R_CH),
                    _row("RGF_G1", _R_GB),
                ]
            )
            await s.commit()

        # The region aggregates are cached process-globally; wipe them so a
        # prior module's cache can't leak a stale total into the search
        # fast-path for our scoped queries.
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
    """Register + promote-to-admin + log in a test user, return auth headers.

    ``GET /api/v1/costs/`` requires a valid JWT (presence check), so mint one
    and reuse it across the module.
    """
    from sqlalchemy import update as sa_update

    from app.database import async_session_factory
    from app.modules.users.models import User

    unique = uuid.uuid4().hex[:8]
    email = f"regions-filter-{unique}@test.io"
    password = f"RegionsTest{unique}9!"

    reg = await http_client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Regions Filter"},
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


async def _get(http_client, auth_headers, **params) -> dict:
    params.setdefault("limit", 100)
    resp = await http_client.get("/api/v1/costs/", params=params, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _codes(body: dict) -> set[str]:
    return {it["code"] for it in body["items"]}


# ── Tests ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_regions_repeated_param_returns_union(http_client, auth_headers):
    """``?regions=OE_RGF_DE&regions=OE_RGF_CH`` returns the union of both."""
    body = await _get(http_client, auth_headers, regions=[_R_DE, _R_CH])
    assert _codes(body) == {"RGF_D1", "RGF_D2", "RGF_D3", "RGF_C1", "RGF_C2"}
    assert body["total"] == 5


@pytest.mark.asyncio
async def test_regions_single_value_scopes_to_one_catalogue(http_client, auth_headers):
    body = await _get(http_client, auth_headers, regions=[_R_CH])
    assert _codes(body) == {"RGF_C1", "RGF_C2"}
    assert body["total"] == 2


@pytest.mark.asyncio
async def test_regions_plural_beats_region_singular(http_client, auth_headers):
    """Precedence: when both are sent, ``regions`` wins and ``region`` is
    ignored - never AND-combined into an empty intersection."""
    body = await _get(http_client, auth_headers, regions=[_R_DE], region=_R_GB)
    assert _codes(body) == {"RGF_D1", "RGF_D2", "RGF_D3"}
    assert body["total"] == 3


@pytest.mark.asyncio
async def test_no_region_param_is_broader_than_a_single_scope(http_client, auth_headers):
    """With no region filter the endpoint returns every loaded row - which is
    at least all of ours and strictly more than one region's slice. (Exact
    grand total is not asserted: the shared DB carries other rows too.)"""
    all_body = await _get(http_client, auth_headers, limit=1)
    de_body = await _get(http_client, auth_headers, regions=[_R_DE])
    assert all_body["total"] >= 6
    assert all_body["total"] > de_body["total"] == 3


@pytest.mark.asyncio
async def test_back_to_back_region_scopes_do_not_bleed(http_client, auth_headers):
    """Query-cache isolation: two sequential requests with different scopes
    each return their own rows. A cached total or item set from the first
    must not surface in the second."""
    de = await _get(http_client, auth_headers, regions=[_R_DE])
    ch = await _get(http_client, auth_headers, regions=[_R_CH])

    assert _codes(de) == {"RGF_D1", "RGF_D2", "RGF_D3"}
    assert _codes(ch) == {"RGF_C1", "RGF_C2"}
    assert de["total"] == 3
    assert ch["total"] == 2
    assert _codes(de).isdisjoint(_codes(ch))
