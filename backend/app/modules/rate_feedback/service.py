# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Rate feedback: closed-project actuals become reviewable updates to the cost database.

The service only ever proposes. A proposal changes a cost item when, and only
when, a person confirms it, and the confirm refuses if the item moved since the
proposal was made.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cost_scope import get_cost_item
from app.modules.costs.models import CostItem
from app.modules.rate_feedback.models import (
    STATUS_ACCEPTED,
    STATUS_PENDING,
    STATUS_REJECTED,
    STATUS_SUPERSEDED,
    RateFeedbackProposal,
)
from app.modules.rate_feedback.rate_math import (
    LineObservation,
    aggregate,
    deviates,
    suggested_rate,
)
from app.modules.rate_feedback.schemas import (
    ConfirmRequest,
    ProposalListResponse,
    ProposalResponse,
    RefreshRequest,
    RefreshResponse,
)
from app.modules.rate_feedback.validators import RateFeedbackError, check_confirmable, run_rules

logger = logging.getLogger(__name__)

CLOSED_STATUSES = ("completed", "archived")
HOURS_KEY = "labor_hours"  # the numeric key the cost browser reads
HISTORY_KEY = "rate_feedback_history"
_HISTORY_CAP = 20
_Q4 = Decimal("0.0001")


def _rate_of(item: CostItem) -> Decimal | None:
    try:
        out = Decimal(str(item.rate))
    except (InvalidOperation, ValueError):
        return None
    return out if out.is_finite() and out > 0 else None


def _linked_item_id(position: object) -> str | None:
    meta = getattr(position, "metadata_", None)
    raw = meta.get("cost_item_id") if isinstance(meta, dict) else None
    try:
        return str(uuid.UUID(str(raw))) if raw else None
    except (ValueError, TypeError):
        return None


