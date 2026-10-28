# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Forms & Checklists API routes.

Mounted at ``/api/v1/forms``. Two halves:

Templates (the reusable library):
    GET    /templates                       - list the library (global + project)
    POST   /templates                       - create a template
    GET    /categories                      - category metadata + counts
    GET    /templates/{id}                  - get one template
    PATCH  /templates/{id}                  - update (editing fields bumps version)
    POST   /templates/{id}/duplicate        - clone a template into a draft
    DELETE /templates/{id}                  - delete a template

Submissions (a template filled into a project):
    GET    /submissions                     - list a project's submissions
    POST   /submissions                     - start a submission from a template
    GET    /submissions/{id}                - get one submission
    PATCH  /submissions/{id}                - save draft answers
    POST   /submissions/{id}/complete       - validate + complete
    DELETE /submissions/{id}                - delete a submission
    GET    /submissions/{id}/export/pdf     - download the filled form as PDF
    POST   /submissions/{id}/create-inspection - raise a QA inspection from a form
"""

from __future__ import annotations

import io
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.core.content_disposition import attachment_disposition
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.forms.models import FormSubmission, FormTemplate
from app.modules.forms.schemas import (
    CategoryInfo,
    CompleteSubmissionRequest,
    SubmissionCreate,
    SubmissionResponse,
    SubmissionSummary,
    SubmissionUpdate,
    TemplateCreate,
    TemplateResponse,
    TemplateSummary,
    TemplateUpdate,
)
from app.modules.forms.service import FormsService
from app.modules.forms.validation import CATEGORIES, LAYOUT_TYPES

router = APIRouter(tags=["forms"])
logger = logging.getLogger(__name__)

_READ = Depends(RequirePermission("forms.read"))
_CREATE = Depends(RequirePermission("forms.create"))
_UPDATE = Depends(RequirePermission("forms.update"))
_DELETE = Depends(RequirePermission("forms.delete"))

_CATEGORY_LABELS: dict[str, str] = {
    "safety": "Safety",
    "quality": "Quality & acceptance",
    "handover": "Handover",
    "inspection": "Inspection",
    "commissioning": "Commissioning",
    "custom": "Custom",
}


def _service(session: SessionDep) -> FormsService:
    return FormsService(session)


# ── Response builders ─────────────────────────────────────────────────────────


def _template_response(t: FormTemplate) -> TemplateResponse:
    return TemplateResponse(
        id=t.id,
        project_id=t.project_id,
        name=t.name,
        description=t.description,
        category=t.category,
        status=t.status,
        version=t.version,
        fields=list(t.fields_data or []),
        tags=list(t.tags or []),
        is_seed=bool(t.is_seed),
        created_by=t.created_by,
        metadata=getattr(t, "metadata_", {}) or {},
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


def _template_summary(t: FormTemplate) -> TemplateSummary:
    fields = t.fields_data or []
    fillable = sum(1 for f in fields if isinstance(f, dict) and str(f.get("type")) not in LAYOUT_TYPES)
    return TemplateSummary(
        id=t.id,
        project_id=t.project_id,
        name=t.name,
        description=t.description,
        category=t.category,
        status=t.status,
        version=t.version,
        field_count=fillable,
        tags=list(t.tags or []),
        is_seed=bool(t.is_seed),
        updated_at=t.updated_at,
    )


def _submission_response(s: FormSubmission) -> SubmissionResponse:
    return SubmissionResponse(
        id=s.id,
        project_id=s.project_id,
        template_id=s.template_id,
        submission_number=s.submission_number,
        template_name=s.template_name,
        template_category=s.template_category,
        template_version=s.template_version,
        template_snapshot=list(s.template_snapshot or []),
        title=s.title,
        location=s.location,
        answers=dict(s.answers_data or {}),
        status=s.status,
        result=s.result,
        completed_at=s.completed_at,
        completed_by=s.completed_by,
        linked_inspection_id=s.linked_inspection_id,
        created_by=s.created_by,
        metadata=getattr(s, "metadata_", {}) or {},
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


def _submission_summary(s: FormSubmission) -> SubmissionSummary:
    return SubmissionSummary(
        id=s.id,
        project_id=s.project_id,
        submission_number=s.submission_number,
        template_name=s.template_name,
        template_category=s.template_category,
        title=s.title,
        location=s.location,
        status=s.status,
        result=s.result,
        completed_at=s.completed_at,
        created_by=s.created_by,
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


async def _guard_template_scope(template: FormTemplate, user_id: str, session: SessionDep) -> None:
    """A project-scoped template is only reachable by that project's members.

    Global (null-project) templates are the shared library and need no
    project check - the ``forms.*`` permission gate already applies.
    """
    if template.project_id is not None:
        await verify_project_access(template.project_id, str(user_id), session)


# ── Templates ────────────────────────────────────────────────────────────────


@router.get("/templates", response_model=list[TemplateSummary], dependencies=[_READ])
async def list_templates(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID | None = Query(default=None),
    category: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, description="Search name / description."),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
) -> list[TemplateSummary]:
    """List the template library: the global templates plus, when a project is
    given, that project's own templates."""
    if project_id is not None:
        await verify_project_access(project_id, str(user_id), session)
    templates, _ = await _service(session).repo.list_templates(
        project_id=project_id,
        include_global=True,
        category=category,
        status=status_filter,
        search=q,
        offset=offset,
        limit=limit,
    )
    return [_template_summary(t) for t in templates]


