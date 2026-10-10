# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""String catalogue for the printed variation, claim and notice registers.

Three registers leave this module on paper: the variation register (what was
asked for, what was agreed, the time it costs), the claims register
(disruption and extension of time claims side by side) and the notice
register. Their fixed strings live here, next to the renderer, the way
:mod:`app.modules.rfi.pdf_translations` keeps the RFI's.

English and Turkish are in the catalogue; any other request renders in
English and the route says so in ``Content-Language``.

The Turkish follows the variation screens of the interface, which call the
module "İlave İşler". A claim is "hak talebi" here, the term a Turkish
contract uses, because the interface's bare "talep" also means any request.
"""

from __future__ import annotations

from typing import Any

from app.core.register_export import DocumentCatalogue, export_filename

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

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "variation_register_title": "Variation Register",
        "claim_register_title": "Claims Register",
        "notice_register_title": "Notice Register",
        "doc_title": "Variation Request",
        "col_code": "Code",
        "col_title": "Title",
        "col_classification": "Type",
        "col_urgency": "Urgency",
        "col_requested": "Date requested",
        "col_claimed_amount": "Claimed amount",
        "col_agreed_amount": "Agreed amount",
        "col_time_impact": "Time impact (days)",
        "col_response_due": "Response due",
        "col_clause": "Contract clause",
        "col_row": "No.",
        "col_claim_type": "Claim type",
        "col_raised": "Date raised",
        "col_period_start": "Period from",
        "col_period_end": "Period to",
        "col_description": "Description",
        "col_decided_amount": "Decided amount",
        "col_days_requested": "Days requested",
        "col_days_granted": "Days granted",
        "col_recipient_type": "Addressed to",
        "col_recipient": "Recipient",
        "col_target_response": "Response expected",
        "col_response_received": "Response received",
        "requested_by": "Requested by",
        "decided_by": "Decided by",
        "date_submitted": "Date submitted",
        "date_decided": "Date decided",
        "description": "Description",
        "no_description": "No description recorded.",
        "decision_notes": "Decision notes",
        "no_decision_notes": "No decision recorded yet.",
        "variation_register_filename": "variation-register",
        "claim_register_filename": "claims-register",
        "notice_register_filename": "notice-register",
    },
    "tr": {
        "variation_register_title": "İlave İşler Kayıt Listesi",
        "claim_register_title": "Hak Talepleri Kayıt Listesi",
        "notice_register_title": "Bildirimler Kayıt Listesi",
        "doc_title": "İlave İş Talebi",
        "col_code": "Kod",
        "col_title": "Başlık",
        "col_classification": "Tür",
        "col_urgency": "Aciliyet",
        "col_requested": "Talep tarihi",
        "col_claimed_amount": "Talep edilen tutar",
        "col_agreed_amount": "Üzerinde anlaşılan tutar",
        "col_time_impact": "Süre etkisi (gün)",
        "col_response_due": "Yanıt son tarihi",
        "col_clause": "Sözleşme maddesi",
        "col_row": "Sıra no.",
        "col_claim_type": "Talep türü",
        "col_raised": "Düzenlenme tarihi",
        "col_period_start": "Dönem başlangıcı",
        "col_period_end": "Dönem bitişi",
        "col_description": "Açıklama",
        "col_decided_amount": "Karara bağlanan tutar",
        "col_days_requested": "İstenen gün",
        "col_days_granted": "Verilen gün",
        "col_recipient_type": "Muhatap",
        "col_recipient": "Alıcı",
        "col_target_response": "Beklenen yanıt tarihi",
        "col_response_received": "Yanıtın alındığı tarih",
        "requested_by": "Talep eden",
        "decided_by": "Karar veren",
        "date_submitted": "Gönderilme tarihi",
        "date_decided": "Karar tarihi",
        "description": "Açıklama",
        "no_description": "Açıklama kaydedilmedi.",
        "decision_notes": "Karar notları",
        "no_decision_notes": "Henüz karar kaydedilmedi.",
        "variation_register_filename": "ilave-isler-kayit-listesi",
        "claim_register_filename": "hak-talepleri-kayit-listesi",
        "notice_register_filename": "bildirimler-kayit-listesi",
    },
}

# One entry per value the request schemas accept: the variation request,
# notice, disruption and extension of time statuses, the classification and
# urgency of a request, and who a notice is addressed to.
_LABELS: dict[str, dict[str, dict[str, str]]] = {
    "request_status": {
        "en": {
            "draft": "Draft",
            "submitted": "Submitted",
            "under_review": "Under review",
            "approved": "Approved",
            "rejected": "Rejected",
            "converted_to_vo": "Converted to order",
        },
        "tr": {
            "draft": "Taslak",
            "submitted": "Gönderildi",
            "under_review": "İnceleniyor",
            "approved": "Onaylandı",
            "rejected": "Reddedildi",
            "converted_to_vo": "Emre dönüştürüldü",
        },
    },
    "claim_status": {
        "en": {
            "draft": "Draft",
            "submitted": "Submitted",
            "under_review": "Under review",
            "agreed": "Agreed",
            "granted": "Granted",
            "rejected": "Rejected",
        },
        "tr": {
            "draft": "Taslak",
            "submitted": "Gönderildi",
            "under_review": "İnceleniyor",
            "agreed": "Mutabık kalındı",
            "granted": "Verildi",
            "rejected": "Reddedildi",
        },
    },
    "notice_status": {
        "en": {"issued": "Issued", "acknowledged": "Acknowledged", "responded": "Responded", "closed": "Closed"},
        "tr": {
            "issued": "Yayımlandı",
            "acknowledged": "Teyit edildi",
            "responded": "Yanıtlandı",
            "closed": "Kapandı",
        },
    },
    "classification": {
        "en": {
            "scope_change": "Scope change",
            "unforeseen": "Unforeseen condition",
            "owner_change": "Owner change",
            "design_dev": "Design development",
            "regulatory": "Regulatory",
            "other": "Other",
        },
        "tr": {
            "scope_change": "Kapsam değişikliği",
            "unforeseen": "Öngörülemeyen durum",
            "owner_change": "İşveren değişikliği",
            "design_dev": "Tasarım geliştirme",
            "regulatory": "Mevzuat",
            "other": "Diğer",
        },
    },
    "urgency": {
        "en": {"low": "Low", "med": "Medium", "high": "High"},
        "tr": {"low": "Düşük", "med": "Orta", "high": "Yüksek"},
    },
    "claim_type": {
        "en": {"disruption": "Disruption", "eot": "Extension of time"},
        "tr": {"disruption": "Aksama", "eot": "Süre uzatımı"},
    },
    "recipient_type": {
        "en": {
            "owner": "Owner",
            "contractor": "Contractor",
            "architect": "Architect",
            "engineer": "Engineer",
            "consultant": "Consultant",
        },
        "tr": {
            "owner": "İşveren",
            "contractor": "Yüklenici",
            "architect": "Mimar",
            "engineer": "Mühendis",
            "consultant": "Müşavir",
        },
    },
}

CATALOGUE = DocumentCatalogue(_STRINGS, _LABELS, default=DEFAULT_PDF_LOCALE)

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
