# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A Saudi bill whose tax seed answers nothing still falls back to Saudi VAT.

Saudi Arabia read the Gulf stack, whose one tax line is 5: the UAE rate, and
Saudi Arabia's own rate only until 2020-06-30. A bill seeds its VAT from the
dated tax seed when it can, so the 5 surfaced where the seed answered nothing:
a fresh install, or a seed row that does not resolve. That fallback is now a
Saudi stack built from the Gulf lines with the tax line at 15, and the tax seed
carries the 5 percent period as history so a 2019 bill still resolves 5.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from app.modules.boq.markup_templates import (
    DEFAULT_MARKUP_TEMPLATES,
    REGION_BY_COUNTRY,
    region_key_for_country,
    resolve_region_lines,
)

_SEED = Path(__file__).resolve().parents[2] / "app/modules/i18n_foundation/seed_data/tax_configurations.json"


def _tax_lines(lines: list[dict[str, object]]) -> list[dict[str, object]]:
    return [line for line in lines if line.get("category") == "tax"]


def test_saudi_arabia_falls_back_to_fifteen_percent() -> None:
    lines = resolve_region_lines(region_key_for_country("SA"))
    tax = _tax_lines(lines)
    assert len(tax) == 1
    assert Decimal(str(tax[0]["percentage"])) == Decimal("15")


def test_the_saudi_stack_is_the_gulf_convention_with_saudi_vat() -> None:
    gulf = sorted(DEFAULT_MARKUP_TEMPLATES["GULF"], key=lambda e: int(e["sort_order"]))  # type: ignore[arg-type]
    saudi = sorted(DEFAULT_MARKUP_TEMPLATES["SA"], key=lambda e: int(e["sort_order"]))  # type: ignore[arg-type]
    assert [line["name"] for line in saudi] == [line["name"] for line in gulf]
    for ours, theirs in zip(saudi, gulf, strict=True):
        if ours["category"] == "tax":
            continue
        assert ours == theirs, f"{ours['name']} drifted from the Gulf convention"


def test_the_uae_keeps_the_gulf_stack_at_five_percent() -> None:
    assert REGION_BY_COUNTRY["AE"] == "GULF"
    tax = _tax_lines(resolve_region_lines(region_key_for_country("AE")))
    assert [Decimal(str(line["percentage"])) for line in tax] == [Decimal("5.0")]


def test_a_project_override_still_replaces_the_saudi_rate() -> None:
    tax = _tax_lines(resolve_region_lines("SA", vat_rate="0"))
    assert [line["percentage"] for line in tax] == ["0"]


def _saudi_vat_rows() -> list[dict[str, object]]:
    rows = json.loads(_SEED.read_text(encoding="utf-8"))
    return [row for row in rows if row["country_code"] == "SA" and row["tax_code"] == "VAT"]


def _rate_on(day: str) -> Decimal:
    in_force = [
        row
        for row in _saudi_vat_rows()
        if str(row["effective_from"]) <= day and (row["effective_to"] is None or day <= str(row["effective_to"]))
    ]
    assert len(in_force) == 1, f"{len(in_force)} Saudi VAT rows claim {day}"
    return Decimal(str(in_force[0]["rate_pct"]))


def test_the_tax_seed_carries_the_five_percent_period() -> None:
    assert _rate_on("2018-01-01") == Decimal("5.0")
    assert _rate_on("2020-06-30") == Decimal("5.0")
    assert _rate_on("2020-07-01") == Decimal("15.0")
