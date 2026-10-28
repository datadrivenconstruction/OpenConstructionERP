# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠``served_routes`` sees a module's routes, WebSockets included.

The case this exists for could not be expressed before. ``served_routes`` used
FastAPI's own ``iter_route_contexts``, which resolves HTTP paths correctly and
yields an EMPTY path for every ``APIWebSocketRoute``. A module whose only routes
are WebSockets therefore served nothing as far as
:meth:`ModuleLoader._has_live_routes` could tell, and that method decides
whether an enable has to mount the router again. Wrong on FastAPI 0.141, which
is what CI installs and what any fresh install resolves to under the
``fastapi>=0.116,<1`` pin, and right on the older releases the local
virtualenvs happen to carry - so nothing here was red.

Routers are mounted through ``include_router`` with a prefix, the way
``ModuleLoader._load_module`` mounts a real module, because that is the shape
whose behaviour changed. Declaring the same routes directly on the application
exercises a different code path and would pass either way.

No database and no application: a bare ``FastAPI`` is enough, and keeping it
bare is what lets this run in a lane that does not boot PostgreSQL.
"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI, WebSocket

from app.core.module_loader import module_loader, served_paths, served_routes


def _socket_only_module_app() -> FastAPI:
    """An app carrying one module that mounts nothing but a WebSocket."""
    router = APIRouter()

    @router.websocket("/presence/")
    async def presence(websocket: WebSocket) -> None:  # pragma: no cover - never driven
        await websocket.accept()

    app = FastAPI()
    # Both spellings, exactly as the loader mounts an underscore-named module.
    app.include_router(router, prefix="/api/v1/socket-only")
    app.include_router(router, prefix="/api/v1/socket_only", include_in_schema=False)
    return app


def test_a_websocket_only_module_reports_live_routes() -> None:
    """The regression: a socket-only module must not read as unmounted."""
    app = _socket_only_module_app()
    paths = set(served_paths(app))

    assert "/api/v1/socket-only/presence/" in paths, f"canonical socket path missing from {sorted(paths)}"
    assert "/api/v1/socket_only/presence/" in paths, f"legacy mirror socket path missing from {sorted(paths)}"
    assert "" not in paths, "a route came back with an empty path, which no prefix test can match"

    assert module_loader._has_live_routes("oe_socket_only", app), (
        "a module whose only routes are WebSockets reads as having no live routes, "
        "so every enable would mount it a second time"
    )


def test_nested_includes_keep_their_full_prefix() -> None:
    """A route two includes deep has to come back with both prefixes on it."""
    inner = APIRouter()

    @inner.get("/leaf")
    async def leaf() -> dict[str, str]:  # pragma: no cover - never called
        return {}

    outer = APIRouter()
    outer.include_router(inner, prefix="/inner")

    app = FastAPI()
    app.include_router(outer, prefix="/api/v1/outer")

    assert "/api/v1/outer/inner/leaf" in set(served_paths(app))


def test_http_and_socket_routes_both_come_back_with_their_route_object() -> None:
    """Callers need the route itself, not only the URL.

    The URL is known only to the include that mounted it, while the endpoint
    function, the methods and the dependencies live on the route object. A
    traversal that returned one without the other would satisfy the path
    assertions above and still be useless to the callers that read
    ``route.endpoint``.
    """
    from fastapi.routing import APIRoute, APIWebSocketRoute

    router = APIRouter()

    @router.get("/thing")
    async def thing() -> dict[str, str]:  # pragma: no cover - never called
        return {}

    @router.websocket("/sock")
    async def sock(websocket: WebSocket) -> None:  # pragma: no cover - never driven
        await websocket.accept()

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/mixed")

    found = {path: route for path, route in served_routes(app)}
    http_route = found["/api/v1/mixed/thing"]
    socket_route = found["/api/v1/mixed/sock"]

    assert isinstance(http_route, APIRoute)
    assert isinstance(socket_route, APIWebSocketRoute)
    assert http_route.endpoint.__name__ == "thing"
    assert socket_route.endpoint.__name__ == "sock"
