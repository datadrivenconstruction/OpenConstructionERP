# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Commissioning (Cx) service - business logic.

Stateless service layer. Owns:

- CRUD for systems, checklists, items and issues (with project-scoped access
  enforced by the router before every call).
- Live commissioning-readiness scoring via the pure
  :func:`app.modules.commissioning.validators.compute_readiness` helper.
- The gated ``commission_system`` action, which refuses to commission a system
  that still has an open functional checklist item or an open critical issue.
- A light, forward-only auto-advance of a system's lifecycle label as its
  functional results are recorded, so ``status`` reflects reality without a
  manual edit (the live readiness gate stays the source of truth).
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.json_merge import merge_metadata
from app.modules.commissioning.events import emit_system_commissioned
from app.modules.commissioning.models import (
    CxChecklist,
    CxChecklistItem,
    CxIssue,
    CxSystem,
)
from app.modules.commissioning.repository import (
    ChecklistRepository,
    IssueRepository,
    ItemRepository,
    SystemRepository,
)
from app.modules.commissioning.schemas import (
    ChecklistCreate,
    ChecklistUpdate,
    CommissionRequest,
    CxStatsResponse,
    IssueCreate,
    IssueUpdate,
    ItemCreate,
    ItemResultRequest,
    ItemUpdate,
    SystemCreate,
    SystemUpdate,
)
from app.modules.commissioning.validators import compute_readiness

logger = logging.getLogger(__name__)


def _counts_to_statuses(counts: dict[str, int]) -> list[str]:
    """Expand a ``{status: count}`` map into a flat list of status strings.

    Lets the pure ``compute_readiness`` helper (which takes an iterable of
    statuses) be fed from an aggregate ``GROUP BY`` count without a second code
    path. Item counts per system are small, so the expansion is negligible.
    """
    out: list[str] = []
    for item_status, count in counts.items():
        out.extend([item_status] * max(0, int(count)))
    return out


