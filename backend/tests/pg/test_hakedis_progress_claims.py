# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The payment certificate (hakediş) of a progress claim, from claim to certified sheet.

One mechanical and electrical bill is claimed three times on a unit-price
contract of a Turkish project, the third claim being final, and the same is
done once on a lump-sum contract. What is held here:

* the chain: what one certificate carries as its total, the next one states
  as the total of the previous certificates;
* agreement: the value of work on the certificate is the value the claim's
  own payment application states, because both read the same rows;
* certification: it is refused while a line is open, while the taxes are not
  stored, not confirmed, or were computed before the certificate changed, and
  once it passes the sheet is frozen;
* reproducibility: a frozen sheet reads the same after the rate table, the
  VAT rate and the contract's own lines have all changed;
* a project outside the certificate countries is not touched by any of it.

Every rate in this file is SYNTHETIC. The VAT rate, the withholding fraction
and the income and stamp duty rates are round numbers that make the sums easy
to follow; none of them is a Turkish rate and none may be read as one.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select

from app.core.payment_taxes import RateRow
from app.modules.contracts import certificate_taxes, hakedis_document
from app.modules.contracts.models import CertificateLine, Contract, ContractLine, ProgressClaim
from app.modules.contracts.schemas import (
    AutoGenerateClaimRequest,
    HakedisLineInput,
    HakedisOptionsInput,
    HakedisTaxChoice,
    HakedisTaxesInput,
)
from app.modules.contracts.service import ContractsService
from app.modules.contracts.validators import register_contracts_validation_rules
from app.modules.projects.models import Project
from app.modules.tax_withholding import service as tax_service
from app.modules.tax_withholding import source_owners
from app.modules.tax_withholding.validators import register_tax_withholding_rules
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

D = Decimal
OWNER_ID = uuid.uuid4()

# SYNTHETIC rates, illustrative only.
SYNTHETIC_VAT_PCT = D("20")
SYNTHETIC_WITHHOLDING = (3, 10)
SYNTHETIC_INCOME_PCT = D("4")
SYNTHETIC_STAMP_PCT = D("0.25")
RETENTION_PCT = D("10")

# code, description, unit, contract quantity, unit price, quantity of claims 1, 2 and 3.
BILL: tuple[tuple[str, str, str, str, str, str, str, str], ...] = (
    ("M-25.101", "Siyah çelik boru DN50, dişli, yangın tesisatı", "m", "1200", "485.50", "400", "500", "300"),
    ("M-25.210", "Sprinkler başlığı, sarkık tip", "adet", "850", "312.00", "300", "400", "150"),
    ("M-27.040", "Galvanizli sac hava kanalı, dikdörtgen kesitli", "m²", "3450.5", "742.20", "1000.5", "1500", "950"),
    ("E-35.110", "NYY kablo 3x2,5 mm², döşeme dahil", "m", "18500", "64.20", "6000", "8000", "4500"),
    ("E-36.085", "Tali dağıtım panosu, sıva üstü", "adet", "36", "86500.00", "10", "16", "10"),
    ("E-37.010", "LED armatür, 60x60, gömme", "adet", "2400", "1485.00", "800", "1000", "600"),
)
CONTRACT_VALUE = sum((D(row[3]) * D(row[4]) for row in BILL), D("0"))


def _period_value(number: int) -> Decimal:
    return sum((D(row[4 + number]) * D(row[4]) for row in BILL), D("0"))


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


def _rows(*, income: Decimal = SYNTHETIC_INCOME_PCT, stamp: Decimal = SYNTHETIC_STAMP_PCT) -> tuple[RateRow, ...]:
    return (
        _row(),
        _row(kind="income_withholding", code="I1", base="net", rate_pct=income, numerator=None, denominator=None),
        _row(kind="stamp_duty", code="S1", base="net", rate_pct=stamp, numerator=None, denominator=None),
    )


class Rates:
    """The synthetic rate world of one test; a test changes it to show what a frozen sheet ignores."""

    def __init__(self) -> None:
        self.rows = _rows()
        self.vat: Decimal | None = SYNTHETIC_VAT_PCT


