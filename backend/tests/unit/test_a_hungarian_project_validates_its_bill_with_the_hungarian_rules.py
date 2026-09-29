# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A Hungarian project's bill is checked by the Hungarian rules, whatever the pack.

The classification a Hungarian bill is written against is registered as
``tetelrend`` and the rule set that checks it is registered as ``hungary``.
The rule-set builder mapped classification standards and countries to rule
sets and had neither: a Hungarian project got the Hungarian rules only when the
country pack was active at the moment it was created, and imported every bill
without them otherwise. The engine logs an unknown rule set and carries on, so
a table entry naming a set that does not exist is just as quiet, which is why
every value in both tables is held against what the engine registers.
"""

from __future__ import annotations

import pytest

from app.core.validation.engine import rule_registry
from app.modules.boq.router import _COUNTRY_RULE_SETS, _STANDARD_RULE_SETS, _build_rule_sets


def _registered() -> set[str]:
    return set(rule_registry.list_rule_sets())


def test_the_hungarian_classification_brings_the_hungarian_rule_set() -> None:
    assert "hungary" in _build_rule_sets(["boq_quality"], "tetelrend", "")


@pytest.mark.parametrize("region", ["HU", "hu", "HU_BUDAPEST"])
def test_a_hungarian_region_brings_the_hungarian_rule_set(region: str) -> None:
    assert "hungary" in _build_rule_sets(["boq_quality"], "", region)


def test_the_country_column_answers_when_the_region_names_no_country() -> None:
    assert "hungary" in _build_rule_sets(["boq_quality"], "", "", country_code="HU")
    assert "hungary" not in _build_rule_sets(["boq_quality"], "", "", country_code=None)


def test_the_rule_set_is_added_once() -> None:
    rule_sets = _build_rule_sets(["boq_quality", "hungary"], "tetelrend", "HU")
    assert rule_sets.count("hungary") == 1


def test_the_region_still_decides_before_the_country_column() -> None:
    rule_sets = _build_rule_sets(["boq_quality"], "", "DE", country_code="HU")
    assert "din276" in rule_sets
    assert "hungary" not in rule_sets


def test_every_rule_set_a_classification_standard_asks_for_is_registered() -> None:
    missing = {standard: name for standard, name in _STANDARD_RULE_SETS.items() if name not in _registered()}
    assert missing == {}


def test_every_rule_set_a_country_asks_for_is_registered() -> None:
    registered = _registered()
    missing = {
        country: [name for name in names if name not in registered]
        for country, names in _COUNTRY_RULE_SETS.items()
        if any(name not in registered for name in names)
    }
    assert missing == {}


def test_the_hungarian_rule_set_is_not_registered_under_the_classification_name() -> None:
    """Guards the test above: if both names were registered the trap would be invisible."""
    registered = _registered()
    assert "hungary" in registered
    assert "tetelrend" not in registered
