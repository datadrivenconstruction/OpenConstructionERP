# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠DB-backed module tests for PO retainage + reconciliation report (Gap F).

Runs against PostgreSQL via the canonical ``transactional_session`` helper:
each test gets a session inside an outer transaction that is rolled back on
teardown, so the database starts empty every time and FK clauses are enforced
for real.

Covered:
    * Model + repository round-trip of ``PORetainageRelease``.
    * End-to-end release sequence through ``ProcurementService`` (held drains
      to zero, audit log rows accumulate).
    * ``ReportingService.render_po_retainage_reconciliation`` period scoping,
      held-amount roll-up, and per-currency (never-blended) summary.

FK note: ``oe_procurement_po`` declares no outgoing foreign keys, so its
``project_id`` / ``created_by`` columns are plain identifier columns and the
rows below persist without a full project/user graph behind them. The
reconciliation report's Project/Contact lookups are best-effort (wrapped in
try/except in the service) and tolerate the missing parents. Nothing here
needs FK enforcement relaxed, and it must not be: the release log is removed
by the database's own ``ON DELETE CASCADE``, which PostgreSQL implements as
an internal referential-integrity trigger. Turning triggers off (
``session_replication_role = replica``) would silently switch that cascade
off along with them.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.modules.procurement.models  # noqa: F401  (register tables)
from app.modules.procurement.models import PORetainageRelease, PurchaseOrder
from app.modules.procurement.repository import PORetainageReleaseRepository
from app.modules.procurement.service import ProcurementService
from app.modules.reporting.service import ReportingService
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Isolated PostgreSQL session with foreign keys enforced for real.

    ``oe_procurement_po`` has no outgoing foreign keys, so the synthetic
    ``project_id`` / ``created_by`` values used below need no parent rows and
    no relaxation. Enforcement stays on because the cascade test depends on
    it: an ``ON DELETE CASCADE`` runs as an internal trigger, so a session
    with triggers disabled would never delete the release log.
    """
    async with transactional_session(disable_fks=False) as sess:
        yield sess


async def _make_po(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    po_number: str,
    amount_total: str = "100000.00",
    pct: str = "5.00",
    status: str = "issued",
    issue_date: str | None = "2026-06-05",
    currency: str = "EUR",
    released: str = "0",
) -> PurchaseOrder:
    po = PurchaseOrder(
        project_id=project_id,
        po_number=po_number,
        po_type="standard",
        issue_date=issue_date,
        currency_code=currency,
        amount_subtotal=amount_total,
        tax_amount="0",
        amount_total=amount_total,
        status=status,
        retention_percent=Decimal(pct),
        retainage_released_amount=released,
    )
    session.add(po)
    await session.flush()
    return po


# ── Model + repository round-trip ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_retainage_release_persists(session: AsyncSession) -> None:
    project_id = uuid.uuid4()
    po = await _make_po(session, project_id=project_id, po_number="PO-001")

    repo = PORetainageReleaseRepository(session)
    rec = await repo.create(
        PORetainageRelease(
            po_id=po.id,
            release_date="2026-06-10T00:00:00+00:00",
            release_amount=Decimal("1234.5600"),
            release_reason="Snag list cleared",
        )
    )
    assert rec.id is not None

    rows, total = await repo.list_for_po(po.id)
    assert total == 1
    assert rows[0].release_amount == Decimal("1234.5600")
    assert rows[0].release_reason == "Snag list cleared"


@pytest.mark.asyncio
async def test_retainage_release_cascades_on_po_delete(session: AsyncSession) -> None:
    project_id = uuid.uuid4()
    po = await _make_po(session, project_id=project_id, po_number="PO-001")
    repo = PORetainageReleaseRepository(session)
    await repo.create(
        PORetainageRelease(
            po_id=po.id,
            release_date="2026-06-10T00:00:00+00:00",
            release_amount=Decimal("100"),
        )
    )
    # ON DELETE CASCADE: deleting the PO removes its release log.
    await session.delete(po)
    await session.flush()
    remaining = (
        (await session.execute(select(PORetainageRelease).where(PORetainageRelease.po_id == po.id))).scalars().all()
    )
    assert remaining == []


# ── End-to-end release through the service ────────────────────────────────


@pytest.mark.asyncio
async def test_service_release_sequence(session: AsyncSession) -> None:
    project_id = uuid.uuid4()
    po = await _make_po(session, project_id=project_id, po_number="PO-001")  # held = 5000
    svc = ProcurementService(session)

    await svc.release_po_retainage(po.id, Decimal("2000"), reason="Phase 1")
    await svc.release_po_retainage(po.id, Decimal("3000"), reason="Phase 2")

    refreshed = await svc.get_po(po.id)
    assert refreshed.retainage_amount() == Decimal("5000.0000")
    assert refreshed.retainage_held() == Decimal("0.0000")
    assert refreshed.retainage_released_amount == "5000"

    releases, total = await svc.get_po_retainage_releases(po.id)
    assert total == 2
    # Newest first.
    assert {r.release_reason for r in releases} == {"Phase 1", "Phase 2"}


@pytest.mark.asyncio
async def test_service_release_over_held_rejected(session: AsyncSession) -> None:
    from fastapi import HTTPException

    project_id = uuid.uuid4()
    po = await _make_po(session, project_id=project_id, po_number="PO-001")  # held = 5000
    svc = ProcurementService(session)
    await svc.release_po_retainage(po.id, Decimal("4000"))
    # Remaining held is 1000; a 2000 release must 400.
    with pytest.raises(HTTPException) as exc:
        await svc.release_po_retainage(po.id, Decimal("2000"))
    assert exc.value.status_code == 400


# ── Reconciliation report ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_report_period_scoping(session: AsyncSession) -> None:
    project_id = uuid.uuid4()
    # Two POs in June, one in July; period is June.
    await _make_po(session, project_id=project_id, po_number="PO-001", issue_date="2026-06-01")
    await _make_po(session, project_id=project_id, po_number="PO-002", issue_date="2026-06-15")
    await _make_po(session, project_id=project_id, po_number="PO-003", issue_date="2026-07-01")
    # A PO with no retention is excluded even though it falls in the period.
    await _make_po(
        session,
        project_id=project_id,
        po_number="PO-004",
        issue_date="2026-06-20",
        pct="0.00",
    )

    svc = ReportingService(session)
    report = await svc.render_po_retainage_reconciliation(
        project_id=project_id,
        period_start="2026-06-01",
        period_end="2026-06-30",
    )

    numbers = sorted(row["po_number"] for row in report["po_rows"])
    assert numbers == ["PO-001", "PO-002"]
    assert report["report_type"] == "po_retainage_reconciliation"
    # 2 POs * 100000 * 5% = 10000 withheld, nothing released yet.
    assert report["summary"]["total_committed"] == "200000.00"
    assert report["summary"]["total_withheld"] == "10000.0000"
    assert report["summary"]["total_released"] == "0"
    assert report["summary"]["total_held"] == "10000.0000"
    assert report["summary"]["mixed_currency"] is False
    assert report["currencies"] == ["EUR"]


@pytest.mark.asyncio
async def test_report_reflects_release(session: AsyncSession) -> None:
    project_id = uuid.uuid4()
    po = await _make_po(session, project_id=project_id, po_number="PO-001", issue_date="2026-06-05")
    proc = ProcurementService(session)
    await proc.release_po_retainage(po.id, Decimal("1000"))

    svc = ReportingService(session)
    report = await svc.render_po_retainage_reconciliation(
        project_id=project_id,
        period_start="2026-06-01",
        period_end="2026-06-30",
    )
    row = report["po_rows"][0]
    assert row["retainage_withheld"] == "5000.0000"
    assert row["retainage_released_ytd"] == "1000"
    assert row["retainage_held"] == "4000.0000"
    assert report["summary"]["total_held"] == "4000.0000"
    assert report["summary"]["total_released"] == "1000"


@pytest.mark.asyncio
async def test_report_never_blends_currencies(session: AsyncSession) -> None:
    project_id = uuid.uuid4()
    await _make_po(
        session,
        project_id=project_id,
        po_number="PO-001",
        issue_date="2026-06-05",
        currency="EUR",
        amount_total="100000.00",
    )
    await _make_po(
        session,
        project_id=project_id,
        po_number="PO-002",
        issue_date="2026-06-06",
        currency="USD",
        amount_total="200000.00",
    )

    svc = ReportingService(session)
    report = await svc.render_po_retainage_reconciliation(
        project_id=project_id,
        period_start="2026-06-01",
        period_end="2026-06-30",
    )

    assert report["currencies"] == ["EUR", "USD"]
    assert report["summary"]["mixed_currency"] is True
    # Per-currency breakdown keeps the two currencies separate.
    assert report["summary_by_currency"]["EUR"]["total_withheld"] == "5000.0000"
    assert report["summary_by_currency"]["USD"]["total_withheld"] == "10000.0000"
    # The convenience summary carries no single currency code when mixed.
    assert report["summary"]["currency"] == ""


@pytest.mark.asyncio
async def test_report_empty_period(session: AsyncSession) -> None:
    project_id = uuid.uuid4()
    await _make_po(session, project_id=project_id, po_number="PO-001", issue_date="2026-05-01")
    svc = ReportingService(session)
    report = await svc.render_po_retainage_reconciliation(
        project_id=project_id,
        period_start="2026-06-01",
        period_end="2026-06-30",
    )
    assert report["po_rows"] == []
    assert report["summary"]["total_committed"] == "0"
    assert report["summary"]["total_held"] == "0"
    assert report["currencies"] == []
