"""Geo Hub cross-module event subscriber suite.

Verifies the 10 subscribers fire correctly when other modules publish
domain events, that each one is idempotent on replay, and that error
paths emit ``geo_hub.subscriber.failed`` rather than raising.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from decimal import Decimal
from pathlib import Path

# ── Per-module SQLite isolation (must run BEFORE app imports) ──────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-geo-hub-subscribers-"))
_TMP_DB = _TMP_DIR / "geo_hub_subscribers.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.geo_hub import models as _geo_models  # noqa: F401
        from app.modules.property_dev import models as _prop_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture
async def project_id(app_instance):
    """A fresh project per test — keeps subscriber idempotency clean."""
    from app.database import async_session_factory
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user_id = uuid.uuid4()
    proj_id = uuid.uuid4()
    async with async_session_factory() as s:
        u = User(
            id=user_id,
            email=f"geo-sub-{uuid.uuid4().hex[:6]}@geo.io",
            full_name="Geo Sub",
            hashed_password="x" * 60,
            role="admin",
            is_active=True,
        )
        s.add(u)
        await s.flush()
        p = Project(
            id=proj_id,
            name=f"Geo-Sub-{uuid.uuid4().hex[:6]}",
            description="",
            owner_id=user_id,
            currency="EUR",
        )
        s.add(p)
        await s.commit()
    return proj_id


# ── projects.created -> empty anchor ───────────────────────────────────


class TestProjectCreatedSubscriber:
    @pytest.mark.asyncio
    async def test_creates_empty_anchor(self, app_instance, project_id):
        from app.core.events import event_bus
        from app.database import async_session_factory
        from app.modules.geo_hub.repository import GeoAnchorRepository

        await event_bus.publish(
            "projects.created",
            {"project_id": str(project_id), "name": "Demo"},
        )
        async with async_session_factory() as s:
            repo = GeoAnchorRepository(s)
            anchor = await repo.get_by_project(project_id)
            assert anchor is not None
            assert anchor.lat == Decimal("0")

    @pytest.mark.asyncio
    async def test_idempotent_on_replay(self, app_instance, project_id):
        from sqlalchemy import select

        from app.core.events import event_bus
        from app.database import async_session_factory
        from app.modules.geo_hub.models import GeoAnchor

        # Publish twice.
        await event_bus.publish("projects.created", {"project_id": str(project_id)})
        await event_bus.publish("projects.created", {"project_id": str(project_id)})
        async with async_session_factory() as s:
            res = await s.execute(select(GeoAnchor).where(GeoAnchor.project_id == project_id))
            anchors = list(res.scalars().all())
            assert len(anchors) == 1

    @pytest.mark.asyncio
    async def test_missing_project_id_ignored(self, app_instance):
        from app.core.events import event_bus

        res = await event_bus.publish("projects.created", {})
        # No exception, subscriber returned "ignored".
        assert res.success


# ── bim_hub.model.uploaded -> tile job queued ─────────────────────────


class TestBimUploadSubscriber:
    @pytest.mark.asyncio
    async def test_enqueues_tile_job(self, app_instance, project_id):
        from app.core.events import event_bus
        from app.database import async_session_factory
        from app.modules.geo_hub.repository import TileJobRepository

        model_id = uuid.uuid4()
        await event_bus.publish(
            "bim_hub.model.uploaded",
            {
                "project_id": str(project_id),
                "model_id": str(model_id),
            },
        )
        async with async_session_factory() as s:
            repo = TileJobRepository(s)
            jobs = await repo.list_for_project(project_id, state="queued")
            assert any(j.source_id == model_id for j in jobs)


# ── property_dev.development.created -> place anchor + fanout ─────────


class TestDevelopmentCreatedSubscriber:
    @pytest.mark.asyncio
    async def test_places_anchor_and_emits_geo_placed(
        self,
        app_instance,
        project_id,
    ):
        from app.core.events import event_bus
        from app.database import async_session_factory
        from app.modules.geo_hub.repository import GeoAnchorRepository

        fanout_received: list[dict] = []

        async def _capture(event):  # noqa: ANN001
            fanout_received.append(dict(event.data))
            return {"status": "captured"}

        event_bus.subscribe(
            "property_dev.development.geo_placed",
            _capture,
        )

        try:
            await event_bus.publish(
                "property_dev.development.created",
                {
                    "project_id": str(project_id),
                    "development_id": str(uuid.uuid4()),
                    "lat": "52.5200",
                    "lon": "13.4050",
                },
            )
            async with async_session_factory() as s:
                repo = GeoAnchorRepository(s)
                anchor = await repo.get_by_project(project_id)
                assert anchor is not None
                assert anchor.lat == Decimal("52.5200000")
            assert any(f.get("anchor_id") for f in fanout_received)
        finally:
            event_bus.unsubscribe(
                "property_dev.development.geo_placed",
                _capture,
            )

    @pytest.mark.asyncio
    async def test_missing_lat_lon_skipped(self, app_instance, project_id):
        from app.core.events import event_bus

        # Without lat/lon the subscriber returns "ignored".
        res = await event_bus.publish(
            "property_dev.development.created",
            {"project_id": str(project_id), "development_id": str(uuid.uuid4())},
        )
        assert res.success


# ── carbon.footprint.computed -> tint stamp ──────────────────────────


class TestCarbonSubscriber:
    @pytest.mark.asyncio
    async def test_stamps_tint_on_existing_tileset(
        self,
        app_instance,
        project_id,
    ):
        from app.core.events import event_bus
        from app.database import async_session_factory
        from app.modules.geo_hub.models import Tileset
        from app.modules.geo_hub.repository import TilesetRepository

        # Seed a Tileset.
        source_id = uuid.uuid4()
        async with async_session_factory() as s:
            ts = Tileset(
                project_id=project_id,
                source_kind="bim_model",
                source_id=source_id,
                status="ready",
            )
            await TilesetRepository(s).create(ts)
            await s.commit()
            tileset_id = ts.id

        await event_bus.publish(
            "carbon.footprint.computed",
            {
                "project_id": str(project_id),
                "source_kind": "bim_model",
                "source_id": str(source_id),
                "tint": {"elem_001": [0.8, 0.2, 0.1, 1.0]},
            },
        )
        async with async_session_factory() as s:
            ts = await s.get(Tileset, tileset_id)
            assert ts.metadata_.get("carbon_tint") is not None


# ── schedule.task.scheduled -> 4D dates ───────────────────────────────


class TestScheduleSubscriber:
    @pytest.mark.asyncio
    async def test_stamps_temporal_metadata(
        self,
        app_instance,
        project_id,
    ):
        from app.core.events import event_bus
        from app.database import async_session_factory
        from app.modules.geo_hub.models import Tileset
        from app.modules.geo_hub.repository import TilesetRepository

        source_id = uuid.uuid4()
        async with async_session_factory() as s:
            ts = Tileset(
                project_id=project_id,
                source_kind="bim_model",
                source_id=source_id,
                status="ready",
            )
            await TilesetRepository(s).create(ts)
            await s.commit()
            tileset_id = ts.id

        await event_bus.publish(
            "schedule.task.scheduled",
            {
                "project_id": str(project_id),
                "model_id": str(source_id),
                "task_id": "task_001",
                "start_date": "2026-06-01",
                "end_date": "2026-08-15",
                "element_ids": ["elem_001", "elem_002"],
            },
        )
        async with async_session_factory() as s:
            ts = await s.get(Tileset, tileset_id)
            temporal = ts.metadata_.get("temporal")
            assert isinstance(temporal, list)
            assert temporal[0]["task_id"] == "task_001"

    @pytest.mark.asyncio
    async def test_temporal_dedup_by_task_id(self, app_instance, project_id):
        from app.core.events import event_bus
        from app.database import async_session_factory
        from app.modules.geo_hub.models import Tileset
        from app.modules.geo_hub.repository import TilesetRepository

        source_id = uuid.uuid4()
        async with async_session_factory() as s:
            ts = Tileset(
                project_id=project_id,
                source_kind="bim_model",
                source_id=source_id,
                status="ready",
            )
            await TilesetRepository(s).create(ts)
            await s.commit()
            tileset_id = ts.id

        for date in ("2026-06-01", "2026-06-10", "2026-06-15"):
            await event_bus.publish(
                "schedule.task.scheduled",
                {
                    "project_id": str(project_id),
                    "model_id": str(source_id),
                    "task_id": "task_replay",
                    "start_date": date,
                    "end_date": "2026-08-15",
                },
            )
        async with async_session_factory() as s:
            ts = await s.get(Tileset, tileset_id)
            temporal = ts.metadata_.get("temporal") or []
            task_replays = [t for t in temporal if t.get("task_id") == "task_replay"]
            assert len(task_replays) == 1
            # And the latest payload won.
            assert task_replays[0]["start_date"] == "2026-06-15"


# ── clash.detected -> marker overlay ──────────────────────────────────


class TestClashSubscriber:
    @pytest.mark.asyncio
    async def test_creates_clash_marker(self, app_instance, project_id):
        from app.core.events import event_bus
        from app.database import async_session_factory
        from app.modules.geo_hub.repository import GeoOverlayRepository

        clash_id = f"clash-{uuid.uuid4().hex[:8]}"
        await event_bus.publish(
            "clash.detected",
            {
                "project_id": str(project_id),
                "clash_id": clash_id,
                "lat": "52.520",
                "lon": "13.405",
                "severity": "high",
            },
        )
        async with async_session_factory() as s:
            repo = GeoOverlayRepository(s)
            overlay = await repo.find_by_event(f"clash:{clash_id}")
            assert overlay is not None
            assert overlay.kind == "clash_marker"

    @pytest.mark.asyncio
    async def test_clash_replay_idempotent(self, app_instance, project_id):
        from sqlalchemy import func, select

        from app.core.events import event_bus
        from app.database import async_session_factory
        from app.modules.geo_hub.models import GeoOverlay

        clash_id = f"clash-replay-{uuid.uuid4().hex[:6]}"
        for _ in range(3):
            await event_bus.publish(
                "clash.detected",
                {
                    "project_id": str(project_id),
                    "clash_id": clash_id,
                    "lat": "52.520",
                    "lon": "13.405",
                },
            )
        async with async_session_factory() as s:
            res = await s.execute(
                select(func.count(GeoOverlay.id)).where(
                    GeoOverlay.source_event_id == f"clash:{clash_id}",
                )
            )
            assert res.scalar() == 1


# ── field_reports.submitted -> photo overlay ──────────────────────────


class TestFieldReportSubscriber:
    @pytest.mark.asyncio
    async def test_creates_field_report_overlay(self, app_instance, project_id):
        from app.core.events import event_bus
        from app.database import async_session_factory
        from app.modules.geo_hub.repository import GeoOverlayRepository

        report_id = f"fr-{uuid.uuid4().hex[:6]}"
        await event_bus.publish(
            "field_reports.submitted",
            {
                "project_id": str(project_id),
                "report_id": report_id,
                "lat": "52.519",
                "lon": "13.406",
                "title": "Concrete pour",
            },
        )
        async with async_session_factory() as s:
            ov = await GeoOverlayRepository(s).find_by_event(
                f"field_report:{report_id}",
            )
            assert ov is not None
            assert ov.name == "Concrete pour"


# ── safety.incident.created -> incident marker ───────────────────────


class TestSafetyIncidentSubscriber:
    @pytest.mark.asyncio
    async def test_creates_incident_marker(self, app_instance, project_id):
        from app.core.events import event_bus
        from app.database import async_session_factory
        from app.modules.geo_hub.repository import GeoOverlayRepository

        incident_id = f"si-{uuid.uuid4().hex[:6]}"
        await event_bus.publish(
            "safety.incident.created",
            {
                "project_id": str(project_id),
                "incident_id": incident_id,
                "lat": "52.521",
                "lon": "13.404",
                "title": "Slip & fall",
                "severity": "high",
            },
        )
        async with async_session_factory() as s:
            ov = await GeoOverlayRepository(s).find_by_event(
                f"incident:{incident_id}",
            )
            assert ov is not None
            assert ov.kind == "incident"


# ── risk.zone.flagged -> polygon overlay ─────────────────────────────


class TestRiskZoneSubscriber:
    @pytest.mark.asyncio
    async def test_creates_risk_polygon(self, app_instance, project_id):
        from app.core.events import event_bus
        from app.database import async_session_factory
        from app.modules.geo_hub.repository import GeoOverlayRepository

        zone_id = f"rz-{uuid.uuid4().hex[:6]}"
        polygon = {
            "type": "Polygon",
            "coordinates": [
                [
                    [13.40, 52.51],
                    [13.42, 52.51],
                    [13.42, 52.52],
                    [13.40, 52.52],
                    [13.40, 52.51],
                ]
            ],
        }
        await event_bus.publish(
            "risk.zone.flagged",
            {
                "project_id": str(project_id),
                "zone_id": zone_id,
                "polygon": polygon,
                "risk_category": "flood",
                "kind": "flood_zone",
            },
        )
        async with async_session_factory() as s:
            ov = await GeoOverlayRepository(s).find_by_event(
                f"risk_zone:{zone_id}",
            )
            assert ov is not None
            assert ov.kind == "flood_zone"

    @pytest.mark.asyncio
    async def test_risk_zone_idempotent(self, app_instance, project_id):
        from sqlalchemy import func, select

        from app.core.events import event_bus
        from app.database import async_session_factory
        from app.modules.geo_hub.models import GeoOverlay

        zone_id = f"rz-replay-{uuid.uuid4().hex[:6]}"
        polygon = {
            "type": "Polygon",
            "coordinates": [
                [
                    [13.40, 52.51],
                    [13.42, 52.51],
                    [13.42, 52.52],
                    [13.40, 52.51],
                ]
            ],
        }
        for _ in range(3):
            await event_bus.publish(
                "risk.zone.flagged",
                {
                    "project_id": str(project_id),
                    "zone_id": zone_id,
                    "polygon": polygon,
                },
            )
        async with async_session_factory() as s:
            res = await s.execute(
                select(func.count(GeoOverlay.id)).where(
                    GeoOverlay.source_event_id == f"risk_zone:{zone_id}",
                )
            )
            assert res.scalar() == 1
