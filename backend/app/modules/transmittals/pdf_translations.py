# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""String catalogue for the printed transmittal register and transmittal cover sheet.

A transmittal is the cover sheet that goes out with a set of documents: what
was sent, to whom, for what purpose and by when an answer is expected. The
register lists every transmittal of a project. Their fixed strings live
here, next to the renderer, the way :mod:`app.modules.rfi.pdf_translations`
keeps the RFI's.

English and Turkish are in the catalogue; any other request renders in
English and the route says so in ``Content-Language``. The status and purpose
words are capitalised register words, held here because the tables in
:mod:`app.modules.transmittals.intl` are lower-case fragments for a sentence
and cover a different set of languages.

The Turkish follows the transmittal screens of the interface, which call a
transmittal "İletim Yazısı".
"""

from __future__ import annotations

from typing import Any

from app.core.register_export import DocumentCatalogue, export_filename

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

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "register_title": "Transmittal Register",
        "doc_title": "Transmittal",
        "col_number": "Transmittal no.",
        "col_subject": "Subject",
        "col_purpose": "Purpose",
        "col_issued": "Date issued",
        "col_response_due": "Response due",
        "col_recipients": "Recipients",
        "col_item_count": "Items",
        "sender": "Sender",
        "cover_note": "Cover note",
        "no_cover_note": "No cover note.",
        "recipients": "Recipients",
        "recipient": "Recipient",
        "action_required": "Action required",
        "acknowledged": "Receipt acknowledged",
        "responded": "Date responded",
        "items": "Items transmitted",
        "item_no": "No.",
        "item_description": "Description",
        "item_notes": "Notes",
        "sig_issued": "Issued by",
        "sig_received": "Received by",
        "register_filename": "transmittal-register",
    },
    "tr": {
        "register_title": "İletim Yazıları Kayıt Listesi",
        "doc_title": "İletim Yazısı",
        "col_number": "İletim no.",
        "col_subject": "Konu",
        "col_purpose": "Amaç",
        "col_issued": "Gönderilme tarihi",
        "col_response_due": "Yanıt son tarihi",
        "col_recipients": "Alıcılar",
        "col_item_count": "Kalem sayısı",
        "sender": "Gönderen",
        "cover_note": "Kapak notu",
        "no_cover_note": "Kapak notu yok.",
        "recipients": "Alıcılar",
        "recipient": "Alıcı",
        "action_required": "İstenen işlem",
        "acknowledged": "Teslim alma teyidi",
        "responded": "Yanıt tarihi",
        "items": "İletilen kalemler",
        "item_no": "Sıra no.",
        "item_description": "Açıklama",
        "item_notes": "Notlar",
        "sig_issued": "Gönderen",
        "sig_received": "Teslim alan",
        "register_filename": "iletim-yazilari-kayit-listesi",
    },
}

# One entry per value in ``logic.VALID_STATUSES`` and ``logic.PURPOSE_CODES``.
_LABELS: dict[str, dict[str, dict[str, str]]] = {
    "status": {
        "en": {"draft": "Draft", "issued": "Issued", "responded": "Responded"},
        "tr": {"draft": "Taslak", "issued": "Gönderildi", "responded": "Yanıtlandı"},
    },
    "purpose": {
        "en": {
            "for_approval": "For approval",
            "for_review": "For review",
            "for_information": "For information",
            "for_construction": "For construction",
            "for_tender": "For tender",
            "for_record": "For record",
        },
        "tr": {
            "for_approval": "Onay için",
            "for_review": "İnceleme için",
            "for_information": "Bilgi için",
            "for_construction": "Yapım için",
            "for_tender": "İhale için",
            "for_record": "Kayıt için",
        },
    },
}

CATALOGUE = DocumentCatalogue(_STRINGS, _LABELS, default=DEFAULT_PDF_LOCALE)

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
