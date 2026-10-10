# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Notification text in the language of the person it is written for.

A notification row stores a key and its params, never a sentence, so the same
row can be read in any language. Two places turn that into text on the server:

* the subject and body of the e-mail, rendered once at send time for its
  recipient (the frame around them is ``email_render``'s), and
* the ``title_default`` / ``body_default`` the API hands the bell as a fallback
  for a locale file that lacks the key, rendered at read time for the reader.

Both go through :func:`render`. English is ``templates._TEMPLATES``, the
existing source of truth; Turkish is ``templates_tr.TEMPLATES_TR``, held to the
same keys and placeholders by a test. Every other locale answers in English,
and says so in the log once per locale rather than on every message.

Dates are params too. :func:`localize_context` rewrites ``due_date_display``
from ``due_date_iso`` in the format the person uses, so a date stored for a
Turkish recipient is not read back as written when the reader's settings
differ.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from app.core.regional_format import format_date
from app.modules.notifications.templates import english_template
from app.modules.notifications.templates import render as render_english
from app.modules.notifications.templates_tr import TEMPLATES_TR

logger = logging.getLogger(__name__)

DEFAULT_LOCALE = "en"

#: Locales with a notification catalogue of their own. Anything else falls
#: back to English through :func:`catalogue_locale`.
CATALOGUE_LOCALES: tuple[str, ...] = ("en", "tr")

_CATALOGUES: dict[str, dict[str, str]] = {"tr": TEMPLATES_TR}

#: Date order a language writes when the person has not picked one. English is
#: ISO because "10/04/2026" is April in one English-speaking country and
#: October in another, and a deadline is the wrong place to guess.
_LOCALE_DATE_PATTERN: dict[str, str] = {"en": "YYYY-MM-DD", "tr": "DD.MM.YYYY"}

#: ``User.date_format`` values that mean "never chose". ``DD.MM.YYYY`` is the
#: column's old default, and the frontend store reads it the same way.
_UNCHOSEN_DATE_FORMATS = frozenset({"", "auto", "DD.MM.YYYY"})

# Locales and keys already reported as falling back, so the log carries one
# line per gap and not one per message.
_FALLBACK_LOGGED: set[str] = set()


def base_locale(locale: str | None) -> str:
    """The base language of a locale tag, lower-cased; English when empty.

    ``tr-TR`` and ``TR_tr`` are both ``tr``.
    """
    if not locale:
        return DEFAULT_LOCALE
    return locale.strip().lower().replace("_", "-").split("-", 1)[0] or DEFAULT_LOCALE


def catalogue_locale(locale: str | None) -> str:
    """The catalogue that answers for ``locale``.

    A language without a notification catalogue is answered in English, and
    the first time that happens for a language it is logged by name.
    """
    base = base_locale(locale)
    if base in CATALOGUE_LOCALES:
        return base
    if base not in _FALLBACK_LOGGED:
        _FALLBACK_LOGGED.add(base)
        logger.info(
            "notifications: no message catalogue for locale %r, its notifications are written in English",
            base,
        )
    return DEFAULT_LOCALE


def render(key: str | None, context: dict[str, Any] | None = None, locale: str | None = None) -> str:
    """The text of a notification key in ``locale``, placeholders filled.

    Same contract as ``templates.render``: never raises, an unknown key comes
    back as the key, a missing placeholder leaves the template unfilled. A key
    the chosen catalogue lacks is answered from English and logged once.
    """
    if not key:
        return ""
    chosen = catalogue_locale(locale)
    if chosen == DEFAULT_LOCALE:
        return render_english(key, context)
    template = _CATALOGUES[chosen].get(key)
    if template is None:
        if english_template(key) is not None:
            marker = f"{chosen}:{key}"
            if marker not in _FALLBACK_LOGGED:
                _FALLBACK_LOGGED.add(marker)
                logger.warning(
                    "notifications: key %r has no %r text, written in English",
                    key,
                    chosen,
                )
        return render_english(key, context)
    if not context:
        return template
    try:
        return template.format(**context)
    except (KeyError, IndexError, ValueError) as exc:
        logger.debug("notifications.localized: interpolation failed for key=%r: %s", key, exc)
        return template


def date_pattern(locale: str | None, date_format: str | None = None) -> str:
    """The date order to write for a person.

    Their own choice wins. ``auto`` and the column's old default both mean
    nobody chose, and then the language decides.

    Args:
        locale: The person's interface language (``User.locale``).
        date_format: ``User.date_format``.

    Returns:
        A pattern in ``DD`` / ``MM`` / ``YYYY`` tokens.
    """
    chosen = (date_format or "").strip()
    if chosen not in _UNCHOSEN_DATE_FORMATS and all(token in chosen for token in ("DD", "MM", "YYYY")):
        return chosen
    return _LOCALE_DATE_PATTERN[catalogue_locale(locale)]


def _parse_day(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


def format_day(value: Any, locale: str | None, date_format: str | None = None) -> str:
    """A stored date written for one person, e.g. ``10.10.2026`` in Turkish.

    A value that is not a date comes back as stored, and an empty one as an
    empty string, so a malformed row still renders.
    """
    day = _parse_day(value)
    if day is None:
        return str(value or "")
    return format_date(day, pattern=date_pattern(locale, date_format))


def localize_context(
    context: dict[str, Any] | None,
    locale: str | None,
    date_format: str | None = None,
) -> dict[str, Any]:
    """A copy of the params with the display date written for this person.

    Only ``due_date_display`` is touched, and only when the canonical
    ``due_date_iso`` travels with it. Every other param is language neutral
    by construction.
    """
    localized = dict(context or {})
    iso = localized.get("due_date_iso")
    if iso:
        localized["due_date_display"] = format_day(iso, locale, date_format)
    return localized


__all__ = [
    "CATALOGUE_LOCALES",
    "DEFAULT_LOCALE",
    "base_locale",
    "catalogue_locale",
    "date_pattern",
    "format_day",
    "localize_context",
    "render",
]
