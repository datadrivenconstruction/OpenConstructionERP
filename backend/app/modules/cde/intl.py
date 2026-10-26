# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""International, explainable helpers for the ISO 19650 Common Data Environment.

This module is deliberately pure and database free. It adds plain-language,
locale-aware helpers on top of the existing CDE vocabulary without changing any
existing signature, route or schema. Everything here is safe to call from a
router, a report generator or a test.

Design goals:

- International: no hardcoded machine locale is read, dates are formatted as
  ISO 8601 strings, and every localized word falls back to English when a
  language is not supported.
- Clarity: one-line, plain-language explainers for each ISO 19650 state and for
  a revision, so a site engineer understands the figure without a manual.
- Edge cases: division by zero is guarded, empty inputs return well-defined
  values, and unknown states raise a clean ``ValueError`` instead of surfacing a
  500 or a NaN / infinity anywhere.
- Explainability: aggregate figures expose the exact components they are derived
  from, so a reader can reproduce every number by hand.

The canonical four-state lifecycle (WIP -> SHARED -> PUBLISHED -> ARCHIVED) and
the transition gates live in :mod:`app.core.cde_states`; this module reuses that
state machine rather than re-encoding the rules.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from typing import Any

from app.core.cde_states import CDEState, CDEStateMachine
from app.core.i18n import catalogue_table

# ── Languages ─────────────────────────────────────────────────────────────

# Localization ships with English, German and Russian in parity with the
# validation-message bundles. Any other language code falls back to English.
DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES: tuple[str, ...] = ("en", "de", "ru")

# Canonical ordered list of CDE states (source of truth: CDEState enum).
CDE_STATE_ORDER: tuple[str, ...] = tuple(s.value for s in CDEState)

_UNKNOWN_STATE_KEY = "unknown"


# ── Localized vocabulary ──────────────────────────────────────────────────

# Short display label for each CDE state, per language. English is the fallback.
_STATE_LABELS: dict[str, dict[str, str]] = catalogue_table(
    "cde.intl.state_labels", ("wip", "shared", "published", "archived")
)

# One-line, plain-language explainer for each CDE state, per language.
_STATE_EXPLAINERS: dict[str, dict[str, str]] = {
    "en": {
        "wip": ("Work in progress: draft content owned by one task team and not yet visible to others."),
        "shared": (
            "Shared: content released to the wider project team for coordination and comment, but not yet approved."
        ),
        "published": (
            "Published: content approved and authorised for use, for example for construction or manufacture."
        ),
        "archived": ("Archived: a superseded or closed record kept only for audit and history."),
    },
    "de": {
        "wip": ("In Bearbeitung: Entwurf eines einzelnen Fachteams, fuer andere noch nicht sichtbar."),
        "shared": (
            "Freigegeben zur Abstimmung: fuer das Projektteam zur Koordination und "
            "Kommentierung bereitgestellt, aber noch nicht genehmigt."
        ),
        "published": (
            "Veroeffentlicht: genehmigt und zur Verwendung freigegeben, zum Beispiel fuer Ausfuehrung oder Fertigung."
        ),
        "archived": (
            "Archiviert: ein ersetzter oder abgeschlossener Datensatz, nur fuer Nachweis und Historie aufbewahrt."
        ),
    },
    "ru": {
        "wip": ("В работе: черновик одной рабочей группы, ещё не виден остальным участникам."),
        "shared": (
            "Опубликовано для согласования: передано команде проекта для координации и замечаний, но ещё не утверждено."
        ),
        "published": ("Выпущено: утверждено и разрешено к применению, например для строительства или изготовления."),
        "archived": ("Архив: замещённая или закрытая запись, хранится только для аудита и истории."),
    },
}

# Localized short label for a revision status word. ``draft`` is the only status
# the service writes today; ``preliminary`` / ``final`` mirror the revision
# ``is_preliminary`` flag. English is the fallback.
_STATUS_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "draft": "Draft",
        "preliminary": "Preliminary",
        "final": "Final",
    },
    "de": {
        "draft": "Entwurf",
        "preliminary": "Vorlaeufig",
        "final": "Endgueltig",
    },
    "ru": {
        "draft": "Черновик",
        "preliminary": "Предварительно",
        "final": "Окончательно",
    },
}

