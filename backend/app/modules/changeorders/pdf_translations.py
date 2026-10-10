# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""String catalogue for the printed change order register and change order form.

The register lists every change order of a project with what the contractor
asked for, what the engineer assessed, what was approved and the time each
one costs. Its fixed strings live here, next to the renderer, the way
:mod:`app.modules.rfi.pdf_translations` keeps the RFI's.

English and Turkish are in the catalogue; any other request renders in
English and the route says so in ``Content-Language``. The status, reason and
type words are short register words, not the explanatory sentences of
:mod:`app.modules.changeorders.intl`, which are written for a tooltip and
would not fit a column.

The Turkish follows the change order screens of the interface.
"""

from __future__ import annotations

from typing import Any

from app.core.register_export import DocumentCatalogue, export_filename

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

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "register_title": "Change Order Register",
        "doc_title": "Change Order",
        "col_code": "Code",
        "col_title": "Title",
        "col_reason": "Reason",
        "col_instrument": "Instrument",
        "col_submitted": "Date submitted",
        "col_contractor_amount": "Contractor amount",
        "col_engineer_amount": "Engineer amount",
        "col_approved_amount": "Approved amount",
        "col_cost_impact": "Cost impact",
        "col_time_impact": "Time impact (days)",
        "col_approved_time": "Approved time (days)",
        "time_impact": "Time impact",
        "approved_time": "Approved time",
        "col_approved": "Date approved",
        "submitted_by": "Submitted by",
        "approved_by": "Approved by",
        "description": "Description",
        "no_description": "No description recorded.",
        "items": "Change items",
        "item_description": "Description",
        "item_change": "Change",
        "item_unit": "Unit",
        "item_original_quantity": "Original qty",
        "item_new_quantity": "New qty",
        "item_original_rate": "Original rate",
        "item_new_rate": "New rate",
        "item_cost_delta": "Cost difference",
        "register_filename": "change-order-register",
    },
    "tr": {
        "register_title": "Değişiklik Emirleri Kayıt Listesi",
        "doc_title": "Değişiklik Emri",
        "col_code": "Kod",
        "col_title": "Başlık",
        "col_reason": "Neden",
        "col_instrument": "Belge türü",
        "col_submitted": "Gönderilme tarihi",
        "col_contractor_amount": "Yüklenici talebi",
        "col_engineer_amount": "Mühendis değerlendirmesi",
        "col_approved_amount": "Onaylanan tutar",
        "col_cost_impact": "Maliyet etkisi",
        "col_time_impact": "Süre etkisi (gün)",
        "col_approved_time": "Onaylanan süre (gün)",
        "time_impact": "Süre etkisi",
        "approved_time": "Onaylanan süre",
        "col_approved": "Onay tarihi",
        "submitted_by": "Gönderen",
        "approved_by": "Onaylayan",
        "description": "Açıklama",
        "no_description": "Açıklama kaydedilmedi.",
        "items": "Değişiklik kalemleri",
        "item_description": "Açıklama",
        "item_change": "Değişiklik",
        "item_unit": "Birim",
        "item_original_quantity": "Önceki miktar",
        "item_new_quantity": "Yeni miktar",
        "item_original_rate": "Önceki birim fiyat",
        "item_new_rate": "Yeni birim fiyat",
        "item_cost_delta": "Maliyet farkı",
        "register_filename": "degisiklik-emirleri-kayit-listesi",
    },
}

# One entry per value in ``intl.CHANGE_ORDER_STATUSES``, ``intl.REASON_CATEGORIES``,
# ``intl.VARIATION_TYPES`` and ``intl.CHANGE_TYPE_LABELS``.
_LABELS: dict[str, dict[str, dict[str, str]]] = {
    "status": {
        "en": {
            "draft": "Draft",
            "submitted": "Submitted",
            "approved": "Approved",
            "rejected": "Rejected",
            "executed": "Executed",
        },
        "tr": {
            "draft": "Taslak",
            "submitted": "Gönderildi",
            "approved": "Onaylandı",
            "rejected": "Reddedildi",
            "executed": "Uygulandı",
        },
    },
    "reason": {
        "en": {
            "client_request": "Client request",
            "design_change": "Design change",
            "unforeseen": "Unforeseen conditions",
            "regulatory": "Regulatory",
            "error": "Error or omission",
            "non_conformance": "Non-conformance",
            "value_engineering": "Value engineering",
        },
        "tr": {
            "client_request": "İşveren talebi",
            "design_change": "Tasarım değişikliği",
            "unforeseen": "Öngörülemeyen koşullar",
            "regulatory": "Mevzuat",
            "error": "Hata veya eksiklik",
            "non_conformance": "Uygunsuzluk",
            "value_engineering": "Değer mühendisliği",
        },
    },
    "instrument": {
        "en": {
            "works_change": "Instructed change",
            "site_confirmation": "Site confirmation",
            "claim": "Claim",
        },
        "tr": {
            "works_change": "İş değişikliği talimatı",
            "site_confirmation": "Saha tespit tutanağı",
            "claim": "Hak talebi",
        },
    },
    "change": {
        "en": {"added": "Added", "removed": "Removed", "modified": "Modified"},
        "tr": {"added": "Eklendi", "removed": "Kaldırıldı", "modified": "Değiştirildi"},
    },
}

CATALOGUE = DocumentCatalogue(_STRINGS, _LABELS, default=DEFAULT_PDF_LOCALE)

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
