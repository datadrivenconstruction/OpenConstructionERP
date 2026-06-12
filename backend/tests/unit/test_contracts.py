"""Unit tests for the Contract Types Engine.

Covers:
    * Pure helpers: validate_contract_terms, compute_line_total,
      compute_contract_total (with hierarchical SoV), compute_progress_claim_total,
      compute_gmp_gainshare, compute_ld_amount, apply_change_order pure helper.
    * Type-specific claim generators (lump_sum / cost_plus / tm / unit_price).
    * Service-level transitions and event emission (mocked event bus).
    * State machines (Contract / ProgressClaim / FinalAccount).
    * Permission registration on module startup.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.modules.contracts import service as contracts_service
from app.modules.contracts.service import (
    _REQUIRED_TERM_FIELDS,
    ContractsService,
    InvalidTransitionError,
    NTECapExceededError,
    allowed_claim_transitions,
    allowed_contract_transitions,
    allowed_final_account_transitions,
    apply_change_order_to_contract_pure,
    assert_claim_transition,
    assert_contract_transition,
    assert_final_account_transition,
    compute_contract_total,
    compute_gmp_gainshare,
    compute_ld_amount,
    compute_line_total,
    compute_progress_claim_total,
    generate_cost_plus_claim,
    generate_lump_sum_claim,
    generate_tm_claim,
    generate_unit_price_claim,
    validate_contract_terms,
)

PROJECT_ID = uuid.uuid4()


# ── Stub helpers ─────────────────────────────────────────────────────────


def _line(
    *,
    id: uuid.UUID | None = None,
    parent_line_id: uuid.UUID | None = None,
    quantity: float | Decimal = Decimal("0"),
    unit_rate: float | Decimal = Decimal("0"),
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id or uuid.uuid4(),
        parent_line_id=parent_line_id,
        quantity=Decimal(str(quantity)),
        unit_rate=Decimal(str(unit_rate)),
    )


def _contract(
    *,
    contract_type: str = "lump_sum",
    retention_percent: float | Decimal = Decimal("5"),
    total_value: float | Decimal = Decimal("0"),
    terms: dict[str, Any] | None = None,
    status: str = "draft",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        contract_type=contract_type,
        retention_percent=Decimal(str(retention_percent)),
        total_value=Decimal(str(total_value)),
        terms=terms or {},
        status=status,
    )


# ── validate_contract_terms ──────────────────────────────────────────────


def test_validate_contract_terms_lump_sum_no_required() -> None:
    ok, errors = validate_contract_terms("lump_sum", {})
    assert ok is True
    assert errors == []


def test_validate_contract_terms_gmp_success() -> None:
    ok, errors = validate_contract_terms(
        "gmp",
        {"gmp_cap": "1000000", "target_cost": "900000"},
    )
    assert ok is True
    assert errors == []


def test_validate_contract_terms_gmp_missing_field() -> None:
    ok, errors = validate_contract_terms("gmp", {"gmp_cap": "1000000"})
    assert ok is False
    assert any("target_cost" in e for e in errors)


def test_validate_contract_terms_cost_plus_requires_fee_percent() -> None:
    ok, errors = validate_contract_terms("cost_plus", {})
    assert ok is False
    assert any("fee_percent" in e for e in errors)


def test_validate_contract_terms_tm_requires_nte_cap() -> None:
    ok, errors = validate_contract_terms("tm", {})
    assert ok is False
    assert any("tm_nte_cap" in e for e in errors)


def test_validate_contract_terms_rejects_unknown_type() -> None:
    ok, errors = validate_contract_terms("bogus_type", {})
    assert ok is False
    assert any("unknown contract_type" in e for e in errors)


def test_validate_contract_terms_rejects_negative_value() -> None:
    ok, errors = validate_contract_terms("cost_plus", {"fee_percent": "-3"})
    assert ok is False


def test_required_term_fields_completeness() -> None:
    # Every contract type must be in the required-fields map.
    for t in (
        "lump_sum",
        "gmp",
        "cost_plus",
        "tm",
        "unit_price",
        "design_build",
        "combination",
    ):
        assert t in _REQUIRED_TERM_FIELDS


# ── compute_line_total / compute_contract_total ──────────────────────────


def test_compute_line_total() -> None:
    assert compute_line_total(_line(quantity=10, unit_rate="50")) == Decimal("500")


def test_compute_line_total_zero_inputs() -> None:
    assert compute_line_total(SimpleNamespace(quantity=None, unit_rate=None)) == Decimal("0")


def test_compute_contract_total_flat() -> None:
    lines = [
        _line(quantity=5, unit_rate=100),
        _line(quantity=10, unit_rate=20),
    ]
    assert compute_contract_total(lines) == Decimal("700")


def test_compute_contract_total_hierarchical_skips_parents() -> None:
    """Parent lines must NOT be summed — child line totals already cover them."""
    parent_id = uuid.uuid4()
    child_a = _line(parent_line_id=parent_id, quantity=4, unit_rate=200)  # 800
    child_b = _line(parent_line_id=parent_id, quantity=2, unit_rate=50)  # 100
    parent = _line(id=parent_id, quantity=999, unit_rate=999)  # would be 998001 if counted
    lines = [parent, child_a, child_b]
    # Only children should count.
    assert compute_contract_total(lines) == Decimal("900")


def test_compute_contract_total_empty() -> None:
    assert compute_contract_total([]) == Decimal("0")


# ── compute_progress_claim_total ─────────────────────────────────────────


def test_compute_progress_claim_total_basic() -> None:
    claim_lines = [
        SimpleNamespace(period_completed_value=Decimal("1000")),
        SimpleNamespace(period_completed_value=Decimal("500")),
    ]
    totals = compute_progress_claim_total(
        claim_lines,
        retention_percent=Decimal("5"),
        prior_claims_paid=Decimal("200"),
    )
    assert totals["gross"] == Decimal("1500")
    assert totals["retention"] == Decimal("75.0000")
    assert totals["net"] == Decimal("1225.0000")


def test_compute_progress_claim_total_net_clamped_at_zero() -> None:
    claim_lines = [SimpleNamespace(period_completed_value=Decimal("100"))]
    totals = compute_progress_claim_total(
        claim_lines,
        retention_percent=Decimal("10"),
        prior_claims_paid=Decimal("999"),
    )
    assert totals["net"] == Decimal("0")


# ── generate_lump_sum_claim ─────────────────────────────────────────────


def test_generate_lump_sum_claim_zero_completion() -> None:
    c = _contract(retention_percent=Decimal("5"))
    line = _line(quantity=10, unit_rate=100)
    result = generate_lump_sum_claim(c, [line], completion={str(line.id): Decimal("0")})
    assert result["gross"] == Decimal("0")
    assert result["net"] == Decimal("0")


def test_generate_lump_sum_claim_full_completion() -> None:
    c = _contract(retention_percent=Decimal("5"))
    line = _line(quantity=10, unit_rate=100)
    result = generate_lump_sum_claim(c, [line], completion={str(line.id): Decimal("100")})
    assert result["gross"] == Decimal("1000.0000")
    assert result["retention"] == Decimal("50.0000")
    assert result["net"] == Decimal("950.0000")


def test_generate_lump_sum_claim_partial_completion() -> None:
    c = _contract(retention_percent=Decimal("5"))
    line = _line(quantity=10, unit_rate=100)
    result = generate_lump_sum_claim(c, [line], completion={str(line.id): Decimal("40")})
    assert result["gross"] == Decimal("400.0000")
    assert result["retention"] == Decimal("20.0000")
    assert result["net"] == Decimal("380.0000")


def test_generate_lump_sum_claim_skips_parents() -> None:
    parent_id = uuid.uuid4()
    parent = _line(id=parent_id, quantity=100, unit_rate=100)  # would-be 10k
    child = _line(parent_line_id=parent_id, quantity=10, unit_rate=50)
    c = _contract(retention_percent=Decimal("0"))
    result = generate_lump_sum_claim(
        c,
        [parent, child],
        completion={str(child.id): Decimal("100")},
    )
    # Only the child contributes.
    assert result["gross"] == Decimal("500.0000")


# ── generate_cost_plus_claim ────────────────────────────────────────────


def test_generate_cost_plus_claim() -> None:
    c = _contract(contract_type="cost_plus", retention_percent=Decimal("5"))
    fee = {"fee_type": "percent_of_cost", "fee_percent": Decimal("10")}
    result = generate_cost_plus_claim(c, fee, Decimal("10000"))
    assert result["fee"] == Decimal("1000.0000")
    assert result["gross"] == Decimal("11000.0000")
    assert result["retention"] == Decimal("550.0000")
    assert result["net"] == Decimal("10450.0000")


def test_generate_cost_plus_claim_with_max_fee_cap() -> None:
    c = _contract(contract_type="cost_plus", retention_percent=Decimal("0"))
    fee = {
        "fee_type": "percent_of_cost",
        "fee_percent": Decimal("20"),
        "max_fee": Decimal("100"),
    }
    result = generate_cost_plus_claim(c, fee, Decimal("10000"))
    # 20% of 10000 = 2000, capped at 100.
    assert result["fee"] == Decimal("100")
    assert result["gross"] == Decimal("10100")


# ── generate_tm_claim ───────────────────────────────────────────────────


def test_generate_tm_claim_below_cap() -> None:
    c = _contract(
        contract_type="tm",
        retention_percent=Decimal("0"),
        terms={"tm_nte_cap": "10000"},
    )
    result = generate_tm_claim(
        c,
        time_entries_total=Decimal("3000"),
        material_entries_total=Decimal("2000"),
        fee_structure=None,
    )
    assert result["gross"] == Decimal("5000")
    assert result["net"] == Decimal("5000")


def test_generate_tm_claim_raises_nte_cap_exceeded() -> None:
    c = _contract(
        contract_type="tm",
        retention_percent=Decimal("0"),
        terms={"tm_nte_cap": "1000"},
    )
    with pytest.raises(NTECapExceededError):
        generate_tm_claim(
            c,
            time_entries_total=Decimal("800"),
            material_entries_total=Decimal("500"),
            fee_structure=None,
        )


def test_generate_tm_claim_with_fee_and_prior_paid() -> None:
    c = _contract(
        contract_type="tm",
        retention_percent=Decimal("5"),
        terms={"tm_nte_cap": "100000"},
    )
    fee = {"fee_type": "percent_of_cost", "fee_percent": Decimal("10")}
    result = generate_tm_claim(
        c,
        time_entries_total=Decimal("4000"),
        material_entries_total=Decimal("1000"),
        fee_structure=fee,
        prior_paid=Decimal("1000"),
    )
    # base = 5000, fee = 500, gross = 5500, retention = 275, prior = 1000, net = 4225
    assert result["fee"] == Decimal("500.0000")
    assert result["gross"] == Decimal("5500")
    assert result["retention"] == Decimal("275.0000")
    assert result["net"] == Decimal("4225.0000")


# ── generate_unit_price_claim ───────────────────────────────────────────


def test_generate_unit_price_claim() -> None:
    c = _contract(contract_type="unit_price", retention_percent=Decimal("5"))
    line = _line(quantity=100, unit_rate=50)  # contracted qty=100
    result = generate_unit_price_claim(
        c,
        [line],
        measurements={str(line.id): Decimal("30")},
    )
    # 30 measured × 50 rate = 1500 gross
    assert result["gross"] == Decimal("1500.0000")
    assert result["retention"] == Decimal("75.0000")
    assert result["net"] == Decimal("1425.0000")


# ── compute_gmp_gainshare ───────────────────────────────────────────────


def test_compute_gmp_gainshare_savings_case() -> None:
    out = compute_gmp_gainshare(
        actual_cost=Decimal("800000"),
        target_cost=Decimal("1000000"),
        gmp_cap=Decimal("1100000"),
        split_owner_pct=Decimal("60"),
        split_contractor_pct=Decimal("40"),
    )
    assert out["savings"] == Decimal("200000")
    assert out["owner_share"] == Decimal("120000.0000")
    assert out["contractor_share"] == Decimal("80000.0000")
    assert out["overrun"] == Decimal("0")


def test_compute_gmp_gainshare_overrun_case() -> None:
    out = compute_gmp_gainshare(
        actual_cost=Decimal("1200000"),
        target_cost=Decimal("1000000"),
        gmp_cap=Decimal("1100000"),
        split_owner_pct=Decimal("50"),
        split_contractor_pct=Decimal("50"),
    )
    assert out["savings"] == Decimal("0")
    assert out["owner_share"] == Decimal("0")
    assert out["contractor_share"] == Decimal("0")
    assert out["overrun"] == Decimal("100000")


def test_compute_gmp_gainshare_break_even() -> None:
    out = compute_gmp_gainshare(
        actual_cost=Decimal("1000000"),
        target_cost=Decimal("1000000"),
        gmp_cap=Decimal("1100000"),
        split_owner_pct=Decimal("50"),
        split_contractor_pct=Decimal("50"),
    )
    assert out["savings"] == Decimal("0")
    assert out["overrun"] == Decimal("0")


def test_compute_gmp_gainshare_within_buffer_zone() -> None:
    """Actual between target and cap — no savings, no overrun."""
    out = compute_gmp_gainshare(
        actual_cost=Decimal("1050000"),
        target_cost=Decimal("1000000"),
        gmp_cap=Decimal("1100000"),
        split_owner_pct=Decimal("50"),
        split_contractor_pct=Decimal("50"),
    )
    assert out["savings"] == Decimal("0")
    assert out["overrun"] == Decimal("0")


# ── compute_ld_amount ───────────────────────────────────────────────────


def test_compute_ld_amount_below_cap() -> None:
    assert compute_ld_amount(Decimal("500"), 10, Decimal("10000")) == Decimal("5000")


def test_compute_ld_amount_capped() -> None:
    assert compute_ld_amount(Decimal("500"), 100, Decimal("10000")) == Decimal("10000")


def test_compute_ld_amount_zero_days() -> None:
    assert compute_ld_amount(Decimal("500"), 0, Decimal("10000")) == Decimal("0")


def test_compute_ld_amount_no_cap() -> None:
    assert compute_ld_amount(Decimal("500"), 100, None) == Decimal("50000")


# ── apply_change_order_to_contract_pure ─────────────────────────────────


def test_apply_change_order_to_contract_pure_increment() -> None:
    assert apply_change_order_to_contract_pure(
        Decimal("100000"),
        Decimal("25000"),
    ) == Decimal("125000")


def test_apply_change_order_to_contract_pure_negative() -> None:
    assert apply_change_order_to_contract_pure(
        Decimal("100000"),
        Decimal("-10000"),
    ) == Decimal("90000")


# ── State-machine transitions ───────────────────────────────────────────


def test_contract_transitions_happy_path() -> None:
    assert "active" in allowed_contract_transitions("draft")
    assert "suspended" in allowed_contract_transitions("active")
    assert "active" in allowed_contract_transitions("suspended")
    assert "completed" in allowed_contract_transitions("active")


def test_contract_transitions_terminal_no_exit() -> None:
    assert allowed_contract_transitions("completed") == frozenset()
    assert allowed_contract_transitions("terminated") == frozenset()


def test_contract_transition_invalid_raises() -> None:
    with pytest.raises(InvalidTransitionError):
        assert_contract_transition("draft", "completed")
    with pytest.raises(InvalidTransitionError):
        assert_contract_transition("completed", "draft")


def test_claim_transitions_pipeline() -> None:
    assert "submitted" in allowed_claim_transitions("draft")
    assert "approved" in allowed_claim_transitions("submitted")
    assert "certified" in allowed_claim_transitions("approved")
    assert "paid" in allowed_claim_transitions("certified")
    assert allowed_claim_transitions("paid") == frozenset()


def test_claim_transition_invalid_raises() -> None:
    with pytest.raises(InvalidTransitionError):
        assert_claim_transition("draft", "paid")


def test_final_account_transitions() -> None:
    assert "agreed" in allowed_final_account_transitions("draft")
    assert "closed" in allowed_final_account_transitions("agreed")
    assert allowed_final_account_transitions("closed") == frozenset()


def test_final_account_transition_invalid_raises() -> None:
    with pytest.raises(InvalidTransitionError):
        assert_final_account_transition("closed", "draft")


# ── Permission registration ─────────────────────────────────────────────


def test_permissions_registered() -> None:
    from app.core.permissions import permission_registry
    from app.modules.contracts.permissions import register_contracts_permissions

    register_contracts_permissions()
    expected = {
        "contracts.read",
        "contracts.create",
        "contracts.update",
        "contracts.delete",
        "contracts.sign",
        "contracts.terminate",
        "contracts.submit_claim",
        "contracts.approve_claim",
        "contracts.certify_claim",
        "contracts.mark_paid",
        "contracts.close",
    }
    # Use the real registry contract (list_modules → {module: [perms]}),
    # not a hasattr fallback that silently weakens the assertion.
    registered = set(permission_registry.list_modules().get("contracts", []))
    assert expected.issubset(registered)


# ── apply_change_order_to_contract (service, with event emission) ───────


class _StubContractRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def get_by_id(self, contract_id: uuid.UUID) -> Any:
        return self.rows.get(contract_id)

    async def create(self, contract: Any) -> Any:
        if getattr(contract, "id", None) is None:
            contract.id = uuid.uuid4()
        self.rows[contract.id] = contract
        return contract

    async def update_fields(self, contract_id: uuid.UUID, **fields: Any) -> None:
        obj = self.rows.get(contract_id)
        if obj:
            for k, v in fields.items():
                setattr(obj, k, v)


class _StubLineRepo:
    """SoV line lookup for the compliance gate. Empty by default."""

    def __init__(self, lines: list[Any] | None = None) -> None:
        self.lines = lines or []

    async def list_for_contract(self, _contract_id: uuid.UUID) -> list[Any]:
        return list(self.lines)


class _StubSession:
    def __init__(self, project: Any | None = None) -> None:
        self._project = project

    async def get(self, _model: Any, _pk: Any) -> Any:
        return self._project

    async def refresh(self, obj: Any) -> None:
        pass


def _stub_service() -> ContractsService:
    svc = ContractsService.__new__(ContractsService)
    svc.session = _StubSession()
    svc.contract_repo = _StubContractRepo()
    svc.line_repo = _StubLineRepo()
    return svc


@pytest.mark.asyncio
async def test_apply_change_order_increments_value_and_emits_event() -> None:
    svc = _stub_service()
    contract_id = uuid.uuid4()
    svc.contract_repo.rows[contract_id] = SimpleNamespace(
        id=contract_id,
        total_value=Decimal("100000"),
        status="active",
        metadata_={},
    )
    mock_publish = MagicMock()
    with patch.object(contracts_service.event_bus, "publish_detached", mock_publish):
        await svc.apply_change_order_to_contract(
            contract_id,
            Decimal("25000"),
            co_schedule_days=14,
            co_reference="CO-1",
        )
    row = svc.contract_repo.rows[contract_id]
    assert row.total_value == Decimal("125000")
    # Audit m7: the service path stamps the same rollup metadata as the
    # changeorder.approved subscriber so both paths stay consistent.
    assert row.metadata_["change_order_ids"] == ["CO-1"]
    assert Decimal(row.metadata_["change_order_total"]) == Decimal("25000")
    assert mock_publish.called
    args = mock_publish.call_args
    assert args.args[0] == "contracts.contract.amended"


@pytest.mark.asyncio
async def test_apply_change_order_rollup_key_survives_zero_net() -> None:
    """Offsetting COs net to zero but keep the rollup key present.

    Audit m7: AIA G702 decides rollup-vs-terms by KEY presence, so a
    legitimately zero rollup must not resurrect a stale manual figure.
    """
    svc = _stub_service()
    contract_id = uuid.uuid4()
    svc.contract_repo.rows[contract_id] = SimpleNamespace(
        id=contract_id,
        total_value=Decimal("100000"),
        status="active",
        metadata_={},
    )
    with patch.object(contracts_service.event_bus, "publish_detached", MagicMock()):
        await svc.apply_change_order_to_contract(contract_id, Decimal("10000"), co_reference="CO-1")
        await svc.apply_change_order_to_contract(contract_id, Decimal("-10000"), co_reference="CO-2")
    row = svc.contract_repo.rows[contract_id]
    assert row.total_value == Decimal("100000")
    assert row.metadata_["change_order_ids"] == ["CO-1", "CO-2"]
    assert "change_order_total" in row.metadata_
    assert Decimal(row.metadata_["change_order_total"]) == Decimal("0")


@pytest.mark.asyncio
async def test_transition_contract_emits_signed_event() -> None:
    svc = _stub_service()
    contract_id = uuid.uuid4()
    svc.contract_repo.rows[contract_id] = SimpleNamespace(
        id=contract_id,
        code="CT-X",
        project_id=PROJECT_ID,
        total_value=Decimal("0"),
        status="draft",
        signed_at=None,
        metadata_={},
    )
    mock_publish = MagicMock()
    with patch.object(contracts_service.event_bus, "publish_detached", mock_publish):
        await svc.transition_contract(contract_id, "active", actor_id="user-1")
    assert svc.contract_repo.rows[contract_id].status == "active"
    event_names = [c.args[0] for c in mock_publish.call_args_list]
    assert "contracts.contract.signed" in event_names


@pytest.mark.asyncio
async def test_transition_contract_invalid_raises_http_400() -> None:
    from fastapi import HTTPException

    svc = _stub_service()
    contract_id = uuid.uuid4()
    svc.contract_repo.rows[contract_id] = SimpleNamespace(
        id=contract_id,
        status="completed",
        total_value=Decimal("0"),
    )
    with pytest.raises(HTTPException) as exc:
        await svc.transition_contract(contract_id, "draft", actor_id="u")
    assert exc.value.status_code == 400


# ── New (Wave-5): SOV / retention / lien waiver / clause templates ──────


def test_compute_sov_status_aggregates_by_line() -> None:
    """Each contract line shows scheduled vs earned vs billed vs paid."""
    from app.modules.contracts.service import compute_sov_status

    line_a = SimpleNamespace(id=uuid.uuid4(), quantity=Decimal("100"), unit_rate=Decimal("10"))
    line_b = SimpleNamespace(id=uuid.uuid4(), quantity=Decimal("50"), unit_rate=Decimal("20"))
    # 30 units billed on A in a paid claim, 10 units billed on B in submitted (earned not paid)
    cl_a_paid = SimpleNamespace(
        contract_line_id=line_a.id,
        period_completed_value=Decimal("300"),
        _claim_status="paid",
    )
    cl_b_submitted = SimpleNamespace(
        contract_line_id=line_b.id,
        period_completed_value=Decimal("200"),
        _claim_status="submitted",
    )
    result = compute_sov_status(
        [line_a, line_b],
        [cl_a_paid, cl_b_submitted],
        retention_percent=Decimal("5"),
    )
    a_row = result["by_line"][str(line_a.id)]
    b_row = result["by_line"][str(line_b.id)]
    assert a_row["scheduled"] == Decimal("1000")
    assert a_row["paid"] == Decimal("300")
    assert a_row["earned"] == Decimal("300")
    assert a_row["billed"] == Decimal("300")
    assert b_row["earned"] == Decimal("200")
    assert b_row["billed"] == Decimal("0")  # submitted but not approved → not billed
    assert b_row["paid"] == Decimal("0")
    # Totals
    assert result["totals"]["scheduled"] == Decimal("2000")
    assert result["totals"]["earned"] == Decimal("500")


def test_plan_retention_release_default_substantial_completion() -> None:
    from app.modules.contracts.service import plan_retention_release

    result = plan_retention_release(Decimal("10000"), "substantial_completion")
    assert result["percent_released"] == Decimal("50")
    assert result["amount_released"] == Decimal("5000.0000")
    assert result["remaining"] == Decimal("5000.0000")


def test_plan_retention_release_zero_held_is_zero_out() -> None:
    from app.modules.contracts.service import plan_retention_release

    result = plan_retention_release(0, "substantial_completion")
    assert result["amount_released"] == Decimal("0")
    assert result["remaining"] == Decimal("0")


def test_plan_retention_release_unknown_event_zero_release() -> None:
    from app.modules.contracts.service import plan_retention_release

    result = plan_retention_release(Decimal("10000"), "unknown_event")
    assert result["percent_released"] == Decimal("0")
    assert result["amount_released"] == Decimal("0")


def test_plan_retention_release_custom_schedule() -> None:
    from app.modules.contracts.service import plan_retention_release

    result = plan_retention_release(
        Decimal("20000"),
        "milestone_3",
        schedule={"milestone_3": Decimal("25")},
    )
    assert result["percent_released"] == Decimal("25")
    assert result["amount_released"] == Decimal("5000.0000")


def test_validate_lien_waiver_payload_happy() -> None:
    from app.modules.contracts.service import validate_lien_waiver_payload

    ok, errors = validate_lien_waiver_payload(
        {
            "waiver_type": "conditional_partial",
            "through_date": "2026-05-31",
            "amount": "10000",
            "signed_by": "GC Treasurer",
        }
    )
    assert ok is True
    assert errors == []


def test_validate_lien_waiver_payload_rejects_bad_type() -> None:
    from app.modules.contracts.service import validate_lien_waiver_payload

    ok, errors = validate_lien_waiver_payload(
        {
            "waiver_type": "random",
            "through_date": "2026-05-31",
            "amount": "10000",
            "signed_by": "GC",
        }
    )
    assert ok is False
    assert any("waiver_type" in e for e in errors)


def test_validate_lien_waiver_payload_rejects_negative_amount() -> None:
    from app.modules.contracts.service import validate_lien_waiver_payload

    ok, errors = validate_lien_waiver_payload(
        {
            "waiver_type": "unconditional_final",
            "through_date": "2026-05-31",
            "amount": "-1",
            "signed_by": "GC",
        }
    )
    assert ok is False
    assert any("non-negative" in e for e in errors)


def test_list_contract_templates_includes_fidic_jct_aia() -> None:
    from app.modules.contracts.service import list_contract_templates

    codes = {t["code"] for t in list_contract_templates()}
    assert "fidic_red_1999" in codes
    assert "jct_standard_2016" in codes
    assert "aia_a201_2017" in codes
    assert "nec4_ecc_option_a" in codes


def test_get_contract_template_returns_clauses() -> None:
    from app.modules.contracts.service import get_contract_template

    body = get_contract_template("fidic_red_1999")
    assert body["family"] == "fidic"
    assert "14" in body["key_clauses"]
    assert "Payment" in body["key_clauses"]["14"]


def test_get_contract_template_unknown_raises_key_error() -> None:
    from app.modules.contracts.service import get_contract_template

    with pytest.raises(KeyError):
        get_contract_template("does_not_exist")


# ── Claim certify emits event + stamps certifier (cross-module money) ────


class _StubClaimRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def get_by_id(self, claim_id: uuid.UUID) -> Any:
        return self.rows.get(claim_id)

    async def update_fields(self, claim_id: uuid.UUID, **fields: Any) -> None:
        obj = self.rows.get(claim_id)
        if obj:
            for k, v in fields.items():
                setattr(obj, k, v)


def _stub_claim_service() -> ContractsService:
    svc = ContractsService.__new__(ContractsService)
    svc.session = _StubSession()
    svc.claim_repo = _StubClaimRepo()
    return svc


@pytest.mark.asyncio
async def test_transition_claim_certified_emits_event_and_stamps_certifier() -> None:
    svc = _stub_claim_service()
    claim_id = uuid.uuid4()
    svc.claim_repo.rows[claim_id] = SimpleNamespace(
        id=claim_id,
        contract_id=uuid.uuid4(),
        claim_number="PC-0001",
        net_due=Decimal("9500"),
        status="approved",
        metadata_={},
    )
    mock_publish = MagicMock()
    with patch.object(contracts_service.event_bus, "publish_detached", mock_publish):
        await svc.transition_claim(claim_id, "certified", actor_id="qs-7")
    row = svc.claim_repo.rows[claim_id]
    assert row.status == "certified"
    assert row.metadata_["certified_by"] == "qs-7"
    assert row.metadata_["certified_at"]
    event_names = [c.args[0] for c in mock_publish.call_args_list]
    assert "contracts.claim.certified" in event_names


# ── update_contract: financial-terms lock + status guard ────────────────


class _StubContractRepoRows(_StubContractRepo):
    pass


def _stub_update_service() -> ContractsService:
    svc = ContractsService.__new__(ContractsService)
    svc.session = _StubSession()
    svc.contract_repo = _StubContractRepoRows()
    return svc


def _contract_update(**kwargs: Any) -> Any:
    from app.modules.contracts.schemas import ContractUpdate

    return ContractUpdate(**kwargs)


@pytest.mark.asyncio
async def test_update_contract_locks_financial_terms_when_active() -> None:
    from fastapi import HTTPException

    svc = _stub_update_service()
    cid = uuid.uuid4()
    svc.contract_repo.rows[cid] = SimpleNamespace(
        id=cid,
        status="active",
        contract_type="lump_sum",
        terms={},
        total_value=Decimal("100000"),
    )
    with pytest.raises(HTTPException) as exc:
        await svc.update_contract(cid, _contract_update(total_value=Decimal("250000")))
    assert exc.value.status_code == 409
    assert exc.value.detail["error"] == "financial_terms_locked"


@pytest.mark.asyncio
async def test_update_contract_allows_title_when_active() -> None:
    svc = _stub_update_service()
    cid = uuid.uuid4()
    svc.contract_repo.rows[cid] = SimpleNamespace(
        id=cid,
        status="active",
        contract_type="lump_sum",
        terms={},
        total_value=Decimal("100000"),
        title="Old",
    )
    await svc.update_contract(cid, _contract_update(title="New title"))
    assert svc.contract_repo.rows[cid].title == "New title"


@pytest.mark.asyncio
async def test_update_contract_allows_financial_edit_while_draft() -> None:
    svc = _stub_update_service()
    cid = uuid.uuid4()
    svc.contract_repo.rows[cid] = SimpleNamespace(
        id=cid,
        status="draft",
        contract_type="lump_sum",
        terms={},
        total_value=Decimal("0"),
    )
    await svc.update_contract(cid, _contract_update(total_value=Decimal("500000")))
    assert svc.contract_repo.rows[cid].total_value == Decimal("500000")


@pytest.mark.asyncio
async def test_update_contract_rejects_direct_status_change() -> None:
    from fastapi import HTTPException

    svc = _stub_update_service()
    cid = uuid.uuid4()
    svc.contract_repo.rows[cid] = SimpleNamespace(
        id=cid,
        status="draft",
        contract_type="lump_sum",
        terms={},
        total_value=Decimal("0"),
    )
    with pytest.raises(HTTPException) as exc:
        await svc.update_contract(cid, _contract_update(status="active"))
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "status_not_directly_editable"
