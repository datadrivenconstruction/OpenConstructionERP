# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Locale resolution for generated documents.

A document is not an API response. The API can answer in any of the
locales listed in :data:`app.core.i18n.SUPPORTED_LOCALES`, because those
strings live in locale files that are complete by construction. A PDF is
rendered from a string catalogue that ships inside its own module and
covers far fewer languages. The two numbers are different, and the gap
between them is where a reader ends up holding an English invoice after
setting the interface to their own language.

This module holds the resolution the document renderers share, so the
rule lives in one place instead of being copied per module:

  1. ``?locale=de`` query parameter (region stripped) when the catalogue
     has it.
  2. The first ``Accept-Language`` tag, in header order, whose primary
     subtag the catalogue has. Quality weights are ignored on purpose -
     a single best match is enough, and header order is the browser's
     preference order in practice.
  3. The catalogue's default language.

**Primary subtags only.** Every caller reduces ``fr-CA`` to ``fr`` before
matching, so a document catalogue cannot today distinguish Canadian from
European French, nor Brazilian from European Portuguese, however many
strings it holds. Regional document variants are a schema change here and
in every catalogue, not a translation job.

**Falling back is not free.** :func:`resolve_document_locale` returning
the default means the reader asked for something we could not render.
Callers serving that document MUST declare the language they actually
produced in a ``Content-Language`` response header, so the degradation is
visible to the client instead of being hidden behind a request-derived
header that names a language the body is not written in.
"""

from __future__ import annotations

from collections.abc import Container, Mapping
from typing import Any

__all__ = [
    "normalize_document_locale",
    "resolve_document_locale",
    "translate",
]


def normalize_document_locale(
    value: str | None,
    supported: Container[str],
    default: str,
) -> str:
    """Reduce a locale-ish value to a primary subtag the catalogue has.

    Args:
        value: A locale code such as ``"de"``, ``"de-DE"`` or ``"DE"``.
            ``None`` and unsupported values normalise to *default*.
        supported: The catalogue's language codes.
        default: The catalogue's fallback language.

    Returns:
        A member of *supported*.
    """
    if not value:
        return default
    primary = value.strip().lower().split("-")[0]
    return primary if primary in supported else default


def resolve_document_locale(
    locale_param: str | None,
    accept_language: str | None,
    supported: Container[str],
    default: str,
) -> str:
    """Pick the document language for an HTTP request.

    Args:
        locale_param: Explicit ``?locale=`` query value, if any.
        accept_language: Raw ``Accept-Language`` header value, if any.
        supported: The catalogue's language codes.
        default: The catalogue's fallback language.

    Returns:
        A member of *supported*. When the return value is *default* but
        the caller asked for something else, the document is a fallback
        and the route must say so in ``Content-Language``.
    """
    if locale_param:
        primary = locale_param.strip().lower().split("-")[0]
        if primary in supported:
            return primary
    if accept_language:
        for raw_tag in accept_language.split(","):
            primary = raw_tag.split(";", 1)[0].strip().lower().split("-")[0]
            if primary in supported:
                return primary
    return default


def translate(
    tables: Mapping[str, Mapping[str, str]],
    locale: str,
    key: str,
    default: str,
    **params: Any,
) -> str:
    """Resolve ``key`` for ``locale`` with a fallback chain.

    Requested locale -> *default* -> the key itself. Returning the key is
    a bug in the catalogue, but it is never a crash in a document render.

    Args:
        tables: Catalogue keyed by language, then by string key.
        locale: A document locale code; unknown codes read the default table.
        key: Catalogue key, e.g. ``"net_total"``.
        default: The catalogue's fallback language.
        **params: ``str.format`` interpolation values.

    Returns:
        The resolved, formatted string.
    """
    table = tables.get(locale) or tables[default]
    template = table.get(key) or tables[default].get(key) or key
    if not params:
        return template
    try:
        return template.format(**params)
    except (IndexError, KeyError, ValueError):
        return template
