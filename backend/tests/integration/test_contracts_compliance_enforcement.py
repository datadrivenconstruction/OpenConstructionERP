# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Compliance-gate enforcement on the contract draft → active transition (Item #27).

The contract-signature gate runs the project's compliance rule packs (resolved
to validation rule sets) against the contract's schedule of values before the
``draft → active`` transition is allowed. These tests pin down:

1. A contract whose SoV has blocking compliance errors (a zero-quantity work
   line) is refused with HTTP 422 and stays in ``draft``. The blocking audit is
   written through a separate, isolated session, so the request session is left
   untouched and the 422 is not masked by a rollback-time 500.
2. A contract whose SoV is clean signs successfully, gets ``signed_at`` stamped
   and an audit trail with ``blocked=false`` recorded.
3. The gate maps SoV parent (roll-up) lines to ``section`` so the leaf-only
   ``boq_quality`` rules do not false-positive on header rows.

The tests drive ``ContractsService`` directly with in-memory stub repos so they
exercise the real validation engine and the real gate logic without a database.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.validation.rules import register_builtin_rules

# The validation engine needs its built-in rules registered (normally done at
# app startup). Idempotent — registering twice just overwrites.
register_builtin_rules()


# ── Stub repos / session ─────────────────────────────────────────────────


class _StubContractRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def get_by_id(self, contract_id: uuid.UUID) -> Any:
        return self.rows.get(contract_id)

    async def update_fields(self, contract_id: uuid.UUID, **fields: Any) -> None:
        obj = self.rows.get(contract_id)
        if obj:
            for k, v in fields.items():
                setattr(obj, k, v)


class _StubLineRepo:
    def __init__(self, lines: list[Any] | None = None) -> None:
        self.lines = lines or []

    async def list_for_contract(self, _contract_id: uuid.UUID) -> list[Any]:
        return list(self.lines)


class _StubRetentionRepo:
    """Signing now reads the contract's retention schedules and may write one.

    See ``ContractsService.seed_retention_schedule``: the country's retention
    ladder is frozen onto the contract at the same moment the contract value
    is. These stubs have no country between them, so nothing is written here,
    but the repo has to exist for the gate to be reached at all.
    """

    def __init__(self) -> None:
        self.rows: list[Any] = []

    async def list_for_contract(self, _contract_id: uuid.UUID) -> list[Any]:
        return list(self.rows)

    async def create(self, item: Any) -> Any:
        self.rows.append(item)
        return item


class _StubSession:
    def __init__(self, project: Any | None = None) -> None:
        self._project = project
        self.committed = False

    async def get(self, _model: Any, _pk: Any) -> Any:
        return self._project

    async def refresh(self, _obj: Any) -> None:
        pass

    async def commit(self) -> None:
        self.committed = True


def _line(
    *,
    code: str,
    quantity: str,
    unit_rate: str,
    parent_line_id: uuid.UUID | None = None,
) -> SimpleNamespace:
    qty = Decimal(quantity)
    rate = Decimal(unit_rate)
    return SimpleNamespace(
        id=uuid.uuid4(),
        code=code,
        description=f"Line {code}",
        unit="m2",
        quantity=qty,
        unit_rate=rate,
        total_value=qty * rate,
        parent_line_id=parent_line_id,
        metadata_={},
    )


def _make_service(*, contract: Any, lines: list[Any], project: Any) -> Any:
    from app.modules.contracts.service import ContractsService

    svc = ContractsService.__new__(ContractsService)
    svc.session = _StubSession(project=project)
    svc.contract_repo = _StubContractRepo()
    svc.contract_repo.rows[contract.id] = contract
    svc.line_repo = _StubLineRepo(lines)
    svc.retention_repo = _StubRetentionRepo()
    return svc


def _draft_contract() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        code="C-2026-001",
        project_id=uuid.uuid4(),
        status="draft",
        signed_at=None,
        # Signing freezes the contract value, and has since well before this
        # stub carried one: both tests that reach the transition have been red
        # on the missing attribute rather than on anything they assert.
        total_value=Decimal("2500"),
        contract_type="lump_sum",
        retention_percent=Decimal("10"),
        metadata_={},
    )


# ── 1. Blocking errors → 422, stays draft, audit recorded ─────────────────


