# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Letter template override ORM model.

One row is a company's (``project_id`` NULL) or a project's own wording of
one registered letter in one language. Rows only exist for changed letters;
an unchanged letter reads its shipped default from the core registry.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class LetterTemplateOverride(Base):
    """A changed letter text for ``(template_key, language, project_id)``."""

    __tablename__ = "oe_letter_templates_override"
    __table_args__ = (Index("ix_letter_template_override_lookup", "template_key", "language", "project_id"),)

    template_key: Mapped[str] = mapped_column(String(100), nullable=False)
    language: Mapped[str] = mapped_column(String(10), nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    subject: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")
    heading: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    closing: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")
    updated_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __repr__(self) -> str:
        scope = self.project_id or "company"
        return f"<LetterTemplateOverride {self.template_key} {self.language} {scope}>"
