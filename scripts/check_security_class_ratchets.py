#!/usr/bin/env python3
"""Ratchets for the four bug classes behind the published security advisories.

Each advisory the project has published was one instance of a class that the
codebase can grow again in a single line, and none of them made a test fail
when it went in:

  * GHSA-cvgq, GHSA-vwvr, GHSA-pvpj: a route takes an object id (or a project
    id) and checks the caller's role but never ``verify_project_access``. Row
    level security is a deliberate no-op, so that call is the only boundary
    between projects. The siblings on the same object were guarded each time,
    which is how a reporter found them and how a review missed them.
  * GHSA-pc2c: a route with no authentication dependency at all. There is no
    global auth middleware, so a route without one is public.
  * GHSA-rq5j: a server-side HTTP request to a URL a user can set, with no
    pass through ``app.core.url_safety``.
  * GHSA-wfpw: a module-level dict mutated from a request path, so one user's
    settings became every user's.

A static reading cannot decide any of these with certainty, so this is a
ratchet rather than a proof. Each check produces a set of sites from the AST of
``backend/app`` and compares it with ``scripts/security_class_baseline.json``.
A site that is not in the baseline fails the run: it is new, and somebody has
to either add the guard or argue it into the baseline in the same commit. A
baseline entry that no longer matches a site also fails, so the baseline only
shrinks and cannot pre-approve a future site that happens to reuse a name.

What each check counts as handled:

  * ``project_access``: a route whose path names a parameter (``{x_id}``) or
    that takes a ``project_id`` argument, unless its body, or a function in the
    same module it calls (followed four levels deep), calls one of
    ``ACCESS_PRIMITIVES``, or the route is admin-only. Handing the caller's id
    to the service does not count: GHSA-pvpj's mutators passed ``user_id`` on
    for the audit trail and checked nothing, so a check that lives in a service
    is a baseline entry with a reason, not a pass.

    ``resolve_grant_authority`` is in the list because it *is* the boundary
    check for the routes that call it, not a service that was handed an id: it
    loads the project and raises before any row is touched, 404 unless the
    caller's organization owns the project, 409 when no organization does, and
    it has no platform-admin bypass - so it is stricter than
    ``verify_project_access``, which admits team members and admins. Baseline
    entries for those four routes were the alternative and were rejected: a
    baseline entry excuses the route forever, so deleting the authority call
    from one of them would pass this guard, whereas an unrecognized primitive
    keeps failing until somebody reads the body. Only
    ``app/modules/projects/router.py``'s four participant-grant routes call it.
  * ``authentication``: a route with an auth dependency in its signature, its
    decorator's ``dependencies=`` or its router's ``APIRouter(dependencies=)``.
  * ``outbound_url_safety``: a module that imports an HTTP client library and
    does not import ``app.core.url_safety``. A fixed host is a fine reason to
    be in the baseline; a user-settable one is not.
  * ``module_state``: a module-level dict, list, set, deque or OrderedDict that
    a function in the same module mutates.

Run ``--update`` to rewrite the baseline from the tree, then read the diff: an
entry that appears there is a decision, not a formality. Use ``--update`` only
when a new site is safe for a reason the AST cannot see (a fixed host, a check
inside a service, an admin-only router), and give that reason in the commit
message that adds the entry, one line per site. Fix the site instead whenever
you can. Run it with Python 3.12 or newer, the version the backend parses as;
an older interpreter cannot read some files and the run stops on them.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "backend" / "app"
BASELINE = ROOT / "scripts" / "security_class_baseline.json"

HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options", "api_route", "websocket"})

ACCESS_PRIMITIVES = frozenset(
    {
        "verify_project_access",
        "accessible_project_ids",
        "is_project_member",
        "tenant_scoped_owner_filter",
        "allowed_project_ids_for_similar",
        # ADR 006. The participant-grant routes' boundary: the caller's
        # organization has to own the project, and no admin bypass softens it.
        # See the ``project_access`` bullet in this module's docstring for why
        # this is a primitive rather than four baseline entries.
        "resolve_grant_authority",
    }
)

# Names that, as a parameter annotation or a Depends() target, mean the caller
# was authenticated before the handler ran.
AUTH_NAMES = frozenset(
    {
        "CurrentUserId",
        "CurrentUserPayload",
        "CurrentTenantId",
        "ApiKeyUser",
        "get_current_user_id",
        "get_current_user_payload",
        "verify_user_exists_and_active",
        "get_user_from_api_key",
        "RequirePermission",
        "RequirePermissionOrApiKey",
        "RequireRole",
        "get_current_tenant_id",
    }
)

HTTP_CLIENT_MODULES = ("httpx", "requests", "aiohttp", "urllib.request", "urllib3", "smtplib", "websockets")

MUTATING_METHODS = frozenset(
    {
        "append",
        "extend",
        "insert",
        "update",
        "setdefault",
        "pop",
        "popitem",
        "clear",
        "add",
        "discard",
        "remove",
        "appendleft",
        "move_to_end",
    }
)
CONTAINER_CALLS = frozenset({"dict", "list", "set", "defaultdict", "OrderedDict", "deque", "Counter"})


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


class UnreadableSourceError(Exception):
    """A file under the scanned tree that this interpreter cannot parse."""


def _python_files(app_dir: Path) -> list[tuple[Path, ast.Module]]:
    """Parse every module, failing on one that does not parse.

    A file skipped here would be a file every check is silently blind to, and
    the way that happens in practice is an older interpreter that cannot read
    newer syntax: Python 3.11 cannot parse four files in this tree, one of
    them ``ai/ai_client.py``, the file GHSA-wfpw was in.
    """
    out: list[tuple[Path, ast.Module]] = []
    unreadable: list[str] = []
    for path in sorted(app_dir.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            out.append((path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))))
        except SyntaxError as exc:
            unreadable.append(f"{path}: {exc.msg} (line {exc.lineno})")
    if unreadable:
        raise UnreadableSourceError(
            f"cannot parse {len(unreadable)} file(s) with Python {sys.version.split()[0]}; "
            "run this with the interpreter the backend requires:\n  " + "\n  ".join(unreadable)
        )
    return out


def _names_in(node: ast.AST) -> set[str]:
    """Every bare name and attribute name mentioned under ``node``."""
    out: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            out.add(sub.id)
        elif isinstance(sub, ast.Attribute):
            out.add(sub.attr)
        elif isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            # String annotations under ``from __future__ import annotations``.
            out.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", sub.value))
    return out


def _called_names(fn: ast.AST) -> set[str]:
    out: set[str] = set()
    for sub in ast.walk(fn):
        if isinstance(sub, ast.Call):
            f = sub.func
            if isinstance(f, ast.Name):
                out.add(f.id)
            elif isinstance(f, ast.Attribute):
                out.add(f.attr)
    return out


def _router_level_auth(tree: ast.Module) -> set[str]:
    """Router variables built with an auth dependency in ``dependencies=``."""
    authed: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign | ast.AnnAssign):
            continue
        value = node.value
        if not isinstance(value, ast.Call):
            continue
        callee = value.func.attr if isinstance(value.func, ast.Attribute) else getattr(value.func, "id", "")
        if callee != "APIRouter":
            continue
        for kw in value.keywords:
            if kw.arg == "dependencies" and _names_in(kw.value) & AUTH_NAMES:
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                authed.update(t.id for t in targets if isinstance(t, ast.Name))
    return authed


def _module_alias_names(tree: ast.Module) -> dict[str, set[str]]:
    """Module-level ``_READ = Depends(RequirePermission(...))`` style aliases."""
    aliases: dict[str, set[str]] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            aliases[node.targets[0].id] = _names_in(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            aliases[node.target.id] = _names_in(node.value) | _names_in(node.annotation)
    return aliases


def _expand(names: set[str], aliases: dict[str, set[str]]) -> set[str]:
    seen = set(names)
    frontier = list(names)
    while frontier:
        n = frontier.pop()
        for extra in aliases.get(n, ()):
            if extra not in seen:
                seen.add(extra)
                frontier.append(extra)
    return seen


def _routes(tree: ast.Module) -> Iterator[tuple[ast.AsyncFunctionDef | ast.FunctionDef, str, str, ast.Call]]:
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
            continue
        for dec in node.decorator_list:
            if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)):
                continue
            if dec.func.attr not in HTTP_METHODS:
                continue
            owner = dec.func.value
            owner_name = owner.id if isinstance(owner, ast.Name) else getattr(owner, "attr", "")
            if not re.search(r"router|app|api", owner_name, re.IGNORECASE):
                continue
            path = dec.args[0].value if dec.args and isinstance(dec.args[0], ast.Constant) else "<computed>"
            yield node, owner_name, f"{dec.func.attr.upper()} {path}", dec


def _function_index(tree: ast.Module) -> dict[str, ast.AST]:
    index: dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
            index.setdefault(node.name, node)
    return index


def _imported_functions(tree: ast.Module, module: str) -> dict[str, tuple[str, str]]:
    """Map a local name to the ``(module, name)`` an ``app.`` import binds it to."""
    out: dict[str, tuple[str, str]] = {}
    package = module.rsplit(".", 1)[0]
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        source = node.module or ""
        if node.level:
            base = package.rsplit(".", node.level - 1)[0] if node.level > 1 else package
            source = f"{base}.{source}" if source else base
        if not source.startswith("app"):
            continue
        for alias in node.names:
            out[alias.asname or alias.name] = (source, alias.name)
    return out


class _Resolver:
    """Follows calls to functions in the same module and to ones imported from ``app``.

    Helpers are resolved to their bodies, never trusted by name: a helper called
    ``_guard_project`` that checks nothing does not count.
    """

    def __init__(self, parsed: list[tuple[Path, ast.Module]], app_dir: Path) -> None:
        self.functions: dict[str, dict[str, ast.AST]] = {}
        self.imports: dict[str, dict[str, tuple[str, str]]] = {}
        for path, tree in parsed:
            parts = path.relative_to(app_dir.parent).with_suffix("").parts
            module = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
            self.functions[module] = _function_index(tree)
            self.imports[module] = _imported_functions(tree, module + (".__init__" if parts[-1] == "__init__" else ""))

    def _lookup(self, module: str, name: str) -> tuple[str, ast.AST] | None:
        if name in self.functions.get(module, {}):
            return module, self.functions[module][name]
        target = self.imports.get(module, {}).get(name)
        if target is not None:
            source, attr = target
            if attr in self.functions.get(source, {}):
                return source, self.functions[source][attr]
        return None

    def reaches_access_check(self, module: str, fn: ast.AST, depth: int = 5) -> bool:
        seen: set[tuple[str, str]] = set()
        frontier: list[tuple[str, ast.AST]] = [(module, fn)]
        for _ in range(depth + 1):
            nxt: list[tuple[str, ast.AST]] = []
            for mod, f in frontier:
                called = _called_names(f)
                if called & ACCESS_PRIMITIVES:
                    return True
                for name in called:
                    found = self._lookup(mod, name)
                    if found is not None and (found[0], name) not in seen:
                        seen.add((found[0], name))
                        nxt.append(found)
            frontier = nxt
        return False


def _is_admin_only(names: set[str], fn: ast.AST) -> bool:
    for sub in ast.walk(fn):
        if isinstance(sub, ast.Call) and getattr(sub.func, "id", getattr(sub.func, "attr", "")) == "RequireRole":
            if sub.args and isinstance(sub.args[0], ast.Constant) and sub.args[0].value == "admin":
                return True
    return "RequireAdmin" in names or "_require_admin" in names


def collect(app_dir: Path = APP, root: Path = ROOT) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {
        "project_access": set(),
        "authentication": set(),
        "outbound_url_safety": set(),
        "module_state": set(),
    }
    parsed = _python_files(app_dir)
    resolver = _Resolver(parsed, app_dir)
    for path, tree in parsed:
        rel = _rel(path, root)
        parts = path.relative_to(app_dir.parent).with_suffix("").parts
        module = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
        aliases = _module_alias_names(tree)
        authed_routers = _router_level_auth(tree)

        for fn, owner, label, dec in _routes(tree):
            key = f"{rel}::{label}"
            sig_names = set()
            for a in fn.args.args + fn.args.kwonlyargs:
                if a.annotation is not None:
                    sig_names |= _names_in(a.annotation)
            for d in fn.args.defaults + fn.args.kw_defaults:
                if d is not None:
                    sig_names |= _names_in(d)
            for kw in dec.keywords:
                if kw.arg == "dependencies":
                    sig_names |= _names_in(kw.value)
            sig_names = _expand(sig_names, aliases)
            authenticated = bool(sig_names & AUTH_NAMES) or owner in authed_routers
            if not authenticated:
                found["authentication"].add(key)
                continue

            params = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
            object_scoped = "{" in label or "project_id" in params
            if not object_scoped:
                continue
            if resolver.reaches_access_check(module, fn):
                continue
            if _is_admin_only(sig_names, dec) or _is_admin_only(sig_names, fn):
                continue
            found["project_access"].add(key)

        imports_client = False
        imports_safety = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                mods = [node.module or ""] + [f"{node.module}.{a.name}" for a in node.names]
            else:
                continue
            for m in mods:
                if any(m == c or m.startswith(c + ".") for c in HTTP_CLIENT_MODULES):
                    imports_client = True
                if m.startswith("app.core.url_safety"):
                    imports_safety = True
        if imports_client and not imports_safety:
            found["outbound_url_safety"].add(rel)

        containers: set[str] = set()
        for node in tree.body:
            targets: list[ast.expr] = []
            value: ast.expr | None = None
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, value = [node.target], node.value
            if value is None:
                continue
            is_container = isinstance(value, ast.Dict | ast.List | ast.Set) or (
                isinstance(value, ast.Call)
                and (getattr(value.func, "id", None) or getattr(value.func, "attr", None)) in CONTAINER_CALLS
            )
            if is_container:
                containers.update(t.id for t in targets if isinstance(t, ast.Name))
        if containers:
            for fn in ast.walk(tree):
                if not isinstance(fn, ast.AsyncFunctionDef | ast.FunctionDef):
                    continue
                for sub in ast.walk(fn):
                    name = None
                    if isinstance(sub, ast.Assign | ast.AugAssign | ast.Delete):
                        for t in sub.targets if isinstance(sub, ast.Assign | ast.Delete) else [sub.target]:
                            # X[k] = v and X[k][j] = v both rewrite the table X.
                            while isinstance(t, ast.Subscript):
                                t = t.value
                                if isinstance(t, ast.Name):
                                    name = t.id
                    elif (
                        isinstance(sub, ast.Call)
                        and isinstance(sub.func, ast.Attribute)
                        and sub.func.attr in MUTATING_METHODS
                    ):
                        base = sub.func.value
                        while isinstance(base, ast.Subscript):
                            base = base.value
                        if isinstance(base, ast.Name):
                            name = base.id
                    if name in containers:
                        found["module_state"].add(f"{rel}::{name}")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--update",
        action="store_true",
        help="rewrite the baseline from the tree; name the reason for every new entry in the commit message",
    )
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    args = parser.parse_args(argv)

    try:
        found = collect()
    except UnreadableSourceError as exc:
        print(exc)
        return 1
    if args.update:
        args.baseline.write_text(
            json.dumps({k: sorted(v) for k, v in sorted(found.items())}, indent=2) + "\n", encoding="utf-8"
        )
        print(f"wrote {args.baseline.name}: " + ", ".join(f"{k}={len(v)}" for k, v in sorted(found.items())))
        return 0

    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    failed = False
    for check, sites in sorted(found.items()):
        known = set(baseline.get(check, []))
        new = sorted(sites - known)
        stale = sorted(known - sites)
        print(f"{check}: {len(sites)} site(s), baseline {len(known)}, new {len(new)}, stale {len(stale)}")
        for site in new:
            print(f"  NEW   {site}")
        for site in stale:
            print(f"  STALE {site}  (fixed or moved: delete it from {args.baseline.name})")
        failed = failed or bool(new) or bool(stale)
    if failed:
        print(
            "\nA NEW site is one of the advisory classes appearing again. Add the guard it is missing "
            "(verify_project_access, an auth dependency, app.core.url_safety, per-request state), or, if it "
            f"is safe for a reason the AST cannot see, add it to {args.baseline.name} in the same commit and "
            "say why in the message. A STALE entry must be deleted so the baseline cannot excuse a future site."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
