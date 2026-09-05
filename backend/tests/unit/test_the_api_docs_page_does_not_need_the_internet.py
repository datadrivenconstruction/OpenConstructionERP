# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Both API reference pages have to render with no way out to the internet.

FastAPI's stock routes write pages that fetch their application code from
``cdn.jsdelivr.net``: ``swagger-ui-bundle.js`` and ``swagger-ui.css`` for
``/api/docs``, ``redoc.standalone.js`` for ``/api/redoc``. Both also take a
favicon from ``fastapi.tiangolo.com``, and ReDoc additionally asks
``fonts.googleapis.com`` for Montserrat and Roboto. On a machine with outbound
access that is invisible. On an air-gapped site, or a VPS behind an egress
firewall, the shell arrives, the browser cannot fetch the files that turn it
into a reference, and the operator gets a blank page with no error to search
for. Self-hosting is the premise of this platform rather than an edge case, so
the assets ship in the wheel and the pages point at this install.

The test that matters here is not "the HTML changed". It is that the URLs the
pages name are actually served, which is why every referenced asset is
requested and its bytes checked. Asserting only on the absence of the CDN
string would stay green if the vendored files were dropped from the package,
and that failure mode - a page referring to local files that are not there -
looks exactly like the bug this replaced.

``/api/docs`` is also the one thing on the API surface a first-time operator is
told to open: the boot banner prints it under "Open in your browser". A blank
page there is the first impression.

What this does not prove, said here rather than left for somebody to find in a
network log: ReDoc's own bundle renders an ``<img>`` for the Redocly mark at
``cdn.redoc.ly``. It is hidden by the component's ``onError`` handler, so the
page is complete without it, but it is one request that leaves the machine and
no assertion over the served HTML can see it. Suppressing it would mean
writing the page by hand instead of calling ``get_redoc_html``, or editing a
vendored bundle. Nothing else in either page reaches off the host, including
fonts - the bundles carry their own styles.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

#: Anything that would make the browser leave this host. ``//`` catches
#: protocol-relative URLs, which are easy to miss and just as fatal offline.
#: ``spec-url`` is in here because it is the attribute ReDoc loads the whole
#: document from, and it is on a custom element rather than on a ``script``.
_EXTERNAL = re.compile(r"""(?:src|href|spec-url)\s*=\s*["'](?:https?:)?//""", re.IGNORECASE)


@pytest.fixture(scope="module")
def client() -> TestClient:
    """The app without its lifespan, which is all this page needs.

    Entering ``TestClient`` as a context manager would run the startup
    handler: module loading, migrations, a database. The docs route and its
    assets are registered in ``create_app`` and depend on none of it.
    """
    return TestClient(create_app())


@pytest.mark.parametrize("path", ["/api/docs", "/api/redoc"])
def test_a_reference_page_names_no_host_but_this_one(client: TestClient, path: str) -> None:
    """No URL in either page leaves this machine, so no request can either.

    This is the offline claim in the only form the server can make it: a page
    that names nothing off-host needs nothing off-host to arrive. What the
    browser does with the bytes afterwards is the asset test below, and the one
    request neither test can see is in this module's docstring.
    """
    response = client.get(path)

    assert response.status_code == 200
    offenders = _EXTERNAL.findall(response.text)
    assert not offenders, f"{path} still loads from another host: {offenders}"
    # The specific origins this replaced, named so a failure says which one
    # came back rather than only that some URL is absolute.
    assert "cdn.jsdelivr.net" not in response.text
    assert "fastapi.tiangolo.com" not in response.text
    assert "fonts.googleapis.com" not in response.text
    assert "fonts.gstatic.com" not in response.text


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
    ("path", "filename", "content_type", "signature"),
    [
        ("/api/docs", "swagger-ui-bundle.js", "application/javascript", b"SwaggerUIBundle"),
        ("/api/docs", "swagger-ui.css", "text/css", b".swagger-ui"),
        ("/api/redoc", "redoc.standalone.js", "application/javascript", b"Redoc"),
    ],
)
def test_every_asset_a_page_names_is_served(
    client: TestClient,
    path: str,
    filename: str,
    content_type: str,
    signature: bytes,
) -> None:
    """Fetch what the page asks for, and check it is the real library.

    The signature check is the point: a 200 carrying an HTML error page, or the
    SPA's ``index.html`` handed back by the catch-all, would satisfy a status
    assertion and leave the page just as blank as the CDN did. It is also what
    catches a half-finished download, which is the likely way a vendored file
    goes wrong.
    """
    page = client.get(path)
    assert f"/api/docs/assets/{filename}" in page.text, f"{path} no longer loads {filename}"

    response = client.get(f"/api/docs/assets/{filename}")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(content_type)
    assert signature in response.content


def test_the_asset_route_serves_nothing_but_the_files_in_its_table(client: TestClient) -> None:
    """The route matches names against a table instead of mounting a directory.

    A ``StaticFiles`` mount would have put path traversal between the network
    and the installed package for the sake of three files. This asserts the
    refusal in both shapes: a plain unknown name, and a traversal attempt. The
    third shape is a name that is real but not ours - the table also decides
    which directory a file is read from, so a caller cannot pick one.
    """
    assert client.get("/api/docs/assets/swagger-ui-bundle.js.map").status_code == 404
    assert client.get("/api/docs/assets/..%2F..%2Fmain.py").status_code == 404
    assert client.get("/api/docs/assets/README.md").status_code == 404


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
    assert {"/api/docs", "/api/redoc", "/api/docs/assets/{filename}"} <= reference

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
