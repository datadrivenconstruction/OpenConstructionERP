# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Claims / dispute evidence-pack service - the thin database layer.

Gathers a project's cross-module activity (from the activity-log timeline) and
its change-family records, projects them to evidence entries, and hands them to
the pure assembly engine to produce a deterministic, ordered evidence pack. The
pack is assembled on demand; nothing is persisted, so there is no new table and
no migration.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.changeorders.models import ChangeOrder
from app.modules.claims_evidence.evidence_pack import (
    EvidenceEntry,
    EvidencePack,
    assemble_pack,
)
from app.modules.moc.models import MoCEntry
from app.modules.timeline.service import get_project_timeline
from app.modules.variations.models import Notice, VariationOrder, VariationRequest

# Change-family source tables mapped to the (source_module, kind) the evidence
# engine routes on. source_module mirrors the activity-log module names so a
# document and the events about it land in the same section.
_CHANGE_SOURCES: tuple[tuple[type, str, str], ...] = (
    (Notice, "notices", "notice"),
    (VariationRequest, "variations", "variation_request"),
    (VariationOrder, "variations", "variation_order"),
    (ChangeOrder, "changeorders", "change_order"),
    (MoCEntry, "moc", "moc_entry"),
)


def _iso(value: object) -> str | None:
    """Render a datetime-like value as an ISO string, or None."""
    return value.isoformat() if hasattr(value, "isoformat") else None


async def _activity_entries(session: AsyncSession, project_id: uuid.UUID, limit: int) -> list[EvidenceEntry]:
    """Project the activity-log timeline rows into evidence entries."""
    rows = await get_project_timeline(session, project_id=project_id, limit=limit)
    entries: list[EvidenceEntry] = []
    for row in rows:
        action = row.action or ""
        title = f"{row.entity_type} {action}".strip() if row.entity_type else action
        entries.append(
            EvidenceEntry(
                ref_id=str(row.id),
                source_module=row.module or "activity_log",
                kind=action,
                title=title or "activity",
                occurred_at=_iso(row.created_at),
                actor_id=str(row.actor_id) if row.actor_id else None,
                summary=row.reason or "",
            )
        )
    return entries


async def _change_entries(session: AsyncSession, project_id: uuid.UUID) -> list[EvidenceEntry]:
    """Project the change-family documents into evidence entries."""
    entries: list[EvidenceEntry] = []
    for model, source_module, kind in _CHANGE_SOURCES:
        stmt = select(model.id, model.code, model.title, model.created_at).where(model.project_id == project_id)
        for row in (await session.execute(stmt)).all():
            title = (row.title or "").strip() or (row.code or "")
            label = f"{row.code} {title}".strip() if row.code else title
            entries.append(
                EvidenceEntry(
                    ref_id=str(row.id),
                    source_module=source_module,
                    kind=kind,
                    title=label or kind,
                    occurred_at=_iso(row.created_at),
                    actor_id=None,
                    summary="",
                )
            )
    return entries


async def assemble_evidence(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    subject_ref: str,
    basis: str = "dispute",
    activity_limit: int = 500,
) -> EvidencePack:
    """Assemble a deterministic evidence pack for a project's claim or dispute.

    Pulls the project's recent cross-module activity and every change-family
    record, then orders, sections and digests them with the pure engine. The
    same project state always yields the same pack and content digest.
    """
    entries = await _activity_entries(session, project_id, activity_limit)
    entries += await _change_entries(session, project_id)
    return assemble_pack(subject_ref, entries, basis=basis)


# Reconciliation record-type -> (evidence source_module, kind). The source_module
# mirrors the activity-log module names the evidence engine sections on, so a
# reconstructed pack groups each record into the same section the full project
# pack would. A record type not listed here falls back to using the type itself.
_RECON_TO_EVIDENCE: dict[str, tuple[str, str]] = {
    "correspondence": ("correspondence", "correspondence"),
    "change_order": ("changeorders", "change_order"),
    "variation_request": ("variations", "variation_request"),
    "variation_order": ("variations", "variation_order"),
    "notice": ("notices", "notice"),
    "moc": ("moc", "moc_entry"),
}


def _entry_from_thread_record(thread_record: object) -> EvidenceEntry:
    """Project one reconciled-thread record onto an evidence entry."""
    record = thread_record.record  # type: ignore[attr-defined]
    source_module, kind = _RECON_TO_EVIDENCE.get(record.record_type, (record.record_type, record.record_type))
    title = (record.subject or "").strip() or kind
    occurred_at = record.occurred_at.isoformat() if record.occurred_at is not None else None
    return EvidenceEntry(
        ref_id=record.record_id,
        source_module=source_module,
        kind=kind,
        title=title,
        occurred_at=occurred_at,
        actor_id=record.party,
        summary="",
    )


async def reconstruct_subject(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    subject_type: str,
    subject_id: uuid.UUID,
    basis: str = "dispute",
) -> EvidencePack:
    """Assemble an evidence pack scoped to ONE subject's reconciled thread.

    Where :func:`assemble_evidence` pulls the whole project, this reconstructs
    the story of a single change or dispute: it grows the cross-channel thread
    around the subject (the reconciliation engine's connected component of
    linked records), then assembles only those records into a deterministic,
    SHA-256-digested pack. The same project state always yields the same pack,
    so the export is reproducible for a claim.

    If the reconciliation module is not installed the pack is empty rather than
    failing (the feature degrades to "nothing linked yet").
    """
    event_key = f"{subject_type}:{subject_id}"
    try:
        from app.modules.reconciliation.service import build_event_thread
    except ModuleNotFoundError:  # pragma: no cover - optional module absent
        return assemble_pack(event_key, [], basis=basis)

    thread = await build_event_thread(session, project_id, event_key)
    entries = [_entry_from_thread_record(tr) for tr in thread.records]
    return assemble_pack(event_key, entries, basis=basis)
