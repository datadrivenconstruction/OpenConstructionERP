# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
# AGPL-3.0 License
"""Which projects are demo projects, and which demos the user removed.

Every seeder that writes demo records asks one of the two questions here and
nothing else. A demo project is one whose ``metadata_`` carries a ``demo_id``,
the tag every installer writes (the showcase and partner-pack installers and
the flagship seeder alike). It is never recognised by name, by owner or by
position in the table: a user can rename a project, the demo account can own
real work, and "the first projects" is whatever the database returns first.

A demo project the user deleted is archived rather than removed, and it is not
a demo project for seeding purposes any more. Filling it would be invisible,
since nobody opens an archived project, but it is still writing into a record
the user asked to be rid of.

The retired-demo record (:class:`DemoProjectTombstone`) is what keeps a removed
demo from being installed again. Boot installers consult it; an explicit
install by a person clears it.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def demo_id_of(metadata: Any) -> str:
    """The project's ``demo_id`` marker, or an empty string for a real project."""
    if not isinstance(metadata, dict):
        return ""
    return str(metadata.get("demo_id") or "").strip()


async def live_demo_projects(
    session: AsyncSession,
    candidate_ids: Iterable[uuid.UUID] | None = None,
) -> list[tuple[uuid.UUID, str]]:
    """``(project_id, demo_id)`` of every demo project that is not deleted.

    Ordered by creation, so a caller that takes the first one gets the same
    project on every boot. Read in Python rather than filtered in SQL:
    ``metadata_`` is a portable JSON column, and a containment test on it
    compiles to a string comparison rather than to JSON containment.

    Args:
        session: Session to read through.
        candidate_ids: Restrict the answer to these projects. ``None`` means
            every project in the database.
    """
    from app.modules.projects.models import Project

    stmt = select(Project.id, Project.metadata_).where(Project.status != "archived")
    if candidate_ids is not None:
        ids = list(candidate_ids)
        if not ids:
            return []
        stmt = stmt.where(Project.id.in_(ids))
    rows = (await session.execute(stmt.order_by(Project.created_at, Project.id))).all()
    return [(pid, did) for pid, meta in rows if (did := demo_id_of(meta))]


async def first_live_demo_project_id(session: AsyncSession) -> uuid.UUID | None:
    """The oldest demo project that is not deleted, or None when there is none."""
    found = await live_demo_projects(session)
    return found[0][0] if found else None


async def retired_demo_ids(session: AsyncSession) -> set[str]:
    """Every ``demo_id`` the user removed and has not installed again."""
    from app.modules.projects.models import DemoProjectTombstone

    return set((await session.execute(select(DemoProjectTombstone.demo_id))).scalars().all())


async def retire_demo_ids(
    session: AsyncSession,
    demo_projects: Mapping[str, uuid.UUID | None],
    *,
    reason: str,
) -> int:
    """Record that these demos were removed, so boot does not bring them back.

    Idempotent: a demo already recorded keeps its first record. Flushes but
    does not commit, so the record lands in the same transaction as the delete
    it describes.

    Args:
        session: The session the delete runs in.
        demo_projects: ``demo_id`` to the project row being removed.
        reason: ``"archived"`` for a deleted project, ``"purged"`` for a purge.

    Returns:
        How many new records were written.
    """
    from app.modules.projects.models import DemoProjectTombstone

    wanted = {did.strip(): pid for did, pid in demo_projects.items() if did and did.strip()}
    if not wanted:
        return 0
    # One statement that skips an existing record, rather than a read and then
    # an insert: two removals of the same demo racing (a double-click, two
    # tabs) would otherwise both pass the read and one would fail on the
    # unique demo_id.
    dialect = (await session.connection()).dialect.name
    if dialect in ("postgresql", "sqlite"):
        if dialect == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        await session.flush()
        result = await session.execute(
            insert(DemoProjectTombstone)
            .values(
                [
                    {"id": uuid.uuid4(), "demo_id": did, "removed_project_id": pid, "reason": reason}
                    for did, pid in wanted.items()
                ]
            )
            .on_conflict_do_nothing(index_elements=["demo_id"])
        )
        return max(result.rowcount or 0, 0)

    already = await retired_demo_ids(session)
    added = 0
    for did, pid in wanted.items():
        if did in already:
            continue
        session.add(DemoProjectTombstone(demo_id=did, removed_project_id=pid, reason=reason))
        added += 1
    if added:
        await session.flush()
    return added


async def restore_demo_id(session: AsyncSession, demo_id: str) -> None:
    """Forget that ``demo_id`` was removed; a person asked for it again."""
    from app.modules.projects.models import DemoProjectTombstone

    await session.execute(delete(DemoProjectTombstone).where(DemoProjectTombstone.demo_id == demo_id))
