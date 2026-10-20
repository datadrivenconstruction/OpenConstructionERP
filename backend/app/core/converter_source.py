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
``rvt``     DDC RVT Converter 2.0.0           ``cli/RVTconverter.exe``
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

This module imports nothing beyond the standard library. ``app.main`` reads it
for ``/api/system/converters/version-check`` and must keep working when the
takeoff module is not loaded; keep it that way.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONVERTER_REPO = "datadrivenconstruction/cad2data-Revit-IFC-DWG"

DEFAULT_CONVERTER_TAG = "v2026.10.0"

#: Name of the checksum file attached to every release.
CHECKSUMS_ASSET = "SHA256SUMS.txt"

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


PACKAGES: dict[str, ConverterPackage] = {
    "rvt": ConverterPackage(
        fmt="rvt",
        name="DDC RVT Converter",
        version="2.0.0",
        asset="DDC-RVT-Converter-2.0.0-portable.zip",
        sha256="d7ac510251e396ffc6cefd0236eb10e5ea12dcfc6255721e7ce5a3a317767bd7",
        size_bytes=79483317,
        exe_rel="cli/RVTconverter.exe",
        script_rel=None,
        include=("cli/", "licenses/", "EULA.txt"),
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

#: The release is Windows 10/11 x64 only today; Linux and macOS builds are
#: announced by upstream but not published.
SUPPORTED_PLATFORM = "win32"


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
    """Absolute path of a format's executable inside its install folder."""
    return install_dir / PACKAGES[fmt].exe_rel


def command_prefix(fmt: str, exe: Path) -> list[str]:
    """Argv prefix that starts the converter of ``fmt`` whose executable is ``exe``.

    For the IFC package ``exe`` is the bundled Python and the converter is a
    script two levels up from it; the other formats are plain executables.
    """
    pkg = PACKAGES.get(fmt)
    if pkg is None or pkg.script_rel is None:
        return [str(exe)]
    root = exe.parents[len(Path(pkg.exe_rel).parts) - 1]
    return [str(exe), str(root / pkg.script_rel)]


def is_new_generation(exe: Path) -> bool:
    """True when ``exe`` is one of the 2026.10 command lines."""
    name = exe.name.lower()
    return name in {"rvtconverter.exe", "dwg2excel.exe", "python.exe"}
