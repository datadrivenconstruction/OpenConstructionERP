# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bid day API routes (mounted at ``/api/v1/bid-day``).

Every handler checks project access first, then the module permission. Every
edit answers with the whole recalculated board, so the client's optimistic
figure is replaced by the server's within one round trip.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response

from app.core.content_disposition import attachment_disposition
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.bid_day.exports import snapshot_pdf, snapshot_xlsx
from app.modules.bid_day.models import BidDayBoard
from app.modules.bid_day.schemas import (
    BoardOut,
    ChoiceUpdate,
    FreezeRequest,
    MarkupUpdate,
    PushOut,
    PushRequest,
    QuoteCreate,
    QuoteUpdate,
    RowCreate,
    RowUpdate,
    SnapshotOut,
    VersionOut,
)
from app.modules.bid_day.service import BidDayService

router = APIRouter(tags=["bid_day"])
_READ = Depends(RequirePermission("bid_day.read"))
_WRITE = Depends(RequirePermission("bid_day.write"))
_SUBMIT = Depends(RequirePermission("bid_day.submit"))


async def _load(board_id: uuid.UUID, session: SessionDep, user_id: str) -> tuple[BidDayService, BidDayBoard]:
    svc = BidDayService(session)
    board = await svc.board(board_id)
    await verify_project_access(board.project_id, user_id, session)
    return svc, board


async def _out(svc: BidDayService, board: BidDayBoard) -> BoardOut:
    await svc.session.flush()
    return BoardOut.model_validate(await svc.view(board))


