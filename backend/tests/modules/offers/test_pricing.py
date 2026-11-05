"""Customer offer arithmetic against the DOMAIN worked examples, to the cent."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.modules.offers import pricing
from tests.modules.offers.fixtures import de_items, uk_items, us_ca_items


def _price(items, currency, rate, mode="standard", **kw):
    built = pricing.build_lines(items, currency=currency, default_tax_rate=Decimal(rate), **kw)
    totals = pricing.totals(built["lines"], currency=currency, tax_mode=mode, estimate_net=built["estimate_net"])
    return built, totals


def test_de_totals() -> None:
    _, t = _price(de_items(), "EUR", "19")
    assert (t["net"], t["tax_total"], t["gross"]) == ("48350.00", "9186.50", "57536.50")
    assert t["tax_groups"] == [{"rate": "19", "base": "48350.00", "tax": "9186.50"}]


def test_de_optional_item_is_listed_not_summed() -> None:
    _, t = _price(de_items(), "EUR", "19")
    assert [n["ordinal"] for n in t["not_included"]] == ["02.0040"]
    assert t["not_included"][0]["total"] == "640.00"
    without = [i for i in de_items() if i["ordinal"] != "02.0040"]
    assert _price(without, "EUR", "19")[1]["gross"] == t["gross"]


def test_de_schedule_30_40_30() -> None:
    rows = [
        {"name": "Deposit", "kind": "deposit", "percent": "30"},
        {"name": "Shell", "kind": "progress", "percent": "40"},
        {"name": "Acceptance", "kind": "final", "percent": "30"},
    ]
    out = pricing.schedule(rows, net=Decimal("48350.00"), tax_total=Decimal("9186.50"), currency="EUR")
    assert [(r["net"], r["tax"], r["gross"]) for r in out] == [
        ("14505.00", "2755.95", "17260.95"),
        ("19340.00", "3674.60", "23014.60"),
        ("14505.00", "2755.95", "17260.95"),
    ]
    assert out[-1]["takes_rest"] is True
    assert sum(Decimal(r["net"]) for r in out) == Decimal("48350.00")
    assert sum(Decimal(r["tax"]) for r in out) == Decimal("9186.50")
    assert pricing.before_acceptance_percent(out) == Decimal("70")


def test_de_reverse_charge_has_no_vat() -> None:
    _, t = _price(de_items(), "EUR", "19", mode="reverse_charge")
    assert (t["tax_total"], t["gross"]) == ("0.00", "48350.00")


def test_uk_totals_and_provisional_sum_inside_net() -> None:
    built, t = _price(uk_items(), "GBP", "20")
    assert (t["net"], t["tax_total"], t["gross"]) == ("48350.00", "9670.00", "58020.00")
    prov = [ln for ln in built["lines"] if ln.get("role") == "provisional_sum"]
    assert [p["total"] for p in prov] == ["3500.00"]
    out = pricing.schedule(
        [{"percent": "30", "kind": "deposit"}, {"percent": "40"}, {"percent": "30", "kind": "final"}],
        net=Decimal(t["net"]),
        tax_total=Decimal(t["tax_total"]),
        currency="GBP",
    )
    assert [r["gross"] for r in out] == ["17406.00", "23208.00", "17406.00"]
    assert [r["tax"] for r in out] == ["2901.00", "3868.00", "2901.00"]


def test_us_ca_lump_sum_no_sales_tax() -> None:
    _, t = _price(us_ca_items(), "USD", "0")
    assert (t["net"], t["tax_total"], t["gross"]) == ("48350.00", "0.00", "48350.00")


def test_us_ca_fixed_schedule_sums_to_total() -> None:
    rows = [
        {"name": "Deposit", "kind": "deposit", "value": "1000.00"},
        {"name": "Framing", "value": "18340.00"},
        {"name": "Drywall", "value": "19340.00"},
        {"name": "Final", "kind": "final", "value": "9670.00"},
    ]
    out = pricing.schedule(rows, net=Decimal("48350.00"), tax_total=Decimal("0"), currency="USD")
    assert sum(Decimal(r["net"]) for r in out) == Decimal("48350.00")
    assert out[0]["percent"] == "2.0683"
    assert out[-1]["takes_rest"] is False


def test_rounding_fixture_last_instalment_takes_remainder() -> None:
    rows = [{"percent": "33.3333"}] * 3
    out = pricing.schedule(rows, net=Decimal("100.00"), tax_total=Decimal("0"), currency="EUR")
    assert [r["net"] for r in out] == ["33.33", "33.33", "33.34"]


def test_spread_markups_into_unit_rates_and_gap() -> None:
    items = [
        {"kind": "item", "ordinal": "1", "description": "A", "quantity": "3", "unit_rate": "10.00", "role": "base"},
        {"kind": "item", "ordinal": "2", "description": "B", "quantity": "1", "unit_rate": "70.00", "role": "base"},
    ]
    built = pricing.build_lines(items, currency="EUR", markups=[{"label": "Overhead", "amount": "10.00"}])
    assert [ln["unit_rate"] for ln in built["lines"]] == ["11", "77"]
    t = pricing.totals(built["lines"], currency="EUR", estimate_net=built["estimate_net"])
    assert t["net"] == "110.00"
    assert t["rounding_gap"] == "0.00"
    assert all("overhead" not in ln["description"].lower() for ln in built["lines"])


def test_spread_rounding_gap_is_reported_and_net_is_the_printed_sum() -> None:
    items = [
        {"kind": "item", "ordinal": "1", "description": "A", "quantity": "7", "unit_rate": "3.33", "role": "base"},
        {"kind": "item", "ordinal": "2", "description": "B", "quantity": "3", "unit_rate": "1.11", "role": "base"},
    ]
    built = pricing.build_lines(items, currency="EUR", markups=[{"label": "x", "amount": "1.00"}])
    t = pricing.totals(built["lines"], currency="EUR", estimate_net=built["estimate_net"])
    printed = sum(Decimal(ln["total"]) for ln in built["lines"])
    assert Decimal(t["net"]) == printed
    assert Decimal(t["rounding_gap"]) == printed - built["estimate_net"]


def test_lines_mode_prints_neutral_markup_lines() -> None:
    items = [
        {"kind": "item", "ordinal": "1", "description": "A", "quantity": "1", "unit_rate": "100.00", "role": "base"}
    ]
    built = pricing.build_lines(
        items, currency="EUR", markups=[{"label": "Site set-up", "amount": "8.00"}], presentation="lines"
    )
    t = pricing.totals(built["lines"], currency="EUR", estimate_net=built["estimate_net"])
    assert t["net"] == "108.00"
    assert built["lines"][-1]["description"] == "Site set-up"


def test_zero_decimal_currency() -> None:
    items = [
        {"kind": "item", "ordinal": "1", "description": "A", "quantity": "3", "unit_rate": "333.5", "role": "base"}
    ]
    assert pricing.build_lines(items, currency="JPY")["lines"][0]["total"] == "1001"


def test_daywork_rate_has_no_total() -> None:
    items = [
        {
            "kind": "item",
            "ordinal": "1",
            "description": "Labourer",
            "quantity": "1",
            "unit_rate": "55.00",
            "role": "daywork_rate",
        }
    ]
    built = pricing.build_lines(items, currency="EUR")
    assert built["lines"][0]["total"] == ""
    assert pricing.totals(built["lines"], currency="EUR")["net"] == "0.00"


def test_alternative_is_not_summed() -> None:
    items = [
        {"kind": "item", "ordinal": "1", "description": "Base", "quantity": "1", "unit_rate": "100.00", "role": "base"},
        {
            "kind": "item",
            "ordinal": "2",
            "description": "Alt",
            "quantity": "1",
            "unit_rate": "130.00",
            "role": "alternative",
            "alternative_of": "1",
        },
    ]
    built = pricing.build_lines(items, currency="EUR")
    t = pricing.totals(built["lines"], currency="EUR")
    assert t["net"] == "100.00"
    assert t["not_included"][0]["alternative_of"] == "1"


def test_mixed_tax_rates_round_once_per_rate() -> None:
    def row(o, rate, tax):
        return {
            "kind": "item",
            "ordinal": o,
            "description": o,
            "quantity": "1",
            "unit_rate": rate,
            "role": "base",
            "tax_rate": tax,
        }

    built = pricing.build_lines(
        [row("1", "100.05", "10"), row("2", "100.05", "10"), row("3", "50.00", "20")], currency="EUR"
    )
    t = pricing.totals(built["lines"], currency="EUR")
    assert [(g["rate"], g["tax"]) for g in t["tax_groups"]] == [("10", "20.01"), ("20", "10.00")]
    assert Decimal(t["gross"]) == Decimal(t["net"]) + Decimal(t["tax_total"])


@pytest.mark.parametrize(
    ("pattern", "existing", "expected"),
    [
        ("OF-{YYYY}-{seq:3}", [], "OF-2026-001"),
        ("OF-{YYYY}-{seq:3}", ["OF-2026-014", "OF-2025-099", "OF-2026-003"], "OF-2026-015"),
        ("{seq}/{YY}", ["7/26"], "8/26"),
    ],
)
def test_number_sequence(pattern, existing, expected) -> None:
    assert pricing.render_number(pattern, 2026, pricing.next_sequence(pattern, 2026, existing)) == expected


def test_revision_letters_roundtrip() -> None:
    assert [pricing.revision_letter(i) for i in (0, 1, 25, 26)] == ["A", "B", "Z", "AA"]
    assert pricing.revision_index("AA") == 26


def test_placeholders() -> None:
    assert pricing.unknown_placeholders("Valid until {valid_until}, {oops} and {oops}") == ["oops"]
    assert pricing.resolve("Until {valid_until} {oops}", {"valid_until": "12.12.2026"}) == "Until 12.12.2026 {oops}"


def test_locale_formats() -> None:
    assert pricing.format_money("48350.00", "EUR", "de") == "48.350,00"
    assert pricing.format_money("48350.00", "USD", "en") == "48,350.00"
    assert pricing.format_date("2026-11-12", "de") == "12.11.2026"
    assert pricing.format_date("2026-11-12", "en-US") == "11/12/2026"


def test_valid_until_and_fingerprint_changes() -> None:
    assert pricing.valid_until(date(2026, 11, 5), 30) == date(2026, 12, 5)
    a = [{"id": "1", "ordinal": "1", "description": "x", "unit": "m", "quantity": "1", "unit_rate": "10"}]
    b = [{**a[0], "unit_rate": "11"}]
    assert pricing.fingerprint(a) != pricing.fingerprint(b)
    assert pricing.fingerprint(a) == pricing.fingerprint([dict(a[0])])


def test_acceptance_with_a_ticked_optional_adds_it_to_the_award() -> None:
    built, _ = _price(de_items(), "EUR", "19")
    rows = [{"name": "All", "kind": "final", "percent": "100"}]
    fig = pricing.accepted_figures(built["lines"], rows, {"02.0040"}, currency="EUR")
    assert fig["totals"]["net"] == "48990.00"
    assert fig["schedule"][0]["net"] == "48990.00"
    assert fig["totals"]["not_included"] == []


def test_acceptance_with_a_ticked_alternative_replaces_its_base() -> None:
    items = [
        {"kind": "item", "ordinal": "1", "description": "Base", "quantity": "1", "unit_rate": "100.00", "role": "base"},
        {
            "kind": "item", "ordinal": "2", "description": "Alt", "quantity": "1", "unit_rate": "130.00",
            "role": "alternative", "alternative_of": "1",
        },
    ]  # fmt: skip
    built = pricing.build_lines(items, currency="EUR")
    fig = pricing.accepted_figures(built["lines"], [], {"2"}, currency="EUR")
    assert fig["totals"]["net"] == "130.00"
    assert pricing.accepted_figures(built["lines"], [], set(), currency="EUR")["totals"]["net"] == "100.00"


def test_contract_payload_maps_each_instalment_to_a_milestone() -> None:
    rows = pricing.schedule(
        [{"name": "Deposit", "kind": "deposit", "percent": "30"}, {"name": "Final", "kind": "final", "percent": "70"}],
        net=Decimal("1000.00"), tax_total=Decimal("190.00"), currency="EUR",
    )  # fmt: skip
    out = pricing.contract_payload({"instalments": rows, "net": "1000.00", "currency": "EUR"})
    assert out["total_value"] == "1000.00"
    assert [m["kind"] for m in out["milestones"]] == ["deposit", "final"]
    assert [m["percent_of_contract"] for m in out["milestones"]] == ["30.0000", "70.0000"]
