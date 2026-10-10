# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The printed submittal register and the printed form of one submittal.

A contractor's submittal register is a contractual record: it shows what was
submitted for approval (shop drawings, product data, method statements), in
which revision, when it was required, when it came back and with which
decision. It is printed and attached to letters, so it carries the project,
the generation date and "page x of y", and its columns are the ones the
submittal row stores, not ones a template would like to have.

The builders are pure, like :mod:`app.modules.rfi.pdf_export`: they take
rows plus already-resolved names and never touch the database, so the routes
do the lookups and the tests drive them with plain namespaces. The layout
is the shared one in :mod:`app.core.register_export`.
"""

from __future__ import annotations

import io
from collections.abc import Mapping, Sequence
from typing import Any

from app.core.register_export import (
    ProjectHeader,
    RecordBlock,
    RecordDocument,
    RegisterColumn,
    RegisterDocument,
    build_record_pdf,
    build_register_pdf,
    build_register_xlsx,
    caps,
    format_count,
    format_stored_date,
    person_name,
)
from app.modules.submittals.pdf_translations import CATALOGUE, DEFAULT_PDF_LOCALE, normalize_pdf_locale, tr

__all__ = [
    "build_submittal_pdf",
    "build_submittal_register_pdf",
    "build_submittal_register_xlsx",
    "submittal_record",
    "submittal_register",
]


def submittal_register(
    submittals: Sequence[Any],
    *,
    project: ProjectHeader,
    people: Mapping[str, str] | None = None,
    locale: str = DEFAULT_PDF_LOCALE,
    generated: str = "",
) -> RegisterDocument:
    """Describe the submittal register of one project.

    Args:
        submittals: :class:`~app.modules.submittals.models.Submittal` rows, or
            objects with the same attributes, in the order to print them.
        project: The project the register belongs to.
        people: Display names keyed by ``str(id)`` for reviewers, approvers
            and whoever holds the ball.
        locale: Document language; unsupported values fall back to English.
        generated: The timestamp printed in the footer.

    Returns:
        The register, ready for the PDF or the workbook renderer.
    """
    locale = normalize_pdf_locale(locale)
    columns = [
        RegisterColumn(tr(locale, "col_number"), weight=1.1, xlsx_width=14),
        RegisterColumn(tr(locale, "col_title"), weight=3.0, xlsx_width=42, wrap=True),
        RegisterColumn(tr(locale, "col_type"), weight=1.4, xlsx_width=18),
        RegisterColumn(tr(locale, "col_spec"), weight=1.2, xlsx_width=16),
        RegisterColumn(tr(locale, "col_rev"), kind="count", weight=0.6, xlsx_width=7),
        RegisterColumn(tr(locale, "status"), weight=1.5, xlsx_width=22),
        RegisterColumn(tr(locale, "col_date_submitted"), kind="date", weight=1.35, xlsx_width=14),
        RegisterColumn(tr(locale, "col_date_required"), kind="date", weight=1.35, xlsx_width=14),
        RegisterColumn(tr(locale, "col_date_returned"), kind="date", weight=1.35, xlsx_width=14),
        RegisterColumn(tr(locale, "col_reviewer"), weight=1.4, xlsx_width=20),
        RegisterColumn(tr(locale, "col_approver"), weight=1.4, xlsx_width=20),
        RegisterColumn(tr(locale, "col_ball_in_court"), weight=1.4, xlsx_width=20),
    ]
    rows = [
        [
            getattr(item, "submittal_number", ""),
            getattr(item, "title", ""),
            CATALOGUE.label("type", getattr(item, "submittal_type", None), locale),
            getattr(item, "spec_section", None),
            getattr(item, "current_revision", None),
            CATALOGUE.label("status", getattr(item, "status", None), locale),
            getattr(item, "date_submitted", None),
            getattr(item, "date_required", None),
            getattr(item, "date_returned", None),
            person_name(getattr(item, "reviewer_id", None), people),
            person_name(getattr(item, "approver_id", None), people),
            person_name(getattr(item, "ball_in_court", None), people),
        ]
        for item in submittals
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


def build_submittal_register_pdf(submittals: Sequence[Any], **context: Any) -> bytes:
    """Render the submittal register as a PDF; see :func:`submittal_register`."""
    return build_register_pdf(submittal_register(submittals, **context))


def build_submittal_register_xlsx(submittals: Sequence[Any], **context: Any) -> io.BytesIO:
    """Render the submittal register as a workbook; see :func:`submittal_register`."""
    return build_register_xlsx(submittal_register(submittals, **context))


def submittal_record(
    submittal: Any,
    *,
    project: ProjectHeader,
    people: Mapping[str, str] | None = None,
    locale: str = DEFAULT_PDF_LOCALE,
    generated: str = "",
) -> RecordDocument:
    """Describe the printable form of one submittal.

    Args:
        submittal: The submittal row, or any object with the same attributes.
        project: The owning project.
        people: Display names keyed by ``str(id)``.
        locale: Document language; unsupported values fall back to English.
        generated: The timestamp printed in the footer.

    Returns:
        The form, ready for the PDF renderer.
    """
    locale = normalize_pdf_locale(locale)
    date_format = tr(locale, "date_format")
    metadata = getattr(submittal, "metadata_", None)
    notes = str((metadata if isinstance(metadata, dict) else {}).get("review_notes") or "")
    reviewer = person_name(getattr(submittal, "reviewer_id", None), people)
    approver = person_name(getattr(submittal, "approver_id", None), people)
    submitter = person_name(getattr(submittal, "submitted_by_org", None), people)
    grid = [
        [
            tr(locale, "project"),
            project.label,
            tr(locale, "col_type"),
            CATALOGUE.label("type", getattr(submittal, "submittal_type", None), locale),
        ],
        [
            tr(locale, "col_spec"),
            str(getattr(submittal, "spec_section", None) or "-"),
            tr(locale, "col_rev"),
            format_count(getattr(submittal, "current_revision", None)),
        ],
        [
            tr(locale, "submitted_by_org"),
            submitter,
            tr(locale, "col_ball_in_court"),
            person_name(getattr(submittal, "ball_in_court", None), people),
        ],
        [
            tr(locale, "col_date_submitted"),
            format_stored_date(getattr(submittal, "date_submitted", None), date_format),
            tr(locale, "col_date_required"),
            format_stored_date(getattr(submittal, "date_required", None), date_format),
        ],
        [
            tr(locale, "col_date_returned"),
            format_stored_date(getattr(submittal, "date_returned", None), date_format),
            tr(locale, "col_reviewer"),
            reviewer,
        ],
        [tr(locale, "col_approver"), approver, "", ""],
    ]
    blank = ["", ""]
    signatures = [
        ["", tr(locale, "name"), tr(locale, "signature"), tr(locale, "date")],
        [tr(locale, "sig_submitted"), "" if submitter == "-" else submitter, *blank],
        [tr(locale, "sig_reviewed"), "" if reviewer == "-" else reviewer, *blank],
        [tr(locale, "sig_approved"), "" if approver == "-" else approver, *blank],
    ]
    status = CATALOGUE.label("status", getattr(submittal, "status", None) or "draft", locale)
    return RecordDocument(
        title=tr(locale, "doc_title"),
        number=str(getattr(submittal, "submittal_number", "") or ""),
        project_label=project.label,
        status_text=caps(status, locale),
        subject=str(getattr(submittal, "title", "") or ""),
        grid=grid,
        blocks=[
            RecordBlock(tr(locale, "review_notes"), text=notes, empty_text=tr(locale, "no_review_notes")),
            RecordBlock(tr(locale, "signatures"), kind="signatures", rows=signatures),
        ],
        page_label=tr(locale, "footer_page"),
        generated_label=tr(locale, "footer_generated"),
        generated=generated,
    )


def build_submittal_pdf(submittal: Any, **context: Any) -> bytes:
    """Render one submittal as a PDF form; see :func:`submittal_record`."""
    return build_record_pdf(submittal_record(submittal, **context))
