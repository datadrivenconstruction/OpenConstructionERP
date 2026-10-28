# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠An inspector flags a non-conformity and a pin appears on the map.

Two layers are gated here, and they fail differently.

The subscriber layer (``geo_hub._on_ncr_created``) is exercised by
publishing ``ncr.created`` directly. It has to draw a pin from the event
payload alone, be idempotent on replay, and stay quiet about the ordinary
case of an NCR with no coordinates.

The end-to-end layer goes through ``POST /api/v1/ncr/`` and is the one that
catches the bug the subscriber tests cannot see. Event subscribers open
their own sessions, so an event published from inside a still-open
transaction describes a row nothing else can read yet. The publish is
therefore deferred to ``after_commit``, and the only way to know that
actually holds is to create an NCR through the API and look for its pin.
That is what ``TestEndToEnd`` does; it is deliberately run several times,
because a race that is lost half the time passes a single-shot test half
the time too.
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.geo_hub import models as _geo_models  # noqa: F401
        from app.modules.ncr import models as _ncr_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def project_id(app_instance):
    """A fresh project per test, so replay tests start from nothing."""
    from app.database import async_session_factory
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user_id = uuid.uuid4()
    new_project_id = uuid.uuid4()
    async with async_session_factory() as session:
        session.add(
            User(
                id=user_id,
                email=f"ncr-pin-{uuid.uuid4().hex[:6]}@geo.io",
                full_name="NCR Pin",
                hashed_password="x" * 60,
                role="admin",
                is_active=True,
            ),
        )
        await session.flush()
        session.add(
            Project(
                id=new_project_id,
                name=f"NCR-Pin-{uuid.uuid4().hex[:6]}",
                description="",
                owner_id=user_id,
                currency="EUR",
            ),
        )
        await session.commit()
    return new_project_id


async def _find_pin(ncr_id: str):
    from app.database import async_session_factory
    from app.modules.geo_hub.repository import GeoOverlayRepository

    async with async_session_factory() as session:
        return await GeoOverlayRepository(session).find_by_event(f"ncr:{ncr_id}")


async def _await_pin(ncr_id: str, *, seconds: float = 10.0):
    """Poll for the pin the detached subscriber writes.

    The publish is detached on purpose - the request must not wait on
    subscribers that open their own writers - so a test that looked once
    would be asserting on scheduling luck.
    """
    deadline = asyncio.get_running_loop().time() + seconds
    while asyncio.get_running_loop().time() < deadline:
        overlay = await _find_pin(ncr_id)
        if overlay is not None:
            return overlay
        await asyncio.sleep(0.05)
    return None


# ── The subscriber ─────────────────────────────────────────────────────────


