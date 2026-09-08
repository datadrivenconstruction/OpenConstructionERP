# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A traced variation line says what it does to its source, and the rule that judges it.

Issue #435. A trace row said where a line of a variation's bill came from and
nothing about what the variation does to that source. A line citing contract
line 020 at 30 m3 could be extra quantity of the same item, a re-measure down
from 40, or the whole item omitted, and the three price differently: an
omission is money coming off the contract. ``change_kind`` is that statement,
made by the estimator, and ``variations.change_kind_matches_numbers`` is the
rule that reports it when it contradicts the line's own numbers or trace.

The rule is exercised in both directions on every clause, because a rule that
fires on everything and one that fires on nothing print the same green line.
Two properties are pinned beyond the individual findings: the rule is a
WARNING and registered under the set the bill view requests, and every message
key resolves in every locale the validation bundle ships, so no finding falls
back to its raw key in the reader's language.

The schema is pinned at the same time: the kind is a closed set, refused
rather than stored when it is anything else, and defaults to ``added`` for the
reason the model gives - a line with no trace is added scope, and a row that
predates the column has to read the same way as no row.

Run (CI):
    cd backend
    python -m pytest tests/unit/test_variation_change_kind_rule.py -v
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.messages import available_locales, is_key_present
from app.modules.variations.schemas import (
    DEFAULT_CHANGE_KIND,
    VariationBOQLineTraceUpdate,
    VariationBOQSourceContractLine,
    VariationBOQSourcePosition,
)
from app.modules.variations.validators import (
    VARIATIONS_RULE_SET,
    VariationBOQChangeKindMatchesNumbers,
    _contradiction,
    register_variations_rules,
)

RULE = "variations.change_kind_matches_numbers"


def _line(
    ordinal: str,
    *,
    quantity: str = "10",
    unit: str = "m3",
    change_kind: str | None = "added",
    contract_line_id: str | None = None,
    source_position_id: str | None = None,
) -> dict[str, Any]:
    """One priced line in the shape the bill view hands the rule set."""
    line: dict[str, Any] = {
        "id": f"pos-{ordinal}",
        "ordinal": ordinal,
        "unit": unit,
        "quantity": quantity,
        "contract_line_id": contract_line_id,
        "source_position_id": source_position_id,
    }
    if change_kind is not None:
        line["change_kind"] = change_kind
    return line


def _context(lines: list[dict[str, Any]]) -> ValidationContext:
    return ValidationContext(data={"lines": lines}, metadata={"locale": "en"})


async def _findings(lines: list[dict[str, Any]]) -> list[RuleResult]:
    results = await VariationBOQChangeKindMatchesNumbers().validate(_context(lines))
    # The rule answers for every priced line so the population is visible
    # next to the verdict; the findings are the failed ones.
    assert len(results) == sum(1 for line in lines if line["unit"] not in ("", "section"))
    return [r for r in results if not r.passed]


# ── An omission is a negative quantity against the schedule of values ───────


@pytest.mark.asyncio
async def test_a_removed_line_with_a_positive_quantity_is_flagged_with_its_quantity() -> None:
    """The contradiction that prices an omission in the contractor's favour."""
    findings = await _findings([_line("0010", quantity="40", change_kind="removed", contract_line_id="cl-1")])

    assert [f.element_ref for f in findings] == ["pos-0010"]
    assert findings[0].severity is Severity.WARNING
    assert "0010" in findings[0].message
    assert "40" in findings[0].message
    assert findings[0].suggestion


@pytest.mark.asyncio
async def test_a_removed_line_with_a_negative_quantity_against_a_contract_line_passes() -> None:
    """The correct shape of an omission, so the rule is not firing on the word alone."""
    assert await _findings([_line("0010", quantity="-40", change_kind="removed", contract_line_id="cl-1")]) == []


@pytest.mark.asyncio
async def test_a_removed_line_that_traces_to_no_contract_line_is_flagged() -> None:
    """Nothing contracted, nothing to remove - even with the sign right and an estimate cited."""
    findings = await _findings([_line("0010", quantity="-40", change_kind="removed", source_position_id="src-1")])

    assert len(findings) == 1
    assert "0010" in findings[0].message


# ── A re-measure keeps the contract line and may go either way ──────────────


@pytest.mark.asyncio
async def test_a_modified_line_passes_in_both_directions_when_it_names_its_contract_line() -> None:
    lines = [
        _line("0010", quantity="-10", change_kind="modified", contract_line_id="cl-1"),
        _line("0020", quantity="10", change_kind="modified", contract_line_id="cl-1"),
    ]

    assert await _findings(lines) == []


