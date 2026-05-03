# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""HTTP routes for the element-to-CWICR matcher.

Endpoints:
    * ``POST /api/v1/match/element``  — run the matcher.
    * ``POST /api/v1/match/feedback`` — record user confirmation.

Both require auth via the existing JWT bearer scheme.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.match_service import (
    ElementEnvelope,
    MatchCandidate,
    MatchResponse,
)
from app.dependencies import CurrentUserPayload, SessionDep
from app.modules.match.service import run_match_for_element, submit_feedback

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Request schemas ──────────────────────────────────────────────────────


class MatchElementRequest(BaseModel):
    """Inbound body for ``POST /element``."""

    model_config = ConfigDict(extra="ignore")

    source: Literal["bim", "pdf", "dwg", "photo"] = Field(
        ..., description="One of bim/pdf/dwg/photo. Validated to a closed allowlist.",
    )
    project_id: UUID
    raw_element_data: dict[str, Any] = Field(default_factory=dict)
    top_k: int = Field(default=10, ge=1, le=100)
    use_reranker: bool = False


class MatchFeedbackRequest(BaseModel):
    """Inbound body for ``POST /feedback``."""

    model_config = ConfigDict(extra="ignore")

    project_id: UUID
    element_envelope: ElementEnvelope
    accepted_candidate: MatchCandidate | None = None
    rejected_candidates: list[MatchCandidate] = Field(default_factory=list)
    user_chose_code: str | None = None


# ── Routes ────────────────────────────────────────────────────────────────


@router.post(
    "/element",
    response_model=MatchResponse,
    summary="Match one element to CWICR",
    description=(
        "Build an :class:`ElementEnvelope` from ``raw_element_data`` for "
        "the requested ``source``, run the translation → vector search → "
        "boost stack → optional rerank pipeline, and return ranked "
        "CWICR candidates."
    ),
)
async def match_element_endpoint(
    body: MatchElementRequest,
    session: SessionDep,
    user: CurrentUserPayload,
) -> MatchResponse:
    """Run the matcher on one element and return ranked CWICR candidates."""
    user_id = str(user.get("sub") or "")
    user_role = str(user.get("role") or "")
    return await run_match_for_element(
        db=session,
        project_id=body.project_id,
        user_id=user_id,
        user_role=user_role,
        source=body.source,
        raw_element_data=body.raw_element_data,
        top_k=body.top_k,
        use_reranker=body.use_reranker,
    )


@router.post(
    "/feedback",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Record match feedback",
    description=(
        "Persist the user's accept/reject decision for one element so "
        "we can re-tune boost weights and grow the golden set."
    ),
)
async def feedback_endpoint(
    body: MatchFeedbackRequest,
    session: SessionDep,
    user: CurrentUserPayload,
) -> None:
    """Record one match feedback event into the audit log."""
    user_id = str(user.get("sub") or "")
    user_role = str(user.get("role") or "")
    await submit_feedback(
        db=session,
        project_id=body.project_id,
        user_id=user_id,
        user_role=user_role,
        element_envelope=body.element_envelope,
        accepted_candidate=body.accepted_candidate,
        rejected_candidates=body.rejected_candidates,
        user_chose_code=body.user_chose_code,
    )


@router.get("/_health", include_in_schema=False)
async def health() -> dict[str, str]:
    """Module-loaded probe."""
    return {"module": "oe_match", "status": "ok"}


# Convenience handle for typed re-exports if needed.
ROUTER_PREFIX = "/match"


def _prevent_unused_import_warning() -> tuple[Any, ...]:
    """Keep static-analysis happy while exposing a stable test handle."""
    return (uuid.UUID, ROUTER_PREFIX)
