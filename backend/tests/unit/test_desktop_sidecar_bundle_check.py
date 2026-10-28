"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The build gate that reads the produced desktop sidecar.

``scripts/check_desktop_sidecar_bundle.py`` is the output half of the issue
#419 fix: the hook refuses to build without PostgreSQL's loadable modules, and
this reads the onefile archive that came out and confirms they are inside it.
Neither can see what the other misses, so both have to be right.

The script is wired into the release workflow as a hard step, which makes its
own failure modes interesting: a step that raises takes the Linux sidecar job
with it, and no installer ships at all. That is the same user-visible outcome
as #419. So the cases here are about the script's behaviour, not PyInstaller's.
The archive reader is stubbed, because what it returns is already settled by
the smoke test against real onefile executables; what is not settled is what
this script does with the names.

Cases:
    * a bundle carrying the modules and the executables passes
    * a bundle missing dict_snowball fails and says why
    * a Windows bundle, where the same modules are .dll, passes
    * an empty archive fails rather than passing vacuously
    * a path that is not a file fails without reaching the reader
    * the suffix stripping does not confuse a module with a longer name
    * a support file of the same name elsewhere in the tree does not stand in
      for the module or the executable
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "check_desktop_sidecar_bundle.py"

_PGDIR = "pixeltable_pgserver/pginstall"

# What a healthy Linux bundle looks like, trimmed to the entries the check reads.
LINUX_NAMES = {
    f"{_PGDIR}/bin/postgres",
    f"{_PGDIR}/bin/initdb",
    f"{_PGDIR}/bin/pg_ctl",
    f"{_PGDIR}/lib/libpq.so.5",
    f"{_PGDIR}/lib/postgresql/dict_snowball.so",
    f"{_PGDIR}/lib/postgresql/plpgsql.so",
    f"{_PGDIR}/share/postgresql/postgres.bki",
    "base_library.zip",
}

# The same bundle on Windows. PyInstaller writes backslashes into the archive
# names there, and PostgreSQL names the modules .dll, which is the whole reason
# the Windows installer was never affected by #419.
WINDOWS_NAMES = {name.replace("/", "\\").replace(".so", ".dll") for name in LINUX_NAMES} | {"base_library.zip"}


