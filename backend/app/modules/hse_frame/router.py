# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""HSE frame API, mounted at ``/api/v1/hse-frame``.

Every route lives under ``/projects/{project_id}/...`` and calls
``verify_project_access`` before it reads anything, so a project the caller
cannot see answers 404 exactly like a missing one. Child rows are looked up by
``(project_id, id)`` and linked records are resolved inside the project, so an
id from another project is also 404.

Errors carry ``{"code", "message_key", "message", "violations"?, "info"?}`` in
``detail``; ``message_key`` is ``hse_frame.errors.<code>``. 404 = not found or
not visible, 403 = visible but not allowed (four-eyes), 409 = state conflict,
422 = invalid input or a refusing rule (``violations`` lists every finding).
Lists are ``{items, total, offset, limit}``.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable
from datetime import UTC, date, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm.exc import StaleDataError

from app.core.i18n import get_locale
from app.core.tenant_scope import resolve_tenant_id
from app.dependencies import CurrentUserId, CurrentUserPayload, RequirePermission, SessionDep, verify_project_access
from app.modules.hse_frame import links as link_resolvers
from app.modules.hse_frame import schemas as s
from app.modules.hse_frame.errors import HseFrameError
from app.modules.hse_frame.messages import translate
from app.modules.hse_frame.models import HseFrame
from app.modules.hse_frame.service import HseFrameService
from app.modules.hse_frame.vocab import ITEM_STATUSES

router = APIRouter(tags=["hse_frame"])

READ = Depends(RequirePermission("hse_frame.read"))
EDIT = Depends(RequirePermission("hse_frame.edit"))
MANAGE = Depends(RequirePermission("hse_frame.manage"))
APPROVE = Depends(RequirePermission("hse_frame.approve"))
P = "/projects/{project_id}"


async def _run[T](awaitable: Awaitable[T]) -> T:
    try:
        return await awaitable
    except StaleDataError as exc:
        key = "hse_frame.errors.concurrent_update"
        detail = {
            "code": "concurrent_update",
            "message_key": key,
            "message": translate(key, locale=get_locale() or "en"),
        }
        raise HTTPException(status_code=409, detail=detail) from exc
    except HseFrameError as exc:
        message = translate(f"hse_frame.errors.{exc.code}", locale=get_locale() or "en")
        raise HTTPException(status_code=exc.status_code, detail=exc.as_detail(message)) from exc
    except HTTPException as exc:
        if isinstance(exc.detail, dict) and exc.detail.get("code"):
            raise
        # A neighbouring module refused in its own words; the screens read a code and a key.
        key = "hse_frame.errors.neighbour_refused"
        detail = {
            "code": "neighbour_refused",
            "message_key": key,
            "message": translate(key, locale=get_locale() or "en"),
            "detail": exc.detail if isinstance(exc.detail, str) else str(exc.detail),
        }
        raise HTTPException(status_code=exc.status_code, detail=detail, headers=exc.headers) from exc


def _uid(user_id: str) -> uuid.UUID:
    return uuid.UUID(str(user_id))


def _today(value: date | None) -> date:
    return value or datetime.now(UTC).date()


def _page(items: list[Any], offset: int = 0, limit: int | None = None) -> dict[str, Any]:
    total = len(items)
    lim = limit or max(total, 1)
    return {"items": items[offset : offset + lim], "total": total, "offset": offset, "limit": lim}


async def _svc(project_id: uuid.UUID, user_id: str, session: Any) -> HseFrameService:
    await verify_project_access(project_id, user_id, session)
    return HseFrameService(session)


def _frame_out(row: HseFrame) -> dict[str, Any]:
    return s.FrameOut.model_validate(row).model_dump(mode="json")


# ── frame ──────────────────────────────────────────────────────────────────


