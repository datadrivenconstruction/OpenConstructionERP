# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Business logic for design-side site supervision.

Owns the two visit / entry state machines and wires the request path to the
pure, database-free domain logic in :mod:`app.modules.site_supervision.validators`
(plan-versus-fact, the hidden-works register, motivated refusal, change-sheet
links and the structured export). The analytics themselves are jurisdiction-
neutral and live in the pure module so they can be unit tested without a session.

Visit lifecycle:  planned -> conducted -> reported.
Entry lifecycle:  open -> addressed | refused_motivated | closed.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from fastapi import status as http_status

from app.modules.site_supervision import validators
from app.modules.site_supervision.models import SupervisionEntry, SupervisionVisit
from app.modules.site_supervision.repository import SupervisionRepository
from app.modules.site_supervision.schemas import (
    SupervisionEntryCreate,
    SupervisionEntryUpdate,
    SupervisionVisitCreate,
    SupervisionVisitUpdate,
)

logger = logging.getLogger(__name__)


class SupervisionService:
    """Business logic for the site-supervision module."""

    def __init__(self, session: object) -> None:
        self.session = session
        self.repo = SupervisionRepository(session)  # type: ignore[arg-type]

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    # ── Visit CRUD ──────────────────────────────────────────────────────

    async def create_visit(
        self,
        data: SupervisionVisitCreate,
        *,
        user_id: str | None = None,
    ) -> SupervisionVisit:
        visit = SupervisionVisit(
            project_id=data.project_id,
            planned_date=data.planned_date,
            actual_date=data.actual_date,
            visitor=data.visitor,
            discipline=data.discipline,
            status=data.status,
            summary=data.summary,
            photo_refs=list(data.photo_refs),
            metadata_=data.metadata,
            created_by=user_id,
        )
        visit = await self.repo.add_visit(visit)
        logger.info("Supervision visit created: %s for project %s", visit.id, visit.project_id)
        return visit

    async def get_visit(self, visit_id: uuid.UUID) -> SupervisionVisit:
        row = await self.repo.get_visit(visit_id)
        if row is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Supervision visit not found.",
            )
        return row

    async def list_visits(
        self,
        project_id: uuid.UUID,
        *,
        status: str | None = None,
        discipline: str | None = None,
    ) -> list[SupervisionVisit]:
        return await self.repo.list_visits(project_id, status=status, discipline=discipline)

    async def update_visit(
        self,
        visit_id: uuid.UUID,
        data: SupervisionVisitUpdate,
        *,
        user_id: str | None = None,
    ) -> SupervisionVisit:
        visit = await self.get_visit(visit_id)
        fields: dict[str, Any] = data.model_dump(exclude_unset=True)

        if "metadata" in fields:
            incoming = fields.pop("metadata")
            merged = dict(visit.metadata_ or {})
            if isinstance(incoming, dict):
                merged.update(incoming)
            fields["metadata_"] = merged

        for key, value in fields.items():
            setattr(visit, key, value)
        await self.session.flush()  # type: ignore[attr-defined]
        await self.session.refresh(visit)  # type: ignore[attr-defined]
        return visit

    async def delete_visit(self, visit_id: uuid.UUID) -> None:
        await self.get_visit(visit_id)
        await self.repo.delete_visit(visit_id)

    # ── Visit state machine ─────────────────────────────────────────────

    async def conduct_visit(self, visit_id: uuid.UUID) -> SupervisionVisit:
        """Mark a planned visit as conducted (planned -> conducted).

        Idempotent from ``conducted``; blocked once ``reported``. Stamps the
        actual date if one is not already recorded.
        """
        visit = await self.get_visit(visit_id)
        if visit.status == "reported":
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="A reported visit cannot be re-opened for conducting.",
            )
        if visit.actual_date is None:
            visit.actual_date = self._now().date()
        visit.status = "conducted"
        await self.session.flush()  # type: ignore[attr-defined]
        await self.session.refresh(visit)  # type: ignore[attr-defined]
        return visit

    async def report_visit(self, visit_id: uuid.UUID) -> SupervisionVisit:
        """Mark a conducted visit as reported (conducted -> reported).

        A visit must have been conducted before it can be reported.
        """
        visit = await self.get_visit(visit_id)
        if visit.status != "conducted":
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="Only a conducted visit can be reported.",
            )
        visit.status = "reported"
        await self.session.flush()  # type: ignore[attr-defined]
        await self.session.refresh(visit)  # type: ignore[attr-defined]
        return visit

    # ── Entry CRUD ──────────────────────────────────────────────────────

    async def create_entry(
        self,
        data: SupervisionEntryCreate,
        *,
        user_id: str | None = None,
    ) -> SupervisionEntry:
        # The entry inherits its tenancy from the visit so the project-scoped
        # guard need not join through the visit.
        visit = await self.get_visit(data.visit_id)
        entry = SupervisionEntry(
            visit_id=visit.id,
            project_id=visit.project_id,
            ordinal=data.ordinal,
            observation=data.observation,
            category=data.category,
            structured_fields=dict(data.structured_fields),
            links_to_change_ref=data.links_to_change_ref,
            status=data.status,
            created_by=user_id,
        )
        entry = await self.repo.add_entry(entry)
        logger.info("Supervision entry created: %s on visit %s", entry.id, visit.id)
        return entry

    async def get_entry(self, entry_id: uuid.UUID) -> SupervisionEntry:
        row = await self.repo.get_entry(entry_id)
        if row is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Supervision entry not found.",
            )
        return row

    async def list_entries_for_visit(self, visit_id: uuid.UUID) -> list[SupervisionEntry]:
        return await self.repo.list_entries_for_visit(visit_id)

    async def update_entry(
        self,
        entry_id: uuid.UUID,
        data: SupervisionEntryUpdate,
        *,
        user_id: str | None = None,
    ) -> SupervisionEntry:
        entry = await self.get_entry(entry_id)
        fields: dict[str, Any] = data.model_dump(exclude_unset=True)

        # Stamp resolved_at when the entry reaches a resolved state.
        new_status = fields.get("status")
        if new_status in ("addressed", "closed") and entry.resolved_at is None:
            entry.resolved_at = self._now()

        for key, value in fields.items():
            setattr(entry, key, value)
        await self.session.flush()  # type: ignore[attr-defined]
        await self.session.refresh(entry)  # type: ignore[attr-defined]
        return entry

    async def refuse_entry(self, entry_id: uuid.UUID, reason: str) -> SupervisionEntry:
        """Record a motivated refusal on an entry (-> refused_motivated).

        Delegates the reason-required rule to the pure validator; a blank reason
        surfaces as a 400.
        """
        entry = await self.get_entry(entry_id)
        try:
            validators.motivated_refusal(entry, reason)
        except ValueError as exc:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        entry.resolved_at = self._now()
        await self.session.flush()  # type: ignore[attr-defined]
        await self.session.refresh(entry)  # type: ignore[attr-defined]
        return entry

    async def delete_entry(self, entry_id: uuid.UUID) -> None:
        await self.get_entry(entry_id)
        await self.repo.delete_entry(entry_id)

    # ── Analytics (delegate to the pure domain module) ──────────────────

    async def plan_vs_fact(self, project_id: uuid.UUID) -> dict[str, Any]:
        visits = await self.repo.list_visits(project_id)
        return validators.plan_vs_fact(visits)

    async def hidden_works_register(self, project_id: uuid.UUID) -> list[dict[str, Any]]:
        entries = await self.repo.list_entries_for_project(project_id, category="hidden_works")
        return validators.hidden_works_register(entries)

    async def change_sheet_links(self, project_id: uuid.UUID) -> list[dict[str, Any]]:
        entries = await self.repo.list_entries_for_project(project_id)
        return validators.change_sheet_links(entries)

    async def plan_coverage(self, project_id: uuid.UUID) -> dict[str, Any]:
        visits = await self.repo.list_visits(project_id)
        entries = await self.repo.list_entries_for_project(project_id)
        return validators.supervision_plan_coverage(visits, entries)

    async def export_visit(self, visit_id: uuid.UUID) -> dict[str, Any]:
        visit = await self.get_visit(visit_id)
        entries = await self.repo.list_entries_for_visit(visit_id)
        return validators.export_visit(visit, entries)


__all__ = ["SupervisionService"]
