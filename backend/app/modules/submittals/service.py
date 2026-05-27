"""‌⁠‍Submittals service — business logic for submittal management."""

import logging
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.submittals.models import Submittal
from app.modules.submittals.repository import SubmittalRepository
from app.modules.submittals.schemas import SubmittalCreate, SubmittalUpdate

logger = logging.getLogger(__name__)

# Max attempts when ``next_submittal_number`` collides under concurrent
# creates. Five gives ample slack for high-throughput contention without
# letting a buggy / faulty unique-constraint state pin the request loop.
_MAX_NUMBER_RETRIES = 5

# Transitions a non-MANAGER caller is allowed to drive via PATCH
# ``/{id}`` alone. Anything that approves, rejects, or closes a submittal
# is funnelled through the dedicated ``/submit``, ``/review``, ``/approve``
# endpoints so the role-gate and audit logging in those handlers cannot
# be bypassed by a plain editor PATCHing ``status=approved`` directly.
_PATCH_ALLOWED_STATUSES: frozenset[str] = frozenset({"draft", "submitted", "under_review"})


async def _safe_publish(name: str, data: dict, source_module: str = "oe_submittals") -> None:
    """‌⁠‍Publish an event, swallowing errors so business logic continues."""
    try:
        from app.core.events import event_bus

        event_bus.publish_detached(name, data, source_module=source_module)
    except Exception as exc:
        logger.debug("Event publish failed for %s: %s", name, exc)


