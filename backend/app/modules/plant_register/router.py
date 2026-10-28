# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Plant register API, mounted at ``/api/v1/plant-register``.

Every route lives under ``/projects/{project_id}/...`` and calls
``verify_project_access`` before it reads anything, so a project the caller
cannot see answers 404 exactly like a missing one. Child rows are looked up by
``(project_id, id)`` (and their item), so an id from another project is 404 too.

Writes need ``plant.edit`` AND either ``plant.manage`` or being the owner or
deputy of the project's equipment area. The router checks the permissions and
hands the service a boolean; the service never sees a role. Pinning the
catalogue and overriding an item's critical or long-lead classification need
``plant.manage``. Decision papers are approved only through their approval
route.

No write route takes a date: "today" on a write is the server's UTC date. The
optional ``today`` query exists on reads only.

Errors carry ``{"code", "message_key", "message", "violations"?}`` in
``detail``; ``message_key`` is ``plant.errors.<code>``. 404 = not found or not
visible, 403 = not allowed, 409 = state conflict, 422 = invalid input or a rule
that blocks (each blocker in ``violations``).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable
from datetime import UTC, date, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.core.i18n import get_locale
from app.core.tenant_scope import resolve_tenant_id
from app.dependencies import CurrentUserId, CurrentUserPayload, RequirePermission, SessionDep, verify_project_access
from app.modules.plant_register import calc
from app.modules.plant_register.errors import PlantError, forbidden, worded
from app.modules.plant_register.messages import translate, written_locale
from app.modules.plant_register.schemas import (
    FindingOut,
    HandoverIn,
    ItemCreate,
    ItemOut,
    ItemUpdate,
    ItServiceIn,
    ItServiceOut,
    LimitOut,
    LimitsIn,
    Page,
    PaperIn,
    PaperOut,
    QuoteIn,
    QuoteOut,
    RouteIn,
    SettingsIn,
    SettingsOut,
    SlotIn,
    SlotOut,
    SpareIn,
    SpareOut,
    SpareTransitionIn,
    SubmittalLeadOut,
    TransitionIn,
)
from app.modules.plant_register.service import PlantService
from app.modules.plant_register.site_plant import (
    PositionCreate,
    PositionIn,
    PositionList,
    PositionOut,
    SitePlantService,
)

router = APIRouter(tags=["plant_register"])

READ = Depends(RequirePermission("plant.read"))
EDIT = Depends(RequirePermission("plant.edit"))
_MANAGE = RequirePermission("plant.manage")
_EDIT_CHECK = RequirePermission("plant.edit")
P = "/projects/{project_id}"


async def _run[T](awaitable: Awaitable[T]) -> T:
    """Turn a :class:`PlantError` into the HTTP error the module documents."""
    try:
        return await awaitable
    except PlantError as exc:
        locale = get_locale() or "en"
        message = translate(f"plant.errors.{exc.code}", locale=locale)
        detail = exc.as_detail(message)
        if exc.violations:
            detail["violations"] = worded(exc.violations, locale)
        raise HTTPException(status_code=exc.status_code, detail=detail) from exc


def _uid(user_id: str) -> uuid.UUID:
    return uuid.UUID(str(user_id))


def _today(value: date | None) -> date:
    return value or datetime.now(UTC).date()


def _page(items: list[Any], total: int | None = None, offset: int = 0, limit: int = 0) -> dict[str, Any]:
    return {
        "items": items,
        "total": len(items) if total is None else total,
        "offset": offset,
        "limit": limit or len(items),
    }


async def _plant_read(project_id: uuid.UUID, user_id: str, session: Any) -> PlantService:
    await verify_project_access(project_id, user_id, session)
    return PlantService(session)


async def _holds(check: Any, payload: dict[str, Any]) -> bool:
    try:
        await check(payload)
    except HTTPException:
        return False
    return True


async def _can_manage(payload: dict[str, Any]) -> bool:
    """Whether the caller holds ``plant.manage``, by the same check every permission gate uses."""
    return await _holds(_MANAGE, payload)


async def _plant_edit(project_id: uuid.UUID, user_id: str, payload: dict[str, Any], session: Any) -> PlantService:
    await verify_project_access(project_id, user_id, session)
    svc = PlantService(session)
    await _run(svc.require_editor(project_id, _uid(user_id), can_manage=await _can_manage(payload)))
    return svc


