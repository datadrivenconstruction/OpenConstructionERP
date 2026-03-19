"""AI Estimation service — business logic for AI-powered BOQ generation.

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

from app.core.events import event_bus
from app.modules.ai.ai_client import call_ai, extract_json, resolve_provider_and_key
from app.modules.ai.models import AIEstimateJob, AISettings
from app.modules.ai.prompts import PHOTO_ESTIMATE_PROMPT, SYSTEM_PROMPT, TEXT_ESTIMATE_PROMPT
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


def _validate_items(raw_items: Any) -> list[dict[str, Any]]:
    """Validate and clean AI-generated work items.

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

        valid.append({
            "ordinal": ordinal,
            "description": description,
            "unit": unit,
            "quantity": round(quantity, 2),
            "unit_rate": round(unit_rate, 2),
            "total": total,
            "classification": classification,
            "category": category,
        })

    return valid


def _build_settings_response(settings: AISettings) -> AISettingsResponse:
    """Build an AISettingsResponse from an AISettings ORM instance.

    Masks API keys — only indicates whether they are set.
    """
    return AISettingsResponse(
        id=settings.id,
        user_id=settings.user_id,
        anthropic_api_key_set=bool(settings.anthropic_api_key),
        openai_api_key_set=bool(settings.openai_api_key),
        gemini_api_key_set=bool(settings.gemini_api_key),
        preferred_model=settings.preferred_model,
        metadata_=settings.metadata_ or {},
        created_at=settings.created_at,
        updated_at=settings.updated_at,
    )


