# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Persistence service for forensic delay analysis (T2.2).

Thin async DB glue around the :class:`DelayAnalysis` / :class:`DelayEvent` /
:class:`Fragnet` / :class:`DelayWindow` tables. All compute is the pure
:mod:`delay_report` / :mod:`delay_engine`; this service only loads/persists.
Access control (project scoping / IDOR) is enforced at the router via
``verify_project_access`` against the analysis's ``project_id``.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import DelayAnalysis, DelayEvent, DelayWindow, Fragnet
from .schemas import (
    DelayAnalysisCreate,
    DelayAnalysisPatch,
    DelayEventCreate,
    DelayEventPatch,
    FragnetUpsert,
)

# Statuses in which an analysis (and its events/fragnets) is still editable.
_EDITABLE = ("draft",)


class DelayAnalysisService:
    """CRUD + compute-persist for forensic delay analyses."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── analyses ─────────────────────────────────────────────────────────────

    async def create_analysis(
        self, project_id: uuid.UUID, data: DelayAnalysisCreate, user_id: uuid.UUID | str | None
    ) -> DelayAnalysis:
        analysis = DelayAnalysis(
            project_id=project_id,
            schedule_id=data.schedule_id,
            method=data.method,
            name=data.name,
            description=data.description,
            as_planned_baseline_id=data.as_planned_baseline_id,
            as_built_snapshot_id=data.as_built_snapshot_id,
            oos_mode=data.oos_mode,
            apportionment_method=data.apportionment_method,
            data_date=data.data_date,
            status="draft",
            created_by=str(user_id) if user_id is not None else None,
        )
        self.session.add(analysis)
        await self.session.flush()
        return analysis

    async def get_analysis(self, analysis_id: uuid.UUID) -> DelayAnalysis | None:
        return await self.session.get(DelayAnalysis, analysis_id)

    async def list_analyses(self, project_id: uuid.UUID) -> list[DelayAnalysis]:
        rows = await self.session.execute(
            select(DelayAnalysis)
            .where(DelayAnalysis.project_id == project_id)
            .order_by(DelayAnalysis.created_at.desc())
        )
        return list(rows.scalars().all())

    async def patch_analysis(self, analysis: DelayAnalysis, data: DelayAnalysisPatch) -> DelayAnalysis:
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(analysis, field, value)
        await self.session.flush()
        return analysis

    async def delete_analysis(self, analysis: DelayAnalysis) -> None:
        # Children cascade at the DB level; remove explicitly too for SQLite.
        await self._delete_children(analysis.id)
        await self.session.delete(analysis)
        await self.session.flush()

    # ── events ───────────────────────────────────────────────────────────────

    async def list_events(self, analysis_id: uuid.UUID) -> list[DelayEvent]:
        rows = await self.session.execute(
            select(DelayEvent).where(DelayEvent.analysis_id == analysis_id).order_by(DelayEvent.created_at.asc())
        )
        return list(rows.scalars().all())

    async def get_event(self, event_id: uuid.UUID) -> DelayEvent | None:
        return await self.session.get(DelayEvent, event_id)

    async def add_event(self, analysis_id: uuid.UUID, data: DelayEventCreate) -> DelayEvent:
        event = DelayEvent(analysis_id=analysis_id, **data.model_dump())
        self.session.add(event)
        await self.session.flush()
        return event

    async def patch_event(self, event: DelayEvent, data: DelayEventPatch) -> DelayEvent:
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(event, field, value)
        await self.session.flush()
        return event

    async def delete_event(self, event: DelayEvent) -> None:
        for frag in await self.list_fragnets(event.id):
            await self.session.delete(frag)
        await self.session.delete(event)
        await self.session.flush()

    # ── fragnets ─────────────────────────────────────────────────────────────

    async def list_fragnets(self, event_id: uuid.UUID) -> list[Fragnet]:
        rows = await self.session.execute(
            select(Fragnet).where(Fragnet.delay_event_id == event_id).order_by(Fragnet.created_at.asc())
        )
        return list(rows.scalars().all())

    async def set_fragnet(self, event_id: uuid.UUID, data: FragnetUpsert) -> Fragnet:
        """Replace the event's fragnet(s) with the one provided (PUT semantics)."""
        for frag in await self.list_fragnets(event_id):
            await self.session.delete(frag)
        frag = Fragnet(delay_event_id=event_id, **data.model_dump())
        self.session.add(frag)
        await self.session.flush()
        return frag

    async def add_fragnet(
        self,
        event_id: uuid.UUID,
        *,
        insert_mode: str,
        insert_at_activity_ref: str,
        added_duration_days: int,
        fragnet_activities: list[Any],
        rewires: list[Any],
    ) -> Fragnet:
        """Append a fragnet (used by the auto-fragnet helper)."""
        frag = Fragnet(
            delay_event_id=event_id,
            insert_mode=insert_mode,
            insert_at_activity_ref=insert_at_activity_ref,
            added_duration_days=added_duration_days,
            fragnet_activities=fragnet_activities,
            rewires=rewires,
        )
        self.session.add(frag)
        await self.session.flush()
        return frag

    # ── windows / compute persistence ────────────────────────────────────────

    async def list_windows(self, analysis_id: uuid.UUID) -> list[DelayWindow]:
        rows = await self.session.execute(
            select(DelayWindow).where(DelayWindow.analysis_id == analysis_id).order_by(DelayWindow.sequence_order.asc())
        )
        return list(rows.scalars().all())

    async def persist_compute(self, analysis: DelayAnalysis, result: dict[str, Any]) -> DelayAnalysis:
        """Persist a compute result: totals, status, result_json, and windows."""
        # Replace prior window rows.
        for win in await self.list_windows(analysis.id):
            await self.session.delete(win)
        await self.session.flush()

        windows = result.get("windows") or []
        for w in windows:
            self.session.add(
                DelayWindow(
                    analysis_id=analysis.id,
                    sequence_order=int(w.get("sequence_order", 0)),
                    finish_at_open=int(w.get("finish_at_open", 0)),
                    finish_at_close=int(w.get("finish_at_close", 0)),
                    gross_slip_days=int(w.get("gross_slip_days", 0)),
                    employer_days=int(w.get("employer_days", 0)),
                    contractor_days=int(w.get("contractor_days", 0)),
                    neutral_days=int(w.get("neutral_days", 0)),
                    concurrent_days=int(w.get("concurrent_days", 0)),
                    net_entitlement_days=int(w.get("net_entitlement_days", 0)),
                )
            )

        analysis.result_json = result
        analysis.total_entitlement_days = int(result.get("total_entitlement_days", 0) or 0)
        analysis.concurrent_days = int(
            (result.get("attribution") or {}).get("concurrent_days", 0)
            if result.get("attribution")
            else result.get("concurrent_days", 0) or 0
        )
        analysis.window_count = len(windows)
        analysis.status = "computed"
        await self.session.flush()
        return analysis

    # ── issue / e-sign + EOT link ────────────────────────────────────────────

    async def issue(
        self,
        analysis: DelayAnalysis,
        *,
        user_id: uuid.UUID | str | None,
        signature_sha256: str,
        signature_snapshot: dict[str, Any],
        issued_at: str,
    ) -> DelayAnalysis:
        analysis.status = "issued"
        analysis.issued_at = issued_at
        analysis.issued_by = str(user_id) if user_id is not None else None
        analysis.signature_sha256 = signature_sha256
        analysis.signature_snapshot = signature_snapshot
        await self.session.flush()
        return analysis

    async def set_eot_claim(self, analysis: DelayAnalysis, eot_claim_id: uuid.UUID) -> DelayAnalysis:
        analysis.eot_claim_id = eot_claim_id
        await self.session.flush()
        return analysis

    async def refuse_if_eot_claim_raised(self, analysis: DelayAnalysis, *, doing: str) -> None:
        """Raise 409 while the EOT claim raised from this analysis still exists.

        The claim points back at the analysis by ``delay_analysis_id`` with no
        foreign key, so deleting the analysis would leave the claim citing
        nothing, and raising a second claim would re-point ``eot_claim_id`` and
        leave two drafts for one delay. A claim that was itself deleted no
        longer holds the analysis.

        Args:
            analysis: The delay analysis.
            doing: What the caller is refused, as it reads in the sentence.
        """
        if analysis.eot_claim_id is None:
            return
        try:
            from app.modules.variations.models import ExtensionOfTimeClaim
        except ImportError:
            return
        claim = await self.session.get(ExtensionOfTimeClaim, analysis.eot_claim_id)
        if claim is None:
            return
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"An EOT claim was already raised from this analysis (id={claim.id}), "
                f"so it cannot {doing}. Work on that claim instead."
            ),
        )

    # ── helpers ──────────────────────────────────────────────────────────────

    async def build_event_specs(self, analysis_id: uuid.UUID) -> list[dict[str, Any]]:
        """Assemble the stored event specs (dicts) for :func:`delay_report.run_analysis`."""
        events = await self.list_events(analysis_id)
        specs: list[dict[str, Any]] = []
        for ev in events:
            frags = await self.list_fragnets(ev.id)
            specs.append(
                {
                    "id": str(ev.id),
                    "insert_at": ev.insert_at_activity_ref or None,
                    "responsibility": ev.responsibility,
                    "is_concurrent": ev.is_concurrent,
                    "is_pacing": ev.is_pacing,
                    "event_start": ev.start_workday,
                    "event_end": ev.end_workday,
                    "fragnets": [
                        {
                            "insert_mode": f.insert_mode,
                            "host_id": f.insert_at_activity_ref,
                            "added_duration_days": f.added_duration_days,
                            "fragnet_activities": f.fragnet_activities or [],
                            "rewires": f.rewires or [],
                        }
                        for f in frags
                    ],
                }
            )
        return specs

    async def _delete_children(self, analysis_id: uuid.UUID) -> None:
        for win in await self.list_windows(analysis_id):
            await self.session.delete(win)
        for ev in await self.list_events(analysis_id):
            for frag in await self.list_fragnets(ev.id):
                await self.session.delete(frag)
            await self.session.delete(ev)
        await self.session.flush()
