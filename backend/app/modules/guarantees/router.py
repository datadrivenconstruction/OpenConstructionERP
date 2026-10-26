# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Guarantees​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ register API routes (mounted at ``/api/v1/guarantees``).

Project routes are gated twice like the sibling registers: a ``RequirePermission``
dependency, and ``verify_project_access`` awaited first in every handler. The
company exposure and the bank credit lines are company-level and need the read or
write permission only.
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.guarantees import logic
from app.modules.guarantees.models import Guarantee
from app.modules.guarantees.schemas import (
    AdvanceRecoveryRequest,
    DocumentLinkRequest,
    ExposureResponse,
    FacilityCreate,
    FacilityResponse,
    FacilityUpdate,
    GuaranteeCreate,
    GuaranteeDetailResponse,
    GuaranteeDocumentResponse,
    GuaranteeEventResponse,
    GuaranteeResponse,
    GuaranteeUpdate,
    PaymentGateResponse,
    SummaryResponse,
    TransitionRequest,
)
from app.modules.guarantees.service import GuaranteesService, derived

router = APIRouter(tags=["guarantees"])

_READ = Depends(RequirePermission("guarantees.read"))
_WRITE = Depends(RequirePermission("guarantees.write"))


def _check(value: str | None, allowed: tuple[str, ...], field: str) -> str | None:
    if value is not None and value not in allowed:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"Invalid {field}: {value!r}")
    return value


def _out(row: Guarantee, as_of: date | None = None) -> GuaranteeResponse:
    resp = GuaranteeResponse.model_validate(row)
    return resp.model_copy(update=derived(row, as_of))


# -- company level ---------------------------------------------------------


@router.get("/exposure", response_model=ExposureResponse, dependencies=[_READ])
async def company_exposure(session: SessionDep, as_of: date | None = None) -> ExposureResponse:
    """Live guarantees of the whole company by bank, by type and against credit lines."""
    data = await GuaranteesService(session).exposure(None, as_of)
    data["expiring"] = [_out(r, as_of) for r in data["expiring"]]
    return ExposureResponse.model_validate(data)


@router.get("/defaults", dependencies=[_READ])
async def guarantee_defaults(country: str | None = None) -> dict:
    """Default percentages, periods and forms per type: FIDIC 2017, then the country pack."""
    from app.modules.guarantees.defaults import defaults_for

    return defaults_for(country)


@router.get("/facilities", response_model=list[FacilityResponse], dependencies=[_READ])
async def list_facilities(session: SessionDep) -> list[FacilityResponse]:
    rows = await GuaranteesService(session).repo.facilities()
    return [FacilityResponse.model_validate(r) for r in rows]


@router.post("/facilities", response_model=FacilityResponse, status_code=201, dependencies=[_WRITE])
async def create_facility(data: FacilityCreate, session: SessionDep) -> FacilityResponse:
    row = await GuaranteesService(session).create_facility(data)
    return FacilityResponse.model_validate(row)


@router.patch("/facilities/{facility_id}", response_model=FacilityResponse, dependencies=[_WRITE])
async def update_facility(facility_id: uuid.UUID, data: FacilityUpdate, session: SessionDep) -> FacilityResponse:
    row = await GuaranteesService(session).update_facility(facility_id, data)
    return FacilityResponse.model_validate(row)


@router.delete("/facilities/{facility_id}", status_code=204, dependencies=[_WRITE])
async def delete_facility(facility_id: uuid.UUID, session: SessionDep) -> None:
    await GuaranteesService(session).delete_facility(facility_id)


@router.post("/alerts/run", dependencies=[_WRITE])
async def run_alerts(session: SessionDep, as_of: date | None = None) -> dict[str, int]:
    """Run the daily expiry job now (alerts, auto-extension, lapsing)."""
    counts = await GuaranteesService(session).run_daily(as_of)
    return counts


@router.get("/portfolio", response_model=list[SummaryResponse], dependencies=[_READ])
async def portfolio(session: SessionDep, user_id: CurrentUserId) -> list[SummaryResponse]:
    """Per-project guarantee figures for the portfolio view (projects the caller can open)."""
    from sqlalchemy import distinct, select

    service = GuaranteesService(session)
    ids = (await session.execute(select(distinct(Guarantee.project_id)))).scalars().all()
    out: list[SummaryResponse] = []
    for pid in ids:
        try:
            await verify_project_access(pid, user_id, session)
        except HTTPException:
            continue
        out.append(SummaryResponse.model_validate(await service.summary(pid)))
    return out


