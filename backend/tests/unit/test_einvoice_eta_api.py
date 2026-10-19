"""The ETA client and the clearance adapter, against a fake ETA.

Nothing here reaches ETA. :class:`httpx.MockTransport` answers with bodies
shaped like the examples on the SDK pages (read 2026-10-19):

* login            https://sdk.invoicing.eta.gov.eg/api/01-login-as-taxpayer-system/
* submit           https://sdk.invoicing.eta.gov.eg/einvoicingapi/01-submit-documents/
* get submission   https://sdk.invoicing.eta.gov.eg/einvoicingapi/09-get-submission/
* details          https://sdk.invoicing.eta.gov.eg/einvoicingapi/11-get-document-details/
* document type    https://sdk.invoicing.eta.gov.eg/api/03-get-document-type/
* cancel           https://sdk.invoicing.eta.gov.eg/einvoicingapi/02-cancel-document/
"""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.modules.einvoice_clearance.adapters import (
    CancellationRequest,
    PollRequest,
    ReferenceAdapter,
    SubmissionRequest,
    supports_polling,
)
from app.modules.einvoice_eta import adapter as eta_adapter
from app.modules.einvoice_eta import client as eta_client
from app.modules.einvoice_eta.serialization import canonical_bytes
from app.modules.einvoice_eta.signing import verify_cades

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "eta"
IDENTITY = "https://id.example.test"
API = "https://api.example.test"
DOC_UUID = "EKV0TCMYB5CMSC0AV38AR8YF10"
SUBMISSION_UUID = "KMDN1CW8ZV8FFDYGRY1DPBYF10"
NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _fresh_tokens():
    eta_client.clear_token_cache()
    yield
    eta_client.clear_token_cache()


class FakeEta:
    """A scripted ETA. ``routes`` maps ``"METHOD /path"`` to a handler."""

    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []
        self.logins = 0
        self.routes: dict[str, Callable[[httpx.Request], httpx.Response]] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if request.url.path == "/connect/token":
            self.logins += 1
            return httpx.Response(
                200,
                json={"access_token": f"token-{self.logins}", "expires_in": 3600, "token_type": "Bearer"},
            )
        handler = self.routes.get(f"{request.method} {request.url.path}")
        if handler is None:
            return httpx.Response(404, json={"error": {"code": "NotFound", "message": request.url.path}})
        return handler(request)

    def api_calls(self) -> list[httpx.Request]:
        return [c for c in self.calls if c.url.path != "/connect/token"]


async def _any_url(url: str) -> str:
    # The fake ETA lives on .test hosts that resolve nowhere; the URL policy
    # itself is exercised in TestUrlSafety.
    return url


def _client(
    fake: FakeEta,
    *,
    on_behalf_of: str = "",
    clock: Callable[[], float] | None = None,
    secret: str = "secret",
) -> eta_client.EtaClient:
    return eta_client.EtaClient(
        eta_client.EtaEnvironment(IDENTITY, API),
        client_id="cid",
        client_secret=secret,
        on_behalf_of=on_behalf_of,
        transport=httpx.MockTransport(fake),
        url_guard=_any_url,
        **({"clock": clock} if clock else {}),
    )


