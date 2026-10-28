# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The three GESN rules the Russian pack added, and what they decline to judge.

A Russian estimate cites norms rather than describing works, so the rules are
about whether a derivation is present and traceable, not about whether a price
is plausible. Two of them therefore have to be silent far more often than they
speak: a company working to the Russian base still imports plenty of bills that
never came from it, and a rule set that comments on every one of those trains
its reader to close the panel.

The cases below spend more effort on that silence than on the failures, because
the failures are the easy half.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.validation.engine import ValidationContext
from app.core.validation.rules import (
    GESNLabourHoursPresent,
    GESNPriceLevelDeclared,
    GESNResourceBreakdown,
)

LABOUR = {"name": "Рабочий 5 разряда", "unit": "чел.-ч", "quantity": 4.59}
PLANT = {"name": "Кран башенный", "unit": "маш.-ч", "quantity": 1.2}
MATERIAL = {"name": "Бетон B25", "unit": "м3", "quantity": 10.5}


def position(
    *,
    pid: str = "p1",
    code: str | None = "08-04-001-21",
    resources: Any = None,
    namespaced: bool = True,
    is_section: bool = False,
) -> dict[str, Any]:
    """One position in the shape the rules read off a validation context."""
    meta: dict[str, Any] = {}
    if resources is not None:
        if namespaced:
            meta["gesn"] = {"resources": resources}
        else:
            meta["resources"] = resources
    return {
        "id": pid,
        "ordinal": pid,
        "type": "section" if is_section else "item",
        "description": "Устройство перегородок",
        "unit": "м2",
        "quantity": 100.0,
        "unit_rate": 1500.0,
        "classification": {"gesn": code} if code else {},
        "metadata": meta,
    }


def context(positions: list[dict[str, Any]], **meta: Any) -> ValidationContext:
    return ValidationContext(data={"positions": positions}, metadata={"locale": "en", **meta})


# ── The resource decomposition ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_line_that_cites_no_norm_is_not_this_rules_business() -> None:
    """The silence that keeps the rule set readable.

    A Russian company's workspace sees bills imported from everywhere. A line
    with no norm code is not a Russian estimate line missing its resources, it
    is a line from somewhere else, and reporting it says nothing the reader can
    act on.
    """
    results = await GESNResourceBreakdown().validate(context([position(code=None)]))
    assert results == []


@pytest.mark.asyncio
async def test_a_line_citing_a_norm_without_resources_is_reported() -> None:
    results = await GESNResourceBreakdown().validate(context([position()]))
    assert len(results) == 1
    assert not results[0].passed
    assert "08-04-001-21" in results[0].message
    assert results[0].details["resource_count"] == 0


@pytest.mark.asyncio
async def test_a_line_carrying_its_resources_passes() -> None:
    results = await GESNResourceBreakdown().validate(context([position(resources=[LABOUR, PLANT, MATERIAL])]))
    assert results[0].passed
    assert results[0].details["resource_count"] == 3


@pytest.mark.asyncio
async def test_the_decomposition_is_found_whether_or_not_the_import_namespaced_it() -> None:
    """An import that knows it is reading a Russian base puts the block under
    ``gesn``; a generic one leaves it at the top of the metadata. Reading only
    the first would make the rule an assertion about which importer ran."""
    namespaced = await GESNResourceBreakdown().validate(context([position(resources=[LABOUR])]))
    bare = await GESNResourceBreakdown().validate(context([position(resources=[LABOUR], namespaced=False)]))
    assert namespaced[0].passed
    assert bare[0].passed


@pytest.mark.asyncio
@pytest.mark.parametrize("junk", ["", 0, {"labour": 1}, "чел.-ч"])
async def test_a_resource_field_that_is_not_a_list_counts_as_absent(junk: Any) -> None:
    """Distinguishing malformed from missing would report on the importer, and
    the reader of a validation panel cannot act on that."""
    results = await GESNResourceBreakdown().validate(context([position(resources=junk)]))
    assert len(results) == 1
    assert not results[0].passed


@pytest.mark.asyncio
async def test_section_rows_are_not_asked_for_a_decomposition() -> None:
    """A section aggregates its children and consumes nothing itself."""
    rows = [position(pid="header", is_section=True), position(pid="child", resources=[LABOUR])]
    results = await GESNResourceBreakdown().validate(context(rows))
    assert [r.element_ref for r in results] == ["child"]


# ── Labour hours ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_line_with_no_decomposition_is_left_to_the_rule_above() -> None:
    """Both rules firing on one line doubles the finding count and adds no
    finding: the reader still has exactly one thing to do."""
    results = await GESNLabourHoursPresent().validate(context([position()]))
    assert results == []


@pytest.mark.asyncio
async def test_a_decomposition_with_man_hours_passes() -> None:
    results = await GESNLabourHoursPresent().validate(context([position(resources=[LABOUR, MATERIAL])]))
    assert results[0].passed


