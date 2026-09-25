# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tendering service - business logic for tender packages and bids.

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

from app.core.events import event_bus, publish_after_commit
from app.core.json_merge import merge_metadata

_logger_ev = __import__("logging").getLogger(__name__ + ".events")

# ── Lifecycle state machine ──────────────────────────────────────────────────
# Package status transitions. ``closed`` is terminal; ``awarded`` may still be
# closed for archival but never re-opened. Anything not listed is rejected.
# ``evaluating -> awarded`` is the lifecycle step, but only ``apply_winner``
# takes it: ``update_package`` refuses a PATCH to ``awarded``.
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

# Package states in which a bid's figures are final. ``apply_winner`` copies
# the winning bid's rates into the BOQ and records the award against them, and
# a closed package has ended its tender either way; repricing any bid after
# that would leave the award, the bill and the comparison describing figures
# the bid no longer carries.
_BID_FIGURES_FROZEN_STATES: frozenset[str] = frozenset({"awarded", "closed"})

# The bid fields that carry its money.
_BID_MONEY_FIELDS: tuple[str, ...] = ("total_amount", "currency", "line_items")

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


def _positions_in_scope(positions: list, metadata: dict | None) -> list:
    """Narrow a package's BOQ positions to the lines it was raised over.

    A tender package can cover part of a bill: ``create_from_boq`` freezes the
    chosen sections into ``line_item_template``, and the demo installer records
    the same thing as a plain ``scope_position_ids`` list. Both comparison
    screens read the package's whole BOQ, so without this narrowing the lines
    nobody was asked to price still land on the reference side, where every
    bidder reads as having omitted them. A package over a quarter of a bill
    then levels a bid of 812,400 to roughly four times that, because each
    out-of-scope line is imputed at the bidder's own mean rate, and compares it
    against a budget four times its own.

    Metadata that declares no scope means the package covers everything its
    BOQ holds, which is what every package created before this carried. A scope
    that matches nothing in the BOQ is stale metadata rather than an empty
    package, so it is ignored too: an empty matrix would be a worse answer than
    a wide one.

    Args:
        positions: BOQ positions as loaded for the package.
        metadata: The package's metadata mapping, possibly empty.

    Returns:
        The positions in scope, in their original order.
    """
    scope = _scope_position_ids(metadata)
    if not scope:
        return positions
    narrowed = [p for p in positions if str(p.id) in scope]
    return narrowed or positions


def _scope_position_ids(metadata: dict | None) -> set[str]:
    """The position ids a package declares, from either shape the metadata takes.

    Empty means the package declares no scope, which every package created
    before the scope was recorded carries and which means the whole bill.
    """
    meta = metadata or {}
    scope: set[str] = set()

    raw = meta.get("scope_position_ids")
    if isinstance(raw, list):
        scope.update(str(v) for v in raw if v)

    template = meta.get("line_item_template")
    if isinstance(template, list):
        for item in template:
            if isinstance(item, dict) and item.get("position_id"):
                scope.add(str(item["position_id"]))

    return scope


