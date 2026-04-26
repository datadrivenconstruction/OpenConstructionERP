# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bulk alias resolver (RFC 35 §6 EAC-2.1).

Given many aliases and a single element, walk the element's property
bag once and resolve every alias against it. The flattening step is
the bottleneck for the per-alias resolver, so amortising it across N
aliases gives roughly an N× speed-up — important when an aggregate
rule references ``_Length``, ``_Width``, ``_Volume``, ``_Material``
all at once.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.modules.eac.aliases.resolver import (
    ElementDict,
    ResolveResult,
    _apply_unit_multiplier,
    _iter_properties,
    _matches_pattern,
    _pset_filter_matches,
    _source_filter_matches,
)


def resolve_bulk(
    aliases: list[Any],
    element: ElementDict,
) -> dict[UUID, ResolveResult]:
    """Resolve every alias in ``aliases`` against ``element``.

    Each alias must expose ``.id`` and ``.synonyms``. The synonyms
    contract matches :func:`resolve_alias`.

    Returns a dict keyed by ``alias.id`` with the resolution result for
    every input alias (matched=False entries are included so callers
    can use the dict directly without ``KeyError`` checks).
    """
    out: dict[UUID, ResolveResult] = {}
    if not aliases:
        return out

    # Flatten properties once. The list is small (typically < 200 entries).
    flat = _iter_properties(element)

    for alias in aliases:
        alias_id = getattr(alias, "id", None)
        synonyms = getattr(alias, "synonyms", None) or []
        if not synonyms:
            out[alias_id] = ResolveResult(matched=False)
            continue

        sorted_syns = sorted(
            synonyms,
            key=lambda s: (
                getattr(s, "priority", 100) is None,
                getattr(s, "priority", 100),
            ),
        )

        winner: ResolveResult = ResolveResult(matched=False)
        for syn in sorted_syns:
            pattern = getattr(syn, "pattern", None)
            if not pattern:
                continue
            kind = getattr(syn, "kind", "exact") or "exact"
            case_sensitive = bool(getattr(syn, "case_sensitive", False))
            pset_filter = getattr(syn, "pset_filter", None)
            source_filter = getattr(syn, "source_filter", "any") or "any"
            multiplier = getattr(syn, "unit_multiplier", 1)

            matched = False
            for pset_name, prop_name, value in flat:
                if not _pset_filter_matches(pset_filter, pset_name):
                    continue
                if not _source_filter_matches(source_filter, pset_name):
                    continue
                if not _matches_pattern(pattern, kind, case_sensitive, prop_name):
                    continue

                converted = _apply_unit_multiplier(value, multiplier)
                winner = ResolveResult(
                    matched=True,
                    matched_synonym_id=getattr(syn, "id", None),
                    raw_value=value,
                    value_after_unit_conversion=converted,
                    pset_name=pset_name,
                )
                matched = True
                break
            if matched:
                break

        out[alias_id] = winner

    return out


__all__ = ["resolve_bulk"]
