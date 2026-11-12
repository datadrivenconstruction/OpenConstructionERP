# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Letter templates request/response schemas."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.letter_templates import MAX_BODY, MAX_LINE, LetterText


class LetterTextIn(BaseModel):
    """The four editable fields of a letter."""

    subject: str = Field(default="", max_length=MAX_LINE)
    heading: str = Field(default="", max_length=MAX_LINE)
    body: str = Field(default="", max_length=MAX_BODY)
    closing: str = Field(default="", max_length=MAX_LINE)

    def to_text(self) -> LetterText:
        """As the core value object."""
        return LetterText(subject=self.subject, heading=self.heading, body=self.body, closing=self.closing)


class LetterTextOut(LetterTextIn):
    """Letter text as returned to the editor."""


class SaveTemplateRequest(LetterTextIn):
    """Save a template override; ``project_id`` absent means the company-wide text."""

    language: str = Field(min_length=2, max_length=10)
    project_id: UUID | None = None


class PlaceholderOut(BaseModel):
    """A placeholder offered by a letter."""

    name: str
    sample: str
    required: bool


class IssueOut(BaseModel):
    """A validation finding."""

    code: str
    severity: Literal["error", "warning"]
    field: str
    placeholder: str = ""


class TemplateSummary(BaseModel):
    """One letter in the list, with which languages the company changed."""

    key: str
    module: str
    kind: str
    languages: list[str]
    customised_languages: list[str]


class ResolvedTemplate(BaseModel):
    """The text a letter would use now, where it came from, and the default."""

    key: str
    module: str
    kind: str
    language: str
    source: Literal["project", "company", "default"]
    text: LetterTextOut
    default: LetterTextOut
    placeholders: list[PlaceholderOut]
    issues: list[IssueOut]


class ValidateRequest(LetterTextIn):
    """Check a text without saving it."""


class PreviewRequest(LetterTextIn):
    """Render a sample letter from an unsaved text."""

    language: str = Field(default="en", min_length=2, max_length=10)
