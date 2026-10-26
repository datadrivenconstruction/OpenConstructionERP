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

* **The platform's locale files**: the strings live in
  ``backend/locales/<code>.json`` under ``document_forms.report`` (strings plus
  the ``field_labels`` and ``section_titles`` tables), read through
  :mod:`app.core.document_forms_i18n`, like every other printed form.
* **Shared resolution**, from :mod:`app.core.document_locale`: an explicit
  ``?locale=`` query parameter wins, otherwise the first ``Accept-Language``
  tag whose primary subtag this table has, otherwise English. The
  middleware's context locale is deliberately not reused, so a report's
  language depends only on what this table can actually render.
* **English is byte-for-byte what the module shipped before.** Every English
  value here is the literal it replaced, including the two that read wrong
  (``Open Rfis``, ``Cpi``): fixing those is a change to the English document
  and belongs in its own commit, not hidden inside a localization one.

Because this table is narrower than the interface's locale list, a reader can
ask for a language it does not hold. The routes serving a report therefore
declare the language they actually rendered in ``Content-Language`` - see
:mod:`app.core.document_locale`.

Adding a language is translating the block in its locale file; no code changes.
"""

from __future__ import annotations

from typing import Any

from app.core.document_forms_i18n import REGISTER_UNRENDERABLE, form_labels, form_strings
from app.core.document_locale import (
    normalize_document_locale,
    resolve_document_locale,
    translate,
)

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

# ── Report chrome ─────────────────────────────────────────────────────────
#
# Everything the renderer and the exporters emit that is not a section title
# or a field label: the header metadata line, the table column headers, the
# empty-snapshot notice, the footer, the AI-narrative block.

_STRINGS: dict[str, dict[str, str]] = form_strings("report")
# Languages a generated report can be rendered in: every language whose locale
# file translates part of the ``document_forms.report`` block, less the ones the
# PDF layer cannot draw.
SUPPORTED_REPORT_LOCALES: tuple[str, ...] = tuple(code for code in _STRINGS if code not in REGISTER_UNRENDERABLE)

# ── Section titles ────────────────────────────────────────────────────────
#
# Keyed by the English title rather than by the section id, because the id
# alone does not determine the heading: ``kpi`` is "Key Performance
# Indicators" in a project-status report and "Safety KPIs" in a safety one,
# and ``risk`` is "Risk Summary" in one and "Top Risks" in another.
#
# The English string is also the only thing available at render time for a
# report bound to a template, because ``SYSTEM_TEMPLATES`` seeds these exact
# headings into ``ReportTemplate.template_data`` as rows in the database.
# Looking them up by their own text localizes the seeded templates and the
# renderer's built-in defaults through one table, and it is what makes
# :func:`section_title` leave a user's own heading alone: a title that is not
# one of ours is not in this table and renders verbatim.

_SECTION_TITLES: dict[str, dict[str, str]] = form_labels("report", "section_titles")


# ── Field labels ──────────────────────────────────────────────────────────
#
# Keyed by the snapshot key, which is a stable token the service layer emits
# rather than prose. Only the keys ``ReportingService._build_default_snapshot``
# produces are listed: a caller-supplied snapshot may carry any keys at all,
# and those keep falling through to the Title-Cased fallback the renderer and
# the exporters already used.
#
# The English column reproduces that fallback exactly, ``Open Rfis`` and
# ``Cpi`` included. They read wrong, and correcting them changes the English
# document, which is a separate change from being able to write a German one.

_FIELD_LABELS: dict[str, dict[str, str]] = form_labels("report", "field_labels")


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
    return translate(_STRINGS, locale, key, DEFAULT_REPORT_LOCALE, **params)


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
    table = _SECTION_TITLES.get(locale) or _SECTION_TITLES[DEFAULT_REPORT_LOCALE]
    return table.get(title) or _SECTION_TITLES[DEFAULT_REPORT_LOCALE].get(title) or title


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
    table = _FIELD_LABELS.get(locale) or _FIELD_LABELS[DEFAULT_REPORT_LOCALE]
    return table.get(text) or _FIELD_LABELS[DEFAULT_REPORT_LOCALE].get(text) or text.replace("_", " ").title()
