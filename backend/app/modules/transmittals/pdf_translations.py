# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""String catalogue for the printed transmittal register and transmittal cover sheet.

A transmittal is the cover sheet that goes out with a set of documents: what
was sent, to whom, for what purpose and by when an answer is expected. The
register lists every transmittal of a project. Their fixed strings live
here, next to the renderer, the way :mod:`app.modules.rfi.pdf_translations`
keeps the RFI's.

The strings live in ``backend/locales/<code>.json`` under ``document_forms.transmittals``
and are built into a catalogue by :func:`app.core.document_forms_i18n.document_form_catalogue`,
so the document can be printed in every language a PDF can draw. A key a
language has not translated reads English, and a language outside the
catalogue (Bengali and Urdu, see ``REGISTER_UNRENDERABLE``) renders in English
with the route saying so in ``Content-Language``. The status and purpose
words are capitalised register words, held here because the tables in
:mod:`app.modules.transmittals.intl` are lower-case fragments for a sentence
and cover a different set of languages.

The Turkish follows the transmittal screens of the interface, which call a
transmittal "İletim Yazısı".
"""

from __future__ import annotations

from typing import Any

from app.core.document_forms_i18n import register_form_catalogue
from app.core.register_export import export_filename

__all__ = [
    "CATALOGUE",
    "DEFAULT_PDF_LOCALE",
    "SUPPORTED_PDF_LOCALES",
    "normalize_pdf_locale",
    "resolve_pdf_locale",
    "tr",
    "transmittal_pdf_filename",
    "transmittal_register_filename",
]

DEFAULT_PDF_LOCALE = "en"

#: Strings and code tables come from ``backend/locales/<code>.json`` under
#: ``document_forms.transmittals``; English is the fallback for any gap.
CATALOGUE = register_form_catalogue("transmittals")

#: Languages the transmittal documents can render; anything else is English.
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


def transmittal_pdf_filename(transmittal_number: str | None) -> str:
    """Download filename for one transmittal, e.g. ``TR-0007.pdf``."""
    return export_filename(transmittal_number, "transmittal", "pdf")


def transmittal_register_filename(locale: str, extension: str) -> str:
    """Download filename for the register, e.g. ``transmittal-register.xlsx``."""
    return export_filename(tr(locale, "register_filename"), "transmittal-register", extension)
