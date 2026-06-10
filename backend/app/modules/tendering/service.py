"""‌⁠‍Tendering service - business logic for tender packages and bids.

Stateless service layer. Handles:
- Package CRUD with status workflow
- Bid CRUD and comparison generation
- Event publishing on key actions
"""

import logging
import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus

_logger_ev = __import__("logging").getLogger(__name__ + ".events")

# ── Lifecycle state machine ──────────────────────────────────────────────────
# Package status transitions. ``closed`` is terminal; ``awarded`` may still be
# closed for archival but never re-opened. Anything not listed is rejected.
_PACKAGE_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"draft", "issued", "closed"},
    "issued": {"issued", "collecting", "closed"},
    "collecting": {"collecting", "evaluating", "closed"},
    "evaluating": {"evaluating", "awarded", "closed"},
    "awarded": {"awarded", "closed"},
    "closed": {"closed"},
}

# Package states from which a winner may legitimately be applied. Awarding a
# draft/issued package, or re-awarding an already-awarded/closed one, is invalid.
_AWARDABLE_PACKAGE_STATES: set[str] = {"collecting", "evaluating"}

# Bid statuses that disqualify a bid from being awarded.
_NON_AWARDABLE_BID_STATES: set[str] = {"rejected"}

_CENTS = Decimal("0.01")


def _to_decimal(value: object, default: str = "0") -> Decimal:
    """Parse an arbitrary value into Decimal, never raising.

    Money is parsed exactly (no float intermediary) so bid-comparison sums and
    deviations are not subject to binary-float drift.
    """
    try:
        if value is None or value == "":
            return Decimal(default)
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def _round2(value: Decimal) -> float:
    """Round a Decimal to 2 dp at the presentation boundary and emit float.

    For the response-schema fields still typed ``float`` (quantities and
    informational totals); rounding happens only here so all intermediate
    arithmetic stays in Decimal.
    """
    return float(value.quantize(_CENTS, rounding=ROUND_HALF_UP))


def _round2_dec(value: Decimal) -> Decimal:
    """Round a Decimal to 2 dp and keep it Decimal (v3 §10 money fields)."""
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


async def _safe_publish(name: str, data: dict, source_module: str = "") -> None:
    try:
        event_bus.publish_detached(name, data, source_module=source_module)
    except Exception:
        _logger_ev.debug("Event publish skipped: %s", name)


from app.modules.tendering.models import TenderBid, TenderPackage
from app.modules.tendering.repository import TenderingRepository
from app.modules.tendering.schemas import (
    AddendumAckEntry,
    AddendumCreate,
    AddendumResponse,
    BidComparisonResponse,
    BidComparisonRow,
    BidCreate,
    BidLevelingSummary,
    BidUpdate,
    LevelBidsResponse,
    LevelingMatrixCell,
    LevelingMatrixResponse,
    LevelingMatrixRow,
    PackageCreate,
    PackageUpdate,
)

logger = logging.getLogger(__name__)


