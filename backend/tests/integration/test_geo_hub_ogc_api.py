# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""OGC API - Features integration suite.

Drives the service the way a GIS client does: land on the root, follow the
links to the collections, then page the items. What is gated here is the
part that cannot be checked from the pure functions:

* the whole point of serving this from the application rather than handing
  out a database credential - a caller sees exactly the projects they can
  already see, and nothing else;
* that the links a client follows actually resolve, rather than pointing at
  a prefix that happens to be right on the developer's machine;
* that paging is over FEATURES, not over overlay rows - an overlay holding
  several features would otherwise make page two start in the wrong place;
* that ``numberMatched`` agrees with what paging through actually returns.

Runs against the PostgreSQL cluster provisioned by ``conftest.py``.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

OGC = "/api/v1/geo-hub/ogc"


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.geo_hub import models as _geo_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def _set_role(email: str, role: str) -> None:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as session:
        await session.execute(update(User).where(User.email == email.lower()).values(role=role, is_active=True))
        await session.commit()


async def _account(client: AsyncClient, label: str, role: str) -> dict:
    email = f"{label}-{uuid.uuid4().hex[:8]}@ogc-geo.io"
    password = f"OgcGeo{uuid.uuid4().hex[:6]}9!"
    registered = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": label},
    )
    assert registered.status_code in (200, 201), registered.text
    await _set_role(email, role)
    logged_in = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    assert logged_in.status_code == 200, logged_in.text
    return {"email": email, "headers": {"Authorization": f"Bearer {logged_in.json()['access_token']}"}}


async def _project(client: AsyncClient, headers: dict, name: str) -> str:
    created = await client.post(
        "/api/v1/projects/",
        json={"name": f"{name} {uuid.uuid4().hex[:6]}", "description": name, "currency": "EUR"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


@pytest_asyncio.fixture(scope="module")
async def owner(http_client):
    """A non-admin owner, with one anchored project carrying overlays.

    Deliberately an editor rather than an admin: an admin sees every project
    on the instance, which would make the isolation assertions vacuous.
    """
    account = await _account(http_client, "ogc-owner", "editor")
    headers = account["headers"]
    project_id = await _project(http_client, headers, "OGC Owner")

    anchored = await http_client.post(
        "/api/v1/geo-hub/anchors/",
        json={
            "project_id": project_id,
            "lat": "52.5200",
            "lon": "13.4050",
            "alt": "34.0",
            "epsg_code": 4326,
            "region_code": "DE-BE",
            "address": "Alexanderplatz, Berlin",
        },
        headers=headers,
    )
    assert anchored.status_code == 201, anchored.text

    # One overlay holding THREE features. Paging over rows instead of
    # features would slice this in the wrong place, which is the bug the
    # paging tests below exist to catch.
    multi = await http_client.post(
        "/api/v1/geo-hub/overlays/",
        json={
            "project_id": project_id,
            "name": "Berlin site works",
            "kind": "boundary",
            "geojson": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [13.40, 52.51]},
                        "properties": {"label": "gate"},
                    },
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [13.41, 52.52]},
                        "properties": {"label": "crane"},
                    },
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [13.42, 52.53]},
                        "properties": {"label": "hoarding"},
                    },
                ],
            },
        },
        headers=headers,
    )
    assert multi.status_code == 201, multi.text

    # A second overlay, far away, so bbox filtering has something to exclude.
    far = await http_client.post(
        "/api/v1/geo-hub/overlays/",
        json={
            "project_id": project_id,
            "name": "Auckland site",
            "kind": "boundary",
            "geojson": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [174.76, -36.85]},
                        "properties": {"label": "far away"},
                    },
                ],
            },
        },
        headers=headers,
    )
    assert far.status_code == 201, far.text

    viewpoint = await http_client.post(
        "/api/v1/geo-hub/viewpoints/",
        json={
            "project_id": project_id,
            "name": "South approach",
            "camera_lat": "52.5100",
            "camera_lon": "13.4000",
            "camera_alt": "250.0",
            "heading": "180.0",
            "pitch": "-30.0",
            "roll": "0.0",
        },
        headers=headers,
    )
    assert viewpoint.status_code == 201, viewpoint.text

    return {
        "headers": headers,
        "project_id": project_id,
        "overlay_id": multi.json()["id"],
        "viewpoint_id": viewpoint.json()["id"],
    }


@pytest_asyncio.fixture(scope="module")
async def stranger(http_client):
    """A second editor with their own project and no access to the owner's."""
    account = await _account(http_client, "ogc-stranger", "editor")
    project_id = await _project(http_client, account["headers"], "OGC Stranger")
    return {"headers": account["headers"], "project_id": project_id}


# ── Landing page, conformance, collections ─────────────────────────────────