async def _plant_manage(project_id: uuid.UUID, user_id: str, payload: dict[str, Any], session: Any) -> PlantService:
    """A write that changes what the gates read: ``plant.manage`` only."""
    await verify_project_access(project_id, user_id, session)
    if not await _can_manage(payload):
        await _run(_refuse(forbidden("manage_required")))
    return PlantService(session)


async def _refuse(error: PlantError) -> None:
    raise error


async def _with_can(
    svc: PlantService, project_id: uuid.UUID, views: list[dict[str, Any]], user_id: str, payload: dict[str, Any]
) -> list[dict[str, Any]]:
    """Put on each item view what this caller may do with it, answered by the functions the writes raise from."""
    return await svc.item_capabilities(
        project_id,
        views,
        _uid(user_id),
        can_edit=await _holds(_EDIT_CHECK, payload),
        can_manage=await _can_manage(payload),
    )


async def _item_out(
    svc: PlantService, project_id: uuid.UUID, item_id: uuid.UUID, today: date, user_id: str, payload: dict[str, Any]
) -> ItemOut:
    views = await _run(svc.item_views(project_id, today=today, only=[item_id]))
    if not views:
        await _run(_refuse(PlantError("item_not_found", 404)))
    return ItemOut.from_view((await _with_can(svc, project_id, views, user_id, payload))[0])


# ── catalogue and settings ────────────────────────────────────────────────


