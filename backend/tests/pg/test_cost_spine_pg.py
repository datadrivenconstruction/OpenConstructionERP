"""Cost Spine on real PostgreSQL (PG lane only).

Runs against the embedded PostgreSQL 16 cluster (``OE_TEST_DB=pg``) via the
``pg_session`` savepoint-isolated fixture. Guards the two things the SQLite
suite cannot:

* JSONB round-trip of the ``metadata`` blobs on control accounts / cost lines
  AND the ``cost_line_ids`` JSON array on ``oe_rfq_rfq`` (asyncpg + JSONB).
* The four grouped rollup aggregates in ``CostSpineRepository``
  (budget / po / contract / claimed) producing correct FX-converted Decimals
  off real grouped SQL, including a foreign-currency line converted through the
  project ``fx_rates``.

Money is asserted with exact ``Decimal`` values.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

pytestmark = pytest.mark.asyncio


# ── Seed helpers ────────────────────────────────────────────────────────────


async def _seed_project(pg_session, *, currency: str = "EUR", fx_rates: list | None = None) -> uuid.UUID:
    """Insert a project with optional fx_rates and return its id."""
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    owner = User(
        id=uuid.uuid4(),
        email=f"pg-spine-{uuid.uuid4().hex[:8]}@cost-spine.io",
        hashed_password="x",
        full_name="PG Spine Owner",
        role="admin",
    )
    pg_session.add(owner)
    await pg_session.flush()

    project = Project(
        id=uuid.uuid4(),
        name="PG Cost Spine",
        owner_id=owner.id,
        currency=currency,
        fx_rates=fx_rates or [],
    )
    pg_session.add(project)
    await pg_session.flush()
    return project.id


# ── JSONB round-trip ────────────────────────────────────────────────────────


async def test_control_account_jsonb_metadata_round_trips(pg_session) -> None:
    """ControlAccount.metadata_ (JSONB on PG) survives a write/read cycle."""
    from app.modules.costmodel.models import ControlAccount
    from app.modules.costmodel.repository import ControlAccountRepository

    project_id = await _seed_project(pg_session)
    blob = {"din276": "330", "nested": {"k": [1, 2, 3], "flag": True}, "label": "Baukonstruktion"}
    acct = ControlAccount(
        project_id=project_id,
        code="330",
        name="Baukonstruktion",
        classification_standard="din276",
        metadata_=blob,
    )
    pg_session.add(acct)
    await pg_session.flush()
    pg_session.expunge_all()

    repo = ControlAccountRepository(pg_session)
    fetched = await repo.get_by_id(acct.id)
    assert fetched is not None
    assert fetched.metadata_ == blob
    assert fetched.metadata_["nested"]["k"] == [1, 2, 3]
    assert fetched.metadata_["nested"]["flag"] is True


async def test_cost_line_jsonb_metadata_round_trips(pg_session) -> None:
    """CostLine.metadata_ (JSONB on PG) survives a write/read cycle."""
    from app.modules.costmodel.models import CostLine
    from app.modules.costmodel.repository import CostLineRepository

    project_id = await _seed_project(pg_session)
    blob = {"origin": "boq", "tags": ["rc", "wall"], "qty_source": {"model": "abc", "field": "volume_m3"}}
    line = CostLine(
        project_id=project_id,
        code="CL-PG-1",
        description="RC wall",
        unit="m3",
        source="boq",
        estimate_amount="1000.00",
        currency="EUR",
        metadata_=blob,
    )
    pg_session.add(line)
    await pg_session.flush()
    pg_session.expunge_all()

    repo = CostLineRepository(pg_session)
    fetched = await repo.get_by_id(line.id)
    assert fetched is not None
    assert fetched.metadata_ == blob
    assert fetched.metadata_["tags"] == ["rc", "wall"]


async def test_rfq_cost_line_ids_json_array_round_trips(pg_session) -> None:
    """oe_rfq_rfq.cost_line_ids (JSON array) round-trips a list of UUID strings."""
    from app.modules.rfq_bidding.models import RFQ

    project_id = await _seed_project(pg_session)
    ids = [str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())]
    rfq = RFQ(
        project_id=project_id,
        rfq_number=f"RFQ-{uuid.uuid4().hex[:6]}",
        title="Concrete package",
        currency_code="EUR",
        cost_line_ids=ids,
    )
    pg_session.add(rfq)
    await pg_session.flush()
    pg_session.expunge_all()

    fetched = await pg_session.get(RFQ, rfq.id)
    assert fetched is not None
    assert fetched.cost_line_ids == ids
    assert isinstance(fetched.cost_line_ids, list)
    assert len(fetched.cost_line_ids) == 3


async def test_rfq_cost_line_ids_default_empty_list(pg_session) -> None:
    """A new RFQ with no cost_line_ids defaults to an empty JSON array (NOT NULL)."""
    from app.modules.rfq_bidding.models import RFQ

    project_id = await _seed_project(pg_session)
    rfq = RFQ(
        project_id=project_id,
        rfq_number=f"RFQ-{uuid.uuid4().hex[:6]}",
        title="Empty links",
        currency_code="EUR",
    )
    pg_session.add(rfq)
    await pg_session.flush()
    pg_session.expunge_all()

    fetched = await pg_session.get(RFQ, rfq.id)
    assert fetched is not None
    assert fetched.cost_line_ids == []


# ── Grouped rollup aggregates with FX conversion ────────────────────────────


async def test_budget_aggregate_by_cost_line_fx_converted(pg_session) -> None:
    """budget_aggregate_by_cost_line sums planned/committed/actual, FX-converted.

    Two budget lines on ONE cost line: one in base EUR, one in USD with a
    configured 0.90 EUR/USD rate. The aggregate must convert the USD line to
    EUR before summing.
    """
    from app.modules.costmodel.models import BudgetLine, CostLine
    from app.modules.costmodel.repository import CostSpineRepository

    project_id = await _seed_project(pg_session, currency="EUR", fx_rates=[{"code": "USD", "rate": "0.90"}])
    line = CostLine(project_id=project_id, code="CL-FX", currency="EUR", estimate_amount="0")
    pg_session.add(line)
    await pg_session.flush()

    pg_session.add_all(
        [
            BudgetLine(
                project_id=project_id,
                cost_line_id=line.id,
                category="material",
                planned_amount="1000",
                committed_amount="400",
                actual_amount="200",
                currency="EUR",
            ),
            BudgetLine(
                project_id=project_id,
                cost_line_id=line.id,
                category="labor",
                planned_amount="1000",  # 1000 USD -> 900 EUR at 0.90
                committed_amount="100",  # 100 USD -> 90 EUR
                actual_amount="0",
                currency="USD",
            ),
        ]
    )
    await pg_session.flush()

    repo = CostSpineRepository(pg_session)
    agg = await repo.budget_aggregate_by_cost_line(project_id)
    bucket = agg[str(line.id)]
    # planned = 1000 EUR + (1000 USD * 0.90) = 1900 EUR
    assert bucket["planned"] == Decimal("1900.00")
    # committed = 400 EUR + (100 USD * 0.90) = 490 EUR
    assert bucket["committed"] == Decimal("490.00")
    # actual = 200 EUR + 0 = 200 EUR
    assert bucket["actual"] == Decimal("200")


async def test_po_committed_by_cost_line_only_committed_statuses(pg_session) -> None:
    """po_committed_by_cost_line counts only committed POs, FX-converted by PO ccy."""
    from app.modules.costmodel.models import CostLine
    from app.modules.costmodel.repository import CostSpineRepository
    from app.modules.procurement.models import PurchaseOrder, PurchaseOrderItem

    project_id = await _seed_project(pg_session, currency="EUR", fx_rates=[{"code": "USD", "rate": "0.90"}])
    line = CostLine(project_id=project_id, code="CL-PO", currency="EUR", estimate_amount="0")
    pg_session.add(line)
    await pg_session.flush()

    # Issued EUR PO (counts), issued USD PO (counts, converted), draft PO (ignored).
    po_eur = PurchaseOrder(project_id=project_id, po_number="PO-E", currency_code="EUR", status="issued")
    po_usd = PurchaseOrder(project_id=project_id, po_number="PO-U", currency_code="USD", status="completed")
    po_draft = PurchaseOrder(project_id=project_id, po_number="PO-D", currency_code="EUR", status="draft")
    pg_session.add_all([po_eur, po_usd, po_draft])
    await pg_session.flush()

    pg_session.add_all(
        [
            PurchaseOrderItem(po_id=po_eur.id, description="a", amount="300", cost_line_id=line.id),
            PurchaseOrderItem(po_id=po_usd.id, description="b", amount="1000", cost_line_id=line.id),  # ->900 EUR
            PurchaseOrderItem(po_id=po_draft.id, description="c", amount="999", cost_line_id=line.id),  # ignored
        ]
    )
    await pg_session.flush()

    repo = CostSpineRepository(pg_session)
    out = await repo.po_committed_by_cost_line(project_id)
    # 300 EUR + (1000 USD * 0.90) = 1200 EUR; draft excluded.
    assert out[str(line.id)] == Decimal("1200.00")


async def test_contract_value_by_cost_line_fx_converted(pg_session) -> None:
    """contract_value_by_cost_line sums linked ContractLine totals, FX-converted."""
    from app.modules.contracts.models import Contract, ContractLine
    from app.modules.costmodel.models import CostLine
    from app.modules.costmodel.repository import CostSpineRepository

    project_id = await _seed_project(pg_session, currency="EUR", fx_rates=[{"code": "USD", "rate": "0.90"}])
    line = CostLine(project_id=project_id, code="CL-CT", currency="EUR", estimate_amount="0")
    pg_session.add(line)
    await pg_session.flush()

    c_eur = Contract(
        code=f"C-E-{uuid.uuid4().hex[:5]}",
        title="EUR",
        project_id=project_id,
        total_value=Decimal("0"),
        currency="EUR",
        status="active",
    )
    c_usd = Contract(
        code=f"C-U-{uuid.uuid4().hex[:5]}",
        title="USD",
        project_id=project_id,
        total_value=Decimal("0"),
        currency="USD",
        status="active",
    )
    pg_session.add_all([c_eur, c_usd])
    await pg_session.flush()

    pg_session.add_all(
        [
            ContractLine(
                contract_id=c_eur.id,
                code="L1",
                description="x",
                unit="m3",
                quantity=Decimal("1"),
                unit_rate=Decimal("500"),
                total_value=Decimal("500"),
                cost_line_id=line.id,
            ),
            ContractLine(
                contract_id=c_usd.id,
                code="L2",
                description="y",
                unit="m3",
                quantity=Decimal("1"),
                unit_rate=Decimal("1000"),
                total_value=Decimal("1000"),  # ->900 EUR
                cost_line_id=line.id,
            ),
        ]
    )
    await pg_session.flush()

    repo = CostSpineRepository(pg_session)
    out = await repo.contract_value_by_cost_line(project_id)
    # 500 EUR + (1000 USD * 0.90) = 1400 EUR
    assert out[str(line.id)] == Decimal("1400.00")


async def test_claimed_to_date_by_cost_line_takes_latest_cumulative(pg_session) -> None:
    """claimed_to_date_by_cost_line takes the MAX cumulative per contract line, FX-converted.

    Two progress-claim lines on the SAME contract line (interim then later
    claim): the running ``cumulative_completed_value`` already nets the prior
    claim, so the aggregate must take the MAX, not the sum.
    """
    from app.modules.contracts.models import (
        Contract,
        ContractLine,
        ProgressClaim,
        ProgressClaimLine,
    )
    from app.modules.costmodel.models import CostLine
    from app.modules.costmodel.repository import CostSpineRepository

    project_id = await _seed_project(pg_session, currency="EUR", fx_rates=[{"code": "USD", "rate": "0.90"}])
    line = CostLine(project_id=project_id, code="CL-CLAIM", currency="EUR", estimate_amount="0")
    pg_session.add(line)
    await pg_session.flush()

    contract = Contract(
        code=f"C-CLAIM-{uuid.uuid4().hex[:5]}",
        title="claims",
        project_id=project_id,
        total_value=Decimal("0"),
        currency="USD",
        status="active",
    )
    pg_session.add(contract)
    await pg_session.flush()

    cl = ContractLine(
        contract_id=contract.id,
        code="L1",
        description="x",
        unit="m3",
        quantity=Decimal("1"),
        unit_rate=Decimal("2000"),
        total_value=Decimal("2000"),
        cost_line_id=line.id,
    )
    pg_session.add(cl)
    await pg_session.flush()

    claim1 = ProgressClaim(
        contract_id=contract.id,
        claim_number="1",
        status="approved",
        currency="USD",
    )
    claim2 = ProgressClaim(
        contract_id=contract.id,
        claim_number="2",
        status="approved",
        currency="USD",
    )
    pg_session.add_all([claim1, claim2])
    await pg_session.flush()

    pg_session.add_all(
        [
            ProgressClaimLine(
                progress_claim_id=claim1.id,
                contract_line_id=cl.id,
                period_completed_value=Decimal("500"),
                cumulative_completed_value=Decimal("500"),  # interim
            ),
            ProgressClaimLine(
                progress_claim_id=claim2.id,
                contract_line_id=cl.id,
                period_completed_value=Decimal("500"),
                cumulative_completed_value=Decimal("1000"),  # running total = 1000 USD
            ),
        ]
    )
    await pg_session.flush()

    repo = CostSpineRepository(pg_session)
    out = await repo.claimed_to_date_by_cost_line(project_id)
    # MAX cumulative = 1000 USD -> * 0.90 = 900 EUR (NOT 500+1000=1500).
    assert out[str(line.id)] == Decimal("900.00")


async def test_missing_fx_rate_keeps_foreign_units_not_zeroed(pg_session) -> None:
    """A foreign line with NO configured fx rate is kept in its own units, never zeroed.

    This is the deliberate degrade-visibly behaviour: a forgotten rate surfaces
    as an obviously-wrong total rather than silently dropping money.
    """
    from app.modules.costmodel.models import BudgetLine, CostLine
    from app.modules.costmodel.repository import CostSpineRepository

    # Project base EUR, NO fx_rates configured at all.
    project_id = await _seed_project(pg_session, currency="EUR", fx_rates=[])
    line = CostLine(project_id=project_id, code="CL-NOFX", currency="EUR", estimate_amount="0")
    pg_session.add(line)
    await pg_session.flush()

    pg_session.add(
        BudgetLine(
            project_id=project_id,
            cost_line_id=line.id,
            category="material",
            planned_amount="750",
            currency="JPY",  # no rate -> kept as 750, not zeroed
        )
    )
    await pg_session.flush()

    repo = CostSpineRepository(pg_session)
    agg = await repo.budget_aggregate_by_cost_line(project_id)
    assert agg[str(line.id)]["planned"] == Decimal("750")


# ── Idempotency of generate_from_boq on real PostgreSQL ─────────────────────


async def _seed_boq_with_unreferenced_positions(pg_session, project_id: uuid.UUID) -> uuid.UUID:
    """Insert a BOQ + 3 priced positions with reference_code=None, return boq id.

    No ``reference_code`` is the exact trigger for the idempotency bug: the
    cost-line code falls back to a random ``CL-XXXX`` regenerated every run.
    """
    from app.modules.boq.models import BOQ, Position

    boq = BOQ(project_id=project_id, name="PG Unref BOQ")
    pg_session.add(boq)
    await pg_session.flush()
    specs = [
        ("01.001", "RC wall C30/37", "m3", "10", "100", "1000", {"din276": "330"}),
        ("01.002", "Formwork", "m2", "5", "40", "200", {"din276": "330"}),
        ("02.001", "Rebar B500B", "kg", "200", "1.5", "300", {"din276": "340"}),
    ]
    for ordinal, desc, unit, qty, rate, total, classification in specs:
        pg_session.add(
            Position(
                boq_id=boq.id,
                ordinal=ordinal,
                description=desc,
                unit=unit,
                quantity=qty,
                unit_rate=rate,
                total=total,
                classification=classification,
                reference_code=None,  # the bug trigger
            )
        )
    await pg_session.flush()
    boq_id = boq.id
    # Detach the seed rows so the service works off fresh queries only. The
    # service ``expire_all()``s mid-generation; a lingering expired seed object
    # would otherwise be lazy-loaded during the next autoflush (MissingGreenlet
    # under the async session). Same pattern the JSONB tests above use.
    pg_session.expunge_all()
    return boq_id


async def test_generate_from_boq_idempotent_unreferenced_positions_pg(pg_session) -> None:
    """A 2nd generate_from_boq on real PG creates 0 lines for unreferenced positions.

    Regression guard for the real bug on the production dialect: without a
    ``reference_code`` the cost-line code is a random ``CL-XXXX`` regenerated
    every run, so the prior code-keyed dedup never matched and each re-run
    duplicated the whole batch (a real demo BOQ went 129 -> 258 cost lines).
    Dedup is now keyed on the stable ``boq_position_id``; the count must stay
    equal across runs, with the exact same rows.
    """
    from app.modules.costmodel.repository import CostLineRepository
    from app.modules.costmodel.service import CostSpineService

    project_id = await _seed_project(pg_session, currency="EUR")
    boq_id = await _seed_boq_with_unreferenced_positions(pg_session, project_id)

    service = CostSpineService(pg_session)
    line_repo = CostLineRepository(pg_session)

    # ── 1st generate ──
    first = await service.generate_from_boq(project_id, boq_id)
    assert first.cost_lines_created == 3
    assert first.accounts_created == 2  # din276 330 + 340
    assert first.positions_linked == 3

    lines_after_first, total_after_first = await line_repo.list_for_project(project_id, limit=1000)
    assert total_after_first == 3
    # Every code is a random auto CL-XXXX (no reference_code on any position).
    assert all(line.code.startswith("CL-") for line in lines_after_first)
    first_ids = {line.id for line in lines_after_first}

    # ── 2nd generate: pure no-op on counts, no duplicate rows ──
    second = await service.generate_from_boq(project_id, boq_id)
    assert second.cost_lines_created == 0, "2nd run duplicated cost lines on PG (the bug)"
    assert second.accounts_created == 0
    assert second.positions_linked == 0
    assert second.budget_lines_linked == 0

    lines_after_second, total_after_second = await line_repo.list_for_project(project_id, limit=1000)
    assert total_after_second == total_after_first == 3, "cost lines doubled on PG"
    assert {line.id for line in lines_after_second} == first_ids


async def test_generate_from_boq_idempotent_referenced_positions_pg(pg_session) -> None:
    """Referenced positions stay idempotent on PG too (no regression).

    With a stable ``reference_code`` the code-keyed path already worked; this
    pins that the new position-keyed dedup keeps it a no-op on the 2nd run.
    """
    from app.modules.boq.models import BOQ, Position
    from app.modules.costmodel.repository import CostLineRepository
    from app.modules.costmodel.service import CostSpineService

    project_id = await _seed_project(pg_session, currency="EUR")
    boq = BOQ(project_id=project_id, name="PG Ref BOQ")
    pg_session.add(boq)
    await pg_session.flush()
    pg_session.add_all(
        [
            Position(
                boq_id=boq.id,
                ordinal="01",
                description="RC wall",
                unit="m3",
                quantity="10",
                unit_rate="100",
                total="1000",
                classification={"din276": "330"},
                reference_code="P-330-1",
            ),
            Position(
                boq_id=boq.id,
                ordinal="02",
                description="Rebar",
                unit="kg",
                quantity="200",
                unit_rate="1.5",
                total="300",
                classification={"din276": "340"},
                reference_code="P-340-1",
            ),
        ]
    )
    await pg_session.flush()
    boq_id = boq.id
    # Detach seed rows (see _seed_boq_with_unreferenced_positions for why).
    pg_session.expunge_all()

    service = CostSpineService(pg_session)
    line_repo = CostLineRepository(pg_session)

    first = await service.generate_from_boq(project_id, boq_id)
    assert first.cost_lines_created == 2
    lines_first, total_first = await line_repo.list_for_project(project_id, limit=1000)
    # Codes come from the reference_code, not the auto CL-XXXX.
    assert {line.code for line in lines_first} == {"P-330-1", "P-340-1"}

    second = await service.generate_from_boq(project_id, boq_id)
    assert second.cost_lines_created == 0
    assert second.accounts_created == 0
    _lines_second, total_second = await line_repo.list_for_project(project_id, limit=1000)
    assert total_second == total_first == 2


async def test_committed_by_cost_line_counts_only_subcontract_contracts(pg_session) -> None:
    """A client contract is what the project earns, so it commits no cost."""
    from app.modules.contracts.models import Contract, ContractLine
    from app.modules.costmodel.models import CostLine
    from app.modules.costmodel.repository import CostSpineRepository

    project_id = await _seed_project(pg_session, currency="EUR")
    line = CostLine(project_id=project_id, code="CL-SIDE", currency="EUR", estimate_amount="0")
    pg_session.add(line)
    await pg_session.flush()

    contracts = {
        side: Contract(
            code=f"C-{side[:3].upper()}-{uuid.uuid4().hex[:5]}",
            title=side,
            project_id=project_id,
            counterparty_type=side,
            total_value=Decimal("0"),
            currency="EUR",
            status="active",
        )
        for side in ("client", "subcontractor")
    }
    pg_session.add_all(contracts.values())
    await pg_session.flush()
    pg_session.add_all(
        [
            ContractLine(
                contract_id=contracts["client"].id,
                code="L1",
                description="billed to the client",
                unit="m3",
                quantity=Decimal("1"),
                unit_rate=Decimal("5000"),
                total_value=Decimal("5000"),
                cost_line_id=line.id,
            ),
            ContractLine(
                contract_id=contracts["subcontractor"].id,
                code="L1",
                description="owed to the subcontractor",
                unit="m3",
                quantity=Decimal("1"),
                unit_rate=Decimal("3000"),
                total_value=Decimal("3000"),
                cost_line_id=line.id,
            ),
        ]
    )
    await pg_session.flush()

    out = await CostSpineRepository(pg_session).committed_by_cost_line(project_id)
    assert out == {str(line.id): Decimal("3000")}
