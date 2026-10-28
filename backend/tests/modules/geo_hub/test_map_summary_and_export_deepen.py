# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Deepen-wave tests for the Geo Hub map summary, address-coords anchor
fallback, and enriched GeoJSON export.

What is under test
~~~~~~~~~~~~~~~~~~~
* ``GeoHubService.map_config`` synthesises a *transient* anchor from a
  project's address ``lat``/``lng`` when no GeoAnchor row exists, so a
  project pinned on the global map opens to a usable project-scoped map
  instead of a dead "not anchored" empty state. A persisted anchor wins;
  a project with neither coords nor anchor stays ``anchor=None``.
* ``GeoHubService.map_summary`` aggregates per-layer counts plus
  severity / priority / kind breakdowns with SQL grouped counts, matching
  exactly the rows the pin-layer endpoints return, and is IDOR-gated.
* ``GeoHubService.export_geojson`` folds the anchor and the cross-module
  pin layers into one FeatureCollection (each feature tagged with an
  ``oe:layer`` property), honours the ``include`` filter, treats an
  all-unknown-token filter as "export nothing", and is IDOR-gated.

Why the service layer (not the ASGI client)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
These are exercised through the **service layer directly** against the
conftest-provisioned PostgreSQL cluster, seeding users / projects / pins
via the ORM. That mirrors the precedent in
``tests/modules/ai/test_quick_estimate_history_enrich.py`` and avoids the
module-scoped ASGI HTTP-client fixture pattern, which currently breaks on
Windows + pytest-asyncio 1.3 + asyncpg (WinError 10038) under the only
locally available interpreter. The IDOR boundary is the same
``_verify_project_owner`` the router depends on, so cross-tenant 404
behaviour is still covered here. The router wiring itself (query parsing,
``RequirePermission``) is thin and covered by the existing geo_hub HTTP
suites in CI.

Run:
    cd backend
    python -m pytest tests/modules/geo_hub/test_map_summary_and_export_deepen.py -v
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException

# Eager-import every model namespace the suite touches so Base.metadata
# sees a coherent table set when create_all runs.
import app.modules.daily_diary.models  # noqa: E402,F401
import app.modules.geo_hub.models  # noqa: E402,F401
import app.modules.projects.models  # noqa: E402,F401
import app.modules.punchlist.models  # noqa: E402,F401
import app.modules.safety.models  # noqa: E402,F401
import app.modules.teams.models  # noqa: E402,F401
import app.modules.users.models  # noqa: E402,F401

# ── Schema bootstrap (no ASGI client needed) ───────────────────────────────


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def schema():
    """Create all ORM tables once for the module against the embedded cluster."""
    from app.database import Base, engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


# ── ORM seed helpers ────────────────────────────────────────────────────────


async def _seed_user(role: str = "user") -> str:
    from app.database import async_session_factory
    from app.modules.users.models import User

    uid = uuid.uuid4()
    async with async_session_factory() as s:
        s.add(
            User(
                id=uid,
                email=f"geo-{uuid.uuid4().hex[:10]}@geo-deepen.io",
                full_name="Geo Deepen",
                hashed_password="x",
                is_active=True,
                role=role,
            )
        )
        await s.commit()
    return str(uid)


async def _seed_project(
    *,
    owner_id: str,
    currency: str = "EUR",
    address: dict | None = None,
) -> uuid.UUID:
    from app.database import async_session_factory
    from app.modules.projects.models import Project

    pid = uuid.uuid4()
    async with async_session_factory() as s:
        s.add(
            Project(
                id=pid,
                name=f"GeoD-{uuid.uuid4().hex[:6]}",
                description="geo deepening test",
                owner_id=uuid.UUID(owner_id),
                currency=currency,
                region="DACH",
                classification_standard="din276",
                address=address,
                metadata_={},
                fx_rates=[],
            )
        )
        await s.commit()
    return pid


async def _seed_incident(
    *,
    project_id: uuid.UUID,
    severity: str,
    geo_lat: float | None,
    geo_lon: float | None,
    number: str,
) -> None:
    from app.database import async_session_factory
    from app.modules.safety.models import SafetyIncident

    async with async_session_factory() as s:
        s.add(
            SafetyIncident(
                id=uuid.uuid4(),
                project_id=project_id,
                incident_number=number,
                title=f"Incident {severity}",
                incident_date="2026-05-01",
                incident_type="injury",
                severity=severity,
                description="geo-pinned" if geo_lat is not None else "no coords",
                geo_lat=geo_lat,
                geo_lon=geo_lon,
            )
        )
        await s.commit()


