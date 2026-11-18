# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Document layouts: drafts, published versions, variants, scopes, preview and issue.

A layout is stored per ``(kind, scope, variant)``. ``scope`` is ``workspace``
(the company default) or ``project:<uuid>`` (that project's override);
``variant`` names one of several layouts of the same document, one per scope
being the default. A published version holds the whole normalised template;
an empty document means "the standard template", which is what reset
publishes, so a reset document prints exactly as it did before any layout.

Issuing resolves, in order: the asked version (a reprint); the asked variant in
the project, then in the workspace; the project's default; the workspace's
default; the standard template.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.doc_templates.layout.compile import compile_layout
from app.core.doc_templates.layout.spec import LayoutContext, LayoutSpec, all_layouts, get_layout
from app.core.doc_templates.layout.template import (
    BLOCK_TYPES,
    COLUMN_CHILD_TYPES,
    CONDITION_OPS,
    check,
    iter_blocks,
    locks_for,
    normalise,
)
from app.core.doc_templates.rules import Issue, has_errors
from app.modules.doc_templates.models import WORKSPACE_SCOPE, DocClause, DocLayout, DocLayoutVersion, DocTemplateIssue
from app.modules.doc_templates.repository import DocLayoutRepository

logger = logging.getLogger(__name__)

MAX_VERSIONS = 50
MAX_VARIANTS = 8
STANDARD_VARIANT = "standard"
EXPORT_FORMAT = "openconstructionerp.doc-layout"

__all__ = [
    "EXPORT_FORMAT",
    "Resolved",
    "data_issues",
    "diff_templates",
    "issue_document",
    "issue_for_user",
    "layout_visible",
    "published_layout",
    "require_layout",
    "scope_for",
]


# ── Lookup ───────────────────────────────────────────────────────────────


def layout_visible(spec: LayoutSpec) -> bool:
    """A layout shows only while its owning module is enabled."""
    try:
        from app.core.module_loader import module_loader

        if not module_loader._manifests:  # noqa: SLF001 - nothing loaded (tests, scripts): show all
            return True
        return module_loader.is_enabled(f"oe_{spec.module}")
    except Exception:  # noqa: BLE001 - registry state never hides a document by accident
        return True


_KNOWN_PROVIDERS = (
    ("app.modules.procurement.layouts", "register_procurement_layouts"),
    ("app.modules.finance.layouts", "register_finance_layouts"),
    ("app.modules.changeorders.layouts", "register_changeorder_layouts"),
)


def _register_known() -> None:
    import importlib

    for module, name in _KNOWN_PROVIDERS:
        try:
            getattr(importlib.import_module(module), name)()
        except Exception:  # noqa: BLE001 - the module may be absent
            logger.debug("doc_templates: layouts of %s unavailable", module, exc_info=True)


def visible_layouts() -> list[LayoutSpec]:
    """Every registered layout whose module is enabled."""
    _register_known()
    return [s for s in all_layouts() if layout_visible(s)]


def require_layout(key: str) -> LayoutSpec:
    """The registered layout or a 404."""
    _register_known()
    spec = get_layout(key)
    if spec is None or not layout_visible(spec):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown document")
    return spec


def scope_for(project_id: uuid.UUID | str | None) -> str:
    """``workspace`` or ``project:<uuid>``."""
    return f"project:{uuid.UUID(str(project_id))}" if project_id else WORKSPACE_SCOPE


def clean_variant(value: str | None) -> str:
    """A variant key: lower case letters, digits and underscores; ``standard`` when empty."""
    import re

    text = re.sub(r"[^a-z0-9_]+", "_", (value or "").strip().lower()).strip("_")[:40]
    return text or STANDARD_VARIANT


# ── Spec description for the editor ──────────────────────────────────────


def describe(spec: LayoutSpec, locale: str, countries: Sequence[str]) -> dict[str, Any]:
    """What the editor offers: fields with sample values, collections, sections, locks, block types."""
    sample = spec.sample(locale)
    return {
        "key": spec.key,
        "module": spec.module,
        "label": spec.label,
        "languages": list(spec.languages),
        "statuses": list(spec.statuses),
        "block_types": list(BLOCK_TYPES),
        "column_child_types": sorted(COLUMN_CHILD_TYPES),
        "condition_ops": list(CONDITION_OPS),
        "fields": [
            {
                "path": f.path,
                "type": f.type,
                "group": f.group,
                "label": sample.labels.get(f"field:{f.path}", ""),
                "sample": sample.values.get(f.path, f.sample),
            }
            for f in spec.fields
        ]
        + [
            {"path": "page.number", "type": "number", "group": "page", "label": "", "sample": "1"},
            {"path": "page.total", "type": "number", "group": "page", "label": "", "sample": "2"},
        ],
        "collections": [
            {
                "id": c.id,
                "label": c.label,
                "columns": [
                    {
                        "id": col.id,
                        "label": col.label,
                        "heading": sample.labels.get(f"column:{c.id}.{col.id}", col.label),
                        "format": col.format,
                        "required": col.required,
                        "right": col.right,
                    }
                    for col in c.columns
                ],
            }
            for c in spec.collections
        ],
        "sections": [
            {
                "id": s.id,
                "label": s.label,
                "heading": sample.labels.get(f"section:{s.id}", ""),
                "required": s.required,
                "builtin": s.builtin,
            }
            for s in spec.sections
        ],
        "locks": locks_for(spec, countries).as_dict(),
        "legal": _legal_for_editor(spec, countries, locale),
        "standard": normalise(spec.standard(_legacy_sections(spec))),
    }


def _legal_for_editor(spec: LayoutSpec, countries: Sequence[str], locale: str) -> list[dict[str, str]]:
    from app.core.doc_templates.legal import legal_blocks_for_editor

    try:
        return legal_blocks_for_editor(spec.key, countries, locale)
    except Exception:  # noqa: BLE001 - an unreadable pack file never hides the editor
        logger.debug("doc_templates: legal blocks unreadable", exc_info=True)
        return []


def _legacy_sections(spec: LayoutSpec) -> Mapping[str, bool] | None:
    if not spec.appearance_type:
        return None
    try:
        from app.core.pdf_appearance import resolve_sections

        return resolve_sections(spec.appearance_type)
    except Exception:  # noqa: BLE001 - per-type settings unreadable: print every section
        return None


def standard_template(spec: LayoutSpec) -> dict[str, Any]:
    """The standard template with the workspace's per-type section switches applied."""
    return spec.standard(_legacy_sections(spec))


# ── State ────────────────────────────────────────────────────────────────


def _issues(spec: LayoutSpec, template: Mapping[str, Any], countries: Sequence[str]) -> list[Issue]:
    return check(template, spec, locks_for(spec, countries))


def _version_out(v: DocLayoutVersion) -> dict[str, Any]:
    return {
        "id": str(v.id),
        "number": v.number,
        "action": v.action,
        "note": v.note,
        "author_name": v.author_name,
        "created_at": v.created_at.isoformat() if v.created_at else None,
    }


def _variant_out(row: DocLayout) -> dict[str, Any]:
    return {
        "variant": row.variant,
        "name": row.name or row.variant,
        "scope": row.scope,
        "is_default": bool(row.is_default),
        "published": row.published_version_id is not None,
        "has_draft": row.draft is not None,
    }


async def state(
    session: AsyncSession,
    spec: LayoutSpec,
    *,
    scope: str,
    variant: str,
    countries: Sequence[str],
) -> dict[str, Any]:
    """Editor state for one layout row: template in force, draft, versions, variants, issues."""
    repo = DocLayoutRepository(session)
    row = await repo.get(spec.key, scope, variant)
    published: dict[str, Any] | None = None
    published_number: int | None = None
    versions: list[dict[str, Any]] = []
    if row is not None:
        rows = await repo.versions(row.id)
        versions = [_version_out(v) for v in rows]
        current = next((v for v in rows if v.id == row.published_version_id), None)
        if current is not None:
            published = normalise(current.document) if current.document else None
            published_number = current.number
    inherited = None
    if scope != WORKSPACE_SCOPE and (row is None or row.published_version_id is None):
        workspace = await published_layout(session, spec.key, project_id=None, variant=variant)
        inherited = workspace.template if workspace is not None else None
    in_force = published or inherited or normalise(standard_template(spec))
    draft = normalise(row.draft) if row is not None and row.draft is not None else None
    scopes = [WORKSPACE_SCOPE] if scope == WORKSPACE_SCOPE else [WORKSPACE_SCOPE, scope]
    variants = [_variant_out(r) for r in await repo.in_scopes(spec.key, scopes)]
    return {
        "key": spec.key,
        "scope": scope,
        "variant": variant,
        "name": (row.name if row is not None else "") or variant,
        "is_default": bool(row.is_default) if row is not None else variant == STANDARD_VARIANT,
        "template": draft or in_force,
        "published": published,
        "published_number": published_number,
        "inherits": "workspace" if inherited is not None else ("standard" if published is None else None),
        "has_draft": draft is not None,
        "draft_updated_at": row.draft_updated_at.isoformat() if row is not None and row.draft_updated_at else None,
        "versions": versions,
        "variants": variants,
        "issues": [i.as_dict() for i in _issues(spec, draft or in_force, countries)],
    }


async def _row(session: AsyncSession, spec: LayoutSpec, scope: str, variant: str, name: str = "") -> DocLayout:
    repo = DocLayoutRepository(session)
    row = await repo.get(spec.key, scope, variant)
    if row is not None:
        return row
    existing = await repo.in_scopes(spec.key, [scope])
    if len(existing) >= MAX_VARIANTS:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"At most {MAX_VARIANTS} variants per scope")
    row = await repo.create(spec.key, scope, variant, name)
    if not any(r.is_default for r in existing):
        row.is_default = True
    return row


