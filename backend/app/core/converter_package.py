# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Verify and unpack a DDC converter package (a portable ``.zip`` of a release).

Standard library only. The two steps the installer must not get wrong live
here so they can be tested without a network: the digest check, and the
extraction, which refuses entries that would land outside the install folder
and caps the unpacked size.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath

from app.core.converter_source import INSTALL_STAMP_NAME, ConverterPackage

#: Cap on the unpacked size of one package. The largest published package
#: unpacks to a few hundred MB; this leaves headroom and stops a bomb.
MAX_UNPACKED_BYTES = 1536 * 1024 * 1024


class PackageError(RuntimeError):
    """The archive is corrupt, hostile or not the package we asked for."""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_sha256(path: Path, expected: str) -> None:
    """Raise :class:`PackageError` unless ``path`` hashes to ``expected``."""
    actual = sha256_file(path)
    if actual != expected.lower():
        raise PackageError(f"SHA-256 mismatch for {path.name}: expected {expected.lower()}, got {actual}")


def _common_root(names: list[str], include: tuple[str, ...] | None = None) -> str:
    """Single top-level folder shared by every entry, or ``""``.

    A top-level folder that is itself one of the wanted ``include`` prefixes
    (an archive holding only ``cli/...``) is content, not a wrapper.
    """
    tops = {PurePosixPath(n).parts[0] for n in names if PurePosixPath(n).parts}
    if len(tops) != 1:
        return ""
    top = next(iter(tops))
    if include and any(inc == f"{top}/" or inc.startswith(f"{top}/") for inc in include):
        return ""
    # A lone top-level *file* is not a wrapper folder.
    return top if all(len(PurePosixPath(n).parts) > 1 for n in names) else ""


def _wanted(rel: str, include: tuple[str, ...] | None) -> bool:
    if include is None:
        return True
    return any(rel == inc or (inc.endswith("/") and rel.startswith(inc)) for inc in include)


def extract_package(archive: Path, dest: Path, pkg: ConverterPackage) -> int:
    """Unpack ``archive`` into the empty folder ``dest``; returns files written.

    A single wrapper folder at the top of the archive (the DWG and RVT zips have
    one, the IFC zip has none) is stripped. Entries that are absolute, climb with
    ``..``, carry a drive, or are symlinks are refused before anything is written.
    """
    dest = dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    try:
        zf = zipfile.ZipFile(archive)
    except zipfile.BadZipFile as exc:
        raise PackageError(f"{archive.name} is not a valid zip archive: {exc}") from exc
    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        root = _common_root([i.filename.replace("\\", "/") for i in infos], pkg.include)
        total = sum(i.file_size for i in infos)
        if total > MAX_UNPACKED_BYTES:
            raise PackageError(f"{archive.name} unpacks to {total} bytes, over the {MAX_UNPACKED_BYTES} byte cap")
        plan: list[tuple[zipfile.ZipInfo, Path]] = []
        for info in infos:
            name = info.filename.replace("\\", "/")
            pure = PurePosixPath(name)
            if pure.is_absolute() or ".." in pure.parts or (pure.parts and ":" in pure.parts[0]):
                raise PackageError(f"Refused archive entry {info.filename!r} (path traversal)")
            mode = info.external_attr >> 16
            if mode and stat.S_ISLNK(mode):
                raise PackageError(f"Refused archive entry {info.filename!r} (symbolic link)")
            rel = "/".join(pure.parts[1:]) if root else str(pure)
            if not rel or not _wanted(rel, pkg.include):
                continue
            target = (dest / rel).resolve()
            try:
                target.relative_to(dest)
            except ValueError as exc:
                raise PackageError(f"Refused archive entry {info.filename!r} (escapes install folder)") from exc
            plan.append((info, target))
        for info, target in plan:
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, target.open("wb") as out:
                shutil.copyfileobj(src, out, 1024 * 1024)
    return len(plan)


def write_stamp(dest: Path, pkg: ConverterPackage, *, tag: str, repo: str) -> None:
    (dest / INSTALL_STAMP_NAME).write_text(
        json.dumps(
            {
                "fmt": pkg.fmt,
                "asset": pkg.asset,
                "version": pkg.version,
                "sha256": pkg.sha256,
                "tag": tag,
                "repo": repo,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def read_stamp(install_dir: Path) -> dict[str, str] | None:
    """The stamp of an installed package, or ``None`` (absent or unreadable)."""
    try:
        data = json.loads((install_dir / INSTALL_STAMP_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None
