# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""String catalogue for the printed submittal register and submittal form.

The submittal register is the log a contractor attaches to a letter to show
what was submitted, in which revision, when it was required and when and how
it came back. Its fixed strings live here, next to the renderer, the way
:mod:`app.modules.rfi.pdf_translations` keeps the RFI's, and the rule that
picks a language is the shared one in :mod:`app.core.document_locale`.

The strings live in ``backend/locales/<code>.json`` under ``document_forms.submittals``
and are built into a catalogue by :func:`app.core.document_forms_i18n.document_form_catalogue`,
so the document can be printed in every language a PDF can draw. A key a
language has not translated reads English, and a language outside the
catalogue (Bengali and Urdu, see ``REGISTER_UNRENDERABLE``) renders in English
with the route saying so in ``Content-Language``. The status and type
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

from app.core.document_forms_i18n import register_form_catalogue
from app.core.register_export import export_filename

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

#: Strings and code tables come from ``backend/locales/<code>.json`` under
#: ``document_forms.submittals``; English is the fallback for any gap.
CATALOGUE = register_form_catalogue("submittals")

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
    return typed if typed in CATALOGUE.strings[DEFAULT_PDF_LOCALE] else prefix


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
