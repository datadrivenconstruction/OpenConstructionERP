"""Gap B unit tests: ``CostSpineService.post_actual_to_budget_line``.

The shared actual-cost posting method (costmodel/service.py) is the single sink
Finance and Gaps A/C/E call to fold realised cost into ``BudgetLine.actual_amount``.
These tests exercise it directly against a real PostgreSQL session (the only
dialect the app runs on) wrapped in a per-test transaction that is rolled back on
teardown via the canonical ``transactional_session`` helper.

Money is asserted with exact ``Decimal`` values — the spine is the source of
truth every downstream rollup sums against, so a silent float drift here would
corrupt the whole 5D model.

Covers TEST MATRIX cases 1-10 (unit):
    1  new row created with the posted amount
    2  second call with a different ref cumulates
    3  replay of the same (source_kind, source_ref) is a no-op
    4  two different refs both sum
    5  nonexistent project → HTTPException
    6  cost_line_id not in the project → HTTPException
    7  unknown category → HTTPException
    8  metadata.postings carries the audit trail
    9  costmodel.budget_line.actual_posted is emitted
    10 project with no base currency → HTTPException
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.costmodel.models import BudgetLine, ControlAccount, CostLine
from app.modules.costmodel.service import CostSpineService
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Isolated PostgreSQL session per test (rolled back on teardown)."""
    async with transactional_session() as sess:
        yield sess


# ── Seed helpers ────────────────────────────────────────────────────────────


async def _seed_project(
    session: AsyncSession,
    *,
    currency: str = "EUR",
    fx_rates: list | None = None,
) -> uuid.UUID:
    """Insert a user + project and return the project id."""
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    owner = User(
        id=uuid.uuid4(),
        email=f"gapb-{uuid.uuid4().hex[:10]}@cost-spine.io",
        hashed_password="x",
        full_name="Gap B Owner",
        role="admin",
    )
    session.add(owner)
    await session.flush()

    project = Project(
        id=uuid.uuid4(),
        name="Gap B project",
        owner_id=owner.id,
        currency=currency,
        fx_rates=fx_rates or [],
    )
    session.add(project)
    await session.flush()
    return project.id


async def _seed_cost_line(session: AsyncSession, project_id: uuid.UUID) -> CostLine:
    """Insert a cost line (with a control account) for the project."""
    account = ControlAccount(
        project_id=project_id,
        code=f"330-{uuid.uuid4().hex[:6]}",
        name="Baukonstruktion",
        classification_standard="din276",
    )
    session.add(account)
    await session.flush()
    line = CostLine(
        project_id=project_id,
        control_account_id=account.id,
        code=f"CL-{uuid.uuid4().hex[:8].upper()}",
        description="RC wall",
        unit="m3",
        source="manual",
        estimate_amount="1000.00",
        currency="EUR",
    )
    session.add(line)
    await session.flush()
    return line


# ── Case 1: new row ───────────────────────────────────────────────────────────


