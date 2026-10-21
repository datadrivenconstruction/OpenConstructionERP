# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Business logic for the Resource Summary module.

Reads a project's BoQ positions read-only (via the BoQ position repository), rolls
their stored resource split up into a procurement statement with the pure
:mod:`app.modules.resource_summary.aggregate` library, and optionally freezes a run
as a stored snapshot. It writes nothing back to the BoQ.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.repository import PositionRepository
from app.modules.resource_summary.aggregate import (
    MaterialBuyList,
    ResourceStatement,
    aggregate_material_buy_list,
    aggregate_resource_statement,
)
from app.modules.resource_summary.models import ResourceStatementSnapshot

logger = logging.getLogger(__name__)


class ResourceSummaryService:
    """Assemble and persist the aggregated resource / procurement statement."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.position_repo = PositionRepository(session)

    async def _resolve_project_currency(self, project_id: uuid.UUID) -> tuple[str, dict[str, str]]:
        """Resolve ``(base_currency, {code: rate})`` for a project.

        Best-effort: any failure returns ``("", {})`` so the statement degrades to
        raw (unconverted) sums rather than a 500, exactly like the BoQ export
        rollup. The FX map lets a foreign-priced resource line be converted into the
        project base currency before it is aggregated.
        """
        try:
            from app.modules.projects.models import Project

            row = (
                await self.session.execute(select(Project.currency, Project.fx_rates).where(Project.id == project_id))
            ).first()
        except Exception:  # noqa: BLE001 - never break the statement on this lookup
            logger.debug("Project currency lookup failed for %s", project_id, exc_info=True)
            return "", {}
        if not row:
            return "", {}
        base = str(row[0]).strip()[:3].upper() if row[0] else ""
        raw = row[1] if isinstance(row[1], list) else []
        fx_map: dict[str, str] = {}
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            code = str(entry.get("code") or "").strip().upper()
            rate = str(entry.get("rate") or "").strip()
            if code and rate:
                fx_map[code] = rate
        return base, fx_map

    async def _load_position_dicts(
        self,
        project_id: uuid.UUID,
    ) -> tuple[list[dict], str, dict[str, str]]:
        """Load a project's positions as plain dicts plus its currency context.

        Returns ``(position_dicts, base_currency, fx_map)`` ready to hand to the
        pure aggregation library. Shared by every rollup so the statement and the
        buy-list read exactly the same positions the same way.
        """
        base_currency, fx_map = await self._resolve_project_currency(project_id)
        positions = await self.position_repo.list_for_project(project_id)
        position_dicts: list[dict] = [
            {"id": str(pos.id), "quantity": pos.quantity, "metadata_": pos.metadata_ or {}} for pos in positions
        ]
        return position_dicts, base_currency, fx_map

    async def generate(self, project_id: uuid.UUID) -> tuple[ResourceStatement, datetime]:
        """Build the live procurement statement for a project.

        Returns the statement plus the generation timestamp so a caller that also
        persists a snapshot stores the exact same moment it served.
        """
        position_dicts, base_currency, fx_map = await self._load_position_dicts(project_id)
        statement = aggregate_resource_statement(
            position_dicts,
            currency=base_currency,
            fx_rates=fx_map,
        )
        return statement, datetime.now(UTC)

    async def generate_buy_list(self, project_id: uuid.UUID) -> tuple[MaterialBuyList, datetime]:
        """Build the live material procurement buy-list for a project.

        Groups every position's material resource lines by material into a single
        purchase list. Degrades gracefully: a project with no material lines yields
        an empty list rather than an error.
        """
        position_dicts, base_currency, fx_map = await self._load_position_dicts(project_id)
        buy_list = aggregate_material_buy_list(
            position_dicts,
            currency=base_currency,
            fx_rates=fx_map,
        )
        return buy_list, datetime.now(UTC)

    async def requisition_coverage(self, project_id: uuid.UUID) -> dict[tuple[str, str], dict[str, Decimal]] | None:
        """What active requisitions hold of each BOQ resource, or None when it cannot be read.

        Procurement owns the figure; the buy list only shows it, so a build without
        the procurement module leaves the columns empty.
        """
        try:
            from app.modules.procurement.requisition_coverage import covered_by_source

            return await covered_by_source(self.session, project_id)
        except ImportError:
            return None

    async def save_snapshot(self, project_id: uuid.UUID) -> ResourceStatementSnapshot:
        """Generate the current statement and store it as a snapshot row."""
        statement, generated_at = await self.generate(project_id)
        payload = statement.to_dict()
        snapshot = ResourceStatementSnapshot(
            project_id=project_id,
            generated_at=generated_at,
            currency=statement.currency,
            total_cost=payload["total_cost"],
            line_count=statement.line_count,
            payload=payload,
        )
        self.session.add(snapshot)
        await self.session.flush()
        return snapshot

    async def list_snapshots(
        self,
        project_id: uuid.UUID,
        *,
        limit: int = 50,
    ) -> list[ResourceStatementSnapshot]:
        """List a project's saved statements, most recent first."""
        stmt = (
            select(ResourceStatementSnapshot)
            .where(ResourceStatementSnapshot.project_id == project_id)
            .order_by(ResourceStatementSnapshot.generated_at.desc())
            .limit(max(1, min(limit, 200)))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
