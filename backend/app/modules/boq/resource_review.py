# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The review of resource buildups the AI estimator stored the wrong size.

:mod:`app.modules.boq.resource_norms` says which stored buildups cannot price
their position. This module is what a person does about them. It lists the
positions of a project that fall in one of the review categories, and on
request re-derives ONE position's rows from the linked catalogue item, writing
per-unit norms. Rows without a catalogue link are only marked for review.

Nothing here runs unattended and nothing rewrites money: ``unit_rate`` and
``total`` are never touched, the re-derivation asks for an explicit
confirmation, and the previous rows are kept on the position so the step can
be reversed by hand. That is the platform's rule that AI results are never
applied without a person confirming them, applied to the repair of an AI
result.
"""

from __future__ import annotations

import logging
import uuid
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BOQ, Position
from app.modules.boq.repository import PositionRepository
from app.modules.boq.resource_norms import (
    REVIEW_CATEGORIES,
    REVIEW_KEY,
    UNIT_RATE_KEPT_KEY,
    BuildupVerdict,
    classify_buildup,
    clear_unit_rate_kept,
    rederive_rows_from_catalogue,
    resource_subtotal,
)

logger = logging.getLogger(__name__)


class ResourceNormReviewService:
    """List and, one position at a time, re-derive untrusted resource buildups."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.position_repo = PositionRepository(session)

    async def list_for_project(self, project_id: uuid.UUID) -> dict[str, Any]:
        """Every position of the project whose stored rows fall in a review category.

        Read-only. Returns the counts per category, how many of the flagged
        positions can be re-derived from a catalogue link, and one entry per
        position with what the reviewer needs to decide: the shape found, the
        stored rate, the sum the rows would have written over it, and whether
        an edit already had to keep the rate.
        """
        boq_rows = (await self.session.execute(select(BOQ.id, BOQ.name).where(BOQ.project_id == project_id))).all()
        boq_names = {row[0]: row[1] for row in boq_rows}
        by_boq = await self.position_repo.list_all_for_boqs(list(boq_names)) if boq_names else {}

        flagged: list[dict[str, Any]] = []
        scanned = 0
        for boq_id, positions in by_boq.items():
            for pos in positions:
                scanned += 1
                meta = pos.metadata_ if isinstance(pos.metadata_, dict) else {}
                verdict = classify_buildup(
                    source=pos.source,
                    metadata=meta,
                    quantity=pos.quantity,
                    resources=meta.get("resources"),
                )
                if verdict is None:
                    continue
                kept = meta.get(UNIT_RATE_KEPT_KEY)
                review = meta.get(REVIEW_KEY)
                created = getattr(pos, "created_at", None)
                flagged.append(
                    {
                        "position_id": str(pos.id),
                        "boq_id": str(boq_id),
                        "boq_name": boq_names.get(boq_id, ""),
                        "ordinal": pos.ordinal,
                        "description": pos.description,
                        "unit": pos.unit,
                        "quantity": str(pos.quantity),
                        "unit_rate": str(pos.unit_rate),
                        "resource_subtotal": format(resource_subtotal(meta.get("resources")), "f"),
                        "category": verdict.category,
                        "recoverable": verdict.recoverable,
                        "cost_item_id": str(meta["cost_item_id"]) if meta.get("cost_item_id") else None,
                        "row_count": verdict.row_count,
                        "flagged_rows": verdict.flagged_rows,
                        "unit_rate_kept_on_edit": kept if isinstance(kept, dict) else None,
                        "review_reason": meta.get("review_reason"),
                        "reviewed": review if isinstance(review, dict) else None,
                        "created_at": created.isoformat() if isinstance(created, datetime) else None,
                    }
                )

        counts = Counter(entry["category"] for entry in flagged)
        return {
            "project_id": str(project_id),
            "boq_count": len(boq_names),
            "positions_scanned": scanned,
            "positions_flagged": len(flagged),
            "recoverable": sum(1 for entry in flagged if entry["recoverable"]),
            "review_only": sum(1 for entry in flagged if not entry["recoverable"]),
            "counts": {category: counts.get(category, 0) for category in REVIEW_CATEGORIES},
            "positions": flagged,
        }

    async def review_position(
        self,
        position_id: uuid.UUID,
        *,
        confirm: bool,
        actor_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Re-derive one position's rows from its catalogue item, or mark it.

        A position that links a catalogue item with components is rewritten to
        per-unit norms, but only when ``confirm`` is true: the rows change, so
        the caller has to say so. A position without a usable link is marked
        (``metadata.review_reason``) and its rows are left exactly as they are.
        Money is never touched in either branch.

        Raises:
            HTTPException 404: the position does not exist.
            HTTPException 409: the owning BOQ is locked, or the rows are clean.
            HTTPException 422: the rows are recoverable and ``confirm`` is false.
        """
        from app.modules.boq.service import BOQService, _stamp_resource_breakdown
        from app.modules.costs.repository import CostItemRepository

        position = await self.position_repo.get_by_id(position_id)
        if position is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Position not found")
        await BOQService(self.session)._ensure_not_locked(position.boq_id)

        meta = dict(position.metadata_) if isinstance(position.metadata_, dict) else {}
        verdict = classify_buildup(
            source=position.source,
            metadata=meta,
            quantity=position.quantity,
            resources=meta.get("resources"),
        )
        if verdict is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This position's resource rows are not flagged for review",
            )

        cost_item = None
        raw_link = meta.get("cost_item_id")
        if verdict.recoverable and raw_link:
            try:
                cost_item = await CostItemRepository(self.session).get_by_id(uuid.UUID(str(raw_link)))
            except (ValueError, TypeError):
                cost_item = None
        components = getattr(cost_item, "components", None) if cost_item is not None else None
        new_rows = rederive_rows_from_catalogue(components) if verdict.recoverable else []

        if not new_rows:
            reason = verdict.category if not verdict.recoverable else "catalogue_row_unavailable"
            return await self._mark(position, meta, verdict, reason=reason, actor_id=actor_id)

        if not confirm:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    "Re-deriving replaces this position's resource rows with the catalogue's "
                    "per-unit norms. Repeat the call with confirm=true to proceed."
                ),
            )

        previous = meta.get("resources")
        before = resource_subtotal(previous)
        meta["resources"] = new_rows
        meta[REVIEW_KEY] = {
            "action": "rederived",
            "category": verdict.category,
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            "by": str(actor_id) if actor_id else None,
            "cost_item_id": str(raw_link),
            "cost_item_code": str(getattr(cost_item, "code", "") or ""),
            "previous_resources": previous if isinstance(previous, list) else [],
        }
        meta.pop("review_reason", None)
        clear_unit_rate_kept(meta)
        _stamp_resource_breakdown(meta)

        await self.position_repo.update_fields(
            position.id,
            metadata_=meta,
            validation_status="pending",
            version=int(position.version or 0) + 1,
        )
        await self.session.flush()
        await self.session.refresh(position)
        logger.info(
            "Resource rows of position %s re-derived from cost item %s (%s -> %s rows)",
            position.id,
            raw_link,
            len(previous) if isinstance(previous, list) else 0,
            len(new_rows),
        )
        return {
            "action": "rederived",
            "position_id": str(position.id),
            "category": verdict.category,
            "unit_rate": str(position.unit_rate),
            "total": str(position.total),
            "rows_before": len(previous) if isinstance(previous, list) else 0,
            "rows_after": len(new_rows),
            "resource_subtotal_before": format(before, "f"),
            "resource_subtotal_after": format(resource_subtotal(new_rows), "f"),
            "resources": new_rows,
        }

    async def _mark(
        self,
        position: Position,
        meta: dict[str, Any],
        verdict: BuildupVerdict,
        *,
        reason: str,
        actor_id: uuid.UUID | None,
    ) -> dict[str, Any]:
        """Leave the rows alone and say why a person has to look at them."""
        meta["review_reason"] = reason
        meta[REVIEW_KEY] = {
            "action": "marked",
            "category": verdict.category,
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            "by": str(actor_id) if actor_id else None,
        }
        await self.position_repo.update_fields(
            position.id,
            metadata_=meta,
            version=int(position.version or 0) + 1,
        )
        await self.session.flush()
        await self.session.refresh(position)
        return {
            "action": "marked",
            "position_id": str(position.id),
            "category": verdict.category,
            "review_reason": reason,
            "unit_rate": str(position.unit_rate),
            "total": str(position.total),
            "rows_before": verdict.row_count,
            "rows_after": verdict.row_count,
        }
