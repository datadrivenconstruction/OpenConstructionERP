# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost control on a real schema: the figures, the axes, overrides, snapshots.

One project carries every case the report has to tell apart: a line let with a
change and part-certified, a line still at estimate, a line whose contract is
completed, money on a contract line with no cost line, a change order waiting
for a decision and an approved change order on no contract.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.changeorders.models import ChangeOrder
from app.modules.contracts.models import Contract, ContractLine, ProgressClaim, ProgressClaimLine
from app.modules.contracts.sov_posting import post_source_to_sov
from app.modules.costmodel.cost_control import (
    FINDING_PENDING_CHANGES,
    FINDING_STALE_SNAPSHOT,
    FINDING_UNASSIGNED,
)
from app.modules.costmodel.cost_control_forecast import ForecastDocsService
from app.modules.costmodel.cost_control_schemas import (
    AssignRequest,
    AssignTarget,
    ForecastOverrideRequest,
    SnapshotCreateRequest,
)
from app.modules.costmodel.cost_control_service import CostControlService
from app.modules.costmodel.models import BudgetLine, CostForecastOverride, CostLine
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

D = Decimal
TODAY = date(2026, 10, 17)


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session(disable_fks=True) as s:
        yield s


async def _cost_line(session: AsyncSession, project_id: uuid.UUID, code: str, estimate: str) -> CostLine:
    line = CostLine(
        project_id=project_id, code=code, description=f"KG {code}", estimate_amount=estimate, currency="EUR"
    )
    session.add(line)
    await session.flush()
    return line


async def _budget(session: AsyncSession, project_id: uuid.UUID, line: CostLine, planned: str) -> None:
    session.add(
        BudgetLine(
            project_id=project_id,
            cost_line_id=line.id,
            category="subcontractor",
            description=line.description,
            planned_amount=planned,
            currency="EUR",
        )
    )
    await session.flush()


async def _contract(session: AsyncSession, project_id: uuid.UUID, code: str, status: str) -> Contract:
    contract = Contract(
        project_id=project_id,
        code=code,
        title=f"Package {code}",
        contract_type="lump_sum",
        counterparty_type="subcontractor",
        total_value=D("0"),
        currency="EUR",
        status=status,
    )
    session.add(contract)
    await session.flush()
    return contract


async def _contract_line(
    session: AsyncSession,
    contract: Contract,
    cost_line: CostLine | None,
    total: str,
    *,
    origin: str = "original",
    original: str | None = None,
) -> ContractLine:
    line = ContractLine(
        contract_id=contract.id,
        code=f"{contract.code}-{origin}-{total}",
        description="",
        quantity=D("1"),
        unit_rate=D(total),
        total_value=D(total),
        cost_line_id=cost_line.id if cost_line else None,
        origin=origin,
        original_value=D(original) if original is not None else (D(total) if origin == "original" else D("0")),
    )
    session.add(line)
    contract.total_value = (contract.total_value or D("0")) + D(total)
    await session.flush()
    return line


async def _claim(session: AsyncSession, contract: Contract, line: ContractLine, cumulative: str, status: str) -> None:
    claim = ProgressClaim(
        contract_id=contract.id, claim_number=f"C-{uuid.uuid4().hex[:6]}", status=status, currency="EUR"
    )
    session.add(claim)
    await session.flush()
    session.add(
        ProgressClaimLine(
            progress_claim_id=claim.id,
            contract_line_id=line.id,
            cumulative_completed_value=D(cumulative),
        )
    )
    await session.flush()


