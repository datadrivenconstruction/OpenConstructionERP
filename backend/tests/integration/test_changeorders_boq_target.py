# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠DB-backed tests for which bill an approved change order is written into.

The target used to be "the project's oldest unlocked BOQ", picked by
``created_at`` and recorded only in a log line. No caller passes ``boq_id``,
so that guess was the live default rather than a rare fallback: on a project
holding two unlocked bills it wrote real money into a bill nobody named, and
the read-only preview ran its own copy of the same query, so it agreed with
the wrong answer instead of exposing it.

The rule is now about ambiguity: one candidate is an answer, several
candidates are a question, and a question is refused. The refusal belongs to
the approval, not only to the writeback - ``approve_order`` returns early on
an order that is already approved and ``_apply_to_boq`` has exactly one call
site inside it, so an approval that lands without placing its scope can never
place it afterwards. Refusing costs a retry; reporting would cost a permanent
gap between the budget and the bills.

These tests run against a real PostgreSQL database rather than a stubbed
session, because the claim under test is that the *query* is right - a stub
would only re-state the service's own branching back at it. The last section
drives the HTTP endpoint instead, because the claim there is that the refusal
is visible from outside the module.

Every case seeds ``ChangeOrderItem`` rows unless it says otherwise:
``_apply_to_boq`` returns ``no_items`` before it ever consults the resolver,
so an item-less change order would "refuse" for a reason that has nothing to
do with the target. The one case that seeds none asserts exactly that.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Import the sibling ORM modules so their tables exist in Base.metadata.
import app.modules.boq.models  # noqa: F401
import app.modules.changeorders.models  # noqa: F401
import app.modules.finance.models  # noqa: F401
import app.modules.projects.models  # noqa: F401
from app.main import create_app
from app.modules.boq.models import BOQ, Position
from app.modules.changeorders.models import ChangeOrder, ChangeOrderApproval, ChangeOrderItem
from app.modules.changeorders.service import ChangeOrderService
from app.modules.projects.models import Project
from tests._pg import transactional_session

#: Submitter and approver must differ - ``_assert_not_self_approval`` enforces
#: the four-eyes principle on the single-step approval path.
SUBMITTER = "11111111-1111-1111-1111-111111111111"
APPROVER = "22222222-2222-2222-2222-222222222222"

