#!/usr/bin/env python3
"""Refuse a frontend API call that no backend route answers.

The frontend names about two thousand API paths as string literals, and the
backend serves about three thousand routes that are mounted at run time by the
module loader. Nothing compared the two. A path that drifted on either side,
a renamed segment, a trailing slash added on one side only, a helper that does
not prepend ``/api``, surfaced as a 404 in a user's browser and nowhere else.
The application is built with ``redirect_slashes=False``, so a slash is not a
detail here: ``/v1/rfi/stats`` and ``/v1/rfi/stats/`` are different URLs and
only one of them is served.

How the two sides are read:

* The backend table is the real one. The script builds the FastAPI app with
  ``create_app()``, mounts every module router the way
  ``ModuleLoader._load_module`` does (the kebab-case prefix plus the legacy
  underscore mirror), and then mounts the alias routers the lifespan adds after
  the loader. Those aliases are not copied into this file: they are read out of
  ``main.py`` by finding the function that awaits ``module_loader.load_all`` and
  taking every ``include_router(<imported router>, prefix="...")`` in it. A
  mount this cannot resolve fails the run rather than being skipped. Nothing is
  started, so no database is needed; the backend package has to be importable.

* The frontend side is every string or template literal in the committed
  ``frontend/src`` (tests, type declarations and locale bundles excluded) whose
  text starts with ``/v1/``, ``/v2/``, ``/api/v1/`` or ``/api/v2/``, or with a
  ``${CONST}`` naming a string constant declared in the same file. A template
  substitution stands for one path segment; it may also stand for nothing when
  it closes the literal or opens a query string, which is how ``${qs}`` is
  written. Everything from the first ``?`` on is dropped.

A literal is then one of:

* ``MISSING``: no route has that path under any method.
* ``SLASH``: a route exists once the trailing slash is added or removed.
* ``METHOD``: the literal is the first argument of ``apiGet``/``apiPost``/
  ``apiPatch``/``apiPut``/``apiDelete`` and the path is served, but not under
  that method.
* ``PREFIX``: the literal starts with a bare ``/v1/`` and is handed straight to
  something that does not prepend ``/api`` (``fetch``, ``downloadWithAuth``,
  ``window.open``, ``EventSource``, ``WebSocket``). Only ``request()`` in
  ``shared/lib/api.ts`` adds the prefix.

A literal can only be checked when its path starts with text the script can
read, so a path assembled from a constant imported from another file is not
checked at all. Those are counted and the count is printed on every run next
to the verdict, because a scan that quietly reads less than it claims to is
the failure this file exists to prevent, one level up.

``ALLOWED`` holds the calls that are known not to match and are right not to,
each with its reason. It is checked both ways: an entry that no longer names an
unmatched call fails the run, so the list can only shrink.

Usage::

    python scripts/check_frontend_api_routes.py                 # build the app, check
    python scripts/check_frontend_api_routes.py --report        # also list allowed entries
    python scripts/check_frontend_api_routes.py --dump-routes routes.json
    python scripts/check_frontend_api_routes.py --routes routes.json   # reuse a dumped table
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND = REPO_ROOT / "backend"
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"

# Floors, not targets. The tree held 2044 checkable literals and 5855 served
# routes (legacy mirrors included) when this was written; a run far below
# either has lost a source, not become clean.
MIN_CALLS = 1000
MIN_ROUTES = 2500
MIN_BEARER_ROUTES = 1000

API_PREFIXES = ("/v1/", "/v2/", "/api/v1/", "/api/v2/")
HELPER_METHODS = {
    "apiGet": "GET",
    "apiPost": "POST",
    "apiPatch": "PATCH",
    "apiPut": "PUT",
    "apiDelete": "DELETE",
}
# Callees that send the URL exactly as given, without request()'s "/api".
RAW_URL_CALLEES = frozenset({"fetch", "downloadWithAuth", "window.open", "EventSource", "WebSocket", "href", "src"})
# Of those, the ones the browser requests on its own: no code runs to add an
# Authorization header, so a route that reads only the bearer header answers
# 401 to every user. Verdict AUTH.
NAVIGATION_CALLEES = frozenset({"href", "src", "window.open", "EventSource"})
# Literals checked only as a prefix of some route, because nothing shows which
# call sends them (a builder's return, a const handed to another module). A
# ratchet, not a target: lower it when the count drops, never raise it to pass.
MAX_PREFIX_ONLY = 228

# Known unmatched calls that are right as they are. Key format:
#   "<VERDICT> <METHOD|*> <path as written> @ <file under frontend/src>"
# Every entry carries its reason; an entry that stops matching fails the run.
ALLOWED: dict[str, str] = {}


# --------------------------------------------------------------------------
# Frontend
# --------------------------------------------------------------------------


@dataclass
class Call:
    """One API path literal found in the frontend."""

    file: str
    line: int
    method: str | None
    callee: str | None
    parts: list[tuple[str, str]]
    concat: bool = False
    verdict: str = "OK"
    closest: list[str] = field(default_factory=list)
    as_prefix: bool = False

    @property
    def display(self) -> str:
        return "".join(v if k == "lit" else "{" + v + "}" for k, v in self.parts)

    @property
    def key(self) -> str:
        return f"{self.verdict} {self.method or '*'} {self.display} @ {self.file}"


_TEMPLATE_TEXT_RE = re.compile(r"[^`\\$]+")


def _scan_template(text: str, j: int) -> tuple[int, list[tuple[str, str]]]:
    """Read a template literal body starting after the opening backtick."""
    n = len(text)
    parts: list[tuple[str, str]] = []
    buf: list[str] = []
    while j < n:
        run = _TEMPLATE_TEXT_RE.match(text, j)
        if run:
            buf.append(run.group(0))
            j = run.end()
            continue
        ch = text[j]
        if ch == "\\":
            buf.append(text[j : j + 2])
            j += 2
            continue
        if ch == "`":
            if buf:
                parts.append(("lit", "".join(buf)))
            return j + 1, parts
        if ch == "$" and text.startswith("${", j):
            if buf:
                parts.append(("lit", "".join(buf)))
                buf = []
            depth = 1
            k = j + 2
            while k < n and depth:
                c = text[k]
                if c == "`":
                    k, _ = _scan_template(text, k + 1)
                    continue
                if c in "'\"":
                    k += 1
                    while k < n and text[k] != c:
                        k += 2 if text[k] == "\\" else 1
                    k += 1
                    continue
                if c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                k += 1
            parts.append(("sub", text[j + 2 : k - 1].strip()))
            j = k
            continue
        buf.append(ch)
        j += 1
    return j, parts


def scan_literal_spans(text: str):
    """Yield ``(start, end, parts)`` for every string and template literal outside comments.

    Regex literals are not recognised, which is safe for what is looked for
    here: a regex body that happened to contain a quote could only shift where
    the next literal is read from, and every API path literal in the tree sits
    in an ordinary call or assignment.
    """
    pos, n = 0, len(text)
    while pos < n:
        m = _TOKEN_RE.search(text, pos)
        if m is None:
            return
        tok = m.group(0)
        if tok == "`":
            end, parts = _scan_template(text, m.end())
            yield m.start(), end, parts
            pos = end
            continue
        if tok[0] in "'\"":
            yield m.start(), m.end(), [("lit", tok[1:-1])]
        pos = m.end()


def scan_literals(text: str):
    """Yield ``(start, parts)`` for every string and template literal outside comments."""
    for start, _end, parts in scan_literal_spans(text):
        yield start, parts


# Comments, single-line quoted strings, or the opening backtick of a template.
# An unterminated quote (an apostrophe in JSX text) matches up to the line end.
_TOKEN_RE = re.compile(r"//[^\n]*|/\*.*?(?:\*/|\Z)|'(?:\\.|[^'\\\n])*'?|\"(?:\\.|[^\"\\\n])*\"?|`", re.S)


_CONST_RE = re.compile(r"\bconst\s+([A-Za-z_$][\w$]*)\s*(?::\s*string\s*)?=\s*(['\"`])")
# A leading substitution that is probably an API base imported from elsewhere.
_BASE_NAME_RE = re.compile(r"(?i)(base|prefix|api|root|url)")
_STRING_OPS = frozenset(
    {"includes", "startsWith", "endsWith", "indexOf", "lastIndexOf", "replace", "match", "test", "split"}
)
# A URL written into a JSX attribute is fetched by the browser as written.
_ATTR_RE = re.compile(r"\b(href|src)\s*=\s*\{?\s*$")
_IDENT_TAIL_RE = re.compile(r"(?:new\s+)?([A-Za-z_$][\w$.]*)\s*$")
# ``const url = `...``` or ``let url: string = '...'`` right before a literal.
_ASSIGN_RE = re.compile(r"\b(?:const|let)\s+([A-Za-z_$][\w$]*)\s*(?::[^=;\n]+)?=\s*$")
_CLOSERS = {")": "(", "]": "[", "}": "{"}
# A declaration at column 0 starts the next top-level function or constant.
_TOP_LEVEL_DECL = re.compile(r"\n(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function|const|let|class)\b")


def _callee_at(text: str, paren: int) -> str | None:
    """The callee whose argument list opens at ``text[paren] == '('``.

    Steps back over a type argument list of any length, ``apiDelete<{ cb: () =>
    void }>(``, which a regex with a bounded window and no nesting could not.
    """
    j = paren - 1
    while j >= 0 and text[j].isspace():
        j -= 1
    if j >= 0 and text[j] == ">" and not (j and text[j - 1] == "="):
        depth = 0
        while j >= 0:
            c = text[j]
            if c == ">" and not (j and text[j - 1] == "="):
                depth += 1
            elif c == "<":
                depth -= 1
                if depth == 0:
                    j -= 1
                    break
            j -= 1
        else:
            return None
    m = _IDENT_TAIL_RE.search(text, max(0, j - 200), j + 1)
    return m.group(1) if m else None


def _enclosing_call(text: str, start: int) -> str | None:
    """The callee a literal at ``start`` is the first argument of, or None.

    A literal counts as the first argument when nothing but a ternary head sits
    between it and the open paren: ``apiGet(flag ? `/a/` : `/b`)`` hands either
    branch to ``apiGet``. A comma, a semicolon or a brace at the top level first
    means the literal is not that argument, and the scan gives up.
    """
    depth: list[str] = []
    j = start - 1
    lowest = max(0, start - 2000)
    while j >= lowest:
        c = text[j]
        if c in _CLOSERS:
            depth.append(_CLOSERS[c])
        elif c in "([{":
            if depth:
                if depth.pop() != c:
                    return None
            elif c == "(":
                between = text[j + 1 : start]
                if between.strip() and "?" not in between:
                    return None
                return _callee_at(text, j)
            else:
                return None
        elif not depth and c in ",;":
            return None
        j -= 1
    return None


_MAY_HOLD_API_RE = re.compile(r"/v[12]/|/api/|\bapi(?:Get|Post|Patch|Put|Delete)\b")
_FUNC_RE = re.compile(
    r"\bconst\s+([A-Za-z_$][\w$]*)\s*=\s*\(([^()]*)\)\s*(?::\s*string\s*)?=>\s*(`)"
    r"|\bfunction\s+([A-Za-z_$][\w$]*)\s*\(([^()]*)\)\s*(?::\s*string\s*)?\{\s*return\s+(`)"
)
_CALL_EXPR_RE = re.compile(r"^([A-Za-z_$][\w$]*)\((.*)\)$", re.S)


def _string_consts(text: str) -> dict[str, str]:
    """``const NAME = '...'`` declared in this file, templates built from such consts included.

    ``const RASTER_BASE = `${BASE}/raster-overlays``` resolves once ``BASE``
    does, so the table is filled to a fixpoint rather than in one pass.
    """
    consts: dict[str, str] = {"API_BASE": "/api", "BASE_URL": "/api"}
    pending: dict[str, list[tuple[str, str]]] = {}
    for m in _CONST_RE.finditer(text):
        start = m.end() - 1
        for _s, parts in scan_literals(text[start : start + 400]):
            if parts and all(k == "lit" for k, _ in parts):
                consts[m.group(1)] = "".join(v for _, v in parts)
            elif parts:
                pending[m.group(1)] = parts
            break
    changed = True
    while changed:
        changed = False
        for name, parts in list(pending.items()):
            if all(k == "lit" or v in consts for k, v in parts):
                consts[name] = "".join(v if k == "lit" else consts[v] for k, v in parts)
                del pending[name]
                changed = True
    return consts


def _url_functions(text: str) -> dict[str, list[tuple[str, str]]]:
    """Same-file helpers whose whole body is one template, ``(id) => `/v1/x/${id}```."""
    funcs: dict[str, list[tuple[str, str]]] = {}
    for m in _FUNC_RE.finditer(text):
        name = m.group(1) or m.group(4)
        start = m.end() - 1
        for _s, parts in scan_literals(text[start : start + 400]):
            funcs[name] = parts
            break
    return funcs


def _resolve_head(
    parts: list[tuple[str, str]], consts: dict[str, str], funcs: dict[str, list[tuple[str, str]]]
) -> list[tuple[str, str]] | None:
    """Replace a leading ``${CONST}`` or ``${helper(arg)}`` with what it stands for."""
    name = parts[0][1]
    if name in consts:
        return [("lit", consts[name]), *parts[1:]]
    call = _CALL_EXPR_RE.match(name)
    if call and call.group(1) in funcs:
        body = [("lit", consts[v]) if k == "sub" and v in consts else (k, v) for k, v in funcs[call.group(1)]]
        if body and body[0][0] == "lit":
            return [*body, *parts[1:]]
    return None


def extract_calls(text: str, rel: str) -> tuple[list[Call], int]:
    """Every checkable API literal in one file, and how many were unreadable."""
    if not _MAY_HOLD_API_RE.search(text):
        return [], 0
    consts = _string_consts(text)
    funcs = _url_functions(text)
    calls: list[Call] = []
    unresolved = 0
    for start, end, parts in scan_literal_spans(text):
        if not parts:
            continue
        if parts[0][0] == "sub":
            name = parts[0][1]
            resolved = _resolve_head(parts, consts, funcs)
            if resolved is not None:
                parts = resolved
            else:
                tail = parts[1][1] if len(parts) > 1 and parts[1][0] == "lit" else ""
                if tail.startswith("/") and _BASE_NAME_RE.search(name):
                    unresolved += 1
                continue
        if parts[0][0] != "lit" or not parts[0][1].startswith("/"):
            continue
        # merge adjacent literal parts produced by the const substitution
        merged: list[tuple[str, str]] = []
        for k, v in parts:
            if merged and k == "lit" and merged[-1][0] == "lit":
                merged[-1] = ("lit", merged[-1][1] + v)
            else:
                merged.append((k, v))
        before = text[max(0, start - 160) : start]
        attr = _ATTR_RE.search(before)
        callee = attr.group(1) if attr else _enclosing_call(text, start)
        head = merged[0][1]
        # A versioned path anywhere, an unversioned one under /api/ (/api/system/status),
        # or any path handed to a request helper, which puts /api in front of it.
        if not (
            head.startswith(API_PREFIXES)
            or (head.startswith("/api/") and len(head) > len("/api/"))
            or (callee in HELPER_METHODS and len(head) > 1 and head != "/api")
        ):
            continue
        if callee and callee.rsplit(".", 1)[-1] in _STRING_OPS:
            # url.includes('/api/v1/geo-hub/') tests a URL, it does not request one.
            continue
        # ``'/v1/x/' + id + '/'`` is a base with a tail added at run time.
        concat = text[end : end + 40].lstrip().startswith("+")
        line = text.count("\n", 0, start) + 1
        users = [] if callee else _variable_users(text, start, end)
        for user in users or [callee]:
            calls.append(
                Call(
                    file=rel,
                    line=line,
                    method=HELPER_METHODS.get(user) if user else None,
                    callee=user,
                    parts=merged,
                    concat=concat,
                )
            )
    return calls, unresolved


def _variable_users(text: str, start: int, end: int) -> list[str]:
    """The callees a literal stored in a local variable is handed to.

    ``const url = `/v1/x/${id}/`; return apiGet(url);`` requests the literal as
    surely as ``apiGet(`/v1/x/${id}/`)`` does, so it is checked the same way.
    The search runs from the literal to the next declaration of the same name
    or the next top-level declaration, whichever comes first, so two functions
    that both call their URL ``url`` do not borrow each other's method.
    """
    m = _ASSIGN_RE.search(text, max(0, start - 200), start)
    if not m:
        return []
    name = m.group(1)
    redecl = re.compile(rf"\b(?:const|let|var)\s+{re.escape(name)}\b|{_TOP_LEVEL_DECL.pattern}")
    stop_m = redecl.search(text, end)
    stop = stop_m.start() if stop_m else len(text)
    users = []
    for use in re.finditer(rf"\(\s*{re.escape(name)}\s*[,)]", text[:stop]):
        if use.start() < end:
            continue
        callee = _callee_at(text, use.start())
        if callee and callee.rsplit(".", 1)[-1] not in _STRING_OPS:
            users.append(callee)
    return users


def frontend_files() -> list[Path]:
    """The committed TypeScript sources, so CI and a dirty checkout read the same set."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "--", "frontend/src"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        paths = [REPO_ROOT / p for p in out]
    except (OSError, subprocess.CalledProcessError):
        paths = list(FRONTEND_SRC.rglob("*"))
    keep = []
    for p in paths:
        rel = p.relative_to(FRONTEND_SRC).as_posix()
        if not rel.endswith((".ts", ".tsx")) or rel.endswith(".d.ts"):
            continue
        if ".test." in rel or ".spec." in rel or "__tests__/" in rel or "/locales/" in rel:
            continue
        keep.append(p)
    return keep


# --------------------------------------------------------------------------
# Backend
# --------------------------------------------------------------------------


def _lifespan_mounts(main_py: Path) -> list[tuple[str, str, str]]:
    """``(module, attribute, prefix)`` for every router the lifespan mounts after the loader."""
    tree = ast.parse(main_py.read_text(encoding="utf-8"))
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.AsyncFunctionDef | ast.FunctionDef):
            continue
        body_src = ast.unparse(fn)
        if "module_loader.load_all(" not in body_src:
            continue
        if isinstance(fn, ast.FunctionDef) or fn.name == "load_all":
            continue
        imports: dict[str, tuple[str, str]] = {}
        mounts: list[tuple[str, str, str]] = []
        for node in ast.walk(fn):
            if isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    imports[alias.asname or alias.name] = (node.module, alias.name)
        for node in ast.walk(fn):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "include_router"
            ):
                continue
            arg = node.args[0] if node.args else None
            prefix = next((kw.value for kw in node.keywords if kw.arg == "prefix"), None)
            if not isinstance(arg, ast.Name) or arg.id not in imports or not isinstance(prefix, ast.Constant):
                raise SystemExit(f"cannot resolve a lifespan mount in main.py: {ast.unparse(node)}")
            module, attr = imports[arg.id]
            mounts.append((module, attr, prefix.value))
        if mounts:
            return mounts
    raise SystemExit("found no lifespan function awaiting module_loader.load_all in main.py")


