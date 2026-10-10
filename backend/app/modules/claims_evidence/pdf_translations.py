# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""String catalogue for the printed evidence pack.

An evidence pack is the chronological list of records that supports a claim
or a dispute: notices, correspondence, RFIs, variations, approvals. Printed,
it is the schedule of documents attached to the claim. Its fixed strings
live here, next to the renderer, the way
:mod:`app.modules.rfi.pdf_translations` keeps the RFI's.

English and Turkish are in the catalogue; any other request renders in
English and the route says so in ``Content-Language``. The Turkish section
and basis names are the ones the evidence screen of the interface uses.
"""

from __future__ import annotations

from typing import Any

from app.core.register_export import DocumentCatalogue, export_filename

__all__ = [
    "CATALOGUE",
    "DEFAULT_PDF_LOCALE",
    "SUPPORTED_PDF_LOCALES",
    "evidence_pack_filename",
    "normalize_pdf_locale",
    "resolve_pdf_locale",
    "tr",
]

DEFAULT_PDF_LOCALE = "en"

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "register_title": "Evidence Pack",
        "subject": "Subject",
        "basis": "Basis",
        "period_from": "Earliest record",
        "period_to": "Latest record",
        "digest": "Content digest (SHA-256)",
        "col_section": "Section",
        "col_date": "Date",
        "col_kind": "Record type",
        "col_title": "Title",
        "col_summary": "Summary",
        "col_reference": "Reference",
        "register_filename": "evidence-pack",
    },
    "tr": {
        "register_title": "Kanıt Paketi",
        "subject": "Konu",
        "basis": "Dayanak",
        "period_from": "İlk kayıt",
        "period_to": "Son kayıt",
        "digest": "İçerik özeti (SHA-256)",
        "col_section": "Bölüm",
        "col_date": "Tarih",
        "col_kind": "Kayıt türü",
        "col_title": "Başlık",
        "col_summary": "Özet",
        "col_reference": "Referans",
        "register_filename": "kanit-paketi",
    },
}

# One entry per value in ``evidence_pack.SECTION_ORDER``, the record kinds of
# the change family, and the bases the evidence screen offers. A kind or a
# basis outside these tables prints as it was stored.
_LABELS: dict[str, dict[str, dict[str, str]]] = {
    "section": {
        "en": {
            "notices": "Notices",
            "correspondence": "Correspondence",
            "rfis": "RFIs",
            "variations": "Variations",
            "approvals": "Approvals",
            "delay": "Delay",
            "timeline": "Timeline",
            "other": "Other",
        },
        "tr": {
            "notices": "Bildirimler",
            "correspondence": "Yazışmalar",
            "rfis": "Bilgi Talepleri",
            "variations": "İlave İşler",
            "approvals": "Onaylar",
            "delay": "Gecikme",
            "timeline": "Zaman Çizelgesi",
            "other": "Diğer",
        },
    },
    "kind": {
        "en": {
            "notice": "Notice",
            "variation_notice": "Variation notice",
            "variation_request": "Variation request",
            "variation_order": "Variation order",
            "change_order": "Change order",
            "moc_entry": "Change record",
            "correspondence": "Correspondence",
        },
        "tr": {
            "notice": "Bildirim",
            "variation_notice": "İlave iş bildirimi",
            "variation_request": "İlave iş talebi",
            "variation_order": "İlave iş emri",
            "change_order": "Değişiklik emri",
            "moc_entry": "Değişiklik kaydı",
            "correspondence": "Yazışma",
        },
    },
    "basis": {
        "en": {
            "dispute": "Dispute",
            "valuation": "Valuation",
            "delay": "Delay / extension of time",
            "general": "General record",
        },
        "tr": {
            "dispute": "Uyuşmazlık",
            "valuation": "Değerlendirme",
            "delay": "Gecikme / süre uzatımı",
            "general": "Genel kayıt",
        },
    },
}

CATALOGUE = DocumentCatalogue(_STRINGS, _LABELS, default=DEFAULT_PDF_LOCALE)

#: Languages the evidence pack can render; anything else is English.
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


def evidence_pack_filename(locale: str, extension: str) -> str:
    """Download filename for a pack, e.g. ``evidence-pack.pdf``."""
    return export_filename(tr(locale, "register_filename"), "evidence-pack", extension)
