# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Routes for exchange fidelity reports and proportional resource scaling.

Mounted into the BOQ router, so every path sits under ``/api/v1/boq``.

* ``GET  /boqs/{boq_id}/exchange-reports/``                       the bill's reports, newest first
* ``GET  /boqs/{boq_id}/exchange-reports/{report_id}/``           one report with its items
* ``GET  /boqs/{boq_id}/exchange-reports/{report_id}/download/``  the items as CSV or XLSX
* ``POST /boqs/{boq_id}/exchange-reports/check/``                 build an export in memory and report it
* ``POST /boqs/{boq_id}/resources/scale/preview/``                propose scaled norms, write nothing
* ``POST /boqs/{boq_id}/resources/scale/apply/``                  write the proposal a person confirmed

The analysis is in ``exchange_fidelity`` and ``resource_scaling``; this file
checks access, loads and shapes responses.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.content_disposition import attachment_disposition
from app.core.i18n import t
from app.dependencies import CurrentUserId, CurrentUserPayload, RequirePermission, SessionDep
from app.modules.boq.exchange_fidelity import DOWNLOAD_COLUMNS, render_csv, render_xlsx
from app.modules.boq.exchange_fidelity_service import (
    analyze_export,
    record_report,
    report_out,
    summary_out,
)
from app.modules.boq.repository import ExchangeReportRepository
from app.modules.boq.resource_scaling_service import ScaleRequest, apply_plan, build_plan

logger = logging.getLogger(__name__)

exchange_fidelity_router = APIRouter(tags=["boq"])


def _boq_service(session: SessionDep) -> Any:
    from app.modules.boq.service import BOQService

    return BOQService(session)


async def _verify_boq(session: Any, boq_id: uuid.UUID, user_id: str, payload: dict | None) -> None:
    from app.modules.boq.router import _verify_boq_owner

    await _verify_boq_owner(session, boq_id, user_id, payload)


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "exchange_report_not_found"})


# ── Exchange fidelity reports ──────────────────────────────────────────────


