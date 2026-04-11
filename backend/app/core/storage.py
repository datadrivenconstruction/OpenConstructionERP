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
import logging
import shutil
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config import Settings

logger = logging.getLogger(__name__)


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

    @abstractmethod
    def open_stream(self, key: str) -> AsyncIterator[bytes]:
        """Return an async iterator yielding the blob in chunks.

        Implementations are async-generator functions — the caller
        invokes them **without** ``await`` and iterates the result with
        ``async for``.  Used by the BIM geometry endpoint to feed
        ``StreamingResponse``.
        """
        # Must be a regular (non-async) function that returns an async
        # iterator.  Concrete subclasses implement this as an async
        # generator (``async def`` + ``yield``) which has exactly this
        # runtime signature.
        raise NotImplementedError

    def url_for(self, key: str, *, expires_in: int = 3600) -> str | None:
        """Return a presigned download URL for ``key``.

        The local backend returns ``None`` — callers then fall back to
        serving the blob through their own route via :meth:`open_stream`.
        The S3 backend returns a short-lived presigned ``GET`` URL which
        callers can ``RedirectResponse`` to.
        """
        _ = (key, expires_in)
        return None


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
            raise ValueError(
                f"Storage key {key!r} escapes base_dir {self.base_dir}"
            ) from exc
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
        root = (
            self.base_dir
            if not normalised
            else self.base_dir.joinpath(*normalised.split("/"))
        )

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

    raise ValueError(
        f"Unknown storage backend {backend_name!r}. "
        f"Expected one of: 'local', 's3'."
    )


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
