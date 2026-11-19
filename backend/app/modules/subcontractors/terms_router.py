# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Routes for levies, payment discount, deduction statements and the bidder radius search.

Mounted inside the subcontractors router (``/api/v1/subcontractors/...``).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query

from app.dependencies import (
    CurrentUserId,
    CurrentUserPayload,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.subcontractors.terms_schemas import (
    BidderSearchResponse,
    DeductionStatementResponse,
    FavouriteIn,
    FavouriteListResponse,
    FavouriteResponse,
    FirmLocationIn,
    FirmLocationResponse,
    LevyCatalogueItemIn,
    LevyCatalogueItemResponse,
    LevyCatalogueResponse,
    SubcontractTermsIn,
    SubcontractTermsResponse,
)
from app.modules.subcontractors.terms_service import SubcontractTermsService

terms_router = APIRouter(tags=["subcontractors-terms"])


async def _agreement_access(agreement_id: uuid.UUID, user_id: str, session: SessionDep) -> None:
    from app.modules.subcontractors.models import SubcontractAgreement

    agreement = await session.get(SubcontractAgreement, agreement_id)
    if agreement is not None:
        await verify_project_access(agreement.project_id, user_id, session)


# ── Levy catalogue (company configuration) ───────────────────────────────


@terms_router.get("/levy-catalogue", response_model=LevyCatalogueResponse)
async def get_levy_catalogue(
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    _perm: None = Depends(RequirePermission("subcontractors.read")),
) -> LevyCatalogueResponse:
    """The company's levies, and the levy names the workspace's country packs suggest."""
    svc = SubcontractTermsService(session)
    items = await svc.list_catalogue()
    return LevyCatalogueResponse(
        items=[LevyCatalogueItemResponse.model_validate(i) for i in items],
        pack_defaults=await svc.catalogue_defaults_for(dict(payload), user_id, items),
    )


@terms_router.post("/levy-catalogue", response_model=LevyCatalogueItemResponse, status_code=201)
async def create_levy(
    data: LevyCatalogueItemIn,
    session: SessionDep,
    _user: CurrentUserId,
    _perm: None = Depends(RequirePermission("subcontractors.configure_levies")),
) -> LevyCatalogueItemResponse:
    """Add a levy to the company catalogue."""
    entity = await SubcontractTermsService(session).create_catalogue_item(data)
    await session.commit()
    return LevyCatalogueItemResponse.model_validate(entity)


@terms_router.put("/levy-catalogue/{item_id}", response_model=LevyCatalogueItemResponse)
async def update_levy(
    item_id: uuid.UUID,
    data: LevyCatalogueItemIn,
    session: SessionDep,
    _user: CurrentUserId,
    _perm: None = Depends(RequirePermission("subcontractors.configure_levies")),
) -> LevyCatalogueItemResponse:
    """Change a catalogue levy; subcontracts keep the rate they agreed."""
    entity = await SubcontractTermsService(session).update_catalogue_item(item_id, data)
    await session.commit()
    return LevyCatalogueItemResponse.model_validate(entity)


@terms_router.delete("/levy-catalogue/{item_id}", status_code=204)
async def delete_levy(
    item_id: uuid.UUID,
    session: SessionDep,
    _user: CurrentUserId,
    _perm: None = Depends(RequirePermission("subcontractors.configure_levies")),
) -> None:
    """Remove a levy from the catalogue; subcontracts keep their copy."""
    await SubcontractTermsService(session).delete_catalogue_item(item_id)
    await session.commit()


@terms_router.post("/levy-catalogue/import-pack")
async def import_pack_levies(
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    _perm: None = Depends(RequirePermission("subcontractors.configure_levies")),
) -> dict[str, int]:
    """Copy the pack's levy names into the catalogue, inactive and without a rate."""
    svc = SubcontractTermsService(session)
    defaults = await svc.catalogue_defaults_for(dict(payload), user_id, await svc.list_catalogue())
    added = await svc.import_pack_defaults(defaults)
    await session.commit()
    return {"added": added}


# ── Subcontract terms and deduction statements ───────────────────────────


@terms_router.get("/agreements/{agreement_id}/terms", response_model=SubcontractTermsResponse)
async def get_agreement_terms(
    agreement_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("subcontractors.read")),
) -> SubcontractTermsResponse:
    """Levies, retention cap, deduction order and payment discount of a subcontract."""
    await _agreement_access(agreement_id, user_id, session)
    return await SubcontractTermsService(session).get_terms(agreement_id)


@terms_router.put("/agreements/{agreement_id}/terms", response_model=SubcontractTermsResponse)
async def put_agreement_terms(
    agreement_id: uuid.UUID,
    data: SubcontractTermsIn,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("subcontractors.update")),
) -> SubcontractTermsResponse:
    """Replace the deduction terms of a subcontract."""
    await _agreement_access(agreement_id, user_id, session)
    out = await SubcontractTermsService(session).put_terms(agreement_id, data, user_id)
    await session.commit()
    return out


