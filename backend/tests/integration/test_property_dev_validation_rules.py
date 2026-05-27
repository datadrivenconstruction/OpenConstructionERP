# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Integration tests for property_dev ValidationRules + regulator reports
+ cross-module event subscribers (task #139).

Covers:
    * 8 ValidationRule classes — seed minimal rows, run, assert pass/fail.
      Each rule has a happy-path test + a violation-path test = 16 rule tests.
    * 4 regulator report generators — assert ``%PDF`` magic + parseable payload.
    * 3 cross-module event subscribers — publish source event, assert side
      effect.
    * 5 IDOR / RBAC tests on the compliance endpoints.

Test isolation: pointed at a per-module temp SQLite (see
``feedback_test_isolation.md``).
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path

# ── Per-module SQLite isolation (MUST run BEFORE app imports) ─────────────

_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-propdev-rules-"))
_TMP_DB = _TMP_DIR / "propdev_rules.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"
# Skip the slow seed phases — tests don't need them and they 2x the boot time.
os.environ.setdefault("SEED_DEMO", "false")
os.environ.setdefault("SEED_SHOWCASE", "false")

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

# ── App + DB fixtures ──────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    """Boot the FastAPI app once per module against the temp SQLite."""
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.property_dev import models as _pd_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield app


@pytest_asyncio.fixture(scope="module")
async def client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def session(app_instance):
    """Fresh AsyncSession bound to the temp DB."""
    from app.database import async_session_factory

    async with async_session_factory() as s:
        yield s


@pytest_asyncio.fixture
async def seeded_dev(session):
    """Create User + Project + Development + 2 plots + 1 buyer for tests."""
    import uuid as _uuid

    from app.modules.projects.models import Project
    from app.modules.property_dev.models import Buyer, Development, Plot
    from app.modules.users.models import User

    owner = User(
        id=_uuid.uuid4(),
        email=f"pd-owner-{_uuid.uuid4().hex[:6]}@test.io",
        hashed_password="x",
        full_name="PropDev Owner",
        role="admin",
    )
    session.add(owner)
    await session.flush()

    proj = Project(
        id=_uuid.uuid4(),
        name=f"PD test {_uuid.uuid4().hex[:6]}",
        description="",
        owner_id=owner.id,
    )
    session.add(proj)
    await session.flush()

    dev = Development(
        id=_uuid.uuid4(),
        project_id=proj.id,
        code=f"PD-{_uuid.uuid4().hex[:8].upper()}",
        name="Oak Park",
        sales_phase="sales",
        status="active",
        units="metric",
        metadata_={
            "jurisdiction": "AE",
            "regulator": "RERA",
            "rera_registration_number": "RERA-12345",
            "maharera_registration_number": "P1234567890",
            "fz214_project_id": "EISZS-001",
            "cma_licence_no": "WAFI-2026-007",
            "authorised_signatory": "Test Signatory",
        },
    )
    session.add(dev)
    await session.flush()

    plot_a = Plot(
        id=_uuid.uuid4(),
        development_id=dev.id,
        plot_number="A-01",
        area_m2=Decimal("100"),
        price_base=Decimal("500000"),
        currency="AED",
        status="reserved",
        construction_status_percent=Decimal("50"),
        metadata_={"kind": "residential", "carpet_area_m2": "85"},
    )
    plot_b = Plot(
        id=_uuid.uuid4(),
        development_id=dev.id,
        plot_number="A-02",
        area_m2=Decimal("120"),
        price_base=Decimal("600000"),
        currency="AED",
        status="planned",
        construction_status_percent=Decimal("30"),
        metadata_={"kind": "residential"},
    )
    session.add_all([plot_a, plot_b])
    await session.flush()

    buyer_email = f"jane-{_uuid.uuid4().hex[:8]}@example.com"
    buyer = Buyer(
        id=_uuid.uuid4(),
        development_id=dev.id,
        plot_id=plot_a.id,
        full_name="Jane Buyer",
        email=buyer_email,
        status="contracted",
        contract_value=Decimal("500000"),
        currency="AED",
        contract_signed_at="2026-05-10",
        deposit_paid_at="2026-05-12",
        deposit_amount=Decimal("50000"),
        jurisdiction="AE",
    )
    session.add(buyer)
    await session.commit()
    return {
        "owner": owner,
        "project": proj,
        "development": dev,
        "plot_a": plot_a,
        "plot_b": plot_b,
        "buyer": buyer,
    }


async def _run_rule(rule, session, dev_id):
    """Execute a single ValidationRule and return the result list."""
    from app.core.validation.engine import ValidationContext

    ctx = ValidationContext(
        data={},
        project_id=str(dev_id),
        metadata={
            "session": session,
            "development_id": str(dev_id),
            "locale": "en",
        },
    )
    return await rule.validate(ctx)


# ─────────────────────────────────────────────────────────────────────────
# Rule 1: escrow_account_required
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rule_escrow_account_required_fails_without_account(session, seeded_dev):
    """RERA jurisdiction without an EscrowAccount → ERROR."""
    from app.core.validation.rules import PropDevEscrowAccountRequired

    dev = seeded_dev["development"]
    rule = PropDevEscrowAccountRequired()
    results = await _run_rule(rule, session, dev.id)
    assert results, "expected at least one result"
    failed = [r for r in results if not r.passed]
    assert failed, "expected ERROR for missing escrow"
    assert "RERA" in failed[0].details.get("regulator", "")


@pytest.mark.asyncio
async def test_rule_escrow_account_required_passes_with_active_account(session, seeded_dev):
    """Adding an active EscrowAccount makes the rule pass."""
    import uuid as _uuid

    from app.core.validation.rules import PropDevEscrowAccountRequired
    from app.modules.property_dev.models import EscrowAccount

    dev = seeded_dev["development"]
    acc = EscrowAccount(
        id=_uuid.uuid4(),
        development_id=dev.id,
        regulator_ref="RERA",
        regulator_account_number="RERA-001",
        bank_name="Emirates NBD",
        iban="AE070331234567890123456",
        swift_bic="EBILAEAD",
        currency="AED",
        opened_at="2026-01-01",
        is_active=True,
    )
    session.add(acc)
    await session.flush()
    rule = PropDevEscrowAccountRequired()
    results = await _run_rule(rule, session, dev.id)
    assert all(r.passed for r in results), "expected pass after escrow added"


# ─────────────────────────────────────────────────────────────────────────
# Rule 2: escrow_iban_valid
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rule_escrow_iban_valid_fails_bad_checksum(session, seeded_dev):
    """An IBAN with broken mod-97 checksum triggers ERROR."""
    import uuid as _uuid

    from app.core.validation.rules import PropDevEscrowIBANValid
    from app.modules.property_dev.models import EscrowAccount

    dev = seeded_dev["development"]
    acc = EscrowAccount(
        id=_uuid.uuid4(),
        development_id=dev.id,
        regulator_ref="RERA",
        bank_name="Bank X",
        iban="AE99XX12-NOT-A-VALID-IBAN-999",  # bad
        currency="AED",
        opened_at="2026-01-01",
        is_active=True,
    )
    session.add(acc)
    await session.flush()
    rule = PropDevEscrowIBANValid()
    results = await _run_rule(rule, session, dev.id)
    failed = [r for r in results if not r.passed]
    assert failed, "expected IBAN failure"


@pytest.mark.asyncio
async def test_rule_escrow_iban_valid_passes_with_valid_iban(session, seeded_dev):
    """A structurally valid German IBAN passes the check."""
    import uuid as _uuid

    from app.core.validation.rules import PropDevEscrowIBANValid
    from app.modules.property_dev.models import EscrowAccount

    dev = seeded_dev["development"]
    acc = EscrowAccount(
        id=_uuid.uuid4(),
        development_id=dev.id,
        regulator_ref="RERA",
        bank_name="Deutsche Bank",
        # Known-valid DE IBAN (DE89 3704 0044 0532 0130 00).
        iban="DE89370400440532013000",
        currency="EUR",
        opened_at="2026-01-01",
        is_active=True,
    )
    session.add(acc)
    await session.flush()
    rule = PropDevEscrowIBANValid()
    results = await _run_rule(rule, session, dev.id)
    assert all(r.passed for r in results), "DE IBAN must pass"


# ─────────────────────────────────────────────────────────────────────────
# Rule 3: escrow_balance_reconciled
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rule_escrow_balance_reconciled_flags_drift(session, seeded_dev):
    """Declared ledger far from transaction sum → WARNING."""
    import uuid as _uuid

    from app.core.validation.rules import PropDevEscrowBalanceReconciled
    from app.modules.property_dev.models import EscrowAccount, EscrowTransaction

    dev = seeded_dev["development"]
    acc = EscrowAccount(
        id=_uuid.uuid4(),
        development_id=dev.id,
        regulator_ref="RERA",
        bank_name="Bank X",
        iban="AE070331234567890123456",
        currency="AED",
        opened_at="2026-01-01",
        is_active=True,
        metadata_={"ledger_balance": "1000.00"},  # declared
    )
    session.add(acc)
    await session.flush()
    tx = EscrowTransaction(
        id=_uuid.uuid4(),
        escrow_account_id=acc.id,
        direction="credit",
        amount=Decimal("500.00"),
        currency="AED",
        source_type="instalment",
        transaction_date="2026-05-01",
    )
    session.add(tx)
    await session.flush()
    rule = PropDevEscrowBalanceReconciled()
    results = await _run_rule(rule, session, dev.id)
    failed = [r for r in results if not r.passed]
    assert failed, "expected drift warning"


@pytest.mark.asyncio
async def test_rule_escrow_balance_reconciled_passes_when_matches(session, seeded_dev):
    """Declared ledger matches transaction sum → pass."""
    import uuid as _uuid

    from app.core.validation.rules import PropDevEscrowBalanceReconciled
    from app.modules.property_dev.models import EscrowAccount, EscrowTransaction

    dev = seeded_dev["development"]
    acc = EscrowAccount(
        id=_uuid.uuid4(),
        development_id=dev.id,
        regulator_ref="RERA",
        bank_name="Bank X",
        iban="AE070331234567890123456",
        currency="AED",
        opened_at="2026-01-01",
        is_active=True,
        metadata_={"ledger_balance": "500.00"},
    )
    session.add(acc)
    await session.flush()
    tx = EscrowTransaction(
        id=_uuid.uuid4(),
        escrow_account_id=acc.id,
        direction="credit",
        amount=Decimal("500.00"),
        currency="AED",
        source_type="instalment",
        transaction_date="2026-05-01",
    )
    session.add(tx)
    await session.flush()
    rule = PropDevEscrowBalanceReconciled()
    results = await _run_rule(rule, session, dev.id)
    assert all(r.passed for r in results), "balanced ledger must pass"


# ─────────────────────────────────────────────────────────────────────────
# Rule 4: sales_contract_party_ownership_sums_to_100
# ─────────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def seeded_spa(session, seeded_dev):
    """Create a SalesContract on plot_a for ownership/instalment tests."""
    import uuid as _uuid

    from app.modules.property_dev.models import SalesContract

    dev = seeded_dev["development"]
    plot = seeded_dev["plot_a"]
    spa = SalesContract(
        id=_uuid.uuid4(),
        contract_number=f"SPA-{dev.code}-00001",
        plot_id=plot.id,
        signing_date="2026-05-20",
        governing_law="AE-DU",
        language="en",
        total_value=Decimal("500000"),
        currency="AED",
        status="signed",
        revision_number=1,
        terms_version="spa-v1.0",
    )
    session.add(spa)
    await session.commit()
    return spa


@pytest.mark.asyncio
async def test_rule_party_ownership_passes_when_summing_100(session, seeded_dev, seeded_spa):
    """Two parties at 60+40 sum to 100% → pass."""
    import uuid as _uuid

    from app.core.validation.rules import (
        PropDevSalesContractPartyOwnershipSumsTo100,
    )
    from app.modules.property_dev.models import Buyer, ContractParty

    dev = seeded_dev["development"]
    buyer1 = seeded_dev["buyer"]
    buyer2 = Buyer(
        id=_uuid.uuid4(),
        development_id=dev.id,
        plot_id=seeded_dev["plot_a"].id,
        full_name="Co-owner",
        email="co@example.com",
        status="contracted",
        contract_value=Decimal("0"),
        currency="AED",
        jurisdiction="AE",
    )
    session.add(buyer2)
    await session.flush()
    p1 = ContractParty(
        id=_uuid.uuid4(),
        sales_contract_id=seeded_spa.id,
        buyer_id=buyer1.id,
        ownership_pct=Decimal("60"),
        party_role="primary",
    )
    p2 = ContractParty(
        id=_uuid.uuid4(),
        sales_contract_id=seeded_spa.id,
        buyer_id=buyer2.id,
        ownership_pct=Decimal("40"),
        party_role="co_owner",
    )
    session.add_all([p1, p2])
    await session.commit()
    rule = PropDevSalesContractPartyOwnershipSumsTo100()
    results = await _run_rule(rule, session, dev.id)
    assert all(r.passed for r in results), "60+40=100 must pass"


@pytest.mark.asyncio
async def test_rule_party_ownership_fails_when_not_summing_100(session, seeded_dev, seeded_spa):
    """A single party at 80% triggers ERROR."""
    import uuid as _uuid

    from app.core.validation.rules import (
        PropDevSalesContractPartyOwnershipSumsTo100,
    )
    from app.modules.property_dev.models import ContractParty

    dev = seeded_dev["development"]
    buyer = seeded_dev["buyer"]
    p1 = ContractParty(
        id=_uuid.uuid4(),
        sales_contract_id=seeded_spa.id,
        buyer_id=buyer.id,
        ownership_pct=Decimal("80"),
        party_role="primary",
    )
    session.add(p1)
    await session.commit()
    rule = PropDevSalesContractPartyOwnershipSumsTo100()
    results = await _run_rule(rule, session, dev.id)
    failed = [r for r in results if not r.passed]
    assert failed, "80% != 100% must fail"


# ─────────────────────────────────────────────────────────────────────────
# Rule 5: payment_schedule_instalments_sum_to_contract_value
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rule_instalments_sum_passes_when_matching(session, seeded_dev, seeded_spa):
    """Two instalments at 250k each sum to contract.total_value=500k → pass."""
    import uuid as _uuid

    from app.core.validation.rules import (
        PropDevPaymentScheduleInstalmentsSumToContractValue,
    )
    from app.modules.property_dev.models import Instalment, PaymentSchedule

    dev = seeded_dev["development"]
    sched = PaymentSchedule(
        id=_uuid.uuid4(),
        sales_contract_id=seeded_spa.id,
        currency="AED",
        total_amount=Decimal("500000"),
    )
    session.add(sched)
    await session.flush()
    i1 = Instalment(
        id=_uuid.uuid4(),
        schedule_id=sched.id,
        sequence=1,
        amount=Decimal("250000"),
        milestone_label="Reservation",
        milestone_event="reservation",
    )
    i2 = Instalment(
        id=_uuid.uuid4(),
        schedule_id=sched.id,
        sequence=2,
        amount=Decimal("250000"),
        milestone_label="Handover",
        milestone_event="handover",
    )
    session.add_all([i1, i2])
    await session.commit()
    rule = PropDevPaymentScheduleInstalmentsSumToContractValue()
    results = await _run_rule(rule, session, dev.id)
    assert all(r.passed for r in results), "instalments=total must pass"


@pytest.mark.asyncio
async def test_rule_instalments_sum_fails_on_mismatch(session, seeded_dev, seeded_spa):
    """Instalments summing to less than contract value → ERROR."""
    import uuid as _uuid

    from app.core.validation.rules import (
        PropDevPaymentScheduleInstalmentsSumToContractValue,
    )
    from app.modules.property_dev.models import Instalment, PaymentSchedule

    dev = seeded_dev["development"]
    sched = PaymentSchedule(
        id=_uuid.uuid4(),
        sales_contract_id=seeded_spa.id,
        currency="AED",
        total_amount=Decimal("500000"),
    )
    session.add(sched)
    await session.flush()
    i1 = Instalment(
        id=_uuid.uuid4(),
        schedule_id=sched.id,
        sequence=1,
        amount=Decimal("100000"),
        milestone_label="Reservation",
        milestone_event="reservation",
    )
    session.add(i1)
    await session.commit()
    rule = PropDevPaymentScheduleInstalmentsSumToContractValue()
    results = await _run_rule(rule, session, dev.id)
    failed = [r for r in results if not r.passed]
    assert failed, "100k != 500k must fail"


# ─────────────────────────────────────────────────────────────────────────
# Rule 6: reservation_expiry_in_future
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rule_reservation_expiry_passes_when_in_future(session, seeded_dev):
    """Active reservation expiring next year → pass."""
    import uuid as _uuid

    from app.core.validation.rules import PropDevReservationExpiryInFuture
    from app.modules.property_dev.models import Reservation

    dev = seeded_dev["development"]
    plot = seeded_dev["plot_a"]
    res = Reservation(
        id=_uuid.uuid4(),
        plot_id=plot.id,
        reservation_number=f"RES-{dev.code}-00001",
        deposit_amount=Decimal("50000"),
        currency="AED",
        expires_at="2099-12-31",  # far future
        status="active",
    )
    session.add(res)
    await session.commit()
    rule = PropDevReservationExpiryInFuture()
    results = await _run_rule(rule, session, dev.id)
    assert all(r.passed for r in results), "future expiry must pass"


@pytest.mark.asyncio
async def test_rule_reservation_expiry_fails_when_past(session, seeded_dev):
    """Active reservation expiring in 2020 → WARNING."""
    import uuid as _uuid

    from app.core.validation.rules import PropDevReservationExpiryInFuture
    from app.modules.property_dev.models import Reservation

    dev = seeded_dev["development"]
    plot = seeded_dev["plot_b"]
    res = Reservation(
        id=_uuid.uuid4(),
        plot_id=plot.id,
        reservation_number=f"RES-{dev.code}-00002",
        deposit_amount=Decimal("60000"),
        currency="AED",
        expires_at="2020-01-01",  # past
        status="active",
    )
    session.add(res)
    await session.commit()
    rule = PropDevReservationExpiryInFuture()
    results = await _run_rule(rule, session, dev.id)
    failed = [r for r in results if not r.passed]
    assert failed, "past expiry on active reservation must fail"


# ─────────────────────────────────────────────────────────────────────────
# Rule 7: broker_commission_rate_within_bounds
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rule_commission_passes_with_valid_percent(session, seeded_dev):
    """A 2.5% percent commission is in range."""
    import uuid as _uuid

    from app.core.validation.rules import (
        PropDevBrokerCommissionRateWithinBounds,
    )
    from app.modules.property_dev.models import Broker, CommissionAgreement

    dev = seeded_dev["development"]
    broker = Broker(
        id=_uuid.uuid4(),
        name="ACME Realty",
        license_number=f"LIC-{_uuid.uuid4().hex[:8]}",
        jurisdiction="AE-DU",
        contact_email="acme@example.com",
        kyc_status="verified",
        active=True,
    )
    session.add(broker)
    await session.flush()
    agreement = CommissionAgreement(
        id=_uuid.uuid4(),
        broker_id=broker.id,
        development_id=dev.id,
        structure_type="percent",
        structure={"pct": "2.5"},
        accrual_trigger="spa_signed",
        currency="AED",
        effective_from="2026-01-01",
        status="active",
    )
    session.add(agreement)
    await session.commit()
    rule = PropDevBrokerCommissionRateWithinBounds()
    results = await _run_rule(rule, session, dev.id)
    assert all(r.passed for r in results), "2.5% must pass"


@pytest.mark.asyncio
async def test_rule_commission_fails_with_excessive_percent(session, seeded_dev):
    """A 25% percent commission is outside the 0.1%-15% band."""
    import uuid as _uuid

    from app.core.validation.rules import (
        PropDevBrokerCommissionRateWithinBounds,
    )
    from app.modules.property_dev.models import Broker, CommissionAgreement

    dev = seeded_dev["development"]
    broker = Broker(
        id=_uuid.uuid4(),
        name="Greedy Realty",
        license_number=f"LIC-{_uuid.uuid4().hex[:8]}",
        jurisdiction="AE-DU",
        contact_email="greed@example.com",
        kyc_status="verified",
        active=True,
    )
    session.add(broker)
    await session.flush()
    agreement = CommissionAgreement(
        id=_uuid.uuid4(),
        broker_id=broker.id,
        development_id=dev.id,
        structure_type="percent",
        structure={"pct": "25"},  # 25% > 15% cap
        currency="AED",
        effective_from="2026-01-01",
        status="active",
    )
    session.add(agreement)
    await session.commit()
    rule = PropDevBrokerCommissionRateWithinBounds()
    results = await _run_rule(rule, session, dev.id)
    failed = [r for r in results if not r.passed]
    assert failed, "25% commission must fail"


# ─────────────────────────────────────────────────────────────────────────
# Rule 8: price_matrix_no_negative_modifier
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rule_price_matrix_passes_with_valid_modifiers(session, seeded_dev):
    """A matrix with multipliers in range passes."""
    import uuid as _uuid

    from app.core.validation.rules import PropDevPriceMatrixNoNegativeModifier
    from app.modules.property_dev.models import PriceMatrix

    dev = seeded_dev["development"]
    matrix = PriceMatrix(
        id=_uuid.uuid4(),
        development_id=dev.id,
        name="Standard",
        base_price_per_m2=Decimal("5000"),
        currency="AED",
        effective_from="2026-01-01",
        rules=[
            {"factor_type": "floor", "condition": {"min": 5}, "multiplier": "1.04"},
            {"factor_type": "view", "condition": {"value": "sea"}, "multiplier": "1.15"},
        ],
        status="active",
    )
    session.add(matrix)
    await session.commit()
    rule = PropDevPriceMatrixNoNegativeModifier()
    results = await _run_rule(rule, session, dev.id)
    assert all(r.passed for r in results), "modifiers in range must pass"


@pytest.mark.asyncio
async def test_rule_price_matrix_fails_with_out_of_range_modifier(session, seeded_dev):
    """A multiplier of 5.0 (out of [-0.5, 2.0]) triggers WARNING."""
    import uuid as _uuid

    from app.core.validation.rules import PropDevPriceMatrixNoNegativeModifier
    from app.modules.property_dev.models import PriceMatrix

    dev = seeded_dev["development"]
    matrix = PriceMatrix(
        id=_uuid.uuid4(),
        development_id=dev.id,
        name="Premium",
        base_price_per_m2=Decimal("5000"),
        currency="AED",
        effective_from="2026-01-01",
        rules=[
            {
                "factor_type": "penthouse",
                "condition": {"value": True},
                "multiplier": "5.0",  # absurd
            },
        ],
        status="active",
    )
    session.add(matrix)
    await session.commit()
    rule = PropDevPriceMatrixNoNegativeModifier()
    results = await _run_rule(rule, session, dev.id)
    failed = [r for r in results if not r.passed]
    assert failed, "5.0 multiplier must fail"


# ─────────────────────────────────────────────────────────────────────────
# Missing-context safety
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rules_noop_silently_without_session_or_dev_id():
    """Every rule must return [] when session/dev_id missing — never raise."""
    from app.core.validation.engine import ValidationContext
    from app.core.validation.rules import (
        PropDevBrokerCommissionRateWithinBounds,
        PropDevEscrowAccountRequired,
        PropDevEscrowBalanceReconciled,
        PropDevEscrowIBANValid,
        PropDevPaymentScheduleInstalmentsSumToContractValue,
        PropDevPriceMatrixNoNegativeModifier,
        PropDevReservationExpiryInFuture,
        PropDevSalesContractPartyOwnershipSumsTo100,
    )

    rules = [
        PropDevEscrowAccountRequired(),
        PropDevEscrowIBANValid(),
        PropDevEscrowBalanceReconciled(),
        PropDevSalesContractPartyOwnershipSumsTo100(),
        PropDevPaymentScheduleInstalmentsSumToContractValue(),
        PropDevReservationExpiryInFuture(),
        PropDevBrokerCommissionRateWithinBounds(),
        PropDevPriceMatrixNoNegativeModifier(),
    ]
    ctx = ValidationContext(data={}, metadata={})
    for r in rules:
        out = await r.validate(ctx)
        assert out == [], f"{r.rule_id} should no-op without context"


# ─────────────────────────────────────────────────────────────────────────
# Regulator report generators (PDF + payload)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_regulator_report_rera_generates_pdf_and_json(session, seeded_dev):
    """RERA report has %PDF magic and parseable JSON payload."""
    from app.modules.property_dev.regulatory import (
        generate_regulator_report_rera,
    )

    dev = seeded_dev["development"]
    report = await generate_regulator_report_rera(session, dev.id, "2026-Q2")
    assert report.pdf_bytes.startswith(b"%PDF")
    assert report.payload_format == "json"
    payload = json.loads(report.payload_bytes.decode("utf-8"))
    assert payload["regulator"] == "RERA"
    assert payload["submission"]["project_number"] == dev.code


@pytest.mark.asyncio
async def test_regulator_report_maharera_generates_pdf_and_xml(session, seeded_dev):
    """MAHARERA report has %PDF magic and parseable XML payload."""
    from app.modules.property_dev.regulatory import (
        generate_regulator_report_maharera,
    )

    dev = seeded_dev["development"]
    report = await generate_regulator_report_maharera(session, dev.id, "2026-Q2")
    assert report.pdf_bytes.startswith(b"%PDF")
    assert report.payload_format == "xml"
    root = ET.fromstring(report.payload_bytes)
    assert root.tag == "MAHARERA_Form5"


@pytest.mark.asyncio
async def test_regulator_report_214fz_generates_pdf_and_xml(session, seeded_dev):
    """214-FZ report has %PDF magic and parseable XML payload."""
    from app.modules.property_dev.regulatory import (
        generate_regulator_report_214fz,
    )

    dev = seeded_dev["development"]
    report = await generate_regulator_report_214fz(session, dev.id, "2026-Q2")
    assert report.pdf_bytes.startswith(b"%PDF")
    assert report.payload_format == "xml"
    root = ET.fromstring(report.payload_bytes)
    assert root.tag == "FZ214_QuarterlyReport"


@pytest.mark.asyncio
async def test_regulator_report_cma_generates_pdf_and_json(session, seeded_dev):
    """CMA report has %PDF magic and parseable JSON payload."""
    from app.modules.property_dev.regulatory import (
        generate_regulator_report_cma,
    )

    dev = seeded_dev["development"]
    report = await generate_regulator_report_cma(session, dev.id, "2026-Q2")
    assert report.pdf_bytes.startswith(b"%PDF")
    assert report.payload_format == "json"
    payload = json.loads(report.payload_bytes.decode("utf-8"))
    assert payload["regulator"] == "CMA"


@pytest.mark.asyncio
async def test_regulator_report_invalid_quarter_raises(session, seeded_dev):
    """Bad quarter string raises ValueError."""
    from app.modules.property_dev.regulatory import (
        generate_regulator_report,
    )

    dev = seeded_dev["development"]
    with pytest.raises(ValueError, match="Invalid quarter"):
        await generate_regulator_report(
            session,
            dev_id=dev.id,
            regulator="RERA",
            quarter="bad",
        )


@pytest.mark.asyncio
async def test_regulator_report_includes_escrow_from_table(session, seeded_dev):
    """Generated report carries the active EscrowAccount rows (not metadata)."""
    import uuid as _uuid

    from app.modules.property_dev.models import EscrowAccount
    from app.modules.property_dev.regulatory import (
        generate_regulator_report_rera,
    )

    dev = seeded_dev["development"]
    acc = EscrowAccount(
        id=_uuid.uuid4(),
        development_id=dev.id,
        regulator_ref="RERA",
        regulator_account_number="ESC-AE-123",
        bank_name="Emirates NBD",
        iban="AE070331234567890123456",
        swift_bic="EBILAEAD",
        currency="AED",
        opened_at="2026-01-01",
        is_active=True,
    )
    session.add(acc)
    await session.commit()
    report = await generate_regulator_report_rera(session, dev.id, "2026-Q2")
    payload = json.loads(report.payload_bytes.decode("utf-8"))
    accounts = payload["submission"]["escrow"]["accounts"]
    assert any(a["account_no"] == "ESC-AE-123" for a in accounts), "EscrowAccount row should appear in payload"


# ─────────────────────────────────────────────────────────────────────────
# Cross-module event subscribers (task #139)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_subscriber_crm_lead_qualified_creates_buyer(session, seeded_dev):
    """``crm.lead.qualified`` with dev_focused=True auto-creates Buyer."""
    from sqlalchemy import func, select

    from app.core.events import Event
    from app.modules.property_dev.events import _on_crm_lead_qualified
    from app.modules.property_dev.models import Buyer

    dev = seeded_dev["development"]
    new_email = f"newbuyer-{uuid.uuid4().hex[:6]}@example.com"
    event = Event(
        name="crm.lead.qualified",
        data={
            "lead_id": str(uuid.uuid4()),
            "metadata": {
                "dev_focused": True,
                "development_code": dev.code,
                "email": new_email,
                "full_name": "Auto Buyer",
                "phone": "+971500000000",
            },
        },
        source_module="crm",
    )
    result = await _on_crm_lead_qualified(event)
    assert result is not None
    assert result["status"] == "ok"
    # Verify with a fresh session.
    from app.database import async_session_factory

    async with async_session_factory() as s:
        rows = list(
            (
                await s.execute(
                    select(Buyer)
                    .where(Buyer.development_id == dev.id)
                    .where(func.lower(Buyer.email) == new_email.lower())
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].status == "lead"


@pytest.mark.asyncio
async def test_subscriber_portal_buyer_signup_wires_portal_id(session, seeded_dev):
    """``portal.buyer_signup.completed`` stamps Buyer.portal_user_id."""
    from app.core.events import Event
    from app.modules.property_dev.events import _on_portal_buyer_signup
    from app.modules.property_dev.models import Buyer

    buyer = seeded_dev["buyer"]
    portal_uid = uuid.uuid4()
    event = Event(
        name="portal.buyer_signup.completed",
        data={"portal_user_id": str(portal_uid), "email": buyer.email},
        source_module="portal",
    )
    await _on_portal_buyer_signup(event)
    # Verify with a fresh session.
    from app.database import async_session_factory

    async with async_session_factory() as s:
        fresh = await s.get(Buyer, buyer.id)
        assert fresh.portal_user_id == portal_uid


@pytest.mark.asyncio
async def test_subscriber_finance_invoice_created_records_ref(session, seeded_dev):
    """``finance.invoice.created`` appends to Buyer.metadata.invoice_refs."""
    from app.core.events import Event
    from app.modules.property_dev.events import _on_finance_invoice_created
    from app.modules.property_dev.models import Buyer

    buyer = seeded_dev["buyer"]
    event = Event(
        name="finance.invoice.created",
        data={
            "invoice_id": str(uuid.uuid4()),
            "invoice_number": "INV-2026-00042",
            "metadata": {
                "instalment_buyer_id": str(buyer.id),
                "instalment_kind": "deposit",
            },
        },
        source_module="finance",
    )
    await _on_finance_invoice_created(event)
    from app.database import async_session_factory

    async with async_session_factory() as s:
        fresh = await s.get(Buyer, buyer.id)
        meta = fresh.metadata_ or {}
        assert meta.get("invoice_ref") == "INV-2026-00042"
        refs = meta.get("invoice_refs") or []
        assert refs and refs[-1]["invoice_number"] == "INV-2026-00042"


# ─────────────────────────────────────────────────────────────────────────
# Compliance endpoints — IDOR / RBAC / 404
# ─────────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def auth_headers(seeded_dev):
    """Mint a JWT directly for the admin owner seeded by ``seeded_dev``.

    Avoids the httpx auth round-trip (which raced against sqlite locks
    when both the registration and the seeded_dev fixture wrote to the
    same DB on the same loop in earlier iterations).
    """
    from app.config import get_settings
    from app.modules.users.service import create_access_token

    settings = get_settings()
    token = create_access_token(seeded_dev["owner"], settings)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_compliance_dashboard_requires_auth(client, seeded_dev):
    """Unauthenticated request returns 401."""
    dev = seeded_dev["development"]
    resp = await client.get(
        "/api/v1/property-dev/compliance/dashboard",
        params={"dev_id": str(dev.id)},
    )
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_compliance_dashboard_404_for_unknown_dev(client, auth_headers):
    """Unknown UUID → 404 development_not_found."""
    resp = await client.get(
        "/api/v1/property-dev/compliance/dashboard",
        params={"dev_id": str(uuid.uuid4())},
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_compliance_dashboard_returns_results(client, seeded_dev, auth_headers):
    """Authed call returns a populated dashboard."""
    dev = seeded_dev["development"]
    resp = await client.get(
        "/api/v1/property-dev/compliance/dashboard",
        params={"dev_id": str(dev.id), "locale": "en"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["development_id"] == str(dev.id)
    assert isinstance(body["results"], list)
    rule_ids = {r["rule_id"] for r in body["results"]}
    assert "property_dev.escrow_account_required" in rule_ids


@pytest.mark.asyncio
async def test_compliance_regulator_reports_422_on_unknown_regulator(client, seeded_dev, auth_headers):
    """Unknown regulator code returns 422."""
    dev = seeded_dev["development"]
    resp = await client.get(
        "/api/v1/property-dev/compliance/regulator-reports",
        params={
            "dev_id": str(dev.id),
            "regulator": "BOGUS",
            "quarter": "2026-Q2",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_compliance_regulator_reports_returns_pdf(client, seeded_dev, auth_headers):
    """as=pdf returns application/pdf bytes starting with %PDF."""
    dev = seeded_dev["development"]
    resp = await client.get(
        "/api/v1/property-dev/compliance/regulator-reports",
        params={
            "dev_id": str(dev.id),
            "regulator": "RERA",
            "quarter": "2026-Q2",
            "as": "pdf",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/pdf")
    assert resp.content.startswith(b"%PDF")
