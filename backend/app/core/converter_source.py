# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Where the DDC converters come from - one declaration, one place.

The converters are published as packages on a GitHub *release* of
``datadrivenconstruction/cad2data-Revit-IFC-DWG``. Release 2026.10.0 replaced
the 18.x generation with converters built on DataDrivenConstruction's own
RVT, IFC and DWG readers; no third-party CAD SDK is inside them. The release
carries a ``SHA256SUMS.txt`` and this module pins the digest of every package
it installs, so an install is a download of one named asset followed by a hash
check, not a walk over a repository tree.

Three packages are used (there is no DGN converter in this generation):

==========  ================================  ================================
format      package                           command line
==========  ================================  ================================
``rvt``     DDC RVT Converter 2.0.1           ``cli/RVTconverter.exe``
``ifc``     DDC IFC to Excel 2.0.0            ``runtime/python.exe`` running
                                              ``sources/ifc-excel/converter.py``
``dwg``     DDC DWG to Excel 0.4.1            ``cli/dwg2excel.exe``
==========  ================================  ================================

The digest below is the one published in the release's ``SHA256SUMS.txt``. The
installer re-reads that file from the release it downloads from and refuses a
package whose digest is not the same in both places, so moving the pin is a
deliberate act: bump the tag and every ``sha256`` here together. ``OE_CONVERTER_TAG``
and ``OE_CONVERTER_REPO`` point a fork or a newer release at the installer
without a code change; for a tag other than the pinned one the digest comes
from that release's ``SHA256SUMS.txt`` alone.

Linux and macOS builds of the same converters ship in a release of their own as
``.tar.gz`` archives (x64 and arm64), with their digests in
``SHA256SUMS.txt`` of :data:`POSIX_CONVERTER_TAG`. They are other command lines with the same
outputs; :data:`PLATFORM_PACKAGES` maps a host key (``windows-x64``,
``linux-x64``, ``linux-arm64``, ``macos-x64``, ``macos-arm64``) to the
packages that run there, and :func:`host_platform_key` names the host.

==========  ==========================================  =======================================
format      Linux / macOS package                       command line
==========  ==========================================  =======================================
``rvt``     ``rvt-decode-2.0.1-<os>-<arch>.tar.gz``     ``rvt-decode native-graph <in> --ifc``
``ifc``     ``ifc2excel-2.0.1-<os>-<arch>.tar.gz``      ``ifc2excel <in> --raw-tables``
``dwg``     ``dwg2excel-2.0.0-<os>-<arch>.tar.gz``      ``dwg2excel <in> --json``
==========  ==========================================  =======================================

