"""LRU-cached, read-only DuckDB connections keyed by snapshot_id.

Why a pool at all?
------------------
DuckDB connections are cheap to open, but each fresh connection has
cold statistics — repeated queries against the same Parquet file benefit
from the zone maps and row-group statistics that DuckDB caches in-process.
Keeping a warm, pinned connection per snapshot also amortises the cost of
registering the Parquet files as views so analytical SQL reads
``FROM entities`` instead of ``FROM read_parquet('/long/absolute/path')``
(the latter both clutters the query and makes log output harder to
redact).

Read-only semantics
-------------------
Connections register Parquet files as **views**, never tables. They are
never given write capabilities. If the snapshot storage changes under
the pool (e.g. T01 delete) the connection is invalidated via
:meth:`DuckDBPool.invalidate`.

Thread-safety
-------------
DuckDB connections are not safe for concurrent access from multiple
threads. To keep the FastAPI event loop responsive we wrap every
execution in :func:`asyncio.to_thread`. Each cached connection gets a
per-snapshot :class:`asyncio.Lock` so concurrent requests on the same
snapshot are serialised, while different snapshots run in parallel.
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.core.cache import _RateLimitedLogger
from app.modules.dashboards.snapshot_storage import (
    ParquetKind,
    ParquetNotLocalError,
    parquet_key,
    resolve_local_parquet_path,
)

if TYPE_CHECKING:
    import duckdb

logger = logging.getLogger(__name__)


# ── Module-level config ─────────────────────────────────────────────────────

DEFAULT_MAX_POOL_SIZE = 16
"""How many warm snapshot connections to keep. Each connection holds an
in-memory DuckDB catalog — ~10-50 MB for a registered-views-only session.
Beyond 16 snapshots we evict the least-recently-used one; the next
request pays the one-off view-registration cost to warm it back up."""

_CONNECT_ERROR_LOGGER = _RateLimitedLogger(window_seconds=60.0)


# ── Error types ─────────────────────────────────────────────────────────────


class DuckDBPoolError(RuntimeError):
    """Base class for pool-level failures. The service layer converts
    these into HTTP status codes; the pool itself never raises HTTP
    directly (so it stays reusable from offline scripts)."""


class DuckDBNotInstalledError(DuckDBPoolError):
    """Raised when the ``duckdb`` package is not importable — which after
    v2.5.0 only happens if an operator manually pinned a minimal extra
    set. Surfaces at first use rather than at import time so the module
    still loads cleanly for static checks."""


class SnapshotHasNoEntitiesError(DuckDBPoolError):
    """Raised when asked to open a pool entry for a snapshot whose
    ``entities.parquet`` is missing. Callers should 404 this — the
    snapshot row exists but the data under it doesn't."""


# ── Pool ────────────────────────────────────────────────────────────────────


class _Entry:
    """One warm snapshot connection plus its serialisation lock."""

    __slots__ = ("conn", "lock", "project_id", "registered_kinds")

    def __init__(
        self,
        conn: duckdb.DuckDBPyConnection,
        project_id: str,
        registered_kinds: set[ParquetKind],
    ) -> None:
        self.conn = conn
        self.lock = asyncio.Lock()
        self.project_id = project_id
        self.registered_kinds = registered_kinds