def _accepted(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    internal_id = body["documents"][0]["internalID"]
    return httpx.Response(
        202,
        json={
            "submissionUUID": SUBMISSION_UUID,
            "acceptedDocuments": [{"uuid": DOC_UUID, "longId": "LONG-1", "internalId": internal_id}],
            "rejectedDocuments": [],
        },
    )


def _summary(status: str) -> Callable[[httpx.Request], httpx.Response]:
    return lambda _request: httpx.Response(
        200,
        json={
            "submissionId": SUBMISSION_UUID,
            "overallStatus": status,
            "documentSummary": [{"uuid": DOC_UUID, "status": status.capitalize()}],
        },
    )


# ── Client ───────────────────────────────────────────────────────────────────


class TestClient:
    def test_login_uses_basic_auth_client_credentials_and_on_behalf_of(self):
        fake = FakeEta()
        token = asyncio.run(_client(fake, on_behalf_of="200000001").access_token())
        assert token == "token-1"
        login = fake.calls[0]
        assert str(login.url) == f"{IDENTITY}/connect/token"
        assert login.headers["Authorization"] == "Basic " + base64.b64encode(b"cid:secret").decode()
        assert login.headers["onbehalfof"] == "200000001"
        form = dict(pair.split("=") for pair in login.content.decode().split("&"))
        assert form == {"grant_type": "client_credentials", "scope": "InvoicingAPI"}

    def test_the_token_is_reused_until_it_nears_expiry(self):
        fake = FakeEta()
        moment = [0.0]
        client = _client(fake, clock=lambda: moment[0])
        asyncio.run(client.access_token())
        asyncio.run(client.access_token())
        assert fake.logins == 1
        moment[0] = 3600 - eta_client.TOKEN_MARGIN_SECONDS + 1
        asyncio.run(client.access_token())
        assert fake.logins == 2

    def test_a_401_logs_in_again_once(self):
        fake = FakeEta()
        answers = iter([httpx.Response(401), httpx.Response(200, json={"status": "Valid"})])
        fake.routes[f"GET /api/v1.0/documents/{DOC_UUID}/details"] = lambda _r: next(answers)
        body = asyncio.run(_client(fake).get_document_details(DOC_UUID))
        assert body == {"status": "Valid"}
        assert fake.logins == 2
        assert [c.headers["Authorization"] for c in fake.api_calls()] == ["Bearer token-1", "Bearer token-2"]

    def test_the_submission_body_embeds_documents_verbatim(self):
        text = '{"internalID": "A", "totalAmount": 947.00}'
        body = eta_client.EtaClient.submission_body([text])
        assert body == b'{"documents":[{"internalID": "A", "totalAmount": 947.00}]}'

    def test_a_202_is_returned_as_etas_answer(self):
        fake = FakeEta()
        fake.routes["POST /api/v1.0/documentsubmissions/"] = _accepted
        answer = asyncio.run(_client(fake).submit(['{"internalID": "INV-1"}']))
        assert answer["acceptedDocuments"][0]["uuid"] == DOC_UUID
        assert fake.api_calls()[0].headers["Content-Type"] == "application/json"

    def test_a_duplicate_within_ten_minutes_is_its_own_error(self):
        fake = FakeEta()
        fake.routes["POST /api/v1.0/documentsubmissions/"] = lambda _r: httpx.Response(
            422,
            headers={"Retry-After": "600"},
            json={"error": {"code": "DuplicateSubmission", "message": "Duplicate submission"}},
        )
        with pytest.raises(eta_client.EtaDuplicateSubmission) as caught:
            asyncio.run(_client(fake).submit(['{"internalID": "INV-1"}']))
        assert caught.value.retry_after == "600"
        assert caught.value.status == 422

    def test_cancel_puts_the_state_and_reason(self):
        fake = FakeEta()
        fake.routes[f"PUT /api/v1.0/documents/state/{DOC_UUID}/state"] = lambda _r: httpx.Response(200)
        asyncio.run(_client(fake).cancel_document(DOC_UUID, "Wrong buyer"))
        assert json.loads(fake.api_calls()[0].content) == {"status": "cancelled", "reason": "Wrong buyer"}

    def test_reject_puts_rejected(self):
        fake = FakeEta()
        fake.routes[f"PUT /api/v1.0/documents/state/{DOC_UUID}/state"] = lambda _r: httpx.Response(200)
        asyncio.run(_client(fake).reject_document(DOC_UUID, "Not ours"))
        assert json.loads(fake.api_calls()[0].content)["status"] == "rejected"

    def test_missing_configuration_is_refused_before_any_call(self):
        with pytest.raises(eta_client.EtaApiError, match="base URLs"):
            eta_client.EtaClient(eta_client.EtaEnvironment("", API), client_id="a", client_secret="b")
        with pytest.raises(eta_client.EtaApiError, match="client id and secret"):
            eta_client.EtaClient(eta_client.EtaEnvironment(IDENTITY, API), client_id="", client_secret="b")


# ── Adapter ──────────────────────────────────────────────────────────────────


def _profile(**eta: Any) -> dict[str, Any]:
    settings = {
        "environment": "preprod",
        "identity_base_url": IDENTITY,
        "api_base_url": API,
        "client_id_env": "OE_TEST_ETA_ID",
        "client_secret_env": "OE_TEST_ETA_SECRET",
        "signer": {"kind": "test"},
        "poll_attempts": 2,
        "poll_interval_seconds": 0,
    }
    settings.update(eta)
    return {"tax_registration_id": "100000001", "sandbox": True, "settings": {"eta": settings}}


def _document_text() -> str:
    # The SDK sample, with a v1.0 version; the adapter signs whatever it gets.
    return (FIXTURES / "one-doc.json").read_text(encoding="utf-8")


def _request(profile: dict[str, Any] | None = None) -> SubmissionRequest:
    payload = _document_text().encode("utf-8")
    return SubmissionRequest(
        country="EG",
        regime="clearance",
        document_format="eta_json_1_0",
        payload=payload,
        payload_hash="x",
        payload_media_type="application/json",
        profile=profile or _profile(),
    )


async def _no_sleep(_seconds: float) -> None:
    return None


def _adapter(fake: FakeEta, *, now: datetime = NOW, guard: Any = None) -> eta_adapter.EtaAdapter:
    def factory(settings: eta_adapter.EtaSettings) -> eta_client.EtaClient:
        return eta_client.EtaClient(
            eta_client.EtaEnvironment(settings.identity_base_url, settings.api_base_url),
            client_id="cid",
            client_secret="secret",
            transport=httpx.MockTransport(fake),
            url_guard=guard or _any_url,
        )

    return eta_adapter.EtaAdapter(client_factory=factory, sleep=_no_sleep, now=lambda: now)


class TestAdapterSubmit:
    def test_it_signs_submits_and_reports_a_valid_verdict(self):
        fake = FakeEta()
        fake.routes["POST /api/v1.0/documentsubmissions/"] = _accepted
        fake.routes[f"GET /api/v1.0/documentsubmissions/{SUBMISSION_UUID}"] = _summary("valid")
        outcome = asyncio.run(_adapter(fake).submit(_request()))
        assert outcome.accepted and not outcome.pending
        assert outcome.authority_identifier == DOC_UUID
        sent = json.loads(fake.api_calls()[0].content)["documents"][0]
        signature = sent["signatures"][0]
        assert signature["signatureType"] == "I"
        # The signature covers the document as stored, and ETA gets that text.
        verify_cades(signature["value"], canonical_bytes(_document_text()))

    def test_no_verdict_in_time_is_pending_with_the_uuid(self):
        fake = FakeEta()
        fake.routes["POST /api/v1.0/documentsubmissions/"] = _accepted
        fake.routes[f"GET /api/v1.0/documentsubmissions/{SUBMISSION_UUID}"] = _summary("submitted")
        outcome = asyncio.run(_adapter(fake).submit(_request()))
        assert outcome.accepted and outcome.pending
        assert outcome.authority_identifier == DOC_UUID
        assert outcome.raw_response["submissionUUID"] == SUBMISSION_UUID

    def test_an_invalid_verdict_carries_etas_step_errors(self):
        fake = FakeEta()
        fake.routes["POST /api/v1.0/documentsubmissions/"] = _accepted
        fake.routes[f"GET /api/v1.0/documentsubmissions/{SUBMISSION_UUID}"] = _summary("invalid")
        fake.routes[f"GET /api/v1.0/documents/{DOC_UUID}/details"] = lambda _r: httpx.Response(
            200,
            json={
                "status": "Invalid",
                "validationResults": {
                    "status": "Invalid",
                    "validationSteps": [
                        {"name": "Step-03-ITIDA Signature Validator", "status": "Valid"},
                        {
                            "name": "Step-04-Core Tax Calculations Validator",
                            "status": "Invalid",
                            "error": {
                                "message": "Tax calculation mismatch",
                                "details": [{"message": "Total amount is wrong", "target": "totalAmount"}],
                            },
                        },
                    ],
                },
            },
        )
        outcome = asyncio.run(_adapter(fake).submit(_request()))
        assert not outcome.accepted
        assert outcome.rejection_code == "Invalid"
        assert "Core Tax Calculations" in outcome.rejection_message
        assert "Total amount is wrong (totalAmount)" in outcome.rejection_message
        assert "Signature" not in outcome.rejection_message

    def test_a_document_in_rejected_documents_is_a_rejection(self):
        fake = FakeEta()
        fake.routes["POST /api/v1.0/documentsubmissions/"] = lambda r: httpx.Response(
            202,
            json={
                "submissionUUID": SUBMISSION_UUID,
                "acceptedDocuments": [],
                "rejectedDocuments": [
                    {
                        "internalId": json.loads(r.content)["documents"][0]["internalID"],
                        "error": {"code": "BadStructure", "message": "Invalid structure"},
                    }
                ],
            },
        )
        outcome = asyncio.run(_adapter(fake).submit(_request()))
        assert not outcome.accepted
        assert outcome.rejection_code == "BadStructure"

    def test_a_duplicate_is_raised_so_the_document_stays_submitted(self):
        fake = FakeEta()
        fake.routes["POST /api/v1.0/documentsubmissions/"] = lambda _r: httpx.Response(
            422, json={"error": {"code": "DuplicateSubmission", "message": "Duplicate"}}
        )
        with pytest.raises(eta_client.EtaDuplicateSubmission):
            asyncio.run(_adapter(fake).submit(_request()))

    def test_an_already_signed_document_is_sent_as_it_is(self):
        fake = FakeEta()
        fake.routes["POST /api/v1.0/documentsubmissions/"] = _accepted
        fake.routes[f"GET /api/v1.0/documentsubmissions/{SUBMISSION_UUID}"] = _summary("valid")
        signed = (FIXTURES / "one-doc-I.json").read_bytes()
        request = SubmissionRequest(**{**_request().__dict__, "payload": signed})
        asyncio.run(_adapter(fake).submit(request))
        assert fake.api_calls()[0].content == b'{"documents":[' + signed.decode().strip().encode() + b"]}"

    def test_a_test_signer_is_refused_on_a_live_registration(self):
        profile = _profile(environment="prod")
        profile["sandbox"] = False
        outcome = asyncio.run(_adapter(FakeEta()).submit(_request(profile)))
        assert outcome.rejection_code == eta_adapter.CODE_NOT_CONFIGURED
        assert "test signer" in outcome.rejection_message

    def test_a_plain_http_base_url_is_refused_without_a_call(self):
        fake = FakeEta()
        outcome = asyncio.run(_adapter(fake).submit(_request(_profile(api_base_url="http://api.example.test"))))
        assert outcome.rejection_code == eta_adapter.CODE_NOT_CONFIGURED
        assert "api_base_url must be an https URL" in outcome.rejection_message
        assert fake.calls == []

    def test_an_unknown_environment_has_no_hosts_to_fall_back_on(self):
        problems = eta_adapter.settings_problems(_profile(environment="staging", identity_base_url="", api_base_url=""))
        assert any("environment" in p for p in problems)
        assert any("api_base_url is not set" in p for p in problems)

    def test_a_presigned_registration_refuses_an_unsigned_document(self):
        fake = FakeEta()
        outcome = asyncio.run(_adapter(fake).submit(_request(_profile(signer={"kind": "presigned"}))))
        assert outcome.rejection_code == eta_adapter.CODE_SIGNING
        assert fake.calls == []


class TestAdapterPoll:
    def _poll(self, fake: FakeEta) -> Any:
        return asyncio.run(
            _adapter(fake).poll(
                PollRequest(country="EG", regime="clearance", authority_identifier=DOC_UUID, profile=_profile())
            )
        )

    def test_the_adapter_declares_polling(self):
        assert supports_polling(eta_adapter.EtaAdapter())
        assert not supports_polling(ReferenceAdapter())

    @pytest.mark.parametrize(
        ("status", "accepted", "pending", "code"),
        [
            ("Valid", True, False, ""),
            ("Submitted", True, True, ""),
            ("Invalid", False, False, "Invalid"),
            ("Cancelled", False, False, "Cancelled"),
        ],
    )
    def test_document_status_maps_to_the_outcome(self, status, accepted, pending, code):
        fake = FakeEta()
        fake.routes[f"GET /api/v1.0/documents/{DOC_UUID}/details"] = lambda _r: httpx.Response(
            200, json={"uuid": DOC_UUID, "status": status, "validationResults": {"validationSteps": []}}
        )
        outcome = self._poll(fake)
        assert (outcome.accepted, outcome.pending, outcome.rejection_code) == (accepted, pending, code)


def _cancel_eta(received: str, hours: str) -> FakeEta:
    fake = FakeEta()
    fake.routes[f"GET /api/v1.0/documents/{DOC_UUID}/details"] = lambda _r: httpx.Response(
        200, json={"uuid": DOC_UUID, "status": "Valid", "typeName": "I", "dateTimeReceived": received}
    )
    fake.routes["GET /api/v1.0/documenttypes"] = lambda _r: httpx.Response(
        200, json=[{"id": 1, "name": "I", "description": "Invoice"}]
    )
    fake.routes["GET /api/v1.0/documenttypes/1"] = lambda _r: httpx.Response(
        200,
        json={
            "id": 1,
            "name": "I",
            "workflowParameters": [
                {"id": 1, "parameter": "Rejection time limit in hours", "value": 72},
                {"id": 2, "parameter": "Cancellation time limit in hours", "value": hours},
            ],
        },
    )
    fake.routes[f"PUT /api/v1.0/documents/state/{DOC_UUID}/state"] = lambda _r: httpx.Response(200)
    return fake


def _cancel_request() -> CancellationRequest:
    return CancellationRequest(
        country="EG", regime="clearance", authority_identifier=DOC_UUID, reason="Wrong buyer", profile=_profile()
    )


class TestAdapterCancel:
    def test_inside_the_window_read_from_eta_the_cancel_is_sent(self):
        fake = _cancel_eta("2026-10-18T12:00:00Z", "72")
        outcome = asyncio.run(_adapter(fake).cancel(_cancel_request()))
        assert outcome.accepted
        assert outcome.raw_response["deadline"] == "2026-10-21T12:00:00+00:00"
        assert fake.api_calls()[-1].method == "PUT"

    def test_after_the_window_it_refuses_without_asking_eta(self):
        fake = _cancel_eta("2026-10-10T12:00:00Z", "72")
        outcome = asyncio.run(_adapter(fake).cancel(_cancel_request()))
        assert not outcome.accepted
        assert outcome.rejection_code == "OperationPeriodOver"
        assert "credit note" in outcome.rejection_message
        assert all(call.method == "GET" for call in fake.api_calls())

    def test_the_rejection_parameter_is_not_mistaken_for_the_cancel_window(self):
        fake = _cancel_eta("2026-10-18T12:00:00Z", "1")  # cancel window 1h, rejection 72h
        outcome = asyncio.run(_adapter(fake).cancel(_cancel_request()))
        assert outcome.rejection_code == "OperationPeriodOver"

    def test_etas_own_refusal_is_reported_with_its_code(self):
        fake = _cancel_eta("2026-10-18T12:00:00Z", "72")
        fake.routes[f"PUT /api/v1.0/documents/state/{DOC_UUID}/state"] = lambda _r: httpx.Response(
            400, json={"error": {"code": "ActiveReferencingDocuments", "message": "Referenced by a credit note"}}
        )
        outcome = asyncio.run(_adapter(fake).cancel(_cancel_request()))
        assert outcome.rejection_code == "ActiveReferencingDocuments"

    def test_an_unreadable_window_leaves_the_decision_to_eta(self):
        fake = _cancel_eta("2026-10-18T12:00:00Z", "72")
        fake.routes["GET /api/v1.0/documenttypes"] = lambda _r: httpx.Response(500)
        outcome = asyncio.run(_adapter(fake).cancel(_cancel_request()))
        assert outcome.accepted
        assert outcome.raw_response["deadline"] == ""


class TestSignatureInsertion:
    def test_signatures_go_before_the_closing_brace_and_nothing_else_moves(self):
        text = _document_text()
        signed = eta_adapter.insert_signatures(text, [{"signatureType": "I", "value": "AAA"}])
        assert signed.startswith(text.rstrip()[:-1].rstrip())
        assert json.loads(signed)["signatures"] == [{"signatureType": "I", "value": "AAA"}]
        assert canonical_bytes(signed) == canonical_bytes(text)
        assert eta_adapter.has_signatures(signed)
        assert not eta_adapter.has_signatures(text)


class TestReferenceAdapterUnchanged:
    def test_it_still_cancels_inside_a_day_window(self):
        outcome = asyncio.run(
            ReferenceAdapter().cancel(
                CancellationRequest(
                    country="IT",
                    regime="clearance",
                    authority_identifier="X",
                    reason="r",
                    regime_spec={"cancellation_window_days": 5, "is_cancellable": True},
                )
            )
        )
        assert outcome.accepted

    def test_it_refuses_when_the_regime_has_no_cancellation(self):
        outcome = asyncio.run(
            ReferenceAdapter().cancel(
                CancellationRequest(
                    country="IT",
                    regime="clearance",
                    authority_identifier="X",
                    reason="r",
                    regime_spec={"cancellation_window_days": None, "is_cancellable": False},
                )
            )
        )
        assert not outcome.accepted


class TestEgyptRegimeRow:
    def test_egypt_is_a_clearance_country_returning_a_document_uuid(self):
        from app.modules.einvoice_clearance import regimes

        entry = regimes.COUNTRY_REGIMES["EG"]
        assert entry.regime == regimes.REGIME_CLEARANCE
        assert entry.document_format == "eta_json_1_0"
        assert entry.identifier_label
        assert entry.commencement and all(phase.source_url for phase in entry.commencement)

    def test_the_cancellation_window_is_read_from_eta_not_stored(self):
        from app.modules.einvoice_clearance import regimes

        entry = regimes.COUNTRY_REGIMES["EG"]
        assert entry.cancellation_window_days is None
        assert entry.cancellation_basis == regimes.CANCELLATION_BASIS_AUTHORITY
        assert entry.is_cancellable is True
        assert regimes.regime_as_dict(entry)["is_cancellable"] is True

    def test_the_published_hosts_are_the_default_base_urls(self):
        from app.modules.einvoice_clearance import regimes

        environments = regimes.COUNTRY_REGIMES["EG"].extra["environments"]
        assert environments["source_url"] == "https://sdk.invoicing.eta.gov.eg/faq/"
        preprod = eta_adapter.EtaSettings.from_profile({"settings": {"eta": {"environment": "preprod"}}})
        assert preprod.identity_base_url == "https://id.preprod.eta.gov.eg"
        assert preprod.api_base_url == "https://api.preprod.invoicing.eta.gov.eg"
        prod = eta_adapter.EtaSettings.from_profile({"settings": {"eta": {"environment": "prod"}}})
        assert prod.api_base_url == "https://api.invoicing.eta.gov.eg"

    def test_a_registration_may_still_name_its_own_hosts(self):
        settings = eta_adapter.EtaSettings.from_profile(
            {"settings": {"eta": {"environment": "prod", "api_base_url": "https://proxy.example.test"}}}
        )
        assert settings.api_base_url == "https://proxy.example.test"
        assert settings.identity_base_url == "https://id.eta.gov.eg"


class TestUrlSafety:
    def test_a_cached_token_is_never_served_for_another_secret(self):
        fake = FakeEta()
        asyncio.run(_client(fake, secret="right").access_token())
        asyncio.run(_client(fake, secret="wrong").access_token())
        assert fake.logins == 2

    def test_the_default_policy_refuses_a_metadata_address_before_any_call(self):
        fake = FakeEta()
        client = eta_client.EtaClient(
            eta_client.EtaEnvironment("https://169.254.169.254", API),
            client_id="cid",
            client_secret="secret",
            transport=httpx.MockTransport(fake),
        )
        with pytest.raises(eta_client.EtaUrlRefused, match="identity base URL"):
            asyncio.run(client.access_token())
        assert fake.calls == []

    def test_the_default_policy_refuses_loopback_for_eta(self):
        client = eta_client.EtaClient(
            eta_client.EtaEnvironment(IDENTITY, "https://127.0.0.1"),
            client_id="cid",
            client_secret="secret",
            transport=httpx.MockTransport(FakeEta()),
            url_guard=None,
        )

        async def identity_ok(url: str) -> str:
            if url == IDENTITY:
                return url
            from app.core.url_safety import resolve_and_validate_external_url

            return await resolve_and_validate_external_url(url)

        client._url_guard = identity_ok
        with pytest.raises(eta_client.EtaUrlRefused, match="API base URL"):
            asyncio.run(client.access_token())

    def test_a_refused_url_is_a_configuration_refusal_not_an_unknown_outcome(self):
        from app.core.url_safety import UnsafeUrlError

        async def refuse(url: str) -> str:
            raise UnsafeUrlError("internal address")

        fake = FakeEta()
        outcome = asyncio.run(_adapter(fake, guard=refuse).submit(_request()))
        assert not outcome.accepted
        assert outcome.rejection_code == eta_adapter.CODE_NOT_CONFIGURED
        assert fake.calls == []

    def test_the_external_signer_may_reach_loopback_but_not_metadata(self):
        from app.modules.einvoice_eta import signing

        signer = signing.ExternalHttpSigner({"url": "http://169.254.169.254/sign"})
        with pytest.raises(signing.EtaSigningError, match="refused"):
            asyncio.run(signer.sign(b"x"))

        seen = []

        def answer(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(500, text="token not inserted")

        local = signing.ExternalHttpSigner({"url": "http://127.0.0.1:8099/sign"}, transport=httpx.MockTransport(answer))
        with pytest.raises(signing.EtaSigningError, match="answered 500"):
            asyncio.run(local.sign(b"x"))
        assert seen == ["http://127.0.0.1:8099/sign"]

    def test_a_plain_http_base_url_is_refused_by_the_client_itself(self):
        fake = FakeEta()
        client = eta_client.EtaClient(
            eta_client.EtaEnvironment(IDENTITY, "http://api.example.test"),
            client_id="cid",
            client_secret="secret",
            transport=httpx.MockTransport(fake),
            url_guard=_any_url,
        )
        with pytest.raises(eta_client.EtaUrlRefused, match="https"):
            asyncio.run(client.access_token())
        assert fake.calls == []

    def test_an_internal_proxy_is_refused_until_an_administrator_lists_it(self, monkeypatch):
        from app.core import url_safety

        def build() -> eta_client.EtaClient:
            return eta_client.EtaClient(
                eta_client.EtaEnvironment(IDENTITY, "https://10.20.30.40"),
                client_id="cid",
                client_secret="secret",
                transport=httpx.MockTransport(FakeEta()),
            )

        async def identity_passes(url: str) -> str:
            if url == IDENTITY:
                return url
            return await url_safety.resolve_and_validate_external_url(url)

        monkeypatch.setattr(url_safety, "_internal_allowlist", lambda: [])
        closed = build()
        closed._url_guard = identity_passes
        with pytest.raises(eta_client.EtaUrlRefused, match="API base URL"):
            asyncio.run(closed.access_token())

        monkeypatch.setattr(url_safety, "_internal_allowlist", lambda: ["10.20.30.40"])
        opened = build()
        opened._url_guard = identity_passes
        assert asyncio.run(opened.access_token()) == "token-1"


class TestTokenLifetime:
    def test_a_token_is_still_served_one_second_before_the_margin(self):
        fake = FakeEta()
        moment = [0.0]
        client = _client(fake, clock=lambda: moment[0])
        asyncio.run(client.access_token())
        moment[0] = 3600 - eta_client.TOKEN_MARGIN_SECONDS - 1
        assert asyncio.run(client.access_token()) == "token-1"
        assert fake.logins == 1

    def test_an_expired_token_is_replaced_and_the_new_one_is_used(self):
        fake = FakeEta()
        moment = [0.0]
        client = _client(fake, clock=lambda: moment[0])
        asyncio.run(client.access_token())
        moment[0] = 3600
        assert asyncio.run(client.access_token()) == "token-2"

    def test_the_cache_is_per_represented_taxpayer(self):
        fake = FakeEta()
        asyncio.run(_client(fake, on_behalf_of="111").access_token())
        asyncio.run(_client(fake, on_behalf_of="222").access_token())
        asyncio.run(_client(fake, on_behalf_of="111").access_token())
        assert fake.logins == 2

    def test_a_second_401_is_reported_and_there_is_no_third_attempt(self):
        fake = FakeEta()
        fake.routes[f"GET /api/v1.0/documents/{DOC_UUID}/details"] = lambda _r: httpx.Response(401)
        with pytest.raises(eta_client.EtaApiError) as caught:
            asyncio.run(_client(fake).get_document_details(DOC_UUID))
        assert caught.value.status == 401
        assert fake.logins == 2
        assert len(fake.api_calls()) == 2

    def test_a_401_retry_replaces_the_cached_token_for_later_calls(self):
        fake = FakeEta()
        answers = iter([httpx.Response(401), httpx.Response(200, json={"status": "Valid"})])
        fake.routes[f"GET /api/v1.0/documents/{DOC_UUID}/details"] = lambda _r: next(answers)
        client = _client(fake)
        asyncio.run(client.get_document_details(DOC_UUID))
        assert asyncio.run(client.access_token()) == "token-2"
        assert fake.logins == 2
