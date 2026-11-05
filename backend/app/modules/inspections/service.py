# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Inspections service - business logic for quality inspection management."""

import logging
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import publish_after_commit
from app.core.i18n import get_locale
from app.core.json_merge import merge_metadata
from app.core.validation.engine import ValidationReport, validation_engine
from app.core.validation.failure import introduced_errors
from app.core.validation.quality_rules import rule_errors_detail, warning_findings
from app.modules.inspections.models import QualityInspection
from app.modules.inspections.repository import InspectionRepository
from app.modules.inspections.schemas import InspectionCreate, InspectionUpdate
from app.modules.inspections.validators import INSPECTIONS_RULE_SET

logger = logging.getLogger(__name__)


def _validate_checklist_structure(checklist: list[dict[str, Any]]) -> None:
    """Validate checklist_data JSON structure.

    Each item must have at minimum a ``question`` field (non-empty string).
    ``response_type`` must be one of the known types if provided.

    Raises:
        HTTPException 422 if structure is invalid.
    """
    valid_response_types = {"yes_no", "pass_fail", "numeric", "text", "rating"}
    for idx, item in enumerate(checklist):
        if not isinstance(item, dict):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Checklist item {idx} must be a dict, got {type(item).__name__}",
            )
        question = item.get("question", "")
        if not question or not isinstance(question, str) or len(question.strip()) < 1:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Checklist item {idx} must have a non-empty 'question' field",
            )
        resp_type = item.get("response_type", "yes_no")
        if resp_type and resp_type not in valid_response_types:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    f"Checklist item {idx} has invalid response_type '{resp_type}'. "
                    f"Valid types: {sorted(valid_response_types)}"
                ),
            )


# ── Allowed inspection status transitions ─────────────────────────────────────

_INSPECTION_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "scheduled": {"in_progress", "cancelled"},
    "in_progress": {"completed", "failed", "cancelled"},
    "completed": set(),  # terminal
    "failed": {"scheduled"},  # allow re-inspection
    "cancelled": {"scheduled"},  # allow rescheduling
}


