# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""International, dependency-free reporting helpers for enterprise workflows.

This module is strictly additive and pure: no database, no I/O, no
framework imports. It provides small, well-defined helpers that turn the
raw workflow state (steps, statuses, dates) into clear, plain-language,
localizable figures that a site engineer or estimator anywhere in the
world can understand in under a minute.

Design goals:

* International by default. No locale is hardcoded into the numbers: the
  caller passes a locale for the words, and every date is read as ISO
  8601 (``datetime.fromisoformat``, with a trailing ``Z`` accepted as
  UTC). Service-level thresholds (SLA / grace days) are always a
  parameter, never a baked-in constant.
* Clear. Each figure has a one-line explainer describing how it is
  derived, and status / action words localize into English, German and
  Russian with an English fallback for any unknown locale.
* Safe on the edges. Division by zero (no steps, no instances), empty
  sets and negative counts are all handled: helpers either return a
  well-defined value (a rate stays inside [0, 1] or [0, 100], never NaN
  or infinity) or raise a plain ``ValueError`` with a readable message.
  They never surface an unhandled 500 or a non-finite number.
* Explainable. The ``*_breakdown`` helpers expose the individual
  components behind each headline figure so the number can always be
  traced back to its inputs.

All timestamps are ISO 8601 strings, ``date`` or ``datetime`` objects.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta

from app.core.i18n import catalogue_table

__all__ = [
    "ACTIVE_STATUSES",
    "DEFAULT_LOCALE",
    "KNOWN_STATUSES",
    "SUPPORTED_LOCALES",
    "TERMINAL_STATUSES",
    "active_vs_done",
    "counts_by_state",
    "cycle_time_days",
    "describe_step",
    "explain",
    "is_step_overdue",
    "localize_action_type",
    "localize_status",
    "normalize_locale",
    "overdue_breakdown",
    "step_completion_breakdown",
    "step_completion_rate",
]

# ── Vocabulary ───────────────────────────────────────────────────────────────

DEFAULT_LOCALE = "en"
SUPPORTED_LOCALES: tuple[str, ...] = ("en", "de", "ru")

# A request is "active" while it is still in-flight and "done" once it has
# reached any terminal outcome. Mirrors the statuses the service writes.
ACTIVE_STATUSES: frozenset[str] = frozenset({"pending"})
TERMINAL_STATUSES: frozenset[str] = frozenset({"approved", "rejected", "cancelled"})
KNOWN_STATUSES: frozenset[str] = ACTIVE_STATUSES | TERMINAL_STATUSES

# Localized status words. English is the fallback for any missing locale
# or any status that is not in the table.
_STATUS_LABELS: dict[str, dict[str, str]] = catalogue_table(
    "enterprise_workflows.intl.status_labels", ("pending", "approved", "rejected", "cancelled")
)

# Localized per-step action words. Keys match ALLOWED_ACTION_TYPES in the
# service layer. English is the fallback.
_ACTION_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "approve": "Approve or reject",
        "review": "Review",
        "sign_off": "Final sign-off",
        "notify": "Notify",
    },
    "de": {
        "approve": "Genehmigen oder ablehnen",
        "review": "Pruefen",
        "sign_off": "Endgueltige Freigabe",
        "notify": "Benachrichtigen",
    },
    "ru": {
        "approve": "Одобрить или отклонить",
        "review": "Проверка",
        "sign_off": "Окончательное утверждение",
        "notify": "Уведомить",
    },
}

_STEP_WORD: dict[str, str] = {"en": "Step", "de": "Schritt", "ru": "Шаг"}
_ROLE_WORD: dict[str, str] = {"en": "role", "de": "Rolle", "ru": "роль"}

