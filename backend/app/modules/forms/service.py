# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Forms & Checklists service - business logic for templates and submissions."""

from __future__ import annotations

import io
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.content_disposition import attachment_disposition
from app.core.json_merge import merge_metadata
from app.modules.forms.formula import compute_formulas
from app.modules.forms.models import FormSubmission, FormTemplate
from app.modules.forms.repository import FormsRepository
from app.modules.forms.schemas import (
    SubmissionCreate,
    SubmissionUpdate,
    TemplateCreate,
    TemplateUpdate,
)
from app.modules.forms.seed import STARTER_TEMPLATES
from app.modules.forms.validation import (
    LAYOUT_TYPES,
    normalize_fields,
    validate_submission_answers,
    validate_template_fields,
)

logger = logging.getLogger(__name__)


def _raise_template_issues(issues: list) -> None:
    """Turn template-integrity issues into a 422 with a structured detail."""
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={
            "message": "The template has validation problems.",
            "issues": [i.as_dict() for i in issues],
        },
    )


class FormsService:
    """Business logic for form templates and submissions."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = FormsRepository(session)

    # ── Templates ────────────────────────────────────────────────────────────

    async def create_template(self, data: TemplateCreate, user_id: str | None) -> FormTemplate:
        """Create a template after validating its field integrity."""
        raw_fields = [f.model_dump() for f in data.fields]
        clean = normalize_fields(raw_fields)
        issues = validate_template_fields(clean)
        if issues:
            _raise_template_issues(issues)

        template = FormTemplate(
            project_id=data.project_id,
            name=data.name,
            description=data.description,
            category=data.category,
            status=data.status,
            version=1,
            fields_data=clean,
            tags=_clean_tags(data.tags),
            is_seed=False,
            created_by=user_id,
            metadata_=data.metadata,
        )
        template = await self.repo.add_template(template)
        logger.info("Form template created: %s (%s)", template.name, template.category)
        return template

    async def get_template(self, template_id: uuid.UUID) -> FormTemplate:
        """Get a template, raising 404 if absent."""
        template = await self.repo.get_template(template_id)
        if template is None:
            raise HTTPException(status_code=404, detail="Template not found")
        return template

    async def update_template(self, template_id: uuid.UUID, data: TemplateUpdate) -> FormTemplate:
        """Update a template. Changing its fields validates them and bumps the version.

        Past submissions are unaffected - each carries its own snapshot - so an
        edit here only changes what future submissions are filled against.
        """
        template = await self.get_template(template_id)
        fields: dict[str, Any] = data.model_dump(exclude_unset=True)

        if "fields" in fields:
            raw = fields.pop("fields")
            clean = normalize_fields([f if isinstance(f, dict) else f.model_dump() for f in (raw or [])])
            issues = validate_template_fields(clean)
            if issues:
                _raise_template_issues(issues)
            fields["fields_data"] = clean
            fields["version"] = int(template.version or 1) + 1

        if "tags" in fields and fields["tags"] is not None:
            fields["tags"] = _clean_tags(fields["tags"])

        if "metadata" in fields:
            incoming = fields.pop("metadata")
            if isinstance(incoming, dict):
                fields["metadata_"] = merge_metadata(getattr(template, "metadata_", None), incoming)

        if not fields:
            return template

        await self.repo.update_template_fields(template_id, **fields)
        await self.session.refresh(template)
        logger.info("Form template updated: %s (fields=%s)", template_id, list(fields.keys()))
        return template

    async def duplicate_template(self, template_id: uuid.UUID, user_id: str | None) -> FormTemplate:
        """Clone a template into a fresh, editable draft (never a seed)."""
        src = await self.get_template(template_id)
        copy = FormTemplate(
            project_id=src.project_id,
            name=f"{src.name} (copy)"[:300],
            description=src.description,
            category=src.category,
            status="draft",
            version=1,
            fields_data=list(src.fields_data or []),
            tags=list(src.tags or []),
            is_seed=False,
            created_by=user_id,
            metadata_={"duplicated_from": str(src.id)},
        )
        copy = await self.repo.add_template(copy)
        logger.info("Form template duplicated: %s -> %s", template_id, copy.id)
        return copy

    async def delete_template(self, template_id: uuid.UUID) -> None:
        """Delete a template. Submissions keep their snapshot (FK SET NULL)."""
        await self.get_template(template_id)
        await self.repo.delete_template(template_id)
        logger.info("Form template deleted: %s", template_id)

    # ── Submissions ──────────────────────────────────────────────────────────

    async def create_submission(self, data: SubmissionCreate, user_id: str | None) -> FormSubmission:
        """Start a submission by snapshotting a template into a project draft.

        The template's fields are frozen onto the submission so a later edit or
        deletion of the template cannot change or corrupt this filled form.
        """
        template = await self.get_template(data.template_id)

        submission = FormSubmission(
            project_id=data.project_id,
            template_id=template.id,
            template_name=template.name,
            template_category=template.category,
            template_version=int(template.version or 1),
            template_snapshot=list(template.fields_data or []),
            title=data.title,
            location=data.location,
            answers_data=dict(data.answers or {}),
            status="draft",
            created_by=user_id,
            metadata_=data.metadata,
        )
        submission = await self.repo.add_submission(submission)
        logger.info(
            "Form submission created: %s from template %s (project %s)",
            submission.submission_number,
            template.id,
            data.project_id,
        )
        return submission

    async def get_submission(self, submission_id: uuid.UUID) -> FormSubmission:
        """Get a submission, raising 404 if absent."""
        submission = await self.repo.get_submission(submission_id)
        if submission is None:
            raise HTTPException(status_code=404, detail="Submission not found")
        return submission

    async def update_submission(self, submission_id: uuid.UUID, data: SubmissionUpdate) -> FormSubmission:
        """Save progress on a draft submission (answers merge key-by-key)."""
        submission = await self.get_submission(submission_id)
        if submission.status == "completed":
            raise HTTPException(status_code=400, detail="A completed submission can no longer be edited.")

        fields: dict[str, Any] = data.model_dump(exclude_unset=True)

        if "answers" in fields:
            incoming = fields.pop("answers")
            if isinstance(incoming, dict):
                merged = dict(submission.answers_data or {})
                merged.update(incoming)
                fields["answers_data"] = merged

        if "metadata" in fields:
            incoming_meta = fields.pop("metadata")
            if isinstance(incoming_meta, dict):
                fields["metadata_"] = merge_metadata(getattr(submission, "metadata_", None), incoming_meta)

        if not fields:
            return submission

        await self.repo.update_submission_fields(submission_id, **fields)
        await self.session.refresh(submission)
        return submission

    async def complete_submission(
        self,
        submission_id: uuid.UUID,
        answers: dict[str, Any] | None,
        user_id: str | None,
    ) -> FormSubmission:
        """Validate completeness and mark a submission completed.

        Every required field must be answered and every provided answer must be
        consistent with its field, or the call is a 422 listing the issues.
        """
        submission = await self.get_submission(submission_id)
        if submission.status == "completed":
            raise HTTPException(status_code=400, detail="Submission is already completed.")

        final_answers = dict(submission.answers_data or {})
        if answers:
            final_answers.update(answers)

        snapshot = list(submission.template_snapshot or [])
        # Resolve computed (formula) fields from the entered answers before
        # validating and freezing them, so the stored form carries the derived
        # values and any formula-driven consistency is against real numbers.
        final_answers = compute_formulas(snapshot, final_answers)
        check = validate_submission_answers(snapshot, final_answers)
        if not check.is_complete:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "message": "The form is not complete yet.",
                    "issues": [i.as_dict() for i in check.issues],
                },
            )

        result = _derive_result(snapshot, final_answers)
        await self.repo.update_submission_fields(
            submission_id,
            answers_data=final_answers,
            status="completed",
            result=result,
            completed_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            completed_by=user_id,
        )
        await self.session.refresh(submission)
        logger.info("Form submission completed: %s (result=%s)", submission.submission_number, result)
        return submission

    async def delete_submission(self, submission_id: uuid.UUID) -> None:
        """Delete a submission."""
        await self.get_submission(submission_id)
        await self.repo.delete_submission(submission_id)
        logger.info("Form submission deleted: %s", submission_id)

    # ── PDF export ───────────────────────────────────────────────────────────

    def build_submission_pdf(self, submission: FormSubmission) -> tuple[bytes, str]:
        """Render a completed (or draft) submission to a simple PDF.

        Uses only the standard library so the export needs no extra dependency,
        mirroring the tendering package export. Returns ``(pdf_bytes, filename)``.
        """
        lines = _submission_pdf_lines(submission)
        pdf = _render_text_pdf(lines)
        safe_name = (submission.submission_number or "form").replace(" ", "_")
        filename = f"{safe_name}.pdf"
        return pdf, filename


# ── Seeding ──────────────────────────────────────────────────────────────────


async def seed_starter_templates_if_empty(session: AsyncSession) -> int:
    """Seed the built-in starter templates once, when none exist yet.

    Idempotent: if any seed template is already present (or a prior seed ran),
    it does nothing. Returns the number of templates created.
    """
    repo = FormsRepository(session)
    try:
        if await repo.count_seed_templates() > 0:
            return 0
    except Exception:
        # First-run before the table exists / transient DB hiccup - never break
        # startup over seeding. The next startup retries.
        logger.debug("forms: seed-count query failed, skipping seed this startup", exc_info=True)
        return 0

    created = 0
    for spec in STARTER_TEMPLATES:
        clean = normalize_fields(spec.get("fields", []))
        if validate_template_fields(clean):
            # A malformed starter template is a bug in seed.py; skip it rather
            # than abort the whole seed.
            logger.warning("forms: skipping invalid starter template %r", spec.get("name"))
            continue
        session.add(
            FormTemplate(
                project_id=None,
                name=str(spec["name"]),
                description=spec.get("description"),
                category=str(spec.get("category", "custom")),
                status="published",
                version=1,
                fields_data=clean,
                tags=_clean_tags(spec.get("tags", [])),
                is_seed=True,
                created_by=None,
                metadata_={},
            )
        )
        created += 1

    if created:
        await session.commit()
        logger.info("forms: seeded %d starter templates", created)
    return created


# ── Pure helpers ─────────────────────────────────────────────────────────────


def _clean_tags(tags: Any) -> list[str]:
    """Trim, de-duplicate and cap a tag list."""
    if not isinstance(tags, (list, tuple)):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        text = str(tag).strip()[:40]
        low = text.lower()
        if text and low not in seen:
            seen.add(low)
            out.append(text)
        if len(out) >= 20:
            break
    return out


def _derive_result(fields: list[dict[str, Any]], answers: dict[str, Any]) -> str | None:
    """Roll pass_fail_na answers into one result: fail > pass > na > None.

    A single failed checklist item fails the whole form; otherwise any pass
    makes it a pass; a form of only n/a answers is ``na``; a form with no
    pass/fail fields has no result.
    """
    saw_pass = saw_na = saw_field = False
    for field in fields:
        if str(field.get("type")) != "pass_fail_na":
            continue
        saw_field = True
        value = str(answers.get(str(field.get("key")), "")).strip().lower()
        if value == "fail":
            return "fail"
        if value == "pass":
            saw_pass = True
        elif value == "na":
            saw_na = True
    if not saw_field:
        return None
    if saw_pass:
        return "pass"
    if saw_na:
        return "na"
    return None


def _submission_pdf_lines(submission: FormSubmission) -> list[str]:
    """Flatten a submission into printable text lines (label: answer)."""
    lines: list[str] = []
    lines.append(f"{submission.template_name}")
    lines.append(f"Ref: {submission.submission_number}    Status: {submission.status}")
    if submission.title:
        lines.append(f"Title: {submission.title}")
    if submission.location:
        lines.append(f"Location: {submission.location}")
    if submission.result:
        lines.append(f"Result: {submission.result.upper()}")
    if submission.completed_at:
        lines.append(f"Completed: {submission.completed_at}")
    lines.append("")

    answers = submission.answers_data or {}
    for field in submission.template_snapshot or []:
        ftype = str(field.get("type", ""))
        label = str(field.get("label", ""))
        if ftype in LAYOUT_TYPES:
            lines.append("")
            lines.append(f"== {label} ==")
            continue
        key = str(field.get("key", ""))
        lines.append(f"{label}: {_format_answer(ftype, answers.get(key))}")
    return lines


def _format_answer(ftype: str, value: Any) -> str:
    """Render one answer value as a compact string for the PDF."""
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return "-"
    if ftype == "checkbox":
        return "Yes" if value is True else "No"
    if ftype == "multi_choice" and isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value) or "-"
    if ftype == "pass_fail_na":
        return str(value).upper()
    if ftype == "signature":
        if isinstance(value, dict):
            name = str(value.get("name", "") or "").strip()
            return f"Signed: {name}" if name else "Signed"
        return "Signed" if str(value).strip() else "-"
    if ftype == "photo":
        count = len(value) if isinstance(value, (list, tuple)) else (1 if str(value).strip() else 0)
        return f"{count} photo(s)"
    return str(value)


def _render_text_pdf(lines: list[str]) -> bytes:
    """Build a minimal single-page text PDF from ``lines`` using only stdlib.

    A pared-down version of the tendering package export: one Courier text
    stream, fixed 12pt leading, clipped to the page. Enough for a clean,
    printable record without pulling in reportlab.
    """
    buf = io.BytesIO()

    def _w(text: str) -> None:
        buf.write(text.encode("latin-1", errors="replace"))

    offsets: list[int] = []

    def _obj() -> int:
        idx = len(offsets) + 1
        offsets.append(buf.tell())
        _w(f"{idx} 0 obj\n")
        return idx

    y = 780
    stream_lines: list[str] = ["BT", "/F1 10 Tf"]
    for line in lines:
        safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream_lines.append(f"1 0 0 1 40 {y} Tm")
        stream_lines.append(f"({safe}) Tj")
        y -= 14
        if y < 40:
            break
    stream_lines.append("ET")
    stream_content = "\n".join(stream_lines)

    _w("%PDF-1.4\n")
    _obj()
    _w("<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")
    _obj()
    _w("<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n")
    _obj()
    _w(
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        "/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n"
    )
    _obj()
    _w(f"<< /Length {len(stream_content)} >>\nstream\n{stream_content}\nendstream\nendobj\n")
    _obj()
    _w("<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>\nendobj\n")

    xref_offset = buf.tell()
    _w("xref\n")
    _w(f"0 {len(offsets) + 1}\n")
    _w("0000000000 65535 f \n")
    for off in offsets:
        _w(f"{off:010d} 00000 n \n")
    _w("trailer\n")
    _w(f"<< /Size {len(offsets) + 1} /Root 1 0 R >>\n")
    _w("startxref\n")
    _w(f"{xref_offset}\n")
    _w("%%EOF\n")

    return buf.getvalue()


# Re-exported so the router can build the download header without importing the
# content_disposition module directly.
__all__ = ["FormsService", "attachment_disposition", "seed_starter_templates_if_empty"]
