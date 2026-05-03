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
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import logging
import sqlite3
from typing import Any

from app.core.translation.paths import cache_db_path

logger = logging.getLogger(__name__)


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
        """Return cached row as a dict, or ``None`` if no hit."""
        h = _hash(text)

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

        return await self._run(_do)

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
