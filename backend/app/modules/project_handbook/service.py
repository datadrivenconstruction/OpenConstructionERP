# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Project handbook service: chapters from a catalogue, their text, owners, versions and approval.

Every write runs in the caller's transaction with its audit entry (``log_activity``) and its events
(``publish_after_commit``).

A chapter is written by its editors, submitted, and approved by someone with the manage right. Approving
freezes the text as an immutable ``HandbookChapterVersion``; with four eyes on (the governance setting of
the project) the approver is never the person who submitted it. Editing an approved chapter opens a
revision; the approved version stays in force until the next one is approved.

The caller arrives as an :class:`Actor`: a user id and the booleans the router's permission checks
produced. No role and no token reach this file.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_log import log_activity
from app.core.events import publish_after_commit
from app.core.fsm import FSMError
from app.modules.project_governance import public as governance
from app.modules.project_handbook import data_room, rules, sources
from app.modules.project_handbook.catalogue import (
    DEFAULT_CATALOGUE_ID,
    HANDBOOK_KIND,
    HandbookCatalogue,
    label_of,
    register_kinds,
)
from app.modules.project_handbook.errors import HandbookError, conflict, forbidden, not_found
from app.modules.project_handbook.fsm import CHAPTER_FSM
from app.modules.project_handbook.models import Handbook, HandbookChapter, HandbookChapterVersion

logger = logging.getLogger(__name__)

MODULE = "project_handbook"
_EDITABLE_FIELDS = ("title", "content", "owner_id")


def _s(value: Any) -> str | None:
    return None if value is None else str(value)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Actor:
    """Who is calling, and what the router's permission checks allow them."""

    user_id: uuid.UUID | None
    manage: bool = False
    edit: bool = False


