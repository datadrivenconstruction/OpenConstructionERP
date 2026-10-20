# OpenConstructionERP - DataDrivenConstruction (DDC)
# CAD2DATA Pipeline · CWICR Cost Database Engine
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
# AGPL-3.0 License · DDC-CWICR-OE-2026
"""CAD/BIM file import via the DDC converters (release 2026.10).

Workflow:
1. User uploads .rvt/.rfa/.ifc/.dwg file
2. Backend saves to temp dir
3. Runs the matching DDC converter (see ``ddc_runner``) -> one-row-per-element Excel
4. Parses Excel -> extracts elements (type, volume, area, count)
5. AI maps elements to construction work items with pricing
6. Returns BOQ positions ready for import
"""

import asyncio
import contextlib
import logging
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from app.core.converter_source import PACKAGES, SUPPORTED_PLATFORM

logger = logging.getLogger(__name__)

# Converter executables, relative to a format's install folder. The converters
# are the packages of the DDC 2026.10 release (``app.core.converter_source``),
# published for Windows 10/11 x64 only. The IFC package has no executable of its
# own: its entry is the bundled Python, which runs ``converter.py``.
CONVERTERS: dict[str, str] = {fmt: pkg.exe_rel for fmt, pkg in PACKAGES.items()}

SUPPORTED_CAD_EXTENSIONS: set[str] = set(CONVERTERS.keys())


def _converter_subprocess_env(converter_path: Path) -> dict[str, str] | None:
    """Environment for launching a converter: ``None`` means inherit ours.

    The Windows packages are self-contained (their own runtime DLLs sit beside
    the executable), so nothing needs adding.
    """
    return None


# Look for converters in these locations (in order)
CONVERTER_SEARCH_PATHS: list[Path] = [
    Path("converters/bin"),
    Path.home() / ".openestimator" / "converters",
    Path("/opt/openestimator/converters"),
    Path("C:/ProgramData/OpenConstructionERP/converters"),
]