async def save_draft(
    session: AsyncSession,
    spec: LayoutSpec,
    *,
    scope: str,
    variant: str,
    template: Mapping[str, Any],
    name: str,
    user_id: str,
) -> None:
    """Store the working template. Never blocks on errors: publishing does."""
    row = await _row(session, spec, scope, variant, name)
    if name.strip():
        row.name = name.strip()[:120]
    row.draft = normalise(template)
    row.draft_updated_by = user_id
    row.draft_updated_at = datetime.now(UTC)
    await session.flush()


async def discard_draft(session: AsyncSession, spec: LayoutSpec, *, scope: str, variant: str) -> None:
    """Drop the working template."""
    row = await DocLayoutRepository(session).get(spec.key, scope, variant)
    if row is not None and row.draft is not None:
        row.draft = None
        row.draft_updated_at = None
        await session.flush()


async def _author_name(session: AsyncSession, user_id: str) -> str:
    try:
        from app.modules.users.models import User

        user = await session.get(User, uuid.UUID(user_id))
        return (user.full_name or user.email) if user is not None else ""
    except Exception:  # noqa: BLE001
        return ""


async def _new_version(
    session: AsyncSession, row: DocLayout, document: Mapping[str, Any], action: str, note: str, user_id: str
) -> DocLayoutVersion:
    repo = DocLayoutRepository(session)
    version = await repo.add_version(
        DocLayoutVersion(
            layout_id=row.id,
            number=await repo.next_number(row.id),
            document=dict(document),
            action=action,
            note=note[:500],
            author_id=user_id,
            author_name=await _author_name(session, user_id),
        )
    )
    row.published_version_id = version.id
    row.draft = None
    row.draft_updated_at = None
    await session.flush()
    await repo.prune(row.id, MAX_VERSIONS, {version.id})
    from app.core.audit import audit_log

    await audit_log(
        session,
        action=f"doc_layout_{action}",
        entity_type="doc_layout",
        entity_id=str(row.id),
        user_id=user_id,
        details={"kind": row.kind, "scope": row.scope, "variant": row.variant, "version": version.number},
    )
    return version


