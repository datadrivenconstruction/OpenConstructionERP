# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The version the CLI prints is the version the server reports.

``_resolve_version`` used to ask ``importlib.metadata`` first, which returns
whatever distribution is installed in the environment. On a source checkout
that had ever seen ``pip install openconstructionerp``, that is not the code
being executed: the CLI printed v15.2.0 for a tree at 15.9.1 while
``/api/health`` on the same interpreter correctly said 15.9.1, and there was no
test to notice. ``config._detect_version`` exists precisely to prefer the
pyproject beside the running source, and its own docstring says why: otherwise
you cannot tell, in a QA session, whether a just-edited file is serving
requests.

None of this is a fact about the environment these tests happen to run in, so
the checks below construct the disagreement rather than waiting for one.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.cli import _resolve_version
from app.config import Settings, _detect_version, _read_pyproject_version

REPO_ROOT = Path(__file__).resolve().parents[3]
PYPROJECT = REPO_ROOT / "backend" / "pyproject.toml"


def test_the_cli_agrees_with_what_health_would_report() -> None:
    settings_version = str(Settings.model_fields["app_version"].default_factory())  # type: ignore[misc]
    assert _resolve_version() == settings_version


def test_running_from_the_tree_the_version_is_the_pyproject_one() -> None:
    """The source tree wins. This is the assertion the old ordering failed."""
    declared = re.search(r'^version\s*=\s*"([^"]+)"', PYPROJECT.read_text(encoding="utf-8"), re.M)
    assert declared, "backend/pyproject.toml has no version line where this test looks for it"
    assert _read_pyproject_version() == declared.group(1)
    assert _detect_version() == declared.group(1)
    assert _resolve_version() == declared.group(1)


def test_installed_metadata_does_not_win_over_the_source_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    """The control. The two agree in a clean environment, so agreement proves
    nothing on its own; make them disagree and check which one is believed."""
    import importlib.metadata

    monkeypatch.setattr(importlib.metadata, "version", lambda _name: "0.0.1-stale-install")
    assert _resolve_version() != "0.0.1-stale-install", (
        "the CLI is reporting the installed distribution rather than the running source again"
    )
    assert _resolve_version() == _detect_version()


def test_the_metadata_lookup_is_still_the_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """It has to stay reachable: a real installed copy has no source tree above
    it, and that is the case the fallback is for. The helper imports Settings
    inside its own body, so replacing the name on the config module is what a
    broken settings import looks like from in there."""
    import importlib.metadata

    import app.config as config_module

    class _Unusable:
        @property
        def model_fields(self) -> dict[str, object]:
            raise RuntimeError("settings unavailable")

    monkeypatch.setattr(config_module, "Settings", _Unusable(), raising=True)
    monkeypatch.setattr(importlib.metadata, "version", lambda _name: "9.9.9-from-metadata")
    assert _resolve_version() == "9.9.9-from-metadata"

    # And with neither source available it says so rather than printing the
    # sentinel pydantic keeps where a default_factory field's default would be.
    def _absent(_name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(_name)

    monkeypatch.setattr(importlib.metadata, "version", _absent)
    got = _resolve_version()
    assert got == "unknown", got
    assert "PydanticUndefined" not in got
