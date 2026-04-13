"""Submittals service — business logic for submittal management."""

import logging
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.submittals.models import Submittal
from app.modules.submittals.repository import SubmittalRepository
from app.modules.submittals.schemas import SubmittalCreate, SubmittalUpdate

logger = logging.getLogger(__name__)


async def _safe_publish(name: str, data: dict, source_module: str = "oe_submittals") -> None:
    """Publish an event, swallowing errors so business logic continues."""
    try:
        from app.core.events import event_bus

        await event_bus.publish(name, data, source_module=source_module)
    except Exception as exc:
        logger.debug("Event publish failed for %s: %s", name, exc)

# ── Allowed submittal status transitions ──────────────────────────────────────

_SUBMITTAL_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"submitted"},
    "submitted": {"under_review", "approved", "approved_as_noted", "revise_and_resubmit", "rejected"},
    "under_review": {"approved", "approved_as_noted", "revise_and_resubmit", "rejected"},
    "approved": {"closed"},
    "approved_as_noted": {"closed"},
    "revise_and_resubmit": {"draft", "submitted"},
    "rejected": {"draft", "closed"},
    "closed": set(),  # terminal
}


class SubmittalService:
    """Business logic for submittal operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = SubmittalRepository(session)

    async def create_submittal(
        self,
        data: SubmittalCreate,
        user_id: str | None = None,
    ) -> Submittal:
        """Create a new submittal with auto-generated number.

        Ball-in-court defaults to the submitting organization's creator when
        status is 'draft', or to the reviewer when status is 'submitted'.
        """
        submittal_number = await self.repo.next_submittal_number(data.project_id)

        # Auto-set ball_in_court based on initial status
        ball_in_court = data.ball_in_court
        if ball_in_court is None:
            if data.status == "submitted" and data.reviewer_id:
                ball_in_court = data.reviewer_id
            elif user_id is not None:
                ball_in_court = user_id

        submittal = Submittal(
            project_id=data.project_id,
            submittal_number=submittal_number,
            title=data.title,
            spec_section=data.spec_section,
            submittal_type=data.submittal_type,
            status=data.status,
            ball_in_court=ball_in_court,
            current_revision=data.current_revision,
            submitted_by_org=data.submitted_by_org,
            reviewer_id=data.reviewer_id,
            approver_id=data.approver_id,
            date_submitted=data.date_submitted,
            date_required=data.date_required,
            date_returned=data.date_returned,
            linked_boq_item_ids=data.linked_boq_item_ids,
            created_by=user_id,
            metadata_=data.metadata,
        )
        submittal = await self.repo.create(submittal)
        logger.info(
            "Submittal created: %s (%s) for project %s",
            submittal_number,
            data.submittal_type,
            data.project_id,
        )
        return submittal

    async def get_submittal(self, submittal_id: uuid.UUID) -> Submittal:
        submittal = await self.repo.get_by_id(submittal_id)
        if submittal is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Submittal not found",
            )
        return submittal

    async def list_submittals(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status_filter: str | None = None,
        submittal_type: str | None = None,
    ) -> tuple[list[Submittal], int]:
        return await self.repo.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            status=status_filter,
            submittal_type=submittal_type,
        )

    async def update_submittal(
        self,
        submittal_id: uuid.UUID,
        data: SubmittalUpdate,
    ) -> Submittal:
        submittal = await self.get_submittal(submittal_id)

        if submittal.status == "closed":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot edit a closed submittal",
            )

        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        # Validate status transition if status is being changed
        new_status = fields.get("status")
        if new_status is not None and new_status != submittal.status:
            allowed = _SUBMITTAL_STATUS_TRANSITIONS.get(submittal.status, set())
            if new_status not in allowed:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Cannot transition submittal from '{submittal.status}' to "
                        f"'{new_status}'. Allowed transitions: "
                        f"{', '.join(sorted(allowed)) or 'none'}"
                    ),
                )

        if not fields:
            return submittal

        await self.repo.update_fields(submittal_id, **fields)
        await self.session.refresh(submittal)
        logger.info("Submittal updated: %s (fields=%s)", submittal_id, list(fields.keys()))
        return submittal

    async def delete_submittal(self, submittal_id: uuid.UUID) -> None:
        await self.get_submittal(submittal_id)
        await self.repo.delete(submittal_id)
        logger.info("Submittal deleted: %s", submittal_id)

    async def submit_submittal(self, submittal_id: uuid.UUID) -> Submittal:
        """Move submittal from draft (or revise_and_resubmit) to submitted.

        Revision numbering:
        - First submission (``draft`` → ``submitted``): sets ``current_revision`` to 1.
        - Resubmission after ``revise_and_resubmit``: increments by 1.
        Ball-in-court moves to the reviewer. Publishes ``submittal.submitted`` event.
        """
        submittal = await self.get_submittal(submittal_id)
        allowed = ("draft", "revise_and_resubmit")
        if submittal.status not in allowed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Can only submit from draft or revise_and_resubmit status, "
                    f"current: {submittal.status}"
                ),
            )

        from datetime import UTC, datetime

        fields: dict[str, Any] = {
            "status": "submitted",
            "date_submitted": datetime.now(UTC).strftime("%Y-%m-%d"),
            "date_returned": None,
        }

        # Revision management:
        # First submit → revision 1; resubmit → previous + 1.
        current_rev = submittal.current_revision or 0
        if submittal.status == "revise_and_resubmit":
            fields["current_revision"] = current_rev + 1
        elif current_rev == 0:
            fields["current_revision"] = 1

        # Ball-in-court moves to reviewer
        if submittal.reviewer_id:
            fields["ball_in_court"] = str(submittal.reviewer_id)

        await self.repo.update_fields(submittal_id, **fields)
        await self.session.refresh(submittal)

        await _safe_publish(
            "submittal.submitted",
            {
                "project_id": str(submittal.project_id),
                "submittal_id": str(submittal_id),
                "submittal_number": getattr(submittal, "submittal_number", None),
                "title": submittal.title,
                "current_revision": fields.get("current_revision", current_rev),
                "reviewer_id": str(submittal.reviewer_id) if submittal.reviewer_id else None,
                "submitted_by": str(submittal.created_by) if submittal.created_by else None,
            },
        )

        logger.info("Submittal submitted: %s (rev %s)", submittal_id, submittal.current_revision)
        return submittal

    async def review_submittal(
        self,
        submittal_id: uuid.UUID,
        new_status: str,
        reviewer_id: str,
    ) -> Submittal:
        """Review a submittal (approve, reject, etc.).

        Ball-in-court updates depend on the decision:
        - ``approved`` / ``approved_as_noted``: stays with reviewer (done)
        - ``revise_and_resubmit`` / ``rejected``: back to submitter
        Publishes ``submittal.reviewed`` event with the decision.
        """
        submittal = await self.get_submittal(submittal_id)
        if submittal.status not in ("submitted", "under_review"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot review submittal with status '{submittal.status}'",
            )

        from datetime import UTC, datetime

        # Determine ball-in-court based on decision
        if new_status in ("revise_and_resubmit", "rejected"):
            ball = submittal.created_by
        else:
            ball = reviewer_id

        fields: dict[str, Any] = {
            "status": new_status,
            "reviewer_id": reviewer_id,
            "date_returned": datetime.now(UTC).strftime("%Y-%m-%d"),
            "ball_in_court": ball,
        }
        await self.repo.update_fields(submittal_id, **fields)
        await self.session.refresh(submittal)

        await _safe_publish(
            "submittal.reviewed",
            {
                "project_id": str(submittal.project_id),
                "submittal_id": str(submittal_id),
                "title": submittal.title,
                "decision": new_status,
                "reviewer_id": reviewer_id,
                "ball_in_court": str(ball) if ball else None,
                "submitted_by": str(submittal.created_by) if submittal.created_by else None,
            },
        )

        logger.info("Submittal reviewed: %s -> %s by %s", submittal_id, new_status, reviewer_id)
        return submittal

    async def approve_submittal(
        self,
        submittal_id: uuid.UUID,
        approver_id: str,
    ) -> Submittal:
        """Final approval of a submittal.

        Only submittals that are currently ``submitted`` or ``under_review``
        can receive final approval.  Ball-in-court is cleared on approval.
        Publishes ``submittal.approved`` event.
        """
        submittal = await self.get_submittal(submittal_id)
        allowed = ("submitted", "under_review")
        if submittal.status not in allowed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Cannot approve submittal with status '{submittal.status}'. "
                    f"Expected one of: {', '.join(allowed)}"
                ),
            )

        from datetime import UTC, datetime

        fields: dict[str, Any] = {
            "status": "approved",
            "approver_id": approver_id,
            "date_returned": datetime.now(UTC).strftime("%Y-%m-%d"),
            "ball_in_court": None,
        }
        await self.repo.update_fields(submittal_id, **fields)
        await self.session.refresh(submittal)

        await _safe_publish(
            "submittal.approved",
            {
                "project_id": str(submittal.project_id),
                "submittal_id": str(submittal_id),
                "title": submittal.title,
                "approver_id": approver_id,
                "submitted_by": str(submittal.created_by) if submittal.created_by else None,
            },
        )

        logger.info("Submittal approved: %s by %s", submittal_id, approver_id)
        return submittal
