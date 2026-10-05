# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tendering API routes.

Endpoints:
    POST   /packages/                       - Create a tender package
    GET    /packages/?project_id=xxx        - List packages
    GET    /packages/{package_id}           - Get package with bids
    PATCH  /packages/{package_id}           - Update package
    POST   /packages/{package_id}/bids      - Add a bid
    GET    /packages/{package_id}/bids      - List bids
    PATCH  /bids/{bid_id}                   - Update a bid
    GET    /packages/{package_id}/comparison - Compare all bids side-by-side
    GET    /packages/{package_id}/export/pdf - Export tender package as PDF
"""

import io
import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse

from app.core.content_disposition import attachment_disposition
from app.dependencies import (
    CurrentUserId,
    CurrentUserPayload,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.tendering.bid_portal import BidPortalService, enforce_rate_limit
from app.modules.tendering.schemas import (
    AddendumAcknowledgeRequest,
    AddendumCreate,
    AddendumResponse,
    AwardRecordNoteCreate,
    AwardRecordResponse,
    BidAnalysisResponse,
    BidComparisonResponse,
    BidCreate,
    BidInvitationCreated,
    BidInvitationListResponse,
    BidInvitationResponse,
    BidPortalPricesRequest,
    BidPortalView,
    BidResponse,
    BidUpdate,
    CreatePackageFromBOQData,
    DistributeRequest,
    DistributeResponse,
    LevelBidsResponse,
    LevelingMatrixResponse,
    PackageCreate,
    PackageResponse,
    PackageScopeResponse,
    PackageUpdate,
    PackageWithBidsResponse,
    RecipientCreate,
    RecipientResponse,
)
from app.modules.tendering.service import TenderingService

router = APIRouter(tags=["tendering"])
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> TenderingService:
    return TenderingService(session)


async def _verify_tender_project_owner(
    session: SessionDep,
    project_id: uuid.UUID,
    user_id: str,
    payload: dict | None = None,  # noqa: ARG001 - kept for call-site symmetry
) -> None:
    """Verify the caller may access the project.

    Routes through the shared ``verify_project_access`` helper so the
    tendering surface grants the SAME population (owner + admins + project
    team members) as every other module - previously this was owner-only,
    which silently locked team members out of the package/bid endpoints
    even though they could already reach ``GET /bid-analysis/`` (which uses
    ``verify_project_access``). ``verify_project_access`` raises 404 on both
    "missing" and "denied" (IDOR defence).
    """
    await verify_project_access(project_id, user_id, session)


async def _verify_package_owner(
    service: TenderingService,
    session: SessionDep,
    package_id: uuid.UUID,
    user_id: str,
    payload: dict | None = None,  # noqa: ARG001 - kept for call-site symmetry
) -> object:
    """Load a package, then verify project access (owner + admin + team)."""
    package = await service.get_package(package_id)
    await verify_project_access(package.project_id, user_id, session)
    return package


async def _caller_scope_project_ids(
    session: SessionDep,
    user_id: str,
) -> list[uuid.UUID] | None:
    """Project IDs the caller may reach, for scoping addendum lookups.

    Returns ``None`` for admins (no filter - cross-tenant by design) and the
    union of owned + team-member project IDs for everyone else. This is *only*
    used to keep ``find_addendum_package`` from scanning every package in the
    database; the authoritative access check stays ``verify_project_access`` on
    the resolved package's project (owner + admin + team), so this scope can
    never grant more than that check allows.
    """
    from sqlalchemy import select

    from app.modules.projects.models import Project
    from app.modules.teams.access import member_project_ids_subquery
    from app.modules.users.repository import UserRepository

    try:
        uid = uuid.UUID(str(user_id))
    except (ValueError, TypeError):
        return []

    try:
        user = await UserRepository(session).get_by_id(uid)
        if user is not None and getattr(user, "role", "") == "admin":
            return None
    except Exception:
        logger.exception("Admin-role lookup failed during addendum scope resolution")

    stmt = select(Project.id).where((Project.owner_id == uid) | (Project.id.in_(member_project_ids_subquery(uid))))
    rows = await session.execute(stmt)
    return list(rows.scalars().all())


async def _verify_bid_access(
    service: TenderingService,
    session: SessionDep,
    bid_id: uuid.UUID,
    user_id: str,
    payload: dict | None = None,
) -> object:
    """Load a bid → derive package → derive project → verify ownership.

    Closes the IDOR hole on ``PATCH /bids/{bid_id}`` where the update
    endpoint previously accepted any bid_id from any tenant.
    """
    try:
        bid = await service.get_bid(bid_id)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Failed to load bid %s: %s", bid_id, exc)
        raise HTTPException(status_code=404, detail="Bid not found")

    if bid is None:
        raise HTTPException(status_code=404, detail="Bid not found")

    # Delegate ownership check via the parent package
    await _verify_package_owner(service, session, bid.package_id, user_id, payload)
    return bid


def _package_to_response(package: object) -> PackageResponse:
    """Build a PackageResponse from a TenderPackage ORM object."""
    try:
        bids = list(package.bids)  # type: ignore[attr-defined]
    except Exception:
        bids = []
    return PackageResponse(
        id=package.id,  # type: ignore[attr-defined]
        project_id=package.project_id,  # type: ignore[attr-defined]
        boq_id=getattr(package, "boq_id", None),  # type: ignore[attr-defined]
        name=package.name,  # type: ignore[attr-defined]
        description=package.description,  # type: ignore[attr-defined]
        status=package.status,  # type: ignore[attr-defined]
        deadline=package.deadline,  # type: ignore[attr-defined]
        metadata=getattr(package, "metadata_", {}),  # type: ignore[attr-defined]
        created_at=package.created_at,  # type: ignore[attr-defined]
        updated_at=package.updated_at,  # type: ignore[attr-defined]
        bid_count=len(bids),
    )


def _bid_to_response(bid: object) -> BidResponse:
    """Build a BidResponse from a TenderBid ORM object."""
    return BidResponse(
        id=bid.id,  # type: ignore[attr-defined]
        package_id=bid.package_id,  # type: ignore[attr-defined]
        company_name=bid.company_name,  # type: ignore[attr-defined]
        contact_email=bid.contact_email,  # type: ignore[attr-defined]
        total_amount=bid.total_amount,  # type: ignore[attr-defined]
        currency=bid.currency,  # type: ignore[attr-defined]
        submitted_at=bid.submitted_at,  # type: ignore[attr-defined]
        status=bid.status,  # type: ignore[attr-defined]
        notes=bid.notes,  # type: ignore[attr-defined]
        line_items=bid.line_items,  # type: ignore[attr-defined]
        metadata=bid.metadata_,  # type: ignore[attr-defined]
        created_at=bid.created_at,  # type: ignore[attr-defined]
        updated_at=bid.updated_at,  # type: ignore[attr-defined]
    )


def _package_with_bids(package: object) -> PackageWithBidsResponse:
    """Build a PackageWithBidsResponse from a TenderPackage ORM object."""
    bids = getattr(package, "bids", []) or []
    return PackageWithBidsResponse(
        id=package.id,  # type: ignore[attr-defined]
        project_id=package.project_id,  # type: ignore[attr-defined]
        boq_id=package.boq_id,  # type: ignore[attr-defined]
        name=package.name,  # type: ignore[attr-defined]
        description=package.description,  # type: ignore[attr-defined]
        status=package.status,  # type: ignore[attr-defined]
        deadline=package.deadline,  # type: ignore[attr-defined]
        metadata=package.metadata_,  # type: ignore[attr-defined]
        created_at=package.created_at,  # type: ignore[attr-defined]
        updated_at=package.updated_at,  # type: ignore[attr-defined]
        bid_count=len(bids),
        bids=[_bid_to_response(b) for b in bids],
    )


# ── Root listing (BUG-TENDER01) ─────────────────────────────────────────────


@router.get("/", response_model=list[PackageResponse])
async def list_tenders_root(
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: TenderingService = Depends(_get_service),
    _perm: None = Depends(RequirePermission("tendering.read")),
    project_id: uuid.UUID | None = Query(
        default=None,
        description="Optional project filter. When omitted returns an empty list "
        "(cross-tenant enumeration is forbidden).",
    ),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[PackageResponse]:
    """List tender packages.

    Convenience root alias of ``GET /packages/`` so clients can probe
    ``/api/v1/tendering/`` without having to know the inner ``packages``
    sub-prefix. ``project_id`` is still required to return data - when omitted
    we return ``[]`` rather than 422 to keep the route discoverable for
    smoke probes.
    """
    if project_id is None:
        return []
    await _verify_tender_project_owner(session, project_id, user_id, payload)
    packages, _ = await service.list_packages(project_id=project_id, offset=offset, limit=limit)
    return [_package_to_response(p) for p in packages]


# ── Package Endpoints ────────────────────────────────────────────────────────


@router.post("/packages/", response_model=PackageResponse, status_code=201)
async def create_package(
    data: PackageCreate,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: TenderingService = Depends(_get_service),
    _perm: None = Depends(RequirePermission("tendering.create")),
) -> PackageResponse:
    """Create a new tender package from a BOQ."""
    await _verify_tender_project_owner(session, data.project_id, user_id, payload)
    try:
        package = await service.create_package(data)
        return _package_to_response(package)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to create tender package")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create tender package",
        )


@router.post("/packages/from-boq/", response_model=PackageResponse, status_code=201)
async def create_package_from_boq(
    data: CreatePackageFromBOQData,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: TenderingService = Depends(_get_service),
    _perm: None = Depends(RequirePermission("tendering.create")),
) -> PackageResponse:
    """Create a tender package seeded from selected BOQ sections.

    Loads the specified BOQ, collects every position under the requested
    top-level sections (or all sections when ``section_ids`` is empty), and
    creates a draft package whose metadata contains a compact line-item
    template ready for pre-seeding incoming bids.
    """
    await _verify_tender_project_owner(session, data.project_id, user_id, payload)
    try:
        package = await service.create_package_from_boq(data, actor_id=user_id)
        return _package_to_response(package)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to create tender package from BOQ")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create tender package from BOQ",
        )


@router.get("/packages/", response_model=list[PackageResponse])
async def list_packages(
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: TenderingService = Depends(_get_service),
    _perm: None = Depends(RequirePermission("tendering.read")),
    project_id: uuid.UUID = Query(
        ...,
        description="Required: project ID to scope the listing (prevents cross-tenant enumeration)",
    ),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[PackageResponse]:
    """List tender packages for a project.

    ``project_id`` is REQUIRED to prevent cross-tenant enumeration - the
    previous optional parameter let any authenticated user dump packages
    for every tenant when omitted.
    """
    await _verify_tender_project_owner(session, project_id, user_id, payload)
    packages, _ = await service.list_packages(project_id=project_id, offset=offset, limit=limit)
    return [_package_to_response(p) for p in packages]


@router.get("/packages/{package_id}", response_model=PackageWithBidsResponse)
async def get_package(
    package_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: TenderingService = Depends(_get_service),
    _perm: None = Depends(RequirePermission("tendering.read")),
) -> PackageWithBidsResponse:
    """Get a tender package with all bids."""
    package = await _verify_package_owner(service, session, package_id, user_id, payload)
    return _package_with_bids(package)


@router.get("/packages/{package_id}/scope", response_model=PackageScopeResponse)
async def get_package_scope(
    package_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: TenderingService = Depends(_get_service),
    _perm: None = Depends(RequirePermission("tendering.read")),
) -> PackageScopeResponse:
    """Report which sections of the bill this package was raised over.

    The comparison and levelling screens already narrow to that scope, so this
    is the fact they compute made readable rather than a new one.
    """
    await _verify_package_owner(service, session, package_id, user_id, payload)
    return await service.package_scope(package_id)


@router.patch("/packages/{package_id}", response_model=PackageResponse)
async def update_package(
    package_id: uuid.UUID,
    data: PackageUpdate,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: TenderingService = Depends(_get_service),
    _perm: None = Depends(RequirePermission("tendering.update")),
) -> PackageResponse:
    """Update a tender package status or fields."""
    await _verify_package_owner(service, session, package_id, user_id, payload)
    package = await service.update_package(package_id, data)
    return _package_to_response(package)


# ── Bid Endpoints ────────────────────────────────────────────────────────────


@router.post("/packages/{package_id}/bids/", response_model=BidResponse, status_code=201)
async def create_bid(
    package_id: uuid.UUID,
    data: BidCreate,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: TenderingService = Depends(_get_service),
    _perm: None = Depends(RequirePermission("tendering.bid.create")),
) -> BidResponse:
    """Add a bid to a tender package."""
    await _verify_package_owner(service, session, package_id, user_id, payload)
    try:
        bid = await service.create_bid(package_id, data)
        return _bid_to_response(bid)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to create bid for package %s", package_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create bid",
        )


@router.get("/packages/{package_id}/bids/", response_model=list[BidResponse])
async def list_bids(
    package_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: TenderingService = Depends(_get_service),
    _perm: None = Depends(RequirePermission("tendering.read")),
) -> list[BidResponse]:
    """List all bids for a tender package."""
    await _verify_package_owner(service, session, package_id, user_id, payload)
    bids = await service.list_bids(package_id)
    return [_bid_to_response(b) for b in bids]


@router.patch("/bids/{bid_id}", response_model=BidResponse)
async def update_bid(
    bid_id: uuid.UUID,
    data: BidUpdate,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: TenderingService = Depends(_get_service),
    _perm: None = Depends(RequirePermission("tendering.bid.update")),
) -> BidResponse:
    """Update a bid.

    Verifies the caller owns the parent package's project before
    accepting the mutation - otherwise a cross-tenant tamper attack
    could silently rewrite competing bids.
    """
    await _verify_bid_access(service, session, bid_id, user_id, payload)

    # Accepting or rejecting a bid is an award decision and must require
    # tendering.award (the same gate apply-winner uses). The generic
    # tendering.bid.update permission must not let an editor flip a bid to
    # accepted/rejected and bypass that gate. Mirrors RequirePermission: admin
    # bypass, explicit token permission, then live role-registry fallback.
    if (data.status or "").lower() in {"accepted", "rejected"}:
        from app.core.permissions import permission_registry as _reg

        role = payload.get("role", "")
        perms = payload.get("permissions", []) or []
        if role != "admin" and "tendering.award" not in perms and not _reg.role_has_permission(role, "tendering.award"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Accepting or rejecting a bid requires the tendering.award permission.",
            )

    try:
        bid = await service.update_bid(bid_id, data)
        return _bid_to_response(bid)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to update bid %s", bid_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update bid",
        )


# ── Comparison Endpoint ──────────────────────────────────────────────────────


@router.get(
    "/packages/{package_id}/comparison/",
    response_model=BidComparisonResponse,
)
async def compare_bids(
    package_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: TenderingService = Depends(_get_service),
    _perm: None = Depends(RequirePermission("tendering.comparison.read")),
) -> BidComparisonResponse:
    """Compare all bids for a package side-by-side."""
    await _verify_package_owner(service, session, package_id, user_id, payload)
    return await service.compare_bids(package_id)


_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


async def _project_name_and_currency(session: SessionDep, project_id: uuid.UUID) -> tuple[str, str]:
    from app.modules.projects.repository import ProjectRepository

    project = await ProjectRepository(session).get_by_id(project_id)
    if project is None:
        return "", ""
    return str(getattr(project, "name", "") or ""), (getattr(project, "currency", "") or "").strip().upper()


@router.get("/packages/{package_id}/comparison/export/")
async def export_bid_comparison_xlsx(
    package_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: TenderingService = Depends(_get_service),
    _perm: None = Depends(RequirePermission("tendering.comparison.read")),
    locale: str | None = Query(default=None, max_length=10, description="Sheet language, overrides Accept-Language"),
    accept_language: str | None = Header(default=None, alias="accept-language"),
) -> StreamingResponse:
    """Download the price comparison as an Excel workbook.

    The sheet is the comparison endpoint's answer laid out per bill line, with
    the lowest unit price, missing prices and outliers marked, and each
    bidder's submitted total. ``Content-Language`` names the language the
    sheet's own text is written in.
    """
    import asyncio

    from app.modules.tendering.workbooks import render_comparison_xlsx
    from app.modules.tendering.xlsx_translations import resolve_xlsx_locale, xt

    package = await _verify_package_owner(service, session, package_id, user_id, payload)
    comparison = await service.compare_bids(package_id)
    project_name, project_currency = await _project_name_and_currency(session, package.project_id)  # type: ignore[attr-defined]
    if not project_currency:
        # No project currency: rank in the currency most bids are quoted in,
        # the same fallback the comparison uses for its deviations.
        counts: dict[str, int] = {}
        for bt in comparison.bid_totals:
            code = str(bt.get("currency") or "").strip().upper()
            if code:
                counts[code] = counts.get(code, 0) + 1
        project_currency = max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0] if counts else ""
    sheet_locale = resolve_xlsx_locale(locale, accept_language)
    data = await asyncio.to_thread(
        render_comparison_xlsx,
        comparison,
        project_name=project_name,
        reporting_currency=project_currency,
        locale=sheet_locale,
    )
    filename = f"{comparison.package_name} - {xt(sheet_locale, 'comparison_title')}.xlsx"
    return StreamingResponse(
        iter([data]),
        media_type=_XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": attachment_disposition(filename), "Content-Language": sheet_locale},
    )


@router.get("/packages/{package_id}/export/bidder-xlsx/")
async def export_bill_for_bidders_xlsx(
    package_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: TenderingService = Depends(_get_service),
    _perm: None = Depends(RequirePermission("tendering.read")),
    locale: str | None = Query(default=None, max_length=10, description="Sheet language, overrides Accept-Language"),
    accept_language: str | None = Header(default=None, alias="accept-language"),
) -> StreamingResponse:
    """Download the package's lines as an Excel sheet for bidders to price.

    Only the lines the package was raised over, with quantities and texts and
    none of the contractor's own rates, totals or markups. Each line has an
    open unit price cell and a line total formula.
    """
    import asyncio

    from app.modules.boq.service import BOQService, exportable_positions
    from app.modules.tendering.service import _positions_in_scope
    from app.modules.tendering.workbooks import bidder_lines, render_bidder_xlsx
    from app.modules.tendering.xlsx_translations import resolve_xlsx_locale, xt

    package = await _verify_package_owner(service, session, package_id, user_id, payload)
    boq_id = getattr(package, "boq_id", None)
    if boq_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Package has no linked BOQ to send out")
    boq_data = await BOQService(session).get_boq_with_positions(boq_id)
    positions = exportable_positions(boq_data.positions)
    lines = bidder_lines(positions, _positions_in_scope(positions, getattr(package, "metadata_", None)))
    project_name, project_currency = await _project_name_and_currency(session, package.project_id)  # type: ignore[attr-defined]
    deadline = getattr(package, "deadline", None)
    sheet_locale = resolve_xlsx_locale(locale, accept_language)
    data = await asyncio.to_thread(
        render_bidder_xlsx,
        lines,
        project_name=project_name,
        package_name=str(getattr(package, "name", "") or ""),
        currency=project_currency,
        deadline=str(deadline)[:10] if deadline else "",
        locale=sheet_locale,
    )
    filename = f"{getattr(package, 'name', '') or 'tender'} - {xt(sheet_locale, 'bidder_title')}.xlsx"
    return StreamingResponse(
        iter([data]),
        media_type=_XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": attachment_disposition(filename), "Content-Language": sheet_locale},
    )


@router.get("/packages/{package_id}/export/gaeb-x83/")
async def export_package_gaeb_x83(
    package_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: TenderingService = Depends(_get_service),
    _perm: None = Depends(RequirePermission("tendering.read")),
) -> StreamingResponse:
    """Download the package's lines as a GAEB DA XML 3.3 call for bids (X83).

    The same positions as the Excel bill for bidders, written by the BOQ
    module's GAEB writer: unpriced, as DP 83 is, and without the lines of the
    bill the package was not raised over.
    """
    import asyncio

    from app.modules.boq.router import build_gaeb_xml
    from app.modules.boq.service import BOQService, exportable_positions
    from app.modules.tendering.gaeb_package import package_bill, package_line_ids

    package = await _verify_package_owner(service, session, package_id, user_id, payload)
    boq_id = getattr(package, "boq_id", None)
    if boq_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Package has no linked BOQ to send out")
    boq_service = BOQService(session)
    positions = exportable_positions((await boq_service.get_boq_with_positions(boq_id)).positions)
    line_ids = package_line_ids(positions, getattr(package, "metadata_", None))
    bill = package_bill(await boq_service.get_boq_structured_for_export(boq_id), line_ids)
    if not bill.sections and not bill.positions:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Package has no lines to send out")
    project_name, project_currency = await _project_name_and_currency(session, package.project_id)  # type: ignore[attr-defined]
    xml_content = await asyncio.to_thread(
        build_gaeb_xml,
        bill,
        project_name=project_name,
        project_currency=project_currency[:3],
        gaeb_format="x83",
    )
    filename = f"{getattr(package, 'name', '') or 'tender'}.X83"
    return StreamingResponse(
        iter([xml_content]),
        media_type="application/xml; charset=utf-8",
        headers={"Content-Disposition": attachment_disposition(filename)},
    )


@router.post("/packages/{package_id}/apply-winner/")
async def apply_tender_winner(
    package_id: uuid.UUID,
    bid_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: TenderingService = Depends(_get_service),
    _perm: None = Depends(RequirePermission("tendering.award")),
) -> dict:
    """Award the package to *bid_id* and copy its unit rates into the BOQ.

    Closes the loop between tendering and estimation: once a winner is
    chosen, the BOQ positions are updated with the winning unit_rates so
    the project budget reflects the actual contracted price.
    """
    await _verify_package_owner(service, session, package_id, user_id, payload)
    return await service.apply_winner(package_id, bid_id, awarded_by=user_id)


# ── Distribution Endpoints ────────────────────────────────────────────────────


@router.get("/packages/{package_id}/recipients/", response_model=list[RecipientResponse])
async def list_package_recipients(
    package_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: TenderingService = Depends(_get_service),
    _perm: None = Depends(RequirePermission("tendering.read")),
) -> list[RecipientResponse]:
    """List the subcontractors on a package's distribution list."""
    await _verify_package_owner(service, session, package_id, user_id, payload)
    return await service.list_recipients(package_id)


