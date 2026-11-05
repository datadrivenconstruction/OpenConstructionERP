"""Offer rule set: each rule id fires on its trigger and stays quiet on the worked examples."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from decimal import Decimal
from typing import Any

import pytest

from app.modules.offers import pack as pack_mod
from app.modules.offers import pricing, validators
from tests.modules.offers.fixtures import de_items, uk_items, us_ca_items

_TEXTS = {
    "payment_terms": {"body": "Pay within 14 days."},
    "validity": {"body": "Valid."},
    "legal_notice": {"body": "Insurer X, policy 1."},
}
_ADDR = {"street": "Gartenweg 4", "postcode": "12345", "city": "Berlin"}


def _snapshot(
    items: list[dict[str, Any]],
    *,
    country: str,
    sub: str | None = None,
    currency: str,
    rate: str,
    rows: list[dict[str, Any]],
    kind: str = "private",
    **offer_over: Any,
) -> dict[str, Any]:
    pack = pack_mod.pack_for(country, sub)
    composed = pricing.compose(items, currency=currency, tax_rate=Decimal(rate), instalments=rows)
    offer = {
        "status": "draft",
        "number": "OF-2026-001",
        "revision": "A",
        "contact_id": "c1",
        "customer_kind": kind,
        "customer": {"name": "Max Meyer", "billing_address": _ADDR, "vat_id": "DE123"},
        "site_address": _ADDR,
        "issue_date": "2026-11-05",
        "valid_until": "2026-12-05",
        "currency": currency,
        "tax_mode": "standard",
        "tax_rate": rate,
        "markup_presentation": "spread",
        "options": {"show_gross": True, "cancellation_notice": True},
        "texts": deepcopy(_TEXTS),
        "licence_number": "123456",
        **composed,
        **offer_over,
    }
    return {"offer": offer, "pack": pack, "facts": {"currencies": [currency], "country": country}}


def _failed(snapshot: dict[str, Any]) -> dict[str, list[str]]:
    validators.register_offer_rules()
    results = asyncio.run(validators.evaluate(snapshot))
    out: dict[str, list[str]] = {}
    for r in results:
        out.setdefault(r.rule_id, []).append(r.message)
    return out


_DE_ROWS = [
    {"name": "Deposit", "kind": "deposit", "percent": "30"},
    {"name": "Shell", "kind": "progress", "percent": "40"},
    {"name": "Acceptance", "kind": "final", "percent": "30"},
]


def _de(**kw: Any) -> dict[str, Any]:
    return _snapshot(de_items(), country="DE", currency="EUR", rate="19", rows=_DE_ROWS, **kw)


def test_de_example_is_clean() -> None:
    assert _failed(_de()) == {}


def test_rule_ids_cover_the_spec() -> None:
    spec = {
        "offer.customer_present", "offer.billing_address_present", "offer.site_address_present", "offer.number_unique",
        "offer.valid_until_present", "offer.valid_until_after_issue", "offer.payment_terms_present",
        "offer.placeholders_resolved", "offer.no_cost_columns", "offer.totals_consistent", "offer.rounding_gap",
        "offer.unpriced_line", "offer.alternative_target", "offer.single_currency", "offer.tax_rate_known",
        "offer.reverse_charge_tax_id", "offer.consumer_gross", "offer.stale_revision", "offer.address_window_fit",
        "payment_plan.sum_matches", "payment_plan.non_negative", "payment_plan.dates_ordered",
        "payment_plan.final_last", "de.offer.abschlag_90", "fr.offer.insurance_named",
        "fr.offer.reduced_vat_attestation", "uk.offer.cancellation_notice", "us_ca.offer.licence_number",
    }  # fmt: skip
    assert spec <= set(validators.RULE_IDS)


def test_missing_customer_and_address() -> None:
    snap = _de(contact_id=None, customer={})
    assert "offer.customer_present" in _failed(snap)
    snap = _de(customer={"name": "X", "billing_address": {}})
    assert "offer.billing_address_present" in _failed(snap)


def test_site_validity_and_terms_warnings() -> None:
    snap = _de(site_address={}, valid_until=None, texts={})
    failed = _failed(snap)
    assert {"offer.site_address_present", "offer.valid_until_present", "offer.payment_terms_present"} <= set(failed)


def test_valid_until_must_follow_issue() -> None:
    assert "offer.valid_until_after_issue" in _failed(_de(valid_until="2026-11-05"))


def test_number_taken() -> None:
    snap = _de()
    snap["facts"]["number_taken"] = True
    assert "offer.number_unique" in _failed(snap)


def test_unknown_placeholder_is_an_error_naming_it() -> None:
    snap = _de(texts={"payment_terms": {"body": "Pay {oops}"}})
    assert "oops" in _failed(snap)["offer.placeholders_resolved"][0]


def test_unpriced_line_and_by_others() -> None:
    items = de_items()
    items.append(
        {
            "kind": "item",
            "ordinal": "05.0010",
            "description": "Scaffold",
            "quantity": "1",
            "unit_rate": "0",
            "role": "base",
        }
    )
    snap = _snapshot(items, country="DE", currency="EUR", rate="19", rows=_DE_ROWS)
    assert "05.0010" in _failed(snap)["offer.unpriced_line"][0]
    items[-1]["by_others"] = True
    snap = _snapshot(items, country="DE", currency="EUR", rate="19", rows=_DE_ROWS)
    assert "offer.unpriced_line" not in _failed(snap)


def test_alternative_must_point_at_an_item() -> None:
    items = de_items() + [
        {
            "kind": "item",
            "ordinal": "02.0099",
            "description": "Alt",
            "quantity": "1",
            "unit_rate": "10",
            "role": "alternative",
            "alternative_of": "99.9999",
        }
    ]
    snap = _snapshot(items, country="DE", currency="EUR", rate="19", rows=_DE_ROWS)
    assert "offer.alternative_target" in _failed(snap)


def test_mixed_currencies() -> None:
    snap = _de()
    snap["facts"]["currencies"] = ["EUR", "USD"]
    assert "offer.single_currency" in _failed(snap)


def test_totals_must_follow_printed_lines() -> None:
    snap = _de()
    snap["offer"]["totals"]["gross"] = "57536.51"
    assert "offer.totals_consistent" in _failed(snap)


def test_cost_keys_and_percent_labels_are_blocked() -> None:
    snap = _de()
    snap["offer"]["lines"][1]["net_cost_rate"] = "10"
    assert "offer.no_cost_columns" in _failed(snap)
    items = [{"kind": "item", "ordinal": "1", "description": "A", "quantity": "1", "unit_rate": "100", "role": "base"}]
    composed = pricing.compose(
        items, currency="EUR", markups=[{"label": "Overhead 12%", "amount": "5"}], presentation="lines"
    )
    snap = _de(**composed)
    assert "offer.no_cost_columns" in _failed(snap)


def test_rounding_gap_warns_only_in_spread() -> None:
    snap = _de()
    snap["offer"]["totals"]["rounding_gap"] = "0.37"
    assert "offer.rounding_gap" in _failed(snap)
    snap["offer"]["markup_presentation"] = "lines"
    assert "offer.rounding_gap" not in _failed(snap)


def test_reverse_charge_needs_vat_id() -> None:
    snap = _de(tax_mode="reverse_charge", kind="business")
    snap["offer"]["customer"]["vat_id"] = ""
    assert "offer.reverse_charge_tax_id" in _failed(snap)
    snap["offer"]["customer"]["vat_id"] = "DE123456789"
    assert "offer.reverse_charge_tax_id" not in _failed(snap)


def test_consumer_gross_rule() -> None:
    snap = _de()
    snap["offer"]["options"]["show_gross"] = False
    assert "offer.consumer_gross" in _failed(snap)


def test_stale_revision() -> None:
    snap = _de(status="sent")
    snap["facts"]["boq_changed"] = True
    assert "offer.stale_revision" in _failed(snap)


def test_unknown_pack_rate_warns_only_with_a_pack() -> None:
    snap = _de(issue_date="1950-01-01")
    assert "offer.tax_rate_known" in _failed(snap)
    neutral = _snapshot(de_items(), country="ZZ", currency="EUR", rate="0", rows=[])
    assert "offer.tax_rate_known" not in _failed(neutral)


def test_schedule_rules() -> None:
    snap = _de()
    snap["offer"]["schedule"][1]["net"] = "-5.00"
    failed = _failed(snap)
    assert "payment_plan.sum_matches" in failed and "payment_plan.non_negative" in failed
    rows = [{"kind": "final", "percent": "50"}, {"kind": "progress", "percent": "50"}]
    assert "payment_plan.final_last" in _failed(
        _snapshot(de_items(), country="DE", currency="EUR", rate="19", rows=rows)
    )
    dated = [
        {"percent": "50", "due": {"type": "date", "date": "2026-12-01"}},
        {"percent": "50", "due": {"type": "date", "date": "2026-11-01"}},
    ]
    assert "payment_plan.dates_ordered" in _failed(
        _snapshot(de_items(), country="DE", currency="EUR", rate="19", rows=dated)
    )


def test_de_abschlag_90_only_over_the_cap_and_only_consumers() -> None:
    rows = [
        {"kind": "deposit", "percent": "50"},
        {"kind": "progress", "percent": "45"},
        {"kind": "final", "percent": "5"},
    ]
    over = _snapshot(de_items(), country="DE", currency="EUR", rate="19", rows=rows)
    assert "de.offer.abschlag_90" in _failed(over)
    biz = _snapshot(de_items(), country="DE", currency="EUR", rate="19", rows=rows, kind="business")
    assert "de.offer.abschlag_90" not in _failed(biz)


def test_pack_rules_stay_inside_their_market() -> None:
    de_failed = _failed(_de(licence_number=""))
    assert "us_ca.offer.licence_number" not in de_failed
    assert "uk.offer.cancellation_notice" not in _failed(_de(options={"cancellation_notice": False}))


def test_uk_cancellation_notice() -> None:
    rows = [{"percent": "100", "kind": "final"}]
    snap = _snapshot(
        uk_items(), country="GB", currency="GBP", rate="20", rows=rows, options={"cancellation_notice": False}
    )
    assert "uk.offer.cancellation_notice" in _failed(snap)
    snap = _snapshot(uk_items(), country="GB", currency="GBP", rate="20", rows=rows)
    assert _failed(snap) == {}


def test_us_ca_licence_and_deposit_cap() -> None:
    rows = [
        {"name": "Deposit", "kind": "deposit", "percent": "30"},
        {"name": "Framing", "percent": "40"},
        {"name": "Final", "kind": "final", "percent": "30"},
    ]
    snap = _snapshot(us_ca_items(), country="US", sub="CA", currency="USD", rate="0", rows=rows, licence_number="")
    failed = _failed(snap)
    assert "us_ca.offer.licence_number" in failed
    assert (
        "1,000.00" in failed["payment_plan.consumer_deposit_cap"][0]
        or "1000.00" in failed["payment_plan.consumer_deposit_cap"][0]
    )


def test_us_ca_compliant_schedule_passes_the_cap() -> None:
    rows = [
        {"name": "Deposit", "kind": "deposit", "value": "1000.00"},
        {"name": "Framing", "value": "18340.00"},
        {"name": "Drywall", "value": "19340.00"},
        {"name": "Final", "kind": "final", "value": "9670.00"},
    ]
    snap = _snapshot(us_ca_items(), country="US", sub="CA", currency="USD", rate="0", rows=rows)
    assert _failed(snap) == {}


def test_fr_rules() -> None:
    rows = [{"percent": "100", "kind": "final"}]
    snap = _snapshot(
        de_items(), country="FR", currency="EUR", rate="10", rows=rows, texts={"payment_terms": {"body": "x"}}
    )
    failed = _failed(snap)
    assert "fr.offer.insurance_named" in failed
    assert "fr.offer.reduced_vat_attestation" in failed
    snap["offer"]["options"]["attestation_received"] = True
    snap["offer"]["texts"]["legal_notice"] = {"body": "AXA contrat 123"}
    assert "fr.offer.reduced_vat_attestation" not in _failed(snap)
    assert "fr.offer.insurance_named" not in _failed(snap)


def test_address_window_finding() -> None:
    snap = _de()
    snap["facts"]["address_fit"] = "overflow"
    assert "offer.address_window_fit" in _failed(snap)


@pytest.mark.parametrize("country", ["DE", "GB", "FR", "US"])
def test_every_pack_has_every_text_kind(country: str) -> None:
    pack = pack_mod.pack_for(country, "CA" if country == "US" else None)
    assert pack["key"] is not None
    assert set(pack["texts"]) == set(pack_mod.TEXT_KINDS)
    for kind in pack_mod.TEXT_KINDS:
        for body in pack["texts"][kind].values():
            assert pricing.unknown_placeholders(body) == []
    assert pack["verified"] is False
