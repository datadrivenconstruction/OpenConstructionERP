# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""String catalogue for the printed correspondence log and correspondence record.

The correspondence log is the incoming and outgoing register a site office
keeps: reference number, date, who wrote to whom, the subject and when a
reply is due. Its fixed strings live here, next to the renderer, the way
:mod:`app.modules.rfi.pdf_translations` keeps the RFI's.

English and Turkish are in the catalogue; any other request renders in
English and the route says so in ``Content-Language``. The status printed is
the stored one (``open``, ``awaiting_response``, ``responded``, ``closed``),
not the derived reply status of :mod:`app.modules.correspondence.intl`,
because the register shows the record as it was filed.

The Turkish follows the correspondence screens of the interface.
"""

from __future__ import annotations

from typing import Any

from app.core.register_export import DocumentCatalogue, export_filename

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

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "register_title": "Correspondence Log",
        "doc_title": "Correspondence",
        "col_reference": "Reference no.",
        "col_direction": "Direction",
        "col_type": "Type",
        "col_subject": "Subject",
        "col_from": "From",
        "col_to": "To",
        "col_date_sent": "Date sent",
        "col_date_received": "Date received",
        "col_response_due": "Response required by",
        "col_clause": "Contract clause",
        "notes": "Notes",
        "no_notes": "No notes recorded.",
        "attachments": "Attached files",
        "linked_documents": "Linked documents",
        "sig_prepared": "Prepared by",
        "sig_received": "Received by",
        "register_filename": "correspondence-log",
    },
    "tr": {
        "register_title": "Yazışma Günlüğü",
        "doc_title": "Yazışma",
        "col_reference": "Referans no.",
        "col_direction": "Yön",
        "col_type": "Tür",
        "col_subject": "Konu",
        "col_from": "Gönderen",
        "col_to": "Alıcı",
        "col_date_sent": "Gönderilme tarihi",
        "col_date_received": "Alınma tarihi",
        "col_response_due": "Yanıt için son tarih",
        "col_clause": "Sözleşme maddesi",
        "notes": "Notlar",
        "no_notes": "Not kaydedilmedi.",
        "attachments": "Ekli dosyalar",
        "linked_documents": "Bağlantılı belgeler",
        "sig_prepared": "Hazırlayan",
        "sig_received": "Teslim alan",
        "register_filename": "yazisma-gunlugu",
    },
}

# One entry per stored value: ``schemas.CORRESPONDENCE_TYPES``, the two
# directions and the four stored statuses.
_LABELS: dict[str, dict[str, dict[str, str]]] = {
    "direction": {
        "en": {"incoming": "Incoming", "outgoing": "Outgoing"},
        "tr": {"incoming": "Gelen", "outgoing": "Giden"},
    },
    "type": {
        "en": {"letter": "Letter", "email": "Email", "notice": "Notice", "memo": "Memo", "report": "Report"},
        "tr": {"letter": "Mektup", "email": "E-posta", "notice": "Bildirim", "memo": "Not", "report": "Rapor"},
    },
    "status": {
        "en": {
            "open": "Open",
            "awaiting_response": "Awaiting response",
            "responded": "Responded",
            "closed": "Closed",
        },
        "tr": {
            "open": "Açık",
            "awaiting_response": "Yanıt bekleniyor",
            "responded": "Yanıtlandı",
            "closed": "Kapandı",
        },
    },
}

CATALOGUE = DocumentCatalogue(_STRINGS, _LABELS, default=DEFAULT_PDF_LOCALE)

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
