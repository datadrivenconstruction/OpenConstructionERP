"""‌⁠‍Unit tests for ``detect_converter_capabilities`` — the CLI capability
matrix probe added in v4.6.2 to fix the user-reported "arguments were not
expected" failure on older DDC RvtExporter / IfcExporter binaries.

Coverage:
  * Modern marker found in ``--help`` output → both flags enabled.
  * Legacy banner (no markers) → both flags disabled (safe fallback).
  * Probe process never starts → safe fallback.
  * No binary installed at all → ``probed=False`` sentinel.
  * Cache: second probe never re-invokes subprocess.
  * ``invalidate_converter_capabilities`` clears the cache.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.boq import cad_import


@pytest.fixture(autouse=True)
def _reset_caches() -> None:
    """‌⁠‍Module-level caches must be empty at the start of each test so the
    capability matrix doesn't leak between cases. The fixture runs both
    before and after via try/yield."""
    cad_import._CONVERTER_CAPABILITIES.clear()
    yield
    cad_import._CONVERTER_CAPABILITIES.clear()


def _stub_subprocess(
    monkeypatch: pytest.MonkeyPatch,
    *,
    stdout: bytes = b"",
    stderr: bytes = b"",
    returncode: int = 0,
    side_effect: Exception | None = None,
) -> dict[str, int]:
    """‌⁠‍Replace ``subprocess.run`` and return a hit counter so tests can
    assert the cache short-circuits the second probe."""
    import subprocess as _subprocess

    counter = {"calls": 0}

    class _Proc:
        def __init__(self) -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def fake_run(*_args: object, **_kwargs: object) -> _Proc:
        counter["calls"] += 1
        if side_effect is not None:
            raise side_effect
        return _Proc()

    monkeypatch.setattr(_subprocess, "run", fake_run)
    return counter


def _fake_binary(tmp_path: Path, name: str = "RvtExporter") -> Path:
    """‌⁠‍Materialise a non-empty file so ``find_converter`` size guard passes."""
    binary = tmp_path / name
    binary.write_bytes(b"x" * 4096)
    return binary


def test_modern_cli_marker_enables_full_argument_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """‌⁠‍A binary whose ``--help`` mentions ``-no-collada`` is treated as a
    modern CLI: both depth-mode and ``-no-collada`` capabilities flip to
    True so ``_run_ddc`` builds the full v18+ command line."""
    binary = _fake_binary(tmp_path)
    monkeypatch.setattr(cad_import, "find_converter", lambda _ext: binary)
    _stub_subprocess(
        monkeypatch,
        stdout=b"Usage: RvtExporter input output [standard|complete] [-no-collada]\n",
    )

    caps = cad_import.detect_converter_capabilities("rvt")

    assert caps["accepts_depth_mode"] is True
    assert caps["accepts_no_collada_flag"] is True
    assert caps["probed"] is True
    assert caps["version_text"] is not None
    assert "no-collada" in caps["version_text"]


def test_legacy_banner_falls_back_to_bare_invocation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """‌⁠‍A binary whose ``--help`` succeeds but lacks any modern marker is
    treated as legacy — capability flags stay False so the runtime never
    appends ``standard`` or ``-no-collada`` (the user-reported exit-15
    cause)."""
    binary = _fake_binary(tmp_path)
    monkeypatch.setattr(cad_import, "find_converter", lambda _ext: binary)
    _stub_subprocess(monkeypatch, stdout=b"RvtExporter v3.0.0\nUsage: RvtExporter <in> <out>\n")

    caps = cad_import.detect_converter_capabilities("rvt")

    assert caps["accepts_depth_mode"] is False
    assert caps["accepts_no_collada_flag"] is False
    assert caps["probed"] is True


def test_probe_subprocess_never_starts_falls_back_to_legacy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """‌⁠‍If every probe attempt raises (FileNotFoundError / PermissionError /
    timeout), the conservative legacy profile is cached. The conversion
    path is then guaranteed to emit a bare CLI that the user's binary
    actually accepts."""
    binary = _fake_binary(tmp_path)
    monkeypatch.setattr(cad_import, "find_converter", lambda _ext: binary)
    _stub_subprocess(monkeypatch, side_effect=PermissionError("denied"))

    caps = cad_import.detect_converter_capabilities("rvt")

    assert caps["accepts_depth_mode"] is False
    assert caps["accepts_no_collada_flag"] is False
    assert caps["probed"] is True
    assert caps["version_text"] is None


def test_no_binary_installed_returns_unprobed_sentinel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """‌⁠‍With no converter installed, ``probed`` is False so a later install
    triggers a fresh probe instead of reading a stale "old CLI" entry.

    The capability dict gained v18-era keys in task #164 (``accepts_flag_*``,
    ``cli_profile``, ``legacy_positional_input_output``); this test now
    asserts the core-historical contract as a *subset* rather than a
    strict equality, so future capability-key additions don't force a
    test edit just to keep the legacy invariants pinned.
    """
    monkeypatch.setattr(cad_import, "find_converter", lambda _ext: None)

    caps = cad_import.detect_converter_capabilities("rvt")

    # Core contract pinned since v4.6.2:
    assert caps["accepts_depth_mode"] is False
    assert caps["accepts_no_collada_flag"] is False
    assert caps["version_text"] is None
    assert caps["probed"] is False
    # New in task #164: no-binary sentinel should be a distinct profile
    # (``unknown``) so callers can differentiate "binary missing" from
    # "binary present but legacy".
    assert caps["cli_profile"] == cad_import.CLI_PROFILE_UNKNOWN


def test_capability_cache_short_circuits_second_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """‌⁠‍The second probe of the same binary must not spawn a subprocess —
    the cache is keyed by binary path so two extensions sharing a dir
    cost one probe between them."""
    binary = _fake_binary(tmp_path)
    monkeypatch.setattr(cad_import, "find_converter", lambda _ext: binary)
    counter = _stub_subprocess(monkeypatch, stdout=b"complete\n")

    cad_import.detect_converter_capabilities("rvt")
    cad_import.detect_converter_capabilities("rvt")

    assert counter["calls"] == 1, "cache hit should have skipped second probe"


def test_invalidate_capabilities_forces_reprobe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """‌⁠‍Reinstall workflow: after the binary on disk is replaced,
    ``invalidate_converter_capabilities`` must drop the cached entry so
    the next conversion sees the new CLI shape immediately (no service
    restart required)."""
    binary = _fake_binary(tmp_path)
    monkeypatch.setattr(cad_import, "find_converter", lambda _ext: binary)
    counter = _stub_subprocess(monkeypatch, stdout=b"Usage: standard | -no-collada\n")

    cad_import.detect_converter_capabilities("rvt")
    cad_import.invalidate_converter_capabilities("rvt")
    cad_import.detect_converter_capabilities("rvt")

    assert counter["calls"] == 2


def test_invalidate_health_also_drops_capabilities(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """‌⁠‍``invalidate_converter_health`` is called from the install router
    on every successful install — it must drop the capability cache in
    lock-step so an upgraded binary doesn't keep using the old CLI
    profile. Otherwise the v4.6.2 fix would silently regress whenever
    the same Python process processes both an old and a new binary."""
    binary = _fake_binary(tmp_path)
    monkeypatch.setattr(cad_import, "find_converter", lambda _ext: binary)
    counter = _stub_subprocess(monkeypatch, stdout=b"Usage: standard | -no-collada\n")

    cad_import.detect_converter_capabilities("rvt")
    cad_import.invalidate_converter_health("rvt")
    cad_import.detect_converter_capabilities("rvt")

    assert counter["calls"] == 2
