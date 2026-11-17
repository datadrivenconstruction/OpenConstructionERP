# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A pay application's statement is read from the database, not from the request.

The worked example: a 100,000 agreement with 5,000 of approved change, retention
10 percent, concrete 60,000 and steel 40,000. PA-0001 (finance approved) bills
30,000 and 10,000, PA-0002 (rejected) bills 50,000 on concrete, and PA-0003 (the
one read) bills 15,000 and 20,000. Rejected work never counts, so the statement
shows 75,000 completed, 7,500 retention held, 36,000 previously certified and
31,500 due. The required-documents list is read from the same database.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.projects.models import Project
from app.modules.subcontractors.models import (
    PaymentApplication,
    PaymentApplicationLine,
    SubcontractAgreement,
    SubcontractChange,
    SubcontractDocument,
    Subcontractor,
    WorkPackage,
)
from app.modules.subcontractors.service import SubcontractorService
from app.modules.users.models import User
from tests._pg import isolated_engine

D = Decimal


@pytest.mark.asyncio
async def test_the_statement_ignores_rejected_work_and_reads_the_document_gaps() -> None:
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as s:
            user = User(
                email=f"sov-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", full_name="QS", role="admin"
            )
            s.add(user)
            await s.flush()
            project = Project(name="Tower", owner_id=user.id, currency="USD")
            sub = Subcontractor(legal_name="Concrete Co", country="US")
            s.add_all([project, sub])
            await s.flush()
            agreement = SubcontractAgreement(
                subcontractor_id=sub.id,
                project_id=project.id,
                title="Frame",
                status="active",
                currency="USD",
                total_value=D("100000"),
                retention_percent=D("10"),
            )
            s.add(agreement)
            await s.flush()
            s.add(
                SubcontractChange(
                    agreement_id=agreement.id,
                    project_id=project.id,
                    code="CO-01",
                    title="Extra slab",
                    status="approved",
                    amount=D("5000"),
                    applied_amount=D("5000"),
                )
            )
            concrete = WorkPackage(agreement_id=agreement.id, name="Concrete", planned_value=D("60000"))
            steel = WorkPackage(agreement_id=agreement.id, name="Steel", planned_value=D("40000"))
            s.add_all([concrete, steel])
            await s.flush()

            def pa(number: str, status: str, c: str, st: str) -> PaymentApplication:
                gross = D(c) + D(st)
                ret = gross * D("0.10")
                row = PaymentApplication(
                    agreement_id=agreement.id,
                    application_number=number,
                    gross_amount=gross,
                    retention_amount=ret,
                    net_amount=gross - ret,
                    currency="USD",
                    status=status,
                )
                if status == "finance_approved":
                    row.approved_gross_amount = gross
                    row.approved_retention_amount = ret
                    row.approved_net_amount = gross - ret
                return row

            apps = [
                (pa("PA-0001", "finance_approved", "30000", "10000"), ("30000", "10000")),
                (pa("PA-0002", "rejected", "50000", "0"), ("0", "0")),
                (pa("PA-0003", "submitted", "15000", "20000"), ("0", "0")),
            ]
            for row, _ in apps:
                s.add(row)
            await s.flush()
            for row, (ca, sa) in apps:
                claimed = {"PA-0001": ("30000", "10000"), "PA-0002": ("50000", "0"), "PA-0003": ("15000", "20000")}[
                    row.application_number
                ]
                for pkg, amount, approved in ((concrete, claimed[0], ca), (steel, claimed[1], sa)):
                    s.add(
                        PaymentApplicationLine(
                            payment_application_id=row.id,
                            work_package_id=pkg.id,
                            claimed_amount=D(amount),
                            approved_amount=D(approved),
                        )
                    )
            await s.commit()
            current_id = apps[2][0].id
            agreement_id = agreement.id

        async with factory() as s:
            svc = SubcontractorService(s)
            statement = await svc.pay_app_statement(current_id)
            summary = statement["summary"]
            assert D(str(summary["completed_to_date"])) == D("75000")
            assert D(str(summary["retention_held"])) == D("7500")
            assert D(str(summary["previous_certified"])) == D("36000")
            assert D(str(summary["current_due"])) == D("31500")
            assert D(str(summary["change_orders"])) == D("5000")
            assert {row["name"]: D(str(row["previous"])) for row in statement["lines"]} == {
                "Concrete": D("30000"),
                "Steel": D("10000"),
            }

            gaps = await svc.required_documents_status(agreement_id)
            assert {g["role"]: g["state"] for g in gaps["gaps"]} == {
                "terms_and_conditions": "missing",
                "safety_plan": "missing",
            }
            s.add(
                SubcontractDocument(
                    agreement_id=agreement_id,
                    doc_role="safety_plan",
                    title="Site safety plan",
                    filename="plan.pdf",
                    document_url="/x/plan.pdf",
                )
            )
            await s.commit()
            gaps = await svc.required_documents_status(agreement_id)
            assert [g["role"] for g in gaps["gaps"]] == ["terms_and_conditions"]