@router.post(
    "/packages/{package_id}/recipients/",
    response_model=RecipientResponse,
    status_code=201,
)
async def add_package_recipient(
    package_id: uuid.UUID,
    data: RecipientCreate,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: TenderingService = Depends(_get_service),
    _perm: None = Depends(RequirePermission("tendering.distribute")),
) -> RecipientResponse:
    """Add a subcontractor to a package's distribution list."""
    await _verify_package_owner(service, session, package_id, user_id, payload)
    return await service.add_recipient(package_id, data, actor_id=user_id)


@router.delete(
    "/packages/{package_id}/recipients/{recipient_id}",
    status_code=204,
)
async def remove_package_recipient(
    package_id: uuid.UUID,
    recipient_id: str,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: TenderingService = Depends(_get_service),
    _perm: None = Depends(RequirePermission("tendering.distribute")),
) -> None:
    """Remove a subcontractor from a package's distribution list."""
    await _verify_package_owner(service, session, package_id, user_id, payload)
    await service.remove_recipient(package_id, recipient_id)


@router.post(
    "/packages/{package_id}/distribute/",
    response_model=DistributeResponse,
)
async def distribute_package(
    package_id: uuid.UUID,
    data: DistributeRequest,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: TenderingService = Depends(_get_service),
    _perm: None = Depends(RequirePermission("tendering.distribute")),
) -> DistributeResponse:
    """Email the tender package to its recipients.

    Sends each recipient an invitation-to-tender email (with the package
    details and a link), records the per-recipient send state/timestamp, and
    degrades gracefully when SMTP is not configured: the platform email sender
    falls back to the console backend and never raises, so the response reports
    the resolved backend and ``smtp_configured`` instead of crashing.
    """
    await _verify_package_owner(service, session, package_id, user_id, payload)
    return await service.distribute_package(package_id, data, actor_id=user_id)


