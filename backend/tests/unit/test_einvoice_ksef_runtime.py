# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""KSeF around the document: QR codes, offline deadlines, the API, the rules.

Nothing here reaches KSeF. The API client runs against an in-process fake that
holds its own RSA key, so the fake can decrypt what the client encrypted and
the tests check the bytes, not the shape of a call.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.x509.oid import NameOID

from app.core.validation.engine import Severity, ValidationContext
from app.modules.einvoice_clearance.adapters import CancellationRequest, PollRequest, SubmissionRequest
from app.modules.einvoice_clearance.regimes import get_country_regime, regime_as_dict
from app.modules.einvoice_ksef import crypto, fa3, jpk, ksef_number, offline, payments, qr
from app.modules.einvoice_ksef import validators as rules
from app.modules.einvoice_ksef.adapter import (
    CODE_BAD_HANDLE,
    CODE_NO_CANCELLATION,
    CODE_NOT_CONFIGURED,
    KsefAdapter,
    settings_problems,
)
from app.modules.einvoice_ksef.builder import build_input_from_invoice, party_from_buyer, vat_code_for
from app.modules.einvoice_ksef.client import KsefClient, environment
from app.modules.einvoice_ksef.facts import FA2, FA3

SELLER_NIP = "5265877635"
# Real KSeF numbers from the Ministry's documentation; their checksums are right.
KSEF_A = "5265877635-20250826-0100001AF629-AF"
KSEF_B = "5265877635-20250916-0200A0D6723E-C2"


async def _no_sleep(_: float) -> None:
    return None


# ── KSeF number ─────────────────────────────────────────────────────────────


class TestKsefNumberHandle:
    def test_pending_handle_round_trips_and_is_not_a_number(self):
        handle = ksef_number.pending_handle("20251010-SO-1", "20251010-EE-2")
        assert ksef_number.parse_pending_handle(handle) == ("20251010-SO-1", "20251010-EE-2")
        assert not ksef_number.is_valid(handle)
        assert ksef_number.parse_pending_handle(KSEF_A) is None

    def test_a_number_from_another_seller_keeps_its_nip(self):
        assert ksef_number.seller_nip(KSEF_B) == SELLER_NIP


# ── QR codes ────────────────────────────────────────────────────────────────

MF_HASH = "UtQp9Gpc51y-u3xApZjIjgkpZ01js-J8KflSPW8WzIE"


class TestKodI:
    def test_matches_the_ministry_example(self):
        link = qr.invoice_link(
            environment="test", seller_nip="1111111111", issue_date=date(2026, 2, 1), file_hash=MF_HASH
        )
        assert link == f"https://qr-test.ksef.mf.gov.pl/invoice/1111111111/01-02-2026/{MF_HASH}"

    def test_hash_is_of_the_exact_bytes(self):
        a = qr.invoice_link(environment="prod", seller_nip=SELLER_NIP, issue_date=date(2026, 10, 19), xml_bytes=b"<a/>")
        b = qr.invoice_link(
            environment="prod", seller_nip=SELLER_NIP, issue_date=date(2026, 10, 19), xml_bytes=b"<a />"
        )
        assert a.startswith("https://qr.ksef.mf.gov.pl/invoice/") and a != b
        assert "=" not in a.rsplit("/", 1)[1]

    def test_label_is_offline_until_there_is_a_number(self):
        assert qr.kod_i_label("") == "OFFLINE"
        assert qr.kod_i_label(KSEF_A) == KSEF_A

    def test_renders_an_svg_carrying_the_label(self):
        code = qr.kod_i(environment="test", seller_nip=SELLER_NIP, issue_date=date(2026, 10, 19), xml_bytes=b"<x/>")
        assert code.label == "OFFLINE" and "<svg" in code.svg and "OFFLINE" in code.svg

    def test_refuses_a_bad_nip_or_environment(self):
        with pytest.raises(qr.QrError):
            qr.invoice_link(environment="test", seller_nip="123", issue_date=date(2026, 1, 1), file_hash=MF_HASH)
        with pytest.raises(qr.QrError):
            qr.invoice_link(environment="live", seller_nip=SELLER_NIP, issue_date=date(2026, 1, 1), file_hash=MF_HASH)


