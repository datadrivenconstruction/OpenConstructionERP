# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The printed transmittal register and the printed cover sheet of one transmittal.

The cover sheet is the page that travels with the documents: number,
subject, purpose, who it goes to and what each recipient is asked to do, the
list of items sent, and lines to sign for issue and receipt. The register
lists every transmittal of a project. Both print what the transmittal rows
store.

The builders are pure, like :mod:`app.modules.rfi.pdf_export`. The layout is
the shared one in :mod:`app.core.register_export`.
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
    grid_rows,
    person_name,
)
from app.modules.transmittals.pdf_translations import CATALOGUE, DEFAULT_PDF_LOCALE, normalize_pdf_locale, tr

__all__ = [
    "build_transmittal_pdf",
    "build_transmittal_register_pdf",
    "build_transmittal_register_xlsx",
    "transmittal_record",
    "transmittal_register",
]


def _recipient_name(recipient: Any, people: Mapping[str, str] | None) -> str:
    """A recipient by the name typed for them, else by the user or company picked."""
    typed = str(getattr(recipient, "recipient_name", None) or "").strip()
    if typed:
        return typed
    for attribute in ("recipient_user_id", "recipient_org_id"):
        value = getattr(recipient, attribute, None)
        if value:
            return person_name(value, people)
    return str(getattr(recipient, "recipient_email", None) or "").strip() or EMPTY


def _recipient_names(transmittal: Any, people: Mapping[str, str] | None) -> str:
    names = [_recipient_name(recipient, people) for recipient in (getattr(transmittal, "recipients", None) or [])]
    return ", ".join(name for name in names if name != EMPTY) or EMPTY


def transmittal_register(
    transmittals: Sequence[Any],
    *,
    project: ProjectHeader,
    people: Mapping[str, str] | None = None,
    locale: str = DEFAULT_PDF_LOCALE,
    generated: str = "",
) -> RegisterDocument:
    """Describe the transmittal register of one project.

    Args:
        transmittals: :class:`~app.modules.transmittals.models.Transmittal`
            rows with ``recipients`` and ``items`` loaded, or objects with the
            same attributes, in print order.
        project: The project the register belongs to.
        people: Display names keyed by ``str(id)`` for picked recipients.
        locale: Document language; unsupported values fall back to English.
        generated: The timestamp printed in the footer.

    Returns:
        The register, ready for the PDF or the workbook renderer.
    """
    locale = normalize_pdf_locale(locale)
    columns = [
        RegisterColumn(tr(locale, "col_number"), weight=1.3, xlsx_width=16, nobreak=True),
        RegisterColumn(tr(locale, "col_subject"), weight=3.4, xlsx_width=46, wrap=True),
        RegisterColumn(tr(locale, "col_purpose"), weight=1.3, xlsx_width=18),
        RegisterColumn(tr(locale, "status"), weight=1.1, xlsx_width=14),
        RegisterColumn(tr(locale, "col_issued"), kind="date", weight=1.3, xlsx_width=14),
        RegisterColumn(tr(locale, "col_response_due"), kind="date", weight=1.3, xlsx_width=14),
        RegisterColumn(tr(locale, "col_recipients"), weight=2.6, xlsx_width=36, wrap=True),
        RegisterColumn(tr(locale, "col_item_count"), kind="count", weight=0.8, xlsx_width=10),
    ]
    rows = [
        [
            getattr(item, "transmittal_number", ""),
            getattr(item, "subject", ""),
            CATALOGUE.label("purpose", getattr(item, "purpose_code", None), locale),
            CATALOGUE.label("status", getattr(item, "status", None), locale),
            getattr(item, "issued_date", None),
            getattr(item, "response_due_date", None),
            _recipient_names(item, people),
            len(getattr(item, "items", None) or []),
        ]
        for item in transmittals
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
        **CATALOGUE.furniture(locale, project),
    )


def build_transmittal_register_pdf(transmittals: Sequence[Any], **context: Any) -> bytes:
    """Render the transmittal register as a PDF; see :func:`transmittal_register`."""
    return build_register_pdf(transmittal_register(transmittals, **context))


def build_transmittal_register_xlsx(transmittals: Sequence[Any], **context: Any) -> io.BytesIO:
    """Render the transmittal register as a workbook; see :func:`transmittal_register`."""
    return build_register_xlsx(transmittal_register(transmittals, **context))


