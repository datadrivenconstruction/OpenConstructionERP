"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Gap A module tests: ``PayrollService.finalize_batch`` against PostgreSQL.

Finalize approves a draft batch and posts its labour cost onto the project's
cost-spine labour budget line via the shared
``CostSpineService.post_actual_to_budget_line`` (Gap B). These tests exercise
the real service against a transaction-isolated PostgreSQL session (the only
dialect the app runs on), rolled back on teardown via the canonical
``transactional_session`` helper.

Money is asserted with exact ``Decimal`` values: the labour actual feeds every
downstream EVM / budget rollup, so a silent drift here corrupts the 5D model.

Covers the unit slice of the TEST MATRIX:
    1  draft -> approved, labour posted to the budget line
    2  idempotent: a second finalize on an approved batch is a no-op
    3  404 when the batch is missing
    4  400 when the batch is in a non-draft, non-approved status
    5  a zero-total batch approves but posts nothing
    6  a posting failure leaves the batch in draft (safe retry)
    7  the idempotency key is deterministic (and the cost spine never
       double-posts the same batch)
    8  the finalize event is published with the posted amount
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.costmodel.models import BudgetLine
from app.modules.payroll.models import PayrollBatch, PayrollEntry
from app.modules.payroll.service import PayrollService, _finalize_idempotency_key
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Isolated PostgreSQL session per test (rolled back on teardown)."""
    async with transactional_session() as sess:
        yield sess


# ── Seed helpers ────────────────────────────────────────────────────────────


async def _seed_project(session: AsyncSession, *, currency: str = "EUR") -> uuid.UUID:
    """Insert a user + project and return the project id."""
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    owner = User(
        id=uuid.uuid4(),
        email=f"gapa-{uuid.uuid4().hex[:10]}@payroll.io",
        hashed_password="x",
        full_name="Gap A Owner",
        role="admin",
    )
    session.add(owner)
    await session.flush()

    project = Project(
        id=uuid.uuid4(),
        name="Gap A project",
        owner_id=owner.id,
        currency=currency,
        fx_rates=[],
    )
    session.add(project)
    await session.flush()
    return project.id


async def _seed_batch(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    status: str = "draft",
    currency: str = "EUR",
    entry_amounts: list[str] | None = None,
) -> PayrollBatch:
    """Create a batch (default draft) with one entry per amount in *entry_amounts*."""
    amounts = entry_amounts if entry_amounts is not None else ["400.00", "315.00"]
    total = sum((Decimal(a) for a in amounts), Decimal("0")).quantize(Decimal("0.01"))

    batch = PayrollBatch(
        project_id=project_id,
        period_label="Week 2026-W23",
        period_start="2026-06-01",
        period_end="2026-06-07",
        status=status,
        currency=currency,
        total_hours="16.00",
        total_amount=str(total),
        entry_count=len(amounts),
    )
    session.add(batch)
    await session.flush()

    for idx, amt in enumerate(amounts):
        session.add(
            PayrollEntry(
                batch_id=batch.id,
                worker=f"worker-{idx}",
                work_date="2026-06-01",
                hours="8.00",
                rate="50.0000",
                amount=amt,
                currency=currency,
                source="fieldreport",
            )
        )
    await session.flush()
    return batch


async def _budget_lines(session: AsyncSession, project_id: uuid.UUID) -> list[BudgetLine]:
    rows = await session.execute(select(BudgetLine).where(BudgetLine.project_id == project_id))
    return list(rows.scalars().all())


# ── Case 1: draft -> approved, labour posted ──────────────────────────────────


async def test_finalize_batch_success_draft_to_approved(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    batch = await _seed_batch(session, project_id, entry_amounts=["400.00", "315.00"])
    svc = PayrollService(session)

    result = await svc.finalize_batch(batch.id)

    assert result.status == "approved"
    lines = await _budget_lines(session, project_id)
    assert len(lines) == 1
    line = lines[0]
    assert line.category == "labor"
    assert Decimal(line.actual_amount) == Decimal("715.00")
    # The posting carries the batch's payroll source-ref.
    postings = line.metadata_["postings"]
    assert len(postings) == 1
    assert postings[0]["source_kind"] == "payroll_batch"
    assert postings[0]["source_ref"] == str(batch.id)
    assert postings[0]["idempotency_key"] == _finalize_idempotency_key(batch.id)


# ── Case 2: idempotent on an already-approved batch ───────────────────────────


async def test_finalize_batch_idempotent_already_approved(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    batch = await _seed_batch(session, project_id, entry_amounts=["400.00"])
    svc = PayrollService(session)

    first = await svc.finalize_batch(batch.id)
    assert first.status == "approved"

    # Re-finalize: must be a no-op (no second posting, amount unchanged).
    second = await svc.finalize_batch(batch.id)
    assert second.status == "approved"

    lines = await _budget_lines(session, project_id)
    assert len(lines) == 1
    assert Decimal(lines[0].actual_amount) == Decimal("400.00")  # not 800
    assert len(lines[0].metadata_["postings"]) == 1


# ── Case 3: 404 when the batch is missing ─────────────────────────────────────


async def test_finalize_batch_not_found(session: AsyncSession) -> None:
    svc = PayrollService(session)
    with pytest.raises(HTTPException) as exc:
        await svc.finalize_batch(uuid.uuid4())
    assert exc.value.status_code == 404


# ── Case 4: 400 on a non-draft, non-approved status ───────────────────────────


async def test_finalize_batch_wrong_status(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    batch = await _seed_batch(session, project_id, status="cancelled", entry_amounts=["100.00"])
    svc = PayrollService(session)

    with pytest.raises(HTTPException) as exc:
        await svc.finalize_batch(batch.id)
    assert exc.value.status_code == 400
    # Nothing posted.
    assert await _budget_lines(session, project_id) == []


# ── Case 5: a zero-total batch approves but posts nothing ──────────────────────


async def test_finalize_batch_zero_entries(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    batch = await _seed_batch(session, project_id, entry_amounts=["0.00"])
    svc = PayrollService(session)

    result = await svc.finalize_batch(batch.id)
    assert result.status == "approved"
    # No budget line is created for a strictly-zero posting (avoids 0.00 noise).
    assert await _budget_lines(session, project_id) == []


# ── Case 6: a posting failure leaves the batch in draft ───────────────────────


async def test_finalize_batch_posting_failure(session: AsyncSession) -> None:
    """If the cost-spine posting raises, finalize must not flip status.

    A project with no base currency makes ``post_actual_to_budget_line`` raise a
    400; the batch must stay ``draft`` so the operator can fix the project and
    retry without losing the batch.
    """
    project_id = await _seed_project(session, currency="")
    # The batch still carries a currency (it was generated earlier), so finalize
    # reaches the posting call, which the currency-less project rejects.
    batch = await _seed_batch(session, project_id, currency="EUR", entry_amounts=["100.00"])
    svc = PayrollService(session)

    with pytest.raises(HTTPException) as exc:
        await svc.finalize_batch(batch.id)
    assert exc.value.status_code == 400

    await session.refresh(batch)
    assert batch.status == "draft"
    assert await _budget_lines(session, project_id) == []


# ── Case 7: idempotency key is deterministic + spine never double-posts ────────


def test_finalize_idempotency_key_deterministic() -> None:
    bid = uuid.uuid4()
    a = _finalize_idempotency_key(bid)
    b = _finalize_idempotency_key(bid)
    assert a == b
    # SHA-256 hex digest length.
    assert len(a) == 64
    # Different batches produce different keys.
    assert _finalize_idempotency_key(uuid.uuid4()) != a


async def test_finalize_does_not_double_post_same_batch(session: AsyncSession) -> None:
    """Two finalize calls on the same batch post the labour cost exactly once."""
    project_id = await _seed_project(session)
    batch = await _seed_batch(session, project_id, entry_amounts=["250.00", "250.00"])
    svc = PayrollService(session)

    await svc.finalize_batch(batch.id)
    await svc.finalize_batch(batch.id)  # idempotent no-op

    lines = await _budget_lines(session, project_id)
    assert len(lines) == 1
    assert Decimal(lines[0].actual_amount) == Decimal("500.00")
    assert len(lines[0].metadata_["postings"]) == 1


# ── Case 8: the finalize event is published with the posted amount ────────────


async def test_finalize_publishes_event(session: AsyncSession, monkeypatch) -> None:
    project_id = await _seed_project(session)
    batch = await _seed_batch(session, project_id, entry_amounts=["400.00", "100.00"])
    svc = PayrollService(session)

    captured: list[tuple[str, dict]] = []

    async def _fake_publish(name: str, data: dict, source_module: str = "oe_payroll") -> None:
        captured.append((name, data))

    monkeypatch.setattr("app.modules.payroll.service.safe_publish", _fake_publish)

    await svc.finalize_batch(batch.id)

    assert len(captured) == 1
    name, data = captured[0]
    assert name == "payroll.batch.finalized"
    assert data["project_id"] == str(project_id)
    assert data["batch_id"] == str(batch.id)
    assert data["amount"] == "500.00"
    assert data["currency"] == "EUR"
    assert data["budget_line_id"]  # a real line id


async def test_finalize_sums_live_entries_over_stale_total(session: AsyncSession) -> None:
    """Finalize sums the live entries, not a (possibly stale) denormalised total.

    A hand-edited entry amount must be the value that posts, so the budget actual
    reflects the entries an approver actually reviewed.
    """
    project_id = await _seed_project(session)
    batch = await _seed_batch(session, project_id, entry_amounts=["400.00", "100.00"])
    # Corrupt the denormalised total to prove finalize ignores it.
    batch.total_amount = "999999.00"
    await session.flush()
    svc = PayrollService(session)

    await svc.finalize_batch(batch.id)
    lines = await _budget_lines(session, project_id)
    assert len(lines) == 1
    assert Decimal(lines[0].actual_amount) == Decimal("500.00")