_EPOCH = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Isolated PostgreSQL session, FK triggers off, rolled back on teardown."""
    async with transactional_session(disable_fks=True) as sess:
        yield sess


# ── Seed helpers ────────────────────────────────────────────────────────────


async def _make_project(session: AsyncSession, name: str = "Harbour Terminal") -> Project:
    project = Project(
        name=name,
        owner_id=uuid.uuid4(),
        currency="EUR",
        budget_estimate="1000000",
    )
    session.add(project)
    await session.flush()
    return project


async def _make_boq(
    session: AsyncSession,
    project: Project,
    name: str,
    *,
    locked: bool = False,
    age_days: int = 0,
) -> BOQ:
    """One bill on ``project``. ``age_days`` fixes ``created_at`` so the
    "oldest unlocked bill" the old code picked is deterministic, which is what
    makes the bite proof in this file meaningful."""
    boq = BOQ(
        project_id=project.id,
        name=name,
        is_locked=locked,
        created_at=_EPOCH + timedelta(days=age_days),
    )
    session.add(boq)
    await session.flush()
    return boq


async def _make_submitted_order(
    session: AsyncSession,
    project: Project,
    *,
    code: str = "CO-001",
    title: str = "Extra piling to grid F",
    item_count: int = 2,
) -> ChangeOrder:
    """A submitted change order with priced line items, ready to approve."""
    order = ChangeOrder(
        project_id=project.id,
        code=code,
        title=title,
        description="Ground conditions differed from the geotechnical report.",
        status="submitted",
        submitted_by=SUBMITTER,
        submitted_at=datetime.now(UTC).isoformat()[:19],
        cost_impact=Decimal("12500.00"),
        currency="EUR",
        schedule_impact_days=4,
    )
    session.add(order)
    await session.flush()
    for idx in range(item_count):
        session.add(
            ChangeOrderItem(
                change_order_id=order.id,
                description=f"Additional bored pile {idx + 1}",
                change_type="added",
                new_quantity=Decimal("1"),
                new_rate=Decimal("6250.00"),
                cost_delta=Decimal("6250.00"),
                unit="nr",
                sort_order=idx,
            )
        )
    await session.flush()
    return order


async def _position_count(session: AsyncSession, boq_id: uuid.UUID) -> int:
    rows = (await session.execute(select(Position.id).where(Position.boq_id == boq_id))).scalars().all()
    return len(rows)


async def _section_boq_id(session: AsyncSession, order_id: uuid.UUID) -> uuid.UUID | None:
    """Which bill actually received the CO section, read back from the DB.

    Deliberately not taken from the service's return value: the point of these
    tests is that rows landed, not that a function reported that they did.
    """
    sections = (await session.execute(select(Position).where(Position.unit == "section"))).scalars().all()
    for section in sections:
        md = section.metadata_ if isinstance(section.metadata_, dict) else {}
        if md.get("change_order_id") == str(order_id):
            return section.boq_id
    return None


def _capture_writeback(service: ChangeOrderService) -> dict:
    """Record what the real approval path decided about the BOQ writeback.

    ``approve_order`` returns the change order, not the writeback verdict, so
    the reason string is otherwise invisible from the outside. The wrapper
    delegates to the original method and changes nothing about its behaviour -
    the assertions still describe the production code path.
    """
    captured: dict = {}
    original = service._apply_to_boq

    async def _wrapped(order, **kwargs):
        result = await original(order, **kwargs)
        captured.clear()
        captured.update(result)
        return result

    service._apply_to_boq = _wrapped  # type: ignore[method-assign]
    return captured


# ── 1. Positive control ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_single_unlocked_bill_still_receives_the_change_order(session: AsyncSession) -> None:
    """The ordinary project - one bill - behaves exactly as it did before.

    This case is not decoration. A resolver that refused everything would
    satisfy every ambiguity assertion below; only a test that watches rows
    arrive can tell "correctly refused" from "broken".
    """
    project = await _make_project(session)
    boq = await _make_boq(session, project, "Main bill")
    order = await _make_submitted_order(session, project)

    service = ChangeOrderService(session)
    verdict = _capture_writeback(service)
    approved = await service.approve_order(order.id, APPROVER)

    assert approved.status == "approved"
    assert verdict["applied"] is True
    assert verdict["positions_added"] == 2
    # One section header plus one position per change-order item.
    assert await _position_count(session, boq.id) == 3
    assert await _section_boq_id(session, order.id) == boq.id


# ── 2. Ambiguity is refused, and refused without side effects ───────────────


@pytest.mark.asyncio
async def test_two_unlocked_bills_refuse_the_approval_and_write_into_neither(session: AsyncSession) -> None:
    """Two candidates is a question, and the answer is not "the older one".

    The whole transition is refused, not just its BOQ half. Approving and
    reporting the un-written scope on the side would have been the other
    honest shape, and it is the unrecoverable one: the budget would have
    moved, the order would read ``approved``, and no later request could put
    the scope in a bill. So the assertions here are about what did *not*
    happen - status, approver, budget, positions.
    """
    project = await _make_project(session)
    first = await _make_boq(session, project, "Base contract bill", age_days=0)
    second = await _make_boq(session, project, "Variations bill", age_days=5)
    order = await _make_submitted_order(session, project)

    before = (await _position_count(session, first.id), await _position_count(session, second.id))
    budget_before = project.budget_estimate

    service = ChangeOrderService(session)
    with pytest.raises(HTTPException) as raised:
        await service.approve_order(order.id, APPROVER)

    assert raised.value.status_code == 409
    detail = raised.value.detail
    assert detail["error"] == "ambiguous_boq"
    # The refusal carries the answer set, so the question it asks can be
    # answered without going to look the bills up somewhere else.
    assert {c["name"] for c in detail["candidates"]} == {"Base contract bill", "Variations bill"}
    assert {c["id"] for c in detail["candidates"]} == {str(first.id), str(second.id)}

    after = (await _position_count(session, first.id), await _position_count(session, second.id))
    assert after == before == (0, 0)
    assert await _section_boq_id(session, order.id) is None

    persisted = (await session.execute(select(ChangeOrder).where(ChangeOrder.id == order.id))).scalar_one()
    assert persisted.status == "submitted"
    assert persisted.approved_by is None
    project_row = (await session.execute(select(Project).where(Project.id == project.id))).scalar_one()
    assert project_row.budget_estimate == budget_before


# ── 3. A locked sibling is not a candidate ─────────────────────────────────


@pytest.mark.asyncio
async def test_locked_sibling_leaves_exactly_one_candidate(session: AsyncSession) -> None:
    """Two bills, one locked: the unlocked one is the only answer, so it wins.

    The locked bill is the *older* of the two, so a resolver that filtered
    nothing and took the first row would land in the wrong bill here.
    """
    project = await _make_project(session)
    locked = await _make_boq(session, project, "Signed tender bill", locked=True, age_days=0)
    live = await _make_boq(session, project, "Working bill", age_days=3)
    order = await _make_submitted_order(session, project)

    service = ChangeOrderService(session)
    verdict = _capture_writeback(service)
    await service.approve_order(order.id, APPROVER)

    assert verdict["applied"] is True
    assert verdict["boq_id"] == str(live.id)
    assert await _position_count(session, live.id) == 3
    assert await _position_count(session, locked.id) == 0


# ── 4. An explicit target is the whole answer ──────────────────────────────


@pytest.mark.asyncio
async def test_explicit_boq_id_wins_over_several_unlocked_bills(session: AsyncSession) -> None:
    """Naming the bill removes the ambiguity, including the oldest-first tie."""
    project = await _make_project(session)
    oldest = await _make_boq(session, project, "Bill A", age_days=0)
    await _make_boq(session, project, "Bill B", age_days=1)
    chosen = await _make_boq(session, project, "Bill C", age_days=2)
    order = await _make_submitted_order(session, project)

    service = ChangeOrderService(session)
    verdict = _capture_writeback(service)
    await service.approve_order(order.id, APPROVER, boq_id=chosen.id)

    assert verdict["applied"] is True
    assert verdict["boq_id"] == str(chosen.id)
    assert await _position_count(session, chosen.id) == 3
    assert await _position_count(session, oldest.id) == 0
    assert await _section_boq_id(session, order.id) == chosen.id


@pytest.mark.asyncio
async def test_explicit_boq_id_is_still_checked(session: AsyncSession) -> None:
    """An explicit id short-circuits the search, not the project/lock rules.

    These three refusals used to be silent 200s, and nothing reached them
    because no caller passed ``boq_id`` at all. Now that a caller answering
    the ambiguity question passes one, they are reachable from the UI for the
    first time: a bill locked between the preview and the click has to say so
    rather than swallow the scope.
    """
    project = await _make_project(session)
    only = await _make_boq(session, project, "Only bill")
    locked = await _make_boq(session, project, "Locked bill", locked=True, age_days=1)

    other_project = await _make_project(session, name="Riverside Depot")
    foreign = await _make_boq(session, other_project, "Someone else's bill")

    service = ChangeOrderService(session)

    async def _refusal(code: str, boq_id: uuid.UUID) -> dict:
        order = await _make_submitted_order(session, project, code=code)
        with pytest.raises(HTTPException) as raised:
            await service.approve_order(order.id, APPROVER, boq_id=boq_id)
        assert raised.value.status_code == 409
        persisted = (await session.execute(select(ChangeOrder).where(ChangeOrder.id == order.id))).scalar_one()
        assert persisted.status == "submitted"
        return raised.value.detail

    assert (await _refusal("CO-101", locked.id))["error"] == "boq_locked"

    mismatch = await _refusal("CO-102", foreign.id)
    assert mismatch["error"] == "boq_project_mismatch"
    assert await _position_count(session, foreign.id) == 0

    missing = await _refusal("CO-103", uuid.uuid4())
    assert missing["error"] == "boq_not_found"
    # Every refusal offers the bills that could have taken the scope, so a
    # wrong id is answerable in the same round trip that rejected it.
    assert [c["id"] for c in missing["candidates"]] == [str(only.id)]


# ── 5. No candidate at all ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_only_bill_being_locked_is_refused_not_shrugged_off(session: AsyncSession) -> None:
    """A locked-out project is a question, not an absence.

    This case used to answer ``no_active_boq`` and approve: the filter that
    keeps the scope out of a locked bill also erased the difference between
    "this project has no bill" and "this project's only bill is locked". They
    are not the same fact. The first leaves the caller nothing to do, which is
    why it is still allowed through. The second has an obvious answer - unlock
    the bill, or open another - and treating it as an absence moved the budget
    while writing no scope and saying nothing, on a project with a single bill
    and no ambiguity anywhere in sight.

    The candidate list is the locked bill itself. Listing writable candidates
    here would be an empty list, and an empty list names nothing to unlock.
    """
    project = await _make_project(session)
    locked = await _make_boq(session, project, "Frozen bill", locked=True)
    order = await _make_submitted_order(session, project)
    before = (await session.execute(select(Project).where(Project.id == project.id))).scalar_one().budget_estimate

    service = ChangeOrderService(session)
    with pytest.raises(HTTPException) as raised:
        await service.approve_order(order.id, APPROVER)

    assert raised.value.status_code == 409
    assert raised.value.detail["error"] == "boq_locked"
    assert [c["name"] for c in raised.value.detail["candidates"]] == ["Frozen bill"]

    assert await _position_count(session, locked.id) == 0
    persisted = (await session.execute(select(ChangeOrder).where(ChangeOrder.id == order.id))).scalar_one()
    assert persisted.status == "submitted"
    assert persisted.approved_by is None
    after = (await session.execute(select(Project).where(Project.id == project.id))).scalar_one().budget_estimate
    assert after == before


# ── 6. Preview and approval must give the same answer ──────────────────────


@pytest.mark.asyncio
async def test_preview_names_the_bill_the_approval_writes_into(session: AsyncSession) -> None:
    """Compare the two answers, not two hardcoded expectations.

    The preview used to run its own copy of the approval's query, which is why
    it could agree with a wrong answer. Asserting a literal name here would
    re-create that: it would keep passing if both paths drifted together. So
    the preview's name is read first, the approval is then allowed to place
    the section wherever it likes, and the bill it actually chose is looked up
    by id and compared against what the preview promised.
    """
    project = await _make_project(session)
    await _make_boq(session, project, "Signed tender bill", locked=True, age_days=0)
    live = await _make_boq(session, project, "Live working bill", age_days=1)
    order = await _make_submitted_order(session, project)

    service = ChangeOrderService(session)
    preview = await service.simulate_impact(order.id)
    promised_name = preview["boq"]["target_boq_name"]
    assert preview["boq"]["target_boq_ambiguous"] is False
    assert promised_name is not None

    await service.approve_order(order.id, APPROVER)

    landed_boq_id = await _section_boq_id(session, order.id)
    assert landed_boq_id is not None
    landed = (await session.execute(select(BOQ).where(BOQ.id == landed_boq_id))).scalar_one()
    assert landed.name == promised_name
    assert landed.id == live.id


@pytest.mark.asyncio
async def test_preview_reports_ambiguity_where_the_approval_refuses(session: AsyncSession) -> None:
    """The ambiguous half of the same agreement.

    ``target_boq_name is None`` on its own is what "no bill at all" also looks
    like, so the flag is what carries the difference. A preview that said
    nothing here would be read as "the project bill", which is the guess the
    whole change removed.
    """
    project = await _make_project(session)
    await _make_boq(session, project, "Base contract bill", age_days=0)
    await _make_boq(session, project, "Variations bill", age_days=2)
    order = await _make_submitted_order(session, project)

    service = ChangeOrderService(session)
    preview = await service.simulate_impact(order.id)

    assert preview["boq"]["target_boq_ambiguous"] is True
    assert preview["boq"]["target_boq_name"] is None

    with pytest.raises(HTTPException) as raised:
        await service.approve_order(order.id, APPROVER)

    # The two paths agree: the preview refuses to name a bill and the
    # approval refuses to pick one.
    assert raised.value.detail["error"] == "ambiguous_boq"
    assert await _section_boq_id(session, order.id) is None


@pytest.mark.asyncio
async def test_preview_distinguishes_ambiguity_from_having_no_bill(session: AsyncSession) -> None:
    """No unlocked bill is a name-less preview that is *not* flagged ambiguous."""
    project = await _make_project(session)
    await _make_boq(session, project, "Frozen bill", locked=True)
    order = await _make_submitted_order(session, project)

    preview = await ChangeOrderService(session).simulate_impact(order.id)

    assert preview["boq"]["target_boq_name"] is None
    assert preview["boq"]["target_boq_ambiguous"] is False


# ── 7. What the refusal does NOT cover ─────────────────────────────────────


@pytest.mark.asyncio
async def test_a_project_with_no_bill_at_all_still_approves(session: AsyncSession) -> None:
    """The refused set is the set the caller can act on, and no wider.

    A project holding no bill of quantities leaves nothing to name and nothing
    to unlock: plenty of them run commercial change control without ever
    opening one, modules being plugins here. Refusing would put a question
    about an unused module in front of the approval button, so
    ``no_active_boq`` stays a skipped writeback on a successful approval - the
    behaviour it has always had.

    This is the negative half of the ambiguity tests. A check that refused
    every un-written outcome would satisfy all of them and would be wrong,
    and it is the boundary against the locked-bill refusal in section 5: the
    two projects differ by one row.
    """
    project = await _make_project(session)
    order = await _make_submitted_order(session, project)

    service = ChangeOrderService(session)
    verdict = _capture_writeback(service)
    approved = await service.approve_order(order.id, APPROVER)

    assert verdict["reason"] == "no_active_boq"
    assert approved.status == "approved"
    assert approved.approved_by == APPROVER

    # And it is approved in the database, not merely in the returned instance.
    persisted = (await session.execute(select(ChangeOrder).where(ChangeOrder.id == order.id))).scalar_one()
    assert persisted.status == "approved"


@pytest.mark.asyncio
async def test_an_item_less_change_order_is_never_ambiguous(session: AsyncSession) -> None:
    """Nothing to place is not a question about where to place it.

    A change order with no line items is a budget-only decision. It has always
    been approvable, and the ambiguity check runs ahead of ``_apply_to_boq``,
    which is where ``no_items`` is detected - so without an explicit guard the
    check would have started blocking approvals that write nothing at all.
    """
    project = await _make_project(session)
    await _make_boq(session, project, "Base contract bill", age_days=0)
    await _make_boq(session, project, "Variations bill", age_days=1)
    order = await _make_submitted_order(session, project, item_count=0)

    approved = await ChangeOrderService(session).approve_order(order.id, APPROVER)

    assert approved.status == "approved"


# ── 8. The approval chain reaches the same refusal, one step earlier ───────


@pytest.mark.asyncio
async def test_the_final_chain_step_refuses_before_it_stamps_itself(session: AsyncSession) -> None:
    """The chain hands over to the same writeback, so it asks the same question.

    Where it asks matters. ``advance_approval`` stamps the step, publishes a
    "chain complete" event and only then calls ``approve_order``; the event is
    published detached from this session, so a refusal raised at the end would
    roll the rows back and leave the event already gone. The step row staying
    ``pending`` is what proves the check ran ahead of all of that.
    """
    project = await _make_project(session)
    await _make_boq(session, project, "Base contract bill", age_days=0)
    await _make_boq(session, project, "Variations bill", age_days=1)
    order = await _make_submitted_order(session, project)

    service = ChangeOrderService(session)
    await service.start_approval_chain(order.id, [uuid.UUID(APPROVER)])

    with pytest.raises(HTTPException) as raised:
        await service.advance_approval(order.id, APPROVER, "approved")
    assert raised.value.status_code == 409
    assert raised.value.detail["error"] == "ambiguous_boq"

    steps = (
        (await session.execute(select(ChangeOrderApproval).where(ChangeOrderApproval.change_order_id == order.id)))
        .scalars()
        .all()
    )
    assert [s.decision for s in steps] == ["pending"]
    persisted = (await session.execute(select(ChangeOrder).where(ChangeOrder.id == order.id))).scalar_one()
    assert persisted.status == "submitted"


@pytest.mark.asyncio
async def test_the_final_chain_step_can_name_the_bill(session: AsyncSession) -> None:
    """And the question is answerable from the chain, not only from /approve.

    Without ``boq_id`` on the advance request the chain would be a dead end on
    a project with several unlocked bills: the last approver refused, with no
    field to answer in.
    """
    project = await _make_project(session)
    await _make_boq(session, project, "Base contract bill", age_days=0)
    chosen = await _make_boq(session, project, "Variations bill", age_days=1)
    order = await _make_submitted_order(session, project)

    service = ChangeOrderService(session)
    await service.start_approval_chain(order.id, [uuid.UUID(APPROVER)])
    await service.advance_approval(order.id, APPROVER, "approved", boq_id=chosen.id)

    persisted = (await session.execute(select(ChangeOrder).where(ChangeOrder.id == order.id))).scalar_one()
    assert persisted.status == "approved"
    assert await _section_boq_id(session, order.id) == chosen.id
    assert await _position_count(session, chosen.id) == 3


# ── 8b. What the preview costs, and what it does with a failure ───────────


@pytest.mark.asyncio
async def test_the_candidate_query_is_capped_at_two_rows(session: AsyncSession) -> None:
    """Two rows settle "one candidate or several"; the rest are not read.

    This query runs on the preview path, which re-runs on every impact
    simulation - each time a reviewer nudges a cost or a duration. Reading
    every unlocked bill on the project to compute a boolean is the kind of
    cost that never shows up on the project that has two bills and does show
    up on the one that has two hundred.
    """
    project = await _make_project(session)
    for index in range(5):
        await _make_boq(session, project, f"Bill {index}", age_days=index)
    order = await _make_submitted_order(session, project)

    service = ChangeOrderService(session)
    bill_queries: list[tuple[str, dict]] = []
    original = service.session.execute

    async def _spy(stmt, *args, **kwargs):  # type: ignore[no-untyped-def]
        text = str(stmt)
        if "oe_boq_boq" in text:
            bill_queries.append((text, dict(stmt.compile().params)))
        return await original(stmt, *args, **kwargs)

    service.session.execute = _spy  # type: ignore[method-assign]
    try:
        preview = await service.simulate_impact(order.id)
    finally:
        service.session.execute = original  # type: ignore[method-assign]

    assert preview["boq"]["target_boq_ambiguous"] is True
    assert len(bill_queries) == 1, bill_queries
    sql, params = bill_queries[0]
    assert "LIMIT" in sql.upper(), sql
    assert 2 in params.values(), params


@pytest.mark.asyncio
async def test_a_failed_lookup_is_not_reported_as_having_no_bill(session: AsyncSession) -> None:
    """A broken query and a project with no bill are different answers.

    Both used to arrive as ``(None, False)``, which the panel renders as a
    sentence about a bill it does not have. The preview is read-only and
    everything above it in ``simulate_impact`` already fails loudly on a dead
    session, so surfacing here costs no working preview and stops one lying.
    """
    project = await _make_project(session)
    await _make_boq(session, project, "Main bill")
    order = await _make_submitted_order(session, project)

    service = ChangeOrderService(session)

    async def _explode(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("the bill lookup failed")

    service._resolve_writeback_boq = _explode  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="the bill lookup failed"):
        await service.simulate_impact(order.id)


@pytest.mark.asyncio
async def test_an_absent_boq_module_still_reads_as_no_bill(session: AsyncSession) -> None:
    """The one failure that really is "no bill": the module is not installed.

    Modules are plugins on this platform, so a deployment without the
    bill-of-quantities module has no target rather than a broken one. It is
    also the reason the old blanket ``except Exception`` existed, so the
    narrower catch has to keep answering this case the same way.
    """
    project = await _make_project(session)
    order = await _make_submitted_order(session, project)

    service = ChangeOrderService(session)

    async def _absent(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise ImportError("No module named 'app.modules.boq.models'")

    service._resolve_writeback_boq = _absent  # type: ignore[method-assign]

    preview = await service.simulate_impact(order.id)

    assert preview["boq"]["target_boq_name"] is None
    assert preview["boq"]["target_boq_ambiguous"] is False


@pytest.mark.asyncio
async def test_an_unreadable_item_count_still_asks_which_bill(session: AsyncSession) -> None:
    """A count that could not be read is not a count of zero.

    The ambiguity check skips change orders with no line items, because those
    place nothing and have nothing to be ambiguous about. That skip reads a
    count, and the count used to answer 0 on any failure - so a broken query
    would have said "no items", the question would have gone unasked, and an
    ambiguous project would have approved with nothing written: the exact
    silence this whole check exists to end, rebuilt inside it.

    Unknown therefore asks anyway. The cost of asking about an order that
    turns out to be empty is a 409 the caller can retry; the cost of skipping
    is an approval nobody can undo. The paired test above
    (``test_an_item_less_change_order_is_never_ambiguous``) holds the other
    side: a real zero still skips, so this is not a check that simply always
    fires.
    """
    project = await _make_project(session)
    await _make_boq(session, project, "Base contract bill", age_days=0)
    await _make_boq(session, project, "Variations bill", age_days=1)
    order = await _make_submitted_order(session, project, item_count=0)

    service = ChangeOrderService(session)
    real_execute = session.execute

    async def _fail_the_count(stmt, *args, **kwargs):  # type: ignore[no-untyped-def]
        sql = str(stmt)
        if "oe_changeorders_item" in sql and "count" in sql.lower():
            raise RuntimeError("the item count failed")
        return await real_execute(stmt, *args, **kwargs)

    session.execute = _fail_the_count  # type: ignore[method-assign]
    try:
        with pytest.raises(HTTPException) as excinfo:
            await service.approve_order(order.id, APPROVER)
    finally:
        session.execute = real_execute  # type: ignore[method-assign]

    assert excinfo.value.status_code == 409
    assert excinfo.value.detail["error"] == "ambiguous_boq"

    await session.refresh(order)
    assert order.status == "submitted"


# ── 9. The refusal seen from outside the module ────────────────────────────
#
# Everything above reaches into ``ChangeOrderService``. That is the right lens
# for "did the query pick the right bill", and the wrong one for the finding
# that started this: the service already knew the writeback had been refused,
# and the caller could not tell, because the refusal lived in a return value
# the endpoint never serialised. A test that reads that return value proves
# nothing about what the caller sees. These drive the HTTP surface instead -
# register, seed, submit, approve - and read every claim back over the wire.


@pytest_asyncio.fixture
async def client():
    """The real FastAPI app, lifespan included, over an in-process transport."""
    app = create_app()
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac


async def _admin_headers(client: AsyncClient, label: str) -> dict[str, str]:
    """Register, activate and log in one admin, returning their auth header.

    Two are needed per case: the four-eyes rule refuses an approver who is
    also the submitter, and that rule is enforced before the bill question is
    ever asked. Admin, because ``changeorders.approve`` is admin/manager only
    and because ``verify_project_access`` would otherwise 404 the second user
    out of a project the first one owns - neither of which is what these tests
    are about.
    """
    from tests.integration._auth_helpers import promote_to_admin

    unique = uuid.uuid4().hex[:8]
    email = f"co-{label}-{unique}@boqtarget.io"
    password = f"CoBoq{unique}9"
    registered = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"CO {label}"},
    )
    # Asserted rather than assumed: a rejected registration surfaces two steps
    # later as "user not found" inside the promotion helper, which reads like a
    # database-isolation problem and is not one.
    assert registered.status_code in (200, 201), registered.text
    await promote_to_admin(email)
    login = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _seed_over_http(
    client: AsyncClient,
    author: dict[str, str],
    bill_names: list[str],
) -> tuple[str, list[str], str]:
    """A project, its bills and one submitted change order, all via the API.

    Returns ``(project_id, boq_ids, change_order_id)``. Seeding through HTTP
    rather than the ORM keeps the fixture honest: the rows are the ones the
    product itself creates, including the defaults these tests never set.
    """
    unique = uuid.uuid4().hex[:6]
    project = await client.post("/api/v1/projects/", json={"name": f"Harbour Terminal {unique}"}, headers=author)
    assert project.status_code in (200, 201), project.text
    project_id = project.json()["id"]

    boq_ids: list[str] = []
    for name in bill_names:
        created = await client.post(
            "/api/v1/boq/boqs/",
            json={"project_id": project_id, "name": name},
            headers=author,
        )
        assert created.status_code in (200, 201), created.text
        boq_ids.append(created.json()["id"])

    order = await client.post(
        "/api/v1/changeorders/",
        json={
            "project_id": project_id,
            "title": "Extra piling to grid F",
            "description": "Ground conditions differed from the geotechnical report.",
            "schedule_impact_days": 4,
        },
        headers=author,
    )
    assert order.status_code in (200, 201), order.text
    order_id = order.json()["id"]

    item = await client.post(
        f"/api/v1/changeorders/{order_id}/items/",
        json={
            "description": "Additional bored pile",
            "change_type": "added",
            "new_quantity": "2",
            "new_rate": "6250.00",
            "unit": "nr",
        },
        headers=author,
    )
    assert item.status_code in (200, 201), item.text

    submitted = await client.post(f"/api/v1/changeorders/{order_id}/submit/", headers=author)
    assert submitted.status_code == 200, submitted.text
    return project_id, boq_ids, order_id


async def _positions(client: AsyncClient, headers: dict[str, str], boq_id: str) -> list[dict]:
    """Every position row in a bill, read back over HTTP."""
    resp = await client.get(f"/api/v1/boq/boqs/{boq_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["positions"]


@pytest.mark.asyncio
async def test_the_endpoint_refuses_an_ambiguous_approval_and_says_so(client: AsyncClient) -> None:
    """The caller can tell. That is the whole finding.

    Before this, the same request answered 200 with an approved change order,
    a moved ``budget_estimate`` and no bill touched. Every assertion below is
    read back over the wire, because the earlier bug was invisible precisely
    to a caller who had only the response to go on.
    """
    author = await _admin_headers(client, "author")
    approver = await _admin_headers(client, "approver")
    project_id, boq_ids, order_id = await _seed_over_http(client, author, ["Base contract bill", "Variations bill"])

    before = await client.get(f"/api/v1/projects/{project_id}", headers=author)
    budget_before = before.json()["budget_estimate"]

    refused = await client.post(f"/api/v1/changeorders/{order_id}/approve/", headers=approver)

    assert refused.status_code == 409, refused.text
    detail = refused.json()["detail"]
    assert detail["error"] == "ambiguous_boq"
    assert detail["message"]
    # The body carries the choice, so a client can render a picker instead of
    # telling the user to go and find the bills for themselves.
    assert {c["id"] for c in detail["candidates"]} == set(boq_ids)
    assert {c["name"] for c in detail["candidates"]} == {"Base contract bill", "Variations bill"}

    # Refused means nothing moved - not the status, not the money, not a row.
    still = await client.get(f"/api/v1/changeorders/{order_id}", headers=approver)
    assert still.json()["status"] == "submitted"
    assert still.json()["approved_by"] is None
    after = await client.get(f"/api/v1/projects/{project_id}", headers=author)
    assert after.json()["budget_estimate"] == budget_before
    for boq_id in boq_ids:
        assert await _positions(client, author, boq_id) == []

    # And the question is answerable in the next request, with the id the
    # refusal just handed over.
    approved = await client.post(
        f"/api/v1/changeorders/{order_id}/approve/?boq_id={boq_ids[1]}",
        headers=approver,
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    # One section header plus one position for the change order's single item.
    assert len(await _positions(client, author, boq_ids[1])) == 2
    assert await _positions(client, author, boq_ids[0]) == []


@pytest.mark.asyncio
async def test_the_endpoint_still_approves_a_single_bill_project(client: AsyncClient) -> None:
    """The positive control, at the same level as the refusal it guards.

    An implementation that answered 409 to every approval would satisfy the
    test above completely. This is the ordinary project - one unlocked bill,
    no ``boq_id`` in the request, which is the only call the UI makes - and it
    has to keep behaving exactly as it did.
    """
    author = await _admin_headers(client, "author")
    approver = await _admin_headers(client, "approver")
    project_id, boq_ids, order_id = await _seed_over_http(client, author, ["Main bill"])

    approved = await client.post(f"/api/v1/changeorders/{order_id}/approve/", headers=approver)

    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert len(await _positions(client, author, boq_ids[0])) == 2

    moved = await client.get(f"/api/v1/projects/{project_id}", headers=author)
    assert Decimal(moved.json()["budget_estimate"]) == Decimal("12500.00")


# -- 10. Publishing a scenario, pressed rather than described -----------------
#
# The same lens as section 9, aimed at a different endpoint. publish-scenario
# stored the projection dict verbatim in a JSONB column, and the dict carried
# order_id as a uuid.UUID, so the flush raised on every call and the audit trail
# had never received a row. Nothing noticed, because the only test naming the
# handler reads a list of route names to check the route is guarded, which is a
# test about the guard and not about the route.
#
# Asserting that a snapshot dict encodes would be a test of the encoder. The
# route is what had never run, so these press it.


@pytest.mark.asyncio
async def test_publish_scenario_endpoint_stores_a_scenario(client: AsyncClient) -> None:
    """POST publish-scenario returns 200 and the order comes back carrying it.

    Before the fix this raised at flush, so the endpoint answered 500 for every
    caller of a button that ships in the impact screen.
    """
    author = await _admin_headers(client, "publish")
    project_id, _boqs, order_id = await _seed_over_http(client, author, ["Main bill"])

    published = await client.post(
        f"/api/v1/changeorders/{order_id}/publish-scenario/",
        json={"cost_impact": "50000"},
        headers=author,
    )
    assert published.status_code == 200, published.text

    scenarios = published.json()["metadata"]["simulations"]
    assert len(scenarios) == 1
    snapshot = scenarios[0]["snapshot"]
    assert snapshot["order_id"] == order_id
    assert snapshot["co_cost_native"] == "50000.00"


@pytest.mark.asyncio
async def test_a_published_scenario_survives_the_wire(client: AsyncClient) -> None:
    """What was stored is JSON, proven by asking for it back over HTTP.

    The failure was at flush rather than at read, so a value that never
    serialised is exactly the value a re-read cannot show you. Fetching the
    order again makes the database hand the column back through the same
    encoder that used to refuse it.
    """
    author = await _admin_headers(client, "wire")
    project_id, _boqs, order_id = await _seed_over_http(client, author, ["Main bill"])

    published = await client.post(
        f"/api/v1/changeorders/{order_id}/publish-scenario/",
        json={"cost_impact": "1200"},
        headers=author,
    )
    assert published.status_code == 200, published.text

    # No trailing slash. This router declares the read as "/{order_id}" and
    # the publish as "/{order_id}/publish-scenario/", so the two disagree and
    # the wrong guess is answered with a bare 404 rather than a redirect.
    fetched = await client.get(f"/api/v1/changeorders/{order_id}", headers=author)
    assert fetched.status_code == 200, fetched.text

    stored = fetched.json()["metadata"]["simulations"][-1]["snapshot"]
    assert isinstance(stored["order_id"], str)
    assert stored["order_id"] == order_id
