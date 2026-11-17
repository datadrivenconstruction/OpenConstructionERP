# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Sealed estimate API, mounted at /api/v1/estimate-archive.

There is no PATCH and no DELETE on a seal: every such verb answers 409.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.dependencies import (
    CurrentUserId,
    CurrentUserPayload,
    RequirePermission,
    SessionDep,
    accessible_project_ids,
    verify_project_access,
)
from app.modules.estimate_archive.models import EstimateSeal
from app.modules.estimate_archive.schemas import (
    ChangeOrderRateFill,
    ChangeOrderRateFilled,
    ContentsOut,
    DerivationChoose,
    DerivationCreate,
    DerivationList,
    DerivationOut,
    DeriveRequest,
    DeriveResult,
    EventList,
    EventOut,
    ExternalReceiptCreate,
    FindingPage,
    OpeningClose,
    OpeningCreate,
    OpeningList,
    OpeningOut,
    OpeningStart,
    Policy,
    ReceiptOut,
    SealCreate,
    SealDetail,
    SealKpis,
    SealList,
    SealPreview,
    SupersedeCreate,
    VerifyResult,
)
from app.modules.estimate_archive.service import EstimateArchiveService, refused

router = APIRouter(tags=["estimate_archive"])


def _service(session: SessionDep) -> EstimateArchiveService:
    return EstimateArchiveService(session)


async def _seal(svc: EstimateArchiveService, seal_id: uuid.UUID, user_id: str) -> EstimateSeal:
    """The seal, once the caller is shown to reach its project; 404 otherwise."""
    seal = await svc.repo.get_seal(seal_id)
    if seal is None:
        raise HTTPException(status_code=404, detail="Sealed estimate not found")
    await verify_project_access(seal.project_id, user_id, svc.session)
    return seal


async def _opening(svc: EstimateArchiveService, opening_id: uuid.UUID, user_id: str) -> None:
    opening = await svc.repo.get_opening(opening_id)
    if opening is None:
        raise HTTPException(status_code=404, detail="Opening not found")
    await _seal(svc, opening.seal_id, user_id)


async def _listed_seals(
    svc: EstimateArchiveService,
    user_id: str,
    *,
    project_id: uuid.UUID | None = None,
    contract_id: uuid.UUID | None = None,
    status: str | None = None,
) -> list[EstimateSeal]:
    """Seals of the projects the caller reaches, narrowed to ``project_id`` when one is named."""
    if project_id is not None:
        await verify_project_access(project_id, user_id, svc.session)
    return await svc.repo.list_seals(
        project_ids=await accessible_project_ids(svc.session, user_id),
        project_id=project_id,
        contract_id=contract_id,
        status=status,
    )


async def _derivation_out(svc: EstimateArchiveService, row: object) -> DerivationOut:
    out = DerivationOut.model_validate(row)
    seal = await svc.repo.get_seal(out.seal_id)
    claimed = (
        await svc.variation_markups(seal.project_id, out.variation_request_id)
        if seal is not None and out.variation_request_id is not None
        else None
    )
    out.findings = await svc.pricing_findings(seal, out.result, out.basis_method, claimed_markups=claimed)
    return out


@router.get("/policy", response_model=Policy)
async def project_policy(
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    _perm: None = Depends(RequirePermission("estimate_archive.read")),
    svc: EstimateArchiveService = Depends(_service),
) -> Policy:
    await verify_project_access(project_id, user_id, svc.session)
    return await svc.policy_for(project_id, await svc.client_contract(project_id))


@router.get("/seals", response_model=SealList)
async def list_seals(
    user_id: CurrentUserId,
    project_id: uuid.UUID | None = Query(default=None),
    contract_id: uuid.UUID | None = Query(default=None),
    status: str | None = Query(default=None, max_length=30),
    _perm: None = Depends(RequirePermission("estimate_archive.read")),
    svc: EstimateArchiveService = Depends(_service),
) -> SealList:
    seals = await _listed_seals(svc, user_id, project_id=project_id, contract_id=contract_id, status=status)
    return SealList(items=await svc.summaries(seals), total=len(seals))