This module imports nothing beyond the standard library. ``app.main`` reads it
for ``/api/system/converters/version-check`` and must keep working when the
takeoff module is not loaded; keep it that way.
"""

from __future__ import annotations

import os
import platform
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONVERTER_REPO = "datadrivenconstruction/cad2data-Revit-IFC-DWG"

DEFAULT_CONVERTER_TAG = "v2026.10.0"

#: Name of the checksum file of the Windows packages.
CHECKSUMS_ASSET = "SHA256SUMS.txt"

#: Name of the checksum file of the Linux and macOS packages.
POSIX_CHECKSUMS_ASSET = "SHA256SUMS.txt"

#: Release the Linux and macOS packages are pinned to. Upstream ships them in a
#: release of their own; the copies inside :data:`DEFAULT_CONVERTER_TAG` were
#: re-uploaded with other digests, so the two sets are pinned separately.
POSIX_CONVERTER_TAG = "v2026.10.1"

#: Host key of the Windows packages.
WINDOWS_KEY = "windows-x64"

#: Written next to an installed package so a later check can tell which
#: release asset the folder came from without re-hashing hundreds of files.
INSTALL_STAMP_NAME = ".ddc-package.json"


@dataclass(frozen=True)
class ConverterPackage:
    """One installable converter package of the release."""

    fmt: str
    name: str
    version: str
    asset: str
    sha256: str
    size_bytes: int
    #: Command-line executable, relative to the install folder, POSIX separators.
    exe_rel: str
    #: Python script the executable runs, relative to the install folder, or
    #: ``None`` when the executable is the converter itself.
    script_rel: str | None
    #: Only these top-level entries of the archive are extracted. ``None``
    #: extracts everything. The desktop apps and viewers inside the RVT and DWG
    #: packages are not used from the command line, so they are not installed.
    include: tuple[str, ...] | None
    #: Files that must exist next to a healthy install besides the executable.
    companions: tuple[str, ...] = ()
    #: Source-format versions the converter reads, as shown to people. The one
    #: place a version range is written down; every screen reads it from the API.
    format_range: str = ""
    #: False for a converter that writes element tables and no 3D mesh.
    produces_geometry: bool = True
    #: Host the package runs on (a key of :data:`PLATFORM_PACKAGES`).
    platform_key: str = WINDOWS_KEY
    #: ``zip`` or ``tar.gz``.
    archive_format: str = "zip"
    #: Release asset that lists this package's digest.
    checksums_asset: str = CHECKSUMS_ASSET
    #: Release this package is pinned to; empty means :data:`DEFAULT_CONVERTER_TAG`.
    release_tag: str = ""


PACKAGES: dict[str, ConverterPackage] = {
    "rvt": ConverterPackage(
        fmt="rvt",
        name="DDC RVT Converter",
        version="2.0.1",
        asset="DDC-RVT-Converter-2.0.1-portable.zip",
        sha256="6f4f79fc65415670c35e01c25797362a41b954c5fd7b182ef44d45d85578272b",
        size_bytes=80801009,
        exe_rel="cli/RVTconverter.exe",
        script_rel=None,
        include=("cli/", "licenses/", "EULA.txt", "EULA.md"),
        format_range="Revit 2019-2027",
    ),
    "ifc": ConverterPackage(
        fmt="ifc",
        name="DDC IFC to Excel",
        version="2.0.0",
        asset="DDC-IFC-to-Excel-2.0.0-portable.zip",
        sha256="0238bae0cf4cf5ae717c180d6f286e451189d6a78402068d9bb3b5e065061ea0",
        size_bytes=35600175,
        exe_rel="runtime/python.exe",
        script_rel="sources/ifc-excel/converter.py",
        include=None,
        companions=("sources/ifc-excel/converter.py",),
        format_range="IFC2x3, IFC4",
        produces_geometry=False,
    ),
    "dwg": ConverterPackage(
        fmt="dwg",
        name="DDC DWG to Excel",
        version="0.4.1",
        asset="DDC-DWG-to-Excel-0.4.1-portable.zip",
        sha256="b84defacf1ca9209baa17f509053b57b50bfc00a669d96d44cfc9739752a070b",
        size_bytes=22507533,
        exe_rel="cli/dwg2excel.exe",
        script_rel=None,
        include=("cli/", "licenses/", "EULA.txt"),
        format_range="DWG R13-2018",
    ),
}

#: Linux and macOS packages: ``(format, tool, version, display name, range, geometry)``.
_POSIX_TOOLS: tuple[tuple[str, str, str, str, str, bool], ...] = (
    ("rvt", "rvt-decode", "2.0.1", "DDC RVT Converter", "Revit 2019-2027", True),
    ("ifc", "ifc2excel", "2.0.1", "DDC IFC to Excel", "IFC2x3, IFC4, IFC4x3", False),
    ("dwg", "dwg2excel", "2.0.0", "DDC DWG to Excel", "DWG R13-2018", True),
)

#: ``(sha256, size)`` of every Linux and macOS package, as listed in
#: ``SHA256SUMS.txt`` of :data:`POSIX_CONVERTER_TAG`.
_POSIX_DIGESTS: dict[str, tuple[str, int]] = {
    "dwg2excel-2.0.0-linux-arm64.tar.gz": (
        "075df8e5c05de2a6b992029b83c5130097e91f2bbea5031f571892f4e1396fc5",
        27211556,
    ),
    "dwg2excel-2.0.0-linux-x64.tar.gz": (
        "d4eba8e798ba98b2d5914f03f86fbfbf11928ff1337742f3492e813853b29051",
        28829054,
    ),
    "dwg2excel-2.0.0-macos-arm64.tar.gz": (
        "d5747a914422560e28478d7e95b5b5b3fc140a6624999f18da8920be0331f396",
        12791822,
    ),
    "dwg2excel-2.0.0-macos-x64.tar.gz": (
        "3acf906cdd8a8532d6b240f7be02a09eafa3b9c9e03f350c83da94a1d65ce68b",
        14080015,
    ),
    "ifc2excel-2.0.1-linux-arm64.tar.gz": (
        "5a741249d1f5e456c36918fd3524896aa2bf1896570a98872e2e6ae2d4797118",
        22890537,
    ),
    "ifc2excel-2.0.1-linux-x64.tar.gz": (
        "54574db86ee38121db45c485288725e3cddbb675d1dc6d06f32928b3716a7b9f",
        23951488,
    ),
    "ifc2excel-2.0.1-macos-arm64.tar.gz": (
        "4ebe7eed52898277f2c20a351856d9803774036202dd7b76ee21179d7f5e585b",
        8840850,
    ),
    "ifc2excel-2.0.1-macos-x64.tar.gz": (
        "141998f72b104674c93d67a2f2782604485677362ab03fc89959ea65db43fff4",
        9577374,
    ),
    "rvt-decode-2.0.1-linux-arm64.tar.gz": (
        "b2622a9f61dfb633f40b04c58d84c7f02e73f327eb66b430aec1a4eb7d1e278c",
        5629940,
    ),
    "rvt-decode-2.0.1-linux-x64.tar.gz": (
        "fc176c46e27da129bec57783c0bfa9c25c20d4d8d603daf43d97bdbebed39550",
        6632956,
    ),
    "rvt-decode-2.0.1-macos-arm64.tar.gz": (
        "0157b03e2b57678d71c1e5c5348c91986646f17c75a4f4f2e7b23328e41ab2a1",
        5409885,
    ),
    "rvt-decode-2.0.1-macos-x64.tar.gz": (
        "bce61756354bcaa07fc015491c270fd10f5d13c3cb75f53e486355377c966984",
        6556419,
    ),
}

POSIX_KEYS: tuple[str, ...] = ("linux-x64", "linux-arm64", "macos-x64", "macos-arm64")


def _posix_packages(key: str) -> dict[str, ConverterPackage]:
    packages: dict[str, ConverterPackage] = {}
    for fmt, tool, version, name, format_range, geometry in _POSIX_TOOLS:
        asset = f"{tool}-{version}-{key}.tar.gz"
        sha256, size = _POSIX_DIGESTS[asset]
        packages[fmt] = ConverterPackage(
            fmt=fmt,
            name=name,
            version=version,
            asset=asset,
            sha256=sha256,
            size_bytes=size,
            exe_rel=tool,
            script_rel=None,
            include=None,
            # rvt-decode carries BUILD_INFO.json, the two bundled-Python tools a MANIFEST.json.
            companions=("BUILD_INFO.json",) if fmt == "rvt" else ("MANIFEST.json",),
            format_range=format_range,
            produces_geometry=geometry,
            platform_key=key,
            archive_format="tar.gz",
            checksums_asset=POSIX_CHECKSUMS_ASSET,
            release_tag=POSIX_CONVERTER_TAG,
        )
    return packages


#: Packages per host key. ``PACKAGES`` stays the Windows set.
PLATFORM_PACKAGES: dict[str, dict[str, ConverterPackage]] = {
    WINDOWS_KEY: PACKAGES,
    **{key: _posix_packages(key) for key in POSIX_KEYS},
}

_ARCH_ALIASES = {"x86_64": "x64", "amd64": "x64", "x64": "x64", "aarch64": "arm64", "arm64": "arm64"}


def host_platform_key(system: str | None = None, machine: str | None = None) -> str | None:
    """Key of :data:`PLATFORM_PACKAGES` for this host, or ``None`` when no build runs here.

    ``system`` is a ``sys.platform`` value and ``machine`` a ``platform.machine()``
    value; both default to the running host. Windows on ARM runs the x64 build.
    """
    plat = sys.platform if system is None else system
    if plat == "win32":
        return WINDOWS_KEY
    if plat.startswith("linux"):
        os_name = "linux"
    elif plat == "darwin":
        os_name = "macos"
    else:
        return None
    arch = _ARCH_ALIASES.get((platform.machine() if machine is None else machine).lower())
    return f"{os_name}-{arch}" if arch else None


def host_packages(key: str | None = None) -> dict[str, ConverterPackage]:
    """Packages that run on ``key`` (default: this host); empty when there are none."""
    return PLATFORM_PACKAGES.get(key or host_platform_key() or "", {})


def install_dir_name(fmt: str, key: str) -> str:
    """Folder under ``~/.openestimator/converters`` a package of ``key`` is unpacked into."""
    return f"{fmt}_windows" if key == WINDOWS_KEY else f"{fmt}_{key}"


def all_packages() -> list[ConverterPackage]:
    """Every package of every host."""
    return [pkg for packages in PLATFORM_PACKAGES.values() for pkg in packages.values()]


def resolve_converter_repo(env: Mapping[str, str] | None = None) -> str:
    """Pick the converter repository: the override, then the default."""
    source = os.environ if env is None else env
    return source.get("OE_CONVERTER_REPO") or DEFAULT_CONVERTER_REPO


def resolve_converter_tag(env: Mapping[str, str] | None = None) -> str:
    """Pick the release tag: the override, then the pin.

    An empty string counts as unset, so a CI runner that exports
    ``OE_CONVERTER_TAG=`` from an undefined variable still gets the pin.
    """
    source = os.environ if env is None else env
    return source.get("OE_CONVERTER_TAG") or DEFAULT_CONVERTER_TAG


def package_tag(pkg: ConverterPackage, env: Mapping[str, str] | None = None) -> str:
    """Release a package is downloaded from: the ``OE_CONVERTER_TAG`` override, then its own pin."""
    source = os.environ if env is None else env
    return source.get("OE_CONVERTER_TAG") or pkg.release_tag or DEFAULT_CONVERTER_TAG


def release_asset_url(asset: str, *, repo: str | None = None, tag: str | None = None) -> str:
    """Download URL of one asset of the release."""
    return f"https://github.com/{repo or resolve_converter_repo()}/releases/download/{tag or resolve_converter_tag()}/{asset}"


def release_page_url(*, repo: str | None = None, tag: str | None = None) -> str:
    return f"https://github.com/{repo or resolve_converter_repo()}/releases/tag/{tag or resolve_converter_tag()}"


def parse_sha256sums(text: str) -> dict[str, str]:
    """Parse ``sha256sum`` output (``<hex> *<name>`` or ``<hex>  <name>``)."""
    sums: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        digest, name = parts[0].lower(), parts[1].strip().lstrip("*")
        if len(digest) == 64 and all(c in "0123456789abcdef" for c in digest):
            sums[name] = digest
    return sums


def package_exe(install_dir: Path, fmt: str) -> Path:
    """Absolute path of a format's Windows executable inside its install folder."""
    return install_dir / PACKAGES[fmt].exe_rel


def command_prefix(fmt: str, exe: Path) -> list[str]:
    """Argv prefix that starts the converter of ``fmt`` whose executable is ``exe``.

    For the Windows IFC package ``exe`` is the bundled Python and the converter
    is a script two levels up from it; every other package is a plain executable.
    """
    pkg = PACKAGES.get(fmt)
    if pkg is None or pkg.script_rel is None or exe.name.lower() != Path(pkg.exe_rel).name.lower():
        return [str(exe)]
    root = exe.parents[len(Path(pkg.exe_rel).parts) - 1]
    return [str(exe), str(root / pkg.script_rel)]


def is_new_generation(exe: Path) -> bool:
    """True when ``exe`` is one of the 2026.10 command lines."""
    name = exe.name.lower()
    return name in {"rvtconverter.exe", "dwg2excel.exe", "python.exe", "rvt-decode", "dwg2excel", "ifc2excel"}
