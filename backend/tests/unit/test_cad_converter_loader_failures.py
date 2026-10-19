"""The converter health check has to notice a binary Windows refuses to start.

Issue #416. A user opened the BIM page and Windows put up a "Bad Image" box
naming a DLL beside the converter executable, error 0xC000007B. Two separate
things were wrong, and the one that matters is not the one in the title.

The exit code was not in the set the health check recognises, so it fell
through to the branch that reports every unrecognised code as healthy. The
status card said the converter was fine while the operating system was
refusing to run it.

And the box itself is drawn by the loader in a process we started, so nothing
we write reaches the screen until somebody clicks OK on a dialog the
application does not know exists.

These tests pin the classification, which is pure logic and runs anywhere.
Whether the dialog is actually suppressed is a Windows behaviour: the call is
asserted here, and only a Windows machine can confirm the effect.
"""

from __future__ import annotations

import contextlib
import sys
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from app.modules.boq import cad_import


@pytest.fixture(autouse=True)
def _clear_health_cache() -> Any:
    """The check caches for five minutes, which would leak between tests."""
    cad_import._HEALTH_CACHE.clear()
    yield
    cad_import._HEALTH_CACHE.clear()


@pytest.fixture
def installed_exe(tmp_path: Path) -> Path:
    """A converter folder shaped the way the installer writes one.

    The exit-code tests need a complete folder, because the check now
    refuses a folder that is missing the libraries we ship beside the exe
    before it spawns anything - which is its own behaviour, tested below.
    Pointing these at a path that does not exist would quietly move every
    one of them onto that branch.
    """
    folder = tmp_path / "ifc_windows"
    (folder / "runtime").mkdir(parents=True)
    exe = folder / "runtime" / "python.exe"
    exe.write_bytes(b"MZ" + b"\x00" * 2048)
    script = folder / "sources" / "ifc-excel" / "converter.py"
    script.parent.mkdir(parents=True)
    script.write_text("print('converter')", encoding="utf-8")
    return exe


def _run_smoke(exe: Path, exit_code: int, stderr: bytes = b"") -> dict[str, Any]:
    """Drive smoke_test_converter over a converter that exits with a code."""
    completed = mock.Mock(returncode=exit_code, stdout=b"", stderr=stderr)
    with (
        mock.patch.object(cad_import, "find_converter", return_value=exe),
        mock.patch("subprocess.run", return_value=completed),
    ):
        return dict(cad_import.smoke_test_converter("ifc", force=True))


# The four codes are one family: the image never reaches its first
# instruction. Listed by name so a future reader can check them against the
# NTSTATUS tables rather than trusting the numbers here.
LOADER_FAILURES = [
    pytest.param(0xC0000135, id="dll-not-found"),
    pytest.param(0xC0000142, id="dll-init-failed"),
    pytest.param(0xC000007B, id="invalid-image-format"),
    pytest.param(0xC0000139, id="entrypoint-not-found"),
]


@pytest.mark.parametrize("status", LOADER_FAILURES)
def test_loader_failure_is_reported_as_failed(installed_exe: Path, status: int) -> None:
    assert _run_smoke(installed_exe, status)["status"] == "failed"


@pytest.mark.parametrize("status", LOADER_FAILURES)
def test_loader_failure_is_caught_however_the_sign_arrives(installed_exe: Path, status: int) -> None:
    """subprocess reports these as a negative int on some paths and unsigned on others."""
    assert _run_smoke(installed_exe, status - 0x1_0000_0000)["status"] == "failed"


def test_the_code_from_the_report_is_not_called_healthy(installed_exe: Path) -> None:
    """The specific regression: 0xC000007B used to fall through to "ok"."""
    result = _run_smoke(installed_exe, 0xC000007B)
    assert result["status"] == "failed"
    assert result["message"], "a failed converter must say why"


def test_bitness_message_claims_only_what_we_have_measured(installed_exe: Path) -> None:
    """This text used to assert something we later measured to be false.

    It said every library was present and one of them was built for the other
    word size, and it sent the user to download the converter again. Every PE
    image we publish is 64-bit, in every version we have ever published, so
    the word-size claim describes nothing we ship - and the download
    overwrites and adds, so it was never the step that removes a file which
    should not be in the folder. Uninstall is.

    The plugin assertion stays from the original: sending somebody to fetch
    plugins is not advice this converter generation has any use for.
    """
    message = _run_smoke(installed_exe, 0xC000007B)["message"]
    assert "0xc000007b" in message.lower()
    assert "64-bit" in message
    assert "uninstall" in message.lower()
    assert "plugin" not in message.lower()


