#!/usr/bin/env python3
"""The route table the single-page application can actually serve.

Two things in this repository need to know which URLs the app answers, and
until now each of them worked it out for itself. They disagreed, and the
disagreement was not academic. ``scripts/check_case_routes.py`` read
``<Route path="...">`` out of ``App.tsx`` plus quoted ``path:`` properties out
of the module manifests and reported "293 in App.tsx, 8 from module
manifests". ``marketing-site/scripts/check-app-routes.mjs``, the gate that
compares the router against the reverse proxy's allowlist, read only
``App.tsx``. Neither of them could see the twenty routes
``modules/regional-exchange/manifest.tsx`` builds from a table, because it
writes them as ``path: `/${tpl.routeSlug}` `` rather than as literals.

The cost of that blind spot was paid on 2026-09-09: the whole regional BOQ
exchange feature, the hub plus twenty country screens, answered the static
site's 404 on the public origin, and the gate that exists for exactly this
class of drift ran green over them because it never knew they were routes.

So there is now one collector, this module, and everything that wants the
route table calls it. It reads both sources, it resolves the computed paths
rather than skipping them, and anything it cannot resolve comes back in
``unresolved`` rather than being quietly dropped. A collector that drops what
it does not understand reports agreement it has not measured, which is the
failure being fixed here, not a smaller version of it.

Two sources, and only two. Every other ``<Route `` in ``frontend/src`` is
lucide-react's ``Route`` icon, and there is no ``createBrowserRouter`` or
``useRoutes`` anywhere in the tree. To keep that true rather than merely
remembered, ``collect`` cross-checks the manifests it read on disk against the
modules ``_registry.ts`` actually imports and fails on a mismatch in either
direction: a manifest nobody registers contributes no routes at run time, and
a registered module whose manifest this cannot find is a route source that has
moved out from under the glob.

What the resolver supports, deliberately narrowly:

  * a quoted string, ``path: '/gaeb-exchange'``
  * a template literal with no substitution, which is the same thing
  * a template literal whose substitutions are all ``param.prop``, inside a
    ``ARRAY.map((param) => ...)`` whose ``ARRAY`` is a const array of object
    literals defined in the same file or imported from a relative one

Anything else is UNRESOLVED and fails the caller. The temptation is to widen
this until it covers whatever the next manifest does; do not. A resolver that
stretches to a shape it half understands answers with a path that looks right
and is not, and a wrong path in an allowlist is invisible in a way a missing
one is not. Widen it only by adding another exact shape.

Run it directly to see the table:

    python scripts/app_routes.py            # human readable, exit 1 if anything is unresolved
    python scripts/app_routes.py --json     # machine readable, same exit codes
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_TSX = REPO_ROOT / "frontend" / "src" / "app" / "App.tsx"
MODULES_DIR = REPO_ROOT / "frontend" / "src" / "modules"
REGISTRY_TS = MODULES_DIR / "_registry.ts"
MANIFEST_NAMES = ("manifest.ts", "manifest.tsx")
SRC_DIR = REPO_ROOT / "frontend" / "src"

IDENT = r"[A-Za-z_$][A-Za-z0-9_$]*"


@dataclass(frozen=True)
class Route:
    """One path the router declares, with where it came from and how."""

    path: str
    #: "App.tsx" or the module directory name.
    source: str
    #: "literal" when the source wrote the path out, "resolved" when this
    #: module computed it from a table.
    origin: str
    #: None for App.tsx routes.
    module_id: str | None = None
    #: Whether the owning module ships switched on. None for App.tsx routes.
    default_enabled: bool | None = None

    @property
    def segment(self) -> str:
        """The top-level path segment, which is what the proxy allowlist keys on."""
        return self.path.lstrip("/").split("/")[0].strip()


@dataclass(frozen=True)
class Unresolved:
    """A route declaration that was found and could not be turned into a path."""

    file: str
    line: int
    expression: str
    reason: str


@dataclass
class RouteTable:
    app_routes: list[Route] = field(default_factory=list)
    module_routes: list[Route] = field(default_factory=list)
    unresolved: list[Unresolved] = field(default_factory=list)
    #: Module directory names that had a manifest on disk.
    manifests_read: list[str] = field(default_factory=list)
    #: Module directory names imported by _registry.ts.
    registry_modules: list[str] = field(default_factory=list)
    #: Pathless layout routes in App.tsx. They carry no path and are not drift.
    layout_routes: int = 0
    #: How many module routes came out of a computed expression.
    resolved_count: int = 0

    @property
    def routes(self) -> list[Route]:
        return self.app_routes + self.module_routes

    # There is deliberately no enabled_routes() helper here. Only
    # check_case_routes.py wants that population, it wants it without the
    # catch-all as well, and it needs the App.tsx and manifest halves counted
    # separately for its own summary line, so it filters on
    # ``default_enabled`` where it uses it. One helper that no consumer could
    # call as it stands, asserted by the self test and used by nobody, is the
    # same shape as the defect this module was written to remove: a tested
    # path and a shipped path doing one job twice.


# ─── Source scanner ────────────────────────────────────────────────────────
#
# Small enough to read, strict enough to trust. It marks which characters are
# code rather than string or comment, and records the bracket nesting, so that
# a `path:` inside a comment or a translation value is not mistaken for a route
# and so that the `.map(` that encloses a computed path can be found without
# counting parentheses by hand.

_REGEX_PRECEDERS = set("(,=:[!&|?{};\n+-*%<>~^")
_REGEX_PRECEDING_WORDS = {"return", "typeof", "case", "in", "of", "do", "else", "yield", "await"}


class _Scan:
    """Character classification and bracket nesting for one source file."""

    def __init__(self, src: str) -> None:
        self.src = src
        n = len(src)
        self.is_code = [False] * n
        #: Index of the innermost bracket open at this character, or -1.
        self.enclosing = [-1] * n
        #: Open bracket index to its matching close index.
        self.close_of: dict[int, int] = {}
        self._run()

    def parent_of(self, open_index: int) -> int:
        """The bracket enclosing the bracket that opens at ``open_index``."""
        return self.enclosing[open_index]

    def ancestors(self, index: int) -> list[int]:
        """Open-bracket indices enclosing ``index``, innermost first."""
        out: list[int] = []
        cur = self.enclosing[index] if 0 <= index < len(self.enclosing) else -1
        while cur != -1:
            out.append(cur)
            cur = self.parent_of(cur)
        return out

    def _regex_allowed(self, i: int) -> bool:
        """Whether a ``/`` at ``i`` starts a regex literal rather than a division."""
        j = i - 1
        while j >= 0 and self.src[j] in " \t":
            j -= 1
        if j < 0:
            return True
        ch = self.src[j]
        if ch in _REGEX_PRECEDERS:
            return True
        if ch.isalnum() or ch == "_":
            k = j
            while k >= 0 and (self.src[k].isalnum() or self.src[k] == "_"):
                k -= 1
            return self.src[k + 1 : j + 1] in _REGEX_PRECEDING_WORDS
        return False

    def _run(self) -> None:  # noqa: C901 - one flat state machine, splitting it hides it
        src = self.src
        n = len(src)
        brackets: list[int] = []
        # Each entry is ("tpl", brace_depth_at_entry) for a template literal we
        # are inside, so a `}` closing a `${}` returns us to template text.
        template_stack: list[int] = []
        i = 0
        while i < n:
            c = src[i]
            self.is_code[i] = True
            self.enclosing[i] = brackets[-1] if brackets else -1

            if c == "/" and i + 1 < n and src[i + 1] == "/":
                j = src.find("\n", i)
                i = n if j == -1 else j
                continue
            if c == "/" and i + 1 < n and src[i + 1] == "*":
                j = src.find("*/", i + 2)
                i = n if j == -1 else j + 2
                continue
            if c in "'\"":
                i = self._skip_quoted(i)
                continue
            if c == "/" and self._regex_allowed(i):
                skipped = self._skip_regex(i)
                if skipped is not None:
                    i = skipped
                    continue
            if c == "`":
                i, brackets, template_stack = self._enter_template(i, brackets, template_stack)
                continue
            if c in "([{":
                self.enclosing[i] = brackets[-1] if brackets else -1
                brackets.append(i)
                i += 1
                continue
            if c in ")]}":
                if c == "}" and template_stack and len(brackets) == template_stack[-1] + 1:
                    # This `}` closes a `${` substitution, so we drop back into
                    # template text rather than plain code.
                    open_i = brackets.pop()
                    self.close_of[open_i] = i
                    template_stack.pop()
                    i = self._resume_template(i + 1, brackets, template_stack)
                    continue
                if brackets:
                    open_i = brackets.pop()
                    self.close_of[open_i] = i
                i += 1
                continue
            i += 1

    def _skip_quoted(self, i: int) -> int:
        src = self.src
        quote = src[i]
        j = i + 1
        while j < len(src):
            if src[j] == "\\":
                self.is_code[j] = False
                if j + 1 < len(src):
                    self.is_code[j + 1] = False
                j += 2
                continue
            self.is_code[j] = False
            if src[j] == quote:
                return j + 1
            if src[j] == "\n":
                # Unterminated string literal. Give up on the rest of the line
                # rather than swallowing the file.
                return j + 1
            j += 1
        return j

    def _skip_regex(self, i: int) -> int | None:
        """Skip a regex literal, or return None if this ``/`` does not start one."""
        src = self.src
        j = i + 1
        in_class = False
        while j < len(src):
            ch = src[j]
            if ch == "\\":
                j += 2
                continue
            if ch == "\n":
                return None
            if ch == "[":
                in_class = True
            elif ch == "]":
                in_class = False
            elif ch == "/" and not in_class:
                for k in range(i + 1, j + 1):
                    self.is_code[k] = False
                j += 1
                while j < len(src) and src[j].isalpha():
                    self.is_code[j] = False
                    j += 1
                return j
            j += 1
        return None

    def _enter_template(
        self, i: int, brackets: list[int], template_stack: list[int]
    ) -> tuple[int, list[int], list[int]]:
        template_stack.append(len(brackets))
        return self._resume_template(i + 1, brackets, template_stack), brackets, template_stack

    def _resume_template(self, j: int, brackets: list[int], template_stack: list[int]) -> int:
        """Consume template text from ``j`` until the closing backtick or a ``${``."""
        src = self.src
        n = len(src)
        while j < n:
            if src[j] == "\\":
                self.is_code[j] = False
                if j + 1 < n:
                    self.is_code[j + 1] = False
                j += 2
                continue
            if src[j] == "`":
                self.is_code[j] = False
                if template_stack:
                    template_stack.pop()
                return j + 1
            if src[j] == "$" and j + 1 < n and src[j + 1] == "{":
                self.is_code[j] = False
                self.enclosing[j + 1] = brackets[-1] if brackets else -1
                self.is_code[j + 1] = True
                template_stack.append(len(brackets))
                brackets.append(j + 1)
                return j + 2
            self.is_code[j] = False
            j += 1
        return j


def _line_of(src: str, index: int) -> int:
    return src.count("\n", 0, index) + 1


# ─── App.tsx ───────────────────────────────────────────────────────────────

_ROUTE_TAG_RE = re.compile(r"<Route\s")
_PATH_ATTR_RE = re.compile(r'path\s*=\s*"([^"]*)"')
_PATH_ATTR_EXPR_RE = re.compile(r"path\s*=\s*\{")


def read_app_routes(app_tsx: Path) -> tuple[list[Route], int, list[Unresolved]]:
    """Every path App.tsx declares, plus the count of pathless layout routes.

    A ``<Route>`` with no ``path`` is a layout wrapper (``<Route
    element={<AppShell />}>``) and contributes nothing to the URL space, so it
    is counted rather than treated as drift. A ``path={expr}`` is a computed
    route this cannot follow, and is reported rather than skipped: App.tsx has
    none today, and the day it grows one is exactly the day silence would cost
    us another feature on the public origin.
    """
    src = app_tsx.read_text(encoding="utf-8", errors="replace")
    scan = _Scan(src)
    routes: list[Route] = []
    unresolved: list[Unresolved] = []
    layouts = 0
    for m in _ROUTE_TAG_RE.finditer(src):
        if not scan.is_code[m.start()]:
            continue
        end = src.find(">", m.start())
        tag = src[m.start() : end if end != -1 else m.start() + 400]
        attr = _PATH_ATTR_RE.search(tag)
        if attr:
            routes.append(Route(path=attr.group(1), source="App.tsx", origin="literal"))
            continue
        expr = _PATH_ATTR_EXPR_RE.search(tag)
        if expr:
            unresolved.append(
                Unresolved(
                    file=str(app_tsx),
                    line=_line_of(src, m.start()),
                    expression=tag.strip(),
                    reason="a Route path written as an expression; this collector reads literals only",
                )
            )
            continue
        layouts += 1
    return routes, layouts, unresolved


# ─── Module manifests ──────────────────────────────────────────────────────

_PATH_PROP_RE = re.compile(r"(?<![A-Za-z0-9_$])path\s*:")
_DEFAULT_ENABLED_RE = re.compile(r"defaultEnabled\s*:\s*(true|false)")
_REGISTRY_IMPORT_RE = re.compile(r"from\s+['\"]\./([^'\"/]+)/manifest['\"]")


def read_registry_modules(registry_ts: Path) -> list[str]:
    """The module directories ``_registry.ts`` imports a manifest from."""
    src = registry_ts.read_text(encoding="utf-8", errors="replace")
    scan = _Scan(src)
    names: list[str] = []
    for m in _REGISTRY_IMPORT_RE.finditer(src):
        if scan.is_code[m.start()]:
            names.append(m.group(1))
    return sorted(set(names))


def _read_string_at(src: str, j: int) -> tuple[str, int] | None:
    """Read a quoted string starting at ``j``, returning its value and end index."""
    if j >= len(src) or src[j] not in "'\"":
        return None
    quote = src[j]
    out: list[str] = []
    k = j + 1
    while k < len(src):
        if src[k] == "\\" and k + 1 < len(src):
            out.append(src[k + 1])
            k += 2
            continue
        if src[k] == quote:
            return "".join(out), k + 1
        if src[k] == "\n":
            return None
        out.append(src[k])
        k += 1
    return None


def _read_template_at(src: str, j: int) -> tuple[str, int] | None:
    """Read a template literal starting at the backtick ``j``, raw body and end."""
    if j >= len(src) or src[j] != "`":
        return None
    k = j + 1
    depth = 0
    while k < len(src):
        if src[k] == "\\":
            k += 2
            continue
        if src[k] == "$" and k + 1 < len(src) and src[k + 1] == "{":
            depth += 1
            k += 2
            continue
        if src[k] == "}" and depth:
            depth -= 1
            k += 1
            continue
        if src[k] == "`" and depth == 0:
            return src[j + 1 : k], k + 1
        k += 1
    return None


_TEMPLATE_PART_RE = re.compile(r"\$\{([^{}]*)\}")
_MEMBER_RE = re.compile(rf"^({IDENT})\.({IDENT})$")


def _find_const_array(src: str, scan: _Scan, name: str) -> int | None:
    """Index of the ``[`` opening the array ``const <name> = [ ... ]``."""
    pattern = re.compile(rf"(?:export\s+)?const\s+{re.escape(name)}\b[^=;]*?=\s*\[")
    for m in pattern.finditer(src):
        if scan.is_code[m.start()]:
            return m.end() - 1
    return None


def _resolve_import(manifest: Path, src: str, scan: _Scan, name: str) -> Path | None:
    """The file a named import of ``name`` comes from, if it is followable."""
    for m in re.finditer(r"import\s+(?:type\s+)?\{([^}]*)\}\s*from\s*['\"]([^'\"]+)['\"]", src):
        if not scan.is_code[m.start()]:
            continue
        names = [part.strip() for part in m.group(1).split(",")]
        hit = False
        for part in names:
            local = part.split(" as ")[-1].strip() if " as " in part else part
            if local == name:
                hit = True
        if not hit:
            continue
        spec = m.group(2)
        if spec.startswith("."):
            base = (manifest.parent / spec).resolve()
        elif spec.startswith("@/"):
            base = (SRC_DIR / spec[2:]).resolve()
        else:
            return None
        for candidate in (
            base.with_suffix(".ts"),
            base.with_suffix(".tsx"),
            base / "index.ts",
            base / "index.tsx",
            base,
        ):
            if candidate.is_file():
                return candidate
        return None
    return None


def _array_entry_property(src: str, scan: _Scan, obj_open: int, prop: str) -> str | None:
    """The string value of ``prop`` directly on the object literal at ``obj_open``."""
    obj_close = scan.close_of.get(obj_open)
    if obj_close is None:
        return None
    prop_re = re.compile(rf"(?<![A-Za-z0-9_$]){re.escape(prop)}\s*:")
    for m in prop_re.finditer(src, obj_open, obj_close):
        if not scan.is_code[m.start()] or scan.enclosing[m.start()] != obj_open:
            continue
        j = m.end()
        while j < len(src) and src[j] in " \t":
            j += 1
        read = _read_string_at(src, j)
        if read is None:
            return None
        return read[0]
    return None


def _resolve_computed_path(
    manifest: Path,
    src: str,
    scan: _Scan,
    template_body: str,
    at: int,
) -> tuple[list[str], str | None]:
    """Turn ``/${tpl.routeSlug}`` into one path per entry of the mapped array.

    Returns ``(paths, failure_reason)``. Exactly one of the two is meaningful:
    an empty path list always comes with a reason.
    """
    exprs = _TEMPLATE_PART_RE.findall(template_body)
    if not exprs:
        return [template_body], None

    members: list[tuple[str, str]] = []
    for expr in exprs:
        member = _MEMBER_RE.match(expr.strip())
        if not member:
            return [], f"substitution `${{{expr.strip()}}}` is not a simple param.property reference"
        members.append((member.group(1), member.group(2)))
    params = {p for p, _ in members}
    if len(params) != 1:
        return [], f"substitutions read from more than one variable: {sorted(params)}"
    param = members[0][0]

    map_call = None
    for open_index in scan.ancestors(at):
        if src[open_index] != "(":
            continue
        before = re.search(rf"({IDENT}(?:\.{IDENT})*)\s*\.\s*map\s*$", src[:open_index])
        if before:
            map_call = (open_index, before.group(1))
            break
    if map_call is None:
        return [], f"`{param}` is not bound by any enclosing `.map(` call this collector can see"
    open_index, array_expr = map_call

    arrow_param = re.match(rf"\s*\(?\s*({IDENT})", src[open_index + 1 :])
    if not arrow_param or arrow_param.group(1) != param:
        return [], f"the enclosing `.map(` binds `{arrow_param.group(1) if arrow_param else '?'}`, not `{param}`"

    if "." in array_expr:
        return [], f"the mapped value `{array_expr}` is a member expression, not a plain array name"

    array_src, array_scan, array_file = src, scan, manifest
    array_open = _find_const_array(src, scan, array_expr)
    if array_open is None:
        imported = _resolve_import(manifest, src, scan, array_expr)
        if imported is None:
            return [], f"cannot find where `{array_expr}` is defined or imported from"
        array_file = imported
        array_src = imported.read_text(encoding="utf-8", errors="replace")
        array_scan = _Scan(array_src)
        array_open = _find_const_array(array_src, array_scan, array_expr)
        if array_open is None:
            return [], f"`{array_expr}` is imported from {imported.name} but is not a const array literal there"

    array_close = array_scan.close_of.get(array_open)
    if array_close is None:
        return [], f"the array literal `{array_expr}` in {array_file.name} is not closed"

    entries = [
        i
        for i in range(array_open + 1, array_close)
        if array_src[i] == "{" and array_scan.is_code[i] and array_scan.enclosing[i] == array_open
    ]
    if not entries:
        return [], f"`{array_expr}` in {array_file.name} has no object-literal entries"

    paths: list[str] = []
    for entry in entries:
        rendered = template_body
        for _, prop in members:
            value = _array_entry_property(array_src, array_scan, entry, prop)
            if value is None:
                line = _line_of(array_src, entry)
                return [], f"entry at {array_file.name}:{line} has no string `{prop}` property"
            rendered = rendered.replace("${" + f"{param}.{prop}" + "}", value, 1)
            rendered = _TEMPLATE_PART_RE.sub(
                lambda m, p=prop, v=value: v if m.group(1).strip() == f"{param}.{p}" else m.group(0),
                rendered,
            )
        if "${" in rendered or not rendered.strip():
            return [], f"entry at {array_file.name}:{_line_of(array_src, entry)} did not render to a path"
        paths.append(rendered)

    if len(paths) != len(entries):
        return [], f"resolved {len(paths)} paths from {len(entries)} entries of `{array_expr}`"
    return paths, None


def read_module_routes(modules_dir: Path) -> tuple[list[Route], list[Unresolved], list[str], int]:
    """Every route the bundled module manifests declare, computed ones included."""
    routes: list[Route] = []
    unresolved: list[Unresolved] = []
    manifests_read: list[str] = []
    resolved_count = 0

    for module_dir in sorted(p for p in modules_dir.iterdir() if p.is_dir()):
        manifest = next((module_dir / name for name in MANIFEST_NAMES if (module_dir / name).is_file()), None)
        if manifest is None:
            continue
        manifests_read.append(module_dir.name)
        src = manifest.read_text(encoding="utf-8", errors="replace")
        scan = _Scan(src)

        enabled_match = _DEFAULT_ENABLED_RE.search(src)
        if enabled_match is None:
            unresolved.append(
                Unresolved(
                    file=str(manifest),
                    line=1,
                    expression="defaultEnabled",
                    reason="the manifest declares no defaultEnabled, so whether its routes ship on is unknown",
                )
            )
            default_enabled = None
        else:
            default_enabled = enabled_match.group(1) == "true"

        for m in _PATH_PROP_RE.finditer(src):
            if not scan.is_code[m.start()]:
                continue
            j = m.end()
            while j < len(src) and src[j] in " \t\n":
                j += 1
            line = _line_of(src, m.start())

            literal = _read_string_at(src, j)
            if literal is not None:
                routes.append(
                    Route(
                        path=literal[0],
                        source=module_dir.name,
                        origin="literal",
                        module_id=module_dir.name,
                        default_enabled=default_enabled,
                    )
                )
                continue

            template = _read_template_at(src, j)
            if template is not None:
                paths, reason = _resolve_computed_path(manifest, src, scan, template[0], j)
                if reason is not None:
                    unresolved.append(
                        Unresolved(
                            file=str(manifest),
                            line=line,
                            expression="`" + template[0] + "`",
                            reason=reason,
                        )
                    )
                    continue
                for path in paths:
                    resolved_count += 1
                    routes.append(
                        Route(
                            path=path,
                            source=module_dir.name,
                            origin="resolved",
                            module_id=module_dir.name,
                            default_enabled=default_enabled,
                        )
                    )
                continue

            tail = src[j : src.find("\n", j) if src.find("\n", j) != -1 else len(src)]
            unresolved.append(
                Unresolved(
                    file=str(manifest),
                    line=line,
                    expression=tail.strip().rstrip(","),
                    reason="a route path that is neither a string literal nor a template this collector can follow",
                )
            )

    return routes, unresolved, manifests_read, resolved_count


# ─── The table ─────────────────────────────────────────────────────────────


def collect(
    app_tsx: Path = APP_TSX,
    modules_dir: Path = MODULES_DIR,
    registry_ts: Path = REGISTRY_TS,
) -> RouteTable:
    """Read both route sources and cross-check them against the module registry."""
    table = RouteTable()

    app_routes, layouts, app_unresolved = read_app_routes(app_tsx)
    table.app_routes = app_routes
    table.layout_routes = layouts
    table.unresolved.extend(app_unresolved)

    module_routes, module_unresolved, manifests_read, resolved = read_module_routes(modules_dir)
    table.module_routes = module_routes
    table.unresolved.extend(module_unresolved)
    table.manifests_read = manifests_read
    table.resolved_count = resolved

    table.registry_modules = read_registry_modules(registry_ts)

    on_disk = set(manifests_read)
    registered = set(table.registry_modules)
    for name in sorted(registered - on_disk):
        table.unresolved.append(
            Unresolved(
                file=str(registry_ts),
                line=1,
                expression=name,
                reason="_registry.ts imports this module's manifest and no manifest file was found for it",
            )
        )
    for name in sorted(on_disk - registered):
        table.unresolved.append(
            Unresolved(
                file=str(modules_dir / name),
                line=1,
                expression=name,
                reason="a manifest exists here but _registry.ts does not import it, so its routes never mount",
            )
        )
    return table


def population_lines(table: RouteTable) -> list[str]:
    """The population, for printing next to any verdict built on this table.

    A green run over 301 routes and a green run over 321 look identical unless
    the count is printed beside them, and the twenty routes that went missing
    were exactly the difference between two such runs.
    """
    modules_with_routes = sorted({r.module_id for r in table.module_routes if r.module_id})
    return [
        f"routes read            : {len(table.routes)}",
        f"  from App.tsx         : {len(table.app_routes)} literal, plus {table.layout_routes} pathless layout route(s)",
        f"  from module manifests: {len(table.module_routes)} across {len(modules_with_routes)} of "
        f"{len(table.manifests_read)} modules "
        f"({len(table.module_routes) - table.resolved_count} literal, {table.resolved_count} resolved from a table)",
        f"  unresolvable         : {len(table.unresolved)}",
    ]


def print_unresolved(table: RouteTable, stream=sys.stderr) -> None:
    # The population goes to stdout and this goes to stderr. Into a pipe, which
    # is what a CI log is, stdout is block buffered and stderr is not, so
    # without this flush the verdict overtakes the numbers it is a verdict
    # about and the reader sees them in the wrong order, or at the bottom.
    sys.stdout.flush()
    print("", file=stream)
    print(
        f"UNRESOLVED: {len(table.unresolved)} route declaration(s) were found and could not be read.",
        file=stream,
    )
    print(
        "A route nobody can enumerate is exactly the one that reaches the public origin as a 404,",
        file=stream,
    )
    print("so this is a failure rather than something to skip:", file=stream)
    for u in table.unresolved:
        print(f"  {u.file}:{u.line}  {u.expression}", file=stream)
        print(f"      {u.reason}", file=stream)
    print("", file=stream)
    print(
        "Either write the path as a literal, or teach scripts/app_routes.py the exact shape it "
        "is written in. Do not widen the resolver to guess.",
        file=stream,
    )


# ─── Self test ─────────────────────────────────────────────────────────────
#
# This collector is a set of patterns over text, and the way a set of patterns
# fails is by matching nothing and reporting a short list in a confident voice.
# That is not a hypothetical failure mode here, it is the one that shipped: the
# two collectors this replaces both returned a shorter list than the truth and
# neither said so. So the fixtures below are built and read on every run, and a
# caller that cannot reproduce them refuses to report a route table at all.

_FIXTURE_APP = """\
import { Routes, Route } from 'react-router-dom';
// A commented-out route: <Route path="/ghost" element={<Ghost />} />
export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/alpha" element={<Alpha />} />
        <Route path="/beta/:betaId" element={<Beta />} />
        <Route path={COMPUTED} element={<Computed />} />
      </Route>
    </Routes>
  );
}
"""

_FIXTURE_LITERAL_MANIFEST = """\
const ITEMS = [
  { slug: 'one', label: 'One' },
  { slug: 'two', label: 'Two' },
];
const built = ITEMS.map((item) => ({
  path: `/${item.slug}`,
  title: 'built',
}));
export const manifest = {
  id: 'litmod',
  defaultEnabled: true,
  routes: [{ path: '/litmod', title: 'lit' }, ...built],
  translations: { en: { 'litmod.path': 'not a route', 'litmod.help': 'set path: /nope' } },
};
"""

_FIXTURE_IMPORTED_MANIFEST = """\
import { ROWS } from './table';
const built = ROWS.map((row) => ({ path: `/${row.slug}-x`, title: row.label }));
export const manifest = {
  id: 'offmod',
  defaultEnabled: false,
  routes: built,
};
"""

_FIXTURE_TABLE = r"""
export interface Row {
  slug: string;
  code: RegExp;
}
// The two `code` values are regex literals, not division, and the scanner has
// to tell the difference. Each carries a brace count and one apostrophe: read
// as code rather than as a regex, that apostrophe opens a string which runs to
// the end of its line and swallows the closing brace of its own entry, so the
// table is read wrong rather than not at all. The real regionalRegistry.ts is
// full of literals shaped like these.
export const ROWS: Row[] = [
  { slug: 'three', label: 'Three', code: /^\d{2}(don't)?$/ },
  { slug: 'four', label: 'Four', code: /^\d{3}(won't)?$/ },
];
"""

_FIXTURE_OPAQUE_MANIFEST = """\
import { ROUTE_PATH } from '@/shared/routes';
export const manifest = {
  id: 'opaque',
  defaultEnabled: true,
  routes: [{ path: ROUTE_PATH, title: 'opaque' }],
};
"""

_FIXTURE_LOST_ARRAY_MANIFEST = """\
const built = NOWHERE.map((row) => ({ path: `/${row.slug}`, title: 'lost' }));
export const manifest = {
  id: 'lostarray',
  defaultEnabled: true,
  routes: built,
};
"""

_FIXTURE_REGISTRY = """\
import { manifest as litmod } from './litmod/manifest';
import { manifest as offmod } from './offmod/manifest';
import { manifest as opaque } from './opaque/manifest';
import { manifest as lostarray } from './lostarray/manifest';
import { manifest as phantom } from './phantom/manifest';
export const MODULE_REGISTRY = [litmod, offmod, opaque, lostarray, phantom];
"""

_FIXTURE_STRAY_MANIFEST = """\
export const manifest = {
  id: 'stray',
  defaultEnabled: true,
  routes: [{ path: '/stray', title: 'stray' }],
};
"""


def _build_fixture(root: Path) -> tuple[Path, Path, Path]:
    app = root / "App.tsx"
    app.write_text(_FIXTURE_APP, encoding="utf-8")
    modules = root / "modules"
    modules.mkdir()
    (modules / "litmod").mkdir()
    (modules / "litmod" / "manifest.ts").write_text(_FIXTURE_LITERAL_MANIFEST, encoding="utf-8")
    (modules / "offmod").mkdir()
    (modules / "offmod" / "manifest.tsx").write_text(_FIXTURE_IMPORTED_MANIFEST, encoding="utf-8")
    (modules / "offmod" / "table.ts").write_text(_FIXTURE_TABLE, encoding="utf-8")
    (modules / "opaque").mkdir()
    (modules / "opaque" / "manifest.ts").write_text(_FIXTURE_OPAQUE_MANIFEST, encoding="utf-8")
    (modules / "lostarray").mkdir()
    (modules / "lostarray" / "manifest.ts").write_text(_FIXTURE_LOST_ARRAY_MANIFEST, encoding="utf-8")
    (modules / "stray").mkdir()
    (modules / "stray" / "manifest.ts").write_text(_FIXTURE_STRAY_MANIFEST, encoding="utf-8")
    registry = modules / "_registry.ts"
    registry.write_text(_FIXTURE_REGISTRY, encoding="utf-8")
    return app, modules, registry


def self_test(stream=sys.stdout) -> int:  # noqa: C901 - a flat list of assertions reads better than a helper per line
    """Prove the collector still resolves, still refuses, and still cross-checks."""
    with tempfile.TemporaryDirectory() as tmp:
        app, modules, registry = _build_fixture(Path(tmp))
        table = collect(app_tsx=app, modules_dir=modules, registry_ts=registry)

        paths = sorted(r.path for r in table.routes)
        expected = sorted(["/alpha", "/beta/:betaId", "/litmod", "/one", "/two", "/three-x", "/four-x", "/stray"])
        if paths != expected:
            print(f"SELF-TEST FAIL: route paths came back as {paths}, expected {expected}.", file=stream)
            return 1
        if table.layout_routes != 1:
            print(f"SELF-TEST FAIL: counted {table.layout_routes} pathless layout routes, expected 1.", file=stream)
            return 1
        if table.resolved_count != 4:
            print(f"SELF-TEST FAIL: resolved {table.resolved_count} paths from tables, expected 4.", file=stream)
            return 1

        # A route the collector cannot read has to be named, never dropped.
        reasons = " | ".join(u.reason for u in table.unresolved)
        expressions = sorted(u.expression for u in table.unresolved)
        if len(table.unresolved) != 5:
            print(f"SELF-TEST FAIL: {len(table.unresolved)} unresolved, expected 5. Got: {expressions}", file=stream)
            return 1
        if not any("expression" in u.reason for u in table.unresolved):
            print(f"SELF-TEST FAIL: a Route with a computed path attribute was not reported. {reasons}", file=stream)
            return 1
        if not any("ROUTE_PATH" in u.expression for u in table.unresolved):
            print(f"SELF-TEST FAIL: an opaque path identifier was not reported. {expressions}", file=stream)
            return 1
        if not any("NOWHERE" in u.reason for u in table.unresolved):
            print(f"SELF-TEST FAIL: a map over an array with no definition was not reported. {reasons}", file=stream)
            return 1
        if not any("phantom" in u.expression for u in table.unresolved):
            print(f"SELF-TEST FAIL: a registered module with no manifest was not reported. {expressions}", file=stream)
            return 1
        if not any("stray" in u.expression for u in table.unresolved):
            print(f"SELF-TEST FAIL: a manifest nobody registers was not reported. {expressions}", file=stream)
            return 1

        # A `path:` inside a comment or a translation value is not a route.
        if any(p in ("/ghost", "/nope", "not a route") for p in paths):
            print(f"SELF-TEST FAIL: a comment or a string was read as a route. {paths}", file=stream)
            return 1

        # The module that ships off still contributes routes, tagged. Only
        # check_case_routes.py drops them; the proxy allowlist needs them.
        off = [r for r in table.module_routes if r.default_enabled is False]
        if sorted(r.path for r in off) != ["/four-x", "/three-x"]:
            print(f"SELF-TEST FAIL: routes of a module that ships off came back as {off}.", file=stream)
            return 1
        on = {r.path: r.default_enabled for r in table.module_routes if r.default_enabled is not False}
        if sorted(on) != ["/litmod", "/one", "/stray", "/two"]:
            print(f"SELF-TEST FAIL: routes of a module that ships on came back as {sorted(on)}.", file=stream)
            return 1
        if any(r.default_enabled is not None for r in table.app_routes):
            print("SELF-TEST FAIL: an App.tsx route was tagged with a module enablement flag.", file=stream)
            return 1

    print("SELF-TEST OK: resolves a table-built path, follows a relative import, refuses four", file=stream)
    print("              shapes it cannot read, ignores comments and strings, and cross-checks", file=stream)
    print("              the manifests on disk against the module registry.", file=stream)
    return 0


def require_self_test(stream=sys.stdout) -> None:
    """Refuse to report a route table the collector cannot prove it still reads."""
    if self_test(stream) != 0:
        print(
            "FAIL: the route collector could not reproduce its own fixtures, so any table it "
            "reports is worthless. Fix scripts/app_routes.py before trusting a green run.",
            file=sys.stderr,
        )
        raise SystemExit(2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print the route table the SPA can serve.")
    parser.add_argument("--json", action="store_true", help="emit the table as JSON")
    parser.add_argument("--self-test", action="store_true", help="prove the collector can fail, then exit")
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()
    if not args.json:
        require_self_test()
        print("")
    else:
        # JSON goes to stdout and has to stay parseable, so the self test reports
        # on stderr in that mode. It still runs, and it still refuses.
        require_self_test(sys.stderr)

    table = collect()

    if args.json:
        payload = {
            "routes": [
                {
                    "path": r.path,
                    "segment": r.segment,
                    "source": r.source,
                    "origin": r.origin,
                    "module_id": r.module_id,
                    "default_enabled": r.default_enabled,
                }
                for r in table.routes
            ],
            "unresolved": [
                {"file": u.file, "line": u.line, "expression": u.expression, "reason": u.reason}
                for u in table.unresolved
            ],
            "app_route_count": len(table.app_routes),
            "module_route_count": len(table.module_routes),
            "resolved_count": table.resolved_count,
            "layout_routes": table.layout_routes,
            "manifests_read": table.manifests_read,
            "registry_modules": table.registry_modules,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 1 if table.unresolved else 0

    for line in population_lines(table):
        print(line)
    print("")
    for route in sorted(table.routes, key=lambda r: (r.source != "App.tsx", r.source, r.path)):
        flag = "" if route.default_enabled is not False else "  (module ships off)"
        print(f"  {route.path:<48} {route.source} [{route.origin}]{flag}")

    if table.unresolved:
        print_unresolved(table)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
