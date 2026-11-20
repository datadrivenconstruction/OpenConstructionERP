# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tenders: one read API over every tender package, whichever module wrote it.

Mounted under ``/api/v1/bid-management/tenders/``. Lists the canonical
packages *including* the mirrors of tendering packages and RFQs (see
``legacy_mirror``), filtered by kind (``subcontract`` | ``supply``) and source.
A mirror is read here and edited in the module that owns it until that module
is retired; each row says which (``legacy_source`` and ``source_id``).

Also here: the old-id resolver the redirects use, the reconcile report of the
copy, and a JSON or CSV export of the old tables (principle 6: no lock-in).
"""

from __future__ import annotations

import csv
import io
import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.bid_management.legacy_mirror import INCLUDE_MIRRORS
from app.modules.bid_management.models import (
    BidAward,
    Bidder,
    BidInvitation,
    BidPackage,
    BidPackageLineItem,
    BidQA,
    BidSubmission,
    BidSubmissionLine,
    TenderLegacyMap,
)
from app.modules.bid_management.schemas import (
    BidAwardResponse,
    BidderResponse,
    BidInvitationResponse,
    BidPackageLineItemResponse,
    BidPackageResponse,
    BidSubmissionLineResponse,
    BidSubmissionResponse,
)

router = APIRouter(prefix="/tenders", tags=["tenders"])

_KINDS = r"^(subcontract|supply)$"
_SOURCES = r"^(native|tendering|rfq_bidding)$"
_ALL = {INCLUDE_MIRRORS: True}


class TenderSummary(BaseModel):
    """One row of the Tenders list."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    code: str
    title: str = ""
    status: str
    kind: str
    source: str
    source_id: str | None = None
    currency: str = ""
    submission_deadline: str | None = None
    bid_count: int = 0
    lowest_total: Decimal | None = None
    awarded_amount: Decimal | None = None
    awarded_bidder: str | None = None


class TenderDetail(BaseModel):
    """A tender package with everything the Tenders page shows."""

    package: BidPackageResponse
    source: str
    source_id: str | None = None
    read_only: bool = False
    line_items: list[BidPackageLineItemResponse] = Field(default_factory=list)
    invitations: list[BidInvitationResponse] = Field(default_factory=list)
    bidders: list[BidderResponse] = Field(default_factory=list)
    submissions: list[BidSubmissionResponse] = Field(default_factory=list)
    submission_lines: list[BidSubmissionLineResponse] = Field(default_factory=list)
    award: BidAwardResponse | None = None
    question_count: int = 0


class TenderResolve(BaseModel):
    """Where an old tendering or RFQ id lives in the canonical model."""

    source_table: str
    source_id: str
    package_id: uuid.UUID
    source: str


def _source_of(pkg: BidPackage) -> tuple[str, str | None]:
    if not pkg.legacy_source:
        return "native", None
    legacy = (pkg.metadata_ or {}).get("legacy") if isinstance(pkg.metadata_, dict) else None
    return pkg.legacy_source, (legacy or {}).get("source_id")


async def _package(session: Any, package_id: uuid.UUID, user_id: str) -> BidPackage:
    pkg = (
        await session.execute(select(BidPackage).where(BidPackage.id == package_id).execution_options(**_ALL))
    ).scalar_one_or_none()
    if pkg is None:
        raise HTTPException(status_code=404, detail="Tender not found")
    await verify_project_access(pkg.project_id, user_id, session)
    return pkg


