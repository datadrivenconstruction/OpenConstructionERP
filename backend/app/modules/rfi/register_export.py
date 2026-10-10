# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The printed RFI log, in the reader's language.

The RFI log of ``GET /export/`` is a workbook with English headings, English
status words and "Yes"/"No" cells whatever language the workspace runs in,
and it has no PDF form. This module describes the same twelve columns once,
translated, for both a workbook and a printable PDF with the project, the
generation date and "page x of y" on it.

The log's strings are kept here rather than added to the single-RFI
catalogue in :mod:`app.modules.rfi.pdf_translations`: that catalogue is held
to every one of its thirty-three languages by its tests, and the log is
translated into English and Turkish so far. Status words still come from
:mod:`app.modules.rfi.intl`, asked in the log's own language, so a heading
and a status never disagree. Any other request renders in English and the
route says so in ``Content-Language``.

The builder is pure: RFI rows plus already-resolved names in, a register
description out.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.register_export import (
    DocumentCatalogue,
    ProjectHeader,
    RegisterColumn,
    RegisterDocument,
    export_filename,
    format_amount,
    person_name,
)
from app.modules.rfi.intl import localize_status

__all__ = [
    "CATALOGUE",
    "SUPPORTED_REGISTER_LOCALES",
    "resolve_register_locale",
    "rfi_register",
    "rfi_register_filename",
]

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "register_title": "RFI Log",
        "col_number": "RFI #",
        "col_subject": "Subject",
        "col_raised_by": "Raised By",
        "col_assigned_to": "Assigned To",
        "col_ball_in_court": "Ball-in-Court",
        "col_date_required": "Date Required",
        "col_response_due": "Response Due",
        "col_days_open": "Days Open",
        "col_cost_impact": "Cost Impact",
        "col_schedule_impact": "Schedule Impact",
        "col_response": "Response",
        "yes_with": "Yes ({detail})",
        "register_filename": "rfi_log",
    },
    "tr": {
        "register_title": "Bilgi Talepleri Kayıt Listesi (RFI)",
        "col_number": "RFI no.",
        "col_subject": "Konu",
        "col_raised_by": "Oluşturan",
        "col_assigned_to": "Atanan",
        "col_ball_in_court": "Sıradaki sorumlu",
        "col_date_required": "Gerekli tarih",
        "col_response_due": "Yanıt son tarihi",
        "col_days_open": "Açık gün sayısı",
        "col_cost_impact": "Maliyet etkisi",
        "col_schedule_impact": "Takvim etkisi",
        "col_response": "Yanıt",
        "yes_with": "Evet ({detail})",
        "register_filename": "bilgi-talepleri-kayit-listesi",
    },
}

CATALOGUE = DocumentCatalogue(_STRINGS)

#: Languages the RFI log can render; anything else is English.
SUPPORTED_REGISTER_LOCALES: tuple[str, ...] = CATALOGUE.supported


def resolve_register_locale(locale_param: str | None, accept_language: str | None) -> str:
    """Pick the log's language: ``?locale=``, then ``Accept-Language``, then English."""
    return CATALOGUE.resolve(locale_param, accept_language)


def rfi_register_filename(locale: str, extension: str) -> str:
    """Download filename for the log; the English name is the one it always had."""
    return export_filename(CATALOGUE.tr(locale, "register_filename"), "rfi_log", extension)


def _impact(flag: Any, detail: str | None, locale: str) -> str:
    if not flag:
        return CATALOGUE.tr(locale, "no")
    return CATALOGUE.tr(locale, "yes_with", detail=detail) if detail else CATALOGUE.tr(locale, "yes")


def _cost_detail(value: Any, project: ProjectHeader) -> str | None:
    """The cost impact amount in the project's separators, or as typed when it is not a number."""
    text = str(value if value is not None else "").strip()
    if not text:
        return None
    try:
        amount = Decimal(text)
    except (InvalidOperation, ValueError):
        return f"{text} {project.currency}".strip()
    if not amount.is_finite():
        return f"{text} {project.currency}".strip()
    return format_amount(amount, project.number_style, project.currency)


