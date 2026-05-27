# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File Comments business logic.

Stateless service. The router composes these functions inside the
request-scoped session — they don't open transactions themselves so a
caller can string multiple operations together (e.g. create-comment +
extract-mentions) in a single commit.

Mention resolution
------------------
``@username`` tokens in the comment body are extracted via the regex
``@(\\w+)``. The captured handle is matched against (in order):

    1. the local part of ``User.email`` (e.g. ``@alice`` matches
       ``alice@acme.example``);
    2. the full name when squashed to a no-whitespace lowercase token
       (e.g. ``@alicesmith`` matches ``Alice Smith``).

The match is case-insensitive on both sides. Unresolvable handles are
silently dropped — the mention rows only exist for resolved users.

Soft delete
-----------
``DELETE`` replaces ``body`` with ``[deleted]`` and clears the row's
mention children so the inbox doesn't surface tombstoned notifications.
The row itself is preserved to keep the reply thread intact.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.file_comments.models import FileComment, FileCommentMention
from app.modules.file_comments.schemas import (
    FileCommentCreate,
    FileCommentMentionResponse,
    FileCommentResponse,
    FileCommentThread,
    FileCommentUpdate,
    UnreadMentionItem,
)
from app.modules.users.models import User

logger = logging.getLogger(__name__)

# ``@handle`` capture. Word-boundary on the right side so trailing
# punctuation (``@alice,``, ``@bob.``) is not part of the handle. The
# regex deliberately does NOT capture dots / dashes inside the handle
# because the resolver squashes those for full-name match anyway.
_MENTION_RE = re.compile(r"@(\w{2,64})")

# The body excerpt surfaced in the "unread mentions" inbox. Long enough
# to be useful, short enough to fit on a single line of a notification.
_EXCERPT_MAX = 160


# ── helpers ────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(UTC)


def _to_response(comment: FileComment, mentions: list[FileCommentMention]) -> FileCommentResponse:
    """Build a flat response row out of an ORM object."""
    return FileCommentResponse(
        id=comment.id,
        project_id=comment.project_id,
        file_kind=comment.file_kind,
        file_id=comment.file_id,
        file_version_snapshot=comment.file_version_snapshot,
        file_version_id=comment.file_version_id,
        parent_id=comment.parent_id,
        author_id=comment.author_id,
        body=comment.body,
        page_number=comment.page_number,
        anchor_x=comment.anchor_x,
        anchor_y=comment.anchor_y,
        resolved=comment.resolved,
        resolved_at=comment.resolved_at,  # type: ignore[arg-type]
        resolved_by_id=comment.resolved_by_id,
        created_at=comment.created_at,
        updated_at=comment.updated_at,
        mentions=[FileCommentMentionResponse.model_validate(m) for m in mentions],
    )


def _build_threads(
    comments: list[FileComment],
    mentions_by_comment: dict[uuid.UUID, list[FileCommentMention]],
) -> list[FileCommentThread]:
    """Group a flat comment list into nested top-level threads.

    Replies are attached to their immediate parent. Comments whose
    parent_id points to a comment outside the result set (e.g. the
    parent has been hard-pruned) are surfaced as top-level threads so
    they are never invisible.
    """
    nodes: dict[uuid.UUID, FileCommentThread] = {}
    for c in comments:
        ms = mentions_by_comment.get(c.id, [])
        resp = _to_response(c, ms)
        nodes[c.id] = FileCommentThread(**resp.model_dump(), replies=[])

    roots: list[FileCommentThread] = []
    for c in comments:
        node = nodes[c.id]
        parent_id = c.parent_id
        if parent_id is not None and parent_id in nodes:
            nodes[parent_id].replies.append(node)
        else:
            roots.append(node)
    # Top-level oldest first; replies oldest first too (chronological).
    roots.sort(key=lambda n: n.created_at)
    for n in nodes.values():
        n.replies.sort(key=lambda r: r.created_at)
    return roots


def _resolve_mentions(handles: list[str], users: list[User]) -> list[uuid.UUID]:
    """Map ``@handle`` tokens to real user IDs.

    Two strategies (handle-case-insensitive):

    * exact match on the local part of ``User.email``
    * exact match on ``User.full_name`` with whitespace squashed out
    """
    if not handles:
        return []
    norm = [h.lower() for h in handles]
    resolved: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for u in users:
        local = (u.email or "").split("@", 1)[0].lower()
        squashed_name = re.sub(r"\s+", "", (u.full_name or "")).lower()
        for h in norm:
            if h == local or (squashed_name and h == squashed_name):
                if u.id not in seen:
                    resolved.append(u.id)
                    seen.add(u.id)
                break
    return resolved


