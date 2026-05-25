"""‌⁠‍AI Estimation API routes.

Endpoints:
    GET    /ai/settings                          — Get user's AI settings
    PATCH  /ai/settings                          — Update API keys and preferences
    POST   /ai/quick-estimate                    — Text description -> AI -> BOQ items
    POST   /ai/photo-estimate                    — Photo upload -> AI Vision -> BOQ items
    POST   /ai/file-estimate                     — Any file (PDF/Excel/CAD/image) -> AI -> BOQ items
    POST   /ai/estimate/{job_id}/create-boq      — Save AI estimate as a real BOQ
    POST   /ai/estimate/{job_id}/enrich          — Enrich estimate items with cost DB matches
    GET    /ai/estimate/{job_id}                 — Get estimate job status and results
    POST   /ai/advisor/chat                      — AI Cost Advisor chat
"""

import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Response, UploadFile, status

logger = logging.getLogger(__name__)

from app.core.file_signature import (
    ALLOWED_CAD_TYPES,
    ALLOWED_PHOTO_TYPES,
    SIGNATURE_BYTES_REQUIRED,
    FileSignatureMismatch,
    require as require_signature,
)
from app.core.i18n import get_locale
from app.core.validation.messages import translate
from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    check_ai_rate_limit,
    verify_project_access,
)
from app.modules.ai.ai_client import (
    call_ai,
    default_model_for,
    resolve_provider_key_model,
)
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


# ── AI Providers (BUG-AI-PROVIDERS) ─────────────────────────────────────────


_AI_PROVIDERS: list[dict[str, Any]] = [
    {
        "id": "anthropic",
        "display_name": "Anthropic Claude",
        "supports_streaming": True,
        "model_choices": ["claude-sonnet", "claude-opus", "claude-haiku"],
        "recommended": True,
    },
    {
        "id": "openai",
        "display_name": "OpenAI",
        "supports_streaming": True,
        "model_choices": ["gpt-4.1", "gpt-4.1-mini", "gpt-4o", "gpt-4o-mini"],
    },
    {
        "id": "gemini",
        "display_name": "Google Gemini",
        "supports_streaming": True,
        "model_choices": ["gemini-flash", "gemini-pro"],
    },
    {
        "id": "openrouter",
        "display_name": "OpenRouter",
        "supports_streaming": True,
        "model_choices": [],
    },
    {"id": "mistral", "display_name": "Mistral AI", "supports_streaming": True, "model_choices": []},
    {"id": "groq", "display_name": "Groq", "supports_streaming": True, "model_choices": []},
    {"id": "deepseek", "display_name": "DeepSeek", "supports_streaming": True, "model_choices": []},
    {"id": "together", "display_name": "Together AI", "supports_streaming": True, "model_choices": []},
    {"id": "fireworks", "display_name": "Fireworks AI", "supports_streaming": True, "model_choices": []},
    {"id": "perplexity", "display_name": "Perplexity", "supports_streaming": True, "model_choices": []},
    {"id": "cohere", "display_name": "Cohere", "supports_streaming": True, "model_choices": []},
    {"id": "ai21", "display_name": "AI21 Labs", "supports_streaming": False, "model_choices": []},
    {"id": "xai", "display_name": "xAI Grok", "supports_streaming": True, "model_choices": []},
    {"id": "ollama", "display_name": "Ollama (Local)", "supports_streaming": True, "model_choices": []},
    {"id": "kimi", "display_name": "Kimi (Moonshot AI)", "supports_streaming": True, "model_choices": []},
    {"id": "vllm", "display_name": "vLLM (Local)", "supports_streaming": True, "model_choices": []},
]


@router.get(
    "/providers",
    summary="List available AI providers",
    description="Return the list of AI providers the platform can talk to. "
    "Lets the frontend render provider toggles dynamically instead of "
    "hard-coding the list.",
)
@router.get(
    "/providers/",
    summary="List available AI providers",
    description="Return the list of AI providers the platform can talk to. "
    "Lets the frontend render provider toggles dynamically instead of "
    "hard-coding the list.",
)
async def list_ai_providers() -> list[dict[str, Any]]:
    """‌⁠‍Return the list of supported AI providers."""
    return _AI_PROVIDERS


# ── AI Settings ──────────────────────────────────────────────────────────────


