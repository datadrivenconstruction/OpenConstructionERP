# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Catalog-shape tests for the EAC v2 alias seed (RFC 35 §6 EAC-2.2)."""

from __future__ import annotations

import json
from importlib import resources


def _load_catalog() -> dict:
    ref = resources.files("app.modules.eac.aliases").joinpath(
        "seed_catalog.json",
    )
    return json.loads(ref.read_text(encoding="utf-8"))


def test_catalog_has_40_aliases() -> None:
    """RFC 35 §6 EAC-2.2 mandates exactly 40 canonical aliases."""
    catalog = _load_catalog()
    aliases = catalog["aliases"]
    assert len(aliases) == 40, f"Expected 40 aliases, got {len(aliases)}"


def test_each_alias_has_at_least_9_synonyms() -> None:
    """≥9 synonyms per alias = canonical English + 8 language variants."""
    catalog = _load_catalog()
    for alias in catalog["aliases"]:
        synonyms = alias.get("synonyms") or []
        assert (
            len(synonyms) >= 9
        ), f"{alias['name']} has only {len(synonyms)} synonyms"


def test_no_duplicate_priorities_per_alias() -> None:
    """Within one alias, every synonym priority must be unique.

    Duplicate priorities would make the resolver's "first match wins"
    rule order-dependent and therefore non-deterministic.
    """
    catalog = _load_catalog()
    for alias in catalog["aliases"]:
        priorities = [s["priority"] for s in alias.get("synonyms") or []]
        assert len(priorities) == len(
            set(priorities)
        ), f"{alias['name']} has duplicate priorities: {priorities}"


def test_canonical_names_unique() -> None:
    """Every alias must have a unique canonical name across the catalog."""
    catalog = _load_catalog()
    names = [a["name"] for a in catalog["aliases"]]
    assert len(names) == len(
        set(names)
    ), f"Duplicate canonical names detected: {names}"


def test_each_alias_has_required_fields() -> None:
    """Sanity guard — every entry must carry the fields the migration reads."""
    required_keys = {"name", "value_type_hint", "synonyms"}
    catalog = _load_catalog()
    for alias in catalog["aliases"]:
        missing = required_keys - alias.keys()
        assert not missing, f"{alias.get('name')} missing keys: {missing}"


def test_synonym_patterns_unique_within_alias() -> None:
    """Two identical synonym patterns inside one alias would be redundant."""
    catalog = _load_catalog()
    for alias in catalog["aliases"]:
        patterns = [s["pattern"] for s in alias.get("synonyms") or []]
        assert len(patterns) == len(
            set(patterns)
        ), f"{alias['name']} has duplicate synonym patterns"
