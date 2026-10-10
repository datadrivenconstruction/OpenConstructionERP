# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The payment certificate (hakediş) we issue to one of our own subcontractors.

The same sheet as the one a progress claim prints, read the other way round:
we are the employer, the subcontractor is the contractor, and the taxes are
ones we withhold. Three pay applications of one agreement are taken to
finance approval, which is where a pay application stops moving and so where
its certificate is checked and frozen.

Raising the payable is the finance module's business and is replaced by a
stand-in here; what is asserted is that it is reached only after the
certificate has passed.

Every rate in this file is SYNTHETIC and none may be read as a Turkish rate.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select

from app.core.payment_taxes import RateRow
from app.modules.contracts import certificate_taxes, hakedis_document
from app.modules.contracts.models import CertificateLine
from app.modules.contracts.schemas import HakedisLineInput, HakedisOptionsInput, HakedisTaxChoice, HakedisTaxesInput
from app.modules.contracts.validators import register_contracts_validation_rules
from app.modules.projects.models import Project
from app.modules.subcontractors import service as sub_service
from app.modules.subcontractors.models import Certificate, Subcontractor
from app.modules.subcontractors.schemas import (
    AgreementCreate,
    AgreementUpdate,
    ApprovedLineAmount,
    PaymentApplicationCreate,
    PaymentApplicationLineCreate,
    WorkPackageCreate,
)
from app.modules.subcontractors.service import SubcontractorService
from app.modules.tax_withholding import service as tax_service
from app.modules.tax_withholding import source_owners
from app.modules.tax_withholding.validators import register_tax_withholding_rules
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

D = Decimal
OWNER_ID = uuid.uuid4()
SOURCE_KIND = "sub_payment_application"

# SYNTHETIC rates, illustrative only.
SYNTHETIC_VAT_PCT = D("20")
SYNTHETIC_WITHHOLDING = (1, 2)
SYNTHETIC_INCOME_PCT = D("3")
SYNTHETIC_STAMP_PCT = D("0.5")
RETENTION_PCT = D("5")

# work package, planned value, billed on applications 1, 2 and 3.
PACKAGES: tuple[tuple[str, str, str, str, str], ...] = (
    ("Yangın tesisatı borulaması", "480000.00", "150000.00", "210000.00", "120000.00"),
    ("Havalandırma kanalları", "725500.50", "200000.00", "300500.50", "225000.00"),
    ("Kablo tavaları ve kablolama", "394499.50", "94499.50", "200000.00", "100000.00"),
)
AGREEMENT_VALUE = sum((D(row[1]) for row in PACKAGES), D("0"))


def _billed(number: int) -> Decimal:
    return sum((D(row[1 + number]) for row in PACKAGES), D("0"))


def q(value: Decimal) -> Decimal:
    return value.quantize(D("0.01"), rounding=ROUND_HALF_UP)


def _row(**changes) -> RateRow:
    base = RateRow(
        country_code="TR",
        kind="vat_withholding",
        code="W1",
        labels={"en": "Synthetic work", "tr": "Sentetik iş"},
        base="vat",
        rate_pct=None,
        numerator=SYNTHETIC_WITHHOLDING[0],
        denominator=SYNTHETIC_WITHHOLDING[1],
        threshold_amount=None,
        threshold_currency="",
        threshold_scope="",
        threshold_measure="",
        cap_amount=None,
        effective_from=date(2020, 1, 1),
        effective_to=None,
        legal_reference="Synthetic Act art. 1",
        source_url="https://example.invalid/act/1",
        read_date="2026-01-01",
        review_status="confirmed",
    )
    return replace(base, **changes)


ROWS: tuple[RateRow, ...] = (
    _row(),
    _row(
        kind="income_withholding",
        code="I1",
        base="net",
        rate_pct=SYNTHETIC_INCOME_PCT,
        numerator=None,
        denominator=None,
    ),
    _row(kind="stamp_duty", code="S1", base="net", rate_pct=SYNTHETIC_STAMP_PCT, numerator=None, denominator=None),
)

TAX_CHOICES = HakedisTaxesInput(
    vat_withholding=HakedisTaxChoice(state="selected", code="W1"),
    income_withholding=HakedisTaxChoice(state="selected", code="I1"),
    stamp_duty=HakedisTaxChoice(state="selected", code="S1"),
)


@pytest_asyncio.fixture
async def world(monkeypatch):
    async def vat_rate(_session, _country, _subdivision, _on):
        return SYNTHETIC_VAT_PCT

    monkeypatch.setattr(tax_service, "certificate_rows", lambda country: ROWS)
    monkeypatch.setattr(hakedis_document, "tax_rows", lambda country: ROWS)
    monkeypatch.setattr(hakedis_document, "vat_rate_source", vat_rate)
    payable = AsyncMock()
    monkeypatch.setattr(sub_service.finance_bridge, "raise_payable_for_pay_app", payable)
    monkeypatch.setattr(sub_service.event_bus, "publish_detached", lambda *args, **kwargs: None)

    register_contracts_validation_rules()
    register_tax_withholding_rules()
    provider, writer = certificate_taxes._provider, certificate_taxes._writer
    owners = dict(source_owners._resolvers)
    tax_service.register_certificate_tax_provider()
    assert sub_service.register_payment_application_as_tax_source() is True
    try:
        async with transactional_session() as session:
            session.add(User(id=OWNER_ID, email=f"sub-hakedis-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x"))
            await session.flush()
            yield session, payable
    finally:
        certificate_taxes._provider, certificate_taxes._writer = provider, writer
        source_owners._resolvers.clear()
        source_owners._resolvers.update(owners)


