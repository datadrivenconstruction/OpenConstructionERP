# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
#
# Regression guard for a module that ships a REST surface nobody can reach.
#
# Background: the portfolio module shipped a full router, service, models and
# Alembic revisions, but no ``manifest.py``. ``ModuleLoader.discover()`` skips
# any package without one, so the router never mounted and all ten
# ``/api/v1/portfolio/`` endpoints answered 404, while the frontend page kept
# calling them. Nothing failed loudly: the tables were still created, because
# schema provisioning scans the package directory rather than reading the
# manifest list, so the only symptom was a page that stayed empty.
#
# The rule this pins is narrow on purpose. A package with no ``router.py`` is a
# shared helper library, not a module, and correctly has no manifest (einvoice,
# measurement and price_breakdown are all imported directly by finance, boq and
# postcalc). What must never happen again is a package that DEFINES routes and
# is nevertheless invisible to the loader.

from __future__ import annotations

import re
from pathlib import Path

MODULES_DIR = Path(__file__).resolve().parents[2] / "app" / "modules"

# Matches ``@router.get(``, ``@router.post(`` and friends at any indentation.
_ROUTE_DECORATOR = re.compile(r"@\w+\.(get|post|put|patch|delete|head|options)\s*\(")


def _packages_defining_routes() -> list[Path]:
    """Every module package whose ``router.py`` declares at least one route."""
    found: list[Path] = []
    for module_dir in sorted(MODULES_DIR.iterdir()):
        if not module_dir.is_dir() or module_dir.name.startswith("__"):
            continue
        router_file = module_dir / "router.py"
        if not router_file.exists():
            continue
        if _ROUTE_DECORATOR.search(router_file.read_text(encoding="utf-8")):
            found.append(module_dir)
    return found


def test_every_module_with_routes_has_a_manifest() -> None:
    """A package that defines routes must be discoverable, or its API is dead."""
    unreachable = [d.name for d in _packages_defining_routes() if not (d / "manifest.py").exists()]

    assert not unreachable, (
        "these packages define HTTP routes but have no manifest.py, so the "
        "module loader never mounts them and every one of their endpoints "
        f"returns 404: {sorted(unreachable)}"
    )


def test_the_guard_actually_finds_routed_packages() -> None:
    """Guard the guard: a passing result must not come from an empty scan."""
    routed = _packages_defining_routes()

    assert len(routed) > 100, (
        "expected the sweep to find routed packages across the module tree; "
        f"found only {len(routed)}, so the detection above is broken and the "
        "test above would pass vacuously"
    )
    assert any(d.name == "portfolio" for d in routed), "portfolio defines routes and must be covered by this guard"