# ── Bidder price-entry links ──────────────────────────────────────────────────
# Staff routes make, list and revoke a recipient's personal link; they are
# guarded like every package route (permission + ``_verify_package_owner``).
# The public routes below take no login: the token in the path is the
# credential, see ``bid_portal.py`` for what that implies and what the public
# payload is allowed to carry.


def _get_bid_portal(session: SessionDep) -> BidPortalService:
    return BidPortalService(session)


@router.get("/packages/{package_id}/bid-invitations/", response_model=BidInvitationListResponse)
async def list_bid_invitations(
    package_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: TenderingService = Depends(_get_service),
    _perm: None = Depends(RequirePermission("tendering.read")),
) -> BidInvitationListResponse:
    """Every bidder link of a package with its status, newest first. Never the token."""
    await _verify_package_owner(service, session, package_id, user_id, payload)
    items = await _get_bid_portal(session).list_invitations(package_id)
    return BidInvitationListResponse(items=items, total=len(items))


@router.post(
    "/packages/{package_id}/recipients/{recipient_id}/bid-link/",
    response_model=BidInvitationCreated,
    status_code=201,
)
async def create_bid_link(
    package_id: uuid.UUID,
    recipient_id: str,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: TenderingService = Depends(_get_service),
    _perm: None = Depends(RequirePermission("tendering.distribute")),
    reopen: bool = Query(default=False, description="Let a firm that already submitted revise its bid"),
) -> BidInvitationCreated:
    """Make a new price-entry link for a recipient and return its URL once.

    Any older link of the same recipient stops working; its draft, bid and
    submitted state carry over to the new one, so a firm that submitted gets a
    read-only receipt unless ``reopen`` is set.
    """
    await _verify_package_owner(service, session, package_id, user_id, payload)
    return await _get_bid_portal(session).create_link(package_id, recipient_id, actor_id=user_id, reopen=reopen)


