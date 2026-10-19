# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""ZATCA EGS unit onboarding routes.

Mounted at ``/api/v1/einvoice-zatca/``.

    GET    /meta                              - states, environments, API paths, open questions

    GET    /units/?profile_id=                - the units of a registration
    POST   /units/                            - add a unit to a Saudi registration
    GET    /units/{unit_id}                   - one unit (never a key or a secret)
    POST   /units/{unit_id}/csr               - make the key pair and CSR
    POST   /units/{unit_id}/compliance-csid   - exchange the OTP for a compliance CSID
    POST   /units/{unit_id}/compliance-checks - ZATCA checks one sample of each document type
    POST   /units/{unit_id}/production-csid   - obtain the production CSID
    POST   /units/{unit_id}/renew             - renew the production CSID (new OTP, new CSR)
    POST   /units/{unit_id}/revoke            - retire the unit

Invoices themselves go through the e-invoice clearance routes; this router only
prepares the unit that stamps them. The FATOORA client is a dependency, so a
test substitutes a mock transport and nothing reaches ZATCA.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import RequirePermission, SessionDep
from app.modules.einvoice_clearance import repository as clearance_repository
from app.modules.einvoice_zatca import data, service, signing
from app.modules.einvoice_zatca.client import FatooraClient
from app.modules.einvoice_zatca.schemas import (
    ApiPathResponse,
    CsrRequest,
    EinvoiceZatcaListResponse,
    EnvironmentResponse,
    MetaResponse,
    OtpRequest,
    UnitCreateRequest,
    UnitResponse,
)

router = APIRouter(tags=["einvoice_zatca"])

ClientFactory = Callable[[str], FatooraClient]


def get_client_factory() -> ClientFactory:
    """The FATOORA client for an environment. Overridden in tests."""
    return FatooraClient


def _refuse(exc: service.ZatcaServiceError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT if exc.conflict else status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"message": exc.message},
    )


async def _locked_unit(session: SessionDep, unit_id: uuid.UUID) -> Any:
    unit = await service.get_unit(session, unit_id, lock=True)
    if unit is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unit not found")
    return unit


def _respond(unit: Any) -> UnitResponse:
    return UnitResponse(**service.unit_as_dict(unit))


@router.get("/meta", response_model=MetaResponse, dependencies=[Depends(RequirePermission("einvoice_zatca.read"))])
async def get_meta() -> MetaResponse:
    """What the onboarding path is, where it can run, and what is still unconfirmed."""
    return MetaResponse(
        states=list(service.TRANSITIONS),
        transitions={state: sorted(targets) for state, targets in service.TRANSITIONS.items()},
        signer_kinds=list(signing.SIGNER_KINDS),
        environments=[
            EnvironmentResponse(key=e.key, label=e.label, base_url=e.base_url, live=e.live)
            for e in data.ENVIRONMENTS.values()
        ],
        api_paths=[
            ApiPathResponse(
                name=name,
                path=p.path,
                method=p.method,
                source=p.source,
                needs_expert_review=p.needs_expert_review,
            )
            for name, p in data.API_PATHS.items()
        ],
        unconfirmed=list(data.UNCONFIRMED_FACTS),
    )


@router.get(
    "/units/",
    response_model=EinvoiceZatcaListResponse,
    dependencies=[Depends(RequirePermission("einvoice_zatca.read"))],
)
async def list_units(
    session: SessionDep,
    profile_id: uuid.UUID = Query(...),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> EinvoiceZatcaListResponse:
    units, total = await service.page_units(session, profile_id, offset=offset, limit=limit)
    return EinvoiceZatcaListResponse(items=[_respond(u) for u in units], total=total, offset=offset, limit=limit)


@router.post(
    "/units/",
    response_model=UnitResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("einvoice_zatca.manage"))],
)
async def create_unit(payload: UnitCreateRequest, session: SessionDep) -> UnitResponse:
    profile = await clearance_repository.get_profile(session, payload.profile_id)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Registration not found")
    try:
        unit = await service.create_unit(
            session,
            profile=profile,
            unit_key=payload.unit_key,
            csr_fields=payload.csr_fields,
            signer_kind=payload.signer_kind,
            signer_config=payload.signer_config,
            environment=payload.environment,
        )
    except service.ZatcaServiceError as exc:
        raise _refuse(exc) from exc
    return _respond(unit)


