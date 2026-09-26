"""Unit tests for the ``changeorder.approved`` → contract-value subscriber.

Covers ``_on_changeorder_approved_contract`` in
``app.modules.notifications._wave5_cross_module_subscribers``:

* happy path - the linked contract's total_value is bumped by the CO's
  cost_impact (via an atomic SQL increment) and the CO id / running total
  land in contract.metadata;
* idempotency - re-delivering the same event does not double-apply;
* amendability guard - terminated / completed contracts are skipped;
* currency guard - a CO whose currency differs from the contract currency
  never bumps total_value but is still recorded in metadata;
* no contract link - the handler returns without opening a session.

The session factory is faked so no database is required (the handler is
best-effort and isolated by design): SELECT statements return the staged
contract, UPDATE statements apply the bound total_value delta in memory.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.sql import Select, Update

import app.modules.notifications._wave5_cross_module_subscribers as w5
from app.modules.contracts import sov_posting
from app.core.events import Event


class _FakeContract:
    def __init__(
        self,
        *,
        total_value: Decimal = Decimal("100000"),
        status: str = "active",
        metadata: dict | None = None,
        project_id: uuid.UUID | None = None,
        currency: str = "EUR",
    ) -> None:
        self.id = uuid.uuid4()
        self.code = "CT-001"
        self.total_value = total_value
        self.status = status
        self.metadata_ = metadata or {}
        self.project_id = project_id or _PROJECT_ID
        self.currency = currency


class _FakeResult:
    def __init__(self, contract: _FakeContract | None) -> None:
        self._contract = contract

    def scalar_one_or_none(self) -> _FakeContract | None:
        return self._contract


class _FakeSession:
    def __init__(self, state: dict) -> None:
        self.committed = False
        self._state = state

    async def execute(self, stmt):
        if isinstance(stmt, Select):
            return _FakeResult(self._state["contract"])
        if isinstance(stmt, Update):
            # The handler issues UPDATE ... SET total_value = total_value
            # + :delta; pull the bound delta out of the compiled params and
            # apply it to the staged contract.
            params = stmt.compile().params
            delta = next(v for k, v in params.items() if k.startswith("total_value"))
            contract = self._state["contract"]
            contract.total_value = Decimal(str(contract.total_value)) + Decimal(str(delta))
            return None
        raise AssertionError(f"unexpected statement: {stmt!r}")

    async def commit(self) -> None:
        self.committed = True

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch):
    """Patch the isolated session factory used by the handler."""
    state: dict = {"contract": None, "sessions": []}

    def _factory() -> _FakeSession:
        session = _FakeSession(state)
        state["sessions"].append(session)
        return session

    monkeypatch.setattr(w5, "async_session_factory", _factory)

    # The schedule-of-values posting reads and writes tables of its own and is
    # covered where it lives. Here it is only recorded, so the tests can tell
    # which bumps also asked for a line.
    posted: list[dict] = []
    state["posted"] = posted

    async def _record_posting(session, contract, **kwargs):
        posted.append({"contract_id": contract.id, **kwargs})

    monkeypatch.setattr(sov_posting, "post_source_to_sov", _record_posting)
    return state


#: Shared project id - the fake contract and the event agree by default,
#: mirroring a CO and its contract living in the same project.
_PROJECT_ID = uuid.uuid4()


def _event(
    contract_id: str | None,
    co_id: str,
    cost_impact: str = "2500.00",
    project_id: uuid.UUID | None = None,
    variation_order_id: str | None = None,
) -> Event:
    data = {
        "change_order_id": co_id,
        "project_id": str(project_id or _PROJECT_ID),
        "code": "CO-001",
        "cost_impact": cost_impact,
        "currency": "EUR",
        "contract_id": contract_id,
        # Set only on a CO that mirrors a variation order; None otherwise,
        # which is what the publisher sends for a CO a user raised.
        "variation_order_id": variation_order_id,
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
    (posting,) = harness["posted"]
    assert posting["contract_id"] == contract.id
    assert posting["key"] == f"change_order:{co_id}"
    assert posting["amount"] == Decimal("2500.00")


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


@pytest.mark.asyncio
async def test_currency_mismatch_skips_bump_but_records_co(harness: dict) -> None:
    """A CO in a foreign currency must never blend into total_value.

    The bump is skipped, but the CO is recorded in change_order_ids plus a
    skipped_currency_mismatch entry so the money is not silently lost.
    """
    contract = _FakeContract(total_value=Decimal("100000"), currency="USD")
    harness["contract"] = contract
    co_id = str(uuid.uuid4())

    await w5._on_changeorder_approved_contract(_event(str(uuid.uuid4()), co_id))

    assert contract.total_value == Decimal("100000")
    assert contract.metadata_["change_order_ids"] == [co_id]
    assert "change_order_total" not in contract.metadata_
    skipped = contract.metadata_["skipped_currency_mismatch"]
    assert skipped == [{"change_order_id": co_id, "cost_impact": "2500.00", "currency": "EUR"}]
    # The metadata record IS committed (otherwise redelivery would retry).
    assert harness["sessions"][-1].committed is True


@pytest.mark.asyncio
async def test_currency_mismatch_is_idempotent(harness: dict) -> None:
    contract = _FakeContract(total_value=Decimal("100000"), currency="USD")
    harness["contract"] = contract
    co_id = str(uuid.uuid4())
    event = _event(str(uuid.uuid4()), co_id)

    await w5._on_changeorder_approved_contract(event)
    await w5._on_changeorder_approved_contract(event)

    assert contract.total_value == Decimal("100000")
    assert contract.metadata_["change_order_ids"] == [co_id]
    assert len(contract.metadata_["skipped_currency_mismatch"]) == 1


@pytest.mark.asyncio
async def test_event_without_currency_still_bumps(harness: dict) -> None:
    """COs that do not carry a currency keep the legacy behaviour."""
    contract = _FakeContract(total_value=Decimal("100000"), currency="USD")
    harness["contract"] = contract
    co_id = str(uuid.uuid4())
    event = _event(str(uuid.uuid4()), co_id)
    event.data["currency"] = ""

    await w5._on_changeorder_approved_contract(event)

    assert contract.total_value == Decimal("102500.00")
    assert Decimal(contract.metadata_["change_order_total"]) == Decimal("2500.00")


@pytest.mark.asyncio
async def test_mirrored_co_does_not_repost_its_variation_orders_value(harness: dict) -> None:
    """A mirror of a VO that already posted must not post the amount again.

    Promoting a variation request mirrors the VO into a draft CO carrying
    ``metadata.variation_order_id``. Link that mirror to the contract the
    VO already names and both subscribers target one contract with one
    commercial change - which used to add the money twice.
    """
    vo_id = str(uuid.uuid4())
    contract = _FakeContract(
        total_value=Decimal("102500.00"),
        metadata={"variation_ids": [vo_id], "variation_total": "2500.00"},
    )
    harness["contract"] = contract
    co_id = str(uuid.uuid4())

    await w5._on_changeorder_approved_contract(
        _event(str(uuid.uuid4()), co_id, variation_order_id=vo_id),
    )

    assert contract.total_value == Decimal("102500.00")
    assert Decimal(contract.metadata_["variation_total"]) == Decimal("2500.00")
    assert "change_order_total" not in contract.metadata_
    # Kept out of change_order_ids: the dashboard rollup counts that list.
    assert "change_order_ids" not in contract.metadata_
    assert contract.metadata_["skipped_variation_mirror"] == [
        {
            "change_order_id": co_id,
            "variation_order_id": vo_id,
            "cost_impact": "2500.00",
            # Which half stood down; the other half carried the money.
            "skipped": "change_order",
        }
    ]
    # The skip record IS committed (otherwise it would not survive).
    assert harness["sessions"][-1].committed is True


@pytest.mark.asyncio
async def test_mirror_skip_is_idempotent(harness: dict) -> None:
    vo_id = str(uuid.uuid4())
    contract = _FakeContract(
        total_value=Decimal("102500.00"),
        metadata={"variation_ids": [vo_id], "variation_total": "2500.00"},
    )
    harness["contract"] = contract
    event = _event(str(uuid.uuid4()), str(uuid.uuid4()), variation_order_id=vo_id)

    await w5._on_changeorder_approved_contract(event)
    await w5._on_changeorder_approved_contract(event)

    assert contract.total_value == Decimal("102500.00")
    assert len(contract.metadata_["skipped_variation_mirror"]) == 1
    # Second delivery had nothing to write.
    assert harness["sessions"][-1].committed is False


@pytest.mark.asyncio
async def test_mirror_posts_when_its_variation_order_has_not(harness: dict) -> None:
    """The guard keys on money already applied, not on being a mirror.

    A mirror whose VO has posted nothing to this contract - the VO names
    no contract, or has not completed yet - is the only route the amount
    has, so it still posts. A VO that completes afterwards applies its own
    amount through its own subscriber.
    """
    contract = _FakeContract(total_value=Decimal("100000"))
    harness["contract"] = contract
    co_id = str(uuid.uuid4())

    await w5._on_changeorder_approved_contract(
        _event(str(uuid.uuid4()), co_id, variation_order_id=str(uuid.uuid4())),
    )

    assert contract.total_value == Decimal("102500.00")
    assert contract.metadata_["change_order_ids"] == [co_id]
    assert Decimal(contract.metadata_["change_order_total"]) == Decimal("2500.00")
    assert "skipped_variation_mirror" not in contract.metadata_


def test_subscriber_registered() -> None:
    assert ("changeorder.approved", w5._on_changeorder_approved_contract) in w5._SUBSCRIPTIONS
