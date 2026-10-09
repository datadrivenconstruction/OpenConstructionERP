# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Open an uploaded price list, plain or zipped, without loading it into memory.

Regions publish their lists as a single XML or spreadsheet, or as a ZIP of
several: Lombardia ships one XML of 125 MB and a second in an older layout,
Lazio nine CSV parts in two encodings, Umbria the same list as XLSX and JSON.
Each member is read through ``zipfile``'s streaming reader, so memory does not
grow with the archive, and the archive is checked before anything is inflated.

The ZIP guard reads the sizes the archive declares and refuses an archive that
would inflate past the budget, holds too many members, or packs one member
tighter than any real price list does. The real lists compress about 32 to 1
(Toscana and Lombardia XML); the ratio limit sits well above that so a real
file is never refused for compressing well, and far below what a zip bomb
needs. The declared size can lie, so every member is also read through a
counting stream that stops at the declared size plus a margin.
"""

from __future__ import annotations

import io
import os
import zipfile
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import IO, Final

# Budgets. The upload limit covers the bytes the user sends; the inflated
# budget covers what the parsers will read. Both are streamed, so they bound
# time and temporary disk, not memory.
MAX_UPLOAD_BYTES: Final[int] = 200 * 1024 * 1024
MAX_INFLATED_BYTES: Final[int] = 800 * 1024 * 1024
MAX_ZIP_MEMBERS: Final[int] = 200
MAX_MEMBER_RATIO: Final[int] = 200

# Extensions a member can be read as; anything else in an archive (a PDF of
# the decree, a DOCX of metadata) is listed as skipped.
READABLE_EXTENSIONS: Final[tuple[str, ...]] = (".xml", ".xpwe", ".pwe", ".csv", ".xlsx", ".json", ".txt")


class ContainerRefused(ValueError):
    """The upload is not opened. ``code`` is a stable reason the UI translates."""

    def __init__(self, code: str, **params: object) -> None:
        super().__init__(code)
        self.code = code
        self.params = params


@dataclass
class Member:
    """One readable file of an upload: the upload itself or a ZIP member."""

    name: str
    size: int
    opener: Callable[[], IO[bytes]]

    @property
    def extension(self) -> str:
        return os.path.splitext(self.name.lower())[1]

    def open(self) -> IO[bytes]:
        return self.opener()

    def head(self, size: int = 64 * 1024) -> bytes:
        with self.open() as stream:
            return stream.read(size)


class _CappedReader(io.RawIOBase):
    """A read-only stream that refuses to yield more than ``limit`` bytes."""

    def __init__(self, inner: IO[bytes], limit: int, name: str) -> None:
        self._inner = inner
        self._limit = limit
        self._read = 0
        self._name = name

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int:  # type: ignore[no-untyped-def,override]
        try:
            chunk = self._inner.read(len(buffer))
        except (zipfile.BadZipFile, zlib.error, EOFError) as exc:
            # The member's bytes do not match the checksum or the sizes it
            # declares: a damaged or doctored archive, refused by name.
            raise ContainerRefused("zip_member_corrupt", member=self._name) from exc
        self._read += len(chunk)
        if self._read > self._limit:
            raise ContainerRefused("zip_member_too_large", member=self._name)
        buffer[: len(chunk)] = chunk
        return len(chunk)

    def close(self) -> None:
        try:
            self._inner.close()
        finally:
            super().close()


def _is_zip(stream: IO[bytes]) -> bool:
    stream.seek(0)
    magic = stream.read(4)
    stream.seek(0)
    return magic == b"PK\x03\x04"


def _is_ooxml(zf: zipfile.ZipFile) -> bool:
    """Whether the archive is itself a workbook rather than a ZIP of lists."""
    return "[Content_Types].xml" in zf.namelist()


def guard_archive(zf: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    """Refuse an archive by what it declares, before anything is inflated.

    Applied to an uploaded ZIP, to an uploaded workbook, and to a workbook
    found inside a ZIP, which the outer check sees only as one well-behaved
    member.

    Returns:
        The archive's file entries (directories left out).

    Raises:
        ContainerRefused: Too many members, too much inflated in total, a
            member compressed beyond :data:`MAX_MEMBER_RATIO`, or encryption.
    """
    infos = [info for info in zf.infolist() if not info.is_dir()]
    if len(infos) > MAX_ZIP_MEMBERS:
        raise ContainerRefused("zip_too_many_members", limit=MAX_ZIP_MEMBERS)
    total = sum(info.file_size for info in infos)
    if total > MAX_INFLATED_BYTES:
        raise ContainerRefused("zip_too_large_inflated", limit_mb=MAX_INFLATED_BYTES // (1024 * 1024))
    for info in infos:
        if info.compress_size and info.file_size / info.compress_size > MAX_MEMBER_RATIO:
            raise ContainerRefused("zip_ratio_suspicious", member=info.filename)
        if info.flag_bits & 0x1:
            raise ContainerRefused("zip_encrypted", member=info.filename)
    return infos


def stream_size(stream: IO[bytes]) -> int:
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(0)
    return size


def open_members(stream: IO[bytes], filename: str) -> tuple[list[Member], list[dict[str, str]]]:
    """The readable files of an upload, and the members that were skipped.

    Args:
        stream: The upload, seekable (Starlette's spooled temporary file).
        filename: The name the user uploaded it under.

    Returns:
        ``(members, skipped)``. ``skipped`` lists archive members that are not
        price-list files, each with a reason code.

    Raises:
        ContainerRefused: For an empty or oversized upload, or an archive that
            fails the ZIP guard.
    """
    size = stream_size(stream)
    if size == 0:
        raise ContainerRefused("empty_file")
    if size > MAX_UPLOAD_BYTES:
        raise ContainerRefused("file_too_large", limit_mb=MAX_UPLOAD_BYTES // (1024 * 1024))

    if not _is_zip(stream):

        def _open_self() -> IO[bytes]:
            stream.seek(0)
            return _NonClosing(stream)

        return [Member(name=os.path.basename(filename), size=size, opener=_open_self)], []

    try:
        zf = zipfile.ZipFile(stream)
    except zipfile.BadZipFile as exc:
        raise ContainerRefused("zip_unreadable") from exc
    # Checked before the workbook case: an .xlsx is a ZIP too, and a sheet
    # that inflates a thousandfold is the same bomb under another extension.
    infos = guard_archive(zf)
    if _is_ooxml(zf):

        def _open_book() -> IO[bytes]:
            stream.seek(0)
            return _NonClosing(stream)

        return [Member(name=os.path.basename(filename), size=size, opener=_open_book)], []

    members: list[Member] = []
    skipped: list[dict[str, str]] = []
    for info in infos:
        base = os.path.basename(info.filename)
        if base.startswith(("~$", ".")) or "__MACOSX" in info.filename:
            continue
        if not base.lower().endswith(READABLE_EXTENSIONS):
            skipped.append({"name": base, "reason": "not_a_price_list_file"})
            continue

        def _open_member(info: zipfile.ZipInfo = info) -> IO[bytes]:
            # A margin over the declared size: the declared size is what the
            # guard above trusted, and a member that inflates past it lied.
            return io.BufferedReader(_CappedReader(zf.open(info), info.file_size + 1024, info.filename))

        members.append(Member(name=base, size=info.file_size, opener=_open_member))
    return members, skipped


class _NonClosing(io.RawIOBase):
    """A view of the upload stream that a parser may close without closing the upload."""

    def __init__(self, inner: IO[bytes]) -> None:
        self._inner = inner

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        return self._inner.seek(offset, whence)

    def tell(self) -> int:
        return self._inner.tell()

    def readinto(self, buffer) -> int:  # type: ignore[no-untyped-def,override]
        chunk = self._inner.read(len(buffer))
        buffer[: len(chunk)] = chunk
        return len(chunk)

    def read(self, size: int = -1) -> bytes:
        return self._inner.read(size)

    def close(self) -> None:
        # The upload outlives every parse of it; only this view is closed.
        super().close()


__all__ = [
    "MAX_INFLATED_BYTES",
    "MAX_MEMBER_RATIO",
    "MAX_UPLOAD_BYTES",
    "MAX_ZIP_MEMBERS",
    "ContainerRefused",
    "Member",
    "guard_archive",
    "open_members",
    "stream_size",
]