@pytest_asyncio.fixture
async def project(session: AsyncSession) -> dict[str, object]:
    pid = uuid.uuid4()
    shell = await _cost_line(session, pid, "330", "110000")
    finishes = await _cost_line(session, pid, "350", "50000")
    windows = await _cost_line(session, pid, "334", "38000")
    await _budget(session, pid, shell, "100000")
    await _budget(session, pid, windows, "40000")

    k1 = await _contract(session, pid, "K1", "active")
    k1_main = await _contract_line(session, k1, shell, "95000")
    await _contract_line(session, k1, shell, "5000", origin="change_order")
    await _contract_line(session, k1, None, "7000")
    await _claim(session, k1, k1_main, "60000", "certified")

    k2 = await _contract(session, pid, "K2", "completed")
    k2_line = await _contract_line(session, k2, windows, "45000")
    await _claim(session, k2, k2_line, "43200", "paid")

    session.add(
        ChangeOrder(
            project_id=pid,
            code="CO-7",
            title="Extra fire doors",
            status="submitted",
            cost_impact=D("2500"),
            contractor_amount=D("3000"),
            currency="EUR",
            metadata_={"contract_id": str(k1.id)},
        )
    )
    session.add(
        ChangeOrder(
            project_id=pid,
            code="CO-8",
            title="Client upgrade, no contract yet",
            status="approved",
            cost_impact=D("2000"),
            approved_amount=D("2000"),
            currency="EUR",
            metadata_={},
        )
    )
    await session.flush()
    return {"pid": pid, "shell": shell, "finishes": finishes, "windows": windows, "k1": k1, "k2": k2}


def _row(report, key: str):  # noqa: ANN001, ANN202
    return next(r for r in report.rows if r.key == key)


async def test_cost_line_axis_takes_each_line_from_its_most_mature_stage(
    session: AsyncSession, project: dict[str, object]
) -> None:
    service = CostControlService(session)
    report = await service.report(project["pid"], today=TODAY)  # type: ignore[arg-type]

    shell = _row(report, str(project["shell"].id))  # type: ignore[attr-defined]
    assert (shell.planned, shell.awarded, shell.changes, shell.committed) == (
        D("100000"),
        D("95000"),
        D("5000"),
        D("100000"),
    )
    assert (shell.certified, shell.forecast, shell.forecast_source) == (D("60000"), D("100000"), "awarded")

    finishes = _row(report, str(project["finishes"].id))  # type: ignore[attr-defined]
    assert (finishes.planned, finishes.forecast, finishes.forecast_source) == (D("50000"), D("50000"), "estimate")

    windows = _row(report, str(project["windows"].id))  # type: ignore[attr-defined]
    assert (windows.forecast, windows.forecast_source, windows.paid) == (D("43200"), "final", D("43200"))
    assert windows.variance == D("3200")

    unassigned = _row(report, "unassigned")
    assert (unassigned.kind, unassigned.committed, unassigned.forecast) == ("unassigned", D("7000"), D("7000"))
    loose = _row(report, "changes_without_contract")
    assert (loose.changes, loose.forecast, loose.description) == (D("2000"), D("2000"), "1")

    # 100 000 + 50 000 + 43 200 + 7 000 + 2 000
    assert D(report.totals["forecast"]) == D("202200")
    assert D(report.totals["pending_changes"]) == D("3000")
    assert D(report.totals["forecast_with_pending"]) == D("205200")

    rules = {f.rule_id for f in report.findings}
    assert {FINDING_UNASSIGNED, FINDING_PENDING_CHANGES, FINDING_STALE_SNAPSHOT} <= rules
    # The completed windows package came in above its budget.
    over = [f for f in report.findings if f.rule_id == "cost_control.forecast_over_plan"]
    assert [f.code for f in over] == ["334"]


async def test_contract_axis_adds_up_to_the_same_commitment(session: AsyncSession, project: dict[str, object]) -> None:
    service = CostControlService(session)
    by_line = await service.report(project["pid"], today=TODAY)  # type: ignore[arg-type]
    by_contract = await service.report(project["pid"], axis="contract", today=TODAY)  # type: ignore[arg-type]

    k1 = _row(by_contract, str(project["k1"].id))  # type: ignore[attr-defined]
    assert (k1.awarded, k1.changes, k1.committed, k1.pending_changes) == (
        D("102000"),
        D("5000"),
        D("107000"),
        D("3000"),
    )
    k2 = _row(by_contract, str(project["k2"].id))  # type: ignore[attr-defined]
    assert (k2.forecast_source, k2.forecast) == ("final", D("43200"))

    assert D(by_contract.totals["committed"]) == D(by_line.totals["committed"])
    assert D(by_contract.totals["certified"]) == D(by_line.totals["certified"])