@router.post(
    "/packages/{package_id}/bid-invitations/{invitation_id}/revoke/",
    response_model=BidInvitationResponse,
)
async def revoke_bid_invitation(
    package_id: uuid.UUID,
    invitation_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: TenderingService = Depends(_get_service),
    _perm: None = Depends(RequirePermission("tendering.distribute")),
) -> BidInvitationResponse:
    """Revoke one link. A submitted bid stays; only the link stops working."""
    await _verify_package_owner(service, session, package_id, user_id, payload)
    return await _get_bid_portal(session).revoke(package_id, invitation_id)


def _public_headers(response: Response) -> None:
    # The URL carries the credential: keep answers out of caches and indexes.
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["Referrer-Policy"] = "no-referrer"


@router.get("/bid-portal/{token}/", response_model=BidPortalView)
async def bid_portal_view(
    token: str,
    request: Request,
    response: Response,
    session: SessionDep,
) -> BidPortalView:
    """Public: the bill to price, the package facts and the bidder's own draft.

    No login. Unknown token 404, revoked or expired 410, each with a bare code.
    """
    enforce_rate_limit(request, write=False)
    _public_headers(response)
    return await _get_bid_portal(session).public_view(token)


@router.put("/bid-portal/{token}/draft/", response_model=BidPortalView)
async def bid_portal_save_draft(
    token: str,
    body: BidPortalPricesRequest,
    request: Request,
    response: Response,
    session: SessionDep,
) -> BidPortalView:
    """Public: save the bidder's unit prices without submitting."""
    enforce_rate_limit(request, write=True)
    _public_headers(response)
    return await _get_bid_portal(session).save_draft(token, body)