async def test_post_actual_new_row(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    svc = CostSpineService(session)

    line = await svc.post_actual_to_budget_line(
        project_id=project_id,
        cost_line_id=None,
        cost_category="material",
        amount_base="1500.00",
        currency="EUR",
        source_kind="invoice_paid",
        source_ref="inv-1:item-1",
        idempotency_key="k1",
    )

    assert Decimal(line.actual_amount) == Decimal("1500.00")
    assert line.category == "material"
    assert line.currency == "EUR"
    # Exactly one budget line exists.
    rows = (await session.execute(select(BudgetLine).where(BudgetLine.project_id == project_id))).scalars().all()
    assert len(rows) == 1


# ── Case 2: increment existing (same triple, different ref) ────────────────────


async def test_post_actual_increment_existing(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    svc = CostSpineService(session)

    await svc.post_actual_to_budget_line(
        project_id=project_id,
        cost_line_id=None,
        cost_category="labor",
        amount_base="100.00",
        currency="EUR",
        source_kind="invoice_paid",
        source_ref="ref-A",
        idempotency_key="kA",
    )
    line = await svc.post_actual_to_budget_line(
        project_id=project_id,
        cost_line_id=None,
        cost_category="labor",
        amount_base="250.00",
        currency="EUR",
        source_kind="invoice_paid",
        source_ref="ref-B",
        idempotency_key="kB",
    )

    assert Decimal(line.actual_amount) == Decimal("350.00")
    rows = (await session.execute(select(BudgetLine).where(BudgetLine.project_id == project_id))).scalars().all()
    assert len(rows) == 1  # both postings land on one row


# ── Case 3: idempotency on (source_kind, source_ref) ──────────────────────────


async def test_post_actual_idempotent_same_source_ref(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    svc = CostSpineService(session)

    await svc.post_actual_to_budget_line(
        project_id=project_id,
        cost_line_id=None,
        cost_category="material",
        amount_base="500.00",
        currency="EUR",
        source_kind="invoice_paid",
        source_ref="dup-ref",
        idempotency_key="k1",
    )
    line = await svc.post_actual_to_budget_line(
        project_id=project_id,
        cost_line_id=None,
        cost_category="material",
        amount_base="500.00",
        currency="EUR",
        source_kind="invoice_paid",
        source_ref="dup-ref",  # same ref → no-op
        idempotency_key="k1-again",
    )

    assert Decimal(line.actual_amount) == Decimal("500.00")  # not 1000
    postings = line.metadata_["postings"]
    assert len(postings) == 1


# ── Case 4: two refs both cumulate ────────────────────────────────────────────


async def test_post_actual_different_refs_cumulate(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    svc = CostSpineService(session)

    for ref, amt in (("r1", "10.00"), ("r2", "20.00"), ("r3", "30.00")):
        line = await svc.post_actual_to_budget_line(
            project_id=project_id,
            cost_line_id=None,
            cost_category="equipment",
            amount_base=amt,
            currency="EUR",
            source_kind="invoice_paid",
            source_ref=ref,
            idempotency_key=ref,
        )
    assert Decimal(line.actual_amount) == Decimal("60.00")
    assert len(line.metadata_["postings"]) == 3


# ── Case 5: invalid project ───────────────────────────────────────────────────


async def test_post_actual_invalid_project(session: AsyncSession) -> None:
    svc = CostSpineService(session)
    # A random project id has no currency configured → 400 (no base currency).
    with pytest.raises(HTTPException) as exc:
        await svc.post_actual_to_budget_line(
            project_id=uuid.uuid4(),
            cost_line_id=None,
            cost_category="material",
            amount_base="100.00",
            currency="EUR",
            source_kind="invoice_paid",
            source_ref="x",
            idempotency_key="x",
        )
    assert exc.value.status_code == 400


# ── Case 6: cost line not in project ──────────────────────────────────────────


async def test_post_actual_invalid_cost_line(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    other_project_id = await _seed_project(session)
    foreign_line = await _seed_cost_line(session, other_project_id)
    svc = CostSpineService(session)

    with pytest.raises(HTTPException) as exc:
        await svc.post_actual_to_budget_line(
            project_id=project_id,
            cost_line_id=foreign_line.id,  # belongs to another project
            cost_category="material",
            amount_base="100.00",
            currency="EUR",
            source_kind="invoice_paid",
            source_ref="x",
            idempotency_key="x",
        )
    assert exc.value.status_code == 404


# ── Case 7: unknown category ──────────────────────────────────────────────────


async def test_post_actual_invalid_category(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    svc = CostSpineService(session)

    with pytest.raises(HTTPException) as exc:
        await svc.post_actual_to_budget_line(
            project_id=project_id,
            cost_line_id=None,
            cost_category="space-tourism",  # not in the allowed set
            amount_base="100.00",
            currency="EUR",
            source_kind="invoice_paid",
            source_ref="x",
            idempotency_key="x",
        )
    assert exc.value.status_code == 400


# ── Case 8: metadata postings trail ───────────────────────────────────────────


async def test_post_actual_metadata_postings_trail(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    svc = CostSpineService(session)

    line = await svc.post_actual_to_budget_line(
        project_id=project_id,
        cost_line_id=None,
        cost_category="overhead",
        amount_base="42.50",
        currency="USD",
        source_kind="invoice_paid",
        source_ref="inv-9:item-3",
        idempotency_key="key-xyz",
    )
    postings = line.metadata_["postings"]
    assert len(postings) == 1
    entry = postings[0]
    assert entry["source_kind"] == "invoice_paid"
    assert entry["source_ref"] == "inv-9:item-3"
    assert entry["idempotency_key"] == "key-xyz"
    assert entry["amount"] == "42.50"
    assert entry["currency"] == "USD"
    assert "posted_at" in entry
    assert line.metadata_["kind"] == "actual_posting_auto"


# ── Case 9: event published ───────────────────────────────────────────────────


async def test_post_actual_event_published(session: AsyncSession, monkeypatch) -> None:
    """The method publishes ``costmodel.budget_line.actual_posted`` with the payload.

    ``_safe_publish`` is monkeypatched to capture synchronously, sidestepping the
    detached-task timing of the real bus so the assertion is deterministic.
    """
    project_id = await _seed_project(session)
    svc = CostSpineService(session)

    captured: list[tuple[str, dict]] = []

    async def _fake_publish(name: str, data: dict, source_module: str = "") -> None:
        captured.append((name, data))

    monkeypatch.setattr("app.modules.costmodel.service._safe_publish", _fake_publish)

    await svc.post_actual_to_budget_line(
        project_id=project_id,
        cost_line_id=None,
        cost_category="material",
        amount_base="77.00",
        currency="EUR",
        source_kind="invoice_paid",
        source_ref="evt-ref",
        idempotency_key="evt",
    )

    assert len(captured) == 1
    name, data = captured[0]
    assert name == "costmodel.budget_line.actual_posted"
    assert data["project_id"] == str(project_id)
    assert data["source_ref"] == "evt-ref"
    assert data["source_kind"] == "invoice_paid"
    assert data["category"] == "material"
    assert data["amount"] == "77.00"


async def test_post_actual_replay_does_not_publish(session: AsyncSession, monkeypatch) -> None:
    """A replayed (idempotent) posting must NOT re-emit the event."""
    project_id = await _seed_project(session)
    svc = CostSpineService(session)

    captured: list[tuple[str, dict]] = []

    async def _fake_publish(name: str, data: dict, source_module: str = "") -> None:
        captured.append((name, data))

    monkeypatch.setattr("app.modules.costmodel.service._safe_publish", _fake_publish)

    for _ in range(2):
        await svc.post_actual_to_budget_line(
            project_id=project_id,
            cost_line_id=None,
            cost_category="material",
            amount_base="50.00",
            currency="EUR",
            source_kind="invoice_paid",
            source_ref="same",
            idempotency_key="same",
        )
    # First posts and emits; second is a no-op and stays silent.
    assert len(captured) == 1


# ── Case 10: project without a base currency ──────────────────────────────────


async def test_post_actual_project_without_currency(session: AsyncSession) -> None:
    project_id = await _seed_project(session, currency="")
    svc = CostSpineService(session)

    with pytest.raises(HTTPException) as exc:
        await svc.post_actual_to_budget_line(
            project_id=project_id,
            cost_line_id=None,
            cost_category="material",
            amount_base="100.00",
            currency="EUR",
            source_kind="invoice_paid",
            source_ref="x",
            idempotency_key="x",
        )
    assert exc.value.status_code == 400


# ── Extra: posting onto a cost line carries the link + account ────────────────


async def test_post_actual_links_cost_line_and_account(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    cost_line = await _seed_cost_line(session, project_id)
    account_id = cost_line.control_account_id
    svc = CostSpineService(session)

    line = await svc.post_actual_to_budget_line(
        project_id=project_id,
        cost_line_id=cost_line.id,
        cost_category="material",
        amount_base="900.00",
        currency="EUR",
        source_kind="invoice_paid",
        source_ref="cl-ref",
        idempotency_key="cl",
    )
    assert line.cost_line_id == cost_line.id
    assert line.control_account_id == account_id
    assert Decimal(line.actual_amount) == Decimal("900.00")


# ── Extra: None category lands on one stable "uncategorised" row ──────────────


async def test_post_actual_none_category_single_row(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    svc = CostSpineService(session)

    await svc.post_actual_to_budget_line(
        project_id=project_id,
        cost_line_id=None,
        cost_category=None,
        amount_base="100.00",
        currency="EUR",
        source_kind="invoice_paid",
        source_ref="u1",
        idempotency_key="u1",
    )
    line = await svc.post_actual_to_budget_line(
        project_id=project_id,
        cost_line_id=None,
        cost_category=None,
        amount_base="200.00",
        currency="EUR",
        source_kind="invoice_paid",
        source_ref="u2",
        idempotency_key="u2",
    )
    assert Decimal(line.actual_amount) == Decimal("300.00")
    assert line.category == ""
    rows = (await session.execute(select(BudgetLine).where(BudgetLine.project_id == project_id))).scalars().all()
    assert len(rows) == 1


# ── Extra: lost-update fix — two sequential postings sum correctly ────────────


async def test_post_actual_two_postings_sum_under_row_lock(session: AsyncSession) -> None:
    """Two distinct postings from different sources land on the same row and sum.

    Regression guard for the lost-update race (audit finding #7). Different
    sources (an invoice payment and a labour event) resolve to the SAME budget
    row (same project_id + cost_line_id + category) but carry distinct
    ``(source_kind, source_ref)``, so the idempotency guard does NOT dedupe
    them — both must be added. Under the fix, the existing-row branch re-fetches
    the row with ``SELECT ... FOR UPDATE`` immediately before the
    read-modify-write of the Decimal-as-string ``actual_amount``. That lock is
    held until the surrounding transaction commits, so a second poster racing on
    the same row BLOCKS until the first has written its increment and only then
    reads the now-incremented ``prior`` — serialising concurrent posters so no
    increment is silently lost. A true two-connection race cannot be exercised
    inside a single rolled-back test transaction, so this asserts the sequential
    accumulation the lock guarantees (300 + 250 = 550, never 250 or 300).
    """
    project_id = await _seed_project(session)
    svc = CostSpineService(session)

    await svc.post_actual_to_budget_line(
        project_id=project_id,
        cost_line_id=None,
        cost_category="labor",
        amount_base="300.00",
        currency="EUR",
        source_kind="invoice_paid",
        source_ref="inv-7:item-2",
        idempotency_key="inv-7",
    )
    line = await svc.post_actual_to_budget_line(
        project_id=project_id,
        cost_line_id=None,
        cost_category="labor",
        amount_base="250.00",
        currency="EUR",
        source_kind="labour_event",  # different source, same target row
        source_ref="crew-shift-9",
        idempotency_key="crew-9",
    )

    assert Decimal(line.actual_amount) == Decimal("550.00")
    # Both postings are recorded in the trail AND reflected in actual_amount —
    # the audit trail and the increment stay consistent (no phantom entry).
    assert len(line.metadata_["postings"]) == 2
    rows = (await session.execute(select(BudgetLine).where(BudgetLine.project_id == project_id))).scalars().all()
    assert len(rows) == 1


# ── Extra: the lock itself — a SELECT ... FOR UPDATE must hit the existing row ─


async def test_post_actual_existing_row_issues_for_update_lock(session: AsyncSession) -> None:
    """Pin the lock mechanism, not just the sum (audit finding #7).

    The previous test asserts the *outcome* (300 + 250 = 550) which would also
    hold on the un-fixed code in a single transaction. This one fails the moment
    someone removes ``with_for_update()``: it spies on the session and asserts the
    existing-row branch issues a ``SELECT ... FOR UPDATE`` against the BudgetLine
    row before the read-modify-write of ``actual_amount``. That row lock is what
    serialises concurrent posters so no increment is silently lost under a real
    two-connection race.
    """
    project_id = await _seed_project(session)
    svc = CostSpineService(session)

    # Seed the row so the second call takes the existing-row (locked) branch.
    await svc.post_actual_to_budget_line(
        project_id=project_id,
        cost_line_id=None,
        cost_category="labor",
        amount_base="300.00",
        currency="EUR",
        source_kind="invoice_paid",
        source_ref="inv-7",
        idempotency_key="inv-7",
    )

    captured: list[object] = []
    original_execute = svc.session.execute

    async def _spy(statement, *args, **kwargs):  # type: ignore[no-untyped-def]
        captured.append(statement)
        return await original_execute(statement, *args, **kwargs)

    svc.session.execute = _spy  # type: ignore[method-assign]
    try:
        await svc.post_actual_to_budget_line(
            project_id=project_id,
            cost_line_id=None,
            cost_category="labor",
            amount_base="250.00",
            currency="EUR",
            source_kind="labour_event",  # different source, same target row
            source_ref="crew-9",
            idempotency_key="crew-9",
        )
    finally:
        svc.session.execute = original_execute  # type: ignore[method-assign]

    def _is_budget_line_for_update(statement: object) -> bool:
        # ``_for_update_arg`` is set by Select.with_for_update(); None otherwise.
        if getattr(statement, "_for_update_arg", None) is None:
            return False
        return "budget" in str(statement).lower()

    assert any(_is_budget_line_for_update(s) for s in captured), (
        "post_actual_to_budget_line must SELECT ... FOR UPDATE the BudgetLine row "
        "before incrementing actual_amount (lost-update lock, finding #7)"
    )


# ── Extra: a negative posting (refund semantics) decrements the actual ────────


async def test_post_actual_negative_amount_reduces(session: AsyncSession) -> None:
    """A negative ``amount_base`` (e.g. a refund reversal) reduces the actual.

    The method is a pure accumulator: callers posting a refund pass the negative
    delta. It is NOT zeroed or rejected here — the dashboard clamps display to
    >= 0 (see design risk #6). This pins TEST MATRIX case 21 semantics at the
    spine level (the refund→actual wiring itself is a future finance pass).
    """
    project_id = await _seed_project(session)
    svc = CostSpineService(session)

    await svc.post_actual_to_budget_line(
        project_id=project_id,
        cost_line_id=None,
        cost_category="material",
        amount_base="1000.00",
        currency="EUR",
        source_kind="invoice_paid",
        source_ref="pay-1",
        idempotency_key="pay-1",
    )
    line = await svc.post_actual_to_budget_line(
        project_id=project_id,
        cost_line_id=None,
        cost_category="material",
        amount_base="-300.00",
        currency="EUR",
        source_kind="payment_refund",
        source_ref="refund-1",
        idempotency_key="refund-1",
    )
    assert Decimal(line.actual_amount) == Decimal("700.00")
