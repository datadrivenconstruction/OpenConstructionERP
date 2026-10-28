# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the banded and escalation markup types.

Two shapes a markup stack could not express before:

* A bond premium. A surety quotes a rate card, not a rate: the first tranche of
  the contract sum at one percentage, the next at a lower one, the rest at a
  lower one still. Charging the whole sum at any single band over-prices or
  under-prices every job that is not exactly at a band edge.
* An escalation. A bill priced in one month and built in another is worth what
  the cost index says, not what an estimator guesses. The factor comes from
  ``price_index.resolve_factor`` and this module does not reimplement the
  date-to-date arithmetic. There is a test below that would fail if it did.

The band tests spend their effort on the boundary, because a tranche table is
correct everywhere except at its edges and that is where the money is.

Run (CI):
    cd backend
    python -m pytest tests/unit/test_boq_markup_types.py -v
"""

from __future__ import annotations

import inspect
import re
import uuid
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from app.modules.boq.models import BOQMarkup
from app.modules.boq.schemas import MarkupCreate
from app.modules.boq.service import _banded_amount, _calculate_markup_amounts, _read_bands
from app.modules.price_index.index_math import resolve_factor

# A surety rate card: 2.5 % on the first million, 1.5 % on the next four,
# 1 % on everything above five million.
_RATE_CARD: list[dict[str, Any]] = [
    {"up_to": "1000000", "percentage": "2.5"},
    {"up_to": "5000000", "percentage": "1.5"},
    {"up_to": None, "percentage": "1.0"},
]


def _mk(
    name: str,
    *,
    markup_type: str = "percentage",
    percentage: str = "0",
    fixed_amount: str = "0",
    apply_to: str = "direct_cost",
    sort_order: int = 0,
    category: str = "overhead",
    metadata: dict[str, Any] | None = None,
    markup_id: uuid.UUID | None = None,
) -> BOQMarkup:
    markup = BOQMarkup(
        boq_id=None,
        name=name,
        markup_type=markup_type,
        category=category,
        percentage=percentage,
        fixed_amount=fixed_amount,
        apply_to=apply_to,
        sort_order=sort_order,
        is_active=True,
        metadata_=metadata or {},
    )
    markup.id = markup_id or uuid.uuid4()
    return markup


# ── Banded bond rates ───────────────────────────────────────────────────────


def test_each_tranche_is_charged_at_its_own_rate() -> None:
    """1.5 M against the card pays 25,000 on the first million and 7,500 on the rest.

    Not 22,500, which is what charging the whole sum at the band it lands in
    would give, and not 37,500, which is the top rate applied throughout.
    """
    assert _banded_amount(Decimal("1500000"), {"bands": _RATE_CARD}) == Decimal("32500")


def test_a_base_exactly_on_a_band_edge_belongs_to_the_lower_band() -> None:
    """The edge is the case a rate card is read wrong at.

    Exactly one million is entirely inside the 2.5 % tranche and pays 25,000.
    A cent more pays 25,000 plus 1.5 % of that cent, and nothing about the
    first million changes.
    """
    assert _banded_amount(Decimal("1000000"), {"bands": _RATE_CARD}) == Decimal("25000")

    just_over = _banded_amount(Decimal("1000000.01"), {"bands": _RATE_CARD})
    assert just_over == Decimal("25000") + Decimal("0.01") * Decimal("1.5") / Decimal("100")


def test_a_base_inside_the_first_band_never_reaches_the_others() -> None:
    assert _banded_amount(Decimal("400000"), {"bands": _RATE_CARD}) == Decimal("10000")


def test_the_open_ended_band_takes_everything_above_the_last_ceiling() -> None:
    """Ten million: 25,000 + 60,000 + 50,000."""
    assert _banded_amount(Decimal("10000000"), {"bands": _RATE_CARD}) == Decimal("135000")


def test_bands_written_out_of_order_are_read_in_order() -> None:
    """The card is data an API client sends; its order must not decide the price."""
    shuffled = [_RATE_CARD[2], _RATE_CARD[0], _RATE_CARD[1]]

    assert _banded_amount(Decimal("1500000"), {"bands": shuffled}) == Decimal("32500")


def test_an_unreadable_band_entry_is_dropped_rather_than_crashing_the_rollup() -> None:
    """A markup row is user data. A malformed band must not fail a whole bill."""
    bands = [
        {"up_to": "1000000", "percentage": "2.5"},
        {"up_to": "not a number", "percentage": "9"},
        "nonsense",
        {"up_to": None, "percentage": "1.0"},
    ]

    assert _read_bands({"bands": bands}) == [(Decimal("1000000"), Decimal("2.5")), (None, Decimal("1.0"))]
    assert _banded_amount(Decimal("1500000"), {"bands": bands}) == Decimal("30000")


@pytest.mark.parametrize("metadata", [None, {}, {"bands": []}, {"bands": "not a list"}, "not a dict"])
def test_a_banded_line_with_no_card_charges_nothing(metadata: object) -> None:
    assert _banded_amount(Decimal("1000000"), metadata) == Decimal("0")


def test_a_banded_line_charges_its_own_base_not_the_direct_cost() -> None:
    """A bond is written against the contract sum, so ``cumulative`` matters here.

    The bond line follows a 10 % overhead, so its base is 1,100,000 and it pays
    25,000 on the first million plus 1,500 on the next hundred thousand.
    """
    stack = [
        _mk("Overhead", percentage="10", sort_order=1),
        _mk(
            "Performance & Payment Bond",
            markup_type="banded",
            apply_to="cumulative",
            sort_order=2,
            category="bond",
            metadata={"bands": _RATE_CARD},
        ),
    ]

    results = _calculate_markup_amounts(Decimal("1000000"), stack)

    assert results[0][1] == Decimal("100000")
    assert results[1][1] == Decimal("26500")


# ── Escalation ──────────────────────────────────────────────────────────────


def test_an_escalation_line_adds_the_increase_not_the_whole_indexed_amount() -> None:
    """The base is already in the bill; the markup line is what the index added."""
    markup = _mk("Escalation to 2027-06", markup_type="escalation", sort_order=1, category="other")

    results = _calculate_markup_amounts(Decimal("1000000"), [markup], {markup.id: Decimal("1.06")})

    assert results[0][1] == Decimal("60000.00")


def test_an_escalation_nobody_could_resolve_contributes_nothing() -> None:
    """Absent is not zero percent, but zero is the only honest number to add.

    The line stays visible at zero rather than being folded into another one,
    and the service logs why the factor was missing.
    """
    markup = _mk("Escalation", markup_type="escalation", sort_order=1, category="other")

    assert _calculate_markup_amounts(Decimal("1000000"), [markup], {})[0][1] == Decimal("0")
    assert _calculate_markup_amounts(Decimal("1000000"), [markup])[0][1] == Decimal("0")


def test_a_falling_index_reduces_the_price_rather_than_being_clamped_away() -> None:
    """A bill brought back to an earlier period is worth less, and says so.

    This is a deliberate decision and the only place in the stack where a
    markup line can be negative. Clamping it at zero would report a bid at a
    price the index does not support, which is inventing money in the safer
    looking direction.
    """
    markup = _mk("Escalation to 2019-01", markup_type="escalation", sort_order=1, category="other")

    results = _calculate_markup_amounts(Decimal("1000000"), [markup], {markup.id: Decimal("0.94")})

    assert results[0][1] == Decimal("-60000.00")


def test_the_escalation_factor_is_the_price_index_module_s_own_arithmetic() -> None:
    """The BOQ module must not grow its own date-to-date maths.

    The amount is asserted against ``resolve_factor`` computed here from the
    same series, so a reimplementation inside the BOQ module that happened to
    round differently would fail this rather than pass a hand-typed constant.
    """
    points = {"2024-01": Decimal("104.2"), "2027-06": Decimal("119.8")}
    factor = resolve_factor(points, "2024-01", "2027-06")
    markup = _mk("Escalation", markup_type="escalation", sort_order=1, category="other")

    results = _calculate_markup_amounts(Decimal("1000000"), [markup], {markup.id: factor})

    assert results[0][1] == Decimal("1000000") * (factor - Decimal("1"))
    assert factor > Decimal("1")


def test_an_escalation_line_can_compound_like_any_other() -> None:
    """``apply_to`` still says only what the base is, and it still works.

    That is the point of putting escalation in ``markup_type``: the statement
    about the base did not have to learn a second job.
    """
    overhead = _mk("Overhead", percentage="10", sort_order=1)
    escalation = _mk(
        "Escalation",
        markup_type="escalation",
        apply_to="cumulative",
        sort_order=2,
        category="other",
    )

    results = _calculate_markup_amounts(Decimal("1000000"), [overhead, escalation], {escalation.id: Decimal("1.05")})

    assert results[0][1] == Decimal("100000")
    assert results[1][1] == Decimal("55000.00")  # 5 % of 1,100,000


# ── The two sets that have to be one set ────────────────────────────────────


def test_the_schema_accepts_exactly_the_types_the_engine_computes() -> None:
    """A type the schema takes and the engine does not know prices at zero.

    That is how ``per_unit`` used to fail: accepted, stored, silently worth
    nothing. The check reads the branches out of the engine's own source rather
    than restating them, so adding a branch without widening the schema, or
    widening the schema without adding a branch, fails here.
    """
    engine_types = set(re.findall(r'markup_type == "([a-z_]+)"', inspect.getsource(_calculate_markup_amounts)))

    candidates = ["percentage", "fixed", "banded", "escalation", "per_unit", "cumulative", "", "nonsense"]
    schema_types: set[str] = set()
    for candidate in candidates:
        try:
            MarkupCreate(name="x", markup_type=candidate)
        except ValidationError:
            continue
        schema_types.add(candidate)

    assert engine_types == schema_types, f"engine {sorted(engine_types)} vs schema {sorted(schema_types)}"
