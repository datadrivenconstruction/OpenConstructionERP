"""Permission gates of the survey endpoints: a read-only role can look but not write."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from .conftest import _login, _register, _set_role
from .test_geotiff_sniff import make_geotiff

BASE = "/api/v1/geo-hub/surveys"


@pytest_asyncio.fixture(scope="module")
async def viewer_headers(http_client):
    email, password = await _register(http_client, "viewer")
    await _set_role(email, "viewer")
    return await _login(http_client, email, password)


@pytest.mark.asyncio
async def test_viewer_cannot_create_update_or_delete(http_client, viewer_headers, tenant_a) -> None:
    files = {"file": ("s.tif", make_geotiff(), "image/tiff")}
    data = {"project_id": tenant_a["project_id"], "captured_on": "2026-03-11"}
    assert (
        await http_client.post(f"{BASE}/orthophoto", data=data, files=files, headers=viewer_headers)
    ).status_code == 403
    body = {"scan_id": str(uuid.uuid4())}
    assert (await http_client.post(f"{BASE}/from-scan", json=body, headers=viewer_headers)).status_code == 403
    sid = uuid.uuid4()
    assert (await http_client.patch(f"{BASE}/{sid}", json={"name": "x"}, headers=viewer_headers)).status_code == 403
    assert (
        await http_client.put(
            f"{BASE}/{sid}/observations/{uuid.uuid4()}", json={"observed_pct": "5"}, headers=viewer_headers
        )
    ).status_code == 403
    assert (await http_client.delete(f"{BASE}/{sid}", headers=viewer_headers)).status_code == 403


@pytest.mark.asyncio
async def test_anonymous_calls_are_refused(http_client, tenant_a) -> None:
    assert (await http_client.get(f"{BASE}/?project_id={tenant_a['project_id']}")).status_code in (401, 403)


def test_permissions_are_registered_with_the_expected_roles() -> None:
    from app.core.permissions import Role
    from app.modules.geo_hub.permissions import GEO_HUB_PERMISSIONS

    assert GEO_HUB_PERMISSIONS["geo_hub.create"] == Role.EDITOR
    assert GEO_HUB_PERMISSIONS["geo_hub.update"] == Role.EDITOR
    assert GEO_HUB_PERMISSIONS["geo_hub.read"] == Role.VIEWER
