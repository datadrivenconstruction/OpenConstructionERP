"""Customer offer API routes (mounted at ``/api/v1/offers``)."""

from __future__ import annotations

import base64
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Response

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.offers import pack as pack_mod
from app.modules.offers.models import Offer
from app.modules.offers.schemas import (
    AcceptRequest,
    AcceptResponse,
    ContextResponse,
    NumberCheck,
    OfferCreate,
    OfferResponse,
    OfferSummary,
    OfferUpdate,
    PositionRoleIn,
    PreviewResponse,
    SettingsOut,
    SettingsUpdate,
    TextBlockIn,
    TextBlockOut,
    ValidationOut,
)
from app.modules.offers.service import OfferService

router = APIRouter(tags=["offers"])

_READ = Depends(RequirePermission("boq.read"))
_WRITE = Depends(RequirePermission("boq.update"))
_AWARD = Depends(RequirePermission("contracts.create"))


async def _load(session: SessionDep, user_id: str, offer_id: uuid.UUID) -> tuple[OfferService, Offer]:
    service = OfferService(session)
    offer = await service.get(offer_id)
    await verify_project_access(offer.project_id, user_id, session)
    return service, offer


@router.get("/context", response_model=ContextResponse, dependencies=[_READ])
async def context(
    session: SessionDep, user_id: CurrentUserId, project_id: uuid.UUID, boq_id: uuid.UUID
) -> ContextResponse:
    """Everything the offer page needs before an offer exists."""
    await verify_project_access(project_id, user_id, session)
    return ContextResponse.model_validate(await OfferService(session).context(project_id, boq_id))


@router.get("/", response_model=list[OfferSummary], dependencies=[_READ])
async def list_offers(
    session: SessionDep, user_id: CurrentUserId, project_id: uuid.UUID, boq_id: uuid.UUID | None = None
) -> list[OfferSummary]:
    await verify_project_access(project_id, user_id, session)
    service = OfferService(session)
    rows = await (service.repo.list_for_boq(boq_id) if boq_id else service.repo.list_for_project(project_id))
    return [await service._summary(r) for r in rows]


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


@router.get("/texts", response_model=list[TextBlockOut], dependencies=[_READ])
async def list_texts(
    session: SessionDep, user_id: CurrentUserId, project_id: uuid.UUID | None = None, country: str | None = None
) -> list[TextBlockOut]:
    if project_id:
        await verify_project_access(project_id, user_id, session)
    rows = await OfferService(session).list_text_blocks(project_id, pack_mod.pack_for(country, None))
    return [TextBlockOut.model_validate(r) for r in rows]


@router.post("/texts", response_model=TextBlockOut, status_code=201, dependencies=[_WRITE])
async def create_text(data: TextBlockIn, session: SessionDep) -> TextBlockOut:
    return TextBlockOut.model_validate(await OfferService(session).save_text_block(data))


@router.post("/texts/restore", dependencies=[_WRITE])
async def restore_texts(session: SessionDep, country: str | None = Query(None)) -> dict[str, int]:
    """Bring a market's default texts back after they were edited or deleted."""
    return {"restored": await OfferService(session).restore_pack_texts(pack_mod.pack_for(country, None))}


@router.patch("/texts/{block_id}", response_model=TextBlockOut, dependencies=[_WRITE])
async def update_text(block_id: uuid.UUID, data: TextBlockIn, session: SessionDep) -> TextBlockOut:
    return TextBlockOut.model_validate(await OfferService(session).save_text_block(data, block_id))


@router.delete("/texts/{block_id}", status_code=204, dependencies=[_WRITE])
async def delete_text(block_id: uuid.UUID, session: SessionDep) -> Response:
    await OfferService(session).delete_text_block(block_id)
    return Response(status_code=204)


@router.patch("/positions/{position_id}/role", dependencies=[_WRITE])
async def set_position_role(position_id: uuid.UUID, data: PositionRoleIn, session: SessionDep) -> dict[str, Any]:
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
        headers={"Content-Disposition": f'attachment; filename="{offer.number}-{offer.revision}.pdf"'},
    )


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


@router.post("/{offer_id}/accept", response_model=AcceptResponse, dependencies=[_WRITE, _AWARD])
async def accept_offer(
    offer_id: uuid.UUID, data: AcceptRequest, session: SessionDep, user_id: CurrentUserId
) -> AcceptResponse:
    """Record the customer's acceptance and award the work to a client contract."""
    service, _ = await _load(session, user_id, offer_id)
    offer, contract_id, milestones = await service.accept(offer_id, data, user_id)
    return AcceptResponse(offer=await service.response(offer), contract_id=contract_id, milestones=milestones)