def _log_state_change(
    *,
    submittal_id: uuid.UUID | str,
    submittal_number: str | None,
    project_id: uuid.UUID | str | None,
    prior_status: str,
    new_status: str,
    actor_id: str | None,
    revision: int | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Emit a single structured log line for an FSM transition.

    The log payload is JSON-friendly (flat key/value pairs) so the prod
    log shipper can index ``from_status`` / ``to_status`` / ``actor`` for
    submittal-cycle dashboards. Calling this in addition to
    :func:`audit_log.log_activity` is intentional — the audit row lands
    in a DB table the customer can wipe, the log line lands on the
    immutable log-shipper sink.
    """
    payload: dict[str, Any] = {
        "event": "submittal.state_change",
        "submittal_id": str(submittal_id),
        "submittal_number": submittal_number,
        "project_id": str(project_id) if project_id is not None else None,
        "from_status": prior_status,
        "to_status": new_status,
        "actor_id": actor_id,
        "revision": revision,
    }
    if extra:
        payload.update({k: v for k, v in extra.items() if k not in payload})
    logger.info("submittal.state_change %s", payload)


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
    """‌⁠‍Business logic for submittal operations."""

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

        Concurrent-create race: ``next_submittal_number`` computes the next
        ordinal from ``MAX(suffix)+1`` which has TOCTOU semantics. Two
        parallel POSTs can read the same MAX and both attempt to insert
        ``SUB-005``. The unique constraint on
        ``(project_id, submittal_number)`` (alembic
        ``v3099_submittals_unique_number``) turns the second insert into
        ``IntegrityError`` and we simply re-roll the number. After
        ``_MAX_NUMBER_RETRIES`` collisions we surface 409 rather than spin.
        """
        # Auto-set ball_in_court based on initial status
        ball_in_court = data.ball_in_court
        if ball_in_court is None:
            if data.status == "submitted" and data.reviewer_id:
                ball_in_court = data.reviewer_id
            elif user_id is not None:
                ball_in_court = user_id

        last_exc: Exception | None = None
        for attempt in range(_MAX_NUMBER_RETRIES):
            submittal_number = await self.repo.next_submittal_number(data.project_id)
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
            try:
                submittal = await self.repo.create(submittal)
            except IntegrityError as exc:
                last_exc = exc
                logger.warning(
                    "Submittal-number collision on attempt %d for project %s (number=%s); retrying",
                    attempt + 1,
                    data.project_id,
                    submittal_number,
                )
                continue
            logger.info(
                "Submittal created: %s (%s) for project %s",
                submittal_number,
                data.submittal_type,
                data.project_id,
            )
            return submittal

        # All retries exhausted — translate to 409 so the caller can retry
        # at the HTTP layer with a clear contract.
        logger.error(
            "Submittal-number collision still unresolved after %d retries for project %s",
            _MAX_NUMBER_RETRIES,
            data.project_id,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Could not allocate a unique submittal number after {_MAX_NUMBER_RETRIES} attempts; please retry."
            ),
        ) from last_exc

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
            # Approval / rejection / closure must go through the role-
            # gated handlers — a plain editor with ``submittals.update``
            # would otherwise be able to PATCH ``status=approved`` and
            # bypass the MANAGER gate on ``/approve`` + the rate limiter.
            if new_status not in _PATCH_ALLOWED_STATUSES:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        f"Transition to '{new_status}' must be performed via the "
                        "dedicated /submit, /review, or /approve endpoint."
                    ),
                )

        if not fields:
            return submittal

        prior_status = submittal.status
        await self.repo.update_fields(submittal_id, **fields)
        # ``update_fields`` expires the row — any subsequent lazy attribute
        # access on the stale ORM object triggers MissingGreenlet under
        # async context. Re-fetch a fresh row instead of calling
        # ``session.refresh`` so downstream callers see loaded columns.
        fresh = await self.repo.get_by_id(submittal_id)
        logger.info("Submittal updated: %s (fields=%s)", submittal_id, list(fields.keys()))
        if new_status is not None and new_status != prior_status:
            _log_state_change(
                submittal_id=submittal_id,
                submittal_number=getattr(fresh or submittal, "submittal_number", None),
                project_id=getattr(fresh or submittal, "project_id", None),
                prior_status=prior_status,
                new_status=new_status,
                actor_id=None,  # PATCH path: actor visible only at router layer
                extra={"source": "patch"},
            )
        return fresh or submittal

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
                detail=(f"Can only submit from draft or revise_and_resubmit status, current: {submittal.status}"),
            )

        from datetime import UTC, datetime

        fields: dict[str, Any] = {
            "status": "submitted",
            "date_submitted": datetime.now(UTC).strftime("%Y-%m-%d"),
            "date_returned": None,
        }

        # Revision management: First submit → revision 1; resubmit → previous + 1.
        current_rev = submittal.current_revision or 0
        if submittal.status == "revise_and_resubmit":
            fields["current_revision"] = current_rev + 1
        elif current_rev == 0:
            fields["current_revision"] = 1

        # Ball-in-court moves to reviewer
        if submittal.reviewer_id:
            fields["ball_in_court"] = str(submittal.reviewer_id)

        # Snapshot attributes BEFORE update_fields (expire detaches lazy
        # columns). Re-fetch after so returned object has fresh values.
        project_id_s = str(submittal.project_id)
        title_s = submittal.title
        reviewer_id_s = str(submittal.reviewer_id) if submittal.reviewer_id else None
        created_by_s = str(submittal.created_by) if submittal.created_by else None
        submittal_number_s = getattr(submittal, "submittal_number", None)

        prior_status = submittal.status
        await self.repo.update_fields(submittal_id, **fields)
        fresh = await self.repo.get_by_id(submittal_id)

        # Epic H — universal audit trail. The try/except: pass wrapper
        # has been removed: the helper now raises only for real DB
        # failures, and silently swallowing those would lose the
        # compliance trail right when we need it most. If the audit
        # write actually fails the business write rolls back too — that
        # is the documented atomicity contract.
        from app.core.audit_log import log_activity as _log_activity

        await _log_activity(
            self.session,
            actor_id=created_by_s,
            entity_type="submittal",
            entity_id=str(submittal_id),
            action="status_changed",
            from_status=prior_status,
            to_status="submitted",
            reason="Submittal submitted via submit_submittal()",
            metadata={
                "submittal_number": submittal_number_s,
                "revision": fields.get("current_revision", current_rev),
            },
            module="submittals",
            parent_entity_type="project",
            parent_entity_id=project_id_s,
            before_state={"status": prior_status, "revision": current_rev},
            after_state={
                "status": "submitted",
                "revision": fields.get("current_revision", current_rev),
            },
        )

        await _safe_publish(
            "submittal.submitted",
            {
                "project_id": project_id_s,
                "submittal_id": str(submittal_id),
                "submittal_number": submittal_number_s,
                "title": title_s,
                "current_revision": fields.get("current_revision", current_rev),
                "reviewer_id": reviewer_id_s,
                "submitted_by": created_by_s,
            },
        )

        new_rev = (
            fresh.current_revision
            if fresh
            else fields.get(
                "current_revision",
                current_rev,
            )
        )
        logger.info(
            "Submittal submitted: %s (rev %s)",
            submittal_id,
            new_rev,
        )
        _log_state_change(
            submittal_id=submittal_id,
            submittal_number=submittal_number_s,
            project_id=project_id_s,
            prior_status=prior_status,
            new_status="submitted",
            actor_id=created_by_s,
            revision=new_rev,
            extra={"source": "submit", "reviewer_id": reviewer_id_s},
        )
        return fresh or submittal

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
        project_id_s = str(submittal.project_id)
        title_s = submittal.title
        created_by_s = str(submittal.created_by) if submittal.created_by else None
        submittal_number_s = getattr(submittal, "submittal_number", None)

        prior_status = submittal.status
        await self.repo.update_fields(submittal_id, **fields)
        fresh = await self.repo.get_by_id(submittal_id)

        # Epic H — universal audit trail (drop the try/except: pass
        # wrapper; the helper raises only for real DB failures).
        from app.core.audit_log import log_activity as _log_activity

        await _log_activity(
            self.session,
            actor_id=reviewer_id,
            entity_type="submittal",
            entity_id=str(submittal_id),
            action="status_changed",
            from_status=prior_status,
            to_status=new_status,
            reason=f"Submittal reviewed: decision={new_status}",
            metadata={"reviewer_id": reviewer_id},
            module="submittals",
            parent_entity_type="project",
            parent_entity_id=project_id_s,
            before_state={"status": prior_status},
            after_state={
                "status": new_status,
                "ball_in_court": str(ball) if ball else None,
            },
        )

        await _safe_publish(
            "submittal.reviewed",
            {
                "project_id": project_id_s,
                "submittal_id": str(submittal_id),
                "title": title_s,
                "decision": new_status,
                "reviewer_id": reviewer_id,
                "ball_in_court": str(ball) if ball else None,
                "submitted_by": created_by_s,
            },
        )

        if new_status == "rejected":
            await _safe_publish(
                "submittal.rejected",
                {
                    "project_id": project_id_s,
                    "submittal_id": str(submittal_id),
                    "submittal_number": submittal_number_s,
                    "title": title_s,
                    "reviewer_id": reviewer_id,
                    "submitted_by": created_by_s,
                    "reason": fields.get("review_notes") or "",
                },
            )
        elif new_status == "revise_and_resubmit":
            await _safe_publish(
                "submittal.revise_resubmit",
                {
                    "project_id": project_id_s,
                    "submittal_id": str(submittal_id),
                    "submittal_number": submittal_number_s,
                    "title": title_s,
                    "reviewer_id": reviewer_id,
                    "submitted_by": created_by_s,
                    "reason": fields.get("review_notes") or "",
                },
            )

        logger.info("Submittal reviewed: %s -> %s by %s", submittal_id, new_status, reviewer_id)
        _log_state_change(
            submittal_id=submittal_id,
            submittal_number=submittal_number_s,
            project_id=project_id_s,
            prior_status=prior_status,
            new_status=new_status,
            actor_id=reviewer_id,
            extra={"source": "review", "decision": new_status},
        )
        return fresh or submittal

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

        # Idempotent: approving an already-approved submittal is a no-op,
        # not a 400 (ENH-095). Clients retrying an approval after a network
        # timeout should see success instead of a confusing error.
        if submittal.status == "approved":
            logger.info(
                "Submittal %s already approved — returning existing state (idempotent)",
                submittal_id,
            )
            return submittal

        allowed = ("submitted", "under_review")
        if submittal.status not in allowed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Cannot approve submittal with status '{submittal.status}'. Expected one of: {', '.join(allowed)}"
                ),
            )

        from datetime import UTC, datetime

        fields: dict[str, Any] = {
            "status": "approved",
            "approver_id": approver_id,
            "date_returned": datetime.now(UTC).strftime("%Y-%m-%d"),
            "ball_in_court": None,
        }
        project_id_s = str(submittal.project_id)
        title_s = submittal.title
        created_by_s = str(submittal.created_by) if submittal.created_by else None
        submittal_number_s = getattr(submittal, "submittal_number", None)

        prior_status = submittal.status

        # R8: compare-and-swap to prevent concurrent double-approval races.
        # Two simultaneous requests both read status != "approved", both pass
        # the pre-check above, and then both try to write "approved". The
        # WHERE clause on prior_status means the second writer updates 0 rows;
        # we detect that and return 409 so the caller knows to re-read state.
        from sqlalchemy import update as _sa_update

        from app.modules.submittals.models import Submittal as _Submittal

        result = await self.session.execute(
            _sa_update(_Submittal)
            .where(_Submittal.id == submittal_id)
            .where(_Submittal.status == prior_status)
            .values(**fields)
        )
        if result.rowcount == 0:  # type: ignore[union-attr]
            # Concurrent writer already transitioned this row — re-read and
            # return idempotently if it's now "approved", else 409.
            fresh_check = await self.repo.get_by_id(submittal_id)
            if fresh_check and fresh_check.status == "approved":
                logger.info(
                    "Submittal %s concurrently approved — returning existing state (idempotent)",
                    submittal_id,
                )
                return fresh_check
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Submittal status changed concurrently; please reload and retry."
                ),
            )

        fresh = await self.repo.get_by_id(submittal_id)

        # Epic H — universal audit trail (drop the try/except: pass wrapper).
        from app.core.audit_log import log_activity as _log_activity

        await _log_activity(
            self.session,
            actor_id=approver_id,
            entity_type="submittal",
            entity_id=str(submittal_id),
            action="status_changed",
            from_status=prior_status,
            to_status="approved",
            reason="Submittal approved via approve_submittal()",
            metadata={"approver_id": approver_id},
            module="submittals",
            parent_entity_type="project",
            parent_entity_id=project_id_s,
            before_state={"status": prior_status},
            after_state={"status": "approved", "ball_in_court": None},
        )

        await _safe_publish(
            "submittal.approved",
            {
                "project_id": project_id_s,
                "submittal_id": str(submittal_id),
                "title": title_s,
                "approver_id": approver_id,
                "submitted_by": created_by_s,
            },
        )

        logger.info("Submittal approved: %s by %s", submittal_id, approver_id)
        _log_state_change(
            submittal_id=submittal_id,
            submittal_number=submittal_number_s,
            project_id=project_id_s,
            prior_status=prior_status,
            new_status="approved",
            actor_id=approver_id,
            extra={"source": "approve"},
        )
        return fresh or submittal
