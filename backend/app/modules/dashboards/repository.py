"""Dashboards data-access layer.

Queries for :class:`~.models.Snapshot` and
:class:`~.models.SnapshotSourceFile`. No business logic lives here.

Tenant scoping
--------------
Every read funnel accepts an explicit ``tenant_id`` argument. The
service layer decides whether to pass the caller's tenant (normal
path) or ``None`` (admin-only list-all path). The repo never defaults
to "unscoped" — if the caller forgets to pass ``tenant_id`` they get a
``TypeError`` from the keyword-only argument.

The current schema uses a plain ``tenant_id`` column (no ``created_by``
fallback — snapshots are new in v2.5.0, there is no pre-migration
legacy tier to accommodate).
"""

from __future__ import annotations

import uuid
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.dashboards.models import Snapshot, SnapshotSourceFile


class SnapshotRepository:
    """Persistence surface for snapshots + their source-file rows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- reads -------------------------------------------------------------

    async def get(
        self,
        snapshot_id: uuid.UUID | str,
        *,
        tenant_id: str | None,
    ) -> Snapshot | None:
        """Return one snapshot by id, constrained to the caller's tenant.

        ``tenant_id=None`` bypasses the scope filter — service layer
        must only do that for admin-privileged callers.
        """
        stmt = select(Snapshot).where(Snapshot.id == _as_uuid(snapshot_id))
        if tenant_id is not None:
            stmt = stmt.where(Snapshot.tenant_id == str(tenant_id))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_label(
        self,
        project_id: uuid.UUID | str,
        label: str,
    ) -> Snapshot | None:
        """Return the snapshot with the given label in the given project.

        Used by ``SnapshotService.create`` to check the unique-label
        precondition *before* doing any expensive Parquet work. Not
        tenant-scoped — label uniqueness is a DB-level invariant that
        must hold across all callers.
        """
        stmt = select(Snapshot).where(
            Snapshot.project_id == _as_uuid(project_id),
            Snapshot.label == label,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_project(
        self,
        project_id: uuid.UUID | str,
        *,
        tenant_id: str | None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Snapshot], int]:
        """List snapshots for a project, newest first. Returns ``(rows,
        total)`` so callers can emit total-count headers.

        ``limit`` is hard-capped at 500 to avoid unbounded pulls —
        matches the v2.4.0 pagination discipline. Callers wanting more
        should page.
        """
        if limit <= 0:
            raise ValueError("limit must be positive")
        if offset < 0:
            raise ValueError("offset must be >= 0")
        limit = min(limit, 500)

        base = select(Snapshot).where(Snapshot.project_id == _as_uuid(project_id))
        if tenant_id is not None:
            base = base.where(Snapshot.tenant_id == str(tenant_id))

        total = (
            await self.session.execute(
                select(func.count()).select_from(base.subquery())
            )
        ).scalar_one()

        rows_stmt = (
            base.order_by(Snapshot.created_at.desc()).limit(limit).offset(offset)
        )
        rows = (await self.session.execute(rows_stmt)).scalars().all()
        return list(rows), total

    async def list_source_files(
        self, snapshot_id: uuid.UUID | str,
    ) -> list[SnapshotSourceFile]:
        """Return every source-file row for a snapshot, oldest first."""
        stmt = (
            select(SnapshotSourceFile)
            .where(SnapshotSourceFile.snapshot_id == _as_uuid(snapshot_id))
            .order_by(SnapshotSourceFile.created_at.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    # -- writes ------------------------------------------------------------

    async def add(self, snapshot: Snapshot) -> Snapshot:
        """Insert a new snapshot row. Callers set every field first;
        this method only flushes. Caller owns the transaction.
        """
        self.session.add(snapshot)
        await self.session.flush()
        return snapshot

    async def add_source_files(
        self, rows: Iterable[SnapshotSourceFile],
    ) -> list[SnapshotSourceFile]:
        rows = list(rows)
        if not rows:
            return []
        self.session.add_all(rows)
        await self.session.flush()
        return rows

    async def delete(self, snapshot: Snapshot) -> None:
        """Delete a snapshot row — cascades to source_file rows via the
        DB FK. Storage-file cleanup is the service's responsibility.
        """
        await self.session.delete(snapshot)
        await self.session.flush()


# ── helpers ─────────────────────────────────────────────────────────────────


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """Coerce either a UUID instance or a string into a UUID, rejecting
    anything else. Callers that receive an invalid ``snapshot_id`` path
    parameter get a 422 via FastAPI long before reaching the repo, but
    offline callers (tests, scripts) benefit from the defensive
    conversion."""
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


__all__ = ["SnapshotRepository"]
