# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Service layer for the file-distribution module.

Holds the two sub-feature services side by side so the router stays
thin:

* :class:`CrossProjectSearchService` — ranked file search across every
  project the caller can read. Optional ``oe_file_search`` integration
  via soft import.
* :class:`DistributionListService` — CRUD for distribution lists +
  members.
* :class:`SubscriptionService` — CRUD for per-project/kind subs.

Per CLAUDE.md §"no hard import" we never ``import`` the optional
``oe_file_search`` module at module-load time. Instead the search
service tries the import inside a try/except on first use, caches the
outcome, and degrades gracefully when the module isn't installed.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.file_distribution.models import (
    FileDistributionList,
    FileDistributionMember,
    FileDistributionSubscription,
)
from app.modules.file_distribution.schemas import (
    NOTIFY_EVENTS,
    DistributionListCreate,
    DistributionListUpdate,
    DistributionMemberCreate,
    SearchHit,
    SubscriptionCreate,
)

if TYPE_CHECKING:  # pragma: no cover — typing only
    pass

logger = logging.getLogger(__name__)


# ── Exceptions ──────────────────────────────────────────────────────────────


class DistributionNotFoundError(Exception):
    """Target row missing or invisible to the caller."""


class DistributionConflictError(Exception):
    """Unique-constraint violation (name / member / subscription)."""


class DistributionValidationError(Exception):
    """Payload failed a business-rule check (e.g. unknown notify_on)."""


# ── Cross-project search ────────────────────────────────────────────────────


