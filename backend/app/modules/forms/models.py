# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Forms & Checklists ORM models.

Tables:
    oe_forms_template   - a reusable form / checklist template (the library)
    oe_forms_submission - one filled-in instance of a template, tied to a project

A template is *library-scoped*: ``project_id`` is nullable, so a template with
no project is an organisation-wide library entry available to every project,
while a template pinned to a project is that project's own. A submission is
always project-scoped and CASCADE-deletes with its project.

Light versioning by snapshot: a submission copies the template's field
definitions into ``template_snapshot`` at fill time and records the
``template_version`` it was taken from, so editing (or deleting) a template
later never rewrites or corrupts a form that was already filled against it.
"""

import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class FormTemplate(Base):
    """A reusable form / checklist template composed of ordered fields."""

    __tablename__ = "oe_forms_template"
    __table_args__ = (
        # Library browse path: filter by category within a scope (global or one
        # project). project_id first so the "global library" scan (NULL) is
        # equally well served.
        Index("ix_oe_forms_template_project_category", "project_id", "category"),
    )

    # Nullable: NULL == organisation-wide library template (visible to every
    # project); set == a template that belongs to one project only. When the
    # owning project is deleted its private templates go with it.
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(40), nullable=False, default="custom", index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="published", index=True)

    # Lightweight version counter, bumped when the field structure changes.
    # A submission records the value it was filled against.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    # Ordered field definitions:
    # [{key, type, label, required, help_text, options?, unit?, max_rating?}]
    fields_data: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )

    # Free-text tags for search / grouping in the library.
    tags: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )

    # True for the built-in starter templates seeded at first startup, so the
    # UI can badge them and the seeder can tell "already seeded" from "user
    # deleted them all".
    is_seed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")

    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<FormTemplate {self.name!r} ({self.category}/v{self.version})>"


class FormSubmission(Base):
    """One filled-in instance of a template, tied to a project."""

    __tablename__ = "oe_forms_submission"
    __table_args__ = (
        Index("ix_oe_forms_submission_project_status", "project_id", "status"),
        # Per-project uniqueness of the human-facing FRM-NNN number. COUNT+1
        # numbering races under concurrent creates; this constraint forces a
        # retry instead of a duplicate (mirrors inspections).
        UniqueConstraint(
            "project_id",
            "submission_number",
            name="uq_oe_forms_submission_project_number",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Link back to the source template. SET NULL on delete: the submission keeps
    # its own ``template_snapshot`` so it survives the template being removed.
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_forms_template.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    submission_number: Mapped[str] = mapped_column(String(20), nullable=False)

    # Snapshot of the template at fill time - name, category, version and the
    # frozen field definitions. Editing the template later never touches these.
    template_name: Mapped[str] = mapped_column(String(300), nullable=False)
    template_category: Mapped[str] = mapped_column(String(40), nullable=False, default="custom")
    template_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    template_snapshot: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )

    # Optional human reference for this instance (location, asset, pour ref...).
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    location: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Answers keyed by field key: {field_key: answer_value}.
    answers_data: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    # A rolled-up result for checklist-style forms (pass / fail / na / none),
    # derived from the pass_fail_na answers on complete.
    result: Mapped[str | None] = mapped_column(String(20), nullable=True)

    completed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    completed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # Light QA link: a completed inspection-category form can point at an
    # inspection raised from it (see router.create-inspection). Nullable string,
    # never a hard FK, so the forms module carries no dependency on inspections.
    linked_inspection_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<FormSubmission {self.submission_number} ({self.status})>"
