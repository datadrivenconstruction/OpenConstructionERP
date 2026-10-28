# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠DB-free unit tests for the final-account readiness checklist helper.

These exercise the pure evaluator in ``app.modules.contracts.final_account``
directly with plain :class:`ClosureFacts` value objects, so no database, ORM or
FastAPI machinery is involved.
"""

from decimal import Decimal

from app.modules.contracts.final_account import (
    CHECK_EOT_CLAIMS_DECIDED,
    CHECK_FINAL_CERTIFICATE_ISSUED,
    CHECK_FINAL_VALUE_RECONCILED,
    CHECK_PROGRESS_CLAIMS_SETTLED,
    CHECK_RETENTION_RELEASED,
    CHECK_SECURITIES_RELEASED,
    STATUS_FAIL,
    STATUS_NA,
    STATUS_PASS,
    ChecklistItem,
    ClosureFacts,
    completion_percent,
    evaluate_final_account_readiness,
)


def _ready_facts(**overrides: object) -> ClosureFacts:
    """Facts under which every applicable check passes (contract fully ready)."""
    base: dict[str, object] = {
        "contract_total_value": Decimal("1000000.00"),
        "open_progress_claim_count": 0,
        "total_progress_claim_count": 4,
        "pending_eot_count": 0,
        "total_eot_count": 2,
        "outstanding_security_count": 0,
        "total_security_count": 3,
        "retention_held": Decimal("50000.00"),
        "retention_released": Decimal("50000.00"),
        "final_account_present": True,
        "final_account_agreed": True,
        "final_account_signed_off": True,
        "final_account_value": Decimal("1000000.00"),
    }
    base.update(overrides)
    return ClosureFacts(**base)  # type: ignore[arg-type]


def _item(result: object, key: str) -> ChecklistItem:
    """Fetch the single checklist item with ``key`` (fails loudly if absent)."""
    matches = [i for i in result.items if i.key == key]  # type: ignore[attr-defined]
    assert len(matches) == 1
    return matches[0]


def test_all_checks_pass_is_ready() -> None:
    result = evaluate_final_account_readiness(_ready_facts())
    assert result.ready is True
    assert result.total_count == 6
    assert result.applicable_count == 6
    assert result.passed_count == 6
    assert result.completion_percent == Decimal("100")
    assert all(item.status == STATUS_PASS for item in result.items)


def test_one_failing_check_blocks_readiness() -> None:
    # Two progress claims are still open -> that single check fails.
    result = evaluate_final_account_readiness(_ready_facts(open_progress_claim_count=2))
    assert result.ready is False
    item = _item(result, CHECK_PROGRESS_CLAIMS_SETTLED)
    assert item.status == STATUS_FAIL
    assert item.based_on["open_claim_count"] == "2"
    assert item.based_on["total_claim_count"] == "4"
    # Five of six checks still pass; percentage is over applicable checks.
    assert result.passed_count == 5
    assert result.applicable_count == 6
    assert result.completion_percent == Decimal("83.33")


def test_not_applicable_checks_excluded_from_percentage() -> None:
    # No EOT claims, no securities and no retention -> those three are N/A and
    # must not count toward the completion percentage.
    facts = _ready_facts(
        total_eot_count=0,
        pending_eot_count=0,
        total_security_count=0,
        outstanding_security_count=0,
        retention_held=Decimal("0"),
        retention_released=Decimal("0"),
    )
    result = evaluate_final_account_readiness(facts)
    na_keys = {i.key for i in result.items if i.status == STATUS_NA}
    assert na_keys == {
        CHECK_EOT_CLAIMS_DECIDED,
        CHECK_SECURITIES_RELEASED,
        CHECK_RETENTION_RELEASED,
    }
    # Only three checks apply (progress claims, final certificate, reconciliation)
    # and all pass, so the percentage is 3/3 not 3/6.
    assert result.applicable_count == 3
    assert result.passed_count == 3
    assert result.completion_percent == Decimal("100")
    assert result.ready is True


def test_no_final_account_fails_certificate_and_na_reconciliation() -> None:
    facts = _ready_facts(
        final_account_present=False,
        final_account_agreed=False,
        final_account_signed_off=False,
        final_account_value=Decimal("0"),
    )
    result = evaluate_final_account_readiness(facts)
    cert = _item(result, CHECK_FINAL_CERTIFICATE_ISSUED)
    recon = _item(result, CHECK_FINAL_VALUE_RECONCILED)
    assert cert.status == STATUS_FAIL
    assert recon.status == STATUS_NA
    assert result.ready is False


def test_completion_percent_zero_applicable_is_guarded() -> None:
    # The guard: applicable == 0 returns Decimal(0), never a ZeroDivisionError.
    assert completion_percent(0, 0) == Decimal("0")
    assert completion_percent(3, 0) == Decimal("0")


def test_completion_percent_basic_ratios() -> None:
    assert completion_percent(6, 6) == Decimal("100")
    assert completion_percent(5, 6) == Decimal("83.33")
    assert completion_percent(1, 3) == Decimal("33.33")
    assert completion_percent(0, 4) == Decimal("0")


def test_retention_reconciliation_is_decimal_exact() -> None:
    # Released is short of held by exactly one ten-thousandth. A float path would
    # smear this remainder; Decimal keeps it exact.
    facts = _ready_facts(
        retention_held=Decimal("1000.0002"),
        retention_released=Decimal("1000.0001"),
    )
    result = evaluate_final_account_readiness(facts)
    item = _item(result, CHECK_RETENTION_RELEASED)
    assert item.status == STATUS_FAIL
    assert item.based_on["retention_outstanding"] == "0.0001"
    assert result.ready is False


def test_retention_fully_released_boundary_passes() -> None:
    # Released exactly equals held -> outstanding is zero -> pass (boundary).
    facts = _ready_facts(
        retention_held=Decimal("50000.0000"),
        retention_released=Decimal("50000.0000"),
    )
    item = _item(evaluate_final_account_readiness(facts), CHECK_RETENTION_RELEASED)
    assert item.status == STATUS_PASS
    assert Decimal(item.based_on["retention_outstanding"]) == Decimal("0")


def test_final_value_reconciles_when_certified_equals_final_value() -> None:
    # Boundary: agreed final value exactly equals the contract sum to date.
    facts = _ready_facts(
        final_account_value=Decimal("1234567.89"),
        contract_total_value=Decimal("1234567.89"),
    )
    item = _item(evaluate_final_account_readiness(facts), CHECK_FINAL_VALUE_RECONCILED)
    assert item.status == STATUS_PASS
    assert Decimal(item.based_on["difference"]) == Decimal("0")


def test_final_value_mismatch_fails_with_exact_difference() -> None:
    facts = _ready_facts(
        final_account_value=Decimal("1000000.02"),
        contract_total_value=Decimal("1000000.00"),
    )
    result = evaluate_final_account_readiness(facts)
    item = _item(result, CHECK_FINAL_VALUE_RECONCILED)
    assert item.status == STATUS_FAIL
    assert item.based_on["difference"] == "0.02"
    assert result.ready is False


def test_eot_and_securities_pending_fail() -> None:
    facts = _ready_facts(
        pending_eot_count=1,
        total_eot_count=3,
        outstanding_security_count=2,
        total_security_count=2,
    )
    result = evaluate_final_account_readiness(facts)
    assert _item(result, CHECK_EOT_CLAIMS_DECIDED).status == STATUS_FAIL
    assert _item(result, CHECK_SECURITIES_RELEASED).status == STATUS_FAIL
    # Four pass, two fail -> 4/6 = 66.67, not ready.
    assert result.passed_count == 4
    assert result.applicable_count == 6
    assert result.completion_percent == Decimal("66.67")
    assert result.ready is False