@router.get("/", response_model=list[TenderSummary])
async def list_tenders(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    kind: str | None = Query(default=None, pattern=_KINDS),
    source: str | None = Query(default=None, pattern=_SOURCES),
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    _perm: None = Depends(RequirePermission("bid_management.read")),
) -> list[TenderSummary]:
    """Every tender package of a project, native and copied, newest first."""
    await verify_project_access(project_id, user_id, session)
    stmt = select(BidPackage).where(BidPackage.project_id == project_id)
    if kind:
        stmt = stmt.where(BidPackage.package_type == kind)
    if source == "native":
        stmt = stmt.where(BidPackage.legacy_source.is_(None))
    elif source:
        stmt = stmt.where(BidPackage.legacy_source == source)
    if status_filter:
        stmt = stmt.where(BidPackage.status == status_filter)
    stmt = stmt.order_by(BidPackage.created_at.desc(), BidPackage.id).offset(offset).limit(limit)
    packages = list((await session.execute(stmt.execution_options(**_ALL))).scalars().all())
    if not packages:
        return []
    ids = [p.id for p in packages]
    bids = (
        await session.execute(
            select(BidInvitation.package_id, func.count(BidSubmission.id), func.min(BidSubmission.total_amount))
            .join(BidSubmission, BidSubmission.invitation_id == BidInvitation.id)
            .where(BidInvitation.package_id.in_(ids))
            .group_by(BidInvitation.package_id)
            .execution_options(**_ALL)
        )
    ).all()
    by_pkg = {row[0]: (int(row[1]), row[2]) for row in bids}
    awards = (
        await session.execute(
            select(BidAward.package_id, BidAward.awarded_amount, Bidder.company_name)
            .join(Bidder, Bidder.id == BidAward.awarded_bidder_id)
            .where(BidAward.package_id.in_(ids))
            .execution_options(**_ALL)
        )
    ).all()
    award_by_pkg = {row[0]: (row[1], row[2]) for row in awards}
    out: list[TenderSummary] = []
    for pkg in packages:
        src, src_id = _source_of(pkg)
        count, lowest = by_pkg.get(pkg.id, (0, None))
        amount, winner = award_by_pkg.get(pkg.id, (None, None))
        out.append(
            TenderSummary(
                id=pkg.id,
                project_id=pkg.project_id,
                code=pkg.code,
                title=pkg.title,
                status=pkg.status,
                kind=pkg.package_type,
                source=src,
                source_id=src_id,
                currency=pkg.currency,
                submission_deadline=pkg.submission_deadline,
                bid_count=count,
                lowest_total=lowest,
                awarded_amount=amount,
                awarded_bidder=winner,
            )
        )
    return out


