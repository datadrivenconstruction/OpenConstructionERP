"""Unit tests for the rfq_bidding module.

Scope (this is the FIRST test for this module — previously zero coverage):
    * Happy-path workflow: create RFQ → issue → vendor submits bid →
      buyer (manager) awards bid → verify RFQ.status == "awarded",
      bid.is_awarded == True, ActivityLog row written with actor_id.
    * Money validation: bid_amount rejects non-decimal junk + negatives.
    * State-machine guards:
        - Cannot submit bid against a draft RFQ.
        - Cannot submit bid against an already-awarded RFQ.
        - Cannot award twice (double-award race protection).
    * Role gate: an "editor" actor cannot award (FSM contract requires
      admin / manager / owner).

Runs against PostgreSQL via ``transactional_session`` (each test executes
inside an outer transaction rolled back on teardown) with the real ORM
models, so the audit log row is genuinely persisted and observable within
the test - the load-bearing guarantee for the financial-traceability claim
in the architecture guide.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_log import get_activity_for_entity
from app.modules.rfq_bidding.schemas import BidCreate, RFQCreate
from app.modules.rfq_bidding.service import RFQService
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Per-test PostgreSQL session inside a transaction rolled back on teardown.

    The shared ``oe_test_unit`` database already carries the full schema, so no
    ``create_all`` is needed; the outer transaction provides isolation between
    tests.
    """
    async with transactional_session() as s:
        yield s


def _make_rfq_create(project_id: uuid.UUID) -> RFQCreate:
    return RFQCreate(
        project_id=project_id,
        title="Concrete works package",
        description="C30/37 to foundations",
        scope_of_work="See attached drawings",
        currency_code="EUR",
        status="draft",
        issued_to_contacts=[],
        metadata={},
    )


# ── Happy path: full lifecycle ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_workflow_create_submit_award_audit(session: AsyncSession) -> None:
    """End-to-end: create RFQ → issue → submit bid → award → audit row."""
    service = RFQService(session)
    project_id = uuid.uuid4()
    actor_id = str(uuid.uuid4())

    # 1. Create RFQ (draft)
    rfq = await service.create_rfq(_make_rfq_create(project_id), user_id=actor_id)
    # Snapshot identity fields — the repos' expire_all() will invalidate
    # later attribute reads on this ORM instance, and a re-fetch under
    # the same session is best practice.
    rfq_id = rfq.id
    assert rfq.status == "draft"
    assert rfq.rfq_number.startswith("RFQ-")
    assert rfq.currency_code == "EUR"

    # 2. Issue (draft → published)
    issued = await service.issue_rfq(rfq_id, actor_id=actor_id, reason="Ready to publish")
    assert issued.status == "published"

    # 3. Vendor submits bid
    bid_payload = BidCreate(
        rfq_id=rfq_id,
        bidder_contact_id=str(uuid.uuid4()),
        bid_amount="125000.50",
        currency_code="EUR",
        validity_days=45,
    )
    bid = await service.submit_bid(bid_payload, user_id=actor_id)
    bid_id = bid.id
    assert bid.bid_amount == "125000.50"
    assert bid.currency_code == "EUR"
    assert bid.is_awarded is False

    # 4. Buyer (manager role) awards the bid
    awarded = await service.award_bid(
        bid_id,
        actor_id=actor_id,
        actor_role="manager",
        reason="Best price",
        gate_override_reason="Single-source test fixture",
    )
    assert awarded.is_awarded is True

    # 5. RFQ status flipped to awarded
    final_rfq = await service.get_rfq(rfq_id)
    assert final_rfq.status == "awarded"

    # 6. Audit log row written with actor_id (was None before the fix)
    log_rows = await get_activity_for_entity(session, entity_type="rfq", entity_id=str(rfq_id))
    award_rows = [r for r in log_rows if r.to_status == "awarded"]
    assert len(award_rows) == 1
    audit = award_rows[0]
    assert str(audit.actor_id) == actor_id  # ← regression-guard for the fix
    assert audit.from_status == "published"
    assert audit.metadata_["bid_id"] == str(bid_id)
    assert audit.metadata_["bid_amount"] == "125000.50"
    assert audit.metadata_["currency_code"] == "EUR"


# ── Money validation ───────────────────────────────────────────────────────


def test_bid_amount_rejects_non_decimal() -> None:
    """bid_amount = 'abc' must fail at the schema layer."""
    with pytest.raises(ValueError, match="bid_amount"):
        BidCreate(
            rfq_id=uuid.uuid4(),
            bidder_contact_id="x",
            bid_amount="not-a-number",
        )


def test_bid_amount_rejects_negative() -> None:
    with pytest.raises(ValueError, match="must be >= 0"):
        BidCreate(
            rfq_id=uuid.uuid4(),
            bidder_contact_id="x",
            bid_amount="-100",
        )


