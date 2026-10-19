"""What the converter installer checks, and what it leaves behind.

The converters are the portable ``.zip`` packages of the DDC 2026.10 release.
An install is: read ``SHA256SUMS.txt``, download one asset, check its digest,
unpack it next to the old folder, check the executable is a PE image, swap the
folders. These tests run the real installer, the real archive reader and the
real hash check against a synthetic package; only the two network calls are
replaced. No network, no database, no converter binary.
"""

from __future__ import annotations

import hashlib
import io
import sys
import zipfile
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from app.core import converter_package
from app.core.converter_source import (
    INSTALL_STAMP_NAME,
    PACKAGES,
    command_prefix,
    package_exe,
    parse_sha256sums,
)
from app.modules.boq import cad_import
from app.modules.takeoff import router

_X64 = 0x8664
_X86 = 0x014C

_NOT_A_PE_IMAGE = b"placeholder text, not a binary and not a licence\n"


def _pe_bytes(machine: int = _X64, *, pe_off: int = 0x80, size: int = 4096) -> bytes:
    """Smallest buffer that parses as a PE image for the given machine.

    The DOS stub carries real ``0x0A`` bytes so that a CRLF mangle of this
    buffer actually shifts the header, which is what the corrupt-download case
    needs.
    """
    buf = bytearray(b"MZ" + b"\x00" * (0x40 - 2))
    buf[0x3C:0x40] = pe_off.to_bytes(4, "little")
    stub = b"This program cannot be run in DOS mode.\x0d\x0a\x0a$"
    buf += stub + b"\x00" * (pe_off - len(buf) - len(stub))
    buf += b"PE\x00\x00" + machine.to_bytes(2, "little")
    buf += b"\x00" * max(0, size - len(buf))
    return bytes(buf)


# ── Reading the PE header ─────────────────────────────────────────────────


def test_the_machine_field_of_a_64_bit_image_is_read(tmp_path: Path) -> None:
    path = tmp_path / "RVTconverter.exe"
    path.write_bytes(_pe_bytes(_X64))
    assert router._read_pe_machine(path) == (_X64, None)


def test_a_file_that_is_not_a_binary_is_reported_as_neither(tmp_path: Path) -> None:
    path = tmp_path / "LICENSE"
    path.write_bytes(_NOT_A_PE_IMAGE)
    assert router._read_pe_machine(path) == (None, None)


def test_a_mangled_image_reports_a_reason_instead_of_a_machine(tmp_path: Path) -> None:
    """The WinError 216 corruption: every 0x0A rewritten as 0x0D 0x0A."""
    path = tmp_path / "python.exe"
    path.write_bytes(_pe_bytes(_X64).replace(b"\x0a", b"\x0d\x0a"))
    machine, problem = router._read_pe_machine(path)
    assert machine is None
    assert problem is not None and "PE signature" in problem


def test_the_structural_gate_reports_structure_only(tmp_path: Path) -> None:
    good = tmp_path / "dwg2excel.exe"
    good.write_bytes(_pe_bytes(_X64))
    assert router._verify_pe_executable(good) is None

    not_a_binary = tmp_path / "NotABinary.exe"
    not_a_binary.write_bytes(b"PK\x03\x04" + b"\x00" * 200)
    reason = router._verify_pe_executable(not_a_binary)
    assert reason is not None and "MZ" in reason


# ── The package: digest and archive ───────────────────────────────────────


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_a_digest_that_does_not_match_is_refused(tmp_path: Path) -> None:
    archive = tmp_path / "pkg.zip"
    archive.write_bytes(b"not what the release published")
    with pytest.raises(converter_package.PackageError, match="SHA-256 mismatch"):
        converter_package.verify_sha256(archive, "0" * 64)


def test_a_matching_digest_passes(tmp_path: Path) -> None:
    archive = tmp_path / "pkg.zip"
    archive.write_bytes(b"payload")
    converter_package.verify_sha256(archive, hashlib.sha256(b"payload").hexdigest().upper())


def test_the_wrapper_folder_of_a_package_is_stripped(tmp_path: Path) -> None:
    """The DWG and RVT zips have one top-level folder, the IFC zip has none."""
    pkg = PACKAGES["dwg"]
    archive = tmp_path / "dwg.zip"
    archive.write_bytes(
        _zip_bytes(
            {
                "DWG-to-Excel-0.4.1/cli/dwg2excel.exe": _pe_bytes(),
                "DWG-to-Excel-0.4.1/licenses/NOTICE.txt": b"notice",
                "DWG-to-Excel-0.4.1/DWG to Excel.exe": _pe_bytes(),
                "DWG-to-Excel-0.4.1/viewer/index.html": b"<html>",
            }
        )
    )
    dest = tmp_path / "out"
    converter_package.extract_package(archive, dest, pkg)

    assert (dest / "cli" / "dwg2excel.exe").is_file()
    assert (dest / "licenses" / "NOTICE.txt").is_file()
    # Only the command line and the licences are installed, not the desktop app.
    assert not (dest / "DWG to Excel.exe").exists()
    assert not (dest / "viewer").exists()


