# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""International, plain-language helpers for meeting action items.

This module is intentionally free of any database, ORM, network, or
FastAPI dependency. Every function here is pure: given the same input it
returns the same output and never raises anything other than a clean
``ValueError`` for logically invalid input (for example a negative
count). Nothing here ever returns ``NaN`` or ``inf`` and no rate can
leave the documented range.

Design goals (worldwide, clear and simple):

- No hardcoded locale. Dates are read as ISO 8601 (``YYYY-MM-DD``). The
  "overdue" threshold is a caller-supplied grace period in days and the
  reference date is always a parameter, so the same code behaves the
  same in every timezone and office.
- Plain language. Every metric has a one-line explainer that a site
  engineer or estimator can read in a few seconds, localized in every
  platform language with an English fallback.
- Explainable rates. ``completion_rate`` is completed actions divided by
  total actions. The raw components (open, done, cancelled, overdue) are
  always exposed next to the rate so nothing is a black box.

The three status words used across the meetings module are ``open``,
``completed``, and ``cancelled`` (see ``ActionItemEntry`` in
``schemas.py``). The ``meetings.actions`` locale group covers exactly those
plus the derived ``overdue`` flag.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from app.core.i18n import SUPPORTED_LOCALES, is_locale_loaded, load_translations, t

# ==========================================================================
# Localization: the platform's locale files, group ``meetings.actions``
# ==========================================================================

_DEFAULT_LANG = "en"
_GROUP = "meetings.actions"

# The canonical action-item statuses used by the meetings module.
KNOWN_STATUSES: tuple[str, ...] = ("open", "completed", "cancelled")


# ==========================================================================
# Language + translation
# ==========================================================================


def normalize_lang(lang: str | None) -> str:
    """Return a supported language code, defaulting to English.

    Accepts loose input such as ``"de-DE"``, ``"DE"``, or ``"ru_RU"`` and
    reduces it to the base language. Any language the platform does not carry
    or an empty value falls back to ``"en"`` so the caller never has to guard
    the return value.
    """
    if not lang:
        return _DEFAULT_LANG
    base = str(lang).strip().lower().replace("_", "-").split("-", 1)[0]
    return base if base in SUPPORTED_LOCALES else _DEFAULT_LANG


def _lookup(key: str, lang: str | None) -> str | None:
    """The text of ``key`` in ``lang``, English for a key the language lacks, ``None`` when unknown."""
    if not is_locale_loaded(_DEFAULT_LANG):
        load_translations()
    full = f"{_GROUP}.{key}"
    text = t(full, normalize_lang(lang))
    return None if text == full else text


def translate(key: str, lang: str | None = None) -> str:
    """Translate a dotted key, falling back to English then to the key.

    Args:
        key: A dotted identifier such as ``"status.open"``.
        lang: Any locale hint. Unsupported values fall back to English.

    Returns:
        The localized string, or the English string if the requested
        language lacks the key, or the key itself if it is unknown.
    """
    return _lookup(key, lang) or key


def localize_status(status_value: str | None, lang: str | None = None) -> str:
    """Localize an action-item status word (open, completed, cancelled).

    Unknown statuses are echoed back unchanged rather than turned into a
    raw key, so a future status value never leaks as ``"status.foo"``.
    """
    norm = (status_value or "open").strip().lower() or "open"
    return _lookup(f"status.{norm}", lang) or (str(status_value) if status_value else norm)


def overdue_label(is_overdue_flag: bool, lang: str | None = None) -> str:
    """Return the localized ``Overdue`` or ``On track`` flag word."""
    return translate("flag.overdue" if is_overdue_flag else "flag.on_track", lang)


def explainers(lang: str | None = None) -> dict[str, str]:
    """Return the four one-line plain-language explainers, localized.

    Keys: ``action_item``, ``completion_rate``, ``open_vs_done``,
    ``overdue``. Always present, always non-empty.
    """
    return {
        "action_item": translate("explain.action_item", lang),
        "completion_rate": translate("explain.completion_rate", lang),
        "open_vs_done": translate("explain.open_vs_done", lang),
        "overdue": translate("explain.overdue", lang),
    }


