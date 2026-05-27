"""‌⁠‍RFQ Bidding service — business logic for RFQ and bid management.

Stateless service layer.
"""

import logging
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.rfq_bidding.models import RFQ, RFQBid
from app.modules.rfq_bidding.repository import RFQBidRepository, RFQRepository
from app.modules.rfq_bidding.schemas import (
    BidCreate,
    BidEvaluation,
    RFQCreate,
    RFQUpdate,
)

logger = logging.getLogger(__name__)

# RFQ statuses where a vendor may still submit a bid. Submissions against
# draft / awarded / completed / cancelled RFQs are rejected — those would
# otherwise allow a vendor to slip a bid in after the award has been made
# or before the RFQ has been published.
_BID_SUBMISSION_OPEN_STATUSES: frozenset[str] = frozenset({"published", "issued", "bids_received"})

# Roles permitted to award an RFQ (mirrors FSM registry
# ``bids_received → awarded`` ``required_roles=("admin", "manager")``).
# The router-level ``rfq.update`` permission lets EDITOR call award_bid,
# which would side-step the FSM contract — service must re-check.
_AWARD_ALLOWED_ROLES: frozenset[str] = frozenset({"admin", "manager", "owner"})


class RFQService:
    """‌⁠‍Business logic for RFQ and bidding operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.rfqs = RFQRepository(session)
        self.bids_repo = RFQBidRepository(session)

    # ── RFQs ────────────────────────────────────────────────────────────────

    async def create_rfq(
        self,
        data: RFQCreate,
        user_id: str | None = None,
    ) -> RFQ:
        """‌⁠‍Create a new RFQ."""
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
            created_by=uuid.UUID(user_id) if user_id else None,
            metadata_=data.metadata,
        )
        rfq = await self.rfqs.create(rfq)
        logger.info("RFQ created: %s (%s)", rfq.rfq_number, rfq.title[:50])
        return rfq

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
        await self.get_rfq(rfq_id)  # 404 check

        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

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

        v3033 unified the lifecycle nomenclature — the new canonical status
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
        # Snapshot fields BEFORE rfqs.update() — that call invokes
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

    # ── Bids ────────────────────────────────────────────────────────────────

    async def submit_bid(
        self,
        data: BidCreate,
        user_id: str | None = None,
    ) -> RFQBid:
        """Submit a bid against an RFQ.

        Rejects:
            * RFQ not found (404)
            * RFQ in a non-bidding status — draft / awarded / cancelled /
              completed (409 Conflict).
            * Submission past ``rfq.submission_deadline`` if set (409).
        """
        rfq = await self.get_rfq(data.rfq_id)  # 404 check

        # Lifecycle gate — bidding is only legal while the RFQ is open.
        if rfq.status not in _BID_SUBMISSION_OPEN_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot submit bid against RFQ in status '{rfq.status}'; RFQ must be published or accepting bids."
                ),
            )

        # Deadline gate — best-effort ISO parse. If deadline is malformed
        # we DO NOT silently allow late submissions; we 422 because a
        # malformed deadline on the RFQ is a data-quality bug a buyer
        # must resolve before bids land.
        if rfq.submission_deadline:
            try:
                deadline = datetime.fromisoformat(rfq.submission_deadline.replace("Z", "+00:00"))
                if deadline.tzinfo is None:
                    deadline = deadline.replace(tzinfo=UTC)
                if datetime.now(UTC) > deadline:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="RFQ submission deadline has passed",
                    )
            except (ValueError, TypeError):
                logger.warning(
                    "RFQ %s has malformed submission_deadline %r — bid rejected",
                    data.rfq_id,
                    rfq.submission_deadline,
                )
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="RFQ submission_deadline is malformed; ask buyer to fix",
                ) from None

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
            metadata_=data.metadata,
        )
        bid = await self.bids_repo.create(bid)
        logger.info("Bid submitted: %s for RFQ %s", data.bid_amount, data.rfq_id)
        return bid

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

        Scores must be between 0 and 100 if provided.
        """
        await self.get_bid(bid_id)  # 404 check

        # Validate score ranges (0-100)
        for field_name in ("technical_score", "commercial_score"):
            value = getattr(data, field_name, None)
            if value is not None:
                try:
                    score = float(value)
                    if score < 0 or score > 100:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"{field_name} must be between 0 and 100, got {value}",
                        )
                except ValueError:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"{field_name} must be a valid number, got '{value}'",
                    )

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

    async def award_bid(
        self,
        bid_id: uuid.UUID,
        *,
        actor_id: str | None = None,
        actor_role: str | None = None,
        reason: str | None = None,
    ) -> RFQBid:
        """Award a bid and transition the RFQ to awarded status.

        Only one bid can be awarded per RFQ. Attempting to award a second
        bid raises a 409 Conflict.

        ``actor_role`` MUST be one of ``admin`` / ``manager`` / ``owner``
        per the FSM contract on ``bids_received → awarded``. The router-
        level ``rfq.update`` permission lets EDITOR call this entrypoint,
        which would side-step the FSM contract, so we re-check here.
        """
        # ── Role gate (mirrors FSM ``bids_received → awarded`` required_roles) ─
        # ``None`` actor_role is treated as a bypass ONLY for back-compat
        # with internal/system callers (background reconciliation, demo
        # seeders, tests that don't simulate JWT). HTTP requests always
        # pass a role through the router.
        if actor_role is not None and actor_role.lower() not in _AWARD_ALLOWED_ROLES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(f"RFQ award requires admin or manager role; role '{actor_role}' is not permitted."),
            )

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
                },
                source_module="rfq_bidding",
            )
        except Exception:
            logger.exception("rfq.awarded event publish failed for %s", rfq_id_local)

        updated = await self.bids_repo.get(bid_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Bid not found",
            )
        logger.info(
            "Bid awarded: %s for RFQ %s by actor %s",
            bid_id,
            rfq_id_local,
            actor_id,
        )
        return updated
