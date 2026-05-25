"""‌⁠‍AI Estimation service — business logic for AI-powered BOQ generation.

Stateless service layer. Handles:
- Per-user AI settings (get, create, update)
- Quick text-based estimation (description -> AI -> BOQ items)
- Photo-based estimation (image -> AI Vision -> BOQ items)
- Creating real BOQ from AI estimate results
- Job tracking with status, timing, and token usage
"""

import base64
import logging
import time
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ai.pricing import estimate_cost_usd
from app.core.events import event_bus
from app.core.i18n import get_locale
from app.core.validation.messages import translate

_logger_ev = __import__("logging").getLogger(__name__ + ".events")


async def _safe_publish(name: str, data: dict, source_module: str = "") -> None:
    try:
        event_bus.publish_detached(name, data, source_module=source_module)
    except Exception:
        _logger_ev.debug("Event publish skipped: %s", name)


from app.modules.ai.ai_client import call_ai, extract_json, resolve_provider_key_model
from app.modules.ai.models import AIEstimateJob, AISettings
from app.modules.ai.prompts import (
    CAD_IMPORT_PROMPT,
    PHOTO_ESTIMATE_PROMPT,
    SMART_IMPORT_PROMPT,
    SMART_IMPORT_VISION_PROMPT,
    SYSTEM_PROMPT,
    TEXT_ESTIMATE_PROMPT,
    fence_user_content,
    sanitize_user_text,
)
from app.modules.ai.repository import AIEstimateJobRepository, AISettingsRepository
from app.modules.ai.schemas import (
    AISettingsResponse,
    AISettingsUpdate,
    CreateBOQFromEstimateRequest,
    EstimateItem,
    EstimateJobResponse,
    QuickEstimateRequest,
)

logger = logging.getLogger(__name__)


