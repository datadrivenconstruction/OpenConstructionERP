# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍Customer & Partner Portal — business logic.

Pure-function helpers (token gen, hashing, permission predicate) plus a
:class:`PortalService` that wraps the repositories with idempotent operations
and emits cross-module events (``portal.user.invited``,
``portal.user.session_started``, ``portal.notification.created``).

Magic-link and session tokens are stored as ``sha256(token)`` hex digests
ONLY. Plaintext is shown to the inviter exactly once (response to
``POST /admin/users/invite``) and to the portal user exactly once (response
to ``POST /auth/consume``). All in-DB comparisons go through
:func:`hmac.compare_digest`.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.modules.portal.models import (
    PortalAccessRule,
    PortalDocumentAccessLog,
    PortalMagicLink,
    PortalNotification,
    PortalSession,
    PortalUser,
)
from app.modules.portal.repository import (
    PortalAccessRuleRepository,
    PortalDocumentAccessLogRepository,
    PortalMagicLinkRepository,
    PortalNotificationRepository,
    PortalSessionRepository,
    PortalUserRepository,
)

logger = logging.getLogger(__name__)

# ── Defaults (override via env later) ─────────────────────────────────────
MAGIC_LINK_TTL = timedelta(hours=24)
SESSION_TTL = timedelta(days=7)

# Permission rank — higher number satisfies all lower-number requirements.
_PERMISSION_RANK: dict[str, int] = {
    "view": 1,
    "comment": 2,
    "submit": 3,
    "sign": 4,
}


# ── Pure helpers ──────────────────────────────────────────────────────────