@router.get("/categories", response_model=list[CategoryInfo], dependencies=[_READ])
async def list_categories(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID | None = Query(default=None),
) -> list[CategoryInfo]:
    """Category chips for the library, each with a live template count."""
    if project_id is not None:
        await verify_project_access(project_id, str(user_id), session)
    counts = await _service(session).repo.category_counts(project_id)
    return [
        CategoryInfo(key=key, label=_CATEGORY_LABELS.get(key, key.title()), template_count=counts.get(key, 0))
        for key in CATEGORIES
    ]


@router.post("/templates", response_model=TemplateResponse, status_code=201, dependencies=[_CREATE])
async def create_template(
    data: TemplateCreate,
    session: SessionDep,
    user_id: CurrentUserId,
) -> TemplateResponse:
    """Author a reusable template. Omit ``project_id`` for the global library."""
    if data.project_id is not None:
        await verify_project_access(data.project_id, str(user_id), session)
    template = await _service(session).create_template(data, user_id=user_id)
    return _template_response(template)


@router.get("/templates/{template_id}", response_model=TemplateResponse, dependencies=[_READ])
async def get_template(
    template_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> TemplateResponse:
    """Get one template with its full field definitions."""
    svc = _service(session)
    template = await svc.get_template(template_id)
    await _guard_template_scope(template, user_id, session)
    return _template_response(template)


@router.patch("/templates/{template_id}", response_model=TemplateResponse, dependencies=[_UPDATE])
async def update_template(
    template_id: uuid.UUID,
    data: TemplateUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
) -> TemplateResponse:
    """Update a template. Editing its fields validates them and bumps the version;
    existing submissions keep their own snapshot and are untouched."""
    svc = _service(session)
    existing = await svc.get_template(template_id)
    await _guard_template_scope(existing, user_id, session)
    template = await svc.update_template(template_id, data)
    return _template_response(template)


@router.post(
    "/templates/{template_id}/duplicate", response_model=TemplateResponse, status_code=201, dependencies=[_CREATE]
)
async def duplicate_template(
    template_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> TemplateResponse:
    """Clone a template (including a seed) into a fresh editable draft."""
    svc = _service(session)
    existing = await svc.get_template(template_id)
    await _guard_template_scope(existing, user_id, session)
    template = await svc.duplicate_template(template_id, user_id=user_id)
    return _template_response(template)


@router.delete("/templates/{template_id}", status_code=204, dependencies=[_DELETE])
async def delete_template(
    template_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> None:
    """Delete a template. Past submissions survive (they hold their own snapshot)."""
    svc = _service(session)
    existing = await svc.get_template(template_id)
    await _guard_template_scope(existing, user_id, session)
    await svc.delete_template(template_id)


# ── Submissions ──────────────────────────────────────────────────────────────


@router.get("/submissions", response_model=list[SubmissionSummary], dependencies=[_READ])
async def list_submissions(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    status_filter: str | None = Query(default=None, alias="status"),
    category: str | None = Query(default=None),
    template_id: uuid.UUID | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[SubmissionSummary]:
    """List a project's form submissions."""
    await verify_project_access(project_id, str(user_id), session)
    subs, _ = await _service(session).repo.list_submissions(
        project_id,
        status=status_filter,
        category=category,
        template_id=template_id,
        offset=offset,
        limit=limit,
    )
    return [_submission_summary(s) for s in subs]


@router.post("/submissions", response_model=SubmissionResponse, status_code=201, dependencies=[_CREATE])
async def create_submission(
    data: SubmissionCreate,
    session: SessionDep,
    user_id: CurrentUserId,
) -> SubmissionResponse:
    """Start filling a template into a project (snapshots the template)."""
    await verify_project_access(data.project_id, str(user_id), session)
    svc = _service(session)
    template = await svc.get_template(data.template_id)
    # A project-scoped template belonging to a different project is off-limits;
    # global templates (null project) are usable by any project.
    if template.project_id is not None and template.project_id != data.project_id:
        raise HTTPException(status_code=404, detail="Template not found")
    submission = await svc.create_submission(data, user_id=user_id)
    return _submission_response(submission)


@router.get("/submissions/{submission_id}", response_model=SubmissionResponse, dependencies=[_READ])
async def get_submission(
    submission_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> SubmissionResponse:
    """Get one submission with its frozen template snapshot and answers."""
    svc = _service(session)
    submission = await svc.get_submission(submission_id)
    await verify_project_access(submission.project_id, str(user_id), session)
    return _submission_response(submission)


@router.patch("/submissions/{submission_id}", response_model=SubmissionResponse, dependencies=[_UPDATE])
async def update_submission(
    submission_id: uuid.UUID,
    data: SubmissionUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
) -> SubmissionResponse:
    """Save progress on a draft (answers merge key-by-key)."""
    svc = _service(session)
    existing = await svc.get_submission(submission_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    submission = await svc.update_submission(submission_id, data)
    return _submission_response(submission)


@router.post("/submissions/{submission_id}/complete", response_model=SubmissionResponse, dependencies=[_UPDATE])
async def complete_submission(
    submission_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    body: CompleteSubmissionRequest | None = None,
) -> SubmissionResponse:
    """Validate completeness (every required field answered, all answers
    consistent) and mark the submission complete. Returns 422 with the list of
    issues when the form is not ready."""
    svc = _service(session)
    existing = await svc.get_submission(submission_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    answers = body.answers if body else None
    submission = await svc.complete_submission(submission_id, answers=answers, user_id=user_id)
    return _submission_response(submission)


@router.delete("/submissions/{submission_id}", status_code=204, dependencies=[_DELETE])
async def delete_submission(
    submission_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> None:
    """Delete a submission."""
    svc = _service(session)
    existing = await svc.get_submission(submission_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    await svc.delete_submission(submission_id)


@router.get("/submissions/{submission_id}/export/pdf", dependencies=[_READ])
async def export_submission_pdf(
    submission_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> StreamingResponse:
    """Download a filled form as a PDF record."""
    svc = _service(session)
    submission = await svc.get_submission(submission_id)
    await verify_project_access(submission.project_id, str(user_id), session)
    pdf_bytes, filename = svc.build_submission_pdf(submission)
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": attachment_disposition(filename),
            # English, and this page cannot hold anything else. The record is a
            # hand-built single Courier text stream written through latin-1, so
            # a character outside that set is replaced before it reaches the
            # page whatever language the labels are in. Declaring English is
            # accurate about the labels; it is not a claim that the answers a
            # person typed survived, which is a separate defect on the script
            # axis rather than this one.
            "Content-Language": "en",
        },
    )


@router.post("/submissions/{submission_id}/create-inspection", status_code=201, dependencies=[_UPDATE])
async def create_inspection_from_submission(
    submission_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> dict[str, Any]:
    """Raise a QA inspection from a completed inspection/quality/handover form.

    A light, additive bridge toward QA: it pre-fills a QualityInspection with
    the form's title/location and turns each ``pass_fail_na`` answer into a
    checklist entry, then links the two so the inspection points back at the
    form. Idempotent - a form already linked to an inspection returns it as-is.
    The forms module keeps no hard dependency on inspections (import is lazy).
    """
    svc = _service(session)
    submission = await svc.get_submission(submission_id)
    await verify_project_access(submission.project_id, str(user_id), session)

    if submission.status != "completed":
        raise HTTPException(status_code=400, detail="Only a completed form can raise an inspection.")
    if submission.linked_inspection_id:
        return {
            "inspection_id": submission.linked_inspection_id,
            "submission_id": str(submission_id),
            "created": False,
        }

    try:
        from app.modules.inspections.models import QualityInspection
        from app.modules.inspections.repository import InspectionRepository
    except ImportError:
        raise HTTPException(status_code=501, detail="Inspections module is not available.")

    # Map pass_fail_na answers to inspection checklist entries.
    answers = submission.answers_data or {}
    checklist: list[dict[str, Any]] = []
    for field in submission.template_snapshot or []:
        if str(field.get("type")) != "pass_fail_na":
            continue
        key = str(field.get("key", ""))
        response = str(answers.get(key, "")).strip().lower()
        checklist.append(
            {
                "question": str(field.get("label", "")),
                "response_type": "pass_fail",
                "response": response or None,
                "critical": bool(field.get("required")),
            }
        )

    # Map the form category onto an allowed inspection type; default to general.
    category = str(submission.template_category or "").lower()
    inspection_type = category if category in ("handover", "general") else "general"

    inspection = QualityInspection(
        project_id=submission.project_id,
        inspection_type=inspection_type,
        title=f"{submission.template_name} ({submission.submission_number})"[:500],
        description=f"Raised from form {submission.submission_number}.",
        location=submission.location,
        status="completed" if submission.result else "scheduled",
        result=submission.result if submission.result in ("pass", "fail") else None,
        checklist_data=checklist,
        created_by=str(user_id),
        metadata_={
            "source": "forms",
            "submission_id": str(submission_id),
            "submission_number": submission.submission_number,
        },
    )
    inspection = await InspectionRepository(session).create(inspection)
    await svc.repo.update_submission_fields(submission_id, linked_inspection_id=str(inspection.id))
    logger.info("Inspection %s raised from form submission %s", inspection.id, submission_id)
    return {
        "inspection_id": str(inspection.id),
        "inspection_number": inspection.inspection_number,
        "submission_id": str(submission_id),
        "created": True,
    }
