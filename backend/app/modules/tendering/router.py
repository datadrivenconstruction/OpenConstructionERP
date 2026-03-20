"""Tendering API routes.

Endpoints:
    POST   /packages/                       — Create a tender package
    GET    /packages/?project_id=xxx        — List packages
    GET    /packages/{package_id}           — Get package with bids
    PATCH  /packages/{package_id}           — Update package
    POST   /packages/{package_id}/bids      — Add a bid
    GET    /packages/{package_id}/bids      — List bids
    PATCH  /bids/{bid_id}                   — Update a bid
    GET    /packages/{package_id}/comparison — Compare all bids side-by-side
"""

import uuid

from fastapi import APIRouter, Depends, Query

from app.dependencies import CurrentUserId, SessionDep
from app.modules.tendering.schemas import (
    BidComparisonResponse,
    BidCreate,
    BidResponse,
    BidUpdate,
    PackageCreate,
    PackageResponse,
    PackageUpdate,
    PackageWithBidsResponse,
)
from app.modules.tendering.service import TenderingService

router = APIRouter()


def _get_service(session: SessionDep) -> TenderingService:
    return TenderingService(session)


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


# ── Package Endpoints ────────────────────────────────────────────────────────


@router.post("/packages/", response_model=PackageResponse, status_code=201)
async def create_package(
    data: PackageCreate,
    user_id: CurrentUserId,
    service: TenderingService = Depends(_get_service),
) -> PackageResponse:
    """Create a new tender package from a BOQ."""
    package = await service.create_package(data)
    return _package_to_response(package)


@router.get("/packages/", response_model=list[PackageResponse])
async def list_packages(
    user_id: CurrentUserId,
    service: TenderingService = Depends(_get_service),
    project_id: uuid.UUID | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[PackageResponse]:
    """List tender packages with optional project filter."""
    packages, _ = await service.list_packages(
        project_id=project_id, offset=offset, limit=limit
    )
    return [_package_to_response(p) for p in packages]


@router.get("/packages/{package_id}", response_model=PackageWithBidsResponse)
async def get_package(
    package_id: uuid.UUID,
    user_id: CurrentUserId,
    service: TenderingService = Depends(_get_service),
) -> PackageWithBidsResponse:
    """Get a tender package with all bids."""
    package = await service.get_package(package_id)
    return _package_with_bids(package)


@router.patch("/packages/{package_id}", response_model=PackageResponse)
async def update_package(
    package_id: uuid.UUID,
    data: PackageUpdate,
    user_id: CurrentUserId,
    service: TenderingService = Depends(_get_service),
) -> PackageResponse:
    """Update a tender package status or fields."""
    package = await service.update_package(package_id, data)
    return _package_to_response(package)


# ── Bid Endpoints ────────────────────────────────────────────────────────────


@router.post(
    "/packages/{package_id}/bids", response_model=BidResponse, status_code=201
)
async def create_bid(
    package_id: uuid.UUID,
    data: BidCreate,
    user_id: CurrentUserId,
    service: TenderingService = Depends(_get_service),
) -> BidResponse:
    """Add a bid to a tender package."""
    bid = await service.create_bid(package_id, data)
    return _bid_to_response(bid)


@router.get("/packages/{package_id}/bids", response_model=list[BidResponse])
async def list_bids(
    package_id: uuid.UUID,
    user_id: CurrentUserId,
    service: TenderingService = Depends(_get_service),
) -> list[BidResponse]:
    """List all bids for a tender package."""
    bids = await service.list_bids(package_id)
    return [_bid_to_response(b) for b in bids]


@router.patch("/bids/{bid_id}", response_model=BidResponse)
async def update_bid(
    bid_id: uuid.UUID,
    data: BidUpdate,
    user_id: CurrentUserId,
    service: TenderingService = Depends(_get_service),
) -> BidResponse:
    """Update a bid."""
    bid = await service.update_bid(bid_id, data)
    return _bid_to_response(bid)


# ── Comparison Endpoint ──────────────────────────────────────────────────────


@router.get(
    "/packages/{package_id}/comparison",
    response_model=BidComparisonResponse,
)
async def compare_bids(
    package_id: uuid.UUID,
    user_id: CurrentUserId,
    service: TenderingService = Depends(_get_service),
) -> BidComparisonResponse:
    """Compare all bids for a package side-by-side."""
    return await service.compare_bids(package_id)
