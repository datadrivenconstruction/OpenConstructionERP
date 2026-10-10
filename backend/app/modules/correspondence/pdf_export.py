# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The printed correspondence log and the printed record of one item.

The log is the incoming and outgoing register: reference number, direction,
dates, from and to, the subject and the date a reply is required by, with
the contract clause the item was sent under. Its columns are the ones the
correspondence row stores.

The builders are pure, like :mod:`app.modules.rfi.pdf_export`: rows plus
already-resolved names in, a document description out. The layout is the
shared one in :mod:`app.core.register_export`.
"""

from __future__ import annotations

import io
from collections.abc import Mapping, Sequence
from typing import Any

from app.core.register_export import (
    EMPTY,
    ProjectHeader,
    RecordBlock,
    RecordDocument,
    RegisterColumn,
    RegisterDocument,
    build_record_pdf,
    build_register_pdf,
    build_register_xlsx,
    caps,
    format_stored_date,
    person_name,
)
from app.modules.correspondence.pdf_translations import CATALOGUE, DEFAULT_PDF_LOCALE, normalize_pdf_locale, tr

__all__ = [
    "build_correspondence_pdf",
    "build_correspondence_register_pdf",
    "build_correspondence_register_xlsx",
    "correspondence_record",
    "correspondence_register",
]


def _recipients(item: Any, people: Mapping[str, str] | None) -> str:
    """Every addressee by name, comma separated, or a dash."""
    names = [person_name(value, people) for value in (getattr(item, "to_contact_ids", None) or []) if value]
    return ", ".join(names) or EMPTY


def correspondence_register(
    items: Sequence[Any],
    *,
    project: ProjectHeader,
    people: Mapping[str, str] | None = None,
    locale: str = DEFAULT_PDF_LOCALE,
    generated: str = "",
) -> RegisterDocument:
    """Describe the correspondence log of one project.

    Args:
        items: :class:`~app.modules.correspondence.models.Correspondence`
            rows, or objects with the same attributes, in print order.
        project: The project the log belongs to.
        people: Display names keyed by ``str(contact id)``.
        locale: Document language; unsupported values fall back to English.
        generated: The timestamp printed in the footer.

    Returns:
        The log, ready for the PDF or the workbook renderer.
    """
    locale = normalize_pdf_locale(locale)
    columns = [
        RegisterColumn(tr(locale, "col_reference"), weight=1.3, xlsx_width=16),
        RegisterColumn(tr(locale, "col_direction"), weight=0.9, xlsx_width=11),
        RegisterColumn(tr(locale, "col_type"), weight=0.9, xlsx_width=12),
        RegisterColumn(tr(locale, "col_subject"), weight=3.0, xlsx_width=44, wrap=True),
        RegisterColumn(tr(locale, "col_from"), weight=1.6, xlsx_width=24),
        RegisterColumn(tr(locale, "col_to"), weight=1.8, xlsx_width=28, wrap=True),
        RegisterColumn(tr(locale, "col_date_sent"), kind="date", weight=1.3, xlsx_width=14),
        RegisterColumn(tr(locale, "col_date_received"), kind="date", weight=1.3, xlsx_width=14),
        RegisterColumn(tr(locale, "col_response_due"), kind="date", weight=1.3, xlsx_width=16),
        RegisterColumn(tr(locale, "status"), weight=1.3, xlsx_width=18),
        RegisterColumn(tr(locale, "col_clause"), weight=1.2, xlsx_width=18),
    ]
    rows = [
        [
            getattr(item, "reference_number", ""),
            CATALOGUE.label("direction", getattr(item, "direction", None), locale),
            CATALOGUE.label("type", getattr(item, "correspondence_type", None), locale),
            getattr(item, "subject", ""),
            person_name(getattr(item, "from_contact_id", None), people),
            _recipients(item, people),
            getattr(item, "date_sent", None),
            getattr(item, "date_received", None),
            getattr(item, "response_required_by", None),
            CATALOGUE.label("status", getattr(item, "status", None), locale),
            getattr(item, "contract_clause_ref", None),
        ]
        for item in items
    ]
    return RegisterDocument(
        title=tr(locale, "register_title"),
        columns=columns,
        rows=rows,
        details=CATALOGUE.register_details(locale, project, count=len(rows)),
        locale=locale,
        number_style=project.number_style,
        generated=generated,
        empty_text=tr(locale, "empty_register"),
        **CATALOGUE.furniture(locale),
    )


def build_correspondence_register_pdf(items: Sequence[Any], **context: Any) -> bytes:
    """Render the correspondence log as a PDF; see :func:`correspondence_register`."""
    return build_register_pdf(correspondence_register(items, **context))


def build_correspondence_register_xlsx(items: Sequence[Any], **context: Any) -> io.BytesIO:
    """Render the correspondence log as a workbook; see :func:`correspondence_register`."""
    return build_register_xlsx(correspondence_register(items, **context))


def correspondence_record(
    item: Any,
    *,
    project: ProjectHeader,
    people: Mapping[str, str] | None = None,
    locale: str = DEFAULT_PDF_LOCALE,
    generated: str = "",
) -> RecordDocument:
    """Describe the printable record of one piece of correspondence.

    Args:
        item: The correspondence row, or any object with the same attributes.
        project: The owning project.
        people: Display names keyed by ``str(contact id)``.
        locale: Document language; unsupported values fall back to English.
        generated: The timestamp printed in the footer.

    Returns:
        The record, ready for the PDF renderer.
    """
    locale = normalize_pdf_locale(locale)
    date_format = tr(locale, "date_format")

    def _date(name: str) -> str:
        return format_stored_date(getattr(item, name, None), date_format)

    grid = [
        [
            tr(locale, "project"),
            project.label,
            tr(locale, "col_direction"),
            CATALOGUE.label("direction", getattr(item, "direction", None), locale),
        ],
        [
            tr(locale, "col_from"),
            person_name(getattr(item, "from_contact_id", None), people),
            tr(locale, "col_to"),
            _recipients(item, people),
        ],
        [tr(locale, "col_date_sent"), _date("date_sent"), tr(locale, "col_date_received"), _date("date_received")],
        [
            tr(locale, "col_type"),
            CATALOGUE.label("type", getattr(item, "correspondence_type", None), locale),
            tr(locale, "col_response_due"),
            _date("response_required_by"),
        ],
        [
            tr(locale, "col_clause"),
            str(getattr(item, "contract_clause_ref", None) or EMPTY),
            tr(locale, "attachments"),
            str(len(getattr(item, "attachments", None) or [])),
        ],
        [tr(locale, "linked_documents"), str(len(getattr(item, "linked_document_ids", None) or [])), "", ""],
    ]
    signatures = [
        ["", tr(locale, "name"), tr(locale, "signature"), tr(locale, "date")],
        [tr(locale, "sig_prepared"), "", "", ""],
        [tr(locale, "sig_received"), "", "", ""],
    ]
    status = CATALOGUE.label("status", getattr(item, "status", None) or "open", locale)
    return RecordDocument(
        title=tr(locale, "doc_title"),
        number=str(getattr(item, "reference_number", "") or ""),
        project_label=project.label,
        status_text=caps(status, locale),
        subject=str(getattr(item, "subject", "") or ""),
        grid=grid,
        blocks=[
            RecordBlock(
                tr(locale, "notes"), text=str(getattr(item, "notes", None) or ""), empty_text=tr(locale, "no_notes")
            ),
            RecordBlock(tr(locale, "signatures"), kind="signatures", rows=signatures),
        ],
        page_label=tr(locale, "footer_page"),
        generated_label=tr(locale, "footer_generated"),
        generated=generated,
    )


def build_correspondence_pdf(item: Any, **context: Any) -> bytes:
    """Render one correspondence record as a PDF; see :func:`correspondence_record`."""
    return build_record_pdf(correspondence_record(item, **context))