async def _seed_punch(
    *,
    project_id: uuid.UUID,
    priority: str,
    geo_lat: float | None,
    geo_lon: float | None,
) -> None:
    from app.database import async_session_factory
    from app.modules.punchlist.models import PunchItem

    async with async_session_factory() as s:
        s.add(
            PunchItem(
                id=uuid.uuid4(),
                project_id=project_id,
                title="Cracked tile",
                priority=priority,
                category="finishing",
                geo_lat=geo_lat,
                geo_lon=geo_lon,
            )
        )
        await s.commit()


def _owner_payload(owner_id: str) -> dict[str, str]:
    # Non-admin so the IDOR owner-check actually runs (admins bypass).
    return {"sub": owner_id, "role": "user"}


async def _make_service():
    from app.database import async_session_factory
    from app.modules.geo_hub.service import GeoHubService

    session = async_session_factory()
    return GeoHubService(session), session


# ── A: address-coords transient anchor in map_config ────────────────────


class TestAddressCoordsAnchorFallback:
    @pytest.mark.asyncio(loop_scope="module")
    async def test_address_coords_synthesise_transient_anchor(self, schema):  # noqa: ARG002
        owner = await _seed_user()
        pid = await _seed_project(
            owner_id=owner,
            currency="CAD",
            address={
                "street": "King West",
                "city": "Toronto",
                "country": "Canada",
                "country_code": "ca",
                "lat": 43.6433,
                "lng": -79.4019,
            },
        )
        svc, session = await _make_service()
        try:
            bundle = await svc.map_config(pid, payload=_owner_payload(owner))
        finally:
            await session.close()
        anchor = bundle["anchor"]
        assert anchor is not None, "map_config must synthesise an anchor from address coords"
        # ``id`` is None for a transient anchor; metadata flags it derived.
        assert anchor.id is None
        assert abs(float(anchor.lat) - 43.6433) < 1e-6
        assert abs(float(anchor.lon) - (-79.4019)) < 1e-6
        assert anchor.metadata_["persisted"] is False
        assert anchor.metadata_["derived_from"] == "project_address"
        assert anchor.region_code == "CA"
        # The single-line address renders from the JSONB.
        assert "Toronto" in (anchor.address or "")

    @pytest.mark.asyncio(loop_scope="module")
    async def test_real_anchor_wins_over_address_coords(self, schema):  # noqa: ARG002
        from app.modules.geo_hub.schemas import GeoAnchorCreate

        owner = await _seed_user()
        pid = await _seed_project(
            owner_id=owner,
            address={"country": "Canada", "lat": 43.6433, "lng": -79.4019},
        )
        svc, session = await _make_service()
        try:
            created = await svc.create_anchor(
                GeoAnchorCreate(
                    project_id=pid,
                    lat=Decimal("48.1351"),
                    lon=Decimal("11.5820"),
                    epsg_code=4326,
                ),
                payload=_owner_payload(owner),
            )
            assert created.id is not None
            bundle = await svc.map_config(pid, payload=_owner_payload(owner))
        finally:
            await session.close()
        anchor = bundle["anchor"]
        assert anchor.id is not None, "a persisted anchor must keep its UUID id"
        assert abs(float(anchor.lat) - 48.1351) < 1e-6

    @pytest.mark.asyncio(loop_scope="module")
    async def test_no_coords_no_anchor(self, schema):  # noqa: ARG002
        owner = await _seed_user()
        pid = await _seed_project(owner_id=owner, address=None)
        svc, session = await _make_service()
        try:
            bundle = await svc.map_config(pid, payload=_owner_payload(owner))
        finally:
            await session.close()
        assert bundle["anchor"] is None

    @pytest.mark.tenant_isolation
    @pytest.mark.asyncio(loop_scope="module")
    async def test_map_config_cross_tenant_404(self, schema):  # noqa: ARG002
        owner = await _seed_user()
        stranger = await _seed_user()
        pid = await _seed_project(owner_id=owner, address={"country": "X", "lat": 10, "lng": 10})
        svc, session = await _make_service()
        try:
            with pytest.raises(HTTPException) as exc:
                await svc.map_config(pid, payload=_owner_payload(stranger))
            assert exc.value.status_code == 404
        finally:
            await session.close()


