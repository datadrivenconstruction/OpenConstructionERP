"""Unit tests for the ``changeorder.approved`` → contract-value subscriber.

Covers ``_on_changeorder_approved_contract`` in
``app.modules.notifications._wave5_cross_module_subscribers``:

* happy path - the linked contract's total_value is bumped by the CO's
  cost_impact and the CO id / running total land in contract.metadata;
* idempotency - re-delivering the same event does not double-apply;
* amendability guard - terminated / completed contracts are skipped;
* no contract link - the handler returns without opening a session.

The session factory and ContractRepository are faked so no database is
required (the handler is best-effort and isolated by design).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

import app.modules.notifications._wave5_cross_module_subscribers as w5
from app.core.events import Event


class _FakeContract:
    def __init__(
        self,
        *,
        total_value: Decimal = Decimal("100000"),
        status: str = "active",
        metadata: dict | None = None,
        project_id: uuid.UUID | None = None,
    ) -> None:
        self.code = "CT-001"
        self.total_value = total_value
        self.status = status
        self.metadata_ = metadata or {}
        self.project_id = project_id or _PROJECT_ID


class _FakeSession:
    def __init__(self) -> None:
        self.committed = False

    async def commit(self) -> None:
        self.committed = True

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch):
    """Patch the isolated session + ContractRepository used by the handler."""
    import app.modules.contracts.repository as contracts_repo_mod

    state: dict = {"contract": None, "sessions": []}

    def _factory() -> _FakeSession:
        session = _FakeSession()
        state["sessions"].append(session)
        return session

    class _FakeRepo:
        def __init__(self, session: object) -> None:
            pass

        async def get_by_id(self, contract_id: uuid.UUID):
            return state["contract"]

    monkeypatch.setattr(w5, "async_session_factory", _factory)
    monkeypatch.setattr(contracts_repo_mod, "ContractRepository", _FakeRepo)
    return state


#: Shared project id - the fake contract and the event agree by default,
#: mirroring a CO and its contract living in the same project.
_PROJECT_ID = uuid.uuid4()


def _event(
    contract_id: str | None,
    co_id: str,
    cost_impact: str = "2500.00",
    project_id: uuid.UUID | None = None,
) -> Event:
    data = {
        "change_order_id": co_id,
        "project_id": str(project_id or _PROJECT_ID),
        "code": "CO-001",
        "cost_impact": cost_impact,
        "currency": "EUR",
        "contract_id": contract_id,
    }
    return Event(name="changeorder.approved", data=data)


@pytest.mark.asyncio
async def test_bumps_contract_value_and_tracks_metadata(harness: dict) -> None:
    contract = _FakeContract(total_value=Decimal("100000"))
    harness["contract"] = contract
    co_id = str(uuid.uuid4())

    await w5._on_changeorder_approved_contract(_event(str(uuid.uuid4()), co_id))

    assert contract.total_value == Decimal("102500.00")
    assert contract.metadata_["change_order_ids"] == [co_id]
    assert Decimal(contract.metadata_["change_order_total"]) == Decimal("2500.00")
    assert harness["sessions"][-1].committed is True


@pytest.mark.asyncio
async def test_idempotent_on_redelivery(harness: dict) -> None:
    contract = _FakeContract(total_value=Decimal("100000"))
    harness["contract"] = contract
    co_id = str(uuid.uuid4())
    event = _event(str(uuid.uuid4()), co_id)

    await w5._on_changeorder_approved_contract(event)
    await w5._on_changeorder_approved_contract(event)

    # Applied exactly once.
    assert contract.total_value == Decimal("102500.00")
    assert contract.metadata_["change_order_ids"] == [co_id]
    assert Decimal(contract.metadata_["change_order_total"]) == Decimal("2500.00")
    # Second delivery skipped before commit.
    assert harness["sessions"][-1].committed is False


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["terminated", "completed"])
async def test_skips_closed_contract(harness: dict, status: str) -> None:
    contract = _FakeContract(total_value=Decimal("100000"), status=status)
    harness["contract"] = contract

    await w5._on_changeorder_approved_contract(_event(str(uuid.uuid4()), str(uuid.uuid4())))

    assert contract.total_value == Decimal("100000")
    assert "change_order_ids" not in contract.metadata_
    assert harness["sessions"][-1].committed is False


@pytest.mark.asyncio
async def test_skips_silently_without_contract_link(harness: dict) -> None:
    await w5._on_changeorder_approved_contract(_event(None, str(uuid.uuid4())))
    # Never opened a session - most COs carry no contract link.
    assert harness["sessions"] == []


@pytest.mark.asyncio
async def test_skips_on_invalid_contract_id(harness: dict) -> None:
    await w5._on_changeorder_approved_contract(_event("not-a-uuid", str(uuid.uuid4())))
    assert harness["sessions"] == []


@pytest.mark.asyncio
async def test_negative_delta_reduces_contract_value(harness: dict) -> None:
    contract = _FakeContract(total_value=Decimal("100000"))
    harness["contract"] = contract

    await w5._on_changeorder_approved_contract(
        _event(str(uuid.uuid4()), str(uuid.uuid4()), cost_impact="-1500.50"),
    )

    assert contract.total_value == Decimal("98499.50")
    assert Decimal(contract.metadata_["change_order_total"]) == Decimal("-1500.50")


@pytest.mark.asyncio
async def test_rejects_contract_from_another_project(harness: dict) -> None:
    """A CO may not move money on a contract outside its own project.

    The contract link arrives via client-supplied CO metadata, so a CO in
    project A naming a contract in project B must be ignored.
    """
    contract = _FakeContract(total_value=Decimal("100000"))
    harness["contract"] = contract

    await w5._on_changeorder_approved_contract(
        _event(str(uuid.uuid4()), str(uuid.uuid4()), project_id=uuid.uuid4()),
    )

    assert contract.total_value == Decimal("100000")
    assert contract.metadata_ == {}
    assert all(not s.committed for s in harness["sessions"])


@pytest.mark.asyncio
async def test_rejects_event_without_project_id(harness: dict) -> None:
    contract = _FakeContract(total_value=Decimal("100000"))
    harness["contract"] = contract
    event = _event(str(uuid.uuid4()), str(uuid.uuid4()))
    event.data.pop("project_id")

    await w5._on_changeorder_approved_contract(event)

    assert contract.total_value == Decimal("100000")
    assert all(not s.committed for s in harness["sessions"])


def test_subscriber_registered() -> None:
    assert ("changeorder.approved", w5._on_changeorder_approved_contract) in w5._SUBSCRIPTIONS
