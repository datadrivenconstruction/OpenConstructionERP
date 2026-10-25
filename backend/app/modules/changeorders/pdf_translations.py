# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""String catalogue for the printed change order register and change order form.

The register lists every change order of a project with what the contractor
asked for, what the engineer assessed, what was approved and the time each
one costs. Its fixed strings live here, next to the renderer, the way
:mod:`app.modules.rfi.pdf_translations` keeps the RFI's.

The strings live in ``backend/locales/<code>.json`` under ``document_forms.changeorders``
and are built into a catalogue by :func:`app.core.document_forms_i18n.document_form_catalogue`,
so the document can be printed in every language a PDF can draw. A key a
language has not translated reads English, and a language outside the
catalogue (Bengali and Urdu, see ``REGISTER_UNRENDERABLE``) renders in English
with the route saying so in ``Content-Language``. The status, reason and
type words are short register words, not the explanatory sentences of
:mod:`app.modules.changeorders.intl`, which are written for a tooltip and
would not fit a column.

The Turkish follows the change order screens of the interface.
"""

from __future__ import annotations

from typing import Any

from app.core.document_forms_i18n import register_form_catalogue
from app.core.register_export import export_filename

__all__ = [
    "CATALOGUE",
    "DEFAULT_PDF_LOCALE",
    "SUPPORTED_PDF_LOCALES",
    "change_order_pdf_filename",
    "change_order_register_filename",
    "normalize_pdf_locale",
    "resolve_pdf_locale",
    "tr",
]

DEFAULT_PDF_LOCALE = "en"

#: Strings and code tables come from ``backend/locales/<code>.json`` under
#: ``document_forms.changeorders``; English is the fallback for any gap.
CATALOGUE = register_form_catalogue("changeorders")

#: Languages the change order documents can render; anything else is English.
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


def change_order_pdf_filename(code: str | None) -> str:
    """Download filename for one change order, e.g. ``CO-003.pdf``."""
    return export_filename(code, "change-order", "pdf")


def change_order_register_filename(locale: str, extension: str) -> str:
    """Download filename for the register, e.g. ``change-order-register.xlsx``."""
    return export_filename(tr(locale, "register_filename"), "change-order-register", extension)