@router.post("/bid-portal/{token}/submit/", response_model=BidPortalView)
async def bid_portal_submit(
    token: str,
    body: BidPortalPricesRequest,
    request: Request,
    response: Response,
    session: SessionDep,
) -> BidPortalView:
    """Public: submit the bid. The link is read-only afterwards."""
    enforce_rate_limit(request, write=True)
    _public_headers(response)
    return await _get_bid_portal(session).submit(token, body)


# ── Addenda Endpoints ────────────────────────────────────────────────────────


@router.get("/packages/{package_id}/addenda/", response_model=list[AddendumResponse])
async def list_package_addenda(
    package_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: TenderingService = Depends(_get_service),
    _perm: None = Depends(RequirePermission("tendering.addendum.read")),
) -> list[AddendumResponse]:
    """List a package's addenda (mid-tender clarifications), oldest first."""
    await _verify_package_owner(service, session, package_id, user_id, payload)
    return await service.list_addenda(package_id)


@router.post(
    "/packages/{package_id}/addenda/",
    response_model=AddendumResponse,
    status_code=201,
)
async def create_package_addendum(
    package_id: uuid.UUID,
    data: AddendumCreate,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: TenderingService = Depends(_get_service),
    _perm: None = Depends(RequirePermission("tendering.addendum.create")),
) -> AddendumResponse:
    """Create a new draft addendum on a package."""
    await _verify_package_owner(service, session, package_id, user_id, payload)
    return await service.create_addendum(package_id, data)


