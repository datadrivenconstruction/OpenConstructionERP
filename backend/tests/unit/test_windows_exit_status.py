"""A converter that dies on Windows must be explained, never shown as a bare negative number.

Users reported the RVT converter failing with ``-1073741674`` on every file, also
after reinstalling the Visual C++ runtime. That number is NTSTATUS 0xC0000096 read
as a signed 32-bit int. These tests pin the mapping from the numbers people
actually see to a plain sentence with a fix, and the runtime pre-flight.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core import windows_exit_status as wes


@pytest.mark.parametrize(
    ("code", "hex_text", "cause"),
    [
        (-1073741674, "0xC0000096", "blocked_instruction"),
        (3221225622, "0xC0000096", "blocked_instruction"),
        (-1073741515, "0xC0000135", "runtime_missing"),
        (-1073741819, "0xC0000005", "native_crash"),
        (-1073741795, "0xC000001D", "cpu_unsupported"),
        (-1073740791, "0xC0000409", "native_crash"),
        (-1073741801, "0xC0000017", "out_of_memory"),
        (-1073741701, "0xC000007B", "damaged_install"),
        (-2147450730, "0x80008096", "dotnet_missing"),
    ],
)
def test_known_windows_codes_have_a_cause_and_a_fix(code: int, hex_text: str, cause: str) -> None:
    info = wes.describe_exit_code(code)
    assert info is not None
    assert info.hex == hex_text
    assert info.cause == cause
    assert info.message
    assert info.fix


def test_privileged_instruction_does_not_send_the_user_back_to_vc_redist() -> None:
    """The reporters had already reinstalled the runtime; repeating that advice is no answer."""
    info = wes.describe_exit_code(-1073741674)
    assert info is not None
    assert "is not a missing runtime" in info.message
    assert "install_vc_redist" not in info.actions


def test_missing_dll_points_at_the_runtime() -> None:
    info = wes.describe_exit_code(-1073741515)
    assert info is not None
    assert "install_vc_redist" in info.actions
    assert "Visual C++" in info.fix


@pytest.mark.parametrize("code", [0, 1, 2, 15, None])
def test_ordinary_codes_are_not_windows_statuses(code: int | None) -> None:
    assert wes.describe_exit_code(code) is None


def test_plain_message_never_shows_a_bare_negative_number() -> None:
    known = wes.plain_exit_message(-1073741674, "The RVT converter")
    assert "-1073741674" not in known
    assert "0xC0000096" in known
    assert known.startswith("The RVT converter")

    unknown = wes.plain_exit_message(-1073741000, "The converter")
    assert "-1073741000" not in unknown
    assert "0xC0000338" in unknown
    assert "stopped by Windows" in unknown

    ordinary = wes.plain_exit_message(2, "The converter")
    assert ordinary == "The converter stopped with error code 2."


def test_runtime_preflight_accepts_a_package_that_carries_its_own_runtime(tmp_path: Path) -> None:
    exe_dir = tmp_path / "conv"
    exe_dir.mkdir()
    for name in wes.VC_RUNTIME_DLLS:
        (exe_dir / name).write_bytes(b"x")
    empty_system = tmp_path / "system32"
    empty_system.mkdir()
    assert wes.missing_vc_runtime(exe_dir, system_dir=empty_system) == []


def test_runtime_preflight_accepts_the_system_runtime(tmp_path: Path) -> None:
    exe_dir = tmp_path / "conv"
    exe_dir.mkdir()
    system = tmp_path / "system32"
    system.mkdir()
    for name in wes.VC_RUNTIME_DLLS:
        (system / name).write_bytes(b"x")
    assert wes.missing_vc_runtime(exe_dir, system_dir=system) == []


def test_runtime_preflight_names_what_neither_place_has(tmp_path: Path) -> None:
    exe_dir = tmp_path / "conv"
    exe_dir.mkdir()
    (exe_dir / "vcruntime140.dll").write_bytes(b"x")
    system = tmp_path / "system32"
    system.mkdir()
    (system / "msvcp140.dll").write_bytes(b"x")
    assert wes.missing_vc_runtime(exe_dir, system_dir=system) == ["vcruntime140_1.dll"]


def test_runtime_preflight_is_silent_off_windows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wes.sys, "platform", "linux")
    assert wes.missing_vc_runtime(tmp_path) == []


def test_runtime_imports_are_read_from_the_image(tmp_path: Path) -> None:
    exe = tmp_path / "conv.exe"
    exe.write_bytes(b"MZ" + b"\x00" * 64 + b"KERNEL32.dll\x00VCRUNTIME140.dll\x00MSVCP140.dll\x00")
    assert wes.vc_runtime_imports(exe) == ("vcruntime140.dll", "msvcp140.dll")


def test_only_the_imported_runtime_is_required(tmp_path: Path) -> None:
    """A Python-based package imports vcruntime140 only; a missing msvcp140 must not fail it."""
    exe_dir = tmp_path / "conv"
    exe_dir.mkdir()
    (exe_dir / "vcruntime140.dll").write_bytes(b"x")
    system = tmp_path / "system32"
    system.mkdir()
    assert wes.missing_vc_runtime(exe_dir, system_dir=system, required=("vcruntime140.dll",)) == []
