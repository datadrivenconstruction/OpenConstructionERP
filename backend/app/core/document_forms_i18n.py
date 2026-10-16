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

Page furniture (footer, signature captions, "Total") keeps the shared tables
in :mod:`app.core.register_export` for the languages they already carry; a
language they do not carry reads ``document_forms.furniture`` with English
for any gap. The date patterns are never translated text: a language without
a furniture table prints ISO dates unless the project's country decides.
"""

from __future__ import annotations

import json
from functools import cache
from typing import Any

from app.core.i18n import LOCALES_DIR, SUPPORTED_LOCALES
from app.core.register_export import FORM_FURNITURE, FURNITURE, DocumentCatalogue

__all__ = ["document_form_catalogue", "load_document_forms"]

_ROOT = "document_forms"
_DATE_KEYS = ("date_format", "datetime_format")


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
    return {str(k): v for k, v in value.items() if isinstance(v, str) and v.strip()}


def _furniture_for(code: str, default: str) -> dict[str, str]:
    """Furniture for a language the shared tables do not carry."""
    english = FURNITURE[default]
    own = _text_map(load_document_forms(code).get("furniture"))
    return {key: (english[key] if key in _DATE_KEYS else own.get(key, english[key])) for key in english}


def document_form_catalogue(form: str, *, default: str = "en") -> DocumentCatalogue:
    """Build the catalogue of one printed form from the locale files.

    Args:
        form: The block name under ``document_forms``, e.g. ``"finance"``.
        default: The fallback language; its file must define every string.

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
        if code != default and not any(key in own for key in english):
            continue
        strings[code] = {key: own.get(key, value) for key, value in english.items()}
        own_labels = block.get("labels") or {}
        for name, table in english_labels.items():
            mine = _text_map(own_labels.get(name))
            labels[name][code] = {key: mine.get(key, value) for key, value in table.items()}
        if code not in FURNITURE and code not in furniture:
            furniture[code] = _furniture_for(code, default)
    return DocumentCatalogue(strings, labels, default=default, furniture=furniture)
