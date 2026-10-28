# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠PG: which submission an award refers to, when a bidder has more than one.

A bidder can hold several submissions in one package. ``BidSubmission``
constrains ``invitation_id`` to be unique but not ``bidder_id``, nothing forbids
inviting the same company twice, and ``record_submission`` checks only that the
bidder and the invitation agree about the package. A revised round produces
exactly this shape through the ordinary API.

Two subscribers of ``bid_management.package.awarded`` read that submission and
used to pick differently. The contract subscriber read an unbounded query with
``scalar_one_or_none``, which raises on two rows, and its handler-wide
``except Exception`` swallowed the failure at debug level: the award created no
contract and reported nothing.

These tests must run against a real database. The fake session in
``tests/unit/test_procurement_events.py`` models neither ``order_by`` nor
``limit``, and its ``scalar_one_or_none`` returns the first row where SQLAlchemy
raises, so under that double both the defect and the fix are invisible.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.bid_management.award_selection import select_awarded_submission
from app.modules.bid_management.models import (
    Bidder,
    BidInvitation,
    BidPackage,
    BidPackageLineItem,
    BidSubmission,
    BidSubmissionLine,
)
from app.modules.contracts.models import Contract, ContractLine
from app.modules.notifications import _wave5_cross_module_subscribers as w5
from app.modules.projects.models import Project
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio

_BASE_TIME = datetime(2026, 8, 24, 9, 0, tzinfo=UTC)


class _NonCommittingSession:
    """The real session with ``commit`` demoted to ``flush``.

    The subscriber opens its own session and commits, which is right in
    production and fatal to a test that keeps its rows inside a transaction it
    means to roll back. Everything else is forwarded, so the handler runs its
    real SQL against the real schema.
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


async def _seed(session, submissions: list[tuple[bool, str, int]]):
    """Seed a package with one bidder and one priced line per submission.

    ``submissions`` is a list of ``(is_valid, unit_price, minutes_offset)``, so
    each test states the shape it is about instead of relying on insertion
    order. ``created_at`` is set explicitly: it has a Python-side default, and
    rows written in one transaction would otherwise share a timestamp and make
    "newest" undecidable.
    """
    owner = User(
        email=f"award-{uuid.uuid4().hex[:8]}@example.test",
        hashed_password="x",
        full_name="Award Owner",
    )
    session.add(owner)
    await session.flush()
    project = Project(name="Selection project", owner_id=owner.id)
    session.add(project)
    await session.flush()

    code = f"BP-{uuid.uuid4().hex[:8]}"
    package = BidPackage(project_id=project.id, code=code, title="Concrete works", currency="EUR")
    session.add(package)
    await session.flush()

    pkg_line = BidPackageLineItem(
        package_id=package.id,
        code="C-100",
        description="In situ concrete",
        unit="m3",
        quantity=Decimal("10"),
        order_index=0,
    )
    session.add(pkg_line)
    bidder = Bidder(package_id=package.id, company_name="ACME Bau GmbH", status="active")
    session.add(bidder)
    await session.flush()

    made: list[BidSubmission] = []
    for is_valid, unit_price, minutes in submissions:
        inv = BidInvitation(
            package_id=package.id,
            invitee_email="bids@acme.test",
            invitee_company_name="ACME Bau GmbH",
            status="submitted",
        )
        session.add(inv)
        await session.flush()
        sub = BidSubmission(
            invitation_id=inv.id,
            bidder_id=bidder.id,
            total_amount=Decimal(unit_price) * 10,
            currency="EUR",
            is_valid=is_valid,
            created_at=_BASE_TIME.replace(minute=minutes),
        )
        session.add(sub)
        await session.flush()
        session.add(
            BidSubmissionLine(
                submission_id=sub.id,
                line_item_id=pkg_line.id,
                quantity_priced=Decimal("10"),
                unit_price=Decimal(unit_price),
                total_price=Decimal(unit_price) * 10,
            )
        )
        await session.flush()
        made.append(sub)

    return package, bidder, project, made


async def _award(session, monkeypatch, package, bidder, project) -> Contract | None:
    monkeypatch.setattr(w5, "async_session_factory", lambda: _NonCommittingSession(session))
    event = w5.Event(
        name="bid_management.package.awarded",
        data={
            "package_id": str(package.id),
            "project_id": str(project.id),
            "awarded_bidder_id": str(bidder.id),
            "awarded_amount": "95000.00",
            "currency": "EUR",
        },
        source_module="bid_management",
    )
    await w5._on_bid_package_awarded(event)
    stmt = select(Contract).where(Contract.code == f"CONTRACT-{package.code}")
    return (await session.execute(stmt)).scalar_one_or_none()


@pytest.mark.parametrize("count", [1, 2])
async def test_an_award_produces_a_contract_whatever_the_submission_count(
    pg_session, monkeypatch, caplog, count: int
) -> None:
    """The regression control, and the reason it is parametrised.

    One submission passed before this fix and two produced nothing at all, so a
    test seeding a single submission would have gone green over the defect. The
    one-submission case is kept as the negative control: it shows the two-row
    case is not passing because the assertion is weak.
    """
    package, bidder, project, _ = await _seed(pg_session, [(True, "100", m) for m in range(count)])

    with caplog.at_level("DEBUG", logger=w5.logger.name):
        contract = await _award(pg_session, monkeypatch, package, bidder, project)

    assert contract is not None, (
        f"no contract for an award with {count} submission(s). The handler swallows every failure "
        f"into logger.debug; captured: {[r.getMessage() for r in caplog.records]}"
    )


async def test_the_contract_is_priced_from_the_newest_valid_submission(pg_session, monkeypatch) -> None:
    """Two valid submissions, and the later one is the award's subject."""
    package, bidder, project, made = await _seed(pg_session, [(True, "100", 0), (True, "200", 30)])

    contract = await _award(pg_session, monkeypatch, package, bidder, project)
    assert contract is not None

    stmt = select(ContractLine).where(ContractLine.contract_id == contract.id)
    lines = (await pg_session.execute(stmt)).scalars().all()
    assert [str(line.unit_rate) for line in lines] == ["200.0000"], (
        "the contract priced from a submission other than the newest valid one"
    )

    chosen = await select_awarded_submission(pg_session, bidder_id=bidder.id)
    assert chosen is not None
    assert chosen.id == made[1].id