# ==========================================================================
# Date parsing (ISO 8601 only, timezone free by design)
# ==========================================================================


def parse_iso_date(value: Any) -> date | None:  # noqa: ANN401 - accepts loose input
    """Parse an ISO 8601 date, returning ``None`` on anything unparseable.

    Accepts a ``date``, a ``datetime`` (its date part is used), or a
    string whose first 10 characters are ``YYYY-MM-DD``. Empty, ``None``,
    or malformed input returns ``None`` instead of raising, so a single
    bad row never breaks a whole aggregation.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


# ==========================================================================
# Pure metric helpers
# ==========================================================================


def action_completion_rate(
    done: int,
    total: int,
    *,
    as_percent: bool = False,
) -> float:
    """Completed actions divided by total actions, guarded at zero.

    The rate is derived as ``done / total``. When there are no actions at
    all the rate is defined as ``0.0`` (nothing done, nothing to do),
    which avoids a division by zero. The result is always within
    ``[0.0, 1.0]`` (or ``[0.0, 100.0]`` when ``as_percent`` is set) and is
    never ``NaN`` or ``inf``.

    Args:
        done: Count of completed actions. Must be non-negative.
        total: Count of all actions. Must be non-negative.
        as_percent: When true, return a percentage in ``[0, 100]``
            instead of a ratio in ``[0, 1]``.

    Returns:
        The completion rate.

    Raises:
        ValueError: If either count is negative, or if ``done`` exceeds
            ``total`` (a logically impossible input).
    """
    if done < 0 or total < 0:
        raise ValueError("action counts must be non-negative")
    if done > total:
        raise ValueError("completed count cannot exceed total count")
    if total == 0:
        return 0.0
    rate = done / total
    # Clamp defensively so floating point can never push us out of range.
    rate = max(0.0, min(1.0, rate))
    if as_percent:
        return round(rate * 100.0, 4)
    return round(rate, 6)


def count_actions_by_status(action_items: list[Any] | None) -> dict[str, int]:
    """Count action items by status word.

    The result always contains the three canonical keys (``open``,
    ``completed``, ``cancelled``). Any unrecognized status is tallied
    under an ``other`` key, which is only present when it is non-zero.
    Non-dict entries and missing statuses are treated as ``open`` (the
    schema default), and an empty or ``None`` input yields all zeros.
    """
    counts: dict[str, int] = dict.fromkeys(KNOWN_STATUSES, 0)
    other = 0
    for item in action_items or []:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status", "open")).strip().lower() or "open"
        if status in counts:
            counts[status] += 1
        else:
            other += 1
    if other:
        counts["other"] = other
    return counts


def open_vs_done(action_items: list[Any] | None) -> tuple[int, int]:
    """Return ``(open_count, done_count)`` for a set of action items.

    A tiny convenience over :func:`count_actions_by_status` for the most
    common two-number readout. Cancelled and unknown statuses are counted
    in neither bucket.
    """
    counts = count_actions_by_status(action_items)
    return counts["open"], counts["completed"]


def is_overdue(
    due_date: Any,  # noqa: ANN401 - accepts str/date/datetime/None
    reference_date: Any,  # noqa: ANN401 - accepts str/date/datetime/None
    *,
    status: str | None = "open",
    grace_days: int = 0,
) -> bool:
    """Return whether an action is overdue at a given reference date.

    An action is overdue only when all of the following hold:

    - it is still ``open`` (a completed or cancelled action is never
      overdue),
    - it has a parseable due date,
    - the reference date is parseable, and
    - the due date plus the ``grace_days`` threshold is strictly before
      the reference date.

    The ``grace_days`` value is the overdue threshold, always supplied by
    the caller, so nothing is hardcoded to a single locale or policy. Any
    unparseable date returns ``False`` rather than raising.

    Args:
        due_date: The action due date (ISO string, ``date``, or
            ``datetime``).
        reference_date: The date to compare against, typically "today" in
            the caller's own timezone.
        status: The action status. Only ``open`` can be overdue.
        grace_days: Days of slack added to the due date before it counts
            as overdue. Defaults to zero (strict).

    Returns:
        ``True`` if the action is overdue, otherwise ``False``.
    """
    if (status or "open").strip().lower() != "open":
        return False
    due = parse_iso_date(due_date)
    ref = parse_iso_date(reference_date)
    if due is None or ref is None:
        return False
    if grace_days:
        due = due + timedelta(days=int(grace_days))
    return due < ref


def count_overdue_open_actions(
    action_items: list[Any] | None,
    reference_date: Any,  # noqa: ANN401 - accepts str/date/datetime/None
    *,
    grace_days: int = 0,
) -> int:
    """Count open action items that are overdue at ``reference_date``.

    Wraps :func:`is_overdue` over a list. Non-dict entries are skipped and
    an unparseable ``reference_date`` yields ``0`` (nothing can be judged
    overdue without a valid reference), never an error.
    """
    if parse_iso_date(reference_date) is None:
        return 0
    total = 0
    for item in action_items or []:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status", "open")).strip().lower() or "open"
        if is_overdue(
            item.get("due_date"),
            reference_date,
            status=status,
            grace_days=grace_days,
        ):
            total += 1
    return total


# ==========================================================================
# Aggregate summary (components + rate + explainers, all in one place)
# ==========================================================================


@dataclass(frozen=True)
class ActionItemSummary:
    """A plain, explainable readout of a meeting's action items.

    Every rate is presented next to the raw components it is derived
    from, so the number is never a black box. ``completion_rate`` is
    ``done / total`` (see :func:`action_completion_rate`); ``total``
    includes cancelled actions, matching the pure helper exactly.
    """

    total: int
    open: int
    done: int
    cancelled: int
    other: int
    overdue_open: int
    completion_rate: float
    completion_percent: float
    lang: str
    explainers: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly plain dict of the summary."""
        return {
            "total": self.total,
            "open": self.open,
            "done": self.done,
            "cancelled": self.cancelled,
            "other": self.other,
            "overdue_open": self.overdue_open,
            "completion_rate": self.completion_rate,
            "completion_percent": self.completion_percent,
            "lang": self.lang,
            "explainers": dict(self.explainers),
        }


