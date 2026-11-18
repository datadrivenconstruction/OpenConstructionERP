# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""String catalogue for the printed contract.

The strings live in ``backend/locales/<code>.json`` under ``document_forms.contracts``
and are built into a catalogue by :func:`app.core.document_forms_i18n.register_form_catalogue`.
A language that has not translated the block prints English, and the route says so
in ``Content-Language``.
"""

from __future__ import annotations

from typing import Any

from app.core.document_forms_i18n import register_form_catalogue
from app.core.register_export import export_filename

__all__ = [
    "CATALOGUE",
    "DEFAULT_PDF_LOCALE",
    "contract_pdf_filename",
    "normalize_pdf_locale",
    "resolve_pdf_locale",
    "tr",
]

DEFAULT_PDF_LOCALE = "en"

CATALOGUE = register_form_catalogue("contracts")


def normalize_pdf_locale(value: str | None) -> str:
    """Reduce a locale-ish value to a language the contract can be printed in."""
    return CATALOGUE.normalize(value)


def resolve_pdf_locale(locale_param: str | None, accept_language: str | None) -> str:
    """Pick the document language: ``?locale=``, then ``Accept-Language``, then English."""
    return CATALOGUE.resolve(locale_param, accept_language)


def tr(locale: str, key: str, **params: Any) -> str:
    """Resolve ``key`` for ``locale``, falling back to English, then the key."""
    return CATALOGUE.tr(locale, key, **params)


def contract_pdf_filename(code: str | None) -> str:
    """Download filename for one contract, e.g. ``C-001.pdf``."""
    return export_filename(code, "contract", "pdf")
