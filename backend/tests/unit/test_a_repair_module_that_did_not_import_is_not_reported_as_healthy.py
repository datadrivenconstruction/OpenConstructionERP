# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A repairs module that will not import must not come out looking like a clean pass.

The defect
----------
``discover_data_repairs`` imports every ``app/modules/*/repairs.py`` and keeps
going when one of them raises, which is right: one broken module must not stop
the application. What was wrong is what happened next. The error went to the log
and nowhere else, so the module registered nothing, the pass had no outcome for
it, and every published field answered the way it answers for a boot with
nothing wrong in it - ``data_repairs_failed: false``,
``data_repair_ledger_failed: false``, status ``healthy``.

That is the shape this codebase keeps being caught by: a signal that cannot tell
"nothing ran" from "everything is fine". Here it was worse than symmetrical,
because the *more* broken module got the *more* reassuring answer. A repair that
raises against the database was reported; a module so broken it never loaded was
not.

How this is measured
--------------------
The probe modules are written under ``tmp_path`` and ``app.modules.__path__`` is
pointed at them, rather than a file being planted in ``backend/app/modules``.
Two reasons, and the second is the one that bites: a probe left behind by a
crashed test is an untracked file that reddens gates for everybody sharing the
tree, and this particular one would go on being discovered by every boot in that
working copy afterwards.

``__path__`` is *replaced* rather than extended, so discovery sees the probe
packages and nothing else. That makes the pass deterministic no matter what has
already been imported: this registry grows as modules are imported, so a check
written over the real one answers differently depending on what ran before it,
which is the neighbouring trap rather than a way out of this one. It also means
no repair is selected, so the runner can be driven end to end without a
database - a factory that is never opened cannot need one.
"""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING

import pytest

import app.modules as modules_pkg
from app.core import data_repairs

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi import FastAPI

#: One package per import failure the discovery loop distinguishes. The first
#: raises ``ModuleNotFoundError`` from inside ``repairs.py``, which the loop has
#: to tell apart from the ordinary case of a module that simply has no
#: ``repairs.py``; the second raises something else entirely at import time.
_MISSING_IMPORT_PKG = "probe_repairs_missing_import"
_RAISES_AT_IMPORT_PKG = "probe_repairs_raises_at_import"


def _write_package(root: Path, name: str, repairs_source: str | None) -> None:
    package = root / name
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    if repairs_source is not None:
        (package / "repairs.py").write_text(repairs_source, encoding="utf-8")


def _point_discovery_at(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``root`` the only place discovery looks, with an empty registry."""
    monkeypatch.setattr(modules_pkg, "__path__", [str(root)])
    monkeypatch.setattr(data_repairs, "_REGISTRY", {})
    monkeypatch.setattr(data_repairs, "_DISCOVERY_FAILURES", [])
    # The finder behind ``app.modules`` caches the directory listing it was
    # first asked about, and these packages were created after that.
    importlib.invalidate_caches()


def _forget_probe_modules() -> None:
    for name in [n for n in sys.modules if n.startswith("app.modules.probe_")]:
        del sys.modules[name]


@pytest.fixture(scope="module")
def application_imports_warmed():
    """Import everything ``create_app`` needs while ``app.modules`` is still whole.

    The fixture below points ``app.modules.__path__`` at a temporary directory,
    and ``create_app`` imports ``app.modules.ai`` on its way to the routers. A
    module already in ``sys.modules`` is served from there and never consults
    ``__path__``; one that is not cannot be found at all. Which of those applies
    depends on what ran earlier in the session, so it is settled here instead of
    being left to test order - the same hazard these tests exist to remove, and
    it would show up as a red run in a full suite and a green one alone.
    """
    from app.main import create_app

    create_app()


@pytest.fixture
def broken_repair_modules(tmp_path, monkeypatch, application_imports_warmed):
    """Two unimportable repairs modules, and nothing else, on the discovery path.

    Yields the dotted names discovery is expected to report.
    """
    _write_package(
        tmp_path,
        _MISSING_IMPORT_PKG,
        "from app.core.a_module_that_does_not_exist import anything  # noqa: F401\n",
    )
    _write_package(
        tmp_path,
        _RAISES_AT_IMPORT_PKG,
        "raise RuntimeError('this module is broken on purpose')\n",
    )
    _point_discovery_at(tmp_path, monkeypatch)
    try:
        yield (
            f"app.modules.{_MISSING_IMPORT_PKG}.repairs",
            f"app.modules.{_RAISES_AT_IMPORT_PKG}.repairs",
        )
    finally:
        _forget_probe_modules()


def _fresh_app() -> FastAPI:
    """An application as it exists before any startup has run."""
    from app.main import create_app

    return create_app()


def _health(app: FastAPI) -> dict:
    from fastapi.testclient import TestClient

    # Not the context-manager form: running the lifespan would replace the
    # verdict under test with one taken from the real tree.
    return TestClient(app).get("/api/health").json()


def _unopenable_factory():
    raise AssertionError("no repair was registered, so the runner must not open a session")


def test_discovery_records_the_modules_it_could_not_import(broken_repair_modules) -> None:
    """Both branches of the loop, because they discriminate differently.

    An ``ImportError`` raised from *inside* ``repairs.py`` arrives as the same
    exception type as "this module has no repairs.py", and only the name on the
    exception separates them. Anything else lands in the general branch. A fix
    that recorded one and not the other would leave half the defect in place.
    """
    repairs = data_repairs.discover_data_repairs()

    assert repairs == (), "the probe path registers nothing, so anything here came from elsewhere"
    reported = {failure.module: failure.error for failure in data_repairs.data_repair_discovery_failures()}
    assert set(reported) == set(broken_repair_modules), (
        f"discovery reported {sorted(reported)} for a path holding only unimportable modules"
    )
    assert "ModuleNotFoundError" in reported[broken_repair_modules[0]]
    assert "RuntimeError" in reported[broken_repair_modules[1]]


def test_a_module_with_no_repairs_file_is_not_a_failure(tmp_path, monkeypatch, application_imports_warmed) -> None:
    """The control the check above needs, or it would fire on the ordinary case.

    Almost no module has a ``repairs.py``. If their absence were recorded the
    field would read ``true`` on every healthy install, which is the same defect
    with the sign flipped and would be switched off within a week.
    """
    _write_package(tmp_path, "probe_module_without_repairs", None)
    _point_discovery_at(tmp_path, monkeypatch)
    try:
        data_repairs.discover_data_repairs()
        assert data_repairs.data_repair_discovery_failures() == ()
    finally:
        _forget_probe_modules()


async def test_a_pass_that_lost_a_module_says_so_instead_of_reporting_a_clean_run(
    broken_repair_modules,
) -> None:
    """The runner's own report, over a discovery where everything failed to load.

    The control is inside the assertions rather than in a test beside them:
    every other number this report carries is the one a flawless pass carries.
    Nothing raised, nothing was attempted, the ledger is intact.
    ``discovery_failures`` is the only field that separates this from a boot
    where all was well, and before it existed there was no separation at all.
    """
    report = await data_repairs.run_data_repairs(_unopenable_factory, app_version="test")

    assert report.outcomes == ()
    assert report.attempted == 0
    assert report.failed == ()
    assert report.ledger_written is True
    assert {failure.module for failure in report.discovery_failures} == set(broken_repair_modules)


async def test_the_health_verdict_degrades_on_a_module_that_never_loaded(broken_repair_modules) -> None:
    """End to end through the only writer of the field, into the payload a monitor reads."""
    from app.main import publish_data_repair_verdict

    report = await data_repairs.run_data_repairs(_unopenable_factory, app_version="test")
    app = _fresh_app()
    publish_data_repair_verdict(app, report)

    payload = _health(app)

    assert payload["data_repairs_failed"] is True
    assert payload["status"] == "degraded"
    assert set(app.state.data_repairs_failed_ids) == {f"<{module} did not import>" for module in broken_repair_modules}


async def test_the_module_names_are_not_published_to_an_anonymous_caller(broken_repair_modules) -> None:
    """Same rule as the repair ids beside them: the verdict travels, the detail does not.

    Module paths name internal structure and the endpoint is unauthenticated.
    They stay on ``app.state`` and in the boot log, where the operator is.
    """
    from app.main import publish_data_repair_verdict

    report = await data_repairs.run_data_repairs(_unopenable_factory, app_version="test")
    app = _fresh_app()
    publish_data_repair_verdict(app, report)

    assert _MISSING_IMPORT_PKG not in str(_health(app))


def test_a_pass_with_nothing_broken_still_reports_false() -> None:
    """The other direction, so ``true`` keeps meaning something.

    A field that reads ``true`` whatever happened is as useless as one that
    reads ``false``. This goes through the same writer with the same report
    type, and only the discovery failures taken out.
    """
    from app.main import publish_data_repair_verdict

    app = _fresh_app()
    publish_data_repair_verdict(
        app,
        data_repairs.DataRepairReport(
            outcomes=(data_repairs.DataRepairOutcome(repair_id="example", status="clean", rows_changed=0),),
            ledger_written=True,
        ),
    )

    assert _health(app)["data_repairs_failed"] is False
    assert app.state.data_repairs_failed_ids == ()
