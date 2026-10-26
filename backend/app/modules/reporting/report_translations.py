# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""String catalogue and locale resolution for generated reports.

Every word a generated report put in front of a reader used to be an English
literal: the section headings, the field labels, the metadata line, the
"no data" notice, the AI-narrative caution, ``Yes`` / ``No``, and the
``<html lang="en">`` attribute. The module carried a locale-aware toolkit
(:mod:`app.modules.reporting.intl`) but nothing on the render or export path
called it, so a reader who set the interface to German still downloaded an
English PDF. This file is the catalogue those two paths now read.

* **The platform catalogue.** The strings live in ``backend/locales/<code>.json``
  under ``reporting.doc.*``, ``reporting.section.*`` and ``reporting.field.*``,
  so a report can be written in every language the interface offers.
* **Shared resolution**, from :mod:`app.core.document_locale`: an explicit
  ``?locale=`` query parameter wins, otherwise the first ``Accept-Language``
  tag whose primary subtag this table has, otherwise English. The
  middleware's context locale is deliberately not reused, so a report's
  language depends only on what this table can actually render.
* **English is byte-for-byte what the module shipped before.** Every English
  value here is the literal it replaced, including the two that read wrong
  (``Open Rfis``, ``Cpi``): fixing those is a change to the English document
  and belongs in its own commit, not hidden inside a localization one.

A key a language lacks reads in English, key by key. The routes serving a
report declare the language they resolved in ``Content-Language`` - see
:mod:`app.core.document_locale`.
"""

from __future__ import annotations

import re
from typing import Any

from app.core.document_locale import normalize_document_locale, resolve_document_locale
from app.core.i18n import SUPPORTED_LOCALES, lookup, t

__all__ = [
    "DEFAULT_REPORT_LOCALE",
    "SUPPORTED_REPORT_LOCALES",
    "field_label",
    "normalize_report_locale",
    "resolve_report_locale",
    "section_title",
    "tr",
]

DEFAULT_REPORT_LOCALE = "en"

#: Languages a generated report can be rendered in: every interface language.
SUPPORTED_REPORT_LOCALES: tuple[str, ...] = tuple(SUPPORTED_LOCALES)

# ── Locale resolution ─────────────────────────────────────────────────────


def normalize_report_locale(value: str | None) -> str:
    """Reduce a locale-ish value to a language this catalogue can render.

    Args:
        value: A locale code such as ``"de"``, ``"de-DE"`` or ``"DE"``.

    Returns:
        A member of :data:`SUPPORTED_REPORT_LOCALES`.
    """
    return normalize_document_locale(value, SUPPORTED_REPORT_LOCALES, DEFAULT_REPORT_LOCALE)


def resolve_report_locale(locale_param: str | None, accept_language: str | None) -> str:
    """Pick the language of a report for one HTTP request.

    Args:
        locale_param: Explicit ``?locale=`` query value, if any.
        accept_language: Raw ``Accept-Language`` header value, if any.

    Returns:
        A member of :data:`SUPPORTED_REPORT_LOCALES`. When it is
        :data:`DEFAULT_REPORT_LOCALE` but the caller asked for something
        else, the document is a fallback and the route must say so in
        ``Content-Language``.
    """
    return resolve_document_locale(
        locale_param,
        accept_language,
        SUPPORTED_REPORT_LOCALES,
        DEFAULT_REPORT_LOCALE,
    )


# ── Lookups ───────────────────────────────────────────────────────────────


def tr(locale: str, key: str, **params: Any) -> str:
    """Resolve a report-chrome string, falling back to English then the key.

    Args:
        locale: A member of :data:`SUPPORTED_REPORT_LOCALES`; anything else
            reads the English table.
        key: Catalogue key, e.g. ``"no_data_heading"``.
        **params: ``str.format`` interpolation values.

    Returns:
        The resolved, formatted string.
    """
    return t(f"reporting.doc.{key}", locale, **params)


def section_title(title: str, locale: str) -> str:
    """Localize a section heading, leaving a caller's own heading untouched.

    *title* is looked up as itself. The platform's own headings - the
    renderer's ``_DEFAULT_SECTIONS`` and the ``SYSTEM_TEMPLATES`` rows seeded
    into the database - are in the table and come back translated. A heading
    a user wrote into their own template is not, and comes back unchanged,
    which is the point: translating it would mean overwriting their text with
    ours whenever it happened to collide.

    Args:
        title: The section heading as the template or the default list holds it.
        locale: A member of :data:`SUPPORTED_REPORT_LOCALES`.

    Returns:
        The localized heading, or *title* verbatim when it is not ours.
    """
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
    english = lookup(f"reporting.section.{slug}", DEFAULT_REPORT_LOCALE)
    if not slug or english != title:
        return title
    return lookup(f"reporting.section.{slug}", locale) or title


def field_label(key: Any, locale: str) -> str:
    """Localize a snapshot key into a row label.

    Falls back to the Title-Cased key the renderer and the exporters used
    before this catalogue existed, so a caller-supplied snapshot carrying
    keys the platform never emits still labels its rows readably.

    Args:
        key: A snapshot key, e.g. ``"net_cash_flow"``.
        locale: A member of :data:`SUPPORTED_REPORT_LOCALES`.

    Returns:
        The localized label, or the Title-Cased key.
    """
    text = str(key)
    return lookup(f"reporting.field.{text}", locale) or text.replace("_", " ").title()