class TestKodII:
    SERIAL = "01F20A5D352AE590"
    SIGNED = f"qr-test.ksef.mf.gov.pl/certificate/Nip/1111111111/1111111111/{SERIAL}/{MF_HASH}"

    def _link(self, key):
        signer = qr.SoftwareLinkSigner(key, self.SERIAL)
        return qr.certificate_link(
            environment="test",
            context_type="Nip",
            context_value="1111111111",
            seller_nip="1111111111",
            signer=signer,
            file_hash=MF_HASH,
        )

    def test_rsa_signs_the_link_without_the_scheme(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        link = self._link(key)
        signed, signature = qr.signed_part(link)
        assert signed == self.SIGNED.encode()
        key.public_key().verify(
            signature, signed, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32), hashes.SHA256()
        )

    def test_ec_signature_is_raw_r_and_s(self):
        key = ec.generate_private_key(ec.SECP256R1())
        signed, signature = qr.signed_part(self._link(key))
        assert len(signature) == 64
        der = encode_dss_signature(int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big"))
        key.public_key().verify(der, signed, ec.ECDSA(hashes.SHA256()))

    def test_refuses_a_small_rsa_key_and_another_curve(self):
        with pytest.raises(qr.QrError):
            qr.SoftwareLinkSigner(rsa.generate_private_key(public_exponent=65537, key_size=1024), self.SERIAL)
        with pytest.raises(qr.QrError):
            qr.SoftwareLinkSigner(ec.generate_private_key(ec.SECP384R1()), self.SERIAL)

    def test_label_is_certyfikat(self):
        key = ec.generate_private_key(ec.SECP256R1())
        code = qr.kod_ii(
            environment="test",
            context_type="Nip",
            context_value=SELLER_NIP,
            seller_nip=SELLER_NIP,
            xml_bytes=b"<x/>",
            signer=qr.SoftwareLinkSigner(key, self.SERIAL),
        )
        assert code.label == "CERTYFIKAT"


# ── Offline deadlines ───────────────────────────────────────────────────────


class TestOfflineDeadline:
    def test_offline24_is_the_next_business_day(self):
        assert offline.upload_deadline("offline24", issue_date=date(2026, 10, 14)).due == date(2026, 10, 15)
        assert offline.upload_deadline("offline24", issue_date=date(2026, 10, 16)).due == date(2026, 10, 19)

    def test_failure_ending_on_a_saturday_matches_the_ministry_example(self):
        deadline = offline.upload_deadline("offline24", issue_date=date(2025, 7, 10), failure_end=date(2025, 7, 12))
        assert deadline.due == date(2025, 7, 22) and deadline.business_days == 7

    def test_awaria_counts_from_the_end_of_the_failure(self):
        deadline = offline.upload_deadline("awaria", issue_date=date(2025, 7, 10), event_end=date(2025, 7, 12))
        assert deadline.due == date(2025, 7, 22)

    def test_awaria_without_an_end_is_refused(self):
        with pytest.raises(offline.OfflineError):
            offline.upload_deadline("awaria", issue_date=date(2026, 10, 14))

    def test_total_failure_has_nothing_to_send(self):
        deadline = offline.upload_deadline("awaria_calkowita", issue_date=date(2026, 10, 14))
        assert deadline.due is None and not offline.is_overdue(deadline, date(2030, 1, 1))

    def test_overdue_is_the_day_after(self):
        deadline = offline.upload_deadline("offline24", issue_date=date(2026, 10, 14))
        assert not offline.is_overdue(deadline, date(2026, 10, 15))
        assert offline.is_overdue(deadline, date(2026, 10, 16))


# ── A fake KSeF ─────────────────────────────────────────────────────────────


def _certificate(key) -> str:
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "KSeF test key")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    return base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode()


_OAEP = padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None)
UPO = "<Potwierdzenie><NumerKSeFDokumentu>" + KSEF_A + "</NumerKSeFDokumentu></Potwierdzenie>"