@router.get(
    "/settings/",
    response_model=AISettingsResponse,
    dependencies=[Depends(RequirePermission("ai.settings.read"))],
)
async def get_ai_settings(
    user_id: CurrentUserId,
    service: AIService = Depends(_get_service),
) -> AISettingsResponse:
    """‌⁠‍Get the current user's AI settings.

    Returns the configured providers and preferred model.
    API keys are masked — the response only indicates whether each key is set.
    """
    return await service.get_ai_settings(user_id)


@router.patch(
    "/settings/",
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


# ── Test API key ──────────────────────────────────────────────────────────────


@router.post(
    "/settings/test/",
    dependencies=[Depends(RequirePermission("ai.settings.read"))],
)
async def test_ai_connection(
    body: dict,
    user_id: CurrentUserId,
    service: AIService = Depends(_get_service),
) -> dict:
    """Test an AI provider connection by sending a minimal request.

    Body: ``{provider: "anthropic" | "openai" | "gemini"}``

    Returns success status and response latency.
    """
    _VALID_PROVIDERS = (
        "anthropic", "openai", "gemini", "openrouter", "mistral", "groq", "deepseek",
        "together", "fireworks", "perplexity", "cohere", "ai21", "xai",
        "ollama", "kimi", "vllm",
    )
    provider = body.get("provider", "").strip()
    if provider not in _VALID_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown provider: {provider}. Use one of: {', '.join(_VALID_PROVIDERS)}.",
        )

    from app.core.crypto import decrypt_secret

    uid = uuid.UUID(user_id)
    settings = await service.settings_repo.get_by_user_id(uid)

    # Resolve the API key for the requested provider. Keys are stored
    # Fernet-encrypted — passing the ciphertext straight to the provider
    # triggers a 401 ("AI API key is invalid or expired") even for a
    # fresh, valid key the user just pasted.
    key_attr = f"{provider}_api_key"
    raw = getattr(settings, key_attr, None) if settings else None
    if not raw:
        return {
            "success": False,
            "message": f"No API key configured for {provider}. Please save your key first.",
            "latency_ms": None,
        }
    api_key = decrypt_secret(raw)
    if not api_key:
        return {
            "success": False,
            "message": (
                f"Stored {provider} key could not be decrypted — the backend encryption key "
                "has rotated since the key was saved. Please re-enter and save it in Settings."
            ),
            "latency_ms": None,
        }

    # Resolve the model id the user configured for this provider (if any),
    # falling back to the built-in default. Testing with the SAME model the
    # real estimate calls use is what makes "stale model name" failures
    # surface here instead of mid-estimate (issue #129).
    from app.modules.ai.ai_client import _model_override_for

    model_override = _model_override_for(settings, provider)
    effective_model = model_override or default_model_for(provider)

    # Resolve custom base URL for local providers (Ollama, vLLM)
    meta = settings.metadata_ or {}
    base_url = None
    if provider in ("ollama", "vllm"):
        url_key = f"{provider}_base_url"
        raw_url = meta.get(url_key) if isinstance(meta, dict) else None
        if isinstance(raw_url, str) and raw_url.strip():
            base = raw_url.strip().rstrip("/")
            if not base.endswith("/v1/chat/completions"):
                base += "/v1/chat/completions"
            base_url = base

    # Make a minimal test call
    try:
        t0 = time.monotonic()
        await call_ai(
            provider=provider,
            api_key=api_key,
            system="You are a test assistant.",
            prompt="Reply with exactly: OK",
            max_tokens=10,
            model=model_override,
            base_url=base_url,
        )
        latency_ms = int((time.monotonic() - t0) * 1000)
        return {
            "success": True,
            "message": f"{provider.title()} API is working (model: {effective_model}).",
            "latency_ms": latency_ms,
            "model": effective_model,
        }
    except ValueError as exc:
        return {
            "success": False,
            "message": str(exc),
            "latency_ms": None,
            "model": effective_model,
        }
    except Exception as exc:
        logger.warning("AI test failed for %s: %s", provider, exc)
        return {
            "success": False,
            "message": f"Connection failed: {str(exc)[:200]}",
            "latency_ms": None,
            "model": effective_model,
        }


# ── Quick Estimate (text -> AI -> BOQ) ───────────────────────────────────────