@router.get("/kpis", response_model=SealKpis)
async def kpis(
    user_id: CurrentUserId,
    project_id: uuid.UUID | None = Query(default=None),
    _perm: None = Depends(RequirePermission("estimate_archive.read")),
    svc: EstimateArchiveService = Depends(_service),
) -> SealKpis:
    return await svc.kpis(await _listed_seals(svc, user_id, project_id=project_id))


@router.post("/seals/preview", response_model=SealPreview)
async def preview_seal(
    data: SealCreate,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("estimate_archive.seal")),
    svc: EstimateArchiveService = Depends(_service),
) -> SealPreview:
    return await svc.preview(data, user_id)


@router.post("/seals", response_model=SealDetail, status_code=201)
async def create_seal(
    data: SealCreate,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    _perm: None = Depends(RequirePermission("estimate_archive.seal")),
    svc: EstimateArchiveService = Depends(_service),
) -> SealDetail:
    seal = await svc.create_seal(data, user_id)
    return await svc.detail(seal, payload)


@router.get("/seals/{seal_id}", response_model=SealDetail)
async def get_seal(
    seal_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    _perm: None = Depends(RequirePermission("estimate_archive.read")),
    svc: EstimateArchiveService = Depends(_service),
) -> SealDetail:
    return await svc.detail(await _seal(svc, seal_id, user_id), payload)


@router.patch("/seals/{seal_id}", status_code=409)
@router.put("/seals/{seal_id}", status_code=409)
@router.delete("/seals/{seal_id}", status_code=409)
async def mutate_seal(
    seal_id: uuid.UUID,
    user_id: CurrentUserId,
    svc: EstimateArchiveService = Depends(_service),
) -> None:
    await _seal(svc, seal_id, user_id)
    raise refused()


@router.post("/seals/{seal_id}/supersede", response_model=SealDetail, status_code=201)
async def supersede_seal(
    seal_id: uuid.UUID,
    data: SupersedeCreate,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    _perm: None = Depends(RequirePermission("estimate_archive.seal")),
    svc: EstimateArchiveService = Depends(_service),
) -> SealDetail:
    old = await _seal(svc, seal_id, user_id)
    if old.status == "superseded":
        raise refused()
    seal = await svc.create_seal(data, user_id, supersedes=old, reason=data.reason)
    return await svc.detail(seal, payload)


@router.post("/seals/{seal_id}/verify", response_model=VerifyResult)
async def verify_seal(
    seal_id: uuid.UUID,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("estimate_archive.read")),
    svc: EstimateArchiveService = Depends(_service),
) -> VerifyResult:
    return await svc.verify(await _seal(svc, seal_id, user_id), user_id)


@router.post("/seals/{seal_id}/attachments/{attachment_id}/verify")
async def verify_attachment(
    seal_id: uuid.UUID,
    attachment_id: uuid.UUID,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("estimate_archive.read")),
    svc: EstimateArchiveService = Depends(_service),
) -> dict:
    return await svc.check_attachment(await _seal(svc, seal_id, user_id), attachment_id, user_id)


@router.get("/seals/{seal_id}/contents", response_model=ContentsOut)
async def seal_contents(
    seal_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    _perm: None = Depends(RequirePermission("estimate_archive.read")),
    svc: EstimateArchiveService = Depends(_service),
) -> ContentsOut:
    return await svc.contents(await _seal(svc, seal_id, user_id), user_id, payload)


@router.post("/seals/{seal_id}/positions/{ordinal}/viewed", status_code=204)
async def position_viewed(
    seal_id: uuid.UUID,
    ordinal: str,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("estimate_archive.read")),
    svc: EstimateArchiveService = Depends(_service),
) -> Response:
    await svc.log_position_view(await _seal(svc, seal_id, user_id), ordinal, user_id)
    return Response(status_code=204)


@router.get("/seals/{seal_id}/events", response_model=EventList)
async def seal_events(
    seal_id: uuid.UUID,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("estimate_archive.read")),
    svc: EstimateArchiveService = Depends(_service),
) -> EventList:
    seal = await _seal(svc, seal_id, user_id)
    rows = await svc.repo.events(seal_ids=[seal.id])
    return EventList(items=[EventOut.model_validate(r) for r in rows], total=len(rows))