def collect_backend_routes() -> list[tuple[str, frozenset[str]]]:
    """Build the app without starting it and return ``(path, methods)`` for every route."""
    import importlib

    sys.path.insert(0, str(BACKEND))
    os.chdir(BACKEND)
    # app.database builds (but never connects) an engine at import time and
    # refuses anything that is not a PostgreSQL URL.
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://oe:oe@127.0.0.1:1/oe_route_check")
    os.environ.setdefault("DATABASE_SYNC_URL", "postgresql+psycopg://oe:oe@127.0.0.1:1/oe_route_check")

    from app.core.module_loader import module_loader, served_routes
    from app.main import create_app

    app = create_app()
    module_loader.discover()
    failed: list[str] = []
    for name in module_loader.resolve_order():
        dir_name = name.removeprefix("oe_")
        package = f"app.modules.{dir_name}"
        try:
            router_mod = importlib.import_module(f"{package}.router")
        except ModuleNotFoundError as exc:
            if exc.name == f"{package}.router":
                continue
            failed.append(f"{name}: {exc}")
            continue
        router = getattr(router_mod, "router", None)
        if router is None:
            continue
        kebab = dir_name.replace("_", "-")
        app.include_router(router, prefix=f"/api/v1/{kebab}")
        if kebab != dir_name:
            app.include_router(router, prefix=f"/api/v1/{dir_name}")
    if failed:
        raise SystemExit(
            "module routers failed to import, their routes would read as missing:\n  " + "\n  ".join(failed)
        )
    for module, attr, prefix in _lifespan_mounts(BACKEND / "app" / "main.py"):
        app.include_router(getattr(importlib.import_module(module), attr), prefix=prefix)

    routes = []
    bearer = set()
    for path, route in served_routes(app):
        methods = getattr(route, "methods", None) or {"WS"}
        routes.append((path, frozenset(methods)))
        if _reads_only_the_bearer_header(route):
            bearer.add(path)
    return routes, frozenset(bearer)


