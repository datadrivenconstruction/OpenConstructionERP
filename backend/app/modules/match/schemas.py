# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pydantic request/response schemas for the element-to-CWICR matcher.

Schemas:
    * :class:`MatchElementRequest`   - ``POST /element`` inbound body.
    * :class:`MatchFeedbackRequest`  - ``POST /feedback`` inbound body.
    * :class:`MatchAcceptRequest`    - ``POST /accept`` inbound body.
    * :class:`MatchAcceptResponse`   - ``POST /accept`` outbound body.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.match_service import ElementEnvelope, MatchCandidate


class MatchElementRequest(BaseModel):
    """Inbound body for ``POST /element``.

    Attributes:
        source: One of bim/pdf/dwg/photo. Validated to a closed allowlist.
        project_id: Target project UUID.
        raw_element_data: Arbitrary element payload forwarded to the
            source extractor.
        top_k: Maximum number of ranked candidates to return (1-100).
        use_reranker: Toggle the optional LLM rerank tier.
    """

    model_config = ConfigDict(extra="ignore")

    source: Literal["bim", "pdf", "dwg", "photo"] = Field(
        ...,
        description="One of bim/pdf/dwg/photo. Validated to a closed allowlist.",
    )
    project_id: UUID
    raw_element_data: dict[str, Any] = Field(default_factory=dict)
    top_k: int = Field(default=10, ge=1, le=100)
    use_reranker: bool = False


class MatchFeedbackRequest(BaseModel):
    """Inbound body for ``POST /feedback``.

    Attributes:
        project_id: Project the match was scoped to.
        element_envelope: The envelope the matcher saw.
        accepted_candidate: Candidate the user accepted (if any).
        rejected_candidates: Candidates the user explicitly rejected.
        user_chose_code: Free-form code when the user went manual.
    """

    model_config = ConfigDict(extra="ignore")

    project_id: UUID
    element_envelope: ElementEnvelope
    accepted_candidate: MatchCandidate | None = None
    rejected_candidates: list[MatchCandidate] = Field(default_factory=list)
    user_chose_code: str | None = None


class MatchAcceptRequest(BaseModel):
    """Inbound body for ``POST /accept``.

    Consolidates the three round-trips the frontend would otherwise need
    (create / update position, create BIM link, submit feedback) into
    one transactional call. ``existing_position_id`` swaps the create
    path for an update; ``bim_element_id`` opts into the BIM link.

    Attributes:
        project_id: Project scope.
        element_envelope: The envelope the matcher saw.
        accepted_candidate: The candidate the user confirmed.
        rejected_candidates: Candidates the user rejected.
        boq_id: Target BOQ for the new/updated position.
        parent_section_id: Optional parent section within the BOQ.
        existing_position_id: When set, PATCH this position instead of
            creating a new one.
        quantity_override: Caller-supplied quantity; overrides envelope
            inference when positive.
        bim_element_id: When set, create a BIM element link to the
            resulting BOQ position.
    """

    model_config = ConfigDict(extra="ignore")

    project_id: UUID
    element_envelope: ElementEnvelope
    accepted_candidate: MatchCandidate
    rejected_candidates: list[MatchCandidate] = Field(default_factory=list)
    boq_id: UUID
    parent_section_id: UUID | None = None
    existing_position_id: UUID | None = None
    quantity_override: float | None = Field(default=None, ge=0.0)
    bim_element_id: str | None = None


class MatchAcceptResponse(BaseModel):
    """Outbound body for ``POST /accept``.

    Attributes:
        position_id: UUID of the created or updated BOQ position.
        position_ordinal: Ordinal string assigned to the position.
        created: ``True`` when a new position was created, ``False``
            when an existing one was patched.
        cost_link_created: ``True`` when the position carries a CWICR
            cost item link.
        bim_link_created: ``True`` when a BIM element link was created.
        audit_entry_id: UUID of the match-feedback audit row (best-effort).
    """

    position_id: UUID
    position_ordinal: str
    created: bool
    cost_link_created: bool
    bim_link_created: bool
    audit_entry_id: UUID | None = None
