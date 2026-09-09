"""A visitor asking for /api/openapi.json must not stop every other request.

FastAPI registers the document route itself, in ``FastAPI.setup()``, as an
``async`` handler that calls ``app.openapi()`` inline. With ~190 module routers
mounted that build takes between 52 and 140 seconds on this stand, and while it
runs on the event loop the process answers nothing: measured on the 17.0.2
wheel, a ``GET /api/health`` issued during the build came back after 71.5s,
exactly when the build ended, against 0.05s at any other time. The health
endpoint is what the desktop shell polls to decide whether a backend is alive.

``serve_openapi_document_off_the_event_loop`` swaps that route for one that
builds and serialises on a worker thread. These tests use a tiny FastAPI app
with a build that blocks on an event, so the loop-blocking half of the story
can be shown failing as well as fixed, in milliseconds rather than minutes.
"""

from __future__ import annotations

import asyncio
import threading
import time

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.main import serve_openapi_document_off_the_event_loop

OPENAPI_URL = "/api/openapi.json"


def _tiny_app() -> FastAPI:
    app = FastAPI(openapi_url=OPENAPI_URL, docs_url=None, redoc_url=None)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "healthy"}

    @app.get("/api/ping")
    async def ping() -> dict[str, bool]:
        return {"ok": True}

    return app


def test_the_route_is_replaced_in_place_so_it_keeps_its_position() -> None:
    """Order matters: the frontend catch-all comes later and would swallow a re-added route."""
    app = _tiny_app()
    paths_before = [getattr(route, "path", None) for route in app.router.routes]
    index = paths_before.index(OPENAPI_URL)

    assert serve_openapi_document_off_the_event_loop(app) is True

    paths_after = [getattr(route, "path", None) for route in app.router.routes]
    assert paths_after == paths_before
    replaced = app.router.routes[index]
    assert replaced.endpoint.__name__ == "_openapi_document"
    assert replaced.include_in_schema is False


def test_an_app_without_a_document_url_is_left_alone() -> None:
    """Production sets ``openapi_url=None`` (BUG-394); there is nothing to swap there."""
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    assert serve_openapi_document_off_the_event_loop(app) is False


def test_the_document_is_byte_identical_to_the_one_fastapi_would_serve() -> None:
    app = _tiny_app()
    serve_openapi_document_off_the_event_loop(app)

    with TestClient(app) as client:
        response = client.get(OPENAPI_URL)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.content == JSONResponse(app.openapi()).body
    assert response.json()["paths"].keys() == {"/api/health", "/api/ping"}


def test_a_root_path_is_added_to_servers_exactly_as_fastapi_does() -> None:
    """The one bit of logic FastAPI's own handler has, kept so a prefixed deployment still works."""
    app = _tiny_app()
    serve_openapi_document_off_the_event_loop(app)

    with TestClient(app, root_path="/erp") as client:
        response = client.get(OPENAPI_URL)

    assert response.status_code == 200
    assert response.json()["servers"][0] == {"url": "/erp"}
    # The cached document itself is not mutated by the request that added a server.
    assert "servers" not in app.openapi() or {"url": "/erp"} not in app.openapi()["servers"]


def test_the_build_runs_on_a_worker_thread_not_on_the_loop_thread() -> None:
    app = _tiny_app()
    seen: dict[str, int] = {}

    @app.middleware("http")
    async def _record_loop_thread(request, call_next):  # type: ignore[no-untyped-def]
        seen["loop"] = threading.get_ident()
        return await call_next(request)

    original = app.openapi

    def _recording_openapi():  # type: ignore[no-untyped-def]
        seen["build"] = threading.get_ident()
        return original()

    app.openapi = _recording_openapi  # type: ignore[method-assign]
    serve_openapi_document_off_the_event_loop(app)

    with TestClient(app) as client:
        assert client.get(OPENAPI_URL).status_code == 200

    assert seen["build"] != seen["loop"]


@pytest.mark.parametrize("off_the_loop", [True, False], ids=["swapped-route", "fastapi-default-route"])
async def test_health_is_answered_while_the_document_is_being_built(off_the_loop: bool) -> None:
    """The user-visible half, shown in both directions.

    The build is made to block until a timer fires 1.5s later. With FastAPI's
    own route the health request cannot be answered before that, because the
    build holds the event loop; with the swapped route it is answered while
    the build is still running.
    """
    app = _tiny_app()
    gate = threading.Event()
    original = app.openapi

    def _slow_openapi():  # type: ignore[no-untyped-def]
        gate.wait(timeout=10)
        return original()

    app.openapi = _slow_openapi  # type: ignore[method-assign]
    if off_the_loop:
        assert serve_openapi_document_off_the_event_loop(app) is True

    release_after = 1.5
    threading.Timer(release_after, gate.set).start()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # The clock starts before the document request does. When the build
        # holds the loop, it is the sleep below that stretches to the timer,
        # not the health call after it, so timing the health call alone would
        # read the blocked case as fast.
        started = time.perf_counter()
        document = asyncio.ensure_future(client.get(OPENAPI_URL))
        # Let the document request reach its handler and start the build.
        await asyncio.sleep(0.2)
        health = await client.get("/api/health")
        health_answered_after = time.perf_counter() - started
        response = await document

    assert response.status_code == 200
    assert health.status_code == 200
    if off_the_loop:
        assert health_answered_after < release_after / 2, f"health waited {health_answered_after:.2f}s behind the build"
    else:
        assert health_answered_after >= release_after / 2, (
            f"the control case answered health after {health_answered_after:.2f}s; the default route no longer "
            "blocks the loop, so this test's premise needs re-measuring"
        )