class CommissioningService:
    """Business logic for commissioning operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.system_repo = SystemRepository(session)
        self.checklist_repo = ChecklistRepository(session)
        self.item_repo = ItemRepository(session)
        self.issue_repo = IssueRepository(session)

    # ── Systems ───────────────────────────────────────────────────────────

    async def create_system(self, data: SystemCreate, user_id: str | None = None) -> CxSystem:
        """Create a new commissionable system."""
        await self._check_plant_item(data.project_id, data.plant_item_id)
        system = CxSystem(
            project_id=data.project_id,
            plant_item_id=data.plant_item_id,
            name=data.name,
            system_type=data.system_type,
            tag=data.tag,
            location=data.location,
            description=data.description,
            status=data.status,
            created_by=user_id,
            metadata_=data.metadata,
        )
        system = await self.system_repo.create(system)
        logger.info(
            "Cx system created: %s (%s) for project %s",
            data.name,
            data.system_type,
            data.project_id,
        )
        return system

    async def get_system(self, system_id: uuid.UUID) -> CxSystem:
        """Get a system by ID. Raises 404 if not found."""
        system = await self.system_repo.get_by_id(system_id)
        if system is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="System not found")
        return system

    async def list_systems(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status_filter: str | None = None,
        system_type: str | None = None,
    ) -> tuple[list[CxSystem], int]:
        """List systems for a project."""
        return await self.system_repo.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            status=status_filter,
            system_type=system_type,
        )

    async def _check_plant_item(self, project_id: uuid.UUID, plant_item_id: str | None) -> None:
        """A plant link is stored only when the plant register confirms the item in this project."""
        from app.core.project_scope_directory import plant_item_facts, plant_reader_registered

        if plant_item_id is None:
            return
        if not plant_reader_registered():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="No plant register is installed, so a plant item cannot be linked",
            )
        if await plant_item_facts(self.session, project_id, plant_item_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plant item not found in this project")

    async def update_system(self, system_id: uuid.UUID, data: SystemUpdate) -> CxSystem:
        """Update system fields.

        Moving a system to ``commissioned`` via a plain update is refused - the
        gated ``commission_system`` action is the only way to reach that state.
        """
        system = await self.get_system(system_id)

        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if fields.get("status") == "commissioned":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Use the commission action to commission a system",
            )
        if fields.get("plant_item_id") is not None:
            await self._check_plant_item(system.project_id, fields["plant_item_id"])
        if "metadata" in fields:
            incoming = fields.pop("metadata")
            fields["metadata_"] = (
                merge_metadata(getattr(system, "metadata_", None), incoming) if isinstance(incoming, dict) else incoming
            )

        if not fields:
            return system

        await self.system_repo.update_fields(system_id, **fields)
        await self.session.refresh(system)
        logger.info("Cx system updated: %s (fields=%s)", system_id, list(fields.keys()))
        return system

    async def delete_system(self, system_id: uuid.UUID) -> None:
        """Delete a system and everything under it."""
        await self.get_system(system_id)
        await self.system_repo.delete(system_id)
        logger.info("Cx system deleted: %s", system_id)

    # ── Readiness + commission gate ───────────────────────────────────────

    async def readiness_summary(self, system_id: uuid.UUID) -> dict[str, Any]:
        """Compute the live readiness breakdown for one system."""
        fmap = await self.system_repo.functional_status_counts([system_id])
        cmap = await self.system_repo.open_critical_issue_counts([system_id])
        statuses = _counts_to_statuses(fmap.get(system_id, {}))
        return compute_readiness(statuses, cmap.get(system_id, 0))

    async def readiness_map(self, system_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
        """Compute readiness breakdowns for many systems in two queries."""
        if not system_ids:
            return {}
        fmap = await self.system_repo.functional_status_counts(system_ids)
        cmap = await self.system_repo.open_critical_issue_counts(system_ids)
        return {sid: compute_readiness(_counts_to_statuses(fmap.get(sid, {})), cmap.get(sid, 0)) for sid in system_ids}

    async def commission_system(
        self,
        system_id: uuid.UUID,
        data: CommissionRequest,
        user_id: str | None = None,
    ) -> CxSystem:
        """Commission a system once it passes the readiness gate.

        Raises 400 with the concrete blocking reasons when the system still has
        an open functional checklist item, an open critical issue, or no
        applicable functional test to pass. Emits
        ``commissioning.system.commissioned`` on success.
        """
        system = await self.get_system(system_id)
        if system.status == "commissioned":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="System is already commissioned",
            )

        # Capture the scalars the event needs before the writes below.
        project_id = str(system.project_id)
        system_name = system.name
        system_type = system.system_type
        current_metadata = dict(system.metadata_ or {})

        # A project with a staged commissioning model (quality concept) commissions a
        # system only when its final stage is released.
        from app.core.commissioning_stage_guard import commissioning_blockers

        stage_blockers = await commissioning_blockers(self.session, system.project_id, system_id)
        if stage_blockers:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot commission system: {' '.join(stage_blockers)}",
            )

        readiness = await self.readiness_summary(system_id)
        if not readiness["can_commission"]:
            reasons = " ".join(readiness["blocking_reasons"]) or "System is not ready to be commissioned."
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot commission system: {reasons}",
            )

        fields: dict[str, Any] = {
            "status": "commissioned",
            "commissioned_at": datetime.now(UTC).isoformat(),
            "commissioned_by": user_id,
        }
        if data.note:
            current_metadata["commission_note"] = data.note
            fields["metadata_"] = current_metadata

        await self.system_repo.update_fields(system_id, **fields)
        await self.session.refresh(system)

        logger.info("Cx system commissioned: %s (project %s, user %s)", system_id, project_id, user_id)
        emit_system_commissioned(
            project_id=project_id,
            system_id=str(system_id),
            system_name=system_name,
            system_type=system_type,
            readiness_pct=float(readiness["readiness_pct"]),
            user_id=user_id,
        )
        return system

    # ── Checklists ────────────────────────────────────────────────────────

    async def create_checklist(
        self,
        system_id: uuid.UUID,
        data: ChecklistCreate,
        user_id: str | None = None,
    ) -> CxChecklist:
        """Create a checklist under a system."""
        await self.get_system(system_id)
        checklist = CxChecklist(
            system_id=system_id,
            kind=data.kind,
            stage_code=data.stage_code,
            title=data.title,
            description=data.description,
            created_by=user_id,
            metadata_=data.metadata,
        )
        checklist = await self.checklist_repo.create(checklist)
        logger.info("Cx checklist created: %s (%s) on system %s", data.title, data.kind, system_id)
        return checklist

    async def get_checklist(self, checklist_id: uuid.UUID) -> CxChecklist:
        """Get a checklist by ID. Raises 404 if not found."""
        checklist = await self.checklist_repo.get_by_id(checklist_id)
        if checklist is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Checklist not found")
        return checklist

    async def resolve_checklist_context(
        self,
        checklist_id: uuid.UUID,
    ) -> tuple[CxChecklist, CxSystem]:
        """Return a checklist plus its owning system (for access checks)."""
        checklist = await self.get_checklist(checklist_id)
        system = await self.get_system(checklist.system_id)
        return checklist, system

    async def list_checklists(
        self,
        system_id: uuid.UUID,
        *,
        kind: str | None = None,
    ) -> list[CxChecklist]:
        """List checklists for a system."""
        await self.get_system(system_id)
        return await self.checklist_repo.list_for_system(system_id, kind=kind)

    async def update_checklist(self, checklist_id: uuid.UUID, data: ChecklistUpdate) -> CxChecklist:
        """Update checklist fields."""
        checklist = await self.get_checklist(checklist_id)
        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            incoming = fields.pop("metadata")
            fields["metadata_"] = (
                merge_metadata(getattr(checklist, "metadata_", None), incoming)
                if isinstance(incoming, dict)
                else incoming
            )
        if not fields:
            return checklist
        await self.checklist_repo.update_fields(checklist_id, **fields)
        await self.session.refresh(checklist)
        return checklist

    async def delete_checklist(self, checklist_id: uuid.UUID) -> None:
        """Delete a checklist and its items."""
        await self.get_checklist(checklist_id)
        await self.checklist_repo.delete(checklist_id)

    # ── Checklist items ───────────────────────────────────────────────────

    async def create_item(
        self,
        checklist_id: uuid.UUID,
        data: ItemCreate,
        user_id: str | None = None,
    ) -> CxChecklistItem:
        """Create an item under a checklist."""
        await self.get_checklist(checklist_id)
        verified_at = datetime.now(UTC).isoformat() if data.status in ("pass", "fail", "na") else None
        item = CxChecklistItem(
            checklist_id=checklist_id,
            sequence=data.sequence,
            description=data.description,
            status=data.status,
            result_note=data.result_note,
            verified_by=user_id if verified_at else None,
            verified_at=verified_at,
            metadata_=data.metadata,
        )
        item = await self.item_repo.create(item)
        return item

    async def get_item(self, item_id: uuid.UUID) -> CxChecklistItem:
        """Get a checklist item by ID. Raises 404 if not found."""
        item = await self.item_repo.get_by_id(item_id)
        if item is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Checklist item not found")
        return item

    async def resolve_item_context(
        self,
        item_id: uuid.UUID,
    ) -> tuple[CxChecklistItem, CxChecklist, CxSystem]:
        """Return an item plus its checklist and owning system."""
        item = await self.get_item(item_id)
        checklist = await self.get_checklist(item.checklist_id)
        system = await self.get_system(checklist.system_id)
        return item, checklist, system

    async def list_items(self, checklist_id: uuid.UUID) -> list[CxChecklistItem]:
        """List items for a checklist."""
        await self.get_checklist(checklist_id)
        return await self.item_repo.list_for_checklist(checklist_id)

    async def update_item(self, item_id: uuid.UUID, data: ItemUpdate) -> CxChecklistItem:
        """Update item fields.

        When ``status`` is changed to a real result the verification timestamp
        is refreshed; setting it back to ``pending`` clears the timestamp and
        verifier.
        """
        item = await self.get_item(item_id)
        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            incoming = fields.pop("metadata")
            fields["metadata_"] = (
                merge_metadata(getattr(item, "metadata_", None), incoming) if isinstance(incoming, dict) else incoming
            )
        if "status" in fields:
            if fields["status"] == "pending":
                fields["verified_at"] = None
                fields["verified_by"] = None
            else:
                fields["verified_at"] = datetime.now(UTC).isoformat()
        if not fields:
            return item
        await self.item_repo.update_fields(item_id, **fields)
        await self.session.refresh(item)
        return item

    async def set_item_result(
        self,
        item_id: uuid.UUID,
        data: ItemResultRequest,
        user_id: str | None = None,
    ) -> CxChecklistItem:
        """Record a pass / fail / na result and auto-advance the system label."""
        item, checklist, system = await self.resolve_item_context(item_id)
        # Capture the pre-write scalars the auto-advance below compares against.
        checklist_kind = checklist.kind
        system_id = system.id
        system_status = system.status

        fields: dict[str, Any] = {
            "status": data.status,
            "verified_by": user_id,
            "verified_at": datetime.now(UTC).isoformat(),
        }
        if data.result_note is not None:
            fields["result_note"] = data.result_note
        await self.item_repo.update_fields(item_id, **fields)

        # Forward-only lifecycle auto-advance on a functional result. Never
        # touches an already-commissioned system and never regresses the label;
        # the live readiness gate is what actually protects the commission
        # action, so a lagging label can never let an unready system through.
        if checklist_kind == "functional" and system_status != "commissioned":
            readiness = await self.readiness_summary(system_id)
            new_status: str | None = None
            if readiness["can_commission"]:
                new_status = "tests_complete"
            elif system_status == "not_started":
                new_status = "in_progress"
            if new_status and new_status != system_status:
                await self.system_repo.update_fields(system_id, status=new_status)

        refreshed = await self.item_repo.get_by_id(item_id)
        assert refreshed is not None, "Item vanished between update and re-read"
        return refreshed

    async def delete_item(self, item_id: uuid.UUID) -> None:
        """Delete a checklist item."""
        await self.get_item(item_id)
        await self.item_repo.delete(item_id)

    # ── Issues ────────────────────────────────────────────────────────────

    async def create_issue(
        self,
        system_id: uuid.UUID,
        data: IssueCreate,
        user_id: str | None = None,
    ) -> CxIssue:
        """Create an issue against a system."""
        await self.get_system(system_id)
        closed_at = datetime.now(UTC).isoformat() if data.status == "closed" else None
        issue = CxIssue(
            system_id=system_id,
            description=data.description,
            severity=data.severity,
            status=data.status,
            resolution=data.resolution,
            raised_by=user_id,
            closed_by=user_id if closed_at else None,
            closed_at=closed_at,
            metadata_=data.metadata,
        )
        issue = await self.issue_repo.create(issue)
        logger.info("Cx issue raised: %s (%s) on system %s", data.description[:40], data.severity, system_id)
        return issue

    async def get_issue(self, issue_id: uuid.UUID) -> CxIssue:
        """Get an issue by ID. Raises 404 if not found."""
        issue = await self.issue_repo.get_by_id(issue_id)
        if issue is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Issue not found")
        return issue

    async def resolve_issue_context(self, issue_id: uuid.UUID) -> tuple[CxIssue, CxSystem]:
        """Return an issue plus its owning system (for access checks)."""
        issue = await self.get_issue(issue_id)
        system = await self.get_system(issue.system_id)
        return issue, system

    async def list_issues(
        self,
        system_id: uuid.UUID,
        *,
        status_filter: str | None = None,
    ) -> list[CxIssue]:
        """List issues for a system."""
        await self.get_system(system_id)
        return await self.issue_repo.list_for_system(system_id, status=status_filter)

    async def update_issue(
        self,
        issue_id: uuid.UUID,
        data: IssueUpdate,
        user_id: str | None = None,
    ) -> CxIssue:
        """Update issue fields, keeping the close bookkeeping consistent."""
        issue = await self.get_issue(issue_id)
        prior_status = issue.status
        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            incoming = fields.pop("metadata")
            fields["metadata_"] = (
                merge_metadata(getattr(issue, "metadata_", None), incoming) if isinstance(incoming, dict) else incoming
            )
        new_status = fields.get("status")
        if new_status == "closed" and prior_status != "closed":
            fields["closed_at"] = datetime.now(UTC).isoformat()
            fields["closed_by"] = user_id
        elif new_status == "open" and prior_status == "closed":
            fields["closed_at"] = None
            fields["closed_by"] = None
        if not fields:
            return issue
        await self.issue_repo.update_fields(issue_id, **fields)
        await self.session.refresh(issue)
        return issue

    async def delete_issue(self, issue_id: uuid.UUID) -> None:
        """Delete an issue."""
        await self.get_issue(issue_id)
        await self.issue_repo.delete(issue_id)

    # ── Stats ─────────────────────────────────────────────────────────────

    async def get_stats(self, project_id: uuid.UUID) -> CxStatsResponse:
        """Return aggregate commissioning statistics for a project."""
        raw = await self.system_repo.stats_for_project(project_id)

        # Average readiness across all systems in the project (systems with no
        # applicable functional item contribute 0, matching their display).
        systems, _ = await self.system_repo.list_for_project(project_id, offset=0, limit=10_000)
        system_ids = [s.id for s in systems]
        rmap = await self.readiness_map(system_ids)
        if system_ids:
            avg = sum(rmap[sid]["readiness_pct"] for sid in system_ids) / len(system_ids)
        else:
            avg = 0.0

        return CxStatsResponse(
            total_systems=raw["total_systems"],
            by_status=raw["by_status"],
            by_type=raw["by_type"],
            commissioned=raw["commissioned"],
            open_issues=raw["open_issues"],
            open_critical_issues=raw["open_critical_issues"],
            average_readiness_pct=round(avg, 2),
        )
