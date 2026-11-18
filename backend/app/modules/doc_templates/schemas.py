# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Request and response schemas of the document templates API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.core.doc_templates.rules import MAX_BLOCK_CHARS

Status = Literal["default", "custom", "draft", "error"]


class IssueOut(BaseModel):
    """One validation finding; the UI translates ``validation.<rule_id>``."""

    rule_id: str
    severity: Literal["error", "warning", "info"]
    block: str = ""
    params: dict[str, str] = Field(default_factory=dict)


class FieldOut(BaseModel):
    """A merge field offered by the picker."""

    path: str
    type: str
    group: str
    sample: str


class KindSummary(BaseModel):
    """One row of the Documents or Emails list."""

    key: str
    channel: Literal["pdf", "email"]
    module: str
    label: str
    status: Status
    languages: list[str]
    builtin_languages: list[str]
    last_published_at: datetime | None = None
    last_published_by: str = ""
    error_rules: list[str] = Field(default_factory=list)


class KindListResponse(BaseModel):
    """The kinds visible to this workspace."""

    items: list[KindSummary]
    total: int
    can_edit: bool
    email_enabled: bool


class VersionOut(BaseModel):
    """One published version."""

    id: uuid.UUID
    number: int
    action: str
    note: str
    author_name: str
    created_at: datetime
    is_published: bool


class TemplateOptions(BaseModel):
    """Presentation options of a PDF template."""

    font: Literal["sans", "serif"] = "sans"
    signature_image: str = Field(default="", max_length=420_000)

    @field_validator("signature_image")
    @classmethod
    def _image(cls, value: str) -> str:
        from app.core.doc_templates.pdf import decode_png_data_url

        if value and decode_png_data_url(value) is None:
            raise ValueError("Signature image must be a PNG or JPEG data URL under 300 KB")
        return value


class EditorState(BaseModel):
    """Everything the editor drawer needs for one kind and language."""

    key: str
    channel: Literal["pdf", "email"]
    module: str
    label: str
    locale: str
    blocks: list[str]
    required_blocks: list[str]
    text: dict[str, str]
    default_text: dict[str, str]
    published_text: dict[str, str] | None
    has_draft: bool
    has_translation: bool
    builtin_language: bool
    primary_locale: str | None
    options: TemplateOptions
    fields: list[FieldOut]
    versions: list[VersionOut]
    issues: list[IssueOut]
    legal_blocks: list[dict[str, str]] = Field(default_factory=list)
    has_records: bool = False


class DraftIn(BaseModel):
    """A working text to save as draft."""

    blocks: dict[str, str] = Field(default_factory=dict)
    options: TemplateOptions | None = None

    @field_validator("blocks")
    @classmethod
    def _caps(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 12:
            raise ValueError("Too many blocks")
        for name, text in value.items():
            if len(name) > 30 or len(text or "") > MAX_BLOCK_CHARS * 2:
                raise ValueError("Block too large")
        return value


class PublishIn(BaseModel):
    """Optional note stored with the version."""

    note: str = Field(default="", max_length=500)


class PreviewIn(BaseModel):
    """Render a draft text with sample values or one real record."""

    blocks: dict[str, str] = Field(default_factory=dict)
    options: TemplateOptions | None = None
    record_id: str | None = Field(default=None, max_length=64)


class PreviewEmailOut(BaseModel):
    """Email preview: subject and isolated HTML."""

    subject: str
    html: str
    issues: list[IssueOut]


class RecordOut(BaseModel):
    """A record the preview can use."""

    id: str
    label: str


class RecordListResponse(BaseModel):
    """Records for "Preview with"; each kind's lister returns its newest few, so ``total`` counts that sample."""

    items: list[RecordOut]
    total: int
    offset: int = 0
    limit: int = 50


class TestSendOut(BaseModel):
    """Outcome of a test send to the signed-in user."""

    sent: bool
    to: str
    detail: str = ""


class ManagerOut(BaseModel):
    """A user and whether they hold the Document manager role."""

    user_id: uuid.UUID
    email: str
    full_name: str
    role: str
    is_manager: bool


class ManagerListResponse(BaseModel):
    """One page of active users with their Document manager flag; ``total`` counts every active user."""

    items: list[ManagerOut]
    total: int
    offset: int = 0
    limit: int = 50


class ManagerIn(BaseModel):
    """Grant or revoke the Document manager role."""

    is_manager: bool


# ── Document layouts ─────────────────────────────────────────────────────


class LayoutSummary(BaseModel):
    """One document whose structure a firm can lay out."""

    key: str
    module: str
    label: str
    published: int = 0
    drafts: int = 0
    projects: int = 0


class LayoutListResponse(BaseModel):
    """Every visible layout."""

    items: list[LayoutSummary]
    total: int
    can_edit: bool


class LayoutDraftIn(BaseModel):
    """The working template; normalised on save, checked on publish."""

    template: dict = Field(default_factory=dict)
    name: str = Field("", max_length=120)


class LayoutPublishIn(BaseModel):
    """Publish note."""

    note: str = Field("", max_length=500)


class LayoutPreviewIn(BaseModel):
    """An unsaved template and, optionally, the record to preview it on."""

    template: dict = Field(default_factory=dict)
    record_id: str | None = Field(None, max_length=64)


class LayoutImportIn(BaseModel):
    """An exported layout file."""

    format: str = Field("", max_length=80)
    schema_version: int = Field(1, alias="schema")
    kind: str = Field("", max_length=120)
    name: str = Field("", max_length=120)
    template: dict = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class ClauseIn(BaseModel):
    """One clause of the library, per language."""

    category: str = Field("", max_length=40)
    title: dict[str, str] = Field(default_factory=dict)
    text: dict[str, str] = Field(default_factory=dict)

    @field_validator("title", "text")
    @classmethod
    def _bounded(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 40:
            raise ValueError("too many languages")
        return value