def _reads_only_the_bearer_header(route: object) -> bool:
    """True when the route refuses a request that carries no Authorization header.

    That is any route whose dependency tree reaches ``get_current_user_payload``
    (401 "Not authenticated" when the header is absent), unless it also takes a
    ``token`` query parameter, the one fallback a link can carry.
    """
    dependant = getattr(route, "dependant", None)
    if dependant is None:
        return False
    stack, seen, required, token_query = [dependant], set(), False, False
    while stack:
        dep = stack.pop()
        if id(dep) in seen:
            continue
        seen.add(id(dep))
        if getattr(dep.call, "__name__", "") == "get_current_user_payload":
            required = True
        if any(p.name in ("token", "access_token") for p in dep.query_params):
            token_query = True
        stack.extend(dep.dependencies)
    return required and not token_query


# Stands for one template substitution inside a sample URL.
HOLE = "\x00"
# Stands for a substitution that reads as an identifier (``${id}``,
# ``${encodeURIComponent(projectId)}``): it fills a path parameter, never a
# segment the backend spells out, so ``/documents/${d.id}/file`` is not
# allowed to match ``/documents/photos/{photo_id}/file/``.
HOLE_ID = "\x01"
_ID_EXPR_RE = re.compile(r"(?i)(id|uuid|key|hash)\b|(id|uuid)\)*$|encodeURIComponent")


