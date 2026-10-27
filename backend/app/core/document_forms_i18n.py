# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Printed form strings read from the platform's locale files.

The procurement and finance record forms used to keep their strings in Python
dictionaries with English, German and Russian only, so every other language
printed in English. Their strings now live in ``backend/locales/<code>.json``
under ``document_forms.<form>``, the same files and the same translation
workflow as every other backend string, and a catalogue is built from them
for every language in :data:`app.core.i18n.SUPPORTED_LOCALES`.

Layout inside a locale file::

    "document_forms": {
      "furniture": {"signature": "...", "footer_page": "...", ...},
      "<form>": {
        "strings": {"invoice_title": "...", ...},
        "labels": {"<table>": {"<code>": "...", ...}, ...}
      }
    }

A language joins a form's catalogue once its file translates at least one of
that form's strings. Until then a request in it prints English and the route
says ``Content-Language: en``, as before, rather than claiming a language the
body is not in. A key a language has not translated yet falls back to English.

Documents that need no register page furniture (the bill of quantities PDF, the
generated reports, the e-invoice page) read the same blocks through
:func:`form_strings` and :func:`form_labels`: ``{language: {key: text}}`` with
English filled in key by key. A language joins once its file translates at
least one string, so adding a language is translating the block, never code.

Page furniture (footer, signature captions, "Total") keeps the shared tables
in :mod:`app.core.register_export` for the languages they already carry; a
language they do not carry reads ``document_forms.furniture`` with English
for any gap. The date patterns are never translated text: a language without
a furniture table prints ISO dates unless the project's country decides.
"""

from __future__ import annotations

import json
from collections.abc import Collection
from functools import cache
from typing import Any

from app.core.i18n import LOCALES_DIR, SUPPORTED_LOCALES
from app.core.register_export import FORM_FURNITURE, FURNITURE, DocumentCatalogue

__all__ = [
    "REGISTER_UNRENDERABLE",
    "document_form_catalogue",
    "document_form_locales",
    "form_labels",
    "form_strings",
    "load_document_forms",
    "register_form_catalogue",
]

_ROOT = "document_forms"

#: Languages the register and record forms deliberately print in English, and
#: why. Bengali is translated in the locale files but not offered, because no
#: bundled face carries its script. Urdu is offered: its letters need the
#: bundled Naskh face, which has digits and Arabic only, while brackets, slashes
#: and Latin letters need the Unicode face, and the PDF layer now sets such a
#: string in runs, one face per run (``app.core.pdf_fonts.pdf_font_runs``).
REGISTER_UNRENDERABLE: dict[str, str] = {
    "bn": "no bundled PDF face carries Bengali glyphs",
}
_DATE_KEYS = ("date_format", "datetime_format")

#: Forms read through :func:`form_strings` rather than a register catalogue, with
#: the languages each one lists as unavailable besides :data:`REGISTER_UNRENDERABLE`.
#: A bill's PDF labels are Chinese in part only and the PDF declares them English,
#: so its list leaves Chinese out.
_PLAIN_FORMS: dict[str, tuple[str, ...]] = {"boq_pdf": ("zh",), "report": (), "einvoice_pdf": ()}


@cache
def load_document_forms(code: str) -> dict[str, Any]:
    """The ``document_forms`` block of one locale file, or an empty dict."""
    path = LOCALES_DIR / f"{code}.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    block = data.get(_ROOT)
    return block if isinstance(block, dict) else {}


def _text_map(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    # Not stripped: a thousands separator is legitimately one non-breaking space.
    return {str(k): v for k, v in value.items() if isinstance(v, str) and v != ""}


def _furniture_for(code: str, default: str) -> dict[str, str]:
    """Furniture for a language the shared tables do not carry."""
    english = FURNITURE[default]
    own = _text_map(load_document_forms(code).get("furniture"))
    return {key: (english[key] if key in _DATE_KEYS else own.get(key, english[key])) for key in english}


def form_strings(form: str, *, default: str = "en") -> dict[str, dict[str, str]]:
    """The plain strings of one form for every language that translates part of it.

    For a document that needs no register page furniture (a bill's PDF labels,
    for instance): ``{language: {key: text}}`` with the default language first.
    A language joins once its file translates at least one string, and a key it
    has not translated reads the default language's text, so every table is
    complete.

    Raises:
        ValueError: When the default language defines no strings for ``form``.
    """
    english = _text_map((load_document_forms(default).get(form) or {}).get("strings"))
    if not english:
        raise ValueError(f"locales/{default}.json has no {_ROOT}.{form}.strings")
    tables: dict[str, dict[str, str]] = {}
    for code in SUPPORTED_LOCALES:
        if code in REGISTER_UNRENDERABLE:
            continue
        own = _text_map((load_document_forms(code).get(form) or {}).get("strings"))
        if code == default or any(key in own for key in english):
            tables[code] = {key: own.get(key, value) for key, value in english.items()}
    return tables


def form_labels(form: str, name: str, *, default: str = "en") -> dict[str, dict[str, str]]:
    """One named code table of a form for the languages :func:`form_strings` lists.

    Layout in a locale file: ``document_forms.<form>.labels.<name>``. Every
    language of the form gets the table complete: a key it has not translated
    reads the default language's text.

    Raises:
        ValueError: When the default language defines no such table.
    """
    english = _text_map(((load_document_forms(default).get(form) or {}).get("labels") or {}).get(name))
    if not english:
        raise ValueError(f"locales/{default}.json has no {_ROOT}.{form}.labels.{name}")
    tables: dict[str, dict[str, str]] = {}
    for code in form_strings(form, default=default):
        own = _text_map(((load_document_forms(code).get(form) or {}).get("labels") or {}).get(name))
        tables[code] = {key: own.get(key, value) for key, value in english.items()}
    return tables


def document_form_catalogue(form: str, *, default: str = "en", skip: Collection[str] = ()) -> DocumentCatalogue:
    """Build the catalogue of one printed form from the locale files.

    Args:
        form: The block name under ``document_forms``, e.g. ``"finance"``.
        default: The fallback language; its file must define every string.
        skip: Languages left out although their file translates the form.

    Returns:
        A complete :class:`DocumentCatalogue` covering the default language and
        every supported language that translates part of the form.

    Raises:
        ValueError: When the default language defines no strings for ``form``.
    """
    english_block = load_document_forms(default).get(form) or {}
    english = _text_map(english_block.get("strings"))
    if not english:
        raise ValueError(f"locales/{default}.json has no {_ROOT}.{form}.strings")
    english_labels = {str(name): _text_map(table) for name, table in (english_block.get("labels") or {}).items()}

    strings: dict[str, dict[str, str]] = {}
    labels: dict[str, dict[str, dict[str, str]]] = {name: {} for name in english_labels}
    furniture: dict[str, dict[str, str]] = dict(FORM_FURNITURE)
    for code in SUPPORTED_LOCALES:
        block = load_document_forms(code).get(form) or {}
        own = _text_map(block.get("strings"))
        if code in skip or (code != default and not any(key in own for key in english)):
            continue
        strings[code] = {key: own.get(key, value) for key, value in english.items()}
        own_labels = block.get("labels") or {}
        for name, table in english_labels.items():
            mine = _text_map(own_labels.get(name))
            labels[name][code] = {key: mine.get(key, value) for key, value in table.items()}
        if code not in FURNITURE and code not in furniture:
            furniture[code] = _furniture_for(code, default)
    return DocumentCatalogue(strings, labels, default=default, furniture=furniture)


def document_form_locales(default: str = "en") -> dict[str, tuple[str, ...]]:
    """The languages each printed form can be rendered in, keyed by form name.

    Reads the same locale files :func:`document_form_catalogue` does, so the
    answer is what a request for that language really gets. A form missing
    from the default language's file is not listed.
    """
    forms = [name for name in load_document_forms(default) if name != "furniture"]
    return {name: _locales_of(name, default) for name in sorted(forms)}


def register_form_catalogue(form: str) -> DocumentCatalogue:
    """The catalogue of a register or record form: every language but :data:`REGISTER_UNRENDERABLE`."""
    return document_form_catalogue(form, skip=REGISTER_UNRENDERABLE)


def _locales_of(form: str, default: str) -> tuple[str, ...]:
    if form in _PLAIN_FORMS:
        left_out = {*REGISTER_UNRENDERABLE, *_PLAIN_FORMS[form]}
        return tuple(code for code in form_strings(form, default=default) if code not in left_out)
    return document_form_catalogue(form, default=default, skip=REGISTER_UNRENDERABLE).supported