@pytest.mark.asyncio
async def test_sign_blocked_on_compliance_errors() -> None:
    from fastapi import HTTPException

    contract = _draft_contract()
    # A zero-quantity work line trips boq_quality.position_has_quantity (ERROR).
    lines = [_line(code="01", quantity="0", unit_rate="100")]
    project = SimpleNamespace(
        id=contract.project_id,
        region="DACH",
        compliance_rule_packs=["universal"],
    )
    svc = _make_service(contract=contract, lines=lines, project=project)

    with pytest.raises(HTTPException) as exc:
        await svc.transition_contract(contract.id, "active", actor_id="u1")

    assert exc.value.status_code == 422
    detail = exc.value.detail
    assert detail["error"] == "compliance_gate_failed"
    assert detail["counts"]["errors"] >= 1
    assert any(e["rule_id"] == "boq_quality.position_has_quantity" for e in detail["errors"])
    # Contract must NOT have transitioned.
    assert contract.status == "draft"
    assert contract.signed_at is None
    # The blocking audit is persisted via a SEPARATE, isolated session
    # (async_session_factory) so the request session that the get_session
    # dependency rolls back on the raised 422 stays untouched. If we committed
    # the request session here and then raised, the dependency's rollback of an
    # already-committed transaction surfaced a misleading 500 instead of the
    # 422. So the request session must NOT be committed by the gate.
    assert svc.session.committed is False


# ── 2. Clean SoV → signs, signed_at + passing audit ──────────────────────


@pytest.mark.asyncio
async def test_sign_succeeds_when_compliant() -> None:
    contract = _draft_contract()
    lines = [
        _line(code="01", quantity="10", unit_rate="100"),
        _line(code="02", quantity="5", unit_rate="250"),
    ]
    project = SimpleNamespace(
        id=contract.project_id,
        region="DACH",
        compliance_rule_packs=["universal"],
    )
    svc = _make_service(contract=contract, lines=lines, project=project)

    result = await svc.transition_contract(contract.id, "active", actor_id="u1")

    assert result.status == "active"
    assert result.signed_at is not None
    audit = result.metadata_.get("compliance_validation")
    assert audit is not None
    assert audit["blocked"] is False
    assert audit["status"] in ("passed", "warnings")
    assert audit["counts"]["errors"] == 0
    # The retention seed stamp goes into the same metadata dict and must not
    # displace the audit above. This project names a market rather than a
    # country, DACH being three of them, so no pack answers for it and nothing
    # is written - which is the stamp saying so, not the stamp being absent.
    seed = result.metadata_["retention_policy_seed"]
    assert seed == {"seeded": False, "reason": "pack_silent", "country_code": None}
    assert svc.retention_repo.rows == []


# ── 3. Parent (roll-up) lines are treated as sections, not leaves ─────────


@pytest.mark.asyncio
async def test_parent_lines_not_validated_as_leaf_positions() -> None:
    """A parent SoV row legitimately has no quantity; it must not trip the
    zero-quantity rule. Only the leaf children are validated."""
    contract = _draft_contract()
    parent = _line(code="A", quantity="0", unit_rate="0")
    child = _line(
        code="A.1",
        quantity="12",
        unit_rate="50",
        parent_line_id=parent.id,
    )
    project = SimpleNamespace(
        id=contract.project_id,
        region="DACH",
        compliance_rule_packs=["universal"],
    )
    svc = _make_service(contract=contract, lines=[parent, child], project=project)

    result = await svc.transition_contract(contract.id, "active", actor_id="u1")

    # Parent zero-qty must NOT block — gate passes.
    assert result.status == "active"
    audit = result.metadata_["compliance_validation"]
    assert audit["blocked"] is False


# ── 4. run_compliance_gate is read-only / deterministic ──────────────────


@pytest.mark.asyncio
async def test_run_compliance_gate_is_side_effect_free() -> None:
    contract = _draft_contract()
    lines = [_line(code="01", quantity="0", unit_rate="100")]
    project = SimpleNamespace(
        id=contract.project_id,
        region="US",
        compliance_rule_packs=["us_compliance"],
    )
    svc = _make_service(contract=contract, lines=lines, project=project)

    report, pack_ids = await svc.run_compliance_gate(contract)
    report2, pack_ids2 = await svc.run_compliance_gate(contract)

    assert pack_ids == ["us_compliance"] == pack_ids2
    assert report.has_errors is True
    # Deterministic — same error count on a repeat run.
    assert len(report.errors) == len(report2.errors)
    # Read-only: nothing mutated, nothing committed.
    assert contract.status == "draft"
    assert svc.session.committed is False