@pytest.fixture
def rates(monkeypatch) -> Rates:
    world = Rates()

    async def vat_rate(_session, _country, _subdivision, _on):
        return world.vat

    monkeypatch.setattr(tax_service, "certificate_rows", lambda country: world.rows)
    monkeypatch.setattr(hakedis_document, "tax_rows", lambda country: world.rows)
    monkeypatch.setattr(hakedis_document, "vat_rate_source", vat_rate)
    return world


@pytest_asyncio.fixture
async def session(rates):
    register_tax_withholding_rules()
    provider, writer = certificate_taxes._provider, certificate_taxes._writer
    owners = dict(source_owners._resolvers)
    register_contracts_validation_rules()
    tax_service.register_certificate_tax_provider()
    try:
        async with transactional_session() as s:
            s.add(User(id=OWNER_ID, email=f"hakedis-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x"))
            await s.flush()
            yield s
    finally:
        certificate_taxes._provider, certificate_taxes._writer = provider, writer
        source_owners._resolvers.clear()
        source_owners._resolvers.update(owners)


async def _project(session, *, country: str = "TR") -> Project:
    project = Project(id=uuid.uuid4(), name="Kule Projesi", owner_id=OWNER_ID, currency="TRY", country_code=country)
    session.add(project)
    await session.flush()
    return project


async def _contract(session, project: Project, *, contract_type: str = "unit_price", terms: dict | None = None):
    contract = Contract(
        id=uuid.uuid4(),
        code=f"S-{uuid.uuid4().hex[:8]}",
        title="Mekanik ve elektrik tesisatı",
        project_id=project.id,
        contract_type=contract_type,
        counterparty_type="client",
        currency="TRY",
        total_value=CONTRACT_VALUE,
        original_contract_value=CONTRACT_VALUE,
        retention_percent=RETENTION_PCT,
        status="active",
        start_date="2026-01-05",
        end_date="2027-03-31",
        terms=terms or {},
    )
    session.add(contract)
    await session.flush()
    return contract


async def _bill(session, contract) -> list[ContractLine]:
    lines = []
    for code, description, unit, quantity, price, *_claimed in BILL:
        line = ContractLine(
            id=uuid.uuid4(),
            contract_id=contract.id,
            code=code,
            description=description,
            unit=unit,
            quantity=D(quantity),
            unit_rate=D(price),
            total_value=D(quantity) * D(price),
            metadata_={},
        )
        session.add(line)
        lines.append(line)
    await session.flush()
    return lines


async def _claim(session, contract, number: int) -> ProgressClaim:
    month = number + 1
    claim = ProgressClaim(
        id=uuid.uuid4(),
        contract_id=contract.id,
        claim_number=str(number),
        currency="TRY",
        status="draft",
        period_start=f"2026-{month:02d}-01",
        period_end=f"2026-{month:02d}-28",
        period_from=date(2026, month, 1),
        period_to=date(2026, month, 28),
    )
    session.add(claim)
    await session.flush()
    return claim


async def _measure(svc: ContractsService, claim, lines, number: int, *, lump_sum: bool = False) -> ProgressClaim:
    if lump_sum:
        # Percent complete to date, the same on every row.
        to_date = {1: D("30"), 2: D("70"), 3: D("100")}[number]
        request = AutoGenerateClaimRequest(completion={str(line.id): to_date for line in lines})
    else:
        request = AutoGenerateClaimRequest(
            measurements={str(line.id): D(row[4 + number]) for line, row in zip(lines, BILL, strict=True)}
        )
    return await svc.auto_generate_claim_lines(claim.id, request)


def _amounts(view: dict) -> dict[str, Decimal | None]:
    return {line["key"]: (D(line["amount"]) if line["amount"] is not None else None) for line in view["summary"]}


def _line(view: dict, key: str) -> dict:
    return next(line for line in view["summary"] if line["key"] == key)


def _failed(view: dict) -> set[str]:
    return {finding["rule_id"] for finding in view["findings"]}


TAX_CHOICES = HakedisTaxesInput(
    vat_withholding=HakedisTaxChoice(state="selected", code="W1"),
    income_withholding=HakedisTaxChoice(state="selected", code="I1"),
    stamp_duty=HakedisTaxChoice(state="selected", code="S1"),
)


