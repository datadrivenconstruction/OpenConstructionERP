# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""String catalog and locale resolution for the hybrid e-invoice PDF page.

The readable half of a Factur-X / ZUGFeRD hybrid used to be hardcoded English
with ISO dates and decimal points, wrapped around German line texts and party
names. The embedded CII XML is untouched by any of this - its dates and
decimal points are prescribed by the standard and read by machines - but the
page exists precisely for the human who still opens invoices by eye, and that
human reads it in their own conventions.

* **The platform catalogue** - labels live in ``backend/locales/<code>.json``
  under ``einvoice.pdf.*``; a key a language lacks reads in English.
* **Shared resolution** from :mod:`app.core.document_locale` - an explicit
  ``?locale=`` query parameter wins, otherwise the first ``Accept-Language``
  tag whose primary subtag this table has, otherwise ``"en"``.

This module once carried its own copy of that resolution, taken from
``daily_diary.pdf_translations``. Both copies were byte-identical, so a fix
to either reached only one invoice. The rule now lives in one place and the
strings stay here.

English label text is byte-for-byte the pre-i18n page; English numbers gain
thousands grouping (1,240,000.00) and quantities now round to the same four
decimals the embedded XML carries, so page and document can no longer state
two different figures.

The route serving the PDF declares the language it resolved in
``Content-Language``.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.core.document_locale import normalize_document_locale, resolve_document_locale
from app.core.i18n import SUPPORTED_LOCALES, t
from app.core.regional_format import (
    date_format_for_language,
    format_date,
    format_number,
    number_style_for_language,
)
from app.modules.einvoice.rules import money_decimals

__all__ = [
    "DEFAULT_PDF_LOCALE",
    "SUPPORTED_PDF_LOCALES",
    "fmt_date",
    "fmt_money",
    "fmt_number",
    "normalize_pdf_locale",
    "resolve_pdf_locale",
    "tr",
]

DEFAULT_PDF_LOCALE = "en"

#: Languages the invoice page can render: every interface language. Labels
#: come from ``einvoice.pdf.*`` in ``backend/locales``; separators and date
#: order from :mod:`app.core.regional_format`.
SUPPORTED_PDF_LOCALES: tuple[str, ...] = tuple(SUPPORTED_LOCALES)

# ── Locale resolution ────────────────────────────────────────────────────


def normalize_pdf_locale(value: str | None) -> str:
    """Reduce a locale-ish value to a supported primary subtag.

    Args:
        value: A locale code such as ``"de"``, ``"de-DE"`` or ``"DE"``.
            ``None`` and unsupported values normalise to ``"en"``.

    Returns:
        A member of :data:`SUPPORTED_PDF_LOCALES`.
    """
    return normalize_document_locale(value, SUPPORTED_PDF_LOCALES, DEFAULT_PDF_LOCALE)


def resolve_pdf_locale(locale_param: str | None, accept_language: str | None) -> str:
    """Pick the page language for an HTTP request.

    See :func:`app.core.document_locale.resolve_document_locale` for the
    rule. When this returns ``"en"`` for a reader who asked for something
    else, the route must declare ``Content-Language: en`` so the fallback
    is visible rather than silent.

    Args:
        locale_param: Explicit ``?locale=`` query value, if any.
        accept_language: Raw ``Accept-Language`` header value, if any.

    Returns:
        A member of :data:`SUPPORTED_PDF_LOCALES`.
    """
    return resolve_document_locale(locale_param, accept_language, SUPPORTED_PDF_LOCALES, DEFAULT_PDF_LOCALE)


# ── Catalog lookup ───────────────────────────────────────────────────────


def tr(locale: str, key: str, **params: Any) -> str:
    """Resolve ``key`` for ``locale`` with English fallback.

    Same fallback chain as the daily-diary bundle: requested locale ->
    ``en`` -> the key itself (a bug, but never a crash).

    Args:
        locale: A PDF locale code; unknown codes read the English table.
        key: Catalog key, e.g. ``"net_total"``.
        **params: ``str.format`` interpolation values.

    Returns:
        The resolved, formatted string.
    """
    return t(f"einvoice.pdf.{key}", locale, **params)


# ── Value formatting ─────────────────────────────────────────────────────


def fmt_money(value: Decimal, currency: str, locale: str) -> str:
    """A document amount with thousands grouping in the locale's separators.

    ``Decimal("1240000")`` renders as ``1,240,000.00`` in English and
    ``1.240.000,00`` in German. The currency decides the decimal places,
    exactly as the XML's ``_money`` does, so page and document agree on
    every figure.

    Args:
        value: The amount.
        currency: ISO 4217 code deciding the decimal places.
        locale: A supported PDF locale.

    Returns:
        The formatted amount, without a currency symbol.
    """
    places = money_decimals(currency)
    return format_number(value, places, number_style_for_language(locale))


def fmt_number(value: Decimal, locale: str) -> str:
    """A quantity or unit price: up to four decimals, trailing zeros trimmed.

    Args:
        value: The number.
        locale: A supported PDF locale.

    Returns:
        The formatted number in the locale's separators, without grouping -
        quantities read as counts, not as money.
    """
    q = value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP).normalize()
    # normalize() can yield exponent form for integers (e.g. 5E+1); expand it.
    text = f"{q:f}"
    places = len(text.partition(".")[2])
    style = replace(number_style_for_language(locale), group="")
    return format_number(q, places, style)


def fmt_date(iso: str, locale: str) -> str:
    """Render an ISO ``YYYY-MM-DD`` string in the locale's date format.

    The English format is ISO itself, so English output is unchanged.
    Non-ISO input is returned as-is - the renderer must never crash on a
    malformed stored date; the validation rules report those separately.

    Args:
        iso: The stored date string.
        locale: A supported PDF locale.

    Returns:
        The formatted date, or ``iso`` unchanged when unparseable.
    """
    try:
        parsed = date.fromisoformat((iso or "").strip()[:10])
    except ValueError:
        return iso
    return format_date(parsed, None, date_format_for_language(locale))
