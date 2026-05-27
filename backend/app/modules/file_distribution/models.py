# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File Distribution ORM models.

Tables:
    oe_file_distribution_list         — named recipient group
    oe_file_distribution_member       — one recipient in a list
    oe_file_distribution_subscription — per-project/kind subscription

Cross-project search has NO table of its own: it reads the existing
``oe_documents_document`` / ``oe_documents_sheet`` / ``oe_documents_photo``
tables (and, when present, ``oe_file_search_index``) directly.
``id`` / ``created_at`` / ``updated_at`` come from
:class:`app.database.Base`.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


class FileDistributionList(Base):
    """A named recipient group authored by ``owner_id``.

    ``project_id`` is nullable — NULL means a personal list usable on
    any project the owner can access (e.g. "External Consultants").
    When ``is_shared`` is true and ``project_id`` is set, project
    members can re-use the list (read + send to) but never edit it.
    """

    __tablename__ = "oe_file_distribution_list"
    __table_args__ = (
        Index("ix_file_distribution_list_project", "project_id"),
        Index("ix_file_distribution_list_owner", "owner_id"),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=True,
        default=None,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    is_shared: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )

    members: Mapped[list[FileDistributionMember]] = relationship(
        back_populates="distribution_list",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:  # pragma: no cover — debug helper
        return (
            f"<FileDistributionList {self.name!r} owner={self.owner_id} "
            f"project={self.project_id} shared={self.is_shared}>"
        )


class FileDistributionMember(Base):
    """One recipient in a :class:`FileDistributionList`.

    ``email`` is the canonical key — a member is identified by the
    address messages will go to. ``display_name`` is a free-text label
    so the list reads naturally ("Lena Schmidt — Structural Reviewer")
    even when the address is a shared inbox. ``role`` is an optional
    transmittal-style label (``for_review`` / ``fyi`` / ``for_construction``)
    so the same list can be used to drive review packages.
    """

    __tablename__ = "oe_file_distribution_member"
    __table_args__ = (
        UniqueConstraint(
            "list_id",
            "email",
            name="uq_file_distribution_member_list_email",
        ),
        Index("ix_file_distribution_member_list", "list_id"),
    )

    list_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_file_distribution_list.id", ondelete="CASCADE"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        default=None,
    )
    role: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        default=None,
    )

    distribution_list: Mapped[FileDistributionList] = relationship(
        back_populates="members",
    )

    def __repr__(self) -> str:  # pragma: no cover — debug helper
        return f"<FileDistributionMember {self.email} list={self.list_id}>"


class FileDistributionSubscription(Base):
    """Per-project/kind subscription.

    A subscriber (an internal user id or a free-form external email)
    is auto-notified when a file of ``file_kind`` is created / updated
    / deleted in ``project_id``. ``file_kind`` is a free-text key
    matching the file-manager's kinds (``document``, ``sheet``,
    ``bim_model`` …); ``"*"`` matches every kind.
    """

    __tablename__ = "oe_file_distribution_subscription"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "file_kind",
            "subscriber_email",
            name="uq_file_distribution_subscription_proj_kind_email",
        ),
        Index(
            "ix_file_distribution_subscription_project_kind",
            "project_id",
            "file_kind",
        ),
        Index(
            "ix_file_distribution_subscription_user",
            "subscriber_user_id",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
    )
    file_kind: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="*",
        server_default="*",
    )
    subscriber_email: Mapped[str] = mapped_column(String(255), nullable=False)
    # When the subscriber is an internal user we record the user_id so a
    # password reset / deactivation can cascade-clean their subscriptions.
    # External-only subscribers (vendors, clients) keep this NULL.
    subscriber_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="CASCADE"),
        nullable=True,
        default=None,
    )
    notify_on: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default='["created","updated","deleted"]',
    )
    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
    )

    def __repr__(self) -> str:  # pragma: no cover — debug helper
        return (
            f"<FileDistributionSubscription project={self.project_id} "
            f"kind={self.file_kind} email={self.subscriber_email}>"
        )
