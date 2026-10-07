# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tests for the AIA G702/G703 payment-application vertical.

Two layers:

* pure G703 line math and G702 roll-up against hand-computed fixtures (no DB);
* the country gate: an AIA-eligible (US) project builds the application, a
  non-eligible (DE) project gets a 404 from the same service call.

The pure tests need no database; the gate tests use the canonical
``transactional_session`` isolation primitive (one rolled-back outer
transaction per test) against the embedded PostgreSQL the suite boots.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.modules.contracts.aia import (
    apply_retention_snapshot,
    build_g702_summary,
    build_g703,
    build_g703_line,
    is_aia_eligible,
    normalise_country,
)
from app.modules.contracts.models import Contract, ContractLine, ProgressClaim, ProgressClaimLine
from app.modules.contracts.service import ContractsService
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

OWNER_ID = uuid.uuid4()


# ── Fakes for the pure builders ──────────────────────────────────────────


class _FakeContractLine:
    def __init__(self, code: str, description: str, total: str) -> None:
        self.id = uuid.uuid4()
        self.code = code
        self.description = description
        self.total_value = Decimal(total)


class _FakeClaimLine:
    def __init__(
        self,
        period: str,
        *,
        prior: str | None = None,
        stored: str | None = None,
        cumulative: str | None = None,
    ) -> None:
        self.period_completed_value = Decimal(period)
        self.prior_completed_value = Decimal(prior) if prior is not None else None
        self.materials_stored_value = Decimal(stored) if stored is not None else None
        self.cumulative_completed_value = Decimal(cumulative) if cumulative is not None else None
        self.metadata_ = {}


# ── Country gate (pure) ──────────────────────────────────────────────────


def test_normalise_country_codes_and_names() -> None:
    assert normalise_country("US") == "US"
    assert normalise_country("usa") == "US"
    assert normalise_country("United States") == "US"
    assert normalise_country("Canada") == "CA"
    assert normalise_country("australia") == "AU"
    assert normalise_country("DE") == "DE"
    assert normalise_country("") is None
    assert normalise_country(None) is None


def test_is_aia_eligible_gate() -> None:
    assert is_aia_eligible("US") is True
    assert is_aia_eligible("CA") is True
    assert is_aia_eligible("AU") is True
    # Non-eligible countries
    assert is_aia_eligible("DE") is False
    assert is_aia_eligible("GB") is False
    assert is_aia_eligible("FR") is False
    # Fall back to the address display name when code is blank
    assert is_aia_eligible("", {"country": "United States"}) is True
    assert is_aia_eligible("", {"country": "Germany"}) is False
    assert is_aia_eligible(None, None) is False


# ── G703 line math (pure) ─────────────────────────────────────────────────


def test_g703_line_math_with_explicit_prior_and_stored() -> None:
    cl = _FakeContractLine("01", "Foundations", "10000")
    pcl = _FakeClaimLine("2000", prior="3000", stored="500")
    row = build_g703_line(cl, pcl, line_number=1, retainage_percent=Decimal("5"))

    assert row["scheduled_value"] == Decimal("10000.00")
    assert row["previous_value"] == Decimal("3000.00")
    assert row["this_period_value"] == Decimal("2000.00")
    assert row["materials_stored"] == Decimal("500.00")
    # G = D + E + F = 3000 + 2000 + 500 = 5500
    assert row["total_completed_stored"] == Decimal("5500.00")
    # G/C = 5500/10000 = 55%
    assert row["percent_complete"] == Decimal("55.00")
    # H = C - G = 4500
    assert row["balance_to_finish"] == Decimal("4500.00")
    # I = 5% * 5500 = 275
    assert row["retainage"] == Decimal("275.00")


def test_g703_line_derives_prior_from_cumulative() -> None:
    cl = _FakeContractLine("02", "Framing", "8000")
    # No explicit prior; cumulative 5000, this period 2000 -> prior 3000.
    pcl = _FakeClaimLine("2000", cumulative="5000")
    row = build_g703_line(cl, pcl, line_number=1, retainage_percent=Decimal("10"))

    assert row["previous_value"] == Decimal("3000.00")
    assert row["this_period_value"] == Decimal("2000.00")
    assert row["total_completed_stored"] == Decimal("5000.00")
    assert row["retainage"] == Decimal("500.00")  # 10% of 5000


def test_g703_line_unbilled_line_is_zero() -> None:
    cl = _FakeContractLine("03", "Roofing", "4000")
    row = build_g703_line(cl, None, line_number=1, retainage_percent=Decimal("5"))
    assert row["this_period_value"] == Decimal("0.00")
    assert row["total_completed_stored"] == Decimal("0.00")
    assert row["balance_to_finish"] == Decimal("4000.00")
    assert row["percent_complete"] == Decimal("0.00")