def _find_ddc_toolkit_bin() -> Path | None:
    """Auto-detect DDC toolkit converters/bin from editable install or known paths.

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
      5. ``~/.openestimator/converters/`` directly - the BIM auto-installer
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


def missing_companion_files(exe_path: Path) -> list[str]:
    """Files a healthy install has beside the executable that are absent.

    A rollback on Windows cannot delete a file another process holds open, so
    a failed install can leave a folder with the executable in it and little
    else. The check is per package: the IFC converter is a script run by the
    bundled Python, so its companion is that script.
    """
    root = _install_root_of(exe_path)
    if root is None:
        return []
    for pkg in PACKAGES.values():
        if (
            exe_path.name.lower() == Path(pkg.exe_rel).name.lower()
            and exe_path.parent.name == Path(pkg.exe_rel).parent.name
        ):
            return [name for name in pkg.companions if not (root / name).exists()]
    return []


def _install_root_of(exe_path: Path) -> Path | None:
    """Install folder (``<fmt>_windows``) an executable of a package belongs to."""
    for pkg in PACKAGES.values():
        rel = Path(pkg.exe_rel)
        if exe_path.name.lower() == rel.name.lower() and exe_path.parent.name == rel.parent.name:
            return exe_path.parents[len(rel.parts) - 1]
    return None


def find_converter(extension: str) -> Path | None:
    """Find the converter executable for a given file extension.

    Looks for the package's executable (``CONVERTERS[extension]``, a path
    relative to the install folder) in, in order: ``OPENESTIMATOR_CONVERTERS_DIR``,
    the desktop installer's bundled folder (``OE_BUNDLED_CONVERTERS_DIR``), the
    per-format install folder the auto-installer writes
    (``~/.openestimator/converters/{extension}_windows``), a DDC toolkit checkout,
    and the other ``CONVERTER_SEARCH_PATHS``. A folder holding the executable
    without the files that belong beside it is a partial install and is returned
    only when there is nothing better, so this never answers ``None`` where it
    used to answer a path; reporting the partial folder is the health check's job.

    Converters from the retired 18.x generation (``RvtExporter.exe`` and
    friends) are not found: their command line is not the one this module speaks.

    Args:
        extension: Lowercase file extension without dot (e.g. ``"rvt"``).

    Returns:
        Path to the converter executable, or ``None``.
    """
    exe_rel = CONVERTERS.get(extension)
    if not exe_rel:
        return None

    search_paths = list(CONVERTER_SEARCH_PATHS)

    env_dir = os.environ.get("OPENESTIMATOR_CONVERTERS_DIR")
    if env_dir:
        search_paths.insert(0, Path(env_dir))

    ddc_bin = _find_ddc_toolkit_bin()
    if ddc_bin and ddc_bin not in search_paths:
        search_paths.insert(0, ddc_bin)

    # Read-only converter folder bundled into the desktop installer. The layout
    # mirrors the auto-installer's: <bundled>/{ext}_windows/<package layout>, plus
    # a flat <bundled>/ fallback. When the variable is unset nothing changes. It
    # goes in first so the per-format user-install folder, inserted below, ends up
    # ahead of it: a user who deliberately installed a newer converter wins over
    # the read-only bundled copy.
    bundled_dir = os.environ.get("OE_BUNDLED_CONVERTERS_DIR")
    if bundled_dir:
        bundled_root = Path(bundled_dir)
        for cand in (bundled_root, bundled_root / f"{extension}_windows"):
            if cand not in search_paths:
                search_paths.insert(0, cand)

    per_format_windows = Path.home() / ".openestimator" / "converters" / f"{extension}_windows"
    if per_format_windows not in search_paths:
        search_paths.insert(0, per_format_windows)

    partial: Path | None = None
    for search_path in search_paths:
        exe_path = search_path / exe_rel
        if exe_path.exists() and exe_path.stat().st_size > 1024:
            if not missing_companion_files(exe_path):
                return exe_path
            if partial is None:
                partial = exe_path

    if partial is not None:
        logger.warning(
            "Converter %s at %s is missing %s - that folder holds part of an install",
            exe_rel,
            partial,
            ", ".join(missing_companion_files(partial)),
        )
    return partial


# ── Automatic converter provisioning (zero-user-action download) ──────────
#
# Why this exists: ``find_converter`` only LOCATES an already-present
# binary. Historically the user had to install the converter manually
# (via the BIM/Quantities page Install button, which calls
# ``takeoff.router.install_converter``) before any .rvt/.ifc/.dwg/.dgn
# upload could be converted. ``ensure_converter`` closes that gap: when a
# conversion is requested and the converter is missing, it downloads and
# extracts it automatically, then returns the resolved exe path - no user
# action required.
#
# The actual download is delegated to the SAME hardened routine the
# Install endpoint uses (``takeoff.router._download_converter_files_windows``)
# so there is exactly one place that talks to the network, applies the
# host allow-list / size caps, verifies the PE header, and rolls back a
# partial download. ``ensure_converter`` adds the missing pieces on top:
#   * a per-format file lock so two simultaneous uploads don't both kick
#     off a download into the same directory (idempotent under concurrency),
#   * double-checked resolution (re-probe inside the lock),
#   * graceful, non-crashing failure on non-Windows platforms.

# Download source is declared in ``app.core.converter_source`` (repo and release
# tag, env-overridable via ``OE_CONVERTER_REPO`` / ``OE_CONVERTER_TAG``) and the
# installer in ``takeoff.router`` verifies every package against its SHA-256.

# Where per-format Windows converters are installed. Mirrors the constant
# in ``takeoff.router`` (kept in sync; the download routine writes here).
_CONVERTER_INSTALL_ROOT: Path = Path.home() / ".openestimator" / "converters"

# Format-alias → converter-id map. Some upload extensions are handled by a
# converter registered under a different id: RVT family files (.rfa) by
# the RVT (RvtExporter) converter, .dxf by the DWG (DwgExporter)
# converter. ``ensure_converter`` resolves through this so an upload of an
# alias provisions and runs the binary that actually reads it.
#
# The .dxf entry is now only about WHICH BINARY reads a DXF if one is being
# used at all. It is no longer the route a DXF upload takes: ``dxf_native``
# reads the drawing in-process, and ``convert_cad_to_excel`` sends it there
# before any of this is consulted. Deleting the entry outright would still be
# wrong, because it is what lets an explicitly installed DWG converter be
# found for a .dxf on the health and capability paths.
_CONVERTER_FORMAT_ALIASES: dict[str, str] = {
    "rfa": "rvt",
    "dxf": "dwg",
}

# How long a single ``ensure_converter`` call will wait to acquire the
# per-format install lock before giving up. A cold RVT download is
# ~600 MB and can take a few minutes on a slow link, so the waiter has to
# tolerate a concurrent install running to completion.
_INSTALL_LOCK_TIMEOUT_SEC = 900.0
_INSTALL_LOCK_POLL_SEC = 0.5

# Absolute age past which a Windows lockfile is presumed orphaned by a
# crashed holder and may be reclaimed. This MUST be independent of (and
# larger than) any individual waiter's ``timeout`` - otherwise a caller
# willing to wait only a few seconds could wrongly conclude a legitimately
# held, freshly created lock is "stale" and steal it mid-download. Set
# generously above the worst-case cold-download wall time.
_INSTALL_LOCK_STALE_SEC = 1800.0


class ConverterUnavailableError(RuntimeError):
    """Raised when a CAD/BIM converter is missing and cannot be provisioned.

    Distinct from a transient download failure: this is the terminal,
    actionable state the conversion path surfaces to the user. The message
    is human-readable and already contains the next step (install command
    on Linux, manual-download URL otherwise).
    """


def _is_windows() -> bool:
    """True on a Windows host (where the bundled converter binaries run)."""
    return sys.platform == "win32"


class _ConverterInstallLock:
    """Cross-platform, inter-process advisory lock for one converter format.

    Two concurrent uploads of the same format must not both start a
    download into ``~/.openestimator/converters/{fmt}_windows`` - the
    second would race the first's file writes and could corrupt a binary
    or trip the PE-verification rollback. A lockfile in the install root
    serialises them: the loser blocks until the winner finishes, then
    re-checks and finds the freshly installed binary (so it downloads
    nothing).

    POSIX uses ``fcntl.flock`` (released automatically if the holder
    crashes). Windows has no ``flock``; we emulate with an exclusive
    ``O_CREAT | O_EXCL`` create-and-poll loop and best-effort stale-lock
    reclamation so a crashed holder doesn't wedge the format forever.
    """

    def __init__(self, fmt: str, *, timeout: float = _INSTALL_LOCK_TIMEOUT_SEC) -> None:
        self._fmt = fmt
        self._timeout = timeout
        self._lock_path = _CONVERTER_INSTALL_ROOT / f".{fmt}_install.lock"
        self._fd: int | None = None

    def __enter__(self) -> "_ConverterInstallLock":
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self._timeout
        if not _is_windows():
            import fcntl

            self._fd = os.open(str(self._lock_path), os.O_RDWR | os.O_CREAT, 0o600)
            while True:
                try:
                    fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return self
                except OSError:
                    if time.monotonic() >= deadline:
                        os.close(self._fd)
                        self._fd = None
                        raise TimeoutError(
                            f"Timed out after {self._timeout:.0f}s waiting for the .{self._fmt} converter install lock"
                        ) from None
                    time.sleep(_INSTALL_LOCK_POLL_SEC)
        # Windows: exclusive-create poll loop.
        while True:
            try:
                self._fd = os.open(str(self._lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
                return self
            except FileExistsError:
                # Reclaim a stale lock left by a crashed holder. Staleness
                # is judged against the absolute ``_INSTALL_LOCK_STALE_SEC``
                # threshold (NOT this waiter's ``timeout``) so a short-timeout
                # caller can never steal a lock that another process is
                # legitimately holding mid-download.
                try:
                    age = time.time() - self._lock_path.stat().st_mtime
                    if age > _INSTALL_LOCK_STALE_SEC:
                        logger.warning(
                            "Reclaiming stale .%s converter install lock (age %.0fs)",
                            self._fmt,
                            age,
                        )
                        self._lock_path.unlink(missing_ok=True)
                        continue
                except OSError:
                    pass
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"Timed out after {self._timeout:.0f}s waiting for the .{self._fmt} converter install lock"
                    ) from None
                time.sleep(_INSTALL_LOCK_POLL_SEC)

    def __exit__(self, *_exc: object) -> None:
        if self._fd is None:
            return
        try:
            if not _is_windows():
                import fcntl

                fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            try:
                os.close(self._fd)
            finally:
                self._fd = None
                # POSIX flock auto-releases on close; the lockfile itself
                # is harmless to leave behind. On Windows we MUST remove it
                # so the next acquirer can exclusive-create again.
                if _is_windows():
                    try:
                        self._lock_path.unlink(missing_ok=True)
                    except OSError:
                        pass


def ensure_converter(fmt: str) -> Path:
    """Resolve a CAD/BIM converter, downloading it automatically if missing.

    This is the single entry point the conversion path calls before
    invoking a converter binary. Behaviour:

    1. If the converter for ``fmt`` is already present (``find_converter``
       resolves it), return its path immediately - no network IO.
    2. On Windows, acquire a per-format install lock, re-check (so two
       concurrent uploads do not both download), and otherwise delegate to
       the hardened downloader that mirrors the upstream repo directory
       into ``~/.openestimator/converters/{fmt}_windows/``. The downloader
       verifies the extracted ``*Exporter.exe`` is a valid PE and rolls
       back a partial download on failure. The freshly installed path is
       then re-resolved through ``find_converter`` and returned.
    3. On non-Windows platforms the bundled binaries do not run, so this
       raises :class:`ConverterUnavailableError` with the platform-correct
       install instructions instead of crashing.

    Args:
        fmt: Lowercase format key without dot - one of ``rvt`` / ``ifc`` /
            ``dwg``. Aliases (``rfa`` → ``rvt``, ``dxf`` → ``dwg``)
            are normalised by the caller; this function expects a key that
            exists in :data:`CONVERTERS`.

    Returns:
        Absolute path to a present, runnable converter executable.

    Raises:
        ConverterUnavailableError: The converter is missing and could not
            be provisioned (unsupported platform, unknown format, or the
            download failed). The message is user-actionable.
    """
    fmt = fmt.lower().lstrip(".")
    # Normalise format aliases to the converter that actually handles them:
    # the RVT converter reads .rfa families, the DWG converter .dxf. This mirrors
    # the converter metadata in ``takeoff.router._CONVERTER_META`` (where
    # ``rvt`` advertises ``[".rvt", ".rfa"]`` and ``dwg`` advertises
    # ``[".dwg", ".dxf"]``) so an upload of either alias provisions and uses
    # the correct binary.
    fmt = _CONVERTER_FORMAT_ALIASES.get(fmt, fmt)
    if fmt not in CONVERTERS:
        raise ConverterUnavailableError(
            f"No DDC converter is defined for .{fmt} files. Supported formats: {', '.join(sorted(CONVERTERS))}."
        )

    # Fast path - already installed.
    existing = find_converter(fmt)
    if existing is not None:
        return existing

    # The 2026.10 converters are published for Windows 10/11 x64 only; Linux
    # and macOS builds are announced upstream but do not exist yet.
    if sys.platform != SUPPORTED_PLATFORM:
        raise ConverterUnavailableError(
            f"The .{fmt.upper()} converter is published for Windows 10/11 x64 only; "
            f"Linux and macOS builds are not available yet. Run OpenConstructionERP on "
            f"Windows to convert .{fmt} files, or convert the file to DXF (drawings) or "
            f"IFC (models) first - both are read without a converter binary where supported."
        )

    # Windows auto-downloads under a per-format lock so concurrent
    # uploads of the same format don't both fetch into the same directory. The
    # lock is cross-platform (Windows O_EXCL / POSIX flock).
    try:
        with _ConverterInstallLock(fmt):
            # Double-checked: another upload may have completed the install
            # while we waited for the lock.
            existing = find_converter(fmt)
            if existing is not None:
                logger.info("Converter for .%s became available while waiting for the install lock", fmt)
                return existing

            logger.info("Converter for .%s not found - downloading automatically", fmt)
            # Lazy import: the downloader lives in the takeoff router, which
            # pulls in FastAPI. Importing it at module load would create a
            # circular import (the router imports THIS module) and bloat the
            # import-time cost of cad_import. Importing it here, only on the
            # cold-download path, is cheap and cycle-free.
            try:
                from app.modules.takeoff.router import (
                    _download_converter_files_windows as _download_converter,
                )
            except Exception as exc:  # noqa: BLE001 - import failure must be actionable
                raise ConverterUnavailableError(f"Could not load the converter installer for .{fmt}: {exc}") from exc

            try:
                exe_path = _download_converter(fmt)
            except Exception as exc:  # noqa: BLE001 - surface a clean message
                raise ConverterUnavailableError(
                    f"Automatic download of the .{fmt.upper()} converter failed: {exc}"
                ) from exc

            logger.info("Converter for .%s downloaded to %s", fmt, exe_path)

            # The downloader returns the exe directly, but re-resolve through
            # find_converter so callers always get a path that passes the
            # canonical resolution + size gate (and so the in-process caches
            # see the same path). Fall back to the downloader's path if the
            # re-probe somehow misses it.
            resolved = find_converter(fmt)
            if resolved is not None:
                return resolved
            if exe_path.exists():
                return exe_path
            raise ConverterUnavailableError(
                f"The .{fmt.upper()} converter was downloaded but could not be located afterwards at {exe_path}."
            )
    except ConverterUnavailableError:
        raise
    except TimeoutError as exc:
        raise ConverterUnavailableError(
            f"Timed out waiting to install the .{fmt.upper()} converter: {exc}. "
            f"Another conversion may be downloading it - retry shortly."
        ) from exc


async def ensure_converter_async(fmt: str) -> Path:
    """Async wrapper around :func:`ensure_converter`.

    The download is blocking (network + disk IO across many files), so it
    is offloaded to a worker thread to keep the event loop responsive.
    Use this from ``async def`` endpoint handlers and ``async`` conversion
    coroutines; use the sync :func:`ensure_converter` from threads.
    """
    return await asyncio.to_thread(ensure_converter, fmt)


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
        - ``"ok"`` - binary loads and exits cleanly.
        - ``"failed"`` - binary doesn't load (DLL missing, etc).
        - ``"unknown"`` - smoke test couldn't run (timeout, OS error
          unrelated to the binary itself).
    ``message``:
        Human-readable explanation. Empty string on the happy path.
    ``suggested_actions``:
        Stable string ids the frontend uses to render specific buttons
        / instructions (Reinstall / Open install dir / Run as admin /
        Install VCRedist / etc).
    ``checked_at``:
        Unix timestamp of the check - used by the cache layer.
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
#
# Anything not listed here falls through to the healthy branch, so a code
# missing from this set is not a worse message - it is the banner reporting
# a converter as working while Windows refuses to start it. That is exactly
# what happened with 0xC000007B, which a user hit on the DGN converter while
# the status card showed no problem at all.
#
# The four codes are one family: the image is unusable before its first
# instruction runs. 0xC000007B is the odd one out in cause - it is a bitness
# mismatch, not an absent file - so it carries its own wording below.
_WINDOWS_STATUS_DLL_NOT_FOUND = 0xC0000135
_WINDOWS_STATUS_DLL_INIT_FAILED = 0xC0000142
_WINDOWS_STATUS_INVALID_IMAGE_FORMAT = 0xC000007B
_WINDOWS_STATUS_ENTRYPOINT_NOT_FOUND = 0xC0000139


def _both_signs(code: int) -> tuple[int, int]:
    """Return an NTSTATUS as the unsigned and signed ints subprocess may report."""
    return code, code - 0x1_0000_0000


_WINDOWS_DLL_LOAD_FAILURES: frozenset[int] = frozenset(
    code
    for status in (
        _WINDOWS_STATUS_DLL_NOT_FOUND,
        _WINDOWS_STATUS_DLL_INIT_FAILED,
        _WINDOWS_STATUS_INVALID_IMAGE_FORMAT,
        _WINDOWS_STATUS_ENTRYPOINT_NOT_FOUND,
    )
    for code in _both_signs(status)
)


@contextlib.contextmanager
def _windows_loader_errors_stay_quiet() -> Iterator[None]:
    """Stop Windows putting its own modal dialog in front of the application.

    When the loader cannot start an image it shows a "Bad Image" message box
    and blocks until somebody clicks OK. The box belongs to the operating
    system, so the application never learns it exists: our own health message
    is written to a card the user cannot see behind it, and the reporter of
    this defect saw a system dialog naming a DLL rather than anything we wrote.

    A child process inherits the error mode of its parent, and
    SEM_FAILCRITICALERRORS is documented as the setting a service should hold,
    so setting it here is what makes the failure come back as an exit code we
    can explain. The previous mode is restored, because the flag is
    process-wide and this module does not own the process.

    No-op off Windows, where a loader failure already arrives as an exit code
    and a line on stderr.
    """
    if not sys.platform.startswith("win"):
        yield
        return
    import ctypes

    sem_failcriticalerrors = 0x0001
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    previous = kernel32.SetErrorMode(sem_failcriticalerrors)
    try:
        # SetErrorMode replaces rather than merges, so put back whatever the
        # host process had once we are done.
        kernel32.SetErrorMode(previous | sem_failcriticalerrors)
        yield
    finally:
        kernel32.SetErrorMode(previous)


def smoke_test_converter(extension: str, force: bool = False) -> ConverterHealth:
    """Quick health check: spawn the converter binary and verify it loads.

    Runs the converter with ``--help`` and waits up to ``20`` seconds for an
    exit. The purpose is NOT to detect feature bugs - only to verify that the OS
    can launch the binary without a missing-DLL / wrong-arch / perms
    error. A binary that loads and then exits with an error code
    is fine for our purposes.

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

    # A folder with the exe but not the libraries we ship beside it is a
    # partial install, and it reads as a healthy one from every check we
    # had: the file is there and it is bigger than 1 KB. Say so before
    # spawning anything, because whether the binary starts from such a
    # folder depends on what else is installed on the machine, and a
    # converter that starts by borrowing another program's libraries is
    # not an install we can support either way.
    absent = missing_companion_files(exe_path)
    if absent:
        result = {
            "status": "failed",
            "message": (
                f"{exe_path.parent} holds {exe_path.name} but not {', '.join(absent)}, "
                f"so that folder has only part of a converter in it. Windows will look "
                f"for those libraries everywhere else on the machine and may start the "
                f"converter against an unrelated copy. Press Uninstall and then Install "
                f"so the folder is rebuilt from empty."
            ),
            "suggested_actions": ["reinstall_converter", "manual_install_from_github"],
            "checked_at": now,
        }
        _HEALTH_CACHE[extension] = result
        return result

    try:
        import subprocess

        # ``input=`` already implies ``stdin=PIPE`` - passing both raises
        # ``ValueError: stdin and input arguments may not both be used``,
        # which used to crash the per-upload pre-flight check on every
        # native CAD format and leave the model stuck at
        # ``ddc_smoke_failed`` even when the binary was correctly
        # installed.  Drop the explicit ``stdin=PIPE``.
        from app.core.converter_source import command_prefix

        with _windows_loader_errors_stay_quiet():
            proc = subprocess.run(
                [*command_prefix(extension, exe_path), "--help"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                cwd=str(exe_path.parent),
                env=_converter_subprocess_env(exe_path),
                timeout=20,
            )
        rc = proc.returncode

        if rc in _WINDOWS_DLL_LOAD_FAILURES:
            unsigned = rc & 0xFFFFFFFF
            if unsigned == _WINDOWS_STATUS_INVALID_IMAGE_FORMAT:
                # The loader found the image and refused it. This branch used
                # to assert that every library was present and one of them was
                # built for the other word size, and told the user to download
                # the converter again. Both halves were wrong. Every file we
                # publish for every converter is 64-bit, and has been in every
                # version we have released, so the word-size claim describes
                # nothing we ship; and downloading again cannot remove a file
                # that should not be in the folder. What clears the folder is
                # Uninstall, or deleting it.
                diagnosis = (
                    f"Windows found {exe_path.name} and then refused to start it "
                    f"(error 0x{unsigned:08x}). Every file we publish for this converter is 64-bit, "
                    f"in every version we have released, so a folder that fails this way is either "
                    f"missing something we ship or holding something we do not. Press Uninstall and "
                    f"then Install so the folder is rebuilt from empty, or delete {exe_path.parent} "
                    f"yourself and install again. If it comes back, send us the converter path shown "
                    f"here and a listing of that folder with file sizes."
                )
            else:
                diagnosis = (
                    f"{exe_path.name} exists on disk but cannot load - a required runtime DLL is "
                    f"missing or the wrong version (Windows error 0x{unsigned:08x}). Install the "
                    f"Microsoft Visual C++ Redistributable (x64), then press Uninstall and Install "
                    f"so {exe_path.parent} is rebuilt from empty."
                )
            result = {
                "status": "failed",
                "message": diagnosis,
                "suggested_actions": [
                    "reinstall_converter",
                    "install_vc_redist",
                    "manual_install_from_github",
                ],
                "checked_at": now,
            }
        else:
            # Any other exit code (including non-zero from the missing input): the binary did load, so the install
            # is healthy from our perspective.
            result = {
                "status": "ok",
                "message": "",
                "suggested_actions": [],
                "checked_at": now,
            }
    except subprocess.TimeoutExpired:
        # Binary is alive but waiting for stdin / showing a window. That
        # means the loader succeeded - treat as healthy.
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
                f"On Windows this is usually 'Mark of the Web' - right-click "
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
    except Exception as exc:  # noqa: BLE001 - health check must never raise
        logger.warning("Smoke test for .%s converter errored: %s", extension, exc)
        result = {
            "status": "unknown",
            "message": (f"Health check could not complete: {exc.__class__.__name__}: {exc}"),
            "suggested_actions": [],
            "checked_at": now,
        }

    _HEALTH_CACHE[extension] = result
    return result


# ── Version detection - RVT file + installed converter ────────────────────
#
# Why this exists: the smoke test verifies the binary LOADS, not that it can
# parse the user's file. A user can have a perfectly installed converter that
# is simply OLDER than the RVT version that saved their .rvt file - and the
# DDC converter then silently writes an empty Excel. Detecting both versions
# upfront lets us surface the actual reason ("Your RVT is from Revit 2025
# but the installed converter only supports up to 2023") instead of the
# generic "Converter Required" message.


def read_rvt_revit_version(path: Path, *, max_scan_bytes: int = 262144) -> dict[str, str | None]:
    """Extract RVT version metadata from a .rvt file header.

    RVT files are OLE Compound Documents. The ``BasicFileInfo`` stream
    near the start contains UTF-16-LE text like ``Format: 2024`` and
    ``Revit Build: 24.0.11.21``. We don't parse the full OLE structure
    (would add a dependency) - we just scan the first 256 KB for the
    well-known marker strings, which are reliably present in the leading
    sectors for files saved by RVT 2018+.

    Returns a dict with optional ``format``, ``build``, ``app_name``
    fields. All values are strings or ``None`` if the marker wasn't found.
    Never raises - IO errors return all-None.
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

    # Decode the scanned region as UTF-16-LE (RVT's chosen encoding for
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
    """Detect the installed DDC converter's package version.

    Reads the stamp the installer writes beside an installed package, falling
    back to the version declared for the package when the folder carries no
    stamp (a bundled or hand-unpacked copy).

    Returns a dict ``{"version": str | None, "source": str | None,
    "binary_path": str | None}``. Never raises.
    """
    result: dict[str, str | None] = {"version": None, "source": None, "binary_path": None}
    exe = find_converter(extension)
    if exe is None:
        return result
    result["binary_path"] = str(exe)
    pkg = PACKAGES.get(extension)
    root = _install_root_of(exe)
    if root is not None:
        from app.core.converter_package import read_stamp

        stamp = read_stamp(root)
        if stamp and stamp.get("version"):
            result["version"] = str(stamp["version"])
            result["source"] = f"release:{stamp.get('tag') or 'unknown'}"
            return result
    if pkg is not None:
        result["version"] = pkg.version
        result["source"] = "package"
    return result


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


async def convert_cad_to_excel(
    input_path: Path,
    output_dir: Path,
    extension: str,
) -> Path | None:
    """Run a DDC converter to transform a CAD file into a one-row-per-element Excel file.

    The converter runs as a subprocess with a 10-minute timeout. What it writes
    depends on the format (see :mod:`app.modules.boq.ddc_runner`): IFC and RVT
    output is flattened into an ``Elements`` workbook; a DWG is read through the
    DXF its converter writes, like an uploaded DXF.

    Args:
        input_path: Path to the uploaded CAD file.
        output_dir: Directory where the Excel output should be written.
        extension: Lowercase file extension without dot.

    Returns:
        Path to the generated Excel file, or ``None`` on failure.
    """
    # Formats the platform reads in-process never touch a converter binary.
    #
    # Decided on the file's OWN suffix rather than on ``extension``, because
    # callers pre-resolve the alias: ``takeoff.router`` passes
    # ``_CONVERTER_FORMAT_ALIASES.get(ext, ext)``, so a .dxf upload arrives
    # here labelled "dwg" and a check on the label would never fire. The file
    # on disk is the thing being read, so the file decides.
    from app.modules.boq.dxf_native import convert_dxf_to_excel, is_natively_readable

    if is_natively_readable(input_path.suffix):
        return await asyncio.to_thread(convert_dxf_to_excel, input_path, output_dir)

    # Resolve the converter, auto-downloading it on first use if missing.
    # ``ensure_converter`` is idempotent and concurrency-safe; on an
    # unsupported platform (or a failed download) it raises
    # ``ConverterUnavailableError``, which we translate to the historical
    # ``None`` return so the caller's existing "conversion failed" path is
    # preserved.
    try:
        converter = await ensure_converter_async(extension)
    except ConverterUnavailableError as exc:
        logger.error("No converter available for .%s: %s", extension, exc)
        return None

    import subprocess

    from app.modules.boq.ddc_runner import run_converter, tool_label, write_flat_workbook

    fmt = _CONVERTER_FORMAT_ALIASES.get(extension, extension)
    logger.info("Converting %s using %s", input_path.name, tool_label(fmt))

    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        run = await asyncio.to_thread(run_converter, fmt, converter, input_path, output_dir, timeout=600)
    except subprocess.TimeoutExpired:
        logger.error("Converter timed out after 600s for %s", input_path.name)
        return None
    except Exception:
        logger.exception("Converter error for %s", input_path.name)
        return None

    if not run.ok:
        logger.error(
            "Converter failed (exit %d, status %s) for %s: %s",
            run.returncode,
            run.status,
            input_path.name,
            (run.stderr or run.stdout)[:500],
        )
        return None

    try:
        if fmt == "dwg":
            # The converter's own workbook is a decoder log (one row per stored
            # record: block definitions, table entries, every attribute column).
            # Its DXF is read like an uploaded DXF instead: modelspace entities,
            # layer as category, lengths and areas in metres.
            dxf = run.outputs.get("dxf")
            if dxf is not None and dxf.is_file():
                table = await asyncio.to_thread(convert_dxf_to_excel, dxf, output_dir)
                if table is not None:
                    return table
                logger.warning("Could not read the DXF the DWG converter wrote for %s", input_path.name)
            return run.outputs["xlsx"]
        return await asyncio.to_thread(write_flat_workbook, run, output_dir / (input_path.stem + ".xlsx"))
    except Exception:
        logger.exception("Could not read the converter output for %s", input_path.name)
        return None


def _cad_excel_header_keys(header_row: tuple | list) -> tuple[list[str], dict[str, str]]:
    """Normalise a DDC Excel header row into row keys plus their display labels.

    Keys are lowercased with the DDC type suffix (``" : String"``) removed:
    element properties, rules and lookups all key on that form. The label map
    sends each key back to the header as the converter wrote it
    (``"phase created" -> "Phase Created"``). When two headers collapse onto
    one key the first header's text wins.
    """
    raw_headers = [str(h or "").strip() for h in header_row]
    display = [h.split(" : ")[0].strip() if " : " in h else h for h in raw_headers]
    keys = [h.lower() for h in display]
    labels: dict[str, str] = {}
    for key, text in zip(keys, display, strict=True):
        if key and key not in labels:
            labels[key] = text
    return keys, labels


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
    headers, _labels = _cad_excel_header_keys(rows[0])

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


def read_cad_excel_labels(excel_path: Path) -> dict[str, str]:
    """Return ``{row key: original header text}`` for a DDC Excel export.

    Reads only the header row. Best-effort: an unreadable file gives ``{}``,
    and the property panel then shows each column by its key.
    """
    try:
        import openpyxl

        wb = openpyxl.load_workbook(excel_path, read_only=True, data_only=True)
        try:
            ws = wb.active
            if ws is None:
                return {}
            header = next(ws.iter_rows(max_row=1, values_only=True), None)
            if not header:
                return {}
            return _cad_excel_header_keys(header)[1]
        finally:
            wb.close()
    except Exception:  # noqa: BLE001 - labels are cosmetic, never block an import
        logger.debug("read_cad_excel_labels: could not read headers of %s", excel_path, exc_info=True)
        return {}


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


# BUG-D-TKC-004b / D-TKC-NEW-05 - canonical quantity synonym map.
#
# DDC / RVT / IFC exporters emit the same physical quantity under a
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
# stripped - that would mis-merge unrelated columns like ``team``.

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

    Resolves the many DDC / RVT / IFC spellings of the same physical
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

    # Cap length before the super-linear cleanup regexes below; a real quantity
    # column name is short, so this never truncates legitimate input.
    s = str(name)[:256].strip().lower()
    s = s.replace("²", "2").replace("³", "3")
    # Drop a trailing unit qualifier in brackets/parens: "volume (m3)",
    # "area [m2]", "weight {kg}".
    s = re.sub(r"[\s,]*[([{].*?[)\]}]\s*$", "", s)
    # IFC ``Qto_<set>.<Quantity>`` dotted form - keep only the final
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

    # Final canonical synonym mapping (exact token match only - we never
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
        # BUG-D-TKC-017 - each row from ``parse_cad_excel`` is ONE physical
        # element.  The optional ``count`` column is a per-element multiplier
        # (e.g. an array/group of 4 identical fixtures on one row).  A
        # missing column, an empty cell, or an explicit ``0`` must still
        # contribute the single physical instance the row represents - the
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
    # BUG-D-TKC-024 - displayed rows MUST reconcile.  Previously the item
    # rows were rounded for display while the category and grand totals
    # were summed from the UNROUNDED running sums, so e.g. 250 rebar rows
    # each displaying 0.000 sat under a non-zero category total - an
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


#: Lowercase column names that hold identifiers, never quantities.
_ID_COLUMNS = frozenset({"id", "element id", "elementid", "guid", "globalid", "uniqueid", "handle", "ordinal"})


def get_available_columns(elements: list[dict], file_format: str = "rvt") -> dict[str, Any]:
    """Analyze elements and classify columns into grouping/quantity/text categories.

    Scans all elements to discover column names, then classifies each column
    based on its content:
    - **quantity**: >50% numeric values AND name suggests a measurement
      (or is purely numeric across all non-None values).
    - **grouping**: string columns with <500 unique values - suitable for
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

        # Identifiers are numbers, not quantities; reals in Revit internal units
        # (feet and derived) would be summed as metres.
        not_a_quantity = col_lower in _ID_COLUMNS or "[internal units]" in col_lower

        # Classify
        if not not_a_quantity and numeric_ratio > 0.5 and (name_is_quantity or numeric_ratio == 1.0):
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

    # "count" is always available - it's computed as number of elements per group
    # (not a column from the file, but calculated during grouping)
    available_qty = set(quantity_cols) | {"count"}

    if file_format in ("rvt", "rfa"):
        presets = {
            "standard": {
                "label": "Standard BIM QTO",
                "description": "Category + Type Name - standard BIM breakdown",
                "group_by": [c for c in ["category", "type name"] if c in grouping_cols],
                "sum_columns": [c for c in ["volume", "area", "count"] if c in available_qty],
            },
            "detailed": {
                "label": "Detailed (with Level)",
                "description": "Category + Type Name + Level - per-floor breakdown",
                "group_by": [c for c in ["category", "type name", "level"] if c in grouping_cols],
                "sum_columns": [c for c in ["volume", "area", "length", "count"] if c in available_qty],
            },
            "by_family": {
                "label": "By Family",
                "description": "Family + Type - for procurement and ordering",
                "group_by": [c for c in ["family", "type name"] if c in grouping_cols],
                "sum_columns": [c for c in ["count", "volume", "area"] if c in available_qty],
            },
            "summary": {
                "label": "Quick Summary",
                "description": "Category only - high-level overview",
                "group_by": [c for c in ["category"] if c in grouping_cols],
                "sum_columns": [c for c in ["count", "volume", "area"] if c in available_qty],
            },
        }
    elif file_format == "ifc":
        presets = {
            "standard": {
                "label": "Standard IFC QTO",
                "description": "Group by Category + Type - standard IFC entity breakdown",
                "group_by": [c for c in ["category", "type name", "type"] if c in grouping_cols][:2],
                "sum_columns": [c for c in ["volume", "area", "count"] if c in available_qty],
            },
            "detailed": {
                "label": "Detailed (with Level)",
                "description": "Category + Type + Level - per-floor breakdown",
                "group_by": [c for c in ["category", "type name", "type", "level"] if c in grouping_cols][:3],
                "sum_columns": [c for c in ["volume", "area", "length", "count"] if c in available_qty],
            },
            "by_storey": {
                "label": "By Building Storey",
                "description": "Building Storey + Category + Type - storey-first breakdown",
                "group_by": [c for c in ["level", "category", "type name", "type"] if c in grouping_cols][:3],
                "sum_columns": [c for c in ["volume", "area", "length", "count"] if c in available_qty],
            },
            "by_material": {
                "label": "By Material",
                "description": "Material + Category - material-first grouping for procurement",
                "group_by": [c for c in ["material", "category"] if c in grouping_cols][:2],
                "sum_columns": [c for c in ["volume", "area", "count"] if c in available_qty],
            },
            "summary": {
                "label": "Quick Summary",
                "description": "Category only - high-level element count",
                "group_by": [c for c in ["category"] if c in grouping_cols],
                "sum_columns": [c for c in ["count", "volume", "area"] if c in available_qty],
            },
        }
    elif file_format == "dwg":
        presets = {
            "standard": {
                "label": "Standard DWG QTO",
                "description": "Group by Layer - standard CAD organization",
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

    This is the interactive counterpart to ``group_cad_elements`` - instead
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

        # BUG-D-TKC-004: tolerant column lookup - a DDC export that wrote
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
