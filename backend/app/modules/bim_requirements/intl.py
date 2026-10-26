# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""International, database-free helpers for BIM requirement reporting.

This module is purely additive and has no framework or database dependency.
It provides small, deterministic helper functions that summarize how well a
BIM model meets its requirements (LOD/LOI, EIR deliverables) in a way that is
clear to construction professionals worldwide.

Design goals:
    * International by default. No hardcoded locale, dates rendered as ISO 8601.
    * Plain language. Every figure has a one-line explainer and exposes the
      exact components it was derived from.
    * Safe edge cases. Division by zero, empty sets and negative counts never
      raise a 500 and never return NaN or infinity. Rates stay inside [0, 1]
      (or [0, 100] for percentages) or a clean ``ValueError`` is raised.

Status vocabulary matches the compliance check in ``service.py``:
    * ``pass``            -> the requirement is met
    * ``fail``            -> the requirement is not met
    * ``not_applicable``  -> no model element matched the requirement filter

Terminology (open standards, ISO 19650):
    * LOD -- Level of Development / Detail. How complete a model element is.
    * LOI -- Level of Information. How much data an element carries.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime

from app.core.i18n import catalogue_table

# -- Status vocabulary ------------------------------------------------------

STATUS_MET = "pass"
STATUS_UNMET = "fail"
STATUS_NOT_APPLICABLE = "not_applicable"

#: All requirement-check status codes, in report order.
VALID_STATUSES: tuple[str, ...] = (STATUS_MET, STATUS_UNMET, STATUS_NOT_APPLICABLE)

# -- LOD levels -------------------------------------------------------------

#: Level of Development steps in common BIM practice (100..500).
VALID_LOD_LEVELS: tuple[int, ...] = (100, 200, 300, 350, 400, 500)

_LOD_MIN = VALID_LOD_LEVELS[0]
_LOD_MAX = VALID_LOD_LEVELS[-1]

# -- Localized status words (en / de / ru, English fallback) ----------------

_DEFAULT_LOCALE = "en"

_STATUS_WORDS: dict[str, dict[str, str]] = catalogue_table(
    "bim_requirements.intl.status_words", ("pass", "fail", "not_applicable")
)

# One-line, plain-language explainers keyed by term, then locale.
_EXPLAINERS: dict[str, dict[str, str]] = {
    "lod": {
        "en": "LOD (Level of Development) says how complete a model element is, from 100 (concept) to 500 (as built).",
        "de": "LOD (Level of Development) zeigt, wie vollstaendig ein Modellelement ist, von 100 (Konzept) bis 500 (wie gebaut).",
        "ru": "LOD (uroven prorabotki) pokazyvaet, naskolko polon element modeli, ot 100 (koncepciya) do 500 (kak postroeno).",
    },
    "loi": {
        "en": "LOI (Level of Information) says how much data an element carries, such as material, fire rating or cost code.",
        "de": "LOI (Level of Information) zeigt, wie viele Daten ein Element traegt, etwa Material, Feuerwiderstand oder Kostencode.",
        "ru": "LOI (uroven informacii) pokazyvaet, skolko dannyh neset element, naprimer material, ognestoykost ili kod stoimosti.",
    },
    "met": {
        "en": "A requirement is met when every matched element satisfies its constraint.",
        "de": "Eine Anforderung ist erfuellt, wenn jedes passende Element seine Vorgabe erfuellt.",
        "ru": "Trebovanie vypolneno, kogda kazhdyy podhodyashchiy element sootvetstvuet svoemu ogranicheniyu.",
    },
    "unmet": {
        "en": "A requirement is unmet when at least one matched element fails its constraint.",
        "de": "Eine Anforderung ist nicht erfuellt, wenn mindestens ein passendes Element seine Vorgabe verletzt.",
        "ru": "Trebovanie ne vypolneno, kogda hotya by odin podhodyashchiy element narushaet svoe ogranichenie.",
    },
    "coverage": {
        "en": "Coverage is the share of applicable requirements that are met, from 0 to 100 percent.",
        "de": "Abdeckung ist der Anteil der zutreffenden Anforderungen, die erfuellt sind, von 0 bis 100 Prozent.",
        "ru": "Pokrytie -- eto dolya primenimyh trebovaniy, kotorye vypolneny, ot 0 do 100 procentov.",
    },
}


def normalize_locale(locale: str | None) -> str:
    """Reduce a locale tag to a supported two-letter code, English fallback.

    Accepts tags like ``en``, ``en-US``, ``de_DE`` or ``ru``. Anything not
    supported falls back to English so output is never empty.

    Args:
        locale: A locale tag or ``None``.

    Returns:
        One of the supported locale codes (``en``, ``de``, ``ru``).
    """
    if not locale:
        return _DEFAULT_LOCALE
    base = locale.strip().lower().replace("_", "-").split("-", 1)[0]
    if base in _STATUS_WORDS:
        return base
    return _DEFAULT_LOCALE


