# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""User ORM models.

Tables:
    oe_users_user - registered users
    oe_users_api_key - API keys for programmatic access
    oe_users_session - login sessions, so one can be revoked without the rest
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


class User(Base):
    """Application user."""

    __tablename__ = "oe_users_user"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="editor")
    locale: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Tracks when the password was last changed. Tokens issued (`iat`) before
    # this timestamp are considered invalid - see dependencies.get_current_user.
    # Used to invalidate existing sessions on password change.
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # GDPR Art. 17 erasure marker. When the account holder self-erases via
    # DELETE /api/v1/users/me the row is anonymised in place (PII nulled,
    # password hash invalidated, is_active flipped False) rather than hard
    # deleted, so foreign-key references (projects, activity, audit) survive.
    # This timestamp records when that happened; NULL means a live account.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
    # "auto" means the paper size follows the country of the project the
    # document belongs to, resolved by app.core.paper_size. The old default of
    # "A4" was not a neutral start: it is a real choice a European user makes
    # on purpose, so "nobody chose" and "chose A4" were the same row and no
    # generator could have told a US account apart from a German one even once
    # it started reading this column. server_default stays "A4" for the reason
    # spelled out under date_format below - changing it alters the table DDL
    # and needs a migration for no functional gain, because ORM inserts always
    # supply the Python-side default. Accounts created before this still carry
    # "A4" and keep rendering A4, which is what they rendered yesterday.
    paper_size: Mapped[str] = mapped_column(String(10), nullable=False, default="auto", server_default="A4")
    # "auto" means numbers follow the interface language, the same neutral
    # start the date_format below already takes. The old default handed every
    # new account in the world German grouping, and because the column is
    # free-form nothing downstream could tell that seeded "1.234,56" apart from
    # a reader who deliberately picked German. server_default stays "1.234,56"
    # for the reason spelled out under date_format: changing it alters the
    # table DDL and needs a migration for no functional gain, because ORM
    # inserts always supply the Python-side default. Accounts created before
    # this still carry "1.234,56"; the frontend store treats that exact value
    # as "never chose" so their rendering does not change.
    number_format: Mapped[str] = mapped_column(String(20), nullable=False, default="auto", server_default="1.234,56")
    # "auto" means the UI follows the interface language when rendering dates.
    # New accounts start there so the stored value is only ever an order the
    # user actually picked. server_default stays "DD.MM.YYYY" for the same
    # reason as currency_code below - changing it would alter the table DDL and
    # require a migration for no functional gain, because ORM inserts always
    # supply the Python-side default. Accounts created before the automatic
    # option still carry "DD.MM.YYYY"; the frontend store treats that exact
    # value as "never chose" so their rendering does not change.
    date_format: Mapped[str] = mapped_column(String(20), nullable=False, default="auto", server_default="DD.MM.YYYY")
    # No EUR bias for new accounts: empty string means "not chosen yet" and
    # the UI falls back to the project currency / local preference store.
    # server_default stays "EUR" on purpose - changing it would alter the
    # table DDL and require an alembic migration for zero functional gain
    # (ORM inserts always supply the Python-side default).
    currency_code: Mapped[str] = mapped_column(String(10), nullable=False, default="", server_default="EUR")

    # Relationships
    api_keys: Mapped[list["APIKey"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<User {self.email} ({self.role})>"


class APIKey(Base):
    """API key for programmatic access."""

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


class UserSession(Base):
    """One login session, named by the ``sid`` claim its tokens carry.

    This row is what makes revoking a single session expressible. Before it,
    every token carried a ``jti`` that nothing read, so an issued credential
    had a name but no record, and the only way to end one session was to
    rotate the signing secret, which ends everybody's. Revocation now has
    something to point at: the access token and the refresh token minted
    together carry the same ``sid``, so refusing this row refuses the pair and
    every pair rotated out of it.

    Revocation sets ``revoked_at``; it never deletes the row. That is the
    whole reason a "revoked" column exists rather than just a missing row: a
    token whose session cannot be found is honoured (see
    ``reject_revoked_session`` in ``app.dependencies`` for why), so deleting
    the row would *undo* the revocation instead of enforcing it. Pruning is
    therefore only ever allowed to touch rows already past ``expires_at``,
    which no live credential can be pointing at.
    """

    __tablename__ = "oe_users_session"

    # The token claim, ``uuid4().hex`` (32 chars); sized with headroom so a
    # future change of generator does not need a migration. Unique because it
    # names one session, indexed because every authenticated request looks a
    # token up by it.
    sid: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The refresh horizon, not the access horizon: the session stays alive as
    # long as its refresh token can still mint, which is what a person means
    # by "I am still logged in on that laptop". Also the pruning boundary.
    # Indexed here as well as in the migration so the two descriptions of this
    # table stay identical; declared in only one of them, the next
    # autogenerated revision would propose dropping the index.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Written on refresh rather than on every request: it exists so a person
    # can recognise which session to end, and paying a write on each
    # authenticated call to sharpen that timestamp is not worth it.
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        state = "revoked" if self.revoked_at else "active"
        return f"<UserSession {self.sid[:8]}... ({state})>"
