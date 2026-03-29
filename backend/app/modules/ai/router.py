"""AI Estimation API routes.

Endpoints:
    GET    /ai/settings                          — Get user's AI settings
    PATCH  /ai/settings                          — Update API keys and preferences
    POST   /ai/quick-estimate                    — Text description -> AI -> BOQ items
    POST   /ai/photo-estimate                    — Photo upload -> AI Vision -> BOQ items
    POST   /ai/file-estimate                     — Any file (PDF/Excel/CAD/image) -> AI -> BOQ items
    POST   /ai/estimate/{job_id}/create-boq      — Save AI estimate as a real BOQ
    GET    /ai/estimate/{job_id}                 — Get estimate job status and results
    POST   /ai/advisor/chat                      — AI Cost Advisor chat
"""

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status

logger = logging.getLogger(__name__)

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, check_ai_rate_limit
from app.modules.ai.schemas import (
    AISettingsResponse,
    AISettingsUpdate,
    CreateBOQFromEstimateRequest,
    EstimateJobResponse,
    QuickEstimateRequest,
)
from app.modules.ai.ai_client import call_ai, resolve_provider_and_key
from app.modules.ai.service import AIService

router = APIRouter()

# Maximum upload size for photos: 10 MB
MAX_PHOTO_SIZE = 10 * 1024 * 1024
# Maximum upload size for documents: 50 MB
MAX_FILE_SIZE = 50 * 1024 * 1024

ALLOWED_IMAGE_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
}