# One-line explainer for what a revision is, per language.
_REVISION_EXPLAINER: dict[str, str] = {
    "en": (
        "A revision is one numbered version of a document inside its container; "
        "the highest revision number is the current one."
    ),
    "de": (
        "Eine Revision ist eine nummerierte Version eines Dokuments in seinem "
        "Container; die hoechste Revisionsnummer ist die aktuelle."
    ),
    "ru": (
        "Ревизия - это одна пронумерованная версия документа внутри контейнера; "
        "актуальной считается версия с наибольшим номером."
    ),
}


# ── Language helpers ──────────────────────────────────────────────────────


def normalize_language(language: str | None) -> str:
    """Return a supported language code, falling back to English.

    The match is case insensitive and tolerates region suffixes such as
    ``de-DE`` or ``ru_RU``. Any unsupported or missing value yields
    :data:`DEFAULT_LANGUAGE`.
    """
    if not language:
        return DEFAULT_LANGUAGE
    base = language.strip().lower().replace("_", "-").split("-", 1)[0]
    if base in SUPPORTED_LANGUAGES:
        return base
    return DEFAULT_LANGUAGE


# ── State normalisation ───────────────────────────────────────────────────


def canonical_state(state: str) -> str:
    """Return the canonical lower-case CDE state value.

    Args:
        state: A state string in any casing, for example ``"WIP"``.

    Returns:
        One of ``wip`` / ``shared`` / ``published`` / ``archived``.

    Raises:
        ValueError: If ``state`` is not one of the four ISO 19650 states. The
            message lists the allowed values so callers can surface a clean 400
            rather than a 500.
    """
    if not isinstance(state, str) or not state.strip():
        raise ValueError(f"CDE state must be a non-empty string, got {state!r}")
    value = state.strip().lower()
    if value not in CDE_STATE_ORDER:
        allowed = ", ".join(CDE_STATE_ORDER)
        raise ValueError(f"Unknown CDE state {state!r}. Allowed states: {allowed}")
    return value


def is_known_state(state: str) -> bool:
    """Return ``True`` if ``state`` is one of the four canonical CDE states."""
    return isinstance(state, str) and state.strip().lower() in CDE_STATE_ORDER


# ── Localized lookups ─────────────────────────────────────────────────────


def localize_state(state: str, language: str = DEFAULT_LANGUAGE) -> str:
    """Return the localized short label for a CDE ``state``.

    Falls back to English for an unsupported language. Raises ``ValueError``
    for an unknown state (a closed vocabulary), never a 500.
    """
    value = canonical_state(state)
    lang = normalize_language(language)
    return _STATE_LABELS.get(lang, _STATE_LABELS[DEFAULT_LANGUAGE]).get(
        value,
        _STATE_LABELS[DEFAULT_LANGUAGE][value],
    )


def explain_state(state: str, language: str = DEFAULT_LANGUAGE) -> str:
    """Return a one-line plain-language explainer for a CDE ``state``.

    Falls back to English for an unsupported language. Raises ``ValueError``
    for an unknown state.
    """
    value = canonical_state(state)
    lang = normalize_language(language)
    return _STATE_EXPLAINERS.get(lang, _STATE_EXPLAINERS[DEFAULT_LANGUAGE]).get(
        value,
        _STATE_EXPLAINERS[DEFAULT_LANGUAGE][value],
    )


def localize_status(status: str, language: str = DEFAULT_LANGUAGE) -> str:
    """Return the localized short label for a revision ``status`` word.

    Unlike :func:`localize_state`, an unrecognised status is not an error: the
    input is returned unchanged with only surrounding whitespace stripped, so
    display never breaks on a status the vocabulary does not yet cover.
    """
    if not isinstance(status, str) or not status.strip():
        return ""
    key = status.strip().lower()
    lang = normalize_language(language)
    table = _STATUS_LABELS.get(lang, _STATUS_LABELS[DEFAULT_LANGUAGE])
    if key in table:
        return table[key]
    fallback = _STATUS_LABELS[DEFAULT_LANGUAGE]
    if key in fallback:
        return fallback[key]
    return status.strip()


def explain_revision(language: str = DEFAULT_LANGUAGE) -> str:
    """Return a one-line plain-language explainer for what a revision is."""
    lang = normalize_language(language)
    return _REVISION_EXPLAINER.get(lang, _REVISION_EXPLAINER[DEFAULT_LANGUAGE])