def localize_status(status: str, locale: str | None = _DEFAULT_LOCALE) -> str:
    """Return a human word for a requirement status in the given locale.

    Args:
        status: One of :data:`VALID_STATUSES`.
        locale: Target locale tag. Unsupported locales fall back to English.

    Returns:
        A short, plain-language label such as ``"Met"``.

    Raises:
        ValueError: If ``status`` is not a known status code.
    """
    if status not in _STATUS_WORDS[_DEFAULT_LOCALE]:
        raise ValueError(f"Unknown requirement status: {status!r}")
    loc = normalize_locale(locale)
    words = _STATUS_WORDS.get(loc, _STATUS_WORDS[_DEFAULT_LOCALE])
    return words.get(status) or _STATUS_WORDS[_DEFAULT_LOCALE][status]


def explain(term: str, locale: str | None = _DEFAULT_LOCALE) -> str:
    """Return a one-line, plain-language explainer for a reporting term.

    Args:
        term: One of ``lod``, ``loi``, ``met``, ``unmet``, ``coverage``
            (case-insensitive).
        locale: Target locale tag. Unsupported locales fall back to English.

    Returns:
        A single sentence explaining the term.

    Raises:
        ValueError: If ``term`` is not a known explainer key.
    """
    key = term.strip().lower()
    if key not in _EXPLAINERS:
        raise ValueError(f"No explainer for term: {term!r}")
    loc = normalize_locale(locale)
    variants = _EXPLAINERS[key]
    return variants.get(loc) or variants[_DEFAULT_LOCALE]


# -- LOD parsing / validation -----------------------------------------------


def parse_lod_level(raw: object) -> int:
    """Parse a Level of Development value into a validated integer level.

    Accepts common written forms such as ``300``, ``"300"``, ``"LOD300"``,
    ``"LOD 300"``, ``"lod_350"`` or ``"LOD-400"``. The extracted number must be
    one of :data:`VALID_LOD_LEVELS`.

    Args:
        raw: The value to parse (integer or string).

    Returns:
        The LOD level as an integer, for example ``300``.

    Raises:
        ValueError: If the value is empty, has no digits, or is not a
            recognized LOD level.
    """
    if isinstance(raw, bool):
        # bool is a subclass of int; reject it explicitly to avoid surprises.
        raise ValueError("LOD level must be a number or string, not a boolean")
    if isinstance(raw, int):
        level = raw
    else:
        text = str(raw).strip()
        if not text:
            raise ValueError("LOD level is empty")
        digits = "".join(ch for ch in text if ch.isdigit())
        if not digits:
            raise ValueError(f"No LOD number found in {raw!r}")
        level = int(digits)
    if level not in VALID_LOD_LEVELS:
        allowed = ", ".join(str(x) for x in VALID_LOD_LEVELS)
        raise ValueError(f"LOD level {level} is not one of: {allowed}")
    return level


def is_valid_lod_level(raw: object) -> bool:
    """Return ``True`` if ``raw`` parses to a valid LOD level, else ``False``.

    Never raises. A convenience wrapper around :func:`parse_lod_level`.

    Args:
        raw: The value to test.

    Returns:
        Whether the value is a recognized LOD level.
    """
    try:
        parse_lod_level(raw)
    except ValueError:
        return False
    return True


# -- Coverage math (zero-guarded, bounded) ----------------------------------


def _require_non_negative(**counts: int) -> None:
    """Raise ``ValueError`` if any named count is negative.

    Args:
        **counts: Named integer counts to check.

    Raises:
        ValueError: If any value is negative.
    """
    for name, value in counts.items():
        if value < 0:
            raise ValueError(f"{name} must not be negative, got {value}")


def coverage_rate(met: int, total: int) -> float:
    """Fraction of requirements met, always inside ``[0.0, 1.0]``.

    Zero guard: when ``total`` is 0 (no requirements) the rate is a
    well-defined ``0.0`` rather than a division error.

    Args:
        met: Count of met requirements.
        total: Count of requirements considered (met plus unmet).

    Returns:
        ``met / total`` clamped to ``[0.0, 1.0]``, or ``0.0`` when ``total`` is 0.

    Raises:
        ValueError: If ``met`` or ``total`` is negative, or ``met`` exceeds
            ``total``.
    """
    _require_non_negative(met=met, total=total)
    if met > total:
        raise ValueError(f"met ({met}) cannot exceed total ({total})")
    if total == 0:
        return 0.0
    rate = met / total
    # Guard against any floating point drift beyond the valid range.
    return min(1.0, max(0.0, rate))