async def _enter_manual_lines(svc: ContractsService, claim_id: uuid.UUID, *, advance: str) -> None:
    """Decide every manual line: the advance recovery is an amount, the rest do not apply."""
    view = await svc.hakedis_view(claim_id, locale="tr")
    for line in view["summary"]:
        if line["op"] != "manual":
            continue
        if line["key"] == "advance_recovery":
            entry = HakedisLineInput(state="value", amount=D(advance))
        else:
            entry = HakedisLineInput(state="not_applicable", note="Sözleşmede yok")
        await svc.save_hakedis_line(claim_id, line["key"], entry, str(OWNER_ID))


async def _confirm_taxes(session, claim_id: uuid.UUID) -> None:
    calc, _lines = await tax_service.get_statutory(session, source_kind="progress_claim", source_id=claim_id)
    await tax_service.confirm_statutory(session, calc=calc, user_id=OWNER_ID)


async def _certify(svc: ContractsService, claim_id: uuid.UUID) -> ProgressClaim:
    claim = None
    for target in ("submitted", "approved", "certified"):
        claim = await svc.transition_claim(claim_id, target, actor_id=str(OWNER_ID))
    return claim


async def _whole_certificate(
    session, svc: ContractsService, contract, lines, number: int, *, advance: str, lump_sum: bool = False
) -> dict:
    """Claim, complete, tax, confirm and certify one period; the frozen sheet is returned."""
    claim = await _measure(svc, await _claim(session, contract, number), lines, number, lump_sum=lump_sum)
    await _enter_manual_lines(svc, claim.id, advance=advance)
    if number == 3:
        await svc.save_hakedis_options(claim.id, HakedisOptionsInput(is_final=True), str(OWNER_ID))
    await svc.save_hakedis_taxes(claim.id, TAX_CHOICES, str(OWNER_ID))
    await _confirm_taxes(session, claim.id)
    ready = await svc.hakedis_view(claim.id, locale="tr")
    assert ready["can_certify"], ready["findings"]
    certified = await _certify(svc, claim.id)
    assert certified.status == "certified"
    view = await svc.hakedis_view(claim.id, locale="tr")
    assert view["frozen"] is True
    assert view["editable"] is False
    # Freezing changed no figure and no printed word: the stored sheet is the
    # sheet that was checked a moment before.
    assert _amounts(view) == _amounts(ready)
    for frozen_line, live_line in zip(view["summary"], ready["summary"], strict=True):
        for name in ("key", "letter", "status", "text", "labels", "formulas", "details"):
            assert frozen_line[name] == live_line[name], (frozen_line["key"], name)
    assert view["works"] == ready["works"]
    assert view["header"] == {**ready["header"], "issue_date": view["header"]["issue_date"]}
    assert not any(line["enterable"] for line in view["summary"])
    return view


def _check_sheet(view: dict, *, number: int, previous_total: Decimal, advance: str) -> None:
    """Every lettered line of one certificate, from arithmetic done here and not by the module."""
    amounts = _amounts(view)
    cumulative = sum((_period_value(n) for n in range(1, number + 1)), D("0"))
    this = cumulative - previous_total
    vat = q(this * SYNTHETIC_VAT_PCT / 100)
    withheld = q(vat * SYNTHETIC_WITHHOLDING[0] / SYNTHETIC_WITHHOLDING[1])
    income = q(this * SYNTHETIC_INCOME_PCT / 100)
    stamp = q((this - D(advance)) * SYNTHETIC_STAMP_PCT / 100)
    retention = q(this * RETENTION_PCT / 100)
    deductions = income + stamp + withheld + D(advance) + retention

    assert amounts["work_done"] == cumulative
    assert amounts["price_adjustment"] is None
    assert amounts["total"] == cumulative
    assert amounts["previous_certificates"] == previous_total
    assert amounts["this_certificate"] == this
    assert amounts["vat"] == vat
    assert amounts["accrued"] == this + vat
    assert amounts["income_tax"] == income
    assert amounts["stamp_duty"] == stamp
    assert amounts["vat_withholding"] == withheld
    assert amounts["advance_recovery"] == D(advance)
    assert amounts["retention"] == retention
    assert amounts["deductions_total"] == deductions
    assert amounts["payable"] == this + vat - deductions
    assert D(view["carried_total"]) == cumulative
    assert view["header"]["certificate_number"] == number
    assert not [line["key"] for line in view["summary"] if line["status"] == "held"]


