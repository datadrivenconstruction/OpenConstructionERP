"""‌⁠‍User ORM models.

Tables:
    oe_users_user — registered users
    oe_users_api_key — API keys for programmatic access
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


class User(Base):
    """‌⁠‍Application user."""

    __tablename__ = "oe_users_user"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="editor")
    locale: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Tracks when the password was last changed. Tokens issued (`iat`) before
    # this timestamp are considered invalid — see dependencies.get_current_user.
    # Used to invalidate existing sessions on password change.
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Regional preferences
    timezone: Mapped[str] = mapped_column(String(50), nullable=False, default="UTC", server_default="UTC")
    measurement_system: Mapped[str] = mapped_column(
        String(20), nullable=False, default="metric", server_default="metric"
    )
    paper_size: Mapped[str] = mapped_column(String(10), nullable=False, default="A4", server_default="A4")
    number_format: Mapped[str] = mapped_column(
        String(20), nullable=False, default="1.234,56", server_default="1.234,56"
    )
    date_format: Mapped[str] = mapped_column(
        String(20), nullable=False, default="DD.MM.YYYY", server_default="DD.MM.YYYY"
    )
    currency_code: Mapped[str] = mapped_column(String(10), nullable=False, default="EUR", server_default="EUR")

    # Relationships
    api_keys: Mapped[list["APIKey"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<User {self.email} ({self.role})>"


class APIKey(Base):
    """‌⁠‍API key for programmatic access."""

    __tablename__ = "oe_users_api_key"

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    key_prefix: Mapped[str] = mapped_column(String(12), nullable=False)  # First 8 chars for identification
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    permissions: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )

    # Relationships
    user: Mapped[User] = relationship(back_populates="api_keys")

    def __repr__(self) -> str:
        return f"<APIKey {self.key_prefix}... ({self.name})>"
