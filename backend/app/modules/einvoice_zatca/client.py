# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The FATOORA REST client.

One class, one method per call the integration makes: the compliance CSID, a
compliance invoice check, the production CSID and its renewal, and the two
invoice calls, clearance and reporting. The HTTP transport is injectable, so
every test runs against ``httpx.MockTransport`` and none reaches ZATCA.

Authentication is HTTP Basic with the CSID: the user is the certificate
(``binarySecurityToken``, as ZATCA returned it) and the password is the secret
issued with it. The onboarding calls that precede a CSID authenticate with the
OTP header instead.

What the client does not decide: whether a document is accepted. A 400 with
validation errors is a business rejection and comes back as a
:class:`FatooraResponse` the adapter turns into a rejected outcome. Only a
transport problem or an answer that says nothing about the document (401, 5xx,
an unreadable body) raises :class:`FatooraError`, because those are facts about
the connection and must not be recorded against the invoice.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.modules.einvoice_zatca import data

ACCEPT_VERSION = "V2"
DEFAULT_TIMEOUT = 30.0


class FatooraError(RuntimeError):
    """ZATCA could not be asked, or answered something that is not about the document."""

    def __init__(self, message: str, *, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Credentials:
    """A CSID: the certificate token and its secret."""

    token: str
    secret: str

    def authorization(self) -> str:
        raw = f"{self.token}:{self.secret}".encode()
        return "Basic " + base64.b64encode(raw).decode("ascii")


@dataclass(frozen=True)
class Message:
    """One entry of ZATCA's validation results."""

    type: str
    code: str
    category: str
    message: str
    status: str


@dataclass(frozen=True)
class FatooraResponse:
    """What ZATCA said about a document (clearance, reporting, compliance check)."""

    http_status: int
    status: str
    errors: tuple[Message, ...] = ()
    warnings: tuple[Message, ...] = ()
    infos: tuple[Message, ...] = ()
    cleared_invoice: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def accepted(self) -> bool:
        """200 and 202 are acceptances; 202 carries warnings (P3 §6)."""
        return self.http_status in (200, 202) and not self.errors


@dataclass(frozen=True)
class CsidResponse:
    """A compliance or production CSID."""

    request_id: str
    token: str
    secret: str
    message: str
    raw: dict[str, Any] = field(default_factory=dict)


def _messages(raw: Any) -> tuple[Message, ...]:
    out: list[Message] = []
    for item in raw or []:
        if isinstance(item, dict):
            out.append(
                Message(
                    type=str(item.get("type") or ""),
                    code=str(item.get("code") or ""),
                    category=str(item.get("category") or ""),
                    message=str(item.get("message") or ""),
                    status=str(item.get("status") or ""),
                )
            )
    return tuple(out)


class FatooraClient:
    """Talks to one Fatoora environment."""

    def __init__(
        self,
        environment: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        language: str = "en",
    ) -> None:
        env = data.ENVIRONMENTS.get(environment)
        if env is None:
            raise FatooraError(
                f"Unknown Fatoora environment {environment!r}; use one of {', '.join(data.ENVIRONMENTS)}."
            )
        self.environment = env
        self._transport = transport
        self._timeout = timeout
        self._language = language

    def _url(self, name: str) -> str:
        return self.environment.base_url + data.API_PATHS[name].path

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Accept-Language": self._language,
            "Accept-Version": ACCEPT_VERSION,
            "Content-Type": "application/json",
        }
        headers.update(extra or {})
        return headers

    async def _call(self, name: str, *, body: dict[str, Any], headers: dict[str, str]) -> httpx.Response:
        method = data.API_PATHS[name].method
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=self._timeout) as http:
                return await http.request(method, self._url(name), json=body, headers=self._headers(headers))
        except httpx.HTTPError as exc:
            raise FatooraError(f"ZATCA did not answer: {exc}.") from exc

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        try:
            value = response.json()
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}

    # ── Onboarding ──────────────────────────────────────────────────────────

    async def _csid(self, name: str, *, body: dict[str, Any], headers: dict[str, str]) -> CsidResponse:
        response = await self._call(name, body=body, headers=headers)
        payload = self._json(response)
        if response.status_code != 200:
            detail = payload.get("message") or payload.get("errors") or response.text[:300]
            raise FatooraError(
                f"ZATCA refused the request ({response.status_code}): {detail}", status=response.status_code
            )
        token = str(payload.get("binarySecurityToken") or "")
        secret = str(payload.get("secret") or "")
        if not token or not secret:
            raise FatooraError("ZATCA answered without a certificate token and secret.", status=200)
        return CsidResponse(
            request_id=str(payload.get("requestID") or ""),
            token=token,
            secret=secret,
            message=str(payload.get("dispositionMessage") or ""),
            raw={k: v for k, v in payload.items() if k not in ("secret", "binarySecurityToken")},
        )

    async def compliance_csid(self, csr_b64: str, otp: str) -> CsidResponse:
        """Exchange the CSR and the one-time password for a compliance CSID."""
        return await self._csid("compliance_csid", body={"csr": csr_b64}, headers={"OTP": otp.strip()})

    async def production_csid(self, compliance: Credentials, compliance_request_id: str) -> CsidResponse:
        """Exchange a compliance CSID whose checks passed for the production CSID."""
        return await self._csid(
            "production_csid",
            body={"compliance_request_id": compliance_request_id},
            headers={"Authorization": compliance.authorization()},
        )

    async def renew_csid(self, production: Credentials, csr_b64: str, otp: str) -> CsidResponse:
        """Renew the production CSID with a new CSR and a new one-time password."""
        return await self._csid(
            "production_csid_renewal",
            body={"csr": csr_b64},
            headers={"Authorization": production.authorization(), "OTP": otp.strip()},
        )

    # ── Documents ───────────────────────────────────────────────────────────

    def _document_body(self, invoice_xml: str, invoice_hash: str, invoice_uuid: str) -> dict[str, Any]:
        return {
            "invoiceHash": invoice_hash,
            "uuid": invoice_uuid,
            "invoice": base64.b64encode(invoice_xml.encode("utf-8")).decode("ascii"),
        }

    def _document_response(self, response: httpx.Response) -> FatooraResponse:
        payload = self._json(response)
        code = response.status_code
        if code in (401, 403) or code >= 500 or (code not in (200, 202) and code != 400 and not payload):
            raise FatooraError(f"ZATCA answered {code}; nothing is known about the document.", status=code)
        results = payload.get("validationResults") if isinstance(payload.get("validationResults"), dict) else {}
        errors = _messages(results.get("errorMessages"))
        if code == 400 and not errors:
            # A 400 without validation results (a malformed request): keep what was said.
            errors = (
                Message(
                    "ERROR",
                    str(payload.get("code") or "400"),
                    "",
                    str(payload.get("message") or response.text[:300]),
                    "ERROR",
                ),
            )
        status = str(payload.get("clearanceStatus") or payload.get("reportingStatus") or results.get("status") or "")
        return FatooraResponse(
            http_status=code,
            status=status,
            errors=errors,
            warnings=_messages(results.get("warningMessages")),
            infos=_messages(results.get("infoMessages")),
            cleared_invoice=str(payload.get("clearedInvoice") or ""),
            raw=payload,
        )

    async def compliance_invoice(
        self, compliance: Credentials, invoice_xml: str, invoice_hash: str, invoice_uuid: str
    ) -> FatooraResponse:
        """Check one sample document during onboarding."""
        response = await self._call(
            "compliance_invoice",
            body=self._document_body(invoice_xml, invoice_hash, invoice_uuid),
            headers={"Authorization": compliance.authorization()},
        )
        return self._document_response(response)

    async def clear(
        self, credentials: Credentials, invoice_xml: str, invoice_hash: str, invoice_uuid: str
    ) -> FatooraResponse:
        """Put a standard tax invoice to ZATCA for clearance."""
        response = await self._call(
            "clearance",
            body=self._document_body(invoice_xml, invoice_hash, invoice_uuid),
            headers={"Authorization": credentials.authorization(), "Clearance-Status": "1"},
        )
        return self._document_response(response)

    async def report(
        self, credentials: Credentials, invoice_xml: str, invoice_hash: str, invoice_uuid: str
    ) -> FatooraResponse:
        """Report a simplified tax invoice."""
        response = await self._call(
            "reporting",
            body=self._document_body(invoice_xml, invoice_hash, invoice_uuid),
            headers={"Authorization": credentials.authorization(), "Clearance-Status": "0"},
        )
        return self._document_response(response)


__all__ = [
    "ACCEPT_VERSION",
    "Credentials",
    "CsidResponse",
    "FatooraClient",
    "FatooraError",
    "FatooraResponse",
    "Message",
]
