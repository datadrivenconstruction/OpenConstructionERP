# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bidder price-entry links: a subcontractor prices the bill through a web link.

A firm on a package's distribution list has no account on the platform. Staff
make it a personal link (``/tendering/bid/{token}`` in the web app); the firm opens it,
sees the bill as text and quantities, types its unit prices, saves a draft as
often as it likes and submits once. Submitting writes a ``TenderBid`` through
the same ``TenderingService.create_bid`` / ``update_bid`` path a manually
entered bid takes, so the bid lands in the price comparison and the leveling
matrix with the same line shape and the same frozen-package rules.

The link is the credential, so:

* the token is 32 random bytes, shown once when the link is made, and only its
  sha256 is stored (:func:`hash_token`);
* the public payload is built field by field from the bill's text and
  quantities; the buyer's rates, sums, markups, resources, budget, the package
  metadata and the other bidders never enter it;
* an unknown token answers 404 and a revoked or expired one 410, all three with
  a bare code and no package data;
* a link expires at the tender deadline (end of day for a date-only deadline),
  or after :data:`DEFAULT_LINK_TTL` when the package has no deadline in the
  future. A link made before the deadline follows the package's current
  deadline both ways, so moving it later extends the link and moving it
  earlier (or setting one on a package that had none) cuts it. A link the
  buyer makes after the deadline has passed is a deliberate late invitation
  and keeps its own expiry; a bid submitted through it is marked ``late``.

Making a new link for a recipient revokes that recipient's older links and
carries their draft, their bid and their submitted state over, so a firm that
already submitted gets a read-only receipt, whether the link came from "Copy
bidder link" or from another distribution run. Only an explicit reopen by the
buyer (:meth:`BidPortalService.create_link` with ``reopen=True``) makes the
new link writable again; the resubmission then updates the same ``TenderBid``
rather than adding a second one, and the figures it replaces are kept in the
bid's ``metadata["revisions"]``.

The token helpers are three lines each and match ``app.modules.portal``'s; they
are not imported from there so tendering does not depend on the portal module
being installed.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.core.rate_limiter import RateLimiter, client_identifier
from app.modules.tendering.intl import _parse_deadline
from app.modules.tendering.models import TenderBidInvitation, TenderPackage
from app.modules.tendering.schemas import (
    BidCreate,
    BidInvitationCreated,
    BidInvitationResponse,
    BidLineItem,
    BidPortalDraft,
    BidPortalLine,
    BidPortalPricesRequest,
    BidPortalView,
    BidUpdate,
)

logger = logging.getLogger(__name__)

#: How long a link lives when the package has no deadline in the future.
DEFAULT_LINK_TTL = timedelta(days=30)

#: Package states in which the tender is decided; a link then only reads.
_CLOSED_PACKAGE_STATES = frozenset({"awarded", "closed"})

#: Upper bound for one unit price, and how many decimals it may carry.
_MAX_UNIT_PRICE = Decimal("100000000000")
_MAX_PRICE_DECIMALS = 4

_MAX_LONG_TEXT = 20_000

#: How many replaced versions of a reopened bid its metadata keeps.
_MAX_REVISIONS = 20

# The public routes answer anyone who holds a link, so each client address
# gets a budget. Reads are cheap and a bidder's page refetches; writes are a
# draft save or a submit. In-memory per process, like every limiter here.
_read_limiter = RateLimiter(max_requests=120, window_seconds=60)
_write_limiter = RateLimiter(max_requests=30, window_seconds=60)

# Codes the public routes answer with. They name the case and nothing else.
LINK_NOT_FOUND = "bid_link_not_found"
LINK_REVOKED = "bid_link_revoked"
LINK_EXPIRED = "bid_link_expired"


# ── Pure helpers ──────────────────────────────────────────────────────────────


