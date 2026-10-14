# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""HSE frame service: the frame, its register, its roles and the readiness it reports.

Owned here: the frame (pinned catalogue, facts, plan state, review state), the
register of items, the roles and the links from items to records of other
modules.

Read only (linked): permit conditions (permits), incidents and observations
(safety), permits to work, job safety analyses, audits and corrective actions
(hse_advanced), inspections (inspections, construction_control). Their numbers
and states are read when asked, never copied; the linked summary and the
permit-condition topic therefore cannot disagree with the owning module.

Which duties apply (advance notice, coordinator, plan, later-works file) is
decided by :mod:`rules` from the project's facts and the pinned catalogue's
thresholds; an unknown answer is reported as unknown, never as met.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.core.events import publish_after_commit
from app.modules.hse_frame import links, rules
from app.modules.hse_frame.catalogue import (
    DEFAULT_CATALOGUE_ID,
    HSE_FRAME_KIND,
    HseFrameCatalogue,
    merged,
    register_kind,
    shipped_catalogues,
)
from app.modules.hse_frame.errors import HseFrameError, conflict, not_found
from app.modules.hse_frame.models import HseFrame, HseItem, HseLink, HseRole
from app.modules.hse_frame.repository import HseFrameRepository
from app.modules.hse_frame.vocab import FRAME_EDITABLE, ITEM_DONE

logger = logging.getLogger(__name__)

EVENT_PREFIX = "hse_frame."
# Incident severities the frame treats as serious; statuses of a corrective action that still demand work.
SERIOUS_SEVERITIES = ("major", "severe", "critical")
OPEN_CAPA = ("open", "in_progress", "overdue")


def _now() -> datetime:
    return datetime.now(UTC)


def _today() -> date:
    return datetime.now(UTC).date()


def _label(entry: Any, locale: str) -> str:
    labels = getattr(entry, "labels", None) or {}
    return labels.get(locale) or labels.get("en") or getattr(entry, "code", "")


