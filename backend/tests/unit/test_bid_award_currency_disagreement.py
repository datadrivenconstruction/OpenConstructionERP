# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""One award, and every record describing it agrees what money it is.

Written as a failing control before the fix and kept as the regression for
it. The chains, as they were:

    bid_management/service.py   BidAward.currency  = data.currency or package.currency
    notifications/_wave5        Contract.currency  = data["currency"] or package.currency
    procurement/events.py       PO.currency_code   = data["currency"]
                                                     or winning_submission.currency
                                                     or package.currency or ""

Only the procurement chain consulted the winning submission. That difference
is invisible whenever the package declares a currency, because the first term
wins everywhere, which is why every existing test passes ``currency="EUR"`` in
the event payload and never reaches the rest of any chain.

It became visible when the package was unlabelled, and nothing prevents that:
``BidPackage.currency`` defaults to ``""`` and the validation that looks like
it would object requires both operands to be truthy::

    service.py:202-205
        package_currency = (getattr(package, "currency", "") or "").upper()
        submission_currency = (getattr(submission, "currency", "") or "").upper()
        if package_currency and submission_currency and package_currency != submission_currency:
            errors.append("currency_mismatch")

so an unlabelled package plus a EUR submission is not a mismatch, stays
``is_valid=True``, and is awardable.

``award_package`` now resolves the currency once and publishes it, so the
subscribers take the payload's first term and never reach their own fallbacks.
The two chains below are therefore still true statements about each
subscriber given a blank payload - a payload the publisher no longer emits -
and they are kept because that is the behaviour anything reaching those
handlers from elsewhere would get. The test that matters is
``test_one_award_is_labelled_two_different_ways``, which drives the real
``award_package`` and follows the payload it actually publishes.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.procurement import events as proc_events
from tests._pg import transactional_session
from tests.unit.test_procurement_events import (
    _bid_award_event as _labelled_award_event,
)

# The procurement handler reads its rows through its own session, so this file
# reuses the fake store that test_procurement_events already drives it with,
# rather than standing up a second, subtly different one. A difference in
# outcome is then attributable to the currency and to nothing else.
from tests.unit.test_procurement_events import (
    _FakeSession,
    _FakeStore,
    _seed_bid_award,
    _StubPOItemRepo,
    _StubPORepo,
)


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """Per-test PostgreSQL session inside a rolled-back outer transaction."""
    async with transactional_session() as s:
        yield s


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch) -> _FakeStore:
    """Wire the procurement handlers to a fresh in-memory store.

    A copy of the fixture in test_procurement_events: fixtures live in the
    module that defines them and importing the helpers does not bring them
    along.
    """
    store = _FakeStore()
    monkeypatch.setattr(proc_events, "async_session_factory", lambda: _FakeSession(store))
    monkeypatch.setattr(proc_events, "PurchaseOrderRepository", _StubPORepo)
    monkeypatch.setattr(proc_events, "POItemRepository", _StubPOItemRepo)
    return store


def _unlabelled_package_award(store: _FakeStore, *, project_id: uuid.UUID):
    """Seed the reachable state: package with no currency, submission in EUR.

    ``_seed_bid_award`` builds both in EUR; this blanks the package only, so
    the package and the submission are the sole difference from the passing
    test next door.
    """
    package, bidder = _seed_bid_award(store, project_id=project_id)
    package.currency = ""
    return package, bidder


def _award_event_carrying(package, bidder, *, currency: str):
    """The payload ``award_package`` publishes, with the currency it computed.

    ``award_package`` writes ``currency=data.currency or package.currency`` onto
    the award row and then publishes that same value, so an unlabelled package
    awarded without an explicit currency publishes ``""``.
    """
    event = _labelled_award_event(package, bidder)
    event.data["currency"] = currency
    return event


@pytest.mark.asyncio
async def test_the_po_reaches_past_the_blank_to_the_submissions_currency(patched: _FakeStore) -> None:
    """The falsifiable half, measured first.

    If the purchase order does not come back EUR here then the reading behind
    this whole file is wrong and there is no disagreement to fix, because the
    contract side can only ever produce the empty string from these inputs.
    This is the assertion that decides it.
    """
    project_id = uuid.uuid4()
    package, bidder = _unlabelled_package_award(patched, project_id=project_id)

    await proc_events._create_po_from_bid_award(_award_event_carrying(package, bidder, currency=""))

    assert len(patched.purchase_orders) == 1
    po = patched.purchase_orders[0]
    assert po.currency_code == "EUR", (
        "expected the PO chain to fall through the empty event currency and the "
        "empty package currency to the winning submission's EUR; got "
        f"{po.currency_code!r}"
    )
    # The amount is the awarded amount either way, so the two records below are
    # describing the same money and only its label is in question.
    assert po.amount_total == "95000.00"


