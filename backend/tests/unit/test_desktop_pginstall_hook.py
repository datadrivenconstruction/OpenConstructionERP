"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The PyInstaller hook that bundles the embedded PostgreSQL tree.

Issue #419: on Ubuntu based distributions the desktop app stopped at "Starting
the local database" because initdb could not load ``$libdir/dict_snowball``.
The hook collected the ``pginstall/`` tree with PyInstaller's
``collect_data_files``, which is documented to return only files that are "not
shared libraries / binary python extensions" and decides that from the suffix
alone: it excludes every entry in ``importlib.machinery.all_suffixes()``. On
Linux that list contains ``.so``, which is exactly how PostgreSQL names its own
loadable modules there, so dict_snowball, plpgsql, pgoutput and the encoding
converters were dropped. Windows and macOS name the same modules ``.dll`` and
``.dylib``, neither of which is a Python extension suffix, so both of those
installers were intact and the break looked platform specific rather than
suffix specific.

These tests exec the real hook file against a synthetic package tree, with a
stub ``collect_data_files`` that reproduces the exclusion. That is the point: if
the hook ever goes back to leaning on the helper for the PostgreSQL tree, the
stub drops the modules again and the first test fails.

Cases:
    * a loadable module survives a helper that excludes its suffix
    * loadable modules and bin/ executables are collected as binaries, so
      PyInstaller marks them executable on extraction
    * the tree keeps its layout, which is what lets PostgreSQL find $libdir
      relative to its own executable
    * ordinary support files stay data
    * files outside pginstall/ still come from the helper
    * Windows takes the whole tree as data, unchanged from before the fix
    * a tree without dict_snowball fails the build instead of shipping
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

HOOK_PATH = Path(__file__).resolve().parents[3] / "desktop" / "hooks" / "hook-pixeltable_pgserver.py"

# What PyInstaller's collect_data_files excludes on a Linux build. The real
# value is importlib.machinery.all_suffixes(), which is platform dependent;
# pinning the Linux set here is what makes this test reproduce #419 when it runs
# on a Windows or macOS developer machine. macOS shares the .so entry but names
# its PostgreSQL modules .dylib, so only Linux was ever hit.
POSIX_PY_SUFFIXES = (".py", ".pyc", ".so")

# Names taken from a real pixeltable-pgserver wheel. dict_snowball is the one
# initdb needs, vector is pgvector, libpq.so.5 is a versioned support library
# that was never affected because its name does not end in ".so".
TREE = [
    "pginstall/bin/postgres",
    "pginstall/bin/initdb",
    "pginstall/bin/pg_ctl",
    "pginstall/lib/libpq.so.5",
    "pginstall/lib/libpgcommon.a",
    "pginstall/lib/postgresql/dict_snowball.so",
    "pginstall/lib/postgresql/plpgsql.so",
    "pginstall/lib/postgresql/vector.so",
    "pginstall/lib/postgresql/utf8_and_win.so",
    "pginstall/share/postgresql/postgres.bki",
    "pginstall/share/postgresql/snowball_create.sql",
    "pginstall/share/postgresql/timezone/UTC",
    "py.typed",
]


