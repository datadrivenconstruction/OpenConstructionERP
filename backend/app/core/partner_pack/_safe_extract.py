# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Shared, battle-tested safe zip extraction.

This is the single implementation of zip-member safety used by:
  * ``app.cli.cmd_module_install`` (installing a business module .zip)
  * ``app.core.partner_pack.discovery`` (auto-extracting a dropped pack .zip)
  * ``app.core.partner_pack.router`` (the ``POST /install`` upload endpoint)

It guards against the classic untrusted-archive attacks (Zip Slip and
friends): absolute paths, ``..`` traversal, Windows drive letters, backslash
separators and symlink members. Every member is validated **twice** - once up
front before any filesystem write, and again at write time against the resolved
staging root (defence in depth against a crafted ``ZipInfo`` whose name passes
the string checks but resolves outside the target).

Extraction is staged: files are written into a temporary directory and only the
finished package directory is atomically moved into place, so a mid-extract
failure never leaves a half-written tree in a scanned location.
"""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path

# Local-file-header magic for a regular zip, plus the empty-archive and
# spanned-archive end-of-central-directory signatures. ``zipfile.is_zipfile``
# is the authoritative structural check; these constants let callers reject a
# non-zip upload cheaply (and before buffering the whole body) by sniffing the
# leading bytes.
ZIP_MAGIC_PREFIXES: tuple[bytes, ...] = (
    b"PK\x03\x04",  # standard local file header
    b"PK\x05\x06",  # empty archive (end of central directory)
    b"PK\x07\x08",  # spanned archive
)


class UnsafeArchiveError(Exception):
    """Raised when a zip archive contains an unsafe member or invalid layout."""


def has_zip_magic(head: bytes) -> bool:
    """Return ``True`` if ``head`` begins with a known zip signature.

    Args:
        head: The first few bytes of a candidate archive (>= 4 bytes).

    Returns:
        Whether the bytes start with a recognised zip magic prefix. This is a
        cheap pre-filter only; callers must still validate the full structure
        with :func:`zipfile.is_zipfile` before trusting the archive.
    """
    return any(head.startswith(prefix) for prefix in ZIP_MAGIC_PREFIXES)


def is_unsafe_zip_member(info: zipfile.ZipInfo) -> str | None:
    """Return a human-readable reason if a zip member is unsafe, else ``None``.

    Rejects:
      * absolute POSIX paths (``/etc/passwd``)
      * parent-directory traversal (any ``..`` path segment)
      * Windows drive letters / backslash separators (``C:\\evil``, ``a\\b``)
      * symlinks (encoded in the Unix mode bits of ``external_attr``)

    Args:
        info: A single archive member's :class:`zipfile.ZipInfo`.

    Returns:
        A reason string when the member is unsafe, otherwise ``None``.
    """
    name = getattr(info, "filename", "")

    # Windows drive letter, e.g. "C:..." - also catches "C:\\..." once \\ -> /.
    if len(name) >= 2 and name[1] == ":":
        return f"drive-letter path: {name!r}"

    # Normalise backslashes so a Windows-authored archive can't smuggle
    # traversal past the POSIX checks below.
    if "\\" in name:
        return f"backslash separator in path: {name!r}"

    if name.startswith("/"):
        return f"absolute path: {name!r}"

    parts = name.split("/")
    if ".." in parts:
        return f"parent-directory traversal: {name!r}"

    # Symlink detection: the high 16 bits of external_attr hold the Unix mode.
    external_attr = getattr(info, "external_attr", 0)
    mode = external_attr >> 16
    if mode and stat.S_ISLNK(mode):
        return f"symlink member: {name!r}"

    return None


def assert_safe_archive(infos: list[zipfile.ZipInfo]) -> None:
    """Validate every member of an archive, raising on the first unsafe one.

    Args:
        infos: The archive's member list (``ZipFile.infolist()``).

    Raises:
        UnsafeArchiveError: If the archive is empty or any member is unsafe.
    """
    if not infos:
        raise UnsafeArchiveError("archive is empty")
    for info in infos:
        reason = is_unsafe_zip_member(info)
        if reason is not None:
            raise UnsafeArchiveError(f"unsafe archive member ({reason})")


def safe_extract_all(zf: zipfile.ZipFile, dest_dir: Path) -> None:
    """Extract every file member of ``zf`` into ``dest_dir``, sandboxed.

    Each member is re-validated against the *resolved* destination root at write
    time (not just by name), so a member that slips past the up-front name check
    can never escape ``dest_dir``. Directory entries are skipped - they are
    created implicitly by file writes. The caller is responsible for having
    already run :func:`assert_safe_archive` (this re-checks as defence in depth).

    Args:
        zf: An open :class:`zipfile.ZipFile`.
        dest_dir: The directory to extract into (created if missing).

    Raises:
        UnsafeArchiveError: If a member resolves outside ``dest_dir``.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    root = dest_dir.resolve()
    for info in zf.infolist():
        # Skip directory entries - created implicitly by file writes below.
        if info.filename.endswith("/"):
            continue
        reason = is_unsafe_zip_member(info)
        if reason is not None:
            raise UnsafeArchiveError(f"unsafe archive member ({reason})")
        target = (root / info.filename).resolve()
        # Belt-and-braces: the resolved path must stay under the root.
        if target != root and not str(target).startswith(str(root) + os.sep):
            raise UnsafeArchiveError(f"member escapes destination dir: {info.filename!r}")
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(target, "wb") as out:
            shutil.copyfileobj(src, out)


def stage_and_extract(zf: zipfile.ZipFile, prefix: str = "oe_safe_extract_") -> Path:
    """Safely extract ``zf`` into a fresh temp staging directory.

    The caller owns the returned directory and MUST clean it up (or move its
    contents elsewhere and then remove it). Staging keeps a mid-extract failure
    out of any production scan path.

    Args:
        zf: An open :class:`zipfile.ZipFile`.
        prefix: Temp-directory name prefix, for easier debugging.

    Returns:
        The path to the populated staging directory.

    Raises:
        UnsafeArchiveError: If the archive is empty or any member is unsafe.
    """
    assert_safe_archive(zf.infolist())
    staging = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        safe_extract_all(zf, staging)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return staging


def resolve_single_top_level(staging: Path) -> Path:
    """Return the pack root inside ``staging``: itself or its lone subdirectory.

    A dropped pack archive may be laid out either as ``manifest.json`` (and
    assets) at the archive root, or wrapped in a single top-level directory
    (e.g. ``my-pack/manifest.json``). This collapses the wrapped case so the
    caller always gets the directory that *contains* ``manifest.json``.

    Args:
        staging: A populated extraction directory.

    Returns:
        ``staging`` itself when files sit at its root, or the single
        subdirectory when the archive wrapped everything in one folder.
    """
    entries = [p for p in staging.iterdir() if not p.name.startswith("__MACOSX")]
    visible_dirs = [p for p in entries if p.is_dir()]
    visible_files = [p for p in entries if p.is_file()]
    # Exactly one subdir and no loose files at the root -> the wrapper case.
    if len(visible_dirs) == 1 and not visible_files:
        return visible_dirs[0]
    return staging
