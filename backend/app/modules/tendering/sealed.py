# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Sealed submission mode of a tender package.

A package is informal unless it has an ``oe_tendering_sealing`` row. In sealed
mode:

* the deadline is an instant with a time and a zone, stored and compared in UTC
  on the server; a submission at or after it is refused, there is no late flag;
* until an authorised opening the bid content (amount, line items, notes,
  metadata) is withheld from every staff read, list, export, event and log, and
  every route that computes from bid figures answers 409 ``sealed_not_opened``;
* opening needs ``tendering.sealed.open`` and a passed deadline; with
  ``dual_opening`` a second, different user completes it;
* each accepted submission gets a receipt: UTC time stamp and the SHA-256 of
  its canonical content, which the integrity check recomputes later.

Openings, refused openings, integrity checks and reads of opened sealed bids are
written to the audit log. This is a tool for running a sealed procedure; it does
not by itself make a procedure compliant with any particular procurement law.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_log
from app.modules.tendering.intl import _parse_deadline
from app.modules.tendering.models import TenderBid, TenderBidReceipt, TenderPackage, TenderSealing

logger = logging.getLogger(__name__)

MODE_INFORMAL = "informal"
MODE_SEALED = "sealed"

SEALED_NOT_OPENED = "sealed_not_opened"
SEALED_DEADLINE_PASSED = "sealed_deadline_passed"

_AUDIT_ENTITY = "tender_sealed"
_DECIDED_STATES = frozenset({"awarded", "closed"})


# ── Pure helpers ──────────────────────────────────────────────────────────────


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def deadline_has_time_and_zone(text: str | None) -> bool:
    """True when a deadline names a clock time and a UTC offset (or ``Z``)."""
    raw = (text or "").strip()
    if "T" not in raw.upper() or ":" not in raw:
        return False
    clock = raw.upper().split("T", 1)[1]
    return clock.endswith("Z") or "+" in clock or "-" in clock


def sealed_deadline(text: str | None) -> datetime | None:
    """The sealed deadline as a UTC instant, or None when it is missing or unreadable."""
    if not deadline_has_time_and_zone(text):
        return None
    try:
        return _parse_deadline(text).astimezone(UTC)
    except ValueError:
        return None


def state_of(sealing: TenderSealing | None) -> str | None:
    """``None`` for informal, else ``sealed`` / ``awaiting_second`` / ``opened``."""
    if sealing is None:
        return None
    if sealing.opened_at is not None:
        return "opened"
    if sealing.first_approver_id:
        return "awaiting_second"
    return "sealed"


def is_closed(sealing: TenderSealing | None) -> bool:
    """True while the bid content of a sealed package must stay hidden."""
    return sealing is not None and sealing.opened_at is None


