# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""``/api/health`` counts the modules that loaded, and says what it counted.

``modules_loaded`` was ``len(module_loader.list_modules())``, and that list is
built by iterating ``_manifests`` - every manifest that parsed, whether the
module behind it is loaded, disabled, or neither. So the field named "loaded"
answered with the discovered figure. Measured on a registry holding 191
manifests with nothing loaded, it said 191.

The name is not the only thing wrong with one number here. Discovered, enabled
and loaded are three quantities that move independently, and a reader given
their sum under one label cannot tell which of them dropped: a module the
operator switched off and a module that failed to import both lower it by one,
and only the second is a fault. All three are published now, and each row of
``list_modules`` carries the ``loaded`` and ``enabled`` flags they are counted
from.

The fault is computed per row - ``enabled and not loaded`` - and never as
``modules_enabled - modules_loaded``. The two are different claims.
``resolve_order`` recurses into a module's dependencies without asking whether
the dependency is enabled, so a disabled module pulled in by an enabled one
comes back ``loaded: True, enabled: False``; one row of that shape cancels one
row of the shape this file is about, and the subtraction reads zero across an
install that has genuinely lost a module.

Enabled-and-not-loaded is reachable in a shipped install, and not at boot:
``load_all`` re-raises, so a module that cannot be imported at startup takes the
whole process down and never answers a health probe at all. The runtime path is
``enable_module``, which sets ``manifest.enabled = True`` and discards the name
from ``_disabled`` *before* it calls ``_load_module``. When that import raises -
the case ``tests/pg/test_module_builder_install.py`` describes for a module
whose files were removed under a running server - the registry is left holding a
module that is enabled and is not there, until somebody restarts. Every endpoint
it owns answers 404 for as long as that lasts.

That state degrades the status. What a reader does with the answer is the whole
argument: told ``healthy``, a person looking for a feature that is missing
concludes their edition does not include it and stops, which is the one wrong
conclusion available; told ``degraded`` beside ``modules_enabled: 190,
modules_loaded: 189``, they restart or reinstall, which is the fix. Degrading
here is cheap - the desktop launcher deliberately stopped testing bare
``status == "degraded"`` for attach (it turns on version equality and
``blocking_fault``), and this handler returns 200 whatever the status says, so
container healthchecks keyed on the HTTP code do not move.

It is narrow on purpose, for the reason the stale alembic stamp is published as
a fact and degrades nothing: an aggregate with a permanently active cause has
stopped being a signal. A disabled module is not a fault, and neither is a
smaller module count than the last release - nothing at runtime knows what the
last release held. Only the contradiction between what is enabled and what is
loaded is, and no correct install produces one.

What this does NOT close: a manifest that fails to import is swallowed by
``_discover_in``, so the module leaves all three counts at once and no runtime
baseline exists to notice. That needs a fourth number - the directories holding
a ``manifest.py``, counted once at boot - and is not in this change.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from fastapi import FastAPI


@pytest.fixture(autouse=True)
def _pin_the_frontend_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Leave ``status`` a function of the module counts, which is what this file is about.

    ``/api/health`` folds a frontend-build probe into the same ``status`` field
    every test here reads, and that probe degrades whenever no ``index.html`` is
    on disk. The backend CI lane creates ``frontend/dist`` holding nothing but a
    ``.gitkeep``, so the probe answers False for the whole lane, and it would
    break this file in both directions at once: the healthy cases could not pass
    there whatever the registry held, and the degraded case would pass there on
    a verdict the field under test took no part in.
    """
    from app import cli_static

    monkeypatch.setattr(cli_static, "mounted_frontend_intact", lambda: True)


def _row(name: str, *, loaded: bool, enabled: bool) -> dict[str, Any]:
    """One entry shaped as ``ModuleLoader.list_modules`` builds it.

    Only the two flags are read by the endpoint; the rest are carried so the
    fixture cannot pass by being smaller than the real thing.
    """
    return {
        "name": name,
        "version": "1.0.0",
        "display_name": name,
        "display_name_i18n": {},
        "description": "",
        "author": "",
        "category": "core",
        "depends": [],
        "optional_depends": [],
        "has_router": loaded,
        "loaded": loaded,
        "enabled": enabled,
        "is_core": True,
    }


def _registry(monkeypatch: pytest.MonkeyPatch, rows: list[dict[str, Any]]) -> None:
    """Answer ``list_modules`` with ``rows``.

    Patched on the singleton rather than on the name ``main`` imported, so it
    holds however the endpoint reaches the loader. The real registry is a
    process-wide object that grows as modules are imported, so no count taken
    from it inside a suite would mean anything; every number in this file comes
    from a population written down two lines above the assertion that reads it.
    """
    from app.core.module_loader import module_loader

    monkeypatch.setattr(module_loader, "list_modules", lambda: list(rows))


def _fresh_app() -> FastAPI:
    """An application as it exists before any startup has run."""
    from app.main import create_app

    return create_app()


def _health(app: FastAPI) -> dict:
    from fastapi.testclient import TestClient

    # Deliberately not the context-manager form, which would run the lifespan
    # and load the real modules over the registry under test.
    return TestClient(app).get("/api/health").json()


def test_the_count_names_the_loaded_modules_not_the_discovered_ones(monkeypatch: pytest.MonkeyPatch) -> None:
    """The measured defect. Population: 3 manifests, of which 2 are loaded.

    Before the change this asserted 3, because the field was the length of the
    manifest list.
    """
    _registry(
        monkeypatch,
        [
            _row("oe_alpha", loaded=True, enabled=True),
            _row("oe_beta", loaded=True, enabled=True),
            _row("oe_gamma", loaded=False, enabled=False),
        ],
    )

    payload = _health(_fresh_app())

    assert payload["modules_loaded"] == 2, "the field named for the loaded modules counted the discovered ones"
    assert payload["modules_discovered"] == 3
    assert payload["modules_enabled"] == 2


def test_an_enabled_module_that_did_not_load_degrades_the_status(monkeypatch: pytest.MonkeyPatch) -> None:
    """The operator asked for it and it is not there. Population: 2 manifests, 1 loaded.

    Reachable through ``enable_module``, which marks the manifest enabled before
    it imports the package and leaves it enabled when that import raises.
    """
    _registry(
        monkeypatch,
        [
            _row("oe_alpha", loaded=True, enabled=True),
            _row("oe_beta", loaded=False, enabled=True),
        ],
    )

    payload = _health(_fresh_app())

    assert payload["modules_enabled"] == 2
    assert payload["modules_loaded"] == 1
    assert payload["status"] == "degraded", "a module that is enabled and absent is not a healthy install"


def test_a_module_the_operator_switched_off_is_not_a_fault(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disabling is a choice, not a loss. Population: 2 manifests, 1 loaded.

    This is what keeps the signal worth reading. A condition that lights on
    every install carrying a disabled module would be permanently active, and
    an aggregate with a permanently active cause cannot report anything else.
    """
    _registry(
        monkeypatch,
        [
            _row("oe_alpha", loaded=True, enabled=True),
            _row("oe_beta", loaded=False, enabled=False),
        ],
    )

    payload = _health(_fresh_app())

    assert payload["modules_discovered"] == 2
    assert payload["modules_enabled"] == 1
    assert payload["modules_loaded"] == 1
    # Named so a red run says which other probe moved instead of pointing here.
    assert payload["frontend_dist_present"] is True
    assert payload["database"] == "ok"
    assert payload["status"] == "healthy"


