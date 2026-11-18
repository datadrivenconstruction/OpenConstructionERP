# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""International, plain-language CRM pipeline helpers (pure, DB-free).

This module is strictly additive. It complements ``service.py`` with a small
set of pure functions that are safe to reuse anywhere - no database, no I/O,
no global state. The design goals are:

International by default
    Nothing here hardcodes a currency, a locale, or a minor-unit assumption.
    Money stays :class:`decimal.Decimal` and is never summed across different
    ISO currency codes (there is no FX table in scope, so blending currencies
    would be financially wrong). Money grouping is always per currency code.
    Probability is expressed as a plain ``0..1`` fraction (0 = no chance,
    1 = certain), independent of any percent convention. Dates are ISO 8601
    (``YYYY-MM-DD``).

Clarity
    Every figure has a one-line, plain-language explainer and every localized
    word (pipeline stage, deal status) has en / de / ru text with an English
    fallback so a site engineer or estimator understands the number in a
    minute.

Robust edge cases
    Division by zero, empty inputs, negative amounts, and probabilities
    outside ``0..1`` are all handled explicitly: either a clean
    :class:`ValueError` with a readable message, or a well-defined value.
    No function ever returns ``NaN`` / ``inf`` or raises an unexpected 500.

Explainability
    The report helpers return the derived figure together with the exact
    components it was built from, so a UI can show the working, not just the
    result.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

# ── Localized vocabulary (en / de / ru, English fallback) ──────────────────
#
# Keys are the canonical lower-case codes used across the CRM module. Unknown
# codes fall back to a humanized version of the code itself, so a custom,
# tenant-defined stage never renders as a blank or a raw slug.

_SUPPORTED_LOCALES: tuple[str, ...] = ("en", "de", "ru")
_FALLBACK_LOCALE = "en"

STAGE_LABELS: dict[str, dict[str, str]] = {
    "lead": {"en": "Lead", "de": "Lead", "ru": "Лид"},
    "qualification": {"en": "Qualification", "de": "Qualifizierung", "ru": "Квалификация"},
    "qualified": {"en": "Qualified", "de": "Qualifiziert", "ru": "Квалифицирован"},
    "bidding": {"en": "Bidding", "de": "Angebotsphase", "ru": "Торги"},
    "proposal": {"en": "Proposal", "de": "Angebot", "ru": "Предложение"},
    "negotiation": {"en": "Negotiation", "de": "Verhandlung", "ru": "Переговоры"},
    "won": {"en": "Won", "de": "Gewonnen", "ru": "Выиграно"},
    "lost": {"en": "Lost", "de": "Verloren", "ru": "Проиграно"},
}

STATUS_LABELS: dict[str, dict[str, str]] = {
    # Opportunity statuses.
    "open": {"en": "Open", "de": "Offen", "ru": "Открыто"},
    "won": {"en": "Won", "de": "Gewonnen", "ru": "Выиграно"},
    "lost": {"en": "Lost", "de": "Verloren", "ru": "Проиграно"},
    "abandoned": {"en": "Abandoned", "de": "Aufgegeben", "ru": "Отменено"},
    # Lead statuses.
    "new": {"en": "New", "de": "Neu", "ru": "Новый"},
    "qualifying": {"en": "Qualifying", "de": "In Qualifizierung", "ru": "Квалифицируется"},
    "disqualified": {"en": "Disqualified", "de": "Disqualifiziert", "ru": "Отклонён"},
    "converted": {"en": "Converted", "de": "Konvertiert", "ru": "Сконвертирован"},
}

# One-line explainers for each headline figure, in plain language.
METRIC_EXPLAINERS: dict[str, dict[str, str]] = {
    "pipeline_value": {
        "en": "Total value of all open deals, added up per currency (no currency mixing).",
        "de": "Gesamtwert aller offenen Deals, je Waehrung summiert (keine Waehrungsmischung).",
        "ru": "Суммарная стоимость всех открытых сделок, по каждой валюте отдельно.",
    },
    "weighted_value": {
        "en": "Expected value: each deal value multiplied by its win probability (0 to 1).",
        "de": "Erwartungswert: Deal-Wert multipliziert mit der Gewinnwahrscheinlichkeit (0 bis 1).",
        "ru": "Ожидаемая стоимость: стоимость сделки, умноженная на вероятность выигрыша (0..1).",
    },
    "win_rate": {
        "en": "Won deals divided by closed deals (won plus lost); 0 when nothing has closed.",
        "de": "Gewonnene Deals geteilt durch abgeschlossene Deals (gewonnen plus verloren).",
        "ru": "Выигранные сделки, делённые на закрытые (выигранные плюс проигранные).",
    },
    "stage": {
        "en": "The step a deal has reached in the sales pipeline, from Lead to Won or Lost.",
        "de": "Die Stufe eines Deals in der Vertriebspipeline, von Lead bis Gewonnen oder Verloren.",
        "ru": "Этап сделки в воронке продаж, от Лида до Выигрыша или Проигрыша.",
    },
}


