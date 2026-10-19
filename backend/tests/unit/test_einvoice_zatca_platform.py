"""ZATCA platform tests: the client and adapter against a mock gateway, the rules, the registry row and the wiring.

No database and no network. The adapter takes its credentials from an injected loader and talks through
``httpx.MockTransport``.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
from pathlib import Path

import httpx
import pytest

from app.core.party_identifiers import check as check_identifier
from app.modules.einvoice_clearance import adapters, regimes
from app.modules.einvoice_clearance.validators import evaluate, register_einvoice_clearance_rules
from app.modules.einvoice_zatca import adapter as za
from app.modules.einvoice_zatca import checks, data
from app.modules.einvoice_zatca.client import Credentials, FatooraClient, FatooraError
from app.modules.einvoice_zatca.validators import register_zatca_rules
from tests.unit.test_einvoice_zatca_document import SELLER_VAT, make_input, stamped

CREDENTIALS = Credentials("token-b64", "secret")


def request_for(text: str, **profile) -> adapters.SubmissionRequest:
    return adapters.SubmissionRequest(
        country="SA",
        regime="clearance",
        document_format="zatca_phase2",
        payload=text.encode("utf-8"),
        payload_hash="x",
        payload_media_type="application/xml",
        profile={"sandbox": True, **profile},
    )


def adapter_with(handler, *, access: za.UnitAccess | None = None) -> tuple[za.ZatcaAdapter, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    async def loader(_uuid: str):
        return access or za.UnitAccess("EGS1", "active", "developer_portal", CREDENTIALS)

    return za.ZatcaAdapter(credential_loader=loader, transport=httpx.MockTransport(record)), seen


def accepted(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/clearance/single"):
        return httpx.Response(
            200,
            json={
                "clearanceStatus": "CLEARED",
                "clearedInvoice": "PEludm9pY2UvPg==",
                "validationResults": {"status": "PASS"},
            },
        )
    return httpx.Response(200, json={"reportingStatus": "REPORTED", "validationResults": {"status": "PASS"}})


# ── The adapter ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestAdapter:
    async def test_the_subtype_decides_between_clearance_and_reporting(self):
        adapter, seen = adapter_with(accepted)
        _r, _s, standard, _ = await stamped(make_input())
        _r, _s, simplified, _ = await stamped(make_input(simplified=True))
        cleared = await adapter.submit(request_for(standard))
        reported = await adapter.submit(request_for(simplified))
        assert (cleared.accepted, cleared.act) == (True, "clearance")
        assert (reported.accepted, reported.act) == (True, "reporting")
        assert seen[0].url.path.endswith("/invoices/clearance/single")
        assert seen[1].url.path.endswith("/invoices/reporting/single")
        assert seen[0].headers["clearance-status"] == "1" and seen[1].headers["clearance-status"] == "0"
        assert seen[0].headers["accept-version"] == "V2"
        assert seen[0].url.host == "gw-fatoora.zatca.gov.sa" and "developer-portal" in seen[0].url.path

    async def test_the_body_carries_the_hash_the_uuid_and_the_exact_document(self):
        adapter, seen = adapter_with(accepted)
        _r, stamp, text, _ = await stamped(make_input())
        await adapter.submit(request_for(text))
        body = json.loads(seen[0].content)
        assert body["invoiceHash"] == stamp.invoice_hash
        assert body["uuid"] == "8e6000cf-1a98-4174-b3e7-b5d5954bc10d"
        assert base64.b64decode(body["invoice"]).decode("utf-8") == text
        user, _, password = base64.b64decode(seen[0].headers["authorization"].split()[1]).decode().partition(":")
        assert (user, password) == ("token-b64", "secret")

    async def test_the_cleared_xml_is_kept_for_the_buyer(self):
        adapter, _ = adapter_with(accepted)
        _r, _s, text, _ = await stamped(make_input())
        outcome = await adapter.submit(request_for(text))
        assert outcome.raw_response["cleared_invoice"] == "PEludm9pY2UvPg=="
        assert outcome.authority_identifier == "8e6000cf-1a98-4174-b3e7-b5d5954bc10d"

    async def test_a_202_is_an_acceptance_with_its_warnings(self):
        def warned(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                202,
                json={
                    "reportingStatus": "REPORTED",
                    "validationResults": {
                        "status": "WARNING",
                        "warningMessages": [
                            {"type": "WARNING", "code": "W1", "category": "c", "message": "m", "status": "WARNING"}
                        ],
                    },
                },
            )

        adapter, _ = adapter_with(warned)
        _r, _s, text, _ = await stamped(make_input(simplified=True))
        outcome = await adapter.submit(request_for(text))
        assert outcome.accepted and outcome.raw_response["warnings"][0]["code"] == "W1"

    async def test_a_200_that_does_not_say_cleared_is_not_a_clearance(self):
        def odd(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"clearanceStatus": "NOT_CLEARED", "validationResults": {"status": "PASS"}})

        adapter, _ = adapter_with(odd)
        _r, _s, text, _ = await stamped(make_input())
        outcome = await adapter.submit(request_for(text))
        assert not outcome.accepted and outcome.rejection_code == za.CODE_NOT_ACCEPTED

    async def test_a_400_is_a_rejection_with_zatcas_own_codes(self):
        def refused(request: httpx.Request) -> httpx.Response:
            errors = [
                {"type": "ERROR", "code": "BR-KSA-F-06", "category": "KSA", "message": "Bad total", "status": "ERROR"},
                {"type": "ERROR", "code": "BR-KSA-12", "category": "KSA", "message": "Bad type", "status": "ERROR"},
            ]
            return httpx.Response(400, json={"validationResults": {"status": "ERROR", "errorMessages": errors}})

        adapter, _ = adapter_with(refused)
        _r, _s, text, _ = await stamped(make_input())
        outcome = await adapter.submit(request_for(text))
        assert not outcome.accepted and outcome.rejection_code == "BR-KSA-F-06"
        assert outcome.rejection_message == "Bad total; Bad type"
        assert outcome.act == "clearance"

    @pytest.mark.parametrize("status", [401, 403, 500, 503])
    async def test_an_answer_that_says_nothing_about_the_document_raises(self, status):
        adapter, _ = adapter_with(lambda request: httpx.Response(status, json={}))
        _r, _s, text, _ = await stamped(make_input())
        with pytest.raises(FatooraError) as excinfo:
            await adapter.submit(request_for(text))
        assert excinfo.value.status == status

    async def test_an_unreadable_payload_is_a_rejection_not_a_crash(self):
        adapter, seen = adapter_with(accepted)
        outcome = await adapter.submit(request_for("not xml"))
        assert outcome.rejection_code == za.CODE_UNREADABLE and seen == []

    async def test_a_live_registration_is_not_sent_to_a_sandbox_gateway(self):
        adapter, seen = adapter_with(accepted)
        _r, _s, text, _ = await stamped(make_input())
        outcome = await adapter.submit(request_for(text, sandbox=False))
        assert outcome.rejection_code == za.CODE_ENVIRONMENT and seen == []

    async def test_a_live_unit_that_is_not_active_is_not_sent(self):
        access = za.UnitAccess("EGS1", "compliance_issued", "production", CREDENTIALS)
        adapter, seen = adapter_with(accepted, access=access)
        _r, _s, text, _ = await stamped(make_input())
        outcome = await adapter.submit(request_for(text, sandbox=False))
        assert outcome.rejection_code == za.CODE_NOT_ONBOARDED and seen == []

    async def test_the_adapter_is_for_saudi_arabia_and_does_not_poll(self):
        adapter = za.ZatcaAdapter()
        assert adapter.countries == ("SA",) and adapter.key == "zatca_fatoora"
        assert adapters.supports_polling(adapter) is False


@pytest.mark.asyncio
class TestClient:
    async def test_an_unknown_environment_is_refused(self):
        with pytest.raises(FatooraError, match="Unknown Fatoora environment"):
            FatooraClient("moon")

    async def test_the_otp_travels_in_its_header_and_the_csr_in_the_body(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"requestID": "1", "binarySecurityToken": "t", "secret": "s"})

        client = FatooraClient("simulation", transport=httpx.MockTransport(handler))
        response = await client.compliance_csid("Y3Ny", " 123456 ")
        assert (response.request_id, response.token, response.secret) == ("1", "t", "s")
        assert seen[0].headers["otp"] == "123456" and json.loads(seen[0].content) == {"csr": "Y3Ny"}
        assert seen[0].url.path == "/e-invoicing/simulation/compliance"

    async def test_a_csid_answer_without_a_secret_is_refused(self):
        client = FatooraClient(
            "developer_portal",
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"binarySecurityToken": "t"})),
        )
        with pytest.raises(FatooraError, match="without a certificate token and secret"):
            await client.compliance_csid("Y3Ny", "1")

    async def test_the_production_gateway_is_core(self):
        assert data.ENVIRONMENTS["production"].base_url.endswith("/e-invoicing/core")
        assert data.ENVIRONMENTS["production"].live and not data.ENVIRONMENTS["simulation"].live


# ── The rules ───────────────────────────────────────────────────────────────


def context(text: str, *, intent: str = "submit", reference: str = "2026-10-19T11:00:00+03:00", fields=None, **profile):
    entry = regimes.COUNTRY_REGIMES["SA"]
    return {
        "intent": intent,
        "profile": {
            "id": "p1",
            "country": "SA",
            "tax_registration_id": SELLER_VAT,
            "adapter_key": za.ZATCA_ADAPTER_KEY,
            "sandbox": True,
            "is_active": True,
            "certificate_reference": "unit:EGS1",
            **profile,
        },
        "regime": regimes.regime_as_dict(entry),
        "document": {
            "id": "d1",
            "country": "SA",
            "status": "draft",
            "country_fields": {"zatca": fields or {}},
            "payload_hash": "a" * 64,
        },
        "duplicate": None,
        "changed_fields": [],
        "invoice_is_real": False,
        "reference_time": reference,
        "payload": {"format": "zatca_phase2", "media_type": "application/xml", "text": text},
    }


@pytest.fixture(autouse=True)
def _rules():
    register_einvoice_clearance_rules()
    register_zatca_rules()


def zatca_findings(findings):
    return [f for f in findings if f.rule_id.startswith("einvoice_clearance.zatca_")]


@pytest.mark.asyncio
class TestRules:
    async def test_a_good_document_passes_every_zatca_rule(self):
        _r, _s, text, _ = await stamped(make_input())
        assert zatca_findings(await evaluate(context(text))) == []

    async def test_a_tampered_document_fails_the_stamp_rule_as_an_error(self):
        _r, _s, text, _ = await stamped(make_input())
        tampered = text.replace("<cbc:ID>INV-1</cbc:ID>", "<cbc:ID>INV-2</cbc:ID>", 1)
        found = zatca_findings(await evaluate(context(tampered)))
        assert {f.rule_id for f in found} == {"einvoice_clearance.zatca_stamp"}
        assert all(str(f.severity) == "error" for f in found)

    async def test_text_that_is_not_xml_fails_the_readable_rule_only(self):
        found = zatca_findings(await evaluate(context("<<<")))
        assert {f.rule_id for f in found} == {"einvoice_clearance.zatca_document_readable"}

    async def test_a_construction_rule_breach_blocks(self):
        _r, _s, text, _ = await stamped(make_input())
        found = zatca_findings(await evaluate(context(text, fields={"kind": "liquidated_damages"})))
        assert [f.rule_id for f in found] == ["einvoice_clearance.zatca_construction_vat"]

    async def test_a_government_claim_without_a_payment_order_date_is_a_warning(self):
        _r, _s, text, _ = await stamped(make_input())
        found = zatca_findings(await evaluate(context(text, fields={"government": {"contract": "C-1"}})))
        assert [(f.rule_id, str(f.severity)) for f in found] == [("einvoice_clearance.zatca_advisory", "warning")]

    async def test_a_simplified_invoice_past_24_hours_warns_only_when_submitting(self):
        _r, _s, text, _ = await stamped(make_input(simplified=True))
        late = zatca_findings(await evaluate(context(text, reference="2026-10-21T12:00:00+03:00")))
        assert [(f.rule_id, str(f.severity)) for f in late] == [
            ("einvoice_clearance.zatca_reporting_deadline", "warning")
        ]
        on_time = await evaluate(context(text, reference="2026-10-20T09:59:00+03:00"))
        assert zatca_findings(on_time) == []
        saving = await evaluate(context(text, intent="save", reference="2026-10-21T12:00:00+03:00"))
        assert zatca_findings(saving) == []

    async def test_a_standard_invoice_has_no_reporting_deadline(self):
        _r, _s, text, _ = await stamped(make_input())
        assert zatca_findings(await evaluate(context(text, reference="2026-12-01T00:00:00+03:00"))) == []

    async def test_a_registration_with_a_bad_vat_number_is_stopped(self):
        _r, _s, text, _ = await stamped(make_input())
        found = zatca_findings(await evaluate(context(text, tax_registration_id="30000000000003")))
        assert "einvoice_clearance.zatca_profile" in {f.rule_id for f in found}

    async def test_the_rules_are_silent_for_other_countries(self):
        _r, _s, text, _ = await stamped(make_input())
        other = context(text)
        other["regime"] = regimes.regime_as_dict(regimes.COUNTRY_REGIMES["MX"])
        other["document"]["country"] = "MX"
        other["payload"]["format"] = "cfdi"
        other["profile"]["adapter_key"] = "reference"
        assert zatca_findings(await evaluate(other)) == []

    async def test_the_reporting_deadline_is_the_documented_twenty_four_hours(self):
        assert dt.timedelta(hours=24) == data.REPORTING_DEADLINE


# ── The registry row and the identifiers ────────────────────────────────────


class TestRegistryRow:
    def test_saudi_arabia_clears_and_reports(self):
        sa = regimes.COUNTRY_REGIMES["SA"]
        assert sa.regime == "clearance" and sa.additional_regimes == ("reporting",)
        assert sa.regimes == ("clearance", "reporting") and sa.is_hybrid

    def test_the_fields_inside_the_signed_document_are_not_asked_for_twice(self):
        # The VAT number, the hash and the QR are inside the stamped XML. Asking the operator to type
        # them would block every submission on values nobody can know before the stamp.
        assert regimes.COUNTRY_REGIMES["SA"].document_fields == ()

    def test_phase_one_and_twenty_five_waves_are_each_sourced(self):
        phases = regimes.COUNTRY_REGIMES["SA"].commencement
        assert len(phases) == 26
        assert phases[0].effective_date == "2021-12-04"
        for phase in phases:
            assert phase.source_url.startswith("https://") and phase.read_date == "2026-10-19"

    def test_wave_twenty_five_is_enacted_with_its_threshold_and_deadline(self):
        wave = regimes.COUNTRY_REGIMES["SA"].commencement[-1]
        assert wave.effective_date == "2027-02-01"
        assert wave.legal_status == regimes.LEGAL_STATUS_ENACTED
        assert "187,500" in wave.threshold and "2025" in wave.threshold

    def test_the_historical_waves_say_they_need_an_expert(self):
        waves = regimes.COUNTRY_REGIMES["SA"].commencement[1:-1]
        assert len(waves) == 24 and all("needs expert review" in w.notes for w in waves)
        assert all(w.legal_status == regimes.LEGAL_STATUS_IN_FORCE for w in waves)

    def test_the_wave_dates_never_go_backwards(self):
        dates = [p.effective_date for p in regimes.COUNTRY_REGIMES["SA"].commencement]
        assert dates == sorted(dates)

    def test_the_open_questions_are_listed_and_not_shipped_as_numbers(self):
        assert any("penalty" in fact for fact in data.UNCONFIRMED_FACTS)
        assert all(path.source.startswith("https://") for path in data.API_PATHS.values())
        assert data.API_PATHS["reporting"].needs_expert_review is False
        assert data.API_PATHS["clearance"].needs_expert_review is True


class TestSaudiIdentifiers:
    @pytest.mark.parametrize(
        ("scheme", "value", "valid"),
        [
            ("vat", "300000000000003", True),
            ("vat", "310000000000003", True),
            ("vat", "30000000000003", False),
            ("vat", "400000000000003", False),
            ("vat", "300000000000004", False),
            ("vat", "٣٠٠٠٠٠٠٠٠٠٠٠٠٠٣", True),
            ("cr", "1010010000", True),
            ("cr", "101001000", False),
            ("unified_700", "7001234567", True),
            ("unified_700", "1001234567", False),
        ],
    )
    def test_the_shapes(self, scheme, value, valid):
        result = check_identifier("SA", scheme, value)
        assert result is not None and result.valid is valid

    def test_a_vat_group_is_marked_by_the_eleventh_digit(self):
        assert check_identifier("SA", "vat", "310000000010003").details["vat_group"] == "yes"
        assert check_identifier("SA", "vat", "300000000000003").details["vat_group"] == "no"

    def test_the_checks_module_agrees_with_the_registry_on_a_vat_number(self):
        for value in ("300000000000003", "30000000000003", "400000000000003", "300000000000004"):
            assert checks.is_vat_number(value) is check_identifier("SA", "vat", value).valid


# ── Wiring ──────────────────────────────────────────────────────────────────


class TestWiring:
    def test_every_permission_the_router_asks_for_is_registered(self):
        from app.core.permissions import permission_registry
        from app.modules.einvoice_zatca.permissions import register_einvoice_zatca_permissions
        from app.modules.einvoice_zatca.router import router

        register_einvoice_zatca_permissions()
        asked: set[str] = set()
        unguarded = []
        for route in router.routes:
            keys = {
                getattr(getattr(d, "dependency", None), "permission", None) for d in getattr(route, "dependencies", [])
            } - {None}
            asked |= keys
            if not keys:
                unguarded.append(route.path)
        assert unguarded == []
        assert asked <= set(permission_registry.list_all())

    def test_onboarding_sits_above_editing(self):
        from app.core.permissions import Role, permission_registry
        from app.modules.einvoice_zatca.permissions import register_einvoice_zatca_permissions

        register_einvoice_zatca_permissions()
        assert permission_registry.role_has_permission(Role.EDITOR, "einvoice_zatca.manage") is True
        assert permission_registry.role_has_permission(Role.EDITOR, "einvoice_zatca.onboard") is False
        assert permission_registry.role_has_permission(Role.MANAGER, "einvoice_zatca.onboard") is True
        assert permission_registry.role_has_permission(Role.VIEWER, "einvoice_zatca.read") is True

    def test_no_response_shape_can_carry_a_key_or_a_secret(self):
        from app.modules.einvoice_zatca.schemas import UnitResponse

        fields = set(UnitResponse.model_fields)
        assert not {f for f in fields if "secret" in f or "token" in f or f == "private_key_encrypted"}
        assert "has_private_key" in fields

    @pytest.mark.asyncio
    async def test_startup_registers_the_adapter_the_builder_and_the_rules(self):
        from app.modules.einvoice_clearance.service import payload_builder_for
        from app.modules.einvoice_zatca import on_startup

        await on_startup()
        assert adapters.adapter_registry.get("zatca_fatoora") is not None
        assert payload_builder_for("zatca_phase2") is not None
        adapters.adapter_registry._adapters.pop("zatca_fatoora", None)

    def test_the_manifest_depends_on_the_clearance_module(self):
        from app.modules.einvoice_zatca.manifest import manifest

        assert manifest.name == "oe_einvoice_zatca" and manifest.depends == ["oe_einvoice_clearance"]


class _EmptyInspector:
    def get_table_names(self) -> list[str]:
        return []

    def get_indexes(self, table: str) -> list[dict]:
        return []


class _Shim:
    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    def inspect(self, bind):
        return _EmptyInspector()


class _Ops:
    def __init__(self) -> None:
        self.tables: dict[str, list[str]] = {}
        self.indexes: dict[str, tuple[str, list[str], bool]] = {}

    def get_bind(self):
        return None

    def create_table(self, name, *args, **kwargs):
        import sqlalchemy as sa

        self.tables[name] = [a.name for a in args if isinstance(a, sa.Column)]

    def create_index(self, name, table, columns, **kwargs):
        self.indexes[name] = (table, list(columns), bool(kwargs.get("unique")))


class TestMigration:
    @staticmethod
    def _run():
        import importlib.util

        import sqlalchemy as sa

        path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "v197_sa_zatca_egs_units.py"
        spec = importlib.util.spec_from_file_location("_rev_v197_sa_zatca", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        ops = _Ops()
        module.op = ops
        module.sa = _Shim(sa)
        module.upgrade()
        return ops, module

    def test_the_revision_keeps_the_agreed_parent(self):
        _ops, module = self._run()
        assert module.revision == "v197_sa_zatca_egs_units" and module.down_revision == "v195_eg_tax_payee_exemption"

    def test_the_revision_builds_the_columns_and_indexes_the_models_declare(self):
        from app.database import Base
        from app.modules.einvoice_zatca import models  # noqa: F401

        ops, _module = self._run()
        for name in ("oe_einvoice_zatca_egs_unit", "oe_einvoice_zatca_chain_entry"):
            declared = set(Base.metadata.tables[name].columns.keys())
            assert set(ops.tables[name]) == declared, sorted(set(ops.tables[name]) ^ declared)
            for index in Base.metadata.tables[name].indexes:
                table, columns, unique = ops.indexes[index.name]
                assert (table, columns, unique) == (name, [c.name for c in index.columns], bool(index.unique))

    def test_a_document_uuid_is_unique_across_units(self):
        ops, _module = self._run()
        assert ops.indexes["ix_einvoice_zatca_chain_entry_uuid"][2] is True

    def test_the_hash_columns_hold_the_88_character_seed(self):
        from app.modules.einvoice_zatca.codes import FIRST_PREVIOUS_HASH
        from app.modules.einvoice_zatca.models import ZatcaChainEntry, ZatcaEgsUnit

        assert len(FIRST_PREVIOUS_HASH) == 88
        for column in (ZatcaChainEntry.previous_hash, ZatcaChainEntry.invoice_hash, ZatcaEgsUnit.last_hash):
            assert column.type.length >= len(FIRST_PREVIOUS_HASH)
