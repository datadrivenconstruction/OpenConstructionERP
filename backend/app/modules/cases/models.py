# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Cases ORM models.

Tables:
    oe_cases_user_case - a case scenario written by a user
    oe_cases_pin       - a case pinned to a project, per user

``UserCase.steps`` is a JSON array rather than a child table. The steps of a
case are always read and rewritten as a whole: the editor saves the ordered
list in one go, the reader walks it start to finish, and nothing ever queries a
single step across cases. A child table would buy a relationship every caller
has to eager-load and an ordinal column to keep in sync, and buy nothing back.
The shape is validated by the Pydantic layer before it is stored, so the column
is not a free-form bag - see :mod:`app.modules.cases.schemas`.

Nothing here is ever queried *inside* the JSON. That matters: on PostgreSQL a
``.contains()`` on a plain JSON column compiles to a string LIKE, not to JSONB
containment, so a filter written that way would silently mean something else.
Filtering is done on real columns only.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base

# The case categories the reader groups by. Mirrors ``CaseCategory`` in
# ``frontend/src/features/cases/types.ts``; a user case has to land in one of
# the same buckets as a shipped playbook or it cannot be shown beside them.
CASE_CATEGORIES: tuple[str, ...] = (
    "estimating",
    "tendering",
    "planning",
    "bim",
    "site",
    "quality",
    "commercial",
    "handover",
)

# Where a pinned case comes from. A shipped playbook is identified by its source
# slug ("build-a-5d-cost-loaded-model"), a user case by its UUID. Keeping the
# source explicit means the two id spaces can never collide, which a single
# free-text id column could not guarantee.
PIN_SOURCES: tuple[str, ...] = ("builtin", "custom")


class UserCase(Base):
    """One case scenario authored in the app.

    A case is a short walkthrough: why you would do this, and the ordered
    screens you pass through to do it. The shipped playbooks say how the
    product expects work to flow; a user case says how *this* team actually
    works, which is the version a new starter needs.

    ``is_shared`` is the whole visibility model. There is no tenancy in the
    platform - one deployment is one company - so a shared case is visible to
    every signed-in user of this installation, and a private one only to its
    owner. Editing and deleting stay with the owner either way.
    """

    __tablename__ = "oe_cases_user_case"
    __table_args__ = (
        Index("ix_cases_user_case_owner", "owner_id"),
        Index("ix_cases_user_case_shared_category", "is_shared", "category"),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    long_description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    # Free-text audience tags, mirroring the shipped playbooks' companyTypes /
    # roles. Stored as written so a team can use its own vocabulary.
    company_types: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    roles: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    stage: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    est_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=10, server_default="10")
    icon: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    steps: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    # Set when the case was started from a shipped playbook, so the reader can
    # say "adapted from" and a later product change to that playbook can be
    # traced to the copies it inspired. Never a foreign key: the shipped
    # playbooks live in the frontend bundle, not in this database.
    source_playbook_id: Mapped[str] = mapped_column(String(128), nullable=False, default="", server_default="")
    is_shared: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")

    def __repr__(self) -> str:
        scope = "shared" if self.is_shared else "private"
        return f"<UserCase {self.id} {self.category} {scope} steps={len(self.steps or [])}>"


class CasePin(Base):
    """One ``user x project x case`` pin.

    This is the row that used to be a ``localStorage`` key. A pinned set is the
    handful of cases that matter on this job, and it has to survive a different
    device and a cleared cache or it is not a work tool.

    Deliberately per user, not per project: two people on one job care about
    different walkthroughs, and a shared pin board would need a conflict story
    nobody asked for. ``sort_order`` keeps the order the user dragged them into.
    """

    __tablename__ = "oe_cases_pin"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "project_id",
            "case_source",
            "case_id",
            name="uq_cases_pin_user_project_case",
        ),
        Index("ix_cases_pin_user_project", "user_id", "project_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
    )
    case_source: Mapped[str] = mapped_column(String(16), nullable=False)
    case_id: Mapped[str] = mapped_column(String(128), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")

    def __repr__(self) -> str:
        return f"<CasePin user={self.user_id} project={self.project_id} {self.case_source}:{self.case_id}>"