def summarize_action_items(
    action_items: list[Any] | None,
    *,
    reference_date: Any = None,  # noqa: ANN401 - accepts str/date/datetime/None
    grace_days: int = 0,
    lang: str | None = None,
) -> ActionItemSummary:
    """Build a full, localized, explainable action-item summary.

    Combines the status counts, the completion rate, and the overdue
    count into one object, together with the localized one-line
    explainers for each concept. This is the single call a router or a
    dashboard needs to render a clear readout.

    Args:
        action_items: The raw JSON action-items list (dicts). ``None`` or
            an empty list yields an all-zero summary with a ``0.0`` rate.
        reference_date: The date to judge overdue against. When omitted or
            unparseable, ``overdue_open`` is ``0`` (it cannot be judged).
        grace_days: Overdue threshold in days (see :func:`is_overdue`).
        lang: Locale hint for the explainers and any localized labels.

    Returns:
        An :class:`ActionItemSummary`.
    """
    resolved_lang = normalize_lang(lang)
    counts = count_actions_by_status(action_items)
    other = counts.get("other", 0)
    total = counts["open"] + counts["completed"] + counts["cancelled"] + other
    done = counts["completed"]
    overdue = count_overdue_open_actions(
        action_items,
        reference_date,
        grace_days=grace_days,
    )
    rate = action_completion_rate(done, total)
    percent = action_completion_rate(done, total, as_percent=True)
    return ActionItemSummary(
        total=total,
        open=counts["open"],
        done=done,
        cancelled=counts["cancelled"],
        other=other,
        overdue_open=overdue,
        completion_rate=rate,
        completion_percent=percent,
        lang=resolved_lang,
        explainers=explainers(resolved_lang),
    )
