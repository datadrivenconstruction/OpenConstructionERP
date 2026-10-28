# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A claim bills percent to date less what the earlier claims billed.

The defect this holds shut: a line's percent complete is a figure TO DATE, and
the generators stored ``line value × percent`` as the value for the period. A
line at 40% and then 60% billed 40 and then 60, so from the second claim on the
continuation sheet's D + E counted the first 40 twice, and the running total
that costmodel reads as claimed-to-date ran ahead of the work.

The same numbers are run through the continuation sheet and the certificate
face at the end, because the invariant that matters is not any one figure but
that G702 line 8 on a claim equals the net due the claim stores. The PG lane
repeats this against the database in ``tests/pg/test_claim_prior_ordering.py``;
this copy runs in the default lane so a local run catches it first.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

from app.modules.contracts.aia import build_g702_summary, build_g703_line
from app.modules.contracts.service import (
    claim_line_percent_regressed,
    compute_progress_claim_line,
    generate_lump_sum_claim,
    generate_unit_price_claim,
)

RETENTION = Decimal("10")


def _line(total: str, quantity: str = "1", unit_rate: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        code="03 30 00",
        description="Cast-in-place concrete",
        parent_line_id=None,
        quantity=Decimal(quantity),
        unit_rate=Decimal(unit_rate if unit_rate is not None else total),
        total_value=Decimal(total),
    )


def _contract() -> SimpleNamespace:
    return SimpleNamespace(retention_percent=RETENTION)


def test_percent_to_date_bills_only_what_is_new() -> None:
    line = _line("1000", quantity="10", unit_rate="100")
    first = compute_progress_claim_line(line, Decimal("40"))
    assert first["period_completed_value"] == Decimal("400.0000")
    assert first["period_completed_qty"] == Decimal("4.0000")

    second = compute_progress_claim_line(line, Decimal("60"), prior_value=first["cumulative_completed_value"])
    assert second["prior_completed_value"] == Decimal("400.0000")
    assert second["period_completed_value"] == Decimal("200.0000")
    assert second["period_completed_qty"] == Decimal("2.0000")
    assert second["cumulative_completed_value"] == Decimal("600.0000")
    # The percent stays what the person entered: to date, not for the period.
    assert second["period_completed_pct"] == Decimal("60.0000")
    assert not claim_line_percent_regressed(second)


def test_a_percent_below_what_was_billed_bills_nothing_and_says_so() -> None:
    line = _line("1000")
    derived = compute_progress_claim_line(line, Decimal("50"), prior_value=Decimal("600"))
    assert derived["period_completed_value"] == Decimal("0")
    assert derived["period_completed_qty"] == Decimal("0")
    assert derived["cumulative_completed_value"] == Decimal("600.0000")
    assert claim_line_percent_regressed(derived)
    # Holding level is not going backwards.
    assert not claim_line_percent_regressed(
        compute_progress_claim_line(line, Decimal("60"), prior_value=Decimal("600"))
    )


def test_a_credit_line_bills_towards_its_negative_total() -> None:
    credit = _line("-500")
    first = compute_progress_claim_line(credit, Decimal("40"))
    assert first["period_completed_value"] == Decimal("-200.0000")
    assert not claim_line_percent_regressed(first)
    back = compute_progress_claim_line(credit, Decimal("20"), prior_value=Decimal("-200"))
    assert back["period_completed_value"] == Decimal("0")
    assert claim_line_percent_regressed(back)


def test_an_override_cannot_take_the_line_past_its_scheduled_value() -> None:
    line = _line("1000")
    derived = compute_progress_claim_line(
        line, Decimal("100"), value_override=Decimal("900"), prior_value=Decimal("600")
    )
    assert derived["period_completed_value"] == Decimal("400")
    assert derived["cumulative_completed_value"] == Decimal("1000.0000")


