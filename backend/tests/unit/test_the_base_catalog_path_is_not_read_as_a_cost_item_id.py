"""The cost-base catalogue path must reach its own handler, not the item-by-id route.

``GET /api/v1/costs/base-catalog`` used to answer ``400 {"error": "Invalid request"}``.
Nothing about the request was bad. Starlette matches routes in registration order, and
the costs router registered an unconstrained ``GET /{item_id}`` catch-all roughly 1300
lines above the literal ``/base-catalog`` route, so the literal path was captured as an
item id, the UUID parse failed, and the path-parameter sanitiser in ``app.main``
collapsed the resulting ``RequestValidationError`` into an opaque 400.

These tests assert route *identity* rather than a status code on purpose. Asserting
``status_code != 400`` would also pass on a 401, a 404 or a 500, so it would go green for
reasons unrelated to the defect. Resolving a path and naming the endpoint it lands on can
only pass when the routing itself is right.

Resolution is done against the costs router's own ``routes`` list rather than against a
built application. That list is a plain list appended in decorator order, which is
exactly the ordering the defect lives in, and it keeps the test off the private
``_IncludedRouter`` internals that current FastAPI uses to mount routers lazily (see the
long note in ``tests/integration/test_demo_read_only.py``). The mount prefix
(``/api/v1/costs``, applied by ``app.core.module_loader``) is irrelevant to the property:
shadowing is decided inside the router, before any prefix is applied.
"""

from starlette.routing import compile_path

from app.modules.costs.router import router as costs_router


def _resolve(path: str, method: str = "GET", routes: list | None = None):
    """First route whose path matches, mirroring Starlette's in-order matching.

    Starlette walks the route table in order and stops at the first full match, which is
    precisely the behaviour that let an early catch-all swallow a later literal route.
    """
    for route in costs_router.routes if routes is None else routes:
        if method not in (getattr(route, "methods", None) or set()):
            continue
        path_regex, _path_format, _convertors = compile_path(route.path)
        if path_regex.match(path):
            return route
    return None


def test_the_base_catalog_path_resolves_to_the_base_catalog_handler() -> None:
    """The documented, in-schema path must land on ``get_base_catalog``."""
    route = _resolve("/base-catalog")

    assert route is not None, "/base-catalog matched no route at all"
    assert route.endpoint.__name__ == "get_base_catalog", (
        f"/base-catalog resolved to {route.endpoint.__name__!r} via the registered path "
        f"{route.path!r}. A literal route is being swallowed by an earlier parameterized "
        f"one, so the caller gets a path-parameter parse failure instead of the catalogue."
    )


def test_both_slash_forms_of_the_base_catalog_path_reach_the_same_handler() -> None:
    """The app runs with ``redirect_slashes=False``, so both forms are registered.

    The slash-less form is the one published in the OpenAPI schema; the slash form is the
    one the frontend calls. They must not disagree about which handler they reach.
    """
    without_slash = _resolve("/base-catalog")
    with_slash = _resolve("/base-catalog/")

    assert without_slash is not None, "/base-catalog matched no route"
    assert with_slash is not None, "/base-catalog/ matched no route"
    assert without_slash.endpoint.__name__ == with_slash.endpoint.__name__ == "get_base_catalog", (
        f"the two slash forms disagree: {without_slash.endpoint.__name__!r} without the "
        f"trailing slash, {with_slash.endpoint.__name__!r} with it"
    )


def test_a_cost_item_id_route_still_matches_a_real_uuid() -> None:
    """Constraining the convertor must not cost us the route it constrains."""
    route = _resolve("/3f2504e0-4f89-11d3-9a0c-0305e82c3301")

    assert route is not None, "a real UUID no longer resolves to any cost-item route"
    assert route.endpoint.__name__ == "get_cost_item", (
        f"a real UUID resolved to {route.endpoint.__name__!r}, expected get_cost_item"
    )


def test_no_literal_route_in_the_costs_router_is_swallowed_by_an_earlier_parameterized_one() -> None:
    """Guard the whole class, not just the one route that was reported.

    ``/base-catalog`` was appended below the ``/{item_id}`` catch-all and broke silently.
    The next literal route appended at the bottom of this 6000-line router would break the
    same way, so assert the property over every literal path the router registers.
    """
    routes = list(costs_router.routes)
    literal_routes = [(i, r) for i, r in enumerate(routes) if "{" not in getattr(r, "path", "{")]
    assert literal_routes, "found no literal routes to check, this probe is measuring nothing"

    violations = []
    for index, route in literal_routes:
        for method in sorted(route.methods or set()):
            earlier = _resolve(route.path, method, routes=routes[:index])
            if earlier is not None:
                violations.append(
                    f"{method} {route.path} is swallowed by the earlier route "
                    f"{earlier.path!r} ({earlier.endpoint.__name__})"
                )

    # Report the population alongside the verdict: a probe that narrowed itself down to
    # nothing would otherwise pass silently.
    detail = "\n".join(violations)
    assert not violations, (
        f"{len(violations)} of {len(literal_routes)} literal routes in the costs router are "
        f"unreachable because an earlier parameterized route matches them first:\n{detail}"
    )
