# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""RFQ Bidding service - business logic for RFQ and bid management.

Stateless service layer. It holds three things beyond plain CRUD:

* the lifecycle gates, which decide when a quote may still arrive and who may
  award one;
* the standing of each quote, which decides whether it may be ranked at all -
  a quote that arrived late is recorded and kept out of the ranking until the
  buyer admits it on the record, rather than refused and lost;
* the award itself, which is only allowed to take a quote the comparison could
  actually put on the RFQ's basis, and which writes down the ranked table it
  was taken from.

The arithmetic of putting quotes on one basis lives in
:mod:`app.modules.rfq_bidding.comparison` and is pure; this layer supplies it
with data and stores what it returns.
"""

import logging
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import get_locale
from app.core.json_merge import merge_metadata
from app.core.validation.engine import ValidationReport, validation_engine
from app.modules.rfq_bidding.comparison import ComparisonResult, compare
from app.modules.rfq_bidding.constants import (
    BID_STATUS_DISQUALIFIED,
    BID_STATUS_LATE,
    BID_STATUS_RECEIVED,
    BID_STATUS_WITHDRAWN,
    quote_gate_rule,
)
from app.modules.rfq_bidding.models import (
    RFQ,
    RFQAward,
    RFQBid,
    RFQBidAdjustment,
    RFQBidLine,
    RFQLine,
)
from app.modules.rfq_bidding.repository import (
    RFQAwardRepository,
    RFQBidRepository,
    RFQLineRepository,
    RFQRepository,
)
from app.modules.rfq_bidding.schemas import (
    BidAdjustmentCreate,
    BidCreate,
    BidEvaluation,
    BidLineCreate,
    RFQCreate,
    RFQLineCreate,
    RFQLineUpdate,
    RFQUpdate,
)

logger = logging.getLogger(__name__)

# RFQ statuses where a vendor may still submit a bid. Submissions against
# draft / awarded / completed / cancelled RFQs are rejected - those would
# otherwise allow a vendor to slip a bid in after the award has been made
# or before the RFQ has been published.
_BID_SUBMISSION_OPEN_STATUSES: frozenset[str] = frozenset({"published", "issued", "bids_received"})

# Roles permitted to award an RFQ (mirrors FSM registry
# ``bids_received → awarded`` ``required_roles=("admin", "manager")``).
# The router-level ``rfq.update`` permission lets EDITOR call award_bid,
# which would side-step the FSM contract - service must re-check.
_AWARD_ALLOWED_ROLES: frozenset[str] = frozenset({"admin", "manager", "owner"})

# Rule sets holding this module's checks. Both are registered in
# ``app.core.validation.rules.register_builtin_rules`` and each is passed
# explicitly by exactly one caller below. Two sets rather than one plus an
# operation flag: the submission deadline must be in the future when the RFQ is
# published and has necessarily passed by the time it is awarded, so a single
# set could only hold both by way of a rule that silently no-ops, which is
# indistinguishable from a rule nobody calls.
RFQ_ISSUE_RULE_SET = "rfq_issue"
RFQ_AWARD_RULE_SET = "rfq_award"

#: Non-answers a gate-override "reason" may not be. Mirrors the workflow
#: module's GATE_REASON_JUNK (kept local: this module must not import
#: register_workflow - the dependency runs the other way).
_OVERRIDE_REASON_JUNK = frozenset(
    {
        "n/a",
        "na",
        "nil",
        "none",
        "no",
        "-",
        "--",
        ".",
        "x",
        "xx",
        "xxx",
        "tbc",
        "tba",
        "later",
        "asap",
        "unknown",
        "idk",
        "no reason",
        "because",
        "override",
        "force",
        "test",
        "ok",
        "yes",
    }
)


def _override_reason_bad(reason: str | None) -> str:
    """ "" when the justification will still mean something later, else why not.

    This cannot judge whether a reason is TRUE - only a person can. It
    refuses the ways of writing nothing. The award is its own enforcement
    point: a UI that skipped the compare screen must meet the same bar here.
    """
    text = " ".join(str(reason or "").split())
    if not text:
        return "It needs a reason."
    if text.strip(" .-").lower() in _OVERRIDE_REASON_JUNK:
        return f'"{text}" is not a reason - say what is actually happening.'
    if len(text) < 12:
        return f'"{text}" is too short to mean anything in six weeks - one plain sentence is enough.'
    return ""


# RFQ statuses in which the scope may still be edited. Once the package is out
# with vendors, changing what they were asked to price behind their backs makes
# the returned quotes answers to different questions.
_SCOPE_EDITABLE_STATUSES: frozenset[str] = frozenset({"draft"})

# RFQ statuses in which no quote may be changed at all: the decision has been
# taken, and an adjustment added afterwards would move a comparison that has
# already been acted on.
_RFQ_CLOSED_STATUSES: frozenset[str] = frozenset({"awarded", "cancelled", "completed", "po_issued"})


class RFQService:
    """Business logic for RFQ and bidding operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.rfqs = RFQRepository(session)
        self.bids_repo = RFQBidRepository(session)
        self.lines_repo = RFQLineRepository(session)
        self.awards = RFQAwardRepository(session)

    # ── RFQs ────────────────────────────────────────────────────────────────

    async def create_rfq(
        self,
        data: RFQCreate,
        user_id: str | None = None,
    ) -> RFQ:
        """Create a new RFQ, with its scope lines if any were supplied.

        Args:
            data: The RFQ to create. ``lines`` is optional: an RFQ priced as a
                single lump sum is a legitimate package, and one with a line
                breakdown is the one whose quotes can be compared line by line.
            user_id: The authenticated user, recorded as the author.

        Returns:
            The created RFQ, with ``lines`` populated.
        """
        rfq_number = data.rfq_number
        if not rfq_number:
            rfq_number = await self.rfqs.next_rfq_number(data.project_id)

        rfq = RFQ(
            project_id=data.project_id,
            rfq_number=rfq_number,
            title=data.title,
            description=data.description,
            scope_of_work=data.scope_of_work,
            submission_deadline=data.submission_deadline,
            currency_code=data.currency_code,
            status=data.status,
            issued_to_contacts=data.issued_to_contacts,
            evaluation_method=data.evaluation_method,
            technical_weight=data.technical_weight,
            require_full_scope=data.require_full_scope,
            created_by=uuid.UUID(user_id) if user_id else None,
            metadata_=data.metadata,
        )
        for position, line in enumerate(data.lines, start=1):
            rfq.lines.append(self._build_line(line, line_no=line.line_no or position))
        self._reject_duplicate_line_numbers(rfq.lines)
        rfq = await self.rfqs.create(rfq)
        logger.info("RFQ created: %s (%s)", rfq.rfq_number, rfq.title[:50])
        # Serialisation walks ``bids`` (and ``lines``), and on a freshly
        # flushed instance the never-touched ``bids`` collection is unloaded -
        # pydantic's sync attribute access then trips MissingGreenlet and the
        # router 500s AFTER the row exists. Re-read through the repository,
        # whose populate_existing query runs both selectin loaders.
        return await self.get_rfq(rfq.id)

    # ── Scope lines ─────────────────────────────────────────────────────────

    @staticmethod
    def _build_line(data: RFQLineCreate, *, line_no: int) -> RFQLine:
        """Build a scope line row from its payload."""
        return RFQLine(
            line_no=line_no,
            code=data.code,
            description=data.description,
            unit=data.unit,
            quantity=data.quantity,
            is_optional=data.is_optional,
            cost_line_id=data.cost_line_id,
            notes=data.notes,
            metadata_=data.metadata,
        )

    @staticmethod
    def _reject_duplicate_line_numbers(lines: list[RFQLine]) -> None:
        """Refuse a scope whose line numbers repeat.

        The database enforces this too, but a unique-violation surfaces as a
        500 after a partial write. A quote references a line by its number, so
        two lines sharing one is not a cosmetic problem.
        """
        numbers = [line.line_no for line in lines]
        duplicates = sorted({number for number in numbers if numbers.count(number) > 1})
        if duplicates:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Scope line numbers must be unique; repeated: {duplicates}",
            )

    async def _require_editable_scope(self, rfq_id: uuid.UUID) -> RFQ:
        """Load an RFQ and refuse to change its scope once it has gone out."""
        rfq = await self.get_rfq(rfq_id)
        if rfq.status not in _SCOPE_EDITABLE_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot change the scope of an RFQ in status '{rfq.status}'; "
                    "vendors have already been asked to price it."
                ),
            )
        return rfq

    async def list_lines(self, rfq_id: uuid.UUID) -> list[RFQLine]:
        """The scope lines of one RFQ, in line order."""
        await self.get_rfq(rfq_id)  # 404 check
        return await self.lines_repo.list_for_rfq(rfq_id)

    async def add_line(self, rfq_id: uuid.UUID, data: RFQLineCreate) -> RFQLine:
        """Add one line to an RFQ that has not gone out yet."""
        await self._require_editable_scope(rfq_id)
        line_no = data.line_no or await self.lines_repo.next_line_no(rfq_id)
        line = self._build_line(data, line_no=line_no)
        line.rfq_id = rfq_id
        existing = await self.lines_repo.list_for_rfq(rfq_id)
        if any(other.line_no == line_no for other in existing):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Scope line {line_no} already exists on this RFQ",
            )
        created = await self.lines_repo.create(line)
        logger.info("RFQ %s scope line added: %s", rfq_id, line_no)
        return created

    async def update_line(
        self,
        rfq_id: uuid.UUID,
        line_id: uuid.UUID,
        data: RFQLineUpdate,
    ) -> RFQLine:
        """Update one scope line of an RFQ that has not gone out yet."""
        await self._require_editable_scope(rfq_id)
        line = await self._get_line(rfq_id, line_id)

        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            incoming = fields.pop("metadata")
            fields["metadata_"] = (
                merge_metadata(getattr(line, "metadata_", None), incoming) if isinstance(incoming, dict) else incoming
            )
        if fields:
            await self.lines_repo.update(line_id, **fields)
        updated = await self.lines_repo.get(line_id)
        if updated is None:  # pragma: no cover - the row was just updated
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scope line not found")
        return updated

    async def delete_line(self, rfq_id: uuid.UUID, line_id: uuid.UUID) -> None:
        """Remove one scope line, and any quoted prices that referenced it."""
        await self._require_editable_scope(rfq_id)
        line = await self._get_line(rfq_id, line_id)
        await self.lines_repo.delete(line)
        logger.info("RFQ %s scope line removed: %s", rfq_id, line_id)

    async def _get_line(self, rfq_id: uuid.UUID, line_id: uuid.UUID) -> RFQLine:
        """Load one scope line and check it belongs to the RFQ in the path."""
        line = await self.lines_repo.get(line_id)
        if line is None or line.rfq_id != rfq_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scope line not found")
        return line

    async def get_rfq(self, rfq_id: uuid.UUID) -> RFQ:
        """Get RFQ by ID. Raises 404 if not found."""
        rfq = await self.rfqs.get(rfq_id)
        if rfq is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="RFQ not found",
            )
        return rfq

    async def list_rfqs(
        self,
        *,
        project_id: uuid.UUID | None = None,
        rfq_status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[RFQ], int]:
        """List RFQs with filters."""
        return await self.rfqs.list(
            project_id=project_id,
            status=rfq_status,
            limit=limit,
            offset=offset,
        )

    async def update_rfq(
        self,
        rfq_id: uuid.UUID,
        data: RFQUpdate,
    ) -> RFQ:
        """Update RFQ fields."""
        rfq = await self.get_rfq(rfq_id)  # 404 check

        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            _incoming = fields.pop("metadata")
            fields["metadata_"] = (
                merge_metadata(getattr(rfq, "metadata_", None), _incoming) if isinstance(_incoming, dict) else _incoming
            )
            self._reject_lowering_the_estimate(rfq, fields["metadata_"])

        if fields:
            await self.rfqs.update(rfq_id, **fields)

        updated = await self.rfqs.get(rfq_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="RFQ not found",
            )
        logger.info("RFQ updated: %s", rfq_id)
        return updated

    @staticmethod
    def _reject_lowering_the_estimate(rfq: RFQ, incoming: Any) -> None:
        """The package value may be corrected upward, never downward.

        The quote gate tiers off ``max(estimate, every standing price)``,
        so on the face of it lowering the estimate looks harmless - the
        quotes hold the line. They do not, in the one case that matters:
        a $50,000 package with a single $2,900 quote against it. Drop the
        estimate to $100 and the value becomes $2,900, which is under the
        $3,000 tier, and the package awards on one price. That is exactly
        the single-source award the gate exists to prevent, reached
        through an endpoint that looks like an admin correction.

        Raising it is always allowed: it can only ask for more quotes.
        Editing a draft is free - nothing has been asked of anybody yet.
        """
        if not isinstance(incoming, dict) or rfq.status == "draft":
            return
        from app.core.money_text import parse_amount

        was = parse_amount((rfq.metadata_ or {}).get("estimated_value"))
        now = parse_amount(incoming.get("estimated_value"))
        if was is None or now is None or now >= was:
            return
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"The package value cannot be reduced once the RFQ is out with suppliers "
                f"({was:.2f} to {now:.2f}) - it decides how many quotes the award needs. "
                f"Cancel and re-raise the package if the scope has genuinely shrunk."
            ),
        )

    async def delete_rfq(self, rfq_id: uuid.UUID) -> None:
        """Delete an RFQ and all its bids."""
        await self.get_rfq(rfq_id)  # 404 check
        await self.rfqs.delete(rfq_id)
        logger.info("RFQ deleted: %s", rfq_id)

    async def issue_rfq(
        self,
        rfq_id: uuid.UUID,
        *,
        actor_id: str | None = None,
        reason: str | None = None,
    ) -> RFQ:
        """Transition RFQ from draft to published (legacy alias: ``issued``).

        v3033 unified the lifecycle nomenclature - the new canonical status
        is ``published``, and the v3033 data migration remaps existing
        ``issued`` rows. We still write ``published`` here to be consistent
        with :mod:`app.core.fsm.registry`.
        """
        rfq = await self.get_rfq(rfq_id)
        prior = rfq.status
        if prior != "draft":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot issue RFQ in status '{prior}'",
            )
        # Validate the package as it is about to go out, before the write:
        # ``rfqs.update()`` expires the instance and ``bids`` would then need a
        # fresh load. This reports, it does not refuse - see
        # :meth:`_report_rfq_validation`.
        await self._report_rfq_validation(
            rfq,
            rule_set=RFQ_ISSUE_RULE_SET,
            operation="issue",
        )

        # Snapshot fields BEFORE rfqs.update() - that call invokes
        # expire_all() and any subsequent ORM-managed attribute access
        # would otherwise trigger a sync DB fetch (MissingGreenlet).
        rfq_number_local = rfq.rfq_number
        await self.rfqs.update(rfq_id, status="published")
        try:
            from app.core.audit_log import log_activity

            await log_activity(
                self.session,
                actor_id=actor_id,
                entity_type="rfq",
                entity_id=str(rfq_id),
                action="status_changed",
                from_status=prior,
                to_status="published",
                reason=reason or "RFQ published via issue_rfq()",
                metadata={"rfq_number": rfq_number_local},
            )
        except Exception:
            logger.debug("FSM audit log skipped for RFQ %s issue", rfq_id)
        updated = await self.rfqs.get(rfq_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="RFQ not found",
            )
        logger.info("RFQ published: %s", rfq_number_local)
        return updated

    # ── Validation ──────────────────────────────────────────────────────────

    @staticmethod
    def _decimal_str(value: Any) -> str | None:
        """Render a stored Decimal for a payload without ever going via float."""
        if value is None:
            return None
        return format(value, "f") if isinstance(value, Decimal) else str(value)

    @classmethod
    def _line_payload(cls, line: RFQLine) -> dict[str, Any]:
        """One scope line, flattened for the rules and the comparison."""
        return {
            "id": str(line.id),
            "line_no": line.line_no,
            "code": line.code,
            "description": line.description,
            "unit": line.unit,
            "quantity": cls._decimal_str(line.quantity),
            "is_optional": line.is_optional,
        }

    @classmethod
    def _bid_payload(cls, bid: RFQBid) -> dict[str, Any]:
        """One quote, flattened with everything its comparability rests on."""
        return {
            "id": str(bid.id),
            "bidder_contact_id": bid.bidder_contact_id,
            "bid_amount": bid.bid_amount,
            "currency_code": bid.currency_code,
            "submitted_at": bid.submitted_at,
            "validity_days": bid.validity_days,
            "is_awarded": bid.is_awarded,
            "status": bid.status,
            "is_late": bid.is_late,
            "admitted_at": bid.admitted_at,
            "technical_score": bid.technical_score,
            "commercial_score": bid.commercial_score,
            "exchange_rate": cls._decimal_str(bid.exchange_rate),
            "exchange_rate_date": bid.exchange_rate_date,
            "lines": [
                {
                    "id": str(line.id),
                    "rfq_line_id": None if line.rfq_line_id is None else str(line.rfq_line_id),
                    "description": line.description,
                    "unit": line.unit,
                    "quantity": cls._decimal_str(line.quantity),
                    "unit_rate": cls._decimal_str(line.unit_rate),
                    "amount": cls._decimal_str(line.amount),
                    "unit_conversion_factor": cls._decimal_str(line.unit_conversion_factor),
                    "is_excluded": line.is_excluded,
                }
                for line in bid.lines
            ],
            "adjustments": [
                {
                    "id": str(adjustment.id),
                    "kind": adjustment.kind,
                    "description": adjustment.description,
                    "amount": cls._decimal_str(adjustment.amount),
                    "currency_code": adjustment.currency_code,
                    "included_in_bid": adjustment.included_in_bid,
                    "source": adjustment.source,
                }
                for adjustment in bid.adjustments
            ],
        }

    @classmethod
    def _validation_payload(cls, rfq: RFQ, *, as_of: date | None = None) -> dict[str, Any]:
        """Flatten an RFQ, its scope and its quotes into the dict rules read.

        Rules never touch the ORM, so everything they need is copied out here.
        ``bid_amount`` and ``submission_deadline`` are free-form string columns
        and stay exactly as stored: the rules parse them and report an
        unreadable value, which is the whole point of two of them.

        ``as_of`` is the clock the date-relative rules use. It is supplied as
        data so a test can pin it; no rule in this module calls ``today()``.
        """
        contacts = rfq.issued_to_contacts
        return {
            "id": str(rfq.id),
            "project_id": str(rfq.project_id),
            "rfq_number": rfq.rfq_number,
            "title": rfq.title,
            "status": rfq.status,
            "description": rfq.description,
            "scope_of_work": rfq.scope_of_work,
            "submission_deadline": rfq.submission_deadline,
            "currency_code": rfq.currency_code or "",
            "issued_to_contacts": list(contacts) if isinstance(contacts, list) else [],
            "evaluation_method": rfq.evaluation_method,
            "technical_weight": cls._decimal_str(rfq.technical_weight),
            "require_full_scope": rfq.require_full_scope,
            "as_of": (as_of or datetime.now(UTC).date()).isoformat(),
            "lines": [cls._line_payload(line) for line in rfq.lines],
            "bids": [cls._bid_payload(bid) for bid in rfq.bids],
        }

    @classmethod
    def compare_payload(cls, rfq: RFQ, *, as_of: date | None = None) -> ComparisonResult:
        """Put every quote on the RFQ's basis and rank the ones that fit.

        Args:
            rfq: The RFQ with its ``lines`` and ``bids`` loaded.
            as_of: The date the comparison is made on. Defaults to today.

        Returns:
            The ranked quotes and the ones that could not be ranked, each with
            the reason it could not.
        """
        return compare(cls._validation_payload(rfq, as_of=as_of))

    async def compare_bids(self, rfq_id: uuid.UUID, *, as_of: date | None = None) -> tuple[RFQ, ComparisonResult]:
        """Load an RFQ and compare the quotes returned against it."""
        rfq = await self.get_rfq(rfq_id)
        return rfq, self.compare_payload(rfq, as_of=as_of)

    async def _validate_rfq(
        self,
        rfq: RFQ,
        *,
        rule_set: str,
        operation: str,
        candidate_bid_id: uuid.UUID | None = None,
        as_of: date | None = None,
    ) -> ValidationReport:
        """Run one of the two RFQ rule sets against an RFQ.

        The payload carries the comparison as well as the raw rows, so a rule
        that asks whether a quote could be ranked reads the same verdict the
        ranking itself used. Two answers to that question would eventually
        disagree, and the report is the half nobody would re-check.
        """
        payload = self._validation_payload(rfq, as_of=as_of)
        payload["comparison"] = compare(payload).as_dict()
        payload["candidate_bid_id"] = None if candidate_bid_id is None else str(candidate_bid_id)
        return await validation_engine.validate(
            data=payload,
            rule_sets=[rule_set],
            target_type="rfq",
            target_id=str(rfq.id),
            project_id=str(rfq.project_id),
            metadata={"locale": get_locale(), "operation": operation},
        )

    async def _report_rfq_validation(
        self,
        rfq: RFQ,
        *,
        rule_set: str,
        operation: str,
        candidate_bid_id: uuid.UUID | None = None,
    ) -> None:
        """Validate an RFQ at a lifecycle moment and record what is wrong.

        This reports, it does not refuse. Publishing and awarding are already
        gated (status, role, single-award), and a third gate that rejected would
        change the meaning of endpoints other people's workflows depend on. The
        findings still have to reach somebody, so they land on the log with
        their rule ids, and the same report is available on demand through
        :meth:`validate_rfq`.

        Failures inside validation are swallowed. An advisory check that broke a
        legitimate award would be worse than the problem it reports.
        """
        try:
            report = await self._validate_rfq(
                rfq,
                rule_set=rule_set,
                operation=operation,
                candidate_bid_id=candidate_bid_id,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("RFQ validation skipped for %s: %s", rfq.id, exc)
            return
        if not report.errors and not report.warnings:
            return
        logger.warning(
            "rfq.%s_with_findings %s",
            operation,
            {
                "rfq_id": str(rfq.id),
                "project_id": str(rfq.project_id),
                "rule_set": rule_set,
                "errors": [r.rule_id for r in report.errors],
                "warnings": [r.rule_id for r in report.warnings],
            },
        )

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

    async def validate_rfq(self, rfq_id: uuid.UUID, *, stage: str = "issue") -> dict[str, Any]:
        """Run one RFQ rule set and return the report (read-only).

        ``stage`` selects which question is being asked: ``issue`` for whether
        the package is ready to go out to vendors, ``award`` for what the
        comparison between the returned bids rests on. Anything else is a
        caller error rather than a silent default, because quietly answering
        the wrong question is how a rule set ends up trusted for a check it
        never ran.
        """
        stages = {"issue": RFQ_ISSUE_RULE_SET, "award": RFQ_AWARD_RULE_SET}
        rule_set = stages.get(stage)
        if rule_set is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown validation stage '{stage}'; expected one of {sorted(stages)}",
            )
        rfq = await self.get_rfq(rfq_id)
        report = await self._validate_rfq(rfq, rule_set=rule_set, operation="read")
        return self._report_to_dict(report)

    # ── Bids ────────────────────────────────────────────────────────────────

    @staticmethod
    def _deadline_has_passed(rfq: RFQ) -> bool:
        """Whether the RFQ's own deadline is already behind us.

        A deadline the system cannot read is not treated as absent. Every bid
        submission would otherwise be refused later by the parse, which lands on
        the vendor for a data problem on the buyer's side, so an unreadable
        deadline is reported as such at the moment it blocks something.
        """
        if not rfq.submission_deadline:
            return False
        try:
            deadline = datetime.fromisoformat(rfq.submission_deadline.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            logger.warning(
                "RFQ %s has malformed submission_deadline %r - bid rejected",
                rfq.id,
                rfq.submission_deadline,
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="RFQ submission_deadline is malformed; ask buyer to fix",
            ) from None
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        return datetime.now(UTC) > deadline

    @staticmethod
    def _build_bid_line(data: BidLineCreate) -> RFQBidLine:
        """Build one quoted line, deriving the amount when it was not sent."""
        amount = data.amount if data.amount is not None else data.quantity * data.unit_rate
        return RFQBidLine(
            rfq_line_id=data.rfq_line_id,
            description=data.description,
            unit=data.unit,
            quantity=data.quantity,
            unit_rate=data.unit_rate,
            amount=amount,
            unit_conversion_factor=data.unit_conversion_factor,
            is_excluded=data.is_excluded,
            notes=data.notes,
        )

    @staticmethod
    def _build_adjustment(data: BidAdjustmentCreate, *, default_currency: str) -> RFQBidAdjustment:
        """Build one adjustment, defaulting its currency to the quote's own."""
        return RFQBidAdjustment(
            kind=data.kind,
            description=data.description,
            amount=data.amount,
            currency_code=data.currency_code or default_currency,
            included_in_bid=data.included_in_bid,
            source=data.source,
        )

    def _reject_unknown_scope_lines(self, rfq: RFQ, data: BidCreate) -> None:
        """Refuse a quote that prices a line of somebody else's RFQ.

        A quoted line whose ``rfq_line_id`` belongs to another package would be
        counted as covering nothing here and would quietly lower this quote's
        coverage instead of failing loudly.
        """
        known = {line.id for line in rfq.lines}
        unknown = sorted(
            {
                str(line.rfq_line_id)
                for line in data.lines
                if line.rfq_line_id is not None and line.rfq_line_id not in known
            }
        )
        if unknown:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"These quoted lines do not belong to this RFQ: {unknown}",
            )

    async def submit_bid(
        self,
        data: BidCreate,
        user_id: str | None = None,
    ) -> RFQBid:
        """Record a quote against an RFQ, with its priced lines and terms.

        A quote that arrives after the deadline is not thrown away. Sent
        without ``late_reason`` it is refused, exactly as before; sent with one
        it is recorded with standing ``late``, which keeps it visible in the
        comparison table and out of the ranking until somebody admits it
        through :meth:`admit_late_bid`. Losing the quote would not make the
        decision cleaner, it would only make it unauditable.

        Args:
            data: The quote, its lines and its stated inclusions.
            user_id: The authenticated user recording the quote.

        Returns:
            The stored quote.

        Raises:
            HTTPException: 404 when the RFQ does not exist, 409 when the RFQ is
                not accepting quotes or the deadline has passed without a
                recorded reason, 422 when the RFQ's deadline is unreadable.
        """
        rfq = await self.get_rfq(data.rfq_id)  # 404 check

        # Lifecycle gate - bidding is only legal while the RFQ is open.
        if rfq.status not in _BID_SUBMISSION_OPEN_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot submit bid against RFQ in status '{rfq.status}'; RFQ must be published or accepting bids."
                ),
            )

        is_late = self._deadline_has_passed(rfq)
        if is_late and not data.late_reason:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "RFQ submission deadline has passed; record the quote with a "
                    "late_reason if the buyer wants it on the file."
                ),
            )

        self._reject_unknown_scope_lines(rfq, data)

        submitted_at = data.submitted_at or datetime.now(UTC).isoformat()

        bid = RFQBid(
            rfq_id=data.rfq_id,
            bidder_contact_id=data.bidder_contact_id,
            bid_amount=data.bid_amount,
            currency_code=data.currency_code,
            submitted_at=submitted_at,
            validity_days=data.validity_days,
            technical_score=data.technical_score,
            commercial_score=data.commercial_score,
            notes=data.notes,
            is_awarded=False,
            status=BID_STATUS_LATE if is_late else BID_STATUS_RECEIVED,
            is_late=is_late,
            late_reason=data.late_reason if is_late else None,
            exchange_rate=data.exchange_rate,
            exchange_rate_date=data.exchange_rate_date,
            exchange_rate_source=data.exchange_rate_source,
            metadata_=data.metadata,
        )
        for line in data.lines:
            bid.lines.append(self._build_bid_line(line))
        for adjustment in data.adjustments:
            bid.adjustments.append(self._build_adjustment(adjustment, default_currency=data.currency_code))
        bid = await self.bids_repo.create(bid)
        logger.info(
            "Bid recorded: %s %s for RFQ %s (%d lines, %d adjustments, late=%s)",
            data.bid_amount,
            data.currency_code,
            data.rfq_id,
            len(data.lines),
            len(data.adjustments),
            is_late,
        )
        # Same serialisation trap as create_rfq: a collection never touched
        # on the fresh instance (adjustments when none were sent, lines
        # likewise) is unloaded, and pydantic's sync access MissingGreenlets.
        # _reload_bid runs the repository's eager loaders.
        return await self._reload_bid(bid.id)

    async def get_bid(self, bid_id: uuid.UUID) -> RFQBid:
        """Get bid by ID. Raises 404 if not found."""
        bid = await self.bids_repo.get(bid_id)
        if bid is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Bid not found",
            )
        return bid

    async def list_bids(
        self,
        *,
        rfq_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[RFQBid], int]:
        """List bids with optional RFQ filter."""
        return await self.bids_repo.list(rfq_id=rfq_id, limit=limit, offset=offset)

    async def evaluate_bid(
        self,
        bid_id: uuid.UUID,
        data: BidEvaluation,
    ) -> RFQBid:
        """Score a bid (technical + commercial evaluation).

        Both scores are validated as numbers between 0 and 100 by
        :class:`~app.modules.rfq_bidding.schemas.BidEvaluation` before they get
        here, so this method does not re-check them. It used to, through
        ``float()``, which was both a second implementation of an already
        enforced rule and the one place in this module where money-adjacent
        arithmetic left Decimal.
        """
        await self.get_bid(bid_id)  # 404 check

        fields = data.model_dump(exclude_unset=True)
        if fields:
            await self.bids_repo.update(bid_id, **fields)

        updated = await self.bids_repo.get(bid_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Bid not found",
            )
        logger.info("Bid evaluated: %s", bid_id)
        return updated

    # ── Standing: which quotes the ranking is allowed to consider ───────────

    @staticmethod
    def _require_award_role(actor_role: str | None, action: str) -> None:
        """Check the actor may take a decision that changes the field of quotes.

        ``None`` is a bypass for internal callers (background reconciliation,
        demo seeders, tests that do not simulate a JWT); an HTTP request always
        carries a role through the router.
        """
        if actor_role is not None and actor_role.lower() not in _AWARD_ALLOWED_ROLES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"{action} requires admin or manager role; role '{actor_role}' is not permitted.",
            )

    async def _bid_for_open_rfq(self, bid_id: uuid.UUID, action: str) -> tuple[RFQBid, RFQ]:
        """Load a quote and its RFQ, refusing to touch a decided package.

        Once an RFQ is awarded its comparison has been acted on. Changing a
        quote's standing or its inclusions afterwards would rewrite the basis of
        a decision already taken, which is precisely what the award record
        exists to prevent.
        """
        bid = await self.get_bid(bid_id)
        rfq = await self.get_rfq(bid.rfq_id)
        if rfq.status in _RFQ_CLOSED_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot {action} on an RFQ in status '{rfq.status}'",
            )
        if bid.is_awarded:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot {action} on the awarded quote",
            )
        return bid, rfq

    async def _reload_bid(self, bid_id: uuid.UUID) -> RFQBid:
        """Re-read a quote after a write, refusing to guess if it vanished."""
        updated = await self.bids_repo.get(bid_id)
        if updated is None:  # pragma: no cover - the row was just updated
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bid not found")
        return updated

    async def withdraw_bid(
        self,
        bid_id: uuid.UUID,
        *,
        reason: str,
        actor_id: str | None = None,
    ) -> RFQBid:
        """Record that a supplier has withdrawn its quote.

        The quote stays in the register with the reason attached. Deleting it
        would leave the comparison showing a field of offers that never
        included it, and the count of quotes received is itself evidence about
        how competitive the package was.
        """
        bid, _rfq = await self._bid_for_open_rfq(bid_id, "withdraw a quote")
        await self.bids_repo.update(
            bid_id,
            status=BID_STATUS_WITHDRAWN,
            withdrawn_at=datetime.now(UTC).isoformat(),
            withdrawn_reason=reason,
        )
        await self._log_bid_decision(
            bid,
            action="withdrawn",
            actor_id=actor_id,
            reason=reason,
            to_status=BID_STATUS_WITHDRAWN,
        )
        logger.info("Bid withdrawn: %s", bid_id)
        return await self._reload_bid(bid_id)

    async def disqualify_bid(
        self,
        bid_id: uuid.UUID,
        *,
        reason: str,
        actor_id: str | None = None,
        actor_role: str | None = None,
    ) -> RFQBid:
        """Rule a quote out of the ranking, with the reason on the record.

        A buyer decision, so it carries the same role gate as an award: keeping
        a quote out of the comparison decides the outcome as surely as choosing
        one does.
        """
        self._require_award_role(actor_role, "Disqualifying a quote")
        bid, _rfq = await self._bid_for_open_rfq(bid_id, "disqualify a quote")
        await self.bids_repo.update(
            bid_id,
            status=BID_STATUS_DISQUALIFIED,
            disqualified_reason=reason,
        )
        await self._log_bid_decision(
            bid,
            action="disqualified",
            actor_id=actor_id,
            reason=reason,
            to_status=BID_STATUS_DISQUALIFIED,
        )
        logger.info("Bid disqualified: %s", bid_id)
        return await self._reload_bid(bid_id)

    async def admit_late_bid(
        self,
        bid_id: uuid.UUID,
        *,
        reason: str,
        actor_id: str | None = None,
        actor_role: str | None = None,
    ) -> RFQBid:
        """Let a quote that arrived late into the ranking, on the record.

        This is the only way a late quote becomes rankable, and it is
        deliberately an explicit act by somebody entitled to award: admitting a
        quote after the others are known is the single most contestable thing a
        buyer can do, so it is signed and dated rather than inferred.
        """
        self._require_award_role(actor_role, "Admitting a late quote")
        bid, _rfq = await self._bid_for_open_rfq(bid_id, "admit a late quote")
        if not bid.is_late:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This quote did not arrive late, so there is nothing to admit",
            )
        if bid.admitted_at:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This late quote has already been admitted",
            )
        await self.bids_repo.update(
            bid_id,
            admitted_by=uuid.UUID(actor_id) if actor_id else None,
            admitted_at=datetime.now(UTC).isoformat(),
            admission_reason=reason,
        )
        await self._log_bid_decision(
            bid,
            action="late_quote_admitted",
            actor_id=actor_id,
            reason=reason,
            to_status=BID_STATUS_LATE,
        )
        logger.info("Late bid admitted into the ranking: %s", bid_id)
        return await self._reload_bid(bid_id)

    async def add_adjustment(
        self,
        bid_id: uuid.UUID,
        data: BidAdjustmentCreate,
        *,
        actor_id: str | None = None,
    ) -> RFQBid:
        """Record an inclusion, an exclusion or a buyer allowance on a quote.

        This is how a quote that left delivery out is brought level with one
        that priced it: the amount is recorded against the quote, and the
        comparison adds it to that quote's comparable total. Nothing is
        estimated here on the quote's behalf; the amount is the one somebody
        entered.
        """
        bid, _rfq = await self._bid_for_open_rfq(bid_id, "adjust a quote")
        adjustment = self._build_adjustment(data, default_currency=bid.currency_code)
        adjustment.bid_id = bid_id
        await self.bids_repo.add_adjustment(adjustment)
        logger.info(
            "Bid %s adjustment recorded: %s %s (included=%s, source=%s) by %s",
            bid_id,
            adjustment.kind,
            adjustment.currency_code,
            adjustment.included_in_bid,
            adjustment.source,
            actor_id,
        )
        return await self._reload_bid(bid_id)

    async def _log_bid_decision(
        self,
        bid: RFQBid,
        *,
        action: str,
        actor_id: str | None,
        reason: str,
        to_status: str,
    ) -> None:
        """Write one standing decision to the activity log, best effort.

        The decision is already stored on the quote; the log is the trail that
        survives a later edit. A log backend that is unavailable must not undo
        a decision the buyer has taken.
        """
        try:
            from app.core.audit_log import log_activity

            await log_activity(
                self.session,
                actor_id=actor_id,
                entity_type="rfq_bid",
                entity_id=str(bid.id),
                action=action,
                from_status=bid.status,
                to_status=to_status,
                reason=reason,
                metadata={"rfq_id": str(bid.rfq_id), "bidder_contact_id": bid.bidder_contact_id},
            )
        except Exception:
            logger.debug("Audit log skipped for bid %s decision %s", bid.id, action)

    async def get_award(self, rfq_id: uuid.UUID) -> RFQAward:
        """The award record of one RFQ.

        Raises:
            HTTPException: 404 when the RFQ has not been awarded.
        """
        await self.get_rfq(rfq_id)  # 404 check
        award = await self.awards.get_for_rfq(rfq_id)
        if award is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="This RFQ has not been awarded",
            )
        return award

    # ── The quote gate ─────────────────────────────────────────────────────

    @staticmethod
    def _gate_dec(value: Any) -> Decimal:
        try:
            d = Decimal(str(value).replace(",", "").replace("$", "").strip())
            return d if d > 0 else Decimal("0")
        except Exception:  # noqa: BLE001 - any unparseable figure is zero, never a guess
            return Decimal("0")

    def quote_gate_status(self, rfq: RFQ) -> dict[str, Any]:
        """How this package stands against the tiered quote rule.

        Package value = the LARGEST of the buyer's estimate
        (``rfq.metadata_["estimated_value"]``) and every standing bid - so
        a package estimated at $2k that draws a $9k quote needs three
        prices, not one. The quoted COUNT is distinct suppliers with a
        price > 0 whose bid still stands (withdrawn / disqualified bids do
        not count, and a supplier's question never becomes a bid at all -
        the "a question is not a quote" rule holds by construction).
        """
        rule = quote_gate_rule()
        standing = [b for b in rfq.bids if b.status not in (BID_STATUS_WITHDRAWN, BID_STATUS_DISQUALIFIED)]
        prices = [self._gate_dec(b.bid_amount) for b in standing]
        raw_estimate = (rfq.metadata_ or {}).get("estimated_value")
        estimate = self._gate_dec(raw_estimate)
        value = max([estimate, *prices], default=Decimal("0"))
        counted = {str(b.bidder_contact_id) for b in standing if self._gate_dec(b.bid_amount) > 0}
        required = 1
        if value > Decimal(str(rule["over3"])):
            required = int(rule["min3"])
        elif value > Decimal(str(rule["over"])):
            required = int(rule["min"])
        # AN ESTIMATE WE CANNOT READ IS NOT AN ESTIMATE OF ZERO. Something
        # was written in the box and it did not parse, so the package
        # value is unknown - and unknown has to mean the top tier, not the
        # bottom one. Written text with no standing price behind it was
        # the exact shape that let a $50k package award on one quote.
        from app.core.money_text import parse_amount

        if str(raw_estimate or "").strip() and parse_amount(raw_estimate) is None:
            required = max(required, int(rule["min3"]))
        return {
            "value": format(value, "f"),
            "required": required,
            "counted": len(counted),
            "quoted_suppliers": sorted(counted),
            "rule": {k: str(v) for k, v in rule.items()},
            "passes": len(counted) >= required,
        }

    async def _award_confirmation_correspondence(
        self,
        *,
        project_id: uuid.UUID,
        rfq_number: str,
        rfq_title: str,
        bidder_contact_id: str,
        amount: str,
        currency: str,
        po_number: str | None,
        actor_id: str | None,
    ) -> None:
        """File an outgoing correspondence record for the award confirmation.

        Best-effort by design: the award must never roll back because the
        correspondence module is absent or unhappy. The record is the
        register entry the confirmation email is written FROM - this module
        sends nothing itself.
        """
        # A SAVEPOINT, or "best-effort" is a lie. Catching the exception is
        # not enough: the failing flush has already put the session into a
        # rolled-back state, so every later statement raises
        # PendingRollbackError and the award this was meant to protect dies
        # anyway - after the business has committed to a supplier. Seen for
        # real on a foreign-key violation writing the confirmation row.
        try:
            async with self.session.begin_nested():
                await self._write_award_confirmation(
                    project_id=project_id,
                    rfq_number=rfq_number,
                    rfq_title=rfq_title,
                    bidder_contact_id=bidder_contact_id,
                    amount=amount,
                    currency=currency,
                    po_number=po_number,
                    actor_id=actor_id,
                )
        except Exception:  # noqa: BLE001
            logger.warning("Award confirmation correspondence skipped for %s", rfq_number, exc_info=True)

    async def _write_award_confirmation(
        self,
        *,
        project_id: uuid.UUID,
        rfq_number: str,
        rfq_title: str,
        bidder_contact_id: Any,
        amount: Any,
        currency: str,
        po_number: str | None,
        actor_id: str | None,
    ) -> None:
        """The confirmation row itself. Called only inside a savepoint."""
        from app.modules.correspondence.models import Correspondence
        from app.modules.correspondence.repository import CorrespondenceRepository

        repo = CorrespondenceRepository(self.session)
        reference = await repo.next_reference_number(project_id)
        po_bit = f" - PO {po_number}" if po_number else ""
        row = Correspondence(
            project_id=project_id,
            reference_number=reference,
            direction="outgoing",
            subject=f"AWARD - {rfq_number}{po_bit} - {rfq_title}"[:500],
            correspondence_type="email",
            to_contact_ids=[str(bidder_contact_id)],
            status="open",
            notes=(
                f"Order confirmation for {rfq_number} ({rfq_title}).\n"
                f"Awarded value: {currency} {amount}"
                + (f"\nOur PO #: {po_number}" if po_number else "")
                + "\nThis register entry records the confirmation to be sent to the winning supplier."
            ),
            created_by=actor_id,
            metadata_={"rfq_award": {"rfq_number": rfq_number, "po_number": po_number}},
        )
        self.session.add(row)
        await self.session.flush()
        from app.core.events import event_bus

        event_bus.publish_detached(
            "correspondence.created",
            {
                "project_id": str(project_id),
                "correspondence_id": str(row.id),
                "reference_number": reference,
            },
            source_module="rfq_bidding",
        )

    async def award_bid(
        self,
        bid_id: uuid.UUID,
        *,
        actor_id: str | None = None,
        actor_role: str | None = None,
        reason: str | None = None,
        gate_override_reason: str | None = None,
        po_number: str | None = None,
    ) -> RFQBid:
        """Award a bid and transition the RFQ to awarded status.

        Only one bid can be awarded per RFQ. Attempting to award a second
        bid raises a 409 Conflict.

        ``actor_role`` MUST be one of ``admin`` / ``manager`` / ``owner``
        per the FSM contract on ``bids_received → awarded``. The router-
        level ``rfq.update`` permission lets EDITOR call this entrypoint,
        which would side-step the FSM contract, so we re-check here.

        The quote being awarded must be one the comparison could actually put
        on the RFQ's basis. Awarding a quote that was kept out of the ranking -
        priced in a currency with no rate recorded, covering part of the scope,
        arrived late and never admitted - would mean the decision rests on a
        comparison that did not include it, which is the one thing this
        register exists to make impossible.
        """
        # ── Role gate (mirrors FSM ``bids_received → awarded`` required_roles) ─
        self._require_award_role(actor_role, "RFQ award")

        bid = await self.get_bid(bid_id)

        if bid.is_awarded:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This bid has already been awarded",
            )

        # Race-safe "already-awarded?" check: read the RFQ AND its sibling
        # bids fresh so two concurrent /award/ calls can't both pass the
        # gate. The selectinload on RFQ.bids on the second call observes
        # the first call's write because both share this AsyncSession and
        # the update was flushed.
        rfq = await self.get_rfq(bid.rfq_id)
        for existing_bid in rfq.bids:
            if existing_bid.is_awarded and existing_bid.id != bid_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Another bid has already been awarded for this RFQ",
                )

        # FSM-style transition gate: we accept any non-terminal status to
        # preserve back-compat with demo data, but explicitly reject
        # awarding into a cancelled / completed RFQ.
        prior_status = rfq.status
        if prior_status in {"cancelled", "completed"}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(f"Cannot award bid against RFQ in terminal status '{prior_status}'."),
            )

        # Put the whole field on one basis and refuse to award a quote the
        # comparison could not place there. The reasons are the comparison's
        # own, so the refusal says exactly what the buyer has to fix: record a
        # rate, admit the late quote, allow partial scope, or price the gap.
        comparison = self.compare_payload(rfq)
        candidate = comparison.get(str(bid_id))
        if candidate is None or not candidate.comparable:
            reasons = ", ".join(candidate.reasons) if candidate else "quote not found in the comparison"
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"This quote was not comparable with the others and cannot be awarded: {reasons}",
            )

        # ── The award reason is the justification on the file ─────────────
        # Ported rail: an award without a written reason is refused outright.
        # The comparison shows WHAT won; the reason records WHY - and it is
        # what gets read years later when the decision is questioned.
        if not (reason and reason.strip()):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "An award must record why this supplier won (e.g. 'Best price', "
                    "'Only supplier who quoted'). The reason is the justification on the file."
                ),
            )

        # ── The quote gate ────────────────────────────────────────────────
        # Tiered minimum price-count off the package value. The award is an
        # enforcement point in its own right - a UI that skipped the compare
        # step must still be stopped here. Overriding requires a WRITTEN
        # reason which lands on the award record; silent overrides do not
        # exist.
        gate = self.quote_gate_status(rfq)
        if not gate["passes"]:
            # The override reason is judged the way the workflow gates judge
            # theirs: a non-answer ("x", "n/a") on the award file is a silent
            # override wearing a costume. reason_rejected tells the UI to ask
            # again rather than give up.
            problem = _override_reason_bad(gate_override_reason)
            if problem:
                base = (
                    f"The quote rule for a package of {gate['value']} requires "
                    f"{gate['required']} written price(s); {gate['counted']} recorded. "
                    "(A supplier asking a question does not count as a quote.)"
                )
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "error": base if not (gate_override_reason or "").strip() else f"{base} {problem}",
                        "gate": "quotes",
                        "can_force": True,
                        "reason_rejected": bool((gate_override_reason or "").strip()),
                        "quote_gate": gate,
                    },
                )
        if not gate["passes"]:
            logger.warning(
                "rfq.award_below_quote_rule %s",
                {"rfq_id": str(rfq.id), "gate": gate, "override_reason": gate_override_reason},
            )

        # Validate the field of bids the award is being taken from, before the
        # write expires the instance. The comparison that picked this bid has
        # already happened by now, so the point of the report is to say what
        # that comparison rested on. Reporting, not refusing.
        await self._report_rfq_validation(
            rfq,
            rule_set=RFQ_AWARD_RULE_SET,
            operation="award",
            candidate_bid_id=bid_id,
        )

        # Capture identity + display fields BEFORE calling repo.update().
        # The repo's `expire_all()` invalidates these ORM-managed
        # attributes, which would otherwise trigger an implicit sync
        # SQL fetch in the next access (MissingGreenlet under async).
        rfq_id_local = bid.rfq_id
        rfq_number_local = rfq.rfq_number
        bidder_contact_local = bid.bidder_contact_id
        bid_amount_local = bid.bid_amount
        bid_currency_local = bid.currency_code
        project_id_local = rfq.project_id

        # Mark the bid as awarded
        await self.bids_repo.update(bid_id, is_awarded=True)

        # Transition the RFQ to awarded status
        await self.rfqs.update(rfq_id_local, status="awarded")

        # Keep the ranked table as it stood at this moment. Recomputing it
        # later answers a different question: a quote edited afterwards, a rate
        # corrected, a line added, and the comparison that justified this award
        # would no longer be reproducible.
        recommended = comparison.recommended_bid_id
        is_override = recommended is not None and recommended != str(bid_id)
        award = RFQAward(
            rfq_id=rfq_id_local,
            bid_id=bid_id,
            awarded_by=uuid.UUID(actor_id) if actor_id else None,
            awarded_at=datetime.now(UTC).isoformat(),
            method=comparison.method,
            reason=reason,
            recommended_bid_id=uuid.UUID(recommended) if recommended else None,
            is_override=is_override,
            awarded_amount=candidate.normalised_amount or Decimal("0"),
            awarded_currency=comparison.basis_currency or bid_currency_local,
            basis={
                **comparison.as_dict(),
                "awarded_bid_id": str(bid_id),
                "quote_gate": {
                    **gate,
                    "override_reason": (gate_override_reason or "").strip() or None,
                },
                "po_number": (po_number or "").strip() or None,
            },
        )
        # The in-Python "already awarded?" check above only holds within one
        # session. Two award requests racing in separate sessions both pass
        # it, and the loser then violates uq_oe_rfq_award_rfq - which
        # surfaced as an unexplained 500 on a screen where the user has just
        # committed the business to a supplier. The constraint is the real
        # rail; this turns it into the same 409 the single-session path
        # gives, so the second person is told what happened.
        from sqlalchemy.exc import IntegrityError

        try:
            if self.session is None:  # pure-logic tests drive the repos directly
                await self.awards.create(award)
            else:
                # A savepoint, so the losing insert rolls back on its own
                # without poisoning the session the 409 still has to travel out on.
                async with self.session.begin_nested():
                    await self.awards.create(award)
        except IntegrityError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This package has just been awarded by someone else - reload to see who won.",
            ) from None

        # File the order-confirmation register entry to the winner (the
        # PO-confirmation email, as a correspondence record the comms layer
        # can draft from). Best-effort.
        await self._award_confirmation_correspondence(
            project_id=project_id_local,
            rfq_number=rfq_number_local,
            rfq_title=rfq.title or "",
            bidder_contact_id=bidder_contact_local,
            amount=format(candidate.normalised_amount or Decimal("0"), "f"),
            currency=comparison.basis_currency or bid_currency_local,
            po_number=po_number,
            actor_id=actor_id,
        )
        if is_override:
            logger.warning(
                "rfq.award_overrides_ranking %s",
                {
                    "rfq_id": str(rfq_id_local),
                    "awarded_bid_id": str(bid_id),
                    "recommended_bid_id": recommended,
                    "reason": reason,
                },
            )

        try:
            from app.core.audit_log import log_activity

            await log_activity(
                self.session,
                actor_id=actor_id,
                entity_type="rfq",
                entity_id=str(rfq_id_local),
                action="status_changed",
                from_status=prior_status,
                to_status="awarded",
                reason=reason or "RFQ awarded via award_bid()",
                metadata={
                    "rfq_number": rfq_number_local,
                    "bid_id": str(bid_id),
                    "bidder_contact_id": bidder_contact_local,
                    "bid_amount": bid_amount_local,
                    "currency_code": bid_currency_local,
                    "normalised_amount": format(candidate.normalised_amount or Decimal("0"), "f"),
                    "basis_currency": comparison.basis_currency,
                    "is_override": is_override,
                    "recommended_bid_id": recommended,
                },
            )
        except Exception:
            logger.debug("FSM audit log skipped for RFQ %s award", rfq_id_local)

        # Notification + downstream subscribers (procurement PO creation, etc).
        # Best-effort: a flaky subscriber must not roll back the award itself.
        try:
            from app.core.events import event_bus

            await event_bus.publish(
                "rfq.awarded",
                {
                    "rfq_id": str(rfq_id_local),
                    "rfq_number": rfq_number_local,
                    "bid_id": str(bid_id),
                    "bidder_contact_id": bidder_contact_local,
                    "bid_amount": bid_amount_local,
                    "currency_code": bid_currency_local,
                    "project_id": str(project_id_local),
                    "actor_id": actor_id,
                    # The number downstream commitments should carry: the
                    # headline restated on the RFQ's basis, which is what the
                    # decision was actually taken on.
                    "normalised_amount": format(candidate.normalised_amount or Decimal("0"), "f"),
                    "basis_currency": comparison.basis_currency,
                    "award_id": str(award.id),
                    "is_override": is_override,
                },
                source_module="rfq_bidding",
            )
        except Exception:
            logger.exception("rfq.awarded event publish failed for %s", rfq_id_local)

        logger.info(
            "Bid awarded: %s for RFQ %s by actor %s (override=%s)",
            bid_id,
            rfq_id_local,
            actor_id,
            is_override,
        )
        return await self._reload_bid(bid_id)
