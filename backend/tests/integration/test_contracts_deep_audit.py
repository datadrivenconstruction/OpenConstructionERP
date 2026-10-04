# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Deep-audit regressions for the Contracts module (post-R5 sweep).

R5 closed the obvious IDOR holes and the financial-terms lock. This
suite pins down the remaining money-correctness and state-machine
hardening that R5 missed:

1. ``auto_generate_claim_lines`` must refuse to mutate a claim that has
   already left the ``draft`` lifecycle stage. Without the gate, calling
   the endpoint on a ``paid`` claim silently wipes its lines and
   rewrites gross/retention/net — corrupting the audit trail and
   double-spending retention.
2. ``attach_lien_waiver`` must refuse claims in ``draft`` or
   ``rejected`` state. Lien waivers are legally binding; attaching one
   to a draft is meaningless and to a rejected claim is fraud.
3-5. The retention release checks (no event released twice, custom
   schedule percentages refused rather than clamped, nothing released
   once everything is) moved to
   ``tests/modules/test_contracts_retention_release.py``. Releases are
   rows in their own table now, and a fake repository here would test the
   fake rather than the ledger.

Every fix lives in its own commit; this file is the regression net so
the next refactor can't quietly re-open the hole.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

# ── Stub repositories shared by these tests ──────────────────────────────


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


class _StubClaimRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}
        self.deleted_lines: list[uuid.UUID] = []

    async def get_by_id(self, claim_id: uuid.UUID) -> Any:
        return self.rows.get(claim_id)

    async def update_fields(self, claim_id: uuid.UUID, **fields: Any) -> None:
        obj = self.rows.get(claim_id)
        if obj:
            for k, v in fields.items():
                setattr(obj, k, v)

    async def paid_total(self, _contract_id: uuid.UUID) -> Decimal:
        return Decimal("0")

    async def prior_claims(self, contract_id: uuid.UUID, *, before_claim_id: uuid.UUID | None) -> list[Any]:
        """Every other non-rejected claim on the contract, in insertion order.

        The real repository orders by billing period and keeps only the claims
        strictly before ``before_claim_id``. This fake has no periods to order
        by, so it answers the way the old lookup did; a test that needs the
        order has outgrown it and belongs on a real repository.
        """
        return [
            row
            for row in self.rows.values()
            if row.contract_id == contract_id and row.id != before_claim_id and row.status != "rejected"
        ]

    async def outstanding_retention(self, _contract_id: uuid.UUID) -> Decimal:
        return Decimal("10000")


class _StubClaimLineRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def list_for_claim(self, claim_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if r.progress_claim_id == claim_id]

    async def delete(self, line_id: uuid.UUID) -> None:
        self.rows.pop(line_id, None)

    async def bulk_create(self, lines: list[Any]) -> list[Any]:
        for ln in lines:
            if getattr(ln, "id", None) is None:
                ln.id = uuid.uuid4()
            self.rows[ln.id] = ln
        return lines

    async def prior_period_value_by_line(
        self,
        _contract_id: uuid.UUID,
        *,
        before_claim_id: uuid.UUID | None,
    ) -> dict[uuid.UUID, Decimal]:
        """Period value already billed per contract line, from the rows held here.

        The real repository also drops lines belonging to rejected claims,
        which this cannot do: it holds claim lines and no claims, so it has no
        status to read. Every row it has is counted. A test that needs a
        rejected claim excluded has outgrown this fake and belongs on a real
        repository rather than on a status field invented here.
        """
        totals: dict[uuid.UUID, Decimal] = {}
        for row in self.rows.values():
            if before_claim_id is not None and row.progress_claim_id == before_claim_id:
                continue
            line_id = getattr(row, "contract_line_id", None)
            if line_id is None:
                continue
            totals[line_id] = totals.get(line_id, Decimal("0")) + Decimal(str(row.period_completed_value or 0))
        return totals


class _StubLineRepo:
    def __init__(self) -> None:
        self.rows: list[Any] = []

    async def list_for_contract(self, _contract_id: uuid.UUID) -> list[Any]:
        return list(self.rows)


