"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The licence endpoints as the real application mounts them.

``tests/unit/test_license_texts_route.py`` mounts the router on a bare app and
covers its behaviour. That leaves one thing unproven and it is the one that
makes the difference between a feature and a file: whether ``create_app``
actually includes the router. A route that exists and is not mounted looks
exactly like a route that was never written, from the only place a user
stands.

No lifespan is entered. These endpoints read files and touch no database, so
starting one would buy nothing and cost a schema creation over 190 modules.
"""

from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.license_texts import license_dir


@pytest_asyncio.fixture(scope="module")
async def app_client():
    from app.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestLicenseTextsAPI:
    """The bundled licence texts are readable from the running product."""

    async def test_the_app_mounts_the_listing(self, app_client: AsyncClient) -> None:
        resp = await app_client.get("/api/v1/licenses/")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        on_disk = {p.name for p in license_dir().iterdir() if p.is_file() and not p.name.startswith(".")}
        assert {item["name"] for item in body["items"]} == on_disk
        assert body["total"] == len(on_disk)

    async def test_the_app_mounts_the_text_route(self, app_client: AsyncClient) -> None:
        resp = await app_client.get("/api/v1/licenses/LICENSE_LGPL_3_0")
        assert resp.status_code == 200, resp.text
        assert "GNU LESSER GENERAL PUBLIC LICENSE" in resp.json()["text"]

    async def test_both_routes_are_public(self, app_client: AsyncClient) -> None:
        """No Authorization header is sent anywhere in this file.

        Worth its own name because the whole point is the offline desktop
        install, where somebody may be looking at the licence long before they
        have an account on the thing.
        """
        assert (await app_client.get("/api/v1/licenses/")).status_code == 200
        assert (await app_client.get("/api/v1/licenses/LICENSE_GPL_3_0")).status_code == 200

    async def test_an_unknown_name_is_a_plain_404(self, app_client: AsyncClient) -> None:
        resp = await app_client.get("/api/v1/licenses/LICENSE_NOT_A_THING")
        assert resp.status_code == 404
        assert "LICENSE_NOT_A_THING" in resp.json()["detail"]
