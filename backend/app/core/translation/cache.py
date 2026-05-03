"""Async SQLite cache of past translations.

Lives in a dedicated SQLite file (default
``~/.openestimate/translations/cache.db``) so it doesn't pollute the
main application database — caches are easy to throw away and don't
need to be part of regular Alembic migrations.

An Alembic migration (see ``alembic/versions/v280_translation_cache.py``)
*also* creates the table inside the main DB for deployments that prefer a
single-file layout (e.g. multi-tenant SaaS where every artefact must be
backed up together). Both code paths use the same column names so a
future merge is straightforward.

In-process LRU
==============
Even with the SQLite cache, every translate() under concurrent match
load issues an OS-level SELECT — for 50 walls of identical material in
one batch that's 50 SELECTs on identical keys. We layer an in-process
LRU cache on top so a single SELECT round-trip is amortised across
the whole batch. The LRU is invalidated on every ``upsert()`` so a
new translation written by one request is visible to the next one.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import logging
import sqlite3
import threading
from collections import OrderedDict
from typing import Any

from app.core.translation.paths import cache_db_path

logger = logging.getLogger(__name__)


# ── In-process LRU on top of the SQLite cache ───────────────────────────
#
# Bounded by ``_LRU_MAXSIZE`` (~1k entries — a few MB at most for typical
# construction-domain phrases). Each entry is the dict shape returned by
# :meth:`TranslationCache.get` so the cache layer above can pretend it
# came straight from SQLite. A ``None`` sentinel marks "looked up but
# missed" so we don't re-query SQLite for a known cold key.
#
# Key shape ``(db_path, text_hash, src, tgt, domain)`` — the path prefix
# is critical for test isolation: every pytest creates its own temp
# SQLite file, but module-level state outlives the test, so without the
# path two tests with identical ``(text, src, tgt, domain)`` would hand
# each other stale rows from a long-deleted DB.
_LRU_MAXSIZE = 1024
_LRUKey = tuple[str, str, str, str, str]
_lru: OrderedDict[_LRUKey, dict[str, Any] | None] = OrderedDict()
# Reverse index ``row_id → key`` so ``mark_used`` (which only knows the
# row id) can invalidate the matching LRU entry. Without this, a hit
# that bumps ``usage_count`` in SQLite would still serve the stale
# ``usage_count`` from the LRU on the next ``get()``.
_lru_by_row_id: dict[int, _LRUKey] = {}
_lru_lock = threading.Lock()


def _lru_get(key: _LRUKey) -> tuple[bool, dict[str, Any] | None]:
    """Return ``(hit, value)`` — caller distinguishes "miss" from "known None"."""
    with _lru_lock:
        if key not in _lru:
            return False, None
        value = _lru.pop(key)
        _lru[key] = value
        return True, value


def _lru_put(key: _LRUKey, value: dict[str, Any] | None) -> None:
    with _lru_lock:
        if key in _lru:
            old = _lru.pop(key)
            if old and "id" in old:
                _lru_by_row_id.pop(int(old["id"]), None)
        _lru[key] = value
        if value and "id" in value:
            _lru_by_row_id[int(value["id"])] = key
        while len(_lru) > _LRU_MAXSIZE:
            _, evicted = _lru.popitem(last=False)
            if evicted and "id" in evicted:
                _lru_by_row_id.pop(int(evicted["id"]), None)


def _lru_invalidate(key: _LRUKey | None = None) -> None:
    """Drop one or all entries from the in-process LRU.

    Called on every ``upsert()`` so a write is visible on the next
    ``get()`` from any other coroutine — without this, a freshly cached
    translation would be hidden by a stale ``None`` sentinel for as
    long as the entry stayed in the LRU.
    """
    with _lru_lock:
        if key is None:
            _lru.clear()
            _lru_by_row_id.clear()
        else:
            old = _lru.pop(key, None)
            if old and "id" in old:
                _lru_by_row_id.pop(int(old["id"]), None)


def _lru_invalidate_by_row_id(row_id: int) -> None:
    """Drop the LRU entry that points at ``row_id``.

    ``mark_used`` only knows the row id, not the (text, src, tgt, domain)
    tuple — without this hook, a usage_count bump would persist to
    SQLite but stay invisible to subsequent ``get()`` calls served by
    the LRU.
    """
    with _lru_lock:
        key = _lru_by_row_id.pop(row_id, None)
        if key is not None:
            _lru.pop(key, None)


def lru_stats() -> dict[str, int]:
    """Stats for tests / observability."""
    with _lru_lock:
        return {"entries": len(_lru), "maxsize": _LRU_MAXSIZE}


_SCHEMA = """
CREATE TABLE IF NOT EXISTS oe_translation_cache (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    text_hash       TEXT NOT NULL,
    source_lang     TEXT NOT NULL,
    target_lang     TEXT NOT NULL,
    domain          TEXT NOT NULL DEFAULT 'construction',
    translated_text TEXT NOT NULL,
    tier_used       TEXT NOT NULL,
    confidence      REAL NOT NULL DEFAULT 1.0,
    created_at      TEXT NOT NULL,
    usage_count     INTEGER NOT NULL DEFAULT 1,
    last_used_at    TEXT NOT NULL
);
"""

_UNIQUE_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS uq_oe_translation_cache_key
ON oe_translation_cache (text_hash, source_lang, target_lang, domain);
"""


def _hash(text: str) -> str:
    # SHA1 is fine here — it's a cache key, not a security primitive.
    # ``usedforsecurity=False`` silences Bandit B324 / FIPS-mode warnings.
    return hashlib.sha1(text.encode("utf-8"), usedforsecurity=False).hexdigest()