@router.get("/events", response_model=EventList)
async def all_events(
    user_id: CurrentUserId,
    project_id: uuid.UUID | None = Query(default=None),
    event_type: str | None = Query(default=None, max_length=40),
    actor_id: uuid.UUID | None = Query(default=None),
    _perm: None = Depends(RequirePermission("estimate_archive.read")),
    svc: EstimateArchiveService = Depends(_service),
) -> EventList:
    seals = await _listed_seals(svc, user_id, project_id=project_id)
    rows = await svc.repo.events(seal_ids=[s.id for s in seals], event_type=event_type, actor_id=actor_id)
    return EventList(items=[EventOut.model_validate(r) for r in rows], total=len(rows))


@router.get("/seals/{seal_id}/package")
async def deposit_package(
    seal_id: uuid.UUID,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("estimate_archive.read_sealed")),
    svc: EstimateArchiveService = Depends(_service),
) -> Response:
    seal = await _seal(svc, seal_id, user_id)
    body = await svc.deposit_package(seal, user_id)
    return Response(
        content=body,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="sealed-estimate-{str(seal.id)[:8]}.zip"'},
    )


# ── Receipt ──────────────────────────────────────────────────────────────────


@router.post("/seals/{seal_id}/receipt", response_model=ReceiptOut, status_code=201)
async def request_receipt(
    seal_id: uuid.UUID,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("estimate_archive.seal")),
    svc: EstimateArchiveService = Depends(_service),
) -> ReceiptOut:
    seal = await _seal(svc, seal_id, user_id)
    return ReceiptOut.model_validate(await svc.request_receipt(seal, user_id))


@router.post("/seals/{seal_id}/receipt/external", response_model=ReceiptOut, status_code=201)
async def external_receipt(
    seal_id: uuid.UUID,
    data: ExternalReceiptCreate,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("estimate_archive.seal")),
    svc: EstimateArchiveService = Depends(_service),
) -> ReceiptOut:
    seal = await _seal(svc, seal_id, user_id)
    row = await svc.record_external_receipt(seal, data.external_reference, data.receipt_document_id, user_id)
    return ReceiptOut.model_validate(row)


# ── Openings ─────────────────────────────────────────────────────────────────


@router.get("/openings", response_model=OpeningList)
async def list_openings(
    user_id: CurrentUserId,
    project_id: uuid.UUID | None = Query(default=None),
    seal_id: uuid.UUID | None = Query(default=None),
    status: str | None = Query(default=None, max_length=20),
    _perm: None = Depends(RequirePermission("estimate_archive.read")),
    svc: EstimateArchiveService = Depends(_service),
) -> OpeningList:
    if seal_id is not None:
        seal_ids = [(await _seal(svc, seal_id, user_id)).id]
    else:
        seal_ids = [s.id for s in await _listed_seals(svc, user_id, project_id=project_id)]
    rows = await svc.repo.openings(seal_ids=seal_ids, status=status) if seal_ids else []
    return OpeningList(items=await svc.opening_out(rows), total=len(rows))


@router.post("/seals/{seal_id}/openings", response_model=OpeningOut, status_code=201)
async def request_opening(
    seal_id: uuid.UUID,
    data: OpeningCreate,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("estimate_archive.request_opening")),
    svc: EstimateArchiveService = Depends(_service),
) -> OpeningOut:
    seal = await _seal(svc, seal_id, user_id)
    return (await svc.opening_out([await svc.request_opening(seal, data, user_id)]))[0]


@router.post("/openings/{opening_id}/start", response_model=OpeningOut)
async def start_opening(
    opening_id: uuid.UUID,
    data: OpeningStart,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("estimate_archive.attend")),
    svc: EstimateArchiveService = Depends(_service),
) -> OpeningOut:
    await _opening(svc, opening_id, user_id)
    return (await svc.opening_out([await svc.start_opening(opening_id, data.present, user_id)]))[0]