def test_two_lump_sum_claims_at_forty_then_sixty_bill_forty_then_twenty() -> None:
    line = _line("100000")
    first = generate_lump_sum_claim(_contract(), [line], {str(line.id): Decimal("40")})
    assert first["gross"] == Decimal("40000.0000")
    assert first["retention"] == Decimal("4000.0000")
    assert first["net"] == Decimal("36000.0000")

    prior = {line.id: first["claim_lines"][0]["cumulative_completed_value"]}
    second = generate_lump_sum_claim(_contract(), [line], {str(line.id): Decimal("60")}, prior_by_line=prior)
    [row] = second["claim_lines"]
    assert row["prior_completed_value"] == Decimal("40000.0000")
    assert row["period_completed_value"] == Decimal("20000.0000")
    assert row["cumulative_completed_value"] == Decimal("60000.0000")
    assert second["gross"] == Decimal("20000.0000")
    assert second["retention"] == Decimal("2000.0000")
    # Net is this period's gross less retention. Subtracting what was paid
    # before as well would take the first claim off a second time.
    assert second["net"] == Decimal("18000.0000")
    assert second["percent_regressed"] == []


def test_a_lump_sum_line_that_goes_backwards_is_listed() -> None:
    line = _line("100000")
    result = generate_lump_sum_claim(
        _contract(), [line], {str(line.id): Decimal("30")}, prior_by_line={line.id: Decimal("40000")}
    )
    assert result["gross"] == Decimal("0")
    [entry] = result["percent_regressed"]
    assert entry["contract_line_id"] == str(line.id)
    assert entry["observed_pct"] == "30.0000"
    assert Decimal(entry["requested_value"]) == Decimal("30000")
    assert Decimal(entry["previous_value"]) == Decimal("40000")


def test_a_unit_price_measurement_is_the_period_and_the_prior_is_carried() -> None:
    line = _line("5000", quantity="100", unit_rate="50")
    result = generate_unit_price_claim(
        _contract(), [line], {str(line.id): Decimal("30")}, prior_by_line={line.id: Decimal("1000")}
    )
    [row] = result["claim_lines"]
    assert row["period_completed_value"] == Decimal("1500.0000")
    assert row["prior_completed_value"] == Decimal("1000")
    assert row["cumulative_completed_value"] == Decimal("2500.0000")
    assert result["net"] == Decimal("1350.0000")


def test_the_second_certificate_pays_exactly_the_claims_net_due() -> None:
    """G702 line 8 on claim 2 equals the net due claim 2 stores.

    Line 7 is what claim 1 certified: its gross less its retention. Line 6
    is everything earned to date less retention. The difference has to be
    this period's gross less this period's retention, or the certificate and
    the claim ask the owner for two different amounts.
    """
    line = _line("100000")
    first = generate_lump_sum_claim(_contract(), [line], {str(line.id): Decimal("40")})
    second = generate_lump_sum_claim(
        _contract(),
        [line],
        {str(line.id): Decimal("60")},
        prior_by_line={line.id: first["claim_lines"][0]["cumulative_completed_value"]},
    )
    stored = SimpleNamespace(**second["claim_lines"][0])
    row = build_g703_line(line, stored, line_number=1, retainage_percent=RETENTION)
    assert row["previous_value"] == Decimal("40000.00")
    assert row["this_period_value"] == Decimal("20000.00")
    assert row["total_completed_stored"] == Decimal("60000.00")

    summary = build_g702_summary(
        [row],
        original_contract_sum=Decimal("100000"),
        previous_certificates_total=first["gross"] - first["retention"],
        previous_certificates_basis="reconstructed",
    )
    assert summary["retainage"] == Decimal("6000.00")
    assert summary["total_earned_less_retainage"] == Decimal("54000.00")
    assert summary["previous_certificates_total"] == Decimal("36000.00")
    assert summary["current_payment_due"] == Decimal("18000.00")
    assert summary["current_payment_due"] == second["net"]
    assert summary["previous_certificates_basis"] == "reconstructed"