@router.get(
    "/subcontractors/{subcontractor_id}/guarantees", response_model=list[GuaranteeResponse], dependencies=[_READ]
)
async def subcontractor_guarantees(
    subcontractor_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> list[GuaranteeResponse]:
    """Bonds received from one subcontractor, across the projects the caller can open."""
    rows = await GuaranteesService(session).repo.list(subcontractor_id=subcontractor_id)
    out: list[GuaranteeResponse] = []
    allowed: dict[uuid.UUID, bool] = {}
    for row in rows:
        if row.project_id not in allowed:
            try:
                await verify_project_access(row.project_id, user_id, session)
                allowed[row.project_id] = True
            except HTTPException:
                allowed[row.project_id] = False
        if allowed[row.project_id]:
            out.append(_out(row))
    return out


@router.get("/contracts/{contract_id}/payment-gate", response_model=PaymentGateResponse, dependencies=[_READ])
async def payment_gate(contract_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> PaymentGateResponse:
    """Whether the contract may take its first interim payment (performance bond held)."""
    from app.modules.contracts.models import Contract

    contract = await session.get(Contract, contract_id)
    if contract is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Contract not found")
    await verify_project_access(contract.project_id, user_id, session)
    return PaymentGateResponse.model_validate(await GuaranteesService(session).payment_gate(contract_id))


# -- project register ------------------------------------------------------


@router.get("/projects/{project_id}/guarantees", response_model=list[GuaranteeResponse], dependencies=[_READ])
async def list_guarantees(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    guarantee_type: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    direction: str | None = Query(default=None),
    contract_id: uuid.UUID | None = Query(default=None),
    as_of: date | None = None,
) -> list[GuaranteeResponse]:
    await verify_project_access(project_id, user_id, session)
    rows = await GuaranteesService(session).list(
        project_id,
        guarantee_type=_check(guarantee_type, logic.GUARANTEE_TYPES, "guarantee_type"),
        status=_check(status_filter, logic.STATUSES, "status"),
        direction=_check(direction, logic.DIRECTIONS, "direction"),
        contract_id=contract_id,
    )
    return [_out(r, as_of) for r in rows]


@router.post(
    "/projects/{project_id}/guarantees", response_model=GuaranteeResponse, status_code=201, dependencies=[_WRITE]
)
async def create_guarantee(
    project_id: uuid.UUID, data: GuaranteeCreate, session: SessionDep, user_id: CurrentUserId
) -> GuaranteeResponse:
    await verify_project_access(project_id, user_id, session)
    row = await GuaranteesService(session).create(project_id, data, str(user_id))
    return _out(row)


@router.get("/projects/{project_id}/exposure", response_model=ExposureResponse, dependencies=[_READ])
async def project_exposure(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, as_of: date | None = None
) -> ExposureResponse:
    await verify_project_access(project_id, user_id, session)
    data = await GuaranteesService(session).exposure(project_id, as_of)
    data["expiring"] = [_out(r, as_of) for r in data["expiring"]]
    return ExposureResponse.model_validate(data)


@router.get("/projects/{project_id}/summary", response_model=SummaryResponse, dependencies=[_READ])
async def project_summary(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> SummaryResponse:
    """Compact figures for the project dashboard widget."""
    await verify_project_access(project_id, user_id, session)
    return SummaryResponse.model_validate(await GuaranteesService(session).summary(project_id))


@router.get("/projects/{project_id}/validation", dependencies=[_READ])
async def project_validation(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict:
    """The register rule set over the project: failing findings only."""
    await verify_project_access(project_id, user_id, session)
    findings = await GuaranteesService(session).findings(project_id)
    return {"project_id": str(project_id), "findings": findings}


@router.get(
    "/projects/{project_id}/guarantees/{guarantee_id}", response_model=GuaranteeDetailResponse, dependencies=[_READ]
)
async def get_guarantee(
    project_id: uuid.UUID, guarantee_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> GuaranteeDetailResponse:
    await verify_project_access(project_id, user_id, session)
    service = GuaranteesService(session)
    row = await service.require(project_id, guarantee_id)
    base = _out(row).model_dump()
    base["events"] = [GuaranteeEventResponse.model_validate(e) for e in await service.events(row)]
    base["findings"] = await service.findings(project_id, guarantee_id)
    return GuaranteeDetailResponse.model_validate(base)


@router.patch(
    "/projects/{project_id}/guarantees/{guarantee_id}", response_model=GuaranteeResponse, dependencies=[_WRITE]
)
async def update_guarantee(
    project_id: uuid.UUID, guarantee_id: uuid.UUID, data: GuaranteeUpdate, session: SessionDep, user_id: CurrentUserId
) -> GuaranteeResponse:
    await verify_project_access(project_id, user_id, session)
    row = await GuaranteesService(session).update(project_id, guarantee_id, data, str(user_id))
    return _out(row)


@router.delete("/projects/{project_id}/guarantees/{guarantee_id}", status_code=204, dependencies=[_WRITE])
async def delete_guarantee(
    project_id: uuid.UUID, guarantee_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> None:
    await verify_project_access(project_id, user_id, session)
    await GuaranteesService(session).delete(project_id, guarantee_id)


@router.post(
    "/projects/{project_id}/guarantees/{guarantee_id}/transition",
    response_model=GuaranteeResponse,
    dependencies=[_WRITE],
)
async def transition_guarantee(
    project_id: uuid.UUID, guarantee_id: uuid.UUID, req: TransitionRequest, session: SessionDep, user_id: CurrentUserId
) -> GuaranteeResponse:
    await verify_project_access(project_id, user_id, session)
    row = await GuaranteesService(session).transition(project_id, guarantee_id, req, str(user_id))
    return _out(row)


@router.post(
    "/projects/{project_id}/guarantees/{guarantee_id}/advance-recovery",
    response_model=GuaranteeResponse,
    dependencies=[_WRITE],
)
async def advance_recovery(
    project_id: uuid.UUID,
    guarantee_id: uuid.UUID,
    req: AdvanceRecoveryRequest,
    session: SessionDep,
    user_id: CurrentUserId,
) -> GuaranteeResponse:
    """Record advance recovered through a payment; the guarantee reduces to what is outstanding."""
    await verify_project_access(project_id, user_id, session)
    row = await GuaranteesService(session).recover_manually(project_id, guarantee_id, req, str(user_id))
    return _out(row)


@router.post(
    "/projects/{project_id}/guarantees/{guarantee_id}/commission",
    dependencies=[_WRITE],
)
async def post_commission(
    project_id: uuid.UUID,
    guarantee_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    period_end: date = Query(...),
) -> dict:
    """Post the bank commission accrued up to ``period_end`` to the finance ledger."""
    await verify_project_access(project_id, user_id, session)
    result = await GuaranteesService(session).post_commission(project_id, guarantee_id, period_end, str(user_id))
    return {**result, "amount": format(result["amount"], "f")}


@router.post(
    "/projects/{project_id}/guarantees/{guarantee_id}/documents",
    response_model=GuaranteeDocumentResponse,
    status_code=201,
    dependencies=[_WRITE],
)
async def link_document(
    project_id: uuid.UUID,
    guarantee_id: uuid.UUID,
    req: DocumentLinkRequest,
    session: SessionDep,
    user_id: CurrentUserId,
) -> GuaranteeDocumentResponse:
    await verify_project_access(project_id, user_id, session)
    link = await GuaranteesService(session).link_document(project_id, guarantee_id, req, str(user_id))
    return GuaranteeDocumentResponse.model_validate(link)


@router.delete(
    "/projects/{project_id}/guarantees/{guarantee_id}/documents/{document_id}",
    status_code=204,
    dependencies=[_WRITE],
)
async def unlink_document(
    project_id: uuid.UUID,
    guarantee_id: uuid.UUID,
    document_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> None:
    await verify_project_access(project_id, user_id, session)
    await GuaranteesService(session).unlink_document(project_id, guarantee_id, document_id, str(user_id))
