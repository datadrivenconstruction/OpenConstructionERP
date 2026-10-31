# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Estimate check API routes (mounted at ``/api/v1/estimate_checks``).

Reading a check needs ``estimate_checks.read`` and access to the BOQ's project;
accepting a finding needs ``estimate_checks.accept``; workspace thresholds need
``estimate_checks.admin``. The display preference belongs to the caller.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.boq.models import BOQ
from app.modules.estimate_checks.kpis import KPI_DEFS
from app.modules.estimate_checks.schemas import (
    AcceptRequest,
    CheckResponse,
    KpiCatalogEntry,
    PreferenceBody,
    SettingsBody,
    SettingsResponse,
)
from app.modules.estimate_checks.service import EstimateCheckService

router = APIRouter(tags=["estimate_checks"])

_READ = Depends(RequirePermission("estimate_checks.read"))
_ACCEPT = Depends(RequirePermission("estimate_checks.accept"))
_ADMIN = Depends(RequirePermission("estimate_checks.admin"))


async def _verify_boq(session: SessionDep, boq_id: uuid.UUID, user_id: str) -> None:
    """404 unless the caller may see the BOQ's project."""
    row = (await session.execute(select(BOQ.project_id).where(BOQ.id == boq_id))).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "BOQ not found")
    try:
        await verify_project_access(row[0], user_id, session)
    except HTTPException as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "BOQ not found") from exc


def _settings_out(settings: dict) -> SettingsResponse:
    catalog = [
        KpiCatalogEntry(
            kpi_id=k.kpi_id,
            group=k.group,
            unit=k.unit,
            kind=k.kind,
            default_low=k.default_low,
            default_high=k.default_high,
        )
        for k in KPI_DEFS
    ]
    return SettingsResponse(**settings, catalog=catalog)


@router.get("/boq/{boq_id}", response_model=CheckResponse, dependencies=[_READ])
async def get_check(boq_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> CheckResponse:
    """Rate every enabled KPI of the estimate."""
    await _verify_boq(session, boq_id, user_id)
    return CheckResponse(**await EstimateCheckService(session).check(boq_id))


@router.put("/boq/{boq_id}/accept/{kpi_id}", response_model=CheckResponse, dependencies=[_ACCEPT])
async def accept_finding(
    boq_id: uuid.UUID, kpi_id: str, body: AcceptRequest, session: SessionDep, user_id: CurrentUserId
) -> CheckResponse:
    """Accept a suspect or warning finding with a reason (recorded in the activity log)."""
    await _verify_boq(session, boq_id, user_id)
    result = await EstimateCheckService(session).accept(boq_id, kpi_id, body.reason, user_id)
    await session.commit()
    return CheckResponse(**result)


@router.delete("/boq/{boq_id}/accept/{kpi_id}", response_model=CheckResponse, dependencies=[_ACCEPT])
async def withdraw_acceptance(
    boq_id: uuid.UUID, kpi_id: str, session: SessionDep, user_id: CurrentUserId
) -> CheckResponse:
    """Withdraw an acceptance; the finding counts again."""
    await _verify_boq(session, boq_id, user_id)
    result = await EstimateCheckService(session).withdraw(boq_id, kpi_id, user_id)
    await session.commit()
    return CheckResponse(**result)


@router.get("/settings", response_model=SettingsResponse, dependencies=[_READ])
async def get_settings(session: SessionDep) -> SettingsResponse:
    """Workspace settings with the KPI catalogue and default ranges."""
    return _settings_out(await EstimateCheckService(session).settings())


@router.put("/settings", response_model=SettingsResponse, dependencies=[_ADMIN])
async def put_settings(body: SettingsBody, session: SessionDep, user_id: CurrentUserId) -> SettingsResponse:
    """Replace the workspace settings."""
    saved = await EstimateCheckService(session).save_settings(body.model_dump(), user_id)
    await session.commit()
    return _settings_out(saved)


@router.get("/preference", response_model=PreferenceBody, dependencies=[_READ])
async def get_preference(session: SessionDep, user_id: CurrentUserId) -> PreferenceBody:
    """The caller's display preference (default: badge only)."""
    return PreferenceBody(display_mode=await EstimateCheckService(session).preference(user_id))


@router.put("/preference", response_model=PreferenceBody, dependencies=[_READ])
async def put_preference(body: PreferenceBody, session: SessionDep, user_id: CurrentUserId) -> PreferenceBody:
    """Change the caller's display preference."""
    mode = await EstimateCheckService(session).save_preference(user_id, body.display_mode)
    await session.commit()
    return PreferenceBody(display_mode=mode)  # type: ignore[arg-type]
