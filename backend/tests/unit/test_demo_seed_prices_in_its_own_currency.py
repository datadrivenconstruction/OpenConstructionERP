# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The demo seed must not print one price under every currency code.

Three blocks in ``demo_projects`` are written once and reused by all thirty-one
packs: the assembly recipes, the plant rates and the resource pool. Their
numbers are euro figures, and they used to be written verbatim whatever the
template said. A square metre of plaster and paint came out at 42.30 in Berlin,
in Sao Paulo, in Delhi and in Dubai, with only the currency code changing, so
the catalogue quietly claimed that a euro, a real and a rupee buy the same
amount of building.

``_DEMO_COST_LEVEL`` fixes that, and these hold it up. Note what the fix is not:
it is not an exchange rate, and the assertions below are written so that nobody
can later mistake it for one and start reconciling it against a live feed. What
is being pinned is that the numbers differ per market, that material and labour
differ from each other, and that the euro projects still read exactly as they
were hand-authored.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from app.core.demo_projects import (
    _DEMO_COST_LEVEL,
    DEMO_TEMPLATES,
    _cost_level,
    _demo_blended_rate,
    _demo_rate,
    _generate_module_data,
)

SEEDER = Path(__file__).resolve().parents[2] / "app" / "core" / "demo_projects.py"
PACK_DIR = Path(__file__).resolve().parents[2] / "app" / "core" / "demo_packs"

# The recipe that made the defect visible: it is the cheapest of the three and
# the one whose total, 42.30, appeared on seven currencies at once.
PLASTER = (("material", 1.0, 9.0), ("labor", 0.7, 44.0), ("equipment", 0.1, 25.0))


def _recipe_total(currency: str) -> float:
    return round(sum(qty * _demo_rate(rate, currency, kind) for kind, qty, rate in PLASTER), 2)


def _module_rows(currency: str) -> dict[str, float]:
    """Run the real generator on one template and return its resource rates."""
    template = replace(DEMO_TEMPLATES["residential-berlin"], currency=currency)
    generated = _generate_module_data(
        template,
        uuid.UUID("00000000-0000-0000-0000-0000000000aa"),
        uuid.UUID("00000000-0000-0000-0000-0000000000bb"),
        "residential-berlin",
        datetime(2026, 1, 5),
    )
    return {r["name"]: float(r["rate"]) for r in generated["resources"]}


def test_the_same_recipe_is_a_different_number_in_a_different_currency() -> None:
    totals = {code: _recipe_total(code) for code in _DEMO_COST_LEVEL}
    assert totals["EUR"] == 42.30, "the euro total is the hand-authored figure and must not move"
    # The defect was one number under every code, so the falsifying observation
    # is any two markets agreeing. Compared as a set rather than pairwise: a
    # single collision is the whole failure, and reporting which one it is
    # matters more than the count.
    collisions = sorted(code for code, total in totals.items() if code != "EUR" and total == totals["EUR"])
    assert not collisions, f"these currencies still print the euro figure {totals['EUR']}: {collisions}"
    assert len(set(totals.values())) >= 10, (
        f"thirteen markets collapsed to {len(set(totals.values()))} distinct totals: {totals}"
    )


def test_material_and_labour_do_not_move_together() -> None:
    """One blended factor per currency would be wrong in both directions.

    The Gulf is the case that proves it and the reason the table has two
    columns: cement arrives at world prices while crews are hired well below
    German wages, so material has to rise in the same market where labour
    falls. A single factor cannot do that, and a test that only checked
    "the number changed" would pass on one.
    """
    split = {
        code: (_cost_level(code, "material"), _cost_level(code, "labor")) for code in _DEMO_COST_LEVEL if code != "EUR"
    }
    assert all(mat != lab for mat, lab in split.values()), (
        f"a currency levels material and labour identically, which is a blended factor: {split}"
    )
    for code in ("AED", "SAR"):
        material, labour = split[code]
        assert material > 1.0 > labour, (
            f"{code} is in the table to hold the opposite-direction case, and it now moves both ways together: "
            f"material {material}, labour {labour}"
        )


def test_the_euro_projects_keep_the_numbers_they_were_hand_authored_with() -> None:
    """EUR is the base, so every euro literal has to survive untouched.

    Eight packs and three of the five built-in templates are euro projects.
    A levelling pass that shifted them would be rewriting figures a person
    chose, which is the one thing this change is not allowed to do.
    """
    for value in (9.0, 1.35, 44.0, 118.0, 980.0, 95.0):
        for kind in ("material", "labor", "equipment", "person"):
            assert _demo_rate(value, "EUR", kind) == value, f"EUR moved {value} on a {kind} line"


def test_an_unrecognised_currency_leaves_the_literal_alone() -> None:
    """A pack for a market with no row must still seed, at the euro figures.

    Falling back to 1.0 rather than raising is deliberate: these helpers run
    inside best-effort seed blocks, and a pack landing before its row does
    should install with euro-shaped numbers rather than not install at all.
    """
    for unknown in ("", "   ", "XYZ", "not a currency"):
        assert _demo_rate(118.0, unknown, "material") == 118.0, f"{unknown!r} scaled a material literal"
        assert _demo_rate(48.0, unknown, "labor") == 48.0, f"{unknown!r} scaled a labour literal"
    assert _demo_rate(None, "INR", "material") == 0.0, "a non-numeric literal must not raise inside a seed block"