# One-line explainers for each headline figure, localized. English is the
# fallback for any missing locale.
_EXPLAINERS: dict[str, dict[str, str]] = {
    "workflow_step": {
        "en": "A single decision point in a workflow: who acts and what they do.",
        "de": "Ein einzelner Entscheidungspunkt im Ablauf: wer handelt und was.",
        "ru": "Отдельный шаг принятия решения: кто действует и что делает.",
    },
    "step_completion_rate": {
        "en": "Share of a request's steps already completed, from 0 to 1.",
        "de": "Anteil der bereits erledigten Schritte einer Anfrage, von 0 bis 1.",
        "ru": "Доля уже завершенных шагов заявки, от 0 до 1.",
    },
    "active_vs_done": {
        "en": "How many requests are still in progress versus finished.",
        "de": "Wie viele Anfragen noch laufen im Vergleich zu abgeschlossenen.",
        "ru": "Сколько заявок еще в работе по сравнению с завершенными.",
    },
    "overdue": {
        "en": "A step is overdue when the reference date passes its due date plus the SLA grace days.",
        "de": "Ein Schritt ist ueberfaellig, wenn das Bezugsdatum das Faelligkeitsdatum plus SLA-Tage ueberschreitet.",
        "ru": "Шаг просрочен, когда контрольная дата превышает срок плюс дни SLA.",
    },
    "cycle_time_days": {
        "en": "Elapsed days from a request's start to its finish.",
        "de": "Vergangene Tage vom Start bis zum Abschluss einer Anfrage.",
        "ru": "Прошедшие дни от начала заявки до ее завершения.",
    },
}


# ── Locale helpers ───────────────────────────────────────────────────────────


def normalize_locale(locale: str | None) -> str:
    """Reduce a locale tag to its base language code.

    ``"de-DE"``, ``"de_AT"`` and ``"DE"`` all become ``"de"``. An empty or
    unknown value falls back to :data:`DEFAULT_LOCALE`.
    """
    if not locale:
        return DEFAULT_LOCALE
    base = str(locale).strip().replace("_", "-").split("-", 1)[0].lower()
    return base or DEFAULT_LOCALE


def _lookup(table: dict[str, dict[str, str]], key: str, locale: str) -> str | None:
    """Look ``key`` up in ``table`` for ``locale`` with an English fallback."""
    lang = normalize_locale(locale)
    localized = table.get(lang, {}).get(key)
    if localized is not None:
        return localized
    return table.get(DEFAULT_LOCALE, {}).get(key)


def localize_status(status: str, locale: str = DEFAULT_LOCALE) -> str:
    """Localize a request status word (English fallback).

    An unknown status is returned as a readable title-cased phrase so the
    caller never sees a raw enum token or an empty string for a real value.
    """
    key = str(status or "").strip().lower()
    label = _lookup(_STATUS_LABELS, key, locale)
    if label is not None:
        return label
    return key.replace("_", " ").title()


def localize_action_type(action_type: str, locale: str = DEFAULT_LOCALE) -> str:
    """Localize a per-step action-type word (English fallback)."""
    key = str(action_type or "").strip().lower()
    label = _lookup(_ACTION_LABELS, key, locale)
    if label is not None:
        return label
    return key.replace("_", " ").title()


def explain(figure: str, locale: str = DEFAULT_LOCALE) -> str:
    """Return a one-line, plain-language explainer for a headline figure.

    Known ``figure`` keys: ``workflow_step``, ``step_completion_rate``,
    ``active_vs_done``, ``overdue``, ``cycle_time_days``. An unknown key
    yields an empty string rather than raising, so a caller can safely
    attach an explainer to any label.
    """
    entry = _EXPLAINERS.get(str(figure or "").strip())
    if not entry:
        return ""
    lang = normalize_locale(locale)
    return entry.get(lang) or entry.get(DEFAULT_LOCALE, "")


# ── Date parsing (ISO 8601) ──────────────────────────────────────────────────


def _parse_dt(value: str | date | datetime, *, field: str) -> datetime:
    """Parse an ISO 8601 string / date / datetime into a ``datetime``.

    A trailing ``Z`` is accepted and read as UTC. Raises ``ValueError``
    with a readable message on any unparseable input.
    """
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            raise ValueError(f"{field} must be a non-empty ISO 8601 string")
        candidate = f"{raw[:-1]}+00:00" if raw.endswith("Z") else raw
        try:
            return datetime.fromisoformat(candidate)
        except ValueError as exc:
            raise ValueError(f"{field} is not a valid ISO 8601 date/time: {value!r}") from exc
    raise ValueError(f"{field} must be an ISO 8601 string, date, or datetime")


