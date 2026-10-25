# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""String catalog and locale resolution for the daily-diary PDF export.

The diary PDF used to be hardcoded English and printed the raw
``weather_summary`` dictionary keys (``temp_c: 20 · conditions: clear``).
This module gives the renderer its catalogue - English (source of truth) and
every other language of ``backend/locales/<code>.json`` under
``document_forms.daily_diary`` - and the small helpers the router and the
renderer need to pick and apply a locale.

The Turkish document is titled "Şantiye Günlük Raporu", the name Turkish
contractors print on this form. It is deliberately not "Şantiye Defteri":
that is the statutory site book a site chief keeps under the Turkish
regulation on site chiefs, and a report printed from here is not that book.
The other Turkish labels follow the diary screen (``daily_diary.*`` in the
Turkish interface locale) so the page says what the screen says.

* **Locale files**, like the other printed forms: the strings are built into a
  catalogue by :mod:`app.core.document_forms_i18n`.
* **Shared resolution**, from :mod:`app.core.document_locale`: an explicit
  ``?locale=`` query parameter wins, otherwise the first
  ``Accept-Language`` tag whose primary subtag this table has, otherwise
  ``"en"``. The middleware's context locale is deliberately not reused
  here, so the PDF language depends only on what this table can render.

The strings are local; the rule that picks between them is not. It used to
be, copied verbatim into the e-invoice bundle, which is how the two drifted
into being separately maintained copies of the same three functions.

Because this table is narrower than the interface's locale list, a reader
can ask for a language it does not hold. The route serving the PDF must
then declare the language it actually rendered in ``Content-Language`` -
see :mod:`app.core.document_locale`.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.core import register_export
from app.core.document_forms_i18n import register_form_catalogue

__all__ = [
    "CATALOGUE",
    "DEFAULT_PDF_LOCALE",
    "SUPPORTED_PDF_LOCALES",
    "diary_pdf_filename",
    "entry_type_label",
    "fmt_number",
    "format_iso_date",
    "normalize_pdf_locale",
    "resolve_pdf_locale",
    "status_caps",
    "status_label",
    "tr",
    "weather_source_label",
    "weather_summary_text",
]

DEFAULT_PDF_LOCALE = "en"

#: Strings and code tables come from ``backend/locales/<code>.json`` under
#: ``document_forms.daily_diary``; English is the fallback for any gap. The
#: weather condition, entry type, status and source words are the diary's own
#: code tables inside that block.
CATALOGUE = register_form_catalogue("daily_diary")

#: Languages the diary PDF can render; anything else is English.
SUPPORTED_PDF_LOCALES: tuple[str, ...] = CATALOGUE.supported

# ── Locale resolution ────────────────────────────────────────────────────


def normalize_pdf_locale(value: str | None) -> str:
    """Reduce a locale-ish value to a supported primary subtag.

    Args:
        value: A locale code such as ``"de"``, ``"de-DE"`` or ``"DE"``.
            ``None`` and unsupported values normalise to ``"en"``.

    Returns:
        A member of :data:`SUPPORTED_PDF_LOCALES`.
    """
    return CATALOGUE.normalize(value)