def coverage_percent(met: int, total: int, ndigits: int = 1) -> float:
    """Percentage of requirements met, always inside ``[0.0, 100.0]``.

    Args:
        met: Count of met requirements.
        total: Count of requirements considered (met plus unmet).
        ndigits: Decimal places to round the percentage to.

    Returns:
        The coverage as a percentage rounded to ``ndigits``.

    Raises:
        ValueError: Propagated from :func:`coverage_rate`.
    """
    return round(coverage_rate(met, total) * 100.0, ndigits)


def counts_by_status(statuses: Iterable[str]) -> dict[str, int]:
    """Tally requirement statuses into a fixed, complete mapping.

    Every key in :data:`VALID_STATUSES` is present in the result even when its
    count is zero, so callers never have to guard for missing keys.

    Args:
        statuses: An iterable of status codes.

    Returns:
        A mapping ``{status: count}`` covering all valid statuses.

    Raises:
        ValueError: If any element is not a known status code.
    """
    tally = dict.fromkeys(VALID_STATUSES, 0)
    for status in statuses:
        if status not in tally:
            raise ValueError(f"Unknown requirement status: {status!r}")
        tally[status] += 1
    return tally


def met_vs_unmet_breakdown(
    statuses: Iterable[str],
    locale: str | None = _DEFAULT_LOCALE,
) -> dict[str, object]:
    """Summarize a list of requirement statuses into a clear, explainable report.

    Applicable requirements are those that are met or unmet. Requirements with
    no matching element (``not_applicable``) are reported separately and kept
    out of the coverage denominator, matching the compliance ratio used by the
    service layer.

    Args:
        statuses: An iterable of status codes (see :data:`VALID_STATUSES`).
        locale: Locale for the human-readable labels, English fallback.

    Returns:
        A mapping with these keys:
            * ``met`` / ``unmet`` / ``not_applicable`` -- integer counts.
            * ``total`` -- total requirements seen.
            * ``applicable`` -- met plus unmet (the coverage denominator).
            * ``coverage_rate`` -- ``met / applicable`` in ``[0, 1]``.
            * ``coverage_percent`` -- the same figure in ``[0, 100]``.
            * ``labels`` -- localized status words.
            * ``components`` -- how ``coverage_rate`` was derived.

    Raises:
        ValueError: If any status code is unknown.
    """
    tally = counts_by_status(statuses)
    met = tally[STATUS_MET]
    unmet = tally[STATUS_UNMET]
    not_applicable = tally[STATUS_NOT_APPLICABLE]
    applicable = met + unmet
    total = applicable + not_applicable
    rate = coverage_rate(met, applicable)
    return {
        "met": met,
        "unmet": unmet,
        "not_applicable": not_applicable,
        "total": total,
        "applicable": applicable,
        "coverage_rate": rate,
        "coverage_percent": round(rate * 100.0, 1),
        "labels": {
            STATUS_MET: localize_status(STATUS_MET, locale),
            STATUS_UNMET: localize_status(STATUS_UNMET, locale),
            STATUS_NOT_APPLICABLE: localize_status(STATUS_NOT_APPLICABLE, locale),
        },
        "components": {
            "numerator": met,
            "denominator": applicable,
            "formula": "met / (met + unmet)",
            "note": "not_applicable requirements are excluded from the denominator",
        },
    }


def summarize_check_results(
    results: Iterable[Mapping[str, object]],
    locale: str | None = _DEFAULT_LOCALE,
) -> dict[str, object]:
    """Build a breakdown from raw requirement-check result rows.

    Convenience wrapper that reads the ``status`` field of each result row (as
    produced by the compliance check) and delegates to
    :func:`met_vs_unmet_breakdown`.

    Args:
        results: An iterable of mappings, each with a ``status`` key.
        locale: Locale for the human-readable labels, English fallback.

    Returns:
        The same mapping as :func:`met_vs_unmet_breakdown`.

    Raises:
        ValueError: If a row lacks a ``status`` or carries an unknown one.
    """
    statuses: list[str] = []
    for row in results:
        if "status" not in row:
            raise ValueError("check result is missing a 'status' field")
        statuses.append(str(row["status"]))
    return met_vs_unmet_breakdown(statuses, locale)


# -- ISO 8601 dates ---------------------------------------------------------


def format_iso8601(value: date | datetime) -> str:
    """Render a date or datetime as an ISO 8601 string, locale-independent.

    Args:
        value: A ``date`` or ``datetime`` instance.

    Returns:
        The ISO 8601 representation, for example ``2026-07-05`` or
        ``2026-07-05T14:30:00``.

    Raises:
        ValueError: If ``value`` is not a ``date`` or ``datetime``.
    """
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    raise ValueError("value must be a date or datetime")
