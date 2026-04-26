# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests for the EAC v2 parameter-alias resolver (RFC 35 §6 EAC-2.1).

The resolver is intentionally pure (no DB) so we drive it with simple
duck-typed namespaces — no pytest-asyncio, no SQLAlchemy session.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import pytest

from app.modules.eac.aliases.resolver import ResolveResult, resolve_alias


@dataclass
class _Synonym:
    pattern: str
    priority: int = 100
    kind: str = "exact"
    case_sensitive: bool = False
    pset_filter: str | None = None
    source_filter: str = "any"
    unit_multiplier: Decimal | float = 1
    id: uuid.UUID = field(default_factory=uuid.uuid4)


@dataclass
class _Alias:
    name: str = "_Length"
    value_type_hint: str = "number"
    default_unit: str | None = "m"
    id: uuid.UUID = field(default_factory=uuid.uuid4)


# ── Tests ────────────────────────────────────────────────────────────────


def test_resolve_finds_first_priority_match() -> None:
    """Synonyms are tried in priority order — the priority-20 one should win."""
    alias = _Alias()
    syns = [
        _Synonym(pattern="A", priority=10),  # not present in element
        _Synonym(pattern="B", priority=20),  # present — wins
        _Synonym(pattern="C", priority=30),  # also present, lower priority
    ]
    element: dict[str, Any] = {"properties": {"B": "match-B", "C": "match-C"}}

    result = resolve_alias(alias, syns, element)
    assert result.matched is True
    assert result.matched_synonym_id == syns[1].id
    assert result.raw_value == "match-B"


def test_resolve_unit_multiplier_applied() -> None:
    """``length_mm`` synonym with multiplier 0.001 should report metres."""
    alias = _Alias()
    syns = [
        _Synonym(
            pattern="length_mm",
            priority=10,
            unit_multiplier=Decimal("0.001"),
        ),
    ]
    element = {"properties": {"length_mm": 2500}}

    result = resolve_alias(alias, syns, element)
    assert result.matched is True
    assert result.raw_value == 2500
    # 2500 * 0.001 == 2.5 in metres.
    assert result.value_after_unit_conversion == pytest.approx(2.5)


def test_resolve_pset_filter_narrows_search() -> None:
    """A pset_filter forces the synonym to only match inside the named pset."""
    alias = _Alias()
    syns = [
        _Synonym(
            pattern="FireRating",
            priority=10,
            pset_filter="Pset_WallCommon",
        ),
    ]
    element = {
        "properties": {
            "Pset_DoorCommon": {"FireRating": "F30"},
            "Pset_WallCommon": {"FireRating": "F90"},
        }
    }

    result = resolve_alias(alias, syns, element)
    assert result.matched is True
    assert result.raw_value == "F90"
    assert result.pset_name == "Pset_WallCommon"


def test_resolve_regex_kind() -> None:
    """A regex synonym should match any property name satisfying the pattern."""
    alias = _Alias()
    syns = [
        _Synonym(
            pattern=r"_(Length|Longueur).*",
            priority=10,
            kind="regex",
        ),
    ]
    element = {"properties": {"_LengthMM": 1500}}

    result = resolve_alias(alias, syns, element)
    assert result.matched is True
    assert result.raw_value == 1500


def test_resolve_case_sensitive_default_off() -> None:
    """case_sensitive defaults to False — `LENGTH` matches `Length`."""
    alias = _Alias()
    syn_insensitive = _Synonym(pattern="Length", priority=10)
    syn_sensitive = _Synonym(pattern="Length", priority=10, case_sensitive=True)
    element = {"properties": {"LENGTH": 12.5}}

    insensitive = resolve_alias(alias, [syn_insensitive], element)
    assert insensitive.matched is True
    assert insensitive.raw_value == 12.5

    sensitive = resolve_alias(alias, [syn_sensitive], element)
    assert sensitive.matched is False


def test_resolve_no_synonyms_returns_unmatched() -> None:
    """An empty synonym list short-circuits without scanning the element."""
    alias = _Alias()
    result = resolve_alias(alias, [], {"properties": {"Length": 1.0}})
    assert result == ResolveResult(matched=False)


def test_resolve_handles_both_nested_and_flat_properties() -> None:
    """The resolver accepts both nested-pset and flat property bags."""
    alias = _Alias()
    syns = [_Synonym(pattern="Length", priority=10)]

    flat = {"properties": {"Length": 3.0}}
    nested = {"properties": {"Pset_Common": {"Length": 4.5}}}

    flat_res = resolve_alias(alias, syns, flat)
    nested_res = resolve_alias(alias, syns, nested)

    assert flat_res.matched is True
    assert flat_res.raw_value == 3.0
    assert flat_res.pset_name is None

    assert nested_res.matched is True
    assert nested_res.raw_value == 4.5
    assert nested_res.pset_name == "Pset_Common"


def test_resolve_50_synonyms_under_10ms() -> None:
    """50 synonyms × 100-property element must resolve under 10 ms (RFC 35)."""
    alias = _Alias()
    # 50 synonyms — last one matches.
    syns = [
        _Synonym(pattern=f"NoMatch{idx}", priority=idx)
        for idx in range(49)
    ]
    syns.append(_Synonym(pattern="WinningProp", priority=999))

    element = {
        "properties": {f"prop_{idx}": idx for idx in range(99)}
        | {"WinningProp": "found"}
    }

    # Warm up so JIT/page-faults don't dominate.
    resolve_alias(alias, syns, element)

    iterations = 50
    start = time.perf_counter()
    for _ in range(iterations):
        result = resolve_alias(alias, syns, element)
    duration_ms = (time.perf_counter() - start) * 1000 / iterations

    assert result.matched is True
    assert result.raw_value == "found"
    # Generous bound — actual is well under 1 ms; 10 ms is the spec ceiling.
    assert duration_ms < 10, f"Resolver too slow: {duration_ms:.3f}ms/call"