def _segment_regex(seg: str) -> re.Pattern[str]:
    """A backend segment with a parameter inside it, ``export.{fmt}`` or ``{name}.json``."""
    out = []
    for piece in re.split(r"(\{[^}]+\})", seg):
        out.append("[^/]+" if piece.startswith("{") else re.escape(piece))
    return re.compile("".join(out))


def _hole_regex(seg: str) -> re.Pattern[str]:
    """A frontend segment with a substitution inside it, ``form.${fmt}``."""
    return re.compile("[^/]+".join(re.escape(p) for p in re.split(f"[{HOLE}{HOLE_ID}]", seg)))


class RouteTable:
    """Segment trie over route templates, so each lookup is a walk rather than a scan."""

    def __init__(self, routes: list[tuple[str, frozenset[str]]], bearer: frozenset[str] = frozenset()) -> None:
        self.root: dict = {}
        self.count = len(routes)
        # Templates that answer 401 without an Authorization header.
        self.bearer = bearer
        for path, methods in routes:
            node = self.root
            for seg in path.split("/")[1:]:
                if seg.startswith("{") and seg.endswith(":path}"):
                    node = node.setdefault("\x00rest", {})
                    break
                if seg.startswith("{") and seg.endswith("}") and seg.count("{") == 1:
                    key = "\x00param"
                elif "{" in seg:
                    key = "\x00re" + seg
                else:
                    key = seg
                node = node.setdefault(key, {})
            ends = node.setdefault("\x00end", {})
            ends[path] = ends.get(path, frozenset()) | methods

    @staticmethod
    def _children(node: dict, seg: str):
        """The child nodes a sample segment can descend into."""
        if seg == HOLE_ID:
            for key, child in node.items():
                if key == "\x00param" or key.startswith("\x00re"):
                    yield child
            return
        if HOLE not in seg and HOLE_ID not in seg:
            if seg in node:
                # A word the backend spells out at this level names that route
                # family. Letting it fall through to a sibling {param} as well
                # would pass GET /enterprise-workflows/requests as a lookup of a
                # workflow whose id is "requests" (a 422 in production) and hide
                # the missing slash of /requests/.
                yield node[seg]
                return
            if seg and "\x00param" in node:
                yield node["\x00param"]
            for key, child in node.items():
                if key.startswith("\x00re") and _segment_regex(key[3:]).fullmatch(seg):
                    yield child
            return
        # A substitution may be any value, including a literal segment the
        # backend spells out, e.g. /moc/{id}/${action} against /moc/{id}/approve.
        rx = _hole_regex(seg)
        for key, child in node.items():
            if key in ("\x00end", "\x00rest"):
                continue
            if key == "\x00param" or key.startswith("\x00re") or rx.fullmatch(key):
                yield child

    @staticmethod
    def _all_ends(node: dict, found: dict[str, frozenset[str]]) -> None:
        for key, child in node.items():
            if key == "\x00end":
                found.update(child)
            else:
                RouteTable._all_ends(child, found)

    def lookup(self, path: str, *, as_prefix: bool = False) -> dict[str, frozenset[str]]:
        """Every template matching a sample URL, or starting with it when ``as_prefix``."""
        found: dict[str, frozenset[str]] = {}
        segs = path.split("/")[1:]

        def walk(node: dict, i: int) -> None:
            if "\x00rest" in node and i < len(segs):
                found.update(node["\x00rest"].get("\x00end", {}))
            if i == len(segs):
                if as_prefix:
                    self._all_ends(node, found)
                else:
                    found.update(node.get("\x00end", {}))
                return
            if as_prefix and i == len(segs) - 1 and segs[i] == "":
                self._all_ends(node, found)
                return
            for child in self._children(node, segs[i]):
                walk(child, i + 1)

        walk(self.root, 0)
        return found


