# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""String catalogue for the printed submittal register and submittal form.

The submittal register is the log a contractor attaches to a letter to show
what was submitted, in which revision, when it was required and when and how
it came back. Its fixed strings live here, next to the renderer, the way
:mod:`app.modules.rfi.pdf_translations` keeps the RFI's, and the rule that
picks a language is the shared one in :mod:`app.core.document_locale`.

English and Turkish are in the catalogue. Any other request renders in
English and the route says so in ``Content-Language``. The status and type
words are held here rather than read from :mod:`app.modules.submittals.intl`
because a heading in one language over a status word in another is the
defect a catalogue exists to prevent, and the two tables there cover a
different set of languages.

The Turkish follows the submittal screens: "Onay Belgesi" is what the
interface calls a submittal where it creates and edits one, and the status
and type words are the interface's own.
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
    "submittal_pdf_filename",
    "submittal_register_filename",
    "tr",
]

DEFAULT_PDF_LOCALE = "en"

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "register_title": "Submittal Register",
        "doc_title": "Submittal",
        "col_number": "Submittal no.",
        "col_title": "Title",
        "col_type": "Type",
        "col_spec": "Spec section",
        "col_rev": "Rev.",
        "col_date_submitted": "Date submitted",
        "col_date_required": "Date required",
        "col_date_returned": "Date returned",
        "col_reviewer": "Reviewer",
        "col_approver": "Approver",
        "col_ball_in_court": "Ball in court",
        "submitted_by_org": "Submitting company",
        "review_notes": "Reviewer comments",
        "no_review_notes": "No reviewer comments recorded.",
        "sig_submitted": "Submitted by",
        "sig_reviewed": "Reviewed by",
        "sig_approved": "Approved by",
        "register_filename": "submittal-register",
    },
    "tr": {
        "register_title": "Onay Belgeleri Takip Listesi",
        "doc_title": "Onay Belgesi",
        "col_number": "Belge no.",
        "col_title": "Başlık",
        "col_type": "Tür",
        "col_spec": "Şartname bölümü",
        "col_rev": "Rev.",
        "col_date_submitted": "Sunulma tarihi",
        "col_date_required": "Gerekli tarih",
        "col_date_returned": "İade tarihi",
        "col_reviewer": "İnceleyen",
        "col_approver": "Onaylayan",
        "col_ball_in_court": "Sıradaki sorumlu",
        "submitted_by_org": "Sunan firma",
        "review_notes": "İnceleyen yorumları",
        "no_review_notes": "İnceleyen yorumu kaydedilmedi.",
        "sig_submitted": "Sunan",
        "sig_reviewed": "İnceleyen",
        "sig_approved": "Onaylayan",
        "register_filename": "onay-belgeleri-takip-listesi",
    },
}

# One entry per value in ``intl.SUBMITTAL_STATUSES`` and ``schemas.SUBMITTAL_TYPES``.
# The register prints the module's own review vocabulary; it does not add an
# approval-code scheme of its own.
_LABELS: dict[str, dict[str, dict[str, str]]] = {
    "status": {
        "en": {
            "draft": "Draft",
            "submitted": "Submitted",
            "under_review": "Under review",
            "approved": "Approved",
            "approved_as_noted": "Approved as noted",
            "revise_and_resubmit": "Revise and resubmit",
            "rejected": "Rejected",
            "closed": "Closed",
        },
        "tr": {
            "draft": "Taslak",
            "submitted": "Sunuldu",
            "under_review": "İncelemede",
            "approved": "Onaylandı",
            "approved_as_noted": "Notlarla onaylandı",
            "revise_and_resubmit": "Revize edip yeniden sunun",
            "rejected": "Reddedildi",
            "closed": "Kapatıldı",
        },
    },
    "type": {
        "en": {
            "shop_drawing": "Shop drawing",
            "product_data": "Product data",
            "sample": "Sample",
            "mock_up": "Mock-up",
            "test_report": "Test report",
            "calculation": "Calculation",
            "method_statement": "Method statement",
            "certificate": "Certificate",
            "warranty": "Warranty",
        },
        "tr": {
            "shop_drawing": "İmalat çizimi",
            "product_data": "Ürün verisi",
            "sample": "Numune",
            "mock_up": "Maket",
            "test_report": "Test raporu",
            "calculation": "Hesap",
            "method_statement": "Metot beyanı",
            "certificate": "Sertifika",
            "warranty": "Garanti",
        },
    },
}

CATALOGUE = DocumentCatalogue(_STRINGS, _LABELS, default=DEFAULT_PDF_LOCALE)

#: Languages the submittal documents can render; anything else is English.
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


def submittal_pdf_filename(submittal_number: str | None) -> str:
    """Download filename for one submittal, e.g. ``SUB-012.pdf``."""
    return export_filename(submittal_number, "submittal", "pdf")


def submittal_register_filename(locale: str, extension: str) -> str:
    """Download filename for the register, e.g. ``submittal-register.xlsx``."""
    return export_filename(tr(locale, "register_filename"), "submittal-register", extension)