# Extension → file category mapping for file-estimate
_EXT_CATEGORY: dict[str, str] = {
    "pdf": "pdf",
    "xlsx": "excel",
    "xls": "excel",
    "csv": "csv",
    "rvt": "cad",
    "ifc": "cad",
    "dwg": "cad",
    "dgn": "cad",
    "rfa": "cad",
    "jpg": "image",
    "jpeg": "image",
    "png": "image",
    "webp": "image",
    "gif": "image",
    "tiff": "image",
    "bmp": "image",
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
    response: Response,
    remaining: int = Depends(check_ai_rate_limit),
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
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    return await service.quick_estimate(user_id, request)


# ── Photo Estimate (image -> AI Vision -> BOQ) ──────────────────────────────


@router.post(
    "/photo-estimate",
    response_model=EstimateJobResponse,
    dependencies=[Depends(RequirePermission("ai.estimate"))],
)
async def photo_estimate(
    user_id: CurrentUserId,
    response: Response,
    file: UploadFile = File(..., description="Building or construction site photo"),
    location: str = Form(default="Europe", description="Location for pricing context"),
    currency: str = Form(default="EUR", description="Currency code"),
    standard: str = Form(default="din276", description="Classification standard"),
    project_id: str | None = Form(default=None, description="Optional project ID"),
    remaining: int = Depends(check_ai_rate_limit),
    service: AIService = Depends(_get_service),
) -> EstimateJobResponse:
    """Generate a BOQ estimate from a building photo using AI Vision.

    Upload a photo of a building or construction site. The AI will:
    1. Identify the building type, dimensions, and materials
    2. Estimate quantities based on visible elements
    3. Generate a BOQ with realistic unit prices

    Accepted formats: JPEG, PNG, WebP, GIF. Max size: 10 MB.
    """
    response.headers["X-RateLimit-Remaining"] = str(remaining)
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


# ── Universal File Estimate (any file -> AI -> BOQ) ─────────────────────────


@router.post(
    "/file-estimate",
    response_model=EstimateJobResponse,
    dependencies=[Depends(RequirePermission("ai.estimate"))],
)
async def file_estimate(
    user_id: CurrentUserId,
    response: Response,
    file: UploadFile = File(..., description="Any file: PDF, Excel, CSV, CAD, or image"),
    location: str = Form(default="Europe", description="Location for pricing context"),
    currency: str = Form(default="EUR", description="Currency code"),
    standard: str = Form(default="din276", description="Classification standard"),
    project_id: str | None = Form(default=None, description="Optional project ID"),
    remaining: int = Depends(check_ai_rate_limit),
    service: AIService = Depends(_get_service),
) -> EstimateJobResponse:
    """Generate a BOQ estimate from any uploaded file using AI.

    Supports: PDF, Excel (.xlsx/.xls), CSV, CAD/BIM (.rvt, .ifc, .dwg, .dgn),
    and images (JPEG, PNG, WebP, GIF).

    The file is analysed based on its extension:
    - **PDF**: Text and tables extracted, sent to AI for BOQ generation
    - **Excel/CSV**: Parsed for structured data; falls back to AI if unstructured
    - **CAD/BIM**: Converted via DDC converter, elements summarised, AI generates BOQ
    - **Image**: Sent to AI Vision for OCR and BOQ extraction

    Max file size: 50 MB.
    """
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    filename = file.filename or "file"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    category = _EXT_CATEGORY.get(ext)
    if not category:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported file type: .{ext}. "
                f"Accepted: {', '.join(f'.{e}' for e in sorted(_EXT_CATEGORY))}"
            ),
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File is empty.")
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large ({len(content) / 1024 / 1024:.1f} MB). Max: {MAX_FILE_SIZE // 1024 // 1024} MB.",
        )

    parsed_project_id: uuid.UUID | None = None
    if project_id:
        try:
            parsed_project_id = uuid.UUID(project_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid project_id: {project_id}",
            ) from exc

    return await service.file_estimate(
        user_id=user_id,
        content=content,
        filename=filename,
        ext=ext,
        category=category,
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


# ── AI Cost Advisor chat ──────────────────────────────────────────────────


@router.post(
    "/advisor/chat",
    dependencies=[Depends(RequirePermission("ai.estimate"))],
)
async def advisor_chat(
    body: dict,
    session: SessionDep,
    user_id: CurrentUserId,
) -> dict:
    """AI Cost Advisor — answer questions about costs using the cost database.

    Body: ``{message: str, project_id?: str, region?: str}``

    Steps:
        1. Search cost DB for relevant items (vector search if available, text fallback)
        2. Build context from found items
        3. Call AI with context + user question
        4. Return structured answer with source references
    """
    message = body.get("message", "").strip()
    if not message:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Message is required")

    project_id = body.get("project_id")
    region = body.get("region", "")

    # 1. Search cost database for relevant items
    from app.modules.costs.models import CostItem
    from sqlalchemy import select

    context_items: list[dict] = []

    # Try vector search first
    try:
        from app.core.vector import encode_texts, vector_search

        query_vector = encode_texts([message])[0]
        results = vector_search(query_vector, region=region or None, limit=8)
        context_items = results
    except Exception:
        # Fallback: simple text search on first keyword
        keywords = message.split()
        pattern = f"%{keywords[0] if keywords else message}%"
        stmt = (
            select(CostItem)
            .where(CostItem.is_active.is_(True), CostItem.description.ilike(pattern))
            .limit(8)
        )
        result = await session.execute(stmt)
        items = result.scalars().all()
        for item in items:
            context_items.append({
                "code": item.code,
                "description": item.description[:200],
                "unit": item.unit,
                "rate": float(item.rate) if item.rate else 0,
                "region": item.region or "",
            })

    # 2. Build context from found items
    if context_items:
        items_text = "\n".join([
            f"- {it.get('code', '')}: {it.get('description', '')[:100]} | "
            f"{it.get('unit', '')} | {it.get('rate', 0)} | {it.get('region', '')}"
            for it in context_items[:8]
        ])
        context = f"Available cost data from database:\n{items_text}"
    else:
        context = "No specific cost items found in the database for this query."

    # 3. Get project context if provided
    project_context = ""
    if project_id:
        try:
            from app.modules.projects.models import Project

            proj = await session.get(Project, project_id)
            if proj:
                project_context = (
                    f"\nProject: {proj.name}, Region: {proj.region}, "
                    f"Currency: {proj.currency}"
                )
        except Exception:
            pass

    # 4. Build prompt
    system_prompt = (
        "You are an AI Cost Advisor for construction projects. "
        "You help estimators with cost-related questions.\n\n"
        "Rules:\n"
        "- Use the cost database data provided as context to answer questions\n"
        "- Always mention specific rates and units when available\n"
        "- If asked about costs, provide ranges (min-max) when possible\n"
        "- Suggest alternatives if the user asks about expensive items\n"
        "- Be concise and professional\n"
        "- Format numbers with proper currency\n"
        "- If you don't have data for the question, say so honestly"
    )

    user_prompt = (
        f"{context}{project_context}\n\n"
        f"User question: {message}\n\n"
        "Provide a helpful, concise answer based on the cost data above."
    )

    # 5. Call AI (reuse existing settings/provider resolution)
    service = _get_service(session)
    uid = uuid.UUID(user_id)
    settings = await service.settings_repo.get_by_user_id(uid)

    try:
        provider, api_key = resolve_provider_and_key(settings)
        text, _tokens = await call_ai(
            provider=provider,
            api_key=api_key,
            system=system_prompt,
            prompt=user_prompt,
            max_tokens=500,
        )
        answer = text
    except (ValueError, Exception) as exc:
        answer = (
            "AI is not configured. Please set up an AI provider in Settings. "
            f"(Error: {str(exc)[:100]})"
        )

    # 6. Build source references
    sources = [
        {
            "code": it.get("code", ""),
            "description": it.get("description", "")[:80],
            "rate": it.get("rate", 0),
            "unit": it.get("unit", ""),
            "region": it.get("region", ""),
        }
        for it in context_items[:5]
    ]

    return {
        "answer": answer,
        "sources": sources,
        "query": message,
    }