class RateFeedbackService:
    """Collects observations, stores proposals, applies the confirmed ones."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _closed_project_ids(self, user_id: uuid.UUID, is_admin: bool) -> list[uuid.UUID]:
        from app.modules.projects.repository import ProjectRepository

        repo = ProjectRepository(self.session)
        ids: list[uuid.UUID] = []
        for status in CLOSED_STATUSES:
            rows, _ = await repo.list_for_user(user_id, limit=1000, status=status, is_admin=is_admin)
            ids.extend(p.id for p in rows)
        return ids

    async def _observations(self, project_ids: list[uuid.UUID]) -> list[LineObservation]:
        from app.modules.postcalc.service import PostCalcService

        calc = PostCalcService(self.session)
        out: list[LineObservation] = []
        for pid in project_ids:
            positions = {str(p.id): p for p in await calc._load_positions(pid)}
            report = await calc.generate(pid)
            for line in report.lines:
                position = positions.get(line.position_id or "")
                item_id = _linked_item_id(position) if position is not None else None
                if item_id is None or line.actual_quantity <= 0:
                    continue
                parts = (
                    line.earned_labour_cost,
                    line.earned_material_cost,
                    line.actual_labour_cost,
                    line.actual_material_cost,
                )
                complete = all(p is not None for p in parts)
                hours_known = line.actual_hours > 0 and line.planned_hours_per_unit is not None
                out.append(
                    LineObservation(
                        project_id=str(pid),
                        cost_item_id=item_id,
                        quantity=line.actual_quantity,
                        earned_cost=parts[0] + parts[1] if complete else None,
                        actual_cost=parts[2] + parts[3] if complete else None,
                        actual_hours=line.actual_hours if hours_known else None,
                        planned_hours_per_unit=line.planned_hours_per_unit if hours_known else None,
                    )
                )
        return out

    async def refresh(self, user_id: uuid.UUID, is_admin: bool, req: RefreshRequest) -> RefreshResponse:
        """Recompute pending proposals from the closed projects the caller can see."""
        project_ids = await self._closed_project_ids(user_id, is_admin)
        stats = [s for s in aggregate(await self._observations(project_ids)) if s.project_count >= req.min_projects]
        created = unchanged = 0
        for stat in stats:
            item = await get_cost_item(self.session, stat.cost_item_id)
            rate = _rate_of(item) if item is not None else None
            if item is None or rate is None or not deviates(stat, req.tolerance):
                continue
            new_rate = suggested_rate(rate, stat)
            pending = await self._pending_for(item.id)
            if pending is not None and (
                pending.current_rate == rate.quantize(_Q4)
                and pending.suggested_rate == new_rate
                and pending.project_count == stat.project_count
                and pending.line_count == stat.line_count
            ):
                unchanged += 1
                continue
            if pending is not None:
                pending.status = STATUS_SUPERSEDED
            self.session.add(
                RateFeedbackProposal(
                    cost_item_id=item.id,
                    unit=item.unit,
                    current_rate=rate.quantize(_Q4),
                    suggested_rate=new_rate,
                    variance_pct=stat.cost_variance_pct,
                    current_hours_per_unit=stat.planned_hours_per_unit,
                    observed_hours_per_unit=stat.observed_hours_per_unit,
                    hours_variance_pct=stat.hours_variance_pct,
                    project_count=stat.project_count,
                    line_count=stat.line_count,
                    total_quantity=stat.total_quantity,
                    spread_pct=stat.spread_pct,
                    confidence=stat.confidence,
                    project_ids=stat.project_ids,
                    status=STATUS_PENDING,
                )
            )
            created += 1
        await self.session.flush()
        return RefreshResponse(
            closed_projects=len(project_ids),
            observed_cost_items=len(stats),
            created=created,
            unchanged=unchanged,
        )

    async def _pending_for(self, item_id: uuid.UUID) -> RateFeedbackProposal | None:
        stmt = select(RateFeedbackProposal).where(
            RateFeedbackProposal.cost_item_id == item_id, RateFeedbackProposal.status == STATUS_PENDING
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def list_proposals(
        self, status: str | None = STATUS_PENDING, *, offset: int = 0, limit: int = 50
    ) -> ProposalListResponse:
        """Proposals with the cost item they refer to, biggest confidence-weighted change first."""
        stmt = select(RateFeedbackProposal, CostItem).join(CostItem, CostItem.id == RateFeedbackProposal.cost_item_id)
        count_stmt = (
            select(func.count())
            .select_from(RateFeedbackProposal)
            .join(CostItem, CostItem.id == RateFeedbackProposal.cost_item_id)
        )
        if status:
            stmt = stmt.where(RateFeedbackProposal.status == status)
            count_stmt = count_stmt.where(RateFeedbackProposal.status == status)
        total = int((await self.session.execute(count_stmt)).scalar() or 0)
        weight = func.abs(func.coalesce(RateFeedbackProposal.variance_pct, 0)) * RateFeedbackProposal.confidence
        stmt = stmt.order_by(weight.desc(), RateFeedbackProposal.id).offset(offset).limit(limit)
        rows = (await self.session.execute(stmt)).all()
        out: list[ProposalResponse] = []
        for proposal, item in rows:
            view = ProposalResponse.model_validate(proposal)
            view.cost_item_code = item.code
            view.cost_item_description = item.description
            view.warnings = [
                r.rule_id for r in await run_rules(_as_dict(proposal), {"unit": item.unit, "rate": item.rate})
            ]
            out.append(view)
        return ProposalListResponse(items=out, total=total, offset=offset, limit=limit)

    async def _load_pending(self, proposal_id: uuid.UUID) -> tuple[RateFeedbackProposal, CostItem | None]:
        proposal = await self.session.get(RateFeedbackProposal, proposal_id)
        if proposal is None:
            raise RateFeedbackError(404, "not_found", "Proposal not found.")
        item = await get_cost_item(self.session, proposal.cost_item_id)
        return proposal, item

    async def confirm(self, proposal_id: uuid.UUID, user_id: uuid.UUID, req: ConfirmRequest) -> ProposalResponse:
        """Apply a pending proposal to the cost item, with the estimator's own rate if given."""
        proposal, item = await self._load_pending(proposal_id)
        check_confirmable(_as_dict(proposal), {"unit": item.unit, "rate": item.rate} if item else None)
        assert item is not None  # check_confirmable raised otherwise
        new_rate = (req.rate if req.rate is not None else proposal.suggested_rate).quantize(_Q4)
        before = item.rate
        item.rate = format(new_rate.normalize(), "f")
        item.price_as_of = date.today()
        meta = dict(item.metadata_ or {})
        if req.apply_hours and proposal.observed_hours_per_unit is not None:
            meta[HOURS_KEY] = float(proposal.observed_hours_per_unit.quantize(Decimal("0.01")))
        history = list(meta.get(HISTORY_KEY, []))[-(_HISTORY_CAP - 1) :]
        history.append(
            {
                "proposal_id": str(proposal.id),
                "from_rate": before,
                "to_rate": item.rate,
                "projects": proposal.project_count,
                "confidence": format(proposal.confidence, "f"),
                "by": str(user_id),
                "at": datetime.now(UTC).isoformat(),
            }
        )
        meta[HISTORY_KEY] = history
        item.metadata_ = meta
        proposal.status = STATUS_ACCEPTED
        proposal.applied_rate = new_rate
        proposal.decided_by = user_id
        proposal.decided_at = datetime.now(UTC)
        proposal.decision_note = req.note
        await self.session.flush()
        return ProposalResponse.model_validate(proposal)

    async def reject(self, proposal_id: uuid.UUID, user_id: uuid.UUID, note: str | None) -> ProposalResponse:
        """Dismiss a pending proposal; the cost item is untouched."""
        proposal, _ = await self._load_pending(proposal_id)
        if proposal.status != STATUS_PENDING:
            raise RateFeedbackError(409, "not_pending", "Only a pending proposal can be decided.")
        await self.session.execute(
            update(RateFeedbackProposal)
            .where(RateFeedbackProposal.id == proposal_id)
            .values(status=STATUS_REJECTED, decided_by=user_id, decided_at=datetime.now(UTC), decision_note=note)
        )
        await self.session.refresh(proposal)
        return ProposalResponse.model_validate(proposal)


def _as_dict(p: RateFeedbackProposal) -> dict[str, object]:
    return {
        "status": p.status,
        "unit": p.unit,
        "current_rate": p.current_rate,
        "suggested_rate": p.suggested_rate,
        "confidence": p.confidence,
        "project_count": p.project_count,
        "line_count": p.line_count,
    }
