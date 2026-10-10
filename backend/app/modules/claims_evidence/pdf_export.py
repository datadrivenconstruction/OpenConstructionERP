# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The printed evidence pack: the schedule of records behind a claim.

The pack is already assembled, ordered and digested by
:mod:`app.modules.claims_evidence.evidence_pack`. This module only lays it
out as a register: one row per record, in the pack's own order, with the
section it was filed under, its date, what kind of record it is and its
title. The header carries the subject, the basis, the period the records
span and the content digest, so a printed pack can be matched to the one on
screen.

A record's title is data written by other modules and is printed as stored.
The section, the basis and the kinds of the change family are translated; a
kind taken from the activity log is an action name and prints as stored.

The builder is pure, like :mod:`app.modules.rfi.pdf_export`. The layout is
the shared one in :mod:`app.core.register_export`.
"""

from __future__ import annotations

from typing import Any

from app.core.register_export import (
    EMPTY,
    ProjectHeader,
    RegisterColumn,
    RegisterDocument,
    format_stored_date,
)
from app.modules.claims_evidence.pdf_translations import CATALOGUE, DEFAULT_PDF_LOCALE, normalize_pdf_locale, tr

__all__ = ["evidence_pack_register"]


def _kind_label(kind: Any, locale: str) -> str:
    """A change-family kind by name; any other kind (an activity action) as stored."""
    code = str(kind or "").strip()
    label = CATALOGUE.label("kind", code or None, locale)
    return label.replace("_", " ") if label == code else label


def evidence_pack_register(
    pack: Any,
    *,
    project: ProjectHeader,
    locale: str = DEFAULT_PDF_LOCALE,
    generated: str = "",
) -> RegisterDocument:
    """Describe an evidence pack as a printable register.

    Args:
        pack: An :class:`~app.modules.claims_evidence.evidence_pack.EvidencePack`,
            or any object with the same attributes.
        project: The project the pack belongs to.
        locale: Document language; unsupported values fall back to English.
        generated: The timestamp printed in the footer.

    Returns:
        The register, ready for the PDF or the workbook renderer.
    """
    locale = normalize_pdf_locale(locale)
    date_format = tr(locale, "date_format")
    columns = [
        RegisterColumn(tr(locale, "col_section"), weight=1.4, xlsx_width=18),
        RegisterColumn(tr(locale, "col_date"), kind="date", weight=1.2, xlsx_width=14),
        RegisterColumn(tr(locale, "col_kind"), weight=1.5, xlsx_width=20),
        RegisterColumn(tr(locale, "col_title"), weight=3.2, xlsx_width=44, wrap=True),
        RegisterColumn(tr(locale, "col_summary"), weight=3.6, xlsx_width=56, wrap=True),
        RegisterColumn(tr(locale, "col_reference"), weight=1.6, xlsx_width=38),
    ]
    rows: list[list[Any]] = []
    for section in getattr(pack, "sections", None) or []:
        section_label = CATALOGUE.label("section", getattr(section, "name", None), locale)
        for entry in getattr(section, "entries", None) or []:
            rows.append(
                [
                    section_label,
                    getattr(entry, "occurred_at", None),
                    _kind_label(getattr(entry, "kind", None), locale),
                    getattr(entry, "title", ""),
                    getattr(entry, "summary", ""),
                    getattr(entry, "ref_id", ""),
                ]
            )
    details = CATALOGUE.register_details(locale, project, count=len(rows))
    details.extend(
        [
            (tr(locale, "subject"), str(getattr(pack, "subject_ref", "") or EMPTY)),
            (tr(locale, "basis"), CATALOGUE.label("basis", getattr(pack, "basis", None), locale)),
            (tr(locale, "period_from"), format_stored_date(getattr(pack, "date_from", None), date_format)),
            (tr(locale, "period_to"), format_stored_date(getattr(pack, "date_to", None), date_format)),
            (tr(locale, "digest"), str(getattr(pack, "content_digest", "") or EMPTY)),
        ]
    )
    return RegisterDocument(
        title=tr(locale, "register_title"),
        columns=columns,
        rows=rows,
        details=details,
        locale=locale,
        number_style=project.number_style,
        generated=generated,
        empty_text=tr(locale, "empty_register"),
        **CATALOGUE.furniture(locale),
    )
