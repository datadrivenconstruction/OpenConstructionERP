# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""String catalogue for the printed correspondence log and correspondence record.

The correspondence log is the incoming and outgoing register a site office
keeps: reference number, date, who wrote to whom, the subject and when a
reply is due. Its fixed strings live here, next to the renderer, the way
:mod:`app.modules.rfi.pdf_translations` keeps the RFI's.

The strings live in ``backend/locales/<code>.json`` under ``document_forms.correspondence``
and are built into a catalogue by :func:`app.core.document_forms_i18n.document_form_catalogue`,
so the document can be printed in every language a PDF can draw. A key a
language has not translated reads English, and a language outside the
catalogue (Bengali and Urdu, see ``REGISTER_UNRENDERABLE``) renders in English
with the route saying so in ``Content-Language``. The status printed is
the stored one (``open``, ``awaiting_response``, ``responded``, ``closed``),
not the derived reply status of :mod:`app.modules.correspondence.intl`,
because the register shows the record as it was filed.

The Turkish follows the correspondence screens of the interface.
"""

from __future__ import annotations

from typing import Any

from app.core.document_forms_i18n import register_form_catalogue
from app.core.register_export import export_filename

__all__ = [
    "CATALOGUE",
    "DEFAULT_PDF_LOCALE",
    "SUPPORTED_PDF_LOCALES",
    "correspondence_pdf_filename",
    "correspondence_register_filename",
    "normalize_pdf_locale",
    "resolve_pdf_locale",
    "tr",
]

DEFAULT_PDF_LOCALE = "en"

#: Strings and code tables come from ``backend/locales/<code>.json`` under
#: ``document_forms.correspondence``; English is the fallback for any gap.
CATALOGUE = register_form_catalogue("correspondence")

#: Languages the correspondence documents can render; anything else is English.
SUPPORTED_PDF_LOCALES: tuple[str, ...] = CATALOGUE.supported


def normalize_pdf_locale(value: str | None) -> str:
    """Reduce a locale-ish value to a member of :data:`SUPPORTED_PDF_LOCALES`."""
    return CATALOGUE.normalize(value)


def resolve_pdf_locale(locale_param: str | None, accept_language: str | None) -> str:
    """Pick the document language: ``?locale=``, then ``Accept-Language``, then English."""
    return CATALOGUE.resolve(locale_param, accept_language)


def tr(locale: str, key: str, **params: Any) -> str:
    """Resolve ``key`` for ``locale``, falling back to English, then the key."""
    return CATALOGUE.tr(locale, key, **params)


def correspondence_pdf_filename(reference_number: str | None) -> str:
    """Download filename for one record, e.g. ``COR-014.pdf``."""
    return export_filename(reference_number, "correspondence", "pdf")


def correspondence_register_filename(locale: str, extension: str) -> str:
    """Download filename for the log, e.g. ``correspondence-log.xlsx``."""
    return export_filename(tr(locale, "register_filename"), "correspondence-log", extension)