async def test_three_unit_price_certificates_chain_and_the_final_one_lands_on_the_contract(session) -> None:
    project = await _project(session)
    contract = await _contract(session, project)
    lines = await _bill(session, contract)
    svc = ContractsService(session)

    views = []
    previous_total = D("0")
    for number, advance in ((1, "100000.00"), (2, "250000.00"), (3, "0.00")):
        view = await _whole_certificate(session, svc, contract, lines, number, advance=advance)
        _check_sheet(view, number=number, previous_total=previous_total, advance=advance)
        previous_total = D(view["carried_total"])
        views.append(view)

    # What one certificate carries, the next states as previous: read off the
    # two sheets, not recomputed.
    for earlier, later in zip(views, views[1:], strict=False):
        assert _amounts(later)["previous_certificates"] == D(earlier["carried_total"])
        assert D(later["works"]["totals"]["previous_amount"]) == D(earlier["works"]["totals"]["cumulative_amount"])

    final = views[-1]
    assert final["header"]["is_final"] is True
    assert views[0]["header"]["is_final"] is False
    assert _amounts(final)["work_done"] == CONTRACT_VALUE
    assert D(final["works"]["totals"]["contract_amount"]) == CONTRACT_VALUE
    assert sum((_amounts(view)["this_certificate"] for view in views), D("0")) == CONTRACT_VALUE
    assert final["flavour"] == "unit_price"
    assert final["taxes"]["direction"] == "borne_by_us"
    # Every bill row is on the sheet, in the bill's order.
    # The order is the payment application's own, by item code.
    printed = [cell for row in final["works"]["rows"] for cell in row["cells"]]
    positions = [printed.index(code) for code in sorted(row[0] for row in BILL)]
    assert positions == sorted(positions)


async def test_the_certificate_and_the_payment_application_state_one_value_of_work(session) -> None:
    project = await _project(session)
    contract = await _contract(session, project)
    lines = await _bill(session, contract)
    svc = ContractsService(session)
    await _whole_certificate(session, svc, contract, lines, 1, advance="0.00")
    second = await _measure(svc, await _claim(session, contract, 2), lines, 2)

    view = await svc.hakedis_view(second.id, locale="en")
    application = await svc._build_payment_application(second.id, locale="en", require_aia=False)
    summary = application["summary"]
    totals = view["works"]["totals"]
    assert D(totals["cumulative_amount"]) == D(str(summary["total_completed_stored"]))
    assert D(totals["period_amount"]) == sum((D(str(row["this_period_value"])) for row in application["lines"]), D("0"))
    assert D(totals["previous_amount"]) == sum((D(str(row["previous_value"])) for row in application["lines"]), D("0"))
    assert D(totals["period_amount"]) == D(str(second.gross_amount)) == _period_value(2)
    assert _amounts(view)["work_done"] == D(totals["cumulative_amount"])
    assert "hakedis.work_value_differs" not in _failed(view)


async def test_a_lump_sum_contract_prints_percentages_and_lands_on_its_price(session) -> None:
    project = await _project(session)
    contract = await _contract(session, project, contract_type="lump_sum")
    lines = await _bill(session, contract)
    svc = ContractsService(session)

    previous_total = D("0")
    views = []
    for number in (1, 2, 3):
        view = await _whole_certificate(session, svc, contract, lines, number, advance="0.00", lump_sum=True)
        amounts = _amounts(view)
        assert amounts["previous_certificates"] == previous_total
        assert amounts["this_certificate"] == amounts["total"] - previous_total
        previous_total = D(view["carried_total"])
        views.append(view)

    assert views[0]["flavour"] == "lump_sum"
    assert [_amounts(view)["work_done"] for view in views] == [
        q(CONTRACT_VALUE * D("30") / 100),
        q(CONTRACT_VALUE * D("70") / 100),
        CONTRACT_VALUE,
    ]
    assert "hakedis.weights_sum" not in _failed(views[-1])


