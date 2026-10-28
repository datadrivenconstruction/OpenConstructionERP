# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Delivery model service: comparison, decision, risk allocation, package plan, owner-furnished items.

Every write runs in the caller's transaction with its audit entry
(``log_activity``) and its events (``publish_after_commit``).

Approval (lead decision 2): this module PROPOSES. The decision record is the
content of the governance frame document that the project's governance
catalogue tags as hosting the delivery model (``hosting.py``); the governance
act that makes that document binding is the approval. ``sync_with_governance``
copies the approver and the bound revision onto the decision and moves the
model to ``binding``. It is the only writer of ``approved`` and ``binding``,
and it runs from the ``frame_document.state_changed`` subscriber, at the end
of ``propose`` and on every read of the model, so a lost event is caught up.
After that a change of form needs a governance change request (``reopen``);
this module never edits a binding decision.

Readiness for the gate does not require an approved decision (that would
deadlock the gate that approves it): a proposed decision, every risk category
allocated and no error-level finding. The same readiness is checked again at
approval, because allocations and packages stay editable in between.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_log import log_activity
from app.core.events import publish_after_commit
from app.core.fsm import FSMError
from app.modules.delivery_model import hosting, plant, rules
from app.modules.delivery_model.catalogue import (
    DEFAULT_CATALOGUE_ID,
    DELIVERY_FORMS_KIND,
    SHARED_PARTY,
    DeliveryForm,
    DeliveryFormsCatalogue,
    effective_form,
    override_errors,
    register_kinds,
)
from app.modules.delivery_model.errors import DeliveryModelError, conflict, not_found
from app.modules.delivery_model.fsm import EDITABLE, MODEL_FSM, OFI_FSM, PACKAGE_FSM, effective_package_state
from app.modules.delivery_model.models import (
    ContractItem,
    ContractPackage,
    DecisionCriterion,
    DeliveryDecision,
    DeliveryModel,
    DeliveryOption,
    OptionScore,
    OwnerFurnishedItem,
    RiskAllocation,
)
from app.modules.delivery_model.repository import DeliveryModelRepository

logger = logging.getLogger(__name__)

MODULE = "delivery_model"
DECIDED = ("proposed", "approved", "binding")
FROZEN = ("approved", "binding")
PACKAGE_LINKS: dict[str, tuple[str, str]] = {
    "bid_package": ("app.modules.bid_management.models", "BidPackage"),
    "tender_package": ("app.modules.tendering.models", "TenderPackage"),
    "rfq": ("app.modules.rfq_bidding.models", "RFQ"),
    "subcontract_agreement": ("app.modules.subcontractors.models", "SubcontractAgreement"),
    "contract": ("app.modules.contracts.models", "Contract"),
}
OFI_LINKS: dict[str, tuple[str, str]] = {
    "rfq": ("app.modules.rfq_bidding.models", "RFQ"),
    "purchase_order": ("app.modules.procurement.models", "PurchaseOrder"),
    "requisition": ("app.modules.procurement.models", "MaterialRequisition"),
}
# Date column on a linked OFI row that says when the item arrives (rule 11).
_OFI_ARRIVAL = {"purchase_order": "delivery_date", "requisition": "estimated_delivery_date"}
_GO = ("go", "go_with_conditions")
# Weights are stored as Numeric(9, 4); more decimals would be rounded by PostgreSQL and no longer sum to 100.
_WEIGHT_SCALE = 4
# Columns a PATCH may set to null; every other column refuses an explicit null (the schema answers 422).
PACKAGE_NULLABLE = ("parent_id", "price_basis", "need_date")
OFI_NULLABLE = (
    "package_id",
    "need_by_date",
    "expected_delivery_date",
    "enquiry_date",
    "lead_time_days",
    "schedule_activity_id",
    "plant_item_id",
)
# Reason codes ``sync_with_governance`` stores on a proposed decision it could not approve.
BLOCKED_NEEDS_CHANGE_REQUEST = "approval_needs_change_request"
BLOCKED_NOT_READY = "approval_not_ready"
BLOCKED_FOUR_EYES = "four_eyes_proposer_is_approver"
BLOCKED_APPROVER_UNKNOWN = "approver_unknown"


def _s(value: Any) -> str | None:
    return None if value is None else str(value)


def _now() -> datetime:
    return datetime.now(UTC)


def _weight(value: Any) -> Decimal:
    try:
        out = rules.dec(value)
    except (ValueError, InvalidOperation) as exc:
        raise DeliveryModelError("weight_invalid", 422) from exc
    exponent = out.as_tuple().exponent
    if out < 0 or out > 100 or (isinstance(exponent, int) and exponent < -_WEIGHT_SCALE):
        raise DeliveryModelError("weight_invalid", 422)
    return out


def snapshot_hash(snapshot: dict[str, Any]) -> str:
    """SHA-256 of the canonical JSON of a decision snapshot."""
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def record_matches_bound_revision(record_hash: str | None, bound_hash: str | None) -> bool | None:
    """Is the revision governance bound the decision record itself? ``None`` when it cannot be compared.

    Comparable only when both hashes exist: the decision has been approved and
    the bound revision carries a content hash. Equal means the bound file is
    byte for byte the canonical JSON of the snapshot.
    """
    if not record_hash or not bound_hash:
        return None
    return record_hash == bound_hash


def default_pin(country: str | None) -> tuple[str, str, int | None]:
    """The catalogue a new model pins when none was asked for: ``(source, id, version)``.

    Which catalogue a country gets is governance's answer for every catalogue
    kind (active pack, national packs, the one shipped catalogue claiming the
    country). This module has no country rule of its own: when governance names
    none, the neutral catalogue is pinned.
    """
    from app.modules.project_governance.public import default_catalogue_pin

    pin = default_catalogue_pin(DELIVERY_FORMS_KIND, country)
    if pin is None:
        return "shipped", DEFAULT_CATALOGUE_ID, None
    return pin.source, pin.catalogue_id, pin.version


def _model_cls(spec: tuple[str, str]) -> Any:
    import importlib

    return getattr(importlib.import_module(spec[0]), spec[1])


