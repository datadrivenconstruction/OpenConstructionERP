# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Plant register service: the one long-lead list of a project and everything hung on it.

Writes:
    pin_catalogue, create_item, update_item, transition_item, sync_item_state
    add_quote, set_basis                        (rules 2, 4)
    set_route                                   (rules 10, 11; OFI through the port)
    create_slot, update_slot, transition_slot, expire_slots      (rule 13)
    create_paper, update_paper, submit_paper, apply_paper_verdict (rule 9)
    put_limits                                   (rule 14)
    create_spare, update_spare, transition_spare (rule 15)
    create_it_service, update_it_service, transition_it_service (rule 18)
    handover                                     (rule 16)
    escalate                                     (rules 7, 13 notifications)

Reads compute every date on the fly (``item_views``): effective lead, need
date, latest order date, float, long-lead. Nothing derived is stored.

Who may write: a holder of ``plant.manage``, or the owner or deputy of the
governance area that hosts plant on the project (``hosting.py``, ``require_editor``).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_log import log_activity
from app.core.events import publish_after_commit
from app.core.fsm import FSMError
from app.modules.plant_register import calc, hosting
from app.modules.plant_register.catalogue import DEFAULT_CATALOGUE_ID, PLANT_KIND, PlantCatalogue, register_plant_kind
from app.modules.plant_register.errors import PlantError, blocked, conflict, forbidden, not_found
from app.modules.plant_register.fsm import IT_FSM, ITEM_FSM, MANUAL_TARGETS, PAPER_FSM, SLOT_FSM, SPARE_FSM
from app.modules.plant_register.hosting import PlantHost
from app.modules.plant_register.models import (
    DecisionPaper,
    DeliveryLimit,
    ItService,
    LeadTimeQuote,
    PlantItem,
    PlantSettings,
    SlotReservation,
    SparePartRequirement,
)
from app.modules.plant_register.ports import (
    CommitmentRef,
    OwnerFurnishedRef,
    PackagePlan,
    commitment_provider,
    package_plan_provider,
)
from app.modules.plant_register.repository import PlantRepository

logger = logging.getLogger(__name__)

MODULE = "plant_register"
PAPER_TARGET_KIND = "plant_decision_paper"
VENDOR_BOUND_REASONS = ("standardisation", "existing_estate", "warranty", "sole_source")
ITEM_FIELDS = (
    "title",
    "description",
    "component_class_code",
    "quantity",
    "unit",
    "tag",
    "wbs_id",
    "boq_position_id",
    "bim_element_ids",
    "cx_system_id",
    "space_ref",
    "performance",
    "redundancy_scheme",
    "maintainability",
    "vendor_policy",
    "vendor_bound_reason",
    "vendor_id",
    "critical_override",
    "critical_reason",
    "need_activity_id",
    "need_date_fixed",
    "order_buffers",
    "purchase_order_id",
    "submittal_id",
    "maintenance_strategy",
    "no_strategic_spare_reason",
    "long_lead_override",
    "long_lead_override_reason",
    "owner_user_id",
)
# Item states that may still change the specification freely.
_OPEN_SPEC = ("identified", "specified", "enquired")
_CLOSED = ("handed_over", "cancelled")
# Refusals that mean the action does not exist for the item in its state: nothing the caller can do about them.
GONE_CODES = (
    "item_closed",
    "specification_frozen",
    "classification_frozen",
    "route_frozen",
    "invalid_transition",
    "state_read_from_source",
    "handover_needs_commissioned",
)
MANUAL_TARGETS_ORDERED = ("specified", "enquired", "route_set", "manufactured", "cancelled")


def item_verdict(refusal: PlantError | None, right: dict[str, Any]) -> dict[str, Any]:
    """One ``can`` entry of an item, from the write's own refusal and the caller's right to edit.

    The action is gone (``applies`` false) when the refusal lies in the state of
    the item. Otherwise a caller without the right reads the code of the right,
    which is what the write answers first, and a caller with it reads the rule.
    """
    if refusal is not None and refusal.code in GONE_CODES:
        return {"applies": False, "allowed": False, "reason": refusal.code, "violations": []}
    if not right["allowed"]:
        return {"applies": True, "allowed": False, "reason": right["reason"], "violations": []}
    if refusal is not None:
        return {"applies": True, "allowed": False, "reason": refusal.code, "violations": refusal.violations}
    return {"applies": True, "allowed": True, "reason": None, "violations": []}


# Overrides of what the catalogue derives; they decide which rules a gate applies.
_SPECIFICATION_FIELDS = ("component_class_code", "performance", "redundancy_scheme", "vendor_policy", "vendor_id")
_CLASSIFICATION_FIELDS = ("critical_override", "critical_reason", "long_lead_override", "long_lead_override_reason")
# Item classes whose delivery limits must be complete before the route is set (rule 14).
_LIMITED_CLASSES = ("main_component", "user_equipment")
# Links the item's state is read from (rule 11).
_SOURCE_LINKS = ("purchase_order_id", "cx_system_id")
PO_ORDERED = ("issued", "partially_received", "completed")
PO_DELIVERED = ("completed",)


def _s(value: Any) -> str | None:
    return str(value) if value is not None else None


def _audit_metadata(extra: dict[str, Any]) -> dict[str, Any] | None:
    """Fold audit extras into the JSON ``metadata`` column of ``log_activity``."""

    def plain(value: Any) -> Any:
        if value is None or isinstance(value, bool | int | str):
            return value
        if isinstance(value, dict):
            return {str(k): plain(v) for k, v in value.items()}
        if isinstance(value, list | tuple | set | frozenset):
            return [plain(v) for v in value]
        return str(value)

    return {k: plain(v) for k, v in extra.items()} or None


def _uuid(value: Any) -> uuid.UUID | None:
    if value is None or value == "":
        return None
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _quote_view(q: LeadTimeQuote) -> calc.QuoteView:
    return calc.QuoteView(
        id=q.id,
        source=q.source,
        enquiry_date=q.enquiry_date,
        response_date=q.response_date,
        lead_weeks_min=q.lead_weeks_min,
        lead_weeks_max=q.lead_weeks_max,
        lead_basis=q.lead_basis,
        is_basis=q.is_basis,
        superseded=q.superseded_by is not None,
    )