# A closing substitution that builds a query string: ``${qs}``, ``${typesQs}``,
# ``${query ? `?${query}` : ''}``, ``${params.toString()}``.
# Whole identifiers only: ``${queryId}`` and ``${subqueryType}`` are path segments.
_QUERY_EXPR_RE = re.compile(r"['\"`]\?|\b\w*(?:qs|Qs|QS)\b|\b\w*[Qq]uery\b|toString\(\)|URLSearchParams")


def _samples(parts: list[tuple[str, str]]) -> tuple[list[str], bool]:
    """Sample URLs a literal can produce, with ``/api`` in front and HOLE for a substitution.

    The flag is true when the literal ends in a substitution glued to a word,
    ``/api/v1/ai-estimator${path}``: that is a base with an unknown tail, so it
    can only be checked as a prefix of some route.
    """
    first = parts[0][1]
    if first.startswith("/api/"):
        parts = [("lit", first[4:]), *parts[1:]]
    samples = [""]
    open_tail = False
    for idx, (kind, value) in enumerate(parts):
        if kind == "lit":
            samples = [s + value for s in samples]
            continue
        prev = parts[idx - 1][1] if idx and parts[idx - 1][0] == "lit" else ""
        nxt_kind, nxt = parts[idx + 1] if idx + 1 < len(parts) else ("lit", "")
        if nxt == "" and _QUERY_EXPR_RE.search(value):
            # ``/bids${qs ? `?${qs}` : ''}`` adds a query string or nothing, so the
            # path ends here. Read as an open tail it would hide the missing slash.
            break
        if nxt == "" and prev and (prev[-1].isalnum() or prev[-1] in "-_"):
            open_tail = True
            break
        hole = HOLE_ID if _ID_EXPR_RE.search(value) else HOLE
        # ``${qs}${typesQs}``: a substitution followed by another one may be empty
        # too. An id never is: ``/x/${id}`` read as possibly ``/x/`` would let the
        # list route answer for a missing or misspelt item route.
        may_be_empty = hole == HOLE and (nxt_kind == "sub" or nxt == "" or nxt[:1] in "?&")
        samples = [s + hole for s in samples] + (list(samples) if may_be_empty else [])
        samples = samples[:64]
    return ["/api" + s.split("?", 1)[0].split("#", 1)[0] for s in samples], open_tail