@router.post("/addenda/{addendum_id}/publish/", response_model=AddendumResponse)
async def publish_package_addendum(
    addendum_id: str,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: TenderingService = Depends(_get_service),
    _perm: None = Depends(RequirePermission("tendering.addendum.publish")),
) -> AddendumResponse:
    """Publish a draft addendum so bidders can acknowledge it."""
    scope = await _caller_scope_project_ids(session, user_id)
    package, _entry, _idx = await service.find_addendum_package(addendum_id, scope)
    await verify_project_access(package.project_id, user_id, session)
    return await service.publish_addendum(package, addendum_id, user_id)


@router.post("/addenda/{addendum_id}/acknowledge/", response_model=AddendumResponse)
async def acknowledge_package_addendum(
    addendum_id: str,
    data: AddendumAcknowledgeRequest,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: TenderingService = Depends(_get_service),
    _perm: None = Depends(RequirePermission("tendering.addendum.acknowledge")),
) -> AddendumResponse:
    """Record a bidder's acknowledgement of a published addendum."""
    scope = await _caller_scope_project_ids(session, user_id)
    package, _entry, _idx = await service.find_addendum_package(addendum_id, scope)
    await verify_project_access(package.project_id, user_id, session)
    return await service.acknowledge_addendum(package, addendum_id, data.bidder_id, user_id)


# ── Bid Leveling Endpoints ─────────────────────────────────────────────────────


@router.get(
    "/packages/{package_id}/leveling-matrix/",
    response_model=LevelingMatrixResponse,
)
async def get_leveling_matrix(
    package_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: TenderingService = Depends(_get_service),
    _perm: None = Depends(RequirePermission("tendering.leveling.read")),
) -> LevelingMatrixResponse:
    """Return the bid-leveling matrix (reference BOQ lines × bids)."""
    await _verify_package_owner(service, session, package_id, user_id, payload)
    return await service.get_leveling_matrix(package_id)


@router.post(
    "/packages/{package_id}/level-bids/",
    response_model=LevelBidsResponse,
)
async def level_package_bids(
    package_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: TenderingService = Depends(_get_service),
    _perm: None = Depends(RequirePermission("tendering.leveling.run")),
) -> LevelBidsResponse:
    """Run bid leveling across a package's bids and return the rollup."""
    await _verify_package_owner(service, session, package_id, user_id, payload)
    return await service.level_bids(package_id)