def _refuse(issues: list[Issue]) -> None:
    if has_errors(issues):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"message": "Template has errors", "issues": [i.as_dict() for i in issues]},
        )


async def publish(
    session: AsyncSession,
    spec: LayoutSpec,
    *,
    scope: str,
    variant: str,
    note: str,
    countries: Sequence[str],
    user_id: str,
) -> DocLayoutVersion:
    """Publish the draft as a new version. Errors (a locked block hidden, an unknown field) refuse with 422."""
    row = await DocLayoutRepository(session).get(spec.key, scope, variant)
    if row is None or row.draft is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Nothing to publish: save a draft first")
    template = normalise(row.draft)
    _refuse(_issues(spec, template, countries))
    return await _new_version(session, row, template, "publish", note, user_id)


async def restore(
    session: AsyncSession,
    spec: LayoutSpec,
    *,
    scope: str,
    variant: str,
    version_id: uuid.UUID,
    countries: Sequence[str],
    user_id: str,
) -> DocLayoutVersion:
    """Publish a copy of an older version as the newest one; refused if today's locks reject it."""
    repo = DocLayoutRepository(session)
    row = await repo.get(spec.key, scope, variant)
    old = await repo.version(version_id)
    if row is None or old is None or old.layout_id != row.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")
    if old.document:
        _refuse(_issues(spec, normalise(old.document), countries))
    return await _new_version(session, row, old.document or {}, "restore", f"v{old.number}", user_id)