def rfi_register(
    rfis: Sequence[Any],
    *,
    project: ProjectHeader,
    people: Mapping[str, str] | None = None,
    days_open: Mapping[Any, int] | None = None,
    locale: str = "en",
    generated: str = "",
) -> RegisterDocument:
    """Describe the RFI log of one project.

    Args:
        rfis: :class:`~app.modules.rfi.models.RFI` rows, or objects with the
            same attributes, in print order.
        project: The project the log belongs to.
        people: Display names keyed by ``str(user_id)``.
        days_open: Days each RFI has been open, keyed by RFI id. The caller
            computes it with the helper the list and detail views use, so the
            three agree.
        locale: Document language; unsupported values fall back to English.
        generated: The timestamp printed in the footer.

    Returns:
        The log, ready for the PDF or the workbook renderer.
    """
    locale = CATALOGUE.normalize(locale)
    tr = CATALOGUE.tr
    columns = [
        RegisterColumn(tr(locale, "col_number"), weight=1.0, xlsx_width=10),
        RegisterColumn(tr(locale, "col_subject"), weight=3.0, xlsx_width=45, wrap=True),
        RegisterColumn(tr(locale, "status"), weight=1.0, xlsx_width=12),
        RegisterColumn(tr(locale, "col_raised_by"), weight=1.4, xlsx_width=22),
        RegisterColumn(tr(locale, "col_assigned_to"), weight=1.4, xlsx_width=22),
        RegisterColumn(tr(locale, "col_ball_in_court"), weight=1.4, xlsx_width=22),
        RegisterColumn(tr(locale, "col_date_required"), kind="date", weight=1.3, xlsx_width=14),
        RegisterColumn(tr(locale, "col_response_due"), kind="date", weight=1.3, xlsx_width=14),
        RegisterColumn(tr(locale, "col_days_open"), kind="count", weight=0.8, xlsx_width=10),
        RegisterColumn(tr(locale, "col_cost_impact"), weight=1.6, xlsx_width=22),
        RegisterColumn(tr(locale, "col_schedule_impact"), weight=1.3, xlsx_width=16),
        RegisterColumn(tr(locale, "col_response"), weight=3.2, xlsx_width=60, wrap=True),
    ]
    open_days = days_open or {}
    rows = []
    for item in rfis:
        schedule_days = getattr(item, "schedule_impact_days", None)
        rows.append(
            [
                getattr(item, "rfi_number", ""),
                getattr(item, "subject", ""),
                localize_status(str(getattr(item, "status", "") or "draft"), locale),
                person_name(getattr(item, "raised_by", None), people),
                person_name(getattr(item, "assigned_to", None), people),
                person_name(getattr(item, "ball_in_court", None), people),
                getattr(item, "date_required", None),
                getattr(item, "response_due_date", None),
                open_days.get(getattr(item, "id", None)),
                _impact(
                    getattr(item, "cost_impact", False),
                    _cost_detail(getattr(item, "cost_impact_value", None), project),
                    locale,
                ),
                _impact(
                    getattr(item, "schedule_impact", False),
                    CATALOGUE.days(schedule_days, locale) if isinstance(schedule_days, int) else None,
                    locale,
                ),
                getattr(item, "official_response", None),
            ]
        )
    return RegisterDocument(
        title=tr(locale, "register_title"),
        columns=columns,
        rows=rows,
        details=CATALOGUE.register_details(locale, project, count=len(rows)),
        locale=locale,
        number_style=project.number_style,
        generated=generated,
        empty_text=tr(locale, "empty_register"),
        sheet_title="RFI Log" if locale == "en" else tr(locale, "register_title"),
        doc_type="rfi",
        **CATALOGUE.furniture(locale),
    )
