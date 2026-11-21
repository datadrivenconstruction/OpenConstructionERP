"""HTTP surface and agent tool for brief extraction (card R5).

Both endpoints are stateless: they return a draft and never write the brief. A person reviews the
draft and saves it through the brief endpoints; AI output is a suggestion until confirmed.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.dependencies import SessionDep

from .auth import PrincipalDep, require_project
from .brief_draft import AnswerError, DraftContext, apply_answers
from .brief_extract import extract_brief
from .brief_model import SourceDoc
from .brief_sources import load_source_docs

router = APIRouter()
MAX_TEXT = 200_000


class ExtractRequest(BaseModel):
    document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    text: str | None = Field(default=None, max_length=MAX_TEXT)
    use_ai: bool = True
    base: dict | None = None  # current brief: confirmed values are kept
    editor: bool = False  # asked from the editor workspace: the person's editor AI choice applies, if any


class AnswersRequest(BaseModel):
    brief: dict
    answers: list[dict] = Field(min_length=1, max_length=100)


async def provider_completer(session, user_id: uuid.UUID, *, editor: bool = False):
    """The user's configured AI provider behind the ``Completer`` shape; ``None`` when none is set.

    For the editor, the person's own editor choice (service and model) wins; without one it is the ERP's."""
    from app.modules.ai.ai_client import call_ai, resolve_provider_key_model
    from app.modules.ai.repository import AISettingsRepository

    from .drafts_api import editor_ai_choice

    settings = await AISettingsRepository(session).get_by_user_id(user_id)
    choice = await editor_ai_choice(session, user_id) if editor else None
    try:
        provider, api_key, model = resolve_provider_key_model(settings, choice.preferred_model if choice else None)
    except ValueError:
        return None
    if choice is not None and choice.model:
        model = choice.model

    async def complete(*, system, prompt, image_base64=None, image_media_type="image/png"):
        return await call_ai(
            provider=provider,
            api_key=api_key,
            system=system,
            prompt=prompt,
            image_base64=image_base64,
            image_media_type=image_media_type,
            max_tokens=3000,
            model=model,
        )

    return complete


async def project_defaults(session, project_id: uuid.UUID) -> tuple[dict[str, Any], str]:
    from app.modules.projects.models import Project

    p = await session.get(Project, project_id)
    defaults: dict[str, Any] = {}
    if p is not None:
        if p.country_code:
            defaults["/country"] = p.country_code
        if p.locale:
            defaults["/locale"] = p.locale
        if p.name:
            defaults["/name"] = p.name
    return defaults, defaults.get("/locale", "en")


async def run_extraction(
    session, project_id: uuid.UUID, user_id: uuid.UUID, req: ExtractRequest, *, complete=None
) -> dict:
    docs = await load_source_docs(session, project_id, user_id, req.document_ids, with_images=req.use_ai)
    if req.text and req.text.strip():
        docs.append(SourceDoc(None, "Pasted description", "text", pages=[req.text]))
    if not docs:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Attach a document or give a description")
    if complete is None and req.use_ai:
        complete = await (
            provider_completer(session, user_id, editor=True) if req.editor else provider_completer(session, user_id)
        )
    defaults, locale = await project_defaults(session, project_id)
    base = req.base
    ctx = DraftContext(
        project_id=str(project_id),
        brief_id=str((base or {}).get("brief_id") or uuid.uuid4()),
        version=int((base or {}).get("version") or 1),
        locale=locale,
        defaults=defaults,
        base=base,
    )
    return (await extract_brief(docs, ctx, complete)).view()


@router.post("/projects/{project_id}/brief/extract")
async def extract(project_id: uuid.UUID, body: ExtractRequest, principal: PrincipalDep, session: SessionDep) -> dict:
    """Draft brief from attached documents and/or a pasted description, with questions."""
    await require_project(principal, project_id, session)
    if principal.via_link:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Extraction is started from the ERP")
    return await run_extraction(session, project_id, principal.user_id, body)


@router.post("/projects/{project_id}/brief/answers")
async def answers(project_id: uuid.UUID, body: AnswersRequest, principal: PrincipalDep, session: SessionDep) -> dict:
    """Apply a person's answers: values are set and marked confirmed by the caller."""
    await require_project(principal, project_id, session)
    if principal.via_link:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Answers are given in the ERP")
    try:
        return apply_answers(body.brief, body.answers, user_id=str(principal.user_id))
    except AnswerError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.errors) from exc


# ── ai_agents tool: proposals only, never a write ───────────────────────────


async def _tool_propose_brief(
    project_id: str | None = None,
    document_ids: list[str] | None = None,
    text: str | None = None,
    __agent_context__: dict | None = None,  # noqa: N803 - runner-injected key
) -> dict:
    from app.database import async_session_factory
    from app.modules.ai_agents.agents._access import assert_user_can_access_project, coerce_user_id

    user_id = coerce_user_id(__agent_context__)
    pid = project_id or (__agent_context__ or {}).get("project_id")
    try:
        project_uuid = uuid.UUID(str(pid))
        ids = [uuid.UUID(str(d)) for d in document_ids or []]
    except (ValueError, TypeError):
        return {"error": "unavailable", "detail": "Invalid project_id or document_ids."}
    if user_id is None:
        return {"error": "unavailable", "detail": "No authenticated user in scope."}
    async with async_session_factory() as session:
        if not await assert_user_can_access_project(session, project_uuid, user_id):
            return {"error": "unavailable", "detail": "Project not available."}
        try:
            result = await run_extraction(session, project_uuid, user_id, ExtractRequest(document_ids=ids, text=text))
        except HTTPException as exc:
            return {"error": "unavailable", "detail": str(exc.detail)}
    result["status"] = "proposal"
    result["detail"] = "These are proposals. A person must confirm every value and answer the questions."
    return result


def register_tool() -> None:
    from app.modules.ai_agents.base import FunctionTool, global_tool_registry

    global_tool_registry.register(
        FunctionTool(
            name="propose_design_brief",
            description=(
                "Read the project's attached documents (PDF, drawings, DWG/DXF, images, text) and return a draft "
                "design brief: every value cited with document, page and quote, status 'proposed', plus clarifying "
                "questions for missing or contradicting values. Writes nothing."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "document_ids": {"type": "array", "items": {"type": "string"}},
                    "text": {"type": "string", "description": "Free-text description of the project"},
                },
            },
            func=_tool_propose_brief,
        )
    )
