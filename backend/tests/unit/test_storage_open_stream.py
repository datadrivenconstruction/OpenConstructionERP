"""Unit tests for :meth:`StorageBackend.open_stream` default fallback (v2.4.0).

Audit finding: :meth:`StorageBackend.open_stream` was declared as
``@abstractmethod`` and unconditionally raised ``NotImplementedError``
when a subclass forgot it.  Simple community backends that only
implement ``read_bytes``/``get`` still needed a streamed-read path for
the BIM viewer endpoint, so we now:

* provide a default :meth:`read_bytes` that delegates to :meth:`get`;
* downgrade :meth:`open_stream` to a concrete default that calls
  :meth:`read_bytes` and yields a single chunk (logged at DEBUG so the
  backend author notices);
* still raise a helpful :class:`NotImplementedError` when neither
  :meth:`read_bytes` nor :meth:`get` produces bytes.

These tests pin all three behaviours down.
"""

from __future__ import annotations

import logging

import pytest

from app.core.storage import StorageBackend

# ---------------------------------------------------------------------------
# Test subclasses
# ---------------------------------------------------------------------------


class OnlyReadBytesBackend(StorageBackend):
    """A minimal community backend: implements ``read_bytes`` directly,
    leaves ``get`` as a stub that raises so we can prove the fallback
    uses ``read_bytes`` and never touches ``get``.
    """

    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}

    async def put(self, key: str, content: bytes) -> None:
        self._store[key] = content

    async def get(self, key: str) -> bytes:
        # A naive subclass might deliberately not implement ``get``.
        # The default ``open_stream`` must NOT reach this path if
        # ``read_bytes`` is overridden.
        raise NotImplementedError("this backend only implements read_bytes")

    async def read_bytes(self, key: str) -> bytes:
        if key not in self._store:
            raise FileNotFoundError(key)
        return self._store[key]

    async def exists(self, key: str) -> bool:
        return key in self._store

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    async def delete_prefix(self, prefix: str) -> int:
        victims = [k for k in self._store if k.startswith(prefix)]
        for k in victims:
            del self._store[k]
        return len(victims)

    async def size(self, key: str) -> int:
        if key not in self._store:
            raise FileNotFoundError(key)
        return len(self._store[key])


class OnlyGetBackend(StorageBackend):
    """Backend that overrides ``get`` but not ``read_bytes`` — validates
    that the default ``read_bytes`` delegates to ``get`` correctly.
    """

    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}

    async def put(self, key: str, content: bytes) -> None:
        self._store[key] = content

    async def get(self, key: str) -> bytes:
        if key not in self._store:
            raise FileNotFoundError(key)
        return self._store[key]

    async def exists(self, key: str) -> bool:
        return key in self._store

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    async def delete_prefix(self, prefix: str) -> int:
        victims = [k for k in self._store if k.startswith(prefix)]
        for k in victims:
            del self._store[k]
        return len(victims)

    async def size(self, key: str) -> int:
        return len(self._store[key])


class NothingBackend(StorageBackend):
    """Backend that implements neither ``read_bytes`` nor a working
    ``get`` — must yield a helpful ``NotImplementedError`` when a
    caller tries to stream.
    """

    async def put(self, key: str, content: bytes) -> None:
        return None

    async def get(self, key: str) -> bytes:
        raise NotImplementedError

    async def exists(self, key: str) -> bool:
        return False

    async def delete(self, key: str) -> None:
        return None

    async def delete_prefix(self, prefix: str) -> int:
        return 0

    async def size(self, key: str) -> int:
        raise FileNotFoundError


# ---------------------------------------------------------------------------
# Streaming fallback
# ---------------------------------------------------------------------------


class TestOpenStreamFallback:
    @pytest.mark.asyncio
    async def test_subclass_with_only_read_bytes_streams_via_default(self, caplog):
        backend = OnlyReadBytesBackend()
        await backend.put("reports/year.csv", b"A,B,C\n1,2,3\n")

        with caplog.at_level(logging.DEBUG, logger="app.core.storage"):
            chunks: list[bytes] = []
            async for chunk in backend.open_stream("reports/year.csv"):
                chunks.append(chunk)

        assert b"".join(chunks) == b"A,B,C\n1,2,3\n"

        # DEBUG note for backend authors.
        debug_records = [
            rec for rec in caplog.records if "storage.open_stream default fallback engaged" in rec.getMessage()
        ]
        assert debug_records
        assert debug_records[0].levelno == logging.DEBUG
        # The log line mentions the subclass name + key.
        assert "OnlyReadBytesBackend" in debug_records[0].getMessage()
        assert "reports/year.csv" in debug_records[0].getMessage()

    @pytest.mark.asyncio
    async def test_default_read_bytes_delegates_to_get(self):
        backend = OnlyGetBackend()
        await backend.put("k", b"payload")

        # read_bytes (default) pulls from get (overridden).
        assert await backend.read_bytes("k") == b"payload"

        # open_stream fallback → read_bytes → get → yields everything.
        chunks = []
        async for chunk in backend.open_stream("k"):
            chunks.append(chunk)
        assert b"".join(chunks) == b"payload"

    @pytest.mark.asyncio
    async def test_file_not_found_propagates_through_fallback(self):
        backend = OnlyReadBytesBackend()
        with pytest.raises(FileNotFoundError):
            async for _ in backend.open_stream("missing.bin"):
                pass  # pragma: no cover — the first iteration raises

    @pytest.mark.asyncio
    async def test_backend_without_read_bytes_or_get_raises_helpful_error(self):
        backend = NothingBackend()
        with pytest.raises(NotImplementedError) as excinfo:
            async for _ in backend.open_stream("anything"):
                pass  # pragma: no cover

        msg = str(excinfo.value)
        # The message names both alternative hooks so authors can fix
        # their subclass quickly.
        assert "open_stream" in msg
        assert "read_bytes" in msg
        assert "get" in msg or "LocalStorageBackend" in msg
        # The original NotImplementedError is preserved as __cause__
        # for debuggers.
        assert isinstance(excinfo.value.__cause__, NotImplementedError)


# ---------------------------------------------------------------------------
# Existing LocalStorageBackend is still the gold-standard override
# ---------------------------------------------------------------------------


class TestLocalBackendOverrideStillWorks:
    @pytest.mark.asyncio
    async def test_local_backend_does_not_use_fallback(self, tmp_path, caplog):
        """The real :class:`LocalStorageBackend` overrides ``open_stream``
        so the DEBUG fallback line must NOT fire for it.
        """
        from app.core.storage import LocalStorageBackend

        backend = LocalStorageBackend(tmp_path)
        await backend.put("x.bin", b"xyz")

        with caplog.at_level(logging.DEBUG, logger="app.core.storage"):
            chunks = []
            async for chunk in backend.open_stream("x.bin"):
                chunks.append(chunk)

        assert b"".join(chunks) == b"xyz"
        assert not [rec for rec in caplog.records if "storage.open_stream default fallback engaged" in rec.getMessage()]