def classify(call: Call, table: RouteTable) -> None:
    """Set ``call.verdict`` and ``call.closest``.

    A literal handed straight to a call is the URL of that request and has to
    match a route exactly. A literal that is only stored (a ``const BASE``, a
    ``return`` from a URL builder) is checked as a prefix: it has to lead to
    some route, and the calls that extend it are checked where they are made.
    """
    samples, open_tail = _samples(call.parts)
    as_prefix = open_tail or call.concat or call.callee is None
    call.as_prefix = as_prefix
    method = None if as_prefix else call.method

    def serving(found: dict[str, frozenset[str]]) -> dict[str, frozenset[str]]:
        return {p: m for p, m in found.items() if method is None or method in m}

    hits: dict[str, frozenset[str]] = {}
    flipped: dict[str, frozenset[str]] = {}
    for s in samples:
        hits.update(table.lookup(s, as_prefix=as_prefix))
        flipped.update(table.lookup(s[:-1] if s.endswith("/") else s + "/", as_prefix=as_prefix))
    if serving(hits):
        pass
    elif serving(flipped):
        call.verdict = "SLASH"
        call.closest = sorted(serving(flipped))[:3]
        return
    elif hits:
        call.verdict = "METHOD"
        call.closest = [f"{','.join(sorted(m))} {p}" for p, m in sorted(hits.items())[:3]]
        return
    else:
        call.verdict = "MISSING"
        call.closest = sorted(flipped)[:3]
        return
    if call.callee in RAW_URL_CALLEES and not call.parts[0][1].startswith("/api/"):
        call.verdict = "PREFIX"
        call.closest = sorted(hits)[:3]
        return
    served = serving(hits)
    if call.callee in NAVIGATION_CALLEES and all(p in table.bearer for p in served):
        # The browser opens these itself and sends no Authorization header.
        call.verdict = "AUTH"
        call.closest = sorted(served)[:3]
        return
    call.verdict = "OK"


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--routes", type=Path, help="read the backend route table from this JSON file")
    parser.add_argument("--dump-routes", type=Path, help="write the backend route table to this JSON file")
    parser.add_argument("--report", action="store_true", help="also list the allowed unmatched calls")
    parser.add_argument("--json", type=Path, help="write every unmatched call to this JSON file")
    args = parser.parse_args(argv)

    if args.routes:
        dumped = json.loads(args.routes.read_text())["routes"]
        routes = [(r["path"], frozenset(r["methods"])) for r in dumped]
        bearer = frozenset(r["path"] for r in dumped if r.get("bearer"))
    else:
        routes, bearer = collect_backend_routes()
    if args.dump_routes:
        args.dump_routes.write_text(
            json.dumps(
                {"routes": [{"path": p, "methods": sorted(m), "bearer": p in bearer} for p, m in routes]},
                indent=0,
            )
        )
    table = RouteTable(routes, bearer)

    calls: list[Call] = []
    unresolved = 0
    files = frontend_files()
    for path in files:
        found, skipped = extract_calls(path.read_text(encoding="utf-8"), path.relative_to(FRONTEND_SRC).as_posix())
        calls.extend(found)
        unresolved += skipped
    for call in calls:
        classify(call, table)

    bad = [c for c in calls if c.verdict != "OK"]
    keys = {c.key for c in bad}
    new = [c for c in bad if c.key not in ALLOWED]
    stale = sorted(k for k in ALLOWED if k not in keys)
    verdicts = Counter(c.verdict for c in calls)

    print(
        f"backend routes: {table.count}; frontend files: {len(files)}; API literals checked: {len(calls)}; "
        f"skipped (prefix from an imported name): {unresolved}"
    )
    print("verdicts: " + ", ".join(f"{k}={v}" for k, v in sorted(verdicts.items())) + f"; allowed: {len(ALLOWED)}")
    # Stored literals (a const BASE, a URL builder's return) are only checked as
    # a prefix of some route, so a missing slash in one of them passes here and
    # is caught where the call extends it. Printed so the green line does not
    # claim more than it read.
    prefix_only = sum(c.as_prefix for c in calls)
    print(
        f"checked as a prefix only (not handed straight to a call): {prefix_only} "
        f"(ratchet {MAX_PREFIX_ONLY}); routes that need the bearer header: {len(bearer)}"
    )

    if args.json:
        args.json.write_text(
            json.dumps(
                [
                    {
                        "file": c.file,
                        "line": c.line,
                        "method": c.method,
                        "callee": c.callee,
                        "path": c.display,
                        "verdict": c.verdict,
                        "closest": c.closest,
                        "allowed": c.key in ALLOWED,
                    }
                    for c in bad
                ],
                indent=1,
            )
        )

    failed = False
    if table.count < MIN_ROUTES or len(calls) < MIN_CALLS:
        print(
            f"FAIL: population below the floor (routes {table.count} < {MIN_ROUTES} or calls {len(calls)} < {MIN_CALLS})"
        )
        failed = True
    if not args.routes and len(bearer) < MIN_BEARER_ROUTES:
        # Nearly every route reads the bearer header; a count near zero means the
        # dependency walk stopped finding it and AUTH went quiet with it.
        print(f"FAIL: only {len(bearer)} routes read as needing the bearer header (< {MIN_BEARER_ROUTES})")
        failed = True
    if prefix_only > MAX_PREFIX_ONLY:
        print(
            f"FAIL: {prefix_only} literals are checked only as a prefix, above the ratchet of {MAX_PREFIX_ONLY}. "
            "Hand the new ones straight to their call, or say why they cannot be."
        )
        failed = True
    if new:
        failed = True
        print(f"\nFAIL: {len(new)} frontend API call(s) no backend route answers:")
        for c in sorted(new, key=lambda c: (c.file, c.line)):
            hint = f"  (closest: {'; '.join(c.closest)})" if c.closest else ""
            print(f"  frontend/src/{c.file}:{c.line}  {c.verdict} {c.method or '*'} {c.display}{hint}")
        print("\nFix the path, or if the call is right as it is, add its key to ALLOWED with the reason.")
    if stale:
        failed = True
        print(f"\nFAIL: {len(stale)} ALLOWED entr(y/ies) no longer name an unmatched call; delete them:")
        for k in stale:
            print(f"  {k}")
    if args.report:
        for c in bad:
            if c.key in ALLOWED:
                print(f"  allowed: {c.key}")
    if not failed:
        print("OK: every checked frontend API call has a backend route.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
