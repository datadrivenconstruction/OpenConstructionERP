"""Customer offer API routes (mounted at ``/api/v1/offers``)."""

from __future__ import annotations

import base64
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    get_current_user_payload,
    verify_project_access,
)
from app.modules.boq.pdf_export import pdf_language
from app.modules.offers import pack as pack_mod
from app.modules.offers.models import Offer
from app.modules.offers.schemas import (
    AcceptRequest,
    AcceptResponse,
    ContextResponse,
    NumberCheck,
    OfferCreate,
    OfferResponse,
    OffersListResponse,
    OfferUpdate,
    PositionRoleIn,
    PreviewResponse,
    SettingsOut,
    SettingsUpdate,
    TextBlockIn,
    TextBlockOut,
    TextBlocksListResponse,
    ValidationOut,
)
from app.modules.offers.service import OfferService

router = APIRouter(tags=["offers"])

_READ = Depends(RequirePermission("boq.read"))
_WRITE = Depends(RequirePermission("boq.update"))


async def _can_award(payload: dict[str, Any] = Depends(get_current_user_payload)) -> bool:
    """Whether the caller may also create the client contract (accepting needs only ``boq.update``)."""
    from app.core.permissions import permission_registry

    role = str(payload.get("role", ""))
    return (
        role == "admin"
        or "contracts.create" in payload.get("permissions", [])
        or permission_registry.role_has_permission(role, "contracts.create")
    )


CanAward = Annotated[bool, Depends(_can_award)]


async def _load(session: SessionDep, user_id: str, offer_id: uuid.UUID) -> tuple[OfferService, Offer]:
    service = OfferService(session)
    offer = await service.get(offer_id)
    await verify_project_access(offer.project_id, user_id, session)
    return service, offer


@router.get("/context", response_model=ContextResponse, dependencies=[_READ])
async def context(
    session: SessionDep, user_id: CurrentUserId, can_award: CanAward, project_id: uuid.UUID, boq_id: uuid.UUID
) -> ContextResponse:
    """Everything the offer page needs before an offer exists."""
    await verify_project_access(project_id, user_id, session)
    data = await OfferService(session).context(project_id, boq_id)
    data["permissions"] = {"create_contract": can_award}
    return ContextResponse.model_validate(data)


@router.get("/", response_model=OffersListResponse, dependencies=[_READ])
async def list_offers(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID,
    boq_id: uuid.UUID | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
) -> OffersListResponse:
    await verify_project_access(project_id, user_id, session)
    service = OfferService(session)
    rows, total = await service.repo.list_page(project_id, boq_id, offset=offset, limit=limit)
    return OffersListResponse(items=[await service._summary(r) for r in rows], total=total, offset=offset, limit=limit)


@router.post("/", response_model=OfferResponse, status_code=201, dependencies=[_WRITE])
async def create_offer(data: OfferCreate, session: SessionDep, user_id: CurrentUserId) -> OfferResponse:
    await verify_project_access(data.project_id, user_id, session)
    service = OfferService(session)
    return await service.response(await service.create(data, user_id))


@router.get("/number-check", response_model=NumberCheck, dependencies=[_READ])
async def number_check(session: SessionDep, number: str, group_id: uuid.UUID | None = None) -> NumberCheck:
    return NumberCheck(number=number, taken=await OfferService(session).repo.number_taken(number, group_id))


@router.get("/settings", response_model=SettingsOut, dependencies=[_READ])
async def get_settings(session: SessionDep) -> SettingsOut:
    service = OfferService(session)
    row = await service.settings()
    return SettingsOut.model_validate(row).model_copy(update={"next_number": await service.next_number()})


@router.patch("/settings", response_model=SettingsOut, dependencies=[_WRITE])
async def update_settings(data: SettingsUpdate, session: SessionDep) -> SettingsOut:
    service = OfferService(session)
    row = await service.update_settings(data)
    return SettingsOut.model_validate(row).model_copy(update={"next_number": await service.next_number()})


@router.get("/texts", response_model=TextBlocksListResponse, dependencies=[_READ])
async def list_texts(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID | None = None,
    country: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
) -> TextBlocksListResponse:
    if project_id:
        await verify_project_access(project_id, user_id, session)
    rows = await OfferService(session).list_text_blocks(project_id, pack_mod.pack_for(country, None))
    return TextBlocksListResponse(
        items=[TextBlockOut.model_validate(r) for r in rows[offset : offset + limit]],
        total=len(rows),
        offset=offset,
        limit=limit,
    )


@router.post("/texts", response_model=TextBlockOut, status_code=201, dependencies=[_WRITE])
async def create_text(data: TextBlockIn, session: SessionDep, user_id: CurrentUserId) -> TextBlockOut:
    if data.project_id is not None:
        await verify_project_access(data.project_id, user_id, session)
    return TextBlockOut.model_validate(await OfferService(session).save_text_block(data))


@router.post("/texts/restore", dependencies=[_WRITE])
async def restore_texts(session: SessionDep, country: str | None = Query(None)) -> dict[str, int]:
    """Bring a market's default texts back after they were edited or deleted."""
    return {"restored": await OfferService(session).restore_pack_texts(pack_mod.pack_for(country, None))}