@terms_router.get("/agreements/{agreement_id}/deductions", response_model=DeductionStatementResponse)
async def get_deductions(
    agreement_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payment_application_id: uuid.UUID | None = Query(default=None),
    work_value: Decimal | None = Query(default=None, ge=0, le=Decimal("1e15")),
    final_account: bool = Query(default=False),
    invoice_date: date | None = Query(default=None),
    paid_on: date | None = Query(default=None),
    _perm: None = Depends(RequirePermission("subcontractors.read")),
) -> DeductionStatementResponse:
    """Work value, levies, retention, payable and payment discount, line by line."""
    await _agreement_access(agreement_id, user_id, session)
    statement = await SubcontractTermsService(session).deduction_statement(
        agreement_id,
        payment_application_id=payment_application_id,
        work_value=work_value,
        final_account=final_account,
        invoice_date=invoice_date,
        paid_on=paid_on,
    )
    return DeductionStatementResponse.model_validate(statement)


@terms_router.post(
    "/agreements/{agreement_id}/payment-applications/{payment_application_id}/deductions",
    response_model=DeductionStatementResponse,
)
async def record_deductions(
    agreement_id: uuid.UUID,
    payment_application_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("subcontractors.update")),
) -> DeductionStatementResponse:
    """Record the statement on the payment application as it stands today."""
    await _agreement_access(agreement_id, user_id, session)
    statement = await SubcontractTermsService(session).record_deductions(agreement_id, payment_application_id)
    await session.commit()
    return DeductionStatementResponse.model_validate(statement)


# ── Bidder search: radius around the site, favourites per trade ──────────


@terms_router.get("/bidder-search", response_model=BidderSearchResponse)
async def bidder_search(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID | None = Query(default=None),
    trade: str | None = Query(default=None, max_length=120),
    radius_km: Decimal | None = Query(default=None, gt=0, le=20000),
    favourites_only: bool = Query(default=False),
    include_outside: bool = Query(default=False),
    search: str | None = Query(default=None, max_length=200),
    _perm: None = Depends(RequirePermission("subcontractors.read")),
) -> BidderSearchResponse:
    """Firms for a trade, nearest to the project site first; blocked firms are hidden."""
    if project_id is not None:
        await verify_project_access(project_id, user_id, session)
    return await SubcontractTermsService(session).search_bidders(
        project_id=project_id,
        trade=trade or None,
        radius_km=radius_km,
        favourites_only=favourites_only,
        include_outside=include_outside,
        search=search,
    )


@terms_router.get("/subcontractors/{sub_id}/location", response_model=FirmLocationResponse)
async def get_firm_location(
    sub_id: uuid.UUID,
    session: SessionDep,
    _user: CurrentUserId,
    _perm: None = Depends(RequirePermission("subcontractors.read")),
) -> FirmLocationResponse:
    """Where the firm is, or why its coordinates are not known."""
    return await SubcontractTermsService(session).get_location(sub_id)


@terms_router.put("/subcontractors/{sub_id}/location", response_model=FirmLocationResponse)
async def put_firm_location(
    sub_id: uuid.UUID,
    data: FirmLocationIn,
    session: SessionDep,
    _user: CurrentUserId,
    _perm: None = Depends(RequirePermission("subcontractors.update")),
) -> FirmLocationResponse:
    """Set the firm's coordinates by hand."""
    out = await SubcontractTermsService(session).set_location(sub_id, data.lat, data.lon)
    await session.commit()
    return out


@terms_router.post("/subcontractors/{sub_id}/geocode", response_model=FirmLocationResponse)
async def geocode_firm(
    sub_id: uuid.UUID,
    session: SessionDep,
    _user: CurrentUserId,
    _perm: None = Depends(RequirePermission("subcontractors.update")),
) -> FirmLocationResponse:
    """Locate the firm from its address; offline installs answer with the reason instead."""
    out = await SubcontractTermsService(session).geocode(sub_id)
    await session.commit()
    return out


@terms_router.get("/favourites", response_model=FavouriteListResponse)
async def list_favourites(
    session: SessionDep,
    _user: CurrentUserId,
    trade: str | None = Query(default=None, max_length=120),
    _perm: None = Depends(RequirePermission("subcontractors.read")),
) -> FavouriteListResponse:
    """Favourite firms, per trade."""
    rows = await SubcontractTermsService(session).list_favourites(trade)
    items = [FavouriteResponse(subcontractor_id=str(r.subcontractor_id), trade=r.trade) for r in rows]
    return FavouriteListResponse(items=items, total=len(items), limit=max(len(items), 1))


@terms_router.post("/favourites", status_code=204)
async def add_favourite(
    data: FavouriteIn,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("subcontractors.update")),
) -> None:
    """Mark a firm as favourite for a trade."""
    await SubcontractTermsService(session).add_favourite(data.subcontractor_id, data.trade.strip(), user_id)
    await session.commit()


@terms_router.delete("/favourites", status_code=204)
async def remove_favourite(
    session: SessionDep,
    _user: CurrentUserId,
    subcontractor_id: uuid.UUID = Query(...),
    trade: str = Query(..., min_length=1, max_length=120),
    _perm: None = Depends(RequirePermission("subcontractors.update")),
) -> None:
    """Unmark a favourite."""
    await SubcontractTermsService(session).remove_favourite(subcontractor_id, trade.strip())
    await session.commit()
