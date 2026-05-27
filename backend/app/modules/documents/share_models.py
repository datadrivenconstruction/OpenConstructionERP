"""‌⁠‍Document share-link ORM models.

Tables:
    oe_documents_share_link — public, optionally password-protected
                              share tokens that grant a recipient
                              one-click download access to a single
                              :class:`Document`.

Workflow:
    1. Owner POSTs ``/{id}/share-links/`` with an optional password
       + expiry. Server mints a 32-char URL-safe token, stores a
       bcrypt hash of the password (if any), and returns the public
       URL.
    2. Recipient opens ``/share/{token}`` (frontend). Frontend calls
       ``GET /share-links/{token}/`` to learn whether a password is
       required and whether the link has expired.
    3. Recipient submits the password to
       ``POST /share-links/{token}/access/``. On success the server
       returns the authenticated ``download_url`` and bumps
       ``download_count``.
    4. Owner can revoke a link any time via DELETE — once revoked
       the token returns 404 to keep enumeration costs symmetric.

A dedicated file (rather than tacking onto ``models.py``) keeps the
sharing surface easy to grep for and avoids growing the already-busy
``models`` module. ``models.py`` re-imports the symbol at the bottom
so the alembic autogenerate / module loader still discover the
metadata.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class DocumentShareLink(Base):
    """‌⁠‍Public download token for a single :class:`Document`.

    ``token`` is the URL segment recipients use (32-char URL-safe
    base64 from :func:`secrets.token_urlsafe`). It is indexed
    ``unique=True`` so the public lookup is a single index probe.

    ``password_hash`` is a bcrypt hash (cost 12) of the optional
    password — ``None`` means the link is open. Storing a hash rather
    than the plaintext means a leaked DB still requires a brute-force
    crack per link.

    ``expires_at`` is optional. When set, the public-facing read /
    access endpoints treat ``now > expires_at`` as 404 (same surface
    as revoke / unknown token, by design — leaking "expired vs
    revoked" lets attackers enumerate valid past tokens).

    ``download_count`` is incremented on every successful access. It
    is informational only — the link is not single-use.

    ``revoked`` is set by the owner via DELETE. We never hard-delete
    so the audit row + count survive cleanup; the index covers the
    "active & not expired" lookup with no extra scan.
    """

    __tablename__ = "oe_documents_share_link"

    __table_args__ = (
        Index(
            "ix_documents_share_link_document_id",
            "document_id",
        ),
        Index(
            "ix_documents_share_link_revoked",
            "revoked",
        ),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_documents_document.id", ondelete="CASCADE"),
        nullable=False,
    )
    token: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
    )
    password_hash: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        default=None,
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="CASCADE"),
        nullable=False,
    )
    download_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    revoked: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )

    def __repr__(self) -> str:  # pragma: no cover — debug helper
        return f"<DocumentShareLink token={self.token[:8]}… doc={self.document_id} revoked={self.revoked}>"