def test_a_package_without_a_wrapper_folder_is_unpacked_as_it_is(tmp_path: Path) -> None:
    pkg = PACKAGES["ifc"]
    archive = tmp_path / "ifc.zip"
    archive.write_bytes(
        _zip_bytes(
            {
                "IFC to Excel.exe": b"x",
                "runtime/python.exe": _pe_bytes(),
                "sources/ifc-excel/converter.py": b"print('hi')",
            }
        )
    )
    dest = tmp_path / "out"
    converter_package.extract_package(archive, dest, pkg)
    assert (dest / "runtime" / "python.exe").is_file()
    assert (dest / "sources" / "ifc-excel" / "converter.py").is_file()


@pytest.mark.parametrize("evil", ["../escape.txt", "cli/../../escape.txt", "/abs/escape.txt", "C:/Windows/escape.txt"])
def test_an_entry_that_climbs_out_of_the_folder_is_refused(tmp_path: Path, evil: str) -> None:
    archive = tmp_path / "evil.zip"
    archive.write_bytes(_zip_bytes({"cli/dwg2excel.exe": _pe_bytes(), evil: b"pwned"}))
    dest = tmp_path / "out"
    with pytest.raises(converter_package.PackageError):
        converter_package.extract_package(archive, dest, replace(PACKAGES["dwg"], include=None))
    assert not (tmp_path / "escape.txt").exists()


def test_a_file_that_is_not_a_zip_is_reported(tmp_path: Path) -> None:
    archive = tmp_path / "bad.zip"
    archive.write_bytes(b"this is html, not a zip")
    with pytest.raises(converter_package.PackageError, match="not a valid zip"):
        converter_package.extract_package(archive, tmp_path / "out", PACKAGES["dwg"])


def test_the_checksum_file_is_parsed_in_both_layouts() -> None:
    a, b = "a" * 64, "b" * 64
    sums = parse_sha256sums(f"{a} *one.zip\n{b}  two.zip\nnot a line\n{'z' * 64}  bad.zip\n")
    assert sums == {"one.zip": a, "two.zip": b}


def test_the_ifc_package_is_run_through_the_bundled_python(tmp_path: Path) -> None:
    exe = tmp_path / "ifc_windows" / "runtime" / "python.exe"
    assert command_prefix("ifc", exe) == [
        str(exe),
        str(tmp_path / "ifc_windows" / "sources" / "ifc-excel" / "converter.py"),
    ]
    rvt = tmp_path / "rvt_windows" / "cli" / "RVTconverter.exe"
    assert command_prefix("rvt", rvt) == [str(rvt)]


# ── A whole install, with the network replaced ────────────────────────────


def _package_files(machine: int = _X64) -> dict[str, bytes]:
    return {
        "DWG-to-Excel-0.4.1/cli/dwg2excel.exe": _pe_bytes(machine),
        "DWG-to-Excel-0.4.1/licenses/NOTICE.txt": b"notice",
    }


def _run_install(
    monkeypatch: pytest.MonkeyPatch,
    install_dir: Path,
    *,
    archive_bytes: bytes | None = None,
    published_digest: str | None = None,
    clean: bool = False,
    downloads: list[str] | None = None,
) -> Path:
    """Run the real installer with the checksum file and the transport stubbed."""
    data = archive_bytes if archive_bytes is not None else _zip_bytes(_package_files())
    digest = hashlib.sha256(data).hexdigest()
    pkg = replace(PACKAGES["dwg"], sha256=digest, size_bytes=len(data))
    monkeypatch.setitem(PACKAGES, "dwg", pkg)
    monkeypatch.setattr(router, "PACKAGES", PACKAGES)
    monkeypatch.setattr(router, "_CONVERTER_INSTALL_DIR", install_dir)
    monkeypatch.setattr(router, "_CONVERTER_CACHE_DIR", install_dir / "cache")
    monkeypatch.setattr(router, "_fetch_release_checksums", lambda _repo, _tag: {pkg.asset: published_digest or digest})

    def _fake_download(url: str, target: Path) -> int:
        if downloads is not None:
            downloads.append(url)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return len(data)

    monkeypatch.setattr(router, "_download_one_file", _fake_download)
    return router._download_converter_files_windows("dwg", clean=clean)