class PlantService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = PlantRepository(session)

    # ── plumbing ──────────────────────────────────────────────────────────

    async def _fsm(self, fsm: Any, entity: Any, target: str, actor_id: Any, **meta: Any) -> None:
        try:
            await fsm.apply(
                self.session,
                entity,
                target,
                actor_id=_s(actor_id),
                extra_metadata={"project_id": _s(getattr(entity, "project_id", None)), **meta},
                entity_type=fsm.name,
            )
        except FSMError as exc:
            raise conflict("invalid_transition", detail=str(exc)) from exc

    async def _audit(self, actor_id: Any, entity_type: str, entity_id: Any, action: str, **kw: Any) -> None:
        await log_activity(
            self.session,
            actor_id=_s(actor_id),
            entity_type=entity_type,
            entity_id=_s(entity_id),
            action=action,
            module=MODULE,
            from_status=kw.pop("from_status", None),
            to_status=kw.pop("to_status", None),
            reason=kw.pop("reason", None),
            metadata=_audit_metadata(kw),
        )

    def _publish(self, name: str, data: dict[str, Any]) -> None:
        """Publish ``name`` after commit. Callers write the full event name as a literal:
        the event wiring scan reads the source and cannot see a name built at run time."""
        publish_after_commit(self.session, name, data, source_module=MODULE)

    async def _notify(self, user_id: Any, kind: str, entity_id: Any, ctx: dict[str, Any]) -> None:
        """Best effort, in a savepoint so a failure never poisons the write."""
        if not user_id:
            return
        try:
            from app.modules.notifications.service import NotificationService

            async with self.session.begin_nested():
                await NotificationService(self.session).create(
                    user_id=user_id,
                    notification_type=f"plant_{kind}",
                    title_key=f"notifications.plant.{kind}.title",
                    entity_type="plant_item",
                    entity_id=str(entity_id),
                    body_key=f"notifications.plant.{kind}.body",
                    body_context=ctx,
                    action_url=f"/projects/{ctx.get('project_id')}/plant-register?item={entity_id}",
                    metadata=ctx,
                )
        except Exception:
            logger.warning("plant notification %s skipped", kind, exc_info=True)

    async def _host(self, project_id: uuid.UUID) -> PlantHost:
        """Where the governance model of the project puts plant, read from its catalogue tags."""
        return await hosting.project_host(self.session, project_id) or PlantHost()

    async def _area(self, project_id: uuid.UUID) -> Any:
        """The governance area that hosts plant on this project, or ``None`` when its model tags none."""
        from app.modules.project_governance.public import project_areas

        code = (await self._host(project_id)).area_code
        if code is None:
            return None
        return next((a for a in await project_areas(self.session, project_id) if a.code == code), None)

    async def require_editor(self, project_id: uuid.UUID, user_id: uuid.UUID, *, can_manage: bool) -> None:
        """A holder of ``plant.manage`` (checked by the router), or the equipment area owner or deputy."""
        if can_manage:
            return
        area = await self._area(project_id)
        if area is not None and user_id in (area.owner_user_id, area.deputy_user_id):
            return
        raise forbidden("not_equipment_owner")

    async def capabilities(
        self, project_id: uuid.UUID, user_id: uuid.UUID, *, can_edit: bool, can_manage: bool
    ) -> dict[str, dict[str, Any]]:
        """What this caller may do on the project, each refusal with the code the write would answer.

        ``applies`` says whether the action exists here at all. Editing and
        managing the register exist on every project in every state, so it is
        always true: a caller without the right sees the action disabled with
        the reason, never hidden.
        """
        edit_reason: str | None = None
        if not can_edit:
            edit_reason = "edit_permission_required"
        else:
            try:
                await self.require_editor(project_id, user_id, can_manage=can_manage)
            except PlantError as exc:
                edit_reason = exc.code
        manage_reason = None if can_manage else "manage_required"
        return {
            "edit": {"applies": True, "allowed": edit_reason is None, "reason": edit_reason},
            "manage": {"applies": True, "allowed": manage_reason is None, "reason": manage_reason},
        }

    # ── catalogue ─────────────────────────────────────────────────────────

    async def settings(self, project_id: uuid.UUID) -> PlantSettings | None:
        return await self.repo.settings(project_id)

    async def catalogue(self, project_id: uuid.UUID) -> PlantCatalogue:
        """The pinned catalogue; the shipped neutral one when the project pinned nothing yet."""
        from app.modules.project_governance.catalogue_store import resolve_catalogue
        from app.modules.project_governance.errors import GovernanceError

        register_plant_kind()
        row = await self.repo.settings(project_id)
        source, cid, version = (
            (row.catalogue_source, row.catalogue_id, row.catalogue_version)
            if row
            else ("shipped", DEFAULT_CATALOGUE_ID, None)
        )
        try:
            return await resolve_catalogue(self.session, source, cid, version, kind=PLANT_KIND, from_pin=True)
        except GovernanceError as exc:
            raise not_found("unknown_catalogue") from exc

    async def pin_catalogue(
        self,
        project_id: uuid.UUID,
        *,
        tenant_id: str | None,
        source: str,
        catalogue_id: str,
        version: int | None,
        actor_id: uuid.UUID,
    ) -> PlantSettings:
        """Pin ``(source, id, version)``. A tenant catalogue must belong to ``tenant_id`` and not be retired."""
        from app.modules.project_governance.catalogue_store import CatalogueStore
        from app.modules.project_governance.errors import GovernanceError

        register_plant_kind()
        try:
            pinned = await CatalogueStore(self.session).assert_pinnable(
                tenant_id, source, catalogue_id, version, kind=PLANT_KIND
            )
        except GovernanceError as exc:
            if exc.code == "catalogue_retired":
                raise conflict("catalogue_retired") from exc
            raise not_found("unknown_catalogue") from exc
        row = await self._settings_row(project_id, actor_id)
        row.catalogue_source, row.catalogue_id, row.catalogue_version = source, catalogue_id, pinned
        await self.session.flush()
        await self._audit(
            actor_id, "plant_settings", row.id, "catalogue_pinned", catalogue=f"{source}:{catalogue_id}@{pinned}"
        )
        return row

    async def _settings_row(self, project_id: uuid.UUID, actor_id: uuid.UUID | None) -> PlantSettings:
        """The project's settings row, created with the newest shipped neutral version when it has none.

        A project that never pinned would otherwise follow every newly shipped
        version, and a changed buffer or threshold would move its order dates.
        Two first writers race on the unique project id; the loser reads the
        winner's row.
        """
        row = await self.repo.settings(project_id)
        if row is not None:
            return row
        version = (await self.catalogue(project_id)).version
        try:
            async with self.session.begin_nested():
                row = PlantSettings(
                    project_id=project_id,
                    catalogue_source="shipped",
                    catalogue_id=DEFAULT_CATALOGUE_ID,
                    catalogue_version=version,
                    created_by=actor_id,
                )
                self.session.add(row)
                await self.session.flush()
        except IntegrityError:
            row = await self.repo.settings(project_id)
            if row is None:
                raise
        return row

    # ── items ─────────────────────────────────────────────────────────────

    async def get_item(self, project_id: uuid.UUID, item_id: uuid.UUID, *, lock: bool = False) -> PlantItem:
        item = await self.repo.get_scoped(PlantItem, project_id, item_id, lock=lock)
        if item is None:
            raise not_found("item_not_found")
        return item

    # Soft link field -> (module, model). A project-scoped model is matched on its ``project_id``.
    _PROJECT_LINKS: dict[str, tuple[str, str]] = {
        "purchase_order_id": ("app.modules.procurement.models", "PurchaseOrder"),
        "submittal_id": ("app.modules.submittals.models", "Submittal"),
        "cx_system_id": ("app.modules.commissioning.models", "CxSystem"),
        "wbs_id": ("app.modules.projects.models", "ProjectWBS"),
        "cde_container_id": ("app.modules.cde.models", "DocumentContainer"),
    }
    # Master data shared by the installation (no project column): the row must exist.
    _MASTER_LINKS: dict[str, tuple[str, str]] = {
        "vendor_id": ("app.modules.supplier_catalogs.models", "Vendor"),
        "catalogue_entry_id": ("app.modules.supplier_catalogs.models", "CatalogEntry"),
    }
    _ACTIVITY_LINKS = ("need_activity_id", "needed_from_activity_id")

    async def _link_statement(self, project_id: uuid.UUID, key: str, value: Any) -> Any:
        import importlib

        if key in self._ACTIVITY_LINKS:
            from app.modules.schedule.models import Activity, Schedule

            return (
                select(Activity.id)
                .join(Schedule, Schedule.id == Activity.schedule_id)
                .where(Activity.id == value, Schedule.project_id == project_id)
            )
        if key == "boq_position_id":
            from app.modules.boq.models import BOQ, Position

            return (
                select(Position.id)
                .join(BOQ, BOQ.id == Position.boq_id)
                .where(Position.id == value, BOQ.project_id == project_id)
            )
        if key in self._PROJECT_LINKS:
            path, attr = self._PROJECT_LINKS[key]
            model = getattr(importlib.import_module(path), attr)
            return select(model.id).where(model.id == value, model.project_id == project_id)
        path, attr = self._MASTER_LINKS[key]
        model = getattr(importlib.import_module(path), attr)
        return select(model.id).where(model.id == value)

    async def _check_links(self, project_id: uuid.UUID, data: dict[str, Any]) -> None:
        """Every soft link in ``data`` must resolve, inside this project where the target is project-scoped.

        A foreign, dangling or unverifiable id is 404 ``link_not_found`` with the
        field in ``info``: the answer never says whether the row exists elsewhere.
        A link into a module that is not installed cannot be verified and is
        refused the same way.
        """
        known = {*self._ACTIVITY_LINKS, "boq_position_id", *self._PROJECT_LINKS, *self._MASTER_LINKS}
        for key in sorted(known & set(data)):
            value = data[key]
            if value is None:
                continue
            try:
                stmt = await self._link_statement(project_id, key, value)
            except ImportError as exc:
                raise PlantError("link_not_found", 404, detail=key) from exc
            if (await self.session.execute(stmt.limit(1))).first() is None:
                raise PlantError("link_not_found", 404, detail=key)
        if data.get("owner_user_id") is not None and not await self._has_project_access(
            project_id, data["owner_user_id"]
        ):
            raise PlantError("link_not_found", 404, detail="owner_user_id")

    async def _has_project_access(self, project_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        """Whether ``user_id`` may see the project, by the platform's own access rule."""
        from app.dependencies import verify_project_access

        try:
            await verify_project_access(project_id, str(user_id), self.session)
        except HTTPException:
            return False
        return True

    async def _check_package(self, project_id: uuid.UUID, package_id: uuid.UUID | None) -> None:
        """A contract package id must be in the project's package plan; nobody to ask is a refusal."""
        if package_id is None:
            return
        if package_plan_provider() is None:
            raise PlantError("package_plan_unavailable")
        plan = await self._plan(project_id)
        if plan is None:
            raise PlantError("package_plan_unavailable")
        if plan.package(package_id) is None:
            raise PlantError("package_not_found", 404)

    def _check_item_fields(self, cat: PlantCatalogue, item: PlantItem) -> None:
        cls = cat.component_class(item.component_class_code)
        if cls is None:
            raise PlantError("unknown_component_class")
        item.item_class = cls.item_class
        if item.redundancy_scheme and cat.scheme(item.redundancy_scheme) is None:
            raise PlantError("unknown_redundancy_scheme")
        if item.maintenance_strategy and item.maintenance_strategy not in cat.codes("maintenance_strategies"):
            raise PlantError("unknown_maintenance_strategy")
        if item.vendor_policy not in ("neutral", "bound"):
            raise PlantError("unknown_vendor_policy")
        if item.vendor_policy == "bound":
            if not item.vendor_bound_reason:
                raise PlantError("vendor_bound_needs_reason")
            if item.vendor_bound_reason not in VENDOR_BOUND_REASONS:
                raise PlantError("unknown_vendor_bound_reason")
        elif item.vendor_bound_reason:
            item.vendor_bound_reason = ""
        if item.critical_override is not None and not (item.critical_reason or "").strip():
            raise PlantError("critical_override_needs_reason")
        if item.long_lead_override is not None and not (item.long_lead_override_reason or "").strip():
            raise PlantError("long_lead_override_needs_reason")
        if item.quantity is None or Decimal(item.quantity) <= 0:
            raise PlantError("quantity_not_positive")

    @staticmethod
    def _check_classification_change(data: dict[str, Any], *, can_manage: bool) -> None:
        """Overriding critical or long-lead changes what the gates read: only with ``plant.manage``."""
        if set(data) & set(_CLASSIFICATION_FIELDS) and not can_manage:
            raise forbidden("manage_required")

    async def create_item(
        self, project_id: uuid.UUID, data: dict[str, Any], *, actor_id: uuid.UUID | None, can_manage: bool = False
    ) -> PlantItem:
        self._check_classification_change({k: v for k, v in data.items() if v not in (None, "")}, can_manage=can_manage)
        # Pin first, so the item is judged by the version the project keeps.
        await self._settings_row(project_id, actor_id)
        cat = await self.catalogue(project_id)
        await self._check_links(project_id, data)
        cls = cat.component_class(data.get("component_class_code") or "")
        if cls is None:
            raise PlantError("unknown_component_class")
        item = PlantItem(project_id=project_id, code=data["code"], created_by=actor_id, status="identified")
        for key in ITEM_FIELDS:
            if key in data:
                setattr(item, key, data[key])
        for key, default in (
            ("bim_element_ids", []),
            ("performance", []),
            ("maintainability", {}),
            ("order_buffers", {}),
            ("quantity", Decimal(1)),
            ("unit", "pcs"),
            ("vendor_policy", "neutral"),
            ("vendor_bound_reason", ""),
            ("critical_reason", ""),
            ("long_lead_override_reason", ""),
            ("no_strategic_spare_reason", ""),
            ("description", ""),
            ("tag", ""),
            ("space_ref", ""),
            ("redundancy_scheme", ""),
        ):
            if getattr(item, key, None) is None:
                setattr(item, key, default)
        if not item.maintenance_strategy:
            item.maintenance_strategy = cls.default_maintenance_strategy
        if item.owner_user_id is None:
            item.owner_user_id = actor_id
        self._check_item_fields(cat, item)
        try:
            async with self.session.begin_nested():
                await self.repo.add(item)
        except IntegrityError as exc:
            raise conflict("item_code_taken") from exc
        await self._audit(actor_id, "plant_item", item.id, "created", to_status=item.status)
        self._publish("plant.item.created", {"project_id": str(project_id), "item_id": str(item.id), "code": item.code})
        return item

    async def update_item(
        self,
        project_id: uuid.UUID,
        item_id: uuid.UUID,
        data: dict[str, Any],
        *,
        actor_id: uuid.UUID,
        can_manage: bool = False,
    ) -> PlantItem:
        item = await self.get_item(project_id, item_id, lock=True)
        if refusal := self.edit_refusal(item):
            raise refusal
        changed = {k: v for k, v in data.items() if k in ITEM_FIELDS and getattr(item, k) != v}
        if set(changed) & set(_SPECIFICATION_FIELDS) and (refusal := self.specification_refusal(item)):
            raise refusal
        if set(changed) & set(_CLASSIFICATION_FIELDS) and (
            refusal := self.classification_refusal(item, can_manage=can_manage)
        ):
            raise refusal
        await self._check_links(project_id, changed)
        for key, value in changed.items():
            setattr(item, key, value)
        self._check_item_fields(await self.catalogue(project_id), item)
        await self.session.flush()
        await self._audit(actor_id, "plant_item", item.id, "updated", fields=sorted(changed))
        self._publish("plant.item.updated", {"project_id": str(project_id), "item_id": str(item.id)})
        if set(changed) & set(_SOURCE_LINKS):
            # The state from ``ordered`` on is read from these links (rule 11): read it again now.
            await self._sync(item, actor_id)
        return item

    async def transition_item(
        self, project_id: uuid.UUID, item_id: uuid.UUID, target: str, *, actor_id: uuid.UUID, today: date
    ) -> PlantItem:
        """A transition by hand. ``ordered`` onward is read from its owner (rule 11), except ``manufactured``."""
        if target not in MANUAL_TARGETS:
            raise conflict("state_read_from_source")
        item = await self.get_item(project_id, item_id, lock=True)
        view = None
        if self._transition_reads_rules(item.status, target):
            view = (await self.item_views(project_id, today=today, only=[item.id]))[0]
        if refusal := await self.transition_refusal(project_id, item, view, target):
            raise refusal
        before = item.status
        await self._fsm(ITEM_FSM, item, target, actor_id)
        self._publish(
            "plant.item.state_changed",
            {"project_id": str(project_id), "item_id": str(item.id), "from": before, "to": target},
        )
        return item

    # ── refusals: one function per action, raised by the write and read by ``can`` ──
    #
    # Each answers the error the write would raise for a reason that lies in the
    # item, or ``None``. The writes raise exactly this, and ``item_capabilities``
    # reads the same functions, so what a caller is told and what a write does
    # cannot drift apart.

    @staticmethod
    def edit_refusal(item: PlantItem) -> PlantError | None:
        return conflict("item_closed") if item.status in _CLOSED else None

    @classmethod
    def specification_refusal(cls, item: PlantItem) -> PlantError | None:
        if refusal := cls.edit_refusal(item):
            return refusal
        # After the route is set, the specification is what the package was let on.
        return None if item.status in _OPEN_SPEC else conflict("specification_frozen")

    @classmethod
    def classification_refusal(cls, item: PlantItem, *, can_manage: bool) -> PlantError | None:
        if refusal := cls.edit_refusal(item):
            return refusal
        if not can_manage:
            # Overriding critical or long-lead changes what the gates read.
            return forbidden("manage_required")
        # The route was released on this classification (rules 6 and 9 read it).
        return None if item.status in _OPEN_SPEC else conflict("classification_frozen")

    @staticmethod
    def route_refusal(item: PlantItem) -> PlantError | None:
        return conflict("route_frozen") if calc.is_ordered(item.status) or item.status == "cancelled" else None

    @staticmethod
    def _transition_reads_rules(status: str, target: str) -> bool:
        """Whether ``status -> target`` is a step forward that rules 4, 6, 9, 10 and 14 guard."""
        return (
            ITEM_FSM.has_transition(status, target)
            and target in ("enquired", "route_set")
            and calc.state_rank(target) > calc.state_rank(status)
        )

    async def transition_refusal(
        self, project_id: uuid.UUID, item: PlantItem, view: dict[str, Any] | None, target: str
    ) -> PlantError | None:
        """Why ``target`` cannot be set by hand now. ``view`` is read only for a guarded step forward."""
        if target not in MANUAL_TARGETS:
            return conflict("state_read_from_source")
        if not ITEM_FSM.has_transition(item.status, target):
            return conflict("invalid_transition")
        if self._transition_reads_rules(item.status, target):
            if view is None:
                raise ValueError("a guarded transition needs the item view")
            blockers = await self.transition_blockers(project_id, item, view, target)
            if blockers:
                return blocked(blockers)
        return None

    @staticmethod
    def handover_blockers(item: PlantItem, spares: list[SparePartRequirement], *, critical: bool) -> list[str]:
        """Rules 15 and 16 as far as they lie in the item: open spares, a critical item without a strategic spare."""
        out: list[str] = []
        if any(s.status not in ("handed_over", "waived") for s in spares):
            out.append("spares_not_handed_over")
        if not calc.strategic_spares_ok(critical, (s.category for s in spares), item.no_strategic_spare_reason):
            out.append("critical_without_strategic_spares")
        return out

    @classmethod
    def handover_refusal(
        cls, item: PlantItem, spares: list[SparePartRequirement], *, critical: bool
    ) -> PlantError | None:
        if item.status != "commissioned":
            return conflict("handover_needs_commissioned")
        blockers = cls.handover_blockers(item, spares, critical=critical)
        return blocked(blockers) if blockers else None

    async def item_capabilities(
        self,
        project_id: uuid.UUID,
        views: list[dict[str, Any]],
        user_id: uuid.UUID,
        *,
        can_edit: bool,
        can_manage: bool,
    ) -> list[dict[str, Any]]:
        """Put ``can`` on every item view: what this caller may do with that item, and why not.

        ``applies`` is false when the action does not exist for the item in its
        state (closed, frozen, no such step); the reason is still given. With
        ``applies`` true, ``allowed`` false carries the code the write would
        answer: a missing right first, then a rule the user can still satisfy,
        with every blocking rule in ``violations``.
        """
        if not views:
            return views
        right = (await self.capabilities(project_id, user_id, can_edit=can_edit, can_manage=can_manage))["edit"]
        spares = await self.repo.spares(project_id)
        for view in views:
            item: PlantItem = view["item"]
            mine = [s for s in spares if s.plant_item_id == item.id]
            refusals: dict[str, PlantError | None] = {
                "edit": self.edit_refusal(item),
                "edit_specification": self.specification_refusal(item),
                "edit_classification": self.classification_refusal(item, can_manage=can_manage),
                "set_route": self.route_refusal(item),
                "handover": self.handover_refusal(item, mine, critical=view["critical"]),
            }
            for target in MANUAL_TARGETS_ORDERED:
                refusals[f"transition_{target}"] = await self.transition_refusal(project_id, item, view, target)
            view["can"] = {action: item_verdict(refusal, right) for action, refusal in refusals.items()}
        return views

    async def transition_blockers(
        self, project_id: uuid.UUID, item: PlantItem, view: dict[str, Any], target: str
    ) -> list[str]:
        """Every rule that stops ``target``; empty when it may happen."""
        if target == "enquired":
            # Rule 4: from enquired on, exactly one basis quote.
            return [] if view["basis_quote_id"] else ["basis_quote_required"]
        if target != "route_set":
            return []
        out: list[str] = []
        if not view["basis_quote_id"]:
            out.append("basis_quote_required")
        if view["critical"]:
            if not view["market_evidence"]:
                out.append("critical_without_market_evidence")  # rule 6
            if view["paper_status"] != "approved":
                out.append("critical_without_decision")  # rule 9
            if view["quote_stale"]:
                out.append("lead_time_stale")  # rule 3 at the gate that releases procurement
        if item.item_class in _LIMITED_CLASSES and view["delivery_limit_gaps"]:
            out.append("delivery_limit_gap")  # rule 14
        out += await self.route_findings(project_id, item)  # rule 10
        return out

    # ── route (rules 10, 11) ──────────────────────────────────────────────

    # Three states of the delivery-model port (lead decision 2026-10-11, modules are plugins):
    #   not installed  -> degrade: the route is recorded unchecked, owner-furnished info is "not available",
    #                     never a refusal and never a blocker;
    #   installed, ok  -> rule 10 / 11 apply in full;
    #   installed, the call raised -> ``package_plan_failed``, an error finding and a blocker, like a raising
    #                     governance evidence provider.

    async def _port(self, call: Any) -> Any:
        """Await a port call in a savepoint; any failure becomes ``package_plan_failed`` (422)."""
        try:
            async with self.session.begin_nested():
                return await call
        except PlantError:
            raise
        except Exception as exc:
            logger.exception("plant_register: delivery model port failed")
            raise PlantError("package_plan_failed") from exc

    async def _plan(self, project_id: uuid.UUID) -> PackagePlan | None:
        provider = package_plan_provider()
        return None if provider is None else await self._port(provider.package_plan(self.session, project_id))

    async def _ofi(self, project_id: uuid.UUID, ofi_id: uuid.UUID | None) -> OwnerFurnishedRef | None:
        provider = package_plan_provider()
        if provider is None or ofi_id is None:
            return None
        return await self._port(provider.get_owner_furnished_item(self.session, project_id, ofi_id))

    @staticmethod
    def port_state() -> str:
        """``not_installed`` or ``installed`` (a failing call shows per item as ``package_plan_failed``)."""
        return "not_installed" if package_plan_provider() is None else "installed"

    async def route_findings(self, project_id: uuid.UUID, item: PlantItem) -> list[str]:
        if item.procurement_route is None:
            return ["route_missing"]
        if package_plan_provider() is None:
            return []
        try:
            plan = await self._plan(project_id)
            ofi = await self._ofi(project_id, item.owner_furnished_item_id)
        except PlantError as exc:
            return [exc.code]
        return calc.route_errors(item.procurement_route, item.contract_package_id, ofi, plan)

    async def set_route(
        self,
        project_id: uuid.UUID,
        item_id: uuid.UUID,
        *,
        route: str,
        contract_package_id: uuid.UUID | None,
        actor_id: uuid.UUID,
    ) -> PlantItem:
        """Record the procurement route; an owner-furnished route creates or attaches the OFI (rule 11)."""
        item = await self.get_item(project_id, item_id, lock=True)
        if refusal := self.route_refusal(item):
            raise refusal
        cat = await self.catalogue(project_id)
        if cat.route(route) is None:
            raise PlantError("unknown_route")
        provider = package_plan_provider()
        ofi: OwnerFurnishedRef | None = None
        if provider is None and contract_package_id is not None:
            # The route itself degrades (see above); an id into a plan nobody can read is not stored.
            raise PlantError("package_plan_unavailable")
        if provider is not None:
            plan = await self._plan(project_id)
            if plan is None:
                raise PlantError("package_plan_unavailable")
            if contract_package_id is not None and plan.package(contract_package_id) is None:
                raise PlantError("package_not_found", 404)
            if calc.needs_ofi(route):
                installer = None if route == "owner_furnished_owner_installed" else contract_package_id
                ofi = await self._port(
                    provider.ensure_owner_furnished_item(
                        self.session,
                        project_id,
                        plant_item_id=item.id,
                        title=item.title,
                        installer_package_id=installer,
                        actor_id=actor_id,
                    )
                )
            errors = calc.route_errors(route, contract_package_id, ofi, plan)
            if errors:
                raise blocked(errors)
            if ofi is None and item.owner_furnished_item_id is not None:
                # The route left owner-furnished supply: the delivery model lets its item go too.
                await self._port(
                    provider.release_owner_furnished_item(
                        self.session, project_id, plant_item_id=item.id, actor_id=actor_id
                    )
                )
        # Without the delivery-model module the route is recorded without a package and no OFI exists.
        item.procurement_route = route
        item.contract_package_id = contract_package_id
        item.owner_furnished_item_id = ofi.id if ofi else None
        await self.session.flush()
        await self._audit(actor_id, "plant_item", item.id, "route_set", route=route, package=_s(contract_package_id))
        self._publish("plant.item.updated", {"project_id": str(project_id), "item_id": str(item.id), "route": route})
        return item

    async def sync_item_state(
        self, project_id: uuid.UUID, item_id: uuid.UUID, *, actor_id: uuid.UUID | None
    ) -> PlantItem:
        """Rule 11: read ``ordered`` / ``delivered`` / ``installed`` / ``commissioned`` from their owners."""
        item = await self.get_item(project_id, item_id, lock=True)
        await self._sync(item, actor_id)
        return item

    async def _sync(self, item: PlantItem, actor_id: uuid.UUID | None) -> None:
        """Move the item to the state its sources support, forward or back.

        Only an item between ``route_set`` and ``commissioned`` is read: before
        the route there is nothing to order, and a handover is an act, not a
        reading. A source that went away (order cancelled or unlinked) takes the
        item back to ``route_set``; ``manufactured`` is recorded by hand against
        the order and stands as long as an order supports it.
        """
        if not calc.at_least(item.status, "route_set") or item.status in _CLOSED:
            return
        target = await self._external_target(item.project_id, item) or "route_set"
        if item.status == "manufactured" and target == "ordered":
            return
        if target == item.status:
            return
        before = item.status
        await self._fsm(ITEM_FSM, item, target, actor_id, source="external")
        self._publish(
            "plant.item.state_changed",
            {"project_id": str(item.project_id), "item_id": str(item.id), "from": before, "to": target},
        )

    async def _external_target(self, project_id: uuid.UUID, item: PlantItem) -> str | None:
        best: str | None = None

        def bump(state: str) -> None:
            nonlocal best
            if best is None or calc.state_rank(state) > calc.state_rank(best):
                best = state

        if item.purchase_order_id is not None:
            from app.modules.procurement.models import PurchaseOrder

            po = await self.repo.get_scoped(PurchaseOrder, project_id, item.purchase_order_id)
            if po is not None and po.status in PO_ORDERED:
                bump("delivered" if po.status in PO_DELIVERED else "ordered")
        if item.owner_furnished_item_id is not None:
            ofi = await self._ofi(project_id, item.owner_furnished_item_id)
            if ofi is not None and ofi.progress in ("ordered", "delivered", "installed"):
                bump(ofi.progress)
        # Commissioning reads only what is on site: a delivered order or an installed owner-furnished item.
        if item.cx_system_id is not None and best is not None and calc.at_least(best, "delivered"):
            from app.modules.commissioning.models import CxSystem

            cx = await self.repo.get_scoped(CxSystem, project_id, item.cx_system_id)
            if cx is not None and cx.status == "commissioned":
                bump("commissioned")
        return best

    # ── quotes (rules 2, 3, 4) ────────────────────────────────────────────

    async def add_quote(
        self, project_id: uuid.UUID, item_id: uuid.UUID, data: dict[str, Any], *, actor_id: uuid.UUID, today: date
    ) -> LeadTimeQuote:
        item = await self.get_item(project_id, item_id, lock=True)
        if item.status in ("handed_over", "cancelled"):
            raise conflict("item_closed")
        cat = await self.catalogue(project_id)
        if cat.source(data.get("source") or "") is None:
            raise PlantError("unknown_lead_time_source")
        if data.get("lead_basis", "from_order") not in calc.LEAD_BASES:
            raise PlantError("unknown_lead_basis")
        errors = calc.quote_errors(
            enquiry_date=data.get("enquiry_date"),
            response_date=data.get("response_date"),
            lead_min=int(data.get("lead_weeks_min", 0)),
            lead_max=int(data.get("lead_weeks_max", 0)),
            today=today,
        )
        if errors:
            raise blocked(errors)
        await self._check_links(
            project_id, {k: data.get(k) for k in ("vendor_id", "catalogue_entry_id") if data.get(k) is not None}
        )
        if data.get("source") == "supplier_catalogue":
            if not data.get("catalogue_entry_id"):
                raise PlantError("catalogue_entry_required")
            await self._check_catalogue_lead(
                data["catalogue_entry_id"], int(data["lead_weeks_min"]), int(data["lead_weeks_max"])
            )
        quote = LeadTimeQuote(
            project_id=project_id,
            plant_item_id=item.id,
            source=data["source"],
            vendor_id=data.get("vendor_id"),
            source_name=data.get("source_name") or "",
            enquiry_date=data["enquiry_date"],
            response_date=data.get("response_date"),
            lead_weeks_min=int(data["lead_weeks_min"]),
            lead_weeks_max=int(data["lead_weeks_max"]),
            lead_basis=data.get("lead_basis") or "from_order",
            valid_until=data.get("valid_until"),
            document_ref=data.get("document_ref") or "",
            catalogue_entry_id=data.get("catalogue_entry_id"),
            note=data.get("note") or "",
            is_basis=False,
            created_by=actor_id,
        )
        await self.repo.add(quote)
        current = [q for q in await self.repo.quotes(project_id, item.id) if q.is_basis]
        if data.get("set_basis") or not current:
            await self._make_basis(item, quote, current, actor_id)
        await self._audit(actor_id, "plant_lead_time_quote", quote.id, "created", item=str(item.id))
        return quote

    async def _check_catalogue_lead(self, entry_id: uuid.UUID, lead_min: int, lead_max: int) -> None:
        """A quote sourced from a supplier catalogue entry must carry that entry's lead time.

        The entry holds whole days; the quote holds a range of whole weeks. The
        range has to contain the entry's days rounded up to weeks, otherwise
        the quote claims a source that says something else.
        """
        from app.modules.supplier_catalogs.models import CatalogEntry

        days = (
            await self.session.execute(select(CatalogEntry.lead_time_days).where(CatalogEntry.id == entry_id))
        ).scalar_one_or_none()
        if days is None:
            raise PlantError("link_not_found", 404, detail="catalogue_entry_id")
        weeks = -(-int(days) // 7)
        if not lead_min <= weeks <= lead_max:
            raise PlantError("catalogue_lead_mismatch", detail=f"{days} days")

    async def _make_basis(
        self, item: PlantItem, quote: LeadTimeQuote, current: Iterable[LeadTimeQuote], actor_id: uuid.UUID | None
    ) -> None:
        for old in current:
            if old.id == quote.id:
                continue
            old.is_basis = False
            old.superseded_by = quote.id
        await self.session.flush()
        quote.is_basis = True
        quote.superseded_by = None
        try:
            async with self.session.begin_nested():
                await self.session.flush()
        except IntegrityError as exc:
            raise conflict("concurrent_basis_change") from exc
        self._publish(
            "plant.item.updated",
            {"project_id": str(item.project_id), "item_id": str(item.id), "basis_quote_id": str(quote.id)},
        )

    async def set_basis(
        self, project_id: uuid.UUID, item_id: uuid.UUID, quote_id: uuid.UUID, *, actor_id: uuid.UUID
    ) -> LeadTimeQuote:
        item = await self.get_item(project_id, item_id, lock=True)
        if item.status in _CLOSED:
            raise conflict("item_closed")
        quote = await self.repo.get_scoped(LeadTimeQuote, project_id, quote_id)
        if quote is None or quote.plant_item_id != item.id:
            raise not_found("quote_not_found")
        current = [q for q in await self.repo.quotes(project_id, item.id) if q.is_basis]
        await self._make_basis(item, quote, current, actor_id)
        await self._audit(actor_id, "plant_lead_time_quote", quote.id, "basis_set", item=str(item.id))
        return quote

    # ── slot reservation (rule 13) ────────────────────────────────────────

    _SLOT_FIELDS = (
        "vendor_id",
        "vendor_name",
        "slot_from",
        "slot_to",
        "reservation_fee",
        "currency",
        "fee_refundable",
        "fee_credited_to_order",
        "convert_by_date",
        "terms",
        "commitment_item_id",
        "document_ref",
    )
    _SLOT_NULLABLE = frozenset(
        {"vendor_id", "slot_from", "slot_to", "reservation_fee", "convert_by_date", "commitment_item_id"}
    )

    async def get_slot(
        self, project_id: uuid.UUID, item_id: uuid.UUID, slot_id: uuid.UUID, *, lock: bool = False
    ) -> SlotReservation:
        slot = await self.repo.get_scoped(SlotReservation, project_id, slot_id, lock=lock)
        if slot is None or slot.plant_item_id != item_id:
            raise not_found("slot_not_found")
        return slot

    async def create_slot(
        self, project_id: uuid.UUID, item_id: uuid.UUID, data: dict[str, Any], *, actor_id: uuid.UUID
    ) -> SlotReservation:
        item = await self.get_item(project_id, item_id, lock=True)
        if calc.is_ordered(item.status) or item.status == "cancelled":
            raise conflict("item_already_ordered")
        live = [s for s in await self.repo.slots(project_id, item.id) if s.status in ("requested", "held")]
        if live:
            raise conflict("slot_exists")
        slot = SlotReservation(project_id=project_id, plant_item_id=item.id, created_by=actor_id, status="requested")
        self._apply(slot, data, self._SLOT_FIELDS, self._SLOT_NULLABLE)
        self._check_slot(slot)
        await self._check_slot_links(project_id, data)
        await self.repo.add(slot)
        await self._audit(actor_id, "plant_slot_reservation", slot.id, "created", item=str(item.id))
        return slot

    @staticmethod
    def _apply(row: Any, data: dict[str, Any], fields: Iterable[str], nullable: Iterable[str] = ()) -> None:
        """Copy the sent fields onto the row. A null on a field that cannot be null is refused, not stored."""
        allowed = set(nullable)
        for key in fields:
            if key not in data:
                continue
            value = data[key]
            if value is None and key not in allowed:
                raise PlantError("null_not_allowed", detail=key)
            setattr(row, key, value.strip() if isinstance(value, str) and key != "terms" else value)

    @staticmethod
    def _check_slot(slot: SlotReservation) -> None:
        if slot.fee_refundable and slot.fee_refundable not in ("none", "partial", "full"):
            raise PlantError("unknown_fee_refundable")
        if slot.reservation_fee is not None:
            if Decimal(slot.reservation_fee) < 0:
                raise PlantError("fee_negative")
            if not slot.currency:
                # An amount without a currency is not money.
                raise PlantError("fee_needs_currency")
        if slot.slot_from and slot.slot_to and slot.slot_to < slot.slot_from:
            raise PlantError("slot_range_invalid")

    async def _check_slot_links(self, project_id: uuid.UUID, data: dict[str, Any]) -> None:
        """The vendor must exist; a commitment id is stored only when the commitment module confirms it."""
        await self._check_links(project_id, {"vendor_id": data.get("vendor_id")})
        if data.get("commitment_item_id") is not None:
            provider = commitment_provider()
            if provider is None:
                raise PlantError("commitment_release_unavailable")
            if await self._commitment(provider, project_id, data["commitment_item_id"]) is None:
                raise PlantError("link_not_found", 404, detail="commitment_item_id")

    async def _commitment(
        self, provider: Any, project_id: uuid.UUID, commitment_item_id: uuid.UUID
    ) -> CommitmentRef | None:
        try:
            async with self.session.begin_nested():
                return await provider.get_commitment(self.session, project_id, commitment_item_id)
        except Exception as exc:
            logger.exception("plant_register: commitment port failed")
            raise PlantError("commitment_release_failed") from exc

    async def update_slot(
        self,
        project_id: uuid.UUID,
        item_id: uuid.UUID,
        slot_id: uuid.UUID,
        data: dict[str, Any],
        *,
        actor_id: uuid.UUID,
    ) -> SlotReservation:
        slot = await self.get_slot(project_id, item_id, slot_id, lock=True)
        if slot.status not in ("requested", "held"):
            raise conflict("slot_closed")
        self._apply(slot, data, self._SLOT_FIELDS, self._SLOT_NULLABLE)
        self._check_slot(slot)
        await self._check_slot_links(project_id, data)
        if slot.status == "held":
            # A held slot keeps meeting the terms it was held on, whatever is edited.
            missing = await self.slot_hold_blockers(slot)
            if missing:
                raise blocked(missing)
        await self.session.flush()
        await self._audit(actor_id, "plant_slot_reservation", slot.id, "updated", fields=sorted(data))
        return slot

    async def slot_hold_blockers(self, slot: SlotReservation) -> list[str]:
        """Rule 13: held needs fee, refund terms and a conversion deadline; a fee binds money only through
        a released commitment.

        The commitment is read through the commitment port, never taken on the
        strength of an id. With a fee above zero and nobody to ask, the answer
        is a refusal (``commitment_release_unavailable``).
        """
        out: list[str] = []
        if slot.reservation_fee is None or not slot.fee_refundable or slot.convert_by_date is None:
            out.append("slot_terms_incomplete")
        if slot.reservation_fee is None or Decimal(slot.reservation_fee) <= 0:
            return out
        if not slot.currency:
            out.append("slot_terms_incomplete:currency")
        if slot.commitment_item_id is None:
            return [*out, "slot_fee_needs_commitment"]
        provider = commitment_provider()
        if provider is None:
            return [*out, "commitment_release_unavailable"]
        try:
            ref = await self._commitment(provider, slot.project_id, slot.commitment_item_id)
        except PlantError as exc:
            return [*out, exc.code]
        return [*out, *calc.commitment_errors(ref, slot.plant_item_id, Decimal(slot.reservation_fee), slot.currency)]

    async def transition_slot(
        self, project_id: uuid.UUID, item_id: uuid.UUID, slot_id: uuid.UUID, target: str, *, actor_id: uuid.UUID
    ) -> SlotReservation:
        if target == "expired":
            raise conflict("state_read_from_source")
        slot = await self.get_slot(project_id, item_id, slot_id, lock=True)
        if not SLOT_FSM.has_transition(slot.status, target):
            raise conflict("invalid_transition")
        if target == "held":
            missing = await self.slot_hold_blockers(slot)
            if missing:
                raise blocked(missing)
        await self._fsm(SLOT_FSM, slot, target, actor_id)
        return slot

    async def expire_slots(self, project_id: uuid.UUID | None, *, today: date) -> list[SlotReservation]:
        """Rule 13: every held slot past ``convert_by_date`` expires and its item owner is told."""
        expired: list[SlotReservation] = []
        for slot in await self.repo.held_slots_due(project_id, today):
            if await self.expire_slot(slot, today=today):
                expired.append(slot)
        return expired

    async def expire_slot(self, slot: SlotReservation, *, today: date) -> bool:
        """Expire one held slot whose deadline passed. The transition happens once, so does the notice."""
        if slot.status != "held" or slot.convert_by_date is None or slot.convert_by_date >= today:
            return False
        await self._fsm(SLOT_FSM, slot, "expired", None, reason="convert_by_date passed")
        item = await self.repo.get_scoped(PlantItem, slot.project_id, slot.plant_item_id)
        ctx = {
            "project_id": str(slot.project_id),
            "item_code": getattr(item, "code", ""),
            "convert_by_date": slot.convert_by_date.isoformat(),
        }
        for uid in await self._recipients(slot.project_id, item):
            await self._notify(uid, "slot_expired", slot.plant_item_id, ctx)
        self._publish("plant.slot.expired", {**ctx, "slot_id": str(slot.id), "item_id": str(slot.plant_item_id)})
        return True

    async def _recipients(self, project_id: uuid.UUID, item: PlantItem | None) -> list[uuid.UUID]:
        area = await self._area(project_id)
        out = [getattr(item, "owner_user_id", None), getattr(area, "owner_user_id", None)]
        return list(dict.fromkeys(u for u in out if u))

    # ── decision paper (rule 9) ───────────────────────────────────────────

    async def get_paper(
        self, project_id: uuid.UUID, item_id: uuid.UUID, paper_id: uuid.UUID, *, lock: bool = False
    ) -> DecisionPaper:
        paper = await self.repo.get_scoped(DecisionPaper, project_id, paper_id, lock=lock)
        if paper is None or paper.plant_item_id != item_id:
            raise not_found("paper_not_found")
        return paper

    @staticmethod
    def _check_paper_body(paper: DecisionPaper) -> None:
        codes = [str(o.get("code") or "") for o in paper.options]
        if any(not c for c in codes) or len(set(codes)) != len(codes):
            raise PlantError("paper_option_codes_invalid")
        if paper.recommendation and paper.recommendation not in codes:
            raise PlantError("paper_recommendation_unknown")
        try:
            calc.weighted_scores(paper.options, paper.criteria)
        except (ValueError, ArithmeticError) as exc:
            raise PlantError("paper_scores_invalid") from exc
        if any(o.get("cost") is not None and not o.get("currency") for o in paper.options):
            raise PlantError("cost_needs_currency")

    async def _check_paper_links(self, paper: DecisionPaper) -> None:
        """An option's vendor must exist and its quote must be one of this item's quotes."""
        quotes = {str(q.id) for q in await self.repo.quotes(paper.project_id, paper.plant_item_id)}
        for option in paper.options:
            if option.get("quote_id") is not None and str(option["quote_id"]) not in quotes:
                raise PlantError("link_not_found", 404, detail="options.quote_id")
            if option.get("vendor_id") is not None:
                try:
                    await self._check_links(paper.project_id, {"vendor_id": _uuid(option["vendor_id"])})
                except PlantError as exc:
                    raise PlantError("link_not_found", 404, detail="options.vendor_id") from exc

    async def create_paper(
        self, project_id: uuid.UUID, item_id: uuid.UUID, data: dict[str, Any], *, actor_id: uuid.UUID
    ) -> DecisionPaper:
        item = await self.get_item(project_id, item_id, lock=True)
        if item.status in _CLOSED:
            raise conflict("item_closed")
        papers = await self.repo.papers(project_id, item.id)
        if any(p.status in ("draft", "submitted") for p in papers):
            raise conflict("paper_open")
        latest = papers[-1] if papers else None
        paper = DecisionPaper(
            project_id=project_id,
            plant_item_id=item.id,
            question=data.get("question") or "",
            options=list(data.get("options") or []),
            criteria=list(data.get("criteria") or []),
            recommendation=data.get("recommendation") or "",
            rationale=data.get("rationale") or "",
            supersedes_id=latest.id if latest else None,
            status="draft",
            created_by=actor_id,
        )
        self._check_paper_body(paper)
        await self._check_paper_links(paper)
        await self.repo.add(paper)
        await self._audit(actor_id, "plant_decision_paper", paper.id, "created", item=str(item.id))
        return paper

    async def update_paper(
        self,
        project_id: uuid.UUID,
        item_id: uuid.UUID,
        paper_id: uuid.UUID,
        data: dict[str, Any],
        *,
        actor_id: uuid.UUID,
    ) -> DecisionPaper:
        paper = await self.get_paper(project_id, item_id, paper_id, lock=True)
        if paper.status != "draft":
            raise conflict("paper_not_draft")
        for key in ("question", "options", "criteria", "recommendation", "rationale"):
            if key not in data:
                continue
            if data[key] is None:
                raise PlantError("null_not_allowed", detail=key)
            setattr(paper, key, list(data[key]) if key in ("options", "criteria") else data[key])
        self._check_paper_body(paper)
        await self._check_paper_links(paper)
        await self.session.flush()
        await self._audit(actor_id, "plant_decision_paper", paper.id, "updated", fields=sorted(data))
        return paper

    async def submit_paper(
        self, project_id: uuid.UUID, item_id: uuid.UUID, paper_id: uuid.UUID, *, actor_id: uuid.UUID
    ) -> DecisionPaper:
        from app.modules.approval_routes.schemas import InstanceCreate
        from app.modules.approval_routes.service import ApprovalRouteService

        item = await self.get_item(project_id, item_id)
        paper = await self.get_paper(project_id, item_id, paper_id, lock=True)
        if paper.status != "draft":
            raise conflict("paper_not_draft")
        errors = calc.paper_errors(paper.options, item.vendor_bound_reason)
        if not paper.recommendation:
            errors.append("paper_needs_recommendation")
        if not (paper.rationale or "").strip():
            errors.append("paper_needs_rationale")
        if errors:
            raise blocked(errors)
        svc = ApprovalRouteService(self.session)
        routes = [
            r
            for r in await svc.list_routes(project_id=project_id, target_kind=PAPER_TARGET_KIND, include_inactive=False)
            if r.project_id == project_id
        ]
        if not routes:
            raise PlantError("no_decision_route")
        # Four eyes: whoever submits the paper is not a named approver of its route.
        if any(step.approver_user_id == actor_id for step in await svc.list_steps(routes[0].id)):
            raise blocked(["paper_submitter_is_approver"])
        try:
            instance = await svc.start_instance(
                InstanceCreate(route_id=routes[0].id, target_kind=PAPER_TARGET_KIND, target_id=paper.id),
                started_by=actor_id,
            )
        except HTTPException as exc:
            # The approval engine speaks plain HTTP errors; this API answers with a code.
            raise PlantError("decision_route_refused", exc.status_code, detail=str(exc.detail)) from exc
        paper.approval_instance_id = instance.id
        paper.submitted_by = actor_id
        await self._fsm(PAPER_FSM, paper, "submitted", actor_id, instance=str(instance.id))
        return paper

    async def withdraw_paper(
        self, project_id: uuid.UUID, item_id: uuid.UUID, paper_id: uuid.UUID, *, actor_id: uuid.UUID
    ) -> DecisionPaper:
        """Take a submitted paper back to draft and cancel its approval route.

        When the route already ended (its event never arrived), the paper takes
        the route's verdict instead: a decided paper is never reopened by hand.
        """
        from app.modules.approval_routes.service import ApprovalRouteService

        await self.get_item(project_id, item_id)
        paper = await self.get_paper(project_id, item_id, paper_id, lock=True)
        if paper.status != "submitted":
            raise conflict("paper_not_submitted")
        if await self.reconcile_paper(paper):
            return paper
        if paper.approval_instance_id is not None:
            try:
                await ApprovalRouteService(self.session).cancel_instance(
                    paper.approval_instance_id, actor_id=actor_id, reason="decision paper withdrawn"
                )
            except HTTPException as exc:
                raise PlantError("decision_route_refused", exc.status_code, detail=str(exc.detail)) from exc
        await self._fsm(PAPER_FSM, paper, "draft", actor_id, source="withdrawn")
        return paper

    async def reconcile_paper(self, paper: DecisionPaper) -> bool:
        """Read the verdict of a submitted paper from its approval instance. True when the paper moved.

        The verdict normally arrives as an event. An event that was lost would
        leave the paper ``submitted`` and block every new paper of the item, so
        the periodic job and the withdraw route both read the instance itself.
        """
        from app.modules.approval_routes.models import Instance

        if paper.status != "submitted" or paper.approval_instance_id is None:
            return False
        instance = await self.session.get(Instance, paper.approval_instance_id)
        if instance is None or instance.status not in ("approved", "rejected", "cancelled"):
            return False
        await self.apply_paper_verdict(paper.id, instance.id, decision=instance.status)
        return True

    async def apply_paper_verdict(self, paper_id: uuid.UUID, instance_id: uuid.UUID | None, *, decision: str) -> None:
        """The approval route decided. Acts once, only on the instance the paper started.

        ``decision`` is ``approved``, ``rejected`` or ``cancelled`` (the route
        was cancelled: the paper is a draft again). An approval the submitter
        gave to their own paper is not an approval: the paper goes back to draft.
        """
        paper = await self.session.get(DecisionPaper, paper_id, with_for_update=True)
        if paper is None or paper.status != "submitted":
            return
        if instance_id is not None and paper.approval_instance_id != instance_id:
            return
        if decision == "cancelled":
            await self._fsm(PAPER_FSM, paper, "draft", None, source="approval_route", instance=_s(instance_id))
            return
        target = "approved" if decision == "approved" else "rejected"
        if target == "approved" and await self._self_approved(paper):
            logger.warning("plant_register: paper %s was approved by its submitter, returned to draft", paper.id)
            await self._fsm(PAPER_FSM, paper, "draft", None, source="four_eyes", instance=_s(instance_id))
            return
        if target == "approved":
            scores = calc.weighted_scores(paper.options, paper.criteria)
            paper.snapshot = {
                "question": paper.question,
                "options": paper.options,
                "criteria": paper.criteria,
                "scores": {k: str(v) for k, v in scores.items()},
                "recommendation": paper.recommendation,
                "rationale": paper.rationale,
            }
        paper.decided_at = datetime.now(UTC)
        await self._fsm(PAPER_FSM, paper, target, None, source="approval_route", instance=_s(instance_id))
        if target == "approved":
            self._publish(
                "plant.paper.approved",
                {"project_id": str(paper.project_id), "item_id": str(paper.plant_item_id), "paper_id": str(paper.id)},
            )

    async def _self_approved(self, paper: DecisionPaper) -> bool:
        """Whether the person who submitted the paper is among those who approved it."""
        from app.modules.approval_routes.models import StepState

        if paper.submitted_by is None or paper.approval_instance_id is None:
            return False
        stmt = select(StepState.id).where(
            StepState.instance_id == paper.approval_instance_id,
            StepState.approver_user_id == paper.submitted_by,
            StepState.decision == "approved",
        )
        return (await self.session.execute(stmt.limit(1))).first() is not None

    # ── delivery limits (rule 14) ─────────────────────────────────────────

    async def put_limits(
        self, project_id: uuid.UUID, item_id: uuid.UUID, rows: list[dict[str, Any]], *, actor_id: uuid.UUID
    ) -> list[DeliveryLimit]:
        """Replace the item's delivery-limit row. One party per step (unique), steps from the catalogue."""
        item = await self.get_item(project_id, item_id, lock=True)
        if item.status in _CLOSED:
            raise conflict("item_closed")
        cat = await self.catalogue(project_id)
        steps = set(cat.step_codes())
        parties = cat.codes("parties")
        seen: set[str] = set()
        for r in rows:
            step = r.get("step")
            if step not in steps:
                raise PlantError("unknown_step")
            if step in seen:
                raise conflict("two_parties_on_one_step")
            seen.add(step)
            if not r.get("party") and not r.get("contract_package_id"):
                raise PlantError("limit_needs_party")
            if r.get("party") and r["party"] not in parties:
                raise PlantError("unknown_party")
        for package_id in {_uuid(r.get("contract_package_id")) for r in rows}:
            await self._check_package(project_id, package_id)
        if (
            calc.at_least(item.status, "route_set")
            and item.item_class in _LIMITED_CLASSES
            and calc.delivery_limit_gaps(cat.step_codes(), {r["step"]: True for r in rows})
        ):
            # Rule 14 let the route be set on a complete row; it cannot be taken apart afterwards.
            raise blocked(["delivery_limit_gap"])
        for old in await self.repo.limits(project_id, item.id):
            await self.session.delete(old)
        await self.session.flush()
        out = [
            DeliveryLimit(
                project_id=project_id,
                plant_item_id=item.id,
                step=r["step"],
                party=r.get("party") or "",
                contract_package_id=_uuid(r.get("contract_package_id")),
                note=r.get("note") or "",
            )
            for r in rows
        ]
        self.session.add_all(out)
        await self.session.flush()
        await self._audit(actor_id, "plant_item", item.id, "delivery_limits_set", steps=sorted(seen))
        return out

    # ── spares (rule 15) ──────────────────────────────────────────────────

    _SPARE_FIELDS = ("category", "description", "quantity", "unit", "supply_by", "supply_package_id", "handover_target")
    _SPARE_NULLABLE = frozenset({"supply_package_id"})

    async def get_spare(self, project_id: uuid.UUID, item_id: uuid.UUID, spare_id: uuid.UUID) -> SparePartRequirement:
        row = await self.repo.get_scoped(SparePartRequirement, project_id, spare_id, lock=True)
        if row is None or row.plant_item_id != item_id:
            raise not_found("spare_not_found")
        return row

    async def _spare_item(self, project_id: uuid.UUID, item_id: uuid.UUID) -> PlantItem:
        item = await self.get_item(project_id, item_id, lock=True)
        if item.status in _CLOSED:
            raise conflict("item_closed")
        return item

    async def _check_spare(self, project_id: uuid.UUID, row: SparePartRequirement, data: dict[str, Any]) -> None:
        if "category" in data and data["category"] not in (await self.catalogue(project_id)).codes("spare_categories"):
            raise PlantError("unknown_spare_category")
        if row.quantity is not None and Decimal(row.quantity) <= 0:
            raise PlantError("quantity_not_positive")
        if "supply_package_id" in data:
            await self._check_package(project_id, data["supply_package_id"])

    async def _check_strategic_spares_kept(
        self, project_id: uuid.UUID, item: PlantItem, remaining: Iterable[str]
    ) -> None:
        """Rule 15 holds from ``route_set`` on: the last strategic spare of a critical item stays."""
        if not calc.at_least(item.status, "route_set"):
            return
        cls = (await self.catalogue(project_id)).component_class(item.component_class_code)
        critical = (
            item.critical_override if item.critical_override is not None else bool(cls and cls.critical_by_default)
        )
        if not calc.strategic_spares_ok(critical, remaining, item.no_strategic_spare_reason):
            raise blocked(["critical_without_strategic_spares"])

    async def create_spare(
        self, project_id: uuid.UUID, item_id: uuid.UUID, data: dict[str, Any], *, actor_id: uuid.UUID | None
    ) -> SparePartRequirement:
        item = await self._spare_item(project_id, item_id)
        if "category" not in data:
            raise PlantError("unknown_spare_category")
        row = SparePartRequirement(project_id=project_id, plant_item_id=item.id, status="required")
        self._apply(row, data, self._SPARE_FIELDS, self._SPARE_NULLABLE)
        await self._check_spare(project_id, row, data)
        await self.repo.add(row)
        await self._audit(actor_id, "plant_spare_part", row.id, "created", item=str(item.id))
        return row

    async def update_spare(
        self,
        project_id: uuid.UUID,
        item_id: uuid.UUID,
        spare_id: uuid.UUID,
        data: dict[str, Any],
        *,
        actor_id: uuid.UUID,
    ) -> SparePartRequirement:
        item = await self._spare_item(project_id, item_id)
        row = await self.get_spare(project_id, item_id, spare_id)
        if row.status in ("handed_over", "waived"):
            raise conflict("spare_closed")
        self._apply(row, data, self._SPARE_FIELDS, self._SPARE_NULLABLE)
        await self._check_spare(project_id, row, data)
        if "category" in data:
            others = [s.category for s in await self.repo.spares(project_id, item.id) if s.id != row.id]
            await self._check_strategic_spares_kept(project_id, item, [*others, row.category])
        await self.session.flush()
        await self._audit(actor_id, "plant_spare_part", row.id, "updated", fields=sorted(data))
        return row

    async def transition_spare(
        self,
        project_id: uuid.UUID,
        item_id: uuid.UUID,
        spare_id: uuid.UUID,
        target: str,
        *,
        reason: str,
        actor_id: uuid.UUID,
    ) -> SparePartRequirement:
        row = await self.get_spare(project_id, item_id, spare_id)
        if not SPARE_FSM.has_transition(row.status, target):
            raise conflict("invalid_transition")
        if target == "waived":
            if not (reason or "").strip():
                raise PlantError("waiver_needs_reason")
            row.waiver_reason = reason.strip()
        await self._fsm(SPARE_FSM, row, target, actor_id)
        return row

    async def delete_spare(
        self, project_id: uuid.UUID, item_id: uuid.UUID, spare_id: uuid.UUID, *, actor_id: uuid.UUID
    ) -> None:
        item = await self._spare_item(project_id, item_id)
        row = await self.get_spare(project_id, item_id, spare_id)
        if row.status != "required":
            raise conflict("spare_not_deletable")
        others = [s.category for s in await self.repo.spares(project_id, item.id) if s.id != row.id]
        await self._check_strategic_spares_kept(project_id, item, others)
        await self.session.delete(row)
        await self.session.flush()
        await self._audit(actor_id, "plant_spare_part", spare_id, "deleted")

    # ── IT services (rule 18) ─────────────────────────────────────────────

    _IT_FIELDS = (
        "kind",
        "description",
        "responsible_party",
        "needed_from",
        "needed_until",
        "needed_from_activity_id",
        "access_roles",
        "cde_container_id",
    )
    _IT_NULLABLE = frozenset({"needed_from", "needed_until", "needed_from_activity_id", "cde_container_id"})

    async def get_it_service(self, project_id: uuid.UUID, service_id: uuid.UUID) -> ItService:
        row = await self.repo.get_scoped(ItService, project_id, service_id, lock=True)
        if row is None:
            raise not_found("it_service_not_found")
        return row

    async def create_it_service(self, project_id: uuid.UUID, data: dict[str, Any], *, actor_id: uuid.UUID) -> ItService:
        cat = await self.catalogue(project_id)
        kind = next((k for k in cat.it_service_kinds if k.code == data.get("kind")), None)
        if kind is None:
            raise PlantError("unknown_it_service_kind")
        await self._check_links(project_id, data)
        row = ItService(project_id=project_id, status="planned")
        self._apply(row, data, self._IT_FIELDS, self._IT_NULLABLE)
        # The kind names who provides the service unless the project says otherwise.
        row.responsible_party = row.responsible_party or kind.responsible_party
        self._check_it_service(row)
        await self.repo.add(row)
        await self._audit(actor_id, "plant_it_service", row.id, "created")
        return row

    @staticmethod
    def _check_it_service(row: ItService) -> None:
        if row.needed_from and row.needed_until and row.needed_until < row.needed_from:
            raise PlantError("it_service_range_invalid")

    async def update_it_service(
        self, project_id: uuid.UUID, service_id: uuid.UUID, data: dict[str, Any], *, actor_id: uuid.UUID
    ) -> ItService:
        row = await self.get_it_service(project_id, service_id)
        if "kind" in data and data["kind"] not in (await self.catalogue(project_id)).codes("it_service_kinds"):
            raise PlantError("unknown_it_service_kind")
        if row.status == "retired":
            raise conflict("it_service_retired")
        await self._check_links(project_id, data)
        self._apply(row, data, self._IT_FIELDS, self._IT_NULLABLE)
        self._check_it_service(row)
        if row.status == "provisioned" and row.kind == "cde_access" and row.cde_container_id is None:
            # Rule 18 let it be provisioned on a linked container; the link stays.
            raise blocked(["it_cde_not_linked"])
        await self.session.flush()
        await self._audit(actor_id, "plant_it_service", row.id, "updated", fields=sorted(data))
        return row

    async def transition_it_service(
        self, project_id: uuid.UUID, service_id: uuid.UUID, target: str, *, actor_id: uuid.UUID
    ) -> ItService:
        row = await self.get_it_service(project_id, service_id)
        if not IT_FSM.has_transition(row.status, target):
            raise conflict("invalid_transition")
        if target == "provisioned" and row.kind == "cde_access" and row.cde_container_id is None:
            raise blocked(["it_cde_not_linked"])
        await self._fsm(IT_FSM, row, target, actor_id)
        return row

    async def delete_it_service(self, project_id: uuid.UUID, service_id: uuid.UUID, *, actor_id: uuid.UUID) -> None:
        row = await self.get_it_service(project_id, service_id)
        await self.session.delete(row)
        await self.session.flush()
        await self._audit(actor_id, "plant_it_service", service_id, "deleted")

    # ── handover (rule 16) ────────────────────────────────────────────────

    async def handover(
        self,
        project_id: uuid.UUID,
        item_id: uuid.UUID,
        *,
        confirm: bool,
        service_contract_id: uuid.UUID | None,
        actor_id: uuid.UUID,
        no_asset_reason: str = "",
    ) -> PlantItem:
        """Hand the item over to operation (rule 16).

        The spares are handed over or waived, a critical item has its strategic
        spare (rule 15), and on explicit confirmation the service asset is
        created under the named service contract. Handing over without a
        service asset needs a stated reason, which is kept in the audit trail.
        """
        item = await self.get_item(project_id, item_id, lock=True)
        if item.status != "commissioned":
            raise conflict("handover_needs_commissioned")
        spares = await self.repo.spares(project_id, item.id)
        cls = (await self.catalogue(project_id)).component_class(item.component_class_code)
        critical = (
            item.critical_override if item.critical_override is not None else bool(cls and cls.critical_by_default)
        )
        blockers = self.handover_blockers(item, spares, critical=critical)
        if service_contract_id is None and not (no_asset_reason or "").strip():
            blockers.append("handover_needs_service_asset")
        if blockers:
            raise blocked(blockers)
        if not confirm:
            raise PlantError("handover_needs_confirmation")
        if service_contract_id is not None:
            from app.modules.service.models import ServiceContract
            from app.modules.service.schemas import ServiceAssetCreate
            from app.modules.service.service import ServiceService

            contract = await self.session.get(ServiceContract, service_contract_id)
            if contract is None or getattr(contract, "project_id", None) != project_id:
                raise PlantError("link_not_found", 404, detail="service_contract_id")
            cat = await self.catalogue(project_id)
            cls = cat.component_class(item.component_class_code)
            asset = await ServiceService(self.session).create_asset(
                ServiceAssetCreate(
                    contract_id=service_contract_id,
                    asset_tag=item.tag or None,
                    asset_type=(cls.code if cls else item.component_class_code)[:64],
                    name=item.title[:255],
                    location=item.space_ref or None,
                    metadata={"plant_item_id": str(item.id), "maintenance_strategy": item.maintenance_strategy},
                )
            )
            item.service_asset_id = asset.id
        before = item.status
        await self._fsm(
            ITEM_FSM,
            item,
            "handed_over",
            actor_id,
            service_asset=_s(item.service_asset_id),
            no_asset_reason=(no_asset_reason or "").strip(),
        )
        self._publish(
            "plant.item.state_changed",
            {"project_id": str(project_id), "item_id": str(item.id), "from": before, "to": "handed_over"},
        )
        return item

    # ── computed reads ────────────────────────────────────────────────────

    async def _activities(self, project_id: uuid.UUID, ids: set[uuid.UUID]) -> dict[uuid.UUID, Any]:
        if not ids:
            return {}
        from app.modules.schedule.models import Activity, Schedule

        stmt = (
            select(Activity.id, Activity.late_start, Activity.start_date)
            .join(Schedule, Schedule.id == Activity.schedule_id)
            .where(Activity.id.in_(ids), Schedule.project_id == project_id)
        )
        return {r.id: r for r in (await self.session.execute(stmt)).all()}

    async def _review_days(self, project_id: uuid.UUID, ids: set[uuid.UUID]) -> dict[uuid.UUID, int | None]:
        if not ids:
            return {}
        from app.modules.submittals.models import Submittal

        stmt = select(Submittal.id, Submittal.review_period_days).where(
            Submittal.id.in_(ids), Submittal.project_id == project_id
        )
        return {r.id: r.review_period_days for r in (await self.session.execute(stmt)).all()}

    async def item_views(
        self, project_id: uuid.UUID, *, today: date, only: list[uuid.UUID] | None = None
    ) -> list[dict[str, Any]]:
        """Every item with its derived dates and rule inputs, in code order."""
        cat = await self.catalogue(project_id)
        items = [i for i in await self.repo.items(project_id) if only is None or i.id in only]
        quotes = await self.repo.quotes(project_id)
        papers = await self.repo.papers(project_id)
        slots = await self.repo.slots(project_id)
        limits = await self.repo.limits(project_id)
        spares = await self.repo.spares(project_id)
        acts = await self._activities(project_id, {i.need_activity_id for i in items if i.need_activity_id})
        reviews = await self._review_days(project_id, {i.submittal_id for i in items if i.submittal_id})
        steps = cat.step_codes()
        market = {s.code for s in cat.lead_time_sources if s.market_evidence}
        return [
            self._view(
                i,
                cat,
                today=today,
                quotes=[q for q in quotes if q.plant_item_id == i.id],
                papers=[p for p in papers if p.plant_item_id == i.id],
                slots=[s for s in slots if s.plant_item_id == i.id],
                limits={x.step: (x.party or _s(x.contract_package_id)) for x in limits if x.plant_item_id == i.id},
                spares=[s for s in spares if s.plant_item_id == i.id],
                activity=acts.get(i.need_activity_id) if i.need_activity_id else None,
                review_days=reviews.get(i.submittal_id) if i.submittal_id else None,
                steps=steps,
                market=market,
            )
            for i in items
        ]

    def _view(
        self,
        item: PlantItem,
        cat: PlantCatalogue,
        *,
        today: date,
        quotes: list[LeadTimeQuote],
        papers: list[DecisionPaper],
        slots: list[SlotReservation],
        limits: dict[str, Any],
        spares: list[SparePartRequirement],
        activity: Any,
        review_days: int | None,
        steps: tuple[str, ...],
        market: set[str],
    ) -> dict[str, Any]:
        cls = cat.component_class(item.component_class_code)
        qviews = [_quote_view(q) for q in quotes]
        basis = calc.basis_quote(qviews)
        weeks, lead_source = calc.effective_lead(basis, cls.typical_lead_weeks.max if cls else None)
        need, date_basis = calc.need_date(
            activity_late_start=getattr(activity, "late_start", None),
            activity_start=getattr(activity, "start_date", None),
            fixed=item.need_date_fixed,
        )
        buffers = calc.Buffers.merged(cat.order_buffer_days, item.order_buffers)
        lead_basis = basis.lead_basis if basis else "from_order"
        latest = calc.latest_order_date(need, weeks, lead_basis, buffers, review_period_days=review_days)
        ordered = calc.is_ordered(item.status)
        age = calc.quote_age_days(basis, today)
        max_age = cls.quote_max_age_days if cls else 90
        critical = (
            item.critical_override if item.critical_override is not None else bool(cls and cls.critical_by_default)
        )
        paper = papers[-1] if papers else None
        slot = next((s for s in reversed(slots) if s.status in ("requested", "held")), slots[-1] if slots else None)
        scheme = cat.scheme(item.redundancy_scheme) if item.redundancy_scheme else None
        return {
            "item": item,
            "id": item.id,
            "code": item.code,
            "critical": critical,
            "critical_default": bool(cls and cls.critical_by_default),
            "effective_lead_weeks": weeks,
            "lead_source": lead_source,
            "lead_basis": lead_basis,
            "market_evidence": calc.has_market_evidence(lead_source, market),
            "basis_quote_id": basis.id if basis else None,
            "basis_enquiry_date": basis.enquiry_date if basis else None,
            "basis_count": calc.basis_count(qviews),
            "quote_count": len(quotes),
            "quote_age_days": age,
            "quote_max_age_days": max_age,
            "quote_stale": calc.is_stale(age, max_age),
            "need_date": need,
            "date_basis": date_basis,
            "buffers": buffers,
            "review_period_days": review_days,
            "latest_order_date": latest,
            "float_days": (latest - today).days if latest else None,
            # A cancelled item has no order to place; it is never due or overdue.
            "order_status": calc.order_status(latest, today, ordered or item.status == "cancelled", cat.warn_days),
            "long_lead": calc.is_long_lead(weeks, cat.long_lead_threshold_weeks, item.long_lead_override),
            "long_lead_threshold_weeks": cat.long_lead_threshold_weeks,
            "needs_slot": bool(
                cls
                and cls.needs_slot_reservation_above_weeks is not None
                and weeks is not None
                and weeks > cls.needs_slot_reservation_above_weeks
            ),
            "paper_id": paper.id if paper else None,
            "paper_status": paper.status if paper else None,
            "paper_options": len(paper.options) if paper else 0,
            "slot_id": slot.id if slot else None,
            "slot_status": slot.status if slot else None,
            "slot_convert_by_date": slot.convert_by_date if slot else None,
            "slot_after_order_date": bool(slot and slot.convert_by_date and latest and slot.convert_by_date > latest),
            "delivery_limit_gaps": calc.delivery_limit_gaps(steps, limits),
            "spare_categories": sorted({s.category for s in spares}),
            "strategic_spares_ok": calc.strategic_spares_ok(
                critical, (s.category for s in spares), item.no_strategic_spare_reason
            ),
            "redundancy_ok": calc.redundancy_ok(scheme.min_quantity if scheme else None, Decimal(item.quantity)),
            # not_installed: owner-furnished info is not available (the module is absent), not a defect.
            "delivery_model": self.port_state(),
            "vendor_findings": calc.vendor_findings(item.vendor_policy, item.vendor_bound_reason, item.vendor_id),
        }

    async def long_lead(self, project_id: uuid.UUID, *, today: date) -> list[dict[str, Any]]:
        """Long-lead items with computed dates, least float first (no date last)."""
        views = [
            v
            for v in await self.item_views(project_id, today=today)
            if v["long_lead"] and v["item"].status != "cancelled"
        ]
        return sorted(views, key=lambda v: (v["float_days"] is None, v["float_days"] or 0, v["code"]))

    # ── validation, readiness, escalation ─────────────────────────────────

    async def validation_payload(self, project_id: uuid.UUID, *, today: date) -> dict[str, Any]:
        """The input of rule set ``plant_register`` (see ``validators.py``)."""
        views = [v for v in await self.item_views(project_id, today=today) if v["item"].status != "cancelled"]
        route_findings: dict[str, list[str]] = {}
        for v in views:
            item = v["item"]
            if item.procurement_route is not None:
                route_findings[item.code] = await self.route_findings(project_id, item)
        gate_date = await self._gate_date(project_id)
        slots = [s for s in await self.repo.slots(project_id) if s.status in ("requested", "held")]
        codes = {v["id"]: v["code"] for v in views}
        return {
            "today": today.isoformat(),
            "gate_date": gate_date.isoformat() if gate_date else None,
            "items": [self.view_payload(v) for v in views],
            "route_findings": route_findings,
            "slots": [
                {
                    "item": codes.get(s.plant_item_id, ""),
                    "status": s.status,
                    "terms_blockers": await self.slot_hold_blockers(s) if s.status == "held" else [],
                    "convert_by_date": s.convert_by_date.isoformat() if s.convert_by_date else None,
                }
                for s in slots
                if s.plant_item_id in codes
            ],
            "it_services": [
                {
                    "id": str(r.id),
                    "kind": r.kind,
                    "needed_from": r.needed_from.isoformat() if r.needed_from else None,
                    "cde_container_id": _s(r.cde_container_id),
                    "status": r.status,
                }
                for r in await self.repo.it_services(project_id)
            ],
        }

    @staticmethod
    def view_payload(v: dict[str, Any]) -> dict[str, Any]:
        item: PlantItem = v["item"]
        return {
            "code": item.code,
            "status": item.status,
            "item_class": item.item_class,
            "critical": v["critical"],
            "long_lead": v["long_lead"],
            "procurement_route": item.procurement_route,
            "basis_count": v["basis_count"],
            "quote_count": v["quote_count"],
            "quote_stale": v["quote_stale"],
            "market_evidence": v["market_evidence"],
            "lead_source": v["lead_source"],
            "order_status": v["order_status"],
            "latest_order_date": v["latest_order_date"].isoformat() if v["latest_order_date"] else None,
            "paper_status": v["paper_status"],
            "delivery_limit_gaps": v["delivery_limit_gaps"],
            "strategic_spares_ok": v["strategic_spares_ok"],
            "redundancy_ok": v["redundancy_ok"],
            "vendor_findings": v["vendor_findings"],
            "slot_after_order_date": v["slot_after_order_date"],
        }

    async def _gate_date(self, project_id: uuid.UUID) -> date | None:
        from app.modules.project_governance.public import project_gates

        codes = (await self._host(project_id)).gate_codes
        if not codes:
            return None
        gates = await project_gates(self.session, project_id)
        days = [g.target_date for g in gates if g.code in codes and g.target_date is not None]
        return min(days) if days else None

    async def readiness(self, project_id: uuid.UUID, *, today: date) -> dict[str, Any]:
        """SPEC 7: the readiness of the plant area at the gate that enables construction start, item by item."""
        from app.modules.plant_register.validators import run_rules

        payload = await self.validation_payload(project_id, today=today)
        errors = [r for r in await run_rules(payload, "en") if not r["passed"] and r["severity"] == "error"]
        items = payload["items"]
        critical_open = calc.critical_open(items)
        long_lead_open = calc.long_lead_open(items)
        frame = await self._frame_document(project_id)
        frame_ok = bool(frame is not None and frame.container_id is not None)
        # A project without a phase model has no gate to be ready for and no frame document to attach:
        # the register is then judged on its own items, and the reader is told that no gate is in use.
        gates_in_use = await self.gates_in_use(project_id)
        return {
            "gates_in_use": gates_in_use,
            "ready": not errors and not critical_open and not long_lead_open and (frame_ok or not gates_in_use),
            "error_findings": [{"rule_id": e["rule_id"], "element_ref": e["element_ref"]} for e in errors],
            "critical_open": critical_open,
            "long_lead_open": long_lead_open,
            "frame_document_attached": frame_ok,
            "frame_document_exists": frame is not None,
        }

    async def gates_in_use(self, project_id: uuid.UUID) -> bool:
        """Whether the project pinned a phase model, and so has gates and frame documents at all."""
        from app.modules.project_governance.public import project_controls

        return (await project_controls(self.session, project_id)).has_model

    async def _frame_document(self, project_id: uuid.UUID) -> Any:
        from app.modules.project_governance.public import project_documents

        host = await self._host(project_id)
        if host.area_code is None or not host.document_types:
            return None
        return next(
            (
                d
                for d in await project_documents(self.session, project_id)
                if d.area_code == host.area_code and d.code in host.document_types
            ),
            None,
        )

    async def escalate(self, project_id: uuid.UUID, *, today: date) -> dict[str, Any]:
        """Rules 7 and 13 for one project: notify order dates that are due or overdue, expire slots."""
        overdue: list[str] = []
        due_soon: list[str] = []
        for v in await self.item_views(project_id, today=today):
            status = await self.notify_order_date(v)
            if status == "overdue":
                overdue.append(v["code"])
            elif status == "due_soon":
                due_soon.append(v["code"])
        expired = await self.expire_slots(project_id, today=today)
        return {"overdue": overdue, "due_soon": due_soon, "expired_slots": [str(s.id) for s in expired]}

    async def notify_order_date(self, view: dict[str, Any]) -> str | None:
        """Rule 7: tell the item owner and the area owner that an order date is close or has passed.

        Returns the status notified (``overdue`` / ``due_soon``) or ``None``.
        One notice per person, item and kind per calendar day: the periodic job
        and the manual run may both pass here many times a day.
        """
        return (await self.notify_order_date_once(view))[0]

    async def notify_order_date_once(self, view: dict[str, Any]) -> tuple[str | None, bool]:
        """:meth:`notify_order_date` and whether anybody was told by this call (not told earlier today)."""
        status = view["order_status"]
        if status not in ("overdue", "due_soon"):
            return None, False
        item: PlantItem = view["item"]
        kind = f"order_{status}"
        ctx = {
            "project_id": str(item.project_id),
            "item_code": item.code,
            "latest_order_date": view["latest_order_date"].isoformat(),
        }
        told = False
        for uid in await self._recipients(item.project_id, item):
            if await self._notified_today(uid, kind, item.id):
                continue
            await self._notify(uid, kind, item.id, ctx)
            told = True
        if told:
            data = {**ctx, "item_id": str(item.id)}
            if status == "overdue":
                self._publish("plant.order.overdue", data)
            else:
                self._publish("plant.order.due_soon", data)
        return status, told

    async def _notified_today(self, user_id: uuid.UUID, kind: str, item_id: uuid.UUID) -> bool:
        from app.modules.notifications.models import Notification

        start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        stmt = select(Notification.id).where(
            Notification.user_id == user_id,
            Notification.notification_type == f"plant_{kind}",
            Notification.entity_id == str(item_id),
            Notification.created_at >= start,
        )
        return (await self.session.execute(stmt.limit(1))).first() is not None

    async def frame_summary(self, project_id: uuid.UUID, *, today: date) -> dict[str, Any]:
        """What the governance frame document of the plant area shows."""
        from app.modules.site_logistics.models import SitePlantPosition

        views = [v for v in await self.item_views(project_id, today=today) if v["item"].status != "cancelled"]
        positions = list(
            (
                await self.session.execute(
                    select(SitePlantPosition)
                    .where(SitePlantPosition.project_id == project_id)
                    .order_by(SitePlantPosition.kind)
                )
            ).scalars()
        )
        by_class: dict[str, int] = {}
        by_route: dict[str, int] = {}
        for v in views:
            by_class[v["item"].item_class] = by_class.get(v["item"].item_class, 0) + 1
            key = v["item"].procurement_route or "unset"
            by_route[key] = by_route.get(key, 0) + 1
        settings = await self.repo.settings(project_id)
        return {
            "catalogue": (
                f"{settings.catalogue_source}:{settings.catalogue_id}@{settings.catalogue_version}"
                if settings
                else f"shipped:{DEFAULT_CATALOGUE_ID}"
            ),
            "item_count": len(views),
            "critical_count": sum(1 for v in views if v["critical"]),
            "long_lead_count": sum(1 for v in views if v["long_lead"]),
            "overdue_count": sum(1 for v in views if v["order_status"] == "overdue"),
            "by_item_class": by_class,
            "by_route": by_route,
            "long_lead": [
                {
                    "code": v["code"],
                    "title": v["item"].title,
                    "effective_lead_weeks": v["effective_lead_weeks"],
                    "lead_source": v["lead_source"],
                    "latest_order_date": v["latest_order_date"],
                    "float_days": v["float_days"],
                    "procurement_route": v["item"].procurement_route,
                }
                for v in sorted(views, key=lambda v: (v["float_days"] is None, v["float_days"] or 0))
                if v["long_lead"]
            ],
            "site_plant": [
                {
                    "id": p.id,
                    "kind": p.kind,
                    "name": p.name,
                    "reach_m": p.reach_m,
                    "max_load_t": p.max_load_t,
                    "from_date": p.from_date,
                    "to_date": p.to_date,
                }
                for p in positions
            ],
            "it_services": [
                {"id": r.id, "kind": r.kind, "responsible_party": r.responsible_party, "status": r.status}
                for r in await self.repo.it_services(project_id)
            ],
        }