def now_utc() -> datetime:
    """‌⁠‍Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


def generate_token() -> str:
    """‌⁠‍Generate a random 64-hex-char token (32 bytes of entropy).

    Used for both magic-link tokens and session tokens. The plaintext is
    shown to the caller exactly once — only ``hash_token(plain)`` is stored.
    """
    return secrets.token_hex(32)


def hash_token(plain: str) -> str:
    """Hash a token with sha256 and return the hex digest."""
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    """Constant-time string comparison via :func:`hmac.compare_digest`."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def _ensure_aware(dt: datetime | None) -> datetime | None:
    """Coerce naive datetimes coming back from SQLite to UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _permission_satisfies(granted: str, required: str) -> bool:
    """Return ``True`` iff ``granted`` is at least as powerful as ``required``."""
    return _PERMISSION_RANK.get(granted, 0) >= _PERMISSION_RANK.get(required, 0)


# ── Service ───────────────────────────────────────────────────────────────


class PortalService:
    """Business logic for portal users, access rules, sessions, magic-links,
    notifications, and document-access logs.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.user_repo = PortalUserRepository(session)
        self.rule_repo = PortalAccessRuleRepository(session)
        self.session_repo = PortalSessionRepository(session)
        self.magic_repo = PortalMagicLinkRepository(session)
        self.notif_repo = PortalNotificationRepository(session)
        self.audit_repo = PortalDocumentAccessLogRepository(session)

    # ── Users / invitations ───────────────────────────────────────────────

    async def invite_portal_user(
        self,
        email: str,
        role: str,
        language: str = "en",
        *,
        full_name: str = "",
        timezone_: str = "UTC",
        granted_by: str | None = None,
        redirect_path: str | None = None,
        created_ip: str | None = None,
    ) -> tuple[PortalUser, str, datetime]:
        """Idempotent invite.

        If ``email`` already exists, the existing user is reused and a fresh
        magic-link minted. Returns ``(user, plain_token, link_expires_at)``.
        The plaintext token is the only chance to email it to the user;
        only the sha256 hash is persisted.
        """
        normalized = email.strip().lower()
        existing = await self.user_repo.get_by_email(normalized)
        now = now_utc()

        if existing is None:
            user = PortalUser(
                email=normalized,
                full_name=full_name,
                portal_role=role,
                language=language,
                timezone=timezone_,
                status="invited",
                invited_at=now,
            )
            user = await self.user_repo.create(user)
            created = True
        else:
            user = existing
            # Refresh the invitation window. Don't downgrade a confirmed
            # account back to "invited" — that would break access checks.
            if user.status == "expired":
                await self.user_repo.update_fields(user.id, status="invited")
                user.status = "invited"
            created = False

        plain = generate_token()
        link = PortalMagicLink(
            portal_user_id=user.id,
            token_hash=hash_token(plain),
            purpose="login",
            redirect_path=redirect_path,
            expires_at=now + MAGIC_LINK_TTL,
            created_ip=created_ip,
        )
        link = await self.magic_repo.create(link)

        event_bus.publish_detached(
            "portal.user.invited",
            {
                "portal_user_id": str(user.id),
                "email": user.email,
                "portal_role": user.portal_role,
                "created": created,
                "granted_by": granted_by,
            },
            source_module="portal",
        )
        logger.info(
            "Portal user invited: %s (%s) created=%s",
            user.email,
            user.portal_role,
            created,
        )
        return user, plain, link.expires_at

    async def get_portal_user(self, user_id: uuid.UUID) -> PortalUser:
        user = await self.user_repo.get_by_id(user_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Portal user not found",
            )
        return user

    async def list_portal_users(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        portal_role: str | None = None,
        status_filter: str | None = None,
    ) -> tuple[list[PortalUser], int]:
        return await self.user_repo.list_users(
            offset=offset,
            limit=limit,
            portal_role=portal_role,
            status=status_filter,
        )

    async def patch_portal_user(
        self,
        user_id: uuid.UUID,
        **fields: Any,
    ) -> PortalUser:
        user = await self.get_portal_user(user_id)
        cleaned: dict[str, Any] = {k: v for k, v in fields.items() if v is not None}
        if cleaned:
            await self.user_repo.update_fields(user_id, **cleaned)
            await self.session.refresh(user)
        return user

    # ── Magic links / sessions ────────────────────────────────────────────

    async def request_magic_link(
        self,
        email: str,
        *,
        redirect_path: str | None = None,
        created_ip: str | None = None,
    ) -> tuple[PortalUser, str, datetime] | None:
        """Mint a new login magic-link for an existing portal user.

        Returns ``None`` if the email is not registered or the account is not
        in a state that accepts logins (suspended / expired). Callers MUST
        always respond 202 regardless of the return value to avoid
        email-enumeration leaks.
        """
        normalized = email.strip().lower()
        user = await self.user_repo.get_by_email(normalized)
        if user is None or user.status in ("suspended", "expired"):
            return None

        plain = generate_token()
        now = now_utc()
        link = PortalMagicLink(
            portal_user_id=user.id,
            token_hash=hash_token(plain),
            purpose="login",
            redirect_path=redirect_path,
            expires_at=now + MAGIC_LINK_TTL,
            created_ip=created_ip,
        )
        link = await self.magic_repo.create(link)
        return user, plain, link.expires_at

    async def consume_magic_link(
        self,
        token: str,
        *,
        purpose: str = "login",
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[PortalUser, PortalSession, str, datetime]:
        """Consume a one-time magic link and open a portal session.

        Raises HTTPException 400 on expired / consumed / wrong-purpose tokens
        and 401 on unknown tokens (no plaintext-token comparison hits the DB
        — only the sha256 hash).

        Returns ``(user, session, plain_session_token, session_expires_at)``.
        """
        token_h = hash_token(token)
        link = await self.magic_repo.get_by_token_hash(token_h)
        if link is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid magic link",
            )
        # Constant-time hash check (`get_by_token_hash` matched by equality
        # but we still compare via `compare_digest` to keep the path uniform
        # against any future change to the lookup that loosens equality).
        if not constant_time_equals(link.token_hash, token_h):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid magic link",
            )
        if link.purpose != purpose:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Wrong magic link purpose",
            )
        if link.consumed_at is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Magic link already consumed",
            )
        expires_at = _ensure_aware(link.expires_at)
        now = now_utc()
        if expires_at is not None and expires_at < now:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Magic link expired",
            )

        user = await self.user_repo.get_by_id(link.portal_user_id)
        if user is None or user.status in ("suspended", "expired"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Portal account is not active",
            )

        # Snapshot scalars BEFORE any repo write. Every repo's
        # ``update_fields`` ends with ``session.expire_all()``, which detaches
        # *all* attributes on every loaded ORM instance — including ``user``
        # and ``link``. Touching ``user.status`` / ``user.id`` after that
        # point triggers an illegal *synchronous* lazy-load on the async
        # session (MissingGreenlet → 500). The PKs/status are stable, so
        # capture them here and operate on the locals afterwards.
        link_id = link.id
        user_id = user.id
        user_status = user.status

        # Mark link consumed.
        await self.magic_repo.update_fields(link_id, consumed_at=now)

        # Activate first-login users.
        if user_status == "invited":
            await self.user_repo.update_fields(
                user_id,
                status="active",
                last_login_at=now,
            )
        else:
            await self.user_repo.update_fields(user_id, last_login_at=now)

        # Open session.
        plain_session = generate_token()
        sess = PortalSession(
            portal_user_id=user_id,
            session_token_hash=hash_token(plain_session),
            ip_address=ip_address,
            user_agent=user_agent,
            started_at=now,
            last_seen_at=now,
            expires_at=now + SESSION_TTL,
        )
        sess = await self.session_repo.create(sess)
        # Snapshot the freshly-flushed session fields before the next
        # expire_all() (refresh below) can detach them.
        session_id = sess.id
        session_expires_at = sess.expires_at

        # Re-load ``user`` as a live, fully-populated instance — the router
        # serialises it via ``PortalUserResponse.model_validate(user)`` and
        # the expire_all() chain above left every attribute detached.
        await self.session.refresh(user)

        event_bus.publish_detached(
            "portal.user.session_started",
            {
                "portal_user_id": str(user_id),
                "session_id": str(session_id),
                "ip_address": ip_address,
            },
            source_module="portal",
        )
        return user, sess, plain_session, session_expires_at

    async def verify_session(self, session_token: str) -> PortalUser | None:
        """Validate a session token. Returns the owning user or ``None``.

        Touches ``last_seen_at`` on success.
        """
        if not session_token:
            return None
        token_h = hash_token(session_token)
        sess = await self.session_repo.get_by_token_hash(token_h)
        if sess is None:
            return None
        if sess.revoked_at is not None:
            return None
        expires_at = _ensure_aware(sess.expires_at)
        now = now_utc()
        if expires_at is not None and expires_at < now:
            return None
        if not constant_time_equals(sess.session_token_hash, token_h):
            return None

        user = await self.user_repo.get_by_id(sess.portal_user_id)
        if user is None or user.status in ("suspended", "expired"):
            return None

        # session_repo.update_fields() ends with session.expire_all(), which
        # detaches *every* attribute on the already-loaded ``user``. The
        # returned object is consumed by the portal-session dependency and its
        # route handlers (``user.id``, ``PortalUserResponse.model_validate``);
        # touching an expired attribute later triggers an illegal synchronous
        # lazy-load on the async session (MissingGreenlet → 500). Snapshot the
        # PK across the expiring write, then re-load ``user`` as a live,
        # fully-populated instance.
        user_id = user.id
        await self.session_repo.update_fields(sess.id, last_seen_at=now)
        user = await self.user_repo.get_by_id(user_id)
        return user

    async def revoke_session(self, session_token: str) -> bool:
        """Revoke a specific session by its bearer token. Returns ``True``
        if a row was changed.
        """
        if not session_token:
            return False
        token_h = hash_token(session_token)
        sess = await self.session_repo.get_by_token_hash(token_h)
        if sess is None or sess.revoked_at is not None:
            return False
        await self.session_repo.update_fields(sess.id, revoked_at=now_utc())
        return True

    async def revoke_all_for_user(self, portal_user_id: uuid.UUID) -> int:
        """Revoke every active session for a portal user."""
        return await self.session_repo.revoke_all_for_user(
            portal_user_id,
            revoked_at=now_utc(),
        )

    # ── Access rules / RLS ────────────────────────────────────────────────

    async def grant_access(
        self,
        portal_user_id: uuid.UUID,
        resource_type: str,
        resource_id: uuid.UUID,
        permission: str = "view",
        *,
        granted_by: str | None = None,
        expires_at: datetime | None = None,
    ) -> PortalAccessRule:
        """Idempotent upsert of an access rule."""
        existing = await self.rule_repo.get_one(
            portal_user_id,
            resource_type,
            resource_id,
        )
        now = now_utc()
        if existing is not None:
            fields: dict[str, Any] = {
                "permission": permission,
                "granted_at": now,
                "granted_by": granted_by,
                "expires_at": expires_at,
            }
            await self.rule_repo.update_fields(existing.id, **fields)
            await self.session.refresh(existing)
            return existing

        rule = PortalAccessRule(
            portal_user_id=portal_user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            permission=permission,
            granted_at=now,
            granted_by=granted_by,
            expires_at=expires_at,
        )
        return await self.rule_repo.create(rule)

    async def revoke_access(
        self,
        portal_user_id: uuid.UUID,
        resource_type: str,
        resource_id: uuid.UUID,
    ) -> None:
        await self.rule_repo.delete_match(
            portal_user_id,
            resource_type,
            resource_id,
        )

    async def revoke_access_rule(self, rule_id: uuid.UUID) -> None:
        await self.rule_repo.delete(rule_id)

    async def list_access_rules(
        self,
        *,
        portal_user_id: uuid.UUID | None = None,
        resource_type: str | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> tuple[list[PortalAccessRule], int]:
        """Admin-facing paginated list of access rules.

        Backs ``GET /admin/access-rules`` so the access-rules table is
        durable across reloads instead of only reflecting grants made in the
        current browser session.
        """
        return await self.rule_repo.list_rules(
            portal_user_id=portal_user_id,
            resource_type=resource_type,
            offset=offset,
            limit=limit,
        )

    async def list_accessible_resources(
        self,
        portal_user_id: uuid.UUID,
        resource_type: str,
    ) -> list[uuid.UUID]:
        """Return resource IDs of ``resource_type`` the user can currently see."""
        rules = await self.rule_repo.list_for_user(
            portal_user_id,
            resource_type=resource_type,
        )
        now = now_utc()
        out: list[uuid.UUID] = []
        for r in rules:
            expires_at = _ensure_aware(r.expires_at)
            if expires_at is not None and expires_at < now:
                continue
            out.append(r.resource_id)
        return out

    async def enforce_rls(
        self,
        portal_user_id: uuid.UUID,
        resource_type: str,
        resource_id: uuid.UUID,
        required: str = "view",
    ) -> bool:
        """Central RLS predicate.

        Returns ``True`` iff a non-expired :class:`PortalAccessRule` exists
        granting at least ``required`` permission on the target resource.
        """
        rule = await self.rule_repo.get_one(
            portal_user_id,
            resource_type,
            resource_id,
        )
        if rule is None:
            return False
        expires_at = _ensure_aware(rule.expires_at)
        if expires_at is not None and expires_at < now_utc():
            return False
        return _permission_satisfies(rule.permission, required)

    # ── Document access log ───────────────────────────────────────────────

    async def record_document_access(
        self,
        portal_user_id: uuid.UUID,
        document_type: str,
        document_id: uuid.UUID,
        action: str = "view",
        *,
        ip_address: str | None = None,
    ) -> PortalDocumentAccessLog:
        entry = PortalDocumentAccessLog(
            portal_user_id=portal_user_id,
            document_type=document_type,
            document_id=document_id,
            action=action,
            occurred_at=now_utc(),
            ip_address=ip_address,
        )
        return await self.audit_repo.create(entry)

    async def list_document_access(
        self,
        *,
        portal_user_id: uuid.UUID | None = None,
        document_type: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[PortalDocumentAccessLog], int]:
        return await self.audit_repo.list_entries(
            portal_user_id=portal_user_id,
            document_type=document_type,
            offset=offset,
            limit=limit,
        )

    # ── Notifications ─────────────────────────────────────────────────────

    async def notify(
        self,
        portal_user_id: uuid.UUID,
        kind: str,
        title: str,
        body: str = "",
        *,
        link_path: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> PortalNotification:
        notif = PortalNotification(
            portal_user_id=portal_user_id,
            kind=kind,
            title=title,
            body=body,
            link_path=link_path,
            payload=payload or {},
        )
        notif = await self.notif_repo.create(notif)

        event_bus.publish_detached(
            "portal.notification.created",
            {
                "notification_id": str(notif.id),
                "portal_user_id": str(portal_user_id),
                "kind": kind,
                "title": title,
            },
            source_module="portal",
        )
        return notif

    async def list_notifications(
        self,
        portal_user_id: uuid.UUID,
        *,
        unread_only: bool = False,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[PortalNotification], int, int]:
        items, total = await self.notif_repo.list_for_user(
            portal_user_id,
            unread_only=unread_only,
            offset=offset,
            limit=limit,
        )
        unread = await self.notif_repo.unread_count(portal_user_id)
        return items, total, unread

    async def mark_notification_read(
        self,
        notification_id: uuid.UUID,
        portal_user_id: uuid.UUID,
    ) -> PortalNotification:
        notif = await self.notif_repo.get_by_id(notification_id)
        if notif is None or notif.portal_user_id != portal_user_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notification not found",
            )
        if notif.read_at is None:
            await self.notif_repo.update_fields(notif.id, read_at=now_utc())
            await self.session.refresh(notif)
        return notif


# ── Re-exports for cross-module use ───────────────────────────────────────


async def enforce_rls(
    session: AsyncSession,
    portal_user_id: uuid.UUID,
    resource_type: str,
    resource_id: uuid.UUID,
    required: str = "view",
) -> bool:
    """Free-function wrapper around :meth:`PortalService.enforce_rls` for
    cross-module use (other modules importing this directly).
    """
    svc = PortalService(session)
    return await svc.enforce_rls(
        portal_user_id,
        resource_type,
        resource_id,
        required,
    )


async def list_accessible_resources(
    session: AsyncSession,
    portal_user_id: uuid.UUID,
    resource_type: str,
) -> list[uuid.UUID]:
    """Free-function wrapper around :meth:`PortalService.list_accessible_resources`
    for cross-module use.
    """
    svc = PortalService(session)
    return await svc.list_accessible_resources(portal_user_id, resource_type)


__all__ = [
    "MAGIC_LINK_TTL",
    "SESSION_TTL",
    "PortalService",
    "constant_time_equals",
    "enforce_rls",
    "generate_token",
    "hash_token",
    "list_accessible_resources",
    "now_utc",
]
