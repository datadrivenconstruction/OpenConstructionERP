"""Project location: one reconciled point for the address and the geo-hub anchor."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio

from app.modules.geo_hub import coord_reconcile as cr
from app.modules.geo_hub.models import GeoAnchor
from app.modules.geo_hub.repairs import reconcile_project_locations
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

D = Decimal
NEAR = (D("38.8895"), D("-77.0353"))
FAR = (D("38.9"), D("-90.5"))


def test_server_geocode_wins_over_unattributed_client_pair_and_flags_it():
    d = cr.reconcile(FAR, None, NEAR)
    assert (d.lat, d.lon, d.source) == (NEAR[0], NEAR[1], "geocoder")
    assert d.conflict["lng"] == float(FAR[1]) and d.conflict["distance_km"] > 1000


def test_picked_suggestion_wins_but_a_large_gap_is_flagged():
    d = cr.reconcile(FAR, "suggestion", NEAR)
    assert (d.lat, d.lon, d.source) == (FAR[0], FAR[1], "suggestion")
    assert d.conflict["source"] == "geocoder"


def test_moved_pin_is_final_and_not_flagged():
    d = cr.reconcile(FAR, "pin", NEAR)
    assert (d.lat, d.lon) == FAR and d.conflict is None


def test_small_gap_is_not_a_conflict_and_missing_sides_fall_back():
    assert cr.reconcile((D("38.8896"), D("-77.0354")), None, NEAR).conflict is None
    assert cr.reconcile(None, None, NEAR).source == "geocoder"
    assert cr.reconcile(FAR, None, None).source == "project_coordinates"
    assert cr.reconcile(None, None, None) is None


def test_apply_writes_provenance_and_clears_a_resolved_conflict():
    addr = cr.apply_to_address({"city": "X", "coord_conflict": {"lat": 1}}, cr.reconcile(None, None, NEAR), "t0")
    assert addr["lat"] == float(NEAR[0]) and addr["coord_source"] == "geocoder" and addr["coord_at"] == "t0"
    assert "coord_conflict" not in addr


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        yield s


async def _project(session, address, anchor_point, source="nominatim"):
    user = User(email=f"g-{uuid.uuid4().hex}@test.local", hashed_password="x", full_name="U")
    session.add(user)
    await session.flush()
    project = Project(name="Site", owner_id=user.id, address=address)
    session.add(project)
    await session.flush()
    anchor = GeoAnchor(
        project_id=project.id,
        lat=anchor_point[0],
        lon=anchor_point[1],
        alt=D("0"),
        epsg_code=4326,
        metadata_={"geocoded_from": "project_address", "geocode_source": source},
    )
    session.add(anchor)
    await session.flush()
    return project, anchor


@pytest.mark.asyncio
async def test_repair_moves_unattributed_pair_to_the_anchor_and_is_idempotent(session):
    project, anchor = await _project(session, {"country": "US", "lat": float(FAR[0]), "lng": float(FAR[1])}, NEAR)
    assert await reconcile_project_locations(session) == 1
    await session.refresh(project)
    assert project.address["lng"] == pytest.approx(float(NEAR[1]))
    assert project.address["coord_source"] == "geocoder"
    assert project.address["coord_conflict"]["lng"] == float(FAR[1])
    assert await reconcile_project_locations(session) == 0


@pytest.mark.asyncio
async def test_repair_keeps_a_picked_point_and_only_flags(session):
    addr = {"country": "US", "lat": float(FAR[0]), "lng": float(FAR[1]), "coord_source": "suggestion"}
    project, _ = await _project(session, addr, NEAR)
    assert await reconcile_project_locations(session) == 1
    await session.refresh(project)
    assert project.address["lng"] == float(FAR[1])
    assert project.address["coord_conflict"]["lng"] == pytest.approx(float(NEAR[1]))
    assert await reconcile_project_locations(session) == 0


@pytest.mark.asyncio
async def test_repair_skips_agreeing_and_manual_anchors(session):
    await _project(session, {"country": "US", "lat": 38.8896, "lng": -77.0354}, NEAR)
    await _project(
        session, {"country": "US", "lat": float(FAR[0]), "lng": float(FAR[1])}, NEAR, source="project_coordinates"
    )
    assert await reconcile_project_locations(session) == 0
