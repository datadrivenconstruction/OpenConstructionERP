# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Drafts, publishing, versions, previews and the resolver generators call.

Generators call :func:`resolve` (or :func:`published_letter_text` for the
tendering letters) to get the wording of a document; nothing else here is on a
render path. Every publish, restore and reset is written to the audit log.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.doc_templates.markup import to_html, to_plain
from app.core.doc_templates.pdf import SignatureImage, decode_png_data_url, render_document_pdf
from app.core.doc_templates.registry import DocumentKind, RecordDocument, all_kinds, get_kind
from app.core.doc_templates.resolve import Published, ResolvedText, normalise_locale, resolve_text
from app.core.doc_templates.rules import DRAFT_UNPUBLISHED, Issue, check_blocks, has_errors
from app.core.doc_templates.seller import resolve_seller
from app.modules.doc_templates.models import DocTemplate, DocTemplateVersion
from app.modules.doc_templates.repository import DocTemplateRepository

logger = logging.getLogger(__name__)

#: Versions kept per template; the published one is never pruned.
MAX_VERSIONS = 50
#: Preview time limit, seconds.
PREVIEW_TIMEOUT = 5.0


def require_kind(key: str) -> DocumentKind:
    """The registered kind or a 404."""
    from app.modules.doc_templates.kinds import register_builtin_kinds

    register_builtin_kinds()
    kind = get_kind(key)
    if kind is None or not kind_visible(kind):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown document kind: {key}")
    return kind


def kind_visible(kind: DocumentKind) -> bool:
    """A kind shows only while its owning module is enabled."""
    if kind.module in {"users", "core"}:
        return True
    try:
        from app.core.module_loader import module_loader

        if not module_loader._manifests:  # noqa: SLF001 - nothing loaded (tests, scripts): show all
            return True
        return module_loader.is_enabled(f"oe_{kind.module}")
    except Exception:  # noqa: BLE001 - registry state never hides a kind by accident
        return True


def visible_kinds() -> list[DocumentKind]:
    """Every registered kind whose module is enabled."""
    from app.modules.doc_templates.kinds import register_builtin_kinds

    register_builtin_kinds()
    return [k for k in all_kinds() if kind_visible(k)]


def clean_blocks(kind: DocumentKind, blocks: Mapping[str, Any]) -> dict[str, str]:
    """Keep only the kind's blocks, as strings, ``\\r\\n`` normalised."""
    return {b: str(blocks.get(b) or "").replace("\r\n", "\n") for b in kind.blocks if b in blocks}


def issues_of(kind: DocumentKind, blocks: Mapping[str, str]) -> list[Issue]:
    """Rule findings of a text."""
    return check_blocks(kind, blocks)


async def _published(repo: DocTemplateRepository, kind: str) -> tuple[dict[str, Published], str | None]:
    rows = await repo.for_kind(kind)
    versions = await repo.versions_by_ids([r.published_version_id for r in rows if r.published_version_id])
    out: dict[str, Published] = {}
    primary: str | None = None
    for row in rows:
        version = versions.get(row.published_version_id) if row.published_version_id else None
        if version is None:
            continue
        out[row.locale] = Published(version.id, dict(version.blocks or {}))
        if primary is None and any(str(v or "").strip() for v in (version.blocks or {}).values()):
            primary = row.locale
    return out, primary


async def resolve(session: AsyncSession, kind_key: str, locale: str | None) -> ResolvedText | None:
    """The wording a generator prints for *kind_key* in *locale*. ``None`` for an unknown kind.

    Never raises: a database problem yields the built-in wording.
    """
    from app.modules.doc_templates.kinds import register_builtin_kinds

    register_builtin_kinds()
    kind = get_kind(kind_key)
    if kind is None:
        return None
    try:
        published, primary = await _published(DocTemplateRepository(session), kind_key)
    except Exception:  # noqa: BLE001 - never break a document on a template read
        logger.warning("doc_templates: could not read templates for %s", kind_key, exc_info=True)
        published, primary = {}, None
    return resolve_text(kind, locale, published, primary)


async def published_letter_text(session: AsyncSession, key: str, language: str) -> Any | None:
    """A published template of a tendering letter as ``LetterText``, or ``None``.

    Called by ``letter_templates.service.resolve`` between the project's own
    wording and the older company override.
    """
    from app.core.letter_templates import get_template
    from app.modules.doc_templates.kinds import blocks_to_letter

    resolved = await resolve(session, key, language)
    template = get_template(key)
    if resolved is None or template is None or resolved.source == "default":
        return None
    fallback = template.defaults.get(language) or template.defaults[template.default_language]
    return blocks_to_letter(resolved.blocks, template.kind, set(template.placeholder_names), fallback)