def _normalize_locale(locale: str | None) -> str:
    """Return a supported locale code, defaulting to English.

    Args:
        locale: A locale code such as ``"de"`` or ``"de-DE"``; may be None.

    Returns:
        One of the supported locale codes, or the English fallback.
    """
    if not locale:
        return _FALLBACK_LOCALE
    base = str(locale).strip().lower().replace("_", "-").split("-", 1)[0]
    return base if base in _SUPPORTED_LOCALES else _FALLBACK_LOCALE


def _humanize_code(code: str) -> str:
    """Turn a raw code such as ``"cold_outreach"`` into ``"Cold Outreach"``."""
    cleaned = str(code).replace("_", " ").replace("-", " ").strip()
    return cleaned.title() if cleaned else ""


def _localize(table: dict[str, dict[str, str]], key: str, locale: str | None) -> str:
    """Look ``key`` up in a label table with locale then English fallback."""
    loc = _normalize_locale(locale)
    entry = table.get((key or "").strip().lower())
    if entry is None:
        return _humanize_code(key)
    return entry.get(loc) or entry.get(_FALLBACK_LOCALE) or _humanize_code(key)


def localize_stage(stage_code: str, locale: str | None = None) -> str:
    """Localize a pipeline stage code into a plain word.

    Args:
        stage_code: Canonical stage code (for example ``"proposal"``). Unknown
            or custom codes are humanized rather than dropped.
        locale: Target locale (en / de / ru); anything else falls back to en.

    Returns:
        A human-readable stage label. Never empty for a non-empty code.
    """
    return _localize(STAGE_LABELS, stage_code, locale)


def localize_status(status_code: str, locale: str | None = None) -> str:
    """Localize an opportunity or lead status code into a plain word.

    Args:
        status_code: Canonical status code (for example ``"open"``).
        locale: Target locale (en / de / ru); anything else falls back to en.

    Returns:
        A human-readable status label. Never empty for a non-empty code.
    """
    return _localize(STATUS_LABELS, status_code, locale)


def explain(metric: str, locale: str | None = None) -> str:
    """Return a one-line, plain-language explainer for a headline metric.

    Args:
        metric: One of ``"pipeline_value"``, ``"weighted_value"``,
            ``"win_rate"``, ``"stage"``.
        locale: Target locale (en / de / ru); anything else falls back to en.

    Returns:
        A single explanatory sentence, or an empty string for an unknown
        metric key (callers can safely render the empty string).
    """
    entry = METRIC_EXPLAINERS.get((metric or "").strip().lower())
    if entry is None:
        return ""
    loc = _normalize_locale(locale)
    return entry.get(loc) or entry.get(_FALLBACK_LOCALE) or ""


# ── Numeric coercion (Decimal-exact, no NaN / inf) ─────────────────────────


def coerce_money(value: Any, *, field: str = "value") -> Decimal:
    """Coerce an input into a non-negative, finite :class:`Decimal` amount.

    Money is kept at full Decimal precision (no minor-unit rounding is
    assumed, because that depends on the currency). Use
    :func:`quantize_money` when a currency's minor units are known.

    Args:
        value: A number-like input (Decimal, int, float, or numeric string).
            ``None`` is treated as ``0``.
        field: Name used in the error message for a bad input.

    Returns:
        The value as a finite, non-negative Decimal.

    Raises:
        ValueError: If the input is not a finite number or is negative.
    """
    if value is None:
        return Decimal(0)
    try:
        # Route floats through str so 0.1 does not become 0.1000000000000000055.
        amount = Decimal(str(value)) if isinstance(value, float) else Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} is not a valid number: {value!r}") from exc
    if not amount.is_finite():
        raise ValueError(f"{field} must be finite, got {value!r}")
    if amount < 0:
        raise ValueError(f"{field} must be zero or positive, got {amount}")
    return amount