def test_bid_amount_rejects_inf() -> None:
    with pytest.raises(ValueError, match="finite"):
        BidCreate(
            rfq_id=uuid.uuid4(),
            bidder_contact_id="x",
            bid_amount="Infinity",
        )


def test_currency_code_rejects_bogus() -> None:
    with pytest.raises(ValueError, match="currency_code"):
        BidCreate(
            rfq_id=uuid.uuid4(),
            bidder_contact_id="x",
            bid_amount="100",
            currency_code="BOGUS",
        )


def test_currency_code_normalises_case() -> None:
    """Lowercase 'eur' → 'EUR' for downstream FX rollup determinism."""
    bid = BidCreate(
        rfq_id=uuid.uuid4(),
        bidder_contact_id="x",
        bid_amount="100",
        currency_code="usd",
    )
    assert bid.currency_code == "USD"


# ── State-machine guards ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cannot_submit_bid_against_draft_rfq(session: AsyncSession) -> None:
    service = RFQService(session)
    rfq = await service.create_rfq(_make_rfq_create(uuid.uuid4()))
    rfq_id = rfq.id
    assert rfq.status == "draft"

    bid_payload = BidCreate(
        rfq_id=rfq_id,
        bidder_contact_id=str(uuid.uuid4()),
        bid_amount="1000",
    )
    with pytest.raises(Exception) as exc:
        await service.submit_bid(bid_payload)
    # HTTPException 409
    assert getattr(exc.value, "status_code", None) == 409


@pytest.mark.asyncio
async def test_cannot_submit_bid_against_awarded_rfq(session: AsyncSession) -> None:
    service = RFQService(session)
    rfq = await service.create_rfq(_make_rfq_create(uuid.uuid4()))
    rfq_id = rfq.id
    await service.issue_rfq(rfq_id, actor_id=str(uuid.uuid4()))
    first_bid = await service.submit_bid(
        BidCreate(
            rfq_id=rfq_id,
            bidder_contact_id=str(uuid.uuid4()),
            bid_amount="1000",
        ),
    )
    first_bid_id = first_bid.id
    await service.award_bid(
        first_bid_id, actor_role="admin", reason="Best price", gate_override_reason="Single-source test fixture"
    )

    # Now the RFQ is awarded — a second vendor cannot slip a bid in.
    with pytest.raises(Exception) as exc:
        await service.submit_bid(
            BidCreate(
                rfq_id=rfq_id,
                bidder_contact_id=str(uuid.uuid4()),
                bid_amount="900",
            ),
        )
    assert getattr(exc.value, "status_code", None) == 409


@pytest.mark.asyncio
async def test_cannot_double_award(session: AsyncSession) -> None:
    service = RFQService(session)
    rfq = await service.create_rfq(_make_rfq_create(uuid.uuid4()))
    rfq_id = rfq.id
    await service.issue_rfq(rfq_id, actor_id=str(uuid.uuid4()))
    b1 = await service.submit_bid(
        BidCreate(rfq_id=rfq_id, bidder_contact_id="v1", bid_amount="1000"),
    )
    b1_id = b1.id
    b2 = await service.submit_bid(
        BidCreate(rfq_id=rfq_id, bidder_contact_id="v2", bid_amount="950"),
    )
    b2_id = b2.id
    await service.award_bid(
        b1_id, actor_role="manager", reason="Best price", gate_override_reason="Single-source test fixture"
    )
    with pytest.raises(Exception) as exc:
        await service.award_bid(
            b2_id, actor_role="manager", reason="Best price", gate_override_reason="Single-source test fixture"
        )
    assert getattr(exc.value, "status_code", None) == 409


# ── Role gate ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_editor_cannot_award(session: AsyncSession) -> None:
    """A user with role='editor' must NOT be able to award (FSM contract)."""
    service = RFQService(session)
    rfq = await service.create_rfq(_make_rfq_create(uuid.uuid4()))
    rfq_id = rfq.id
    await service.issue_rfq(rfq_id, actor_id=str(uuid.uuid4()))
    bid = await service.submit_bid(
        BidCreate(rfq_id=rfq_id, bidder_contact_id="v", bid_amount="100"),
    )
    bid_id = bid.id
    with pytest.raises(Exception) as exc:
        await service.award_bid(bid_id, actor_id=str(uuid.uuid4()), actor_role="editor")
    assert getattr(exc.value, "status_code", None) == 403


@pytest.mark.asyncio
async def test_admin_role_can_award(session: AsyncSession) -> None:
    service = RFQService(session)
    rfq = await service.create_rfq(_make_rfq_create(uuid.uuid4()))
    rfq_id = rfq.id
    await service.issue_rfq(rfq_id, actor_id=str(uuid.uuid4()))
    bid = await service.submit_bid(
        BidCreate(rfq_id=rfq_id, bidder_contact_id="v", bid_amount="100"),
    )
    bid_id = bid.id
    awarded = await service.award_bid(
        bid_id, actor_role="admin", reason="Best price", gate_override_reason="Single-source test fixture"
    )
    assert awarded.is_awarded is True