# ── G702 summary roll-up (pure) ───────────────────────────────────────────


def test_g702_summary_rollup() -> None:
    cl = _FakeContractLine("01", "Foundations", "10000")
    pcl = _FakeClaimLine("2000", prior="3000", stored="500")
    rows = build_g703([cl], {cl.id: pcl}, retainage_percent=Decimal("5"))

    summary = build_g702_summary(
        rows,
        original_contract_sum=Decimal("10000"),
        change_orders_net=Decimal("0"),
        previous_certificates_total=Decimal("2850"),
    )
    assert summary["contract_sum_to_date"] == Decimal("10000.00")
    assert summary["total_completed_stored"] == Decimal("5500.00")
    assert summary["retainage"] == Decimal("275.00")
    # 6 = 4 - 5 = 5225
    assert summary["total_earned_less_retainage"] == Decimal("5225.00")
    # 8 = 6 - 7 = 5225 - 2850 = 2375
    assert summary["current_payment_due"] == Decimal("2375.00")
    # 9 = 3 - 6 = 10000 - 5225 = 4775
    assert summary["balance_to_finish"] == Decimal("4775.00")


def test_g702_splits_retainage_into_completed_work_and_stored_material() -> None:
    cl = _FakeContractLine("01", "Foundations", "10000")
    pcl = _FakeClaimLine("2000", prior="3000", stored="500")
    rows = build_g703([cl], {cl.id: pcl}, retainage_percent=Decimal("5"))
    summary = build_g702_summary(rows, original_contract_sum=Decimal("10000"), change_orders_net=Decimal("0"))
    # 5% of 5,000 of work and of 500 stored.
    assert (summary["retainage_completed_work"], summary["retainage_stored_materials"]) == (
        Decimal("250.00"),
        Decimal("25.00"),
    )


def test_column_i_is_the_claims_line_5_and_the_lines_it_does_not_bill_take_the_rest() -> None:
    a = _FakeContractLine("01", "Foundations", "6000")
    b = _FakeContractLine("02", "Framing", "4000")
    pcl = _FakeClaimLine("1000", prior="2000", stored="500")
    pcl.retention_to_date = Decimal("270")
    pcl.retention_stored_to_date = Decimal("50")
    rows = build_g703([a, b], {a.id: pcl}, retainage_percent=Decimal("10"), prior_by_line={b.id: Decimal("1000")})
    # Framing is not billed this period, and still counts what it billed before.
    assert rows[1]["previous_value"] == Decimal("1000.00")

    apply_retention_snapshot(rows, [a, b], {a.id: pcl}, held=Decimal("400"))
    assert [row["retainage"] for row in rows] == [Decimal("320.00"), Decimal("80.00")]
    assert (rows[0]["retainage_completed_work"], rows[0]["retainage_stored_materials"]) == (
        Decimal("270.00"),
        Decimal("50.00"),
    )
    summary = build_g702_summary(rows, original_contract_sum=Decimal("10000"), change_orders_net=Decimal("0"))
    assert summary["retainage"] == Decimal("400.00")
    assert (summary["retainage_completed_work"], summary["retainage_stored_materials"]) == (
        Decimal("350.00"),
        Decimal("50.00"),
    )


def test_g702_current_payment_due_floors_at_zero() -> None:
    # Previous certificates exceed earned-less-retainage -> current due clamps.
    summary = build_g702_summary(
        [],
        original_contract_sum=Decimal("10000"),
        change_orders_net=Decimal("0"),
        previous_certificates_total=Decimal("500"),
    )
    assert summary["total_earned_less_retainage"] == Decimal("0.00")
    assert summary["current_payment_due"] == Decimal("0.00")


def test_g702_change_orders_lift_contract_sum() -> None:
    cl = _FakeContractLine("01", "Site work", "10000")
    pcl = _FakeClaimLine("1000")
    rows = build_g703([cl], {cl.id: pcl}, retainage_percent=Decimal("0"))
    summary = build_g702_summary(
        rows,
        original_contract_sum=Decimal("10000"),
        change_orders_net=Decimal("2000"),
    )
    assert summary["contract_sum_to_date"] == Decimal("12000.00")
    assert summary["balance_to_finish"] == Decimal("11000.00")  # 12000 - 1000


# ── DB-backed country gate on the service ─────────────────────────────────


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        s.add(User(id=OWNER_ID, email="aia-owner@test.io", hashed_password="x", full_name="Owner"))
        await s.flush()
        yield s