@router.patch("/texts/{block_id}", response_model=TextBlockOut, dependencies=[_WRITE])
async def update_text(
    block_id: uuid.UUID, data: TextBlockIn, session: SessionDep, user_id: CurrentUserId
) -> TextBlockOut:
    block = await OfferService(session).repo.text_block(block_id)
    if block is None:
        raise HTTPException(status_code=404, detail="Text not found")
    if block.project_id is not None:
        await verify_project_access(block.project_id, user_id, session)
    if data.project_id is not None:
        await verify_project_access(data.project_id, user_id, session)
    return TextBlockOut.model_validate(await OfferService(session).save_text_block(data, block_id))


@router.delete("/texts/{block_id}", status_code=204, dependencies=[_WRITE])
async def delete_text(block_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> Response:
    block = await OfferService(session).repo.text_block(block_id)
    if block is None:
        raise HTTPException(status_code=404, detail="Text not found")
    if block.project_id is not None:
        await verify_project_access(block.project_id, user_id, session)
    await OfferService(session).delete_text_block(block_id)
    return Response(status_code=204)


@router.patch("/positions/{position_id}/role", dependencies=[_WRITE])
async def set_position_role(
    position_id: uuid.UUID, data: PositionRoleIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    from app.modules.boq.models import BOQ, Position

    pos = await session.get(Position, position_id)
    boq = await session.get(BOQ, pos.boq_id) if pos is not None else None
    if boq is None:
        raise HTTPException(status_code=404, detail="Position not found")
    await verify_project_access(boq.project_id, user_id, session)
    return await OfferService(session).set_position_role(position_id, data.role, data.alternative_of, data.by_others)


@router.get("/{offer_id}", response_model=OfferResponse, dependencies=[_READ])
async def get_offer(offer_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> OfferResponse:
    service, offer = await _load(session, user_id, offer_id)
    return await service.response(offer)


@router.patch("/{offer_id}", response_model=OfferResponse, dependencies=[_WRITE])
async def update_offer(
    offer_id: uuid.UUID, data: OfferUpdate, session: SessionDep, user_id: CurrentUserId
) -> OfferResponse:
    service, _ = await _load(session, user_id, offer_id)
    return await service.response(await service.update(offer_id, data))


@router.get("/{offer_id}/validate", response_model=ValidationOut, dependencies=[_READ])
async def validate_offer(offer_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> ValidationOut:
    service, offer = await _load(session, user_id, offer_id)
    return await service.validate(offer)


@router.get("/{offer_id}/preview", response_model=PreviewResponse, dependencies=[_READ])
async def preview_offer(offer_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> PreviewResponse:
    service, offer = await _load(session, user_id, offer_id)
    pdf_bytes, pages = await service.render(offer)
    return PreviewResponse(
        pdf_base64=base64.b64encode(pdf_bytes).decode("ascii"),
        page_count=pages,
        filename=f"{offer.number}-{offer.revision}.pdf",
    )


@router.get("/{offer_id}/pdf", dependencies=[_READ])
async def download_pdf(offer_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> Response:
    service, offer = await _load(session, user_id, offer_id)
    pdf_bytes, _ = await service.render(offer)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{offer.number}-{offer.revision}.pdf"',
            "Content-Language": pdf_language(offer.locale),
        },
    )


@router.post("/{offer_id}/texts/{kind}/reset", response_model=OfferResponse, dependencies=[_WRITE])
async def reset_offer_text(
    offer_id: uuid.UUID, kind: str, session: SessionDep, user_id: CurrentUserId
) -> OfferResponse:
    """Drop this project's override of one text and use the company text again."""
    service, _ = await _load(session, user_id, offer_id)
    return await service.response(await service.reset_text(offer_id, kind))


@router.post("/{offer_id}/send", response_model=OfferResponse, dependencies=[_WRITE])
async def send_offer(offer_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> OfferResponse:
    service, _ = await _load(session, user_id, offer_id)
    return await service.response(await service.send(offer_id))


@router.post("/{offer_id}/revise", response_model=OfferResponse, status_code=201, dependencies=[_WRITE])
async def revise_offer(offer_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> OfferResponse:
    service, _ = await _load(session, user_id, offer_id)
    return await service.response(await service.revise(offer_id, user_id))


@router.post("/{offer_id}/decline", response_model=OfferResponse, dependencies=[_WRITE])
async def decline_offer(offer_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> OfferResponse:
    service, _ = await _load(session, user_id, offer_id)
    return await service.response(await service.decline(offer_id))


@router.post("/{offer_id}/accept", response_model=AcceptResponse, dependencies=[_WRITE])
async def accept_offer(
    offer_id: uuid.UUID, data: AcceptRequest, session: SessionDep, user_id: CurrentUserId, can_award: CanAward
) -> AcceptResponse:
    """Record the customer's acceptance; the client contract needs contracts.create on top of boq.update."""
    service, _ = await _load(session, user_id, offer_id)
    blocked = data.create_contract and not can_award
    if blocked:
        data = data.model_copy(update={"create_contract": False})
    offer, contract_id, milestones = await service.accept(offer_id, data, user_id)
    return AcceptResponse(
        offer=await service.response(offer),
        contract_id=contract_id,
        milestones=milestones,
        contract_blocked="contracts.create" if blocked else None,
    )
