"""Unit tests for Linux apt-install path of the CAD/BIM converters.

Plan A1 of the Linux-converter rollout: confirm that
  - find_converter() picks up `/usr/bin/{Format}Exporter` (the actual
    binary inside the upstream `.deb` packages from
    `pkg.datadrivenconstruction.io`),
  - the legacy `/usr/bin/ddc-{ext}converter` probe still works as a
    fallback for users who installed from older instructions,
  - smoke_test_converter() recognises the Linux ld.so missing-shared-
    library failure (exit 127 + "error while loading shared libraries"
    in stderr) and reports `failed` with reinstall_converter as the
    suggested action,
  - non-127 exits on Linux are treated as `ok` (binary loaded, exited
    on the empty-stdin input — same convention as the Windows path).

The tests do not require a real Linux environment — they monkeypatch
``sys.platform`` and the filesystem probes so they are runnable on
Windows and macOS CI runners too.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from app.modules.boq import cad_import

# ── find_converter() ───────────────────────────────────────────────────


def _patch_no_other_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every non-Linux candidate look absent so the test focuses
    on the Linux apt probe specifically. We don't want the Windows
    install-dir under `~/.openestimator/converters/...` to accidentally
    contain a leftover binary from a previous local run."""
    monkeypatch.setattr(cad_import, "CONVERTER_SEARCH_PATHS", [Path("/nonexistent/oe-test")])
    monkeypatch.setattr(cad_import, "_find_ddc_toolkit_bin", lambda: None)
    # Block the per-format Windows install-dir probe by pointing
    # Path.home() at an empty tmp dir handled by the test's monkeypatch.
    monkeypatch.delenv("OPENESTIMATOR_CONVERTERS_DIR", raising=False)
    monkeypatch.delenv("DDC_TOOLKIT_DIR", raising=False)


def test_find_converter_picks_up_real_apt_binary_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """`/usr/bin/RvtExporter` (real .deb binary name) is found when present."""
    _patch_no_other_paths(monkeypatch)
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path))

    real_existing: dict[str, int] = {"/usr/bin/RvtExporter": 4096}

    original_exists = Path.exists
    original_stat = Path.stat

    def fake_exists(self: Path) -> bool:
        # ``as_posix()`` keeps the test cross-platform — on Windows the
        # path constructor stores back-slashes, but the upstream code
        # compares against POSIX paths conceptually.
        return self.as_posix() in real_existing or original_exists(self)

    def fake_stat(self: Path, **_kwargs: Any) -> Any:
        if self.as_posix() in real_existing:

            class _S:
                st_size = real_existing[self.as_posix()]

            return _S()
        return original_stat(self)

    monkeypatch.setattr(Path, "exists", fake_exists)
    monkeypatch.setattr(Path, "stat", fake_stat)

    found = cad_import.find_converter("rvt")

    assert found is not None
    assert found.as_posix() == "/usr/bin/RvtExporter"


def test_find_converter_falls_back_to_legacy_ddc_name(  # noqa: PLR0915
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Legacy `/usr/bin/ddc-rvtconverter` symlink path still resolves.

    Some early users installed by hand-symlinking the binary under the
    package name. The probe keeps that path as a secondary fallback so
    those installs don't break.
    """
    _patch_no_other_paths(monkeypatch)
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path))

    real_existing: dict[str, int] = {"/usr/bin/ddc-rvtconverter": 4096}

    original_exists = Path.exists
    original_stat = Path.stat

    def fake_exists(self: Path) -> bool:
        # ``as_posix()`` keeps the test cross-platform — on Windows the
        # path constructor stores back-slashes, but the upstream code
        # compares against POSIX paths conceptually.
        return self.as_posix() in real_existing or original_exists(self)

    def fake_stat(self: Path, **_kwargs: Any) -> Any:
        if self.as_posix() in real_existing:

            class _S:
                st_size = real_existing[self.as_posix()]

            return _S()
        return original_stat(self)

    monkeypatch.setattr(Path, "exists", fake_exists)
    monkeypatch.setattr(Path, "stat", fake_stat)

    found = cad_import.find_converter("rvt")

    assert found is not None
    assert found.as_posix() == "/usr/bin/ddc-rvtconverter"


def test_find_converter_returns_none_when_nothing_installed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Probe returns None when neither the real nor legacy path exists."""
    _patch_no_other_paths(monkeypatch)
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path))

    # Force every probe path to look absent.
    monkeypatch.setattr(Path, "exists", lambda _self: False)

    found = cad_import.find_converter("rvt")

    assert found is None