async def reset(session: AsyncSession, spec: LayoutSpec, *, scope: str, variant: str, user_id: str) -> DocLayoutVersion:
    """Publish "standard": the document prints as the platform ships it."""
    row = await _row(session, spec, scope, variant)
    return await _new_version(session, row, {}, "reset", "", user_id)


async def import_template(
    session: AsyncSession,
    spec: LayoutSpec,
    *,
    scope: str,
    variant: str,
    payload: Mapping[str, Any],
    user_id: str,
) -> None:
    """Load an exported layout into the draft. The kind must match; the content is normalised."""
    if payload.get("format") != EXPORT_FORMAT or payload.get("kind") != spec.key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="This file is not a layout of this document"
        )
    template = payload.get("template")
    if not isinstance(template, Mapping):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="The file holds no layout")
    await save_draft(
        session,
        spec,
        scope=scope,
        variant=variant,
        template=template,
        name=str(payload.get("name") or ""),
        user_id=user_id,
    )


def export_payload(spec: LayoutSpec, template: Mapping[str, Any], name: str) -> dict[str, Any]:
    """A layout as a portable JSON file."""
    return {"format": EXPORT_FORMAT, "schema": 1, "kind": spec.key, "name": name, "template": dict(template)}


async def set_default(session: AsyncSession, spec: LayoutSpec, *, scope: str, variant: str, user_id: str) -> None:
    """Make *variant* the one a document prints when no variant is asked for."""
    repo = DocLayoutRepository(session)
    row = await _row(session, spec, scope, variant)
    for other in await repo.in_scopes(spec.key, [scope]):
        other.is_default = other.id == row.id
    await session.flush()
    from app.core.audit import audit_log

    await audit_log(
        session,
        action="doc_layout_default",
        entity_type="doc_layout",
        entity_id=str(row.id),
        user_id=user_id,
        details={"kind": spec.key, "scope": scope, "variant": variant},
    )


async def delete_variant(session: AsyncSession, spec: LayoutSpec, *, scope: str, variant: str, user_id: str) -> None:
    """Delete one variant and its versions. Issued documents keep their log rows."""
    repo = DocLayoutRepository(session)
    row = await repo.get(spec.key, scope, variant)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Variant not found")
    was_default = row.is_default
    await repo.delete(row)
    if was_default:
        rest = await repo.in_scopes(spec.key, [scope])
        if rest:
            rest[0].is_default = True
            await session.flush()
    from app.core.audit import audit_log

    await audit_log(
        session,
        action="doc_layout_delete",
        entity_type="doc_layout",
        entity_id=str(row.id),
        user_id=user_id,
        details={"kind": spec.key, "scope": scope, "variant": variant},
    )