async def _resolve_project_currency(
    session: AsyncSession,
    project_id: uuid.UUID | None,
) -> str:
    """Look up the project's default currency.

    Returns empty string when no project_id is supplied or the project is
    missing — callers fall back to a literal default for prompt rendering.
    Inline import keeps the AI module decoupled from projects at module level.
    """
    if project_id is None:
        return ""
    from sqlalchemy import select

    from app.modules.projects.models import Project

    project = (
        await session.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if project is None:
        return ""
    return project.currency or ""


def _validate_items(raw_items: Any) -> list[dict[str, Any]]:
    """‌⁠‍Validate and clean AI-generated work items.

    Filters out invalid entries, normalises fields, and computes totals.

    Args:
        raw_items: Parsed JSON (expected to be a list of dicts).

    Returns:
        List of validated item dicts.
    """
    if not isinstance(raw_items, list):
        return []

    valid: list[dict[str, Any]] = []
    for idx, item in enumerate(raw_items):
        if not isinstance(item, dict):
            continue

        description = str(item.get("description", "")).strip()
        if len(description) < 3:
            continue

        try:
            quantity = float(item.get("quantity", 0))
        except (ValueError, TypeError):
            quantity = 0.0

        try:
            unit_rate = float(item.get("unit_rate", 0))
        except (ValueError, TypeError):
            unit_rate = 0.0

        if quantity <= 0 or quantity > 10_000_000:
            continue

        unit = str(item.get("unit", "m2")).strip()
        if not unit:
            unit = "m2"

        category = str(item.get("category", "General")).strip()
        if not category:
            category = "General"

        ordinal = str(item.get("ordinal", "")).strip()
        if not ordinal:
            # Auto-generate ordinal
            section = (idx // 10) + 1
            position = (idx % 10) + 1
            ordinal = f"{section:02d}.01.{position:04d}"

        classification = item.get("classification", {})
        if not isinstance(classification, dict):
            classification = {}

        total = round(quantity * unit_rate, 2)

        valid.append(
            {
                "ordinal": ordinal,
                "description": description,
                "unit": unit,
                "quantity": round(quantity, 2),
                "unit_rate": round(unit_rate, 2),
                "total": total,
                "classification": classification,
                "category": category,
            }
        )

    return valid


def _build_settings_response(settings: AISettings) -> AISettingsResponse:
    """‌⁠‍Build an AISettingsResponse from an AISettings ORM instance.

    A key is only reported as "set" when it is both present *and* decryptable
    with the current backend encryption key. If the ciphertext was written
    under a rotated JWT_SECRET the key is functionally useless — surfacing it
    as "configured" would make the Settings UI show "Key configured" while
    every chat/estimate call fails with a decrypt error.
    """
    from app.core.crypto import decrypt_secret
    from app.modules.ai.ai_client import DEFAULT_MODELS

    def _usable(value: Any) -> bool:
        return bool(decrypt_secret(value)) if value else False

    meta = settings.metadata_ or {}
    raw_overrides = meta.get("model_overrides") if isinstance(meta, dict) else None
    model_overrides: dict[str, str] = {}
    if isinstance(raw_overrides, dict):
        # Only surface non-empty string overrides.
        model_overrides = {
            str(k): str(v).strip()
            for k, v in raw_overrides.items()
            if isinstance(v, str) and v.strip()
        }

    # Read custom base URLs for local providers from metadata_
    raw_ollama_base_url = meta.get("ollama_base_url") if isinstance(meta, dict) else None
    raw_vllm_base_url = meta.get("vllm_base_url") if isinstance(meta, dict) else None
    ollama_base_url = str(raw_ollama_base_url).strip() if isinstance(raw_ollama_base_url, str) and raw_ollama_base_url.strip() else None
    vllm_base_url = str(raw_vllm_base_url).strip() if isinstance(raw_vllm_base_url, str) and raw_vllm_base_url.strip() else None

    return AISettingsResponse(
        id=settings.id,
        user_id=settings.user_id,
        anthropic_api_key_set=_usable(settings.anthropic_api_key),
        openai_api_key_set=_usable(settings.openai_api_key),
        gemini_api_key_set=_usable(settings.gemini_api_key),
        openrouter_api_key_set=_usable(settings.openrouter_api_key),
        mistral_api_key_set=_usable(settings.mistral_api_key),
        groq_api_key_set=_usable(settings.groq_api_key),
        deepseek_api_key_set=_usable(settings.deepseek_api_key),
        together_api_key_set=_usable(getattr(settings, "together_api_key", None)),
        fireworks_api_key_set=_usable(getattr(settings, "fireworks_api_key", None)),
        perplexity_api_key_set=_usable(getattr(settings, "perplexity_api_key", None)),
        cohere_api_key_set=_usable(getattr(settings, "cohere_api_key", None)),
        ai21_api_key_set=_usable(getattr(settings, "ai21_api_key", None)),
        xai_api_key_set=_usable(getattr(settings, "xai_api_key", None)),
        zhipu_api_key_set=_usable(getattr(settings, "zhipu_api_key", None)),
        baidu_api_key_set=_usable(getattr(settings, "baidu_api_key", None)),
        yandex_api_key_set=_usable(getattr(settings, "yandex_api_key", None)),
        gigachat_api_key_set=_usable(getattr(settings, "gigachat_api_key", None)),
        kimi_api_key_set=_usable(getattr(settings, "kimi_api_key", None)),
        ollama_base_url=ollama_base_url,
        vllm_base_url=vllm_base_url,
        preferred_model=settings.preferred_model,
        model_overrides=model_overrides,
        default_models=dict(DEFAULT_MODELS),
        metadata_=settings.metadata_ or {},
        created_at=settings.created_at,
        updated_at=settings.updated_at,
    )


def _build_job_response(job: AIEstimateJob) -> EstimateJobResponse:
    """Build an EstimateJobResponse from an AIEstimateJob ORM instance."""
    from decimal import Decimal

    items: list[EstimateItem] = []
    grand_total: Decimal = Decimal("0")

    if job.result and isinstance(job.result, list):
        for item_data in job.result:
            if not isinstance(item_data, dict):
                continue
            ei = EstimateItem(
                ordinal=str(item_data.get("ordinal", "")),
                description=str(item_data.get("description", "")),
                unit=str(item_data.get("unit", "m2")),
                quantity=float(item_data.get("quantity", 0)),
                unit_rate=Decimal(str(item_data.get("unit_rate", 0) or 0)),
                total=float(item_data.get("total", 0)),
                classification=item_data.get("classification", {}),
                category=str(item_data.get("category", "General")),
            )
            items.append(ei)
            grand_total += Decimal(str(ei.total))

    return EstimateJobResponse(
        id=job.id,
        user_id=job.user_id,
        project_id=job.project_id,
        input_type=job.input_type,
        input_text=job.input_text,
        input_filename=job.input_filename,
        status=job.status,
        items=items,
        error_message=job.error_message,
        model_used=job.model_used,
        tokens_used=job.tokens_used,
        duration_ms=job.duration_ms,
        cost_usd_estimate=Decimal(str(getattr(job, "cost_usd_estimate", 0.0) or 0.0)),
        grand_total=grand_total.quantize(Decimal("0.01")),
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


class AIService:
    """Business logic for AI estimation operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings_repo = AISettingsRepository(session)
        self.job_repo = AIEstimateJobRepository(session)

    # ── Settings operations ──────────────────────────────────────────────

    async def get_ai_settings(self, user_id: str) -> AISettingsResponse:
        """Get or create default AI settings for a user.

        Args:
            user_id: Current user's ID (string from JWT).

        Returns:
            AISettingsResponse with masked API keys.
        """
        uid = uuid.UUID(user_id)
        settings = await self.settings_repo.get_by_user_id(uid)

        if settings is None:
            # Create default settings for the user
            settings = AISettings(
                user_id=uid,
                preferred_model="claude-sonnet",
            )
            settings = await self.settings_repo.create(settings)
            logger.info("Created default AI settings for user %s", user_id)

        return _build_settings_response(settings)

    async def update_ai_settings(self, user_id: str, data: AISettingsUpdate) -> AISettingsResponse:
        """Update per-user AI settings (API keys, preferred model).

        Only updates fields that are explicitly provided (not None).

        Args:
            user_id: Current user's ID.
            data: Update payload.

        Returns:
            Updated AISettingsResponse.
        """
        uid = uuid.UUID(user_id)
        settings = await self.settings_repo.get_by_user_id(uid)

        # All API key field names that can be saved
        _API_KEY_FIELDS = [
            "anthropic_api_key",
            "openai_api_key",
            "gemini_api_key",
            "openrouter_api_key",
            "mistral_api_key",
            "groq_api_key",
            "deepseek_api_key",
            "together_api_key",
            "fireworks_api_key",
            "perplexity_api_key",
            "cohere_api_key",
            "ai21_api_key",
            "xai_api_key",
            "zhipu_api_key",
            "baidu_api_key",
            "yandex_api_key",
            "gigachat_api_key",
            "kimi_api_key",
        ]

        from app.core.crypto import encrypt_secret

        def _merge_overrides(
            existing_meta: Any,
            incoming: dict[str, str] | None,
        ) -> dict[str, Any]:
            """Merge model-id overrides into the metadata JSON blob.

            A blank/whitespace value for a provider clears that override
            (falls back to the built-in default). Returns the full new
            metadata dict (other metadata keys are preserved).
            """
            meta: dict[str, Any] = dict(existing_meta) if isinstance(existing_meta, dict) else {}
            current = meta.get("model_overrides")
            overrides: dict[str, str] = dict(current) if isinstance(current, dict) else {}
            for provider, model_id in (incoming or {}).items():
                key = str(provider).strip()
                if not key:
                    continue
                cleaned = str(model_id).strip() if isinstance(model_id, str) else ""
                if cleaned:
                    overrides[key] = cleaned
                else:
                    overrides.pop(key, None)  # blank clears the override
            meta["model_overrides"] = overrides
            return meta

        def _merge_base_urls(
            existing_meta: Any,
            ollama_url: str | None,
            vllm_url: str | None,
        ) -> dict[str, Any]:
            """Merge custom base URLs for local providers into metadata."""
            meta: dict[str, Any] = dict(existing_meta) if isinstance(existing_meta, dict) else {}
            if ollama_url is not None:
                cleaned = ollama_url.strip()
                meta["ollama_base_url"] = cleaned if cleaned else None
            if vllm_url is not None:
                cleaned = vllm_url.strip()
                meta["vllm_base_url"] = cleaned if cleaned else None
            return meta

        if settings is None:
            # Create with provided values (encrypt API keys at rest)
            create_kwargs: dict[str, Any] = {"user_id": uid}
            for key_field in _API_KEY_FIELDS:
                val = getattr(data, key_field, None)
                if val is not None:
                    create_kwargs[key_field] = encrypt_secret(val)
            create_kwargs["preferred_model"] = data.preferred_model or "claude-sonnet"
            if data.model_overrides is not None:
                create_kwargs["metadata_"] = _merge_overrides({}, data.model_overrides)
            meta = create_kwargs.get("metadata_", {})
            if isinstance(meta, dict):
                create_kwargs["metadata_"] = _merge_base_urls(meta, data.ollama_base_url, data.vllm_base_url)
            settings = AISettings(**create_kwargs)
            settings = await self.settings_repo.create(settings)
        else:
            fields: dict[str, Any] = {}
            for key_field in _API_KEY_FIELDS:
                val = getattr(data, key_field, None)
                if val is not None:
                    fields[key_field] = encrypt_secret(val)
            if data.preferred_model is not None:
                fields["preferred_model"] = data.preferred_model
            if data.model_overrides is not None:
                fields["metadata_"] = _merge_overrides(settings.metadata_, data.model_overrides)
            if data.ollama_base_url is not None or data.vllm_base_url is not None:
                existing_meta = fields.get("metadata_", settings.metadata_)
                fields["metadata_"] = _merge_base_urls(existing_meta, data.ollama_base_url, data.vllm_base_url)

            if fields:
                await self.settings_repo.update_fields(settings.id, **fields)

        # Re-fetch to return fresh data
        settings = await self.settings_repo.get_by_user_id(uid)
        if settings is None:
            msg = "Settings not found after update"
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=msg)

        await _safe_publish(
            "ai.settings.updated",
            {"user_id": user_id},
            source_module="oe_ai",
        )

        # Sync custom base URLs for local providers into the global
        # provider config so all subsequent call_ai() calls across the
        # entire app (boq, takeoff, erp_chat, etc.) use the user's URL.
        from app.modules.ai.ai_client import update_provider_config

        update_provider_config(settings.metadata_)

        return _build_settings_response(settings)

    # ── Quick estimate (text -> AI -> BOQ items) ─────────────────────────

    async def quick_estimate(self, user_id: str, request: QuickEstimateRequest) -> EstimateJobResponse:
        """Generate a BOQ estimate from a text description using AI.

        Args:
            user_id: Current user's ID.
            request: Estimation request with description and optional context.

        Returns:
            EstimateJobResponse with generated items.
        """
        uid = uuid.UUID(user_id)
        settings = await self.settings_repo.get_by_user_id(uid)

        # Resolve which AI provider / model to use
        try:
            provider, api_key, model_override = resolve_provider_key_model(settings)
        except ValueError as exc:
            logger.warning("AI provider config error for user %s: %s", user_id, exc)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No AI provider configured. Please add an API key in Settings.",
            ) from exc

        # Create the job record
        job = AIEstimateJob(
            user_id=uid,
            project_id=request.project_id,
            input_type="text",
            input_text=request.description,
            status="processing",
        )
        job = await self.job_repo.create(job)
        job_id = job.id  # Save before expire_all() in update_fields

        # Build prompt with context
        extra_parts: list[str] = []
        if request.project_type:
            extra_parts.append(f"Building type: {request.project_type}")
        if request.area_m2:
            extra_parts.append(f"Total area: {request.area_m2} m2")
        if request.location:
            extra_parts.append(f"Location: {request.location}")
        extra_context = "\n".join(extra_parts)

        # Currency precedence: explicit request → project default →
        # empty string (LLM prompts tolerate a blank currency token).
        currency = (
            request.currency
            or await _resolve_project_currency(self.session, request.project_id)
            or ""
        )
        # No standard fallback — empty token signals "no preferred classification"
        # so the LLM is steered by the project's explicit setting (or absence).
        standard_val = request.standard or ""

        # Audit AI1: hard-strip control chars + truncate any free-form
        # user text before it reaches the LLM, so attackers can't smuggle
        # role-switch escapes (\x1b, raw bidi marks, etc.) through the
        # description / extra-context fields.
        prompt = TEXT_ESTIMATE_PROMPT.format(
            description=sanitize_user_text(request.description, max_len=5000),
            extra_context=sanitize_user_text(extra_context, max_len=2000),
            currency=sanitize_user_text(currency, max_len=20),
            standard=sanitize_user_text(standard_val, max_len=64),
        )

        # Call AI
        start_time = time.monotonic()
        try:
            raw_response, tokens = await call_ai(
                provider=provider,
                api_key=api_key,
                system=SYSTEM_PROMPT,
                prompt=prompt,
                model=model_override,
            )
            duration_ms = int((time.monotonic() - start_time) * 1000)

            # Parse response
            parsed = extract_json(raw_response)
            items = _validate_items(parsed)

            if not items:
                await self.job_repo.update_fields(
                    job_id,
                    status="failed",
                    error_message="AI returned no valid work items. Please try a more detailed description.",
                    model_used=provider,
                    tokens_used=tokens,
                    cost_usd_estimate=float(estimate_cost_usd(provider, int(tokens or 0))),
                    duration_ms=duration_ms,
                )
                self.session.expunge(job)
                job = await self.job_repo.get_by_id(job_id)
                if job is None:
                    msg = "Job not found after update"
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=msg,
                    )
                return _build_job_response(job)

            # Update job with results
            await self.job_repo.update_fields(
                job_id,
                status="completed",
                result=items,
                model_used=provider,
                tokens_used=tokens,
                cost_usd_estimate=float(estimate_cost_usd(provider, int(tokens or 0))),
                duration_ms=duration_ms,
            )

        except HTTPException:
            raise
        except ValueError as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            error_msg = str(exc)
            logger.warning("Quick estimate user error for %s: %s", user_id, exc)

            await self.job_repo.update_fields(
                job_id,
                status="failed",
                error_message=error_msg,
                model_used=provider,
                duration_ms=duration_ms,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="AI estimation failed due to invalid input. Please check your request.",
            ) from exc
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            error_msg = f"AI estimation failed: {exc}"
            logger.exception("Quick estimate failed for user %s: %s", user_id, exc)

            await self.job_repo.update_fields(
                job_id,
                status="failed",
                error_message=error_msg,
                model_used=provider,
                duration_ms=duration_ms,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="AI service temporarily unavailable. Please try again.",
            ) from exc

        # Re-fetch the completed job
        self.session.expunge(job)
        job = await self.job_repo.get_by_id(job_id)
        if job is None:
            msg = "Job not found after completion"
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=msg)

        await _safe_publish(
            "ai.estimate.completed",
            {
                "job_id": str(job.id),
                "user_id": user_id,
                "input_type": "text",
                "items_count": len(items),
            },
            source_module="oe_ai",
        )

        logger.info(
            "Quick estimate completed: job=%s, items=%d, tokens=%d, duration=%dms",
            job.id,
            len(items),
            tokens,
            duration_ms,
        )

        return _build_job_response(job)

    # ── Photo estimate (image -> AI Vision -> BOQ items) ─────────────────

    async def photo_estimate(
        self,
        user_id: str,
        image_bytes: bytes,
        filename: str,
        media_type: str = "image/jpeg",
        location: str | None = None,
        currency: str | None = None,
        standard: str | None = None,
        project_id: uuid.UUID | None = None,
    ) -> EstimateJobResponse:
        """Generate a BOQ estimate from a building photo using AI Vision.

        Args:
            user_id: Current user's ID.
            image_bytes: Raw image file content.
            filename: Original filename.
            media_type: Image MIME type.
            location: Optional location for pricing context.
            currency: Optional currency code.
            standard: Optional classification standard.
            project_id: Optional project to link to.

        Returns:
            EstimateJobResponse with generated items.
        """
        uid = uuid.UUID(user_id)
        settings = await self.settings_repo.get_by_user_id(uid)

        try:
            provider, api_key, model_override = resolve_provider_key_model(settings)
        except ValueError as exc:
            logger.warning("AI provider config error for user %s: %s", user_id, exc)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No AI provider configured. Please add an API key in Settings.",
            ) from exc

        # Create job record
        job = AIEstimateJob(
            user_id=uid,
            project_id=project_id,
            input_type="photo",
            input_filename=filename,
            status="processing",
        )
        job = await self.job_repo.create(job)
        job_id = job.id  # Save before expire_all() in update_fields

        # Build prompt — currency: explicit arg → project default → blank.
        currency_val = (
            currency
            or await _resolve_project_currency(self.session, project_id)
            or ""
        )
        # No standard / location fallback — explicit-only avoids steering
        # the LLM toward DIN 276 / Europe on non-DACH projects.
        standard_val = standard or ""
        location_val = location or ""

        # Audit AI1: sanitize any free-form user strings reaching the LLM.
        prompt = PHOTO_ESTIMATE_PROMPT.format(
            location=sanitize_user_text(location_val, max_len=200),
            currency=sanitize_user_text(currency_val, max_len=20),
            standard=sanitize_user_text(standard_val, max_len=64),
        )

        # Encode image
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        # Call AI with vision
        start_time = time.monotonic()
        try:
            raw_response, tokens = await call_ai(
                provider=provider,
                api_key=api_key,
                system=SYSTEM_PROMPT,
                prompt=prompt,
                image_base64=image_b64,
                image_media_type=media_type,
                model=model_override,
            )
            duration_ms = int((time.monotonic() - start_time) * 1000)

            parsed = extract_json(raw_response)
            items = _validate_items(parsed)

            if not items:
                await self.job_repo.update_fields(
                    job_id,
                    status="failed",
                    error_message="AI could not extract work items from this photo. Please try a clearer image.",
                    model_used=provider,
                    tokens_used=tokens,
                    cost_usd_estimate=float(estimate_cost_usd(provider, int(tokens or 0))),
                    duration_ms=duration_ms,
                )
                self.session.expunge(job)
                job = await self.job_repo.get_by_id(job_id)
                if job is None:
                    msg = "Job not found after update"
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=msg,
                    )
                return _build_job_response(job)

            await self.job_repo.update_fields(
                job_id,
                status="completed",
                result=items,
                model_used=provider,
                tokens_used=tokens,
                cost_usd_estimate=float(estimate_cost_usd(provider, int(tokens or 0))),
                duration_ms=duration_ms,
            )

        except HTTPException:
            raise
        except ValueError as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            error_msg = str(exc)
            logger.warning("Photo estimate user error for %s: %s", user_id, exc)

            await self.job_repo.update_fields(
                job_id,
                status="failed",
                error_message=error_msg,
                model_used=provider,
                duration_ms=duration_ms,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="AI photo analysis failed due to invalid input. Please check your request.",
            ) from exc
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            error_msg = f"AI photo analysis failed: {exc}"
            logger.exception("Photo estimate failed for user %s: %s", user_id, exc)

            await self.job_repo.update_fields(
                job_id,
                status="failed",
                error_message=error_msg,
                model_used=provider,
                duration_ms=duration_ms,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="AI service temporarily unavailable. Please try again.",
            ) from exc

        self.session.expunge(job)
        job = await self.job_repo.get_by_id(job_id)
        if job is None:
            msg = "Job not found after completion"
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=msg)

        await _safe_publish(
            "ai.estimate.completed",
            {
                "job_id": str(job.id),
                "user_id": user_id,
                "input_type": "photo",
                "items_count": len(items),
            },
            source_module="oe_ai",
        )

        logger.info(
            "Photo estimate completed: job=%s, items=%d, tokens=%d, duration=%dms",
            job.id,
            len(items),
            tokens,
            duration_ms,
        )

        return _build_job_response(job)

    # ── Universal file estimate ──────────────────────────────────────────

    async def file_estimate(
        self,
        user_id: str,
        content: bytes,
        filename: str,
        ext: str,
        category: str,
        location: str | None = None,
        currency: str | None = None,
        standard: str | None = None,
        project_id: uuid.UUID | None = None,
    ) -> EstimateJobResponse:
        """Generate a BOQ estimate from any file type using AI.

        Routes to the appropriate extraction method based on file category,
        then sends extracted data to the AI for BOQ generation.

        Args:
            user_id: Current user's ID.
            content: Raw file bytes.
            filename: Original filename.
            ext: Lowercase extension (e.g. "pdf", "rvt").
            category: File category ("pdf", "excel", "csv", "cad", "image").
            location: Optional location for pricing context.
            currency: Optional currency code.
            standard: Optional classification standard.
            project_id: Optional project to link to.

        Returns:
            EstimateJobResponse with generated items.
        """
        uid = uuid.UUID(user_id)
        settings = await self.settings_repo.get_by_user_id(uid)

        try:
            provider, api_key, model_override = resolve_provider_key_model(settings)
        except ValueError as exc:
            logger.warning("AI provider config error for user %s: %s", user_id, exc)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No AI provider configured. Please add an API key in Settings.",
            ) from exc

        # Create job record
        job = AIEstimateJob(
            user_id=uid,
            project_id=project_id,
            input_type=category,
            input_filename=filename,
            status="processing",
        )
        job = await self.job_repo.create(job)
        job_id = job.id  # Save before expire_all() in update_fields

        # Currency: explicit arg → project default → blank token.
        currency_val = (
            currency
            or await _resolve_project_currency(self.session, project_id)
            or ""
        )
        # No region/standard steering — empty tokens let the LLM rely on
        # the file's content rather than defaulting to DACH / DIN 276.
        standard_val = standard or ""
        location_val = location or ""

        # ── Extract content based on file category ──
        extracted_text = ""
        image_b64: str | None = None
        image_mime: str | None = None
        cad_elements: int | None = None
        cad_format: str | None = None

        try:
            if category == "pdf":
                from app.modules.boq.router import _extract_from_pdf

                result = _extract_from_pdf(content)
                extracted_text = result.get("text", "")

            elif category == "excel":
                from app.modules.boq.router import _extract_from_excel_for_smart

                result = _extract_from_excel_for_smart(content)
                if result.get("structured") and result.get("rows"):
                    # Format structured rows as text for AI
                    rows = result["rows"]
                    lines = []
                    for r in rows:
                        parts = [
                            r.get("ordinal", ""),
                            r.get("description", ""),
                            r.get("unit", ""),
                            str(r.get("quantity", "")),
                            str(r.get("unit_rate", "")),
                        ]
                        lines.append("\t".join(parts))
                    extracted_text = "Pos\tDescription\tUnit\tQty\tRate\n" + "\n".join(lines)
                else:
                    extracted_text = result.get("text", "")

            elif category == "csv":
                from app.modules.boq.router import _extract_from_csv_for_smart

                result = _extract_from_csv_for_smart(content)
                if result.get("structured") and result.get("rows"):
                    rows = result["rows"]
                    lines = []
                    for r in rows:
                        parts = [
                            r.get("ordinal", ""),
                            r.get("description", ""),
                            r.get("unit", ""),
                            str(r.get("quantity", "")),
                            str(r.get("unit_rate", "")),
                        ]
                        lines.append("\t".join(parts))
                    extracted_text = "Pos\tDescription\tUnit\tQty\tRate\n" + "\n".join(lines)
                else:
                    extracted_text = result.get("text", "")

            elif category == "cad":
                from app.modules.boq.router import _extract_from_cad

                result = await _extract_from_cad(content, ext, filename)
                extracted_text = result.get("text", "")
                cad_elements = result.get("cad_elements")
                cad_format = result.get("cad_format", ext)

                if result.get("cad_no_converter"):
                    # No converter installed — return helpful error
                    await self.job_repo.update_fields(
                        job_id,
                        status="failed",
                        error_message=(
                            f"DDC converter for .{ext} files is not installed. "
                            f"Go to Quantities page to install the converter module."
                        ),
                        model_used=provider,
                        duration_ms=0,
                    )
                    self.session.expunge(job)
                    job = await self.job_repo.get_by_id(job_id)
                    if job is None:
                        raise HTTPException(status_code=404, detail=translate("errors.estimate_job_not_found", locale=get_locale()))
                    return _build_job_response(job)

            elif category == "image":
                from app.modules.boq.router import _extract_from_image

                result = _extract_from_image(content, ext)
                image_b64 = result.get("image_base64")
                image_mime = result.get("mime", "image/jpeg")

        except Exception as exc:
            logger.warning("File extraction failed for %s: %s", filename, exc)
            await self.job_repo.update_fields(
                job_id,
                status="failed",
                error_message=f"Failed to extract content from file: {exc}",
                model_used=provider,
                duration_ms=0,
            )
            self.session.expunge(job)
            job = await self.job_repo.get_by_id(job_id)
            if job is None:
                raise HTTPException(status_code=404, detail=translate("errors.estimate_job_not_found", locale=get_locale()))
            return _build_job_response(job)

        # ── Choose prompt and call AI ──
        start_time = time.monotonic()
        try:
            if category == "cad":
                # Audit AI1: wrap extracted CAD/element data in the
                # "treat as data not instructions" fence so a malicious
                # element description in the model can't issue commands.
                prompt = CAD_IMPORT_PROMPT.format(
                    text=fence_user_content(extracted_text),
                    currency=sanitize_user_text(currency_val, max_len=20),
                )
                raw_response, tokens = await call_ai(
                    provider=provider,
                    api_key=api_key,
                    system=SYSTEM_PROMPT,
                    prompt=prompt,
                    model=model_override,
                )
            elif image_b64:
                # Audit AI1: filename is user-controlled — sanitize before
                # interpolation.
                prompt = SMART_IMPORT_VISION_PROMPT.format(
                    filename=sanitize_user_text(filename, max_len=255),
                )
                raw_response, tokens = await call_ai(
                    provider=provider,
                    api_key=api_key,
                    system=SYSTEM_PROMPT,
                    prompt=prompt,
                    image_base64=image_b64,
                    image_media_type=image_mime or "image/jpeg",
                    model=model_override,
                )
            else:
                # Audit AI1: filename + extracted text are user-controlled.
                # Fence the text (which carries the heaviest injection risk)
                # and sanitize the filename so neither can break out of the
                # prompt template.
                prompt = SMART_IMPORT_PROMPT.format(
                    filename=sanitize_user_text(filename, max_len=255),
                    text=fence_user_content(extracted_text),
                )
                raw_response, tokens = await call_ai(
                    provider=provider,
                    api_key=api_key,
                    system=SYSTEM_PROMPT,
                    prompt=prompt,
                    model=model_override,
                )

            duration_ms = int((time.monotonic() - start_time) * 1000)

            parsed = extract_json(raw_response)
            items = _validate_items(parsed)

            if not items:
                await self.job_repo.update_fields(
                    job_id,
                    status="failed",
                    error_message="AI returned no valid work items from this file. Try a different file or add more detail.",
                    model_used=provider,
                    tokens_used=tokens,
                    cost_usd_estimate=float(estimate_cost_usd(provider, int(tokens or 0))),
                    duration_ms=duration_ms,
                )
                self.session.expunge(job)
                job = await self.job_repo.get_by_id(job_id)
                if job is None:
                    raise HTTPException(status_code=404, detail=translate("errors.estimate_job_not_found", locale=get_locale()))
                return _build_job_response(job)

            # Store metadata about the file
            meta: dict[str, Any] = {}
            if cad_elements is not None:
                meta["cad_elements"] = cad_elements
            if cad_format:
                meta["cad_format"] = cad_format

            await self.job_repo.update_fields(
                job_id,
                status="completed",
                result=items,
                model_used=provider,
                tokens_used=tokens,
                cost_usd_estimate=float(estimate_cost_usd(provider, int(tokens or 0))),
                duration_ms=duration_ms,
            )

        except HTTPException:
            raise
        except ValueError as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            error_msg = str(exc)
            logger.warning("File estimate user error for %s: %s", user_id, exc)

            await self.job_repo.update_fields(
                job_id,
                status="failed",
                error_message=error_msg,
                model_used=provider,
                duration_ms=duration_ms,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="AI file analysis failed due to invalid input. Please check your request.",
            ) from exc
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            error_msg = f"AI file analysis failed: {exc}"
            logger.exception("File estimate failed for user %s: %s", user_id, exc)

            await self.job_repo.update_fields(
                job_id,
                status="failed",
                error_message=error_msg,
                model_used=provider,
                duration_ms=duration_ms,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="AI service temporarily unavailable. Please try again.",
            ) from exc

        self.session.expunge(job)
        job = await self.job_repo.get_by_id(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=translate("errors.estimate_job_not_found", locale=get_locale()))

        await _safe_publish(
            "ai.estimate.completed",
            {
                "job_id": str(job.id),
                "user_id": user_id,
                "input_type": category,
                "items_count": len(items),
            },
            source_module="oe_ai",
        )

        logger.info(
            "File estimate completed: job=%s, category=%s, items=%d, tokens=%d, duration=%dms",
            job.id,
            category,
            len(items),
            tokens,
            duration_ms,
        )

        return _build_job_response(job)

    # ── Create BOQ from estimate ─────────────────────────────────────────

    async def create_boq_from_estimate(
        self,
        user_id: str,
        job_id: uuid.UUID,
        request: CreateBOQFromEstimateRequest,
    ) -> dict[str, Any]:
        """Save AI estimation results as a real BOQ with positions.

        Takes a completed AI estimate job and creates a BOQ in the specified
        project, with each estimated item becoming a BOQ position.

        Args:
            user_id: Current user's ID.
            job_id: ID of the completed estimate job.
            request: BOQ creation parameters (project_id, name).

        Returns:
            Dict with boq_id, positions_created count, and grand_total.

        Raises:
            HTTPException 404: If job not found.
            HTTPException 400: If job is not completed or has no results.
        """
        uid = uuid.UUID(user_id)
        job = await self.job_repo.get_by_id(job_id)

        # R7 audit: collapse "job missing" + "different owner" into the
        # same 404 surface so the response cannot be used as a job-id
        # oracle by another tenant.
        if job is None or str(job.user_id) != str(uid):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=translate("errors.estimate_job_not_found", locale=get_locale()),
            )

        # R7 audit: the caller can supply ANY ``request.project_id``;
        # without this guard a non-owner could land an AI-generated BOQ
        # inside a project they don't own (silent BOQ injection that
        # bypasses the projects-module RBAC). The shared helper returns
        # 404 on "missing" OR "no access" — identical surface.
        from app.dependencies import verify_project_access

        await verify_project_access(request.project_id, user_id, self.session)

        if job.status != "completed":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Estimate job is not completed (status: {job.status})",
            )

        if not job.result or not isinstance(job.result, list):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Estimate job has no results",
            )

        # Import BOQ service to create the BOQ and positions
        from app.modules.boq.models import BOQ, Position
        from app.modules.boq.repository import BOQRepository, PositionRepository

        boq_repo = BOQRepository(self.session)
        position_repo = PositionRepository(self.session)

        # Create the BOQ
        boq = BOQ(
            project_id=request.project_id,
            name=request.boq_name,
            description=f"Generated by AI from {job.input_type} input",
            status="draft",
            metadata_={"ai_job_id": str(job_id), "ai_model": job.model_used or ""},
        )
        boq = await boq_repo.create(boq)

        # Create positions from estimated items
        grand_total = 0.0
        positions_created = 0

        for sort_idx, item_data in enumerate(job.result):
            if not isinstance(item_data, dict):
                continue

            description = str(item_data.get("description", "")).strip()
            if not description:
                continue

            quantity = float(item_data.get("quantity", 0))
            unit_rate = float(item_data.get("unit_rate", 0))
            total = round(quantity * unit_rate, 2)
            grand_total += total

            position = Position(
                boq_id=boq.id,
                parent_id=None,
                ordinal=str(item_data.get("ordinal", str(sort_idx + 1))),
                description=description,
                unit=str(item_data.get("unit", "m2")),
                quantity=str(quantity),
                unit_rate=str(unit_rate),
                total=str(total),
                classification=item_data.get("classification", {}),
                source="ai_estimate",
                confidence="0.7",
                cad_element_ids=[],
                validation_status="pending",
                metadata_={
                    "ai_job_id": str(job_id),
                    "category": str(item_data.get("category", "")),
                },
                sort_order=sort_idx,
            )
            await position_repo.create(position)
            positions_created += 1

        await _safe_publish(
            "ai.boq.created",
            {
                "boq_id": str(boq.id),
                "job_id": str(job_id),
                "user_id": user_id,
                "project_id": str(request.project_id),
                "positions_count": positions_created,
            },
            source_module="oe_ai",
        )

        logger.info(
            "BOQ created from AI estimate: boq=%s, job=%s, positions=%d, total=%.2f",
            boq.id,
            job_id,
            positions_created,
            grand_total,
        )

        return {
            "boq_id": str(boq.id),
            "positions_created": positions_created,
            "grand_total": round(grand_total, 2),
        }
