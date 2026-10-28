# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Professional-credentials registry ORM model.

Tables:
    oe_credentials_credential - a project-scoped register of the professional
        credentials a delivery relies on: licences, certifications, statutory
        memberships, professional indemnity, trade/registration cards and
        training. Each row carries a validity window and a reminder threshold
        so the platform can warn before a credential lapses, plus an optional
        statutory-notification obligation (the "notify the authority within N
        days of appointment" duty that exists, in different forms, in most
        jurisdictions).
    oe_credentials_requirement - what the project *demands*. A credential row
        on its own can only answer "does this ticket expire soon". Answering
        "who may not work today" needs the other half: which credential types
        are required, of whom, and whether a gap stops work or merely warrants
        a note. Requirements are matched to credentials by ``credential_type``
        rather than by a foreign key, because a requirement exists precisely
        when the matching credential does *not*.

Why a dedicated register
========================
Three narrower certification tables already exist elsewhere (per-resource,
per-safety-worker, per-subcontractor). None answers the cross-cutting question
this register does: "for THIS project, which people and firms hold which
credentials, are any about to lapse, and do we owe an authority a notification".
It is deliberately jurisdiction-neutral - it stores *what* the credential is and
*when* it is valid, never a country's rule. Per-country vocabularies (which
authority, which statutory window) come from the regional packs.

Design
======
- Tenancy is by ``project_id`` (non-null, cascade delete), mirroring
  :mod:`app.modules.compliance_docs` so the same ``verify_project_access`` guard
  applies and cross-project reads surface as 404.
- ``holder_user_id`` is an optional link to a platform user; ``holder_name`` is
  always present so a credential can belong to a named engineer or firm who is
  not (yet) a user of the system.
- ``status`` is derived from the validity window on every write and stored (not
  computed) so ``status='expiring_soon'`` list filters hit an index. Manual
  ``suspended`` / ``revoked`` states are preserved and never auto-flip back.
- Open-ended ``String`` code fields (never DB enums) so a pack can introduce a
  new credential type without a migration.
"""

from __future__ import annotations

import uuid
from datetime import date as _date

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import true as sa_true
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class Credential(Base):
    """A tracked professional credential held by a person or firm."""

    __tablename__ = "oe_credentials_credential"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Holder ─────────────────────────────────────────────────────────
    # A credential always names its holder; the user link is optional so a
    # named professional who is not a platform user can still be tracked.
    holder_name: Mapped[str] = mapped_column(String(255), nullable=False)
    holder_kind: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="person",
        server_default="person",
    )
    holder_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── Type & identification ──────────────────────────────────────────
    credential_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    discipline: Mapped[str | None] = mapped_column(String(64), nullable=True)
    authority: Mapped[str | None] = mapped_column(String(255), nullable=True)
    identifier: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # ISO country / region code the credential is issued under. A plain tag for
    # filtering and pack lookups - never a rule. NULL = unspecified / global.
    jurisdiction: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # ── Validity window ────────────────────────────────────────────────
    issued_at: Mapped[_date | None] = mapped_column(Date, nullable=True)
    # NULL valid_until = a perpetual credential that never expires; it stays
    # ``active`` and never enters an expiry state.
    valid_until: Mapped[_date | None] = mapped_column(
        Date,
        nullable=True,
        index=True,
    )
    notify_days_before: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=30,
        server_default="30",
    )

    # ── Statutory notification obligation (jurisdiction-neutral) ───────
    # Some engagements carry a duty to notify an authority within N days of a
    # triggering event (e.g. appointment to a role, a contract being signed).
    # The window is a plain number of days; the trigger is an open-ended code.
    # Both NULL = no such obligation on this credential.
    notification_obligation_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notification_trigger: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # ── Derived status (recomputed on every write) ────────────────────
    # One of: active | expiring_soon | expired | suspended | revoked.
    # Stored so the index hits without a window function.
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
        server_default="active",
        index=True,
    )

    # ── Verification ───────────────────────────────────────────────────
    # A credential someone typed in and a credential someone checked against
    # the issuing authority carry different weight on an audit. Both columns
    # NULL means "claimed, never checked"; the compliance report says so rather
    # than treating an unchecked entry as proof.
    verified_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    verified_at: Mapped[_date | None] = mapped_column(Date, nullable=True)

    # ── Free-form ──────────────────────────────────────────────────────
    notes: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # ── Audit ─────────────────────────────────────────────────────────
    created_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        index=True,
    )

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return (
            f"<Credential {self.credential_type} holder={self.holder_name[:30]!r} "
            f"valid_until={self.valid_until} status={self.status}>"
        )


class CredentialRequirement(Base):
    """A credential the project requires of a class of people or firms.

    Deliberately not related to :class:`Credential` by a foreign key. A
    requirement is a statement about a *type* of credential, and its most
    important reading is the negative one: the holder who has no matching row
    at all is exactly the holder the report must name. An FK could only point
    at credentials that exist, which is the case that needs no reporting.
    """

    __tablename__ = "oe_credentials_requirement"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Matched against Credential.credential_type. Open-ended String for the
    # same reason the credential side is: a regional pack introduces a new
    # family without a migration.
    credential_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # Who the requirement binds. "all" covers everyone on the register; any
    # other value is matched against the holder's discipline, which is how a
    # site rule like "supervisors need a first-aid ticket" is expressed without
    # this module inventing a roles table of its own.
    applies_to: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="all",
        server_default="all",
    )
    holder_kind: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="person",
        server_default="person",
    )

    # Blocking is the whole point of the distinction: a missing blocking
    # credential stops the holder working today, a non-blocking one is a note
    # for the file. The compliance report separates them and never silently
    # promotes one to the other.
    is_blocking: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=sa_true(),
    )
    # Days a lapsed credential is tolerated before it starts blocking. Zero is
    # the strict reading (expired means stop); a positive value models the site
    # rule that gives someone a fortnight to get the renewal back.
    grace_days: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=sa_true(),
        index=True,
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    __table_args__ = (
        # One rule per (type, audience, holder kind) per project. Without this a
        # requirement added twice would double every gap it reports.
        UniqueConstraint(
            "project_id",
            "credential_type",
            "applies_to",
            "holder_kind",
            name="uq_credentials_requirement_scope",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return (
            f"<CredentialRequirement {self.credential_type} applies_to={self.applies_to!r} blocking={self.is_blocking}>"
        )


__all__ = ["Credential", "CredentialRequirement"]