class TestServiceDocuments:
    @pytest.mark.asyncio
    async def test_landing_page_links_to_conformance_and_data(self, http_client, owner):
        res = await http_client.get(f"{OGC}/", headers=owner["headers"])
        assert res.status_code == 200, res.text
        rels = {item["rel"]: item["href"] for item in res.json()["links"]}
        assert "conformance" in rels
        assert "data" in rels
        assert rels["self"].endswith("/geo-hub/ogc")

    @pytest.mark.asyncio
    async def test_the_url_a_user_types_reaches_the_landing_page(self, http_client, owner):
        """A QGIS user pastes the root with no trailing slash. It must land."""
        res = await http_client.get(OGC, headers=owner["headers"], follow_redirects=True)
        assert res.status_code == 200, res.text
        assert res.json()["title"]

    @pytest.mark.asyncio
    async def test_every_link_on_the_landing_page_resolves(self, http_client, owner):
        """A client walks this service by following links. A link that 404s
        is the whole service being unreachable, not a cosmetic defect."""
        landing = await http_client.get(f"{OGC}/", headers=owner["headers"])
        for item in landing.json()["links"]:
            if item["rel"] == "service-desc":
                continue  # the OpenAPI schema is not part of this service
            followed = await http_client.get(item["href"], headers=owner["headers"])
            assert followed.status_code == 200, f"{item['rel']} -> {item['href']}: {followed.status_code}"

    @pytest.mark.asyncio
    async def test_a_client_can_walk_from_the_landing_page_down_to_features(self, http_client, owner):
        """The whole promise is that a GIS client reaches data by following
        links, so walk the path it walks: landing -> data -> every collection's
        self and items. Those links are built at four different depths below
        the service root, and an off-by-one in any one of them stays silent
        until a client hits it.
        """
        landing = await http_client.get(f"{OGC}/", headers=owner["headers"])
        data_href = next(item["href"] for item in landing.json()["links"] if item["rel"] == "data")

        collections = await http_client.get(data_href, headers=owner["headers"])
        assert collections.status_code == 200
        listed = collections.json()["collections"]
        assert listed, "the walk proves nothing if there is nothing to walk to"

        for collection in listed:
            for rel in ("self", "items"):
                href = next(item["href"] for item in collection["links"] if item["rel"] == rel)
                followed = await http_client.get(href, headers=owner["headers"])
                assert followed.status_code == 200, f"{collection['id']} {rel} -> {href}"
                if rel == "items":
                    assert followed.json()["type"] == "FeatureCollection"

    @pytest.mark.asyncio
    async def test_conformance_lists_the_core_classes(self, http_client, owner):
        res = await http_client.get(f"{OGC}/conformance", headers=owner["headers"])
        assert res.status_code == 200
        assert "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core" in res.json()["conformsTo"]

    @pytest.mark.asyncio
    async def test_collections_are_described_with_crs_and_item_links(self, http_client, owner):
        res = await http_client.get(f"{OGC}/collections", headers=owner["headers"])
        assert res.status_code == 200
        by_id = {collection["id"]: collection for collection in res.json()["collections"]}
        assert {"project-anchors", "geo-overlays", "viewpoints"} <= set(by_id)
        overlays = by_id["geo-overlays"]
        assert overlays["itemType"] == "feature"
        assert overlays["storageCrs"] == "http://www.opengis.net/def/crs/OGC/1.3/CRS84"
        assert any(item["rel"] == "items" for item in overlays["links"])
        # The collection has to SAY it spans projects; a client cannot guess it.
        assert overlays["projectScoped"] is True

    @pytest.mark.asyncio
    async def test_one_collection_can_be_described_on_its_own(self, http_client, owner):
        res = await http_client.get(f"{OGC}/collections/viewpoints", headers=owner["headers"])
        assert res.status_code == 200
        assert res.json()["id"] == "viewpoints"

    @pytest.mark.asyncio
    async def test_unknown_collection_is_404(self, http_client, owner):
        res = await http_client.get(f"{OGC}/collections/nope", headers=owner["headers"])
        assert res.status_code == 404


# ── Authentication ─────────────────────────────────────────────────────────


class TestAuthentication:
    @pytest.mark.asyncio
    async def test_anonymous_callers_get_nothing(self, http_client):
        """The reason we serve this instead of handing out a DB credential."""
        for path in ("/", "/conformance", "/collections", "/collections/geo-overlays/items"):
            res = await http_client.get(f"{OGC}{path}")
            assert res.status_code == 401, f"{path} answered {res.status_code} to an anonymous caller"

    @pytest.mark.asyncio
    async def test_an_api_key_reaches_the_same_data_as_its_owner(self, http_client, owner):
        """QGIS cannot refresh a JWT, so the API-key path is the usable one."""
        created = await http_client.post(
            "/api/v1/users/me/api-keys/",
            json={"name": f"qgis-{uuid.uuid4().hex[:6]}", "description": "QGIS"},
            headers=owner["headers"],
        )
        assert created.status_code in (200, 201), created.text
        raw_key = created.json()["key"]

        res = await http_client.get(
            f"{OGC}/collections/geo-overlays/items",
            params={"project_id": owner["project_id"]},
            headers={"X-API-Key": raw_key},
        )
        assert res.status_code == 200, res.text
        assert res.json()["numberMatched"] == 4