async def _agreement(session, *, country: str = "TR", metadata: dict | None = None):
    """An active agreement with its three work packages, on a project of ``country``."""
    project = Project(id=uuid.uuid4(), name="Kule Projesi", owner_id=OWNER_ID, currency="TRY", country_code=country)
    subcontractor = Subcontractor(legal_name="Örnek Tesisat Taahhüt A.Ş.", country="TR")
    session.add_all([project, subcontractor])
    await session.flush()
    for cert_type in ("insurance", "license"):
        session.add(
            Certificate(
                subcontractor_id=subcontractor.id, cert_type=cert_type, valid_until=date(2030, 12, 31), status="valid"
            )
        )
    await session.flush()
    svc = SubcontractorService(session)
    agreement = await svc.create_agreement(
        AgreementCreate(
            subcontractor_id=subcontractor.id,
            project_id=project.id,
            title="Mekanik ve elektrik tesisatı taşeronluğu",
            total_value=AGREEMENT_VALUE,
            currency="TRY",
            start_date=date(2026, 1, 5),
            end_date=date(2027, 3, 31),
            retention_percent=RETENTION_PCT,
        )
    )
    if metadata:
        agreement.metadata_ = {**(agreement.metadata_ or {}), **metadata}
        await session.flush()
    await svc.update_agreement(agreement.id, AgreementUpdate(status="active"))
    packages = [
        await svc.create_work_package(WorkPackageCreate(agreement_id=agreement.id, name=name, planned_value=D(planned)))
        for name, planned, *_billed_amounts in PACKAGES
    ]
    return svc, agreement, packages


async def _application(svc: SubcontractorService, agreement, packages, number: int):
    month = number + 1
    application = await svc.submit_payment_application(
        PaymentApplicationCreate(
            agreement_id=agreement.id,
            application_number=str(number),
            period_start=date(2026, month, 1),
            period_end=date(2026, month, 28),
            gross_amount=_billed(number),
            currency="TRY",
            lines=[
                PaymentApplicationLineCreate(work_package_id=package.id, claimed_amount=D(row[1 + number]))
                for package, row in zip(packages, PACKAGES, strict=True)
            ],
        ),
        user_id=str(OWNER_ID),
    )
    return await svc.approve_payment_application_foreman(application.id, user_id=str(OWNER_ID))


def _amounts(view: dict) -> dict[str, Decimal | None]:
    return {line["key"]: (D(line["amount"]) if line["amount"] is not None else None) for line in view["summary"]}


def _line(view: dict, key: str) -> dict:
    return next(line for line in view["summary"] if line["key"] == key)


async def _complete(session, svc: SubcontractorService, payment_id: uuid.UUID, *, advance: str, final: bool) -> None:
    view = await svc.hakedis_view(payment_id, locale="tr")
    for line in view["summary"]:
        if line["op"] != "manual":
            continue
        if line["key"] == "advance_recovery":
            entry = HakedisLineInput(state="value", amount=D(advance))
        else:
            entry = HakedisLineInput(state="not_applicable", note="Sözleşmede yok")
        await svc.save_hakedis_line(payment_id, line["key"], entry, str(OWNER_ID))
    if final:
        await svc.save_hakedis_options(payment_id, HakedisOptionsInput(is_final=True), str(OWNER_ID))
    await svc.save_hakedis_taxes(payment_id, TAX_CHOICES, str(OWNER_ID))
    calc, _lines = await tax_service.get_statutory(session, source_kind=SOURCE_KIND, source_id=payment_id)
    assert calc.direction == "withheld_by_us"
    await tax_service.confirm_statutory(session, calc=calc, user_id=OWNER_ID)


