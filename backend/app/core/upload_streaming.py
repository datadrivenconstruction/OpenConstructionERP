"""‌⁠‍Streaming-upload helper.

UploadFile.read() loads the entire request body into memory.  On the
2 GB-RAM VPS this is a trivial DoS vector once we removed the per-route
size caps (a single 1 GB upload pushes the process into swap; a few
concurrent uploads OOM the box).

This module spools the upload to a real on-disk temp file in 1 MB
chunks, returning a :class:`pathlib.Path` the caller can hand straight
to :meth:`StorageBackend.put_stream` (which on the local backend is a
single ``rename`` syscall — close to free).

A SHA-256 of the upload is computed on the fly so callers don't need a
second pass over the bytes.

Typical use::

    from app.core.upload_streaming import stream_upload_to_temp

    async with stream_upload_to_temp(file) as upload:
        # upload.path: pathlib.Path to the spooled temp file
        # upload.size: int (bytes written)
        # upload.sha256_hex: str
        # upload.head: bytes — first ~64 bytes for magic-byte checks
        await storage.put_stream(key, upload.path)
        # ↑ on success, upload.path is moved/consumed.

The context manager removes the temp file on exit IF it still exists
(i.e. ``put_stream`` failed before consuming it).  Successful streaming
moves the file out from under us, which is fine — ``unlink`` no-ops on
a missing path.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import tempfile
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import UploadFile


_CHUNK = 1 * 1024 * 1024  # 1 MiB
_HEAD_BYTES = 64  # enough for every magic-byte check we run


# ── Proportional subprocess timeout ─────────────────────────────────────────


def proportional_timeout(
    size_bytes: int,
    *,
    min_sec: float = 600.0,
    sec_per_mb: float = 30.0,
    max_sec: float | None = None,
) -> float:
    """‌⁠‍Derive a subprocess wall-time from the size of the input file.

    The old fixed 300 s ceiling we used for CAD/RVT/IFC conversion was a
    silent ceiling on legitimate uploads — a 100 MB hospital RVT model
    routinely needs 8-12 minutes of converter time, and the 5 min cap
    just SIGTERMed it without explanation. We now scale the timeout
    linearly with input size so big-but-real files succeed while a
    runaway converter still gets killed eventually.

    Args:
        size_bytes: Size of the input file on disk.  Negative values are
            clamped to 0 (defensive — callers occasionally pass
            ``stat().st_size`` of a missing file as -1).
        min_sec: Floor — used even for empty/tiny inputs, because
            converter startup itself takes 60-180 s regardless of
            input size. Default 600 s = 10 minutes.
        sec_per_mb: Linear growth rate.  Default 30 s/MB matches the
            slowest real-world DDC converter (Revit shelling out to the
            Teigha format readers on cold-cache).
        max_sec: Optional hard ceiling.  ``None`` (default) means
            unbounded — relies on ``min_sec`` as the only floor and
            the per-MB rate to scale up.

    Returns:
        Timeout in seconds as a float, suitable for
        ``asyncio.wait_for`` or ``subprocess.run(..., timeout=...)``.
    """
    if size_bytes < 0:
        size_bytes = 0
    mb = size_bytes / (1024 * 1024)
    scaled = max(min_sec, sec_per_mb * mb)
    if max_sec is not None:
        scaled = min(scaled, max_sec)
    return float(scaled)


@dataclass(frozen=True)
class StreamedUpload:
    """‌⁠‍The result of streaming a request body to disk."""

    path: Path
    size: int
    sha256_hex: str
    head: bytes
    head_used: int = field(default=_HEAD_BYTES, repr=False)


@contextlib.asynccontextmanager
async def stream_upload_to_temp(
    file: UploadFile,
    *,
    max_bytes: int | None = None,
    suffix: str = "",
) -> AsyncIterator[StreamedUpload]:
    """Spool ``file`` to a temp file in chunks, yield a :class:`StreamedUpload`.

    Args:
        file: The FastAPI ``UploadFile`` to consume.
        max_bytes: Optional hard upper bound — when provided and exceeded
            the temp file is removed and ``ValueError`` is raised before
            the request finishes streaming.  ``None`` keeps the existing
            "no cap" product policy while still bounding *in-memory*
            footprint to the chunk size.
        suffix: Optional file-extension suffix for the temp file (e.g.
            ``".ifc"``) — useful when downstream tools sniff the path.

    The yielded path is removed on exit unless something else moved or
    deleted it first (which is the success case for ``put_stream``).
    """
    fd, tmp_path_str = tempfile.mkstemp(prefix="oce-upload-", suffix=suffix)
    tmp_path = Path(tmp_path_str)
    sha = hashlib.sha256()
    head = bytearray()
    written = 0

    try:
        with os.fdopen(fd, "wb") as out:
            while True:
                chunk = await file.read(_CHUNK)
                if not chunk:
                    break
                if len(head) < _HEAD_BYTES:
                    head.extend(chunk[: _HEAD_BYTES - len(head)])
                sha.update(chunk)
                out.write(chunk)
                written += len(chunk)
                if max_bytes is not None and written > max_bytes:
                    raise ValueError(
                        f"Upload exceeds maximum size of {max_bytes:,} bytes",
                    )
        yield StreamedUpload(
            path=tmp_path,
            size=written,
            sha256_hex=sha.hexdigest(),
            head=bytes(head),
        )
    finally:
        # If put_stream consumed the file, this is a no-op.  If anything
        # raised before then, we leave a clean filesystem behind.
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            # Last-ditch: the temp dir cleaner will handle it eventually.
            pass
