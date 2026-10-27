# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Quote​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ capture API routes (mounted at ``/api/v1/quote-capture``).

Every handler checks project access first, then the module permission. Nothing
reaches a bid, a price list or a purchase order except through ``/confirm``,
which a person calls after review and which the validation rules gate.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.quote_capture.models import CapturedQuote
from app.modules.quote_capture.schemas import (
    ConfirmOut,
    ConfirmRequest,
    FindingOut,
    LevellingOut,
    LineUpdate,
    QuoteOut,
    QuoteSummaryOut,
    QuoteTextCreate,
    QuoteUpdate,
)
from app.modules.quote_capture.service import QuoteCaptureService

router = APIRouter(tags=["quote_capture"])
_READ = Depends(RequirePermission("quote_capture.read"))
_WRITE = Depends(RequirePermission("quote_capture.write"))


async def _load(quote_id: uuid.UUID, session: SessionDep, user_id: str) -> tuple[QuoteCaptureService, CapturedQuote]:
    svc = QuoteCaptureService(session)
    row = await svc.get(quote_id)
    await verify_project_access(row.project_id, user_id, session)
    return svc, row


def _summary(row: CapturedQuote) -> QuoteSummaryOut:
    out = QuoteSummaryOut.model_validate(row)
    return out.model_copy(update={"line_count": len(row.lines or [])})


async def _detail(svc: QuoteCaptureService, row: CapturedQuote) -> QuoteOut:
    findings = await svc.findings(row)
    base = QuoteOut.model_validate(row)
    return base.model_copy(
        update={
            "line_count": len(row.lines or []),
            "has_file": bool(row.storage_key),
            "tax": await svc.tax(row),
            "open_findings": len(findings),
            "findings": [
                FindingOut(rule_id=f.rule_id, severity=str(f.severity), message=f.message, element_ref=f.element_ref)
                for f in findings
            ],
        }
    )


@router.get("/projects/{project_id}/quotes", response_model=list[QuoteSummaryOut], dependencies=[_READ])
async def list_quotes(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    package_id: uuid.UUID | None = Query(default=None),
) -> list[QuoteSummaryOut]:
    await verify_project_access(project_id, user_id, session)
    rows = await QuoteCaptureService(session).list(project_id, package_id)
    return [_summary(r) for r in rows]


@router.post("/projects/{project_id}/quotes/upload", response_model=QuoteOut, status_code=201, dependencies=[_WRITE])
async def upload_quote(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    file: UploadFile = File(...),
    package_id: uuid.UUID | None = Form(default=None),
    locale: str | None = Form(default=None),
) -> QuoteOut:
    await verify_project_access(project_id, user_id, session)
    svc = QuoteCaptureService(session)
    row = await svc.upload(project_id=project_id, package_id=package_id, file=file, user_id=user_id, locale=locale)
    return await _detail(svc, row)


@router.post("/quotes/text", response_model=QuoteOut, status_code=201, dependencies=[_WRITE])
async def create_from_text(data: QuoteTextCreate, session: SessionDep, user_id: CurrentUserId) -> QuoteOut:
    await verify_project_access(data.project_id, user_id, session)
    svc = QuoteCaptureService(session)
    row = await svc.create_from_text(
        project_id=data.project_id,
        package_id=data.package_id,
        text=data.text,
        filename=data.filename,
        user_id=user_id,
        locale=data.locale,
    )
    return await _detail(svc, row)


@router.get("/quotes/{quote_id}", response_model=QuoteOut, dependencies=[_READ])
async def get_quote(quote_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> QuoteOut:
    svc, row = await _load(quote_id, session, user_id)
    return await _detail(svc, row)


@router.patch("/quotes/{quote_id}", response_model=QuoteOut, dependencies=[_WRITE])
async def update_quote(quote_id: uuid.UUID, data: QuoteUpdate, session: SessionDep, user_id: CurrentUserId) -> QuoteOut:
    svc, row = await _load(quote_id, session, user_id)
    row = await svc.update(row, data, user_id)
    return await _detail(svc, row)


@router.patch("/quotes/{quote_id}/lines/{line_id}", response_model=QuoteOut, dependencies=[_WRITE])
async def update_line(
    quote_id: uuid.UUID, line_id: str, data: LineUpdate, session: SessionDep, user_id: CurrentUserId
) -> QuoteOut:
    svc, row = await _load(quote_id, session, user_id)
    row = await svc.update_line(row, line_id, data, user_id)
    return await _detail(svc, row)


@router.post("/quotes/{quote_id}/rematch", response_model=QuoteOut, dependencies=[_WRITE])
async def rematch(quote_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> QuoteOut:
    svc, row = await _load(quote_id, session, user_id)
    row = await svc.rematch(row)
    return await _detail(svc, row)


@router.post("/quotes/{quote_id}/confirm", response_model=ConfirmOut, dependencies=[_WRITE])
async def confirm_quote(
    quote_id: uuid.UUID, data: ConfirmRequest, session: SessionDep, user_id: CurrentUserId
) -> ConfirmOut:
    svc, row = await _load(quote_id, session, user_id)
    result = await svc.confirm(row, data.target, user_id, accept_warnings=data.accept_warnings)
    return ConfirmOut.model_validate(result)


@router.delete("/quotes/{quote_id}", status_code=204, dependencies=[_WRITE])
async def delete_quote(quote_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> Response:
    svc, row = await _load(quote_id, session, user_id)
    await svc.delete(row)
    return Response(status_code=204)


@router.get("/quotes/{quote_id}/pages/{page}", dependencies=[_READ])
async def page_image(quote_id: uuid.UUID, page: int, session: SessionDep, user_id: CurrentUserId) -> Response:
    svc, row = await _load(quote_id, session, user_id)
    png = await svc.page_png(row, page)
    media = "image/png" if png[:4] == b"\x89PNG" else "image/jpeg"
    return Response(content=png, media_type=media, headers={"Cache-Control": "private, max-age=600"})


@router.get("/packages/{package_id}/levelling", response_model=LevellingOut, dependencies=[_READ])
async def levelling(package_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> LevellingOut:
    svc = QuoteCaptureService(session)
    package = await svc._package(package_id)
    if package is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Package not found")
    await verify_project_access(package.project_id, user_id, session)
    return LevellingOut.model_validate(await svc.levelling(package_id))