async def published_blocks(
    session: AsyncSession, kind_key: str, locale: str | None
) -> tuple[dict[str, str], uuid.UUID | None] | None:
    """The firm's published blocks for a kind with its own generator, or ``None`` for built-in wording.

    Only blocks the firm wrote are returned; the caller keeps its own text for the rest.
    """
    from app.modules.doc_templates.kinds import register_builtin_kinds

    register_builtin_kinds()
    kind = get_kind(kind_key)
    if kind is None:
        return None
    try:
        published, primary = await _published(DocTemplateRepository(session), kind_key)
    except Exception:  # noqa: BLE001 - never break a document on a template read
        logger.warning("doc_templates: could not read templates for %s", kind_key, exc_info=True)
        return None
    resolved = resolve_text(kind, locale, published, primary)
    if resolved.source == "default":
        return None
    own = published.get(resolved.text_locale)
    blocks = {b: v for b, v in (own.blocks if own else {}).items() if (v or "").strip() and b in kind.blocks}
    return blocks, resolved.version_id


async def resolved_email_blocks(session: AsyncSession, kind_key: str, locale: str | None) -> dict[str, str] | None:
    """Published email wording, or ``None`` when the firm never published one (built-in mail unchanged)."""
    resolved = await resolve(session, kind_key, locale)
    if resolved is None or resolved.source == "default":
        return None
    return resolved.blocks


# ── List and editor ─────────────────────────────────────────────────────────


async def list_kinds(session: AsyncSession) -> list[dict[str, Any]]:
    """Rows of the Documents and Emails lists."""
    repo = DocTemplateRepository(session)
    rows = await repo.all_rows()
    versions = await repo.versions_by_ids([r.published_version_id for r in rows if r.published_version_id])
    by_kind: dict[str, list[DocTemplate]] = {}
    for row in rows:
        by_kind.setdefault(row.kind, []).append(row)
    out: list[dict[str, Any]] = []
    for kind in visible_kinds():
        own = by_kind.get(kind.key, [])
        languages: list[str] = []
        status_: str = "default"
        errors: list[str] = []
        last: DocTemplateVersion | None = None
        for row in own:
            version = versions.get(row.published_version_id) if row.published_version_id else None
            if version is not None and any(str(v or "").strip() for v in (version.blocks or {}).values()):
                languages.append(row.locale)
                status_ = "custom" if status_ == "default" else status_
                problems = [
                    i.rule_id
                    for i in issues_of(kind, clean_blocks(kind, version.blocks or {}))
                    if i.severity == "error"
                ]
                if problems:
                    errors += problems
            if version is not None and (last is None or version.created_at > last.created_at):
                last = version
            if row.draft_blocks is not None and status_ != "error":
                status_ = "draft"
        if errors:
            status_ = "error"
        out.append(
            {
                "key": kind.key,
                "channel": kind.channel,
                "module": kind.module,
                "label": kind.label,
                "status": status_,
                "languages": sorted(set(languages)),
                "builtin_languages": list(kind.languages),
                "last_published_at": last.created_at if last else None,
                "last_published_by": last.author_name if last else "",
                "error_rules": sorted(set(errors)),
            }
        )
    return out


