# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Retrieval ORM models.

One table, ``oe_retrieval_saved_search``: a search the user pinned so they can
re-run it later. Until now the pin lived in the browser's ``localStorage``,
which meant a saved search was invisible to the same person on a second machine
and gone the moment the profile was cleared. The facets are stored as their own
columns rather than as one JSON blob, so the unique constraint, the indexes and
the validation rules can all address them directly.

Deliberately carries **no** ``relationship()``. The two foreign keys are read as
ids and nothing ever traverses from a saved search to its owner or its project,
so there is no collection to eager-load and no back-reference that could fire a
lazy SELECT out of the async greenlet. Should a caller ever need traversal, the
project rule applies: collections get ``lazy="selectin"`` and the child's
back-reference to its parent gets ``lazy="raise_on_sql"``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base

#: Validation outcomes persisted on the row after a write.
VALIDATION_STATUSES: tuple[str, ...] = ("pending", "passed", "warnings", "errors")


class SavedSearch(Base):
    """A named, re-runnable set of Find Records facets owned by one user.

    Scoped to a project because the search endpoint requires one: a saved
    search that cannot name the project it runs against is a row nobody can
    replay. The unique constraint on ``(user_id, project_id, signature)`` is
    what makes re-saving the same facets an update of the existing pin rather
    than a second identical entry in the list.
    """

    __tablename__ = "oe_retrieval_saved_search"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "project_id",
            "signature",
            name="uq_retrieval_saved_search_sig",
        ),
        Index("ix_retrieval_saved_search_owner", "user_id", "project_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Owner. Saved searches are private to the person who pinned them.",
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Project the facets are replayed against.",
    )
    label: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        doc="What the user calls this search. Free text, shown in the list.",
    )

    # ── The facets, one column each, mirroring the /search query parameters ──
    text: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")
    party: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    record_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="",
        server_default="",
        doc="One of document / correspondence / change_order, or empty for any.",
    )
    date_from: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="",
        server_default="",
        doc="ISO calendar date, inclusive lower bound. Empty means open-ended.",
    )
    date_to: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="",
        server_default="",
        doc="ISO calendar date, inclusive upper bound. Empty means open-ended.",
    )
    entity: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        default="",
        server_default="",
        doc="Reference a record must carry, e.g. a drawing or correspondence number.",
    )

    signature: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        doc="Hash of the canonical facets, see saved_search_logic.facet_signature.",
    )

    # ── Usage, so a long list can be ordered by what the user actually runs ──
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="When the search was last replayed. Null until it is run once.",
    )
    use_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        doc="How many times the search has been replayed.",
    )

    # ── Write-time validation outcome, persisted so a list needs no re-run ──
    validation_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending",
        server_default="pending",
        doc="Outcome of the last write-time validation: pending/passed/warnings/errors",
    )
    validation_findings: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
        doc="Failing rule results from the last write, so the list view can flag them.",
    )

    def __repr__(self) -> str:
        return f"<SavedSearch {self.label!r} user={self.user_id} project={self.project_id}>"


__all__ = ["VALIDATION_STATUSES", "SavedSearch"]