async def test_three_certificates_to_a_subcontractor_chain_and_land_on_the_agreement(world) -> None:
    session, payable = world
    svc, agreement, packages = await _agreement(session)

    previous_total = D("0")
    views = []
    for number, advance in ((1, "40000.00"), (2, "60000.00"), (3, "0.00")):
        application = await _application(svc, agreement, packages, number)
        await _complete(session, svc, application.id, advance=advance, final=number == 3)
        approved = await svc.approve_payment_application_finance(application.id, user_id=str(OWNER_ID))
        assert approved.status == "finance_approved"
        assert payable.await_count == number

        view = await svc.hakedis_view(application.id, locale="tr")
        amounts = _amounts(view)
        cumulative = sum((_billed(n) for n in range(1, number + 1)), D("0"))
        this = _billed(number)
        vat = q(this * SYNTHETIC_VAT_PCT / 100)
        withheld = q(vat * SYNTHETIC_WITHHOLDING[0] / SYNTHETIC_WITHHOLDING[1])
        income = q(this * SYNTHETIC_INCOME_PCT / 100)
        stamp = q((this - D(advance)) * SYNTHETIC_STAMP_PCT / 100)
        retention = q(this * RETENTION_PCT / 100)
        deductions = income + stamp + withheld + D(advance) + retention

        assert view["frozen"] is True
        assert view["source_kind"] == SOURCE_KIND
        assert view["flavour"] == "lump_sum"
        assert view["taxes"]["direction"] == "withheld_by_us"
        assert view["header"]["certificate_number"] == number
        assert amounts["work_done"] == cumulative
        assert amounts["previous_certificates"] == previous_total
        assert amounts["this_certificate"] == this
        assert amounts["vat"] == vat
        assert amounts["income_tax"] == income
        assert amounts["stamp_duty"] == stamp
        assert amounts["vat_withholding"] == withheld
        assert amounts["retention"] == retention
        assert amounts["deductions_total"] == deductions
        assert amounts["payable"] == this + vat - deductions
        # The retention the sheet prints is the retention the application holds.
        assert retention == D(str(approved.approved_retention_amount))
        previous_total = D(view["carried_total"])
        views.append(view)

    assert _amounts(views[-1])["work_done"] == AGREEMENT_VALUE
    assert views[-1]["header"]["is_final"] is True
    # We are the employer on this sheet and the subcontractor the contractor.
    assert views[0]["header"]["contractor"]["name"] == "Örnek Tesisat Taahhüt A.Ş."


async def test_finance_approval_is_refused_until_the_certificate_is_ready(world) -> None:
    session, payable = world
    svc, agreement, packages = await _agreement(session)
    # The id is kept apart: the refusal rolls the approval back, and with it
    # every attribute loaded on the row.
    application_id = (await _application(svc, agreement, packages, 1)).id

    with pytest.raises(HTTPException) as refused:
        await svc.approve_payment_application_finance(application_id, user_id=str(OWNER_ID))
    assert refused.value.status_code == 422
    assert refused.value.detail["error"] == "hakedis_not_ready"
    assert "hakedis.lines_complete" in {finding["rule_id"] for finding in refused.value.detail["findings"]}
    payable.assert_not_awaited()
    stored = await session.scalar(
        select(func.count())
        .select_from(CertificateLine)
        .where(CertificateLine.source_id == application_id, CertificateLine.frozen.is_(True))
    )
    assert stored == 0
    # The refusal undid the approval itself, not only the certificate.
    assert (await svc.payments.get_by_id(application_id)).status == "foreman_approved"

    # Lowering a line at approval would certify a sheet nobody has seen.
    await _complete(session, svc, application_id, advance="0.00", final=False)
    [line, *_others] = await svc.payment_lines.list_for_application(application_id)
    with pytest.raises(HTTPException) as lowered:
        await svc.approve_payment_application_finance(
            application_id,
            user_id=str(OWNER_ID),
            lines=[ApprovedLineAmount(line_id=line.id, approved_amount=D("1000.00"))],
        )
    assert lowered.value.status_code == 409
    assert lowered.value.detail["code"] == "hakedis_amounts_differ"
    payable.assert_not_awaited()

    approved = await svc.approve_payment_application_finance(application_id, user_id=str(OWNER_ID))
    assert approved.status == "finance_approved"
    payable.assert_awaited_once()


async def test_an_agreement_can_bring_its_own_layout(world) -> None:
    session, _payable = world
    svc, agreement, packages = await _agreement(session, metadata={"hakedis": {"preset": "TR_PRIVATE"}})
    application = await _application(svc, agreement, packages, 1)
    view = await svc.hakedis_view(application.id, locale="tr-en")
    # The private layout leads with the retention, lettered a.
    assert _line(view, "retention")["letter"] == "a"
    assert "back_charges" in {line["key"] for line in view["summary"]}
    assert len(_line(view, "retention")["labels"]) == 2


async def test_a_subcontract_outside_the_certificate_countries_is_approved_as_before(world) -> None:
    session, payable = world
    svc, agreement, packages = await _agreement(session, country="DE")
    application = await _application(svc, agreement, packages, 1)

    with pytest.raises(HTTPException) as absent:
        await svc.hakedis_view(application.id, locale="tr")
    assert absent.value.status_code == 404
    assert absent.value.detail["error"] == "hakedis_not_available"

    approved = await svc.approve_payment_application_finance(application.id, user_id=str(OWNER_ID))
    assert approved.status == "finance_approved"
    payable.assert_awaited_once()
    stored = await session.scalar(
        select(func.count()).select_from(CertificateLine).where(CertificateLine.source_id == application.id)
    )
    assert stored == 0
