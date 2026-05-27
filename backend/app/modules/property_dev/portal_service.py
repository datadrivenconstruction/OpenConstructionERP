"""Buyer self-service portal — JWT magic-link service.

This module implements the buyer-facing portal that NEVER authenticates
through the internal JWT auth (buyers have no internal accounts). The
flow is:

1. A sales-manager (internal user) creates a Reservation / SalesContract
   for a Buyer. The UI offers an "Issue buyer access link" action which
   calls :meth:`PortalLinkService.issue_token`.
2. ``issue_token`` mints a JWT with ``scope='portal'`` and persists the
   ``jti`` on :class:`oe_propdev_portal_token` for audit + revocation.
   The full URL ``{frontend_origin}/buyer-portal/{token}`` is emailed
   to the buyer (out of scope for this service — caller handles email).
3. The buyer opens the link. Frontend hits ``POST /verify/`` which
   decodes the JWT, looks up the ``jti`` row, rejects revoked /
   expired / wrong-scope tokens, and returns buyer summary.
4. Every subsequent buyer call (``/overview/``, ``/documents/...``,
   ``/upload-kyc/``, ``/contact-agent/``) goes through
   :meth:`PortalLinkService.resolve_token_for_buyer_access` which
   re-runs the verify + records ``last_used_at`` / ``last_used_ip``.

Design notes:

* The token is stateless on the wire (JWT-signed with ``JWT_SECRET``)
  so verify is fast and doesn't need a DB round-trip for the crypto
  check. The DB lookup is then ONLY for the revocation list + audit
  trail — adding a single ``SELECT WHERE jwt_id = ?`` per request,
  always satisfied by the unique index on ``jwt_id``.
* The ``scope='portal'`` claim is mandatory. The existing R5 token
  ``decode_access_token`` rejects portal tokens for internal endpoints
  by requiring ``type='access'``; this module mirrors that by checking
  ``scope='portal'`` here. A leaked internal access token cannot pivot
  into a portal token and vice-versa.
* Money / payment-schedule reads happen at the service layer; IDOR
  guards live in the router (where the buyer's UUID is known).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.modules.property_dev.models import (
    Buyer,
    PortalToken,
    Reservation,
    SalesContract,
)

logger = logging.getLogger(__name__)


# Token TTL — 30 days per spec. Kept as a module-level constant so the
# tests can monkey-patch it without reaching into the settings object.
PORTAL_TOKEN_TTL_DAYS: int = 30

# JWT scope claim — must match exactly. Any token missing this claim
# (or carrying a different one) is rejected as not-a-portal-token.
PORTAL_TOKEN_SCOPE: str = "portal"

# Error code for a magic-link token that has already been redeemed via
# ``/verify/``. Distinct from the catch-all ``portal_token_invalid_or_expired``
# so the frontend can render the targeted "request a new login link" CTA.
PORTAL_TOKEN_ALREADY_USED_CODE: str = "portal_token_already_used"


class PortalTokenError(Exception):
    """Raised when a portal JWT is malformed / expired / revoked / wrong scope.

    Two distinct error codes:

    * ``portal_token_invalid_or_expired`` — default. Covers four failure
      modes (signature mismatch / missing claims / row missing / expired
      / revoked) collapsed into one code so the response can't be used
      as an existence oracle for forged-but-DB-missing vs genuinely
      expired tokens (anti-enumeration, spec §10).
    * ``portal_token_already_used`` — magic-link has already been
      redeemed via ``/verify/``. Industry-standard single-use semantics
      (Slack/Notion/Linear). The frontend surfaces a dedicated
      "request a new login link" CTA on this code so the buyer knows
      to ask the agent for a fresh link rather than retrying the same
      one. This code is distinguishable on purpose: it carries no
      information that a forged/stranger token wouldn't reveal (the
      row was successfully decoded + matched in the DB, so the only
      thing the response leaks is "this token was previously valid",
      which the holder already knew).
    """

    def __init__(self, code: str = "portal_token_invalid_or_expired") -> None:
        super().__init__(code)
        self.code = code


@dataclass(slots=True)
class PortalContext:
    """Resolved portal session — opaque handle the router uses."""

    token_row: PortalToken
    buyer: Buyer
    reservation: Reservation | None
    sales_contract: SalesContract | None


class PortalLinkService:
    """JWT magic-link issuance + verification for the buyer portal."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    # ── Issuance ──────────────────────────────────────────────────────

    async def issue_token(
        self,
        *,
        buyer_id: uuid.UUID,
        reservation_id: uuid.UUID | None = None,
        sales_contract_id: uuid.UUID | None = None,
        issued_by_user_id: uuid.UUID | None = None,
    ) -> tuple[str, PortalToken]:
        """Mint a fresh portal JWT + persist its ``jti`` for revocation.

        Returns ``(token_string, row)``. The token string is opaque to
        the caller — it should be passed verbatim into the email body
        and the audit row should be returned in the UI panel.
        """
        buyer = await self.session.get(Buyer, buyer_id)
        if buyer is None:
            # Caller already RBAC-checked; a missing buyer here means
            # the row was deleted in-flight. Surface as an HTTP-friendly
            # error at the router layer.
            raise PortalTokenError("portal_token_buyer_not_found")

        now = datetime.now(UTC)
        expires_at = now + timedelta(days=PORTAL_TOKEN_TTL_DAYS)
        jti = uuid.uuid4().hex

        payload = {
            "iss": "openconstructionerp",
            "sub": str(buyer_id),
            "scope": PORTAL_TOKEN_SCOPE,
            "type": "portal",  # mirrors existing 'access' / 'refresh' / 'reset'
            "jti": jti,
            "iat": now,
            "exp": expires_at,
        }
        if reservation_id is not None:
            payload["res"] = str(reservation_id)
        if sales_contract_id is not None:
            payload["spa"] = str(sales_contract_id)

        token = jwt.encode(
            payload,
            self.settings.jwt_secret,
            algorithm=self.settings.jwt_algorithm,
        )

        row = PortalToken(
            buyer_id=buyer_id,
            reservation_id=reservation_id,
            sales_contract_id=sales_contract_id,
            jwt_id=jti,
            issued_at=now,
            expires_at=expires_at,
            issued_by_user_id=issued_by_user_id,
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return token, row

    def portal_url(self, token: str) -> str:
        """Build the customer-facing ``/buyer-portal/{token}`` URL."""
        return f"{self.settings.resolved_frontend_url}/buyer-portal/{token}"

    # ── Verification + IDOR guard ─────────────────────────────────────

    async def consume_token_atomic(
        self,
        jti: str,
        *,
        now: datetime,
    ) -> bool:
        """Single-use redemption — flip ``consumed_at`` NULL → ``now`` atomically.

        Implemented as ONE SQL UPDATE with ``WHERE consumed_at IS NULL``
        so concurrent verify requests on the same token cannot both
        succeed. The DB enforces the race-safety, not a Python
        read-then-write that could lose to a concurrent writer.

        Returns:
            ``True``  — row was previously unconsumed and is now marked
                        consumed (this caller "won" the race).
            ``False`` — row was already consumed (either by an earlier
                        call or by a concurrent winner).
        """
        stmt = (
            update(PortalToken)
            .where(PortalToken.jwt_id == jti)
            .where(PortalToken.consumed_at.is_(None))
            .values(consumed_at=now)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        # rowcount is 1 when the WHERE matched (we won), 0 otherwise
        # (the row was already consumed). Cast through int() to make
        # the boolean conversion explicit.
        return int(result.rowcount or 0) == 1  # type: ignore[union-attr]

    async def verify_token(
        self,
        token: str,
        *,
        client_ip: str | None = None,
        consume: bool = False,
    ) -> PortalContext:
        """Decode the JWT, check the revocation list, return resolved context.

        Updates ``last_used_at`` / ``last_used_ip`` as a side effect.
        Raises :class:`PortalTokenError` on any failure mode.

        Args:
            token: the raw JWT string from the URL / request body.
            client_ip: best-effort client IP captured for the audit row.
            consume: when ``True`` (only the ``/verify/`` route), the
                token is atomically marked consumed via a single SQL
                UPDATE WHERE consumed_at IS NULL. Already-consumed
                tokens raise ``PortalTokenError`` with code
                ``portal_token_already_used``. When ``False`` (every
                buyer-facing endpoint after the first verify), the
                token's consumed state is NOT checked — continued
                access uses the same JWT as a session token until
                its expiry or revocation, per the spec's
                "session JWT stays multi-use" constraint.
        """
        if not token or not isinstance(token, str):
            raise PortalTokenError()

        try:
            payload = jwt.decode(
                token,
                self.settings.jwt_secret,
                algorithms=[self.settings.jwt_algorithm],
            )
        except JWTError:
            raise PortalTokenError() from None

        # Scope claim is the single gate that separates portal tokens
        # from internal access / refresh / reset tokens. Without this,
        # a leaked internal access token (also signed by JWT_SECRET)
        # would unlock the portal of any buyer whose UUID happens to
        # equal the leaked user's UUID. With the scope check, the two
        # token families are non-fungible.
        scope = payload.get("scope")
        token_type = payload.get("type")
        if scope != PORTAL_TOKEN_SCOPE or token_type != "portal":
            raise PortalTokenError()

        jti = payload.get("jti")
        sub = payload.get("sub")
        if not jti or not sub:
            raise PortalTokenError()

        # DB lookup: revocation + audit. The unique index on jwt_id
        # makes this a single seek.
        stmt = select(PortalToken).where(PortalToken.jwt_id == str(jti))
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        if row is None:
            # Token was never registered (forged / from a different DB)
            # — reject the same way as expired so the caller can't
            # distinguish forged-but-DB-missing from genuinely expired.
            raise PortalTokenError()
        if row.revoked_at is not None:
            raise PortalTokenError()

        # Expiry: trust the JWT exp claim (already verified by jose)
        # AND cross-check the row's expires_at in case the row was
        # back-dated via direct DB edits during incident response.
        now = datetime.now(UTC)
        expires_at = row.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at < now:
            raise PortalTokenError()

        # buyer_id consistency: JWT sub MUST match the row's buyer_id.
        # Otherwise an attacker who learned a buyer's ``jti`` could
        # mint their own JWT with a different ``sub`` and slip past
        # the revocation check.
        if str(row.buyer_id) != str(sub):
            raise PortalTokenError()

        buyer = await self.session.get(Buyer, row.buyer_id)
        if buyer is None:
            # Buyer deleted after token issuance — equivalent to revoked.
            raise PortalTokenError()

        # Single-use redemption gate — only triggered by the /verify/
        # route (consume=True). If the magic-link was already redeemed,
        # the atomic UPDATE returns rowcount=0 and we surface the
        # distinct ``portal_token_already_used`` code so the frontend
        # can show "request a new login link" rather than "your link
        # expired". A concurrent verify of the same token is naturally
        # race-safe: exactly one UPDATE has its WHERE clause match,
        # the loser gets rowcount=0.
        if consume:
            won = await self.consume_token_atomic(jti=str(jti), now=now)
            if not won:
                raise PortalTokenError(PORTAL_TOKEN_ALREADY_USED_CODE)
            # Reflect the consumed_at on the cached row so the caller's
            # log lines / return value carry the up-to-date state.
            row.consumed_at = now

        reservation: Reservation | None = None
        if row.reservation_id is not None:
            reservation = await self.session.get(
                Reservation,
                row.reservation_id,
            )
        sales_contract: SalesContract | None = None
        if row.sales_contract_id is not None:
            sales_contract = await self.session.get(
                SalesContract,
                row.sales_contract_id,
            )

        # Best-effort audit write. Failures here MUST NOT block the
        # request — the buyer is already cryptographically verified and
        # losing a single audit timestamp is the lesser harm.
        try:
            row.last_used_at = now
            row.last_used_ip = (client_ip or "")[:64] or None
            await self.session.flush()
        except Exception:  # noqa: BLE001 — audit is best-effort
            logger.warning(
                "portal_token: failed to bump last_used_at for jti=%s",
                jti,
            )

        return PortalContext(
            token_row=row,
            buyer=buyer,
            reservation=reservation,
            sales_contract=sales_contract,
        )

    # ── Revocation ────────────────────────────────────────────────────

    async def revoke(self, token_id: uuid.UUID) -> bool:
        """Mark a token row revoked. Returns False if not found."""
        row = await self.session.get(PortalToken, token_id)
        if row is None:
            return False
        if row.revoked_at is None:
            row.revoked_at = datetime.now(UTC)
            await self.session.flush()
        return True

    # ── Listing / lookup for the manager UI ──────────────────────────

    async def list_active_for_buyer(
        self,
        buyer_id: uuid.UUID,
    ) -> list[PortalToken]:
        """Return non-revoked, non-expired tokens for a buyer."""
        now = datetime.now(UTC)
        stmt = (
            select(PortalToken)
            .where(PortalToken.buyer_id == buyer_id)
            .where(PortalToken.revoked_at.is_(None))
            .where(PortalToken.expires_at > now)
            .order_by(PortalToken.issued_at.desc())
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows)


__all__ = [
    "PortalContext",
    "PortalLinkService",
    "PortalTokenError",
    "PORTAL_TOKEN_ALREADY_USED_CODE",
    "PORTAL_TOKEN_SCOPE",
    "PORTAL_TOKEN_TTL_DAYS",
]