# ── Award record (Vergabevermerk) ─────────────────────────────────────────────
# Guarded exactly like the neighbouring package routes: the declared permission
# plus ``_verify_package_owner``, which loads the package and then runs
# ``verify_project_access`` (owner + admin + team, 404 on both missing and
# denied). Reading the record is a read of the package, and writing a statement
# into it is an update of the package, so the existing ``tendering.read`` and
# ``tendering.update`` permissions are the right ones; the record is not a
# separate object with a separate right.


@router.get("/packages/{package_id}/award-record/", response_model=AwardRecordResponse)
async def get_award_record(
    package_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: TenderingService = Depends(_get_service),
    _perm: None = Depends(RequirePermission("tendering.read")),
) -> AwardRecordResponse:
    """The written record of the award procedure, at whatever stage it stands.

    Assembled from the procedure itself rather than from anything retyped, and
    readable from the first day: the sections the procedure already owes and
    that nothing has answered are returned as gaps rather than left blank.
    """
    await _verify_package_owner(service, session, package_id, user_id, payload)
    return await service.award_record(package_id)


@router.post("/packages/{package_id}/award-record/notes/", response_model=AwardRecordResponse, status_code=201)
async def record_award_record_note(
    package_id: uuid.UUID,
    data: AwardRecordNoteCreate,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: TenderingService = Depends(_get_service),
    _perm: None = Depends(RequirePermission("tendering.update")),
) -> AwardRecordResponse:
    """Write one statement into the record and return the record as it now reads.

    Only the statements a person has to make are accepted here: which procedure
    type was chosen and why, the award criteria, the ground for excluding a bid,
    and why the winning bid won. Everything else the record states comes from
    the procedure. Statements are append-only, so writing a section again
    supersedes the earlier statement instead of erasing it.
    """
    await _verify_package_owner(service, session, package_id, user_id, payload)
    return await service.record_award_note(package_id, data, actor_id=user_id)


@router.get("/packages/{package_id}/award-record/pdf/")
async def export_award_record_pdf(
    package_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: TenderingService = Depends(_get_service),
    _perm: None = Depends(RequirePermission("tendering.read")),
) -> StreamingResponse:
    """Download the award record as a PDF for filing.

    Reuses the module's PDF stack (reportlab, via ``pdf_documents.py``) so the
    record matches the award and rejection letters. Available at every stage,
    with the still-open points printed, because a record that could only be
    exported once the award was made would be the reconstruction after the fact
    that the rule exists to prevent.
    """
    await _verify_package_owner(service, session, package_id, user_id, payload)
    try:
        pdf_bytes, filename = await service.build_award_record_pdf(package_id)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to generate award record for package %s", package_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate award record",
        )
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": attachment_disposition(filename),
            # Every tendering document on this router is written in English:
            # pdf_documents.py holds its labels as English literals and takes no
            # locale from anywhere. Saying so is not a limitation we are adding,
            # it is the one we already have. Without this line the
            # Accept-Language middleware labels these bytes with whatever the
            # reader asked for, so a bidder who set the interface to French
            # receives an English document declared French, and neither the
            # browser nor an archive can tell that it is a fallback.
            "Content-Language": "en",
        },
    )


# ── Export Endpoints ──────────────────────────────────────────────────────────