def test_linux_converters_table_uses_no_extension() -> None:
    """The Linux mapping must NOT carry `.exe` suffixes, otherwise the
    probe falls back to the Windows naming and `find_converter()` on
    Linux returns None even when the apt package is installed."""
    for ext, exe in cad_import._LINUX_CONVERTERS.items():
        assert not exe.endswith(".exe"), f"{ext}: {exe} still has .exe suffix"
        assert exe[:1].isupper(), f"{ext}: {exe} expected CapitalCamelCase"


# ── smoke_test_converter() Linux ld.so failure ─────────────────────────


class _FakeProc:
    def __init__(self, returncode: int, stderr: bytes = b""):
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = b""


def _patch_linux_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cad_import.sys, "platform", "linux")


def test_smoke_test_linux_ld_failure_reports_failed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """exit 127 + 'error while loading shared libraries' → failed."""
    _patch_linux_platform(monkeypatch)
    cad_import.invalidate_converter_health()

    fake_exe = tmp_path / "RvtExporter"
    fake_exe.write_bytes(b"\x00" * 2048)
    monkeypatch.setattr(cad_import, "find_converter", lambda _ext: fake_exe)

    stderr = (
        b"RvtExporter: error while loading shared libraries: "
        b"libQt6Core.so.6: cannot open shared object file: No such file or directory\n"
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_a, **_kw: _FakeProc(returncode=127, stderr=stderr),
    )

    health = cad_import.smoke_test_converter("rvt", force=True)

    assert health["status"] == "failed"
    assert "shared library" in health["message"].lower()
    assert "libqt6core" in health["message"].lower()
    assert "reinstall_converter" in health["suggested_actions"]


def test_smoke_test_linux_non_127_treated_as_ok(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Any other Linux exit code = the binary loaded → ok.

    The empty-stdin smoke test triggers a non-zero exit because the
    converter has no real input to parse — that's expected and not
    indicative of a broken install.
    """
    _patch_linux_platform(monkeypatch)
    cad_import.invalidate_converter_health()

    fake_exe = tmp_path / "RvtExporter"
    fake_exe.write_bytes(b"\x00" * 2048)
    monkeypatch.setattr(cad_import, "find_converter", lambda _ext: fake_exe)

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_a, **_kw: _FakeProc(returncode=2, stderr=b"usage: ..."),
    )

    health = cad_import.smoke_test_converter("rvt", force=True)

    assert health["status"] == "ok"
    assert health["suggested_actions"] == []


def test_smoke_test_linux_127_without_marker_treated_as_ok(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """exit 127 alone is NOT a Linux loader failure — it's only a
    failure if `error while loading shared libraries` appears in stderr.
    Other 127 cases (e.g. argv parsing → 'command not found' from a
    wrapper script) shouldn't be misclassified as broken installs.
    """
    _patch_linux_platform(monkeypatch)
    cad_import.invalidate_converter_health()

    fake_exe = tmp_path / "RvtExporter"
    fake_exe.write_bytes(b"\x00" * 2048)
    monkeypatch.setattr(cad_import, "find_converter", lambda _ext: fake_exe)

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_a, **_kw: _FakeProc(returncode=127, stderr=b"unknown option\n"),
    )

    health = cad_import.smoke_test_converter("rvt", force=True)

    assert health["status"] == "ok"


def test_smoke_test_linux_timeout_means_loader_succeeded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """If the binary hangs waiting on stdin, the loader did its job."""
    _patch_linux_platform(monkeypatch)
    cad_import.invalidate_converter_health()

    fake_exe = tmp_path / "RvtExporter"
    fake_exe.write_bytes(b"\x00" * 2048)
    monkeypatch.setattr(cad_import, "find_converter", lambda _ext: fake_exe)

    def raise_timeout(*_a: Any, **_kw: Any) -> _FakeProc:
        raise subprocess.TimeoutExpired(cmd="RvtExporter", timeout=8)

    monkeypatch.setattr(subprocess, "run", raise_timeout)

    health = cad_import.smoke_test_converter("rvt", force=True)

    assert health["status"] == "ok"