@pytest.mark.asyncio
@pytest.mark.parametrize("unit", ["чел.-ч", "чел-ч", "чел.ч", "человеко-час", "man-hours", "chel.-ch", "ЧЕЛ.-Ч"])
async def test_the_man_hour_is_recognised_however_it_is_spelled(unit: str) -> None:
    """Three spellings of the same unit are in circulation and a transliterated
    fourth arrives from any exporter that cannot write Cyrillic. Picking one
    and calling the others absent would fail correct estimates."""
    resources = [{"name": "Рабочий", "unit": unit, "quantity": 1.0}]
    results = await GESNLabourHoursPresent().validate(context([position(resources=resources)]))
    assert results[0].passed, f"{unit} was not recognised as a labour unit"


@pytest.mark.asyncio
async def test_plant_and_material_alone_are_reported() -> None:
    """Without man-hours there is no payroll, and without payroll the overhead
    and profit norms have no base to be taken on. This is the one place the
    rule is about arithmetic rather than about tidiness."""
    results = await GESNLabourHoursPresent().validate(context([position(resources=[PLANT, MATERIAL])]))
    assert not results[0].passed
    assert "08-04-001-21" in results[0].message


# ── The price level ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_bill_that_cites_no_norms_is_not_asked_for_a_price_level() -> None:
    """A document-level rule has nothing to attach itself to on a bill that is
    not a Russian estimate, and a finding about a price level on a bill with no
    norm codes reads as the rule set malfunctioning."""
    results = await GESNPriceLevelDeclared().validate(context([position(code=None)]))
    assert results == []


@pytest.mark.asyncio
async def test_a_russian_estimate_without_a_price_level_is_reported_once() -> None:
    """Once, not once per line: the published base carries the level as a
    single document attribute, so it is one fact and one finding."""
    rows = [position(pid=f"p{n}") for n in range(5)]
    results = await GESNPriceLevelDeclared().validate(context(rows))
    assert len(results) == 1
    assert not results[0].passed
    assert results[0].element_ref is None


@pytest.mark.asyncio
@pytest.mark.parametrize("meta", [{"price_level": "01.01.2022"}, {"gesn": {"price_level": "01.01.2022"}}])
async def test_a_declared_price_level_passes_from_either_place(meta: dict[str, Any]) -> None:
    results = await GESNPriceLevelDeclared().validate(context([position()], **meta))
    assert results[0].passed
    assert results[0].details["price_level"] == "01.01.2022"


@pytest.mark.asyncio
@pytest.mark.parametrize("blank", ["", "   ", None])
async def test_a_blank_price_level_is_not_a_declaration(blank: Any) -> None:
    """An empty field reads as a level of nothing. Accepting it would turn the
    rule into a check that somebody had opened the dialogue."""
    results = await GESNPriceLevelDeclared().validate(context([position()], price_level=blank))
    assert not results[0].passed


# ── Where the estimate's own facts actually live ─────────────────────────
#
# The helper above puts them in the run metadata, which is where a test can
# put them and where the product never does: the BOQ validation path fills
# that dict with the request locale and nothing else. A rule reading only
# there can never pass in the product, and a warning nobody can clear teaches
# the reader to skip the rule set. These exercise the bill block, which is
# what the shared payload builder supplies.


def bill(positions: list[dict[str, Any]], **fields: Any) -> ValidationContext:
    """A context shaped like the one the payload builder hands the engine."""
    return ValidationContext(data={"positions": positions, "boq": fields}, metadata={"locale": "en"})


@pytest.mark.asyncio
async def test_a_price_level_recorded_on_the_bill_is_a_declaration() -> None:
    results = await GESNPriceLevelDeclared().validate(bill([position()], metadata={"price_level": "01.01.2022"}))
    assert results[0].passed
    assert results[0].details["price_level"] == "01.01.2022"


@pytest.mark.asyncio
async def test_the_bills_base_date_is_the_price_level_it_is_in() -> None:
    """The bill carries a base date in a column of its own. An estimate that
    states one has said which roubles it is in, and reading only the metadata
    blob would have called that estimate silent."""
    results = await GESNPriceLevelDeclared().validate(bill([position()], base_date="01.01.2022"))
    assert results[0].passed
    assert results[0].details["price_level"] == "01.01.2022"


@pytest.mark.asyncio
async def test_the_bill_outranks_the_run_metadata() -> None:
    """Both are read, and the estimate's own record is the one that counts.
    The run metadata is the caller's, and a caller driving a single rule with
    a fixture is the only thing that puts a price level there."""
    ctx = ValidationContext(
        data={"positions": [position()], "boq": {"metadata": {"price_level": "01.01.2022"}}},
        metadata={"locale": "en", "price_level": "01.01.2000"},
    )
    results = await GESNPriceLevelDeclared().validate(ctx)
    assert results[0].details["price_level"] == "01.01.2022"