def coerce_probability(value: Any) -> Decimal:
    """Coerce an input into a probability in the closed range ``0..1``.

    A probability outside ``0..1`` is clamped to the nearest bound (a
    well-defined result) rather than raising, so a slightly-off caller value
    never breaks a whole pipeline computation. Non-finite or non-numeric
    inputs are rejected.

    Args:
        value: A number-like input. ``None`` is treated as ``0``.

    Returns:
        A Decimal in the inclusive range ``[0, 1]``.

    Raises:
        ValueError: If the input is not a finite number.
    """
    if value is None:
        return Decimal(0)
    try:
        prob = Decimal(str(value)) if isinstance(value, float) else Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"probability is not a valid number: {value!r}") from exc
    if not prob.is_finite():
        raise ValueError(f"probability must be finite, got {value!r}")
    if prob < 0:
        return Decimal(0)
    if prob > 1:
        return Decimal(1)
    return prob


def quantize_money(amount: Decimal, minor_units: int = 2) -> Decimal:
    """Round a Decimal amount to a currency's minor units (banker-free).

    Args:
        amount: A finite Decimal amount.
        minor_units: Number of fractional digits for the currency (for
            example 2 for USD/EUR, 0 for JPY, 3 for BHD). Defaults to 2 only
            because most currencies use it; callers that know the currency
            should pass its real value.

    Returns:
        The amount rounded half-up to ``minor_units`` places.

    Raises:
        ValueError: If ``minor_units`` is negative.
    """
    if minor_units < 0:
        raise ValueError(f"minor_units must be zero or positive, got {minor_units}")
    quantum = Decimal(1) if minor_units == 0 else Decimal(1).scaleb(-minor_units)
    return amount.quantize(quantum, rounding=ROUND_HALF_UP)


# ── Pure figures ───────────────────────────────────────────────────────────


def weighted_value(value: Any, probability: Any) -> Decimal:
    """Expected (probability-weighted) value of a single deal.

    ``weighted = value * probability`` where probability is a ``0..1``
    fraction. The result keeps full Decimal precision (no currency rounding
    assumption). Out-of-range probabilities are clamped to ``0..1``.

    Args:
        value: The deal's monetary value (non-negative).
        probability: The win probability as a ``0..1`` fraction.

    Returns:
        The expected value as a Decimal.

    Raises:
        ValueError: If ``value`` is negative or either input is not finite.
    """
    amount = coerce_money(value)
    prob = coerce_probability(probability)
    return amount * prob


def win_rate(won: int, lost: int) -> Decimal:
    """Win rate as a ``0..1`` fraction: ``won / (won + lost)``.

    Only closed deals count toward the denominator, so open deals never dilute
    the figure. When nothing has closed yet the rate is a well-defined
    ``Decimal("0")`` rather than a division-by-zero error.

    Args:
        won: Count of won deals (>= 0).
        lost: Count of lost deals (>= 0).

    Returns:
        The win rate in the inclusive range ``[0, 1]``.

    Raises:
        ValueError: If either count is negative.
    """
    won_i = int(won)
    lost_i = int(lost)
    if won_i < 0 or lost_i < 0:
        raise ValueError(f"won and lost must be zero or positive, got won={won}, lost={lost}")
    closed = won_i + lost_i
    if closed == 0:
        return Decimal(0)
    return Decimal(won_i) / Decimal(closed)


def _deal_attr(deal: Any, key: str, default: Any = None) -> Any:
    """Read ``key`` from a deal given as a mapping or an attribute object."""
    if isinstance(deal, dict):
        return deal.get(key, default)
    return getattr(deal, key, default)


def _deal_currency(deal: Any) -> str:
    """Return a deal's own ISO currency code, or ``""`` when unset.

    A blank code means the currency is unknown; it is grouped under the
    empty-string key and never silently assumed to be any default currency.
    """
    return (_deal_attr(deal, "currency", "") or "").strip().upper()