def _align(a: datetime, b: datetime) -> tuple[datetime, datetime]:
    """Make two datetimes comparable.

    If exactly one side is timezone-aware, the naive side is read as UTC
    so subtraction and comparison never raise on a mixed pair.
    """
    if (a.tzinfo is None) != (b.tzinfo is None):
        if a.tzinfo is None:
            a = a.replace(tzinfo=UTC)
        if b.tzinfo is None:
            b = b.replace(tzinfo=UTC)
    return a, b


# ── Rates and counts ─────────────────────────────────────────────────────────


def step_completion_rate(
    completed_steps: int,
    total_steps: int,
    *,
    scale: str = "fraction",
) -> float:
    """Share of a request's steps that are already completed.

    Derivation: ``completed_steps / total_steps``, clamped to the closed
    range [0, 1] (or [0, 100] with ``scale="percent"``).

    Zero guard: a request with ``total_steps == 0`` has nothing to do, so
    the rate is a well-defined ``0.0`` rather than a division error.

    Raises ``ValueError`` on negative counts or when ``completed_steps``
    exceeds ``total_steps`` (an impossible state that must be caught, not
    silently clamped).
    """
    if scale not in ("fraction", "percent"):
        raise ValueError("scale must be 'fraction' or 'percent'")
    if completed_steps < 0 or total_steps < 0:
        raise ValueError("step counts must be >= 0")
    if completed_steps > total_steps:
        raise ValueError("completed_steps cannot exceed total_steps")
    rate = 0.0 if total_steps == 0 else completed_steps / total_steps
    rate = min(1.0, max(0.0, rate))
    return rate * 100.0 if scale == "percent" else rate


def step_completion_breakdown(
    completed_steps: int,
    total_steps: int,
    *,
    locale: str = DEFAULT_LOCALE,
) -> dict[str, object]:
    """Completion rate plus the components it is derived from.

    Exposes ``completed``, ``total``, the rate on both scales, the
    remaining step count, and a localized one-line explanation, so the
    headline figure is always traceable to its inputs.
    """
    fraction = step_completion_rate(completed_steps, total_steps, scale="fraction")
    return {
        "completed": completed_steps,
        "total": total_steps,
        "remaining": max(0, total_steps - completed_steps),
        "rate_fraction": fraction,
        "rate_percent": round(fraction * 100.0, 2),
        "explanation": explain("step_completion_rate", locale),
    }


def _status_of(item: object) -> str:
    """Extract a normalized status string from a status, dict, or object."""
    if isinstance(item, str):
        value: object = item
    elif isinstance(item, dict):
        value = item.get("status")
    else:
        value = getattr(item, "status", None)
    text = str(value).strip().lower() if value is not None else ""
    return text or "unknown"


def counts_by_state(items: Iterable[object]) -> dict[str, int]:
    """Count items grouped by their status.

    Accepts an iterable of status strings, of dicts with a ``status`` key,
    or of objects with a ``status`` attribute. An empty iterable yields an
    empty dict (no division, no error). Items with no readable status are
    grouped under ``"unknown"`` so nothing is silently dropped.
    """
    counts: dict[str, int] = {}
    for item in items:
        key = _status_of(item)
        counts[key] = counts.get(key, 0) + 1
    return counts


def active_vs_done(items: Iterable[object]) -> dict[str, int]:
    """Split requests into active (in progress), done (terminal) and other.

    Derivation: statuses in :data:`ACTIVE_STATUSES` count as ``active``,
    those in :data:`TERMINAL_STATUSES` count as ``done``, and any status
    outside :data:`KNOWN_STATUSES` counts as ``other``. ``total`` is their
    sum. An empty input yields all zeros.
    """
    counts = counts_by_state(items)
    active = sum(n for s, n in counts.items() if s in ACTIVE_STATUSES)
    done = sum(n for s, n in counts.items() if s in TERMINAL_STATUSES)
    other = sum(n for s, n in counts.items() if s not in KNOWN_STATUSES)
    return {"active": active, "done": done, "other": other, "total": active + done + other}