async def test_certification_is_refused_until_the_sheet_is_complete_taxed_and_confirmed(session) -> None:
    project = await _project(session)
    contract = await _contract(session, project)
    lines = await _bill(session, contract)
    svc = ContractsService(session)
    claim = await _measure(svc, await _claim(session, contract, 1), lines, 1)
    for target in ("submitted", "approved"):
        await svc.transition_claim(claim.id, target, actor_id=str(OWNER_ID))

    async def refused() -> set[str]:
        with pytest.raises(HTTPException) as caught:
            await svc.transition_claim(claim.id, "certified", actor_id=str(OWNER_ID))
        assert caught.value.status_code == 422
        assert caught.value.detail["error"] == "hakedis_not_ready"
        reloaded = await svc.claim_repo.get_by_id(claim.id)
        assert reloaded.status == "approved"
        # Warnings travel with the refusal but are not what refuses.
        return {f["rule_id"] for f in caught.value.detail["findings"] if f["severity"] == "error"}

    # Manual lines open: the sheet says which, and nothing can be taxed yet.
    opened = await svc.hakedis_view(claim.id, locale="tr")
    assert _line(opened, "advance_recovery")["status"] == "held"
    assert _line(opened, "advance_recovery")["reason_key"] == "not_entered"
    assert opened["can_certify"] is False
    assert "hakedis.lines_complete" in await refused()

    await _enter_manual_lines(svc, claim.id, advance="50000.00")
    untaxed = await svc.hakedis_view(claim.id, locale="tr")
    assert untaxed["taxes"]["stored"] is False
    assert _line(untaxed, "vat")["reason_key"] == "taxes_not_stored"
    assert "hakedis.lines_complete" in await refused()

    await svc.save_hakedis_taxes(claim.id, TAX_CHOICES, str(OWNER_ID))
    drafted = await svc.hakedis_view(claim.id, locale="tr")
    assert drafted["taxes"]["status"] == "draft"
    assert drafted["is_draft"] is True
    assert _amounts(drafted)["vat"] is not None
    assert await refused() == {"hakedis.taxes_confirmed"}

    # The advance changes after the taxes were computed: the stamp duty base
    # moved, so the stored figures no longer belong to this sheet.
    await svc.save_hakedis_line(
        claim.id, "advance_recovery", HakedisLineInput(state="value", amount=D("60000.00")), str(OWNER_ID)
    )
    stale = await svc.hakedis_view(claim.id, locale="tr")
    assert stale["taxes"]["stale"] is True
    assert _line(stale, "stamp_duty")["status"] == "held"
    assert "hakedis.taxes_stale" in await refused()

    # Sending no choices recalculates on the sheet's current amounts.
    await svc.save_hakedis_taxes(claim.id, HakedisTaxesInput(), str(OWNER_ID))
    fresh = await svc.hakedis_view(claim.id, locale="tr")
    assert fresh["taxes"]["stale"] is False
    assert fresh["taxes"]["choices"]["stamp_duty"] == {"state": "selected", "code": "S1", "reason": ""}
    assert _amounts(fresh)["stamp_duty"] == q((_period_value(1) - D("60000.00")) * SYNTHETIC_STAMP_PCT / 100)

    await _confirm_taxes(session, claim.id)
    certified = await svc.transition_claim(claim.id, "certified", actor_id=str(OWNER_ID))
    assert certified.status == "certified"
    assert (await svc.hakedis_view(claim.id, locale="tr"))["frozen"] is True