def transmittal_record(
    transmittal: Any,
    *,
    project: ProjectHeader,
    people: Mapping[str, str] | None = None,
    locale: str = DEFAULT_PDF_LOCALE,
    generated: str = "",
) -> RecordDocument:
    """Describe the printable cover sheet of one transmittal.

    Args:
        transmittal: The transmittal row with ``recipients`` and ``items``
            loaded, or any object with the same attributes.
        project: The owning project.
        people: Display names keyed by ``str(id)``.
        locale: Document language; unsupported values fall back to English.
        generated: The timestamp printed in the footer.

    Returns:
        The cover sheet, ready for the PDF renderer.
    """
    locale = normalize_pdf_locale(locale)
    date_format = CATALOGUE.date_format(locale, project)

    def _date(value: Any) -> str:
        return format_stored_date(value, date_format)

    # The project is in the line under the title, with the transmittal number.
    grid = grid_rows(
        [
            (tr(locale, "sender"), person_name(getattr(transmittal, "sender_org_id", None), people)),
            (tr(locale, "col_purpose"), CATALOGUE.label("purpose", getattr(transmittal, "purpose_code", None), locale)),
            (tr(locale, "col_issued"), _date(getattr(transmittal, "issued_date", None))),
            (tr(locale, "col_response_due"), _date(getattr(transmittal, "response_due_date", None))),
        ]
    )
    blocks = [
        RecordBlock(
            tr(locale, "cover_note"),
            text=str(getattr(transmittal, "cover_note", None) or ""),
            empty_text=tr(locale, "no_cover_note"),
        )
    ]
    recipients = list(getattr(transmittal, "recipients", None) or [])
    if recipients:
        rows = [
            [
                tr(locale, "recipient"),
                tr(locale, "action_required"),
                tr(locale, "acknowledged"),
                tr(locale, "responded"),
            ]
        ]
        for recipient in recipients:
            rows.append(
                [
                    _recipient_name(recipient, people),
                    str(getattr(recipient, "action_required", None) or EMPTY),
                    _date(getattr(recipient, "acknowledged_at", None)),
                    _date(getattr(recipient, "responded_at", None)),
                ]
            )
        blocks.append(
            RecordBlock(
                tr(locale, "recipients"),
                kind="table",
                rows=rows,
                weights=[2.4, 2.2, 1.4, 1.4],
                keep_together=[False, False, True, True],
            )
        )
    items = sorted(getattr(transmittal, "items", None) or [], key=lambda item: getattr(item, "item_number", 0) or 0)
    if items:
        rows = [[tr(locale, "item_no"), tr(locale, "item_description"), tr(locale, "item_notes")]]
        for item in items:
            rows.append(
                [
                    str(getattr(item, "item_number", "") or ""),
                    str(getattr(item, "description", None) or EMPTY),
                    str(getattr(item, "notes", None) or EMPTY),
                ]
            )
        blocks.append(
            RecordBlock(
                tr(locale, "items"),
                kind="table",
                rows=rows,
                weights=[0.8, 3.6, 2.6],
                keep_together=[True, False, False],
            )
        )
    blocks.append(
        RecordBlock(
            tr(locale, "signatures"),
            kind="signatures",
            rows=CATALOGUE.signature_rows(
                locale, [(tr(locale, "sig_issued"), EMPTY), (tr(locale, "sig_received"), EMPTY)]
            ),
        )
    )
    status = CATALOGUE.label("status", getattr(transmittal, "status", None) or "draft", locale)
    return RecordDocument(
        title=tr(locale, "doc_title"),
        number=str(getattr(transmittal, "transmittal_number", "") or ""),
        project_label=project.label,
        status_text=caps(status, locale),
        subject=str(getattr(transmittal, "subject", "") or ""),
        grid=grid,
        blocks=blocks,
        page_label=tr(locale, "footer_page"),
        generated_label=tr(locale, "footer_generated"),
        generated=generated,
    )


def build_transmittal_pdf(transmittal: Any, **context: Any) -> bytes:
    """Render one transmittal as a PDF cover sheet; see :func:`transmittal_record`."""
    return build_record_pdf(transmittal_record(transmittal, **context))
