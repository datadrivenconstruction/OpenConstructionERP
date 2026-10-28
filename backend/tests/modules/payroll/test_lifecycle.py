"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠TOP-30 #2 delta: payroll batch lifecycle (submit/post), reconcile, export.

Extends the v6.8 ``finalize_batch`` (draft -> approved) with the full
``draft -> submitted -> approved -> posted`` FSM, plus the read-only
reconciliation and CSV/JSON export the ERP handoff needs. Exercised against a
transaction-isolated PostgreSQL session (the only dialect the app runs on),
rolled back on teardown.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.finance.models import LedgerEntry
from app.modules.payroll.models import PayrollBatch, PayrollEntry
from app.modules.payroll.service import (
    _GL_LABOUR_EXPENSE_ACCOUNT,
    _GL_WAGES_PAYABLE_ACCOUNT,
    PayrollService,
)
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as sess:
        yield sess


async def _seed_project(session: AsyncSession, *, currency: str = "EUR") -> uuid.UUID:
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    owner = User(
        id=uuid.uuid4(),
        email=f"life-{uuid.uuid4().hex[:10]}@payroll.io",
        hashed_password="x",
        full_name="Lifecycle Owner",
        role="admin",
    )
    session.add(owner)
    await session.flush()

    project = Project(
        id=uuid.uuid4(),
        name="Lifecycle project",
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


async def _ledger_rows(session: AsyncSession, ref: str) -> list[LedgerEntry]:
    rows = await session.execute(select(LedgerEntry).where(LedgerEntry.transaction_ref == ref))
    return list(rows.scalars().all())


# ── submit (draft -> submitted) ───────────────────────────────────────────────


async def test_submit_draft_to_submitted(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    batch = await _seed_batch(session, project_id, entry_amounts=["400.00"])
    svc = PayrollService(session)

    actor = str(uuid.uuid4())
    result = await svc.submit_batch(batch.id, user_id=actor)
    assert result.status == "submitted"
    assert result.submitted_at is not None
    assert str(result.submitted_by) == actor


async def test_submit_idempotent(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    batch = await _seed_batch(session, project_id, status="submitted", entry_amounts=["100.00"])
    svc = PayrollService(session)
    result = await svc.submit_batch(batch.id)
    assert result.status == "submitted"


async def test_submit_wrong_status_400(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    batch = await _seed_batch(session, project_id, status="approved", entry_amounts=["100.00"])
    svc = PayrollService(session)
    with pytest.raises(HTTPException) as exc:
        await svc.submit_batch(batch.id)
    assert exc.value.status_code == 400


# ── approve accepts submitted (two-step flow) ─────────────────────────────────


async def test_approve_from_submitted(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    batch = await _seed_batch(session, project_id, status="submitted", entry_amounts=["250.00"])
    svc = PayrollService(session)
    result = await svc.finalize_batch(batch.id)
    assert result.status == "approved"
    assert result.approved_at is not None


# ── post (approved -> posted, GL journal) ─────────────────────────────────────


async def test_post_writes_balanced_ledger(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    batch = await _seed_batch(session, project_id, status="approved", entry_amounts=["400.00", "100.00"])
    svc = PayrollService(session)

    actor = str(uuid.uuid4())
    result = await svc.post_batch(batch.id, user_id=actor)
    assert result.status == "posted"
    assert result.posted_at is not None
    assert str(result.posted_by) == actor
    assert result.gl_transaction_ref == f"PAYROLL-{batch.id}"

    rows = await _ledger_rows(session, f"PAYROLL-{batch.id}")
    assert len(rows) == 2  # one debit, one credit
    debit = next(r for r in rows if r.debit_amount > 0)
    credit = next(r for r in rows if r.credit_amount > 0)
    assert debit.account_code == _GL_LABOUR_EXPENSE_ACCOUNT
    assert credit.account_code == _GL_WAGES_PAYABLE_ACCOUNT
    assert Decimal(debit.debit_amount) == Decimal("500.00")
    assert Decimal(credit.credit_amount) == Decimal("500.00")


async def test_post_requires_approved(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    batch = await _seed_batch(session, project_id, status="draft", entry_amounts=["100.00"])
    svc = PayrollService(session)
    with pytest.raises(HTTPException) as exc:
        await svc.post_batch(batch.id)
    assert exc.value.status_code == 400


async def test_post_idempotent_no_double_journal(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    batch = await _seed_batch(session, project_id, status="approved", entry_amounts=["300.00"])
    svc = PayrollService(session)
    await svc.post_batch(batch.id)
    await svc.post_batch(batch.id)  # idempotent no-op
    rows = await _ledger_rows(session, f"PAYROLL-{batch.id}")
    assert len(rows) == 2  # not 4


# ── reconcile ─────────────────────────────────────────────────────────────────


async def test_reconcile_no_source_flags_delta(session: AsyncSession) -> None:
    """A batch with entries but no live field source is fully unbalanced."""
    project_id = await _seed_project(session)
    batch = await _seed_batch(session, project_id, entry_amounts=["400.00"])
    svc = PayrollService(session)

    report = await svc.reconcile_batch(batch.id)
    assert report["balanced"] is False
    assert Decimal(report["batch_total_hours"]) == Decimal("8.00")
    assert Decimal(report["source_total_hours"]) == Decimal("0.00")
    assert Decimal(report["delta_total_hours"]) == Decimal("8.00")
    assert len(report["rows"]) == 1
    assert report["rows"][0]["matched"] is False


# ── export ────────────────────────────────────────────────────────────────────


async def test_export_rows_mirror_entries(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    batch = await _seed_batch(session, project_id, entry_amounts=["400.00", "100.00"])
    svc = PayrollService(session)

    exported_batch, rows = await svc.export_rows(batch.id)
    assert exported_batch.id == batch.id
    assert len(rows) == 2
    assert {r["amount"] for r in rows} == {"400.00", "100.00"}
    assert all(r["currency"] == "EUR" for r in rows)
    assert all(r["source"] == "fieldreport" for r in rows)
