#!/usr/bin/env python3
"""Case-route guard: every step of every shipped case must land on a real screen.

A case is a guided walkthrough. Each step names the screen it happens on in its
``to`` field, and the reader clicks straight through to it. If that path has no
matching ``<Route>`` in ``App.tsx``, the click lands on the not-found page and
the walkthrough dead-ends, which is worse than not shipping the case at all.

This is not hypothetical. ``automate-a-recurring-check-with-a-pipeline`` had
three steps pointing at ``/pipelines`` and the route was never declared, even
though the sidebar linked to it and the feature behind it was complete: page,
canvas, store, templates and a typed client all present. The menu entry went
nowhere for as long as the module had existed. Nothing caught it, because
nothing compared the two lists. Measured 2026-08-05: with that route declared,
all 518 steps across the 144 shipped cases resolve, so this guard starts clean
and any failure it reports is new.

Two lists, one comparison:

  - The route table, from ``scripts/app_routes.py``. That module reads
    ``frontend/src/app/App.tsx`` and every bundled module manifest, and it
    resolves the paths a manifest computes from a table rather than skipping
    them. This file used to read both sources itself, with a regex that saw
    only quoted literals, and so did the gate that compares the router against
    the reverse proxy's allowlist; the two collectors disagreed, and the twenty
    routes ``regional-exchange`` builds from ``COUNTRY_TEMPLATES`` were
    invisible to both. There is one collector now. The catch-all ``*`` is
    deliberately excluded here: it matches everything, so counting it as a
    match would make this file always pass and mean nothing.
  - Every ``to`` in ``frontend/src/features/cases/data/*.playbook.ts``.

Matching is segment-wise rather than by string equality, because a route
segment written ``:boqId`` stands for any value and a step is allowed to name a
concrete one. Query strings are stripped first: React Router does not match on
them.

A step naming ``/projects/:projectId/...`` has to satisfy the check twice.
``resolveStepRoute`` (``frontend/src/features/cases/progress.ts``) fills the
slot when a sample project is picked and strips the whole
``/projects/:projectId`` prefix when one is not, so both the scoped and the
unscoped form are reachable at run time and both have to exist. Checking only
the scoped one would pass a case that dead-ends for every reader who has not
picked a project, which is the default.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app_routes import collect, print_unresolved, require_self_test  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_TSX = REPO_ROOT / "frontend" / "src" / "app" / "App.tsx"
MODULES_DIR = REPO_ROOT / "frontend" / "src" / "modules"
PLAYBOOK_DIR = REPO_ROOT / "frontend" / "src" / "features" / "cases" / "data"
PLAYBOOK_GLOB = "*.playbook.ts"

# `to` inside a playbook step. Single and double quotes both appear in the tree.
STEP_TO_RE = re.compile(r"""^\s*to:\s*(["'])([^"']*)\1""", re.MULTILINE)
PLAYBOOK_ID_RE = re.compile(r"""^\s*id:\s*(["'])([^"']*)\1""", re.MULTILINE)


def segments(path: str) -> list[str]:
    return [s for s in path.split("/") if s]


def matches(target: str, route: str) -> bool:
    """Whether a step target is served by one route declaration.

    A route segment beginning with ``:`` is a parameter and stands for any
    single segment, including one that is itself written ``:projectId``.
    """
    t_parts, r_parts = segments(target), segments(route)
    if len(t_parts) != len(r_parts):
        return False
    return all(r.startswith(":") or r == t for t, r in zip(t_parts, r_parts, strict=False))


def resolve_unscoped(target: str) -> str | None:
    """The form a step resolves to when no sample project is picked.

    Mirrors ``resolveStepRoute``. Returns None when the step has no
    ``:projectId`` slot and therefore only has the one form.
    """
    if ":projectId" not in target:
        return None
    stripped = re.sub(r"^/projects/:projectId", "", target)
    if stripped == "":
        return "/"
    return stripped if stripped.startswith("/") else f"/{stripped}"


def read_steps(directory: Path) -> list[tuple[str, str]]:
    """Every (playbook file stem, step target) pair, query strings stripped."""
    pairs: list[tuple[str, str]] = []
    for path in sorted(directory.glob(PLAYBOOK_GLOB)):
        source = path.read_text(encoding="utf-8", errors="replace")
        first_id = PLAYBOOK_ID_RE.search(source)
        case_id = first_id.group(2) if first_id else path.stem
        for _, target in STEP_TO_RE.findall(source):
            pairs.append((case_id, target.split("?", 1)[0]))
    return pairs


def main() -> int:
    if not APP_TSX.is_file():
        print(f"ERROR: {APP_TSX} not found", file=sys.stderr)
        return 1
    if not PLAYBOOK_DIR.is_dir():
        print(f"ERROR: {PLAYBOOK_DIR} not found", file=sys.stderr)
        return 1

    # The collector proves it can still read a route table, and still refuse one,
    # before this guard builds a verdict on what it returns. A collector that has
    # quietly stopped matching returns a short list, and a short list is what makes
    # a dead case step look alive.
    require_self_test()

    table = collect(app_tsx=APP_TSX, modules_dir=MODULES_DIR)

    # A route declaration the collector found and could not read is not a
    # reason to carry on with a shorter list. The shorter list is what makes a
    # dead case step look alive, and it is what made twenty shipped screens
    # look like screens nobody had.
    if table.unresolved:
        print_unresolved(table)
        return 1

    # Routes owned by a module that ships switched off are excluded here on
    # purpose, and only here. Their routes are not mounted until the reader
    # turns the module on, so a step pointing at one really does dead-end on a
    # default install. The proxy allowlist gate wants the opposite set, because
    # enablement is client side and a visitor who switches a module on still
    # has to get through Caddy to reach it.
    app_routes = [r.path for r in table.app_routes if r.path != "*"]
    module_routes = [r.path for r in table.module_routes if r.default_enabled is not False]
    routes = app_routes + module_routes
    steps = read_steps(PLAYBOOK_DIR)

    # An empty read is a broken scan, not a clean tree. Both of these have moved
    # before, and a guard that silently measures nothing is worse than none.
    if not app_routes:
        print(f"ERROR: no route declarations found in {APP_TSX}", file=sys.stderr)
        return 1
    if not module_routes:
        print(
            f"ERROR: no module routes found under {MODULES_DIR}; modules mount "
            "their own routes, so an empty read here would call every module "
            "screen dead",
            file=sys.stderr,
        )
        return 1
    if not steps:
        print(
            f"ERROR: no case steps found under {PLAYBOOK_DIR}/{PLAYBOOK_GLOB}",
            file=sys.stderr,
        )
        return 1

    dead: list[tuple[str, str, str]] = []
    for case_id, target in steps:
        if not any(matches(target, route) for route in routes):
            dead.append((case_id, target, "no route declares this path"))
            continue
        unscoped = resolve_unscoped(target)
        if unscoped is not None and not any(matches(unscoped, r) for r in routes):
            dead.append(
                (
                    case_id,
                    target,
                    f"resolves to {unscoped} with no project picked, and that has no route",
                )
            )

    if dead:
        # stdout is block buffered into a pipe and stderr is not, so without
        # this the verdict below overtakes what the collector printed above it.
        sys.stdout.flush()
        print(
            f"Case steps pointing at screens that do not exist: {len(dead)}",
            file=sys.stderr,
        )
        for case_id, target, why in sorted(set(dead)):
            print(f"  {case_id}: {target} - {why}", file=sys.stderr)
        print(
            "\nA case step is a link the reader clicks. Either declare the route "
            "in frontend/src/app/App.tsx or in the module manifest that owns the "
            "screen, or point the step at a screen that exists. Do not add the "
            "case to a list of exceptions: a walkthrough that dead-ends is not a "
            "walkthrough.",
            file=sys.stderr,
        )
        return 1

    cases = len({case_id for case_id, _ in steps})
    resolved_from_table = sum(
        1 for r in table.module_routes if r.origin == "resolved" and r.default_enabled is not False
    )
    print(
        f"case routes OK: {len(steps)} steps across {cases} cases, "
        f"all resolve against {len(routes)} declared routes "
        f"({len(app_routes)} in App.tsx, {len(module_routes)} from module manifests, "
        f"{resolved_from_table} of those resolved from a table)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