def describe_states(language: str = DEFAULT_LANGUAGE) -> list[dict[str, str]]:
    """Return label plus explainer for every CDE state in lifecycle order.

    Handy for building a legend or a dropdown in a single call. The list is
    ordered WIP -> SHARED -> PUBLISHED -> ARCHIVED.
    """
    return [
        {
            "state": value,
            "label": localize_state(value, language),
            "explanation": explain_state(value, language),
        }
        for value in CDE_STATE_ORDER
    ]


# ── ISO 8601 dates ────────────────────────────────────────────────────────


def format_date_iso(value: date | datetime | None) -> str | None:
    """Return an ISO 8601 calendar date (``YYYY-MM-DD``) or ``None``.

    Locale independent by construction. ``None`` in yields ``None`` out so the
    helper is safe on optional timestamps.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raise ValueError(f"Expected a date or datetime, got {type(value).__name__}")


def format_datetime_iso(value: datetime | None) -> str | None:
    """Return a full ISO 8601 timestamp or ``None``.

    Locale independent. ``None`` in yields ``None`` out.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    raise ValueError(f"Expected a datetime, got {type(value).__name__}")


# ── Counts by state ───────────────────────────────────────────────────────


def count_by_state(states: Iterable[str]) -> dict[str, int]:
    """Count containers per ISO 19650 state.

    The result always carries the four canonical states as keys (zero filled)
    plus an ``unknown`` bucket for any value outside the vocabulary, so callers
    get a stable, well-defined shape even for an empty input.

    Args:
        states: An iterable of state strings, for example the ``cde_state`` of
            every container in a project.

    Returns:
        A mapping ``{state: count}`` with keys
        ``wip, shared, published, archived, unknown``.
    """
    counts: dict[str, int] = dict.fromkeys(CDE_STATE_ORDER, 0)
    counts[_UNKNOWN_STATE_KEY] = 0
    for raw in states:
        if is_known_state(raw):
            counts[raw.strip().lower()] += 1
        else:
            counts[_UNKNOWN_STATE_KEY] += 1
    return counts


def _sum_known(counts: Mapping[str, int]) -> int:
    """Return the total of the four canonical state counts (ignores unknown)."""
    return sum(int(counts.get(value, 0)) for value in CDE_STATE_ORDER)


# ── Share / published rate ────────────────────────────────────────────────


def share_published_rate(counts: Mapping[str, int]) -> dict[str, Any]:
    """Return the share of containers that have left the private WIP area.

    A container is counted in the numerator once it reaches ``shared`` or
    ``published`` (that is, it is visible to the wider team). ``archived`` and
    ``wip`` are excluded from the numerator. The denominator is the total of the
    four canonical states.

    Division by zero is guarded: with no containers the rate and percent are a
    well-defined ``0.0`` and the result is flagged ``defined=False`` so a caller
    can show "no data" rather than a misleading zero. The result never contains
    NaN or infinity.

    Args:
        counts: A mapping like the output of :func:`count_by_state`.

    Returns:
        A dictionary exposing the derived figure and every component it was
        built from::

            {
                "rate": 0.0-1.0,
                "percent": 0.0-100.0,
                "numerator": int,       # shared + published
                "denominator": int,     # total of the four states
                "components": {"shared": int, "published": int,
                               "wip": int, "archived": int},
                "defined": bool,        # False only when denominator == 0
                "formula": str,         # human-readable derivation
            }
    """
    shared = int(counts.get(CDEState.SHARED.value, 0))
    published = int(counts.get(CDEState.PUBLISHED.value, 0))
    wip = int(counts.get(CDEState.WIP.value, 0))
    archived = int(counts.get(CDEState.ARCHIVED.value, 0))

    numerator = shared + published
    denominator = _sum_known(counts)

    if denominator <= 0:
        rate = 0.0
        defined = False
    else:
        rate = numerator / denominator
        defined = True

    return {
        "rate": round(rate, 6),
        "percent": round(rate * 100.0, 2),
        "numerator": numerator,
        "denominator": denominator,
        "components": {
            "shared": shared,
            "published": published,
            "wip": wip,
            "archived": archived,
        },
        "defined": defined,
        "formula": "(shared + published) / (wip + shared + published + archived)",
    }


# ── Latest revision selector ──────────────────────────────────────────────


def _get_field(item: Any, name: str) -> Any:
    """Read ``name`` from a mapping or an attribute holder, else ``None``."""
    if isinstance(item, Mapping):
        return item.get(name)
    return getattr(item, name, None)