@pytest.mark.asyncio
async def test_a_modified_line_that_traces_to_no_contract_line_is_flagged() -> None:
    """The finding the brief asks for by name: modified with nothing contracted behind it."""
    findings = await _findings([_line("0010", quantity="10", change_kind="modified", source_position_id="src-1")])

    assert [f.element_ref for f in findings] == ["pos-0010"]


# ── Added scope goes on, not off ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_added_line_with_a_negative_quantity_is_flagged() -> None:
    findings = await _findings([_line("0010", quantity="-5", change_kind="added")])

    assert [f.element_ref for f in findings] == ["pos-0010"]
    assert "-5" in findings[0].message


@pytest.mark.asyncio
async def test_an_added_line_needs_no_contract_line_and_passes_with_or_without_one() -> None:
    """Extra quantity of a contracted item is an addition too, so citing the line is allowed."""
    lines = [
        _line("0010", quantity="5", change_kind="added"),
        _line("0020", quantity="5", change_kind="added", contract_line_id="cl-1"),
        _line("0030", quantity="5", change_kind="added", source_position_id="src-1"),
    ]

    assert await _findings(lines) == []


# ── Lines nobody has spoken for, and words the schema never let in ──────────


@pytest.mark.asyncio
async def test_a_line_with_no_kind_is_read_as_added() -> None:
    """No trace row is added scope: positive passes, negative is flagged, like an explicit ``added``."""
    assert await _findings([_line("0010", quantity="5", change_kind=None)]) == []

    findings = await _findings([_line("0010", quantity="-5", change_kind=None)])
    assert len(findings) == 1


@pytest.mark.asyncio
async def test_a_kind_the_schema_does_not_know_is_read_as_added_not_as_a_claim() -> None:
    """A value that reached the column by some other path is not a statement about an omission."""
    assert await _findings([_line("0010", quantity="5", change_kind="deleted")]) == []


@pytest.mark.asyncio
async def test_headings_and_unitless_lines_are_not_judged() -> None:
    """Same priced-line test as the two sibling rules, so the three judge one population."""
    lines = [
        _line("01", quantity="0", unit="section", change_kind="removed"),
        _line("0010", quantity="40", unit="", change_kind="removed"),
    ]

    results = await VariationBOQChangeKindMatchesNumbers().validate(_context(lines))
    assert results == []


def test_the_contradiction_table_reports_one_fault_per_line_in_a_fixed_order() -> None:
    """A line wrong twice is one finding, and the money-side fault wins."""
    # Removed, positive AND untraced: the sign is reported, not the missing line.
    assert _contradiction("removed", Decimal("40"), False) == "removed_positive"
    assert _contradiction("removed", Decimal("-40"), False) == "removed_needs_contract_line"
    assert _contradiction("removed", Decimal("-40"), True) is None
    assert _contradiction("modified", Decimal("40"), False) == "modified_needs_contract_line"
    assert _contradiction("modified", Decimal("-40"), True) is None
    assert _contradiction("added", Decimal("-1"), True) == "added_negative"
    assert _contradiction("added", Decimal("0"), False) is None


# ── Registered where the bill view looks, and readable in every locale ──────


def test_the_rule_is_registered_under_the_variations_rule_set() -> None:
    register_variations_rules()
    ids = {rule.rule_id for rule in rule_registry.get_rules_for_sets([VARIATIONS_RULE_SET])}

    assert RULE in ids
    assert rule_registry.get_rule(RULE).severity is Severity.WARNING


@pytest.mark.parametrize(
    "key",
    [
        "removed_positive",
        "added_negative",
        "removed_needs_contract_line",
        "modified_needs_contract_line",
        "suggestion",
    ],
)
def test_every_message_key_resolves_in_every_shipped_locale(key: str) -> None:
    """A finding that falls back to its raw key is a finding nobody can read."""
    locales = available_locales()
    assert "en" in locales
    for locale in locales:
        assert is_key_present(f"variations.change_kind_matches_numbers.{key}", locale), (key, locale)


# ── The schema: a closed set, stated by the estimator, defaulting to added ──


def test_the_kind_is_a_closed_set_on_every_payload_that_carries_it() -> None:
    for model, extra in (
        (VariationBOQLineTraceUpdate, {}),
        (VariationBOQSourceContractLine, {"contract_line_id": "11111111-1111-1111-1111-111111111111"}),
        (VariationBOQSourcePosition, {"position_id": "11111111-1111-1111-1111-111111111111"}),
    ):
        assert model(**extra).change_kind == DEFAULT_CHANGE_KIND == "added"
        for kind in ("added", "removed", "modified"):
            assert model(change_kind=kind, **extra).change_kind == kind
        with pytest.raises(ValidationError):
            model(change_kind="deleted", **extra)
        with pytest.raises(ValidationError):
            model(change_kind="", **extra)
