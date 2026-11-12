# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Resolve, save and reset letter texts.

Resolution for ``(key, language, project)``: the project's own override, then
the company override, then the shipped default. The language is the letter's
(the project's document language), reduced to one the letter ships; it is never
the language of the user's interface.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.letter_templates import (
    LetterIssue,
    LetterTemplate,
    LetterText,
    check_text,
    default_text,
    get_template,
    template_language,
)
from app.modules.letter_templates.repository import LetterTemplateRepository


@dataclass(frozen=True)
class Resolved:
    """A resolved letter text and its origin (``project``, ``company`` or ``default``)."""

    template: LetterTemplate
    language: str
    text: LetterText
    source: str


def require_template(key: str) -> LetterTemplate:
    """The registered letter or a 404."""
    from app.modules.tendering.letter_texts import register_tendering_letter_templates

    register_tendering_letter_templates()
    template = get_template(key)
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown letter template: {key}")
    return template


def _row_text(row: object) -> LetterText:
    return LetterText(
        subject=getattr(row, "subject", "") or "",
        heading=getattr(row, "heading", "") or "",
        body=getattr(row, "body", "") or "",
        closing=getattr(row, "closing", "") or "",
    )


async def project_language(session: AsyncSession, project_id: uuid.UUID | None) -> str | None:
    """The project's document language (``Project.locale``), if any."""
    if project_id is None:
        return None
    from app.modules.projects.repository import ProjectRepository

    project = await ProjectRepository(session).get_by_id(project_id)
    return getattr(project, "locale", None) if project is not None else None


async def resolve(
    session: AsyncSession,
    key: str,
    language: str | None,
    project_id: uuid.UUID | None = None,
) -> Resolved:
    """The text a letter uses now: project, then company, then default."""
    template = require_template(key)
    if language is None:
        language = await project_language(session, project_id)
    lang = template_language(template, language)
    repo = LetterTemplateRepository(session)
    if project_id is not None:
        row = await repo.get(key, lang, project_id)
        if row is not None:
            return Resolved(template, lang, _row_text(row), "project")
    row = await repo.get(key, lang, None)
    if row is not None:
        return Resolved(template, lang, _row_text(row), "company")
    return Resolved(template, lang, default_text(template, lang), "default")


def validate(template: LetterTemplate, text: LetterText) -> list[LetterIssue]:
    """Run the letter rules (see :func:`app.core.letter_templates.check_text`)."""
    return check_text(template, text)


async def save(
    session: AsyncSession,
    key: str,
    language: str,
    project_id: uuid.UUID | None,
    text: LetterText,
    user_id: str | None,
) -> list[LetterIssue]:
    """Validate and store an override. Errors refuse the save with a 422."""
    template = require_template(key)
    lang = template_language(template, language)
    if lang != language.strip().lower().split("-")[0]:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported letter language")
    issues = validate(template, text)
    errors = [i for i in issues if i.severity == "error"]
    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "Letter text has errors", "issues": [i.__dict__ for i in errors]},
        )
    await LetterTemplateRepository(session).upsert(key, lang, project_id, text.as_dict(), user_id)
    return issues


async def reset(session: AsyncSession, key: str, language: str, project_id: uuid.UUID | None) -> int:
    """Drop the override for one scope; the letter falls back one level."""
    template = require_template(key)
    return await LetterTemplateRepository(session).delete(key, template_language(template, language), project_id)


async def customised_map(session: AsyncSession, project_id: uuid.UUID | None = None) -> dict[str, list[str]]:
    """Languages with an override, per template key."""
    out: dict[str, list[str]] = {}
    for key, lang in await LetterTemplateRepository(session).customised(project_id):
        out.setdefault(key, []).append(lang)
    return out