# ── B: map summary endpoint ─────────────────────────────────────────────


class TestMapSummary:
    @pytest.mark.asyncio(loop_scope="module")
    async def test_summary_counts_match_pin_layers(self, schema):  # noqa: ARG002
        from app.modules.geo_hub.schemas import GeoOverlayCreate

        owner = await _seed_user()
        pid = await _seed_project(owner_id=owner)
        payload = _owner_payload(owner)

        # Two geo-pinned incidents (moderate + minor), one un-pinned.
        await _seed_incident(project_id=pid, severity="moderate", geo_lat=52.52, geo_lon=13.40, number="INC-1")
        await _seed_incident(project_id=pid, severity="minor", geo_lat=52.53, geo_lon=13.40, number="INC-2")
        await _seed_incident(project_id=pid, severity="minor", geo_lat=None, geo_lon=None, number="INC-3")
        # One geo-pinned punch item.
        await _seed_punch(project_id=pid, priority="high", geo_lat=48.13, geo_lon=11.58)

        svc, session = await _make_service()
        try:
            # One vector overlay (boundary).
            await svc.create_overlay(
                GeoOverlayCreate(
                    project_id=pid,
                    name="Site boundary",
                    kind="boundary",
                    geojson={
                        "type": "FeatureCollection",
                        "features": [
                            {
                                "type": "Feature",
                                "geometry": {
                                    "type": "Polygon",
                                    "coordinates": [[[0, 0], [0, 1], [1, 1], [0, 0]]],
                                },
                                "properties": {},
                            }
                        ],
                    },
                ),
                payload=payload,
            )

            summary = await svc.map_summary(pid, payload=payload)
            hse_pins = await svc.list_hse_pins(pid, payload=payload)
        finally:
            await session.close()

        assert summary["hse_pins"]["total"] == 2
        assert summary["hse_pins"]["breakdown"] == {"moderate": 1, "minor": 1}
        assert summary["punchlist_pins"]["total"] == 1
        assert summary["punchlist_pins"]["breakdown"] == {"high": 1}
        assert summary["overlays"]["total"] == 1
        assert summary["overlays"]["breakdown"]["boundary"] == 1
        assert summary["diary_pins"]["total"] == 0
        # Summary HSE count must equal the pin-layer projection exactly.
        assert len(hse_pins) == summary["hse_pins"]["total"]
        # total_features rolls up every layer.
        assert summary["total_features"] >= 2 + 1 + 1  # hse + punch + overlay

    @pytest.mark.asyncio(loop_scope="module")
    async def test_summary_anchor_is_derived_flag(self, schema):  # noqa: ARG002
        owner = await _seed_user()
        pid = await _seed_project(
            owner_id=owner,
            address={"country": "Canada", "lat": 43.6433, "lng": -79.4019},
        )
        svc, session = await _make_service()
        try:
            summary = await svc.map_summary(pid, payload=_owner_payload(owner))
        finally:
            await session.close()
        assert summary["has_anchor"] is True
        assert summary["anchor_is_derived"] is True

    @pytest.mark.tenant_isolation
    @pytest.mark.asyncio(loop_scope="module")
    async def test_summary_cross_tenant_404(self, schema):  # noqa: ARG002
        owner = await _seed_user()
        stranger = await _seed_user()
        pid = await _seed_project(owner_id=owner)
        svc, session = await _make_service()
        try:
            with pytest.raises(HTTPException) as exc:
                await svc.map_summary(pid, payload=_owner_payload(stranger))
            assert exc.value.status_code == 404
        finally:
            await session.close()


# ── C: enriched GeoJSON export ──────────────────────────────────────────