class _StubFeeRepo:
    async def get_for_contract(self, _contract_id: uuid.UUID) -> Any:
        return None


class _StubSession:
    async def refresh(self, _obj: Any) -> None:
        pass

    async def get(self, _model: Any, _ident: Any) -> Any:
        # No project row behind the stub: a contract created here has no
        # country, so it starts from no country defaults.
        return None


class _StubRetentionScheduleRepo:
    async def list_for_contract(self, _contract_id: uuid.UUID) -> list[Any]:
        return []


class _StubReleaseRepo:
    async def list_for_contract(self, _contract_id: uuid.UUID) -> list[Any]:
        return []

    async def billed_on_claims(self, _claim_ids: list[uuid.UUID]) -> list[Any]:
        return []


def _make_service() -> Any:
    """Construct a ContractsService with the in-memory stub repos wired up."""
    from app.modules.contracts.service import ContractsService

    svc = ContractsService.__new__(ContractsService)
    svc.session = _StubSession()
    svc.contract_repo = _StubContractRepo()
    svc.claim_repo = _StubClaimRepo()
    svc.claim_line_repo = _StubClaimLineRepo()
    svc.line_repo = _StubLineRepo()
    svc.fee_repo = _StubFeeRepo()
    # Generation works retention out afterwards; no policy and no releases.
    svc.retention_repo = _StubRetentionScheduleRepo()
    svc.release_repo = _StubReleaseRepo()
    return svc


# ── 1. auto_generate_claim_lines must refuse non-draft claims ────────────


@pytest.mark.asyncio
async def test_auto_generate_claim_lines_rejects_paid_claim() -> None:
    """A paid claim's lines / totals are an immutable audit record.

    Pre-fix the service happily wiped existing lines and re-wrote
    gross_amount / retention_amount / net_due on a paid claim — silent
    money corruption that would break reconciliation against AR.
    """
    from fastapi import HTTPException

    from app.modules.contracts.schemas import AutoGenerateClaimRequest

    svc = _make_service()
    contract_id = uuid.uuid4()
    claim_id = uuid.uuid4()

    svc.contract_repo.rows[contract_id] = SimpleNamespace(
        id=contract_id,
        contract_type="lump_sum",
        retention_percent=Decimal("5"),
        status="active",
    )
    svc.claim_repo.rows[claim_id] = SimpleNamespace(
        id=claim_id,
        contract_id=contract_id,
        status="paid",
        gross_amount=Decimal("50000"),
        retention_amount=Decimal("2500"),
        net_due=Decimal("47500"),
        metadata_={},
    )

    payload = AutoGenerateClaimRequest(completion={})

    with pytest.raises(HTTPException) as exc:
        await svc.auto_generate_claim_lines(claim_id, payload)
    assert exc.value.status_code == 409, (
        "expected 409 conflict on auto-generate against a non-draft claim, "
        f"got {exc.value.status_code}: {exc.value.detail!r}"
    )
    # Defensive: totals must remain untouched.
    row = svc.claim_repo.rows[claim_id]
    assert row.gross_amount == Decimal("50000")
    assert row.net_due == Decimal("47500")


@pytest.mark.asyncio
async def test_auto_generate_claim_lines_allows_draft_claim() -> None:
    """Regression guard: draft claims must still be auto-generatable."""
    from app.modules.contracts.schemas import AutoGenerateClaimRequest

    svc = _make_service()
    contract_id = uuid.uuid4()
    claim_id = uuid.uuid4()

    svc.contract_repo.rows[contract_id] = SimpleNamespace(
        id=contract_id,
        contract_type="lump_sum",
        retention_percent=Decimal("5"),
        status="active",
    )
    svc.claim_repo.rows[claim_id] = SimpleNamespace(
        id=claim_id,
        contract_id=contract_id,
        status="draft",
        gross_amount=Decimal("0"),
        retention_amount=Decimal("0"),
        net_due=Decimal("0"),
        metadata_={},
    )

    payload = AutoGenerateClaimRequest(completion={})
    # Should NOT raise.
    claim = await svc.auto_generate_claim_lines(claim_id, payload)
    assert claim.status == "draft"


