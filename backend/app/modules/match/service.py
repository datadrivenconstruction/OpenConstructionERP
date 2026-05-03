# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""HTTP-facing service layer — keeps the router thin.

Loads the acting user's AISettings (so the translation cascade and
rerank tier can use their key) and verifies project ownership before
delegating to :mod:`app.core.match_service`.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.match_service import (
    ElementEnvelope,
    MatchCandidate,
    MatchResponse,
    build_envelope,
    match_envelope,
    record_feedback,
)

logger = logging.getLogger(__name__)


async def _load_ai_settings(db: AsyncSession, user_id: str | None) -> Any:
    """Fetch the user's AISettings row, or ``None`` when unavailable.

    AISettings powers the translation LLM and the rerank LLM. If the
    user has no row, both tiers degrade gracefully (translation falls
    through to fallback, rerank skips).
    """
    if not user_id:
        return None
    try:
        from sqlalchemy import select

        from app.modules.ai.models import AISettings

        stmt = select(AISettings).where(AISettings.user_id == uuid.UUID(user_id))
        return (await db.execute(stmt)).scalar_one_or_none()
    except Exception as exc:  # pragma: no cover — AI module optional
        logger.debug("ai_settings load skipped: %s", exc)
        return None


async def _verify_project_access(
    db: AsyncSession,
    project_id: uuid.UUID,
    user_id: str,
    role: str = "",
) -> None:
    """Raise 403/404 if the acting user can't see this project."""
    from app.modules.projects.repository import ProjectRepository

    repo = ProjectRepository(db)
    project = await repo.get_by_id(project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    if role == "admin":
        return
    if str(project.owner_id) != str(user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this project",
        )


async def run_match_for_element(
    *,
    db: AsyncSession,
    project_id: uuid.UUID,
    user_id: str,
    user_role: str,
    source: str,
    raw_element_data: dict[str, Any],
    top_k: int = 10,
    use_reranker: bool = False,
) -> MatchResponse:
    """Build envelope, verify access, run the matcher."""
    await _verify_project_access(db, project_id, user_id, user_role)
    envelope = build_envelope(source, raw_element_data)
    ai_settings = await _load_ai_settings(db, user_id)
    return await match_envelope(
        envelope,
        project_id=project_id,
        top_k=top_k,
        use_reranker=use_reranker,
        db=db,
        ai_settings=ai_settings,
    )


async def submit_feedback(
    *,
    db: AsyncSession,
    project_id: uuid.UUID,
    user_id: str,
    user_role: str,
    element_envelope: ElementEnvelope,
    accepted_candidate: MatchCandidate | None,
    rejected_candidates: list[MatchCandidate],
    user_chose_code: str | None,
) -> None:
    """Authorize and persist a feedback event."""
    await _verify_project_access(db, project_id, user_id, user_role)
    await record_feedback(
        db=db,
        project_id=project_id,
        element_envelope=element_envelope,
        accepted_candidate=accepted_candidate,
        rejected_candidates=rejected_candidates,
        user_chose_code=user_chose_code,
        user_id=user_id,
    )


# ── Phase 4: accept-match consolidated flow ─────────────────────────────


# Quantity inference order — area takes precedence over volume because
# walls/slabs are most often estimated per m². Length covers linear
# elements (pipes, beams, kerb), and 1.0 is the safe fallback so the BOQ
# row still rolls up at the candidate's unit_rate even when the envelope
# is geometry-less (e.g. a manual photo crop with no dimensions).
_QUANTITY_INFERENCE_ORDER: tuple[str, ...] = (
    "area_m2",
    "volume_m3",
    "length_m",
)
_QUANTITY_FALLBACK: float = 1.0


def _infer_quantity(
    *,
    envelope: ElementEnvelope,
    override: float | None,
) -> float:
    """Pick a position quantity from the envelope's quantities map.

    Caller-supplied override always wins. Otherwise we walk
    :data:`_QUANTITY_INFERENCE_ORDER` and pick the first positive number;
    if none are present we fall back to :data:`_QUANTITY_FALLBACK` so the
    new BOQ row still rolls up at the candidate's unit_rate.
    """
    if override is not None and override > 0:
        return float(override)
    quantities = envelope.quantities or {}
    for key in _QUANTITY_INFERENCE_ORDER:
        raw = quantities.get(key)
        try:
            val = float(raw) if raw is not None else 0.0
        except (TypeError, ValueError):
            continue
        if val > 0:
            return val
    return _QUANTITY_FALLBACK


def _build_match_metadata(
    *,
    accepted: MatchCandidate,
    confidence_band: str,
    matched_at: str,
    user_id: str | None,
    boosts_applied: dict[str, float],
    bim_element_id: str | None,
) -> dict[str, Any]:
    """Build the ``metadata`` dict written onto the BOQ position.

    Captures the full provenance trail so a later auditor can answer
    "where did this rate come from?" without joining the audit log:

    * ``cost_item_code`` — the CWICR code that was matched.
    * ``match_score`` / ``match_vector_score`` — final and pre-boost
      score; lets downstream tooling distinguish "high vector recall +
      tiny boost" from "low recall, big boost".
    * ``match_boosts_applied`` — full boost trail (classifier, unit, lex…).
    * ``match_confidence_band`` — high/medium/low at the moment of accept.
    * ``matched_at`` — UTC ISO-8601 timestamp of the accept call.
    * ``matched_by_user_id`` — acting user; ``None`` for admin/service
      callers that don't carry a sub claim.
    * ``bim_element_id`` — cross-reference back to the source BIM element.
    """
    return {
        "cost_item_code": accepted.code,
        "match_score": round(float(accepted.score), 4),
        "match_vector_score": round(float(accepted.vector_score), 4),
        "match_boosts_applied": {k: float(v) for k, v in (boosts_applied or {}).items()},
        "match_confidence_band": confidence_band,
        "matched_at": matched_at,
        "matched_by_user_id": user_id or None,
        "bim_element_id": bim_element_id,
    }


async def _resolve_audit_entry_id(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    user_id: str | None,
) -> uuid.UUID | None:
    """Best-effort lookup of the most recent ``match_feedback`` audit row.

    ``record_feedback`` swallows its own errors and returns ``None``, so
    the only way to surface the row id back to the caller is to query
    by entity for the last entry. We scope to ``user_id`` when present
    so concurrent writers don't collide.
    """
    from sqlalchemy import desc, select

    from app.core.audit import AuditEntry

    stmt = (
        select(AuditEntry.id)
        .where(
            AuditEntry.action == "match_feedback",
            AuditEntry.entity_type == "match_feedback",
            AuditEntry.entity_id == str(project_id),
        )
        .order_by(desc(AuditEntry.created_at))
        .limit(1)
    )
    if user_id:
        try:
            uid = uuid.UUID(user_id)
            stmt = stmt.where(AuditEntry.user_id == uid)
        except (TypeError, ValueError):
            pass
    try:
        return (await db.execute(stmt)).scalar_one_or_none()
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("audit entry lookup skipped: %s", exc)
        return None


async def _link_bim_element(
    db: AsyncSession,
    *,
    boq_position_id: uuid.UUID,
    bim_element_id: str,
    user_id: str | None,
    confidence_band: str,
) -> bool:
    """Create a BIM element ↔ BOQ position link.

    Returns ``True`` when a link was created, ``False`` when the link
    couldn't be made (BIM element doesn't exist, ``bim_hub`` module
    unavailable, etc). Any failure is logged at debug level and
    swallowed so a missing BIM module never blocks the accept flow —
    the BOQ position is still created.
    """
    try:
        try:
            elem_uuid = uuid.UUID(bim_element_id)
        except (TypeError, ValueError):
            logger.debug("bim_element_id not a UUID, skipping link: %s", bim_element_id)
            return False

        from app.modules.bim_hub.schemas import BOQElementLinkCreate
        from app.modules.bim_hub.service import BIMHubService

        svc = BIMHubService(db)
        await svc.create_link(
            BOQElementLinkCreate(
                boq_position_id=boq_position_id,
                bim_element_id=elem_uuid,
                link_type="auto",
                confidence=confidence_band,
                metadata={"created_by": "match_accept"},
            ),
            user_id=user_id,
        )
        return True
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.debug("BIM link create skipped: %s", exc)
        return False


async def accept_match(
    *,
    db: AsyncSession,
    project_id: uuid.UUID,
    user_id: str,
    user_role: str,
    element_envelope: ElementEnvelope,
    accepted_candidate: MatchCandidate,
    rejected_candidates: list[MatchCandidate],
    boq_id: uuid.UUID,
    parent_section_id: uuid.UUID | None,
    existing_position_id: uuid.UUID | None,
    quantity_override: float | None,
    bim_element_id: str | None,
) -> dict[str, Any]:
    """Persist an accepted match by writing/updating a BOQ position.

    Steps:
        1. Verify project membership.
        2. Resolve quantity from the envelope (area > volume > length > 1.0)
           or use the caller's override.
        3. Either PATCH ``existing_position_id`` or create a fresh row.
        4. Optionally link the new position to a BIM element.
        5. Submit feedback so the audit log captures accept + rejects.
        6. Return a dict the router can serialize into ``MatchAcceptResponse``.

    Returns:
        Dict with ``position_id``, ``position_ordinal``, ``created``,
        ``cost_link_created``, ``bim_link_created``, ``audit_entry_id``.
    """
    from datetime import UTC, datetime

    from app.modules.boq.schemas import PositionCreate, PositionUpdate
    from app.modules.boq.service import BOQService

    await _verify_project_access(db, project_id, user_id, user_role)

    boq_service = BOQService(db)
    boq = await boq_service.get_boq(boq_id)
    if str(boq.project_id) != str(project_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="boq_id does not belong to the supplied project_id",
        )

    quantity = _infer_quantity(envelope=element_envelope, override=quantity_override)
    matched_at = datetime.now(UTC).isoformat(timespec="seconds")

    match_metadata = _build_match_metadata(
        accepted=accepted_candidate,
        confidence_band=accepted_candidate.confidence_band,
        matched_at=matched_at,
        user_id=user_id or None,
        boosts_applied=dict(accepted_candidate.boosts_applied or {}),
        bim_element_id=bim_element_id,
    )

    actor_id: uuid.UUID | None
    try:
        actor_id = uuid.UUID(user_id) if user_id else None
    except (TypeError, ValueError):
        actor_id = None

    cost_link_created = False
    if existing_position_id is not None:
        # PATCH an existing row in place. We merge the match metadata
        # over whatever the row already carried so unrelated keys
        # (custom columns, BIM provenance, …) survive.
        existing = await boq_service.position_repo.get_by_id(existing_position_id)
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="existing_position_id not found",
            )
        if str(existing.boq_id) != str(boq_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="existing_position_id does not belong to the supplied boq_id",
            )
        merged_metadata: dict[str, Any] = (
            dict(existing.metadata_) if isinstance(existing.metadata_, dict) else {}
        )
        merged_metadata.update(match_metadata)

        update_payload = PositionUpdate(
            description=accepted_candidate.description or existing.description,
            unit=accepted_candidate.unit or existing.unit,
            quantity=quantity,
            unit_rate=float(accepted_candidate.unit_rate),
            source="ai_match",
            metadata=merged_metadata,
        )
        position = await boq_service.update_position(
            existing_position_id, update_payload, actor_id=actor_id,
        )
        created = False
        cost_link_created = True
    else:
        # Fresh position — pick an auto-ordinal so the user doesn't have
        # to. We reuse the BIM-NNN namespace for ai_match too: it never
        # collides with manual MasterFormat/DIN ordinals (03, 32.07.1)
        # and signals at-a-glance that the row came from automation.
        positions, _total = await boq_service.position_repo.list_for_boq(
            boq_id, offset=0, limit=10000,
        )
        ordinal = _build_match_ordinal(positions)

        unit = accepted_candidate.unit or "pcs"
        create_payload = PositionCreate(
            boq_id=boq_id,
            parent_id=parent_section_id,
            ordinal=ordinal,
            description=accepted_candidate.description or accepted_candidate.code,
            unit=unit,
            quantity=quantity,
            unit_rate=float(accepted_candidate.unit_rate),
            classification=dict(accepted_candidate.classification or {}),
            source="ai_match",
            confidence=float(accepted_candidate.score),
            metadata=match_metadata,
        )
        position = await boq_service.add_position(create_payload)
        created = True
        cost_link_created = True

    bim_link_created = False
    if bim_element_id:
        bim_link_created = await _link_bim_element(
            db,
            boq_position_id=position.id,
            bim_element_id=bim_element_id,
            user_id=user_id or None,
            confidence_band=accepted_candidate.confidence_band,
        )

    # Capture feedback so the audit log holds the accept + rejected list.
    # ``record_feedback`` is fire-and-forget on its own side; we await
    # it so the audit row is committed in the same transaction as the
    # position write.
    await record_feedback(
        db=db,
        project_id=project_id,
        element_envelope=element_envelope,
        accepted_candidate=accepted_candidate,
        rejected_candidates=rejected_candidates,
        user_chose_code=accepted_candidate.code,
        user_id=user_id or None,
    )
    audit_entry_id = await _resolve_audit_entry_id(
        db, project_id=project_id, user_id=user_id or None,
    )

    return {
        "position_id": position.id,
        "position_ordinal": position.ordinal,
        "created": created,
        "cost_link_created": cost_link_created,
        "bim_link_created": bim_link_created,
        "audit_entry_id": audit_entry_id,
    }


# Match-sourced ordinal prefix — kept distinct from "BIM-NNN" used by the
# manual AddToBOQModal so an auditor can grep the BOQ for AI-accepted rows.
_MATCH_ORDINAL_PREFIX = "AI-"
_MATCH_ORDINAL_PAD = 3


def _build_match_ordinal(positions: list[Any]) -> str:
    """Pick the next free ``AI-NNN`` ordinal for an accepted match.

    Scans every existing position's ordinal for the ``AI-NNN`` shape
    and returns ``AI-{max+1}`` zero-padded to :data:`_MATCH_ORDINAL_PAD`.
    """
    import re

    pattern = re.compile(r"^AI-(\d+)$", re.IGNORECASE)
    max_n = 0
    for pos in positions:
        ordinal = (getattr(pos, "ordinal", "") or "").strip()
        m = pattern.match(ordinal)
        if m:
            try:
                n = int(m.group(1))
            except ValueError:
                continue
            if n > max_n:
                max_n = n
    return f"{_MATCH_ORDINAL_PREFIX}{(max_n + 1):0{_MATCH_ORDINAL_PAD}d}"
