"""BOQ API routes.

Endpoints:
    POST   /boqs/                              — Create a new BOQ
    GET    /boqs/?project_id=xxx               — List BOQs for a project
    GET    /boqs/templates                     — List available BOQ templates
    POST   /boqs/from-template                 — Create a BOQ from a template
    GET    /boqs/{boq_id}                      — Get BOQ with all positions
    PATCH  /boqs/{boq_id}                      — Update BOQ metadata
    DELETE /boqs/{boq_id}                      — Delete BOQ and all positions
    GET    /boqs/{boq_id}/structured           — Full BOQ with sections + markups
    GET    /boqs/{boq_id}/activity             — Activity log for a BOQ
    POST   /boqs/{boq_id}/positions            — Add a position to a BOQ
    POST   /boqs/{boq_id}/positions/bulk      — Bulk insert multiple positions
    PATCH  /positions/{position_id}            — Update a position
    DELETE /positions/{position_id}            — Delete a position
    POST   /boqs/{boq_id}/positions/reorder   — Reorder positions via drag-and-drop
    POST   /boqs/{boq_id}/sections             — Create a section header
    POST   /boqs/{boq_id}/markups              — Add a markup line
    PATCH  /boqs/{boq_id}/markups/{markup_id}  — Update a markup
    DELETE /boqs/{boq_id}/markups/{markup_id}  — Delete a markup
    POST   /boqs/{boq_id}/markups/apply-defaults — Apply regional default markups
    POST   /boqs/{boq_id}/duplicate            — Duplicate a BOQ with all data
    POST   /positions/{position_id}/duplicate  — Duplicate a single position
    POST   /boqs/{boq_id}/recalculate-rates    — Recalculate unit_rates from resources
    POST   /boqs/{boq_id}/validate             — Validate a BOQ against rule sets
    GET    /boqs/{boq_id}/export/csv           — Export BOQ as CSV
    GET    /boqs/{boq_id}/export/excel         — Export BOQ as Excel (xlsx)
    GET    /boqs/{boq_id}/export/pdf           — Export BOQ as PDF report
    GET    /boqs/{boq_id}/export/gaeb          — Export BOQ as GAEB XML 3.3 (X83)
    POST   /boqs/{boq_id}/import/excel         — Import positions from Excel/CSV
    POST   /boqs/{boq_id}/import/smart         — Smart import: any file via AI (incl. CAD/BIM)
    GET    /boqs/{boq_id}/resource-summary    — Aggregated resource summary across positions
    GET    /boqs/{boq_id}/cost-breakdown     — Cost breakdown by resource category
    GET    /boqs/{boq_id}/sensitivity       — Sensitivity analysis (tornado chart)
    GET    /boqs/{boq_id}/cost-risk        — Monte Carlo cost risk simulation
    GET    /projects/{project_id}/activity     — Activity log for a project
    POST   /boqs/classify                    — AI: suggest classification codes
    POST   /boqs/suggest-rate                — AI: suggest market rate
    POST   /boqs/{boq_id}/check-anomalies   — AI: detect pricing anomalies
"""

import csv
import io
import logging
import random
import tempfile
import uuid
from pathlib import Path
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, UploadFile, File, status
from fastapi.responses import StreamingResponse

from app.dependencies import CurrentUserId, CurrentUserPayload, RequirePermission, SessionDep
from app.modules.boq.schemas import (
    AIChatRequest,
    AIChatResponse,
    ActivityLogList,
    AnomalyCheckResponse,
    BOQCreate,
    BOQFromTemplateRequest,
    BOQListItem,
    BOQResponse,
    BOQUpdate,
    BOQWithPositions,
    BOQWithSections,
    CheckScopeRequest,
    CheckScopeResponse,
    ClassificationSuggestion,
    ClassifiedElement,
    ClassifyElementsRequest,
    ClassifyElementsResponse,
    ClassifyRequest,
    ClassifyResponse,
    CostItemSearchRequest,
    CostItemSearchResponse,
    CostItemSearchResult,
    CO2MaterialBreakdown,
    CostBreakdownResponse,
    CostRiskDriver,
    CostRiskHistogramBin,
    CostRiskPercentiles,
    CostRiskResponse,
    EnhanceDescriptionRequest,
    EnhanceDescriptionResponse,
    EscalateRateRequest,
    EscalateRateResponse,
    EscalationFactors,
    MarkupCreate,
    MarkupResponse,
    MarkupUpdate,
    PositionCreate,
    PositionResponse,
    PositionUpdate,
    PrerequisiteItem,
    PricingAnomaly,
    RateMatch,
    ResourceSummaryItem,
    ResourceSummaryResponse,
    ResourceTypeSummary,
    ScopeMissingItem,
    SectionCreate,
    SensitivityItem,
    SensitivityResponse,
    SnapshotCreate,
    SnapshotDetail,
    SnapshotResponse,
    SuggestPrerequisitesRequest,
    SuggestPrerequisitesResponse,
    SuggestRateRequest,
    SuggestRateResponse,
    SustainabilityResponse,
    CO2EnrichResponse,
    CO2AssignRequest,
    PositionCO2Detail,
    EstimateClassificationResponse,
    TemplateInfo,
)
from app.modules.boq.service import BOQService
from app.modules.costs.repository import CostItemRepository

router = APIRouter()
_log = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> BOQService:
    return BOQService(session)


async def _verify_boq_owner(
    session: SessionDep,
    boq_id: uuid.UUID,
    user_id: str,
    payload: dict | None = None,
) -> None:
    """Load a BOQ, then its project, and verify ownership.

    Admins bypass the check. Raises 403 if the user is not the project owner.
    """
    if payload and payload.get("role") == "admin":
        return
    from app.modules.boq.repository import BOQRepository
    from app.modules.projects.repository import ProjectRepository

    boq_repo = BOQRepository(session)
    boq = await boq_repo.get_by_id(boq_id)
    if boq is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BOQ not found")
    project_repo = ProjectRepository(session)
    project = await project_repo.get_by_id(boq.project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if str(project.owner_id) != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this BOQ",
        )


async def _verify_project_owner_for_boq(
    session: SessionDep,
    project_id: uuid.UUID,
    user_id: str,
    payload: dict | None = None,
) -> None:
    """Verify the current user owns the given project. Admins bypass."""
    if payload and payload.get("role") == "admin":
        return
    from app.modules.projects.repository import ProjectRepository

    project_repo = ProjectRepository(session)
    project = await project_repo.get_by_id(project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if str(project.owner_id) != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this project",
        )


async def _log_activity(
    service: BOQService,
    *,
    user_id: uuid.UUID,
    action: str,
    target_type: str,
    description: str,
    project_id: uuid.UUID | None = None,
    boq_id: uuid.UUID | None = None,
    target_id: uuid.UUID | None = None,
    changes: dict | None = None,
) -> None:
    """Fire-and-forget activity logging — never fails the request."""
    try:
        # Resolve project_id from boq if not provided
        if project_id is None and boq_id is not None:
            try:
                boq = await service.get_boq(boq_id)
                project_id = boq.project_id
            except Exception:
                pass
        await service.log_activity(
            user_id=user_id,
            action=action,
            target_type=target_type,
            description=description,
            project_id=project_id,
            boq_id=boq_id,
            target_id=target_id,
            changes=changes,
        )
    except Exception:
        _log.debug("Activity log write failed (non-critical)", exc_info=True)


def _position_to_response(position: object) -> PositionResponse:
    """Build a PositionResponse from a Position ORM object."""
    return PositionResponse(
        id=position.id,  # type: ignore[attr-defined]
        boq_id=position.boq_id,  # type: ignore[attr-defined]
        parent_id=position.parent_id,  # type: ignore[attr-defined]
        ordinal=position.ordinal,  # type: ignore[attr-defined]
        description=position.description,  # type: ignore[attr-defined]
        unit=position.unit,  # type: ignore[attr-defined]
        quantity=float(position.quantity),  # type: ignore[attr-defined]
        unit_rate=float(position.unit_rate),  # type: ignore[attr-defined]
        total=float(position.total),  # type: ignore[attr-defined]
        classification=position.classification,  # type: ignore[attr-defined]
        source=position.source,  # type: ignore[attr-defined]
        confidence=(
            float(position.confidence) if position.confidence else None  # type: ignore[attr-defined]
        ),
        cad_element_ids=position.cad_element_ids,  # type: ignore[attr-defined]
        validation_status=position.validation_status,  # type: ignore[attr-defined]
        metadata=position.metadata_,  # type: ignore[attr-defined]
        sort_order=position.sort_order,  # type: ignore[attr-defined]
        created_at=position.created_at,  # type: ignore[attr-defined]
        updated_at=position.updated_at,  # type: ignore[attr-defined]
    )


def _markup_to_response(markup: object) -> MarkupResponse:
    """Build a MarkupResponse from a BOQMarkup ORM object."""
    return MarkupResponse(
        id=markup.id,  # type: ignore[attr-defined]
        boq_id=markup.boq_id,  # type: ignore[attr-defined]
        name=markup.name,  # type: ignore[attr-defined]
        markup_type=markup.markup_type,  # type: ignore[attr-defined]
        category=markup.category,  # type: ignore[attr-defined]
        percentage=float(markup.percentage),  # type: ignore[attr-defined]
        fixed_amount=float(markup.fixed_amount),  # type: ignore[attr-defined]
        apply_to=markup.apply_to,  # type: ignore[attr-defined]
        sort_order=markup.sort_order,  # type: ignore[attr-defined]
        is_active=markup.is_active,  # type: ignore[attr-defined]
        metadata_=markup.metadata_,  # type: ignore[attr-defined]
        created_at=markup.created_at,  # type: ignore[attr-defined]
        updated_at=markup.updated_at,  # type: ignore[attr-defined]
    )


# ── BOQ CRUD ──────────────────────────────────────────────────────────────────


@router.post(
    "/boqs/",
    response_model=BOQResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("boq.create"))],
)
async def create_boq(
    data: BOQCreate,
    _user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: BOQService = Depends(_get_service),
) -> BOQResponse:
    """Create a new Bill of Quantities."""
    await _verify_project_owner_for_boq(session, data.project_id, _user_id, payload)
    boq = await service.create_boq(data)
    await _log_activity(
        service,
        user_id=_user_id,
        action="boq_created",
        target_type="boq",
        description=f"Created BOQ '{boq.name}'",
        project_id=data.project_id,
        boq_id=boq.id,
        target_id=boq.id,
    )
    return BOQResponse.model_validate(boq)