class FakeKsef:
    """Answers the calls the client makes, and keeps what it was sent."""

    def __init__(self, *, statuses: list[int] | None = None, send_error: tuple[int, dict] | None = None) -> None:
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.certificate = _certificate(self.key)
        self.statuses = list(statuses or [200])
        self.send_error = send_error
        self.paths: list[str] = []
        self.token_plain = ""
        self.session_key: crypto.SessionKey | None = None
        self.invoice_plain = b""
        self.send_body: dict = {}
        self.closed = False
        self.open_body: dict = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.paths.append(f"{request.method} {path}")
        assert path.startswith("/v2/"), path
        path = path[3:]
        body = (
            json.loads(request.content)
            if request.content and request.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        if path == "/security/public-key-certificates":
            usage = ["KsefTokenEncryption", "SymmetricKeyEncryption"]
            return httpx.Response(200, json=[{"certificate": self.certificate, "usage": usage, "publicKeyId": "k1"}])
        if path == "/auth/challenge":
            return httpx.Response(200, json={"challenge": "20261019-CR-1", "timestampMs": 1760860800000})
        if path == "/auth/ksef-token":
            self.token_plain = self.key.decrypt(base64.b64decode(body["encryptedToken"]), _OAEP).decode()
            return httpx.Response(202, json={"referenceNumber": "AUTH-1", "authenticationToken": {"token": "auth"}})
        if path == "/auth/AUTH-1":
            assert request.headers["Authorization"] == "Bearer auth"
            return httpx.Response(200, json={"status": {"code": 200, "description": "ok"}})
        if path == "/auth/token/redeem":
            return httpx.Response(200, json={"accessToken": {"token": "access"}, "refreshToken": {"token": "refresh"}})
        if path == "/sessions/online":
            self.open_body = body
            enc = body["encryption"]
            self.session_key = crypto.SessionKey(
                key=self.key.decrypt(base64.b64decode(enc["encryptedSymmetricKey"]), _OAEP),
                iv=base64.b64decode(enc["initializationVector"]),
            )
            return httpx.Response(201, json={"referenceNumber": "SES-1", "validUntil": "2026-10-19T12:00:00Z"})
        if path == "/sessions/online/SES-1/invoices":
            if self.send_error is not None:
                return httpx.Response(self.send_error[0], json=self.send_error[1])
            self.send_body = body
            assert self.session_key is not None
            self.invoice_plain = crypto.decrypt_document(
                base64.b64decode(body["encryptedInvoiceContent"]), self.session_key
            )
            return httpx.Response(202, json={"referenceNumber": "INV-1"})
        if path == "/sessions/online/SES-1/close":
            self.closed = True
            return httpx.Response(204)
        if path == "/sessions/SES-1/invoices/INV-1":
            code = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
            raw: dict = {"status": {"code": code, "description": {200: "Sukces", 450: "Błąd semantyki"}.get(code, "")}}
            if code == 200:
                raw["ksefNumber"] = KSEF_A
                raw["invoicingMode"] = "Online"
            if code == 450:
                raw["status"]["details"] = ["P_15 does not match"]
            return httpx.Response(200, json=raw)
        if path == "/sessions/SES-1/invoices/INV-1/upo":
            return httpx.Response(200, text=UPO, headers={"content-type": "application/xml"})
        return httpx.Response(404, json={"title": "not found"})


def _profile(**settings) -> dict:
    ksef = {"environment": "test", "auth": "token", "token_env": "KSEF_TOKEN_TEST", **settings}
    return {
        "id": "p1",
        "country": "PL",
        "sandbox": True,
        "tax_registration_id": SELLER_NIP,
        "adapter_key": "ksef_pl",
        "settings": {"ksef": ksef},
    }


def _adapter(fake: FakeKsef, today: date = date(2026, 10, 19)) -> KsefAdapter:
    def factory(settings):
        return KsefClient(
            environment(settings.environment),
            transport=httpx.MockTransport(fake.handler),
            sleep=_no_sleep,
            poll_attempts=3,
            poll_interval=0,
        )

    return KsefAdapter(client_factory=factory, env={"KSEF_TOKEN_TEST": "secret-token"}.get, today=lambda: today)


def _request(payload: bytes = b"<Faktura/>", **document) -> SubmissionRequest:
    return SubmissionRequest(
        country="PL",
        regime="clearance",
        document_format=FA3.key,
        payload=payload,
        payload_hash="x",
        payload_media_type="application/xml",
        profile=_profile(),
        document={"country_fields": {"ksef": document}} if document else {},
    )


class TestClientAndAdapter:
    async def test_clears_and_keeps_the_number_and_the_upo(self):
        fake = FakeKsef()
        outcome = await _adapter(fake).submit(_request(b"<Faktura>1</Faktura>"))
        assert outcome.accepted and not outcome.pending
        assert outcome.authority_identifier == KSEF_A
        assert outcome.raw_response["upo"] == UPO
        # The token went encrypted, with the challenge's timestamp.
        assert fake.token_plain == "secret-token|1760860800000"
        # The fake decrypted exactly the bytes that were given.
        assert fake.invoice_plain == b"<Faktura>1</Faktura>"
        assert fake.send_body["invoiceHash"] == crypto.metadata(b"<Faktura>1</Faktura>").sha256_b64
        assert fake.send_body["invoiceSize"] == len(b"<Faktura>1</Faktura>")
        assert fake.send_body["offlineMode"] is False
        assert fake.open_body["formCode"] == {"systemCode": "FA (3)", "schemaVersion": "1-0E", "value": "FA"}
        assert fake.closed

    async def test_still_processing_is_pending_with_a_handle(self):
        fake = FakeKsef(statuses=[150])
        outcome = await _adapter(fake).submit(_request())
        assert outcome.accepted and outcome.pending
        assert ksef_number.parse_pending_handle(outcome.authority_identifier) == ("SES-1", "INV-1")

    async def test_poll_reads_the_verdict_from_the_handle(self):
        fake = FakeKsef(statuses=[200])
        poll = PollRequest(
            country="PL",
            regime="clearance",
            authority_identifier=ksef_number.pending_handle("SES-1", "INV-1"),
            profile=_profile(),
        )
        outcome = await _adapter(fake).poll(poll)
        assert outcome.accepted and outcome.authority_identifier == KSEF_A

    async def test_poll_refuses_something_that_is_not_a_handle(self):
        poll = PollRequest(country="PL", regime="clearance", authority_identifier=KSEF_A, profile=_profile())
        outcome = await _adapter(FakeKsef()).poll(poll)
        assert not outcome.accepted and outcome.rejection_code == CODE_BAD_HANDLE

    async def test_semantic_rejection_carries_the_code_and_details(self):
        fake = FakeKsef(statuses=[450])
        outcome = await _adapter(fake).submit(_request())
        assert not outcome.accepted and outcome.rejection_code == "KSEF-450"
        assert "P_15 does not match" in outcome.rejection_message

    async def test_a_400_on_send_is_a_rejection_not_a_crash(self):
        error = {"exception": {"exceptionDetailList": [{"exceptionCode": 21405, "exceptionDescription": "Bad"}]}}
        fake = FakeKsef(send_error=(400, error))
        outcome = await _adapter(fake).submit(_request())
        assert not outcome.accepted and outcome.rejection_code == "KSEF-21405"
        assert fake.closed

    async def test_offline_flag_and_corrected_hash_reach_ksef(self):
        fake = FakeKsef()
        await _adapter(fake).submit(_request(offline_mode="offline24", corrected_invoice_hash="abc="))
        assert fake.send_body["offlineMode"] is True
        assert fake.send_body["hashOfCorrectedInvoice"] == "abc="

    async def test_total_failure_is_never_sent(self):
        fake = FakeKsef()
        outcome = await _adapter(fake).submit(_request(offline_mode="awaria_calkowita"))
        assert not outcome.accepted and fake.paths == []

    async def test_token_after_2026_is_refused_before_any_call(self):
        fake = FakeKsef()
        outcome = await _adapter(fake, today=date(2027, 1, 1)).submit(_request())
        assert outcome.rejection_code == CODE_NOT_CONFIGURED and fake.paths == []
        assert not settings_problems(_profile(), today=date(2026, 12, 31))

    def test_live_registration_on_the_test_environment_is_a_problem(self):
        profile = {**_profile(), "sandbox": False}
        assert any("environment is test" in p for p in settings_problems(profile, today=date(2026, 10, 19)))

    async def test_cancel_is_always_refused(self):
        request = CancellationRequest(
            country="PL",
            regime="clearance",
            authority_identifier=KSEF_A,
            reason="x",
            regime_spec={"correction_mechanism": "faktura korygujaca"},
        )
        outcome = await KsefAdapter().cancel(request)
        assert not outcome.accepted and outcome.rejection_code == CODE_NO_CANCELLATION


# ── Builder ─────────────────────────────────────────────────────────────────


def _invoice(**kw) -> dict:
    base = {
        "invoice_number": "FV/1",
        "invoice_date": "2026-10-19",
        "currency_code": "PLN",
        "amount_subtotal": "20000.00",
        "tax_amount": "4600.00",
    }
    base.update(kw)
    return base


def _lines() -> list[dict]:
    return [
        {
            "description": "Roboty murarskie",
            "quantity": "100",
            "unit_rate": "200.00",
            "amount": "20000.00",
            "unit": "m2",
        }
    ]


class TestBuilder:
    def test_vat_codes_from_rate_and_category(self):
        assert vat_code_for(Decimal("23"), "S") == "23"
        assert vat_code_for(Decimal("8"), None) == "8"
        assert vat_code_for(Decimal("0"), "AE") == "oo"
        assert vat_code_for(Decimal("0"), "E") == "zw"

    def test_buyers_map_to_the_right_identifier(self):
        assert party_from_buyer({"name": "A", "country_code": "PL", "vat_id": "PL7010001454"}).nip == "7010001454"
        eu = party_from_buyer({"name": "B", "country_code": "DE", "vat_id": "DE123456789"})
        assert (eu.eu_country, eu.eu_vat) == ("DE", "123456789")
        # Greece is GR as a country and EL on a VAT number.
        greek = party_from_buyer({"name": "G", "country_code": "GR", "vat_id": "EL123456789"})
        assert (greek.eu_country, greek.eu_vat) == ("EL", "123456789")
        other = party_from_buyer({"name": "C", "country_code": "US", "vat_id": "12-3456789"})
        assert other.other_country == "US" and other.other_id
        assert party_from_buyer({"name": "D", "country_code": "US"}).no_id

    def _build(self, **ksef):
        return build_input_from_invoice(
            invoice=_invoice(),
            lines=_lines(),
            nip=SELLER_NIP,
            settings={"issuer": {"name": "Firma", "address_line1": "ul. A 1"}},
            ksef_fields=ksef,
            buyer={"name": "Inwestor", "country_code": "PL", "vat_id": "7010001454"},
        )

    def test_annex_15_line_above_threshold_sets_split_payment(self):
        data = self._build(lines=[{"annex_15": True, "pkwiu": "43.31.10.0"}])
        assert data.split_payment
        assert fa3.read_summary(fa3.build_xml(data)).split_payment

    def test_same_invoice_without_the_flag_does_not(self):
        assert not self._build().split_payment

    def test_a_stored_marker_that_disagrees_with_the_lines_stops_the_build(self):
        def build(stored, annex):
            return build_input_from_invoice(
                invoice=_invoice(metadata={"split_payment": stored}),
                lines=_lines(),
                nip=SELLER_NIP,
                settings={},
                ksef_fields={"lines": [{"annex_15": annex}]},
                buyer={"name": "X", "country_code": "PL", "vat_id": "7010001454"},
            )

        assert build(True, True).split_payment
        assert not build(False, False).split_payment
        with pytest.raises(fa3.Fa3BuildError, match="recorded as split payment required"):
            build(True, False)
        with pytest.raises(fa3.Fa3BuildError, match="not required"):
            build(False, True)

    def test_stated_vat_that_the_lines_do_not_give_is_refused(self):
        with pytest.raises(fa3.Fa3BuildError, match="states VAT"):
            build_input_from_invoice(
                invoice=_invoice(tax_amount="4500.00"),
                lines=_lines(),
                nip=SELLER_NIP,
                settings={},
                ksef_fields={},
                buyer={"name": "X", "country_code": "PL", "vat_id": "7010001454"},
            )

    def test_foreign_currency_annex_15_without_rate_is_refused(self):
        with pytest.raises(fa3.Fa3BuildError, match="split payment"):
            build_input_from_invoice(
                invoice=_invoice(currency_code="EUR"),
                lines=_lines(),
                nip=SELLER_NIP,
                settings={},
                ksef_fields={"lines": [{"annex_15": True}]},
                buyer={"name": "X", "country_code": "PL", "vat_id": "7010001454"},
            )


# ── Rules ───────────────────────────────────────────────────────────────────


def _fa3_xml(split: bool = False, annex: bool = False, issue_date: str = "2026-10-19") -> str:
    line = fa3.Line(
        description="Roboty",
        quantity=Decimal("100"),
        unit="m2",
        unit_net_price=Decimal("200"),
        net_amount=Decimal("20000.00"),
        vat_code="23",
        annex_15=annex,
    )
    return fa3.build_xml(
        fa3.Fa3Input(
            seller=fa3.Party(name="Firma", nip=SELLER_NIP, address_line1="ul. A 1"),
            buyer=fa3.Party(name="Inwestor", nip="7010001454", address_line1="ul. B 2"),
            number="FV/1",
            issue_date=issue_date,
            currency="PLN",
            lines=(line,),
            split_payment=split,
            generated_at=datetime(2026, 10, 19, 9, tzinfo=UTC),
        )
    )


def _as_fa2(text: str) -> str:
    return text.replace(FA3.namespace, FA2.namespace).replace('kodSystemowy="FA (3)"', 'kodSystemowy="FA (2)"')


def _context(*, country: str = "PL", text: str = "", intent: str = "submit", **document) -> ValidationContext:
    doc = {"id": "d1", "country": country, "invoice_date": "2026-10-19", "status": "draft", **document}
    return ValidationContext(
        data={
            "intent": intent,
            "profile": _profile(),
            "regime": {"country": country, "document_format": FA3.key if country == "PL" else "other"},
            "document": doc,
            "payload": {"format": FA3.key if country == "PL" else "other", "text": text},
            "reference_time": "2026-10-19T10:00:00+00:00",
        }
    )


async def _failures(rule, context) -> list:
    return [r for r in await rule.validate(context) if not r.passed]


class TestDocumentRules:
    async def test_fa3_document_passes_every_error_rule(self):
        context = _context(text=_fa3_xml())
        for rule in rules._DOCUMENT_RULES:
            if rule.severity == Severity.ERROR:
                assert await _failures(rule, context) == [], rule.rule_id

    async def test_fa2_after_its_end_is_refused(self):
        found = await _failures(rules.KsefStructure(), _context(text=_as_fa2(_fa3_xml())))
        assert found and "FA (2)" in found[0].message

    async def test_fa2_declared_format_is_refused_without_a_payload(self):
        found = await _failures(rules.KsefStructure(), _context(document_format=FA2.key))
        assert found and FA2.valid_to in found[0].message

    async def test_fa3_dated_before_february_2026_is_refused(self):
        found = await _failures(rules.KsefStructure(), _context(text=_fa3_xml(issue_date="2026-01-30")))
        assert found

    async def test_foreign_seller_nip_is_refused(self):
        text = _fa3_xml().replace(f"<NIP>{SELLER_NIP}</NIP>", "<NIP>7010001454</NIP>", 1)
        found = await _failures(rules.KsefStructure(), _context(text=text))
        assert any("seller NIP" in r.message for r in found)

    async def test_missing_split_payment_marker_is_refused(self):
        found = await _failures(rules.KsefSplitPayment(), _context(text=_fa3_xml(annex=True, split=False)))
        assert found and "P_18A" in found[0].message

    async def test_marker_without_reason_is_refused(self):
        assert await _failures(rules.KsefSplitPayment(), _context(text=_fa3_xml(annex=False, split=True)))

    async def test_consistent_marker_passes(self):
        assert not await _failures(rules.KsefSplitPayment(), _context(text=_fa3_xml(annex=True, split=True)))

    async def test_rules_ignore_other_countries(self):
        context = _context(country="EG", text="not xml at all", document_format=FA2.key)
        for rule in rules._DOCUMENT_RULES:
            assert await _failures(rule, context) == [], rule.rule_id

    async def test_invalid_stored_number_is_refused(self):
        bad = KSEF_A[:-2] + "00"
        assert await _failures(rules.KsefNumberFormat(), _context(status="cleared", authority_identifier=bad))
        assert not await _failures(rules.KsefNumberFormat(), _context(status="cleared", authority_identifier=KSEF_A))
        pending = ksef_number.pending_handle("S", "I")
        assert not await _failures(rules.KsefNumberFormat(), _context(status="cleared", authority_identifier=pending))

    async def test_token_registration_in_2027_is_refused(self):
        context = _context()
        context.data["reference_time"] = "2027-01-02T08:00:00+00:00"
        found = await _failures(rules.KsefRegistrationReady(), context)
        assert found and "certificate" in found[0].message

    async def test_offline_deadline_warns_and_then_says_overdue(self):
        fields = {"country_fields": {"ksef": {"offline_mode": "offline24"}}}
        found = await _failures(rules.KsefOfflineDeadline(), _context(invoice_date="2026-10-19", **fields))
        assert found and "2026-10-20" in found[0].message and found[0].severity == Severity.WARNING
        late = await _failures(rules.KsefOfflineDeadline(), _context(invoice_date="2026-10-14", **fields))
        assert late[0].details["overdue"] is True

    async def test_construction_line_not_in_annex_15_is_a_hint(self):
        fields = {"country_fields": {"ksef": {"lines": [{"pkwiu": "43.31.10.0"}, {"pkwiu": "62.01"}]}}}
        found = await _failures(rules.KsefAnnex15Hint(), _context(**fields))
        assert len(found) == 1 and found[0].details["line"] == 1

    async def test_nip_rules_follow_the_shared_check(self, monkeypatch):
        verdicts = {}

        def fake_check(country, scheme, value):
            assert (country, scheme) == ("PL", "nip")
            return verdicts.get(value)

        monkeypatch.setattr(rules, "_nip_checker", lambda: fake_check)
        context = _context(text=_fa3_xml())
        # Nothing registered for this NIP: a warning, never a block.
        assert not await _failures(rules.KsefNipValid(), context)
        assert len(await _failures(rules.KsefNipUnchecked(), context)) == 2
        verdicts["7010001454"] = {"valid": False, "reason": "checksum"}
        found = await _failures(rules.KsefNipValid(), context)
        assert len(found) == 1 and found[0].details["party"] == "buyer"
        # A check still under expert review only warns.
        verdicts["7010001454"] = {"valid": False, "reason": "checksum", "details": {"needs_expert_review": True}}
        assert not await _failures(rules.KsefNipValid(), context)
        verdicts[SELLER_NIP] = {"valid": True}
        unchecked = await _failures(rules.KsefNipUnchecked(), context)
        assert [r.details["party"] for r in unchecked] == ["buyer"]

    async def test_the_clearance_gate_runs_the_ksef_rules(self):
        from app.modules.einvoice_clearance.validators import hard_blockers

        rules.register_ksef_rules()
        payload = _context(text=_as_fa2(_fa3_xml())).data
        assert any(r.rule_id == rules.KsefStructure.rule_id for r in await hard_blockers(payload))


# ── Payment title ───────────────────────────────────────────────────────────


class TestPaymentTitle:
    def test_2026_is_a_warning_and_2027_an_error(self):
        w = payments.payment_title_finding(payment_date=date(2026, 12, 31), title="FV/1", invoice_ksef_number=KSEF_A)
        e = payments.payment_title_finding(payment_date=date(2027, 1, 1), title="FV/1", invoice_ksef_number=KSEF_A)
        assert w.severity == "warning" and e.severity == "error"

    def test_title_with_the_number_passes(self):
        title = payments.suggested_title("FV/1", KSEF_A)
        assert payments.payment_title_finding(
            payment_date=date(2027, 3, 1), title=title, invoice_ksef_number=KSEF_A
        ).passed

    def test_no_number_or_a_consumer_is_not_flagged(self):
        assert payments.payment_title_finding(payment_date=date(2027, 3, 1), title="", invoice_ksef_number="").passed
        assert payments.payment_title_finding(
            payment_date=date(2027, 3, 1), title="", invoice_ksef_number=KSEF_A, between_vat_payers=False
        ).passed

    def test_entered_number_must_be_valid(self):
        assert payments.number_from_metadata({"ksef_number": KSEF_A}) == KSEF_A
        assert payments.number_from_metadata({"ksef_number": KSEF_A[:-2] + "00"}) == ""

    async def test_rule_severity_follows_the_payment_date(self):
        rule = rules.KsefNumberInPaymentTitle()

        def record(day: str) -> ValidationContext:
            return ValidationContext(
                data={
                    "record_type": "payment",
                    "country": "PL",
                    "payment_date": day,
                    "reference": "FV/1",
                    "ksef_number": KSEF_A,
                }
            )

        assert (await _failures(rule, record("2026-11-01")))[0].severity == Severity.WARNING
        assert (await _failures(rule, record("2027-01-04")))[0].severity == Severity.ERROR
        claim = ValidationContext(data={"record_type": "claim_invoice", "country": "PL"})
        assert not await _failures(rule, claim)


# ── JPK_V7(3) ───────────────────────────────────────────────────────────────


class TestJpkMarker:
    def test_a_number_wins(self):
        marker = jpk.marker_for(ksef_number_value=KSEF_A)
        assert marker.ksef_number == KSEF_A and marker.marker == ""

    def test_without_a_number(self):
        assert jpk.marker_for().marker == "BFK"
        assert jpk.marker_for(is_invoice=False).marker == "DI"
        assert jpk.marker_for(issued_as="awaria_calkowita").marker == "BFK"

    def test_offline24_is_marked_for_review(self):
        marker = jpk.marker_for(issued_as="offline24")
        assert marker.marker == "OFF" and marker.needs_expert_review

    def test_bad_input_is_refused(self):
        with pytest.raises(ValueError):
            jpk.marker_for(ksef_number_value="5265877635-20250826-0100001AF629-00")
        with pytest.raises(ValueError):
            jpk.marker_for(issued_as="carrier pigeon")


# ── Regime row ──────────────────────────────────────────────────────────────


class TestRegimeRow:
    def test_poland_is_fa3_with_fa2_as_history(self):
        regime = get_country_regime("PL")
        assert regime is not None and regime.document_format == FA3.key
        assert regime.extra["schema"]["namespace"] == FA3.namespace
        (old,) = regime.extra["historical_schemas"]
        assert old["key"] == FA2.key and old["valid_to"] == FA2.valid_to == "2026-01-31"
        assert regime.extra["token_auth_last_day"] == "2026-12-31"
        penalties = {p["key"]: p for p in regime.extra["penalties"]}
        assert {p["effective_date"] for p in penalties.values()} == {"2027-01-01"}
        assert "100%" in penalties["invoice_outside_ksef_vat"]["cap"]
        assert "18.7%" in penalties["invoice_outside_ksef_no_vat"]["cap"]
        assert all(p["source_url"] and p["read_date"] for p in penalties.values())

    def test_issue_phases_by_size_and_their_sources(self):
        phases = [p for p in get_country_regime("PL").commencement if p.obligation == "issue"]
        assert [p.effective_date for p in phases] == ["2026-02-01", "2026-04-01", "2027-01-01"]
        assert "PLN 200000000" in phases[0].threshold
        assert all(p.source_url.startswith("https://") and p.read_date for p in phases)

    def test_still_a_clearance_regime_without_cancellation(self):
        spec = regime_as_dict(get_country_regime("PL"))
        assert spec["regime"] == "clearance" and not spec["is_cancellable"]


# ── Split payment data comes from the Polish VAT data ───────────────────────


class TestSplitPaymentData:
    def test_threshold_is_read_from_the_vat_data(self, monkeypatch):
        from app.modules.einvoice_ksef import split_payment

        monkeypatch.setattr(split_payment, "rules", lambda: {"threshold_gross": "100.00"})
        decision = split_payment.decide(gross=Decimal("100.01"), currency="PLN", annex_15_lines=1)
        assert decision.required and decision.threshold_pln == Decimal("100.00")
        assert not split_payment.decide(gross=Decimal("100.00"), currency="PLN", annex_15_lines=1).required

    def test_shipped_data_is_strictly_above_15000(self):
        from app.modules.einvoice_ksef import split_payment

        assert split_payment.threshold_pln() == Decimal("15000.00")
        assert split_payment.annex_15_sections() == ("41", "42", "43")
        assert split_payment.looks_like_construction("43.31.10.0") and not split_payment.looks_like_construction("430")

    def test_changing_the_data_file_changes_the_decision(self, monkeypatch):
        import copy

        from app.core import vat_construction
        from app.modules.einvoice_ksef import split_payment

        data = copy.deepcopy(vat_construction._data())
        data["countries"]["PL"]["split_payment"]["threshold_gross"] = "20000.00"
        monkeypatch.setattr(vat_construction, "_data", lambda: data)
        assert split_payment.threshold_pln() == Decimal("20000.00")
        assert not split_payment.decide(gross=Decimal("16000"), currency="PLN", annex_15_lines=1).required
        assert split_payment.decide(gross=Decimal("20000.01"), currency="PLN", annex_15_lines=1).required

    def test_unreadable_data_is_not_checked_never_a_remembered_number(self, monkeypatch):
        from app.modules.einvoice_ksef import split_payment

        monkeypatch.setattr(split_payment, "rules", lambda: None)
        decision = split_payment.decide(gross=Decimal("99999"), currency="PLN", annex_15_lines=1)
        assert decision.verdict == split_payment.NOT_CHECKED and decision.threshold_pln is None
        # Without Annex 15 lines the threshold is never needed.
        assert split_payment.decide(gross=Decimal("99999"), currency="PLN", annex_15_lines=0).verdict == "not_required"

    def test_builder_without_data_uses_the_stored_marker_or_stops(self, monkeypatch):
        from app.modules.einvoice_ksef import split_payment

        monkeypatch.setattr(split_payment, "rules", lambda: None)

        def build(**invoice):
            return build_input_from_invoice(
                invoice=_invoice(**invoice),
                lines=_lines(),
                nip=SELLER_NIP,
                settings={},
                ksef_fields={"lines": [{"annex_15": True}]},
                buyer={"name": "X", "country_code": "PL", "vat_id": "7010001454"},
            )

        with pytest.raises(fa3.Fa3BuildError, match="not checked"):
            build()
        assert build(metadata={"split_payment": True}).split_payment

    async def test_rules_warn_and_do_not_block_without_data(self, monkeypatch):
        from app.modules.einvoice_ksef import split_payment

        monkeypatch.setattr(split_payment, "rules", lambda: None)
        context = _context(text=_fa3_xml(annex=True, split=False))
        assert not await _failures(rules.KsefSplitPayment(), context)
        found = await _failures(rules.KsefSplitPaymentUnchecked(), context)
        assert found and found[0].severity == Severity.WARNING