async def editor_state(
    session: AsyncSession, kind: DocumentKind, locale: str, countries: list[str] | None = None
) -> dict[str, Any]:
    """Everything the editor shows for one kind and language."""
    lang = normalise_locale(locale)
    repo = DocTemplateRepository(session)
    row = await repo.get(kind.key, lang)
    published_map, primary = await _published(repo, kind.key)
    defaults = kind.default_blocks(lang)
    published = published_map.get(lang)
    published_text = {b: (published.blocks.get(b) or "") for b in kind.blocks} if published else None
    if published_text is not None and not any(v.strip() for v in published_text.values()):
        published_text = None
    if row is not None and row.draft_blocks is not None:
        text = {b: str(row.draft_blocks.get(b, "")) for b in kind.blocks}
    elif published_text is not None:
        text = {b: published_text[b] or defaults.get(b, "") for b in kind.blocks}
    else:
        legacy = await _legacy_letter_blocks(session, kind, lang)
        text = {b: legacy.get(b) or defaults.get(b, "") for b in kind.blocks} if legacy else dict(defaults)
    versions: list[dict[str, Any]] = []
    options: dict[str, Any] = {}
    if row is not None:
        current = await repo.version(row.published_version_id) if row.published_version_id else None
        options = dict(
            (row.draft_options if row.draft_options is not None else (current.options if current else {})) or {}
        )
        for v in await repo.versions(row.id):
            versions.append(
                {
                    "id": v.id,
                    "number": v.number,
                    "action": v.action,
                    "note": v.note,
                    "author_name": v.author_name,
                    "created_at": v.created_at,
                    "is_published": v.id == row.published_version_id,
                }
            )
    issues = issues_of(kind, text)
    if row is not None and row.draft_blocks is not None:
        issues.append(Issue(DRAFT_UNPUBLISHED, "info"))
    if published_text is None and primary and primary != lang:
        issues.append(Issue("doctpl.locale_fallback", "warning", "", {"language": lang, "fallback": primary}))
    from app.core.doc_templates.legal import legal_blocks_for_editor

    return {
        "key": kind.key,
        "channel": kind.channel,
        "module": kind.module,
        "label": kind.label,
        "locale": lang,
        "blocks": list(kind.blocks),
        "required_blocks": list(kind.required_blocks),
        "text": text,
        "default_text": defaults,
        "published_text": published_text,
        "has_draft": bool(row is not None and row.draft_blocks is not None),
        "has_translation": published_text is not None,
        "builtin_language": lang in kind.languages,
        "primary_locale": primary,
        "options": {"font": options.get("font", "sans"), "signature_image": options.get("signature_image", "")},
        "fields": [{"path": f.path, "type": f.type, "group": f.group, "sample": f.sample} for f in kind.fields],
        "versions": versions,
        "issues": [i.as_dict() for i in issues],
        "legal_blocks": legal_blocks_for_editor(kind.key, countries or [], lang),
        "has_records": kind.records is not None,
    }


async def _legacy_letter_blocks(session: AsyncSession, kind: DocumentKind, lang: str) -> dict[str, str]:
    """Company wording saved in the retired Letters tab, shown until a template is published.

    Letters still print it while nothing is published, so the editor opens on the
    same text instead of the shipped default.
    """
    from app.core.letter_templates import get_template

    template = get_template(kind.key)
    if template is None:
        return {}
    try:
        from app.modules.doc_templates.kinds import letter_to_blocks
        from app.modules.letter_templates.repository import LetterTemplateRepository

        row = await LetterTemplateRepository(session).get(kind.key, lang, None)
    except Exception:  # noqa: BLE001 - the editor never fails on the retired store
        return {}
    if row is None:
        return {}
    from app.core.letter_templates import LetterText

    text = LetterText(subject=row.subject, heading=row.heading, body=row.body, closing=row.closing)
    return {b: v for b, v in letter_to_blocks(text, template.kind, set(template.placeholder_names)).items() if v}


# ── Draft, publish, restore, reset ──────────────────────────────────────────


async def _row(session: AsyncSession, kind: DocumentKind, locale: str) -> DocTemplate:
    repo = DocTemplateRepository(session)
    row = await repo.get(kind.key, locale)
    return row if row is not None else await repo.create(kind.key, kind.channel, locale)


async def save_draft(
    session: AsyncSession,
    kind: DocumentKind,
    locale: str,
    blocks: Mapping[str, str],
    options: Mapping[str, Any] | None,
    user_id: str,
) -> list[Issue]:
    """Store the working text. Errors are returned, not refused: a draft may be broken."""
    lang = normalise_locale(locale)
    row = await _row(session, kind, lang)
    text = clean_blocks(kind, blocks)
    row.draft_blocks = text
    if options is not None:
        row.draft_options = dict(options)
    row.draft_updated_by = user_id
    row.draft_updated_at = datetime.now(UTC)
    await session.flush()
    return issues_of(kind, text)


async def discard_draft(session: AsyncSession, kind: DocumentKind, locale: str) -> None:
    """Drop the working text."""
    row = await DocTemplateRepository(session).get(kind.key, normalise_locale(locale))
    if row is not None:
        row.draft_blocks = None
        row.draft_options = None
        await session.flush()


def _letterhead_snapshot() -> dict[str, str]:
    seller = resolve_seller()
    return {
        "legal_name": seller.legal_name,
        "address": seller.address,
        "registration_line": seller.registration_line,
    }


