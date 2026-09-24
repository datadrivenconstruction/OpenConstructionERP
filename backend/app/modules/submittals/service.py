# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Submittals service - business logic for submittal management."""

import logging
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import get_locale
from app.core.json_merge import merge_metadata
from app.core.validation.engine import ValidationReport, validation_engine
from app.modules.submittals.models import Submittal
from app.modules.submittals.repository import SubmittalRepository
from app.modules.submittals.schemas import SubmittalCreate, SubmittalUpdate

logger = logging.getLogger(__name__)

#: Rule set holding this module's submittal checks. Registered in
#: ``app.core.validation.rules.register_builtin_rules`` and passed explicitly by
#: :meth:`SubmittalService._validate_submittal`. A rule registered with
#: ``rule_sets=None`` lands in the set named by its ``standard`` and never runs
#: unless a caller asks for that set by name, so the name lives in one place and
#: its reachability is pinned by a test rather than by convention.
SUBMITTAL_RULE_SET = "submittal"

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
# Decided submittals are the approval record and are never deleted.
_DELETE_KEPT_STATUSES: frozenset[str] = frozenset({"approved", "approved_as_noted", "closed"})


async def _safe_publish(name: str, data: dict, source_module: str = "oe_submittals") -> None:
    """Publish an event, swallowing errors so business logic continues."""
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
    :func:`audit_log.log_activity` is intentional - the audit row lands
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

        # Description has no dedicated column; persist it into metadata so the
        # create modal's Description textarea is no longer silently dropped.
        create_meta = dict(data.metadata or {})
        if data.description is not None:
            desc = data.description.strip()
            if desc:
                create_meta["description"] = desc

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
                metadata_=create_meta,
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
            # Publish submittal.created so the vector indexer embeds the new
            # row for semantic search / the floating-chat assistant (item 16).
            await _safe_publish(
                "submittal.created",
                {
                    "project_id": str(data.project_id),
                    "submittal_id": str(submittal.id),
                    "submittal_number": submittal_number,
                },
            )
            return submittal

        # All retries exhausted - translate to 409 so the caller can retry
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
        # Merge a partial metadata patch into the existing column instead of
        # replacing it wholesale (the description block below then operates on
        # the merged dict). Without this a metadata PATCH without description
        # dropped sibling keys like review_notes / attachments.
        if "metadata" in fields:
            incoming_meta = fields.pop("metadata")
            if isinstance(incoming_meta, dict):
                fields["metadata_"] = merge_metadata(getattr(submittal, "metadata_", None), incoming_meta)
            else:
                fields["metadata_"] = incoming_meta

        # Description lives in metadata (no dedicated column). Merge it into a
        # copy of the existing metadata so the edit modal persists it without
        # clobbering review_notes / attachments etc.
        if "description" in fields:
            desc = fields.pop("description")
            meta = dict(fields.get("metadata_") or getattr(submittal, "metadata_", {}) or {})
            cleaned = (desc or "").strip()
            if cleaned:
                meta["description"] = cleaned
            else:
                meta.pop("description", None)
            fields["metadata_"] = meta

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
            # gated handlers - a plain editor with ``submittals.update``
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
        # ``update_fields`` expires the row - any subsequent lazy attribute
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
        # Publish submittal.updated so the vector indexer re-embeds the
        # edited row (title / spec section may have changed) - item 16.
        await _safe_publish(
            "submittal.updated",
            {
                "project_id": str(getattr(fresh or submittal, "project_id", "") or ""),
                "submittal_id": str(submittal_id),
                "submittal_number": getattr(fresh or submittal, "submittal_number", None),
            },
        )
        return fresh or submittal

    async def delete_submittal(self, submittal_id: uuid.UUID) -> None:
        submittal = await self.get_submittal(submittal_id)
        # An approved or closed submittal is the approval record procurement
        # and installation rely on; approve_submittal and update_submittal
        # already treat those states as final.
        if submittal.status in _DELETE_KEPT_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot delete a submittal in status '{submittal.status}': it is the approval record and is kept."
                ),
            )
        project_id_s = str(submittal.project_id) if submittal.project_id is not None else ""
        await self.repo.delete(submittal_id)
        logger.info("Submittal deleted: %s", submittal_id)
        # Publish submittal.deleted so the vector indexer drops the
        # embedding for the removed row (item 16).
        await _safe_publish(
            "submittal.deleted",
            {
                "project_id": project_id_s,
                "submittal_id": str(submittal_id),
            },
        )

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

        # Epic H - universal audit trail. The try/except: pass wrapper
        # has been removed: the helper now raises only for real DB
        # failures, and silently swallowing those would lose the
        # compliance trail right when we need it most. If the audit
        # write actually fails the business write rolls back too - that
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
        # Validation findings ride the same structured line as the state
        # change rather than a second log entry, so the submittal-cycle
        # dashboard can index "submitted with open findings" without joining
        # two events. Reporting, not refusing: see
        # :meth:`_collect_submission_findings`.
        findings = await self._collect_submission_findings(fresh)
        _log_state_change(
            submittal_id=submittal_id,
            submittal_number=submittal_number_s,
            project_id=project_id_s,
            prior_status=prior_status,
            new_status="submitted",
            actor_id=created_by_s,
            revision=new_rev,
            extra={"source": "submit", "reviewer_id": reviewer_id_s, **findings},
        )
        return fresh or submittal

    # ── Validation ───────────────────────────────────────────────────────────

    @staticmethod
    def _validation_payload(submittal: Submittal) -> dict[str, Any]:
        """Flatten a submittal into the dict the ``submittal`` rules read.

        Rules never touch the ORM, so everything they need is copied out here.
        Dates stay exactly as stored; the rules parse them and treat anything
        unreadable as absent rather than coercing it.

        ``as_of`` is the clock the date-relative rules use. It is supplied as
        data so a test can pin it; no rule in this module calls ``today()``.
        """
        from datetime import UTC, datetime

        linked = submittal.linked_boq_item_ids
        return {
            "id": str(submittal.id),
            "project_id": str(submittal.project_id),
            "submittal_number": submittal.submittal_number,
            "title": submittal.title,
            "status": submittal.status,
            "spec_section": submittal.spec_section,
            "reviewer_id": str(submittal.reviewer_id) if submittal.reviewer_id else None,
            "approver_id": str(submittal.approver_id) if submittal.approver_id else None,
            "date_submitted": submittal.date_submitted,
            "date_required": submittal.date_required,
            "current_revision": submittal.current_revision,
            "linked_boq_item_ids": list(linked) if isinstance(linked, list) else [],
            "as_of": datetime.now(UTC).date().isoformat(),
        }

    async def _validate_submittal(
        self,
        submittal: Submittal,
        *,
        operation: str,
    ) -> ValidationReport:
        """Run the ``submittal`` rule set against one submittal."""
        return await validation_engine.validate(
            data=self._validation_payload(submittal),
            rule_sets=[SUBMITTAL_RULE_SET],
            target_type="submittal",
            target_id=str(submittal.id),
            project_id=str(submittal.project_id),
            metadata={"locale": get_locale(), "operation": operation},
        )

    async def _collect_submission_findings(self, submittal: Submittal | None) -> dict[str, Any]:
        """Validate a submittal as it is filed and return the ids of what failed.

        This reports, it does not refuse. Submission is already gated by the
        state machine, and adding a second gate that rejects would change the
        meaning of an endpoint other people's workflows depend on. The findings
        still have to reach somebody, so the caller folds them into the
        structured state-change line, and the same report is available on demand
        through :meth:`validate_submittal`.

        Returns empty on any failure. An advisory check that breaks a legitimate
        submission would be worse than the problem it reports.
        """
        if submittal is None:
            return {}
        try:
            report = await self._validate_submittal(submittal, operation="submit")
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("Submittal validation skipped for %s: %s", submittal.id, exc)
            return {}
        if not report.errors and not report.warnings:
            return {}
        return {
            "validation_errors": [r.rule_id for r in report.errors],
            "validation_warnings": [r.rule_id for r in report.warnings],
        }

    @staticmethod
    def _report_to_dict(report: ValidationReport) -> dict[str, Any]:
        """Flatten a ValidationReport into the API response shape."""
        summary = report.summary()
        return {
            "status": summary["status"],
            "score": summary["score"],
            "counts": summary["counts"],
            "results": [
                {
                    "rule_id": r.rule_id,
                    "rule_name": r.rule_name,
                    "severity": r.severity.value,
                    "category": r.category.value,
                    "passed": r.passed,
                    "message": r.message,
                    "element_ref": r.element_ref,
                    "suggestion": r.suggestion,
                }
                for r in report.results
            ],
        }

    async def validate_submittal(self, submittal_id: uuid.UUID) -> dict[str, Any]:
        """Run the ``submittal`` rule set and return the report (read-only).

        Lets the person filing a submittal see what is missing before the review
        clock starts, instead of after a reviewer has already been waiting.
        """
        submittal = await self.get_submittal(submittal_id)
        report = await self._validate_submittal(submittal, operation="read")
        return self._report_to_dict(report)

    async def review_submittal(
        self,
        submittal_id: uuid.UUID,
        new_status: str,
        reviewer_id: str,
        notes: str | None = None,
    ) -> Submittal:
        """Review a submittal (approve, reject, etc.).

        Ball-in-court updates depend on the decision:
        - ``approved`` / ``approved_as_noted``: stays with reviewer (done)
        - ``revise_and_resubmit`` / ``rejected``: back to submitter
        Reviewer ``notes`` (free text) are persisted into the submittal
        metadata under ``review_notes`` so the reason survives in the audit
        trail and is propagated to the ``submittal.rejected`` /
        ``submittal.revise_resubmit`` notification events.
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

        review_notes = (notes or "").strip()

        fields: dict[str, Any] = {
            "status": new_status,
            "reviewer_id": reviewer_id,
            "date_returned": datetime.now(UTC).strftime("%Y-%m-%d"),
            "ball_in_court": ball,
        }
        # Persist the reviewer's comments into metadata so they are durable
        # and visible in the audit trail / detail view. We merge into a copy
        # of the existing metadata to avoid clobbering attachments etc.
        if review_notes:
            meta = dict(getattr(submittal, "metadata_", {}) or {})
            meta["review_notes"] = review_notes
            fields["metadata_"] = meta
        project_id_s = str(submittal.project_id)
        title_s = submittal.title
        created_by_s = str(submittal.created_by) if submittal.created_by else None
        submittal_number_s = getattr(submittal, "submittal_number", None)

        prior_status = submittal.status
        await self.repo.update_fields(submittal_id, **fields)
        fresh = await self.repo.get_by_id(submittal_id)

        # Epic H - universal audit trail (drop the try/except: pass
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
            reason=(f"Submittal reviewed: decision={new_status}" + (f" - {review_notes}" if review_notes else "")),
            metadata={"reviewer_id": reviewer_id, "review_notes": review_notes or None},
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
                    "reason": review_notes,
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
                    "reason": review_notes,
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
        notes: str | None = None,
    ) -> Submittal:
        """Final approval of a submittal.

        Only submittals that are currently ``submitted`` or ``under_review``
        can receive final approval.  Ball-in-court is cleared on approval.
        Optional reviewer ``notes`` are persisted into metadata under
        ``review_notes`` (mirroring :meth:`review_submittal`) so an approval
        with comments does not silently drop them.
        Publishes ``submittal.approved`` event.
        """
        submittal = await self.get_submittal(submittal_id)

        # Idempotent: approving an already-approved submittal is a no-op,
        # not a 400 (ENH-095). Clients retrying an approval after a network
        # timeout should see success instead of a confusing error.
        if submittal.status == "approved":
            logger.info(
                "Submittal %s already approved - returning existing state (idempotent)",
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
        approve_notes = (notes or "").strip()
        if approve_notes:
            # Merge into a copy of the existing metadata so attachments etc.
            # are not clobbered, mirroring review_submittal.
            meta = dict(getattr(submittal, "metadata_", {}) or {})
            meta["review_notes"] = approve_notes
            fields["metadata_"] = meta
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
            # Concurrent writer already transitioned this row - re-read and
            # return idempotently if it's now "approved", else 409.
            fresh_check = await self.repo.get_by_id(submittal_id)
            if fresh_check and fresh_check.status == "approved":
                logger.info(
                    "Submittal %s concurrently approved - returning existing state (idempotent)",
                    submittal_id,
                )
                return fresh_check
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=("Submittal status changed concurrently; please reload and retry."),
            )

        fresh = await self.repo.get_by_id(submittal_id)

        # Epic H - universal audit trail (drop the try/except: pass wrapper).
        from app.core.audit_log import log_activity as _log_activity

        await _log_activity(
            self.session,
            actor_id=approver_id,
            entity_type="submittal",
            entity_id=str(submittal_id),
            action="status_changed",
            from_status=prior_status,
            to_status="approved",
            reason=("Submittal approved via approve_submittal()" + (f" - {approve_notes}" if approve_notes else "")),
            metadata={"approver_id": approver_id, "review_notes": approve_notes or None},
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

    async def start_approval(
        self,
        submittal_id: uuid.UUID,
        route_id: uuid.UUID,
        *,
        started_by: str | None = None,
    ) -> Any:
        """Start a routed approval workflow against this submittal (feature 06).

        Delegates to the generic ``approval_routes`` engine. The engine
        validates that the route is active, that its ``target_kind`` is
        ``submittal``, that it has steps, and that no workflow is already
        pending on this target (409). On success the submittal is moved into
        the review flow through the *existing* FSM: a ``draft`` submittal is
        submitted first (``draft -> submitted``) so the state machine stays
        honest; a submittal already in ``submitted`` / ``under_review`` is
        left where it is while the workflow runs. The new instance id is
        recorded in ``metadata_["approval_instance_id"]`` so the detail
        screen can deep-link without a second query.

        Returns the created approval ``Instance`` (the engine row) so the
        router can serialise it through the engine's ``InstanceResponse``.
        The FSM transition and the instance insert share this request
        session, so they commit together.
        """
        from app.modules.approval_routes.schemas import InstanceCreate
        from app.modules.approval_routes.service import ApprovalRouteService

        submittal = await self.get_submittal(submittal_id)

        # Reviewable states only. ``approved`` / ``closed`` / ``rejected``
        # are not sensible places to begin a fresh routed sign-off.
        if submittal.status not in ("draft", "submitted", "under_review", "revise_and_resubmit"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Cannot start an approval workflow on a submittal with status "
                    f"'{submittal.status}'. Expected draft, submitted, under_review, or "
                    f"revise_and_resubmit."
                ),
            )

        engine = ApprovalRouteService(self.session)
        instance = await engine.start_instance(
            InstanceCreate(
                route_id=route_id,
                target_kind="submittal",
                target_id=submittal_id,
            ),
            started_by=uuid.UUID(started_by) if started_by else None,
        )

        # Move the submittal into the review flow through the existing FSM.
        if submittal.status in ("draft", "revise_and_resubmit"):
            await self.submit_submittal(submittal_id)

        # Record the instance id for deep-linking. Re-fetch to merge against
        # the latest metadata (submit_submittal above may have touched it).
        fresh = await self.get_submittal(submittal_id)
        meta = dict(getattr(fresh, "metadata_", {}) or {})
        meta["approval_instance_id"] = str(instance.id)
        await self.repo.update_fields(submittal_id, metadata_=meta)

        return instance

    async def get_latest_approval(self, submittal_id: uuid.UUID) -> Any:
        """Return the most recent approval instance for this submittal, or None.

        Reuses the engine's instance listing (already ordered newest-first)
        filtered by ``target_kind='submittal'`` and this submittal id.
        """
        from app.modules.approval_routes.service import ApprovalRouteService

        # 404 the submittal first so a caller without project access never
        # learns whether an instance exists.
        await self.get_submittal(submittal_id)
        engine = ApprovalRouteService(self.session)
        instances = await engine.list_instances(
            target_kind="submittal",
            target_id=submittal_id,
            limit=1,
        )
        return instances[0] if instances else None

    async def apply_approval_decision(
        self,
        submittal_id: uuid.UUID,
        *,
        decision: str,
        decided_by: str | None,
        comment: str | None = None,
    ) -> Submittal | None:
        """Drive the submittal FSM from a terminal routed approval decision.

        Called by the approval subscriber when the engine fires
        ``approval_routes.instance.completed`` (``decision='approved'``) or
        ``approval_routes.instance.rejected`` (``decision='rejected'``) for a
        ``submittal`` target. Only ever drives transitions the existing FSM
        already permits, so a stray or duplicate event can never corrupt
        state:

        * ``approved`` and the submittal is ``submitted`` / ``under_review`` →
          the idempotent :meth:`approve_submittal` (a duplicate event is a
          no-op, not a double-approval).
        * ``rejected`` and the submittal is ``submitted`` / ``under_review`` →
          :meth:`review_submittal` with ``rejected``, which returns
          ball-in-court to the submitter and persists the step comment.

        Any other current status (already approved, closed, draft, …) is a
        deliberate no-op: the routed decision arrived for a submittal the FSM
        has already moved past, so there is nothing to do.
        """
        submittal = await self.get_submittal(submittal_id)
        if submittal.status not in ("submitted", "under_review"):
            logger.info(
                "Submittal %s not in a reviewable state (%s); approval decision %r is a no-op",
                submittal_id,
                submittal.status,
                decision,
            )
            return None

        actor = decided_by or str(submittal.approver_id or submittal.reviewer_id or "")
        if decision == "approved":
            return await self.approve_submittal(submittal_id, approver_id=actor, notes=comment)
        if decision == "rejected":
            return await self.review_submittal(
                submittal_id,
                "rejected",
                reviewer_id=actor,
                notes=comment,
            )
        return None