class _NonCommittingSession:
    """The real session, with ``commit`` demoted to ``flush``.

    The subscriber opens its own session and commits, which is correct in
    production and fatal to a test that keeps its rows inside a transaction it
    intends to roll back. Everything else is forwarded untouched, so the
    handler runs its real SQL against the real schema.
    """

    def __init__(self, inner) -> None:
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    async def commit(self) -> None:
        await self._inner.flush()

    async def close(self) -> None:
        return None

    async def __aenter__(self) -> _NonCommittingSession:
        return self

    async def __aexit__(self, *_exc) -> bool:
        return False


@pytest.mark.asyncio
async def test_the_contract_stops_at_the_blank(session, monkeypatch, caplog) -> None:
    """The other half, measured rather than read.

    The contract chain has only two terms and neither of them is the winning
    submission, so an unlabelled package yields an unlabelled contract for the
    same award the purchase order labels EUR.

    The handler wraps its whole body in ``except Exception`` and reports
    failures at ``logger.debug``, so a contract that is missing because the
    harness broke is indistinguishable from one that is missing because the
    code did. Hence the explicit assertion that a contract exists at all, and
    the debug capture, before anything is claimed about its currency.
    """
    from sqlalchemy import select

    from app.modules.bid_management.models import Bidder, BidPackage
    from app.modules.contracts.models import Contract
    from app.modules.notifications import _wave5_cross_module_subscribers as w5
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    # A real Project row, and a real User to own it: BidPackage.project_id
    # carries an FK and so does Project.owner_id, so the fake-store shortcut
    # used above is not available on the real schema.
    owner = User(
        email=f"award-{uuid.uuid4().hex[:8]}@example.test",
        hashed_password="x",
        full_name="Award Owner",
    )
    session.add(owner)
    await session.flush()
    project = Project(name="Control project", owner_id=owner.id)
    session.add(project)
    await session.flush()
    project_id = project.id

    code = f"BP-{uuid.uuid4().hex[:8]}"
    package = BidPackage(project_id=project_id, code=code, title="Concrete works", currency="")
    session.add(package)
    await session.flush()
    bidder = Bidder(package_id=package.id, company_name="ACME Bau GmbH", status="active")
    session.add(bidder)
    await session.flush()

    monkeypatch.setattr(w5, "async_session_factory", lambda: _NonCommittingSession(session))

    event = w5.Event(
        name="bid_management.package.awarded",
        data={
            "package_id": str(package.id),
            "project_id": str(project_id),
            "awarded_bidder_id": str(bidder.id),
            "awarded_amount": "95000.00",
            "currency": "",
        },
        source_module="bid_management",
    )

    with caplog.at_level("DEBUG", logger=w5.logger.name):
        await w5._on_bid_package_awarded(event)

    contract = (await session.execute(select(Contract).where(Contract.code == f"CONTRACT-{code}"))).scalar_one_or_none()
    assert contract is not None, (
        "no contract was created, so nothing can be concluded about its currency. "
        "The handler swallows every failure into logger.debug; captured records: "
        f"{[r.getMessage() for r in caplog.records]}"
    )

    assert contract.currency == "", (
        f"expected the contract chain to stop at the blank package currency; got {contract.currency!r}"
    )
    # Same award, same money. The purchase order test above labels this EUR.
    assert str(contract.total_value) in {"95000.00", "95000.0000"}


