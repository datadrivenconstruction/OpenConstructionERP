# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Translation-memory cache backed by the main PostgreSQL database.

Past translations are persisted in the ``oe_translation_cache`` table of
the main application database (embedded PostgreSQL 16 by default, or an
external PostgreSQL via ``DATABASE_URL``). Keeping the cache in the main
DB means it is backed up, migrated, and connection-pooled together with
the rest of the application state - no separate file to manage.

The table is defined here on ``Base.metadata`` so application startup
(``Base.metadata.create_all``) provisions it, and a lazy idempotent
``create(checkfirst=True)`` covers code paths (e.g. unit tests) that
instantiate :class:`TranslationCache` without a full app boot. The
column layout matches the Alembic migration
``alembic/versions/v280_translation_cache.py`` so an external PostgreSQL
that already has the table stays compatible (``create_all`` uses
``checkfirst`` and never duplicates).

In-process LRU
==============
Even with the DB-backed cache, every translate() under concurrent match
load issues a SELECT round-trip - for 50 walls of identical material in
one batch that's 50 SELECTs on identical keys. We layer an in-process
LRU cache on top so a single SELECT round-trip is amortised across the
whole batch. The LRU is invalidated on every ``upsert()`` so a new
translation written by one request is visible to the next one.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import threading
from collections import OrderedDict
from typing import Any

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    case,
    func,
    select,
    text,
    update,
)

from app.database import Base

# ── Table definition on the main metadata ───────────────────────────────
#
# Registered on ``Base.metadata`` so startup ``create_all`` provisions it
# on embedded PostgreSQL, and so the lazy ``create(checkfirst=True)`` below
# can target the same object. Column layout mirrors the Alembic migration
# ``v280_translation_cache`` so external PG that already has the table is
# left untouched (``checkfirst`` makes both code paths no-ops on conflict).
_TABLE = Table(
    "oe_translation_cache",
    Base.metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("text_hash", String(40), nullable=False),
    Column("source_lang", String(8), nullable=False),
    Column("target_lang", String(8), nullable=False),
    Column("domain", String(64), nullable=False, server_default="construction"),
    Column("translated_text", Text, nullable=False),
    Column("tier_used", String(32), nullable=False),
    Column("confidence", Float, nullable=False, server_default=text("1.0")),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("usage_count", Integer, nullable=False, server_default=text("1")),
    Column("last_used_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "text_hash",
        "source_lang",
        "target_lang",
        "domain",
        name="uq_oe_translation_cache_key",
    ),
    Index("ix_oe_translation_cache_langs", "source_lang", "target_lang"),
    extend_existing=True,
)


# ── In-process LRU on top of the DB cache ───────────────────────────────
#
# Bounded by ``_LRU_MAXSIZE`` (~1k entries - a few MB at most for typical
# construction-domain phrases). Each entry is the dict shape returned by
# :meth:`TranslationCache.get` so the cache layer above can pretend it
# came straight from the DB. A ``None`` sentinel marks "looked up but
# missed" so we don't re-query the DB for a known cold key.
#
# Key shape ``(namespace, text_hash, src, tgt, domain)`` - the cache now
# lives in the single shared main database, so the namespace slot is a
# constant ``"pg"`` rather than a per-file path. The 5-tuple shape is
# preserved so the LRU helpers below are unchanged.
_LRU_NAMESPACE = "pg"
_LRU_MAXSIZE = 1024
_LRUKey = tuple[str, str, str, str, str]
_lru: OrderedDict[_LRUKey, dict[str, Any] | None] = OrderedDict()
# Reverse index ``row_id → key`` so ``mark_used`` (which only knows the
# row id) can invalidate the matching LRU entry. Without this, a hit
# that bumps ``usage_count`` in the DB would still serve the stale
# ``usage_count`` from the LRU on the next ``get()``.
_lru_by_row_id: dict[int, _LRUKey] = {}
_lru_lock = threading.Lock()