class TenderingService:
    """‌⁠‍Business logic for tendering operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = TenderingRepository(session)

    # ── Packages ─────────────────────────────────────────────────────────

    async def create_package(self, data: PackageCreate) -> TenderPackage:
        """‌⁠‍Create a new tender package."""
        package = TenderPackage(
            project_id=data.project_id,
            boq_id=data.boq_id,
            name=data.name,
            description=data.description,
            deadline=data.deadline,
            metadata_=data.metadata,
        )
        package = await self.repo.create_package(package)

        await _safe_publish(
            "tendering.package.created",
            {
                "package_id": str(package.id),
                "project_id": str(package.project_id),
                "boq_id": str(package.boq_id) if package.boq_id else None,
                "name": package.name,
                "deadline": package.deadline,
            },
            source_module="oe_tendering",
        )

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
        """Update package fields. Raises 404 if not found.

        Status changes are validated against the lifecycle state machine so
        illegal transitions (re-issuing a closed package, reverting an
        ``awarded`` package to ``draft``, skipping evaluation, etc.) are
        rejected with 409 instead of being silently persisted. ``boq_id`` is
        already immutable post-creation (absent from ``PackageUpdate``), so
        bids can never be re-pointed at a different BOQ underneath them.
        """
        package = await self.get_package(package_id)

        fields = data.model_dump(exclude_unset=True)

        # Map schema field 'metadata' to model column 'metadata_'
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        # Validate status transition before persisting anything.
        new_status = fields.get("status")
        if new_status is not None and new_status != package.status:
            allowed = _PACKAGE_TRANSITIONS.get(package.status, set())
            if new_status not in allowed:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(f"Illegal package transition: {package.status!r} → {new_status!r}"),
                )
            # Stamp lifecycle timestamps into metadata (no schema column
            # exists; metadata_ is the extensible store per the data model).
            meta = dict(package.metadata_ or {})
            stamp_key = {
                "issued": "issued_at",
                "closed": "closed_at",
                "awarded": "awarded_at",
            }.get(new_status)
            if stamp_key and stamp_key not in meta:
                meta[stamp_key] = datetime.now(UTC).isoformat()
                fields["metadata_"] = {**meta, **fields.get("metadata_", {})}
        elif new_status is not None and new_status == package.status:
            # No-op status write - drop it so we don't emit a misleading
            # "status changed" update event for an unchanged value.
            fields.pop("status")

        if not fields:
            return await self.get_package(package_id)

        await self.repo.update_package_fields(package_id, **fields)

        await _safe_publish(
            "tendering.package.updated",
            {
                "package_id": str(package_id),
                "updated_fields": list(fields.keys()),
            },
            source_module="oe_tendering",
        )

        logger.info("Tender package updated: %s (fields=%s)", package_id, list(fields.keys()))

        # Re-fetch to return updated data with relationships
        return await self.get_package(package_id)

    # ── Bids ─────────────────────────────────────────────────────────────

    async def create_bid(self, package_id: uuid.UUID, data: BidCreate) -> TenderBid:
        """Create a new bid for a package."""
        # Verify package exists
        await self.get_package(package_id)

        # v3 §10 - ``BidLineItem.unit_rate`` is Decimal; dump in JSON
        # mode so the serializer converts it to a string (the JSON DB
        # column can't natively persist a ``Decimal`` object).
        line_items_raw = [item.model_dump(mode="json") for item in data.line_items]

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

        await _safe_publish(
            "tendering.bid.created",
            {
                "bid_id": str(bid.id),
                "package_id": str(package_id),
                "company_name": bid.company_name,
                "total_amount": bid.total_amount,
                "currency": bid.currency,
                "status": bid.status,
            },
            source_module="oe_tendering",
        )

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

        # Serialize line_items if present - JSON mode coerces Decimal to
        # string so the persisted JSON value matches the wire contract.
        if "line_items" in fields and fields["line_items"] is not None:
            fields["line_items"] = [
                item.model_dump(mode="json") if hasattr(item, "model_dump") else item for item in fields["line_items"]
            ]

        if not fields:
            return await self.get_bid(bid_id)

        await self.repo.update_bid_fields(bid_id, **fields)

        await _safe_publish(
            "tendering.bid.updated",
            {
                "bid_id": str(bid_id),
                "updated_fields": list(fields.keys()),
            },
            source_module="oe_tendering",
        )

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

        # Build position map from BOQ (exact Decimal arithmetic).
        position_map: dict[str, dict] = {}
        budget_total = Decimal("0")
        for pos in budget_positions:
            pid = str(pos.id)
            qty = _to_decimal(pos.quantity)
            rate = _to_decimal(pos.unit_rate)
            total = _to_decimal(pos.total) if pos.total else qty * rate
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

        # Index each bid's line items by position_id once → comparison is
        # O(positions·bids + bids·line_items) instead of the previous
        # O(positions·bids·line_items) triple nested scan.
        bid_line_index: dict[str, dict[str, dict]] = {}
        for bid in bids:
            idx: dict[str, dict] = {}
            for item in bid.line_items or []:
                key = item.get("position_id")
                if key and key not in idx:
                    idx[key] = item
            bid_line_index[str(bid.id)] = idx

        # Best-effort cross-currency guard. The BOQ/Position ORM carries no
        # single authoritative budget currency (currency is tracked per
        # position payload), so we can only suppress a deviation when the
        # budget currency is actually discoverable. When it is not, we do not
        # invent one - we simply do not suppress (degrades safely, never
        # emits a *wrong* percentage). Where bidders disagree among
        # themselves, the dominant bid currency is treated as the comparison
        # baseline so a single odd-currency bid cannot poison every row.
        bid_ccy_counts: dict[str, int] = {}
        for b in bids:
            c = (b.currency or "").strip().upper()
            if c:
                bid_ccy_counts[c] = bid_ccy_counts.get(c, 0) + 1
        baseline_currency = ""
        if budget_positions:
            baseline_currency = (getattr(budget_positions[0], "currency", "") or "").strip().upper()
        if not baseline_currency and bid_ccy_counts:
            baseline_currency = max(bid_ccy_counts.items(), key=lambda kv: (kv[1], kv[0]))[0]

        def _bid_currency(bid: TenderBid) -> str:
            return (bid.currency or "").strip().upper()

        def _same_currency(bid: TenderBid) -> bool:
            bc = _bid_currency(bid)
            return not baseline_currency or not bc or bc == baseline_currency

        # Build comparison rows
        rows: list[BidComparisonRow] = []
        for pid, pdata in position_map.items():
            bid_entries = []
            budget_rate: Decimal = pdata["unit_rate"]
            for bid in bids:
                matching = bid_line_index.get(str(bid.id), {}).get(pid)
                if matching:
                    bid_rate = _to_decimal(matching.get("unit_rate", 0))
                    bid_total = _to_decimal(matching.get("total", 0))
                    if budget_rate > 0 and _same_currency(bid):
                        deviation = (bid_rate - budget_rate) / budget_rate * Decimal("100")
                        dev_val = round(float(deviation), 1)
                    else:
                        dev_val = 0.0
                    bid_entries.append(
                        {
                            "company_name": bid.company_name,
                            "bid_id": str(bid.id),
                            "unit_rate": _round2(bid_rate),
                            "total": _round2(bid_total),
                            "deviation_pct": dev_val,
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
                    budget_quantity=_round2(pdata["quantity"]),
                    budget_rate=_round2(budget_rate),
                    budget_total=_round2(pdata["total"]),
                    bids=bid_entries,
                )
            )

        # Build bid totals - never compute a deviation against the budget for
        # a bid quoted in a different currency (mixed-currency comparison is a
        # data error, not a 0% match).
        bid_totals = []
        for bid in bids:
            total = _to_decimal(bid.total_amount)
            if budget_total > 0 and _same_currency(bid):
                deviation = (total - budget_total) / budget_total * Decimal("100")
                dev_val = round(float(deviation), 1)
            else:
                dev_val = 0.0
            bid_totals.append(
                {
                    "bid_id": str(bid.id),
                    "company_name": bid.company_name,
                    "total": _round2(total),
                    "currency": bid.currency,
                    "deviation_pct": dev_val,
                    "status": bid.status,
                }
            )

        return BidComparisonResponse(
            package_id=package_id,
            package_name=package.name,
            bid_count=len(bids),
            bid_companies=[b.company_name for b in bids],
            budget_total=_round2(budget_total),
            rows=rows,
            bid_totals=bid_totals,
        )

    async def apply_winner(
        self,
        package_id: uuid.UUID,
        bid_id: uuid.UUID,
        awarded_by: str | None = None,
    ) -> dict:
        """Apply a winning bid's unit rates back to the BOQ.

        Iterates the bid's ``line_items`` and updates the matching BOQ
        position ``unit_rate`` (recomputing ``total`` via quantity * new rate).
        The package is transitioned to ``awarded``, the winning bid to
        ``accepted`` and every other bid to ``rejected``. An event is
        published for downstream budget / EVM modules.

        Lifecycle is enforced at the root:
        - the package must be in an awardable state (``collecting`` /
          ``evaluating``) - you cannot award a ``draft``/``issued`` package;
        - an already ``awarded``/``closed`` package cannot be re-awarded
          (no double-award);
        - a ``rejected``/disqualified bid cannot win.
        The decision-maker identity and timestamp are stamped into the
        package metadata (no dedicated column exists in the schema).
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
        if package.status not in _AWARDABLE_PACKAGE_STATES:
            # Covers double-award (already 'awarded'), awarding a 'draft'
            # or 'issued' package, and re-awarding a 'closed' one.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Package in status {package.status!r} cannot be awarded; "
                    f"it must be one of {sorted(_AWARDABLE_PACKAGE_STATES)}"
                ),
            )
        if bid.status in _NON_AWARDABLE_BID_STATES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(f"Bid is {bid.status!r} and cannot be awarded (disqualified bids are not eligible)"),
            )

        # ── Currency-mismatch guard ────────────────────────────────────────
        # Awarding writes the winning bid's unit_rate values straight into
        # the BOQ positions (which are denominated in the project currency).
        # If the winning bid - or any of its line items - is quoted in a
        # different currency we would silently overwrite project-currency
        # rates with foreign-currency numbers, corrupting the budget.
        # Block the award and surface every offending entity so the user
        # can re-quote in the right currency or run FX conversion first.
        from app.modules.projects.repository import ProjectRepository

        project_repo = ProjectRepository(self.session)
        project = await project_repo.get_by_id(package.project_id)
        project_currency = (getattr(project, "currency", "") or "").strip().upper() if project is not None else ""
        if project_currency:
            offenders: list[dict[str, str]] = []
            bid_ccy = (bid.currency or "").strip().upper()
            if bid_ccy and bid_ccy != project_currency:
                offenders.append(
                    {
                        "bid_id": str(bid.id),
                        "scope": "bid",
                        "currency": bid_ccy,
                    }
                )
            for idx, item in enumerate(bid.line_items or []):
                # line_items are stored as plain dicts; an optional per-line
                # currency override is honoured if present (some bid imports
                # carry it explicitly, see GAEB X84 / Excel templates).
                line_ccy_raw = item.get("currency") if isinstance(item, dict) else None
                line_ccy = (line_ccy_raw or "").strip().upper() if line_ccy_raw else ""
                if line_ccy and line_ccy != project_currency:
                    offenders.append(
                        {
                            "bid_id": str(bid.id),
                            "scope": f"line[{idx}]",
                            "position_id": str(item.get("position_id") or ""),
                            "currency": line_ccy,
                        }
                    )
            if offenders:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "code": "currency_mismatch",
                        "message": (
                            f"Winning bid currency does not match project "
                            f"currency {project_currency!r}; refusing to "
                            f"overwrite BOQ rates with foreign-currency values."
                        ),
                        "project_currency": project_currency,
                        "offenders": offenders,
                    },
                )

        from sqlalchemy import update

        from app.modules.boq.models import Position
        from app.modules.boq.service import _quantize_money_str

        updated = 0
        for item in bid.line_items or []:
            pos_id = item.get("position_id")
            if not pos_id:
                continue
            if "unit_rate" not in item:
                continue
            rate = _to_decimal(item.get("unit_rate"))
            try:
                pos_uuid = uuid.UUID(str(pos_id))
            except (ValueError, AttributeError):
                continue
            pos = await self.session.get(Position, pos_uuid)
            if pos is None:
                continue
            # A bid stores position_id values as free-form JSON; never trust
            # them to belong to this package's BOQ. Skip any foreign position
            # so a winning bid can only ever overwrite rates in its own BOQ.
            if pos.boq_id != package.boq_id:
                continue
            qty = _to_decimal(pos.quantity)
            # Quantize at this write boundary the same way every other BOQ
            # writer does (boq/service.py:_quantize_money_str). Writing the raw
            # Decimal would store more than 4 fractional digits and break the
            # money invariant the BOQ engine assumes, forcing a needless rewrite
            # on the next recompute.
            rate_str = _quantize_money_str(rate)
            new_total_str = _quantize_money_str(qty * rate)
            await self.session.execute(
                update(Position)
                .where(Position.id == pos.id, Position.boq_id == package.boq_id)
                .values(unit_rate=rate_str, total=new_total_str)
            )
            updated += 1

        # Stamp decision-maker identity + timestamp into package metadata
        # (the data model keeps lifecycle audit trail in metadata_).
        meta = dict(package.metadata_ or {})
        meta.setdefault("awarded_at", datetime.now(UTC).isoformat())
        if awarded_by:
            meta["awarded_by"] = str(awarded_by)
        meta["awarded_bid_id"] = str(bid_id)

        # Flip statuses - package: awarded, winning bid: accepted,
        # every competing bid: rejected (a closed tender has one winner).
        await self.repo.update_package_fields(package_id, status="awarded", metadata_=meta)
        all_bids = await self.repo.list_bids_for_package(package_id)
        for other in all_bids:
            if other.id == bid_id:
                if other.status != "accepted":
                    await self.repo.update_bid_fields(bid_id, status="accepted")
            elif other.status not in ("rejected",):
                await self.repo.update_bid_fields(other.id, status="rejected")

        await _safe_publish(
            "tendering.package.awarded",
            {
                "package_id": str(package_id),
                "bid_id": str(bid_id),
                "company_name": bid.company_name,
                "positions_updated": updated,
                "boq_id": str(package.boq_id),
                "awarded_by": str(awarded_by) if awarded_by else None,
            },
            source_module="oe_tendering",
        )

        logger.info(
            "Tender winner applied: package=%s bid=%s positions_updated=%s by=%s",
            package_id,
            bid_id,
            updated,
            awarded_by,
        )
        return {
            "package_id": str(package_id),
            "bid_id": str(bid_id),
            "positions_updated": updated,
            "boq_id": str(package.boq_id),
        }

    # ── Addenda (mid-tender clarifications) ────────────────────────────────
    # Addenda live in the package ``metadata_`` JSON store under ``addenda``
    # (an append-only list of revision dicts). No dedicated table is needed:
    # an addendum is a small, package-scoped revision log and ``metadata_`` is
    # already the data model's extensible per-package store. Each entry shape:
    #   {id, revision_no, title, body, published_at, published_by_user_id,
    #    acknowledged_by: [{bidder_id, acknowledged_at, user_id}],
    #    created_at, updated_at}

    @staticmethod
    def _addendum_to_response(package_id: uuid.UUID, raw: dict) -> AddendumResponse:
        acks = [
            AddendumAckEntry(
                bidder_id=str(a.get("bidder_id", "")),
                acknowledged_at=str(a.get("acknowledged_at", "")),
                user_id=a.get("user_id"),
            )
            for a in (raw.get("acknowledged_by") or [])
            if isinstance(a, dict)
        ]
        return AddendumResponse(
            id=str(raw.get("id", "")),
            package_id=package_id,
            revision_no=int(raw.get("revision_no", 0)),
            title=str(raw.get("title", "")),
            body=raw.get("body"),
            published_at=raw.get("published_at"),
            published_by_user_id=raw.get("published_by_user_id"),
            acknowledged_by=acks,
            created_at=str(raw.get("created_at", "")),
            updated_at=str(raw.get("updated_at", "")),
        )

    @staticmethod
    def _read_addenda(package: TenderPackage) -> list[dict]:
        raw = (package.metadata_ or {}).get("addenda")
        return [a for a in raw if isinstance(a, dict)] if isinstance(raw, list) else []

    async def list_addenda(self, package_id: uuid.UUID) -> list[AddendumResponse]:
        """List a package's addenda, oldest revision first."""
        package = await self.get_package(package_id)
        addenda = sorted(self._read_addenda(package), key=lambda a: int(a.get("revision_no", 0)))
        return [self._addendum_to_response(package_id, a) for a in addenda]

    async def create_addendum(self, package_id: uuid.UUID, data: AddendumCreate) -> AddendumResponse:
        """Append a new draft addendum to a package."""
        package = await self.get_package(package_id)
        addenda = self._read_addenda(package)
        next_rev = max((int(a.get("revision_no", 0)) for a in addenda), default=0) + 1
        now = datetime.now(UTC).isoformat()
        entry = {
            "id": str(uuid.uuid4()),
            "revision_no": next_rev,
            "title": data.title,
            "body": data.body,
            "published_at": None,
            "published_by_user_id": None,
            "acknowledged_by": [],
            "created_at": now,
            "updated_at": now,
        }
        meta = dict(package.metadata_ or {})
        meta["addenda"] = [*addenda, entry]
        await self.repo.update_package_fields(package_id, metadata_=meta)

        await _safe_publish(
            "tendering.addendum.created",
            {"package_id": str(package_id), "addendum_id": entry["id"], "revision_no": next_rev},
            source_module="oe_tendering",
        )
        logger.info("Addendum created: package=%s rev=%s", package_id, next_rev)
        return self._addendum_to_response(package_id, entry)

    async def find_addendum_package(
        self,
        addendum_id: str,
        accessible_project_ids: list[uuid.UUID] | None = None,
    ) -> tuple[TenderPackage, dict, int]:
        """Locate the package and stored entry for ``addendum_id``.

        Returns ``(package, entry, index)``. Raises 404 if no package holds an
        addendum with that id (the IDOR/access check still runs at the router,
        which scopes by the returned package's project).

        ``accessible_project_ids`` scopes the lookup to the caller's own
        projects so a regular user never triggers a cross-tenant table scan
        over every package in the database. ``None`` means "no filter" and is
        reserved for admins (who are cross-tenant by design); an empty list
        means the caller owns no projects and therefore can hold no addendum,
        so we short-circuit to 404 without any scan. The package relationship
        ``bids`` is *not* eager-loaded here - addendum lookup only reads the
        package ``metadata_`` JSON, so we avoid the heavy bids fan-out the old
        ``list_packages(limit=10_000)`` path incurred.
        """
        from sqlalchemy import select

        if accessible_project_ids is not None and len(accessible_project_ids) == 0:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Addendum not found")

        stmt = select(TenderPackage)
        if accessible_project_ids is not None:
            stmt = stmt.where(TenderPackage.project_id.in_(accessible_project_ids))
        result = await self.session.execute(stmt)
        for package in result.scalars().all():
            addenda = self._read_addenda(package)
            for idx, a in enumerate(addenda):
                if str(a.get("id")) == str(addendum_id):
                    return package, a, idx
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Addendum not found")

    async def publish_addendum(self, package: TenderPackage, addendum_id: str, user_id: str | None) -> AddendumResponse:
        """Mark an addendum as published (stamps timestamp + publisher)."""
        addenda = self._read_addenda(package)
        target_idx = next(
            (i for i, a in enumerate(addenda) if str(a.get("id")) == str(addendum_id)),
            None,
        )
        if target_idx is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Addendum not found")
        entry = dict(addenda[target_idx])
        if entry.get("published_at"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Addendum is already published",
            )
        now = datetime.now(UTC).isoformat()
        entry["published_at"] = now
        entry["published_by_user_id"] = str(user_id) if user_id else None
        entry["updated_at"] = now
        addenda[target_idx] = entry
        meta = dict(package.metadata_ or {})
        meta["addenda"] = addenda
        await self.repo.update_package_fields(package.id, metadata_=meta)

        await _safe_publish(
            "tendering.addendum.published",
            {"package_id": str(package.id), "addendum_id": addendum_id},
            source_module="oe_tendering",
        )
        logger.info("Addendum published: package=%s addendum=%s", package.id, addendum_id)
        return self._addendum_to_response(package.id, entry)

    async def acknowledge_addendum(
        self, package: TenderPackage, addendum_id: str, bidder_id: str, user_id: str | None
    ) -> AddendumResponse:
        """Record a bidder acknowledgement of a published addendum."""
        addenda = self._read_addenda(package)
        target_idx = next(
            (i for i, a in enumerate(addenda) if str(a.get("id")) == str(addendum_id)),
            None,
        )
        if target_idx is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Addendum not found")
        entry = dict(addenda[target_idx])
        if not entry.get("published_at"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot acknowledge a draft addendum; publish it first",
            )
        acks = [a for a in (entry.get("acknowledged_by") or []) if isinstance(a, dict)]
        if not any(str(a.get("bidder_id")) == str(bidder_id) for a in acks):
            acks.append(
                {
                    "bidder_id": str(bidder_id),
                    "acknowledged_at": datetime.now(UTC).isoformat(),
                    "user_id": str(user_id) if user_id else None,
                }
            )
        entry["acknowledged_by"] = acks
        entry["updated_at"] = datetime.now(UTC).isoformat()
        addenda[target_idx] = entry
        meta = dict(package.metadata_ or {})
        meta["addenda"] = addenda
        await self.repo.update_package_fields(package.id, metadata_=meta)
        logger.info(
            "Addendum acknowledged: package=%s addendum=%s bidder=%s",
            package.id,
            addendum_id,
            bidder_id,
        )
        return self._addendum_to_response(package.id, entry)

    # ── Bid leveling ───────────────────────────────────────────────────────
    # Normalize every bid onto the package's reference BOQ lines. Pure
    # computation over existing data (BOQ positions + bid line_items); no
    # persistence. Omitted lines are imputed at the bidder's own mean unit
    # rate so a short quote cannot win on a misleadingly low total.

    async def _build_leveling(
        self, package_id: uuid.UUID
    ) -> tuple[TenderPackage, list[LevelingMatrixRow], list[BidLevelingSummary], str, int]:
        package = await self.get_package(package_id)
        all_bids = await self.repo.list_bids_for_package(package_id)

        # Cross-currency guard. Leveling normalises every bid onto the SAME
        # reference BOQ quantities and emits raw_total / leveled_total numbers
        # with no per-cell currency tag - so blending bids quoted in different
        # currencies would silently sum euros with dollars. Scope leveling to
        # the package's reporting currency (mirrors compare_bids'
        # ``_same_currency`` and bid_management.leveling_matrix). Bids quoted in
        # another currency are excluded and their count is surfaced so the user
        # can re-quote / FX convert before trusting the leveled totals.
        #
        # Currency bug fix: ``TenderPackage`` has NO ``currency`` column (only
        # each ``TenderBid`` carries one), so the previous
        # ``package.currency`` read raised AttributeError -> HTTP 500 on both
        # leveling endpoints. The package's reporting currency is the project
        # currency, so derive it from the project exactly as ``apply_winner``
        # already does. Fall back to "" (unknown) - NEVER hardcode "EUR" - so
        # that when the project currency is unknown we degrade safely (the
        # ``_same_currency`` guard then keeps every bid rather than blending a
        # provably-foreign one). ``getattr`` is used defensively in case the
        # project row is missing or lacks the attribute.
        from app.modules.projects.repository import ProjectRepository

        project = await ProjectRepository(self.session).get_by_id(package.project_id)
        package_currency = (getattr(project, "currency", "") or "").strip().upper() if project is not None else ""

        def _same_currency(bid: TenderBid) -> bool:
            bc = (bid.currency or "").strip().upper()
            # No package currency, or a bid that did not declare one, cannot
            # be proven mismatched - keep it (degrades safely, never blends a
            # *provably* foreign-currency bid).
            return not package_currency or not bc or bc == package_currency

        bids = [b for b in all_bids if _same_currency(b)]
        excluded_off_currency = len(all_bids) - len(bids)

        from app.modules.boq.service import BOQService

        boq_service = BOQService(self.session)
        try:
            boq_data = await boq_service.get_boq_with_positions(package.boq_id)
            ref_positions = boq_data.positions
        except HTTPException:
            ref_positions = []

        # Reference line index → (position_id, code, description, unit, qty, rate, total)
        ref_rows: list[dict] = []
        for pos in ref_positions:
            qty = _to_decimal(pos.quantity)
            rate = _to_decimal(pos.unit_rate)
            total = _to_decimal(pos.total) if pos.total else qty * rate
            ref_rows.append(
                {
                    "position_id": str(pos.id),
                    "line_code": pos.ordinal or "",
                    "description": pos.description or "",
                    "unit": pos.unit or "",
                    "quantity": qty,
                    "rate": rate,
                    "total": total,
                }
            )

        # Index each bid's line items by position_id (last write wins per pid).
        bid_index: dict[str, dict[str, dict]] = {}
        for bid in bids:
            idx: dict[str, dict] = {}
            for item in bid.line_items or []:
                if not isinstance(item, dict):
                    continue
                key = item.get("position_id")
                if key:
                    idx[str(key)] = item
            bid_index[str(bid.id)] = idx

        # Per-bid mean unit rate across the lines the bidder actually quoted -
        # used to impute omitted lines so the leveled total covers full scope.
        bid_mean_rate: dict[str, Decimal] = {}
        for bid in bids:
            quoted = [_to_decimal(it.get("unit_rate", 0)) for it in bid_index[str(bid.id)].values()]
            quoted = [r for r in quoted if r > 0]
            bid_mean_rate[str(bid.id)] = (sum(quoted, Decimal("0")) / Decimal(len(quoted))) if quoted else Decimal("0")

        summaries: dict[str, dict] = {
            str(bid.id): {
                "bid_id": str(bid.id),
                "company_name": bid.company_name,
                "raw_amount": _to_decimal(bid.total_amount),
                "leveled_amount": Decimal("0"),
                "matched_lines": 0,
                "scaled_lines": 0,
                "imputed_lines": 0,
                "currency": bid.currency or "",
            }
            for bid in bids
        }

        rows: list[LevelingMatrixRow] = []
        for ref in ref_rows:
            pid = ref["position_id"]
            ref_qty: Decimal = ref["quantity"]
            cells: list[LevelingMatrixCell] = []
            for bid in bids:
                bid_id = str(bid.id)
                matching = bid_index[bid_id].get(pid)
                if matching is not None:
                    unit_rate = _to_decimal(matching.get("unit_rate", 0))
                    raw_total = _to_decimal(matching.get("total", 0))
                    # When the bidder quoted a rate but not a total (or a total
                    # that disagrees with rate×ref_qty), level to ref_qty so all
                    # bids are compared at the SAME quantity.
                    leveled_total = unit_rate * ref_qty if ref_qty > 0 else raw_total
                    if leveled_total != raw_total and raw_total > 0:
                        cell_status = "scaled"
                        summaries[bid_id]["scaled_lines"] += 1
                    else:
                        cell_status = "matched"
                        summaries[bid_id]["matched_lines"] += 1
                else:
                    # Imputed at the bidder's mean rate × reference quantity.
                    unit_rate = bid_mean_rate[bid_id]
                    leveled_total = unit_rate * ref_qty if ref_qty > 0 else Decimal("0")
                    raw_total = Decimal("0")
                    cell_status = "imputed"
                    summaries[bid_id]["imputed_lines"] += 1
                summaries[bid_id]["leveled_amount"] += leveled_total
                cells.append(
                    LevelingMatrixCell(
                        bid_id=bid_id,
                        company_name=bid.company_name,
                        raw_total=_round2(raw_total),
                        leveled_total=_round2(leveled_total),
                        status=cell_status,
                        unit_rate=_round2_dec(unit_rate),
                    )
                )
            rows.append(
                LevelingMatrixRow(
                    position_id=pid,
                    line_code=ref["line_code"],
                    description=ref["description"],
                    unit=ref["unit"],
                    reference_quantity=float(ref_qty),
                    reference_rate=_round2(ref["rate"]),
                    reference_total=_round2(ref["total"]),
                    cells=cells,
                )
            )

        summary_list = [
            BidLevelingSummary(
                bid_id=s["bid_id"],
                company_name=s["company_name"],
                raw_amount=_round2_dec(s["raw_amount"]),
                leveled_amount=_round2_dec(s["leveled_amount"]),
                matched_lines=s["matched_lines"],
                scaled_lines=s["scaled_lines"],
                imputed_lines=s["imputed_lines"],
                currency=s["currency"],
            )
            for s in summaries.values()
        ]
        return package, rows, summary_list, package_currency, excluded_off_currency

    async def get_leveling_matrix(self, package_id: uuid.UUID) -> LevelingMatrixResponse:
        """Return the full bid-leveling matrix for a package."""
        package, rows, summaries, currency, excluded = await self._build_leveling(package_id)
        return LevelingMatrixResponse(
            package_id=package_id,
            package_name=package.name,
            currency=currency,
            excluded_off_currency=excluded,
            bid_summaries=summaries,
            rows=rows,
        )

    async def level_bids(self, package_id: uuid.UUID) -> LevelBidsResponse:
        """Run bid leveling and return the per-bid rollup."""
        package, rows, summaries, currency, excluded = await self._build_leveling(package_id)
        await _safe_publish(
            "tendering.bids.leveled",
            {"package_id": str(package_id), "bid_count": len(summaries)},
            source_module="oe_tendering",
        )
        return LevelBidsResponse(
            package_id=package_id,
            package_name=package.name,
            currency=currency,
            excluded_off_currency=excluded,
            bid_count=len(summaries),
            reference_line_count=len(rows),
            bid_summaries=summaries,
        )

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

        def _norm_ccy(value: str | None) -> str:
            return (value or "").strip().upper()

        # Statistical aggregates (spread / outliers) are only meaningful
        # within a single currency - summing or comparing totals across
        # currencies produces nonsense. Scope numeric stats to the dominant
        # currency cohort (the currency carried by the most bids).
        ccy_counts: dict[str, int] = {}
        for b in bids:
            ccy_counts[_norm_ccy(b.currency)] = ccy_counts.get(_norm_ccy(b.currency), 0) + 1
        dominant_ccy = max(ccy_counts.items(), key=lambda kv: (kv[1], kv[0]))[0]

        # Vendor rollup - Decimal sums, and a vendor that bid in more than
        # one currency is reported with a blank currency rather than a
        # silently-mixed total.
        vendor_map: dict[str, dict] = {}
        for bid in bids:
            company = (bid.company_name or "").strip() or "(unnamed)"
            amount = _to_decimal(bid.total_amount)
            ccy = _norm_ccy(bid.currency)
            entry = vendor_map.setdefault(
                company,
                {
                    "company_name": company,
                    "total": Decimal("0"),
                    "currencies": set(),
                    "bid_count": 0,
                },
            )
            entry["total"] += amount
            entry["currencies"].add(ccy)
            entry["bid_count"] += 1

        vendors = [
            BidVendorEntry(
                company_name=str(v["company_name"]),
                total=_round2(v["total"]),
                currency=(next(iter(v["currencies"])) if len(v["currencies"]) == 1 else ""),
                bid_count=int(v["bid_count"]),
            )
            for v in sorted(
                vendor_map.values(),
                key=lambda e: -float(e["total"]),
            )
        ]

        # Cohort restricted to the dominant currency for spread/outliers.
        cohort = [(b, _to_decimal(b.total_amount)) for b in bids if _norm_ccy(b.currency) == dominant_ccy]
        totals: list[Decimal] = [t for _, t in cohort]
        sorted_totals = sorted(totals)

        def _pct(values: list[Decimal], p: float) -> Decimal:
            if not values:
                return Decimal("0")
            idx = max(0, min(len(values) - 1, int(round((len(values) - 1) * p))))
            return values[idx]

        p25 = _pct(sorted_totals, 0.25)
        p50 = _pct(sorted_totals, 0.50)
        p75 = _pct(sorted_totals, 0.75)
        n = len(totals)
        mean = sum(totals, Decimal("0")) / Decimal(n)
        variance = sum(((t - mean) ** 2 for t in totals), Decimal("0")) / Decimal(n)
        std = variance.sqrt()

        spread = BidSpread(
            min=_round2(sorted_totals[0]),
            max=_round2(sorted_totals[-1]),
            p25=_round2(p25),
            p50=_round2(p50),
            p75=_round2(p75),
            mean=_round2(mean),
            std=_round2(std),
            sample_size=n,
        )

        # Outliers (IQR rule) - also confined to the dominant-currency cohort.
        iqr = p75 - p25
        low_bound = p25 - Decimal("1.5") * iqr
        high_bound = p75 + Decimal("1.5") * iqr
        outliers: list[BidOutlierEntry] = []
        if n >= 4 and iqr > 0:
            for bid, total in cohort:
                if total < low_bound or total > high_bound:
                    reason = "too_low" if total < low_bound else "too_high"
                    outliers.append(
                        BidOutlierEntry(
                            bid_id=bid.id,
                            company_name=(bid.company_name or "").strip() or "(unnamed)",
                            total=_round2(total),
                            reason=reason,
                        )
                    )

        return BidAnalysisResponse(vendors=vendors, outliers=outliers, spread=spread)