@router.post("/openings/{opening_id}/close", response_model=OpeningOut)
async def close_opening(
    opening_id: uuid.UUID,
    data: OpeningClose,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("estimate_archive.attend")),
    svc: EstimateArchiveService = Depends(_service),
) -> OpeningOut:
    await _opening(svc, opening_id, user_id)
    return (await svc.opening_out([await svc.close_opening(opening_id, data.minutes_document_id, user_id)]))[0]


# ── Pricing changes from the seal ────────────────────────────────────────────


@router.post("/seals/{seal_id}/derive", response_model=DeriveResult)
async def derive(
    seal_id: uuid.UUID,
    data: DeriveRequest,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    _perm: None = Depends(RequirePermission("estimate_archive.price")),
    svc: EstimateArchiveService = Depends(_service),
) -> DeriveResult:
    return await svc.derive(await _seal(svc, seal_id, user_id), data, user_id, payload)


@router.post("/seals/{seal_id}/derivations", response_model=DerivationOut, status_code=201)
async def record_derivation(
    seal_id: uuid.UUID,
    data: DerivationCreate,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    _perm: None = Depends(RequirePermission("estimate_archive.price")),
    svc: EstimateArchiveService = Depends(_service),
) -> DerivationOut:
    seal = await _seal(svc, seal_id, user_id)
    return await _derivation_out(svc, await svc.record_derivation(seal, data, user_id, payload))


@router.get("/derivations", response_model=DerivationList)
async def list_derivations(
    user_id: CurrentUserId,
    seal_id: uuid.UUID | None = Query(default=None),
    variation_request_id: uuid.UUID | None = Query(default=None),
    _perm: None = Depends(RequirePermission("estimate_archive.read")),
    svc: EstimateArchiveService = Depends(_service),
) -> DerivationList:
    allowed = {s.id for s in await _listed_seals(svc, user_id)}
    rows = [
        r
        for r in await svc.repo.derivations(seal_id=seal_id, variation_request_id=variation_request_id)
        if r.seal_id in allowed
    ]
    return DerivationList(items=[await _derivation_out(svc, r) for r in rows], total=len(rows))


@router.post("/derivations/{derivation_id}/method", response_model=DerivationOut)
async def choose_method(
    derivation_id: uuid.UUID,
    data: DerivationChoose,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("estimate_archive.price")),
    svc: EstimateArchiveService = Depends(_service),
) -> DerivationOut:
    row = await svc.repo.get_derivation(derivation_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Derivation not found")
    await _seal(svc, row.seal_id, user_id)
    return await _derivation_out(svc, await svc.choose_method(row, data.basis_method, user_id))


@router.post("/seals/{seal_id}/change-order-items/{item_id}/original-rate", response_model=ChangeOrderRateFilled)
async def fill_change_order_rate(
    seal_id: uuid.UUID,
    item_id: uuid.UUID,
    data: ChangeOrderRateFill,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("estimate_archive.price")),
    svc: EstimateArchiveService = Depends(_service),
) -> ChangeOrderRateFilled:
    seal = await _seal(svc, seal_id, user_id)
    _, rate = await svc.fill_change_order_rate(seal, item_id, data.position_ordinal, user_id)
    return ChangeOrderRateFilled(
        change_order_item_id=item_id, original_rate=rate, seal_id=seal.id, position_ordinal=data.position_ordinal
    )


@router.get("/variations/{variation_request_id}/findings", response_model=FindingPage)
async def variation_findings(
    variation_request_id: uuid.UUID,
    user_id: CurrentUserId,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=2000),
    _perm: None = Depends(RequirePermission("estimate_archive.read")),
    svc: EstimateArchiveService = Depends(_service),
) -> FindingPage:
    """Lines of a variation priced on the original basis with no live seal behind them."""
    from app.modules.variations.models import VariationRequest

    vr = await svc.session.get(VariationRequest, variation_request_id)
    if vr is None:
        raise HTTPException(status_code=404, detail="Variation not found")
    await verify_project_access(vr.project_id, user_id, svc.session)
    rows = await svc.variation_findings(variation_request_id, user_id)
    return FindingPage(items=rows[offset : offset + limit], total=len(rows), offset=offset, limit=limit)