@router.get("/resolve/", response_model=TenderResolve)
async def resolve_tender(
    session: SessionDep,
    user_id: CurrentUserId,
    source_table: str = Query(..., pattern=r"^(oe_tendering_package|oe_rfq_rfq)$"),
    source_id: uuid.UUID = Query(...),
    _perm: None = Depends(RequirePermission("bid_management.read")),
) -> TenderResolve:
    """The canonical package of an old tender package or RFQ id (for redirects)."""
    row = (
        await session.execute(
            select(TenderLegacyMap.target_id).where(
                TenderLegacyMap.source_table == source_table, TenderLegacyMap.source_id == source_id
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Tender not found")
    pkg = await _package(session, row[0], user_id)
    return TenderResolve(
        source_table=source_table,
        source_id=str(source_id),
        package_id=pkg.id,
        source=pkg.legacy_source or "native",
    )


@router.get("/reconcile/")
async def reconcile_copy(
    session: SessionDep,
    _perm: None = Depends(RequirePermission("bid_management.delete")),
) -> dict[str, Any]:
    """Bid count and bid total, source against copy, for every old package."""
    from app.modules.bid_management.legacy_copy import reconcile  # noqa: PLC0415

    report = await session.run_sync(lambda s: reconcile(s.connection()))
    return {
        "ok": report.ok,
        "packages": len(report.packages),
        "mismatched": [p.line() for p in report.packages if not p.ok][:200],
    }


_EXPORT_TABLES = {
    "tendering": ("oe_tendering_package", "oe_tendering_bid", "oe_tendering_bid_invitation"),
    "rfq_bidding": ("oe_rfq_rfq", "oe_rfq_line", "oe_rfq_bid", "oe_rfq_bid_line", "oe_rfq_award"),
}


@router.get("/export/")
async def export_legacy(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    source: str = Query(..., pattern=r"^(tendering|rfq_bidding)$"),
    fmt: str = Query(default="json", alias="format", pattern=r"^(json|csv)$"),
    _perm: None = Depends(RequirePermission("bid_management.read")),
) -> Response:
    """The rows of a project in the old tables, as JSON (all tables) or CSV (packages)."""
    await verify_project_access(project_id, user_id, session)
    from app.modules.bid_management.legacy_copy import Tables  # noqa: PLC0415

    def _dump(sync_session: Any) -> dict[str, list[dict[str, Any]]]:
        t = Tables(sync_session.connection())
        names = _EXPORT_TABLES[source]
        head = t.get(names[0])
        if head is None:
            return {}
        pid = str(project_id)
        root_ids = [
            str(r[0]) for r in sync_session.connection().execute(select(head.c.id).where(head.c.project_id == pid))
        ]
        data: dict[str, list[dict[str, Any]]] = {}
        data[names[0]] = [
            dict(r) for r in sync_session.connection().execute(select(head).where(head.c.project_id == pid)).mappings()
        ]
        child_ids: dict[str, list[str]] = {}
        for name in names[1:]:
            table = t.get(name)
            if table is None:
                continue
            fk = "package_id" if "package_id" in table.c else ("rfq_id" if "rfq_id" in table.c else "bid_id")
            parents = child_ids.get("oe_rfq_bid", []) if fk == "bid_id" else root_ids
            rows = (
                [
                    dict(r)
                    for r in sync_session.connection().execute(select(table).where(table.c[fk].in_(parents))).mappings()
                ]
                if parents
                else []
            )
            data[name] = rows
            child_ids[name] = [str(r["id"]) for r in rows]
        return data

    data = await session.run_sync(_dump)
    if fmt == "csv":
        rows = next(iter(data.values()), [])
        buf = io.StringIO()
        if rows:
            writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            for row in rows:
                writer.writerow({k: _plain(v) for k, v in row.items()})
        return Response(
            content=buf.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{source}_packages.csv"'},
        )
    import json  # noqa: PLC0415

    body = json.dumps({k: [{c: _plain(v) for c, v in r.items()} for r in rows] for k, rows in data.items()})
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{source}_export.json"'},
    )


def _plain(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, dict | list):
        return value
    return str(value)


@router.get("/{package_id}", response_model=TenderDetail)
async def get_tender(
    package_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.read")),
) -> TenderDetail:
    """One tender with scope, invitations, bidders, bids, priced lines and award."""
    pkg = await _package(session, package_id, user_id)

    async def _all(stmt: Any) -> list[Any]:
        return list((await session.execute(stmt.execution_options(**_ALL))).scalars().all())

    lines = await _all(
        select(BidPackageLineItem)
        .where(BidPackageLineItem.package_id == pkg.id)
        .order_by(BidPackageLineItem.order_index, BidPackageLineItem.id)
    )
    invitations = await _all(
        select(BidInvitation).where(BidInvitation.package_id == pkg.id).order_by(BidInvitation.created_at)
    )
    bidders = await _all(select(Bidder).where(Bidder.package_id == pkg.id).order_by(Bidder.created_at))
    inv_ids = [i.id for i in invitations]
    submissions = (
        await _all(
            select(BidSubmission).where(BidSubmission.invitation_id.in_(inv_ids)).order_by(BidSubmission.created_at)
        )
        if inv_ids
        else []
    )
    sub_ids = [s.id for s in submissions]
    sub_lines = (
        await _all(select(BidSubmissionLine).where(BidSubmissionLine.submission_id.in_(sub_ids))) if sub_ids else []
    )
    award = (await _all(select(BidAward).where(BidAward.package_id == pkg.id)))[:1]
    questions = (
        await session.execute(select(func.count(BidQA.id)).where(BidQA.package_id == pkg.id).execution_options(**_ALL))
    ).scalar_one()
    src, src_id = _source_of(pkg)
    return TenderDetail(
        package=BidPackageResponse.model_validate(pkg),
        source=src,
        source_id=src_id,
        read_only=pkg.legacy_source is not None,
        line_items=[BidPackageLineItemResponse.model_validate(r) for r in lines],
        invitations=[BidInvitationResponse.model_validate(r) for r in invitations],
        bidders=[BidderResponse.model_validate(r) for r in bidders],
        submissions=[BidSubmissionResponse.model_validate(r) for r in submissions],
        submission_lines=[BidSubmissionLineResponse.model_validate(r) for r in sub_lines],
        award=BidAwardResponse.model_validate(award[0]) if award else None,
        question_count=int(questions or 0),
    )


@router.get("/{package_id}/validation")
async def validate_tender(
    package_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.read")),
) -> dict[str, Any]:
    """Run the ``tender`` merge rules on one tender; a copy is also reconciled with its source."""
    from app.core.validation.engine import ValidationContext  # noqa: PLC0415
    from app.modules.bid_management.legacy_copy import RFQ, TENDER_PACKAGE, reconcile_one  # noqa: PLC0415
    from app.modules.bid_management.tender_rules import _MERGE_RULES, tender_payload  # noqa: PLC0415

    detail = await get_tender(package_id, session, user_id)
    copy_line = None
    if detail.source in ("tendering", "rfq_bidding") and detail.source_id:
        table = TENDER_PACKAGE if detail.source == "tendering" else RFQ
        copy_line = await session.run_sync(lambda s: reconcile_one(s.connection(), table, detail.source_id))
    context = ValidationContext(data=tender_payload(detail, copy_line), project_id=str(detail.package.project_id))
    results = []
    for rule in _MERGE_RULES:
        for r in await rule.validate(context):
            results.append(
                {
                    "rule_id": r.rule_id,
                    "severity": str(r.severity),
                    "passed": r.passed,
                    "message": r.message,
                    "element_ref": r.element_ref,
                }
            )
    return {"package_id": str(package_id), "passed": all(r["passed"] for r in results), "results": results}
