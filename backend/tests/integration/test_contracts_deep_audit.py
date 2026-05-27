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
3. ``release_retention`` must refuse duplicate release events. The
   metadata audit log was being treated as advisory — the same event
   key could be released N times, each time releasing the configured
   percentage of whatever retention remained, producing arbitrary
   double-spend.
4. ``release_retention`` must reject negative / non-numeric / >100
   custom-schedule percentages up front (it used to silently clamp them
   to 0 or 100, which masked configuration mistakes).
5. ``plan_retention_release`` 100% edge case: after the original held
   amount has been fully released, subsequent calls must return zero
   (not re-release on a stale base). Combined with #3 above this gives
   true idempotency on the audit log.

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


# ── 3. release_retention must refuse duplicate events ────────────────────


@pytest.mark.asyncio
async def test_release_retention_rejects_duplicate_event() -> None:
    """Releasing the same event twice double-spends retention.

    Pre-fix the audit log was append-only but never consulted to dedupe.
    Each call would compute ``net_held = held - already_released`` and
    happily release the configured percentage *again* — releasing 50 %
    of remaining each time, asymptotically approaching 100 % regardless
    of the schedule's stated intent.
    """
    from fastapi import HTTPException

    svc = _make_service()
    contract_id = uuid.uuid4()
    svc.contract_repo.rows[contract_id] = SimpleNamespace(
        id=contract_id,
        status="active",
        metadata_={
            "retention_releases": [
                {
                    "event": "substantial_completion",
                    "released_at": "2026-05-22T10:00:00+00:00",
                    "released_by": "qs",
                    "percent_released": "50",
                    "amount_released": "5000",
                    "remaining": "5000",
                },
            ],
        },
    )
    with pytest.raises(HTTPException) as exc:
        await svc.release_retention(
            contract_id,
            "substantial_completion",
            actor_id="qs",
        )
    assert exc.value.status_code == 409
    # Structured error payload — caller code keys off ``error`` not the prose.
    assert exc.value.detail["error"] == "retention_event_already_released"
    assert exc.value.detail["event"] == "substantial_completion"


@pytest.mark.asyncio
async def test_release_retention_allows_distinct_event() -> None:
    """Regression guard: a NEW event must still be releasable."""
    svc = _make_service()
    contract_id = uuid.uuid4()
    svc.contract_repo.rows[contract_id] = SimpleNamespace(
        id=contract_id,
        status="active",
        metadata_={
            "retention_releases": [
                {
                    "event": "substantial_completion",
                    "released_at": "2026-05-22T10:00:00+00:00",
                    "released_by": "qs",
                    "percent_released": "50",
                    "amount_released": "5000",
                    "remaining": "5000",
                },
            ],
        },
    )
    result = await svc.release_retention(
        contract_id,
        "punch_list_complete",
        actor_id="qs",
    )
    assert result["event"] == "punch_list_complete"
    # default schedule: punch_list_complete = 50 % of (held - already_released)
    # held=10000, already=5000, net_held=5000, release=2500
    assert Decimal(result["amount_released"]) == Decimal("2500.0000")


# ── 4. release_retention must validate custom_schedule values ────────────


@pytest.mark.asyncio
async def test_release_retention_rejects_negative_custom_schedule_value() -> None:
    """Negative percentages are a configuration mistake, not a release."""
    from fastapi import HTTPException

    svc = _make_service()
    contract_id = uuid.uuid4()
    svc.contract_repo.rows[contract_id] = SimpleNamespace(
        id=contract_id,
        status="active",
        metadata_={},
    )
    with pytest.raises(HTTPException) as exc:
        await svc.release_retention(
            contract_id,
            "milestone_3",
            custom_schedule={"milestone_3": Decimal("-5")},
            actor_id="qs",
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_release_retention_rejects_over_100_custom_schedule_value() -> None:
    """A percentage > 100 is a configuration mistake, not a release."""
    from fastapi import HTTPException

    svc = _make_service()
    contract_id = uuid.uuid4()
    svc.contract_repo.rows[contract_id] = SimpleNamespace(
        id=contract_id,
        status="active",
        metadata_={},
    )
    with pytest.raises(HTTPException) as exc:
        await svc.release_retention(
            contract_id,
            "milestone_3",
            custom_schedule={"milestone_3": Decimal("150")},
            actor_id="qs",
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_release_retention_rejects_non_numeric_custom_schedule_value() -> None:
    """Non-numeric schedule values must fail loudly, not silently clamp."""
    from fastapi import HTTPException

    svc = _make_service()
    contract_id = uuid.uuid4()
    svc.contract_repo.rows[contract_id] = SimpleNamespace(
        id=contract_id,
        status="active",
        metadata_={},
    )
    with pytest.raises(HTTPException) as exc:
        await svc.release_retention(
            contract_id,
            "milestone_3",
            custom_schedule={"milestone_3": "tomorrow"},
            actor_id="qs",
        )
    assert exc.value.status_code == 400


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


# ── 5. 100% retention edge — fully-released contract is idempotent ───────


@pytest.mark.asyncio
async def test_release_retention_after_full_release_is_zero() -> None:
    """Once original held is fully released, further events return zero.

    This relies on duplicate-event rejection (#3) to keep the audit log
    clean. With a fresh event whose schedule asks for 100 % of remaining
    when remaining is already zero, the function must return
    ``amount_released == 0`` rather than re-base on stale held.
    """
    svc = _make_service()
    contract_id = uuid.uuid4()
    svc.contract_repo.rows[contract_id] = SimpleNamespace(
        id=contract_id,
        status="active",
        metadata_={
            "retention_releases": [
                {
                    "event": "substantial_completion",
                    "released_at": "2026-05-22T10:00:00+00:00",
                    "released_by": "qs",
                    "percent_released": "100",
                    "amount_released": "10000",
                    "remaining": "0",
                },
            ],
        },
    )
    result = await svc.release_retention(
        contract_id,
        "defects_liability_end",
        actor_id="qs",
    )
    # Everything's already gone — nothing left to release.
    assert Decimal(result["amount_released"]) == Decimal("0")
    assert Decimal(result["remaining"]) == Decimal("0")