async def _author_name(session: AsyncSession, user_id: str) -> str:
    try:
        from app.modules.users.models import User

        user = await session.get(User, uuid.UUID(user_id))
        return (user.full_name or user.email) if user is not None else ""
    except Exception:  # noqa: BLE001
        return ""


async def _new_version(
    session: AsyncSession,
    row: DocTemplate,
    blocks: Mapping[str, str],
    options: Mapping[str, Any],
    action: str,
    note: str,
    user_id: str,
) -> DocTemplateVersion:
    repo = DocTemplateRepository(session)
    version = await repo.add_version(
        DocTemplateVersion(
            template_id=row.id,
            number=await repo.next_number(row.id),
            blocks=dict(blocks),
            options=dict(options),
            letterhead=_letterhead_snapshot(),
            action=action,
            note=note,
            author_id=user_id,
            author_name=await _author_name(session, user_id),
        )
    )
    row.published_version_id = version.id
    row.draft_blocks = None
    row.draft_options = None
    await session.flush()
    await repo.prune(row.id, MAX_VERSIONS, {version.id})
    from app.core.audit import audit_log

    await audit_log(
        session,
        action=f"doc_template_{action}",
        entity_type="doc_template",
        entity_id=str(row.id),
        user_id=user_id,
        details={"kind": row.kind, "locale": row.locale, "version": version.number},
    )
    return version


async def publish(
    session: AsyncSession, kind: DocumentKind, locale: str, note: str, user_id: str
) -> DocTemplateVersion:
    """Publish the draft (or the current text when there is no draft). Errors refuse with 422."""
    lang = normalise_locale(locale)
    row = await _row(session, kind, lang)
    if row.draft_blocks is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Nothing to publish: save a draft first")
    blocks = clean_blocks(kind, row.draft_blocks)
    issues = issues_of(kind, blocks)
    if has_errors(issues):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"message": "Template has errors", "issues": [i.as_dict() for i in issues]},
        )
    defaults = kind.default_blocks(lang)
    stored = {b: t for b, t in blocks.items() if t.strip() != (defaults.get(b) or "").strip()}
    return await _new_version(session, row, stored, row.draft_options or {}, "publish", note, user_id)


async def restore(
    session: AsyncSession, kind: DocumentKind, locale: str, version_id: uuid.UUID, user_id: str
) -> DocTemplateVersion:
    """Publish a copy of an older version as the newest one."""
    lang = normalise_locale(locale)
    repo = DocTemplateRepository(session)
    row = await repo.get(kind.key, lang)
    old = await repo.version(version_id)
    if row is None or old is None or old.template_id != row.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")
    return await _new_version(session, row, old.blocks or {}, old.options or {}, "restore", f"v{old.number}", user_id)


async def reset(session: AsyncSession, kind: DocumentKind, locale: str, user_id: str) -> DocTemplateVersion:
    """Publish a version with no overrides: the document prints its built-in wording again."""
    row = await _row(session, kind, normalise_locale(locale))
    return await _new_version(session, row, {}, {}, "reset", "", user_id)


# ── Preview and test send ───────────────────────────────────────────────────


def sample_values(kind: DocumentKind) -> dict[str, str]:
    """The kind's samples, with the company's real name where it has one."""
    values = kind.samples()
    seller = resolve_seller()
    for path, value in seller.as_fields().items():
        if value and path in kind.field_paths:
            values[path] = value
    return values


def render_email(
    kind: DocumentKind, blocks: Mapping[str, str], values: Mapping[str, str], locale: str
) -> tuple[str, str]:
    """``(subject, html)`` of an email kind from blocks, in the branded shell."""
    from app.core.email.templates import wrap

    known = kind.field_paths
    subject = to_plain(blocks.get("subject") or "", values, known)
    title = to_plain(blocks.get("preheader") or "", values, known) or subject
    import html as _html

    body = to_html(blocks.get("body") or "", values, known)
    label = to_plain(blocks.get("cta_label") or "", values, known)
    footer = to_html(blocks.get("footer") or "", values, known) or None
    page = wrap(
        _html.escape(title),
        body,
        "https://example.com/preview" if label else None,
        _html.escape(label or "Open"),
        footer=footer,
        lang=locale,
        rtl=locale in {"ar", "he", "fa", "ur"},
    )
    return subject, page