async def test_manual_forecast_needs_a_reason_and_leaves_a_history(
    session: AsyncSession, project: dict[str, object]
) -> None:
    service = CostControlService(session)
    finishes: CostLine = project["finishes"]  # type: ignore[assignment]

    with pytest.raises(ValueError, match="reason"):
        ForecastOverrideRequest(amount=D("55000"), reason="  ")

    first = await service.set_override(
        finishes, ForecastOverrideRequest(amount=D("55000"), reason="Tiles quote above estimate"), "u1"
    )
    await service.set_override(
        finishes,
        ForecastOverrideRequest(amount=D("52000"), reason="Second quote", document_ref="Offer 2026-10-12"),
        "u1",
    )
    report = await service.report(project["pid"], today=TODAY)  # type: ignore[arg-type]
    row = _row(report, str(finishes.id))
    assert (row.forecast, row.forecast_source) == (D("52000"), "manual")
    assert (row.automatic_forecast, row.automatic_source) == (D("50000"), "estimate")
    assert row.override is not None and row.override.document_ref == "Offer 2026-10-12"

    history = await service.line_history(finishes)
    assert [o.amount for o in history.overrides] == [D("55000"), D("52000")]
    assert history.overrides[0].id == first.id and history.overrides[0].closed_at is not None
    assert history.overrides[1].closed_at is None

    await service.clear_override(finishes, "u1")
    report = await service.report(project["pid"], today=TODAY)  # type: ignore[arg-type]
    assert _row(report, str(finishes.id)).forecast_source == "estimate"
    with pytest.raises(HTTPException) as exc:
        await service.clear_override(finishes, "u1")
    assert exc.value.status_code == 404


async def test_snapshot_freezes_the_report_and_feeds_the_line_history(
    session: AsyncSession, project: dict[str, object]
) -> None:
    service = CostControlService(session)
    with pytest.raises(ValueError, match="stage"):
        SnapshotCreateRequest(stage="kostenanschlag")

    snap = await service.create_snapshot(
        project["pid"],  # type: ignore[arg-type]
        SnapshotCreateRequest(stage="award", label="After award of the shell"),
        "u1",
    )
    assert snap.stage == "award"
    assert D(snap.totals["forecast"]) == D("202200")

    listed = await service.list_snapshots(project["pid"])  # type: ignore[arg-type]
    assert [s.id for s in listed.items] == [snap.id] and listed.total == 1
    _, detail = await service.get_snapshot(snap.id)
    shell_row = next(r for r in detail.rows if r["code"] == "330")
    assert (shell_row["forecast"], shell_row["source"]) == ("100000.00", "awarded")

    # A new snapshot is a draft: the history and the stale check only read frozen ones.
    assert snap.status == "draft"
    assert (await service.line_history(project["shell"])).snapshots == []  # type: ignore[arg-type]
    docs = ForecastDocsService(session)
    frozen = await docs.freeze(await docs.snapshot(snap.id), "u1")
    assert frozen.status == "frozen"

    history = await service.line_history(project["shell"])  # type: ignore[arg-type]
    assert [(p.stage, p.forecast) for p in history.snapshots] == [("award", D("100000"))]

    report = await service.report(project["pid"])  # type: ignore[arg-type]
    assert report.last_snapshot is not None and report.last_snapshot.id == snap.id
    assert FINDING_STALE_SNAPSHOT not in {f.rule_id for f in report.findings}