# ── Items ──────────────────────────────────────────────────────────────────


class TestItems:
    @pytest.mark.asyncio
    async def test_overlays_come_back_as_geojson(self, http_client, owner):
        res = await http_client.get(
            f"{OGC}/collections/geo-overlays/items",
            params={"project_id": owner["project_id"]},
            headers=owner["headers"],
        )
        assert res.status_code == 200, res.text
        assert res.headers["content-type"].startswith("application/geo+json")
        body = res.json()
        assert body["type"] == "FeatureCollection"
        # Three features in one overlay plus one in the other: four, not two.
        assert body["numberMatched"] == 4
        assert body["numberReturned"] == 4
        labels = {feature["properties"].get("label") for feature in body["features"]}
        assert {"gate", "crane", "hoarding", "far away"} == labels

    @pytest.mark.asyncio
    async def test_anchor_collection_carries_the_project(self, http_client, owner):
        res = await http_client.get(
            f"{OGC}/collections/project-anchors/items",
            params={"project_id": owner["project_id"]},
            headers=owner["headers"],
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["numberMatched"] == 1
        feature = body["features"][0]
        assert feature["id"] == owner["project_id"]
        assert feature["geometry"]["coordinates"] == [13.405, 52.52]

    @pytest.mark.asyncio
    async def test_viewpoints_come_back_as_points(self, http_client, owner):
        res = await http_client.get(
            f"{OGC}/collections/viewpoints/items",
            params={"project_id": owner["project_id"]},
            headers=owner["headers"],
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["numberMatched"] == 1
        assert body["features"][0]["properties"]["heading_deg"] == 180.0

    @pytest.mark.asyncio
    async def test_bbox_narrows_to_the_area_asked_for(self, http_client, owner):
        res = await http_client.get(
            f"{OGC}/collections/geo-overlays/items",
            params={"project_id": owner["project_id"], "bbox": "13.0,52.0,14.0,53.0"},
            headers=owner["headers"],
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["numberMatched"] == 3
        assert "far away" not in {feature["properties"].get("label") for feature in body["features"]}

    @pytest.mark.asyncio
    async def test_paging_walks_features_not_rows(self, http_client, owner):
        """One overlay holds three features. Paging two at a time must not
        skip an overlay's tail - a SQL OFFSET over rows would.
        """
        seen: list[str] = []
        url = f"{OGC}/collections/geo-overlays/items?project_id={owner['project_id']}&limit=2"
        for _ in range(10):
            res = await http_client.get(url, headers=owner["headers"])
            assert res.status_code == 200, res.text
            body = res.json()
            seen.extend(feature["id"] for feature in body["features"])
            following = [item["href"] for item in body["links"] if item["rel"] == "next"]
            if not following:
                break
            url = following[0]
        assert len(seen) == 4
        assert len(set(seen)) == 4, "paging returned the same feature twice"

    @pytest.mark.asyncio
    async def test_a_single_feature_can_be_fetched_by_its_id(self, http_client, owner):
        listed = await http_client.get(
            f"{OGC}/collections/geo-overlays/items",
            params={"project_id": owner["project_id"], "limit": 1},
            headers=owner["headers"],
        )
        feature_id = listed.json()["features"][0]["id"]
        res = await http_client.get(
            f"{OGC}/collections/geo-overlays/items/{feature_id}",
            headers=owner["headers"],
        )
        assert res.status_code == 200, res.text
        assert res.json()["id"] == feature_id
        assert any(item["rel"] == "self" for item in res.json()["links"])

    @pytest.mark.asyncio
    async def test_unknown_feature_is_404(self, http_client, owner):
        res = await http_client.get(
            f"{OGC}/collections/geo-overlays/items/{uuid.uuid4()}:0",
            headers=owner["headers"],
        )
        assert res.status_code == 404

    @pytest.mark.asyncio
    async def test_datetime_filters_the_collections_that_have_a_time(self, http_client, owner):
        past = await http_client.get(
            f"{OGC}/collections/geo-overlays/items",
            params={"project_id": owner["project_id"], "datetime": "2000-01-01T00:00:00Z/2001-01-01T00:00:00Z"},
            headers=owner["headers"],
        )
        assert past.status_code == 200
        assert past.json()["numberMatched"] == 0

        present = await http_client.get(
            f"{OGC}/collections/geo-overlays/items",
            params={"project_id": owner["project_id"], "datetime": "2000-01-01T00:00:00Z/.."},
            headers=owner["headers"],
        )
        assert present.json()["numberMatched"] == 4

    @pytest.mark.asyncio
    async def test_datetime_on_a_timeless_collection_is_refused_not_ignored(self, http_client, owner):
        """Silently ignoring an unsupported filter hands back the wrong set."""
        res = await http_client.get(
            f"{OGC}/collections/project-anchors/items",
            params={"datetime": "2000-01-01T00:00:00Z/.."},
            headers=owner["headers"],
        )
        assert res.status_code == 400

    @pytest.mark.asyncio
    async def test_a_broken_bbox_is_a_400_with_a_reason(self, http_client, owner):
        res = await http_client.get(
            f"{OGC}/collections/geo-overlays/items",
            params={"bbox": "13.0,52.0,14.0"},
            headers=owner["headers"],
        )
        assert res.status_code == 400
        assert "bbox" in res.json()["detail"]

    @pytest.mark.asyncio
    async def test_an_unsupported_format_is_refused_rather_than_served_as_json(self, http_client, owner):
        res = await http_client.get(
            f"{OGC}/collections/geo-overlays/items",
            params={"f": "html"},
            headers=owner["headers"],
        )
        assert res.status_code == 400


# ── Isolation ──────────────────────────────────────────────────────────────


class TestIsolation:
    @pytest.mark.tenant_isolation
    @pytest.mark.asyncio
    async def test_a_stranger_sees_none_of_the_owners_features(self, http_client, owner, stranger):
        for collection in ("project-anchors", "geo-overlays", "viewpoints"):
            res = await http_client.get(
                f"{OGC}/collections/{collection}/items",
                headers=stranger["headers"],
            )
            assert res.status_code == 200, res.text
            projects = {feature["properties"].get("project_id") for feature in res.json()["features"]}
            assert owner["project_id"] not in projects, f"{collection} leaked the owner's project"

    @pytest.mark.tenant_isolation
    @pytest.mark.asyncio
    async def test_narrowing_to_someone_elses_project_is_404_not_empty(self, http_client, owner, stranger):
        """404, not 200-with-nothing: an empty page would confirm the id exists."""
        res = await http_client.get(
            f"{OGC}/collections/geo-overlays/items",
            params={"project_id": owner["project_id"]},
            headers=stranger["headers"],
        )
        assert res.status_code == 404

    @pytest.mark.tenant_isolation
    @pytest.mark.asyncio
    async def test_fetching_someone_elses_feature_by_id_is_404(self, http_client, owner, stranger):
        res = await http_client.get(
            f"{OGC}/collections/geo-overlays/items/{owner['overlay_id']}:0",
            headers=stranger["headers"],
        )
        assert res.status_code == 404

    @pytest.mark.tenant_isolation
    @pytest.mark.asyncio
    async def test_fetching_someone_elses_viewpoint_by_id_is_404(self, http_client, owner, stranger):
        res = await http_client.get(
            f"{OGC}/collections/viewpoints/items/{owner['viewpoint_id']}",
            headers=stranger["headers"],
        )
        assert res.status_code == 404


# ── XYZ basemap tiles (task C) ─────────────────────────────────────────────


class TestTileEndpointIsDiscoverable:
    @pytest.mark.asyncio
    async def test_the_tile_route_is_in_the_openapi_schema(self, app_instance):
        """A QGIS user has to be able to FIND the XYZ template.

        The route worked before, but ``include_in_schema=False`` kept it out
        of the API description, so the only way to learn the URL was to read
        the source.

        The canonical spelling is ``/basemap/...``. ``/tiles/...`` is the older
        one, still served by the same handler but deliberately hidden from the
        schema so the description advertises one name rather than two. This
        test asked the schema for the hidden alias and therefore failed on
        every run after the rename, while the thing it cares about - a
        discoverable XYZ template - had been true the whole time. Both halves
        are pinned here: the canonical path is published and self-describing,
        and the alias still exists so QGIS connections saved against it keep
        working.
        """
        schema = app_instance.openapi()
        path = "/api/v1/geo-hub/basemap/{z}/{x}/{y}.png"
        assert path in schema["paths"], "the XYZ basemap route is not published"
        operation = schema["paths"][path]["get"]
        assert path in operation.get("description", "")
        assert "XYZ" in operation.get("summary", "")

        # Asked of ``served_paths`` rather than of ``app.routes``: from FastAPI
        # 0.141 an included router is one marker entry in ``app.routes`` with
        # no ``path`` of its own, so a scan of that list finds no module route
        # at all and reports the alias missing while it serves.
        from app.core.module_loader import served_paths

        alias = "/api/v1/geo-hub/tiles/{z}/{x}/{y}.png"
        assert alias in set(served_paths(app_instance)), "the older /tiles/ spelling must keep serving, hidden or not"