@router.get(P + "/catalogue", response_model=dict[str, Any], dependencies=[READ])
async def get_catalogue(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    """The pinned plant catalogue (classes, routes, sources, steps, parties) as JSON."""
    svc = await _plant_read(project_id, user_id, session)
    return (await _run(svc.catalogue(project_id))).model_dump(mode="json")


@router.get(P + "/settings", response_model=SettingsOut, dependencies=[READ])
async def get_settings(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> SettingsOut:
    """The pinned catalogue and what the caller may do here (``can.edit``, ``can.manage``, each with a reason)."""
    svc = await _plant_read(project_id, user_id, session)
    can = await svc.capabilities(
        project_id,
        _uid(user_id),
        can_edit=await _holds(_EDIT_CHECK, payload),
        can_manage=await _can_manage(payload),
    )
    row = await svc.settings(project_id)
    if row is None:
        return SettingsOut(
            catalogue_source="shipped", catalogue_id="neutral", catalogue_version=None, pinned=False, can=can
        )
    return SettingsOut(
        catalogue_source=row.catalogue_source,
        catalogue_id=row.catalogue_id,
        catalogue_version=row.catalogue_version,
        pinned=True,
        can=can,
    )


@router.get(P + "/submittals/{submittal_id}/lead-time", response_model=SubmittalLeadOut, dependencies=[READ])
async def submittal_lead_time(
    project_id: uuid.UUID, submittal_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> SubmittalLeadOut:
    """Whether a plant item owns the lead time of this submittal; if so its own lead fields are read-only."""
    from app.modules.plant_register.reads import plant_item_for_submittal

    await _plant_read(project_id, user_id, session)
    dates = await _run(plant_item_for_submittal(session, project_id, submittal_id))
    if dates is None:
        return SubmittalLeadOut(owned_by_plant_item=False)
    return SubmittalLeadOut(
        owned_by_plant_item=True,
        reason="lead_time_owned_by_plant_item",
        plant_item_id=dates.plant_item_id,
        plant_item_code=dates.code,
        effective_lead_weeks=dates.effective_lead_weeks,
        long_lead=dates.long_lead,
        latest_order_date=dates.latest_order_date,
    )


@router.put(P + "/settings", response_model=SettingsOut, dependencies=[EDIT])
async def put_settings(
    project_id: uuid.UUID, body: SettingsIn, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> SettingsOut:
    svc = await _plant_manage(project_id, user_id, payload, session)
    row = await _run(
        svc.pin_catalogue(
            project_id,
            tenant_id=resolve_tenant_id(payload),
            source=body.catalogue_source,
            catalogue_id=body.catalogue_id,
            version=body.catalogue_version,
            actor_id=_uid(user_id),
        )
    )
    return SettingsOut(
        catalogue_source=row.catalogue_source,
        catalogue_id=row.catalogue_id,
        catalogue_version=row.catalogue_version,
        pinned=True,
    )


# ── items ─────────────────────────────────────────────────────────────────


@router.get(P + "/items", response_model=Page[ItemOut], dependencies=[READ])
async def list_items(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    long_lead: bool | None = None,
    critical: bool | None = None,
    overdue: bool | None = None,
    route: str | None = Query(None, max_length=64),
    component_class: str | None = Query(None, alias="class", max_length=64),
    status: str | None = Query(None, max_length=20),
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
    today: date | None = None,
) -> dict[str, Any]:
    """Items with every derived figure; filters as the register grid offers them."""
    svc = await _plant_read(project_id, user_id, session)
    views = await _run(svc.item_views(project_id, today=_today(today)))
    if long_lead is not None:
        views = [v for v in views if v["long_lead"] is long_lead]
    if critical is not None:
        views = [v for v in views if v["critical"] is critical]
    if overdue is not None:
        views = [v for v in views if (v["order_status"] == "overdue") is overdue]
    if route:
        views = [v for v in views if (v["item"].procurement_route or "unset") == route]
    if component_class:
        views = [v for v in views if v["item"].component_class_code == component_class]
    if status:
        views = [v for v in views if v["item"].status == status]
    total = len(views)
    shown = await _with_can(svc, project_id, views[offset : offset + limit], user_id, payload)
    return _page([ItemOut.from_view(v) for v in shown], total, offset, limit)


@router.post(P + "/items", response_model=ItemOut, status_code=201, dependencies=[EDIT])
async def create_item(
    project_id: uuid.UUID, body: ItemCreate, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> ItemOut:
    svc = await _plant_edit(project_id, user_id, payload, session)
    item = await _run(
        svc.create_item(project_id, body.changes(), actor_id=_uid(user_id), can_manage=await _can_manage(payload))
    )
    return await _item_out(svc, project_id, item.id, _today(None), user_id, payload)


@router.get(P + "/items/{item_id}", response_model=ItemOut, dependencies=[READ])
async def get_item(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    today: date | None = None,
) -> ItemOut:
    svc = await _plant_read(project_id, user_id, session)
    await _run(svc.get_item(project_id, item_id))
    return await _item_out(svc, project_id, item_id, _today(today), user_id, payload)


@router.patch(P + "/items/{item_id}", response_model=ItemOut, dependencies=[EDIT])
async def update_item(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    body: ItemUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> ItemOut:
    svc = await _plant_edit(project_id, user_id, payload, session)
    await _run(
        svc.update_item(
            project_id, item_id, body.changes(), actor_id=_uid(user_id), can_manage=await _can_manage(payload)
        )
    )
    return await _item_out(svc, project_id, item_id, _today(None), user_id, payload)


@router.post(P + "/items/{item_id}/transition", response_model=ItemOut, dependencies=[EDIT])
async def transition_item(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    body: TransitionIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> ItemOut:
    """Move by hand to specified, enquired, route_set, manufactured or cancelled; blockers in ``violations``."""
    svc = await _plant_edit(project_id, user_id, payload, session)
    await _run(svc.transition_item(project_id, item_id, body.target, actor_id=_uid(user_id), today=_today(None)))
    return await _item_out(svc, project_id, item_id, _today(None), user_id, payload)


@router.post(P + "/items/{item_id}/sync", response_model=ItemOut, dependencies=[EDIT])
async def sync_item(
    project_id: uuid.UUID, item_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> ItemOut:
    """Read ordered / delivered / installed / commissioned from the PO, OFI and Cx system (rule 11)."""
    svc = await _plant_edit(project_id, user_id, payload, session)
    await _run(svc.sync_item_state(project_id, item_id, actor_id=_uid(user_id)))
    return await _item_out(svc, project_id, item_id, _today(None), user_id, payload)


@router.put(P + "/items/{item_id}/route", response_model=ItemOut, dependencies=[EDIT])
async def set_route(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    body: RouteIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> ItemOut:
    """Set the procurement route; an owner-furnished route creates or attaches the OFI."""
    svc = await _plant_edit(project_id, user_id, payload, session)
    await _run(
        svc.set_route(
            project_id,
            item_id,
            route=body.procurement_route,
            contract_package_id=body.contract_package_id,
            actor_id=_uid(user_id),
        )
    )
    return await _item_out(svc, project_id, item_id, _today(None), user_id, payload)


@router.post(P + "/items/{item_id}/handover", response_model=ItemOut, dependencies=[EDIT])
async def handover_item(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    body: HandoverIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> ItemOut:
    """Rule 16: hand over to operation; ``confirm: true`` is required, a service asset is created when a contract is named."""
    svc = await _plant_edit(project_id, user_id, payload, session)
    await _run(
        svc.handover(
            project_id,
            item_id,
            confirm=body.confirm,
            service_contract_id=body.service_contract_id,
            no_asset_reason=body.no_asset_reason,
            actor_id=_uid(user_id),
        )
    )
    return await _item_out(svc, project_id, item_id, _today(None), user_id, payload)


# ── quotes ────────────────────────────────────────────────────────────────


@router.get(P + "/items/{item_id}/quotes", response_model=Page[QuoteOut], dependencies=[READ])
async def list_quotes(
    project_id: uuid.UUID, item_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _plant_read(project_id, user_id, session)
    await _run(svc.get_item(project_id, item_id))
    return _page([QuoteOut.model_validate(q) for q in await svc.repo.quotes(project_id, item_id)])


@router.post(P + "/items/{item_id}/quotes", response_model=QuoteOut, status_code=201, dependencies=[EDIT])
async def add_quote(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    body: QuoteIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> QuoteOut:
    """Append a lead time; enquiry date required (rule 2). The first quote, or ``set_basis``, becomes the basis."""
    svc = await _plant_edit(project_id, user_id, payload, session)
    quote = await _run(
        svc.add_quote(project_id, item_id, body.model_dump(), actor_id=_uid(user_id), today=_today(None))
    )
    return QuoteOut.model_validate(quote)


@router.post(P + "/items/{item_id}/quotes/{quote_id}/basis", response_model=QuoteOut, dependencies=[EDIT])
async def set_basis(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    quote_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> QuoteOut:
    svc = await _plant_edit(project_id, user_id, payload, session)
    return QuoteOut.model_validate(await _run(svc.set_basis(project_id, item_id, quote_id, actor_id=_uid(user_id))))


# ── slot reservation ──────────────────────────────────────────────────────


@router.get(P + "/items/{item_id}/slot", response_model=Page[SlotOut], dependencies=[READ])
async def list_slots(
    project_id: uuid.UUID, item_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _plant_read(project_id, user_id, session)
    await _run(svc.get_item(project_id, item_id))
    return _page([SlotOut.model_validate(s) for s in await svc.repo.slots(project_id, item_id)])


@router.post(P + "/items/{item_id}/slot", response_model=SlotOut, status_code=201, dependencies=[EDIT])
async def create_slot(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    body: SlotIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> SlotOut:
    svc = await _plant_edit(project_id, user_id, payload, session)
    return SlotOut.model_validate(
        await _run(svc.create_slot(project_id, item_id, body.model_dump(exclude_unset=True), actor_id=_uid(user_id)))
    )


@router.patch(P + "/items/{item_id}/slot/{slot_id}", response_model=SlotOut, dependencies=[EDIT])
async def update_slot(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    slot_id: uuid.UUID,
    body: SlotIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> SlotOut:
    svc = await _plant_edit(project_id, user_id, payload, session)
    return SlotOut.model_validate(
        await _run(
            svc.update_slot(project_id, item_id, slot_id, body.model_dump(exclude_unset=True), actor_id=_uid(user_id))
        )
    )


@router.post(P + "/items/{item_id}/slot/{slot_id}/transition", response_model=SlotOut, dependencies=[EDIT])
async def transition_slot(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    slot_id: uuid.UUID,
    body: TransitionIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> SlotOut:
    """held (terms complete, rule 13), converted_to_order, released. ``expired`` is set by the escalation."""
    svc = await _plant_edit(project_id, user_id, payload, session)
    return SlotOut.model_validate(
        await _run(svc.transition_slot(project_id, item_id, slot_id, body.target, actor_id=_uid(user_id)))
    )


# ── decision paper ────────────────────────────────────────────────────────


def _paper_out(paper: Any) -> PaperOut:
    out = PaperOut.model_validate(paper)
    try:
        out.scores = {k: str(v) for k, v in calc.weighted_scores(paper.options, paper.criteria).items()}
    except (ValueError, ArithmeticError):
        out.scores = {}
    return out


@router.get(P + "/items/{item_id}/decision-paper", response_model=Page[PaperOut], dependencies=[READ])
async def list_papers(
    project_id: uuid.UUID, item_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    """Every paper of the item, oldest first; the last one is current."""
    svc = await _plant_read(project_id, user_id, session)
    await _run(svc.get_item(project_id, item_id))
    return _page([_paper_out(p) for p in await svc.repo.papers(project_id, item_id)])


@router.post(P + "/items/{item_id}/decision-paper", response_model=PaperOut, status_code=201, dependencies=[EDIT])
async def create_paper(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    body: PaperIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> PaperOut:
    svc = await _plant_edit(project_id, user_id, payload, session)
    return _paper_out(await _run(svc.create_paper(project_id, item_id, body.body(), actor_id=_uid(user_id))))


@router.patch(P + "/items/{item_id}/decision-paper/{paper_id}", response_model=PaperOut, dependencies=[EDIT])
async def update_paper(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    paper_id: uuid.UUID,
    body: PaperIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> PaperOut:
    svc = await _plant_edit(project_id, user_id, payload, session)
    return _paper_out(await _run(svc.update_paper(project_id, item_id, paper_id, body.body(), actor_id=_uid(user_id))))


@router.post(P + "/items/{item_id}/decision-paper/{paper_id}/submit", response_model=PaperOut, dependencies=[EDIT])
async def submit_paper(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    paper_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> PaperOut:
    """Start the ``plant_decision_paper`` approval route; 422 ``no_decision_route`` when the project has none."""
    svc = await _plant_edit(project_id, user_id, payload, session)
    return _paper_out(await _run(svc.submit_paper(project_id, item_id, paper_id, actor_id=_uid(user_id))))


@router.post(P + "/items/{item_id}/decision-paper/{paper_id}/withdraw", response_model=PaperOut, dependencies=[EDIT])
async def withdraw_paper(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    paper_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> PaperOut:
    """Take a submitted paper back to draft (its route is cancelled); a route that already decided wins."""
    svc = await _plant_edit(project_id, user_id, payload, session)
    return _paper_out(await _run(svc.withdraw_paper(project_id, item_id, paper_id, actor_id=_uid(user_id))))


# ── delivery limits ───────────────────────────────────────────────────────


@router.get(P + "/items/{item_id}/delivery-limits", response_model=Page[LimitOut], dependencies=[READ])
async def list_limits(
    project_id: uuid.UUID, item_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _plant_read(project_id, user_id, session)
    await _run(svc.get_item(project_id, item_id))
    return _page([LimitOut.model_validate(x) for x in await svc.repo.limits(project_id, item_id)])


@router.put(P + "/items/{item_id}/delivery-limits", response_model=Page[LimitOut], dependencies=[EDIT])
async def put_limits(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    body: LimitsIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    """Replace the item's row of the delivery-limit matrix; 409 ``two_parties_on_one_step``."""
    svc = await _plant_edit(project_id, user_id, payload, session)
    rows = await _run(
        svc.put_limits(project_id, item_id, [r.model_dump() for r in body.limits], actor_id=_uid(user_id))
    )
    return _page([LimitOut.model_validate(x) for x in rows])


@router.get(P + "/delivery-limits", response_model=dict[str, Any], dependencies=[READ])
async def limit_matrix(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    """The whole matrix: ``{steps: [code], rows: [{item_id, code, cells: {step: {party, contract_package_id}}}]}``."""
    svc = await _plant_read(project_id, user_id, session)
    cat = await _run(svc.catalogue(project_id))
    items = await svc.repo.items(project_id)
    limits = await svc.repo.limits(project_id)
    rows = []
    for i in items:
        cells = {
            x.step: {
                "party": x.party,
                "contract_package_id": str(x.contract_package_id) if x.contract_package_id else None,
            }
            for x in limits
            if x.plant_item_id == i.id
        }
        rows.append(
            {"item_id": str(i.id), "code": i.code, "title": i.title, "item_class": i.item_class, "cells": cells}
        )
    return {"steps": list(cat.step_codes()), "rows": rows}


# ── spares ────────────────────────────────────────────────────────────────


@router.get(P + "/items/{item_id}/spares", response_model=Page[SpareOut], dependencies=[READ])
async def list_spares(
    project_id: uuid.UUID, item_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _plant_read(project_id, user_id, session)
    await _run(svc.get_item(project_id, item_id))
    return _page([SpareOut.model_validate(s) for s in await svc.repo.spares(project_id, item_id)])


@router.post(P + "/items/{item_id}/spares", response_model=SpareOut, status_code=201, dependencies=[EDIT])
async def create_spare(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    body: SpareIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> SpareOut:
    svc = await _plant_edit(project_id, user_id, payload, session)
    return SpareOut.model_validate(
        await _run(svc.create_spare(project_id, item_id, body.model_dump(exclude_unset=True), actor_id=_uid(user_id)))
    )


@router.patch(P + "/items/{item_id}/spares/{spare_id}", response_model=SpareOut, dependencies=[EDIT])
async def update_spare(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    spare_id: uuid.UUID,
    body: SpareIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> SpareOut:
    svc = await _plant_edit(project_id, user_id, payload, session)
    return SpareOut.model_validate(
        await _run(
            svc.update_spare(project_id, item_id, spare_id, body.model_dump(exclude_unset=True), actor_id=_uid(user_id))
        )
    )


@router.post(P + "/items/{item_id}/spares/{spare_id}/transition", response_model=SpareOut, dependencies=[EDIT])
async def transition_spare(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    spare_id: uuid.UUID,
    body: SpareTransitionIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> SpareOut:
    svc = await _plant_edit(project_id, user_id, payload, session)
    return SpareOut.model_validate(
        await _run(
            svc.transition_spare(project_id, item_id, spare_id, body.target, reason=body.reason, actor_id=_uid(user_id))
        )
    )


@router.delete(P + "/items/{item_id}/spares/{spare_id}", status_code=204, dependencies=[EDIT])
async def delete_spare(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    spare_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> Response:
    svc = await _plant_edit(project_id, user_id, payload, session)
    await _run(svc.delete_spare(project_id, item_id, spare_id, actor_id=_uid(user_id)))
    return Response(status_code=204)


# ── IT services ───────────────────────────────────────────────────────────


@router.get(P + "/it-services", response_model=Page[ItServiceOut], dependencies=[READ])
async def list_it_services(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    svc = await _plant_read(project_id, user_id, session)
    return _page([ItServiceOut.model_validate(r) for r in await svc.repo.it_services(project_id)])


@router.post(P + "/it-services", response_model=ItServiceOut, status_code=201, dependencies=[EDIT])
async def create_it_service(
    project_id: uuid.UUID, body: ItServiceIn, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> ItServiceOut:
    svc = await _plant_edit(project_id, user_id, payload, session)
    return ItServiceOut.model_validate(
        await _run(svc.create_it_service(project_id, body.model_dump(exclude_unset=True), actor_id=_uid(user_id)))
    )


@router.patch(P + "/it-services/{service_id}", response_model=ItServiceOut, dependencies=[EDIT])
async def update_it_service(
    project_id: uuid.UUID,
    service_id: uuid.UUID,
    body: ItServiceIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> ItServiceOut:
    svc = await _plant_edit(project_id, user_id, payload, session)
    return ItServiceOut.model_validate(
        await _run(
            svc.update_it_service(project_id, service_id, body.model_dump(exclude_unset=True), actor_id=_uid(user_id))
        )
    )


@router.post(P + "/it-services/{service_id}/transition", response_model=ItServiceOut, dependencies=[EDIT])
async def transition_it_service(
    project_id: uuid.UUID,
    service_id: uuid.UUID,
    body: TransitionIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> ItServiceOut:
    svc = await _plant_edit(project_id, user_id, payload, session)
    return ItServiceOut.model_validate(
        await _run(svc.transition_it_service(project_id, service_id, body.target, actor_id=_uid(user_id)))
    )


@router.delete(P + "/it-services/{service_id}", status_code=204, dependencies=[EDIT])
async def delete_it_service(
    project_id: uuid.UUID,
    service_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> Response:
    svc = await _plant_edit(project_id, user_id, payload, session)
    await _run(svc.delete_it_service(project_id, service_id, actor_id=_uid(user_id)))
    return Response(status_code=204)


# ── read views ────────────────────────────────────────────────────────────


@router.get(P + "/long-lead", response_model=Page[ItemOut], dependencies=[READ])
async def long_lead(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    today: date | None = None,
) -> dict[str, Any]:
    """Long-lead items with computed dates, least float first."""
    svc = await _plant_read(project_id, user_id, session)
    views = await _run(svc.long_lead(project_id, today=_today(today)))
    return _page([ItemOut.from_view(v) for v in await _with_can(svc, project_id, views, user_id, payload)])


@router.get(P + "/frame-summary", response_model=dict[str, Any], dependencies=[READ])
async def frame_summary(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, today: date | None = None
) -> dict[str, Any]:
    """What the governance frame document of the plant area shows."""
    from fastapi.encoders import jsonable_encoder

    svc = await _plant_read(project_id, user_id, session)
    return jsonable_encoder(await _run(svc.frame_summary(project_id, today=_today(today))))


@router.get(P + "/readiness", response_model=dict[str, Any], dependencies=[READ])
async def readiness(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, today: date | None = None
) -> dict[str, Any]:
    svc = await _plant_read(project_id, user_id, session)
    return await _run(svc.readiness(project_id, today=_today(today)))


@router.get(P + "/validation", response_model=Page[FindingOut], dependencies=[READ])
async def validation(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, today: date | None = None
) -> dict[str, Any]:
    """Run rule set ``plant_register`` against the project's register."""
    from app.modules.plant_register.validators import run_rules

    svc = await _plant_read(project_id, user_id, session)
    payload = await _run(svc.validation_payload(project_id, today=_today(today)))
    return _page([FindingOut(**r) for r in await run_rules(payload, get_locale() or "en")])


@router.post(P + "/escalate", response_model=dict[str, Any], dependencies=[EDIT])
async def escalate(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    """Run the periodic check now: notify due and overdue order dates (rule 7), expire slots (rule 13)."""
    svc = await _plant_edit(project_id, user_id, payload, session)
    return await _run(svc.escalate(project_id, today=_today(None)))


_MEDIA = {"pdf": "application/pdf", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}


@router.get(P + "/export/{kind}", dependencies=[READ])
async def export(
    project_id: uuid.UUID,
    kind: Literal["register", "limits", "spares", "paper", "frame"],
    session: SessionDep,
    user_id: CurrentUserId,
    fmt: Literal["pdf", "xlsx"] = Query("pdf", alias="format"),
    item_id: uuid.UUID | None = None,
) -> Response:
    """PDF or XLSX of the long-lead register, delivery-limit matrix, spares list, one decision paper or the frame summary."""
    from app.modules.plant_register import export as ex
    from app.modules.projects.models import Project

    svc = await _plant_read(project_id, user_id, session)
    project = await session.get(Project, project_id)
    name = getattr(project, "name", "") or ""
    locale = get_locale() or "en"
    today = _today(None)
    if kind == "register":
        doc = ex.register_document(await _run(svc.long_lead(project_id, today=today)), project_name=name, locale=locale)
    elif kind == "limits":
        cat = await _run(svc.catalogue(project_id))
        views = await _run(svc.item_views(project_id, today=today))
        limits: dict[Any, dict[str, str]] = {}
        for x in await svc.repo.limits(project_id):
            limits.setdefault(x.plant_item_id, {})[x.step] = x.party or str(x.contract_package_id or "")
        doc = ex.limits_document(views, limits, cat.step_codes(), project_name=name, locale=locale)
    elif kind == "spares":
        codes = {i.id: i.code for i in await svc.repo.items(project_id)}
        rows = [
            {
                "item_code": codes.get(s.plant_item_id, ""),
                "category": s.category,
                "description": s.description,
                "quantity": s.quantity,
                "unit": s.unit,
                "supply_by": s.supply_by,
                "status": s.status,
            }
            for s in await svc.repo.spares(project_id)
        ]
        doc = ex.spares_document(rows, project_name=name, locale=locale)
    elif kind == "paper":
        if item_id is None:
            await _run(_refuse(PlantError("item_required")))
        item = await _run(svc.get_item(project_id, item_id))
        papers = await svc.repo.papers(project_id, item_id)
        if not papers:
            await _run(_refuse(PlantError("paper_not_found", 404)))
        paper = papers[-1]
        try:
            scores = calc.weighted_scores(paper.options, paper.criteria)
        except (ValueError, ArithmeticError):
            await _run(_refuse(PlantError("paper_scores_invalid")))
        doc = ex.paper_document(paper, scores, item.code, project_name=name, locale=locale)
    else:
        doc = ex.frame_document(
            await _run(svc.frame_summary(project_id, today=today)), project_name=name, locale=locale
        )
    return Response(
        content=ex.render(doc, fmt),
        media_type=_MEDIA[fmt],
        headers={
            "Content-Disposition": f'attachment; filename="plant_{kind}.{fmt}"',
            # The labels come from this module's catalogue, which falls back to
            # English for a language it does not carry: declare what was written.
            "Content-Language": written_locale(locale),
        },
    )


# ── site plant positions ──────────────────────────────────────────────────

SP = P + "/site-plant-positions"


async def _position_can(svc: Any, project_id: uuid.UUID, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return await svc.capabilities(
        project_id, _uid(user_id), can_edit=await _holds(_EDIT_CHECK, payload), can_manage=await _can_manage(payload)
    )


@router.get(SP, response_model=PositionList, dependencies=[READ])
async def list_site_plant_positions(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    stage_id: uuid.UUID | None = None,
    plant_item_id: uuid.UUID | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=1000),
) -> PositionList:
    """Every plant position of the project, for the site plan: point in local metres (y up), reach, item, stage."""
    await verify_project_access(project_id, user_id, session)
    svc = SitePlantService(session)
    can = await _position_can(svc, project_id, user_id, payload)
    views = await _run(svc.listing(project_id, stage_id=stage_id, plant_item_id=plant_item_id))
    return PositionList(
        items=[PositionOut.of(v, can) for v in views[offset : offset + limit]],
        total=len(views),
        offset=offset,
        limit=limit,
        can={"place": can["place"]},
    )


@router.post(SP, response_model=PositionOut, status_code=201, dependencies=[EDIT])
async def place_site_plant_position(
    project_id: uuid.UUID,
    body: PositionCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> PositionOut:
    """Place a piece of site plant, or a register item, on the site plan."""
    await verify_project_access(project_id, user_id, session)
    svc = SitePlantService(session)
    await _run(svc.plant.require_editor(project_id, _uid(user_id), can_manage=await _can_manage(payload)))
    row = await _run(svc.place(project_id, body.changes(), actor_id=_uid(user_id)))
    return PositionOut.of(
        await _run(svc.view(project_id, row.id)), await _position_can(svc, project_id, user_id, payload)
    )


@router.get(SP + "/{position_id}", response_model=PositionOut, dependencies=[READ])
async def get_site_plant_position(
    project_id: uuid.UUID,
    position_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> PositionOut:
    await verify_project_access(project_id, user_id, session)
    svc = SitePlantService(session)
    return PositionOut.of(
        await _run(svc.view(project_id, position_id)), await _position_can(svc, project_id, user_id, payload)
    )


@router.patch(SP + "/{position_id}", response_model=PositionOut, dependencies=[EDIT])
async def move_site_plant_position(
    project_id: uuid.UUID,
    position_id: uuid.UUID,
    body: PositionIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> PositionOut:
    """Move a position (point, stage) or change what it says; only the fields sent change."""
    await verify_project_access(project_id, user_id, session)
    svc = SitePlantService(session)
    await _run(svc.plant.require_editor(project_id, _uid(user_id), can_manage=await _can_manage(payload)))
    await _run(svc.move(project_id, position_id, body.changes(), actor_id=_uid(user_id)))
    return PositionOut.of(
        await _run(svc.view(project_id, position_id)), await _position_can(svc, project_id, user_id, payload)
    )


@router.delete(SP + "/{position_id}", status_code=204, dependencies=[EDIT])
async def remove_site_plant_position(
    project_id: uuid.UUID,
    position_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> Response:
    await verify_project_access(project_id, user_id, session)
    svc = SitePlantService(session)
    await _run(svc.plant.require_editor(project_id, _uid(user_id), can_manage=await _can_manage(payload)))
    await _run(svc.remove(project_id, position_id, actor_id=_uid(user_id)))
    return Response(status_code=204)