def pipeline_value_by_currency(deals: Any) -> dict[str, Decimal]:
    """Sum deal values grouped strictly by ISO currency code.

    Currencies are never blended: the return is a mapping from each currency
    code to its own Decimal subtotal. An unknown currency groups under ``""``.

    Args:
        deals: Iterable of deals (mappings or objects) exposing ``value`` and
            ``currency``.

    Returns:
        Mapping ``{currency_code: Decimal_total}``.

    Raises:
        ValueError: If any deal value is negative or not finite.
    """
    totals: dict[str, Decimal] = {}
    for deal in deals:
        currency = _deal_currency(deal)
        amount = coerce_money(_deal_attr(deal, "value", 0))
        totals[currency] = totals.get(currency, Decimal(0)) + amount
    return totals


def pipeline_value_by_stage(deals: Any) -> dict[str, dict[str, Decimal]]:
    """Sum deal values grouped by pipeline stage, then by currency.

    Two-level grouping keeps the "never mix currencies" rule inside every
    stage bucket. The shape is ``{stage_code: {currency_code: Decimal}}``.

    Args:
        deals: Iterable of deals (mappings or objects) exposing ``stage``,
            ``value`` and ``currency``. A missing stage groups under ``""``.

    Returns:
        Nested mapping ``{stage_code: {currency_code: Decimal_total}}``.

    Raises:
        ValueError: If any deal value is negative or not finite.
    """
    by_stage: dict[str, dict[str, Decimal]] = {}
    for deal in deals:
        stage = (_deal_attr(deal, "stage", "") or "").strip()
        currency = _deal_currency(deal)
        amount = coerce_money(_deal_attr(deal, "value", 0))
        bucket = by_stage.setdefault(stage, {})
        bucket[currency] = bucket.get(currency, Decimal(0)) + amount
    return by_stage


# ── ISO 8601 date helpers ──────────────────────────────────────────────────


def parse_iso_date(text: str | None) -> date | None:
    """Parse an ISO 8601 ``YYYY-MM-DD`` date, tolerant of a time suffix.

    Args:
        text: A date string such as ``"2026-07-05"`` or
            ``"2026-07-05T12:00:00Z"``; ``None`` or empty returns ``None``.

    Returns:
        A :class:`datetime.date`, or ``None`` for empty input.

    Raises:
        ValueError: If a non-empty string is not a valid ISO date.
    """
    if not text:
        return None
    head = str(text).strip()[:10]
    try:
        return date.fromisoformat(head)
    except ValueError as exc:
        raise ValueError(f"expected an ISO 8601 date (YYYY-MM-DD), got {text!r}") from exc


# ── Explainable reports (figure plus its components) ───────────────────────


def weighted_value_report(
    value: Any,
    probability: Any,
    *,
    currency: str = "",
    locale: str | None = None,
) -> dict[str, Any]:
    """Expected value together with the components used to derive it.

    Args:
        value: The deal's monetary value.
        probability: The win probability as a ``0..1`` fraction.
        currency: The deal's ISO currency code (echoed back, never assumed).
        locale: Locale for the plain-language explainer.

    Returns:
        A dict with the inputs, the derived ``weighted`` value, the currency,
        a human formula string, and a localized explainer.

    Raises:
        ValueError: If ``value`` is negative or an input is not finite.
    """
    amount = coerce_money(value)
    prob = coerce_probability(probability)
    weighted = amount * prob
    return {
        "value": amount,
        "probability": prob,
        "weighted": weighted,
        "currency": (currency or "").strip().upper(),
        "formula": "weighted = value * probability",
        "explanation": explain("weighted_value", locale),
    }


def win_rate_report(won: int, lost: int, *, locale: str | None = None) -> dict[str, Any]:
    """Win rate together with the counts used to derive it.

    Args:
        won: Count of won deals (>= 0).
        lost: Count of lost deals (>= 0).
        locale: Locale for the plain-language explainer.

    Returns:
        A dict with ``won``, ``lost``, ``closed``, the ``win_rate`` (0..1),
        a human formula string, and a localized explainer.

    Raises:
        ValueError: If either count is negative.
    """
    rate = win_rate(won, lost)
    return {
        "won": int(won),
        "lost": int(lost),
        "closed": int(won) + int(lost),
        "win_rate": rate,
        "formula": "win_rate = won / (won + lost)",
        "explanation": explain("win_rate", locale),
    }