@router.get("/tenders/{tender_id}/board", response_model=BoardOut, dependencies=[_READ])
async def open_board(tender_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> BoardOut:
    svc = BidDayService(session)
    tender = await svc.tender(tender_id)
    await verify_project_access(tender.project_id, user_id, session)
    return await _out(svc, await svc.open_board(tender_id, user_id))


@router.get("/boards/{board_id}", response_model=BoardOut, dependencies=[_READ])
async def get_board(board_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> BoardOut:
    svc, board = await _load(board_id, session, user_id)
    return await _out(svc, board)


@router.get("/boards/{board_id}/version", response_model=VersionOut, dependencies=[_READ])
async def board_version(board_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> VersionOut:
    _svc, board = await _load(board_id, session, user_id)
    return VersionOut(version=board.version, status=board.status)


@router.post("/boards/{board_id}/rows", response_model=BoardOut, dependencies=[_WRITE])
async def add_row(board_id: uuid.UUID, body: RowCreate, session: SessionDep, user_id: CurrentUserId) -> BoardOut:
    svc, board = await _load(board_id, session, user_id)
    await svc.add_row(board, body, user_id)
    return await _out(svc, board)


@router.patch("/boards/{board_id}/rows/{row_id}", response_model=BoardOut, dependencies=[_WRITE])
async def update_row(
    board_id: uuid.UUID, row_id: uuid.UUID, body: RowUpdate, session: SessionDep, user_id: CurrentUserId
) -> BoardOut:
    svc, board = await _load(board_id, session, user_id)
    await svc.update_row(board, row_id, body, user_id)
    return await _out(svc, board)


@router.delete("/boards/{board_id}/rows/{row_id}", response_model=BoardOut, dependencies=[_WRITE])
async def delete_row(board_id: uuid.UUID, row_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> BoardOut:
    svc, board = await _load(board_id, session, user_id)
    await svc.delete_row(board, row_id, user_id)
    return await _out(svc, board)


@router.put("/boards/{board_id}/rows/{row_id}/choice", response_model=BoardOut, dependencies=[_WRITE])
async def choose_quote(
    board_id: uuid.UUID, row_id: uuid.UUID, body: ChoiceUpdate, session: SessionDep, user_id: CurrentUserId
) -> BoardOut:
    svc, board = await _load(board_id, session, user_id)
    await svc.choose(board, row_id, body, user_id)
    return await _out(svc, board)


@router.post("/boards/{board_id}/rows/{row_id}/quotes", response_model=BoardOut, dependencies=[_WRITE])
async def add_quote(
    board_id: uuid.UUID, row_id: uuid.UUID, body: QuoteCreate, session: SessionDep, user_id: CurrentUserId
) -> BoardOut:
    svc, board = await _load(board_id, session, user_id)
    await svc.add_quote(board, row_id, body, user_id)
    return await _out(svc, board)


@router.patch("/boards/{board_id}/quotes/{quote_id}", response_model=BoardOut, dependencies=[_WRITE])
async def update_quote(
    board_id: uuid.UUID, quote_id: uuid.UUID, body: QuoteUpdate, session: SessionDep, user_id: CurrentUserId
) -> BoardOut:
    svc, board = await _load(board_id, session, user_id)
    await svc.update_quote(board, quote_id, body, user_id)
    return await _out(svc, board)


@router.delete("/boards/{board_id}/quotes/{quote_id}", response_model=BoardOut, dependencies=[_WRITE])
async def delete_quote(
    board_id: uuid.UUID, quote_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> BoardOut:
    svc, board = await _load(board_id, session, user_id)
    await svc.delete_quote(board, quote_id, user_id)
    return await _out(svc, board)


@router.patch("/boards/{board_id}/markups", response_model=BoardOut, dependencies=[_WRITE])
async def set_markups(board_id: uuid.UUID, body: MarkupUpdate, session: SessionDep, user_id: CurrentUserId) -> BoardOut:
    svc, board = await _load(board_id, session, user_id)
    await svc.set_markups(board, body, user_id)
    return await _out(svc, board)


@router.post("/boards/{board_id}/freeze", response_model=BoardOut, dependencies=[_SUBMIT])
async def freeze(board_id: uuid.UUID, body: FreezeRequest, session: SessionDep, user_id: CurrentUserId) -> BoardOut:
    svc, board = await _load(board_id, session, user_id)
    await svc.freeze(board, body.note, user_id)
    return await _out(svc, board)


@router.post("/boards/{board_id}/reopen", response_model=BoardOut, dependencies=[_SUBMIT])
async def reopen(board_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> BoardOut:
    svc, board = await _load(board_id, session, user_id)
    await svc.reopen(board, user_id)
    return await _out(svc, board)


@router.get("/boards/{board_id}/snapshots/{snapshot_id}", response_model=SnapshotOut, dependencies=[_READ])
async def get_snapshot(
    board_id: uuid.UUID, snapshot_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> SnapshotOut:
    svc, board = await _load(board_id, session, user_id)
    return SnapshotOut.model_validate(await svc.snapshot(board, snapshot_id))


@router.get("/boards/{board_id}/snapshots/{snapshot_id}/export", dependencies=[_READ])
async def export_snapshot(
    board_id: uuid.UUID, snapshot_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, fmt: str = "xlsx"
) -> Response:
    svc, board = await _load(board_id, session, user_id)
    snap = await svc.snapshot(board, snapshot_id)
    stamp = snap.created_at.strftime("%Y%m%d-%H%M")
    if fmt == "pdf":
        return Response(
            snapshot_pdf(snap.payload),
            media_type="application/pdf",
            headers={"Content-Disposition": attachment_disposition(f"submitted-bid-{stamp}.pdf")},
        )
    return Response(
        snapshot_xlsx(snap.payload),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": attachment_disposition(f"submitted-bid-{stamp}.xlsx")},
    )


@router.post("/boards/{board_id}/snapshots/{snapshot_id}/push", response_model=PushOut, dependencies=[_SUBMIT])
async def push_to_estimate(
    board_id: uuid.UUID, snapshot_id: uuid.UUID, body: PushRequest, session: SessionDep, user_id: CurrentUserId
) -> PushOut:
    svc, board = await _load(board_id, session, user_id)
    snap = await svc.snapshot(board, snapshot_id)
    return PushOut.model_validate(await svc.push_to_estimate(board, snap, dry_run=body.dry_run))
