"""Geo Hub cross-module event subscriber suite.

Verifies the marker subscribers fire when other modules publish domain
events. The address geocoding subscriber has its own suite in
``tests/modules/geo_hub/test_anchor_from_address.py``.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio


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
