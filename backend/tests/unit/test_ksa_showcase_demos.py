# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The four Saudi showcase demos are registered, priced, and install with every business area filled.

Static checks read the templates only. The install check runs the real seeder and then counts what the
project holds: bill, budget, procurement, subcontract, schedule and billing, and that the numbers reconcile.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.demo_projects import DEMO_CATALOG, DEMO_TEMPLATES, install_demo_project

KSA_SHOWCASE_IDS = [
    "consultancy-riyadh",
    "contractor-jeddah",
    "site-development-dammam",
    "full-showcase-riyadh",
]


@pytest.mark.parametrize("demo_id", KSA_SHOWCASE_IDS)
def test_template_is_registered_and_saudi(demo_id: str) -> None:
    template = DEMO_TEMPLATES[demo_id]
    assert demo_id in {entry["demo_id"] for entry in DEMO_CATALOG}
    assert template.region == "SA"
    assert template.currency == "SAR"
    assert template.locale == "en"
    assert template.project_metadata.get("name_ar")
    assert any(m[0].startswith("VAT") and m[1] == 15.0 for m in template.markups)


@pytest.mark.parametrize("demo_id", KSA_SHOWCASE_IDS)
def test_bill_is_compact_and_priced(demo_id: str) -> None:
    template = DEMO_TEMPLATES[demo_id]
    ordinals = [item[0] for section in template.sections for item in section[3]]
    assert 60 <= len(ordinals) <= 150
    assert len(ordinals) == len(set(ordinals)), "duplicate position ordinals"
    for _code, _title, _cls, items in template.sections:
        for _ord, desc, unit, qty, rate, cls in items:
            assert desc.strip()
            assert unit
            assert qty > 0
            assert rate > 0
            assert cls.get("masterformat")
    assert len(template.tender_packages) >= 2
    assert len(template.schedule_activities) >= 6


def test_ids_are_unique_across_the_registry() -> None:
    catalog_ids = [entry["demo_id"] for entry in DEMO_CATALOG]
    assert len(catalog_ids) == len(set(catalog_ids))
    assert len(set(KSA_SHOWCASE_IDS)) == 4


def test_full_showcase_covers_all_six_business_lines() -> None:
    sections = {s[0]: s[1] for s in DEMO_TEMPLATES["full-showcase-riyadh"].sections}
    assert set(sections) == {"A", "B", "C", "D", "E", "F"}
    ffe = next(s for s in DEMO_TEMPLATES["full-showcase-riyadh"].sections if s[0] == "F")
    assert len(ffe[3]) >= 15
    names = " ".join(p[0].lower() for p in DEMO_TEMPLATES["full-showcase-riyadh"].tender_packages)
    assert "ff&e" in names


@pytest.mark.parametrize("demo_id", KSA_SHOWCASE_IDS)
async def test_install_fills_every_business_area(demo_id: str) -> None:
    from app.modules.boq.models import BOQ, Position
    from app.modules.contracts.models import Contract
    from app.modules.costmodel.models import BudgetLine
    from app.modules.finance.models import Invoice
    from app.modules.procurement.models import PurchaseOrder
    from app.modules.schedule.models import Activity, Schedule
    from app.modules.subcontractors.models import PaymentApplication, SubcontractAgreement
    from tests._pg import transactional_session

    template = DEMO_TEMPLATES[demo_id]
    async with transactional_session() as session:
        result = await install_demo_project(session, demo_id)
        pid = uuid.UUID(result["project_id"])

        # Bill: the bill total is the sum of its priced positions and matches the template.
        boqs = (await session.execute(select(BOQ).where(BOQ.project_id == pid))).scalars().all()
        assert boqs
        bill = next(b for b in boqs if b.name == template.boq_name)
        rows = (await session.execute(select(Position).where(Position.boq_id == bill.id))).scalars().all()
        priced = [p for p in rows if Decimal(str(p.quantity or 0)) > 0]
        assert len(priced) == sum(len(s[3]) for s in template.sections)
        installed_total = sum((Decimal(str(p.total)) for p in priced), Decimal(0))
        expected_total = sum(
            (Decimal(str(i[3])) * Decimal(str(i[4])) for s in template.sections for i in s[3]), Decimal(0)
        )
        assert abs(installed_total - expected_total) <= Decimal("0.05") * len(priced)

        async def count(model, *where) -> int:
            return (await session.execute(select(func.count()).select_from(model).where(*where))).scalar_one()

        assert await count(BudgetLine, BudgetLine.project_id == pid) > 0, "no budget lines"
        assert await count(PurchaseOrder, PurchaseOrder.project_id == pid) > 0, "no purchase orders"
        assert await count(Contract, Contract.project_id == pid) > 0, "no contracts"
        assert await count(Invoice, Invoice.project_id == pid) > 0, "no invoices"

        agreements = (
            (await session.execute(select(SubcontractAgreement).where(SubcontractAgreement.project_id == pid)))
            .scalars()
            .all()
        )
        assert agreements, "no subcontract"
        agreement_ids = [a.id for a in agreements]
        claims = (
            (
                await session.execute(
                    select(PaymentApplication).where(PaymentApplication.agreement_id.in_(agreement_ids))
                )
            )
            .scalars()
            .all()
        )
        assert claims, "no progress claim"
        for agreement in agreements:
            claimed = sum((Decimal(str(c.gross_amount)) for c in claims if c.agreement_id == agreement.id), Decimal(0))
            assert claimed <= Decimal(str(agreement.total_value)), "claims exceed the subcontract value"
            for claim in (c for c in claims if c.agreement_id == agreement.id):
                gross = Decimal(str(claim.gross_amount))
                assert Decimal(str(claim.net_amount)) == gross - Decimal(str(claim.retention_amount))

        schedules = (await session.execute(select(Schedule).where(Schedule.project_id == pid))).scalars().all()
        assert schedules
        assert await count(Activity, Activity.schedule_id == schedules[0].id) >= len(template.schedule_activities)