def latest_revision(revisions: Sequence[Any]) -> Any | None:
    """Return the current revision, or ``None`` for an empty input.

    The current revision is the one with the highest ``revision_number``. Ties
    (which should not happen for valid data) are broken by the later
    ``created_at`` when present, so the selection is deterministic. A missing or
    non-integer ``revision_number`` is treated as ``-1`` so a malformed row never
    wins and never raises.

    Works with revisions given as dicts or as ORM objects (anything exposing a
    ``revision_number`` and optionally a ``created_at``).
    """
    if not revisions:
        return None

    def sort_key(item: Any) -> tuple[int, float]:
        number_raw = _get_field(item, "revision_number")
        try:
            number = int(number_raw)
        except (TypeError, ValueError):
            number = -1
        created = _get_field(item, "created_at")
        created_ord = 0.0
        if isinstance(created, datetime):
            created_ord = created.timestamp()
        return (number, created_ord)

    return max(revisions, key=sort_key)


# ── Transition validity ───────────────────────────────────────────────────

# One shared, stateless machine instance is safe to reuse: it holds no state.
_state_machine = CDEStateMachine()


def is_transition_allowed(from_state: str, to_state: str) -> bool:
    """Return ``True`` if the CDE transition is structurally valid.

    Thin, explainable wrapper over
    :meth:`app.core.cde_states.CDEStateMachine.can_transition`. Role gates are
    not evaluated here; use :func:`transition_check` for a reason string.
    """
    return _state_machine.can_transition(from_state, to_state)


def allowed_transitions(from_state: str) -> list[str]:
    """Return the states reachable in one step from ``from_state``.

    An unknown state yields an empty list rather than raising, so this is safe
    to call on arbitrary data.
    """
    return _state_machine.get_allowed_transitions(from_state)


def transition_check(
    from_state: str,
    to_state: str,
    language: str = DEFAULT_LANGUAGE,
) -> dict[str, Any]:
    """Explain whether a CDE transition is allowed and why.

    Combines the structural check with localized labels so a UI can render both
    ends of the move in the reader's language. Never raises for unknown states;
    an invalid state simply reports ``allowed=False`` with a clear reason.

    Returns:
        A dictionary::

            {
                "from": str, "to": str,
                "allowed": bool,
                "reason": str,               # "ok" or why not
                "from_label": str | None,    # localized, None if unknown state
                "to_label": str | None,
                "next_states": list[str],    # allowed one-step targets
            }
    """
    allowed = _state_machine.can_transition(from_state, to_state)
    if allowed:
        reason = "ok"
    elif not is_known_state(from_state) or not is_known_state(to_state):
        reason = f"Invalid state value: {from_state!r} or {to_state!r}"
    else:
        nxt = _state_machine.get_allowed_transitions(from_state)
        reason = f"Transition {from_state!r} -> {to_state!r} is not allowed. Allowed from {from_state!r}: {nxt}"

    from_label = localize_state(from_state, language) if is_known_state(from_state) else None
    to_label = localize_state(to_state, language) if is_known_state(to_state) else None

    return {
        "from": from_state,
        "to": to_state,
        "allowed": allowed,
        "reason": reason,
        "from_label": from_label,
        "to_label": to_label,
        "next_states": allowed_transitions(from_state),
    }


# ── Aggregate, explainable summary ────────────────────────────────────────


def state_summary(states: Iterable[str], language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
    """Build one explainable, localized summary of a set of container states.

    Bundles the per-state counts, the localized label and explainer for each
    state, and the share-published rate with its components, so a dashboard can
    render an entire CDE overview from a single pure call. Safe on an empty
    input: every figure is well defined and no value is NaN or infinity.

    Args:
        states: An iterable of container ``cde_state`` values.
        language: Display language; unsupported codes fall back to English.

    Returns:
        A dictionary with ``total``, ``by_state`` (count plus localized label
        plus explainer for each canonical state), ``unknown`` count, and
        ``share_published`` (the full :func:`share_published_rate` result).
    """
    counts = count_by_state(states)
    per_state = [
        {
            "state": value,
            "count": counts[value],
            "label": localize_state(value, language),
            "explanation": explain_state(value, language),
        }
        for value in CDE_STATE_ORDER
    ]
    return {
        "total": _sum_known(counts),
        "by_state": per_state,
        "unknown": counts[_UNKNOWN_STATE_KEY],
        "share_published": share_published_rate(counts),
        "language": normalize_language(language),
    }
