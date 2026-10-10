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
and type words are the interface's own. One type has a form name of its own
on a Turkish site: a material (product data) submittal is printed as
"Malzeme Onay Formu", the title contractors' own material approval forms
carry, so the form's title follows the type (``doc_title_product_data``).
The register is a "Kayıt Listesi", the one word for a register across the
printed set, and the date a review is required by is "Yanıt son tarihi",
the set's one term for a response due date.

The register columns added for procurement (discipline, manufacturer, origin,
supplier) use the words a Turkish contractor's material approval form prints:
"Disiplin", "Üretici", "Marka", "Menşei", "Tedarikçi", "Şartname Bölümü".
"Onay Kodu", "Temin Süresi" and "Şantiyede Gerekli Tarih" are plain Turkish
for columns such a form does not carry.

A register filtered to one type is still this register. Three types have a
name of their own on site, so the title follows the filter:
``register_title_shop_drawing`` and its neighbours.
"""

from __future__ import annotations

from typing import Any

from app.core.register_export import DocumentCatalogue, export_filename
from app.modules.submittals.tracking import DISCIPLINES

__all__ = [
    "CATALOGUE",
    "DEFAULT_PDF_LOCALE",
    "SUPPORTED_PDF_LOCALES",
    "doc_title",
    "normalize_pdf_locale",
    "register_title",
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
        "doc_title_product_data": "Material Approval Form",
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
        "register_title_shop_drawing": "Shop Drawing Register",
        "register_title_product_data": "Material Approval Register",
        "register_title_method_statement": "Method Statement Register",
        "register_filename_shop_drawing": "shop-drawing-register",
        "register_filename_product_data": "material-approval-register",
        "register_filename_method_statement": "method-statement-register",
        "col_discipline": "Discipline",
        "col_manufacturer": "Manufacturer / brand",
        "col_model": "Model / reference",
        "col_origin": "Country of origin",
        "col_supplier": "Supplier",
        "col_product": "Maker / model / origin",
        "col_review_code": "Review code",
        "col_outcome": "Review outcome",
        "col_review_period": "Review period (days)",
        "col_review_due": "Review due",
        "col_days_in_review": "Days in review",
        "col_days_in_review_print": "Days in review",
        "col_review_overdue": "Days overdue",
        "col_required_on_site": "Required on site",
        "col_long_lead": "Long lead",
        "col_lead_time": "Lead time (weeks)",
        "col_needed_by": "Approval needed by",
        "col_approval_late": "Days past needed-by",
        "col_drawings": "Linked drawings",
        "col_submitted_returned": "Submitted / returned",
        "col_on_site_needed_by": "On site / approval by",
        "resubmit_for_record": "Corrected copy to be resubmitted for record",
        "review_history": "Review history",
        "hist_submitted": "Submitted",
        "hist_returned": "Returned",
        "drawings_missing_one": "{n} linked drawing is no longer available",
        "drawings_missing_other": "{n} linked drawings are no longer available",
        "weeks_one": "{n} week",
        "weeks_other": "{n} weeks",
    },
    "tr": {
        "register_title": "Onay Belgeleri Kayıt Listesi",
        "doc_title": "Onay Belgesi",
        "doc_title_product_data": "Malzeme Onay Formu",
        "col_number": "Belge no.",
        "col_title": "Başlık",
        "col_type": "Tür",
        "col_spec": "Şartname bölümü",
        "col_rev": "Rev.",
        "col_date_submitted": "Sunulma tarihi",
        "col_date_required": "Yanıt son tarihi",
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
        "register_filename": "onay-belgeleri-kayit-listesi",
        "register_title_shop_drawing": "İmalat Çizimleri Kayıt Listesi",
        "register_title_product_data": "Malzeme Onay Kayıt Listesi",
        "register_title_method_statement": "Metot Beyanları Kayıt Listesi",
        "register_filename_shop_drawing": "imalat-cizimleri-kayit-listesi",
        "register_filename_product_data": "malzeme-onay-kayit-listesi",
        "register_filename_method_statement": "metot-beyanlari-kayit-listesi",
        "col_discipline": "Disiplin",
        "col_manufacturer": "Üretici / Marka",
        "col_model": "Model / Referans",
        "col_origin": "Menşei",
        "col_supplier": "Tedarikçi",
        "col_product": "Üretici / Model / Menşei",
        "col_review_code": "Onay Kodu",
        "col_outcome": "İnceleme sonucu",
        "col_review_period": "İnceleme süresi (gün)",
        "col_review_due": "İnceleme son tarihi",
        "col_days_in_review": "İncelemede geçen gün",
        "col_days_in_review_print": "İnceleme gün sayısı",
        "col_review_overdue": "Geciken gün",
        "col_required_on_site": "Şantiyede Gerekli Tarih",
        "col_long_lead": "Uzun temin süreli",
        "col_lead_time": "Temin Süresi (hafta)",
        "col_needed_by": "Onay için son tarih",
        "col_approval_late": "Onayda geciken gün",
        "col_drawings": "İlgili çizimler",
        "col_submitted_returned": "Sunulma / iade",
        "col_on_site_needed_by": "Şantiye / onay son tarihi",
        "resubmit_for_record": "Düzeltilmiş nüsha kayıt için yeniden sunulacak",
        "review_history": "İnceleme geçmişi",
        "hist_submitted": "Sunuldu",
        "hist_returned": "İade edildi",
        "drawings_missing_one": "{n} ilgili çizim artık mevcut değil",
        "drawings_missing_other": "{n} ilgili çizim artık mevcut değil",
        "weeks_one": "{n} hafta",
        "weeks_other": "{n} hafta",
    },
}

# One entry per value in ``intl.SUBMITTAL_STATUSES`` and ``schemas.SUBMITTAL_TYPES``.
# The register prints the module's own review vocabulary: a review outcome is
# one of the four decision statuses and is printed with the same word, and the
# code beside it is the mark the reviewer stamped, printed as stored.
# The discipline table is built from ``tracking.DISCIPLINES``; a discipline a
# project adds on its own prints as stored.
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
    "discipline": {language: {item.code: item.labels[language] for item in DISCIPLINES} for language in ("en", "tr")},
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


def _typed_key(prefix: str, submittal_type: str | None) -> str:
    """The key of a per-type string when the catalogue has one, else the general key."""
    typed = f"{prefix}_{submittal_type}" if submittal_type else prefix
    return typed if typed in _STRINGS[DEFAULT_PDF_LOCALE] else prefix


def register_title(locale: str, submittal_type: str | None = None) -> str:
    """The register's name, which follows a type filter that has a name of its own.

    Filtered to shop drawings it is the shop drawing register, to product
    data the material approval register. Any other filter keeps the general
    title, and the filter is printed in the details above the table.
    """
    return tr(locale, _typed_key("register_title", submittal_type))


def doc_title(locale: str, submittal_type: str | None = None) -> str:
    """The title of one submittal's printed form, which follows a type that has a form name of its own."""
    return tr(locale, _typed_key("doc_title", submittal_type))


def submittal_register_filename(locale: str, extension: str, submittal_type: str | None = None) -> str:
    """Download filename for the register, e.g. ``submittal-register.xlsx``."""
    return export_filename(tr(locale, _typed_key("register_filename", submittal_type)), "submittal-register", extension)
