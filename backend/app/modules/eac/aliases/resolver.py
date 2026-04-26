# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure alias resolver (RFC 35 §6 EAC-2.1).

The resolver maps a canonical alias (e.g. ``_Length``) onto a value
inside an element's property bag, trying each synonym pattern in
priority order. The first match wins.

Inputs are plain Python objects (no DB session, no Pydantic models on
the hot path) so the resolver stays trivially testable and reusable
from inside DuckDB UDFs in EAC-1.4.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

# Local type aliases — kept narrow on purpose so the resolver doesn't
# accidentally pull SQLAlchemy into a hot path.
PropertyBag = dict[str, Any]
ElementDict = dict[str, Any]


@dataclass(frozen=True)
class ResolveResult:
    """Outcome of resolving an alias against an element."""

    matched: bool
    matched_synonym_id: UUID | None = None
    raw_value: Any = None
    value_after_unit_conversion: Any = None
    pset_name: str | None = None


# ── Internal helpers ────────────────────────────────────────────────────


def _iter_properties(element: ElementDict) -> list[tuple[str | None, str, Any]]:
    """Yield ``(pset_name, prop_name, value)`` for every property in element.

    Handles both shapes used across the codebase per W0.2 ddc_extras:

    * Nested:  ``{"properties": {"Pset_WallCommon": {"FireRating": "F90"}}}``
    * Flat:    ``{"properties": {"FireRating": "F90"}}``

    A *flat* leaf has ``pset_name=None`` so a synonym with
    ``pset_filter`` won't match it (psets must be explicitly nested).

    The function is tolerant of missing or non-dict ``properties`` —
    callers don't have to pre-validate.
    """
    out: list[tuple[str | None, str, Any]] = []
    props = element.get("properties")
    if not isinstance(props, dict):
        return out

    for key, value in props.items():
        if isinstance(value, dict):
            # Nested pset: {"Pset_X": {"PropA": ..., "PropB": ...}}
            for prop_name, prop_value in value.items():
                out.append((key, prop_name, prop_value))
        else:
            # Flat property at the root.
            out.append((None, key, value))
    return out


def _pset_filter_matches(synonym_filter: str | None, pset_name: str | None) -> bool:
    """Return True if the synonym's pset filter accepts ``pset_name``.

    Treat ``synonym_filter is None`` as "match anywhere". When set, we
    accept exact equality OR a regex match against the pset name.
    Flat properties (``pset_name is None``) only match when no filter
    is configured.
    """
    if synonym_filter is None:
        return True
    if pset_name is None:
        return False
    if synonym_filter == pset_name:
        return True
    try:
        return bool(re.fullmatch(synonym_filter, pset_name))
    except re.error:
        return False


def _source_filter_matches(synonym_filter: str, pset_name: str | None) -> bool:
    """Return True if the synonym's source filter accepts the property's origin.

    EAC-2.1 surfaces a coarse three-way split inferred from where the
    property lives in the element dict:

    * ``any``                       — every property qualifies
    * ``pset``                      — only properties nested under a pset
    * ``instance`` / ``type``       — flat properties (best-effort —
      heuristics deferred to EAC-2.2 once ddc_extras tags origin)
    * ``external_classification``   — properties whose pset_name starts
      with ``Classification`` (heuristic, refined later)
    """
    if synonym_filter == "any":
        return True
    if synonym_filter == "pset":
        return pset_name is not None
    if synonym_filter in ("instance", "type"):
        return pset_name is None
    if synonym_filter == "external_classification":
        return pset_name is not None and pset_name.lower().startswith(
            "classification",
        )
    # Unknown filter values fall through to permissive behaviour rather
    # than failing closed so an out-of-band string doesn't break a run.
    return True


def _matches_pattern(
    pattern: str,
    kind: str,
    case_sensitive: bool,
    candidate: str,
) -> bool:
    """Return True if ``candidate`` satisfies ``pattern`` under ``kind``."""
    if kind == "exact":
        if case_sensitive:
            return pattern == candidate
        return pattern.lower() == candidate.lower()
    if kind == "regex":
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            return bool(re.fullmatch(pattern, candidate, flags))
        except re.error:
            return False
    # Unknown kinds never match — fail closed.
    return False


def _apply_unit_multiplier(value: Any, multiplier: Decimal | float) -> Any:
    """Multiply numeric ``value`` by ``multiplier``; pass non-numerics through."""
    if multiplier in (1, 1.0, Decimal("1")):
        return value
    if isinstance(value, bool):
        # bool is a subclass of int — explicitly preserve it.
        return value
    if isinstance(value, (int, float)):
        return float(Decimal(str(value)) * Decimal(str(multiplier)))
    if isinstance(value, Decimal):
        return value * Decimal(str(multiplier))
    return value


# ── Public API ──────────────────────────────────────────────────────────


def resolve_alias(
    alias: Any,
    synonyms: list[Any],
    element: ElementDict,
) -> ResolveResult:
    """Resolve ``alias`` against ``element`` using ``synonyms``.

    The function does not touch the DB — both ``alias`` and ``synonyms``
    must be objects that expose attributes by name (ORM rows, dataclasses,
    or duck-typed namespaces all work).

    Args:
        alias:     Anything with ``.id`` and (optionally) ``.value_type_hint``.
                   Currently unused for branching, but kept for forward
                   compatibility with type-aware coercion.
        synonyms:  Iterable of objects exposing ``.id``, ``.pattern``,
                   ``.kind`` (exact|regex), ``.case_sensitive``,
                   ``.priority``, ``.pset_filter``, ``.source_filter``,
                   ``.unit_multiplier``.
        element:   ``{"properties": {...}, ...}`` — both nested-pset and
                   flat shapes supported.

    Returns:
        :class:`ResolveResult` with ``matched=True`` on the first
        winning synonym (lowest priority), or ``matched=False`` when
        no synonym matches.
    """
    # Defensive: alias is unused but required by the contract; keep
    # the reference visible to silence linters and document intent.
    _ = alias

    if not synonyms:
        return ResolveResult(matched=False)

    # Sort by priority asc — None last so deterministic.
    sorted_synonyms = sorted(
        synonyms,
        key=lambda s: (getattr(s, "priority", 100) is None, getattr(s, "priority", 100)),
    )
    properties = _iter_properties(element)

    for syn in sorted_synonyms:
        pattern = getattr(syn, "pattern", None)
        if not pattern:
            continue
        kind = getattr(syn, "kind", "exact") or "exact"
        case_sensitive = bool(getattr(syn, "case_sensitive", False))
        pset_filter = getattr(syn, "pset_filter", None)
        source_filter = getattr(syn, "source_filter", "any") or "any"
        multiplier = getattr(syn, "unit_multiplier", 1)

        for pset_name, prop_name, value in properties:
            if not _pset_filter_matches(pset_filter, pset_name):
                continue
            if not _source_filter_matches(source_filter, pset_name):
                continue
            if not _matches_pattern(pattern, kind, case_sensitive, prop_name):
                continue

            converted = _apply_unit_multiplier(value, multiplier)
            return ResolveResult(
                matched=True,
                matched_synonym_id=getattr(syn, "id", None),
                raw_value=value,
                value_after_unit_conversion=converted,
                pset_name=pset_name,
            )

    return ResolveResult(matched=False)


__all__ = ["ResolveResult", "resolve_alias"]