@router.get(
    "/boqs/",
    response_model=list[BOQListItem],
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def list_boqs(
    _user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    project_id: uuid.UUID = Query(..., description="Filter BOQs by project"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    service: BOQService = Depends(_get_service),
) -> list[BOQListItem]:
    """List all BOQs for a given project with computed grand totals."""
    await _verify_project_owner_for_boq(session, project_id, _user_id, payload)
    boqs, _ = await service.list_boqs_for_project(
        project_id, offset=offset, limit=limit
    )
    # Compute grand totals + position counts via aggregate queries
    boq_ids = [b.id for b in boqs]
    totals = await service.boq_repo.grand_totals_for_boqs(boq_ids)

    # Position counts per BOQ
    from sqlalchemy import select, func
    from app.modules.boq.models import Position
    pos_counts: dict[uuid.UUID, int] = {}
    if boq_ids:
        rows = (
            await session.execute(
                select(Position.boq_id, func.count())
                .where(Position.boq_id.in_(boq_ids))
                .where(Position.unit != "")  # Exclude section headers
                .group_by(Position.boq_id)
            )
        ).all()
        for bid, cnt in rows:
            pos_counts[bid] = cnt

    results: list[BOQListItem] = []
    for b in boqs:
        item = BOQListItem(
            id=b.id,
            project_id=b.project_id,
            name=b.name,
            description=b.description,
            status=b.status,
            metadata=b.metadata_,
            created_at=b.created_at,
            updated_at=b.updated_at,
            grand_total=totals.get(b.id, 0.0),
            position_count=pos_counts.get(b.id, 0),
        )
        results.append(item)
    return results


# ── Templates ────────────────────────────────────────────────────────────────


@router.get(
    "/boqs/templates",
    response_model=list[TemplateInfo],
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def list_templates(
    service: BOQService = Depends(_get_service),
) -> list[TemplateInfo]:
    """List all available BOQ templates.

    Returns summary information for each built-in template: name, description,
    icon, section count, and total position count.

    Templates cover common building types:
    - **residential** — Multi-family apartments, 3-5 floors
    - **office** — Commercial office, 4-8 floors
    - **warehouse** — Logistics warehouse, single-story
    - **school** — Primary/secondary school, 2-3 floors
    - **hospital** — General hospital or clinic
    - **hotel** — 3-5 star hotel with conference
    - **retail** — Shopping mall, 1-3 floors
    - **infrastructure** — Bridge / overpass
    """
    return service.list_templates()


@router.post(
    "/boqs/from-template",
    response_model=BOQResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("boq.create"))],
)
async def create_boq_from_template(
    data: BOQFromTemplateRequest,
    _user_id: CurrentUserId,
    service: BOQService = Depends(_get_service),
) -> BOQResponse:
    """Create a complete BOQ from a built-in template.

    Provide the template ID, gross floor area (m2), and optionally a custom
    name.  The endpoint creates:
    - A new BOQ
    - Section headers for each trade group
    - All positions with quantities derived from ``area_m2 * qty_factor``

    Use ``GET /boqs/templates`` to discover available template IDs.
    """
    boq = await service.create_boq_from_template(data)
    return BOQResponse.model_validate(boq)


# ── AI-powered Classification ─────────────────────────────────────────────
# NOTE: These POST routes with literal paths (/boqs/classify, /boqs/suggest-rate)
# MUST be defined BEFORE GET /boqs/{boq_id}, otherwise FastAPI matches "classify"
# and "suggest-rate" as {boq_id} path parameters and returns 405 Method Not Allowed.


@router.post(
    "/boqs/classify",
    response_model=ClassifyResponse,
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def classify_position(
    data: ClassifyRequest,
    service: BOQService = Depends(_get_service),
) -> ClassifyResponse:
    """Suggest classification codes for a BOQ position description.

    Uses vector similarity search against the cost database to find items
    with similar descriptions, then aggregates their classification codes
    ranked by frequency weighted by similarity score.

    Returns 3-5 suggestions ordered by confidence (highest first).
    Gracefully returns an empty list if the vector database is unavailable.

    Args:
        data: ClassifyRequest with description, unit, and project_standard.

    Returns:
        ClassifyResponse with a list of ClassificationSuggestion.
    """
    try:
        raw_suggestions = await service.classify_position(
            description=data.description,
            unit=data.unit,
            project_standard=data.project_standard,
        )
    except Exception:
        _log.exception("classify_position failed")
        raw_suggestions = []

    suggestions = [
        ClassificationSuggestion(
            standard=s["standard"],
            code=s["code"],
            label=s["label"],
            confidence=s["confidence"],
        )
        for s in raw_suggestions
    ]

    return ClassifyResponse(suggestions=suggestions)


# ── Deterministic CAD Element Classification ──────────────────────────────


@router.post(
    "/boqs/classify-elements",
    response_model=ClassifyElementsResponse,
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def classify_elements(
    data: ClassifyElementsRequest,
) -> ClassifyElementsResponse:
    """Map CAD/BIM element categories to classification codes.

    Uses deterministic lookup tables to map Revit/IFC category names
    (e.g. ``"Walls"``, ``"Doors"``) to classification codes in the
    requested standard (DIN 276, NRM, or MasterFormat).

    This is a fast, offline operation — no AI or database access required.
    Useful for initial classification of CAD-extracted elements before
    importing them into a BOQ.

    Args:
        data: ClassifyElementsRequest with elements list and standard.

    Returns:
        ClassifyElementsResponse with classified elements and counts.
    """
    from app.modules.cad.classification_mapper import map_category_to_standard

    classified: list[ClassifiedElement] = []
    mapped_count = 0

    for elem in data.elements:
        code = map_category_to_standard(elem.category, data.standard)
        # Merge existing classification with the new mapping
        merged_classification = dict(elem.classification)
        was_mapped = False
        if code:
            merged_classification[data.standard] = code
            was_mapped = True
            mapped_count += 1

        classified.append(
            ClassifiedElement(
                id=elem.id,
                category=elem.category,
                classification=merged_classification,
                mapped=was_mapped,
            )
        )

    total = len(data.elements)
    return ClassifyElementsResponse(
        elements=classified,
        standard=data.standard,
        total=total,
        mapped_count=mapped_count,
        unmapped_count=total - mapped_count,
    )


# ── AI Cost Finder (vector search) ────────────────────────────────────────


@router.post(
    "/boqs/search-cost-items",
    response_model=CostItemSearchResponse,
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def search_cost_items(
    data: CostItemSearchRequest,
    service: BOQService = Depends(_get_service),
) -> CostItemSearchResponse:
    """Search cost items using AI vector similarity.

    Performs semantic search against the cost database using text embeddings.
    Returns ranked results with similarity scores, enriched with full item
    details (components, classification) from the SQL database.

    Filters: unit (exact match), region, min_score threshold.
    Gracefully returns empty results if vector DB is unavailable.
    """
    try:
        result = await service.search_cost_items(
            query=data.query,
            unit=data.unit,
            region=data.region,
            limit=data.limit,
            min_score=data.min_score,
        )
    except Exception:
        _log.exception("search_cost_items failed")
        result = {
            "results": [],
            "total_found": 0,
            "query_embedding_ms": 0,
            "search_ms": 0,
        }

    items = [
        CostItemSearchResult(
            id=r["id"],
            code=r["code"],
            description=r["description"],
            unit=r["unit"],
            rate=r["rate"],
            region=r["region"],
            score=r["score"],
            classification=r.get("classification", {}),
            components=r.get("components", []),
            currency=r.get("currency", "EUR"),
        )
        for r in result.get("results", [])
    ]

    return CostItemSearchResponse(
        results=items,
        total_found=result.get("total_found", 0),
        query_embedding_ms=result.get("query_embedding_ms", 0),
        search_ms=result.get("search_ms", 0),
    )


# ── AI-powered Rate Suggestion ─────────────────────────────────────────────


@router.post(
    "/boqs/suggest-rate",
    response_model=SuggestRateResponse,
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def suggest_rate(
    data: SuggestRateRequest,
    service: BOQService = Depends(_get_service),
) -> SuggestRateResponse:
    """Suggest a market rate for a BOQ position based on its description.

    Uses vector similarity search to find cost items with similar
    descriptions, optionally filtered by unit and region. Computes a
    weighted average rate (weighted by similarity score) and returns
    the individual matches for transparency.

    Gracefully returns zero rate with empty matches if the vector database
    is unavailable.

    Args:
        data: SuggestRateRequest with description, unit, classification, region.

    Returns:
        SuggestRateResponse with suggested_rate, confidence, source, matches.
    """
    try:
        result = await service.suggest_rate(
            description=data.description,
            unit=data.unit,
            classification=data.classification,
            region=data.region,
        )
    except Exception:
        _log.exception("suggest_rate failed")
        result = {
            "suggested_rate": 0.0,
            "confidence": 0.0,
            "source": "vector_search",
            "matches": [],
        }

    matches = [
        RateMatch(
            code=m["code"],
            description=m["description"],
            rate=m["rate"],
            region=m["region"],
            score=m["score"],
        )
        for m in result.get("matches", [])
    ]

    return SuggestRateResponse(
        suggested_rate=result["suggested_rate"],
        confidence=result["confidence"],
        source=result["source"],
        matches=matches,
    )


# ── BOQ Anomaly Detection ─────────────────────────────────────────────────


@router.post(
    "/boqs/{boq_id}/check-anomalies",
    response_model=AnomalyCheckResponse,
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def check_anomalies(
    boq_id: uuid.UUID,
    service: BOQService = Depends(_get_service),
) -> AnomalyCheckResponse:
    """Check all positions in a BOQ for pricing anomalies.

    For each position with a description and unit_rate > 0, performs a
    vector search to find 5-10 similar cost items. Calculates the p25,
    median, and p75 of matched rates and flags positions whose rate
    deviates significantly from the market range:

    - **error**: rate > 3x median (likely a pricing mistake)
    - **warning**: rate > 2x median (review recommended)
    - **warning**: rate < 0.3x median (suspiciously low)

    Gracefully returns an empty anomaly list if the vector database is
    unavailable.

    Args:
        boq_id: Target BOQ identifier.

    Returns:
        AnomalyCheckResponse with anomalies list and positions_checked count.
    """
    try:
        result = await service.check_anomalies(boq_id)
    except HTTPException:
        raise
    except Exception:
        _log.exception("check_anomalies failed for BOQ %s", boq_id)
        result = {"anomalies": [], "positions_checked": 0}

    anomalies = [
        PricingAnomaly(
            position_id=a["position_id"],
            field=a["field"],
            current_value=a["current_value"],
            market_range=a["market_range"],
            severity=a["severity"],
            message=a["message"],
            suggestion=a["suggestion"],
        )
        for a in result.get("anomalies", [])
    ]

    return AnomalyCheckResponse(
        anomalies=anomalies,
        positions_checked=result.get("positions_checked", 0),
    )


# ── LLM-powered AI features ─────────────────────────────────────────────────


@router.post(
    "/boqs/enhance-description",
    response_model=EnhanceDescriptionResponse,
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def enhance_description(
    data: EnhanceDescriptionRequest,
    user_id: CurrentUserId,
    service: BOQService = Depends(_get_service),
) -> EnhanceDescriptionResponse:
    """Enhance a short BOQ position description into a precise technical specification.

    Uses LLM to add material grades, standards references, and technical details.
    Requires an AI API key configured in user settings.
    """
    try:
        result = await service.enhance_description(
            user_id=user_id,
            description=data.description,
            unit=data.unit,
            classification=data.classification,
            locale=data.locale,
        )
    except HTTPException:
        raise
    except Exception:
        _log.exception("enhance_description failed")
        result = {
            "enhanced_description": data.description,
            "specifications": [],
            "standards": [],
            "confidence": 0.0,
            "model_used": "",
            "tokens_used": 0,
        }

    return EnhanceDescriptionResponse(**result)


@router.post(
    "/boqs/suggest-prerequisites",
    response_model=SuggestPrerequisitesResponse,
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def suggest_prerequisites(
    data: SuggestPrerequisitesRequest,
    user_id: CurrentUserId,
    service: BOQService = Depends(_get_service),
) -> SuggestPrerequisitesResponse:
    """Suggest prerequisite and related work items for a BOQ position.

    Analyzes the target position and existing BOQ to identify commonly
    needed companion, prerequisite, and successor work items.
    """
    try:
        result = await service.suggest_prerequisites(
            user_id=user_id,
            description=data.description,
            unit=data.unit,
            classification=data.classification,
            existing_descriptions=data.existing_descriptions,
            locale=data.locale,
        )
    except HTTPException:
        raise
    except Exception:
        _log.exception("suggest_prerequisites failed")
        result = {"suggestions": [], "model_used": "", "tokens_used": 0}

    suggestions = [
        PrerequisiteItem(**s)
        for s in result.get("suggestions", [])
    ]
    return SuggestPrerequisitesResponse(
        suggestions=suggestions,
        model_used=result.get("model_used", ""),
        tokens_used=result.get("tokens_used", 0),
    )


@router.post(
    "/boqs/{boq_id}/check-scope",
    response_model=CheckScopeResponse,
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def check_scope(
    boq_id: uuid.UUID,
    data: CheckScopeRequest,
    user_id: CurrentUserId,
    service: BOQService = Depends(_get_service),
) -> CheckScopeResponse:
    """Analyze BOQ for scope completeness — find missing trades and work packages.

    Sends a summary of all positions to the LLM which identifies gaps:
    missing structural items, MEP, finishes, external works, preliminaries, etc.
    """
    try:
        result = await service.check_scope_completeness(
            user_id=user_id,
            boq_id=boq_id,
            project_type=data.project_type,
            region=data.region,
            currency=data.currency,
            locale=data.locale,
        )
    except HTTPException:
        raise
    except Exception:
        _log.exception("check_scope failed for BOQ %s", boq_id)
        result = {
            "completeness_score": 0.0,
            "missing_items": [],
            "warnings": ["Analysis failed"],
            "summary": "",
            "model_used": "",
            "tokens_used": 0,
        }

    missing = [ScopeMissingItem(**m) for m in result.get("missing_items", [])]
    return CheckScopeResponse(
        completeness_score=result.get("completeness_score", 0.0),
        missing_items=missing,
        warnings=result.get("warnings", []),
        summary=result.get("summary", ""),
        model_used=result.get("model_used", ""),
        tokens_used=result.get("tokens_used", 0),
    )


@router.post(
    "/boqs/escalate-rate",
    response_model=EscalateRateResponse,
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def escalate_rate(
    data: EscalateRateRequest,
    user_id: CurrentUserId,
    service: BOQService = Depends(_get_service),
) -> EscalateRateResponse:
    """Escalate a unit rate from a base year to current prices.

    Uses LLM to estimate inflation factors (material, labor, regional)
    and compute an escalated rate.
    """
    try:
        result = await service.escalate_rate(
            user_id=user_id,
            description=data.description,
            unit=data.unit,
            rate=data.rate,
            currency=data.currency,
            base_year=data.base_year,
            target_year=data.target_year,
            region=data.region,
            locale=data.locale,
        )
    except HTTPException:
        raise
    except Exception:
        _log.exception("escalate_rate failed")
        result = {
            "original_rate": data.rate,
            "escalated_rate": data.rate,
            "escalation_percent": 0.0,
            "factors": {},
            "confidence": "low",
            "reasoning": "Analysis failed",
            "model_used": "",
            "tokens_used": 0,
        }

    factors = result.get("factors", {})
    return EscalateRateResponse(
        original_rate=result["original_rate"],
        escalated_rate=result["escalated_rate"],
        escalation_percent=result["escalation_percent"],
        factors=EscalationFactors(**factors) if isinstance(factors, dict) else EscalationFactors(),
        confidence=result.get("confidence", "low"),
        reasoning=result.get("reasoning", ""),
        model_used=result.get("model_used", ""),
        tokens_used=result.get("tokens_used", 0),
    )


@router.get(
    "/boqs/{boq_id}",
    response_model=BOQWithPositions,
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def get_boq(
    boq_id: uuid.UUID,
    _user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: BOQService = Depends(_get_service),
) -> BOQWithPositions:
    """Get a BOQ with all its positions and grand total."""
    await _verify_boq_owner(session, boq_id, _user_id, payload)
    return await service.get_boq_with_positions(boq_id)


@router.get(
    "/boqs/{boq_id}/structured",
    response_model=BOQWithSections,
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def get_boq_structured(
    boq_id: uuid.UUID,
    service: BOQService = Depends(_get_service),
) -> BOQWithSections:
    """Get a BOQ with hierarchical sections, subtotals, markups, and totals.

    Returns the full structured view that a professional estimator needs:
    - Sections with grouped positions and subtotals
    - Ungrouped positions (no parent section)
    - Direct cost (sum of all item totals)
    - Markup lines with computed amounts
    - Net total (direct cost + markups)
    - Grand total
    """
    return await service.get_boq_structured(boq_id)


@router.get(
    "/boqs/{boq_id}/activity",
    response_model=ActivityLogList,
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def get_boq_activity(
    boq_id: uuid.UUID,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    service: BOQService = Depends(_get_service),
) -> ActivityLogList:
    """Get the activity log for a BOQ (paginated, newest first).

    Returns a chronological audit trail of all mutations: position additions,
    updates, deletions, markup changes, exports, etc.
    """
    return await service.get_activity_for_boq(boq_id, offset=offset, limit=limit)


@router.get(
    "/projects/{project_id}/activity",
    response_model=ActivityLogList,
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def get_project_activity(
    project_id: uuid.UUID,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    service: BOQService = Depends(_get_service),
) -> ActivityLogList:
    """Get the activity log for a project (paginated, newest first).

    Returns all BOQ-related activity across all BOQs in the project.
    """
    return await service.get_activity_for_project(
        project_id, offset=offset, limit=limit
    )


@router.patch(
    "/boqs/{boq_id}",
    response_model=BOQResponse,
    dependencies=[Depends(RequirePermission("boq.update"))],
)
async def update_boq(
    boq_id: uuid.UUID,
    data: BOQUpdate,
    _user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: BOQService = Depends(_get_service),
) -> BOQResponse:
    """Update BOQ metadata (name, description, status)."""
    await _verify_boq_owner(session, boq_id, _user_id, payload)
    boq = await service.update_boq(boq_id, data)
    return BOQResponse.model_validate(boq)


@router.delete(
    "/boqs/{boq_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("boq.delete"))],
)
async def delete_boq(
    boq_id: uuid.UUID,
    _user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: BOQService = Depends(_get_service),
) -> None:
    """Delete a BOQ and all its positions."""
    await _verify_boq_owner(session, boq_id, _user_id, payload)
    await service.delete_boq(boq_id)


# ── Duplicate ────────────────────────────────────────────────────────────────


@router.post(
    "/boqs/{boq_id}/duplicate",
    response_model=BOQResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("boq.create"))],
)
async def duplicate_boq(
    boq_id: uuid.UUID,
    service: BOQService = Depends(_get_service),
) -> BOQResponse:
    """Duplicate an entire BOQ with all its positions and markups.

    Creates a new BOQ named "<original> (Copy)" in the same project.
    All positions (with hierarchy) and markups are deep-copied with new IDs.
    """
    new_boq = await service.duplicate_boq(boq_id)
    return BOQResponse.model_validate(new_boq)


@router.post(
    "/positions/{position_id}/duplicate",
    response_model=PositionResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("boq.update"))],
)
async def duplicate_position(
    position_id: uuid.UUID,
    service: BOQService = Depends(_get_service),
) -> PositionResponse:
    """Duplicate a single position within the same BOQ.

    Creates a copy with ordinal "<original>.1" placed after the original.
    """
    new_position = await service.duplicate_position(position_id)
    return _position_to_response(new_position)


# ── Position CRUD ─────────────────────────────────────────────────────────────


@router.post(
    "/boqs/{boq_id}/positions",
    response_model=PositionResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("boq.update"))],
)
async def add_position(
    boq_id: uuid.UUID,
    data: PositionCreate,
    user_id: CurrentUserId,
    service: BOQService = Depends(_get_service),
) -> PositionResponse:
    """Add a new position to a BOQ.

    The boq_id in the URL takes precedence over the body field.
    """
    # Override body boq_id with URL path parameter
    data.boq_id = boq_id
    position = await service.add_position(data)
    await _log_activity(
        service,
        user_id=user_id,
        action="position_added",
        target_type="position",
        description=f"Added position '{data.description[:60]}'",
        boq_id=boq_id,
        target_id=position.id,
    )
    return _position_to_response(position)


@router.post(
    "/boqs/{boq_id}/positions/bulk",
    response_model=list[PositionResponse],
    status_code=201,
    dependencies=[Depends(RequirePermission("boq.import"))],
)
async def bulk_add_positions(
    boq_id: uuid.UUID,
    payload: dict[str, Any],
    service: BOQService = Depends(_get_service),
) -> list[PositionResponse]:
    """Bulk insert multiple positions into a BOQ.

    Accepts ``{"items": [{"description": ..., "quantity": ..., "unit": ...}, ...]}``
    as sent by the Takeoff page.  Each item is converted into a full
    :class:`PositionCreate` and inserted sequentially.
    """
    items: list[dict[str, Any]] = payload.get("items", [])
    if not items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="'items' list is required and must not be empty",
        )

    # Determine next ordinal base from existing positions
    try:
        boq_data = await service.get_boq_with_positions(boq_id)
        existing_count = len(boq_data.positions) if boq_data.positions else 0
    except HTTPException:
        existing_count = 0

    results: list[PositionResponse] = []
    errors: list[dict[str, Any]] = []
    for idx, item in enumerate(items):
        try:
            ordinal = item.get("ordinal", f"{existing_count + idx + 1:03d}")
            description = str(item.get("description", "")).strip()
            if not description:
                description = f"Position {existing_count + idx + 1}"

            quantity = 0.0
            try:
                quantity = float(item.get("quantity", 0))
            except (ValueError, TypeError):
                quantity = 0.0

            unit_rate = 0.0
            try:
                unit_rate = float(item.get("unit_rate", 0))
            except (ValueError, TypeError):
                unit_rate = 0.0

            pos_data = PositionCreate(
                boq_id=boq_id,
                ordinal=ordinal,
                description=description,
                unit=item.get("unit", "pcs"),
                quantity=quantity,
                unit_rate=unit_rate,
                source=item.get("source", "takeoff"),
                classification=item.get("classification", {}),
                metadata=item.get("metadata", {}),
            )
            position = await service.add_position(pos_data)
            results.append(_position_to_response(position))
        except Exception as exc:
            logger.warning("Bulk import: item %d failed: %s", idx, exc)
            errors.append({"index": idx, "error": str(exc)})

    if not results and errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"All {len(errors)} items failed to import. First error: {errors[0]['error']}",
        )

    return results


@router.patch(
    "/positions/{position_id}",
    response_model=PositionResponse,
    dependencies=[Depends(RequirePermission("boq.update"))],
)
async def update_position(
    position_id: uuid.UUID,
    data: PositionUpdate,
    user_id: CurrentUserId,
    service: BOQService = Depends(_get_service),
) -> PositionResponse:
    """Update a BOQ position. Recalculates total if quantity or unit_rate changed."""
    position = await service.update_position(position_id, data)
    return _position_to_response(position)


@router.delete(
    "/positions/{position_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("boq.delete"))],
)
async def delete_position(
    position_id: uuid.UUID,
    user_id: CurrentUserId,
    service: BOQService = Depends(_get_service),
) -> None:
    """Delete a single position."""
    await _log_activity(
        service,
        user_id=user_id,
        action="position_deleted",
        target_type="position",
        description=f"Deleted position {position_id}",
        target_id=position_id,
    )
    await service.delete_position(position_id)


@router.post(
    "/boqs/{boq_id}/positions/reorder",
    dependencies=[Depends(RequirePermission("boq.update"))],
)
async def reorder_positions(
    boq_id: uuid.UUID,
    data: dict = Body(...),
    user_id: CurrentUserId = None,
    service: BOQService = Depends(_get_service),
) -> dict:
    """Reorder positions within a BOQ.

    Expects ``{"position_ids": ["uuid1", "uuid2", ...]}``.
    The list order determines the new ``sort_order`` for each position.
    """
    raw_ids = data.get("position_ids", [])
    position_ids = [uuid.UUID(pid) if isinstance(pid, str) else pid for pid in raw_ids]
    await service.reorder_positions(boq_id, position_ids)
    await _log_activity(
        service,
        user_id=user_id,
        action="position_updated",
        target_type="boq",
        description=f"Reordered {len(position_ids)} positions",
        boq_id=boq_id,
    )
    return {"ok": True}


# ── Section CRUD ──────────────────────────────────────────────────────────────


@router.post(
    "/boqs/{boq_id}/sections",
    response_model=PositionResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("boq.update"))],
)
async def create_section(
    boq_id: uuid.UUID,
    data: SectionCreate,
    service: BOQService = Depends(_get_service),
) -> PositionResponse:
    """Create a section header row in a BOQ.

    Sections are positions with unit="section", quantity=0, unit_rate=0.
    They serve as grouping headers for estimating line items.
    """
    section = await service.create_section(boq_id, data)
    return _position_to_response(section)


# ── Markup CRUD ───────────────────────────────────────────────────────────────


@router.get(
    "/boqs/{boq_id}/markups",
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def list_markups(
    boq_id: uuid.UUID,
    service: BOQService = Depends(_get_service),
) -> dict:
    """List all markups for a BOQ."""
    markups = await service.list_markups(boq_id)
    return {"markups": [_markup_to_response(m) for m in markups]}


@router.post(
    "/boqs/{boq_id}/markups",
    response_model=MarkupResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("boq.update"))],
)
async def add_markup(
    boq_id: uuid.UUID,
    data: MarkupCreate,
    service: BOQService = Depends(_get_service),
) -> MarkupResponse:
    """Add a markup/overhead line to a BOQ."""
    markup = await service.add_markup(boq_id, data)
    return _markup_to_response(markup)


@router.patch(
    "/boqs/{boq_id}/markups/{markup_id}",
    response_model=MarkupResponse,
    dependencies=[Depends(RequirePermission("boq.update"))],
)
async def update_markup(
    boq_id: uuid.UUID,
    markup_id: uuid.UUID,
    data: MarkupUpdate,
    service: BOQService = Depends(_get_service),
) -> MarkupResponse:
    """Update a markup/overhead line on a BOQ."""
    markup = await service.update_markup(markup_id, data)
    return _markup_to_response(markup)


@router.delete(
    "/boqs/{boq_id}/markups/{markup_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("boq.delete"))],
)
async def delete_markup(
    boq_id: uuid.UUID,
    markup_id: uuid.UUID,
    service: BOQService = Depends(_get_service),
) -> None:
    """Delete a markup/overhead line from a BOQ."""
    await service.delete_markup(markup_id)


@router.post(
    "/boqs/{boq_id}/markups/apply-defaults",
    response_model=list[MarkupResponse],
    dependencies=[Depends(RequirePermission("boq.update"))],
)
async def apply_default_markups(
    boq_id: uuid.UUID,
    region: str = Query(
        default="DEFAULT",
        description="Region code: DACH, UK, US, FR, GULF, IN, AU, JP, BR, NORDIC, RU, CN, KR, DEFAULT",
    ),
    service: BOQService = Depends(_get_service),
) -> list[MarkupResponse]:
    """Apply regional default markups to a BOQ.

    Replaces any existing markups with the standard template for the region.
    Pass region as query parameter: ``?region=DACH``.

    Supported regions: DACH, UK, US, FR, GULF, IN, AU, JP, BR, NORDIC,
    RU, CN, KR, DEFAULT.
    """
    markups = await service.apply_default_markups(boq_id, region)
    return [_markup_to_response(m) for m in markups]


# ── Snapshots (Version History) ───────────────────────────────────────────────


@router.get(
    "/boqs/{boq_id}/snapshots",
    response_model=list[SnapshotResponse],
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def list_snapshots(
    boq_id: uuid.UUID,
    service: BOQService = Depends(_get_service),
) -> list[SnapshotResponse]:
    """List all snapshots for a BOQ, newest first."""
    snapshots = await service.list_snapshots(boq_id)
    return [
        SnapshotResponse(
            id=s.id,
            boq_id=s.boq_id,
            name=s.name,
            created_at=s.created_at,
            created_by=s.created_by,
        )
        for s in snapshots
    ]


@router.post(
    "/boqs/{boq_id}/snapshots",
    response_model=SnapshotResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("boq.update"))],
)
async def create_snapshot(
    boq_id: uuid.UUID,
    data: SnapshotCreate,
    user_id: CurrentUserId = None,
    service: BOQService = Depends(_get_service),
) -> SnapshotResponse:
    """Create a point-in-time snapshot of the current BOQ state."""
    snap = await service.create_snapshot(boq_id, name=data.name, user_id=user_id)
    return SnapshotResponse(
        id=snap.id,
        boq_id=snap.boq_id,
        name=snap.name,
        created_at=snap.created_at,
        created_by=snap.created_by,
    )


@router.post(
    "/boqs/{boq_id}/restore/{snapshot_id}",
    response_model=BOQWithPositions,
    dependencies=[Depends(RequirePermission("boq.update"))],
)
async def restore_snapshot(
    boq_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    service: BOQService = Depends(_get_service),
) -> BOQWithPositions:
    """Restore a BOQ to a previous snapshot state."""
    boq = await service.restore_snapshot(boq_id, snapshot_id)
    return boq


# ── Validation ────────────────────────────────────────────────────────────────


def _build_rule_sets(
    project_rule_sets: list[str],
    classification_standard: str,
    region: str,
) -> list[str]:
    """Determine which validation rule sets to apply based on project config.

    Always includes the project's configured rule sets (default: ["boq_quality"]).
    Adds standard-specific rules based on classification_standard and region.

    Args:
        project_rule_sets: Explicit rule sets from project config.
        classification_standard: e.g. "din276", "nrm", "masterformat".
        region: e.g. "DACH", "UK", "US".

    Returns:
        Deduplicated list of rule set names.
    """
    rule_sets = list(project_rule_sets)

    # Map classification standard → rule set name
    STANDARD_RULES: dict[str, str] = {
        "din276": "din276",
        "nrm": "nrm",
        "masterformat": "masterformat",
        "sinapi": "sinapi",
        "gesn": "gesn",
        "dpgf": "dpgf",
        "onorm": "onorm",
        "gbt50500": "gbt50500",
        "cpwd": "cpwd",
        "birimfiyat": "birimfiyat",
        "sekisan": "sekisan",
    }
    std_rule = STANDARD_RULES.get(classification_standard)
    if std_rule and std_rule not in rule_sets:
        rule_sets.append(std_rule)

    # Map region → additional rule sets
    REGION_RULES: dict[str, list[str]] = {
        "DACH": ["gaeb", "din276"],
        "DE": ["gaeb", "din276"],
        "AT": ["gaeb", "onorm"],
        "CH": ["gaeb", "din276"],
        "UK": ["nrm"],
        "GB": ["nrm"],
        "US": ["masterformat"],
        "CA": ["masterformat"],
        "FR": ["dpgf"],
        "BR": ["sinapi"],
        "RU": ["gesn"],
        "CN": ["gbt50500"],
        "IN": ["cpwd"],
        "TR": ["birimfiyat"],
        "JP": ["sekisan"],
        "UAE": ["nrm"],
        "GCC": ["nrm"],
    }
    for rs in REGION_RULES.get(region.upper(), []):
        if rs not in rule_sets:
            rule_sets.append(rs)

    return rule_sets


@router.post(
    "/boqs/{boq_id}/recalculate-rates",
    dependencies=[Depends(RequirePermission("boq.update"))],
)
async def recalculate_rates(
    boq_id: uuid.UUID,
    service: BOQService = Depends(_get_service),
) -> dict[str, Any]:
    """Recalculate position unit_rates from their resource breakdowns.

    Iterates over all positions in the BOQ and, for those with resource
    entries in metadata, recomputes unit_rate as the sum of resource costs.
    Returns a summary with updated/skipped/total counts.
    """
    return await service.recalculate_rates(boq_id)


@router.post(
    "/boqs/{boq_id}/validate",
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def validate_boq(
    boq_id: uuid.UUID,
    session: SessionDep,
    service: BOQService = Depends(_get_service),
) -> dict[str, Any]:
    """Validate a BOQ against configured rule sets.

    Loads the BOQ with all positions, determines which validation rule sets
    to apply based on the project configuration, runs the validation engine,
    and returns a full validation report.
    """
    from app.core.validation.engine import validation_engine
    from app.modules.projects.repository import ProjectRepository

    # Load BOQ with positions
    boq_data = await service.get_boq_with_positions(boq_id)

    # Load project to get classification config
    project_repo = ProjectRepository(session)
    project = await project_repo.get_by_id(boq_data.project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found for this BOQ",
        )

    # Convert positions to the format expected by validation rules
    positions_data = [
        {
            "id": str(pos.id),
            "ordinal": pos.ordinal,
            "description": pos.description,
            "quantity": pos.quantity,
            "unit_rate": pos.unit_rate,
            "classification": pos.classification,
        }
        for pos in boq_data.positions
    ]

    # Determine rule sets from project config
    rule_sets = _build_rule_sets(
        project_rule_sets=project.validation_rule_sets or ["boq_quality"],
        classification_standard=project.classification_standard or "din276",
        region=project.region or "DACH",
    )

    # Run validation
    report = await validation_engine.validate(
        data={"positions": positions_data},
        rule_sets=rule_sets,
        target_type="boq",
        target_id=str(boq_id),
        project_id=str(boq_data.project_id),
        region=project.region,
        standard=project.classification_standard,
    )

    # Build response: summary + full results
    summary = report.summary()
    summary["results"] = [
        {
            "rule_id": r.rule_id,
            "rule_name": r.rule_name,
            "severity": r.severity.value,
            "passed": r.passed,
            "message": r.message,
            "element_ref": r.element_ref,
            "suggestion": r.suggestion,
        }
        for r in report.results
    ]

    return summary


# ── AI Chat ──────────────────────────────────────────────────────────────────


BOQ_CHAT_SYSTEM_PROMPT = """\
You are a professional construction cost estimator integrated into a BOQ editor. \
You generate accurate, detailed BOQ positions with realistic market-rate pricing. \
Always return valid JSON arrays. Never include explanatory text outside the JSON structure.\
"""

BOQ_CHAT_USER_PROMPT = """\
You are a cost estimator assistant. The user is working on a BOQ for {project_name}.
Current BOQ has {existing_positions_count} positions.
Classification standard: {standard}.
User's language/locale: {locale}

User request: {message}

Generate additional BOQ positions as a JSON array:
[
  {{"ordinal": "...", "description": "...", "unit": "...", "quantity": N, "unit_rate": N}}
]

Rules:
- Be specific and use realistic prices in {currency}
- Each item must have: ordinal, description, unit, quantity, unit_rate
- Use realistic market-rate unit prices
- ALL description values MUST be in the user's language ({locale})
- Return ONLY the JSON array, no other text
"""


@router.post(
    "/boqs/{boq_id}/ai-chat",
    response_model=AIChatResponse,
    dependencies=[Depends(RequirePermission("boq.update"))],
)
async def ai_chat_boq(
    boq_id: uuid.UUID,
    data: AIChatRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    service: BOQService = Depends(_get_service),
) -> AIChatResponse:
    """Chat with AI to generate additional BOQ positions.

    Sends the user's message along with BOQ context to the AI and returns
    suggested positions that can be added to the BOQ.

    Requires the user to have an AI API key configured in their settings.
    """
    from app.modules.ai.ai_client import call_ai, extract_json, resolve_provider_and_key
    from app.modules.ai.repository import AISettingsRepository

    # Verify BOQ exists
    await service.get_boq(boq_id)

    # Resolve AI provider from user settings
    uid = uuid.UUID(user_id)
    settings_repo = AISettingsRepository(session)
    settings = await settings_repo.get_by_user_id(uid)

    try:
        provider, api_key = resolve_provider_and_key(settings)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    # Build prompt
    ctx = data.context
    locale = getattr(data, "locale", "en") or "en"
    prompt = BOQ_CHAT_USER_PROMPT.format(
        project_name=ctx.project_name or "Unnamed project",
        existing_positions_count=ctx.existing_positions_count,
        standard=ctx.standard or "din276",
        currency=ctx.currency or "EUR",
        locale=locale,
        message=data.message,
    )

    # Call AI
    from app.modules.boq.ai_prompts import with_locale

    try:
        raw_response, _tokens = await call_ai(
            provider=provider,
            api_key=api_key,
            system=with_locale(BOQ_CHAT_SYSTEM_PROMPT, locale),
            prompt=prompt,
            max_tokens=4096,
        )
    except Exception as exc:
        logger.exception("AI chat failed for BOQ %s: %s", boq_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI request failed: {exc}",
        ) from exc

    # Parse response
    parsed = extract_json(raw_response)
    if not isinstance(parsed, list):
        return AIChatResponse(
            items=[],
            message="AI did not return valid items. Please try rephrasing your request.",
        )

    # Build response items
    from app.modules.boq.schemas import AIChatItem

    items: list[AIChatItem] = []
    for raw_item in parsed:
        if not isinstance(raw_item, dict):
            continue

        description = str(raw_item.get("description", "")).strip()
        if len(description) < 3:
            continue

        try:
            quantity = float(raw_item.get("quantity", 0))
            unit_rate = float(raw_item.get("unit_rate", 0))
        except (ValueError, TypeError):
            continue

        if quantity <= 0:
            continue

        total = round(quantity * unit_rate, 2)
        items.append(
            AIChatItem(
                ordinal=str(raw_item.get("ordinal", "")),
                description=description,
                unit=str(raw_item.get("unit", "m2")),
                quantity=round(quantity, 2),
                unit_rate=round(unit_rate, 2),
                total=total,
            )
        )

    grand_total = sum(item.total for item in items)
    summary = (
        f"Generated {len(items)} position{'s' if len(items) != 1 else ''} "
        f"totalling {grand_total:,.2f} {ctx.currency or 'EUR'}."
    )

    return AIChatResponse(items=items, message=summary)


# ── Export (CSV / Excel) ──────────────────────────────────────────────────────


def _get_classification_code(classification: dict[str, Any]) -> str:
    """Extract the most relevant classification code for display.

    Checks din276, nrm, masterformat in order.
    """
    if not classification:
        return ""
    for key in ("din276", "nrm", "masterformat"):
        val = classification.get(key, "")
        if val:
            return str(val)
    # Fall back to the first available key
    for val in classification.values():
        if val:
            return str(val)
    return ""


@router.get(
    "/boqs/{boq_id}/export/csv",
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def export_boq_csv(
    boq_id: uuid.UUID,
    service: BOQService = Depends(_get_service),
) -> StreamingResponse:
    """Export BOQ positions as a CSV file."""
    boq_data = await service.get_boq_with_positions(boq_id)

    output = io.StringIO()
    writer = csv.writer(output)

    # Header row
    writer.writerow([
        "Pos.",
        "Description",
        "Unit",
        "Quantity",
        "Unit Rate",
        "Total",
        "Classification",
    ])

    # Position rows
    for pos in boq_data.positions:
        writer.writerow([
            pos.ordinal,
            pos.description,
            pos.unit,
            f"{pos.quantity:.2f}",
            f"{pos.unit_rate:.2f}",
            f"{pos.total:.2f}",
            _get_classification_code(pos.classification),
        ])

    # Grand total row
    writer.writerow([
        "",
        "Grand Total",
        "",
        "",
        "",
        f"{boq_data.grand_total:.2f}",
        "",
    ])

    content = output.getvalue()
    output.close()

    safe_name = boq_data.name.encode("ascii", errors="replace").decode("ascii").replace('"', "'")
    filename = f"{safe_name}.csv"

    return StreamingResponse(
        iter([content]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.get(
    "/boqs/{boq_id}/export/excel",
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def export_boq_excel(
    boq_id: uuid.UUID,
    service: BOQService = Depends(_get_service),
) -> StreamingResponse:
    """Export BOQ positions as an Excel (xlsx) file with formatting."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, numbers
    from openpyxl.utils import get_column_letter

    boq_data = await service.get_boq_with_positions(boq_id)

    wb = Workbook()
    ws = wb.active
    ws.title = "BOQ"

    # ── Header row ────────────────────────────────────────────────────────
    headers = [
        "Pos.",
        "Description",
        "Unit",
        "Quantity",
        "Unit Rate",
        "Total",
        "Classification",
    ]
    bold_font = Font(bold=True)

    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = bold_font

    # ── Position rows ─────────────────────────────────────────────────────
    number_format = numbers.FORMAT_NUMBER_COMMA_SEPARATED1  # #,##0.00

    for row_idx, pos in enumerate(boq_data.positions, start=2):
        ws.cell(row=row_idx, column=1, value=pos.ordinal)
        ws.cell(row=row_idx, column=2, value=pos.description)
        ws.cell(row=row_idx, column=3, value=pos.unit)

        qty_cell = ws.cell(row=row_idx, column=4, value=pos.quantity)
        qty_cell.number_format = number_format

        rate_cell = ws.cell(row=row_idx, column=5, value=pos.unit_rate)
        rate_cell.number_format = number_format

        total_cell = ws.cell(row=row_idx, column=6, value=pos.total)
        total_cell.number_format = number_format

        ws.cell(
            row=row_idx,
            column=7,
            value=_get_classification_code(pos.classification),
        )

    # ── Grand total row ───────────────────────────────────────────────────
    total_row = len(boq_data.positions) + 2
    total_label = ws.cell(row=total_row, column=2, value="Grand Total")
    total_label.font = bold_font

    grand_total_cell = ws.cell(row=total_row, column=6, value=boq_data.grand_total)
    grand_total_cell.font = bold_font
    grand_total_cell.number_format = number_format

    # ── Auto-width columns ────────────────────────────────────────────────
    for col_idx in range(1, len(headers) + 1):
        max_length = len(str(headers[col_idx - 1]))
        for row in ws.iter_rows(
            min_row=2,
            max_row=total_row,
            min_col=col_idx,
            max_col=col_idx,
        ):
            for cell in row:
                val = cell.value
                if val is not None:
                    max_length = max(max_length, len(str(val)))
        # Add a small padding; cap at 60 to avoid excessively wide columns
        adjusted = min(max_length + 3, 60)
        ws.column_dimensions[get_column_letter(col_idx)].width = adjusted

    # Align numeric columns to the right
    for row in ws.iter_rows(min_row=2, max_row=total_row, min_col=4, max_col=6):
        for cell in row:
            cell.alignment = Alignment(horizontal="right")

    # ── Write to bytes buffer and return ──────────────────────────────────
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    safe_name = boq_data.name.encode("ascii", errors="replace").decode("ascii").replace('"', "'")
    filename = f"{safe_name}.xlsx"

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.get(
    "/boqs/{boq_id}/export/pdf",
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def export_boq_pdf(
    boq_id: uuid.UUID,
    session: SessionDep,
    service: BOQService = Depends(_get_service),
) -> StreamingResponse:
    """Export BOQ as a professional PDF cost estimate report.

    Generates a multi-page PDF document with:
    - Cover page: project name, BOQ title, cost summary, date, status
    - BOQ table pages: sections, positions, subtotals, markups, totals
    - Running headers/footers with page numbering

    For large BOQs (> 500 positions), a simplified summary report is generated
    to avoid memory issues and connection resets on Windows.
    """
    from app.modules.boq.pdf_export import (
        LARGE_BOQ_THRESHOLD,
        count_boq_positions,
        generate_boq_pdf,
        generate_boq_pdf_simple,
    )
    from app.modules.projects.repository import ProjectRepository
    from app.modules.users.models import User

    boq_data = await service.get_boq_structured(boq_id)

    # Load project for cover page info
    project_repo = ProjectRepository(session)
    project = await project_repo.get_by_id(boq_data.project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found for this BOQ",
        )

    # Try to get the owner name for "Prepared by"
    prepared_by = ""
    owner = await session.get(User, project.owner_id)
    if owner is not None:
        prepared_by = owner.full_name or owner.email

    try:
        position_count = count_boq_positions(boq_data)

        if position_count > LARGE_BOQ_THRESHOLD:
            _log.info(
                "BOQ %s has %d positions (> %d) — generating simplified PDF",
                boq_id,
                position_count,
                LARGE_BOQ_THRESHOLD,
            )
            pdf_bytes = generate_boq_pdf_simple(
                boq_data=boq_data,
                project_name=project.name,
                currency=project.currency or "EUR",
                prepared_by=prepared_by,
            )
        else:
            pdf_bytes = generate_boq_pdf(
                boq_data=boq_data,
                project_name=project.name,
                currency=project.currency or "EUR",
                prepared_by=prepared_by,
            )
    except Exception:
        _log.exception("PDF generation failed for BOQ %s", boq_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="PDF generation failed. The BOQ may be too large or contain "
            "invalid data. Please try exporting as Excel or CSV instead.",
        )

    safe_name = (
        boq_data.name.encode("ascii", errors="replace")
        .decode("ascii")
        .replace('"', "'")
    )
    filename = f"{safe_name}.pdf"

    def _iter_pdf_chunks() -> Iterator[bytes]:
        """Yield PDF bytes in chunks to enable true streaming."""
        chunk_size = 64 * 1024  # 64 KB chunks
        offset = 0
        while offset < len(pdf_bytes):
            yield pdf_bytes[offset : offset + chunk_size]
            offset += chunk_size

    return StreamingResponse(
        _iter_pdf_chunks(),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(pdf_bytes)),
        },
    )


@router.get(
    "/boqs/{boq_id}/export/gaeb",
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def export_boq_gaeb(
    boq_id: uuid.UUID,
    session: SessionDep,
    service: BOQService = Depends(_get_service),
) -> StreamingResponse:
    """Export BOQ as a GAEB XML 3.3 file (DP 83 — Angebotsabgabe / Bid Submission).

    Generates a valid GAEB DA XML document containing:
    - GAEBInfo header with version and program identification
    - Award block with DP 83 (bid submission phase)
    - BoQ with sections mapped to BoQCtgy elements
    - Positions mapped to Item elements with quantities, units, rates, and totals
    - Grand total in the trailing BoQInfo block
    """
    import xml.etree.ElementTree as ET
    from datetime import date

    from app.modules.projects.repository import ProjectRepository

    boq_data = await service.get_boq_structured(boq_id)

    # Load project for label text
    project_repo = ProjectRepository(session)
    project = await project_repo.get_by_id(boq_data.project_id)
    project_name = project.name if project else "OpenEstimate Project"

    today = date.today().isoformat()

    # ── Build GAEB XML tree ────────────────────────────────────────────────
    ns = "http://www.gaeb.de/GAEB_DA_XML/200407"
    ET.register_namespace("", ns)

    gaeb = ET.Element("GAEB", xmlns=ns)

    # GAEBInfo
    gaeb_info = ET.SubElement(gaeb, "GAEBInfo")
    ET.SubElement(gaeb_info, "Version").text = "3.3"
    ET.SubElement(gaeb_info, "VersDate").text = "2024-01"
    ET.SubElement(gaeb_info, "Date").text = today
    ET.SubElement(gaeb_info, "ProgSystem").text = "OpenEstimate.io"
    ET.SubElement(gaeb_info, "ProgName").text = "OpenEstimate"

    # Award
    award = ET.SubElement(gaeb, "Award")
    ET.SubElement(award, "DP").text = "83"

    # BoQ
    boq_el = ET.SubElement(award, "BoQ")

    # BoQInfo (header)
    boq_info = ET.SubElement(boq_el, "BoQInfo")
    ET.SubElement(boq_info, "Name").text = boq_data.name
    ET.SubElement(boq_info, "LblTx").text = project_name
    ET.SubElement(boq_info, "Date").text = today
    outl_compl = ET.SubElement(boq_info, "OutlCompl")
    ET.SubElement(outl_compl, "OutlComplType").text = "OutlCompl"

    # BoQBody (root level)
    boq_body = ET.SubElement(boq_el, "BoQBody")

    def _fmt(value: float) -> str:
        """Format a numeric value with 2 decimal places for GAEB XML."""
        return f"{value:.2f}"

    # Map GAEB-compatible unit codes
    _UNIT_MAP: dict[str, str] = {
        "m": "m",
        "m2": "m2",
        "m3": "m3",
        "kg": "kg",
        "t": "t",
        "pcs": "Stk",
        "lsum": "psch",
        "h": "h",
        "l": "l",
    }

    def _gaeb_unit(unit: str) -> str:
        """Convert internal unit to GAEB-compatible unit code."""
        return _UNIT_MAP.get(unit.lower().strip(), unit)

    # ── Sections → BoQCtgy ────────────────────────────────────────────────
    for section in boq_data.sections:
        ctgy = ET.SubElement(
            boq_body,
            "BoQCtgy",
            RNoPart="1",
            ID=str(section.ordinal),
        )
        ET.SubElement(ctgy, "LblTx").text = section.description

        ctgy_body = ET.SubElement(ctgy, "BoQBody")
        itemlist = ET.SubElement(ctgy_body, "Itemlist")

        for pos in section.positions:
            item = ET.SubElement(
                itemlist,
                "Item",
                RNoPart="2",
                ID=str(pos.ordinal),
            )
            ET.SubElement(item, "Qty").text = _fmt(pos.quantity)
            ET.SubElement(item, "QU").text = _gaeb_unit(pos.unit)

            desc = ET.SubElement(item, "Description")
            complete_text = ET.SubElement(desc, "CompleteText")
            detail_txt = ET.SubElement(complete_text, "DetailTxt")
            ET.SubElement(detail_txt, "Text").text = pos.description

            ET.SubElement(item, "UP").text = _fmt(pos.unit_rate)
            ET.SubElement(item, "IT").text = _fmt(pos.total)

    # ── Ungrouped positions → separate BoQCtgy ────────────────────────────
    if boq_data.positions:
        ctgy = ET.SubElement(
            boq_body,
            "BoQCtgy",
            RNoPart="1",
            ID="00",
        )
        ET.SubElement(ctgy, "LblTx").text = "Ungrouped Positions"

        ctgy_body = ET.SubElement(ctgy, "BoQBody")
        itemlist = ET.SubElement(ctgy_body, "Itemlist")

        for pos in boq_data.positions:
            item = ET.SubElement(
                itemlist,
                "Item",
                RNoPart="2",
                ID=str(pos.ordinal),
            )
            ET.SubElement(item, "Qty").text = _fmt(pos.quantity)
            ET.SubElement(item, "QU").text = _gaeb_unit(pos.unit)

            desc = ET.SubElement(item, "Description")
            complete_text = ET.SubElement(desc, "CompleteText")
            detail_txt = ET.SubElement(complete_text, "DetailTxt")
            ET.SubElement(detail_txt, "Text").text = pos.description

            ET.SubElement(item, "UP").text = _fmt(pos.unit_rate)
            ET.SubElement(item, "IT").text = _fmt(pos.total)

    # ── Trailing BoQInfo with grand total ─────────────────────────────────
    boq_info_total = ET.SubElement(boq_el, "BoQInfo")
    ET.SubElement(boq_info_total, "TotPr").text = _fmt(boq_data.grand_total)

    # ── Serialize to XML string ───────────────────────────────────────────
    xml_declaration = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml_body = ET.tostring(gaeb, encoding="unicode", xml_declaration=False)
    xml_content = xml_declaration + xml_body

    safe_name = (
        boq_data.name.encode("ascii", errors="replace")
        .decode("ascii")
        .replace('"', "'")
    )
    filename = f"{safe_name}.X83"

    return StreamingResponse(
        iter([xml_content]),
        media_type="application/xml; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


# ── Import (CSV / Excel) ──────────────────────────────────────────────────────

logger = logging.getLogger(__name__)

# Column name aliases for flexible matching (all lowercased for comparison)
_COLUMN_ALIASES: dict[str, list[str]] = {
    "ordinal": ["pos", "pos.", "position", "ordinal", "nr.", "nr", "no.", "no", "#"],
    "description": [
        "description", "beschreibung", "desc", "text", "bezeichnung",
        "item", "item description",
    ],
    "unit": ["unit", "einheit", "me", "uom", "unit of measure"],
    "quantity": ["quantity", "qty", "menge", "amount", "qty.", "quantity (qty)"],
    "unit_rate": [
        "unit rate", "rate", "ep", "einheitspreis", "unit price",
        "unit cost", "price", "rate (ep)",
    ],
    "total": ["total", "amount", "gesamtpreis", "gp", "sum", "total price"],
    "classification": [
        "classification", "din 276", "din276", "kg", "nrm", "code",
        "masterformat", "cost code", "cost group", "class",
    ],
}


def _match_column(header: str) -> str | None:
    """Match a header string to a canonical column name using the alias map.

    Args:
        header: Raw column header text from the uploaded file.

    Returns:
        Canonical column key (e.g. "ordinal", "description") or None if unrecognised.
    """
    normalised = header.strip().lower()
    for canonical, aliases in _COLUMN_ALIASES.items():
        if normalised in aliases:
            return canonical
    return None


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Parse a value to float, returning *default* on failure.

    Handles strings with comma decimal separators (e.g. "1.234,56" → 1234.56).
    """
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return default
    # Handle European-style numbers: "1.234,56" → "1234.56"
    if "," in text and "." in text:
        # Determine which is the decimal separator (last one wins)
        last_comma = text.rfind(",")
        last_dot = text.rfind(".")
        if last_comma > last_dot:
            # Comma is decimal separator: "1.234,56"
            text = text.replace(".", "").replace(",", ".")
        else:
            # Dot is decimal separator: "1,234.56"
            text = text.replace(",", "")
    elif "," in text:
        # Only commas — assume comma is decimal separator: "234,56"
        text = text.replace(",", ".")
    try:
        return float(text)
    except (ValueError, TypeError):
        return default


def _parse_rows_from_csv(content_bytes: bytes) -> list[dict[str, Any]]:
    """Parse rows from a CSV file.

    Tries UTF-8 first, then Latin-1 as fallback (common for DACH region files).

    Returns:
        List of dicts mapping canonical column names to cell values.
    """
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = content_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("Unable to decode CSV file — unsupported encoding")

    # Detect delimiter by sniffing first 4KB
    sniffer = csv.Sniffer()
    try:
        dialect = sniffer.sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel  # type: ignore[assignment]

    reader = csv.reader(io.StringIO(text), dialect)
    raw_headers = next(reader, None)
    if not raw_headers:
        raise ValueError("CSV file is empty or has no header row")

    column_map: dict[int, str] = {}
    for idx, hdr in enumerate(raw_headers):
        canonical = _match_column(hdr)
        if canonical:
            column_map[idx] = canonical

    rows: list[dict[str, Any]] = []
    for raw_row in reader:
        row: dict[str, Any] = {}
        for idx, val in enumerate(raw_row):
            canonical = column_map.get(idx)
            if canonical:
                row[canonical] = val.strip() if isinstance(val, str) else val
        if row:
            rows.append(row)

    return rows


def _parse_rows_from_excel(content_bytes: bytes) -> list[dict[str, Any]]:
    """Parse rows from an Excel (.xlsx) file using openpyxl.

    Reads the first (active) worksheet. The first row is treated as headers.

    Returns:
        List of dicts mapping canonical column names to cell values.
    """
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(content_bytes), read_only=True, data_only=True)
    ws = wb.active
    if ws is None:
        raise ValueError("Excel file has no worksheets")

    rows_iter = ws.iter_rows(values_only=True)
    raw_headers = next(rows_iter, None)
    if not raw_headers:
        raise ValueError("Excel file is empty or has no header row")

    column_map: dict[int, str] = {}
    for idx, hdr in enumerate(raw_headers):
        if hdr is not None:
            canonical = _match_column(str(hdr))
            if canonical:
                column_map[idx] = canonical

    rows: list[dict[str, Any]] = []
    for raw_row in rows_iter:
        row: dict[str, Any] = {}
        for idx, val in enumerate(raw_row):
            canonical = column_map.get(idx)
            if canonical and val is not None:
                row[canonical] = val
        if row:
            rows.append(row)

    wb.close()
    return rows


@router.post(
    "/boqs/{boq_id}/import/excel",
    dependencies=[Depends(RequirePermission("boq.update"))],
)
async def import_boq_excel(
    boq_id: uuid.UUID,
    file: UploadFile = File(..., description="Excel (.xlsx) or CSV (.csv) file"),
    service: BOQService = Depends(_get_service),
) -> dict[str, Any]:
    """Import BOQ positions from an Excel or CSV file.

    Accepts a multipart file upload. The file must be .xlsx or .csv.

    Expected columns (all optional except Description):
    - **Pos / Position / Ordinal / Nr.** — position ordinal number
    - **Description / Beschreibung / Text** — description (required)
    - **Unit / Einheit / ME** — unit of measurement
    - **Quantity / Qty / Menge** — quantity
    - **Unit Rate / Rate / EP / Einheitspreis** — unit rate
    - **Total** (ignored — auto-calculated from quantity x rate)
    - **Classification / DIN 276 / KG / NRM / Code** — classification code

    Returns:
        Summary with counts of imported, skipped, and error details per row.
    """
    # Verify BOQ exists (raises 404 if not found)
    await service.get_boq(boq_id)

    # Validate file type
    filename = (file.filename or "").lower()
    if not filename.endswith((".xlsx", ".csv")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file type. Please upload an Excel (.xlsx) or CSV (.csv) file.",
        )

    # Read file content
    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )

    # Limit file size (10 MB)
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File too large. Maximum size is 10 MB.",
        )

    # Parse rows based on file type
    try:
        if filename.endswith(".xlsx"):
            rows = _parse_rows_from_excel(content)
        else:
            rows = _parse_rows_from_csv(content)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to parse file: {exc}",
        )
    except Exception as exc:
        logger.exception("Unexpected error parsing import file: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to parse file. Please check the format and try again.",
        )

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No data rows found in file. Check that the first row contains column headers.",
        )

    # Import each row as a Position
    imported = 0
    skipped = 0
    errors: list[dict[str, Any]] = []
    auto_ordinal = 1

    for row_idx, row in enumerate(rows, start=2):  # start=2 because row 1 is header
        try:
            description = str(row.get("description", "")).strip()

            # Skip rows without a description (likely empty or total rows)
            if not description:
                skipped += 1
                continue

            # Skip rows that look like summary/total rows
            desc_lower = description.lower()
            if desc_lower in (
                "grand total", "total", "summe", "gesamt", "gesamtsumme",
                "subtotal", "zwischensumme",
            ):
                skipped += 1
                continue

            # Build ordinal: use from file or auto-generate
            ordinal = str(row.get("ordinal", "")).strip()
            if not ordinal:
                ordinal = str(auto_ordinal)
            auto_ordinal += 1

            # Parse unit
            unit = str(row.get("unit", "pcs")).strip()
            if not unit:
                unit = "pcs"

            # Parse numeric fields
            quantity = _safe_float(row.get("quantity"), default=0.0)
            unit_rate = _safe_float(row.get("unit_rate"), default=0.0)

            # Build classification from the classification column
            classification: dict[str, Any] = {}
            class_value = str(row.get("classification", "")).strip()
            if class_value:
                classification["code"] = class_value

            # Create position via service
            position_data = PositionCreate(
                boq_id=boq_id,
                ordinal=ordinal,
                description=description,
                unit=unit,
                quantity=quantity,
                unit_rate=unit_rate,
                classification=classification,
                source="excel_import",
            )
            await service.add_position(position_data)
            imported += 1

        except Exception as exc:
            errors.append({
                "row": row_idx,
                "error": str(exc),
                "data": {k: str(v)[:100] for k, v in row.items()},
            })
            logger.warning(
                "Import error at row %d for BOQ %s: %s", row_idx, boq_id, exc
            )

    logger.info(
        "BOQ import complete for %s: imported=%d, skipped=%d, errors=%d",
        boq_id, imported, skipped, len(errors),
    )

    return {
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
        "total_rows": len(rows),
    }


# ── Smart import helpers ─────────────────────────────────────────────────────


def _extract_from_pdf(content: bytes) -> dict[str, Any]:
    """Extract text and tables from a PDF file.

    Uses pdfplumber to extract tabular data first, falling back to plain text.

    Args:
        content: Raw PDF file bytes.

    Returns:
        Dict with ``text`` (extracted content) and ``structured`` flag.
    """
    import pdfplumber

    text_parts: list[str] = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            if tables:
                for table in tables:
                    for row in table:
                        text_parts.append("\t".join(str(cell or "") for cell in row))
            else:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)

    return {"text": "\n".join(text_parts), "structured": False}


def _extract_from_image(content: bytes, ext: str) -> dict[str, Any]:
    """Prepare an image for AI vision analysis.

    Encodes the raw image bytes as base64 and determines the MIME type.

    Args:
        content: Raw image file bytes.
        ext: File extension (e.g. ``jpg``, ``png``).

    Returns:
        Dict with ``image_base64``, ``mime``, empty ``text``, and ``structured`` flag.
    """
    import base64

    mime = f"image/{'jpeg' if ext in ('jpg', 'jpeg') else ext}"
    b64 = base64.b64encode(content).decode()
    return {"text": "", "image_base64": b64, "mime": mime, "structured": False}


def _extract_from_excel_for_smart(content: bytes) -> dict[str, Any]:
    """Extract data from Excel for smart import.

    Tries to parse as structured rows first. If columns can be detected, returns
    structured data. Otherwise returns the raw cell text for AI processing.

    Args:
        content: Raw Excel file bytes.

    Returns:
        Dict with ``text``, ``structured`` flag, and optionally ``rows``.
    """
    try:
        rows = _parse_rows_from_excel(content)
        if rows:
            # Check if we have enough structure for a direct import
            has_description = any(r.get("description") for r in rows)
            if has_description:
                return {"text": "", "structured": True, "rows": rows}
    except Exception:
        pass

    # Fall back to extracting raw text from all cells
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active
    text_parts: list[str] = []
    if ws is not None:
        for row in ws.iter_rows(values_only=True):
            cells = [str(cell or "") for cell in row]
            line = "\t".join(cells).strip()
            if line:
                text_parts.append(line)
    wb.close()
    return {"text": "\n".join(text_parts), "structured": False}


def _extract_from_csv_for_smart(content: bytes) -> dict[str, Any]:
    """Extract data from CSV for smart import.

    Tries structured parsing first. If column detection fails, falls back to
    raw text extraction for AI processing.

    Args:
        content: Raw CSV file bytes.

    Returns:
        Dict with ``text``, ``structured`` flag, and optionally ``rows``.
    """
    try:
        rows = _parse_rows_from_csv(content)
        if rows:
            has_description = any(r.get("description") for r in rows)
            if has_description:
                return {"text": "", "structured": True, "rows": rows}
    except Exception:
        pass

    # Fall back to raw text
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = content.decode("latin-1", errors="replace")

    return {"text": text, "structured": False}


async def _extract_from_cad(content: bytes, ext: str, filename: str) -> dict[str, Any]:
    """Extract data from a CAD/BIM file using DDC Community converters.

    Saves the uploaded file to a temp directory, runs the appropriate DDC
    converter (.exe) to produce an Excel file, then parses the Excel output
    into an element summary for AI processing.

    Args:
        content: Raw CAD file bytes.
        ext: Lowercase file extension without dot (e.g. ``"rvt"``).
        filename: Original file name for temp file creation.

    Returns:
        Dict with ``text`` (element summary), ``structured`` flag, and metadata.
        If no converter is installed, returns a helpful message with download link.
    """
    from app.modules.boq.cad_import import (
        convert_cad_to_excel,
        find_converter,
        parse_cad_excel,
        summarize_cad_elements,
    )

    converter = find_converter(ext)
    if not converter:
        return {
            "text": (
                f"CAD file detected (.{ext}) but no DDC converter found.\n"
                f"Download DDC converters from:\n"
                f"https://github.com/datadrivenconstruction/ddc-community-toolkit/releases\n"
                f"Place .exe files in one of these locations:\n"
                f"  - converters/bin/ (project root)\n"
                f"  - ~/.openestimator/converters/\n"
                f"  - Set OPENESTIMATOR_CONVERTERS_DIR environment variable"
            ),
            "structured": False,
            "cad_no_converter": True,
        }

    # Save to temp dir, convert, parse
    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = Path(tmpdir) / filename
        input_path.write_bytes(content)

        output_dir = Path(tmpdir) / "output"
        output_dir.mkdir()

        excel_path = await convert_cad_to_excel(input_path, output_dir, ext)
        if not excel_path:
            return {
                "text": (
                    f"CAD conversion failed for .{ext} file. "
                    "Check that the converter is properly installed and the file is valid."
                ),
                "structured": False,
            }

        elements = parse_cad_excel(excel_path)
        summary = summarize_cad_elements(elements)

        return {
            "text": summary,
            "structured": False,
            "cad_elements": len(elements),
            "cad_format": ext,
        }


# ── Smart import endpoint ────────────────────────────────────────────────────


@router.post(
    "/boqs/{boq_id}/import/smart",
    dependencies=[Depends(RequirePermission("boq.update"))],
)
async def smart_import(
    boq_id: uuid.UUID,
    user_id: CurrentUserId,
    file: UploadFile = File(
        ...,
        description="Any document file (Excel, CSV, PDF, image, or CAD/BIM: .rvt, .ifc, .dwg, .dgn)",
    ),
    service: BOQService = Depends(_get_service),
    session: SessionDep = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Smart import: parse ANY file into BOQ positions using AI.

    Accepts Excel (.xlsx), CSV (.csv), PDF (.pdf), image files
    (.jpg, .jpeg, .png, .tiff, .bmp), and CAD/BIM files
    (.rvt, .ifc, .dwg, .dgn). For structured Excel/CSV with
    recognisable column headers, performs a direct import. For CAD/BIM
    files, runs a DDC converter to extract element data. Otherwise,
    sends the extracted text (or image) to the user's configured AI
    provider for intelligent parsing into BOQ positions.

    Returns:
        Summary with imported/error counts, method used, and AI model if applicable.
    """
    # Verify BOQ exists
    await service.get_boq(boq_id)

    filename = (file.filename or "unknown").lower()
    ext = filename.rsplit(".", 1)[-1] if "." in filename else ""

    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )

    # Limit file size — CAD files can be much larger than documents
    is_cad = ext in ("rvt", "ifc", "dwg", "dgn")
    max_size = 200 * 1024 * 1024 if is_cad else 15 * 1024 * 1024
    if len(content) > max_size:
        limit_label = "200 MB" if is_cad else "15 MB"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large. Maximum size is {limit_label}.",
        )

    # ── 1. Extract text/data based on file type ────────────────────────
    if ext in ("xlsx", "xls"):
        extracted = _extract_from_excel_for_smart(content)
    elif ext == "csv":
        extracted = _extract_from_csv_for_smart(content)
    elif ext == "pdf":
        extracted = _extract_from_pdf(content)
    elif ext in ("jpg", "jpeg", "png", "tiff", "bmp"):
        extracted = _extract_from_image(content, ext)
    elif ext in ("rvt", "ifc", "dwg", "dgn"):
        extracted = await _extract_from_cad(content, ext, file.filename or f"model.{ext}")
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported file type: .{ext}. "
                "Supported: xlsx, csv, pdf, jpg, png, tiff, rvt, ifc, dwg, dgn."
            ),
        )

    # ── 1b. Handle missing CAD converter (return early) ────────────────
    if extracted.get("cad_no_converter"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=extracted["text"],
        )

    # ── 2. Direct import for structured Excel/CSV ──────────────────────
    if extracted.get("structured") and extracted.get("rows"):
        rows = extracted["rows"]
        imported = 0
        skipped = 0
        errors: list[dict[str, Any]] = []
        auto_ordinal = 1

        for row_idx, row in enumerate(rows, start=2):
            try:
                description = str(row.get("description", "")).strip()
                if not description:
                    skipped += 1
                    continue

                desc_lower = description.lower()
                if desc_lower in (
                    "grand total", "total", "summe", "gesamt", "gesamtsumme",
                    "subtotal", "zwischensumme",
                ):
                    skipped += 1
                    continue

                ordinal = str(row.get("ordinal", "")).strip()
                if not ordinal:
                    ordinal = str(auto_ordinal)
                auto_ordinal += 1

                unit = str(row.get("unit", "pcs")).strip() or "pcs"
                quantity = _safe_float(row.get("quantity"), default=0.0)
                unit_rate = _safe_float(row.get("unit_rate"), default=0.0)

                classification: dict[str, Any] = {}
                class_value = str(row.get("classification", "")).strip()
                if class_value:
                    classification["code"] = class_value

                position_data = PositionCreate(
                    boq_id=boq_id,
                    ordinal=ordinal,
                    description=description,
                    unit=unit,
                    quantity=quantity,
                    unit_rate=unit_rate,
                    classification=classification,
                    source="smart_import",
                )
                await service.add_position(position_data)
                imported += 1

            except Exception as exc:
                errors.append({
                    "row": row_idx,
                    "error": str(exc),
                    "data": {k: str(v)[:100] for k, v in row.items()},
                })

        logger.info(
            "Smart import (direct) for BOQ %s: imported=%d, skipped=%d, errors=%d",
            boq_id, imported, skipped, len(errors),
        )

        return {
            "imported": imported,
            "skipped": skipped,
            "errors": errors,
            "total_items": len(rows),
            "method": "direct",
            "model_used": None,
        }

    # ── 3. AI-powered import ───────────────────────────────────────────
    from app.modules.ai.ai_client import call_ai, extract_json, resolve_provider_and_key
    from app.modules.ai.prompts import (
        CAD_IMPORT_PROMPT,
        SMART_IMPORT_PROMPT,
        SMART_IMPORT_VISION_PROMPT,
        SYSTEM_PROMPT,
    )
    from app.modules.ai.repository import AISettingsRepository

    settings_repo = AISettingsRepository(session)
    user_uuid = uuid.UUID(user_id)
    ai_settings = await settings_repo.get_by_user_id(user_uuid)

    try:
        provider, api_key = resolve_provider_and_key(ai_settings)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    # Build prompt
    image_b64: str | None = None
    image_mime: str = "image/jpeg"

    if extracted.get("image_base64"):
        # Image-based: use vision prompt
        prompt = SMART_IMPORT_VISION_PROMPT.format(filename=file.filename or "image")
        image_b64 = extracted["image_base64"]
        image_mime = extracted.get("mime", "image/jpeg")
    elif extracted.get("cad_format"):
        # CAD/BIM data: use specialized CAD prompt with larger context
        text_content = extracted.get("text", "")[:12000]
        if not text_content.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="CAD conversion produced no element data. The file may be empty or corrupt.",
            )
        prompt = CAD_IMPORT_PROMPT.format(text=text_content, currency="EUR")
    else:
        # Text-based: use text prompt (truncate to 8000 chars for context window)
        text_content = extracted.get("text", "")[:8000]
        if not text_content.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not extract any text from the file. Try a different format.",
            )
        prompt = SMART_IMPORT_PROMPT.format(
            text=text_content,
            filename=file.filename or "document",
        )

    # Call AI
    try:
        raw_response, _tokens = await call_ai(
            provider=provider,
            api_key=api_key,
            system=SYSTEM_PROMPT,
            prompt=prompt,
            image_base64=image_b64,
            image_media_type=image_mime,
            max_tokens=4096,
        )
    except Exception as exc:
        logger.exception("Smart import AI call failed for BOQ %s: %s", boq_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI service error: {exc}",
        ) from exc

    items = extract_json(raw_response)
    if not isinstance(items, list):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI did not return a valid list of items. Please try again.",
        )

    # ── 4. Create positions from AI response ───────────────────────────
    is_cad_import = bool(extracted.get("cad_format"))
    import_source = "cad_import_ai" if is_cad_import else "smart_import_ai"

    imported = 0
    errors = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        try:
            description = str(item.get("description", "")).strip()
            if len(description) < 2:
                continue

            ordinal = str(item.get("ordinal", "")).strip()
            if not ordinal:
                prefix = "CAD" if is_cad_import else "AI"
                ordinal = f"{prefix}.{imported + 1:04d}"

            unit = str(item.get("unit", "lsum")).strip() or "lsum"

            try:
                quantity = float(item.get("quantity", 0))
            except (ValueError, TypeError):
                quantity = 0.0

            try:
                unit_rate = float(item.get("unit_rate", 0))
            except (ValueError, TypeError):
                unit_rate = 0.0

            classification = item.get("classification", {})
            if not isinstance(classification, dict):
                classification = {}

            position_data = PositionCreate(
                boq_id=boq_id,
                ordinal=ordinal,
                description=description,
                unit=unit,
                quantity=max(quantity, 0.0),
                unit_rate=max(unit_rate, 0.0),
                classification=classification,
                source=import_source,
                confidence=0.7,
            )
            await service.add_position(position_data)
            imported += 1
        except Exception as exc:
            errors.append({
                "item": str(item.get("description", "?"))[:100],
                "error": str(exc),
            })
            logger.warning(
                "Smart import AI item error at index %d for BOQ %s: %s",
                idx, boq_id, exc,
            )

    method = "cad_ai" if is_cad_import else "ai"
    logger.info(
        "Smart import (%s) for BOQ %s: imported=%d, errors=%d, provider=%s",
        method, boq_id, imported, len(errors), provider,
    )

    result: dict[str, Any] = {
        "imported": imported,
        "errors": errors,
        "total_items": len(items),
        "method": method,
        "model_used": provider,
    }
    if is_cad_import:
        result["cad_format"] = extracted.get("cad_format")
        result["cad_elements"] = extracted.get("cad_elements", 0)
    return result


# ── Sustainability / CO2 Calculator ──────────────────────────────────────────

from app.modules.boq.epd_materials import (
    EPD_CATEGORIES,
    EPD_INDEX,
    EPD_MATERIALS,
    EU_CPR_BENCHMARKS,
    detect_epd_material,
    search_epd_materials,
)


def _co2_rating(benchmark_per_m2: float) -> tuple[str, str]:
    """Determine CO2 rating based on benchmark per m2."""
    if benchmark_per_m2 < 80:
        return "A", "Excellent"
    if benchmark_per_m2 < 150:
        return "B", "Good"
    if benchmark_per_m2 < 250:
        return "C", "Average"
    return "D", "Poor"


def _eu_cpr_compliance(gwp_per_m2_year: float) -> str:
    """Determine EU CPR 2024/3110 compliance level."""
    if gwp_per_m2_year <= EU_CPR_BENCHMARKS["excellent"]:
        return "excellent"
    if gwp_per_m2_year <= EU_CPR_BENCHMARKS["good"]:
        return "good"
    if gwp_per_m2_year <= EU_CPR_BENCHMARKS["acceptable"]:
        return "acceptable"
    return "non-compliant"


def _get_position_co2(pos: Any) -> dict[str, Any] | None:
    """Extract stored CO2 data from position metadata, or auto-detect."""
    meta = pos.metadata_ if hasattr(pos, "metadata_") else (pos.metadata or {})
    if isinstance(meta, dict) and "co2" in meta:
        return meta["co2"]
    return None


# ── Resource Summary ──────────────────────────────────────────────────────────


@router.get(
    "/boqs/{boq_id}/resource-summary",
    response_model=ResourceSummaryResponse,
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def get_resource_summary(
    boq_id: uuid.UUID,
    session: SessionDep,
    service: BOQService = Depends(_get_service),
) -> ResourceSummaryResponse:
    """Aggregate all resources across a BOQ's positions.

    Loads every position's ``metadata_.resources`` list, combines resources
    that share the same (name, type) key, sums quantities and costs, and
    groups totals by resource type (material, labor, equipment, etc.).

    When a position has no explicit resources in metadata, falls back to
    looking up the matching cost item from the database and using its
    ``components`` list as the resource data.

    Returns:
        ResourceSummaryResponse with per-type counts/totals and a flat
        resource list sorted by total_cost descending.
    """
    boq_data = await service.get_boq_with_positions(boq_id)

    # Aggregation key: (name_lower, type_lower) → accumulator
    agg: dict[tuple[str, str], dict[str, Any]] = {}

    def _add_resource(
        raw: dict[str, Any], pos_id: str, pos_qty: float = 1.0
    ) -> None:
        """Add a single resource dict to the aggregation map."""
        name = str(raw.get("name", raw.get("code", ""))).strip()
        rtype = str(raw.get("type", "other")).strip().lower()
        if not name:
            return

        unit = str(raw.get("unit", "")).strip()
        try:
            qty = float(raw.get("quantity", 1.0))
            rate = float(raw.get("unit_rate", 0))
        except (ValueError, TypeError):
            return

        cost = qty * rate * max(pos_qty, 1.0)
        key = (name.lower(), rtype)

        if key not in agg:
            agg[key] = {
                "name": name,
                "type": rtype,
                "unit": unit,
                "total_quantity": 0.0,
                "total_cost": 0.0,
                "rates": [],
                "positions": set(),
            }

        entry = agg[key]
        entry["total_quantity"] += qty * max(pos_qty, 1.0)
        entry["total_cost"] += cost
        entry["rates"].append(rate)
        entry["positions"].add(pos_id)

    for pos in boq_data.positions:
        meta = pos.metadata or {}
        resources = meta.get("resources")
        pos_qty = float(pos.quantity or 0) if hasattr(pos, "quantity") else 1.0

        if isinstance(resources, list) and len(resources) > 0:
            for raw in resources:
                if not isinstance(raw, dict):
                    continue
                _add_resource(raw, str(pos.id))
        else:
            # Fast heuristic: classify by description and create a synthetic resource
            desc = pos.description or ""
            if not desc.strip():
                continue
            rate = float(pos.unit_rate or 0) if hasattr(pos, "unit_rate") else 0.0
            total = rate * max(pos_qty, 1.0)
            if total <= 0:
                continue
            cat = BOQService._classify_position_category(desc)
            _add_resource({
                "name": desc[:80],
                "type": cat,
                "unit": str(getattr(pos, "unit", "") or ""),
                "quantity": pos_qty,
                "unit_rate": rate,
            }, str(pos.id))

    # Build flat resource list sorted by total_cost descending
    resource_items: list[ResourceSummaryItem] = []
    for entry in agg.values():
        rates_list: list[float] = entry["rates"]
        avg_rate = sum(rates_list) / len(rates_list) if rates_list else 0.0
        resource_items.append(
            ResourceSummaryItem(
                name=entry["name"],
                type=entry["type"],
                unit=entry["unit"],
                total_quantity=round(entry["total_quantity"], 3),
                avg_unit_rate=round(avg_rate, 2),
                total_cost=round(entry["total_cost"], 2),
                positions_used=len(entry["positions"]),
            )
        )

    resource_items.sort(key=lambda r: r.total_cost, reverse=True)

    # Build by_type summary
    by_type: dict[str, ResourceTypeSummary] = {}
    for item in resource_items:
        if item.type not in by_type:
            by_type[item.type] = ResourceTypeSummary(count=0, total_cost=0.0)
        by_type[item.type].count += 1
        by_type[item.type].total_cost = round(
            by_type[item.type].total_cost + item.total_cost, 2
        )

    return ResourceSummaryResponse(
        total_resources=len(resource_items),
        by_type=by_type,
        resources=resource_items,
    )


@router.post(
    "/boqs/{boq_id}/enrich-resources",
    dependencies=[Depends(RequirePermission("boq.write"))],
)
async def enrich_resources(
    boq_id: uuid.UUID,
    session: SessionDep,
    service: BOQService = Depends(_get_service),
) -> dict[str, Any]:
    """Auto-populate metadata.resources for positions that don't have them.

    For each position without explicit resources:
    1. If metadata has cost_item_code → look up cost item → copy components
    2. Else → fuzzy match by description via _lookup_cost_item_components

    Returns count of enriched positions.
    """
    boq_data = await service.get_boq_with_positions(boq_id)
    cost_repo = CostItemRepository(session)
    enriched_count = 0
    total_positions = 0

    for pos in boq_data.positions:
        # Skip sections (positions with children / no unit)
        if not pos.unit:
            continue
        total_positions += 1

        meta = dict(pos.metadata_) if pos.metadata_ else {}
        existing_resources = meta.get("resources")
        if isinstance(existing_resources, list) and len(existing_resources) > 0:
            continue  # Already has resources

        # Try lookup by cost_item_code first
        components: list[dict[str, Any]] = []
        cost_item_code = meta.get("cost_item_code")
        if cost_item_code:
            try:
                items, _ = await cost_repo.search(q=str(cost_item_code), limit=1)
                if items and items[0].components:
                    raw = items[0].components
                    if isinstance(raw, str):
                        import json as _json
                        raw = _json.loads(raw)
                    if isinstance(raw, list):
                        components = raw
            except Exception:
                pass

        # Fallback: lookup by description
        if not components:
            components = await BOQService._lookup_cost_item_components(
                cost_repo, pos.description or ""
            )

        if components:
            resources = []
            for c in components:
                res = {
                    "name": c.get("name", ""),
                    "code": c.get("code", ""),
                    "type": c.get("type", "other"),
                    "unit": c.get("unit", ""),
                    "quantity": float(c.get("quantity", 0)),
                    "unit_rate": float(c.get("unit_rate", 0)),
                    "total": float(c.get("cost", 0))
                    or float(c.get("quantity", 0)) * float(c.get("unit_rate", 0)),
                }
                resources.append(res)

            meta["resources"] = resources
            await service.repo.update(pos.id, {"metadata_": meta})
            enriched_count += 1

    await session.commit()

    return {
        "enriched_count": enriched_count,
        "total_positions": total_positions,
    }


@router.get(
    "/epd-materials",
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def list_epd_materials(
    category: str | None = Query(default=None, description="Filter by category"),
    search: str | None = Query(default=None, description="Search by name or ID"),
) -> dict[str, Any]:
    """List available EPD materials with optional filtering."""
    materials = search_epd_materials(category=category, query=search)
    return {
        "materials": materials,
        "categories": EPD_CATEGORIES,
        "total": len(materials),
    }


@router.post(
    "/boqs/{boq_id}/enrich-co2",
    response_model=CO2EnrichResponse,
    dependencies=[Depends(RequirePermission("boq.write"))],
)
async def enrich_co2(
    boq_id: uuid.UUID,
    session: SessionDep,
    service: BOQService = Depends(_get_service),
) -> CO2EnrichResponse:
    """Auto-detect EPD materials for all BOQ positions and store CO2 data.

    Loops through positions, matches descriptions to the 77 EPD materials,
    calculates GWP totals, and stores results in position metadata.
    Skips positions that already have manually assigned CO2 data.
    """
    boq_data = await service.get_boq_with_positions(boq_id)
    enriched = 0
    skipped = 0
    total = 0

    for pos in boq_data.positions:
        if not pos.unit:
            continue  # Skip section headers
        total += 1

        meta = dict(pos.metadata_) if pos.metadata_ else {}
        existing_co2 = meta.get("co2", {})

        # Skip manually assigned (source=manual)
        if existing_co2.get("source") == "manual":
            skipped += 1
            continue

        epd = detect_epd_material(pos.description)
        if epd is None:
            skipped += 1
            continue

        qty = float(pos.quantity) if pos.quantity else 0.0
        gwp_total = qty * epd["gwp"]

        meta["co2"] = {
            "epd_id": epd["id"],
            "epd_name": epd["name"],
            "category": epd["category"],
            "gwp_per_unit": epd["gwp"],
            "gwp_total": round(gwp_total, 2),
            "unit": epd["unit"],
            "source": "auto",
            "stages": epd["stages"],
            "data_source": epd["source"],
        }
        await service.repo.update(pos.id, {"metadata_": meta})
        enriched += 1

    await session.commit()
    return CO2EnrichResponse(enriched=enriched, skipped=skipped, total=total)


@router.put(
    "/positions/{position_id}/co2",
    dependencies=[Depends(RequirePermission("boq.write"))],
)
async def assign_position_co2(
    position_id: uuid.UUID,
    payload: CO2AssignRequest,
    session: SessionDep,
    service: BOQService = Depends(_get_service),
) -> dict[str, Any]:
    """Manually assign an EPD material to a BOQ position.

    Updates the position's metadata with CO2 data from the specified EPD material.
    """
    from fastapi import HTTPException

    epd = EPD_INDEX.get(payload.epd_id)
    if not epd:
        raise HTTPException(
            status_code=404,
            detail=f"EPD material '{payload.epd_id}' not found. "
            f"Use GET /epd-materials to list available materials.",
        )

    pos = await service.repo.get(position_id)
    if not pos:
        raise HTTPException(status_code=404, detail="Position not found")

    meta = dict(pos.metadata_) if pos.metadata_ else {}
    qty = float(pos.quantity) if pos.quantity else 0.0
    gwp_total = qty * epd["gwp"]

    meta["co2"] = {
        "epd_id": epd["id"],
        "epd_name": epd["name"],
        "category": epd["category"],
        "gwp_per_unit": epd["gwp"],
        "gwp_total": round(gwp_total, 2),
        "unit": epd["unit"],
        "source": "manual",
        "stages": epd["stages"],
        "data_source": epd["source"],
    }
    await service.repo.update(position_id, {"metadata_": meta})
    await session.commit()

    return {"status": "ok", "co2": meta["co2"]}


@router.get(
    "/boqs/{boq_id}/sustainability",
    response_model=SustainabilityResponse,
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def get_sustainability(
    boq_id: uuid.UUID,
    area_m2: float = Query(default=0.0, ge=0.0, description="Project gross floor area in m2"),
    service: BOQService = Depends(_get_service),
) -> SustainabilityResponse:
    """Calculate CO2 emissions for a BOQ using EPD data.

    Two-pass approach:
    1. Use stored metadata.co2 data (from enrich-co2 or manual assignment)
    2. Fall back to auto-detection for positions without stored CO2

    Returns per-position detail, category breakdown, benchmarks, and EU CPR compliance.
    """
    boq_data = await service.get_boq_with_positions(boq_id)

    positions_detail: list[PositionCO2Detail] = []
    category_totals: dict[str, dict[str, Any]] = {}  # category -> {co2, qty, count}
    positions_matched = 0
    enriched_count = 0
    total_positions = 0

    for pos in boq_data.positions:
        if not pos.unit:
            continue  # Skip section headers
        total_positions += 1
        qty = float(pos.quantity) if pos.quantity else 0.0

        # Try stored CO2 data first
        stored = _get_position_co2(pos)
        if stored and stored.get("epd_id"):
            epd_id = stored["epd_id"]
            epd_name = stored.get("epd_name", "")
            gwp_per_unit = float(stored.get("gwp_per_unit", 0))
            gwp_total = qty * gwp_per_unit  # Recalculate with current quantity
            category = stored.get("category", "")
            source = "enriched" if stored.get("source") != "manual" else "manual"
            enriched_count += 1
            positions_matched += 1
        else:
            # Auto-detect fallback
            epd = detect_epd_material(pos.description)
            if epd:
                epd_id = epd["id"]
                epd_name = epd["name"]
                gwp_per_unit = epd["gwp"]
                gwp_total = qty * gwp_per_unit
                category = epd["category"]
                source = "auto-detected"
                positions_matched += 1
            else:
                epd_id = None
                epd_name = None
                gwp_per_unit = 0.0
                gwp_total = 0.0
                category = ""
                source = "none"

        positions_detail.append(
            PositionCO2Detail(
                position_id=str(pos.id),
                ordinal=pos.ordinal,
                description=pos.description[:120],
                quantity=qty,
                unit=pos.unit,
                epd_id=epd_id,
                epd_name=epd_name,
                gwp_per_unit=round(gwp_per_unit, 4),
                gwp_total=round(gwp_total, 2),
                category=category,
                source=source,
            )
        )

        # Accumulate by category
        if category and gwp_total != 0:
            if category not in category_totals:
                cat_info = next(
                    (c for c in EPD_CATEGORIES if c["id"] == category), {}
                )
                category_totals[category] = {
                    "label": cat_info.get("label", category),
                    "co2": 0.0,
                    "qty": 0.0,
                    "count": 0,
                    "unit": pos.unit,
                }
            category_totals[category]["co2"] += gwp_total
            category_totals[category]["qty"] += qty
            category_totals[category]["count"] += 1

    total_co2_kg = sum(ct["co2"] for ct in category_totals.values())
    total_co2_tons = total_co2_kg / 1000.0
    abs_total = sum(abs(ct["co2"]) for ct in category_totals.values()) or 1.0

    # Build breakdown sorted by absolute CO2 descending
    breakdown: list[CO2MaterialBreakdown] = []
    for cat, info in sorted(
        category_totals.items(), key=lambda x: abs(x[1]["co2"]), reverse=True
    ):
        breakdown.append(
            CO2MaterialBreakdown(
                material=info["label"],
                category=cat,
                quantity=round(info["qty"], 2),
                unit=info["unit"],
                co2_kg=round(info["co2"], 1),
                percentage=round(abs(info["co2"]) / abs_total * 100, 1),
                positions_count=info["count"],
            )
        )

    # Benchmark per m2 and rating
    benchmark: float | None = None
    rating = ""
    rating_label = ""
    eu_cpr_compliance = ""
    eu_cpr_gwp_per_m2_year: float | None = None

    if area_m2 > 0:
        benchmark = round(total_co2_kg / area_m2, 1)
        rating, rating_label = _co2_rating(benchmark)
        # EU CPR uses annualized value (50-year reference service period)
        eu_cpr_gwp_per_m2_year = round(total_co2_kg / area_m2 / 50, 2)
        eu_cpr_compliance = _eu_cpr_compliance(eu_cpr_gwp_per_m2_year)

    # Data quality
    if enriched_count == positions_matched and enriched_count > 0:
        data_quality = "enriched"
    elif enriched_count > 0:
        data_quality = "mixed"
    else:
        data_quality = "estimated"

    return SustainabilityResponse(
        total_co2_kg=round(total_co2_kg, 1),
        total_co2_tons=round(total_co2_tons, 2),
        breakdown=breakdown,
        benchmark_per_m2=benchmark,
        rating=rating,
        rating_label=rating_label,
        project_area_m2=area_m2 if area_m2 > 0 else None,
        positions_analyzed=total_positions,
        positions_matched=positions_matched,
        lifecycle_stages="A1-A3",
        data_quality=data_quality,
        positions_detail=positions_detail,
        eu_cpr_compliance=eu_cpr_compliance,
        eu_cpr_gwp_per_m2_year=eu_cpr_gwp_per_m2_year,
    )


# ── Cost Breakdown ──────────────────────────────────────────────────────────


@router.get(
    "/boqs/{boq_id}/cost-breakdown",
    response_model=CostBreakdownResponse,
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def get_cost_breakdown(
    boq_id: uuid.UUID,
    service: BOQService = Depends(_get_service),
) -> CostBreakdownResponse:
    """Get a cost breakdown for a BOQ split by resource category.

    Analyzes all positions in the BOQ and aggregates costs into categories:
    material, labor, equipment, subcontractor, and other. Each position's
    ``metadata.resources`` list is used when available; otherwise, the position
    description is classified via keyword heuristics.

    Returns:
        CostBreakdownResponse with direct cost categories, markup lines,
        grand total, and top 10 most expensive resources.
    """
    return await service.get_cost_breakdown(boq_id)


# ── Sensitivity Analysis (Tornado Chart) ─────────────────────────────────────


@router.get(
    "/boqs/{boq_id}/sensitivity",
    response_model=SensitivityResponse,
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def get_sensitivity(
    boq_id: uuid.UUID,
    variation_pct: float = Query(
        default=10.0, gt=0.0, le=100.0, description="Cost variation percentage"
    ),
    top_n: int = Query(
        default=15, ge=1, le=50, description="Number of top positions to return"
    ),
    service: BOQService = Depends(_get_service),
) -> SensitivityResponse:
    """Compute sensitivity analysis (tornado chart data) for a BOQ.

    For each non-section position, calculates the share of the total cost and
    the impact of a ``variation_pct`` increase or decrease.  Returns the top N
    positions sorted by descending impact.

    Args:
        boq_id: Target BOQ identifier.
        variation_pct: Percentage to vary each position's cost (default 10%).
        top_n: Maximum number of positions to return (default 15).

    Returns:
        SensitivityResponse with base_total, variation_pct, and ranked items.
    """
    boq_data = await service.get_boq_with_positions(boq_id)

    # Filter to non-section positions (positions that have a unit)
    items = [p for p in boq_data.positions if p.unit and p.unit.strip() != ""]

    base_total = sum(p.total for p in items)

    if base_total == 0 or len(items) == 0:
        return SensitivityResponse(
            base_total=0.0,
            variation_pct=variation_pct,
            items=[],
        )

    factor = variation_pct / 100.0

    sensitivity_items: list[SensitivityItem] = []
    for pos in items:
        pos_total = pos.total
        share_pct = round(pos_total / base_total * 100, 2)
        impact = round(pos_total * factor, 2)
        sensitivity_items.append(
            SensitivityItem(
                ordinal=pos.ordinal,
                description=pos.description,
                total=round(pos_total, 2),
                share_pct=share_pct,
                impact_low=round(-impact, 2),
                impact_high=round(impact, 2),
            )
        )

    # Sort by absolute impact descending, take top N
    sensitivity_items.sort(key=lambda x: abs(x.impact_high), reverse=True)
    sensitivity_items = sensitivity_items[:top_n]

    return SensitivityResponse(
        base_total=round(base_total, 2),
        variation_pct=variation_pct,
        items=sensitivity_items,
    )


# ── AACE Estimate Classification ─────────────────────────────────────────────


@router.get(
    "/boqs/{boq_id}/classification",
    response_model=EstimateClassificationResponse,
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def get_estimate_classification(
    boq_id: uuid.UUID,
    service: BOQService = Depends(_get_service),
) -> EstimateClassificationResponse:
    """Get the AACE 18R-97 estimate classification for a BOQ.

    Auto-detects the estimate class (1-5) based on the number of positions,
    rate completeness, resource completeness, and classification coverage.

    Returns:
        EstimateClassificationResponse with class, accuracy range, definition
        level, methodology description, and underlying metrics.
    """
    return await service.get_estimate_classification(boq_id)


# ── Monte Carlo Cost Risk Analysis ───────────────────────────────────────────


def _pert_sample(low: float, mode: float, high: float) -> float:
    """Sample from a Beta-PERT distribution.

    Uses the standard PERT parameterization with lambda=4.

    Args:
        low: Minimum value (optimistic).
        mode: Most likely value.
        high: Maximum value (pessimistic).

    Returns:
        A random sample from the PERT distribution in [low, high].
    """
    if high <= low:
        return mode
    lam = 4.0
    alpha = 1.0 + lam * (mode - low) / (high - low)
    beta_param = 1.0 + lam * (high - mode) / (high - low)
    sample = random.betavariate(alpha, beta_param)
    return low + (high - low) * sample


@router.get(
    "/boqs/{boq_id}/cost-risk",
    response_model=CostRiskResponse,
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def get_cost_risk(
    boq_id: uuid.UUID,
    iterations: int = Query(
        default=1000, ge=100, le=10000, description="Number of Monte Carlo iterations"
    ),
    optimistic_pct: float = Query(
        default=15.0, ge=0.0, le=50.0, description="Optimistic cost reduction %"
    ),
    pessimistic_pct: float = Query(
        default=25.0, ge=0.0, le=100.0, description="Pessimistic cost increase %"
    ),
    service: BOQService = Depends(_get_service),
) -> CostRiskResponse:
    """Run a Monte Carlo cost risk simulation for a BOQ.

    For each iteration, every non-section position's total cost is sampled
    using a Beta-PERT distribution with:
        - optimistic = total * (1 - optimistic_pct/100)
        - most_likely = total
        - pessimistic = total * (1 + pessimistic_pct/100)

    After all iterations, percentiles (P10..P90) are computed, a histogram
    with ~20 bins is built, and the top risk drivers (positions contributing
    most to total variance) are identified.

    Contingency is defined as P80 - P50.  Recommended budget is P80.

    Args:
        boq_id: Target BOQ identifier.
        iterations: Number of simulation iterations (default 1000).
        optimistic_pct: Optimistic cost reduction percentage (default 15).
        pessimistic_pct: Pessimistic cost increase percentage (default 25).

    Returns:
        CostRiskResponse with percentiles, histogram, contingency, and risk drivers.
    """
    boq_data = await service.get_boq_with_positions(boq_id)

    # Filter to non-section positions (positions that have a unit)
    items = [p for p in boq_data.positions if p.unit and p.unit.strip() != ""]
    base_total = sum(p.total for p in items)

    if base_total == 0 or len(items) == 0:
        return CostRiskResponse(
            iterations=iterations,
            base_total=0.0,
            percentiles=CostRiskPercentiles(
                p10=0.0, p25=0.0, p50=0.0, p75=0.0, p80=0.0, p90=0.0
            ),
            contingency_p80=0.0,
            contingency_pct=0.0,
            recommended_budget=0.0,
            histogram=[],
            risk_drivers=[],
        )

    opt_factor = 1.0 - optimistic_pct / 100.0
    pess_factor = 1.0 + pessimistic_pct / 100.0

    # Pre-compute per-position bounds
    position_bounds: list[tuple[float, float, float, str, str]] = []
    for pos in items:
        t = pos.total
        position_bounds.append((t * opt_factor, t, t * pess_factor, pos.ordinal, pos.description))

    # Run Monte Carlo simulation
    iteration_totals: list[float] = []
    # Track per-position sampled values for variance analysis
    n_positions = len(position_bounds)
    position_sums: list[float] = [0.0] * n_positions
    position_sq_sums: list[float] = [0.0] * n_positions

    for _ in range(iterations):
        iter_total = 0.0
        for idx, (low, mode, high, _ordinal, _desc) in enumerate(position_bounds):
            sampled = _pert_sample(low, mode, high)
            iter_total += sampled
            position_sums[idx] += sampled
            position_sq_sums[idx] += sampled * sampled
        iteration_totals.append(iter_total)

    # Sort for percentile extraction
    iteration_totals.sort()

    def _percentile(sorted_data: list[float], pct: float) -> float:
        """Extract a percentile from sorted data using linear interpolation."""
        n = len(sorted_data)
        idx = pct / 100.0 * (n - 1)
        lower = int(idx)
        upper = min(lower + 1, n - 1)
        frac = idx - lower
        return sorted_data[lower] + frac * (sorted_data[upper] - sorted_data[lower])

    p10 = round(_percentile(iteration_totals, 10), 2)
    p25 = round(_percentile(iteration_totals, 25), 2)
    p50 = round(_percentile(iteration_totals, 50), 2)
    p75 = round(_percentile(iteration_totals, 75), 2)
    p80 = round(_percentile(iteration_totals, 80), 2)
    p90 = round(_percentile(iteration_totals, 90), 2)

    contingency_p80 = round(p80 - p50, 2)
    contingency_pct = round((contingency_p80 / p50 * 100) if p50 > 0 else 0.0, 1)

    # Build histogram with ~20 bins
    min_val = iteration_totals[0]
    max_val = iteration_totals[-1]
    num_bins = 20
    bin_width = (max_val - min_val) / num_bins if max_val > min_val else 1.0

    histogram: list[CostRiskHistogramBin] = []
    for i in range(num_bins):
        bin_start = min_val + i * bin_width
        bin_end = min_val + (i + 1) * bin_width
        count = 0
        for val in iteration_totals:
            if i == num_bins - 1:
                # Last bin includes the upper bound
                if bin_start <= val <= bin_end:
                    count += 1
            else:
                if bin_start <= val < bin_end:
                    count += 1
        histogram.append(
            CostRiskHistogramBin(
                bin_start=round(bin_start, 2),
                bin_end=round(bin_end, 2),
                count=count,
            )
        )

    # Calculate risk drivers — positions sorted by their share of total variance
    position_variances: list[tuple[float, str, str]] = []
    for idx in range(n_positions):
        mean = position_sums[idx] / iterations
        variance = (position_sq_sums[idx] / iterations) - (mean * mean)
        ordinal = position_bounds[idx][3]
        description = position_bounds[idx][4]
        position_variances.append((variance, ordinal, description))

    total_variance = sum(v[0] for v in position_variances)

    risk_drivers: list[CostRiskDriver] = []
    if total_variance > 0:
        position_variances.sort(key=lambda x: x[0], reverse=True)
        for variance, ordinal, description in position_variances[:10]:
            contribution_pct = round(variance / total_variance * 100, 1)
            risk_drivers.append(
                CostRiskDriver(
                    ordinal=ordinal,
                    description=description,
                    contribution_pct=contribution_pct,
                )
            )

    return CostRiskResponse(
        iterations=iterations,
        base_total=round(base_total, 2),
        percentiles=CostRiskPercentiles(
            p10=p10, p25=p25, p50=p50, p75=p75, p80=p80, p90=p90
        ),
        contingency_p80=contingency_p80,
        contingency_pct=contingency_pct,
        recommended_budget=p80,
        histogram=histogram,
        risk_drivers=risk_drivers,
    )


# ── Custom Column Definitions ────────────────────────────────────────────────


@router.get(
    "/boqs/{boq_id}/columns",
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def list_custom_columns(
    boq_id: uuid.UUID,
    service: BOQService = Depends(_get_service),
) -> list[dict]:
    """List custom column definitions for a BOQ."""
    boq = await service.get_boq(boq_id)
    meta = boq.metadata_ if isinstance(boq.metadata_, dict) else {}
    return meta.get("custom_columns", [])


@router.post(
    "/boqs/{boq_id}/columns",
    status_code=201,
    dependencies=[Depends(RequirePermission("boq.update"))],
)
async def add_custom_column(
    boq_id: uuid.UUID,
    data: dict = Body(...),
    service: BOQService = Depends(_get_service),
) -> dict:
    """Add a custom column definition to a BOQ.

    Body: {"name": "supplier", "display_name": "Supplier", "column_type": "text", "options": []}
    """
    name = data.get("name", "").strip().lower().replace(" ", "_")
    if not name or not name.isidentifier():
        raise HTTPException(400, "Invalid column name — use alphanumeric + underscore")

    reserved = {"ordinal", "description", "unit", "quantity", "unit_rate", "total", "id", "parent_id"}
    if name in reserved:
        raise HTTPException(400, f"Column name '{name}' is reserved")

    display_name = data.get("display_name", name.replace("_", " ").title())
    column_type = data.get("column_type", "text")
    if column_type not in ("text", "number", "date", "select"):
        raise HTTPException(400, "column_type must be: text, number, date, or select")

    options = data.get("options", [])

    boq = await service.get_boq(boq_id)
    meta = dict(boq.metadata_) if isinstance(boq.metadata_, dict) else {}
    columns: list[dict] = meta.get("custom_columns", [])

    # Check uniqueness
    if any(c["name"] == name for c in columns):
        raise HTTPException(400, f"Column '{name}' already exists")

    col_def = {
        "name": name,
        "display_name": display_name,
        "column_type": column_type,
        "options": options,
        "sort_order": len(columns),
    }
    columns.append(col_def)
    meta["custom_columns"] = columns

    boq.metadata_ = meta
    await service.session.flush()
    await service.session.commit()

    return col_def


@router.delete(
    "/boqs/{boq_id}/columns/{column_name}",
    status_code=204,
    dependencies=[Depends(RequirePermission("boq.update"))],
)
async def delete_custom_column(
    boq_id: uuid.UUID,
    column_name: str,
    service: BOQService = Depends(_get_service),
) -> None:
    """Remove a custom column definition (data in positions preserved)."""
    boq = await service.get_boq(boq_id)
    meta = dict(boq.metadata_) if isinstance(boq.metadata_, dict) else {}
    columns: list[dict] = meta.get("custom_columns", [])
    meta["custom_columns"] = [c for c in columns if c["name"] != column_name]

    boq.metadata_ = meta
    await service.session.flush()
    await service.session.commit()