# ── 2. attach_lien_waiver must reject draft / rejected claims ────────────


@pytest.mark.asyncio
async def test_attach_lien_waiver_rejects_draft_claim() -> None:
    """A lien waiver is a legal release of lien rights.

    Attaching one to a ``draft`` claim has no legal meaning — the claim
    hasn't been submitted to the owner — and lets a contractor build a
    bogus waiver chain. Reject up-front with 409.
    """
    from fastapi import HTTPException

    svc = _make_service()
    claim_id = uuid.uuid4()
    svc.claim_repo.rows[claim_id] = SimpleNamespace(
        id=claim_id,
        contract_id=uuid.uuid4(),
        status="draft",
        metadata_={},
    )
    payload = {
        "waiver_type": "conditional_partial",
        "through_date": "2026-05-31",
        "amount": "10000",
        "signed_by": "GC Treasurer",
    }
    with pytest.raises(HTTPException) as exc:
        await svc.attach_lien_waiver(claim_id, payload, actor_id="u-1")
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_attach_lien_waiver_rejects_rejected_claim() -> None:
    """A rejected claim does not establish a lien — waivers are bogus."""
    from fastapi import HTTPException

    svc = _make_service()
    claim_id = uuid.uuid4()
    svc.claim_repo.rows[claim_id] = SimpleNamespace(
        id=claim_id,
        contract_id=uuid.uuid4(),
        status="rejected",
        metadata_={},
    )
    payload = {
        "waiver_type": "unconditional_final",
        "through_date": "2026-05-31",
        "amount": "10000",
        "signed_by": "GC Treasurer",
    }
    with pytest.raises(HTTPException) as exc:
        await svc.attach_lien_waiver(claim_id, payload, actor_id="u-1")
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_attach_lien_waiver_allows_submitted_claim() -> None:
    """Regression guard: submitted claims must still accept waivers."""
    svc = _make_service()
    claim_id = uuid.uuid4()
    svc.claim_repo.rows[claim_id] = SimpleNamespace(
        id=claim_id,
        contract_id=uuid.uuid4(),
        status="submitted",
        metadata_={},
    )
    payload = {
        "waiver_type": "conditional_partial",
        "through_date": "2026-05-31",
        "amount": "10000",
        "signed_by": "GC Treasurer",
    }
    record = await svc.attach_lien_waiver(claim_id, payload, actor_id="u-1")
    assert record["waiver_type"] == "conditional_partial"
    assert svc.claim_repo.rows[claim_id].metadata_["lien_waivers"]


# ── 4b. create_contract must always start in 'draft' ─────────────────────


@pytest.mark.asyncio
async def test_create_contract_forces_draft_status() -> None:
    """The lifecycle FSM (draft → active → suspended/completed/terminated)
    is enforced by transition endpoints that stamp signed_at and emit
    the contracts.contract.signed event. A POST /contracts/ that lets
    the caller pre-set status='active' would skip both, producing a
    contract that's commercially live but has no audit trail of being
    signed and no notification reaching downstream finance / dashboards.

    The fix forces status='draft' on create regardless of payload.
    """
    from app.modules.contracts.schemas import ContractCreate
    from app.modules.contracts.service import ContractsService

    class _RecordingRepo(_StubContractRepo):
        async def create(self, contract: Any) -> Any:
            if getattr(contract, "id", None) is None:
                contract.id = uuid.uuid4()
            self.rows[contract.id] = contract
            return contract

    svc = ContractsService.__new__(ContractsService)
    svc.session = _StubSession()
    svc.contract_repo = _RecordingRepo()

    data = ContractCreate(
        code="CT-FORCE",
        title="Force-draft",
        contract_type="lump_sum",
        project_id=uuid.uuid4(),
        # Caller tries to sneak in an active status to bypass the FSM.
        status="active",
    )
    contract = await svc.create_contract(data, user_id="u-1")
    assert contract.status == "draft", (
        "POST /contracts/ must always create in 'draft' state; "
        f"got {contract.status!r}. The sign / suspend / terminate "
        "transition endpoints are the only path that may change status."
    )
