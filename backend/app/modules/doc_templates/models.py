# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Document template ORM models.

``DocTemplate`` is one kind in one scope and language: the working draft and a
pointer to the published version. ``DocTemplateVersion`` rows are immutable;
publish, restore and reset each add one. A kind nobody edited has no rows and
prints its built-in wording.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base

#: The only scope until legal entities ship; then ``entity:<uuid>``.
WORKSPACE_SCOPE = "workspace"


class DocTemplate(Base):
    """A firm's wording of one document kind for ``(scope, locale)``."""

    __tablename__ = "oe_doc_templates_template"
    __table_args__ = (UniqueConstraint("kind", "scope", "locale", name="uq_doc_templates_template_kind_scope_locale"),)

    kind: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(10), nullable=False, default="pdf", server_default="pdf")
    scope: Mapped[str] = mapped_column(String(60), nullable=False, default=WORKSPACE_SCOPE, server_default="workspace")
    locale: Mapped[str] = mapped_column(String(10), nullable=False)
    draft_blocks: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    draft_options: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    draft_updated_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    draft_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_version_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)

    def __repr__(self) -> str:
        return f"<DocTemplate {self.kind} {self.scope} {self.locale}>"


class DocTemplateVersion(Base):
    """An immutable published text. ``action`` is ``publish``, ``restore`` or ``reset``."""

    __tablename__ = "oe_doc_templates_version"
    __table_args__ = (UniqueConstraint("template_id", "number", name="uq_doc_templates_version_template_number"),)

    template_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_doc_templates_template.id", ondelete="CASCADE"), nullable=False, index=True
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    blocks: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    options: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    letterhead: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    action: Mapped[str] = mapped_column(String(20), nullable=False, default="publish", server_default="publish")
    note: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")
    author_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    author_name: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")

    def __repr__(self) -> str:
        return f"<DocTemplateVersion {self.template_id} v{self.number}>"


class DocTemplateIssue(Base):
    """One issued document and the wording it printed, so a reprint can tell what was sent.

    ``template_version_id`` is ``None`` when the built-in wording printed;
    ``source`` is ``published``, ``primary_language`` or ``default``.
    """

    __tablename__ = "oe_doc_templates_issue"

    kind: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    record_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    locale: Mapped[str] = mapped_column(String(10), nullable=False)
    text_locale: Mapped[str] = mapped_column(String(10), nullable=False, default="en", server_default="en")
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="default", server_default="default")
    template_version_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    issued_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __repr__(self) -> str:
        return f"<DocTemplateIssue {self.kind} {self.record_id}>"