def test_missing_dll_still_names_the_runtime(installed_exe: Path) -> None:
    message = _run_smoke(installed_exe, 0xC0000135)["message"]
    assert "Visual C++" in message
    assert "0xc0000135" in message.lower()


def test_an_ordinary_non_zero_exit_is_still_healthy(installed_exe: Path) -> None:
    """The probe feeds a newline to a CAD converter, so it is meant to fail.

    Only a loader failure means the install is broken; a binary that starts
    and then rejects the input has proved everything this check asks of it.
    """
    assert _run_smoke(installed_exe, 1)["status"] == "ok"
    assert _run_smoke(installed_exe, 0)["status"] == "ok"
    # Neighbours of the recognised codes, to show the set is a list and not a
    # range that swallows whatever is nearby.
    assert _run_smoke(installed_exe, 0xC0000136)["status"] == "ok"
    assert _run_smoke(installed_exe, 0xC000007A)["status"] == "ok"


def test_the_probe_asks_windows_not_to_draw_its_own_dialog(installed_exe: Path) -> None:
    """The suppression has to wrap the spawn, or the box appears before we can report.

    Asserted by ordering rather than by outcome: the effect is a Windows
    behaviour and this suite runs everywhere.
    """
    calls: list[str] = []
    completed = mock.Mock(returncode=0xC000007B, stdout=b"", stderr=b"")

    @contextlib.contextmanager
    def _tracking_guard() -> Any:
        calls.append("guard-enter")
        yield
        calls.append("guard-exit")

    def _tracking_run(*_args: Any, **_kwargs: Any) -> Any:
        calls.append("spawn")
        return completed

    with (
        mock.patch.object(cad_import, "find_converter", return_value=installed_exe),
        mock.patch.object(cad_import, "_windows_loader_errors_stay_quiet", _tracking_guard),
        mock.patch("subprocess.run", _tracking_run),
    ):
        cad_import.smoke_test_converter("ifc", force=True)

    assert calls == ["guard-enter", "spawn", "guard-exit"]


# ── The partial folder, which used to read as a healthy install ──────────


def test_a_folder_missing_the_converter_script_is_reported_before_anything_is_spawned(
    installed_exe: Path,
) -> None:
    """The leading hypothesis for the reported failure, and it was invisible.

    A rollback on Windows cannot delete a file another process holds open,
    both rollbacks in the installer ignore errors, and resolution accepted any
    file over 1 KB - so a folder holding the exe and nothing else passed for an
    install. Windows then falls through the rest of its search order, and a
    32-bit Qt belonging to some other program is exactly the 0xC000007B the
    report carried.

    The spawn is asserted not to happen: whether such a folder starts at all
    depends on what else is on the machine, so the answer must not.
    """
    (installed_exe.parents[1] / "sources" / "ifc-excel" / "converter.py").unlink()
    spawned: list[str] = []

    def _refuse_to_spawn(*_args: Any, **_kwargs: Any) -> Any:
        spawned.append("spawn")
        raise AssertionError("the check must not launch a converter from a partial folder")

    with (
        mock.patch.object(cad_import, "find_converter", return_value=installed_exe),
        mock.patch("subprocess.run", _refuse_to_spawn),
    ):
        result = cad_import.smoke_test_converter("ifc", force=True)

    assert spawned == []
    assert result["status"] == "failed"
    assert "converter.py" in result["message"]
    assert "uninstall" in result["message"].lower()


def test_a_complete_folder_is_not_reported_as_partial(installed_exe: Path) -> None:
    """The other half of the pair - the check has to pass on a good tree.

    Without this, emptying the companion list would leave the test above
    green while the guard did nothing at all.
    """
    assert cad_import.missing_companion_files(installed_exe) == []
    assert _run_smoke(installed_exe, 0)["status"] == "ok"


def test_a_binary_that_is_not_one_of_our_packages_is_not_asked_for_companions(tmp_path: Path) -> None:
    """Only the executables of the release packages have companions to check.

    Keyed on the package layout rather than on the host platform, so this holds
    when the check runs on a Windows machine too.
    """
    linux_exe = tmp_path / "SomethingElse"
    linux_exe.write_bytes(b"\x7fELF" + b"\x00" * 2048)
    assert cad_import.missing_companion_files(linux_exe) == []


@pytest.mark.skipif(sys.platform.startswith("win"), reason="the guard does real work on Windows")
def test_the_guard_is_inert_off_windows() -> None:
    """Linux and macOS already return a loader failure as an exit code."""
    with cad_import._windows_loader_errors_stay_quiet():
        pass