class DeliveryModelService:
    """Orchestrates the delivery model of one project."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = DeliveryModelRepository(session)
        register_kinds()

    # ── infrastructure ─────────────────────────────────────────────────────

    async def _audit(self, actor_id: Any, entity_type: str, entity_id: Any, action: str, **kw: Any) -> None:
        await log_activity(
            self.session,
            actor_id=_s(actor_id),
            entity_type=entity_type,
            entity_id=_s(entity_id),
            action=action,
            module=MODULE,
            **kw,
        )

    def _publish(self, name: str, data: dict[str, Any]) -> None:
        publish_after_commit(self.session, f"{MODULE}.{name}", data, source_module=MODULE)

    async def _fsm(self, fsm: Any, row: Any, target: str, actor_id: Any, **meta: Any) -> None:
        if row.status == target:
            raise conflict("invalid_transition", detail=f"already {target}")
        try:
            await fsm.apply(
                self.session,
                row,
                target,
                actor_id=_s(actor_id),
                extra_metadata={"project_id": _s(row.project_id), **meta},
                entity_type=fsm.name,
            )
        except FSMError as exc:
            raise conflict("invalid_transition", detail=str(exc)) from exc

    async def _project(self, project_id: uuid.UUID) -> Any:
        from app.modules.projects.models import Project

        project = await self.session.get(Project, project_id)
        if project is None:
            raise not_found("project_not_found")
        return project

    async def catalogue_for(self, model: DeliveryModel) -> DeliveryFormsCatalogue:
        from app.modules.project_governance.catalogue_store import resolve_catalogue

        # The triple is the pin this module stored: checked when it was written, readable by every member.
        return await resolve_catalogue(
            self.session,
            model.catalogue_source,
            model.catalogue_id,
            model.catalogue_version,
            kind=DELIVERY_FORMS_KIND,
            from_pin=True,
        )

    async def get_model(self, project_id: uuid.UUID, *, lock: bool = False) -> DeliveryModel | None:
        return await self.repo.get_model(project_id, lock=lock)

    async def require_model(self, project_id: uuid.UUID, *, lock: bool = False) -> DeliveryModel:
        model = await self.repo.get_model(project_id, lock=lock)
        if model is None:
            raise not_found("model_missing")
        return model

    async def _editable(self, project_id: uuid.UUID) -> DeliveryModel:
        model = await self.require_model(project_id, lock=True)
        if model.status not in EDITABLE:
            raise conflict("model_not_editable")
        return model

    async def _pin(self, tenant_id: str | None, source: str, cid: str, version: int | None) -> int:
        from app.modules.project_governance.catalogue_store import CatalogueStore
        from app.modules.project_governance.errors import GovernanceError

        try:
            return await CatalogueStore(self.session).assert_pinnable(
                tenant_id, source, cid, version, kind=DELIVERY_FORMS_KIND
            )
        except GovernanceError as exc:
            raise DeliveryModelError(exc.code, exc.status_code) from exc

    # ── model ──────────────────────────────────────────────────────────────

    async def set_model(
        self,
        project_id: uuid.UUID,
        *,
        actor_id: uuid.UUID,
        tenant_id: str | None,
        catalogue_source: str = "shipped",
        catalogue_id: str | None = None,
        catalogue_version: int | None = None,
    ) -> DeliveryModel:
        """Create the project's model, pin a catalogue and copy its criteria with default weights."""
        project = await self._project(project_id)
        if await self.repo.get_model(project_id) is not None:
            raise conflict("model_exists")
        cid = catalogue_id
        if cid is None:
            catalogue_source, cid, catalogue_version = default_pin(getattr(project, "country_code", None))
        version = await self._pin(tenant_id, catalogue_source, cid, catalogue_version)
        try:
            # A second request that passed the check above loses on the unique constraint: 409, not 500.
            async with self.session.begin_nested():
                model = await self.repo.add(
                    DeliveryModel(
                        project_id=project_id,
                        catalogue_source=catalogue_source,
                        catalogue_id=cid,
                        catalogue_version=version,
                        status="draft",
                        owner_capability={},
                        created_by=actor_id,
                    )
                )
        except IntegrityError as exc:
            raise conflict("model_exists") from exc
        catalogue = await self.catalogue_for(model)
        for i, c in enumerate(catalogue.criteria):
            self.session.add(
                DecisionCriterion(project_id=project_id, code=c.code, weight=Decimal(c.default_weight), sort_order=i)
            )
        await self.session.flush()
        await self._audit(actor_id, "delivery_model", model.id, "model_created", metadata={"catalogue": cid})
        self._publish("model.set", {"project_id": str(project_id), "catalogue_id": cid, "version": version})
        return model

    async def patch_model(
        self,
        project_id: uuid.UUID,
        *,
        actor_id: uuid.UUID,
        underground_risk_sharing: bool | None = None,
        owner_capability: dict[str, Any] | None = None,
    ) -> DeliveryModel:
        model = await self._editable(project_id)
        if underground_risk_sharing is not None:
            model.underground_risk_sharing = underground_risk_sharing
        if owner_capability is not None:
            model.owner_capability = owner_capability
        await self.session.flush()
        await self._audit(actor_id, "delivery_model", model.id, "model_updated")
        return model

    async def change_catalogue(
        self,
        project_id: uuid.UUID,
        *,
        actor_id: uuid.UUID,
        tenant_id: str | None,
        catalogue_source: str,
        catalogue_id: str,
        catalogue_version: int | None,
        form_mapping: dict[str, str],
        category_mapping: dict[str, str],
    ) -> DeliveryModel:
        """SPEC rule 15: re-pin with a code mapping; unmapped allocations become ``unconfirmed``."""
        model = await self._editable(project_id)
        version = await self._pin(tenant_id, catalogue_source, catalogue_id, catalogue_version)
        from app.modules.project_governance.catalogue_store import resolve_catalogue

        new: DeliveryFormsCatalogue = await resolve_catalogue(
            self.session, catalogue_source, catalogue_id, version, kind=DELIVERY_FORMS_KIND, tenant_id=tenant_id
        )
        forms = {f.code for f in new.forms}
        cats = {c.code for c in new.risk_categories}
        options = await self.repo.options(project_id)
        violations = []
        targets: dict[str, str] = {}
        for o in options:
            target = o.form_code if o.form_code in forms else form_mapping.get(o.form_code)
            if target is None:
                violations.append({"code": "form_mapping_missing", "ref": o.form_code})
            elif target not in forms:
                violations.append({"code": "form_mapping_unknown_target", "ref": o.form_code})
            elif target in targets:
                # Two options on one form would break the one-option-per-form constraint at flush.
                violations.append({"code": "form_mapping_collision", "ref": o.form_code, "with": targets[target]})
            else:
                targets[target] = o.form_code
                target_form = new.form(target)
                errs = override_errors(target_form, o.overrides) if target_form is not None else []
                violations += [{"code": "override_invalid", "ref": o.form_code, "info": e} for e in errs]
        selected = model.selected_form_code
        if selected and selected not in forms and form_mapping.get(selected) not in forms:
            violations.append({"code": "form_mapping_missing", "ref": selected})
        for old, target in category_mapping.items():
            if target not in cats:
                violations.append({"code": "category_mapping_unknown_target", "ref": old})
        if violations:
            raise DeliveryModelError(violations[0]["code"], 422, violations=violations)
        for o in options:
            o.form_code = o.form_code if o.form_code in forms else form_mapping[o.form_code]
        for a in await self.repo.allocations(project_id, lock=True):
            if a.category_code in cats:
                continue
            target = category_mapping.get(a.category_code)
            if target and await self.repo.allocation(project_id, target) is None:
                a.category_code = target
            else:
                a.status = "unconfirmed"
        if selected and selected not in forms:
            model.selected_form_code = form_mapping[selected]
        existing = {c.code for c in await self.repo.criteria(project_id)}
        for i, c in enumerate(new.criteria):
            if c.code not in existing:
                self.session.add(
                    DecisionCriterion(project_id=project_id, code=c.code, weight=Decimal("0"), sort_order=100 + i)
                )
        before = f"{model.catalogue_source}:{model.catalogue_id}@{model.catalogue_version}"
        model.catalogue_source, model.catalogue_id, model.catalogue_version = catalogue_source, catalogue_id, version
        await self.session.flush()
        await self._audit(actor_id, "delivery_model", model.id, "catalogue_changed", before_state={"catalogue": before})
        self._publish("model.catalogue_changed", {"project_id": str(project_id), "catalogue_id": catalogue_id})
        return model

    async def model_view(
        self,
        project_id: uuid.UUID,
        *,
        can_edit: bool = False,
        can_manage: bool = False,
        edit_denied: str = "permission_missing",
        actor_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """The model with its carrier document and what the caller may do now (``can``).

        ``edit_denied`` is why the caller may not edit when ``can_edit`` is false,
        as the router's enforcing check words it. ``actor_id`` is the caller:
        whether they may approve by hand depends on who proposed.
        """
        await self.sync_with_governance(project_id)
        model = await self.require_model(project_id)
        catalogue = await self.catalogue_for(model)
        form = await self._form_of(project_id, catalogue, model.selected_form_code)
        doc, why = await hosting.carrier_document(self.session, project_id)
        gates = await hosting.gates_in_use(self.session, project_id)
        blocks = await self._action_blocks(model)
        blocks["approve"] = await self.hand_approval_refusal(model, actor_id)
        current = await self.repo.decision(project_id, model.current_decision_id) if model.current_decision_id else None

        applies = self._action_applies(model.status, await self._approved_decision(project_id) is not None, gates)

        def can(action: str, permitted: bool, denied: str = "permission_missing") -> dict[str, Any]:
            # ``applies`` false: the action does not exist in this state (hide it). True with a reason: the
            # caller lacks a right or a precondition can be fixed (show it disabled with the reason).
            reason = blocks[action] if permitted else denied
            return {"applies": applies[action], "allowed": applies[action] and reason is None, "reason": reason}

        return {
            "id": str(model.id),
            "project_id": str(project_id),
            "catalogue_source": model.catalogue_source,
            "catalogue_id": model.catalogue_id,
            "catalogue_version": model.catalogue_version,
            "selected_form_code": model.selected_form_code,
            "selected_form": _form_view(form) if form else None,
            "status": model.status,
            "underground_risk_sharing": model.underground_risk_sharing,
            "owner_capability": model.owner_capability or {},
            "carrier": {
                "document_id": _s(doc.id) if doc is not None else None,
                "document_type": doc.code if doc is not None else None,
                "document_status": doc.status if doc is not None else None,
                # A project that does not use gates is not missing a frame document.
                "missing_reason": why if gates else None,
            },
            "gates_in_use": gates,
            "change_request_id": _s(model.change_request_id),
            "current_decision_id": _s(model.current_decision_id),
            "approval_blocked_reason": (current.approval_blocked_reason or None) if current is not None else None,
            "can": {
                "edit": can("edit", can_edit, edit_denied),
                "propose": can("propose", can_manage),
                "withdraw": can("withdraw", can_manage),
                "approve": can("approve", can_manage),
                "reopen": can("reopen", can_manage),
                "close_reopening": can("close_reopening", can_manage),
            },
            "version": model.version,
        }

    @staticmethod
    def _action_applies(status: str, has_approved: bool, gates_in_use: bool = True) -> dict[str, bool]:
        """Does the action exist in this state at all? False means there is nothing to show, not a refusal.

        Approval by hand exists only on a project without gates: with gates the
        gate decision approves and nobody does it here.
        """
        return {
            "edit": status in EDITABLE,
            "propose": status in EDITABLE,
            "withdraw": status == "proposed",
            "approve": status == "proposed" and not gates_in_use,
            "reopen": status == "binding",
            "close_reopening": status in ("reopened", "under_evaluation") and has_approved,
        }

    async def _action_blocks(self, model: DeliveryModel) -> dict[str, str | None]:
        """Why each state-changing action is refused now (``None`` = allowed). Enforcement reads the same answer."""
        doc, why = await hosting.carrier_document(self.session, model.project_id)
        gates = await hosting.gates_in_use(self.session, model.project_id)
        approved = await self._approved_decision(model.project_id)
        if model.status == "proposed":
            propose: str | None = "decision_pending"
        elif model.status == "draft":
            # No option yet: the first one moves the model to under_evaluation.
            propose = "single_option_decision"
        elif model.status not in ("under_evaluation", "reopened"):
            propose = "model_not_editable"
        else:
            # With gates the decision needs the frame document that carries it to the gate. Without gates it is
            # approved by hand and needs none.
            propose = why if gates else None
        if model.status != "binding":
            reopen: str | None = "model_not_binding"
        elif not gates:
            # Nothing but a manager's reason reopens it here; the reason is asked for at the write.
            reopen = None
        elif doc is None:
            reopen = why
        else:
            open_cr = await hosting.open_change_request(self.session, model.project_id, doc.id)
            reopen = None if open_cr is not None else "change_request_required"
        closable = model.status in ("reopened", "under_evaluation") and approved is not None
        return {
            "edit": None if model.status in EDITABLE else "model_not_editable",
            "propose": propose,
            "withdraw": None if model.status == "proposed" else "decision_not_pending",
            "reopen": reopen,
            "close_reopening": None if closable else "reopening_not_open",
        }

    async def is_carrier_area_owner(self, project_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        """Is the user owner or deputy of the governance area whose frame document carries the decision?"""
        doc, _ = await hosting.carrier_document(self.session, project_id)
        if doc is None:
            return False
        area = await hosting.area(self.session, project_id, doc.area_id)
        return area is not None and user_id in (area.owner_user_id, area.deputy_user_id)

    async def _form_of(
        self, project_id: uuid.UUID, catalogue: DeliveryFormsCatalogue, form_code: str | None
    ) -> DeliveryForm | None:
        """The catalogue form with the project's option overrides applied (what every rule reads)."""
        form = catalogue.form(form_code)
        if form is None:
            return None
        option = next((o for o in await self.repo.options(project_id) if o.form_code == form_code), None)
        return effective_form(form, option.overrides if option is not None else None)

    async def _form_in_use(
        self, project_id: uuid.UUID, model: DeliveryModel, catalogue: DeliveryFormsCatalogue
    ) -> tuple[str | None, DeliveryForm | None]:
        """The chosen form, or before a proposal the one leading the comparison."""
        code = model.selected_form_code or await self._leading_form(project_id)
        return code, await self._form_of(project_id, catalogue, code)

    # ── options, criteria, scores ──────────────────────────────────────────

    async def add_option(
        self, project_id: uuid.UUID, form_code: str, *, overrides: dict[str, Any], notes: str, actor_id: uuid.UUID
    ) -> DeliveryOption:
        model = await self._editable(project_id)
        catalogue = await self.catalogue_for(model)
        form = catalogue.form(form_code)
        if form is None:
            raise DeliveryModelError("form_unknown", 422)
        self._check_overrides(form, overrides)
        if any(o.form_code == form_code for o in await self.repo.options(project_id)):
            raise conflict("option_exists")
        count = len(await self.repo.options(project_id))
        row = await self.repo.add(
            DeliveryOption(
                project_id=project_id, form_code=form_code, overrides=overrides, notes=notes, sort_order=count
            )
        )
        if model.status == "draft":
            await self._fsm(MODEL_FSM, model, "under_evaluation", actor_id)
        await self._audit(actor_id, "delivery_option", row.id, "option_added", metadata={"form": form_code})
        return row

    async def update_option(self, project_id: uuid.UUID, option_id: uuid.UUID, changes: dict[str, Any], actor_id: Any):
        model = await self._editable(project_id)
        row = await self.repo.option(project_id, option_id)
        if row is None:
            raise not_found("option_not_found")
        if "overrides" in changes:
            form = (await self.catalogue_for(model)).form(row.form_code)
            if form is not None:
                self._check_overrides(form, changes["overrides"])
        for key in ("overrides", "notes", "sort_order"):
            if key in changes:
                setattr(row, key, changes[key])
        await self.session.flush()
        await self._audit(actor_id, "delivery_option", row.id, "option_updated")
        return row

    @staticmethod
    def _check_overrides(form: DeliveryForm, overrides: dict[str, Any] | None) -> None:
        errs = override_errors(form, overrides)
        if errs:
            raise DeliveryModelError(
                "override_invalid", 422, violations=[{"code": "override_invalid", "info": e} for e in errs]
            )

    async def delete_option(self, project_id: uuid.UUID, option_id: uuid.UUID, actor_id: Any) -> None:
        await self._editable(project_id)
        row = await self.repo.option(project_id, option_id)
        if row is None:
            raise not_found("option_not_found")
        await self.session.delete(row)
        await self.session.flush()
        await self._audit(actor_id, "delivery_option", option_id, "option_deleted")

    async def patch_weights(self, project_id: uuid.UUID, weights: dict[str, Any], actor_id: Any) -> list[Any]:
        await self._editable(project_id)
        rows = {c.code: c for c in await self.repo.criteria(project_id)}
        unknown = sorted(set(weights) - set(rows))
        if unknown:
            raise DeliveryModelError("criterion_unknown", 422, detail=", ".join(unknown))
        for code, value in weights.items():
            rows[code].weight = _weight(value)
        await self.session.flush()
        await self._audit(actor_id, "delivery_model", project_id, "weights_updated", metadata={"weights": weights})
        return list(rows.values())

    async def put_scores(self, project_id: uuid.UUID, scores: list[dict[str, Any]], actor_id: Any) -> int:
        await self._editable(project_id)
        options = {o.id for o in await self.repo.options(project_id)}
        criteria = {c.code: c.id for c in await self.repo.criteria(project_id)}
        existing = {(s.option_id, s.criterion_id): s for s in await self.repo.scores(project_id)}
        for s in scores:
            if s["option_id"] not in options:
                raise not_found("option_not_found")
            cid = criteria.get(s["criterion_code"])
            if cid is None:
                raise DeliveryModelError("criterion_unknown", 422, detail=s["criterion_code"])
            row = existing.get((s["option_id"], cid))
            if row is None:
                row = OptionScore(project_id=project_id, option_id=s["option_id"], criterion_id=cid, score=s["score"])
                self.session.add(row)
                existing[(s["option_id"], cid)] = row
            row.score = int(s["score"])
            row.rationale = s.get("rationale") or ""
        await self.session.flush()
        await self._audit(actor_id, "delivery_model", project_id, "scores_updated", metadata={"count": len(scores)})
        return len(scores)

    async def prefill_scores(self, project_id: uuid.UUID, actor_id: Any) -> int:
        """Copy the catalogue's default scores for every option x criterion not yet scored."""
        model = await self._editable(project_id)
        catalogue = await self.catalogue_for(model)
        crit_defaults = {c.code: c.scores for c in catalogue.criteria}
        scored = {(s.option_id, s.criterion_id) for s in await self.repo.scores(project_id)}
        n = 0
        for o in await self.repo.options(project_id):
            for c in await self.repo.criteria(project_id):
                default = (crit_defaults.get(c.code) or {}).get(o.form_code)
                if default and (o.id, c.id) not in scored:
                    self.session.add(
                        OptionScore(project_id=project_id, option_id=o.id, criterion_id=c.id, score=int(default))
                    )
                    n += 1
        await self.session.flush()
        await self._audit(actor_id, "delivery_model", project_id, "scores_prefilled", metadata={"count": n})
        return n

    async def comparison(self, project_id: uuid.UUID) -> dict[str, Any]:
        """Options as columns, criteria as rows, weighted totals computed now (never stored)."""
        model = await self.require_model(project_id)
        catalogue = await self.catalogue_for(model)
        options = await self.repo.options(project_id)
        criteria = await self.repo.criteria(project_id)
        scores = await self.repo.scores(project_id)
        code_of = {c.id: c.code for c in criteria}
        smap = {(str(s.option_id), code_of[s.criterion_id]): s.score for s in scores if s.criterion_id in code_of}
        weights = {c.code: Decimal(c.weight) for c in criteria}
        totals = rules.weighted_totals(weights, [str(o.id) for o in options], smap)
        return {
            "options": [
                {
                    "id": str(o.id),
                    "form_code": o.form_code,
                    "form": _form_view(effective_form(catalogue.form(o.form_code), o.overrides)),
                    "overrides": o.overrides or {},
                    "customised": sorted(o.overrides or {}),
                    "notes": o.notes,
                    "weighted_total": _s(totals.get(str(o.id))),
                }
                for o in options
            ],
            "criteria": [
                {
                    "id": str(c.id),
                    "code": c.code,
                    "weight": str(c.weight),
                    "name_key": next((x.name_key for x in catalogue.criteria if x.code == c.code), None),
                    "rationale_key": next((x.rationale_key for x in catalogue.criteria if x.code == c.code), None),
                }
                for c in criteria
            ],
            "scores": [
                {
                    "option_id": str(s.option_id),
                    "criterion_code": code_of.get(s.criterion_id),
                    "score": s.score,
                    "rationale": s.rationale,
                }
                for s in scores
            ],
            "weights_total": str(sum(weights.values(), Decimal("0"))),
        }

    # ── decision (rules 1, 9, 14) ──────────────────────────────────────────

    async def package_rows(self, project_id: uuid.UUID) -> list[dict[str, Any]]:
        packages = await self.repo.packages(project_id)
        linked = await self._linked_rows(
            [(p.link_kind, p.link_id) for p in packages if p.link_kind and p.link_id], PACKAGE_LINKS
        )
        out = []
        for p in packages:
            row = linked.get((p.link_kind, p.link_id)) if p.link_kind else None
            status = getattr(row, "status", None) if row is not None else None
            out.append(
                {
                    "id": str(p.id),
                    "code": p.code,
                    "title": p.title,
                    "kind": p.kind,
                    "designs": p.designs,
                    "builds": p.builds,
                    "supplies": p.supplies,
                    "manages": p.manages,
                    "party": p.party,
                    "contracting_party": p.contracting_party,
                    "price_basis": p.price_basis,
                    "standard_form": p.standard_form,
                    "parent_id": _s(p.parent_id),
                    "scope": p.scope,
                    "wbs_ref": p.wbs_ref,
                    "boq_ref": p.boq_ref,
                    "need_date": p.need_date,
                    "status": p.status,
                    "effective_status": effective_package_state(p.status, p.link_kind, status),
                    "link": {"kind": p.link_kind, "id": str(p.link_id), "status": status, "missing": row is None}
                    if p.link_kind
                    else None,
                    "linked_contract_type": getattr(row, "contract_type", None) if p.link_kind == "contract" else None,
                }
            )
        return out

    async def _linked_rows(
        self, refs: list[tuple[str, uuid.UUID]], table: dict[str, tuple[str, str]]
    ) -> dict[tuple[str, uuid.UUID], Any]:
        out: dict[tuple[str, uuid.UUID], Any] = {}
        by_kind: dict[str, set[uuid.UUID]] = {}
        for kind, rid in refs:
            by_kind.setdefault(kind, set()).add(rid)
        for kind, ids in by_kind.items():
            if kind not in table:
                continue
            cls = _model_cls(table[kind])
            for row in (await self.session.execute(select(cls).where(cls.id.in_(ids)))).scalars():
                out[(kind, row.id)] = row
        return out

    async def _allocation_rows(self, project_id: uuid.UUID) -> list[dict[str, Any]]:
        return [
            {
                "category_code": a.category_code,
                "party": a.party,
                "basis": a.basis,
                "shares": a.shares or None,
                "rationale": a.rationale,
                "not_applicable": a.not_applicable,
                "status": a.status,
            }
            for a in await self.repo.allocations(project_id)
        ]

    async def propose(
        self,
        project_id: uuid.UUID,
        *,
        option_id: uuid.UUID,
        rationale: str,
        owner_capability: dict[str, Any] | None,
        dispositions: dict[str, str],
        actor_id: uuid.UUID,
    ) -> DeliveryDecision:
        model = await self.require_model(project_id, lock=True)
        blocked = (await self._action_blocks(model))["propose"]
        if blocked:
            raise conflict(blocked)
        cmp = await self.comparison(project_id)
        option_ids = [o["id"] for o in cmp["options"]]
        weights = {c["code"]: Decimal(c["weight"]) for c in cmp["criteria"]}
        scores = {(s["option_id"], s["criterion_code"]): s["score"] for s in cmp["scores"]}
        findings = rules.proposal_findings(option_ids, weights, scores, rationale, str(option_id))
        if findings:
            raise DeliveryModelError(findings[0].code, 422, violations=[f.as_dict() for f in findings])
        chosen = next(o for o in cmp["options"] if o["id"] == str(option_id))
        decisions = await self.repo.decisions(project_id)
        previous = next((d for d in decisions if d.status == "approved"), None)
        # Rule 9: the form the plan was last made under is the approved one, else the last one proposed
        # (a withdrawn proposal still shaped the packages that went out under it).
        in_force = previous.form_code if previous is not None else (decisions[0].form_code if decisions else None)
        packages = await self.package_rows(project_id)
        if in_force is not None and in_force != chosen["form_code"]:
            impacted = [p for p in packages if p["effective_status"] in ("in_procurement", "awarded")]
            missing = [p for p in impacted if p["id"] not in dispositions]
            if missing:
                raise DeliveryModelError(
                    "form_change_impacts_packages",
                    422,
                    violations=[
                        {"code": "disposition_missing", "ref": p["code"], "effective_status": p["effective_status"]}
                        for p in missing
                    ],
                )
        snapshot = {
            "catalogue": f"{model.catalogue_source}:{model.catalogue_id}@{model.catalogue_version}",
            # The form as this project customised it (option overrides applied), not the bare catalogue form.
            "form": chosen["form"],
            "underground_risk_sharing": model.underground_risk_sharing,
            **cmp,
            "allocations": await self._allocation_rows(project_id),
            "packages": packages,
        }
        capability = owner_capability if owner_capability is not None else (model.owner_capability or {})
        decision = await self.repo.add(
            DeliveryDecision(
                project_id=project_id,
                form_code=chosen["form_code"],
                option_id=option_id,
                status="proposed",
                rationale=rationale,
                snapshot=snapshot,
                owner_capability=capability,
                dispositions=dispositions,
                proposed_by=actor_id,
                proposed_at=_now(),
                supersedes_id=previous.id if previous is not None else None,
            )
        )
        model.selected_form_code = chosen["form_code"]
        model.current_decision_id = decision.id
        model.owner_capability = capability
        await self._fsm(MODEL_FSM, model, "proposed", actor_id, decision_id=str(decision.id))
        await self.session.flush()
        await self._audit(
            actor_id, "delivery_decision", decision.id, "decision_proposed", metadata={"form": chosen["form_code"]}
        )
        self._publish(
            "decision.proposed",
            {"project_id": str(project_id), "decision_id": str(decision.id), "form_code": chosen["form_code"]},
        )
        # Catch-up: the carrier may already be binding (a change request approved before this proposal).
        await self._approve_if_bound(model)
        return decision

    async def withdraw(self, project_id: uuid.UUID, actor_id: uuid.UUID) -> DeliveryModel:
        model = await self.require_model(project_id, lock=True)
        blocked = (await self._action_blocks(model))["withdraw"]
        if blocked:
            raise conflict(blocked)
        decision = (
            await self.repo.decision(project_id, model.current_decision_id) if model.current_decision_id else None
        )
        if decision is not None and decision.status == "proposed":
            decision.status = "withdrawn"
            decision.approval_blocked_reason = ""
        approved = await self._approved_decision(project_id)
        # Without an approved decision no form is in force: the withdrawn one must not keep driving the plan.
        model.selected_form_code = approved.form_code if approved else None
        model.current_decision_id = approved.id if approved else None
        await self._fsm(MODEL_FSM, model, "under_evaluation", actor_id)
        await self.session.flush()
        await self._audit(actor_id, "delivery_model", model.id, "decision_withdrawn")
        return model

    async def _approved_decision(self, project_id: uuid.UUID) -> DeliveryDecision | None:
        return next((d for d in await self.repo.decisions(project_id) if d.status == "approved"), None)

    async def reopen(self, project_id: uuid.UUID, actor_id: uuid.UUID, reason: str | None = None) -> DeliveryModel:
        """Binding -> reopened.

        With gates: only while governance has an open change request on the
        carrier document (rule 9). Without gates: by a manager with a reason,
        which is recorded, or an approved decision could never change again.
        """
        model = await self.require_model(project_id, lock=True)
        blocked = (await self._action_blocks(model))["reopen"]
        if blocked:
            raise conflict(blocked)
        if not await hosting.gates_in_use(self.session, project_id):
            why = (reason or "").strip()
            if not why:
                raise DeliveryModelError("reopen_reason_required", 422)
            await self._fsm(MODEL_FSM, model, "reopened", actor_id, reason=why)
            await self._audit(actor_id, "delivery_model", model.id, "model_reopened", metadata={"reason": why})
            return model
        doc, _ = await hosting.carrier_document(self.session, project_id)
        open_cr = await hosting.open_change_request(self.session, project_id, doc.id) if doc is not None else None
        if open_cr is None:
            raise conflict("change_request_required")
        model.change_request_id = open_cr
        await self._fsm(MODEL_FSM, model, "reopened", actor_id, change_request_id=str(open_cr))
        await self._audit(actor_id, "delivery_model", model.id, "model_reopened")
        return model

    async def close_reopening(self, project_id: uuid.UUID, actor_id: uuid.UUID) -> DeliveryModel:
        """Give up a reopening: the model returns to ``binding`` with the approved decision in force."""
        model = await self.require_model(project_id, lock=True)
        blocked = (await self._action_blocks(model))["close_reopening"]
        if blocked:
            raise conflict(blocked)
        await self._return_to_binding(model, actor_id, "reopening_closed")
        return model

    async def _return_to_binding(self, model: DeliveryModel, actor_id: Any, reason: str) -> None:
        """Back to the approved decision: its form, its allocations, no pending proposal."""
        approved = await self._approved_decision(model.project_id)
        if approved is None:
            raise conflict("reopening_not_open")
        current = (
            await self.repo.decision(model.project_id, model.current_decision_id) if model.current_decision_id else None
        )
        if current is not None and current.status == "proposed":
            current.status = "rejected" if reason == "change_request_rejected" else "withdrawn"
            current.approval_blocked_reason = ""
        # Allocations edited during the reopening are not in force: restore the record governance bound.
        frozen = {a["category_code"]: a for a in (approved.snapshot or {}).get("allocations") or []}
        for row in await self.repo.allocations(model.project_id, lock=True):
            was = frozen.get(row.category_code)
            if was is None:
                await self.session.delete(row)
                continue
            row.party, row.basis = was.get("party"), was.get("basis") or "contract"
            row.shares, row.rationale = dict(was.get("shares") or {}), was.get("rationale") or ""
            row.not_applicable = bool(was.get("not_applicable"))
            if row.status != "link_missing":
                row.status = was.get("status") or "confirmed"
        model.selected_form_code = approved.form_code
        model.current_decision_id = approved.id
        model.change_request_id = None
        await self._fsm(MODEL_FSM, model, "binding", actor_id, reason=reason)
        await self.session.flush()
        await self._audit(actor_id, "delivery_model", model.id, "reopening_closed", metadata={"reason": reason})
        self._publish("model.reopening_closed", {"project_id": str(model.project_id), "reason": reason})

    # ── approval mirror (rules 2, 9, 14) ───────────────────────────────────

    async def sync_with_governance(self, project_id: uuid.UUID) -> bool:
        """Bring the model in line with what governance decided since; idempotent, returns whether it changed.

        Two things can have happened without this module hearing of it: the
        carrier document became binding (the proposed decision is approved),
        or the change request that licensed a reopening was rejected (the
        model returns to ``binding``). Called from the governance subscriber,
        at the end of ``propose`` and from the model and decision reads.
        """
        model = await self.repo.get_model(project_id)
        if model is None or model.status not in ("proposed", "reopened", "under_evaluation"):
            return False
        if model.status != "proposed" and model.change_request_id is None:
            return False
        await self.session.refresh(model, with_for_update=True)
        if await self._settle_change_request(model):
            return True
        if model.status == "proposed":
            return await self._approve_if_bound(model)
        return False

    async def mirror_binding(self, project_id: uuid.UUID | None, document_id: uuid.UUID) -> bool:
        """Subscriber entry point: a frame document of the project changed state.

        Which document it was does not matter: the carrier is resolved from the
        project's governance model, and the sync is idempotent.
        """
        if project_id is None:
            return False
        return await self.sync_with_governance(project_id)

    async def _settle_change_request(self, model: DeliveryModel) -> bool:
        """A reopening whose change request was rejected or withdrawn goes back to ``binding``."""
        if model.change_request_id is None:
            return False
        doc, _ = await hosting.carrier_document(self.session, model.project_id)
        if doc is None:
            # The project left the governance model that carried the request: nothing says it was rejected.
            return False
        requests = await hosting.change_requests(self.session, model.project_id, doc.id)
        cr = next((r for r in requests if r.id == model.change_request_id), None)
        if cr is not None and cr.status in ("submitted", "approved"):
            return False
        await self._return_to_binding(model, cr.decided_by if cr is not None else None, "change_request_rejected")
        return True

    async def _approving_act(
        self, model: DeliveryModel, decision: DeliveryDecision, doc: Any
    ) -> tuple[Any, datetime | None, str, Any] | None:
        """The governance act that bound the carrier for THIS proposal: ``(approver, at, source, ref)``.

        An act counts when it was decided after the proposal, or when it is the
        approved change request that licensed the reopening this proposal came
        out of. An older gate decision bound an earlier record, not this one.
        """
        proposed_at = decision.proposed_at
        approved = [
            r
            for r in await hosting.change_requests(self.session, model.project_id, doc.id)
            if r.status == "approved" and r.decided_at
        ]
        for cr in sorted(approved, key=lambda r: r.decided_at, reverse=True):
            after = bool(proposed_at and cr.decided_at >= proposed_at)
            if after or cr.id == model.change_request_id:
                return cr.decided_by, cr.decided_at if after else None, "change_request", cr.id
        if doc.approved_gate_id is not None:
            gd = await hosting.latest_gate_decision(self.session, model.project_id, doc.approved_gate_id, _GO)
            if gd is not None and gd.decided_at and proposed_at and gd.decided_at >= proposed_at:
                return gd.decided_by, gd.decided_at, "gate", gd.id
        return None

    async def _blocked(self, decision: DeliveryDecision, reason: str) -> bool:
        """Record why a bound carrier did not approve the decision; written once per reason."""
        if (decision.approval_blocked_reason or "") == reason:
            return False
        decision.approval_blocked_reason = reason
        await self.session.flush()
        if reason:
            await self._audit(
                None, "delivery_decision", decision.id, "decision_approval_blocked", metadata={"reason": reason}
            )
        return True

    async def _approve_if_bound(self, model: DeliveryModel) -> bool:
        """Approve the proposed decision if the carrier document is binding for it; else say why not."""
        if model.status != "proposed" or model.current_decision_id is None:
            return False
        decision = await self.repo.decision(model.project_id, model.current_decision_id)
        if decision is None or decision.status != "proposed":
            return False
        doc, _ = await hosting.carrier_document(self.session, model.project_id)
        if doc is None or doc.status != "binding":
            return await self._blocked(decision, "")
        act = await self._approving_act(model, decision, doc)
        if act is None:
            return await self._blocked(decision, BLOCKED_NEEDS_CHANGE_REQUEST)
        approver, at, source, ref = act
        # Allocations and packages stay editable while proposed: the gate's evidence may be stale by now.
        if not (await self.readiness(model.project_id))["met"]:
            return await self._blocked(decision, BLOCKED_NOT_READY)
        four_eyes = await self._four_eyes(model.project_id)
        if four_eyes and approver is None:
            return await self._blocked(decision, BLOCKED_APPROVER_UNKNOWN)
        if four_eyes and approver == decision.proposed_by:
            return await self._blocked(decision, BLOCKED_FOUR_EYES)
        await self._approve(model, decision, approver=approver, at=at, source=source, ref=ref, doc=doc)
        return True

    async def hand_approval_refusal(self, model: DeliveryModel, actor_id: uuid.UUID | None) -> str | None:
        """Why this person cannot approve the proposed decision by hand now (``None`` = they can).

        The same checks the gate's approval runs: the model has no open error,
        and under four-eyes whoever proposed does not approve. The view and the
        write both ask here.
        """
        if await hosting.gates_in_use(self.session, model.project_id):
            return "approved_by_gate_decision"
        decision = (
            await self.repo.decision(model.project_id, model.current_decision_id) if model.current_decision_id else None
        )
        if model.status != "proposed" or decision is None or decision.status != "proposed":
            return "decision_not_proposed"
        if await self._four_eyes(model.project_id) and actor_id is not None and decision.proposed_by == actor_id:
            return BLOCKED_FOUR_EYES
        if not (await self.readiness(model.project_id))["met"]:
            return BLOCKED_NOT_READY
        return None

    async def approve_by_hand(self, project_id: uuid.UUID, actor_id: uuid.UUID) -> DeliveryModel:
        """Approve the proposed decision on a project that has no gates to approve it."""
        model = await self.require_model(project_id, lock=True)
        refusal = await self.hand_approval_refusal(model, actor_id)
        if refusal:
            raise conflict(refusal)
        decision = await self.repo.decision(project_id, model.current_decision_id)
        await self._approve(model, decision, approver=actor_id, at=None, source="hand", ref=None, doc=None)
        return model

    async def _approve(
        self,
        model: DeliveryModel,
        decision: DeliveryDecision,
        *,
        approver: Any,
        at: datetime | None,
        source: str,
        ref: Any,
        doc: Any | None,
    ) -> None:
        """Make the proposed decision the one in force. ``doc`` is the bound frame document, ``None`` by hand."""
        four_eyes = await self._four_eyes(model.project_id)
        for old in await self.repo.decisions(model.project_id):
            if old.status == "approved" and old.id != decision.id:
                old.status = "superseded"
        # Rule 14: the snapshot is completed at approval (allocations and packages as they stand), then frozen.
        frozen = {
            **(decision.snapshot or {}),
            "allocations": await self._allocation_rows(model.project_id),
            "packages": await self.package_rows(model.project_id),
        }
        decision.snapshot, decision.snapshot_hash = frozen, snapshot_hash(frozen)
        decision.status = "approved"
        decision.approved_by, decision.approved_at = approver, at or _now()
        decision.approval_source, decision.governance_ref_id = source, ref
        if doc is not None:
            decision.governance_document_id = doc.id
            decision.bound_revision_id = doc.bound_revision_id
            # The hash governance recorded when it bound the revision, not the revision's hash today.
            decision.bound_content_hash = doc.bound_content_hash
        decision.four_eyes, decision.approval_blocked_reason = four_eyes, ""
        model.change_request_id = None
        await self._fsm(MODEL_FSM, model, "approved", approver, decision_id=str(decision.id))
        await self._fsm(MODEL_FSM, model, "binding", approver, decision_id=str(decision.id))
        await self.session.flush()
        await self._audit(approver, "delivery_decision", decision.id, "decision_approved", metadata={"source": source})
        self._publish(
            "decision.approved",
            {"project_id": str(model.project_id), "decision_id": str(decision.id), "form_code": decision.form_code},
        )

    async def decision_views(self, project_id: uuid.UUID) -> list[dict[str, Any]]:
        await self.sync_with_governance(project_id)
        model = await self.get_model(project_id)
        return [_decision_view(d, model) for d in await self.repo.decisions(project_id)]

    async def _four_eyes(self, project_id: uuid.UUID) -> bool:
        return await hosting.four_eyes(self.session, project_id)

    # ── risk allocation (rules 3 to 6, 12, 13) ─────────────────────────────

    async def allocation_matrix(self, project_id: uuid.UUID) -> dict[str, Any]:
        model = await self.require_model(project_id)
        catalogue = await self.catalogue_for(model)
        form, form_obj = await self._form_in_use(project_id, model, catalogue)
        rows = {a.category_code: a for a in await self.repo.allocations(project_id)}
        findings = rules.allocation_findings(catalogue, form, await self._allocation_rows(project_id), form=form_obj)
        by_cat: dict[str, list[dict[str, Any]]] = {}
        for f in findings:
            by_cat.setdefault(f.ref, []).append(f.as_dict())
        items = []
        for c in catalogue.risk_categories:
            a = rows.get(c.code)
            d = catalogue.default_for(form, c.code)
            items.append(
                {
                    "category_code": c.code,
                    "name_key": c.name_key,
                    "description_key": c.description_key,
                    "register_category": c.register_category,
                    "allocation": _allocation_view(a) if a else None,
                    "default": {
                        "party": d.party,
                        "basis": d.basis,
                        "shares": d.shares,
                        "rationale_key": d.rationale_key,
                        "source_url": d.source_url,
                        "review_status": str(d.review_status),
                    }
                    if d
                    else None,
                    "findings": by_cat.get(c.code, []),
                }
            )
        orphans = [_allocation_view(a) for code, a in rows.items() if catalogue.category(code) is None]
        return {
            "form_code": form,
            "parties": [
                {"code": p.code, "name_key": p.name_key, "contract_party_role": p.contract_party_role}
                for p in catalogue.parties
            ],
            "items": items,
            "orphans": orphans,
            "total": len(items),
            "offset": 0,
            "limit": len(items),
        }

    async def _leading_form(self, project_id: uuid.UUID) -> str | None:
        cmp = await self.comparison(project_id)
        ranked = sorted(
            (o for o in cmp["options"] if o["weighted_total"] is not None),
            key=lambda o: Decimal(o["weighted_total"]),
            reverse=True,
        )
        return ranked[0]["form_code"] if ranked else None

    async def put_allocation(self, project_id: uuid.UUID, category: str, data: dict[str, Any], actor_id: Any) -> Any:
        model = await self.require_model(project_id, lock=True)
        if model.status in FROZEN:
            raise conflict("model_not_editable")
        catalogue = await self.catalogue_for(model)
        if catalogue.category(category) is None:
            raise not_found("category_unknown")
        party = data.get("party")
        parties = {p.code for p in catalogue.parties}
        if party is not None and party not in parties:
            raise DeliveryModelError("party_unknown", 422)
        shares = data.get("shares") or {}
        if party == SHARED_PARTY or shares:
            from app.modules.delivery_model.catalogue import share_errors

            errs = share_errors(party or "", shares, parties)
            if errs:
                raise DeliveryModelError("shared_risk_not_100" if errs == ["shares_not_100"] else errs[0], 422)
        if data.get("not_applicable") and not (data.get("rationale") or "").strip():
            raise DeliveryModelError("not_applicable_needs_rationale", 422)
        row = await self.repo.allocation(project_id, category, lock=True)
        if row is None:
            row = RiskAllocation(project_id=project_id, category_code=category, shares={}, risk_item_ids=[])
            self.session.add(row)
        # The same form the matrix shows defaults for: the chosen one, or before a proposal the leading one.
        default = catalogue.default_for((await self._form_in_use(project_id, model, catalogue))[0], category)
        row.party = None if data.get("not_applicable") else party
        row.basis = data.get("basis") or "contract"
        row.shares = shares if party == SHARED_PARTY else {}
        row.rationale = data.get("rationale") or ""
        row.not_applicable = bool(data.get("not_applicable"))
        row.source = (
            "catalogue_default"
            if default is not None and default.party == row.party and default.basis == row.basis
            else "edited"
        )
        if row.status != "link_missing":
            row.status = "unconfirmed"
        row.confirmed_by = row.confirmed_at = None
        await self.session.flush()
        await self._audit(actor_id, "delivery_allocation", row.id, "allocation_set", metadata={"category": category})
        return row

    async def confirm_allocations(
        self, project_id: uuid.UUID, categories: list[str] | None, actor_id: uuid.UUID
    ) -> list[RiskAllocation]:
        """Confirm allocations; a category with no row takes the catalogue default (human confirms, rule 7 of the platform)."""
        model = await self.require_model(project_id, lock=True)
        if model.status in FROZEN:
            raise conflict("model_not_editable")
        catalogue = await self.catalogue_for(model)
        form = model.selected_form_code or await self._leading_form(project_id)
        wanted = categories or [c.code for c in catalogue.risk_categories]
        out = []
        for code in wanted:
            if catalogue.category(code) is None:
                raise not_found("category_unknown")
            row = await self.repo.allocation(project_id, code, lock=True)
            if row is None:
                d = catalogue.default_for(form, code)
                if d is None:
                    continue
                row = RiskAllocation(
                    project_id=project_id,
                    category_code=code,
                    party=d.party,
                    basis=d.basis,
                    shares=dict(d.shares or {}),
                    rationale="",
                    source="catalogue_default",
                    risk_item_ids=[],
                )
                self.session.add(row)
            if not row.party and not row.not_applicable:
                continue
            # An explicit confirm also acknowledges a deleted register entry (rule 13): the row can be seeded again.
            row.status = "confirmed"
            row.confirmed_by, row.confirmed_at = actor_id, _now()
            out.append(row)
        await self.session.flush()
        await self._audit(actor_id, "delivery_model", model.id, "allocations_confirmed", metadata={"count": len(out)})
        return out

    async def seed_risks(
        self, project_id: uuid.UUID, categories: list[str] | None, *, preview: bool, actor_id: uuid.UUID, locale: str
    ) -> list[dict[str, Any]]:
        """Rule 12: one register entry per confirmed allocation without a link; idempotent on the allocation id."""
        from app.modules.delivery_model.messages import translate
        from app.modules.risk.models import RiskItem
        from app.modules.risk.schemas import RiskCreate
        from app.modules.risk.service import RiskService

        model = await self.require_model(project_id)
        catalogue = await self.catalogue_for(model)
        out: list[dict[str, Any]] = []
        stamped = {}
        if not preview:
            # A register row already stamped with an allocation (a lost link write) is relinked, not duplicated.
            for r in (await self.session.execute(select(RiskItem).where(RiskItem.project_id == project_id))).scalars():
                aid = (r.metadata_ or {}).get("delivery_model_allocation_id")
                if aid:
                    stamped[aid] = r
        for a in await self.repo.allocations(project_id, lock=not preview):
            if categories and a.category_code not in categories:
                continue
            cat = catalogue.category(a.category_code)
            if cat is None or a.status != "confirmed" or a.not_applicable or a.risk_item_ids:
                continue
            title = translate(cat.name_key, locale=locale)
            entry = {
                "category_code": a.category_code,
                "register_category": cat.register_category,
                "title": title,
                "party": a.party,
            }
            if preview:
                out.append({**entry, "risk_id": None})
                continue
            found = stamped.get(str(a.id))
            if found is None:
                found = await RiskService(self.session).create_risk(
                    RiskCreate(
                        project_id=project_id,
                        title=title[:255],
                        description=translate(cat.description_key, locale=locale) if cat.description_key else "",
                        category=cat.register_category,
                        metadata={
                            "delivery_model_allocation_id": str(a.id),
                            "delivery_model_category": a.category_code,
                            "allocated_party": a.party,
                        },
                    ),
                    user_id=str(actor_id),
                )
            a.risk_item_ids = [str(found.id)]
            out.append({**entry, "risk_id": str(found.id)})
        if not preview:
            await self.session.flush()
            await self._audit(actor_id, "delivery_model", model.id, "risks_seeded", metadata={"count": len(out)})
        return out

    async def risk_deleted(self, project_id: uuid.UUID, risk_id: str) -> int:
        """Rule 13: drop the soft link and flag the allocation; never recreate."""
        n = 0
        for a in await self.repo.allocations(project_id, lock=True):
            if risk_id in (a.risk_item_ids or []):
                a.risk_item_ids = [r for r in a.risk_item_ids if r != risk_id]
                a.status = "link_missing"
                n += 1
        if n:
            await self.session.flush()
            await self._audit(None, "delivery_model", project_id, "risk_link_missing", metadata={"risk_id": risk_id})
        return n

    # ── packages (rules 7, 8, 16) ──────────────────────────────────────────

    async def _check_parent(self, project_id: uuid.UUID, parent_id: uuid.UUID | None, own_id: Any = None) -> None:
        if parent_id is None:
            return
        packages = await self.repo.packages(project_id)
        if parent_id == own_id or all(p.id != parent_id for p in packages):
            raise DeliveryModelError("parent_invalid", 422)
        if own_id is not None:
            parents = {str(p.id): p.parent_id for p in packages}
            parents[str(own_id)] = parent_id
            if rules.parent_cycle(str(own_id), parents):
                raise DeliveryModelError("parent_invalid", 422)

    async def create_package(self, project_id: uuid.UUID, data: dict[str, Any], actor_id: Any) -> ContractPackage:
        # The model row is the lock every writer of the plan takes: a double submit waits, then sees the code.
        model = await self.require_model(project_id, lock=True)
        catalogue = await self.catalogue_for(model)
        if data.get("party") not in {p.code for p in catalogue.parties}:
            raise DeliveryModelError("party_unknown", 422)
        if any(p.code == data["code"] for p in await self.repo.packages(project_id)):
            raise conflict("package_code_exists")
        await self._check_parent(project_id, data.get("parent_id"))
        row = await self.repo.add(ContractPackage(project_id=project_id, status="planned", **data))
        await self._audit(actor_id, "delivery_package", row.id, "package_created", metadata={"code": row.code})
        self._publish("package.created", {"project_id": str(project_id), "package_id": str(row.id)})
        return row

    async def update_package(
        self, project_id: uuid.UUID, package_id: uuid.UUID, changes: dict[str, Any], actor_id: Any
    ):
        row = await self.repo.package(project_id, package_id, lock=True)
        if row is None:
            raise not_found("package_not_found")
        if "party" in changes and changes["party"] is not None:
            catalogue = await self.catalogue_for(await self.require_model(project_id))
            if changes["party"] not in {p.code for p in catalogue.parties}:
                raise DeliveryModelError("party_unknown", 422)
        if changes.get("parent_id") is not None:
            await self._check_parent(project_id, changes["parent_id"], row.id)
        for key, value in changes.items():
            if value is None and key not in PACKAGE_NULLABLE:
                raise DeliveryModelError("field_not_nullable", 422, detail=key)
            setattr(row, key, value)
        await self.session.flush()
        await self._audit(actor_id, "delivery_package", row.id, "package_updated")
        self._publish("package.updated", {"project_id": str(project_id), "package_id": str(row.id)})
        return row

    async def delete_package(self, project_id: uuid.UUID, package_id: uuid.UUID, actor_id: Any) -> None:
        row = await self.repo.package(project_id, package_id, lock=True)
        if row is None:
            raise not_found("package_not_found")
        if row.link_kind:
            raise conflict("package_linked")
        if any(p.parent_id == row.id for p in await self.repo.packages(project_id)):
            raise conflict("package_has_children")
        await self.session.delete(row)
        await self.session.flush()
        await self._audit(actor_id, "delivery_package", package_id, "package_deleted")

    async def set_package_status(self, project_id: uuid.UUID, package_id: uuid.UUID, status: str, actor_id: Any):
        row = await self.repo.package(project_id, package_id, lock=True)
        if row is None:
            raise not_found("package_not_found")
        await self._fsm(PACKAGE_FSM, row, status, actor_id)
        await self.session.flush()
        return row

    async def _assert_in_project(self, project_id: uuid.UUID, kind: str, link_id: uuid.UUID, table: dict) -> Any:
        if kind not in table:
            raise DeliveryModelError("link_kind_unknown", 422)
        cls = _model_cls(table[kind])
        row = await self.session.get(cls, link_id)
        if row is None or getattr(row, "project_id", None) != project_id:
            raise not_found("linked_record_not_found")
        return row

    async def link_package(
        self, project_id: uuid.UUID, package_id: uuid.UUID, kind: str, link_id: uuid.UUID, actor_id: Any
    ) -> ContractPackage:
        row = await self.repo.package(project_id, package_id, lock=True)
        if row is None:
            raise not_found("package_not_found")
        await self._assert_in_project(project_id, kind, link_id, PACKAGE_LINKS)
        row.link_kind, row.link_id = kind, link_id
        await self.session.flush()
        await self._audit(
            actor_id, "delivery_package", row.id, "package_linked", metadata={"kind": kind, "id": str(link_id)}
        )
        self._publish("package.linked", {"project_id": str(project_id), "package_id": str(row.id), "kind": kind})
        return row

    async def unlink_package(self, project_id: uuid.UUID, package_id: uuid.UUID, actor_id: Any) -> ContractPackage:
        row = await self.repo.package(project_id, package_id, lock=True)
        if row is None:
            raise not_found("package_not_found")
        row.link_kind, row.link_id = None, None
        await self.session.flush()
        await self._audit(actor_id, "delivery_package", row.id, "package_unlinked")
        return row

    async def derive_packages(
        self, project_id: uuid.UUID, actor_id: Any, *, locale: str = "en"
    ) -> list[ContractPackage]:
        """Create the template packages of the form in use whose codes are not in the plan yet (idempotent).

        The form in use is the chosen one, or before a proposal the one leading
        the comparison, so the plan can be drafted and shown with the proposal.
        Titles are written once, in the caller's locale.
        """
        from app.modules.delivery_model.messages import translate

        model = await self.require_model(project_id, lock=True)
        catalogue = await self.catalogue_for(model)
        form_code, _ = await self._form_in_use(project_id, model, catalogue)
        if not form_code:
            raise DeliveryModelError("form_not_selected", 422)
        template = catalogue.template_for(form_code)
        if template is None:
            return []
        existing = {p.code: p for p in await self.repo.packages(project_id)}
        created = []
        for i, t in enumerate(template.packages):
            if t.code in existing:
                continue
            row = ContractPackage(
                project_id=project_id,
                code=t.code,
                title=translate(t.title_key, locale=locale)
                if t.title_key
                else (t.labels or {}).get(locale) or (t.labels or {}).get("en", t.code),
                kind=t.kind,
                designs=t.designs,
                builds=t.builds,
                supplies=t.supplies,
                manages=t.manages,
                party=t.party,
                contracting_party=t.contracting_party,
                price_basis=t.price_basis,
                status="planned",
                sort_order=len(existing) + i,
            )
            self.session.add(row)
            await self.session.flush()
            existing[t.code] = row
            created.append((row, t.parent))
        for row, parent in created:
            if parent and parent in existing:
                row.parent_id = existing[parent].id
        await self.session.flush()
        await self._audit(actor_id, "delivery_model", model.id, "packages_derived", metadata={"count": len(created)})
        return [r for r, _ in created]

    async def package_views(self, project_id: uuid.UUID) -> list[dict[str, Any]]:
        await self.require_model(project_id)
        return await self.package_rows(project_id)

    async def consistency(self, project_id: uuid.UUID) -> dict[str, Any]:
        """Rules 6 to 8 and 10 to 11 as one report for the consistency banner."""
        model = await self.require_model(project_id)
        catalogue = await self.catalogue_for(model)
        form_code = model.selected_form_code
        form = await self._form_of(project_id, catalogue, form_code)
        packages = await self.package_rows(project_id)
        ctypes = {p["id"]: p["linked_contract_type"] for p in packages if p.get("linked_contract_type")}
        findings = [
            *rules.allocation_findings(catalogue, form_code, await self._allocation_rows(project_id), form=form),
            *rules.package_findings(form, packages, linked_contract_types=ctypes),
            *rules.ofi_findings(
                await self.ofi_rows(project_id),
                packages,
                procurement_released=bool(await self.procurement_released(project_id)),
            ),
        ]
        items = [f.as_dict() for f in findings]
        return {
            "form_code": form_code,
            "errors": sum(1 for f in findings if f.severity == rules.ERROR),
            "warnings": sum(1 for f in findings if f.severity == rules.WARNING),
            "items": items,
            "total": len(items),
            "offset": 0,
            "limit": len(items),
        }

    async def responsibility(
        self,
        project_id: uuid.UUID,
        *,
        designs: bool | None = None,
        builds: bool | None = None,
        supplies: bool | None = None,
    ) -> list[dict[str, Any]]:
        """Rule 16: "which party designs / builds / supplies" for modules 4, 7 and 8, from the package plan only."""
        out = []
        for p in await self.package_rows(project_id):
            if p["effective_status"] == "cancelled":
                continue
            if designs is not None and p["designs"] != designs:
                continue
            if builds is not None and p["builds"] != builds:
                continue
            if supplies is not None and p["supplies"] != supplies:
                continue
            out.append(p)
        return out

    # ── owner-furnished items (rules 10, 11) ───────────────────────────────

    async def procurement_released(self, project_id: uuid.UUID) -> bool | None:
        """Has a gate into a phase tagged as enabling procurement been passed? ``None``: no phase carries the tag."""
        return await hosting.released_procurement(self.session, project_id, _GO)

    async def ofi_rows(self, project_id: uuid.UUID) -> list[dict[str, Any]]:
        items = await self.repo.ofis(project_id)
        today = datetime.now(UTC).date()
        linked = await self._linked_rows(
            [(i.link_kind, i.link_id) for i in items if i.link_kind and i.link_id], OFI_LINKS
        )
        out = []
        for i in items:
            row = linked.get((i.link_kind, i.link_id)) if i.link_kind else None
            arrival = getattr(row, _OFI_ARRIVAL.get(i.link_kind or "", ""), None) if row is not None else None
            out.append(
                {
                    "id": str(i.id),
                    "code": i.code,
                    "description": i.description,
                    "item_kind": i.item_kind,
                    "install_by": i.install_by,
                    "package_id": _s(i.package_id),
                    "procurement_route": i.procurement_route,
                    "link": {
                        "kind": i.link_kind,
                        "id": str(i.link_id),
                        "status": getattr(row, "status", None),
                        "missing": row is None,
                    }
                    if i.link_kind
                    else None,
                    "schedule_activity_id": _s(i.schedule_activity_id),
                    "need_by_date": i.need_by_date,
                    "expected_delivery_date": arrival or i.expected_delivery_date,
                    "enquiry_date": i.enquiry_date,
                    "lead_time_days": i.lead_time_days,
                    "plant_item_id": _s(i.plant_item_id),
                    "status": i.status,
                }
            )
            # A linked item shows the register's enquiry date, lead time and latest order date, not its own.
            dates = (
                await plant.plant_item_dates(self.session, project_id, i.plant_item_id, today=today)
                if i.plant_item_id is not None
                else None
            )
            out[-1] = plant.with_dates(out[-1], dates)
        return out

    async def ofi_views(self, project_id: uuid.UUID) -> list[dict[str, Any]]:
        await self.require_model(project_id)
        rows = await self.ofi_rows(project_id)
        findings = rules.ofi_findings(
            rows,
            await self.package_rows(project_id),
            procurement_released=bool(await self.procurement_released(project_id)),
        )
        for r in rows:
            r["findings"] = [f.as_dict() for f in findings if f.ref == r["code"]]
        return rows

    async def _check_package(self, project_id: uuid.UUID, package_id: uuid.UUID | None) -> None:
        if package_id is not None and await self.repo.package(project_id, package_id) is None:
            raise not_found("package_not_found")

    async def _check_plant_item(
        self, project_id: uuid.UUID, plant_item_id: uuid.UUID | None, *, own_id: uuid.UUID | None = None
    ) -> None:
        """A plant item may be linked when the register holds it in this project and no other item is it."""
        if plant_item_id is None:
            return
        if not plant.installed():
            raise DeliveryModelError("plant_register_unavailable", 422)
        dates = await plant.plant_item_dates(self.session, project_id, plant_item_id)
        if dates is None:
            # Missing and of another project read the same, here as in the register.
            raise not_found("plant_item_not_found")
        if not plant.keeps_owner_furnished_item(dates):
            # The register says a contractor supplies it (or nobody yet): the two lists must not disagree.
            raise conflict("plant_item_not_owner_furnished")
        if any(o.plant_item_id == plant_item_id and o.id != own_id for o in await self.repo.ofis(project_id)):
            raise conflict("plant_item_already_linked")

    async def _refuse_if_held(self, row: OwnerFurnishedItem) -> None:
        """An item the register still counts as the owner's supply of a plant item is let go there, not here."""
        if row.plant_item_id is None:
            return
        dates = await plant.plant_item_dates(self.session, row.project_id, row.plant_item_id)
        if plant.keeps_owner_furnished_item(dates):
            raise conflict("ofi_held_by_plant_item")

    async def ensure_ofi_for_plant_item(
        self,
        project_id: uuid.UUID,
        plant_item_id: uuid.UUID,
        *,
        title: str,
        installer_package_id: uuid.UUID | None,
        actor_id: Any,
    ) -> OwnerFurnishedItem:
        """The register asks for the owner-furnished item of a plant item: created once, its installer as passed.

        The register asks while it is setting the route, so its route is not
        read back here; the checks of a link made by hand do not apply.
        """
        await self.require_model(project_id, lock=True)
        await self._check_package(project_id, installer_package_id)
        items = await self.repo.ofis(project_id)
        install_by = "package" if installer_package_id is not None else "owner"
        row = next((o for o in items if o.plant_item_id == plant_item_id), None)
        if row is not None:
            row.install_by, row.package_id = install_by, installer_package_id
            await self.session.flush()
            return row
        dates = await plant.plant_item_dates(self.session, project_id, plant_item_id)
        code = plant.item_code(dates.code if dates is not None else None, plant_item_id, {o.code for o in items})
        row = await self.repo.add(
            OwnerFurnishedItem(
                project_id=project_id,
                status="identified",
                code=code,
                description=title,
                item_kind="equipment",
                install_by=install_by,
                package_id=installer_package_id,
                plant_item_id=plant_item_id,
            )
        )
        await self._audit(
            actor_id, "delivery_ofi", row.id, "ofi_created", metadata={"code": code, "source": "plant_register"}
        )
        self._publish("ofi.created", {"project_id": str(project_id), "ofi_id": str(row.id)})
        return row

    async def release_ofi_of_plant_item(
        self, project_id: uuid.UUID, plant_item_id: uuid.UUID, *, actor_id: Any
    ) -> bool:
        """The register says the plant item is no longer the owner's supply: detach its item; it stays, unlinked."""
        row = next((o for o in await self.repo.ofis(project_id) if o.plant_item_id == plant_item_id), None)
        if row is None:
            return False
        row.plant_item_id = None
        await self.session.flush()
        await self._audit(actor_id, "delivery_ofi", row.id, "ofi_released", metadata={"source": "plant_register"})
        return True

    async def create_ofi(self, project_id: uuid.UUID, data: dict[str, Any], actor_id: Any) -> OwnerFurnishedItem:
        await self.require_model(project_id, lock=True)
        if any(o.code == data["code"] for o in await self.repo.ofis(project_id)):
            raise conflict("ofi_code_exists")
        await self._check_package(project_id, data.get("package_id"))
        await self._check_plant_item(project_id, data.get("plant_item_id"))
        row = await self.repo.add(OwnerFurnishedItem(project_id=project_id, status="identified", **data))
        await self._audit(actor_id, "delivery_ofi", row.id, "ofi_created", metadata={"code": row.code})
        self._publish("ofi.created", {"project_id": str(project_id), "ofi_id": str(row.id)})
        return row

    async def update_ofi(self, project_id: uuid.UUID, ofi_id: uuid.UUID, changes: dict[str, Any], actor_id: Any):
        if changes.get("plant_item_id") is not None:
            # Two items must not claim one plant item: linking waits for the model row, as creating does.
            await self.require_model(project_id, lock=True)
        row = await self.repo.ofi(project_id, ofi_id, lock=True)
        if row is None:
            raise not_found("ofi_not_found")
        await self._check_package(project_id, changes.get("package_id"))
        if "plant_item_id" in changes and changes["plant_item_id"] != row.plant_item_id:
            await self._refuse_if_held(row)
            await self._check_plant_item(project_id, changes["plant_item_id"], own_id=row.id)
        for key, value in changes.items():
            if value is None and key not in OFI_NULLABLE:
                raise DeliveryModelError("field_not_nullable", 422, detail=key)
            setattr(row, key, value)
        await self.session.flush()
        await self._audit(actor_id, "delivery_ofi", row.id, "ofi_updated")
        return row

    async def delete_ofi(self, project_id: uuid.UUID, ofi_id: uuid.UUID, actor_id: Any) -> None:
        row = await self.repo.ofi(project_id, ofi_id, lock=True)
        if row is None:
            raise not_found("ofi_not_found")
        await self._refuse_if_held(row)
        await self.session.delete(row)
        await self.session.flush()
        await self._audit(actor_id, "delivery_ofi", ofi_id, "ofi_deleted")

    # ── contract-side items (module 2) ─────────────────────────────────────

    async def contract_item_views(self, project_id: uuid.UUID) -> list[dict[str, Any]]:
        model = await self.require_model(project_id)
        catalogue = await self.catalogue_for(model)
        rows = [_contract_item_view(i) for i in await self.repo.contract_items(project_id)]
        findings = await self.contract_findings(project_id, rows=rows)
        for r in rows:
            r["kind_known"] = catalogue.contract_kind(r["group_code"], r["kind_code"]) is not None
            r["findings"] = [f.as_dict() for f in findings if f.ref == r["code"]]
        return rows

    async def contract_findings(
        self, project_id: uuid.UUID, rows: list[dict[str, Any]] | None = None
    ) -> list[rules.Finding]:
        model = await self.require_model(project_id)
        catalogue = await self.catalogue_for(model)
        form = await self._form_of(project_id, catalogue, model.selected_form_code)
        items = (
            rows if rows is not None else [_contract_item_view(i) for i in await self.repo.contract_items(project_id)]
        )
        return rules.contract_item_findings(
            items,
            [k.model_dump(mode="json") for k in catalogue.contract_kinds],
            form,
            procurement_released=bool(await self.procurement_released(project_id)),
        )

    async def _check_contract_kind(self, project_id: uuid.UUID, group: str, kind: str) -> None:
        catalogue = await self.catalogue_for(await self.require_model(project_id))
        # A catalogue without contract kinds (an older tenant draft) accepts any code; one with kinds is closed.
        if catalogue.contract_kinds and catalogue.contract_kind(group, kind) is None:
            raise DeliveryModelError("contract_kind_unknown", 422, detail=f"{group}:{kind}")

    async def create_contract_item(self, project_id: uuid.UUID, data: dict[str, Any], actor_id: Any) -> ContractItem:
        await self.require_model(project_id, lock=True)
        if any(i.code == data["code"] for i in await self.repo.contract_items(project_id)):
            raise conflict("contract_item_code_exists")
        await self._check_package(project_id, data.get("package_id"))
        await self._check_contract_kind(project_id, data["group_code"], data["kind_code"])
        row = await self.repo.add(ContractItem(project_id=project_id, **data))
        await self._audit(
            actor_id, "delivery_contract_item", row.id, "contract_item_created", metadata={"code": row.code}
        )
        self._publish("contract_item.created", {"project_id": str(project_id), "item_id": str(row.id)})
        return row

    async def update_contract_item(
        self, project_id: uuid.UUID, item_id: uuid.UUID, changes: dict[str, Any], actor_id: Any
    ) -> ContractItem:
        row = await self.repo.contract_item(project_id, item_id, lock=True)
        if row is None:
            raise not_found("contract_item_not_found")
        await self._check_package(project_id, changes.get("package_id"))
        if "kind_code" in changes:
            await self._check_contract_kind(project_id, row.group_code, changes["kind_code"])
        if changes.get("price_basis") is not None and row.group_code != "contract_form":
            raise DeliveryModelError("price_basis_not_for_group", 422)
        if changes.get("share_percent") is not None and row.group_code != "partner_structure":
            raise DeliveryModelError("share_not_for_group", 422)
        for key, value in changes.items():
            setattr(row, key, value)
        await self.session.flush()
        await self._audit(actor_id, "delivery_contract_item", row.id, "contract_item_updated")
        return row

    async def delete_contract_item(self, project_id: uuid.UUID, item_id: uuid.UUID, actor_id: Any) -> None:
        row = await self.repo.contract_item(project_id, item_id, lock=True)
        if row is None:
            raise not_found("contract_item_not_found")
        if row.status == "signed":
            # A signed agreement is terminated, never erased from the record.
            raise DeliveryModelError("contract_item_signed", 409)
        await self.session.delete(row)
        await self.session.flush()
        await self._audit(actor_id, "delivery_contract_item", item_id, "contract_item_deleted")

    async def set_ofi_route(
        self,
        project_id: uuid.UUID,
        ofi_id: uuid.UUID,
        *,
        route: str,
        link_kind: str | None,
        link_id: uuid.UUID | None,
        actor_id: Any,
    ) -> OwnerFurnishedItem:
        row = await self.repo.ofi(project_id, ofi_id, lock=True)
        if row is None:
            raise not_found("ofi_not_found")
        if (link_kind is None) != (link_id is None):
            raise DeliveryModelError("link_incomplete", 422)
        if link_kind is not None:
            await self._assert_in_project(project_id, link_kind, link_id, OFI_LINKS)
        row.procurement_route, row.link_kind, row.link_id = route, link_kind, link_id
        if route == "none_yet":
            if row.status == "route_set":
                await self._fsm(OFI_FSM, row, "identified", actor_id)
        elif row.status == "identified":
            await self._fsm(OFI_FSM, row, "route_set", actor_id)
        await self.session.flush()
        await self._audit(actor_id, "delivery_ofi", row.id, "ofi_route_set", metadata={"route": route})
        return row

    async def set_ofi_status(self, project_id: uuid.UUID, ofi_id: uuid.UUID, status: str, actor_id: Any):
        row = await self.repo.ofi(project_id, ofi_id, lock=True)
        if row is None:
            raise not_found("ofi_not_found")
        if status != "identified" and row.procurement_route == "none_yet":
            raise DeliveryModelError("ofi_without_route", 422)
        await self._fsm(OFI_FSM, row, status, actor_id)
        await self.session.flush()
        return row

    # ── readiness, validation ──────────────────────────────────────────────

    async def readiness(self, project_id: uuid.UUID) -> dict[str, Any]:
        """What the governance gate reads: a proposed (or approved) decision, all risks allocated, no errors."""
        model = await self.get_model(project_id)
        if model is None:
            return {"in_use": False, "met": False, "status": None, "errors": []}
        report = await self.consistency(project_id)
        errors = [i for i in report["items"] if i["severity"] == rules.ERROR]
        decided = model.status in DECIDED
        return {
            "in_use": True,
            "met": decided and not errors,
            "status": model.status,
            "decision_present": decided,
            "risks_allocated": not any(e["code"] == "risk_unallocated" for e in errors),
            "errors": errors,
        }

    async def validation_payload(self, project_id: uuid.UUID) -> dict[str, Any]:
        model = await self.require_model(project_id)
        catalogue = await self.catalogue_for(model)
        packages = await self.package_rows(project_id)
        return {
            "catalogue": catalogue.model_dump(mode="json"),
            "model": {
                "status": model.status,
                "selected_form_code": model.selected_form_code,
                "selected_form": _form_view(await self._form_of(project_id, catalogue, model.selected_form_code)),
            },
            "comparison": await self.comparison(project_id),
            "allocations": await self._allocation_rows(project_id),
            "packages": packages,
            "ofis": await self.ofi_rows(project_id),
            "contract_items": [_contract_item_view(i) for i in await self.repo.contract_items(project_id)],
            "procurement_released": bool(await self.procurement_released(project_id)),
            "decisions": await self.decision_views(project_id),
        }


def _contract_item_view(i: ContractItem) -> dict[str, Any]:
    return {
        "id": str(i.id),
        "code": i.code,
        "group_code": i.group_code,
        "kind_code": i.kind_code,
        "title": i.title,
        "counterparty": i.counterparty,
        "package_id": _s(i.package_id),
        "status": i.status,
        "reference": i.reference,
        "start_date": i.start_date,
        "end_date": i.end_date,
        "price_basis": i.price_basis,
        "share_percent": i.share_percent,
        "notes": i.notes,
    }


def _form_view(form: Any) -> dict[str, Any] | None:
    if form is None:
        return None
    return form.model_dump(mode="json")


def _allocation_view(a: RiskAllocation) -> dict[str, Any]:
    return {
        "id": str(a.id),
        "category_code": a.category_code,
        "party": a.party,
        "basis": a.basis,
        "shares": a.shares or {},
        "rationale": a.rationale,
        "not_applicable": a.not_applicable,
        "source": a.source,
        "status": a.status,
        "confirmed_by": _s(a.confirmed_by),
        "confirmed_at": a.confirmed_at.isoformat() if a.confirmed_at else None,
        "risk_item_ids": list(a.risk_item_ids or []),
    }


def _decision_view(d: DeliveryDecision, model: DeliveryModel | None) -> dict[str, Any]:
    return {
        "id": str(d.id),
        "form_code": d.form_code,
        "option_id": _s(d.option_id),
        "status": d.status,
        "rationale": d.rationale,
        "snapshot": d.snapshot or {},
        "owner_capability": d.owner_capability or {},
        "dispositions": d.dispositions or {},
        "proposed_by": _s(d.proposed_by),
        "proposed_at": d.proposed_at.isoformat() if d.proposed_at else None,
        "approved_by": _s(d.approved_by),
        "approved_at": d.approved_at.isoformat() if d.approved_at else None,
        "approval_source": d.approval_source,
        "governance_document_id": _s(d.governance_document_id),
        "governance_ref_id": _s(d.governance_ref_id),
        "bound_revision_id": _s(d.bound_revision_id),
        "bound_content_hash": d.bound_content_hash,
        "supersedes_id": _s(d.supersedes_id),
        "snapshot_hash": d.snapshot_hash,
        "record_matches_bound_revision": record_matches_bound_revision(d.snapshot_hash, d.bound_content_hash),
        # Rule 2: the setting as it stood at approval. Under it the proposer is never the approver; a decision
        # approved before the rule was enforced still shows here when it breaks it.
        "four_eyes": d.four_eyes,
        "four_eyes_violated": bool(d.four_eyes and d.approved_by and d.approved_by == d.proposed_by),
        "approval_blocked_reason": d.approval_blocked_reason or None,
        "is_current": model is not None and model.current_decision_id == d.id,
    }
