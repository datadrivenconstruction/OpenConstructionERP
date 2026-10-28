# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Authority-submission ORM models.

Tables:
    oe_authority_submission_profile - a schema definition (carried as data) for
        one authority XML format: its root element, schema version and the list
        of expected fields (``field_spec``). Profiles are *global*, not
        project-scoped: the same format is reused across every project, and the
        built-in, jurisdiction-neutral ones are seeded idempotently. A regional
        pack (e.g. RU Minstroy expertise XML) adds its national dialect as a new
        profile row with its own ``field_spec`` and ``root_element`` - no schema
        migration, no engine change.

    oe_authority_submission_submission - one concrete document being prepared
        against a profile: the structured ``payload``, its lifecycle ``status``,
        the deterministically generated XML and the validation report. Tenancy
        is by ``project_id`` (cascade delete) so the standard
        ``verify_project_access`` guard applies and cross-project ids surface as
        404.

Design
======
- ``format_key`` and ``status`` are open-ended ``String`` columns (never DB
  enums) so a pack can introduce a new format family or the lifecycle can grow a
  state without a migration; the API validates against the built-in whitelists.
- ``field_spec`` is JSON: an ordered list of field descriptors
  ``{"name", "type", "required", "xml_tag"?, "label"?, ...}``. The order is
  significant - the XML builder walks it in order so output is deterministic.
- ``generated_xml`` / ``validation_report`` are nullable: they only exist once
  the caller has generated / validated, and are cleared when the payload changes.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class SubmissionProfile(Base):
    """A schema definition for one authority XML format, carried as data."""

    __tablename__ = "oe_authority_submission_profile"

    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    # ISO country / region code the format belongs to. A plain tag for filtering
    # and pack lookups - never a rule. NULL = jurisdiction-neutral / global.
    jurisdiction: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # Open-ended family key: minstroy_xml | gaeb_x83 | cobie | eplan |
    # generic_xml | custom. Plain String so a pack can add a new family.
    format_key: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="generic_xml",
        server_default="generic_xml",
        index=True,
    )
    schema_version: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="1.0",
        server_default="1.0",
    )
    # The XML root element the builder emits for this format.
    root_element: Mapped[str] = mapped_column(String(64), nullable=False, default="Document")

    # Ordered list of field descriptors driving validation and XML generation.
    field_spec: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )

    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    # True for a platform-seeded profile; built-ins are protected from deletion.
    is_builtin: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
        index=True,
    )

    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return (
            f"<SubmissionProfile {self.name!r} format={self.format_key} "
            f"root={self.root_element} builtin={self.is_builtin}>"
        )


class Submission(Base):
    """A concrete authority document being prepared against a profile."""

    __tablename__ = "oe_authority_submission_submission"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_authority_submission_profile.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)

    # The structured data to submit, keyed by field-spec ``name``.
    payload: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Lifecycle: draft | validated | signed_pending | submitted | accepted |
    # rejected. Stored (not computed) so list filters hit the index.
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="draft",
        server_default="draft",
        index=True,
    )

    # Populated on demand; cleared when the payload changes (both go stale).
    generated_xml: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_report: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return f"<Submission {self.title[:30]!r} status={self.status} profile={self.profile_id}>"


__all__ = ["Submission", "SubmissionProfile"]
