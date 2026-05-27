"""Unit tests for the subcontractors module.

Scope:
    - Pure helpers: derive_cert_status, compute_expiry_alerts,
      next_payment_blocked, compute_rating
    - State-machine workflows: prequalification + payment + agreement
    - Retention accrual + release math
    - Repository CRUD basics with stubbed AsyncSession
    - Permission constants registered correctly
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

# ── Stub model factory helpers ─────────────────────────────────────────


def _cert(
    *,
    cert_type: str = "insurance",
    valid_until: date | None = None,
    revoked: bool = False,
    subcontractor_id: uuid.UUID | None = None,
    cert_id: uuid.UUID | None = None,
) -> Any:
    return SimpleNamespace(
        id=cert_id or uuid.uuid4(),
        subcontractor_id=subcontractor_id or uuid.uuid4(),
        cert_type=cert_type,
        valid_until=valid_until,
        revoked=revoked,
    )


# ── Pure-helper tests ──────────────────────────────────────────────────


def test_derive_cert_status_valid() -> None:
    from app.modules.subcontractors.service import derive_cert_status

    today = date(2026, 5, 12)
    assert derive_cert_status(date(2026, 12, 31), revoked=False, today=today) == "valid"


def test_derive_cert_status_expired() -> None:
    from app.modules.subcontractors.service import derive_cert_status

    today = date(2026, 5, 12)
    assert derive_cert_status(date(2026, 4, 1), revoked=False, today=today) == "expired"


def test_derive_cert_status_revoked_wins() -> None:
    from app.modules.subcontractors.service import derive_cert_status

    today = date(2026, 5, 12)
    assert derive_cert_status(date(2030, 1, 1), revoked=True, today=today) == "revoked"


def test_derive_cert_status_no_valid_until() -> None:
    from app.modules.subcontractors.service import derive_cert_status

    assert derive_cert_status(None, revoked=False) == "valid"


# ── Expiry alerts ───────────────────────────────────────────────────────


def test_expiry_alerts_window_7() -> None:
    from app.modules.subcontractors.service import compute_expiry_alerts

    today = date(2026, 5, 12)
    cert = _cert(valid_until=today + timedelta(days=5))
    alerts = compute_expiry_alerts([cert], today=today)
    assert len(alerts) == 1
    assert alerts[0].window == 7
    assert alerts[0].days_until_expiry == 5


def test_expiry_alerts_window_30() -> None:
    from app.modules.subcontractors.service import compute_expiry_alerts

    today = date(2026, 5, 12)
    cert = _cert(valid_until=today + timedelta(days=20))
    alerts = compute_expiry_alerts([cert], today=today)
    assert alerts[0].window == 30


def test_expiry_alerts_window_60() -> None:
    from app.modules.subcontractors.service import compute_expiry_alerts

    today = date(2026, 5, 12)
    cert = _cert(valid_until=today + timedelta(days=50))
    alerts = compute_expiry_alerts([cert], today=today)
    assert alerts[0].window == 60


def test_expiry_alerts_outside_window_returns_empty() -> None:
    from app.modules.subcontractors.service import compute_expiry_alerts

    today = date(2026, 5, 12)
    cert = _cert(valid_until=today + timedelta(days=200))
    assert compute_expiry_alerts([cert], today=today) == []


def test_expiry_alerts_skip_revoked() -> None:
    from app.modules.subcontractors.service import compute_expiry_alerts

    today = date(2026, 5, 12)
    cert = _cert(valid_until=today + timedelta(days=10), revoked=True)
    assert compute_expiry_alerts([cert], today=today) == []


# ── next_payment_blocked ────────────────────────────────────────────────


def test_next_payment_blocked_when_missing_insurance() -> None:
    from app.modules.subcontractors.service import next_payment_blocked

    today = date(2026, 5, 12)
    certs = [_cert(cert_type="license", valid_until=today + timedelta(days=200))]
    result = next_payment_blocked(certs, today=today)
    assert result.blocked is True
    assert any("insurance" in r for r in result.reasons)


def test_next_payment_blocked_when_insurance_expired() -> None:
    from app.modules.subcontractors.service import next_payment_blocked

    today = date(2026, 5, 12)
    certs = [
        _cert(cert_type="insurance", valid_until=today - timedelta(days=10)),
        _cert(cert_type="license", valid_until=today + timedelta(days=100)),
    ]
    result = next_payment_blocked(certs, today=today)
    assert result.blocked is True
    assert any("insurance" in r for r in result.reasons)


def test_next_payment_unblocked_when_all_required_valid() -> None:
    from app.modules.subcontractors.service import next_payment_blocked

    today = date(2026, 5, 12)
    certs = [
        _cert(cert_type="insurance", valid_until=today + timedelta(days=200)),
        _cert(cert_type="license", valid_until=today + timedelta(days=200)),
    ]
    result = next_payment_blocked(certs, today=today)
    assert result.blocked is False
    assert result.reasons == []


def test_next_payment_blocked_when_revoked() -> None:
    from app.modules.subcontractors.service import next_payment_blocked

    today = date(2026, 5, 12)
    certs = [
        _cert(
            cert_type="insurance",
            valid_until=today + timedelta(days=200),
            revoked=True,
        ),
        _cert(cert_type="license", valid_until=today + timedelta(days=200)),
    ]
    result = next_payment_blocked(certs, today=today)
    assert result.blocked is True


# ── compute_rating ─────────────────────────────────────────────────────


def test_compute_rating_perfect_score() -> None:
    from app.modules.subcontractors.service import compute_rating

    rating = compute_rating({})  # no events = no penalties
    assert rating.quality_score == Decimal("100.00")
    assert rating.hse_score == Decimal("100.00")
    assert rating.overall_score == Decimal("100.00")


def test_compute_rating_penalises_ncr() -> None:
    from app.modules.subcontractors.service import compute_rating

    rating = compute_rating({"ncr_count": 2})
    # 100 - 15*2 = 70 quality
    assert rating.quality_score == Decimal("70.00")
    assert rating.hse_score == Decimal("100.00")
    assert rating.overall_score < Decimal("100.00")


def test_compute_rating_penalises_hse_more_than_ncr() -> None:
    from app.modules.subcontractors.service import compute_rating

    only_hse = compute_rating({"hse_incidents": 1})
    only_ncr = compute_rating({"ncr_count": 1})
    # HSE penalty (20) > NCR penalty (15)
    assert only_hse.hse_score < only_ncr.quality_score


def test_compute_rating_schedule_deviation() -> None:
    from app.modules.subcontractors.service import compute_rating

    rating = compute_rating({"schedule_deviations_days": 10})
    # 100 - 10*2 = 80
    assert rating.schedule_score == Decimal("80.00")


def test_compute_rating_direct_score_override() -> None:
    from app.modules.subcontractors.service import compute_rating

    rating = compute_rating({"direct_scores": {"quality": 50, "hse": 60, "schedule": 70, "cost": 80}})
    assert rating.quality_score == Decimal("50.00")
    assert rating.hse_score == Decimal("60.00")
    assert rating.schedule_score == Decimal("70.00")
    assert rating.cost_score == Decimal("80.00")


def test_compute_rating_clamps_negative() -> None:
    from app.modules.subcontractors.service import compute_rating

    rating = compute_rating({"ncr_count": 100})  # would go very negative
    assert rating.quality_score == Decimal("0.00")


# ── Repository CRUD stubs ──────────────────────────────────────────────


class _SessionStub:
    """Minimal AsyncSession stub for repository tests."""

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.flushed = 0
        self.expired = False

    def add(self, obj: Any) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        now = datetime.now(UTC)
        if not hasattr(obj, "created_at") or obj.created_at is None:
            obj.created_at = now
        obj.updated_at = now
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushed += 1

    async def execute(self, _stmt: Any) -> Any:
        return SimpleNamespace(scalar_one=lambda: 0)

    async def get(self, _model: Any, ent_id: Any) -> Any:
        for o in self.added:
            if getattr(o, "id", None) == ent_id:
                return o
        return None

    def expire_all(self) -> None:
        self.expired = True

    async def delete(self, obj: Any) -> None:
        if obj in self.added:
            self.added.remove(obj)

    async def refresh(self, _obj: Any) -> None:
        pass


@pytest.mark.asyncio
async def test_subcontractor_repository_create_and_get() -> None:
    from app.modules.subcontractors.models import Subcontractor
    from app.modules.subcontractors.repository import SubcontractorRepository

    session = _SessionStub()
    repo = SubcontractorRepository(session)  # type: ignore[arg-type]

    entity = Subcontractor(
        legal_name="Acme GmbH",
        trade_categories=["concrete"],
        prequalification_status="approved",
    )
    created = await repo.create(entity)
    assert created.id is not None
    fetched = await repo.get_by_id(created.id)
    assert fetched is not None
    assert fetched.legal_name == "Acme GmbH"


@pytest.mark.asyncio
async def test_certificate_repository_create() -> None:
    from app.modules.subcontractors.models import Certificate
    from app.modules.subcontractors.repository import CertificateRepository

    session = _SessionStub()
    repo = CertificateRepository(session)  # type: ignore[arg-type]
    cert = Certificate(
        subcontractor_id=uuid.uuid4(),
        cert_type="insurance",
        valid_until=date(2026, 12, 31),
        status="valid",
    )
    created = await repo.create(cert)
    assert created.id is not None
    assert session.flushed >= 1


# ── Workflow tests with stub repositories ──────────────────────────────


@dataclass
class _Repo:
    """Generic in-memory repo holding rows + counter."""

    rows: dict[uuid.UUID, Any] = field(default_factory=dict)
    _counter: int = 0

    async def create(self, entity: Any) -> Any:
        if getattr(entity, "id", None) is None:
            entity.id = uuid.uuid4()
        now = datetime.now(UTC)
        if not hasattr(entity, "created_at") or entity.created_at is None:
            entity.created_at = now
        entity.updated_at = now
        self.rows[entity.id] = entity
        return entity

    async def get_by_id(self, eid: uuid.UUID) -> Any:
        return self.rows.get(eid)

    async def update_fields(self, eid: uuid.UUID, **kwargs: Any) -> None:
        obj = self.rows.get(eid)
        if obj is None:
            return
        for k, v in kwargs.items():
            setattr(obj, k, v)
        obj.updated_at = datetime.now(UTC)

    async def delete(self, eid: uuid.UUID) -> None:
        self.rows.pop(eid, None)

    async def list_for_subcontractor(self, sub_id: uuid.UUID, **_kwargs: Any) -> list[Any]:
        return [r for r in self.rows.values() if getattr(r, "subcontractor_id", None) == sub_id]

    async def list_by_subcontractor(self, sub_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if getattr(r, "subcontractor_id", None) == sub_id]

    async def list_for_agreement(self, ag_id: uuid.UUID, **_kwargs: Any) -> list[Any]:
        return [r for r in self.rows.values() if getattr(r, "agreement_id", None) == ag_id]

    async def next_application_number(self, _ag_id: uuid.UUID) -> str:
        self._counter += 1
        return f"PA-{self._counter:04d}"

    async def get_for_period(self, sub_id: uuid.UUID, period: str) -> Any:
        for r in self.rows.values():
            if getattr(r, "subcontractor_id", None) == sub_id and getattr(r, "period", None) == period:
                return r
        return None


def _make_service() -> Any:
    from app.modules.subcontractors.service import SubcontractorService

    svc = SubcontractorService.__new__(SubcontractorService)
    svc.session = SimpleNamespace(
        refresh=AsyncMock(),
        execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: None)),
        add=lambda _o: None,
        flush=AsyncMock(),
    )
    svc.subs = _Repo()
    svc.contacts = _Repo()
    svc.prequal = _Repo()
    svc.certs = _Repo()
    svc.agreements = _Repo()
    svc.work_packages = _Repo()
    svc.payments = _Repo()
    svc.payment_lines = _Repo()
    svc.retention = _Repo()
    svc.ratings = _Repo()
    return svc


@pytest.mark.asyncio
async def test_prequalification_workflow_happy_path() -> None:
    from app.modules.subcontractors.schemas import (
        PrequalificationCreate,
        SubcontractorCreate,
    )

    svc = _make_service()
    with patch(
        "app.modules.subcontractors.service.event_bus.publish_detached",
    ):
        sub = await svc.create_subcontractor(
            SubcontractorCreate(legal_name="Acme", prequalification_status="pending"),
            user_id="u1",
        )
        prequal = await svc.create_prequalification(
            PrequalificationCreate(subcontractor_id=sub.id, status="draft"),
            user_id="u1",
        )
        assert prequal.status == "draft"

        submitted = await svc.submit_prequalification(prequal.id)
        assert submitted.status == "submitted"

        approved = await svc.approve_prequalification(
            prequal.id,
            reviewer_id="reviewer-1",
            notes="OK",
        )
        assert approved.status == "approved"
        assert approved.reviewer_id == "reviewer-1"
        # Parent subcontractor should now be approved.
        refreshed_sub = await svc.subs.get_by_id(sub.id)
        assert refreshed_sub.prequalification_status == "approved"


@pytest.mark.asyncio
async def test_prequalification_invalid_transition_raises() -> None:
    from fastapi import HTTPException

    from app.modules.subcontractors.schemas import (
        PrequalificationCreate,
        SubcontractorCreate,
    )

    svc = _make_service()
    with patch("app.modules.subcontractors.service.event_bus.publish_detached"):
        sub = await svc.create_subcontractor(
            SubcontractorCreate(legal_name="Acme"),
        )
        prequal = await svc.create_prequalification(
            PrequalificationCreate(subcontractor_id=sub.id, status="approved"),
        )
        with pytest.raises(HTTPException) as exc:
            await svc.submit_prequalification(prequal.id)
        assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_payment_application_workflow_happy_path() -> None:
    from app.modules.subcontractors.schemas import (
        AgreementCreate,
        AgreementUpdate,
        CertificateCreate,
        PaymentApplicationCreate,
        SubcontractorCreate,
    )

    svc = _make_service()
    with patch("app.modules.subcontractors.service.event_bus.publish_detached"):
        sub = await svc.create_subcontractor(SubcontractorCreate(legal_name="Acme"))
        # Required certs so the block doesn't trigger.
        await svc.record_certificate(
            CertificateCreate(
                subcontractor_id=sub.id,
                cert_type="insurance",
                valid_until=date.today() + timedelta(days=180),
            ),
        )
        await svc.record_certificate(
            CertificateCreate(
                subcontractor_id=sub.id,
                cert_type="license",
                valid_until=date.today() + timedelta(days=180),
            ),
        )
        agreement = await svc.create_agreement(
            AgreementCreate(
                subcontractor_id=sub.id,
                project_id=uuid.uuid4(),
                title="Concrete subcontract",
                total_value=Decimal("100000"),
                currency="EUR",
                retention_percent=Decimal("5"),
            ),
        )
        # An agreement is born "draft"; it must be signed off (activated)
        # before any payment can be claimed against it.
        agreement = await svc.update_agreement(
            agreement.id,
            AgreementUpdate(status="active"),
        )
        assert agreement.status == "active"
        pa = await svc.submit_payment_application(
            PaymentApplicationCreate(
                agreement_id=agreement.id,
                gross_amount=Decimal("10000"),
                currency="EUR",
            ),
            user_id="u1",
        )
        assert pa.status == "submitted"
        # 5% retention => 500 retention, 9500 net
        assert pa.retention_amount == Decimal("500.00")
        assert pa.net_amount == Decimal("9500.00")

        foreman = await svc.approve_payment_application_foreman(pa.id, user_id="foreman-1")
        assert foreman.status == "foreman_approved"
        assert foreman.foreman_approved_by == "foreman-1"

        finance = await svc.approve_payment_application_finance(pa.id, user_id="finance-1")
        assert finance.status == "finance_approved"

        paid = await svc.mark_paid(pa.id)
        assert paid.status == "paid"
        assert paid.paid_at is not None


@pytest.mark.asyncio
async def test_payment_application_blocked_when_certs_missing() -> None:
    from fastapi import HTTPException

    from app.modules.subcontractors.schemas import (
        AgreementCreate,
        AgreementUpdate,
        PaymentApplicationCreate,
        SubcontractorCreate,
    )

    svc = _make_service()
    with patch("app.modules.subcontractors.service.event_bus.publish_detached"):
        sub = await svc.create_subcontractor(SubcontractorCreate(legal_name="Acme"))
        agreement = await svc.create_agreement(
            AgreementCreate(
                subcontractor_id=sub.id,
                project_id=uuid.uuid4(),
                title="Concrete subcontract",
                total_value=Decimal("100000"),
                currency="EUR",
            ),
        )
        # Activate so the flow reaches the cert-missing block under test
        # rather than short-circuiting on the agreement-status guard.
        await svc.update_agreement(agreement.id, AgreementUpdate(status="active"))
        with pytest.raises(HTTPException) as exc:
            await svc.submit_payment_application(
                PaymentApplicationCreate(
                    agreement_id=agreement.id,
                    gross_amount=Decimal("10000"),
                ),
            )
        assert exc.value.status_code == 409
        assert "payment_blocked" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_retention_accrue_and_release() -> None:
    from app.modules.subcontractors.schemas import (
        AgreementCreate,
        AgreementUpdate,
        CertificateCreate,
        PaymentApplicationCreate,
        SubcontractorCreate,
    )

    svc = _make_service()
    with patch("app.modules.subcontractors.service.event_bus.publish_detached"):
        sub = await svc.create_subcontractor(SubcontractorCreate(legal_name="Acme"))
        for ct in ("insurance", "license"):
            await svc.record_certificate(
                CertificateCreate(
                    subcontractor_id=sub.id,
                    cert_type=ct,
                    valid_until=date.today() + timedelta(days=180),
                ),
            )
        agreement = await svc.create_agreement(
            AgreementCreate(
                subcontractor_id=sub.id,
                project_id=uuid.uuid4(),
                title="X",
                total_value=Decimal("100000"),
                currency="EUR",
            ),
        )
        await svc.update_agreement(agreement.id, AgreementUpdate(status="active"))
        # Submit two payments, each gross=20000 => retention 1000 each => balance 2000
        for _ in range(2):
            await svc.submit_payment_application(
                PaymentApplicationCreate(
                    agreement_id=agreement.id,
                    gross_amount=Decimal("20000"),
                    currency="EUR",
                ),
            )
        balance = await svc.retention_balance(agreement.id)
        assert balance == Decimal("2000.00")

        # Release 1500
        await svc.release_retention(
            agreement_id=agreement.id,
            amount=Decimal("1500"),
            reason="50% practical_completion",
        )
        new_balance = await svc.retention_balance(agreement.id)
        assert new_balance == Decimal("500.00")


@pytest.mark.asyncio
async def test_agreement_invalid_status_transition() -> None:
    from fastapi import HTTPException

    from app.modules.subcontractors.schemas import (
        AgreementCreate,
        AgreementUpdate,
        SubcontractorCreate,
    )

    svc = _make_service()
    with patch("app.modules.subcontractors.service.event_bus.publish_detached"):
        sub = await svc.create_subcontractor(SubcontractorCreate(legal_name="Acme"))
        agreement = await svc.create_agreement(
            AgreementCreate(
                subcontractor_id=sub.id,
                project_id=uuid.uuid4(),
                title="X",
                total_value=Decimal("100"),
            ),
        )
        # draft -> completed is invalid
        with pytest.raises(HTTPException):
            await svc.update_agreement(agreement.id, AgreementUpdate(status="completed"))


@pytest.mark.asyncio
async def test_certificate_status_auto_derived() -> None:
    from app.modules.subcontractors.schemas import (
        CertificateCreate,
        SubcontractorCreate,
    )

    svc = _make_service()
    with patch("app.modules.subcontractors.service.event_bus.publish_detached"):
        sub = await svc.create_subcontractor(SubcontractorCreate(legal_name="Acme"))
        expired_cert = await svc.record_certificate(
            CertificateCreate(
                subcontractor_id=sub.id,
                cert_type="insurance",
                valid_until=date.today() - timedelta(days=30),
            ),
        )
        assert expired_cert.status == "expired"
        valid_cert = await svc.record_certificate(
            CertificateCreate(
                subcontractor_id=sub.id,
                cert_type="license",
                valid_until=date.today() + timedelta(days=30),
            ),
        )
        assert valid_cert.status == "valid"


@pytest.mark.asyncio
async def test_update_rating_rolls_up_score() -> None:
    from app.modules.subcontractors.schemas import (
        RatingCreate,
        SubcontractorCreate,
    )

    svc = _make_service()
    with patch("app.modules.subcontractors.service.event_bus.publish_detached"):
        sub = await svc.create_subcontractor(SubcontractorCreate(legal_name="Acme"))
        rating = await svc.update_rating(
            RatingCreate(
                subcontractor_id=sub.id,
                period="2026-05",
                quality_score=Decimal("80"),
                hse_score=Decimal("90"),
                schedule_score=Decimal("70"),
                cost_score=Decimal("60"),
            ),
        )
        # weights: 0.30 quality + 0.30 hse + 0.20 schedule + 0.20 cost
        # = 24 + 27 + 14 + 12 = 77
        assert rating.overall_score == Decimal("77.00")
        refreshed = await svc.subs.get_by_id(sub.id)
        assert refreshed.rating_score == Decimal("77.00")


# ── Permission registration ────────────────────────────────────────────


def test_permissions_registered() -> None:
    from app.core.permissions import permission_registry
    from app.modules.subcontractors.permissions import (
        register_subcontractors_permissions,
    )

    register_subcontractors_permissions()
    all_perms = permission_registry.list_all()
    for perm in (
        "subcontractors.create",
        "subcontractors.read",
        "subcontractors.update",
        "subcontractors.delete",
        "subcontractors.approve_prequalification",
        "subcontractors.approve_payment_foreman",
        "subcontractors.approve_payment_finance",
        "subcontractors.release_retention",
    ):
        assert perm in all_perms


def test_permissions_role_hierarchy() -> None:
    from app.core.permissions import Role, permission_registry
    from app.modules.subcontractors.permissions import (
        register_subcontractors_permissions,
    )

    register_subcontractors_permissions()
    # Editor cannot delete or approve finance / release retention
    assert not permission_registry.role_has_permission(
        Role.EDITOR,
        "subcontractors.delete",
    )
    assert not permission_registry.role_has_permission(
        Role.EDITOR,
        "subcontractors.release_retention",
    )
    # Manager can do everything except the admin-only system commands
    assert permission_registry.role_has_permission(
        Role.MANAGER,
        "subcontractors.approve_payment_finance",
    )
    assert permission_registry.role_has_permission(
        Role.MANAGER,
        "subcontractors.release_retention",
    )


# ── Tax-ID / VAT validator ────────────────────────────────────────────────


def test_validate_tax_id_de_format_ok() -> None:
    from app.modules.subcontractors.service import validate_tax_id

    # German VAT body is 9 digits; the validator strips the "DE" prefix
    # and the spaces / dashes too.
    res = validate_tax_id("DE", "DE 123 456 789")
    assert res.format_valid is True
    assert res.tax_id_normalised == "123456789"
    assert res.standard == "EU VAT (DE)"
    assert res.country == "DE"
    assert res.reason is None


def test_validate_tax_id_de_format_fail() -> None:
    from app.modules.subcontractors.service import validate_tax_id

    res = validate_tax_id("DE", "12345")  # too short
    assert res.format_valid is False
    assert res.standard == "EU VAT (DE)"
    assert res.reason is not None


def test_validate_tax_id_unknown_country_is_permissive() -> None:
    """Countries without a registered rule pass through as `format_valid=True`."""
    from app.modules.subcontractors.service import validate_tax_id

    res = validate_tax_id("XX", "ABCDEF123")
    assert res.format_valid is True
    assert res.standard is None
    assert res.country == "XX"


def test_validate_tax_id_us_ein() -> None:
    from app.modules.subcontractors.service import validate_tax_id

    res = validate_tax_id("US", "12-3456789")
    assert res.format_valid is True
    assert res.tax_id_normalised == "123456789"
    assert res.standard == "US EIN"


def test_validate_tax_id_br_cnpj() -> None:
    from app.modules.subcontractors.service import validate_tax_id

    res = validate_tax_id("BR", "12.345.678/0001-95")
    assert res.format_valid is True
    assert res.tax_id_normalised == "12345678000195"
    assert res.standard == "BR CNPJ"


def test_validate_tax_id_empty_input() -> None:
    from app.modules.subcontractors.service import validate_tax_id

    res = validate_tax_id("DE", "")
    assert res.format_valid is False
    assert res.reason == "empty_after_normalisation"


# ── Rating bump from cross-module event ───────────────────────────────────


@dataclass
class _RatingStubRepo:
    rows: dict[uuid.UUID, Any] = field(default_factory=dict)

    async def get_for_period(self, sub_id: uuid.UUID, period: str) -> Any | None:
        for r in self.rows.values():
            if r.subcontractor_id == sub_id and r.period == period:
                return r
        return None

    async def create(self, entity: Any) -> Any:
        entity.id = uuid.uuid4()
        self.rows[entity.id] = entity
        return entity

    async def update_fields(self, entity_id: uuid.UUID, **fields: Any) -> None:
        row = self.rows.get(entity_id)
        if row is None:
            return
        for k, v in fields.items():
            setattr(row, k, v)


@dataclass
class _SubStubRepo:
    sub_id: uuid.UUID
    legal_name: str = "ACME Subcontractor"
    rating_score: Decimal = Decimal("100")

    async def get_by_id(self, sub_id: uuid.UUID) -> Any | None:
        if sub_id != self.sub_id:
            return None
        return SimpleNamespace(
            id=self.sub_id,
            legal_name=self.legal_name,
            rating_score=self.rating_score,
        )

    async def update_fields(self, sub_id: uuid.UUID, **fields: Any) -> None:
        if sub_id == self.sub_id and "rating_score" in fields:
            self.rating_score = fields["rating_score"]


@pytest.mark.asyncio
async def test_bump_rating_creates_period_row() -> None:
    """First ncr event for the month → new rating row, score < 100."""
    from app.modules.subcontractors.service import SubcontractorService

    sub_id = uuid.uuid4()
    svc = SubcontractorService.__new__(SubcontractorService)
    svc.session = SimpleNamespace(refresh=AsyncMock(return_value=None))
    svc.subs = _SubStubRepo(sub_id=sub_id)  # type: ignore[assignment]
    svc.ratings = _RatingStubRepo()  # type: ignore[assignment]

    with patch("app.modules.subcontractors.service.event_bus.publish_detached"):
        rating = await svc.bump_rating_from_event(sub_id, kind="ncr")

    assert rating is not None
    assert rating.subcontractor_id == sub_id
    # NCR penalty (15 per NCR) reduces quality below 100; weighted overall
    # therefore strictly < 100.
    assert rating.overall_score < Decimal("100")
    # Sub's rolled-up rating_score is the new overall.
    assert svc.subs.rating_score == rating.overall_score  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_bump_rating_idempotent_within_period() -> None:
    """Second event in the same period updates the existing row, not a new one."""
    from app.modules.subcontractors.service import SubcontractorService

    sub_id = uuid.uuid4()
    svc = SubcontractorService.__new__(SubcontractorService)
    svc.session = SimpleNamespace(refresh=AsyncMock(return_value=None))
    svc.subs = _SubStubRepo(sub_id=sub_id)  # type: ignore[assignment]
    svc.ratings = _RatingStubRepo()  # type: ignore[assignment]

    with patch("app.modules.subcontractors.service.event_bus.publish_detached"):
        first = await svc.bump_rating_from_event(sub_id, kind="ncr")
        # Snapshot the score BEFORE the second bump mutates the same row.
        assert first is not None
        score_after_one_ncr = first.overall_score

        second = await svc.bump_rating_from_event(sub_id, kind="ncr")
        assert second is not None
        score_after_two_ncrs = second.overall_score

    # Same row updated, not a new period row added.
    assert first.id == second.id
    # Only one row exists in the stub.
    assert len(svc.ratings.rows) == 1  # type: ignore[attr-defined]
    # 2 NCRs → lower score than 1 NCR.
    assert score_after_two_ncrs < score_after_one_ncr


@pytest.mark.asyncio
async def test_bump_rating_silently_skips_unknown_sub() -> None:
    """Event for a deleted/unknown subcontractor returns None, no exception."""
    from app.modules.subcontractors.service import SubcontractorService

    svc = SubcontractorService.__new__(SubcontractorService)
    svc.session = SimpleNamespace(refresh=AsyncMock(return_value=None))
    svc.subs = _SubStubRepo(sub_id=uuid.uuid4())  # type: ignore[assignment]
    svc.ratings = _RatingStubRepo()  # type: ignore[assignment]

    with patch("app.modules.subcontractors.service.event_bus.publish_detached"):
        result = await svc.bump_rating_from_event(uuid.uuid4(), kind="ncr")

    assert result is None


# ── Schedule of Values (SOV) ──────────────────────────────────────────────


@dataclass
class _SovWPRepo:
    rows: list[Any] = field(default_factory=list)

    async def list_for_agreement(self, agreement_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows if r.agreement_id == agreement_id]


@dataclass
class _SovPaRepo:
    rows: list[Any] = field(default_factory=list)

    async def list_for_agreement(self, agreement_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows if r.agreement_id == agreement_id]


@dataclass
class _SovLineRepo:
    rows: list[Any] = field(default_factory=list)

    async def list_for_application(self, app_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows if r.payment_application_id == app_id]


@dataclass
class _SovAgreementRepo:
    rows: dict[uuid.UUID, Any] = field(default_factory=dict)

    async def get_by_id(self, ag_id: uuid.UUID) -> Any | None:
        return self.rows.get(ag_id)


@pytest.mark.asyncio
async def test_sov_summary_rolls_up_claimed_certified_approved() -> None:
    """SOV per work package sums lines across every PA."""
    from app.modules.subcontractors.service import SubcontractorService

    agreement_id = uuid.uuid4()
    sub_id = uuid.uuid4()
    wp1_id = uuid.uuid4()
    wp2_id = uuid.uuid4()
    pa1_id = uuid.uuid4()
    pa2_id = uuid.uuid4()

    svc = SubcontractorService.__new__(SubcontractorService)
    svc.session = SimpleNamespace(refresh=AsyncMock(return_value=None))

    svc.agreements = _SovAgreementRepo(  # type: ignore[assignment]
        rows={
            agreement_id: SimpleNamespace(
                id=agreement_id,
                subcontractor_id=sub_id,
                project_id=uuid.uuid4(),
                total_value=Decimal("100000"),
                currency="EUR",
            )
        }
    )
    svc.work_packages = _SovWPRepo(  # type: ignore[assignment]
        rows=[
            SimpleNamespace(
                id=wp1_id,
                agreement_id=agreement_id,
                name="Foundations",
                planned_value=Decimal("60000"),
                completion_percent=Decimal("50"),
                status="in_progress",
            ),
            SimpleNamespace(
                id=wp2_id,
                agreement_id=agreement_id,
                name="Frame",
                planned_value=Decimal("40000"),
                completion_percent=Decimal("0"),
                status="planned",
            ),
        ]
    )
    svc.payments = _SovPaRepo(  # type: ignore[assignment]
        rows=[
            SimpleNamespace(id=pa1_id, agreement_id=agreement_id),
            SimpleNamespace(id=pa2_id, agreement_id=agreement_id),
        ]
    )
    svc.payment_lines = _SovLineRepo(  # type: ignore[assignment]
        rows=[
            # PA1: 20k claimed / 18k cert / 18k approved on WP1
            SimpleNamespace(
                payment_application_id=pa1_id,
                work_package_id=wp1_id,
                claimed_amount=Decimal("20000"),
                certified_amount=Decimal("18000"),
                approved_amount=Decimal("18000"),
            ),
            # PA2: 10k claimed / 10k cert / 10k approved on WP1
            SimpleNamespace(
                payment_application_id=pa2_id,
                work_package_id=wp1_id,
                claimed_amount=Decimal("10000"),
                certified_amount=Decimal("10000"),
                approved_amount=Decimal("10000"),
            ),
        ]
    )

    summary = await svc.sov_summary(agreement_id)
    assert summary.agreement_id == agreement_id
    assert summary.subcontractor_id == sub_id
    by_wp = {row.work_package_id: row for row in summary.rows}
    # WP1 totals
    assert by_wp[wp1_id].claimed_to_date == Decimal("30000")
    assert by_wp[wp1_id].certified_to_date == Decimal("28000")
    assert by_wp[wp1_id].approved_to_date == Decimal("28000")
    # remaining = planned - approved = 60_000 - 28_000
    assert by_wp[wp1_id].remaining == Decimal("32000")
    # WP2 has no PA lines yet → all zero, remaining == planned.
    assert by_wp[wp2_id].approved_to_date == Decimal("0")
    assert by_wp[wp2_id].remaining == Decimal("40000")
    # Totals roll up across WPs.
    assert summary.totals["approved_to_date"] == Decimal("28000")
    assert summary.totals["remaining"] == Decimal("72000")
