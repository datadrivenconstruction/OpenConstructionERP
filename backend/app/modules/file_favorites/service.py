# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠File Favourites service - toggle / pin / list.

Stateless helpers around :class:`FileFavorite`. Polymorphic on
``(file_kind, file_id)``; ownership is implicit via ``user_id``.

The toggle endpoint is idempotent: posting the same
``(user_id, file_kind, file_id)`` twice flips the ``pinned`` flag
only when the caller explicitly asks for it; otherwise it returns
the existing row unchanged. That keeps the one-click star UX safe.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import and_, delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.file_favorites.models import FAVORITE_KINDS, FileFavorite

logger = logging.getLogger(__name__)


def _validate_kind(kind: str) -> None:
    if kind not in FAVORITE_KINDS:
        raise ValueError(f"Unknown favourite kind: {kind!r}")


async def list_favorites(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID | None = None,
    only_pinned: bool = False,
) -> list[FileFavorite]:
    """Return the user's favourites; pinned-first then newest-first."""
    stmt = select(FileFavorite).where(FileFavorite.user_id == user_id)
    if project_id is not None:
        stmt = stmt.where(FileFavorite.project_id == project_id)
    if only_pinned:
        stmt = stmt.where(FileFavorite.pinned.is_(True))
    stmt = stmt.order_by(
        FileFavorite.pinned.desc(),
        FileFavorite.updated_at.desc(),
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_favorite(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    file_kind: str,
    file_id: str,
) -> FileFavorite | None:
    stmt = select(FileFavorite).where(
        and_(
            FileFavorite.user_id == user_id,
            FileFavorite.project_id == project_id,
            FileFavorite.file_kind == file_kind,
            FileFavorite.file_id == file_id,
        )
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def toggle_favorite(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    file_kind: str,
    file_id: str,
    pinned: bool = False,
) -> tuple[FileFavorite, bool]:
    """Star (or update pin) for the current user.

    Returns ``(row, created)`` so the router can pick 201 vs 200.
    Idempotent on the unique key ``(user, kind, file)``; a second call
    only updates the ``pinned`` flag if the caller passes a different
    value than what's stored.
    """
    _validate_kind(file_kind)
    existing = await get_favorite(
        session,
        user_id=user_id,
        project_id=project_id,
        file_kind=file_kind,
        file_id=file_id,
    )
    if existing is not None:
        if existing.pinned != pinned:
            existing.pinned = pinned
            await session.flush()
        return existing, False

    row = FileFavorite(
        user_id=user_id,
        project_id=project_id,
        file_kind=file_kind,
        file_id=file_id,
        pinned=pinned,
    )
    session.add(row)
    try:
        await session.flush()
    except IntegrityError:
        # Concurrent insert - fall back to the existing row.
        await session.rollback()
        existing = await get_favorite(
            session,
            user_id=user_id,
            project_id=project_id,
            file_kind=file_kind,
            file_id=file_id,
        )
        if existing is None:
            raise
        return existing, False
    return row, True


async def unstar(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    file_kind: str,
    file_id: str,
) -> bool:
    """Remove the favourite. Returns ``True`` iff a row was deleted."""
    _validate_kind(file_kind)
    stmt = delete(FileFavorite).where(
        and_(
            FileFavorite.user_id == user_id,
            FileFavorite.project_id == project_id,
            FileFavorite.file_kind == file_kind,
            FileFavorite.file_id == file_id,
        )
    )
    result = await session.execute(stmt)
    return bool(result.rowcount or 0)


__all__ = [
    "get_favorite",
    "list_favorites",
    "toggle_favorite",
    "unstar",
]