def _lru_get(key: _LRUKey) -> tuple[bool, dict[str, Any] | None]:
    """Return ``(hit, value)`` - caller distinguishes "miss" from "known None"."""
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
    ``get()`` from any other coroutine - without this, a freshly cached
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
    tuple - without this hook, a usage_count bump would persist to the
    DB but stay invisible to subsequent ``get()`` calls served by the
    LRU.
    """
    with _lru_lock:
        key = _lru_by_row_id.pop(row_id, None)
        if key is not None:
            _lru.pop(key, None)


def lru_stats() -> dict[str, int]:
    """Stats for tests / observability."""
    with _lru_lock:
        return {"entries": len(_lru), "maxsize": _LRU_MAXSIZE}


def _hash(text_value: str) -> str:
    # SHA1 is fine here - it's a cache key, not a security primitive.
    # ``usedforsecurity=False`` silences Bandit B324 / FIPS-mode warnings.
    return hashlib.sha1(text_value.encode("utf-8"), usedforsecurity=False).hexdigest()


# Module-level guard so the lazy table-ensure runs at most once per process.
_table_ready = False
_table_ready_lock = threading.Lock()


async def _ensure_table() -> None:
    """Idempotently create the cache table on the main engine.

    Application startup already provisions the table via
    ``Base.metadata.create_all``; this lazy helper covers code paths (most
    notably unit tests) that construct :class:`TranslationCache` without a
    full app boot. ``create(checkfirst=True)`` is a no-op when the table
    already exists, so it is safe to call from every public method.
    """
    global _table_ready
    if _table_ready:
        return
    from app.database import engine

    async with engine.begin() as conn:
        await conn.run_sync(_TABLE.create, checkfirst=True)
    with _table_ready_lock:
        _table_ready = True


class TranslationCache:
    """Async translation-memory cache over the main PostgreSQL database.

    Reads and writes go through the shared async engine
    (``app.database.engine``) using SQLAlchemy Core, so the cache shares
    the application connection pool and is backed up with the rest of the
    schema. An in-process LRU (see module level) absorbs repeated lookups
    of identical envelopes so a batch of N identical phrases costs one
    SELECT, not N.
    """

    def __init__(self) -> None:
        # No per-instance state: the table lives in the shared main DB and
        # the LRU is module-global. The table is ensured lazily on first use.
        pass

    # ── public API ──────────────────────────────────────────────────

    async def get(
        self,
        text: str,  # noqa: A002 - public signature kept stable for callers
        source_lang: str,
        target_lang: str,
        domain: str,
    ) -> dict[str, Any] | None:
        """Return cached row as a dict, or ``None`` if no hit.

        Backed by an in-process LRU keyed on ``(namespace, text_hash, src,
        tgt, domain)`` so 50 concurrent match requests with identical
        envelopes do one DB SELECT, not 50.
        """
        await _ensure_table()
        h = _hash(text)
        key = (_LRU_NAMESPACE, h, source_lang, target_lang, domain)

        hit, cached = _lru_get(key)
        if hit:
            return cached

        from app.database import engine

        stmt = (
            select(
                _TABLE.c.id,
                _TABLE.c.translated_text,
                _TABLE.c.tier_used,
                _TABLE.c.confidence,
                _TABLE.c.usage_count,
                _TABLE.c.created_at,
                _TABLE.c.last_used_at,
            )
            .where(
                _TABLE.c.text_hash == h,
                _TABLE.c.source_lang == source_lang,
                _TABLE.c.target_lang == target_lang,
                _TABLE.c.domain == domain,
            )
            .limit(1)
        )
        async with engine.connect() as conn:
            row = (await conn.execute(stmt)).mappings().first()

        result: dict[str, Any] | None
        if row is None:
            result = None
        else:
            # Cast timestamps to str so the return shape stays
            # string-friendly for callers that compare/serialise them.
            result = {
                "id": int(row["id"]),
                "translated_text": row["translated_text"],
                "tier_used": row["tier_used"],
                "confidence": float(row["confidence"]),
                "usage_count": int(row["usage_count"]),
                "created_at": str(row["created_at"]),
                "last_used_at": str(row["last_used_at"]),
            }
        _lru_put(key, result)
        return result

    async def upsert(
        self,
        *,
        text: str,  # noqa: A002 - public signature kept stable for callers
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
        await _ensure_table()
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from app.database import engine

        h = _hash(text)
        now = dt.datetime.now(dt.UTC)
        key = (_LRU_NAMESPACE, h, source_lang, target_lang, domain)

        ins = pg_insert(_TABLE).values(
            text_hash=h,
            source_lang=source_lang,
            target_lang=target_lang,
            domain=domain,
            translated_text=translated_text,
            tier_used=tier_used,
            confidence=confidence,
            created_at=now,
            usage_count=1,
            last_used_at=now,
        )
        stmt = ins.on_conflict_do_update(
            index_elements=[
                _TABLE.c.text_hash,
                _TABLE.c.source_lang,
                _TABLE.c.target_lang,
                _TABLE.c.domain,
            ],
            set_={
                "translated_text": case(
                    (ins.excluded.confidence > _TABLE.c.confidence, ins.excluded.translated_text),
                    else_=_TABLE.c.translated_text,
                ),
                "tier_used": case(
                    (ins.excluded.confidence > _TABLE.c.confidence, ins.excluded.tier_used),
                    else_=_TABLE.c.tier_used,
                ),
                "confidence": func.greatest(_TABLE.c.confidence, ins.excluded.confidence),
                "usage_count": _TABLE.c.usage_count + 1,
                "last_used_at": ins.excluded.last_used_at,
            },
        )

        async with engine.begin() as conn:
            await conn.execute(stmt)

        # Invalidate the LRU entry so the next ``get()`` reads the freshly
        # written row instead of a stale "None" sentinel from a previous miss.
        _lru_invalidate(key)

    async def mark_used(self, row_id: int) -> None:
        """Bump ``usage_count`` and refresh ``last_used_at`` on a hit."""
        await _ensure_table()
        from app.database import engine

        now = dt.datetime.now(dt.UTC)
        stmt = (
            update(_TABLE).where(_TABLE.c.id == row_id).values(usage_count=_TABLE.c.usage_count + 1, last_used_at=now)
        )
        async with engine.begin() as conn:
            await conn.execute(stmt)

        # Drop the LRU entry so the next ``get()`` reads the freshly bumped
        # ``usage_count``/``last_used_at`` from the DB instead of the row
        # that was cached at insert time.
        _lru_invalidate_by_row_id(int(row_id))

    async def stats(self) -> dict[str, Any]:
        """Return basic counts for the status endpoint."""
        await _ensure_table()
        from app.database import engine

        stmt = select(
            func.count().label("rows"),
            func.coalesce(func.sum(_TABLE.c.usage_count), 0).label("hits"),
        )
        async with engine.connect() as conn:
            row = (await conn.execute(stmt)).mappings().first()

        if row is None:
            return {"rows": 0, "hits": 0}
        return {"rows": int(row["rows"]), "hits": int(row["hits"])}
