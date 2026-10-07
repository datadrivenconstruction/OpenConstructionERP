# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tests for the runtime module root.

The claim under test is not "a string was appended to a list". It is "a module
written into the instance's data directory can be imported as
``app.modules.<name>``, and one that collides with a shipped module cannot
take its place". Every test here goes through the real import system for that
reason: a test that only inspected ``__path__`` would pass on an attachment
that Python never actually consults.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from app.core import module_runtime_root as rr

MANIFEST_SOURCE = """\
from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="{name}",
    version="{version}",
    display_name="{display}",
    category="community",
)
"""


def write_module(root: Path, dir_name: str, *, name: str, version: str = "0.1.0") -> Path:
    """Create a minimal but genuine module package under ``root``."""
    module_dir = root / dir_name
    module_dir.mkdir(parents=True, exist_ok=True)
    (module_dir / "__init__.py").write_text("", encoding="utf-8")
    (module_dir / "manifest.py").write_text(
        MANIFEST_SOURCE.format(name=name, version=version, display=name.replace("_", " ").title()),
        encoding="utf-8",
    )
    return module_dir


@pytest.fixture
def runtime_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A runtime root that is detached and purged from sys.modules afterwards.

    Import state is process-global, so a leaked ``__path__`` entry or a cached
    ``app.modules.<name>`` would leak into every later test in the session and
    make failures land somewhere other than where they were caused.
    """
    root = tmp_path / "instance-modules"
    monkeypatch.setenv(rr.ENV_VAR, str(root))
    before = list(rr._package_path())
    yield root
    path = rr._package_path()
    path[:] = before
    for name in [n for n in sys.modules if n.startswith("app.modules.zz")]:
        del sys.modules[name]
    importlib.invalidate_caches()


class TestResolution:
    def test_suite_excludes_home_plugins_but_keeps_bundled_modules(self, tmp_path, monkeypatch):
        from app import modules
        from app.core.module_loader import ModuleLoader

        fake_home_modules = tmp_path / "user-home-modules"
        write_module(fake_home_modules, "zz_home_only", name="oe_zz_home_only")
        monkeypatch.setattr(rr, "default_runtime_modules_dir", lambda: fake_home_modules)
        # Preserve the actual fixture environment; replacing it here would
        # merely test the application's override, not the suite's isolation.
        monkeypatch.setattr(modules, "__path__", [str(Path(modules.__file__).parent)])
        try:
            attached = rr.attach_runtime_root()
            names = {manifest.name for manifest in ModuleLoader().discover()}
            assert attached != fake_home_modules
            assert "oe_zz_home_only" not in names
            assert {"oe_users", "oe_projects", "oe_cost_match"} <= names
            assert (fake_home_modules / "zz_home_only" / "manifest.py").exists()
        finally:
            for name in list(sys.modules):
                if name.startswith("app.modules.zz_home_only"):
                    del sys.modules[name]
            importlib.invalidate_caches()

    def test_env_override_wins(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(rr.ENV_VAR, str(tmp_path / "elsewhere"))
        assert rr.runtime_modules_dir() == tmp_path / "elsewhere"

    def test_falls_back_to_the_instance_home(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(rr.ENV_VAR, raising=False)
        assert rr.runtime_modules_dir() == rr.default_runtime_modules_dir()
        assert rr.runtime_modules_dir().name == "modules"

    def test_blank_override_is_not_an_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # An env var set to empty or whitespace is how a shell exports "unset".
        # Treating it as a path would point the root at the process's cwd.
        monkeypatch.setenv(rr.ENV_VAR, "   ")
        assert rr.runtime_modules_dir() == rr.default_runtime_modules_dir()

    def test_resolving_does_not_create_anything(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        target = tmp_path / "not-yet"
        monkeypatch.setenv(rr.ENV_VAR, str(target))
        rr.runtime_modules_dir()
        assert not target.exists()


class TestAttach:
    def test_attach_creates_the_directory_and_appends_once(self, runtime_root: Path) -> None:
        before = len(rr._package_path())

        attached = rr.attach_runtime_root()

        assert attached == runtime_root
        assert runtime_root.is_dir()
        assert len(rr._package_path()) == before + 1
        assert rr.is_attached()

        # Startup can run twice under a reloader, and a second entry would make
        # every module discoverable twice.
        rr.attach_runtime_root()
        assert len(rr._package_path()) == before + 1

    def test_attach_appends_rather_than_prepends(self, runtime_root: Path) -> None:
        shipped_first = rr._package_path()[0]
        rr.attach_runtime_root()
        assert rr._package_path()[0] == shipped_first
        assert str(runtime_root) in rr._package_path()[-1]

    def test_missing_directory_without_create_attaches_nothing(self, runtime_root: Path) -> None:
        before = list(rr._package_path())
        assert rr.attach_runtime_root(create=False) is None
        assert rr._package_path() == before

    def test_detach_removes_it(self, runtime_root: Path) -> None:
        rr.attach_runtime_root()
        assert rr.detach_runtime_root(runtime_root) is True
        assert not rr.is_attached()
        assert rr.detach_runtime_root(runtime_root) is False

    def test_detach_never_removes_the_shipped_root(self, runtime_root: Path) -> None:
        shipped = Path(rr._package_path()[0])
        assert rr.detach_runtime_root(shipped) is False
        assert Path(rr._package_path()[0]) == shipped


class TestImportsForReal:
    """The part that matters: does Python find the module."""

    def test_a_runtime_module_is_importable(self, runtime_root: Path) -> None:
        runtime_root.mkdir(parents=True, exist_ok=True)
        write_module(runtime_root, "zz_runtime_demo", name="oe_zz_runtime_demo", version="2.3.4")
        rr.attach_runtime_root()
        importlib.invalidate_caches()

        mod = importlib.import_module("app.modules.zz_runtime_demo.manifest")

        assert mod.manifest.name == "oe_zz_runtime_demo"
        assert mod.manifest.version == "2.3.4"

    def test_it_is_not_importable_before_attaching(self, runtime_root: Path) -> None:
        # Establishes that the previous test proves the attachment and not
        # merely that tmp_path happened to be importable for another reason.
        runtime_root.mkdir(parents=True, exist_ok=True)
        write_module(runtime_root, "zz_not_attached", name="oe_zz_not_attached")
        importlib.invalidate_caches()

        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("app.modules.zz_not_attached.manifest")

    def test_the_loader_discovers_it(self, runtime_root: Path) -> None:
        from app.core.module_loader import ModuleLoader

        runtime_root.mkdir(parents=True, exist_ok=True)
        write_module(runtime_root, "zz_discovered", name="oe_zz_discovered", version="1.5.0")
        rr.attach_runtime_root()
        importlib.invalidate_caches()

        manifests = ModuleLoader().discover(runtime_root)

        assert [m.name for m in manifests] == ["oe_zz_discovered"]
        assert manifests[0].version == "1.5.0"


class TestShadowing:
    """A shipped module must win, and the loser must be named."""

    @staticmethod
    def _a_shipped_module_dir() -> str:
        shipped = Path(rr._package_path()[0])
        for child in sorted(shipped.iterdir()):
            if child.is_dir() and (child / "manifest.py").is_file():
                return child.name
        pytest.skip("no shipped module with a manifest to collide with")

    def test_shipped_wins_the_collision(self, runtime_root: Path) -> None:
        victim = self._a_shipped_module_dir()
        runtime_root.mkdir(parents=True, exist_ok=True)
        write_module(runtime_root, victim, name="oe_impostor", version="99.0.0")
        rr.attach_runtime_root()
        importlib.invalidate_caches()

        mod = importlib.import_module(f"app.modules.{victim}.manifest")

        assert mod.manifest.name != "oe_impostor"
        assert mod.manifest.version != "99.0.0"

    def test_the_shadowed_module_is_named(self, runtime_root: Path) -> None:
        victim = self._a_shipped_module_dir()
        runtime_root.mkdir(parents=True, exist_ok=True)
        write_module(runtime_root, victim, name="oe_impostor")
        write_module(runtime_root, "zz_no_collision", name="oe_zz_no_collision")
        rr.attach_runtime_root()

        assert rr.shadowed_modules() == [victim]

    def test_nothing_is_shadowed_when_names_are_free(self, runtime_root: Path) -> None:
        runtime_root.mkdir(parents=True, exist_ok=True)
        write_module(runtime_root, "zz_free", name="oe_zz_free")
        rr.attach_runtime_root()

        assert rr.shadowed_modules() == []

    def test_origin_reports_where_python_will_look(self, runtime_root: Path) -> None:
        victim = self._a_shipped_module_dir()
        runtime_root.mkdir(parents=True, exist_ok=True)
        write_module(runtime_root, victim, name="oe_impostor")
        write_module(runtime_root, "zz_only_runtime", name="oe_zz_only_runtime")
        rr.attach_runtime_root()

        assert rr.origin_of(victim) == "shipped"
        assert rr.origin_of("zz_only_runtime") == "runtime"
        assert rr.origin_of("zz_nowhere") is None
