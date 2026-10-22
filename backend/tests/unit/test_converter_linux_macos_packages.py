# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The Linux and macOS converter packages: pins, host selection, install, command lines.

The release carries one ``.tar.gz`` per tool, OS and architecture. These tests
run the real installer and the real archive reader against synthetic packages;
only the checksum file and the transport are replaced. No network, no binary.
"""

from __future__ import annotations

import hashlib
import io
import re
import stat
import sys
import tarfile
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from app.core import converter_package, converter_source
from app.core.converter_source import (
    PACKAGES,
    PLATFORM_PACKAGES,
    POSIX_CHECKSUMS_ASSET,
    POSIX_CONVERTER_TAG,
    POSIX_KEYS,
    WINDOWS_KEY,
    command_prefix,
    host_packages,
    host_platform_key,
    install_dir_name,
)
from app.modules.boq import cad_import, ddc_runner
from app.modules.takeoff import router

_ELF = b"\x7fELF" + b"\x02\x01\x01" + b"\x00" * 4089
_MACHO = b"\xcf\xfa\xed\xfe" + b"\x00" * 4092


def _on_host(monkeypatch: pytest.MonkeyPatch, plat: str, machine: str) -> None:
    monkeypatch.setattr(sys, "platform", plat)
    monkeypatch.setattr(converter_source.platform, "machine", lambda: machine)


# ── Pins ──────────────────────────────────────────────────────────────────


def test_every_linux_and_macos_host_has_all_three_formats() -> None:
    assert set(POSIX_KEYS) == {"linux-x64", "linux-arm64", "macos-x64", "macos-arm64"}
    assert set(PLATFORM_PACKAGES) == {WINDOWS_KEY, *POSIX_KEYS}
    assert PLATFORM_PACKAGES[WINDOWS_KEY] is PACKAGES
    for key in POSIX_KEYS:
        assert set(PLATFORM_PACKAGES[key]) == {"rvt", "ifc", "dwg"}


@pytest.mark.parametrize("key", POSIX_KEYS)
def test_a_posix_package_names_its_release_asset_and_pins_its_digest(key: str) -> None:
    tools = {"rvt": ("rvt-decode", "2.0.1"), "ifc": ("ifc2excel", "2.0.1"), "dwg": ("dwg2excel", "2.0.0")}
    for fmt, pkg in PLATFORM_PACKAGES[key].items():
        tool, version = tools[fmt]
        assert pkg.asset == f"{tool}-{version}-{key}.tar.gz"
        assert pkg.version == version
        assert pkg.exe_rel == tool
        assert pkg.script_rel is None
        assert re.fullmatch(r"[0-9a-f]{64}", pkg.sha256)
        assert pkg.size_bytes > 1_000_000
        assert pkg.archive_format == "tar.gz"
        assert pkg.checksums_asset == POSIX_CHECKSUMS_ASSET == "SHA256SUMS.txt"
        assert pkg.release_tag == POSIX_CONVERTER_TAG == "v2026.10.1"
        assert pkg.platform_key == key


def test_the_pins_are_the_published_digests() -> None:
    """Spot checks against ``SHA256SUMS.txt`` of v2026.10.1."""
    by_asset = {p.asset: p.sha256 for k in POSIX_KEYS for p in PLATFORM_PACKAGES[k].values()}
    assert len(set(by_asset.values())) == 12
    assert by_asset["rvt-decode-2.0.1-linux-x64.tar.gz"] == (
        "fc176c46e27da129bec57783c0bfa9c25c20d4d8d603daf43d97bdbebed39550"
    )
    assert by_asset["ifc2excel-2.0.1-macos-arm64.tar.gz"] == (
        "4ebe7eed52898277f2c20a351856d9803774036202dd7b76ee21179d7f5e585b"
    )
    assert by_asset["dwg2excel-2.0.0-linux-arm64.tar.gz"] == (
        "075df8e5c05de2a6b992029b83c5130097e91f2bbea5031f571892f4e1396fc5"
    )


def test_the_windows_packages_did_not_move() -> None:
    assert PACKAGES["rvt"].asset == "DDC-RVT-Converter-2.0.1-portable.zip"
    assert PACKAGES["rvt"].archive_format == "zip"
    assert PACKAGES["rvt"].checksums_asset == "SHA256SUMS.txt"
    assert PACKAGES["ifc"].exe_rel == "runtime/python.exe"


# ── Host selection ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("plat", "machine", "key"),
    [
        ("win32", "AMD64", "windows-x64"),
        ("win32", "ARM64", "windows-x64"),
        ("linux", "x86_64", "linux-x64"),
        ("linux", "aarch64", "linux-arm64"),
        ("darwin", "x86_64", "macos-x64"),
        ("darwin", "arm64", "macos-arm64"),
        ("linux", "riscv64", None),
        ("linux", "armv7l", None),
        ("freebsd14", "amd64", None),
    ],
)
def test_the_host_key_follows_os_and_machine(plat: str, machine: str, key: str | None) -> None:
    assert host_platform_key(plat, machine) == key
    assert (key in PLATFORM_PACKAGES) is (key is not None)
    if key is not None:
        assert host_packages(key) is PLATFORM_PACKAGES[key]


def test_the_install_folder_keeps_the_windows_name() -> None:
    assert install_dir_name("rvt", WINDOWS_KEY) == "rvt_windows"
    assert install_dir_name("rvt", "linux-arm64") == "rvt_linux-arm64"


def test_a_linux_host_is_supported_and_an_unknown_one_is_not(monkeypatch: pytest.MonkeyPatch) -> None:
    _on_host(monkeypatch, "linux", "aarch64")
    assert cad_import.converter_supported_here() is True
    _on_host(monkeypatch, "sunos5", "i86pc")
    assert cad_import.converter_supported_here() is False


# ── Command lines ─────────────────────────────────────────────────────────


def test_the_linux_and_macos_command_lines(tmp_path: Path) -> None:
    src = tmp_path / "in.bin"
    out = tmp_path / "out"
    rvt = tmp_path / "rvt_linux-x64" / "rvt-decode"
    ifc = tmp_path / "ifc_macos-arm64" / "ifc2excel"
    dwg = tmp_path / "dwg_linux-arm64" / "dwg2excel"
    assert ddc_runner.build_command("rvt", rvt, src, out) == [
        str(rvt),
        "native-graph",
        str(src.resolve()),
        "--out",
        str(out),
        "--ifc",
    ]
    assert ddc_runner.build_command("ifc", ifc, src, out) == [
        str(ifc),
        str(src.resolve()),
        "--output",
        str(out),
        "--raw-tables",
    ]
    assert ddc_runner.build_command("dwg", dwg, src, out, timeout=900) == [
        str(dwg),
        str(src.resolve()),
        "-o",
        str(out),
        "--json",
        "--no-svg",
        "--timeout",
        "885",
    ]
    assert command_prefix("ifc", ifc) == [str(ifc)]


def test_the_windows_command_lines_are_unchanged(tmp_path: Path) -> None:
    src = tmp_path / "in.rvt"
    out = tmp_path / "out"
    rvt = tmp_path / "rvt_windows" / "cli" / "RVTconverter.exe"
    assert ddc_runner.build_command("rvt", rvt, src, out) == [str(rvt), str(src.resolve()), "-o", str(out), "--ifc"]
    py = tmp_path / "ifc_windows" / "runtime" / "python.exe"
    assert ddc_runner.build_command("ifc", py, src, out)[2:] == [str(src.resolve()), "--output", str(out), "--glb"]


def test_the_native_graph_output_is_collected_like_the_windows_one(tmp_path: Path) -> None:
    folder = tmp_path / "m.converted"
    folder.mkdir()
    for name in ("native_graph.glb", "native_graph.ifc", "report.json"):
        (folder / name).write_bytes(b"x")
    run = ddc_runner.ConverterRun(fmt="rvt", command=[], returncode=0)
    ddc_runner._collect_outputs(run, folder, "m")
    assert set(run.outputs) == {"glb", "ifc", "report"}
    assert run.ok


# ── Resolution ────────────────────────────────────────────────────────────


def _installed(home: Path, fmt: str, key: str) -> Path:
    pkg = PLATFORM_PACKAGES[key][fmt]
    folder = home / ".openestimator" / "converters" / install_dir_name(fmt, key)
    folder.mkdir(parents=True)
    exe = folder / pkg.exe_rel
    exe.write_bytes(_ELF)
    for companion in pkg.companions:
        (folder / companion).write_text("{}", encoding="utf-8")
    converter_package.write_stamp(folder, pkg, tag="v2026.10.0", repo="o/r")
    return exe


def _isolate(monkeypatch: pytest.MonkeyPatch, home: Path) -> None:
    monkeypatch.setattr(cad_import, "CONVERTER_SEARCH_PATHS", [])
    monkeypatch.setattr(cad_import, "_find_ddc_toolkit_bin", lambda: None)
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: home))
    monkeypatch.delenv("OPENESTIMATOR_CONVERTERS_DIR", raising=False)
    monkeypatch.delenv("OE_BUNDLED_CONVERTERS_DIR", raising=False)


@pytest.mark.parametrize("fmt", ["rvt", "ifc", "dwg"])
def test_a_linux_install_is_found_and_reports_its_version(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fmt: str
) -> None:
    _on_host(monkeypatch, "linux", "aarch64")
    _isolate(monkeypatch, tmp_path)
    exe = _installed(tmp_path, fmt, "linux-arm64")

    assert cad_import.find_converter(fmt) == exe
    assert cad_import.missing_companion_files(exe) == []
    assert cad_import._install_root_of(exe) == exe.parent
    assert cad_import.detect_converter_version(fmt)["version"] == PLATFORM_PACKAGES["linux-arm64"][fmt].version


def test_a_linux_folder_without_its_companion_is_partial(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _on_host(monkeypatch, "linux", "x86_64")
    _isolate(monkeypatch, tmp_path)
    exe = _installed(tmp_path, "dwg", "linux-x64")
    (exe.parent / "MANIFEST.json").unlink()
    assert cad_import.missing_companion_files(exe) == ["MANIFEST.json"]


def test_a_package_of_another_architecture_is_not_found(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _on_host(monkeypatch, "linux", "x86_64")
    _isolate(monkeypatch, tmp_path)
    _installed(tmp_path, "rvt", "linux-arm64")
    assert cad_import.find_converter("rvt") is None


# ── Archive ───────────────────────────────────────────────────────────────


def _tar_bytes(entries: dict[str, bytes], *, modes: dict[str, int] | None = None, link: str | None = None) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = (modes or {}).get(name, 0o644)
            tf.addfile(info, io.BytesIO(data))
        if link:
            info = tarfile.TarInfo(link)
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            tf.addfile(info)
    return buf.getvalue()


def _rvt_tar(key: str, exe: bytes = _ELF, exe_mode: int = 0o755) -> bytes:
    top = f"rvt-decode-2.0.1-{key}"
    return _tar_bytes(
        {f"{top}/rvt-decode": exe, f"{top}/BUILD_INFO.json": b"{}", f"{top}/licenses/NOTICE.txt": b"n"},
        modes={f"{top}/rvt-decode": exe_mode},
    )


def test_a_tar_package_is_unpacked_without_its_wrapper_folder(tmp_path: Path) -> None:
    archive = tmp_path / "p.tar.gz"
    archive.write_bytes(_rvt_tar("linux-x64"))
    dest = tmp_path / "dest"
    n = converter_package.extract_package(archive, dest, PLATFORM_PACKAGES["linux-x64"]["rvt"])
    assert n == 3
    assert (dest / "rvt-decode").read_bytes() == _ELF
    assert (dest / "licenses" / "NOTICE.txt").is_file()
    if sys.platform != "win32":
        assert stat.S_IMODE((dest / "rvt-decode").stat().st_mode) == 0o755
        assert stat.S_IMODE((dest / "BUILD_INFO.json").stat().st_mode) == 0o644


@pytest.mark.parametrize("evil", ["../escape", "top/../../escape", "/abs/escape"])
def test_a_tar_entry_that_climbs_out_is_refused(tmp_path: Path, evil: str) -> None:
    archive = tmp_path / "p.tar.gz"
    archive.write_bytes(_tar_bytes({evil: b"x", "top/rvt-decode": _ELF}))
    with pytest.raises(converter_package.PackageError, match="Refused"):
        converter_package.extract_package(archive, tmp_path / "dest", PLATFORM_PACKAGES["linux-x64"]["rvt"])
    assert not (tmp_path / "escape").exists()


def test_a_tar_link_is_refused(tmp_path: Path) -> None:
    archive = tmp_path / "p.tar.gz"
    archive.write_bytes(_tar_bytes({"top/rvt-decode": _ELF}, link="top/passwd"))
    with pytest.raises(converter_package.PackageError, match="link"):
        converter_package.extract_package(archive, tmp_path / "dest", PLATFORM_PACKAGES["linux-x64"]["rvt"])


def test_a_broken_tar_is_a_package_error(tmp_path: Path) -> None:
    archive = tmp_path / "p.tar.gz"
    archive.write_bytes(b"not gzip")
    with pytest.raises(converter_package.PackageError):
        converter_package.extract_package(archive, tmp_path / "dest", PLATFORM_PACKAGES["linux-x64"]["rvt"])


# ── The installer, with the network replaced ──────────────────────────────


def _install(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, key: str, data: bytes, *, seen: dict[str, Any] | None = None
) -> Path:
    digest = hashlib.sha256(data).hexdigest()
    packages = PLATFORM_PACKAGES[key]
    pkg = replace(packages["rvt"], sha256=digest, size_bytes=len(data))
    monkeypatch.setitem(packages, "rvt", pkg)
    monkeypatch.setattr(router, "_CONVERTER_INSTALL_DIR", tmp_path)
    monkeypatch.setattr(router, "_CONVERTER_CACHE_DIR", tmp_path / "cache")
    record = seen if seen is not None else {}

    def _sums(_repo: str, _tag: str, asset: str = "SHA256SUMS.txt") -> dict[str, str]:
        record["checksums"] = asset
        return {pkg.asset: digest}

    def _download(url: str, target: Path) -> int:
        record["url"] = url
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return len(data)

    monkeypatch.setattr(router, "_fetch_release_checksums", _sums)
    monkeypatch.setattr(router, "_download_one_file", _download)
    return router._download_converter_package("rvt", platform_key=key)


def test_the_installer_fetches_the_package_of_the_given_host(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: dict[str, Any] = {}
    exe = _install(monkeypatch, tmp_path, "linux-arm64", _rvt_tar("linux-arm64", exe_mode=0o644), seen=seen)

    assert exe == (tmp_path / "rvt_linux-arm64" / "rvt-decode").resolve()
    assert exe.read_bytes() == _ELF
    assert seen["checksums"] == "SHA256SUMS.txt"
    assert seen["url"].endswith("/v2026.10.1/rvt-decode-2.0.1-linux-arm64.tar.gz")
    stamp = converter_package.read_stamp(exe.parent)
    assert stamp is not None and stamp["asset"] == "rvt-decode-2.0.1-linux-arm64.tar.gz"
    if sys.platform != "win32":
        assert stat.S_IMODE(exe.stat().st_mode) & 0o111, "the installer sets the execute bit itself"


def test_the_installer_picks_the_running_host_when_none_is_given(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _on_host(monkeypatch, "darwin", "arm64")
    seen: dict[str, Any] = {}
    data = _tar_bytes(
        {"rvt-decode-2.0.1-macos-arm64/rvt-decode": _MACHO, "rvt-decode-2.0.1-macos-arm64/BUILD_INFO.json": b"{}"}
    )
    pkg = replace(PLATFORM_PACKAGES["macos-arm64"]["rvt"], sha256=hashlib.sha256(data).hexdigest())
    monkeypatch.setitem(PLATFORM_PACKAGES["macos-arm64"], "rvt", pkg)
    monkeypatch.setattr(router, "_CONVERTER_INSTALL_DIR", tmp_path)
    monkeypatch.setattr(router, "_CONVERTER_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(router, "_fetch_release_checksums", lambda _r, _t, _a=None: {pkg.asset: pkg.sha256})

    def _download(url: str, target: Path) -> int:
        seen["url"] = url
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return len(data)

    monkeypatch.setattr(router, "_download_one_file", _download)
    exe = router._download_converter_package("rvt")
    assert exe.parent.name == "rvt_macos-arm64"
    assert seen["url"].endswith("rvt-decode-2.0.1-macos-arm64.tar.gz")


def test_a_binary_for_another_os_fails_the_install_and_leaves_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with pytest.raises(RuntimeError, match="not an ELF executable"):
        _install(monkeypatch, tmp_path, "linux-x64", _rvt_tar("linux-x64", exe=_MACHO))
    assert not (tmp_path / "rvt_linux-x64").exists()


def test_a_digest_the_linux_checksum_file_does_not_confirm_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(router, "_CONVERTER_INSTALL_DIR", tmp_path)
    monkeypatch.setattr(
        router,
        "_fetch_release_checksums",
        lambda _r, _t, _a=None: {PLATFORM_PACKAGES["linux-x64"]["dwg"].asset: "f" * 64},
    )
    monkeypatch.setattr(router, "_download_one_file", lambda *_a: pytest.fail("must not download"))
    with pytest.raises(RuntimeError, match="SHA256SUMS.txt of release v2026.10.1 .* Refusing to install"):
        router._download_converter_package("dwg", platform_key="linux-x64")


def test_an_asset_missing_from_the_linux_checksum_file_is_the_coded_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(router, "_CONVERTER_INSTALL_DIR", tmp_path)
    monkeypatch.setattr(router, "_fetch_release_checksums", lambda _r, _t, _a=None: {})
    monkeypatch.setattr(router, "_download_one_file", lambda *_a: pytest.fail("must not download"))
    with pytest.raises(converter_package.ConverterPackageMissingError) as info:
        router._download_converter_package("ifc", platform_key="macos-x64")
    assert info.value.code == "converter_package_missing"
    assert info.value.asset == "ifc2excel-2.0.1-macos-x64.tar.gz"


def test_a_host_without_a_build_gets_no_install(monkeypatch: pytest.MonkeyPatch) -> None:
    _on_host(monkeypatch, "linux", "riscv64")
    with pytest.raises(RuntimeError, match="no build"):
        router._download_converter_package("rvt")


# ── Endpoints ─────────────────────────────────────────────────────────────


async def test_the_install_endpoint_starts_an_install_on_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    import types

    _on_host(monkeypatch, "linux", "x86_64")
    monkeypatch.setattr(cad_import, "find_converter", lambda _ext: None)
    started: list[str] = []

    async def _impl(converter_id: str, force: bool, app: object) -> dict[str, object]:
        started.append(converter_id)
        return {"converter_id": converter_id, "installed": True}

    monkeypatch.setattr(router, "_install_converter_impl", _impl)
    router._INSTALL_TASKS.pop("dwg", None)
    request = types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace()))
    result = await router.install_converter("dwg", request, "user-1", force=False)  # type: ignore[arg-type]
    assert result.get("platform_unsupported") is None
    assert result["async_install"] is True
    task = router._INSTALL_TASKS.get("dwg")
    if task is not None:
        await task
    assert started == ["dwg"]
    router._clear_install_progress("dwg")


async def test_the_listing_describes_the_package_of_the_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cad_import, "find_converter", lambda _fmt: None)
    _on_host(monkeypatch, "darwin", "arm64")
    rows = {r["id"]: r for r in (await router.list_converters(verify=False, user=None))["converters"]}
    assert rows["rvt"]["exe"] == "rvt-decode"
    assert rows["ifc"]["version"] == "2.0.1"
    assert "IFC4x3" in rows["ifc"]["description"]
    assert all(r["platform_supported"] is True and r["platform"] == "macos-arm64" for r in rows.values())

    _on_host(monkeypatch, "sunos5", "i86pc")
    rows = {r["id"]: r for r in (await router.list_converters(verify=False, user=None))["converters"]}
    assert all(r["platform_supported"] is False for r in rows.values())


def test_each_package_downloads_from_its_own_release() -> None:
    from app.core.converter_source import DEFAULT_CONVERTER_TAG, package_tag

    assert package_tag(PACKAGES["rvt"], env={}) == DEFAULT_CONVERTER_TAG
    assert package_tag(PLATFORM_PACKAGES["linux-x64"]["rvt"], env={}) == POSIX_CONVERTER_TAG
    override = {"OE_CONVERTER_TAG": "v9"}
    assert package_tag(PLATFORM_PACKAGES["macos-arm64"]["ifc"], env=override) == "v9"