class TestSubscriber:
    @pytest.mark.asyncio
    async def test_a_located_ncr_gets_a_pin(self, app_instance, project_id):
        from app.core.events import event_bus

        ncr_id = str(uuid.uuid4())
        await event_bus.publish(
            "ncr.created",
            {
                "project_id": str(project_id),
                "ncr_id": ncr_id,
                "ncr_number": "NCR-004",
                "title": "Rebar cover below spec",
                "severity": "critical",
                "ncr_type": "workmanship",
                "status": "identified",
                "lat": "52.5200",
                "lon": "13.4050",
                "accuracy_m": "4.50",
            },
        )
        overlay = await _find_pin(ncr_id)
        assert overlay is not None
        assert overlay.kind == "ncr"
        assert overlay.name == "Rebar cover below spec"
        feature = overlay.geojson["features"][0]
        # CRS84 is longitude first. Reversed, this NCR is off the Somali coast.
        assert feature["geometry"]["coordinates"] == [13.405, 52.52]
        assert feature["properties"]["ncr_number"] == "NCR-004"
        assert feature["properties"]["severity"] == "critical"
        assert feature["properties"]["accuracy_m"] == "4.50"

    @pytest.mark.asyncio
    async def test_severity_reaches_the_pin_colour(self, app_instance, project_id):
        from app.core.events import event_bus

        drawn = {}
        for severity in ("critical", "observation", "not-a-severity"):
            ncr_id = str(uuid.uuid4())
            await event_bus.publish(
                "ncr.created",
                {
                    "project_id": str(project_id),
                    "ncr_id": ncr_id,
                    "severity": severity,
                    "lat": "52.52",
                    "lon": "13.405",
                },
            )
            overlay = await _find_pin(ncr_id)
            assert overlay is not None
            drawn[severity] = overlay.style["iconColor"]

        assert drawn["critical"] != drawn["observation"]
        # An unrecognised severity is still a non-conformity worth seeing.
        assert drawn["not-a-severity"]

    @pytest.mark.asyncio
    async def test_an_ncr_with_no_location_is_skipped_quietly(self, app_instance, project_id):
        """Most NCRs are raised against a drawing. That is not a failure."""
        from app.core.events import event_bus

        ncr_id = str(uuid.uuid4())
        result = await event_bus.publish(
            "ncr.created",
            {"project_id": str(project_id), "ncr_id": ncr_id, "title": "Missing test certificate"},
        )
        assert result.success
        assert await _find_pin(ncr_id) is None

    @pytest.mark.asyncio
    async def test_replay_does_not_duplicate_the_pin(self, app_instance, project_id):
        from sqlalchemy import select

        from app.core.events import event_bus
        from app.database import async_session_factory
        from app.modules.geo_hub.models import GeoOverlay

        ncr_id = str(uuid.uuid4())
        payload = {
            "project_id": str(project_id),
            "ncr_id": ncr_id,
            "severity": "minor",
            "lat": "52.52",
            "lon": "13.405",
        }
        await event_bus.publish("ncr.created", payload)
        await event_bus.publish("ncr.created", payload)

        async with async_session_factory() as session:
            found = await session.execute(select(GeoOverlay).where(GeoOverlay.source_event_id == f"ncr:{ncr_id}"))
            assert len(list(found.scalars().all())) == 1

    @pytest.mark.asyncio
    async def test_a_payload_with_no_project_is_ignored_not_raised(self, app_instance):
        from app.core.events import event_bus

        result = await event_bus.publish(
            "ncr.created",
            {"ncr_id": str(uuid.uuid4()), "lat": "52.52", "lon": "13.405"},
        )
        assert result.success

    @pytest.mark.asyncio
    async def test_an_unknown_ncr_is_still_pinned(self, app_instance, project_id):
        """The existence check is a regression detector, not a gate.

        If it ever became a gate, a subscriber that ran a moment early would
        stop drawing pins altogether - trading a rare stale marker for a
        routine missing one, which is the worse failure of the two.
        """
        from app.core.events import event_bus

        ncr_id = str(uuid.uuid4())  # no such NCR row anywhere
        await event_bus.publish(
            "ncr.created",
            {"project_id": str(project_id), "ncr_id": ncr_id, "lat": "52.52", "lon": "13.405"},
        )
        assert await _find_pin(ncr_id) is not None


