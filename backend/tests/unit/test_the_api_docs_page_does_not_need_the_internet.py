# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""``/api/docs`` has to render on an install with no way out to the internet.

FastAPI's stock docs route writes a page that loads ``swagger-ui-bundle.js``
and ``swagger-ui.css`` from ``cdn.jsdelivr.net``, and its favicon from
``fastapi.tiangolo.com``. On a machine with outbound access that is invisible.
On an air-gapped site, or a VPS behind an egress firewall, the shell arrives,
the browser cannot fetch the two files that turn it into Swagger UI, and the
operator gets a blank page with no error to search for. Self-hosting is the
premise of this platform rather than an edge case, so the assets ship in the
wheel and the page points at this install.

The test that matters here is not "the HTML changed". It is that the URLs the
page names are actually served, which is why every referenced asset is
requested and its bytes checked. Asserting only on the absence of the CDN
string would stay green if the vendored files were dropped from the package,
and that failure mode - a page referring to two local files that are not
there - looks exactly like the bug this replaced.

The page is also the one thing on the API surface a first-time operator is
told to open: the boot banner prints ``/api/docs`` under "Open in your
browser". A blank page there is the first impression.

Deliberately not covered: ``/api/redoc``. It keeps FastAPI's stock route and
still loads ``redoc.standalone.js`` from the same CDN, so it is still blank
offline. Vendoring it costs roughly another megabyte in the wheel and it is
not the page the banner advertises; the choice is recorded here rather than
left for somebody to discover as a surprise.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

#: Anything that would make the browser leave this host. ``//`` catches
#: protocol-relative URLs, which are easy to miss and just as fatal offline.
_EXTERNAL = re.compile(r"""(?:src|href)\s*=\s*["'](?:https?:)?//""", re.IGNORECASE)


@pytest.fixture(scope="module")
def client() -> TestClient:
    """The app without its lifespan, which is all this page needs.

    Entering ``TestClient`` as a context manager would run the startup
    handler: module loading, migrations, a database. The docs route and its
    assets are registered in ``create_app`` and depend on none of it.
    """
    return TestClient(create_app())


def test_the_docs_page_names_no_host_but_this_one(client: TestClient) -> None:
    response = client.get("/api/docs")

    assert response.status_code == 200
    offenders = _EXTERNAL.findall(response.text)
    assert not offenders, f"/api/docs still loads from another host: {offenders}"
    # The two specific origins this replaced, named so a failure says which
    # one came back rather than only that some URL is absolute.
    assert "cdn.jsdelivr.net" not in response.text
    assert "fastapi.tiangolo.com" not in response.text


def test_the_page_does_not_ask_the_browser_to_draw_every_operation(client: TestClient) -> None:
    """A document this size has to arrive collapsed.

    Swagger UI lays out whatever the schema holds, and this one holds 3938
    operations and 3601 component schemas. Timed in headless Chromium against
    the running app, the stock settings took 122.1s from navigation to the
    first tag section appearing, against 80.7s with these two parameters set;
    the difference is 7576 operation blocks and the models section that the
    browser no longer builds before it can show anything.

    Both numbers are bad, and the remaining cost is Swagger UI working through
    the document rather than anything the server does - caching the schema
    server-side cannot touch it. This asserts only the cheap half that is in
    our hands.
    """
    page = client.get("/api/docs").text

    assert '"docExpansion": "none"' in page
    assert '"defaultModelsExpandDepth": -1' in page


@pytest.mark.parametrize(
    ("filename", "content_type", "signature"),
    [
        ("swagger-ui-bundle.js", "application/javascript", b"SwaggerUIBundle"),
        ("swagger-ui.css", "text/css", b".swagger-ui"),
    ],
)
def test_every_asset_the_page_names_is_served(
    client: TestClient,
    filename: str,
    content_type: str,
    signature: bytes,
) -> None:
    """Fetch what the page asks for, and check it is the real library.

    The signature check is the point: a 200 carrying an HTML error page, or the
    SPA's ``index.html`` handed back by the catch-all, would satisfy a status
    assertion and leave the page just as blank as the CDN did.
    """
    page = client.get("/api/docs")
    assert f"/api/docs/assets/{filename}" in page.text, f"the page no longer loads {filename}"

    response = client.get(f"/api/docs/assets/{filename}")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(content_type)
    assert signature in response.content


def test_the_asset_route_serves_nothing_but_those_two_files(client: TestClient) -> None:
    """The route matches names against a table instead of mounting a directory.

    A ``StaticFiles`` mount would have put path traversal between the network
    and the installed package for the sake of two files. This asserts the
    refusal in both shapes: a plain unknown name, and a traversal attempt.
    """
    assert client.get("/api/docs/assets/swagger-ui-bundle.js.map").status_code == 404
    assert client.get("/api/docs/assets/..%2F..%2Fmain.py").status_code == 404


def _published_paths(app: object) -> set[str | None]:
    return {getattr(route, "path", None) for route in app.routes}  # type: ignore[attr-defined]


def test_production_publishes_no_route_that_could_serve_the_schema(client: TestClient) -> None:
    """Nothing in a production process can hand out the OpenAPI document.

    ``openapi_url`` is None there, and with no schema route there is no
    ``/api/docs`` and no ``/api/redoc`` either. This is the fact the startup
    prime relies on when it declines to run: building this document costs the
    better part of three minutes of CPU, and on a production box that would buy
    a cache with no reader, spent in the window where a health check is already
    answering slowly enough to look like a hung process.

    So this asserts the premise rather than the guard. If someone later decides
    the reference should be published in production, the prime has to be
    revisited in the same change, and this is what will say so.
    """
    from app.config import get_settings

    # First the same question of the app the rest of this file uses, so a
    # rename or a change of route class cannot turn the assertions below into
    # three true statements about a set that never held these paths anyway.
    reference = _published_paths(client.app)
    assert {"/api/docs", "/api/docs/assets/{filename}"} <= reference

    settings = get_settings()
    original = settings.app_env
    try:
        settings.app_env = "production"
        app = create_app()
    finally:
        settings.app_env = original

    assert app.openapi_url is None
    paths = _published_paths(app)
    assert "/api/docs" not in paths
    assert "/api/redoc" not in paths
    assert "/api/docs/assets/{filename}" not in paths


def test_the_schema_is_rebuilt_when_the_route_table_moves() -> None:
    """The cached schema must not outlive the routes it describes.

    ``create_app`` overrides ``app.openapi`` to stamp the DDC origin markers
    into ``info``, and the override caches. FastAPI's own implementation keys
    that cache on a counter the router bumps from every ``include_router`` and
    rebuilds when it moves; an override that checks only "is the cache
    populated" silently drops that. It matters here rather than in theory,
    because modules mount their routers during the startup lifespan and
    ``enable_module`` mounts one at runtime - so the pinned document would be
    the one built before ~190 module routers existed, and a module enabled by
    an operator would never appear in the docs at all.
    """
    # Its own app: this one adds a route, and the module-scoped client is
    # shared with the tests above.
    app = create_app()
    before = app.openapi()
    assert before is app.openapi(), "the schema should be cached between calls"

    marker = "/probe-route-added-after-the-schema-was-cached"

    @app.get(marker, include_in_schema=True)
    async def _probe() -> dict[str, str]:  # pragma: no cover - never called
        return {}

    after = app.openapi()

    assert marker in after["paths"], "a route added after the first build never reached the schema"
    # The markers the override exists to add must survive the rebuild.
    assert after["info"]["x-ddc-author"].startswith("Artem Boiko")
    assert "DataDrivenConstruction" in after["info"]["x-ddc-origin"]
