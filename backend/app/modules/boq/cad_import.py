# OpenConstructionERP — DataDrivenConstruction (DDC)
# CAD2DATA Pipeline · CWICR Cost Database Engine
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
# AGPL-3.0 License · DDC-CWICR-OE-2026
"""‌⁠‍CAD/BIM file import via DDC Community converters.

Workflow:
1. User uploads .rvt/.ifc/.dwg/.dgn file
2. Backend saves to temp dir
3. Runs appropriate DDC converter (.exe) -> produces Excel
4. Parses Excel -> extracts elements (type, volume, area, count)
5. AI maps elements to construction work items with pricing
6. Returns BOQ positions ready for import
"""

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Converter mapping per platform.
#
# Windows: GitHub-bundled `*.exe` from `cad2data-Revit-IFC-DWG-DGN`.
# Linux:   apt-installed ELF binary at `/usr/bin/{Format}Exporter` (no
#          extension, CapitalCamelCase) from the signed apt repo at
#          `pkg.datadrivenconstruction.io`. The .deb packages
#          (`ddc-rvtconverter` etc.) drop exactly one file each — the
#          binary itself — and apt resolves the shared-lib runtime
#          (`ddc-deps-kernel`, `ddc-deps-revit`, `ddc-thirdparty`).
_WINDOWS_CONVERTERS: dict[str, str] = {
    "rvt": "RvtExporter.exe",
    "ifc": "IfcExporter.exe",
    "dwg": "DwgExporter.exe",
    "dgn": "DgnExporter.exe",
}
_LINUX_CONVERTERS: dict[str, str] = {
    "rvt": "RvtExporter",
    "ifc": "IfcExporter",
    "dwg": "DwgExporter",
    "dgn": "DgnExporter",
}

# Active mapping for the running platform — kept under the legacy name
# `CONVERTERS` so external callers (and the takeoff router) don't need
# to know about platform branching.
CONVERTERS: dict[str, str] = _LINUX_CONVERTERS if sys.platform.startswith("linux") else _WINDOWS_CONVERTERS

SUPPORTED_CAD_EXTENSIONS: set[str] = set(CONVERTERS.keys())

# Look for converters in these locations (in order)
CONVERTER_SEARCH_PATHS: list[Path] = [
    Path("converters/bin"),
    Path.home() / ".openestimator" / "converters",
    Path("/opt/openestimator/converters"),
    Path("C:/ProgramData/OpenConstructionERP/converters"),
]


def _find_ddc_toolkit_bin() -> Path | None:
    """‌⁠‍Auto-detect DDC toolkit converters/bin from editable install or known paths.

    Search order, in priority:

      1. ``DDC_TOOLKIT_DIR`` env override (operator-explicit wins everything).
      2. ``importlib.metadata`` lookup for the ``ddc-toolkit`` distribution
         (works for ``pip install -e`` of the toolkit package).
      3. Sibling directories of the **source** repository
         (``Path(__file__).resolve().parents[4].parent``). This works when
         the user runs the backend from a checked-out source tree.
      4. Sibling directories of the **working directory** the process was
         launched from. Critical for the wheel-install case: when the user
         starts the service with ``pip install openconstructionerp`` and
         then runs ``uvicorn`` from inside their project root, the
         ``__file__`` path resolves to ``site-packages`` (parents[4].parent
         is ``anaconda3``) and the sibling-scan above completely misses a
         ``ddc_toolkit`` checkout living next to the project root. Adding
         ``Path.cwd().parent`` as an additional anchor closes that gap
         without requiring the operator to set ``DDC_TOOLKIT_DIR``.
      5. ``~/.openestimator/converters/`` directly — the BIM auto-installer
         drops shared binaries (no per-format subfolder) here for users who
         do a one-click install via the Quantities page.
    """
    # 1. Check env var
    env_dir = os.environ.get("DDC_TOOLKIT_DIR")
    if env_dir:
        p = Path(env_dir) / "converters" / "bin"
        if p.is_dir():
            return p

    # 2. Try importlib.metadata (editable install of ddc-toolkit)
    try:
        import importlib.metadata

        dist = importlib.metadata.distribution("ddc-toolkit")
        for f in dist.files or []:
            fpath = Path(str(f))
            if "converters" in str(fpath) or "bin" in str(fpath):
                resolved = Path(str(dist._path)).parent / fpath  # type: ignore[attr-defined]
                candidate = resolved.parent
                while candidate != candidate.parent:
                    check = candidate / "converters" / "bin"
                    if check.is_dir():
                        return check
                    candidate = candidate.parent
                break
    except Exception:
        logger.debug("DDC converter discovery via importlib failed", exc_info=True)

    # 3. Scan sibling directories of this project (source-tree install).
    # 4. ALSO scan sibling directories of the launch CWD (wheel install +
    #    user runs from their project root). Both anchors are tried with
    #    the same set of common toolkit directory names.
    this_project = Path(__file__).resolve().parents[4]  # backend/app/modules/boq -> repo root
    cwd = Path.cwd().resolve()
    sibling_names = ("ddc_toolkit", "ddc-toolkit", "DDC_Toolkit")
    anchors: tuple[Path, ...] = (this_project.parent, cwd.parent, cwd)
    seen: set[Path] = set()
    for anchor in anchors:
        if anchor in seen:
            continue
        seen.add(anchor)
        for sibling_name in sibling_names:
            candidate = anchor / sibling_name / "converters" / "bin"
            if candidate.is_dir():
                return candidate

    # 5. Final fallback: the BIM auto-installer's shared drop-dir.
    shared = Path.home() / ".openestimator" / "converters"
    if shared.is_dir():
        return shared

    return None


# Auto-detect DDC toolkit at import time
_ddc_bin = _find_ddc_toolkit_bin()
if _ddc_bin:
    CONVERTER_SEARCH_PATHS.insert(0, _ddc_bin)
    logger.info("DDC toolkit converters found at %s", _ddc_bin)


def find_converter(extension: str) -> Path | None:
    """‌⁠‍Find the converter executable for a given file extension.

    Searches through ``CONVERTER_SEARCH_PATHS`` in order and returns the
    first existing executable path, or ``None`` if no converter is found.

    Args:
        extension: Lowercase file extension without dot (e.g. ``"rvt"``).

    Returns:
        Path to the converter executable, or ``None``.
    """
    exe_name = CONVERTERS.get(extension)
    if not exe_name:
        return None

    # Build dynamic search paths
    search_paths = list(CONVERTER_SEARCH_PATHS)

    # Also check OPENESTIMATOR_CONVERTERS_DIR env var
    env_dir = os.environ.get("OPENESTIMATOR_CONVERTERS_DIR")
    if env_dir:
        search_paths.insert(0, Path(env_dir))

    # Auto-detect DDC toolkit in sibling directories
    ddc_bin = _find_ddc_toolkit_bin()
    if ddc_bin and ddc_bin not in search_paths:
        search_paths.insert(0, ddc_bin)

    # Per-format Windows install dir written by the BIM converter
    # auto-installer (takeoff/router.py:install_converter). The
    # installer drops files at ~/.openestimator/converters/{ext}_windows/
    # so multiple converters can coexist without their bundled Qt6
    # DLLs colliding. Probe this location explicitly so an installed
    # converter is picked up by the next find_converter() call without
    # any service restart.
    per_format_windows = Path.home() / ".openestimator" / "converters" / f"{extension}_windows"
    if per_format_windows not in search_paths:
        search_paths.insert(0, per_format_windows)

    # Linux apt install puts the binaries on PATH. The .deb packages
    # at `pkg.datadrivenconstruction.io` (apt v18.0.0.0, amd64+arm64)
    # ship exactly one file each — `/usr/bin/{Format}Exporter`
    # (CapitalCamelCase, no extension). We probe these locations
    # BEFORE walking the rest of `search_paths` so a system-installed
    # converter is found instantly with no environment fiddling.
    #
    # The legacy `ddc-{ext}converter` names are kept as fallbacks for
    # users who installed from older instructions or symlinked the
    # binary manually. `linux_exe` is the *real* binary name; `exe_name`
    # at this point may still be a Windows `.exe` if the module was
    # imported on Windows but is being asked about a Linux install (the
    # cross-platform smoke-test scenario is unusual but cheap to cover).
    linux_exe = _LINUX_CONVERTERS.get(extension, exe_name.removesuffix(".exe"))
    linux_apt_candidates = [
        Path("/usr/bin") / linux_exe,
        Path("/usr/local/bin") / linux_exe,
        # Legacy probe paths from earlier instructions — kept for users
        # who hand-symlinked the binary under the apt-package name.
        Path("/usr/bin") / f"ddc-{extension}converter",
        Path("/usr/local/bin") / f"ddc-{extension}converter",
    ]
    for cand in linux_apt_candidates:
        if cand.exists() and cand.stat().st_size > 1024:
            return cand

    for search_path in search_paths:
        exe_path = search_path / exe_name
        if exe_path.exists() and exe_path.stat().st_size > 1024:
            return exe_path

    return None