async def version_document(session: AsyncSession, spec: LayoutSpec, version_id: uuid.UUID) -> dict[str, Any]:
    """The template one version printed; the standard template for a reset version."""
    repo = DocLayoutRepository(session)
    version = await repo.version(version_id)
    row = await session.get(DocLayout, version.layout_id) if version is not None else None
    if version is None or row is None or row.kind != spec.key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")
    return normalise(version.document) if version.document else normalise(standard_template(spec))


# ── Diff ─────────────────────────────────────────────────────────────────


def diff_templates(old: Mapping[str, Any], new: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Block-level changes from *old* to *new*: added, removed, moved, changed (with the keys that changed).

    Page, branding, header, footer, watermark and title changes are reported as pseudo blocks.
    """
    changes: list[dict[str, Any]] = []
    for part in ("title", "subject", "show_subject", "page", "branding", "watermark", "header", "footer"):
        if (old.get(part) or None) != (new.get(part) or None):
            changes.append({"id": part, "type": part, "change": "changed", "keys": []})
    before = {b["id"]: b for b in iter_blocks(old.get("body") or [])}
    after = {b["id"]: b for b in iter_blocks(new.get("body") or [])}
    order_before = [i for i in before if i in after]
    order_after = [i for i in after if i in before]
    for block_id, block in after.items():
        if block_id not in before:
            changes.append({"id": block_id, "type": block.get("type"), "change": "added", "keys": []})
            continue
        prior = before[block_id]
        keys = sorted(k for k in set(prior) | set(block) if k != "children" and prior.get(k) != block.get(k))
        if keys:
            changes.append({"id": block_id, "type": block.get("type"), "change": "changed", "keys": keys})
        elif order_before.index(block_id) != order_after.index(block_id):
            changes.append({"id": block_id, "type": block.get("type"), "change": "moved", "keys": []})
    for block_id, block in before.items():
        if block_id not in after:
            changes.append({"id": block_id, "type": block.get("type"), "change": "removed", "keys": []})
    return changes


# ── Clauses ──────────────────────────────────────────────────────────────


def _clause_out(c: DocClause) -> dict[str, Any]:
    return {"key": c.key, "category": c.category, "title": dict(c.title or {}), "text": dict(c.text or {})}


async def list_clauses(session: AsyncSession) -> list[dict[str, Any]]:
    """The clause library."""
    return [_clause_out(c) for c in await DocLayoutRepository(session).clauses()]


async def save_clause(
    session: AsyncSession, key: str, category: str, title: Mapping[str, str], text: Mapping[str, str], user_id: str
) -> dict[str, Any]:
    """Create or replace one clause. Text is the same markdown subset as template blocks."""
    from app.core.doc_templates.markup import has_raw_html

    if any(has_raw_html(str(v)) for v in (*title.values(), *text.values())):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Use the text format, not HTML")
    repo = DocLayoutRepository(session)
    clause = await repo.clause(key)
    if clause is None:
        clause = DocClause(key=key)
        session.add(clause)
    clause.category = category[:40]
    clause.title = {str(k)[:10]: str(v)[:200] for k, v in title.items()}
    clause.text = {str(k)[:10]: str(v)[:4000] for k, v in text.items()}
    clause.updated_by = user_id
    await session.flush()
    return _clause_out(clause)


async def delete_clause(session: AsyncSession, key: str) -> None:
    """Delete one clause; blocks that used it print their own text or nothing."""
    clause = await DocLayoutRepository(session).clause(key)
    if clause is not None:
        await session.delete(clause)
        await session.flush()


async def clause_map(session: AsyncSession) -> dict[str, dict[str, Any]]:
    """``key -> {"title", "text"}`` for the compiler."""
    try:
        return {
            c.key: {"title": c.title or {}, "text": c.text or {}} for c in await DocLayoutRepository(session).clauses()
        }
    except Exception:  # noqa: BLE001 - a missing clause table never stops a document
        return {}


# ── Resolve, preview and issue ───────────────────────────────────────────


@dataclass(frozen=True)
class Resolved:
    """The template a document prints and where it came from. ``template`` is ``None`` for standard."""

    template: dict[str, Any] | None
    version_id: uuid.UUID | None
    scope: str
    variant: str


async def _published_of(session: AsyncSession, row: DocLayout | None) -> Resolved | None:
    if row is None or row.published_version_id is None:
        return None
    version = await DocLayoutRepository(session).version(row.published_version_id)
    if version is None:
        return None
    template = normalise(version.document) if version.document else None
    return Resolved(template, version.id, row.scope, row.variant)


async def published_layout(
    session: AsyncSession,
    key: str,
    *,
    project_id: uuid.UUID | str | None,
    variant: str | None = None,
    version_id: uuid.UUID | None = None,
) -> Resolved | None:
    """The published layout a record of *project_id* prints with; ``None`` when nothing is published."""
    repo = DocLayoutRepository(session)
    try:
        if version_id is not None:
            version = await repo.version(version_id)
            row = await session.get(DocLayout, version.layout_id) if version is not None else None
            if version is None or row is None or row.kind != key:
                return None
            if row.scope != WORKSPACE_SCOPE and row.scope != scope_for(project_id):
                return None
            return Resolved(
                normalise(version.document) if version.document else None, version.id, row.scope, row.variant
            )
        scopes = [scope_for(project_id), WORKSPACE_SCOPE] if project_id else [WORKSPACE_SCOPE]
        rows = await repo.in_scopes(key, scopes)
    except Exception:  # noqa: BLE001 - no layout tables yet: the standard form prints
        logger.debug("doc_templates: layout lookup failed", exc_info=True)
        return None
    for scope in scopes:
        in_scope = [r for r in rows if r.scope == scope]
        pick = next((r for r in in_scope if r.variant == variant), None) if variant else None
        if pick is None and not variant:
            pick = next((r for r in in_scope if r.is_default), None)
        found = await _published_of(session, pick)
        if found is not None:
            return found
    return None


def render(
    spec: LayoutSpec,
    template: Mapping[str, Any] | None,
    ctx: LayoutContext,
    *,
    standard: Mapping[str, Any] | None = None,
    clauses: Mapping[str, Mapping[str, Any]] | None = None,
    legal: Sequence[Any] = (),
) -> Any:
    """The record form *template* (or the standard one) prints for *ctx*, pack notes in the legal zone."""
    return compile_layout(template or standard or standard_template(spec), spec, ctx, clauses=clauses, legal=legal)


def _facts(ctx: LayoutContext) -> dict[str, Any]:
    """Display values with the empty ones blank, so a printed dash never counts as data."""
    facts: dict[str, Any] = dict(ctx.values)
    for path, value in ctx.raw.items():
        if value is None or value is False:
            facts[path] = ""
        elif path not in facts or value is True:
            facts[path] = value
    return facts


def data_issues(spec: LayoutSpec, ctx: LayoutContext, countries: Sequence[str]) -> tuple[list[Any], list[Issue]]:
    """Legal notes the packs print on this record, and the data it lacks.

    Data a pack requires and the record lacks (``doctpl.legal_data_missing``, error)
    blocks issuing. Data the platform standard asks for is a warning, so a record
    saved before the field existed still prints.
    """
    from app.core.doc_templates.legal import legal_notes
    from app.core.doc_templates.rules import check_mandatory

    facts = _facts(ctx)
    standard = [Issue(i.rule_id, "warning", i.block, i.params) for i in check_mandatory(spec, facts)]  # type: ignore[arg-type]
    try:
        notes, legal = legal_notes(spec.key, countries, facts, ctx.locale)
    except Exception:  # noqa: BLE001 - an unreadable pack file costs its notes, not the document
        logger.warning("doc_templates: legal notes unreadable for %s", spec.key, exc_info=True)
        notes, legal = [], []
    return notes, [*legal, *standard]


def _refuse_issue(issues: list[Issue]) -> None:
    if has_errors(issues):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"message": "Mandatory document data is missing", "issues": [i.as_dict() for i in issues]},
        )


async def issue_document(
    session: AsyncSession,
    spec: LayoutSpec,
    ctx: LayoutContext,
    *,
    standard: Mapping[str, Any],
    record_id: str,
    project_id: uuid.UUID | None,
    user_id: str | None,
    variant: str | None = None,
    version_id: uuid.UUID | None = None,
    countries: Sequence[str] = (),
) -> Any:
    """The record form to print, from the published layout in force, with an issue log row.

    The country packs' legal notes print in the legal zone of every layout, standard
    or custom; data a pack requires and the record lacks refuses the document (422).
    """
    notes, problems = data_issues(spec, ctx, countries)
    _refuse_issue(problems)
    resolved = await published_layout(session, spec.key, project_id=project_id, variant=variant, version_id=version_id)
    template = resolved.template if resolved is not None else None
    clauses = await clause_map(session) if template is not None else {}
    document = render(spec, template, ctx, standard=standard, clauses=clauses, legal=notes)
    try:
        session.add(
            DocTemplateIssue(
                kind=spec.key,
                record_id=record_id,
                project_id=project_id,
                locale=ctx.locale,
                text_locale=ctx.locale,
                source="published" if template is not None else "default",
                template_version_id=resolved.version_id if resolved is not None else None,
                issued_by=user_id,
            )
        )
        await session.flush()
    except Exception:  # noqa: BLE001 - a document never fails on its issue log
        logger.debug("doc_templates: layout issue log failed", exc_info=True)
    return document


async def issue_for_user(
    session: AsyncSession,
    spec: LayoutSpec,
    ctx: LayoutContext,
    *,
    standard: Mapping[str, Any],
    record_id: str,
    project_id: uuid.UUID | None,
    user_id: str,
    payload: Mapping[str, Any] | None,
    variant: str | None = None,
    version_id: uuid.UUID | None = None,
    legal: bool = True,
) -> Any:
    """:func:`issue_document` for a download route: the variant cleaned, the packs of the user's workspace.

    ``legal=False`` skips the packs, for a document the workspace receives rather than issues
    (a supplier's invoice is not held to the rules of an invoice the firm sends).
    """
    from app.modules.doc_templates.service import workspace_countries

    countries = await workspace_countries(session, dict(payload or {}), user_id) if legal else ()
    return await issue_document(
        session,
        spec,
        ctx,
        standard=standard,
        record_id=record_id,
        project_id=project_id,
        user_id=user_id,
        variant=clean_variant(variant) if variant else None,
        version_id=version_id,
        countries=countries,
    )


async def preview_context(
    session: AsyncSession, spec: LayoutSpec, locale: str, record_id: str | None, project_ids: set[Any] | None
) -> LayoutContext:
    """The context of a real record the caller may read, or the sample one."""
    if not record_id or spec.context is None:
        return spec.sample(locale)
    try:
        ctx = await spec.context(session, record_id, locale)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Record not found") from exc
    if project_ids is not None and ctx.project_id not in project_ids:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Record not found")
    return ctx


async def preview_pdf(
    session: AsyncSession,
    spec: LayoutSpec,
    template: Mapping[str, Any],
    *,
    locale: str,
    record_id: str | None,
    project_ids: set[Any] | None,
    countries: Sequence[str] = (),
) -> bytes:
    """PDF of an unsaved template on a real record or the sample, with the packs' legal notes."""
    import asyncio

    from app.core.register_export import build_record_pdf

    ctx = await preview_context(session, spec, locale, record_id, project_ids)
    notes, _problems = data_issues(spec, ctx, countries)
    document = render(spec, normalise(template), ctx, clauses=await clause_map(session), legal=notes)
    return await asyncio.to_thread(build_record_pdf, document)


async def list_summaries(session: AsyncSession) -> list[dict[str, Any]]:
    """Every visible layout with the number of published and draft variants."""
    rows = await DocLayoutRepository(session).all_rows()
    out = []
    for spec in visible_layouts():
        mine = [r for r in rows if r.kind == spec.key]
        out.append(
            {
                "key": spec.key,
                "module": spec.module,
                "label": spec.label,
                "published": sum(1 for r in mine if r.published_version_id is not None),
                "drafts": sum(1 for r in mine if r.draft is not None),
                "projects": len({r.scope for r in mine if r.scope != WORKSPACE_SCOPE}),
            }
        )
    return out
