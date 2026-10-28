"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Every method the router calls on the service has to exist on the service.

``PropertyDevService`` is assembled twice over. Most methods are defined inside
the class; forty-one more are module-level ``_svc_*`` functions bolted on at
import time::

    PropertyDevService.get_broker = _svc_get_broker  # type: ignore[attr-defined]

That trailing ``type: ignore`` is the reason this module exists. It silences the
only checker that would otherwise notice a name which was never bolted on, and
it silences it at the definition site rather than at the call sites, so a route
calling a method nobody attached type-checks clean, imports clean, starts clean,
and raises ``AttributeError`` the first time a real request reaches that
endpoint. Nothing between the typo and the 500 except somebody exercising that
one route.

The check resolves bindings, not spellings
------------------------------------------
The obvious version of this - collect every ``svc.X(`` in the router and look
each ``X`` up on the class - was written first and reported five failures. All
five were false. ``cohort_retention``, ``time_to_close``,
``lead_source_attribution``, ``conversion_funnel`` and ``broker_performance``
are methods of ``AnalyticsService``, constructed locally inside the dashboard
routes under a variable that happens to also be called ``svc``. Two classes, one
variable name, and a check that could not tell them apart because it asked what
the receiver was *called* instead of what it was *bound to*.

So this walks each function, resolves every receiver it can - parameters by
their annotation, locals by their constructor - and attributes a call to
``PropertyDevService`` only when the binding says so. Receivers it can place on
some other type are counted separately and reported in the failure message
rather than dropped, because a classifier that silently discards what it cannot
categorise is reporting a denominator it does not have.

Static on purpose. Importing the module would answer the same question, but only
for the branches that import cleanly in the test environment, and it would make
a genuine missing attribute look like an import error.
"""

from __future__ import annotations

import ast
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parents[3] / "app" / "modules" / "property_dev"
SERVICE = MODULE_DIR / "service.py"
ROUTER = MODULE_DIR / "router.py"
TARGET = "PropertyDevService"


def _annotation_names(node: ast.AST | None) -> set[str]:
    """Every bare name inside an annotation, however the annotation is wrapped.

    Routes spell the dependency several ways - a plain annotation, an
    ``Annotated[...]`` carrying a ``Depends``, a string forward reference.
    Walking the annotation catches all of them without enumerating the wrappers,
    and it is the enumeration that would quietly go stale.
    """
    if node is None:
        return set()
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            node = ast.parse(node.value, mode="eval").body
        except SyntaxError:
            return set()
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _service_surface() -> set[str]:
    """Names an instance answers to: defined in the class, or bolted on after."""
    tree = ast.parse(SERVICE.read_text(encoding="utf-8"))

    defined: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == TARGET:
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    defined.add(sub.name)

    # Parsed rather than pattern-matched: several of these assignments wrap
    # their value across lines, and a line-oriented reader sees nothing there.
    attached: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == TARGET
                ):
                    attached.add(target.attr)

    assert defined, f"no methods found on {TARGET}; the class was renamed or moved"
    assert attached, (
        f"no names are bolted onto {TARGET} any more. If the _svc_* helpers were folded into the "
        "class this check still works, but delete this assertion so it stops claiming otherwise."
    )
    return defined | attached


def _router_calls_on_the_service() -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    """Calls attributed to the service, and calls placed on something else."""
    tree = ast.parse(ROUTER.read_text(encoding="utf-8"))
    on_service: list[tuple[str, int]] = []
    elsewhere: list[tuple[str, int]] = []

    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        params = [*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs]
        placed = {a.arg: "parameter" for a in params}
        bound: set[str] = {a.arg for a in params if TARGET in _annotation_names(a.annotation)}

        for node in ast.walk(fn):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                ctor = node.value.func
                name = ctor.id if isinstance(ctor, ast.Name) else getattr(ctor, "attr", "")
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        placed[target.id] = name
                        if name == TARGET:
                            bound.add(target.id)

        for node in ast.walk(fn):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            recv = node.func.value
            if not isinstance(recv, ast.Name):
                continue
            if recv.id in bound:
                on_service.append((node.func.attr, node.lineno))
            elif recv.id in placed:
                elsewhere.append((f"{recv.id} ({placed[recv.id]})", node.lineno))

    return on_service, elsewhere


def test_every_router_call_resolves_on_the_service() -> None:
    surface = _service_surface()
    on_service, elsewhere = _router_calls_on_the_service()

    # Anti-vacuity. If the router is refactored so no receiver resolves to the
    # service any more, every assertion below passes over an empty set and this
    # module goes green while checking nothing. The floor is far under the ~199
    # call sites present today so ordinary refactoring cannot trip it.
    assert len(on_service) > 50, (
        f"only {len(on_service)} router calls resolved to a {TARGET}, and {len(elsewhere)} resolved "
        "to something else. Either the routes stopped taking the service as a dependency or the "
        "binding resolution above no longer matches how they declare it - fix the resolver rather "
        "than lowering this floor, because an empty set passes every check that follows."
    )

    missing = sorted({name for name, _ in on_service if name not in surface})
    assert not missing, (
        f"the router calls {missing} on a {TARGET}, and the class carries no such attribute. "
        f"Population: {len(on_service)} calls resolved to the service out of "
        f"{len(on_service) + len(elsewhere)} placed receivers. "
        "Most of this surface is attached after the class body with a type: ignore, so nothing "
        "else in the build will notice - the route will simply raise AttributeError on its first "
        "real request. Either bolt the helper on or correct the call."
    )