# ── thread fetch ───────────────────────────────────────────────────────


async def list_threads(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    file_kind: str,
    file_id: str,
    include_resolved: bool = False,
) -> tuple[list[FileCommentThread], int]:
    """Return every comment on a file, grouped into top-level threads.

    Resolved threads are filtered at the *thread* level: a thread is
    omitted iff its top-level comment is resolved. Resolving a single
    reply doesn't hide it from the rest of the thread.
    """
    stmt = (
        select(FileComment)
        .where(
            FileComment.project_id == project_id,
            FileComment.file_kind == file_kind,
            FileComment.file_id == file_id,
        )
        .order_by(FileComment.created_at.asc())
    )
    result = await session.execute(stmt)
    comments = list(result.scalars().all())
    if not comments:
        return [], 0

    # Bulk-load mentions for every comment in one query.
    mention_stmt = select(FileCommentMention).where(FileCommentMention.comment_id.in_([c.id for c in comments]))
    mention_rows = list((await session.execute(mention_stmt)).scalars().all())
    mentions_by_comment: dict[uuid.UUID, list[FileCommentMention]] = {}
    for m in mention_rows:
        mentions_by_comment.setdefault(m.comment_id, []).append(m)

    threads = _build_threads(comments, mentions_by_comment)
    if not include_resolved:
        threads = [t for t in threads if not t.resolved]
    return threads, len(threads)


# ── create ─────────────────────────────────────────────────────────────


async def create_comment(
    session: AsyncSession,
    payload: FileCommentCreate,
    author_id: uuid.UUID,
) -> tuple[FileComment, list[FileCommentMention]]:
    """Insert a comment + resolve @mentions.

    Returns ``(comment, mentions)`` — the router lifts them into a
    response. Both PDF-pin coordinates are required together: a comment
    with one of ``anchor_x``/``anchor_y`` but not the other is rejected
    here (we can't render half a pin).
    """
    if (payload.anchor_x is None) != (payload.anchor_y is None):
        raise ValueError("Both anchor_x and anchor_y must be provided together")

    # If a parent is referenced, it must (a) exist, (b) belong to the
    # same (project, kind, file) tuple. Cross-thread parenting is
    # rejected — otherwise a stranger could nest replies under a
    # comment they do not normally see.
    if payload.parent_id is not None:
        parent_stmt = select(FileComment).where(FileComment.id == payload.parent_id)
        parent = (await session.execute(parent_stmt)).scalar_one_or_none()
        if parent is None:
            raise ValueError(f"Parent comment {payload.parent_id} not found")
        if (
            parent.project_id != payload.project_id
            or parent.file_kind != payload.file_kind
            or parent.file_id != payload.file_id
        ):
            raise ValueError("Parent comment belongs to a different file")

    # Epic C — default ``file_version_id`` to the chain head when the
    # caller hasn't pinned one explicitly. Best-effort: a missing chain
    # head leaves the FK NULL (legacy behaviour, treated as "current"
    # in the viewer).
    file_version_id = payload.file_version_id
    if file_version_id is None:
        try:
            from app.modules.file_versions.repository import FileVersionRepository

            # Reuse the seed-lookup helper to find the chain via
            # (file_id, file_kind) so we don't need the canonical_name
            # at the comment site. The newest current row in that
            # chain is the right pin.
            repo = FileVersionRepository(session)
            seeds = await repo.list_for_file_id(payload.file_id, payload.file_kind)
            if seeds:
                # ``list_chain`` is the authoritative lookup — it
                # follows the canonical_name even if the seed id
                # itself is not the current row.
                chain = await repo.list_chain(
                    project_id=seeds[0].project_id,
                    file_kind=seeds[0].file_kind,
                    canonical_name=seeds[0].canonical_name,
                )
                current = next((r for r in chain if r.is_current), None)
                if current is not None:
                    file_version_id = current.id
        except Exception:
            logger.debug(
                "Failed to default file_version_id for new comment; leaving NULL",
                exc_info=True,
            )

    comment = FileComment(
        project_id=payload.project_id,
        file_kind=payload.file_kind,
        file_id=payload.file_id,
        file_version_snapshot=payload.file_version_snapshot,
        file_version_id=file_version_id,
        parent_id=payload.parent_id,
        author_id=author_id,
        body=payload.body,
        page_number=payload.page_number,
        anchor_x=payload.anchor_x,
        anchor_y=payload.anchor_y,
    )
    session.add(comment)
    await session.flush()

    mentions = await _extract_and_persist_mentions(
        session,
        comment.id,
        comment.body,
        exclude_user_id=author_id,
        comment=comment,
    )

    # Epic H — universal audit trail.
    from app.core.audit_log import log_activity as _log_activity

    await _log_activity(
        session,
        actor_id=str(author_id),
        entity_type="file_comment",
        entity_id=str(comment.id),
        action="created",
        metadata={
            "file_kind": payload.file_kind,
            "file_id": str(payload.file_id),
            "mention_count": len(mentions),
            "is_reply": payload.parent_id is not None,
        },
        module="file_comments",
        parent_entity_type="project",
        parent_entity_id=str(payload.project_id),
        after_state={"body_len": len(payload.body or "")},
    )
    return comment, mentions