async def test_a_pooled_change_line_inherits_the_contracts_only_cost_line(
    session: AsyncSession, project: dict[str, object]
) -> None:
    """A change on a one-cost-line contract lands on that cost line, not on "no cost line"."""
    pid = project["pid"]
    roof = await _cost_line(session, pid, "360", "30000")  # type: ignore[arg-type]
    k3 = await _contract(session, pid, "K3", "active")  # type: ignore[arg-type]
    await _contract_line(session, k3, roof, "28000")

    adjustments = await post_source_to_sov(
        session,
        k3,
        key=f"change_order:{uuid.uuid4()}",
        kind="change_order",
        source_id=None,
        code="CO-9",
        title="Extra flashing",
        amount=D("1500"),
        currency="EUR",
        approved_on=TODAY,
    )
    assert adjustments, "the change should have been posted"
    added = await session.get(ContractLine, adjustments[0].contract_line_id)
    assert added is not None and added.cost_line_id == roof.id

    report = await CostControlService(session).report(pid, today=TODAY)  # type: ignore[arg-type]
    row = _row(report, str(roof.id))
    assert (row.awarded, row.changes) == (D("28000"), D("1500"))
    history = await CostControlService(session).line_history(roof)
    assert [(c.source_code, c.amount) for c in history.changes] == [("CO-9", D("1500"))]


async def test_both_axes_show_the_same_plan_and_forecast(session: AsyncSession, project: dict[str, object]) -> None:
    """Switching the axis must not change the project's figures, and the contract rows add up to them."""
    service = CostControlService(session)
    by_line = await service.report(project["pid"], today=TODAY)  # type: ignore[arg-type]
    by_contract = await service.report(project["pid"], axis="contract", today=TODAY)  # type: ignore[arg-type]

    for name in ("planned", "forecast", "variance", "committed", "certified", "paid"):
        assert D(by_contract.totals[name]) == D(by_line.totals[name]), name
    assert sum((r.forecast for r in by_contract.rows), D("0")) == D(by_contract.totals["forecast"])
    # The finishes line has no contract yet: its 50 000 sits on the remaining row.
    remaining = _row(by_contract, "remaining")
    assert remaining.kind == "remaining" and remaining.forecast == D("50000")


async def test_a_change_order_some_contract_carries_is_not_a_loose_change(
    session: AsyncSession, project: dict[str, object]
) -> None:
    """Applied to a contract directly or through the variation it mirrors: counted on the contract, once."""
    k1: Contract = project["k1"]  # type: ignore[assignment]
    applied = ChangeOrder(
        project_id=project["pid"],
        code="CO-10",
        title="Applied to K1",
        status="approved",
        cost_impact=D("4000"),
        approved_amount=D("4000"),
        currency="EUR",
        metadata_={},
    )
    variation_id = uuid.uuid4()
    mirror = ChangeOrder(
        project_id=project["pid"],
        code="CO-11",
        title="Mirror of a variation",
        status="executed",
        cost_impact=D("6000"),
        approved_amount=D("6000"),
        currency="EUR",
        metadata_={"variation_order_id": str(variation_id)},
    )
    session.add_all([applied, mirror])
    await session.flush()
    k1.metadata_ = {"change_order_ids": [str(applied.id)], "variation_ids": [str(variation_id)]}
    await session.flush()

    report = await CostControlService(session).report(project["pid"], today=TODAY)  # type: ignore[arg-type]
    loose = _row(report, "changes_without_contract")
    # Only CO-8 of the fixture is on no contract.
    assert (loose.changes, loose.description) == (D("2000"), "1")


