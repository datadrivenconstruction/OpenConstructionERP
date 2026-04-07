"""RFQ Bidding service — business logic for RFQ and bid management.

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


class RFQService:
    """Business logic for RFQ and bidding operations."""

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
        """Create a new RFQ."""
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

    async def issue_rfq(self, rfq_id: uuid.UUID) -> RFQ:
        """Transition RFQ from draft to issued."""
        rfq = await self.get_rfq(rfq_id)
        if rfq.status != "draft":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot issue RFQ in status '{rfq.status}'",
            )
        await self.rfqs.update(rfq_id, status="issued")
        updated = await self.rfqs.get(rfq_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="RFQ not found",
            )
        logger.info("RFQ issued: %s", rfq.rfq_number)
        return updated

    # ── Bids ────────────────────────────────────────────────────────────────

    async def submit_bid(
        self,
        data: BidCreate,
        user_id: str | None = None,
    ) -> RFQBid:
        """Submit a bid against an RFQ."""
        await self.get_rfq(data.rfq_id)  # 404 check

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
        """Score a bid (technical + commercial evaluation)."""
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

    async def award_bid(self, bid_id: uuid.UUID) -> RFQBid:
        """Award a bid and transition the RFQ to awarded status."""
        bid = await self.get_bid(bid_id)

        # Mark the bid as awarded
        await self.bids_repo.update(bid_id, is_awarded=True)

        # Transition the RFQ to awarded status
        await self.rfqs.update(bid.rfq_id, status="awarded")

        updated = await self.bids_repo.get(bid_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Bid not found",
            )
        logger.info("Bid awarded: %s for RFQ %s", bid_id, bid.rfq_id)
        return updated
