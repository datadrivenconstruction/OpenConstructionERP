"""ACAP module API routes."""

from __future__ import annotations

import logging
import uuid as _uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.dependencies import get_current_user_id

logger = logging.getLogger(__name__)

router = APIRouter(tags=["acap"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe for the ACAP module. Unauthenticated."""
    return {"status": "ok", "module": "acap"}


# ── Layout generation ────────────────────────────────────────────────────────


class GenerateLayoutRequest(BaseModel):
    requirement_text: str
    kavling_width_m: float = Field(gt=0.0)
    kavling_length_m: float = Field(gt=0.0)
    jumlah_lantai: int = Field(default=1, ge=1)


class GenerateLayoutResponse(BaseModel):
    version: int
    plan: dict
    project_id: _uuid.UUID


async def get_session():
    """Yield an async database session (local copy to avoid import-order issues)."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@router.post("/projects/{project_id}/layout:generate")
async def generate_layout_endpoint(
    project_id: _uuid.UUID,
    body: GenerateLayoutRequest,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user_id),
) -> GenerateLayoutResponse:
    """Generate a new floor-plan version for *project_id* via LLM.

    Each call creates a new version (does NOT overwrite older versions).
    The generated plan is validated against :mod:`app.modules.acap.layout.validator`.
    """
    from app.modules.acap.layout.generator import LayoutGenerationError, generate_layout
    from app.modules.acap.models.floor_plan import FloorPlanRecord, next_version

    try:
        plan = await generate_layout(
            session=session,
            requirement_text=body.requirement_text,
            kavling_width_m=body.kavling_width_m,
            kavling_length_m=body.kavling_length_m,
            jumlah_lantai=body.jumlah_lantai,
            user_id=current_user,
        )
    except LayoutGenerationError as e:
        status = 400 if e.attempts == 0 else 422
        raise HTTPException(
            status_code=status,
            detail={
                "detail": str(e),
                "reasons": e.reasons,
                "attempts": e.attempts,
            },
        ) from e

    # Persist
    version = await next_version(session, project_id)
    record = FloorPlanRecord(
        project_id=project_id,
        version=version,
        requirement_text=body.requirement_text,
        jumlah_lantai=body.jumlah_lantai,
        model=plan.generated_by,
        status="generated",
        plan_json=plan.model_dump(),
    )
    session.add(record)
    await session.flush()

    logger.info(
        "Generated layout v%d for project %s (model=%s)",
        version,
        project_id,
        plan.generated_by,
    )

    return GenerateLayoutResponse(
        version=version,
        plan=plan.model_dump(),
        project_id=project_id,
    )
