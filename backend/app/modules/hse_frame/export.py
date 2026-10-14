# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Printable registers of the HSE frame (PDF and XLSX).

Two registers: the requirements register (one line per row, grouped by the
catalogue's topic order) and the responsibilities (every role the catalogue
names with who carries it). Topic and role names come from the pinned
catalogue in the reader's language; headers and status words come from
``hse_frame.export.*``.
"""

from __future__ import annotations

import io
import uuid
from typing import Any

from app.core.register_export import RegisterColumn, RegisterDocument, build_register_pdf, build_register_xlsx
from app.modules.hse_frame.messages import DEFAULT_LOCALE, is_key_present, translate
from app.modules.hse_frame.models import HseItem, HseRole

WHATS = ("register", "roles")


def rendered_language(locale: str) -> str:
    """The language the export's own texts come out in for a reader who asked for ``locale``."""
    probe = "hse_frame.export.empty"
    base = locale.replace("_", "-").split("-")[0]
    for candidate in (locale, base):
        if candidate and is_key_present(probe, locale=candidate):
            return candidate
    return DEFAULT_LOCALE


def _label(entry: Any, locale: str) -> str:
    if entry is None:
        return ""
    labels = getattr(entry, "labels", None) or {}
    base = locale.replace("_", "-").split("-")[0]
    return labels.get(base) or labels.get("en") or getattr(entry, "code", "")


async def render(svc: Any, project_id: uuid.UUID, *, what: str, fmt: str, locale: str) -> bytes:
    """Build the ``what`` register of the project as ``fmt`` (pdf or xlsx)."""

    def t(key: str) -> str:
        return translate(f"hse_frame.export.{key}", locale=locale)

    frame = await svc.require_frame(project_id)
    catalogue = await svc.catalogue_for(frame)
    if what == "register":
        order = {topic.code: i for i, topic in enumerate(catalogue.topics)}
        items = sorted(
            await svc.repo.list(HseItem, project_id),
            key=lambda i: (order.get(i.topic, len(order)), i.created_at),
        )
        templates = {tpl.code: tpl for tpl in catalogue.templates}
        columns = [
            RegisterColumn(t("col.topic")),
            RegisterColumn(t("col.title"), wrap=True),
            RegisterColumn(t("col.legal_basis")),
            RegisterColumn(t("col.obligation")),
            RegisterColumn(t("col.responsible")),
            RegisterColumn(t("col.due"), kind="date"),
            RegisterColumn(t("col.status")),
            RegisterColumn(t("col.met_on"), kind="date"),
        ]
        rows = []
        for i in items:
            template = templates.get(i.template_code or "")
            # A row made from a template keeps the stored English title until someone edits it.
            same = template is not None and (template.labels or {}).get("en") == i.title
            rows.append(
                [
                    _label(catalogue.entry("topics", i.topic), locale) or i.topic,
                    _label(template, locale) if same else i.title,
                    i.legal_basis,
                    t(f"obligation.{i.obligation}"),
                    i.responsible_party,
                    i.due_date,
                    t(f"status.{i.status}"),
                    i.met_on,
                ]
            )
    else:
        roles = await svc.repo.list(HseRole, project_id)
        columns = [
            RegisterColumn(t("col.role")),
            RegisterColumn(t("col.person")),
            RegisterColumn(t("col.organisation")),
            RegisterColumn(t("col.role_status")),
            RegisterColumn(t("col.appointed_on"), kind="date"),
            RegisterColumn(t("col.qualification")),
            RegisterColumn(t("col.valid_until"), kind="date"),
        ]
        rows = []
        for r in roles:
            kind = catalogue.entry("role_kinds", r.role_code)
            name = _label(kind, locale)
            national = getattr(kind, "national_name", "") or ""
            rows.append(
                [
                    f"{name} ({national})" if national else name,
                    r.person_name,
                    r.organisation,
                    t(f"role_status.{r.status}"),
                    r.appointed_on,
                    r.qualification,
                    r.qualification_valid_until,
                ]
            )
    doc = RegisterDocument(
        title=t(f"{what}.title"),
        columns=columns,
        rows=rows,
        locale=locale,
        empty_text=t("empty"),
        sheet_title=t(f"{what}.title")[:31],
    )
    if fmt == "xlsx":
        buf: io.BytesIO = build_register_xlsx(doc)
        return buf.getvalue()
    return build_register_pdf(doc)