@pytest.mark.parametrize("demo_id", KSA_SHOWCASE_IDS)
async def test_billing_history_and_requisitions(demo_id: str) -> None:
    from app.modules.boq.models import Position
    from app.modules.procurement.models import MaterialRequisition
    from app.modules.subcontractors.models import PaymentApplication, SubcontractAgreement
    from tests._pg import transactional_session

    template = DEMO_TEMPLATES[demo_id]
    assert 3 <= len(template.progress_claims) <= 4
    assert template.seed_requisitions
    async with transactional_session() as session:
        result = await install_demo_project(session, demo_id)
        pid = uuid.UUID(result["project_id"])

        agreement = (
            await session.execute(select(SubcontractAgreement).where(SubcontractAgreement.project_id == pid))
        ).scalar_one()
        claims = (
            (
                await session.execute(
                    select(PaymentApplication)
                    .where(PaymentApplication.agreement_id == agreement.id)
                    .order_by(PaymentApplication.application_number)
                )
            )
            .scalars()
            .all()
        )
        assert len(claims) == len(template.progress_claims)
        contract = Decimal(str(agreement.total_value))
        cumulative = Decimal(0)
        for claim, pct in zip(claims, template.progress_claims, strict=True):
            gross = Decimal(str(claim.gross_amount))
            retention = Decimal(str(claim.retention_amount))
            assert gross > 0
            assert Decimal(str(claim.net_amount)) == gross - retention
            cumulative += gross
            assert abs(cumulative - contract * Decimal(str(pct))) <= Decimal("0.01")
            assert cumulative <= contract
        assert abs(
            sum((Decimal(str(c.retention_amount)) for c in claims), Decimal(0)) - cumulative * Decimal("0.05")
        ) <= Decimal("0.01")
        assert [c.period_start.month for c in claims] == [4, 5, 6, 7][: len(claims)]

        reqs = (
            (await session.execute(select(MaterialRequisition).where(MaterialRequisition.project_id == pid)))
            .scalars()
            .all()
        )
        assert len(reqs) == len(template.tender_packages)
        assert {"ordered", "approved", "submitted", "draft"} >= {r.status for r in reqs}
        positions = {p.id: p for p in (await session.execute(select(Position))).scalars().all() if p.unit != ""}
        for req in reqs:
            assert req.items
            assert (req.status == "ordered") == (req.po_id is not None)
            for item in req.items:
                assert item.unit
                assert item.required_date
                source = item.sources[0]
                position = positions[source.boq_position_id]
                assert Decimal(source.quantity) == Decimal(item.quantity_requested)
                assert 0 < Decimal(source.quantity) <= Decimal(str(position.quantity))


async def test_template_without_the_new_fields_seeds_as_before() -> None:
    from app.modules.procurement.models import MaterialRequisition
    from app.modules.subcontractors.models import PaymentApplication, SubcontractAgreement
    from tests._pg import transactional_session

    template = DEMO_TEMPLATES["residential-berlin"]
    assert template.progress_claims == ()
    assert template.seed_requisitions is False
    async with transactional_session() as session:
        result = await install_demo_project(session, "residential-berlin")
        pid = uuid.UUID(result["project_id"])
        agreement = (
            await session.execute(select(SubcontractAgreement).where(SubcontractAgreement.project_id == pid))
        ).scalar_one()
        claims = (
            (await session.execute(select(PaymentApplication).where(PaymentApplication.agreement_id == agreement.id)))
            .scalars()
            .all()
        )
        assert [c.application_number for c in claims] == ["PA-001"]
        assert Decimal(str(claims[0].gross_amount)) == (Decimal(str(agreement.total_value)) * Decimal("0.35")).quantize(
            Decimal("0.01")
        )
        count = (
            await session.execute(
                select(func.count()).select_from(MaterialRequisition).where(MaterialRequisition.project_id == pid)
            )
        ).scalar_one()
        assert count == 0
