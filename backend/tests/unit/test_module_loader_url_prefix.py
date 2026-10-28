# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
#
# Regression test for the module-loader URL-prefix derivation.
#
# Background: the recently-added 18 modules were shipped with frontend
# api.ts files that hit hyphenated paths like ``/api/v1/bi-dashboards``
# and ``/api/v1/hse-advanced``. The loader, however, derived the URL
# prefix straight from the Python package directory name (which uses
# underscores), so the frontend got a 404 on every request and the
# pages like /bi-dashboards and /hse-advanced were reported as
# completely broken.
#
# The fix mounts the router on the kebab-cased path AND mirrors it under
# the legacy underscore form. This test pins exactly that: for each real
# module it asserts the loader calls ``include_router`` with BOTH the
# kebab-case prefix and the underscore mirror.
#
# Why we assert on the prefix the loader passes to ``include_router``
# rather than on the routes that end up mounted: the route-transfer step
# (``app.include_router`` iterating ``router.routes`` and re-adding each
# one) hinges on FastAPI's ``isinstance(route, APIRoute)`` check, which
# silently drops every route when the route objects and the app come from
# different copies of the ``fastapi.routing`` module. That class-identity
# split can happen in a worker that has already imported a large slice of
# the app (e.g. one ``pytest-split`` shard that pulled in many modules),
# and it is unrelated to the URL derivation this test exists to guard. The
# prefix passed to ``include_router`` is the actual regression surface, so
# we assert on that and stay immune to the import-identity quirk. Each test
# runs the real loader against the real module in a fresh interpreter.

from __future__ import annotations

import json
import subprocess
import sys

# Program run in a fresh interpreter. It loads ONE real module through the real
# ModuleLoader (seeding just that module's manifest, so it does not mass-import
# every manifest) and records the prefixes the loader hands to
# ``include_router``. It only imports and mounts routes (no DB connection), so it
# does not need the test database.
_LOADER_PROBE = """\
import sys, json, traceback, importlib

module_name = sys.argv[1]
dir_name = module_name[3:] if module_name.startswith("oe_") else module_name
diag = {"py": sys.version.split()[0]}
try:
    import asyncio
    from fastapi import FastAPI
    from app.core.module_loader import ModuleLoader

    manifest = importlib.import_module("app.modules." + dir_name + ".manifest").manifest
    loader = ModuleLoader()
    loader._manifests[module_name] = manifest

    app = FastAPI()
    prefixes = []
    _orig = app.include_router

    def _spy(router, **kwargs):
        prefixes.append(kwargs.get("prefix"))
        return _orig(router, **kwargs)

    app.include_router = _spy
    asyncio.run(loader._load_module(module_name, app))
    diag["include_prefixes"] = prefixes
    diag["mounted_count"] = len(app.routes)
except Exception as exc:
    diag["error"] = repr(exc)
    diag["tb"] = traceback.format_exc()[-1500:]
sys.stdout.write("OE_DIAG=" + json.dumps(diag) + "\\n")
"""


def _include_prefixes(module_name: str) -> tuple[list, dict]:
    """Run the real loader for one module in a fresh interpreter.

    Returns ``(prefixes, diag)`` where ``prefixes`` is the list of prefix
    arguments the loader passed to ``include_router`` for that module.
    """
    proc = subprocess.run(
        [sys.executable, "-c", _LOADER_PROBE, module_name],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    marker = "OE_DIAG="
    line = next((ln for ln in proc.stdout.splitlines() if ln.startswith(marker)), None)
    assert line is not None, (
        f"loader probe for {module_name} produced no diagnostics (exit {proc.returncode}).\n"
        f"stdout tail:\n{proc.stdout[-2000:]}\nstderr tail:\n{proc.stderr[-2500:]}"
    )
    diag = json.loads(line[len(marker) :])
    return diag.get("include_prefixes") or [], diag


def test_bi_dashboards_mounted_on_kebab_case() -> None:
    """``bi_dashboards`` package must mount under ``/api/v1/bi-dashboards``."""
    prefixes, diag = _include_prefixes("oe_bi_dashboards")
    assert "/api/v1/bi-dashboards" in prefixes, (
        "BI dashboards router must mount under /api/v1/bi-dashboards (frontend "
        f"api.ts uses this kebab-case prefix). diag={json.dumps(diag)[:3000]}"
    )


def test_bi_dashboards_legacy_underscore_mirror() -> None:
    """The underscore form is mirrored for callers that haven't migrated."""
    prefixes, diag = _include_prefixes("oe_bi_dashboards")
    assert "/api/v1/bi_dashboards" in prefixes, (
        "Legacy /api/v1/bi_dashboards mirror is missing - third-party callers "
        f"that have not migrated to the kebab-case URL would 404. diag={json.dumps(diag)[:3000]}"
    )


def test_hse_advanced_mounted_on_kebab_case() -> None:
    """``hse_advanced`` package must mount under ``/api/v1/hse-advanced``."""
    prefixes, diag = _include_prefixes("oe_hse_advanced")
    assert "/api/v1/hse-advanced" in prefixes, (
        f"hse-advanced must mount under /api/v1/hse-advanced. diag={json.dumps(diag)[:3000]}"
    )
    assert "/api/v1/hse_advanced" in prefixes, (
        f"hse_advanced underscore mirror is missing. diag={json.dumps(diag)[:3000]}"
    )


def test_schedule_advanced_mounted_on_kebab_case() -> None:
    """``schedule_advanced`` package must mount under ``/api/v1/schedule-advanced``.

    The user's "create doesn't work" on /schedule-advanced was caused by this
    URL mismatch.
    """
    prefixes, diag = _include_prefixes("oe_schedule_advanced")
    assert "/api/v1/schedule-advanced" in prefixes, (
        f"schedule-advanced must mount under /api/v1/schedule-advanced. diag={json.dumps(diag)[:3000]}"
    )
    assert "/api/v1/schedule_advanced" in prefixes, (
        f"schedule_advanced underscore mirror is missing. diag={json.dumps(diag)[:3000]}"
    )
