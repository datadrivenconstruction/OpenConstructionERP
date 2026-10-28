# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Portfolio / programme tree models (T3.3).

An enterprise *schedule-of-schedules* navigation overlay:

* ``oe_portfolio_node`` - an adjacency-list tree of portfolio / programme /
  sub-programme nodes (mirrors the ``ProjectWBS`` node shape).
* ``oe_portfolio_membership`` - a thin link placing a project under exactly one
  node (unique on ``project_id``), so a project's position in the tree is kept
  orthogonal to its engineering decomposition (``Project.parent_project_id``).

The tree is a navigation / rollup / scoping overlay, NOT a security principal:
every read still intersects with ``accessible_project_ids`` and a node grants
no access on its own. Cross-module references (``project_id``, ``owner_id``) are
plain GUIDs with no DB-level FK, matching the codebase precedent; a membership
to a deleted project is simply pruned by the access intersection.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    JSON,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base

#: Node types, coarse-to-fine; the first entry is the default.
PORTFOLIO_NODE_TYPES: tuple[str, ...] = ("portfolio", "programme", "subprogramme")


class PortfolioNode(Base):
    """One node in the portfolio / programme tree (adjacency list)."""

    __tablename__ = "oe_portfolio_node"

    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_portfolio_node.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    node_type: Mapped[str] = mapped_column(String(20), nullable=False, default="programme", server_default="programme")
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False, default="", server_default="")
    # Plain GUID (no cross-module FK to oe_users_user), per codebase precedent.
    owner_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return f"<PortfolioNode {self.node_type}:{self.name!r}>"


class PortfolioMembership(Base):
    """Places a project under exactly one portfolio node (unique on project)."""

    __tablename__ = "oe_portfolio_membership"
    __table_args__ = (UniqueConstraint("project_id", name="uq_portfolio_membership_project"),)

    node_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_portfolio_node.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Plain GUID (no cross-module FK to oe_projects_project), per precedent.
    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return f"<PortfolioMembership node={self.node_id} project={self.project_id}>"


class PortfolioCrossLink(Base):
    """A cross-schedule dependency between two activities in different schedules.

    Drives the portfolio (schedule-of-schedules) CPM: the engine treats a link
    whose both endpoints are in scope as a real edge. All four references are
    plain GUIDs (no cross-module FK to the ``schedule`` module's tables, per
    codebase precedent); a link pointing at a deleted schedule/activity is simply
    skipped at compute time.
    """

    __tablename__ = "oe_portfolio_cross_link"
    __table_args__ = (
        Index("ix_portfolio_cross_link_predecessor", "predecessor_schedule_id"),
        Index("ix_portfolio_cross_link_successor", "successor_schedule_id"),
    )

    predecessor_schedule_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    predecessor_activity_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    successor_schedule_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    successor_activity_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    dep_type: Mapped[str] = mapped_column(String(2), nullable=False, default="FS", server_default="FS")
    lag_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return f"<PortfolioCrossLink {self.predecessor_activity_id}->{self.successor_activity_id} {self.dep_type}>"
