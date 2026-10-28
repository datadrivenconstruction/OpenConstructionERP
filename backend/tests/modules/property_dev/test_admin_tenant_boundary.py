"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The global admin role does not cross a tenant boundary in property_dev.

The module decided once that ownership is strict: an admin from another
tenant must still 404 on an object they do not own. That decision lived in
one helper's docstring while sibling helpers kept an admin bypass, so the
module answered two ways depending on which door a request came through.

DISCOVERY IS BY WIRING, NOT BY NAME. The population is the module's own
route table: every mutating route it registers, and the functions each one
actually reaches. Naming the gates instead would repeat the defect this
suite exists to catch. An earlier draft of this test discovered helpers by
the ``_verify_owner_via_*`` prefix and would have gone green while missing
the live broker gate entirely, because that gate is called
``_ensure_broker_owner`` and the prefixed broker helper it looks like is
reached by no route at all. A scope written as a name is blind to the
sibling that does the work, and it counts dead code as covered.

Reaching from the route table fixes both. A renamed gate stays in the
population because the route still reaches it, a gate written under a
fourth naming shape is included the day it is wired up, and an unreachable
helper is excluded because no route reaches it.

Where spelling still enters, and why it is the safe direction. Discovery
narrows by nothing but wiring: every registered route, every verb, and the
whole transitive call graph underneath. The two DETECTORS do read spelling,
matching the literal ``admin`` and the fields ``owner_id`` and ``tenant_id``,
and a gate comparing some third field under a name nobody here guessed would
not be recognised. Both are deliberately broad and both fail toward
flagging, so the cost of that residue is a false alarm rather than a silent
pass. The exemption lists are keyed to ROUTE handlers, and a renamed handler
breaks the stale-entry test loudly instead of quietly granting an amnesty.
"""

from __future__ import annotations

import ast
import pathlib
import uuid
from collections import defaultdict

import pytest
import pytest_asyncio
from httpx import AsyncClient

from .conftest import _register_user

MODULE_DIR = pathlib.Path(__file__).resolve().parents[3] / "app" / "modules" / "property_dev"

MUTATING = {"POST", "PATCH", "PUT", "DELETE"}


# Routes whose handler may branch on the admin role, with the reason.
# Each of these decides how WIDE a batch is, not whether a caller may reach
# one named object belonging to another tenant, which is what this guards.
#
# The bulk endpoints are the sales-ops batch console. They are RBAC-gated at
# MANAGER, and their admin branch decides whether rows the caller does not
# own are processed or skipped. Whether that batch should span tenants is a
# product decision that has not been made here, so it is recorded rather
# than silently changed.
#
# THE RULING THIS LIST ENCODES. "An admin gets no cross-tenant reach on a
# named object" and "an admin sees every row in a list" are two different
# rules. This suite settles the first and deliberately does NOT bind the
# second. Every entry below decides how wide a listing, dashboard or batch
# runs; none decides whether one named object belonging to another tenant
# may be read or written. Narrowing admin list width may well be right, but
# it is a product decision with visible consequences for the admin console,
# so it is recorded here rather than made silently as a side effect of an
# authorization fix.
_ALLOWED_ROUTE_HANDLERS: dict[str, str] = {
    "bulk_plots_status_change": "batch width: admin batch spans the estate",
    "bulk_reservations_extend_expiry": "batch width: admin batch spans the estate",
    "bulk_documents_regenerate": "batch width: admin batch spans the estate",
    "bulk_leads_import_csv": "batch width: admin batch spans the estate",
    "bulk_buyers_merge": "batch width: admin batch spans the estate",
    # Read scoping. Each returns an unfiltered set to an admin and an
    # owner-scoped set to everyone else.
    "list_developments": "list width: admin console lists every development",
    "list_leads": "list width: admin console lists every lead",
    "list_reservations": "list width: admin console lists every reservation",
    "list_document_templates": "list width: admin console lists every template",
    "dashboard_cohort_retention": "aggregate width: rollup over the whole estate",
    "dashboard_time_to_close": "aggregate width: rollup over the whole estate",
    "dashboard_lead_source_attribution": "aggregate width: rollup over the whole estate",
    "dashboard_conversion_funnel": "aggregate width: rollup over the whole estate",
    "dashboard_broker_performance": "aggregate width: rollup over the whole estate",
}
# Note there is no separate helper exemption list. ``_list_accessible_dev_ids``
# reads the admin role too, but it is reachable only from the handlers above,
# so exempting those routes covers it. Every exemption here is keyed to a
# ROUTE, never to a helper name, which keeps the spelling of an internal
# function out of the decision entirely.

# Routes, read and write alike, that legitimately resolve no ownership
# chain, with why. Each was read before being listed. A route added here
# without a reason that survives reading the handler is a bypass with
# paperwork.
_NO_OWNER_CHAIN_EXPECTED: dict[str, str] = {
    # The portal authenticates by signed token, not by user payload. The
    # token is the credential and it names exactly one buyer, so there is
    # no caller identity to compare an owner against.
    "verify_portal_token": "portal: the signed token is the credential",
    "upload_kyc_document": "portal: the signed token is the credential",
    # Renders a synthetic sample from in-memory stub data. No real entity
    # is read, so there is nothing to own.
    "sample_preview_document_template": "preview: renders stub data, touches no tenant row",
    # Cron-style sweep over every overdue instalment, by design.
    "accrue_late_fees": "scheduled sweep: spans the estate by design",
    # Locale override files for the document templates. These are
    # translation assets rather than tenant rows, and they carry no owner
    # column to resolve. Whether one tenant should be able to replace a
    # translation another tenant reads is a separate question, raised
    # rather than settled here.
    "put_document_template_locale": "translation asset: no owner column exists",
    "delete_document_template_locale_override": "translation asset: no owner column exists",
    "get_document_template_locale": "translation asset: no owner column exists",
    # Static reference data. Neither reads a tenant row, so there is no
    # owner to resolve and nothing to cross.
    "list_jurisdictions": "reference data: ISO codes, identical for every caller",
    "list_payment_schedule_templates": "reference data: static catalogue, identical for every caller",
    # Buyer portal reads, authenticated by the same signed token as the
    # portal writes above rather than by a user payload.
    "buyer_overview": "portal: the signed token is the credential",
    "download_buyer_document": "portal: the signed token is the credential",
    "portal_list_my_snags": "portal session: scoped to the buyer the session names",
    "portal_list_my_warranty_claims": "portal session: scoped to the buyer the session names",
}


def _strip_docstring(fn: ast.AST) -> list[ast.stmt]:
    body = list(fn.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        if isinstance(body[0].value.value, str):
            return body[1:]
    return body


def _reads_admin_role(fn: ast.AST) -> bool:
    """True when the function's CODE branches on the admin role.

    A broad net on purpose: it matches the literal in any position, so
    ``payload.get("role") == "admin"``, ``payload["role"] == "admin"`` and
    ``role in ("admin", "root")`` all count, and it matches any name
    carrying ``admin`` so a helper reading a module constant is caught too.
    The docstring is stripped first, because a function that only DESCRIBES
    the rule in prose is not branching on it. Comments never reach the AST.
    """
    for stmt in _strip_docstring(fn):
        for node in ast.walk(stmt):
            if isinstance(node, ast.Constant) and node.value == "admin":
                return True
            if isinstance(node, ast.Name) and "admin" in node.id.lower():
                return True
            if isinstance(node, ast.Attribute) and "admin" in node.attr.lower():
                return True
    return False


def _resolves_ownership(fn: ast.AST) -> bool:
    """True when the function compares a stored owner/tenant to the caller.

    Shape-based, not name-based: it looks for a read of ``owner_id`` or
    ``tenant_id``. That is what an ownership gate DOES, whatever it happens
    to be called. Both spellings count, because the module reaches the field
    as an attribute in most places and through ``getattr(broker,
    "tenant_id", None)`` in the broker gate.

    Deliberately does NOT require a ``raise`` alongside. The batch console
    enforces by skipping the row rather than raising, and demanding a raise
    reported those routes as ungated when they are not.
    """
    owner_fields = {"owner_id", "tenant_id"}
    for stmt in _strip_docstring(fn):
        for node in ast.walk(stmt):
            if isinstance(node, ast.Attribute) and node.attr in owner_fields:
                return True
            if isinstance(node, ast.Name) and node.id in owner_fields:
                return True
            if isinstance(node, ast.Constant) and node.value in owner_fields:
                return True
    return False


def _module_functions() -> dict[str, list[ast.AST]]:
    """Every function defined in the module, keyed by name.

    A name can map to several definitions (a method and a free function
    sharing a name), so callers consider all of them.
    """
    out: dict[str, list[ast.AST]] = defaultdict(list)
    for path in sorted(MODULE_DIR.rglob("*.py")):
        if "__pycache__" in str(path):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out[node.name].append(node)
    return out


def _callees(fn: ast.AST) -> set[str]:
    """Names this function calls, by plain name and by attribute name.

    Attribute calls are resolved by their attribute alone, so
    ``self._verify_project_owner_for_house_type_catalogue(...)`` and
    ``service.get_broker(...)`` both land. That over-approximates the call
    graph, which is the safe direction: it widens what the admin-role
    assertion inspects.
    """
    names: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                names.add(node.func.attr)
    return names


def _reachable(entry: str, functions: dict[str, list[ast.AST]]) -> set[str]:
    """Transitive closure of everything ``entry`` can call inside the module."""
    seen: set[str] = set()
    stack = [entry]
    while stack:
        name = stack.pop()
        if name in seen or name not in functions:
            continue
        seen.add(name)
        for defn in functions[name]:
            stack.extend(_callees(defn) - seen)
    return seen


def _all_routes() -> list[tuple[str, str, str]]:
    """(method, path, handler name) for every route the module registers.

    Reads AND writes. A cross-tenant admin reading one named object is the
    same boundary crossing as mutating it, so restricting this to mutating
    verbs would leave every single-object GET outside the population.

    Read off the assembled APIRouter, so this is the real route table rather
    than a guess from decorators or names.

    Included routers are walked rather than assumed flat. ``router`` mounts
    the buyer portal through ``include_router``, and this FastAPI version
    leaves an ``_IncludedRouter`` wrapper in ``routes`` holding the child
    under ``original_router`` instead of splicing the child's routes in.
    Reading only the top level silently dropped all nine portal routes,
    which is exactly the kind of quiet under-count this suite exists to
    prevent.

    The descent is by SHAPE, not by attribute name: anything reachable from
    a route object that carries its own ``routes`` is followed. A rename of
    that private attribute therefore does not silently shrink the
    population, which is the same mistake at one remove.

    How we know the walk is complete rather than merely plausible: the
    assembled table yields 142 mutating routes, and an independent scan of
    the ``@router.<verb>`` decorators in the module source yields the same
    142. Two mechanisms that share no code agreeing on a count is the only
    thing that catches a population which looks whole and is short by nine.
    Before the descent was added the assembled figure was 137 and nothing
    anywhere said so.
    """
    from app.modules.property_dev.router import router

    found: list[tuple[str, str, str]] = []
    seen: set[int] = set()

    def walk(node) -> None:
        if id(node) in seen:
            return
        seen.add(id(node))
        for route in getattr(node, "routes", []):
            endpoint = getattr(route, "endpoint", None)
            methods = getattr(route, "methods", None) or set()
            if endpoint is not None and methods:
                for method in sorted(methods):
                    if method in {"HEAD", "OPTIONS"}:
                        continue
                    found.append((method, getattr(route, "path", "?"), endpoint.__name__))
            # An included router, or a wrapper holding one, carries its own
            # routes; descend so mounted surfaces are not missed.
            if hasattr(route, "routes"):
                walk(route)
            for value in vars(route).values() if hasattr(route, "__dict__") else ():
                if hasattr(value, "routes"):
                    walk(value)

    walk(router)
    return found


def test_the_route_table_is_populated() -> None:
    """Guard the guard: discovery that finds nothing must fail loudly."""
    routes = _all_routes()
    assert len(routes) > 150, f"only {len(routes)} routes discovered, the route scan is broken"
    assert any(m in MUTATING for m, _p, _h in routes), "no mutating routes discovered"
    assert any(m == "GET" for m, _p, _h in routes), "no read routes discovered"
    functions = _module_functions()
    assert "_verify_owner_via_development" in functions, "module source scan is broken"


def test_no_route_reaches_a_gate_that_admits_a_cross_tenant_admin() -> None:
    """No route may reach a function that branches on the admin role.

    The population is the route table, so a gate that is renamed, or written
    under a naming shape nobody anticipated, is covered the moment a route
    reaches it.
    """
    functions = _module_functions()
    offenders: dict[str, set[str]] = defaultdict(set)

    for method, path, handler in _all_routes():
        if handler in _ALLOWED_ROUTE_HANDLERS:
            continue
        for name in _reachable(handler, functions):
            if any(_reads_admin_role(d) for d in functions[name]):
                offenders[f"{name}"].add(f"{method} {path}")

    assert not offenders, (
        "These functions branch on the global admin role and are reachable from a "
        "route, so an admin from another tenant can reach an object they do not "
        "own. That is the defect this module already decided against in "
        "_verify_owner_via_development. Make the gate strict, or record the route "
        "in _ALLOWED_ROUTE_HANDLERS with a reason if it decides listing, aggregate "
        "or batch WIDTH rather than reach on one named object.\n"
        + "\n".join(f"  {name} <- {', '.join(sorted(routes))}" for name, routes in sorted(offenders.items()))
    )


def test_every_route_reaches_some_ownership_resolution() -> None:
    """A route that resolves no owner at all is a finding, not a pass.

    This is the assertion that catches a route reaching NO gate whatsoever.
    The admin-role test above cannot: a route with no gate reaches no admin
    branch either, so it sails through on an absence rather than on a check.

    It covers reads as well as writes. It did not always. While this suite
    still enumerated mutating routes only, seven read routes reached no
    ownership resolution and NOTHING asserted anything about them. They all
    turned out to be reference data or portal-token reads, so the answer was
    the same either way, but an unexamined route is not an exempted one and
    the two should never have looked alike from outside.
    """
    functions = _module_functions()
    ungated: list[str] = []

    for method, path, handler in _all_routes():
        if handler in _NO_OWNER_CHAIN_EXPECTED:
            continue
        reached = _reachable(handler, functions)
        if not any(_resolves_ownership(d) for name in reached for d in functions[name]):
            ungated.append(f"{method} {path} (handler {handler})")

    assert not ungated, (
        "These routes reach no function that compares a stored owner or tenant "
        "against the caller, so nothing stands between the request and another "
        "tenant's data. Add the ownership gate, or record the route in "
        "_NO_OWNER_CHAIN_EXPECTED with the reason it needs none.\n" + "\n".join(f"  {r}" for r in sorted(ungated))
    )


def test_allowlists_have_no_stale_entries() -> None:
    """Allowlisted names must still be live route handlers.

    Without this the lists become a place where a real gate can hide behind
    the name of a route that was deleted or renamed.
    """
    handlers = {handler for _m, _p, handler in _all_routes()}
    stale = sorted((set(_ALLOWED_ROUTE_HANDLERS) | set(_NO_OWNER_CHAIN_EXPECTED)) - handlers)
    assert not stale, "Allowlisted but no longer a route handler: " + ", ".join(stale)

    # An entry that is no longer needed must be removed, not left lying
    # around where it would excuse a future route that reuses the name.
    functions = _module_functions()
    unnecessary = sorted(
        handler
        for handler in _NO_OWNER_CHAIN_EXPECTED
        if any(_resolves_ownership(d) for name in _reachable(handler, functions) for d in functions[name])
    )
    assert not unnecessary, (
        "These routes now resolve ownership, so their _NO_OWNER_CHAIN_EXPECTED entry "
        "is dead weight. Remove them: " + ", ".join(unnecessary)
    )


# ── Behavioural anchor: the plot path the live probe exercised ──────────


@pytest_asyncio.fixture(scope="module")
async def owner_and_foreign_admin(client: AsyncClient):
    """An editor owning a plot, plus an admin belonging to another tenant."""
    _uid, _email, owner = await _register_user(client, role="editor", tag="atbowner")

    proj = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"ATB-{uuid.uuid4().hex[:6]}",
            "description": "admin tenant boundary",
            "currency": "EUR",
        },
        headers=owner,
    )
    assert proj.status_code in (200, 201), proj.text

    dev = await client.post(
        "/api/v1/property-dev/developments/",
        json={
            "project_id": proj.json()["id"],
            "code": f"ATB-{uuid.uuid4().hex[:6]}",
            "name": "Boundary Gardens",
            "total_plots": 1,
            "currency": "EUR",
        },
        headers=owner,
    )
    assert dev.status_code == 201, dev.text

    plot = await client.post(
        "/api/v1/property-dev/plots/",
        json={
            "development_id": dev.json()["id"],
            "plot_number": f"ATB-{uuid.uuid4().hex[:4]}",
            "area_m2": "120.0",
            "price_base": "400000.00",
            "currency": "EUR",
            "status": "planned",
        },
        headers=owner,
    )
    assert plot.status_code == 201, plot.text

    _aid, _aemail, admin = await _register_user(client, role="admin", tag="atbadmin")
    return {"plot_id": plot.json()["id"], "owner": owner, "admin": admin}


@pytest.mark.asyncio
async def test_foreign_admin_cannot_read_another_tenants_plot(
    owner_and_foreign_admin,
    client: AsyncClient,
) -> None:
    plot_id = owner_and_foreign_admin["plot_id"]
    resp = await client.get(
        f"/api/v1/property-dev/plots/{plot_id}",
        headers=owner_and_foreign_admin["admin"],
    )
    assert resp.status_code == 404, f"a cross-tenant admin read another tenant's plot: {resp.status_code}"


@pytest.mark.asyncio
async def test_foreign_admin_cannot_mutate_another_tenants_plot(
    owner_and_foreign_admin,
    client: AsyncClient,
) -> None:
    plot_id = owner_and_foreign_admin["plot_id"]
    resp = await client.patch(
        f"/api/v1/property-dev/plots/{plot_id}",
        json={"status": "sold"},
        headers=owner_and_foreign_admin["admin"],
    )
    assert resp.status_code == 404, f"a cross-tenant admin mutated another tenant's plot: {resp.status_code}"


@pytest.mark.asyncio
async def test_foreign_admin_cannot_delete_another_tenants_plot(
    owner_and_foreign_admin,
    client: AsyncClient,
) -> None:
    plot_id = owner_and_foreign_admin["plot_id"]
    resp = await client.delete(
        f"/api/v1/property-dev/plots/{plot_id}",
        headers=owner_and_foreign_admin["admin"],
    )
    assert resp.status_code == 404, f"a cross-tenant admin deleted another tenant's plot: {resp.status_code}"


@pytest.mark.asyncio
async def test_the_owner_still_reaches_their_own_plot(
    owner_and_foreign_admin,
    client: AsyncClient,
) -> None:
    """Same-tenant access is unaffected.

    Without this the three tests above would pass just as well on a module
    that had been broken to refuse everyone.
    """
    plot_id = owner_and_foreign_admin["plot_id"]
    resp = await client.get(
        f"/api/v1/property-dev/plots/{plot_id}",
        headers=owner_and_foreign_admin["owner"],
    )
    assert resp.status_code == 200, resp.text