@exchange_fidelity_router.get(
    "/boqs/{boq_id}/exchange-reports/",
    summary="List the exchange fidelity reports of a bill",
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def list_exchange_reports(
    boq_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    direction: Literal["import", "export"] | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    """Newest first, counts only; open one report for its items."""
    await _verify_boq(session, boq_id, user_id, payload)
    rows = await ExchangeReportRepository(session).list_for_boq(boq_id, direction=direction, limit=limit)
    return {"items": [summary_out(r) for r in rows]}


@exchange_fidelity_router.get(
    "/boqs/{boq_id}/exchange-reports/{report_id}/",
    summary="One exchange fidelity report with its items",
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def get_exchange_report(
    boq_id: uuid.UUID,
    report_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
) -> dict[str, Any]:
    """The report, scoped to the bill: a report id of another bill answers 404."""
    await _verify_boq(session, boq_id, user_id, payload)
    row = await ExchangeReportRepository(session).get(boq_id, report_id)
    if row is None:
        raise _not_found()
    return report_out(row)


def _label(group: str, value: str) -> str:
    key = f"boq.fidelity.{group}.{value}"
    text = t(key)
    return value if text == key else text


@exchange_fidelity_router.get(
    "/boqs/{boq_id}/exchange-reports/{report_id}/download/",
    summary="Download an exchange fidelity report as CSV or XLSX",
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def download_exchange_report(
    boq_id: uuid.UUID,
    report_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    file_format: Literal["csv", "xlsx"] = Query("csv", alias="format"),
    severity: Literal["error", "warning", "info"] | None = Query(None),
    kind: str | None = Query(None, max_length=40),
) -> StreamingResponse:
    """The items, filtered the way the dialog filtered them, in the reader's language."""
    await _verify_boq(session, boq_id, user_id, payload)
    row = await ExchangeReportRepository(session).get(boq_id, report_id)
    if row is None:
        raise _not_found()
    items = [
        it
        for it in (row.items or [])
        if isinstance(it, dict)
        and (severity is None or it.get("severity") == severity)
        and (kind is None or it.get("kind") == kind)
    ]
    headers = [_label("column", key) for key, _attr in DOWNLOAD_COLUMNS]
    stamp = (row.created_at or datetime.now(UTC)).strftime("%Y%m%d-%H%M")
    base = f"fidelity-{row.direction}-{row.format_id}-{stamp}"
    if file_format == "xlsx":
        content = render_xlsx(items, headers, _label, title=_label("sheet", "title"))
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = f"{base}.xlsx"
    else:
        content = render_csv(items, headers, _label)
        media = "text/csv; charset=utf-8"
        filename = f"{base}.csv"
    return StreamingResponse(
        iter([content]),
        media_type=media,
        headers={"Content-Disposition": attachment_disposition(filename)},
    )


class ExchangeCheckRequest(BaseModel):
    """Which export to build in memory and how hard to check it."""

    format_id: Literal["gaeb_xml", "bc3", "excel", "csv"]
    variant: Literal["", "x83", "x84"] = ""
    roundtrip: bool = Field(True, description="Read the export back with the matching importer and diff it")
    embed_markups: bool | None = None


@exchange_fidelity_router.post(
    "/boqs/{boq_id}/exchange-reports/check/",
    summary="Check what an export would lose, without downloading it",
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def check_export_fidelity(
    boq_id: uuid.UUID,
    body: ExchangeCheckRequest,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
) -> dict[str, Any]:
    """Build the export exactly as the download would, analyse it, optionally round-trip it.

    The report is stored as a check (``is_check``), so it is listed with the
    bill's reports but never feeds the validation rule: no file left the system.
    """
    from app.modules.boq import router as boq_router

    await _verify_boq(session, boq_id, user_id, payload)
    service = _boq_service(session)
    if body.format_id == "gaeb_xml":
        built = await boq_router._build_gaeb_export(
            session, service, boq_id, body.variant or "x83", "main", body.embed_markups
        )
    elif body.format_id == "bc3":
        built = await boq_router._build_bc3_export(session, service, boq_id, body.embed_markups)
    elif body.format_id == "excel":
        built = await boq_router._build_excel_export(session, service, boq_id, body.embed_markups)
    else:
        built = await boq_router._build_csv_export(service, boq_id, body.embed_markups)

    report = await analyze_export(
        service,
        boq_id,
        built.structured,
        format_id=built.format_id,
        variant=built.variant,
        project_name=built.project_name,
        trace=built.trace,
        content=built.content,
        roundtrip=body.roundtrip,
    )
    row = await record_report(
        session,
        boq_id=boq_id,
        report=report,
        file_name=built.filename,
        user_id=user_id,
        project_id=built.project_id,
        is_check=True,
    )
    if row is None:
        out = report.to_dict()
        out["id"] = None
        return out
    return report_out(row)


# ── Proportional resource scaling ──────────────────────────────────────────


class ResourceScaleBody(BaseModel):
    """A scaling request: the scope, the metric, the target and the rounding rule."""

    metric: Literal["hours", "cost", "quantity"]
    target: Decimal | None = Field(
        None, ge=0, max_digits=20, decimal_places=6, description="Omitted on preview: measure the scope only"
    )
    section_id: uuid.UUID | None = None
    position_ids: list[uuid.UUID] | None = Field(None, max_length=20000)
    resource_type: str | None = Field(None, max_length=50)
    resource_key: str | None = Field(None, max_length=255)
    decimals: int = Field(3, ge=0, le=6)
    rounding_mode: Literal["half_up", "up", "down"] = "half_up"
    excluded_position_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20000)
    expected_factor: Decimal | None = Field(None, description="Apply only: the factor of the confirmed preview")

    def to_request(self) -> ScaleRequest:
        """The transport-free request the service takes."""
        return ScaleRequest(
            metric=self.metric,
            target=self.target,
            section_id=self.section_id,
            position_ids=self.position_ids,
            resource_type=self.resource_type,
            resource_key=self.resource_key,
            decimals=self.decimals,
            rounding_mode=self.rounding_mode,
            excluded_position_ids=self.excluded_position_ids,
        )


@exchange_fidelity_router.post(
    "/boqs/{boq_id}/resources/scale/preview/",
    summary="Preview proportional scaling of resource norms to a target total",
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def preview_resource_scaling(
    boq_id: uuid.UUID,
    body: ResourceScaleBody,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
) -> dict[str, Any]:
    """The factor, the totals before and after rounding and every line it would change. Writes nothing."""
    await _verify_boq(session, boq_id, user_id, payload)
    plan, _rows = await build_plan(_boq_service(session), boq_id, body.to_request())
    return plan.to_dict()


@exchange_fidelity_router.post(
    "/boqs/{boq_id}/resources/scale/apply/",
    summary="Apply a confirmed proportional scaling (snapshot first, undo by restoring it)",
    dependencies=[Depends(RequirePermission("boq.update"))],
)
async def apply_resource_scaling(
    boq_id: uuid.UUID,
    body: ResourceScaleBody,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
) -> dict[str, Any]:
    """Recompute the plan server-side, refuse it when it moved since the preview, then write it."""
    await _verify_boq(session, boq_id, user_id, payload)
    if body.target is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"code": "scaling_target_required"}
        )
    actor: uuid.UUID | None
    try:
        actor = uuid.UUID(str(user_id))
    except ValueError:
        actor = None
    return await apply_plan(
        _boq_service(session),
        boq_id,
        body.to_request(),
        user_id=actor,
        expected_factor=body.expected_factor,
    )
