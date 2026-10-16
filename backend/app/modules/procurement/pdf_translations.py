# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""String catalogue for the printed purchase order and goods receipt.

The strings live in ``backend/locales/<code>.json`` under
``document_forms.procurement`` and go through the same translation workflow
as every other backend string; :func:`app.core.document_forms_i18n.document_form_catalogue`
builds the catalogue from them for every supported language. A language whose
file does not translate the form yet renders in English and the route says so
in ``Content-Language``; a single untranslated key falls back to English. The
Russian strings avoid past tense verbs, which would force a grammatical gender
onto whoever ordered or received the goods.
"""

from __future__ import annotations

from typing import Any

from app.core.document_forms_i18n import document_form_catalogue
from app.core.register_export import export_filename

__all__ = [
    "CATALOGUE",
    "DEFAULT_PDF_LOCALE",
    "SUPPORTED_PDF_LOCALES",
    "goods_receipt_pdf_filename",
    "normalize_pdf_locale",
    "purchase_order_pdf_filename",
    "resolve_pdf_locale",
    "tr",
]

DEFAULT_PDF_LOCALE = "en"

CATALOGUE = document_form_catalogue("procurement", default=DEFAULT_PDF_LOCALE)

#: Languages the procurement documents can render; anything else is English.
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


def purchase_order_pdf_filename(number: str | None) -> str:
    """Download filename for one purchase order, e.g. ``PO-0001.pdf``."""
    return export_filename(number, "purchase-order", "pdf")


def goods_receipt_pdf_filename(po_number: str | None, delivery_note: str | None) -> str:
    """Download filename for one goods receipt, e.g. ``GR_PO-0001_DN-77.pdf``."""
    stem = "_".join(part for part in ("GR", po_number, delivery_note) if part)
    return export_filename(stem, "goods-receipt", "pdf")