def _write_tree(root: Path, entries: list[str]) -> tuple[Path, Path]:
    """Build a fake site-packages holding the package. Returns (base, pkg_dir)."""
    base = root / "site-packages"
    pkg_dir = base / "pixeltable_pgserver"
    for entry in entries:
        path = pkg_dir / entry
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
    (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
    return base, pkg_dir


def _stub_collect_data_files(base: Path, pkg_dir: Path):
    """Stand in for PyInstaller's helper, including its suffix exclusion."""

    def collect_data_files(package, include_py_files=False):  # noqa: ANN001, ANN202, ARG001
        collected = []
        for path in sorted(pkg_dir.rglob("*")):
            if not path.is_file() or path.name.endswith(POSIX_PY_SUFFIXES):
                continue
            collected.append((str(path), str(path.parent.relative_to(base))))
        return collected

    return collect_data_files


def _run_hook(monkeypatch, base: Path, pkg_dir: Path, platform: str = "linux") -> dict:
    """Exec the hook with PyInstaller stubbed out, and hand back its namespace."""
    hooks = types.ModuleType("PyInstaller.utils.hooks")
    hooks.collect_data_files = _stub_collect_data_files(base, pkg_dir)
    hooks.get_package_paths = lambda package: (str(base), str(pkg_dir))  # noqa: ARG005
    utils = types.ModuleType("PyInstaller.utils")
    utils.hooks = hooks
    pyinstaller = types.ModuleType("PyInstaller")
    pyinstaller.utils = utils

    monkeypatch.setitem(sys.modules, "PyInstaller", pyinstaller)
    monkeypatch.setitem(sys.modules, "PyInstaller.utils", utils)
    monkeypatch.setitem(sys.modules, "PyInstaller.utils.hooks", hooks)
    monkeypatch.setattr(sys, "platform", platform)

    namespace = {"__file__": str(HOOK_PATH), "__name__": "hook_pixeltable_pgserver"}
    exec(compile(HOOK_PATH.read_text(encoding="utf-8"), str(HOOK_PATH), "exec"), namespace)
    return namespace


@pytest.fixture
def tree(tmp_path):
    return _write_tree(tmp_path, TREE)


def _names(entries: list[tuple[str, str]]) -> set[str]:
    return {Path(src).name for src, _dest in entries}


def test_hook_file_exists():
    """A rename would make every other test here silently vacuous."""
    assert HOOK_PATH.is_file(), HOOK_PATH


def test_loadable_module_survives_a_helper_that_excludes_its_suffix(monkeypatch, tree):
    """The #419 regression test: dict_snowball.so is not offered by the helper."""
    base, pkg_dir = tree
    helper = _stub_collect_data_files(base, pkg_dir)
    assert "dict_snowball.so" not in _names(helper("pixeltable_pgserver"))

    namespace = _run_hook(monkeypatch, base, pkg_dir)
    collected = _names(namespace["binaries"]) | _names(namespace["datas"])
    assert "dict_snowball.so" in collected


def test_every_loadable_module_is_collected(monkeypatch, tree):
    base, pkg_dir = tree
    namespace = _run_hook(monkeypatch, base, pkg_dir)
    collected = _names(namespace["binaries"]) | _names(namespace["datas"])
    for module in ("plpgsql.so", "vector.so", "utf8_and_win.so", "libpq.so.5"):
        assert module in collected, module


def test_modules_and_executables_are_binaries_not_data(monkeypatch, tree):
    """PyInstaller sets the executable bit only on entries collected as binaries."""
    base, pkg_dir = tree
    namespace = _run_hook(monkeypatch, base, pkg_dir)
    binaries = _names(namespace["binaries"])
    assert {"initdb", "postgres", "pg_ctl"} <= binaries
    assert {"dict_snowball.so", "plpgsql.so", "libpq.so.5"} <= binaries
    assert "postgres.bki" not in binaries


def test_layout_is_preserved(monkeypatch, tree):
    """PostgreSQL resolves $libdir from its own executable, so bin/ and lib/ must
    keep their relative positions inside the extracted bundle."""
    base, pkg_dir = tree
    namespace = _run_hook(monkeypatch, base, pkg_dir)
    dests = {Path(src).name: dest.replace("\\", "/") for src, dest in namespace["binaries"]}
    assert dests["initdb"] == "pixeltable_pgserver/pginstall/bin"
    assert dests["dict_snowball.so"] == "pixeltable_pgserver/pginstall/lib/postgresql"


def test_support_files_stay_data(monkeypatch, tree):
    base, pkg_dir = tree
    namespace = _run_hook(monkeypatch, base, pkg_dir)
    datas = _names(namespace["datas"])
    assert {"postgres.bki", "snowball_create.sql", "UTC", "libpgcommon.a"} <= datas


def test_files_outside_pginstall_still_come_from_the_helper(monkeypatch, tree):
    base, pkg_dir = tree
    namespace = _run_hook(monkeypatch, base, pkg_dir)
    assert "py.typed" in _names(namespace["datas"])


def test_nothing_is_collected_twice(monkeypatch, tree):
    """A file in both lists makes PyInstaller pick one and warn about the other."""
    base, pkg_dir = tree
    namespace = _run_hook(monkeypatch, base, pkg_dir)
    entries = namespace["binaries"] + namespace["datas"]
    assert len(entries) == len(set(entries))


def test_windows_takes_the_whole_tree_as_data(monkeypatch, tree):
    """Windows ignores the executable bit, and routing the PG binaries through PE
    import analysis can duplicate or misplace their DLLs."""
    base, pkg_dir = tree
    namespace = _run_hook(monkeypatch, base, pkg_dir, platform="win32")
    assert namespace["binaries"] == []
    assert {"initdb", "dict_snowball.so", "postgres.bki"} <= _names(namespace["datas"])


def test_a_tree_without_dict_snowball_stops_the_build(monkeypatch, tmp_path):
    """Better a red build than an installer that dies on the user's machine."""
    base, pkg_dir = _write_tree(tmp_path, [e for e in TREE if "dict_snowball" not in e])
    with pytest.raises(SystemExit) as excinfo:
        _run_hook(monkeypatch, base, pkg_dir)
    assert "dict_snowball" in str(excinfo.value)


def test_a_tree_without_plpgsql_stops_the_build(monkeypatch, tmp_path):
    base, pkg_dir = _write_tree(tmp_path, [e for e in TREE if "plpgsql" not in e])
    with pytest.raises(SystemExit) as excinfo:
        _run_hook(monkeypatch, base, pkg_dir)
    assert "plpgsql" in str(excinfo.value)