class TestEnrichedExport:
    @pytest.mark.asyncio(loop_scope="module")
    async def test_export_folds_anchor_and_pins(self, schema):  # noqa: ARG002
        from app.modules.geo_hub.schemas import GeoAnchorCreate, GeoOverlayCreate

        owner = await _seed_user()
        pid = await _seed_project(owner_id=owner)
        payload = _owner_payload(owner)

        await _seed_incident(project_id=pid, severity="moderate", geo_lat=52.52, geo_lon=13.40, number="EXP-1")
        await _seed_incident(project_id=pid, severity="minor", geo_lat=52.53, geo_lon=13.40, number="EXP-2")
        await _seed_punch(project_id=pid, priority="high", geo_lat=48.13, geo_lon=11.58)

        svc, session = await _make_service()
        try:
            await svc.create_overlay(
                GeoOverlayCreate(
                    project_id=pid,
                    name="Site boundary",
                    kind="boundary",
                    geojson={
                        "type": "FeatureCollection",
                        "features": [
                            {
                                "type": "Feature",
                                "geometry": {
                                    "type": "Polygon",
                                    "coordinates": [[[0, 0], [0, 1], [1, 1], [0, 0]]],
                                },
                                "properties": {},
                            }
                        ],
                    },
                ),
                payload=payload,
            )
            await svc.create_anchor(
                GeoAnchorCreate(
                    project_id=pid,
                    lat=Decimal("52.5000"),
                    lon=Decimal("13.4000"),
                    epsg_code=4326,
                ),
                payload=payload,
            )
            fc = await svc.export_geojson(pid, payload=payload)
        finally:
            await session.close()

        assert fc["type"] == "FeatureCollection"
        layers = [f["properties"].get("oe:layer") for f in fc["features"]]
        assert "anchor" in layers, "anchor point must be folded into the export"
        assert layers.count("hse") == 2
        assert layers.count("punchlist") == 1
        assert "overlay" in layers
        # Every feature carries an oe:layer tag for downstream splitting.
        assert all("oe:layer" in f["properties"] for f in fc["features"])

    @pytest.mark.asyncio(loop_scope="module")
    async def test_export_include_filter(self, schema):  # noqa: ARG002
        from app.modules.geo_hub.schemas import GeoAnchorCreate

        owner = await _seed_user()
        pid = await _seed_project(owner_id=owner)
        payload = _owner_payload(owner)

        await _seed_incident(project_id=pid, severity="moderate", geo_lat=52.52, geo_lon=13.40, number="FLT-1")
        svc, session = await _make_service()
        try:
            await svc.create_anchor(
                GeoAnchorCreate(project_id=pid, lat=Decimal("52.5"), lon=Decimal("13.4"), epsg_code=4326),
                payload=payload,
            )
            fc = await svc.export_geojson(pid, payload=payload, include={"hse"})
        finally:
            await session.close()
        layers = {f["properties"].get("oe:layer") for f in fc["features"]}
        assert layers == {"hse"}, f"include={{'hse'}} must export only hse, got {layers}"

    @pytest.mark.asyncio(loop_scope="module")
    async def test_export_empty_include_folds_nothing(self, schema):  # noqa: ARG002
        # The router maps an all-unknown ``include`` token (e.g. ?include=bogus)
        # to an explicit empty set. That must fold NOTHING, not degrade back
        # to "everything".
        from app.modules.geo_hub.schemas import GeoAnchorCreate

        owner = await _seed_user()
        pid = await _seed_project(owner_id=owner)
        payload = _owner_payload(owner)

        await _seed_incident(project_id=pid, severity="moderate", geo_lat=52.52, geo_lon=13.40, number="EMP-1")
        svc, session = await _make_service()
        try:
            await svc.create_anchor(
                GeoAnchorCreate(project_id=pid, lat=Decimal("52.5"), lon=Decimal("13.4"), epsg_code=4326),
                payload=payload,
            )
            fc = await svc.export_geojson(pid, payload=payload, include=set())
        finally:
            await session.close()
        assert fc["features"] == []

    @pytest.mark.tenant_isolation
    @pytest.mark.asyncio(loop_scope="module")
    async def test_export_cross_tenant_404(self, schema):  # noqa: ARG002
        owner = await _seed_user()
        stranger = await _seed_user()
        pid = await _seed_project(owner_id=owner)
        svc, session = await _make_service()
        try:
            with pytest.raises(HTTPException) as exc:
                await svc.export_geojson(pid, payload=_owner_payload(stranger))
            assert exc.value.status_code == 404
        finally:
            await session.close()
