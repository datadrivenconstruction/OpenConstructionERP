# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""No route is answered in its place by a route declared before it.

``GET /finance/{invoice_id}`` sat before the inbox router's ``GET /finance/inbox``
and took every inbox request (see ``tests/_route_shadowing.py``). Each route was
right on its own, so no module test could see it; only the order of the whole
table shows it. The first tests pin the detector on small routers, the last ones
run it over the finance router and over every module router mounted the way
``ModuleLoader._load_module`` mounts them (kebab prefix, then the underscore
mirror). The fully booted application, with the routes the lifespan adds, is
checked again by the fresh-install API smoke.

No database: routers are only imported and mounted on a bare ``FastAPI``.
"""

from __future__ import annotations

import importlib

from fastapi import APIRouter, FastAPI
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles

from app.core.module_loader import ModuleLoader, served_routes
from tests._route_shadowing import shadowed_routes


def _ok() -> dict:
    return {}


def _parent_then_sub(item_param: str) -> FastAPI:
    """The finance shape: a parametric route, then a sub-router with a static prefix."""
    parent = APIRouter()
    parent.add_api_route("/{" + item_param + "}", _ok, methods=["GET"])
    sub = APIRouter(prefix="/inbox")
    sub.add_api_route("", _ok, methods=["GET"])
    sub.add_api_route("/{capture_id}", _ok, methods=["GET"])
    parent.include_router(sub)
    app = FastAPI()
    app.include_router(parent, prefix="/api/v1/finance")
    return app


def test_a_bare_parameter_before_a_static_sub_route_is_reported() -> None:
    found = shadowed_routes(served_routes(_parent_then_sub("invoice_id")))
    assert [(s.hidden, s.by, s.methods) for s in found] == [
        ("/api/v1/finance/inbox", "/api/v1/finance/{invoice_id}", ("GET",))
    ]


def test_a_uuid_convertor_lets_the_static_route_through() -> None:
    assert shadowed_routes(served_routes(_parent_then_sub("invoice_id:uuid"))) == []


def test_a_different_method_does_not_shadow() -> None:
    router = APIRouter()
    router.add_api_route("/{item_id}", _ok, methods=["PATCH"])
    router.add_api_route("/summary", _ok, methods=["GET"])
    app = FastAPI()
    app.include_router(router, prefix="/x")
    assert shadowed_routes(served_routes(app)) == []


def test_the_static_route_first_is_fine() -> None:
    router = APIRouter()
    router.add_api_route("/summary", _ok, methods=["GET"])
    router.add_api_route("/{item_id}", _ok, methods=["GET"])
    app = FastAPI()
    app.include_router(router, prefix="/x")
    assert shadowed_routes(served_routes(app)) == []


def test_a_two_segment_parameter_route_shadows_a_nested_static_prefix() -> None:
    router = APIRouter()
    router.add_api_route("/{a}/{b}", _ok, methods=["GET"])
    router.add_api_route("/inbox/{capture_id}", _ok, methods=["GET"])
    app = FastAPI()
    app.include_router(router, prefix="/x")
    assert [s.hidden for s in shadowed_routes(served_routes(app))] == ["/x/inbox/{capture_id}"]


def test_a_mount_takes_everything_under_its_path(tmp_path) -> None:
    app = FastAPI()
    app.router.routes.append(Mount("/files", app=StaticFiles(directory=str(tmp_path))))
    router = APIRouter()
    router.add_api_route("/files/list", _ok, methods=["GET"])
    app.include_router(router)
    assert [s.hidden for s in shadowed_routes(served_routes(app))] == ["/files/list"]


def test_the_finance_router_shadows_nothing() -> None:
    from app.modules.finance.router import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/finance")
    assert shadowed_routes(served_routes(app)) == []


def test_no_module_route_is_shadowed_with_every_module_mounted() -> None:
    loader = ModuleLoader()
    loader.discover()
    app = FastAPI()
    mounted = 0
    for name in loader.resolve_order():
        dir_name = name.removeprefix("oe_")
        router = None
        for package in (f"app.modules.{dir_name}", f"app.modules.{name}"):
            try:
                router = getattr(importlib.import_module(f"{package}.router"), "router", None)
                break
            except ModuleNotFoundError as exc:
                if exc.name not in (package, f"{package}.router"):
                    raise
        if router is None:
            continue
        kebab = dir_name.replace("_", "-")
        app.include_router(router, prefix=f"/api/v1/{kebab}")
        if kebab != dir_name:
            app.include_router(router, prefix=f"/api/v1/{dir_name}", include_in_schema=False)
        mounted += 1
    # A walk that mounts nothing finds nothing shadowed; make the population visible.
    assert mounted > 150, f"only {mounted} module routers mounted"
    served = list(served_routes(app))
    assert len(served) > 4000, f"only {len(served)} routes served"
    found = shadowed_routes(served)
    assert found == [], "\n".join(f"{','.join(s.methods)} {s.hidden} <- {s.by}" for s in found)