def _render_sample(
    kind: DocumentKind, blocks: Mapping[str, str], options: Mapping[str, Any], locale: str
) -> tuple[bytes, str]:
    values = sample_values(kind)
    full = {
        b: (blocks.get(b) if (blocks.get(b) or "").strip() else kind.default_blocks(locale).get(b, "")) or ""
        for b in kind.blocks
    }
    if kind.preview is not None:
        return kind.preview(full, locale, values)
    if kind.channel == "email":
        _subject, page = render_email(kind, full, values, locale)
        return page.encode("utf-8"), "text/html; charset=utf-8"
    signature = None
    png = decode_png_data_url(str(options.get("signature_image") or ""))
    if png:
        signature = SignatureImage(png)
    pdf = render_document_pdf(
        blocks=full,
        values=values,
        known=kind.field_paths,
        appearance_type=kind.appearance_type,
        serif=options.get("font") == "serif",
        signature=signature,
        title_fallback=kind.label,
    )
    return pdf, "application/pdf"


async def preview(
    session: AsyncSession,
    kind: DocumentKind,
    locale: str,
    blocks: Mapping[str, str],
    options: Mapping[str, Any],
    record_id: str | None,
    project_ids: set[Any] | None,
    countries: list[str] | None = None,
) -> tuple[bytes, str]:
    """Render the draft: against one readable record when given, else the sample fixture."""
    lang = normalise_locale(locale)
    text = clean_blocks(kind, blocks)
    if record_id and kind.record_document is not None:
        pdf, _doc, _issues = await asyncio.wait_for(
            build_record_pdf(session, kind, record_id, lang, text, options, countries or [], project_ids=project_ids),
            PREVIEW_TIMEOUT,
        )
        return pdf, "application/pdf"
    if record_id and kind.record_preview is not None:
        allowed = {rid for rid, _label in await kind.records(session, project_ids)} if kind.records else set()
        if record_id not in allowed:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Record not found")
        data, media, _project = await asyncio.wait_for(
            kind.record_preview(session, record_id, text, lang), PREVIEW_TIMEOUT
        )
        return data, media
    return await asyncio.wait_for(asyncio.to_thread(_render_sample, kind, text, options, lang), PREVIEW_TIMEOUT)


async def _load_record(
    session: AsyncSession, kind: DocumentKind, record_id: str, lang: str, project_ids: set[Any] | None
) -> RecordDocument:
    assert kind.record_document is not None
    try:
        doc = await kind.record_document(session, record_id, lang)
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Record not found") from exc
    if project_ids is not None and doc.project_id not in project_ids:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Record not found")
    return doc


async def build_record_pdf(
    session: AsyncSession,
    kind: DocumentKind,
    record_id: str,
    lang: str,
    blocks: Mapping[str, str],
    options: Mapping[str, Any],
    countries: list[str],
    *,
    project_ids: set[Any] | None,
    strict: bool = False,
) -> tuple[bytes, RecordDocument, list[Issue]]:
    """Render one record through the generic generator.

    Missing mandatory data (standards on the kind, country law from packs)
    is returned as issues; with ``strict`` it refuses the document (422).
    """
    from app.core.doc_templates.legal import legal_notes
    from app.core.doc_templates.rules import check_mandatory

    doc = await _load_record(session, kind, record_id, lang, project_ids)
    notes, legal_issues = legal_notes(kind.key, countries, doc.values, lang)
    issues = [*check_mandatory(kind, doc.values), *legal_issues]
    if strict and has_errors(issues):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"message": "Mandatory document data is missing", "issues": [i.as_dict() for i in issues]},
        )
    defaults = kind.default_blocks(lang)
    full = {b: (blocks.get(b) if (blocks.get(b) or "").strip() else defaults.get(b, "")) or "" for b in kind.blocks}
    png = decode_png_data_url(str(options.get("signature_image") or ""))
    pdf = await asyncio.to_thread(
        render_document_pdf,
        blocks=full,
        values=doc.values,
        known=kind.field_paths,
        meta=doc.meta,
        table=doc.table,
        totals=doc.totals,
        legal=notes,
        signature=SignatureImage(png) if png else None,
        appearance_type=kind.appearance_type,
        serif=options.get("font") == "serif",
        title_fallback=kind.label,
    )
    return pdf, doc, issues


