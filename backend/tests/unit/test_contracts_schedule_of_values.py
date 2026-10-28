# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The arithmetic a schedule of values has to close.

A schedule of values is a promise about money: these lines, at these rates,
for these quantities, add up to what the contract is worth. Every assertion
here is about that promise holding exactly rather than nearly, because a
continuation sheet that is a few cents out is a continuation sheet a quantity
surveyor stops trusting, and a line whose total is not its own rate times its
own quantity cannot be defended at all.

No database is touched: the arithmetic lives in pure functions precisely so
it can be proven without one.
"""

from __future__ import annotations

import random
from decimal import Decimal

import pytest

from app.core.demo_showcase import GERMAN_SHOWCASE_DEMO_IDS
from app.modules.contracts.seed import (
    _DE_KG_LADDER,
    _DE_LV_LADDER,
    _DE_TRADES,
    _GERMAN_CONTRACT_PROJECTS,
    _SOV_MEASURED,
    _SOV_SECTIONAL,
    apportion_claim,
    build_schedule_of_values,
    build_schedule_of_values_de,
    pick_german_shape,
    split_to_cents,
)

# A spread of contract sums: a small subcontract, an awkward one that does not
# divide, a large head contract, and one carrying odd cents.
CONTRACT_VALUES = [
    Decimal("120000.00"),
    Decimal("437291.37"),
    Decimal("1000000.00"),
    Decimal("42875193.11"),
    Decimal("7777.77"),
]

CONTRACT_TYPES = ["lump_sum", "remeasurement", "gmp", "unit_price", "design_build"]


def _rng(tag: str = "test") -> random.Random:
    return random.Random(f"contract-lines:{tag}")


# ── The split ────────────────────────────────────────────────────────────


def test_the_parts_re_add_to_the_whole() -> None:
    parts = split_to_cents(Decimal("1000.00"), [Decimal("1"), Decimal("1"), Decimal("1")])

    # A third of a thousand does not exist in cents, so this is the case that
    # would silently lose a cent if the remainder were dropped.
    assert sum(parts) == Decimal("1000.00")


def test_the_remainder_lands_on_the_narrowest_part() -> None:
    parts = split_to_cents(Decimal("100.00"), [Decimal("50"), Decimal("50"), Decimal("1")])

    assert sum(parts) == Decimal("100.00")
    # Each share rounds down to 49.50 / 49.50 / 0.99, a cent short. The
    # smallest weight carries the correction, not one of the broad lines.
    assert parts == [Decimal("49.50"), Decimal("49.50"), Decimal("1.00")]


def test_weights_that_sum_to_nothing_are_refused() -> None:
    with pytest.raises(ValueError, match="more than zero"):
        split_to_cents(Decimal("100.00"), [Decimal("0"), Decimal("0")])


def test_no_weights_is_no_parts() -> None:
    assert split_to_cents(Decimal("100.00"), []) == []


# ── The schedule ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("value", CONTRACT_VALUES)
@pytest.mark.parametrize("contract_type", CONTRACT_TYPES)
def test_the_schedule_sums_to_the_contract_value(value: Decimal, contract_type: str) -> None:
    """The headline promise, across every priced shape and size."""
    lines = build_schedule_of_values(value, contract_type, _rng(contract_type))

    assert lines, f"{contract_type} at {value} produced no schedule"
    assert sum(line.total_value for line in lines) == value


@pytest.mark.parametrize("value", CONTRACT_VALUES)
@pytest.mark.parametrize("contract_type", CONTRACT_TYPES)
def test_no_line_total_can_disagree_with_its_own_rate_and_quantity(value: Decimal, contract_type: str) -> None:
    """A stored total that its own rate and quantity do not produce is a lie."""
    lines = build_schedule_of_values(value, contract_type, _rng(contract_type))

    for line in lines:
        assert line.total_value == line.quantity * line.unit_rate, (
            f"{line.code} {line.description}: {line.quantity} x {line.unit_rate} != {line.total_value}"
        )


@pytest.mark.parametrize("contract_type", CONTRACT_TYPES)
def test_every_line_is_worth_something(contract_type: str) -> None:
    lines = build_schedule_of_values(Decimal("850000.00"), contract_type, _rng(contract_type))

    assert all(line.total_value > 0 for line in lines)
    assert all(line.quantity > 0 for line in lines)
    assert all(line.unit_rate > 0 for line in lines)


def test_a_remeasured_contract_is_measured_and_a_lump_one_is_sectioned() -> None:
    """The shape follows how the contract is priced, not one generic list."""
    measured = build_schedule_of_values(Decimal("500000.00"), "remeasurement", _rng("m"))
    sectional = build_schedule_of_values(Decimal("500000.00"), "lump_sum", _rng("s"))

    assert [line.description for line in measured] != [line.description for line in sectional]
    # A remeasured contract is billed against what was built, so most of its
    # lines carry a real unit rather than being priced as a lump.
    measured_units = [line.unit for line in measured if line.unit != "lsum"]
    assert len(measured_units) >= len(measured) - 2


def test_the_schedule_is_the_same_every_time_it_is_built() -> None:
    """A demo estate that reshuffles on every re-seed cannot be filmed."""
    first = build_schedule_of_values(Decimal("640000.00"), "lump_sum", _rng("same"))
    second = build_schedule_of_values(Decimal("640000.00"), "lump_sum", _rng("same"))

    assert [(line.code, line.quantity, line.unit_rate) for line in first] == [
        (line.code, line.quantity, line.unit_rate) for line in second
    ]


@pytest.mark.parametrize("value", [Decimal("0"), Decimal("-1000.00")])
def test_a_contract_with_nothing_to_break_down_gets_no_schedule(value: Decimal) -> None:
    """Better no schedule than an invented one. The caller counts these."""
    assert build_schedule_of_values(value, "lump_sum", _rng()) == []


def test_the_rates_stay_believable_at_both_ends_of_the_scale() -> None:
    """A quantity worked back from a rate band is the point of that band.

    Fixing quantities instead would price a cubic metre of concrete at four
    figures on a large job and at pennies on a small one.
    """
    bands = {
        "Excavation and earthworks": (Decimal("20"), Decimal("48")),
        "Concrete placement and curing": (Decimal("120"), Decimal("230")),
        "Reinforcement supply and fixing": (Decimal("1.2"), Decimal("2.6")),
    }
    small = build_schedule_of_values(Decimal("120000.00"), "remeasurement", _rng("small"))
    large = build_schedule_of_values(Decimal("42875193.11"), "remeasurement", _rng("large"))

    for lines in (small, large):
        for line in lines:
            band = bands.get(line.description)
            if band is None:
                continue
            low, high = band
            assert low <= line.unit_rate <= high, f"{line.description} priced at {line.unit_rate}"


# ── The claim breakdown ──────────────────────────────────────────────────


def test_a_claim_is_placed_in_full_when_there_is_room() -> None:
    capacities = [Decimal("1000.00"), Decimal("2000.00"), Decimal("3000.00")]

    amounts = apportion_claim(Decimal("2500.00"), capacities)

    assert sum(amounts) == Decimal("2500.00")
    # Filled in schedule order: the first line closes out, the second takes
    # the rest, the third has not started.
    assert amounts == [Decimal("1000.00"), Decimal("1500.00"), Decimal("0")]


def test_no_line_is_ever_billed_past_its_scheduled_value() -> None:
    capacities = [Decimal("500.00"), Decimal("500.00")]

    amounts = apportion_claim(Decimal("5000.00"), capacities)

    assert all(amount <= capacity for amount, capacity in zip(amounts, capacities, strict=True))
    # The shortfall is visible rather than forced onto a line that has no room.
    assert sum(amounts) == Decimal("1000.00")


def test_a_line_already_full_is_skipped_not_stalled_on() -> None:
    capacities = [Decimal("0"), Decimal("750.00")]

    amounts = apportion_claim(Decimal("400.00"), capacities)

    assert amounts == [Decimal("0"), Decimal("400.00")]


def test_a_claim_run_fills_the_schedule_and_never_overruns_it() -> None:
    """The whole run, not one claim: the cumulative figure is what a G703 prints."""
    schedule = build_schedule_of_values(Decimal("900000.00"), "lump_sum", _rng("run"))
    capacities = [line.total_value for line in schedule]
    billed = [Decimal("0")] * len(schedule)

    # Six periods at 8% of the contract each, the shape the claims seeder writes.
    for _ in range(6):
        remaining = [capacity - done for capacity, done in zip(capacities, billed, strict=True)]
        amounts = apportion_claim(Decimal("72000.00"), remaining)
        assert sum(amounts) == Decimal("72000.00")
        billed = [done + amount for done, amount in zip(billed, amounts, strict=True)]

    assert sum(billed) == Decimal("432000.00")
    assert all(done <= capacity for done, capacity in zip(billed, capacities, strict=True))


# ── The German schedule ──────────────────────────────────────────────────
#
# The filmed demo projects carry German contracts, and a continuation sheet
# reading "Substructure and foundations" under "Subcontract - Baugrube /
# Erdbau" is the most visible half-translated thing on the screen. These
# assert that the German catalogue is reached, that it is chosen by the trade
# the contract names, and that it closes the same arithmetic as the English.

#: Titles exactly as the demo estate writes them, company names included,
#: because the company name is the part that misleads a naive match.
DE_TITLES = [
    ("Main construction contract - Bürogebäude Frankfurt Europaviertel", "office-frankfurt"),
    ("Subcontract - Baugrube / Erdbau (Rahnstett Bau Hessen GmbH)", "office-frankfurt"),
    ("Subcontract - Gründung, Unterbau (Wehrsen & Talbrunn GmbH & Co. KG)", "office-frankfurt"),
    (
        "Subcontract - Außenwände / vertikale Baukonstruktionen, außen (Adalbert Nauklin GmbH + Co KG)",
        "office-frankfurt",
    ),
    ("Main construction contract - Wohnanlage Berlin-Mitte", "residential-berlin"),
    ("Subcontract - Außenwände (Kessmar Rohbau GmbH)", "residential-berlin"),
    ("Main construction contract - Lebensmittelmarkt Heilbronn", "retail-market-heilbronn"),
    (
        "Subcontract - LV 01 - Baustelleneinrichtung und Gemeinkosten (Sommerfeld Kältetechnik GmbH)",
        "retail-market-heilbronn",
    ),
    (
        "Subcontract - LV 02 - Erdbau und Erschließung (NeckarFrost Kälte- und Klimatechnik GmbH)",
        "retail-market-heilbronn",
    ),
    (
        "Subcontract - LV 04 - Rohbau: Gründung, Bodenplatte, Industrieboden, Massivbau "
        "(Kühlanlagenbau Westheimer GmbH)",
        "retail-market-heilbronn",
    ),
]


@pytest.mark.parametrize("value", CONTRACT_VALUES)
@pytest.mark.parametrize(("title", "demo_id"), DE_TITLES)
def test_a_german_schedule_sums_to_the_contract_value(value: Decimal, title: str, demo_id: str) -> None:
    lines = build_schedule_of_values_de(value, title, demo_id, _rng(title))

    assert lines, "a priced German contract must get a schedule"
    assert sum(line.total_value for line in lines) == value


@pytest.mark.parametrize("value", CONTRACT_VALUES)
@pytest.mark.parametrize(("title", "demo_id"), DE_TITLES)
def test_every_german_line_multiplies_out(value: Decimal, title: str, demo_id: str) -> None:
    for line in build_schedule_of_values_de(value, title, demo_id, _rng(title)):
        assert line.total_value == line.quantity * line.unit_rate


def test_the_company_name_does_not_decide_the_trade() -> None:
    """The regression this was written for.

    "Kessmar Rohbau GmbH" holds the external-walls package on the Berlin job.
    Matching the whole title would read Rohbau out of the company name and
    hand an external-walls subcontract a shell-and-core schedule.
    """
    shape = pick_german_shape("Subcontract - Außenwände (Kessmar Rohbau GmbH)", "residential-berlin")

    assert shape is _DE_TRADES["aussenwaende"]


def test_a_package_naming_two_trades_takes_the_one_it_is() -> None:
    # "LV 04 - Rohbau: Gründung, Bodenplatte, ..." names Gründung inside a
    # Rohbau package. It is a Rohbau package.
    shape = pick_german_shape("Subcontract - LV 04 - Rohbau: Gründung, Bodenplatte (Firma)", "retail-market-heilbronn")

    assert shape is _DE_TRADES["rohbau"]


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Subcontract - Baugrube / Erdbau (Firma)", "erdbau"),
        ("Subcontract - Gründung, Unterbau (Firma)", "gruendung"),
        ("Subcontract - Außenwände (Firma)", "aussenwaende"),
        ("Subcontract - LV 01 - Baustelleneinrichtung und Gemeinkosten (Firma)", "baustelleneinrichtung"),
        ("Subcontract - LV 02 - Erdbau und Erschließung (Firma)", "erdbau"),
    ],
)
def test_a_subcontract_gets_the_positions_of_its_own_trade(title: str, expected: str) -> None:
    assert pick_german_shape(title, "office-frankfurt") is _DE_TRADES[expected]


def test_a_main_contract_takes_the_ladder_its_project_was_procured_under() -> None:
    # A building job is costed by DIN 276 cost group; the retail markets are
    # tendered as a Leistungsverzeichnis. Both are German and both are right.
    berlin = pick_german_shape("Main construction contract - Wohnanlage Berlin-Mitte", "residential-berlin")
    market = pick_german_shape("Main construction contract - Lebensmittelmarkt Heilbronn", "retail-market-heilbronn")

    assert berlin is _DE_KG_LADDER
    assert market is _DE_LV_LADDER


def test_a_german_contract_naming_no_trade_still_gets_a_shape() -> None:
    # Titles are data and a reseed can change them. An unrecognised one must
    # fall back to a ladder rather than to nothing.
    assert pick_german_shape("Nachtrag 7 zum Bauvertrag", "office-frankfurt") is _DE_KG_LADDER


def test_the_german_lines_are_numbered_the_way_the_schedule_numbers_them() -> None:
    lines = build_schedule_of_values_de(
        Decimal("2400000.00"),
        "Main construction contract - Wohnanlage Berlin-Mitte",
        "residential-berlin",
        _rng("kg"),
    )

    # Real DIN 276 cost groups, not 01..15. The gaps are the point: a
    # Kalkulator finds the row by its cost group, and 300 to 700 is not a
    # sequence.
    assert [line.code for line in lines[:4]] == ["300", "320", "330", "340"]
    assert lines[-1].code == "700"


def test_the_english_schedule_is_still_numbered_by_position() -> None:
    # The German codes arrive through the same shared materializer, so this
    # pins that they did not leak into the English shapes.
    lines = build_schedule_of_values(Decimal("500000.00"), "lump_sum", _rng("en"))

    assert [line.code for line in lines[:3]] == ["01", "02", "03"]


def test_no_english_section_name_reaches_a_german_contract() -> None:
    english_wording = {tpl.description for tpl in _SOV_SECTIONAL + _SOV_MEASURED}

    for title, demo_id in DE_TITLES:
        lines = build_schedule_of_values_de(Decimal("1800000.00"), title, demo_id, _rng(title))
        for line in lines:
            assert line.description not in english_wording


def test_the_german_wording_is_actually_german() -> None:
    # A check on the catalogue rather than on one contract. Umlauts are the
    # cheap observable, and an ASCII-transliterated catalogue ("Gruendung")
    # is a defect this estate has filed before, so every shape has to carry
    # at least one real one.
    for shape in [*_DE_TRADES.values(), _DE_KG_LADDER, _DE_LV_LADDER]:
        assert any(ch in tpl.description for tpl in shape for ch in "äöüÄÖÜß")


def test_the_same_german_contract_always_yields_the_same_schedule() -> None:
    title, demo_id = DE_TITLES[1]
    first = build_schedule_of_values_de(Decimal("980000.00"), title, demo_id, _rng(title))
    second = build_schedule_of_values_de(Decimal("980000.00"), title, demo_id, _rng(title))

    assert first == second


def test_german_units_stay_in_the_schema_vocabulary() -> None:
    # German belongs in the description. A unit is a code the rest of the
    # product reads, so "qm" or "Stk" here would be a data defect rather than
    # a translation.
    allowed = {"m", "m2", "m3", "t", "pcs", "lsum", "kg"}

    for shape in [*_DE_TRADES.values(), _DE_KG_LADDER, _DE_LV_LADDER]:
        for tpl in shape:
            assert tpl.unit in allowed


def test_berlin_is_in_the_german_contract_set_but_not_the_shared_showcase_set() -> None:
    """The two sets answer different questions and Berlin is where they differ.

    Its contracts are German, so its schedule must be. Its variations and
    diary registers are not hand-authored, so adding it to the shared
    showcase set would filter it out of the generic English sprinkles and
    hand it nothing back.
    """
    assert "residential-berlin" in _GERMAN_CONTRACT_PROJECTS
    assert "residential-berlin" not in GERMAN_SHOWCASE_DEMO_IDS
    assert GERMAN_SHOWCASE_DEMO_IDS <= _GERMAN_CONTRACT_PROJECTS


@pytest.mark.parametrize("value", [Decimal("0"), Decimal("-1.00"), Decimal("0.01"), Decimal("0.10")])
def test_a_contract_too_small_to_break_down_gets_no_schedule(value: Decimal) -> None:
    """Both catalogues report the gap rather than writing a schedule of pennies.

    The seeder counts an empty return as ``contracts_unpriced``, so this is the
    branch that keeps that number honest. Both language paths share one
    materializer and must agree here, or the counter would mean two different
    things depending on the contract's language.
    """
    title, demo_id = DE_TITLES[1]

    assert build_schedule_of_values(value, "lump_sum", _rng("small")) == []
    assert build_schedule_of_values(value, "remeasurement", _rng("small")) == []
    assert build_schedule_of_values_de(value, title, demo_id, _rng("small")) == []


def test_a_contract_just_large_enough_does_get_a_schedule() -> None:
    # Pins the other side of the threshold, so the test above cannot pass by
    # the shapes having become impossible to materialize at any value.
    title, demo_id = DE_TITLES[1]

    assert build_schedule_of_values(Decimal("1.00"), "lump_sum", _rng("small"))
    assert build_schedule_of_values_de(Decimal("1.00"), title, demo_id, _rng("small"))