async def _seed_claim(s, *, country_code: str, address: dict | None = None) -> ProgressClaim:
    project = Project(
        id=uuid.uuid4(),
        name="AIA Project",
        owner_id=OWNER_ID,
        currency="USD",
        status="active",
        country_code=country_code,
        address=address,
        metadata_={},
    )
    s.add(project)
    await s.flush()

    contract = Contract(
        id=uuid.uuid4(),
        code=f"C-{uuid.uuid4().hex[:8]}",
        title="Main works",
        project_id=project.id,
        currency="USD",
        total_value=Decimal("10000"),
        retention_percent=Decimal("5"),
        status="active",
    )
    s.add(contract)
    await s.flush()

    line = ContractLine(
        id=uuid.uuid4(),
        contract_id=contract.id,
        code="01",
        description="Foundations",
        quantity=Decimal("1"),
        unit_rate=Decimal("10000"),
        total_value=Decimal("10000"),
        metadata_={},
    )
    s.add(line)
    await s.flush()

    claim = ProgressClaim(
        id=uuid.uuid4(),
        contract_id=contract.id,
        claim_number="PC-1",
        currency="USD",
        status="draft",
    )
    s.add(claim)
    await s.flush()

    claim_line = ProgressClaimLine(
        id=uuid.uuid4(),
        progress_claim_id=claim.id,
        contract_line_id=line.id,
        period_completed_qty=Decimal("0.5"),
        period_completed_value=Decimal("5000"),
        period_completed_pct=Decimal("50"),
        cumulative_completed_value=Decimal("5000"),
    )
    s.add(claim_line)
    await s.flush()
    return claim


@pytest.mark.asyncio
async def test_aia_application_built_for_us_project(session) -> None:
    claim = await _seed_claim(session, country_code="US")
    svc = ContractsService(session)
    app = await svc.build_aia_application(claim.id)

    assert app["currency"] == "USD"
    assert len(app["lines"]) == 1
    row = app["lines"][0]
    assert row["scheduled_value"] == Decimal("10000.00")
    assert row["this_period_value"] == Decimal("5000.00")
    assert row["retainage"] == Decimal("250.00")  # 5% of 5000
    assert app["summary"]["total_earned_less_retainage"] == Decimal("4750.00")


@pytest.mark.asyncio
async def test_aia_application_built_via_address_name(session) -> None:
    # country_code blank-ish (DE default would block), but address says Canada.
    claim = await _seed_claim(session, country_code="CA")
    svc = ContractsService(session)
    app = await svc.build_aia_application(claim.id)
    assert app["summary"]["total_completed_stored"] == Decimal("5000.00")


@pytest.mark.asyncio
async def test_aia_application_404_for_non_us_project(session) -> None:
    claim = await _seed_claim(session, country_code="DE")
    svc = ContractsService(session)
    with pytest.raises(HTTPException) as exc:
        await svc.build_aia_application(claim.id)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("country", ["DE", "GB", "", "US", "CA", "AU"])
async def test_canonical_payment_application_preserves_claim_figures(session, country) -> None:
    claim = await _seed_claim(session, country_code=country)
    service = ContractsService(session)
    application = await service.build_payment_application(claim.id)
    assert application["claim_id"] == claim.id
    assert application["currency"] == "USD"
    assert application["summary"]["total_earned_less_retainage"] == Decimal("4750.00")
    assert application["lines"][0]["retainage"] == Decimal("250.00")
    if country in {"US", "CA", "AU"}:
        assert application == await service.build_aia_application(claim.id)
    else:
        with pytest.raises(HTTPException) as exc:
            await service.build_aia_application(claim.id)
        assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_canonical_payment_application_missing_claim(session) -> None:
    with pytest.raises(HTTPException) as exc:
        await ContractsService(session).build_payment_application(uuid.uuid4())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_canonical_route_enforces_project_ownership(session) -> None:
    from app.modules.contracts.router import get_payment_application

    claim = await _seed_claim(session, country_code="DE")
    owner_view = await get_payment_application(claim.id, session, str(OWNER_ID), None)
    assert owner_view.claim_id == claim.id
    assert owner_view.summary.total_earned_less_retainage == Decimal("4750.00")

    outsider_id = uuid.uuid4()
    session.add(User(id=outsider_id, email="outsider@test.io", hashed_password="x", role="manager"))
    await session.flush()
    with pytest.raises(HTTPException) as exc:
        await get_payment_application(claim.id, session, str(outsider_id), None)
    assert exc.value.status_code == 404
