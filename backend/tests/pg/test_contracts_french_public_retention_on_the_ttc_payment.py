# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A French public contract holds its retenue de garantie on the TTC payment, end to end.

Code de la commande publique, R2191-33 and R2191-34, read by the economy
ministry's legal directorate (fiche "Les garanties financières", 2019-04-01,
page 4) as TTC for both the instalment and the five percent ceiling on the
initial amount.

The acompte bills 92,260.14 HT on a 1,000,000.00 HT contract at five percent
retention: 110,712.17 TTC at 20 % TVA, 5,535.61 held. On the HT it was
4,613.01, and that is still the figure for private works and for every
subcontract, which is private works whoever the client is.

The claim and the finance receivable read the retention as money and must
agree. The project and contract state no VAT rate, so the TVA comes from the
country's standard rate.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio

from app.modules.contracts.models import Contract, ContractLine, ProgressClaim
from app.modules.contracts.schemas import AutoGenerateClaimRequest
from app.modules.contracts.service import ContractsService
from app.modules.contracts.validators import register_contracts_validation_rules
from app.modules.finance.service import FinanceService
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

OWNER_ID = uuid.uuid4()
D = Decimal

#: Percent complete of the single 1,000,000.00 line that bills 92,260.14 HT.
ACOMPTE_PERCENT = "9.226014"


@pytest_asyncio.fixture
async def session():
    register_contracts_validation_rules()
    async with transactional_session() as s:
        s.add(User(id=OWNER_ID, email=f"fr-ret-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x"))
        await s.flush()
        yield s


async def _contract(
    session, works: str | None, *, rate: str = "5", counterparty: str = "client"
) -> tuple[Contract, ContractLine]:
    project = Project(
        id=uuid.uuid4(),
        name="Groupe scolaire",
        owner_id=OWNER_ID,
        currency="EUR",
        country_code="FR",
        works=works,
    )
    session.add(project)
    await session.flush()
    contract = Contract(
        id=uuid.uuid4(),
        code=f"C-{uuid.uuid4().hex[:8]}",
        title="Gros oeuvre",
        project_id=project.id,
        contract_type="lump_sum",
        counterparty_type=counterparty,
        currency="EUR",
        total_value=D("1000000"),
        original_contract_value=D("1000000"),
        retention_percent=D(rate),
        status="active",
        terms={"payment_terms": {"retention_cap_percent": "5"}},
        metadata_={},
    )
    session.add(contract)
    await session.flush()
    line = ContractLine(
        id=uuid.uuid4(),
        contract_id=contract.id,
        code="01.01",
        description="Gros oeuvre",
        quantity=D("1"),
        unit_rate=D("1000000"),
        total_value=D("1000000"),
        metadata_={},
    )
    session.add(line)
    await session.flush()
    return contract, line


async def _certified_claim(session, contract: Contract, line: ContractLine, number: str, month: int, percent: str):
    claim = ProgressClaim(
        id=uuid.uuid4(),
        contract_id=contract.id,
        claim_number=number,
        period_start=f"2026-{month:02d}-01",
        period_end=f"2026-{month:02d}-28",
        claim_date=f"2026-{month:02d}-28",
        period_from=date(2026, month, 1),
        period_to=date(2026, month, 28),
        status="draft",
        currency="EUR",
    )
    session.add(claim)
    await session.flush()
    svc = ContractsService(session)
    claim = await svc.auto_generate_claim_lines(
        claim.id, AutoGenerateClaimRequest(completion={str(line.id): D(percent)})
    )
    for target in ("submitted", "approved", "certified"):
        claim = await svc.transition_claim(claim.id, target, actor_id=str(OWNER_ID))
    return claim


async def test_a_public_acompte_holds_5535_61(session) -> None:
    contract, line = await _contract(session, "public")
    claim = await _certified_claim(session, contract, line, "PC-1", 3, ACOMPTE_PERCENT)

    assert D(claim.gross_amount) == D("92260.14")
    assert D(claim.retention_amount) == D("5535.61")
    assert D(claim.retention_held_to_date) == D("5535.61")

    # The receivable books the TVA the retention was measured with and
    # withholds the claim's own retention once.
    invoice = await FinanceService(session).create_receivable_from_claim(claim.id)
    assert D(invoice.amount_subtotal) == D("92260.14")
    assert D(invoice.tax_amount) == D("18452.03")
    assert D(invoice.amount_total) == D("110712.17")
    assert D(invoice.retention_amount) == D("5535.61")


async def test_the_public_ceiling_is_five_percent_of_the_initial_amount_ttc(session) -> None:
    contract, line = await _contract(session, "public", rate="10")
    first = await _certified_claim(session, contract, line, "PC-1", 3, ACOMPTE_PERCENT)
    assert D(first.retention_amount) == D("11071.22")
    second = await _certified_claim(session, contract, line, "PC-2", 4, "90")

    # 5 % of 1,200,000.00 TTC is 60,000.00, not the 50,000.00 of the HT sum.
    assert D(second.retention_held_to_date) == D("60000.00")
    assert D(second.retention_amount) == D("48928.78")


@pytest.mark.parametrize("works", ["private", None])
async def test_private_or_unrecorded_works_stay_on_the_ht(session, works: str | None) -> None:
    contract, line = await _contract(session, works)
    claim = await _certified_claim(session, contract, line, "PC-1", 3, ACOMPTE_PERCENT)
    assert D(claim.retention_amount) == D("4613.01")

    invoice = await FinanceService(session).create_receivable_from_claim(claim.id)
    # No VAT agreed on the contract and an HT basis, so none booked, as before.
    assert (D(invoice.tax_amount), D(invoice.retention_amount)) == (D("0"), D("4613.01"))


async def test_a_subcontract_on_a_public_project_stays_on_the_ht(session) -> None:
    contract, line = await _contract(session, "public", counterparty="subcontractor")
    claim = await _certified_claim(session, contract, line, "PC-1", 3, ACOMPTE_PERCENT)
    assert D(claim.retention_amount) == D("4613.01")

    invoice = await FinanceService(session).create_receivable_from_claim(claim.id)
    assert invoice.invoice_direction == "payable"
    assert (D(invoice.tax_amount), D(invoice.retention_amount)) == (D("0"), D("4613.01"))
