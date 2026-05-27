# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File tags service — CRUD + bulk assign/unassign + AECO defaults.

Stateless. Methods take an :class:`AsyncSession` explicitly so the
router can compose them inside a transaction (or a test can drive them
without the FastAPI DI stack).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.file_tags.models import FileTag, FileTagAssignment
from app.modules.file_tags.schemas import (
    TagAssignmentResponse,
    TagCreate,
    TagResponse,
    TagSeedResponse,
    TagUpdate,
    slugify,
)

logger = logging.getLogger(__name__)


# AECO seed sets. Categories follow the schema in schemas.py.
_DEFAULT_TAGS: list[tuple[str, str, str]] = [
    # (display_name, category, color)
    ("Architecture", "discipline", "#3b82f6"),
    ("Structural", "discipline", "#ef4444"),
    ("MEP", "discipline", "#f59e0b"),
    ("Civil", "discipline", "#10b981"),
    ("Design", "phase", "#6366f1"),
    ("Procurement", "phase", "#8b5cf6"),
    ("Construction", "phase", "#f97316"),
    ("Closeout", "phase", "#64748b"),
]


async def _to_response(session: AsyncSession, tag: FileTag) -> TagResponse:
    """Build a TagResponse including the assignment count."""
    count_stmt = select(func.count(FileTagAssignment.id)).where(FileTagAssignment.tag_id == tag.id)
    count = int((await session.execute(count_stmt)).scalar_one_or_none() or 0)
    return TagResponse(
        id=tag.id,
        project_id=tag.project_id,
        name=tag.name,
        display_name=tag.display_name,
        color=tag.color,
        category=tag.category,
        created_at=tag.created_at,
        updated_at=tag.updated_at,
        created_by_id=tag.created_by_id,
        assignment_count=count,
    )


# ── CRUD ────────────────────────────────────────────────────────────


async def list_tags(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    category: str | None = None,
) -> list[TagResponse]:
    """List every tag in a project, optionally filtered by category.

    Sorted by category then display_name so the picker renders in a
    deterministic order regardless of insertion sequence.
    """
    stmt = select(FileTag).where(FileTag.project_id == project_id)
    if category is not None:
        stmt = stmt.where(FileTag.category == category)
    stmt = stmt.order_by(FileTag.category.nullslast(), FileTag.display_name)
    result = await session.execute(stmt)
    tags = list(result.scalars().all())
    return [await _to_response(session, t) for t in tags]