async def _extract_and_persist_mentions(
    session: AsyncSession,
    comment_id: uuid.UUID,
    body: str,
    *,
    exclude_user_id: uuid.UUID | None = None,
    comment: FileComment | None = None,
) -> list[FileCommentMention]:
    """Find ``@handle`` tokens, resolve them, write mention rows.

    Self-mentions are dropped so the author does not see their own
    note in the unread-mentions inbox.

    Epic B / B1: after persisting mention rows we publish a detached
    ``file_comments.mention.created`` event per resolved user so the
    Notifications module can fan an in-app / email / webhook
    notification out to the mentioned user.  Publishing is detached
    (asyncio.create_task) so a misbehaving subscriber never blocks the
    upstream comment insert.
    """
    handles_raw = _MENTION_RE.findall(body)
    if not handles_raw:
        return []
    handles = list(dict.fromkeys(handles_raw))  # de-dupe, keep order

    # Pull candidate users in one query (filter on each handle for the
    # email-local prefix; falls back to full_name match in Python).
    user_stmt = select(User).where(
        or_(
            *(func.lower(User.email).like(f"{h.lower()}@%") for h in handles),
            *(func.lower(User.full_name).like(f"%{h.lower()}%") for h in handles),
        )
    )
    candidates = list((await session.execute(user_stmt)).scalars().all())
    resolved_ids = _resolve_mentions(handles, candidates)

    rows: list[FileCommentMention] = []
    seen: set[uuid.UUID] = set()
    for uid in resolved_ids:
        if uid == exclude_user_id:
            continue
        if uid in seen:
            continue
        seen.add(uid)
        row = FileCommentMention(
            comment_id=comment_id,
            mentioned_user_id=uid,
            notified_at=None,
        )
        session.add(row)
        rows.append(row)
    if rows:
        await session.flush()

    # Best-effort bridge to the Notifications module (Epic B / B1).
    # We publish detached so the comment insert is never blocked by a
    # downstream subscriber, and the comment context lookup is cheap
    # because the row is already in scope.
    if rows:
        try:
            from app.core.events import event_bus

            ctx_comment = comment
            if ctx_comment is None:
                ctx_comment = (
                    await session.execute(select(FileComment).where(FileComment.id == comment_id))
                ).scalar_one_or_none()
            for row in rows:
                event_bus.publish_detached(
                    "file_comments.mention.created",
                    {
                        "comment_id": str(comment_id),
                        "mention_id": str(row.id),
                        "mentioned_user_id": str(row.mentioned_user_id),
                        "author_id": str(exclude_user_id) if exclude_user_id else None,
                        "project_id": (str(ctx_comment.project_id) if ctx_comment else None),
                        "file_kind": ctx_comment.file_kind if ctx_comment else None,
                        "file_id": ctx_comment.file_id if ctx_comment else None,
                        "body_excerpt": (body or "")[:160],
                    },
                    source_module="oe_file_comments",
                )
        except Exception:  # noqa: BLE001 — event publish must never break the comment insert
            logger.debug("file_comments: mention event publish failed", exc_info=True)
    return rows


# ── update / soft-delete ───────────────────────────────────────────────


