# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The printed evidence pack: the schedule of records behind a claim.

The pack is already assembled, ordered and digested by
:mod:`app.modules.claims_evidence.evidence_pack`. This module only lays it
out as a register: one row per record, in the pack's own order, with the
section it was filed under, its date, what kind of record it is and its
title. The header carries the subject, the basis, the period the records
span and an integrity code, so a printed pack can be matched to the one on
screen.

Two things a database knows and a reader does not are kept off the page.
A record's id is a UUID: the workbook keeps it in a column of its own, for
whoever joins the pack back to the data, and the printed pack numbers its
rows instead, so a letter can cite "item 14 of the evidence pack". A source
reference that is a document number somebody wrote (not a UUID) is a human
reference and is printed. The digest is the one machine value that is the
point of the sheet, so it stays, cut to its first sixteen characters in
groups of four: enough to tell two packs apart, short enough to compare by
eye, and labelled as what it is.

A record's title is data written by other modules and is printed as stored.
The section, the basis and the kinds of the change family are translated; a
kind taken from the activity log is an action name and prints as stored.

The builder is pure, like :mod:`app.modules.rfi.pdf_export`. The layout is
the shared one in :mod:`app.core.register_export`.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.core.register_export import (
    EMPTY,
    ProjectHeader,
    RegisterColumn,
    RegisterDocument,
    format_stored_date,
    short_digest,
)
from app.modules.claims_evidence.pdf_translations import CATALOGUE, DEFAULT_PDF_LOCALE, normalize_pdf_locale, tr

__all__ = ["evidence_pack_register"]


def _kind_label(kind: Any, locale: str) -> str:
    """A change-family kind by name; any other kind (an activity action) as stored."""
    code = str(kind or "").strip()
    label = CATALOGUE.label("kind", code or None, locale)
    return label.replace("_", " ") if label == code else label


def _human_reference(ref_id: Any) -> str | None:
    """A source reference a person wrote, or ``None`` for a database id."""
    text = str(ref_id or "").strip()
    if not text:
        return None
    try:
        uuid.UUID(text)
    except ValueError:
        return text
    return None


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
    date_format = CATALOGUE.date_format(locale, project)
    rows: list[list[Any]] = []
    for section in getattr(pack, "sections", None) or []:
        section_label = CATALOGUE.label("section", getattr(section, "name", None), locale)
        for entry in getattr(section, "entries", None) or []:
            ref_id = getattr(entry, "ref_id", "")
            rows.append(
                [
                    len(rows) + 1,
                    section_label,
                    getattr(entry, "occurred_at", None),
                    _kind_label(getattr(entry, "kind", None), locale),
                    getattr(entry, "title", ""),
                    getattr(entry, "summary", ""),
                    _human_reference(ref_id),
                    ref_id,
                ]
            )
    columns = [
        RegisterColumn(tr(locale, "col_row"), kind="count", weight=0.6, xlsx_width=8),
        RegisterColumn(tr(locale, "col_section"), weight=1.4, xlsx_width=18),
        RegisterColumn(tr(locale, "col_date"), kind="date", weight=1.2, xlsx_width=14),
        RegisterColumn(tr(locale, "col_kind"), weight=1.5, xlsx_width=20),
        RegisterColumn(tr(locale, "col_title"), weight=3.2, xlsx_width=44, wrap=True),
        RegisterColumn(tr(locale, "col_summary"), weight=3.6, xlsx_width=56, wrap=True),
        # Printed only when some record has a reference a person wrote.
        RegisterColumn(
            tr(locale, "col_reference"),
            weight=1.4,
            xlsx_width=20,
            nobreak=True,
            pdf=any(row[6] for row in rows),
        ),
        RegisterColumn(tr(locale, "col_record_id"), weight=1.6, xlsx_width=38, pdf=False),
    ]
    details = CATALOGUE.register_details(locale, project, count=len(rows))
    details.extend(
        [
            (tr(locale, "subject"), str(getattr(pack, "subject_ref", "") or EMPTY)),
            (tr(locale, "basis"), CATALOGUE.label("basis", getattr(pack, "basis", None), locale)),
            (tr(locale, "period_from"), format_stored_date(getattr(pack, "date_from", None), date_format)),
            (tr(locale, "period_to"), format_stored_date(getattr(pack, "date_to", None), date_format)),
            (tr(locale, "digest"), short_digest(getattr(pack, "content_digest", None))),
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
        **CATALOGUE.furniture(locale, project),
    )