@router.get(
    "/units/{unit_id}",
    response_model=UnitResponse,
    dependencies=[Depends(RequirePermission("einvoice_zatca.read"))],
)
async def get_unit(unit_id: uuid.UUID, session: SessionDep) -> UnitResponse:
    unit = await service.get_unit(session, unit_id)
    if unit is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unit not found")
    return _respond(unit)


@router.post(
    "/units/{unit_id}/csr",
    response_model=UnitResponse,
    dependencies=[Depends(RequirePermission("einvoice_zatca.manage"))],
)
async def make_csr(unit_id: uuid.UUID, payload: CsrRequest, session: SessionDep) -> UnitResponse:
    unit = await _locked_unit(session, unit_id)
    try:
        await service.prepare_csr(session, unit, csr_pem=payload.csr_pem)
    except service.ZatcaServiceError as exc:
        raise _refuse(exc) from exc
    return _respond(unit)


@router.post(
    "/units/{unit_id}/compliance-csid",
    response_model=UnitResponse,
    dependencies=[Depends(RequirePermission("einvoice_zatca.onboard"))],
)
async def compliance_csid(
    unit_id: uuid.UUID,
    payload: OtpRequest,
    session: SessionDep,
    factory: ClientFactory = Depends(get_client_factory),
) -> UnitResponse:
    unit = await _locked_unit(session, unit_id)
    try:
        await service.request_compliance_csid(session, unit, otp=payload.otp, client=factory(unit.environment))
    except service.ZatcaServiceError as exc:
        raise _refuse(exc) from exc
    return _respond(unit)


@router.post(
    "/units/{unit_id}/compliance-checks",
    response_model=UnitResponse,
    dependencies=[Depends(RequirePermission("einvoice_zatca.onboard"))],
)
async def compliance_checks(
    unit_id: uuid.UUID,
    session: SessionDep,
    factory: ClientFactory = Depends(get_client_factory),
) -> UnitResponse:
    unit = await _locked_unit(session, unit_id)
    profile = await clearance_repository.get_profile(session, unit.profile_id)
    if profile is None:  # pragma: no cover - the foreign key cascades
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The registration no longer exists.")
    try:
        await service.run_compliance_checks(session, unit, profile=profile, client=factory(unit.environment))
    except service.ZatcaServiceError as exc:
        raise _refuse(exc) from exc
    return _respond(unit)


@router.post(
    "/units/{unit_id}/production-csid",
    response_model=UnitResponse,
    dependencies=[Depends(RequirePermission("einvoice_zatca.onboard"))],
)
async def production_csid(
    unit_id: uuid.UUID,
    session: SessionDep,
    factory: ClientFactory = Depends(get_client_factory),
) -> UnitResponse:
    unit = await _locked_unit(session, unit_id)
    try:
        await service.request_production_csid(session, unit, client=factory(unit.environment))
    except service.ZatcaServiceError as exc:
        raise _refuse(exc) from exc
    return _respond(unit)


@router.post(
    "/units/{unit_id}/renew",
    response_model=UnitResponse,
    dependencies=[Depends(RequirePermission("einvoice_zatca.onboard"))],
)
async def renew_unit(
    unit_id: uuid.UUID,
    payload: OtpRequest,
    session: SessionDep,
    factory: ClientFactory = Depends(get_client_factory),
) -> UnitResponse:
    unit = await _locked_unit(session, unit_id)
    try:
        await service.renew(session, unit, otp=payload.otp, client=factory(unit.environment), csr_pem=payload.csr_pem)
    except service.ZatcaServiceError as exc:
        raise _refuse(exc) from exc
    return _respond(unit)


@router.post(
    "/units/{unit_id}/revoke",
    response_model=UnitResponse,
    dependencies=[Depends(RequirePermission("einvoice_zatca.onboard"))],
)
async def revoke_unit(unit_id: uuid.UUID, session: SessionDep) -> UnitResponse:
    unit = await _locked_unit(session, unit_id)
    try:
        await service.revoke(session, unit)
    except service.ZatcaServiceError as exc:
        raise _refuse(exc) from exc
    return _respond(unit)
