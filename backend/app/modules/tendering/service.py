"""Tendering service — business logic for tender packages and bids.

Stateless service layer. Handles:
- Package CRUD with status workflow
- Bid CRUD and comparison generation
- Event publishing on key actions
"""

import logging
import uuid

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus

_logger_ev = __import__("logging").getLogger(__name__ + ".events")


async def _safe_publish(name: str, data: dict, source_module: str = "") -> None:
    try:
        await event_bus.publish(name, data, source_module=source_module)
    except Exception:
        _logger_ev.debug("Event publish skipped: %s", name)


from app.modules.tendering.models import TenderBid, TenderPackage
from app.modules.tendering.repository import TenderingRepository
from app.modules.tendering.schemas import (
    BidComparisonResponse,
    BidComparisonRow,
    BidCreate,
    BidUpdate,
    PackageCreate,
    PackageUpdate,
)

logger = logging.getLogger(__name__)


class TenderingService:
    """Business logic for tendering operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = TenderingRepository(session)

    # ── Packages ─────────────────────────────────────────────────────────

    async def create_package(self, data: PackageCreate) -> TenderPackage:
        """Create a new tender package."""
        package = TenderPackage(
            project_id=data.project_id,
            boq_id=data.boq_id,
            name=data.name,
            description=data.description,
            deadline=data.deadline,
            metadata_=data.metadata,
        )
        package = await self.repo.create_package(package)
        logger.info("Tender package created: %s", package.name)
        return package

    async def get_package(self, package_id: uuid.UUID) -> TenderPackage:
        """Get a package by ID. Raises 404 if not found."""
        package = await self.repo.get_package_by_id(package_id)
        if package is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tender package not found",
            )
        return package

    async def list_packages(
        self,
        *,
        project_id: uuid.UUID | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[TenderPackage], int]:
        """List packages with optional project filter."""
        return await self.repo.list_packages(project_id=project_id, offset=offset, limit=limit)

    async def update_package(self, package_id: uuid.UUID, data: PackageUpdate) -> TenderPackage:
        """Update package fields. Raises 404 if not found."""
        await self.get_package(package_id)

        fields = data.model_dump(exclude_unset=True)

        # Map schema field 'metadata' to model column 'metadata_'
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        if not fields:
            return await self.get_package(package_id)

        await self.repo.update_package_fields(package_id, **fields)

        # await _safe_publish(
        # "tendering.package.updated",
        # {
        # "package_id": str(package_id),
        # "updated_fields": list(fields.keys()),
        # },
        # source_module="oe_tendering",
        # )

        logger.info("Tender package updated: %s (fields=%s)", package_id, list(fields.keys()))

        # Re-fetch to return updated data with relationships
        return await self.get_package(package_id)

    # ── Bids ─────────────────────────────────────────────────────────────

    async def create_bid(self, package_id: uuid.UUID, data: BidCreate) -> TenderBid:
        """Create a new bid for a package."""
        # Verify package exists
        await self.get_package(package_id)

        line_items_raw = [item.model_dump() for item in data.line_items]

        bid = TenderBid(
            package_id=package_id,
            company_name=data.company_name,
            contact_email=data.contact_email,
            total_amount=data.total_amount,
            currency=data.currency,
            submitted_at=data.submitted_at,
            status=data.status,
            notes=data.notes,
            line_items=line_items_raw,
            metadata_=data.metadata,
        )
        bid = await self.repo.create_bid(bid)

        # await _safe_publish(
        # "tendering.bid.created",
        # {
        # "bid_id": str(bid.id),
        # "package_id": str(package_id),
        # "company_name": bid.company_name,
        # },
        # source_module="oe_tendering",
        # )

        logger.info("Bid created: %s for package %s", bid.company_name, package_id)
        return bid

    async def get_bid(self, bid_id: uuid.UUID) -> TenderBid:
        """Get a bid by ID. Raises 404 if not found."""
        bid = await self.repo.get_bid_by_id(bid_id)
        if bid is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Bid not found",
            )
        return bid

    async def list_bids(self, package_id: uuid.UUID) -> list[TenderBid]:
        """List all bids for a package."""
        await self.get_package(package_id)
        return await self.repo.list_bids_for_package(package_id)

    async def update_bid(self, bid_id: uuid.UUID, data: BidUpdate) -> TenderBid:
        """Update bid fields. Raises 404 if not found."""
        await self.get_bid(bid_id)

        fields = data.model_dump(exclude_unset=True)

        # Map schema field 'metadata' to model column 'metadata_'
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        # Serialize line_items if present
        if "line_items" in fields and fields["line_items"] is not None:
            fields["line_items"] = [
                item.model_dump() if hasattr(item, "model_dump") else item for item in fields["line_items"]
            ]

        if not fields:
            return await self.get_bid(bid_id)

        await self.repo.update_bid_fields(bid_id, **fields)

        # await _safe_publish(
        # "tendering.bid.updated",
        # {
        # "bid_id": str(bid_id),
        # "updated_fields": list(fields.keys()),
        # },
        # source_module="oe_tendering",
        # )

        logger.info("Bid updated: %s (fields=%s)", bid_id, list(fields.keys()))
        return await self.get_bid(bid_id)

    # ── Comparison ───────────────────────────────────────────────────────

    async def compare_bids(self, package_id: uuid.UUID) -> BidComparisonResponse:
        """Generate a side-by-side bid comparison for a package.

        Builds a matrix of positions vs. bids, computing totals and
        deviation percentages from the budget (first available BOQ rates).
        """
        package = await self.get_package(package_id)
        bids = await self.repo.list_bids_for_package(package_id)

        # Load BOQ positions as the budget baseline
        from app.modules.boq.service import BOQService

        boq_service = BOQService(self.session)
        try:
            boq_data = await boq_service.get_boq_with_positions(package.boq_id)
            budget_positions = boq_data.positions
        except HTTPException:
            budget_positions = []

        # Build position map from BOQ
        position_map: dict[str, dict] = {}
        budget_total = 0.0
        for pos in budget_positions:
            pid = str(pos.id)
            qty = float(pos.quantity) if pos.quantity else 0.0
            rate = float(pos.unit_rate) if pos.unit_rate else 0.0
            total = float(pos.total) if pos.total else qty * rate
            position_map[pid] = {
                "position_id": pid,
                "description": pos.description or "",
                "unit": pos.unit or "",
                "quantity": qty,
                "unit_rate": rate,
                "total": total,
                "ordinal": pos.ordinal or "",
            }
            budget_total += total

        # Build comparison rows
        rows: list[BidComparisonRow] = []
        for pid, pdata in position_map.items():
            bid_entries = []
            for bid in bids:
                # Find matching line item in bid
                matching = None
                for item in bid.line_items or []:
                    if item.get("position_id") == pid:
                        matching = item
                        break
                if matching:
                    bid_rate = float(matching.get("unit_rate", 0))
                    bid_total = float(matching.get("total", 0))
                    budget_rate = pdata["unit_rate"]
                    deviation = ((bid_rate - budget_rate) / budget_rate * 100) if budget_rate > 0 else 0.0
                    bid_entries.append(
                        {
                            "company_name": bid.company_name,
                            "bid_id": str(bid.id),
                            "unit_rate": bid_rate,
                            "total": bid_total,
                            "deviation_pct": round(deviation, 1),
                        }
                    )
                else:
                    bid_entries.append(
                        {
                            "company_name": bid.company_name,
                            "bid_id": str(bid.id),
                            "unit_rate": 0.0,
                            "total": 0.0,
                            "deviation_pct": 0.0,
                        }
                    )

            rows.append(
                BidComparisonRow(
                    position_id=pid,
                    description=pdata["description"],
                    unit=pdata["unit"],
                    budget_quantity=pdata["quantity"],
                    budget_rate=pdata["unit_rate"],
                    budget_total=pdata["total"],
                    bids=bid_entries,
                )
            )

        # Build bid totals
        bid_totals = []
        for bid in bids:
            total = float(bid.total_amount) if bid.total_amount else 0.0
            deviation = ((total - budget_total) / budget_total * 100) if budget_total > 0 else 0.0
            bid_totals.append(
                {
                    "bid_id": str(bid.id),
                    "company_name": bid.company_name,
                    "total": total,
                    "currency": bid.currency,
                    "deviation_pct": round(deviation, 1),
                    "status": bid.status,
                }
            )

        return BidComparisonResponse(
            package_id=package_id,
            package_name=package.name,
            bid_count=len(bids),
            bid_companies=[b.company_name for b in bids],
            budget_total=budget_total,
            rows=rows,
            bid_totals=bid_totals,
        )

    async def apply_winner(
        self,
        package_id: uuid.UUID,
        bid_id: uuid.UUID,
    ) -> dict:
        """Apply a winning bid's unit rates back to the BOQ.

        Iterates the bid's ``line_items`` and updates the matching BOQ
        position ``unit_rate`` (recomputing ``total`` via quantity * new rate).
        The package is transitioned to ``awarded`` and the bid to ``awarded``
        status. An event is published for downstream budget / EVM modules.
        """
        package = await self.get_package(package_id)
        bid = await self.get_bid(bid_id)

        if bid.package_id != package_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Bid does not belong to this package",
            )
        if package.boq_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Package has no linked BOQ to write back to",
            )

        from decimal import Decimal, InvalidOperation

        from sqlalchemy import update

        from app.modules.boq.models import BOQPosition

        updated = 0
        for item in bid.line_items or []:
            pos_id = item.get("position_id")
            if not pos_id:
                continue
            try:
                rate = Decimal(str(item.get("unit_rate", "0")))
            except (InvalidOperation, ValueError):
                continue
            pos = await self.session.get(BOQPosition, uuid.UUID(str(pos_id)))
            if pos is None:
                continue
            try:
                qty = Decimal(str(pos.quantity or "0"))
            except (InvalidOperation, ValueError):
                qty = Decimal("0")
            new_total = qty * rate
            await self.session.execute(
                update(BOQPosition)
                .where(BOQPosition.id == pos.id)
                .values(unit_rate=str(rate), total=str(new_total))
            )
            updated += 1

        # Flip statuses — package: awarded, bid: awarded
        await self.repo.update_package_fields(package_id, status="awarded")
        await self.repo.update_bid_fields(bid_id, status="awarded")

        await _safe_publish(
            "tendering.package.awarded",
            {
                "package_id": str(package_id),
                "bid_id": str(bid_id),
                "company_name": bid.company_name,
                "positions_updated": updated,
                "boq_id": str(package.boq_id),
            },
            source_module="oe_tendering",
        )

        logger.info(
            "Tender winner applied: package=%s bid=%s positions_updated=%s",
            package_id,
            bid_id,
            updated,
        )
        return {
            "package_id": str(package_id),
            "bid_id": str(bid_id),
            "positions_updated": updated,
            "boq_id": str(package.boq_id),
        }

    # ── Project Intelligence (RFC 25) ──────────────────────────────────────

    async def get_bid_analysis(self, project_id: uuid.UUID):
        """Aggregate all bids for a project: vendors, outliers, spread."""
        from sqlalchemy import select

        from app.modules.tendering.schemas import (
            BidAnalysisResponse,
            BidOutlierEntry,
            BidSpread,
            BidVendorEntry,
        )

        stmt = (
            select(TenderBid)
            .join(TenderPackage, TenderBid.package_id == TenderPackage.id)
            .where(TenderPackage.project_id == project_id)
        )
        result = await self.session.execute(stmt)
        bids: list[TenderBid] = list(result.scalars().all())

        if not bids:
            return BidAnalysisResponse()

        def _to_float(value: str | None) -> float:
            try:
                return float(value) if value not in (None, "") else 0.0
            except (TypeError, ValueError):
                return 0.0

        totals: list[float] = [_to_float(b.total_amount) for b in bids]

        # Vendor rollup
        vendor_map: dict[str, dict[str, float | int | str]] = {}
        for bid, total in zip(bids, totals, strict=True):
            company = (bid.company_name or "").strip() or "(unnamed)"
            entry = vendor_map.setdefault(
                company,
                {
                    "company_name": company,
                    "total": 0.0,
                    "currency": bid.currency or "EUR",
                    "bid_count": 0,
                },
            )
            entry["total"] = float(entry["total"]) + total
            entry["bid_count"] = int(entry["bid_count"]) + 1

        vendors = [
            BidVendorEntry(
                company_name=str(v["company_name"]),
                total=round(float(v["total"]), 2),
                currency=str(v["currency"]),
                bid_count=int(v["bid_count"]),
            )
            for v in sorted(
                vendor_map.values(),
                key=lambda e: -float(e["total"]),
            )
        ]

        # Spread
        sorted_totals = sorted(totals)

        def _pct(values: list[float], p: float) -> float:
            if not values:
                return 0.0
            idx = max(0, min(len(values) - 1, int(round((len(values) - 1) * p))))
            return values[idx]

        p25 = _pct(sorted_totals, 0.25)
        p50 = _pct(sorted_totals, 0.50)
        p75 = _pct(sorted_totals, 0.75)
        mean = sum(totals) / len(totals)
        variance = sum((t - mean) ** 2 for t in totals) / len(totals)
        std = variance**0.5

        spread = BidSpread(
            min=round(sorted_totals[0], 2),
            max=round(sorted_totals[-1], 2),
            p25=round(p25, 2),
            p50=round(p50, 2),
            p75=round(p75, 2),
            mean=round(mean, 2),
            std=round(std, 2),
            sample_size=len(totals),
        )

        # Outliers (IQR rule)
        iqr = p75 - p25
        low_bound = p25 - 1.5 * iqr
        high_bound = p75 + 1.5 * iqr
        outliers: list[BidOutlierEntry] = []
        if len(totals) >= 4 and iqr > 0:
            for bid, total in zip(bids, totals, strict=True):
                if total < low_bound or total > high_bound:
                    reason = "too_low" if total < low_bound else "too_high"
                    outliers.append(
                        BidOutlierEntry(
                            bid_id=bid.id,
                            company_name=(bid.company_name or "").strip() or "(unnamed)",
                            total=round(total, 2),
                            reason=reason,
                        )
                    )

        return BidAnalysisResponse(vendors=vendors, outliers=outliers, spread=spread)