class CrossProjectSearchService:
    """Ranked file search across every project the caller can read.

    The set of accessible projects is computed by the router (which
    already has the project repository at hand). The service is given
    a concrete list of ``allowed_project_ids`` so it can be unit
    tested in isolation.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        # Cached ``True`` / ``False`` once we've checked whether
        # ``app.modules.file_search`` is import-resolvable AND its
        # table is present. ``None`` means "not checked yet".
        self._content_index_available: bool | None = None

    async def _has_content_index(self) -> bool:
        """Detect the optional ``file_search`` content-text index.

        Two checks needed because a clean install may have the Python
        module shipped but the DB table not yet created (e.g. fresh
        SQLite that hasn't run create_all). We treat either failure
        as "no content index — fall back".
        """
        if self._content_index_available is not None:
            return self._content_index_available
        try:
            # Deferred import so this module's import graph stays
            # independent of ``file_search``. If the module is missing
            # entirely (e.g. enterprise-only build) we land in the
            # except branch and disable the index path.
            from app.modules.file_search.models import (  # noqa: F401
                FileSearchIndex,
            )
        except Exception:  # noqa: BLE001 — broad on purpose
            self._content_index_available = False
            return False

        # Smoke probe the table — even ``SELECT 1`` against a missing
        # table raises in SQLite, so the failure path here also
        # disables the index gracefully on clean installs.
        try:
            await self.session.execute(
                select(FileSearchIndex.id).limit(1),
            )
            self._content_index_available = True
        except Exception:  # noqa: BLE001
            self._content_index_available = False
        return self._content_index_available

    async def search(
        self,
        *,
        q: str,
        allowed_project_ids: list[uuid.UUID],
        kinds: list[str] | None = None,
        limit: int = 50,
    ) -> tuple[list[SearchHit], bool]:
        """Return ranked hits + ``used_content_index`` flag."""
        q = (q or "").strip()
        if not q or not allowed_project_ids:
            return [], await self._has_content_index()

        limit = max(1, min(limit, 200))
        kinds_set = (
            {k.strip().lower() for k in kinds if k and k.strip()}
            if kinds is not None
            else {"document", "sheet", "photo"}
        )
        # Restrict to kinds the canonical-name search actually backs.
        # Everything else is silently dropped — the caller already
        # picked from a fixed dropdown so a bad value is impossible
        # from the UI but we don't want to 500 on a hand-rolled probe.
        kinds_set &= {"document", "sheet", "photo"}
        if not kinds_set:
            return [], await self._has_content_index()

        # Look up project names in one shot so the response has a
        # human-readable pill.
        from app.modules.projects.models import Project

        proj_rows = await self.session.execute(
            select(Project.id, Project.name).where(
                Project.id.in_(allowed_project_ids),
            ),
        )
        proj_names: dict[uuid.UUID, str] = {row[0]: row[1] for row in proj_rows.all()}

        like = f"%{q.lower()}%"
        hits: list[SearchHit] = []

        # ── Documents (canonical_name = ``name`` column) ──
        if "document" in kinds_set:
            from app.modules.documents.models import Document

            rows = await self.session.execute(
                select(
                    Document.id,
                    Document.project_id,
                    Document.name,
                )
                .where(
                    Document.project_id.in_(allowed_project_ids),
                    Document.name.ilike(like),
                )
                .limit(limit),
            )
            for did, pid, name in rows.all():
                hits.append(
                    SearchHit(
                        project_id=pid,
                        project_name=proj_names.get(pid, ""),
                        file_id=did,
                        kind="document",
                        canonical_name=name,
                        snippet="",
                        score=_score_name(name, q),
                    ),
                )

        # ── Sheets (canonical_name = sheet_title or sheet_number) ──
        if "sheet" in kinds_set:
            from app.modules.documents.models import Sheet

            rows = await self.session.execute(
                select(
                    Sheet.id,
                    Sheet.project_id,
                    Sheet.sheet_title,
                    Sheet.sheet_number,
                )
                .where(
                    Sheet.project_id.in_(allowed_project_ids),
                    or_(
                        Sheet.sheet_title.ilike(like),
                        Sheet.sheet_number.ilike(like),
                    ),
                )
                .limit(limit),
            )
            for sid, pid, title, number in rows.all():
                label = title or number or ""
                hits.append(
                    SearchHit(
                        project_id=pid,
                        project_name=proj_names.get(pid, ""),
                        file_id=sid,
                        kind="sheet",
                        canonical_name=label,
                        snippet="",
                        score=_score_name(label, q),
                    ),
                )

        # ── Photos (canonical_name = filename) ──
        if "photo" in kinds_set:
            from app.modules.documents.models import ProjectPhoto

            rows = await self.session.execute(
                select(
                    ProjectPhoto.id,
                    ProjectPhoto.project_id,
                    ProjectPhoto.filename,
                )
                .where(
                    ProjectPhoto.project_id.in_(allowed_project_ids),
                    ProjectPhoto.filename.ilike(like),
                )
                .limit(limit),
            )
            for phid, pid, fname in rows.all():
                hits.append(
                    SearchHit(
                        project_id=pid,
                        project_name=proj_names.get(pid, ""),
                        file_id=phid,
                        kind="photo",
                        canonical_name=fname,
                        snippet="",
                        score=_score_name(fname, q),
                    ),
                )

        # ── Optional content-index augmentation ──
        used_content_index = False
        if await self._has_content_index():
            try:
                from app.modules.file_search.models import (  # type: ignore
                    FileSearchIndex,
                )

                rows = await self.session.execute(
                    select(
                        FileSearchIndex.project_id,
                        FileSearchIndex.file_kind,
                        FileSearchIndex.file_id,
                        FileSearchIndex.content_text,
                    )
                    .where(
                        FileSearchIndex.project_id.in_(allowed_project_ids),
                        FileSearchIndex.file_kind.in_(kinds_set),
                        FileSearchIndex.content_text.ilike(like),
                    )
                    .limit(limit),
                )
                for pid, kind, fid, content in rows.all():
                    snippet = _snippet(content or "", q)
                    # Try to merge with an existing canonical_name hit
                    # so we don't double-list the same file.
                    merged = False
                    for h in hits:
                        if str(h.file_id) == str(fid) and h.kind == kind:
                            h.snippet = snippet
                            h.score += 0.5  # content match boosts rank
                            merged = True
                            break
                    if not merged:
                        hits.append(
                            SearchHit(
                                project_id=pid,
                                project_name=proj_names.get(pid, ""),
                                file_id=uuid.UUID(str(fid)) if not isinstance(fid, uuid.UUID) else fid,
                                kind=kind if kind in ("document", "sheet", "photo") else "document",
                                canonical_name="",
                                snippet=snippet,
                                score=0.5,
                            ),
                        )
                used_content_index = True
            except Exception:  # noqa: BLE001 — fall back if anything blows up
                logger.exception(
                    "file_search content index probe failed; falling back to canonical_name-only search",
                )
                used_content_index = False

        # Stable, descending sort by score then canonical_name.
        hits.sort(key=lambda h: (-h.score, h.canonical_name))
        return hits[:limit], used_content_index


def _score_name(name: str | None, q: str) -> float:
    """Naive substring score: exact > prefix > contains > absent."""
    if not name:
        return 0.0
    lname = name.lower()
    lq = q.lower()
    if lname == lq:
        return 3.0
    if lname.startswith(lq):
        return 2.0
    if lq in lname:
        return 1.0
    return 0.0


def _snippet(content: str, q: str, *, window: int = 80) -> str:
    """Return a short substring around the first match of ``q``."""
    if not content:
        return ""
    idx = content.lower().find(q.lower())
    if idx < 0:
        return content[:window].strip()
    start = max(0, idx - window // 2)
    end = min(len(content), idx + len(q) + window // 2)
    out = content[start:end].strip()
    if start > 0:
        out = "…" + out
    if end < len(content):
        out = out + "…"
    return out


# ── Distribution lists ───────────────────────────────────────────────────────


class DistributionListService:
    """CRUD for :class:`FileDistributionList` and its members."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_user(
        self,
        *,
        user_id: uuid.UUID,
        project_id: uuid.UUID | None,
    ) -> list[FileDistributionList]:
        """Return lists visible to ``user_id``.

        Visibility:
        * the user's own lists (any project_id including NULL)
        * other users' lists in the same project iff ``is_shared``
        """
        own_filter = FileDistributionList.owner_id == user_id
        if project_id is None:
            scope = FileDistributionList.project_id.is_(None)
            shared = and_(False)
        else:
            scope = or_(
                FileDistributionList.project_id == project_id,
                FileDistributionList.project_id.is_(None),
            )
            shared = and_(
                FileDistributionList.project_id == project_id,
                FileDistributionList.is_shared.is_(True),
                FileDistributionList.owner_id != user_id,
            )
        stmt = (
            select(FileDistributionList)
            .where(or_(and_(own_filter, scope), shared))
            .order_by(
                FileDistributionList.name.asc(),
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def _load(
        self,
        list_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> FileDistributionList:
        row = await self.session.get(FileDistributionList, list_id)
        if row is None:
            raise DistributionNotFoundError(str(list_id))
        if row.owner_id == user_id:
            return row
        if row.is_shared and row.project_id is not None:
            return row
        raise DistributionNotFoundError(str(list_id))

    async def get(
        self,
        list_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> FileDistributionList:
        return await self._load(list_id, user_id)

    async def create(
        self,
        payload: DistributionListCreate,
        user_id: uuid.UUID,
    ) -> FileDistributionList:
        row = FileDistributionList(
            owner_id=user_id,
            project_id=payload.project_id,
            name=payload.name,
            description=payload.description,
            is_shared=payload.is_shared,
        )
        self.session.add(row)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise DistributionConflictError(payload.name) from exc
        for m in payload.members:
            self.session.add(
                FileDistributionMember(
                    list_id=row.id,
                    email=m.email.strip().lower(),
                    display_name=m.display_name,
                    role=m.role,
                ),
            )
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise DistributionConflictError("duplicate member email") from exc
        await self.session.refresh(row, attribute_names=["members"])
        return row

    async def update(
        self,
        list_id: uuid.UUID,
        payload: DistributionListUpdate,
        user_id: uuid.UUID,
    ) -> FileDistributionList:
        row = await self._load(list_id, user_id)
        if row.owner_id != user_id:
            raise DistributionNotFoundError(str(list_id))
        data = payload.model_dump(exclude_unset=True)
        for k, v in data.items():
            setattr(row, k, v)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise DistributionConflictError(payload.name or row.name) from exc
        return row

    async def delete(self, list_id: uuid.UUID, user_id: uuid.UUID) -> None:
        row = await self._load(list_id, user_id)
        if row.owner_id != user_id:
            raise DistributionNotFoundError(str(list_id))
        await self.session.delete(row)
        await self.session.flush()

    # ── Members ──────────────────────────────────────────────────────────

    async def add_member(
        self,
        list_id: uuid.UUID,
        payload: DistributionMemberCreate,
        user_id: uuid.UUID,
    ) -> FileDistributionMember:
        row = await self._load(list_id, user_id)
        if row.owner_id != user_id:
            raise DistributionNotFoundError(str(list_id))
        member = FileDistributionMember(
            list_id=row.id,
            email=payload.email.strip().lower(),
            display_name=payload.display_name,
            role=payload.role,
        )
        self.session.add(member)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise DistributionConflictError(payload.email) from exc
        return member

    async def remove_member(
        self,
        list_id: uuid.UUID,
        member_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> None:
        row = await self._load(list_id, user_id)
        if row.owner_id != user_id:
            raise DistributionNotFoundError(str(list_id))
        stmt = select(FileDistributionMember).where(
            FileDistributionMember.id == member_id,
            FileDistributionMember.list_id == list_id,
        )
        result = await self.session.execute(stmt)
        member = result.scalar_one_or_none()
        if member is None:
            raise DistributionNotFoundError(str(member_id))
        await self.session.delete(member)
        await self.session.flush()


# ── Subscriptions ────────────────────────────────────────────────────────────


class SubscriptionService:
    """CRUD for :class:`FileDistributionSubscription`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_project(
        self,
        *,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> list[FileDistributionSubscription]:
        """Subscriptions belonging to the calling user in ``project_id``.

        We deliberately scope to the caller's own user_id / email here
        — a sub authored by user A and pointing at user B's email is
        still A's resource. The cross-project search and the
        subscription manager UI both want "what does this user
        receive?" so per-user filtering is the natural answer.
        """
        stmt = (
            select(FileDistributionSubscription)
            .where(
                FileDistributionSubscription.project_id == project_id,
                or_(
                    FileDistributionSubscription.subscriber_user_id == user_id,
                ),
            )
            .order_by(FileDistributionSubscription.file_kind.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_user_global(
        self,
        *,
        user_id: uuid.UUID,
    ) -> list[FileDistributionSubscription]:
        """All subscriptions the user has across every project."""
        stmt = (
            select(FileDistributionSubscription)
            .where(
                FileDistributionSubscription.subscriber_user_id == user_id,
            )
            .order_by(
                FileDistributionSubscription.project_id.asc(),
                FileDistributionSubscription.file_kind.asc(),
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(
        self,
        payload: SubscriptionCreate,
        user_id: uuid.UUID,
    ) -> FileDistributionSubscription:
        # Validate notify_on values eagerly so a bad payload comes
        # back as 400 instead of leaking into the table.
        bad = [e for e in payload.notify_on if e not in NOTIFY_EVENTS]
        if bad:
            raise DistributionValidationError(
                f"Unknown notify_on event(s): {sorted(bad)}",
            )
        sub = FileDistributionSubscription(
            project_id=payload.project_id,
            file_kind=payload.file_kind or "*",
            subscriber_email=payload.subscriber_email.strip().lower(),
            # Default to the calling user when the payload didn't
            # carry an explicit user id — that's the overwhelmingly
            # common "subscribe me" case.
            subscriber_user_id=payload.subscriber_user_id or user_id,
            notify_on=list(payload.notify_on),
            active=payload.active,
        )
        self.session.add(sub)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise DistributionConflictError(
                f"Subscription already exists for {sub.subscriber_email} on kind={sub.file_kind}",
            ) from exc
        return sub

    async def delete(
        self,
        subscription_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> None:
        row = await self.session.get(
            FileDistributionSubscription,
            subscription_id,
        )
        if row is None:
            raise DistributionNotFoundError(str(subscription_id))
        if row.subscriber_user_id is not None and row.subscriber_user_id != user_id:
            # Only the subscriber themselves (or, indirectly via
            # cascade, the project owner) can delete a sub.
            raise DistributionNotFoundError(str(subscription_id))
        await self.session.delete(row)
        await self.session.flush()


# ── Cross-module hooks ──────────────────────────────────────────────────────


async def on_file_new_revision(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    file_kind: str,
    file_id: str,
    canonical_name: str,
    version_number: int,
    actor_id: uuid.UUID | None = None,
) -> int:
    """Fan-out notifications for a newly-uploaded file revision.

    Looks up every active :class:`FileDistributionSubscription` whose
    ``project_id`` matches and whose ``file_kind`` is either ``"*"`` or
    equals the incoming kind. For each subscriber that resolves to an
    internal user (``subscriber_user_id IS NOT NULL``) we create an
    in-app notification via :class:`NotificationService`.

    External-only subscribers (those with ``subscriber_user_id IS
    NULL``) are not notified here — the email digest channel owns that
    side of the fan-out and lives outside this module. Returns the
    count of notifications created so callers / tests can assert on
    delivery.

    Designed to run in the same transaction as the version write but
    safe to call from a detached event handler too: it never raises,
    and a missing notifications module degrades gracefully (the
    function logs at debug and returns 0).
    """
    # Skip the ``"updated"`` event branch entirely when subscriptions
    # explicitly opt out of it via ``notify_on``. We treat a new
    # revision as ``"updated"`` because the file identity (project
    # scope + canonical name) is unchanged — only the contents
    # changed. Subs that asked only for ``"created"`` get nothing.
    stmt = select(FileDistributionSubscription).where(
        FileDistributionSubscription.project_id == project_id,
        FileDistributionSubscription.active.is_(True),
        or_(
            FileDistributionSubscription.file_kind == file_kind,
            FileDistributionSubscription.file_kind == "*",
        ),
    )
    result = await session.execute(stmt)
    subs = list(result.scalars().all())
    if not subs:
        return 0

    # Per-sub ``notify_on`` filter — keep only subs that opted into
    # ``"updated"`` (our model for "new revision posted").
    matching: list[FileDistributionSubscription] = []
    for sub in subs:
        events = list(sub.notify_on or [])
        if not events or "updated" in events:
            matching.append(sub)
    if not matching:
        return 0

    # Lazy-import the notification module so this file's import graph
    # stays free of a hard dependency on ``notifications``. A clean
    # install that disables the notifications module (e.g. minimal
    # build) gets a graceful no-op + debug log instead of an
    # ImportError.
    try:
        from app.modules.notifications.service import NotificationService
    except Exception:  # noqa: BLE001
        logger.debug(
            "on_file_new_revision: notifications module not available; skipping fan-out",
        )
        return 0

    notif_svc = NotificationService(session)
    created = 0
    for sub in matching:
        if sub.subscriber_user_id is None:
            # External-only subscriber — out of scope here; email
            # digest channel handles those.
            continue
        try:
            await notif_svc.create(
                user_id=sub.subscriber_user_id,
                notification_type="file_revision",
                title_key="notifications.file_distribution.new_revision.title",
                body_key="notifications.file_distribution.new_revision.body",
                body_context={
                    "canonical_name": canonical_name,
                    "version_number": str(version_number),
                    "file_kind": file_kind,
                },
                entity_type=f"file_{file_kind}",
                entity_id=str(file_id),
                action_url=f"/files?file={file_id}",
                metadata={
                    "project_id": str(project_id),
                    "subscription_id": str(sub.id),
                    "actor_id": str(actor_id) if actor_id else None,
                },
            )
            created += 1
        except Exception:  # noqa: BLE001
            # Per-subscriber failure must not block the fan-out for
            # the remaining recipients.
            logger.exception(
                "on_file_new_revision: failed to notify user_id=%s",
                sub.subscriber_user_id,
            )
    if created:
        logger.info(
            "on_file_new_revision: fan-out created %d notification(s) for project=%s kind=%s file=%s",
            created,
            project_id,
            file_kind,
            file_id,
        )
    return created