def canonical_content(bid: TenderBid) -> bytes:
    """The bytes a receipt hashes: what the bidder submitted, in a fixed order."""
    meta = bid.metadata_ if isinstance(bid.metadata_, dict) else {}
    body = {
        "bid_id": str(bid.id),
        "package_id": str(bid.package_id),
        "company_name": bid.company_name,
        "currency": bid.currency,
        "total_amount": bid.total_amount,
        "submitted_at": bid.submitted_at,
        "line_items": bid.line_items or [],
        "bidder_note": meta.get("bidder_note", ""),
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


def content_sha256(bid: TenderBid) -> str:
    return hashlib.sha256(canonical_content(bid)).hexdigest()


def redacted_bid_fields() -> dict[str, Any]:
    """What a staff read gets in place of a sealed bid's content."""
    return {"total_amount": "", "line_items": [], "notes": "", "metadata": {"sealed": True}}


# ── Service ───────────────────────────────────────────────────────────────────


class SealedTenderService:
    """Reads and writes of the sealed mode; every check runs on server UTC time."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, package_id: uuid.UUID, *, for_update: bool = False) -> TenderSealing | None:
        stmt = select(TenderSealing).where(TenderSealing.package_id == package_id)
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def by_package(self, package_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, TenderSealing]:
        ids = list(package_ids)
        if not ids:
            return {}
        rows = (await self.session.execute(select(TenderSealing).where(TenderSealing.package_id.in_(ids)))).scalars()
        return {row.package_id: row for row in rows}

    async def closed_package_ids(self, package_ids: Iterable[uuid.UUID]) -> set[uuid.UUID]:
        return {pid for pid, row in (await self.by_package(package_ids)).items() if is_closed(row)}

    async def is_closed(self, package_id: uuid.UUID) -> bool:
        return is_closed(await self.get(package_id))

    async def ensure_open(self, package_id: uuid.UUID, *, user_id: str | None = None, what: str = "") -> None:
        """Refuse a read of bid content while the package is sealed; record reads after opening."""
        sealing = await self.get(package_id)
        if sealing is None:
            return
        if is_closed(sealing):
            await self._audit("read_refused", package_id, user_id, {"what": what})
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=SEALED_NOT_OPENED)
        await self._audit("read", package_id, user_id, {"what": what})

    async def record_read(self, package_id: uuid.UUID, user_id: str | None, what: str) -> None:
        """Audit a read of an opened sealed package's bids (no-op for informal)."""
        sealing = await self.get(package_id)
        if sealing is not None and not is_closed(sealing):
            await self._audit("read", package_id, user_id, {"what": what})

    async def _audit(self, action: str, package_id: uuid.UUID, user_id: str | None, details: dict) -> None:
        try:
            uid = str(uuid.UUID(str(user_id))) if user_id else None
        except (ValueError, TypeError):
            uid = None
        await audit_log(
            self.session,
            action=action,
            entity_type=_AUDIT_ENTITY,
            entity_id=str(package_id),
            user_id=uid,
            details=details,
        )

    # Mode ──────────────────────────────────────────────────────────────────

    async def set_mode(
        self, package: TenderPackage, mode: str, *, dual_opening: bool, user_id: str | None
    ) -> TenderSealing | None:
        """Switch a package between informal and sealed.

        Raises:
            HTTPException 409: package decided, bids already in, or already opened.
            HTTPException 422: sealed mode without a future deadline carrying time and zone.
        """
        if package.status in _DECIDED_STATES:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="package_decided")
        sealing = await self.get(package.id, for_update=True)
        if sealing is not None and sealing.opened_at is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="sealed_already_opened")
        current = MODE_SEALED if sealing is not None else MODE_INFORMAL
        if mode != current:
            has_bids = (
                await self.session.execute(select(TenderBid.id).where(TenderBid.package_id == package.id).limit(1))
            ).first() is not None
            if has_bids:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="sealed_bids_exist")
        if mode == MODE_INFORMAL:
            if sealing is not None:
                await self.session.delete(sealing)
                await self.session.flush()
                await self._audit("mode_informal", package.id, user_id, {})
            return None
        self.check_deadline(package.deadline, require_future=True)
        if sealing is None:
            sealing = TenderSealing(package_id=package.id, dual_opening=dual_opening, created_by=user_id)
            self.session.add(sealing)
        else:
            if sealing.first_approver_id and sealing.dual_opening != dual_opening:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="sealed_opening_in_progress")
            sealing.dual_opening = dual_opening
        await self.session.flush()
        await self._audit("mode_sealed", package.id, user_id, {"dual_opening": dual_opening})
        return sealing

    @staticmethod
    def check_deadline(deadline: str | None, *, require_future: bool) -> datetime:
        if not (deadline or "").strip():
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="sealed_deadline_required")
        due = sealed_deadline(deadline)
        if due is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="sealed_deadline_needs_time_and_zone"
            )
        if require_future and due <= datetime.now(UTC):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="sealed_deadline_in_past")
        return due

    async def guard_package_update(self, package: TenderPackage, fields: dict[str, Any]) -> None:
        """A sealed deadline may move only while it is still ahead, and only to a future instant."""
        if "deadline" not in fields or fields["deadline"] == package.deadline:
            return
        sealing = await self.get(package.id)
        if sealing is None:
            return
        old_due = sealed_deadline(package.deadline)
        if sealing.opened_at is not None or (old_due is not None and old_due <= datetime.now(UTC)):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=SEALED_DEADLINE_PASSED)
        self.check_deadline(fields["deadline"], require_future=True)

    # Submission ────────────────────────────────────────────────────────────

    def check_submission_window(self, package: TenderPackage, sealing: TenderSealing) -> None:
        """Server-time gate for a bidder write in sealed mode. No late acceptance."""
        if sealing.opened_at is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="tender_closed")
        due = sealed_deadline(package.deadline)
        if due is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="sealed_deadline_required")
        if datetime.now(UTC) >= due:
            raise HTTPException(status_code=status.HTTP_410_GONE, detail=SEALED_DEADLINE_PASSED)

    async def issue_receipt(self, bid: TenderBid, invitation_id: uuid.UUID | None, at: datetime) -> TenderBidReceipt:
        receipt = TenderBidReceipt(
            package_id=bid.package_id,
            bid_id=bid.id,
            invitation_id=invitation_id,
            content_sha256=content_sha256(bid),
            received_at=at,
        )
        self.session.add(receipt)
        await self.session.flush()
        logger.info("Sealed submission received: package=%s bid=%s", bid.package_id, bid.id)
        return receipt

    async def latest_receipt(self, bid_id: uuid.UUID) -> TenderBidReceipt | None:
        stmt = (
            select(TenderBidReceipt)
            .where(TenderBidReceipt.bid_id == bid_id)
            .order_by(TenderBidReceipt.received_at.desc(), TenderBidReceipt.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def verify(self, bid: TenderBid, user_id: str | None) -> dict[str, Any]:
        receipt = await self.latest_receipt(bid.id)
        current = content_sha256(bid)
        intact = receipt is not None and receipt.content_sha256 == current
        await self._audit("integrity_check", bid.package_id, user_id, {"bid_id": str(bid.id), "intact": intact})
        return {
            "bid_id": bid.id,
            "receipt_sha256": receipt.content_sha256 if receipt else None,
            "current_sha256": current,
            "received_at": _aware(receipt.received_at) if receipt else None,
            "intact": intact,
        }

    # Opening ───────────────────────────────────────────────────────────────

    async def open(self, package: TenderPackage, user_id: str) -> TenderSealing:
        """One opening step by an authorised user, on server UTC time.

        Raises:
            HTTPException 409: not sealed, already opened, deadline not passed,
                or the second opener is the first approver.
        """
        sealing = await self.get(package.id, for_update=True)
        if sealing is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="not_sealed")
        if sealing.opened_at is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="sealed_already_opened")
        now = datetime.now(UTC)
        due = sealed_deadline(package.deadline)
        if due is None or now < due:
            await self._audit("open_refused", package.id, user_id, {"reason": "deadline_not_passed"})
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="sealed_deadline_not_passed")
        if sealing.dual_opening and not sealing.first_approver_id:
            sealing.first_approver_id = str(user_id)
            sealing.first_approved_at = now
            await self.session.flush()
            await self._audit("open_first_approval", package.id, user_id, {})
            return sealing
        if sealing.dual_opening and sealing.first_approver_id == str(user_id):
            await self._audit("open_refused", package.id, user_id, {"reason": "same_user"})
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="sealed_second_opener_must_differ")
        sealing.opened_at = now
        sealing.opened_by = str(user_id)
        await self.session.flush()
        await self._audit(
            "open",
            package.id,
            user_id,
            {"dual_opening": sealing.dual_opening, "first_approver_id": sealing.first_approver_id},
        )
        logger.info("Sealed package opened: package=%s", package.id)
        return sealing

    async def status_view(self, package: TenderPackage) -> dict[str, Any]:
        sealing = await self.get(package.id)
        due = sealed_deadline(package.deadline)
        now = datetime.now(UTC)
        submissions: list[dict[str, Any]] = []
        if sealing is not None:
            rows = (
                await self.session.execute(
                    select(TenderBidReceipt, TenderBid.company_name)
                    .join(TenderBid, TenderBid.id == TenderBidReceipt.bid_id)
                    .where(TenderBidReceipt.package_id == package.id)
                    .order_by(TenderBidReceipt.received_at)
                )
            ).all()
            for receipt, company in rows:
                submissions.append(
                    {
                        "bid_id": receipt.bid_id,
                        "company_name": company,
                        "received_at": _aware(receipt.received_at),
                        "sha256": receipt.content_sha256,
                    }
                )
        return {
            "package_id": package.id,
            "mode": MODE_SEALED if sealing is not None else MODE_INFORMAL,
            "state": state_of(sealing),
            "dual_opening": bool(sealing.dual_opening) if sealing else False,
            "deadline_utc": due,
            "server_now": now,
            "deadline_passed": due is not None and now >= due,
            "first_approver_id": sealing.first_approver_id if sealing else None,
            "first_approved_at": _aware(sealing.first_approved_at) if sealing else None,
            "opened_at": _aware(sealing.opened_at) if sealing else None,
            "opened_by": sealing.opened_by if sealing else None,
            "submissions": submissions,
        }

    async def validation_payload(self, package: TenderPackage) -> dict[str, Any]:
        """Input of the ``tendering_sealed`` rule set."""
        sealing = await self.get(package.id)
        bids = list((await self.session.execute(select(TenderBid).where(TenderBid.package_id == package.id))).scalars())
        due = sealed_deadline(package.deadline)
        rows = []
        for bid in bids:
            receipt = await self.latest_receipt(bid.id)
            rows.append(
                {
                    "bid_id": str(bid.id),
                    "has_receipt": receipt is not None,
                    "received_at": _aware(receipt.received_at).isoformat() if receipt else None,
                    "on_time": receipt is not None and due is not None and _aware(receipt.received_at) < due,
                    "intact": receipt is not None and receipt.content_sha256 == content_sha256(bid),
                }
            )
        return {
            "mode": MODE_SEALED if sealing is not None else MODE_INFORMAL,
            "deadline": package.deadline,
            "deadline_ok": due is not None,
            "dual_opening": bool(sealing.dual_opening) if sealing else False,
            "first_approver_id": sealing.first_approver_id if sealing else None,
            "opened_by": sealing.opened_by if sealing else None,
            "opened": sealing is not None and sealing.opened_at is not None,
            "bids": rows,
        }
