"""ZATCA service tests: the chain, onboarding, and a document's whole way through the clearance module.

Runs against the shared PostgreSQL unit database with per-test transaction isolation, like
``test_einvoice_clearance_module.py``. ZATCA is a fake behind ``httpx.MockTransport``: it reads the CSR it
is sent and answers with a certificate for that very key, so the signing path is the real one.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.x509.oid import NameOID
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt_secret
from app.modules.einvoice_clearance import adapters, repository, schemas
from app.modules.einvoice_clearance import service as clearance
from app.modules.einvoice_clearance.models import EInvoiceProfile
from app.modules.einvoice_clearance.validators import register_einvoice_clearance_rules
from app.modules.einvoice_zatca import adapter as zatca_adapter
from app.modules.einvoice_zatca import checks, service, signing
from app.modules.einvoice_zatca.client import FatooraClient
from app.modules.einvoice_zatca.codes import FIRST_PREVIOUS_HASH
from app.modules.einvoice_zatca.models import ZatcaChainEntry
from app.modules.einvoice_zatca.validators import register_zatca_rules
from tests._pg import transactional_session

SELLER_VAT = "399999999900003"
RIYADH = dt.timezone(dt.timedelta(hours=3))
NOW = dt.datetime(2026, 10, 19, 10, 0, 0, tzinfo=RIYADH)

CSR_FIELDS = {
    "serial_number": "1-OCE|2-1|3-ed22f1d8-e6a2-1118-9b58-d9a8f11e445f",
    "organization_unit": "Riyadh Branch",
    "organization_name": "Maximum Speed Tech Supply LTD",
    "location": "Riyadh 12214",
    "industry": "Construction",
    "invoice_type": "1100",
}

SETTINGS = {
    "zatca": {
        "seller": {
            "name": "Maximum Speed Tech Supply LTD",
            "id_scheme": "CRN",
            "id_value": "1010010000",
            "address": {
                "street": "Prince Sultan Street",
                "building_number": "1234",
                "additional_number": "5678",
                "district": "Al Olaya",
                "city": "Riyadh",
                "postal_zone": "12214",
            },
        }
    }
}

BUYER = {
    "name": "Owner Co",
    "vat_id": "399999999800003",
    "line1": "Olaya Road",
    "building_number": "4321",
    "district": "Al Olaya",
    "city": "Riyadh",
    "postcode": "12345",
}

LINES = [
    {
        "description": "Interim payment certificate 4",
        "quantity": "1",
        "unit": "pcs",
        "unit_rate": "5000000",
        "amount": "5000000",
        "vat_rate": "15",
        "vat_category": "S",
    }
]
INVOICE = {"invoice_number": "IPC-4", "invoice_date": "2026-10-19", "currency_code": "SAR"}


# ── A fake ZATCA ─────────────────────────────────────────────────────────────


class FakeZatca:
    """The FATOORA gateway, as far as the integration uses it."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, str], dict]] = []
        self.ca_key = signing.generate_key()
        self.refuse_csid_with: int | None = None
        self.document_status = 200
        self.document_errors: list[dict] = []
        self.compliance_errors_for: set[str] = set()
        self.clearance_status = "CLEARED"

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def client(self, environment: str) -> FatooraClient:
        return FatooraClient(environment, transport=self.transport())

    def _certificate_for(self, csr_b64: str) -> tuple[str, str]:
        request = x509.load_pem_x509_csr(base64.b64decode(csr_b64))
        issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "TEST-ZATCA-CA")])
        certificate = (
            x509.CertificateBuilder()
            .subject_name(request.subject)
            .issuer_name(issuer)
            .public_key(request.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(dt.datetime(2026, 1, 1, tzinfo=dt.UTC))
            .not_valid_after(dt.datetime(2030, 1, 1, tzinfo=dt.UTC))
            .sign(self.ca_key, hashes.SHA256())
        )
        der = certificate.public_bytes(serialization.Encoding.DER)
        return base64.b64encode(base64.b64encode(der)).decode("ascii"), uuid.uuid4().hex

    def _handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        path = request.url.path
        self.calls.append((request.method, path, dict(request.headers), body))
        if path.endswith("/compliance") and request.method == "POST":
            if self.refuse_csid_with:
                return httpx.Response(self.refuse_csid_with, json={"message": "Invalid OTP"})
            token, secret = self._certificate_for(body["csr"])
            return httpx.Response(
                200,
                json={
                    "requestID": "1234567890",
                    "dispositionMessage": "ISSUED",
                    "binarySecurityToken": token,
                    "secret": secret,
                },
            )
        if path.endswith("/production/csids"):
            if request.method == "PATCH" and self.refuse_csid_with:
                return httpx.Response(self.refuse_csid_with, json={"message": "Invalid OTP"})
            token, secret = (
                self._certificate_for(body["csr"]) if "csr" in body else self._certificate_for(self._last_csr())
            )
            return httpx.Response(
                200,
                json={
                    "requestID": "9876543210",
                    "dispositionMessage": "ISSUED",
                    "binarySecurityToken": token,
                    "secret": secret,
                },
            )
        if path.endswith("/compliance/invoices"):
            kind = base64.b64decode(body["invoice"]).decode("utf-8")
            failing = any(marker in kind for marker in self.compliance_errors_for)
            return self._document(failing)
        if path.endswith(("/invoices/clearance/single", "/invoices/reporting/single")):
            return self._document(bool(self.document_errors))
        return httpx.Response(404, json={})

    def _last_csr(self) -> str:
        for _method, path, _headers, body in reversed(self.calls):
            if path.endswith("/compliance") and "csr" in body:
                return body["csr"]
        raise AssertionError("no CSR was sent before the production CSID")

    def _document(self, failing: bool) -> httpx.Response:
        if self.document_status in (401, 500, 503):
            return httpx.Response(self.document_status, json={})
        errors = self.document_errors or (
            [{"type": "ERROR", "code": "BR-KSA-01", "category": "KSA", "message": "Sample refused", "status": "ERROR"}]
            if failing
            else []
        )
        if errors:
            return httpx.Response(400, json={"validationResults": {"status": "ERROR", "errorMessages": errors}})
        payload = {
            "validationResults": {
                "status": "WARNING" if self.document_status == 202 else "PASS",
                "warningMessages": [
                    {"type": "WARNING", "code": "BR-KSA-W", "category": "KSA", "message": "Check", "status": "WARNING"}
                ]
                if self.document_status == 202
                else [],
            }
        }
        path = self.calls[-1][1]
        if path.endswith("/clearance/single"):
            payload["clearanceStatus"] = self.clearance_status
            payload["clearedInvoice"] = base64.b64encode(b"<Invoice>cleared</Invoice>").decode()
        elif path.endswith("/reporting/single"):
            payload["reportingStatus"] = "REPORTED"
        return httpx.Response(self.document_status if self.document_status in (200, 202) else 200, json=payload)


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session() as s:
        yield s


@pytest.fixture(autouse=True)
def _registries():
    register_einvoice_clearance_rules()
    register_zatca_rules()
    adapters.register_builtin_adapters()
    yield
    adapters.adapter_registry._adapters.pop(zatca_adapter.ZATCA_ADAPTER_KEY, None)


@pytest.fixture
def fake() -> FakeZatca:
    return FakeZatca()


async def sa_profile(session: AsyncSession, **overrides) -> EInvoiceProfile:
    values = {
        "company_key": f"acme-{uuid.uuid4().hex[:8]}",
        "country": "SA",
        "regime": "clearance",
        "platform": "ZATCA FATOORA",
        "tax_registration_id": SELLER_VAT,
        "network_participant_id": "",
        "certificate_reference": "unit:EGS1",
        "adapter_key": zatca_adapter.ZATCA_ADAPTER_KEY,
        "sandbox": True,
        "is_active": True,
        "settings": SETTINGS,
    }
    values.update(overrides)
    return await repository.add_profile(session, EInvoiceProfile(**values))


async def onboarded(session, fake, profile, *, key="EGS1", signer_kind="stored_key"):
    unit = await service.create_unit(
        session, profile=profile, unit_key=key, csr_fields=CSR_FIELDS, signer_kind=signer_kind
    )
    await service.prepare_csr(session, unit)
    await service.request_compliance_csid(session, unit, otp="123456", client=fake.client(unit.environment))
    return unit


async def build(session, profile, *, lines=None, fields=None, now=NOW, buyer=BUYER, invoice=None):
    return await service.build_document(
        session,
        profile=profile,
        invoice=invoice or INVOICE,
        lines=lines or LINES,
        buyer=buyer,
        zatca_fields=fields or {},
        invoice_id=None,
        now=now,
    )


# ── The chain ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestChain:
    async def test_documents_take_counters_in_order_and_each_points_at_the_last(self, session, fake):
        profile = await sa_profile(session)
        unit = await onboarded(session, fake, profile)
        seen = []
        for number in (1, 2, 3):
            text, _ = await build(session, profile, invoice={**INVOICE, "invoice_number": f"IPC-{number}"})
            seen.append(text)
        entries = (
            (await session.execute(select(ZatcaChainEntry).where(ZatcaChainEntry.unit_id == unit.id))).scalars().all()
        )
        entries = sorted(entries, key=lambda e: e.icv)
        assert [e.icv for e in entries] == [1, 2, 3]
        assert entries[0].previous_hash == FIRST_PREVIOUS_HASH
        assert entries[1].previous_hash == entries[0].invoice_hash
        assert entries[2].previous_hash == entries[1].invoice_hash
        assert (unit.last_icv, unit.last_hash) == (3, entries[2].invoice_hash)
        # The document says the same thing the chain row does.
        assert "<cbc:UUID>3</cbc:UUID>" in seen[2]
        assert checks.read_identity(seen[2])[0] == entries[2].invoice_uuid

    async def test_a_second_unit_starts_its_own_chain(self, session, fake):
        profile = await sa_profile(session)
        first = await onboarded(session, fake, profile, key="EGS1")
        second = await onboarded(session, fake, profile, key="EGS2")
        await build(session, profile, fields={"egs_unit": "EGS1"})
        await build(session, profile, fields={"egs_unit": "EGS1"})
        await build(session, profile, fields={"egs_unit": "EGS2"})
        assert (first.last_icv, second.last_icv) == (2, 1)

    async def test_a_counter_cannot_be_taken_twice(self, session, fake):
        profile = await sa_profile(session)
        unit = await onboarded(session, fake, profile)
        await build(session, profile)
        async with session.begin_nested():
            session.add(
                ZatcaChainEntry(
                    unit_id=unit.id,
                    icv=1,
                    invoice_uuid=str(uuid.uuid4()),
                    previous_hash="a",
                    invoice_hash="b",
                )
            )
            with pytest.raises(IntegrityError):
                await session.flush()

    async def test_a_document_uuid_belongs_to_one_chain_entry(self, session, fake):
        profile = await sa_profile(session)
        unit = await onboarded(session, fake, profile)
        text, _ = await build(session, profile)
        known = checks.read_identity(text)[0]
        async with session.begin_nested():
            session.add(
                ZatcaChainEntry(unit_id=unit.id, icv=99, invoice_uuid=known, previous_hash="a", invoice_hash="b")
            )
            with pytest.raises(IntegrityError):
                await session.flush()

    async def test_a_refused_build_costs_no_counter(self, session, fake):
        profile = await sa_profile(session)
        unit = await onboarded(session, fake, profile)
        bad = [{**LINES[0], "quantity": "-1", "amount": "-5000000"}]
        with pytest.raises(service.ZatcaServiceError, match="credit note"):
            await build(session, profile, lines=bad)
        assert (unit.last_icv, unit.last_hash) == (0, "")
        await build(session, profile)
        assert unit.last_icv == 1

    async def test_retention_release_is_refused_with_the_guideline_reference(self, session, fake):
        profile = await sa_profile(session)
        unit = await onboarded(session, fake, profile)
        with pytest.raises(service.ZatcaServiceError, match="§5.2"):
            await build(session, profile, fields={"kind": "retention_release"})
        assert unit.last_icv == 0

    async def test_vat_is_billed_on_the_gross_whatever_the_invoice_says_about_retention(self, session, fake):
        profile = await sa_profile(session)
        await onboarded(session, fake, profile)
        text, _ = await build(session, profile, invoice={**INVOICE, "retention_amount": "500000"})
        assert '<cbc:TaxAmount currencyID="SAR">750000.00</cbc:TaxAmount>' in text

    async def test_a_registration_without_a_unit_cannot_issue(self, session):
        profile = await sa_profile(session)
        with pytest.raises(service.ZatcaServiceError, match="no EGS unit"):
            await build(session, profile)

    async def test_several_units_need_the_document_to_name_one(self, session, fake):
        profile = await sa_profile(session)
        await onboarded(session, fake, profile, key="EGS1")
        await onboarded(session, fake, profile, key="EGS2")
        with pytest.raises(service.ZatcaServiceError, match="egs_unit"):
            await build(session, profile)
        with pytest.raises(service.ZatcaServiceError, match="no unit 'EGS9'"):
            await build(session, profile, fields={"egs_unit": "EGS9"})

    async def test_a_revoked_unit_does_not_stamp(self, session, fake):
        profile = await sa_profile(session)
        unit = await onboarded(session, fake, profile)
        await service.revoke(session, unit)
        with pytest.raises(service.ZatcaServiceError, match="no EGS unit"):
            await build(session, profile)

    async def test_a_live_registration_stamps_only_from_an_active_unit(self, session, fake):
        profile = await sa_profile(session, sandbox=False)
        unit = await service.create_unit(
            session, profile=profile, unit_key="EGS1", csr_fields=CSR_FIELDS, signer_kind="stored_key"
        )
        assert unit.environment == "production"
        with pytest.raises(service.ZatcaServiceError, match="active unit"):
            await build(session, profile)

    async def test_an_expired_certificate_blocks_a_live_unit(self, session, fake):
        profile = await sa_profile(session, sandbox=False)
        unit = await service.create_unit(
            session, profile=profile, unit_key="EGS1", csr_fields=CSR_FIELDS, signer_kind="stored_key"
        )
        unit.state = "active"
        unit.certificate_not_after = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
        with pytest.raises(service.ZatcaServiceError, match="expired"):
            await build(session, profile)

    async def test_a_sandbox_test_signer_stamps_without_a_certificate(self, session):
        profile = await sa_profile(session)
        unit = await service.create_unit(
            session, profile=profile, unit_key="EGS1", csr_fields=CSR_FIELDS, signer_kind="test"
        )
        text, _ = await build(session, profile)
        assert checks.check_document(text, profile_vat=SELLER_VAT, now=NOW) == []
        assert unit.last_icv == 1


# ── Onboarding ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestOnboarding:
    async def test_the_whole_path_ends_with_an_active_unit_that_stamps(self, session, fake):
        profile = await sa_profile(session)
        unit = await service.create_unit(
            session, profile=profile, unit_key="EGS1", csr_fields=CSR_FIELDS, signer_kind="stored_key"
        )
        assert unit.state == "new" and unit.environment == "developer_portal"
        await service.prepare_csr(session, unit)
        assert unit.state == "csr_ready" and unit.private_key_encrypted
        client = fake.client(unit.environment)
        await service.request_compliance_csid(session, unit, otp="123456", client=client)
        assert unit.state == "compliance_issued" and unit.compliance_request_id == "1234567890"
        await service.run_compliance_checks(session, unit, profile=profile, client=client)
        assert unit.state == "compliance_passed"
        # One 388, 381 and 383 of each kind the unit is configured for: standard and simplified.
        assert sorted(unit.compliance_results) == sorted(
            f"{kind}_{label}"
            for kind in ("standard", "simplified")
            for label in ("invoice", "credit_note", "debit_note")
        )
        await service.request_production_csid(session, unit, client=client)
        assert unit.state == "active" and unit.production_request_id == "9876543210"
        text, _ = await build(session, profile)
        assert checks.check_document(text, profile_vat=SELLER_VAT, now=NOW) == []

    async def test_secrets_are_encrypted_at_rest_and_never_in_the_view(self, session, fake):
        profile = await sa_profile(session)
        unit = await onboarded(session, fake, profile)
        issued = fake.calls[-1]
        assert unit.compliance_secret_encrypted
        secret = decrypt_secret(unit.compliance_secret_encrypted)
        assert secret and secret != unit.compliance_secret_encrypted
        assert decrypt_secret(unit.private_key_encrypted).startswith("-----BEGIN PRIVATE KEY-----")
        view = json.dumps(service.unit_as_dict(unit), default=str)
        for leaked in (secret, unit.compliance_token, unit.compliance_secret_encrypted, unit.private_key_encrypted):
            assert leaked not in view
        assert issued  # the CSID call happened

    async def test_the_compliance_checks_use_a_counter_of_their_own(self, session, fake):
        profile = await sa_profile(session)
        unit = await onboarded(session, fake, profile)
        await service.run_compliance_checks(session, unit, profile=profile, client=fake.client(unit.environment))
        assert unit.last_icv == 0

    async def test_a_refused_otp_leaves_the_unit_where_it_was(self, session, fake):
        profile = await sa_profile(session)
        unit = await service.create_unit(
            session, profile=profile, unit_key="EGS1", csr_fields=CSR_FIELDS, signer_kind="stored_key"
        )
        await service.prepare_csr(session, unit)
        fake.refuse_csid_with = 400
        with pytest.raises(service.ZatcaServiceError, match="Invalid OTP"):
            await service.request_compliance_csid(session, unit, otp="000000", client=fake.client(unit.environment))
        assert unit.state == "csr_ready" and unit.compliance_token == "" and "Invalid OTP" in unit.last_error

    async def test_a_failed_compliance_check_does_not_advance_the_unit(self, session, fake):
        profile = await sa_profile(session)
        unit = await onboarded(session, fake, profile)
        fake.compliance_errors_for = {'name="0200000">381<'}
        await service.run_compliance_checks(session, unit, profile=profile, client=fake.client(unit.environment))
        assert unit.state == "compliance_issued"
        assert unit.compliance_results["simplified_credit_note"]["accepted"] is False
        assert unit.compliance_results["standard_invoice"]["accepted"] is True
        assert "simplified credit note" in unit.last_error
        with pytest.raises(service.ZatcaServiceError, match="compliance checks passed"):
            await service.request_production_csid(session, unit, client=fake.client(unit.environment))

    async def test_every_transition_the_path_does_not_draw_is_refused(self, session):
        drawn = {
            ("new", "csr_ready"),
            ("csr_ready", "compliance_issued"),
            ("compliance_issued", "compliance_passed"),
            ("compliance_passed", "active"),
            ("active", "active"),
        }
        for source in service.TRANSITIONS:
            for target in service.TRANSITIONS:
                expected = (source, target) in drawn or (target == "revoked" and source != "revoked")
                assert service.can_transition(source, target) is expected, (source, target)

    async def test_steps_out_of_order_are_conflicts(self, session, fake):
        profile = await sa_profile(session)
        unit = await service.create_unit(
            session, profile=profile, unit_key="EGS1", csr_fields=CSR_FIELDS, signer_kind="stored_key"
        )
        client = fake.client(unit.environment)
        with pytest.raises(service.ZatcaServiceError) as excinfo:
            await service.request_compliance_csid(session, unit, otp="1", client=client)
        assert excinfo.value.conflict is True
        with pytest.raises(service.ZatcaServiceError):
            await service.run_compliance_checks(session, unit, profile=profile, client=client)
        with pytest.raises(service.ZatcaServiceError):
            await service.renew(session, unit, otp="1", client=client)
        await service.prepare_csr(session, unit)
        with pytest.raises(service.ZatcaServiceError, match="once"):
            await service.prepare_csr(session, unit)
        assert fake.calls == []

    async def test_renewal_replaces_the_key_only_after_zatca_answered(self, session, fake):
        profile = await sa_profile(session)
        unit = await onboarded(session, fake, profile)
        client = fake.client(unit.environment)
        await service.run_compliance_checks(session, unit, profile=profile, client=client)
        await service.request_production_csid(session, unit, client=client)
        old_key, old_token = unit.private_key_encrypted, unit.production_token
        fake.refuse_csid_with = 400
        with pytest.raises(service.ZatcaServiceError, match="Invalid OTP"):
            await service.renew(session, unit, otp="000000", client=client)
        assert (unit.private_key_encrypted, unit.production_token) == (old_key, old_token)
        fake.refuse_csid_with = None
        await service.renew(session, unit, otp="654321", client=client)
        assert unit.private_key_encrypted != old_key and unit.production_token != old_token
        assert unit.state == "active"
        method, path, _headers, _body = fake.calls[-1]
        assert (method, path.endswith("/production/csids")) == ("PATCH", True)

    async def test_revoked_is_final(self, session, fake):
        profile = await sa_profile(session)
        unit = await onboarded(session, fake, profile)
        await service.revoke(session, unit)
        assert unit.state == "revoked"
        with pytest.raises(service.ZatcaServiceError):
            await service.revoke(session, unit)

    async def test_a_live_registration_cannot_use_a_test_signer_or_a_sandbox_gateway(self, session):
        profile = await sa_profile(session, sandbox=False)
        with pytest.raises(service.ZatcaServiceError, match="live"):
            await service.create_unit(
                session, profile=profile, unit_key="EGS1", csr_fields=CSR_FIELDS, signer_kind="test"
            )
        with pytest.raises(service.ZatcaServiceError, match="live registration"):
            await service.create_unit(
                session,
                profile=profile,
                unit_key="EGS1",
                csr_fields=CSR_FIELDS,
                signer_kind="stored_key",
                environment="simulation",
            )
        sandbox = await sa_profile(session)
        with pytest.raises(service.ZatcaServiceError, match="sandbox"):
            await service.create_unit(
                session,
                profile=sandbox,
                unit_key="EGS1",
                csr_fields=CSR_FIELDS,
                signer_kind="stored_key",
                environment="production",
            )

    async def test_a_unit_key_is_unique_per_registration(self, session):
        profile = await sa_profile(session)
        await service.create_unit(session, profile=profile, unit_key="EGS1", csr_fields=CSR_FIELDS, signer_kind="test")
        with pytest.raises(service.ZatcaServiceError, match="already has"):
            await service.create_unit(
                session, profile=profile, unit_key="EGS1", csr_fields=CSR_FIELDS, signer_kind="test"
            )

    async def test_a_unit_belongs_to_a_saudi_registration(self, session):
        other = await sa_profile(session, country="MX", regime="clearance")
        with pytest.raises(service.ZatcaServiceError, match="Saudi"):
            await service.create_unit(session, profile=other, unit_key="U", csr_fields={}, signer_kind="test")

    async def test_csr_fields_zatca_would_refuse_stop_the_csr(self, session):
        profile = await sa_profile(session)
        unit = await service.create_unit(
            session,
            profile=profile,
            unit_key="EGS1",
            csr_fields={**CSR_FIELDS, "organization_name": "Bad_Name"},
            signer_kind="stored_key",
        )
        with pytest.raises(service.ZatcaServiceError, match="must not contain"):
            await service.prepare_csr(session, unit)
        assert unit.state == "new" and unit.private_key_encrypted == ""

    async def test_a_signing_service_unit_brings_its_own_csr(self, session):
        profile = await sa_profile(session)
        unit = await service.create_unit(
            session,
            profile=profile,
            unit_key="EGS1",
            csr_fields=CSR_FIELDS,
            signer_kind="external_http",
            signer_config={"url": "https://signer.example/sign"},
        )
        with pytest.raises(service.ZatcaServiceError, match="needs the CSR"):
            await service.prepare_csr(session, unit)
        from app.modules.einvoice_zatca import csr as csr_module

        pem = csr_module.build_csr(
            csr_module.CsrFields.from_dict({**CSR_FIELDS, "common_name": "EGS1", "vat_number": SELLER_VAT}),
            signing.generate_key(),
            environment="developer_portal",
        )
        await service.prepare_csr(session, unit, csr_pem=pem)
        assert unit.state == "csr_ready" and unit.private_key_encrypted == ""


# ── A document's whole way through the clearance module ──────────────────────


def _install_adapter(session: AsyncSession, fake: FakeZatca) -> None:
    async def loader(invoice_uuid: str):
        unit = await service.unit_for_document_uuid(session, invoice_uuid)
        if unit is None:
            return None
        return zatca_adapter.UnitAccess(unit.unit_key, unit.state, unit.environment, service.unit_credentials(unit))

    adapters.adapter_registry.register(zatca_adapter.ZatcaAdapter(credential_loader=loader, transport=fake.transport()))


async def clearance_document(session, profile, text):
    body = schemas.DocumentCreateRequest(
        project_id=uuid.uuid4(),
        profile_id=profile.id,
        invoice_number="IPC-4",
        invoice_date="2026-10-19",
        currency_code="SAR",
        total_amount="5750000.00",
        country_fields={},
        payload=text,
    )
    document, _ = await clearance.create_document(session, profile=profile, body=body)
    return document


@pytest.mark.asyncio
class TestThroughTheClearanceModule:
    @pytest.fixture(autouse=True)
    def _clock_at_the_fixture_date(self, monkeypatch):
        # The invoices are issued at NOW. The 24-hour reporting-deadline rule reads the
        # wall clock, so without this the simplified invoice turns "late" two days on
        # and the test starts failing for no change in the code under test.
        monkeypatch.setattr(clearance, "_now", lambda: NOW.astimezone(dt.UTC))

    async def test_a_standard_invoice_is_cleared_and_keeps_the_stamped_xml(self, session, fake):
        profile = await sa_profile(session)
        await onboarded(session, fake, profile)
        _install_adapter(session, fake)
        text, _ = await build(session, profile)
        document = await clearance_document(session, profile, text)
        document, outcome, _ = await clearance.submit_document(session, document=document, profile=profile)
        assert outcome.accepted and document.status == "cleared"
        assert document.authority_identifier == checks.read_identity(text)[0]
        method, path, headers, body = fake.calls[-1]
        assert path.endswith("/invoices/clearance/single") and headers["clearance-status"] == "1"
        assert headers["authorization"].startswith("Basic ")
        assert base64.b64decode(body["invoice"]).decode("utf-8") == text
        events = await repository.list_events(session, document.id)
        assert events[-1].raw_response["cleared_invoice"]

    async def test_a_simplified_invoice_is_reported_not_cleared(self, session, fake):
        # The distinguishing case for the per-outcome act: without it a reported
        # invoice would be recorded as cleared, which it legally is not.
        profile = await sa_profile(session)
        await onboarded(session, fake, profile)
        _install_adapter(session, fake)
        text, _ = await build(session, profile, fields={"simplified": True}, buyer=None)
        document = await clearance_document(session, profile, text)
        document, outcome, _ = await clearance.submit_document(session, document=document, profile=profile)
        assert outcome.accepted and document.status == "reported"
        _method, path, headers, _body = fake.calls[-1]
        assert path.endswith("/invoices/reporting/single") and headers["clearance-status"] == "0"

    async def test_zatca_warnings_are_kept_and_do_not_reject(self, session, fake):
        profile = await sa_profile(session)
        await onboarded(session, fake, profile)
        _install_adapter(session, fake)
        fake.document_status = 202
        text, _ = await build(session, profile)
        document = await clearance_document(session, profile, text)
        document, outcome, _ = await clearance.submit_document(session, document=document, profile=profile)
        assert document.status == "cleared" and "1 warning" in outcome.message

    async def test_a_refusal_is_a_rejection_with_zatcas_code(self, session, fake):
        profile = await sa_profile(session)
        await onboarded(session, fake, profile)
        _install_adapter(session, fake)
        fake.document_errors = [
            {"type": "ERROR", "code": "BR-KSA-F-06", "category": "KSA", "message": "Bad total", "status": "ERROR"}
        ]
        text, _ = await build(session, profile)
        document = await clearance_document(session, profile, text)
        document, outcome, _ = await clearance.submit_document(session, document=document, profile=profile)
        assert not outcome.accepted and document.status == "rejected"
        assert document.rejection_code == "BR-KSA-F-06" and "Bad total" in document.rejection_message

    async def test_an_unreachable_gateway_leaves_the_document_in_doubt(self, session, fake):
        profile = await sa_profile(session)
        await onboarded(session, fake, profile)
        _install_adapter(session, fake)
        fake.document_status = 503
        text, _ = await build(session, profile)
        document = await clearance_document(session, profile, text)
        with pytest.raises(clearance.ClearanceError, match="unknown outcome"):
            await clearance.submit_document(session, document=document, profile=profile)
        assert document.status == "submitted"

    async def test_a_tampered_stamp_is_stopped_before_the_adapter(self, session, fake):
        profile = await sa_profile(session)
        await onboarded(session, fake, profile)
        _install_adapter(session, fake)
        text, _ = await build(session, profile)
        tampered = text.replace("<cbc:ID>IPC-4</cbc:ID>", "<cbc:ID>IPC-5</cbc:ID>", 1)
        assert tampered != text
        document = await clearance_document(session, profile, tampered)
        with pytest.raises(clearance.ClearanceError) as excinfo:
            await clearance.submit_document(session, document=document, profile=profile)
        assert any(f.rule_id == "einvoice_clearance.zatca_stamp" for f in excinfo.value.findings)
        assert not [c for c in fake.calls if "invoices/clearance" in c[1]]

    async def test_a_document_no_unit_of_ours_built_is_refused_by_the_adapter(self, session, fake):
        profile = await sa_profile(session)
        await onboarded(session, fake, profile)
        _install_adapter(session, fake)
        text, _ = await build(session, profile)
        foreign = text.replace(checks.read_identity(text)[0], str(uuid.uuid4()))
        # The foreign UUID breaks the stamp's hash too, so call the adapter directly.
        outcome = await adapters.adapter_registry.get("zatca_fatoora").submit(
            adapters.SubmissionRequest(
                country="SA",
                regime="clearance",
                document_format="zatca_phase2",
                payload=foreign.encode("utf-8"),
                payload_hash="x",
                payload_media_type="application/xml",
                profile={"sandbox": True},
            )
        )
        assert not outcome.accepted and outcome.rejection_code == zatca_adapter.CODE_NO_UNIT

    async def test_a_unit_without_a_csid_cannot_send(self, session, fake):
        profile = await sa_profile(session)
        await service.create_unit(session, profile=profile, unit_key="EGS1", csr_fields=CSR_FIELDS, signer_kind="test")
        _install_adapter(session, fake)
        text, _ = await build(session, profile)
        document = await clearance_document(session, profile, text)
        document, outcome, _ = await clearance.submit_document(session, document=document, profile=profile)
        assert document.status == "rejected" and document.rejection_code == zatca_adapter.CODE_NOT_ONBOARDED
        assert fake.calls == []

    async def test_cancellation_points_at_the_credit_note(self, session):
        outcome = await zatca_adapter.ZatcaAdapter().cancel(
            adapters.CancellationRequest(
                country="SA",
                regime="clearance",
                authority_identifier="x",
                reason="Wrong buyer",
                regime_spec={
                    "correction_mechanism": "credit note (381) or debit note (383) through the same integration"
                },
            )
        )
        assert not outcome.accepted and outcome.rejection_code == zatca_adapter.CODE_NO_CANCELLATION
        assert "381" in outcome.rejection_message
