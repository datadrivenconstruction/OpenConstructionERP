# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""String catalogue for the printed variation, claim and notice registers.

Three registers leave this module on paper: the variation register (what was
asked for, what was agreed, the time it costs), the claims register
(disruption and extension of time claims side by side) and the notice
register. Their fixed strings live here, next to the renderer, the way
:mod:`app.modules.rfi.pdf_translations` keeps the RFI's.

The strings live in ``backend/locales/<code>.json`` under ``document_forms.variations``
and are built into a catalogue by :func:`app.core.document_forms_i18n.document_form_catalogue`,
so the document can be printed in every language a PDF can draw. A key a
language has not translated reads English, and a language outside the
catalogue (Bengali and Urdu, see ``REGISTER_UNRENDERABLE``) renders in English
with the route saying so in ``Content-Language``.

The Turkish follows the variation screens of the interface, which call the
module "İlave İşler". A claim is "hak talebi" here, the term a Turkish
contract uses, because the interface's bare "talep" also means any request.
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
    "register_filename",
    "resolve_pdf_locale",
    "tr",
    "variation_pdf_filename",
]

DEFAULT_PDF_LOCALE = "en"

#: Strings and code tables come from ``backend/locales/<code>.json`` under
#: ``document_forms.variations``; English is the fallback for any gap.
CATALOGUE = register_form_catalogue("variations")

#: Languages the variation documents can render; anything else is English.
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


def variation_pdf_filename(code: str | None) -> str:
    """Download filename for one variation request, e.g. ``VR-004.pdf``."""
    return export_filename(code, "variation-request", "pdf")


def register_filename(register: str, locale: str, extension: str) -> str:
    """Download filename for a register.

    Args:
        register: ``"variation"``, ``"claim"`` or ``"notice"``.
        locale: The document language.
        extension: ``"pdf"`` or ``"xlsx"``.
    """
    return export_filename(tr(locale, f"{register}_register_filename"), f"{register}-register", extension)
