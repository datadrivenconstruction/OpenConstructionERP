# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Preliminaries (general conditions) ORM model.

Table:
    oe_preliminaries_item - one preliminaries / general-conditions line for a
                            project.

A line is either *time-related* (priced ``rate_per_period`` and multiplied by the
number of ``periods`` the item stands on site - site staff, standing plant,
temporary works, welfare that runs for a duration) or *fixed* (a one-off
``fixed_amount`` - mobilisation, set-up, final clean). ``item_type`` selects which
pair of fields drives the line total; see :mod:`app.modules.preliminaries.prelim_math`.

Every money / factor column is ``Numeric`` (never float) with a ``server_default``
of zero so a partially filled row created by a raw insert is still well formed.
The table is built by ``create_all``; no Alembic migration is authored here.
"""

import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base

# The two kinds of preliminaries line. Kept as plain strings (not a DB enum) so a
# region can extend the vocabulary without a migration; the service validates the
# incoming value against this set.
ITEM_TYPE_TIME_RELATED = "time_related"
ITEM_TYPE_FIXED = "fixed"


class PrelimItem(Base):
    """A single preliminaries / general-conditions item for a project.

    Attributes:
        project_id: The owning project (cascade-deleted with it).
        label: Human-facing description, e.g. "Site office", "Tower crane".
        category: Grouping bucket for the roll-up (site_establishment,
            site_staff, temporary_works, standing_plant, welfare, general). A
            free string so a region can add its own category.
        item_type: ``time_related`` or ``fixed`` (see the module docstring).
        rate_per_period: Price for one period (used when time-related).
        periods: Number of periods the item stands on site (used when
            time-related). The period unit - week, month - is a project
            convention shared with the programme; the math is unit-agnostic.
        fixed_amount: The one-off amount (used when fixed).
        sort_order: Stable display order within the project.
    """

    __tablename__ = "oe_preliminaries_item"
    __table_args__ = (Index("ix_oe_preliminaries_item_project", "project_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    category: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        default="general",
        server_default="general",
    )
    item_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=ITEM_TYPE_TIME_RELATED,
        server_default=ITEM_TYPE_TIME_RELATED,
    )
    rate_per_period: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    periods: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    fixed_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    def __repr__(self) -> str:
        return f"<PrelimItem {self.label!r} ({self.item_type}) project={self.project_id}>"