async def get_tag(
    session: AsyncSession,
    project_id: uuid.UUID,
    tag_id: uuid.UUID,
) -> FileTag | None:
    """Fetch a tag, scoping by project so cross-project IDOR is impossible."""
    stmt = select(FileTag).where(
        FileTag.id == tag_id,
        FileTag.project_id == project_id,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def create_tag(
    session: AsyncSession,
    payload: TagCreate,
    user_id: uuid.UUID | None,
) -> TagResponse:
    """Create a new tag in the project.

    Raises ``ValueError`` if a tag with the same slug already exists in
    the project. The router maps that to a 409.
    """
    name = payload.name or slugify(payload.display_name)
    name = slugify(name)
    existing_stmt = select(FileTag).where(
        FileTag.project_id == payload.project_id,
        FileTag.name == name,
    )
    if (await session.execute(existing_stmt)).scalar_one_or_none() is not None:
        raise ValueError(f"Tag '{name}' already exists in this project")

    tag = FileTag(
        project_id=payload.project_id,
        name=name,
        display_name=payload.display_name,
        color=payload.color,
        category=payload.category,
        created_by_id=user_id,
    )
    session.add(tag)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise ValueError(f"Tag '{name}' already exists in this project") from exc
    return await _to_response(session, tag)


async def update_tag(
    session: AsyncSession,
    project_id: uuid.UUID,
    tag_id: uuid.UUID,
    payload: TagUpdate,
) -> TagResponse | None:
    """Rename / recolor / recategorize a tag.

    Returns ``None`` when the tag is missing or belongs to a different
    project (router emits 404).
    """
    tag = await get_tag(session, project_id, tag_id)
    if tag is None:
        return None
    if payload.display_name is not None:
        tag.display_name = payload.display_name
    if payload.color is not None:
        tag.color = payload.color
    if payload.category is not None:
        tag.category = payload.category
    await session.flush()
    # Refresh so the server-side ``onupdate=func.now()`` value lands in
    # the ORM object — without this, accessing ``tag.updated_at`` lazy-
    # loads a SELECT outside the active greenlet and raises
    # MissingGreenlet under asyncio.
    await session.refresh(tag)
    return await _to_response(session, tag)


async def delete_tag(
    session: AsyncSession,
    project_id: uuid.UUID,
    tag_id: uuid.UUID,
) -> bool:
    """Delete a tag (cascades to every assignment).

    Returns ``True`` if a row was deleted, ``False`` if it was missing.
    """
    tag = await get_tag(session, project_id, tag_id)
    if tag is None:
        return False
    await session.delete(tag)
    await session.flush()
    return True


# ── Assignment ─────────────────────────────────────────────────────


async def assign_tag(
    session: AsyncSession,
    project_id: uuid.UUID,
    tag_id: uuid.UUID,
    file_kind: str,
    file_ids: list[str],
    user_id: uuid.UUID | None,
) -> TagAssignmentResponse:
    """Bulk-attach a tag to multiple files.

    Idempotent: re-running with the same ids is a no-op (the rows are
    counted in ``already_done`` instead of ``changed``).
    """
    tag = await get_tag(session, project_id, tag_id)
    if tag is None:
        raise ValueError(f"Tag {tag_id} not found in project {project_id}")

    if not file_ids:
        return TagAssignmentResponse(
            tag_id=tag_id,
            file_kind=file_kind,
            requested=0,
            changed=0,
            already_done=0,
        )

    # Load existing assignments for this (tag, kind) to dedupe.
    existing_stmt = select(FileTagAssignment.file_id).where(
        FileTagAssignment.tag_id == tag_id,
        FileTagAssignment.file_kind == file_kind,
        FileTagAssignment.file_id.in_(file_ids),
    )
    existing_ids: set[str] = {row for row in (await session.execute(existing_stmt)).scalars().all()}
    to_create = [fid for fid in file_ids if fid not in existing_ids]
    now = datetime.now(UTC)
    for fid in to_create:
        session.add(
            FileTagAssignment(
                tag_id=tag_id,
                file_kind=file_kind,
                file_id=fid,
                assigned_at=now,
                assigned_by_id=user_id,
            )
        )
    try:
        await session.flush()
    except IntegrityError:
        # Race window with a parallel writer — recount what's there and
        # treat duplicates as "already done" rather than 500ing.
        await session.rollback()
        existing_ids = {row for row in (await session.execute(existing_stmt)).scalars().all()}
        to_create = [fid for fid in file_ids if fid not in existing_ids]
    return TagAssignmentResponse(
        tag_id=tag_id,
        file_kind=file_kind,
        requested=len(file_ids),
        changed=len(to_create),
        already_done=len(file_ids) - len(to_create),
    )


async def unassign_tag(
    session: AsyncSession,
    project_id: uuid.UUID,
    tag_id: uuid.UUID,
    file_kind: str,
    file_ids: list[str],
) -> TagAssignmentResponse:
    """Bulk-detach a tag from multiple files.

    Idempotent: ids that weren't assigned land in ``already_done``.
    """
    tag = await get_tag(session, project_id, tag_id)
    if tag is None:
        raise ValueError(f"Tag {tag_id} not found in project {project_id}")
    if not file_ids:
        return TagAssignmentResponse(
            tag_id=tag_id,
            file_kind=file_kind,
            requested=0,
            changed=0,
            already_done=0,
        )

    stmt = delete(FileTagAssignment).where(
        FileTagAssignment.tag_id == tag_id,
        FileTagAssignment.file_kind == file_kind,
        FileTagAssignment.file_id.in_(file_ids),
    )
    result = await session.execute(stmt)
    await session.flush()
    changed = int(result.rowcount or 0)
    return TagAssignmentResponse(
        tag_id=tag_id,
        file_kind=file_kind,
        requested=len(file_ids),
        changed=changed,
        already_done=len(file_ids) - changed,
    )


async def tags_for_file(
    session: AsyncSession,
    project_id: uuid.UUID,
    file_kind: str,
    file_id: str,
) -> list[TagResponse]:
    """Return every tag attached to a single ``(kind, file_id)`` pair."""
    stmt = (
        select(FileTag)
        .join(FileTagAssignment, FileTagAssignment.tag_id == FileTag.id)
        .where(
            FileTag.project_id == project_id,
            FileTagAssignment.file_kind == file_kind,
            FileTagAssignment.file_id == file_id,
        )
        .order_by(FileTag.category.nullslast(), FileTag.display_name)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [await _to_response(session, t) for t in rows]


async def tags_by_files(
    session: AsyncSession,
    project_id: uuid.UUID,
    file_kind: str,
    file_ids: list[str],
) -> dict[str, list[TagResponse]]:
    """Map ``{file_id: [tag, ...]}`` for a bulk-render in the grid.

    Avoids the N+1 the file list would otherwise issue (one
    ``tags_for_file`` per row).
    """
    if not file_ids:
        return {}
    stmt = (
        select(FileTag, FileTagAssignment.file_id)
        .join(FileTagAssignment, FileTagAssignment.tag_id == FileTag.id)
        .where(
            FileTag.project_id == project_id,
            FileTagAssignment.file_kind == file_kind,
            FileTagAssignment.file_id.in_(file_ids),
        )
    )
    rows = (await session.execute(stmt)).all()
    out: dict[str, list[TagResponse]] = {fid: [] for fid in file_ids}
    for tag, file_id in rows:
        resp = await _to_response(session, tag)
        out.setdefault(file_id, []).append(resp)
    return out


# ── Defaults ─────────────────────────────────────────────────────


async def seed_default_tags(
    session: AsyncSession,
    project_id: uuid.UUID,
    user_id: uuid.UUID | None,
) -> TagSeedResponse:
    """Idempotently seed the AECO standard tags into a project.

    Calling twice yields the same set — every tag is checked by slug
    before insertion, so duplicates land in ``existing``.
    """
    created = 0
    existing = 0
    seeded: list[FileTag] = []

    for display_name, category, color in _DEFAULT_TAGS:
        name = slugify(display_name)
        find_stmt = select(FileTag).where(
            FileTag.project_id == project_id,
            FileTag.name == name,
        )
        found = (await session.execute(find_stmt)).scalar_one_or_none()
        if found is not None:
            seeded.append(found)
            existing += 1
            continue
        tag = FileTag(
            project_id=project_id,
            name=name,
            display_name=display_name,
            color=color,
            category=category,
            created_by_id=user_id,
        )
        session.add(tag)
        seeded.append(tag)
        created += 1

    try:
        await session.flush()
    except IntegrityError:
        # Race window with another parallel seeder — silently re-load.
        logger.exception("Race window during seed_default_tags; recovering")
        await session.rollback()
        # On rollback, the in-memory ``seeded`` objects are detached;
        # re-query to return canonical state.
        seeded = []
        for display_name, _category, _color in _DEFAULT_TAGS:
            name = slugify(display_name)
            stmt = select(FileTag).where(
                FileTag.project_id == project_id,
                FileTag.name == name,
            )
            found = (await session.execute(stmt)).scalar_one_or_none()
            if found is not None:
                seeded.append(found)

    return TagSeedResponse(
        project_id=project_id,
        created=created,
        existing=existing,
        total=len(seeded),
        tags=[await _to_response(session, t) for t in seeded],
    )


async def remove_assignments_for_file(
    session: AsyncSession,
    file_kind: str,
    file_id: str,
) -> int:
    """Detach every tag from a single file across all projects.

    Called by the file-manager dispatcher on bulk-delete so deleting a
    file doesn't leave orphan rows in ``oe_file_tag_assignment``.
    Returns the number of rows deleted.
    """
    stmt = delete(FileTagAssignment).where(
        FileTagAssignment.file_kind == file_kind,
        FileTagAssignment.file_id == file_id,
    )
    result = await session.execute(stmt)
    await session.flush()
    return int(result.rowcount or 0)