def _scope_sections(positions: list, metadata: dict | None) -> dict:
    """Describe a package's scope in the bill's own terms.

    Answers the question the comparison screens compute silently: which sections
    was this package raised over, and how much of the bill is that. Kept pure so
    it can be read and tested without a database, the way the scope filter above
    it is.

    ``create_from_boq`` records the chosen sections as ``source_section_ids``.
    Packages that predate that, and the ones the demo installer writes, record
    only a flat position list, so the sections are derived by walking each
    in-scope position up to its top-level ancestor. That gives the same answer
    whenever the scope was built from whole sections, and an honest
    approximation when it was not, which ``sections_recorded`` reports.

    Returns:
        A mapping with ``sections_recorded``, ``covers_whole_bill``,
        ``included_position_count`` and ``sections``, each section carrying its
        id, ordinal, description and how many in-scope positions sit under it.
    """
    by_id = {str(p.id): p for p in positions}
    parent_of = {str(p.id): (str(p.parent_id) if getattr(p, "parent_id", None) else None) for p in positions}

    scope = _scope_position_ids(metadata)
    in_scope = {pid for pid in scope if pid in by_id}
    counted = in_scope or set(by_id)

    def top_level(pid: str) -> str:
        seen: set[str] = set()
        while parent_of.get(pid) and pid not in seen:
            seen.add(pid)
            pid = parent_of[pid] or pid
        return pid

    per_section: dict[str, int] = {}
    for pid in counted:
        root = top_level(pid)
        per_section[root] = per_section.get(root, 0) + 1

    meta = metadata if isinstance(metadata, dict) else {}
    recorded = meta.get("source_section_ids")
    sections_recorded = isinstance(recorded, list) and any(str(v) in by_id for v in recorded)
    if sections_recorded:
        section_ids = [str(v) for v in recorded if str(v) in by_id]  # type: ignore[union-attr]
    else:
        section_ids = sorted(per_section, key=lambda pid: str(getattr(by_id[pid], "ordinal", "") or ""))

    return {
        "sections_recorded": sections_recorded,
        "covers_whole_bill": not in_scope or len(in_scope) == len(positions),
        "included_position_count": len(counted),
        "sections": [
            {
                "id": by_id[sid].id,
                "ordinal": str(getattr(by_id[sid], "ordinal", "") or ""),
                "description": str(getattr(by_id[sid], "description", "") or ""),
                "position_count": per_section.get(sid, 0),
            }
            for sid in section_ids
            if sid in by_id
        ],
    }


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
    AwardRecordNoteCreate,
    AwardRecordResponse,
    BidComparisonResponse,
    BidComparisonRow,
    BidCreate,
    BidLevelingSummary,
    BidUpdate,
    CreatePackageFromBOQData,
    DistributeRequest,
    DistributeResponse,
    DistributeResultEntry,
    LevelBidsResponse,
    LevelingMatrixCell,
    LevelingMatrixResponse,
    LevelingMatrixRow,
    PackageCreate,
    PackageScopeResponse,
    PackageUpdate,
    RecipientCreate,
    RecipientResponse,
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

    async def create_package_from_boq(
        self,
        data: CreatePackageFromBOQData,
        *,
        actor_id: str | None = None,
    ) -> TenderPackage:
        """Create a tender package pre-seeded from selected BOQ sections.

        Loads the BOQ the same way ``compare_bids`` and ``_build_leveling`` do,
        identifies top-level sections (positions whose ``parent_id`` is ``None``
        and whose ``unit`` is empty or ``"section"``), filters to the requested
        ``section_ids`` (or takes all sections when the list is empty), then
        recursively gathers every descendant. The resulting positions are stored
        as a compact line-item template in ``metadata_`` so bids can be
        pre-seeded without an additional BOQ read.

        Currency is inferred from the linked project via the same project
        repository path used in ``apply_winner`` and ``_build_leveling``. When
        not available it is omitted from the metadata rather than defaulted to a
        wrong value.

        Raises 400 if ``boq_id`` references a BOQ that cannot be read.
        """
        # Load BOQ positions the same way existing comparison/leveling code does.
        from app.modules.boq.service import BOQService

        boq_service = BOQService(self.session)
        try:
            boq_data = await boq_service.get_boq_with_positions(data.boq_id)
            all_positions = boq_data.positions
        except HTTPException as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Could not load BOQ {data.boq_id}: {exc.detail}",
            ) from exc

        # Tenant guard: the BOQ must belong to the same project the caller was
        # verified to own. The router checks ownership of ``data.project_id``
        # only, not the BOQ, so without this a caller could pair their own
        # ``project_id`` with another tenant's ``boq_id`` and read that BOQ's
        # full line-item template back out of the package metadata. Return 404
        # (not 403) so we don't disclose the existence of BOQs in other
        # tenants - matches the IDOR-404 convention used elsewhere.
        if boq_data.project_id != data.project_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Could not load BOQ {data.boq_id}: not found",
            )

        # Index positions by id for fast descendant lookup.
        pos_by_id: dict[uuid.UUID, object] = {p.id: p for p in all_positions}

        # Identify top-level sections: parent_id is None and unit is empty or "section".
        def _is_section(pos: object) -> bool:
            parent = getattr(pos, "parent_id", None)
            unit = (getattr(pos, "unit", "") or "").strip().lower()
            return parent is None and (unit == "" or unit == "section")

        section_positions = [p for p in all_positions if _is_section(p)]

        # Filter to the requested section_ids when the caller specified any.
        if data.section_ids:
            requested = set(data.section_ids)
            section_positions = [p for p in section_positions if p.id in requested]

        # Build set of chosen section IDs for the metadata record.
        chosen_section_ids = [str(p.id) for p in section_positions]

        # Recursively collect all descendants of the chosen sections.
        # Build a parent->children index first so we traverse the tree once
        # at O(n) rather than O(n*depth) with repeated linear scans.
        children_of: dict[uuid.UUID | None, list[object]] = {}
        for p in all_positions:
            parent_key = getattr(p, "parent_id", None)
            children_of.setdefault(parent_key, []).append(p)

        included_ids: set[uuid.UUID] = set()

        def _collect(pos_id: uuid.UUID) -> None:
            included_ids.add(pos_id)
            for child in children_of.get(pos_id, []):
                _collect(child.id)

        for sec in section_positions:
            _collect(sec.id)

        included = [pos_by_id[pid] for pid in included_ids if pid in pos_by_id]

        # Build the compact line-item template (money as Decimal-as-string).
        def _money_str(raw: object) -> str:
            """Return a Decimal-as-string representation of a money value."""
            try:
                d = Decimal(str(raw)) if raw is not None else Decimal("0")
                return format(d if d.is_finite() else Decimal("0"), "f")
            except (InvalidOperation, ValueError, TypeError):
                return "0"

        line_item_template = [
            {
                "position_id": str(p.id),
                "description": getattr(p, "description", "") or "",
                "unit": getattr(p, "unit", "") or "",
                "quantity": _money_str(getattr(p, "quantity", "0")),
                "unit_rate": _money_str(getattr(p, "unit_rate", "0")),
                "total": _money_str(getattr(p, "total", "0")),
            }
            for p in included
        ]

        # Infer project currency the same way apply_winner and _build_leveling do.
        from app.modules.projects.repository import ProjectRepository

        project = await ProjectRepository(self.session).get_by_id(data.project_id)
        project_currency = (getattr(project, "currency", "") or "").strip().upper() if project is not None else ""

        # Build the metadata payload.
        meta: dict = {
            **data.metadata,
            "source_boq_id": str(data.boq_id),
            "source_section_ids": chosen_section_ids,
            "included_position_count": len(included),
            "line_item_template": line_item_template,
        }
        if project_currency:
            meta["currency"] = project_currency

        package = TenderPackage(
            project_id=data.project_id,
            boq_id=data.boq_id,
            name=data.package_name,
            description=data.package_description,
            status="draft",
            deadline=data.deadline or None,
            metadata_=meta,
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
                "source": "from_boq",
                "included_position_count": len(included),
            },
            source_module="oe_tendering",
        )

        logger.info(
            "Tender package created from BOQ: %s (sections=%s positions=%s by=%s)",
            package.name,
            len(chosen_section_ids),
            len(included),
            actor_id,
        )
        return package

    async def package_scope(self, package_id: uuid.UUID) -> "PackageScopeResponse":
        """Report which part of the bill a package was raised over.

        ``create_from_boq`` records the chosen sections as ``source_section_ids``
        and has never had a reader, so a package covering one trade looked on
        screen exactly like a package covering the whole bill. Comparison and
        levelling already narrow to that scope, which means the number a bidder
        is measured against depends on a fact the reader could not see.

        Packages that predate the metadata, and the ones the demo installer
        writes, record the scope as a flat position list instead. For those the
        sections are derived by walking each in-scope position up to its
        top-level ancestor, and ``sections_recorded`` says so.

        Raises 404 when the package does not exist, and answers with an empty
        scope rather than an error when its BOQ cannot be read, because a bill
        that has since been deleted is not a reason to refuse the question.
        """
        from app.modules.tendering.schemas import PackageScopeSection

        package = await self.get_package(package_id)
        answer = PackageScopeResponse(package_id=package_id, boq_id=package.boq_id)
        if package.boq_id is None:
            answer.covers_whole_bill = False
            return answer

        from app.modules.boq.service import BOQService

        try:
            boq_data = await BOQService(self.session).get_boq_with_positions(package.boq_id)
        except HTTPException:
            logger.info("Package %s names a BOQ that cannot be read", package_id)
            return answer

        positions = list(boq_data.positions)
        answer.boq_name = getattr(boq_data, "name", "") or ""
        answer.boq_position_count = len(positions)

        described = _scope_sections(positions, package.metadata_)
        answer.sections_recorded = described["sections_recorded"]
        answer.covers_whole_bill = described["covers_whole_bill"]
        answer.included_position_count = described["included_position_count"]
        answer.sections = [PackageScopeSection(**section) for section in described["sections"]]
        return answer

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

        # Map schema field 'metadata' to model column 'metadata_'. Merge a
        # partial metadata patch into the existing column instead of replacing
        # it wholesale - a PATCH that touches one key must not wipe every other
        # key already stored (lifecycle stamps, evaluation notes, etc.).
        if "metadata" in fields:
            incoming_meta = fields.pop("metadata")
            if isinstance(incoming_meta, dict):
                fields["metadata_"] = merge_metadata(package.metadata_, incoming_meta)
            else:
                fields["metadata_"] = incoming_meta

        # Validate status transition before persisting anything.
        new_status = fields.get("status")
        if new_status == "awarded" and package.status in _AWARDABLE_PACKAGE_STATES:
            # Awarding is a decision with consequences, not a label: apply_winner
            # names the winning bid, writes its rates into the BOQ, rejects the
            # other bids and announces the award. A PATCH would do none of that
            # and leave a package that reads as awarded with no winner, which
            # apply_winner then refuses for good. It also needs tendering.award,
            # which this route does not ask for.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "A package is awarded by applying the winning bid, which records the winner "
                    "and writes its rates into the BOQ. Use apply-winner instead of changing the status."
                ),
            )
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
        """Create a new bid for a package.

        Raises:
            HTTPException 404: Package not found.
            HTTPException 409: The package is awarded or closed; its tender is
                over and a bid added now would join a decided comparison.
        """
        package = await self.get_package(package_id)
        if package.status in _BID_FIGURES_FROZEN_STATES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Package is '{package.status}' and accepts no new bids",
            )

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
        """Update bid fields.

        Raises:
            HTTPException 404: Bid not found.
            HTTPException 409: The package is awarded or closed and the patch
                would change the bid's total, currency or line items.
        """
        bid = await self.get_bid(bid_id)

        fields = data.model_dump(exclude_unset=True)

        # Map schema field 'metadata' to model column 'metadata_'. Merge a
        # partial metadata patch into the existing column instead of replacing
        # it wholesale, so a PATCH touching one key keeps the rest intact.
        if "metadata" in fields:
            incoming_meta = fields.pop("metadata")
            if isinstance(incoming_meta, dict):
                fields["metadata_"] = merge_metadata(bid.metadata_, incoming_meta)
            else:
                fields["metadata_"] = incoming_meta

        # Serialize line_items if present - JSON mode coerces Decimal to
        # string so the persisted JSON value matches the wire contract. The
        # dump above has already turned each item into a dict that still holds
        # Decimal values, so dump the models themselves, exactly as create_bid
        # does; otherwise an unchanged line never equals its stored form.
        if "line_items" in fields and data.line_items is not None:
            fields["line_items"] = [item.model_dump(mode="json") for item in data.line_items]

        # Once the package is decided the bid's money is final. Compared in the
        # stored form, so a client that sends the bid back unchanged is not
        # refused, and fields without money (notes, contact) stay editable.
        changed_money = [f for f in _BID_MONEY_FIELDS if f in fields and fields[f] != getattr(bid, f, None)]
        if changed_money:
            package = await self.get_package(bid.package_id)
            if package.status in _BID_FIGURES_FROZEN_STATES:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Bid is locked - package is '{package.status}'. "
                        "Its total, currency and line items cannot change after the award or close."
                    ),
                )

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
            budget_positions = _positions_in_scope(boq_data.positions, package.metadata_)
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

        # After commit, not now: the subscribers (the purchase order and the
        # contract draft) open their own sessions, and an award that rolls
        # back must not leave either behind.
        publish_after_commit(
            self.session,
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

    # ── Distribution to subcontractors ─────────────────────────────────────
    # The recipient list lives in the package ``metadata_`` JSON store under
    # ``recipients`` (the same extensible-per-package pattern used for addenda),
    # so distribution needs no new table or migration. Each recipient records
    # who it went to and the per-recipient send state/timestamp. Distribution
    # reuses the platform email sender (``app.core.email``); when SMTP is not
    # configured the sender falls back to the console backend and never raises,
    # so the action degrades to a clear "sent via console" status on a dev
    # checkout instead of crashing. Each entry shape:
    #   {id, company_name, email, subcontractor_id, status, sent_at,
    #    last_error, created_at}

    @staticmethod
    def _read_recipients(package: TenderPackage) -> list[dict]:
        raw = (package.metadata_ or {}).get("recipients")
        return [r for r in raw if isinstance(r, dict)] if isinstance(raw, list) else []

    @staticmethod
    def _recipient_to_response(raw: dict) -> RecipientResponse:
        return RecipientResponse(
            id=str(raw.get("id", "")),
            company_name=str(raw.get("company_name", "")),
            email=str(raw.get("email", "")),
            subcontractor_id=raw.get("subcontractor_id"),
            status=str(raw.get("status", "pending")),
            sent_at=raw.get("sent_at"),
            last_error=raw.get("last_error"),
            created_at=str(raw.get("created_at", "")),
        )

    async def list_recipients(self, package_id: uuid.UUID) -> list[RecipientResponse]:
        """List a package's distribution recipients."""
        package = await self.get_package(package_id)
        return [self._recipient_to_response(r) for r in self._read_recipients(package)]

    async def add_recipient(self, package_id: uuid.UUID, data: RecipientCreate) -> RecipientResponse:
        """Add a subcontractor to a package's distribution list.

        De-duplicates on a case-insensitive email match so the same firm is
        not invited twice; returns the existing entry if already present.
        """
        package = await self.get_package(package_id)
        recipients = self._read_recipients(package)
        email_norm = data.email.strip().lower()
        for r in recipients:
            if str(r.get("email", "")).strip().lower() == email_norm:
                return self._recipient_to_response(r)
        entry = {
            "id": str(uuid.uuid4()),
            "company_name": data.company_name,
            "email": data.email,
            "subcontractor_id": data.subcontractor_id,
            "status": "pending",
            "sent_at": None,
            "last_error": None,
            "created_at": datetime.now(UTC).isoformat(),
        }
        meta = dict(package.metadata_ or {})
        meta["recipients"] = [*recipients, entry]
        await self.repo.update_package_fields(package_id, metadata_=meta)
        logger.info("Tender recipient added: package=%s company=%s", package_id, data.company_name)
        return self._recipient_to_response(entry)

    async def remove_recipient(self, package_id: uuid.UUID, recipient_id: str) -> None:
        """Remove a recipient from a package's distribution list."""
        package = await self.get_package(package_id)
        recipients = self._read_recipients(package)
        remaining = [r for r in recipients if str(r.get("id")) != str(recipient_id)]
        if len(remaining) == len(recipients):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recipient not found")
        meta = dict(package.metadata_ or {})
        meta["recipients"] = remaining
        await self.repo.update_package_fields(package_id, metadata_=meta)
        logger.info("Tender recipient removed: package=%s recipient=%s", package_id, recipient_id)

    async def distribute_package(
        self,
        package_id: uuid.UUID,
        data: DistributeRequest,
        *,
        actor_id: str | None = None,
    ) -> DistributeResponse:
        """Email the tender package to its recipients and record send state.

        Reuses the platform email sender (``app.core.email.get_email_service``).
        Each recipient gets one ``EmailMessage`` so the per-recipient delivery
        status stays independent; we stamp ``status``/``sent_at`` (or
        ``last_error``) back onto the recipient entry in package metadata.

        Graceful no-SMTP behaviour: ``EmailService.send`` never raises and, when
        ``EMAIL_BACKEND`` is the default ``console`` (or ``smtp`` without a
        configured ``SMTP_HOST``), it logs the message and returns ``ok=True``
        via the console backend. The response reports the resolved ``backend``
        and ``smtp_configured`` so the UI can tell the operator whether real
        mail went out. A genuinely failed delivery (smtp configured but the
        server refused) is recorded as ``failed`` without aborting the batch.

        The package is moved to ``issued`` on the first successful send if it is
        still a draft, mirroring the existing lifecycle (draft -> issued).
        """
        from app.config import get_settings
        from app.core.email import EmailMessage, get_email_service
        from app.core.email.service import email_delivery_enabled

        package = await self.get_package(package_id)
        recipients = self._read_recipients(package)
        if not recipients:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No recipients on the distribution list; add subcontractors before distributing",
            )

        requested = {str(rid) for rid in data.recipient_ids}

        settings = get_settings()
        smtp_configured = email_delivery_enabled(settings)
        service = get_email_service()
        backend_name = service.backend_name

        # Build a stable link back to this tender for the email CTA. Falls back
        # to the resolved frontend URL (which itself falls back to the first
        # CORS origin), so a dev install still produces a working-looking link.
        base_url = (settings.resolved_frontend_url or "").rstrip("/")
        action_url = f"{base_url}/tendering?package={package_id}" if base_url else ""

        # Resolve a reporting currency / project name once (tenant-correct:
        # the project was already verified as accessible by the router).
        from app.modules.projects.repository import ProjectRepository

        project = await ProjectRepository(self.session).get_by_id(package.project_id)
        project_name = (getattr(project, "name", "") or "") if project is not None else ""

        results: list[DistributeResultEntry] = []
        sent_count = 0
        failed_count = 0
        skipped_count = 0
        any_sent = False

        # Work on a copy we can mutate, keyed by id, preserving order.
        by_id = {str(r.get("id")): dict(r) for r in recipients}

        for rid, r in by_id.items():
            if requested and rid not in requested:
                continue
            if r.get("status") == "sent" and not data.resend:
                skipped_count += 1
                results.append(
                    DistributeResultEntry(
                        recipient_id=rid,
                        company_name=str(r.get("company_name", "")),
                        email=str(r.get("email", "")),
                        status="skipped",
                        detail="already sent (use resend to send again)",
                    )
                )
                continue

            to_email = str(r.get("email", "")).strip()
            company = str(r.get("company_name", "")) or "Sir or Madam"
            if not to_email:
                failed_count += 1
                r["status"] = "failed"
                r["last_error"] = "missing email"
                results.append(
                    DistributeResultEntry(
                        recipient_id=rid,
                        company_name=company,
                        email="",
                        status="failed",
                        detail="missing email",
                    )
                )
                continue

            subject = f"Invitation to tender: {package.name}"
            html_body = self._build_distribution_html(
                company_name=company,
                package=package,
                project_name=project_name,
                action_url=action_url,
                custom_message=data.message,
            )

            try:
                result = await service.send(
                    EmailMessage(
                        to=to_email,
                        subject=subject,
                        html_body=html_body,
                        tags=["tendering", "distribution", str(package_id)],
                    ),
                )
                ok = bool(getattr(result, "ok", False))
                reason = getattr(result, "reason", "") or ""
            except Exception as exc:  # noqa: BLE001 - degrade, never crash distribution
                ok = False
                reason = f"send crashed: {type(exc).__name__}"
                logger.warning("Tender distribution send crashed: package=%s to=%s", package_id, to_email)

            now = datetime.now(UTC).isoformat()
            if ok:
                sent_count += 1
                any_sent = True
                r["status"] = "sent"
                r["sent_at"] = now
                r["last_error"] = None
                results.append(
                    DistributeResultEntry(
                        recipient_id=rid,
                        company_name=company,
                        email=to_email,
                        status="sent",
                        detail=reason or "sent",
                    )
                )
            else:
                failed_count += 1
                r["status"] = "failed"
                r["last_error"] = reason
                results.append(
                    DistributeResultEntry(
                        recipient_id=rid,
                        company_name=company,
                        email=to_email,
                        status="failed",
                        detail=reason or "delivery failed",
                    )
                )

        # Persist the updated recipient states and a distribution audit stamp.
        meta = dict(package.metadata_ or {})
        meta["recipients"] = list(by_id.values())
        meta["last_distributed_at"] = datetime.now(UTC).isoformat()
        if actor_id:
            meta["last_distributed_by"] = str(actor_id)

        new_status = package.status
        if any_sent and package.status == "draft":
            new_status = "issued"
            meta.setdefault("issued_at", datetime.now(UTC).isoformat())

        if new_status != package.status:
            await self.repo.update_package_fields(package_id, status=new_status, metadata_=meta)
        else:
            await self.repo.update_package_fields(package_id, metadata_=meta)

        await _safe_publish(
            "tendering.package.distributed",
            {
                "package_id": str(package_id),
                "sent_count": sent_count,
                "failed_count": failed_count,
                "skipped_count": skipped_count,
                "backend": backend_name,
                "distributed_by": str(actor_id) if actor_id else None,
            },
            source_module="oe_tendering",
        )

        logger.info(
            "Tender package distributed: package=%s sent=%s failed=%s skipped=%s backend=%s by=%s",
            package_id,
            sent_count,
            failed_count,
            skipped_count,
            backend_name,
            actor_id,
        )

        return DistributeResponse(
            package_id=package_id,
            package_name=package.name,
            backend=backend_name,
            smtp_configured=smtp_configured,
            sent_count=sent_count,
            failed_count=failed_count,
            skipped_count=skipped_count,
            results=results,
        )

    @staticmethod
    def _build_distribution_html(
        *,
        company_name: str,
        package: TenderPackage,
        project_name: str,
        action_url: str,
        custom_message: str | None,
    ) -> str:
        """Render the invitation-to-tender email body via the shared shell."""
        import html as _html

        from app.core.email import wrap

        deadline = package.deadline or ""
        desc = package.description or ""
        parts = [f"<p>Dear {_html.escape(company_name)},</p>"]
        proj = f" for <strong>{_html.escape(project_name)}</strong>" if project_name else ""
        parts.append(
            f"<p>You are invited to submit a bid for the tender package "
            f"<strong>{_html.escape(package.name)}</strong>{proj}.</p>"
        )
        if desc:
            parts.append(
                f"<blockquote style='border-left:3px solid #0071e3; padding-left:12px; "
                f"margin:12px 0; color:#1d1d1f;'>{_html.escape(desc)}</blockquote>"
            )
        if deadline:
            parts.append(f"<p><strong>Submission deadline:</strong> {_html.escape(deadline)}</p>")
        if custom_message:
            parts.append(
                f"<blockquote style='border-left:3px solid #86868b; padding-left:12px; "
                f"margin:12px 0; color:#444;'>{_html.escape(custom_message)}</blockquote>"
            )
        parts.append(
            "<p style='font-size:13px; color:#6e6e73;'>Please review the package details and respond "
            "with your offer before the deadline above.</p>"
        )
        body = "".join(parts)
        if action_url:
            return wrap("Invitation to Tender", body, action_url, "View tender package")
        return wrap("Invitation to Tender", body)

    # ── Decision documents (award / rejection PDFs) ─────────────────────────

    async def build_award_letter_pdf(self, package_id: uuid.UUID, bid_id: uuid.UUID) -> tuple[bytes, str]:
        """Generate a PDF letter of award for a winning bid.

        Returns ``(pdf_bytes, filename)``. Tenant scoping is enforced at the
        router (project access on the package) plus the bid-belongs-to-package
        check here. The winning bid is normally the package's recorded
        ``awarded_bid_id`` and/or a bid in ``accepted`` status, but we render
        for any bid the caller selects so an award letter can be produced for
        the recommended winner before the formal award is applied.
        """
        from app.modules.tendering.pdf_documents import generate_award_letter_pdf

        package = await self.get_package(package_id)
        bid = await self.get_bid(bid_id)
        if bid.package_id != package_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Bid does not belong to this package",
            )

        project_name, _currency = await self._project_name_and_currency(package)
        meta = package.metadata_ or {}
        pdf = generate_award_letter_pdf(
            package_name=package.name,
            package_ref=str(package_id)[:8],
            project_name=project_name,
            company_name=bid.company_name,
            contact_email=bid.contact_email or "",
            awarded_amount=bid.total_amount or "0",
            currency=bid.currency or "",
            awarded_at=meta.get("awarded_at"),
            awarded_by_name=meta.get("awarded_by_name"),
            notes=bid.notes or None,
        )
        filename = f"award_letter_{self._slug(package.name)}_{self._slug(bid.company_name)}.pdf"
        return pdf, filename

    async def build_rejection_letter_pdf(self, package_id: uuid.UUID, bid_id: uuid.UUID) -> tuple[bytes, str]:
        """Generate a PDF rejection notice for an unsuccessful bid.

        Returns ``(pdf_bytes, filename)``. Where the package has a recorded
        winner, the awarded sum is included for transparency (same currency
        only - never blend currencies).
        """
        from app.modules.tendering.pdf_documents import generate_rejection_letter_pdf

        package = await self.get_package(package_id)
        bid = await self.get_bid(bid_id)
        if bid.package_id != package_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Bid does not belong to this package",
            )

        project_name, _currency = await self._project_name_and_currency(package)
        meta = package.metadata_ or {}

        # Awarded sum for transparency - only when we can resolve the winning
        # bid and it shares the rejected bid's currency (no cross-currency mix).
        winning_amount: str | None = None
        awarded_bid_id = meta.get("awarded_bid_id")
        if awarded_bid_id:
            try:
                winner = await self.repo.get_bid_by_id(uuid.UUID(str(awarded_bid_id)))
            except (ValueError, AttributeError):
                winner = None
            if (
                winner is not None
                and winner.package_id == package_id
                and (winner.currency or "").strip().upper() == (bid.currency or "").strip().upper()
            ):
                winning_amount = winner.total_amount or None

        pdf = generate_rejection_letter_pdf(
            package_name=package.name,
            package_ref=str(package_id)[:8],
            project_name=project_name,
            company_name=bid.company_name,
            contact_email=bid.contact_email or "",
            bid_amount=bid.total_amount or None,
            currency=bid.currency or "",
            winning_amount=winning_amount,
            rejected_at=meta.get("awarded_at"),
            signed_by_name=meta.get("awarded_by_name"),
            reason=(bid.notes or None),
        )
        filename = f"rejection_notice_{self._slug(package.name)}_{self._slug(bid.company_name)}.pdf"
        return pdf, filename

    async def _project_name_and_currency(self, package: TenderPackage) -> tuple[str, str]:
        """Resolve (project_name, project_currency) for a package's project."""
        from app.modules.projects.repository import ProjectRepository

        project = await ProjectRepository(self.session).get_by_id(package.project_id)
        if project is None:
            return "", ""
        name = getattr(project, "name", "") or ""
        currency = (getattr(project, "currency", "") or "").strip().upper()
        return name, currency

    @staticmethod
    def _slug(value: str) -> str:
        """Filesystem-safe slug for a download filename."""
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in (value or "").strip())
        return (safe or "tender")[:40]

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

    # ── Award record (Vergabevermerk) ──────────────────────────────────────
    # The written record of an award procedure that German public procurement
    # asks a contracting authority to keep as the procedure runs (VOB/A section
    # 20 below the EU threshold, VgV section 8 above it). Everything about the
    # procedure is assembled on read from the package, its bids, its scope and
    # its levelling, so the record cannot drift away from the procedure it
    # describes. The statements only a person can make live beside those facts
    # in the package ``metadata_`` store, and nothing is written there until
    # somebody writes one: a package that has nothing to do with any of this is
    # untouched.

    async def award_record(self, package_id: uuid.UUID) -> AwardRecordResponse:
        """Assemble the award record for a package at whatever stage it stands.

        Readable from the first day rather than only once an award exists. The
        estimated value is summed over the live bill positions the package was
        raised over, the same narrowing ``compare_bids`` and levelling apply, so
        it is the value the bidders were actually measured against and not the
        frozen line-item template written on the day the package was created.

        A bill that can no longer be read leaves the value and the scope
        unstated, which the record then names as a gap, rather than refusing the
        whole question.
        """
        from app.modules.tendering.award_record import build_award_record

        package = await self.get_package(package_id)
        bids = await self.repo.list_bids_for_package(package_id)
        project_name, currency = await self._project_name_and_currency(package)

        described: dict = {}
        boq_name = ""
        budget_total = Decimal("0")
        if package.boq_id is not None:
            from app.modules.boq.service import BOQService

            try:
                boq_data = await BOQService(self.session).get_boq_with_positions(package.boq_id)
            except HTTPException:
                logger.info("Package %s names a BOQ that cannot be read", package_id)
            else:
                positions = list(boq_data.positions)
                boq_name = getattr(boq_data, "name", "") or ""
                described = _scope_sections(positions, package.metadata_)
                described["boq_position_count"] = len(positions)
                for pos in _positions_in_scope(positions, package.metadata_):
                    qty = _to_decimal(pos.quantity)
                    rate = _to_decimal(pos.unit_rate)
                    budget_total += _to_decimal(pos.total) if pos.total else qty * rate

        # The evaluation section states the levelled figures rather than the raw
        # sums, because those are what the bids were actually compared on. Only
        # run it when there is something to level.
        summaries: list[BidLevelingSummary] = []
        excluded_off_currency = 0
        if bids:
            _pkg, _rows, summaries, _currency, excluded_off_currency = await self._build_leveling(package_id)

        assembled = build_award_record(
            package_name=package.name,
            status=package.status,
            metadata=package.metadata_,
            bids=bids,
            package_description=package.description or "",
            deadline=package.deadline,
            project_name=project_name,
            currency=currency,
            boq_name=boq_name,
            scope=described,
            budget_total=budget_total,
            leveling=summaries,
            excluded_off_currency=excluded_off_currency,
        )
        return AwardRecordResponse(
            package_id=package_id,
            package_name=package.name,
            project_name=project_name,
            **assembled,
        )

    async def record_award_note(
        self,
        package_id: uuid.UUID,
        data: AwardRecordNoteCreate,
        *,
        actor_id: str | None = None,
    ) -> AwardRecordResponse:
        """Write one human statement into a package's award record.

        Statements are append-only, the way addenda are: writing a section again
        supersedes the earlier statement and leaves it readable, so the record
        still shows what was written when it was written.
        """
        from app.modules.tendering.award_record import REASONING_SECTIONS, append_note

        package = await self.get_package(package_id)
        if data.section not in REASONING_SECTIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(f"Unknown award record section {data.section!r}; expected one of {sorted(REASONING_SECTIONS)}"),
            )
        if not data.text.strip() and not data.value.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An award record statement needs either a text or a chosen value",
            )

        meta = append_note(
            package.metadata_,
            note_id=str(uuid.uuid4()),
            section=data.section,
            text=data.text,
            value=data.value,
            recorded_at=datetime.now(UTC).isoformat(),
            recorded_by=str(actor_id) if actor_id else None,
        )
        await self.repo.update_package_fields(package_id, metadata_=meta)

        await _safe_publish(
            "tendering.award_record.recorded",
            {
                "package_id": str(package_id),
                "section": data.section,
                "recorded_by": str(actor_id) if actor_id else None,
            },
            source_module="oe_tendering",
        )
        logger.info("Award record statement written: package=%s section=%s by=%s", package_id, data.section, actor_id)
        return await self.award_record(package_id)

    async def build_award_record_pdf(self, package_id: uuid.UUID) -> tuple[bytes, str]:
        """Render the award record as the PDF the authority files.

        Downloadable at every stage the record is readable, gaps included: a
        record filed halfway through a procedure is the normal case, and one
        that could only be exported after the award would be the reconstruction
        the law is trying to prevent.
        """
        from app.modules.tendering.pdf_documents import generate_award_record_pdf

        record = await self.award_record(package_id)
        pdf = generate_award_record_pdf(record=record.model_dump(), package_ref=str(package_id)[:8])
        return pdf, f"award_record_{self._slug(record.package_name)}.pdf"

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
            ref_positions = _positions_in_scope(boq_data.positions, package.metadata_)
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

        # Per-bid, per-unit mean rate for imputing missing lines (OC-24).
        # A global mean across all units (m, m², m³, pcs, kg ...) produces
        # absurd values when the bidder quotes heavy per-m³ rates that get
        # applied to lightweight per-m positions.  Group by the reference
        # row's unit so the imputed rate comes from comparable work.
        # Build reference-unit lookup first.
        _ref_unit: dict[str, str] = {}
        for ref in ref_rows:
            _ref_unit[ref["position_id"]] = (ref.get("unit") or "").strip().lower()

        # {bid_id -> {unit -> [rates]}}
        bid_unit_rates: dict[str, dict[str, list[Decimal]]] = {}
        bid_all_rates: dict[str, list[Decimal]] = {}
        for bid in bids:
            bid_id = str(bid.id)
            unit_buckets: dict[str, list[Decimal]] = {}
            all_rates: list[Decimal] = []
            for pid, item in bid_index[bid_id].items():
                rate = _to_decimal(item.get("unit_rate", 0))
                if rate > 0:
                    unit = _ref_unit.get(pid, "")
                    unit_buckets.setdefault(unit, []).append(rate)
                    all_rates.append(rate)
            bid_unit_rates[bid_id] = unit_buckets
            bid_all_rates[bid_id] = all_rates

        def _impute_rate(bid_id: str, unit: str) -> Decimal:
            """Return the best available mean rate for this bid and unit."""
            bucket = bid_unit_rates.get(bid_id, {}).get(unit, [])
            if bucket:
                return sum(bucket, Decimal("0")) / Decimal(len(bucket))
            # Fallback to overall mean if no same-unit rates exist.
            all_r = bid_all_rates.get(bid_id, [])
            return (sum(all_r, Decimal("0")) / Decimal(len(all_r))) if all_r else Decimal("0")

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
                    # OC-24: use a tolerance so minor rounding differences
                    # (e.g. 44.36 vs 44.360000) are not flagged as "scaled".
                    if raw_total > 0 and abs(leveled_total - raw_total) > Decimal("0.01"):
                        cell_status = "scaled"
                        summaries[bid_id]["scaled_lines"] += 1
                    else:
                        cell_status = "matched"
                        summaries[bid_id]["matched_lines"] += 1
                else:
                    # Imputed at the bidder's per-unit mean rate × reference
                    # quantity, so rates from incompatible units don't mix.
                    ref_unit = _ref_unit.get(pid, "")
                    unit_rate = _impute_rate(bid_id, ref_unit)
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