@router.get("/packages/{package_id}/export/pdf/")
async def export_tender_pdf(
    package_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: TenderingService = Depends(_get_service),
    _perm: None = Depends(RequirePermission("tendering.read")),
) -> StreamingResponse:
    """Export tender package with bid comparison as a PDF report.

    Generates a simple text-based PDF using only the Python standard library
    so that no extra dependencies (reportlab, etc.) are required.
    """
    await _verify_package_owner(service, session, package_id, user_id, payload)
    package = await service.get_package(package_id)
    comparison = await service.compare_bids(package_id)

    # ── Build a minimal valid PDF in memory ──────────────────────────────
    buf = io.BytesIO()

    def _w(s: str) -> None:
        buf.write(s.encode("latin-1", errors="replace"))

    offsets: list[int] = []

    def _obj() -> int:
        idx = len(offsets) + 1
        offsets.append(buf.tell())
        _w(f"{idx} 0 obj\n")
        return idx

    # Build page content lines
    lines: list[str] = []
    lines.append(f"Tender Package: {package.name}")
    lines.append(f"Status: {package.status}")
    lines.append(f"Deadline: {package.deadline or 'N/A'}")
    lines.append(f"Generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")
    lines.append(f"Budget Total: {comparison.budget_total:,.2f}")
    lines.append(f"Number of Bids: {comparison.bid_count}")
    lines.append("")

    if comparison.bid_totals:
        lines.append("--- Bid Summary ---")
        for bt in comparison.bid_totals:
            company = bt.get("company_name", "Unknown")
            total = bt.get("total", 0)
            currency = bt.get("currency", "")
            dev = bt.get("deviation_pct", 0)
            sign = "+" if dev >= 0 else ""
            tail = f"{currency} " if currency else ""
            lines.append(f"  {company}: {total:,.2f} {tail}({sign}{dev}%)")
        lines.append("")

    if comparison.rows:
        lines.append("--- Position Comparison ---")
        for row in comparison.rows[:50]:  # Limit to first 50 rows for PDF size
            lines.append(
                f"  {row.description[:60]:<60s}  "
                f"{row.budget_quantity:>10.2f} {row.unit:<5s}  "
                f"Budget: {row.budget_total:>12,.2f}"
            )

    # Encode content stream
    y = 750
    stream_lines: list[str] = []
    stream_lines.append("BT")
    stream_lines.append("/F1 10 Tf")
    for line in lines:
        safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream_lines.append(f"1 0 0 1 50 {y} Tm")
        stream_lines.append(f"({safe}) Tj")
        y -= 14
        if y < 50:
            break
    stream_lines.append("ET")
    stream_content = "\n".join(stream_lines)

    # Header
    _w("%PDF-1.4\n")

    # Object layout: 1=Catalog, 2=Pages, 3=Page, 4=Stream, 5=Font
    # Catalog (obj 1)
    _obj()
    _w("<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")

    # Pages (obj 2)
    _obj()
    _w("<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n")

    # Page (obj 3) - references stream (4) and font (5)
    _obj()
    _w(
        "<< /Type /Page /Parent 2 0 R "
        "/MediaBox [0 0 612 792] "
        "/Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> "
        ">>\nendobj\n"
    )

    # Stream (obj 4)
    _obj()
    _w(f"<< /Length {len(stream_content)} >>\nstream\n{stream_content}\nendstream\nendobj\n")

    # Font (obj 5)
    _obj()
    _w("<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>\nendobj\n")

    # Cross-reference table
    xref_offset = buf.tell()
    _w("xref\n")
    _w(f"0 {len(offsets) + 1}\n")
    _w("0000000000 65535 f \n")
    for off in offsets:
        _w(f"{off:010d} 00000 n \n")

    _w("trailer\n")
    _w(f"<< /Size {len(offsets) + 1} /Root 1 0 R >>\n")
    _w("startxref\n")
    _w(f"{xref_offset}\n")
    _w("%%EOF\n")

    buf.seek(0)
    filename = f"tender_{package.name.replace(' ', '_')}_{package_id.hex[:8]}.pdf"

    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={
            # RFC 6266 - a package name with non-Latin-1 chars would otherwise 500
            # while the ASGI server encodes this header.
            "Content-Disposition": attachment_disposition(filename),
            # English, and this page can hold nothing else: the stream above is
            # a single Courier byte stream written through latin-1, so the
            # document could not carry another script even if the labels were
            # translated. The declaration is therefore about the page as it is
            # built rather than a placeholder for a locale that might arrive.
            "Content-Language": "en",
        },
    )


@router.get("/packages/{package_id}/bids/{bid_id}/award-letter/pdf/")
async def export_award_letter_pdf(
    package_id: uuid.UUID,
    bid_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: TenderingService = Depends(_get_service),
    _perm: None = Depends(RequirePermission("tendering.distribute")),
) -> StreamingResponse:
    """Download a PDF letter of award for the winning bid.

    Reuses the platform PDF stack (reportlab, via tendering/pdf_documents.py)
    so the award letter matches the look of the BOQ cost estimate. Money is
    rendered Decimal-correct. Tenant-scoped via project access on the package.
    """
    await _verify_package_owner(service, session, package_id, user_id, payload)
    try:
        pdf_bytes, filename = await service.build_award_letter_pdf(package_id, bid_id)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to generate award letter for package %s bid %s", package_id, bid_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate award letter",
        )
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": attachment_disposition(filename),
            # English for the reason given on the award record above.
            "Content-Language": "en",
        },
    )


@router.get("/packages/{package_id}/bids/{bid_id}/rejection-letter/pdf/")
async def export_rejection_letter_pdf(
    package_id: uuid.UUID,
    bid_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: TenderingService = Depends(_get_service),
    _perm: None = Depends(RequirePermission("tendering.distribute")),
) -> StreamingResponse:
    """Download a PDF rejection notice for an unsuccessful bid.

    Reuses the platform PDF stack (reportlab). Money is Decimal-correct and the
    awarded sum is shown for transparency only when it shares the rejected
    bid's currency. Tenant-scoped via project access on the package.
    """
    await _verify_package_owner(service, session, package_id, user_id, payload)
    try:
        pdf_bytes, filename = await service.build_rejection_letter_pdf(package_id, bid_id)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to generate rejection notice for package %s bid %s", package_id, bid_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate rejection notice",
        )
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            # A rejection is the letter a losing bidder keeps, so being able to
            # tell that it was written in English rather than in the language
            # they asked for matters more here than anywhere else on this
            # router.
            "Content-Disposition": attachment_disposition(filename),
            "Content-Language": "en",
        },
    )


# ── Project Intelligence (RFC 25) ───────────────────────────────────────────


@router.get(
    "/bid-analysis/",
    response_model=BidAnalysisResponse,
    summary="Bid vendor concentration + outlier + spread (RFC 25)",
)
async def get_bid_analysis(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(..., description="Project scope"),
    service: TenderingService = Depends(_get_service),
    _perm: None = Depends(RequirePermission("tendering.read")),
) -> BidAnalysisResponse:
    """Cross-package bid analysis for the Estimation Dashboard."""
    await verify_project_access(project_id, user_id, session)
    return await service.get_bid_analysis(project_id)
