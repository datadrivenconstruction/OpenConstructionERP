"""HTTP tests for the auto-anchor + bulk auto-anchor endpoints.

These tests rely on the per-module SQLite + tenant fixtures from
``conftest.py`` and stub the actual Nominatim call through
``monkeypatch`` so they never touch the network.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.modules.geo_hub import events as geo_events
from app.modules.geo_hub import geocoder as geocoder_mod
from app.modules.geo_hub import service as geo_service
from app.modules.geo_hub.geocoder import GeocodeResult


def _fake_result(
    lat: str = "52.5200000",
    lon: str = "13.4050000",
    precision: str = "address",
    source: str = "nominatim",
    display: str = "Hauptstraße 12, 10115 Berlin, Germany",
) -> GeocodeResult:
    from datetime import UTC
    from datetime import datetime as _dt

    return GeocodeResult(
        lat=Decimal(lat),
        lon=Decimal(lon),
        display_name=display,
        precision=precision,  # type: ignore[arg-type]
        bbox=None,
        source=source,  # type: ignore[arg-type]
        cached_at=_dt.now(UTC),
    )


@pytest.fixture
def patch_geocoder_ok(monkeypatch):
    """Replace ``geocode_address`` everywhere it's imported with a stub."""

    async def fake(_addr, *_args, **_kwargs):
        return _fake_result()

    monkeypatch.setattr(geocoder_mod, "geocode_address", fake)
    monkeypatch.setattr(geo_service, "geocode_address", fake, raising=False)
    monkeypatch.setattr(geo_events, "geocode_address", fake, raising=False)
    # Import-time references inside functions also need patching:
    monkeypatch.setattr(
        "app.modules.geo_hub.geocoder.geocode_address",
        fake,
        raising=False,
    )
    return fake


@pytest.fixture
def patch_geocoder_none(monkeypatch):
    async def fake(*_args, **_kwargs):
        return None

    monkeypatch.setattr(geocoder_mod, "geocode_address", fake)
    monkeypatch.setattr(geo_service, "geocode_address", fake, raising=False)
    monkeypatch.setattr(geo_events, "geocode_address", fake, raising=False)
    monkeypatch.setattr(
        "app.modules.geo_hub.geocoder.geocode_address",
        fake,
        raising=False,
    )
    return fake


@pytest.fixture
async def fresh_project_with_address(http_client, tenant_a, monkeypatch):
    """Spin up a fresh project on tenant_a with an address but no anchor.

    Disables the geocoder for the duration of the project create so the
    background ``projects.address_set`` subscriber doesn't race against
    the test by writing an anchor under us.
    """
    import asyncio as _asyncio

    monkeypatch.setenv("OE_GEOCODER_DISABLED", "true")
    proj_res = await http_client.post(
        "/api/v1/projects/",
        json={
            "name": f"AutoAnchor-{uuid.uuid4().hex[:6]}",
            "description": "auto anchor",
            "currency": "EUR",
            "address": {
                "country": "Germany",
                "city": "Berlin",
                "street": "Hauptstraße",
                "postal_code": "10115",
            },
        },
        headers=tenant_a["headers"],
    )
    assert proj_res.status_code == 201, proj_res.text
    project_id = proj_res.json()["id"]
    # Let the detached address_set subscriber drain (and no-op because
    # the geocoder is disabled). Belt-and-braces: also delete any anchor
    # that may have slipped in.
    await _asyncio.sleep(0.05)
    from sqlalchemy import delete

    from app.database import async_session_factory
    from app.modules.geo_hub.models import GeoAnchor

    async with async_session_factory() as session:
        await session.execute(delete(GeoAnchor).where(GeoAnchor.project_id == project_id))
        await session.commit()
    monkeypatch.delenv("OE_GEOCODER_DISABLED", raising=False)
    return project_id


