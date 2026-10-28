# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Abort exposure: each basis, unknown terms as ``None``, negative residual kept, schedules by date and progress."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.modules.commitment_release.catalogue import AbortBasis, register_kinds
from app.modules.commitment_release.exposure import ScheduleEntry, TermsInput, compute_exposure
from app.modules.project_governance.catalogue_kinds import get_catalogue_kind

D = Decimal
DAY = date(2026, 10, 11)
SUNK = {"paid": D("200000"), "invoiced_unpaid": D("50000"), "certified_not_invoiced": D("0")}


def _basis(basis_id: str) -> AbortBasis:
    register_kinds()
    return get_catalogue_kind("abort_basis").get_shipped(basis_id)


def test_unknown_terms_give_none_not_zero() -> None:
    e = compute_exposure(committed=D("1000000"), sunk_parts=SUNK, terms=None, basis=None, as_of=DAY)
    assert e.residual_loss is None
    assert e.reason == "abort_terms_missing"
    assert e.sunk == D("250000")
    assert e.committed_not_spent == D("750000")


def test_bgb_648_presumes_five_percent_of_the_unperformed_part() -> None:
    e = compute_exposure(
        committed=D("1000000"),
        sunk_parts=SUNK,
        terms=TermsInput(basis_code="de_bgb_648"),
        basis=_basis("de_bgb_648"),
        as_of=DAY,
    )
    # unperformed 750000 x 0.05 = 37500; residual = 250000 + 37500
    assert e.cancellation_charge == D("37500.00")
    assert e.residual_loss == D("287500.00")
    # Decision e: a statutory basis is never applied silently.
    assert e.basis_review_status == "unconfirmed"


def test_bgb_648_with_documented_saved_costs_uses_price_less_saved_costs() -> None:
    e = compute_exposure(
        committed=D("1000000"),
        sunk_parts=SUNK,
        terms=TermsInput(basis_code="de_bgb_648", saved_cost=D("600000")),
        basis=_basis("de_bgb_648"),
        as_of=DAY,
    )
    assert e.cancellation_charge == D("150000")


def test_a_contract_parameter_missing_makes_the_residual_unknown() -> None:
    e = compute_exposure(
        committed=D("1000000"),
        sunk_parts=SUNK,
        terms=TermsInput(basis_code="nec4_ecc_client_reason"),
        basis=_basis("nec4_ecc_client_reason"),
        as_of=DAY,
    )
    assert e.residual_loss is None
    assert e.reason == "abort_terms_incomplete"


def test_nec4_fee_comes_from_the_terms() -> None:
    e = compute_exposure(
        committed=D("1000000"),
        sunk_parts=SUNK,
        terms=TermsInput(basis_code="nec4_ecc_client_reason", parameters={"fee_pct": "0.10"}),
        basis=_basis("nec4_ecc_client_reason"),
        as_of=DAY,
    )
    assert e.cancellation_charge == D("75000.00")


def test_far_convenience_is_profit_on_work_done_plus_settlement_costs() -> None:
    e = compute_exposure(
        committed=D("1000000"),
        sunk_parts=SUNK,
        terms=TermsInput(basis_code="far_49_convenience", parameters={"profit_pct": "0.08"}, other_charge=D("5000")),
        basis=_basis("far_49_convenience"),
        as_of=DAY,
    )
    assert e.cancellation_charge == D("25000.00")


def test_a_negative_residual_is_shown_with_its_sign() -> None:
    e = compute_exposure(
        committed=D("100000"),
        sunk_parts={"paid": D("10000")},
        terms=TermsInput(basis_code="none_free_cancellation", transfer_value=D("8000"), salvage_value=D("7000")),
        basis=_basis("none_free_cancellation"),
        as_of=DAY,
    )
    assert e.residual_loss == D("-5000")


SCHEDULE = (
    ScheduleEntry("order", from_date=date(2026, 9, 1), charge_pct=D("0.10")),
    ScheduleEntry("fabrication", from_date=date(2026, 11, 1), charge_pct=D("0.50")),
    ScheduleEntry("shipped", progress_pct=D("0.9"), charge_amount=D("95000")),
)


@pytest.mark.parametrize(
    ("as_of", "progress", "charge"),
    [
        (date(2026, 8, 31), None, "0"),
        (date(2026, 10, 11), None, "10000.00"),
        (date(2026, 11, 1), None, "50000.00"),
        (date(2026, 10, 11), D("0.95"), "95000"),
    ],
)
def test_cancellation_schedule_by_date_and_by_progress(as_of: date, progress: Decimal | None, charge: str) -> None:
    e = compute_exposure(
        committed=D("100000"),
        sunk_parts={},
        terms=TermsInput(basis_code="supply_cancellation_schedule", cancellation_schedule=SCHEDULE),
        basis=_basis("supply_cancellation_schedule"),
        as_of=as_of,
        progress_pct=progress,
    )
    assert e.cancellation_charge == D(charge)
    assert e.method == "schedule"


def test_custom_basis_without_a_figure_is_unknown() -> None:
    e = compute_exposure(
        committed=D("1"), sunk_parts={}, terms=TermsInput(basis_code="custom"), basis=_basis("custom"), as_of=DAY
    )
    assert e.residual_loss is None


def test_nothing_committed_and_nothing_spent_loses_nothing_whatever_the_salvage() -> None:
    """Review finding 18: a planned item with a salvage estimate showed a residual loss of -60000."""
    terms = TermsInput(basis_code="supply_cancellation_schedule", salvage_value=D("60000"))
    e = compute_exposure(
        committed=D("0"),
        sunk_parts={"paid": D("0"), "invoiced_unpaid": D("0"), "certified_not_invoiced": D("0")},
        terms=terms,
        basis=_basis("supply_cancellation_schedule"),
        as_of=DAY,
    )
    assert e.residual_loss == D("0")
    assert e.recoverable == D("0")
    assert {"code": "nothing_committed", "amount": "0"} in e.lines