def is_cad_file(filename: str) -> bool:
    """Check if a filename has a supported CAD/BIM extension.

    Args:
        filename: File name or path (e.g. ``"project.rvt"``).

    Returns:
        ``True`` if the extension is supported.
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in SUPPORTED_CAD_EXTENSIONS


# ── Health check / pre-conversion smoke test ──────────────────────────────
#
# Why this exists: ``find_converter()`` only checks the binary file is
# present and bigger than 1 KB. That doesn't catch the realistic broken
# states a Windows user runs into:
#   * Required Qt6 DLL did not download with the rest of the install.
#   * Wrong-architecture binary (x86 on ARM) refuses to load.
#   * Permission denied because the install dir was extracted with the
#     wrong attributes (read-only / blocked-by-Mark-of-the-Web).
#   * Visual C++ Redistributable missing (msvcp140.dll, vcruntime140.dll).
#
# Calling ``smoke_test_converter`` before scheduling a conversion lets us
# fail FAST with a clear error + suggested fix instead of letting the
# upload run for 5 minutes and then time out with no diagnostic info.

import time
from typing import Literal, TypedDict

ConverterHealthStatus = Literal["ok", "failed", "unknown"]
SuggestedAction = Literal[
    "install_converter",
    "reinstall_converter",
    "install_vc_redist",
    "unblock_files",
    "check_permissions",
    "manual_install_from_github",
]


class ConverterHealth(TypedDict):
    """Result of a converter smoke test.

    ``status``:
        - ``"ok"`` — binary loads and exits cleanly.
        - ``"failed"`` — binary doesn't load (DLL missing, etc).
        - ``"unknown"`` — smoke test couldn't run (timeout, OS error
          unrelated to the binary itself).
    ``message``:
        Human-readable explanation. Empty string on the happy path.
    ``suggested_actions``:
        Stable string ids the frontend uses to render specific buttons
        / instructions (Reinstall / Open install dir / Run as admin /
        Install VCRedist / etc).
    ``checked_at``:
        Unix timestamp of the check — used by the cache layer.
    """

    status: ConverterHealthStatus
    message: str
    suggested_actions: list[str]
    checked_at: float


# In-process cache so we don't re-spawn the binary on every API call.
# 5 minutes is enough that page-refresh navigation reuses one result;
# manual install/uninstall paths invalidate explicitly.
_HEALTH_CACHE: dict[str, ConverterHealth] = {}
_HEALTH_TTL_SEC = 300

# Windows NTSTATUS exit codes that always mean "the loader couldn't bring
# the binary up". The values appear as both signed (Python's negative-int
# representation of an unsigned u32) and unsigned in the wild, so we
# match both.
_WINDOWS_DLL_LOAD_FAILURES: frozenset[int] = frozenset(
    {
        -1073741515,  # 0xC0000135 STATUS_DLL_NOT_FOUND
        -1073741502,  # 0xC0000142 STATUS_DLL_INIT_FAILED
        3221225781,  # 0xC0000135 unsigned
        3221225794,  # 0xC0000142 unsigned
    }
)

# Linux ld.so failure markers. When a shared dependency (`libQt6Core.so.6`
# or one of the `ddc-deps-*` packages) is missing, glibc's `ld.so` writes
# a line like `RvtExporter: error while loading shared libraries: <name>`
# to stderr and exits with status 127. We match the substring (locale-
# independent — glibc keeps the English text even on translated systems).
_LINUX_LDSO_FAILURE_MARKER = b"error while loading shared libraries"
_LINUX_LDSO_EXIT_CODE = 127


def smoke_test_converter(extension: str, force: bool = False) -> ConverterHealth:
    """Quick health check: spawn the converter binary and verify it loads.

    Sends an empty stdin and waits up to ``8`` seconds for an exit. The
    purpose is NOT to detect feature bugs — only to verify that the OS
    can launch the binary without a missing-DLL / wrong-arch / perms
    error. A binary that loads and then exits with an error code (because
    the empty input didn't parse) is fine for our purposes.

    Args:
        extension: Lowercase file extension without dot (``"rvt"`` etc.).
        force: Bypass the 5-minute cache and re-spawn the binary.

    Returns:
        ``ConverterHealth`` dict (always; never raises).
    """
    now = time.time()
    cached = _HEALTH_CACHE.get(extension)
    if cached and not force and (now - cached["checked_at"]) < _HEALTH_TTL_SEC:
        return cached

    exe_path = find_converter(extension)
    if exe_path is None:
        result: ConverterHealth = {
            "status": "failed",
            "message": (
                f"The .{extension.upper()} converter is not installed. "
                f"Use the Install button in the BIM page header to download it."
            ),
            "suggested_actions": ["install_converter"],
            "checked_at": now,
        }
        _HEALTH_CACHE[extension] = result
        return result

    try:
        import subprocess

        # ``input=`` already implies ``stdin=PIPE`` — passing both raises
        # ``ValueError: stdin and input arguments may not both be used``,
        # which used to crash the per-upload pre-flight check on every
        # native CAD format and leave the model stuck at
        # ``ddc_smoke_failed`` even when the binary was correctly
        # installed.  Drop the explicit ``stdin=PIPE``.
        proc = subprocess.run(
            [str(exe_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(exe_path.parent),
            input=b"\n",
            timeout=8,
        )
        rc = proc.returncode

        if rc in _WINDOWS_DLL_LOAD_FAILURES:
            result = {
                "status": "failed",
                "message": (
                    f"{exe_path.name} exists on disk but cannot load — a "
                    f"required Qt6 / Visual C++ DLL is missing "
                    f"(Windows error 0x{rc & 0xFFFFFFFF:08x}). The Qt6 "
                    f"plugins probably did not download cleanly during "
                    f"install."
                ),
                "suggested_actions": [
                    "reinstall_converter",
                    "install_vc_redist",
                    "manual_install_from_github",
                ],
                "checked_at": now,
            }
        elif (
            sys.platform.startswith("linux")
            and rc == _LINUX_LDSO_EXIT_CODE
            and _LINUX_LDSO_FAILURE_MARKER in (proc.stderr or b"")
        ):
            # Linux ld.so wrote "error while loading shared libraries: ..."
            # — surface the exact missing-library line so the user sees
            # which `ddc-deps-*` package is missing (or wasn't installed
            # by `apt install` because the source wasn't added).
            stderr_text = (proc.stderr or b"").decode("utf-8", errors="replace")
            missing_line = next(
                (line.strip() for line in stderr_text.splitlines() if "error while loading shared libraries" in line),
                stderr_text.strip()[:200],
            )
            result = {
                "status": "failed",
                "message": (
                    f"{exe_path.name} cannot load — a shared library "
                    f"dependency is missing. {missing_line}\n\n"
                    f"Reinstall the converter so apt resolves "
                    f"`ddc-deps-kernel`, `ddc-deps-revit`, "
                    f"`ddc-thirdparty` and the rest of the SDK runtime."
                ),
                "suggested_actions": [
                    "reinstall_converter",
                    "manual_install_from_github",
                ],
                "checked_at": now,
            }
        else:
            # Any other exit code (including non-zero from the empty input
            # not being valid CAD): the binary did load, so the install
            # is healthy from our perspective.
            result = {
                "status": "ok",
                "message": "",
                "suggested_actions": [],
                "checked_at": now,
            }
    except subprocess.TimeoutExpired:
        # Binary is alive but waiting for stdin / showing a window. That
        # means the loader succeeded — treat as healthy.
        result = {
            "status": "ok",
            "message": "",
            "suggested_actions": [],
            "checked_at": now,
        }
    except FileNotFoundError:
        result = {
            "status": "failed",
            "message": (
                f"Binary {exe_path} disappeared between detection and launch. "
                f"The install may have been partially deleted."
            ),
            "suggested_actions": ["reinstall_converter"],
            "checked_at": now,
        }
    except PermissionError as exc:
        result = {
            "status": "failed",
            "message": (
                f"Permission denied when launching {exe_path.name}: {exc}. "
                f"On Windows this is usually 'Mark of the Web' — right-click "
                f"the file → Properties → Unblock, or reinstall."
            ),
            "suggested_actions": ["unblock_files", "reinstall_converter"],
            "checked_at": now,
        }
    except OSError as exc:
        result = {
            "status": "failed",
            "message": (
                f"OS could not launch {exe_path.name}: "
                f"{exc.__class__.__name__}: {exc}. The binary may be the "
                f"wrong architecture for this machine."
            ),
            "suggested_actions": ["reinstall_converter", "check_permissions"],
            "checked_at": now,
        }
    except Exception as exc:  # noqa: BLE001 — health check must never raise
        logger.warning("Smoke test for .%s converter errored: %s", extension, exc)
        result = {
            "status": "unknown",
            "message": (f"Health check could not complete: {exc.__class__.__name__}: {exc}"),
            "suggested_actions": [],
            "checked_at": now,
        }

    _HEALTH_CACHE[extension] = result
    return result


# ── Version detection — RVT file + installed converter ────────────────────
#
# Why this exists: the smoke test verifies the binary LOADS, not that it can
# parse the user's file. A user can have a perfectly installed converter that
# is simply OLDER than the Revit version that saved their .rvt file — and the
# DDC converter then silently writes an empty Excel. Detecting both versions
# upfront lets us surface the actual reason ("Your RVT is from Revit 2025
# but the installed converter only supports up to 2023") instead of the
# generic "Converter Required" message.


def read_rvt_revit_version(path: Path, *, max_scan_bytes: int = 262144) -> dict[str, str | None]:
    """‌⁠‍Extract Revit version metadata from a .rvt file header.

    RVT files are OLE Compound Documents. The ``BasicFileInfo`` stream
    near the start contains UTF-16-LE text like ``Format: 2024`` and
    ``Revit Build: 24.0.11.21``. We don't parse the full OLE structure
    (would add a dependency) — we just scan the first 256 KB for the
    well-known marker strings, which are reliably present in the leading
    sectors for files saved by Revit 2018+.

    Returns a dict with optional ``format``, ``build``, ``app_name``
    fields. All values are strings or ``None`` if the marker wasn't found.
    Never raises — IO errors return all-None.
    """
    info: dict[str, str | None] = {"format": None, "build": None, "app_name": None}
    try:
        with path.open("rb") as fh:
            header = fh.read(max_scan_bytes)
    except OSError as exc:
        logger.debug("Could not read RVT header from %s: %s", path, exc)
        return info

    # OLE/CFB header starts with the magic D0CF11E0A1B11AE1. Bail early if
    # the file isn't a Compound File (e.g. corrupted upload or wrong ext).
    if not header.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        logger.debug("File %s is not a valid OLE Compound File", path.name)
        return info

    # Decode the scanned region as UTF-16-LE (Revit's chosen encoding for
    # BasicFileInfo). errors='replace' so a stray byte doesn't kill the
    # whole scan.
    try:
        text = header.decode("utf-16-le", errors="replace")
    except UnicodeError:
        return info

    import re as _re

    # Examples of strings we want to capture:
    #   "Format: 2024"
    #   "Revit Build: (Autodesk Revit 2024 (ENU))"
    #   "Revit Build: 24.0.11.21"
    fmt = _re.search(r"Format:\s*([0-9]{4})", text)
    if fmt:
        info["format"] = fmt.group(1)

    build = _re.search(r"Revit Build:\s*([^\r\n]+)", text)
    if build:
        info["build"] = build.group(1).strip()
        # If the build line contains "Revit YYYY", lift it as app_name.
        app = _re.search(r"Revit\s+([0-9]{4})", build.group(1))
        if app:
            info["app_name"] = f"Revit {app.group(1)}"

    return info


def detect_converter_version(extension: str) -> dict[str, str | None]:
    """‌⁠‍Detect the installed DDC converter's version.

    On Linux: uses ``dpkg-query -f '${Version}\\n' -W ddc-<ext>converter``
    to read the apt-installed package version.

    On Windows: returns the converter binary's file size as a weak
    fingerprint plus the parent-dir name (per-format install dir often
    carries the version, e.g. ``rvt_windows_v18.0.0``).

    Returns a dict ``{"version": str | None, "source": str | None,
    "binary_path": str | None}``. Never raises.
    """
    result: dict[str, str | None] = {"version": None, "source": None, "binary_path": None}
    exe = find_converter(extension)
    if exe is None:
        return result
    result["binary_path"] = str(exe)

    # Linux: ask dpkg about the apt package.
    if sys.platform.startswith("linux"):
        try:
            import subprocess

            for pkg in (f"ddc-{extension}converter", f"ddc-{extension}-converter"):
                proc = subprocess.run(
                    ["dpkg-query", "-f", "${Version}", "-W", pkg],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=4,
                )
                if proc.returncode == 0 and proc.stdout:
                    version_str = proc.stdout.decode("utf-8", errors="replace").strip()
                    if version_str:
                        result["version"] = version_str
                        result["source"] = f"dpkg:{pkg}"
                        return result
        except (FileNotFoundError, OSError, Exception) as exc:  # noqa: BLE001
            logger.debug("dpkg-query unavailable or failed: %s", exc)

    # Windows or dpkg fallback: parent-dir name often encodes the version,
    # e.g. ~/.openestimator/converters/rvt_windows -> "rvt_windows".
    result["source"] = "binary_metadata"
    parent_name = exe.parent.name
    if parent_name and parent_name not in {"bin", "usr"}:
        result["version"] = parent_name
    return result


# ── Per-binary CLI capability matrix ──────────────────────────────────────
#
# Different DDC RvtExporter / IfcExporter builds accept different positional
# arguments and flags.  Older releases (the ones a user already has installed
# on disk) reject anything beyond ``<input> <output>``; newer releases accept
# a depth-mode token (``standard`` / ``complete``) and the ``-no-collada``
# flag we use to skip the geometry pass.
#
# The platform's invocation has historically appended those extra tokens
# unconditionally — which produces a ``The following arguments were not
# expected`` failure on old binaries even though they could otherwise
# convert the file just fine.  This matrix records what each installed
# binary actually understands so ``ifc_processor._run_ddc`` can build a
# version-tolerant command line.
#
# Cache key is the resolved binary path (str), so a user with two
# extensions sharing the same install dir gets one probe per binary.  We
# also keep a per-extension "negative" sentinel so we don't re-probe a
# missing converter on every call.
_CONVERTER_CAPABILITIES: dict[str, dict[str, Any]] = {}


# ── CLI profile identifiers ───────────────────────────────────────────────
#
# DDC has shipped three distinct CLI shapes that we have to deal with:
#
#   * ``v18_flag``       — v18.x.x: flag-driven, e.g.
#                          ``RvtExporter input -x out.xlsx -d out.dae
#                          -m standard --force-path --no-dae --no-xlsx``.
#                          New keys: -x/--xlsx, -d/--dae, --no-dae,
#                          --no-xlsx, -m/--mode, --force-path.
#                          REJECTS the legacy positional ``standard`` and
#                          flag ``-no-collada`` with ``exit 15``.
#
#   * ``v17_positional`` — v17.x.x: positional + a couple of optional flags.
#                          ``RvtExporter input output [standard|complete]
#                          [-no-collada]``. Modern enough to advertise
#                          ``-no-collada`` in --help; pre-v18 so doesn't
#                          know ``--no-dae`` or ``--force-path``.
#
#   * ``legacy``         — pre-v17 / unknown old binary. Only accepts the
#                          bare ``[exe, input, output]`` shape.
#
#   * ``unknown``        — no binary installed (sentinel for "don't cache").
#
# ``cli_profile`` is the canonical key; the legacy booleans
# (``accepts_depth_mode`` / ``accepts_no_collada_flag``) are kept for
# back-compat with code paths that pre-date v18.
CLI_PROFILE_V18_FLAG = "v18_flag"
CLI_PROFILE_V17_POSITIONAL = "v17_positional"
CLI_PROFILE_LEGACY = "legacy"
CLI_PROFILE_UNKNOWN = "unknown"


def _default_capabilities() -> dict[str, Any]:
    """‌⁠‍Conservative defaults for an unknown/old binary.

    Old DDC CLIs only accept ``[converter, input, output]`` — they reject
    the depth-mode positional and the ``-no-collada`` flag.  When the probe
    fails we fall back to this profile so the retry path matches what
    ``_run_ddc`` would have emitted as its second-attempt fallback.
    """
    return {
        "accepts_depth_mode": False,
        "accepts_no_collada_flag": False,
        # v18-specific flag capabilities — all False on the legacy profile.
        "accepts_flag_xlsx": False,
        "accepts_flag_dae": False,
        "accepts_flag_no_dae": False,
        "accepts_flag_no_xlsx": False,
        "accepts_flag_mode": False,
        "accepts_flag_force_path": False,
        "legacy_positional_input_output": True,
        "cli_profile": CLI_PROFILE_LEGACY,
        "version_text": None,
        "probed": True,
    }


def _modern_capabilities(version_text: str | None = None) -> dict[str, Any]:
    """‌⁠‍Capability profile for a confirmed v17-era DDC binary.

    "Modern" historically meant v17.x (positional CLI that DID accept
    ``standard`` and ``-no-collada``). v18+ uses a different shape — see
    ``_v18_capabilities`` and ``CLI_PROFILE_V18_FLAG``. This constructor
    is retained for back-compat with tests and any external caller that
    has the v17 banner in hand.
    """
    return {
        "accepts_depth_mode": True,
        "accepts_no_collada_flag": True,
        "accepts_flag_xlsx": False,
        "accepts_flag_dae": False,
        "accepts_flag_no_dae": False,
        "accepts_flag_no_xlsx": False,
        "accepts_flag_mode": False,
        "accepts_flag_force_path": False,
        "legacy_positional_input_output": True,
        "cli_profile": CLI_PROFILE_V17_POSITIONAL,
        "version_text": version_text,
        "probed": True,
    }


def _v18_capabilities(version_text: str | None = None) -> dict[str, Any]:
    """‌⁠‍Capability profile for a confirmed DDC v18.x flag-driven binary.

    v18 dropped the legacy positional output path AND the ``-no-collada``
    flag in favour of:

      ``RvtExporter <input> -x <xlsx> -d <dae> -m {basic|standard|complete}
       --force-path [--no-dae] [--no-xlsx]``

    The legacy boolean flags (``accepts_depth_mode`` /
    ``accepts_no_collada_flag``) are set to False here because the
    pre-v18 invocation builder must NOT try to emit those tokens —
    v18 rejects them with ``exit 15: arguments were not expected``.
    """
    return {
        "accepts_depth_mode": False,
        "accepts_no_collada_flag": False,
        "accepts_flag_xlsx": True,
        "accepts_flag_dae": True,
        "accepts_flag_no_dae": True,
        "accepts_flag_no_xlsx": True,
        "accepts_flag_mode": True,
        "accepts_flag_force_path": True,
        "legacy_positional_input_output": False,
        "cli_profile": CLI_PROFILE_V18_FLAG,
        "version_text": version_text,
        "probed": True,
    }


# ── Help-text parsing ─────────────────────────────────────────────────────
#
# The v18 help text contains the word ``complete`` (in the mode-preset
# enum ``{basic,standard,complete,custom}``), which historically caused a
# false-positive against the substring-based ``_MODERN_HELP_MARKERS`` —
# the conversion path would then emit ``standard`` + ``-no-collada`` and
# eat ``exit 15`` from the v18 binary.
#
# Token-based detection avoids that trap: we split the help text into
# whitespace-delimited tokens and check for the LITERAL flag spellings
# that v18 (and only v18) advertises. ``--force-path``, ``--no-dae`` and
# ``--no-xlsx`` are all v18-exclusive — none of them appear in any v17 or
# older help text. ``-no-collada`` is v17-exclusive: v18 dropped it.

_V18_EXCLUSIVE_TOKENS = (
    "--force-path",
    "--no-dae",
    "--no-xlsx",
)
# Tokens that prove v17-era CLI (positional + ``-no-collada``). The leading
# single dash is intentional — v17 used the GNU long-style ``-no-collada``
# (not ``--no-collada``).
_V17_EXCLUSIVE_TOKENS = ("-no-collada",)


def _tokenize_help(text: str) -> set[str]:
    """‌⁠‍Split DDC --help output into a set of whitespace-delimited tokens.

    Strips trailing punctuation that the CLI11 / Qt help formatter
    sometimes appends (``,`` / ``.`` / ``;``) so an exact-match lookup
    against ``"--no-dae"`` finds the token even when it appears mid-line
    as ``--no-dae,`` in a comma-separated alias list. Lower-cases the
    output because DDC has shipped both ``--No-Dae`` and ``--no-dae`` in
    different builds.
    """
    tokens: set[str] = set()
    for raw in text.split():
        tok = raw.strip().lower().strip(",.;:()[]{}")
        if tok:
            tokens.add(tok)
    return tokens


def _classify_help_text(text: str) -> str:
    """‌⁠‍Pick the CLI profile from a probed --help / --version blob.

    Returns one of the ``CLI_PROFILE_*`` constants. Resolution order:

      1. Any v18-exclusive token present → ``v18_flag`` (highest precedence
         because v18 binaries also mention ``complete`` in their mode enum
         which would otherwise hit the v17 heuristic).
      2. Any v17-exclusive token present → ``v17_positional``.
      3. Otherwise → ``legacy``.

    Lower-cased input is expected — the probe already normalises.
    """
    tokens = _tokenize_help(text)
    if any(tok in tokens for tok in _V18_EXCLUSIVE_TOKENS):
        return CLI_PROFILE_V18_FLAG
    if any(tok in tokens for tok in _V17_EXCLUSIVE_TOKENS):
        return CLI_PROFILE_V17_POSITIONAL
    return CLI_PROFILE_LEGACY


# Substrings in ``--help`` / ``--version`` output that confirm the CLI
# understands the modern argument shape.  Retained for back-compat with
# tests that import this constant directly; new code should call
# ``_classify_help_text`` which is token-based and false-positive-free.
_MODERN_HELP_MARKERS = (
    "-no-collada",
    "--no-collada",
    "no-collada",
    "complete",  # the depth-mode token only newer CLIs document
)


def build_ddc_args(
    converter: Path,
    input_path: Path,
    *,
    caps: dict[str, Any],
    xlsx_out: Path | None = None,
    dae_out: Path | None = None,
    mode: str = "standard",
    include_no_dae: bool = False,
    include_no_xlsx: bool = False,
) -> list[str]:
    """‌⁠‍Compose a DDC converter command line that matches the binary's CLI shape.

    Single source of truth for the v18-flag / v17-positional split. The
    caller picks which outputs it wants by passing ``xlsx_out`` / ``dae_out``;
    ``include_no_dae`` / ``include_no_xlsx`` let the v18 path actively
    suppress the OTHER output so the converter doesn't spend time writing
    something the caller will discard. The v17 path approximates the same
    optimisation via the older ``-no-collada`` flag.

    The legacy (``v17_positional`` / ``legacy``) path keeps the historical
    behaviour: one output path per invocation as the third positional
    arg. Callers who need both outputs run two invocations (XLSX pass +
    DAE pass), which is exactly what ``ifc_processor._try_cad2data``
    already does in parallel.

    For ``v18_flag`` we DO emit both ``-x`` and ``-d`` in the same call
    when both are requested — saves loading the RVT a second time. Callers
    that want sequential passes (matching the v17 codepath) can still do
    so by calling this twice with only one of ``xlsx_out`` / ``dae_out``
    populated each time.
    """
    profile = caps.get("cli_profile", CLI_PROFILE_LEGACY)
    args: list[str] = [str(converter), str(input_path)]

    if profile == CLI_PROFILE_V18_FLAG:
        if xlsx_out is not None:
            args.extend(["-x", str(xlsx_out)])
        if dae_out is not None:
            args.extend(["-d", str(dae_out)])
        if include_no_dae and caps.get("accepts_flag_no_dae"):
            args.append("--no-dae")
        if include_no_xlsx and caps.get("accepts_flag_no_xlsx"):
            args.append("--no-xlsx")
        if caps.get("accepts_flag_mode"):
            args.extend(["-m", mode])
        if caps.get("accepts_flag_force_path"):
            args.append("--force-path")
        return args

    # Legacy / v17 positional path — single output target per call.
    out_path = xlsx_out if xlsx_out is not None else dae_out
    if out_path is None:
        raise ValueError("build_ddc_args (legacy profile) requires at least one of xlsx_out or dae_out")
    args.append(str(out_path))
    if caps.get("accepts_depth_mode"):
        args.append(mode)
    # v17 only knows how to *skip* COLLADA; it has no flag to skip XLSX.
    # ``include_no_dae=True`` on the legacy path maps to the v17 spelling
    # ``-no-collada``.
    if include_no_dae and caps.get("accepts_no_collada_flag"):
        args.append("-no-collada")
    return args


def detect_converter_capabilities(extension: str) -> dict[str, Any]:
    """‌⁠‍Probe the installed DDC converter to learn which CLI args it accepts.

    The probe runs the binary with ``--help`` (and falls back to
    ``--version``); both calls are cheap (sub-second, no file IO).
    Results are cached per-binary-path for the lifetime of the process so
    subsequent conversions don't pay the probe cost.

    Returns a dict with the keys:
      * ``accepts_depth_mode`` (bool) — append ``standard`` / ``complete``?
      * ``accepts_no_collada_flag`` (bool) — append ``-no-collada``?
      * ``version_text`` (str | None) — raw probe output (debug only)
      * ``probed`` (bool) — True once the binary was actually executed

    If the probe itself fails (non-zero exit, no recognizable output,
    process never started), the conservative "old CLI" profile is
    returned and cached — so the conversion path skips the extra args
    and avoids the exit-15 trap.
    """
    exe = find_converter(extension)
    if exe is None:
        # No binary installed at all — nothing to probe; mark as not-probed
        # so a later install can trigger a fresh detect.
        return {
            "accepts_depth_mode": False,
            "accepts_no_collada_flag": False,
            "accepts_flag_xlsx": False,
            "accepts_flag_dae": False,
            "accepts_flag_no_dae": False,
            "accepts_flag_no_xlsx": False,
            "accepts_flag_mode": False,
            "accepts_flag_force_path": False,
            "legacy_positional_input_output": False,
            "cli_profile": CLI_PROFILE_UNKNOWN,
            "version_text": None,
            "probed": False,
        }

    cache_key = str(exe)
    cached = _CONVERTER_CAPABILITIES.get(cache_key)
    if cached is not None:
        return cached

    import subprocess

    probe_text = ""
    probe_ok = False
    for flag in ("--help", "-h", "--version"):
        try:
            proc = subprocess.run(
                [str(exe), flag],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(exe.parent),
                input=b"\n",
                timeout=8,
            )
        except (FileNotFoundError, PermissionError, OSError) as exc:
            logger.debug("Converter probe (%s %s) failed to start: %s", exe, flag, exc)
            continue
        except subprocess.TimeoutExpired:
            logger.debug("Converter probe (%s %s) timed out", exe, flag)
            continue

        # DDC binaries occasionally emit their banner on stderr instead of
        # stdout; combine both so the marker scan doesn't miss it.
        out = (proc.stdout or b"") + b"\n" + (proc.stderr or b"")
        try:
            text = out.decode("utf-8", errors="replace").lower()
        except UnicodeError:
            text = ""
        if text.strip():
            probe_text = text
            # Any non-empty banner counts as "we successfully spoke to the
            # binary" — even an exit-1 from ``-h`` on a CLI that wants
            # ``--help``.  The marker scan below decides the actual profile.
            probe_ok = True
            break

    if not probe_ok or not probe_text:
        # Probe failed entirely → assume old CLI.  This is the SAFE branch:
        # if we're wrong and the binary is actually modern, we just lose
        # the COLLADA-skip optimisation but conversion still succeeds.
        caps = _default_capabilities()
        _CONVERTER_CAPABILITIES[cache_key] = caps
        logger.info(
            "DDC capability probe for %s produced no usable output — "
            "assuming legacy CLI (no depth-mode, no -no-collada)",
            exe.name,
        )
        return caps

    # Classify the probed help text against the v18 / v17 / legacy
    # decision tree.  Token-based — see ``_classify_help_text`` for why
    # substring matching was retired (v18 mentions ``complete`` in its
    # mode-preset enum, which used to false-positive the legacy
    # ``_MODERN_HELP_MARKERS`` substring check and emit ``-no-collada``
    # against a v18 binary that rejects it with exit 15).
    profile = _classify_help_text(probe_text)
    if profile == CLI_PROFILE_V18_FLAG:
        caps = _v18_capabilities(version_text=probe_text[:512])
        _CONVERTER_CAPABILITIES[cache_key] = caps
        logger.info(
            "DDC capability probe for %s detected v18 flag CLI (--no-dae / --no-xlsx / --force-path / -m mode)",
            exe.name,
        )
        return caps
    if profile == CLI_PROFILE_V17_POSITIONAL:
        caps = _modern_capabilities(version_text=probe_text[:512])
        _CONVERTER_CAPABILITIES[cache_key] = caps
        logger.info(
            "DDC capability probe for %s detected v17 positional CLI (depth-mode + -no-collada accepted)",
            exe.name,
        )
        return caps

    # Help worked but no modern marker → treat as legacy.  Surfaced at INFO
    # because this is the path the v4.6.2 user-reported bug originally hit.
    caps = _default_capabilities()
    _CONVERTER_CAPABILITIES[cache_key] = caps
    logger.info(
        "DDC capability probe for %s did not advertise modern flags — "
        "assuming legacy CLI (no depth-mode, no -no-collada)",
        exe.name,
    )
    return caps


def invalidate_converter_capabilities(extension: str | None = None) -> None:
    """‌⁠‍Drop the cached capability profile so the next conversion re-probes.

    Call this after a reinstall / update so an upgraded binary's new
    argument shape is picked up without a service restart.  Matches the
    sibling ``invalidate_converter_health`` API.
    """
    if extension is None:
        _CONVERTER_CAPABILITIES.clear()
        return
    exe = find_converter(extension)
    if exe is not None:
        _CONVERTER_CAPABILITIES.pop(str(exe), None)


def invalidate_converter_health(extension: str | None = None) -> None:
    """Drop cached health for one or all converters.

    Call this after a successful install / uninstall so the next health
    poll re-runs the smoke test instead of reading a stale "failed" or
    "ok" entry.
    """
    if extension is None:
        _HEALTH_CACHE.clear()
    else:
        _HEALTH_CACHE.pop(extension, None)
    # Capabilities are tied 1:1 to the installed binary — drop them in
    # lock-step so a reinstall picks up the new CLI shape immediately.
    invalidate_converter_capabilities(extension)


async def convert_cad_to_excel(
    input_path: Path,
    output_dir: Path,
    extension: str,
) -> Path | None:
    """Run a DDC converter to transform a CAD file into Excel.

    The converter is executed as a subprocess with a 5-minute timeout.

    Args:
        input_path: Path to the uploaded CAD file.
        output_dir: Directory where the Excel output should be written.
        extension: Lowercase file extension without dot.

    Returns:
        Path to the generated Excel file, or ``None`` on failure.
    """
    converter = find_converter(extension)
    if not converter:
        logger.error("No converter found for .%s", extension)
        return None

    logger.info("Converting %s using %s", input_path.name, converter.name)

    # Compose the CLI through the capability-aware builder so v18 binaries
    # get ``-x <xlsx> --no-dae -m standard`` (and v17 binaries keep the
    # legacy ``<xlsx> standard -no-collada`` positional shape). Calling
    # the v17 positional form against a v18 binary causes ``exit 15`` with
    # "arguments were not expected: ... standard -no-collada" — the bug
    # the CAD/BIM Data Explorer surfaced as "CAD conversion failed for
    # .rvt file" on every fresh-install with a current DDC binary.
    output_xlsx = output_dir / (input_path.stem + ".xlsx")
    caps = detect_converter_capabilities(extension)
    args = build_ddc_args(
        converter,
        input_path,
        caps=caps,
        xlsx_out=output_xlsx,
        mode="standard",
        # XLSX-only conversion: ask the binary to skip the COLLADA pass.
        # v18 emits ``--no-dae``; v17 emits ``-no-collada``. The legacy
        # profile (no flag) just runs both, which is harmless here.
        include_no_dae=True,
    )

    try:
        import subprocess
        from concurrent.futures import ThreadPoolExecutor

        # DDC converters need DLLs (Qt6Core.dll etc.) from their own directory
        converter_dir = converter.parent

        def _run_converter() -> subprocess.CompletedProcess:
            return subprocess.run(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(converter_dir),
                input=b"\n",  # handle "Press Enter to continue..." prompt
                timeout=300,
            )

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = await loop.run_in_executor(pool, _run_converter)

        if result.returncode != 0:
            logger.error(
                "Converter failed (exit %d): %s",
                result.returncode,
                result.stderr.decode(errors="replace")[:500],
            )
            return None

        # Find the generated Excel file in the output directory
        for f in output_dir.iterdir():
            if f.suffix in (".xlsx", ".xls"):
                return f

        # Also check if xlsx was written directly (not in output_dir)
        if output_xlsx.exists():
            return output_xlsx

        logger.error("No Excel output found in %s after conversion", output_dir)
        return None

    except subprocess.TimeoutExpired:
        logger.error("Converter timed out after 300s for %s", input_path.name)
        return None
    except Exception:
        logger.exception("Converter error for %s", input_path.name)
        return None


def parse_cad_excel(excel_path: Path) -> list[dict]:
    """Parse the Excel output produced by a DDC converter.

    DDC converters produce Excel files with columns such as:
    Category, Family, Type Name, Count, Volume, Area, Length, Material, etc.

    Args:
        excel_path: Path to the Excel file generated by the converter.

    Returns:
        List of dicts where each dict represents one element row.
    """
    import openpyxl

    wb = openpyxl.load_workbook(excel_path, read_only=True, data_only=True)
    ws = wb.active

    if ws is None:
        wb.close()
        return []

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        wb.close()
        return []

    # First row is the header; strip DDC type suffixes like " : String", " : Double"
    raw_headers = [str(h or "").strip() for h in rows[0]]
    headers = [h.split(" : ")[0].strip().lower() if " : " in h else h.lower() for h in raw_headers]

    elements: list[dict] = []
    for row in rows[1:]:
        if not any(row):
            continue

        item: dict = {}
        for i, header in enumerate(headers):
            if i < len(row):
                val = row[i]
                if val is not None:
                    item[header] = val

        if item:
            elements.append(item)

    wb.close()
    return elements


def summarize_cad_elements(elements: list[dict]) -> str:
    """Create a text summary of CAD elements suitable for AI processing.

    The summary is a tabular representation of element categories, types,
    counts, volumes, and areas. Limited to 200 elements to stay within
    AI context window limits.

    Args:
        elements: List of element dicts from ``parse_cad_excel``.

    Returns:
        Human-readable text summary of the CAD model contents.
    """
    if not elements:
        return "No elements found in the CAD file."

    lines = [f"CAD/BIM file contains {len(elements)} elements:\n"]
    lines.append("Category | Type | Count | Volume (m3) | Area (m2)")
    lines.append("-" * 60)

    for el in elements[:200]:  # Limit to 200 elements for AI context
        category = el.get("category", el.get("element type", "unknown"))
        type_name = el.get("type name", el.get("family", el.get("type", "")))
        count = el.get("count", 1)
        volume = el.get("volume", el.get("volume (m3)", ""))
        area = el.get("area", el.get("area (m2)", ""))

        lines.append(f"{category} | {type_name} | {count} | {volume} | {area}")

    if len(elements) > 200:
        lines.append(f"\n... and {len(elements) - 200} more elements (truncated)")

    return "\n".join(lines)


def _to_float(val: object) -> float:
    """Safely convert a value to float, returning 0.0 on failure.

    Rejects NaN / ±Infinity (a converter occasionally emits ``inf`` for a
    degenerate solid) so a single bad cell can't poison a whole sum.
    """
    if val is None:
        return 0.0
    try:
        f = float(val)
    except (ValueError, TypeError):
        return 0.0
    if f != f or f in (float("inf"), float("-inf")):
        return 0.0
    return f


# BUG-D-TKC-004b / D-TKC-NEW-05 — canonical quantity synonym map.
#
# DDC / Revit / IFC exporters emit the same physical quantity under a
# wide range of spellings.  The old ``_norm_col`` only stripped a single
# trailing ``(m2|m3)`` suffix when ``len > 4``, so IFC-standard names
# like ``NetVolume`` / ``Qto_WallBaseQuantities.NetVolume`` /
# ``Volume cbm`` / ``sqm`` / ``m³`` never resolved to the canonical
# ``volume`` / ``area`` / ``length`` keys and ``_resolve_column_value``
# silently returned 0.0.
#
# Strategy (applied in order, to a separator-stripped lowercase token):
#   1. Take the LAST dotted segment of an IFC ``Qto_*.X`` form
#      (``qto_wallbasequantities.netvolume`` → ``netvolume``).
#   2. Drop a leading ``net`` / ``gross`` / ``base`` qualifier.
#   3. Drop a trailing metric/imperial unit suffix
#      (m2/m3/sqm/cbm/sqft/cbft/lfm/rmt/lm + bracketed forms).
#   4. Map any surviving synonym to its canonical key via
#      ``_COL_SYNONYM``.
#
# Bare ambiguous single letters (``m``/``t``/``kg``) are still NOT
# stripped — that would mis-merge unrelated columns like ``team``.

# Trailing unit-suffix tokens that carry no semantic meaning of their
# own (they only annotate the unit of the preceding quantity word).
_UNIT_SUFFIXES: tuple[str, ...] = (
    "m3",
    "m2",
    "cbm",
    "sqm",
    "sqmt",
    "cubm",
    "cbft",
    "sqft",
    "lfm",
    "rmt",
    "lm",
    "rm",
    "cum",
    "sm",
)

# Canonical synonym map: normalised token → canonical column key.
# Every value is one of the keys ``group_cad_*`` / the suggested
# ``sum_columns`` understand: ``volume`` / ``area`` / ``length`` /
# ``count`` / ``weight``.
_COL_SYNONYM: dict[str, str] = {
    "volume": "volume",
    "vol": "volume",
    "cubage": "volume",
    "cubature": "volume",
    "area": "area",
    "surface": "area",
    "surfacearea": "area",
    "footprint": "area",
    "length": "length",
    "len": "length",
    "perimeter": "length",
    "running": "length",
    "count": "count",
    "qty": "count",
    "quantity": "count",
    "number": "count",
    "nr": "count",
    "weight": "weight",
    "mass": "weight",
}


def _instance_count(raw: object) -> float:
    """Resolve a per-element-row ``count`` cell to a physical instance count.

    Each row produced by :func:`parse_cad_excel` represents exactly one
    physical element.  The ``count`` column, when present, is a multiplier
    for rows that legitimately stand for several identical instances
    (e.g. an array of 4 fixtures collapsed onto one row).

    BUG-D-TKC-017: a missing ``count`` column, an empty/blank cell, or an
    explicit ``0`` / negative value must still count the single physical
    instance the row represents (return ``1.0``).  Only a value strictly
    greater than 1 is honoured as an aggregate multiplier; a value of
    exactly 1 is the trivial single instance.
    """
    if raw is None:
        return 1.0
    if isinstance(raw, str) and not raw.strip():
        return 1.0
    n = _to_float(raw)
    return n if n >= 1.0 else 1.0


def _norm_col(name: str) -> str:
    """Normalise a column name to a canonical quantity key.

    Resolves the many DDC / Revit / IFC spellings of the same physical
    quantity to a single key so ``sum_columns=['volume'|'area'|'length']``
    works regardless of how the converter labelled the column.

    Handles, among others::

        volume / Volume / "Volume (m3)" / volume_m3 / "Volume [m³]"
        NetVolume / GrossVolume / "Net Volume" / "Gross Area"
        Qto_WallBaseQuantities.NetVolume / Qto_SlabBaseQuantities.GrossArea
        "Volume cbm" / sqm / m³ / m² / lfm / rmt

    Unknown columns fall through to a deterministic separator-stripped
    lowercase token (back-compat: e.g. ``"Type Name"`` → ``typename``).
    """
    import re

    s = str(name).strip().lower()
    s = s.replace("²", "2").replace("³", "3")
    # Drop a trailing unit qualifier in brackets/parens: "volume (m3)",
    # "area [m2]", "weight {kg}".
    s = re.sub(r"[\s,]*[([{].*?[)\]}]\s*$", "", s)
    # IFC ``Qto_<set>.<Quantity>`` dotted form — keep only the final
    # quantity segment ("qto_wallbasequantities.netvolume" → "netvolume").
    if "." in s:
        s = s.rsplit(".", 1)[-1]
    # Collapse separators ("volume_m3" → "volumem3", "type name" → "typename",
    # "net volume" → "netvolume").
    s = re.sub(r"[\s_\-/:]+", "", s)

    # Strip a leading Net / Gross / Base quantity qualifier
    # ("netvolume" → "volume", "grossarea" → "area",
    # "basequantitiesvolume" → "volume").  Loop so "netbasequantities*"
    # style stacked prefixes peel fully.
    for _ in range(4):
        m = re.match(r"^(net|gross|base|total|sum|adjusted|basequantities)(.+)$", s)
        if not m or len(m.group(2)) < 2:
            break
        s = m.group(2)

    # Strip a trailing unit suffix ("volumem3" → "volume",
    # "aream2" → "area", "volumecbm" → "volume", "lengthlfm" → "length").
    # Only strip when something meaningful remains in front so a bare
    # unit token ("m3"/"sqm"/"cbm") is preserved for the synonym pass
    # below (it maps to a canonical key by unit alone).
    for suf in sorted(_UNIT_SUFFIXES, key=len, reverse=True):
        if s.endswith(suf) and len(s) > len(suf) + 1:
            s = s[: -len(suf)]
            break

    # Bare-unit columns: a converter sometimes labels the only volume
    # column simply "m3" / "cbm" or the area column "sqm" / "m2".
    _BARE_UNIT_CANON = {
        "m3": "volume",
        "cbm": "volume",
        "cum": "volume",
        "cubm": "volume",
        "cbft": "volume",
        "m2": "area",
        "sqm": "area",
        "sqmt": "area",
        "sqft": "area",
        "sm": "area",
        "lfm": "length",
        "rmt": "length",
        "lm": "length",
        "rm": "length",
    }
    if s in _BARE_UNIT_CANON:
        return _BARE_UNIT_CANON[s]

    # Final canonical synonym mapping (exact token match only — we never
    # map a substring so "team"/"kgrid" stay untouched).
    return _COL_SYNONYM.get(s, s)


def _resolve_column_value(el: dict, col: str) -> float:
    """Look up ``col`` in an element dict, tolerant of DDC name variants.

    Tries the exact key first (fast path), then falls back to a
    normalised-name match so ``sum_columns=['volume']`` still finds a
    converter that wrote ``'Volume (m3)'`` (BUG-D-TKC-004).
    """
    if col in el:
        return _to_float(el.get(col))
    target = _norm_col(col)
    for k, v in el.items():
        if _norm_col(k) == target:
            return _to_float(v)
    return 0.0


def group_cad_elements(elements: list[dict]) -> dict:
    """Group CAD elements by category and type, summing numeric quantities.

    Produces a structured dict of quantity tables suitable for direct display
    without AI processing. Each category contains type-level rows with summed
    count, volume (m3), area (m2), and length (m).

    Handles DDC column name variations:
    - ``category`` / ``element type`` -> category
    - ``type name`` / ``family`` / ``type`` -> type
    - ``volume`` / ``volume (m3)`` -> volume
    - ``area`` / ``area (m2)`` -> area
    - ``count`` defaults to 1

    Args:
        elements: List of element dicts from ``parse_cad_excel``.

    Returns:
        Dict with ``groups`` (list), ``grand_totals``, and ``total_elements``.
    """
    from collections import OrderedDict

    # category -> type -> aggregated values
    cat_types: dict[str, dict[str, dict]] = OrderedDict()

    for el in elements:
        raw_cat = str(el.get("category", el.get("element type", "Other"))).strip()
        category = raw_cat if raw_cat and raw_cat != "None" else "Other"
        type_name = str(el.get("type name", el.get("family", el.get("type", "Unknown")))).strip() or "Unknown"
        # BUG-D-TKC-017 — each row from ``parse_cad_excel`` is ONE physical
        # element.  The optional ``count`` column is a per-element multiplier
        # (e.g. an array/group of 4 identical fixtures on one row).  A
        # missing column, an empty cell, or an explicit ``0`` must still
        # contribute the single physical instance the row represents — the
        # old ``_to_float(el.get("count", 1))`` made a ``count=0`` row vanish
        # so two real elements (one with count=0) displayed as count 1.
        # A genuine aggregate multiplier (count > 1) is preserved as-is.
        count = _instance_count(el.get("count"))
        volume = _to_float(el.get("volume", el.get("volume (m3)", 0)))
        area = _to_float(el.get("area", el.get("area (m2)", 0)))
        length = _to_float(el.get("length", 0))
        material = str(el.get("material", "")).strip()

        if category not in cat_types:
            cat_types[category] = OrderedDict()

        if type_name not in cat_types[category]:
            cat_types[category][type_name] = {
                "type": type_name,
                "material": "",
                "count": 0.0,
                "volume_m3": 0.0,
                "area_m2": 0.0,
                "length_m": 0.0,
            }

        entry = cat_types[category][type_name]
        entry["count"] += count
        entry["volume_m3"] += volume
        entry["area_m2"] += area
        entry["length_m"] += length
        if material and not entry["material"]:
            entry["material"] = material

    # Build structured output.
    #
    # BUG-D-TKC-024 — displayed rows MUST reconcile.  Previously the item
    # rows were rounded for display while the category and grand totals
    # were summed from the UNROUNDED running sums, so e.g. 250 rebar rows
    # each displaying 0.000 sat under a non-zero category total — an
    # incoherent table.  Fix: round each item row FIRST, then sum the
    # already-rounded item values into the category total, and sum the
    # rounded category totals into the grand total.  The displayed
    # numbers now add up exactly at every level.
    groups: list[dict] = []
    grand_count = 0.0
    grand_volume = 0.0
    grand_area = 0.0
    grand_length = 0.0

    for cat_name, types in cat_types.items():
        items = list(types.values())

        # Round item values FIRST (display precision per dimension).
        for it in items:
            it["count"] = round(it["count"], 1)
            it["volume_m3"] = round(it["volume_m3"], 3)
            it["area_m2"] = round(it["area_m2"], 2)
            it["length_m"] = round(it["length_m"], 2)

        # Category total = sum of the displayed (rounded) item rows, then
        # rounded again only to clear binary-float dust (e.g.
        # 0.1 + 0.2 → 0.30000000000000004).  The rows now sum exactly to
        # this displayed category total.
        cat_count = round(sum(it["count"] for it in items), 1)
        cat_volume = round(sum(it["volume_m3"] for it in items), 3)
        cat_area = round(sum(it["area_m2"] for it in items), 2)
        cat_length = round(sum(it["length_m"] for it in items), 2)

        groups.append(
            {
                "category": cat_name,
                "items": items,
                "totals": {
                    "count": cat_count,
                    "volume_m3": cat_volume,
                    "area_m2": cat_area,
                    "length_m": cat_length,
                },
            }
        )

        # Grand total = sum of the displayed (rounded) category totals, so
        # the category rows reconcile exactly to the grand total too.
        grand_count += cat_count
        grand_volume += cat_volume
        grand_area += cat_area
        grand_length += cat_length

    return {
        "total_elements": len(elements),
        "groups": groups,
        "grand_totals": {
            "count": round(grand_count, 1),
            "volume_m3": round(grand_volume, 3),
            "area_m2": round(grand_area, 2),
            "length_m": round(grand_length, 2),
        },
    }


def get_available_columns(elements: list[dict], file_format: str = "rvt") -> dict[str, Any]:
    """Analyze elements and classify columns into grouping/quantity/text categories.

    Scans all elements to discover column names, then classifies each column
    based on its content:
    - **quantity**: >50% numeric values AND name suggests a measurement
      (or is purely numeric across all non-None values).
    - **grouping**: string columns with <500 unique values — suitable for
      GROUP BY operations (e.g. category, type name, level, material).
    - **text**: everything else (ids, long descriptions with too many uniques).

    Also provides ``suggested_grouping``, ``suggested_quantities``,
    format-specific ``presets``, and ``unit_labels`` based on common DDC
    converter output conventions.

    Args:
        elements: List of element dicts from ``parse_cad_excel``.
        file_format: Lowercase file extension without dot (e.g. ``"rvt"``, ``"ifc"``).

    Returns:
        Dict with keys ``grouping``, ``quantity``, ``text``,
        ``suggested_grouping``, ``suggested_quantities``, ``presets``,
        and ``unit_labels``.
    """
    if not elements:
        return {
            "grouping": [],
            "quantity": [],
            "text": [],
            "suggested_grouping": [],
            "suggested_quantities": [],
            "presets": {},
            "unit_labels": {},
            "confidence": {},
        }

    # Collect all unique column names across every element
    all_columns: set[str] = set()
    for el in elements:
        all_columns.update(el.keys())

    # Keywords that indicate a quantity / measurement column
    quantity_keywords = {
        "volume",
        "area",
        "length",
        "width",
        "height",
        "count",
        "weight",
        "perimeter",
        "thickness",
        "depth",
        "radius",
        "diameter",
        "mass",
        "quantity",
    }

    grouping_cols: list[str] = []
    quantity_cols: list[str] = []
    text_cols: list[str] = []

    for col in all_columns:
        # Gather non-None values for this column
        values = [el[col] for el in elements if col in el and el[col] is not None]
        if not values:
            text_cols.append(col)
            continue

        # Check how many values are numeric
        numeric_count = 0
        for v in values:
            try:
                float(v)
                numeric_count += 1
            except (ValueError, TypeError):
                pass

        total = len(values)
        numeric_ratio = numeric_count / total if total > 0 else 0.0

        # Does the column name hint at a quantity?
        col_lower = col.lower()
        name_is_quantity = any(kw in col_lower for kw in quantity_keywords)

        # Classify
        if numeric_ratio > 0.5 and (name_is_quantity or numeric_ratio == 1.0):
            quantity_cols.append(col)
        else:
            # Count unique string values to decide grouping vs text
            unique_values = {str(v) for v in values}
            if len(unique_values) < 500:
                grouping_cols.append(col)
            else:
                text_cols.append(col)

    # Sort each list alphabetically for deterministic output
    grouping_cols.sort()
    quantity_cols.sort()
    text_cols.sort()

    # Suggested defaults based on common DDC converter output
    suggested_grouping: list[str] = []
    suggested_quantities: list[str] = []

    # Preferred grouping columns (in priority order)
    for candidate in ["category", "type name", "family", "level", "material", "workset"]:
        if candidate in grouping_cols:
            suggested_grouping.append(candidate)
    # Default to first two if none of the preferred ones matched
    if not suggested_grouping and grouping_cols:
        suggested_grouping = grouping_cols[:2]

    # Preferred quantity columns
    for candidate in ["volume", "area", "length", "count"]:
        if candidate in quantity_cols:
            suggested_quantities.append(candidate)
    # Fall back to all quantity columns if none matched
    if not suggested_quantities:
        suggested_quantities = quantity_cols[:4]

    # Format-specific QTO presets
    presets: dict[str, dict] = {}

    # "count" is always available — it's computed as number of elements per group
    # (not a column from the file, but calculated during grouping)
    available_qty = set(quantity_cols) | {"count"}

    if file_format in ("rvt", "rfa"):
        presets = {
            "standard": {
                "label": "Standard Revit QTO",
                "description": "Category + Type Name — standard Revit breakdown",
                "group_by": [c for c in ["category", "type name"] if c in grouping_cols],
                "sum_columns": [c for c in ["volume", "area", "count"] if c in available_qty],
            },
            "detailed": {
                "label": "Detailed (with Level)",
                "description": "Category + Type Name + Level — per-floor breakdown",
                "group_by": [c for c in ["category", "type name", "level"] if c in grouping_cols],
                "sum_columns": [c for c in ["volume", "area", "length", "count"] if c in available_qty],
            },
            "by_family": {
                "label": "By Family",
                "description": "Family + Type — for procurement and ordering",
                "group_by": [c for c in ["family", "type name"] if c in grouping_cols],
                "sum_columns": [c for c in ["count", "volume", "area"] if c in available_qty],
            },
            "summary": {
                "label": "Quick Summary",
                "description": "Category only — high-level overview",
                "group_by": [c for c in ["category"] if c in grouping_cols],
                "sum_columns": [c for c in ["count", "volume", "area"] if c in available_qty],
            },
        }
    elif file_format == "ifc":
        presets = {
            "standard": {
                "label": "Standard IFC QTO",
                "description": "Group by Category + Type — standard IFC entity breakdown",
                "group_by": [c for c in ["category", "type name", "type"] if c in grouping_cols][:2],
                "sum_columns": [c for c in ["volume", "area", "count"] if c in available_qty],
            },
            "detailed": {
                "label": "Detailed (with Level)",
                "description": "Category + Type + Level — per-floor breakdown",
                "group_by": [c for c in ["category", "type name", "type", "level"] if c in grouping_cols][:3],
                "sum_columns": [c for c in ["volume", "area", "length", "count"] if c in available_qty],
            },
            "by_storey": {
                "label": "By Building Storey",
                "description": "Building Storey + Category + Type — storey-first breakdown",
                "group_by": [c for c in ["level", "category", "type name", "type"] if c in grouping_cols][:3],
                "sum_columns": [c for c in ["volume", "area", "length", "count"] if c in available_qty],
            },
            "by_material": {
                "label": "By Material",
                "description": "Material + Category — material-first grouping for procurement",
                "group_by": [c for c in ["material", "category"] if c in grouping_cols][:2],
                "sum_columns": [c for c in ["volume", "area", "count"] if c in available_qty],
            },
            "summary": {
                "label": "Quick Summary",
                "description": "Category only — high-level element count",
                "group_by": [c for c in ["category"] if c in grouping_cols],
                "sum_columns": [c for c in ["count", "volume", "area"] if c in available_qty],
            },
        }
    elif file_format == "dwg":
        presets = {
            "standard": {
                "label": "Standard DWG QTO",
                "description": "Group by Layer — standard AutoCAD organization",
                "group_by": [c for c in ["layer", "category"] if c in grouping_cols][:1],
                "sum_columns": [c for c in ["count", "length", "area"] if c in available_qty],
            },
        }
    else:
        presets = {
            "standard": {
                "label": "Standard QTO",
                "description": "Default grouping by available categories",
                "group_by": suggested_grouping,
                "sum_columns": suggested_quantities,
            },
        }

    # Remove presets with empty group_by
    presets = {k: v for k, v in presets.items() if v["group_by"]}

    # Confidence scoring: for each column, calculate % of elements with non-null values
    confidence: dict[str, float] = {}
    for col in all_columns:
        non_null = sum(1 for elem in elements if elem.get(col) not in (None, "", "nan", "NaN"))
        confidence[col] = round(non_null / len(elements), 2) if elements else 0

    # Unit labels for quantity columns (+ "count" which is always available)
    unit_labels: dict[str, str] = {"count": "pcs"}
    for col in quantity_cols:
        col_lower = col.lower()
        if "volume" in col_lower:
            unit_labels[col] = "m\u00b3"
        elif "area" in col_lower:
            unit_labels[col] = "m\u00b2"
        elif "length" in col_lower or "perimeter" in col_lower:
            unit_labels[col] = "m"
        elif "weight" in col_lower or "mass" in col_lower:
            unit_labels[col] = "kg"
        elif "count" in col_lower:
            unit_labels[col] = "pcs"
        else:
            unit_labels[col] = ""

    return {
        "grouping": grouping_cols,
        "quantity": quantity_cols,
        "text": text_cols,
        "suggested_grouping": suggested_grouping,
        "suggested_quantities": suggested_quantities,
        "presets": presets,
        "unit_labels": unit_labels,
        "confidence": confidence,
    }


def group_cad_elements_dynamic(
    elements: list[dict],
    group_by: list[str],
    sum_columns: list[str],
) -> dict:
    """Group elements by user-selected columns, sum user-selected quantities.

    This is the interactive counterpart to ``group_cad_elements`` — instead
    of hardcoded category/type grouping, the caller selects which columns
    to group by and which numeric columns to sum.

    Args:
        elements: List of element dicts from ``parse_cad_excel``.
        group_by: Column names to use as group key (e.g. ``["category", "type name"]``).
        sum_columns: Numeric column names to aggregate (e.g. ``["volume", "area"]``).

    Returns:
        Dict with ``total_elements``, ``group_by``, ``sum_columns``, ``groups``
        (list of group dicts), and ``grand_totals``.
    """
    from collections import OrderedDict

    groups: dict[str, dict] = OrderedDict()
    grand_totals: dict[str, float] = dict.fromkeys(sum_columns, 0.0)
    grand_totals["count"] = 0.0

    for el in elements:
        # Build the composite group key
        key_parts: dict[str, str] = {}
        for col in group_by:
            raw = el.get(col)
            val = str(raw).strip() if raw is not None else ""
            key_parts[col] = val if val and val != "None" else "(empty)"

        key = " | ".join(key_parts.values())

        if key not in groups:
            groups[key] = {
                "key": key,
                "key_parts": dict(key_parts),
                "count": 0,
                "sums": dict.fromkeys(sum_columns, 0.0),
            }

        entry = groups[key]
        entry["count"] += 1

        # BUG-D-TKC-004: tolerant column lookup — a DDC export that wrote
        # 'Volume (m3)' must still feed sum_columns=['volume'] instead of
        # silently contributing 0.0.
        for col in sum_columns:
            entry["sums"][col] += _resolve_column_value(el, col)

    # BUG-D-TKC-003: accumulate the grand total from the RAW per-group
    # sum, then round each group's displayed value separately. Previously
    # the grand total summed already-rounded group values, so hundreds of
    # sub-0.0001 quantities each rounded to 0.0 and the real total (e.g.
    # 0.014997 m³) vanished entirely.
    raw_grand: dict[str, float] = dict.fromkeys(sum_columns, 0.0)
    result_groups: list[dict] = []
    for g in groups.values():
        for col in sum_columns:
            raw_grand[col] += g["sums"][col]
            g["sums"][col] = round(g["sums"][col], 4)
        result_groups.append(g)

    for col in sum_columns:
        grand_totals[col] = round(raw_grand[col], 4)
    grand_totals["count"] = len(elements)

    return {
        "total_elements": len(elements),
        "group_by": group_by,
        "sum_columns": sum_columns,
        "groups": result_groups,
        "grand_totals": grand_totals,
    }


def _ddc_cad2data_verify() -> bool:
    """DataDrivenConstruction CAD2DATA pipeline verification. DDC-CWICR-2026."""
    _sig = [0x44, 0x44, 0x43, 0x2D, 0x43, 0x57, 0x49, 0x43, 0x52]  # DDC-CWICR
    return all(c > 0 for c in _sig)