def generate_token() -> str:
    """32 random bytes, URL-safe (43 characters)."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """sha256 hex digest of a token; the only form that is stored."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _aware(value: datetime | None) -> datetime | None:
    """Read a naive timestamp (SQLite hands those back) as UTC."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def deadline_instant(deadline: str | None) -> datetime | None:
    """The tender deadline as an instant, or None when it is empty or unreadable.

    Uses the module's own deadline rule (:func:`intl._parse_deadline`): a
    date-only deadline means the end of that day, UTC.
    """
    try:
        return _parse_deadline(deadline)
    except ValueError:
        return None


def initial_expiry(deadline: str | None, now: datetime) -> datetime:
    """When a link made at ``now`` expires.

    The deadline when it is still ahead, otherwise ``now`` plus
    :data:`DEFAULT_LINK_TTL`. A package without a readable deadline, or one
    whose deadline already passed when the buyer chose to send a link anyway,
    gets the default rather than a link that is dead on arrival.
    """
    due = deadline_instant(deadline)
    if due is not None and due > now:
        return due
    return now + DEFAULT_LINK_TTL


def effective_expiry(invitation: TenderBidInvitation, deadline: str | None) -> datetime:
    """When a link stops working, given the package's deadline as it is now.

    A link made before the deadline lives exactly as long as the tender runs:
    the current deadline decides, whether it moved later or earlier since the
    link was made. A link made after the deadline had passed is the buyer
    deliberately inviting a late bid; the deadline cannot cut it, only extend it.
    """
    stored = _aware(invitation.expires_at) or datetime.now(UTC)
    due = deadline_instant(deadline)
    if due is None:
        return stored
    created = _aware(invitation.created_at)
    if created is not None and created < due:
        return due
    return max(stored, due)


def usable_recipient_id(value: object) -> str | None:
    """A recipient id a link can be keyed on, or None for a missing one.

    ``None``, ``0`` and their string forms are what a recipient entry without
    an id turns into after ``str()``; a link keyed on them would be shared by
    every such entry.
    """
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if text.lower() in ("", "none", "null", "0"):
        return None
    return text


def invitation_status(invitation: TenderBidInvitation, deadline: str | None, now: datetime) -> str:
    """``revoked``, ``submitted``, ``expired``, ``opened`` or ``not_opened``.

    Revoked wins over everything, and a submitted link stays ``submitted`` after
    it expires, because what the buyer needs to know then is that a bid came in.
    """
    if invitation.revoked_at is not None:
        return "revoked"
    if invitation.submitted_at is not None:
        return "submitted"
    if now > effective_expiry(invitation, deadline):
        return "expired"
    if invitation.opened_at is not None:
        return "opened"
    return "not_opened"


def _decimal_text(value: object) -> str:
    """A stored quantity as a plain decimal string; empty when unreadable."""
    try:
        number = Decimal(str(value if value not in (None, "") else "0"))
    except (InvalidOperation, ValueError):
        return ""
    if not number.is_finite():
        return ""
    text = format(number.normalize(), "f")
    return "0" if text in ("-0", "") else text


def _long_text(position: Any) -> str:
    meta = getattr(position, "metadata_", None)
    if not isinstance(meta, Mapping):
        return ""
    for key in ("gaeb_long_text", "long_text"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            text = value.strip()[:_MAX_LONG_TEXT]
            return "" if text == (getattr(position, "description", "") or "").strip() else text
    return ""


def bidder_lines(positions: list[Any], metadata: Mapping[str, Any] | None) -> tuple[list[dict], dict[str, Any]]:
    """The rows a bidder prices, with the section headings above them.

    The package scope decides which lines are asked for, exactly as the
    comparison and leveling read it (:func:`service._positions_in_scope`).
    Section headings come from the whole bill, so a package whose scope lists
    only priced lines still shows the bidder the headings those lines sit
    under. Placeholder rows nobody filled in are left out.

    Returns:
        ``(lines, priceable)``: the rows in bill order as plain dicts, and the
        priceable positions keyed by their id string.
    """
    from app.modules.boq.service import _is_section, is_empty_position
    from app.modules.tendering.service import _positions_in_scope

    in_scope = _positions_in_scope(positions, dict(metadata or {}))
    priceable: dict[str, Any] = {}
    for position in in_scope:
        if _is_section(position) or is_empty_position(position):
            continue
        priceable[str(position.id)] = position

    by_id = {str(p.id): p for p in positions}
    depth_of: dict[str, int] = {}

    def depth(start: str) -> int:
        if start in depth_of:
            return depth_of[start]
        seen: set[str] = set()
        level = 0
        current = by_id.get(start)
        while current is not None and getattr(current, "parent_id", None) and str(current.id) not in seen:
            seen.add(str(current.id))
            current = by_id.get(str(current.parent_id))
            if current is not None:
                level += 1
        depth_of[start] = level
        return level

    headings: set[str] = set()
    for pid in priceable:
        seen: set[str] = set()
        parent_id = getattr(by_id[pid], "parent_id", None)
        while parent_id and str(parent_id) in by_id and str(parent_id) not in seen:
            seen.add(str(parent_id))
            parent = by_id[str(parent_id)]
            if _is_section(parent):
                headings.add(str(parent_id))
            parent_id = getattr(parent, "parent_id", None)

    lines: list[dict] = []
    for position in positions:
        pid = str(position.id)
        if pid in priceable:
            kind = "item"
        elif pid in headings:
            kind = "section"
        else:
            continue
        lines.append(
            {
                "id": pid,
                "kind": kind,
                "ordinal": str(getattr(position, "ordinal", "") or ""),
                "short_text": str(getattr(position, "description", "") or ""),
                "long_text": _long_text(position),
                "unit": str(getattr(position, "unit", "") or "") if kind == "item" else "",
                "quantity": _decimal_text(getattr(position, "quantity", "")) if kind == "item" else "",
                "depth": depth(pid),
            }
        )
    return lines, priceable


def parse_unit_price(raw: object) -> Decimal | None:
    """Parse one entered unit price; None means the line is left unpriced.

    Raises:
        ValueError: with a short reason code (``not_a_number``, ``negative``,
            ``too_large``, ``too_many_decimals``).
    """
    if raw is None or isinstance(raw, bool):
        if isinstance(raw, bool):
            raise ValueError("not_a_number")
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("not_a_number") from exc
    # Before any comparison: ``Decimal('sNaN') < 0`` raises instead of answering.
    if not value.is_finite():
        raise ValueError("not_a_number")
    if value < 0:
        raise ValueError("negative")
    if value > _MAX_UNIT_PRICE:
        raise ValueError("too_large")
    exponent = value.as_tuple().exponent
    if isinstance(exponent, int) and -exponent > _MAX_PRICE_DECIMALS:
        raise ValueError("too_many_decimals")
    # ``-0`` passes the sign check; store it as the zero it is.
    return value.copy_abs() if value.is_zero() else value


def validate_unit_prices(raw_prices: Mapping[str, object], priceable: Mapping[str, Any]) -> dict[str, Decimal]:
    """Check every entered price against the package's lines.

    Returns only the priced lines. Refuses the whole request with 422 when any
    line id is not a priceable line of this package or any value is not a
    usable price, naming each offending line, so nothing is half saved.
    """
    errors: list[dict[str, str]] = []
    priced: dict[str, Decimal] = {}
    for line_id, raw in raw_prices.items():
        key = str(line_id)
        if key not in priceable:
            errors.append({"line_id": key[:64], "reason": "not_in_package"})
            continue
        try:
            value = parse_unit_price(raw)
        except ValueError as exc:
            errors.append({"line_id": key, "reason": str(exc)})
            continue
        if value is not None:
            priced[key] = value
    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "invalid_unit_prices", "errors": errors[:200]},
        )
    return priced


def enforce_rate_limit(request: Request, *, write: bool) -> None:
    """Refuse with 429 once a client address has spent its budget."""
    limiter = _write_limiter if write else _read_limiter
    allowed, _ = limiter.is_allowed(client_identifier(request))
    if not allowed:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="rate_limited")


def reset_rate_limits() -> None:
    """Forget every bucket (tests share one process)."""
    for limiter in (_read_limiter, _write_limiter):
        with limiter._lock:
            limiter._requests.clear()


def bid_link_url(token: str) -> str:
    """The web-app address of a bidder link."""
    from app.config import get_settings

    base = (get_settings().resolved_frontend_url or "").rstrip("/")
    # Under ``/tendering/`` on purpose: the production proxy forwards an
    # allowlist of top-level segments to the app, and ``tendering`` is on it,
    # so the link works without a proxy change. The route itself is public
    # and sits outside the app shell.
    path = f"/tendering/bid/{token}"
    return f"{base}{path}" if base else path


def _utc_stamp(moment: datetime) -> str:
    # ``BidCreate.submitted_at`` allows 20 characters, which is exactly this form.
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Service ───────────────────────────────────────────────────────────────────


class BidPortalService:
    """Staff and public operations on bidder links."""

    def __init__(self, session: AsyncSession) -> None:
        from app.modules.tendering.service import TenderingService

        self.session = session
        self.tendering = TenderingService(session)

    # Staff side ───────────────────────────────────────────────────────────

    def to_response(self, invitation: TenderBidInvitation, deadline: str | None) -> BidInvitationResponse:
        """Staff view of a link, with its status as of now."""
        now = datetime.now(UTC)
        return BidInvitationResponse(
            id=invitation.id,
            package_id=invitation.package_id,
            recipient_id=invitation.recipient_id,
            company_name=invitation.company_name,
            email=invitation.email,
            status=invitation_status(invitation, deadline, now),
            expires_at=effective_expiry(invitation, deadline),
            opened_at=_aware(invitation.opened_at),
            draft_saved_at=_aware(invitation.draft_saved_at),
            submitted_at=_aware(invitation.submitted_at),
            revoked_at=_aware(invitation.revoked_at),
            bid_id=invitation.bid_id,
            created_at=_aware(invitation.created_at) or now,
        )

    async def _invitations_for(
        self, package_id: uuid.UUID, recipient_id: str | None = None
    ) -> list[TenderBidInvitation]:
        stmt = select(TenderBidInvitation).where(TenderBidInvitation.package_id == package_id)
        if recipient_id is not None:
            stmt = stmt.where(TenderBidInvitation.recipient_id == recipient_id)
        stmt = stmt.order_by(TenderBidInvitation.created_at.desc())
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_invitations(self, package_id: uuid.UUID) -> list[BidInvitationResponse]:
        """Every link of a package, newest first."""
        package = await self.tendering.get_package(package_id)
        rows = await self._invitations_for(package_id)
        return [self.to_response(row, package.deadline) for row in rows]

    async def mint(
        self,
        package: TenderPackage,
        recipient: Mapping[str, Any],
        *,
        actor_id: str | None,
        reopen: bool = False,
    ) -> tuple[TenderBidInvitation, str]:
        """Make a new link for a recipient without touching the older ones.

        The newest earlier link's draft, bid and submitted state are carried
        over, so a firm that gets a fresh link keeps what it typed, a firm that
        already submitted gets a read-only receipt, and a resubmission updates
        its existing bid. ``reopen`` drops the submitted state so the firm can
        revise its bid; only the buyer's explicit reopen passes it. Call
        :meth:`retire_others` once the new link is known to have reached the
        firm.

        Raises:
            ValueError: the recipient entry has no usable id.
        """
        recipient_id = usable_recipient_id(recipient.get("id"))
        if recipient_id is None:
            raise ValueError("recipient_without_id")
        previous = await self._invitations_for(package.id, recipient_id)
        carried = previous[0] if previous else None
        now = datetime.now(UTC)
        token = generate_token()
        invitation = TenderBidInvitation(
            package_id=package.id,
            recipient_id=recipient_id,
            company_name=str(recipient.get("company_name") or "")[:255],
            email=str(recipient.get("email") or "")[:255],
            token_hash=hash_token(token),
            expires_at=initial_expiry(package.deadline, now),
            draft=dict(carried.draft or {}) if carried is not None else {},
            draft_saved_at=carried.draft_saved_at if carried is not None else None,
            submitted_at=carried.submitted_at if carried is not None and not reopen else None,
            bid_id=carried.bid_id if carried is not None else None,
            created_by=str(actor_id) if actor_id else None,
        )
        self.session.add(invitation)
        await self.session.flush()
        return invitation, token

    async def retire_others(self, package_id: uuid.UUID, recipient_id: str, keep: uuid.UUID | None) -> int:
        """Revoke every live link of a recipient except ``keep``. Returns how many."""
        now = datetime.now(UTC)
        count = 0
        for row in await self._invitations_for(package_id, recipient_id):
            if row.id == keep or row.revoked_at is not None:
                continue
            row.revoked_at = now
            count += 1
        if count:
            await self.session.flush()
        return count

    async def create_link(
        self,
        package_id: uuid.UUID,
        recipient_id: str,
        *,
        actor_id: str | None,
        reopen: bool = False,
    ) -> BidInvitationCreated:
        """Make (or remake) a recipient's link and return its URL, once.

        A firm that already submitted gets a read-only link to its receipt
        unless ``reopen`` is set, which lets it revise and submit again.

        Raises:
            HTTPException 404: the package or the recipient does not exist.
            HTTPException 422: the recipient entry has no usable id.
        """
        package = await self.tendering.get_package(package_id)
        wanted = usable_recipient_id(recipient_id)
        if wanted is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="recipient_without_id")
        recipient = next(
            (r for r in self.tendering._read_recipients(package) if usable_recipient_id(r.get("id")) == wanted),
            None,
        )
        if recipient is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recipient not found")
        invitation, token = await self.mint(package, recipient, actor_id=actor_id, reopen=reopen)
        replaced = await self.retire_others(package_id, invitation.recipient_id, keep=invitation.id)
        logger.info(
            "Bidder link made: package=%s recipient=%s replaced=%s reopen=%s by=%s",
            package_id,
            invitation.recipient_id,
            replaced,
            reopen,
            actor_id,
        )
        base = self.to_response(invitation, package.deadline)
        return BidInvitationCreated(**base.model_dump(), url=bid_link_url(token), replaced_count=replaced)

    async def revoke(self, package_id: uuid.UUID, invitation_id: uuid.UUID) -> BidInvitationResponse:
        """Revoke one link. A link of another package answers 404."""
        package = await self.tendering.get_package(package_id)
        invitation = await self.session.get(TenderBidInvitation, invitation_id)
        if invitation is None or invitation.package_id != package_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bidder link not found")
        if invitation.revoked_at is None:
            invitation.revoked_at = datetime.now(UTC)
            await self.session.flush()
        return self.to_response(invitation, package.deadline)

    # Public side ──────────────────────────────────────────────────────────

    async def _resolve(self, token: str, *, for_update: bool = False) -> TenderBidInvitation:
        """The live link behind a token, or 404 / 410 with a bare code."""
        if not token or len(token) > 128:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=LINK_NOT_FOUND)
        stmt = select(TenderBidInvitation).where(TenderBidInvitation.token_hash == hash_token(token))
        if for_update:
            stmt = stmt.with_for_update()
        invitation = (await self.session.execute(stmt)).scalar_one_or_none()
        if invitation is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=LINK_NOT_FOUND)
        if invitation.revoked_at is not None:
            raise HTTPException(status_code=status.HTTP_410_GONE, detail=LINK_REVOKED)
        package = await self.session.get(TenderPackage, invitation.package_id)
        deadline = package.deadline if package is not None else None
        if datetime.now(UTC) > effective_expiry(invitation, deadline):
            raise HTTPException(status_code=status.HTTP_410_GONE, detail=LINK_EXPIRED)
        return invitation

    async def _context(self, invitation: TenderBidInvitation) -> tuple[TenderPackage, str, str, list[dict], dict]:
        """(package, project name, currency, lines, priceable) for a link."""
        package = await self.tendering.get_package(invitation.package_id)
        project_name, currency = await self.tendering._project_name_and_currency(package)
        if not currency:
            meta_currency = (package.metadata_ or {}).get("currency")
            currency = meta_currency.strip().upper() if isinstance(meta_currency, str) else ""
        positions: list[Any] = []
        if package.boq_id is not None:
            from app.modules.boq.repository import PositionRepository

            positions = await PositionRepository(self.session).list_all_for_boq(package.boq_id)
        lines, priceable = bidder_lines(positions, package.metadata_)
        return package, project_name, currency, lines, priceable

    def _view(
        self,
        invitation: TenderBidInvitation,
        package: TenderPackage,
        project_name: str,
        currency: str,
        lines: list[dict],
        priceable: dict,
        bid_amount: str | None = None,
    ) -> BidPortalView:
        from app.core.company_profile import read_company_profile

        draft = invitation.draft if isinstance(invitation.draft, dict) else {}
        raw_prices = draft.get("unit_prices") if isinstance(draft.get("unit_prices"), dict) else {}
        # Only lines that are still on the bill are handed back.
        prices = {str(k): str(v) for k, v in raw_prices.items() if str(k) in priceable and v not in (None, "")}
        if invitation.submitted_at is not None:
            state = "submitted"
        elif package.status in _CLOSED_PACKAGE_STATES:
            state = "closed"
        else:
            state = "open"
        try:
            buyer_name = read_company_profile().get("legal_name", "") or ""
        except Exception:  # noqa: BLE001 - a missing letterhead is not a reason to refuse the page
            buyer_name = ""
        return BidPortalView(
            state=state,
            package_name=package.name,
            package_description=package.description or "",
            deadline=package.deadline,
            currency=currency,
            project_name=project_name,
            buyer_name=buyer_name,
            bidder_company=invitation.company_name,
            expires_at=effective_expiry(invitation, package.deadline),
            lines=[BidPortalLine(**line) for line in lines],
            draft=BidPortalDraft(
                unit_prices=prices,
                notes=str(draft.get("notes") or ""),
                saved_at=_aware(invitation.draft_saved_at),
            ),
            submitted_at=_aware(invitation.submitted_at),
            bid_amount=bid_amount,
            item_count=len(priceable),
            unpriced_count=sum(1 for pid in priceable if pid not in prices),
        )

    @staticmethod
    def _submitted_amount(invitation: TenderBidInvitation) -> str | None:
        """The sum the firm submitted, as it was at submit time.

        Read from the link, not from the ``TenderBid``: the buyer may edit the
        bid afterwards, and the firm's receipt must not show those edits.
        """
        if invitation.submitted_at is None:
            return None
        draft = invitation.draft if isinstance(invitation.draft, dict) else {}
        amount = draft.get("submitted_amount")
        return str(amount) if amount not in (None, "") else None

    async def public_view(self, token: str) -> BidPortalView:
        """What the bidder's page shows. Stamps ``opened_at`` on the first read."""
        invitation = await self._resolve(token)
        package, project_name, currency, lines, priceable = await self._context(invitation)
        if invitation.opened_at is None:
            invitation.opened_at = datetime.now(UTC)
            await self.session.flush()
        amount = self._submitted_amount(invitation)
        return self._view(invitation, package, project_name, currency, lines, priceable, amount)

    def _check_writable(
        self, invitation: TenderBidInvitation, package: TenderPackage, currency: str, body: BidPortalPricesRequest
    ) -> None:
        if invitation.submitted_at is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="bid_already_submitted")
        if package.status in _CLOSED_PACKAGE_STATES:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="tender_closed")
        # A link made while the tender ran stops at the deadline. ``_resolve``
        # already answers so through the expiry; this says it where the write
        # is decided, so a change to the expiry rule cannot reopen late writes.
        due = deadline_instant(package.deadline)
        created = _aware(invitation.created_at)
        if due is not None and created is not None and created < due < datetime.now(UTC):
            raise HTTPException(status_code=status.HTTP_410_GONE, detail=LINK_EXPIRED)
        # A package whose project names no currency cannot prove a mismatch.
        sent = (body.currency or "").strip().upper()
        if sent and currency and sent != currency:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "currency_mismatch", "expected": currency},
            )

    async def save_draft(self, token: str, body: BidPortalPricesRequest) -> BidPortalView:
        """Store the bidder's entries without submitting. Partial is fine."""
        invitation = await self._resolve(token, for_update=True)
        package, project_name, currency, lines, priceable = await self._context(invitation)
        self._check_writable(invitation, package, currency, body)
        priced = validate_unit_prices(body.unit_prices, priceable)
        invitation.draft = {
            "unit_prices": {pid: format(value, "f") for pid, value in priced.items()},
            "notes": body.notes,
        }
        invitation.draft_saved_at = datetime.now(UTC)
        if invitation.opened_at is None:
            invitation.opened_at = invitation.draft_saved_at
        await self.session.flush()
        return self._view(invitation, package, project_name, currency, lines, priceable)

    async def _existing_bid(self, invitation: TenderBidInvitation, package_id: uuid.UUID) -> Any:
        """The bid this firm already has on the package, if any.

        Normally the link carries it. A link made while an older link of the
        same firm was still live has none if the older one submitted in
        between (during the email send, say), so the firm's other links are
        asked too; otherwise that submission would add a second bid.
        """
        candidates = [invitation.bid_id] if invitation.bid_id is not None else []
        if not candidates:
            siblings = await self._invitations_for(package_id, invitation.recipient_id)
            candidates = [row.bid_id for row in siblings if row.bid_id is not None and row.id != invitation.id]
        for bid_id in candidates:
            bid = await self.tendering.repo.get_bid_by_id(bid_id)
            if bid is not None and bid.package_id == package_id:
                return bid
        return None

    async def submit(self, token: str, body: BidPortalPricesRequest) -> BidPortalView:
        """Submit the bid: write the ``TenderBid`` and make the link read-only.

        Lines left blank are not priced and are left out of the bid's
        ``line_items``, so leveling imputes them instead of reading a zero; the
        bid's metadata names them. A submission with nothing priced is refused.
        """
        invitation = await self._resolve(token, for_update=True)
        package, project_name, currency, lines, priceable = await self._context(invitation)
        self._check_writable(invitation, package, currency, body)
        priced = validate_unit_prices(body.unit_prices, priceable)
        if not priced:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="nothing_priced")

        now = datetime.now(UTC)
        line_items: list[BidLineItem] = []
        bid_sum = Decimal("0")
        # Bill order, and every field from the server's own position.
        for pid, position in priceable.items():
            if pid not in priced:
                continue
            unit_price = priced[pid]
            quantity = Decimal(_decimal_text(getattr(position, "quantity", "")) or "0")
            line_sum = unit_price * quantity
            bid_sum += line_sum
            line_items.append(
                BidLineItem(
                    position_id=str(position.id),
                    description=position.description or "",
                    unit=position.unit or "",
                    quantity=float(quantity),
                    unit_rate=unit_price,
                    # Exact product, not rounded: leveling reads a gap above
                    # 0.01 between rate x quantity and the line sum as a scaled
                    # line.
                    total=float(line_sum),
                )
            )
        unpriced = [pid for pid in priceable if pid not in priced]
        amount = format(bid_sum.quantize(Decimal("0.01")), "f")
        # The bid is in the tender's currency, never in one the bidder names:
        # with none known on the GC side it stays "" (unknown), which every
        # currency check here reads as "cannot prove a mismatch".
        bid_currency = currency
        # Only a link the buyer made after the deadline gets this far once the
        # deadline has passed (``_check_writable``); the buyer sees it marked.
        due = deadline_instant(package.deadline)
        bid_meta: dict[str, Any] = {
            "source": "bid_portal",
            "invitation_id": str(invitation.id),
            "recipient_id": invitation.recipient_id,
            "unpriced_position_ids": unpriced,
            "unpriced_count": len(unpriced),
            "bidder_note": body.notes,
            "late": due is not None and now > due,
        }

        existing = await self._existing_bid(invitation, package.id)
        if existing is not None:
            # A reopened bid is overwritten in place; what it said before is
            # kept, so the buyer can still see the figures it replaced.
            old_meta = existing.metadata_ if isinstance(existing.metadata_, dict) else {}
            revisions = list(old_meta.get("revisions") or [])
            revisions.append(
                {
                    "total_amount": existing.total_amount,
                    "currency": existing.currency,
                    "submitted_at": existing.submitted_at,
                    "line_items": existing.line_items or [],
                    "replaced_at": _utc_stamp(now),
                }
            )
            bid_meta["revisions"] = revisions[-_MAX_REVISIONS:]
            bid = await self.tendering.update_bid(
                existing.id,
                BidUpdate(
                    total_amount=amount,
                    currency=bid_currency,
                    submitted_at=_utc_stamp(now),
                    status="submitted",
                    line_items=line_items,
                    metadata=bid_meta,
                ),
            )
        else:
            bid = await self.tendering.create_bid(
                package.id,
                BidCreate(
                    company_name=invitation.company_name or "-",
                    contact_email=invitation.email,
                    total_amount=amount,
                    currency=bid_currency,
                    submitted_at=_utc_stamp(now),
                    status="submitted",
                    line_items=line_items,
                    metadata=bid_meta,
                ),
            )

        invitation.draft = {
            "unit_prices": {pid: format(value, "f") for pid, value in priced.items()},
            "notes": body.notes,
            "submitted_amount": amount,
        }
        invitation.draft_saved_at = now
        invitation.submitted_at = now
        invitation.bid_id = bid.id
        if invitation.opened_at is None:
            invitation.opened_at = now
        await self.session.flush()
        logger.info(
            "Bid submitted through bidder link: package=%s recipient=%s priced=%s unpriced=%s",
            package.id,
            invitation.recipient_id,
            len(priced),
            len(unpriced),
        )
        return self._view(invitation, package, project_name, currency, lines, priceable, amount)