class HseFrameService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = HseFrameRepository(session)

    # ── frame ──────────────────────────────────────────────────────────────

    async def frame(self, project_id: uuid.UUID) -> HseFrame | None:
        return await self.repo.frame(project_id)

    async def require_frame(self, project_id: uuid.UUID) -> HseFrame:
        row = await self.repo.frame(project_id)
        if row is None:
            raise not_found("frame_missing")
        return row

    async def _default_pin(self, project_id: uuid.UUID) -> tuple[str, str, int]:
        """What a new frame pins: the governance port's answer for the project's country, else neutral."""
        from app.modules.project_governance.public import default_catalogue_pin
        from app.modules.projects.models import Project

        register_kind()
        project = await self.session.get(Project, project_id)
        pin = default_catalogue_pin(
            HSE_FRAME_KIND, getattr(project, "country_code", None), getattr(project, "subdivision_code", None)
        )
        if pin is not None:
            return pin.source, str(pin.catalogue_id), pin.version
        return "shipped", DEFAULT_CATALOGUE_ID, shipped_catalogues()[DEFAULT_CATALOGUE_ID].version

    async def ensure_frame(self, project_id: uuid.UUID, actor: uuid.UUID | None) -> HseFrame:
        """The frame row for a WRITE; created with the country's default pin when missing.

        Two first writes race on ``uq_oe_hsef_frame_project``; the loser's insert is rolled back
        to its savepoint and it reads the winner's row.
        """
        row = await self.repo.frame(project_id)
        if row is not None:
            return row
        source, cid, version = await self._default_pin(project_id)
        row = HseFrame(
            project_id=project_id,
            catalogue_source=source,
            catalogue_id=cid,
            catalogue_version=version,
            hazardous_work_codes=[],
            created_by=actor,
        )
        try:
            async with self.session.begin_nested():
                await self.repo.add(row)
        except IntegrityError:
            existing = await self.repo.frame(project_id)
            if existing is None:
                raise
            return existing
        return row

    async def catalogue_for(self, frame: HseFrame) -> HseFrameCatalogue:
        """The pinned catalogue with its ``extends`` chain resolved."""
        from app.modules.project_governance.catalogue import InvalidCatalogueError
        from app.modules.project_governance.catalogue_store import resolve_catalogue
        from app.modules.project_governance.errors import GovernanceError

        register_kind()
        try:
            obj = await resolve_catalogue(
                self.session,
                frame.catalogue_source,
                frame.catalogue_id,
                frame.catalogue_version,
                kind=HSE_FRAME_KIND,
                # The triple is the pin stored on the frame; it was checked when it was written.
                from_pin=True,
            )
        except GovernanceError as exc:
            raise HseFrameError(exc.code, exc.status_code) from exc
        except InvalidCatalogueError as exc:
            raise HseFrameError("catalogue_invalid", 422, detail="; ".join(exc.errors)) from exc
        try:
            return merged(obj, shipped_catalogues().__getitem__)
        except (KeyError, ValueError) as exc:
            raise HseFrameError("catalogue_invalid", 422, detail=str(exc)) from exc

    async def project_catalogue(self, project_id: uuid.UUID) -> HseFrameCatalogue:
        """The catalogue a project reads: its frame's pin, else the country default (nothing is written)."""
        frame = await self.repo.frame(project_id)
        if frame is not None:
            return await self.catalogue_for(frame)
        source, cid, version = await self._default_pin(project_id)
        probe = HseFrame(catalogue_source=source, catalogue_id=cid, catalogue_version=version)
        return await self.catalogue_for(probe)

    async def available_catalogues(self, tenant_id: str | None, project_id: uuid.UUID) -> list[dict[str, Any]]:
        from app.modules.project_governance.catalogue_store import CatalogueStore

        source, cid, _version = await self._default_pin(project_id)
        items = await CatalogueStore(self.session).list_available(tenant_id, kind=HSE_FRAME_KIND)
        for item in items:
            item.pop("phases", None)
            item["id"] = str(item["id"])
            item["default"] = (item["source"], item["id"]) == (source, cid)
        return items

    async def _open(self, project_id: uuid.UUID) -> HseFrame:
        """The frame of a write to an existing row; refused unless it is in draft or revising."""
        frame = await self.require_frame(project_id)
        self._assert_draft(frame)
        return frame

    def _assert_draft(self, frame: HseFrame) -> None:
        if frame.state not in FRAME_EDITABLE:
            raise conflict("frame_not_editable", detail=frame.state)

    async def pin_catalogue(
        self,
        project_id: uuid.UUID,
        tenant_id: str | None,
        source: str,
        catalogue_id: str,
        version: int | None,
        actor: uuid.UUID | None,
    ) -> HseFrame:
        from app.modules.project_governance.catalogue_store import CatalogueStore
        from app.modules.project_governance.errors import GovernanceError

        register_kind()
        frame = await self.ensure_frame(project_id, actor)
        self._assert_draft(frame)
        try:
            pinned = await CatalogueStore(self.session).assert_pinnable(
                tenant_id, source, catalogue_id, version, kind=HSE_FRAME_KIND
            )
        except GovernanceError as exc:
            raise HseFrameError(exc.code, exc.status_code) from exc
        frame.catalogue_source, frame.catalogue_id, frame.catalogue_version = source, catalogue_id, pinned
        await self._flush()
        return frame

    async def _flush(self) -> None:
        try:
            await self.session.flush()
        except StaleDataError as exc:
            raise conflict("concurrent_update") from exc

    async def patch_frame(self, project_id: uuid.UUID, data: Any, actor: uuid.UUID | None) -> HseFrame:
        frame = await self.ensure_frame(project_id, actor)
        self._assert_draft(frame)
        catalogue = await self.catalogue_for(frame)
        fields = data.model_dump(exclude_unset=True)
        codes = fields.get("hazardous_work_codes")
        if codes is not None:
            unknown = sorted(set(codes) - catalogue.codes("hazardous_works"))
            if unknown:
                raise HseFrameError("unknown_hazardous_work", 422, detail=",".join(unknown))
            fields["hazardous_work_codes"] = sorted(set(codes))
        for key, value in fields.items():
            if value is None and key not in _NULLABLE_FRAME_FIELDS:
                continue
            setattr(frame, key, value)
        if fields.get("plan_status") in ("issued", "in_force") and frame.plan_issued_on is None:
            frame.plan_issued_on = _today()
        await self._flush()
        return frame

    # ── review: submit, approve, reopen ────────────────────────────────────

    async def submit(self, project_id: uuid.UUID, actor: uuid.UUID, today: date | None = None) -> HseFrame:
        frame = await self.require_frame(project_id)
        if frame.state not in FRAME_EDITABLE:
            raise conflict("invalid_transition", detail=f"{frame.state}->submit")
        payload = await self.validation_payload(project_id, today or _today())
        blockers = [f for f in payload["findings"] if f["severity"] == "error"]
        if blockers:
            raise HseFrameError("frame_incomplete", 422, violations=blockers)
        frame.state, frame.submitted_by, frame.submitted_at = "in_review", actor, _now()
        await self._flush()
        await self._audit(project_id, actor, "frame", frame.id, "submitted")
        self._publish("frame.submitted", project_id)
        return frame

    async def approve(self, project_id: uuid.UUID, actor: uuid.UUID) -> HseFrame:
        frame = await self.require_frame(project_id)
        if frame.state != "in_review":
            raise conflict("invalid_transition", detail=f"{frame.state}->approve")
        if frame.submitted_by == actor and await self._four_eyes(project_id):
            raise HseFrameError("approver_is_submitter", 403)
        # Approved by hand and in force at once; a revision starts from `revise`.
        frame.state, frame.approved_by, frame.approved_at = "binding", actor, _now()
        await self._flush()
        await self._audit(project_id, actor, "frame", frame.id, "approved")
        self._publish("frame.approved", project_id)
        self._publish("frame.binding", project_id)
        return frame

    async def _four_eyes(self, project_id: uuid.UUID) -> bool:
        """The project's four-eyes control as governance states it; on when the project has no model."""
        from app.modules.project_governance import public

        return (await public.project_controls(self.session, project_id)).four_eyes

    async def revise(self, project_id: uuid.UUID, actor: uuid.UUID, note: str = "") -> HseFrame:
        """Take a frame in review, approved or binding back into revision; the next submit puts it in force again."""
        frame = await self.require_frame(project_id)
        if frame.state in FRAME_EDITABLE:
            raise conflict("invalid_transition", detail=f"{frame.state}->revise")
        before = frame.state
        frame.state, frame.approved_by, frame.approved_at = "revising", None, None
        await self._flush()
        await self._audit(project_id, actor, "frame", frame.id, "revised", from_status=before, note=note)
        self._publish("frame.revising", project_id)
        return frame

    def _publish(self, name: str, project_id: uuid.UUID, **data: Any) -> None:
        publish_after_commit(
            self.session, EVENT_PREFIX + name, {"project_id": str(project_id), **data}, source_module="hse_frame"
        )

    async def _audit(
        self, project_id: uuid.UUID, actor: uuid.UUID | None, entity: str, eid: Any, action: str, **kw: Any
    ) -> None:
        from app.core.audit_log import log_activity

        try:
            async with self.session.begin_nested():
                await log_activity(
                    self.session,
                    actor_id=actor,
                    entity_type=f"hse_frame.{entity}",
                    entity_id=eid,
                    action=action,
                    metadata={"project_id": str(project_id), **kw},
                )
        except Exception:  # audit is best effort, never blocks the act
            logger.debug("hse_frame: audit %s %s failed", entity, action, exc_info=True)

    # ── duties ─────────────────────────────────────────────────────────────

    def facts_of(self, frame: HseFrame) -> rules.Facts:
        return rules.Facts(
            duration_working_days=frame.duration_working_days,
            peak_workers=frame.peak_workers,
            person_days=frame.person_days,
            employers_count=frame.employers_count,
            hazardous_work_codes=tuple(frame.hazardous_work_codes or ()),
            hazardous_works_assessed=bool(frame.hazardous_works_assessed),
        )

    def duties_of(self, frame: HseFrame, catalogue: HseFrameCatalogue) -> rules.Duties:
        return rules.duties(self.facts_of(frame), catalogue.thresholds, catalogue.codes("hazardous_works"))

    # ── templates ──────────────────────────────────────────────────────────

    async def apply_templates(self, project_id: uuid.UUID, actor: uuid.UUID | None) -> dict[str, int]:
        """Create register rows from the catalogue templates whose trigger holds; running it twice adds nothing."""
        frame = await self.ensure_frame(project_id, actor)
        self._assert_draft(frame)
        catalogue = await self.catalogue_for(frame)
        duties = self.duties_of(frame, catalogue)
        have = {i.template_code for i in await self.repo.list(HseItem, project_id) if i.template_code}
        created = skipped = 0
        for template in catalogue.templates:
            applies = duties.get(template.applies_when)
            if template.code in have or applies is False:
                skipped += 1
                continue
            # An unknown trigger still creates the row: the duty may apply, and the row says what to do about it.
            await self.repo.add(
                HseItem(
                    project_id=project_id,
                    frame_id=frame.id,
                    topic=template.topic,
                    template_code=template.code,
                    title=_label(template, "en"),
                    audience=list(template.audience),
                    obligation=template.obligation,
                    legal_basis=template.legal_basis,
                    in_tender_documents=template.in_tender_documents,
                    source="template",
                    created_by=actor,
                )
            )
            created += 1
        return {"created": created, "skipped": skipped}

    # ── items ──────────────────────────────────────────────────────────────

    async def list_items(
        self, project_id: uuid.UUID, today: date | None = None, **filters: Any
    ) -> list[dict[str, Any]]:
        today = today or _today()
        rows = await self.repo.list(HseItem, project_id, HseItem.topic, HseItem.created_at, **filters)
        by_item: dict[uuid.UUID, list[HseLink]] = {r.id: [] for r in rows}
        for link in await self.repo.links_for(project_id, [r.id for r in rows]):
            by_item[link.item_id].append(link)
        return [await self._item_out(r, by_item[r.id], today) for r in rows]

    async def _item_out(self, row: HseItem, item_links: list[HseLink], today: date) -> dict[str, Any]:
        out = {c.key: getattr(row, c.key) for c in HseItem.__table__.columns if hasattr(row, c.key)}
        out["overdue"] = bool(row.due_date and row.due_date < today and row.status not in ITEM_DONE)
        out["links"] = [
            {
                "id": link.id,
                "item_id": link.item_id,
                "link_kind": link.link_kind,
                "link_id": link.link_id,
                "note": link.note,
                "fact": await links.resolve(self.session, row.project_id, link.link_kind, link.link_id),
            }
            for link in item_links
        ]
        return out

    async def item(self, project_id: uuid.UUID, item_id: uuid.UUID) -> HseItem:
        row = await self.repo.get(HseItem, project_id, item_id)
        if row is None:
            raise not_found("item_not_found")
        return row

    async def item_view(self, project_id: uuid.UUID, item_id: uuid.UUID) -> dict[str, Any]:
        row = await self.item(project_id, item_id)
        return await self._item_out(row, await self.repo.links_for(project_id, [row.id]), _today())

    async def _check_topic(self, frame: HseFrame, topic: str) -> None:
        if topic not in (await self.catalogue_for(frame)).codes("topics"):
            raise HseFrameError("unknown_topic", 422, detail=topic)

    async def _check_user(self, project_id: uuid.UUID, user_id: uuid.UUID | None) -> None:
        if user_id is None:
            return
        from app.modules.project_governance.public import user_can_access_project

        if not await user_can_access_project(self.session, project_id, user_id):
            raise HseFrameError("user_not_in_project", 422)

    async def create_item(self, project_id: uuid.UUID, data: Any, actor: uuid.UUID | None) -> HseItem:
        frame = await self.ensure_frame(project_id, actor)
        self._assert_draft(frame)
        await self._check_topic(frame, data.topic)
        await self._check_user(project_id, data.responsible_user_id)
        return await self.repo.add(
            HseItem(project_id=project_id, frame_id=frame.id, source="manual", created_by=actor, **data.model_dump())
        )

    async def patch_item(self, project_id: uuid.UUID, item_id: uuid.UUID, data: Any) -> HseItem:
        await self._open(project_id)
        row = await self.item(project_id, item_id)
        fields = data.model_dump(exclude_unset=True)
        if "responsible_user_id" in fields:
            await self._check_user(project_id, fields["responsible_user_id"])
        if "status" in fields and row.status in ITEM_DONE:
            raise conflict("item_closed", detail=row.status)
        for key, value in fields.items():
            if value is None and key not in ("responsible_user_id", "due_date"):
                continue
            setattr(row, key, value)
        await self._flush()
        return row

    async def meet_item(self, project_id: uuid.UUID, item_id: uuid.UUID, data: Any) -> HseItem:
        await self._open(project_id)
        row = await self.item(project_id, item_id)
        if row.status in ("waived", "not_applicable"):
            raise conflict("item_closed", detail=row.status)
        met_on = data.met_on or _today()
        if met_on > _today():
            raise HseFrameError("date_in_future", 422)
        row.status, row.met_on = "met", met_on
        if data.evidence_note:
            row.evidence_note = data.evidence_note
        await self._flush()
        return row

    async def waive_item(self, project_id: uuid.UUID, item_id: uuid.UUID, data: Any, actor: uuid.UUID) -> HseItem:
        await self._open(project_id)
        row = await self.item(project_id, item_id)
        if row.status == "met":
            raise conflict("item_closed", detail=row.status)
        if row.created_by == actor and row.obligation == "mandatory" and row.source != "template":
            # A person cannot waive a duty they wrote down themselves.
            raise HseFrameError("waiver_by_author", 403)
        row.status = "not_applicable" if data.not_applicable else "waived"
        row.waive_reason, row.waived_by = data.reason, actor
        await self._flush()
        await self._audit(project_id, actor, "item", row.id, row.status, reason=data.reason)
        return row

    async def reopen_item(self, project_id: uuid.UUID, item_id: uuid.UUID) -> HseItem:
        await self._open(project_id)
        row = await self.item(project_id, item_id)
        row.status, row.met_on, row.waive_reason, row.waived_by = "open", None, "", None
        await self._flush()
        return row

    async def delete_item(self, project_id: uuid.UUID, item_id: uuid.UUID) -> None:
        await self._open(project_id)
        row = await self.item(project_id, item_id)
        if row.source == "template":
            raise conflict("template_item_not_deletable")
        await self.repo.remove(row)

    # ── roles ──────────────────────────────────────────────────────────────

    async def list_roles(self, project_id: uuid.UUID, today: date | None = None) -> list[dict[str, Any]]:
        today = today or _today()
        rows = await self.repo.list(HseRole, project_id, HseRole.role_code, HseRole.created_at)
        return [
            {
                **{c.key: getattr(r, c.key) for c in HseRole.__table__.columns if hasattr(r, c.key)},
                "in_force": rules.role_in_force(r.status, r.appointed_on, r.ends_on, today),
            }
            for r in rows
        ]

    async def role(self, project_id: uuid.UUID, role_id: uuid.UUID) -> HseRole:
        row = await self.repo.get(HseRole, project_id, role_id)
        if row is None:
            raise not_found("role_not_found")
        return row

    def _check_role_dates(
        self, status: str, appointed_on: date | None, ends_on: date | None, name: str, user: Any
    ) -> None:
        if appointed_on and ends_on and ends_on < appointed_on:
            raise HseFrameError("role_dates_inverted", 422)
        if status == "appointed" and appointed_on is None:
            raise HseFrameError("appointed_without_date", 422)
        if status in ("appointed", "ended") and not (name.strip() or user):
            raise HseFrameError("role_without_person", 422)

    async def create_role(self, project_id: uuid.UUID, data: Any, actor: uuid.UUID | None) -> HseRole:
        frame = await self.ensure_frame(project_id, actor)
        self._assert_draft(frame)
        catalogue = await self.catalogue_for(frame)
        if data.role_code not in catalogue.codes("role_kinds"):
            raise HseFrameError("unknown_role", 422, detail=data.role_code)
        await self._check_user(project_id, data.person_user_id)
        self._check_role_dates(data.status, data.appointed_on, data.ends_on, data.person_name, data.person_user_id)
        return await self.repo.add(
            HseRole(project_id=project_id, frame_id=frame.id, created_by=actor, **data.model_dump())
        )

    async def patch_role(self, project_id: uuid.UUID, role_id: uuid.UUID, data: Any) -> HseRole:
        await self._open(project_id)
        row = await self.role(project_id, role_id)
        fields = data.model_dump(exclude_unset=True)
        if "person_user_id" in fields:
            await self._check_user(project_id, fields["person_user_id"])
        merged_ = {
            **{k: getattr(row, k) for k in ("status", "appointed_on", "ends_on", "person_name", "person_user_id")},
            **fields,
        }
        self._check_role_dates(
            merged_["status"],
            merged_["appointed_on"],
            merged_["ends_on"],
            merged_["person_name"] or "",
            merged_["person_user_id"],
        )
        for key, value in fields.items():
            setattr(row, key, value if value is not None or key not in _NON_NULL_ROLE_FIELDS else getattr(row, key))
        await self._flush()
        return row

    async def delete_role(self, project_id: uuid.UUID, role_id: uuid.UUID) -> None:
        await self._open(project_id)
        await self.repo.remove(await self.role(project_id, role_id))

    # ── links ──────────────────────────────────────────────────────────────

    async def add_link(self, project_id: uuid.UUID, item_id: uuid.UUID, data: Any, actor: uuid.UUID | None) -> HseLink:
        await self._open(project_id)
        row = await self.item(project_id, item_id)
        if data.link_kind not in links.known_kinds():
            raise HseFrameError("unknown_link_kind", 422, detail=data.link_kind)
        fact = await links.resolve(self.session, project_id, data.link_kind, data.link_id)
        if fact is None:
            # Not found and "another project's" read the same, so an id cannot be probed across projects.
            raise not_found("link_target_not_found")
        existing = [
            x
            for x in await self.repo.links_for(project_id, [row.id])
            if (x.link_kind, x.link_id) == (data.link_kind, data.link_id)
        ]
        if existing:
            return existing[0]
        link = HseLink(project_id=project_id, item_id=row.id, created_by=actor, **data.model_dump())
        try:
            async with self.session.begin_nested():
                await self.repo.add(link)
        except IntegrityError:
            return (await self.repo.links_for(project_id, [row.id]))[0]
        return link

    async def remove_link(self, project_id: uuid.UUID, item_id: uuid.UUID, link_id: uuid.UUID) -> None:
        await self._open(project_id)
        link = await self.repo.get(HseLink, project_id, link_id)
        if link is None or link.item_id != item_id:
            raise not_found("link_not_found")
        await self.repo.remove(link)

    # ── permit conditions: merge into the register ─────────────────────────

    async def _hse_conditions(self, project_id: uuid.UUID) -> list[Any]:
        """The confirmed, live permit conditions the permits module counts as HSE relevant."""
        try:
            from app.modules.permits import conditions as cnd
            from app.modules.permits.models import PermitCondition
        except ImportError:
            return []
        stmt = (
            select(PermitCondition)
            .where(PermitCondition.project_id == project_id)
            .where(PermitCondition.confirmed.is_(True))
            .where(PermitCondition.status != "superseded")
            .order_by(PermitCondition.number)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [c for c in rows if cnd.hse_relevant(c.topic, c.hse_override)]

    async def _unconsolidated(self, project_id: uuid.UUID) -> tuple[list[Any], list[Any]]:
        """``(conditions without a register row, conditions with one)``."""
        linked = {x.link_id for x in await self.repo.links_of_kind(project_id, "permit_condition")}
        conditions = await self._hse_conditions(project_id)
        return [c for c in conditions if str(c.id) not in linked], [c for c in conditions if str(c.id) in linked]

    async def consolidate_permit_conditions(self, project_id: uuid.UUID, actor: uuid.UUID | None) -> dict[str, int]:
        """One register row per HSE permit condition, linked to it; a condition already linked is skipped."""
        frame = await self.ensure_frame(project_id, actor)
        self._assert_draft(frame)
        catalogue = await self.catalogue_for(frame)
        topic = next((t for t in catalogue.topics if t.basis == "permits"), None)
        if topic is None:
            raise HseFrameError("no_permit_topic", 422)
        missing, _present = await self._unconsolidated(project_id)
        from app.modules.permits import conditions as cnd

        created = 0
        for c in missing:
            item = await self.repo.add(
                HseItem(
                    project_id=project_id,
                    frame_id=frame.id,
                    topic=topic.code,
                    title=f"{c.number}: {(c.text or '').strip()[:400]}",
                    audience=["owner", "contractor"],
                    obligation="mandatory",
                    legal_basis="",
                    status="met" if c.status in cnd.DONE_STATES else "open",
                    met_on=_today() if c.status in cnd.DONE_STATES else None,
                    due_date=c.due_date,
                    responsible_user_id=c.owner_user_id,
                    responsible_party=c.responsible_party or "",
                    source="permit",
                    created_by=actor,
                )
            )
            await self.repo.add(
                HseLink(
                    project_id=project_id,
                    item_id=item.id,
                    link_kind="permit_condition",
                    link_id=str(c.id),
                    created_by=actor,
                )
            )
            created += 1
        return {"created": created, "already_linked": len(_present)}

    # ── linked summary: live reads of the neighbouring modules ─────────────

    async def linked_summary(self, project_id: uuid.UUID, today: date | None = None) -> dict[str, Any]:
        """Counts read from the owning modules now; a module that is not installed answers ``None``."""
        today = today or _today()

        async def count(kind: str, *where: Any) -> int | None:
            model = links._model(kind)
            if model is None:
                return None
            stmt = select(model.id).where(model.project_id == project_id)
            for clause in where:
                stmt = stmt.where(clause(model))
            return len((await self.session.execute(stmt)).all())

        linked_incidents = {x.link_id for x in await self.repo.links_of_kind(project_id, "safety_incident")}
        incident_model = links._model("safety_incident")
        serious_unlinked = None
        if incident_model is not None:
            rows = (
                (
                    await self.session.execute(
                        select(incident_model.id)
                        .where(incident_model.project_id == project_id)
                        .where(incident_model.status != "closed")
                        .where(incident_model.severity.in_(SERIOUS_SEVERITIES))
                    )
                )
                .scalars()
                .all()
            )
            serious_unlinked = [str(r) for r in rows if str(r) not in linked_incidents]
        conditions = await self._hse_conditions(project_id)
        from app.modules.permits import conditions as cnd

        return {
            "incidents_open": await count("safety_incident", lambda m: m.status != "closed"),
            "incidents_serious_open_unlinked": None if serious_unlinked is None else len(serious_unlinked),
            "serious_unlinked_ids": serious_unlinked or [],
            "observations_open": await count("safety_observation", lambda m: m.status != "closed"),
            "permits_to_work_active": await count("hse_ptw", lambda m: m.status == "active"),
            "corrective_actions_open": await count("hse_capa", lambda m: m.status.in_(OPEN_CAPA)),
            "audits": await count("hse_audit"),
            "inspections": await count("cc_inspection"),
            "permit_conditions_hse": len(conditions) if links._model("permit_condition") is not None else None,
            "permit_conditions_hse_open": sum(1 for c in conditions if c.status in cnd.OPEN_STATES),
            "permit_conditions_hse_overdue": sum(
                1 for c in conditions if c.due_date and c.due_date < today and c.status in cnd.OPEN_STATES
            ),
        }

    # ── readiness ──────────────────────────────────────────────────────────

    async def started(self, project_id: uuid.UUID) -> bool:
        """Whether the frame holds anything: opening the screen alone (no row) does not arm the gate."""
        return await self.repo.frame(project_id) is not None

    async def readiness(self, project_id: uuid.UUID, today: date | None = None) -> dict[str, Any]:
        """One item per catalogue topic with a criterion, plus the permit-condition topic; never met by silence."""
        today = today or _today()
        frame = await self.require_frame(project_id)
        catalogue = await self.catalogue_for(frame)
        duties = self.duties_of(frame, catalogue)
        items = await self.repo.list(HseItem, project_id)
        roles = await self.repo.list(HseRole, project_id)
        in_force = [r.role_code for r in roles if rules.role_in_force(r.status, r.appointed_on, r.ends_on, today)]
        out: list[dict[str, Any]] = []
        for topic in catalogue.topics:
            if topic.criterion is None and topic.basis != "permits":
                # A working topic without a gate criterion is shown on its own tab, not at the gate.
                continue
            if topic.basis == "items":
                rows = [(i.obligation, i.status) for i in items if i.topic == topic.code]
                state, detail = rules.items_state(rows), f"{sum(1 for _o, s in rows if s in ITEM_DONE)}/{len(rows)}"
            elif topic.basis == "roles":
                required = [
                    (r.code, duties.get(r.required_when) if r.required_when else False) for r in catalogue.role_kinds
                ]
                state = rules.roles_state(required, in_force)
                detail = ",".join(code for code, req in required if req is True and code not in in_force)
            else:
                missing, present = await self._unconsolidated(project_id)
                if not missing and not present:
                    state, detail = "unknown", "no_conditions"
                elif missing:
                    state, detail = "not_met", str(len(missing))
                else:
                    state = (
                        "warning"
                        if any(
                            c.status in ("open", "evidence_submitted", "discharge_applied", "breach")
                            and c.trigger == "before_start"
                            for c in present
                        )
                        else "met"
                    )
                    detail = str(len(present))
            out.append(
                {
                    "code": topic.criterion or topic.code,
                    "topic": topic.code,
                    "criterion": topic.criterion,
                    "state": state,
                    "detail": detail,
                    "label": _label(topic, "en"),
                }
            )
        return {"frame_state": frame.state, "items": out, "duties": _duties_out(duties)}

    # ── validation ─────────────────────────────────────────────────────────

    async def validation_payload(self, project_id: uuid.UUID, today: date | None = None) -> dict[str, Any]:
        """Every finding of the frame as ``{code, ref, severity, params}``; rules only pick by code."""
        today = today or _today()
        frame = await self.require_frame(project_id)
        catalogue = await self.catalogue_for(frame)
        duties = self.duties_of(frame, catalogue)
        t = catalogue.thresholds
        findings: list[dict[str, Any]] = []

        def add(code: str, severity: str, ref: str = "", **params: Any) -> None:
            findings.append({"code": code, "severity": severity, "ref": ref, "params": params})

        roles = await self.repo.list(HseRole, project_id)
        in_force = {r.role_code for r in roles if rules.role_in_force(r.status, r.appointed_on, r.ends_on, today)}
        for kind in catalogue.role_kinds:
            if kind.required_when and duties.get(kind.required_when) is True and kind.code not in in_force:
                add(
                    "coordinator_missing" if kind.party == "coordinator" else "required_role_missing",
                    "error",
                    kind.code,
                )
        for r in roles:
            kind = catalogue.entry("role_kinds", r.role_code)
            if kind is not None and kind.qualification_required and r.status == "appointed":
                if not r.qualification.strip():
                    add("role_without_qualification", "warning", str(r.id), role=r.role_code)
                elif r.qualification_valid_until and r.qualification_valid_until < today:
                    add("role_qualification_expired", "warning", str(r.id), role=r.role_code)
        if duties.advance_notice is True and frame.advance_notice_sent_on is None:
            late = rules.advance_notice_overdue(duties, None, frame.planned_start, t.advance_notice_lead_days, today)
            add("advance_notice_missing", "error" if late else "warning", "advance_notice")
        if duties.plan is True and frame.plan_status not in ("issued", "in_force"):
            add("plan_missing", "error", "plan", status=frame.plan_status)
        if duties.later_works_file is True and frame.later_works_status != "complete":
            add("later_works_file_missing", "warning", "later_works_file", status=frame.later_works_status)
        warn_days = t.item_due_warn_days
        for i in await self.repo.list(HseItem, project_id):
            if i.status in ITEM_DONE:
                continue
            if i.obligation == "mandatory" and i.responsible_user_id is None and not i.responsible_party.strip():
                add("item_without_owner", "warning", str(i.id), title=i.title)
            if i.due_date and i.due_date < today:
                add("item_overdue", "warning", str(i.id), title=i.title, due=i.due_date.isoformat())
            elif i.due_date and warn_days is not None and (i.due_date - today).days <= warn_days:
                add("item_due_soon", "info", str(i.id), title=i.title, due=i.due_date.isoformat())
        missing, _present = await self._unconsolidated(project_id)
        for c in missing:
            add("permit_condition_unconsolidated", "warning", str(c.id), number=c.number)
        summary = await self.linked_summary(project_id, today)
        for incident_id in summary["serious_unlinked_ids"]:
            add("serious_incident_unlinked", "warning", incident_id)
        return {"findings": findings, "duties": _duties_out(duties)}


def _duties_out(d: rules.Duties) -> dict[str, bool | None]:
    return {
        "advance_notice": d.advance_notice,
        "coordinator": d.coordinator,
        "plan": d.plan,
        "later_works_file": d.later_works_file,
        "hazardous_work": d.hazardous_work,
    }


# Frame fields a patch may set back to null (a date or a reference that was entered by mistake).
_NULLABLE_FRAME_FIELDS = frozenset(
    {
        "planned_start",
        "duration_working_days",
        "peak_workers",
        "person_days",
        "employers_count",
        "advance_notice_sent_on",
        "plan_issued_on",
        "plan_document_id",
    }
)
_NON_NULL_ROLE_FIELDS = frozenset({"person_name", "organisation", "status", "qualification", "note"})
