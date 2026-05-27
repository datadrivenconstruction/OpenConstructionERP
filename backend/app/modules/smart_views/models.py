# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍Smart Views ORM models.

A :class:`SmartView` carries an ordered list of *rules* in a JSON
column — the rules themselves are validated by Pydantic in
``schemas.py``, the DB just persists them as opaque JSON. The
counter-intuitive design choice is that we DO NOT snapshot which
elements are hidden / coloured at save time; the rules re-evaluate
against the live ``BIMElement.properties`` every time the view is
loaded. See ``__init__.py`` for the rationale.

Tables:
    oe_smart_view  — one rule-set scoped to a user, project, or
                     federation. ``id`` / ``created_at`` /
                     ``updated_at`` come from :class:`app.database.Base`.
"""

import uuid

from sqlalchemy import (
    JSON,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class SmartView(Base):
    """‌⁠‍A named, re-evaluating BIM visibility / colour preset.

    Scoping is encoded by the ``scope_type`` + ``scope_id`` pair:

    * ``user``       — private to one user (``scope_id`` = user UUID).
    * ``project``    — shared inside one project (``scope_id`` =
                       project UUID); visible to anyone with
                       ``bim.read`` on that project.
    * ``federation`` — shared inside one federation (``scope_id`` =
                       federation UUID).

    The ``rules`` JSON column carries the ordered list of rule dicts
    documented by :class:`SmartViewRule` in ``schemas.py``. Later rules
    override earlier ones — semantics validated by the evaluator.
    """

    __tablename__ = "oe_smart_view"
    __table_args__ = (
        Index("ix_smart_view_scope", "scope_type", "scope_id"),
        Index("ix_smart_view_created_by", "created_by"),
        # Partial-uniqueness on the share token: NULL is excluded from
        # the uniqueness contract so revoking a token simply nulls the
        # column (no orphaned "deleted" sentinel rows). The index is
        # additionally narrow — `share_token` lookups are the only
        # read pattern for unauthenticated share-link resolution.
        Index(
            "ix_smart_view_share_token",
            "share_token",
            unique=True,
            sqlite_where=text("share_token IS NOT NULL"),
            postgresql_where=text("share_token IS NOT NULL"),
        ),
    )

    # 'user' | 'project' | 'federation'.
    scope_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="user",
        server_default="user",
    )
    # The owning user-/project-/federation-id, depending on scope_type.
    # We deliberately do NOT declare a foreign key here because the
    # target table varies with ``scope_type``; the service layer
    # validates referential integrity instead.
    scope_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Ordered list of rule dicts (later wins). Persisted as JSON so a
    # schema migration is not required every time a new operator or
    # action ships. Validated by Pydantic on every write.
    rules: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )

    # 'show_all' | 'hide_all' — what the evaluator starts from before
    # the rules run. ``hide_all`` + a ``show`` rule produces the
    # "isolate by query" pattern BIMcollab Zoom is famous for.
    default_action: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="show_all",
        server_default="show_all",
    )

    # Cached colour-legend payload — only populated when at least one
    # rule uses ``color_by_property`` (the evaluator builds it on the
    # fly anyway, but persisting it lets the UI render the legend
    # before the first evaluation lands).
    color_legend: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_by: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Optional signed token enabling unauthenticated read-only access
    # to this view via the public ``/share/<token>`` route. NULL means
    # "not shared"; non-NULL values are unique platform-wide so the
    # token alone resolves to a single view. The value itself is an
    # ``itsdangerous`` URL-safe signed string — its payload is the
    # view UUID, so a stolen token still cannot point at a different
    # view (signature mismatch on tamper).
    share_token: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)

    def __repr__(self) -> str:  # pragma: no cover — debug only
        return f"<SmartView {self.name!r} scope={self.scope_type}:{self.scope_id}>"
