# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Budget rows written by 18.0 read the right outturn from the first boot of 18.1.

18.1 made ``committed`` the open part of each commitment and the outturn of a
budget row ``committed + actual`` (``finance.variance``). 18.0 rows still hold
the full order value in ``committed`` after the order was invoiced, so under
the new rule an order paid in full reads twice: here an order of 50 000 net
(62 500 with VAT, which is what 18.0 committed) paid in full read an outturn of
125 000 instead of 50 000.

The sync that moves a row to the new shape runs after finance writes, so a
project nobody writes to after the upgrade kept the doubled figure. The boot
repair runs it once for every project holding such a row. This builds the
project through the API, puts its rows back into the shape 18.0 left them in,
and checks the dashboard before and after the repair, then that a second pass
changes nothing.

Run:
    cd backend
    python -m pytest tests/integration/test_budget_rows_from_18_0_are_synced_at_boot.py -v
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import app.modules.boq.models  # noqa: F401
import app.modules.projects.models  # noqa: F401
import app.modules.users.models  # noqa: F401
from tests.integration.test_finance_project_cost_position import (
    _dashboard,
    _login,
    _money,
    _ok,
    _order,
    _seed_project_and_bill,
    _supplier,
)

API = "/api/v1"


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    fastapi_app = create_app()
    async with fastapi_app.router.lifespan_context(fastapi_app):
        from app.database import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield fastapi_app


@pytest_asyncio.fixture(scope="module")
async def client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _pay_the_order_in_full(
    client: AsyncClient, h: dict[str, str], project_id: uuid.UUID, vendor: str, po: dict
) -> None:
    invoice = await _ok(
        await client.post(
            f"{API}/finance/",
            json={
                "project_id": str(project_id),
                "contact_id": vendor,
                "invoice_direction": "payable",
                "invoice_number": f"R-{uuid.uuid4().hex[:6]}",
                "invoice_date": "2026-09-22",
                "due_date": "2026-10-22",
                "currency_code": "EUR",
                "amount_subtotal": "50000.00",
                "tax_amount": "12500.00",
                "amount_total": "62500.00",
                "purchase_order_id": po["id"],
                "line_items": [
                    {
                        "description": "Reinforcement B500B",
                        "quantity": "20000",
                        "unit": "kg",
                        "unit_rate": "2.50",
                        "amount": "50000.00",
                        "wbs_id": "02",
                        "vat_rate": "25",
                    }
                ],
            },
            headers=h,
        )
    )
    await _ok(await client.post(f"{API}/finance/{invoice['id']}/approve/", headers=h))
    await _ok(
        await client.post(
            f"{API}/finance/payments/",
            json={
                "invoice_id": invoice["id"],
                "payment_date": "2026-09-25",
                "amount": "62500.00",
                "currency_code": "EUR",
                "reference": "HR12 2360 0001 1023 4567 8",
            },
            headers=h,
        )
    )
    await _ok(await client.post(f"{API}/finance/{invoice['id']}/pay/", headers=h))


async def _put_rows_back_to_18_0(project_id: uuid.UUID, po_id: str) -> None:
    """The rows as 18.0 left them: no sync markers, the order's gross in committed.

    18.0 committed ``amount_total`` on approval and never took it off again for
    an invoice, and its paid-invoice recompute wrote the paid gross into
    ``actual``. Neither ``budget_sync`` nor any ``sync:`` marker existed.
    """
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.finance.models import ProjectBudget

    async with async_session_factory() as s:
        rows = (await s.execute(select(ProjectBudget).where(ProjectBudget.project_id == project_id))).scalars().all()
        for row in rows:
            if row.wbs_id == "02":
                row.committed = Decimal("62500")
                row.actual = Decimal("62500")
                row.metadata_ = {f"committed_from_po:{po_id}": "62500"}
            else:
                row.committed = Decimal("0")
                row.actual = Decimal("0")
                row.metadata_ = {}
        await s.commit()


async def _rows(client: AsyncClient, h: dict[str, str], project_id: uuid.UUID) -> tuple[Decimal, Decimal]:
    body = await _ok(await client.get(f"{API}/finance/budgets/?project_id={project_id}", headers=h))
    items = body["items"] if isinstance(body, dict) else body
    return sum(_money(r["committed"]) for r in items), sum(_money(r["actual"]) for r in items)


@pytest.mark.asyncio
async def test_an_18_0_order_paid_in_full_reads_its_net_once_after_the_boot_repair(client: AsyncClient) -> None:
    from app.core.data_repairs import run_data_repairs
    from app.database import async_session_factory
    from app.modules.finance.repairs import FINANCE_BUDGET_ROWS_18_1

    owner, h = await _login(client)
    project_id, boq_id = await _seed_project_and_bill(owner)
    await _ok(await client.post(f"{API}/boq/boqs/{boq_id}/lock/", headers=h))
    vendor = await _supplier(client, h)
    po = await _order(client, h, project_id, vendor)
    await _pay_the_order_in_full(client, h, project_id, vendor, po)

    await _put_rows_back_to_18_0(project_id, po["id"])

    # The defect, as an upgraded install saw it: 62 500 committed plus
    # 62 500 actual on one row, an outturn of 125 000 against a budget of
    # 400 000. Reading it does not repair it.
    before = await _dashboard(client, h, project_id)
    assert _money(before["total_variance"]) == Decimal("275000")
    assert await _rows(client, h, project_id) == (Decimal("62500"), Decimal("62500"))

    first = await run_data_repairs(async_session_factory, repairs=(FINANCE_BUDGET_ROWS_18_1,))
    assert [o.status for o in first.outcomes] == ["applied"]
    assert first.rows_changed >= 1

    # The order is invoiced and paid in full: nothing open, 50 000 net
    # incurred, and the rows add up to the dashboard.
    after = await _dashboard(client, h, project_id)
    assert _money(after["total_committed"]) == Decimal("0")
    assert _money(after["total_actual"]) == Decimal("50000")
    assert _money(after["total_variance"]) == Decimal("350000")
    assert await _rows(client, h, project_id) == (Decimal("0"), Decimal("50000"))

    second = await run_data_repairs(async_session_factory, repairs=(FINANCE_BUDGET_ROWS_18_1,))
    assert [(o.status, o.rows_changed) for o in second.outcomes] == [("clean", 0)]
    assert await _rows(client, h, project_id) == (Decimal("0"), Decimal("50000"))
