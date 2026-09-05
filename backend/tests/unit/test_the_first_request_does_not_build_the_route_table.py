"""The route table is built during boot, not inside the first request.

FastAPI does not build a route's dependant tree, its response field or its
operation id when the route is registered. It builds them the first time a
request reaches route matching, for every route the router holds, at once and
on the event loop. With ~190 module routers mounted that measured 32.1s on this
stand against 0.04s for the second request, and the cost fell on whichever
request happened to arrive first: ``GET /`` is a static ``index.html`` that
touches no database and no dependency, and it paid the full 32s exactly as
``/api/health`` did when it was the one to arrive first. Everything else queued
behind it - a health check issued alongside that first request answered 33.9s
later, five times the desktop launcher's own 12s probe deadline, so the
launcher read a live backend as unreachable while the splash screen sat there.

``warm_route_table`` moves that work to the end of the startup lifespan, which
is the one place where nobody is holding a socket open: uvicorn binds the
listening port only after the lifespan returns. The cost is unchanged; who
waits for it is not.

What these tests pin, in order:

* after the warm-up, a request to the route furthest down the table builds no
  route state at all;
* the warm-up builds at least what an unwarmed first request would have - so
  the assertion above is measuring the warm-up and not measuring nothing;
* replaying a plausible request would NOT have done the job, because matching
  stops at the first route that matches and leaves every later router cold;
* the warm-up's path reaches no endpoint, because a warm-up that matched a real
  route would be calling application code on every boot;
* a warm-up that raises does not take the boot with it.

The instrument is a counting wrapper around ``fastapi.routing.get_dependant``,
which is what ``_populate_api_route_state`` calls once per route to build the
dependant tree, and is the expensive half of what the first request used to
pay. It is private FastAPI API and named here deliberately: if a future release
renames it these tests fail loudly, which is the correct outcome for a guard
whose whole subject is FastAPI's lazy initialisation.

One thing found while writing this, and worth carrying rather than leaving in a
commit message: whether route state is deferred at all depends on the installed
FastAPI, and both behaviours sit inside the range this project pins,
``fastapi>=0.116.0,<1``. 0.136.3 builds it when the route is registered and no
first request pays anything; 0.141.1, which is what the running server here has,
defers it and is where the 32s came from. So a suite run against the older
release cannot observe the defect at all. That is why the red half below
measures the installed behaviour instead of trusting a version number, and skips
with a message naming the version rather than passing quietly.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import fastapi
import fastapi.routing
import httpx
import pytest
from fastapi import APIRouter, Depends, FastAPI

from app.main import ROUTE_TABLE_WARMUP_PATH, warm_route_table

#: The route furthest down the table built by :func:`_an_app_with_mounted_routers`.
#: Asked for by name because "last" is the load-bearing part: matching stops at
#: the first route that matches, so a request to an early route leaves
#: everything after it unbuilt, and a test that probed an early route would pass
#: on a warm-up that had reached almost nothing.
_THE_LAST_ROUTE = "/api/v1/beta/thing/5"


def _a_dependency() -> str:
    """A parameter that only exists to give the route a dependant tree to build."""
    return "value"


def _an_app_with_mounted_routers(routes: int = 6) -> FastAPI:
    """An application shaped like the real one: routers included, not bare routes.

    The inclusion matters. A router added with ``include_router`` becomes a
    nested branch that the matcher descends into and builds separately, which is
    how all ~190 module routers are mounted, so an app built from bare
    ``@app.get`` routes would not exercise the path this is about.
    """
    app = FastAPI()

    for group in ("alpha", "beta"):
        router = APIRouter()
        for index in range(routes):

            @router.get(f"/thing/{index}")
            async def _endpoint(value: str = Depends(_a_dependency)) -> dict[str, str]:
                return {"value": value}

        app.include_router(router, prefix=f"/api/v1/{group}")

    return app


async def _send(app: FastAPI, path: str) -> httpx.Response:
    """Put one ordinary request through the whole application.

    Through the whole application, not through ``app.router``, even though the
    warm-up goes to the router: a test that reached for the same shortcut the
    production code takes would be describing the shortcut rather than what a
    visitor does. A real request arrives through the middleware stack, and the
    stack is what supplies the exit stack a matched endpoint needs.
    """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(path)


class _CountRouteStateBuilds:
    """Counts the route dependant trees FastAPI builds inside the ``with`` block."""

    def __init__(self) -> None:
        self.count = 0
        self._patch: Any = None

    def __enter__(self) -> _CountRouteStateBuilds:
        real = fastapi.routing.get_dependant

        def counting(*args: Any, **kwargs: Any) -> Any:
            self.count += 1
            return real(*args, **kwargs)

        self._patch = patch.object(fastapi.routing, "get_dependant", counting)
        self._patch.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._patch.stop()


async def _builds_during_an_unwarmed_first_request() -> int:
    """How much route state this FastAPI leaves for the first request to build.

    Zero on a release that builds it when the route is registered, positive on
    one that defers it. Both exist inside the version range this project pins
    (``fastapi>=0.116.0,<1``) and the difference is not cosmetic: it is the
    whole subject of this file. Measured rather than compared against a version
    string, because the question is what the installed release does.
    """
    app = _an_app_with_mounted_routers()
    with _CountRouteStateBuilds() as builds:
        await _send(app, "/api/v1/alpha/thing/0")
    return builds.count


@pytest.mark.asyncio
async def test_a_request_after_the_warm_up_builds_no_route_state() -> None:
    """The property the fix exists for: the first visitor pays nothing.

    This does not measure latency. A timing assertion on a shared build machine
    is a flake, and the count is the more direct claim anyway - what was wrong
    was not that the first request was slow but that it was building every route
    in the process while everything else queued behind it.

    It holds on both halves of the version range, for two different reasons, and
    that is deliberate: on a release that builds route state at registration
    there is nothing left to do, and on one that defers it the warm-up has
    already done it. A test that only held on the second would go quiet on the
    first without anybody noticing which one they were running.
    """
    app = _an_app_with_mounted_routers()

    await warm_route_table(app)

    with _CountRouteStateBuilds() as builds:
        await _send(app, _THE_LAST_ROUTE)

    assert builds.count == 0


@pytest.mark.asyncio
async def test_the_warm_up_absorbs_what_the_first_request_would_have_built() -> None:
    """The red half, so the test above cannot pass by measuring nothing.

    Skipped, loudly, on a FastAPI that populates route state at registration:
    there the first request never paid and the warm-up has nothing to absorb, so
    an assertion that it does would be asserting a defect. The skip message is
    the point of the skip - a suite running against that release cannot catch a
    regression in this behaviour at all, and the version that ships is not
    necessarily the version the suite is run against.
    """
    deferred = await _builds_during_an_unwarmed_first_request()
    if deferred == 0:
        pytest.skip(
            f"fastapi {fastapi.__version__} builds route state when a route is registered, "
            "so no first request pays for it and there is nothing here to absorb"
        )

    app = _an_app_with_mounted_routers()

    with _CountRouteStateBuilds() as builds:
        await warm_route_table(app)

    assert builds.count >= deferred, (
        "the warm-up must build at least what the first request would have built, "
        f"got {builds.count} against {deferred}"
    )


@pytest.mark.asyncio
async def test_one_real_request_would_not_have_warmed_the_rest_of_the_table() -> None:
    """Why the warm-up asks for a path that matches nothing.

    Matching stops at the first route that matches, so a request to an early
    route builds the routers walked up to it and leaves every later one cold -
    measured here as 6 of 12. Warming by replaying a plausible request would
    therefore have left most of ~190 module routers to be built by whoever
    happened to open a page further down the menu, which is the same defect
    moved somewhere harder to see. A path that matches nothing is the only one
    that forces the router to consider all of them.
    """
    deferred = await _builds_during_an_unwarmed_first_request()
    if deferred == 0:
        pytest.skip(
            f"fastapi {fastapi.__version__} builds route state when a route is registered, "
            "so there is no order in which it gets built"
        )

    app = _an_app_with_mounted_routers()
    await _send(app, "/api/v1/alpha/thing/0")

    with _CountRouteStateBuilds() as builds:
        await _send(app, _THE_LAST_ROUTE)

    assert builds.count > 0, "a request to an early route was expected to leave the later routers unbuilt"


@pytest.mark.asyncio
async def test_the_warm_up_reaches_no_endpoint() -> None:
    """Its path must match nothing, in both senses.

    Matching nothing is what forces the router to consider every candidate, so
    the warm-up only works if the path is unroutable. And a path that did match
    would call application code on every boot, with a fabricated request, before
    the port is even open.
    """
    app = _an_app_with_mounted_routers()

    response = await _send(app, ROUTE_TABLE_WARMUP_PATH)

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_a_warm_up_that_fails_does_not_stop_the_boot() -> None:
    """A warm-up is an optimisation and must never be a reason not to start.

    When it fails the cost simply goes back where it was, onto the first request
    to arrive, which is the behaviour that shipped before it existed.
    """
    app = _an_app_with_mounted_routers()

    async def exploding(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("router refused")

    app.router = exploding  # type: ignore[assignment]

    elapsed = await warm_route_table(app)

    assert elapsed >= 0.0