async def test_an_order_on_a_completed_line_keeps_the_line_open(
    session: AsyncSession, project: dict[str, object]
) -> None:
    """A completed subcontract plus an issued order: the order's money stays in the forecast."""
    from app.modules.procurement.models import PurchaseOrder, PurchaseOrderItem

    windows: CostLine = project["windows"]  # type: ignore[assignment]
    po = PurchaseOrder(
        project_id=project["pid"], po_number="PO-1", currency_code="EUR", status="issued", amount_total="5000"
    )
    po.metadata_ = {}
    session.add(po)
    await session.flush()
    session.add(
        PurchaseOrderItem(
            po_id=po.id, description="Sills", quantity="1", unit_rate="5000", amount="5000", cost_line_id=windows.id
        )
    )
    await session.flush()

    report = await CostControlService(session).report(project["pid"], today=TODAY)  # type: ignore[arg-type]
    row = _row(report, str(windows.id))
    assert row.committed == D("50000")
    assert (row.forecast, row.forecast_source) == (D("50000"), "awarded")


async def test_paid_leaves_out_the_retention_still_held(session: AsyncSession, project: dict[str, object]) -> None:
    pid = project["pid"]
    roof = await _cost_line(session, pid, "360", "20000")  # type: ignore[arg-type]
    k4 = await _contract(session, pid, "K4", "active")  # type: ignore[arg-type]
    line = await _contract_line(session, k4, roof, "20000")
    claim = ProgressClaim(
        contract_id=k4.id,
        claim_number="C-R",
        status="paid",
        currency="EUR",
        completed_stored_to_date=D("10000"),
        retention_held_to_date=D("500"),
    )
    session.add(claim)
    await session.flush()
    session.add(
        ProgressClaimLine(progress_claim_id=claim.id, contract_line_id=line.id, cumulative_completed_value=D("10000"))
    )
    await session.flush()

    report = await CostControlService(session).report(pid, today=TODAY)  # type: ignore[arg-type]
    row = _row(report, str(roof.id))
    assert (row.certified, row.paid) == (D("10000"), D("9500"))


async def test_a_line_holds_one_open_manual_forecast_at_most(session: AsyncSession, project: dict[str, object]) -> None:
    """The database refuses a second open forecast on a line, whatever writes it."""
    finishes: CostLine = project["finishes"]  # type: ignore[assignment]
    for amount in ("51000", "52000"):
        session.add(
            CostForecastOverride(project_id=project["pid"], cost_line_id=finishes.id, amount=D(amount), reason="Quote")
        )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_unassigned_money_is_listed_line_by_line_and_can_be_put_on_a_cost_line(
    session: AsyncSession, project: dict[str, object]
) -> None:
    service = CostControlService(session)
    k1: Contract = project["k1"]  # type: ignore[assignment]
    await _contract_line(session, k1, None, "3000")
    page = await service.unassigned(project["pid"])  # type: ignore[arg-type]
    assert page.total == 2
    assert sorted(i.amount for i in page.items) == [D("3000"), D("7000")]
    item = page.items[0]
    assert (item.kind, item.group_code) == ("contract_line", "K1")

    finishes: CostLine = project["finishes"]  # type: ignore[assignment]
    result = await service.assign(
        project["pid"],  # type: ignore[arg-type]
        AssignRequest(cost_line_id=finishes.id, items=[AssignTarget(kind=i.kind, id=i.id) for i in page.items]),
    )
    assert result.assigned == 2

    report = await service.report(project["pid"], today=TODAY)  # type: ignore[arg-type]
    assert "unassigned" not in {r.key for r in report.rows}
    row = _row(report, str(finishes.id))
    # 10 000 of a 50 000 plan is let: the plan stays the forecast until more is.
    assert (row.awarded, row.forecast, row.forecast_source) == (D("10000"), D("50000"), "partly_awarded")
    assert FINDING_UNASSIGNED not in {f.rule_id for f in report.findings}
    assert (await service.unassigned(project["pid"])).total == 0  # type: ignore[arg-type]

    # A cost line of another project is refused.
    with pytest.raises(HTTPException) as exc:
        await service.assign(
            uuid.uuid4(), AssignRequest(cost_line_id=finishes.id, items=[AssignTarget(kind=item.kind, id=item.id)])
        )
    assert exc.value.status_code == 404