def _now_iso() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


class TranslationCache:
    """Thin async wrapper over a synchronous sqlite3 connection.

    sqlite3 is synchronous but each call is microseconds-fast for the row
    counts we care about (tens of thousands at most). We dispatch the
    actual SQL through ``run_in_executor`` to keep the event loop free.
    Running on a fresh sqlite connection per call keeps us thread-safe
    without serialising the whole cache behind a single lock.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._path = str(cache_db_path(db_path))
        # Ensure schema exists — cheap, idempotent.
        self._ensure_schema()

    # ── helpers ─────────────────────────────────────────────────────

    def _ensure_schema(self) -> None:
        try:
            con = sqlite3.connect(self._path)
            try:
                con.execute(_SCHEMA)
                con.execute(_UNIQUE_INDEX)
                con.commit()
            finally:
                con.close()
        except sqlite3.Error as exc:
            logger.debug("Translation cache schema init failed: %s", exc)

    async def _run(self, fn, *args: Any) -> Any:
        return await asyncio.get_running_loop().run_in_executor(None, fn, *args)

    # ── public API ──────────────────────────────────────────────────

    async def get(
        self, text: str, source_lang: str, target_lang: str, domain: str
    ) -> dict[str, Any] | None:
        """Return cached row as a dict, or ``None`` if no hit.

        Backed by an in-process LRU keyed on ``(text_hash, src, tgt,
        domain)`` so 50 concurrent match requests with identical
        envelopes do one SQLite SELECT, not 50.
        """
        h = _hash(text)
        key = (self._path, h, source_lang, target_lang, domain)

        hit, cached = _lru_get(key)
        if hit:
            return cached

        def _do() -> dict[str, Any] | None:
            con = sqlite3.connect(self._path)
            try:
                con.row_factory = sqlite3.Row
                cur = con.execute(
                    "SELECT id, translated_text, tier_used, confidence, "
                    "usage_count, created_at, last_used_at "
                    "FROM oe_translation_cache "
                    "WHERE text_hash = ? AND source_lang = ? "
                    "AND target_lang = ? AND domain = ?",
                    (h, source_lang, target_lang, domain),
                )
                row = cur.fetchone()
                return dict(row) if row else None
            finally:
                con.close()

        result = await self._run(_do)
        _lru_put(key, result)
        return result

    async def upsert(
        self,
        *,
        text: str,
        translated_text: str,
        source_lang: str,
        target_lang: str,
        domain: str,
        tier_used: str,
        confidence: float,
    ) -> None:
        """Insert or update a cache row.

        On conflict (same text+langs+domain) we keep the highest-confidence
        translation and bump ``usage_count``.
        """
        h = _hash(text)
        now = _now_iso()
        key = (self._path, h, source_lang, target_lang, domain)

        def _do() -> None:
            con = sqlite3.connect(self._path)
            try:
                con.execute(
                    "INSERT INTO oe_translation_cache "
                    "(text_hash, source_lang, target_lang, domain, "
                    " translated_text, tier_used, confidence, "
                    " created_at, usage_count, last_used_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?) "
                    "ON CONFLICT (text_hash, source_lang, target_lang, domain) "
                    "DO UPDATE SET "
                    "  translated_text = CASE "
                    "    WHEN excluded.confidence > oe_translation_cache.confidence "
                    "    THEN excluded.translated_text "
                    "    ELSE oe_translation_cache.translated_text END, "
                    "  tier_used = CASE "
                    "    WHEN excluded.confidence > oe_translation_cache.confidence "
                    "    THEN excluded.tier_used "
                    "    ELSE oe_translation_cache.tier_used END, "
                    "  confidence = MAX(oe_translation_cache.confidence, excluded.confidence), "
                    "  usage_count = oe_translation_cache.usage_count + 1, "
                    "  last_used_at = excluded.last_used_at",
                    (
                        h,
                        source_lang,
                        target_lang,
                        domain,
                        translated_text,
                        tier_used,
                        confidence,
                        now,
                        now,
                    ),
                )
                con.commit()
            finally:
                con.close()

        await self._run(_do)
        # Invalidate the LRU entry so the next ``get()`` reads the
        # freshly written row instead of a stale "None" sentinel from
        # a previous miss.
        _lru_invalidate(key)

    async def mark_used(self, row_id: int) -> None:
        """Bump ``usage_count`` and refresh ``last_used_at`` on a hit."""
        now = _now_iso()

        def _do() -> None:
            con = sqlite3.connect(self._path)
            try:
                con.execute(
                    "UPDATE oe_translation_cache "
                    "SET usage_count = usage_count + 1, last_used_at = ? "
                    "WHERE id = ?",
                    (now, row_id),
                )
                con.commit()
            finally:
                con.close()

        await self._run(_do)
        # Drop the LRU entry so the next ``get()`` reads the freshly
        # bumped ``usage_count``/``last_used_at`` from SQLite instead
        # of the row that was cached at insert time.
        _lru_invalidate_by_row_id(int(row_id))

    async def stats(self) -> dict[str, Any]:
        """Return basic counts for the status endpoint."""

        def _do() -> dict[str, Any]:
            con = sqlite3.connect(self._path)
            try:
                con.row_factory = sqlite3.Row
                cur = con.execute(
                    "SELECT COUNT(*) AS rows, "
                    "COALESCE(SUM(usage_count), 0) AS hits "
                    "FROM oe_translation_cache"
                )
                row = cur.fetchone()
                return {"rows": int(row["rows"]), "hits": int(row["hits"])}
            finally:
                con.close()

        return await self._run(_do)