@router.post(
    "/quick-estimate/",
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
    # R7 audit: when the caller links the job to a project we must
    # verify they actually own / can access that project. Without the
    # check, any authenticated user could write AI estimate jobs that
    # reference projects belonging to other tenants — useful for log
    # poisoning, cross-tenant cost-context smuggling, and as a stepping
    # stone for the create_boq_from_estimate flow.
    if request.project_id is not None:
        await verify_project_access(request.project_id, user_id, service.session)
    return await service.quick_estimate(user_id, request)


# ── Photo Estimate (image -> AI Vision -> BOQ) ──────────────────────────────


@router.post(
    "/photo-estimate/",
    response_model=EstimateJobResponse,
    dependencies=[Depends(RequirePermission("ai.estimate"))],
)
async def photo_estimate(
    user_id: CurrentUserId,
    response: Response,
    file: UploadFile = File(..., description="Building or construction site photo"),
    location: str = Form(default="", description="Location for pricing context (empty = AI infers from photo)"),
    currency: str = Form(default="", description="Currency code (empty = AI suggests from project context)"),
    standard: str = Form(default="", description="Classification standard (empty = AI uses region-native default)"),
    project_id: str | None = Form(default=None, description="Optional project ID"),
    content_length: int | None = Header(default=None),
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
            detail=(f"Unsupported image type: {content_type}. Accepted: {', '.join(sorted(ALLOWED_IMAGE_TYPES))}"),
        )

    # No upload size cap — per product policy.
    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )

    # Magic-byte gate: the request ``Content-Type`` header above is fully
    # controlled by the caller, so an attacker could declare ``image/png``
    # while uploading an HTML page, PE, or shellscript and have the AI
    # vision pipeline (or a downstream document store) treat the bytes
    # as something they're not. Inspect the first few bytes and reject
    # anything outside the photo allow-list.
    try:
        require_signature(
            image_bytes[:SIGNATURE_BYTES_REQUIRED],
            ALLOWED_PHOTO_TYPES,
            filename=file.filename,
        )
    except FileSignatureMismatch as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(exc),
        ) from exc

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
        # R7 audit: enforce project access on the linkage (same rationale
        # as quick_estimate — see comment there).
        await verify_project_access(parsed_project_id, user_id, service.session)

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
    "/file-estimate/",
    response_model=EstimateJobResponse,
    dependencies=[Depends(RequirePermission("ai.estimate"))],
)
async def file_estimate(
    user_id: CurrentUserId,
    response: Response,
    file: UploadFile = File(..., description="Any file: PDF, Excel, CSV, CAD, or image"),
    location: str = Form(default="", description="Location for pricing context (empty = AI infers from file)"),
    currency: str = Form(default="", description="Currency code (empty = AI suggests from project context)"),
    standard: str = Form(default="", description="Classification standard (empty = AI uses region-native default)"),
    project_id: str | None = Form(default=None, description="Optional project ID"),
    content_length: int | None = Header(default=None),
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
    """
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    filename = file.filename or "file"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    category = _EXT_CATEGORY.get(ext)
    if not category:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(f"Unsupported file type: .{ext}. Accepted: {', '.join(f'.{e}' for e in sorted(_EXT_CATEGORY))}"),
        )

    # No upload size cap — per product policy.
    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File is empty.")

    # Magic-byte gate per category. The extension above is attacker-
    # controlled (the request multipart filename is fully client-supplied),
    # so we must also confirm the file's actual signature matches the
    # category we're about to dispatch into. CSV/text files have no
    # reliable magic byte — skip the check for that category only.
    _CATEGORY_SIG_ALLOW: dict[str, frozenset[str]] = {
        "pdf": frozenset({"pdf"}),
        "excel": frozenset({"zip", "ole"}),
        "cad": ALLOWED_CAD_TYPES,
        "image": ALLOWED_PHOTO_TYPES,
    }
    allowed_sigs = _CATEGORY_SIG_ALLOW.get(category)
    if allowed_sigs is not None:
        try:
            require_signature(
                content[:SIGNATURE_BYTES_REQUIRED],
                allowed_sigs,
                filename=file.filename,
            )
        except FileSignatureMismatch as exc:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=str(exc),
            ) from exc

    parsed_project_id: uuid.UUID | None = None
    if project_id:
        try:
            parsed_project_id = uuid.UUID(project_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid project_id: {project_id}",
            ) from exc
        # R7 audit: enforce project access on the linkage (same rationale
        # as quick_estimate — see comment there).
        await verify_project_access(parsed_project_id, user_id, service.session)

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
    "/estimate/{job_id}/create-boq/",
    status_code=201,
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


# ── Enrich estimate with cost database matches ────────────────────────────


@router.post(
    "/estimate/{job_id}/enrich/",
    dependencies=[Depends(RequirePermission("ai.use"))],
)
async def enrich_estimate(
    job_id: uuid.UUID,
    body: dict[str, Any],
    user_id: CurrentUserId,
    session: SessionDep,
) -> dict[str, Any]:
    """Enrich AI estimate items with real cost database matches.

    For each item in a completed AI estimate, performs vector similarity search
    (with text search fallback) against the cost database. Returns matched cost
    items ranked by relevance score, preferring items with matching units.

    Body:
        - region (str, optional): Region filter for cost lookup (e.g. "DE_BERLIN")
        - currency (str, optional): Currency code; empty when unknown

    Returns enriched items with cost database matches and a best_match per item.
    """
    uid = uuid.UUID(user_id)
    region = body.get("region", "")
    currency = body.get("currency", "")

    # 1. Get the estimate job from DB
    from app.modules.ai.repository import AIEstimateJobRepository

    job_repo = AIEstimateJobRepository(session)
    job = await job_repo.get_by_id(job_id)

    # R7 audit: collapse "missing" + "wrong owner" into a single 404
    # surface so the response cannot be used as a job-id oracle. The old
    # 403 distinguished the two cases for any caller with a valid JWT.
    if job is None or str(job.user_id) != str(uid):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=translate("errors.estimate_job_not_found", locale=get_locale()),
        )

    if job.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Estimate job is not completed (status: {job.status})",
        )

    # 3. Get items from job result (can be list directly or {"items": [...]})
    result_data = job.result or []
    if isinstance(result_data, list):
        items: list[dict[str, Any]] = result_data
    else:
        items = result_data.get("items", [])
    if not items:
        return {
            "items": [],
            "region": region,
            "total_matched": 0,
            "total_items": 0,
        }

    # 4. Enrich each item
    from app.modules.costs.repository import CostItemRepository

    cost_repo = CostItemRepository(session)
    enriched_items: list[dict[str, Any]] = []
    total_matched = 0

    for idx, item in enumerate(items):
        description = item.get("description", "")
        item_unit = item.get("unit", "")
        ai_rate = item.get("unit_rate", 0.0) or item.get("rate", 0.0) or 0.0

        matches: list[dict[str, Any]] = []

        # 5a. Try vector search first
        try:
            from app.core.vector import encode_texts, vector_search

            query_vec = encode_texts([description])[0]
            raw_matches = vector_search(query_vec, region=region or None, limit=5)
            for m in raw_matches:
                matches.append(
                    {
                        "code": m.get("code", ""),
                        "description": m.get("description", ""),
                        "unit": m.get("unit", ""),
                        "rate": float(m.get("rate", 0)),
                        "region": m.get("region", ""),
                        "score": float(m.get("score", 0)),
                    }
                )
        except Exception as vec_err:
            logger.debug("Vector search unavailable for item %d: %s", idx, vec_err)

        # 5b. If vector search returned nothing, fall back to text search
        if not matches:
            try:
                # Extract meaningful keywords (skip short/common words)
                stop = {"the", "and", "for", "with", "from", "into", "per", "all"}
                keywords = [w for w in description.lower().split() if len(w) > 2 and w not in stop][:5]

                if keywords:
                    # Search each keyword separately with OR
                    # Try with region first, then without if no results
                    for kw in keywords:
                        kw_results, _, _ = await cost_repo.search(
                            q=kw,
                            region=region or None,
                            limit=3,
                        )
                        # Fallback: search without region filter
                        if not kw_results and region:
                            kw_results, _, _ = await cost_repo.search(
                                q=kw,
                                limit=3,
                            )
                        for ci in kw_results:
                            # Avoid duplicates
                            if not any(m["code"] == ci.code for m in matches):
                                # Score: count how many keywords match description
                                desc_lower = (ci.description or "").lower()
                                kw_hits = sum(1 for k in keywords if k in desc_lower)
                                score = min(0.9, 0.3 + kw_hits * 0.15)
                                matches.append(
                                    {
                                        "code": ci.code,
                                        "description": (ci.description or "")[:200],
                                        "unit": ci.unit or "",
                                        "rate": float(ci.rate) if ci.rate else 0.0,
                                        "region": ci.region or "",
                                        "score": score,
                                    }
                                )
                    # Keep top 5
                    matches.sort(key=lambda m: m["score"], reverse=True)
                    matches = matches[:5]
            except Exception as txt_err:
                logger.warning("Text search failed for item %d (%s): %s", idx, description[:30], txt_err)

        # 5c. Prefer matches with the same unit — boost their score
        if item_unit:
            for m in matches:
                if m["unit"].lower() == item_unit.lower():
                    m["score"] = min(1.0, m["score"] + 0.05)

        # Sort by score descending
        matches.sort(key=lambda m: m["score"], reverse=True)

        # Determine best match
        best_match = matches[0] if matches else None
        if best_match:
            total_matched += 1

        enriched_items.append(
            {
                "index": idx,
                "description": description,
                "unit": item_unit,
                "ai_rate": float(ai_rate),
                "matches": matches,
                "best_match": best_match,
            }
        )

    logger.info(
        "Enriched estimate job %s: %d/%d items matched",
        job_id,
        total_matched,
        len(items),
    )

    return {
        "items": enriched_items,
        "region": region,
        "total_matched": total_matched,
        "total_items": len(items),
    }


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

    # R7 audit: collapse missing-vs-wrong-owner into 404 (no enumeration
    # oracle for job UUIDs).
    if job is None or str(job.user_id) != str(uid):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=translate("errors.estimate_job_not_found", locale=get_locale()),
        )

    return _build_job_response(job)


# ── AI Cost Advisor chat ──────────────────────────────────────────────────


@router.post(
    "/advisor/chat/",
    dependencies=[Depends(RequirePermission("ai.estimate"))],
)
async def advisor_chat(
    body: dict,
    session: SessionDep,
    user_id: CurrentUserId,
    response: Response,
    _remaining: int = Depends(check_ai_rate_limit),
) -> dict:
    """AI Cost Advisor — answer questions about costs using the cost database.

    Body: ``{message: str, project_id?: str, region?: str}``

    Steps:
        1. Search cost DB for relevant items (vector search if available, text fallback)
        2. Build context from found items
        3. Call AI with context + user question
        4. Return structured answer with source references
    """
    response.headers["X-RateLimit-Remaining"] = str(_remaining)
    message = body.get("message", "").strip()
    if not message:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Message is required")

    project_id = body.get("project_id")
    region = body.get("region", "")
    locale = body.get("locale", "en")
    history: list[dict] = body.get("history", []) or []

    # R7 audit: when project_id is supplied (used to fetch project
    # name / region / currency below) we must verify the caller can
    # access it. Without the guard, a user with only ai.estimate could
    # probe arbitrary project UUIDs and exfiltrate name/region/currency
    # via the advisor reply text (the system prompt embeds them).
    parsed_project_id: uuid.UUID | None = None
    if project_id:
        try:
            parsed_project_id = uuid.UUID(str(project_id))
        except (ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid project_id: {project_id}",
            ) from exc
        await verify_project_access(parsed_project_id, user_id, session)

    # 1. Search cost database for relevant items
    from sqlalchemy import or_, select

    from app.modules.costs.models import CostItem

    context_items: list[dict] = []

    # Try vector search first
    try:
        from app.core.vector import encode_texts, vector_search

        query_vector = encode_texts([message])[0]
        results = vector_search(query_vector, region=region or None, limit=8)
        context_items = results
    except Exception:
        # Fallback: multi-keyword text search (use all significant words)
        keywords = [w for w in message.split() if len(w) > 2]
        if keywords:
            conditions = [CostItem.description.ilike(f"%{kw}%") for kw in keywords[:5]]
            stmt = select(CostItem).where(CostItem.is_active.is_(True), or_(*conditions)).limit(8)
            result = await session.execute(stmt)
            items = result.scalars().all()
            for item in items:
                context_items.append(
                    {
                        "code": item.code,
                        "description": item.description[:200],
                        "unit": item.unit,
                        "rate": float(item.rate) if item.rate else 0,
                        "region": item.region or "",
                    }
                )

    # 2. Build context from found items
    if context_items:
        items_text = "\n".join(
            [
                f"- {it.get('code', '')}: {it.get('description', '')[:100]} | "
                f"{it.get('unit', '')} | {it.get('rate', 0)} | {it.get('region', '')}"
                for it in context_items[:8]
            ]
        )
        context = (
            f"Cost database results (may or may not be relevant — use only if they "
            f"actually match the user's question):\n{items_text}"
        )
    else:
        context = "No cost items found in the database. Use your general knowledge."

    # 3. Get project context if provided
    project_context = ""
    if project_id:
        try:
            from app.modules.projects.models import Project

            proj = await session.get(Project, project_id)
            if proj:
                project_context = f"\nProject: {proj.name}, Region: {proj.region}, Currency: {proj.currency}"
        except Exception:
            logger.debug("AI advisor: project context lookup failed", exc_info=True)

    # 4. Build prompt — locale-aware, allows general knowledge
    _LOCALE_NAMES = {
        "en": "English",
        "de": "German",
        "fr": "French",
        "es": "Spanish",
        "pt": "Portuguese",
        "ru": "Russian",
        "zh": "Chinese",
        "ar": "Arabic",
        "hi": "Hindi",
        "tr": "Turkish",
        "it": "Italian",
        "nl": "Dutch",
        "pl": "Polish",
        "cs": "Czech",
        "ja": "Japanese",
        "ko": "Korean",
        "sv": "Swedish",
        "no": "Norwegian",
        "da": "Danish",
        "fi": "Finnish",
        "bg": "Bulgarian",
    }
    lang_name = _LOCALE_NAMES.get(locale, "English")

    system_prompt = (
        f"You are an AI Cost Advisor for construction projects — a smart, interactive "
        f"assistant that helps estimators with costs, materials, methods, and regulations.\n\n"
        f"CRITICAL: You MUST respond ONLY in {lang_name}. Every word must be in {lang_name}.\n\n"
        f"## Conversation style\n"
        f"You are having a DIALOGUE, not writing a report. Be smart and interactive:\n"
        f"- If the user's question is AMBIGUOUS or BROAD (e.g., 'compare concrete prices', "
        f"'how much does plaster cost', 'typical rates for electricians'), DO NOT guess "
        f"a region or context. Instead, ask a SHORT clarifying question with options.\n"
        f"  Example: User asks 'Compare concrete prices by region'\n"
        f"  Good response: 'I can compare concrete prices! To give you accurate data, "
        f"please tell me:\\n1. Which regions interest you? (e.g., DACH, UK, Middle East, "
        f"North America, or specific countries)\\n2. What concrete grade? (C20, C25, C30, etc.)\\n"
        f"3. Ready-mix or precast?\\nOr just tell me your project location and I will suggest "
        f"relevant comparisons.'\n"
        f"- If the user provides enough context (specific region, material, project), "
        f"answer directly with data.\n"
        f"- If a project is active (see project context below), use its region/currency "
        f"as default context — but still confirm if the question is broad.\n\n"
        f"## Data rules\n"
        f"- Use cost database items when they are relevant to the question\n"
        f"- IGNORE database items that are clearly unrelated\n"
        f"- Supplement with your general construction knowledge\n"
        f"- When providing prices, ALWAYS specify: region, currency, unit, and whether "
        f"it includes labor/materials/both\n"
        f"- Give ranges (min–max) not single numbers\n"
        f"- Suggest cost-saving alternatives when appropriate\n"
        f"- Format with markdown: use **bold** for key numbers, bullet lists for comparisons\n"
        f"- Never say 'data not available' — either ask for clarification or provide "
        f"general estimates with a note about accuracy"
    )

    # Build conversation history into prompt for context continuity.
    # Hard cap on the assembled history block: 10 messages × 500 chars is
    # 5 KB upper bound, but small-context providers (Mistral, Cohere) start
    # rejecting prompts past ~4 KB once you add system + context + project
    # context. 4000 chars is a conservative ceiling that fits all providers.
    history_text = ""
    if history:
        history_lines = []
        running_chars = 0
        HISTORY_CHAR_BUDGET = 4000
        for h in history[-10:]:  # Last 10 messages max
            role = h.get("role", "user")
            content = h.get("content", "")[:500]  # Truncate long messages
            prefix = "User" if role == "user" else "Assistant"
            line = f"{prefix}: {content}"
            if running_chars + len(line) > HISTORY_CHAR_BUDGET:
                break
            history_lines.append(line)
            running_chars += len(line) + 1  # +1 for newline
        if history_lines:
            history_text = "Previous conversation:\n" + "\n".join(history_lines) + "\n\n---\n\n"

    user_prompt = (
        f"{context}{project_context}\n\n"
        f"{history_text}"
        f"User message: {message}\n\n"
        f"Respond in {lang_name}. This is a continuing conversation — use the history above "
        f"for context. The user may be answering your previous question or selecting an option "
        f"you offered. If the user selected an option, answer that specific topic directly "
        f"with data. Do NOT ask the same clarifying questions again."
    )

    # 5. Call AI (reuse existing settings/provider resolution)
    service = _get_service(session)
    uid = uuid.UUID(user_id)
    settings = await service.settings_repo.get_by_user_id(uid)

    used_db = bool(context_items)
    try:
        provider, api_key, model_override = resolve_provider_key_model(settings)
        text, _tokens = await call_ai(
            provider=provider,
            api_key=api_key,
            system=system_prompt,
            prompt=user_prompt,
            max_tokens=1500,
            model=model_override,
        )
        answer = text
    except (ValueError, Exception) as exc:
        # Provider error bodies (especially from third-party LLM APIs) can
        # echo back masked key prefixes, org IDs, or stale CORS headers.
        # We log the full error for ops, but only show the user a generic
        # localized fallback — never the raw upstream message.
        logger.warning(
            "advisor_chat: AI call failed for user=%s provider-error=%r",
            user_id, exc,
        )
        # ai_client raises a sanitized ValueError (only the model id +
        # truncated provider text — no credentials) when the provider
        # rejects the *model name*. Surface a clear, localized, actionable
        # message in that case so users with a stale model id (issue #129)
        # know to change it instead of seeing a vague "not configured".
        is_model_problem = isinstance(exc, ValueError) and (
            "set the model name" in str(exc) or "denied access to model" in str(exc)
        )
        if is_model_problem:
            _model_msgs = {
                "ru": "Имя модели ИИ устарело или недоступно. Откройте Настройки > ИИ и укажите актуальное имя модели.",
                "de": "Der KI-Modellname ist veraltet oder nicht verfügbar. Öffnen Sie Einstellungen > KI und geben Sie einen aktuellen Modellnamen ein.",
                "fr": "Le nom du modèle d'IA est obsolète ou indisponible. Ouvrez Paramètres > IA et indiquez un nom de modèle valide.",
                "es": "El nombre del modelo de IA está desactualizado o no disponible. Abra Configuración > IA e indique un nombre de modelo válido.",
            }
            answer = _model_msgs.get(
                locale,
                "The AI model name is outdated or unavailable. Open Settings > AI "
                "and set a currently valid model name for your provider.",
            )
        else:
            _err_msgs = {
                "ru": "ИИ не настроен. Пожалуйста, добавьте API-ключ в Настройках.",
                "de": "KI nicht konfiguriert. Bitte fügen Sie Ihren API-Schlüssel in den Einstellungen hinzu.",
                "fr": "IA non configurée. Veuillez ajouter votre clé API dans les Paramètres.",
                "es": "IA no configurada. Agregue su clave API en Configuración.",
            }
            answer = _err_msgs.get(locale, "AI is not configured. Please set up an AI provider in Settings.")
        used_db = False

    # 6. Build source references — only include if items seem relevant
    sources = (
        [
            {
                "code": it.get("code", ""),
                "description": it.get("description", "")[:80],
                "rate": it.get("rate", 0),
                "unit": it.get("unit", ""),
                "region": it.get("region", ""),
            }
            for it in context_items[:5]
        ]
        if used_db
        else []
    )

    # If AI didn't reference any sources in its answer, don't show them
    if sources and answer:
        # Check if the AI actually used any source codes in its response
        codes_in_answer = any(it.get("code", "xxx") in answer for it in context_items[:5])
        if not codes_in_answer:
            sources = []  # AI ignored the DB items — don't show irrelevant sources

    return {
        "answer": answer,
        "sources": sources,
        "query": message,
    }