# ── Through the API ────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def inspector(http_client):
    """A logged-in editor with a project they own."""
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    email = f"inspector-{uuid.uuid4().hex[:8]}@ncr-pin.io"
    password = f"NcrPin{uuid.uuid4().hex[:6]}9!"
    registered = await http_client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Inspector"},
    )
    assert registered.status_code in (200, 201), registered.text
    async with async_session_factory() as session:
        await session.execute(update(User).where(User.email == email.lower()).values(role="editor", is_active=True))
        await session.commit()
    logged_in = await http_client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    assert logged_in.status_code == 200, logged_in.text
    headers = {"Authorization": f"Bearer {logged_in.json()['access_token']}"}

    created = await http_client.post(
        "/api/v1/projects/",
        json={"name": f"NCR Pin {uuid.uuid4().hex[:6]}", "description": "", "currency": "EUR"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    return {"headers": headers, "project_id": created.json()["id"]}


class TestEndToEnd:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("attempt", range(5))
    async def test_creating_a_located_ncr_puts_it_on_the_map(self, http_client, inspector, attempt):
        """Repeated on purpose. The failure this guards against is a race.

        ``ncr.created`` used to be published from inside the request's open
        transaction, so a subscriber opening its own session saw an NCR that
        was not committed yet. A race lost half the time passes a single-shot
        test half the time, so this asks the same question five times.
        """
        created = await http_client.post(
            "/api/v1/ncr/",
            json={
                "project_id": inspector["project_id"],
                "title": f"Honeycombing to column C{attempt}",
                "description": "Voids visible over 300mm at the base of the pour.",
                "ncr_type": "workmanship",
                "severity": "major",
                "location_description": "Grid C4, level 2",
                "location_lat": "52.5163",
                "location_lon": "13.3777",
                "location_accuracy_m": "3.20",
            },
            headers=inspector["headers"],
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert Decimal(body["location_lat"]) == Decimal("52.5163")
        assert Decimal(body["location_accuracy_m"]) == Decimal("3.20")

        overlay = await _await_pin(body["id"])
        assert overlay is not None, "the NCR committed but no pin was ever drawn"
        assert overlay.kind == "ncr"
        assert overlay.geojson["features"][0]["geometry"]["coordinates"] == [13.3777, 52.5163]
        assert overlay.geojson["features"][0]["properties"]["ncr_number"] == body["ncr_number"]

    @pytest.mark.asyncio
    async def test_an_unlocated_ncr_creates_no_pin(self, http_client, inspector):
        created = await http_client.post(
            "/api/v1/ncr/",
            json={
                "project_id": inspector["project_id"],
                "title": "Mill certificate not supplied",
                "description": "Delivery arrived without the certificate.",
                "ncr_type": "documentation",
                "severity": "minor",
            },
            headers=inspector["headers"],
        )
        assert created.status_code == 201, created.text
        # Give the detached publish the same room the positive test gets, so
        # this cannot pass merely by looking too early.
        assert await _await_pin(created.json()["id"], seconds=2.0) is None

    @pytest.mark.asyncio
    async def test_half_a_position_is_refused_at_the_edge(self, http_client, inspector):
        created = await http_client.post(
            "/api/v1/ncr/",
            json={
                "project_id": inspector["project_id"],
                "title": "Half a location",
                "description": "Latitude only.",
                "ncr_type": "material",
                "severity": "minor",
                "location_lat": "52.52",
            },
            headers=inspector["headers"],
        )
        assert created.status_code == 422, created.text

    @pytest.mark.asyncio
    async def test_a_patch_may_correct_one_half_of_a_stored_position(self, http_client, inspector):
        created = await http_client.post(
            "/api/v1/ncr/",
            json={
                "project_id": inspector["project_id"],
                "title": "Position to be corrected",
                "description": "Surveyed again the next morning.",
                "ncr_type": "workmanship",
                "severity": "minor",
                "location_lat": "52.5163",
                "location_lon": "13.3777",
            },
            headers=inspector["headers"],
        )
        assert created.status_code == 201, created.text
        patched = await http_client.patch(
            f"/api/v1/ncr/{created.json()['id']}",
            json={"location_lon": "13.4000"},
            headers=inspector["headers"],
        )
        assert patched.status_code == 200, patched.text
        assert Decimal(patched.json()["location_lon"]) == Decimal("13.4")
        assert Decimal(patched.json()["location_lat"]) == Decimal("52.5163")

    @pytest.mark.asyncio
    async def test_a_patch_cannot_leave_half_a_position_behind(self, http_client, inspector):
        """Clearing only the latitude would leave a row that looks located."""
        created = await http_client.post(
            "/api/v1/ncr/",
            json={
                "project_id": inspector["project_id"],
                "title": "Position to be half-cleared",
                "description": "Someone deletes one field in the UI.",
                "ncr_type": "workmanship",
                "severity": "minor",
                "location_lat": "52.5163",
                "location_lon": "13.3777",
            },
            headers=inspector["headers"],
        )
        assert created.status_code == 201, created.text
        patched = await http_client.patch(
            f"/api/v1/ncr/{created.json()['id']}",
            json={"location_lat": None},
            headers=inspector["headers"],
        )
        assert patched.status_code == 400, patched.text

    @pytest.mark.asyncio
    async def test_a_patch_can_clear_the_whole_position(self, http_client, inspector):
        created = await http_client.post(
            "/api/v1/ncr/",
            json={
                "project_id": inspector["project_id"],
                "title": "Position to be cleared",
                "description": "The coordinates turned out to be the wrong site.",
                "ncr_type": "workmanship",
                "severity": "minor",
                "location_lat": "52.5163",
                "location_lon": "13.3777",
            },
            headers=inspector["headers"],
        )
        assert created.status_code == 201, created.text
        patched = await http_client.patch(
            f"/api/v1/ncr/{created.json()['id']}",
            json={"location_lat": None, "location_lon": None},
            headers=inspector["headers"],
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["location_lat"] is None
        assert patched.json()["location_lon"] is None


# ── The pin is readable by a GIS client ────────────────────────────────────


class TestThePinReachesTheOgcService:
    @pytest.mark.asyncio
    async def test_a_pinned_ncr_shows_up_in_the_overlays_collection(self, http_client, inspector):
        """The point of the whole exercise: the pin is not just in a table."""
        created = await http_client.post(
            "/api/v1/ncr/",
            json={
                "project_id": inspector["project_id"],
                "title": "Slab level out of tolerance",
                "description": "Measured 22mm above datum against a 10mm tolerance.",
                "ncr_type": "workmanship",
                "severity": "major",
                "location_lat": "52.5000",
                "location_lon": "13.3000",
            },
            headers=inspector["headers"],
        )
        assert created.status_code == 201, created.text
        assert await _await_pin(created.json()["id"]) is not None

        served = await http_client.get(
            "/api/v1/geo-hub/ogc/collections/geo-overlays/items",
            params={"project_id": inspector["project_id"], "bbox": "13.2,52.4,13.4,52.6"},
            headers=inspector["headers"],
        )
        assert served.status_code == 200, served.text
        ncr_ids = {
            feature["properties"].get("ncr_id")
            for feature in served.json()["features"]
            if feature["properties"].get("overlay_kind") == "ncr"
        }
        assert created.json()["id"] in ncr_ids