class DuckDBPool:
    """LRU cache of :class:`duckdb.DuckDBPyConnection` by snapshot id.

    Construct once per application (the :mod:`app.dependencies` factory
    will hand out the singleton via FastAPI's ``Depends``). Every public
    method is async-safe.
    """

    def __init__(self, max_size: int = DEFAULT_MAX_POOL_SIZE) -> None:
        self._max_size = max_size
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self._pool_lock = asyncio.Lock()

    # -- lifecycle --------------------------------------------------------

    async def close_all(self) -> None:
        """Close every warm connection. Called from application shutdown."""
        async with self._pool_lock:
            while self._entries:
                _, entry = self._entries.popitem(last=False)
                try:
                    await asyncio.to_thread(entry.conn.close)
                except Exception as exc:  # pragma: no cover — last-ditch
                    logger.warning(
                        "duckdb_pool.close failed: %s", type(exc).__name__,
                        exc_info=True,
                    )

    async def invalidate(self, snapshot_id: str | UUID) -> None:
        """Drop the warm entry for ``snapshot_id`` (if any).

        Called from T01's delete path so a subsequent query can't hit a
        connection whose underlying Parquet has just been removed.
        """
        sid = str(snapshot_id)
        async with self._pool_lock:
            entry = self._entries.pop(sid, None)
        if entry is not None:
            try:
                await asyncio.to_thread(entry.conn.close)
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    "duckdb_pool.invalidate close failed: %s",
                    type(exc).__name__, exc_info=True,
                )

    # -- query surface ----------------------------------------------------

    async def execute(
        self,
        snapshot_id: str | UUID,
        project_id: str | UUID,
        sql: str,
        parameters: list | tuple | None = None,
        *,
        kinds: tuple[ParquetKind, ...] = ("entities",),
    ) -> list[tuple[Any, ...]]:
        """Execute a parameterised SELECT against a snapshot's Parquet
        views and return rows as a plain Python list.

        Parameters
        ----------
        snapshot_id, project_id:
            Identify the snapshot whose Parquet files should be
            registered as views (if not already).
        sql:
            Query text. View names follow the :class:`ParquetKind`
            literal values (``entities``, ``materials`` …).
        parameters:
            Positional parameters — passed through to DuckDB
            unchanged. Never interpolate user input into ``sql``.
        kinds:
            Which Parquet files to ensure are registered before
            execution. Defaults to just ``entities``; autocomplete
            queries pass ``("entities", "attribute_value_index")``.

        Raises
        ------
        DuckDBNotInstalledError
            If ``duckdb`` is not importable.
        SnapshotHasNoEntitiesError
            If the snapshot's ``entities.parquet`` is missing.
        ParquetNotLocalError
            If the storage backend cannot expose Parquet as a local
            path (see snapshot_storage module docstring).
        """
        entry = await self._get_or_open(snapshot_id, project_id, kinds=kinds)
        return await self._execute_on_entry(entry, sql, parameters)

    # -- internals --------------------------------------------------------

    async def _get_or_open(
        self,
        snapshot_id: str | UUID,
        project_id: str | UUID,
        *,
        kinds: tuple[ParquetKind, ...],
    ) -> _Entry:
        sid = str(snapshot_id)
        pid = str(project_id)

        # Serialise pool mutation (open + register_view + evict) under a
        # single lock. The hot path of executing a query against an
        # already-warm connection uses only the per-entry ``entry.lock``
        # and never enters this critical section at all.
        async with self._pool_lock:
            entry = self._entries.get(sid)
            if entry is None:
                entry = await self._open_new(sid, pid, kinds=kinds)
            else:
                missing = [k for k in kinds if k not in entry.registered_kinds]
                if missing:
                    await self._register_kinds(entry, sid, pid, missing=missing)

            # LRU: move to most-recent end.
            self._entries.pop(sid, None)
            self._entries[sid] = entry

            while len(self._entries) > self._max_size:
                evict_sid, evict_entry = self._entries.popitem(last=False)
                logger.debug("duckdb_pool evict snapshot_id=%s", evict_sid)
                try:
                    await asyncio.to_thread(evict_entry.conn.close)
                except Exception as exc:  # pragma: no cover
                    logger.warning(
                        "duckdb_pool.evict close failed snapshot_id=%s: %s",
                        evict_sid, type(exc).__name__, exc_info=True,
                    )

        return entry

    async def _open_new(
        self,
        sid: str,
        pid: str,
        *,
        kinds: tuple[ParquetKind, ...],
    ) -> _Entry:
        try:
            import duckdb
        except ImportError as exc:  # pragma: no cover
            raise DuckDBNotInstalledError(
                "DuckDB is required for the dashboards module. After v2.5.0 "
                "it is part of base dependencies — reinstall the wheel."
            ) from exc

        try:
            conn = await asyncio.to_thread(duckdb.connect, ":memory:", read_only=False)
        except Exception as exc:
            _CONNECT_ERROR_LOGGER.warn("duckdb_pool.connect", sid, exc)
            raise DuckDBPoolError(f"Failed to open DuckDB connection: {exc}") from exc

        entry = _Entry(conn=conn, project_id=pid, registered_kinds=set())
        await self._register_kinds(entry, sid, pid, missing=list(kinds))
        return entry

    async def _register_kinds(
        self,
        entry: _Entry,
        sid: str,
        pid: str,
        *,
        missing: list[ParquetKind],
    ) -> None:
        """Create one DuckDB view per Parquet file."""
        for kind in missing:
            try:
                path = await resolve_local_parquet_path(pid, sid, kind)
            except FileNotFoundError as exc:
                if kind == "entities":
                    raise SnapshotHasNoEntitiesError(
                        f"Snapshot {sid} has no entities.parquet at key "
                        f"{parquet_key(pid, sid, 'entities')}"
                    ) from exc
                # Non-entities files are optional — skip them silently.
                logger.debug(
                    "duckdb_pool.register_view skip missing kind=%s snapshot_id=%s",
                    kind, sid,
                )
                continue
            except ParquetNotLocalError:
                raise

            # DuckDB refuses prepared parameters inside DDL — the
            # binder raises "Unexpected prepared parameter" on
            # ``CREATE VIEW … read_parquet(?)``. The path comes from
            # our own :func:`resolve_local_parquet_path` (it's the
            # LocalStorageBackend's already-resolved absolute file
            # path), never from user input. Escape single quotes
            # defensively anyway so a pathological base_dir with
            # apostrophes can't break out of the literal.
            escaped_path = path.replace("'", "''")
            view_sql = (
                f"CREATE OR REPLACE VIEW {kind} AS "
                f"SELECT * FROM read_parquet('{escaped_path}')"
            )
            try:
                await asyncio.to_thread(entry.conn.execute, view_sql)
            except Exception as exc:
                _CONNECT_ERROR_LOGGER.warn(
                    f"duckdb_pool.register_view({kind})", sid, exc,
                )
                raise DuckDBPoolError(
                    f"Failed to register view {kind} for snapshot {sid}: {exc}"
                ) from exc
            entry.registered_kinds.add(kind)

    @staticmethod
    async def _execute_on_entry(
        entry: _Entry,
        sql: str,
        parameters: list | tuple | None,
    ) -> list[tuple[Any, ...]]:
        async with entry.lock:
            def _run() -> list[tuple[Any, ...]]:
                cursor = entry.conn.execute(sql, parameters or [])
                return cursor.fetchall()

            return await asyncio.to_thread(_run)


# ── Singleton accessor ─────────────────────────────────────────────────────


_pool: DuckDBPool | None = None


def get_duckdb_pool() -> DuckDBPool:
    """Return the module-level pool singleton, creating it on first use."""
    global _pool
    if _pool is None:
        _pool = DuckDBPool()
    return _pool


async def shutdown_duckdb_pool() -> None:
    """Close all warm connections. Wire into FastAPI's shutdown event."""
    global _pool
    if _pool is not None:
        await _pool.close_all()
        _pool = None