def resolve_pdf_locale(locale_param: str | None, accept_language: str | None) -> str:
    """Pick the PDF language for an HTTP request.

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
    return CATALOGUE.resolve(locale_param, accept_language)


# ── Catalog lookups ──────────────────────────────────────────────────────


def tr(locale: str, key: str, **params: Any) -> str:
    """Resolve ``key`` for ``locale`` with English fallback.

    Same fallback chain as the validation-messages bundle: requested
    locale -> ``en`` -> the key itself (a bug, but never a crash).

    Args:
        locale: A PDF locale code; unknown codes read the English table.
        key: Catalog key, e.g. ``"overview"``.
        **params: ``str.format`` interpolation values.

    Returns:
        The resolved, formatted string.
    """
    return CATALOGUE.tr(locale, key, **params)


def entry_type_label(entry_type: str, locale: str) -> str:
    """Section label for a diary entry type, never a raw snake_case token."""
    table = CATALOGUE.labels["entry_type"]
    label = table[normalize_pdf_locale(locale)].get(entry_type) or table[DEFAULT_PDF_LOCALE].get(entry_type)
    return label or entry_type.replace("_", " ").title()


def weather_source_label(source: str | None, locale: str) -> str:
    """The word for a stored weather source; an unknown source prints as stored, none as a dash."""
    code = (source or "").strip()
    if not code:
        return "-"
    table = CATALOGUE.labels["source"]
    return table[normalize_pdf_locale(locale)].get(code.lower()) or table[DEFAULT_PDF_LOCALE].get(code.lower()) or code


def status_label(status: str | None, locale: str) -> str:
    """Status chip label; unknown statuses pass through as stored."""
    normalized = (status or "open").strip().lower()
    table = CATALOGUE.labels["status"]
    label = table[normalize_pdf_locale(locale)].get(normalized) or table[DEFAULT_PDF_LOCALE].get(normalized)
    return label or (status or "open")


def status_caps(label: str, locale: str) -> str:
    """Upper-case the status chip the way the language writes capitals.

    ``str.upper`` printed the Turkish "İmzalandı" correctly only by luck and
    would print "Arşivlendi" as "ARŞIVLENDI", without the dot Turkish keeps
    on a capital i.
    """
    return register_export.caps(label, locale)


def diary_pdf_filename(stem: str, locale: str) -> str:
    """Download filename for a diary export, e.g. ``bautagebuch-2026-04-10.pdf``."""
    return f"{tr(normalize_pdf_locale(locale), 'filename_prefix')}-{stem}.pdf"


# ── Value formatting ─────────────────────────────────────────────────────


def fmt_number(value: Any, decimals: int = 1, locale: str | None = None, *, decimal_mark: str | None = None) -> str:
    """Format a numeric value (int / float / Decimal) for display.

    Args:
        value: The value to format. ``None`` renders as a dash.
        decimals: Number of decimal places to keep.
        locale: Document language, for the decimal mark (German and Turkish
            write ``12,5``). ``None`` keeps the full stop.
        decimal_mark: The mark of the project's market, when the caller
            knows the project's country. It wins over the language's, so an
            English report of a project in Türkiye writes ``12,5`` like the
            registers of the same project do.

    Returns:
        A formatted string, or ``"-"`` when the value is missing or not
        numeric.
    """
    if value is None:
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    if number == int(number):
        return str(int(number))
    text = f"{number:.{decimals}f}"
    if decimal_mark:
        return text.replace(".", decimal_mark)
    return text.replace(".", tr(locale, "decimal_mark")) if locale else text


def format_iso_date(value: str, locale: str, date_format: str | None = None) -> str:
    """Render an ISO ``YYYY-MM-DD`` string in the locale's date format.

    ``date_format`` (a ``strftime`` pattern) overrides the language's own
    when the caller knows the project's country.

    The English format is ISO itself, so English output is unchanged.
    Non-ISO input is returned as-is - the diary stores dates as ISO
    strings, but the renderer must never crash on a malformed row.

    Args:
        value: The stored date string.
        locale: A supported PDF locale.

    Returns:
        The formatted date, or ``value`` unchanged when unparseable.
    """
    try:
        parsed = date.fromisoformat((value or "").strip())
    except ValueError:
        return value
    return parsed.strftime(date_format or tr(locale, "date_format"))


# ── Weather summary ──────────────────────────────────────────────────────

_TEMP_KEYS = ("temp_c", "temperature_c")
_CONDITION_KEYS = ("conditions", "condition")
_WIND_KEYS = ("wind_kmh", "wind_speed_kmh")
_PRECIP_KEYS = ("precipitation_mm", "precip_mm")
_HUMIDITY_KEYS = ("humidity_pct", "humidity")


def _first_present(summary: dict[str, Any], keys: tuple[str, ...]) -> Any:
    """Return the first non-empty value among ``keys``, else ``None``."""
    for key in keys:
        value = summary.get(key)
        if value is not None and str(value).strip() != "":
            return value
    return None


def weather_summary_text(summary: dict[str, Any], locale: str) -> str:
    """Render a ``weather_summary`` snapshot as a human sentence fragment.

    ``{"temp_c": 20, "conditions": "clear"}`` becomes ``"20 °C, clear"``
    (``"20 °C, klar"`` in German). Known keys render in a fixed order;
    anything else is appended as a humanised ``label: value`` pair, so a
    raw ``snake_case`` key never reaches the document.

    Args:
        summary: The diary's ``weather_summary`` JSON snapshot.
        locale: A supported PDF locale.

    Returns:
        The joined fragment, or ``""`` when nothing is renderable.
    """
    parts: list[str] = []
    consumed: set[str] = set()

    temp = _first_present(summary, _TEMP_KEYS)
    if temp is not None:
        text = fmt_number(temp, locale=locale)
        if text != "-":
            parts.append(f"{text} °C")
            consumed.update(_TEMP_KEYS)

    condition = _first_present(summary, _CONDITION_KEYS)
    if condition is not None:
        code = str(condition).strip()
        table = CATALOGUE.labels["condition"]
        label = table[normalize_pdf_locale(locale)].get(code.lower()) or table[DEFAULT_PDF_LOCALE].get(code.lower())
        # Free-text conditions ("Partly cloudy, mild") pass through as
        # written; coded ones only lose their underscores.
        parts.append(label or code.replace("_", " "))
        consumed.update(_CONDITION_KEYS)

    for keys, template_key in (
        (_WIND_KEYS, "summary_wind"),
        (_PRECIP_KEYS, "summary_precipitation"),
        (_HUMIDITY_KEYS, "summary_humidity"),
    ):
        value = _first_present(summary, keys)
        if value is not None:
            text = fmt_number(value, locale=locale)
            if text != "-":
                parts.append(tr(locale, template_key, value=text))
                consumed.update(keys)

    for key, value in summary.items():
        if key in consumed or value is None or str(value).strip() == "":
            continue
        label = str(key).replace("_", " ").strip()
        parts.append(f"{label}: {value}")

    return ", ".join(parts)