async def update_comment(
    session: AsyncSession,
    comment_id: uuid.UUID,
    payload: FileCommentUpdate,
    actor_id: uuid.UUID,
) -> tuple[FileComment, list[FileCommentMention]] | None:
    """Edit body and / or toggle the resolved flag.

    Only the author may edit the body; resolution is open to anyone
    with the ``file_comments.resolve`` permission (the router already
    gates this). Returns ``None`` when the comment is missing — the
    router translates to 404.
    """
    stmt = select(FileComment).where(FileComment.id == comment_id)
    comment = (await session.execute(stmt)).scalar_one_or_none()
    if comment is None:
        return None
    if comment.body == "[deleted]":
        # Tombstones are read-only.
        raise ValueError("Cannot edit a deleted comment")

    body_changed = False
    if payload.body is not None and payload.body != comment.body:
        if comment.author_id != actor_id:
            raise PermissionError("Only the author may edit a comment body")
        comment.body = payload.body
        body_changed = True

    if payload.resolved is not None and payload.resolved != comment.resolved:
        comment.resolved = payload.resolved
        comment.resolved_at = _now() if payload.resolved else None
        comment.resolved_by_id = actor_id if payload.resolved else None

    await session.flush()

    if body_changed:
        # Re-extract mentions on body edit so newly-added @handles
        # surface, and removed ones stop pinging. Old rows are
        # cleared and replaced — the unique constraint prevents
        # accidental duplicates.
        del_stmt = delete(FileCommentMention).where(FileCommentMention.comment_id == comment_id)
        await session.execute(del_stmt)
        await session.flush()
        await _extract_and_persist_mentions(
            session,
            comment_id,
            comment.body,
            exclude_user_id=comment.author_id,
            comment=comment,
        )

    mention_stmt = select(FileCommentMention).where(FileCommentMention.comment_id == comment_id)
    mentions = list((await session.execute(mention_stmt)).scalars().all())
    return comment, mentions


async def soft_delete_comment(
    session: AsyncSession,
    comment_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> bool:
    """Replace body with ``[deleted]`` + remove mentions.

    The row stays so child replies render with a tombstone. Returns
    ``False`` when the comment is missing.
    """
    stmt = select(FileComment).where(FileComment.id == comment_id)
    comment = (await session.execute(stmt)).scalar_one_or_none()
    if comment is None:
        return False
    if comment.author_id != actor_id:
        # Author-only delete — match the edit gate. Admins go through
        # a separate moderator endpoint (not in this wave).
        raise PermissionError("Only the author may delete a comment")
    comment.body = "[deleted]"
    comment.resolved = False
    comment.resolved_at = None
    comment.resolved_by_id = None
    await session.execute(delete(FileCommentMention).where(FileCommentMention.comment_id == comment_id))
    await session.flush()

    # Epic H — universal audit trail.
    from app.core.audit_log import log_activity as _log_activity

    await _log_activity(
        session,
        actor_id=str(actor_id),
        entity_type="file_comment",
        entity_id=str(comment_id),
        action="deleted",
        reason="Soft delete by author",
        module="file_comments",
        parent_entity_type="project",
        parent_entity_id=str(comment.project_id),
    )
    return True


# ── mentions inbox ─────────────────────────────────────────────────────


async def list_unread_mentions(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    limit: int = 50,
) -> tuple[list[UnreadMentionItem], int]:
    """Return mentions for ``user_id`` that have never been notified.

    Tombstoned parents are filtered out so a deleted comment doesn't
    show up in the unread inbox.
    """
    stmt = (
        select(FileCommentMention, FileComment)
        .join(
            FileComment,
            FileComment.id == FileCommentMention.comment_id,
        )
        .where(
            FileCommentMention.mentioned_user_id == user_id,
            FileCommentMention.notified_at.is_(None),
            FileComment.body != "[deleted]",
        )
        .order_by(FileCommentMention.created_at.desc())
        .limit(limit)
    )
    rows = list((await session.execute(stmt)).all())
    items = [
        UnreadMentionItem(
            mention_id=m.id,
            comment_id=c.id,
            project_id=c.project_id,
            file_kind=c.file_kind,
            file_id=c.file_id,
            author_id=c.author_id,
            body_excerpt=(c.body[:_EXCERPT_MAX] + "…") if len(c.body) > _EXCERPT_MAX else c.body,
            created_at=m.created_at,
        )
        for (m, c) in rows
    ]
    return items, len(items)


async def acknowledge_mention(
    session: AsyncSession,
    mention_id: uuid.UUID,
    user_id: uuid.UUID,
) -> bool:
    """Stamp ``notified_at`` so the mention disappears from the inbox.

    Returns ``False`` if the mention is missing or doesn't belong to
    ``user_id`` — the router maps both to 404 so cross-user IDOR is
    indistinguishable from "row not found".
    """
    stmt = select(FileCommentMention).where(
        FileCommentMention.id == mention_id,
        FileCommentMention.mentioned_user_id == user_id,
    )
    mention = (await session.execute(stmt)).scalar_one_or_none()
    if mention is None:
        return False
    if mention.notified_at is None:
        mention.notified_at = _now()
        await session.flush()
    return True


__all__ = [
    "acknowledge_mention",
    "create_comment",
    "list_threads",
    "list_unread_mentions",
    "soft_delete_comment",
    "update_comment",
]
