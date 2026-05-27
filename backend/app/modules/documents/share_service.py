"""‌⁠‍Document share-link service — business logic for password-protected
public share URLs.

Stateless service layer mirroring the pattern in
:mod:`app.modules.documents.service`.

Public surface:
    * :func:`create_share_link` — mint a token for a document
    * :func:`get_share_link_public` — what an unauthenticated
      recipient sees (filename + flags only — no owner / count leak)
    * :func:`access_share_link` — verify password, bump count,
      return the authenticated download URL
    * :func:`list_share_links_for_document` — owner-only inventory
    * :func:`revoke_share_link` — owner-only soft delete

All read paths treat ``revoked=True`` and ``now > expires_at`` the
same as "unknown token": 404. This keeps enumeration symmetric
(attacker cannot distinguish "wrong token" from "expired token" from
"revoked token").
"""

from __future__ import annotations

import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import get_locale
from app.core.validation.messages import translate
from app.modules.documents.models import Document
from app.modules.documents.share_models import DocumentShareLink

logger = logging.getLogger(__name__)

# Length of the URL-safe token. ``secrets.token_urlsafe(24)`` yields a
# ~32-char base64url string; long enough that brute-force enumeration of
# the search space is computationally infeasible.
_TOKEN_BYTES = 24

# bcrypt cost — matches the existing user-password rounds in
# ``app.modules.users.service.hash_password``.
_BCRYPT_ROUNDS = 12

# R7 audit: server-side fallback when the caller omits ``expires_in_days``.
# Previously a missing value meant "never expires" — a leaked URL would
# live forever absent a manual revoke call. Defaulting to 30 days caps
# the blast radius of an unrevoked leak to a single month while still
# leaving plenty of breathing room for the common "share with the GC for
# this stage of the project" use case. Callers that genuinely need
# longer can opt in explicitly (capped at 365 days by the schema).
_DEFAULT_EXPIRES_IN_DAYS = 30


def _hash_password(password: str) -> str:
    """‌⁠‍Bcrypt-hash a share-link password."""
    salt = bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def _verify_password(plain: str, hashed: str) -> bool:
    """‌⁠‍Verify a recipient-supplied password against the stored hash."""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        # Malformed hash (legacy / hand-edited row) → treat as no match
        # rather than crash the request.
        return False


def _now() -> datetime:
    """Timezone-aware "now" — used for expiry comparisons."""
    return datetime.now(tz=UTC)


def _is_expired(link: DocumentShareLink, *, at: datetime | None = None) -> bool:
    """Return True when the link has an expiry that has already passed."""
    if link.expires_at is None:
        return False
    at = at or _now()
    expires_at = link.expires_at
    # PostgreSQL stores tz-aware; SQLite returns naive UTC. Normalize both
    # sides so the comparison is safe regardless of backend.
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    return at >= expires_at


def _build_public_url(token: str) -> str:
    """Construct the relative public share URL recipients open.

    Returned as a path (no host) so the frontend can prepend its own
    origin. The route is mounted under ``/share/{token}`` in the SPA.
    """
    return f"/share/{token}"


async def _load_document(
    session: AsyncSession,
    document_id: uuid.UUID,
) -> Document:
    """Fetch a :class:`Document` or raise 404."""
    stmt = select(Document).where(Document.id == document_id)
    doc = (await session.execute(stmt)).scalar_one_or_none()
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=translate("errors.document_not_found", locale=get_locale()),
        )
    return doc


async def _load_link_by_token(
    session: AsyncSession,
    token: str,
) -> DocumentShareLink | None:
    """Fetch an active share link by token, or ``None``.

    Returns ``None`` (not raising) so callers can decide whether to
    map missing/revoked/expired to 404 themselves.
    """
    stmt = select(DocumentShareLink).where(DocumentShareLink.token == token)
    return (await session.execute(stmt)).scalar_one_or_none()


