#!/usr/bin/env python3
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Permission guard: a route may not ask for a permission nobody registers.

``RequirePermission.__call__`` checks the key against the caller's own
permission list, then falls back to ``permission_registry.role_has_permission``.
That returns **False** for a key nothing registered, logging "Unknown permission
checked". Admin short-circuits above both checks.

So a route asking for an unregistered key is **admin-only in production**, and
no test notices, because the fixtures authenticate as an admin. The failure
needs a non-admin user to appear at all, which is why this has to be a static
check rather than a test.

The second cost is quieter and does not need a non-admin user. The admin
permission matrix calls ``permission_registry.set_min_role(key, role)``, which
raises on a key it has never seen, so a route gated this way can never be
delegated to a lower role no matter what the matrix says.

Measured 2026-08-05 across 184 module directories and 171 router files: 715
distinct keys requested against 760 registered, and exactly one key was
missing, the bare literal ``"admin"``, asked for by three routes
(``core/module_router.py`` twice and ``i18n_foundation/router.py`` once) while
``system.modules.enable`` and ``system.modules.disable`` sat registered and
unused beside them. Whoever wrote those three probably wanted ``RequireRole``,
which is a different class with a similar name that checks the role hierarchy
directly and never touches the registry. This file starts clean, so any failure
it reports is new.

What it reads:

  - Requested: every literal argument to ``RequirePermission(...)`` and
    ``RequirePermissionOrApiKey(...)``, and every literal ``read_permission=``
    / ``write_permission=`` handed to the ``create_vector_routes`` factory.
  - Registered: every literal key inside a
    ``permission_registry.register_module_permissions(...)`` call, plus the
    core ``register_core_permissions`` block.

Docstrings are stripped before scanning. Several ``permissions.py`` files quote
a ``RequirePermission("module.thing")``-shaped example in their own docstring to
explain why the file exists, and counting prose as a call site would report four
modules that are in fact correct.

Deliberately not covered: keys built at run time, and the ad-hoc in-handler
``role_has_permission`` calls in a handful of modules. Both are reachable only
by reading the value, not the source, so a clean run here says nothing about
them.

One known imprecision, in the safe direction. The registered set is read from
every ``"key": Role.X`` pair in a file that registers, rather than by resolving
the constant a registrar was handed. A file that both registers something and
holds a second, unregistered dict of keys mapped to roles would have that
second dict counted as registered, so this check can miss a gap of that exact
shape. The alternative, reading only the call's own brackets, misreports
eleven modules that pass a constant, and 84 false failures would make the gate
worthless. Erring toward a missed gap rather than toward an outage is the right
side to err on for a rule that blocks a merge.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_APP = REPO_ROOT / "backend" / "app"

# One literal string argument, in either quote style, as the first argument.
REQUESTED_RE = re.compile(r"""Require(?:Permission|PermissionOrApiKey)\(\s*(["'])([^"']+)\1""")
# The vector-route factory takes its two gates as keyword arguments.
VECTOR_RE = re.compile(r"""(?:read_permission|write_permission)\s*=\s*(["'])([^"']+)\1""")
# Keys inside a registration dict. Scanned within the call's bracket span so a
# neighbouring dict of something else cannot contribute.
REGISTER_CALL_RE = re.compile(r"register_(?:module|core)_permissions\s*\(")
DICT_KEY_RE = re.compile(r"""(["'])([A-Za-z][\w.]*)\1\s*:""")
# A key mapped to a Role. Anchoring on the value is what makes it safe to scan a
# whole file rather than only the call: eleven modules pass a module-level
# constant to the registrar instead of an inline dict literal
# (``register_module_permissions("service", SERVICE_PERMISSIONS)``), and reading
# only the call's own brackets finds no keys at all there. Reading the file and
# requiring ``Role.`` on the right-hand side picks the constant up without
# admitting unrelated dictionaries.
ROLE_MAPPING_RE = re.compile(r"""(["'])([A-Za-z][\w.]*)\1\s*:\s*Role\.""")
DOCSTRING_RE = re.compile(r'"""(?:.|\n)*?"""|\'\'\'(?:.|\n)*?\'\'\'')


def strip_docstrings(source: str) -> str:
    """Blank out triple-quoted blocks, preserving line count for reporting."""
    return DOCSTRING_RE.sub(lambda m: "\n" * m.group(0).count("\n"), source)


def bracket_span(source: str, open_index: int) -> str:
    """The text between a call's opening paren and its match.

    A newline-anchored regex silently drops single-line registration calls, so
    the span is found by counting brackets instead.
    """
    depth = 0
    for i in range(open_index, len(source)):
        char = source[i]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return source[open_index + 1 : i]
    return ""


def scan() -> tuple[dict[str, list[str]], set[str], int]:
    """Return (requested key -> where, registered keys, files scanned)."""
    requested: dict[str, list[str]] = {}
    registered: set[str] = set()
    files = 0

    for path in sorted(BACKEND_APP.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        files += 1
        raw = path.read_text(encoding="utf-8", errors="replace")
        source = strip_docstrings(raw)
        rel = path.relative_to(REPO_ROOT).as_posix()

        for pattern in (REQUESTED_RE, VECTOR_RE):
            for match in pattern.finditer(source):
                key = match.group(2)
                line = source.count("\n", 0, match.start()) + 1
                requested.setdefault(key, []).append(f"{rel}:{line}")

        registers_here = False
        for match in REGISTER_CALL_RE.finditer(source):
            registers_here = True
            span = bracket_span(source, match.end() - 1)
            registered.update(m.group(2) for m in DICT_KEY_RE.finditer(span))
        if registers_here:
            registered.update(m.group(2) for m in ROLE_MAPPING_RE.finditer(source))

    return requested, registered, files


def main() -> int:
    if not BACKEND_APP.is_dir():
        print(f"ERROR: {BACKEND_APP} not found", file=sys.stderr)
        return 1

    requested, registered, files = scan()

    # An empty read is a broken scan, not a clean tree.
    if not requested:
        print("ERROR: no permission requests found, the scan is broken", file=sys.stderr)
        return 1
    if not registered:
        print("ERROR: no registrations found, the scan is broken", file=sys.stderr)
        return 1

    missing = {key: where for key, where in requested.items() if key not in registered}

    if missing:
        print(
            f"Routes asking for permissions nobody registers: {len(missing)}",
            file=sys.stderr,
        )
        for key in sorted(missing):
            print(f"  {key}", file=sys.stderr)
            for where in sorted(set(missing[key])):
                print(f"      {where}", file=sys.stderr)
        print(
            "\nAn unregistered key resolves to False for every role, and admin "
            "short-circuits above the check, so these routes are admin-only in "
            "production and every admin-authenticated test still passes. Either "
            "register the key in the module's permissions.py, or ask for the "
            "key that already exists. If the route is genuinely meant to be "
            "admin-only and undelegatable, use RequireRole, which checks the "
            "role hierarchy and never consults the registry.",
            file=sys.stderr,
        )
        return 1

    print(
        f"permission registration OK: {len(requested)} distinct keys requested "
        f"across {files} files, all registered ({len(registered)} registered in total)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
