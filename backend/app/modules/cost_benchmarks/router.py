# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ benchmarks API routes (mounted at ``/api/v1/cost_benchmarks``).

Every route is tenant scoped through :data:`CurrentTenantId`; capturing a project also
checks project access.
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from app.dependencies import CurrentTenantId, CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.cost_benchmarks.bench_math import STANDARDS
from app.modules.cost_benchmarks.schemas import CompareRequest, RecordCreate, RecordOut
from app.modules.cost_benchmarks.service import CostBenchmarksService, load_reference
from app.modules.cost_benchmarks.validators import evaluate

router = APIRouter(tags=["cost_benchmarks"])
_READ = Depends(RequirePermission("cost_benchmarks.read"))
_WRITE = Depends(RequirePermission("cost_benchmarks.write"))


@router.get("/records/", response_model=list[RecordOut], dependencies=[_READ])
async def list_records(
    session: SessionDep,
    tenant_id: CurrentTenantId,
    kind: str | None = None,
    project_type: str | None = None,
    country: str | None = None,
) -> list[RecordOut]:
    rows = await CostBenchmarksService(session, tenant_id).list_records(
        kind, project_type=project_type, countries=[country] if country else None
    )
    return [RecordOut.model_validate(r) for r in rows]


@router.post("/records/", response_model=RecordOut, status_code=201, dependencies=[_WRITE])
async def create_record(
    data: RecordCreate, session: SessionDep, tenant_id: CurrentTenantId, user_id: CurrentUserId
) -> RecordOut:
    if not data.standard_ok():
        raise HTTPException(status_code=422, detail=f"Standard must be one of {', '.join(STANDARDS)}")
    payload = data.model_dump()
    payload["elements"] = [e.model_dump() for e in data.elements]
    if payload.get("total_cost") is None:
        payload.pop("total_cost")
    row = await CostBenchmarksService(session, tenant_id).create(payload, user_id)
    return RecordOut.model_validate(row)


@router.delete("/records/{record_id}", status_code=204, dependencies=[_WRITE])
async def delete_record(record_id: uuid.UUID, session: SessionDep, tenant_id: CurrentTenantId) -> Response:
    await CostBenchmarksService(session, tenant_id).delete(record_id)
    return Response(status_code=204)


@router.post("/projects/{project_id}/capture/", response_model=RecordOut, dependencies=[_WRITE])
async def capture_project(
    project_id: uuid.UUID, session: SessionDep, tenant_id: CurrentTenantId, user_id: CurrentUserId
) -> RecordOut:
    """Turn a completed project's final BOQ into a benchmark record (replaces an earlier capture)."""
    await verify_project_access(project_id, user_id, session)
    row = await CostBenchmarksService(session, tenant_id).capture_project(project_id, user_id=user_id)
    return RecordOut.model_validate(row)


@router.post("/compare/", dependencies=[_READ])
async def compare(
    data: CompareRequest, session: SessionDep, tenant_id: CurrentTenantId, user_id: CurrentUserId
) -> dict:
    """Percentile bands per element for an estimate against comparable projects, with findings."""
    if data.project_id is not None:
        await verify_project_access(data.project_id, user_id, session)
    service = CostBenchmarksService(session, tenant_id)
    result = await service.compare(
        estimate_id=data.estimate_id,
        project_id=data.project_id,
        filters={
            "project_type": data.project_type,
            "countries": data.countries,
            "region": data.region,
            "gfa_min": data.gfa_min,
            "gfa_max": data.gfa_max,
            "year_from": data.year_from,
            "year_to": data.year_to,
        },
        base_date=data.base_date or date.today(),
        base_region=data.base_region,
        reporting_currency=data.reporting_currency,
        index_series_id=data.index_series_id,
        fx_date=data.fx_date,
        measure=data.measure,
        min_projects=data.min_projects,
        stale_months=data.stale_months,
    )
    findings = await evaluate(result, target_id=result["estimate"]["id"])
    result["findings"] = [
        {
            "rule_id": f.rule_id,
            "severity": str(getattr(f.severity, "value", f.severity)),
            "message": f.message,
            "element_ref": f.element_ref,
        }
        for f in findings
    ]
    return result


@router.get("/reference/", dependencies=[_READ])
async def reference() -> dict:
    """The open reference bands used where there is no own history."""
    return load_reference()


@router.get("/export/anonymised", dependencies=[_READ], response_model=None)
async def anonymised_export(
    session: SessionDep,
    tenant_id: CurrentTenantId,
    format: str = Query("json", pattern="^(json|csv)$"),  # noqa: A002 - public query name
    base_date: date | None = None,
    reporting_currency: str = Query("EUR", min_length=3, max_length=3),
) -> Response:
    """Company records without names, ids, regions or exact areas."""
    service = CostBenchmarksService(session, tenant_id)
    basis, _info = await service.basis(
        base_date=base_date or date.today(), base_region=None, reporting_currency=reporting_currency
    )
    content, media = await service.anonymised_export(basis=basis, fmt=format)
    return Response(
        content=content,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="cost_benchmarks_anonymised.{format}"'},
    )
