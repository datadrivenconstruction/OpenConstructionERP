"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pluggable storage backend abstraction.

These tests only exercise :class:`LocalStorageBackend` plus the
settings-driven factory.  The S3 backend is intentionally *not*
tested here — it needs a live MinIO/AWS endpoint and its own
integration harness.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.core.storage import (
    LocalStorageBackend,
    StorageBackend,
    build_storage_backend,
)


@pytest.mark.asyncio
async def test_local_backend_round_trip(tmp_path) -> None:
    """Write → read → delete → re-read against ``LocalStorageBackend``."""
    backend: StorageBackend = LocalStorageBackend(tmp_path)

    key = "bim/proj-1/model-abc/geometry.dae"
    payload = b"<?xml version='1.0'?><COLLADA/>"

    # Write.
    await backend.put(key, payload)

    # Read.
    assert await backend.exists(key) is True
    assert await backend.size(key) == len(payload)
    assert await backend.get(key) == payload

    # Stream.
    chunks: list[bytes] = []
    async for chunk in backend.open_stream(key):
        chunks.append(chunk)
    assert b"".join(chunks) == payload

    # Presigned URL — local backend never presigns.
    assert backend.url_for(key) is None

    # Delete.
    await backend.delete(key)
    assert await backend.exists(key) is False

    # get() on a missing key must raise FileNotFoundError.
    with pytest.raises(FileNotFoundError):
        await backend.get(key)

    # Delete again — must be a silent no-op (rm -f semantics).
    await backend.delete(key)


def test_storage_backend_factory(tmp_path, monkeypatch) -> None:
    """``build_storage_backend`` honours ``settings.storage_backend=local``."""
    # Isolate from the developer's real .env file.
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://oe:oe@localhost:5432/test")
    monkeypatch.setenv("DATABASE_SYNC_URL", "postgresql://oe:oe@localhost:5432/test")

    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://oe:oe@localhost:5432/test",
        database_sync_url="postgresql://oe:oe@localhost:5432/test",
        storage_backend="local",
    )

    backend = build_storage_backend(settings)
    assert isinstance(backend, LocalStorageBackend)

    # The factory should also reject unknown backend names.
    bad = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://oe:oe@localhost:5432/test",
        database_sync_url="postgresql://oe:oe@localhost:5432/test",
    )
    # mypy/pyright would flag this — we bypass the Literal check on purpose.
    object.__setattr__(bad, "storage_backend", "nope")
    with pytest.raises(ValueError, match="Unknown storage backend"):
        build_storage_backend(bad)
