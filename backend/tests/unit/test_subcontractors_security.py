"""Round-5 hardening tests for the subcontractors module.

Covers the v4.3.0 audit deltas:

* Rating tampering — ``rating_score`` no longer accepted by
  :class:`SubcontractorUpdate`; ``POST /ratings/`` requires the new
  MANAGER-only ``subcontractors.rate`` permission.
* Block tampering — ``/block`` + ``/unblock`` require the new
  MANAGER-only ``subcontractors.block`` permission.
* tax_id uniqueness — read-then-write 409 + IntegrityError → 409 fallback.
* CRLF sanitisation on free-form text fields fed to logs / events.
* Document URL hygiene on ``CertificateCreate`` (no ``file://``, no
  ``..`` traversal, no CR/LF).
* Backdated / out-of-range certificate ``valid_until``.
* PII redaction in service log lines for subcontractor contacts.
* Currency validation against ISO-4217 on agreement / payment app.
* Questionnaire DoS cap on prequalification payload.
* Dashboard N+1 collapse — verified by hit-count on a counting stub.

LLM is NOT used in these paths, so no mock is required.

Repository stubs follow the same shape as ``test_subcontractors.py``.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

# ── Stubs reused across the file (kept compact; mirrors test_subcontractors.py) ──


@dataclass
class _Repo:
    """Minimal in-memory repo with the surface the service touches."""

    rows: dict[uuid.UUID, Any] = field(default_factory=dict)
    _counter: int = 0
    find_calls: int = 0
    open_payments_calls: int = 0
    balance_calls: int = 0

    async def create(self, entity: Any) -> Any:
        if getattr(entity, "id", None) is None:
            entity.id = uuid.uuid4()
        now = datetime.now(UTC)
        if not hasattr(entity, "created_at") or entity.created_at is None:
            entity.created_at = now
        entity.updated_at = now
        # ORM defaults are only applied at flush time; backfill so the
        # tax_id / dashboard filters that read ``is_active`` behave like
        # they would against the real DB.
        if getattr(entity, "is_active", None) is None:
            entity.is_active = True
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

    async def list_for_subcontractor(
        self,
        sub_id: uuid.UUID,
        **_kwargs: Any,
    ) -> list[Any]:
        return [r for r in self.rows.values() if getattr(r, "subcontractor_id", None) == sub_id]

    async def list_by_subcontractor(self, sub_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if getattr(r, "subcontractor_id", None) == sub_id]

    async def list_for_agreement(
        self,
        ag_id: uuid.UUID,
        **_kwargs: Any,
    ) -> list[Any]:
        return [r for r in self.rows.values() if getattr(r, "agreement_id", None) == ag_id]

    async def next_application_number(self, _ag_id: uuid.UUID) -> str:
        self._counter += 1
        return f"PA-{self._counter:04d}"

    async def get_for_period(self, sub_id: uuid.UUID, period: str) -> Any:
        for r in self.rows.values():
            if getattr(r, "subcontractor_id", None) == sub_id and getattr(r, "period", None) == period:
                return r
        return None

    async def find_by_tax_id(
        self,
        tax_id: str,
        *,
        country: str | None = None,
    ) -> Any:
        self.find_calls += 1
        for r in self.rows.values():
            if (
                getattr(r, "tax_id", None) == tax_id
                and getattr(r, "is_active", True)
                and (country is None or getattr(r, "country", None) == country)
            ):
                return r
        return None

    async def count_open_for_agreements(
        self,
        agreement_ids: list[uuid.UUID],
    ) -> int:
        self.open_payments_calls += 1
        return sum(
            1
            for r in self.rows.values()
            if getattr(r, "agreement_id", None) in agreement_ids
            and getattr(r, "status", None)
            in (
                "submitted",
                "foreman_approved",
                "finance_approved",
            )
        )

    async def balance_for_agreements(
        self,
        agreement_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, tuple[Decimal, Decimal]]:
        self.balance_calls += 1
        out: dict[uuid.UUID, tuple[Decimal, Decimal]] = {}
        for ag_id in agreement_ids:
            accrued = sum(
                (
                    Decimal(str(r.accrued_amount))
                    for r in self.rows.values()
                    if getattr(r, "agreement_id", None) == ag_id
                ),
                Decimal("0"),
            )
            released = sum(
                (
                    Decimal(str(r.released_amount))
                    for r in self.rows.values()
                    if getattr(r, "agreement_id", None) == ag_id
                ),
                Decimal("0"),
            )
            out[ag_id] = (accrued, released)
        return out


def _make_service() -> Any:
    from app.modules.subcontractors.service import SubcontractorService

    svc = SubcontractorService.__new__(SubcontractorService)
    svc.session = SimpleNamespace(
        refresh=AsyncMock(),
        execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: None)),
        add=lambda _o: None,
        flush=AsyncMock(),
        rollback=AsyncMock(),
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


# ── Permission registration — new perms wired in ──────────────────────────


class TestNewPermissionsRegistered:
    def test_rate_perm_registered(self) -> None:
        from app.core.permissions import Role, permission_registry
        from app.modules.subcontractors.permissions import (
            register_subcontractors_permissions,
        )

        register_subcontractors_permissions()
        assert "subcontractors.rate" in permission_registry.list_all()
        # Manager can rate; Editor cannot.
        assert permission_registry.role_has_permission(
            Role.MANAGER,
            "subcontractors.rate",
        )
        assert not permission_registry.role_has_permission(
            Role.EDITOR,
            "subcontractors.rate",
        )

    def test_block_perm_registered(self) -> None:
        from app.core.permissions import Role, permission_registry
        from app.modules.subcontractors.permissions import (
            register_subcontractors_permissions,
        )

        register_subcontractors_permissions()
        assert "subcontractors.block" in permission_registry.list_all()
        assert not permission_registry.role_has_permission(
            Role.EDITOR,
            "subcontractors.block",
        )

    def test_block_route_uses_block_perm(self) -> None:
        """Regression for: any EDITOR could exclude a rival firm."""
        from app.modules.subcontractors import router as sub_router

        block = next(r for r in sub_router.router.routes if getattr(r, "path", "") == "/subcontractors/{sub_id}/block")
        perms = {getattr(d.call, "permission", None) for d in block.dependant.dependencies}
        assert "subcontractors.block" in perms, f"/block lost its dedicated permission guard; saw {perms}"

    def test_rate_route_uses_rate_perm(self) -> None:
        """Regression for: any EDITOR could forge a subcontractor rating."""
        from app.modules.subcontractors import router as sub_router

        rate = next(
            r
            for r in sub_router.router.routes
            if getattr(r, "path", "") == "/ratings/" and "POST" in getattr(r, "methods", set())
        )
        perms = {getattr(d.call, "permission", None) for d in rate.dependant.dependencies}
        assert "subcontractors.rate" in perms, f"POST /ratings/ lost its dedicated permission guard; saw {perms}"


# ── Rating tampering — SubcontractorUpdate must not accept rating_score ───


class TestRatingTamperingClosed:
    def test_subcontractor_update_rejects_rating_score(self) -> None:
        """A future schema regression that re-introduces ``rating_score`` on
        SubcontractorUpdate should fail this test."""
        from app.modules.subcontractors.schemas import SubcontractorUpdate

        assert "rating_score" not in SubcontractorUpdate.model_fields, (
            "rating_score must NOT be settable via PATCH /subcontractors/{id} — "
            "it is a derived rollup of SubcontractorRating rows."
        )

    @pytest.mark.asyncio
    async def test_service_drops_rating_score_on_update(self) -> None:
        """Even if a caller smuggles rating_score in via the dict path
        (e.g. an extra-field-tolerant proxy), the service must strip it."""
        from app.modules.subcontractors.models import Subcontractor

        svc = _make_service()
        sub_id = uuid.uuid4()
        # Pre-seed the sub with score 0.
        seeded = Subcontractor(
            legal_name="Acme",
            rating_score=Decimal("0"),
            prequalification_status="approved",
        )
        seeded.id = sub_id
        seeded.is_active = True
        svc.subs.rows[sub_id] = seeded

        # Build an UpdateModel-ish object that smuggles rating_score in.
        smuggle = SimpleNamespace()
        smuggle.model_dump = lambda exclude_unset: {  # type: ignore[assignment]
            "legal_name": "Acme New",
            "rating_score": Decimal("99.99"),
        }
        with patch("app.modules.subcontractors.service.event_bus.publish_detached"):
            await svc.update_subcontractor(sub_id, smuggle)  # type: ignore[arg-type]

        refreshed = await svc.subs.get_by_id(sub_id)
        assert refreshed.legal_name == "Acme New"
        # rating_score must not have been touched.
        assert refreshed.rating_score == Decimal("0"), (
            "Service let rating_score through the PATCH gate — tampering possible."
        )


# ── tax_id uniqueness — read-then-write + IntegrityError → 409 ────────────


class TestTaxIdUniqueness:
    @pytest.mark.asyncio
    async def test_duplicate_tax_id_returns_409(self) -> None:
        from app.modules.subcontractors.schemas import SubcontractorCreate

        svc = _make_service()
        with patch("app.modules.subcontractors.service.event_bus.publish_detached"):
            await svc.create_subcontractor(
                SubcontractorCreate(
                    legal_name="Acme",
                    tax_id="DE123456789",
                    country="DE",
                ),
            )
            with pytest.raises(HTTPException) as exc:
                await svc.create_subcontractor(
                    SubcontractorCreate(
                        legal_name="Acme Clone",
                        tax_id="DE123456789",
                        country="DE",
                    ),
                )
        assert exc.value.status_code == 409
        # Service hit the read-then-write helper exactly twice.
        assert svc.subs.find_calls == 2

    @pytest.mark.asyncio
    async def test_integrity_error_translates_to_409(self) -> None:
        """If two concurrent writers race past the read check, the
        IntegrityError raised by the DB must be translated to 409."""
        from sqlalchemy.exc import IntegrityError

        from app.modules.subcontractors.schemas import SubcontractorCreate

        svc = _make_service()

        async def _boom(_entity: Any) -> Any:
            raise IntegrityError("INSERT", None, Exception("dup"))

        svc.subs.create = _boom  # type: ignore[assignment]
        # find_by_tax_id returns None so we reach the create path.
        with patch("app.modules.subcontractors.service.event_bus.publish_detached"):
            with pytest.raises(HTTPException) as exc:
                await svc.create_subcontractor(
                    SubcontractorCreate(
                        legal_name="Acme",
                        tax_id="DE999999999",
                        country="DE",
                    ),
                )
        assert exc.value.status_code == 409
        # Session rollback called so the failed tx releases its locks.
        assert svc.session.rollback.await_count == 1


# ── CRLF sanitisation ─────────────────────────────────────────────────────


class TestCrlfSanitisation:
    def test_block_request_strips_crlf(self) -> None:
        from app.modules.subcontractors.schemas import BlockRequest

        body = BlockRequest(reason="Bad sub\r\nSet-Cookie: evil=1")
        # CR/LF collapsed to space; cookie injection vector neutralised.
        assert "\r" not in body.reason
        assert "\n" not in body.reason
        assert "evil" in body.reason  # content preserved, just neutered

    def test_block_request_rejects_blank_after_strip(self) -> None:
        from app.modules.subcontractors.schemas import BlockRequest

        with pytest.raises(ValidationError):
            BlockRequest(reason="\r\n\r\n")

    def test_retention_release_strips_crlf(self) -> None:
        from app.modules.subcontractors.schemas import RetentionReleasePayload

        body = RetentionReleasePayload(
            agreement_id=uuid.uuid4(),
            amount=Decimal("10"),
            reason="50% PC\r\nX-Injected: 1",
        )
        assert "\r" not in body.reason
        assert "\n" not in body.reason


# ── Document URL hygiene ──────────────────────────────────────────────────


class TestCertificateDocumentUrl:
    def test_rejects_file_scheme(self) -> None:
        from app.modules.subcontractors.schemas import CertificateCreate

        with pytest.raises(ValidationError):
            CertificateCreate(
                subcontractor_id=uuid.uuid4(),
                cert_type="insurance",
                document_url="file:///etc/passwd",
            )

    def test_rejects_traversal(self) -> None:
        from app.modules.subcontractors.schemas import CertificateCreate

        with pytest.raises(ValidationError):
            CertificateCreate(
                subcontractor_id=uuid.uuid4(),
                cert_type="insurance",
                document_url="../../etc/shadow",
            )

    def test_rejects_crlf_in_url(self) -> None:
        from app.modules.subcontractors.schemas import CertificateCreate

        with pytest.raises(ValidationError):
            CertificateCreate(
                subcontractor_id=uuid.uuid4(),
                cert_type="insurance",
                document_url="https://x.example/cert\r\nHost: evil",
            )

    def test_accepts_relative_upload_path(self) -> None:
        from app.modules.subcontractors.schemas import CertificateCreate

        ok = CertificateCreate(
            subcontractor_id=uuid.uuid4(),
            cert_type="insurance",
            document_url="uploads/abc-insurance.pdf",
        )
        assert ok.document_url == "uploads/abc-insurance.pdf"

    def test_accepts_https(self) -> None:
        from app.modules.subcontractors.schemas import CertificateCreate

        ok = CertificateCreate(
            subcontractor_id=uuid.uuid4(),
            cert_type="insurance",
            document_url="https://docs.example.com/policy.pdf",
        )
        assert ok.document_url.startswith("https://")

    def test_rejects_http_plain(self) -> None:
        from app.modules.subcontractors.schemas import CertificateCreate

        with pytest.raises(ValidationError):
            CertificateCreate(
                subcontractor_id=uuid.uuid4(),
                cert_type="insurance",
                document_url="http://docs.example.com/policy.pdf",
            )


# ── Certificate expiry sanity ─────────────────────────────────────────────


class TestCertificateExpiry:
    def test_rejects_backdated_valid_until(self) -> None:
        from app.modules.subcontractors.schemas import CertificateCreate

        with pytest.raises(ValidationError):
            CertificateCreate(
                subcontractor_id=uuid.uuid4(),
                cert_type="insurance",
                issue_date=date(2026, 5, 1),
                valid_until=date(2026, 4, 1),  # before issue_date
            )

    def test_rejects_year_out_of_range(self) -> None:
        from app.modules.subcontractors.schemas import CertificateCreate

        with pytest.raises(ValidationError):
            CertificateCreate(
                subcontractor_id=uuid.uuid4(),
                cert_type="insurance",
                valid_until=date(2999, 1, 1),
            )

    def test_accepts_reasonable_expiry(self) -> None:
        from app.modules.subcontractors.schemas import CertificateCreate

        ok = CertificateCreate(
            subcontractor_id=uuid.uuid4(),
            cert_type="insurance",
            issue_date=date(2026, 1, 1),
            valid_until=date(2027, 1, 1),
        )
        assert ok.valid_until == date(2027, 1, 1)


# ── Currency validation ───────────────────────────────────────────────────


class TestCurrencyIso4217:
    def test_agreement_rejects_invalid_currency(self) -> None:
        from app.modules.subcontractors.schemas import AgreementCreate

        with pytest.raises(ValidationError):
            AgreementCreate(
                subcontractor_id=uuid.uuid4(),
                project_id=uuid.uuid4(),
                title="X",
                currency="EURO",  # 4 chars, not ISO
            )

    def test_agreement_accepts_empty_currency_for_inherit(self) -> None:
        from app.modules.subcontractors.schemas import AgreementCreate

        ok = AgreementCreate(
            subcontractor_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            title="X",
            currency="",
        )
        assert ok.currency == ""

    def test_agreement_uppercases_lowercase_currency(self) -> None:
        from app.modules.subcontractors.schemas import AgreementCreate

        ok = AgreementCreate(
            subcontractor_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            title="X",
            currency="eur",
        )
        assert ok.currency == "EUR"

    def test_payment_app_rejects_invalid_currency(self) -> None:
        from app.modules.subcontractors.schemas import PaymentApplicationCreate

        with pytest.raises(ValidationError):
            PaymentApplicationCreate(
                agreement_id=uuid.uuid4(),
                gross_amount=Decimal("100"),
                currency="us",  # 2 chars
            )


# ── PII redaction in logs ─────────────────────────────────────────────────


class TestContactPiiNotInLogs:
    """Service-layer log lines must not interpolate raw e-mail / phone."""

    @pytest.mark.asyncio
    async def test_create_contact_log_redacts_email_and_phone(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        from app.modules.subcontractors.schemas import (
            SubcontractorContactCreate,
            SubcontractorCreate,
        )

        caplog.set_level(
            logging.INFO,
            logger="app.modules.subcontractors.service",
        )
        svc = _make_service()
        with patch("app.modules.subcontractors.service.event_bus.publish_detached"):
            sub = await svc.create_subcontractor(SubcontractorCreate(legal_name="Acme"))
            await svc.create_contact(
                SubcontractorContactCreate(
                    subcontractor_id=sub.id,
                    name="Bob",
                    role="Estimator",
                    email="bob.private@secret-domain.example",
                    phone="+49 170 99999999",
                ),
            )
        blob = "\n".join(rec.getMessage() for rec in caplog.records)
        assert "bob.private@secret-domain.example" not in blob, f"raw e-mail leaked into log stream: {blob!r}"
        assert "+49 170 99999999" not in blob
        assert "99999999" not in blob
        # Sanity — at least one redacted token IS present.
        assert "***" in blob

    @pytest.mark.asyncio
    async def test_update_contact_log_records_only_field_names(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        from app.modules.subcontractors.schemas import (
            SubcontractorContactCreate,
            SubcontractorContactUpdate,
            SubcontractorCreate,
        )

        svc = _make_service()
        with patch("app.modules.subcontractors.service.event_bus.publish_detached"):
            sub = await svc.create_subcontractor(SubcontractorCreate(legal_name="Acme"))
            created = await svc.create_contact(
                SubcontractorContactCreate(
                    subcontractor_id=sub.id,
                    name="Bob",
                    email="old@example.com",
                ),
            )
            caplog.clear()
            caplog.set_level(
                logging.INFO,
                logger="app.modules.subcontractors.service",
            )
            await svc.update_contact(
                created.id,
                SubcontractorContactUpdate(email="new-secret@example.com"),
            )
        blob = "\n".join(rec.getMessage() for rec in caplog.records)
        assert "new-secret@example.com" not in blob
        # Field NAME is fine — values are the PII.
        assert "email" in blob


# ── Prequal questionnaire DoS cap ─────────────────────────────────────────


class TestPrequalQuestionnaireCap:
    def test_rejects_oversize_questionnaire(self) -> None:
        from app.modules.subcontractors.schemas import PrequalRequest

        with pytest.raises(ValidationError):
            PrequalRequest(
                questionnaire={f"q{i}": "yes" for i in range(500)},
            )

    def test_rejects_overlong_answer_value(self) -> None:
        from app.modules.subcontractors.schemas import PrequalRequest

        with pytest.raises(ValidationError):
            PrequalRequest(
                questionnaire={"q1": "x" * 10_000},
            )

    def test_accepts_reasonable_questionnaire(self) -> None:
        from app.modules.subcontractors.schemas import PrequalRequest

        ok = PrequalRequest(
            questionnaire={
                "have_insurance": "yes",
                "iso_certified": False,
                "experience_years": 12,
            },
            score=80,
        )
        assert ok.score == 80


# ── Dashboard N+1 collapsed to 1+1 ────────────────────────────────────────


class TestDashboardSingleRetentionAndPaymentsQuery:
    """Before R5 the dashboard fired 2 queries per agreement (open
    payments + retention balance). After R5 it fires one of each."""

    @pytest.mark.asyncio
    async def test_dashboard_uses_batched_balance_and_count(self) -> None:
        from app.modules.subcontractors.models import Subcontractor
        from app.modules.subcontractors.schemas import (
            AgreementCreate,
            AgreementUpdate,
        )

        svc = _make_service()
        with patch("app.modules.subcontractors.service.event_bus.publish_detached"):
            sub_id = uuid.uuid4()
            sub_row = Subcontractor(
                legal_name="Acme",
                prequalification_status="approved",
            )
            sub_row.id = sub_id
            sub_row.is_active = True
            sub_row.rating_score = Decimal("0")
            svc.subs.rows[sub_id] = sub_row
            # Three agreements — pre-R5 would issue 3 + 3 = 6 calls.
            for i in range(3):
                ag = await svc.create_agreement(
                    AgreementCreate(
                        subcontractor_id=sub_id,
                        project_id=uuid.uuid4(),
                        title=f"A{i}",
                        currency="EUR",
                    ),
                )
                await svc.update_agreement(ag.id, AgreementUpdate(status="active"))

            await svc.dashboard(sub_id)

        # Single batched call to each of the two new repo methods.
        assert svc.payments.open_payments_calls == 1, (
            f"dashboard regressed to per-agreement payments queries: saw {svc.payments.open_payments_calls} calls"
        )
        assert svc.retention.balance_calls == 1, (
            f"dashboard regressed to per-agreement retention queries: saw {svc.retention.balance_calls} calls"
        )


# ── Events payload DoS cap (router-level) ─────────────────────────────────


class TestUpdateRatingEventsCap:
    @pytest.mark.asyncio
    async def test_router_rejects_oversize_events(self) -> None:
        """The router caps the events payload at 50 keys."""
        from app.modules.subcontractors import router as sub_router

        # Inspect the route signature directly so we don't need a full
        # FastAPI TestClient + auth stack here.
        update_route = next(
            r
            for r in sub_router.router.routes
            if getattr(r, "path", "") == "/ratings/" and "POST" in getattr(r, "methods", set())
        )
        handler = update_route.endpoint
        # The handler raises 422 when events len > 50.
        from app.modules.subcontractors.schemas import RatingCreate

        big_events = {f"k{i}": i for i in range(60)}
        with pytest.raises(HTTPException) as exc:
            await handler(
                data=RatingCreate(
                    subcontractor_id=uuid.uuid4(),
                    period="2026-05",
                ),
                session=None,  # type: ignore[arg-type]
                _user="u1",
                events=big_events,
                _perm=None,
            )
        assert exc.value.status_code == 422


# ── Migration metadata smoke ──────────────────────────────────────────────


class TestMigrationMetadata:
    def test_v3099_subcontractors_revision_chain(self) -> None:
        """The new migration declares ``v3098`` as its parent so a
        future single-head merge can chain off it deterministically.

        ``backend/alembic/versions/`` is not a Python package — load the
        file directly via importlib's file-loader so the test stays
        decoupled from how alembic discovers scripts at runtime.
        """
        from importlib.util import module_from_spec, spec_from_file_location
        from pathlib import Path

        # Walk up from this test file: backend/tests/unit/<this>.py →
        # backend/alembic/versions/v3099_subcontractors_unique_tax_id.py
        mig_path = (
            Path(__file__).resolve().parents[2] / "alembic" / "versions" / "v3099_subcontractors_unique_tax_id.py"
        )
        assert mig_path.exists(), f"migration file missing at {mig_path}"
        spec = spec_from_file_location("_v3099_sub", mig_path)
        assert spec is not None
        assert spec.loader is not None
        mod = module_from_spec(spec)
        spec.loader.exec_module(mod)

        assert mod.down_revision == "v3098"
        # The revision ID (what alembic_version stores) is the short form
        # `v3099_subs` — the sibling v3099 migrations follow the same
        # convention (`v3099_rfi`, `v3099_subm`, `v3099_eac`) so they can
        # all chain off the same `v3098` tip without exceeding the
        # alembic_version VARCHAR(32) limit when later merge nodes
        # concatenate them. The longer file name is documentation only.
        assert mod.revision == "v3099_subs"
        assert callable(mod.upgrade)
        assert callable(mod.downgrade)