def test_every_currency_a_pack_declares_has_a_level() -> None:
    """Counted from the packs, not from a list kept beside them.

    A census that reads its own list of currencies is blind to the currency
    that is not on it, which is exactly what a new pack brings. So the packs
    on disk are the input, and the count they yielded is printed on the way
    past: nought offenders out of nought files read the same as nought
    offenders out of thirty-one.
    """
    pack_files = sorted(PACK_DIR.glob("*.py"))
    assert len(pack_files) > 20, f"only {len(pack_files)} pack files found; this census is reading the wrong folder"
    declared: dict[str, str] = {}
    for path in pack_files:
        for code in re.findall(r'currency="([A-Z]{3})"', path.read_text(encoding="utf-8")):
            declared.setdefault(code, path.name)
    for demo_id, template in DEMO_TEMPLATES.items():
        declared.setdefault(template.currency, demo_id)
    assert len(declared) >= 13, f"read {len(pack_files)} pack files and found only {len(declared)} currencies"
    missing = sorted(code for code in declared if code not in _DEMO_COST_LEVEL)
    assert not missing, (
        f"{len(pack_files)} packs declare {len(declared)} currencies and these have no cost level, so their "
        f"projects would seed at German prices: {[(c, declared[c]) for c in missing]}"
    )


@pytest.mark.parametrize("currency", sorted(_DEMO_COST_LEVEL))
def test_the_resource_pool_comes_out_of_the_generator_in_its_own_currency(currency: str) -> None:
    """End to end through the real generator, not through the helper alone.

    A table nothing calls is worth nothing, so this drives
    ``_generate_module_data`` with a real template and reads what it returns.
    The Berlin pack is used with only ``currency`` replaced, so anything that
    differs between the two runs came from the levelling.
    """
    euro = _module_rows("EUR")
    rows = _module_rows(currency)
    assert rows["Project Manager"] == pytest.approx(_demo_rate(95.0, currency, "person"))
    assert rows["Tower crane"] == pytest.approx(_demo_rate(120.0, currency, "equipment"))
    assert rows["Excavator"] == pytest.approx(_demo_rate(85.0, currency, "equipment"))
    if currency != "EUR":
        assert rows["Project Manager"] != euro["Project Manager"], f"{currency} pays the German day rate"
    # Subcontractor rows are priced by their agreements, not by a pool rate.
    subcontractors = [name for name, rate in rows.items() if rate == 0.0]
    assert len(subcontractors) == 3, f"the three subcontractor rows must stay at zero, got {subcontractors}"


def test_dubai_hires_below_berlin_while_paying_more_for_the_machine() -> None:
    """The opposite-direction case, read off the generator's real output.

    ``test_material_and_labour_do_not_move_together`` checks the table. This
    checks that the split survives the call site: the resource pool asks for
    "person" and "equipment", two words neither of which is "labor", and a
    wiring that sent both down one branch would still pass every assertion
    about the table itself.
    """
    berlin = _module_rows("EUR")
    dubai = _module_rows("AED")
    assert dubai["Site Manager"] < berlin["Site Manager"], (
        "AED labour is levelled below EUR in the table; the resource pool is not reading that column"
    )
    assert dubai["Tower crane"] > berlin["Tower crane"], (
        "plant follows the material factor, which is above EUR for AED; the pool sent it down the labour branch"
    )


def test_a_whole_of_works_figure_lands_between_the_two_columns() -> None:
    """Contract sums are a mix, so neither column alone can be right for them.

    The rule is the mean, which is checkable: whatever the two columns are, a
    blended figure has to sit between them and has to move when they do. That
    is worth asserting rather than the constant, because the constant is the
    thing somebody may reasonably retune.
    """
    for code, (material, labour) in _DEMO_COST_LEVEL.items():
        blended = _demo_blended_rate(1000.0, code)
        low, high = sorted((material * 1000.0, labour * 1000.0))
        assert low <= blended <= high, f"{code} blends to {blended}, outside its own columns {low}..{high}"
    assert _demo_blended_rate(50000.0, "EUR") == 50000.0, "the euro base moved on a whole-of-works figure"
    assert _demo_blended_rate(50000.0, "XYZ") == 50000.0, "an unknown currency scaled a whole-of-works figure"
    assert _demo_blended_rate(None, "INR") == 0.0, "a non-numeric figure must not raise inside a seed block"
    assert _demo_blended_rate(50000.0, "INR") > _demo_blended_rate(50000.0, "EUR"), (
        "a rupee contract has to be a bigger number than its euro twin"
    )


def test_the_shared_recipe_and_plant_blocks_route_through_the_level() -> None:
    """Source pins for the two call sites no unit test can reach.

    The assembly and equipment blocks live inside ``_seed_module_data``, an
    async routine that writes every module against a live session and cannot be
    entered for one block. So these read the source, which is a poor substitute
    for calling it and is what is available. They are worth having because the
    failure they guard is silent: drop the call and the seed keeps working,
    keeps its currency codes, and goes back to one price everywhere.
    """
    source = SEEDER.read_text(encoding="utf-8")
    assert "c_rate = _demo_rate(c_cost, _ccy, c_type)" in source, "assembly components no longer level their unit cost"
    assert "unit_cost=str(c_cost)" not in source, "an assembly component writes the raw euro literal again"
    assert '_demo_rate(day_rate, _ccy, "equipment")' in source, "the plant day rate is written unlevelled"
    assert '_demo_rate(hour_rate, _ccy, "equipment")' in source, "the plant hour rate is written unlevelled"
    assert "i * _demo_blended_rate(50000.0, cur)" in source, (
        "the subcontract stagger is a euro-sized step again, which is the one whole-of-works site that fires on "
        "every project rather than only on a template with no priced items"
    )
    assert "NOT AN EXCHANGE RATE" in source, (
        "the table lost the line that stops a reader treating it as FX; it is a demo-data device and has to say so"
    )