async def test_a_valid_submission_outranks_a_newer_invalid_one(pg_session, monkeypatch) -> None:
    """Validity is the first term, so a later invalid row does not displace it.

    This is the rule the purchase-order subscriber already applied. It is
    asserted here so that making the two subscribers agree cannot quietly
    become a change to what ``is_valid`` means for existing rows.
    """
    package, bidder, project, made = await _seed(pg_session, [(True, "100", 0), (False, "999", 30)])

    chosen = await select_awarded_submission(pg_session, bidder_id=bidder.id)
    assert chosen is not None
    assert chosen.id == made[0].id

    contract = await _award(pg_session, monkeypatch, package, bidder, project)
    assert contract is not None
    stmt = select(ContractLine).where(ContractLine.contract_id == contract.id)
    lines = (await pg_session.execute(stmt)).scalars().all()
    assert [str(line.unit_rate) for line in lines] == ["100.0000"]


async def test_the_selector_falls_back_to_the_newest_when_none_is_valid(pg_session) -> None:
    """No valid submission at all: the newest row still wins.

    The award endpoint refuses to award a package with no valid submission, so
    this shape reaches the subscribers only through rows written before that
    guard or outside the bidding flow. The purchase-order subscriber already
    behaved this way and the behaviour is preserved rather than tightened.
    """
    _, bidder, _, made = await _seed(pg_session, [(False, "100", 0), (False, "200", 30)])

    chosen = await select_awarded_submission(pg_session, bidder_id=bidder.id)
    assert chosen is not None
    assert chosen.id == made[1].id


async def test_a_bidder_with_no_submission_resolves_to_none(pg_session) -> None:
    """A package can be awarded from outside the bidding flow."""
    _, bidder, _, _ = await _seed(pg_session, [])
    assert await select_awarded_submission(pg_session, bidder_id=bidder.id) is None