def test_an_install_unpacks_the_package_and_stamps_it(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    downloads: list[str] = []
    exe = _run_install(monkeypatch, tmp_path, downloads=downloads)

    dest = tmp_path / "dwg_windows"
    assert exe == package_exe(dest.resolve(), "dwg")
    assert exe.is_file()
    stamp = converter_package.read_stamp(dest)
    assert stamp is not None and stamp["asset"] == PACKAGES["dwg"].asset and stamp["sha256"] == PACKAGES["dwg"].sha256
    # The download came from the release, by asset name.
    assert downloads == [
        f"https://github.com/datadrivenconstruction/cad2data-Revit-IFC-DWG/releases/download/v2026.10.0/{PACKAGES['dwg'].asset}"
    ]
    # No staging folder or half-downloaded archive is left behind.
    assert [p.name for p in tmp_path.iterdir() if p.name not in {"dwg_windows", "cache"}] == []
    assert list((tmp_path / "cache").glob("*.part")) == []


def test_a_package_that_is_not_the_published_one_is_not_installed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The release page and the download disagree: refuse, and leave nothing."""
    data = _zip_bytes(_package_files())
    pkg = replace(PACKAGES["dwg"], sha256=hashlib.sha256(data).hexdigest())
    monkeypatch.setitem(PACKAGES, "dwg", pkg)
    monkeypatch.setattr(router, "_CONVERTER_INSTALL_DIR", tmp_path)
    monkeypatch.setattr(router, "_CONVERTER_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(router, "_fetch_release_checksums", lambda _r, _t: {pkg.asset: pkg.sha256})

    def _tampered(url: str, target: Path) -> int:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"a different file entirely")
        return 25

    monkeypatch.setattr(router, "_download_one_file", _tampered)

    with pytest.raises(RuntimeError, match="SHA-256 mismatch"):
        router._download_converter_files_windows("dwg")
    assert not (tmp_path / "dwg_windows").exists()
    assert list((tmp_path / "cache").glob("*.part")) == []


def test_a_release_page_that_disagrees_with_the_pin_is_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """For the pinned tag the published digest must equal the one committed here."""
    monkeypatch.setattr(router, "_CONVERTER_INSTALL_DIR", tmp_path)
    monkeypatch.setattr(router, "_fetch_release_checksums", lambda _r, _t: {PACKAGES["dwg"].asset: "f" * 64})
    monkeypatch.setattr(router, "_download_one_file", lambda *_a: pytest.fail("must not download"))

    with pytest.raises(RuntimeError, match="Refusing to install"):
        router._download_converter_files_windows("dwg")


def test_a_32_bit_or_mangled_executable_fails_the_install_and_removes_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mangled = _zip_bytes({"cli/dwg2excel.exe": _pe_bytes().replace(b"\x0a", b"\x0d\x0a")})
    with pytest.raises(RuntimeError, match="install verification failed"):
        _run_install(monkeypatch, tmp_path, archive_bytes=mangled)
    assert not (tmp_path / "dwg_windows").exists()


def test_an_old_generation_folder_is_replaced_not_merged(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A folder of the retired 18.x converters carries no stamp; none of it survives."""
    dest = tmp_path / "dwg_windows"
    old = dest / "DwgExporter.exe"
    old.parent.mkdir(parents=True)
    old.write_bytes(_pe_bytes())
    (dest / "Qt6Core.dll").write_bytes(_pe_bytes())

    _run_install(monkeypatch, tmp_path)

    assert not old.exists()
    assert not (dest / "Qt6Core.dll").exists()
    assert (dest / "cli" / "dwg2excel.exe").is_file()


def test_the_pinned_package_already_installed_is_not_downloaded_again(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    downloads: list[str] = []
    _run_install(monkeypatch, tmp_path, downloads=downloads)
    assert len(downloads) == 1

    _run_install(monkeypatch, tmp_path, downloads=downloads)
    assert len(downloads) == 1, "a current install has nothing to fetch"

    _run_install(monkeypatch, tmp_path, downloads=downloads, clean=True)
    assert len(downloads) == 2, "the Update button's force install replaces it"


def test_a_leftover_that_cannot_be_deleted_fails_the_install_and_says_which(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Windows keeps a handle open; ``rmtree(ignore_errors=True)`` would hide it."""
    dest = tmp_path / "dwg_windows"
    held = dest / "held_open_by_something.dll"
    held.parent.mkdir(parents=True)
    held.write_bytes(_pe_bytes())

    import shutil

    real_rmtree = shutil.rmtree

    def _refuse(path: Any, *args: Any, **kwargs: Any) -> None:
        if Path(path).resolve() == dest.resolve():
            return  # silently leaves everything in place, as a locked file does
        real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", _refuse)

    with pytest.raises(RuntimeError, match="held_open_by_something.dll"):
        _run_install(monkeypatch, tmp_path)


# ── force, from the endpoint down ─────────────────────────────────────────


async def test_the_update_button_asks_for_a_clean_download(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, bool] = {}

    def _recorder(_converter_id: str, *, clean: bool = False) -> Path:
        seen["clean"] = clean
        raise RuntimeError("stubbed - the flag is what this test reads")

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(router, "_download_converter_files_windows", _recorder)

    result = await router._install_converter_impl("dwg", True, None)

    assert seen["clean"] is True
    assert result["installed"] is False


async def test_an_ordinary_install_does_not_ask_for_a_clean_download(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, bool] = {}

    def _recorder(_converter_id: str, *, clean: bool = False) -> Path:
        seen["clean"] = clean
        raise RuntimeError("stubbed - the flag is what this test reads")

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(router, "_download_converter_files_windows", _recorder)

    await router._install_converter_impl("dwg", False, None)

    assert seen["clean"] is False


# ── Resolution, once a partial folder is possible ─────────────────────────


def _isolate_search(monkeypatch: pytest.MonkeyPatch, home: Path, *paths: Path) -> None:
    """Point resolution at the given folders and nothing else."""
    monkeypatch.setattr(cad_import, "CONVERTER_SEARCH_PATHS", list(paths))
    monkeypatch.setattr(cad_import, "_find_ddc_toolkit_bin", lambda: None)
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: home))
    monkeypatch.delenv("OPENESTIMATOR_CONVERTERS_DIR", raising=False)
    monkeypatch.delenv("OE_BUNDLED_CONVERTERS_DIR", raising=False)


def _ifc_folder(root: Path, name: str, *, complete: bool) -> Path:
    folder = root / name
    (folder / "runtime").mkdir(parents=True)
    (folder / "runtime" / "python.exe").write_bytes(_pe_bytes(size=4096))
    if complete:
        script = folder / "sources" / "ifc-excel" / "converter.py"
        script.parent.mkdir(parents=True)
        script.write_text("print('converter')\n", encoding="utf-8")
    return folder


def test_a_complete_folder_wins_over_a_partial_one_earlier_in_the_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A partial folder used to win on position alone."""
    partial = _ifc_folder(tmp_path, "partial", complete=False)
    complete = _ifc_folder(tmp_path, "complete", complete=True)
    _isolate_search(monkeypatch, tmp_path / "home", partial, complete)

    assert cad_import.find_converter("ifc") == complete / "runtime" / "python.exe"


def test_a_partial_folder_is_still_returned_when_it_is_all_there_is(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    partial = _ifc_folder(tmp_path, "partial", complete=False)
    _isolate_search(monkeypatch, tmp_path / "home", partial)

    assert cad_import.find_converter("ifc") == partial / "runtime" / "python.exe"
    assert cad_import.missing_companion_files(partial / "runtime" / "python.exe") == ["sources/ifc-excel/converter.py"]


def test_the_retired_18x_executables_are_not_found(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Their command line is not the one the platform speaks any more."""
    old = tmp_path / "old"
    old.mkdir()
    for name in ("RvtExporter.exe", "IfcExporter.exe", "DwgExporter.exe", "DgnExporter.exe"):
        (old / name).write_bytes(_pe_bytes(size=4096))
    _isolate_search(monkeypatch, tmp_path / "home", old)

    for fmt in ("rvt", "ifc", "dwg", "dgn"):
        assert cad_import.find_converter(fmt) is None


# ── The install endpoint, over the folder the health check calls broken ───


async def _ask_to_install(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Call the endpoint far enough to learn whether it short-circuited.

    The platform is forced to one with no converter build, so the answer comes
    back synchronously and nothing is downloaded or spawned.
    """
    monkeypatch.setattr(sys, "platform", "linux")
    return await router.install_converter("ifc", None, "test-user", force=False)  # type: ignore[arg-type]


async def test_a_partial_folder_is_not_reported_as_already_installed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    partial = _ifc_folder(tmp_path, "ifc_windows", complete=False)
    _isolate_search(monkeypatch, tmp_path / "home", partial)

    result = await _ask_to_install(monkeypatch)

    assert not result.get("already_installed")
    assert result.get("installed") is False


async def test_a_complete_folder_is_still_reported_as_already_installed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    complete = _ifc_folder(tmp_path, "ifc_windows", complete=True)
    _isolate_search(monkeypatch, tmp_path / "home", complete)

    result = await _ask_to_install(monkeypatch)

    assert result["already_installed"] is True
    assert result["path"] == str(complete / "runtime" / "python.exe")


async def test_off_windows_the_install_endpoint_says_there_is_no_build(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolate_search(monkeypatch, tmp_path / "home")
    result = await _ask_to_install(monkeypatch)
    assert result["platform_unsupported"] is True
    assert result["installed"] is False


def test_the_stamp_name_is_the_one_the_workflow_writes() -> None:
    assert INSTALL_STAMP_NAME == ".ddc-package.json"