@pytest.mark.asyncio
async def test_repaired_package_award_labels_every_downstream_record_consistently(
    session, monkeypatch, patched: _FakeStore
) -> None:
    """Repair a legacy blank package before award; every consumer uses its currency.

    The real award and event run against PostgreSQL. The procurement consumer
    retains its own legacy blank snapshot, so its agreement still depends on
    the actual published currency rather than a manufactured event payload.
    """
    from decimal import Decimal

    from sqlalchemy import select

    from app.modules.bid_management import service as bid_service
    from app.modules.bid_management.models import Bidder, BidInvitation, BidPackage, BidSubmission
    from app.modules.bid_management.schemas import BidAwardCreate, BidPackageUpdate
    from app.modules.contracts.models import Contract
    from app.modules.notifications import _wave5_cross_module_subscribers as w5
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    # ── the award, made through the real service against real PostgreSQL ──
    owner = User(
        email=f"award-{uuid.uuid4().hex[:8]}@example.test",
        hashed_password="x",
        full_name="Award Owner",
    )
    session.add(owner)
    await session.flush()
    project = Project(name="Control project", owner_id=owner.id)
    session.add(project)
    await session.flush()

    code = f"BP-{uuid.uuid4().hex[:8]}"
    # Legacy installs can still hold blank packages. They must be repaired
    # explicitly before an award; new packages cannot omit their currency.
    package = BidPackage(project_id=project.id, code=code, title="Concrete works", currency="", status="closed")
    session.add(package)
    await session.flush()
    bidder = Bidder(package_id=package.id, company_name="ACME Bau GmbH", status="active")
    session.add(bidder)
    await session.flush()
    invitation = BidInvitation(package_id=package.id, bidder_ref_id=bidder.id, invitee_company_name="ACME Bau GmbH")
    session.add(invitation)
    await session.flush()
    # A historical validity flag does not bypass the currency guard. Repair
    # the package below before attempting to award this submission.
    submission = BidSubmission(
        invitation_id=invitation.id,
        bidder_id=bidder.id,
        total_amount="95000.00",
        currency="EUR",
        is_valid=True,
    )
    session.add(submission)
    await session.flush()

    published: dict[str, str] = {}

    def _capture(_session, _name, payload, **_kw) -> None:
        published.update(payload)

    monkeypatch.setattr(bid_service, "publish_after_commit", _capture)

    service = bid_service.BidManagementService(session)
    await service.update_package(package.id, BidPackageUpdate(currency="EUR"))
    award = await service.award_package(
        package.id,
        BidAwardCreate(
            package_id=package.id,
            awarded_bidder_id=bidder.id,
            awarded_amount=Decimal("95000.00"),
        ),
    )
    assert published, "award_package published nothing, so there is no payload to follow"
    payload_currency = published["currency"]

    # ── the contracts side, given that payload, on the same rows ──
    monkeypatch.setattr(w5, "async_session_factory", lambda: _NonCommittingSession(session))
    await w5._on_bid_package_awarded(
        w5.Event(name="bid_management.package.awarded", data=dict(published), source_module="bid_management"),
    )
    contract = (await session.execute(select(Contract).where(Contract.code == f"CONTRACT-{code}"))).scalar_one_or_none()
    assert contract is not None, "no contract was created; nothing can be concluded"

    # ── the procurement side, given the same payload currency ──
    fake_package, fake_bidder = _unlabelled_package_award(patched, project_id=uuid.uuid4())
    await proc_events._create_po_from_bid_award(
        _award_event_carrying(fake_package, fake_bidder, currency=payload_currency),
    )
    po_currency = patched.purchase_orders[0].currency_code

    labels = {
        "BidAward.currency (the stored row)": award.currency,
        "the published payload": payload_currency,
        "Contract.currency": contract.currency,
        "PurchaseOrder.currency_code": po_currency,
    }
    assert len(set(labels.values())) == 1, (
        "one award, and the records describing it do not agree what money it is: "
        f"{labels}. The amount is 95000.00 in every one of them, and the winning "
        "submission is in EUR."
    )


@pytest.mark.asyncio
async def test_a_labelled_package_hides_the_difference(patched: _FakeStore) -> None:
    """The paired control, and the reason no existing test caught this.

    Same seed, same handler, package labelled. The first term of every chain
    wins and the rest is never evaluated, so the two consumers agree by
    accident rather than by construction. Without this it would be possible to
    read the test above as the PO chain being broken in general.
    """
    project_id = uuid.uuid4()
    package, bidder = _seed_bid_award(patched, project_id=project_id)
    assert package.currency == "EUR"

    await proc_events._create_po_from_bid_award(_award_event_carrying(package, bidder, currency="EUR"))

    po = patched.purchase_orders[0]
    assert po.currency_code == "EUR"