def _load_script():
    """Import the script by path. It lives in scripts/, which is not a package."""
    spec = importlib.util.spec_from_file_location("check_desktop_sidecar_bundle", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def script():
    return _load_script()


def _run(script, monkeypatch, tmp_path, names, *, make_file=True) -> int:
    """Call main() against a stubbed archive and return its exit code."""
    executable = tmp_path / "openconstructionerp-server"
    if make_file:
        executable.write_bytes(b"not really an executable")
    monkeypatch.setattr(script, "_archive_names", lambda _path: set(names))
    monkeypatch.setattr(sys, "argv", ["check_desktop_sidecar_bundle.py", str(executable)])
    return script.main()


def test_script_exists():
    """A rename or a move would make every other test here silently vacuous."""
    assert SCRIPT_PATH.is_file(), SCRIPT_PATH


def test_a_healthy_linux_bundle_passes(script, monkeypatch, tmp_path, capsys):
    assert _run(script, monkeypatch, tmp_path, LINUX_NAMES) == 0
    out = capsys.readouterr().out
    assert "sidecar bundle OK" in out
    # The passing path prints where the module landed, so a layout change shows
    # up in the build log instead of waiting for a user to hit it.
    assert "lib/postgresql/dict_snowball.so" in out


def test_a_windows_bundle_passes_with_dll_modules(script, monkeypatch, tmp_path, capsys):
    assert _run(script, monkeypatch, tmp_path, WINDOWS_NAMES) == 0
    assert "sidecar bundle OK" in capsys.readouterr().out


def test_a_bundle_without_dict_snowball_fails(script, monkeypatch, tmp_path, capsys):
    """The #419 bundle: everything else is there, initdb still cannot run."""
    names = {n for n in LINUX_NAMES if "dict_snowball" not in n}
    assert _run(script, monkeypatch, tmp_path, names) == 1
    out = capsys.readouterr().out
    assert "dict_snowball" in out
    assert "#419" in out


def test_a_bundle_without_the_executables_fails(script, monkeypatch, tmp_path, capsys):
    """Modules present but bin/ absent is a different fault with the same symptom."""
    names = {n for n in LINUX_NAMES if "/bin/" not in n}
    assert _run(script, monkeypatch, tmp_path, names) == 1
    out = capsys.readouterr().out
    assert "initdb" in out
    assert "postgres" in out


def test_an_empty_archive_fails(script, monkeypatch, tmp_path, capsys):
    """An unreadable archive reads as zero entries, which must not pass."""
    assert _run(script, monkeypatch, tmp_path, set()) == 1
    assert "empty archive" in capsys.readouterr().out


def test_a_missing_executable_fails_before_the_reader(script, monkeypatch, tmp_path, capsys):
    assert _run(script, monkeypatch, tmp_path, LINUX_NAMES, make_file=False) == 1
    assert "is not a file" in capsys.readouterr().out


def test_a_longer_name_does_not_satisfy_a_required_module(script, monkeypatch, tmp_path):
    """dict_snowball_extra is not dict_snowball.

    The check compares suffix-free basenames, so it has to split on the first
    dot rather than match a prefix, otherwise a neighbouring file would stand in
    for the module that is actually missing.
    """
    names = {n for n in LINUX_NAMES if "dict_snowball" not in n}
    names.add(f"{_PGDIR}/lib/postgresql/dict_snowball_extra.so")
    assert _run(script, monkeypatch, tmp_path, names) == 1


def test_a_support_file_of_the_same_name_does_not_stand_in_for_a_module(script, monkeypatch, tmp_path, capsys):
    """share/postgresql/plpgsql.control is not the plpgsql module.

    PostgreSQL ships several files whose name matches a module once the suffix
    is cut: plpgsql.control and plpgsql--1.0.sql next to the extension, and
    postgres.bki next to the catalogue templates. Matching a bare basename let
    those satisfy two of the five required names, so a bundle that had lost
    every loadable module would still have passed on plpgsql and on postgres.
    """
    names = {n for n in LINUX_NAMES if "/lib/postgresql/" not in n and "/bin/" not in n}
    names |= {
        f"{_PGDIR}/share/postgresql/extension/plpgsql.control",
        f"{_PGDIR}/share/postgresql/postgres.bki",
        f"{_PGDIR}/share/postgresql/dict_snowball.txt",
    }
    assert _run(script, monkeypatch, tmp_path, names) == 1
    out = capsys.readouterr().out
    assert "dict_snowball" in out
    assert "plpgsql" in out
    assert "postgres" in out
    # And it says the name was found elsewhere, because a file in the wrong
    # place and a file that is absent need different fixes.
    assert "found under another path" in out


def test_a_versioned_library_keeps_its_full_stem(script):
    """libpq.so.5 was never dropped by the old hook, and must not be counted as
    a module either: the required names are matched on the stem before the first
    dot, which is what makes .so and .dll the same entry."""
    assert script._split(f"{_PGDIR}/lib/libpq.so.5") == (f"{_PGDIR}/lib", "libpq")


def test_the_module_directory_is_told_apart_from_the_share_directory(script):
    """Both end in postgresql; only one holds loadable modules."""
    assert script._is_module_dir(f"{_PGDIR}/lib/postgresql")
    assert script._is_module_dir(f"{_PGDIR}/lib")
    assert not script._is_module_dir(f"{_PGDIR}/share/postgresql")
    assert not script._is_module_dir(f"{_PGDIR}/share/postgresql/extension")
    assert script._is_bin_dir(f"{_PGDIR}/bin")
    assert not script._is_bin_dir(f"{_PGDIR}/sbin")
