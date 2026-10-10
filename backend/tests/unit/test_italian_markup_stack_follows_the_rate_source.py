"""An Italian bill is offered two markup stacks, chosen by where its rates came from.

A regional price list (prezzario regionale) rate already contains spese generali
and utile d'impresa. Seeding such a bill with both again inflated it by about
26.5 percent. The founder chose two explicit templates over hidden logic: "per
price list" (safety and IVA only), which an Italian project gets by default, and
"per price analysis" (the full stack), which keeps the historical ``IT`` key.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

from app.core.validation.engine import ValidationContext
from app.core.validation.rules.italy_prezzario import PrezzarioOverheadsNotAppliedTwice
from app.modules.boq.markup_templates import (
    DEFAULT_MARKUP_TEMPLATES,
    REGION_VARIANTS,
    region_key_for_country,
    resolve_region_lines,
)
from app.modules.boq.models import BOQMarkup
from app.modules.boq.service import _calculate_markup_amounts

_DIRECT = Decimal("100000")


def _total(region: str) -> Decimal:
    markups = [
        BOQMarkup(
            name=str(line["name"]),
            markup_type="percentage",
            category=str(line["category"]),
            percentage=str(line["percentage"]),
            fixed_amount="0",
            apply_to=str(line["apply_to"]),
            sort_order=int(str(line["sort_order"])),
            is_active=True,
        )
        for line in resolve_region_lines(region)
    ]
    return _DIRECT + sum((amount for _, amount in _calculate_markup_amounts(_DIRECT, markups)), Decimal(0))


def _names(region: str) -> set[str]:
    return {str(line["name"]) for line in DEFAULT_MARKUP_TEMPLATES[region]}


def test_an_italian_project_is_seeded_per_price_list() -> None:
    assert region_key_for_country("IT") == "IT_PREZZARIO"
    assert REGION_VARIANTS["IT"] == "IT_PREZZARIO"


def test_the_price_list_stack_carries_no_general_expenses_or_profit() -> None:
    categories = {str(line["category"]) for line in DEFAULT_MARKUP_TEMPLATES["IT_PREZZARIO"]}
    assert "overhead" not in categories
    assert "profit" not in categories
    assert _names("IT_PREZZARIO") == {"Oneri della sicurezza non soggetti a ribasso", "IVA"}


def test_the_two_stacks_differ_by_exactly_general_expenses_and_profit() -> None:
    assert _names("IT") - _names("IT_PREZZARIO") == {"Spese generali", "Utile d'impresa"}
    assert _names("IT_PREZZARIO") <= _names("IT")


def test_the_price_list_total_is_safety_and_iva_only() -> None:
    # 100 000 + 2.5 % safety = 102 500, IVA 22 % on that = 22 550.
    assert _total("IT_PREZZARIO") == Decimal("125050")


def test_the_price_analysis_stack_is_unchanged() -> None:
    # 15 % spese generali, 10 % utile on cost plus 15 %, 2.5 % safety, IVA 22 %.
    sg = _DIRECT * Decimal("0.15")
    utile = (_DIRECT + sg) * Decimal("0.10")
    safety = _DIRECT * Decimal("0.025")
    iva = (_DIRECT + sg + utile + safety) * Decimal("0.22")
    assert _total("IT") == _DIRECT + sg + utile + safety + iva


def _rule(region: str) -> Any:
    lines = [
        {
            "id": pid,
            "ordinal": f"0{pid}",
            "description": "Scavo",
            "unit": "m3",
            "quantity": 1,
            "unit_rate": 500,
            "total": 500,
            "classification": {},
            "metadata": {"prezzario": {"region": "Toscana"}},
        }
        for pid in "12"
    ]
    markups = [{**line, "markup_type": "percentage", "is_active": True} for line in resolve_region_lines(region)]
    context = ValidationContext(data={"positions": lines, "markups": markups}, metadata={"locale": "en"})
    return asyncio.run(PrezzarioOverheadsNotAppliedTwice().validate(context))


def test_the_warning_stays_quiet_on_a_list_priced_bill_seeded_per_price_list() -> None:
    results = _rule("IT_PREZZARIO")
    assert len(results) == 1 and results[0].passed


def test_the_warning_still_fires_when_the_analysis_stack_is_picked_for_a_list_priced_bill() -> None:
    results = _rule("IT")
    assert len(results) == 1 and not results[0].passed
    assert results[0].details["added_percent"] == 27