async def create_share_link(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    created_by: uuid.UUID,
    password: str | None,
    expires_in_days: int | None,
) -> DocumentShareLink:
    """Mint a new share link for ``document_id``.

    The caller MUST have already verified that ``created_by`` owns
    the document's project (use
    :func:`app.dependencies.verify_project_access` in the router).

    The session is flushed but NOT committed — the surrounding
    request transaction owns the commit, matching the existing
    documents-module pattern.
    """
    # Ensure the document exists. This also surfaces a clean 404 to the
    # router if the document was deleted between the access check and
    # the call.
    await _load_document(session, document_id)

    token = secrets.token_urlsafe(_TOKEN_BYTES)
    pw_hash: str | None = None
    if password:
        pw_hash = _hash_password(password)

    # R7 audit: never mint a never-expires link. Apply the 30-day
    # default when the caller omits ``expires_in_days`` so a leaked URL
    # is naturally bounded.
    effective_days = expires_in_days if expires_in_days is not None else _DEFAULT_EXPIRES_IN_DAYS
    expires_at: datetime = _now() + timedelta(days=effective_days)

    row = DocumentShareLink(
        document_id=document_id,
        token=token,
        password_hash=pw_hash,
        expires_at=expires_at,
        created_by=created_by,
        download_count=0,
        revoked=False,
    )
    session.add(row)
    await session.flush()
    logger.info(
        "Minted share link for document=%s by user=%s (password=%s, expires=%s)",
        document_id,
        created_by,
        bool(pw_hash),
        expires_at,
    )
    return row


async def get_share_link_public(
    session: AsyncSession,
    token: str,
) -> tuple[DocumentShareLink, Document]:
    """Return the link + its document, or raise 404.

    Used by the public ``GET /share-links/{token}/`` probe. Revoked
    links 404 — expired links return normally (the caller surfaces
    ``expired=True``) so the recipient sees a useful message rather
    than a bare not-found page.
    """
    link = await _load_link_by_token(session, token)
    if link is None or link.revoked:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Share link not found",
        )
    doc = await _load_document(session, link.document_id)
    return link, doc


async def access_share_link(
    session: AsyncSession,
    *,
    token: str,
    password: str | None,
) -> tuple[DocumentShareLink, Document]:
    """Verify password and bump ``download_count``.

    Raises:
        HTTPException 404: link missing, revoked, or expired
        HTTPException 401: password required but absent/wrong
    """
    link = await _load_link_by_token(session, token)
    if link is None or link.revoked:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Share link not found",
        )
    if _is_expired(link):
        # Expired = no longer accessible. 404 keeps the surface symmetric
        # with revoked / unknown tokens.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Share link not found",
        )

    if link.password_hash:
        if not password or not _verify_password(password, link.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid password",
            )

    # Bump counter. Done as a Python-side increment + flush rather than
    # a SQL UPDATE so the returned row reflects the new count without a
    # second round trip.
    link.download_count = (link.download_count or 0) + 1
    session.add(link)
    await session.flush()

    doc = await _load_document(session, link.document_id)
    return link, doc


async def list_share_links_for_document(
    session: AsyncSession,
    document_id: uuid.UUID,
) -> list[DocumentShareLink]:
    """Return all non-revoked links for a document, newest-first.

    Owner-only — the router enforces project access before calling.
    """
    stmt = (
        select(DocumentShareLink)
        .where(
            DocumentShareLink.document_id == document_id,
            DocumentShareLink.revoked.is_(False),
        )
        .order_by(DocumentShareLink.created_at.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def revoke_share_link(
    session: AsyncSession,
    *,
    link_id: uuid.UUID,
    document_id: uuid.UUID,
) -> None:
    """Soft-delete a link by id.

    ``document_id`` is supplied by the router (taken from the URL
    path) so we can refuse to revoke a link that does not belong to
    the document the caller already proved access to — prevents
    cross-document IDOR via a stale link id.
    """
    stmt = select(DocumentShareLink).where(DocumentShareLink.id == link_id)
    link = (await session.execute(stmt)).scalar_one_or_none()
    if link is None or link.document_id != document_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Share link not found",
        )
    link.revoked = True
    session.add(link)
    await session.flush()
    logger.info("Revoked share link %s for document=%s", link_id, document_id)