async def issue(
    session: AsyncSession,
    kind: DocumentKind,
    record_id: str,
    locale: str | None,
    countries: list[str],
    user_id: str,
    project_ids: set[Any] | None,
) -> tuple[bytes, str, str]:
    """Issue a record's document with the published wording and log the version it printed.

    Returns the PDF, its file name and the language of the wording it printed.
    """
    from app.modules.doc_templates.models import DocTemplateIssue

    if kind.record_document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This document is not issued here")
    lang = normalise_locale(locale) if locale else None
    if lang is None:
        lang = normalise_locale((await _load_record(session, kind, record_id, "en", project_ids)).locale)
    resolved = await resolve(session, kind.key, lang)
    assert resolved is not None
    options: dict[str, Any] = {}
    if resolved.version_id is not None:
        version = await session.get(DocTemplateVersion, resolved.version_id)
        options = dict(version.options or {}) if version is not None else {}
    pdf, doc, _issues = await build_record_pdf(
        session, kind, record_id, lang, resolved.blocks, options, countries, project_ids=project_ids, strict=True
    )
    session.add(
        DocTemplateIssue(
            kind=kind.key,
            record_id=str(record_id),
            project_id=doc.project_id,
            locale=lang,
            text_locale=resolved.text_locale,
            source=resolved.source,
            template_version_id=resolved.version_id,
            issued_by=user_id,
        )
    )
    await session.flush()
    return pdf, doc.filename, resolved.text_locale or lang


async def log_letter_issue(
    session: AsyncSession,
    kind_key: str,
    record_id: str,
    project_id: uuid.UUID | None,
    locale: str | None,
    user_id: str | None,
    *,
    wording: str | None = None,
) -> None:
    """Log the template version a tendering letter printed, as the other documents do.

    ``wording`` names a source that bypassed the published template (``project`` for the
    project's own text, ``override`` for one-off text); no version is logged for it.
    Never raises: a letter does not fail on its log.
    """
    from app.modules.doc_templates.models import DocTemplateIssue

    lang = normalise_locale(locale) if locale else "en"
    try:
        if wording is not None:
            row = {"source": wording, "text_locale": lang, "template_version_id": None}
        else:
            resolved = await resolve(session, kind_key, lang)
            if resolved is None:
                return
            row = {
                "source": resolved.source,
                "text_locale": resolved.text_locale,
                "template_version_id": resolved.version_id,
            }
        session.add(
            DocTemplateIssue(
                kind=kind_key,
                record_id=str(record_id),
                project_id=project_id,
                locale=lang,
                issued_by=user_id,
                **row,
            )
        )
    except Exception:  # noqa: BLE001 - a letter never fails on its issue log
        logger.warning("doc_templates: could not log the issue of %s", kind_key, exc_info=True)


async def send_test(kind: DocumentKind, locale: str, blocks: Mapping[str, str], to: str) -> tuple[bool, str]:
    """Send the draft of an email kind to the signed-in user's own address, subject prefixed ``[Test]``."""
    from app.config import get_settings
    from app.core.email import EmailMessage
    from app.core.email.service import email_delivery_enabled, get_email_service

    if kind.channel != "email":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only emails can be test-sent")
    if not email_delivery_enabled(get_settings()):
        return False, "email delivery is off"
    lang = normalise_locale(locale)
    full = {
        b: (blocks.get(b) if (blocks.get(b) or "").strip() else kind.default_blocks(lang).get(b, "")) or ""
        for b in kind.blocks
    }
    subject, page = render_email(kind, full, sample_values(kind), lang)
    result = await get_email_service().send(
        EmailMessage(to=to, subject=f"[Test] {subject}", html_body=page, tags=["doc_template_test", kind.key])
    )
    return bool(result.ok), "" if result.ok else str(result.reason or "")


async def workspace_countries(session: AsyncSession, payload: Mapping[str, Any], user_id: str) -> list[str]:
    """Countries of the workspace market profile; the active pack's country when none is saved.

    ``[]`` (no legal blocks) for an all-markets profile or when nothing is known.
    """
    from app.core import market_scope as ms

    countries: list[str] = []
    try:
        from app.core.market_router import company_holder_id
        from app.modules.users.models import User

        holder = await company_holder_id(session, dict(payload), uuid.UUID(user_id))
        user = await session.get(User, holder)
        profile = ms.stored_profile(dict(user.metadata_ or {})) if user is not None else None
        if profile is not None:
            countries = [c for c in ms.profile_markets(profile) if c != ms.ALL_MARKETS]
    except Exception:  # noqa: BLE001 - no profile means no country-specific blocks
        logger.debug("doc_templates: market profile unreadable", exc_info=True)
    if not countries:
        try:
            from app.core.market_router import _active_pack_country

            country = _active_pack_country()
            countries = [country.upper()] if country else []
        except Exception:  # noqa: BLE001
            countries = []
    return countries