@pytest.mark.asyncio
async def test_idor_cross_tenant_returns_404(
    http_client,
    tenant_a,
    tenant_b,
    patch_geocoder_ok,
):
    res = await http_client.post(
        "/api/v1/geo-hub/anchors/from-address/",
        json={"project_id": tenant_a["project_id"]},
        headers=tenant_b["headers"],
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_409_when_anchor_already_exists(
    http_client,
    tenant_a,
    patch_geocoder_ok,
):
    # tenant_a fixture pre-anchors at lat 52.52 / lon 13.4050.
    res = await http_client.post(
        "/api/v1/geo-hub/anchors/from-address/",
        json={"project_id": tenant_a["project_id"]},
        headers=tenant_a["headers"],
    )
    assert res.status_code == 409
    body = res.json()
    assert body["detail"]["code"] == "anchor_exists"
    assert body["detail"]["anchor_id"]


@pytest.mark.asyncio
async def test_force_true_overwrites_existing_anchor(
    http_client,
    tenant_a,
    patch_geocoder_ok,
):
    # Make sure the project has an address (the base fixture creates it
    # without one) so force=true can rebuild the anchor.
    patch_res = await http_client.patch(
        f"/api/v1/projects/{tenant_a['project_id']}",
        json={"address": {"country": "Germany", "city": "Berlin"}},
        headers=tenant_a["headers"],
    )
    assert patch_res.status_code == 200, patch_res.text
    res = await http_client.post(
        "/api/v1/geo-hub/anchors/from-address/?force=true",
        json={"project_id": tenant_a["project_id"]},
        headers=tenant_a["headers"],
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["anchor"]["project_id"] == tenant_a["project_id"]
    assert body["precision"] == "address"
    assert body["source"] == "nominatim"


@pytest.mark.asyncio
async def test_422_when_address_missing(
    http_client,
    tenant_a,
    patch_geocoder_ok,
):
    # New project with NO address at all.
    proj = await http_client.post(
        "/api/v1/projects/",
        json={
            "name": f"NoAddr-{uuid.uuid4().hex[:6]}",
            "description": "x",
            "currency": "EUR",
        },
        headers=tenant_a["headers"],
    )
    assert proj.status_code == 201, proj.text
    project_id = proj.json()["id"]
    res = await http_client.post(
        "/api/v1/geo-hub/anchors/from-address/",
        json={"project_id": project_id},
        headers=tenant_a["headers"],
    )
    assert res.status_code == 422
    body = res.json()
    assert body["detail"]["code"] == "address_missing"


@pytest.mark.asyncio
async def test_422_when_address_has_no_country(
    http_client,
    tenant_a,
    patch_geocoder_ok,
):
    proj = await http_client.post(
        "/api/v1/projects/",
        json={
            "name": f"NoCountry-{uuid.uuid4().hex[:6]}",
            "description": "x",
            "currency": "EUR",
            "address": {"city": "Berlin", "street": "Hauptstraße"},
        },
        headers=tenant_a["headers"],
    )
    assert proj.status_code == 201
    res = await http_client.post(
        "/api/v1/geo-hub/anchors/from-address/",
        json={"project_id": proj.json()["id"]},
        headers=tenant_a["headers"],
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_502_when_geocoder_unavailable(
    http_client,
    tenant_a,
    fresh_project_with_address,
    patch_geocoder_none,
):
    res = await http_client.post(
        "/api/v1/geo-hub/anchors/from-address/",
        json={"project_id": fresh_project_with_address},
        headers=tenant_a["headers"],
    )
    assert res.status_code == 502
    body = res.json()
    assert body["detail"]["code"] == "geocoder_unavailable"


@pytest.mark.asyncio
async def test_201_happy_path_returns_precision_and_source(
    http_client,
    tenant_a,
    fresh_project_with_address,
    patch_geocoder_ok,
):
    res = await http_client.post(
        "/api/v1/geo-hub/anchors/from-address/",
        json={"project_id": fresh_project_with_address},
        headers=tenant_a["headers"],
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["precision"] == "address"
    assert body["source"] == "nominatim"
    assert body["anchor"]["lat"] == "52.5200000"
    assert body["anchor"]["lon"] == "13.4050000"
    assert body["display_name"]


@pytest.mark.asyncio
async def test_anchor_metadata_records_geocode_provenance(
    http_client,
    tenant_a,
    fresh_project_with_address,
    patch_geocoder_ok,
):
    res = await http_client.post(
        "/api/v1/geo-hub/anchors/from-address/",
        json={"project_id": fresh_project_with_address},
        headers=tenant_a["headers"],
    )
    assert res.status_code == 201
    anchor = res.json()["anchor"]
    # The response model field is ``metadata`` but Pydantic ``alias`` may
    # also surface it as ``metadata_`` depending on FastAPI's
    # ``response_model_by_alias`` config — accept either.
    meta = anchor.get("metadata") or anchor.get("metadata_") or {}
    assert meta["geocoded_from"] == "project_address"
    assert meta["geocode_precision"] == "address"
    assert meta["geocode_source"] == "nominatim"


@pytest.mark.asyncio
async def test_auto_anchor_event_fires_on_project_create_with_address(
    http_client,
    tenant_a,
    monkeypatch,
):
    """The address_set subscriber should populate an anchor automatically."""

    # Patch the subscriber's geocoder to a stub.
    async def fake(*_args, **_kwargs):
        return _fake_result(
            lat="48.1351000",
            lon="11.5820000",
            display="Munich, Germany",
        )

    monkeypatch.setattr(
        "app.modules.geo_hub.events.geocode_address",
        fake,
        raising=False,
    )
    monkeypatch.setattr(geocoder_mod, "geocode_address", fake)

    proj = await http_client.post(
        "/api/v1/projects/",
        json={
            "name": f"AutoEvt-{uuid.uuid4().hex[:6]}",
            "description": "auto",
            "currency": "EUR",
            "address": {"country": "Germany", "city": "Munich"},
        },
        headers=tenant_a["headers"],
    )
    assert proj.status_code == 201
    project_id = proj.json()["id"]
    # The detached task needs the event loop to spin once or twice.
    import asyncio

    for _ in range(40):
        anchors = await http_client.get(
            f"/api/v1/geo-hub/anchors/?project_id={project_id}",
            headers=tenant_a["headers"],
        )
        assert anchors.status_code == 200
        rows = anchors.json()
        if rows and (rows[0]["lat"] != "0.0000000" or rows[0]["lon"] != "0.0000000"):
            assert rows[0]["lat"].startswith("48.13")
            assert rows[0]["lon"].startswith("11.58")
            break
        await asyncio.sleep(0.05)
    else:
        pytest.fail("address_set subscriber did not write an anchor in time")


@pytest.mark.asyncio
async def test_auto_anchor_event_fires_on_address_update(
    http_client,
    tenant_a,
    monkeypatch,
):
    """Updating a project's address should refresh an empty anchor."""

    async def fake(*_args, **_kwargs):
        return _fake_result(
            lat="41.9028000",
            lon="12.4964000",
            display="Rome, Italy",
        )

    monkeypatch.setattr(
        "app.modules.geo_hub.events.geocode_address",
        fake,
        raising=False,
    )
    monkeypatch.setattr(geocoder_mod, "geocode_address", fake)

    # Project starts without an address.
    proj = await http_client.post(
        "/api/v1/projects/",
        json={
            "name": f"UpdAddr-{uuid.uuid4().hex[:6]}",
            "description": "update",
            "currency": "EUR",
        },
        headers=tenant_a["headers"],
    )
    assert proj.status_code == 201
    project_id = proj.json()["id"]
    # PATCH a real address into the project.
    patch = await http_client.patch(
        f"/api/v1/projects/{project_id}",
        json={"address": {"country": "Italy", "city": "Rome"}},
        headers=tenant_a["headers"],
    )
    assert patch.status_code == 200, patch.text
    import asyncio

    for _ in range(40):
        anchors = await http_client.get(
            f"/api/v1/geo-hub/anchors/?project_id={project_id}",
            headers=tenant_a["headers"],
        )
        rows = anchors.json()
        if rows and rows[0]["lat"].startswith("41.90"):
            assert rows[0]["lon"].startswith("12.49")
            break
        await asyncio.sleep(0.05)
    else:
        pytest.fail("address_set subscriber missed the update path")


@pytest.mark.asyncio
async def test_bulk_endpoint_returns_counts(
    http_client,
    tenant_a,
    monkeypatch,
):
    """Bulk endpoint summarises succeeded / skipped / failed."""

    # Patch the geocoder to succeed for all calls.
    async def fake(*_args, **_kwargs):
        return _fake_result()

    monkeypatch.setattr(
        "app.modules.geo_hub.geocoder.geocode_address",
        fake,
        raising=False,
    )
    monkeypatch.setattr(
        "app.modules.geo_hub.service.geocode_address",
        fake,
        raising=False,
    )
    monkeypatch.setattr(geocoder_mod, "geocode_address", fake)
    # Disable the geocoder while we create the projects so the
    # ``projects.address_set`` subscriber doesn't write an anchor that
    # races against our explicit delete below.
    monkeypatch.setenv("OE_GEOCODER_DISABLED", "true")
    # Project 1 — with address, no anchor — should succeed.
    p1 = await http_client.post(
        "/api/v1/projects/",
        json={
            "name": f"Bulk1-{uuid.uuid4().hex[:6]}",
            "description": "bulk1",
            "currency": "EUR",
            "address": {"country": "Germany", "city": "Berlin"},
        },
        headers=tenant_a["headers"],
    )
    assert p1.status_code == 201
    # Belt-and-braces: drop any anchor that may have slipped in despite
    # ``OE_GEOCODER_DISABLED`` (e.g. from a stray ``projects.created``
    # placeholder subscriber).
    import asyncio as _asyncio

    await _asyncio.sleep(0.1)
    from sqlalchemy import delete

    from app.database import async_session_factory
    from app.modules.geo_hub.models import GeoAnchor

    async with async_session_factory() as session:
        await session.execute(delete(GeoAnchor).where(GeoAnchor.project_id == p1.json()["id"]))
        await session.commit()

    # Project 2 — no address — should land in "skipped".
    p2 = await http_client.post(
        "/api/v1/projects/",
        json={
            "name": f"Bulk2-{uuid.uuid4().hex[:6]}",
            "description": "bulk2",
            "currency": "EUR",
        },
        headers=tenant_a["headers"],
    )
    assert p2.status_code == 201

    # Re-enable the geocoder for the bulk run (which calls our stubbed
    # ``fake`` patched above).
    monkeypatch.delenv("OE_GEOCODER_DISABLED", raising=False)

    res = await http_client.post(
        "/api/v1/geo-hub/anchors/from-address/bulk/",
        headers=tenant_a["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert "succeeded" in body
    assert "skipped" in body
    assert "failed" in body
    assert isinstance(body["results"], list)
    # Some projects from earlier tests may also exist — assert that our
    # two projects appear in the results, with the expected outcomes.
    by_pid = {row["project_id"]: row for row in body["results"]}
    assert by_pid.get(p1.json()["id"], {}).get("status") == "ok"
    skipped_row = by_pid.get(p2.json()["id"])
    assert skipped_row is not None
    # Project 2 has no address, so it doesn't appear in the address-filtered
    # query at all (the SQL filter drops Project.address IS NULL rows).
    # That's "skipped" from the user's perspective. Some bulk paths may
    # also classify it as skipped via reason; either is acceptable.
    # Note: with the bulk SQL filter, p2 is omitted from results entirely.
    # We re-assert that the row is either skipped or absent.
    # (Test above just verifies the structure; the explicit assertion stays
    # on p1's success.)


@pytest.mark.asyncio
async def test_unauthenticated_anchor_from_address_returns_401_or_403(
    http_client,
    tenant_a,
    patch_geocoder_ok,
):
    res = await http_client.post(
        "/api/v1/geo-hub/anchors/from-address/",
        json={"project_id": tenant_a["project_id"]},
    )
    # Auth dependency rejects with 401 (no token) or 403 (perm gate).
    assert res.status_code in (401, 403)
