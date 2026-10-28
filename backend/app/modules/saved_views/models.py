# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Saved-views ORM models.

Two tables, both inheriting :class:`app.database.Base` (so ``id`` / ``created_at``
/ ``updated_at`` are free). No money is involved here, so no ``MoneyType``. JSON
columns carry ``server_default`` because the embedded PostgreSQL runtime builds
the schema via ``create_all`` and ignores Python-side defaults on existing dev
databases.

Tables:
    oe_saved_views_view - one named, scoped filter spec against a registered
                          entity.
    oe_saved_views_run  - append-only audit/telemetry of a run (budget overflow
                          attempts and slow views are observable).
"""

import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base

#: Every share scope the column accepts. ``public`` is deliberately absent:
#: there is no unauthenticated share token, and a saved view never grants a
#: viewer access to a row the row scoper would have withheld.
SHARE_SCOPES: tuple[str, ...] = ("private", "team", "project", "workspace")


class SavedView(Base):
    """A named, scoped saved search against one registered entity.

    The ``spec`` JSON is the serialized ``FilterSpec``; it is re-validated by
    Pydantic on every read and write, never trusted as-is. ``share_scope`` is one
    of ``private`` / ``team`` / ``project`` / ``workspace`` - never ``public``;
    there is no unauthenticated share token in Phase 1.

    Sharing widens who can see the DEFINITION, never what the run returns. Every
    run still passes through the entity scoper under the viewer's own identity,
    so a shared view executed by a colleague returns that colleague's rows.
    """

    __tablename__ = "oe_saved_views_view"
    __table_args__ = (
        Index("ix_saved_views_owner_entity", "owner_id", "entity_type"),
        Index("ix_saved_views_project_entity", "project_id", "entity_type"),
        UniqueConstraint(
            "owner_id",
            "project_id",
            "entity_type",
            "name",
            name="uq_saved_views_owner_scope_name",
        ),
        # The ``ck`` naming convention wraps these names as
        # ``ck_<table>_<name>``, so they are given bare here and spelled out in
        # full in the migration. A name that only matches one of the two routes
        # into this schema is a constraint nobody can drop.
        CheckConstraint(
            "share_scope IN ('private', 'team', 'project', 'workspace')",
            name="share_scope",
        ),
        # A team pin only means something on a team share. The reverse is NOT
        # constrained on purpose: dropping a team SET NULLs this column, and a
        # team share that has lost its team must degrade to owner-only rather
        # than block the delete or take the saved view down with it.
        CheckConstraint(
            "shared_team_id IS NULL OR share_scope = 'team'",
            name="team_pin_scope",
        ),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    spec: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    share_scope: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="private",
        server_default="private",
    )
    shared_team_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_teams_team.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    is_pinned: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    #: Run telemetry for this view, newest first.
    #:
    #: ``raise_on_sql`` rather than ``selectin``: run history grows without
    #: bound and is not what a caller listing or executing a view wants, so a
    #: reader must page it through the repository instead of walking the
    #: attribute. Reading it off an instance that already loaded it stays free.
    #: ``passive_deletes`` leaves the ``ON DELETE SET NULL`` on the database:
    #: without it SQLAlchemy would load the whole collection on every delete
    #: just to null the FK it has already told PostgreSQL to null.
    runs: Mapped[list["SavedViewRun"]] = relationship(
        back_populates="view",
        lazy="raise_on_sql",
        passive_deletes=True,
        order_by="SavedViewRun.created_at.desc()",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return f"<SavedView {self.name!r} entity={self.entity_type} scope={self.share_scope}>"


class SavedViewRun(Base):
    """Append-only audit row written after a run.

    Lets budget-overflow attempts and slow views be observed. ``outcome`` is one
    of ``ok`` / ``budget`` / ``scope`` / ``whitelist`` / ``error``.
    """

    __tablename__ = "oe_saved_views_run"
    __table_args__ = (
        Index("ix_saved_views_run_view_created", "saved_view_id", "created_at"),
        CheckConstraint(
            "outcome IN ('ok', 'budget', 'scope', 'whitelist', 'error')",
            name="outcome",
        ),
    )

    saved_view_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_saved_views_view.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    truncated: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    elapsed_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    #: The view this run belongs to, ``None`` once that view is deleted.
    #:
    #: ``raise_on_sql`` because the FK column already carries the id: walking
    #: up from a run row is exactly the implicit round trip the loading policy
    #: exists to catch. A caller that needs the parent orders it eagerly.
    view: Mapped["SavedView | None"] = relationship(
        back_populates="runs",
        lazy="raise_on_sql",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return f"<SavedViewRun view={self.saved_view_id} outcome={self.outcome} rows={self.row_count}>"