@router.get(P + "/frame", dependencies=[READ])
async def get_frame(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    """The frame, its duties and the pinned catalogue's name; ``frame`` is null before the first write."""
    svc = await _svc(project_id, user_id, session)
    row = await svc.frame(project_id)
    catalogue = await _run(svc.project_catalogue(project_id))
    duties = svc.duties_of(row, catalogue) if row is not None else None
    return {
        "frame": _frame_out(row) if row is not None else None,
        "catalogue": {"id": catalogue.id, "labels": catalogue.labels, "jurisdiction": catalogue.jurisdiction},
        "duties": None
        if duties is None
        else {
            "advance_notice": duties.advance_notice,
            "coordinator": duties.coordinator,
            "plan": duties.plan,
            "later_works_file": duties.later_works_file,
            "hazardous_work": duties.hazardous_work,
        },
    }


@router.post(P + "/frame", dependencies=[EDIT], status_code=201)
async def create_frame(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    svc = await _svc(project_id, user_id, session)
    return _frame_out(await _run(svc.ensure_frame(project_id, _uid(user_id))))


@router.patch(P + "/frame", dependencies=[EDIT])
async def patch_frame(
    project_id: uuid.UUID, data: s.FramePatch, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _svc(project_id, user_id, session)
    return _frame_out(await _run(svc.patch_frame(project_id, data, _uid(user_id))))


@router.get(P + "/catalogue", dependencies=[READ])
async def get_catalogue(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    """The pinned catalogue with its parents merged: what the screens offer as topics, roles and templates."""
    svc = await _svc(project_id, user_id, session)
    catalogue = await _run(svc.project_catalogue(project_id))
    body = catalogue.model_dump(mode="json")
    body["link_kinds"] = list(link_resolvers.known_kinds())
    body["item_statuses"] = list(ITEM_STATUSES)
    return body


@router.get(P + "/catalogues", dependencies=[READ])
async def list_catalogues(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    """Catalogues the caller may pin: shipped, the active pack's and the company's own."""
    svc = await _svc(project_id, user_id, session)
    frame = await svc.frame(project_id)
    items = await _run(svc.available_catalogues(resolve_tenant_id(payload), project_id))
    for item in items:
        item["pinned"] = frame is not None and (item["source"], item["id"]) == (
            frame.catalogue_source,
            frame.catalogue_id,
        )
    return _page(items)


@router.put(P + "/frame/catalogue", dependencies=[MANAGE])
async def pin_catalogue(
    project_id: uuid.UUID,
    data: s.PinCatalogue,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    svc = await _svc(project_id, user_id, session)
    row = await _run(
        svc.pin_catalogue(
            project_id, resolve_tenant_id(payload), data.source, data.catalogue_id, data.version, _uid(user_id)
        )
    )
    return _frame_out(row)


@router.post(P + "/frame/apply-templates", dependencies=[MANAGE])
async def apply_templates(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, int]:
    svc = await _svc(project_id, user_id, session)
    return await _run(svc.apply_templates(project_id, _uid(user_id)))


@router.post(P + "/frame/consolidate-permit-conditions", dependencies=[EDIT])
async def consolidate_permit_conditions(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> dict[str, int]:
    svc = await _svc(project_id, user_id, session)
    return await _run(svc.consolidate_permit_conditions(project_id, _uid(user_id)))


@router.post(P + "/frame/submit", dependencies=[MANAGE])
async def submit_frame(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, today: date | None = None
) -> dict[str, Any]:
    svc = await _svc(project_id, user_id, session)
    return _frame_out(await _run(svc.submit(project_id, _uid(user_id), _today(today))))


@router.post(P + "/frame/approve", dependencies=[APPROVE])
async def approve_frame(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    svc = await _svc(project_id, user_id, session)
    return _frame_out(await _run(svc.approve(project_id, _uid(user_id))))


@router.post(P + "/frame/revise", dependencies=[MANAGE])
async def revise_frame(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, body: s.ReviewDecision | None = None
) -> dict[str, Any]:
    svc = await _svc(project_id, user_id, session)
    return _frame_out(await _run(svc.revise(project_id, _uid(user_id), body.note if body else "")))


# ── items ──────────────────────────────────────────────────────────────────


@router.get(P + "/items", dependencies=[READ])
async def list_items(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    topic: str | None = None,
    status: str | None = None,
    today: date | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int | None = Query(default=None, ge=1, le=1000),
) -> dict[str, Any]:
    svc = await _svc(project_id, user_id, session)
    filters = {k: v for k, v in (("topic", topic), ("status", status)) if v}
    items = await _run(svc.list_items(project_id, _today(today), **filters))
    return _page(items, offset, limit)


@router.post(P + "/items", dependencies=[EDIT], status_code=201)
async def create_item(
    project_id: uuid.UUID, data: s.ItemCreate, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _svc(project_id, user_id, session)
    row = await _run(svc.create_item(project_id, data, _uid(user_id)))
    return await svc.item_view(project_id, row.id)


@router.get(P + "/items/{item_id}", dependencies=[READ])
async def get_item(
    project_id: uuid.UUID, item_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _svc(project_id, user_id, session)
    return await _run(svc.item_view(project_id, item_id))


@router.patch(P + "/items/{item_id}", dependencies=[EDIT])
async def patch_item(
    project_id: uuid.UUID, item_id: uuid.UUID, data: s.ItemPatch, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _svc(project_id, user_id, session)
    await _run(svc.patch_item(project_id, item_id, data))
    return await svc.item_view(project_id, item_id)


@router.post(P + "/items/{item_id}/meet", dependencies=[EDIT])
async def meet_item(
    project_id: uuid.UUID, item_id: uuid.UUID, data: s.ItemMeet, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _svc(project_id, user_id, session)
    await _run(svc.meet_item(project_id, item_id, data))
    return await svc.item_view(project_id, item_id)


@router.post(P + "/items/{item_id}/waive", dependencies=[MANAGE])
async def waive_item(
    project_id: uuid.UUID, item_id: uuid.UUID, data: s.ItemWaive, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _svc(project_id, user_id, session)
    await _run(svc.waive_item(project_id, item_id, data, _uid(user_id)))
    return await svc.item_view(project_id, item_id)


@router.post(P + "/items/{item_id}/reopen", dependencies=[EDIT])
async def reopen_item(
    project_id: uuid.UUID, item_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _svc(project_id, user_id, session)
    await _run(svc.reopen_item(project_id, item_id))
    return await svc.item_view(project_id, item_id)


@router.delete(P + "/items/{item_id}", dependencies=[EDIT], status_code=204)
async def delete_item(project_id: uuid.UUID, item_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> None:
    svc = await _svc(project_id, user_id, session)
    await _run(svc.delete_item(project_id, item_id))


@router.post(P + "/items/{item_id}/links", dependencies=[EDIT], status_code=201)
async def add_link(
    project_id: uuid.UUID, item_id: uuid.UUID, data: s.LinkCreate, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _svc(project_id, user_id, session)
    await _run(svc.add_link(project_id, item_id, data, _uid(user_id)))
    return await svc.item_view(project_id, item_id)


@router.delete(P + "/items/{item_id}/links/{link_id}", dependencies=[EDIT], status_code=204)
async def remove_link(
    project_id: uuid.UUID, item_id: uuid.UUID, link_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> None:
    svc = await _svc(project_id, user_id, session)
    await _run(svc.remove_link(project_id, item_id, link_id))


@router.get(P + "/link-candidates", dependencies=[READ])
async def link_candidates(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    kind: str,
    q: str = "",
) -> dict[str, Any]:
    """Records of one kind in this project that an item can be linked to."""
    await _svc(project_id, user_id, session)
    return _page(await link_resolvers.candidates(session, project_id, kind, q))


# ── roles ──────────────────────────────────────────────────────────────────


@router.get(P + "/roles", dependencies=[READ])
async def list_roles(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, today: date | None = None
) -> dict[str, Any]:
    svc = await _svc(project_id, user_id, session)
    return _page(await _run(svc.list_roles(project_id, _today(today))))


@router.post(P + "/roles", dependencies=[EDIT], status_code=201)
async def create_role(
    project_id: uuid.UUID, data: s.RoleCreate, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _svc(project_id, user_id, session)
    row = await _run(svc.create_role(project_id, data, _uid(user_id)))
    return next(r for r in await svc.list_roles(project_id) if r["id"] == row.id)


@router.patch(P + "/roles/{role_id}", dependencies=[EDIT])
async def patch_role(
    project_id: uuid.UUID, role_id: uuid.UUID, data: s.RolePatch, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _svc(project_id, user_id, session)
    await _run(svc.patch_role(project_id, role_id, data))
    return next(r for r in await svc.list_roles(project_id) if r["id"] == role_id)


@router.delete(P + "/roles/{role_id}", dependencies=[EDIT], status_code=204)
async def delete_role(project_id: uuid.UUID, role_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> None:
    svc = await _svc(project_id, user_id, session)
    await _run(svc.delete_role(project_id, role_id))


# ── readiness, summary, validation ─────────────────────────────────────────


@router.get(P + "/readiness", dependencies=[READ])
async def readiness(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, today: date | None = None
) -> dict[str, Any]:
    svc = await _svc(project_id, user_id, session)
    return await _run(svc.readiness(project_id, _today(today)))


@router.get(P + "/summary", dependencies=[READ])
async def summary(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, today: date | None = None
) -> dict[str, Any]:
    """Counts read from safety, hse_advanced, construction_control and permits now."""
    svc = await _svc(project_id, user_id, session)
    return await _run(svc.linked_summary(project_id, _today(today)))


@router.get(P + "/validation", dependencies=[READ])
async def validation(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, today: date | None = None
) -> dict[str, Any]:
    from app.core.validation.engine import ValidationContext, rule_registry
    from app.modules.hse_frame.validators import HSE_FRAME_RULE_SET

    svc = await _svc(project_id, user_id, session)
    data = await _run(svc.validation_payload(project_id, _today(today)))
    context = ValidationContext(data=data, metadata={"locale": get_locale() or "en"})
    items = []
    for rule in rule_registry.get_rules_for_sets([HSE_FRAME_RULE_SET]):
        for r in await rule.validate(context):
            items.append(
                {
                    "rule_id": r.rule_id,
                    "passed": r.passed,
                    "severity": getattr(r.severity, "value", r.severity),
                    "message": r.message,
                    "element_ref": r.element_ref,
                    "suggestion": r.suggestion,
                }
            )
    return _page(items)


@router.get(P + "/export", dependencies=[READ], response_model=None)
async def export(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    what: Literal["register", "roles"] = Query(default="register"),
    format: Literal["pdf", "xlsx"] = Query(default="xlsx"),
) -> Response:
    """The requirements register or the responsibilities as a printable document."""
    from app.modules.hse_frame.export import render, rendered_language

    svc = await _svc(project_id, user_id, session)
    locale = get_locale() or "en"
    data = await _run(render(svc, project_id, what=what, fmt=format, locale=locale))
    media = (
        "application/pdf" if format == "pdf" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    return Response(
        content=data,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="hse_{what}.{format}"',
            "Content-Language": rendered_language(locale),
        },
    )