def test_a_loaded_disabled_dependency_does_not_cancel_a_missing_module(monkeypatch: pytest.MonkeyPatch) -> None:
    """Why the verdict is per row and never ``modules_enabled - modules_loaded``.

    ``resolve_order`` visits a module's dependencies without checking whether
    they are enabled, so a disabled dependency of an enabled module is loaded
    anyway and comes back ``loaded: True, enabled: False``. Population here: 3
    manifests, 2 loaded, 2 enabled - the two aggregates are equal, and one of
    the three modules is enabled and missing.
    """
    _registry(
        monkeypatch,
        [
            _row("oe_alpha", loaded=True, enabled=True),
            _row("oe_dependency", loaded=True, enabled=False),
            _row("oe_beta", loaded=False, enabled=True),
        ],
    )

    payload = _health(_fresh_app())

    assert payload["modules_enabled"] == payload["modules_loaded"] == 2, "the arithmetic this test exists to reject"
    assert payload["status"] == "degraded", "a subtraction read this install as complete"


def test_the_three_counts_are_always_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """A reader has to tell "none" from "this backend has no such field".

    Both are falsy in Python and in most alerting DSLs, so all three keys are
    emitted unconditionally - the same reason the fields beside them are.
    """
    _registry(monkeypatch, [])

    payload = _health(_fresh_app())

    assert payload["modules_discovered"] == 0
    assert payload["modules_enabled"] == 0
    assert payload["modules_loaded"] == 0


def test_which_module_is_missing_is_not_published_to_an_anonymous_caller(monkeypatch: pytest.MonkeyPatch) -> None:
    """The endpoint is unauthenticated, so it carries counts and not names.

    Same rule that keeps ``schema_heal_error`` and the failed repair ids off
    this payload: a module name maps the deployment, and belongs in the boot
    log where the operator of that machine is.
    """
    _registry(
        monkeypatch,
        [
            _row("oe_alpha", loaded=True, enabled=True),
            _row("oe_a_module_nobody_should_learn_about", loaded=False, enabled=True),
        ],
    )

    payload = _health(_fresh_app())

    assert payload["status"] == "degraded"
    assert "oe_a_module_nobody_should_learn_about" not in str(payload)


def test_the_registry_lists_a_manifest_whose_module_never_loaded() -> None:
    """The property the endpoint was reading, held against the real class.

    Every test above answers ``list_modules`` with a fixture, so they would all
    pass against a registry that never behaved this way. This one builds its own
    ``ModuleLoader`` - not the process-wide singleton, whose contents depend on
    what the suite has imported - puts one manifest in it and loads nothing.
    Population: 1 manifest, 0 loaded, and the list is 1 long.
    """
    from app.core.module_loader import ModuleLoader, ModuleManifest

    loader = ModuleLoader()
    loader._manifests["oe_alpha"] = ModuleManifest(name="oe_alpha", version="1.0.0", display_name="Alpha")

    rows = loader.list_modules()

    assert len(rows) == 1, "the list is the discovered manifests"
    assert rows[0]["loaded"] is False, "and it lists one that never loaded"
