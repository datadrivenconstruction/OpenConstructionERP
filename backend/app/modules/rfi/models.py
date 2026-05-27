"""‌⁠‍RFI ORM models.

Tables:
    oe_rfi_rfi — requests for information with response tracking and impact assessment
"""

import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class RFI(Base):
    """‌⁠‍A Request for Information with response tracking and impact assessment."""

    __tablename__ = "oe_rfi_rfi"
    # R5 / BUG-RFI-UNIQ: ``(project_id, rfi_number)`` must be unique so
    # concurrent ``create_rfi`` calls racing on ``max(rfi_number)+1`` get
    # a clean :class:`IntegrityError` the service can retry, rather than
    # quietly writing two RFI-007 rows in the same project. Mirrors the
    # changeorders ``uq_changeorders_project_code`` pattern.
    __table_args__ = (UniqueConstraint("project_id", "rfi_number", name="uq_rfi_project_number"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rfi_number: Mapped[str] = mapped_column(String(20), nullable=False)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    raised_by: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    assigned_to: Mapped[str | None] = mapped_column(GUID(), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft", index=True)
    ball_in_court: Mapped[str | None] = mapped_column(GUID(), nullable=True)
    official_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    responded_by: Mapped[str | None] = mapped_column(GUID(), nullable=True)
    responded_at: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cost_impact: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cost_impact_value: Mapped[str | None] = mapped_column(String(50), nullable=True)
    schedule_impact: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    schedule_impact_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    date_required: Mapped[str | None] = mapped_column(String(20), nullable=True)
    response_due_date: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Priority: low | normal | high | critical (validated by the Pydantic
    # schema; free-form on the DB side so future values can land without
    # a migration).
    priority: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Discipline: architectural / structural / mep / electrical / plumbing /
    # civil / landscape. Kept free-form server-side; the frontend picker
    # constrains the user-visible values.
    discipline: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Linked drawing IDs: array of document/drawing UUID strings
    linked_drawing_ids: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )

    # R5 / BUG-RFI-ATT: reply attachments. Each entry is a server-derived
    # relative path under ``uploads/rfi/attachments/<rfi_id>_<hex><ext>``.
    # Magic-byte gated at the router; this column never stores
    # attacker-controlled filenames.
    attachments: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )

    change_order_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<RFI {self.rfi_number} — {self.subject[:40]} ({self.status})>"