def _build_job_response(job: AIEstimateJob) -> EstimateJobResponse:
    """Build an EstimateJobResponse from an AIEstimateJob ORM instance."""
    items: list[EstimateItem] = []
    grand_total = 0.0

    if job.result and isinstance(job.result, list):
        for item_data in job.result:
            if not isinstance(item_data, dict):
                continue
            ei = EstimateItem(
                ordinal=str(item_data.get("ordinal", "")),
                description=str(item_data.get("description", "")),
                unit=str(item_data.get("unit", "m2")),
                quantity=float(item_data.get("quantity", 0)),
                unit_rate=float(item_data.get("unit_rate", 0)),
                total=float(item_data.get("total", 0)),
                classification=item_data.get("classification", {}),
                category=str(item_data.get("category", "General")),
            )
            items.append(ei)
            grand_total += ei.total

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
        grand_total=round(grand_total, 2),
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

    async def update_ai_settings(
        self, user_id: str, data: AISettingsUpdate
    ) -> AISettingsResponse:
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

        if settings is None:
            # Create with provided values
            settings = AISettings(
                user_id=uid,
                anthropic_api_key=data.anthropic_api_key,
                openai_api_key=data.openai_api_key,
                gemini_api_key=data.gemini_api_key,
                preferred_model=data.preferred_model or "claude-sonnet",
            )
            settings = await self.settings_repo.create(settings)
        else:
            fields: dict[str, Any] = {}
            if data.anthropic_api_key is not None:
                fields["anthropic_api_key"] = data.anthropic_api_key
            if data.openai_api_key is not None:
                fields["openai_api_key"] = data.openai_api_key
            if data.gemini_api_key is not None:
                fields["gemini_api_key"] = data.gemini_api_key
            if data.preferred_model is not None:
                fields["preferred_model"] = data.preferred_model

            if fields:
                await self.settings_repo.update_fields(settings.id, **fields)

        # Re-fetch to return fresh data
        settings = await self.settings_repo.get_by_user_id(uid)
        if settings is None:
            msg = "Settings not found after update"
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=msg)

        await event_bus.publish(
            "ai.settings.updated",
            {"user_id": user_id},
            source_module="oe_ai",
        )

        return _build_settings_response(settings)

    # ── Quick estimate (text -> AI -> BOQ items) ─────────────────────────

    async def quick_estimate(
        self, user_id: str, request: QuickEstimateRequest
    ) -> EstimateJobResponse:
        """Generate a BOQ estimate from a text description using AI.

        Args:
            user_id: Current user's ID.
            request: Estimation request with description and optional context.

        Returns:
            EstimateJobResponse with generated items.
        """
        uid = uuid.UUID(user_id)
        settings = await self.settings_repo.get_by_user_id(uid)

        # Resolve which AI provider to use
        try:
            provider, api_key = resolve_provider_and_key(settings)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
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

        # Build prompt with context
        extra_parts: list[str] = []
        if request.project_type:
            extra_parts.append(f"Building type: {request.project_type}")
        if request.area_m2:
            extra_parts.append(f"Total area: {request.area_m2} m2")
        if request.location:
            extra_parts.append(f"Location: {request.location}")
        extra_context = "\n".join(extra_parts)

        currency = request.currency or "EUR"
        standard_val = request.standard or "din276"

        prompt = TEXT_ESTIMATE_PROMPT.format(
            description=request.description,
            extra_context=extra_context,
            currency=currency,
            standard=standard_val,
        )

        # Call AI
        start_time = time.monotonic()
        try:
            raw_response, tokens = await call_ai(
                provider=provider,
                api_key=api_key,
                system=SYSTEM_PROMPT,
                prompt=prompt,
            )
            duration_ms = int((time.monotonic() - start_time) * 1000)

            # Parse response
            parsed = extract_json(raw_response)
            items = _validate_items(parsed)

            if not items:
                await self.job_repo.update_fields(
                    job.id,
                    status="failed",
                    error_message="AI returned no valid work items. Please try a more detailed description.",
                    model_used=provider,
                    tokens_used=tokens,
                    duration_ms=duration_ms,
                )
                job = await self.job_repo.get_by_id(job.id)
                if job is None:
                    msg = "Job not found after update"
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=msg,
                    )
                return _build_job_response(job)

            # Update job with results
            await self.job_repo.update_fields(
                job.id,
                status="completed",
                result=items,
                model_used=provider,
                tokens_used=tokens,
                duration_ms=duration_ms,
            )

        except HTTPException:
            raise
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            error_msg = f"AI estimation failed: {exc}"
            logger.exception("Quick estimate failed for user %s: %s", user_id, exc)

            await self.job_repo.update_fields(
                job.id,
                status="failed",
                error_message=error_msg,
                model_used=provider,
                duration_ms=duration_ms,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=error_msg,
            ) from exc

        # Re-fetch the completed job
        job = await self.job_repo.get_by_id(job.id)
        if job is None:
            msg = "Job not found after completion"
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=msg
            )

        await event_bus.publish(
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
            provider, api_key = resolve_provider_and_key(settings)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
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

        # Build prompt
        currency_val = currency or "EUR"
        standard_val = standard or "din276"
        location_val = location or "Europe"

        prompt = PHOTO_ESTIMATE_PROMPT.format(
            location=location_val,
            currency=currency_val,
            standard=standard_val,
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
            )
            duration_ms = int((time.monotonic() - start_time) * 1000)

            parsed = extract_json(raw_response)
            items = _validate_items(parsed)

            if not items:
                await self.job_repo.update_fields(
                    job.id,
                    status="failed",
                    error_message="AI could not extract work items from this photo. Please try a clearer image.",
                    model_used=provider,
                    tokens_used=tokens,
                    duration_ms=duration_ms,
                )
                job = await self.job_repo.get_by_id(job.id)
                if job is None:
                    msg = "Job not found after update"
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=msg,
                    )
                return _build_job_response(job)

            await self.job_repo.update_fields(
                job.id,
                status="completed",
                result=items,
                model_used=provider,
                tokens_used=tokens,
                duration_ms=duration_ms,
            )

        except HTTPException:
            raise
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            error_msg = f"AI photo analysis failed: {exc}"
            logger.exception("Photo estimate failed for user %s: %s", user_id, exc)

            await self.job_repo.update_fields(
                job.id,
                status="failed",
                error_message=error_msg,
                model_used=provider,
                duration_ms=duration_ms,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=error_msg,
            ) from exc

        job = await self.job_repo.get_by_id(job.id)
        if job is None:
            msg = "Job not found after completion"
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=msg
            )

        await event_bus.publish(
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

        if job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Estimate job not found",
            )

        if str(job.user_id) != str(uid):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only create BOQs from your own estimates",
            )

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

        await event_bus.publish(
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
