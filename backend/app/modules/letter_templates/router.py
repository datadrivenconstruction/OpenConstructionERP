# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Letter templates API, mounted at ``/api/v1/letter-templates/``.

GET    /                    - every letter, with the languages the company changed
GET    /{key}               - resolved text (``?language=``, ``?project_id=``)
PUT    /{key}               - save an override (company, or project with ``project_id``)
DELETE /{key}               - reset one language and scope to the next level
POST   /{key}/validate      - check an unsaved text
POST   /{key}/preview       - sample letter from an unsaved text
"""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, Query, Response, status

from app.core.letter_templates import LetterIssue, LetterTemplate, LetterText, all_templates, default_text
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.letter_templates import service
from app.modules.letter_templates.schemas import (
    IssueOut,
    LetterTemplatesListResponse,
    LetterTextOut,
    PlaceholderOut,
    PreviewRequest,
    ResolvedTemplate,
    SaveTemplateRequest,
    TemplateSummary,
    ValidateRequest,
)

router = APIRouter(tags=["letter_templates"])


def _text_out(text: LetterText) -> LetterTextOut:
    return LetterTextOut(**text.as_dict())


def _issues_out(issues: list[LetterIssue]) -> list[IssueOut]:
    return [IssueOut(code=i.code, severity=i.severity, field=i.field, placeholder=i.placeholder) for i in issues]  # type: ignore[arg-type]


def _resolved_out(resolved: service.Resolved) -> ResolvedTemplate:
    t: LetterTemplate = resolved.template
    return ResolvedTemplate(
        key=t.key,
        module=t.module,
        kind=t.kind,
        language=resolved.language,
        source=resolved.source,  # type: ignore[arg-type]
        text=_text_out(resolved.text),
        default=_text_out(default_text(t, resolved.language)),
        placeholders=[PlaceholderOut(name=p.name, sample=p.sample, required=p.required) for p in t.placeholders],
        issues=_issues_out(service.validate(t, resolved.text)),
    )


@router.get(
    "/",
    response_model=LetterTemplatesListResponse,
    dependencies=[Depends(RequirePermission("letter_templates.read"))],
)
async def list_templates(session: SessionDep) -> LetterTemplatesListResponse:
    """Every registered letter, grouped by module in the UI."""
    service.require_template("tendering.award_letter")
    customised = await service.customised_map(session)
    items = [
        TemplateSummary(
            key=t.key,
            module=t.module,
            kind=t.kind,
            languages=list(t.languages),
            customised_languages=sorted(customised.get(t.key, [])),
        )
        for t in all_templates()
    ]
    return LetterTemplatesListResponse(items=items, total=len(items), limit=max(len(items), 1))


@router.get(
    "/{key}",
    response_model=ResolvedTemplate,
    dependencies=[Depends(RequirePermission("letter_templates.read"))],
)
async def get_template_text(
    key: str,
    session: SessionDep,
    user_id: CurrentUserId,
    language: str | None = Query(None, max_length=10),
    project_id: uuid.UUID | None = Query(None),
) -> ResolvedTemplate:
    """The text a letter uses now. Without ``language`` the project's language is used."""
    if project_id is not None:
        await verify_project_access(project_id, user_id, session)
    return _resolved_out(await service.resolve(session, key, language, project_id))


@router.put(
    "/{key}",
    response_model=ResolvedTemplate,
    dependencies=[Depends(RequirePermission("letter_templates.edit"))],
)
async def save_template(
    key: str,
    payload: SaveTemplateRequest,
    session: SessionDep,
    user_id: CurrentUserId,
) -> ResolvedTemplate:
    """Save the company text, or the project's own with ``project_id``."""
    if payload.project_id is not None:
        await verify_project_access(payload.project_id, user_id, session)
    await service.save(session, key, payload.language, payload.project_id, payload.to_text(), str(user_id))
    await session.commit()
    return _resolved_out(await service.resolve(session, key, payload.language, payload.project_id))


@router.delete(
    "/{key}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RequirePermission("letter_templates.edit"))],
)
async def reset_template(
    key: str,
    session: SessionDep,
    user_id: CurrentUserId,
    language: str = Query(..., max_length=10),
    project_id: uuid.UUID | None = Query(None),
) -> Response:
    """Reset to the next level (project to company, company to default)."""
    if project_id is not None:
        await verify_project_access(project_id, user_id, session)
    await service.reset(session, key, language, project_id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{key}/validate",
    response_model=list[IssueOut],
    dependencies=[Depends(RequirePermission("letter_templates.read"))],
)
async def validate_template(key: str, payload: ValidateRequest) -> list[IssueOut]:
    """Check an unsaved text with the same rules the save runs."""
    return _issues_out(service.validate(service.require_template(key), payload.to_text()))


@router.post(
    "/{key}/preview",
    response_model=None,
    dependencies=[Depends(RequirePermission("letter_templates.read"))],
)
async def preview_template(key: str, payload: PreviewRequest) -> Response:
    """Render the letter with sample values from an unsaved text."""
    template = service.require_template(key)
    if template.preview is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    body, media_type = await asyncio.to_thread(template.preview, payload.to_text(), payload.language)
    return Response(content=body, media_type=media_type, headers={"Cache-Control": "no-store"})