class ProjectHandbookService:
    """Orchestrates the handbook of one project."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        register_kinds()

    # ── infrastructure ─────────────────────────────────────────────────────

    async def _audit(self, actor_id: Any, entity_id: Any, action: str, **kw: Any) -> None:
        await log_activity(
            self.session,
            actor_id=_s(actor_id),
            entity_type="project_handbook",
            entity_id=_s(entity_id),
            action=action,
            module=MODULE,
            **kw,
        )

    def _publish(self, name: str, data: dict[str, Any]) -> None:
        publish_after_commit(self.session, f"{MODULE}.{name}", data, source_module=MODULE)

    async def _fsm(self, row: HandbookChapter, target: str, actor_id: Any) -> None:
        if row.status == target:
            raise conflict("already_in_state")
        try:
            await CHAPTER_FSM.apply(
                self.session,
                row,
                target,
                actor_id=_s(actor_id),
                extra_metadata={"project_id": _s(row.project_id), "chapter": row.code},
                entity_type=CHAPTER_FSM.name,
            )
        except FSMError as exc:
            raise conflict("invalid_transition", detail=str(exc)) from exc

    async def _project(self, project_id: uuid.UUID) -> Any:
        from app.modules.projects.models import Project

        project = await self.session.get(Project, project_id)
        if project is None:
            raise not_found("project_not_found")
        return project

    async def _pin(self, tenant_id: str | None, source: str, cid: str, version: int | None) -> int:
        from app.modules.project_governance.catalogue_store import CatalogueStore
        from app.modules.project_governance.errors import GovernanceError

        try:
            return await CatalogueStore(self.session).assert_pinnable(
                tenant_id, source, cid, version, kind=HANDBOOK_KIND
            )
        except GovernanceError as exc:
            raise HandbookError(exc.code, exc.status_code) from exc

    async def catalogue_for(self, handbook: Handbook) -> HandbookCatalogue:
        from app.modules.project_governance.catalogue_store import resolve_catalogue

        return await resolve_catalogue(
            self.session,
            handbook.catalogue_source,
            handbook.catalogue_id,
            handbook.catalogue_version,
            kind=HANDBOOK_KIND,
            from_pin=True,
        )

    async def get_handbook(self, project_id: uuid.UUID) -> Handbook | None:
        stmt = select(Handbook).where(Handbook.project_id == project_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def require_handbook(self, project_id: uuid.UUID) -> Handbook:
        handbook = await self.get_handbook(project_id)
        if handbook is None:
            raise not_found("handbook_missing")
        return handbook

    async def _chapters(
        self, project_id: uuid.UUID, *, code: str | None = None, lock: bool = False
    ) -> list[HandbookChapter]:
        stmt = select(HandbookChapter).where(HandbookChapter.project_id == project_id)
        if code is not None:
            stmt = stmt.where(HandbookChapter.code == code)
        if lock:
            stmt = stmt.with_for_update()
        return list(
            (await self.session.execute(stmt.order_by(HandbookChapter.sort_order, HandbookChapter.code))).scalars()
        )

    async def require_chapter(self, project_id: uuid.UUID, code: str, *, lock: bool = False) -> HandbookChapter:
        rows = await self._chapters(project_id, code=code, lock=lock)
        if not rows:
            raise not_found("chapter_missing")
        return rows[0]

    async def _four_eyes(self, project_id: uuid.UUID) -> bool:
        return (await governance.project_controls(self.session, project_id)).four_eyes

    async def _names(self, ids: set[uuid.UUID | None]) -> dict[str, str]:
        wanted = {i for i in ids if i is not None}
        if not wanted:
            return {}
        from app.modules.users.models import User

        rows = (
            await self.session.execute(select(User.id, User.full_name, User.email).where(User.id.in_(wanted)))
        ).all()
        return {str(uid): (name or email) for uid, name, email in rows}

    # ── handbook ───────────────────────────────────────────────────────────

    async def create_handbook(
        self,
        project_id: uuid.UUID,
        *,
        actor_id: uuid.UUID,
        tenant_id: str | None,
        catalogue_source: str = "shipped",
        catalogue_id: str | None = None,
        catalogue_version: int | None = None,
        title: str = "",
        edition: str = "",
        default_owner_id: uuid.UUID | None = None,
    ) -> Handbook:
        """Create the project's handbook, pin a chapter catalogue (the pack's, else neutral) and lay out its chapters."""
        project = await self._project(project_id)
        if await self.get_handbook(project_id) is not None:
            raise conflict("handbook_exists")
        cid = catalogue_id
        if cid is None:
            pin = governance.default_catalogue_pin(
                HANDBOOK_KIND, getattr(project, "country_code", None), getattr(project, "subdivision_code", None)
            )
            if pin is not None:
                catalogue_source, cid, catalogue_version = pin.source, pin.catalogue_id, pin.version
            else:
                cid = DEFAULT_CATALOGUE_ID
        version = await self._pin(tenant_id, catalogue_source, cid, catalogue_version)
        handbook = Handbook(
            project_id=project_id,
            catalogue_source=catalogue_source,
            catalogue_id=cid,
            catalogue_version=version,
            title=title,
            edition=edition,
            created_by=actor_id,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(handbook)
                await self.session.flush()
        except IntegrityError as exc:
            raise conflict("handbook_exists") from exc
        await self.sync_chapters(project_id, actor_id=actor_id, default_owner_id=default_owner_id)
        await self._audit(actor_id, handbook.id, "handbook_created", metadata={"catalogue": cid})
        return handbook

    async def patch_handbook(self, project_id: uuid.UUID, changes: dict[str, Any], actor_id: Any) -> Handbook:
        handbook = await self.require_handbook(project_id)
        for key in ("title", "edition"):
            if key in changes and changes[key] is not None:
                setattr(handbook, key, changes[key])
        await self.session.flush()
        await self._audit(actor_id, handbook.id, "handbook_updated")
        return handbook

    async def sync_chapters(
        self, project_id: uuid.UUID, *, actor_id: Any = None, default_owner_id: uuid.UUID | None = None
    ) -> dict[str, int]:
        """Lay the catalogue's chapters out for the project; idempotent.

        A chapter the catalogue added is created; one it already had keeps its text, owner, status and
        versions and only follows the catalogue's area, folder and position. A chapter the catalogue
        dropped stays with its text.
        """
        handbook = await self.require_handbook(project_id)
        catalogue = await self.catalogue_for(handbook)
        existing = {c.code: c for c in await self._chapters(project_id)}
        created = updated = 0
        for spec in catalogue.chapters:
            row = existing.get(spec.code)
            if row is None:
                self.session.add(
                    HandbookChapter(
                        project_id=project_id,
                        handbook_id=handbook.id,
                        code=spec.code,
                        area_code=spec.area,
                        folder_code=spec.folder,
                        sort_order=spec.order,
                        owner_id=default_owner_id,
                        status="draft",
                    )
                )
                created += 1
            elif (row.area_code, row.folder_code, row.sort_order) != (spec.area, spec.folder, spec.order):
                row.area_code, row.folder_code, row.sort_order = spec.area, spec.folder, spec.order
                updated += 1
        await self.session.flush()
        if created or updated:
            await self._audit(
                actor_id, handbook.id, "chapters_synced", metadata={"created": created, "updated": updated}
            )
        return {"created": created, "updated": updated}

    # ── chapters ───────────────────────────────────────────────────────────

    async def _linked_counts(
        self, project_id: uuid.UUID, rows: list[HandbookChapter], catalogue: HandbookCatalogue
    ) -> dict[str, int]:
        """Rows each chapter's sources find now; only chapters that read a source are listed."""
        cache: dict[str, int] = {}
        out: dict[str, int] = {}
        for row in rows:
            spec = catalogue.chapter(row.code)
            if spec is None or not spec.sources:
                continue
            total = 0
            for name in spec.sources:
                if name not in cache:
                    found = await sources.linked_rows(self.session, project_id, [name], "en")
                    cache[name] = sum(len(s["rows"]) for s in found)
                total += cache[name]
            out[row.code] = total
        return out

    def _chapter_dict(
        self,
        row: HandbookChapter,
        spec: Any,
        locale: str,
        actor: Actor | None,
        names: dict[str, str],
        four_eyes: bool,
        linked: int | None,
    ) -> dict[str, Any]:
        catalogue_title = label_of(spec, locale, row.code) if spec is not None else row.code
        data = {
            "id": str(row.id),
            "code": row.code,
            "area_code": row.area_code,
            "folder_code": row.folder_code,
            "order": row.sort_order,
            "title": row.title or catalogue_title,
            "catalogue_title": catalogue_title,
            "title_key": getattr(spec, "name_key", "") or None,
            "required": bool(spec.required) if spec is not None else False,
            "sources": list(spec.sources) if spec is not None else [],
            "owner_id": _s(row.owner_id),
            "owner_name": names.get(str(row.owner_id), "") if row.owner_id else "",
            "content": row.content,
            "status": row.status,
            "draft_version": row.draft_version,
            "approved_version": row.approved_version,
            "submitted_by": _s(row.submitted_by),
            "submitted_by_name": names.get(str(row.submitted_by), "") if row.submitted_by else "",
            "submitted_at": _iso(row.submitted_at),
            "approved_by": _s(row.approved_by),
            "approved_by_name": names.get(str(row.approved_by), "") if row.approved_by else "",
            "approved_at": _iso(row.approved_at),
            "linked_rows": linked,
        }
        if actor is not None:
            data["can"] = self._can(row, actor, four_eyes)
        return data

    def _can(self, row: HandbookChapter, actor: Actor, four_eyes: bool) -> dict[str, Any]:
        def one(action: str) -> dict[str, Any]:
            reason = rules.action_refusal(action, row.status, can_edit=actor.edit, can_manage=actor.manage)
            state_reason = rules.action_refusal(action, row.status, can_edit=True, can_manage=True)
            if reason is None and action == "approve":
                reason = rules.approval_refusal(four_eyes=four_eyes, is_submitter=row.submitted_by == actor.user_id)
            return rules.capability(reason, state_reason)

        return {a: one(a) for a in ("edit", "submit", "return", "approve")}

    async def list_chapters(
        self, project_id: uuid.UUID, *, locale: str = "en", actor: Actor | None = None
    ) -> list[dict[str, Any]]:
        handbook = await self.require_handbook(project_id)
        catalogue = await self.catalogue_for(handbook)
        rows = await self._chapters(project_id)
        names = await self._names(
            {r.owner_id for r in rows} | {r.submitted_by for r in rows} | {r.approved_by for r in rows}
        )
        four_eyes = await self._four_eyes(project_id)
        linked = await self._linked_counts(project_id, rows, catalogue)
        return [
            self._chapter_dict(r, catalogue.chapter(r.code), locale, actor, names, four_eyes, linked.get(r.code))
            for r in rows
        ]

    async def get_chapter(
        self, project_id: uuid.UUID, code: str, *, locale: str = "en", actor: Actor | None = None
    ) -> dict[str, Any]:
        """One chapter with the live rows of its sources and the list of approved versions."""
        handbook = await self.require_handbook(project_id)
        catalogue = await self.catalogue_for(handbook)
        row = await self.require_chapter(project_id, code)
        spec = catalogue.chapter(code)
        versions = await self.versions(project_id, code)
        names = await self._names(
            {row.owner_id, row.submitted_by, row.approved_by} | {uuid.UUID(v["approved_by"]) for v in versions}
        )
        linked = await sources.linked_rows(self.session, project_id, spec.sources if spec else (), locale)
        data = self._chapter_dict(
            row,
            spec,
            locale,
            actor,
            names,
            await self._four_eyes(project_id),
            sum(len(s["rows"]) for s in linked) if linked else None,
        )
        data["linked"] = linked
        data["versions"] = [{**v, "approved_by_name": names.get(v["approved_by"], "")} for v in versions]
        return data

    async def versions(self, project_id: uuid.UUID, code: str) -> list[dict[str, Any]]:
        row = await self.require_chapter(project_id, code)
        stmt = (
            select(HandbookChapterVersion)
            .where(HandbookChapterVersion.project_id == project_id, HandbookChapterVersion.chapter_id == row.id)
            .order_by(HandbookChapterVersion.version.desc())
        )
        return [
            {
                "version": v.version,
                "title": v.title,
                "content": v.content,
                "owner_id": _s(v.owner_id),
                "submitted_by": _s(v.submitted_by),
                "submitted_at": _iso(v.submitted_at),
                "approved_by": str(v.approved_by),
                "approved_at": v.approved_at.isoformat(),
            }
            for v in (await self.session.execute(stmt)).scalars()
        ]

    async def patch_chapter(
        self, project_id: uuid.UUID, code: str, changes: dict[str, Any], actor: Actor
    ) -> HandbookChapter:
        """Edit a chapter. An approved chapter opens a revision; one in review stands still."""
        row = await self.require_chapter(project_id, code, lock=True)
        refused = rules.action_refusal("edit", row.status, can_edit=True)
        if refused:
            raise conflict(refused)
        new = {k: changes[k] for k in _EDITABLE_FIELDS if k in changes and changes[k] != getattr(row, k)}
        if "owner_id" in new and new["owner_id"] is not None:
            await self._require_user(new["owner_id"])
        if "title" in new and new["title"] is None:
            new["title"] = ""
        if "content" in new and new["content"] is None:
            new["content"] = ""
        if not new:
            return row
        # Handing the chapter to someone else changes no approved text, so it opens no revision.
        if row.status == "approved" and ({"title", "content"} & new.keys()):
            await self._fsm(row, "revising", actor.user_id)
            row.draft_version = (row.approved_version or row.draft_version) + 1
        for key, value in new.items():
            setattr(row, key, value)
        await self.session.flush()
        await self._audit(actor.user_id, row.id, "chapter_updated", metadata={"chapter": code, "fields": sorted(new)})
        return row

    async def _require_user(self, user_id: uuid.UUID) -> None:
        from app.modules.users.models import User

        if (await self.session.execute(select(User.id).where(User.id == user_id))).scalar_one_or_none() is None:
            raise HandbookError("owner_not_found", 422)

    async def submit(self, project_id: uuid.UUID, code: str, actor: Actor) -> HandbookChapter:
        row = await self.require_chapter(project_id, code, lock=True)
        refused = rules.action_refusal("submit", row.status, can_edit=True)
        if refused:
            raise conflict(refused)
        blockers = rules.submission_blockers({"code": code, "owner_id": row.owner_id, "content": row.content})
        if blockers:
            raise HandbookError("submission_refused", 422, violations=[b.as_dict() for b in blockers])
        await self._fsm(row, "in_review", actor.user_id)
        row.submitted_by, row.submitted_at = actor.user_id, _now()
        await self.session.flush()
        await self._audit(
            actor.user_id, row.id, "chapter_submitted", metadata={"chapter": code, "version": row.draft_version}
        )
        self._publish("chapter.submitted", {"project_id": str(project_id), "chapter": code})
        return row

    async def approve(self, project_id: uuid.UUID, code: str, actor: Actor) -> HandbookChapter:
        """In review -> approved. Four eyes: never the person who submitted it."""
        row = await self.require_chapter(project_id, code, lock=True)
        refused = rules.action_refusal("approve", row.status, can_edit=True, can_manage=actor.manage)
        if refused:
            raise (forbidden if refused == "approval_permission_required" else conflict)(refused)
        refused = rules.approval_refusal(
            four_eyes=await self._four_eyes(project_id), is_submitter=row.submitted_by == actor.user_id
        )
        if refused:
            raise forbidden(refused)
        await self._fsm(row, "approved", actor.user_id)
        at = _now()
        self.session.add(
            HandbookChapterVersion(
                project_id=project_id,
                chapter_id=row.id,
                version=row.draft_version,
                title=row.title,
                content=row.content,
                owner_id=row.owner_id,
                submitted_by=row.submitted_by,
                submitted_at=row.submitted_at,
                approved_by=actor.user_id,
                approved_at=at,
            )
        )
        row.approved_version, row.approved_by, row.approved_at = row.draft_version, actor.user_id, at
        await self.session.flush()
        await self._audit(
            actor.user_id, row.id, "chapter_approved", metadata={"chapter": code, "version": row.approved_version}
        )
        self._publish(
            "chapter.approved", {"project_id": str(project_id), "chapter": code, "version": row.approved_version}
        )
        return row

    async def return_chapter(self, project_id: uuid.UUID, code: str, actor: Actor) -> HandbookChapter:
        row = await self.require_chapter(project_id, code, lock=True)
        refused = rules.action_refusal("return", row.status, can_edit=True, can_manage=actor.manage)
        if refused:
            raise (forbidden if refused == "approval_permission_required" else conflict)(refused)
        # A revision that is sent back stays a revision: the approved text is still in force.
        target = "draft" if row.approved_version is None else "revising"
        await self._fsm(row, target, actor.user_id)
        await self.session.flush()
        await self._audit(actor.user_id, row.id, "chapter_returned", metadata={"chapter": code})
        return row

    # ── readiness, validation ──────────────────────────────────────────────

    async def validation_payload(self, project_id: uuid.UUID) -> dict[str, Any]:
        handbook = await self.require_handbook(project_id)
        catalogue = await self.catalogue_for(handbook)
        rows = await self._chapters(project_id)
        linked = await self._linked_counts(project_id, rows, catalogue)
        chapters = []
        for r in rows:
            spec = catalogue.chapter(r.code)
            chapters.append(
                {
                    "code": r.code,
                    "status": r.status,
                    "content": r.content,
                    "owner_id": r.owner_id,
                    "required": bool(spec.required) if spec else False,
                    "sources": list(spec.sources) if spec else [],
                    "linked_rows": linked.get(r.code),
                    "approved_version": r.approved_version,
                    "submitted_at": r.submitted_at,
                }
            )
        return {"chapters": chapters}

    async def findings(self, project_id: uuid.UUID) -> list[dict[str, str]]:
        payload = await self.validation_payload(project_id)
        return [f.as_dict() for f in rules.handbook_findings(payload["chapters"])]

    async def readiness(self, project_id: uuid.UUID) -> dict[str, Any]:
        """What the gate evidence reads: the required chapters and how many have an approved version."""
        payload = await self.validation_payload(project_id)
        required = [c for c in payload["chapters"] if c["required"]]
        open_codes = sorted(c["code"] for c in required if c["approved_version"] is None)
        return {"required": len(required), "approved": len(required) - len(open_codes), "open": open_codes}

    async def data_room(self, project_id: uuid.UUID, user_id: uuid.UUID | None) -> dict[str, Any]:
        return await data_room.tree(self.session, project_id, user_id)

    # ── export ─────────────────────────────────────────────────────────────

    async def export_data(self, project_id: uuid.UUID, locale: str) -> dict[str, Any]:
        """Everything the PDF prints: the head, every chapter with its text and the live rows of its sources."""
        handbook = await self.require_handbook(project_id)
        project = await self._project(project_id)
        chapters = []
        for entry in await self.list_chapters(project_id, locale=locale):
            spec_sources = entry["sources"]
            entry["linked"] = await sources.linked_rows(self.session, project_id, spec_sources, locale)
            chapters.append(entry)
        return {
            "project_name": project.name,
            "project_code": getattr(project, "code", "") or "",
            "title": handbook.title,
            "edition": handbook.edition,
            "chapters": chapters,
        }