async def test_a_certified_sheet_reads_the_same_after_everything_behind_it_changed(session, rates) -> None:
    project = await _project(session)
    contract = await _contract(session, project)
    lines = await _bill(session, contract)
    svc = ContractsService(session)
    await _whole_certificate(session, svc, contract, lines, 1, advance="100000.00")
    first = (await session.execute(select(ProgressClaim).where(ProgressClaim.contract_id == contract.id))).scalar_one()
    before = {locale: await svc.hakedis_view(first.id, locale=locale) for locale in ("tr", "en", "tr-en")}

    # The rate table, the VAT rate, the bill and the contract all move.
    rates.rows = _rows(income=D("9"), stamp=D("3"))
    rates.vat = D("5")
    lines[0].unit_rate = D("999.99")
    lines[0].description = "Changed after certification"
    contract.retention_percent = D("3")
    contract.title = "Renamed contract"
    await session.flush()

    after = {locale: await svc.hakedis_view(first.id, locale=locale) for locale in ("tr", "en", "tr-en")}
    assert after == before
    assert _amounts(after["tr"])["income_tax"] == q(_period_value(1) * SYNTHETIC_INCOME_PCT / 100)

    # A frozen sheet cannot be edited, and freezing wrote one row per line
    # plus the document itself.
    for call in (
        svc.save_hakedis_line(first.id, "advance_recovery", HakedisLineInput(state="unset"), str(OWNER_ID)),
        svc.save_hakedis_taxes(first.id, HakedisTaxesInput(), str(OWNER_ID)),
        svc.save_hakedis_options(first.id, HakedisOptionsInput(is_final=True), str(OWNER_ID)),
    ):
        with pytest.raises(HTTPException) as refused:
            await call
        assert refused.value.status_code == 409
        assert refused.value.detail["error"] == "hakedis_not_editable"
    frozen_rows = await session.scalar(
        select(func.count())
        .select_from(CertificateLine)
        .where(CertificateLine.source_id == first.id, CertificateLine.frozen.is_(True))
    )
    assert frozen_rows == len(before["tr"]["summary"]) + 1


async def test_the_next_certificate_waits_for_the_previous_one(session) -> None:
    project = await _project(session)
    contract = await _contract(session, project)
    lines = await _bill(session, contract)
    svc = ContractsService(session)
    first = await _measure(svc, await _claim(session, contract, 1), lines, 1)
    # A draft has not left the contractor and is no certificate at all; one
    # that was submitted is, and it is not certified yet.
    first = await svc.transition_claim(first.id, "submitted", actor_id=str(OWNER_ID))
    second = await _measure(svc, await _claim(session, contract, 2), lines, 2)

    view = await svc.hakedis_view(second.id, locale="en")
    previous = _line(view, "previous_certificates")
    assert (previous["status"], previous["reason_key"]) == ("held", "previous_not_certified")
    assert previous["enterable"] is False
    assert "hakedis.previous_unknown" in _failed(view)
    assert view["can_certify"] is False
    # Nor can anybody type a total over a certificate that is still open.
    with pytest.raises(HTTPException) as refused:
        await svc.save_hakedis_line(
            second.id, "previous_certificates", HakedisLineInput(state="value", amount=D("1.00")), str(OWNER_ID)
        )
    assert refused.value.status_code == 409
    assert refused.value.detail["error"] == "hakedis_previous_not_certified"
    assert first.status == "submitted"


async def test_a_project_outside_the_certificate_countries_is_left_alone(session) -> None:
    project = await _project(session, country="DE")
    contract = await _contract(session, project, contract_type="lump_sum")
    lines = await _bill(session, contract)
    svc = ContractsService(session)
    claim = await _measure(svc, await _claim(session, contract, 1), lines, 1, lump_sum=True)

    with pytest.raises(HTTPException) as absent:
        await svc.hakedis_view(claim.id, locale="tr")
    assert absent.value.status_code == 404
    assert absent.value.detail["error"] == "hakedis_not_available"
    with pytest.raises(HTTPException) as no_entry:
        await svc.save_hakedis_line(claim.id, "advance_recovery", HakedisLineInput(state="unset"), str(OWNER_ID))
    assert no_entry.value.status_code == 404

    # It certifies exactly as before: no certificate gate, nothing frozen.
    certified = await _certify(svc, claim.id)
    assert certified.status == "certified"
    stored = await session.scalar(
        select(func.count()).select_from(CertificateLine).where(CertificateLine.source_id == claim.id)
    )
    assert stored == 0
