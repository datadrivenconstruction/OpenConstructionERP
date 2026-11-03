# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Reading feeds: access scope, filters, stable paging and the statement timeout."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import accessible_project_ids, verify_project_access
from app.modules.bi_feed.feeds import (
    MAX_UNPAGED_ROWS,
    SQL_ROLE,
    SQL_SCHEMA,
    ResolvedFeed,
    build_catalogue,
)
from app.modules.bi_feed.formats import ENCODERS
from app.modules.bi_feed.schemas import FeedColumnInfo, FeedInfo, SqlAccessStatus
from app.modules.bi_feed.validators import BiFeedError, FeedParams

logger = logging.getLogger(__name__)

STATEMENT_TIMEOUT_MS = 15_000
CHUNK_ROWS = 5_000


@dataclass(frozen=True)
class FeedExport:
    """An encoded page of a feed with its paging cursors."""

    body: bytes
    media_type: str
    total: int
    rows: int
    next_offset: int | None = None
    next_after: str | None = None


class BiFeedService:
    """Reads feeds for one caller."""

    def __init__(self, session: AsyncSession, catalogue: dict[str, ResolvedFeed] | None = None) -> None:
        self.session = session
        self.catalogue = build_catalogue() if catalogue is None else catalogue

    def feed(self, feed_id: str) -> ResolvedFeed:
        """The feed, or a 404 ``BI_FEED_UNKNOWN``."""
        found = self.catalogue.get(feed_id)
        if found is None:
            raise BiFeedError(404, "BI_FEED_UNKNOWN", f"Unknown feed: {feed_id}")
        return found

    async def _arm_timeout(self) -> None:
        if self.session.get_bind().dialect.name == "postgresql":
            from sqlalchemy import text

            await self.session.execute(text(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}"))

    async def _run(self, stmt: Any) -> Any:
        try:
            return await self.session.execute(stmt)
        except DBAPIError as exc:
            message = str(exc.orig).lower()
            if "statement timeout" in message or "querycanceled" in type(exc.orig).__name__.lower():
                raise BiFeedError(
                    504, "BI_FEED_TIMEOUT", "The feed took too long; narrow it with project_id or page it"
                ) from exc
            raise

    async def _scope(self, feed: ResolvedFeed, user_id: str, params: FeedParams) -> list[Any]:
        """Filter conditions that keep the query inside what ``user_id`` may read.

        The same rule as every project list: owner, team member or admin. A project the
        caller cannot read is silently left out; naming one explicitly is a 404.
        """
        if params.project_id is not None:
            await verify_project_access(params.project_id, user_id, self.session)
            conditions = [feed.project_expr == params.project_id]
        else:
            allowed = await accessible_project_ids(self.session, user_id, live_only=True)
            conditions = [] if allowed is None else [feed.project_expr.in_(allowed)]
        if params.updated_since is not None:
            conditions.append(feed.updated_expr >= params.updated_since)
        return conditions

    async def _count(self, feed: ResolvedFeed, conditions: list[Any]) -> int:
        return int((await self._run(feed.query(func.count()).where(*conditions))).scalar_one())

    @staticmethod
    def _may_read(feed: ResolvedFeed, role: str) -> bool:
        """True when the role holds the read permission of the module the feed comes from."""
        from app.core.permissions import permission_registry

        return permission_registry.role_has_permission(role, feed.spec.permission)

    async def list_feeds(self, user_id: str, role: str) -> list[FeedInfo]:
        """Every feed the caller's role may read, with the caller's visible row count."""
        await self._arm_timeout()
        infos = []
        for feed in self.catalogue.values():
            if not self._may_read(feed, role):
                continue
            conditions = await self._scope(feed, user_id, FeedParams())
            infos.append(
                FeedInfo(
                    id=feed.id,
                    title_key=feed.spec.title_key,
                    columns=[FeedColumnInfo(name=c.name, kind=c.kind) for c in feed.columns],
                    row_count=await self._count(feed, conditions),
                )
            )
        return infos

    async def export(self, feed_id: str, fmt: str, user_id: str, role: str, params: FeedParams) -> FeedExport:
        """One page (``limit`` given) or the rest of the feed, encoded as ``fmt``.

        Rows come in primary-key order. Offset paging is exact while nothing is inserted
        between requests; ``after`` (the last key seen) keeps pages free of repeats and
        gaps even then.
        """
        feed = self.feed(feed_id)
        if not self._may_read(feed, role):
            raise BiFeedError(403, "BI_FEED_FORBIDDEN", f"Your role cannot read the {feed_id} feed")
        await self._arm_timeout()
        conditions = await self._scope(feed, user_id, params)
        total = await self._count(feed, conditions)
        remaining = max(total - params.offset, 0)
        if params.limit is None and remaining > MAX_UNPAGED_ROWS:
            raise BiFeedError(
                400, "BI_FEED_TOO_LARGE", f"{total} rows is too many for one download; page it with limit and offset"
            )
        wanted = params.limit if params.limit is not None else remaining
        columns = [(c.name, c.kind) for c in feed.columns]
        encoder = ENCODERS[fmt](columns, total=total) if fmt == "json" else ENCODERS[fmt](columns)
        pk_index = [c.name for c in feed.columns].index("id")
        fetched, last_pk, offset = 0, params.after, params.offset
        while fetched < wanted:
            stmt = feed.select().where(*conditions)
            if last_pk is not None:
                stmt = stmt.where(feed.pk > last_pk)
            stmt = stmt.order_by(feed.pk).limit(min(CHUNK_ROWS, wanted - fetched))
            if offset:
                stmt = stmt.offset(offset)
                offset = 0
            rows = [tuple(r) for r in (await self._run(stmt)).all()]
            if not rows:
                break
            encoder.add(rows)
            fetched += len(rows)
            last_pk = rows[-1][pk_index]
        more = (
            params.limit is not None
            and fetched == params.limit
            and (params.after is not None or params.offset + fetched < total)
        )
        return FeedExport(
            body=encoder.finish(),
            media_type=encoder.media_type,
            total=total,
            rows=fetched,
            next_offset=params.offset + fetched if more else None,
            next_after=str(last_pk) if more and isinstance(last_pk, uuid.UUID) else None,
        )

    async def sql_status(self) -> SqlAccessStatus:
        """Whether ``bi enable`` has been run; false on anything but PostgreSQL."""
        from app.modules.bi_feed import sqlview

        info = await (await self.session.connection()).run_sync(sqlview.status)
        return SqlAccessStatus(enabled=info["enabled"], schema_name=SQL_SCHEMA, role=SQL_ROLE, views=info["views"])
