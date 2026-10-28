# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Resource Summary ORM models.

Tables:
    oe_resource_summary_snapshot - a saved procurement statement for a project at a
        point in time, so a buyer can freeze what the estimate implied they had to
        procure (e.g. at tender issue) and compare it against a later run.

The full statement is stored as a JSON ``payload`` exactly as the API serves it
(money Decimal-as-string, quantities 4dp), so a snapshot renders with no recompute
and never drifts from the live view's format. ``total_cost`` is mirrored out as an
indexed-free string column for cheap listing without parsing the payload; money is
kept as a string for the same SQLite/JSON precision reason as the BoQ tables.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


def _utcnow() -> datetime:
    """Timezone-aware current time (Python-side default, avoids a lazy reload)."""
    return datetime.now(UTC)


class ResourceStatementSnapshot(Base):
    """A frozen procurement statement for a project."""

    __tablename__ = "oe_resource_summary_snapshot"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # When the statement was generated. Python-side default so the value is set on
    # the instance during flush (mirrors Base.created_at, avoids MissingGreenlet).
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        server_default=func.now(),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="", server_default="")
    # Grand total, mirrored from the payload for cheap listing. Money as string.
    total_cost: Mapped[str] = mapped_column(String(50), nullable=False, default="0", server_default="0")
    line_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # The full statement exactly as the API serves it.
    payload: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<ResourceStatementSnapshot project={self.project_id} at={self.generated_at}>"
