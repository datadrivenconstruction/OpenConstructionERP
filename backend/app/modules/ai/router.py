"""AI Estimation API routes.

Endpoints:
    GET    /ai/settings                          — Get user's AI settings
    PATCH  /ai/settings                          — Update API keys and preferences
    POST   /ai/quick-estimate                    — Text description -> AI -> BOQ items
    POST   /ai/photo-estimate                    — Photo upload -> AI Vision -> BOQ items
    POST   /ai/estimate/{job_id}/create-boq      — Save AI estimate as a real BOQ
    GET    /ai/estimate/{job_id}                 — Get estimate job status and results
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.ai.schemas import (
    AISettingsResponse,
    AISettingsUpdate,
    CreateBOQFromEstimateRequest,
    EstimateJobResponse,
    QuickEstimateRequest,
)
from app.modules.ai.service import AIService

router = APIRouter()

# Maximum upload size for photos: 10 MB
MAX_PHOTO_SIZE = 10 * 1024 * 1024

ALLOWED_IMAGE_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
}


def _get_service(session: SessionDep) -> AIService:
    return AIService(session)


# ── AI Settings ──────────────────────────────────────────────────────────────


@router.get(
    "/settings",
    response_model=AISettingsResponse,
    dependencies=[Depends(RequirePermission("ai.settings.read"))],
)
async def get_ai_settings(
    user_id: CurrentUserId,
    service: AIService = Depends(_get_service),
) -> AISettingsResponse:
    """Get the current user's AI settings.

    Returns the configured providers and preferred model.
    API keys are masked — the response only indicates whether each key is set.
    """
    return await service.get_ai_settings(user_id)


@router.patch(
    "/settings",
    response_model=AISettingsResponse,
    dependencies=[Depends(RequirePermission("ai.settings.update"))],
)
async def update_ai_settings(
    data: AISettingsUpdate,
    user_id: CurrentUserId,
    service: AIService = Depends(_get_service),
) -> AISettingsResponse:
    """Update the current user's AI settings.

    Set API keys for AI providers and choose a preferred model.
    Only provided (non-null) fields are updated.

    Supported providers:
    - **Anthropic Claude** (anthropic_api_key) — recommended, best quality
    - **OpenAI** (openai_api_key) — GPT-4o
    - **Google Gemini** (gemini_api_key) — fast and affordable

    Preferred model options: `claude-sonnet`, `gpt-4o`, `gemini-flash`
    """
    return await service.update_ai_settings(user_id, data)


# ── Quick Estimate (text -> AI -> BOQ) ───────────────────────────────────────


@router.post(
    "/quick-estimate",
    response_model=EstimateJobResponse,
    dependencies=[Depends(RequirePermission("ai.estimate"))],
)
async def quick_estimate(
    request: QuickEstimateRequest,
    user_id: CurrentUserId,
    service: AIService = Depends(_get_service),
) -> EstimateJobResponse:
    """Generate a BOQ estimate from a text description using AI.

    Describe your construction project and the AI will generate a detailed
    Bill of Quantities with realistic quantities and market-rate unit prices.

    **Example descriptions:**
    - "3-story office building, 2000 m2, Berlin, reinforced concrete frame"
    - "Residential villa 350 m2 with swimming pool in Dubai"
    - "Warehouse 5000 m2, steel structure, Hamburg"

    The response includes:
    - Generated BOQ items with ordinal, description, unit, quantity, unit_rate, total
    - Classification codes (DIN 276, NRM, MasterFormat)
    - Token usage and processing time
    """
    return await service.quick_estimate(user_id, request)


# ── Photo Estimate (image -> AI Vision -> BOQ) ──────────────────────────────


@router.post(
    "/photo-estimate",
    response_model=EstimateJobResponse,
    dependencies=[Depends(RequirePermission("ai.estimate"))],
)
async def photo_estimate(
    user_id: CurrentUserId,
    file: UploadFile = File(..., description="Building or construction site photo"),
    location: str = Form(default="Europe", description="Location for pricing context"),
    currency: str = Form(default="EUR", description="Currency code"),
    standard: str = Form(default="din276", description="Classification standard"),
    project_id: str | None = Form(default=None, description="Optional project ID"),
    service: AIService = Depends(_get_service),
) -> EstimateJobResponse:
    """Generate a BOQ estimate from a building photo using AI Vision.

    Upload a photo of a building or construction site. The AI will:
    1. Identify the building type, dimensions, and materials
    2. Estimate quantities based on visible elements
    3. Generate a BOQ with realistic unit prices

    Accepted formats: JPEG, PNG, WebP, GIF. Max size: 10 MB.
    """
    # Validate file type
    content_type = file.content_type or ""
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported image type: {content_type}. "
                f"Accepted: {', '.join(sorted(ALLOWED_IMAGE_TYPES))}"
            ),
        )

    # Read and validate size
    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )
    if len(image_bytes) > MAX_PHOTO_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Image too large. Maximum size is 10 MB.",
        )

    # Parse optional project_id
    parsed_project_id: uuid.UUID | None = None
    if project_id:
        try:
            parsed_project_id = uuid.UUID(project_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid project_id format: {project_id}",
            ) from exc

    return await service.photo_estimate(
        user_id=user_id,
        image_bytes=image_bytes,
        filename=file.filename or "photo.jpg",
        media_type=content_type,
        location=location or None,
        currency=currency or None,
        standard=standard or None,
        project_id=parsed_project_id,
    )


# ── Create BOQ from estimate ────────────────────────────────────────────────


@router.post(
    "/estimate/{job_id}/create-boq",
    dependencies=[Depends(RequirePermission("ai.create_boq"))],
)
async def create_boq_from_estimate(
    job_id: uuid.UUID,
    request: CreateBOQFromEstimateRequest,
    user_id: CurrentUserId,
    service: AIService = Depends(_get_service),
) -> dict[str, Any]:
    """Save an AI estimation result as a real BOQ in a project.

    Takes a completed AI estimate job and creates a new BOQ in the specified
    project. Each estimated work item becomes a BOQ position with:
    - Source set to "ai_estimate"
    - Confidence score of 0.7
    - Validation status "pending"

    The created BOQ is in "draft" status and ready for manual review and editing.

    Returns:
        - boq_id: UUID of the created BOQ
        - positions_created: Number of positions added
        - grand_total: Sum of all position totals
    """
    return await service.create_boq_from_estimate(user_id, job_id, request)


# ── Get estimate job ─────────────────────────────────────────────────────────


@router.get(
    "/estimate/{job_id}",
    response_model=EstimateJobResponse,
    dependencies=[Depends(RequirePermission("ai.estimate"))],
)
async def get_estimate_job(
    job_id: uuid.UUID,
    user_id: CurrentUserId,
    service: AIService = Depends(_get_service),
) -> EstimateJobResponse:
    """Get the status and results of an AI estimate job.

    Returns the full job details including generated BOQ items if completed.
    """
    from app.modules.ai.service import _build_job_response

    uid = uuid.UUID(user_id)
    job = await service.job_repo.get_by_id(job_id)

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Estimate job not found",
        )

    if str(job.user_id) != str(uid):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only view your own estimate jobs",
        )

    return _build_job_response(job)
