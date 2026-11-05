# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Document assistant request and response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SOURCE_KINDS = ("specification", "drawing", "contract", "document", "rfi", "submittal", "correspondence", "minutes")


class AskRequest(BaseModel):
    """A plain-language question over one project's documents."""

    project_id: uuid.UUID
    question: str = Field(..., min_length=2, max_length=2000)
    locale: str = Field(default="en", max_length=12)
    kinds: list[str] = Field(default_factory=list, description=f"Restrict to source kinds: {', '.join(SOURCE_KINDS)}")
    use_ai: bool = True


class Citation(BaseModel):
    """Where a claim comes from, with a deep link that opens the source at that page."""

    ref: int
    passage_id: str
    source_kind: str
    source_id: str
    document_id: str | None = None
    title: str
    revision: str | None = None
    page: int | None = None
    sheet_number: str | None = None
    section: str | None = None
    snippet: str = ""
    deep_link: str = ""
    score: float = 0.0


class Claim(BaseModel):
    """One sentence of the answer and the citations it rests on."""

    text: str
    citations: list[int]
    quote: str | None = None
    quoted: bool = False


class AskResponse(BaseModel):
    """Answer, or the reason there is none (``not_found`` / ``no_documents``)."""

    status: Literal["answered", "not_found", "no_documents"]
    mode: Literal["generated", "extractive", "none"]
    question: str
    locale: str
    answer: str = ""
    confidence: float
    threshold: float
    claims: list[Claim] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    nearest: list[Citation] = Field(default_factory=list)
    searched_passages: int = 0
    tokens: int = 0


class SaveRequest(BaseModel):
    """Keep an answer as a project note or as a new RFI draft."""

    project_id: uuid.UUID
    question: str = Field(..., min_length=1, max_length=2000)
    answer: str = Field(default="", max_length=20000)
    claims: list[Claim] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    locale: str = Field(default="en", max_length=12)
    target: Literal["note", "rfi"] = "note"
    rfi_subject: str | None = Field(default=None, max_length=500)


class SavedAnswerOut(BaseModel):
    """A kept answer with the outcome of the ``doc_assistant_answer`` rules."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    question: str
    answer: str
    claims: list[dict[str, Any]]
    citations: list[dict[str, Any]]
    confidence: float
    locale: str
    target_kind: str
    target_id: str | None
    validation: dict[str, Any]
    created_at: datetime


class SavedAnswerListResponse(BaseModel):
    items: list[SavedAnswerOut]
    total: int
    offset: int = 0
    limit: int = 50