# ── Dates: overdue and cycle time ────────────────────────────────────────────


def is_step_overdue(
    due_date: str | date | datetime,
    reference_date: str | date | datetime,
    *,
    sla_days: int = 0,
) -> bool:
    """Return whether a step is overdue at ``reference_date``.

    A step is overdue when ``reference_date`` is strictly later than
    ``due_date`` plus ``sla_days`` grace days. The SLA is always a
    parameter, never a hardcoded threshold, so it can differ per region,
    client or contract. Dates are read as ISO 8601.

    Raises ``ValueError`` on a negative ``sla_days`` or an unparseable
    date.
    """
    if sla_days < 0:
        raise ValueError("sla_days must be >= 0")
    due = _parse_dt(due_date, field="due_date")
    ref = _parse_dt(reference_date, field="reference_date")
    due, ref = _align(due, ref)
    return ref > due + timedelta(days=sla_days)


def overdue_breakdown(
    due_date: str | date | datetime,
    reference_date: str | date | datetime,
    *,
    sla_days: int = 0,
    locale: str = DEFAULT_LOCALE,
) -> dict[str, object]:
    """Overdue flag plus the components it is derived from.

    Exposes the effective deadline (due date plus SLA), how many days the
    reference date is past that deadline (``0`` when not overdue), the SLA
    used, and a localized explanation.
    """
    if sla_days < 0:
        raise ValueError("sla_days must be >= 0")
    due = _parse_dt(due_date, field="due_date")
    ref = _parse_dt(reference_date, field="reference_date")
    due, ref = _align(due, ref)
    deadline = due + timedelta(days=sla_days)
    overdue = ref > deadline
    days_over = (ref - deadline).total_seconds() / 86400.0 if overdue else 0.0
    return {
        "is_overdue": overdue,
        "sla_days": sla_days,
        "deadline": deadline.isoformat(),
        "days_overdue": round(days_over, 4),
        "explanation": explain("overdue", locale),
    }


def cycle_time_days(
    start: str | date | datetime,
    end: str | date | datetime,
    *,
    allow_negative: bool = False,
) -> float:
    """Elapsed days between two ISO 8601 timestamps.

    Derivation: ``(end - start)`` expressed in days (fractional). By
    default a negative span (``end`` before ``start``) raises
    ``ValueError`` because a cycle time cannot be negative; pass
    ``allow_negative=True`` to return the signed value instead (useful for
    clock-skew diagnostics).
    """
    start_dt = _parse_dt(start, field="start")
    end_dt = _parse_dt(end, field="end")
    start_dt, end_dt = _align(start_dt, end_dt)
    days = (end_dt - start_dt).total_seconds() / 86400.0
    if days < 0 and not allow_negative:
        raise ValueError("end is before start; cycle time cannot be negative")
    return days


def describe_step(
    step: dict[str, object],
    *,
    index: int | None = None,
    locale: str = DEFAULT_LOCALE,
) -> str:
    """Build a one-line, plain-language description of a workflow step.

    Uses the step's ``name``, ``action_type`` (defaulting to ``approve``)
    and optional ``role``, all localized where possible. Example (English):
    ``"Step 2: Design review (Review) - role: manager"``.

    Raises ``ValueError`` if ``step`` is not a dict.
    """
    if not isinstance(step, dict):
        raise ValueError("step must be a dict")
    lang = normalize_locale(locale)
    name = str(step.get("name") or "").strip()
    action_type = str(step.get("action_type") or "approve").strip().lower()
    role = str(step.get("role") or "").strip()

    action_label = localize_action_type(action_type, lang)
    title = name or action_label
    prefix = f"{_STEP_WORD.get(lang, _STEP_WORD[DEFAULT_LOCALE])} {index}: " if index is not None else ""

    parts = [f"{prefix}{title}"]
    if name and action_label.lower() != name.lower():
        parts.append(f"({action_label})")
    if role:
        role_word = _ROLE_WORD.get(lang, _ROLE_WORD[DEFAULT_LOCALE])
        parts.append(f"- {role_word}: {role}")
    return " ".join(parts)
