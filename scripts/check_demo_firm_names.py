#!/usr/bin/env python3
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Fail if the demo seed pool can still produce a real firm name.

The demo data ships with invented contractors, clients and consultants. Real
firms had leaked into it, were removed, and the removal is held by
``backend/tests/unit/test_demo_seed_has_no_real_firm_names.py``. That test reads
source *text*, which is the right surface for a literal but the wrong one for a
name that is assembled at runtime: ``app/modules/subcontractors/seed.py`` builds
a ``legal_name`` with an f-string, and no text scan can evaluate it.

This check reads the pool instead. It loads the demo template registry the
installer actually consumes and walks every string in it, so what is tested is
the value that reaches the database rather than the expression that produces it.

The denylist is not duplicated here. Both the entries and the matching rules are
imported from the test module above, so the two cannot drift apart, and adding a
name in one place arms both. Like that module, it stores only SHA-256 hashes of
lowercased names, so this file puts no firm name in the repo, and a match is
reported in a masked form.

No database is involved. Importing the registry pulls in the ORM, which builds
an engine at import time, so a throwaway PostgreSQL URL is set below. SQLAlchemy
does not dial an engine until it is used and nothing here uses it, so the URL
points at a port nothing listens on rather than at anything real.

Three ways this check can be green while the pool is dirty, each of which is
therefore a failure and not a pass:

* No template loads. A comparison over zero items always succeeds.
* A pack file exists but registered no template. The loader in
  ``app/core/demo_packs/__init__.py`` deliberately swallows a broken pack so it
  cannot break boot, which means a pack can drop out of the pool in silence and
  take its names with it.
* The text surfaces come back empty, which means the glob stopped matching.

Exit codes:
    0  no denylisted name is reachable from the pool or present in the sources
    1  at least one is, or the pool could not be measured

Usage::

    .venv-run/Scripts/python.exe scripts/check_demo_firm_names.py
    .venv-run/Scripts/python.exe scripts/check_demo_firm_names.py --verbose
"""

from __future__ import annotations

import dataclasses
import importlib.util
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[1]
_BACKEND = _REPO / "backend"
_TEST = _BACKEND / "tests" / "unit" / "test_demo_seed_has_no_real_firm_names.py"

# A pack that fails to import is skipped with a warning, so fewer templates than
# pack files means names went unscanned. Floors guard the denominator.
_MIN_TEMPLATES = 25
_MIN_POOL_STRINGS = 500
_MIN_PLACEHOLDER_LINES = 100


def _load_denylist() -> Any:
    """Import the test module by path and hand back its denylist and matcher."""
    spec = importlib.util.spec_from_file_location("_oe_firm_denylist", _TEST)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"cannot load the denylist from {_TEST}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _walk(node: Any, trail: str) -> Iterator[tuple[str, str]]:
    """Yield ``(trail, value)`` for every string reachable from ``node``."""
    if isinstance(node, str):
        yield trail, node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from _walk(value, f"{trail}.{key}")
    elif isinstance(node, list | tuple):
        for index, value in enumerate(node):
            yield from _walk(value, f"{trail}[{index}]")
    elif dataclasses.is_dataclass(node) and not isinstance(node, type):
        for field in dataclasses.fields(node):
            yield from _walk(getattr(node, field.name), f"{trail}.{field.name}")


def _load_pool() -> tuple[dict[str, Any], list[Any], int]:
    """Load the demo template registry without touching a database."""
    os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://oe:oe@127.0.0.1:1/oe_firm_name_check")
    sys.path.insert(0, str(_BACKEND))
    from app.core import demo_packs
    from app.core.demo_projects import DEMO_TEMPLATES

    pack_files = [
        path
        for path in sorted((_BACKEND / "app" / "core" / "demo_packs").glob("*.py"))
        if path.name != "__init__.py" and not path.name.startswith("_")
    ]
    return DEMO_TEMPLATES, demo_packs.PACK_TEMPLATES, len(pack_files)


def main(argv: list[str]) -> int:
    verbose = "--verbose" in argv
    deny = _load_denylist()

    try:
        templates, pack_templates, pack_files = _load_pool()
    except Exception as exc:  # pragma: no cover - surfaced, never swallowed
        print(f"[FAIL] could not load the demo template registry: {exc!r}")
        return 1

    # --- the pool, as the installer receives it ---------------------------
    pool: list[tuple[str, str]] = []
    for demo_id, template in sorted(templates.items()):
        pool.extend(_walk(template, demo_id))

    hits: list[str] = []
    for trail, value in pool:
        for hit in deny._scan(trail, 0, value):
            hits.append(f"  pool  {hit.replace(':0:', ' ->', 1)}")

    # --- the text surfaces, for what only materialises against a database --
    seed_files = deny._seed_sources()
    seed_lines = 0
    for path in seed_files:
        rel = path.relative_to(_BACKEND).as_posix()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            seed_lines += 1
            hits.extend(f"  text  {hit}" for hit in deny._scan(rel, number, line))

    placeholders = deny._placeholder_lines()
    for rel, number, line in placeholders:
        hits.extend(f"  text  {hit}" for hit in deny._scan(rel, number, line))

    entries = len(deny._DENY_TOKENS) + len(deny._DENY_PHRASES) + len(deny._DENY_SUBSTRINGS)
    print(
        f"denylist {entries} entries | "
        f"pool {len(pool)} strings from {len(templates)} templates | "
        f"sources {seed_lines} lines in {len(seed_files)} files | "
        f"placeholders {len(placeholders)} lines"
    )
    if verbose:
        for demo_id in sorted(templates):
            print(f"  template {demo_id}")

    # --- the denominator, so an empty scan cannot read as a clean one ------
    if len(pack_templates) != pack_files:
        print(
            f"[FAIL] {pack_files} demo pack file(s) on disk but {len(pack_templates)} registered. "
            "The loader skips a pack that raises, so its names are in the product and out of this scan. "
            "Run the import by hand to see the traceback."
        )
        return 1
    if len(templates) < _MIN_TEMPLATES or len(pool) < _MIN_POOL_STRINGS:
        print(
            f"[FAIL] the pool is too small to be believed: {len(templates)} templates, {len(pool)} strings. "
            "A scan over nothing passes, so this is a failure rather than a clean run."
        )
        return 1
    if not seed_files or len(placeholders) < _MIN_PLACEHOLDER_LINES:
        print(
            f"[FAIL] a text surface came back empty: {len(seed_files)} seed file(s), "
            f"{len(placeholders)} placeholder line(s). The glob has stopped matching."
        )
        return 1

    if hits:
        print(f"\n[FAIL] {len(hits)} denylisted firm name(s) still reachable:")
        for hit in sorted(set(hits)):
            print(hit)
        print(
            "\nReplace the name with an invented one. Check the replacement against a "
            "company register before using it, and add the rejected candidate to the "
            "denylist in the test module."
        )
        return 1

    print("[OK] no denylisted firm name is reachable from the demo seed pool")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
