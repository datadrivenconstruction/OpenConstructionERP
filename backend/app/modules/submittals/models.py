# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Submittals ORM models.

Tables:
    oe_submittals_submittal - construction submittals with review/approval workflow
"""

import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class Submittal(Base):
    """A construction submittal with multi-stage review and approval workflow."""

    __tablename__ = "oe_submittals_submittal"
    # ``submittal_number`` must be unique per project - the auto-generator
    # uses ``MAX(suffix)+1`` which has a TOCTOU race under concurrent
    # creates; without this constraint two parallel POSTs would silently
    # persist ``SUB-005`` twice. With the constraint the second commit
    # raises ``IntegrityError`` and the service layer retries.
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "submittal_number",
            name="uq_oe_submittals_submittal_project_number",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    submittal_number: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    spec_section: Mapped[str | None] = mapped_column(String(100), nullable=True)
    submittal_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft", index=True)
    ball_in_court: Mapped[str | None] = mapped_column(GUID(), nullable=True)
    current_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    submitted_by_org: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reviewer_id: Mapped[str | None] = mapped_column(GUID(), nullable=True)
    approver_id: Mapped[str | None] = mapped_column(GUID(), nullable=True)
    date_submitted: Mapped[str | None] = mapped_column(String(20), nullable=True)
    date_required: Mapped[str | None] = mapped_column(String(20), nullable=True)
    date_returned: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Linked BOQ item IDs: array of UUID strings
    linked_boq_item_ids: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )

    # ── The register a contractor runs procurement from ──────────────────
    #
    # Every column below is nullable or carries a server default, so the boot
    # heal (``app.core.postgres_migrator``) can add it to a table that already
    # holds rows. A row from before them reads as "not recorded" throughout.

    # Trade the submittal belongs to. A code from ``tracking.DISCIPLINES`` or
    # any other lower-case code a project uses; free on the DB side like
    # ``oe_rfi_rfi.discipline``.
    discipline: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    # What is being offered: brand, the manufacturer's own reference, where it
    # is made (ISO 3166-1 alpha-2) and who sells it. ``supplier`` holds a
    # contact id or a typed name, the same convention as ``submitted_by_org``.
    manufacturer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    country_of_origin: Mapped[str | None] = mapped_column(String(2), nullable=True)
    supplier: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # What the reviewer stamped on the current revision. ``status`` says where
    # the document is in the process and moves on (to ``closed``, or back to
    # ``submitted`` on a resubmission); the decision and the mark printed on
    # the stamp have to stay readable after that. ``review_outcome`` is one of
    # the four review decisions, ``review_code`` the mark as the reviewer
    # wrote it ("B", "2").
    review_outcome: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    review_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Calendar days the contract gives the reviewer. NULL means not recorded,
    # and then "overdue for review" is unknown rather than assumed.
    review_period_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # One entry per finished review cycle (see ``tracking.history_entry``).
    # Revisions are revised in place, so this is what remains of a replaced
    # revision and what links a resubmission to it.
    review_history: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )

    # Procurement: when the item has to be on site and how long it takes to
    # arrive once ordered. Required on site less the lead time is the last day
    # an approval is still in time.
    required_on_site_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    long_lead: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    lead_time_weeks: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Drawing sheets or documents this submittal is about, by id. A soft link
    # with no foreign key, like ``oe_rfi_rfi.linked_drawing_ids``. Distinct
    # from the attachments in ``metadata``, which are the submitted files.
    linked_drawing_ids: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )

    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<Submittal {self.submittal_number} - {self.title[:40]} ({self.status})>"
