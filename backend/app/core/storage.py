"""Storage backend abstraction for binary blobs.

Used by BIM geometry files, CAD uploads, takeoff PDFs, and generated
reports — anything that today lives under ``data/`` on the local
filesystem should eventually flow through this abstraction so operators
can point OpenConstructionERP at an S3-compatible bucket instead.

Two implementations ship in-tree:

- :class:`LocalStorageBackend` — writes to the local filesystem under a
  base directory.  This is the default and preserves the existing
  v1.3.x on-disk layout byte-for-byte.
- :class:`S3StorageBackend` — writes to an S3-compatible bucket via
  ``aioboto3``.  ``aioboto3`` is declared as an optional dependency
  (``pip install openconstructionerp[s3]``); importing the class
  without it raises a clear :class:`ImportError` only when the user
  actually tries to instantiate it.

Keys
----
Storage keys are forward-slash POSIX-style paths such as
``bim/{project_id}/{model_id}/geometry.dae``.  They never start with a
leading ``/`` and never contain backslashes — the :class:`LocalStorageBackend`
translates them into native paths when touching the filesystem.

Factory
-------
:func:`get_storage_backend` reads the :class:`~app.config.Settings`
singleton and returns the backend configured by the
``STORAGE_BACKEND`` environment variable (``local`` or ``s3``).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import shutil
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config import Settings

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────
# Multipart upload data classes (RFC 34 §4 W0.5)
# ──────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MultipartSession:
    """Handle to an in-progress multipart upload.

    For S3 backends ``upload_id`` is the value returned by
    ``CreateMultipartUpload``; for the local backend it's a UUID4 used as
    the directory name under ``<base>/.multipart/``.

    The session is *resumable*: callers may serialise the dataclass
    (e.g. into Redis or a job row) and reconstruct it later to upload
    further parts or to call :meth:`complete_multipart`.
    """

    upload_id: str
    key: str
    backend: str  # "local" or "s3"
    started_at: datetime
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PartInfo:
    """Result of uploading a single part of a multipart upload.

    ``part_number`` is 1-based to match the S3 multipart API.  ``etag``
    is whatever the backend returns for the part — for S3 it's the MD5
    hex (quoted), for the local backend it's the SHA-256 hex of the
    chunk.
    """

    part_number: int  # 1-based
    etag: str
    size_bytes: int


@dataclass(frozen=True)
class StorageObject:
    """Result of finalising a multipart upload (or any other write that
    wants to expose canonical metadata to the caller).
    """

    key: str
    size_bytes: int
    etag: str
    sha256: str | None = None


@dataclass(frozen=True)
class PresignedUrl:
    """Short-lived URL that lets a caller PUT (or GET) an object directly.

    For the local backend the URL is a same-origin route (handled by a
    FastAPI endpoint that the coordinator must wire up — see the TODO in
    :meth:`LocalStorageBackend.presigned_put_url`).  For S3 it is a true
    presigned URL signed with SigV4.
    """

    url: str
    method: str  # "PUT" usually
    expires_at: datetime
    headers: dict[str, str] = field(default_factory=dict)


# ── HMAC token helpers (used by LocalStorageBackend.presigned_put_url) ──


def _local_upload_token_secret() -> bytes:
    """Resolve the secret used to sign local upload tokens.

    Pulled from ``Settings.jwt_secret`` so it rotates with the rest of
    the auth surface; falls back to a process-local secret if settings
    are unavailable (e.g. during tooling).  The fallback is *not* stable
    across restarts, which is fine — local presigned URLs are intended
    to live for at most an hour.
    """
    try:
        from app.config import get_settings

        secret = getattr(get_settings(), "jwt_secret", None)
    except Exception:  # pragma: no cover - settings unavailable in tooling
        secret = None
    if secret:
        return str(secret).encode("utf-8")
    # Module-level fallback: cache one random secret for the life of the
    # process.  Distinct workers will reject each other's tokens, but a
    # single-process dev deployment is the only target for the local
    # backend anyway.
    global _LOCAL_FALLBACK_SECRET
    try:
        return _LOCAL_FALLBACK_SECRET
    except NameError:
        pass
    _LOCAL_FALLBACK_SECRET = secrets.token_bytes(32)
    return _LOCAL_FALLBACK_SECRET


def _sign_local_upload_token(payload: dict[str, object]) -> str:
    """Encode ``payload`` as a compact HMAC-signed token.

    Format: ``<base64-json>.<hex-hmac-sha256>`` — small, opaque, no
    external dep on PyJWT.  The router endpoint that consumes the token
    must call :func:`_verify_local_upload_token` to unpack it.
    """
    import base64

    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    body_b64 = base64.urlsafe_b64encode(body).rstrip(b"=").decode("ascii")
    sig = hmac.new(_local_upload_token_secret(), body_b64.encode("ascii"), hashlib.sha256)
    return f"{body_b64}.{sig.hexdigest()}"


def _verify_local_upload_token(token: str) -> dict[str, object] | None:
    """Decode and verify a token produced by :func:`_sign_local_upload_token`.

    Returns the payload dict on success, ``None`` on signature mismatch
    or expiry.  The caller (the not-yet-wired router endpoint) is
    responsible for matching ``key`` against the URL path.
    """
    import base64

    try:
        body_b64, sig_hex = token.split(".", 1)
    except ValueError:
        return None
    expected = hmac.new(
        _local_upload_token_secret(), body_b64.encode("ascii"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(sig_hex, expected):
        return None
    try:
        padded = body_b64 + "=" * (-len(body_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (ValueError, json.JSONDecodeError):
        return None
    expires_at = payload.get("expires_at")
    if isinstance(expires_at, (int, float)) and expires_at < time.time():
        return None
    return payload  # type: ignore[no-any-return]


# ──────────────────────────────────────────────────────────────────────────
# Key normalisation
# ──────────────────────────────────────────────────────────────────────────


def _normalise_key(key: str) -> str:
    """Validate and normalise a storage key.

    Raises ``ValueError`` for keys that are absolute, contain ``..``
    segments, or use backslashes.  The result is a POSIX path with no
    leading slash.
    """
    if not isinstance(key, str) or not key:
        raise ValueError("Storage key must be a non-empty string")
    if "\\" in key:
        raise ValueError(f"Storage key must not contain backslashes: {key!r}")
    if key.startswith("/"):
        raise ValueError(f"Storage key must be relative (no leading '/'): {key!r}")
    parts = [p for p in key.split("/") if p]
    if any(p == ".." for p in parts):
        raise ValueError(f"Storage key must not contain '..' segments: {key!r}")
    return "/".join(parts)


# ──────────────────────────────────────────────────────────────────────────
# Abstract base
# ──────────────────────────────────────────────────────────────────────────


class StorageBackend(ABC):
    """Abstract storage backend for binary blobs.

    All methods are async.  Implementations SHOULD not leak the
    underlying backend type into caller code — use :func:`url_for` to
    decide whether to redirect or stream, not ``isinstance`` checks.
    """

    @abstractmethod
    async def put(self, key: str, content: bytes) -> None:
        """Write ``content`` to ``key``, overwriting any existing blob."""

    @abstractmethod
    async def get(self, key: str) -> bytes:
        """Read the blob at ``key`` and return its bytes.

        Raises :class:`FileNotFoundError` if ``key`` does not exist.
        """

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Return ``True`` if a blob is stored under ``key``."""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete the blob at ``key``.

        A missing key is *not* an error — implementations should no-op
        in that case (matches ``rm -f`` semantics).
        """

    @abstractmethod
    async def delete_prefix(self, prefix: str) -> int:
        """Delete every blob whose key starts with ``prefix``.

        Returns the number of blobs removed.
        """

    @abstractmethod
    async def size(self, key: str) -> int:
        """Return the size of the blob at ``key`` in bytes.

        Raises :class:`FileNotFoundError` if ``key`` does not exist.
        """

    async def read_bytes(self, key: str) -> bytes:
        """Return the blob at ``key`` as a single ``bytes`` object.

        Default implementation delegates to :meth:`get`.  Subclasses
        that prefer a ``read_bytes``-shaped API (e.g. simple wrappers
        around ``pathlib.Path.read_bytes``) may override this instead
        of :meth:`get`, in which case the default :meth:`open_stream`
        fallback below will still work — it calls :meth:`read_bytes`.

        Raises :class:`FileNotFoundError` if ``key`` does not exist.
        """
        return await self.get(key)

    async def open_stream(self, key: str) -> AsyncIterator[bytes]:
        """Return an async iterator yielding the blob in chunks.

        Concrete subclasses typically override this as an async
        generator (``async def`` + ``yield``) — see
        :class:`LocalStorageBackend` and :class:`S3StorageBackend`.

        When a subclass implements only :meth:`get` or :meth:`read_bytes`
        but not :meth:`open_stream`, this default reads the whole blob
        into memory and yields it as a single chunk.  That keeps the
        streaming endpoint functional for simple community backends at
        the cost of loading the blob in full — not ideal for large
        files.  A DEBUG line is emitted per call so authors can see
        when the fallback engaged and know to provide a real streaming
        implementation.

        If neither :meth:`read_bytes` (nor its underlying :meth:`get`)
        is overridden, :class:`NotImplementedError` is raised with a
        hint pointing to the two methods the subclass must provide.
        """
        try:
            payload = await self.read_bytes(key)
        except NotImplementedError as exc:
            raise NotImplementedError(
                "StorageBackend subclasses must override either "
                "open_stream() for streamed reads, or read_bytes()/get() "
                "so the default open_stream() fallback has something to "
                "yield. See LocalStorageBackend for an example of the "
                "streaming form."
            ) from exc
        logger.debug(
            "storage.open_stream default fallback engaged for backend=%s key=%r "
            "(%d bytes) — override open_stream() for true streaming",
            type(self).__name__,
            key,
            len(payload),
        )
        yield payload

    def url_for(self, key: str, *, expires_in: int = 3600) -> str | None:
        """Return a presigned download URL for ``key``.

        The local backend returns ``None`` — callers then fall back to
        serving the blob through their own route via :meth:`open_stream`.
        The S3 backend returns a short-lived presigned ``GET`` URL which
        callers can ``RedirectResponse`` to.
        """
        _ = (key, expires_in)
        return None

    # -- Multipart upload (RFC 34 §4 W0.5) ------------------------------
    #
    # These four methods are intentionally *concrete* (not @abstractmethod)
    # so that simple community backends defined before the W0.5 surface
    # existed continue to instantiate.  Backends that don't support
    # multipart uploads will surface a NotImplementedError only when a
    # caller actually invokes one of these methods, not at construction
    # time.  Real implementations live on LocalStorageBackend and
    # S3StorageBackend below.

    async def initiate_multipart(
        self,
        key: str,
        content_type: str | None = None,
    ) -> MultipartSession:
        """Begin a multipart upload for ``key``.

        Returns a :class:`MultipartSession` whose ``upload_id`` callers
        may persist and use to resume the upload from a different
        process or worker.  Backends that don't support multipart raise
        :class:`NotImplementedError`.
        """
        _ = (key, content_type)
        raise NotImplementedError(
            f"{type(self).__name__} does not support multipart uploads"
        )

    async def upload_part(
        self,
        session: MultipartSession,
        part_number: int,
        data: bytes,
    ) -> PartInfo:
        """Upload one chunk of a multipart upload.

        ``part_number`` is 1-based.  S3 requires every part except the
        last to be at least 5 MiB; this is the caller's responsibility —
        the backend does not enforce it because tests and small uploads
        legitimately use shorter parts.
        """
        _ = (session, part_number, data)
        raise NotImplementedError(
            f"{type(self).__name__} does not support multipart uploads"
        )

    async def complete_multipart(
        self,
        session: MultipartSession,
        parts: list[PartInfo],
    ) -> StorageObject:
        """Finalise a multipart upload.

        Concatenates the previously-uploaded parts in ``part_number``
        order, atomically renames the result into the canonical ``key``
        location, and cleans up the staging area.  If
        ``session.metadata`` contains a ``sha256`` hex string, the
        completed object's SHA-256 MUST match — otherwise the staging
        area is left in place and :class:`ValueError` is raised so the
        caller can retry.
        """
        _ = (session, parts)
        raise NotImplementedError(
            f"{type(self).__name__} does not support multipart uploads"
        )

    async def abort_multipart(self, session: MultipartSession) -> None:
        """Cancel a multipart upload and release any staged parts."""
        _ = session
        raise NotImplementedError(
            f"{type(self).__name__} does not support multipart uploads"
        )

    async def presigned_put_url(
        self,
        key: str,
        content_type: str | None = None,
        expires_seconds: int = 3600,
    ) -> PresignedUrl:
        """Return a short-lived URL the caller can ``PUT`` directly to.

        The default implementation refuses — backends that support
        direct browser uploads MUST override.  See
        :class:`LocalStorageBackend` and :class:`S3StorageBackend` for
        the two shipped implementations.
        """
        _ = (key, content_type, expires_seconds)
        raise NotImplementedError(
            f"{type(self).__name__} does not support presigned PUT URLs"
        )


# ──────────────────────────────────────────────────────────────────────────
# Local filesystem implementation
# ──────────────────────────────────────────────────────────────────────────


class LocalStorageBackend(StorageBackend):
    """Filesystem-backed storage under ``base_dir``.

    Every key is resolved to ``base_dir / key`` with parent directories
    created on demand.  I/O happens on a thread to keep the event loop
    responsive; this matches the v1.3.x behaviour without pulling in
    ``aiofiles``.
    """

    _STREAM_CHUNK_SIZE: int = 1024 * 1024  # 1 MiB

    def __init__(self, base_dir: Path) -> None:
        self.base_dir: Path = Path(base_dir).resolve()

    # -- helpers --------------------------------------------------------

    def _path_for(self, key: str) -> Path:
        """Map ``key`` onto the concrete filesystem path."""
        normalised = _normalise_key(key)
        # Translate POSIX key into native parts.
        path = self.base_dir.joinpath(*normalised.split("/"))
        # Defence-in-depth: resolve and ensure containment.
        resolved = path.resolve()
        try:
            resolved.relative_to(self.base_dir)
        except ValueError as exc:
            raise ValueError(f"Storage key {key!r} escapes base_dir {self.base_dir}") from exc
        return resolved

    # -- public API -----------------------------------------------------

    async def put(self, key: str, content: bytes) -> None:
        path = self._path_for(key)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

        await asyncio.to_thread(_write)

    async def get(self, key: str) -> bytes:
        path = self._path_for(key)

        def _read() -> bytes:
            if not path.is_file():
                raise FileNotFoundError(f"No blob at key: {key}")
            return path.read_bytes()

        return await asyncio.to_thread(_read)

    async def exists(self, key: str) -> bool:
        path = self._path_for(key)
        return await asyncio.to_thread(path.is_file)

    async def delete(self, key: str) -> None:
        path = self._path_for(key)

        def _remove() -> None:
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                # Treat a directory key as a prefix sweep.
                shutil.rmtree(path, ignore_errors=True)

        await asyncio.to_thread(_remove)

    async def delete_prefix(self, prefix: str) -> int:
        normalised = _normalise_key(prefix) if prefix else ""
        root = self.base_dir if not normalised else self.base_dir.joinpath(*normalised.split("/"))

        def _sweep() -> int:
            if not root.exists():
                return 0
            count = 0
            if root.is_file():
                root.unlink()
                return 1
            for child in root.rglob("*"):
                if child.is_file():
                    count += 1
            shutil.rmtree(root, ignore_errors=True)
            return count

        return await asyncio.to_thread(_sweep)

    async def size(self, key: str) -> int:
        path = self._path_for(key)

        def _size() -> int:
            if not path.is_file():
                raise FileNotFoundError(f"No blob at key: {key}")
            return path.stat().st_size

        return await asyncio.to_thread(_size)

    async def open_stream(self, key: str) -> AsyncIterator[bytes]:
        path = self._path_for(key)

        def _open() -> object:
            if not path.is_file():
                raise FileNotFoundError(f"No blob at key: {key}")
            return path.open("rb")

        handle = await asyncio.to_thread(_open)
        try:
            while True:
                chunk = await asyncio.to_thread(handle.read, self._STREAM_CHUNK_SIZE)  # type: ignore[attr-defined]
                if not chunk:
                    break
                yield chunk
        finally:
            await asyncio.to_thread(handle.close)  # type: ignore[attr-defined]

    def url_for(self, key: str, *, expires_in: int = 3600) -> str | None:
        # Local backend cannot presign — caller must stream through the route.
        return None

    # -- Multipart upload ------------------------------------------------

    _MULTIPART_DIR_NAME: str = ".multipart"
    _MULTIPART_META_FILE: str = "meta.json"

    def _multipart_root(self) -> Path:
        return self.base_dir / self._MULTIPART_DIR_NAME

    def _multipart_dir(self, upload_id: str) -> Path:
        # Defensive: upload_id is server-generated UUID4 in the happy
        # path, but resumed sessions may pass an attacker-controlled id.
        # Validate that it's a plain hex/uuid string with no separators.
        if not upload_id or any(c in upload_id for c in "/\\."):
            raise ValueError(f"Invalid multipart upload_id: {upload_id!r}")
        return self._multipart_root() / upload_id

    def _part_path(self, upload_id: str, part_number: int) -> Path:
        if part_number < 1:
            raise ValueError(f"part_number must be >= 1, got {part_number}")
        # Zero-pad so a directory listing sorts naturally.
        return self._multipart_dir(upload_id) / f"part-{part_number:05d}"

    async def initiate_multipart(
        self,
        key: str,
        content_type: str | None = None,
    ) -> MultipartSession:
        # Validate key now so callers fail fast before staging anything.
        _normalise_key(key)
        upload_id = uuid.uuid4().hex
        started_at = datetime.now(UTC)
        meta: dict[str, str] = {}
        if content_type:
            meta["content_type"] = content_type

        def _stage() -> None:
            staging = self._multipart_dir(upload_id)
            staging.mkdir(parents=True, exist_ok=True)
            meta_payload = {
                "upload_id": upload_id,
                "key": key,
                "started_at": started_at.isoformat(),
                "metadata": meta,
            }
            (staging / self._MULTIPART_META_FILE).write_text(
                json.dumps(meta_payload),
                encoding="utf-8",
            )

        await asyncio.to_thread(_stage)
        return MultipartSession(
            upload_id=upload_id,
            key=key,
            backend="local",
            started_at=started_at,
            metadata=meta,
        )

    async def upload_part(
        self,
        session: MultipartSession,
        part_number: int,
        data: bytes,
    ) -> PartInfo:
        if session.backend != "local":
            raise ValueError(
                f"Cannot upload local part for session backed by {session.backend!r}"
            )
        path = self._part_path(session.upload_id, part_number)
        # SHA-256 of the chunk doubles as etag and lets the resumed
        # session detect duplicate uploads.
        digest = hashlib.sha256(data).hexdigest()

        def _write() -> int:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Write to a temp neighbour and rename, so a crashed write
            # never half-fills part-N.
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
            return path.stat().st_size

        size_bytes = await asyncio.to_thread(_write)
        return PartInfo(part_number=part_number, etag=digest, size_bytes=size_bytes)

    async def complete_multipart(
        self,
        session: MultipartSession,
        parts: list[PartInfo],
    ) -> StorageObject:
        if session.backend != "local":
            raise ValueError(
                f"Cannot complete local upload for session backed by {session.backend!r}"
            )
        if not parts:
            raise ValueError("complete_multipart requires at least one part")
        # Sort by part_number so callers can pass parts out-of-order
        # (e.g. concurrently uploaded parts collected via gather).
        ordered = sorted(parts, key=lambda p: p.part_number)
        # Verify the sequence is contiguous starting at 1 — S3 enforces
        # the same constraint; the local backend matches it for parity.
        expected_numbers = list(range(1, len(ordered) + 1))
        if [p.part_number for p in ordered] != expected_numbers:
            raise ValueError(
                f"Multipart parts must be contiguous starting at 1, "
                f"got {[p.part_number for p in ordered]}"
            )

        staging = self._multipart_dir(session.upload_id)
        target = self._path_for(session.key)
        expected_sha = session.metadata.get("sha256")

        def _assemble() -> tuple[int, str, str]:
            if not staging.is_dir():
                raise FileNotFoundError(
                    f"Multipart staging area for upload_id={session.upload_id!r} "
                    f"is missing — did abort_multipart already run?"
                )
            # Streaming concat into a temp file under the target's parent
            # so the final rename is atomic and on the same filesystem.
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(
                target.suffix + f".multipart-{session.upload_id}.tmp"
            )
            sha = hashlib.sha256()
            md5 = hashlib.md5(usedforsecurity=False)  # noqa: S324  (etag only)
            total = 0
            chunk_size = 1024 * 1024
            with tmp.open("wb") as out:
                for part in ordered:
                    part_path = self._part_path(session.upload_id, part.part_number)
                    if not part_path.is_file():
                        raise FileNotFoundError(
                            f"Missing part {part.part_number} for upload "
                            f"{session.upload_id!r}"
                        )
                    with part_path.open("rb") as part_in:
                        while True:
                            buf = part_in.read(chunk_size)
                            if not buf:
                                break
                            sha.update(buf)
                            md5.update(buf)
                            out.write(buf)
                            total += len(buf)
            sha_hex = sha.hexdigest()
            md5_hex = md5.hexdigest()
            if expected_sha and expected_sha.lower() != sha_hex.lower():
                # Leave staging in place so the caller can retry.
                tmp.unlink(missing_ok=True)
                raise ValueError(
                    f"SHA-256 mismatch for multipart upload {session.upload_id!r}: "
                    f"expected={expected_sha} actual={sha_hex}"
                )
            tmp.replace(target)
            shutil.rmtree(staging, ignore_errors=True)
            return total, md5_hex, sha_hex

        total, md5_hex, sha_hex = await asyncio.to_thread(_assemble)
        return StorageObject(
            key=_normalise_key(session.key),
            size_bytes=total,
            etag=md5_hex,
            sha256=sha_hex,
        )

    async def abort_multipart(self, session: MultipartSession) -> None:
        if session.backend != "local":
            raise ValueError(
                f"Cannot abort local upload for session backed by {session.backend!r}"
            )
        staging = self._multipart_dir(session.upload_id)

        def _remove() -> None:
            if staging.is_dir():
                shutil.rmtree(staging, ignore_errors=True)

        await asyncio.to_thread(_remove)

    async def presigned_put_url(
        self,
        key: str,
        content_type: str | None = None,
        expires_seconds: int = 3600,
    ) -> PresignedUrl:
        """Return a same-origin URL with a signed token.

        The matching PUT endpoint lives at
        ``app.modules.uploads.router`` (mounted at
        ``/api/v1/uploads/local/{token}``) — it verifies the token via
        ``_verify_local_upload_token``, confirms the path's ``key``
        matches the token payload, and streams the request body into
        ``LocalStorageBackend.put`` (or ``upload_part`` when a multipart
        ``upload_id`` is present).
        """
        normalised = _normalise_key(key)
        expires_at = datetime.now(UTC) + timedelta(seconds=int(expires_seconds))
        payload = {
            "key": normalised,
            "expires_at": int(expires_at.timestamp()),
            "content_type": content_type or "",
        }
        token = _sign_local_upload_token(payload)
        # Same-origin path; the deployment's reverse proxy decides the host.
        url = f"/api/v1/uploads/local/{token}"
        headers: dict[str, str] = {}
        if content_type:
            headers["Content-Type"] = content_type
        return PresignedUrl(
            url=url,
            method="PUT",
            expires_at=expires_at,
            headers=headers,
        )


# ──────────────────────────────────────────────────────────────────────────
# S3 implementation (optional dependency: aioboto3)
# ──────────────────────────────────────────────────────────────────────────


class S3StorageBackend(StorageBackend):
    """S3-compatible storage backend.

    Works with AWS S3, MinIO, Backblaze B2, DigitalOcean Spaces, and any
    other S3-protocol service.  Requires the ``aioboto3`` optional
    dependency — install it via ``pip install openconstructionerp[s3]``.
    """

    _STREAM_CHUNK_SIZE: int = 1024 * 1024  # 1 MiB

    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str,
    ) -> None:
        try:
            import aioboto3  # noqa: F401  (import-time check only)
        except ImportError as exc:  # pragma: no cover - exercised at runtime
            raise ImportError(
                "S3StorageBackend requires the 'aioboto3' package. "
                "Install it with: pip install 'openconstructionerp[s3]'"
            ) from exc

        self._endpoint: str = endpoint
        self._access_key: str = access_key
        self._secret_key: str = secret_key
        self._bucket: str = bucket
        self._region: str = region
        # Lazy — a session is cheap but we still cache one instance.
        self._session: object | None = None

    # -- helpers --------------------------------------------------------

    def _get_session(self) -> object:
        if self._session is None:
            import aioboto3  # local import keeps base install lean

            self._session = aioboto3.Session()
        return self._session

    def _client_ctx(self) -> object:
        session = self._get_session()
        return session.client(  # type: ignore[attr-defined]
            "s3",
            endpoint_url=self._endpoint or None,
            aws_access_key_id=self._access_key or None,
            aws_secret_access_key=self._secret_key or None,
            region_name=self._region or None,
        )

    # -- public API -----------------------------------------------------

    async def put(self, key: str, content: bytes) -> None:
        normalised = _normalise_key(key)
        async with self._client_ctx() as client:  # type: ignore[attr-defined]
            await client.put_object(Bucket=self._bucket, Key=normalised, Body=content)

    async def get(self, key: str) -> bytes:
        normalised = _normalise_key(key)
        async with self._client_ctx() as client:  # type: ignore[attr-defined]
            try:
                resp = await client.get_object(Bucket=self._bucket, Key=normalised)
            except Exception as exc:
                if _is_not_found(exc):
                    raise FileNotFoundError(f"No blob at key: {key}") from exc
                raise
            async with resp["Body"] as body:
                return await body.read()  # type: ignore[no-any-return]

    async def exists(self, key: str) -> bool:
        normalised = _normalise_key(key)
        async with self._client_ctx() as client:  # type: ignore[attr-defined]
            try:
                await client.head_object(Bucket=self._bucket, Key=normalised)
                return True
            except Exception as exc:
                if _is_not_found(exc):
                    return False
                raise

    async def delete(self, key: str) -> None:
        normalised = _normalise_key(key)
        async with self._client_ctx() as client:  # type: ignore[attr-defined]
            await client.delete_object(Bucket=self._bucket, Key=normalised)

    async def delete_prefix(self, prefix: str) -> int:
        normalised = _normalise_key(prefix) if prefix else ""
        removed = 0
        async with self._client_ctx() as client:  # type: ignore[attr-defined]
            continuation: str | None = None
            while True:
                kwargs: dict[str, object] = {
                    "Bucket": self._bucket,
                    "Prefix": normalised,
                }
                if continuation:
                    kwargs["ContinuationToken"] = continuation
                resp = await client.list_objects_v2(**kwargs)
                contents = resp.get("Contents") or []
                if contents:
                    delete_payload = {
                        "Objects": [{"Key": obj["Key"]} for obj in contents],
                        "Quiet": True,
                    }
                    await client.delete_objects(
                        Bucket=self._bucket,
                        Delete=delete_payload,
                    )
                    removed += len(contents)
                if not resp.get("IsTruncated"):
                    break
                continuation = resp.get("NextContinuationToken")
        return removed

    async def size(self, key: str) -> int:
        normalised = _normalise_key(key)
        async with self._client_ctx() as client:  # type: ignore[attr-defined]
            try:
                resp = await client.head_object(Bucket=self._bucket, Key=normalised)
            except Exception as exc:
                if _is_not_found(exc):
                    raise FileNotFoundError(f"No blob at key: {key}") from exc
                raise
            return int(resp["ContentLength"])

    async def open_stream(self, key: str) -> AsyncIterator[bytes]:
        normalised = _normalise_key(key)
        async with self._client_ctx() as client:  # type: ignore[attr-defined]
            try:
                resp = await client.get_object(Bucket=self._bucket, Key=normalised)
            except Exception as exc:
                if _is_not_found(exc):
                    raise FileNotFoundError(f"No blob at key: {key}") from exc
                raise
            async with resp["Body"] as body:
                while True:
                    chunk = await body.read(self._STREAM_CHUNK_SIZE)
                    if not chunk:
                        break
                    yield chunk

    def url_for(self, key: str, *, expires_in: int = 3600) -> str | None:
        """Return a presigned download URL (synchronous — uses botocore).

        ``aioboto3`` presigning is sync-safe because it just signs
        strings; no network calls happen here.
        """
        normalised = _normalise_key(key)
        try:
            import boto3  # botocore comes in via aioboto3, but boto3 is the

            # canonical presigner.  It is pulled in as a dependency of
            # aioboto3 so this import is safe when S3StorageBackend is
            # instantiated.
            from botocore.config import Config
        except ImportError:  # pragma: no cover - aioboto3 pulls boto3 in
            return None

        cfg = Config(signature_version="s3v4", region_name=self._region or None)
        client = boto3.client(
            "s3",
            endpoint_url=self._endpoint or None,
            aws_access_key_id=self._access_key or None,
            aws_secret_access_key=self._secret_key or None,
            region_name=self._region or None,
            config=cfg,
        )
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": normalised},
            ExpiresIn=int(expires_in),
        )

    # -- Multipart upload ------------------------------------------------

    async def initiate_multipart(
        self,
        key: str,
        content_type: str | None = None,
    ) -> MultipartSession:
        normalised = _normalise_key(key)
        kwargs: dict[str, object] = {"Bucket": self._bucket, "Key": normalised}
        if content_type:
            kwargs["ContentType"] = content_type
        async with self._client_ctx() as client:  # type: ignore[attr-defined]
            resp = await client.create_multipart_upload(**kwargs)
        meta: dict[str, str] = {}
        if content_type:
            meta["content_type"] = content_type
        return MultipartSession(
            upload_id=str(resp["UploadId"]),
            key=normalised,
            backend="s3",
            started_at=datetime.now(UTC),
            metadata=meta,
        )

    async def upload_part(
        self,
        session: MultipartSession,
        part_number: int,
        data: bytes,
    ) -> PartInfo:
        if session.backend != "s3":
            raise ValueError(
                f"Cannot upload S3 part for session backed by {session.backend!r}"
            )
        if part_number < 1:
            raise ValueError(f"part_number must be >= 1, got {part_number}")
        async with self._client_ctx() as client:  # type: ignore[attr-defined]
            resp = await client.upload_part(
                Bucket=self._bucket,
                Key=session.key,
                UploadId=session.upload_id,
                PartNumber=part_number,
                Body=data,
            )
        return PartInfo(
            part_number=part_number,
            etag=str(resp["ETag"]).strip('"'),
            size_bytes=len(data),
        )

    async def complete_multipart(
        self,
        session: MultipartSession,
        parts: list[PartInfo],
    ) -> StorageObject:
        if session.backend != "s3":
            raise ValueError(
                f"Cannot complete S3 upload for session backed by {session.backend!r}"
            )
        if not parts:
            raise ValueError("complete_multipart requires at least one part")
        ordered = sorted(parts, key=lambda p: p.part_number)
        multipart_payload = {
            "Parts": [
                {"ETag": f'"{p.etag.strip(chr(34))}"', "PartNumber": p.part_number}
                for p in ordered
            ],
        }
        async with self._client_ctx() as client:  # type: ignore[attr-defined]
            resp = await client.complete_multipart_upload(
                Bucket=self._bucket,
                Key=session.key,
                UploadId=session.upload_id,
                MultipartUpload=multipart_payload,
            )
            head = await client.head_object(Bucket=self._bucket, Key=session.key)
        total = int(head["ContentLength"])
        etag = str(resp.get("ETag", head.get("ETag", ""))).strip('"')
        # SHA-256 verification: S3 doesn't return SHA-256 by default; if
        # the caller stashed an expected digest in session.metadata they
        # are responsible for verifying it via a follow-up GET.  We
        # return the ETag (an S3-side digest) as the canonical etag.
        return StorageObject(
            key=session.key,
            size_bytes=total,
            etag=etag,
            sha256=session.metadata.get("sha256"),
        )

    async def abort_multipart(self, session: MultipartSession) -> None:
        if session.backend != "s3":
            raise ValueError(
                f"Cannot abort S3 upload for session backed by {session.backend!r}"
            )
        async with self._client_ctx() as client:  # type: ignore[attr-defined]
            await client.abort_multipart_upload(
                Bucket=self._bucket,
                Key=session.key,
                UploadId=session.upload_id,
            )

    async def presigned_put_url(
        self,
        key: str,
        content_type: str | None = None,
        expires_seconds: int = 3600,
    ) -> PresignedUrl:
        normalised = _normalise_key(key)
        expires_at = datetime.now(UTC) + timedelta(seconds=int(expires_seconds))
        try:
            import boto3
            from botocore.config import Config
        except ImportError as exc:  # pragma: no cover - aioboto3 pulls boto3 in
            raise ImportError(
                "S3StorageBackend.presigned_put_url requires boto3 "
                "(installed transitively via aioboto3)"
            ) from exc

        cfg = Config(signature_version="s3v4", region_name=self._region or None)
        client = boto3.client(
            "s3",
            endpoint_url=self._endpoint or None,
            aws_access_key_id=self._access_key or None,
            aws_secret_access_key=self._secret_key or None,
            region_name=self._region or None,
            config=cfg,
        )
        params: dict[str, object] = {"Bucket": self._bucket, "Key": normalised}
        if content_type:
            params["ContentType"] = content_type
        url = client.generate_presigned_url(
            "put_object",
            Params=params,
            ExpiresIn=int(expires_seconds),
        )
        headers: dict[str, str] = {}
        if content_type:
            headers["Content-Type"] = content_type
        return PresignedUrl(
            url=str(url),
            method="PUT",
            expires_at=expires_at,
            headers=headers,
        )


def _is_not_found(exc: BaseException) -> bool:
    """Best-effort ``404``/``NoSuchKey`` detection for aioboto3 errors."""
    msg = str(exc)
    if "NoSuchKey" in msg or "Not Found" in msg or "404" in msg:
        return True
    resp = getattr(exc, "response", None)
    if isinstance(resp, dict):
        status_code = resp.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if status_code in (404, "404"):
            return True
        code = resp.get("Error", {}).get("Code")
        if code in ("404", "NoSuchKey", "NotFound"):
            return True
    return False


# ──────────────────────────────────────────────────────────────────────────
# Factory
# ──────────────────────────────────────────────────────────────────────────


def _default_local_base_dir() -> Path:
    """Where local blobs live by default.

    Resolves to ``<repo>/data/`` — same layout as v1.3.x so upgrading
    installs don't need to touch disk.  ``app/core/storage.py`` →
    ``parents[3]`` == repo root.
    """
    return Path(__file__).resolve().parents[3] / "data"


def build_storage_backend(settings: Settings) -> StorageBackend:
    """Build a backend from ``settings`` without consulting any cache.

    Exposed so tests can construct a backend against custom settings.
    """
    backend_name = (getattr(settings, "storage_backend", "local") or "local").lower()

    if backend_name == "local":
        return LocalStorageBackend(_default_local_base_dir())

    if backend_name == "s3":
        return S3StorageBackend(
            endpoint=settings.s3_endpoint,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            bucket=settings.s3_bucket,
            region=settings.s3_region,
        )

    raise ValueError(f"Unknown storage backend {backend_name!r}. Expected one of: 'local', 's3'.")


@lru_cache(maxsize=1)
def get_storage_backend() -> StorageBackend:
    """Return the singleton backend configured by application settings."""
    from app.config import get_settings

    return build_storage_backend(get_settings())


def reset_storage_backend_cache() -> None:
    """Clear the :func:`get_storage_backend` singleton.

    Used by tests that flip ``storage_backend`` between cases.
    """
    get_storage_backend.cache_clear()