class InspectionService:
    """Business logic for inspection operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = InspectionRepository(session)

    async def _run(
        self, state: dict[str, Any], inspection_id: str, project_id: uuid.UUID, operation: str
    ) -> ValidationReport:
        return await validation_engine.validate(
            data={"inspection": {**state, "id": inspection_id}},
            rule_sets=[INSPECTIONS_RULE_SET],
            target_type="inspection",
            target_id=inspection_id,
            project_id=str(project_id),
            metadata={"locale": get_locale(), "operation": operation},
        )

    async def _check_rules(
        self,
        state: dict[str, Any],
        *,
        inspection_id: str,
        project_id: uuid.UUID,
        operation: str,
        before: dict[str, Any] | None = None,
    ) -> ValidationReport:
        """Run the ``inspections`` rule set over the record as it will be stored; ERROR findings answer 422.

        WARNING findings do not block: the caller attaches them to the response.
        """
        report = await self._run(state, inspection_id, project_id, operation)

        async def stored() -> ValidationReport:
            return await self._run(before or {}, inspection_id, project_id, operation)

        blocking = await introduced_errors(report, stored if before is not None else None)
        if blocking:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=rule_errors_detail(
                    report,
                    f"This inspection cannot be saved ({operation}) until the errors listed below are corrected.",
                    blocking,
                ),
            )
        return report

    async def check_merge(self, inspection: QualityInspection, changes: dict[str, Any]) -> None:
        """Run the rules over an offline merge before it is written; only errors the merge introduces block."""
        if not changes:
            return
        prior = self._state_of(inspection)
        state = {**prior, **{k: v for k, v in changes.items() if k in prior}}
        await self._check_rules(
            state,
            inspection_id=str(inspection.id),
            project_id=inspection.project_id,
            operation="merge",
            before=prior,
        )

    @staticmethod
    def _state_of(inspection: QualityInspection) -> dict[str, Any]:
        return {
            "status": inspection.status,
            "result": inspection.result,
            "inspector_id": inspection.inspector_id,
            "inspection_date": inspection.inspection_date,
            "checklist_data": inspection.checklist_data,
        }

    async def create_inspection(
        self,
        data: InspectionCreate,
        user_id: str | None = None,
    ) -> QualityInspection:
        """Create a new inspection with auto-generated number.

        Validates checklist_data structure before persisting.
        """
        checklist = [entry.model_dump() for entry in data.checklist_data]
        if checklist:
            _validate_checklist_structure(checklist)

        report = await self._check_rules(
            {
                "status": data.status,
                "result": data.result,
                "inspector_id": data.inspector_id,
                "inspection_date": data.inspection_date,
                "checklist_data": checklist,
            },
            inspection_id="",
            project_id=data.project_id,
            operation="create",
        )
        inspection = QualityInspection(
            project_id=data.project_id,
            inspection_type=data.inspection_type,
            title=data.title,
            description=data.description,
            location=data.location,
            wbs_id=data.wbs_id,
            inspector_id=data.inspector_id,
            inspection_date=data.inspection_date,
            status=data.status,
            result=data.result,
            checklist_data=checklist,
            created_by=user_id,
            metadata_=data.metadata,
        )
        inspection = await self.repo.create(inspection)
        inspection.validation_warnings = warning_findings(report)  # type: ignore[attr-defined]
        # The repository assigns inspection_number (with a collision retry) at
        # insert time, so read the committed value back for logging.
        inspection_number = inspection.inspection_number
        logger.info(
            "Inspection created: %s (%s) for project %s",
            inspection_number,
            data.inspection_type,
            data.project_id,
        )
        if inspection.status == "scheduled":
            self._announce_scheduled(inspection, user_id)
        return inspection

    def _announce_scheduled(self, inspection: QualityInspection, user_id: str | None) -> None:
        """Tell the inspector an inspection is booked for them, once it commits.

        ``core.event_handlers._notify_inspection_due`` turns this into a
        notification for ``inspector_id``. An inspection with no inspector has
        nobody to tell, and the handler skips an inspector who booked it.
        """
        if not inspection.inspector_id:
            return
        publish_after_commit(
            self.session,
            "inspection.scheduled",
            data={
                "project_id": str(inspection.project_id),
                "inspection_id": str(inspection.id),
                "inspection_number": inspection.inspection_number,
                "title": inspection.title,
                "inspector_id": str(inspection.inspector_id),
                "inspection_date": inspection.inspection_date,
                "scheduled_by": str(user_id) if user_id else None,
            },
            source_module="inspections",
        )

    async def get_inspection(self, inspection_id: uuid.UUID) -> QualityInspection:
        """Get inspection by ID. Raises 404 if not found."""
        inspection = await self.repo.get_by_id(inspection_id)
        if inspection is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Inspection not found",
            )
        return inspection

    async def list_inspections(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        inspection_type: str | None = None,
        status_filter: str | None = None,
    ) -> tuple[list[QualityInspection], int]:
        """List inspections for a project."""
        return await self.repo.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            inspection_type=inspection_type,
            status=status_filter,
        )

    async def update_inspection(
        self,
        inspection_id: uuid.UUID,
        data: InspectionUpdate,
        user_id: str | None = None,
    ) -> QualityInspection:
        """Update inspection fields.

        Scheduling it again (``failed`` back to ``scheduled``), moving its date
        or handing it to another inspector tells the inspector, the same way
        creating a scheduled inspection does.
        """
        inspection = await self.get_inspection(inspection_id)
        before = (inspection.status, str(inspection.inspector_id or ""), inspection.inspection_date)

        # ``completed`` is terminal (see _INSPECTION_STATUS_TRANSITIONS) so it
        # stays locked. ``failed`` is NOT terminal: the FSM allows
        # failed → scheduled for re-inspection, so edits must be permitted and
        # the transition validator below enforces that only valid status
        # changes go through.
        if inspection.status == "completed":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot edit an inspection with status '{inspection.status}'",
            )

        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        # Merge a partial metadata patch into the existing column instead of
        # replacing it wholesale, so a PATCH touching one key keeps the rest.
        if "metadata" in fields:
            incoming_meta = fields.pop("metadata")
            if isinstance(incoming_meta, dict):
                fields["metadata_"] = merge_metadata(getattr(inspection, "metadata_", None), incoming_meta)
            else:
                fields["metadata_"] = incoming_meta

        # Validate status transition if status is being changed
        new_status = fields.get("status")
        if new_status is not None and new_status != inspection.status:
            allowed = _INSPECTION_STATUS_TRANSITIONS.get(inspection.status, set())
            if new_status not in allowed:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Cannot transition inspection from '{inspection.status}' to "
                        f"'{new_status}'. Allowed transitions: "
                        f"{', '.join(sorted(allowed)) or 'none'}"
                    ),
                )

        # Completion records the outcome and raises the follow-up events, so it
        # only goes through complete_inspection; a bare status patch would close
        # the inspection with no result and no punch-list or closeout signal.
        if new_status == "completed" and inspection.status != "completed":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Complete an inspection with its result (pass, fail or partial), not by editing the status.",
            )

        if "checklist_data" in fields and fields["checklist_data"] is not None:
            fields["checklist_data"] = [
                entry.model_dump() if hasattr(entry, "model_dump") else entry for entry in fields["checklist_data"]
            ]
            _validate_checklist_structure(fields["checklist_data"])

        if not fields:
            return inspection

        prior = self._state_of(inspection)
        state = {**prior, **{k: v for k, v in fields.items() if k in prior}}
        report = await self._check_rules(
            state,
            inspection_id=str(inspection_id),
            project_id=inspection.project_id,
            operation="update",
            before=prior,
        )

        await self.repo.update_fields(inspection_id, **fields)
        await self.session.refresh(inspection)
        logger.info("Inspection updated: %s (fields=%s)", inspection_id, list(fields.keys()))
        after = (inspection.status, str(inspection.inspector_id or ""), inspection.inspection_date)
        if inspection.status == "scheduled" and after != before:
            self._announce_scheduled(inspection, user_id)
        inspection.validation_warnings = warning_findings(report)  # type: ignore[attr-defined]
        return inspection

    async def delete_inspection(self, inspection_id: uuid.UUID) -> None:
        """Delete an inspection that has not been completed.

        A completed inspection is the quality record: update_inspection locks
        it, a failed result has already raised punch items from it, and NCRs
        point at it by ``linked_inspection_id``. A scheduled one that will not
        happen is cancelled instead.
        """
        inspection = await self.get_inspection(inspection_id)
        if inspection.status == "completed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot delete a completed inspection: it is the quality record and is kept.",
            )
        await self.repo.delete(inspection_id)
        logger.info("Inspection deleted: %s", inspection_id)

    async def complete_inspection(
        self,
        inspection_id: uuid.UUID,
        result: str,
        completed_by: str | None = None,
    ) -> QualityInspection:
        """Mark an inspection as completed with a required result.

        Args:
            inspection_id: Inspection to complete.
            result: Must be one of ``pass``, ``fail``, or ``partial``.
            completed_by: User completing it. Becomes the inspector when none
                was named, because the sign-off dialog has no inspector field.

        Emits ``inspection.completed.failed`` event when result is ``fail``
        or ``partial`` to trigger punchlist item creation flow, and
        ``inspection.completed.passed`` on a pass.
        """
        if result not in ("pass", "fail", "partial"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Result must be 'pass', 'fail', or 'partial', got '{result}'",
            )

        inspection = await self.get_inspection(inspection_id)
        # FSM gate: ``complete`` is the scheduled → in_progress → completed
        # capstone transition. We accept it from ``in_progress`` (normal
        # path) and from ``scheduled`` (one-step shortcut for short
        # inspections - auto-walks through in_progress). Anything else
        # (completed / cancelled / failed) is a 400.
        if inspection.status == "completed":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Inspection is already completed",
            )
        if inspection.status == "cancelled":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot complete a cancelled inspection",
            )
        if inspection.status == "failed":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Inspection is in 'failed' state - reschedule it first "
                    "(failed → scheduled) before completing again."
                ),
            )
        if inspection.status not in ("scheduled", "in_progress"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Cannot complete inspection from status "
                    f"'{inspection.status}'. Must be 'scheduled' or 'in_progress'."
                ),
            )

        fields: dict[str, Any] = {"status": "completed", "result": result}
        if completed_by and not inspection.inspector_id:
            fields["inspector_id"] = completed_by

        report = await self._check_rules(
            {**self._state_of(inspection), **fields},
            inspection_id=str(inspection_id),
            project_id=inspection.project_id,
            operation="complete",
        )
        await self.repo.update_fields(inspection_id, **fields)
        await self.session.refresh(inspection)
        inspection.validation_warnings = warning_findings(report)  # type: ignore[attr-defined]
        logger.info("Inspection completed: %s (result=%s)", inspection_id, result)

        # Emit event for failed/partial inspections -> punchlist creation flow
        if result in ("fail", "partial"):
            # Collect failed checklist items for the event payload
            checklist = inspection.checklist_data or []
            failed_items = [
                item for item in checklist if isinstance(item, dict) and item.get("response") in ("fail", "no", "false")
            ]
            # Deferred to the commit: the punchlist bridge inserts
            # PunchItem(project_id=...) from its own session.
            publish_after_commit(
                self.session,
                "inspection.completed.failed",
                data={
                    "project_id": str(inspection.project_id),
                    "inspection_id": str(inspection_id),
                    "inspection_number": inspection.inspection_number,
                    "result": result,
                    "failed_items": failed_items,
                },
                source_module="inspections",
            )
        else:
            # A pass is closure evidence too: closeout marks a built handover
            # package stale on it, the same as on a failure.
            publish_after_commit(
                self.session,
                "inspection.completed.passed",
                data={
                    "project_id": str(inspection.project_id),
                    "inspection_id": str(inspection_id),
                    "inspection_number": inspection.inspection_number,
                    "result": result,
                },
                source_module="inspections",
            )

        return inspection
