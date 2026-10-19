# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The KSeF API 2.0, the calls this platform needs and nothing more.

Every call is in the Ministry's OpenAPI document and guides
(https://github.com/CIRFMF/ksef-docs, ``open-api.json``, read 2026-10-19):

* ``POST /auth/challenge``                         a challenge, valid 10 minutes
* ``POST /auth/ksef-token``                        token authentication (until 2026-12-31)
* ``POST /auth/xades-signature``                   signed ``AuthTokenRequest`` (certificates)
* ``GET  /auth/{ref}``                             authentication status
* ``POST /auth/token/redeem``                      access and refresh tokens
* ``GET  /security/public-key-certificates``       the Ministry's encryption keys
* ``POST /sessions/online``                        open an interactive session (FA (3), 1-0E, FA)
* ``POST /sessions/online/{ref}/invoices``         send one encrypted invoice
* ``POST /sessions/online/{ref}/close``            close the session
* ``GET  /sessions/{ref}/invoices/{invoiceRef}``   invoice status, KSeF number
* ``GET  /sessions/{ref}/invoices/{invoiceRef}/upo`` the UPO (official receipt), XML

The transport is injectable and the tests use :class:`httpx.MockTransport`.
Nothing in the test suite reaches KSeF.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from xml.sax.saxutils import escape

import httpx

from app.modules.einvoice_ksef import crypto
from app.modules.einvoice_ksef.facts import ENVIRONMENTS, FA3, Environment

DEFAULT_TIMEOUT = 30.0
AUTH_NAMESPACE = "http://ksef.mf.gov.pl/auth/token/2.0"

USAGE_TOKEN = "KsefTokenEncryption"
USAGE_SYMMETRIC = "SymmetricKeyEncryption"

# Status codes of an invoice in a session (open-api.json).
STATUS_ACCEPTED_FOR_PROCESSING = 100
STATUS_PROCESSING = 150
STATUS_SUCCESS = 200
IN_PROGRESS_CODES = frozenset({STATUS_ACCEPTED_FOR_PROCESSING, STATUS_PROCESSING})

# Signs an AuthTokenRequest document with XAdES and returns the signed XML.
XadesSigner = Callable[[str], Awaitable[str]]


class KsefApiError(RuntimeError):
    """KSeF answered with an error, or did not answer."""

    def __init__(self, message: str, *, status: int = 0, code: str = "", details: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.details = details


def _error_from(response: httpx.Response) -> KsefApiError:
    code = ""
    message = response.text[:500]
    details: Any = None
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        exception = body.get("exception") if isinstance(body.get("exception"), dict) else None
        if exception is not None:
            items = exception.get("exceptionDetailList") or []
            first = items[0] if items and isinstance(items[0], dict) else {}
            code = str(first.get("exceptionCode") or "")
            message = str(first.get("exceptionDescription") or message)
            details = items
        else:
            code = str(body.get("code") or body.get("status") or "")
            message = str(body.get("detail") or body.get("title") or message)
            details = body.get("errors") or body.get("details")
    return KsefApiError(
        f"KSeF answered {response.status_code}{f' ({code})' if code else ''}: {message}",
        status=response.status_code,
        code=code,
        details=details,
    )


@dataclass(frozen=True)
class AccessTokens:
    access_token: str
    refresh_token: str
    valid_until: str = ""


@dataclass(frozen=True)
class OpenSession:
    reference: str
    valid_until: str
    key: crypto.SessionKey


@dataclass(frozen=True)
class InvoiceStatus:
    code: int
    description: str
    ksef_number: str
    details: tuple[str, ...]
    invoicing_mode: str
    upo_download_url: str
    raw: dict[str, Any]

    @property
    def in_progress(self) -> bool:
        return self.code in IN_PROGRESS_CODES

    @property
    def succeeded(self) -> bool:
        return self.code == STATUS_SUCCESS


def environment(key: str) -> Environment:
    found = ENVIRONMENTS.get((key or "").strip().lower())
    if found is None:
        raise KsefApiError(f"{key!r} is not a KSeF environment; use one of {', '.join(ENVIRONMENTS)}")
    return found


def auth_token_request_xml(*, challenge: str, context_type: str, context_value: str, subject: str) -> str:
    """The unsigned ``AuthTokenRequest`` a XAdES signer signs."""
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<AuthTokenRequest xmlns="{AUTH_NAMESPACE}">\n'
        f"    <Challenge>{escape(challenge)}</Challenge>\n"
        f"    <ContextIdentifier>\n        <{context_type}>{escape(context_value)}</{context_type}>\n"
        "    </ContextIdentifier>\n"
        f"    <SubjectIdentifierType>{escape(subject)}</SubjectIdentifierType>\n"
        "</AuthTokenRequest>"
    )


class KsefClient:
    """One registration's conversation with KSeF."""

    def __init__(
        self,
        env: Environment,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        poll_attempts: int = 10,
        poll_interval: float = 1.0,
    ) -> None:
        self.env = env
        self._transport = transport
        self._timeout = timeout
        self._sleep = sleep
        self._poll_attempts = poll_attempts
        self._poll_interval = poll_interval
        self._keys: list[dict[str, Any]] | None = None

    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.env.api_base_url, transport=self._transport, timeout=self._timeout)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        bearer: str = "",
        json: Any = None,
        content: str | bytes | None = None,
        content_type: str = "",
        accept_xml: bool = False,
    ) -> httpx.Response:
        headers = {"Accept": "application/xml" if accept_xml else "application/json"}
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        if content_type:
            headers["Content-Type"] = content_type
        try:
            async with self._http() as http:
                response = await http.request(method, path, headers=headers, json=json, content=content)
        except httpx.HTTPError as exc:
            raise KsefApiError(f"KSeF could not be reached: {exc}") from exc
        if response.status_code >= 400:
            raise _error_from(response)
        return response

    # ── keys ────────────────────────────────────────────────────────────
    async def public_key(self, usage: str) -> tuple[Any, str]:
        """``(RSA public key, publicKeyId)`` for one usage, from the Ministry's list."""
        if self._keys is None:
            self._keys = list((await self._request("GET", "/security/public-key-certificates")).json() or [])
        for entry in self._keys:
            if usage in (entry.get("usage") or []):
                return crypto.public_key_from_certificate(entry["certificate"]), str(entry.get("publicKeyId") or "")
        raise KsefApiError(f"KSeF published no public key for {usage}")

    # ── authentication ──────────────────────────────────────────────────
    async def challenge(self) -> dict[str, Any]:
        return (await self._request("POST", "/auth/challenge")).json()

    async def _finish_auth(self, init: dict[str, Any]) -> AccessTokens:
        reference = str(init.get("referenceNumber") or "")
        auth_token = str((init.get("authenticationToken") or {}).get("token") or "")
        if not reference or not auth_token:
            raise KsefApiError("KSeF did not return an authentication reference")
        for attempt in range(self._poll_attempts):
            status = (await self._request("GET", f"/auth/{reference}", bearer=auth_token)).json()
            code = int((status.get("status") or {}).get("code") or 0)
            if code == STATUS_SUCCESS:
                break
            if code not in IN_PROGRESS_CODES:
                description = (status.get("status") or {}).get("description") or "authentication failed"
                raise KsefApiError(f"KSeF refused the authentication: {description}", code=str(code))
            if attempt + 1 < self._poll_attempts:
                await self._sleep(self._poll_interval)
        else:
            raise KsefApiError("KSeF did not finish the authentication in time; try again")
        tokens = (await self._request("POST", "/auth/token/redeem", bearer=auth_token)).json()
        access = tokens.get("accessToken") or {}
        refresh = tokens.get("refreshToken") or {}
        return AccessTokens(
            str(access.get("token") or ""), str(refresh.get("token") or ""), str(access.get("validUntil") or "")
        )

    async def authenticate_with_token(self, *, token: str, context_type: str, context_value: str) -> AccessTokens:
        """Token authentication. KSeF accepts tokens until 2026-12-31."""
        challenge = await self.challenge()
        key, key_id = await self.public_key(USAGE_TOKEN)
        timestamp_ms = int(challenge.get("timestampMs") or 0)
        body: dict[str, Any] = {
            "challenge": challenge["challenge"],
            "contextIdentifier": {"type": context_type, "value": context_value},
            "encryptedToken": crypto.encrypt_token(key, token, timestamp_ms),
        }
        if key_id:
            body["publicKeyId"] = key_id
        init = (await self._request("POST", "/auth/ksef-token", json=body)).json()
        return await self._finish_auth(init)

    async def authenticate_with_xades(
        self, *, signer: XadesSigner, context_type: str, context_value: str, subject: str = "certificateSubject"
    ) -> AccessTokens:
        """Certificate authentication: the signer signs the AuthTokenRequest."""
        challenge = await self.challenge()
        unsigned = auth_token_request_xml(
            challenge=str(challenge["challenge"]),
            context_type=context_type,
            context_value=context_value,
            subject=subject,
        )
        signed = await signer(unsigned)
        init = (
            await self._request(
                "POST", "/auth/xades-signature", content=signed.encode("utf-8"), content_type="application/xml"
            )
        ).json()
        return await self._finish_auth(init)

    # ── sessions ────────────────────────────────────────────────────────
    async def open_session(self, tokens: AccessTokens) -> OpenSession:
        key = crypto.SessionKey.generate()
        public, key_id = await self.public_key(USAGE_SYMMETRIC)
        encryption: dict[str, Any] = {
            "encryptedSymmetricKey": base64.b64encode(crypto.oaep_encrypt(public, key.key)).decode("ascii"),
            "initializationVector": base64.b64encode(key.iv).decode("ascii"),
        }
        if key_id:
            encryption["publicKeyId"] = key_id
        body = {
            "formCode": {"systemCode": FA3.system_code, "schemaVersion": FA3.schema_version, "value": FA3.form_value},
            "encryption": encryption,
        }
        opened = (await self._request("POST", "/sessions/online", bearer=tokens.access_token, json=body)).json()
        return OpenSession(str(opened["referenceNumber"]), str(opened.get("validUntil") or ""), key)

    async def send_invoice(
        self,
        tokens: AccessTokens,
        session: OpenSession,
        xml_bytes: bytes,
        *,
        offline_mode: bool = False,
        hash_of_corrected_invoice: str = "",
    ) -> str:
        """Send one invoice; returns its reference in the session."""
        encrypted = crypto.encrypt_document(xml_bytes, session.key)
        plain_meta, encrypted_meta = crypto.metadata(xml_bytes), crypto.metadata(encrypted)
        body: dict[str, Any] = {
            "invoiceHash": plain_meta.sha256_b64,
            "invoiceSize": plain_meta.size,
            "encryptedInvoiceHash": encrypted_meta.sha256_b64,
            "encryptedInvoiceSize": encrypted_meta.size,
            "encryptedInvoiceContent": base64.b64encode(encrypted).decode("ascii"),
            "offlineMode": bool(offline_mode),
        }
        if hash_of_corrected_invoice:
            body["hashOfCorrectedInvoice"] = hash_of_corrected_invoice
        sent = await self._request(
            "POST", f"/sessions/online/{session.reference}/invoices", bearer=tokens.access_token, json=body
        )
        return str(sent.json()["referenceNumber"])

    async def close_session(self, tokens: AccessTokens, session_reference: str) -> None:
        await self._request("POST", f"/sessions/online/{session_reference}/close", bearer=tokens.access_token)

    async def invoice_status(
        self, tokens: AccessTokens, session_reference: str, invoice_reference: str
    ) -> InvoiceStatus:
        raw = (
            await self._request(
                "GET", f"/sessions/{session_reference}/invoices/{invoice_reference}", bearer=tokens.access_token
            )
        ).json()
        status = raw.get("status") or {}
        return InvoiceStatus(
            code=int(status.get("code") or 0),
            description=str(status.get("description") or ""),
            ksef_number=str(raw.get("ksefNumber") or ""),
            details=tuple(str(d) for d in (status.get("details") or [])),
            invoicing_mode=str(raw.get("invoicingMode") or ""),
            upo_download_url=str(raw.get("upoDownloadUrl") or ""),
            raw=raw,
        )

    async def invoice_upo(self, tokens: AccessTokens, session_reference: str, invoice_reference: str) -> str:
        """The UPO of one invoice, as the XML KSeF signed."""
        response = await self._request(
            "GET",
            f"/sessions/{session_reference}/invoices/{invoice_reference}/upo",
            bearer=tokens.access_token,
            accept_xml=True,
        )
        return response.text

    async def wait_for_status(
        self, tokens: AccessTokens, session_reference: str, invoice_reference: str, *, attempts: int | None = None
    ) -> InvoiceStatus:
        """Read the status until it leaves processing or the attempts run out."""
        tries = self._poll_attempts if attempts is None else attempts
        status = await self.invoice_status(tokens, session_reference, invoice_reference)
        for _ in range(max(tries - 1, 0)):
            if not status.in_progress:
                break
            await self._sleep(self._poll_interval)
            status = await self.invoice_status(tokens, session_reference, invoice_reference)
        return status


__all__ = [
    "AUTH_NAMESPACE",
    "IN_PROGRESS_CODES",
    "STATUS_SUCCESS",
    "USAGE_SYMMETRIC",
    "USAGE_TOKEN",
    "AccessTokens",
    "InvoiceStatus",
    "KsefApiError",
    "KsefClient",
    "OpenSession",
    "XadesSigner",
    "auth_token_request_xml",
    "environment",
]
