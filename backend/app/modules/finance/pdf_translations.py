# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""String catalogue for the printed invoice and the printed payment record.

The strings live in ``backend/locales/<code>.json`` under
``document_forms.finance`` and go through the same translation workflow as
every other backend string; :func:`app.core.document_forms_i18n.document_form_catalogue`
builds the catalogue from them for every supported language. A language whose
file does not translate the form yet renders in English and the route says so
in ``Content-Language``; a single untranslated key falls back to English. The
Brazilian RPS layout in :mod:`app.modules.finance.br_invoice_pdf` is a
separate document with its own fixed language and is not affected.
"""

from __future__ import annotations

from typing import Any

from app.core.document_forms_i18n import document_form_catalogue
from app.core.register_export import export_filename

__all__ = [
    "CATALOGUE",
    "DEFAULT_PDF_LOCALE",
    "SUPPORTED_PDF_LOCALES",
    "invoice_pdf_filename",
    "normalize_pdf_locale",
    "payment_pdf_filename",
    "resolve_pdf_locale",
    "tr",
]

DEFAULT_PDF_LOCALE = "en"

CATALOGUE = document_form_catalogue("finance", default=DEFAULT_PDF_LOCALE)

#: Languages the finance documents can render; anything else is English.
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


def invoice_pdf_filename(number: str | None) -> str:
    """Download filename for one invoice, e.g. ``INV-0042.pdf``."""
    return export_filename(number, "invoice", "pdf")


def payment_pdf_filename(invoice_number: str | None, payment_date: str | None) -> str:
    """Download filename for one payment, e.g. ``Payment_INV-0042_2026-10-01.pdf``."""
    stem = "_".join(part for part in ("Payment", invoice_number, (payment_date or "")[:10]) if part)
    return export_filename(stem, "payment", "pdf")
